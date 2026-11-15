"""Correctness checks of the Trade Room strategies with the 11-channel study's harness (yc_checks): the truncation
(look-ahead) test - every market cut at random minutes, the signals and the closed trades known at the cut must equal
the full run's field by field - and the fill test (every fill inside its row's range plus costs). Counts only: nothing
here measures performance. Writes results/checks.json.

    python -I zt_checks.py [cuts=6] [SID,SID,...]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zt_strategies as ZT  # noqa: E402  (registers the records first)

_argv = sys.argv[1:]
sys.argv = [sys.argv[0]] + (_argv or ["6"])

import yc_checks as YCK  # noqa: E402
import yc_markets as MK  # noqa: E402

YCK.ONLY = set(_argv[1].split(",")) if len(_argv) > 1 else set(ZT.NEW)
YCK.HERE = HERE
DAYS = {"NIFTY": 90, "BANKNIFTY": 90, "XAUUSD": 60, "BTCUSD": 75}


def _load_base() -> dict:
    """Only the four markets these books trade (the harness's own loader also builds the stock pools)."""
    t0 = time.time()
    base = {nm: MK.window(nm, d) for nm, d in DAYS.items()}
    print("data loaded in", round(time.time() - t0, 1), "s:",
          {k: (len(v.t) if v is not None else None) for k, v in base.items()}, flush=True)
    return base


YCK.load_base = _load_base

if __name__ == "__main__":
    YCK.main()
