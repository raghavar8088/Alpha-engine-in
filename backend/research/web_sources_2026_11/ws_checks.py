"""Truncation (look-ahead) test of our QuantConnect re-implementations, the method of the shortlist study's checks:
each strategy is rebuilt on data cut at random minutes, and every signal known before the cut must equal the full
run's signal at the same time. A difference means a signal used data from after its own time. Counts only.

    python -I ws_checks.py [cuts per strategy=3]          writes results/qc_truncation.json
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ws_engine as E  # noqa: E402
import ws_strategies as S  # noqa: E402

FULL = Path(r"D:\Strategy-Web-Sources\signals_qc")
OUT = HERE / "results" / "qc_truncation.json"
COLS = ("enter_long", "exit_long", "enter_short", "exit_short")


def cut_minutes(m: E.Minutes, cut: int) -> E.Minutes:
    c = object.__new__(type(m))
    c.__dict__.update(m.__dict__)
    k = int(np.searchsorted(m.t, cut, side="left"))
    c.t, c.o, c.h, c.l, c.c = m.t[:k], m.o[:k], m.h[:k], m.l[:k], m.c[:k]
    c.n = k
    return c


def compare(full: Path, part: Path, cut: int) -> tuple[int, int]:
    a, b = np.load(full), np.load(part)
    ka, kb = a["t"] + 60 * int(a["tf"]), b["t"] + 60 * int(b["tf"])
    sel_b = kb <= cut
    common, ia, ib = np.intersect1d(ka, kb[sel_b], return_indices=True)
    bad = sum(int((a[c][ia] != b[c][np.flatnonzero(sel_b)][ib]).sum()) for c in COLS)
    return len(common), bad


def main(argv: list[str]) -> None:
    cuts_n = int(argv[0]) if argv else 3
    random.seed(11)
    res = {}
    crypto = {"BTC_USDT": E.Minutes("BTC/USDT"), "ETH_USDT": E.Minutes("ETH/USDT")}
    gold = E.GoldMinutes()
    jobs = [("QC-11340", S.qc_11340, mk) for mk in crypto] + [("QC-13690", S.qc_13690, mk) for mk in crypto] + \
           [("QC-15987", S.qc_15987, mk) for mk in crypto] + [("QC-18379", S.qc_18379, "BTC_USDT"),
                                                               ("QC-20960", S.qc_20960, "XAUUSD"), ("QC-5079", S.qc_5079, "XAUUSD")]
    with tempfile.TemporaryDirectory() as tmp:
        S.OUT = Path(tmp)
        for sid, fn, mk in jobs:
            m = gold if mk == "XAUUSD" else crypto[mk]
            lo, hi = int(m.t[len(m.t) // 5]), int(m.t[-1])
            rows = bad = 0
            for _ in range(cuts_n):
                cut = random.randrange(lo, hi)
                mc = cut_minutes(m, cut)
                fn(mc) if mk == "XAUUSD" else fn(mc, mk)
                r, b = compare(FULL / f"{sid}__{mk}.npz", Path(tmp) / f"{sid}__{mk}.npz", cut)
                rows += r
                bad += b
            res[f"{sid} {mk}"] = {"cuts": cuts_n, "rows_compared": rows, "differences": bad}
            print(f"{sid:9} {mk:9} cuts={cuts_n} rows={rows:>9} differences={bad}", flush=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
