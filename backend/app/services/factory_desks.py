"""Strategy Factory tabs on six modules (2026-10-27).

The owner asked for the Strategy Factory's strategies to be added to Index Option Buying, Index Option
Selling, Stock Pre-Live Buying and Selling, Momentum Trading and Gold Desk, beside their own
strategies. Owner's choices: ALL 546 (over the recommended graded-3+ subset), and a NEW TAB per module
(each module's own catalog, engine and records stay untouched - the Factory's own rule, see its
sources.py: a library injected into every desk would change their capital and signal contracts).

ONE DECISION, SIX INSTRUMENTS. Every tab runs the Factory's own `signals.evaluate` - the code its
backtests and its paper desk run - on that module's UNDERLYING, on closed bars of each strategy's own
timeframe, and expresses the signal in that module's INSTRUMENT at that module's usual account size:

  index-buying   NIFTY bars       BUY -> buy the ATM CE, SELL -> the ATM PE; nearest listed weekly (4h/1d: the
                                  nearest with more than 2 sessions left); 1 lot; Rs 10 lakh each
  index-selling  NIFTY bars       BUY -> sell an ATM put spread, SELL -> an ATM call spread (200-point wing),
                                  the same expiry rule; 1 lot; Rs 10 lakh each
  stock-buying   the stock desk's 12 stocks  ATM option bought on an expiry > 7 sessions away; 1 lot; Rs 10 lakh each
  stock-selling  the same stocks  ATM credit spread, the next listed strike as the wing; 1 lot; Rs 10 lakh each
  momentum       the Factory's NSE equities  LONG signals only, cash equity; Rs 10,000 each; the desk's regime gate
  gold           Delta XAUTUSD bars          both sides on the perpetual; a $1,111 sleeve each at 1x (H1's sleeve)

THE STRATEGY KEEPS ITS OWN EXITS: its stop and target are levels on the UNDERLYING, from its own
logic, and its hold limit is counted in bars of its own timeframe (the Factory's DEFAULT_MAX_HOLD).
Each closed bar after entry is checked; a bar touching both counts as the stop, as in its backtest.
The module's rules apply on top: NSE tabs take entries 09:20-15:00 IST on NSE trading days
(market_calendar); options of intraday timeframes (and intraday momentum) are squared off at 15:15;
an index option is out by 15:15 on its expiry day, a stock option two sessions before; one position
per strategy per tab, sized by its own account's free cash. The parent module's Main Control switch
OFF stops new entries here; open positions are still managed. A signal is taken only off a bar that
has just closed (an NSE intraday bar of today's session), never off a series that has fallen behind.

FILLS AND COSTS. Options are bought at the ask and sold at the bid from Angel's FULL quote - no fresh
two-sided quote, no entry; an exit with no bid uses the LTP and says so. A spread sells its short leg
at the bid and buys its wing at the ask, reversed on exit; its margin is its maximum loss. Option legs
pay Angel's option rate card; an option nobody quotes after expiry settles at intrinsic on the
underlying's last close on or before expiry day. Momentum enters at Angel's live LTP + 5 bp and gold
at Delta's touch; a stop or target exits at the strategy's own level (a bar that opens through the
stop fills at that open), a time exit at the live LTP / touch. Costs: equity 5 bp a side and the NSE
card; Delta the venue's taker fee + 18% GST both legs, and funding at every exchange held through.

DATA, STATED. The Factory's equity store holds deep DAILY bars and intraday bars for only a handful of
names, so on the stock and momentum tabs most intraday strategies have no bars and do not run; that
is counted per timeframe and shown, never filled with a truncated series. NIFTY has every timeframe.
The gold scheduler keeps only the timeframes H1 uses fresh, so this module re-reads the shared XAUTUSD
store's other intervals itself; Delta's daily history (from April 2026) is still shorter than the 215
bars the 1d strategies need. Gold's H1 forward test is untouched: these are records beside it.

LOAD. 546 strategies x up to 118 symbols x 8 timeframes is read sparingly: a series is read again only
once its next bar can have closed, and then only if a one-document probe shows a newer stored bar;
managing and scanning share one pass's reads; the per-desk sums are aggregated in the database.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from anyio import to_thread
from pymongo import UpdateOne

from app.core.db import db
from app.services.book_reset import naive_utc
from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD
from app.services.strategy_factory.catalog import FACTORY_CATALOG
from app.services.strategy_factory.signals import evaluate

logger = logging.getLogger("factory_desks")

IST = timezone(timedelta(hours=5, minutes=30))
# The tabs' own records live in a second MongoDB when FACTORY_MONGO_URL is set (production: the box's
# compose `mongodb` service), not on the Atlas cluster that holds everything else - 546 strategies on
# six tabs write thousands of rows a week and Atlas is near its storage quota. Unset (local runs,
# tests): the main database. Bars, instruments and quotes are always read from the main one.
FACTORY_MONGO_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
FACTORY_MONGO_DB = os.getenv("FACTORY_MONGO_DB", "alpha_engine_factory")


def _open_store():
    if not FACTORY_MONGO_URL:
        return db
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(FACTORY_MONGO_URL, serverSelectionTimeoutMS=5000, maxPoolSize=10)[FACTORY_MONGO_DB]


STORE = _open_store()
POSITIONS = STORE["factory_desk_positions"]
STATE = STORE["factory_desk_state"]
EQUITY = STORE["factory_desk_equity"]
ENABLED = os.getenv("FACTORY_DESKS_ENABLED", "1").lower() not in ("0", "false", "")
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "4h": 240, "1d": 1440}
INTRADAY_TFS = {"1m", "5m", "15m", "30m", "45m", "1h"}
BARS_LIMIT = 600
INDEX_WING_POINTS = float(os.getenv("FACTORY_INDEX_WING_POINTS", "200"))
INDEX_SWING_MIN_SESSIONS = 2    # a 4h/1d strategy's NIFTY option needs MORE sessions than this left
STOCK_MIN_SESSIONS = 7          # a stock option opens only with MORE sessions than this left
STOCK_EXIT_SESSIONS = 2         # and is closed once this few remain
EQUITY_SLIPPAGE_BP = 5.0        # the momentum desk's slippage, a side
GOLD_SLEEVE_USD = 10_000 / 9    # H1's sleeve
DELTA_GST = float(os.getenv("GOLD_DELTA_GST_PCT", "0.18"))
MAX_QUOTE_SPREAD = 0.10         # a two-sided quote wider than this is not a price to trade at
QUOTE_STALE_MIN = 10            # no trade for longer than this and the quote is stale
QUOTE_PACE_SECONDS = 0.15       # between FULL-quote requests, as stock_options and the paper broker pace
SNAPSHOT_EVERY_MIN = 15         # one equity point per tab at most this often
UNIVERSE_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class Tab:
    key: str
    module: str
    route: str
    label: str
    kind: str                      # option_buy | credit_spread | equity_long | perp
    market: str                    # nifty | stocks | equities | xaut
    capital: float                 # per strategy
    currency: str                  # INR | USD
    instrument: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    switch: str = ""               # the parent module's Main Control key: OFF stops new entries here

    @property
    def nse(self) -> bool:
        return self.market != "xaut"


TABS: dict[str, Tab] = {
    "index-buying": Tab(
        "index-buying", "Index Option Buying", "/prelive", "Strategy Factory · 546",
        "option_buy", "nifty", 1_000_000.0, "INR",
        "NIFTY options bought: the ATM CE on a BUY signal, the ATM PE on a SELL, the nearest listed weekly "
        f"(4h/1d strategies: the nearest with more than {INDEX_SWING_MIN_SESSIONS} sessions left), 1 lot",
        ("The signal is read off NIFTY's own bars; the option is the trade.",), "prelive"),
    "index-selling": Tab(
        "index-selling", "Index Option Selling", "/prelive-selling", "Strategy Factory · 546",
        "credit_spread", "nifty", 1_000_000.0, "INR",
        "NIFTY credit spreads sold: a BUY signal sells an ATM put spread, a SELL an ATM call spread, "
        f"{int(INDEX_WING_POINTS)}-point wing, the nearest listed weekly (4h/1d strategies: more than "
        f"{INDEX_SWING_MIN_SESSIONS} sessions left), 1 lot",
        ("Margin is the spread's maximum loss.",), "prelive_selling"),
    "stock-buying": Tab(
        "stock-buying", "Stock Pre-Live · Buying", "/stock-prelive-buying", "Strategy Factory · 546",
        "option_buy", "stocks", 1_000_000.0, "INR",
        "Stock options bought on the stock desk's 12 stocks: ATM CE on BUY, ATM PE on SELL, an expiry more "
        "than 7 sessions away, 1 lot",
        ("Most intraday strategies have no bars on single stocks yet (see the coverage line).",), "stock_desk"),
    "stock-selling": Tab(
        "stock-selling", "Stock Pre-Live · Selling", "/stock-prelive-selling", "Strategy Factory · 546",
        "credit_spread", "stocks", 1_000_000.0, "INR",
        "Stock option credit spreads on the stock desk's 12 stocks: BUY sells an ATM put spread, SELL an ATM "
        "call spread, the next listed strike as the wing, 1 lot",
        ("Most intraday strategies have no bars on single stocks yet (see the coverage line).",), "stock_desk"),
    "momentum": Tab(
        "momentum", "Momentum Trading", "/momentum", "Strategy Factory · 546",
        "equity_long", "equities", 10_000.0, "INR",
        "NSE cash equities, LONG signals only (sell signals are not shorted), ₹10,000 each, the desk's "
        "regime gate",
        ("Delivery charges when held overnight, intraday charges otherwise, plus 5 bp slippage a side.",),
        "momentum_engine"),
    "gold": Tab(
        "gold", "Gold Desk", "/gold-desk", "Strategy Factory · 546",
        "perp", "xaut", GOLD_SLEEVE_USD, "USD",
        "Delta's XAUTUSD perpetual, both sides, one $1,111 sleeve per strategy at 1x",
        ("Records beside the H1 forward test, never part of it.",), "gold_desk"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ist() -> datetime:
    return datetime.now(IST)


def _hm(t: datetime) -> int:
    return t.hour * 60 + t.minute


def _utc(ts) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _closed(bars: list, tf: str) -> list:
    """Drop a last bar that has not finished (its open + its length is still in the future)."""
    if bars and _utc(bars[-1].ts) + timedelta(minutes=TF_MINUTES.get(tf, 1)) > _now():
        return bars[:-1]
    return bars


def _current(tab: Tab, tf: str, bars: list) -> bool:
    """A signal is taken only off a bar that has just closed. NSE intraday timeframes: a bar of
    today's session that closed within two bar lengths (+5 min); gold: within two bar lengths
    (+5 min) around the clock; NSE 4h/1d: the last complete bar is the current one."""
    if not bars:
        return False
    start = _utc(bars[-1].ts)
    end = start + timedelta(minutes=TF_MINUTES.get(tf, 1))
    recent = _now() - end <= timedelta(minutes=2 * TF_MINUTES.get(tf, 1) + 5)
    if tab.market == "xaut":
        return recent
    if tf in INTRADAY_TFS:
        return recent and start.astimezone(IST).date() == _ist().date()
    return True


def _nse_open(t: datetime | None = None) -> bool:
    from app.services import market_calendar
    t = t or _ist()
    return market_calendar.is_trading_day(t) and 9 * 60 + 15 <= _hm(t) <= 15 * 60 + 30


def _entries_open(tab: Tab) -> tuple[bool, str]:
    from app.services import market_calendar
    if not tab.nse:
        return True, ""
    t = _ist()
    if not market_calendar.is_trading_day(t):
        return False, "NSE closed today (weekend or holiday)."
    if not (9 * 60 + 20 <= _hm(t) < 15 * 60):
        return False, "Outside 09:20-15:00 IST: no new entries."
    return True, ""


# -- bars ------------------------------------------------------------------------------------


async def _bars(tab: Tab, symbol: str, tf: str, limit: int = BARS_LIMIT) -> list:
    try:
        if tab.market == "xaut":
            from app.services import gold_delta_feed as g
            return await g.load_bars(symbol, tf, limit, closed_only=True)
        from app.services.strategy_factory import sources as src
        loader = src.index_load_bars if tab.market == "nifty" else src.equity_load_bars
        return _closed(await loader(symbol, tf, limit), tf)
    except Exception as exc:  # noqa: BLE001 - a missing series is a data gap, not a crash
        logger.debug("factory_desks bars %s %s %s: %s", tab.key, symbol, tf, exc)
        return []


_universe_cache: dict[str, tuple[datetime, list[str]]] = {}


async def _universe(tab: Tab) -> list[str]:
    if tab.market == "nifty":
        return ["NIFTY"]
    if tab.market == "xaut":
        return ["XAUTUSD"]
    if tab.market == "stocks":
        from app.services.stock_desk import UNIVERSE
        return list(UNIVERSE)
    hit = _universe_cache.get(tab.key)
    if hit and _now() - hit[0] < UNIVERSE_TTL:
        return hit[1]
    from app.services.strategy_factory.sources import equity_universe
    names = sorted(await equity_universe())
    _universe_cache[tab.key] = (_now(), names)
    return names


async def _equity_ltp(symbols: list[str]) -> dict[str, float]:
    """Angel's live LTP for NSE equities - what a fill or a time exit is priced at, not the bar."""
    from app.core.db import instruments_collection
    from app.services.stock_options import batched_ltp
    tok: dict[str, str] = {}
    async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": list(dict.fromkeys(symbols))}, "angel_token": {"$ne": None}},
            {"symbol": 1, "angel_token": 1}):
        tok.setdefault(d["symbol"], str(d["angel_token"]))
    if not tok:
        return {}
    px = await batched_ltp({"NSE": list(tok.values())})
    return {sym: float(px[t]) for sym, t in tok.items() if px.get(t)}


_regime_cache: dict = {}


async def _regime_ok() -> tuple[bool, str]:
    """The Momentum desk's own gate (index above its 200-DMA, volatility not in panic), read at most
    every ten minutes."""
    now = _now()
    if _regime_cache.get("at") and now - _regime_cache["at"] < timedelta(minutes=10):
        return _regime_cache["ok"], _regime_cache["why"]
    try:
        from app.services.momentum_engine import _regime
        reg = await _regime()
        ok, why = bool(reg.get("ok", True)), str(reg.get("reason") or "risk-off")
    except Exception:  # noqa: BLE001 - an unreadable gate is reported, not assumed
        ok, why = True, "regime gate unavailable this cycle"
    _regime_cache.update(at=now, ok=ok, why=why)
    return ok, why


# -- account ---------------------------------------------------------------------------------


_IS_OPEN = {"$eq": ["$status", "OPEN"]}
_IS_CLOSED = {"$ne": ["$status", "OPEN"]}
_RPNL = {"$ifNull": ["$realized_pnl", 0]}


async def _book(tab: Tab) -> dict[str, dict]:
    """Per strategy: realised, deployed, open count - summed by the database."""
    out: dict[str, dict] = {}
    async for r in POSITIONS.aggregate([
            {"$match": {"desk": tab.key}},
            {"$group": {"_id": "$strategy_id",
                        "realized": {"$sum": {"$cond": [_IS_OPEN, 0, _RPNL]}},
                        "deployed": {"$sum": {"$cond": [_IS_OPEN, {"$ifNull": ["$capital_deployed", 0]}, 0]}},
                        "open": {"$sum": {"$cond": [_IS_OPEN, 1, 0]}}}}]):
        out[r["_id"]] = {"realized": float(r["realized"]), "deployed": float(r["deployed"]), "open": int(r["open"])}
    return out


# -- option helpers ----------------------------------------------------------------------------


async def _quotes(tokens: list[str]) -> dict[str, dict]:
    """Angel FULL quotes for NFO tokens: {token: {ltp, bid, ask, trade_time, fresh, why}}. A quote
    is `fresh` only while NSE is in session, the contract traded within QUOTE_STALE_MIN minutes
    and both sides of the book are there. 50 tokens a request, paced."""
    from app.services import market_calendar
    from app.services.angel_client import angel_client
    toks = [str(t) for t in dict.fromkeys(tokens) if t]
    raw: dict[str, dict] = {}
    for i in range(0, len(toks), 50):
        try:
            raw.update(await angel_client.full_quote({"NFO": toks[i:i + 50]}))
        except Exception as exc:  # noqa: BLE001 - an unpriced leg is skipped, never invented
            logger.warning("factory desks: option FULL quote failed: %s", str(exc)[:120])
        await asyncio.sleep(QUOTE_PACE_SECONDS)
    now = datetime.now(IST)
    in_session = market_calendar.in_session(now)
    out: dict[str, dict] = {}
    for t in toks:
        r = raw.get(t)
        if not r:
            out[t] = {"ltp": None, "bid": None, "ask": None, "fresh": False, "why": "no quote"}
            continue
        q = {"ltp": r.get("ltp"), "bid": r.get("bid"), "ask": r.get("ask"), "fresh": False, "why": ""}
        tt = _trade_time(r.get("trade_time"))
        if not in_session:
            q["why"] = "NSE closed"
        elif tt is None:
            q["why"] = "no last-trade time"
        elif (now - tt).total_seconds() / 60 > QUOTE_STALE_MIN:
            q["why"] = f"no trade for {(now - tt).total_seconds() / 60:.0f} min"
        elif _spread(q) is None:
            q["why"] = "one-sided book"
        else:
            q["fresh"] = True
        out[t] = q
    return out


def _trade_time(raw: str | None) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(raw or "", fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _spread(q: dict) -> float | None:
    bid, ask = q.get("bid"), q.get("ask")
    if bid and ask and ask >= bid > 0:
        return (ask - bid) / ((ask + bid) / 2)
    return None


def _ask(q: dict | None) -> float | None:
    if not q or not q["fresh"] or (_spread(q) or 0.0) > MAX_QUOTE_SPREAD:
        return None
    return float(q["ask"])


def _bid(q: dict | None) -> float | None:
    if not q or not q["fresh"] or (_spread(q) or 0.0) > MAX_QUOTE_SPREAD:
        return None
    return float(q["bid"])


def _exit_px(q: dict | None, side: str) -> tuple[float | None, str]:
    """Closing a leg: a long leg sells at the bid, a short leg buys back at the ask; the LTP
    when that side is missing, labelled."""
    if not q:
        return None, "no quote"
    v = q["bid"] if side == "BUY" else q["ask"]
    if v and v > 0:
        return float(v), "touch"
    if q["ltp"] and q["ltp"] > 0:
        return float(q["ltp"]), "ltp_fallback"
    return None, "no price"


def _sessions_to(expiry: str, today: date | None = None) -> int:
    """NSE sessions from today to expiry, both counted (expiry day = 1, expired = 0)."""
    from app.services import market_calendar
    try:
        exp = date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return 0
    d, n = today or datetime.now(IST).date(), 0
    while d <= exp:
        n += market_calendar.is_listed_trading_day(d)
        d += timedelta(days=1)
    return n


async def _index_contracts(spot: float, kind: str, wing: bool, swing: bool) -> tuple[dict | None, dict | None, str | None]:
    """The ATM NIFTY option (and its wing) of the nearest listed weekly; a 4h/1d strategy, which
    holds for days, skips weeklies with INDEX_SWING_MIN_SESSIONS or fewer sessions left."""
    from app.services import nifty_scalp_engine as ns
    from app.core.db import instruments_collection
    if swing:
        exps = sorted(await instruments_collection.distinct(
            "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": "NIFTY",
                       "expiry": {"$gte": _ist().date().isoformat()}}))
        expiry = next((e for e in exps if _sessions_to(e) > INDEX_SWING_MIN_SESSIONS), None)
    else:
        expiry = await ns.near_expiry()
    if not expiry:
        return None, None, None
    short = await ns._atm_contract(expiry, spot, kind)
    if not short or not wing:
        return short, None, expiry
    target = short["strike"] - INDEX_WING_POINTS if kind == "PE" else short["strike"] + INDEX_WING_POINTS
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": "NIFTY", "expiry": expiry, "option_type": kind,
         "angel_token": {"$ne": None},
         "strike": {"$lt": short["strike"]} if kind == "PE" else {"$gt": short["strike"]}},
        {"symbol": 1, "strike": 1, "option_type": 1, "lot_size": 1, "angel_token": 1, "angel_tradingsymbol": 1})]
    w = min(rows, key=lambda r: abs(r["strike"] - target)) if rows else None
    return short, w, expiry


async def _stock_contracts(symbol: str, spot: float, kind: str, wing: bool) -> tuple[dict | None, dict | None, str | None]:
    from app.core.db import instruments_collection
    from app.services.stock_options import atm_contracts
    # The nearest listed monthly with MORE than STOCK_MIN_SESSIONS sessions left, so a position
    # never opens inside the last stretch of a contract's life.
    exps = sorted(e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol}) if e)
    expiry = next((e for e in exps if _sessions_to(e) > STOCK_MIN_SESSIONS), None)
    if not expiry:
        return None, None, None
    short = (await atm_contracts(symbol, spot, expiry)).get(kind)
    if not short or not wing:
        return short, None, expiry
    from app.services.stock_desk import _wing
    return short, await _wing(symbol, expiry, short["strike"], kind), expiry


def _leg(c: dict, side: str, px: float, expiry: str) -> dict:
    return {"token": str(c["angel_token"]), "tradingsymbol": c.get("angel_tradingsymbol") or c.get("symbol"),
            "strike": float(c["strike"]), "option_type": c["option_type"], "expiry": expiry,
            "side": side, "entry": round(px, 2)}


def _option_fees(legs: list[dict], lots: int, lot_size: int, exits: list[float] | None, on) -> dict:
    """Angel's option card on every leg: each leg's opening side and its close. The card is
    written buy-then-sell, so a short leg passes its buy-back as the buy and its sale as the
    sell (STT on the sale, stamp duty on the buy-back); a buy-back of nothing is floored at one
    tick so the leg is still charged."""
    from app.services.angel_fees import option_round_trip
    total, parts = 0.0, {}
    for i, leg in enumerate(legs):
        x = max(exits[i] if exits else leg["entry"], 0.0)
        if leg["side"] == "BUY":
            fb = option_round_trip(leg["entry"], x, lots, lot_size, on=on)
        else:
            fb = option_round_trip(max(x, 0.05), leg["entry"], lots, lot_size, on=on)
        d = fb.as_dict()
        total += fb.total
        for k, v in d.items():
            if k not in ("total", "product") and isinstance(v, (int, float)):
                parts[k] = parts.get(k, 0.0) + float(v)
    return {"total": round(total, 2), "parts": {k: round(v, 2) for k, v in parts.items()}}


# -- opening -------------------------------------------------------------------------------------


async def _plan_option(tab: Tab, sig, symbol: str, spot: float, swing: bool = False) -> dict | str:
    """Contracts for a signal; prices come in one batched quote afterwards."""
    if tab.kind == "option_buy":
        kind = "CE" if sig.side == "BUY" else "PE"
        wing = False
    else:   # credit_spread: a bullish view sells puts, a bearish one sells calls
        kind = "PE" if sig.side == "BUY" else "CE"
        wing = True
    if tab.market == "nifty":
        short, w, expiry = await _index_contracts(spot, kind, wing, swing)
    else:
        short, w, expiry = await _stock_contracts(symbol, spot, kind, wing)
    if not short:
        return "no listed contract"
    if wing and not w:
        return "no wing strike"
    return {"kind": kind, "short": short, "wing": w, "expiry": expiry}


async def _open_rows(tab: Tab, signals: list[tuple], cash: dict[str, float]) -> tuple[list[dict], dict[str, int]]:
    """Turn this cycle's signals into position rows (prices, sizes, costs), or skips by reason."""
    skips: dict[str, int] = {}

    def skip(why: str) -> None:
        skips[why] = skips.get(why, 0) + 1

    rows: list[dict] = []
    if tab.kind in ("option_buy", "credit_spread"):
        spots: dict[str, float] = {}
        if tab.market == "nifty":
            from app.services import nifty_scalp_engine as ns
            s = await ns._spot()
            if s:
                spots["NIFTY"] = s
        plans = []
        for strat, sig, symbol in signals:
            spot = spots.get(symbol) or float(sig.entry)
            plan = await _plan_option(tab, sig, symbol, spot, swing=strat.timeframe not in INTRADAY_TFS)
            if isinstance(plan, str):
                skip(plan)
                continue
            plans.append((strat, sig, symbol, spot, plan))
        quotes = await _quotes([str(p[4]["short"]["angel_token"]) for p in plans] +
                               [str(p[4]["wing"]["angel_token"]) for p in plans if p[4]["wing"]])
        for strat, sig, symbol, spot, plan in plans:
            short, w, expiry = plan["short"], plan["wing"], plan["expiry"]
            lot_size = int(short.get("lot_size") or 1)
            if tab.kind == "option_buy":
                ask = _ask(quotes.get(str(short["angel_token"])))
                if ask is None:
                    skip("no fresh two-sided quote")
                    continue
                legs = [_leg(short, "BUY", ask, expiry)]
                cost = ask * lot_size
                credit = None
            else:
                sb = _bid(quotes.get(str(short["angel_token"])))
                wa = _ask(quotes.get(str(w["angel_token"])))
                if sb is None or wa is None:
                    skip("no fresh two-sided quote")
                    continue
                credit = round(sb - wa, 2)
                if credit <= 0:
                    skip("no credit")
                    continue
                width = abs(float(short["strike"]) - float(w["strike"]))
                legs = [_leg(short, "SELL", sb, expiry), _leg(w, "BUY", wa, expiry)]
                cost = max((width - credit) * lot_size, 1.0)
            if cost > cash.get(strat.strategy_id, tab.capital):
                skip("no cash")
                continue
            rows.append(_row(tab, strat, sig, symbol, legs=legs, lots=1, lot_size=lot_size, cost=cost,
                             spot=spot, credit=credit, entry_basis="ask/bid touch"))
        return rows, skips

    if tab.kind == "equity_long":
        from backtesting_service.costs import DELIVERY, INTRADAY, CostModel
        cm = CostModel()
        live = await _equity_ltp([sym for _s, sig, sym in signals if sig.side == "BUY"])
        for strat, sig, symbol in signals:
            if sig.side != "BUY":
                skip("sell signal (long only)")
                continue
            if not live.get(symbol):
                skip("no live price")
                continue
            fill = live[symbol] * (1 + EQUITY_SLIPPAGE_BP / 1e4)
            qty = int(min(tab.capital, cash.get(strat.strategy_id, tab.capital)) // fill) if fill > 0 else 0
            if qty < 1:
                skip("price above the account")
                continue
            product = INTRADAY if strat.timeframe in INTRADAY_TFS else DELIVERY
            entry_costs = float(cm.order_charges(product, fill, qty, True))
            rows.append(_row(tab, strat, sig, symbol, legs=None, lots=qty, lot_size=1, cost=fill * qty,
                             spot=live[symbol], entry_px=fill, product=product, entry_costs=entry_costs,
                             entry_basis="live LTP + 5 bp"))
        return rows, skips

    # perp (gold)
    from app.services import gold_delta_feed as g
    spec = await g.product("XAUTUSD")
    fee_rate = (spec or {}).get("taker_fee_rate")
    if not fee_rate:
        return [], {"the venue publishes no taker fee": len(signals)}
    for side in ("BUY", "SELL"):
        mine = [x for x in signals if x[1].side == side]
        if not mine:
            continue
        fp = await g.fill_price("XAUTUSD", side, 1)
        if not fp:
            skips["no two-sided market"] = skips.get("no two-sided market", 0) + len(mine)
            continue
        px = float(fp["price"])
        for strat, sig, symbol in mine:
            notional = min(tab.capital, cash.get(strat.strategy_id, tab.capital))
            if notional < tab.capital * 0.5:
                skip("no cash")
                continue
            fee = notional * float(fee_rate) * (1 + DELTA_GST)
            rows.append(_row(tab, strat, sig, symbol, legs=None, lots=1, lot_size=1, cost=notional,
                             spot=px, entry_px=px, entry_costs=round(fee, 4), fee_rate=float(fee_rate),
                             funding_s=int((spec or {}).get("funding_interval_s") or 14400),
                             entry_basis=fp.get("basis", "touch")))
    return rows, skips


def _row(tab: Tab, strat, sig, symbol: str, *, legs, lots: int, lot_size: int, cost: float, spot: float,
         credit: float | None = None, entry_px: float | None = None, product: str | None = None,
         entry_costs: float = 0.0, fee_rate: float | None = None, funding_s: int | None = None,
         entry_basis: str = "") -> dict:
    now = _now()
    return {
        "position_id": uuid4().hex[:12], "desk": tab.key, "strategy_id": strat.strategy_id,
        "strategy_name": strat.name, "family": strat.family, "timeframe": strat.timeframe,
        "symbol": symbol, "signal_side": sig.side,
        "side": ("SELL" if tab.kind == "credit_spread" else ("BUY" if tab.kind != "perp" else sig.side)),
        "kind": tab.kind, "legs": legs, "lots": lots, "lot_size": lot_size, "credit": credit,
        "entry_px": round(entry_px, 4) if entry_px is not None else (legs[0]["entry"] if legs else None),
        "product": product, "entry_costs": entry_costs, "fee_rate": fee_rate, "funding_s": funding_s,
        "under_entry": round(float(spot), 4), "stop": round(float(sig.stop), 4), "target": round(float(sig.target), 4),
        "signal_entry": round(float(sig.entry), 4), "r_multiple": getattr(sig, "r_multiple", None),
        "pattern": getattr(sig, "pattern", ""), "signal_bar_ts": _utc(sig.bar_ts),
        "max_hold_bars": int(DEFAULT_MAX_HOLD.get(strat.timeframe, 60)), "bars_held": 0,
        "capital_deployed": round(cost, 2), "unrealized_pnl": 0.0, "realized_pnl": None,
        "gross_pnl": None, "fees": None, "exit_reason": None, "exit_basis": None, "status": "OPEN",
        "entry_basis": entry_basis, "currency": tab.currency,
        "opened_at": now, "opened_on": _ist().date().isoformat(), "closed_at": None, "closed_on": None,
        "updated_at": now,
    }


# -- scanning --------------------------------------------------------------------------------------


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Per (tab, symbol, timeframe), in memory: when a newer bar can next exist, the newest stored bar at
# the last full load, (depth, current) at that load, and the last closed bar the scan evaluated.
_due_at: dict[tuple[str, str, str], datetime] = {}
_newest_seen: dict[tuple[str, str, str], datetime | None] = {}
_series: dict[tuple[str, str, str], tuple[int, bool]] = {}
_last_eval: dict[tuple[str, str, str], datetime] = {}
_min_bars: dict[str, list[int]] = {}


async def _newest_ts(tab: Tab, symbol: str, tf: str) -> datetime | None:
    """Open time of the newest stored bar of the series (symbol, tf) is built from: one indexed
    document, so looking at a series that has not moved costs almost nothing."""
    if tab.market == "xaut":
        from app.core.db import gold_bars_collection as coll
        from app.services.gold_delta_feed import DERIVED_FROM
    else:
        from app.core.db import bars_collection as coll
        from app.services.strategy_factory.sources import DERIVED_FROM
    d = await coll.find_one({"symbol": symbol, "timeframe": DERIVED_FROM.get(tf, tf)}, {"ts": 1}, sort=[("ts", -1)])
    return _utc(d.get("ts")) if d else None


def _back_off(tab: Tab, tf: str, newest: datetime | None) -> timedelta:
    """How long before a series with no newer bar is looked at again."""
    if newest is None:
        return timedelta(minutes=30)        # nothing stored for it at all
    if tf not in INTRADAY_TFS:
        return timedelta(minutes=60)
    if tab.nse and newest.astimezone(IST).date() != _ist().date():
        return timedelta(minutes=5)         # today's session has not reached it yet
    return timedelta(minutes=1)


async def _series_bars(tab: Tab, symbol: str, tf: str, pc: dict, force: bool = False) -> list:
    """(symbol, tf)'s bars for this pass, read at most once a pass (`pc`) and only when a newer bar
    can exist: before its next bar's close nothing is read; after it, one probe of the newest stored
    bar decides whether the full read is worth it. [] when there is nothing new (or no data)."""
    if (symbol, tf) in pc:
        return pc[(symbol, tf)]
    k = (tab.key, symbol, tf)
    now = _now()
    if not force:
        if now < _due_at.get(k, _EPOCH):
            return []
        newest = await _newest_ts(tab, symbol, tf)
        if k in _newest_seen and newest == _newest_seen[k]:
            _due_at[k] = now + _back_off(tab, tf, newest)
            return []
    else:
        newest = await _newest_ts(tab, symbol, tf)
    bars = await _bars(tab, symbol, tf)
    _newest_seen[k] = newest
    cur = _current(tab, tf, bars)
    _series[k] = (len(bars), cur)
    nxt = _utc(bars[-1].ts) + timedelta(minutes=2 * TF_MINUTES[tf], seconds=10) if bars and cur else None
    _due_at[k] = nxt if nxt and nxt > now else now + _back_off(tab, tf, _utc(bars[-1].ts) if bars else None)
    pc[(symbol, tf)] = bars
    return bars


def _coverage(tab: Tab) -> tuple[dict[str, int], list[str]]:
    """By timeframe: (strategy, symbol) pairs with enough bars at each series' last read; and the
    timeframes whose every deep-enough series had no just-closed bar at that read."""
    if not _min_bars:
        for st in FACTORY_CATALOG:
            _min_bars.setdefault(st.timeframe, []).append(st.min_bars)
    cov: dict[str, int] = {}
    deep: set[str] = set()
    live: set[str] = set()
    for (k, _sym, tf), (n, cur) in list(_series.items()):
        if k != tab.key:
            continue
        c = sum(1 for m in _min_bars.get(tf, ()) if n >= m)
        if c:
            cov[tf] = cov.get(tf, 0) + c
            deep.add(tf)
            if cur:
                live.add(tf)
    return cov, sorted(deep - live, key=lambda t: TF_MINUTES[t])


def _evaluate_batch(jobs: list[tuple], exchange: str) -> list[tuple]:
    out = []
    for strat, bars, symbol, htf in jobs:
        try:
            sig, _rej = evaluate(strat, bars, symbol, exchange, htf)
        except Exception:  # noqa: BLE001 - one strategy's error costs one signal
            sig = None
        if sig is not None:
            out.append((strat, sig, symbol))
    return out


async def _scan(tab: Tab, book: dict[str, dict], pc: dict) -> dict:
    from app.services.desk_switches import is_on
    ok, why = _entries_open(tab)
    if not ok:
        return {"opened": 0, "notes": [why]}
    if tab.switch and not await is_on(tab.switch):
        return {"opened": 0, "notes": [f"Main Control has {tab.module} OFF: no new entries (open positions are still managed)."]}
    notes: list[str] = []
    if tab.market == "equities":
        ok, why = await _regime_ok()
        if not ok:
            return {"opened": 0, "notes": [f"Regime gate: {why} - no new longs."]}
    busy = {sid for sid, r in book.items() if r["open"] > 0}
    candidates = [st for st in FACTORY_CATALOG if st.strategy_id not in busy]
    exchange = "DELTA" if tab.market == "xaut" else "NSE"
    signals: list[tuple] = []
    for symbol in await _universe(tab):
        fresh: dict[str, list] = {}         # timeframe -> bars whose just-closed bar is not evaluated yet
        for tf in sorted({st.timeframe for st in candidates}, key=lambda t: TF_MINUTES[t]):
            bars = await _series_bars(tab, symbol, tf, pc)
            k = (tab.key, symbol, tf)
            if not bars or not _current(tab, tf, bars) or _last_eval.get(k) == _utc(bars[-1].ts):
                continue
            _last_eval[k] = _utc(bars[-1].ts)
            fresh[tf] = bars
        if not fresh:
            continue
        htfs: dict[str, list] = {}
        jobs = []
        for strat in candidates:
            bars = fresh.get(strat.timeframe)
            if not bars or len(bars) < strat.min_bars:
                continue
            htf = None
            if strat.htf:
                if strat.htf not in htfs:
                    got = pc.get((symbol, strat.htf))
                    htfs[strat.htf] = got[-400:] if got else await _bars(tab, symbol, strat.htf, 400)
                htf = htfs[strat.htf]
            jobs.append((strat, bars, symbol, htf))
        if jobs:
            signals += await to_thread.run_sync(_evaluate_batch, jobs, exchange)
        if signals and tab.market in ("stocks", "equities"):
            # one position per strategy across the whole universe: a strategy that just fired on
            # this symbol is not offered the next one in the same pass
            fired = {st.strategy_id for st, _sig, _sym in signals}
            candidates = [st for st in candidates if st.strategy_id not in fired]
    coverage, stale = _coverage(tab)
    await STATE.update_one({"_id": f"coverage:{tab.key}"},
                           {"$set": {"by_tf": coverage, "stale_tfs": stale, "at": _now()}}, upsert=True)
    if stale:
        notes.append("No just-closed bar (feed behind or not live), so not traded: " + ", ".join(stale))
    if not signals:
        return {"opened": 0, "notes": notes}
    # a strategy holds one position per tab; the same signal bar is never entered twice
    firsts: dict[str, tuple] = {}
    for strat, sig, symbol in signals:
        firsts.setdefault(strat.strategy_id, (strat, sig, symbol))
    fresh_sigs = []
    for strat, sig, symbol in firsts.values():
        dup = await POSITIONS.find_one({"desk": tab.key, "strategy_id": strat.strategy_id, "symbol": symbol,
                                        "signal_bar_ts": _utc(sig.bar_ts)}, {"_id": 1})
        if not dup:
            fresh_sigs.append((strat, sig, symbol))
    cash = {sid: tab.capital + r["realized"] - r["deployed"] for sid, r in book.items()}
    rows, skips = await _open_rows(tab, fresh_sigs, cash)
    if rows:
        await POSITIONS.insert_many(rows)
    if skips:
        await STATE.update_one({"_id": f"skips:{tab.key}"},
                               {"$inc": {f"by_reason.{k}": v for k, v in skips.items()},
                                "$set": {"at": _now()}}, upsert=True)
        notes.append("Skipped: " + ", ".join(f"{v} {k}" for k, v in skips.items()))
    return {"opened": len(rows), "signals": len(fresh_sigs), "notes": notes}


# -- managing --------------------------------------------------------------------------------------


def _hit(p: dict, bar) -> str | None:
    long_view = p["signal_side"] == "BUY"
    stop = bar.low <= p["stop"] if long_view else bar.high >= p["stop"]
    tgt = bar.high >= p["target"] if long_view else bar.low <= p["target"]
    return "stoploss" if stop else ("target" if tgt else None)


def _intrinsic(leg: dict, spot: float) -> float:
    return max(0.0, spot - leg["strike"]) if leg["option_type"] == "CE" else max(0.0, leg["strike"] - spot)


async def _funding(p: dict, until: datetime) -> float:
    from app.services import gold_delta_feed as g
    from app.services.gold_fills import funding_cost, funding_exchanges
    series = await g.funding_series("XAUTUSD")
    side = 1 if p["signal_side"] == "BUY" else -1
    total = 0.0
    for ts in funding_exchanges(int(_utc(p["opened_at"]).timestamp()), int(until.timestamp()),
                                int(p.get("funding_s") or 14400)):
        rate, _basis = g.rate_at(series, ts)
        if rate is not None:
            total += funding_cost(side, p["capital_deployed"], rate)
    return round(total, 4)


async def _close(tab: Tab, p: dict, reason: str, prices: dict) -> None:
    """Book the close. `prices`: option legs -> exit premium per leg; underlying -> exit level."""
    on = _ist().date()
    if tab.kind in ("option_buy", "credit_spread"):
        exits = prices["legs"]
        qty = p["lots"] * p["lot_size"]
        gross = sum((x - leg["entry"]) * qty * (1 if leg["side"] == "BUY" else -1)
                    for leg, x in zip(p["legs"], exits))
        fees = _option_fees(p["legs"], p["lots"], p["lot_size"], exits, on)
        net = gross - fees["total"]
        extra = {"exit_legs": [round(x, 2) for x in exits], "fee_breakdown": fees["parts"], "fees": fees["total"]}
    elif tab.kind == "equity_long":
        from backtesting_service.costs import CostModel
        x = float(prices["under"]) * (1 - EQUITY_SLIPPAGE_BP / 1e4)
        gross = (x - p["entry_px"]) * p["lots"]
        exit_costs = float(CostModel().order_charges(p.get("product"), x, p["lots"], False))
        fees_total = round((p.get("entry_costs") or 0.0) + exit_costs, 2)
        net = gross - fees_total
        extra = {"exit_px": round(x, 4), "fees": fees_total}
    else:
        x = float(prices["under"])
        side = 1 if p["signal_side"] == "BUY" else -1
        gross = side * (x - p["entry_px"]) / p["entry_px"] * p["capital_deployed"]
        exit_fee = p["capital_deployed"] * float(p.get("fee_rate") or 0) * (1 + DELTA_GST)
        funding = await _funding(p, _now())
        fees_total = round((p.get("entry_costs") or 0.0) + exit_fee + funding, 4)
        net = gross - fees_total
        extra = {"exit_px": round(x, 4), "fees": fees_total, "funding": funding}
    await POSITIONS.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
        **extra, "status": "CLOSED", "exit_reason": reason, "exit_basis": prices.get("basis"),
        "gross_pnl": round(gross, 2), "realized_pnl": round(net, 2), "unrealized_pnl": 0.0,
        "closed_at": _now(), "closed_on": on.isoformat(), "updated_at": _now()}})


async def _manage(tab: Tab, pc: dict) -> dict:
    open_rows = [p async for p in POSITIONS.find({"desk": tab.key, "status": "OPEN"})]
    if not open_rows:
        return {"closed": 0, "marked": 0}
    if tab.nse and not _nse_open():
        return {"closed": 0, "marked": 0, "notes": ["NSE closed: open positions wait for the session."]}
    t = _ist()
    today = t.date().isoformat()
    after_1515 = _hm(t) >= 15 * 60 + 15
    decisions: list[tuple] = []
    for p in open_rows:
        # time exits need no bars
        timed = None
        if tab.nse:
            opened_on = p.get("opened_on")
            stale_day = bool(opened_on and opened_on < today)
            if p["timeframe"] in INTRADAY_TFS and (after_1515 or stale_day) and (tab.kind != "equity_long" or p.get("product") != "delivery"):
                timed = "eod"
            elif p.get("legs"):
                exp = p["legs"][0]["expiry"]
                if tab.market == "nifty" and exp and (today > exp or (today == exp and after_1515)):
                    timed = "expiry"
                elif tab.market == "stocks" and exp and _sessions_to(exp) <= STOCK_EXIT_SESSIONS:
                    timed = "expiry_window"
        # stop / target / hold limit only move when a bar closes, so the bars are read only then
        bars = await _series_bars(tab, p["symbol"], p["timeframe"], pc, force=timed is not None)
        start = _utc(p.get("signal_bar_ts"))
        after = [b for b in bars if start is None or _utc(b.ts) > start]
        reason, hit_bar = None, None
        for b in after:
            reason = _hit(p, b)
            if reason:
                hit_bar = b
                break
        held = len(after) if bars else int(p.get("bars_held") or 0)
        if reason is None and bars and held >= p.get("max_hold_bars", 60):
            reason = "max_hold"
        decisions.append((p, reason or timed, held, after, hit_bar))
    # prices
    tokens = [leg["token"] for p, *_r in decisions for leg in (p.get("legs") or [])]
    quotes = await _quotes(tokens) if tokens else {}
    spot_now: dict[str, float] = {}
    marks: list[UpdateOne] = []
    n = {"closed": 0, "marked": 0}
    for p, reason, held, after, hit_bar in decisions:
        last = after[-1].close if after else None
        if p.get("legs"):
            exits, basis = [], "touch"
            for leg in p["legs"]:
                x, b = _exit_px(quotes.get(leg["token"]), leg["side"])
                if x is None and reason == "expiry":
                    # the contract no longer quotes: settle at intrinsic on the underlying's last
                    # close on or before expiry day, never on a later bar
                    upto = [bb for bb in after if _utc(bb.ts).astimezone(IST).date().isoformat() <= leg["expiry"]]
                    x = _intrinsic(leg, float(upto[-1].close if upto else p["under_entry"]))
                    b = "intrinsic"
                exits.append(x)
                if b != "touch":
                    basis = b
            if reason and all(x is not None for x in exits):
                await _close(tab, p, reason, {"legs": exits, "basis": basis})
                n["closed"] += 1
                continue
            if all(x is not None for x in exits):
                qty = p["lots"] * p["lot_size"]
                u = sum((x - leg["entry"]) * qty * (1 if leg["side"] == "BUY" else -1) for leg, x in zip(p["legs"], exits))
                upd = {"unrealized_pnl": round(u, 2), "mark_legs": [round(x, 2) for x in exits], "bars_held": held,
                       "updated_at": _now()}
                if last is not None:
                    upd["under_ltp"] = last
                marks.append(UpdateOne({"_id": p["_id"], "status": "OPEN"}, {"$set": upd}))
                n["marked"] += 1
            continue
        # underlying-priced (momentum, gold)
        if reason in ("stoploss", "target"):
            level, basis = (p["stop"] if reason == "stoploss" else p["target"]), "strategy level"
            if reason == "stoploss" and hit_bar is not None:
                # a bar that OPENED through the stop fills at its open, not at the stop
                gapped = hit_bar.open < level if p["signal_side"] == "BUY" else hit_bar.open > level
                if gapped:
                    level, basis = float(hit_bar.open), "gap open"
            await _close(tab, p, reason, {"under": level, "basis": basis})
            n["closed"] += 1
            continue
        px = last
        if tab.market == "equities":
            if "_ltp" not in spot_now:
                spot_now["_ltp"] = await _equity_ltp([q["symbol"] for q, *_r in decisions if not q.get("legs")])
            px = spot_now["_ltp"].get(p["symbol"]) or last
        if tab.market == "xaut":
            if p["symbol"] not in spot_now:
                from app.services import gold_delta_feed as g
                fp = await g.fill_price("XAUTUSD", "SELL" if p["signal_side"] == "BUY" else "BUY", 1)
                spot_now[p["symbol"]] = float(fp["price"]) if fp else (last or p["entry_px"])
            px = spot_now[p["symbol"]]
        if reason and px:
            await _close(tab, p, reason, {"under": px, "basis": "touch" if tab.market == "xaut" else "live LTP"})
            n["closed"] += 1
            continue
        if px:
            side = 1 if p["signal_side"] == "BUY" else -1
            if tab.kind == "equity_long":
                u = (px - p["entry_px"]) * p["lots"] - (p.get("entry_costs") or 0.0)
            else:
                u = side * (px - p["entry_px"]) / p["entry_px"] * p["capital_deployed"] - (p.get("entry_costs") or 0.0)
            marks.append(UpdateOne({"_id": p["_id"], "status": "OPEN"}, {"$set": {
                "unrealized_pnl": round(u, 2), "under_ltp": px, "bars_held": held, "updated_at": _now()}}))
            n["marked"] += 1
    if marks:
        await POSITIONS.bulk_write(marks, ordered=False)
    return n


# -- cycle -----------------------------------------------------------------------------------------


_lock = asyncio.Lock()
_indexed = False


_gold_read: dict[str, float] = {}


async def _refresh_gold(tab: Tab) -> None:
    """The gold scheduler keeps only 1m, 1d and H1's own timeframes fresh, and only while that
    desk is active. This tab reads all eight, so it re-reads each native interval of the shared
    store itself once a bar of that length has closed since its last read (45m derives from 15m)."""
    from app.services import gold_delta_feed as g
    now = _now().timestamp()
    due = [tf for tf in g.NATIVE_TIMEFRAMES
           if int((now - 15) // g.tf_seconds(tf)) > int((_gold_read.get(tf, 0.0) - 15) // g.tf_seconds(tf))]
    if not due:
        return
    for symbol in await _universe(tab):
        out = await g.refresh_symbol(symbol, due)
        for tf, n in out.items():
            if n >= 0:
                _gold_read[tf] = now


async def run_tab(key: str) -> dict:
    tab = TABS[key]
    if tab.market == "xaut":
        try:
            await _refresh_gold(tab)
        except Exception as exc:  # noqa: BLE001 - stale bars hold entries back; they never crash the tab
            logger.warning("[factory_desks] gold bar refresh failed: %s", exc)
    pc: dict = {}                       # this pass's bar reads, shared by managing and scanning
    m = await _manage(tab, pc)
    book = await _book(tab)
    s = await _scan(tab, book, pc)
    await STATE.update_one({"_id": f"cycle:{tab.key}"}, {"$set": {
        "at": _now(), "closed": m.get("closed", 0), "marked": m.get("marked", 0), "opened": s.get("opened", 0),
        "notes": (m.get("notes") or []) + (s.get("notes") or [])}}, upsert=True)
    await _snapshot(tab)
    return {"manage": m, "scan": s}


async def run_all(only: str | None = None) -> dict:
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    out = {}
    async with _lock:
        for key in TABS:
            if only and key != only:
                continue
            if not only and TABS[key].nse and not _nse_open():
                continue                    # an NSE tab has nothing to do outside the session
            try:
                out[key] = await run_tab(key)
            except Exception as exc:  # noqa: BLE001 - one tab's failure must not stop the others
                logger.warning("[factory_desks] %s failed: %s", key, exc, exc_info=True)
                out[key] = {"error": str(exc)[:200]}
    return out


async def loop() -> None:
    """Every minute: the NSE tabs in session, the gold tab around the clock."""
    logger.info("[factory_desks] records in database %r (%s)", STORE.name,
                "FACTORY_MONGO_URL" if FACTORY_MONGO_URL else "the main database: FACTORY_MONGO_URL is unset")
    await asyncio.sleep(45)
    while True:
        if ENABLED:
            try:
                await run_all()
            except Exception:  # noqa: BLE001
                logger.warning("[factory_desks] cycle failed", exc_info=True)
        await asyncio.sleep(60)


async def _snapshot(tab: Tab) -> None:
    last = await EQUITY.find_one({"desk": tab.key}, {"ts": 1}, sort=[("ts", -1)])
    if last is not None and naive_utc(_now()) - naive_utc(last["ts"]) < timedelta(minutes=SNAPSHOT_EVERY_MIN):
        return
    s = await summary(tab.key)
    await EQUITY.insert_one({"ts": _now(), "desk": tab.key, "equity": s["equity"],
                             "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"],
                             "open_positions": s["open_positions"]})


async def summary(key: str) -> dict:
    tab = TABS[key]
    cap = tab.capital * len(FACTORY_CATALOG)
    agg = {r["_id"]: r async for r in POSITIONS.aggregate([
        {"$match": {"desk": key}},
        {"$group": {"_id": {"$cond": [_IS_OPEN, "OPEN", "CLOSED"]}, "n": {"$sum": 1},
                    "realized": {"$sum": _RPNL},
                    "unrealized": {"$sum": {"$ifNull": ["$unrealized_pnl", 0]}},
                    "deployed": {"$sum": {"$ifNull": ["$capital_deployed", 0]}},
                    "fees": {"$sum": {"$ifNull": ["$fees", 0]}},
                    "gross": {"$sum": {"$ifNull": ["$gross_pnl", 0]}},
                    "wins": {"$sum": {"$cond": [{"$gt": [_RPNL, 0]}, 1, 0]}}}}])}
    o, c = agg.get("OPEN") or {}, agg.get("CLOSED") or {}
    open_n, deployed, unrealized = int(o.get("n", 0)), float(o.get("deployed", 0.0)), float(o.get("unrealized", 0.0))
    closed_n, realized, wins = int(c.get("n", 0)), float(c.get("realized", 0.0)), int(c.get("wins", 0))
    fees, gross = float(c.get("fees", 0.0)), float(c.get("gross", 0.0))
    cyc = await STATE.find_one({"_id": f"cycle:{key}"}) or {}
    cov = await STATE.find_one({"_id": f"coverage:{key}"}) or {}
    sk = await STATE.find_one({"_id": f"skips:{key}"}) or {}
    families: dict[str, int] = {}
    for s in FACTORY_CATALOG:
        families[s.family] = families.get(s.family, 0) + 1
    return {
        "desk": key, "module": tab.module, "label": tab.label, "kind": tab.kind, "instrument": tab.instrument,
        "notes": list(tab.notes), "currency": tab.currency, "strategies": len(FACTORY_CATALOG),
        "families": families, "per_strategy_capital": tab.capital, "desk_capital": cap,
        "equity": round(cap + realized + unrealized, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "deployed": round(deployed, 2), "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "roi_pct": round((realized + unrealized) / cap * 100, 4) if cap else 0.0,
        "coverage": cov.get("by_tf") or {}, "stale_tfs": cov.get("stale_tfs") or [],
        "skipped": sk.get("by_reason") or {},
        "last_cycle_at": naive_utc(cyc["at"]).replace(tzinfo=timezone.utc).isoformat() if cyc.get("at") else None,
        "last_notes": cyc.get("notes") or [],
    }


async def leaderboard(key: str, family: str | None = None, timeframe: str | None = None) -> list[dict]:
    tab = TABS[key]
    won = {"$and": [_IS_CLOSED, {"$gt": [_RPNL, 0]}]}
    lost = {"$and": [_IS_CLOSED, {"$lt": [_RPNL, 0]}]}
    rec: dict[str, dict] = {r["_id"]: r async for r in POSITIONS.aggregate([
        {"$match": {"desk": key}},
        {"$group": {"_id": "$strategy_id",
                    "trades": {"$sum": {"$cond": [_IS_CLOSED, 1, 0]}},
                    "wins": {"$sum": {"$cond": [won, 1, 0]}},
                    "net": {"$sum": {"$cond": [_IS_CLOSED, _RPNL, 0]}},
                    "fees": {"$sum": {"$cond": [_IS_CLOSED, {"$ifNull": ["$fees", 0]}, 0]}},
                    "open": {"$sum": {"$cond": [_IS_OPEN, 1, 0]}},
                    "unreal": {"$sum": {"$cond": [_IS_OPEN, {"$ifNull": ["$unrealized_pnl", 0]}, 0]}},
                    "gw": {"$sum": {"$cond": [won, _RPNL, 0]}},
                    "gl": {"$sum": {"$cond": [lost, {"$multiply": [_RPNL, -1]}, 0]}}}}])}
    rows = []
    for s in FACTORY_CATALOG:
        if family and s.family != family:
            continue
        if timeframe and s.timeframe != timeframe:
            continue
        r = rec.get(s.strategy_id) or {}
        n = r.get("trades", 0)
        rows.append({
            "strategy_id": s.strategy_id, "name": s.name, "family": s.family, "timeframe": s.timeframe,
            "htf": s.htf, "target_r": getattr(s, "target_r", None),
            "trades": n, "wins": r.get("wins", 0), "win_rate": round(r.get("wins", 0) / n, 4) if n else 0.0,
            "net_pnl": round(r.get("net", 0.0), 2), "fees": round(r.get("fees", 0.0), 2),
            "profit_factor": round(r["gw"] / r["gl"], 3) if r.get("gl") else None,
            "open_positions": r.get("open", 0), "unrealized_pnl": round(r.get("unreal", 0.0), 2),
            "roi_pct": round(r.get("net", 0.0) / tab.capital * 100, 4) if tab.capital else 0.0,
        })
    rows.sort(key=lambda r: (-r["net_pnl"], -r["trades"], r["strategy_id"]))
    return rows


def _jsonable(doc: dict) -> dict:
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = _utc(v).isoformat()
    return doc


async def positions(key: str, status: str = "OPEN", limit: int = 200) -> list[dict]:
    q: dict = {"desk": key}
    if status.upper() != "ALL":
        q["status"] = status.upper()
    sort_key = "opened_at" if status.upper() == "OPEN" else "closed_at"
    return [_jsonable(p) async for p in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


async def ensure_indexes() -> None:
    try:
        await POSITIONS.create_index([("desk", 1), ("status", 1)], name="fd_desk_status")
        await POSITIONS.create_index([("desk", 1), ("strategy_id", 1), ("symbol", 1), ("signal_bar_ts", 1)],
                                     name="fd_signal_once")
        await EQUITY.create_index([("desk", 1), ("ts", -1)], name="fd_equity_ts")
    except Exception:  # noqa: BLE001 - an index is a speed-up, never a precondition
        logger.warning("[factory_desks] index creation skipped", exc_info=True)
