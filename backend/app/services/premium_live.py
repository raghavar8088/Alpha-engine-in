"""Real money on Delta Exchange India for Premium strategies: two desks on one engine (2026-11-13, split 2026-11-14).

DESKS. Each desk has its own picks, products, switch (off / shadow / live), daily loss stop, state and trade records;
they share the Delta account, its keys and the owner's PIN, and never trade the same product.
- gold (Premium Strategies > "Real money · Delta gold"): the five gold picks of 13 Nov, on XAUTUSD. Its records are the
  original ones (live_delta_state / live_delta_trades).
- crypto (the "Delta Exchange Live Trading" module, 14 Nov): the bitcoin strategies the owner picked on 14 Nov from the
  Crypto tab - TH-05, TL-04 and TH-01 - on BTCUSD, $5 a trade, a $20 daily stop (live_crypto_state / live_crypto_trades).
  On 14 Nov the owner moved bitcoin here from the gold desk; the gold desk's earlier bitcoin picks (TH-01, TH-05, RU-04,
  TD-02, TD-03) left it, and any bitcoin trade it still had open would be managed by it to its close.

THE ORIGINAL DESK (13 Nov). The owner asked for five bitcoin and five gold strategies from Premium Strategies to trade
REAL money on Delta, and chose the size: $5 of risk a trade and a $20 daily loss stop. Before choosing, the owner was shown the record:
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
import contextlib
import contextvars
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
RISK_USD = float(os.getenv("PREMIUM_LIVE_RISK_USD", "5"))              # the gold desk
DAILY_STOP_USD = float(os.getenv("PREMIUM_LIVE_DAILY_STOP_USD", "20"))
CRYPTO_RISK_USD = float(os.getenv("PREMIUM_CRYPTO_RISK_USD", "5"))       # the crypto desk (the owner's choice, 14 Nov)
CRYPTO_DAILY_STOP_USD = float(os.getenv("PREMIUM_CRYPTO_DAILY_STOP_USD", "20"))
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
PICKED_AT = "2026-11-13T23:00:00+05:30"        # the gold desk
CRYPTO_PICKED_AT = "2026-11-14T09:44:00+05:30"
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


GOLD_PICKS: tuple[Pick, ...] = (
    Pick("RU-02", "XAUTUSD", "XAUTUSD", "Stochastic below 20, then a MACD cross, 1.5R (30-minute)", 5, 2.73, 1.47, 60,
         "loses: -0.06R a trade over 795 trades (t -1.6)"),
    Pick("CP-23", "XAUUSD", "XAUTUSD", "Inducement", 8, 5.29, 1.33, 62, "never backtested"),
    Pick("YT-14", "XAUUSD", "XAUTUSD", "MA fan + engulfing / three-line strike, RSI 50", 13, 5.19, 1.15, 62,
         "loses: -0.14R a trade over 2,317 trades"),
    Pick("DR-01", "XAUTUSD", "XAUTUSD", "EMA 200 side + counter-trend-line breakout, 1:2 (15-minute)", 15, 5.27, 0.88, 53,
         "loses: -0.26R a trade over 1,467 trades (t -7.3)"),
    Pick("CP-05", "XAUUSD", "XAUTUSD", "Turning-point zones (3 touches)", 8, 3.74, 0.86, 50, "never backtested"),
)
# picked by the owner on 14 Nov 2026 from the Crypto tab; records = their bitcoin paper trades at 09:44 IST
CRYPTO_PICKS: tuple[Pick, ...] = (
    Pick("TH-05", "BTCUSD", "BTCUSD", "EMA 50/200 trend, pullback to EMA 50 with RSI 40-55", 9, 8.41, 1.00, 44,
         "never backtested"),
    Pick("TL-04", "BTCUSD", "BTCUSD", "EMA 200 + RSI 50 + engulfing, stop two candles, 2R", 15, 3.58, 0.67, 47,
         "loses: -0.31R a trade over 2,134 trades (t -11.1)"),
    Pick("TH-01", "BTCUSD", "BTCUSD", "Bitcoin 6 PM session: anchored VWAP + EMA 25, the N pattern", 9, 9.55, 0.49, 11,
         "never backtested"),
)
GOLD_NOTES = (
    "Real money on five unproven gold strategies, at the owner's chosen size: $5 risked a trade, a $20 daily loss stop.",
    "Three of the five lose in their own 2-year backtests and two were never backtested; their good week is the only "
    "thing that picked them.",
    "On 14 Nov 2026 the owner moved the bitcoin strategies to the Delta Exchange Live Trading module; this desk trades "
    "gold (XAUTUSD) only.",
    "Each real trade is the paper desk's trade: its entry signal, its stop, its target, its exit. The paper desk sees a "
    "new bar up to a few minutes late, so a fast strategy's copy is often skipped as late or drifted rather than chased.",
    "Delta nets positions by product, so only one gold position can be open at a time; a second signal is skipped "
    "while one is held.",
    "Stops and targets live on Delta itself (a bracket), so a position stays protected if this server goes down.",
    "Leverage is set to 10x on XAUTUSD before going live; positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
)
CRYPTO_NOTES = (
    "Real money on three bitcoin strategies the owner picked on 14 Nov 2026 from the Crypto tab (TH-05, TL-04, TH-01), "
    "at the owner's chosen size: $5 risked a trade and a $20 daily loss stop.",
    "None is proven: TL-04 loses in its own 2-year bitcoin backtest (-0.31R a trade over 2,134 trades, t -11.1) and "
    "TH-05 and TH-01 were never backtested; 9 to 15 paper trades picked them.",
    "Each real trade is the paper desk's trade on Delta's live BTCUSD candles: its entry, stop, target and exit. A "
    "signal seen more than 5 minutes late, or already 30% of its risk away, is skipped, never chased.",
    "Delta nets positions by product, so only one bitcoin position can be open at a time across the three; a second "
    "signal is skipped while one is held.",
    "Stops and targets live on Delta itself (a bracket), so a position stays protected if this server goes down.",
    "Leverage is set to 10x on BTCUSD before going live; positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
    "This desk and the gold desk (Premium Strategies > Real money · Delta gold) share the Delta account, its keys and "
    "the PIN; each has its own switch and its own $20 daily stop.",
)


@dataclass(frozen=True)
class Desk:
    key: str
    title: str
    picks: tuple[Pick, ...]
    state_coll: str
    trades_coll: str
    risk_usd: float
    daily_stop_usd: float
    picked_at: str
    notes: tuple[str, ...]

    @property
    def pick(self) -> dict:
        return {(p.acct, p.mkt): p for p in self.picks}

    @property
    def products(self) -> list[str]:
        return sorted({p.product for p in self.picks})


DESKS: dict[str, Desk] = {
    "gold": Desk("gold", "Real money · Delta gold", GOLD_PICKS, "live_delta_state", "live_delta_trades", RISK_USD,
                 DAILY_STOP_USD, PICKED_AT, GOLD_NOTES),
    "crypto": Desk("crypto", "Delta Exchange Live Trading", CRYPTO_PICKS, "live_crypto_state", "live_crypto_trades",
                   CRYPTO_RISK_USD, CRYPTO_DAILY_STOP_USD, CRYPTO_PICKED_AT, CRYPTO_NOTES),
}
if set(DESKS["gold"].products) & set(DESKS["crypto"].products):
    raise RuntimeError("two desks may never trade the same product")
# The desk the current task works for. The loop and every API call set it (_use); the default is the gold desk, so
# a caller that names no desk gets the original one.
_CUR: contextvars.ContextVar[str] = contextvars.ContextVar("premium_live_desk", default="gold")


def _d() -> Desk:
    return DESKS[_CUR.get()]


@contextlib.contextmanager
def _use(key: str):
    if key not in DESKS:
        raise KeyError(key)
    tok = _CUR.set(key)
    try:
        yield DESKS[key]
    finally:
        _CUR.reset(tok)


def _sc(db):
    """This desk's state collection."""
    return getattr(db, _d().state_coll)


def _tc(db):
    """This desk's trade records."""
    return getattr(db, _d().trades_coll)

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
    st = await _sc(db).find_one({"_id": "state"})
    if st is None:
        st = {"_id": "state", "mode": "off", "since": _now(), "errors_in_row": 0, "pin_fails": [], "products": {},
              "created_at": _now()}
        await _sc(db).update_one({"_id": "state"}, {"$setOnInsert": {k: v for k, v in st.items() if k != "_id"}},
                                             upsert=True)
        st = await _sc(db).find_one({"_id": "state"}) or st
    return st


async def _set_state(db, **fields) -> None:
    await _sc(db).update_one({"_id": "state"}, {"$set": {**fields, "updated_at": _now()}}, upsert=True)


async def _set_trade(db, tid: str, **fields) -> None:
    await _tc(db).update_one({"_id": tid}, {"$set": {**fields, "updated_at": _now()}})


async def _venue_error(db, st: dict, what: str) -> None:
    n = int(st.get("errors_in_row") or 0) + 1
    st["errors_in_row"] = n
    fields = {"errors_in_row": n, "last_error": what, "last_error_at": _now()}
    if n >= ERRORS_TO_STOP and st.get("mode") == "live":
        fields.update(mode="off", switched_off=f"{n} venue errors in a row: {what}")
        st["mode"] = "off"
    await _set_state(db, **fields)
    logger.warning("[premium live %s] %s", _d().key, what)


async def _switch_off(db, st: dict, why: str) -> None:
    st["mode"] = "off"
    await _set_state(db, mode="off", switched_off=why, last_error=why, last_error_at=_now())
    logger.error("[premium live %s] switched off: %s", _d().key, why)


async def _products(db, st: dict, extra: set | None = None) -> dict[str, Product]:
    """The desk's products' specs from Delta (plus any product a still-open trade holds), cached in the state; never a
    default (sizes differ a thousandfold)."""
    cached = st.get("products") or {}
    out: dict[str, Product] = {}
    for sym in sorted(set(_d().products) | set(extra or ())):
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
    """The desk's picks' sized paper trades that entered since `since`, plus any an open real trade points at (kept
    even when its book is no longer a pick, so a trade from before a re-pick is still managed to its close)."""
    want = set(ids)
    q = {"qty": {"$gt": 0},
         "$or": [{"acct": {"$in": sorted({p.acct for p in _d().picks})}, "entry_t": {"$gte": int(since) - MAX_LAG_S}},
                 {"_id": {"$in": ids}}]}
    out = {}
    async for t in db.premium_trades.find(q):
        if t["_id"] in want or (t.get("acct"), t.get("mkt")) in _d().pick:
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
                     exit_basis=ex["basis"], fees=round(fees, 6), pnl_usd=pnl, r=round(pnl / _d().risk_usd, 3),
                     close_reason=reason, closed_at=_now(), day_closed=_day(), unrealised_usd=0.0)


async def _day_pnl(db, mode: str, positions: dict | None) -> float:
    """Today's (IST) closed P&L plus the open trades' marks, in USD, for one mode."""
    total = 0.0
    async for t in _tc(db).find({"mode": mode, "day_closed": _day(), "status": "closed"}, {"pnl_usd": 1}):
        total += float(t.get("pnl_usd") or 0.0)
    async for t in _tc(db).find({"mode": mode, "status": {"$in": ["open", "closing"]}}, {"unrealised_usd": 1}):
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
            await _tc(db).insert_one({**base, **extra, "status": "skipped", "reason": why})
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
    if day_pnl <= -_d().daily_stop_usd:
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
    by_risk = math.floor(_d().risk_usd / (abs(px - stop) * product.contract_value))
    by_cap = math.floor(MAX_NOTIONAL_USD / (px * product.contract_value))
    contracts = min(by_risk, by_cap)
    if contracts < 1:
        return await skip("under one contract at this risk", price=px)
    notional = contracts * product.contract_value * px
    plan = {"price": px, "contracts": contracts, "risk_usd": round(abs(px - stop) * contracts * product.contract_value, 4),
            "notional_usd": round(notional, 2), "margin_usd": round(notional / LEVERAGE, 2), "capped": by_cap < by_risk}

    if mode == "shadow":
        fee = _fee(notional, product.taker_rate)
        await _tc(db).insert_one({**base, "status": "open", "plan": plan, "contracts": contracts, "fill": px,
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
    await _tc(db).insert_one({**base, "status": "entering", "plan": plan, "contracts": contracts})
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
        t = await _tc(db).find_one({"_id": tid})
        ex = await _exit_from_fills(t, product, o2.get("avg_price") or None, o2.get("commission"))
        await _record_close(db, t, ex, f"bracket refused, closed at once: {exc}", product)
        return f"error: bracket refused ({exc}); closed at once"
    await _set_trade(db, tid, status="open", legs=_legs(legs), unrealised_usd=-float(o.get("commission") or 0.0))
    st["errors_in_row"] = 0
    await _set_state(db, errors_in_row=0)
    return f"live entry: {o['filled']} {pick.product} at {fill}"


# -- the cycle -----------------------------------------------------------------------------------------

_LOCKS: dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in DESKS}


async def _cycle_one() -> dict:
    """One pass of the current desk."""
    db = _db()
    if db is None:
        return {"error": "the paper desk's database is not configured on this server"}
    async with _LOCKS[_d().key]:
        st = await _state(db)
        await _set_state(db, last_cycle_at=_now())
        out: dict = {"mode": st["mode"], "managed": [], "entered": []}
        open_rows = [t async for t in _tc(db).find({"status": {"$in": ["entering", "open", "closing"]}})]
        if st["mode"] == "off" and not open_rows:
            return out
        try:
            products = await _products(db, st, {t["product"] for t in open_rows})
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
        decided = {t["_id"] async for t in _tc(db).find({"_id": {"$in": list(paper)}}, {"_id": 1})}
        still_open = [t async for t in _tc(db).find({"status": {"$in": ["entering", "open", "closing"]}},
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
            pk = _d().pick.get((p["acct"], p["mkt"]))
            if pk is None:                      # a trade from before a re-pick: managed above, never entered again
                continue
            res = await _enter(db, st, pk, p, products, positions if st["mode"] == "live" else None,
                               busy, day_pnl, desk_age)
            out["entered"].append({"id": tid, "result": res})
        return out


async def cycle(desk: str | None = None) -> dict:
    """One pass of one desk (its report), or of every desk when none is named ({desk: report})."""
    if desk is not None:
        with _use(desk):
            return await _cycle_one()
    out = {}
    for key in DESKS:
        try:
            with _use(key):
                out[key] = await _cycle_one()
        except Exception as exc:  # noqa: BLE001 - one desk's failure must not stop the other
            logger.warning("[premium live %s] cycle failed", key, exc_info=True)
            out[key] = {"error": f"cycle failed: {exc}"}
    return out


async def loop() -> None:
    """Every TICK_S seconds, around the clock, every desk in turn. Started by the premium routes' startup hook."""
    await asyncio.sleep(60)
    while True:
        try:
            r = await cycle()
            for key, rep_ in r.items():
                if rep_.get("entered") or rep_.get("error"):
                    logger.info("[premium live %s] %s", key, rep_)
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


async def _set_mode_one(mode: str, pin: str | None = None, confirm: str | None = None) -> dict:
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
    tracked = {t["product"] async for t in _tc(db).find({"mode": "live", "status": {"$in": ["entering", "open", "closing"]}},
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


async def _flatten_one(pin: str | None = None) -> dict:
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
    async for t in _tc(db).find({"status": {"$in": ["open", "entering"]}}):
        await _set_trade(db, t["_id"], status="closing", close_reason="flattened by the owner")
        n += 1
    r = await _cycle_one()
    return {"ok": True, "closing": n, "cycle": r}


async def set_mode(mode: str, pin: str | None = None, confirm: str | None = None, desk: str = "gold") -> dict:
    """Switch one desk (the gold desk unless named). Going live needs the PIN and the words REAL MONEY."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _set_mode_one(mode, pin, confirm)


async def flatten(pin: str | None = None, desk: str = "gold") -> dict:
    """Close every open real position one desk holds (the gold desk unless named), and switch it off."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _flatten_one(pin)


# -- the read model ------------------------------------------------------------------------------------


def _clean(t: dict) -> dict:
    t = dict(t)
    t["id"] = t.pop("_id")
    return t


async def _status_one() -> dict:
    db = _db()
    if db is None:
        return {"configured_db": False}
    st = await _state(db)
    rows = [t async for t in _tc(db).find({})]
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
    for p in _d().picks:
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
        "limits": {"risk_usd": _d().risk_usd, "daily_stop_usd": _d().daily_stop_usd, "max_notional_usd": MAX_NOTIONAL_USD,
                   "leverage": LEVERAGE, "max_lag_s": MAX_LAG_S, "drift_frac": DRIFT_FRAC, "tick_s": TICK_S},
        "today": today, "totals": totals, "picked_at": _d().picked_at, "picks": picks,
        "desk": _d().key, "title": _d().title, "desk_products": _d().products,
        "open": [_clean(t) for t in rows if t.get("status") in ("entering", "open", "closing")],
        "recent": [_clean(t) for t in rows[:150]], "notes": list(_d().notes),
    }


async def status(desk: str = "gold") -> dict:
    """What a desk's page reads (the gold desk unless named)."""
    if desk not in DESKS:
        return {"error": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _status_one()
