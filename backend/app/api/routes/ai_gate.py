"""AI final gate API (2026-11-10). Read only: the gate itself runs as a background loop (app.services.ai_gate).

  GET /api/ai-gate/status                              model, switches, daily caps, the last cycle
  GET /api/ai-gate/summary?module=                     the A/B picture: every position the module took since the gate
                                                       started, the AI-approved book, and what the AI skipped
  GET /api/ai-gate/positions?module=&status=&limit=    AI positions (their own ai_position_id and timestamps)
  GET /api/ai-gate/decisions?module=&decision=&limit=  every review, with the AI's reasons

module = intraday | commodity | gold | premium. Paper only: nothing here reaches a broker.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import ai_gate

router = APIRouter(prefix="/api/ai-gate", tags=["ai-gate"])


def _module(module: str) -> str:
    if module not in ai_gate.MODULES:
        raise HTTPException(status_code=422, detail=f"module is one of {', '.join(ai_gate.MODULES)}")
    return module


def _off(module: str | None = None) -> dict | None:
    if ai_gate.ENABLED:
        return None
    return {"enabled": False, "configured": ai_gate.configured(), "model": ai_gate.MODEL, "module": module,
            "why_off": "the gate needs the box's local MongoDB (FACTORY_MONGO_URL) and AI_GATE not set to off"}


@router.get("/status")
async def status(_user: dict = Depends(get_current_user)):
    return ai_gate.status()


@router.get("/summary")
async def summary(module: str = Query(...), _user: dict = Depends(get_current_user)):
    m = _module(module)
    return _off(m) or await ai_gate.summary(m)


@router.get("/positions")
async def positions(module: str = Query(...), status: str | None = Query(None), limit: int = Query(100, ge=1, le=500),
                    _user: dict = Depends(get_current_user)):
    m = _module(module)
    if _off(m):
        return {"positions": [], **_off(m)}
    return {"positions": await ai_gate.positions(m, status, limit)}


@router.get("/decisions")
async def decisions(module: str = Query(...), decision: str | None = Query(None), limit: int = Query(100, ge=1, le=500),
                    _user: dict = Depends(get_current_user)):
    m = _module(module)
    if _off(m):
        return {"decisions": [], **_off(m)}
    return {"decisions": await ai_gate.decisions(m, limit, decision)}
