"""Real money on Delta Exchange India for Premium strategies: two desks on one engine (2026-11-13, split 2026-11-14).

DESKS. Each desk has its own picks, products, switch (off / shadow / live), daily loss stop, state and trade records;
they share the Delta account, its keys and the owner's PIN, and never trade the same product.
- gold (Premium Strategies > "Real money · Delta gold"): the five gold picks of 13 Nov and CP-06 (15 Nov), on XAUTUSD.
  Its records are the original ones (live_delta_state / live_delta_trades).
- crypto (the "Delta Exchange Live Trading" module, 14 Nov): the bitcoin strategies the owner picked from the Crypto
  tab - TH-05, TL-04 and TH-01 on 14 Nov, TD-02 on 15 Nov - on BTCUSD, a $20 daily stop (live_crypto_state /
  live_crypto_trades). From 15 Nov both desks trade one contract a trade (the owner can pick $1 to $5 of risk
  instead) and copy a signal seen up to 10 minutes late.
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
- A paper entry is copied only if it is seen within its desk's lag limit of its entry time (MAX_LAG_S; the bitcoin
  desk's CRYPTO_MAX_LAG_S), the market is still within DRIFT_FRAC of a risk distance of the paper entry, and the price
  is strictly between the paper's stop and target. The order is a market order of one contract, the smallest order
  Delta allows (the default from 15 Nov; skipped if that one contract would lose more than the desk's RISK_USD at the
  stop), or, when the owner picks a dollar risk on the page (RISK_MIN_USD up to RISK_USD), sized so the
  paper's stop loses at most that: contracts = risk / (|price - stop| x contract value), and never more than
  MAX_NOTIONAL_USD of notional; then a trade whose single contract would lose more than that risk is skipped.
- The paper's own stop and target go on the venue right after the fill as the trade's OWN two orders (from 15 Nov:
  standalone stop orders of the trade's size, not reduce-only, their ids on the trade). If either is refused, the
  trade is closed at once and the desk switches itself off: a real trade never stays unprotected.
- When the paper trade closes, for any reason, or disappears, its legs are cancelled first and then the trade is
  closed at the market by its own size. When a leg fills first, the other is cancelled and the close is recorded
  from that leg; legs that filled beyond the trade (both, in a very fast move) are offset at the market at once.
- Every strategy of a desk may hold a trade at the same time (the owner's choice, 15 Nov). Delta keeps one netted
  position per product, so every cycle the desk checks that the account's position equals the sum of the desks'
  trades: a mismatch makes new entries wait, and one seen on three checks switches the desk off, touching nothing.
  A trade from before (one bracket on the whole position) is managed the old way, and nothing new enters its product
  while it is open.
- The daily loss stop: once today's (IST) closed plus open P&L reaches -DAILY_STOP_USD, no new entry until tomorrow.
- Before going live, leverage is set to LEVERAGE on both products and read back. Delta's defaults, 200x on BTCUSD and
  100x on XAUTUSD, liquidate inside the strategies' stops.

MODES
- off: no new trade; open positions are still managed to their close.
- shadow: every decision is made and logged with simulated fills at the quote, and no order is sent.
- live: real orders.
Going live also needs the words REAL MONEY in the request (the page sends them). The owner's PIN is asked for going
live, flattening and changing the size only when PREMIUM_LIVE_REQUIRE_PIN=1; the owner chose no PIN on 15 Nov.
Three venue errors in a row switch the desk off (a good answer from Delta starts the count again).
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
from app.services.delta_rest import Delta, DeltaError, Product, fmt_tick

logger = logging.getLogger("premium_live")

IST = timezone(timedelta(hours=5, minutes=30))
RISK_USD = float(os.getenv("PREMIUM_LIVE_RISK_USD", "5"))              # the gold desk
DAILY_STOP_USD = float(os.getenv("PREMIUM_LIVE_DAILY_STOP_USD", "20"))
CRYPTO_RISK_USD = float(os.getenv("PREMIUM_CRYPTO_RISK_USD", "5"))       # the crypto desk (the owner's choice, 14 Nov)
CRYPTO_DAILY_STOP_USD = float(os.getenv("PREMIUM_CRYPTO_DAILY_STOP_USD", "20"))
MAX_NOTIONAL_USD = float(os.getenv("PREMIUM_LIVE_MAX_NOTIONAL_USD", "2500"))
LEVERAGE = int(os.getenv("PREMIUM_LIVE_LEVERAGE", "10"))
MAX_LAG_S = int(os.getenv("PREMIUM_LIVE_MAX_LAG_S", "300"))
CRYPTO_MAX_LAG_S = int(os.getenv("PREMIUM_CRYPTO_MAX_LAG_S", "600"))   # the bitcoin desk (the owner's choice, 15 Nov)
GOLD_MAX_LAG_S = int(os.getenv("PREMIUM_GOLD_MAX_LAG_S", "600"))       # the gold desk too, when it went live (15 Nov)
SIZING_DEFAULT = os.getenv("PREMIUM_LIVE_SIZING", "min")   # "min": one contract a trade, the owner's choice on 15 Nov
REQUIRE_PIN = os.getenv("PREMIUM_LIVE_REQUIRE_PIN", "0").strip() == "1"   # the owner chose no PIN on 15 Nov
RISK_MIN_USD = 1.0             # the lowest risk a trade the owner can pick on the page; the highest is the desk's own
PRIORITY_REFRESH_S = 600       # the books named to the paper desk (live_priority) are re-written at least this often
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
    picked_at: str | None = None    # its own pick time, when it joined the desk after the others (its record's time)


GOLD_PICKS: tuple[Pick, ...] = (
    Pick("RU-02", "XAUTUSD", "XAUTUSD", "Stochastic below 20, then a MACD cross, 1.5R (30-minute)", 5, 2.73, 1.47, 60,
         "loses: -0.06R a trade over 795 trades (t -1.6)"),
    Pick("CP-23", "XAUUSD", "XAUTUSD", "Inducement", 8, 5.29, 1.33, 62, "never backtested"),
    Pick("YT-14", "XAUUSD", "XAUTUSD", "MA fan + engulfing / three-line strike, RSI 50", 13, 5.19, 1.15, 62,
         "loses: -0.14R a trade over 2,317 trades"),
    Pick("DR-01", "XAUTUSD", "XAUTUSD", "EMA 200 side + counter-trend-line breakout, 1:2 (15-minute)", 15, 5.27, 0.88, 53,
         "loses: -0.26R a trade over 1,467 trades (t -7.3)"),
    Pick("CP-05", "XAUUSD", "XAUTUSD", "Turning-point zones (3 touches)", 8, 3.74, 0.86, 50, "never backtested"),
    # added by the owner on 15 Nov 2026 from the Gold tab's ranking; record = its gold paper trades at 13:40 IST
    Pick("CP-06", "XAUUSD", "XAUTUSD", "Triple top / triple bottom", 3, 1.44, 0.37, 67, "never backtested",
         "2026-11-15T13:40:00+05:30"),
    # added by the owner on 16 Nov 2026 from the Gold tab: TL-04's GOLD book (its bitcoin book stays on the crypto desk;
    # a pick is (account, market), so the two never meet). Record = its XAUTUSD paper trades at 23:33 IST.
    Pick("TL-04", "XAUTUSD", "XAUTUSD", "EMA 200 + RSI 50 + engulfing, stop two candles, 2R", 14, 3.13, 0.61, 43,
         "loses: -0.035R a trade over 1,304 trades (t -1.0)", "2026-11-16T23:33:00+05:30"),
)
# picked by the owner on 14 Nov 2026 from the Crypto tab; records = their bitcoin paper trades at 09:44 IST
CRYPTO_PICKS: tuple[Pick, ...] = (
    Pick("TH-05", "BTCUSD", "BTCUSD", "EMA 50/200 trend, pullback to EMA 50 with RSI 40-55", 9, 8.41, 1.00, 44,
         "never backtested"),
    Pick("TL-04", "BTCUSD", "BTCUSD", "EMA 200 + RSI 50 + engulfing, stop two candles, 2R", 15, 3.58, 0.67, 47,
         "loses: -0.31R a trade over 2,134 trades (t -11.1)"),
    Pick("TH-01", "BTCUSD", "BTCUSD", "Bitcoin 6 PM session: anchored VWAP + EMA 25, the N pattern", 9, 9.55, 0.49, 11,
         "never backtested"),
    # added by the owner on 15 Nov 2026 from the Crypto tab; record = its bitcoin paper trades at 13:40 IST
    Pick("TD-02", "BTCUSD", "BTCUSD", "9/15 EMA cross filtered by the SMI (7, 2, 2)", 7, 20.0, 0.94, 43,
         "loses: -0.37R a trade over 998 trades (t -3.5)", "2026-11-15T13:40:00+05:30"),
)
GOLD_NOTES = (
    "Real money on seven unproven gold strategies (CP-06 joined the five on 15 Nov, TL-04's gold book on 16 Nov), at "
    "the owner's chosen size: one contract a trade, the smallest order (or $1 to $5 of risk picked on this page), and a "
    "$20 daily loss stop.",
    "Four of the seven lose in their own 2-year backtests and three were never backtested; their good week is the only "
    "thing that picked them.",
    "This desk trades gold (XAUTUSD) only; the bitcoin desk is beside it on the Delta Exchange Live Trading page (since "
    "16 Nov both desks are there). Each has its own switch and its own $20 daily stop.",
    "Each real trade is the paper desk's trade: its entry signal, its stop, its target, its exit. The paper desk sees a "
    "new bar up to a few minutes late, so a fast strategy's copy is often skipped as late or drifted rather than chased.",
    "One gold contract is 0.001 XAUT (about $4 of gold), so a trade of one contract loses cents at its stop. A trade "
    "whose one contract would lose more than $5 is skipped (or more than the chosen risk, with a dollar risk).",
    "All seven can hold a trade at the same time (from 15 Nov): each trade is its own order with its own stop and "
    "target on Delta, and Delta shows their sum as one gold position.",
    "Each trade's stop and target live on Delta itself, so it stays protected if this server goes down.",
    "Leverage is set to 10x on XAUTUSD before going live; positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
)
CRYPTO_NOTES = (
    "Real money on four bitcoin strategies the owner picked from the Crypto tab (TH-05, TL-04, TH-01 on 14 Nov 2026, "
    "TD-02 on 15 Nov), at the owner's chosen size: one contract a trade, the smallest order (or $1 to $5 of risk "
    "picked on this page), and a $20 daily loss stop.",
    "None is proven: TL-04 and TD-02 lose in their own 2-year bitcoin backtests (-0.31R a trade over 2,134 trades and "
    "-0.37R over 998) and TH-05 and TH-01 were never backtested; 7 to 15 paper trades picked them.",
    "Each real trade is the paper desk's trade on Delta's live BTCUSD candles: its entry, stop, target and exit. A "
    "signal seen more than 10 minutes late, or already 30% of its risk away, is skipped, never chased. One bitcoin "
    "contract is 0.001 BTC; a trade whose one contract would lose more than $5 at its stop is skipped too (or more "
    "than the chosen risk, with a dollar risk).",
    "All four can hold a trade at the same time (from 15 Nov): each trade is its own order with its own stop and "
    "target on Delta, and Delta shows their sum as one bitcoin position.",
    "Each trade's stop and target live on Delta itself, so it stays protected if this server goes down.",
    "Leverage is set to 10x on BTCUSD before going live; positions are capped at $2,500 of notional.",
    "Fees and funding are Delta's own, read from its fills. Profit and loss are in US dollars.",
    "This desk and the gold desk (beside it on this page, and on Premium Strategies > Real money · Delta gold) share the "
    "Delta account and its keys; each has its own switch and its own $20 daily stop.",
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
    max_lag_s: int = MAX_LAG_S      # a paper entry seen later than this after its entry time is skipped

    @property
    def pick(self) -> dict:
        return {(p.acct, p.mkt): p for p in self.picks}

    @property
    def products(self) -> list[str]:
        return sorted({p.product for p in self.picks})


DESKS: dict[str, Desk] = {
    "gold": Desk("gold", "Real money · Delta gold", GOLD_PICKS, "live_delta_state", "live_delta_trades", RISK_USD,
                 DAILY_STOP_USD, PICKED_AT, GOLD_NOTES, GOLD_MAX_LAG_S),
    "crypto": Desk("crypto", "Delta Exchange Live Trading", CRYPTO_PICKS, "live_crypto_state", "live_crypto_trades",
                   CRYPTO_RISK_USD, CRYPTO_DAILY_STOP_USD, CRYPTO_PICKED_AT, CRYPTO_NOTES, CRYPTO_MAX_LAG_S),
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


def _sizing(st: dict) -> str:
    """"min" (one contract a trade, the smallest order: the default from 15 Nov) or "risk" (sized to the owner's dollar
    risk). A dollar risk chosen before the one-contract choice existed (risk_set_at, no sizing) counts as "risk"."""
    s = st.get("sizing")
    if s in ("min", "risk"):
        return s
    return "risk" if st.get("risk_set_at") else SIZING_DEFAULT


def _risk(st: dict) -> float:
    """The most a new trade of this desk may lose at its stop: the owner's choice on the page (RISK_MIN_USD up to the
    desk's own risk), or the desk's own risk until one is chosen."""
    try:
        r = float(st.get("risk_usd"))
    except (TypeError, ValueError):
        return _d().risk_usd
    return min(max(r, RISK_MIN_USD), _d().risk_usd) if math.isfinite(r) else _d().risk_usd


def _trade_risk(t: dict) -> float:
    """The risk a trade was sized for, for its R (records from before 15 Nov were all sized at the desk's own)."""
    try:
        r = float((t.get("plan") or {}).get("risk_set_usd") or 0)
    except (TypeError, ValueError):
        r = 0.0
    return r if r > 0 else _d().risk_usd


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


async def _venue_ok(db, st: dict) -> None:
    """Delta answered: the count of venue errors IN A ROW starts again. (Before 15 Nov only an entry or arming reset it,
    so scattered timeouts added up until a desk switched itself off.)"""
    if st.get("errors_in_row"):
        st["errors_in_row"] = 0
        await _set_state(db, errors_in_row=0)


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
         "$or": [{"acct": {"$in": sorted({p.acct for p in _d().picks})}, "entry_t": {"$gte": int(since) - _d().max_lag_s}},
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


async def _record_close(db, t: dict, ex: dict, reason: str, product: Product, extra_pnl: float = 0.0) -> None:
    """`extra_pnl`: what offsetting legs that filled beyond the trade's size made or cost; part of its result."""
    fees = float(t.get("entry_fee") or 0.0) + float(ex["fee"] or 0.0)
    pnl = round(_pnl(t["side"], float(t["fill"]), float(ex["price"]), int(t["contracts"]), product.contract_value, fees)
                + extra_pnl, 4)
    await _set_trade(db, t["_id"], status="closed", exit_price=round(float(ex["price"]), 6), exit_fee=round(float(ex["fee"]), 6),
                     exit_basis=ex["basis"], fees=round(fees, 6), pnl_usd=pnl, r=round(pnl / _trade_risk(t), 3),
                     close_reason=reason, closed_at=_now(), day_closed=_day(), unrealised_usd=0.0,
                     **({"extra_pnl": extra_pnl} if extra_pnl else {}))


async def _day_pnl(db, mode: str, positions: dict | None) -> float:
    """Today's (IST) closed P&L plus the open trades' marks, in USD, for one mode."""
    total = 0.0
    async for t in _tc(db).find({"mode": mode, "day_closed": _day(), "status": "closed"}, {"pnl_usd": 1}):
        total += float(t.get("pnl_usd") or 0.0)
    async for t in _tc(db).find({"mode": mode, "status": {"$in": ["open", "closing"]}}, {"unrealised_usd": 1}):
        total += float(t.get("unrealised_usd") or 0.0)
    return round(total, 4)


# -- managing what is open -------------------------------------------------------------------------------


async def _manage_bracket(db, st: dict, t: dict, paper: dict | None, positions: dict, products: dict, desk_age: float) -> None:
    """A trade from before 15 Nov: its one bracket covers the whole position, so the position is the trade."""
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


async def _manage_live(db, st: dict, t: dict, paper: dict | None, positions: dict, products: dict, desk_age: float,
                       resting: dict | None) -> None:
    """A live trade: with its own stop and target on Delta (from 15 Nov), or one from before whose bracket covers the
    whole position (managed the old way)."""
    if _own(t):
        if resting is None:                     # the resting orders could not be read this cycle: next cycle
            return
        await _manage_own(db, st, t, paper, positions, products[t["product"]], desk_age, resting.get(t["product"], {}))
    else:
        await _manage_bracket(db, st, t, paper, positions, products, desk_age)


# -- each trade's own legs (15 Nov 2026) ---------------------------------------------------------------------------
# Every strategy of a desk may hold a trade at the same time (the owner's choice, 15 Nov). Delta keeps one netted
# position per product and one bracket per position, so each trade carries its own stop and target: standalone stop
# orders of its own size, not reduce-only (one trade's leg may have to open or flip the net position), their ids on
# the trade. A leg that fills ends the trade and the other leg is cancelled. When the desk closes a trade it cancels
# both legs FIRST and then closes at the market only what is still held, so its own order and a leg never both close
# the same contracts. Legs that filled beyond the trade's size (both, in a very fast move) are offset at once. Every
# cycle the account's position is checked against the sum of the desks' trades (_check_books).


def _own(t: dict) -> bool:
    return t.get("protect") == "own"


async def _leg_order(product: Product, side: str, size: int, kind: str, trigger: float, limit: float, cid: str) -> dict:
    """Place one leg; an answer that was lost is looked up by its client id (it may exist without our knowing)."""
    try:
        return await D.stop_order(product, side, size, kind, trigger, limit, client_order_id=cid)
    except DeltaError as exc:
        if not exc.ambiguous:
            raise
        try:
            o = await D.order_by_client_id(cid)
        except DeltaError:
            raise exc from None
        if not o.get("id") or o.get("state") == "cancelled":
            raise
        return {**o, "stop_price_sent": fmt_tick(trigger, product.tick), "limit_price_sent": fmt_tick(limit, product.tick)}


async def _place_legs(db, tid: str, product: Product, side: int, contracts: int, fill: float, stop: float,
                      target: float | None) -> dict:
    """The trade's own stop (and target) on Delta, each saved on the trade as soon as it is placed. Raises DeltaError;
    the caller then closes the trade (a leg already placed is on the trade, so it is cancelled with it)."""
    long_ = side > 0
    if (long_ and stop >= fill) or (not long_ and stop <= fill):
        raise DeltaError(f"legs: the stop {stop} is on the wrong side of the fill {fill}")
    if target is not None and ((long_ and target <= fill) or (not long_ and target >= fill)):
        raise DeltaError(f"legs: the target {target} is on the wrong side of the fill {fill}")
    if abs(fill - stop) < 2 * product.tick:
        raise DeltaError("legs: the stop is under two ticks from the fill")
    out = "sell" if long_ else "buy"
    slip = max(abs(fill - stop) * 0.20, 2 * product.tick)     # the stop's limit sits past its trigger (see delta_rest)
    s = await _leg_order(product, out, contracts, "stop_loss_order", stop, stop - slip if long_ else stop + slip,
                         _cid(tid, "s"))
    legs = {"stop": s["stop_price_sent"], "stop_limit": s["limit_price_sent"], "stop_id": s["id"], "target": None,
            "target_id": None}
    await _set_trade(db, tid, legs=legs)
    if target is not None:
        tp = await _leg_order(product, out, contracts, "take_profit_order", target, target, _cid(tid, "t"))
        legs.update(target=tp["stop_price_sent"], target_id=tp["id"])
        await _set_trade(db, tid, legs=legs)
    return legs


def _leg_kind(o: dict) -> str:
    """"filled" (wholly or partly) | "cancelled" | "resting" | "unknown", from an order read back."""
    s = o.get("state") or ""
    if o.get("filled") or s == "closed":
        return "filled"
    if s == "cancelled":
        return "cancelled"
    if s in ("open", "pending"):
        return "resting"
    return "unknown"


async def _leg(product: Product, oid: str | None, resting: dict) -> tuple[str, dict]:
    """A leg's state: from the cycle's list of resting orders, else read back by its id."""
    if not oid:
        return "none", {}
    if oid in resting:
        o = resting[oid]
        return ("filled" if o.get("filled") else "resting"), o
    try:
        o = await D.order(oid)
    except DeltaError:
        return "unknown", {}
    return _leg_kind(o), o


async def _cancel_leg(product: Product, oid: str) -> tuple[str, dict]:
    """Cancel one leg and say how it ended. Delta refuses to cancel an order that already filled or is gone
    ("open_order_not_found"), so a refusal is answered by reading the order back."""
    try:
        o = await D.cancel_order(product.id, oid)
    except DeltaError:
        try:
            o = await D.order(oid)
        except DeltaError:
            return "unknown", {}
    k = _leg_kind(o)
    if k == "filled" and o.get("state") in ("open", "pending"):
        return "unknown", o                  # partly filled and still resting: not settled yet
    return k, o


async def _market_once(db, st: dict, t: dict, product: Product, size: int, side: str, tag: str) -> dict | None:
    """A market order a trade sends to close ("x") or to offset legs that filled beyond it ("f"), sent once: the
    result is kept on the trade, and an answer that was lost is looked up by its client id before anything is sent
    again. None when it did not go through this cycle."""
    cid = _cid(t["_id"], tag)
    prev = (t.get("orders") or {}).get(tag) or {}
    if prev.get("filled"):
        return prev
    if prev.get("ambiguous"):
        try:
            o = await D.order_by_client_id(cid)
            if o.get("filled"):
                await _set_trade(db, t["_id"], **{f"orders.{tag}": o})
                return o
        except DeltaError:
            pass                                    # not found: it never went through
    try:
        o = await D.market(product.id, size, side, client_order_id=cid)
    except DeltaError as exc:
        await _set_trade(db, t["_id"], **{f"orders.{tag}": {"ambiguous": exc.ambiguous, "error": str(exc)[:200]}})
        await _venue_error(db, st, f"{t['acct']}: market order refused ({exc})")
        return None
    await _set_trade(db, t["_id"], **{f"orders.{tag}": o})
    if not o.get("filled"):
        await _venue_error(db, st, f"{t['acct']}: the market order did not fill")
        return None
    return o


async def _close_own(db, st: dict, t: dict, product: Product, reason: str, resting: dict) -> bool:
    """Close a trade that has its own legs: cancel both legs first, close at the market only what is still held, and
    offset at once anything its legs filled beyond its size. True when the trade is closed; False leaves it closing,
    tried again next cycle (nothing more is sent while a leg cannot be settled)."""
    n = int(t.get("contracts") or 0)
    legs = t.get("legs") or {}
    out = "sell" if t["side"] > 0 else "buy"
    if t.get("status") != "closing" or t.get("close_reason") != reason:
        await _set_trade(db, t["_id"], status="closing", close_reason=reason)
    got: list[dict] = []
    for k in ("stop", "target"):
        oid = legs.get(f"{k}_id")
        if not oid:
            continue
        kind, o = await _leg(product, oid, resting)
        if kind in ("resting", "unknown") or (kind == "filled" and o.get("state") in ("open", "pending")):
            kind, o = await _cancel_leg(product, oid)
        if kind in ("resting", "unknown"):
            await _venue_error(db, st, f"{t['acct']}: its {k} on Delta could not be cancelled or read")
            return False
        if kind == "filled":
            got.append(o)
    qty = sum(int(o["filled"]) for o in got)
    value = sum(float(o.get("avg_price") or 0.0) * int(o["filled"]) for o in got)
    fee = sum(float(o.get("commission") or 0.0) for o in got)
    if qty < n:
        o = await _market_once(db, st, t, product, n - qty, out, "x")
        if o is None:
            return False
        qty += int(o["filled"])
        value += float(o.get("avg_price") or 0.0) * int(o["filled"])
        fee += float(o.get("commission") or 0.0)
    extra, extra_pnl = qty - n, 0.0
    if extra > 0:
        # its legs filled more than it held (both, in a very fast move): the overshoot is taken back at once
        o = await _market_once(db, st, t, product, extra, _side(t["side"]), "f")
        if o is None:
            return False
        avg = value / qty
        extra_pnl = round(-t["side"] * (float(o.get("avg_price") or avg) - avg) * extra * product.contract_value
                          - float(o.get("commission") or 0.0), 6)
    price = value / qty if qty else float(t.get("fill") or 0.0)
    await _record_close(db, t, {"price": price, "fee": fee, "basis": "fills"}, reason, product, extra_pnl)
    return True


async def _replace_leg(db, t: dict, product: Product, k: str) -> None:
    """Put back, once, a leg that was cancelled on Delta by someone other than this desk."""
    legs = dict(t.get("legs") or {})
    n, out = int(t["contracts"]), ("sell" if t["side"] > 0 else "buy")
    if k == "stop":
        stop = float(t["stop"])
        slip = max(abs(float(t["fill"]) - stop) * 0.20, 2 * product.tick)
        o = await _leg_order(product, out, n, "stop_loss_order", stop, stop - slip if t["side"] > 0 else stop + slip,
                             _cid(t["_id"], "s2"))
        legs.update(stop_id=o["id"], stop_replaced=True)
    else:
        target = float(t["target"])
        o = await _leg_order(product, out, n, "take_profit_order", target, target, _cid(t["_id"], "t2"))
        legs.update(target_id=o["id"], target_replaced=True)
    await _set_trade(db, t["_id"], legs=legs)


async def _settle_entry(db, st: dict, t: dict, product: Product) -> None:
    """An entry whose answer was lost (or whose record stopped half-way): Delta is asked for it by its client id."""
    if _now() - float(t.get("created_at") or 0) < 60:
        return
    try:
        o = await D.order_by_client_id(_cid(t["_id"]))
    except DeltaError:
        o = None
    if o and o.get("filled"):
        fill = float(o.get("avg_price") or (t.get("plan") or {}).get("price") or 0.0)
        n = int(o["filled"])
        await _set_trade(db, t["_id"], status="open", contracts=n, fill=fill, entry_fee=float(o.get("commission") or 0.0),
                         entry_order=o, opened_at=_now(), recovered=True)
        try:
            await _place_legs(db, t["_id"], product, t["side"], n, fill, float(t["stop"]),
                              float(t["target"]) if t.get("target") else None)
        except DeltaError as exc:
            t = await _tc(db).find_one({"_id": t["_id"]})
            await _switch_off(db, st, f"{t['acct']}: its stop or target was refused on recovery ({exc})")
            await _close_own(db, st, t, product, f"stop or target refused on recovery: {exc}", {})
        return
    if (o is not None and not o.get("filled")) or _now() - float(t.get("created_at") or 0) > 300:
        await _set_trade(db, t["_id"], status="skipped", reason="entry not confirmed by Delta")


async def _manage_own(db, st: dict, t: dict, paper: dict | None, positions: dict, product: Product, desk_age: float,
                      resting: dict) -> None:
    """One trade with its own stop and target on Delta."""
    if t["status"] == "entering":
        await _settle_entry(db, st, t, product)
        return
    if t["status"] == "closing":
        await _close_own(db, st, t, product, t.get("close_reason") or "closing", resting)
        return
    legs = t.get("legs") or {}
    state = {k: await _leg(product, legs[f"{k}_id"], resting) for k in ("stop", "target") if legs.get(f"{k}_id")}
    hit = [k for k, (kind, _o) in state.items() if kind == "filled"]
    if hit:
        why = "venue stop and target" if len(hit) > 1 else f"venue {hit[0]}"
        await _close_own(db, st, t, product, why, resting)
        return
    lost = [k for k, (kind, _o) in state.items() if kind == "cancelled"]
    if lost:
        k = lost[0]
        if legs.get(f"{k}_replaced"):
            await _close_own(db, st, t, product, f"its {k} was cancelled on Delta again", resting)
            return
        try:
            await _replace_leg(db, t, product, k)
        except DeltaError as exc:
            await _close_own(db, st, t, product, f"its {k} was cancelled on Delta and could not be put back ({exc})",
                             resting)
        return
    reason = None
    if paper is None:
        gone = float(t.get("paper_missing_since") or 0)
        if not gone:
            await _set_trade(db, t["_id"], paper_missing_since=_now())
        elif _now() - gone > MISSING_GRACE_S:
            reason = "the paper trade disappeared"
    elif not paper.get("open"):
        reason = f"paper exit: {paper.get('reason') or 'closed'}"
    elif desk_age > DESK_DEAD_S:
        reason = "the paper desk stopped updating"
    if reason is not None:
        await _close_own(db, st, t, product, reason, resting)
        return
    mark = float((positions.get(product.id) or {}).get("mark") or 0.0)
    if not mark:                                   # the net position can be flat while trades are open
        try:
            mark = float((await D.ticker(product.symbol))["mark"])
        except DeltaError:
            mark = 0.0
    n = int(t.get("contracts") or 0)
    u = _pnl(t["side"], float(t["fill"]), mark, n, product.contract_value, float(t.get("entry_fee") or 0.0)) if mark else 0.0
    fields = {"mark": mark, "unrealised_usd": u, "contracts_open": n}
    if paper is not None:
        fields["paper_missing_since"] = None
    await _set_trade(db, t["_id"], **fields)


async def _expected_net(db) -> dict[str, int]:
    """Contracts the desks' live trades hold, signed, by product symbol, across every desk: what the account's netted
    positions should be. Entries still in flight are not counted."""
    out: dict[str, int] = {}
    for d in DESKS.values():
        async for t in getattr(db, d.trades_coll).find({"mode": "live", "status": {"$in": ["open", "closing"]}},
                                                       {"product": 1, "side": 1, "contracts": 1}):
            out[t["product"]] = out.get(t["product"], 0) + int(t["side"]) * int(t.get("contracts") or 0)
    return out


async def _legacy_products(db) -> set[str]:
    """Products where a trade from before 15 Nov is open (its one bracket covers the whole position): no new entry
    there until it closes."""
    out = set()
    for d in DESKS.values():
        async for t in getattr(db, d.trades_coll).find({"mode": "live", "status": {"$in": ["entering", "open", "closing"]}},
                                                       {"product": 1, "protect": 1}):
            if t.get("protect") != "own":
                out.add(t["product"])
    return out


async def _check_books(db, st: dict, products: dict, positions: dict) -> dict[str, bool]:
    """Does the account's position on each of this desk's products equal the sum of the desks' trades on it? A
    mismatch can be Delta's lag (its positions can take up to 10 s) or a trade in flight, so new entries just wait;
    seen on three checks in a row (about a minute), the desk switches off and touches nothing: someone looks at Delta."""
    want = await _expected_net(db)
    out, bad = {}, []
    for sym in _d().products:
        p = products.get(sym)
        if p is None:
            continue
        have = int((positions.get(p.id) or {}).get("size") or 0)
        out[sym] = have == want.get(sym, 0)
        if not out[sym]:
            bad.append(f"{sym}: the account holds {have:+d} contracts, the trades {want.get(sym, 0):+d}")
    n = int(st.get("mismatch_checks") or 0) + 1 if bad else 0
    if n != int(st.get("mismatch_checks") or 0):
        st["mismatch_checks"] = n
        await _set_state(db, mismatch_checks=n, mismatch="; ".join(bad) or None)
    if bad and n >= ERRORS_TO_STOP and st.get("mode") == "live":
        await _switch_off(db, st, f"the account's position has not matched this desk's trades for {n} checks "
                                  f"({'; '.join(bad)}): nothing was touched - check Delta")
    return out


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


async def _enter(db, st: dict, pick: Pick, paper: dict, products: dict, busy: set, day_pnl: float,
                 desk_age: float) -> str:
    """Decide one new paper trade, once. Returns what happened, for the cycle's report."""
    tid, mode = paper["_id"], st["mode"]
    side = 1 if int(paper.get("side") or 0) > 0 else -1
    stop = float(paper.get("stop") or 0.0)
    target = float(paper["target"]) if paper.get("target") else None
    entry = float(paper.get("entry") or 0.0)
    base = {"_id": tid, "acct": pick.acct, "mkt": pick.mkt, "product": pick.product, "name": pick.name, "mode": mode,
            "side": side, "paper_entry": entry, "paper_entry_t": paper.get("entry_t"), "stop": stop, "target": target,
            "setup": paper.get("setup"), "day": _day(), "created_at": _now(), "protect": "own"}

    async def skip(why: str, **extra) -> str:
        try:
            await _tc(db).insert_one({**base, **extra, "status": "skipped", "reason": why})
        except Exception:  # noqa: BLE001 - decided by an earlier pass
            pass
        return f"skipped: {why}"

    lag = _now() - float(paper.get("entry_t") or 0)
    if not paper.get("open"):
        return await skip("closed on paper before it could be copied")
    if lag > _d().max_lag_s:
        return await skip(f"seen {lag / 60:.0f} min after its entry (limit {_d().max_lag_s // 60})", lag_s=round(lag))
    if stop <= 0 or entry <= 0:
        return await skip("no stop on the paper trade")
    if day_pnl <= -_d().daily_stop_usd:
        return await skip(f"daily loss stop reached ({day_pnl:+.2f} USD today)")
    if desk_age > DESK_STALE_S:
        return await skip("the paper desk has not updated for over 20 minutes")
    product = products[pick.product]
    if mode == "live" and pick.product in busy:
        return await skip(f"{pick.product} holds an older trade whose one bracket covers the whole position")
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
    sizing = _sizing(st)
    one = abs(px - stop) * product.contract_value           # what a single contract loses at the stop
    if sizing == "min":                                     # the smallest order; the desk's own risk still caps it
        if one > _d().risk_usd:
            return await skip(f"one contract would lose ${one:.2f} at its stop, more than the ${_d().risk_usd:.2f} cap a "
                              "trade", price=px)
        risk, by_risk = one, 1
    else:
        risk = _risk(st)
        by_risk = math.floor(risk / one)
    by_cap = math.floor(MAX_NOTIONAL_USD / (px * product.contract_value))
    contracts = min(by_risk, by_cap)
    if contracts < 1:
        why = (f"one contract would lose ${one:.2f} at its stop, more than the ${risk:.2f} a trade you set" if by_risk < 1
               else "under one contract within the notional cap")
        return await skip(why, price=px)
    notional = contracts * product.contract_value * px
    plan = {"price": px, "contracts": contracts, "risk_usd": round(one * contracts, 6), "risk_set_usd": round(risk, 6),
            "sizing": sizing, "notional_usd": round(notional, 2), "margin_usd": round(notional / LEVERAGE, 2),
            "capped": by_cap < by_risk}

    if mode == "shadow":
        fee = _fee(notional, product.taker_rate)
        await _tc(db).insert_one({**base, "status": "open", "plan": plan, "contracts": contracts, "fill": px,
                                               "entry_fee": round(fee, 6), "opened_at": _now(), "unrealised_usd": -fee})
        return f"shadow entry: {contracts} {pick.product} at {px}"

    try:
        w = await D.wallet()
    except DeltaError as exc:
        await _venue_error(db, st, f"wallet read failed ({exc})")
        return await skip("could not read the wallet")
    if w["available"] < plan["margin_usd"] * MARGIN_BUFFER:
        return await skip(f"not enough free balance (${w['available']:.2f} for ${plan['margin_usd']:.2f} of margin)")
    await _tc(db).insert_one({**base, "status": "entering", "plan": plan, "contracts": contracts})
    try:
        o = await D.market(product.id, contracts, _side(side), client_order_id=_cid(tid))
    except DeltaError as exc:
        if exc.ambiguous:
            # the order may have filled: it stays "entering", and the next cycles ask Delta for it by its client id
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
        await _place_legs(db, tid, product, side, int(o["filled"]), fill, stop, target)
    except DeltaError as exc:
        # never left unprotected: out at once, and the desk stops until someone looks
        await _switch_off(db, st, f"{pick.acct} {pick.product}: its stop or target was refused ({exc}); the trade was closed")
        t = await _tc(db).find_one({"_id": tid})
        done = await _close_own(db, st, t, product, f"stop or target refused, closed at once: {exc}", {})
        return f"error: stop or target refused ({exc}); " + ("closed at once" if done else "the close is retried every cycle")
    await _set_trade(db, tid, status="open", unrealised_usd=-float(o.get("commission") or 0.0))
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
        resting: dict | None = {}
        if st["mode"] == "live" or live_rows:
            try:
                positions = await D.positions()
            except DeltaError as exc:
                await _venue_error(db, st, f"positions unavailable ({exc})")
                positions = None
            else:
                await _venue_ok(db, st)                     # errors count only in a row
            if positions is not None and _now() - float(st.get("wallet_at") or 0) > 300:
                try:
                    await _set_state(db, wallet=await D.wallet(), wallet_at=_now())
                except DeltaError:
                    pass
            try:                                            # the resting legs of the trades that carry their own
                for sym in sorted({t["product"] for t in live_rows if _own(t)}):
                    resting[sym] = await D.open_orders(products[sym].id)
            except DeltaError as exc:
                await _venue_error(db, st, f"resting orders unavailable ({exc})")
                resting = None
        for t in open_rows:
            if t.get("mode") == "live":
                if positions is not None:
                    await _manage_live(db, st, t, paper.get(t["_id"]), positions, products, desk_age, resting)
            else:
                await _manage_shadow(db, t, paper.get(t["_id"]), desk_age, products)
            out["managed"].append(t["_id"])
        if st["mode"] == "off" or (st["mode"] == "live" and positions is None):
            return out
        decided = {t["_id"] async for t in _tc(db).find({"_id": {"$in": list(paper)}}, {"_id": 1})}
        books: dict[str, bool] = {}
        busy: set = set()
        if st["mode"] == "live":
            try:
                positions = await D.positions()
            except DeltaError as exc:
                await _venue_error(db, st, f"positions unavailable ({exc})")
                return out
            books = await _check_books(db, st, products, positions)
            if st["mode"] != "live":                        # the books check switched the desk off
                return out
            busy = await _legacy_products(db)
        day_pnl = await _day_pnl(db, st["mode"], positions)
        for tid, p in sorted(paper.items(), key=lambda kv: kv[1].get("entry_t") or 0):
            if tid in decided or float(p.get("entry_t") or 0) < float(st.get("since") or 0):
                continue
            if st["mode"] not in ("shadow", "live"):
                break
            pk = _d().pick.get((p["acct"], p["mkt"]))
            if pk is None:                      # a trade from before a re-pick: managed above, never entered again
                continue
            if st["mode"] == "live" and not books.get(pk.product, False):
                continue                        # the account does not match the trades yet: wait, undecided
            res = await _enter(db, st, pk, p, products, busy, day_pnl, desk_age)
            out["entered"].append({"id": tid, "result": res})
        return out


_PRIORITY_SENT: tuple[list[str], float] | None = None


async def _publish_priority() -> None:
    """Name the books these desks copy to the paper desk (premium_meta 'live_priority', "ACCT|MARKET"). Its bitcoin pass
    runs them first, right after it reads new candles, so their trades reach these desks minutes sooner. Written after
    a restart, when the picks change and every PRIORITY_REFRESH_S; a failure is only logged (only speed depends on it)."""
    global _PRIORITY_SENT
    books = sorted({f"{p.acct}|{p.mkt}" for d in DESKS.values() for p in d.picks})
    if _PRIORITY_SENT and _PRIORITY_SENT[0] == books and _now() - _PRIORITY_SENT[1] < PRIORITY_REFRESH_S:
        return
    db = _db()
    if db is None:
        return
    try:
        await db.premium_meta.update_one({"_id": "live_priority"}, {"$set": {"books": books, "at": _now(),
                                                                             "by": "premium_live"}}, upsert=True)
        _PRIORITY_SENT = (books, _now())
    except Exception:  # noqa: BLE001
        logger.warning("[premium live] could not name the priority books to the paper desk", exc_info=True)


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
    await _publish_priority()
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
    """None if the PIN is right; otherwise why not (wrong PINs are counted and lock it for the hour). None at once when
    no PIN is required (REQUIRE_PIN off: the owner's choice on 15 Nov)."""
    if not REQUIRE_PIN:
        return None
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
    want = await _expected_net(db)
    foreign = [sym for sym, p in products.items() if int((positions.get(p.id) or {}).get("size") or 0) != want.get(sym, 0)]
    if foreign:
        return {"ok": False, "why": f"the account already holds {', '.join(foreign)} that the desks' trades do not "
                                    "account for: close it on Delta first"}
    cached = st.get("products") or {}
    for sym in lev:
        cached.setdefault(sym, {})["leverage"] = lev[sym]
    await _set_state(db, mode="live", since=_now(), armed_at=_now(), errors_in_row=0, switched_off=None,
                     mismatch_checks=0, mismatch=None, products=cached, wallet=w, wallet_at=_now())
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


async def _set_risk_one(risk_usd, pin: str | None = None) -> dict:
    db = _db()
    if db is None:
        return {"ok": False, "why": "the paper desk's database is not configured on this server"}
    if isinstance(risk_usd, str) and risk_usd.strip().lower() in ("min", "1 contract", "one contract"):
        r = None                                            # one contract a trade, the smallest order
    else:
        try:
            r = round(float(risk_usd), 2)
        except (TypeError, ValueError):
            return {"ok": False, "why": "the size must be one contract (min) or a number of US dollars"}
        if not (math.isfinite(r) and RISK_MIN_USD <= r <= _d().risk_usd):
            return {"ok": False, "why": f"the risk a trade must be from ${RISK_MIN_USD:.0f} to ${_d().risk_usd:.0f}"}
    st = await _state(db)
    why = await _check_pin(db, st, pin)
    if why:
        return {"ok": False, "why": why}
    if r is None:
        await _set_state(db, sizing="min", risk_set_at=_now())
        return {"ok": True, "sizing": "min"}
    await _set_state(db, sizing="risk", risk_usd=r, risk_set_at=_now())
    return {"ok": True, "sizing": "risk", "risk_usd": r}


async def set_risk(risk_usd, pin: str | None = None, desk: str = "gold") -> dict:
    """A desk's trade size, picked by the owner on the page: "min" (one contract a trade, the smallest order) or the most
    one trade may lose at its stop, RISK_MIN_USD up to the desk's own risk. Needs the PIN; a trade already open keeps
    the size it was given."""
    if desk not in DESKS:
        return {"ok": False, "why": f"unknown desk {desk!r}"}
    with _use(desk):
        return await _set_risk_one(risk_usd, pin)


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
        "configured_db": True, "keys": DR.configured(), "pin_set": _pin_ok(None) is not None, "pin_required": REQUIRE_PIN,
        "mode": st.get("mode"), "since": st.get("since"), "armed_at": st.get("armed_at"),
        "switched_off": st.get("switched_off"), "last_error": st.get("last_error"), "last_error_at": st.get("last_error_at"),
        "errors_in_row": st.get("errors_in_row"), "last_cycle_at": st.get("last_cycle_at"), "wallet": st.get("wallet"),
        "wallet_at": st.get("wallet_at"), "products": st.get("products"),
        "limits": {"risk_usd": _risk(st), "risk_cap_usd": _d().risk_usd, "risk_min_usd": RISK_MIN_USD,
                   "risk_set_at": st.get("risk_set_at"), "sizing": _sizing(st), "daily_stop_usd": _d().daily_stop_usd,
                   "max_notional_usd": MAX_NOTIONAL_USD, "leverage": LEVERAGE, "max_lag_s": _d().max_lag_s,
                   "drift_frac": DRIFT_FRAC, "tick_s": TICK_S},
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
