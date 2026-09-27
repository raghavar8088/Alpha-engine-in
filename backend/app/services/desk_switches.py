"""Per-module ON/OFF switches - the store and the scheduler-side gate.

The registry of what a module IS lives in `module_registry`. This file owns the state: what
is currently off, how that is cached, and the `gated()` helper every scheduler wraps its
cycle in. `module_gate` is the other consumer, gating the HTTP door with the same state.

TWO DOORS, ONE SWITCH
---------------------
Work enters this app two ways: a background loop decides to act, or the browser asks. This
file closes the first. Gating only the loop left the second wide open - the page carried on
pulling quotes and writing rows for a desk that was supposed to be off - which is why the
API gate exists alongside it.

The switch sits at the CYCLE boundary rather than inside each engine, because each desk
fetches its market data inside that cycle. Gating the order-placing step alone would leave
the desk still hammering Angel's quote and candle endpoints for a book it is not allowed to
trade, which on this box is the scarcer of the two resources.

WHAT A SWITCH DOES NOT DO
-------------------------
It does not close anything. An OFF module stops taking NEW positions and stops polling;
positions it already holds are left exactly as they are, untouched and unmanaged. That is
deliberate, and it is the one sharp edge here - a desk switched off mid-session keeps its
open book frozen at the last mark, so an open position will not hit its own stop while the
switch is off. Square off first if that matters. The alternative (force-closing on OFF)
would turn a UI toggle into an irreversible trading action, which is worse.

DEFAULT IS ON
-------------
An absent record reads as ON, so this ships inert: every desk behaves exactly as it did
before anyone touches a switch. Only an explicit OFF changes anything.

THE CACHE IS NOT OPTIONAL
-------------------------
`is_on` is called once per desk per scheduler tick - a dozen desks every ~60s, plus the
commodity loops - and now once more per API request. Reading Mongo each time would add a
round trip to every request to a cluster this app has already had trouble with. State
changes come from one place (the API), which invalidates on write, so it is never stale in
practice.
"""

import logging
import os
import time as _time

from app.core.db import desk_switches_collection
from app.services.module_registry import GROUP_ORDER, REGISTRY

logger = logging.getLogger("desk_switches")

# key -> (label, href). Derived from the registry rather than kept in parallel, because two
# hand-maintained lists of modules WILL drift, and a key missing from one of them is a desk
# whose switch silently controls nothing.
MODULES: dict[str, tuple[str, str]] = {
    k: (m.label, m.href) for k, m in REGISTRY.items()
}

CACHE_TTL = float(os.getenv("DESK_SWITCH_TTL", "20"))
_cache: dict[str, bool] | None = None
_cache_at: float = 0.0


def _invalidate() -> None:
    global _cache, _cache_at
    _cache, _cache_at = None, 0.0


async def _load() -> dict[str, bool]:
    global _cache, _cache_at
    now = _time.monotonic()
    if _cache is not None and now - _cache_at < CACHE_TTL:
        return _cache
    out: dict[str, bool] = {}
    try:
        async for d in desk_switches_collection.find({}):
            key = d.get("_id") or d.get("module")
            if key:
                out[str(key)] = bool(d.get("enabled", True))
    except Exception:  # noqa: BLE001
        # A switch lookup must never be able to stop the desks. If the store is unreachable
        # the safe reading is "carry on as before", not "halt everything".
        logger.warning("[desk_switches] could not read switches - treating all as ON",
                       exc_info=True)
        return dict(_cache or {})
    _cache, _cache_at = out, now
    return out


async def is_on(key: str) -> bool:
    """True unless someone has explicitly switched this module off."""
    return (await _load()).get(key, True)


def is_on_cached(key: str) -> bool:
    """Synchronous read of the last loaded state, for callers that cannot await.

    Returns ON when nothing has been loaded yet - the same fail-open default as `is_on`."""
    return (_cache or {}).get(key, True)


async def set_module(key: str, enabled: bool) -> dict:
    if key not in REGISTRY:
        raise KeyError(key)
    await desk_switches_collection.update_one(
        {"_id": key},
        {"$set": {"_id": key, "module": key, "enabled": bool(enabled)}},
        upsert=True)
    _invalidate()
    logger.warning("[desk_switches] %s = %s", key, "ON" if enabled else "OFF")
    return {"module": key, "enabled": bool(enabled)}


async def set_many(states: dict[str, bool]) -> dict:
    """Apply several switches at once.

    Unknown keys are reported rather than raising, so one stale key in a bulk call from an
    old browser tab cannot lose the other twenty valid changes in it."""
    applied, unknown = {}, []
    for key, enabled in (states or {}).items():
        if key not in REGISTRY:
            unknown.append(key)
            continue
        await desk_switches_collection.update_one(
            {"_id": key},
            {"$set": {"_id": key, "module": key, "enabled": bool(enabled)}},
            upsert=True)
        applied[key] = bool(enabled)
    _invalidate()
    if applied:
        logger.warning("[desk_switches] bulk: %s",
                       ", ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in applied.items()))
    return {"applied": applied, "unknown": unknown}


async def set_all(enabled: bool) -> dict:
    for key in REGISTRY:
        await desk_switches_collection.update_one(
            {"_id": key},
            {"$set": {"_id": key, "module": key, "enabled": bool(enabled)}},
            upsert=True)
    _invalidate()
    logger.warning("[desk_switches] ALL = %s", "ON" if enabled else "OFF")
    return {"modules": list(REGISTRY), "enabled": bool(enabled)}


async def set_only(key: str) -> dict:
    """Switch this module ON and every other module OFF.

    The literal reading of "only that module should work" - one click instead of forty."""
    if key not in REGISTRY:
        raise KeyError(key)
    for k in REGISTRY:
        await desk_switches_collection.update_one(
            {"_id": k},
            {"$set": {"_id": k, "module": k, "enabled": k == key}},
            upsert=True)
    _invalidate()
    logger.warning("[desk_switches] ONLY %s is ON, %d others OFF", key, len(REGISTRY) - 1)
    return {"only": key, "off": [k for k in REGISTRY if k != key]}


NOTE = ("OFF stops a module's scheduler cycle AND blocks its API from doing work - no "
        "broker calls, no new or changed documents. Plain reads of rows already stored "
        "still answer, so the page keeps rendering its last known numbers: they are frozen, "
        "not live. Positions already open are left untouched and are NOT managed while off, "
        "so square off first if that matters.")


async def snapshot() -> dict:
    """Every module with its switch, its group, and the API surface it controls."""
    state = await _load()
    rows = []
    for key, m in REGISTRY.items():
        rows.append({
            "module": key,
            "label": m.label,
            "href": m.href,
            "group": m.group,
            "enabled": state.get(key, True),
            "api_prefixes": list(m.api_prefixes),
            "has_api": m.has_api,
            "shared": m.shared,
            "note": m.note,
        })
    rows.sort(key=lambda r: (GROUP_ORDER.index(r["group"])
                            if r["group"] in GROUP_ORDER else 99, r["label"]))
    return {
        "modules": rows,
        "groups": list(GROUP_ORDER),
        "total": len(rows),
        "on": sum(1 for r in rows if r["enabled"]),
        "off": sum(1 for r in rows if not r["enabled"]),
        "note": NOTE,
    }


async def gated(key: str, fn, *args, **kwargs):
    """Run a desk's cycle only if its module is switched on.

    Returns `{}` when off, so the caller's `result.get("opened")` style logging simply finds
    nothing and stays quiet - no branch, no indentation change at the call site."""
    if not await is_on(key):
        return {}
    return await fn(*args, **kwargs)
