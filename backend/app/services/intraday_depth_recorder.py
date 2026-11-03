"""Order-book snapshots at every signal of the six rules with a real edge before costs (Phase 3).

H1 (h1_slippage — pre-registered, never edited) records what a Rs 10 lakh market order would pay
for three strategies. The signal scorer (Phase 7 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md) also
needs the book's SHAPE at every signal of the six rules, taken or not: both sides' five levels
WITH their quantities, so queue imbalance, depth and the microprice can be tested as features.

One Angel FULL quote per bar close for the batch (the same call H1 makes). Stored in the box's
local MongoDB beside the decision ledger (alpha_engine_intraday.intraday_depth_samples), never
Atlas; off when the ledger is off. Fire-and-forget: never raises, never delays the engine.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from app.services import intraday_signal_ledger as ledger
from app.services.h1_slippage import cost_of

logger = logging.getLogger("intraday_depth_recorder")

RULES = ("iv2_donchian_45m", "iv2_donchian_1h", "iv2_vwap_trend_1h", "iv2_macd_trend_1h",
         "iv2_rsi_momentum_45m", "iv2_bollinger_snap_1h")
ENABLED = ledger.ENABLED and os.getenv("INTRADAY_DEPTH_RECORDER", "1").strip().lower() not in ("0", "false", "no", "off")
COLLECTION = "intraday_depth_samples"
NOTIONAL = 1_000_000.0
stats: dict = {"batches": 0, "stored": 0, "failed_reads": 0, "last_error": None}
_indexed = False
_tasks: set = set()


def _levels(rows) -> list[list[float]]:
    out = []
    for lv in rows or []:
        try:
            p, q = float(lv[0]), float(lv[1])
        except (TypeError, ValueError, IndexError):
            continue
        if p > 0 and q > 0:
            out.append([p, q])
    return out


def shape(bids: list[list[float]], asks: list[list[float]], ltp: float | None) -> dict:
    """The book's shape: spread, depth on each side (shares and rupees), queue imbalance at the
    top and over five levels, the microprice, and a Rs 10 lakh order's cost on either side."""
    out: dict = {"levels_bid": len(bids), "levels_ask": len(asks), "bids": bids, "asks": asks}
    if not bids or not asks:
        return out
    b1, a1 = bids[0], asks[0]
    mid = (b1[0] + a1[0]) / 2
    bq, aq = sum(q for _p, q in bids), sum(q for _p, q in asks)
    out.update({
        "bid": b1[0], "ask": a1[0], "mid": round(mid, 4),
        "spread_bp": round((a1[0] - b1[0]) / mid * 1e4, 3),
        "bid_qty": bq, "ask_qty": aq,
        "bid_value": round(sum(p * q for p, q in bids), 0), "ask_value": round(sum(p * q for p, q in asks), 0),
        "imbalance_top": round((b1[1] - a1[1]) / (b1[1] + a1[1]), 4),
        "imbalance_5": round((bq - aq) / (bq + aq), 4) if bq + aq else None,
        "microprice_bp": round(((a1[0] * b1[1] + b1[0] * a1[1]) / (b1[1] + a1[1]) - mid) / mid * 1e4, 3),
    })
    if ltp:
        for side in ("BUY", "SELL"):
            c = cost_of(side, NOTIONAL, float(ltp), bids, asks)
            if c:
                out[f"cost_{side.lower()}_bp"] = c["cost_bp_vs_ltp"]
                out[f"covered_{side.lower()}_pct"] = c["depth_covered_pct"]
    return out


async def capture(items: list[dict]) -> int:
    """`items`: {strategy_id, symbol, token, side, ltp, signal_at}. One quote call for the batch."""
    global _indexed
    items = [i for i in items if i.get("strategy_id") in RULES and i.get("token")]
    if not ENABLED or not items:
        return 0
    stats["batches"] += 1
    try:
        from app.services.angel_client import angel_client
        q = await angel_client.full_quote({"NSE": sorted({str(i["token"]) for i in items})})
    except Exception as exc:  # noqa: BLE001
        stats["failed_reads"] += 1
        stats["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
        logger.warning("[depth] book read failed (%s) — %d signal(s) not recorded", type(exc).__name__, len(items))
        return 0
    now = datetime.now(timezone.utc)
    docs = []
    for i in items:
        row = q.get(str(i["token"])) or {}
        ltp = i.get("ltp") or row.get("ltp")
        docs.append({"strategy_id": i["strategy_id"], "symbol": i["symbol"], "side": i["side"],
                     "signal_at": i.get("signal_at"), "measured_at": now,
                     "lag_s": (now - i["signal_at"]).total_seconds() if i.get("signal_at") else None,
                     "trade_time": row.get("trade_time"), "ltp": ltp,
                     "d": now.astimezone(ledger.IST).date().isoformat(),
                     **shape(_levels(row.get("depth_buy")), _levels(row.get("depth_sell")), ltp)})
    try:
        coll = ledger._db()[COLLECTION]
        if not _indexed:
            await coll.create_index("measured_at", expireAfterSeconds=ledger.RETENTION_DAYS * 86400, name="ttl")
            await coll.create_index([("d", 1), ("strategy_id", 1)], name="d_sid")
            _indexed = True
        await coll.insert_many(docs, ordered=False)
        stats["stored"] += len(docs)
        return len(docs)
    except Exception as exc:  # noqa: BLE001
        stats["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
        logger.warning("[depth] could not store %d snapshot(s): %s", len(docs), exc)
        return 0


def schedule(items: list[dict]) -> None:
    """Fire-and-forget from inside the engine; a failure is logged, never propagated."""
    if not ENABLED or not any(i.get("strategy_id") in RULES for i in items):
        return

    async def _run():
        try:
            await capture(items)
        except Exception:  # noqa: BLE001
            logger.exception("[depth] capture task failed")
    try:
        t = asyncio.get_running_loop().create_task(_run())
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    except RuntimeError:
        pass


def describe() -> dict:
    return {"enabled": ENABLED, "rules": list(RULES), **stats}
