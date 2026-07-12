from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.schemas.risk import RiskLimitsUpdate, RiskStatus
from app.services.portfolio_analytics import get_risk_limits, get_risk_status, set_risk_limits

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/status", response_model=RiskStatus)
async def risk_status(current_user: dict = Depends(get_current_user)):
    client = await _get_dhan_client(str(current_user["_id"]))
    return await get_risk_status(client)


@router.get("/config")
async def risk_config(_current_user: dict = Depends(get_current_user)):
    return await get_risk_limits()


@router.put("/config")
async def update_risk_config(payload: RiskLimitsUpdate, _current_user: dict = Depends(get_current_user)):
    current = await get_risk_limits()
    updated = current.model_copy(update={k: v for k, v in payload.model_dump().items() if v is not None})
    await set_risk_limits(updated)
    return updated
