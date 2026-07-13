from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.db import strategy_validation_collection
from app.schemas.strategy import RealMoneyCheck, StrategyInfo, ValidationRun, ValidationSummary
from strategy_service import STRATEGY_REGISTRY

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _to_info(strategy_cls, validation_doc: dict | None) -> StrategyInfo:
    m = strategy_cls.metadata
    validation = None
    if validation_doc is not None:
        real_money = validation_doc.get("real_money")
        validation = ValidationSummary(
            status=validation_doc.get("status", "pass" if validation_doc["passed"] else "fail"),
            passed=validation_doc["passed"],
            passing_runs=validation_doc["passing_runs"],
            total_runs=validation_doc["total_runs"],
            validated_at=validation_doc["validated_at"].isoformat(),
            best_run=ValidationRun(**validation_doc["best_run"]) if validation_doc.get("best_run") else None,
            runs=[ValidationRun(**r) for r in validation_doc.get("runs", [])],
            real_money=RealMoneyCheck(**real_money) if real_money else None,
            real_money_ready=validation_doc.get("real_money_ready", False),
        )
    return StrategyInfo(
        strategy_id=m.strategy_id,
        name=m.name,
        category=m.category,
        description=m.description,
        timeframes=[t.value for t in m.timeframes],
        asset_classes=[a.value for a in m.asset_classes],
        suitable_market=m.suitable_market,
        expected_win_rate=m.expected_win_rate,
        risk_reward=m.risk_reward,
        params_schema=strategy_cls.Params.model_json_schema(),
        validation=validation,
    )


@router.get("", response_model=list[StrategyInfo])
async def list_strategies(_current_user: dict = Depends(get_current_user)):
    docs = {d["strategy_id"]: d async for d in strategy_validation_collection.find()}
    return [_to_info(cls, docs.get(sid)) for sid, cls in sorted(STRATEGY_REGISTRY.items())]


@router.get("/{strategy_id}", response_model=StrategyInfo)
async def get_strategy(strategy_id: str, _current_user: dict = Depends(get_current_user)):
    cls = STRATEGY_REGISTRY.get(strategy_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Unknown strategy")
    doc = await strategy_validation_collection.find_one({"strategy_id": strategy_id})
    return _to_info(cls, doc)
