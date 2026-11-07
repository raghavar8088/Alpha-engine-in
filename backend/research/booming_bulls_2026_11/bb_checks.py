"""Verification before any backtest result is read (Phase 5).

    python -I bb_checks.py            # all checks; writes results/checks.json

1. Engine unit tests on synthetic minutes: next-minute entry at ask/bid + slippage, stop-first when one
   minute touches both, a gap through the stop fills at the open, targets fill at the target, breakeven,
   half-off partials, forced time exits, and that a fill never happens inside the signal bar.
2. Look-ahead (truncation) test for every strategy: signals computed on data cut at a random minute must
   equal the full-data signals that end before the cut.
3. Fidelity: BB-01 V0 signals in September 2025 next to the video's own day-by-day replay
   (setup, direction, stop size only; no outcomes are compared, so the hold-out is not scored here).
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I does not add the script's folder
import numpy as np

from bb_engine import Engine, Exits, Limits, Signal, run_book
from bb_markets import COSTS, CostModel, Minutes, load
from bb_strategies import STRATEGIES, build_bars, signals

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def synth(prices: list[tuple], half=0.5, slip=0.1, comm=0.0) -> Minutes:
    """prices: list of (o, h, l, c) mids, one day, one row per minute."""
    n = len(prices)
    o, h, l, c = (np.array([p[i] for p in prices], float) for i in range(4))
    t = 1_700_000_000 + 60 * np.arange(n)
    m = Minutes("TEST", t, o, h, l, c, np.full(n, half), np.ones(n), np.zeros(n, np.int16), np.zeros(n, np.int16),
                np.zeros(n, np.int32), np.array([0]), np.array([n]), np.array(["2026-01-05"], dtype="datetime64[D]"),
                np.array([True]), np.array([False]), CostModel(half, slip, comm))
    m.split_of = lambda d: "dev"
    return m


def engine_tests() -> dict:
    res = {}
    # long: entry at row 1 open + half + slip = 100 + 0.5 + 0.1 = 100.6; stop 98, target at 2R
    rows = [(100, 100, 100, 100), (100, 101, 99.5, 100.5), (100.5, 106.5, 100.4, 106), (106, 106, 106, 106)]
    m = synth(rows)
    e = Engine(m)
    t, _ = e.trade(Signal(0, 0, 1, 98.0), Exits(target_r=2.0), 3, "T", "V")
    res["long_entry_next_minute_at_ask_plus_slip"] = abs(t.entry - 100.6) < 1e-9 and t.entry_k == 1
    res["long_target_fill_at_target"] = t.reason == "target" and abs(t.exit - (100.6 + 2 * 2.6)) < 1e-9
    # stop-first: one minute touches both
    rows = [(100, 100, 100, 100), (100, 100.2, 99.9, 100), (100, 110, 90, 100), (100, 100, 100, 100)]
    t, _ = Engine(synth(rows)).trade(Signal(0, 0, 1, 98.0), Exits(target_r=2.0), 3, "T", "V")
    res["stop_first_when_both_touched"] = t.reason == "stop"
    # gap through the stop: the minute opens below the stop -> fill at the bid open - slip
    rows = [(100, 100, 100, 100), (100, 100.2, 99.9, 100), (95, 95.5, 94, 95), (95, 95, 95, 95)]
    t, _ = Engine(synth(rows)).trade(Signal(0, 0, 1, 98.0), Exits(target_r=2.0), 3, "T", "V")
    res["gap_through_stop_fills_at_open"] = t.reason == "stop" and abs(t.exit - (95 - 0.5 - 0.1)) < 1e-9
    # short mirror: entry at bid - slip; stop triggered by the ask
    rows = [(100, 100, 100, 100), (100, 100.2, 99.8, 100), (100, 101.6, 99.9, 101), (101, 101, 101, 101)]
    t, _ = Engine(synth(rows)).trade(Signal(0, 0, -1, 102.0), Exits(target_r=2.0), 3, "T", "V")
    res["short_entry_at_bid_minus_slip"] = abs(t.entry - 99.4) < 1e-9
    res["short_stop_on_ask"] = t.reason == "stop"      # ask high 102.1 >= 102
    # time exit at the forced row's close (bid - slip for a long)
    rows = [(100, 100, 100, 100)] + [(100, 100.3, 99.8, 100)] * 5
    t, _ = Engine(synth(rows)).trade(Signal(0, 0, 1, 98.0), Exits(target_r=2.0), 4, "T", "V")
    res["time_exit_at_forced_row"] = t.reason == "time" and t.exit_k == 4 and abs(t.exit - (100 - 0.5 - 0.1)) < 1e-9
    # breakeven: reaches 50% of target, then falls back to entry -> be_stop at entry - slip
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 103.5, 100, 103), (103, 103, 99, 99), (99, 99, 99, 99)]
    t, _ = Engine(synth(rows, half=0.0, slip=0.0)).trade(Signal(0, 0, 1, 97.0), Exits(target_r=2.0, be_at_frac=0.5), 4, "T", "V")
    res["breakeven_moves_stop_to_entry"] = t.reason == "be_stop" and abs(t.exit - 100) < 1e-9
    # partial: half at 1R, the rest stopped at breakeven -> 0.5R
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 103.2, 100, 103), (103, 103, 99, 99), (99, 99, 99, 99)]
    t, _ = Engine(synth(rows, half=0.0, slip=0.0)).trade(Signal(0, 0, 1, 97.0), Exits(target_r=2.0, partial_at_r=1.0), 4, "T", "V")
    res["partial_half_at_1R_then_breakeven"] = abs(t.r_net - 0.5) < 1e-9
    # entry never inside the signal bar: the signal's last row is 2, the fill must be row 3
    rows = [(100, 100, 100, 100)] * 2 + [(100, 100, 100, 100), (101, 101, 101, 101), (101, 101, 101, 101)]
    t, _ = Engine(synth(rows, half=0.0, slip=0.0)).trade(Signal(0, 2, 1, 99.0), Exits(target_r=5.0), 4, "T", "V")
    res["fill_after_signal_bar"] = t.entry_k == 3 and abs(t.entry - 101) < 1e-9
    # entry beyond the stop is rejected
    rows = [(100, 100, 100, 100), (97, 97, 97, 97), (97, 97, 97, 97)]
    t, why = Engine(synth(rows, half=0.0, slip=0.0)).trade(Signal(0, 0, 1, 98.0), Exits(target_r=2.0), 2, "T", "V")
    res["entry_beyond_stop_rejected"] = t is None and why == "entry_beyond_stop"
    # book: one trade a day, a target ends the day
    rows = [(100, 100, 100, 100)] * 3 + [(100, 105, 100, 105)] + [(105, 105, 105, 105)] * 6
    m = synth(rows, half=0.0, slip=0.0)
    S = [Signal(0, 0, 1, 99.0), Signal(0, 5, 1, 104.0)]
    tr, rej = run_book(Engine(m), S, Exits(target_r=2.0), Limits(2, True, True), lambda d: 9, "T", "V")
    res["target_ends_the_day"] = len(tr) == 1 and rej.get("day_closed", 0) == 1
    return {k: bool(v) for k, v in res.items()}


def truncate(m: Minutes, cut: int) -> Minutes:
    d_last = int(m.day[cut - 1])
    d1 = m.d1[:d_last + 1].copy()
    d1[-1] = cut
    return replace(m, t=m.t[:cut], o=m.o[:cut], h=m.h[:cut], l=m.l[:cut], c=m.c[:cut], half=m.half[:cut],
                   vol=m.vol[:cut], ist=m.ist[:cut], ny=m.ny[:cut], day=m.day[:cut], d0=m.d0[:d_last + 1], d1=d1,
                   date=m.date[:d_last + 1], prev_ok=m.prev_ok[:d_last + 1], excluded=m.excluded[:d_last + 1])


def window(m: Minutes, d_from: int, d_to: int) -> Minutes:
    a, z = int(m.d0[d_from]), int(m.d1[d_to - 1])
    return replace(m, t=m.t[a:z], o=m.o[a:z], h=m.h[a:z], l=m.l[a:z], c=m.c[a:z], half=m.half[a:z], vol=m.vol[a:z],
                   ist=m.ist[a:z], ny=m.ny[a:z], day=(m.day[a:z] - d_from).astype(np.int32),
                   d0=m.d0[d_from:d_to] - a, d1=m.d1[d_from:d_to] - a, date=m.date[d_from:d_to],
                   prev_ok=m.prev_ok[d_from:d_to], excluded=m.excluded[d_from:d_to])


def lookahead_tests(seed=7) -> dict:
    rng = random.Random(seed)
    out = {}
    cache = {}
    for sid, st in STRATEGIES.items():
        for mk in st.markets:
            if mk not in cache:
                full = load(mk)
                n = full.n_days
                cache[mk] = window(full, n - 260, n)          # the last ~260 sessions keep this quick
            m = cache[mk]
            tfs = tuple(sorted(set(st.tfs) | {5, 15}))
            other = None
            if sid == "BB-03":
                bn = load("BANKNIFTY")
                nb = bn.n_days
                bnw = window(bn, nb - 260, nb)
                other = (bnw, build_bars(bnw, (5,)))
            B = build_bars(m, tfs)
            for v in st.variants:
                full_sigs = signals(st, m, B, v.sig, other)
                ok = True
                tried = 0
                for _ in range(3):
                    cut = rng.randrange(int(m.d0[60]), len(m.t) - 1)
                    mt = truncate(m, cut)
                    Bt = build_bars(mt, tfs)
                    ot = None
                    if other is not None:
                        # cut BankNifty at the same clock time
                        tcut = m.t[cut - 1]
                        kc = int(np.searchsorted(other[0].t, tcut, "right"))
                        bt = truncate(other[0], kc)
                        ot = (bt, build_bars(bt, (5,)))
                    ts = signals(st, mt, Bt, v.sig, ot)
                    a = [(s.day, s.k, s.side, round(s.stop, 6)) for s in full_sigs if s.k < cut - 1]
                    b = [(s.day, s.k, s.side, round(s.stop, 6)) for s in ts if s.k < cut - 1]
                    tried += 1
                    if a != b:
                        ok = False
                        diff = sorted(set(a) ^ set(b))[:3]
                        out[f"{sid}|{mk}|{v.tag}|diff"] = [str(x) for x in diff]
                        break
                out[f"{sid}|{mk}|{v.tag}"] = ok
                print(f"look-ahead {sid} {mk} {v.tag}: {'ok' if ok else 'FAIL'} ({len(full_sigs)} signals, {tried} cuts)", flush=True)
    return out


VIDEO_SEP_2025 = {  # date -> (setup, side) from the video's replay (REPORT.md); None = no trade
    "2025-09-01": ("B", 1), "2025-09-02": ("R", 1), "2025-09-03": None, "2025-09-04": ("G", -1),
    "2025-09-05": ("B_big", 0), "2025-09-08": ("T", -1), "2025-09-09": None, "2025-09-10": None,
    "2025-09-11": None, "2025-09-12": ("G", -1), "2025-09-15": None, "2025-09-16": ("B", 0),
    "2025-09-17": None, "2025-09-18": ("G", -1), "2025-09-19": ("B", -1), "2025-09-22": ("G", 1),
    "2025-09-23": ("B", -1), "2025-09-24": ("T", 1), "2025-09-25": ("B", -1), "2025-09-26": None,
    "2025-09-29": ("T", 1), "2025-09-30": ("T", 1),
}


def fidelity_bb01() -> dict:
    m = load("NIFTY")
    st = STRATEGIES["BB-01"]
    B = build_bars(m, (5,))
    S = signals(st, m, B, {})
    ours = {}
    for s in S:
        d = str(m.date[s.day])
        if d.startswith("2025-09"):
            k = s.k
            ist = int(m.ist[k]) + 1
            px = float(m.c[k])
            ours[d] = {"setup": s.setup, "side": s.side, "signal_close_ist": f"{ist // 60:02d}:{ist % 60:02d}",
                       "stop_points": round(abs(px - s.stop), 1)}
    rows, same_trade_day, same_setup, same_dir, both_none, dir_known = [], 0, 0, 0, 0, 0
    for d, vid in VIDEO_SEP_2025.items():
        o = ours.get(d)
        if vid is None and o is None:
            both_none += 1
        if vid is not None and o is not None:
            same_trade_day += 1
            same_setup += vid[0].split("_")[0] == o["setup"].split("_")[0]
            dir_known += vid[1] != 0
            same_dir += vid[1] != 0 and vid[1] == o["side"]
        rows.append({"date": d, "video": vid, "ours": o})
    video_days = sum(v is not None for v in VIDEO_SEP_2025.values())
    return {"days": len(VIDEO_SEP_2025), "video_trade_days": video_days, "our_trade_days": len(ours),
            "both_trade": same_trade_day, "both_no_trade": both_none, "same_setup_family": same_setup,
            "direction_stated_and_both_trade": dir_known, "same_direction": same_dir, "rows": rows}


if __name__ == "__main__":
    out = {"engine": engine_tests()}
    print("engine:", json.dumps(out["engine"], default=str), flush=True)
    out["fidelity_bb01_sep2025"] = fidelity_bb01()
    f = out["fidelity_bb01_sep2025"]
    print("fidelity:", {k: v for k, v in f.items() if k != "rows"}, flush=True)
    for r in f["rows"]:
        print("  ", r["date"], "video", r["video"], "| ours", r["ours"])
    if "--no-lookahead" not in sys.argv:
        out["lookahead"] = lookahead_tests()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "checks.json").write_text(json.dumps(out, indent=1, default=str))
    bad = [k for k, v in out["engine"].items() if not v] + [k for k, v in out.get("lookahead", {}).items() if v is False]
    print("FAILED:", bad if bad else "none")
