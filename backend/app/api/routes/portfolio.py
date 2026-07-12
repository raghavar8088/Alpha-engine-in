from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.schemas.portfolio import PortfolioAnalytics
from app.services.portfolio_analytics import compute_portfolio_analytics

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/analytics", response_model=PortfolioAnalytics)
async def portfolio_analytics(current_user: dict = Depends(get_current_user)):
    client = await _get_dhan_client(str(current_user["_id"]))
    return await compute_portfolio_analytics(client)
