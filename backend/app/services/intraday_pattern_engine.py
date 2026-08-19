"""Pattern desk inside Intraday Stocks: 63 chart/candle/indicator rules x 8 timeframes.

WHAT THIS ADDS to the existing 150-strategy tournament. Those strategies read DAILY bars
only. This runs the full pattern catalog — 13 geometric chart patterns, 10 candlestick
patterns and 40 indicator/structure rules — on NSE equities at 1m, 5m, 15m, 30m, 45m, 1h,
4h and 1d. 63 x 8 = 504 strategies, Rs10 lakh each, alongside the tournament rather than
replacing it.

THE HARD CONSTRAINT IS ANGEL'S HISTORICAL ENDPOINT, not compute. It rate-limits far harder
than quotes: 150 symbols x 8 timeframes is 1,200 candle requests per cycle, and at the ~1s
pacing that endpoint needs, one cycle would take twenty minutes. So this desk trades a
BOUNDED universe (default 25 names, the best-scoring from the same daily screen the
tournament uses) and caches each series for the life of its own bar — a 1-minute series is
refetched after a minute, a daily series once a day. Steady state is roughly 30 requests a
minute rather than 1,200 a cycle. Widening the universe is a config change, but it is a
change with a known price, and pretending otherwise would just produce a desk that silently
never completes a scan.

45m AND 4h HAVE NO ANGEL INTERVAL and are aggregated from 15m and 1h respectively. NSE
trades 6h15m, so the last bucket of a session is a short partial bar on both — real, but
worth knowing before trusting a signal that sits on one.

COSTS ARE CHARGED on the real Angel One schedule, intraday or delivery according to whether
the position actually slept overnight. A pattern desk fires often; on Rs10 lakh positions
that is a smaller drag than on the little books, but it is never zero and is never assumed.

PAPER. Live Angel prices, no orders.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    pattern_equity_collection,
    pattern_positions_collection,
    pattern_scores_collection,
    pattern_state_collection,
    pattern_trades_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.angel_fees import product_for, round_trip
from app.services.call_engine import IST, _scored_daily_symbols
from app.services.nifty_scalp_strategies import TEMPLATES, Series, from_rows, resample

logger = logging.getLogger("intraday_pattern")

PER_STRATEGY_CAPITAL = float(os.getenv("PAT_PER_STRATEGY_CAPITAL", "1000000"))   # Rs10 lakh
UNIVERSE_SIZE = int(os.getenv("PAT_UNIVERSE", "25"))
CANDLE_PACE = float(os.getenv("PAT_CANDLE_PACE", "1.0"))
ENABLED = os.getenv("PAT_ENABLED", "1").lower() not in ("0", "false", "")
SQUAREOFF = os.getenv("PAT_SQUAREOFF", "15:15")
ENTRY_CUTOFF = os.getenv("PAT_ENTRY_CUTOFF", "15:00")
SWING_MAX_DAYS = int(os.getenv("PAT_SWING_MAX_DAYS", "5"))
MAX_FETCH_PER_CYCLE = int(os.getenv("PAT_MAX_FETCH", "40"))


class TF:
    """A timeframe: how to get it, how long its bars live, and how it is traded."""

    def __init__(self, key, label, resolution, aggregate, style, lookback_days,
                 target_pct, stop_pct, max_bars, ttl):
        self.key, self.label = key, label
        self.resolution, self.aggregate = resolution, aggregate
        self.style, self.lookback_days = style, lookback_days
        self.target_pct, self.stop_pct = target_pct, stop_pct
        self.max_bars, self.ttl = max_bars, ttl


# target/stop are on the SHARE price here, not an option premium, so they are far tighter
# than the NIFTY option desk's — a 40% move in a stock is not the same event as a 40% move
# in a near-expiry premium.
TIMEFRAMES: list[TF] = [
    TF("1m",  "1 minute",   "1",  1, "scalping", 5,   0.6, 0.4, 15, 60),
    TF("5m",  "5 minutes",  "5",  1, "scalping", 15,  0.9, 0.6, 12, 300),
    TF("15m", "15 minutes", "15", 1, "intraday", 45,  1.4, 0.9, 10, 900),
    TF("30m", "30 minutes", "30", 1, "intraday", 90,  1.8, 1.2, 8,  1800),
    # No Angel interval for 45m; built from three 15-minute bars.
    TF("45m", "45 minutes", "15", 3, "intraday", 90,  2.2, 1.4, 8,  2700),
    TF("1h",  "1 hour",     "60", 1, "intraday", 180, 2.5, 1.6, 6,  3600),
    # No Angel interval for 4h either; built from four 1-hour bars.
    TF("4h",  "4 hours",    "60", 4, "swing",    365, 4.0, 2.5, 5,  14400),
    TF("1d",  "1 day",      "D",  1, "swing",    900, 6.0, 3.5, 5,  43200),
]
TF_BY_KEY = {t.key: t for t in TIMEFRAMES}

PROFILE = {"fast": 5, "mid": 10, "slow": 20, "trend": 50, "rsi": 14, "orb": 3,
           "session": 25, "pivot": 3, "pole": 10, "flag": 8, "cup": 40}


class PatternStrategy:
    __slots__ = ("strategy_id", "name", "template", "family", "timeframe", "style", "fn")

    def __init__(self, sid, name, template, family, timeframe, style, fn):
        self.strategy_id, self.name, self.template = sid, name, template
        self.family, self.timeframe, self.style, self.fn = family, timeframe, style, fn


def _build() -> list[PatternStrategy]:
    out = []
    for tf in TIMEFRAMES:
        for i, (name, family, fn) in enumerate(TEMPLATES, start=1):
            out.append(PatternStrategy(
                f"pat_{tf.key}_{i:02d}", f"{name} · {tf.label}", name, family, tf.key,
                tf.style, fn))
    return out


CATALOG = _build()
CATALOG_BY_ID = {s.strategy_id: s for s in CATALOG}
TOTAL_CAPITAL = PER_STRATEGY_CAPITAL * len(CATALOG)


def _now():
    return datetime.now(timezone.utc)


def _today():
    return datetime.now(IST).date().isoformat()


def _hhmm():
    return datetime.now(IST).strftime("%H:%M")


# ── candles, cached for the life of their own bar ─────────────────────────────

_cache: dict[tuple[str, str], tuple[float, Series]] = {}


async def _universe() -> list[dict]:
    scored = await _scored_daily_symbols()
    syms = [s for s, *_ in scored[:UNIVERSE_SIZE]]
    if not syms:
        return []
    return [d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": syms}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1, "security_id": 1,
         "exchange_segment": 1, "lot_size": 1})]


async def _series(inst: dict, tf: TF, budget: list[int]) -> Series | None:
    """Cached candles for one symbol/timeframe. `budget` caps fetches per cycle so a cold
    start spreads over several cycles instead of stalling one for minutes."""
    key = (inst["symbol"], tf.key)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < tf.ttl:
        return hit[1]
    if budget[0] <= 0:
        return hit[1] if hit else None
    now = datetime.now(IST)
    frm = (now - timedelta(days=tf.lookback_days)).strftime("%Y-%m-%d %H:%M")
    rows = None
    for attempt in (1, 2):
        try:
            rows = await angel_client.candles(
                inst.get("angel_exchange") or "NSE", str(inst["angel_token"]),
                tf.resolution, frm, now.strftime("%Y-%m-%d %H:%M"))
            break
        except AngelAPIError as exc:
            if attempt == 1:
                await asyncio.sleep(2.0)
                continue
            logger.warning("pattern: candles failed %s %s (%s)", inst["symbol"], tf.key, exc)
    budget[0] -= 1
    await asyncio.sleep(CANDLE_PACE)
    if rows is None:
        return hit[1] if hit else None
    s = from_rows(rows)
    if tf.aggregate > 1:
        s = resample(s, tf.aggregate)
    _cache[key] = (time.monotonic(), s)
    return s


# ── capital ───────────────────────────────────────────────────────────────────


async def _cash(strategy_id: str) -> float:
    realized = deployed = 0.0
    async for p in pattern_positions_collection.find(
        {"strategy_id": strategy_id}, {"realized_pnl": 1, "capital_deployed": 1, "status": 1}
    ):
        if p.get("status") == "OPEN":
            deployed += p.get("capital_deployed") or 0.0
        else:
            realized += p.get("realized_pnl") or 0.0
    return PER_STRATEGY_CAPITAL + realized - deployed


async def _update_score(strategy_id: str) -> None:
    st = CATALOG_BY_ID.get(strategy_id)
    if st is None:
        return
    trades = wins = 0
    net = fees = gross = 0.0
    async for p in pattern_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "fees": 1, "gross_pnl": 1},
    ):
        trades += 1
        r = p.get("realized_pnl") or 0.0
        wins += 1 if r > 0 else 0
        net += r
        fees += p.get("fees") or 0.0
        gross += p.get("gross_pnl") or 0.0
    await pattern_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "name": st.name, "template": st.template,
                  "family": st.family, "timeframe": st.timeframe, "style": st.style,
                  "trades": trades, "wins": wins,
                  "win_rate": round(wins / trades, 4) if trades else 0.0,
                  "net_pnl": round(net, 2), "fees": round(fees, 2),
                  "gross_pnl": round(gross, 2),
                  "roi_pct": round(net / PER_STRATEGY_CAPITAL * 100, 4),
                  "updated_at": _now()}},
        upsert=True)


# ── trading ───────────────────────────────────────────────────────────────────


async def _open(st: PatternStrategy, inst: dict, price: float, direction: int, bar_ts) -> bool:
    if await pattern_positions_collection.find_one(
        {"strategy_id": st.strategy_id, "status": "OPEN"}
    ):
        return False
    cash = await _cash(st.strategy_id)
    qty = int(min(PER_STRATEGY_CAPITAL, cash) // price) if price > 0 else 0
    if qty < 1:
        return False
    tf = TF_BY_KEY[st.timeframe]
    sign = 1 if direction > 0 else -1
    await pattern_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": st.strategy_id,
        "strategy_name": st.name, "template": st.template, "family": st.family,
        "timeframe": st.timeframe, "style": st.style,
        "symbol": inst["symbol"], "side": "BUY" if sign > 0 else "SELL",
        "entry_price": round(price, 2), "qty": qty, "ltp": round(price, 2),
        "capital_deployed": round(price * qty, 2),
        "target": round(price * (1 + sign * tf.target_pct / 100), 2),
        "stoploss": round(price * (1 - sign * tf.stop_pct / 100), 2),
        "bars_held": 0, "max_hold_bars": tf.max_bars, "bar_ts": str(bar_ts),
        "unrealized_pnl": 0.0, "realized_pnl": None, "gross_pnl": None,
        "fees": None, "fee_breakdown": None, "exit_price": None, "exit_reason": None,
        "status": "OPEN", "opened_at": _now(), "opened_on": _today(),
        "closed_at": None, "closed_on": None, "updated_at": _now(),
    })
    return True


async def _quote(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    insts = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1})}
    by_ex: dict[str, list[str]] = {}
    tok2sym: dict[str, str] = {}
    for sym, d in insts.items():
        tok = str(d["angel_token"])
        tok2sym[tok] = sym
        by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(tok)
    out: dict[str, float] = {}
    for ex, toks in by_ex.items():
        for i in range(0, len(toks), 50):
            try:
                q = await angel_client.full_quote({ex: toks[i:i + 50]})
            except AngelAPIError:
                continue
            for tok, row in q.items():
                if row.get("ltp") and str(tok) in tok2sym:
                    out[tok2sym[str(tok)]] = float(row["ltp"])
            await asyncio.sleep(0.15)
    return out


async def manage() -> int:
    positions = [p async for p in pattern_positions_collection.find({"status": "OPEN"})]
    if not positions:
        return 0
    prices = await _quote(sorted({p["symbol"] for p in positions}))
    eod = _hhmm() >= SQUAREOFF
    today = _today()
    closed = 0
    touched: set[str] = set()
    for p in positions:
        ltp = prices.get(p["symbol"])
        if ltp is None:
            continue
        sign = 1 if p["side"] == "BUY" else -1
        gross = round(sign * (ltp - p["entry_price"]) * p["qty"], 2)
        bars = (p.get("bars_held") or 0) + 1
        days = (datetime.fromisoformat(today).date()
                - datetime.fromisoformat(p["opened_on"]).date()).days
        hit_t = ltp >= p["target"] if sign > 0 else ltp <= p["target"]
        hit_s = ltp <= p["stoploss"] if sign > 0 else ltp >= p["stoploss"]
        reason = ("target" if hit_t else "stoploss" if hit_s
                  else "eod" if (p["style"] in ("scalping", "intraday") and (eod or days >= 1))
                  else "max_hold" if (p["style"] == "swing" and days >= SWING_MAX_DAYS)
                  else "time_stop" if (p["style"] == "scalping" and bars >= p["max_hold_bars"])
                  else None)
        upd = {"ltp": round(ltp, 2), "unrealized_pnl": gross, "bars_held": bars,
               "updated_at": _now()}
        if reason:
            fb = round_trip(p["entry_price"], ltp, p["qty"], side=p["side"],
                            product=product_for(None, days))
            net = round(gross - fb.total, 2)
            upd.update({"status": "CLOSED", "exit_price": round(ltp, 2),
                        "exit_reason": reason, "gross_pnl": gross, "fees": fb.total,
                        "fee_breakdown": fb.as_dict(), "realized_pnl": net,
                        "unrealized_pnl": 0.0, "closed_at": _now(), "closed_on": today})
            touched.add(p["strategy_id"])
            closed += 1
            await pattern_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
                "strategy_name": p["strategy_name"], "timeframe": p["timeframe"],
                "symbol": p["symbol"], "side": p["side"], "qty": p["qty"],
                "entry_price": p["entry_price"], "exit_price": round(ltp, 2),
                "gross_pnl": gross, "fees": fb.total, "realized_pnl": net,
                "exit_reason": reason, "opened_at": p["opened_at"], "closed_at": _now()})
        await pattern_positions_collection.update_one({"_id": p["_id"]}, {"$set": upd})
    for sid in touched:
        await _update_score(sid)
    return closed


async def scan() -> dict:
    if _hhmm() >= ENTRY_CUTOFF:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"Past the {ENTRY_CUTOFF} IST entry cutoff — open positions still managed."]}
    universe = await _universe()
    if not universe:
        return {"opened": 0, "evaluated": 0, "notes": ["No scored symbols to trade."]}

    state = await pattern_state_collection.find_one({"_id": "bars"}) or {}
    last_bar: dict = state.get("last", {})
    budget = [MAX_FETCH_PER_CYCLE]
    prices = await _quote([i["symbol"] for i in universe])

    opened = evaluated = 0
    fresh: dict[str, str] = {}
    for inst in universe:
        px = prices.get(inst["symbol"])
        if not px:
            continue
        for tf in TIMEFRAMES:
            s = await _series(inst, tf, budget)
            if s is None or len(s) < 30:
                continue
            bar_ts = str(s.ts[-1])
            for st in CATALOG:
                if st.timeframe != tf.key:
                    continue
                evaluated += 1
                # One trade per strategy per closed bar, per symbol — without this the
                # desk re-enters the same bar on every tick and pays fees for one signal.
                guard = f"{st.strategy_id}:{inst['symbol']}"
                if last_bar.get(guard) == bar_ts:
                    continue
                try:
                    d = st.fn(s, PROFILE)
                except (IndexError, ValueError, ZeroDivisionError):
                    continue
                if d not in (1, -1):
                    continue
                fresh[guard] = bar_ts
                if await _open(st, inst, px, d, bar_ts):
                    opened += 1
    if fresh:
        await pattern_state_collection.update_one(
            {"_id": "bars"}, {"$set": {f"last.{k}": v for k, v in fresh.items()}}, upsert=True)
    return {"opened": opened, "evaluated": evaluated,
            "symbols": len(universe), "fetch_budget_left": budget[0], "notes": []}


async def run_cycle() -> dict:
    if not ENABLED:
        return {"opened": 0, "closed": 0, "notes": ["desk disabled"]}
    closed = await manage()
    r = await scan()
    snap = await summary()
    await pattern_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"],
        "roi_pct": snap["roi_pct"], "open_positions": snap["open_positions"]})
    await pattern_state_collection.update_one(
        {"_id": "engine"},
        {"$set": {"last_run_at": _now(), "last_opened": r["opened"], "last_closed": closed,
                  "last_evaluated": r.get("evaluated", 0), "last_notes": r["notes"]}},
        upsert=True)
    return {"opened": r["opened"], "closed": closed, **{k: r.get(k) for k in
            ("evaluated", "symbols", "fetch_budget_left")}, "notes": r["notes"]}


# ── reporting ─────────────────────────────────────────────────────────────────


async def summary() -> dict:
    from app.services.desk_totals import split
    op, cl = await split(pattern_positions_collection)
    equity = TOTAL_CAPITAL + cl["realized"] + op["unrealized"]
    state = await pattern_state_collection.find_one({"_id": "engine"}) or {}
    return {
        "mode": "paper", "enabled": ENABLED,
        "initial_capital": TOTAL_CAPITAL,
        "per_strategy_capital": PER_STRATEGY_CAPITAL,
        "strategy_count": len(CATALOG),
        "template_count": len(TEMPLATES),
        "universe_size": UNIVERSE_SIZE,
        "timeframes": [{"key": t.key, "label": t.label, "style": t.style,
                        "target_pct": t.target_pct, "stop_pct": t.stop_pct,
                        "native": t.aggregate == 1} for t in TIMEFRAMES],
        "deployed_capital": op["deployed"],
        "available_cash": round(TOTAL_CAPITAL + cl["realized"] - op["deployed"], 2),
        "realized_pnl": cl["realized"],
        "gross_realized_pnl": round(cl["realized"] + cl["fees"], 2),
        "total_fees": cl["fees"],
        "unrealized_pnl": op["unrealized"],
        "equity": round(equity, 2),
        "roi_pct": round((equity - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100, 4) if TOTAL_CAPITAL else 0.0,
        "open_positions": op["n"], "closed_positions": cl["n"],
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
        "last_notes": state.get("last_notes", []),
        "last_evaluated": state.get("last_evaluated", 0),
    }


async def leaderboard(timeframe: str | None = None, family: str | None = None,
                      limit: int = 600) -> list[dict]:
    q = {}
    if timeframe:
        q["timeframe"] = timeframe
    if family:
        q["family"] = family
    scores = {s["strategy_id"]: s async for s in pattern_scores_collection.find(q)}
    rows = []
    for st in CATALOG:
        if timeframe and st.timeframe != timeframe:
            continue
        if family and st.family != family:
            continue
        sc = scores.get(st.strategy_id) or {}
        rows.append({"strategy_id": st.strategy_id, "name": st.name,
                     "template": st.template, "family": st.family,
                     "timeframe": st.timeframe, "style": st.style,
                     "trades": sc.get("trades", 0) or 0,
                     "win_rate": sc.get("win_rate", 0.0) or 0.0,
                     "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
                     "gross_pnl": round(sc.get("gross_pnl", 0.0) or 0.0, 2),
                     "fees": round(sc.get("fees", 0.0) or 0.0, 2),
                     "roi_pct": round(sc.get("roi_pct", 0.0) or 0.0, 4)})
    rows.sort(key=lambda r: (-r["net_pnl"], r["name"]))
    return rows[:limit]


async def timeframe_stats() -> list[dict]:
    out = []
    for tf in TIMEFRAMES:
        agg = {"timeframe": tf.key, "label": tf.label, "style": tf.style,
               "strategies": len(TEMPLATES), "trades": 0, "wins": 0,
               "net_pnl": 0.0, "fees": 0.0,
               "capital": PER_STRATEGY_CAPITAL * len(TEMPLATES)}
        async for s in pattern_scores_collection.find({"timeframe": tf.key}):
            agg["trades"] += s.get("trades", 0) or 0
            agg["wins"] += s.get("wins", 0) or 0
            agg["net_pnl"] += s.get("net_pnl", 0.0) or 0.0
            agg["fees"] += s.get("fees", 0.0) or 0.0
        agg["win_rate"] = round(agg["wins"] / agg["trades"], 4) if agg["trades"] else 0.0
        agg["roi_pct"] = round(agg["net_pnl"] / agg["capital"] * 100, 4)
        agg["net_pnl"] = round(agg["net_pnl"], 2)
        agg["fees"] = round(agg["fees"], 2)
        out.append(agg)
    return out


async def positions(status: str = "OPEN", limit: int = 400,
                    timeframe: str | None = None) -> list[dict]:
    q: dict = {} if status.upper() == "ALL" else {"status": status.upper()}
    if timeframe:
        q["timeframe"] = timeframe
    out = []
    async for d in pattern_positions_collection.find(q).sort("opened_at", -1).limit(limit):
        d.pop("_id", None)
        for k in ("opened_at", "closed_at", "updated_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        out.append(d)
    return out
