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

FILLS (2026-10-10). This desk used to close every trade at whatever LTP its three-minute
poll happened to see, so price that had run PAST a target was booked as profit, and it
charged no slippage. Over its first four sessions that turned a desk losing Rs23 lakh into a
reported +Rs53 lakh (INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md, D1). It now fills by the
tournament's own rules (`intraday_fills`): exits walk the Angel stream's minute bars since the
last check, a target fills AT the target (a limit order), a stop at the stop or at a gap's
open, the stop assumed first when one minute crosses both; every market fill pays slippage
by the name's liquidity. Without stream bars for a name it falls back to its quote, still
filling a target at the target, never beyond it.

RISK CAPS (2026-10-10). 504 strategies on a 25-name universe meant ~20 strategies per name,
and nothing stopped them stacking: 88% of the first four sessions' trades duplicated another
strategy's bet, and one idea was taken by 32 strategies at once (Rs3.18 crore on a single
trade). Now at most MAX_STRATEGIES_PER_SYMBOL strategies hold one name at a time; competing
signals are ranked by how far their target sits beyond costs (longer timeframes first), never
by catalog order; and a desk loss breaker stops new entries for the session.

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
from app.services import intraday_session as session
from app.services import intraday_universe
from app.services.intraday_fills import adverse, scan_exit, slippage_bp, stream_ltp
from app.services.call_engine import IST, _scored_daily_symbols
from app.services.nifty_scalp_strategies import (
    TEMPLATES as _BASE_TEMPLATES, Series, from_rows, resample)
from app.services.vcp_templates import VCP_TEMPLATES, allowed_on

# The base catalog plus the VCP family. Appended rather than merged into
# nifty_scalp_strategies so the NIFTY option desk keeps exactly the 63 it had —
# a VCP is a multi-week accumulation pattern and means nothing on a near-expiry
# option premium. Duplicate names are skipped, so this stays idempotent.
_EXISTING = {t[0] for t in _BASE_TEMPLATES}
TEMPLATES = list(_BASE_TEMPLATES) + [t for t in VCP_TEMPLATES if t[0] not in _EXISTING]

logger = logging.getLogger("intraday_pattern")

PER_STRATEGY_CAPITAL = float(os.getenv("PAT_PER_STRATEGY_CAPITAL", "1000000"))   # Rs10 lakh
UNIVERSE_SIZE = int(os.getenv("PAT_UNIVERSE", "25"))
CANDLE_PACE = float(os.getenv("PAT_CANDLE_PACE", "1.0"))
ENABLED = os.getenv("PAT_ENABLED", "1").lower() not in ("0", "false", "")
# The square-off is per SYMBOL now (see `intraday_session`): 15:05 for NSE closing-auction
# stocks, 15:12 for the rest. SQUAREOFF is kept only for anything that still prints it.
SQUAREOFF = session.NONCAS_SQUAREOFF_HHMM
ENTRY_CUTOFF = os.getenv("PAT_ENTRY_CUTOFF", session.ENTRY_CUTOFF_HHMM)
SWING_MAX_DAYS = int(os.getenv("PAT_SWING_MAX_DAYS", "5"))
MAX_FETCH_PER_CYCLE = int(os.getenv("PAT_MAX_FETCH", "40"))
# The tournament's own limits (intraday_v2_engine), so the two desks carry the same risk shape.
MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("PAT_MAX_STRATEGIES_PER_SYMBOL", "2"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("PAT_DAILY_LOSS_PCT", "0.03"))


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
            # A template that is not the pattern it is named after on this candle is not
            # created at all, rather than created and quietly mislabelled.
            if not allowed_on(name, tf.key):
                continue
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

# The cache is keyed by (symbol, timeframe) and used to be evicted by nothing at all: an
# entry was replaced only when that exact pair was fetched again. The universe is the top
# 25 symbols by score and it ROTATES, so yesterday's symbols kept their candles for ever
# while today's were added beside them.
#
# Measured on production 2026-10-02: 164 live entries holding 343,642 Bar objects — the
# single largest thing on a heap that had climbed to 90% of the container's limit in nine
# hours. One series is a timeframe's whole lookback (the 1m series is five days of
# minutes), so a handful of entries is tens of megabytes; the ENTRY count being small is
# exactly what made this invisible.
#
# Two entries per (symbol, timeframe) the current universe can produce, so a full rotation
# can be held at once and nothing in flight is ever dropped.
CACHE_MAX = int(os.getenv("PAT_CACHE_MAX", str(UNIVERSE_SIZE * len(TIMEFRAMES) * 2)))

# How far past its own TTL an entry may sit before it is dropped. Generous on purpose:
# `_series` deliberately returns a STALE series when the per-cycle fetch budget is spent,
# so same-cycle staleness is a feature and must survive pruning. A 1m series four TTLs old
# is 4 minutes stale and still a reasonable fallback; one from yesterday is not.
CACHE_STALE_MULTIPLE = float(os.getenv("PAT_CACHE_STALE_MULT", "4"))


def _prune_cache(now: float) -> None:
    """Drop long-dead entries, then the oldest until the cache is within its cap.

    Called on every write, which is the only place the cache can grow."""
    for key in [k for k, (ts, _) in _cache.items()
                if now - ts >= max(TF_BY_KEY[k[1]].ttl if k[1] in TF_BY_KEY else 3600, 1)
                * CACHE_STALE_MULTIPLE]:
        _cache.pop(key, None)
    while len(_cache) > CACHE_MAX:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)


def cache_stats() -> dict:
    """Surfaced so this can never quietly grow again unnoticed — the same treatment the
    screener's bar cache got after it ate a container."""
    return {
        "entries": len(_cache),
        "max_entries": CACHE_MAX,
        "bars_held": sum(len(getattr(v, "bars", v) or []) for _, v in _cache.values()),
        "stale_multiple": CACHE_STALE_MULTIPLE,
    }


async def _universe() -> list[dict]:
    scored = await _scored_daily_symbols()
    syms = [s for s, *_ in scored[:UNIVERSE_SIZE]]
    if not syms:
        return []
    return [d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": syms}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1, "security_id": 1,
         "exchange_segment": 1, "lot_size": 1})]


def _base_minutes(tf: TF) -> int:
    return 375 if tf.resolution == "D" else int(tf.resolution)


def _closed(s: Series, minutes: int, now: datetime) -> Series:
    """Drop trailing bars that have not finished. Angel's candle endpoint returns the bar
    that is still forming; evaluating it fires a rule on a half-built candle — a different
    rule from the one a backtest of closed bars measures — and the old "one entry per
    closed bar" guard keyed on that forming bar. A bar ends `minutes` after it starts,
    clipped to the 15:30 close (so a daily bar ends at 15:30 of its own day)."""
    keep = len(s)
    while keep:
        try:
            start = datetime.fromisoformat(str(s.ts[keep - 1]))
        except (TypeError, ValueError):
            break
        if start.tzinfo is None:
            start = start.replace(tzinfo=IST)
        close = start.astimezone(IST).replace(hour=15, minute=30, second=0, microsecond=0)
        # Angel stamps a DAILY candle at 00:00, so a daily bar ends at its own 15:30.
        end = close if minutes >= 375 else min(start + timedelta(minutes=minutes), close)
        if end <= now:
            break
        keep -= 1
    if keep == len(s):
        return s
    return Series(s.ts[:keep], s.o[:keep], s.h[:keep], s.l[:keep], s.c[:keep], s.v[:keep])


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
    s = _closed(from_rows(rows), _base_minutes(tf), now)
    if tf.aggregate > 1:
        s = _closed(resample(s, tf.aggregate, _base_minutes(tf)),
                    _base_minutes(tf) * tf.aggregate, now)
    now = time.monotonic()
    _cache[key] = (now, s)
    _prune_cache(now)
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


async def _turnover() -> dict[str, float]:
    """Each name's daily traded value (Rs crore) from today's universe — what sets its
    slippage. A name outside the top 200 gets the thinnest bucket, which is the honest default."""
    try:
        return {m["symbol"]: m.get("turnover_cr") for m in await intraday_universe.members()}
    except Exception:  # noqa: BLE001
        return {}


async def _holders(symbol: str) -> int:
    """How many strategies hold `symbol` right now."""
    return await pattern_positions_collection.count_documents({"symbol": symbol, "status": "OPEN"})


async def _open(st: PatternStrategy, inst: dict, price: float, direction: int, bar_ts,
                turnover_cr: float | None = None, source: str = "quote") -> bool:
    if await pattern_positions_collection.find_one(
        {"strategy_id": st.strategy_id, "status": "OPEN"}
    ):
        return False
    if await _holders(inst["symbol"]) >= MAX_STRATEGIES_PER_SYMBOL:
        _skips["symbol_full"] = _skips.get("symbol_full", 0) + 1
        return False
    tf = TF_BY_KEY[st.timeframe]
    sign = 1 if direction > 0 else -1
    side = "BUY" if sign > 0 else "SELL"
    bp = slippage_bp(turnover_cr)
    fill = adverse(price, side, bp, opening=True)          # an entry is a market order
    cash = await _cash(st.strategy_id)
    qty = int(min(PER_STRATEGY_CAPITAL, cash) // fill) if fill > 0 else 0
    if qty < 1:
        return False
    await pattern_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": st.strategy_id,
        "strategy_name": st.name, "template": st.template, "family": st.family,
        "timeframe": st.timeframe, "style": st.style,
        "symbol": inst["symbol"], "side": side,
        "entry_price": round(fill, 2), "signal_price": round(price, 2),
        "fill_basis": f"market @ {price:.2f} ({source}) + {bp:g} bp slippage",
        "slippage_bp": bp, "turnover_cr": turnover_cr,
        "qty": qty, "ltp": round(price, 2), "ltp_source": source,
        "capital_deployed": round(fill * qty, 2),
        # Levels from the FILL: a target measured from a price the desk never got would
        # quietly award it the slippage back.
        "target": round(fill * (1 + sign * tf.target_pct / 100), 2),
        "stoploss": round(fill * (1 - sign * tf.stop_pct / 100), 2),
        "bars_held": 0, "max_hold_bars": tf.max_bars, "bar_ts": str(bar_ts),
        "unrealized_pnl": 0.0, "realized_pnl": None, "gross_pnl": None,
        "fees": None, "fee_breakdown": None, "exit_price": None, "exit_reason": None,
        "checked_through": int(time.time()) // 60 * 60 + 60,   # exits scan from the next minute
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


# Serialises manage between the shared loop and the independent close-out job.
_manage_lock = asyncio.Lock()


def _bars_held(p: dict) -> int:
    """Bars of the position's OWN timeframe since entry, from the clock.

    It used to be `bars_held + 1` on every manage call. The loop calls every 180 s, so the
    count measured how often the loop ran, not how long the trade had lived: a 1-minute
    scalp with a 15-bar limit was held 45 minutes, a 5-minute one with 12 bars was cut at
    36 minutes instead of 60, and calling manage more often would have cut both sooner."""
    tf = TF_BY_KEY.get(p.get("timeframe") or "")
    opened = p.get("opened_at")
    if tf is None or opened is None:
        return (p.get("bars_held") or 0) + 1
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - opened).total_seconds()
    return max(0, int(secs // max(tf.ttl, 1)))


async def manage() -> int:
    """Idempotent: safe to call as often as the close-out job likes."""
    async with _manage_lock:
        await session.ensure_cas()
        return await _manage()


async def _close(p: dict, px: float, reason: str, market: bool, days: int, source: str) -> float:
    """Close at `px`: a level (a target is a limit order — no slippage, never better than
    the level) or a market price (stop, time, end of day) that pays slippage."""
    bp = p.get("slippage_bp")
    bp = slippage_bp(p.get("turnover_cr")) if bp is None else bp
    fill = adverse(px, p["side"], bp, opening=False) if market else px
    sign = 1 if p["side"] == "BUY" else -1
    gross = round(sign * (fill - p["entry_price"]) * p["qty"], 2)
    fb = round_trip(p["entry_price"], fill, p["qty"], side=p["side"],
                    product=product_for(None, days))
    net = round(gross - fb.total, 2)
    today = _today()
    basis = (f"{'market' if market else 'level'} @ {px:.2f} ({source})"
             + (f" - {bp:g} bp" if market else ""))
    await pattern_positions_collection.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 2), "exit_reason": reason,
        "exit_basis": basis, "gross_pnl": gross, "fees": fb.total,
        "fee_breakdown": fb.as_dict(), "realized_pnl": net, "unrealized_pnl": 0.0,
        "ltp": round(px, 2), "closed_at": _now(), "closed_on": today, "updated_at": _now()}})
    await pattern_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
        "strategy_name": p["strategy_name"], "timeframe": p["timeframe"],
        "symbol": p["symbol"], "side": p["side"], "qty": p["qty"],
        "entry_price": p["entry_price"], "exit_price": round(fill, 2),
        "gross_pnl": gross, "fees": fb.total, "realized_pnl": net,
        "exit_reason": reason, "exit_basis": basis,
        "opened_at": p["opened_at"], "closed_at": _now()})
    return net


async def _manage() -> int:
    positions = [p async for p in pattern_positions_collection.find({"status": "OPEN"})]
    if not positions:
        return 0
    # The stream first; the quote endpoint only for names it has nothing fresh on.
    live = {p["symbol"]: stream_ltp(p["symbol"]) for p in positions}
    need = sorted({s for s, v in live.items() if v is None})
    quoted = await _quote(need) if need else {}
    now_ist = datetime.now(IST)
    today = _today()
    closed = 0
    touched: set[str] = set()
    for p in positions:
        sym = p["symbol"]
        ltp = live.get(sym) or quoted.get(sym)
        source = "stream" if live.get(sym) else "quote"
        sign = 1 if p["side"] == "BUY" else -1
        days = (datetime.fromisoformat(today).date()
                - datetime.fromisoformat(p["opened_on"]).date()).days

        # 1. Levels, from the stream's minute bars since the last check: the first level a
        #    minute actually crossed, the stop when one minute crossed both.
        hit = scan_exit(p)
        if hit is not None:
            reason, px, _t = hit
            await _close(p, px, reason, market=(reason == "stoploss"), days=days, source="stream minute")
            touched.add(p["strategy_id"]); closed += 1
            continue
        if ltp is None:
            continue
        # 2. No minute bars for this name: the quote decides THAT a level was crossed, never
        #    the price beyond it — a target fills at the target, as a resting limit order would.
        if sign * (ltp - p["stoploss"]) <= 0:
            await _close(p, ltp, "stoploss", market=True, days=days, source=source)
            touched.add(p["strategy_id"]); closed += 1
            continue
        if sign * (ltp - p["target"]) >= 0:
            await _close(p, p["target"], "target", market=False, days=days, source=source)
            touched.add(p["strategy_id"]); closed += 1
            continue
        # 3. Time: end of day, the swing cap, the scalp's bar limit — market exits.
        bars = _bars_held(p)
        eod = session.squareoff_due(sym, now_ist)
        reason = ("eod" if (p["style"] in ("scalping", "intraday") and (eod or days >= 1))
                  else "max_hold" if (p["style"] == "swing" and days >= SWING_MAX_DAYS)
                  else "time_stop" if (p["style"] == "scalping" and bars >= p["max_hold_bars"])
                  else None)
        if reason:
            await _close(p, ltp, reason, market=True, days=days, source=source)
            touched.add(p["strategy_id"]); closed += 1
            continue
        await pattern_positions_collection.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
            "ltp": round(ltp, 2), "ltp_source": source,
            "unrealized_pnl": round(sign * (ltp - p["entry_price"]) * p["qty"], 2),
            "bars_held": bars, "checked_through": int(time.time()) // 60 * 60,
            "updated_at": _now()}})
    for sid in touched:
        await _update_score(sid)
    return closed


async def _today_pnl() -> float:
    total = 0.0
    async for p in pattern_positions_collection.find(
            {"$or": [{"status": "OPEN"}, {"closed_on": _today()}]},
            {"status": 1, "realized_pnl": 1, "unrealized_pnl": 1}):
        total += (p.get("unrealized_pnl") if p.get("status") == "OPEN" else p.get("realized_pnl")) or 0.0
    return total


_skips: dict[str, int] = {}


def _priority(st: PatternStrategy) -> tuple:
    """Which of several signals on one name gets one of its few slots.

    Not catalog order — that let the 1-minute strategies, evaluated first, take every slot.
    A trade's costs are roughly fixed in basis points, so the signal whose target sits
    furthest beyond them is the one most able to pay them: larger target first (longer
    timeframes), then strategy id so the choice is reproducible."""
    return (-TF_BY_KEY[st.timeframe].target_pct, st.strategy_id)


async def scan() -> dict:
    if _hhmm() >= ENTRY_CUTOFF:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"Past the {ENTRY_CUTOFF} IST entry cutoff — open positions still managed."]}
    today_pnl = await _today_pnl()
    if today_pnl <= -DAILY_LOSS_BREAKER_PCT * TOTAL_CAPITAL:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"DAILY LOSS BREAKER — today's P&L Rs{today_pnl:,.0f} is past "
            f"{DAILY_LOSS_BREAKER_PCT:.0%} of the desk. No new entries; open positions still managed."]}
    universe = await _universe()
    if not universe:
        return {"opened": 0, "evaluated": 0, "notes": ["No scored symbols to trade."]}

    state = await pattern_state_collection.find_one({"_id": "bars"}) or {}
    last_bar: dict = state.get("last", {})
    budget = [MAX_FETCH_PER_CYCLE]
    prices = await _quote([i["symbol"] for i in universe])
    turnover = await _turnover()
    _skips.clear()

    evaluated = 0
    fresh: dict[str, str] = {}
    cands: list[tuple] = []
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
                cands.append((_priority(st), st, inst, px, d, bar_ts))

    opened = 0
    for _prio, st, inst, px, d, bar_ts in sorted(cands, key=lambda c: c[0]):
        if await _open(st, inst, px, d, bar_ts, turnover.get(inst["symbol"]), "quote"):
            opened += 1
    if fresh:
        await pattern_state_collection.update_one(
            {"_id": "bars"}, {"$set": {f"last.{k}": v for k, v in fresh.items()}}, upsert=True)
    notes = []
    if _skips.get("symbol_full"):
        notes.append(f"{_skips['symbol_full']} signal(s) skipped: their name already had "
                     f"{MAX_STRATEGIES_PER_SYMBOL} strategies in it")
    return {"opened": opened, "evaluated": evaluated, "signals": len(cands),
            "symbols": len(universe), "fetch_budget_left": budget[0], "notes": notes}


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


# How many strategies the catalog ACTUALLY holds on each candle.
#
# THIS IS NOT `len(TEMPLATES)`. That is the number of templates; `_build()` then drops any
# template that is not its own pattern on a given candle (`allowed_on`), so the count
# varies: 63 on 1m and 5m, 70 on 15m through 4h, 72 on 1d — 548 in total, not 8 x 72 = 576.
# Charging every candle for all 72 put 28 strategies' worth of capital on the desk that
# does not exist, and since ROI divides by that capital, every row read closer to zero than
# it was: 1m's true -0.68% showed as -0.59%, and only 1d (where all 72 do exist) was right.
_STRATEGIES_PER_TF: dict[str, int] = {}
for _st in CATALOG:
    _STRATEGIES_PER_TF[_st.timeframe] = _STRATEGIES_PER_TF.get(_st.timeframe, 0) + 1


async def timeframe_stats() -> list[dict]:
    out = []
    for tf in TIMEFRAMES:
        n = _STRATEGIES_PER_TF.get(tf.key, 0)
        agg = {"timeframe": tf.key, "label": tf.label, "style": tf.style,
               "strategies": n, "trades": 0, "wins": 0,
               "net_pnl": 0.0, "fees": 0.0,
               "capital": PER_STRATEGY_CAPITAL * n}
        async for s in pattern_scores_collection.find({"timeframe": tf.key}):
            agg["trades"] += s.get("trades", 0) or 0
            agg["wins"] += s.get("wins", 0) or 0
            agg["net_pnl"] += s.get("net_pnl", 0.0) or 0.0
            agg["fees"] += s.get("fees", 0.0) or 0.0
        agg["win_rate"] = round(agg["wins"] / agg["trades"], 4) if agg["trades"] else 0.0
        agg["roi_pct"] = round(agg["net_pnl"] / agg["capital"] * 100, 4) if agg["capital"] else 0.0
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
