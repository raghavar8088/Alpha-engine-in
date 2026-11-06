"""Checks for the liquidity-sweep versions (PREREGISTRATION_VERSIONS.md).

  1. Registry: 22 versions registered with the intended one-rule changes; the engine itself is not.
  2. The engine at its defaults reproduces the original D9 signal for signal over every session on disk.
  3. Each new mechanism on a hand-built session with a known answer.
  4. An ANTI mirror of a version flips it.
`python -I ls_versions_verify.py` (add --real to also check exit-candle parity of the real run)."""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I leaves the script's folder off sys.path
from ls_common import (HERE, IST, UTC, STRATEGY_REGISTRY, Bar, Market, SignalAction, StrategyContext,  # noqa: E402
                       Timeframe, load_minutes)
from strategy_service.strategies.options_buying.booming_bulls_sweep_versions import LiquiditySweepVersion  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
FAILS, CHECKS = [], [0]


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS[0] += 1
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def session(day: date, spec: dict, base: float) -> list[Bar]:
    t = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
    out = []
    for k in range(75):
        ts = t + timedelta(minutes=5 * k)
        o, h, lo, c = spec.get(ts.strftime("%H:%M"), (base, base, base, base))
        out.append(Bar(symbol="NIFTY", timeframe=Timeframe.M5, ts=ts.astimezone(UTC), open=o, high=h, low=lo, close=c))
    return out


def run(sid_or_cls, bars, params=None):
    cls = STRATEGY_REGISTRY[sid_or_cls] if isinstance(sid_or_cls, str) else sid_or_cls
    strat = cls(params=params or {})
    ctx = StrategyContext(max_bars=500)
    sigs = []
    for b in bars:
        ctx.push(b)
        if len(ctx.bars) < strat.warmup:
            continue
        s = strat.on_bar(ctx)
        if s is not None:
            plan = dict(strat.last_plan) if s.signal in (SignalAction.BUY, SignalAction.SELL) else None
            sigs.append((b.ts.astimezone(IST).strftime("%H:%M"), s.signal.value, s.stop_loss, s.target, s.reasoning, plan))
    return sigs


def entries(sigs):
    return [(x[0], x[1]) for x in sigs if x[1] in ("BUY", "SELL")]


# ── 1. registry ──────────────────────────────────────────────────────────────────────────
want = {
    "bb_ls_v01_pdh_pdl": {"level_types": "pdhl"}, "bb_ls_v02_pdc_only": {"level_types": "pdc"},
    "bb_ls_v03_equal_hl": {"level_types": "eq"}, "bb_ls_v04_1h_swings": {"level_types": "1h"},
    "bb_ls_v05_round_numbers": {"level_types": "pdhl,pdc,eq,1h,round"}, "bb_ls_v06_wick_only": {"max_minutes_beyond": 5},
    "bb_ls_v07_strong_reject": {"min_reject_frac": 2 / 3}, "bb_ls_v08_next_candle": {"confirm": "next"},
    "bb_ls_v09_retest_entry": {"confirm": "retest"}, "bb_ls_v10_mss": {"confirm": "mss"},
    "bb_ls_v11_target_1r": {"reward_risk": 1.0}, "bb_ls_v12_target_3r": {"reward_risk": 3.0},
    "bb_ls_v13_breakeven": {"breakeven_r": 1.0}, "bb_ls_v14_opposite_liq": {"target_mode": "opposite"},
    "bb_ls_v15_no_target": {"target_mode": "none"}, "bb_ls_v16_ema200": {"ema_filter": 200},
    "bb_ls_v17_big_sweeps": {"min_risk_pct": 0.15}, "bb_ls_v18_morning": {"last_entry_minute": 675},
    "bb_ls_v19_afternoon": {"first_entry_minute": 725}, "bb_ls_v20_one_a_day": {"max_trades_per_day": 1},
    "bb_ls_v21_break_retest": {"mode": "break_retest"}, "bb_ls_v22_full_video": {"mode": "both"},
}
base_defaults = LiquiditySweepVersion.Params().model_dump()
for sid, change in want.items():
    cls = STRATEGY_REGISTRY.get(sid)
    if cls is None:
        check(f"1 {sid} registered", False)
        continue
    got = cls.Params().model_dump()
    diff = {k: v for k, v in got.items() if base_defaults.get(k) != v}
    check(f"1 {sid}: exactly one rule changed", diff == change, f"{diff}")
    check(f"1 {sid}: 5-minute, options_intraday", [t.value for t in cls.metadata.timeframes] == ["5m"]
          and cls.metadata.category == "options_intraday")
check("1 the engine itself is not registered", LiquiditySweepVersion not in STRATEGY_REGISTRY.values())

# ── 2. the engine at defaults == the original, every session on disk ─────────────────────
mk = Market(load_minutes())
bars = [b for i in range(len(mk.dates)) for b in mk.candles(i, 5)]
orig = [x[:4] for x in run("bb_liquidity_sweep", bars)]
eng = [x[:4] for x in run(LiquiditySweepVersion, bars)]
check("2 engine at defaults reproduces the original signal for signal (2016-2026)", orig == eng and len(orig) > 1000,
      f"{len(orig)} vs {len(eng)}; first diff "
      f"{next(((a, b) for a, b in zip(orig, eng) if a != b), None)}")

# ── 3. mechanisms on hand-built sessions ──────────────────────────────────────────────────
DA, D1, D2 = date(2026, 2, 27), date(2026, 3, 2), date(2026, 3, 3)
# DA flat; D1 spikes to 24,100 (PDH, a 1-hour swing high) and dips to 23,900 (PDL, 1-hour swing low)
HIST = session(DA, {}, 24000) + session(D1, {"11:00": (24000, 24100, 24000, 24000),
                                              "13:00": (24000, 24000, 23900, 24000)}, 24000)
SWEEP = {"10:00": (24010, 24130, 24005, 24080)}          # sweeps 24,100 and closes back below


def day2(spec, base=24010.0, rest=None):
    """D2 with `spec`; candles after the last spec'd one sit flat at `rest` (default: base)."""
    s = session(D2, spec, base)
    if rest is None:
        return HIST + s
    last = max(i for i, b in enumerate(s) if b.ts.astimezone(IST).strftime("%H:%M") in spec)
    return HIST + s[:last + 1] + session(D2, {}, rest)[last + 1:]


s0 = run("bb_liquidity_sweep", day2(SWEEP, rest=24080))
check("3 baseline: the original shorts the 24,100 sweep at 10:00", entries(s0) == [("10:00", "SELL")], str(entries(s0)))
for sid, expect in (("bb_ls_v01_pdh_pdl", [("10:00", "SELL")]), ("bb_ls_v02_pdc_only", []),
                    ("bb_ls_v03_equal_hl", []), ("bb_ls_v04_1h_swings", [("10:00", "SELL")])):
    got = entries(run(sid, day2(SWEEP, rest=24080)))
    check(f"3 level set {sid}: {expect or 'no trade'}", got == expect, str(got))

# v05: levels clear of round numbers (PDH 24,140, PDL 23,940, PDC 24,040); a sweep of 24,100 only exists as a round number
hist2 = session(DA, {}, 24040) + session(D1, {"11:00": (24040, 24140, 24040, 24040),
                                                "13:00": (24040, 24040, 23940, 24040)}, 24040)
rn = hist2 + session(D2, {"10:00": (24050, 24125, 24045, 24085)}, 24050)[:10] + session(D2, {}, 24085)[10:]
check("3 v05: no level at 24,100 for the original", entries(run("bb_liquidity_sweep", rn)) == [])
got = run("bb_ls_v05_round_numbers", rn)
check("3 v05: the 24,100 round number is swept and traded", entries(got) == [("10:00", "SELL")]
      and any("R100" in n for n, _ in got[0][5]["levels"]), str([(x[0], x[1], x[5] and x[5]["levels"]) for x in got]))

# v06: the sweep candle closes ABOVE 24,100, the next closes back below
two = {"10:00": (24010, 24130, 24005, 24120), "10:05": (24120, 24125, 24070, 24080)}
check("3 v06 baseline: original takes the 2-candle sweep", entries(run("bb_liquidity_sweep", day2(two, rest=24080))) == [("10:05", "SELL")])
check("3 v06: wick-only refuses it", entries(run("bb_ls_v06_wick_only", day2(two, rest=24080))) == [])
check("3 v06: wick-only takes a one-candle sweep", entries(run("bb_ls_v06_wick_only", day2(SWEEP, rest=24080))) == [("10:00", "SELL")])

# v07: close 24,080 is 0.4 of the range from the high (refused); close 24,035 is 0.71 (taken; risk 0.33% fits the band)
check("3 v07: weak rejection refused", entries(run("bb_ls_v07_strong_reject", day2(SWEEP, rest=24080))) == [])
strong = {"10:00": (24010, 24110, 24005, 24035)}
check("3 v07: strong rejection taken", entries(run("bb_ls_v07_strong_reject", day2(strong, rest=24035))) == [("10:00", "SELL")])

# v08: next candle lower -> entry on it; next candle higher -> nothing
nxt = {**SWEEP, "10:05": (24080, 24085, 24050, 24060)}
check("3 v08: next candle closes lower -> short at 10:05", entries(run("bb_ls_v08_next_candle", day2(nxt, rest=24060))) == [("10:05", "SELL")])
up = {**SWEEP, "10:05": (24080, 24095, 24075, 24090)}
check("3 v08: next candle closes higher -> no trade", entries(run("bb_ls_v08_next_candle", day2(up, rest=24090))) == [])

# v09: a retest of 24,100 closing back below within 30 min -> short there; none -> no trade; close above -> cancelled
rt = {**SWEEP, "10:10": (24080, 24102, 24078, 24085)}
got = run("bb_ls_v09_retest_entry", day2(rt, rest=24085))
check("3 v09: retest-and-reject -> short at 10:10", entries(got) == [("10:10", "SELL")], str(entries(got)))
check("3 v09: no retest -> no trade", entries(run("bb_ls_v09_retest_entry", day2(SWEEP, rest=24080))) == [])
bad = {**SWEEP, "10:10": (24080, 24120, 24078, 24110), "10:15": (24110, 24112, 24060, 24070)}
check("3 v09: a close back above cancels", entries(run("bb_ls_v09_retest_entry", day2(bad, rest=24070))) == [])

# v10: the morning sits at 24,060, so the structure (lowest low of the 6 candles before the sweep) is 24,060;
# a close below it within 30 min enters (risk 0.31%); with the original's 24,010 morning the same entry would
# risk 0.56% and be refused by the band
SW60 = {"10:00": (24060, 24120, 24055, 24080)}
ms = {**SW60, "10:05": (24080, 24085, 24045, 24050)}
check("3 v10: close below the pre-sweep low -> short at 10:05",
      entries(run("bb_ls_v10_mss", day2(ms, base=24060, rest=24050))) == [("10:05", "SELL")])
check("3 v10: structure intact for 30 min -> no trade", entries(run("bb_ls_v10_mss", day2(SW60, base=24060, rest=24080))) == [])
check("3 v10: a too-wide structure entry is refused by the risk band",
      entries(run("bb_ls_v10_mss", day2({**SWEEP, "10:05": (24080, 24085, 23995, 24000)}, rest=24000))) == [])

# v11 / v12 targets
for sid, r in (("bb_ls_v11_target_1r", 1), ("bb_ls_v12_target_3r", 3)):
    p = run(sid, day2(SWEEP, rest=24080))[0][5]
    check(f"3 {sid}: target = entry - {r}R", abs(p["target"] - (p["entry"] - r * p["risk"])) < 1e-6)

# v13: +1R reached on 10:05 (low 24,020 <= 24,025.18), 10:10 trades back to entry -> breakeven exit
be = {**SWEEP, "10:05": (24080, 24082, 24020, 24050), "10:10": (24050, 24085, 24045, 24060)}
got = run("bb_ls_v13_breakeven", day2(be, rest=24060))
ex = [x for x in got if x[1] == "EXIT_SHORT"]
check("3 v13: breakeven stop at 10:10", len(ex) == 1 and ex[0][0] == "10:10" and "breakeven" in ex[0][4], str(got))
check("3 v13 baseline: original still holds at 10:10", not any(x[0] == "10:10" for x in run("bb_liquidity_sweep", day2(be, rest=24060))))

# v14: PDC 24,000 is the nearest opposite level at >= 1R below the 24,080 entry
p = run("bb_ls_v14_opposite_liq", day2(SWEEP, rest=24080))[0][5]
check("3 v14: target = PDC 24,000", abs(p["target"] - 24000) < 1e-6, str(p["target"]))

# v15: no target; a 200-point drop is held to the 15:10 square-off candle
drop = {**SWEEP, "11:00": (24080, 24080, 23880, 23880)}
got = run("bb_ls_v15_no_target", day2(drop, rest=23880))
ex = [x for x in got if x[1] == "EXIT_SHORT"]
check("3 v15: no target on the signal, exit at 15:10 square-off", got[0][3] is None and len(ex) == 1
      and ex[0][0] == "15:10" and "square-off" in ex[0][4], str([(x[0], x[1], x[3]) for x in got]))

# v17: a 0.10%-risk sweep is refused, the 0.23%-risk one taken
small = {"10:00": (24010, 24110, 24005, 24090)}
check("3 v17: small sweep refused (original takes it)", entries(run("bb_ls_v17_big_sweeps", day2(small, rest=24090))) == []
      and entries(run("bb_liquidity_sweep", day2(small, rest=24090))) == [("10:00", "SELL")])
check("3 v17: big sweep taken", entries(run("bb_ls_v17_big_sweeps", day2(SWEEP, rest=24080))) == [("10:00", "SELL")])

# v18 / v19 time windows
noon = {"12:00": (24010, 24130, 24005, 24080)}
check("3 v18: morning sweep taken, noon refused", entries(run("bb_ls_v18_morning", day2(SWEEP, rest=24080))) == [("10:00", "SELL")]
      and entries(run("bb_ls_v18_morning", day2(noon, rest=24080))) == [])
check("3 v19: noon sweep taken, morning refused", entries(run("bb_ls_v19_afternoon", day2(noon, rest=24080))) == [("12:00", "SELL")]
      and entries(run("bb_ls_v19_afternoon", day2(SWEEP, rest=24080))) == [])

# v20: one a day
two_sweeps = {**SWEEP, "10:05": (24080, 24080, 23960, 23965),            # target hit
              "11:00": (23990, 23995, 23860, 23930)}                      # PDL swept, reclaimed
check("3 v20 baseline: original takes both", len(entries(run("bb_liquidity_sweep", day2(two_sweeps, base=23990, rest=23930)))) == 2)
check("3 v20: one a day", len(entries(run("bb_ls_v20_one_a_day", day2(two_sweeps, base=23990, rest=23930)))) == 1)

# v21 / v22: 24,100 broken and held 30 min (6 closes above), then a retest closing above -> long
brk = {f"10:{m:02d}": (24110, 24125, 24105, 24120) for m in range(0, 30, 5)}
brk["10:30"] = (24120, 24122, 24095, 24115)
got = run("bb_ls_v21_break_retest", day2(brk, rest=24115))
check("3 v21: breakout-retest long at 10:30", entries(got) == [("10:30", "BUY")], str(entries(got)))
if got:
    p = got[0][5]
    check("3 v21: stop under the retest low + 0.02%", abs(p["stop"] - (24095 - 24115 * 0.0002)) < 1e-6, str(p["stop"]))
check("3 v21: the original never trades a held breakout", entries(run("bb_liquidity_sweep", day2(brk, rest=24115))) == [])
check("3 v21: no sweep trades", entries(run("bb_ls_v21_break_retest", day2(SWEEP, rest=24080))) == [])
check("3 v22: both entries", entries(run("bb_ls_v22_full_video", day2(brk, rest=24115))) == [("10:30", "BUY")]
      and entries(run("bb_ls_v22_full_video", day2(SWEEP, rest=24080))) == [("10:00", "SELL")])
fail = {**{f"10:{m:02d}": (24110, 24125, 24105, 24120) for m in range(0, 30, 5)}, "10:30": (24120, 24122, 24080, 24090)}
check("3 v21: a close back below the level drops the watch", entries(run("bb_ls_v21_break_retest", day2(fail, rest=24090))) == [])

# ── 4. ANTI mirror ────────────────────────────────────────────────────────────────────────
try:
    from app.services.anti_strategies import _make_anti
    anti = _make_anti(STRATEGY_REGISTRY["bb_ls_v01_pdh_pdl"])
    check("4 ANTI of a version flips its entry", entries(run(anti, day2(SWEEP, rest=24080))) == [("10:00", "BUY")])
except Exception as exc:  # noqa: BLE001
    check("4 ANTI importable", False, repr(exc))

if "--real" in sys.argv:
    summ = json.load(open(HERE / "results" / "versions" / "summary.json"))
    for vid, blk in summ["versions"].items():
        check(f"5 {vid}: the strategy's own exit candle equals the 1-minute fill's", blk["parity_mismatches"] == 0,
              str(blk["parity_mismatches"]))

print(f"\n{CHECKS[0] - len(FAILS)}/{CHECKS[0]} checks passed" + (f"; FAILED: {FAILS}" if FAILS else ""))
sys.exit(1 if FAILS else 0)
