"""Independent re-walk of sampled trades (engine verification; no performance is measured here).

For each sampled trade of a strategy's BTC spot run (D:/Strategy-Web-Sources/results/trades/<Class>__BTC_spot.csv) it
re-derives, with a plain minute-by-minute loop written separately from ws_engine.simulate:
  - that an entry signal candle closed exactly at the entry time and the entry price is that minute's open;
  - the exit (minute, price, reason) under freqtrade's exit model as ws_engine documents it.
Any difference is printed. Counts only.

    python -I ws_verify.py [Class,Class,...] [samples per strategy]
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ws_engine as E  # noqa: E402

SIG = Path(r"D:\Strategy-Web-Sources\signals")
TRADES = Path(r"D:\Strategy-Web-Sources\results\trades")


def roi_at(s: dict, el: int) -> float:
    items = sorted((int(float(k)), float(v)) for k, v in (s.get("minimal_roi") or {}).items())
    r = -1.0
    for k, v in items:
        if k <= el:
            r = v
    return r


def rewalk(T0: int, side: int, m: E.Minutes, s: dict, f: float, exit_minutes: set, end_k: int):
    k0 = m.at(T0)
    P0 = m.o[k0]
    sl = float(s.get("stoploss") or -1.0)
    stop0 = P0 * (1 + sl) if side > 0 else P0 * (1 - sl)
    trail, tsp = bool(s.get("trailing_stop")), s.get("trailing_stop_positive")
    tso, only = float(s.get("trailing_stop_positive_offset") or 0.0), bool(s.get("trailing_only_offset_is_reached"))
    po, poff = bool(s.get("exit_profit_only")), float(s.get("exit_profit_offset") or 0.0)
    best = P0
    for k in range(k0, end_k + 1):
        o, h, l = m.o[k], m.h[k], m.l[k]
        if k in exit_minutes and k > k0:
            if not po or side * (o - P0) / P0 - 2 * f > poff:
                return k, o, "EXIT_SIGNAL"
        r = roi_at(s, int((m.t[k] - T0) // 60))
        stop = stop0
        if side > 0:
            if trail:
                if tsp is None:
                    stop = max(stop, best * (1 + sl))
                elif (not only) or (best / P0 - 1 >= tso):
                    stop = max(stop, best * (1 - float(tsp)))
            tgt = np.inf if r < 0 else P0 * (1 + f) * (1 + r) / (1 - f)
            if k > k0 and o <= stop:
                return k, o, "STOP"
            if l <= stop:
                return k, stop, "STOP/TRAIL"
            if k > k0 and o >= tgt:
                return k, o, "ROI"
            if h >= tgt:
                return k, tgt, "ROI"
            best = max(best, h)
        else:
            if trail:
                if tsp is None:
                    stop = min(stop, best * (1 - sl))
                elif (not only) or (1 - best / P0 >= tso):
                    stop = min(stop, best * (1 + float(tsp)))
            tgt = -np.inf if r < 0 else P0 * (1 - f) * (1 - r) / (1 + f)
            if k > k0 and o >= stop:
                return k, o, "STOP"
            if h >= stop:
                return k, stop, "STOP/TRAIL"
            if k > k0 and o <= tgt:
                return k, o, "ROI"
            if l <= tgt:
                return k, tgt, "ROI"
            best = min(best, l)
    return end_k, m.c[end_k], "END"


def main(argv: list[str]) -> None:
    names = argv[0].split(",") if argv else ["BinHV45", "Bandtastic", "MACDStrategy", "CMCWinner", "Quickie", "ClucMay72018"]
    n_s = int(argv[1]) if len(argv) > 1 else 40
    m = E.Minutes("BTC/USDT")
    random.seed(7)
    total = bad = 0
    for name in names:
        sig, s = E.load_signals(SIG, name, "BTC/USDT")
        tf = int(sig["tf"]) * 60
        known = sig["t"].astype(np.int64) + tf
        el, xl = sig["enter_long"].astype(bool), sig["exit_long"].astype(bool)
        es, xs = sig["enter_short"].astype(bool), sig["exit_short"].astype(bool)
        flt = sig["filled"].astype(bool)
        entry_known = {1: set(known[el & ~es & ~flt].tolist()), -1: set(known[es & ~el & ~flt].tolist())}
        use_exit = s.get("use_exit_signal", True) is not False
        exit_minutes = {1: set(np.searchsorted(m.t, known[xl & ~el]).tolist()) if use_exit else set(),
                        -1: set(np.searchsorted(m.t, known[xs & ~es]).tolist()) if use_exit else set()}
        rows = list(csv.DictReader(open(TRADES / f"{name}__BTC_spot.csv")))
        rows = [r for r in rows if r["why"] != "END"]
        sample = random.sample(rows, min(n_s, len(rows)))
        mism = 0
        for r in sample:
            T0 = int(pd.Timestamp(r["entry_utc"]).timestamp())
            side = int(r["side"])
            ok_entry = (T0 in entry_known[side]) and abs(m.o[m.at(T0)] - float(r["entry"])) < 1e-6
            k, px, why = rewalk(T0, side, m, s, E.COSTS["spot"].fee, exit_minutes[side], m.n - 1)
            xt_e = int(pd.Timestamp(r["exit_utc"]).timestamp())
            xt_v = int(m.t[k]) + (0 if why in ("EXIT_SIGNAL", "END") or px == m.o[k] else 60)
            same = ok_entry and abs(px - float(r["exit"])) < 1e-4 and xt_v == xt_e and \
                (why.split("/")[0] == r["why"] or (why == "STOP/TRAIL" and r["why"] in ("STOP", "TRAIL")))
            if not same:
                mism += 1
                if mism <= 3:
                    print(f"  MISMATCH {name} entry {r['entry_utc']} engine exit {r['exit_utc']} {r['exit']} {r['why']} | "
                          f"rewalk {pd.Timestamp(xt_v, unit='s', tz='UTC')} {px:.4f} {why} entry_ok={ok_entry}")
        total += len(sample)
        bad += mism
        print(f"{name:22} sampled {len(sample):3} trades, mismatches {mism}")
    print(f"TOTAL {total} sampled, {bad} mismatches")


if __name__ == "__main__":
    main(sys.argv[1:])
