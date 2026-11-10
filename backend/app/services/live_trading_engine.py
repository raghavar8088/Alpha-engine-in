"""Live Trading desk — REAL MONEY: Selected ORB 15-min, copied from the Intraday Stocks tournament.

Since 10 Nov 2026 (the owner's decision) this desk trades ONE strategy: the tournament's
pre-registered Selected ORB 15-min (iv2_orb_sel15). When the tournament's paper engine opens an
iv2_orb_sel15 position, this desk places the same-side REAL Angel One MIS market order within
seconds (`copy_loop`), holds it to the same stop (the opposite edge of the 09:15-09:30 range),
and squares it off with the session (15:05 in closing-auction stocks, 15:12 otherwise), or as
soon as the tournament's own position closes. One real position at a time, about Rs 50,000 of
notional on Angel's intraday leverage. The fourteen earlier strategies and their record were
removed at the owner's request. Angel is also the price feed; Dhan only fills quote gaps and
never receives an order. (This needs an Angel TRADING API key.)

Safety model (mirrors the Antigravity Live Engine the user already runs):
  * ARMED flag — ships OFF. Nothing is ordered until the desk is armed. Disarming stops
    NEW entries but open positions keep being managed to their target/stop/EOD.
  * KILL SWITCH — halts all new orders instantly, independent of the armed flag.
  * Per-strategy ENABLE — a toggle per strategy; a disabled strategy takes no new entries.
  * ₹10k per-strategy cap AND an ₹80k desk-wide ceiling, both server-enforced.
  * Auto-disarm after MAX_CONSECUTIVE_REJECTS failed orders in a row (a crash loop can
    never keep firing rejected orders unattended).
  * PANIC close-all — squares off every open position, disarms, and trips the kill switch.
  * ARMING GATE (2026-10-10) — arming is REFUSED unless every enabled strategy holds a
    CONFIRMED verdict in the incubation registry, and re-checked every scan. See
    `arming_check`.
  * BROKER FIRST (2026-10-10) — before any exit decision the desk reads Angel's own
    position book. A position the broker has already closed is closed in the ledger at the
    broker's fill, with NO order sent. See `reconcile_broker_closes`.
  * CHARGES ON EVERY CLOSE (2026-10-10) — realised P&L is net of Angel's charges, the
    same rate card every paper desk uses; it used to be gross, so the real-money ledger
    was the one ledger in the app that understated its losses.

Real cash-equity reality: you cannot carry a short position overnight, and a losing intraday
short must be covered same day. So every real order here is INTRADAY (MIS) and ALL positions
square off at EOD — the swing/intraday distinction the paper desk carries does not survive
contact with a real broker for shorts, so this desk is honest about being same-day.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from anyio import to_thread

from app.core.db import (
    instruments_collection,
    intraday_lab_positions_collection,
    live_trading_equity_collection,
    live_trading_flags_collection,
    live_trading_positions_collection,
    live_trading_scores_collection,
    live_trading_state_collection,
    live_trading_trades_collection,
)
from app.services.angel_client import angel_client
from app.services.angel_fees import round_trip
from app.services import intraday_session as session
from app.services.call_engine import IST
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import _equity_quote_map, _size
from app.services.live_intraday_engine import ENTRY_CUTOFF_HHMM
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("live_trading")

STATE_ID = "engine"

# ── the strategy: Selected ORB 15-min, copied from the tournament ─────────────────
#
# THE OWNER'S DECISION (10 Nov 2026): this desk trades only the Intraday Stocks tournament's
# Selected ORB 15-min, the one candidate with a pre-registered expectation, a positive two-year
# replay and a positive forward record (the others lose over two years after costs). It trades
# it the way the tournament does on paper: same signal, same side, same stop, same session
# square-off. Real positions are COPIED from the tournament's paper positions, so the two
# cannot drift apart.
#
# SIZE: Angel charges about Rs 51 a round trip on a Rs 10,000 position (0.51%) but about Rs 67
# on Rs 50,000 (0.13%), so small positions lose to charges alone. One position at a time, about
# Rs 50,000 of notional on Angel's intraday (MIS) leverage, never more than MIS_LEVERAGE x the
# cash Angel reports.


@dataclass(frozen=True)
class CopyStrategy:
    strategy_id: str
    name: str
    category: str
    is_anti: bool = False


COPY_SOURCE = "iv2_orb_sel15"
SELECTED = [CopyStrategy(COPY_SOURCE, "Selected ORB 15-min (top-5 expected move)", "momentum")]
SELECTED_BY_ID = {ls.strategy_id: ls for ls in SELECTED}
COPY_NOTIONAL = float(os.getenv("LIVE_TRADING_COPY_NOTIONAL", "50000"))     # one position, ~Rs 50k notional
MIS_LEVERAGE = float(os.getenv("LIVE_TRADING_MIS_LEVERAGE", "4.5"))        # Angel gives up to 5x on MIS
MAX_OPEN_POSITIONS = 1                                                       # one real position at a time
COPY_WINDOW_S = float(os.getenv("LIVE_TRADING_COPY_WINDOW_S", "180"))       # copy a paper entry only this fresh
COPY_MAX_DRIFT_R = 0.5      # skip when the price has run more than half the stop distance since the paper fill
COPY_TICK_S = float(os.getenv("LIVE_TRADING_COPY_TICK_S", "10"))            # the fast loop's cadence
COPY_LOOP_ON = os.getenv("LIVE_TRADING_COPY_LOOP", "on").lower() != "off"   # off: only the 3-minute tick copies
COPY_START_DELAY_S = 45.0                                                    # let the app finish starting
COPY_SESSION = ("09:15", "15:25")                                            # IST, the fast loop's hours
PER_STRATEGY_ALLOCATION = COPY_NOTIONAL
POSITION_NOTIONAL = COPY_NOTIONAL
DESK_CEILING = COPY_NOTIONAL * MAX_OPEN_POSITIONS
MAX_CONSECUTIVE_REJECTS = 3        # auto-disarm after this many failed real orders in a row
PRODUCT_TYPE = "INTRADAY"          # MIS: intraday shorts allowed, everything squares off EOD
DAILY_LOSS_BREAKER_PCT = 0.03      # same 3% desk breaker as the paper desk
INITIAL_CAPITAL = DESK_CEILING     # the desk's notional ceiling, not money held (the real account is reported apart)

# THE ARMING GATE IS OVERRIDDEN FOR THIS STRATEGY by the owner's explicit decision of 10 Nov 2026:
# it may place real orders without a CONFIRMED forward verdict. The override is per strategy and
# written here, so the gate still stands for anything added later, and the page shows it.
OWNER_OVERRIDE = {
    COPY_SOURCE: "the owner's decision of 10 Nov 2026 (real orders without a CONFIRMED forward verdict)",
}

class LiveTradingError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


# ── engine state: armed / kill switch / reject streak ───────────────────────────


async def get_state() -> dict:
    st = await live_trading_state_collection.find_one({"_id": STATE_ID}) or {}
    return {
        "armed": bool(st.get("armed", False)),
        "kill_switch": bool(st.get("kill_switch", False)),
        "consecutive_rejects": int(st.get("consecutive_rejects", 0)),
        "max_consecutive_rejects": MAX_CONSECUTIVE_REJECTS,
        "armed_at": st.get("armed_at").isoformat() if st.get("armed_at") else None,
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_opened": int(st.get("last_opened", 0)),
        "last_managed": int(st.get("last_managed", 0)),
        "last_notes": st.get("last_notes", []),
        "disarmed_reason": st.get("disarmed_reason"),
        "broker_connected": bool(st.get("broker_connected", False)),
    }


# ── the arming gate ──────────────────────────────────────────────────────────────
#
# WHY ARMING HAS PRECONDITIONS. This desk placed 78 REAL orders between 10 and 20 August
# 2026 on strategies that had never passed a forward test: eight picks from the first
# intraday catalog (retired by the 2 October audit; seven of them swing rules forced into
# same-day square-off) and six "extras". Nothing stopped it, because arming was a bare
# flag. Arming is now refused unless EVERY ENABLED strategy holds a CONFIRMED verdict in
# the incubation registry (`intraday_v2_registry`): an expectation written down before the
# forward record existed, tested against at least 40 forward paper trades on thresholds
# frozen at registration. A good-looking leaderboard row is not that.
#
# None of the fourteen strategies below is registered, so this desk cannot be armed today.
# That is the intended outcome. A strategy reaches real money by running as a paper
# strategy, passing the walk-forward gate, being registered, and confirming forward.
# (Until 10 Nov 2026: the owner then overrode the gate for the one strategy this desk now
# trades, by name, in OWNER_OVERRIDE. Everything else still needs its verdict.)
#
# The verdict is re-checked on EVERY scan, not only when arming: a CONFIRMED strategy can
# later FAIL its forward test, and the desk must stop ordering it on the cycle that happens.
#
# Bypassing it takes `LIVE_TRADING_ARMING_GATE=off` in the server's environment and a
# redeploy — deliberately not a button. Even then the ledger checks below still apply:
# they protect against sending orders for positions the broker does not hold.
ARMING_GATE = os.getenv("LIVE_TRADING_ARMING_GATE", "on").strip().lower() not in (
    "off", "0", "false", "no")
if not ARMING_GATE:
    logger.critical("[live_trading] ARMING GATE DISABLED by LIVE_TRADING_ARMING_GATE — the "
                    "real-money desk can be armed on strategies with no forward verdict")

_VERDICT_TEXT = {
    "NOT_REGISTERED": "never registered for a forward test — no evidence it works",
    "INCUBATING": "forward test still running",
    "FAILED": "FAILED its forward test",
    "CONFIRMED": "confirmed by its forward test",
}


async def _verdicts(strategy_ids: list[str]) -> dict[str, dict]:
    """Registry entries for these strategies, keyed by id. Missing = never registered."""
    from app.services.intraday_v2_registry import registry
    out: dict[str, dict] = {}
    async for r in registry.find({"_id": {"$in": list(strategy_ids)}},
                                 {"status": 1, "decided_at": 1, "forward": 1}):
        out[r["_id"]] = r
    return out


def _verdict_of(v: dict | None) -> str:
    return (v or {}).get("status") or "NOT_REGISTERED"


async def _validated_ids() -> set[str]:
    """Strategies allowed to place real orders right now."""
    if not ARMING_GATE:
        return set(SELECTED_BY_ID)
    vs = await _verdicts(list(SELECTED_BY_ID))
    allowed = {sid for sid, v in vs.items() if _verdict_of(v) == "CONFIRMED"}
    return allowed | {sid for sid in OWNER_OVERRIDE if sid in SELECTED_BY_ID}


async def arming_check() -> dict:
    """Everything that must hold before this desk may be armed, and which of it does.

    Two kinds of blocker. VERDICT blockers (an enabled strategy without a CONFIRMED
    verdict) are what the gate exists for. LEDGER blockers (an earlier session's position
    still OPEN, a position that disagrees with Angel's own book) are about the desk's
    picture of reality: arming on a wrong picture risks orders for positions the broker
    does not hold. The environment switch bypasses only the first kind."""
    enabled = await _enabled_map()
    verdicts = await _verdicts(list(SELECTED_BY_ID))
    rows = []
    for ls in SELECTED:
        status = _verdict_of(verdicts.get(ls.strategy_id))
        override = OWNER_OVERRIDE.get(ls.strategy_id)
        plain = _VERDICT_TEXT.get(status, status.lower())
        rows.append({
            "strategy_id": ls.strategy_id, "name": ls.name,
            "enabled": enabled.get(ls.strategy_id, True),
            "verdict": status, "validated": status == "CONFIRMED" or bool(override), "override": override,
            "reason": (f"gate overridden by {override}; its own forward test: {plain}"
                       if override and status != "CONFIRMED" else plain),
        })
    verdict_blockers: list[str] = []
    ledger_blockers: list[str] = []
    warnings: list[str] = []

    on = [r for r in rows if r["enabled"]]
    if not on:
        verdict_blockers.append("No strategy is enabled, so there is nothing to trade.")
    bad = [r for r in on if not r["validated"]]
    if bad:
        by_reason: dict[str, list[str]] = {}
        for r in bad:
            by_reason.setdefault(r["reason"], []).append(r["name"])
        parts = [f"{len(names)} {why} ({', '.join(names[:4])}{'…' if len(names) > 4 else ''})"
                 for why, names in by_reason.items()]
        verdict_blockers.append(
            f"{len(bad)} of {len(on)} enabled strategies have no CONFIRMED forward verdict: "
            + "; ".join(parts) + ". Disable them, or let them earn one.")

    state = await get_state()
    if state["kill_switch"]:
        ledger_blockers.append("The kill switch is on.")
    stale = await live_trading_positions_collection.count_documents(
        {"status": "OPEN", "opened_on": {"$lt": _today_ist().isoformat()}})
    if stale:
        ledger_blockers.append(
            f"{stale} real position(s) from an earlier session are still OPEN in the ledger. "
            "MIS positions cannot outlive their session, so the ledger is wrong about them.")
    mismatch = await live_trading_positions_collection.count_documents(
        {"reconcile_status": "mismatch", "status": "OPEN"})
    if mismatch:
        ledger_blockers.append(
            f"{mismatch} open real position(s) disagree with Angel's own position book.")
    needs_note = await live_trading_positions_collection.count_documents(
        {"reconcile_status": "needs_contract_note"})
    if needs_note:
        warnings.append(
            f"{needs_note} past real trade(s) carry estimated prices or charges until Angel's "
            "contract notes are imported (see scripts/live_trading_contract_notes.py).")
    for r in rows:
        if r.get("override") and r["verdict"] != "CONFIRMED" and r["enabled"]:
            warnings.insert(0, f"The forward-test gate is OVERRIDDEN for {r['name']}: {r['override']}.")
    if not ARMING_GATE:
        warnings.insert(0, "The arming gate is DISABLED on the server "
                           "(LIVE_TRADING_ARMING_GATE=off): verdicts are not being enforced.")

    allowed = not ledger_blockers and (ARMING_GATE is False or not verdict_blockers)
    return {
        "allowed": allowed, "gate": "on" if ARMING_GATE else "off",
        "blockers": ledger_blockers + (verdict_blockers if ARMING_GATE else []),
        "warnings": warnings + ([] if ARMING_GATE else
                                [f"(would block) {b}" for b in verdict_blockers]),
        "strategies": rows,
        "validated_enabled": sum(1 for r in on if r["validated"]),
        "overridden_enabled": sum(1 for r in on if r.get("override") and r["verdict"] != "CONFIRMED"),
        "enabled": len(on),
    }


def arming_refusal_text(check: dict) -> str:
    """One readable string — the page shows the API's `detail` verbatim."""
    return "Live Trading cannot be armed. " + " ".join(check["blockers"])


async def set_armed(armed: bool, reason: str | None = None) -> dict:
    if armed:
        check = await arming_check()
        if not check["allowed"]:
            await live_trading_state_collection.update_one({"_id": STATE_ID}, {"$set": {
                "last_arm_refusal": {"at": _now(), "blockers": check["blockers"]}}}, upsert=True)
            logger.warning("[live_trading] ARMING REFUSED: %s", " | ".join(check["blockers"]))
            raise LiveTradingError(arming_refusal_text(check))
    upd: dict = {"armed": bool(armed), "updated_at": _now()}
    if armed:
        upd.update({"armed_at": _now(), "consecutive_rejects": 0, "disarmed_reason": None})
    else:
        upd["disarmed_reason"] = reason
    await live_trading_state_collection.update_one({"_id": STATE_ID}, {"$set": upd}, upsert=True)
    logger.warning("[live_trading] ARMED=%s (%s)", armed, reason or "manual")
    return await get_state()


async def set_kill_switch(active: bool) -> dict:
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"kill_switch": bool(active), "updated_at": _now()}}, upsert=True
    )
    logger.warning("[live_trading] KILL SWITCH=%s", active)
    return await get_state()


# Phrases Angel uses when it is declining ONE INSTRUMENT rather than reporting that
# something is wrong with the account or the session. Matched loosely because the wording
# is prose, not an error code, and it varies by ban type.
SYMBOL_REFUSAL_MARKERS = (
    "cautionary",
    "surveillance",
    "not allowed to trade",
    "not permitted",
    "banned",
    "ban period",
    "asm",
    "gsm",
    "trade to trade",
    "t2t",
    "blocked for trading",
    "restricted",
)

# Symbols the exchange refused today. Reset with the session, because a listing added on
# Monday is usually gone by the next review and hard-coding a blocklist would outlive it.
_refused_symbols: dict[str, str] = {}


def _is_symbol_refusal(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in SYMBOL_REFUSAL_MARKERS)


def refused_symbols() -> dict[str, str]:
    """Names the exchange declined this session, and why."""
    return dict(_refused_symbols)


async def _register_reject() -> None:
    st = await get_state()
    n = st["consecutive_rejects"] + 1
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"consecutive_rejects": n}}, upsert=True
    )
    if n >= MAX_CONSECUTIVE_REJECTS:
        await set_armed(False, reason=f"auto-disarmed after {n} consecutive order rejects")


async def _clear_rejects() -> None:
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"consecutive_rejects": 0}}, upsert=True
    )


# ── per-strategy enable flags ────────────────────────────────────────────────────


async def _enabled_map() -> dict[str, bool]:
    flags = {f["strategy_id"]: bool(f.get("enabled", True)) async for f in live_trading_flags_collection.find({})}
    return {ls.strategy_id: flags.get(ls.strategy_id, True) for ls in SELECTED}


async def set_strategy_enabled(strategy_id: str, enabled: bool) -> dict:
    if strategy_id not in SELECTED_BY_ID:
        raise LiveTradingError(f"Unknown strategy '{strategy_id}'")
    await live_trading_flags_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "enabled": bool(enabled), "updated_at": _now()}},
        upsert=True,
    )
    return {"strategy_id": strategy_id, "enabled": bool(enabled)}


# ── capital, scoped to this desk's own collections ──────────────────────────────


async def _deployed_capital(strategy_id: str) -> float:
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _desk_deployed() -> float:
    total = 0.0
    async for p in live_trading_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1}):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl(strategy_id: str) -> float:
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    """The tighter of two real limits, in NOTIONAL rupees: this strategy's own one-position
    ceiling, and what the ACCOUNT's cash can fund on MIS at MIS_LEVERAGE.

    The account limit has to be desk-wide. Checking each strategy against Angel's balance
    separately let eleven idle strategies each treat the same rupees as theirs; fired in the
    same cycle they would have ordered several times the cash on hand, been rejected on
    margin, and auto-disarmed the desk for a shortfall that was our arithmetic rather than
    the broker's."""
    # Notional room (10 Nov 2026): the strategy's one-position ceiling minus what is open, and what
    # Angel's cash can fund on MIS at MIS_LEVERAGE; positions opened after the balance was read count
    # at their margin.
    slice_left = PER_STRATEGY_ALLOCATION - await _deployed_capital(strategy_id)
    bal = await account_balance()
    if not bal["ok"]:
        return 0.0            # cannot confirm the money exists, so do not spend it
    unseen = await _desk_unseen_notional(bal.get("fetched_at"))
    desk_room = (bal["available"] - unseen / MIS_LEVERAGE) * MIS_LEVERAGE
    return max(0.0, min(slice_left, desk_room))


async def _desk_unseen_notional(balance_fetched_at: str | None) -> float:
    """Notional opened AFTER the cached balance was read.

    Only these are missing from `availablecash`; everything older is already reflected in
    it as blocked margin, and subtracting those again would charge the desk twice for the
    same positions. Notional overstates what MIS actually consumes, which makes this
    deliberately conservative for the seconds until the next balance refresh — the right
    direction to be wrong in when the alternative is an order the account cannot fund."""
    if not balance_fetched_at:
        return 0.0
    try:
        since = datetime.fromisoformat(balance_fetched_at)
    except (TypeError, ValueError):
        return 0.0
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": since}}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed") or 0.0
    return total


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in live_trading_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


# ── the real account, not a constant ──────────────────────────────────────────
#
# This desk spends ACTUAL money, so the two numbers that decide whether it may keep
# trading — how much cash exists, and how large a loss trips the breaker — have to come
# from Angel rather than from INITIAL_CAPITAL. A static Rs80,000 breaker on an account
# holding Rs10,300 is not a safety limit; it would let the account be emptied without
# ever tripping. Cached briefly because it is read several times per cycle and the
# balance does not move between those reads.

_BALANCE_TTL = float(os.getenv("LIVE_TRADING_BALANCE_TTL", "60"))
_balance_cache: dict = {"at": 0.0, "data": None}


async def account_balance(force: bool = False) -> dict:
    """Live Angel RMS funds. `available` is spendable cash; `net` is the account value.

    On failure this returns `ok: False` with zero cash rather than falling back to a
    made-up figure — the desk then refuses to open, which is the correct behaviour when
    it cannot confirm the money is there."""
    now = time.time()
    cached = _balance_cache["data"]
    if not force and cached and now - _balance_cache["at"] < _BALANCE_TTL:
        return cached
    try:
        f = await angel_client.funds()
        data = {
            "ok": True,
            "available": float(f.get("availablecash") or 0.0),
            "net": float(f.get("net") or 0.0),
            "utilised": float(f.get("utiliseddebits") or 0.0),
            "m2m_realized": float(f.get("m2mrealized") or 0.0),
            "m2m_unrealized": float(f.get("m2munrealized") or 0.0),
            "fetched_at": _now().isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[live_trading] could not read Angel balance: %s", exc)
        data = {"ok": False, "available": 0.0, "net": 0.0, "utilised": 0.0,
                "m2m_realized": 0.0, "m2m_unrealized": 0.0,
                "error": str(exc)[:160], "fetched_at": _now().isoformat()}
    _balance_cache.update({"at": now, "data": data})
    return data


async def breaker_state() -> dict:
    """Daily-loss breaker scaled to the REAL account value, falling back to the configured
    desk size only when Angel cannot be reached — and in that case the desk is not opening
    anything anyway."""
    pnl = await today_pnl()
    bal = await account_balance()
    base = bal["net"] if bal["ok"] and bal["net"] > 0 else INITIAL_CAPITAL
    limit = DAILY_LOSS_BREAKER_PCT * base
    return {
        "breaker_tripped": pnl <= -limit,
        "today_pnl": round(pnl, 2),
        "daily_loss_limit": round(limit, 2),
        "daily_loss_pct": DAILY_LOSS_BREAKER_PCT,
        "breaker_basis": round(base, 2),
        "breaker_basis_source": "angel_net" if (bal["ok"] and bal["net"] > 0) else "configured",
        "angel_balance": bal,
    }


async def _update_score(strategy_id: str) -> None:
    ls = SELECTED_BY_ID.get(strategy_id)
    if ls is None:
        return
    closed = [
        p async for p in live_trading_positions_collection.find(
            {"strategy_id": strategy_id, "status": "CLOSED"}, {"realized_pnl": 1}
        )
    ]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net_pnl = sum(p.get("realized_pnl") or 0 for p in closed)
    await live_trading_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": trades, "wins": wins, "win_rate": round(wins / trades, 4) if trades else 0.0,
            "net_pnl": round(net_pnl, 2), "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
            "updated_at": _now(),
        }},
        upsert=True,
    )


# ── money in, money out ──────────────────────────────────────────────────────────


def _charge(entry: float, exit_: float, qty: int, side: str) -> dict:
    """Gross, Angel's charges, and net for one real round trip.

    The real-money ledger recorded GROSS P&L until 2026-10-10 — the one ledger in the app
    that left out the broker's charges, on the one desk where they are actually paid. Uses
    the same `angel_fees.round_trip` rate card the paper desks are charged on, which was
    checked against Angel's published card to the rupee. The contract note remains the
    final word; `charges_basis` says which of the two a row carries."""
    sign = 1 if side == "BUY" else -1
    gross = round(sign * (float(exit_) - float(entry)) * int(qty), 2)
    fb = round_trip(entry_price=float(entry), exit_price=float(exit_), qty=int(qty),
                    side=side, product=PRODUCT_TYPE)
    return {"gross_pnl": gross, "fees": fb.total, "fee_breakdown": fb.as_dict(),
            "realized_pnl": round(gross - fb.total, 2), "charges_basis": "rate_card"}


# ── real Angel One order placement ───────────────────────────────────────────────


async def _place_angel_order(inst: dict, side: str, qty: int) -> str | None:
    """Place a REAL market INTRADAY order via Angel One SmartAPI. Returns the Angel orderid,
    or None on any failure — rejected, not permitted (a non-trading API key), or no id — so
    the caller can refuse to record a position that never actually opened.

    Angel needs BOTH the symboltoken and the tradingsymbol (e.g. "RELIANCE-EQ"); the token
    map stamps `angel_tradingsymbol`, and we fall back to "<symbol>-EQ" for NSE cash."""
    token = inst.get("angel_token")
    if not token:
        logger.error("[live_trading] no Angel token for %s — cannot place order", inst.get("symbol"))
        return None
    exchange = inst.get("angel_exchange") or "NSE"
    tradingsymbol = inst.get("angel_tradingsymbol") or f"{inst.get('symbol')}-EQ"
    try:
        body = await angel_client.place_order(
            tradingsymbol=tradingsymbol,
            symboltoken=str(token),
            transactiontype=side,
            exchange=exchange,
            quantity=int(qty),
            ordertype="MARKET",
            producttype=PRODUCT_TYPE,
            duration="DAY",
            price=0,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        sym = inst.get("symbol")
        if _is_symbol_refusal(msg):
            # The exchange declining one name is not a desk fault. Remember it, skip it for
            # the rest of the session, and do NOT touch the auto-disarm counter.
            _refused_symbols[sym] = msg[:160]
            logger.warning("[live_trading] %s refused by the exchange, skipping for today: %s",
                           sym, msg[:120])
            return "SKIP"
        logger.exception("[live_trading] Angel order FAILED: %s %s x%s", side, sym, qty)
        return None
    oid = (body.get("data") or {}).get("orderid") if isinstance(body, dict) else None
    if not oid:
        logger.error("[live_trading] Angel order returned no orderid: %s", body)
        return None
    return str(oid)


async def _open_position(ls, symbol: str, inst: dict, signal, ltp_source: str,
                         fill_price: float | None = None, parent: dict | None = None) -> bool:
    """Place one REAL order. Sized on the live quote, never on the signal's bar price.

    The paper twin sized on `signal.entry`, a daily bar's price that does not move
    intraday, and that produced positions opened at levels the market had long left (see
    `live_intraday_engine._open_position`). Here the consequence would be a real order for
    the wrong QUANTITY and a Rs 10,000 cap measured against a price nobody is trading at,
    so the market price is used when one is available."""
    if symbol in _refused_symbols:
        return False          # already declined by the exchange this session
    if await live_trading_positions_collection.find_one(
        {"strategy_id": ls.strategy_id, "symbol": symbol, "status": "OPEN"}
    ):
        return False  # one open position per symbol per strategy
    sig_entry = float(signal.entry or 0.0)
    ref = float(fill_price or 0.0) or sig_entry
    if ref <= 0:
        return False
    cash = await _available_cash(ls.strategy_id)
    qty = _size(ref, POSITION_NOTIONAL, cash)
    if qty < 1:
        return False
    new_notional = ref * qty
    # ₹80k desk-wide ceiling (the per-strategy ₹10k cap is already in `cash` above)
    if await _desk_deployed() + new_notional > DESK_CEILING + 1:
        return False

    # REAL order via Angel One — only record the position if Angel accepted it
    order_id = await _place_angel_order(inst, signal.side, qty)
    if order_id == "SKIP":
        return False          # exchange said no to this SYMBOL; the desk stays armed
    if not order_id:
        await _register_reject()
        return False
    await _clear_rejects()

    await live_trading_positions_collection.insert_one({
        "position_id": uuid4().hex[:12],
        "strategy_id": ls.strategy_id, "strategy_name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
        "symbol": symbol, "display_name": symbol,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
            "angel_token": inst.get("angel_token"), "angel_exchange": inst.get("angel_exchange"),
            "angel_tradingsymbol": inst.get("angel_tradingsymbol"),
        },
        "side": signal.side, "entry_price": round(ref, 2), "qty": qty,
        # `entry_price` is provisional until reconcile_fills() replaces it with the real
        # fill; `signal_price` preserves what the strategy actually asked for.
        "signal_price": round(signal.entry, 2),
        "entry_fill_price": None, "exit_fill_price": None, "entry_slippage": None,
        "capital_deployed": round(ref * qty, 2),
        "target": round(signal.target, 2) if signal.target is not None else None,
        "stoploss": round(signal.stoploss, 2),
        "ltp": round(ref, 2), "ltp_source": ltp_source,
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(signal.confidence, 2), "rationale": signal.rationale,
        "product_type": PRODUCT_TYPE, "mode": "real",
        "parent_id": (parent or {}).get("position_id"), "copied_from": "tournament" if parent else None,
        "parent_entry_price": (parent or {}).get("entry_price"), "parent_opened_at": (parent or {}).get("opened_at"),
        "entry_order_id": order_id, "exit_order_id": None,
        # entry_price is the reference/signal price; the true fill price comes from Angel and
        # is not reconciled into this ledger in v1 (matches the app's existing LiveExecutor).
        "opened_at": _now(), "opened_on": _today_ist().isoformat(), "updated_at": _now(), "closed_at": None,
    })
    logger.warning("[live_trading] REAL ENTRY %s %s x%s @~%.2f (signal %.2f, order %s)",
                   signal.side, symbol, qty, ref, sig_entry, order_id)
    return True


# ── scan (gated) ─────────────────────────────────────────────────────────────────


async def scan_cycle(dhan: DhanClient | None) -> dict:
    state = await get_state()
    if not state["armed"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "Live Trading is DISARMED — no real orders are placed. Arm the desk to trade with real money."]}
    if state["kill_switch"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "KILL SWITCH is ON — new orders halted. Open positions are still managed."]}
    if not angel_client.configured():
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "Angel One is not configured — cannot place real orders."]}
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L Rs{breaker['today_pnl']:,.0f} crossed the "
            f"Rs{breaker['daily_loss_limit']:,.0f} limit. No new positions this session; open ones still managed."]}

    # The arming gate again, every scan: a verdict can change while the desk is armed (a
    # CONFIRMED strategy can later FAIL), and an `armed` flag written straight into the
    # database never went through `set_armed` at all.
    validated = await _validated_ids()
    enabled_now = await _enabled_map()
    if not any(enabled_now.get(sid, True) for sid in validated):
        await set_armed(False, reason="arming gate: no enabled strategy holds a CONFIRMED verdict")
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "DISARMED by the arming gate — no enabled strategy holds a CONFIRMED forward verdict."]}

    async with _entry_lock:
        return await _copy_entries(dhan, validated, enabled_now)


_entry_lock = asyncio.Lock()
_copy_waiting: dict[str, str] = {}      # tournament position id -> why it is still waiting (this process)


def copy_check(parent: dict, ltp: float | None, open_positions: int,
               now_utc: datetime) -> tuple[str | None, bool]:
    """(why not, final) for copying a tournament position now; (None, True) means copy it.

    A FINAL reason is recorded once and the position is never looked at again. A passing one
    (no quote yet, a real position already open, the price has run) is retried on the next
    tick for as long as the paper entry is younger than COPY_WINDOW_S."""
    entry, stop = float(parent.get("entry_price") or 0.0), float(parent.get("stoploss") or 0.0)
    if entry <= 0 or stop <= 0 or entry == stop or parent.get("side") not in ("BUY", "SELL"):
        return "the paper position has no usable side, entry or stop", True
    opened = parent.get("opened_at")
    if not isinstance(opened, datetime):
        return "the paper position has no opening time", True
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    if (now_utc - opened).total_seconds() > COPY_WINDOW_S:
        return f"the paper entry is more than {COPY_WINDOW_S:.0f} s old", True
    if open_positions >= MAX_OPEN_POSITIONS:
        return "one real position at a time, and one is open", False
    if not ltp:
        return "no live quote", False
    sign = 1 if parent["side"] == "BUY" else -1
    if sign * (ltp - stop) <= 0:
        return "the price is already beyond the stop", True
    if abs(ltp - entry) > COPY_MAX_DRIFT_R * abs(entry - stop):
        return (f"the price has moved more than {COPY_MAX_DRIFT_R:g} of the stop distance "
                "since the paper fill"), False
    return None, True


async def _copy_entries(dhan: DhanClient | None, validated: set, enabled: dict) -> dict:
    """Copy the tournament's new Selected ORB 15-min paper positions into REAL orders."""
    if datetime.now(IST).strftime("%H:%M") >= ENTRY_CUTOFF_HHMM:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            f"Past the {ENTRY_CUTOFF_HHMM} IST entry cutoff — no new entries; open positions still managed."]}
    ls = SELECTED_BY_ID[COPY_SOURCE]
    if ls.strategy_id not in validated or not enabled.get(ls.strategy_id, True):
        return {"opened": 0, "scanned_symbols": 0, "notes": [f"{ls.name} is disabled for real trading."]}
    since = _now() - timedelta(seconds=COPY_WINDOW_S + 4 * COPY_TICK_S)   # a waiting one gets its final word
    parents = [p async for p in intraday_lab_positions_collection.find(
        {"engine": "v2", "strategy_id": COPY_SOURCE, "status": "OPEN",
         "opened_on": _today_ist().isoformat(), "opened_at": {"$gte": since}}).sort("opened_at", 1)]
    notes: list[str] = []
    opened = 0
    for par in parents:
        claim = f"copy|{par['position_id']}"
        if await live_trading_state_collection.find_one({"_id": claim}, {"_id": 1}):
            continue                                    # decided before: never ordered twice
        symbol = par["symbol"]
        inst = await instruments_collection.find_one({"asset_class": "EQUITY", "symbol": symbol})
        ltp, ltp_source = None, "none"
        if inst:
            quotes, sources = await _equity_quote_map(dhan, [inst])
            key = (inst["exchange_segment"], str(inst["security_id"]))
            q = quotes.get(key)
            if q:
                ltp = float(q.get("last_price") or q.get("ltp") or 0.0) or None
                ltp_source = sources.get(key, "quote")
        n_open = await live_trading_positions_collection.count_documents({"status": "OPEN"})
        if inst is None:
            why, final = "no instrument record for the symbol", True
        else:
            why, final = copy_check(par, ltp, n_open, _now())
        if why and not final:
            _copy_waiting[par["position_id"]] = why
            notes.append(f"Waiting to copy {par.get('side')} {symbol}: {why}.")
            continue
        if why and par["position_id"] in _copy_waiting:
            why = f"{why} (last wait: {_copy_waiting[par['position_id']]})"
        _copy_waiting.pop(par["position_id"], None)
        # Claim BEFORE ordering: a retry, the other loop or a restart must never order this twice.
        res = await live_trading_state_collection.update_one(
            {"_id": claim}, {"$setOnInsert": {"at": _now(), "symbol": symbol, "side": par.get("side"),
                                             "parent_opened_at": par.get("opened_at"),
                                             "decision": why or "ordering", "ltp": ltp}}, upsert=True)
        if res.upserted_id is None:
            continue
        if why:
            notes.append(f"Not copied: {par.get('side')} {symbol}: {why}.")
            continue
        live = await get_state()
        if not live["armed"] or live["kill_switch"]:
            await live_trading_state_collection.update_one({"_id": claim}, {"$set": {"decision": "desk disarmed"}})
            notes.append("Desk was disarmed / kill-switched mid-scan — stopped placing new orders.")
            break
        signal = SimpleNamespace(
            side=par["side"], entry=float(par["entry_price"]), target=None, stoploss=float(par["stoploss"]),
            confidence=float(par.get("confidence") or 0.0),
            rationale=f"copy of tournament position {par['position_id']}: {par.get('rationale') or ''}"[:400])
        ok = await _open_position(ls, symbol, inst, signal, ltp_source, ltp, parent=par)
        await live_trading_state_collection.update_one({"_id": claim}, {"$set": {
            "decision": "opened" if ok else "not opened (size, cash, ceiling or order refused)"}})
        if ok:
            opened += 1
            notes.append(f"REAL entry copied: {par['side']} {symbol} (tournament position {par['position_id']}).")
    return {"opened": opened, "scanned_symbols": len(parents), "notes": notes}

# ── manage (always runs, even disarmed — open real positions must be exited) ─────


async def _close_real(pos: dict, ltp: float, reason: str) -> bool:
    """Square off a real position with an opposite-side Angel market order. Returns True only
    if the exit order was accepted. If it fails we leave the position OPEN so the next cycle
    retries — we never mark a broker position closed on a failed exit."""
    exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
    oid = await _place_angel_order(pos["instrument"], exit_side, pos["qty"])
    if not oid:
        await _register_reject()
        return False
    await _clear_rejects()
    # Priced at the decision LTP until `reconcile_fills` finds the real exit fill in Angel's
    # trade book (same session) and re-prices it — charges included either way.
    money = _charge(pos["entry_price"], ltp, pos["qty"], pos["side"])
    realized = money["realized_pnl"]
    await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(ltp, 2), "exit_reason": reason,
        "unrealized_pnl": 0.0, "exit_order_id": oid, **money,
        "closed_on": _today_ist().isoformat(),
        "ltp": round(ltp, 2), "updated_at": _now(), "closed_at": _now(),
    }})
    await live_trading_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
        "symbol": pos["symbol"], "side": pos["side"], "entry_price": pos["entry_price"], "exit_price": round(ltp, 2),
        "qty": pos["qty"], "exit_reason": reason, **money,
        "entry_order_id": pos.get("entry_order_id"), "exit_order_id": oid,
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    logger.warning("[live_trading] REAL EXIT %s %s x%s @~%.2f (%s, net %.2f after %.2f charges, order %s)",
                   exit_side, pos["symbol"], pos["qty"], ltp, reason, realized, money["fees"], oid)
    return True


async def _confirm_entry(pos: dict) -> str:
    """What Angel did with a position's ENTRY order, asked before its first exit when no fill
    has been seen yet: 'filled' (recorded on the position), 'void' (Angel rejected or cancelled
    it: the position is voided and no order is sent) or 'unknown' (still pending, or the order
    book is unreadable: no exit this tick, the next one asks again). An exit for an entry that
    never filled would open a brand-new real position."""
    try:
        orders = await angel_client.order_book()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[live_trading] order book unavailable before an exit: %s", exc)
        return "unknown"
    oid = str(pos.get("entry_order_id") or "")
    o = next((o for o in (orders or []) if oid and str(o.get("orderid") or "") == oid), None)
    st = str((o or {}).get("status") or (o or {}).get("orderstatus") or "").lower()
    if st == "complete":
        await live_trading_positions_collection.update_one(
            {"_id": pos["_id"]}, {"$set": {"entry_confirmed": True, "updated_at": _now()}})
        return "filled"
    if st in ("rejected", "cancelled", "canceled"):
        await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "status": "VOID", "exit_reason": "entry_rejected", "realized_pnl": 0.0,
            "gross_pnl": 0.0, "fees": 0.0, "unrealized_pnl": 0.0,
            "reconcile_status": "void", "reconciled_at": _now(),
            "reconcile_note": f"Angel {st} the entry order: {str((o or {}).get('text') or '')[:120]}",
            "closed_at": _now(), "closed_on": _today_ist().isoformat(), "updated_at": _now()}})
        logger.error("[live_trading] entry order %s for %s was %s by Angel: position voided, no exit sent",
                     oid, pos.get("symbol"), st)
        return "void"
    logger.warning("[live_trading] entry order %s for %s is '%s' at Angel: exit held until it is seen filled",
                   oid, pos.get("symbol"), st or "not in the order book")
    return "unknown"


# REAL MONEY. Every close decided below sends an opposite-side market order. Two concurrent
# manage cycles — the shared loop and the independent close-out job — could each decide to
# close the same position and send TWO exits; the second would not close anything, it would
# open a brand-new opposite position. This lock makes that impossible.
_manage_lock = asyncio.Lock()


async def manage_cycle(dhan: DhanClient | None) -> int:
    async with _manage_lock:
        await session.ensure_cas()
        try:
            await reconcile_broker_closes()
        except Exception:  # noqa: BLE001 - exits must still be managed if Angel is unreadable
            logger.exception("[live_trading] broker reconciliation failed — managing on the ledger")
        return await _manage_cycle(dhan)


# ── broker first ─────────────────────────────────────────────────────────────────
#
# THE HAZARD THIS CLOSES. When Angel squares a position off on its own — the MIS auto
# square-off in the last minutes of the session, or an RMS margin call — the ledger still
# says OPEN. The next exit decision then sends an opposite-side market order, and that
# order does not close anything: it OPENS a new real position. And the ledger books the
# position at whatever price it finally notices, which on 19 and 20 August 2026 was the NEXT
# session's price for 49 real trades.
#
# So Angel's own position book is read BEFORE any exit decision. A symbol Angel shows flat
# while the ledger holds same-side positions in it was closed by the broker: those
# positions are closed here, at the price of the broker's own closing fills, with no order
# sent. Anything that does not add up — a broker quantity that matches neither the ledger
# nor flat, positions on both sides of one symbol, an entry the broker never filled — is
# MARKED rather than guessed at, and marked positions are never sent an automatic exit.

BROKER_CHECK_EVERY_S = float(os.getenv("LIVE_TRADING_BROKER_CHECK_S", "30"))
# After these times Angel is squaring MIS off itself (closing-auction stocks earlier), so the
# desk stops sending exit orders and leaves the close to the broker and to the
# reconciliation above. An exit sent into that window would race the broker's own.
BROKER_SQUAREOFF_CAS_HHMM = os.getenv("LIVE_TRADING_BROKER_SQUAREOFF_CAS", "15:10")
BROKER_SQUAREOFF_HHMM = os.getenv("LIVE_TRADING_BROKER_SQUAREOFF", "15:15")
_broker_checked_at = 0.0


def _tsym(pos: dict) -> str:
    inst = pos.get("instrument") or {}
    return str(inst.get("angel_tradingsymbol") or f"{pos['symbol']}-EQ")


def _signed_qty(side: str, qty: int) -> int:
    return int(qty) if side == "BUY" else -int(qty)


def _broker_squaring_off(symbol: str, now_ist: datetime) -> bool:
    cutoff = BROKER_SQUAREOFF_CAS_HHMM if session.is_cas(symbol) else BROKER_SQUAREOFF_HHMM
    return now_ist.strftime("%H:%M") >= cutoff


async def reconcile_broker_closes(force: bool = False) -> dict:
    """Bring today's OPEN ledger positions in line with Angel's own position book.

    Never places an order. Throttled to one read every BROKER_CHECK_EVERY_S unless forced,
    and skipped entirely when nothing real is open today."""
    global _broker_checked_at
    today = _today_ist().isoformat()
    open_rows = [p async for p in live_trading_positions_collection.find(
        {"status": "OPEN", "opened_on": today})]
    if not open_rows:
        return {"checked": 0}
    if not force and time.monotonic() - _broker_checked_at < BROKER_CHECK_EVERY_S:
        return {"checked": 0, "throttled": True}
    _broker_checked_at = time.monotonic()

    try:
        book = await angel_client.broker_positions()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[live_trading] Angel position book unavailable: %s", exc)
        return {"checked": len(open_rows), "error": f"position book unavailable: {exc}"[:200]}
    if not book:
        # An account that traded today lists the symbol even once it is flat, so an empty
        # book beside positions opened today is not evidence of anything. Do nothing.
        return {"checked": len(open_rows), "note": "empty position book; nothing inferred"}

    broker_net: dict[str, int] = {}
    broker_avg: dict[str, dict] = {}
    for b in book:
        if str(b.get("producttype") or "").upper() not in ("INTRADAY", "MIS"):
            continue
        ts = str(b.get("tradingsymbol") or "")
        broker_net[ts] = broker_net.get(ts, 0) + int(float(b.get("netqty") or 0))
        broker_avg[ts] = {"BUY": float(b.get("buyavgprice") or 0.0),
                          "SELL": float(b.get("sellavgprice") or 0.0)}

    ours: dict[str, list[dict]] = {}
    for p in open_rows:
        ours.setdefault(_tsym(p), []).append(p)

    # Every order id this desk itself sent today, so the broker's own fills can be told apart.
    known_ids: set[str] = set()
    async for p in live_trading_positions_collection.find(
            {"opened_on": today}, {"entry_order_id": 1, "exit_order_id": 1}):
        for k in ("entry_order_id", "exit_order_id"):
            for oid in str(p.get(k) or "").split(","):
                if oid.strip():
                    known_ids.add(oid.strip())

    trades: list[dict] | None = None
    orders: list[dict] | None = None
    out = {"checked": len(open_rows), "closed_by_broker": 0, "mismatch": 0, "void": 0}
    touched: set[str] = set()

    for ts, rows in ours.items():
        sides = {p["side"] for p in rows}
        ledger_net = sum(_signed_qty(p["side"], p["qty"]) for p in rows)

        if ts not in broker_net:
            # Angel does not list the symbol at all. If our entry was rejected after being
            # accepted, the position never existed: find out before it is ever "closed".
            if orders is None:
                try:
                    orders = await angel_client.order_book()
                except Exception:  # noqa: BLE001
                    orders = []
            by_id = {str(o.get("orderid") or ""): o for o in orders}
            for p in rows:
                o = by_id.get(str(p.get("entry_order_id") or ""))
                st = str((o or {}).get("status") or (o or {}).get("orderstatus") or "").lower()
                if st in ("rejected", "cancelled", "canceled"):
                    await live_trading_positions_collection.update_one({"_id": p["_id"]}, {"$set": {
                        "status": "VOID", "exit_reason": "entry_rejected", "realized_pnl": 0.0,
                        "gross_pnl": 0.0, "fees": 0.0, "unrealized_pnl": 0.0,
                        "reconcile_status": "void", "reconciled_at": _now(),
                        "reconcile_note": f"Angel {st} the entry order: "
                                          f"{str((o or {}).get('text') or '')[:120]}",
                        "closed_at": _now(), "closed_on": today, "updated_at": _now()}})
                    out["void"] += 1
                    touched.add(p["strategy_id"])
            continue

        net = broker_net[ts]
        if net == ledger_net:
            continue                                   # the two agree: still open

        if net == 0 and len(sides) == 1:
            # The broker is flat in a symbol where the ledger holds same-side positions:
            # Angel closed them. Price them at Angel's own closing fills.
            close_side = "SELL" if ledger_net > 0 else "BUY"
            if trades is None:
                try:
                    trades = await angel_client.trade_book()
                except Exception:  # noqa: BLE001
                    trades = []
            fills = [t for t in trades
                     if str(t.get("tradingsymbol") or "") == ts
                     and str(t.get("transactiontype") or "").upper() == close_side
                     and str(t.get("producttype") or "").upper() in ("INTRADAY", "MIS")
                     and str(t.get("orderid") or "") not in known_ids]
            qty = sum(float(t.get("fillsize") or 0) for t in fills)
            if qty > 0:
                px = sum(float(t.get("fillprice") or 0) * float(t.get("fillsize") or 0)
                         for t in fills) / qty
                oids = ",".join(sorted({str(t.get("orderid")) for t in fills}))
                exact = int(round(qty)) == abs(ledger_net)
                basis = (f"Angel's own closing fill{'s' if len(fills) > 1 else ''} "
                         f"(order {oids}), {int(qty)} share(s)")
            else:
                px = broker_avg.get(ts, {}).get(close_side) or 0.0
                oids, exact = None, False
                basis = "Angel position book average (trade book had no closing fill)"
            if px <= 0:
                for p in rows:
                    await _mark_mismatch(p, "broker is flat but no closing price could be read")
                    out["mismatch"] += 1
                continue
            for p in rows:
                money = _charge(p["entry_price"], px, p["qty"], p["side"])
                await live_trading_positions_collection.update_one({"_id": p["_id"]}, {"$set": {
                    "status": "CLOSED", "exit_reason": "broker_squared_off",
                    "exit_price": round(px, 2), "exit_fill_price": round(px, 2) if exact else None,
                    "exit_order_id": oids, "exit_basis": basis, **money,
                    "unrealized_pnl": 0.0, "ltp": round(px, 2),
                    "reconcile_status": "reconciled" if exact else "needs_contract_note",
                    "reconcile_note": None if exact else
                    f"broker closing quantity {int(qty)} vs ledger {abs(ledger_net)}",
                    "reconciled_at": _now(), "closed_at": _now(), "closed_on": today,
                    "updated_at": _now()}})
                await live_trading_trades_collection.insert_one({
                    "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
                    "strategy_name": p["strategy_name"], "symbol": p["symbol"], "side": p["side"],
                    "entry_price": p["entry_price"], "exit_price": round(px, 2), "qty": p["qty"],
                    "exit_reason": "broker_squared_off", **money,
                    "entry_order_id": p.get("entry_order_id"), "exit_order_id": oids,
                    "opened_at": p["opened_at"], "closed_at": _now()})
                out["closed_by_broker"] += 1
                touched.add(p["strategy_id"])
            logger.warning("[live_trading] %s: Angel closed %d ledger position(s) on its own; "
                           "reconciled at %.2f (%s), no order sent", ts, len(rows), px, basis)
            continue

        why = (f"Angel's net {net:+d} vs the ledger's {ledger_net:+d}"
               + (" with positions on both sides" if len(sides) > 1 else ""))
        for p in rows:
            await _mark_mismatch(p, why)
            out["mismatch"] += 1

    for sid in touched:
        await _update_score(sid)
    if out["mismatch"]:
        logger.error("[live_trading] %d real position(s) disagree with Angel's book — no automatic "
                     "exits will be sent for them", out["mismatch"])
    return out


async def _mark_mismatch(pos: dict, why: str) -> None:
    await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "reconcile_status": "mismatch", "reconcile_note": why[:200], "reconciled_at": _now(),
        "updated_at": _now()}})


async def _close_of_session(symbol: str, day: str) -> float | None:
    """NSE close for `symbol` on `day` — the best estimate of a broker square-off price once
    the trade book that held the real one has gone."""
    try:
        bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 0.5)
    except Exception:  # noqa: BLE001
        return None
    for b in reversed(bars or []):
        ts = getattr(b, "ts", None)
        if ts is None:
            continue
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts.astimezone(IST).date().isoformat() == day:
            return float(b.close)
    return None


async def _manage_cycle(dhan: DhanClient | None) -> int:
    open_positions = [p async for p in live_trading_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    by_symbol: dict[str, list[dict]] = {}
    for p in open_positions:
        by_symbol.setdefault(p["symbol"], []).append(p)
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": list(by_symbol.keys())}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

    now_ist = datetime.now(IST)
    today_iso = _today_ist().isoformat()
    # Copied positions follow their tournament position: once the paper position has closed (its
    # stop on minute bars, or its square-off), the real one is closed too.
    parent_ids = [p["parent_id"] for p in open_positions if p.get("parent_id")]
    parent_closed: dict[str, str] = {}
    if parent_ids:
        async for par in intraday_lab_positions_collection.find(
                {"position_id": {"$in": parent_ids}, "status": {"$ne": "OPEN"}}, {"position_id": 1, "exit_reason": 1}):
            parent_closed[par["position_id"]] = par.get("exit_reason") or "closed"

    updated = 0
    touched: set[str] = set()
    broker_checked = False
    for symbol, positions in by_symbol.items():
        inst = equities.get(symbol)
        ltp, ltp_source = None, None
        if inst:
            q = quotes.get((inst["exchange_segment"], str(inst["security_id"])))
            if q:
                ltp = float(q["last_price"])
                ltp_source = quote_source[(inst["exchange_segment"], str(inst["security_id"]))]
        if ltp is None:
            bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 0.1)
            if bars:
                ltp, ltp_source = bars[-1].close, "last_bar_close"
        if ltp is None:
            continue

        for pos in positions:
            sign = 1 if pos["side"] == "BUY" else -1

            # A position opened in an EARLIER session cannot still be live: this desk trades
            # INTRADAY (MIS), which the broker auto-squares-off the same day. If our ledger
            # still says OPEN, the exit order failed (or the scheduler stopped before a retry
            # succeeded) — the broker is already flat. Reconcile it CLOSED here WITHOUT
            # sending an order: placing one would not "close" anything, it would open a
            # brand-new opposite position with real money on a later day.
            if pos.get("opened_on") and pos["opened_on"] < today_iso:
                # The broker squared this off on its own day, and that day's trade book — the
                # only API record of the price — is gone. Today's LTP is NOT that price: it
                # carries an overnight move the account never had (49 real trades on 19-20
                # August 2026 were booked that way). The day's NSE close is the closest
                # available estimate; it is labelled as one until the contract note says.
                est = await _close_of_session(pos["symbol"], pos["opened_on"])
                px = est if est else ltp
                basis = (f"estimate: NSE close on {pos['opened_on']} — Angel squared this off that "
                         "afternoon and its trade book has since reset"
                         if est else f"estimate: next-session LTP ({ltp_source}) — no close found "
                                     f"for {pos['opened_on']}")
                money = _charge(pos["entry_price"], px, pos["qty"], pos["side"])
                await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
                    "status": "CLOSED", "exit_price": round(px, 2),
                    "exit_reason": "stale_session_reconciled", **money, "exit_basis": basis,
                    "reconcile_status": "needs_contract_note", "reconciled_at": _now(),
                    "unrealized_pnl": 0.0, "ltp": round(ltp, 2), "updated_at": _now(), "closed_at": _now(),
                    "closed_on": pos["opened_on"],
                }})
                await live_trading_trades_collection.insert_one({
                    "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"],
                    "strategy_name": pos["strategy_name"], "symbol": pos["symbol"], "side": pos["side"],
                    "entry_price": pos["entry_price"], "exit_price": round(px, 2), "qty": pos["qty"],
                    **money, "exit_reason": "stale_session_reconciled", "exit_basis": basis,
                    "entry_order_id": pos.get("entry_order_id"), "exit_order_id": None,
                    "opened_at": pos["opened_at"], "closed_at": _now(),
                })
                logger.error(
                    "[live_trading] STALE position %s %s from %s closed WITHOUT an order (the broker "
                    "squared it off); net %.2f at %s",
                    pos["side"], pos["symbol"], pos["opened_on"], money["realized_pnl"], basis,
                )
                touched.add(pos["strategy_id"])
                updated += 1
                continue

            if pos.get("reconcile_status") == "mismatch":
                # The ledger and Angel disagree about this position. Sending an exit sized on
                # the ledger could open a new position instead of closing one; MIS squares off
                # at the broker regardless, and `reconcile_broker_closes` settles it from there.
                continue
            unrealized = round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2)
            await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
                "ltp": round(ltp, 2), "ltp_source": ltp_source, "unrealized_pnl": unrealized,
                "pnl_pct": round(sign * (ltp - pos["entry_price"]) / pos["entry_price"] * 100, 2) if pos["entry_price"] else 0.0,
                "updated_at": _now(),
            }})
            updated += 1

            # A daily bar's close is not a live price: never take a stop or target on it.
            live_px = ltp_source != "last_bar_close"
            target = pos.get("target")
            hit_target = live_px and target is not None and (ltp >= target if sign > 0 else ltp <= target)
            hit_stop = live_px and (ltp <= pos["stoploss"] if sign > 0 else ltp >= pos["stoploss"])
            # INTRADAY product: every position squares off same day. The time is per SYMBOL:
            # Angel auto-squares MIS at 15:10 in closing-auction stocks, so exiting at 15:15
            # (the old rule) would send an exit for a position the broker had already closed —
            # which opens a new opposite position instead of closing anything.
            is_eod = session.squareoff_due(symbol, now_ist)
            reason = "target" if hit_target else "stoploss" if hit_stop else "eod" if is_eod else None
            if reason is None and pos.get("parent_id") in parent_closed:
                reason = f"tournament closed ({parent_closed[pos['parent_id']]})"
            if reason and _broker_squaring_off(symbol, now_ist):
                # Angel is squaring MIS off itself now. An exit sent into that window races
                # the broker's own and can land after it — as a NEW position. Leave it to the
                # broker; `reconcile_broker_closes` books it at the broker's fill.
                continue
            if reason and pos.get("entry_fill_price") is None and not pos.get("entry_confirmed"):
                verdict = await _confirm_entry(pos)
                if verdict == "void":
                    touched.add(pos["strategy_id"])
                if verdict != "filled":
                    continue                    # no exit for an entry nobody has seen fill
            if reason and not broker_checked:
                # Ask Angel before the first exit order of this pass. The fast copy loop can reach
                # an exit within seconds of an entry, before the 30-second broker check has seen
                # it: an entry Angel rejected, or a position Angel already squared off, would turn
                # this "exit" into a brand-new real position.
                broker_checked = True
                try:
                    await reconcile_broker_closes(force=True)
                except Exception:  # noqa: BLE001 - an unreadable book must not block a real exit
                    logger.exception("[live_trading] broker check before an exit failed")
            if reason:
                fresh = await live_trading_positions_collection.find_one(
                    {"_id": pos["_id"]}, {"status": 1, "reconcile_status": 1})
                if not fresh or fresh.get("status") != "OPEN" or fresh.get("reconcile_status") == "mismatch":
                    continue                    # the broker check settled it: no order
            if reason and await _close_real(pos, ltp, reason):
                touched.add(pos["strategy_id"])

    for strategy_id in touched:
        await _update_score(strategy_id)
    return updated


async def panic_close_all(dhan: DhanClient | None) -> dict:
    """Square off every open position immediately, then disarm and trip the kill switch."""
    open_positions = [p async for p in live_trading_positions_collection.find({"status": "OPEN"})]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": [p["symbol"] for p in open_positions]}}
    )} if open_positions else {}
    quotes, _ = await _equity_quote_map(dhan, list(equities.values())) if equities else ({}, {})

    closed = failed = 0
    touched: set[str] = set()
    for pos in open_positions:
        inst = equities.get(pos["symbol"])
        ltp = pos.get("ltp") or pos["entry_price"]
        if inst:
            q = quotes.get((inst["exchange_segment"], str(inst["security_id"])))
            if q:
                ltp = float(q["last_price"])
        if await _close_real(pos, ltp, "panic"):
            closed += 1
            touched.add(pos["strategy_id"])
        else:
            failed += 1
    for strategy_id in touched:
        await _update_score(strategy_id)
    await set_kill_switch(True)
    await set_armed(False, reason="panic close-all")
    return {"closed": closed, "failed": failed, "armed": False, "kill_switch": True}


# ── read models ──────────────────────────────────────────────────────────────────


_funds_cache: dict = {"at": 0.0, "data": None}
FUNDS_TTL_SECONDS = 20


def _num(d: dict, key: str) -> float:
    try:
        return round(float(d.get(key) or 0), 2)
    except (TypeError, ValueError):
        return 0.0


async def angel_account(force: bool = False) -> dict:
    """The REAL Angel One account: funds and the broker's own view of today's positions.

    This is the money that actually exists, as opposed to the desk's notional allocation —
    the whole point of showing it on a real-money desk. Cached briefly because the page
    polls, and Angel rate-limits."""
    import time as _t

    if not angel_client.configured():
        return {"available": False, "reason": "Angel One is not configured"}
    if not force and _funds_cache["data"] and _t.monotonic() - _funds_cache["at"] < FUNDS_TTL_SECONDS:
        return _funds_cache["data"]

    out: dict = {"available": True}
    try:
        f = await angel_client.funds()
        out.update({
            "available_cash": _num(f, "availablecash"),
            "net": _num(f, "net"),
            "utilised_margin": _num(f, "utiliseddebits"),
            "collateral": _num(f, "collateral"),
            "m2m_realized": _num(f, "m2mrealized"),
            "m2m_unrealized": _num(f, "m2munrealized"),
            "intraday_payin": _num(f, "availableintradaypayin"),
        })
    except Exception as exc:
        return {"available": False, "reason": f"Could not read Angel funds: {exc}"}

    # Which account is this? Shown so the operator can confirm the desk is pointed at the
    # right Angel login before arming. Informational — never fail the call over it.
    try:
        pr = await angel_client.profile()
        out["client_code"] = pr.get("clientcode")
        out["account_name"] = pr.get("name")
    except Exception:
        out["client_code"] = None
        out["account_name"] = None

    # Broker-side positions are informational; never fail the whole call over them.
    try:
        bp = await angel_client.broker_positions()
        out["broker_positions"] = [
            {
                "symbol": p.get("tradingsymbol"),
                "product": p.get("producttype"),
                "net_qty": int(float(p.get("netqty") or 0)),
                "buy_avg": _num(p, "buyavgprice"),
                "sell_avg": _num(p, "sellavgprice"),
                "pnl": _num(p, "pnl"),
                "ltp": _num(p, "ltp"),
            }
            for p in bp
            if int(float(p.get("netqty") or 0)) != 0
        ]
    except Exception:
        out["broker_positions"] = []
    out["broker_position_count"] = len(out.get("broker_positions") or [])

    _funds_cache.update({"at": _t.monotonic(), "data": out})
    return out


async def summary() -> dict:
    deployed = realized = unrealized = 0.0
    async for p in live_trading_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in live_trading_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    open_count = await live_trading_positions_collection.count_documents({"status": "OPEN"})
    closed_count = await live_trading_positions_collection.count_documents({"status": "CLOSED"})
    state = await get_state()
    _bal = await account_balance()
    return {
        "mode": "real",
        "armed": state["armed"],
        "kill_switch": state["kill_switch"],
        "consecutive_rejects": state["consecutive_rejects"],
        "max_consecutive_rejects": MAX_CONSECUTIVE_REJECTS,
        "disarmed_reason": state["disarmed_reason"],
        "broker_connected": state["broker_connected"],
        "last_run_at": state["last_run_at"],
        "last_notes": state["last_notes"],
        "initial_capital": INITIAL_CAPITAL,
        "desk_ceiling": DESK_CEILING,
        "per_strategy_allocation": round(PER_STRATEGY_ALLOCATION, 2),
        "position_notional": round(POSITION_NOTIONAL, 2),
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        # See the module note on `daily()`: the desk's Rs80,000 is a ceiling, not money
        # held, so the ceiling ROI and the real-account ROI are both reported rather than
        # letting the kinder of the two stand alone.
        "roi_pct": round((realized + unrealized) / INITIAL_CAPITAL * 100, 3)
        if INITIAL_CAPITAL else 0.0,
        "account_roi_pct": round((realized + unrealized) / _bal["net"] * 100, 3)
        if _bal.get("net") else None,
        "account_basis": round(_bal.get("net") or 0.0, 2),
        "deployed_roi_pct": round((realized + unrealized) / deployed * 100, 3)
        if deployed else 0.0,
        # Symbols the exchange declined today. Surfaced rather than silently skipped: a
        # name quietly disappearing from a real-money desk is exactly the kind of thing
        # that should be visible.
        "refused_symbols": refused_symbols(),
        "ledger": await ledger_health(),
        "open_positions": open_count,
        "closed_positions": closed_count,
        "strategy_count": len(SELECTED),
        "copy_source": COPY_SOURCE, "copy_notional": COPY_NOTIONAL, "mis_leverage": MIS_LEVERAGE,
        "max_open_positions": MAX_OPEN_POSITIONS, "gate_override": OWNER_OVERRIDE,
        # The REAL account. `equity` above is only the desk's notional allocation + P&L;
        # on a real-money desk what matters is the money Angel actually holds.
        "angel": await angel_account(),
        **(await breaker_state()),
    }


async def ledger_health() -> dict:
    """How much of the real-money record is the broker's truth, and how much is estimate."""
    out = {"reconciled": 0, "needs_contract_note": 0, "mismatch": 0, "void": 0,
           "unreconciled": 0, "charges_missing": 0}
    async for p in live_trading_positions_collection.find(
            {"status": {"$ne": "OPEN"}}, {"reconcile_status": 1, "fees": 1, "status": 1}):
        st = p.get("reconcile_status")
        if st in out:
            out[st] += 1
        elif p.get("status") == "CLOSED":
            out["unreconciled"] += 1
        if p.get("status") == "CLOSED" and p.get("fees") is None:
            out["charges_missing"] += 1
    return out


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in live_trading_scores_collection.find({})}
    enabled = await _enabled_map()
    verdicts = await _verdicts(list(SELECTED_BY_ID))
    rows = []
    for ls in SELECTED:
        sc = scores.get(ls.strategy_id) or {}
        net_pnl = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": ls.strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net_pnl, 2),
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
            "enabled": enabled.get(ls.strategy_id, True),
            "verdict": _verdict_of(verdicts.get(ls.strategy_id)),
            "validated": (_verdict_of(verdicts.get(ls.strategy_id)) == "CONFIRMED"
                          or ls.strategy_id in OWNER_OVERRIDE),
            "override": OWNER_OVERRIDE.get(ls.strategy_id),
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return rows


async def open_positions() -> list[dict]:
    rows = []
    async for p in live_trading_positions_collection.find({"status": "OPEN"}).sort("opened_at", -1):
        rows.append({
            "position_id": p.get("position_id"), "symbol": p["symbol"], "strategy_name": p.get("strategy_name"),
            "is_anti": p.get("is_anti", False), "side": p["side"], "qty": p["qty"],
            "entry_price": p["entry_price"], "ltp": p.get("ltp"), "ltp_source": p.get("ltp_source"),
            "target": p.get("target"), "stoploss": p["stoploss"], "parent_id": p.get("parent_id"),
            "unrealized_pnl": p.get("unrealized_pnl") or 0.0, "pnl_pct": p.get("pnl_pct") or 0.0,
            "entry_order_id": p.get("entry_order_id"),
        })
    return rows


# ── the tick ─────────────────────────────────────────────────────────────────────


async def reconcile_fills() -> dict:
    """Replace recorded signal prices with the prices Angel actually filled at.

    A market order does not fill at the price the signal was computed from — the spread
    and whatever moved in between sit between the two — so a desk that records the signal
    price reports P&L the broker never charged. Measured on this desk: a session recorded
    as -Rs210 was really -Rs36.52.

    `signal_price` keeps what the strategy asked for, so the slippage stays visible as its
    own number; `entry_price` becomes the truth, and every downstream P&L figure follows
    from it. One trade-book call per cycle covers every position.
    """
    # Angel's trade book covers TODAY ONLY. A position opened on an earlier session can
    # never be reconciled from it, so those are marked once and skipped rather than
    # re-queried every cycle forever — and marked rather than silently left looking
    # reconciled, because their entry price is still the signal price and their P&L is
    # therefore still wrong.
    today_start = datetime.now(IST).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    unresolved = {"$or": [
        {"entry_order_id": {"$ne": None}, "entry_fill_price": None},
        {"exit_order_id": {"$ne": None}, "exit_fill_price": None},
    ]}
    stale = await live_trading_positions_collection.update_many(
        {**unresolved, "opened_at": {"$lt": today_start},
         "reconcile_status": {"$in": [None, False]}},
        {"$set": {"reconcile_status": "unavailable",
                  "reconcile_note": "opened before today; Angel's trade book is same-day "
                                    "only, so this entry price is the signal price, not "
                                    "the fill"}},
    )
    pending = [p async for p in live_trading_positions_collection.find(
        {**unresolved, "opened_at": {"$gte": today_start}})]
    if not pending:
        return {"checked": 0, "entries": 0, "exits": 0,
                "marked_unreconcilable": stale.modified_count}
    try:
        trades = await angel_client.trade_book()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[live_trading] trade book unavailable: %s", exc)
        return {"checked": len(pending), "entries": 0, "exits": 0, "error": str(exc)[:160]}

    # Angel returns one row per FILL; a single order can fill in several pieces, so the
    # honest entry price is the size-weighted average across them, not the first row.
    by_order: dict[str, list[dict]] = {}
    for t in trades:
        oid = str(t.get("orderid") or "")
        if oid:
            by_order.setdefault(oid, []).append(t)

    def avg_fill(oid: str):
        rows = by_order.get(str(oid) or "")
        if not rows:
            return None, 0
        qty = sum(float(r.get("fillsize") or 0) for r in rows)
        if qty <= 0:
            return None, 0
        val = sum(float(r.get("fillprice") or 0) * float(r.get("fillsize") or 0) for r in rows)
        return round(val / qty, 2), int(qty)

    entries = exits = 0
    for pos in pending:
        upd: dict = {}
        eid = pos.get("entry_order_id")
        if eid and pos.get("entry_fill_price") is None:
            price, qty = avg_fill(eid)
            if price:
                signal_px = pos.get("signal_price", pos.get("entry_price"))
                upd.update({
                    "signal_price": round(signal_px, 2),
                    "entry_fill_price": price,
                    "entry_price": price,                       # truth, for all P&L below
                    "entry_fill_qty": qty,
                    "entry_slippage": round(price - signal_px, 2),
                    "capital_deployed": round(price * pos["qty"], 2),
                })
                entries += 1
        xid = pos.get("exit_order_id")
        if xid and pos.get("exit_fill_price") is None:
            price, _ = avg_fill(xid)
            if price:
                upd.update({"exit_fill_price": price, "exit_price": price})
                exits += 1
        if upd:
            # A closed position is re-priced from whatever is now known — real fills where
            # Angel has them — and charged. Recorded gross until 2026-10-10.
            if pos.get("status") == "CLOSED":
                entry_px = upd.get("entry_price", pos.get("entry_price"))
                exit_px = upd.get("exit_price", pos.get("exit_price"))
                if entry_px and exit_px:
                    upd.update(_charge(entry_px, exit_px, pos["qty"], pos["side"]))
                both = (upd.get("entry_fill_price", pos.get("entry_fill_price")) is not None
                        and upd.get("exit_fill_price", pos.get("exit_fill_price")) is not None)
                if both:
                    upd["reconcile_status"] = "reconciled"
            upd["reconciled_at"] = _now()
            await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": upd})
            if pos.get("status") == "CLOSED" and pos.get("entry_order_id"):
                await live_trading_trades_collection.update_one(
                    {"entry_order_id": pos["entry_order_id"], "strategy_id": pos["strategy_id"]},
                    {"$set": {k: upd[k] for k in ("entry_price", "exit_price", "gross_pnl", "fees",
                                                   "fee_breakdown", "realized_pnl", "charges_basis")
                              if k in upd}})
            await _update_score(pos["strategy_id"])
    if entries or exits:
        logger.warning("[live_trading] reconciled %s entries and %s exits to real fills",
                       entries, exits)
    return {"checked": len(pending), "entries": entries, "exits": exits,
            "marked_unreconcilable": stale.modified_count}


async def run_cycle(dhan: DhanClient | None) -> dict:
    # Reconcile BEFORE managing: an open position marked against the signal price would
    # otherwise be stopped or targeted off a price that was never paid.
    fills = await reconcile_fills()
    managed = await manage_cycle(dhan)   # ALWAYS manage open real positions (broker first)
    scan_result = await scan_cycle(dhan)  # gated by armed / kill / breaker / broker / verdicts
    snap = await summary()
    await live_trading_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"], "open_positions": snap["open_positions"],
    })
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {
            "last_run_at": _now(), "last_opened": scan_result["opened"], "last_managed": managed,
            "last_notes": scan_result["notes"], "broker_connected": angel_client.configured(),
            "angel_configured": angel_client.configured(),
        }},
        upsert=True,
    )
    return {"opened": scan_result["opened"], "managed": managed, "fills": fills,
            "scanned_symbols": scan_result["scanned_symbols"], "notes": scan_result["notes"]}


async def copy_loop() -> None:
    """The fast loop (10 Nov 2026): every COPY_TICK_S seconds in the session, exits first (broker
    first, the stop on live prices, the square-off, the tournament's close), then new entries while
    ARMED. The shared 3-minute tick keeps running too; `_manage_lock`, `_entry_lock` and the claim
    per tournament position keep the two from ever acting twice. Started from main.py; obeys the
    Main Control switch of this desk."""
    from app.services import market_calendar
    from app.services.desk_switches import is_on
    await asyncio.sleep(COPY_START_DELAY_S)
    while True:
        try:
            now = datetime.now(IST)
            hhmm = now.strftime("%H:%M")
            if (market_calendar.is_trading_day(now) and COPY_SESSION[0] <= hhmm <= COPY_SESSION[1]
                    and await is_on("live_trading")):
                if await live_trading_positions_collection.count_documents({"status": "OPEN"}):
                    await manage_cycle(None)
                state = await get_state()
                if state["armed"] and not state["kill_switch"] and hhmm < ENTRY_CUTOFF_HHMM:
                    await scan_cycle(None)
        except Exception:  # noqa: BLE001 - the loop must survive any one bad tick
            logger.exception("[live_trading] copy loop tick failed")
        await asyncio.sleep(COPY_TICK_S)


# ── history ────────────────────────────────────────────────────────────────────


async def equity_curve(limit: int = 500) -> list[dict]:
    """Equity marks, oldest first so a chart can plot them directly."""
    rows = []
    async for d in live_trading_equity_collection.find({}).sort("ts", -1).limit(limit):
        d.pop("_id", None)
        d["ts"] = d["ts"].isoformat()
        rows.append(d)
    return list(reversed(rows))


async def daily(limit: int = 90) -> list[dict]:
    """Realised P&L and ROI per trading day, newest first.

    Grouped on the IST date the position CLOSED, since that is when the money moved.
    Positions predating the `closed_on` field fall back to their close timestamp, so old
    trades still appear rather than silently vanishing from the history."""
    buckets: dict[str, dict] = {}
    async for p in live_trading_positions_collection.find(
        {"status": "CLOSED"},
        {"realized_pnl": 1, "closed_at": 1, "closed_on": 1, "capital_deployed": 1,
         "symbol": 1, "strategy_name": 1},
    ):
        closed_at = p.get("closed_at")
        day = p.get("closed_on") or (
            closed_at.astimezone(IST).date().isoformat() if closed_at else None)
        if not day:
            continue
        b = buckets.setdefault(day, {"date": day, "trades": 0, "wins": 0,
                                     "realized_pnl": 0.0, "deployed": 0.0})
        net = p.get("realized_pnl") or 0.0
        b["trades"] += 1
        b["wins"] += 1 if net > 0 else 0
        b["realized_pnl"] += net
        b["deployed"] += p.get("capital_deployed") or 0.0
    rows = sorted(buckets.values(), key=lambda r: r["date"], reverse=True)[:limit]
    for r in rows:
        r["realized_pnl"] = round(r["realized_pnl"], 2)
        r["deployed"] = round(r["deployed"], 2)
        r["win_rate"] = round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0
        r["roi_pct"] = round(r["realized_pnl"] / INITIAL_CAPITAL * 100, 3) if INITIAL_CAPITAL else 0.0
        r["deployed_roi_pct"] = round(r["realized_pnl"] / r["deployed"] * 100, 3) if r["deployed"] else 0.0
    return rows
