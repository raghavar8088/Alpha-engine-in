"""Verification before any result is read (Phase 5).

    python -I yt_checks.py        # engine unit tests for the new order types + look-ahead truncation tests

The truncation test recomputes every strategy's signals (and exit flags) on data cut at random rows; signals
and flags that end before the cut must be identical to the full-data run.
"""

from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

import yt_markets as M  # noqa: E402
from yt_engine import Engine, Exits, Limits, Signal, run_book  # noqa: E402
from yt_strategies import STRATEGIES, build_bars, exits_for  # noqa: E402
from yt_markets import Bars, Cost, Mkt  # noqa: E402

HERE = Path(__file__).resolve().parent


def synth(rows, half=0.0, slip=0.0, overnight=False):
    n = len(rows)
    o, h, l, c = (np.array([r[i] for r in rows], float) for i in range(4))
    t = 1_700_000_000 + 60 * np.arange(n)
    day = np.zeros(n, np.int32) if not overnight else np.arange(n, dtype=np.int32)
    d0 = np.array([0]) if not overnight else np.arange(n)
    d1 = np.array([n]) if not overnight else np.arange(1, n + 1)
    nd = len(d0)
    m = Mkt("TEST", t, o, h, l, c, np.full(n, half), np.ones(n), np.zeros(n, np.int16), np.zeros(n, np.int16), day, d0, d1,
            np.array(["2026-01-05"] * nd, dtype="datetime64[D]"), np.ones(nd, bool), np.zeros(nd, bool), Cost(half, slip, 0.0))
    m.split_key, m.overnight = "XAUUSD", overnight
    return m


def engine_tests():
    res = {}
    rows = [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (100.2, 101.5, 100, 101.2), (101.2, 104, 101, 103.8), (104, 104, 104, 104)]
    m = synth(rows)
    t, _ = Engine(m).trade(Signal(0, 0, 1, 99.0, entry_stop=101.0, expire_k=4), Exits(target_r=1.0), 4, "T", "V")
    res["stop_entry_fills_at_trigger"] = t is not None and abs(t.entry - 101.0) < 1e-9 and t.entry_k == 2
    res["stop_entry_target"] = t is not None and t.reason == "target"
    # gap through the trigger: fills at the open
    rows2 = [(100, 100, 100, 100), (102, 103, 101.5, 102.5), (102.5, 102.5, 102.5, 102.5)]
    t, _ = Engine(synth(rows2)).trade(Signal(0, 0, 1, 99.0, entry_stop=101.0, expire_k=2), Exits(target_r=5.0), 2, "T", "V")
    res["stop_entry_gap_fills_at_open"] = t is not None and abs(t.entry - 102.0) < 1e-9
    # expiry
    t, why = Engine(synth(rows)).trade(Signal(0, 0, 1, 99.0, entry_stop=101.0, expire_k=1), Exits(target_r=2.0), 4, "T", "V")
    res["stop_entry_expires"] = t is None and why == "stop_entry_not_triggered"
    # OCO: the short side triggers first
    rows3 = [(100, 100, 100, 100), (100, 100.2, 98.5, 98.8), (98.8, 103, 98, 102), (102, 102, 102, 102)]
    lg = Signal(0, 0, 1, 99.0, entry_stop=101.0, expire_k=3)
    lg.alt = Signal(0, 0, -1, 101.0, entry_stop=99.0, expire_k=3)
    t, _ = Engine(synth(rows3)).trade(lg, Exits(target_r=2.0), 3, "T", "V")
    res["oco_first_trigger_wins"] = t is not None and t.side == -1 and t.entry_k == 1
    # OCO: both in the same row -> no trade
    rows4 = [(100, 100, 100, 100), (100, 102, 98, 100), (100, 100, 100, 100)]
    lg = Signal(0, 0, 1, 99.0, entry_stop=101.0, expire_k=2)
    lg.alt = Signal(0, 0, -1, 101.0, entry_stop=99.0, expire_k=2)
    t, why = Engine(synth(rows4)).trade(lg, Exits(target_r=2.0), 2, "T", "V")
    res["oco_same_row_no_trade"] = t is None and why == "oco_both_same_row"
    # limit entry: long limit at 99 fills when price trades down to it
    rows5 = [(100, 100, 100, 100), (100, 100.3, 99.6, 99.8), (99.8, 99.9, 98.9, 99.2), (99.2, 103, 99.1, 102.9), (103, 103, 103, 103)]
    t, _ = Engine(synth(rows5)).trade(Signal(0, 0, 1, 98.0, entry_limit=99.0, expire_k=4, target_px=101.0), Exits(target_r=None), 4, "T", "V")
    res["limit_fills_at_limit"] = t is not None and abs(t.entry - 99.0) < 1e-9 and t.entry_k == 2 and t.reason == "target"
    # exit flags: exit at the open after the flagged bar
    m6 = synth([(100, 100, 100, 100)] * 2 + [(100, 101, 99.5, 100.5), (100.5, 101, 100, 100.8), (100.9, 101, 100.5, 100.7), (100.7, 100.7, 100.7, 100.7)])
    b6 = build_bars(m6, (1,))[1]
    fl = np.zeros(len(b6.c), bool)
    fl[3] = True
    ex = Exits(target_r=None, xbars=b6, xlong=fl, xshort=fl)
    t, _ = Engine(m6).trade(Signal(0, 1, 1, 98.0), ex, 5, "T", "V")
    res["exit_flag_next_open"] = t is not None and t.exit_k == 4 and abs(t.exit - 100.9) < 1e-9 and t.reason == "exit_signal"
    # holding limit
    t, _ = Engine(m6).trade(Signal(0, 1, 1, 98.0), Exits(target_r=None, max_hold=2), 5, "T", "V")
    res["max_hold_exit"] = t is not None and t.exit_k == 4
    # fixed target distance
    t, _ = Engine(synth(rows)).trade(Signal(0, 0, 1, 99.0), Exits(target_r=None, target_abs=1.0), 4, "T", "V")
    res["target_abs"] = t is not None and t.reason == "target" and abs(t.exit - (t.entry + 1.0)) < 1e-9
    # risk unit: R measured on the unit, not the far stop
    t, _ = Engine(synth(rows)).trade(Signal(0, 0, 1, 50.0, info={"risk_unit": 2.0}), Exits(target_r=None, max_hold=3), 4, "T", "V")
    res["risk_unit_r"] = t is not None and abs(t.r_gross - (t.exit - t.entry) / 2.0) < 1e-9
    # overnight: a daily trade can run past its entry day
    rows8 = [(100, 101, 99, 100.5), (100.5, 101, 100, 100.8), (100.8, 102, 100.6, 101.9), (101.9, 104, 101.5, 103.5)]
    m8 = synth(rows8, overnight=True)
    t, _ = Engine(m8).trade(Signal(0, 0, 1, 99.0), Exits(target_r=2.0), 3, "T", "V")
    res["overnight_trade_spans_days"] = t is not None and t.exit_k > t.entry_k and t.reason == "target"
    return {k: bool(v) for k, v in res.items()}


def cut_market(m, n_rows):
    """A copy of m holding its first n_rows rows (partial last day)."""
    d_last = int(m.day[n_rows - 1])
    k = copy.copy(m)
    for f in ("t", "o", "h", "l", "c", "half", "vol", "ist", "ny", "day"):
        setattr(k, f, getattr(m, f)[:n_rows])
    k.d0 = m.d0[:d_last + 1].copy()
    k.d1 = m.d1[:d_last + 1].copy()
    k.d1[-1] = n_rows
    for f in ("date", "prev_ok", "excluded"):
        setattr(k, f, getattr(m, f)[:d_last + 1])
    if hasattr(m, "liquid"):
        k.liquid = m.liquid[:n_rows]
    return k


def tail_market(m, n_days):
    d_from = max(0, m.n_days - n_days)
    a = int(m.d0[d_from])
    k = copy.copy(m)
    for f in ("t", "o", "h", "l", "c", "half", "vol", "ist", "ny"):
        setattr(k, f, getattr(m, f)[a:])
    k.day = (m.day[a:] - d_from).astype(np.int32)
    k.d0, k.d1 = m.d0[d_from:] - a, m.d1[d_from:] - a
    for f in ("date", "prev_ok", "excluded"):
        setattr(k, f, getattr(m, f)[d_from:])
    if hasattr(m, "liquid"):
        k.liquid = m.liquid[a:]
    return k


def sig_key(s):
    return (s.day, s.k, s.side, round(s.stop, 6), None if s.entry_stop is None else round(s.entry_stop, 6),
            None if s.entry_limit is None else round(s.entry_limit, 6))


def lookahead_tests(seed=11):
    rng = random.Random(seed)
    out = {}
    stocks = M.nse_intraday(["RELIANCE", "HDFCBANK", "TATAMOTORS"])
    daily_stocks = [x for x in M.nse_daily() if x.name in ("RELIANCE", "INFY", "TATASTEEL")]
    for sid, st in STRATEGIES.items():
        mk = st.markets[0]
        if mk in ("NSE15", "NSE5"):
            base = stocks[0]
        elif mk == "NSED":
            base = daily_stocks[0]
        else:
            base = M.load(mk)
            if st.kind == "overnight":
                base = copy.copy(base)
                base.overnight = True
        n_days = 900 if base.overnight and base.n_days == len(base.t) else 220
        m = tail_market(base, n_days)
        for v in st.variants:
            tfs = tuple(sorted(set(st.tfs) | {v.sig.get("tf", st.tfs[0])} | ({v.exits["trail_tf"]} if v.exits.get("trail_tf") else set())))
            st._mk = mk
            B = build_bars(m, tfs)
            full = st.fn(m, B, v.sig)
            exf = exits_for(st, v, m, B) if st.exit_fn else None
            ok, tries = True, 0
            for _ in range(3):
                cut = rng.randrange(int(m.d0[min(80, m.n_days - 2)]), len(m.t) - 1)
                mt = cut_market(m, cut)
                Bt = build_bars(mt, tfs)
                part = st.fn(mt, Bt, v.sig)
                a = [sig_key(s) for s in full if s.k < cut - 1]
                b = [sig_key(s) for s in part if s.k < cut - 1]
                tries += 1
                if a != b:
                    ok = False
                    out[f"{sid}|{mk}|{v.tag}|diff"] = [str(x) for x in sorted(set(a) ^ set(b))[:3]]
                    break
                if exf is not None:
                    ext = exits_for(st, v, mt, Bt)
                    nb = int(np.searchsorted(ext.xbars.i1, cut - 1, "left"))
                    if not (np.array_equal(exf.xlong[:nb], ext.xlong[:nb]) and np.array_equal(exf.xshort[:nb], ext.xshort[:nb])):
                        ok = False
                        out[f"{sid}|{mk}|{v.tag}|exit_flags"] = "differ"
                        break
            out[f"{sid}|{mk}|{v.tag}"] = ok
            print(f"look-ahead {sid} {mk} {v.tag}: {'ok' if ok else 'FAIL'} ({len(full)} signals, {tries} cuts)", flush=True)
    return out


if __name__ == "__main__":
    res = {"engine": engine_tests()}
    print("engine:", json.dumps(res["engine"]), flush=True)
    res["lookahead"] = lookahead_tests()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "checks.json").write_text(json.dumps(res, indent=1, default=str))
    bad = [k for k, v in res["engine"].items() if not v] + [k for k, v in res["lookahead"].items() if v is False]
    print("FAILED:", bad if bad else "none")
