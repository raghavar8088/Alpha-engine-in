"""Read-only API for the five-strategy live-data paper desk."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.services.intraday_focus import snapshot

router = APIRouter(prefix="/api/intraday-focus", tags=["intraday-focus"])


@router.get("/snapshot")
async def get_snapshot(current_user: dict = Depends(get_current_user)):
    return await snapshot()
