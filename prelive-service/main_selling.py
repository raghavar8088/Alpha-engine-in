"""Pre-Live paper desk daemon for option SELLING.

Loop:
  - Sleeps outside market hours; wakes at 09:15 IST Mon-Fri.
  - At open: reloads the qualified selling basket from the latest selling sweep,
    bootstraps warmup history, re-marks any structure carried in from previous
    sessions, resets the day's circuit breaker.
  - Every POLL_SECONDS: one batched Dhan quote request covering NIFTY spot plus every
    leg of every open structure; rolls spot into bars; drives strategies on finalized
    bars; re-marks and risk-checks every open structure; snapshots equity.
  - At 15:20 IST: squares off the intraday styles ONLY, writes the day's P&L, and
    leaves swing/positional structures open to be picked up tomorrow.

Paper only — no real Dhan orders are ever placed. Premiums are the REAL live option
LTPs of every leg.

WHAT IS DIFFERENT FROM THE BUYING DAEMON, AND WHY
-------------------------------------------------
The buying desk is flat by 15:15 every day, so its daemon can treat a session as a
closed world. The qualified selling basket is dominated by swing strategies that hold
for ~7 days, which changes three things structurally:

  * POSITIONS SURVIVE THE PROCESS. Structures are restored from Mongo at startup, and
    a restart mid-hold is a normal event rather than an incident.
  * POSITIONS SURVIVE GAPS. The first marks of each morning price a book that last
    traded ~17.5 hours ago, and risk controls are evaluated on those marks before any
    new entry is considered — the desk checks what the gap did to it before it does
    anything else.
  * EOD SQUARE-OFF IS STYLE-DEPENDENT. Squaring off swing structures nightly would
    destroy the exact edge the sweep measured (theta accrues in days) and would turn
    every 7-day strategy back into the intraday strategy that demonstrably loses money.

Run as its own long-lived process:  python main_selling.py
Runs alongside the buying desk's `main.py`; they share nothing but the Dhan feed and
the instruments collection.
"""

import time
from datetime import datetime, timedelta, timezone

from angel_feed import FailoverFeed
from db_selling import bars_collection
from main import DhanFeed, bucket_start  # feed wrapper + bar bucketing, debugged in prod
from prelive_selling_engine import PreLiveSellingEngine

from tradingai_shared.domain import Bar, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY_SPOT_SECURITY = 13
NIFTY_SPOT_SEGMENT = "IDX_I"
POLL_SECONDS = 15
MARKET_OPEN = 9 * 60 + 15
MARKET_CLOSE = 15 * 60 + 30
SESSION_END = 15 * 60 + 20
# Swing entries read 15m bars; positional strategies read the daily bar, which is only
# finalized at the close — so the daily slot is driven once per session, at the end.
TIMEFRAMES = ["15m"]


def ist_now():
    return datetime.now(IST)


def ist_minutes(dt=None):
    dt = dt or ist_now()
    return dt.hour * 60 + dt.minute


def market_open_now() -> bool:
    n = ist_now()
    return n.weekday() < 5 and MARKET_OPEN <= ist_minutes(n) < MARKET_CLOSE


def bootstrap_history(engine: PreLiveSellingEngine) -> None:
    """Warm every strategy in the basket from stored bars so it can signal from the
    first live bar of the session rather than waiting ~90 bars into the day."""
    for tf in set(tf for _, tf in engine.universe):
        limit = 400 if tf != "1d" else 600
        recent = list(bars_collection.find(
            {"symbol": "NIFTY", "timeframe": tf}).sort("ts", -1).limit(limit))
        recent.reverse()
        for sid, stf in engine.universe:
            if stf != tf:
                continue
            ctx = engine.contexts.get(f"{sid}@{tf}")
            if ctx is None:
                continue
            ctx.bars.clear()
            for d in recent:
                ctx.push(Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=d["ts"],
                             open=d["open"], high=d["high"], low=d["low"],
                             close=d["close"], volume=d.get("volume", 0)))
    print(f"[selling] bootstrapped warmup history for {len(engine.universe)} strategy slots",
          flush=True)


def open_leg_ids(engine: PreLiveSellingEngine) -> list[int]:
    """Every leg of every open structure, for the batched quote request.

    int() is load-bearing — Mongo stores security_id as a string and Dhan's marketfeed
    rejects string ids with HTTP 400, which is exactly what blinded the buying desk the
    moment its first positions opened (2026-07-20).
    """
    return [int(leg.security_id) for pos in engine.positions.values() for leg in pos.legs]


def run_session(engine: PreLiveSellingEngine, feed: DhanFeed) -> None:
    print(f"[selling] session start {ist_now():%Y-%m-%d %H:%M} IST", flush=True)
    engine.new_session()
    bootstrap_history(engine)

    carried = len(engine.positions)
    if carried:
        print(f"[selling] carrying {carried} structure(s) in from previous sessions — "
              f"re-marking against the overnight gap before any new entry", flush=True)
        # Price the carried book FIRST. If a gap has already breached a stop, that must
        # be acted on before the desk even thinks about opening something new.
        feed.prefetch({NIFTY_SPOT_SEGMENT: [NIFTY_SPOT_SECURITY], "NSE_FNO": open_leg_ids(engine)})
        for ev in engine.manage_open(feed.ltp):
            print(f"[CLOSE-GAP] {ev['key']} {ev['exit_reason']} pnl Rs{ev['pnl']:+,.0f} "
                  f"| {ev['structure']}", flush=True)

    forming = {tf: None for tf in TIMEFRAMES}
    last_finalized = {tf: None for tf in TIMEFRAMES}
    last_equity_snap = 0.0
    ticks_ok = ticks_blocked = 0
    last_tick_log = 0.0

    while market_open_now() and ist_minutes() < SESSION_END:
        feed.prefetch({NIFTY_SPOT_SEGMENT: [NIFTY_SPOT_SECURITY], "NSE_FNO": open_leg_ids(engine)})
        spot = feed.spot()
        now = ist_now()
        if spot:
            ticks_ok += 1
        else:
            ticks_blocked += 1

        if time.time() - last_tick_log > 300:
            last_tick_log = time.time()
            bal = engine.balance()
            print(f"[selling] {now:%H:%M} IST spot={spot} | ticks ok={ticks_ok} "
                  f"blocked={ticks_blocked} | open={len(engine.positions)} "
                  f"margin=Rs{bal['margin_deployed']:,.0f} "
                  f"breaker={'TRIPPED' if engine.breaker_tripped else 'ok'}", flush=True)

        if spot:
            for tf in TIMEFRAMES:
                bs = bucket_start(now, tf)
                cur = forming[tf]
                if cur is None:
                    forming[tf] = [bs, spot, spot, spot, spot]
                elif bs != cur[0]:
                    fin = Bar(symbol="NIFTY", timeframe=Timeframe(tf), ts=cur[0],
                              open=cur[1], high=cur[2], low=cur[3], close=cur[4], volume=0)
                    if last_finalized[tf] != cur[0]:
                        last_finalized[tf] = cur[0]
                        # Breaker is checked once per finalized bar, before any entry is
                        # attempted — it gates the whole bar, not each strategy.
                        blocked = engine.check_breaker(feed.ltp)
                        drove = opened = 0
                        for sid, stf in engine.universe:
                            if stf != tf:
                                continue
                            drove += 1
                            ev = engine.on_bar(sid, tf, fin, feed.ltp)
                            if ev:
                                opened += 1
                                print(f"[OPEN] {ev['key']} {' / '.join(ev['legs'])} "
                                      f"x{ev['lots']}lot credit Rs{ev['credit']:.2f} "
                                      f"margin Rs{ev['margin']:,.0f} ({ev['basis']}) "
                                      f"exp {ev['expiry']}", flush=True)
                        print(f"[BAR] {tf} {cur[0]:%H:%M} close={cur[4]:.2f} drove={drove} "
                              f"opened={opened}{' BREAKER' if blocked else ''}", flush=True)
                    forming[tf] = [bs, spot, spot, spot, spot]
                else:
                    cur[2] = max(cur[2], spot)
                    cur[3] = min(cur[3], spot)
                    cur[4] = spot

        # Risk checks run on EVERY tick, not per finalized bar. A short book can be
        # destroyed inside a 15-minute bar; waiting for the close to check a stop is how
        # a manageable loss becomes an unmanageable one.
        for ev in engine.manage_open(feed.ltp):
            print(f"[CLOSE] {ev['key']} {ev['exit_reason']} pnl Rs{ev['pnl']:+,.0f} "
                  f"| {ev['structure']}", flush=True)

        if time.time() - last_equity_snap > 60:
            engine.snapshot_equity(feed.ltp)
            engine.publish_state(running=True)
            last_equity_snap = time.time()

        time.sleep(POLL_SECONDS * 4 if feed.rate_limited else POLL_SECONDS)

    # --- session end ----------------------------------------------------------
    print(f"[selling] closing session {ist_now():%H:%M}", flush=True)
    feed.prefetch({NIFTY_SPOT_SEGMENT: [NIFTY_SPOT_SECURITY], "NSE_FNO": open_leg_ids(engine)})

    # Drive the daily slot once, on the session's own bar, so positional strategies get
    # exactly one evaluation per day on a finalized daily bar.
    _drive_daily(engine, feed)

    engine.close_session(feed.ltp)
    engine.publish_state(running=False)

    doc = None
    from db_selling import daily_pnl_collection
    doc = daily_pnl_collection.find_one({"session": ist_now().date().isoformat()})
    if doc:
        print(f"[selling] DAY {doc['session']}: net Rs{doc['net_pnl']:+,.0f} "
              f"({doc['trades']} closed, {doc['open_carried']} carried overnight, "
              f"margin Rs{doc['margin_deployed']:,.0f})", flush=True)

    total = ticks_ok + ticks_blocked
    blocked_pct = (100 * ticks_blocked / total) if total else 0
    print(f"[selling] FEED HEALTH: {ticks_ok}/{total} ticks priced "
          f"({blocked_pct:.0f}% blocked; 429={feed.throttled_ticks} 401={feed.auth_failed_ticks})",
          flush=True)
    if doc and doc.get("trades", 0) == 0 and not engine.positions:
        if blocked_pct > 20:
            cause = ("Dhan 401 — this feed's token was rotated out mid-session"
                     if feed.auth_failed_ticks > feed.throttled_ticks
                     else "Dhan rate-limited the account (429)" if feed.throttled_ticks
                     else "the price feed returned no data (see [error]/[warn] above)")
            print(f"[selling] ZERO ACTIVITY because the feed was unusable for "
                  f"{blocked_pct:.0f}% of the session: {cause} — not a strategy decision.",
                  flush=True)
        else:
            dropped = getattr(engine, "dropped_signals", {}) or {}
            n_dropped = sum(dropped.values())
            if n_dropped:
                print(f"[selling] ZERO ACTIVITY but {n_dropped} SELL SIGNAL(S) WERE DROPPED by the "
                      f"execution path: {dropped} — a valid short could not be built into a priced "
                      f"structure (see [selling] SIGNAL DROPPED lines). Execution fault, not a quiet "
                      f"market.", flush=True)
            else:
                print("[selling] ZERO ACTIVITY with a healthy feed and NO dropped signals — no regime "
                      "qualified today (see [BAR] lines for per-bar drove/opened counts). Genuine "
                      "no-trade day, not a fault.", flush=True)


def _drive_daily(engine: PreLiveSellingEngine, feed: DhanFeed) -> None:
    """Give positional strategies their one evaluation of the day, on the session's own
    finalized daily bar built from stored intraday bars."""
    daily_slots = [(sid, tf) for sid, tf in engine.universe if tf == "1d"]
    if not daily_slots:
        return
    today = ist_now().date()
    intraday = list(bars_collection.find({
        "symbol": "NIFTY", "timeframe": "15m",
        "ts": {"$gte": datetime(today.year, today.month, today.day, tzinfo=IST)},
    }).sort("ts", 1))
    if not intraday:
        print("[selling] no intraday bars stored for today — skipping the daily slot", flush=True)
        return
    bar = Bar(symbol="NIFTY", timeframe=Timeframe.D1,
              ts=datetime(today.year, today.month, today.day, tzinfo=IST),
              open=intraday[0]["open"], high=max(b["high"] for b in intraday),
              low=min(b["low"] for b in intraday), close=intraday[-1]["close"], volume=0)
    blocked = engine.check_breaker(feed.ltp)
    opened = 0
    for sid, tf in daily_slots:
        ev = engine.on_bar(sid, tf, bar, feed.ltp)
        if ev:
            opened += 1
            print(f"[OPEN] {ev['key']} {' / '.join(ev['legs'])} x{ev['lots']}lot "
                  f"credit Rs{ev['credit']:.2f} margin Rs{ev['margin']:,.0f} "
                  f"exp {ev['expiry']}", flush=True)
    print(f"[BAR] 1d {today} close={bar.close:.2f} drove={len(daily_slots)} "
          f"opened={opened}{' BREAKER' if blocked else ''}", flush=True)


def main() -> None:
    print("[selling] Pre-Live SELLING paper desk starting — multi-leg credit structures, "
          "margin-sized, real premiums, paper only", flush=True)
    engine = PreLiveSellingEngine()
    bal = engine.balance()
    print(f"[selling] paper account: capital Rs{bal['initial_capital']:,.0f} | "
          f"equity Rs{bal['balance']:,.0f} | margin deployed Rs{bal['margin_deployed']:,.0f}",
          flush=True)
    print(f"[selling] qualified basket: {len(engine.universe)} strategy slots "
          f"(source: {engine.universe_source})", flush=True)
    if not engine.universe:
        print("[selling] WARNING: no qualified selling strategies — run the selling sweep "
              "(POST /api/options/selling/backtest-all) before expecting any trades.",
              flush=True)
    engine.publish_state(running=False)

    while True:
        try:
            # Dhan is the book of record — it is the account the strategies were
            # qualified against. Angel One is a per-tick standby for PRICES only, used
            # for the securities Dhan failed to answer for on that tick. If no Angel
            # credentials are configured the wrapper reports itself unavailable and the
            # desk runs exactly as it would on Dhan alone, so this is inert until
            # someone deliberately enables it.
            feed = FailoverFeed(DhanFeed())  # re-read creds each day; Dhan rotates the token
            if not feed.angel.available:
                print("[selling] standby feed not configured — running on Dhan alone",
                      flush=True)
            if market_open_now():
                run_session(engine, feed)
                while market_open_now():
                    time.sleep(30)
            else:
                n = ist_now()
                mins = ist_minutes(n)
                wait = ("weekend" if n.weekday() >= 5
                        else f"{MARKET_OPEN - mins}min to open" if mins < MARKET_OPEN
                        else "post-close")
                held = len(engine.positions)
                print(f"[selling] market closed ({wait}) - {n:%Y-%m-%d %H:%M} IST"
                      f"{f' | holding {held} structure(s) overnight' if held else ''}",
                      flush=True)
                engine.refresh_universe()
                engine.publish_state(running=False)
                time.sleep(120)
        except KeyboardInterrupt:
            print("[selling] stopped", flush=True)
            break
        except Exception as e:
            print(f"[error] loop: {e} - retrying in 60s", flush=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
