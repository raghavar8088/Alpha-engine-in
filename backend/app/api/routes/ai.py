from fastapi import APIRouter, Depends, HTTPException

from ai_service import modules
from ai_service.provider import DEFAULT_MODEL, get_provider
from app.api.deps import get_current_user
from app.core.db import research_signals_collection, strategy_validation_collection
from app.schemas.ai import (
    AIStatus,
    CompareStrategiesRequest,
    DetectUnusualRequest,
    ExplainTradeRequest,
    SummarizeNewsRequest,
)
from strategy_service import STRATEGY_REGISTRY

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", response_model=AIStatus)
async def status(_current_user: dict = Depends(get_current_user)):
    provider = get_provider()
    return AIStatus(
        configured=provider.configured,
        model=DEFAULT_MODEL,
        note="ANTHROPIC_API_KEY not set — endpoints return status='not_configured' until it is"
        if not provider.configured
        else "live",
    )


@router.post("/explain-trade")
async def explain_trade(request: ExplainTradeRequest, _current_user: dict = Depends(get_current_user)):
    return await modules.explain_trade(request.trade)


@router.get("/rank-strategies")
async def rank_strategies(_current_user: dict = Depends(get_current_user)):
    strategies = []
    async for doc in strategy_validation_collection.find({"passed": True}):
        if not doc.get("best_run"):
            continue
        cls = STRATEGY_REGISTRY.get(doc["strategy_id"])
        strategies.append(
            {
                "strategy_id": doc["strategy_id"],
                "name": cls.metadata.name if cls else doc["strategy_id"],
                "category": cls.metadata.category if cls else None,
                "metrics": doc["best_run"]["metrics"],
                "real_money_ready": doc.get("real_money_ready", False),
            }
        )
    if not strategies:
        return {"status": "no_data", "message": "no passing strategies to rank yet"}
    return await modules.rank_strategies(strategies)


@router.post("/compare-strategies")
async def compare_strategies(request: CompareStrategiesRequest, _current_user: dict = Depends(get_current_user)):
    doc_a = await strategy_validation_collection.find_one({"strategy_id": request.strategy_id_a})
    doc_b = await strategy_validation_collection.find_one({"strategy_id": request.strategy_id_b})
    if doc_a is None or not doc_a.get("best_run"):
        raise HTTPException(status_code=422, detail=f"no validated run for {request.strategy_id_a}")
    if doc_b is None or not doc_b.get("best_run"):
        raise HTTPException(status_code=422, detail=f"no validated run for {request.strategy_id_b}")
    strategy_a = {"strategy_id": request.strategy_id_a, "metrics": doc_a["best_run"]["metrics"]}
    strategy_b = {"strategy_id": request.strategy_id_b, "metrics": doc_b["best_run"]["metrics"]}
    return await modules.compare_strategies(strategy_a, strategy_b)


@router.post("/detect-unusual")
async def detect_unusual(request: DetectUnusualRequest, _current_user: dict = Depends(get_current_user)):
    return await modules.detect_unusual_activity(request.symbol, request.market_data)


@router.get("/trade-ideas")
async def trade_ideas(limit: int = 30, _current_user: dict = Depends(get_current_user)):
    cursor = research_signals_collection.find({}).sort("timestamp", -1).limit(limit)
    signals = [
        {
            "symbol": doc["symbol"],
            "timeframe": doc["timeframe"],
            "signal": doc["signal"],
            "confidence": doc["confidence"],
            "source": doc["source"],
            "reasoning": doc["reasoning"],
        }
        async for doc in cursor
        if doc["symbol"] != "MARKET"
    ]
    if not signals:
        return {"status": "no_data", "message": "no symbol-tagged research signals yet"}
    return await modules.generate_trade_ideas(signals)


@router.post("/summarize-news")
async def summarize_news(request: SummarizeNewsRequest, _current_user: dict = Depends(get_current_user)):
    query: dict = {}
    if request.symbol:
        query["symbol"] = request.symbol.upper()
    cursor = research_signals_collection.find(query).sort("timestamp", -1).limit(request.limit)
    articles = [{"title": doc["reasoning"], "source": doc["source"], "symbol": doc["symbol"]} async for doc in cursor]
    if not articles:
        return {"status": "no_data", "message": "no research signals ingested yet"}
    return await modules.summarize_news(articles)
