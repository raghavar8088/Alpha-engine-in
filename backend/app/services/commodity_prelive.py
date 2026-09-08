"""Pre-Live Commodity Trading — the graduation desk above the 311-pattern paper desk.

WHAT THIS IS FOR
----------------
`commodity_engine` runs every pattern on every contract with ₹10 lakh each and asks one
question: *does this pattern have an edge at all?* It answers it in raw units — `qty =
budget // price` — which is fine for ranking patterns and is not how MCX works. You cannot
buy 14 units of crude oil; you buy ONE LOT of 100 barrels, and you fund it with margin, not
with the full notional.

This desk asks the next question, the one you have to answer before real money: *does
₹2,00,000 on THIS contract survive real lot sizes and real margin?* So it differs from the
paper desk in five deliberate ways:

  1. **Only admitted strategies trade.** A pattern gets in on a contract only if it already
     cleared the paper desk's promotion gate. Two admission modes (below).
  2. **Capital is per CONTRACT, not per strategy.** ₹2,00,000 per script. Every admitted
     strategy on a contract shares that contract's book — which is what a real account
     looks like, and what makes the per-script switches mean something.
  3. **Whole lots, sized against margin.** `lots = available margin // margin per lot`,
     using the same SPAN-lite calibration as the Commodity Positions desk. If the book
     cannot fund one lot, this desk says so instead of inventing a fraction.
  4. **It trades the MINIS.** Measured live: one lot of CRUDEOIL needs ~₹96,000 of margin
     and one of GOLD ~₹10,70,000, so a book this size could hold almost nothing and 29 of
     31 admitted strategies were stranded on contracts they could not fund. CRUDEOILM and
     NATGASMINI quote the SAME price as their parents (8,735 vs 8,732; 273.4 vs 273.2) at a
     tenth and a fifth of the lot, so the same patterns become tradable at this capital.
  5. **The engine ships OFF**, and every contract has its own switch. Nothing trades until
     the master switch is on AND that contract's switch is on.

STILL PAPER. Fills are simulated at the signal bar and marked on live Angel quotes; no
order ever reaches a broker from this module. "Pre-live" is the rehearsal before real
money, not real money — the same meaning the other Pre-Live desks in this app carry.

ADMISSION: PER-SCRIPT IS THE DEFAULT, AND THAT MATTERS
------------------------------------------------------
The paper desk's headline verdict is BLENDED across all eight contracts. "Opening Range
Breakout · 30m is READY" can be true of a book carried by copper and gold while the same
strategy is four trades and negative on crude. Since capital here is committed per
contract, the honest admission test is the per-contract one: the strategy must have
cleared the gate ON THAT CONTRACT'S OWN TRADES. That is the default. `blended` is offered
because it is what the main page's badges show, and someone comparing the two pages should
be able to see both — but it admits strategies to contracts they have never proved
anything on, and the API says so on every row.

BARS COME FROM THE SHARED STORE
-------------------------------
This desk reads `commodity_bars` and never calls Angel's candle endpoint. That endpoint
403s under load (measured: 5 of 8 unpaced calls), and adding a second poller for the same
symbols would break the one that already works. The minis were added to that poller's
universe (`COMMODITY_UNDERLYINGS`) rather than given a fetcher here — a symbol with no
candles in the store has nothing for any strategy to evaluate.
"""

import logging
import os
import time as _time
from datetime import date, datetime, timezone
from uuid import uuid4

from app.core.db import (
    commodity_prelive_equity_collection,
    commodity_prelive_flags_collection,
    commodity_prelive_positions_collection,
    commodity_prelive_scores_collection,
    commodity_prelive_state_collection,
    commodity_prelive_trades_collection,
)
from app.services.broker_data import get_ltp
from app.services.commodity_bars import (
    IST,
    TIMEFRAMES,
    front_month_universe,
    is_market_open,
    load_bars,
)
from app.services.commodity_engine import (
    MAX_DRAWDOWN_PCT,
    MIN_PROFIT_FACTOR,
    MIN_T_STAT,
    MIN_TRADES_FOR_VERDICT,
    MIN_WIN_RATE,
    _script_stats,
    _trade_stats,
    _verdict,
    order_charges,
)
from app.services.commodity_patterns import (
    COMMODITY_BY_ID,
    COMMODITY_CATALOG,
    FAMILY_LABELS,
    evaluate,
)
# The contract mathematics lives with the Commodity Positions desk and is imported rather
# than restated. `multiplier` is the number that turns a quote into contract value, and
# getting it wrong is not a rounding error — a bare 1 understates a ZINC lot by 5,000x.
from app.services.commodity_positions import (
    EXPOSURE_PCT,
    SCAN_FAMILY,
    _scan_pct,
    multiplier,
    spec_doc,
)

logger = logging.getLogger("commodity_prelive")

STATE_ID = "commodity_prelive"

# ── the contracts this desk trades ───────────────────────────────────────────────
# Deliberately NOT the pattern desk's universe. That desk trades the eight liquid
# underlyings to find out which patterns work; this one trades what Rs 2,00,000 can
# actually hold, which at MCX contract sizes means the MINIS. One lot of CRUDEOIL needs
# ~Rs 96,000 of margin against ~Rs 9,600 for CRUDEOILM at the same price — the mini is the
# same commodity in a wrapper this book can carry.
PRELIVE_UNDERLYINGS = [
    u.strip().upper() for u in os.getenv(
        "COMMODITY_PRELIVE_UNDERLYINGS", "CRUDEOILM,NATGASMINI"
    ).split(",") if u.strip()
]

# ── capital: one book per CONTRACT ───────────────────────────────────────────────
SCRIPT_CAPITAL = float(os.getenv("COMMODITY_PRELIVE_SCRIPT_CAPITAL", "200000"))   # ₹2 lakh
MAX_POSITIONS_PER_SCRIPT = int(os.getenv("COMMODITY_PRELIVE_MAX_POSITIONS", "2"))
# There is no pre-divided position budget. The first draft split the book into four equal
# position budgets, the way the equity desks in this app divide a strategy's stake, and on
# MCX that produces a desk that can never open anything: every lot cost more than a quarter
# of the book. A signal is sized against what the contract ACTUALLY has free, which is how a
# real account works — you do not reserve a quarter of your margin for trades you have not
# taken.
#
# HOW BIG ONE POSITION MAY GET IS CAPPED BY NOTIONAL, NOT BY A LOT COUNT.
# A flat "1 lot" cap cannot survive a change of contract size, and this desk exists to
# change contract size: 1 lot of NATURALGAS is Rs 3.4 lakh of notional (1.7x a Rs 2 lakh
# book) while 1 lot of its mini is Rs 68,000 (0.34x). The same number is reckless on one
# and leaves 96% of the book idle on the other. So the limit is expressed in the thing that
# actually measures risk — exposure against the book — and the lot count falls out of it.
# 1.0x means a single position may not carry more notional than the contract's own capital.
MAX_NOTIONAL_X = float(os.getenv("COMMODITY_PRELIVE_MAX_NOTIONAL_X", "1.0"))
# A backstop only, for the case where a contract is so small that the notional cap would
# wave through an absurd number of lots.
MAX_LOTS_PER_POSITION = int(os.getenv("COMMODITY_PRELIVE_MAX_LOTS", "25"))

SLIPPAGE_BPS = float(os.getenv("COMMODITY_PRELIVE_SLIPPAGE_BPS", "5"))
MAX_HOLD_BARS = int(os.getenv("COMMODITY_PRELIVE_MAX_HOLD_BARS", "60"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("COMMODITY_PRELIVE_DAILY_LOSS_PCT", "0.03"))

ADMISSION_MODES = ("per_script", "blended")
DEFAULT_ADMISSION = os.getenv("COMMODITY_PRELIVE_ADMISSION", "per_script")


class PreliveError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


# ── margin ───────────────────────────────────────────────────────────────────────


def margin_pct(symbol: str) -> float:
    """Fraction of notional a single futures lot ties up.

    For ONE futures leg `fno_margin.portfolio_margin` reduces exactly to this: a future's
    P&L is linear, so the worst loss across a ± scan band is `scan × notional`, and there
    is no optionality for the vol shift to bite on. Calling the full portfolio walk here
    would return the same number for eight times the work — but the calibration is taken
    from that module rather than restated, so a change to the scan bands moves both desks
    together."""
    return _scan_pct(symbol) + EXPOSURE_PCT


def margin_per_lot(symbol: str, price: float) -> float:
    return margin_pct(symbol) * float(price) * multiplier(symbol)


# ── this desk's universe ─────────────────────────────────────────────────────────


async def prelive_universe() -> dict:
    """The front-month contracts THIS desk trades — a subset of the shared master.

    The bar store is filled for a wider set (the pattern desk's eight plus these), so this
    filters rather than fetches: the candles are already there."""
    uni = await front_month_universe()
    return {s: d for s, d in uni.items() if s in PRELIVE_UNDERLYINGS}


# A mini and its parent are the SAME COMMODITY at the SAME QUOTE — verified live:
# CRUDEOIL 8,732.00 vs CRUDEOILM 8,735.00, NATURALGAS 273.20 vs NATGASMINI 273.40. They
# differ only in how many units one lot carries. `commodity_positions.SCAN_FAMILY` already
# encodes exactly this reasoning for margin ("a mini is the same commodity as its parent,
# so it inherits the parent's band"); the same fact licenses inheriting ADMISSION.
#
# This matters because a pattern is a function of the PRICE SERIES, and the two series are
# the same series. Without it the minis could never trade at all: admission needs a paper
# record on that exact symbol, the pattern desk has never traded the minis, so their roster
# would be empty for ever and this desk would sit idle by construction.
MINI_PARENT = {m: p for m, p in SCAN_FAMILY.items()}


# ── engine + per-contract switches ───────────────────────────────────────────────


async def get_state() -> dict:
    st = await commodity_prelive_state_collection.find_one({"_id": STATE_ID}) or {}
    mode = st.get("admission_mode") or DEFAULT_ADMISSION
    return {
        "enabled": bool(st.get("enabled", False)),          # ships OFF
        "admission_mode": mode if mode in ADMISSION_MODES else "per_script",
        "enabled_at": st["enabled_at"].isoformat() if st.get("enabled_at") else None,
        "disabled_reason": st.get("disabled_reason"),
        "last_run_at": st["last_run_at"].isoformat() if st.get("last_run_at") else None,
        "last_opened": int(st.get("last_opened", 0)),
        "last_managed": int(st.get("last_managed", 0)),
        "last_evaluated": int(st.get("last_evaluated", 0)),
        "last_notes": st.get("last_notes", []),
    }


async def set_engine(enabled: bool, reason: str | None = None) -> dict:
    upd: dict = {"enabled": bool(enabled), "updated_at": _now()}
    if enabled:
        upd.update({"enabled_at": _now(), "disabled_reason": None})
    else:
        upd["disabled_reason"] = reason or "switched off"
    await commodity_prelive_state_collection.update_one({"_id": STATE_ID}, {"$set": upd}, upsert=True)
    logger.warning("[commodity_prelive] ENGINE=%s (%s)", "ON" if enabled else "OFF", reason or "manual")
    return await get_state()


async def set_admission_mode(mode: str) -> dict:
    if mode not in ADMISSION_MODES:
        raise PreliveError(
            f"Unknown admission mode {mode!r} — expected one of {', '.join(ADMISSION_MODES)}.")
    await commodity_prelive_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"admission_mode": mode, "updated_at": _now()}}, upsert=True)
    _invalidate_admissions()
    return await get_state()


async def script_flags() -> dict[str, bool]:
    """Per-contract on/off. Absent means ON — the master switch is the safety, not this."""
    return {f["symbol"]: bool(f.get("enabled", True))
            async for f in commodity_prelive_flags_collection.find({})}


async def set_script_enabled(symbol: str, enabled: bool) -> dict:
    sym = (symbol or "").strip().upper()
    universe = await prelive_universe()
    if sym not in universe:
        raise PreliveError(
            f"{sym!r} is not one of the front-month contracts this desk trades "
            f"({', '.join(sorted(universe)) or 'none resolved'}).")
    await commodity_prelive_flags_collection.update_one(
        {"symbol": sym},
        {"$set": {"symbol": sym, "enabled": bool(enabled), "updated_at": _now()}},
        upsert=True)
    logger.info("[commodity_prelive] %s = %s", sym, "ON" if enabled else "OFF")
    return {"symbol": sym, "enabled": bool(enabled)}


async def set_all_scripts(enabled: bool) -> dict:
    universe = await prelive_universe()
    for sym in universe:
        await commodity_prelive_flags_collection.update_one(
            {"symbol": sym},
            {"$set": {"symbol": sym, "enabled": bool(enabled), "updated_at": _now()}},
            upsert=True)
    return {"symbols": sorted(universe), "enabled": bool(enabled)}


async def active_scripts() -> list[str]:
    """Contracts allowed to take NEW positions right now."""
    flags = await script_flags()
    return sorted(s for s in (await prelive_universe()) if flags.get(s, True))


# ── admission: which paper strategies earned a place on which contract ───────────

_ADMIT_CACHE: dict | None = None
_ADMIT_AT: float = 0.0
ADMIT_TTL = float(os.getenv("COMMODITY_PRELIVE_ADMIT_TTL", "300"))


def _invalidate_admissions() -> None:
    global _ADMIT_CACHE, _ADMIT_AT
    _ADMIT_CACHE, _ADMIT_AT = None, 0.0


async def admissions(fresh: bool = False) -> dict:
    """{symbol: {strategy_id: {...evidence...}}} — the roster, per contract.

    The evidence travels with the admission on purpose: a strategy trading real-money-shaped
    size should be able to say, on its own row, exactly which paper record bought it the
    seat."""
    global _ADMIT_CACHE, _ADMIT_AT
    state = await get_state()
    mode = state["admission_mode"]
    now = _time.monotonic()
    if not fresh and _ADMIT_CACHE and _ADMIT_CACHE.get("mode") == mode and now - _ADMIT_AT < ADMIT_TTL:
        return _ADMIT_CACHE

    universe = sorted(await prelive_universe())
    per: dict[str, dict[str, dict]] = {s: {} for s in universe}

    if mode == "blended":
        # The main page's badges: one blended record per strategy, applied to every
        # contract. Deliberately available, deliberately not the default.
        from app.core.db import commodity_scores_collection
        async for sc in commodity_scores_collection.find({"verdict": "READY"}):
            sid = sc.get("strategy_id")
            if sid not in COMMODITY_BY_ID:
                continue
            ev = {"basis": "blended", "trades": sc.get("trades", 0),
                  "win_rate": sc.get("win_rate", 0.0), "net_pnl": sc.get("net_pnl", 0.0),
                  "profit_factor": sc.get("profit_factor"), "expectancy": sc.get("expectancy", 0.0),
                  "max_drawdown_pct": sc.get("max_drawdown_pct", 0.0), "t_stat": sc.get("t_stat"),
                  "why": "Cleared the paper gate on the BLENDED record across all contracts — "
                         "not evidence about this contract specifically."}
            for sym in universe:
                per[sym][sid] = ev
    else:
        stats = await _script_stats(fresh)
        for sym in universe:
            # A mini has no paper record of its own — the pattern desk has never traded it.
            # Read its PARENT's record instead: same commodity, same quote, same series.
            source = MINI_PARENT.get(sym, sym)
            inherited = source != sym
            for sid, row in (stats["per_symbol"].get(source) or {}).items():
                if row.get("verdict") != "READY" or sid not in COMMODITY_BY_ID:
                    continue
                per[sym][sid] = {
                    "basis": "parent_script" if inherited else "per_script",
                    "source_symbol": source,
                    "trades": row["trades"], "win_rate": row["win_rate"],
                    "net_pnl": row["net_pnl"], "profit_factor": row["profit_factor"],
                    "expectancy": row["expectancy"], "max_drawdown_pct": row["max_drawdown_pct"],
                    "t_stat": row["t_stat"],
                    "why": (
                        f"Cleared the paper gate on {source}'s own {row['trades']} trades. "
                        f"{sym} is the same commodity at the same quote — one lot carries "
                        f"{multiplier(sym):,} units against {multiplier(source):,} — so the "
                        "price series the pattern was proved on is this contract's series."
                    ) if inherited else
                    f"Cleared the paper gate on {sym}'s own {row['trades']} trades.",
                }

    out = {"mode": mode, "per_symbol": per,
           "counts": {s: len(per[s]) for s in universe},
           "total": sum(len(v) for v in per.values())}
    _ADMIT_CACHE, _ADMIT_AT = out, now
    return out


async def admission_counts_both() -> dict:
    """How many strategies each mode would admit, so the choice is visible before it is made."""
    universe = sorted(await prelive_universe())
    stats = await _script_stats(False)
    per_script = {s: sum(1 for r in (stats["per_symbol"].get(MINI_PARENT.get(s, s)) or {}).values()
                         if r.get("verdict") == "READY") for s in universe}
    from app.core.db import commodity_scores_collection
    blended = await commodity_scores_collection.count_documents({"verdict": "READY"})
    return {"per_script": per_script, "per_script_total": sum(per_script.values()),
            "blended_per_contract": blended, "blended_total": blended * len(universe)}


# ── per-contract books ───────────────────────────────────────────────────────────


async def _book(symbol: str) -> dict:
    """Cash position of one contract's ₹1 lakh account.

    `margin_deployed` is MARGIN blocked, not notional — that is the number that limits what
    else the contract can take on, and on a 5,000x multiplier the two are nowhere near each
    other."""
    deployed = unreal = 0.0
    opens = 0
    async for p in commodity_prelive_positions_collection.find(
        {"symbol": symbol, "status": "OPEN"}, {"margin_used": 1, "unrealized_pnl": 1}
    ):
        deployed += p.get("margin_used") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
        opens += 1
    realized = 0.0
    closed = 0
    async for p in commodity_prelive_positions_collection.find(
        {"symbol": symbol, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        realized += p.get("realized_pnl") or 0.0
        closed += 1
    return {
        "symbol": symbol, "capital": SCRIPT_CAPITAL,
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
        "margin_deployed": round(deployed, 2),
        "available_margin": round(SCRIPT_CAPITAL + realized - deployed, 2),
        "equity": round(SCRIPT_CAPITAL + realized + unreal, 2),
        "open_positions": opens, "closed_positions": closed,
    }


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in commodity_prelive_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in commodity_prelive_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    """The breaker is measured against the capital actually switched ON.

    Three percent of eight contracts is a very different number from three percent of the
    one contract you left running, and the desk should not be able to lose a whole enabled
    book just because seven others are dark."""
    active = await active_scripts()
    base = SCRIPT_CAPITAL * max(len(active), 1)
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * base
    return {"breaker_tripped": pnl <= -limit, "today_pnl": round(pnl, 2),
            "daily_loss_limit": round(limit, 2), "daily_loss_pct": DAILY_LOSS_BREAKER_PCT,
            "breaker_base": round(base, 2)}


# ── position lifecycle ───────────────────────────────────────────────────────────


async def _open_position(spec, symbol: str, inst: dict, sig, bar_ts: datetime,
                         evidence: dict, free_margin: float,
                         open_count: int) -> tuple[bool, str | None, float]:
    """Open one whole-lot position.

    Returns (opened, note, margin consumed). `free_margin` and `open_count` are passed in
    rather than re-read because the caller walks eight timeframes over the same contract in
    one cycle and must see its own earlier fills — querying per signal would size every
    position against a book that still looked empty."""
    if open_count >= MAX_POSITIONS_PER_SCRIPT:
        return False, None, 0.0                 # book full; a normal state, not a note
    if await commodity_prelive_positions_collection.find_one(
            {"strategy_id": spec.strategy_id, "symbol": symbol, "status": "OPEN"}):
        return False, None, 0.0

    slip = SLIPPAGE_BPS / 10000.0
    fill = sig.entry * (1 + slip) if sig.side == "BUY" else sig.entry * (1 - slip)
    mult = multiplier(symbol)
    lot_notional = fill * mult
    lot_margin = margin_pct(symbol) * lot_notional
    if lot_margin <= 0:
        return False, None, 0.0

    lots = min(int(free_margin // lot_margin),                        # what margin allows
               int((MAX_NOTIONAL_X * SCRIPT_CAPITAL) // lot_notional),  # what risk allows
               MAX_LOTS_PER_POSITION)
    if lots < 1:
        return False, (
            f"{symbol}: one lot needs ~₹{lot_margin:,.0f} of margin (notional "
            f"₹{lot_notional:,.0f} = ₹{fill:,.2f} × {mult:,} at {margin_pct(symbol)*100:.0f}%), "
            f"more than the ₹{free_margin:,.0f} this contract has free. No fraction of a lot "
            f"was invented — ₹{SCRIPT_CAPITAL:,.0f} does not fund {symbol} at this price. "
            f"Its mini contract, if MCX lists one, is the version this book can carry."
        ), 0.0

    qty = lots * mult
    margin_used = lots * lot_margin
    entry_costs = order_charges(fill, qty, sig.side == "BUY")
    await commodity_prelive_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": spec.strategy_id,
        "strategy_name": spec.name, "family": spec.family,
        "family_label": FAMILY_LABELS.get(spec.family, spec.family),
        "template": spec.template, "timeframe": spec.timeframe, "pattern": sig.pattern,
        "symbol": symbol, "display_name": inst.get("symbol"),
        "instrument": {"symbol": inst.get("symbol"), "security_id": str(inst.get("security_id")),
                       "exchange_segment": inst.get("exchange_segment"),
                       "expiry": inst.get("expiry"), "lot_size": inst.get("lot_size", 1)},
        "side": sig.side, "signal_price": round(sig.entry, 4), "entry_price": round(fill, 4),
        "lots": lots, "multiplier": mult, "qty": qty,
        "notional": round(fill * qty, 2), "margin_used": round(margin_used, 2),
        "margin_pct": round(margin_pct(symbol), 5), "capital_deployed": round(margin_used, 2),
        "entry_costs": round(entry_costs, 2),
        "target": round(sig.target, 4), "stoploss": round(sig.stoploss, 4),
        "ltp": round(fill, 4), "ltp_source": "signal_bar",
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "return_on_margin_pct": 0.0,
        "realized_pnl": None, "costs": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(sig.confidence, 2), "rationale": sig.rationale,
        "admitted_because": evidence.get("why"), "admission_basis": evidence.get("basis"),
        "entry_bar_ts": bar_ts, "bars_held": 0, "max_hold_bars": MAX_HOLD_BARS,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None,
    })
    return True, None, margin_used


async def _close(pos: dict, ltp: float, reason: str) -> float:
    slip = SLIPPAGE_BPS / 10000.0
    is_long = pos["side"] == "BUY"
    fill = ltp * (1 - slip) if is_long else ltp * (1 + slip)
    qty = pos["qty"]
    gross = (fill - pos["entry_price"]) * qty * (1 if is_long else -1)
    costs = (pos.get("entry_costs") or 0.0) + order_charges(fill, qty, not is_long)
    net = gross - costs
    margin = pos.get("margin_used") or 0.0
    await commodity_prelive_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"],
        "strategy_name": pos["strategy_name"], "family": pos.get("family"),
        "template": pos.get("template"), "timeframe": pos.get("timeframe"),
        "pattern": pos.get("pattern"), "symbol": pos["symbol"], "side": pos["side"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 4),
        "lots": pos.get("lots"), "qty": qty, "multiplier": pos.get("multiplier"),
        "margin_used": round(margin, 2),
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
        "exit_reason": reason, "rationale": pos.get("rationale"),
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await commodity_prelive_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
        "unrealized_pnl": 0.0, "closed_at": _now(), "updated_at": _now(), "ltp": round(ltp, 4),
    }})
    return net


# ── scoring: one record per (contract, strategy) ─────────────────────────────────


async def _update_scores(pairs: set) -> None:
    for sid, sym in pairs:
        spec = COMMODITY_BY_ID.get(sid)
        if spec is None:
            continue
        closed = [p async for p in commodity_prelive_positions_collection.find(
            {"strategy_id": sid, "symbol": sym, "status": {"$ne": "OPEN"}},
            {"realized_pnl": 1, "costs": 1, "closed_at": 1}).sort("closed_at", 1)]
        stats = _trade_stats(closed, base=SCRIPT_CAPITAL)
        verdict, reasons = _verdict(stats)
        await commodity_prelive_scores_collection.update_one(
            {"strategy_id": sid, "symbol": sym},
            {"$set": {"strategy_id": sid, "symbol": sym, "name": spec.name,
                      "family": spec.family,
                      "family_label": FAMILY_LABELS.get(spec.family, spec.family),
                      "template": spec.template, "timeframe": spec.timeframe,
                      **stats, "verdict": verdict, "verdict_reasons": reasons,
                      "updated_at": _now()}},
            upsert=True)


# ── cycles ───────────────────────────────────────────────────────────────────────


async def scan_cycle() -> dict:
    notes: list[str] = []
    state = await get_state()
    if not state["enabled"]:
        return {"opened": 0, "evaluated": 0, "notes": [
            "Pre-Live Commodity engine is OFF — no new positions. Open ones are still managed."]}

    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L ₹{breaker['today_pnl']:,.0f} crossed the "
            f"₹{breaker['daily_loss_limit']:,.0f} limit on the switched-on contracts. No new "
            "positions; open ones still managed."]}

    universe = await prelive_universe()
    if not universe:
        return {"opened": 0, "evaluated": 0,
                "notes": ["No unexpired MCX front-month futures with an Angel token on file."]}

    flags = await script_flags()
    active = {s: inst for s, inst in universe.items() if flags.get(s, True)}
    off = sorted(set(universe) - set(active))
    if not active:
        return {"opened": 0, "evaluated": 0, "notes": [
            "Every contract is switched OFF. Turn at least one on — the engine being ON is "
            "not enough on its own."]}

    admit = await admissions()
    roster = admit["per_symbol"]
    if not admit["total"]:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"No strategy has been admitted yet under the '{admit['mode']}' rule — nothing on "
            "the paper desk has cleared its promotion gate on these contracts. This desk "
            "trades only what has already proved itself there."]}

    by_tf: dict[str, list] = {}
    for spec in COMMODITY_CATALOG:
        by_tf.setdefault(spec.timeframe, []).append(spec)

    opened = evaluated = 0
    thin: list[str] = []
    unaffordable: dict[str, str] = {}
    # CONTRACT-outer, timeframe-inner. The contract is what carries the capital here, so
    # its book is read once per cycle and drawn down in memory as its own signals fill.
    # The other way round (the pattern desk's order) would size every fill against a book
    # that still looked untouched, and a Rs 1 lakh account can only afford one or two.
    for symbol, inst in active.items():
        allowed = roster.get(symbol) or {}
        if not allowed:
            continue
        book = await _book(symbol)
        free = book["available_margin"]
        opens = book["open_positions"]
        for tf, specs in by_tf.items():
            tf_specs = [s for s in specs if s.strategy_id in allowed]
            if not tf_specs:
                continue
            if opens >= MAX_POSITIONS_PER_SCRIPT:
                break
            # Sized to what is actually admitted on THIS contract, not to the whole
            # catalog's worst case: a contract admitting two short-lookback strategies
            # should not be starved because some unrelated 60-bar pattern exists.
            need = max(s.min_bars for s in tf_specs) + 5
            bars = await load_bars(symbol, tf, limit=max(need, 250))
            if len(bars) < need:
                thin.append(f"{symbol}/{tf}({len(bars)})")
                continue
            bar_ts = bars[-1].ts
            for spec in tf_specs:
                if opens >= MAX_POSITIONS_PER_SCRIPT:
                    break
                evaluated += 1
                sig = evaluate(spec, bars)
                if sig is None:
                    continue
                ok, why, used = await _open_position(
                    spec, symbol, inst, sig, bar_ts, allowed[spec.strategy_id], free, opens)
                if ok:
                    opened += 1
                    free -= used
                    opens += 1
                elif why:
                    unaffordable[symbol] = why

    if off:
        notes.append(f"{len(off)} contract{'s' if len(off) > 1 else ''} switched off and skipped "
                     f"entirely: {', '.join(off)}.")
    if thin:
        notes.append(f"{len(thin)} (contract, timeframe) series had too few bars to evaluate — "
                     f"the shared bar store is still filling: {', '.join(thin[:8])}"
                     f"{'…' if len(thin) > 8 else ''}")
    notes.extend(unaffordable.values())
    return {"opened": opened, "evaluated": evaluated, "notes": notes}


async def manage_cycle() -> int:
    """Always runs, engine on or off. An open position is real exposure and must be taken
    to its target, stop or hold limit regardless of whether new entries are allowed."""
    open_positions = [p async for p in commodity_prelive_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    # Deliberately the FULL master, not this desk's universe. A position can outlive its
    # contract's membership — the universe is a config list and it changes — and a position
    # that can no longer be priced is one that can never hit its stop. Managing an orphan
    # out is exactly what you want; stranding it open for ever is not.
    universe = await front_month_universe()
    prices: dict[str, tuple] = {}
    orphans: set[str] = set()
    for symbol in {p["symbol"] for p in open_positions}:
        inst = universe.get(symbol)
        if not inst:
            # Not even in the master any more (expired roll, delisting): fall back to the
            # instrument stamped on the position itself when it was opened.
            for p in open_positions:
                if p["symbol"] == symbol and p.get("instrument", {}).get("security_id"):
                    inst = p["instrument"]
                    break
        if not inst:
            continue
        if symbol not in PRELIVE_UNDERLYINGS:
            orphans.add(symbol)
        price, src = await get_ltp(None, str(inst.get("security_id")), inst.get("exchange_segment"))
        if price:
            prices[symbol] = (float(price), src)
    if orphans:
        logger.info("[commodity_prelive] managing %d position(s) on contracts no longer in "
                    "this desk's universe: %s", len(orphans), ", ".join(sorted(orphans)))

    updated = 0
    touched = set()
    for pos in open_positions:
        got = prices.get(pos["symbol"])
        if not got:
            continue
        ltp, src = got
        is_long = pos["side"] == "BUY"
        qty = pos["qty"]
        gross = (ltp - pos["entry_price"]) * qty * (1 if is_long else -1)
        projected = (pos.get("entry_costs") or 0.0) + order_charges(ltp, qty, not is_long)
        unrealized = gross - projected

        tf_minutes = TIMEFRAMES.get(pos.get("timeframe", "1d"), (None, 1440))[1]
        entry_ts = pos.get("entry_bar_ts")
        if entry_ts is not None and entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        bars_held = 0
        if entry_ts is not None:
            bars_held = int((datetime.now(timezone.utc) - entry_ts).total_seconds() // 60 // max(tf_minutes, 1))

        margin = pos.get("margin_used") or 0.0
        changes = {
            "ltp": round(ltp, 4), "ltp_source": src, "unrealized_pnl": round(unrealized, 2),
            "pnl_pct": round((ltp - pos["entry_price"]) / pos["entry_price"] * 100 * (1 if is_long else -1), 3)
            if pos["entry_price"] else 0.0,
            # Return on the MARGIN actually blocked — the number a real account feels.
            "return_on_margin_pct": round(unrealized / margin * 100, 2) if margin else 0.0,
            "bars_held": bars_held, "updated_at": _now(),
        }

        hit_target = ltp >= pos["target"] if is_long else ltp <= pos["target"]
        hit_stop = ltp <= pos["stoploss"] if is_long else ltp >= pos["stoploss"]
        expired = bars_held >= pos.get("max_hold_bars", MAX_HOLD_BARS)
        reason = "target" if hit_target else "stoploss" if hit_stop else "max_hold_expired" if expired else None

        await commodity_prelive_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        if reason:
            await _close({**pos, **changes}, ltp, reason)
            touched.add((pos["strategy_id"], pos["symbol"]))
        updated += 1

    await _update_scores(touched)
    return updated


async def close_all(symbol: str | None = None, reason: str = "manual_close_all") -> dict:
    """Square off every open position, or every one on a single contract."""
    q: dict = {"status": "OPEN"}
    if symbol:
        q["symbol"] = symbol.strip().upper()
    open_positions = [p async for p in commodity_prelive_positions_collection.find(q)]
    if not open_positions:
        return {"closed": 0, "skipped": 0, "net_pnl": 0.0}
    # Full master, same reason as manage_cycle: squaring off must reach a position on a
    # contract this desk no longer lists, which is precisely when you need it most.
    universe = await front_month_universe()
    closed = skipped = 0
    net = 0.0
    touched = set()
    for pos in open_positions:
        inst = universe.get(pos["symbol"]) or pos.get("instrument")
        price = None
        if inst:
            price, _src = await get_ltp(None, str(inst.get("security_id")), inst.get("exchange_segment"))
        # No live quote: fall back to the last mark rather than leaving the position open.
        ltp = float(price) if price else float(pos.get("ltp") or 0.0)
        if ltp <= 0:
            skipped += 1
            continue
        net += await _close(pos, ltp, reason)
        touched.add((pos["strategy_id"], pos["symbol"]))
        closed += 1
    await _update_scores(touched)
    return {"closed": closed, "skipped": skipped, "net_pnl": round(net, 2)}


async def run_cycle() -> dict:
    managed = await manage_cycle()
    scan = await scan_cycle()
    snap = await summary()
    await commodity_prelive_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "margin_deployed": snap["margin_deployed"],
        "open_positions": snap["open_positions"], "active_scripts": len(snap["active_scripts"]),
    })
    await commodity_prelive_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
        "last_evaluated": scan["evaluated"], "last_notes": scan["notes"],
        "market_open": is_market_open(),
    }}, upsert=True)
    return {"opened": scan["opened"], "managed": managed, "evaluated": scan["evaluated"],
            "notes": scan["notes"]}


# ── read models ──────────────────────────────────────────────────────────────────


async def scripts_view(fresh: bool = False) -> dict:
    """One row per contract: its switch, its lakh, what a lot costs, and how it is doing.

    The lot arithmetic is the point of this view. A contract whose lot needs more margin
    than the position budget can never trade here, and that is a fact about ₹1,00,000
    meeting MCX contract sizes — not a bug — so it is stated on the row rather than
    discovered as silence in the blotter."""
    universe = await prelive_universe()
    flags = await script_flags()
    admit = await admissions(fresh)
    roster = admit["per_symbol"]

    rows = []
    for sym in sorted(universe):
        inst = universe[sym]
        book = await _book(sym)
        price, src = await get_ltp(None, str(inst.get("security_id")), inst.get("exchange_segment"))
        price = float(price) if price else 0.0
        mult = multiplier(sym)
        lot_notional = price * mult if price else 0.0
        lot_margin = margin_pct(sym) * lot_notional
        lots_per_book = int(SCRIPT_CAPITAL // lot_margin) if lot_margin > 0 else 0
        lots_now = min(int(book["available_margin"] // lot_margin) if lot_margin > 0 else 0,
                       int((MAX_NOTIONAL_X * SCRIPT_CAPITAL) // lot_notional) if lot_notional > 0 else 0,
                       MAX_LOTS_PER_POSITION)
        spec = spec_doc(sym)
        rows.append({
            **book,
            "enabled": flags.get(sym, True),
            "contract": inst.get("symbol"), "expiry": inst.get("expiry"),
            "ltp": round(price, 2) if price else None, "ltp_source": src if price else None,
            "multiplier": mult, "lot_quantity": spec.get("lot_quantity"),
            "price_unit": spec.get("price_unit"), "spec_verified": spec.get("verified"),
            "lot_notional": round(lot_notional, 2), "margin_per_lot": round(lot_margin, 2),
            "margin_pct": round(margin_pct(sym) * 100, 2),
            "lots_per_book": lots_per_book, "lots_fundable_now": lots_now,
            # Not fundable is a fact about Rs 1 lakh meeting an MCX contract size, not a
            # fault. A price of 0 means no quote came back, which is a different thing and
            # must not be reported as "you cannot afford this".
            "tradable": lots_per_book >= 1,
            "unpriced": price <= 0,
            "afford_note": None if lots_per_book >= 1 or price <= 0 else (
                f"One lot is ₹{lot_notional:,.0f} of notional and needs ₹{lot_margin:,.0f} "
                f"of margin — more than this contract's whole ₹{SCRIPT_CAPITAL:,.0f}. "
                f"{sym} cannot be traded at this book size; a mini contract can."),
            "admitted_strategies": len(roster.get(sym) or {}),
            "return_pct": round((book["realized_pnl"] + book["unrealized_pnl"]) / SCRIPT_CAPITAL * 100, 2),
            "net_pnl": round(book["realized_pnl"] + book["unrealized_pnl"], 2),
        })
    rows.sort(key=lambda r: (not r["enabled"], -r["net_pnl"]))
    return {
        "rows": rows, "script_capital": SCRIPT_CAPITAL,
        "max_positions_per_script": MAX_POSITIONS_PER_SCRIPT,
        "max_lots_per_position": MAX_LOTS_PER_POSITION,
        "admission_mode": admit["mode"],
        "tradable_count": sum(1 for r in rows if r["tradable"]),
        "note": (f"Each contract gets its own ₹{SCRIPT_CAPITAL:,.0f}. Sizing is in WHOLE MCX "
                 "lots against SPAN-lite margin (scan + exposure), never in raw units — one "
                 "lot is price × multiplier of notional, and margin is a fraction of that. "
                 f"Where 'Lots / ₹{SCRIPT_CAPITAL/1000:,.0f}k' reads 0, one lot of that "
                 "contract costs more margin than the whole book: that is a true fact about "
                 "MCX contract sizes at this capital, not a data problem."),
    }


async def leaderboard(symbol: str | None = None) -> dict:
    """The contract-wise strategy leaderboard: one row per (contract, strategy).

    Never blended. This desk's whole premise is that a contract is the unit that carries
    capital, so a row that averaged natural gas with gold would be describing a book nobody
    holds."""
    sym_filter = symbol.strip().upper() if symbol else None
    q = {"symbol": sym_filter} if sym_filter else {}
    scores = [s async for s in commodity_prelive_scores_collection.find(q)]
    open_counts: dict = {}
    unreal: dict = {}
    async for p in commodity_prelive_positions_collection.find(
            {"status": "OPEN", **q}, {"strategy_id": 1, "symbol": 1, "unrealized_pnl": 1}):
        key = (p["strategy_id"], p["symbol"])
        open_counts[key] = open_counts.get(key, 0) + 1
        unreal[key] = unreal.get(key, 0.0) + (p.get("unrealized_pnl") or 0.0)

    admit = await admissions()
    seen = set()
    rows = []
    for s in scores:
        key = (s["strategy_id"], s["symbol"])
        seen.add(key)
        ev = (admit["per_symbol"].get(s["symbol"]) or {}).get(s["strategy_id"]) or {}
        rows.append({
            "strategy_id": s["strategy_id"], "symbol": s["symbol"], "name": s.get("name"),
            "family": s.get("family"), "family_label": s.get("family_label"),
            "template": s.get("template"), "timeframe": s.get("timeframe"),
            "trades": s.get("trades", 0), "win_rate": s.get("win_rate", 0.0),
            "net_pnl": s.get("net_pnl", 0.0), "total_costs": s.get("total_costs", 0.0),
            "profit_factor": s.get("profit_factor"), "expectancy": s.get("expectancy", 0.0),
            "max_drawdown_pct": s.get("max_drawdown_pct", 0.0), "t_stat": s.get("t_stat"),
            "return_pct": s.get("return_pct", 0.0),
            "open_positions": open_counts.get(key, 0),
            "unrealized_pnl": round(unreal.get(key, 0.0), 2),
            "verdict": s.get("verdict", "PENDING"),
            "verdict_reasons": s.get("verdict_reasons", []),
            "still_admitted": bool(ev), "admitted_because": ev.get("why"),
        })
    # Admitted strategies that have not traded yet still belong on the board — an empty row
    # is the honest answer to "what is this contract allowed to trade", and leaving them out
    # would make a freshly switched-on contract look like it has no roster at all.
    for sym, allowed in admit["per_symbol"].items():
        if sym_filter and sym != sym_filter:
            continue
        for sid, ev in allowed.items():
            if (sid, sym) in seen:
                continue
            spec = COMMODITY_BY_ID.get(sid)
            if spec is None:
                continue
            rows.append({
                "strategy_id": sid, "symbol": sym, "name": spec.name, "family": spec.family,
                "family_label": FAMILY_LABELS.get(spec.family, spec.family),
                "template": spec.template, "timeframe": spec.timeframe,
                "trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "total_costs": 0.0,
                "profit_factor": None, "expectancy": 0.0, "max_drawdown_pct": 0.0,
                "t_stat": None, "return_pct": 0.0, "open_positions": 0, "unrealized_pnl": 0.0,
                "verdict": "PENDING",
                "verdict_reasons": [f"0/{MIN_TRADES_FOR_VERDICT} closed trades on this contract "
                                    "here — admitted, but has not traded yet."],
                "still_admitted": True, "admitted_because": ev.get("why"),
            })
    rows.sort(key=lambda r: (r["verdict"] != "READY", -r["net_pnl"], -r["trades"]))
    return {
        "rows": rows, "symbol": sym_filter, "total": len(rows),
        "admission_mode": admit["mode"],
        "gate": {"min_trades": MIN_TRADES_FOR_VERDICT, "min_profit_factor": MIN_PROFIT_FACTOR,
                 "min_win_rate": MIN_WIN_RATE, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                 "min_t_stat": MIN_T_STAT},
        "note": ("Every row is one strategy on ONE contract, scored on this desk's own "
                 f"whole-lot trades against that contract's ₹{SCRIPT_CAPITAL:,.0f}. These are "
                 "not the paper desk's numbers."),
    }


async def summary() -> dict:
    state = await get_state()
    universe = sorted(await prelive_universe())
    flags = await script_flags()
    active = [s for s in universe if flags.get(s, True)]

    realized = unrealized = deployed = costs = 0.0
    async for p in commodity_prelive_positions_collection.find(
        {"status": "OPEN"}, {"margin_used": 1, "unrealized_pnl": 1, "entry_costs": 1}
    ):
        deployed += p.get("margin_used") or 0.0
        unrealized += p.get("unrealized_pnl") or 0.0
        costs += p.get("entry_costs") or 0.0
    async for p in commodity_prelive_positions_collection.find(
        {"status": {"$ne": "OPEN"}}, {"realized_pnl": 1, "costs": 1}
    ):
        realized += p.get("realized_pnl") or 0.0
        costs += p.get("costs") or 0.0

    verdicts = {"READY": 0, "REJECTED": 0, "PENDING": 0}
    async for s in commodity_prelive_scores_collection.find({}, {"verdict": 1}):
        v = s.get("verdict", "PENDING")
        verdicts[v] = verdicts.get(v, 0) + 1

    admit = await admissions()
    # The desk's stake is every contract's lakh, switched on or not: a contract that is off
    # still holds its book and any position left open in it.
    base = SCRIPT_CAPITAL * max(len(universe), 1)
    return {
        **state,
        "script_capital": SCRIPT_CAPITAL,
        "scripts": universe, "active_scripts": active,
        "script_count": len(universe), "active_script_count": len(active),
        "initial_capital": base,
        "capital_switched_on": SCRIPT_CAPITAL * len(active),
        "equity": round(base + realized + unrealized, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "margin_deployed": round(deployed, 2),
        "available_margin": round(base + realized - deployed, 2),
        "total_costs": round(costs, 2),
        "open_positions": await commodity_prelive_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": await commodity_prelive_positions_collection.count_documents({"status": {"$ne": "OPEN"}}),
        "admitted_total": admit["total"], "admitted_by_script": admit["counts"],
        "admission_counts": await admission_counts_both(),
        "ready_count": verdicts["READY"], "rejected_count": verdicts["REJECTED"],
        "pending_count": verdicts["PENDING"],
        "mode": "paper", "costs_charged": True, "sizing": "whole_lots_on_margin",
        "slippage_bps": SLIPPAGE_BPS, "market_open": is_market_open(),
        "max_positions_per_script": MAX_POSITIONS_PER_SCRIPT,
        "max_lots_per_position": MAX_LOTS_PER_POSITION,
        "promotion_gate": {"min_trades": MIN_TRADES_FOR_VERDICT, "min_profit_factor": MIN_PROFIT_FACTOR,
                           "min_win_rate": MIN_WIN_RATE, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                           "min_t_stat": MIN_T_STAT},
        **(await breaker_state()),
    }


async def ensure_indexes() -> None:
    """Best-effort. An index is a speed-up, never a precondition for the desk to load.

    THIS MUST NOT RAISE. The first version let `create_index` propagate, and on a cluster
    whose writes were blocked (Atlas M0 at its 512 MB quota) that single exception escaped
    the startup hook and took the WHOLE BACKEND down — every unrelated desk with it — for
    a set of indexes nothing needs to serve a page. Every other module here already logs
    and continues; this one now does too."""
    specs = [
        (commodity_prelive_positions_collection, [("symbol", 1), ("status", 1)],
         "cpl_pos_symbol_status", False),
        (commodity_prelive_positions_collection,
         [("strategy_id", 1), ("symbol", 1), ("status", 1)], "cpl_pos_strategy_symbol", False),
        (commodity_prelive_positions_collection, [("closed_at", -1)], "cpl_pos_closed_at", False),
        (commodity_prelive_trades_collection, [("symbol", 1), ("closed_at", -1)],
         "cpl_trade_symbol_closed", False),
        (commodity_prelive_scores_collection, [("symbol", 1), ("strategy_id", 1)],
         "cpl_score_key", True),
        (commodity_prelive_flags_collection, [("symbol", 1)], "cpl_flag_symbol", True),
        (commodity_prelive_equity_collection, [("ts", -1)], "cpl_equity_ts", False),
    ]
    made = skipped = 0
    for coll, keys, name, unique in specs:
        try:
            await coll.create_index(keys, name=name, unique=unique, background=True)
            made += 1
        except Exception as exc:  # noqa: BLE001 — one failure must not skip the rest
            skipped += 1
            logger.warning("[commodity_prelive] index %s skipped: %s", name, exc)
    logger.info("[commodity_prelive] indexes ensured (%d present, %d skipped)", made, skipped)
