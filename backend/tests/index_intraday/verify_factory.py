"""Indian Index Intraday — the Strategy Factory's strategies: the paper engine trades exactly what the catalogue
and the Lab tested. No Mongo, no Angel, no network (real minutes are read from the research folder).

Run:  python backend/tests/index_intraday/verify_factory.py

WIRING     546 strategies on each index; ids round-trip; the family and its exits are registered
SIMULATOR  factory.simulate_day == engine.simulate_day whenever the target is a fixed multiple of the stop
DETECTORS  every factory setup and confirmation runs on real bars without a (swallowed) exception, and fires
LIVE      the live path — today's minutes cut at the decision minute, the engine's 420 days of history, the
           per-bar cache — returns the backtest's entry (minute, side, stop and target distances) and nothing a
           minute earlier (no peek), on every timeframe, higher-timeframe confirmations included
ENGINE     minute-by-minute paper ticks over a real day trade the backtest's trade: entry minute and price,
           exit minute, price and reason
LAB        the Backtesting Lab reproduces the catalogue run's trades (ii_factory.task) over the same window
"""

from __future__ import annotations

import asyncio
import random
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gold_desk"))
from _harness import ROOT, Coll, check, finish, section  # noqa: E402

import numpy as np  # noqa: E402

from app.services.index_intraday import data as DM  # noqa: E402
from app.services.index_intraday import engine as E  # noqa: E402
from app.services.index_intraday import factory as FX  # noqa: E402
from app.services.index_intraday import families as F  # noqa: E402
from app.services.index_intraday.costs import costs_for  # noqa: E402
from app.services.strategy_factory.catalog import FACTORY_BY_ID, FACTORY_CATALOG  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
asyncio.set_event_loop(asyncio.new_event_loop())


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════════════════════
section("WIRING — the factory's strategies, as a family of this module")

check("546 factory strategies, ids SF0001..SF0546", len(FACTORY_CATALOG) == 546 and FACTORY_BY_ID.get("SF0546"))
p = FX.parse_sid("SF0123-NIFTY")
check("a module id names the factory strategy and the index, and round-trips",
      p is not None and p[0].strategy_id == "SF0123" and p[1] == "NIFTY" and FX.sid_for("SF0123", "NIFTY") == "SF0123-NIFTY")
check("ids that are not factory ids are refused", all(FX.parse_sid(x) is None for x in
                                                      ("ii0001", "SF9999-NIFTY", "SF0001-NOPE", "SF0001", None)))
check("the 'sf' family and its eight exit configurations are registered",
      F.FAMILIES.get("sf") is FX.fam_sf and all(f"sf_{tf}" in F.EXITS for tf in FX.TF_MINUTES))
check("only 1m has a maximum hold shorter than the session (the factory's 120 bars = 2 hours)",
      FX.max_hold_minutes("1m") == 120 and all(FX.max_hold_minutes(tf) == 0 for tf in ("5m", "15m", "1h", "4h", "1d")))
check("every strategy's decision window is 300..600 bars (400 on 4h, 230 on 1d) and covers its own min_bars",
      all(s.min_bars <= FX.lookback(s) <= {"4h": 400, "1d": 230}.get(s.timeframe, 600)
          and (s.timeframe == "1d" or FX.lookback(s) >= 300) for s in FACTORY_CATALOG))

# ═════════════════════════════════════════════════════════════════════════════════
section("SIMULATOR — the factory's day = the engine's day when the target is a fixed R multiple")

rng = random.Random(28)
bad = 0
for trial in range(400):
    N = DM.SESSION_MIN
    px = 20000.0
    o, h, l, c = (np.zeros(N) for _ in range(4))
    for m in range(N):
        o[m] = px
        px *= 1 + rng.gauss(0, 0.0007)
        c[m] = px
        h[m] = max(o[m], c[m]) * (1 + abs(rng.gauss(0, 0.0003)))
        l[m] = min(o[m], c[m]) * (1 - abs(rng.gauss(0, 0.0003)))
    k = rng.choice([1.5, 2.0, 3.0])
    sd = rng.uniform(5, 40)
    mins = sorted(rng.sample(range(FX.FIRST_DECISION, E.ENTRY_CUTOFF), 6))
    sides = [rng.choice([-1, 1]) for _ in mins]

    def sf_specs(after, mins=mins, sides=sides, sd=sd, k=k):
        for m, s in zip(mins, sides):
            if m >= after:
                return FX.SFSpec(s, m, "market", stop_dist=sd, target_dist=k * sd)
        return None

    def en_specs(after, mins=mins, sides=sides, sd=sd, o=o):
        for m, s in zip(mins, sides):
            if m >= after:
                return E.EntrySpec(s, m, "market", None, float(o[m]) - s * sd)
        return None
    costs = E.Costs(4.0, 1.0)
    a = FX.simulate_day(o, h, l, c, sf_specs, costs, 4, 0, 0)
    b = E.simulate_day(o, h, l, c, en_specs, E.ExitCfg(target_r=k), 0.0, costs, None, 4, 0)
    # the same target computed two ways (k x distance, k x |entry - stop|) differs in the 12th digit
    if [(t.entry_min, t.exit_min, t.reason) for t in a] != [(t.entry_min, t.exit_min, t.reason) for t in b] or \
            any(abs(x.net_bp - y.net_bp) > 1e-6 for x, y in zip(a, b)):
        bad += 1
check("400 random days, up to 4 trades each: identical entries, exits and reasons; net returns to 1e-6 bp",
      bad == 0, bad)

# ═════════════════════════════════════════════════════════════════════════════════
section("DETECTORS — every factory setup and confirmation runs on real bars (no swallowed error)")

# The factory's detectors and confirmations catch their own exceptions (a bad series must cost one
# signal, not a scan) — which once hid four signature bugs that kept 11 of the 69 hypotheses from
# ever trading: macd() unpacked into three values, session_vwap() called without its session key,
# the RSI detectors reading p["period"], and the PSAR flip comparing directions with prices.
if (DM.DATA / "NIFTY").exists() and (DM.DATA / "NIFTYBEES").exists():
    from app.services.strategy_factory.confirmations import CONFIRMATIONS  # noqa: E402
    from app.services.strategy_factory.detectors import DETECTORS  # noqa: E402
    q = DM._build("NIFTY", DM._read("NIFTY", date(2022, 7, 1), date(2022, 12, 31)))
    qe = DM._build("NIFTYBEES", DM._read("NIFTYBEES", date(2022, 7, 1), date(2022, 12, 31)))
    S5, S1d = FX.Series(q, qe, "5m"), FX.Series(q, qe, "1h")
    raised, fired_by, conf_raised = {}, {}, {}
    for s in FACTORY_CATALOG:
        if s.timeframe not in ("5m", "1h"):
            continue
        S = S5 if s.timeframe == "5m" else S1d
        L = FX.lookback(s)
        for j in range(L, len(S.bars), 11):
            sl = S.bars[j + 1 - L: j + 1]
            try:
                st = DETECTORS[s.detector](sl, s.params)
            except Exception as ex:  # noqa: BLE001
                raised[s.detector] = f"{type(ex).__name__}: {ex}"
                break
            if st is None:
                continue
            fired_by[s.detector] = fired_by.get(s.detector, 0) + 1
            for name, cp in s.confirmations:
                try:
                    CONFIRMATIONS[name](sl, cp, st.side, sl)
                except Exception as ex:  # noqa: BLE001
                    conf_raised[name] = f"{type(ex).__name__}: {ex}"
    used = {s.detector for s in FACTORY_CATALOG if s.timeframe in ("5m", "1h")}
    check(f"all {len(used)} detectors used on 5m / 1h run on NIFTY's real bars without an exception", not raised, raised)
    repaired = {"macd_cross", "macd_histogram", "rsi_regime", "rsi_extreme", "rsi_divergence", "psar_flip", "vwap_reclaim"}
    check("…and the seven repaired ones (MACD x2, RSI x3, PSAR, VWAP reclaim) find their setups again",
          repaired <= set(fired_by), sorted(repaired - set(fired_by)))
    check("every confirmation (volume, RSI, MACD, EMA, VWAP, ADX, ATR, higher timeframe) evaluates without an "
          "exception", not conf_raised, conf_raised)
else:
    print("  SKIP  research data not present")

# ═════════════════════════════════════════════════════════════════════════════════
section("LIVE — the engine's path decides exactly what the backtest decided, never sooner")

HAVE = (DM.DATA / "NIFTY").exists() and (DM.DATA / "NIFTYBEES").exists()
day_epoch = lambda dt: int(datetime(dt.year, dt.month, dt.day, 9, 15, tzinfo=IST).timestamp())  # noqa: E731


def minutes_of(d: DM.Days, i: int) -> dict:
    base = day_epoch(d.dates[i].astype(object))
    return {base + 60 * m: (float(d.o[i, m]), float(d.h[i, m]), float(d.l[i, m]), float(d.c[i, m]), float(d.v[i, m]))
            for m in range(DM.SESSION_MIN)}


def hist_before(d: DM.Days, day, days: int = 420) -> DM.Days:
    """What the engine holds on `day` (datetime64[D]): load_recent(days) minus today."""
    keep = (d.dates < day) & (d.dates >= day - np.timedelta64(days, "D"))
    return DM.Days(d.name, d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep], d.quality)


def live_ctx(d, etf, i, upto):
    dt = d.dates[i].astype(object)
    D = DM.with_today(hist_before(d, d.dates[i]), minutes_of(d, i), dt, upto)
    Et = None
    if etf is not None:
        j = np.nonzero(etf.dates == d.dates[i])[0]
        Et = DM.with_today(hist_before(etf, d.dates[i]), minutes_of(etf, int(j[0])) if len(j) else {}, dt, upto)
    ctx = types.SimpleNamespace(d=D, etf=Et, cache={}, live=True)
    return ctx


def spec_key(s):
    return None if s is None else (s.minute, s.side, round(s.stop_dist, 6), round(s.target_dist, 6))


if not HAVE:
    print("  SKIP  research data not present")
else:
    since, until = date(2021, 9, 1), date(2023, 4, 28)
    rows = DM._read("NIFTY", since, until)
    d = DM._build("NIFTY", rows)
    keep = d.dates <= np.datetime64(until.isoformat())
    d = DM.Days("NIFTY", d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep], d.quality)
    etf = DM._build("NIFTYBEES", DM._read("NIFTYBEES", since, until))
    keep = etf.dates <= np.datetime64(until.isoformat())
    etf = DM.Days("NIFTYBEES", etf.dates[keep], etf.o[keep], etf.h[keep], etf.l[keep], etf.c[keep], etf.v[keep], etf.quality)
    lo = int(np.searchsorted(d.dates, np.datetime64("2023-03-01")))
    ctx_b = FX._Ctx(d, etf, lo)
    # one strategy a timeframe at least, the higher-timeframe users included
    want = ["Engulfing Candle", "Pin Bar at Extreme", "Breakout + Volume + HTF Trend", "Supertrend Flip",
            "VWAP Reclaim + Volume + HTF", "EMA Crossover (fast)", "Inside Bar Breakout", "Fib 61.8% + RSI + HTF Trend"]
    picks = [s for s in FACTORY_CATALOG if s.name.split(" · ")[0] in want]
    compared = mismatch = peeked = none_agree = 0
    tfs_hit = set()
    details = []
    for s in picks:
        day_specs, _x, _mt = FX.fam_sf(ctx_b, {"sf": s.strategy_id})
        found = 0
        for i in range(lo, len(d.dates)):
            sb = day_specs(i)(0)
            if sb is None:
                if i == lo:                                 # a no-signal day: the live path agrees at the cutoff
                    FX._LIVE_CACHE.clear()
                    cl = live_ctx(d, etf, i, E.ENTRY_CUTOFF + 1)
                    sl = FX.fam_sf(cl, {"sf": s.strategy_id})[0](len(cl.d.dates) - 1)(0)
                    none_agree += 1
                    if sl is not None:
                        mismatch += 1
                        details.append((s.name, str(d.dates[i]), "live fired, backtest did not", spec_key(sl)))
                continue
            FX._LIVE_CACHE.clear()
            cl = live_ctx(d, etf, i, sb.minute)
            sl = FX.fam_sf(cl, {"sf": s.strategy_id})[0](len(cl.d.dates) - 1)(0)
            compared += 1
            if spec_key(sl) != spec_key(sb):
                mismatch += 1
                details.append((s.name, str(d.dates[i]), spec_key(sb), spec_key(sl)))
            FX._LIVE_CACHE.clear()
            ce = live_ctx(d, etf, i, sb.minute - 1)
            se = FX.fam_sf(ce, {"sf": s.strategy_id})[0](len(ce.d.dates) - 1)(0)
            # a daily strategy decides on yesterday's bar before the open; the engine waits for its minute
            if se is not None and (se.minute <= sb.minute - 1 or spec_key(se) != spec_key(sb)):
                peeked += 1
                details.append((s.name, str(d.dates[i]), "decided a minute early", spec_key(se)))
            tfs_hit.add(s.timeframe)
            found += 1
            if found >= 2:
                break
    check(f"{compared} first-of-day entries across {len(tfs_hit)} timeframes: the live path returns the same minute, "
          "side, stop and target", compared >= 40 and mismatch == 0 and len(tfs_hit) == 8, details[:6])
    check("…and one minute earlier (the signal bar not yet closed) it returns nothing — no peek", peeked == 0, details[:6])

    # ═════════════════════════════════════════════════════════════════════════════
    section("ENGINE — minute-by-minute paper ticks trade the backtest's trade")

    from app.services import market_calendar  # noqa: E402
    from app.services.index_intraday import paper as P  # noqa: E402

    market_calendar.is_trading_day = lambda *a, **k: True
    P.STATE, P.POS, P.TRADES, P.EQUITY, P.EVENTS = Coll("state"), Coll("pos"), Coll("trades"), Coll("equity"), Coll("events")
    vix = DM._build("INDIAVIX", DM._read("INDIAVIX", since, until))
    # a 5m strategy with a trade mid-morning in the window
    strat = next(s for s in FACTORY_CATALOG if s.name == "Supertrend Flip · 5m")
    costs = costs_for("NIFTY")
    day_specs, _x, mt = FX.fam_sf(ctx_b, {"sf": strat.strategy_id})
    pick = None
    for i in range(lo, len(d.dates)):
        tr = FX.simulate_day(d.o[i], d.h[i], d.l[i], d.c[i], day_specs(i), costs, mt, 0, 0)
        if tr and 30 < tr[0].entry_min < 200:
            pick, bt = i, tr
            break
    check("the backtest finds a day with a mid-morning trade for Supertrend Flip · 5m", pick is not None)
    DAY = d.dates[pick].astype(object)
    hist = {"NIFTY": hist_before(d, d.dates[pick]), "NIFTYBEES": hist_before(etf, d.dates[pick]),
            "INDIAVIX": hist_before(vix, d.dates[pick])}
    jet = np.nonzero(etf.dates == d.dates[pick])[0]
    TODAY = {"NIFTY": minutes_of(d, pick), "NIFTYBEES": minutes_of(etf, int(jet[0])) if len(jet) else {}, "INDIAVIX": {}}
    base = day_epoch(DAY)

    class FakeFeed:
        upto = 0

        def today(self, symbol, now=None):
            return {t: b for t, b in TODAY.get(symbol, {}).items() if t < base + 60 * self.upto}

        def holes(self, symbol, now=None):
            return 0

        async def backfill(self, *a, **k):
            return 0

        def ltp(self, symbol, max_age_s=90):
            if symbol == "NIFTY":
                return float(d.o[pick, min(self.upto, 374)])
            return None

        async def heal(self, *a, **k):
            return {}

    ff = FakeFeed()
    P.feed = ff
    P.load_recent = lambda sym, days=120: hist[sym]
    sid = FX.sid_for(strat.strategy_id, "NIFTY")
    run(P.set_config({"capital": 1_000_000.0, "risk_per_trade_pct": 5.0}))
    run(P.set_deployment(sid, True, "index"))
    for upto in range(1, 376):
        ff.upto = upto
        now = datetime(DAY.year, DAY.month, DAY.day, 9, 15, tzinfo=IST) + timedelta(minutes=upto, seconds=5)
        run(P.engine.tick(now, entries_allowed=True))
    t0 = P.TRADES.docs[0] if P.TRADES.docs else {}
    p0 = next((x for x in P.POS.docs if x.get("sid") == sid), {})
    b0 = bt[0]
    check("paper enters on the backtest's minute at its price (the minute's open plus slippage)",
          p0.get("entry_min") == b0.entry_min and abs(p0.get("fill", 0) - b0.entry_px) < 1e-6,
          (p0.get("entry_min"), b0.entry_min, p0.get("fill"), b0.entry_px))
    stop_b = float(d.o[pick, b0.entry_min]) - b0.side * day_specs(pick)(0).stop_dist
    check("…with the factory's stop and target re-anchored to that fill",
          abs((p0.get("stop") or 0) - stop_b) < 1e-6 and p0.get("target") is not None and p0.get("signal"),
          (p0.get("stop"), stop_b, p0.get("target")))
    check("…and exits on the backtest's minute, at its price, for the same reason",
          t0.get("exit_min") == b0.exit_min and abs(t0.get("exit", 0) - b0.exit_px) < 1e-6 and t0.get("exit_reason") == b0.reason,
          (t0.get("exit_min"), b0.exit_min, t0.get("exit"), b0.exit_px, t0.get("exit_reason"), b0.reason))
    check("paper took the backtest's trades that day, no more", len(P.TRADES.docs) == len(bt), (len(P.TRADES.docs), len(bt)))
    check("the trade carries the factory strategy's name and the pattern that fired",
          t0.get("name") == strat.name and (t0.get("signal") or {}).get("pattern"))
    check("the entry event names the strategy (the page's signal feed reads it)",
          any(e.get("sid") == sid and e["kind"] == "entry" for e in P.EVENTS.docs))

    # ═════════════════════════════════════════════════════════════════════════════
    section("LAB — the Backtesting Lab reproduces the catalogue run")

    sys.path.insert(0, str(ROOT / "backend" / "research" / "index_intraday_2026_10"))
    import ii_factory as G  # noqa: E402
    from app.services.index_intraday import backtest as BT  # noqa: E402

    ids = [s.strategy_id for s in FACTORY_CATALOG if s.name in ("Supertrend Flip · 15m", "Engulfing Candle · 30m",
                                                                 "Pin Bar at Extreme · 1h", "Double Top / Bottom · 1d")]
    _ix, _y, out, _days, _secs = G.task(("NIFTY", 2023, ids))
    diffs = []
    for sf in ids:
        arr = out[sf][0]
        arr = arr[arr["day"] <= np.datetime64("2023-03-31").astype("datetime64[D]").astype(np.int64)]
        lab = BT.run_factory_sync(FX.sid_for(sf, "NIFTY"), date(2023, 1, 1), date(2023, 3, 31))
        a = [(str(np.datetime64(int(t["day"]), "D")), int(t["side"]), int(t["entry"]), int(t["exit"])) for t in arr]
        b = [(t["day"], t["side"], t["entry_min"], t["exit_min"]) for t in lab["trades"]]
        nets = max((abs(float(x["net"]) - y["net_bp"]) for x, y in zip(arr, lab["trades"])), default=0.0)
        if a != b or nets > 0.011 or lab["stats"].get("trades", 0) != len(a):
            diffs.append((FACTORY_BY_ID[sf].name, len(a), len(b), round(nets, 4)))
    check("Q1 2023, four strategies (15m, 30m, 1h, 1d): the Lab's trades are the catalogue run's, trade for trade",
          not diffs, diffs)

finish()
