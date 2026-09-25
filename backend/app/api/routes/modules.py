"""Module ON/OFF switches.

  GET  /api/modules          every module with its current switch
  POST /api/modules/toggle   switch one module on or off
  POST /api/modules/all      switch every module on or off

OFF stops a module's scheduler cycle, which is where it fetches its market data AND
places its paper trades, so both stop together. Positions already open are left as they
are and are NOT managed while the module is off.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services import desk_switches as sw

router = APIRouter(prefix="/api/modules", tags=["modules"])


class ToggleRequest(BaseModel):
    module: str = Field(..., description="module key, e.g. commodity")
    enabled: bool


class AllRequest(BaseModel):
    enabled: bool


@router.get("")
async def list_modules(_user: dict = Depends(get_current_user)):
    return await sw.snapshot()


@router.post("/toggle")
async def toggle_module(req: ToggleRequest, _user: dict = Depends(get_current_user)):
    try:
        result = await sw.set_module(req.module, req.enabled)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown module {req.module!r}. Known: {', '.join(sw.MODULES)}")
    return {"result": result, **(await sw.snapshot())}


@router.post("/all")
async def toggle_all(req: AllRequest, _user: dict = Depends(get_current_user)):
    result = await sw.set_all(req.enabled)
    return {"result": result, **(await sw.snapshot())}
