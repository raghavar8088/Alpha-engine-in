"""NIFTY 50 Option Scalping desk — a 400-strategy hunt for edges worth real money.

WHAT IT TRADES: near-expiry NIFTY 50 options, BOUGHT at the strike nearest the money.
A bullish signal buys the ATM CALL, a bearish signal buys the ATM PUT. Buying only — no
short options anywhere on this desk, so the worst case on any position is the premium
paid, which is what makes a Rs2 lakh per-strategy allocation a real ceiling rather than a
margin estimate.

THE GRID: 63 candle/indicator templates x 8 timeframes (1m, 5m, 10m, 15m, 30m, 1h, 4h,
1d), each on its own Rs2,00,000 — Rs10.08 crore across the desk. Fifty are bar-level
rules; thirteen are the classic geometric chart patterns, which fire only once price
closes through the shape's own boundary. Signals are read off NIFTY
SPOT candles and expressed through options, because indicators computed on an option's own
price are polluted by theta and IV; the index is the thing the rule is actually about.

STYLE FOLLOWS THE CANDLE. 1m and 5m are scalps (square off same session, tight bar
limit); 10m through 1h are intraday; 4h and 1d carry overnight as swings. Holding a
1-minute signal for a week would not be testing the 1-minute signal.

COSTS ARE CHARGED, on the real Angel One F&O schedule. This matters more here than on any
other desk: options brokerage is a FLAT Rs20 per order, so on a small premium the round
trip alone can be several percent before the market moves at all. Any strategy that looks
profitable here has already paid for itself.

RATE LIMITS: one candle request per timeframe per cycle (8 total, not 400) and one batched
quote sweep for the distinct option contracts actually held. All 400 strategies share
those fetches.

PAPER. Fills are the live traded premium, not a model. Nothing here places a real order.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    nifty_scalp_equity_collection,
    nifty_scalp_positions_collection,
    nifty_scalp_scores_collection,
    nifty_scalp_signals_collection,
    nifty_scalp_state_collection,
    nifty_scalp_trades_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.angel_fees import option_round_trip
from app.services.call_engine import IST
from app.services.nifty_scalp_strategies import (
    CATALOG,
    TEMPLATES,
    CATALOG_BY_ID,
    TIMEFRAMES,
    TIMEFRAME_BY_KEY,
    Series,
    evaluate,
    from_rows,
    resample,
)

logger = logging.getLogger("nifty_scalp")

INDEX = "NIFTY"
STRIKE_STEP = 50.0
PER_STRATEGY_CAPITAL = float(os.getenv("NS_PER_STRATEGY_CAPITAL", "200000"))
TOTAL_CAPITAL = PER_STRATEGY_CAPITAL * len(CATALOG)          # Rs8 crore over 400
ENABLED = os.getenv("NS_ENABLED", "1").lower() not in ("0", "false", "")
QUOTE_PACE = float(os.getenv("NS_QUOTE_PACE", "0.15"))
# Angel's HISTORICAL endpoint is rate-limited far harder than its quote endpoints — 8
# candle requests at quote pacing returned 403 on three of them. Candles get their own,
# slower pace plus one retry, because a missing timeframe silently disables 50 strategies.
CANDLE_PACE = float(os.getenv("NS_CANDLE_PACE", "1.0"))
CANDLE_RETRY_WAIT = float(os.getenv("NS_CANDLE_RETRY", "2.5"))
SQUAREOFF = os.getenv("NS_SQUAREOFF", "15:15")
ENTRY_CUTOFF = os.getenv("NS_ENTRY_CUTOFF", "15:05")
SWING_MAX_DAYS = int(os.getenv("NS_SWING_MAX_DAYS", "5"))
# A near-expiry option inside its last day is mostly gamma and decay; entering then is a
# different trade from the one these rules describe.
MIN_DAYS_TO_EXPIRY = int(os.getenv("NS_MIN_DTE", "0"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("NS_DAILY_LOSS_PCT", "0.03"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


# ── market data ────────────────────────────────────────────────────────────────


async def _index_token() -> dict | None:
    return await instruments_collection.find_one(
        {"asset_class": "INDEX", "symbol": INDEX, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
    )


async def load_series() -> dict[str, Series]:
    """One candle request per timeframe. The 4-hour series has no Angel interval, so it
    is aggregated from the 1-hour rows already fetched rather than requested again."""
    inst = await _index_token()
    if not inst:
        return {}
    tok, ex = str(inst["angel_token"]), inst.get("angel_exchange") or "NSE"
    now = datetime.now(IST)
    out: dict[str, Series] = {}
    raw: dict[str, list] = {}
    for tf in TIMEFRAMES:
        if tf.aggregate > 1 and tf.resolution in raw:
            rows = raw[tf.resolution]
        else:
            frm = (now - timedelta(days=tf.lookback_days)).strftime("%Y-%m-%d %H:%M")
            to = now.strftime("%Y-%m-%d %H:%M")
            rows = None
            for attempt in (1, 2):
                try:
                    rows = await angel_client.candles(ex, tok, tf.resolution, frm, to)
                    break
                except AngelAPIError as exc:
                    if attempt == 1:
                        await asyncio.sleep(CANDLE_RETRY_WAIT)
                        continue
                    logger.warning("nifty-scalp: candles failed for %s (%s)", tf.key, exc)
            if rows is None:
                continue
            raw[tf.resolution] = rows
            await asyncio.sleep(CANDLE_PACE)
        s = from_rows(rows)
        out[tf.key] = resample(s, tf.aggregate) if tf.aggregate > 1 else s
    return out


async def near_expiry() -> str | None:
    """The nearest NIFTY expiry at least MIN_DAYS_TO_EXPIRY away that is actually listed.
    Reading the instrument master rather than assuming "every Thursday", because the
    exchange skips and shifts weeklies around holidays."""
    today = _today()
    cutoff = (date.fromisoformat(today) + timedelta(days=MIN_DAYS_TO_EXPIRY)).isoformat()
    rows = await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": INDEX,
                   "expiry": {"$gte": cutoff}})
    return min(rows) if rows else None


async def _atm_contract(expiry: str, spot: float, kind: str) -> dict | None:
    target = round(spot / STRIKE_STEP) * STRIKE_STEP
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": INDEX, "expiry": expiry,
         "option_type": kind, "angel_token": {"$ne": None}},
        {"symbol": 1, "strike": 1, "option_type": 1, "lot_size": 1,
         "angel_token": 1, "angel_exchange": 1, "angel_tradingsymbol": 1})]
    return min(rows, key=lambda r: abs(r["strike"] - target)) if rows else None


async def _quote_options(contracts: list[dict]) -> dict[str, float]:
    """Batched LTP for the distinct option tokens in play. Most of the 400 strategies
    converge on the same one or two ATM contracts, so this is a handful of tokens."""
    by_ex: dict[str, list[str]] = {}
    for c in contracts:
        by_ex.setdefault(c.get("angel_exchange") or "NFO", []).append(str(c["angel_token"]))
    out: dict[str, float] = {}
    for ex, toks in by_ex.items():
        for i in range(0, len(toks), 50):
            try:
                q = await angel_client.full_quote({ex: toks[i:i + 50]})
            except AngelAPIError as exc:
                logger.warning("nifty-scalp: option quote failed (%s)", exc)
                continue
            for tok, row in q.items():
                if row.get("ltp"):
                    out[str(tok)] = float(row["ltp"])
            await asyncio.sleep(QUOTE_PACE)
    return out


async def _spot() -> float | None:
    inst = await _index_token()
    if not inst:
        return None
    try:
        q = await angel_client.full_quote({inst.get("angel_exchange") or "NSE": [str(inst["angel_token"])]})
    except AngelAPIError:
        return None
    for row in q.values():
        if row.get("ltp"):
            return float(row["ltp"])
    return None


# ── capital ────────────────────────────────────────────────────────────────────


async def _realized(strategy_id: str) -> float:
    total = 0.0
    async for p in nifty_scalp_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _deployed(strategy_id: str) -> float:
    total = 0.0
    async for p in nifty_scalp_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed") or 0.0
    return total


async def today_pnl() -> float:
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    total = 0.0
    async for p in nifty_scalp_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in nifty_scalp_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * TOTAL_CAPITAL
    return {
        "breaker_tripped": pnl <= -limit,
        "today_pnl": round(pnl, 2),
        "today_roi_pct": round(pnl / TOTAL_CAPITAL * 100, 4) if TOTAL_CAPITAL else 0.0,
        "daily_loss_limit": round(limit, 2),
    }


async def _update_score(strategy_id: str) -> None:
    st = CATALOG_BY_ID.get(strategy_id)
    if st is None:
        return
    closed = [p async for p in nifty_scalp_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "gross_pnl": 1, "fees": 1})]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net = sum(p.get("realized_pnl") or 0 for p in closed)
    fees = sum(p.get("fees") or 0 for p in closed)
    gross = sum(p.get("gross_pnl") or 0 for p in closed)
    await nifty_scalp_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id, "name": st.name, "template": st.template,
            "family": st.family, "timeframe": st.timeframe, "style": st.style,
            "trades": trades, "wins": wins,
            "win_rate": round(wins / trades, 4) if trades else 0.0,
            "net_pnl": round(net, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
            "roi_pct": round(net / PER_STRATEGY_CAPITAL * 100, 3),
            "allocated_capital": round(PER_STRATEGY_CAPITAL + net, 2),
            "updated_at": _now(),
        }},
        upsert=True,
    )


# ── trading ────────────────────────────────────────────────────────────────────


async def _open(st, contract: dict, premium: float, spot: float, expiry: str,
                direction: int, bar_ts) -> bool:
    if await nifty_scalp_positions_collection.find_one({"strategy_id": st.strategy_id, "status": "OPEN"}):
        return False  # one directional bet per strategy at a time
    lot = int(contract.get("lot_size") or 75)
    cash = PER_STRATEGY_CAPITAL + await _realized(st.strategy_id) - await _deployed(st.strategy_id)
    per_lot = premium * lot
    lots = int(min(PER_STRATEGY_CAPITAL, cash) // per_lot) if per_lot > 0 else 0
    if lots < 1:
        return False
    tf = TIMEFRAME_BY_KEY[st.timeframe]
    await nifty_scalp_positions_collection.insert_one({
        "position_id": uuid4().hex[:12],
        "strategy_id": st.strategy_id, "strategy_name": st.name, "template": st.template,
        "family": st.family, "timeframe": st.timeframe, "style": st.style,
        "symbol": contract["symbol"], "option_type": contract["option_type"],
        "strike": contract["strike"], "expiry": expiry,
        "angel_token": str(contract["angel_token"]),
        "angel_exchange": contract.get("angel_exchange") or "NFO",
        "direction": "BULLISH" if direction > 0 else "BEARISH",
        "side": "BUY", "lots": lots, "lot_size": lot, "qty": lots * lot,
        "entry_premium": round(premium, 2), "ltp": round(premium, 2),
        "entry_spot": round(spot, 2),
        "capital_deployed": round(premium * lots * lot, 2),
        "target_premium": round(premium * (1 + tf.target_pct / 100), 2),
        "stop_premium": round(premium * (1 - tf.stop_pct / 100), 2),
        "max_hold_bars": tf.max_hold_bars, "bars_held": 0,
        "unrealized_pnl": 0.0, "realized_pnl": None, "gross_pnl": None,
        "fees": None, "fee_breakdown": None,
        "exit_premium": None, "exit_reason": None, "status": "OPEN",
        "bar_ts": str(bar_ts),
        "opened_at": _now(), "opened_on": _today(), "closed_at": None, "closed_on": None,
        "updated_at": _now(),
    })
    return True


async def manage() -> int:
    positions = [p async for p in nifty_scalp_positions_collection.find({"status": "OPEN"})]
    if not positions:
        return 0
    seen: dict[str, dict] = {}
    for p in positions:
        seen.setdefault(p["angel_token"], {"angel_token": p["angel_token"],
                                           "angel_exchange": p.get("angel_exchange")})
    prices = await _quote_options(list(seen.values()))

    eod = _hhmm() >= SQUAREOFF
    today = _today()
    closed = 0
    touched: set[str] = set()
    for p in positions:
        ltp = prices.get(p["angel_token"])
        if ltp is None:
            continue
        qty = p["qty"]
        gross = round((ltp - p["entry_premium"]) * qty, 2)
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
            await nifty_scalp_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
                "strategy_name": p["strategy_name"], "timeframe": p["timeframe"],
                "symbol": p["symbol"], "direction": p["direction"], "lots": p["lots"],
                "entry_premium": p["entry_premium"], "exit_premium": round(ltp, 2),
                "gross_pnl": gross, "fees": fb.total, "realized_pnl": net,
                "exit_reason": reason, "opened_at": p["opened_at"], "closed_at": _now(),
            })
        await nifty_scalp_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})

    for sid in touched:
        await _update_score(sid)
    return closed


async def scan() -> dict:
    """Evaluate all 400 strategies against this cycle's candles and open what fires."""
    notes: list[str] = []
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "signals": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L Rs{breaker['today_pnl']:,.0f} crossed the "
            f"Rs{breaker['daily_loss_limit']:,.0f} limit. No new positions; open ones still managed."]}
    if _hhmm() >= ENTRY_CUTOFF:
        return {"opened": 0, "signals": 0, "notes": [
            f"Past the {ENTRY_CUTOFF} IST entry cutoff — open positions still managed."]}

    series = await load_series()
    if not series:
        return {"opened": 0, "signals": 0, "notes": ["No NIFTY candles this cycle."]}
    spot = await _spot()
    if not spot:
        spot = series[max(series, key=lambda k: len(series[k]))].c[-1]
        notes.append("Angel did not quote the index — using the last candle close as spot.")
    expiry = await near_expiry()
    if not expiry:
        return {"opened": 0, "signals": 0, "notes": ["No listed NIFTY expiry found."]}

    # A strategy may take ONE trade per closed bar. Without this the desk re-evaluates
    # the same 1-minute bar every 180-second tick and re-enters the instant a position
    # closes, which is how a book pays fees all day for a single signal. This is the same
    # failure that cost the Live Intraday desk more in costs than its edge was worth.
    bar_state = await nifty_scalp_state_collection.find_one({"_id": "bars"}) or {}
    last_bar: dict = bar_state.get("last", {})

    fired = [(st, d) for st in CATALOG
             if st.timeframe in series
             for d in (evaluate(st, series[st.timeframe]),) if d]
    if not fired:
        return {"opened": 0, "signals": 0, "notes": notes + ["No strategy fired this cycle."]}

    contracts: dict[str, dict] = {}
    for kind in {"CE" if d > 0 else "PE" for _, d in fired}:
        c = await _atm_contract(expiry, spot, kind)
        if c:
            contracts[kind] = c
    if not contracts:
        return {"opened": 0, "signals": len(fired), "notes": notes + ["No ATM contract listed."]}
    prices = await _quote_options(list(contracts.values()))

    opened = 0
    fresh: dict[str, str] = {}
    for st, d in fired:
        bar_ts = str(series[st.timeframe].ts[-1])
        if last_bar.get(st.strategy_id) == bar_ts:
            continue  # already acted on this bar
        fresh[st.strategy_id] = bar_ts
        kind = "CE" if d > 0 else "PE"
        c = contracts.get(kind)
        premium = prices.get(str(c["angel_token"])) if c else None
        await nifty_scalp_signals_collection.insert_one({
            "ts": _now(), "on": _today(), "strategy_id": st.strategy_id,
            "strategy_name": st.name, "timeframe": st.timeframe,
            "direction": "BULLISH" if d > 0 else "BEARISH",
            "spot": round(spot, 2), "option": c["symbol"] if c else None,
            "premium": round(premium, 2) if premium else None,
        })
        if c and premium and await _open(st, c, premium, spot, expiry, d, bar_ts):
            opened += 1
    if fresh:
        await nifty_scalp_state_collection.update_one(
            {"_id": "bars"}, {"$set": {f"last.{k}": v for k, v in fresh.items()}}, upsert=True)
    return {"opened": opened, "signals": len(fired), "acted": len(fresh), "notes": notes}


# ── reporting ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = realized = unrealized = fees = 0.0
    async for p in nifty_scalp_positions_collection.find(
        {"status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1}
    ):
        deployed += p.get("capital_deployed") or 0.0
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in nifty_scalp_positions_collection.find(
        {"status": {"$ne": "OPEN"}}, {"realized_pnl": 1, "fees": 1}
    ):
        realized += p.get("realized_pnl") or 0.0
        fees += p.get("fees") or 0.0
    equity = TOTAL_CAPITAL + realized + unrealized
    state = await nifty_scalp_state_collection.find_one({"_id": "engine"}) or {}
    return {
        "mode": "paper", "enabled": ENABLED,
        "initial_capital": TOTAL_CAPITAL,
        "per_strategy_capital": PER_STRATEGY_CAPITAL,
        "strategy_count": len(CATALOG),
        "timeframes": [{"key": t.key, "label": t.label, "style": t.style,
                        "target_pct": t.target_pct, "stop_pct": t.stop_pct} for t in TIMEFRAMES],
        "deployed_capital": round(deployed, 2),
        "available_cash": round(TOTAL_CAPITAL + realized - deployed, 2),
        "realized_pnl": round(realized, 2),
        "gross_realized_pnl": round(realized + fees, 2),
        "total_fees": round(fees, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(equity, 2),
        "roi_pct": round((equity - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100, 4) if TOTAL_CAPITAL else 0.0,
        "open_positions": await nifty_scalp_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": await nifty_scalp_positions_collection.count_documents({"status": {"$ne": "OPEN"}}),
        "expiry": await near_expiry(),
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
        "last_notes": state.get("last_notes", []),
        **(await breaker_state()),
    }


async def leaderboard(timeframe: str | None = None, limit: int = 1000) -> list[dict]:
    q = {"timeframe": timeframe} if timeframe else {}
    scores = {s["strategy_id"]: s async for s in nifty_scalp_scores_collection.find(q)}
    rows = []
    for st in CATALOG:
        if timeframe and st.timeframe != timeframe:
            continue
        sc = scores.get(st.strategy_id) or {}
        rows.append({
            "strategy_id": st.strategy_id, "name": st.name, "template": st.template,
            "family": st.family, "timeframe": st.timeframe, "style": st.style,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
            "gross_pnl": round(sc.get("gross_pnl", 0.0) or 0.0, 2),
            "fees": round(sc.get("fees", 0.0) or 0.0, 2),
            "roi_pct": round(sc.get("roi_pct", 0.0) or 0.0, 3),
        })
    rows.sort(key=lambda r: (-r["net_pnl"], r["name"]))
    return rows[:limit]


async def timeframe_stats() -> list[dict]:
    """Which HORIZON is working, aggregated over its 50 strategies — the question this
    desk exists to answer."""
    out = []
    for tf in TIMEFRAMES:
        agg = {"timeframe": tf.key, "label": tf.label, "style": tf.style,
               "strategies": len(TEMPLATES), "trades": 0, "wins": 0, "net_pnl": 0.0,
               "fees": 0.0, "gross_pnl": 0.0,
               "capital": PER_STRATEGY_CAPITAL * len(TEMPLATES)}
        async for s in nifty_scalp_scores_collection.find({"timeframe": tf.key}):
            agg["trades"] += s.get("trades", 0) or 0
            agg["wins"] += s.get("wins", 0) or 0
            agg["net_pnl"] += s.get("net_pnl", 0.0) or 0.0
            agg["fees"] += s.get("fees", 0.0) or 0.0
            agg["gross_pnl"] += s.get("gross_pnl", 0.0) or 0.0
        agg["win_rate"] = round(agg["wins"] / agg["trades"], 4) if agg["trades"] else 0.0
        agg["roi_pct"] = round(agg["net_pnl"] / agg["capital"] * 100, 4)
        for k in ("net_pnl", "fees", "gross_pnl"):
            agg[k] = round(agg[k], 2)
        out.append(agg)
    return out


async def positions(status: str = "OPEN", limit: int = 300, timeframe: str | None = None) -> list[dict]:
    q: dict = {"status": status.upper()} if status.upper() != "ALL" else {}
    if timeframe:
        q["timeframe"] = timeframe
    cur = nifty_scalp_positions_collection.find(q).sort("opened_at", -1).limit(limit)
    out = []
    async for d in cur:
        d.pop("_id", None)
        for k in ("opened_at", "closed_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


async def signals(limit: int = 200) -> list[dict]:
    out = []
    async for d in nifty_scalp_signals_collection.find({}).sort("ts", -1).limit(limit):
        d.pop("_id", None)
        d["ts"] = d["ts"].isoformat()
        out.append(d)
    return out


async def daily(limit: int = 60) -> list[dict]:
    buckets: dict[str, dict] = {}
    async for p in nifty_scalp_positions_collection.find(
        {"status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "gross_pnl": 1, "fees": 1, "closed_on": 1},
    ):
        day = p.get("closed_on")
        if not day:
            continue
        b = buckets.setdefault(day, {"date": day, "trades": 0, "wins": 0,
                                     "realized_pnl": 0.0, "fees": 0.0, "gross_pnl": 0.0})
        net = p.get("realized_pnl") or 0.0
        b["trades"] += 1
        b["wins"] += 1 if net > 0 else 0
        b["realized_pnl"] += net
        b["fees"] += p.get("fees") or 0.0
        b["gross_pnl"] += p.get("gross_pnl") or 0.0
    rows = sorted(buckets.values(), key=lambda r: r["date"], reverse=True)[:limit]
    for r in rows:
        for k in ("realized_pnl", "fees", "gross_pnl"):
            r[k] = round(r[k], 2)
        r["win_rate"] = round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0
        r["roi_pct"] = round(r["realized_pnl"] / TOTAL_CAPITAL * 100, 4)
    return rows


async def run_cycle() -> dict:
    if not ENABLED:
        return {"opened": 0, "closed": 0, "notes": ["desk disabled"]}
    closed = await manage()
    result = await scan()
    snap = await summary()
    await nifty_scalp_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "fees": snap["total_fees"],
        "roi_pct": snap["roi_pct"], "open_positions": snap["open_positions"],
    })
    await nifty_scalp_state_collection.update_one(
        {"_id": "engine"},
        {"$set": {"last_run_at": _now(), "last_opened": result["opened"],
                  "last_closed": closed, "last_signals": result["signals"],
                  "last_notes": result["notes"]}},
        upsert=True,
    )
    return {"opened": result["opened"], "closed": closed,
            "signals": result["signals"], "acted": result.get("acted", 0),
            "notes": result["notes"]}
