"""Indian Index Intraday — the strategy catalogue: every variant the research tested, with its status.

catalog.json is written by backend/research/index_intraday_2026_10/ii_catalog.py. Each entry is a
registered trial (variant x index) with its selection (2016-21), validation (2022-23) and combined
metrics, its STATUS and — when not Validated — the first gate it failed, with the number.

STATUS LADDER (the brief's)
  Experimental            defined, never backtested (none in this catalogue)
  Backtested              run through the research; failed a gate (the reason is stored)
  Validated               passed selection, validation, the luck correction, tradability,
                          breadth, walk-forward and neighbours — none did
  Paper Trading Approved  Validated, then the untouched 2024-26 holdout on the index AND the ETF
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent / "catalog.json"
STATUSES = ("Experimental", "Backtested", "Validated", "Paper Trading Approved")


@lru_cache(maxsize=1)
def _doc() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"strategies": [], "trials": 0, "validated": 0}


@lru_cache(maxsize=1)
def _by_id() -> dict:
    return {s["id"]: s for s in _doc()["strategies"]}


def get(sid: str) -> dict | None:
    return _by_id().get(sid)


def header() -> dict:
    d = _doc()
    out = {k: d.get(k) for k in ("generated", "trials", "trials_100_trades", "effective_trials", "luck_sharpe",
                                 "validated", "periods", "costs", "history_starts")}
    out["no_data"] = sum(1 for s in d["strategies"] if (s.get("failed") or "").startswith("no data"))
    return out


def strategies(index: str | None = None, family: str | None = None, status: str | None = None,
               min_trades: int = 0, sort: str = "sv_sharpe", limit: int = 200, with_curves: bool = False,
               stage: int | None = None) -> list[dict]:
    """`stage` 1 / 2 keeps only those that passed selection / validation; `min_trades` counts
    trades over selection + validation."""
    rows = []
    for s in _doc()["strategies"]:
        if stage == 1 and not s["stage1"] or stage == 2 and not s["stage2"]:
            continue
        if index and s["index"] != index:
            continue
        if family and s["family"] != family:
            continue
        if status and s["status"] != status:
            continue
        if (s["sv"].get("trades") or 0) < min_trades:
            continue
        rows.append(s if with_curves else {k: v for k, v in s.items() if k != "monthly"})
    key = {"sv_sharpe": lambda r: -(r["sv"].get("sharpe") or -99),
           "sv_net": lambda r: -(r["sv"].get("mean_net_bp") or -99),
           "dsr": lambda r: -(r.get("dsr") or -1),
           "sel_sharpe": lambda r: -(r["sel"].get("sharpe") or -99)}.get(sort)
    if key:
        rows.sort(key=key)
    return rows[:limit]


def families() -> list[dict]:
    """Per family: how many variants, the best combined Sharpe and where each stopped."""
    out: dict[str, dict] = {}
    for s in _doc()["strategies"]:
        f = out.setdefault(s["family"], {"family": s["family"], "label": s["family_label"], "variants": 0,
                                         "stage1": 0, "stage2": 0, "best_sv_sharpe": None, "best": None})
        f["variants"] += 1
        f["stage1"] += int(s["stage1"])
        f["stage2"] += int(s["stage2"])
        sh = s["sv"].get("sharpe")
        if (s["sv"].get("trades") or 0) >= 100 and sh is not None and (f["best_sv_sharpe"] is None or sh > f["best_sv_sharpe"]):
            f["best_sv_sharpe"] = sh
            f["best"] = {"id": s["id"], "index": s["index"], "exit": s["exit_label"], "params": s["params"],
                         "net_bp": s["sv"].get("mean_net_bp"), "failed": s["failed"]}
    return sorted(out.values(), key=lambda f: -(f["best_sv_sharpe"] or -99))
