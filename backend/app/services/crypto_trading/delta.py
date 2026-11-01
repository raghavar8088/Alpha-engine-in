"""Delta Exchange India's public REST API - products, tickers, candles, funding, the L2 book.

Synchronous on purpose: the sweep calls it from worker processes and the live desk from a thread
(anyio.to_thread), so one paced client serves both. Every call is paced (DELTA_PACE_S) under one
lock and retried with back-off; nothing here needs a key.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import DELTA_BASE_URL, DELTA_PACE_S, DELTA_PAGE, DERIVED_FROM, TF_SECONDS, UTC

_lock = threading.Lock()
_last = 0.0
_UA = {"User-Agent": "TradingAI-CryptoTrading/1.0", "Accept": "application/json"}


def _get(path: str, params: dict | None = None, retries: int = 4, timeout: int = 45) -> dict:
    global _last
    url = f"{DELTA_BASE_URL}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    delay = 1.5
    for attempt in range(retries + 1):
        with _lock:
            wait = DELTA_PACE_S - (time.monotonic() - _last)
            if wait > 0:
                time.sleep(wait)
            _last = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    return {}


def _f(v, default: float | None = None) -> float | None:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def products() -> dict[str, dict]:
    """Live perpetuals by symbol: contract value, tick, fees, funding interval, launch time."""
    out: dict[str, dict] = {}
    for p in _get("/v2/products", {"contract_types": "perpetual_futures", "states": "live"}).get("result") or []:
        spec = p.get("product_specs") or {}
        out[p["symbol"]] = {
            "symbol": p["symbol"],
            "underlying": (p.get("underlying_asset") or {}).get("symbol"),
            "contract_value": _f(p.get("contract_value"), 0.0),
            "tick_size": _f(p.get("tick_size"), 0.0),
            "taker_fee": _f(p.get("taker_commission_rate")),
            "maker_fee": _f(p.get("maker_commission_rate")),
            "funding_interval_s": int(spec.get("rate_exchange_interval") or 28800),
            "launch_time": p.get("launch_time"),
            "initial_margin_pct": _f(p.get("initial_margin")),
            "maintenance_margin_pct": _f(p.get("maintenance_margin")),
            "max_leverage": _f(p.get("default_leverage")),
            "state": p.get("state"),
        }
    return out


def tickers() -> dict[str, dict]:
    """Perpetual tickers by symbol: 24h turnover and open interest in USD, mark, best bid/ask."""
    out: dict[str, dict] = {}
    for r in _get("/v2/tickers", {"contract_types": "perpetual_futures"}).get("result") or []:
        q = r.get("quotes") or {}
        out[r["symbol"]] = {
            "turnover_usd": _f(r.get("turnover_usd"), 0.0),
            "oi_usd": _f(r.get("oi_value_usd"), 0.0),
            "mark": _f(r.get("mark_price")),
            "close": _f(r.get("close")),
            "bid": _f(q.get("best_bid")),
            "ask": _f(q.get("best_ask")),
            "funding_rate_pct": _f(r.get("funding_rate")),
            "ts": r.get("timestamp"),
        }
    return out


def l2_book(symbol: str, depth: int = 50) -> dict:
    r = _get(f"/v2/l2orderbook/{symbol}", {"depth": depth}).get("result") or {}
    side = lambda rows: [(float(x["price"]), float(x["size"])) for x in rows or [] if _f(x.get("price"))]  # noqa: E731
    return {"buy": side(r.get("buy")), "sell": side(r.get("sell"))}


def walk(levels: list[tuple[float, float]], contracts: float) -> tuple[float | None, float]:
    """Average price of `contracts` taken from `levels` (best first), and how many the book held."""
    need, cost, got = float(contracts), 0.0, 0.0
    for px, size in levels:
        take = min(size, need - got)
        cost += take * px
        got += take
        if got >= need:
            break
    return (cost / got if got > 0 else None), got


def candles(symbol: str, tf: str, start: int, end: int) -> list[list]:
    """[ts, o, h, l, c, v] rows (oldest first) with OPEN times in [start, end], paged backwards.
    45m is resampled from 15m on the UTC-midnight anchor."""
    if tf in DERIVED_FROM:
        return resample(candles(symbol, DERIVED_FROM[tf], start, end + TF_SECONDS[tf]), TF_SECONDS[tf])
    step = TF_SECONDS[tf]
    out: dict[int, list] = {}
    hi, empty = int(end), 0
    while hi >= start:
        lo = max(int(start), hi - DELTA_PAGE * step)
        rows = _get("/v2/history/candles", {"symbol": symbol, "resolution": tf, "start": lo, "end": hi}).get("result") or []
        if not rows:
            # Walked past the listing (data already in hand), or there is none at all: stop
            # rather than paging back through years of empty windows.
            empty += 1
            if out or empty >= 3:
                break
            hi = lo - 1
            continue
        empty = 0
        for r in rows:
            t = int(r["time"])
            if start <= t <= end:
                out[t] = [t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                          float(r.get("volume") or 0.0)]
        if lo <= start:
            break
        oldest = min(int(r["time"]) for r in rows)
        hi = (lo - 1) if oldest <= lo + step else (oldest - 1)
    return [out[k] for k in sorted(out)]


def resample(rows: list[list], seconds: int) -> list[list]:
    """Aggregate [ts,o,h,l,c,v] rows into `seconds` buckets anchored to UTC midnight. A bucket is
    kept only when it is complete (every parent bar present), so a missing 15m bar never fakes a
    45m bar with a missing third."""
    if not rows:
        return []
    parent = rows[1][0] - rows[0][0] if len(rows) > 1 else seconds
    need = max(1, seconds // max(parent, 1))
    buckets: dict[int, list[list]] = {}
    for r in rows:
        day = r[0] - r[0] % 86400
        b = day + ((r[0] - day) // seconds) * seconds
        buckets.setdefault(b, []).append(r)
    out = []
    for b in sorted(buckets):
        g = buckets[b]
        if len(g) < need:
            continue
        out.append([b, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)])
    return out


def funding(symbol: str, start: int, end: int) -> list[tuple[int, float]]:
    """The venue's hourly funding-rate candles (percent per exchange interval), oldest first."""
    rows = candles(f"FUNDING:{symbol}", "1h", start, end)
    return [(r[0], r[4]) for r in rows]


def daily_history_days(symbol: str) -> int:
    """Days of daily candles the venue holds for `symbol` (its whole listed life)."""
    now = int(time.time())
    rows = candles(symbol, "1d", now - 4 * 365 * 86400, now)
    return len(rows)


def utc_ts(dt) -> int:
    return int(dt.astimezone(UTC).timestamp())
