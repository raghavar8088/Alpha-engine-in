"""Per-module ON/OFF switches for every auto-trading desk.

Turning a module OFF stops its scheduler cycle, and because each desk fetches its own
market data INSIDE that cycle, one gate stops both the trading and the data pulls. That is
the whole reason the switch sits at the cycle boundary rather than inside each engine:
gating the order-placing step alone would leave the desk still hammering Angel's quote and
candle endpoints for a book it is not allowed to trade, which on this box is the scarcer
resource of the two.

WHAT A SWITCH DOES NOT DO
-------------------------
It does not close anything. An OFF module stops taking NEW positions and stops polling;
positions it already holds are left exactly as they are, untouched and unmanaged. That is
deliberate and it is the one sharp edge here — a desk switched off mid-session keeps its
open book frozen at the last mark, so an open position will not hit its own stop while the
switch is off. Square off first if that matters. The alternative (force-closing on OFF)
would turn a UI toggle into an irreversible trading action, which is worse.

DEFAULT IS ON
-------------
An absent record reads as ON, so this ships inert: every desk behaves exactly as it did
before anyone touches a switch. Only an explicit OFF changes anything.

THE CACHE IS NOT OPTIONAL
-------------------------
`is_on` is called once per desk per scheduler tick — a dozen desks every ~60s, plus the
separate commodity loops. Reading Mongo each time would add a round trip per desk per tick
to a cluster this app has already had trouble with. State changes come from one place (the
API), so the cache is invalidated on write and is never stale in practice.
"""

import logging
import os
import time as _time

from app.core.db import desk_switches_collection

logger = logging.getLogger("desk_switches")

# key -> (label, sidebar href). The key is what the scheduler gates on and what the API
# takes; the label and href exist so the UI can render this list without a second source
# of truth drifting away from it.
MODULES: dict[str, tuple[str, str]] = {
    # ── the shared intraday loop ────────────────────────────────────────────────
    "intraday_lab":      ("Intraday Stocks · Tournament", "/intraday-stocks"),
    "live_intraday":     ("Intraday Stocks · Live Intraday books", "/intraday-stocks"),
    "pattern":           ("Intraday Stocks · Patterns", "/intraday-stocks"),
    "pattern_books":     ("Intraday Stocks · Paper Trade books", "/intraday-stocks"),
    "live_trading":      ("Live Trading (REAL MONEY)", "/live-trading"),
    "nifty_scalp":       ("NIFTY 50 Option Scalping", "/nifty-scalp"),
    "swing_trading":     ("Swing Trading", "/swing-trading"),
    "stock_desk":        ("Stock Pre-Live (buying + selling)", "/stock-prelive-buying"),
    "zero_hero":         ("Zero Hero Trades", "/zero-hero"),
    "live_paper":        ("Live Paper Buying", "/live"),
    "morning_momentum":  ("Morning Momentum", "/momentum"),
    "momentum_engine":   ("Momentum", "/momentum"),
    "fno_stock_roll":    ("F&O Stock Auto-Roll", "/fno-positions"),
    # ── desks on their own loops ────────────────────────────────────────────────
    "commodity":         ("Commodity Trading", "/commodity"),
    "commodity_prelive": ("Pre-Live Commodity Trading", "/commodity-prelive"),
    "ath_trading":       ("All Time High Trading", "/all-time-high-trading"),
    "trending_stocks":   ("Trending Stocks", "/trending-stocks"),
    "long_horizon":      ("Long-Horizon Desk", "/long-horizon"),
    "fno_auto_roll":     ("F&O NIFTY Auto-Roll", "/fno-positions"),
    "screener":          ("Stock Screener (scheduled rebuilds)", "/stock-screener"),
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
        # A switch lookup must never be able to stop the desks. If the store is
        # unreachable the safe reading is "carry on as before", not "halt everything".
        logger.warning("[desk_switches] could not read switches — treating all as ON",
                       exc_info=True)
        return dict(_cache or {})
    _cache, _cache_at = out, now
    return out


async def is_on(key: str) -> bool:
    """True unless someone has explicitly switched this module off."""
    return (await _load()).get(key, True)


async def set_module(key: str, enabled: bool) -> dict:
    if key not in MODULES:
        raise KeyError(key)
    await desk_switches_collection.update_one(
        {"_id": key},
        {"$set": {"_id": key, "module": key, "enabled": bool(enabled)}},
        upsert=True)
    _invalidate()
    logger.warning("[desk_switches] %s = %s", key, "ON" if enabled else "OFF")
    return {"module": key, "enabled": bool(enabled)}


async def set_all(enabled: bool) -> dict:
    for key in MODULES:
        await desk_switches_collection.update_one(
            {"_id": key},
            {"$set": {"_id": key, "module": key, "enabled": bool(enabled)}},
            upsert=True)
    _invalidate()
    logger.warning("[desk_switches] ALL = %s", "ON" if enabled else "OFF")
    return {"modules": list(MODULES), "enabled": bool(enabled)}


async def snapshot() -> dict:
    state = await _load()
    rows = [{"module": k, "label": lbl, "href": href, "enabled": state.get(k, True)}
            for k, (lbl, href) in MODULES.items()]
    return {
        "modules": rows,
        "total": len(rows),
        "on": sum(1 for r in rows if r["enabled"]),
        "off": sum(1 for r in rows if not r["enabled"]),
        "note": ("OFF stops a module's scheduler cycle, which is also what fetches its "
                 "market data — so both the polling and the paper trading stop. Positions "
                 "already open are left untouched and are NOT managed while off; square "
                 "off first if that matters."),
    }


async def gated(key: str, fn, *args, **kwargs):
    """Run a desk's cycle only if its module is switched on.

    Returns `{}` when off, so the caller's `result.get("opened")` style logging simply
    finds nothing and stays quiet — no branch, no indentation change at the call site."""
    if not await is_on(key):
        return {}
    return await fn(*args, **kwargs)
