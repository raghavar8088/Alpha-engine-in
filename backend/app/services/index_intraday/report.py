"""Indian Index Intraday — the daily trading report (written after each close, readable any time)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.core.db import db

TRADES = db["idx_intraday_trades"]
REPORTS = db["idx_intraday_reports"]


async def build(day: date) -> dict:
    rows = [t async for t in TRADES.find({"day": day.isoformat()})]
    by: dict[str, dict] = {}
    for t in rows:
        s = by.setdefault(t["sid"], {"sid": t["sid"], "key": t["key"], "index": t["index"], "model": t["model"],
                                     "trades": 0, "wins": 0, "gross": 0.0, "costs": 0.0, "net": 0.0})
        s["trades"] += 1
        s["wins"] += int(t["net"] > 0)
        s["gross"] += t["gross"]
        s["costs"] += t["costs"]
        s["net"] += t["net"]
    return {"day": day.isoformat(), "trades": len(rows), "wins": sum(int(t["net"] > 0) for t in rows),
            "gross": round(sum(t["gross"] for t in rows), 2), "costs": round(sum(t["costs"] for t in rows), 2),
            "net": round(sum(t["net"] for t in rows), 2),
            "by_strategy": sorted(({**v, "gross": round(v["gross"], 2), "costs": round(v["costs"], 2),
                                    "net": round(v["net"], 2)} for v in by.values()), key=lambda x: -x["net"]),
            "exit_reasons": {r: sum(1 for t in rows if t["exit_reason"] == r) for r in {t["exit_reason"] for t in rows}}}


async def write_daily(day: date, appended: dict | None = None) -> dict:
    rep = await build(day)
    rep["history_appended"] = appended or {}
    rep["written_at"] = datetime.now(timezone.utc)
    await REPORTS.update_one({"_id": day.isoformat()}, {"$set": rep}, upsert=True)
    return rep


async def note_history(filled: dict) -> int:
    """Record, on each day's report, instruments a later heal stored (`heal()`'s output) — so a
    day whose append was refused at 15:40 stops reading as an error once the gap is filled."""
    n = 0
    for sym, res in (filled or {}).items():
        if not isinstance(res, dict):
            continue
        for day, rows in (res.get("rows") or {}).items():
            r = await REPORTS.update_one({"_id": day}, {"$set": {f"history_appended.{sym}": rows}})
            n += r.modified_count
    return n


async def get(day: date) -> dict:
    doc = await REPORTS.find_one({"_id": day.isoformat()})
    if doc:
        doc.pop("_id", None)
        doc.pop("written_at", None)
        return doc
    return await build(day)
