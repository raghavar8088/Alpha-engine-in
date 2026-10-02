"""NSE pre-open (09:00-09:08 call auction), recorded every trading day.

At 09:08 NSE fixes each stock's Indicative Equilibrium Price — the price the opening
auction clears at — and publishes the buy and sell interest behind it. This is the first
real, tradeable read of the day per stock: its gap, and how lopsided the order book was.

It has NEVER been tested here, because no history exists anywhere we can reach: NSE serves
only the current session's pre-open. So from 2026-10-05 it is recorded every day, and only
after a few months of it can "does the pre-open imbalance predict the day" be answered.
Until then it is shown as context and used for nothing.

Stored per day at DATA_DIR/preopen/YYYY-MM-DD.json:
  {sym: [iep, prev_close, pchange, final_qty, total_buy_qty, total_sell_qty]}
and a summary in market_brief.preopen (advances/declines, the universe's biggest movers
and the most lopsided books).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from app.core.db import db
from app.services.nse_client import nse

logger = logging.getLogger("preopen")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = os.path.join(os.getenv("INTRADAY_DATA_DIR", "/data/intraday"), "preopen")
REFERER = "/market-data/pre-open-market-cm-and-emerge-market"
brief_coll = db["market_brief"]
status: dict = {"last_capture": None, "rows": 0, "last_error": None}


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def path(day) -> str:
    return os.path.join(DATA_DIR, f"{day.isoformat()}.json")


def load(day) -> dict | None:
    try:
        with open(path(day)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


async def capture(universe: set[str] | None = None, save: bool = True) -> dict:
    """Fetch the whole-market pre-open and store it. Returns the summary."""
    body = await nse.api("/api/market-data-pre-open?key=ALL", REFERER)
    if not body or not body.get("data"):
        status["last_error"] = "NSE pre-open API returned nothing"
        return {"ok": False}
    rows = {}
    for it in body["data"]:
        md = it.get("metadata") or {}
        pm = (it.get("detail") or {}).get("preOpenMarket") or {}
        sym = md.get("symbol")
        if not sym or md.get("series") not in ("EQ", "BE"):
            continue
        rows[sym] = [_f(md.get("iep") or pm.get("IEP")), _f(md.get("previousClose")), _f(md.get("pChange")),
                     _f(md.get("finalQuantity") or pm.get("finalQuantity")),
                     _f(pm.get("totalBuyQuantity")), _f(pm.get("totalSellQuantity"))]
    now = datetime.now(IST)
    day = now.date()
    stamp = (body.get("data") or [{}])[0].get("detail", {}).get("preOpenMarket", {}).get("lastUpdateTime")
    doc = {"d": day.isoformat(), "captured_at": now.isoformat(), "nse_time": stamp, "x": rows}
    uni = [s for s in rows if not universe or s in universe]

    def imb(r):
        b, s_ = r[4] or 0, r[5] or 0
        return (b - s_) / (b + s_) if (b + s_) else None
    movers = sorted((s for s in uni if rows[s][2] is not None), key=lambda s: -abs(rows[s][2]))[:20]
    lopsided = sorted((s for s in uni if imb(rows[s]) is not None and (rows[s][3] or 0) > 0),
                      key=lambda s: -abs(imb(rows[s])))[:15]
    summary = {
        "nse_time": stamp, "captured_at": now.isoformat(), "stocks": len(rows),
        "advances": sum(1 for r in rows.values() if (r[2] or 0) > 0),
        "declines": sum(1 for r in rows.values() if (r[2] or 0) < 0),
        "universe_movers": [{"symbol": s, "pchange": rows[s][2], "iep": rows[s][0],
                             "imbalance": round(imb(rows[s]), 3) if imb(rows[s]) is not None else None}
                            for s in movers],
        "universe_lopsided": [{"symbol": s, "imbalance": round(imb(rows[s]), 3), "pchange": rows[s][2]}
                              for s in lopsided],
    }
    if save:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path(day), "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        await brief_coll.update_one({"_id": day.isoformat()}, {"$set": {"preopen": summary}}, upsert=True)
    status.update({"last_capture": now.isoformat(), "rows": len(rows), "last_error": None})
    return {"ok": True, **summary}
