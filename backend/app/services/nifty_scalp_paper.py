"""NIFTY 50 Option Scalping — the Rs 2,00,000 PAPER BOOK.

The scalping desk next door gives each of its 504 strategies its own Rs 2,00,000, which is
Rs 10.08 crore and is not a book anybody has. It exists to rank rules against each other,
and for that a per-strategy allocation is the right shape: every strategy gets the same
money so their records are comparable.

This is the other question. A hand-picked roster of those strategies trades ONE shared
Rs 2,00,000 — the amount a real person might actually put up — and therefore has to live
with what the big desk never faces: the strategies compete for the same cash, a position
open on one rule is money the next rule cannot use, and the whole book is the denominator
of the ROI. A roster that looks wonderful at Rs 2 lakh EACH can be mediocre at Rs 2 lakh
BETWEEN them, and nothing on the parent desk will tell you that.

WHAT IS HONEST TO EXPECT. The default roster was picked off the parent desk's leaderboard
by realised ROI. That is selection after the fact from 504 candidates on a desk whose own
ROI was -15%: the best dozen of 504 will look excellent on luck alone, and these have
4-19 closed trades each. This book is the out-of-sample test of that pick, so its record
is worth something only once it has trades of its own. Until then read it as a hypothesis,
not as a result. The same caution is written on the crypto desk that did this first.

HOW IT TRADES. Exactly like the parent desk, so the comparison means something: signals
read off NIFTY SPOT candles, expressed by BUYING the near-expiry option nearest the money,
never sold, real Angel One F&O costs charged on every close, one trade per closed bar, one
open position per strategy. It rides the parent's cycle and its already-fetched candles
rather than fetching its own — Angel's historical endpoint is the binding rate limit on
this desk and a second poller would break both books.

SIZING. Each rostered strategy targets an equal slice of the book, so twelve strategies
means a Rs 16,666 target each. A slice too small for one lot is allowed one lot anyway
when the cash is there — a small real book buys one lot or nothing — and when the cash is
not there the trade is SKIPPED and said so in the notes. Silent skips would make the book
look like it had no signal when what it had was no money.
"""

import logging
import os
from datetime import date, datetime, timezone
from uuid import uuid4

from app.core.db import (
    nifty_scalp_paper_equity_collection,
    nifty_scalp_paper_positions_collection,
    nifty_scalp_paper_scores_collection,
    nifty_scalp_paper_state_collection,
    nifty_scalp_paper_trades_collection,
)
from app.services.angel_fees import option_round_trip
from app.services.call_engine import IST
from app.services.desk_totals import split as _totals_split
from app.services.nifty_scalp_strategies import CATALOG, CATALOG_BY_ID, TIMEFRAME_BY_KEY

logger = logging.getLogger("nifty_scalp_paper")

BOOK_CAPITAL = float(os.getenv("NS_PAPER_CAPITAL", "200000"))
ENABLED = os.getenv("NS_PAPER_ENABLED", "1").lower() not in ("0", "false", "")
# A slice below one lot still gets one lot if the cash is there. A real Rs 2 lakh book buys
# a lot or it does not trade; it cannot buy two thirds of one.
ALLOW_ONE_LOT_OVER_SLICE = os.getenv("NS_PAPER_ONE_LOT", "1").lower() not in ("0", "false", "")
MAX_CONCURRENT = int(os.getenv("NS_PAPER_MAX_CONCURRENT", "0"))  # 0 = only cash limits it
DAILY_LOSS_BREAKER_PCT = float(os.getenv("NS_PAPER_DAILY_LOSS_PCT", "0.05"))
SWING_MAX_DAYS = int(os.getenv("NS_PAPER_SWING_MAX_DAYS", "5"))
SQUAREOFF = os.getenv("NS_SQUAREOFF", "15:15")

# The picks, as (template, timeframe). NOT strategy ids: an id is `ns_<tf>_<index into
# TEMPLATES>`, so adding or reordering a template silently repoints every id after it and
# this roster would quietly start trading different rules. The template NAME is the thing
# the user chose.
DEFAULT_ROSTER: list[tuple[str, str]] = [
    ("Engulfing Candle", "5m"),
    ("Marubozu Continuation", "4h"),
    ("Marubozu Continuation", "1m"),
    ("MACD Divergence", "1h"),
    ("Stochastic Extreme Cross", "5m"),
    ("Stochastic Extreme Cross", "1h"),
    ("Marubozu Continuation", "15m"),
    ("TTM Squeeze Release", "4h"),
    ("Round Number Break", "5m"),
    ("RSI Divergence", "1h"),
    ("MACD Histogram Flip", "5m"),
    ("MACD Signal Cross", "5m"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


# ── roster ─────────────────────────────────────────────────────────────────────

_BY_TEMPLATE_TF = {(s.template, s.timeframe): s for s in CATALOG}


def resolve(template: str, timeframe: str):
    return _BY_TEMPLATE_TF.get((template, timeframe))


def default_roster_ids() -> list[str]:
    """The default picks as strategy ids, dropping any whose template no longer exists.

    Dropped rather than raised on: a template removed upstream must not take the whole
    backend down at import, and a roster short one rule is a working book."""
    out = []
    for template, tf in DEFAULT_ROSTER:
        st = resolve(template, tf)
        if st is None:
            logger.warning("[ns_paper] default roster entry %r %s no longer exists", template, tf)
            continue
        out.append(st.strategy_id)
    return out


async def get_roster() -> list[str]:
    doc = await nifty_scalp_paper_state_collection.find_one({"_id": "roster"})
    if doc and isinstance(doc.get("strategy_ids"), list):
        # Filter through the catalog on every read: an id that no longer resolves would
        # otherwise sit in the roster for ever, counted in the slice divisor and never
        # trading, quietly shrinking every other strategy's size.
        return [sid for sid in doc["strategy_ids"] if sid in CATALOG_BY_ID]
    ids = default_roster_ids()
    await nifty_scalp_paper_state_collection.update_one(
        {"_id": "roster"},
        {"$set": {"strategy_ids": ids, "seeded_at": _now(), "source": "default"}},
        upsert=True)
    return ids


async def set_roster(strategy_ids: list[str]) -> dict:
    clean, unknown = [], []
    for sid in dict.fromkeys(strategy_ids):
        (clean if sid in CATALOG_BY_ID else unknown).append(sid)
    if not clean:
        raise ValueError(
            "That roster has no strategies this desk knows. Ids look like `ns_5m_37` and "
            "must come from the parent desk's leaderboard."
            + (f" Unrecognised: {', '.join(unknown[:5])}." if unknown else ""))
    await nifty_scalp_paper_state_collection.update_one(
        {"_id": "roster"},
        {"$set": {"strategy_ids": clean, "updated_at": _now(), "source": "user"}},
        upsert=True)
    return {"strategy_ids": clean, "count": len(clean), "unknown": unknown}


# ── money ──────────────────────────────────────────────────────────────────────


async def available_cash() -> float:
    op, cl = await _totals_split(nifty_scalp_paper_positions_collection)
    return round(BOOK_CAPITAL + cl["realized"] - op["deployed"], 2)


async def today_pnl() -> float:
    """Realised today plus unrealised on positions opened today — the number the breaker
    reads, and the same definition the parent desk uses."""
    today = _today()
    total = 0.0
    async for p in nifty_scalp_paper_positions_collection.find(
            {"$or": [{"closed_on": today}, {"opened_on": today, "status": "OPEN"}]}):
        total += float(p.get("realized_pnl") or 0.0) + float(p.get("unrealized_pnl") or 0.0)
    return round(total, 2)


async def breaker_state() -> dict:
    limit = -abs(BOOK_CAPITAL * DAILY_LOSS_BREAKER_PCT)
    pnl = await today_pnl()
    return {"today_pnl": pnl, "daily_loss_limit": round(limit, 2),
            "breaker_tripped": pnl <= limit}


# ── scoring ────────────────────────────────────────────────────────────────────


async def _update_score(strategy_id: str) -> None:
    trades = [t async for t in nifty_scalp_paper_trades_collection.find(
        {"strategy_id": strategy_id})]
    if not trades:
        return
    net = sum(float(t.get("realized_pnl") or 0.0) for t in trades)
    gross = sum(float(t.get("gross_pnl") or 0.0) for t in trades)
    fees = sum(float(t.get("fees") or 0.0) for t in trades)
    wins = sum(1 for t in trades if float(t.get("realized_pnl") or 0.0) > 0)
    st = CATALOG_BY_ID.get(strategy_id)
    await nifty_scalp_paper_scores_collection.update_one(
        {"_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id,
            "name": st.name if st else strategy_id,
            "template": st.template if st else None,
            "family": st.family if st else None,
            "timeframe": st.timeframe if st else None,
            "trades": len(trades), "wins": wins,
            "win_rate": round(wins / len(trades), 4),
            "net_pnl": round(net, 2), "gross_pnl": round(gross, 2),
            "fees": round(fees, 2),
            # ROI against the SLICE this strategy is entitled to, not against the whole
            # book — a rule that makes Rs 5,000 on its Rs 16,666 share has returned 30%,
            # and dividing by Rs 2 lakh would report 2.5% and hide it.
            "updated_at": _now(),
        }}, upsert=True)


# ── trading ────────────────────────────────────────────────────────────────────


async def _slice_for(roster_size: int) -> float:
    return BOOK_CAPITAL / max(roster_size, 1)


async def on_signals(fired: list, contracts: dict, prices: dict, spot: float,
                     expiry: str, series: dict) -> dict:
    """Open what the ROSTER fired, on this cycle's already-fetched candles and quotes.

    Called from the parent desk's `scan()` with exactly the data it just used, so this book
    costs no extra candle requests. `fired` is [(strategy, direction)] for the whole desk;
    everything not on the roster is ignored here."""
    if not ENABLED:
        return {"opened": 0, "skipped": 0, "notes": ["paper book disabled"]}

    roster = set(await get_roster())
    mine = [(st, d) for st, d in fired if st.strategy_id in roster]
    if not mine:
        return {"opened": 0, "skipped": 0, "notes": []}

    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "skipped": len(mine), "notes": [
            f"PAPER BOOK BREAKER TRIPPED — today's P&L Rs{breaker['today_pnl']:,.0f} crossed "
            f"the Rs{breaker['daily_loss_limit']:,.0f} limit. No new positions."]}

    state = await nifty_scalp_paper_state_collection.find_one({"_id": "bars"}) or {}
    last_bar: dict = state.get("last", {})

    open_now = await nifty_scalp_paper_positions_collection.count_documents({"status": "OPEN"})
    cash = await available_cash()
    slice_size = await _slice_for(len(roster))

    notes: list[str] = []
    opened = skipped = 0
    fresh: dict[str, str] = {}
    for st, d in mine:
        bar_ts = str(series[st.timeframe].ts[-1])
        if last_bar.get(st.strategy_id) == bar_ts:
            continue  # already acted on this bar — the parent desk's guard, same reason
        fresh[st.strategy_id] = bar_ts

        if MAX_CONCURRENT and open_now >= MAX_CONCURRENT:
            skipped += 1
            notes.append(f"{st.name}: skipped, {open_now} positions already open "
                         f"(limit {MAX_CONCURRENT}).")
            continue
        if await nifty_scalp_paper_positions_collection.find_one(
                {"strategy_id": st.strategy_id, "status": "OPEN"}):
            continue  # one directional bet per strategy at a time

        kind = "CE" if d > 0 else "PE"
        c = contracts.get(kind)
        premium = prices.get(str(c["angel_token"])) if c else None
        if not c or not premium:
            continue

        lot = int(c.get("lot_size") or 75)
        per_lot = premium * lot
        if per_lot <= 0:
            continue
        lots = int(slice_size // per_lot)
        if lots < 1 and ALLOW_ONE_LOT_OVER_SLICE:
            lots = 1
        if lots < 1:
            continue
        cost = per_lot * lots
        if cost > cash:
            # Say it. A book that ran out of money looks exactly like a book with no
            # signal unless this is written down.
            skipped += 1
            notes.append(
                f"{st.name}: signal fired but Rs{cost:,.0f} needed and only Rs{cash:,.0f} "
                "is free — the book is fully deployed.")
            continue

        tf = TIMEFRAME_BY_KEY[st.timeframe]
        await nifty_scalp_paper_positions_collection.insert_one({
            "position_id": uuid4().hex[:12],
            "strategy_id": st.strategy_id, "strategy_name": st.name, "template": st.template,
            "family": st.family, "timeframe": st.timeframe, "style": st.style,
            "symbol": c["symbol"], "option_type": c["option_type"],
            "strike": c["strike"], "expiry": expiry,
            "angel_token": str(c["angel_token"]),
            "angel_exchange": c.get("angel_exchange") or "NFO",
            "direction": "BULLISH" if d > 0 else "BEARISH",
            "side": "BUY", "lots": lots, "lot_size": lot, "qty": lots * lot,
            "entry_premium": round(premium, 2), "ltp": round(premium, 2),
            "entry_spot": round(spot, 2),
            "capital_deployed": round(cost, 2),
            "slice_target": round(slice_size, 2),
            "target_premium": round(premium * (1 + tf.target_pct / 100), 2),
            "stop_premium": round(premium * (1 - tf.stop_pct / 100), 2),
            "max_hold_bars": tf.max_hold_bars, "bars_held": 0,
            "unrealized_pnl": 0.0, "realized_pnl": None, "gross_pnl": None,
            "fees": None, "fee_breakdown": None,
            "exit_premium": None, "exit_reason": None, "status": "OPEN",
            "bar_ts": bar_ts,
            "opened_at": _now(), "opened_on": _today(), "closed_at": None, "closed_on": None,
            "updated_at": _now(),
        })
        cash -= cost
        open_now += 1
        opened += 1

    if fresh:
        await nifty_scalp_paper_state_collection.update_one(
            {"_id": "bars"}, {"$set": {f"last.{k}": v for k, v in fresh.items()}}, upsert=True)
    return {"opened": opened, "skipped": skipped, "notes": notes}


async def manage(prices: dict | None = None) -> int:
    """Mark and exit. Same rules as the parent desk, so a strategy's record here differs
    from its record there only by SIZE and by competition for cash — which is the whole
    point of running this book."""
    if not ENABLED:
        return 0
    positions = [p async for p in nifty_scalp_paper_positions_collection.find({"status": "OPEN"})]
    if not positions:
        return 0

    prices = dict(prices or {})
    missing = [p for p in positions if p["angel_token"] not in prices]
    if missing:
        # The parent quotes only the contracts IT holds. This book can hold a contract the
        # parent has already exited, so anything not in the handed-down sweep is quoted
        # here — a handful of tokens on the cheap endpoint, never candles.
        from app.services.nifty_scalp_engine import _quote_options
        seen: dict[str, dict] = {}
        for p in missing:
            seen.setdefault(p["angel_token"], {"angel_token": p["angel_token"],
                                               "angel_exchange": p.get("angel_exchange")})
        try:
            prices.update(await _quote_options(list(seen.values())))
        except Exception:  # noqa: BLE001 — a failed sweep means "mark nothing", not "crash"
            logger.exception("[ns_paper] quote sweep failed")

    eod = _hhmm() >= SQUAREOFF
    today = _today()
    closed = 0
    touched: set[str] = set()
    for p in positions:
        ltp = prices.get(p["angel_token"])
        if ltp is None:
            continue
        gross = round((ltp - p["entry_premium"]) * p["qty"], 2)
        bars = (p.get("bars_held") or 0) + 1
        days = (date.fromisoformat(today) - date.fromisoformat(p["opened_on"])).days
        style = p.get("style", "intraday")

        reason = None
        if ltp >= p["target_premium"]:
            reason = "target"
        elif ltp <= p["stop_premium"]:
            reason = "stoploss"
        elif p["expiry"] <= today and eod:
            reason = "expiry"
        elif style in ("scalping", "intraday") and (eod or days >= 1):
            reason = "eod"
        elif style == "swing" and days >= SWING_MAX_DAYS:
            reason = "max_hold"
        elif bars >= p["max_hold_bars"] and style == "scalping":
            reason = "time_stop"

        changes = {"ltp": round(ltp, 2), "unrealized_pnl": gross,
                   "bars_held": bars, "updated_at": _now()}
        if reason:
            fb = option_round_trip(p["entry_premium"], ltp, p["lots"], p["lot_size"])
            net = round(gross - fb.total, 2)
            changes.update({
                "status": "CLOSED", "exit_premium": round(ltp, 2), "exit_reason": reason,
                "gross_pnl": gross, "fees": fb.total, "fee_breakdown": fb.as_dict(),
                "realized_pnl": net, "unrealized_pnl": 0.0,
                "closed_at": _now(), "closed_on": today,
            })
            touched.add(p["strategy_id"])
            closed += 1
            await nifty_scalp_paper_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
                "strategy_name": p["strategy_name"], "timeframe": p["timeframe"],
                "symbol": p["symbol"], "direction": p["direction"], "lots": p["lots"],
                "entry_premium": p["entry_premium"], "exit_premium": round(ltp, 2),
                "gross_pnl": gross, "fees": fb.total, "realized_pnl": net,
                "exit_reason": reason, "opened_at": p["opened_at"], "closed_at": _now(),
            })
        await nifty_scalp_paper_positions_collection.update_one(
            {"_id": p["_id"]}, {"$set": changes})

    for sid in touched:
        await _update_score(sid)
    return closed


async def snapshot() -> None:
    """One equity point per cycle, for the curve."""
    s = await summary()
    await nifty_scalp_paper_equity_collection.insert_one({
        "ts": _now(), "equity": s["equity"], "realized": s["realized_pnl"],
        "unrealized": s["unrealized_pnl"], "fees": s["total_fees"],
        "roi_pct": s["roi_pct"], "open_positions": s["open_positions"],
    })


# ── reporting ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    op, cl = await _totals_split(nifty_scalp_paper_positions_collection)
    roster = await get_roster()
    realized, fees, unrealized, deployed = cl["realized"], cl["fees"], op["unrealized"], op["deployed"]
    equity = BOOK_CAPITAL + realized + unrealized
    return {
        "mode": "paper", "enabled": ENABLED,
        "book_capital": BOOK_CAPITAL,
        "roster_size": len(roster),
        "slice_per_strategy": round(await _slice_for(len(roster)), 2),
        "deployed_capital": round(deployed, 2),
        "available_cash": round(BOOK_CAPITAL + realized - deployed, 2),
        "realized_pnl": round(realized, 2),
        "gross_realized_pnl": round(realized + fees, 2),
        "total_fees": round(fees, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(equity, 2),
        "roi_pct": round((equity - BOOK_CAPITAL) / BOOK_CAPITAL * 100, 4) if BOOK_CAPITAL else 0.0,
        "open_positions": op["n"],
        "closed_positions": cl["n"],
        "one_lot_over_slice": ALLOW_ONE_LOT_OVER_SLICE,
        "max_concurrent": MAX_CONCURRENT or None,
        **(await breaker_state()),
        "note": (
            "One shared book, not Rs 2 lakh per strategy — the roster competes for the same "
            "cash, which the parent desk never has to do. The picks were made off that "
            "desk's leaderboard AFTER the fact, so this book is the out-of-sample test of "
            "them; judge it on the trades it takes here, not on the record that got them "
            "picked."),
    }


async def roster_rows() -> list[dict]:
    """The roster with each strategy's record ON THIS BOOK, beside the parent desk's."""
    from app.core.db import nifty_scalp_scores_collection

    ids = await get_roster()
    mine = {s["_id"]: s async for s in nifty_scalp_paper_scores_collection.find(
        {"_id": {"$in": ids}})}
    theirs = {s["strategy_id"]: s async for s in nifty_scalp_scores_collection.find(
        {"strategy_id": {"$in": ids}})}
    slice_size = await _slice_for(len(ids))

    rows = []
    for sid in ids:
        st = CATALOG_BY_ID.get(sid)
        if st is None:
            continue
        m = mine.get(sid) or {}
        t = theirs.get(sid) or {}
        net = round(float(m.get("net_pnl") or 0.0), 2)
        rows.append({
            "strategy_id": sid, "name": st.name, "template": st.template,
            "family": st.family, "timeframe": st.timeframe, "style": st.style,
            "slice": round(slice_size, 2),
            "trades": int(m.get("trades") or 0),
            "win_rate": float(m.get("win_rate") or 0.0),
            "net_pnl": net,
            "gross_pnl": round(float(m.get("gross_pnl") or 0.0), 2),
            "fees": round(float(m.get("fees") or 0.0), 2),
            "roi_pct": round(net / slice_size * 100, 3) if slice_size else 0.0,
            "desk_trades": int(t.get("trades") or 0),
            "desk_net_pnl": round(float(t.get("net_pnl") or 0.0), 2),
            "desk_roi_pct": round(float(t.get("roi_pct") or 0.0), 3),
        })
    rows.sort(key=lambda r: (-r["net_pnl"], r["name"]))
    return rows


async def positions(status: str = "OPEN", limit: int = 300) -> list[dict]:
    q: dict = {} if status.upper() == "ALL" else {"status": status.upper()}
    cur = nifty_scalp_paper_positions_collection.find(q).sort("opened_at", -1).limit(limit)
    out = []
    async for p in cur:
        p.pop("_id", None)
        for k in ("opened_at", "closed_at", "updated_at"):
            if isinstance(p.get(k), datetime):
                p[k] = p[k].isoformat()
        out.append(p)
    return out


async def daily(limit: int = 60) -> list[dict]:
    pipe = [
        {"$match": {"status": "CLOSED", "closed_on": {"$ne": None}}},
        {"$group": {"_id": "$closed_on",
                    "net": {"$sum": {"$ifNull": ["$realized_pnl", 0]}},
                    "fees": {"$sum": {"$ifNull": ["$fees", 0]}},
                    "gross": {"$sum": {"$ifNull": ["$gross_pnl", 0]}},
                    "trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$realized_pnl", 0]}, 0]}, 1, 0]}}}},
        {"$sort": {"_id": -1}},
        {"$limit": limit},
    ]
    out = []
    async for r in nifty_scalp_paper_positions_collection.aggregate(pipe):
        out.append({
            "date": r["_id"],
            "net_pnl": round(float(r["net"]), 2),
            "fees": round(float(r["fees"]), 2),
            "gross_pnl": round(float(r["gross"]), 2),
            "trades": int(r["trades"]),
            "wins": int(r["wins"]),
            "win_rate": round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0,
            "roi_pct": round(float(r["net"]) / BOOK_CAPITAL * 100, 4) if BOOK_CAPITAL else 0.0,
        })
    return out


__all__ = [
    "BOOK_CAPITAL", "ENABLED", "DEFAULT_ROSTER", "default_roster_ids",
    "get_roster", "set_roster", "resolve", "roster_rows",
    "on_signals", "manage", "snapshot", "summary", "positions", "daily",
    "available_cash", "today_pnl", "breaker_state",
]
