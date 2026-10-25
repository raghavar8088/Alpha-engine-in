"""Checks of the simulator on hand-built sessions whose answer is known, plus invariants on the real run.

    python -I backend/research/niftybees_orb_2026_10/orb_verify.py

Prices are paise. The range is 100.00-101.00 (10000-10100) unless a check says otherwise, so the long
trigger is 10101 and the short trigger 9999.
"""

from __future__ import annotations

import random
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orb_engine import Config, Day, Sim, fees, load, make_days, run  # noqa: E402
from app.services.angel_fees import round_trip  # noqa: E402

FAILS: list[str] = []
P = Config()                      # the primary rules
Z = replace(P, slip_bp=0.0)       # no slippage: exact prices in the checks


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def day5(bars: dict[int, tuple[int, int, int, int]], base: int = 10050, orh: int = 10100, orl: int = 10000,
         sig=None) -> Day:
    """A session of 75 five-minute candles, flat at `base`, with `bars` {minute: (o, h, l, c)} overriding."""
    start = np.arange(0, 375, 5)
    o = np.full(75, base); h = o.copy(); l = o.copy(); c = o.copy()
    for m, (a, b, d, e) in bars.items():
        k = m // 5
        o[k], h[k], l[k], c[k] = a, b, d, e
    return Day("2099-01-01", o, h, l, c, start, 5, orh, orl, sig)


def one(cfg: Config, day: Day):
    t, amb = Sim(cfg).run_day(day)
    return t, amb


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    # 1. costs: the inlined fee function is the app's model
    rnd = random.Random(7)
    worst = 0.0
    for _ in range(2000):
        e = rnd.uniform(150, 310); x = e * rnd.uniform(0.97, 1.03); q = rnd.randint(1, 40000); side = rnd.choice([1, -1])
        a = fees(e, x, q, side)
        b = round_trip(e, x, q, "BUY" if side > 0 else "SELL", "INTRADAY").total
        worst = max(worst, abs(a - b))
    check("fees() == angel_fees.round_trip (2,000 random trades)", worst < 0.011, f"max diff {worst}")
    fb = round_trip(270.0, 270.0, 3703, "BUY", "INTRADAY")
    check("Rs10 lakh round trip costs about 4.0 bp", 3.9 < fb.total / (3703 * 270) * 1e4 < 4.1, str(fb.as_dict()))

    # 2. a clean long that reaches its target
    d = day5({15: (10050, 10110, 10040, 10105), 20: (10105, 10330, 10100, 10320)})
    t, _ = one(Z, d)
    check("long: one trade", len(t) == 1)
    if t:
        x = t[0]
        check("long: fills at the trigger 10101", x.entry_fill == 10101, str(x))
        check("long: stop is the range low", x.stop == 10000)
        check("long: target = fill + 2 x (fill - stop) = 10303", x.target == 10303, str(x.target))
        check("long: exits at the target", x.exit_reason == "target" and x.exit_fill == 10303, str(x))
        q = int(1_000_000 // 101.01)
        check("long: Rs10 lakh of units", x.qty == q, f"{x.qty} vs {q}")
        check("long: net = gross - fees", abs(x.net - (q * 2.02 - fees(101.01, 103.03, q, 1))) < 1e-6)

    # 3. with 1 bp slippage the fill is rounded up to the next tick and the target moves with it
    t, _ = one(P, d)
    x = t[0]
    check("slippage: buy-stop fills at ceil(10101 x 1.0001) = 10103", x.entry_fill == 10103, str(x.entry_fill))
    check("slippage: target from the actual fill (10103 + 2 x 103 = 10309)", x.target == 10309, str(x.target))

    # 4. a candle touching both the stop and the target: stop first (worst), target first (best)
    d = day5({15: (10050, 10110, 10040, 10105), 20: (10105, 10400, 9990, 10200)})
    t, amb = one(Z, d)
    check("both in one candle, worst: stop-loss", t and t[0].exit_reason == "stop" and t[0].exit_fill == 10000, str(t))
    check("both in one candle: logged as ambiguous", t and t[0].ambiguous and len(amb) == 1)
    t, _ = one(replace(Z, intrabar="best"), d)
    check("both in one candle, best: target", t and t[0].exit_reason == "target", str(t))

    # 5. the entry candle also reaches the stop (but not the short trigger): worst = entered then stopped
    d = day5({15: (10050, 10150, 10000, 10120)})
    t, _ = one(Z, d)
    check("entry candle reaching the stop, worst: a stop-loss in the same candle",
          len(t) == 1 and t[0].exit_reason == "stop" and t[0].exit_bar == 15, str(t))
    t, _ = one(replace(Z, intrabar="best"), d)
    check("entry candle reaching the stop, best: long still open, out at 15:15",
          len(t) == 1 and t[0].exit_reason == "eod", str(t))

    # 6. a candle triggering both sides: one trade, and it loses
    d = day5({15: (10050, 10150, 9950, 10060)})
    t, _ = one(Z, d)
    check("both triggers in one candle: exactly one trade", len(t) == 1, str(t))
    check("both triggers in one candle, worst: it is stopped", t and t[0].exit_reason == "stop", str(t))

    # 7. a candle that opens beyond the trigger fills at its open
    d = day5({15: (10150, 10160, 10140, 10150)})
    t, _ = one(Z, d)
    check("gap through the buy-stop: fills at the open 10150", t and t[0].entry_fill == 10150 and t[0].entry_level == 10101, str(t))
    t, _ = one(P, d)
    check("gap with slippage: ceil(10150 x 1.0001) = 10152", t and t[0].entry_fill == 10152, str(t))

    # 8. a candle that opens beyond the stop exits at its open
    d = day5({15: (10050, 10110, 10040, 10105), 20: (9980, 9990, 9970, 9985)}, base=10050)
    t, _ = one(Z, d)
    check("gap through the stop: out at the open 9980", t and t[0].exit_fill == 9980 and t[0].exit_reason == "stop", str(t))

    # 9. target fill: trade-through vs touch
    d = day5({15: (10050, 10110, 10040, 10105), 20: (10105, 10303, 10100, 10300)}, base=10200)
    t, _ = one(Z, d)
    check("high exactly at the target: not filled (needs a tick through)", t and t[0].exit_reason != "target", str(t))
    t, _ = one(replace(Z, target_fill="touch"), d)
    check("high exactly at the target, touch rule: filled", t and t[0].exit_reason == "target", str(t))

    # 10. end of day: out at the close of the 15:10-15:15 candle
    d = day5({15: (10050, 10110, 10040, 10105), 355: (10150, 10160, 10140, 10155)}, base=10150)
    t, _ = one(Z, d)
    check("15:15 exit at the 15:10 candle's close", t and t[0].exit_reason == "eod" and t[0].exit_bar == 355
          and t[0].exit_fill == 10155, str(t))
    t, _ = one(P, d)
    check("15:15 exit with slippage: floor(10155 x 0.9999) = 10153", t and t[0].exit_fill == 10153, str(t))

    # 11. entry window: a breakout in the 14:55 candle trades, one in the 15:00 candle does not
    t, _ = one(Z, day5({340: (10050, 10110, 10040, 10105)}))
    check("breakout 14:55-15:00: traded", len(t) == 1 and t[0].entry_bar == 340, str(t))
    t, _ = one(Z, day5({345: (10050, 10110, 10040, 10105)}))
    check("breakout from 15:00: no trade", len(t) == 0, str(t))
    t, _ = one(Z, day5({10: (10050, 10200, 10040, 10105)}))
    check("nothing is walked before 09:30", len(t) == 0, str(t))

    # 12. one trade a day: after a stop-loss the opposite breakout is NOT taken ...
    d = day5({15: (10050, 10110, 10040, 10105), 20: (10105, 10105, 9950, 9960), 25: (9960, 9970, 9800, 9810)},
             base=9810)
    t, _ = one(Z, d)
    check("primary: no reversal after a stop-loss", len(t) == 1, str(t))
    # ... but the stop-and-reverse variant takes it once
    t, _ = one(replace(Z, max_trades=2, reverse=True), d)
    check("reverse variant: long stopped, then short", len(t) == 2 and t[0].side == 1 and t[1].side == -1, str(t))
    if len(t) == 2:
        check("reverse: the short fills at the short trigger 9999", t[1].entry_fill == 9999, str(t[1]))
        check("reverse: the short's stop is the range high", t[1].stop == 10100, str(t[1]))

    # 13. candle-close entry: a close above the range enters at the next candle's open
    cz = replace(Z, entry="close")
    d = day5({15: (10050, 10110, 10040, 10105), 20: (10106, 10120, 10100, 10110)}, sig=(20, 1))
    t, _ = one(cz, d)
    check("close entry: fills at the next candle's open 10106", t and t[0].entry_fill == 10106 and t[0].entry_bar == 20, str(t))

    # 14. the 1-minute walk resolves what a 5-minute candle cannot: target first, then the stop
    o = np.full(375, 10050); h = o.copy(); l = o.copy(); c = o.copy()
    seq = {15: (10050, 10110, 10045, 10108), 20: (10108, 10200, 10100, 10190), 21: (10190, 10310, 10180, 10300),
           22: (10300, 10300, 9990, 10000)}
    for m, (a, b, x_, e) in seq.items():
        o[m], h[m], l[m], c[m] = a, b, x_, e
    o[23:], h[23:], l[23:], c[23:] = 10000, 10000, 10000, 10000
    d1 = Day("2099-01-02", o, h, l, c, np.arange(375), 1, 10100, 10000)
    t1, _ = one(Z, d1)
    s5 = np.arange(0, 375, 5)
    d5 = Day("2099-01-02", o[s5], h.reshape(-1, 5).max(1), l.reshape(-1, 5).min(1), c[s5 + 4], s5, 5, 10100, 10000)
    t5, _ = one(Z, d5)
    check("5-minute walk, worst: the 09:35 candle holds target and stop -> stop", t5 and t5[0].exit_reason == "stop", str(t5))
    check("1-minute walk: the target came first", t1 and t1[0].exit_reason == "target", str(t1))

    # 15. invariants on the real data, primary rules, 5- and 1-minute walks
    data = load(Path(__file__).resolve().parent / "data")
    for bars in (5, 1):
        cfg = replace(P, bars=bars)
        r = run(cfg, data)
        tr = r["trades"]
        per_day: dict[str, int] = {}
        for x in tr:
            per_day[x.date] = per_day.get(x.date, 0) + 1
        check(f"real data ({bars}m): at most one trade a day", max(per_day.values()) == 1)
        check(f"real data ({bars}m): entries 09:30-14:59", all(15 <= x.entry_bar < 345 for x in tr))
        check(f"real data ({bars}m): exits by 15:15", all(x.exit_bar < 360 and x.exit_reason for x in tr))
        rec = {d: data["opening"][d] for d in data["days"]}
        ok = all((x.stop == round(rec[x.date]["orl"] * 100)) if x.side > 0 else (x.stop == round(rec[x.date]["orh"] * 100))
                 for x in tr)
        check(f"real data ({bars}m): every stop is the other side of the cleaned range", ok)
        ok = all(abs(abs(x.target - x.entry_fill) - 2 * abs(x.entry_fill - x.stop)) <= 1 for x in tr)
        check(f"real data ({bars}m): every target is 2R from the fill (to a tick)", ok)
        ok = all(abs(x.net - (x.gross - x.fees)) < 1e-6 for x in tr)
        check(f"real data ({bars}m): net = gross - fees on every trade", ok)
        ok = all((x.exit_reason != "target") or (x.exit_fill == x.target) for x in tr)
        check(f"real data ({bars}m): targets fill at the target price", ok)
    print()
    print("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
