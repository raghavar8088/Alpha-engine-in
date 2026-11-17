"""Per-module ON/OFF switches - the store, the three states, and the scheduler-side gate.

The registry of what a module IS lives in `module_registry`. This file owns the state: what
is currently off, how that is cached, what a switched-off module still holds, and the
`gated()` helper every scheduler wraps its cycle in. `module_gate` is the other consumer,
gating the HTTP door with the same state.

TWO DOORS, ONE SWITCH
---------------------
Work enters this app two ways: a background loop decides to act, or the browser asks. This
file closes the first. Gating only the loop left the second wide open - the page carried on
pulling quotes and writing rows for a desk that was supposed to be off - which is why the
API gate exists alongside it.

THREE STATES, NOT TWO
---------------------
A switch is ON or OFF; a module is in one of three states:

  ACTIVE    switched ON. Everything runs exactly as it did before switches existed.
  STOPPING  switched OFF but still holding open positions. Its cycle keeps running in
            MANAGE-ONLY mode: marks, stops, targets, exits and the mandatory square-off all
            happen, and no new position is opened.
  PAUSED    switched OFF and flat. Its cycle does not run at all - no quotes, no candles, no
            writes - which is the whole point of switching a module off.

STOPPING turns into PAUSED by itself: every drain cycle re-counts what is open, and the
first cycle that finds nothing skips. Switching it back ON resumes on the next tick; the loop
never stopped, so nothing is started twice.

Before 2026-11-17 OFF froze a module's open book at its last mark - an open position would
not hit its own stop while the switch was off. Draining replaced that for every module whose
engine honours `entries_blocked()` (registry `drains=True`). A module with `drains=False`
keeps the old freeze, and Main Control says so beside its switch.

HOW "NO NEW ENTRIES" REACHES THE ENGINE
---------------------------------------
`gated()` runs a draining cycle inside a context variable. The engine asks
`entries_blocked()` at its own entry point and skips opening - one line per engine, no
signature changes, and a manual API call (which runs outside the variable) is unaffected. A
context variable rather than a module global because cycles from different desks interleave
on one event loop: a global set by one desk's drain would block another desk's entries.

WHAT A SWITCH STILL DOES NOT DO
-------------------------------
It never closes anything by itself. Force-closing on OFF would turn a UI toggle into an
irreversible trading action. Draining lets each position leave by its own rules.

DEFAULT IS ON
-------------
An absent record reads as ON, so this ships inert: every desk behaves exactly as it did
before anyone touches a switch. Only an explicit OFF changes anything.

THE CACHES ARE NOT OPTIONAL
---------------------------
`is_on` is called once per desk per scheduler tick - a dozen desks every ~60s, plus the
commodity loops - and once more per API request. Reading Mongo each time would add a round
trip to every request to a cluster this app has already had trouble with. Switch changes come
from one place (the API), which invalidates on write. Open-position counts are only ever
probed for OFF modules, and cached for OPEN_TTL seconds.
"""

import importlib
import logging
import os
import time as _time
from contextvars import ContextVar

from app.core.db import db, desk_switches_collection
from app.services.module_registry import GROUP_ORDER, REGISTRY

logger = logging.getLogger("desk_switches")

ACTIVE, STOPPING, PAUSED = "active", "stopping", "paused"
STATE_LABELS = {
    ACTIVE: "Active",
    STOPPING: "Stopping — managing open positions",
    PAUSED: "Paused",
}
DRAIN_NOTE = ("Switched OFF in Main Control - open positions are managed to their exits; "
              "no new entries are taken.")

# key -> (label, href). Derived from the registry rather than kept in parallel, because two
# hand-maintained lists of modules WILL drift, and a key missing from one of them is a desk
# whose switch silently controls nothing.
MODULES: dict[str, tuple[str, str]] = {
    k: (m.label, m.href) for k, m in REGISTRY.items()
}

CACHE_TTL = float(os.getenv("DESK_SWITCH_TTL", "20"))
OPEN_TTL = float(os.getenv("DESK_OPEN_TTL", "30"))
PROBE_TIMEOUT_MS = int(os.getenv("DESK_OPEN_PROBE_MS", "4000"))

_cache: dict[str, bool] | None = None
_cache_at: float = 0.0
# key -> (monotonic time, open count or None when the probe could not answer)
_open_cache: dict[str, tuple[float, int | None]] = {}
# key -> monotonic time of the last manage-only cycle, for the status line
_last_drain: dict[str, float] = {}

# Set while a switched-OFF module runs a manage-only cycle. Holds the module key.
_DRAINING: ContextVar[str | None] = ContextVar("module_draining", default=None)


def entries_blocked() -> bool:
    """True inside a cycle that runs only to manage what a switched-off module still holds.

    Engines call this at the point where they would open a position. Outside a draining cycle
    (an ON module, or a manual API call) it is always False."""
    return _DRAINING.get() is not None


def draining_module() -> str | None:
    return _DRAINING.get()


def _invalidate() -> None:
    global _cache, _cache_at
    _cache, _cache_at = None, 0.0
    _open_cache.clear()


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


async def any_on(keys) -> bool:
    """True if at least one of these modules is switched on.

    For a shared service (a market-data stream, a bar store) that several modules read: it
    may stop only once every module that needs it is off."""
    state = await _load()
    return any(state.get(k, True) for k in keys)


# ── open-position probes ───────────────────────────────────────────────────────────


def _collection(ref: str):
    """A probe reference -> a Motor collection (or an async callable).

    "name"               a collection in the main database
    "pkg.module:ATTR"    a collection, or an async function returning a count, that the
                         module owns (desks that keep their book in their own database)."""
    if ":" not in ref:
        return db[ref]
    mod, attr = ref.split(":", 1)
    return getattr(importlib.import_module(mod), attr)


async def _count(ref: str) -> int:
    target = _collection(ref)
    if callable(target) and not hasattr(target, "count_documents"):
        return int(await target())
    return int(await target.count_documents({"status": "OPEN"}, maxTimeMS=PROBE_TIMEOUT_MS))


async def open_positions(key: str, fresh: bool = False) -> int | None:
    """How many positions this module still holds open.

    None when the module has no probe (it holds no positions, or keeps them where this file
    cannot see) or when a probe failed. Cached OPEN_TTL seconds."""
    m = REGISTRY.get(key)
    if m is None or not m.positions:
        return None
    now = _time.monotonic()
    hit = _open_cache.get(key)
    if hit is not None and not fresh and now - hit[0] < OPEN_TTL:
        return hit[1]
    total: int | None = 0
    for ref in m.positions:
        try:
            total += await _count(ref)
        except Exception:  # noqa: BLE001
            logger.warning("[desk_switches] open-position probe %s for %s failed", ref, key,
                           exc_info=True)
            total = None
            break
    _open_cache[key] = (now, total)
    return total


async def state(key: str) -> str:
    """ACTIVE, STOPPING or PAUSED - see the module docstring."""
    if await is_on(key):
        return ACTIVE
    m = REGISTRY.get(key)
    if m is None or not m.drains:
        return PAUSED
    n = await open_positions(key)
    # A failed probe counts as "may still hold something": draining an empty book costs one
    # manage pass, while pausing a full one would leave its stops unwatched.
    if n is None and m.positions:
        return STOPPING
    return STOPPING if (n or 0) > 0 else PAUSED


async def entries_allowed(key: str) -> bool:
    """For desks that take an `entries_allowed` flag and manage exits themselves."""
    return await is_on(key)


async def should_run(key: str) -> bool:
    """For a self-draining loop: run this tick at all? ON, or OFF with something to manage.

    Pair it with `entries_allowed(key)` for the entries flag."""
    return await state(key) != PAUSED


async def gated(key: str, fn, *args, **kwargs):
    """Run a desk's cycle according to its module's state.

    ACTIVE    run normally.
    STOPPING  run inside the drain context, so the engine manages what it holds and opens
              nothing (it must call `entries_blocked()`; registry `drains=True` says it does).
    PAUSED    skip, returning `{}` so the caller's `result.get("opened")` style logging finds
              nothing and stays quiet - no branch, no indentation change at the call site."""
    if await is_on(key):
        return await fn(*args, **kwargs)
    if await state(key) != STOPPING:
        return {}
    token = _DRAINING.set(key)
    try:
        out = await fn(*args, **kwargs)
    finally:
        _DRAINING.reset(token)
        _last_drain[key] = _time.monotonic()
        # Re-count next time: this cycle may have closed the last position, and the module
        # should pause on the very next tick rather than one cache period later.
        _open_cache.pop(key, None)
    return out


# ── writes ─────────────────────────────────────────────────────────────────────────


async def _write(key: str, enabled: bool) -> None:
    await desk_switches_collection.update_one(
        {"_id": key},
        {"$set": {"_id": key, "module": key, "enabled": bool(enabled)}},
        upsert=True)


async def set_module(key: str, enabled: bool) -> dict:
    if key not in REGISTRY:
        raise KeyError(key)
    await _write(key, enabled)
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
        await _write(key, enabled)
        applied[key] = bool(enabled)
    _invalidate()
    if applied:
        logger.warning("[desk_switches] bulk: %s",
                       ", ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in applied.items()))
    return {"applied": applied, "unknown": unknown}


async def set_all(enabled: bool) -> dict:
    for key in REGISTRY:
        await _write(key, enabled)
    _invalidate()
    logger.warning("[desk_switches] ALL = %s", "ON" if enabled else "OFF")
    return {"modules": list(REGISTRY), "enabled": bool(enabled)}


async def set_only(key: str) -> dict:
    """Switch this module ON and every other module OFF.

    The literal reading of "only that module should work" - one click instead of forty."""
    if key not in REGISTRY:
        raise KeyError(key)
    for k in REGISTRY:
        await _write(k, k == key)
    _invalidate()
    logger.warning("[desk_switches] ONLY %s is ON, %d others OFF", key, len(REGISTRY) - 1)
    return {"only": key, "off": [k for k in REGISTRY if k != key]}


# ── read models ────────────────────────────────────────────────────────────────────

NOTE = ("OFF stops a module's new entries at once. A module still holding positions keeps "
        "running in manage-only mode - marks, stops, targets, exits and the mandatory "
        "square-off - and shows STOPPING; once it is flat it PAUSES: no polling, no broker "
        "calls, no writes. Its API refuses new work while off, but exits and closes still go "
        "through, and plain reads of stored rows still answer, so the page keeps showing its "
        "history. Turning it back ON resumes on the next tick.")


# Modules whose work runs in their own container, where "what OFF does" is that container's
# own rule rather than this file's.
_OFF_TEXT: dict[str, str] = {
    "premium_strategies": ("OFF: its container (premium-paper) skips every cycle - paper books stay as they "
                           "are. A missed session is replayed when it is switched back on."),
    "prelive_selling": ("OFF: its API refuses new work. Its own container (prelive-selling) does not read "
                        "this switch yet and keeps running its session."),
}


def _drain_text(m) -> str:
    if m.key in _OFF_TEXT:
        return _OFF_TEXT[m.key]
    if m.drains:
        return "OFF: no new entries; open positions are managed to their exits, then it pauses."
    if m.positions:
        return ("OFF: pauses at once. Open positions are left as they are and are NOT managed "
                "while off - square off first if that matters.")
    return "OFF: pauses at once. It holds no positions."


async def _row(key: str, m, enabled: bool) -> dict:
    st = ACTIVE if enabled else await state(key)
    n = await open_positions(key) if not enabled else None
    last = _last_drain.get(key)
    return {
        "module": key,
        "label": m.label,
        "href": m.href,
        "hrefs": list(m.hrefs),
        "group": m.group,
        "enabled": enabled,
        "state": st,
        "state_label": STATE_LABELS[st],
        "open_positions": n,
        "drains": m.drains,
        "off_behaviour": _drain_text(m),
        "last_drain_s": round(_time.monotonic() - last, 1) if last is not None else None,
        "api_prefixes": list(m.api_prefixes),
        "has_api": m.has_api,
        "shared": m.shared,
        "note": m.note,
    }


async def snapshot() -> dict:
    """Every module with its switch, its state, its group, and the API surface it controls."""
    sw = await _load()
    rows = [await _row(key, m, sw.get(key, True)) for key, m in REGISTRY.items()]
    rows.sort(key=lambda r: (GROUP_ORDER.index(r["group"])
                            if r["group"] in GROUP_ORDER else 99, r["label"]))
    return {
        "modules": rows,
        "groups": list(GROUP_ORDER),
        "total": len(rows),
        "on": sum(1 for r in rows if r["enabled"]),
        "off": sum(1 for r in rows if not r["enabled"]),
        "stopping": sum(1 for r in rows if r["state"] == STOPPING),
        "paused": sum(1 for r in rows if r["state"] == PAUSED),
        "states": dict(STATE_LABELS),
        "note": NOTE,
        # Lets an older page tell this server's OFF semantics from the pre-drain freeze.
        "semantics": "drain",
    }


async def status() -> dict:
    """The compact form every page header polls: key -> state, plus the page map."""
    sw = await _load()
    out = {}
    for key, m in REGISTRY.items():
        enabled = sw.get(key, True)
        st = ACTIVE if enabled else await state(key)
        out[key] = {
            "label": m.label,
            "href": m.href,
            "hrefs": list(m.hrefs),
            "enabled": enabled,
            "state": st,
            "open_positions": None if enabled else await open_positions(key),
            "drains": m.drains,
            "real_money": key in REAL_MONEY,
            "group": m.group,
            "shared": m.shared,
            # So the browser can serve a PAUSED module's frozen rows from memory instead of
            # re-asking the server on every poll.
            "api_prefixes": list(m.api_prefixes),
        }
    return {"modules": out, "states": dict(STATE_LABELS), "semantics": "drain"}


# Switching one of these off asks for an explicit confirmation in the UI.
REAL_MONEY: frozenset[str] = frozenset({"live_trading"})
