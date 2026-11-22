"""Correctness checks of the gold channels 21-40 strategies with the 11-channel study's harness (yc_checks): the
truncation (look-ahead) test - the gold minutes cut at random minutes, the signals and the closed trades known at each
cut must equal the full run's field by field - and the fill test (every fill inside its row's range plus costs).
Counts only: nothing here measures performance. Writes results/checks.json.

    python -I zg_checks.py [cuts=12] [days=120] [SID,SID,...]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zg_strategies as ZG  # noqa: E402  (registers the records first)

_argv = sys.argv[1:]
_days = int(_argv[1]) if len(_argv) > 1 and _argv[1].isdigit() else 120
_only = next((a for a in _argv[1:] if not a.isdigit()), None)
sys.argv = [sys.argv[0], _argv[0] if _argv else "12"] + ([_only] if _only else [])

import yc_checks as YCK  # noqa: E402
import yc_markets as MK  # noqa: E402

YCK.ONLY = set(_only.split(",")) if _only else set(ZG.NEW)
YCK.HERE = HERE


def _load_base() -> dict:
    """Gold only: these books trade nothing else."""
    t0 = time.time()
    base = {"XAUUSD": MK.window("XAUUSD", _days)}
    print("data loaded in", round(time.time() - t0, 1), "s:", {k: len(v.t) for k, v in base.items()}, flush=True)
    return base


YCK.load_base = _load_base

if __name__ == "__main__":
    (HERE / "results").mkdir(exist_ok=True)
    YCK.main()
