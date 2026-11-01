"""Crypto Trading's live paper desk: every ELIGIBLE strategy-cryptocurrency pair, traded on the
venue's live data, each on its own $10,000 account. Paper only - nothing here reaches a broker.

THE CYCLE - once a minute, SETTLE_S seconds past the minute so the venue has finalised the bar
that just closed:
  1. bars     each series an eligible pair needs (its coin x timeframe, a Factory pair's higher
              timeframe, the benchmark) is read again only once its next bar can have closed; the
              1-minute bars of every coin with an open position are read every cycle - they are what
              stops and targets are checked against (after a restart, back to the oldest unchecked one).
  2. manage   every open position, on each 1-minute bar since it was last checked: funding at each
              exchange it is held through, liquidation, then the stop and the target by the replay's
              own rule (`backtest.exit_on_bar`: the stop first on a bar touching both, a bar opening
              through a level fills at that open); a Factory position's hold limit in bars of its
              own timeframe; a Strategies-module position's own EXIT / reverse signals.
  3. decide   each eligible pair on a bar of its timeframe that has JUST closed (within FRESH_S): a
              Factory pair only while flat - its `evaluate` on the latest 600 bars, CLOSED
              higher-timeframe bars only, exactly as replayed; a Strategies-module pair on every bar,
              by one instance that keeps its own state as it does in its replay (warmed on the held
              bars after a restart, so a position opened before it is usually known to it again).
  4. fill     the "next bar's open" is now: the average price of walking the venue's L2 book for the
              order's size, never better than mid +/- the coin's slippage (the backtest's charge); the
              taker fee + 18% GST on each side. Accounts are independent: each walks the same book.
  5. mark     open positions at the venue's mark price; one desk equity point an hour.

RISK LIMITS, PER ACCOUNT: one position at a time (no pyramiding); sizing by its library (the Factory:
1% of the account at risk, capped at 1x notional; the Strategies module: its RiskEngine, the whole
account at 1x); leverage 1x, so margin = notional, and the liquidation price is computed from the
venue's maintenance margin (at 1x a long cannot be liquidated short of a ~99.5% fall, a short only
on a ~99.5% rise); -3% in a UTC day stops the account's entries to the next UTC day; equity at half
its capital stops them until a reset. Open positions are always managed to their exit.

CONTROLS. running | paused | stopped (desk-wide, ct_state). Paused or stopped - or Main Control OFF
(key "crypto_trading") - means no new entries; open positions are still managed, and the
Strategies-module instances still see every bar so their state stays true. Reset is explicit (a typed
phrase): every position and signal is archived, then every account goes back to $10,000 and the desk
to `stopped`. Backtests, grades and the universe are untouched by a reset.

WHAT THE LIVE DESK DOES DIFFERENTLY FROM THE BACKTEST, STATED. Stops and targets are watched on
1-minute bars (the replay sees only its own timeframe's bars, so on a bar touching both it must assume
the stop; live, the minute bars usually say which came first). A signal on a bar that closed while
the desk was not running is missed, not back-filled. The two account limits above exist only live.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from datetime import datetime, timedelta
from uuid import uuid4

from anyio import to_thread
from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError

from app.services.gold_fills import funding_cost, funding_exchanges

from . import delta, store
from .adapters import FBar, Contract, factory_bars, fee, rate_at, sm_bars
from .backtest import closed_htf, exit_on_bar, no_trade_pct
from .config import (
    ACCOUNT_CAPITAL_USD, BENCHMARK_STRATEGIES, BENCHMARK_SYMBOL, DAILY_LOSS_PCT, DERIVED_FROM, EVAL_WINDOW,
    HTF_WINDOW, MAX_DRAWDOWN_PCT, MAX_NO_TRADE_BAR_PCT, MAX_NOTIONAL_PCT, NSE_CLOCK_STRATEGIES, RISK_PCT,
    TF_SECONDS, UTC,
)

logger = logging.getLogger("crypto_trading")

SWITCH = "crypto_trading"             # Main Control key
ENABLED = os.getenv("CRYPTO_TRADING_ENABLED", "1").lower() not in ("0", "false", "")
STATE_ID = "engine"
LEASE_ID = "lease"
TICK_S = 60
SETTLE_S = 8                          # seconds past a bar boundary before that bar is read
FRESH_S = 150                         # a bar that closed longer ago than this is history, not a signal
KEEP_BARS = EVAL_WINDOW + 20          # closed bars held per series
MANAGE_BARS = 240                     # 1-minute bars held per coin with an open position
MAX_BACKLOG_MIN = 3 * 1440            # after a long stop, 1-minute bars are read back at most this far
EQUITY_EVERY_S = 3600
BOOK_DEPTH = 50
LEVERAGE = 1.0
DEFAULT_MM_PCT = 0.5                  # maintenance margin when the product spec gives none
RESET_PHRASE = "RESET CRYPTO TRADING"
SIGNAL_TTL = timedelta(days=14)
LEASE_S = 150                         # a second worker (or an overlapping deploy) never runs a cycle too
_HOLDER = uuid4().hex[:10]

# -- in-memory series and strategy state (rebuilt from the venue after a restart) -------------------
_rows: dict[tuple[str, str], list[list]] = {}      # (symbol, tf) -> closed bars, oldest first, coin prices
_due: dict[tuple[str, str], float] = {}            # (symbol, tf) -> epoch at which a newer bar can exist
_sm: dict[str, dict] = {}                          # pair_id -> {"inst", "warm"}
_ctx: dict[tuple, dict] = {}                       # (symbol, tf, unit, nse, max_bars, bench) -> {"ctx", "through"}
_specs: dict = {"at": 0.0, "mm": {}}               # maintenance margin % per symbol, from the product list
_lock = asyncio.Lock()
_indexed = False


def _now() -> datetime:
    return datetime.now(UTC)


def _day(t: datetime | None = None) -> str:
    return (t or _now()).astimezone(UTC).date().isoformat()


def _latest_open(now: float, tf: str) -> int:
    """Open time of the newest bar of `tf` that has CLOSED by `now`."""
    step = TF_SECONDS[tf]
    return (int(now) // step - 1) * step


# -- state and controls --------------------------------------------------------------------------------


async def state() -> dict:
    return await store.STATE.find_one({"_id": STATE_ID}) or {"_id": STATE_ID, "status": "stopped"}


async def _lease() -> bool:
    """Hold the cycle lease: only one process runs the desk at a time."""
    now = _now()
    try:
        doc = await store.STATE.find_one_and_update(
            {"_id": LEASE_ID, "$or": [{"holder": _HOLDER}, {"until": {"$lt": now}}]},
            {"$set": {"holder": _HOLDER, "until": now + timedelta(seconds=LEASE_S)}}, upsert=True,
            return_document=True)
        return bool(doc and doc.get("holder") == _HOLDER)
    except DuplicateKeyError:          # another process holds an unexpired lease
        return False


async def control(action: str, by: str = "") -> dict:
    """start (from stopped), pause (from running), resume (from paused)."""
    allowed = {"start": ("stopped",), "pause": ("running",), "resume": ("paused",)}
    if action not in allowed:
        raise ValueError(f"unknown action {action!r}: start | pause | resume")
    async with _lock:
        st = await state()
        if st.get("status", "stopped") not in allowed[action]:
            raise ValueError(f"cannot {action} a desk that is {st.get('status', 'stopped')}")
        new = "paused" if action == "pause" else "running"
        await store.STATE.update_one({"_id": STATE_ID}, {"$set": {
            "status": new, "since": _now(), "by": by, "last_action": action}}, upsert=True)
    logger.warning("[crypto_trading] desk %s -> %s (%s)", action, new, by or "?")
    return await state()


def fresh_account_fields(reset_id: str | None = None) -> dict:
    return {"cash": ACCOUNT_CAPITAL_USD, "equity": ACCOUNT_CAPITAL_USD, "unrealized_pnl": 0.0, "realized_pnl": 0.0,
            "fees": 0.0, "funding": 0.0, "trades": 0, "wins": 0, "losses": 0, "gross_profit": 0.0,
            "gross_loss": 0.0, "peak_equity": ACCOUNT_CAPITAL_USD, "max_drawdown_pct": 0.0, "day": None,
            "day_start_equity": ACCOUNT_CAPITAL_USD, "halt": None, "open_position_id": None,
            "last_signal_at": None, "last_trade_at": None, "reset_id": reset_id, "reset_at": _now()}


async def reset(confirm: str, by: str = "") -> dict:
    """Archive every position and signal, put every account back to $10,000, stop the desk."""
    if (confirm or "").strip() != RESET_PHRASE:
        raise ValueError(f'type "{RESET_PHRASE}" to reset')
    async with _lock:
        rid = _now().strftime("%Y%m%dT%H%M%SZ")
        n_pos = await store.POSITIONS.count_documents({})
        if n_pos:
            await store.POSITIONS.aggregate([{"$addFields": {"archived_reset_id": rid}},
                                             {"$merge": {"into": "ct_archive_positions", "on": "_id"}}]).to_list(None)
        await store.ACCOUNTS.aggregate([
            {"$match": {"trades": {"$gt": 0}}},
            {"$project": {"_id": {"$concat": ["$_id", "#", rid]}, "pair_id": "$_id", "reset_id": rid,
                          "cash": 1, "realized_pnl": 1, "fees": 1, "funding": 1, "trades": 1, "wins": 1,
                          "losses": 1, "max_drawdown_pct": 1, "since": "$reset_at"}},
            {"$merge": {"into": "ct_archive_accounts", "on": "_id"}}]).to_list(None)
        await store.POSITIONS.delete_many({})
        await store.SIGNALS.delete_many({})
        await store.EQUITY.delete_many({})
        await store.ACCOUNTS.update_many({}, {"$set": fresh_account_fields(rid)})
        await store.STATE.update_one({"_id": STATE_ID}, {"$set": {
            "status": "stopped", "since": _now(), "by": by, "last_action": "reset", "reset_id": rid,
            "last_reset": {"at": _now(), "by": by, "positions_archived": n_pos}}}, upsert=True)
        _sm.clear()
        _ctx.clear()
    logger.warning("[crypto_trading] RESET %s by %s: %d positions archived", rid, by or "?", n_pos)
    return await state()


# -- the venue's data -------------------------------------------------------------------------------------


def _needed(pairs: list[dict], open_pos: list[dict], now: float) -> dict[tuple[str, str], int]:
    """Series -> closed bars to hold. The 1-minute series of a coin with an open position reaches back
    to the oldest minute not yet checked, so a stop is never skipped across a restart."""
    need: dict[tuple[str, str], int] = {}

    def want(sym: str, tf: str, n: int) -> None:
        if tf in DERIVED_FROM:
            parent = DERIVED_FROM[tf]
            want(sym, parent, (n + 2) * (TF_SECONDS[tf] // TF_SECONDS[parent]))
        need[(sym, tf)] = max(need.get((sym, tf), 0), n)

    for p in pairs:
        want(p["symbol"], p["timeframe"], KEEP_BARS)
        if p.get("htf"):
            want(p["symbol"], p["htf"], HTF_WINDOW + 20)
        if p["base_id"] in BENCHMARK_STRATEGIES:
            want(BENCHMARK_SYMBOL, p["timeframe"], KEEP_BARS)
    latest = _latest_open(now, "1m")
    for d in open_pos:
        back = (latest - int(d.get("checked_through") or latest)) // 60 + 5
        want(d["symbol"], "1m", min(max(MANAGE_BARS, back), MAX_BACKLOG_MIN))
    return need


def _refresh(need: dict[tuple[str, str], int], now: float) -> set[tuple[str, str]]:
    """Read each due series from the venue (blocking - run in a thread). Returns the series that
    gained a closed bar, derived ones included."""
    grown: set[tuple[str, str]] = set()
    for key in [k for k in _rows if k not in need]:
        _rows.pop(key, None)
        _due.pop(key, None)
    for (sym, tf), n in sorted(need.items()):
        if tf in DERIVED_FROM:
            continue
        key = (sym, tf)
        have = _rows.get(key) or []
        if now < _due.get(key, 0) and len(have) >= n:
            continue
        step = TF_SECONDS[tf]
        latest = _latest_open(now, tf)
        # Re-read the newest held bar too: the venue may revise a bar for a few seconds after it closes.
        start = have[-1][0] if len(have) >= n else latest - (n + 5) * step
        try:
            rows = delta.candles(sym, tf, start, latest)
        except Exception as exc:  # noqa: BLE001 - a missed read is retried next cycle, never invented
            logger.warning("[crypto_trading] %s %s candles failed: %s", sym, tf, str(exc)[:160])
            _due[key] = now + 30
            continue
        before = have[-1][0] if have else None
        merged = {r[0]: r for r in have}
        merged.update({r[0]: r for r in rows})
        out = [merged[k] for k in sorted(merged)][-n:]
        _rows[key] = out
        if out and (before is None or out[-1][0] > before):
            grown.add(key)
        _due[key] = (latest + 2 * step + SETTLE_S) if out and out[-1][0] >= latest else now + 15
    for (sym, tf), n in need.items():
        if tf not in DERIVED_FROM:
            continue
        parent = (sym, DERIVED_FROM[tf])
        if parent in grown or (sym, tf) not in _rows:
            before = (_rows.get((sym, tf)) or [[None]])[-1][0]
            _rows[(sym, tf)] = delta.resample(_rows.get(parent) or [], TF_SECONDS[tf])[-n:]
            if _rows[(sym, tf)] and _rows[(sym, tf)][-1][0] != before:
                grown.add((sym, tf))
    return grown


def _books(symbols: set[str]) -> dict[str, dict]:
    out = {}
    for sym in sorted(symbols):
        try:
            out[sym] = delta.l2_book(sym, BOOK_DEPTH)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[crypto_trading] %s book failed: %s", sym, str(exc)[:120])
    return out


def _fill(book: dict | None, side: str, contracts: float, slippage_bps: float) -> tuple[float | None, str, float | None]:
    """(average price, basis, mid) for `contracts` taken from the live book: buys lift the asks, sells
    hit the bids, never better than mid +/- the coin's slippage."""
    if not book or not book.get("buy") or not book.get("sell"):
        return None, "no two-sided book", None
    mid = (book["buy"][0][0] + book["sell"][0][0]) / 2
    px, got = delta.walk(book["sell"] if side == "BUY" else book["buy"], contracts)
    if px is None or got < contracts:
        return None, "the book is thinner than the order", mid
    floor = mid * (1 + slippage_bps / 1e4) if side == "BUY" else mid * (1 - slippage_bps / 1e4)
    px = max(px, floor) if side == "BUY" else min(px, floor)
    return px, "L2 book walk", mid


def _mm_pct(symbol: str) -> float:
    if time.time() - _specs["at"] > 6 * 3600:
        try:
            _specs["mm"] = {s: p.get("maintenance_margin_pct") for s, p in delta.products().items()}
            _specs["at"] = time.time()
        except Exception:  # noqa: BLE001 - the default is used and the spec is retried next time
            _specs["at"] = time.time() - 5 * 3600
    v = _specs["mm"].get(symbol)
    return float(v) if v else DEFAULT_MM_PCT


def _liq_px(side: str, entry: float, mm_pct: float) -> float:
    """Isolated-margin liquidation price at LEVERAGE."""
    im, mm = 1.0 / LEVERAGE, mm_pct / 100.0
    return entry * (1 - im + mm) if side == "BUY" else entry * (1 + im - mm)


# -- the strategies, live -----------------------------------------------------------------------------


def _factory_signals(pairs: list[dict], contracts: dict[str, Contract]) -> dict[str, object]:
    """The Factory's `evaluate` on each pair's newest closed bar, as replayed: the latest 600 bars,
    higher-timeframe bars only once closed. Blocking - run in a thread."""
    from app.services.strategy_factory.catalog import FACTORY_BY_ID
    from app.services.strategy_factory.signals import evaluate
    cache: dict[tuple[str, str], list[FBar]] = {}

    def fbars(sym: str, tf: str, n: int) -> list[FBar]:
        if (sym, tf) not in cache:
            cache[(sym, tf)] = factory_bars((_rows.get((sym, tf)) or [])[-n:], contracts[sym])
        return cache[(sym, tf)]

    out: dict[str, object] = {}
    for p in pairs:
        s = FACTORY_BY_ID[p["strategy_id"]]
        bars = fbars(p["symbol"], s.timeframe, EVAL_WINDOW)
        if not bars:
            continue
        htf = None
        if s.htf:
            hb = fbars(p["symbol"], s.htf, HTF_WINDOW + 5)
            h_len = timedelta(seconds=TF_SECONDS[s.htf])
            htf = closed_htf(hb, [b.ts + h_len for b in hb], bars[-1].ts + timedelta(seconds=TF_SECONDS[s.timeframe]))
        try:
            sig, _rej = evaluate(s, bars, p["symbol"], "DELTA", htf)
        except Exception:  # noqa: BLE001 - one strategy's error costs its signal, not the cycle
            logger.warning("[crypto_trading] %s evaluate failed", p["_id"], exc_info=True)
            continue
        if sig is not None:
            out[p["_id"]] = sig
    return out


def _sm_instance(p: dict) -> dict:
    st = _sm.get(p["_id"])
    if st is None:
        import strategy_service  # noqa: F401 - importing it is what fills the registry
        from tradingai_shared.contracts import STRATEGY_REGISTRY
        st = _sm[p["_id"]] = {"inst": STRATEGY_REGISTRY[p["base_id"]](), "warm": False}
    return st


def _sm_context_key(p: dict) -> tuple:
    warmup = _sm_instance(p)["inst"].warmup
    return (p["symbol"], p["timeframe"], int(p["unit_contracts"]), p["base_id"] in NSE_CLOCK_STRATEGIES,
            max(500, warmup + 2), p["base_id"] in BENCHMARK_STRATEGIES)


def _bench_map(tf: str, nse: bool) -> dict:
    rows = _rows.get((BENCHMARK_SYMBOL, tf)) or []
    bc = Contract(BENCHMARK_SYMBOL, "BTC", 1.0, 0.0, 28800, 0.0)
    return {b.ts: b.close for b in sm_bars(rows, bc, tf, 1, nse)}


def _sm_signals(pairs: list[dict], contracts: dict[str, Contract], now: float) -> dict[str, object]:
    """Advance every Strategies-module pair by the bars that closed since it last saw one, exactly as
    its replay feeds it (push the bar, then on_bar once warmed up); returns the NEWEST bar's signal
    per pair when that bar is fresh. A pair seen for the first time (a restart, an import) is warmed
    on the held bars first and its signals there discarded. Blocking - run in a thread."""
    from tradingai_shared.contracts import StrategyContext
    out: dict[str, object] = {}
    by_ctx: dict[tuple, list[dict]] = {}
    for p in pairs:
        try:
            by_ctx.setdefault(_sm_context_key(p), []).append(p)
        except Exception:  # noqa: BLE001 - a strategy this process cannot build costs its pair, not the cycle
            logger.warning("[crypto_trading] %s: cannot build %s", p["_id"], p["base_id"], exc_info=True)
    for key, members in by_ctx.items():
        sym, tf, unit, nse, max_bars, bench = key
        rows = _rows.get((sym, tf)) or []
        if not rows:
            continue
        contract = contracts[sym]
        c = _ctx.get(key)
        if c is None:
            c = _ctx[key] = {"ctx": StrategyContext(max_bars=max_bars), "through": 0}
        new_bars = sm_bars([r for r in rows if r[0] > c["through"]], contract, tf, unit, nse)
        if bench:
            c["ctx"].benchmark_by_ts = _bench_map(tf, nse)
        fresh = now - (rows[-1][0] + TF_SECONDS[tf]) <= FRESH_S
        cold = [p for p in members if not _sm_instance(p)["warm"]]
        warm = [p for p in members if _sm_instance(p)["warm"]]
        for i, b in enumerate(new_bars):
            c["ctx"].push(b)
            newest = i == len(new_bars) - 1
            for p in warm:
                inst = _sm_instance(p)["inst"]
                if len(c["ctx"].bars) < inst.warmup:
                    continue
                try:
                    sig = inst.on_bar(c["ctx"])
                except Exception:  # noqa: BLE001 - one strategy's error costs its signal, not the cycle
                    logger.warning("[crypto_trading] %s on_bar failed", p["_id"], exc_info=True)
                    continue
                if newest and fresh and sig is not None:
                    out[p["_id"]] = sig
        c["through"] = rows[-1][0]
        if cold:
            history = sm_bars(rows, contract, tf, unit, nse)
            for p in cold:
                st = _sm_instance(p)
                wctx = StrategyContext(max_bars=max_bars, benchmark_by_ts=c["ctx"].benchmark_by_ts if bench else None)
                sig = None
                try:
                    for i, b in enumerate(history):
                        wctx.push(b)
                        sig = st["inst"].on_bar(wctx) if i + 1 >= st["inst"].warmup else None
                except Exception:  # noqa: BLE001
                    logger.warning("[crypto_trading] %s warm-up failed", p["_id"], exc_info=True)
                    continue
                st["warm"] = True
                if fresh and sig is not None:
                    out[p["_id"]] = sig
    return out


# -- positions --------------------------------------------------------------------------------------------


async def _pairs() -> list[dict]:
    from app.services.strategy_factory.catalog import FACTORY_BY_ID
    out = []
    async for a in store.ACCOUNTS.find({"eligible": True}, {
            "strategy_id": 1, "library": 1, "base_id": 1, "name": 1, "timeframe": 1, "symbol": 1, "coin": 1,
            "unit_contracts": 1, "cash": 1, "halt": 1, "day": 1, "day_start_equity": 1, "open_position_id": 1,
            "peak_equity": 1, "equity": 1, "unrealized_pnl": 1, "grade": 1, "reset_id": 1}):
        if a["library"] == "factory":
            s = FACTORY_BY_ID.get(a["strategy_id"])
            if s is None:
                continue
            a["htf"] = s.htf
        out.append(a)
    return out


async def _universe_contracts() -> dict[str, Contract]:
    doc = await store.UNIVERSE.find_one({"_id": "current"}) or {}
    return {c["venue_symbol"]: Contract.from_coin(c) for c in doc.get("selected") or []}


def _pos_doc(p: dict, c: Contract, side: str, contracts: int, px: float, mid: float | None, basis: str,
             stop: float | None, target: float | None, signal_bar_ts: int, detail: dict, now: datetime) -> dict:
    from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD
    notional = px * contracts * c.contract_value
    mm = _mm_pct(c.symbol)
    entry_fee = fee(notional, c.taker_fee)
    doc = {
        "_id": uuid4().hex[:14], "pair_id": p["_id"], "strategy_id": p["strategy_id"], "library": p["library"],
        "name": p.get("name"), "timeframe": p["timeframe"], "symbol": c.symbol, "coin": c.coin, "side": side,
        "direction": "long" if side == "BUY" else "short", "contracts": int(contracts),
        "contract_value": c.contract_value, "qty_coin": round(contracts * c.contract_value, 10),
        "entry_px": px, "entry_mid": mid, "entry_basis": basis, "entry_ts": now,
        "signal_bar_ts": int(signal_bar_ts), "stop": stop, "target": target,
        "notional_usd": round(notional, 4), "leverage": LEVERAGE, "margin_usd": round(notional / LEVERAGE, 4),
        "mm_pct": mm, "liq_px": _liq_px(side, px, mm), "entry_fee": round(entry_fee, 6),
        "taker_fee": c.taker_fee, "slippage_bps": c.slippage_bps, "funding_paid": 0.0, "funding_exchanges": 0,
        "funding_fallbacks": 0, "funding_through": int(now.timestamp()),
        # the minute the fill happened in is checked once it closes (it holds a few seconds before the fill)
        "checked_through": (int(now.timestamp()) // 60) * 60 - 60,
        "status": "OPEN", "mark": px, "unrealized_pnl": round(-entry_fee, 4), "signal": detail,
        "reset_id": p.get("reset_id"), "risk_usd": None,
    }
    if stop is not None:
        doc["risk_usd"] = round(abs(px - stop) * contracts * c.contract_value, 4) or None
    if p["library"] == "factory":
        hold = int(DEFAULT_MAX_HOLD.get(p["timeframe"], 60))
        doc["max_hold_bars"] = hold
        # the entry bar opens at signal_bar_ts + tf; the hold ends when bar (entry + hold) has closed
        doc["hold_until"] = int(signal_bar_ts) + (hold + 2) * TF_SECONDS[p["timeframe"]]
        doc["bars_held"] = 0
    return doc


async def _close(pos: dict, px: float, ts: int, reason: str, basis: str, account_updates: dict) -> bool:
    """Close one position at `px` (coin price) and stage its account's update."""
    sign = 1 if pos["side"] == "BUY" else -1
    q = pos["contracts"] * pos["contract_value"]
    gross = (px - pos["entry_px"]) * q * sign
    exit_fee = fee(px * q, pos["taker_fee"])
    net = gross - pos["entry_fee"] - exit_fee - pos["funding_paid"]
    upd = {"status": "CLOSED", "exit_px": px, "exit_ts": datetime.fromtimestamp(ts, UTC), "exit_reason": reason,
           "exit_basis": basis, "exit_fee": round(exit_fee, 6), "gross_pnl": round(gross, 4),
           "costs": round(pos["entry_fee"] + exit_fee + pos["funding_paid"], 4), "net_pnl": round(net, 4),
           "unrealized_pnl": 0.0, "mark": px, "funding_paid": round(pos["funding_paid"], 6),
           "funding_exchanges": pos["funding_exchanges"], "funding_fallbacks": pos.get("funding_fallbacks", 0),
           "checked_through": pos["checked_through"], "funding_through": pos["funding_through"],
           "r_multiple": round(net / pos["risk_usd"], 3) if pos.get("risk_usd") else None, "closed_at": _now()}
    if "bars_held" in pos:
        upd["bars_held"] = pos["bars_held"]
    res = await store.POSITIONS.update_one({"_id": pos["_id"], "status": "OPEN"}, {"$set": upd})
    if not res.modified_count:
        return False
    a = account_updates.setdefault(pos["pair_id"], {"inc": {}, "set": {}})
    for k, v in (("cash", net), ("realized_pnl", net), ("fees", pos["entry_fee"] + exit_fee),
                 ("funding", pos["funding_paid"]), ("trades", 1), ("wins", int(net > 0)), ("losses", int(net < 0)),
                 ("gross_profit", max(net, 0.0)), ("gross_loss", max(-net, 0.0))):
        a["inc"][k] = a["inc"].get(k, 0) + v
    a["set"].update({"open_position_id": None, "last_trade_at": _now()})
    pos.update(upd)
    return True


async def _funding_rate(symbol: str, t: int, marks: dict, cache: dict) -> tuple[float | None, bool]:
    """The rate in force at exchange `t` (the backtest's rule: the latest hourly funding candle that had
    ENDED by then); when the venue has not published it, the ticker's current rate, flagged. Two days
    are asked for: the venue answers a FUNDING: request for only a few hourly bars with none at all
    (measured 2026-11-01; price and MARK: candles come back whole at any window)."""
    if (symbol, t) not in cache:
        try:
            f = await to_thread.run_sync(delta.funding, symbol, t - 2 * 86400, t)
        except Exception:  # noqa: BLE001
            f = []
        cache[(symbol, t)] = rate_at([x[0] for x in f], [x[1] for x in f], t)
    rate = cache[(symbol, t)]
    if rate is not None:
        return rate, False
    fb = (marks.get(symbol) or {}).get("funding_rate_pct")
    return (float(fb), True) if fb is not None else (None, True)


async def _manage(open_pos: list[dict], contracts: dict[str, Contract], marks: dict[str, dict],
                  sm_sigs: dict[str, object], now: float, books: dict[str, dict], account_updates: dict) -> dict:
    """Funding, liquidation, stops, targets, the hold limit and Strategies-module exits."""
    from tradingai_shared.domain import SignalAction
    counts: dict[str, int] = {}
    f_cache: dict = {}
    marks_ops: list[UpdateOne] = []
    for pos in open_pos:
        c = contracts.get(pos["symbol"])
        if c is None:
            continue
        q = pos["contracts"] * pos["contract_value"]
        sign = 1 if pos["side"] == "BUY" else -1
        stop = pos["stop"] if pos.get("stop") is not None else (-math.inf if sign > 0 else math.inf)
        target = pos["target"] if pos.get("target") is not None else (math.inf if sign > 0 else -math.inf)
        rows = [r for r in (_rows.get((pos["symbol"], "1m")) or []) if r[0] > pos["checked_through"]]
        last_close = None
        done = False
        for r in rows:
            # funding at each exchange in (funding_through, this bar's open]: held through it
            for t in funding_exchanges(pos["funding_through"], r[0], c.funding_interval_s):
                rate, fallback = await _funding_rate(pos["symbol"], t, marks, f_cache)
                px_t = last_close if last_close is not None else pos["mark"]
                if rate is not None:
                    pos["funding_paid"] += funding_cost(sign, px_t * q, rate)
                    pos["funding_exchanges"] += 1
                    pos["funding_fallbacks"] = pos.get("funding_fallbacks", 0) + int(fallback)
                pos["funding_through"] = t
            bar = FBar(datetime.fromtimestamp(r[0], UTC), r[1], r[2], r[3], r[4], r[5])
            liq = pos["liq_px"]
            liq_hit = (bar.low <= liq) if sign > 0 else (bar.high >= liq)
            stop_first = (stop > liq) if sign > 0 else (stop < liq)
            pos["checked_through"] = r[0]
            if liq_hit and not stop_first:
                done = await _close(pos, liq, r[0], "liquidation", "liquidation price", account_updates)
            else:
                hit = exit_on_bar(pos["side"], stop, target, bar, c.slippage_bps)
                if hit:
                    done = await _close(pos, hit[0], r[0], hit[1], "level on the 1-minute bar", account_updates)
            if done:
                break
            last_close = r[4]
        if done:
            counts[pos["exit_reason"]] = counts.get(pos["exit_reason"], 0) + 1
            continue
        # the hold limit (Factory) and the strategy's own exit (Strategies module): at the market, now
        why = None
        if pos["library"] == "factory":
            pos["bars_held"] = max(0, int((now - (pos["signal_bar_ts"] + TF_SECONDS[pos["timeframe"]]))
                                          // TF_SECONDS[pos["timeframe"]]))
            if now >= pos.get("hold_until", math.inf) + SETTLE_S:
                why = "max_hold"
        sig = sm_sigs.get(pos["pair_id"]) if pos["library"] == "strategies" else None
        if sig is not None:
            a = sig.signal
            if (a in (SignalAction.EXIT_LONG, SignalAction.SELL) and sign > 0) or \
                    (a in (SignalAction.EXIT_SHORT, SignalAction.BUY) and sign < 0):
                why = "signal"
        if why:
            px, basis, _mid = _fill(books.get(pos["symbol"]), "SELL" if sign > 0 else "BUY", pos["contracts"],
                                    c.slippage_bps)
            if px is None:
                m = (marks.get(pos["symbol"]) or {}).get("mark")
                if m:
                    px, basis = m * (1 - sign * c.slippage_bps / 1e4), f"mark -/+ slippage ({basis})"
            if px is not None and await _close(pos, px, int(now), why, basis, account_updates):
                counts[why] = counts.get(why, 0) + 1
                continue
        m = (marks.get(pos["symbol"]) or {}).get("mark") or last_close or pos["mark"]
        pos["mark"] = m
        pos["unrealized_pnl"] = round((m - pos["entry_px"]) * q * sign - pos["entry_fee"] - pos["funding_paid"], 4)
        fields = ("mark", "unrealized_pnl", "funding_paid", "funding_exchanges", "funding_fallbacks",
                  "funding_through", "checked_through", "bars_held")
        marks_ops.append(UpdateOne({"_id": pos["_id"], "status": "OPEN"},
                                   {"$set": {k: pos[k] for k in fields if k in pos}}))
    if marks_ops:
        await store.POSITIONS.bulk_write(marks_ops, ordered=False)
    return counts


def _halted(acc: dict, today: str) -> str | None:
    h = acc.get("halt") or {}
    if h.get("kind") == "drawdown":
        return h.get("reason") or "drawdown limit"
    if h.get("kind") == "daily_loss" and (h.get("until_day") or "") > today:
        return h.get("reason") or "daily loss limit"
    return None


def _sm_size(p: dict, c: Contract, fill_px: float, stop_coin: float | None, cash: float) -> int:
    """The Strategies module's own RiskEngine, as its replay sizes: CAPITAL_PCT 100% of cash, 1x."""
    from risk_service import RiskEngine, RiskLimits, SizingConfig, SizingMethod
    unit = int(p["unit_contracts"])
    unit_px = fill_px * c.contract_value * unit
    stop_unit = stop_coin * c.contract_value * unit if stop_coin is not None else None
    d = RiskEngine(RiskLimits()).evaluate(
        price=unit_px, equity=cash, open_positions=[],
        sizing=SizingConfig(method=SizingMethod.CAPITAL_PCT, capital_pct=100.0, risk_pct=1.0, atr_mult=2.0,
                            target_daily_vol_pct=1.0, kelly_cap=0.25),
        stop_loss=stop_unit, lot_size=1)
    return int(d.quantity) * unit if d.approved else 0


async def _open(p: dict, c: Contract, side: str, book: dict | None, levels: dict, cash: float,
                signal_bar_ts: int, detail: dict, now: datetime) -> tuple[dict | None, str]:
    """Size, fill and insert one entry. A Factory signal's levels are re-anchored to the fill, as its
    replay re-anchors them to the next bar's open."""
    from app.services.strategy_factory.primitives import Levels, position_size
    touch = (book or {}).get("sell" if side == "BUY" else "buy") or []
    if not touch:
        return None, "no two-sided book"
    ref = touch[0][0]
    cv = c.contract_value
    if p["library"] == "factory":
        shift = ref - levels["entry"]
        stop, target = levels["stop"] + shift, levels["target"] + shift
        if abs(ref - stop) <= 0:
            return None, "degenerate levels"
        n = position_size(ACCOUNT_CAPITAL_USD, cash, Levels(
            ref * cv, stop * cv, target * cv, abs(ref - stop) * cv, abs(target - ref) * cv,
            abs(target - ref) / abs(ref - stop), "", ""), risk_pct=RISK_PCT, max_notional_pct=MAX_NOTIONAL_PCT,
            lot_size=1)
    else:
        n = _sm_size(p, c, ref, levels["stop"], cash)
    if n < 1:
        return None, "sizing produced no whole contract"
    px, basis, mid = _fill(book, side, n, c.slippage_bps)
    if px is None:
        return None, basis
    if p["library"] == "factory":
        shift = px - levels["entry"]
        stop, target = levels["stop"] + shift, levels["target"] + shift
    else:
        stop, target = levels["stop"], levels["target"]
    doc = _pos_doc(p, c, side, n, px, mid, basis, stop, target, signal_bar_ts, detail, now)
    try:
        await store.POSITIONS.insert_one(doc)
    except DuplicateKeyError:
        return None, "already taken (this signal bar opened a position before)"
    await store.ACCOUNTS.update_one({"_id": p["_id"]}, {"$set": {"open_position_id": doc["_id"], "last_signal_at": now}})
    return doc, "opened"


# -- the cycle --------------------------------------------------------------------------------------------


async def tick() -> dict:
    """One pass of the desk. Safe to call at any time: bars are read only when due, a signal bar can
    open at most one position, and only the lease holder runs."""
    global _indexed
    if not _indexed:
        _indexed = True
        await store.ensure_indexes()
    if not await _lease():
        return {"skipped": "another process holds the desk's lease"}
    from app.services.desk_switches import is_on
    from tradingai_shared.domain import SignalAction
    t0 = time.time()
    async with _lock:
        st = await state()
        status = st.get("status") or "stopped"
        contracts = await _universe_contracts()
        pairs = [p for p in await _pairs() if p["symbol"] in contracts]
        open_pos = [d async for d in store.POSITIONS.find({"status": "OPEN"})]
        now = time.time()
        need = _needed(pairs, open_pos, now)
        grown = await to_thread.run_sync(_refresh, need, now)
        marks: dict = {}
        if open_pos:
            try:
                marks = await to_thread.run_sync(delta.tickers)
            except Exception as exc:  # noqa: BLE001 - stops still run on the 1-minute bars; marks fall back to them
                logger.warning("[crypto_trading] tickers failed: %s", str(exc)[:160])
        switch_on = await is_on(SWITCH)
        entries_on = status == "running" and switch_on
        today = _day()

        # who decides this cycle: a pair whose own timeframe has a bar that has JUST closed
        deciding = [p for p in pairs if (p["symbol"], p["timeframe"]) in grown and _rows.get((p["symbol"], p["timeframe"]))
                    and now - (_rows[(p["symbol"], p["timeframe"])][-1][0] + TF_SECONDS[p["timeframe"]]) <= FRESH_S]
        sm_sigs = await to_thread.run_sync(_sm_signals, [p for p in pairs if p["library"] == "strategies"],
                                           contracts, now)

        # manage first, so a pair that exits on this bar is flat when it is decided on - as in the replay
        exit_syms = {d["symbol"] for d in open_pos if
                     (d["library"] == "strategies" and d["pair_id"] in sm_sigs) or now >= d.get("hold_until", math.inf)}
        books = await to_thread.run_sync(_books, exit_syms) if exit_syms else {}
        account_updates: dict[str, dict] = {}
        closed = await _manage(open_pos, contracts, marks, sm_sigs, now, books, account_updates)
        still_open = {d["pair_id"] for d in open_pos if d.get("status") == "OPEN"}
        reversed_now = {d["pair_id"] for d in open_pos if d.get("exit_reason") == "signal"}

        f_pairs = [p for p in deciding if p["library"] == "factory" and p["_id"] not in still_open]
        f_sigs = await to_thread.run_sync(_factory_signals, f_pairs, contracts) if f_pairs else {}
        if entries_on:
            entry_syms = {p["symbol"] for p in deciding if p["_id"] in f_sigs or p["_id"] in sm_sigs} - set(books)
            if entry_syms:
                books.update(await to_thread.run_sync(_books, entry_syms))

        signals: list[dict] = []
        opened, skips = 0, {}
        now_dt = _now()
        for p in deciding:
            c = contracts[p["symbol"]]
            rows = _rows[(p["symbol"], p["timeframe"])]
            if p["library"] == "factory":
                sig = f_sigs.get(p["_id"])
                if sig is None:
                    continue
                side = sig.side
                cv = c.contract_value
                levels = {"entry": sig.entry / cv, "stop": sig.stop / cv, "target": sig.target / cv}
                detail = {"pattern": sig.pattern, "regime": sig.regime_primary, "confirmations": sig.confirmations,
                          "r_multiple": sig.r_multiple, "stop_basis": sig.stop_basis, "target_basis": sig.target_basis,
                          "confidence": sig.confidence}
            else:
                sig = sm_sigs.get(p["_id"])
                if sig is None or sig.signal not in (SignalAction.BUY, SignalAction.SELL):
                    continue
                side = "BUY" if sig.signal == SignalAction.BUY else "SELL"
                if p["_id"] in still_open:
                    continue                           # already that way round: no pyramiding
                k = c.contract_value * int(p["unit_contracts"])
                levels = {"entry": None, "stop": sig.stop_loss / k if sig.stop_loss else None,
                          "target": sig.target / k if sig.target else None}
                detail = {"reasoning": getattr(sig, "reasoning", ""), "confidence": getattr(sig, "confidence", None)}
            out = {"at": now_dt, "expires": now_dt + SIGNAL_TTL, "pair_id": p["_id"], "strategy_id": p["strategy_id"],
                   "name": p.get("name"), "library": p["library"], "symbol": p["symbol"], "coin": p["coin"],
                   "timeframe": p["timeframe"], "bar_ts": datetime.fromtimestamp(rows[-1][0], UTC), "side": side,
                   "entry_ref": levels["entry"], "stop": levels["stop"], "target": levels["target"], "detail": detail}
            halt = _halted(p, today)
            thin = no_trade_pct(rows[-EVAL_WINDOW:])
            if not entries_on:
                out["outcome"] = (f"not taken: the desk is {status}" if status != "running"
                                  else "not taken: Main Control has Crypto Trading OFF")
            elif halt:
                out["outcome"] = f"not taken: {halt}"
            elif thin > MAX_NO_TRADE_BAR_PCT:
                out["outcome"] = f"not taken: {thin:.1f}% of the last {EVAL_WINDOW} bars have no trade"
            elif p["_id"] in still_open:
                out["outcome"] = "not taken: a position is open"
            else:
                cash = float(p.get("cash") or ACCOUNT_CAPITAL_USD) + \
                    (account_updates.get(p["_id"]) or {}).get("inc", {}).get("cash", 0.0)
                doc, why = await _open(p, c, side, books.get(p["symbol"]), levels, cash, rows[-1][0], detail, now_dt)
                if doc:
                    opened += 1
                    out.update({"outcome": "reversed" if p["_id"] in reversed_now else "opened",
                                "position_id": doc["_id"], "fill_px": doc["entry_px"], "contracts": doc["contracts"]})
                else:
                    out["outcome"] = f"not taken: {why}"
            if out["outcome"].startswith("not taken"):
                skips[out["outcome"]] = skips.get(out["outcome"], 0) + 1
            signals.append(out)
        if signals:
            await store.SIGNALS.insert_many(signals)

        # accounts that hold a position but are no longer eligible (a re-import re-graded them) are still
        # marked, limited and credited like the rest
        held = list({d["pair_id"] for d in open_pos} - {p["_id"] for p in pairs})
        extra = [a async for a in store.ACCOUNTS.find({"_id": {"$in": held}}, {
            "cash": 1, "halt": 1, "day": 1, "day_start_equity": 1, "peak_equity": 1, "equity": 1,
            "unrealized_pnl": 1})] if held else []
        await _apply_accounts(pairs + extra, account_updates, today, open_pos)
        await _snapshot(now)
        summary = {"pairs": len(pairs), "deciding": len(deciding), "signals": len(signals), "opened": opened,
                   "closed": closed, "open": len(still_open), "skips": skips, "series": len(need),
                   "grown": len(grown), "status": status, "switch_on": switch_on,
                   "ms": round((time.time() - t0) * 1000)}
        await store.STATE.update_one({"_id": STATE_ID}, {"$set": {"last_cycle_at": _now(), "last_cycle": summary}},
                                     upsert=True)
        return summary


async def _apply_accounts(pairs: list[dict], updates: dict, today: str, open_pos: list[dict]) -> None:
    """Closed trades into each account; its equity, peak and drawdown; the two limits; the day's start."""
    unreal = {d["pair_id"]: d.get("unrealized_pnl") or 0.0 for d in open_pos if d.get("status") == "OPEN"}
    ops = []
    seen = set()
    for p in pairs:
        seen.add(p["_id"])
        u = updates.get(p["_id"], {"inc": {}, "set": {}})
        cash = float(p.get("cash") or ACCOUNT_CAPITAL_USD) + u["inc"].get("cash", 0.0)
        equity = cash + unreal.get(p["_id"], 0.0)
        sets = dict(u["set"])
        start = float(p.get("day_start_equity") or ACCOUNT_CAPITAL_USD)
        h = p.get("halt") or {}
        if p.get("day") != today:
            sets.update({"day": today, "day_start_equity": round(equity, 4)})
            start = equity
            if h.get("kind") == "daily_loss":
                sets["halt"], h = None, {}
        peak = max(float(p.get("peak_equity") or ACCOUNT_CAPITAL_USD), equity)
        marks = {"peak_equity": round(peak, 4), "equity": round(equity, 4),
                 "unrealized_pnl": round(unreal.get(p["_id"], 0.0), 4)}
        if not u["inc"] and not sets and all(
                round(float(p.get(k) if p.get(k) is not None else (0.0 if k == "unrealized_pnl" else ACCOUNT_CAPITAL_USD)), 4) == v
                for k, v in marks.items()) and not (
                equity <= ACCOUNT_CAPITAL_USD * (1 - MAX_DRAWDOWN_PCT) or equity <= start * (1 - DAILY_LOSS_PCT)):
            continue                        # a flat account whose numbers did not move: nothing to write
        sets.update(marks)
        if equity <= ACCOUNT_CAPITAL_USD * (1 - MAX_DRAWDOWN_PCT) and h.get("kind") != "drawdown":
            sets["halt"] = {"kind": "drawdown", "at": _now(),
                            "reason": f"equity ${equity:,.0f} is at half its capital or less: stopped until a reset"}
        elif equity <= start * (1 - DAILY_LOSS_PCT) and not h.get("kind"):
            tomorrow = (datetime.fromisoformat(today) + timedelta(days=1)).date().isoformat()
            sets["halt"] = {"kind": "daily_loss", "at": _now(), "until_day": tomorrow,
                            "reason": f"down {DAILY_LOSS_PCT:.0%} today: no new entries until {tomorrow} 00:00 UTC"}
        upd = {"$set": sets, "$max": {"max_drawdown_pct": round((peak - equity) / peak * 100, 4) if peak > 0 else 0.0}}
        if u["inc"]:
            upd["$inc"] = u["inc"]
        ops.append(UpdateOne({"_id": p["_id"]}, upd))
    for pid, u in updates.items():          # an account no longer eligible, closing a position it still had
        if pid not in seen and u["inc"]:
            ops.append(UpdateOne({"_id": pid}, {"$inc": u["inc"], "$set": u["set"]}))
    if ops:
        await store.ACCOUNTS.bulk_write(ops, ordered=False)


async def _snapshot(now: float) -> None:
    last = await store.EQUITY.find_one({"scope": "desk"}, sort=[("ts", -1)])
    if last and now - last["ts"].replace(tzinfo=UTC).timestamp() < EQUITY_EVERY_S:
        return
    agg = await store.ACCOUNTS.aggregate([
        {"$match": {"$or": [{"eligible": True}, {"trades": {"$gt": 0}}]}},
        {"$group": {"_id": None, "accounts": {"$sum": 1}, "cash": {"$sum": "$cash"},
                    "unrealized": {"$sum": {"$ifNull": ["$unrealized_pnl", 0]}},
                    "realized": {"$sum": "$realized_pnl"}, "fees": {"$sum": "$fees"},
                    "funding": {"$sum": "$funding"}, "trades": {"$sum": "$trades"}}}]).to_list(1)
    if not agg:
        return
    a = agg[0]
    await store.EQUITY.insert_one({
        "scope": "desk", "ts": _now(), "accounts": a["accounts"], "capital": a["accounts"] * ACCOUNT_CAPITAL_USD,
        "equity": round(a["cash"] + a["unrealized"], 2), "realized": round(a["realized"], 2),
        "unrealized": round(a["unrealized"], 2), "fees": round(a["fees"], 2), "funding": round(a["funding"], 2),
        "trades": a["trades"], "open": await store.POSITIONS.count_documents({"status": "OPEN"})})


async def loop() -> None:
    if not ENABLED:
        logger.warning("[crypto_trading] disabled by CRYPTO_TRADING_ENABLED")
        return
    if not store._URL:
        logger.warning("[crypto_trading] FACTORY_MONGO_URL is unset: records go to the main database %r",
                       store.store_name())
    await asyncio.sleep(45)
    while True:
        try:
            r = await tick()
            if r.get("opened") or r.get("closed"):
                logger.warning("[crypto_trading] %s", r)        # WARNING: the app shows no INFO lines
        except Exception:  # noqa: BLE001 - the desk must outlive one bad cycle
            logger.warning("[crypto_trading] tick failed", exc_info=True)
        await asyncio.sleep(max(5.0, TICK_S - (time.time() % TICK_S) + SETTLE_S))
