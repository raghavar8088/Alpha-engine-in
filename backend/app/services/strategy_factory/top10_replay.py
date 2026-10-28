"""Strategy Factory · Top 10: the forward record its Top-10 books copy (2026-10-27).

The owner asked for Rs 2 lakh and Rs 10 lakh paper accounts on the Strategy Factory's top 10, as on
the other desks (app.services.top10_books). Two things made the Factory different:

1. IT HAS NO RUNNING PAPER ENGINE. Nothing schedules engine.run_paper_cycle - only the page's "Run
   paper cycle" button opens or closes a position. On 27 Oct its 41 positions had all been opened
   on a Sunday evening at stale prices, and none had ever been closed. There was nothing to copy.
2. ITS BOARD GRADES EACH STRATEGY ON ITS BEST SYMBOL. A strategy is backtested on every symbol it
   has bars for (~15) and the leaderboard shows the best one; across all their symbols six of the
   board's top ten lost money. The owner chose instead the ten with the best COMBINED backtest over
   every stock and MCX contract each was tested on - net P&L, at least 100 trades (PICKS). Two that
   qualified were left out: their higher-timeframe filter reads the higher bar by its START time,
   so in the backtest it saw a 4h bar that had not finished (up to ~3 hours of future prices).

So this module runs the ten forward, bar by bar as bars close, by the SAME code as the backtest that
picked them: `step` is `backtest()`'s loop body. On each newly closed bar k:
   - an open position is managed on bar k - stop first on an ambiguous bar, then target, then the
     backtest's max hold (DEFAULT_MAX_HOLD bars) at bar k's close; the exit pays 5 bp of slippage;
   - if flat, the strategy is evaluated on the completed bar k-1, and a signal fills at bar k's
     open plus 5 bp, its stop and target re-anchored to the fill.
One position at a time per (strategy, symbol), as backtested. tests/strategy_factory/
verify_top10_replay.py replays real series through `step` and checks it against backtest().

WHERE THEY TRADE. Each strategy on the symbols it was backtested on, frozen at the first cycle -
stocks and MCX. An index cannot be bought, so index symbols are left out. Stock SHORTS are recorded
here (they are the strategy's own trades) but the books are never offered them: a cash account
cannot hold a short overnight.

DATA. MCX bars arrive through the session, so MCX trades appear as they happen. Stock bars are
written once a day after the close (~16:30 IST), so stock trades appear then, at the prices the
bars show; each decision still sees only the bars up to the one it is made on.

MCX ROLLS. commodity_bars is one continuous series that moves to the next contract when the old one
enters its exit window. A position is closed at the open of the last trading day before that window
("contract_roll"), while the series is still its contract, and no entry is made closer than that.

Read-only towards every other desk: it writes only its own sf_top10_* collections.
"""

from __future__ import annotations

import asyncio
import logging
import os
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from app.core.db import db, sf_backtests_collection

logger = logging.getLogger("sf_top10_replay")

IST = timezone(timedelta(hours=5, minutes=30))
TRADES = db["sf_top10_trades"]       # the replay's own trades: what the books copy
SERIES = db["sf_top10_series"]       # per (strategy, market, symbol): last bar replayed, open trade
STATE = db["sf_top10_state"]         # the frozen scope, run stamps

SOURCES = ("equity", "commodity")    # an index cannot be bought
SLIPPAGE_BPS = float(os.getenv("SF_SLIPPAGE_BPS", "5"))     # the Factory's own (engine.SLIPPAGE_BPS)
BAR_LIMIT = int(os.getenv("SF_TOP10_BARS", "600"))          # what the Factory's paper scan reads
TICK_SECONDS = int(os.getenv("SF_TOP10_TICK_SECONDS", "120"))
EQUITY_AFTER = time(16, 45)          # stock bars are written ~16:30 IST
EQUITY_EVERY = timedelta(hours=3)
ENABLED = os.getenv("SF_TOP10_ENABLED", "1").lower() not in ("0", "false", "")

# The mini of each big MCX contract, and the commodity a contract belongs to (one position per
# commodity in a book: CRUDEOIL and CRUDEOILM are one bet).
MINI = {"GOLD": "GOLDM", "SILVER": "SILVERM", "CRUDEOIL": "CRUDEOILM", "NATURALGAS": "NATGASMINI"}
COMMODITY_OF = {**{m: b for b, m in MINI.items()}, **{b: b for b in MINI}}

# THE TEN, frozen: the best combined backtest over every stock and MCX contract each was tested on
# (sf_backtests, read 27 Oct 2026 ~23:35 IST): (strategy_id, rank, trades, net Rs, profit factor,
# symbols net positive, symbols with trades). Ranked on net P&L; at least 100 trades.
PICKED_AT = "2026-10-27T23:35:00+05:30"
PICKS: tuple[tuple[str, int, int, float, float, int, int], ...] = (
    ("SF0006", 1, 187, 352997.0, 1.31, 10, 14),     # Head & Shoulders · 1h
    ("SF0119", 2, 236, 322344.0, 1.24, 9, 14),      # Hammer / Shooting Star · 4h
    ("SF0277", 3, 258, 240029.0, 1.15, 8, 12),      # EMA Ribbon Compression · 1h
    ("SF0410", 4, 142, 227103.0, 1.33, 7, 12),      # ADX / DI Cross · 30m
    ("SF0230", 5, 411, 220529.0, 1.09, 7, 14),      # Keltner Breakout · 1h
    ("SF0420", 6, 123, 197268.0, 1.36, 8, 12),      # Supertrend Flip · 1h
    ("SF0183", 7, 183, 133901.0, 1.11, 8, 14),      # Three Soldiers / Crows · 4h
    ("SF0200", 8, 266, 133455.0, 1.07, 69, 149),    # Pin Bar at Extreme · 1d
    ("SF0022", 9, 400, 112348.0, 1.04, 10, 14),     # Triple Top / Bottom · 1h
    ("SF0298", 10, 192, 105556.0, 1.11, 8, 12),     # Break of Structure · 15m
)
ROSTER: tuple[str, ...] = tuple(p[0] for p in PICKS)


def _utc(dt: datetime) -> datetime:
    """Naive UTC, as Mongo returns it and the books compare it."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _ist(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST)


# -- bars -------------------------------------------------------------------------------------


def bar_end(bar, tf: str, source: str) -> datetime:
    """When a bar stops changing: its start + its length, cut at the session's close."""
    from .sources import TF_MINUTES
    if source == "commodity":
        from app.services.commodity_bars import bar_end as cmd_end
        return cmd_end(bar, TF_MINUTES[tf])
    t = _ist(bar.ts)
    close = datetime.combine(t.date(), time(15, 30), IST)
    return close if tf == "1d" else min(t + timedelta(minutes=TF_MINUTES[tf]), close)


async def closed_bars(source: str, symbol: str, tf: str, now: datetime | None = None) -> list:
    """The series' CLOSED bars, oldest first - never the bar still forming."""
    now = now or datetime.now(IST)
    if source == "commodity":
        # The commodity store refuses a decision series that crosses a contract join it could not
        # back-adjust ([] - fail closed). A 600-bar 4h window needs ~2,400 hourly bars and does;
        # 300 (daily) and 200 (4h) were clean on every contract on 28 Oct and still cover every
        # pick's warm-up (115 bars; 215 for the daily one). No clean window: the series waits.
        from app.services.commodity_bars import load_bars
        for limit in (BAR_LIMIT, 300, 200):
            bars = await load_bars(symbol, tf, limit, closed_only=True)
            if bars:
                return bars
        return []
    from .sources import equity_load_bars
    bars = await equity_load_bars(symbol, tf, BAR_LIMIT)
    return [b for b in bars if bar_end(b, tf, source) <= now]


# -- the backtest's loop, one bar at a time ----------------------------------------------------


def step(strat, bars: list, k: int, pos: dict | None, *, symbol: str, exchange: str,
         htf_bars: list | None = None, regime=None) -> tuple[dict | None, dict | None]:
    """backtest()'s loop body for its iteration i = k - 1 (bar k is the one just closed).

    Returns (position after bar k, the trade it closed on bar k or None). A position opened here
    carries `new: True` and fills at bar k's open."""
    from .backtest import DEFAULT_MAX_HOLD
    from .primitives import DEFAULT_CAPITAL, DEFAULT_RISK_PCT, Levels, position_size, slippage_price
    from .signals import evaluate

    nxt = bars[k]
    closed = None
    if pos is not None:
        pos = {**pos, "new": False, "bars_held": pos["bars_held"] + 1}
        long = pos["side"] == "BUY"
        hit_stop = nxt.low <= pos["stop"] if long else nxt.high >= pos["stop"]
        hit_target = nxt.high >= pos["target"] if long else nxt.low <= pos["target"]
        reason = None
        if hit_stop:                                   # ambiguous bar: the stop came first
            exit_px, reason = pos["stop"], "stoploss"
        elif hit_target:
            exit_px, reason = pos["target"], "target"
        elif pos["bars_held"] >= pos["max_hold"]:
            exit_px, reason = nxt.close, "max_hold"
        if reason:
            closed = {**pos, "exit": slippage_price(exit_px, SLIPPAGE_BPS, adverse_for_buy=not long),
                      "exit_reason": reason, "exit_k": k}
            pos = None
        else:
            pos["ltp"] = nxt.close
    if pos is not None:
        return pos, closed

    htf_slice = None
    if htf_bars:
        cut = bisect_right([b.ts for b in htf_bars], bars[k - 1].ts)
        htf_slice = htf_bars[:cut] or None
    sig, _rej = evaluate(strat, bars[:k], symbol, exchange, htf_slice, regime=regime)
    if sig is None:
        return None, closed
    long = sig.side == "BUY"
    fill = slippage_price(nxt.open, SLIPPAGE_BPS, adverse_for_buy=long)
    shift = fill - sig.entry
    stop, target = sig.stop + shift, sig.target + shift
    risk = abs(fill - stop)
    if risk <= 0:
        return None, closed
    levels = Levels(fill, stop, target, risk, abs(target - fill), abs(target - fill) / risk,
                    sig.stop_basis, sig.target_basis)
    if position_size(DEFAULT_CAPITAL, DEFAULT_CAPITAL, levels, risk_pct=DEFAULT_RISK_PCT) < 1:
        return None, closed                            # the backtest's "sizing" rejection
    return {"new": True, "side": sig.side, "entry": fill, "signal_price": sig.entry, "stop": stop,
            "target": target, "risk": risk, "r_multiple": round(abs(target - fill) / risk, 3),
            "pattern": sig.pattern, "bars_held": 0, "entry_k": k, "ltp": nxt.close,
            "max_hold": DEFAULT_MAX_HOLD.get(strat.timeframe, 60)}, closed


# -- MCX contracts ------------------------------------------------------------------------------


async def _contracts() -> dict[str, dict]:
    from app.services.commodity_bars import front_month_universe
    try:
        return await front_month_universe()
    except Exception:  # noqa: BLE001 - without contracts no MCX entry is made
        logger.warning("[sf_top10] front-month universe unavailable", exc_info=True)
        return {}


def _days_left(expiry: str | None, on: date) -> int | None:
    from tradingai_shared import mcx_calendar as mcal
    return mcal.trading_days_to(expiry, on) if expiry else None


def _too_near_roll(underlying: str, expiry: str | None, on: date, margin: int) -> bool:
    """True from `margin` trading days before the contract's exit window."""
    from app.services.mcx_market import exit_days
    left = _days_left(expiry, on)
    return left is None or left <= exit_days(underlying) + margin


# -- one series ---------------------------------------------------------------------------------


def _trade_doc(strat, source: str, symbol: str, pos: dict, bars: list, contract: dict | None,
               trade_contract: dict | None) -> dict:
    entry_bar = bars[pos["entry_k"]]
    trade_symbol = MINI.get(symbol, symbol) if source == "commodity" else symbol
    return {
        "position_id": uuid4().hex[:12], "strategy_id": strat.strategy_id, "strategy_name": strat.name,
        "family": strat.family, "timeframe": strat.timeframe, "source": source,
        "market": "mcx" if source == "commodity" else "stocks",
        "symbol": symbol, "trade_symbol": trade_symbol,
        "commodity": COMMODITY_OF.get(symbol, symbol) if source == "commodity" else None,
        "side": pos["side"], "signal_price": round(pos["signal_price"], 4),
        "entry_price": round(pos["entry"], 4), "stop": round(pos["stop"], 4),
        "target": round(pos["target"], 4), "risk": round(pos["risk"], 4),
        "r_multiple": pos["r_multiple"], "pattern": pos["pattern"], "max_hold": pos["max_hold"],
        "bars_held": 0, "ltp": round(pos["ltp"], 4), "status": "OPEN",
        "signal_bar_ts": _utc(bars[pos["entry_k"] - 1].ts), "entry_bar_ts": _utc(entry_bar.ts),
        "opened_at": _utc(entry_bar.ts), "opened_on": _ist(entry_bar.ts).date().isoformat(),
        "contract": {k: (contract or {}).get(k) for k in ("symbol", "expiry", "security_id")} if contract else None,
        "trade_contract": {k: (trade_contract or {}).get(k) for k in ("symbol", "expiry", "security_id")}
        if trade_contract else None,
        "exit_price": None, "exit_reason": None, "closed_at": None, "closed_on": None,
        "updated_at": datetime.now(timezone.utc),
    }


def _pos_of(doc: dict) -> dict:
    return {"new": False, "side": doc["side"], "entry": doc["entry_price"],
            "signal_price": doc.get("signal_price"), "stop": doc["stop"], "target": doc["target"],
            "risk": doc["risk"], "r_multiple": doc.get("r_multiple"), "pattern": doc.get("pattern"),
            "bars_held": int(doc.get("bars_held") or 0), "max_hold": int(doc["max_hold"]),
            "ltp": doc.get("ltp"), "position_id": doc["position_id"], "doc": doc}


async def _close(doc: dict, exit_px: float, reason: str, bar, tf: str, source: str, bars_held: int) -> None:
    end = bar_end(bar, tf, source)
    await TRADES.update_one({"position_id": doc["position_id"], "status": "OPEN"}, {"$set": {
        "status": "CLOSED", "exit_price": round(exit_px, 4), "exit_reason": reason,
        "exit_bar_ts": _utc(bar.ts), "closed_at": _utc(end), "closed_on": _ist(end).date().isoformat(),
        "bars_held": bars_held, "ltp": round(exit_px, 4), "updated_at": datetime.now(timezone.utc)}})


async def advance(strat, source: str, symbol: str, bars: list, htf_bars: list | None,
                  contracts: dict[str, dict]) -> dict:
    """Replay every bar of one series that closed since the last look."""
    from .primitives import slippage_price
    n = {"bars": 0, "opened": 0, "closed": 0}
    if len(bars) < 2:
        return n
    key = f"{strat.strategy_id}|{source}|{symbol}"
    st = await SERIES.find_one({"_id": key})
    if st is None:
        # A series starts at its first look: nothing before it is replayed into the record.
        await SERIES.update_one({"_id": key}, {"$setOnInsert": {
            "strategy_id": strat.strategy_id, "source": source, "symbol": symbol, "tf": strat.timeframe,
            "last_ts": _utc(bars[-1].ts), "open_id": None, "started_at": datetime.now(timezone.utc)}},
            upsert=True)
        return n
    last = st["last_ts"]
    todo = [k for k in range(1, len(bars)) if _utc(bars[k].ts) > last]
    if not todo:
        return n
    doc = await TRADES.find_one({"position_id": st["open_id"], "status": "OPEN"}) if st.get("open_id") else None
    pos = _pos_of(doc) if doc else None
    exchange = "MCX" if source == "commodity" else "NSE"
    for k in todo:
        bar = bars[k]
        n["bars"] += 1
        # An MCX position leaves before its contract's exit window, while the series is still it.
        if pos is not None and source == "commodity":
            d = pos["doc"]
            for c, u in ((d.get("contract"), symbol), (d.get("trade_contract"), d.get("trade_symbol"))):
                if c and c.get("expiry") and _too_near_roll(u, c["expiry"], _ist(bar.ts).date(), 1):
                    long = pos["side"] == "BUY"
                    await _close(d, slippage_price(bar.open, SLIPPAGE_BPS, adverse_for_buy=not long),
                                 "contract_roll", bar, strat.timeframe, source, pos["bars_held"])
                    n["closed"] += 1
                    pos = None
                    break
        new_pos, closed = step(strat, bars, k, pos, symbol=symbol, exchange=exchange, htf_bars=htf_bars)
        if closed is not None:
            await _close(closed["doc"], closed["exit"], closed["exit_reason"], bar, strat.timeframe,
                         source, closed["bars_held"])
            n["closed"] += 1
        if new_pos is not None and new_pos.get("new"):
            contract = trade_contract = None
            if source == "commodity":
                contract = contracts.get(symbol)
                trade_contract = contracts.get(MINI.get(symbol, symbol))
                on = _ist(bar.ts).date()
                if (contract is None or trade_contract is None
                        or _too_near_roll(symbol, contract.get("expiry"), on, 2)
                        or _too_near_roll(MINI.get(symbol, symbol), trade_contract.get("expiry"), on, 2)):
                    new_pos = None                       # too close to a roll to hold to an exit
            if new_pos is not None:
                tdoc = _trade_doc(strat, source, symbol, new_pos, bars, contract, trade_contract)
                await TRADES.insert_one(tdoc)
                new_pos = _pos_of(tdoc)
                n["opened"] += 1
        elif new_pos is not None:
            await TRADES.update_one({"position_id": new_pos["doc"]["position_id"], "status": "OPEN"}, {"$set": {
                "bars_held": new_pos["bars_held"], "ltp": round(new_pos["ltp"], 4),
                "updated_at": datetime.now(timezone.utc)}})
        pos = new_pos
    await SERIES.update_one({"_id": key}, {"$set": {
        "last_ts": _utc(bars[todo[-1]].ts), "open_id": pos["doc"]["position_id"] if pos else None,
        "updated_at": datetime.now(timezone.utc)}})
    return n


# -- the scope and the cycle --------------------------------------------------------------------


async def scope() -> list[tuple[str, str, str]]:
    """(strategy, market, symbol) for each symbol a pick was backtested on - frozen at the first look."""
    doc = await STATE.find_one({"_id": "scope"})
    if doc is None:
        found = set()
        async for r in sf_backtests_collection.find(
                {"strategy_id": {"$in": list(ROSTER)}, "source": {"$in": list(SOURCES)}},
                {"strategy_id": 1, "source": 1, "symbol": 1}):
            if r.get("symbol"):
                found.add((r["strategy_id"], r["source"], r["symbol"]))
        await STATE.update_one({"_id": "scope"}, {"$setOnInsert": {
            "series": sorted(found), "frozen_at": datetime.now(timezone.utc), "picked_at": PICKED_AT}},
            upsert=True)
        doc = await STATE.find_one({"_id": "scope"})
    return [tuple(x) for x in doc.get("series") or []]


# The newest stored bar of each MCX (symbol, stored timeframe) at the last cycle. A series is
# replayed only when the timeframe it is built from has moved - decided once per cycle, so every
# strategy on the same series sees the same answer, and recorded only after the cycle.
_seen: dict[tuple[str, str], object] = {}


async def _latest_stored(symbol: str, tf: str):
    from app.services.commodity_bars import commodity_bars_collection
    from .sources import DERIVED_FROM
    d = await commodity_bars_collection.find_one({"symbol": symbol, "timeframe": DERIVED_FROM.get(tf, tf)},
                                                 {"ts": 1}, sort=[("ts", -1)])
    return d.get("ts") if d else None


async def cycle(*, equity: bool | None = None, now: datetime | None = None) -> dict:
    """One look at every series that may have new closed bars."""
    from .catalog import FACTORY_BY_ID
    now = now or datetime.now(IST)
    if equity is None:
        st = await STATE.find_one({"_id": "equity_run"}) or {}
        last = st.get("at")
        equity = now.time() >= EQUITY_AFTER and (last is None or now - _ist(last) >= EQUITY_EVERY)
    from .sources import DERIVED_FROM
    contracts = await _contracts()
    totals = {"series": 0, "bars": 0, "opened": 0, "closed": 0}
    cache: dict[tuple[str, str, str], list] = {}
    latest: dict[tuple[str, str], object] = {}
    for sid, source, symbol in await scope():
        strat = FACTORY_BY_ID.get(sid)
        if strat is None or (source == "equity" and not equity):
            continue
        if source == "commodity":
            base = (symbol, DERIVED_FROM.get(strat.timeframe, strat.timeframe))
            if base not in latest:
                latest[base] = await _latest_stored(symbol, strat.timeframe)
            if latest[base] is not None and _seen.get(base) == latest[base]:
                continue
        try:
            for tf in {strat.timeframe, strat.htf} - {None}:
                if (source, symbol, tf) not in cache:
                    cache[(source, symbol, tf)] = await closed_bars(source, symbol, tf, now)
            bars = cache[(source, symbol, strat.timeframe)]
            htf = cache.get((source, symbol, strat.htf)) if strat.htf else None
            got = await advance(strat, source, symbol, bars, htf, contracts)
        except Exception:  # noqa: BLE001 - one series must not stop the others
            logger.warning("[sf_top10] %s %s %s failed", sid, source, symbol, exc_info=True)
            continue
        totals["series"] += 1
        for k in ("bars", "opened", "closed"):
            totals[k] += got[k]
    _seen.update(latest)
    if equity:
        await STATE.update_one({"_id": "equity_run"}, {"$set": {"at": _utc(now)}}, upsert=True)
    return totals


async def ensure_indexes() -> None:
    try:
        await TRADES.create_index("position_id", unique=True, name="sf_top10_pid")
        await TRADES.create_index([("strategy_id", 1), ("opened_at", 1)], name="sf_top10_sid_opened")
    except Exception:  # noqa: BLE001 - an index must never stop the replay
        logger.warning("[sf_top10] index creation skipped", exc_info=True)


async def loop() -> None:
    """Every two minutes; MCX series when their bars move, stock series after the close."""
    from app.services.desk_switches import is_on
    await asyncio.sleep(45)
    await ensure_indexes()
    while True:
        if ENABLED:
            try:
                if await is_on("strategy_factory"):
                    out = await cycle()
                    if out["opened"] or out["closed"]:
                        logger.info("[sf_top10] %s", out)
            except Exception:  # noqa: BLE001
                logger.warning("[sf_top10] cycle failed", exc_info=True)
        await asyncio.sleep(TICK_SECONDS)


# -- what the Top-10 books read (app.services.top10_books, desk "strategy-factory") ---------------


def parent(t: dict) -> dict | None:
    """One replay trade as a book sees it. A stock short is not offered: a cash account cannot
    hold it overnight. MCX goes through the mini where there is one, a lot costing the broker's
    measured margin; a stock costs its price, whole shares."""
    if t.get("market") == "stocks" and t.get("side") != "BUY":
        return None
    closed = t.get("status") == "CLOSED" and t.get("exit_price") is not None
    px_entry = float(t["entry_price"])
    base = {
        "position_id": t["position_id"], "key": t["strategy_id"], "strategy_id": t["strategy_id"],
        "strategy_name": t.get("strategy_name") or t["strategy_id"], "side": t["side"],
        "opened_at": t["opened_at"], "opened_on": t.get("opened_on"),
        "closed_at": t.get("closed_at") if closed else None, "closed_on": t.get("closed_on") if closed else None,
        "status": "CLOSED" if closed else "OPEN", "exit_reason": t.get("exit_reason"),
        "px_entry": px_entry, "px_exit": float(t["exit_price"]) if closed else None, "px_ltp": t.get("ltp"),
        "market": t.get("market"),
    }
    if t.get("market") == "mcx":
        from app.services.commodity_positions import margin_pct_for, multiplier
        sym = t.get("trade_symbol") or t["symbol"]
        try:
            mult, rate = int(multiplier(sym) or 0), float(margin_pct_for(sym))
        except Exception:  # noqa: BLE001 - a contract without a spec is not offered
            return None
        if mult <= 0 or rate <= 0:
            return None
        base.update({"symbol": t.get("commodity") or COMMODITY_OF.get(t["symbol"], t["symbol"]),
                     "label": sym, "lot_size": mult, "multiplier": mult,
                     "entry_price": round(rate * px_entry * mult, 2),
                     "exit_price": base["px_exit"] if closed else None,
                     "expiry": (t.get("trade_contract") or {}).get("expiry")})
        return base
    base.update({"symbol": t["symbol"], "label": t["symbol"], "lot_size": 1, "multiplier": 1,
                 "entry_price": px_entry, "exit_price": base["px_exit"] if closed else None,
                 "expiry": None})
    return base


async def load_parents(since: datetime, keys: set, pointed: list) -> list[dict]:
    q = {"strategy_id": {"$in": list(keys)},
         "$or": [{"opened_at": {"$gte": since}}, {"position_id": {"$in": pointed}}]}
    out = []
    async for t in TRADES.find(q):
        p = parent(t)
        if p is not None:
            out.append(p)
    return out


def parent_pnl(p: dict, lots: int) -> tuple[float, float, dict]:
    """(gross, fees, fee parts) for `lots` - MCX lots on Angel's MCX card, or shares on Angel's
    equity card (delivery when held overnight)."""
    sign = 1 if p["side"] == "BUY" else -1
    if p.get("market") == "mcx":
        from app.services.mcx_risk import real_trade
        on = date.fromisoformat(p["closed_on"]) if p.get("closed_on") else None
        r = real_trade(p["label"], p["side"], p["px_entry"], p["px_exit"], on=on, lots=lots)
        if r:
            return float(r["gross"]), float(r["fees"]), {"mcx_charges": float(r["fees"])}
        return round(sign * (p["px_exit"] - p["px_entry"]) * p["multiplier"] * lots, 2), 0.0, {}
    from app.services.angel_fees import product_for, round_trip
    held = 0
    try:
        held = (date.fromisoformat(p["closed_on"]) - date.fromisoformat(p["opened_on"])).days
    except (KeyError, TypeError, ValueError):
        held = 0
    fb = round_trip(p["px_entry"], p["px_exit"], lots, side=p["side"], product=product_for(None, held))
    gross = round(sign * (p["px_exit"] - p["px_entry"]) * lots, 2)
    return gross, float(fb.total), {k: v for k, v in fb.as_dict().items() if isinstance(v, (int, float)) and k != "total"}


def parent_mark(p: dict, lots: int) -> float | None:
    if p.get("px_ltp") is None:
        return None
    sign = 1 if p["side"] == "BUY" else -1
    return round(sign * (float(p["px_ltp"]) - p["px_entry"]) * int(p.get("multiplier") or 1) * lots, 2)
