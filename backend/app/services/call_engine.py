"""Shared daily-scan helpers for the trading desks.

Originated as the Trading Calls generation engine; that module is gone, but the
pieces it built for its own scan are now the common ground under a dozen desks —
Intraday Lab, Live Intraday, Live Trading, the pattern engines, Momentum, Swing,
NIFTY Scalp and the schedulers all import from here:

- `technical_score`: EMA trend / RSI / MACD / ROC / Donchian-breakout scoring over
  daily bars, returning (score, reasons, atr14).
- `_scored_daily_symbols`: the cached, periodically-refreshed list of locally
  backfilled symbols ranked by that score — the candidate universe every desk
  starts its day from.
- `_quote_batch`: Dhan-first, Angel-fallback batched quotes.
- `IST` / `INDICES`: the timezone and index list the whole app shares.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app.core.db import instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from app.services.dhan_client import DhanAPIError, DhanClient
from strategy_service.indicators import atr, donchian, ema, macd, roc, rsi
from tradingai_shared.domain import Bar

logger = logging.getLogger("call_engine")

IST = timezone(timedelta(hours=5, minutes=30))

INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


def _avg_volume(bars: list[Bar], n: int = 20) -> float:
    rows = bars[-n:]
    return sum(b.volume for b in rows) / max(len(rows), 1)


def _avg_turnover(bars: list[Bar], n: int = 20) -> float:
    rows = bars[-n:]
    if not rows:
        return 0.0
    return sum(b.close * b.volume for b in rows) / len(rows)


# --------------------------------------------------------------------------------
# Technical scan (stocks, futures direction, commodities)
# --------------------------------------------------------------------------------


def technical_score(bars: list[Bar]) -> tuple[float, list[str], float] | None:
    """Composite score in [-1, 1] from daily bars, with human-readable reasons and
    ATR(14) for target/stop sizing. None when there is not enough history."""
    if len(bars) < 60:
        return None
    closes = [b.close for b in bars]
    close = closes[-1]

    ema20, ema50 = ema(closes, 20), ema(closes, 50)
    rsi14 = rsi(closes, 14)
    _, macd_signal = macd(closes)
    macd_line = ema(closes, 12)[-1] - ema(closes, 26)[-1]
    macd_hist = macd_line - macd_signal[-1]
    roc20 = roc(closes, 20)
    upper, lower = donchian(bars, 20)
    atr14 = atr(bars, 14)[-1]

    score, reasons = 0.0, []
    if ema20[-1] > ema50[-1]:
        score += 0.25
        reasons.append("EMA20 above EMA50 (uptrend)")
    else:
        score -= 0.25
        reasons.append("EMA20 below EMA50 (downtrend)")
    if close > ema20[-1]:
        score += 0.15
        reasons.append("price above EMA20")
    else:
        score -= 0.15
        reasons.append("price below EMA20")

    r = rsi14[-1]
    if r >= 60:
        score += 0.20
        reasons.append(f"RSI {r:.0f} strong")
    elif r >= 55:
        score += 0.10
        reasons.append(f"RSI {r:.0f} firm")
    elif r <= 40:
        score -= 0.20
        reasons.append(f"RSI {r:.0f} weak")
    elif r <= 45:
        score -= 0.10
        reasons.append(f"RSI {r:.0f} soft")

    if macd_hist > 0:
        score += 0.20
        reasons.append("MACD histogram positive")
    else:
        score -= 0.20
        reasons.append("MACD histogram negative")

    m = roc20[-1]
    if m > 2:
        score += 0.10
        reasons.append(f"20d momentum +{m:.1f}%")
    elif m < -2:
        score -= 0.10
        reasons.append(f"20d momentum {m:.1f}%")

    # Donchian proximity: within 1% of the 20d extreme reads as breakout pressure.
    if upper[-1] and close >= upper[-1] * 0.99:
        score += 0.10
        reasons.append("at 20d Donchian high (breakout zone)")
    elif lower[-1] and close <= lower[-1] * 1.01:
        score -= 0.10
        reasons.append("at 20d Donchian low (breakdown zone)")

    return max(-1.0, min(1.0, score)), reasons, atr14


async def _quote_batch(dhan: DhanClient | None, wanted: dict[str, list[int]]) -> dict[tuple[str, str], dict]:
    """{(exchange_segment, security_id): full-quote row} via one Dhan
    /marketfeed/quote call — rows carry last_price, day ohlc and volume, which is
    what the intraday setups need. Empty dict when no client / expired token, so
    intraday families are skipped honestly rather than run on stale data."""
    if not wanted:
        return {}
    out: dict[tuple[str, str], dict] = {}
    if dhan is not None:
        try:
            raw = await dhan.quote_data(wanted)
            data = raw.get("data", {}) if isinstance(raw, dict) else {}
            for segment, by_id in (data.items() if isinstance(data, dict) else []):
                for sec_id, payload in (by_id.items() if isinstance(by_id, dict) else []):
                    if isinstance(payload, dict) and payload.get("last_price"):
                        out[(segment, str(sec_id))] = payload
        except (DhanAPIError, Exception):
            pass
    await _angel_fill_quotes(wanted, out)
    return out


async def _angel_fill_quotes(wanted: dict[str, list[int]], out: dict[tuple[str, str], dict]) -> None:
    """Angel-One failover for anything Dhan didn't price — so live quotes keep flowing
    when Dhan's data endpoint is unavailable. Builds the same {last_price, ohlc, volume}
    row shape from Angel FULL quotes, resolving each contract's Angel token from the
    instrument master; contracts without an Angel token are simply left unpriced."""
    missing = [(seg, str(sid)) for seg, ids in wanted.items() for sid in ids if (seg, str(sid)) not in out]
    if not missing or not angel_client.configured():
        return
    docs = {
        (d["exchange_segment"], str(d["security_id"])): d
        async for d in instruments_collection.find(
            {"$or": [{"exchange_segment": seg, "security_id": sid} for seg, sid in missing]},
            {"exchange_segment": 1, "security_id": 1, "angel_token": 1, "angel_exchange": 1},
        )
    }
    by_ex: dict[str, list[str]] = {}
    tok_key: dict[str, tuple[str, str]] = {}
    for seg, sid in missing:
        d = docs.get((seg, sid))
        if d and d.get("angel_token"):
            tok = str(d["angel_token"])
            by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(tok)
            tok_key[tok] = (seg, sid)
    for ex, toks in by_ex.items():
        try:
            for tok, q in (await angel_client.full_quote({ex: toks})).items():
                key = tok_key.get(tok)
                if key and q.get("ltp"):
                    out[key] = {
                        "last_price": q["ltp"],
                        "ohlc": {"open": q.get("open"), "high": q.get("high"), "low": q.get("low")},
                        "volume": q.get("volume") or 0,
                    }
        except AngelAPIError:
            continue


# --------------------------------------------------------------------------------
# STOCK segment
# --------------------------------------------------------------------------------


# The screen is built from DAILY bars, so it can only change once a day. Holding the
# result for a while turns a 500-second scan into one call that every desk in the tick
# shares. Set SCORED_SYMBOLS_TTL=0 to disable.
SCORED_TTL = float(os.getenv("SCORED_SYMBOLS_TTL", "1800"))
_scored_cache: dict = {"at": 0.0, "data": None}
_scored_lock = asyncio.Lock()


_scored_task: asyncio.Task | None = None


async def _refresh_scored() -> None:
    """Rebuild the screen in the background. Only ever one at a time."""
    global _scored_task
    async with _scored_lock:
        try:
            data = await _scan_daily_symbols()
            _scored_cache.update({"at": time.monotonic(), "data": data})
        except Exception:  # noqa: BLE001 - a failed rebuild must not kill the scheduler
            logger.exception("daily screen rebuild failed; keeping the previous one")
        finally:
            _scored_task = None


async def _scored_daily_symbols(force: bool = False):
    """(symbol, score, reasons, atr14, bars) for every non-index symbol with daily bars.

    NEVER BLOCKS. Returns the last good screen immediately and rebuilds in the background
    when it is stale. This is computed from DAILY bars, so a screen a few minutes old is
    the same screen; a tick hanging ten minutes to prove that is not a trade-off worth
    making on a desk that also places real orders.

    `force=True` awaits a rebuild, for callers that genuinely need it fresh."""
    global _scored_task
    now = time.monotonic()
    cached = _scored_cache["data"]
    fresh = cached is not None and now - _scored_cache["at"] < SCORED_TTL

    if force:
        await _refresh_scored()
        return _scored_cache["data"] or []

    if not fresh and _scored_task is None:
        _scored_task = asyncio.create_task(_refresh_scored())
    return cached or []


async def _scan_daily_symbols() -> list[tuple[str, float, list[str], float, list[Bar]]]:
    """The uncached scan. The universe is exactly what has been backfilled — the module
    never invents data for symbols it cannot see."""
    from app.core.db import bars_collection

    started = time.monotonic()
    # 14 months: the longest lookback in `technical_score` is a 200-day EMA, and every
    # extra month is ~500 more documents per symbol crossing the wire for nothing.
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(os.getenv("SCORED_DAYS", "425")))
    symbols = [s for s in await bars_collection.distinct("symbol", {"timeframe": "1d"})
               if s not in INDICES]
    symbols.sort()

    out: list[tuple[str, float, list[str], float, list[Bar]]] = []
    CHUNK = int(os.getenv("SCORED_SYMBOL_CHUNK", "50"))
    for i in range(0, len(symbols), CHUNK):
        group = symbols[i:i + CHUNK]
        by_symbol: dict[str, list[Bar]] = {sym: [] for sym in group}
        cursor = bars_collection.find(
            {"timeframe": "1d", "symbol": {"$in": group}, "ts": {"$gte": cutoff}},
            {"_id": 0},
        ).sort([("symbol", 1), ("ts", 1)])
        async for doc in cursor:
            sym = doc.get("symbol")
            if sym in by_symbol:
                try:
                    by_symbol[sym].append(Bar(**doc))
                except TypeError:
                    continue          # a stray document shape is skipped, not fatal
        for sym in group:
            bars = by_symbol.get(sym) or []
            scored = technical_score(bars)
            if scored is None:
                continue
            score, reasons, atr14 = scored
            out.append((sym, score, reasons, atr14, bars))

    logger.info("daily screen rebuilt: %s of %s symbols scored in %.1fs (%s chunks)",
                len(out), len(symbols), time.monotonic() - started,
                (len(symbols) + CHUNK - 1) // CHUNK)
    return out


