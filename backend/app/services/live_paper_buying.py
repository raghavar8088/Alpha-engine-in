"""Live Paper Buying — the Pre-Live leaderboard's winners, on real-sized books, live data.

WHAT THIS IS
The Pre-Live tournament runs the whole option-buying library, each strategy on its own
₹10 lakh account, to find out which ones actually work forward. This desk takes the ones
that came out on top and trades them the way a real account of ordinary size would, on
live Angel One prices and REAL option premiums. Still paper.

TWO BOOKS, ONE SET OF SIGNALS
    50k   Live Paper Buying · ₹50,000
    2L    Live Paper Trade  · ₹2,00,000
Both trade the same roster. Signals are computed ONCE per cycle and both books act on the
same signal — the strategies carry internal state, and calling one twice per bar (once per
book) would advance that state twice and hand the second book a different decision than
the first. The books differ only in how much capital they have to act with.

ONE SHARED POOL PER BOOK, NOT A SLICE PER STRATEGY
The first version gave each of five strategies a fixed ₹10,000. With 21 strategies, a
₹50,000 book split evenly is ₹2,381 each — and one NIFTY lot (65) of an ATM option at a
₹100 premium costs ₹6,500, so every slice would be too small to ever trade. A real account
does not reserve cash for trades it has not taken: every signal draws on what the book
has free. When several fire at once and the book cannot fund them all, the roster ORDER
decides — it is the tournament's rank, so the best-proven strategy gets first call.

ONE LOT PER POSITION — THE TOURNAMENT'S UNIT
The leaderboard these were picked from was built at one lot per position, so that is what
these books trade. Their records are then directly comparable to the numbers that got the
strategies picked, rather than blending in a sizing decision the tournament never made.

EACH STRATEGY ON ITS OWN TIMEFRAME
Fifteen of the roster are 15-minute strategies and six are 5-minute. The timeframe is read
from each strategy's own metadata — the same value the tournament ran it at — and each
timeframe gets its own bar history and its own strategy context.

DECIDE ONCE, ON A CLOSED BAR
Angel's candle feed includes the bar still forming. The first version evaluated every
cycle on whatever the last bar was, which means deciding on a half-built candle and then
re-deciding on the same candle a minute later as it changed. Signals are now taken once
per timeframe per COMPLETED bar. The last bar evaluated is persisted, so a restart does
not re-decide a bar that was already acted on.

COSTS. Until 2026-10-02 no broker costs were charged here. Positions closed from then on
pay Angel One's option rate card (tradingai_shared.option_fees: Rs20 an order, STT 0.15% of
the premium sold, exchange, SEBI, stamp, GST), and each closed trade says which basis it is on.

PAUSED BY THE GATE (2026-10-02). This roster is the ANTI of the tournament's 21 "best"
rows of 2026-09-29. Those rows were read-time sign flips of the WORST strategies' records,
never traded; and the Pre-Live audit found that no strategy in the library predicts NIFTY's
direction (two-year replay: 47.8-48.4% hit), so the leaderboard cannot select. A real ANTI
buys the OPPOSITE option, which is not even the trade the flipped record described. New
entries now require the strategy to hold a CONFIRMED verdict in the option-hypothesis
registry (app.services.option_hypotheses); none does, so the books open nothing and keep
their records. LIVE_PAPER_REQUIRE_GATE=0 restores the old behaviour.

MECHANICS UNCHANGED FROM THE FIRST VERSION
Signals buy the ATM CE (bullish) or PE (bearish) of the nearest weekly expiry. Managed to a
premium stop and target, squared off at 15:15, no new entries after 15:00.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    live_paper_equity_collection,
    live_paper_positions_collection,
    live_paper_scores_collection,
    live_paper_state_collection,
    live_paper_trades_collection,
)
from app.services.angel_client import angel_client
from app.services.anti_strategies import register_anti_buying
from tradingai_shared.option_fees import option_round_trip
from app.services.stock_options import batched_ltp
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe
from app.services import market_calendar

logger = logging.getLogger("live_paper_buying")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "engine"

UNDERLYING = os.getenv("LIVE_PAPER_UNDERLYING", "NIFTY")
STOP_PCT = float(os.getenv("LIVE_PAPER_STOP_PCT", "0.35"))
TARGET_PCT = float(os.getenv("LIVE_PAPER_TARGET_PCT", "0.60"))
ENTRY_CUTOFF = os.getenv("LIVE_PAPER_ENTRY_CUTOFF", "15:00")
SQUAREOFF = os.getenv("LIVE_PAPER_SQUAREOFF", "15:15")
MARKET_OPEN = "09:15"
LOTS_PER_POSITION = 1
REQUIRE_GATE = os.getenv("LIVE_PAPER_REQUIRE_GATE", "1").lower() not in ("0", "false", "no")
COSTS_FROM = "2026-10-02"           # trades closed on/after this date pay the rate card
SELECTION_BASIS = ("Picked on 2026-09-29 from the Pre-Live leaderboard's ANTI rows — sign flips of the worst "
                   "strategies' records that never traded. No strategy in the library predicts NIFTY's direction "
                   "(two-year replay, 47.8-48.4% hit), so these picks have no evidence behind them.")

# ── the books ────────────────────────────────────────────────────────────────────
BOOKS: dict[str, float] = {
    "50k": float(os.getenv("LIVE_PAPER_CAPITAL", "50000")),
    "2L": float(os.getenv("LIVE_PAPER_CAPITAL_2L", "200000")),
}
BOOK_LABELS = {"50k": "Live Paper Buying · ₹50k", "2L": "Live Paper Trade · ₹2 lakh"}
DEFAULT_BOOK = "50k"

# Kept for anything that still reads the old single-book constant.
TOTAL_CAPITAL = BOOKS[DEFAULT_BOOK]

# ── the roster ───────────────────────────────────────────────────────────────────
# Base ids, each traded as its ANTI, in the Pre-Live tournament's rank order by net P&L
# (leaderboard of 2026-09-29, ranks 1-21). The ORDER IS THE CAPITAL PRIORITY when a book
# cannot fund every signal in a cycle — see the module docstring.
SELECTED_BASES = [s.strip() for s in os.getenv(
    "LIVE_PAPER_STRATEGIES",
    "intra_macd_hist_turn,intra_trix,intra_rsi_divergence,scalp_stoch_pop,"
    "nj_premium_discount,intra_rsi_regime,scalp_rsi2,sl_reversal_finder,intra_ema_stack,"
    "mt_breakout_buying,it_market_structure,scalp_ibs,prt_hero_zero,mr_1min_scalp,"
    "stockforce_zone_buy,intra_linreg_slope,ema_5_close,crt_range,intra_stoch_swing,"
    "up_sniper_scalp,intra_bb_ride"
).split(",") if s.strip()]

# How each timeframe is fetched. Days are sized to comfortably exceed the largest warmup
# in the roster (81 bars) without asking Angel's rate-limited candle endpoint for more.
TF_CFG: dict[str, dict] = {
    "15m": {"interval": "15", "minutes": 15, "days": 10, "enum": Timeframe.M15},
    "5m": {"interval": "5", "minutes": 5, "days": 4, "enum": Timeframe.M5},
}
_ENUM_TO_TF = {cfg["enum"]: tf for tf, cfg in TF_CFG.items()}
CANDLE_PACE_SECONDS = 0.5


class LivePaperError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _market_open() -> bool:
    return market_calendar.is_trading_day() and MARKET_OPEN <= _hhmm() <= "15:30"


def _book(book: str | None) -> str:
    return book if book in BOOKS else DEFAULT_BOOK


# ── strategies ───────────────────────────────────────────────────────────────────

_ctx: dict[str, StrategyContext] = {}
_insts: dict[str, object] = {}


def selected() -> list[dict]:
    """The roster, resolved against the registry, in rank (= capital priority) order."""
    register_anti_buying()
    out = []
    for rank, base in enumerate(SELECTED_BASES, start=1):
        aid = f"anti_{base}"
        cls = STRATEGY_REGISTRY.get(aid)
        if cls is None:
            logger.warning("live_paper: %s not registered", aid)
            continue
        tfs = list(getattr(cls.metadata, "timeframes", []) or [])
        tf = next((_ENUM_TO_TF[t] for t in tfs if t in _ENUM_TO_TF), None)
        if tf is None:
            logger.warning("live_paper: %s has no supported timeframe (%s)", aid, tfs)
            continue
        out.append({"strategy_id": aid, "base_id": base, "rank": rank, "timeframe": tf,
                    "name": getattr(cls.metadata, "name", aid)})
    return out


def _instance(sid: str):
    inst = _insts.get(sid)
    if inst is None:
        cls = STRATEGY_REGISTRY.get(sid)
        if cls is None:
            return None
        try:
            inst = cls(params={})
        except Exception:
            return None
        _insts[sid] = inst
    return inst


# ── one-time migration ───────────────────────────────────────────────────────────

_migrated = False


async def _migrate() -> None:
    """Every document written before books existed belongs to the ₹50k book.

    Additive and idempotent: it only sets `book` where it is missing, and it must run
    before the first manage pass or an open position from the old version would belong to
    no book and never be managed."""
    global _migrated
    if _migrated:
        return
    for coll in (live_paper_positions_collection, live_paper_trades_collection,
                 live_paper_equity_collection, live_paper_scores_collection):
        try:
            await coll.update_many({"book": {"$exists": False}}, {"$set": {"book": DEFAULT_BOOK}})
        except Exception:
            logger.exception("live_paper: book backfill failed on %s", coll.name)
            return
    _migrated = True


# ── market data ──────────────────────────────────────────────────────────────────


async def _underlying_token() -> tuple[str, str] | None:
    d = await instruments_collection.find_one(
        {"asset_class": "INDEX", "symbol": UNDERLYING, "angel_token": {"$ne": None}},
        {"angel_token": 1, "angel_exchange": 1})
    if not d:
        return None
    return str(d["angel_token"]), d.get("angel_exchange") or "NSE"


async def _closed_bars(tf: str) -> list[Bar]:
    """Bars for one timeframe, with the still-forming bar dropped."""
    ref = await _underlying_token()
    if not ref:
        return []
    token, ex = ref
    cfg = TF_CFG[tf]
    now = datetime.now(IST)
    frm = (now - timedelta(days=cfg["days"])).strftime("%Y-%m-%d 09:15")
    to = now.strftime("%Y-%m-%d %H:%M")
    try:
        rows = await angel_client.candles(ex, token, cfg["interval"], frm, to)
    except Exception as exc:
        logger.debug("live_paper: %s candles failed (%s)", tf, exc)
        return []
    out = []
    span = timedelta(minutes=cfg["minutes"])
    for r in rows or []:
        try:
            ts = datetime.fromisoformat(r[0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            if ts + span > now:          # still forming — not a bar yet
                continue
            out.append(Bar(symbol=UNDERLYING, timeframe=cfg["enum"], ts=ts,
                           open=float(r[1]), high=float(r[2]), low=float(r[3]),
                           close=float(r[4]), volume=float(r[5]), oi=None))
        except (ValueError, TypeError, IndexError):
            continue
    return out


async def _weekly_expiry() -> str | None:
    today = _today()
    exps = [e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING}) if e and e >= today]
    return min(exps) if exps else None


async def _atm(kind: str, spot: float, expiry: str) -> dict | None:
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING, "expiry": expiry,
         "option_type": kind, "angel_token": {"$ne": None}},
        {"symbol": 1, "strike": 1, "lot_size": 1, "angel_token": 1, "angel_tradingsymbol": 1})]
    if not rows:
        return None
    return min(rows, key=lambda r: abs(r["strike"] - spot))


# ── capital ──────────────────────────────────────────────────────────────────────


async def _free_cash(book: str) -> float:
    realized = deployed = 0.0
    async for p in live_paper_positions_collection.find(
            {"book": book}, {"status": 1, "realized_pnl": 1, "cost": 1}):
        if p.get("status") == "OPEN":
            deployed += p.get("cost") or 0.0
        else:
            realized += p.get("realized_pnl") or 0.0
    return BOOKS[book] + realized - deployed


async def _update_score(book: str, sid: str) -> None:
    closed = [p async for p in live_paper_positions_collection.find(
        {"book": book, "strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1})]
    n = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net = sum(p.get("realized_pnl") or 0 for p in closed)
    gw = sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) > 0)
    gl = -sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) < 0)
    meta = next((s for s in selected() if s["strategy_id"] == sid), None)
    await live_paper_scores_collection.update_one(
        {"book": book, "strategy_id": sid},
        {"$set": {"book": book, "strategy_id": sid, "name": meta["name"] if meta else sid,
                  "base_id": meta["base_id"] if meta else None,
                  "trades": n, "wins": wins, "win_rate": round(wins / n, 4) if n else 0.0,
                  "net_pnl": round(net, 2),
                  "profit_factor": round(gw / gl, 2) if gl > 0 else None,
                  "expectancy": round(net / n, 2) if n else 0.0, "updated_at": _now()}},
        upsert=True,
    )


# ── cycle ────────────────────────────────────────────────────────────────────────


async def _signals(notes: list[str]) -> tuple[list[tuple[dict, str]], float | None]:
    """Evaluate each timeframe's strategies once per newly completed bar.

    Returns (signals in rank order, latest spot)."""
    roster = selected()
    by_tf: dict[str, list[dict]] = {}
    for s in roster:
        by_tf.setdefault(s["timeframe"], []).append(s)

    st = await live_paper_state_collection.find_one({"_id": STATE_ID}) or {}
    last_eval: dict = dict(st.get("last_eval_bar") or {})
    fresh: dict[str, str] = {}
    wants: list[tuple[dict, str]] = []
    spot: float | None = None

    for i, (tf, specs) in enumerate(by_tf.items()):
        if i:
            await asyncio.sleep(CANDLE_PACE_SECONDS)      # candle endpoint is rate-limited hard
        bars = await _closed_bars(tf)
        if len(bars) < 30:
            notes.append(f"Only {len(bars)} completed {tf} bars — not enough to signal on.")
            continue
        ctx = _ctx.get(tf)
        if ctx is None:
            ctx = _ctx[tf] = StrategyContext(max_bars=500)
        last = ctx.bars[-1].ts if ctx.bars else None
        for b in bars:
            if last is None or b.ts > last:
                ctx.push(b)
        if tf == "5m" or spot is None:
            spot = bars[-1].close                           # the freshest close available

        newest = str(ctx.bars[-1].ts)
        if last_eval.get(tf) == newest:
            continue                                        # already decided on this bar
        fresh[tf] = newest
        for s in specs:
            inst = _instance(s["strategy_id"])
            if inst is None or len(ctx.bars) < getattr(inst, "warmup", 30):
                continue
            try:
                sig = inst.on_bar(ctx)
            except Exception:
                continue
            if sig is None or sig.signal not in (SignalAction.BUY, SignalAction.SELL):
                continue
            # Option BUYING: bullish is a long CE, bearish a long PE.
            wants.append((s, "CE" if sig.signal == SignalAction.BUY else "PE"))

    if fresh:
        await live_paper_state_collection.update_one(
            {"_id": STATE_ID}, {"$set": {f"last_eval_bar.{k}": v for k, v in fresh.items()}},
            upsert=True)
    wants.sort(key=lambda w: w[0]["rank"])
    return wants, spot


async def run_cycle(force: bool = False) -> dict:
    await _migrate()
    notes: list[str] = []
    managed = await _manage()

    if not force and not _market_open():
        notes.append(f"Market closed (now {_hhmm()} IST) — open positions still managed.")
        await _persist({b: 0 for b in BOOKS}, managed, notes, 0)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes, "books": {}}

    wants, spot = await _signals(notes)
    if REQUIRE_GATE and wants:
        from app.services.option_hypotheses import confirmed_ids
        ok = await confirmed_ids()
        blocked = [w for w in wants if w[0]["strategy_id"] not in ok and w[0]["base_id"] not in ok]
        wants = [w for w in wants if w not in blocked]
        if blocked:
            notes.append(f"{len(blocked)} signal{'s' if len(blocked) > 1 else ''} not taken: no roster strategy holds "
                         "a CONFIRMED verdict in the option-hypothesis registry (paused by the 2026-10-02 gate).")
    expiry = await _weekly_expiry()
    past_cutoff = _hhmm() >= ENTRY_CUTOFF
    if past_cutoff:
        notes.append(f"Past the {ENTRY_CUTOFF} entry cutoff — no new entries.")
    if not expiry:
        notes.append("No live NIFTY expiry found.")

    opened_by_book = {b: 0 for b in BOOKS}
    if wants and not past_cutoff and expiry and spot:
        # Resolve and price each contract ONCE, shared by both books.
        contracts: dict[str, dict] = {}
        for kind in {k for _, k in wants}:
            c = await _atm(kind, spot, expiry)
            if c:
                contracts[kind] = c
        prices = await batched_ltp(
            {"NFO": [str(c["angel_token"]) for c in contracts.values()]}) if contracts else {}

        for book in BOOKS:
            free = await _free_cash(book)
            unfunded = 0
            for s, kind in wants:
                c = contracts.get(kind)
                if not c:
                    continue
                if await live_paper_positions_collection.find_one(
                        {"book": book, "strategy_id": s["strategy_id"], "status": "OPEN"}):
                    continue                                # one open position per strategy
                cost = await _open(book, s, kind, c, spot, expiry, prices, free)
                if cost is None:
                    unfunded += 1
                    continue
                free -= cost
                opened_by_book[book] += 1
            if unfunded:
                notes.append(f"{BOOK_LABELS[book]}: {unfunded} signal"
                             f"{'s' if unfunded > 1 else ''} not taken — the book had no free "
                             "cash for another lot. Higher-ranked strategies were filled first.")

    await _persist(opened_by_book, managed, notes, len(wants))
    return {"opened": sum(opened_by_book.values()), "managed": managed, "signals": len(wants),
            "notes": notes, "books": opened_by_book}


async def _open(book: str, s: dict, kind: str, c: dict, spot: float, expiry: str,
                prices: dict[str, float], free: float) -> float | None:
    """Buy one lot if the book can fund it. Returns the cost, or None if it could not."""
    prem = prices.get(str(c["angel_token"]))
    lot = int(c.get("lot_size") or 0)
    if not prem or prem <= 0 or lot <= 0:
        return None
    qty = LOTS_PER_POSITION * lot
    cost = prem * qty
    if cost > free:
        return None
    await live_paper_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "book": book,
        "strategy_id": s["strategy_id"], "strategy_name": s["name"],
        "base_id": s["base_id"], "timeframe": s["timeframe"], "rank": s["rank"],
        "underlying": UNDERLYING, "option_type": kind, "strike": c["strike"], "expiry": expiry,
        "angel_tradingsymbol": c.get("angel_tradingsymbol"), "token": str(c["angel_token"]),
        "lot_size": lot, "lots": LOTS_PER_POSITION, "qty": qty,
        "spot_at_entry": round(spot, 2),
        "entry_premium": round(prem, 2), "ltp": round(prem, 2),
        "cost": round(cost, 2), "capital_deployed": round(cost, 2),
        "target_premium": round(prem * (1 + TARGET_PCT), 2),
        "stop_premium": round(prem * (1 - STOP_PCT), 2),
        "unrealized_pnl": 0.0, "realized_pnl": None, "exit_premium": None,
        "exit_reason": None, "status": "OPEN",
        "session": _today(), "opened_at": _now(), "updated_at": _now(), "closed_at": None,
    })
    return cost


async def _manage() -> int:
    """Every open position in every book, priced in one batch."""
    pos = [p async for p in live_paper_positions_collection.find({"status": "OPEN"})]
    if not pos:
        return 0
    prices = await batched_ltp({"NFO": [p["token"] for p in pos]})
    hhmm = _hhmm()
    today = _today()
    eod = hhmm >= SQUAREOFF
    touched: set[tuple[str, str]] = set()
    updated = 0
    for p in pos:
        cur = prices.get(p["token"])
        stale = p.get("session", today) < today          # left over from a previous session
        if cur is None:
            if not (eod or stale):
                continue
            cur = 0.0
        gross = round((cur - p["entry_premium"]) * p["qty"], 2)
        pnl = gross
        reason = None
        if cur >= p["target_premium"]:
            reason = "target"
        elif cur <= p["stop_premium"]:
            reason = "stoploss"
        elif eod or stale:
            reason = "eod"
        changes = {"ltp": round(cur, 2), "unrealized_pnl": pnl, "updated_at": _now()}
        if reason:
            book = p.get("book") or DEFAULT_BOOK
            fees = option_round_trip(p["entry_premium"], cur, p["qty"], on=today)["total"] if today >= COSTS_FROM else 0.0
            pnl = round(gross - fees, 2)
            changes.update({"status": "CLOSED", "exit_premium": round(cur, 2),
                            "exit_reason": reason, "realized_pnl": pnl, "gross_pnl": gross,
                            "fees": fees, "fee_basis": "angel_rate_card" if fees else "none",
                            "unrealized_pnl": 0.0, "closed_at": _now(),
                            "closed_on": _today()})
            await live_paper_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "book": book,
                "strategy_id": p["strategy_id"], "strategy_name": p.get("strategy_name"),
                "timeframe": p.get("timeframe"), "underlying": p.get("underlying"),
                "option_type": p["option_type"], "strike": p["strike"],
                "qty": p["qty"], "lots": p.get("lots"),
                "entry_premium": p["entry_premium"], "exit_premium": round(cur, 2),
                "cost": p.get("cost"), "realized_pnl": pnl, "gross_pnl": gross, "fees": fees,
                "fee_basis": "angel_rate_card" if fees else "none", "exit_reason": reason,
                "session": p.get("session"), "opened_at": p["opened_at"], "closed_at": _now(),
            })
            touched.add((book, p["strategy_id"]))
        await live_paper_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})
        updated += 1
    for book, sid in touched:
        await _update_score(book, sid)
    return updated


async def _persist(opened: dict[str, int], managed: int, notes: list[str], signals: int) -> None:
    for book in BOOKS:
        snap = await summary(book)
        await live_paper_equity_collection.insert_one({
            "ts": _now(), "book": book, "session": _today(), "equity": snap["equity"],
            "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
            "open_positions": snap["open_positions"],
        })
    await live_paper_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"last_run_at": _now(), "last_opened": opened, "last_managed": managed,
                  "last_signals": signals, "last_notes": notes}}, upsert=True)


# ── read models ──────────────────────────────────────────────────────────────────


async def summary(book: str | None = None) -> dict:
    await _migrate()                 # a read before the first cycle must still see old rows
    book = _book(book)
    capital = BOOKS[book]
    deployed = realized = unreal = 0.0
    async for p in live_paper_positions_collection.find(
            {"book": book, "status": "OPEN"}, {"cost": 1, "unrealized_pnl": 1}):
        deployed += p.get("cost") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
    async for p in live_paper_positions_collection.find(
            {"book": book, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    closed = await live_paper_positions_collection.count_documents(
        {"book": book, "status": {"$ne": "OPEN"}})
    wins = await live_paper_positions_collection.count_documents(
        {"book": book, "status": {"$ne": "OPEN"}, "realized_pnl": {"$gt": 0}})
    st = await live_paper_state_collection.find_one({"_id": STATE_ID}) or {}
    roster = selected()
    total = realized + unreal
    last_opened = st.get("last_opened")
    return {
        "book": book, "books": list(BOOKS), "label": BOOK_LABELS[book],
        "mode": "paper", "underlying": UNDERLYING,
        "timeframes": sorted({s["timeframe"] for s in roster}),
        # `timeframe` kept for the older page, which printed a single one.
        "timeframe": "5m / 15m",
        "total_capital": capital, "per_strategy": None, "sizing": "shared_pool_one_lot",
        "strategy_count": len(roster),
        "deployed_capital": round(deployed, 2),
        "free_cash": round(capital + realized - deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
        "total_pnl": round(total, 2),
        "realized_pct": round(realized / capital * 100, 2) if capital else 0.0,
        "unrealized_pct": round(unreal / capital * 100, 2) if capital else 0.0,
        "total_pct": round(total / capital * 100, 2) if capital else 0.0,
        "equity": round(capital + total, 2),
        "open_positions": await live_paper_positions_collection.count_documents(
            {"book": book, "status": "OPEN"}),
        "closed_positions": closed, "wins": wins,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "market_open": _market_open(), "costs_charged": True, "costs_from": COSTS_FROM,
        "gate_required": REQUIRE_GATE, "paused_by_gate": REQUIRE_GATE, "selection_basis": SELECTION_BASIS,
        "entry_cutoff": ENTRY_CUTOFF, "squareoff": SQUAREOFF,
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_opened": (last_opened or {}).get(book, 0) if isinstance(last_opened, dict) else 0,
        "last_notes": st.get("last_notes", []),
    }


async def leaderboard(book: str | None = None) -> list[dict]:
    await _migrate()                 # a read before the first cycle must still see old rows
    book = _book(book)
    scores = {s["strategy_id"]: s async for s in live_paper_scores_collection.find({"book": book})}
    open_by: dict[str, dict] = {}
    async for p in live_paper_positions_collection.find(
            {"book": book, "status": "OPEN"}, {"strategy_id": 1, "unrealized_pnl": 1}):
        o = open_by.setdefault(p["strategy_id"], {"n": 0, "u": 0.0})
        o["n"] += 1
        o["u"] += p.get("unrealized_pnl") or 0.0
    rows = []
    for s in selected():
        sc = scores.get(s["strategy_id"]) or {}
        o = open_by.get(s["strategy_id"], {"n": 0, "u": 0.0})
        rows.append({**s,
                     "trades": sc.get("trades", 0) or 0,
                     "wins": sc.get("wins", 0) or 0,
                     "win_rate": sc.get("win_rate", 0.0) or 0.0,
                     "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
                     "profit_factor": sc.get("profit_factor"),
                     "expectancy": sc.get("expectancy", 0.0) or 0.0,
                     "open_positions": o["n"], "unrealized_pnl": round(o["u"], 2),
                     # No per-strategy slice in a shared pool — the whole book is available.
                     "allocated": BOOKS[book]})
    rows.sort(key=lambda r: (-r["net_pnl"], r["rank"]))
    return rows


def _ser(d: dict, ts: tuple[str, ...]) -> dict:
    d.pop("_id", None)
    for k in ts:
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def positions(status: str = "OPEN", limit: int = 300, book: str | None = None) -> list[dict]:
    await _migrate()                 # a read before the first cycle must still see old rows
    q: dict = {"book": _book(book)}
    if status:
        q["status"] = status.upper()
    return [_ser(p, ("opened_at", "updated_at", "closed_at"))
            async for p in live_paper_positions_collection.find(q).sort("opened_at", -1).limit(limit)]


async def trades(limit: int = 300, book: str | None = None) -> list[dict]:
    await _migrate()                 # a read before the first cycle must still see old rows
    return [_ser(t, ("opened_at", "closed_at"))
            async for t in live_paper_trades_collection.find({"book": _book(book)})
            .sort("closed_at", -1).limit(limit)]


async def daily_pnl(limit: int = 60, book: str | None = None) -> list[dict]:
    await _migrate()                 # a read before the first cycle must still see old rows
    rows = []
    async for r in live_paper_trades_collection.aggregate([
        {"$match": {"book": _book(book)}},
        {"$group": {"_id": "$session", "net_pnl": {"$sum": "$realized_pnl"},
                    "trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}}}},
        {"$sort": {"_id": -1}}, {"$limit": limit},
    ]):
        rows.append({"session": r["_id"], "net_pnl": round(r["net_pnl"] or 0, 2),
                     "trades": r["trades"], "wins": r["wins"],
                     "win_rate": round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0})
    return rows
