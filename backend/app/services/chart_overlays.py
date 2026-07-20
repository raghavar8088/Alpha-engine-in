"""Cross-module overlays for the Chart module (Phase 5).

Everything here reads data other modules have already produced — open paper
positions, active research calls, stored backtest trade logs — and reshapes it
into (time, price) marks the chart can draw. No market data is fetched, so none
of it costs Dhan quota; the one exception is option-chain context, which is
opt-in from the UI precisely because it does hit the broker.

An honest note on stop-loss/target lines. Trading Calls carry an explicit
`entry_price`/`target`/`stoploss`, and backtest trades carry `stop_loss`/
`target`, so those are drawn from real stored values. Paper *positions* in this
app have no SL/target field at all — only an average fill price — so a position
overlay draws its entry and nothing else rather than inventing levels the
Positions module never recorded.
"""

from bson import ObjectId

from app.core.db import (
    db,
    fno_positions_collection,
    manual_positions_collection,
    trading_calls_collection,
)

# Declared here the same way app/api/routes/backtest.py declares it — it isn't in
# app.core.db, and importing a route module from a service would invert the
# dependency direction.
backtests_collection = db["backtests"]


def _position_mark(doc: dict, source: str) -> dict:
    instrument = doc.get("instrument") or {}
    return {
        "source": source,
        "position_id": doc.get("position_id"),
        "symbol": doc.get("symbol"),
        "display_name": doc.get("display_name") or doc.get("symbol"),
        "side": doc.get("side"),
        "quantity": doc.get("quantity"),
        "entry_price": doc.get("avg_price"),
        "ltp": doc.get("ltp"),
        "unrealized_pnl": doc.get("unrealized_pnl"),
        "product_type": doc.get("product_type"),
        "opened_at": doc["opened_at"].isoformat() if doc.get("opened_at") else None,
        "security_id": instrument.get("security_id"),
        "exchange_segment": instrument.get("exchange_segment"),
    }


async def open_positions(security_id: str, exchange_segment: str) -> list[dict]:
    """Open paper positions on this exact instrument, from both position modules.

    Matched on the instrument's security_id rather than its symbol so an option
    contract only matches its own strike, never every strike on the underlying.
    """
    query = {
        "instrument.security_id": security_id,
        "instrument.exchange_segment": exchange_segment,
        "status": "OPEN",
    }
    out: list[dict] = []
    async for doc in manual_positions_collection.find(query):
        out.append(_position_mark(doc, "positions"))
    async for doc in fno_positions_collection.find(query):
        out.append(_position_mark(doc, "fno"))
    return out


async def active_calls(security_id: str, exchange_segment: str, symbol: str) -> list[dict]:
    """Open Trading Calls for this instrument.

    Falls back to a symbol match for calls whose stored instrument predates
    security_id being recorded, but only when the segment agrees — so an equity
    call never lands on a derivative chart of the same underlying.
    """
    query = {
        "status": "OPEN",
        "$or": [
            {"instrument.security_id": security_id, "instrument.exchange_segment": exchange_segment},
            {"symbol": symbol, "instrument.exchange_segment": exchange_segment},
        ],
    }
    out = []
    async for doc in trading_calls_collection.find(query).sort("created_at", -1).limit(20):
        out.append({
            "call_id": doc.get("call_id"),
            "symbol": doc.get("symbol"),
            "display_name": doc.get("display_name") or doc.get("symbol"),
            "segment": doc.get("segment"),
            "side": doc.get("side"),
            "horizon": doc.get("horizon"),
            "entry_price": doc.get("entry_price"),
            "target": doc.get("target"),
            "stoploss": doc.get("stoploss"),
            "confidence": doc.get("confidence"),
            "rationale": doc.get("rationale"),
            "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
        })
    return out


async def backtest_runs(symbol: str, limit: int = 20) -> list[dict]:
    """Recent stored backtests for a symbol, as pickable overlay sources."""
    cursor = (
        backtests_collection.find(
            {"symbol": symbol},
            {"strategy_id": 1, "symbol": 1, "timeframe": 1, "start": 1, "end": 1, "metrics": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .limit(limit)
    )
    out = []
    async for doc in cursor:
        metrics = doc.get("metrics") or {}
        out.append({
            "id": str(doc["_id"]),
            "strategy_id": doc.get("strategy_id"),
            "symbol": doc.get("symbol"),
            "timeframe": doc.get("timeframe"),
            "start": doc["start"].isoformat() if doc.get("start") else None,
            "end": doc["end"].isoformat() if doc.get("end") else None,
            "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
            "total_return_pct": metrics.get("total_return_pct"),
            "win_rate": metrics.get("win_rate"),
            "trades": metrics.get("trades"),
        })
    return out


async def backtest_trades(backtest_id: str) -> dict:
    """The stored trade log for one backtest, for entry/exit markers and replay.

    Timestamps are passed through as ISO strings exactly as the backtester wrote
    them; the frontend converts to the chart's epoch grid, since only it knows
    which grid the currently loaded history is on.
    """
    try:
        oid = ObjectId(backtest_id)
    except Exception:
        return {"found": False, "trades": []}
    doc = await backtests_collection.find_one(
        {"_id": oid}, {"charts.trades": 1, "strategy_id": 1, "symbol": 1, "timeframe": 1}
    )
    if doc is None:
        return {"found": False, "trades": []}
    return {
        "found": True,
        "strategy_id": doc.get("strategy_id"),
        "symbol": doc.get("symbol"),
        "timeframe": doc.get("timeframe"),
        "trades": ((doc.get("charts") or {}).get("trades") or []),
    }
