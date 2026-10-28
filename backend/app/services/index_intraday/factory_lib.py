"""Indian Index Intraday — the Strategy Factory library as this module serves it.

factory_catalog.json.gz is written by backend/research/index_intraday_2026_10/ii_factory.py: every
factory strategy (69 hypotheses x 8 timeframes) on each index it ran, traded intraday by factory.py
over 2019-23, with its grade (the factory's 1-5 rules: in-sample 2019-21, out-of-sample 2022-23) and
the luck-corrected Sharpe over every strategy on that index. An index the run did not cover still
lists all 546 strategies, as Experimental and ungraded: the Backtesting Lab runs any of them there.

STATUS on this module's ladder: a catalogued factory strategy is "Backtested" whatever its grade —
"Validated" needs this module's own protocol (luck bar, the ETF track, walk-forward), which these
strategies have not been put through.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from app.services.strategy_factory.catalog import FACTORY_CATALOG, RECIPES

from .costs import ROUTE
from .factory import FAMILY_LABEL, RECIPE_OF, describe, sid_for

PATH = Path(__file__).resolve().parent / "factory_catalog.json.gz"
GRADES = (5, 4, 3, 2, 1)


@lru_cache(maxsize=1)
def _doc() -> dict:
    try:
        with gzip.open(PATH, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        return {"strategies": [], "indexes": [], "trials": 0}


@lru_cache(maxsize=1)
def _by_id() -> dict:
    return {s["id"]: s for s in _doc()["strategies"]}


def covered() -> list[str]:
    return list(_doc().get("indexes") or [])


def _ungraded(sf, index: str) -> dict:
    return {"id": sid_for(sf.strategy_id, index), "index": index, "etf": ROUTE[index][0], **describe(sf),
            "status": "Experimental", "grade": None, "grade_reasons": ["not in the 2019-23 catalogue run for this index"],
            "failed": None, "all": {}, "is": {}, "oos": {}, "dsr": None, "exits": {}, "rejections": {},
            "monthly": {"start": None, "bp": []}}


def get(sid: str) -> dict | None:
    got = _by_id().get(sid)
    if got is not None:
        return got
    from .factory import parse_sid
    p = parse_sid(sid)
    return _ungraded(p[0], p[1]) if p else None


def header() -> dict:
    d = _doc()
    return {k: d.get(k) for k in ("generated", "round", "indexes", "strategies_per_index", "trials", "periods",
                                  "costs", "grade_counts")} | {
        "hypotheses": len(RECIPES), "timeframes": ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"],
        "families": FAMILY_LABEL, "all_indexes": list(ROUTE)}


def rows_for(index: str) -> list[dict]:
    if index in covered():
        return [s for s in _doc()["strategies"] if s["index"] == index]
    return [_ungraded(sf, index) for sf in FACTORY_CATALOG]


SORTS = {
    "grade": lambda r: (-(r.get("grade") or 0), -((r["all"].get("sharpe") if r["all"] else None) or -99)),
    "sharpe": lambda r: -((r["all"].get("sharpe") if r["all"] else None) or -99),
    "net": lambda r: -((r["all"].get("total_bp") if r["all"] else None) or -1e9),
    "oos": lambda r: -((r["oos"].get("total_bp") if r["oos"] else None) or -1e9),
    "dsr": lambda r: -(r.get("dsr") or -1),
    "pf": lambda r: -((r["all"].get("profit_factor") if r["all"] else None) or -1),
    "trades": lambda r: -((r["all"].get("trades") if r["all"] else None) or 0),
    "id": lambda r: r["sf"],
}


def strategies(index: str = "NIFTY", family: str | None = None, timeframe: str | None = None,
               grade: str | None = None, sort: str = "grade", q: str | None = None, limit: int = 100,
               offset: int = 0) -> tuple[list[dict], int]:
    """`grade` is 1-5 or 'ungraded'. Rows leave out the monthly curve."""
    out = []
    ql = (q or "").strip().lower()
    for s in rows_for(index):
        if family and s["family"] != family:
            continue
        if timeframe and s["timeframe"] != timeframe:
            continue
        if grade == "ungraded" and s.get("grade") is not None:
            continue
        if grade and grade != "ungraded" and str(s.get("grade")) != str(grade):
            continue
        if ql and ql not in s["name"].lower() and ql not in s["sf"].lower() and ql not in s["detector"].lower():
            continue
        out.append({k: v for k, v in s.items() if k != "monthly"})
    out.sort(key=SORTS.get(sort, SORTS["grade"]))
    return out[offset:offset + limit], len(out)


def distribution(index: str = "NIFTY") -> dict:
    rows = rows_for(index)
    g = {str(k): sum(1 for r in rows if r.get("grade") == k) for k in GRADES}
    fam: dict[str, int] = {}
    for r in rows:
        fam[r["family"]] = fam.get(r["family"], 0) + 1
    return {"index": index, "grades": g, "ungraded": sum(1 for r in rows if r.get("grade") is None),
            "families": fam, "strategies": len(rows), "covered": index in covered()}


def hypotheses(index: str = "NIFTY") -> list[dict]:
    """The 69 recipes, each with its eight timeframes' grade on `index`."""
    rows = {r["sf"]: r for r in rows_for(index)}
    out = []
    for rec in RECIPES:
        tfs = []
        for sf in FACTORY_CATALOG:
            if RECIPE_OF[sf.strategy_id] is not rec:
                continue
            r = rows.get(sf.strategy_id) or {}
            a = r.get("all") or {}
            tfs.append({"timeframe": sf.timeframe, "id": sid_for(sf.strategy_id, index), "grade": r.get("grade"),
                        "trades": a.get("trades"), "total_bp": a.get("total_bp"), "sharpe": a.get("sharpe")})
        graded = [t for t in tfs if t["grade"] is not None]
        best = max(graded, key=lambda t: (t["grade"], t["sharpe"] or -99), default=None)
        out.append({"key": rec.key, "name": rec.name, "family": rec.family,
                    "family_label": FAMILY_LABEL.get(rec.family, rec.family), "sub_family": rec.sub_family,
                    "hypothesis": rec.hypothesis, "detector": rec.detector, "target_r": rec.target_r,
                    "regimes": sorted(rec.regimes), "confirmations": [n for n, _ in rec.confirmations],
                    "intraday_only": rec.intraday_only, "uses_htf": rec.uses_htf, "timeframes": tfs,
                    "best": best})
    return out
