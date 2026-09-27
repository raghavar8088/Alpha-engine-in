"""Main Control - one switch per module, governing both its loop and its API.

  GET  /api/main-control              every module, its switch, and what it controls
  POST /api/main-control/toggle       one module on or off
  POST /api/main-control/bulk         several at once
  POST /api/main-control/all          everything on or off
  POST /api/main-control/only         this module on, every other one off
  POST /api/main-control/reset-counts clear the blocked-request counters
  GET  /api/main-control/resolve      which module owns a given path (proof, not plumbing)

This router is never itself gated - see module_registry.UNGATED_PREFIXES. A switch you
cannot reach to turn back on is not a switch.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services import desk_switches as sw
from app.services import module_gate as gate
from app.services.module_registry import REGISTRY, is_work, owned_prefixes, resolve

router = APIRouter(prefix="/api/main-control", tags=["main-control"])


class ToggleRequest(BaseModel):
    module: str = Field(..., description="module key, e.g. commodity")
    enabled: bool


class BulkRequest(BaseModel):
    modules: dict[str, bool] = Field(..., description="key -> enabled")


class AllRequest(BaseModel):
    enabled: bool


class OnlyRequest(BaseModel):
    module: str


async def _state() -> dict:
    """The snapshot, plus how many requests each switch has actually refused."""
    snap = await sw.snapshot()
    counts = gate.blocked_counts()
    for row in snap["modules"]:
        c = counts.get(row["module"]) or {}
        row["blocked_requests"] = int(c.get("blocked", 0))
        row["last_blocked"] = c.get("last", "")
    snap["blocked_total"] = sum(r["blocked_requests"] for r in snap["modules"])
    snap["api_prefixes_controlled"] = len(owned_prefixes())
    return snap


def _unknown(key: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=f"Unknown module {key!r}. Known keys: {', '.join(sorted(REGISTRY))}")


@router.get("")
async def get_control(_user: dict = Depends(get_current_user)):
    return await _state()


@router.post("/toggle")
async def toggle(req: ToggleRequest, _user: dict = Depends(get_current_user)):
    try:
        result = await sw.set_module(req.module, req.enabled)
    except KeyError:
        raise _unknown(req.module)
    return {"result": result, **(await _state())}


@router.post("/bulk")
async def bulk(req: BulkRequest, _user: dict = Depends(get_current_user)):
    result = await sw.set_many(req.modules)
    return {"result": result, **(await _state())}


@router.post("/all")
async def all_modules(req: AllRequest, _user: dict = Depends(get_current_user)):
    result = await sw.set_all(req.enabled)
    return {"result": result, **(await _state())}


@router.post("/only")
async def only(req: OnlyRequest, _user: dict = Depends(get_current_user)):
    try:
        result = await sw.set_only(req.module)
    except KeyError:
        raise _unknown(req.module)
    return {"result": result, **(await _state())}


@router.post("/reset-counts")
async def reset_counts(_user: dict = Depends(get_current_user)):
    return {"cleared": gate.reset_counts(), **(await _state())}


@router.get("/resolve")
async def resolve_path(
    path: str = Query(..., description="an API path, e.g. /api/commodity/summary"),
    method: str = Query("GET"),
    _user: dict = Depends(get_current_user),
):
    """Which module owns this path, and would the gate block it right now.

    Here so a switch can be checked rather than trusted: if a page still seems live with its
    module off, ask this what owns the path it is calling."""
    key = resolve(path)
    enabled = await sw.is_on(key) if key else True
    work = is_work(method, path)
    return {
        "path": path,
        "method": method.upper(),
        "module": key,
        "label": REGISTRY[key].label if key else None,
        "enabled": enabled,
        "counts_as_work": work,
        "would_block": bool(key and not enabled and work),
        "reason": (
            "no module claims this path, so it is never gated" if key is None else
            f"{REGISTRY[key].label} is ON" if enabled else
            "module is OFF and this request would do work, so it is blocked" if work else
            "module is OFF but this is a plain read of stored rows, so it is still served"),
    }
