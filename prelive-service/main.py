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

from credentials import get_dhan_access
from db import _db
from prelive_engine import PreLiveEngine

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

    def prefetch(self, segment_ids: dict[str, list[int]]) -> None:
        """One batched POST per poll tick for every security this cycle needs
        (NIFTY spot + every open position), instead of a separate request per
        security. Dhan's /marketfeed/ltp accepts up to 1000 ids per segment in
        one call; firing one request per security here is what was tripping
        Dhan's per-account rate limit (HTTP 429) as soon as more than a
        handful of positions were open, starving every strategy of a price to
        evaluate against."""
        payload = {seg: sorted(set(ids)) for seg, ids in segment_ids.items() if ids}
        if not payload:
            return
        self._cache_stamp = time.time()
        self._ltp_cache = {}
        try:
            r = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=self.headers, json=payload, timeout=10)
            if r.status_code == 401:
                print("[error] Dhan 401 - token expired/invalid (batch fetch)", flush=True)
                return
            if r.status_code != 200:
                print(f"[error] Dhan batch fetch HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return
            data = r.json().get("data", {})
            for seg, rows in data.items():
                for sid, row in rows.items():
                    self._ltp_cache[(sid, seg)] = row.get("last_price")
        except Exception as e:
            print(f"[warn] batch fetch: {e}", flush=True)

    def spot(self) -> float | None:
        ck = (str(NIFTY_SPOT_SECURITY), NIFTY_SPOT_SEGMENT)
        if ck in self._ltp_cache:
            return self._ltp_cache[ck]
        # fallback single call only if this security wasn't in the last prefetch batch
        try:
            r = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=self.headers,
                              json={NIFTY_SPOT_SEGMENT: [NIFTY_SPOT_SECURITY]}, timeout=10)
            if r.status_code == 401:
                print("[error] Dhan 401 - token expired/invalid (spot fetch)", flush=True)
                return None
            if r.status_code != 200:
                print(f"[error] Dhan spot fetch HTTP {r.status_code}: {r.text[:200]}", flush=True)
                return None
            data = r.json().get("data", {}).get(NIFTY_SPOT_SEGMENT, {})
            price = data.get(str(NIFTY_SPOT_SECURITY), {}).get("last_price")
            self._ltp_cache[ck] = price
            return price
        except Exception as e:
            print(f"[warn] spot fetch: {e}", flush=True)
            return None

    def ltp(self, security_id, exchange_segment) -> float | None:
        ck = (str(security_id), exchange_segment)
        if ck in self._ltp_cache:
            return self._ltp_cache[ck]
        # fallback single call only if this security wasn't in the last prefetch batch
        # (e.g. a brand-new position opened mid-tick, after prefetch already ran)
        try:
            r = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=self.headers,
                              json={exchange_segment: [int(security_id)]}, timeout=10)
            if r.status_code == 401:
                print(f"[error] Dhan 401 - token expired/invalid (ltp fetch {security_id})", flush=True)
                return None
            if r.status_code != 200:
                print(f"[error] Dhan ltp fetch {security_id} HTTP {r.status_code}: {r.text[:200]}", flush=True)
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

    while market_open_now() and ist_minutes() < SESSION_END:
        open_security_ids = [pos.security_id for pos in engine.positions.values()]
        feed.prefetch({NIFTY_SPOT_SEGMENT: [NIFTY_SPOT_SECURITY], "NSE_FNO": open_security_ids})
        spot = feed.spot()
        now = ist_now()
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
                        for sid, stf in engine.universe:
                            if stf != tf:
                                continue
                            ev = engine.on_bar(sid, tf, fin, feed.ltp)
                            if ev:
                                print(f"[OPEN] {ev['key']} {ev['type']} {ev['strike']:.0f} "
                                      f"x{ev['lots']}lot @Rs{ev['premium']:.2f}", flush=True)
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

        time.sleep(POLL_SECONDS)

    print(f"[prelive] squaring off + closing session {ist_now():%H:%M}", flush=True)
    engine.close_session(feed.ltp)
    doc = _db["prelive_daily_pnl"].find_one({"session": ist_now().date().isoformat()})
    if doc:
        print(f"[prelive] DAY {doc['session']}: net Rs{doc['net_pnl']:+,.0f} on "
              f"Rs{doc['peak_capital']:,.0f} peak = {doc['roi_pct']}% ({doc['trades']} trades)", flush=True)


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
            feed = DhanFeed()  # re-read creds each day (token rotates)
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
