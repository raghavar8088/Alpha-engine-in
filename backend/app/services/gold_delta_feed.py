"""Delta gold data — bars, prices, funding and order-book costs under the Gold Desk's dollar tab.

WHAT IT PULLS (public endpoints, no keys — this app holds no Delta credentials)
------------------------------------------------------------------------------
    /v2/history/candles          OHLCV per interval; `FUNDING:<sym>` gives the funding series
    /v2/tickers/<sym>            mark price, best bid / ask and their sizes, the live funding rate
    /v2/l2orderbook/<sym>        the book, to price an order bigger than the touch
    /v2/products/<sym>           contract value, the venue's own fee rates, funding interval

XAUTUSD is the one token the desk trades (GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md, C5/D15:
XAUT and PAXG are the same ounce, and XAUT has the tighter book — 0.036 vs 0.12 bp a side for
a slot — and ~2.7x the volume). PAXG is still read for the basis card, by ticker only.

A SEPARATE STORE FROM `commodity_bars`, ON PURPOSE
--------------------------------------------------
Because the SESSION differs: this venue never closes, so buckets are anchored to UTC midnight
and the day is the UTC day; every bar is carried in UTC.

WHAT CHANGED ON 2026-10-11 (the plan's C1, C3, C7, I5)
------------------------------------------------------
* REFRESH IS INCREMENTAL (C7). Each pass used to re-download days of candles per interval and
  rewrite all of them with a fresh `updated_at` — measured on production: ~17,000 documents
  rewritten every 2 minutes (~12 million writes a day) for a desk that was switched off, 8,233
  of them candles more than three days old that cannot change. Now a pass fetches from the last
  stored bar (the last three re-read, in case one was still forming), writes OHLCV only — an
  unchanged candle is a no-op for Mongo — and a prune keeps `KEEP_BARS` per interval.
* CLOSED BARS (C1). `load_bars(..., closed_only=True)` drops the bar still forming. The venue
  returns the live candle; a pattern evaluated on it can fire and vanish within one bar.
* PRICES AT THE TOUCH (C3). Fills use the best bid / ask (an order bigger than the touch walks
  the book), not the mark price plus a guessed 5 bp.
* FUNDING (C3). The `FUNDING:<sym>` series is kept, so open positions pay or receive it at every
  exchange. The rate is read as PERCENT PER EXCHANGE: the product's `annualized_funding` cap
  (XAUT 21.9) is exactly 0.01% x 6 exchanges a day x 365, the same arithmetic as the docs'
  BTCUSD example (10.95 = 0.01% x 3 x 365 at an 8-hour interval).
* COST MONITOR (I5). Every 5 minutes the book is sampled — quoted spread and what one H1 sleeve
  would pay to cross it — into `gold_delta_book_log` (kept 180 days).

FINAL, NOT MERELY CLOSED BY THE CLOCK
-------------------------------------
A candle stored while it was still forming is complete by the clock a moment later, but the
store only holds what it had at the fetch. So every pass records WHEN each interval was read
(`fetched_at`), and a bar counts as final only once the store re-read it after it closed
(`FINAL_MARGIN_S` later). Exits walk final minutes only (`minutes`), the desk decides a 4h bar
only once it is final, and H1's benchmark price at a week boundary (`price_at`) waits for the
same. Without this a stop touched in the last seconds of a minute — or a 4h signal formed in
the last seconds of its bar — could be missed for good.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core.db import db, gold_bars_collection, gold_state_collection

logger = logging.getLogger("gold_delta_feed")

BASE_URL = os.getenv("DELTA_API_BASE_URL", "https://api.india.delta.exchange").rstrip("/")

# The token(s) the desk TRADES and keeps bars for. One by default — see the module docstring.
SYMBOLS: list[str] = [
    s.strip().upper() for s in os.getenv("GOLD_DELTA_SYMBOLS", "XAUTUSD").split(",") if s.strip()
]
# Read for the basis card only (tickers, no bars).
BASIS_SYMBOLS: tuple[str, ...] = ("XAUTUSD", "PAXGUSD")

# label -> (Delta resolution, minutes). None = derived here by resampling.
TIMEFRAMES: dict[str, tuple[str | None, int]] = {
    "1m": ("1m", 1),
    "5m": ("5m", 5),
    "15m": ("15m", 15),
    "30m": ("30m", 30),
    "45m": (None, 45),      # Delta has no 45m — derived from 15m
    "1h": ("1h", 60),
    "4h": ("4h", 240),
    "1d": ("1d", 1440),
}
NATIVE_TIMEFRAMES = {tf: res for tf, (res, _m) in TIMEFRAMES.items() if res}
DERIVED_FROM = {"45m": "15m"}

# First-fill history per interval, and how many bars the store keeps. H1 records XAUT's price
# at each week boundary as it passes (gold_h1.snapshot_boundaries), so its benchmark never
# depends on these; 1d still keeps 1,200 days — longer than the whole two-year test — as the
# fallback for a boundary that could not be read in time.
FETCH_DAYS = {"1m": 3, "5m": 10, "15m": 30, "30m": 60, "1h": 90, "4h": 240, "1d": 600}
KEEP_BARS = {"1m": 3000, "5m": 1500, "15m": 1200, "30m": 1000, "1h": 900, "4h": 700, "1d": 1200}
REFETCH_BARS = 3            # re-read the last few stored bars: the newest may have been forming
PAGE_BARS = 3900            # the venue returns at most ~4000 candles a request
FINAL_MARGIN_S = 10         # a bar is final once the store re-read it this long after it closed
FUNDING_RES_S = 3600        # the FUNDING:<sym> series is read as hourly candles

REQUEST_MIN_INTERVAL_S = float(os.getenv("GOLD_DELTA_REQUEST_INTERVAL_S", "0.4"))
REQUEST_TIMEOUT_S = float(os.getenv("GOLD_DELTA_TIMEOUT_S", "20"))
MAX_RETRIES = int(os.getenv("GOLD_DELTA_RETRIES", "3"))
BACKOFF_S = float(os.getenv("GOLD_DELTA_BACKOFF_S", "2.0"))
PRODUCT_TTL_S = 24 * 3600   # the fee is read from the venue, and re-read daily (D7)
FUNDING_KEEP_DAYS = 14
BOOK_SAMPLE_EVERY_S = float(os.getenv("GOLD_DELTA_BOOK_SAMPLE_S", "300"))
BOOK_LOG_TTL_DAYS = int(os.getenv("GOLD_DELTA_BOOK_LOG_TTL_DAYS", "180"))
SLEEVE_USD_FOR_COSTS = float(os.getenv("GOLD_DELTA_COST_SLEEVE_USD", str(10_000 / 9)))

book_log_collection = db["gold_delta_book_log"]

_last_call_at = 0.0
_call_lock = asyncio.Lock()
_LAST_ERRORS: dict[str, str] = {}
_last_book_sample = 0.0
_last_prune = 0.0


class Bar:
    """Minimal OHLCV bar, carried in UTC — the same six slots as `commodity_bars.Bar`."""

    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts: datetime, o: float, h: float, l: float, c: float, v: float):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v

    def __repr__(self) -> str:
        return f"Bar({self.ts:%Y-%m-%d %H:%M}Z o={self.open} h={self.high} l={self.low} c={self.close})"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_market_open(_now_utc: datetime | None = None) -> bool:
    """Always true — a perpetual has no session."""
    return True


def tf_seconds(tf: str) -> int:
    return TIMEFRAMES[tf][1] * 60


# ── the venue ────────────────────────────────────────────────────────────────────


async def _get(path: str, params: dict) -> dict:
    """One paced GET against Delta's public API, retried, then raised."""
    global _last_call_at
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        async with _call_lock:
            wait = REQUEST_MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
                r = await client.get(f"{BASE_URL}{path}", params=params,
                                     headers={"Accept": "application/json"})
            if r.status_code == 429:
                raise RuntimeError("rate limited (HTTP 429)")
            r.raise_for_status()
            body = r.json()
            if not body.get("success", True):
                raise RuntimeError(f"delta reported failure: {str(body)[:180]}")
            return body
        except Exception as exc:                       # noqa: BLE001 - retried, then reported
            last_err = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_S * (attempt + 1))
    raise RuntimeError(str(last_err))


_PRODUCTS: dict[str, tuple[dict, float]] = {}


async def product(symbol: str) -> dict:
    """Contract value, tick, the venue's own fee rates and funding interval — re-read daily.

    `taker_fee_rate` is None when the venue does not publish one; the desk then REFUSES to
    trade (D7) rather than charging zero."""
    symbol = symbol.upper()
    hit = _PRODUCTS.get(symbol)
    if hit and time.monotonic() - hit[1] < PRODUCT_TTL_S:
        return hit[0]
    body = await _get(f"/v2/products/{symbol}", {})
    r = body.get("result") or {}
    specs = r.get("product_specs") or {}

    def _rate(key: str) -> float | None:
        try:
            v = float(r.get(key))
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    spec = {
        "symbol": symbol,
        "description": r.get("description") or symbol,
        "contract_value": float(r.get("contract_value") or 0) or 0.001,
        "contract_unit": r.get("contract_unit_currency") or symbol.replace("USD", ""),
        "tick_size": float(r.get("tick_size") or 0.01),
        "taker_fee_rate": _rate("taker_commission_rate"),
        "maker_fee_rate": _rate("maker_commission_rate"),
        "funding_interval_s": int(specs.get("rate_exchange_interval") or 28800),
        "annualized_funding_cap": r.get("annualized_funding"),
        "state": r.get("state"),
    }
    _PRODUCTS[symbol] = (spec, time.monotonic())
    return spec


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


async def ticker(symbol: str) -> dict | None:
    """The venue's mark, best bid / ask with sizes, spot index and live funding rate."""
    try:
        body = await _get(f"/v2/tickers/{symbol.upper()}", {})
    except Exception as exc:                            # noqa: BLE001
        _LAST_ERRORS[f"{symbol}:ticker"] = str(exc)[:200]
        return None
    r = body.get("result") or {}
    q = r.get("quotes") or {}
    out = {"symbol": symbol.upper(), "mark": _f(r.get("mark_price")) or _f(r.get("close")),
           "last": _f(r.get("close")), "spot": _f(r.get("spot_price")),
           "bid": _f(q.get("best_bid")), "ask": _f(q.get("best_ask")),
           "bid_size": _f(q.get("bid_size")), "ask_size": _f(q.get("ask_size")),
           "funding_rate": _f(r.get("funding_rate")), "at": _now()}
    if out["bid"] and out["ask"] and out["ask"] >= out["bid"] > 0:
        mid = (out["bid"] + out["ask"]) / 2
        out["mid"] = mid
        out["spread_bp"] = (out["ask"] - out["bid"]) / mid * 1e4
    else:
        out["mid"] = out["spread_bp"] = None
    return out


async def mark_price(symbol: str) -> float | None:
    t = await ticker(symbol)
    return t["mark"] if t else None


async def l2_book(symbol: str, depth: int = 50) -> dict | None:
    try:
        body = await _get(f"/v2/l2orderbook/{symbol.upper()}", {"depth": depth})
    except Exception as exc:                            # noqa: BLE001
        _LAST_ERRORS[f"{symbol}:book"] = str(exc)[:200]
        return None
    r = body.get("result") or {}
    bids = [(float(x["price"]), float(x["size"])) for x in r.get("buy", []) if x.get("price")]
    asks = [(float(x["price"]), float(x["size"])) for x in r.get("sell", []) if x.get("price")]
    return {"bids": bids, "asks": asks}


def walk(levels: list[tuple[float, float]], contracts: int) -> tuple[float | None, int]:
    """VWAP of filling `contracts` down `levels` (best first) and how many filled."""
    left, cost, got = int(contracts), 0.0, 0
    for px, size in levels:
        if left <= 0:
            break
        take = min(int(size), left)
        if take <= 0:
            continue
        cost += take * px
        got += take
        left -= take
    return (cost / got if got else None), got


async def fill_price(symbol: str, side: str, contracts: int) -> dict | None:
    """What a market order of `contracts` on `side` pays: the touch when the best level holds
    the whole order, else the book walked. None when there is no two-sided market."""
    t = await ticker(symbol)
    if not t or not t.get("bid") or not t.get("ask") or t.get("spread_bp") is None:
        return None
    touch_px = t["ask"] if side == "BUY" else t["bid"]
    touch_sz = (t["ask_size"] if side == "BUY" else t["bid_size"]) or 0
    out = {"price": touch_px, "basis": "touch", "spread_bp": round(t["spread_bp"], 4),
           "bid": t["bid"], "ask": t["ask"], "mark": t["mark"], "mid": t["mid"]}
    if contracts > touch_sz:
        book = await l2_book(symbol)
        if book:
            vwap, got = walk(book["asks"] if side == "BUY" else book["bids"], contracts)
            if vwap is not None and got >= contracts:
                out.update(price=vwap, basis="book_walk")
            elif vwap is not None:
                return None          # the visible book cannot fill the order: no fill invented
    return out


async def fetch_candles(symbol: str, resolution: str, start: int, end: int) -> list[Bar]:
    """One native series between two epoch seconds, oldest first, paged."""
    minutes = next((m for _tf, (res, m) in TIMEFRAMES.items() if res == resolution), 1)
    step = minutes * 60 * PAGE_BARS
    out: dict[int, Bar] = {}
    t = int(start)
    while t < end:
        t2 = min(t + step, int(end))
        body = await _get("/v2/history/candles",
                          {"resolution": resolution, "symbol": symbol.upper(), "start": t, "end": t2})
        for c in body.get("result") or []:
            try:
                ts = int(c["time"])
                out[ts] = Bar(datetime.fromtimestamp(ts, tz=timezone.utc), float(c["open"]),
                              float(c["high"]), float(c["low"]), float(c["close"]),
                              float(c.get("volume") or 0))
            except (KeyError, TypeError, ValueError):
                continue                  # one malformed candle costs one candle
        t = t2
    return [out[k] for k in sorted(out)]


# ── the store ────────────────────────────────────────────────────────────────────


async def _latest_ts(symbol: str, tf: str) -> datetime | None:
    d = await gold_bars_collection.find_one({"symbol": symbol, "timeframe": tf}, {"ts": 1},
                                            sort=[("ts", -1)])
    if not d:
        return None
    ts = d["ts"]
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def _oldest_ts(symbol: str, tf: str) -> datetime | None:
    d = await gold_bars_collection.find_one({"symbol": symbol, "timeframe": tf}, {"ts": 1},
                                            sort=[("ts", 1)])
    if not d:
        return None
    ts = d["ts"]
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def fetched_at(symbol: str, tf: str) -> int | None:
    """Epoch seconds of the last SUCCESSFUL read of (symbol, interval) — every bar that closed
    before it (less FINAL_MARGIN_S) is final in the store. A derived interval reads its parent's."""
    tf = DERIVED_FROM.get(tf, tf)
    d = await gold_state_collection.find_one({"_id": "delta_bars"}, {"fetched": 1}) or {}
    v = ((d.get("fetched") or {}).get(symbol.upper()) or {}).get(tf)
    return int(v) if v is not None else None


async def refresh_symbol(symbol: str, intervals: list[str] | None = None) -> dict[str, int]:
    """Bring each NATIVE interval up to date. Returns bars written per interval (-1 = failed).

    From the last stored bar (minus REFETCH_BARS), or FETCH_DAYS on an empty store. Only OHLCV
    is `$set`, so a candle that has not changed is not rewritten. The time of each successful read
    is recorded (`fetched_at`): it is what makes a stored bar final."""
    from pymongo import UpdateOne

    result: dict[str, int] = {}
    read_ok: list[str] = []
    now = int(time.time())
    for tf in (list(NATIVE_TIMEFRAMES) if intervals is None else intervals):
        res = NATIVE_TIMEFRAMES.get(tf)
        if not res:
            continue
        sec = tf_seconds(tf)
        try:
            last = await _latest_ts(symbol, tf)
            start = (int(last.timestamp()) - REFETCH_BARS * sec) if last else now - FETCH_DAYS.get(tf, 30) * 86400
            bars = await fetch_candles(symbol, res, start, now)
            _LAST_ERRORS.pop(f"{symbol}:{tf}", None)
        except Exception as exc:                        # noqa: BLE001
            _LAST_ERRORS[f"{symbol}:{tf}"] = str(exc)[:200]
            result[tf] = -1
            continue
        ops = [UpdateOne({"symbol": symbol, "timeframe": tf, "ts": b.ts},
                         {"$set": {"open": b.open, "high": b.high, "low": b.low, "close": b.close,
                                   "volume": b.volume},
                          "$setOnInsert": {"venue": "DELTA", "created_at": _now()}},
                         upsert=True)
               for b in bars]
        if ops:
            await gold_bars_collection.bulk_write(ops, ordered=False)
        result[tf] = len(bars)
        read_ok.append(tf)
    if read_ok:
        # `now` was taken before any request, so every candle that closed before it is complete.
        await gold_state_collection.update_one(
            {"_id": "delta_bars"}, {"$set": {f"fetched.{symbol.upper()}.{tf}": now for tf in read_ok}}, upsert=True)
    return result


async def prune(symbols: list[str] | None = None) -> int:
    """Keep KEEP_BARS per (symbol, interval); older bars are deleted. Returns documents removed.
    Symbols no longer refreshed age out entirely."""
    removed = 0
    now = _now()
    syms = symbols if symbols is not None else await gold_bars_collection.distinct("symbol")
    for s in syms:
        for tf, keep in KEEP_BARS.items():
            cutoff = now - timedelta(seconds=keep * tf_seconds(tf))
            r = await gold_bars_collection.delete_many({"symbol": s, "timeframe": tf, "ts": {"$lt": cutoff}})
            removed += int(getattr(r, "deleted_count", 0) or 0)
    return removed


async def refresh_funding(symbol: str) -> int:
    """Keep the last FUNDING_KEEP_DAYS of the venue's funding series in one state document."""
    now = int(time.time())
    try:
        body = await _get("/v2/history/candles", {"resolution": "1h", "symbol": f"FUNDING:{symbol.upper()}",
                                                  "start": now - FUNDING_KEEP_DAYS * 86400, "end": now})
    except Exception as exc:                            # noqa: BLE001
        _LAST_ERRORS[f"{symbol}:funding"] = str(exc)[:200]
        return -1
    rows = sorted({int(c["time"]): float(c["close"]) for c in body.get("result") or []
                   if c.get("time") is not None and c.get("close") is not None}.items())
    if rows:
        await gold_state_collection.update_one(
            {"_id": f"funding:{symbol.upper()}"},
            {"$set": {"series": [[t, r] for t, r in rows], "updated_at": _now()}}, upsert=True)
    return len(rows)


async def funding_series(symbol: str) -> list[tuple[int, float]]:
    d = await gold_state_collection.find_one({"_id": f"funding:{symbol.upper()}"}) or {}
    return [(int(t), float(r)) for t, r in d.get("series") or []]


def rate_at(series: list[tuple[int, float]], ts: int, res_s: int = FUNDING_RES_S) -> tuple[float | None, str]:
    """The funding rate in force at the exchange at `ts`: the close of the latest funding candle
    that had ENDED by then (open + res_s <= ts). The candle of the hour starting AT the exchange
    closes an hour later, on the rate quoted for the NEXT exchange — using it would read the
    future. Basis 'series'; or the oldest print when `ts` predates the series ('series_edge');
    or None."""
    if not series:
        return None, "none"
    best = None
    for t, r in series:
        if t + res_s <= ts:
            best = r
        else:
            break
    if best is None:
        return series[0][1], "series_edge"
    return best, "series"


async def sample_book(symbol: str) -> dict | None:
    """One cost-monitor sample: quoted spread and what one sleeve pays to cross (I5)."""
    t = await ticker(symbol)
    book = await l2_book(symbol)
    if not t or not book or not book["bids"] or not book["asks"]:
        return None
    bb, ba = book["bids"][0][0], book["asks"][0][0]
    mid = (bb + ba) / 2
    spec = await product(symbol)
    contracts = int(SLEEVE_USD_FOR_COSTS // (mid * spec["contract_value"])) if mid else 0
    vb, gb = walk(book["asks"], contracts)
    vs, gs = walk(book["bids"], contracts)
    doc = {"ts": _now(), "symbol": symbol.upper(), "bid": bb, "ask": ba, "mid": mid,
           "spread_bp": (ba - bb) / mid * 1e4, "mark": t.get("mark"), "funding_rate": t.get("funding_rate"),
           "sleeve_usd": SLEEVE_USD_FOR_COSTS, "sleeve_contracts": contracts,
           "buy_bp": ((vb - mid) / mid * 1e4) if vb and gb >= contracts else None,
           "sell_bp": ((mid - vs) / mid * 1e4) if vs and gs >= contracts else None,
           "bid_size": book["bids"][0][1], "ask_size": book["asks"][0][1]}
    await book_log_collection.insert_one(doc)
    return doc


async def refresh_all(intervals: list[str] | None = None, symbols: list[str] | None = None,
                      sample_costs: bool = True) -> dict:
    """One pass: bars for the intervals in use, the funding series, the cost sample, a prune."""
    global _last_book_sample, _last_prune
    started = time.monotonic()
    syms = symbols or SYMBOLS
    detail = {}
    for s in syms:
        detail[s] = await refresh_symbol(s, intervals)
        detail[s]["funding"] = await refresh_funding(s)
    if sample_costs and time.monotonic() - _last_book_sample >= BOOK_SAMPLE_EVERY_S:
        _last_book_sample = time.monotonic()
        for s in syms:
            try:
                await sample_book(s)
            except Exception as exc:                    # noqa: BLE001
                _LAST_ERRORS[f"{s}:book_sample"] = str(exc)[:200]
    if time.monotonic() - _last_prune >= 3600:
        _last_prune = time.monotonic()
        try:
            detail["pruned"] = await prune()
        except Exception as exc:                        # noqa: BLE001
            _LAST_ERRORS["prune"] = str(exc)[:200]
    failed = sum(1 for s in syms for v in detail[s].values() if isinstance(v, int) and v < 0)
    outcome = {"symbols": len(syms), "intervals": list(NATIVE_TIMEFRAMES) if intervals is None else intervals,
               "seconds": round(time.monotonic() - started, 1), "failed_fetches": failed,
               "detail": detail, "errors": dict(_LAST_ERRORS), "finished_at": _now(),
               "pacing_seconds": REQUEST_MIN_INTERVAL_S}
    await gold_state_collection.update_one({"_id": "delta_bars"}, {"$set": outcome}, upsert=True)
    return outcome


async def idle_pass(symbols: list[str] | None = None) -> dict:
    """What the feed does while no Delta book is live: the cost sample every few minutes (I5) and
    an hourly prune — no bars, no funding, no state write."""
    global _last_book_sample, _last_prune
    out: dict = {}
    if time.monotonic() - _last_book_sample >= BOOK_SAMPLE_EVERY_S:
        _last_book_sample = time.monotonic()
        for s in symbols or SYMBOLS:
            try:
                out[s] = bool(await sample_book(s))
            except Exception as exc:                    # noqa: BLE001
                _LAST_ERRORS[f"{s}:book_sample"] = str(exc)[:200]
    if time.monotonic() - _last_prune >= 3600:
        _last_prune = time.monotonic()
        try:
            out["pruned"] = await prune()
        except Exception as exc:                        # noqa: BLE001
            _LAST_ERRORS["prune"] = str(exc)[:200]
    return out


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Aggregate into `minutes` buckets anchored to UTC MIDNIGHT (1440 divides by 45: no stub)."""
    if not bars or minutes <= 0:
        return []
    buckets: dict[tuple, list[Bar]] = {}
    for b in bars:
        day_start = b.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        offset = int((b.ts - day_start).total_seconds() // 60)
        buckets.setdefault((b.ts.date(), offset // minutes), []).append(b)
    out: list[Bar] = []
    for (_day, idx) in sorted(buckets):
        group = buckets[(_day, idx)]
        start = group[0].ts.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=idx * minutes)
        out.append(Bar(start, group[0].open, max(g.high for g in group), min(g.low for g in group),
                       group[-1].close, sum(g.volume for g in group)))
    return out


def drop_forming(bars: list[Bar], minutes: int, now: datetime | None = None) -> list[Bar]:
    """Remove trailing bars that have not closed yet (ts + length > now)."""
    now = now or _now()
    while bars and bars[-1].ts + timedelta(minutes=minutes) > now:
        bars = bars[:-1]
    return bars


async def load_bars(symbol: str, timeframe: str, limit: int = 400, closed_only: bool = False,
                    now: datetime | None = None) -> list[Bar]:
    """Bars for (symbol, timeframe), oldest first, in UTC. `closed_only` drops the forming bar."""
    minutes = TIMEFRAMES[timeframe][1]
    if timeframe in DERIVED_FROM:
        parent = DERIVED_FROM[timeframe]
        factor = max(minutes // TIMEFRAMES[parent][1], 1)
        src = await load_bars(symbol, parent, limit * factor + factor)
        out = resample(src, minutes)
    else:
        docs = [d async for d in gold_bars_collection.find(
            {"symbol": symbol, "timeframe": timeframe}).sort("ts", -1).limit(limit + 1)]
        docs.reverse()
        out = []
        for d in docs:
            ts = d["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append(Bar(ts.astimezone(timezone.utc), d["open"], d["high"], d["low"], d["close"],
                           d.get("volume") or 0))
    if closed_only:
        out = drop_forming(out, minutes, now)
    return out[-limit:]


async def minutes(symbol: str, since_ts: int, until_ts: int) -> list[tuple[int, float, float, float, float]]:
    """FINAL one-minute bars with since_ts <= open < until_ts, oldest first — the path an exit is
    walked over (gold_fills.walk_exit).

    Final = the store re-read the minute after it closed (open + 60 <= the last 1m read less
    FINAL_MARGIN_S): the forming minute, or one stored while it was forming, is never walked —
    its last seconds could hold the touch that matters. If the store no longer reaches back to
    `since_ts` (pruned across a long outage) the missing stretch is read from the venue; if that
    read fails nothing is returned, so the walk waits instead of skipping a stretch."""
    done = await fetched_at(symbol, "1m")
    if done is None:
        return []
    hi = min(int(until_ts), int(done) - FINAL_MARGIN_S - 60 + 1)
    if hi <= since_ts:
        return []
    q = {"symbol": symbol, "timeframe": "1m",
         "ts": {"$gte": datetime.fromtimestamp(int(since_ts), timezone.utc),
                "$lt": datetime.fromtimestamp(hi, timezone.utc)}}
    rows: dict[int, tuple] = {}
    async for d in gold_bars_collection.find(q).sort("ts", 1):
        ts = d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=timezone.utc)
        t = int(ts.timestamp())
        rows[t] = (t, float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"]))
    oldest = await _oldest_ts(symbol, "1m")
    reach = int(oldest.timestamp()) if oldest else hi
    if since_ts < reach - 60:
        try:
            for b in await fetch_candles(symbol, "1m", int(since_ts), min(reach, hi)):
                t = int(b.ts.timestamp())
                if since_ts <= t < hi and t not in rows:
                    rows[t] = (t, float(b.open), float(b.high), float(b.low), float(b.close))
        except Exception as exc:                        # noqa: BLE001
            _LAST_ERRORS[f"{symbol}:1m_backfill"] = str(exc)[:200]
            logger.warning("gold delta: could not read %s minutes before the store's oldest (%s) — the "
                           "walk waits", symbol, exc)
            return []
    return [rows[t] for t in sorted(rows)]


async def price_at(symbol: str, t: datetime) -> tuple[float, str] | None:
    """The last price at or before `t`: the close of the finest FINAL bar in the store that ended
    at or before `t` and close to it — 1m (within 30 minutes), else 4h, else 1d. None until the
    store has been re-read past `t`."""
    t_s = int(t.timestamp())
    for tf, near_s in (("1m", 1800), ("4h", 4 * 3600), ("1d", 86400)):
        done = await fetched_at(symbol, tf)
        if done is None or done < t_s + FINAL_MARGIN_S:
            continue
        sec = tf_seconds(tf)
        d = await gold_bars_collection.find_one(
            {"symbol": symbol.upper(), "timeframe": tf,
             "ts": {"$lte": datetime.fromtimestamp(t_s - sec, timezone.utc)}}, sort=[("ts", -1)])
        if not d:
            continue
        ts = d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=timezone.utc)
        if t_s - (int(ts.timestamp()) + sec) <= near_s:
            return float(d["close"]), tf
    return None


async def coverage() -> dict:
    """Bar counts per (symbol, timeframe) — a starved store made visible."""
    rows: dict[str, dict[str, int]] = {}
    latest: dict[str, str | None] = {}
    async for r in gold_bars_collection.aggregate(
            [{"$group": {"_id": {"s": "$symbol", "t": "$timeframe"}, "n": {"$sum": 1}, "last": {"$max": "$ts"}}}]):
        s, t = r["_id"]["s"], r["_id"]["t"]
        rows.setdefault(s, {})[t] = r["n"]
        ts = r.get("last")
        if ts is not None:
            iso = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).isoformat()
            if s not in latest or (latest[s] or "") < iso:
                latest[s] = iso
    last = await gold_state_collection.find_one({"_id": "delta_bars"}) or {}
    last.pop("_id", None)
    if isinstance(last.get("finished_at"), datetime):
        last["finished_at"] = last["finished_at"].isoformat()
    return {"venue": "DELTA", "symbols": SYMBOLS, "timeframes": list(TIMEFRAMES),
            "native": list(NATIVE_TIMEFRAMES), "derived": DERIVED_FROM, "bars": rows,
            "last_bar_at": latest, "last_refresh": last}


async def cost_stats(symbol: str, days: int = 30) -> dict:
    """The cost monitor's summary: quoted spread and sleeve cost, median and 90th percentile."""
    since = _now() - timedelta(days=days)
    sp, buy, sell, n = [], [], [], 0
    async for r in book_log_collection.find({"symbol": symbol.upper(), "ts": {"$gte": since}},
                                            {"spread_bp": 1, "buy_bp": 1, "sell_bp": 1}):
        n += 1
        if r.get("spread_bp") is not None:
            sp.append(float(r["spread_bp"]))
        if r.get("buy_bp") is not None:
            buy.append(float(r["buy_bp"]))
        if r.get("sell_bp") is not None:
            sell.append(float(r["sell_bp"]))

    def q(xs, p):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(len(xs) * p))], 4) if xs else None

    return {"symbol": symbol.upper(), "days": days, "samples": n,
            "spread_bp_median": q(sp, 0.5), "spread_bp_p90": q(sp, 0.9),
            "sleeve_buy_bp_median": q(buy, 0.5), "sleeve_sell_bp_median": q(sell, 0.5),
            "sleeve_buy_bp_p90": q(buy, 0.9), "sleeve_sell_bp_p90": q(sell, 0.9)}


async def ensure_indexes() -> None:
    """Best-effort; never raises (a raising startup hook once took the whole backend down)."""
    try:
        await gold_bars_collection.create_index([("symbol", 1), ("timeframe", 1), ("ts", -1)], unique=True)
        await book_log_collection.create_index([("symbol", 1), ("ts", -1)], name="gdbl_symbol_ts", background=True)
        await book_log_collection.create_index("ts", name="gdbl_ttl", expireAfterSeconds=BOOK_LOG_TTL_DAYS * 86400,
                                               background=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gold_delta_feed indexes skipped: %s", exc)
