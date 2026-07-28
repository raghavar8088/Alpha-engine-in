"""Pre-Live paper desk daemon - runs every trading day, automatically.

Loop:
  - Sleeps outside market hours; wakes at 09:15 IST Mon-Fri.
  - At open: reloads the qualified strategy universe from the latest options sweep,
    bootstraps each strategy's warmup history from the `bars` collection, then resets
    the day.
  - Every POLL_SECONDS: fetches the live NIFTY spot quote from Dhan, rolls it into
    5m/15m/1h bars; on each finalized bar drives that timeframe's strategies; re-prices
    open paper positions at their live option LTP (stop/target/EOD); snapshots equity.
  - At 15:20 IST: squares off everything, writes the daily P&L, sleeps to next day.

Paper only - no real Dhan orders are ever placed. Premiums are the REAL live option
LTPs, so the pre-live desk accrues the real-premium forward track record that a
historical backtest can't (expired-contract history is purged by Dhan).

Run as its own long-lived process:  python main.py
(Optionally behind the OS scheduler / nssm so it restarts on reboot.)
"""

import time
from datetime import datetime, timedelta, timezone

import requests

from angel_feed import FailoverFeed
from credentials import get_dhan_access
from db import _db
from prelive_engine import PreLiveEngine, VOL_REGIME_FLOOR_PCT

from tradingai_shared.domain import Bar, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))
DHAN_BASE = "https://api.dhan.co/v2"
NIFTY_SPOT_SECURITY = 13
NIFTY_SPOT_SEGMENT = "IDX_I"
POLL_SECONDS = 15
MARKET_OPEN = 9 * 60 + 15
MARKET_CLOSE = 15 * 60 + 30
SESSION_END = 15 * 60 + 20
TIMEFRAMES = ["5m", "15m", "1h"]
BUCKET_MIN = {"5m": 5, "15m": 15, "1h": 60}
bars_collection = _db["bars"]


def ist_now():
    return datetime.now(IST)


def ist_minutes(dt=None):
    dt = dt or ist_now()
    return dt.hour * 60 + dt.minute


def market_open_now() -> bool:
    n = ist_now()
    return n.weekday() < 5 and MARKET_OPEN <= ist_minutes(n) < MARKET_CLOSE


class DhanFeed:
    def __init__(self):
        self.client_id, self.token = get_dhan_access()
        self.headers = {"access-token": self.token, "client-id": self.client_id,
                        "Content-Type": "application/json", "Accept": "application/json"}
        self._ltp_cache = {}
        self._cache_stamp = 0.0
        self._requested: set = set()   # (sid, seg) covered by the last prefetch batch
        self.rate_limited = False      # last batch got HTTP 429 — loop backs off on this
        self.throttled_ticks = 0       # ticks lost to 429 (account throttled)
        self.auth_failed_ticks = 0     # ticks lost to 401 (token rotated out from under us)
        self._last_429_log = 0.0
        self._last_cred_reload = 0.0

    def _reload_creds(self) -> None:
        """Re-read the (possibly rotated) token from the credential store. Dhan
        allows ONE active token per account, so any re-login elsewhere (the AWS
        backend's proactive refresh) instantly invalidates the token this feed
        captured at construction. On 2026-07-17 that meant 401s for the entire
        session because the feed held its dead token all day. Rate-limited to
        once per 60s so a persistent auth outage doesn't hammer the store."""
        now = time.time()
        if now - self._last_cred_reload < 60:
            return
        self._last_cred_reload = now
        try:
            self.client_id, self.token = get_dhan_access()
            self.headers = {"access-token": self.token, "client-id": self.client_id,
                            "Content-Type": "application/json", "Accept": "application/json"}
            print("[prelive] reloaded Dhan credentials after 401 — picked up rotated token", flush=True)
        except Exception as e:
            print(f"[error] credential reload failed (will retry in 60s): {e}", flush=True)

    def prefetch(self, segment_ids: dict[str, list[int]]) -> None:
        """ONE batched POST per poll tick for every security this cycle needs
        (NIFTY spot + every open position), instead of a request per security.
        Dhan's /marketfeed/ltp accepts up to 1000 ids per segment in one call;
        firing one request per security is what tripped Dhan's per-account rate
        limit (HTTP 429) and — once the account gets throttled — kept it
        throttled. spot()/ltp() read straight out of this batch's cache and do
        NOT fall back to their own single-security calls for anything already
        requested here, so a rate-limited tick costs exactly one request, never
        one-per-security."""
        payload = {seg: sorted({int(i) for i in ids}) for seg, ids in segment_ids.items() if ids}
        self._ltp_cache = {}
        self._requested = {(str(sid), seg) for seg, ids in payload.items() for sid in ids}
        if not payload:
            return
        self._cache_stamp = time.time()
        try:
            r = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=self.headers, json=payload, timeout=10)
            if r.status_code == 401:
                print("[error] Dhan 401 - token expired/invalid (batch fetch)", flush=True)
                self.rate_limited = False
                self.auth_failed_ticks += 1
                self._reload_creds()
                return
            if r.status_code == 429:
                # log at most once every 30s so a sustained account-level block
                # doesn't flood the logs with an identical line every tick
                now = time.time()
                if now - self._last_429_log > 30:
                    self._last_429_log = now
                    print("[warn] Dhan rate-limited (HTTP 429) — backing off; account is throttled, "
                          "not a token problem. Waiting for the limit to lift.", flush=True)
                self.rate_limited = True
                self.throttled_ticks += 1
                return
            if r.status_code != 200:
                print(f"[error] Dhan batch fetch HTTP {r.status_code}: {r.text[:200]}", flush=True)
                self.rate_limited = False
                return
            self.rate_limited = False
            data = r.json().get("data", {})
            for seg, rows in data.items():
                for sid, row in rows.items():
                    self._ltp_cache[(sid, seg)] = row.get("last_price")
        except Exception as e:
            print(f"[warn] batch fetch: {e}", flush=True)
            self.rate_limited = False

    def spot(self) -> float | None:
        return self.ltp(NIFTY_SPOT_SECURITY, NIFTY_SPOT_SEGMENT)

    def ltp(self, security_id, exchange_segment) -> float | None:
        ck = (str(security_id), exchange_segment)
        if ck in self._ltp_cache:
            return self._ltp_cache[ck]
        # Already covered by this tick's batch (present or not) — never make a
        # per-security fallback call, which is exactly what amplified one failed
        # batch back into N rejected requests and kept the account throttled.
        if ck in self._requested:
            return None
        # Only reached for a security not in the last prefetch (e.g. a position
        # opened mid-tick, after prefetch already ran) — single fallback call.
        try:
            r = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=self.headers,
                              json={exchange_segment: [int(security_id)]}, timeout=10)
            if r.status_code != 200:
                return None
            data = r.json().get("data", {}).get(exchange_segment, {})
            price = data.get(str(security_id), {}).get("last_price")
            self._ltp_cache[ck] = price
            return price
        except Exception as e:
            print(f"[warn] ltp fetch {security_id}: {e}", flush=True)
            return None


def bucket_start(now: datetime, tf: str) -> datetime:
    m = BUCKET_MIN[tf]
    anchor = now.replace(hour=9, minute=15, second=0, microsecond=0)
    delta_min = int((now - anchor).total_seconds() // 60)
    return anchor + timedelta(minutes=(delta_min // m) * m)


def bootstrap_history(engine: PreLiveEngine):
    """Warm each strategy in the engine's CURRENT universe with recent finalized bars
    from the DB so it can signal from the first live bar."""
    for tf in TIMEFRAMES:
        recent = list(bars_collection.find(
            {"symbol": "NIFTY", "timeframe": tf}).sort("ts", -1).limit(400))
        recent.reverse()
        for sid, stf in engine.universe:
            if stf != tf:
                continue
            ctx = engine.contexts[f"{sid}@{tf}"]
            ctx.bars.clear()
            for d in recent:
                ctx.push(Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=d["ts"],
                             open=d["open"], high=d["high"], low=d["low"],
                             close=d["close"], volume=d.get("volume", 0)))
    print(f"[prelive] bootstrapped warmup history for {len(engine.universe)} strategy slots", flush=True)


def run_session(engine: PreLiveEngine, feed: DhanFeed):
    print(f"[prelive] session start {ist_now():%Y-%m-%d %H:%M} IST", flush=True)
    engine.new_session()
    bootstrap_history(engine)
    forming = {tf: None for tf in TIMEFRAMES}          # tf -> (bucket_start, o,h,l,c)
    last_finalized = {tf: None for tf in TIMEFRAMES}
    last_equity_snap = 0

    ticks_ok = ticks_blocked = 0
    last_tick_log = 0.0

    while market_open_now() and ist_minutes() < SESSION_END:
        # int() is load-bearing: Mongo stores security_id as a string, and Dhan's
        # marketfeed rejects string IDs with HTTP 400 "814 Invalid Request" — which
        # blinded the desk the moment its first-ever positions opened (2026-07-20).
        open_security_ids = [int(pos.security_id) for pos in engine.positions.values()]
        feed.prefetch({NIFTY_SPOT_SEGMENT: [NIFTY_SPOT_SECURITY], "NSE_FNO": open_security_ids})
        spot = feed.spot()
        now = ist_now()
        # Proof-of-life: without this there is no way to tell "prices are flowing but
        # nothing set up" from "we never got a single price all session" — which is
        # exactly the ambiguity that made a zero-trade day impossible to diagnose.
        if spot:
            ticks_ok += 1
        else:
            ticks_blocked += 1
        if time.time() - last_tick_log > 300:  # every ~5min
            last_tick_log = time.time()
            print(f"[prelive] {now:%H:%M} IST spot={spot} | ticks ok={ticks_ok} blocked={ticks_blocked} "
                  f"| open_pos={len(engine.positions)}", flush=True)
        if spot:
            for tf in TIMEFRAMES:
                bs = bucket_start(now, tf)
                cur = forming[tf]
                if cur is None:
                    forming[tf] = [bs, spot, spot, spot, spot]
                elif bs != cur[0]:
                    # finalize the previous bucket -> drive strategies
                    fin = Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=cur[0],
                              open=cur[1], high=cur[2], low=cur[3], close=cur[4], volume=0)
                    if last_finalized[tf] != cur[0]:
                        last_finalized[tf] = cur[0]
                        drove = opened = 0
                        for sid, stf in engine.universe:
                            if stf != tf:
                                continue
                            drove += 1
                            ev = engine.on_bar(sid, tf, fin, feed.ltp)
                            if ev:
                                opened += 1
                                print(f"[OPEN] {ev['key']} {ev['type']} {ev['strike']:.0f} "
                                      f"x{ev['lots']}lot @Rs{ev['premium']:.2f}", flush=True)
                        # One line per finalized bar proves the evaluation path ran and
                        # says how many strategies it drove — so "0 trades" is always
                        # attributable to a real cause instead of guesswork.
                        print(f"[BAR] {tf} {cur[0]:%H:%M} close={cur[4]:.2f} drove={drove} opened={opened}",
                              flush=True)
                    forming[tf] = [bs, spot, spot, spot, spot]
                else:
                    cur[2] = max(cur[2], spot)
                    cur[3] = min(cur[3], spot)
                    cur[4] = spot

        # manage open paper positions on live option prices
        for ev in engine.manage_open(feed.ltp):
            print(f"[CLOSE] {ev['key']} {ev['exit_reason']} pnl Rs{ev['pnl']:+,.0f}", flush=True)

        # equity snapshot ~ every 60s
        if time.time() - last_equity_snap > 60:
            engine.snapshot_equity(feed.ltp)
            last_equity_snap = time.time()

        # When Dhan has throttled the account, sleeping the normal 15s and
        # re-hitting it keeps the block alive. Back off hard (POLL x4) so the
        # account can recover and the limit lifts; we lose a little bar
        # resolution during the block but that data was unusable anyway.
        time.sleep(POLL_SECONDS * 4 if feed.rate_limited else POLL_SECONDS)

    print(f"[prelive] squaring off + closing session {ist_now():%H:%M}", flush=True)
    engine.close_session(feed.ltp)
    doc = _db["prelive_daily_pnl"].find_one({"session": ist_now().date().isoformat()})
    if doc:
        print(f"[prelive] DAY {doc['session']}: net Rs{doc['net_pnl']:+,.0f} on "
              f"Rs{doc['peak_capital']:,.0f} peak = {doc['roi_pct']}% ({doc['trades']} trades)", flush=True)
    # A zero-trade day must always state WHY. Without this, "0 trades" is
    # indistinguishable between a throttled feed and a genuinely quiet market.
    total = ticks_ok + ticks_blocked
    blocked_pct = (100 * ticks_blocked / total) if total else 0
    failover_prices = getattr(feed, "failover_prices", 0)
    failover_note = f"; Angel-One-covered={failover_prices}" if failover_prices else ""
    print(f"[prelive] FEED HEALTH: {ticks_ok}/{total} ticks got a price "
          f"({blocked_pct:.0f}% blocked/failed; 429-throttled={feed.throttled_ticks} "
          f"401-auth={feed.auth_failed_ticks}{failover_note})", flush=True)
    if doc and doc.get("trades", 0) == 0:
        if blocked_pct > 20:
            # 401 and 429 are different failures with different fixes — a token
            # rotated out from under this feed is NOT a rate limit, and reporting
            # one as the other sends the next investigation down the wrong path.
            if feed.auth_failed_ticks > feed.throttled_ticks:
                cause = ("Dhan returned 401 (the access token this feed was holding got rotated/"
                         "invalidated mid-session — Dhan allows one active token per account)")
            elif feed.throttled_ticks:
                cause = "Dhan rate-limited the account (HTTP 429)"
            else:
                cause = "the price feed returned no data (cause not 401/429 — see [error]/[warn] lines above)"
            print(f"[prelive] ZERO TRADES because the price feed was unusable for {blocked_pct:.0f}% "
                  f"of the session: {cause} — not a strategy decision.", flush=True)
        else:
            dropped = getattr(engine, "dropped_signals", {}) or {}
            n_dropped = sum(dropped.values())
            if n_dropped:
                # Signals fired but could not be turned into orders — this IS a fault to
                # chase, unlike a genuinely quiet market.
                print(f"[prelive] ZERO TRADES but {n_dropped} SIGNAL(S) WERE DROPPED by the "
                      f"execution path: {dropped} — a valid signal could not become an order "
                      f"(see [prelive] SIGNAL DROPPED lines). This is an execution fault, not a "
                      f"quiet market.", flush=True)
            elif getattr(engine, "regime_skips", 0):
                # Signals fired but the desk deliberately stood aside — a healthy no-trade,
                # not a fault and not a dead market.
                print(f"[prelive] ZERO TRADES by design — {engine.regime_skips} signal(s) stood aside "
                      f"in a low-volatility regime (recent NIFTY daily range below "
                      f"{VOL_REGIME_FLOOR_PCT:.2f}%). Buying premium in a flat tape is where this "
                      f"desk's losses came from; standing aside is the intended behaviour.", flush=True)
            else:
                print("[prelive] ZERO TRADES with a healthy feed and NO dropped signals — strategies "
                      "evaluated but none produced a setup today (see [BAR] lines for per-bar "
                      "drove/opened counts). Genuine no-trade day, not a fault.", flush=True)


def main():
    print("[prelive] Pre-Live paper desk daemon starting - dynamic qualified-strategy "
          "universe, real premiums, paper only", flush=True)
    engine = PreLiveEngine()
    bal = engine.balance()
    print(f"[prelive] paper account: starting capital Rs{bal['initial_capital']:,.0f} | "
          f"balance Rs{bal['balance']:,.0f} | available Rs{bal['available_cash']:,.0f}", flush=True)
    print(f"[prelive] qualified universe: {len(engine.universe)} strategy slots "
          f"(source: {engine.universe_source})", flush=True)
    engine.publish_idle_state()
    while True:
        try:
            # Dhan first, Angel One when Dhan can't price a security this tick — the
            # selling desk (main_selling.py) already runs this way; 2026-07-22 was a
            # whole session with zero ticks and zero trades on this desk specifically
            # because it had no standby when Dhan went dark.
            feed = FailoverFeed(DhanFeed())  # re-read creds each day (token rotates)
            if market_open_now():
                run_session(engine, feed)
                # after session, wait past close
                while market_open_now():
                    time.sleep(30)
            else:
                n = ist_now()
                mins = ist_minutes(n)
                if n.weekday() >= 5:
                    wait = "weekend"
                elif mins < MARKET_OPEN:
                    wait = f"{(MARKET_OPEN - mins)}min to open"
                else:
                    wait = "post-close"
                print(f"[prelive] market closed ({wait}) - {n:%Y-%m-%d %H:%M} IST", flush=True)
                engine.publish_idle_state()
                time.sleep(120)
        except KeyboardInterrupt:
            print("[prelive] stopped", flush=True)
            break
        except Exception as e:
            print(f"[error] loop: {e} - retrying in 60s", flush=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
