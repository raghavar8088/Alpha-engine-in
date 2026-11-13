"""Real money on Delta Exchange India for ten Premium strategies (2026-11-13).

The owner asked for five bitcoin and five gold strategies from Premium Strategies to trade REAL money on Delta,
and chose the size: $5 of risk a trade and a $20 daily loss stop. Before choosing, the owner was shown the record:
since 8 Nov the desk's 107 bitcoin books lost -397R over 585 trades and its 90 gold books -166R; of the ten below, six
lose in their own 2-year backtests (700-2,900 trades each) and four were never backtested; every backtested bitcoin
strategy in the module loses after Delta's fee but one with 24 trades. None is proven. This desk exists because the
owner chose to trade them anyway, at a size meant to be affordable to lose.

THE TEN are frozen as picked on 13 Nov 2026 at 23:00 IST: the five bitcoin and five gold paper books with the best
record since 8 Nov among those with at least five closed trades and a net profit, ranked by the t-stat of their net
R a trade (R = what a trade risks).

WHAT IT DOES. It copies the paper desk's trades of those ten (premium-paper-service's premium_trades, in the box's
local MongoDB) into real Delta orders. The paper desk decides every entry and exit, and this desk never re-scans:
- A paper entry is copied only if it is seen within MAX_LAG_S of its entry time, the market is still within
  DRIFT_FRAC of a risk distance of the paper entry, and the price is strictly between the paper's stop and target.
  The order is a market order sized so the paper's stop loses RISK_USD:
  contracts = RISK_USD / (|price - stop| x contract value), and never more than MAX_NOTIONAL_USD of notional.
- The paper's own stop and target go on the venue as a bracket right after the fill. If the bracket is refused, the
  position is closed at once and the desk switches itself off: a real position never stays unprotected.
- When the paper trade closes, for any reason, or disappears, the real one is closed at the market and its legs are
  cancelled. When the venue closes it first (its bracket), the close is recorded from Delta's fills.
- One real position per product at a time. Delta nets positions by product, so a signal on a product already held,
  by this desk or by anyone, is skipped. It is never stacked or netted.
- The daily loss stop: once today's (IST) closed plus open P&L reaches -DAILY_STOP_USD, no new entry until tomorrow.
- Before going live, leverage is set to LEVERAGE on both products and read back. Delta's defaults, 200x on BTCUSD and
  100x on XAUTUSD, liquidate inside the strategies' stops.

MODES
- off: no new trade; open positions are still managed to their close.
- shadow: every decision is made and logged with simulated fills at the quote, and no order is sent.
- live: real orders.
Going live and flattening need the owner's PIN. Switching to off or shadow never does, since neither sends an order.
Three venue errors in a row switch the desk off.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from app.services import delta_rest as DR
from app.services.delta_rest import Delta, DeltaError, Product

logger = logging.getLogger("premium_live")

IST = timezone(timedelta(hours=5, minutes=30))
RISK_USD = float(os.getenv("PREMIUM_LIVE_RISK_USD", "5"))
DAILY_STOP_USD = float(os.getenv("PREMIUM_LIVE_DAILY_STOP_USD", "20"))
MAX_NOTIONAL_USD = float(os.getenv("PREMIUM_LIVE_MAX_NOTIONAL_USD", "2500"))
LEVERAGE = int(os.getenv("PREMIUM_LIVE_LEVERAGE", "10"))
MAX_LAG_S = int(os.getenv("PREMIUM_LIVE_MAX_LAG_S", "300"))
DRIFT_FRAC = float(os.getenv("PREMIUM_LIVE_DRIFT_FRAC", "0.30"))
TICK_S = int(os.getenv("PREMIUM_LIVE_TICK_S", "20"))
MISSING_GRACE_S = 300          # a paper trade gone this long is treated as closed
DESK_STALE_S = 1200            # the paper desk silent this long: no new entry
DESK_DEAD_S = 3600             # ... this long: open positions are closed (nothing can manage them)
MARGIN_BUFFER = 1.25           # free balance needed: margin x this
ERRORS_TO_STOP = 3
PIN_TRIES = 5                  # wrong PINs an hour before going live is locked for the hour
GST = 0.18                     # on Delta India's fees (shadow estimates only; live uses Delta's own figures)
PICKED_AT = "2026-11-13T23:00:00+05:30"
CONFIRM = "REAL MONEY"
D = Delta()


@dataclass(frozen=True)
class Pick:
    acct: str
    mkt: str            # the paper desk's market key
    product: str        # the Delta perpetual it trades
    name: str
    trades: int         # its paper record at the pick: closed trades since 8 Nov
    sum_r: float        # net R
    t: float            # t-stat of the net R a trade
    win: int            # % of trades won
    backtest: str       # what its own 2-year backtest said


PICKS: tuple[Pick, ...] = (
    Pick("TH-01", "BTCUSD", "BTCUSD", "Bitcoin 6 PM session: anchored VWAP + EMA 25, the N pattern", 8, 10.82, 0.56, 12,
         "never backtested"),
    Pick("TH-05", "BTCUSD", "BTCUSD", "EMA 50/200 trend, pullback to EMA 50 with RSI 40-55", 8, 2.75, 0.42, 38,
         "never backtested"),
    Pick("RU-04", "BTCUSD", "BTCUSD", "Williams fractal breakout in the 200 MA trend, 1.5R", 7, 1.06, 0.34, 43,
         "loses: -0.16R a trade over 1,178 trades (t -5.3)"),
    Pick("TD-02", "BTCUSD", "BTCUSD", "9/15 EMA cross filtered by the SMI (7, 2, 2)", 5, 0.84, 0.17, 40,
         "loses: -0.37R a trade over 998 trades (t -3.5)"),
    Pick("TD-03", "BTCUSD", "BTCUSD", "UT Bot pair + Schaff Trend Cycle, 2R (15-minute)", 6, 0.48, 0.13, 50,
         "loses: -0.20R a trade over 1,092 trades (t -5.5)"),
    Pick("RU-02", "XAUTUSD", "XAUTUSD", "Stochastic below 20, then a MACD cross, 1.5R (30-minute)", 5, 2.73, 1.47, 60,
         "loses: -0.06R a trade over 795 trades (t -1.6)"),
    Pick("CP-23", "XAUUSD", "XAUTUSD", "Inducement", 8, 5.29, 1.33, 62, "never backtested"),
    Pick("YT-14", "XAUUSD", "XAUTUSD", "MA fan + engulfing / three-line strike, RSI 50", 13, 5.19, 1.15, 62,
         "loses: -0.14R a trade over 2,317 trades"),
    Pick("DR-01", "XAUTUSD", "XAUTUSD", "EMA 200 side + counter-trend-line breakout, 1:2 (15-minute)", 15, 5.27, 0.88, 53,
         "loses: -0.26R a trade over 1,467 trades (t -7.3)"),
    Pick("CP-05", "XAUUSD", "XAUTUSD", "Turning-point zones (3 touches)", 8, 3.74, 0.86, 50, "never backtested"),
)
PICK = {(p.acct, p.mkt): p for p in PICKS}
PRODUCTS = sorted({p.product for p in PICKS})
NOTES = (
    "Real money on ten unproven strategies, at the owner's chosen size: $5 risked a trade, a $20 daily loss stop.",
    "Six of the ten lose in their own 2-year backtests and four were never backtested; their good week is the only "
    "thing that picked them.",
    "Each real trade is the paper desk's trade: its entry signal, its stop, its target, its exit. The paper desk sees a "
    "new bar up to a few minutes late, so a fast strategy's copy is often skipped as late or drifted rather than chased.",
    "Delta nets positions by product, so only one bitcoin and one gold position can be open at a time; a second signal "
    "is skipped while one is held.",
    "Stops and targets live on Delta itself (a bracket), so a position stays protected if this server goes down.",
    "Leverage is set to 10x on both products before going live; positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
)


# -- small helpers -------------------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _day(t: float | None = None) -> str:
    return datetime.fromtimestamp(t if t is not None else _now(), IST).date().isoformat()


def _db():
    """The box's local MongoDB that holds the paper desk (premium_paper._database); None when not configured."""
    from app.api.routes.premium_paper import _database
    return _database()


def _cid(trade_id: str, suffix: str = "") -> str:
    """A client order id Delta keeps beside its own: the paper trade's id, hashed (Delta allows 32 characters)."""
    return ("p5" + hashlib.sha1(trade_id.encode()).hexdigest())[:30 - len(suffix)] + suffix


def _side(side: int) -> str:
    return "buy" if side > 0 else "sell"


def _fee(notional: float, rate: float) -> float:
    return abs(notional) * rate * (1 + GST)


async def _state(db) -> dict:
    st = await db.live_delta_state.find_one({"_id": "state"})
    if st is None:
        st = {"_id": "state", "mode": "off", "since": _now(), "errors_in_row": 0, "pin_fails": [], "products": {},
              "created_at": _now()}
        await db.live_delta_state.update_one({"_id": "state"}, {"$setOnInsert": {k: v for k, v in st.items() if k != "_id"}},
                                             upsert=True)
        st = await db.live_delta_state.find_one({"_id": "state"}) or st
    return st


async def _set_state(db, **fields) -> None:
    await db.live_delta_state.update_one({"_id": "state"}, {"$set": {**fields, "updated_at": _now()}}, upsert=True)


async def _set_trade(db, tid: str, **fields) -> None:
    await db.live_delta_trades.update_one({"_id": tid}, {"$set": {**fields, "updated_at": _now()}})


async def _venue_error(db, st: dict, what: str) -> None:
    n = int(st.get("errors_in_row") or 0) + 1
    st["errors_in_row"] = n
    fields = {"errors_in_row": n, "last_error": what, "last_error_at": _now()}
    if n >= ERRORS_TO_STOP and st.get("mode") == "live":
        fields.update(mode="off", switched_off=f"{n} venue errors in a row: {what}")
        st["mode"] = "off"
    await _set_state(db, **fields)
    logger.warning("[premium live] %s", what)


async def _switch_off(db, st: dict, why: str) -> None:
    st["mode"] = "off"
    await _set_state(db, mode="off", switched_off=why, last_error=why, last_error_at=_now())
    logger.error("[premium live] switched off: %s", why)


async def _products(db, st: dict) -> dict[str, Product]:
    """Both products' specs from Delta, cached in the state; never a default (sizes differ a thousandfold)."""
    cached = st.get("products") or {}
    out: dict[str, Product] = {}
    for sym in PRODUCTS:
        c = cached.get(sym)
        if c and _now() - float(c.get("at") or 0) < 6 * 3600:
            out[sym] = Product(int(c["id"]), sym, float(c["contract_value"]), float(c["tick"]),
                               float(c["maintenance_pct"]), float(c["taker_rate"]))
            continue
        p = await D.product(sym)
        out[sym] = p
        cached[sym] = {**asdict(p), "at": _now(), "leverage": (c or {}).get("leverage")}
    st["products"] = cached
    await _set_state(db, products=cached)
    return out


async def _desk_age(db) -> float:
    """Seconds since the paper desk last wrote its status (it does after every cycle)."""
    s = await db.premium_meta.find_one({"_id": "status"}, {"segments_at": 1})
    try:
        at = datetime.fromisoformat(str((s or {}).get("segments_at")))
        return _now() - (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return float("inf")


async def _paper(db, since: float, ids: list[str]) -> dict[str, dict]:
    """The ten books' sized paper trades that entered since `since`, plus any an open real trade points at."""
    q = {"acct": {"$in": sorted({p.acct for p in PICKS})}, "qty": {"$gt": 0},
         "$or": [{"entry_t": {"$gte": int(since) - MAX_LAG_S}}, {"_id": {"$in": ids}}]}
    out = {}
    async for t in db.premium_trades.find(q):
        if (t.get("acct"), t.get("mkt")) in PICK:
            out[t["_id"]] = t
    return out


# -- P&L -----------------------------------------------------------------------------------------------


def _pnl(side: int, entry: float, exit_: float, contracts: int, cv: float, fees: float) -> float:
    return round(side * (exit_ - entry) * contracts * cv - fees, 4)


async def _exit_from_fills(t: dict, product: Product, fallback_price: float | None, fallback_fee: float | None) -> dict:
    """The exit as Delta recorded it: the fills on the product after the entry that are not the entry order's own."""
    try:
        rows = await D.fills(product.id, float(t.get("opened_at") or _now()) - 5)
    except DeltaError:
        rows = []
    entry_id = str((t.get("entry_order") or {}).get("id") or "")
    close_side = "sell" if t["side"] > 0 else "buy"
    ex = [f for f in rows if f["order_id"] != entry_id and str(f.get("side")).lower() == close_side and f["size"] > 0]
    size = sum(f["size"] for f in ex)
    if size >= t["contracts"]:
        take, left, px, fee = [], t["contracts"], 0.0, 0.0
        for f in sorted(ex, key=lambda f: str(f.get("created_at"))):
            n = min(left, f["size"])
            px += f["price"] * n
            fee += f["commission"] * n / f["size"]
            left -= n
            if left <= 0:
                break
        return {"price": px / t["contracts"], "fee": fee, "basis": "fills"}
    if fallback_price:
        return {"price": fallback_price, "fee": fallback_fee if fallback_fee is not None
                else _fee(fallback_price * t["contracts"] * product.contract_value, product.taker_rate), "basis": "order"}
    # nothing read: the stop's limit, the worst the bracket allowed, so the daily stop errs on the safe side
    worst = float((t.get("legs") or {}).get("stop_limit") or t["stop"])
    return {"price": worst, "fee": _fee(worst * t["contracts"] * product.contract_value, product.taker_rate),
            "basis": "estimated (no fills read)"}


async def _record_close(db, t: dict, ex: dict, reason: str, product: Product) -> None:
    fees = float(t.get("entry_fee") or 0.0) + float(ex["fee"] or 0.0)
    pnl = _pnl(t["side"], float(t["fill"]), float(ex["price"]), int(t["contracts"]), product.contract_value, fees)
    await _set_trade(db, t["_id"], status="closed", exit_price=round(float(ex["price"]), 6), exit_fee=round(float(ex["fee"]), 6),
                     exit_basis=ex["basis"], fees=round(fees, 6), pnl_usd=pnl, r=round(pnl / RISK_USD, 3),
                     close_reason=reason, closed_at=_now(), day_closed=_day(), unrealised_usd=0.0)


async def _day_pnl(db, mode: str, positions: dict | None) -> float:
    """Today's (IST) closed P&L plus the open trades' marks, in USD, for one mode."""
    total = 0.0
    async for t in db.live_delta_trades.find({"mode": mode, "day_closed": _day(), "status": "closed"}, {"pnl_usd": 1}):
        total += float(t.get("pnl_usd") or 0.0)
    async for t in db.live_delta_trades.find({"mode": mode, "status": {"$in": ["open", "closing"]}}, {"unrealised_usd": 1}):
        total += float(t.get("unrealised_usd") or 0.0)
    return round(total, 4)


# -- managing what is open -------------------------------------------------------------------------------


async def _manage_live(db, st: dict, t: dict, paper: dict | None, positions: dict, products: dict, desk_age: float) -> None:
    product = products[t["product"]]
    pos = positions.get(product.id)
    size = int(pos["size"]) if pos else 0
    if t["status"] == "entering":
        # left half-done (the process stopped between the order and its record)
        if _now() - float(t.get("created_at") or 0) < 90:
            return
        if size and (size > 0) == (t["side"] > 0) and t.get("adoptable", True):
            await _set_trade(db, t["_id"], status="open", contracts=abs(size), fill=pos["entry"], opened_at=_now(),
                             recovered=True)
            t.update(status="open", contracts=abs(size), fill=pos["entry"])
            try:
                legs = await D.bracket(product, _side(t["side"]), pos["entry"], float(t["stop"]),
                                       float(t["target"]) if t.get("target") else None)
                await _set_trade(db, t["_id"], legs=_legs(legs))
            except DeltaError as exc:
                await _set_trade(db, t["_id"], status="closing", close_reason=f"bracket refused on recovery: {exc}")
                await _switch_off(db, st, f"{t['acct']}: bracket refused on recovery ({exc})")
            return
        await _set_trade(db, t["_id"], status="skipped", reason="entry not confirmed by Delta")
        return
    if size == 0:
        # flat on the venue: its bracket (or anyone) closed it
        try:
            await D.cancel_stops(product.id)
        except DeltaError:
            pass
        ex = await _exit_from_fills(t, product, None, None)
        lv = t.get("legs") or {}
        why = "venue stop" if lv.get("stop") and _near(ex["price"], float(lv["stop"]), float(t["fill"])) else \
              "venue target" if lv.get("target") and _near(ex["price"], float(lv["target"]), float(t["fill"])) else "closed on Delta"
        await _record_close(db, t, ex, why, product)
        return
    if (size > 0) != (t["side"] > 0):
        await _switch_off(db, st, f"{product.symbol}: the account's position is opposite to {t['acct']}'s trade; "
                                  "not touched - check Delta")
        return
    reason = None
    if t["status"] == "closing":
        reason = t.get("close_reason") or "closing"
    elif paper is None:
        gone = float(t.get("paper_missing_since") or 0)
        if not gone:
            await _set_trade(db, t["_id"], paper_missing_since=_now())
        elif _now() - gone > MISSING_GRACE_S:
            reason = "the paper trade disappeared"
    elif not paper.get("open"):
        reason = f"paper exit: {paper.get('reason') or 'closed'}"
    elif desk_age > DESK_DEAD_S:
        reason = "the paper desk stopped updating"
    if reason is None:
        mark = float(pos.get("mark") or 0.0)
        u = _pnl(t["side"], float(t["fill"]), mark, abs(size), product.contract_value, float(t.get("entry_fee") or 0.0)) if mark else 0.0
        fields = {"mark": mark, "unrealised_usd": u, "contracts_open": abs(size)}
        if paper is not None:
            fields["paper_missing_since"] = None       # seen again: the grace clock starts over
        await _set_trade(db, t["_id"], **fields)
        return
    try:
        o = await D.market(product.id, abs(size), "sell" if t["side"] > 0 else "buy", reduce_only=True,
                           client_order_id=_cid(t["_id"], "x"))
    except DeltaError as exc:
        await _set_trade(db, t["_id"], status="closing", close_reason=reason)
        await _venue_error(db, st, f"{t['acct']}: close refused ({exc})")
        return
    try:
        await D.cancel_stops(product.id)
    except DeltaError:
        pass
    ex = await _exit_from_fills(t, product, o.get("avg_price") or None, o.get("commission"))
    await _record_close(db, t, ex, reason, product)


def _near(px: float, level: float, entry: float) -> bool:
    return abs(px - level) <= max(abs(entry - level) * 0.35, 1e-9)


def _legs(legs: dict) -> dict:
    sl, tp = legs.get("stop_loss_order") or {}, legs.get("take_profit_order") or {}
    return {"stop": sl.get("stop_price"), "stop_limit": sl.get("limit_price"), "target": tp.get("stop_price")}


async def _manage_shadow(db, t: dict, paper: dict | None, desk_age: float, products: dict) -> None:
    product = products[t["product"]]
    reason, at = None, None
    if paper is None:
        gone = float(t.get("paper_missing_since") or 0)
        if not gone:
            await _set_trade(db, t["_id"], paper_missing_since=_now())
            return
        if _now() - gone > MISSING_GRACE_S:
            reason = "the paper trade disappeared"
    elif not paper.get("open"):
        reason = f"paper exit: {paper.get('reason') or 'closed'}"
        if paper.get("reason") in ("stop", "target", "be_stop", "stop_gap") and paper.get("exit"):
            at = float(paper["exit"])           # a venue bracket would have filled about there
    elif desk_age > DESK_DEAD_S:
        reason = "the paper desk stopped updating"
    if reason is None and t["status"] != "closing":
        try:
            q = await D.ticker(product.symbol)
            mark = q["bid"] if t["side"] > 0 else q["ask"]
            u = _pnl(t["side"], float(t["fill"]), mark, int(t["contracts"]), product.contract_value,
                     float(t.get("entry_fee") or 0.0))
            fields = {"mark": mark, "unrealised_usd": u}
            if paper is not None:
                fields["paper_missing_since"] = None
            await _set_trade(db, t["_id"], **fields)
        except DeltaError:
            pass
        return
    if at is None:
        try:
            q = await D.ticker(product.symbol)
            at = q["bid"] if t["side"] > 0 else q["ask"]
        except DeltaError:
            return
    ex = {"price": at, "fee": _fee(at * int(t["contracts"]) * product.contract_value, product.taker_rate), "basis": "simulated"}
    await _record_close(db, t, ex, reason or "closing", product)


# -- entries -------------------------------------------------------------------------------------------


async def _enter(db, st: dict, pick: Pick, paper: dict, products: dict, positions: dict | None, busy: set,
                 day_pnl: float, desk_age: float) -> str:
    """Decide one new paper trade, once. Returns what happened, for the cycle's report."""
    tid, mode = paper["_id"], st["mode"]
    side = 1 if int(paper.get("side") or 0) > 0 else -1
    stop = float(paper.get("stop") or 0.0)
    target = float(paper["target"]) if paper.get("target") else None
    entry = float(paper.get("entry") or 0.0)
    base = {"_id": tid, "acct": pick.acct, "mkt": pick.mkt, "product": pick.product, "name": pick.name, "mode": mode,
            "side": side, "paper_entry": entry, "paper_entry_t": paper.get("entry_t"), "stop": stop, "target": target,
            "setup": paper.get("setup"), "day": _day(), "created_at": _now()}

    async def skip(why: str, **extra) -> str:
        try:
            await db.live_delta_trades.insert_one({**base, **extra, "status": "skipped", "reason": why})
        except Exception:  # noqa: BLE001 - decided by an earlier pass
            pass
        return f"skipped: {why}"

    lag = _now() - float(paper.get("entry_t") or 0)
    if not paper.get("open"):
        return await skip("closed on paper before it could be copied")
    if lag > MAX_LAG_S:
        return await skip(f"seen {lag / 60:.0f} min after its entry (limit {MAX_LAG_S // 60})", lag_s=round(lag))
    if stop <= 0 or entry <= 0:
        return await skip("no stop on the paper trade")
    if day_pnl <= -DAILY_STOP_USD:
        return await skip(f"daily loss stop reached ({day_pnl:+.2f} USD today)")
    if desk_age > DESK_STALE_S:
        return await skip("the paper desk has not updated for over 20 minutes")
    product = products[pick.product]
    if pick.product in busy:
        return await skip(f"{pick.product} already holds this desk's position (Delta nets by product)")
    if positions is not None and product.id in positions:
        return await skip(f"the account already holds a {pick.product} position")
    try:
        q = await D.ticker(product.symbol)
    except DeltaError as exc:
        return await skip(f"no quote ({exc})")
    px = q["ask"] if side > 0 else q["bid"]
    lo, hi = (stop, target if target else math.inf) if side > 0 else (target if target else 0.0, stop)
    if not lo < px < hi:
        return await skip(f"price {px} is no longer between the stop and the target", price=px)
    if abs(px - entry) > DRIFT_FRAC * abs(entry - stop):
        return await skip(f"price moved {abs(px - entry) / abs(entry - stop):.0%} of the risk away from the paper entry",
                          price=px)
    by_risk = math.floor(RISK_USD / (abs(px - stop) * product.contract_value))
    by_cap = math.floor(MAX_NOTIONAL_USD / (px * product.contract_value))
    contracts = min(by_risk, by_cap)
    if contracts < 1:
        return await skip("under one contract at this risk", price=px)
    notional = contracts * product.contract_value * px
    plan = {"price": px, "contracts": contracts, "risk_usd": round(abs(px - stop) * contracts * product.contract_value, 4),
            "notional_usd": round(notional, 2), "margin_usd": round(notional / LEVERAGE, 2), "capped": by_cap < by_risk}

    if mode == "shadow":
        fee = _fee(notional, product.taker_rate)
        await db.live_delta_trades.insert_one({**base, "status": "open", "plan": plan, "contracts": contracts, "fill": px,
                                               "entry_fee": round(fee, 6), "opened_at": _now(), "unrealised_usd": -fee})
        busy.add(pick.product)
        return f"shadow entry: {contracts} {pick.product} at {px}"

    try:
        w = await D.wallet()
    except DeltaError as exc:
        await _venue_error(db, st, f"wallet read failed ({exc})")
        return await skip("could not read the wallet")
    if w["available"] < plan["margin_usd"] * MARGIN_BUFFER:
        return await skip(f"not enough free balance (${w['available']:.2f} for ${plan['margin_usd']:.2f} of margin)")
    await db.live_delta_trades.insert_one({**base, "status": "entering", "plan": plan, "contracts": contracts})
    busy.add(pick.product)
    try:
        o = await D.market(product.id, contracts, _side(side), client_order_id=_cid(tid))
    except DeltaError as exc:
        if exc.ambiguous:
            # the order may have filled: it stays "entering", and the next cycles adopt it from the account or drop it
            await _set_trade(db, tid, reason=f"entry answer lost ({exc}); checking the account")
            await _venue_error(db, st, f"{pick.acct}: entry answer lost ({exc})")
            return f"error: entry answer lost ({exc})"
        await _set_trade(db, tid, status="error", reason=f"entry refused: {exc}", adoptable=False)
        await _venue_error(db, st, f"{pick.acct}: entry refused ({exc})")
        return f"error: entry refused ({exc})"
    if o["filled"] < 1:
        await _set_trade(db, tid, status="skipped", reason="the market order did not fill", entry_order=o)
        return "skipped: not filled"
    fill = float(o["avg_price"] or px)
    await _set_trade(db, tid, contracts=o["filled"], fill=fill, entry_fee=float(o.get("commission") or 0.0), entry_order=o,
                     opened_at=_now())
    try:
        legs = await D.bracket(product, _side(side), fill, stop, target)
    except DeltaError as exc:
        # never left unprotected: out at once, and the desk stops until someone looks
        await _set_trade(db, tid, status="closing", close_reason=f"bracket refused: {exc}")
        await _switch_off(db, st, f"{pick.acct} {pick.product}: bracket refused ({exc}); the position was closed")
        try:
            o2 = await D.market(product.id, o["filled"], "sell" if side > 0 else "buy", reduce_only=True,
                                client_order_id=_cid(tid, "x"))
        except DeltaError:
            return f"error: bracket refused ({exc}); the close is retried every cycle"
        try:
            await D.cancel_stops(product.id)
        except DeltaError:
            pass
        t = await db.live_delta_trades.find_one({"_id": tid})
        ex = await _exit_from_fills(t, product, o2.get("avg_price") or None, o2.get("commission"))
        await _record_close(db, t, ex, f"bracket refused, closed at once: {exc}", product)
        return f"error: bracket refused ({exc}); closed at once"
    await _set_trade(db, tid, status="open", legs=_legs(legs), unrealised_usd=-float(o.get("commission") or 0.0))
    st["errors_in_row"] = 0
    await _set_state(db, errors_in_row=0)
    return f"live entry: {o['filled']} {pick.product} at {fill}"


# -- the cycle -----------------------------------------------------------------------------------------

_lock = asyncio.Lock()


async def cycle() -> dict:
    db = _db()
    if db is None:
        return {"error": "the paper desk's database is not configured on this server"}
    async with _lock:
        st = await _state(db)
        await _set_state(db, last_cycle_at=_now())
        out: dict = {"mode": st["mode"], "managed": [], "entered": []}
        open_rows = [t async for t in db.live_delta_trades.find({"status": {"$in": ["entering", "open", "closing"]}})]
        if st["mode"] == "off" and not open_rows:
            return out
        try:
            products = await _products(db, st)
        except DeltaError as exc:
            await _venue_error(db, st, f"product specs unavailable ({exc})")
            return {**out, "error": str(exc)}
        desk_age = await _desk_age(db)
        paper = await _paper(db, float(st.get("since") or _now()), [t["_id"] for t in open_rows])
        live_rows = [t for t in open_rows if t.get("mode") == "live"]
        positions: dict | None = None
        if st["mode"] == "live" or live_rows:
            try:
                positions = await D.positions()
            except DeltaError as exc:
                await _venue_error(db, st, f"positions unavailable ({exc})")
                positions = None
            if positions is not None and _now() - float(st.get("wallet_at") or 0) > 300:
                try:
                    await _set_state(db, wallet=await D.wallet(), wallet_at=_now())
                except DeltaError:
                    pass
        for t in open_rows:
            if t.get("mode") == "live":
                if positions is not None:
                    await _manage_live(db, st, t, paper.get(t["_id"]), positions, products, desk_age)
            else:
                await _manage_shadow(db, t, paper.get(t["_id"]), desk_age, products)
            out["managed"].append(t["_id"])
        if st["mode"] == "off" or (st["mode"] == "live" and positions is None):
            return out
        decided = {t["_id"] async for t in db.live_delta_trades.find({"_id": {"$in": list(paper)}}, {"_id": 1})}
        still_open = [t async for t in db.live_delta_trades.find({"status": {"$in": ["entering", "open", "closing"]}},
                                                                 {"product": 1, "mode": 1})]
        busy = {t["product"] for t in still_open}
        if st["mode"] == "live" and positions is not None:
            try:
                positions = await D.positions()
            except DeltaError as exc:
                await _venue_error(db, st, f"positions unavailable ({exc})")
                return out
        day_pnl = await _day_pnl(db, st["mode"], positions)
        for tid, p in sorted(paper.items(), key=lambda kv: kv[1].get("entry_t") or 0):
            if tid in decided or float(p.get("entry_t") or 0) < float(st.get("since") or 0):
                continue
            if st["mode"] not in ("shadow", "live"):
                break
            res = await _enter(db, st, PICK[(p["acct"], p["mkt"])], p, products, positions if st["mode"] == "live" else None,
                               busy, day_pnl, desk_age)
            out["entered"].append({"id": tid, "result": res})
        return out


async def loop() -> None:
    """Every TICK_S seconds, around the clock. Started by the premium routes' startup hook."""
    await asyncio.sleep(60)
    while True:
        try:
            r = await cycle()
            if r.get("entered") or r.get("error"):
                logger.info("[premium live] %s", r)
        except Exception:  # noqa: BLE001 - the loop must outlive any one bad cycle
            logger.warning("[premium live] cycle failed", exc_info=True)
        await asyncio.sleep(TICK_S)


# -- the owner's controls ------------------------------------------------------------------------------


def _pin_ok(pin: str | None) -> bool | None:
    """True / False, or None when no PIN is set on the server."""
    s = DR.secrets()
    want, salt = s.get("LIVE_ARM_PIN_SHA256"), s.get("LIVE_ARM_SALT", "")
    if not want:
        return None
    got = hashlib.sha256((salt + (pin or "")).encode()).hexdigest()
    return hmac.compare_digest(got, want)


async def _check_pin(db, st: dict, pin: str | None) -> str | None:
    """None if the PIN is right; otherwise why not (wrong PINs are counted and lock it for the hour)."""
    fails = [f for f in (st.get("pin_fails") or []) if _now() - float(f) < 3600]
    if len(fails) >= PIN_TRIES:
        return "too many wrong PINs: locked for an hour"
    ok = _pin_ok(pin)
    if ok is None:
        return "no PIN is set on the server (the deploy script sets it)"
    if not ok:
        await _set_state(db, pin_fails=fails + [_now()])
        return f"wrong PIN ({PIN_TRIES - len(fails) - 1} tries left this hour)"
    if fails:
        await _set_state(db, pin_fails=[])
    return None


async def set_mode(mode: str, pin: str | None = None, confirm: str | None = None) -> dict:
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    if mode not in ("off", "shadow", "live"):
        return {"ok": False, "why": f"unknown mode {mode!r}"}
    st = await _state(db)
    if mode in ("off", "shadow"):
        fields = {"mode": mode, "switched_off": None}
        if mode == "shadow" and st.get("mode") != "shadow":
            fields["since"] = _now()
        await _set_state(db, **fields)
        return {"ok": True, "mode": mode}
    why = await _check_pin(db, st, pin)
    if why:
        return {"ok": False, "why": why}
    if (confirm or "").strip().upper() != CONFIRM:
        return {"ok": False, "why": f"type {CONFIRM} to confirm real orders"}
    if not DR.configured():
        return {"ok": False, "why": "Delta API keys are not set on the server (the deploy script sets them)"}
    try:
        products = await _products(db, st)
        w = await D.wallet()
        positions = await D.positions()
        lev = {}
        for sym, p in products.items():
            got = await D.set_leverage(p.id, LEVERAGE)
            read = await D.leverage(p.id)
            if int(round(read or got)) != LEVERAGE:
                return {"ok": False, "why": f"{sym}: leverage reads {read or got}x, not {LEVERAGE}x"}
            lev[sym] = LEVERAGE
    except DeltaError as exc:
        return {"ok": False, "why": f"Delta refused the check: {exc}"}
    tracked = {t["product"] async for t in db.live_delta_trades.find({"mode": "live", "status": {"$in": ["entering", "open", "closing"]}},
                                                                     {"product": 1})}
    foreign = [sym for sym, p in products.items() if p.id in positions and sym not in tracked]
    if foreign:
        return {"ok": False, "why": f"the account already holds {', '.join(foreign)}: close it on Delta first"}
    cached = st.get("products") or {}
    for sym in lev:
        cached.setdefault(sym, {})["leverage"] = lev[sym]
    await _set_state(db, mode="live", since=_now(), armed_at=_now(), errors_in_row=0, switched_off=None,
                     products=cached, wallet=w, wallet_at=_now())
    return {"ok": True, "mode": "live", "wallet": w, "leverage": lev}


async def flatten(pin: str | None = None) -> dict:
    """Close every open real position this desk holds, now, and switch it off."""
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    st = await _state(db)
    why = await _check_pin(db, st, pin)
    if why:
        return {"ok": False, "why": why}
    await _set_state(db, mode="off", switched_off="flattened by the owner")
    n = 0
    async for t in db.live_delta_trades.find({"status": {"$in": ["open", "entering"]}}):
        await _set_trade(db, t["_id"], status="closing", close_reason="flattened by the owner")
        n += 1
    r = await cycle()
    return {"ok": True, "closing": n, "cycle": r}


# -- the read model ------------------------------------------------------------------------------------


def _clean(t: dict) -> dict:
    t = dict(t)
    t["id"] = t.pop("_id")
    return t


async def status() -> dict:
    db = _db()
    if db is None:
        return {"configured_db": False}
    st = await _state(db)
    rows = [t async for t in db.live_delta_trades.find({})]
    rows.sort(key=lambda t: -(float(t.get("created_at") or 0)))
    per: dict[str, dict] = {}
    for t in rows:
        if t.get("status") not in ("closed", "open", "closing", "entering"):
            continue
        x = per.setdefault(f"{t['mode']}|{t['acct']}|{t['mkt']}", {"trades": 0, "wins": 0, "pnl_usd": 0.0, "open": 0})
        if t["status"] == "closed":
            x["trades"] += 1
            x["wins"] += 1 if (t.get("pnl_usd") or 0) > 0 else 0
            x["pnl_usd"] = round(x["pnl_usd"] + float(t.get("pnl_usd") or 0.0), 4)
        else:
            x["open"] += 1
    picks = []
    for p in PICKS:
        picks.append({**asdict(p), "live": per.get(f"live|{p.acct}|{p.mkt}"), "shadow": per.get(f"shadow|{p.acct}|{p.mkt}")})
    today = {m: await _day_pnl(db, m, None) for m in ("live", "shadow")}
    totals = {}
    for m in ("live", "shadow"):
        closed = [t for t in rows if t.get("mode") == m and t.get("status") == "closed"]
        totals[m] = {"trades": len(closed), "wins": sum(1 for t in closed if (t.get("pnl_usd") or 0) > 0),
                     "pnl_usd": round(sum(float(t.get("pnl_usd") or 0) for t in closed), 4),
                     "fees_usd": round(sum(float(t.get("fees") or 0) for t in closed), 4),
                     "skipped": sum(1 for t in rows if t.get("mode") == m and t.get("status") == "skipped"),
                     "errors": sum(1 for t in rows if t.get("mode") == m and t.get("status") == "error")}
    return {
        "configured_db": True, "keys": DR.configured(), "pin_set": _pin_ok(None) is not None,
        "mode": st.get("mode"), "since": st.get("since"), "armed_at": st.get("armed_at"),
        "switched_off": st.get("switched_off"), "last_error": st.get("last_error"), "last_error_at": st.get("last_error_at"),
        "errors_in_row": st.get("errors_in_row"), "last_cycle_at": st.get("last_cycle_at"), "wallet": st.get("wallet"),
        "wallet_at": st.get("wallet_at"), "products": st.get("products"),
        "limits": {"risk_usd": RISK_USD, "daily_stop_usd": DAILY_STOP_USD, "max_notional_usd": MAX_NOTIONAL_USD,
                   "leverage": LEVERAGE, "max_lag_s": MAX_LAG_S, "drift_frac": DRIFT_FRAC, "tick_s": TICK_S},
        "today": today, "totals": totals, "picked_at": PICKED_AT, "picks": picks,
        "open": [_clean(t) for t in rows if t.get("status") in ("entering", "open", "closing")],
        "recent": [_clean(t) for t in rows[:150]], "notes": list(NOTES),
    }
