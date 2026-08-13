"""Fundamentals for the stock universe, from Yahoo Finance.

The Bullish Stocks screen asks a fundamental question alongside the technical one: is the
business actually growing, profitable, not over-levered, and being bought by people who
know it? None of that existed anywhere in this codebase, so this module adds it.

Yahoo is the pragmatic source: free, no key, and it covers NSE tickers as `SYMBOL.NS`. It
is scraped rather than contracted, so every field is optional and a failure for one symbol
never breaks the screen — the row simply shows no fundamental grade.

Refreshed on a daily cadence into stock_fundamentals; these are quarterly-reported numbers,
so a daily snapshot is far more resolution than the data actually has. The screener reads
Mongo only and never calls Yahoo inline.

What maps cleanly, and what does not:
  revenue growth      -> revenueGrowth
  profit growth       -> earningsGrowth (falls back to earningsQuarterlyGrowth)
  margins             -> profitMargins / operatingMargins
  debt                -> debtToEquity
  return on equity    -> returnOnEquity
  analyst view        -> recommendationKey + numberOfAnalystOpinions
  promoter holding    -> heldPercentInsiders     (proxy: insiders ≈ promoter group)
  institutional       -> heldPercentInstitutions
  ORDER BOOK          -> no programmatic source. It is disclosed in prose in filings and
                         is sector-specific (infra/defence/capital goods). Left out rather
                         than approximated by something that is not an order book.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne

from app.core.db import stock_fundamentals_collection, stock_universe_collection

logger = logging.getLogger("stock_fundamentals")

REFRESH_AFTER_HOURS = 20     # re-pull a symbol at most once a day
PACE_SECONDS = 0.25          # be polite to Yahoo across ~500 symbols
BATCH_CONCURRENCY = 4

# Thresholds for the fundamental grade. Deliberately undemanding — this is a
# confirmation filter on top of a technical screen, not a value screen.
MIN_REVENUE_GROWTH = 0.05    # +5% YoY
MIN_EARNINGS_GROWTH = 0.05   # +5% YoY
MIN_PROFIT_MARGIN = 0.05     # 5% net margin
MAX_DEBT_TO_EQUITY = 150.0   # Yahoo reports this as a percentage (150 = 1.5x)
MIN_ROE = 0.12               # 12% return on equity
MIN_INSTITUTIONAL = 0.05     # 5% institutional holding


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # drop NaN


def _fetch_one(symbol: str) -> dict | None:
    """Blocking yfinance call — run under a thread so the event loop keeps serving."""
    try:
        import yfinance  # imported lazily: the screen works without fundamentals
    except ImportError:
        return None
    try:
        info = yfinance.Ticker(f"{symbol}.NS").info or {}
    except Exception:
        return None
    if not info or _num(info.get("marketCap")) is None:
        return None
    eg = _num(info.get("earningsGrowth"))
    if eg is None:
        eg = _num(info.get("earningsQuarterlyGrowth"))
    return {
        "revenue_growth": _num(info.get("revenueGrowth")),
        "earnings_growth": eg,
        "profit_margin": _num(info.get("profitMargins")),
        "operating_margin": _num(info.get("operatingMargins")),
        "debt_to_equity": _num(info.get("debtToEquity")),
        "roe": _num(info.get("returnOnEquity")),
        "held_insiders": _num(info.get("heldPercentInsiders")),
        "held_institutions": _num(info.get("heldPercentInstitutions")),
        "analyst_rec": info.get("recommendationKey"),
        "analyst_count": _num(info.get("numberOfAnalystOpinions")),
        "market_cap": _num(info.get("marketCap")),
        "trailing_pe": _num(info.get("trailingPE")),
    }


def grade(f: dict | None) -> dict:
    """Turn raw fundamentals into the booleans the screen shows, plus a 0-6 score.

    Every check is None-safe and a missing field simply does not score — a stock Yahoo
    has no data for gets 0/6 and is reported as ungraded, never as a failure.
    """
    if not f:
        return {"fundamental_score": None, "fundamental_max": 6, "fundamentals_known": False}
    rg, eg = f.get("revenue_growth"), f.get("earnings_growth")
    pm, de = f.get("profit_margin"), f.get("debt_to_equity")
    roe, inst = f.get("roe"), f.get("held_institutions")
    rec = (f.get("analyst_rec") or "").lower()

    checks = {
        "fund_revenue": rg is not None and rg >= MIN_REVENUE_GROWTH,
        "fund_earnings": eg is not None and eg >= MIN_EARNINGS_GROWTH,
        "fund_margin": pm is not None and pm >= MIN_PROFIT_MARGIN,
        "fund_debt": de is not None and de <= MAX_DEBT_TO_EQUITY,
        "fund_roe": roe is not None and roe >= MIN_ROE,
        "fund_holding": inst is not None and inst >= MIN_INSTITUTIONAL,
    }
    known = any(v is not None for v in (rg, eg, pm, de, roe, inst))
    return {
        **checks,
        "fundamental_score": sum(1 for v in checks.values() if v),
        "fundamental_max": len(checks),
        "fundamentals_known": known,
        "analyst_bullish": rec in {"buy", "strong_buy"},
    }


async def refresh_fundamentals(force: bool = False, limit: int | None = None,
                               symbols: list[str] | None = None) -> dict:
    """Pull fundamentals for stale universe symbols (or all, when forced).

    `symbols` overrides the default Nifty-500 universe, so callers that need market
    caps for a different set — e.g. ranking the listed stocks OUTSIDE the index — can
    reuse this fetcher instead of writing a second Yahoo client."""
    syms = symbols if symbols is not None else [
        d["symbol"] async for d in stock_universe_collection.find({}, {"symbol": 1})]
    if not syms:
        return {"ok": 0, "failed": 0, "reason": "universe not seeded"}

    if not force:
        cutoff = _now() - timedelta(hours=REFRESH_AFTER_HOURS)
        fresh = set(await stock_fundamentals_collection.distinct(
            "symbol", {"fetched_at": {"$gte": cutoff}}))
        syms = [s for s in syms if s not in fresh]
    if limit:
        syms = syms[:limit]
    if not syms:
        return {"ok": 0, "failed": 0, "all_fresh": True}

    sem = asyncio.Semaphore(BATCH_CONCURRENCY)
    ops: list[UpdateOne] = []
    ok = fail = 0

    async def one(sym: str):
        nonlocal ok, fail
        async with sem:
            data = await asyncio.to_thread(_fetch_one, sym)
            await asyncio.sleep(PACE_SECONDS)
        if not data:
            fail += 1
            return
        ok += 1
        ops.append(UpdateOne(
            {"symbol": sym},
            {"$set": {"symbol": sym, **data, "fetched_at": _now()}},
            upsert=True,
        ))

    await asyncio.gather(*(one(s) for s in syms))
    if ops:
        await stock_fundamentals_collection.bulk_write(ops, ordered=False)
    logger.info("fundamentals refresh: %s ok, %s failed (of %s)", ok, fail, len(syms))
    return {"ok": ok, "failed": fail, "symbols": len(syms)}


async def load_fundamentals(symbols: list[str]) -> dict[str, dict]:
    return {
        d["symbol"]: d async for d in stock_fundamentals_collection.find(
            {"symbol": {"$in": symbols}}, {"_id": 0}
        )
    }
