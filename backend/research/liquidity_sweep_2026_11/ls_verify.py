"""Checks for bb_liquidity_sweep and this harness: hand-built sessions with known answers, the fee
formula against the app's, context-size independence and backfill safety on real candles.
`python -I ls_verify.py` (add --real to also check the real run's parity from results/)."""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I leaves the script's folder off sys.path
from ls_common import (HERE, IST, UTC, STRATEGY_ID, STRATEGY_REGISTRY, Bar, Market, SignalAction,  # noqa: E402
                       StrategyContext, Timeframe, futures_fees, load_minutes)

sys.stdout.reconfigure(encoding="utf-8")
FAILS = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def session(day: date, spec: dict, base: float, minutes: int = 5) -> list[Bar]:
    """A session of flat candles at `base`, with candles overridden by `spec` {"HH:MM": (o, h, l, c)}."""
    bars = []
    t = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
    for k in range(375 // minutes):
        ts = t + timedelta(minutes=k * minutes)
        o, h, lo, c = spec.get(ts.strftime("%H:%M"), (base, base, base, base))
        bars.append(Bar(symbol="NIFTY", timeframe=Timeframe.M5, ts=ts.astimezone(UTC), open=o, high=h, low=lo, close=c))
    return bars


LAST = {}


def run(bars: list[Bar], params: dict | None = None, max_bars: int = 500):
    strat = STRATEGY_REGISTRY[STRATEGY_ID](params=params or {})
    LAST["strategy"] = strat
    ctx = StrategyContext(max_bars=max_bars)
    sigs = []
    for b in bars:
        ctx.push(b)
        if len(ctx.bars) < strat.warmup:
            continue
        s = strat.on_bar(ctx)
        if s is not None:
            sigs.append((b.ts.astimezone(IST).strftime("%m-%d %H:%M"), s.signal.value, s.stop_loss, s.target,
                         s.reasoning, dict(strat.last_plan) if s.signal in (SignalAction.BUY, SignalAction.SELL) else None))
    return sigs


def idx(hhmm: str, minutes: int = 5) -> int:
    h, m = map(int, hhmm.split(":"))
    return (h * 60 + m - (9 * 60 + 15)) // minutes


D1, D2 = date(2026, 3, 2), date(2026, 3, 3)
# previous session: flat at 24,000 with one spike to 24,100 (PDH) and one dip to 23,900 (PDL)
PREV = session(D1, {"11:00": (24000, 24100, 24000, 24000), "13:00": (24000, 24000, 23900, 24000)}, 24000)

# 1. sweep + rejection of PDH in one candle -> short at the close, stop past the wick + 0.02%, target 2R
s = run(PREV + session(D2, {"10:00": (24010, 24130, 24005, 24080), "10:30": (24080, 24080, 23960, 23970)}, 24010)[:20]
        + session(D2, {}, 23970)[20:])
entry = [x for x in s if x[1] == "SELL"]
check("1 one short on the PDH sweep", len(entry) == 1 and entry[0][0] == "03-03 10:00", str(s))
if entry:
    plan = entry[0][5]
    stop = 24130 + 24080 * 0.0002
    check("1 entry at the confirmation close", abs(plan["entry"] - 24080) < 1e-9)
    check("1 stop = sweep high + 0.02%", abs(plan["stop"] - stop) < 1e-6, f"{plan['stop']} vs {stop}")
    check("1 target = 2R", abs(plan["target"] - (24080 - 2 * (stop - 24080))) < 1e-6)
    check("1 PDH is among the swept levels", any("PDH" in n for n, _ in plan["levels"]), str(plan["levels"]))
    check("1 the signal carries stop and target", entry[0][2] == round(stop, 2) and entry[0][3] is not None)
    ex = [x for x in s if x[1] == "EXIT_SHORT"]
    check("1 exits at the 10:30 target candle", len(ex) == 1 and ex[0][0] == "03-03 10:30" and "target" in ex[0][4], str(ex))

# 2. acceptance: 6 candles close above PDH (30 min) -> broken; the later close back below is no trade
spec = {f"10:{m:02d}": (24110, 24125, 24105, 24120) for m in range(0, 30, 5)}
spec["10:30"] = (24120, 24120, 24040, 24050)
s = run(PREV + session(D2, spec, 24010)[:16] + session(D2, {}, 24050)[16:])
check("2 a held breakout is never faded", not any(x[1] in ("BUY", "SELL") for x in s), str(s))

# 2b. 5 candles above then a close back below on the 6th -> still a sweep (inside 30 minutes)
spec = {f"10:{m:02d}": (24110, 24125, 24105, 24120) for m in range(0, 25, 5)}
spec["10:25"] = (24120, 24122, 24060, 24070)
s = run(PREV + session(D2, spec, 24010)[:15] + session(D2, {}, 24070)[15:])
check("2b closing back inside on the 6th candle is a sweep", any(x[1] == "SELL" and x[0] == "03-03 10:25" for x in s), str(s))

# 3. a gap above PDH at the open drops it: later moves around 24,100 never trade it
s = run(PREV + session(D2, {"09:15": (24150, 24160, 24140, 24150), "10:00": (24150, 24150, 24090, 24120),
                            "10:05": (24120, 24130, 24095, 24110)}, 24150)[:20] + session(D2, {}, 24110)[20:])
check("3 a level the gap took is not traded", not any(x[1] in ("BUY", "SELL") for x in s), str(s))

# 4. equal highs: swings 24,060 and 24,065 (within 0.04%), then a sweep to 24,080 closing at 24,050
spec = {"10:00": (24030, 24060, 24030, 24030), "10:30": (24030, 24065, 24030, 24030),
        "11:30": (24030, 24080, 24030, 24050)}
s = run(PREV + session(D2, spec, 24030))
entry = [x for x in s if x[1] == "SELL"]
check("4 equal highs make a level that is traded", len(entry) == 1 and entry[0][0] == "03-03 11:30", str(s))
if entry:
    check("4 the level is EQH at the outer swing", any(n.startswith("EQH") and abs(p - 24065) < 1e-9
                                                     for n, p in entry[0][5]["levels"]), str(entry[0][5]["levels"]))

# 4b. swings 24,060 and 24,075 are 0.062% apart -> not equal, no level, no trade
spec = {"10:00": (24030, 24060, 24030, 24030), "10:30": (24030, 24075, 24030, 24030),
        "11:30": (24030, 24090, 24030, 24050)}
s = run(PREV + session(D2, spec, 24030))
check("4b swings 0.06% apart are not equal highs", not any(x[1] in ("BUY", "SELL") for x in s), str(s))

# 5. risk band: sweep to 24,250 and back to 24,090 = 0.68% risk -> skipped, level used up
s = run(PREV + session(D2, {"10:00": (24010, 24250, 24005, 24090), "11:00": (24090, 24120, 24080, 24090)}, 24010)[:12]
        + session(D2, {"11:00": (24090, 24120, 24080, 24090)}, 24090)[12:])
check("5 a sweep with risk > 0.35% is skipped (and the level is spent)", not any(x[1] in ("BUY", "SELL") for x in s), str(s))

# 6. time window: confirmation candle closing 14:50 -> no trade; one closing 14:45 trades, squared off 15:15
k = idx("14:45") + 1
s = run(PREV + session(D2, {"14:45": (24010, 24130, 24005, 24080)}, 24010)[:k] + session(D2, {}, 24080)[k:])
check("6 the 14:45 candle (closes 14:50) is past the cut-off", not any(x[1] in ("BUY", "SELL") for x in s)
      and len(LAST["strategy"]._levels) < 3, str(s))
k = idx("14:40") + 1
s = run(PREV + session(D2, {"14:40": (24010, 24130, 24005, 24080)}, 24010)[:k] + session(D2, {}, 24080)[k:])
ex = [x for x in s if x[1] == "EXIT_SHORT"]
check("6 entry on the 14:40 candle, square-off on the 15:10 candle", any(x[1] == "SELL" and x[0] == "03-03 14:40" for x in s)
      and len(ex) == 1 and ex[0][0] == "03-03 15:10" and "square-off" in ex[0][4], str(s))

# 7. at most 2 trades a day: PDH, PDC-above and a third high all swept and rejected
prev2 = session(D1, {"11:00": (24000, 24300, 24000, 24000), "11:30": (24000, 24200, 24000, 24000),
                     "13:00": (24000, 24000, 23900, 24000)}, 24100)
spec = {"09:30": (23950, 24110, 23945, 24060), "09:35": (24060, 24060, 23900, 23905),   # PDC 24,100 swept, target
        "10:30": (23950, 24210, 23945, 24150), "10:35": (24150, 24150, 23950, 23955),   # 24,200 (1H) swept, target
        "11:30": (23950, 24310, 23945, 24250)}                                         # PDH 24,300 swept: 3rd
s = run(prev2 + session(D2, spec, 23950))
check("7 the third sweep of the day is not taken", sum(x[1] in ("BUY", "SELL") for x in s) == 2, str([x[:2] for x in s]))

# 8. a long: PDL swept and reclaimed
s = run(PREV + session(D2, {"09:50": (23990, 23995, 23860, 23930)}, 23990))
check("8 PDL sweep + reclaim is a long", any(x[1] == "BUY" and x[0] == "03-03 09:50" for x in s), str(s))

# 9. one candle sweeping a high and a low together is skipped
s = run(PREV + session(D2, {"10:00": (24010, 24130, 23870, 24010)}, 24010))
check("9 a candle that sweeps both sides is skipped", not any(x[1] in ("BUY", "SELL") for x in s), str(s))

# 10. 200-EMA filter: two earlier sessions (150 candles) seed the EMA 300 points below / above; the same
# PDH sweep short is then refused above the EMA and taken below it
hist = session(date(2026, 2, 26), {}, 24000) + session(date(2026, 2, 27), {}, 24000)
for shift, want, label in ((-300, False, "refuses a short above"), (+300, True, "allows a short below")):
    moved = [b.model_copy(update={"open": b.open + shift, "high": b.high + shift, "low": b.low + shift,
                                  "close": b.close + shift}) for b in hist]
    s = run(moved + PREV + session(D2, {"10:00": (24010, 24130, 24005, 24080)}, 24010), {"ema_filter": 200})
    ema = LAST["strategy"]._ema
    check(f"10 EMA filter {label} the 200 EMA", ema is not None and any(x[1] == "SELL" for x in s) == want,
          f"ema={ema} sigs={[x[:2] for x in s]}")
s = run(PREV + session(D2, {"10:00": (24010, 24130, 24005, 24080)}, 24010), {"ema_filter": 200})
check("10 no trade before the EMA has 200 candles", not any(x[1] == "SELL" for x in s))

# 11. fees equal the app's angel_fees.futures_round_trip
try:
    from app.services import angel_fees
    for (e, x, side, on) in [(24000, 24050, 1, date(2026, 5, 4)), (24000, 23950, -1, date(2026, 5, 4)),
                             (17000, 17100, 1, date(2023, 1, 9)), (25000, 24900, -1, date(2025, 1, 6))]:
        mine = futures_fees(e, x, 65, side, on)
        app = angel_fees.futures_round_trip(e, x, 65, "BUY" if side > 0 else "SELL", on=on).total
        check(f"11 fees match angel_fees ({on}, {'long' if side > 0 else 'short'})", abs(mine - app) < 0.02, f"{mine} vs {app}")
except Exception as exc:  # noqa: BLE001
    check("11 angel_fees importable", False, repr(exc))

# 12-13 on real candles: the answer does not depend on the runner's context size, and a first call that
# sees history at once trades nothing in the past
mk = Market(load_minutes())
span = [i for i, d in enumerate(mk.dates) if date(2026, 6, 1) <= d <= date(2026, 7, 31)]
bars = [b for i in span for b in mk.candles(i, 5)]
a = [x[:4] for x in run(bars, max_bars=500)]
b = [x[:4] for x in run(bars, max_bars=90)]
check("12 same signals with a 500- or 90-candle context", a == b and len(a) > 0, f"{len(a)} vs {len(b)}")
strat = STRATEGY_REGISTRY[STRATEGY_ID]()
ctx = StrategyContext(max_bars=500)
for bb in bars[:400]:
    ctx.push(bb)
sig = strat.on_bar(ctx)
check("13 a backfilled first call only acts on the current candle", sig is None or sig.timestamp == bars[399].ts)
check("13 backfill leaves no open position from the past", strat._pos is None or strat._pos["n"] == strat._n)

if "--real" in sys.argv:
    summ = json.load(open(HERE / "results" / "summary.json"))
    for name, blk in summ["runs"].items():
        check(f"14 run {name}: the strategy's own exit candle equals the 1-minute fill's", blk["parity_mismatches"] == 0,
              str(blk["parity_mismatches"]))

print(f"\n{CHECKS - len(FAILS)}/{CHECKS} checks passed" + (f"; FAILED: {FAILS}" if FAILS else ""))
sys.exit(1 if FAILS else 0)
