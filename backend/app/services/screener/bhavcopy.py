"""NSE full bhavcopy — the daily file that carries DELIVERY data.

WHY THIS FILE AND NOT THE QUOTE API. Delivery percentage is the single best available answer
to "is this real buying or intraday churn": it is the share of the day's traded quantity that
actually moved into someone's demat rather than being squared off before the close. A 4% rise
on 30% delivery is traders passing stock between themselves; the same rise on 70% delivery is
someone accumulating.

NSE's `quote-equity?section=trade_info` endpoint exposes it per symbol, and it 403s — verified
2026-08-22, "Access Denied" from this host. `equity-stockIndices` 404s. What DOES work is the
end-of-day archive:

    https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv

SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE,
AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER

One request returns the whole market — about 400KB and ~2,700 rows — instead of 500 per-symbol
calls that would be rate-limited into next week. Verified working for 21-Aug and 20-Aug 2026.

DELIVERY IS ONLY MEANINGFUL AGAINST ITS OWN HABIT. Utilities routinely deliver 70%; an
operator-driven smallcap routinely delivers 15%. So a single day's number says almost nothing
on its own, and this module keeps a rolling history so the screener can say "68% against a
20-day average of 41%" — which is a fact about THIS stock changing behaviour, not a fact about
its sector's conventions.

FAILS SOFT, like every other NSE path here. The archive host may block this box, and the file
does not exist on holidays or before the evening publish. Missing delivery data means the
column reads "n/a" and the delivery reason never fires; it never means zero, and it never
blocks a page.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from app.core.db import screener_bhavcopy_collection
from app.services.screener.horizons import IST

logger = logging.getLogger("screener.bhavcopy")

ARCHIVE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
HOME = "https://www.nseindia.com"
TIMEOUT = float(os.getenv("NSE_TIMEOUT", "40"))
LOOKBACK_DAYS = int(os.getenv("SCREENER_BHAV_LOOKBACK", "30"))
DELIVERY_AVG_WINDOW = 20

# Only ordinary equity. Government securities, ETFs and the rights/when-issued series carry
# delivery numbers that mean something different, and mixing them into a stock screen's
# averages would quietly skew every comparison.
KEEP_SERIES = {"EQ", "BE"}

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{HOME}/all-reports",
}

_status: dict = {"last_ok": None, "last_error": None, "days_stored": 0}

# The computed delivery table, cached. Rebuilding it means pulling 21 daily documents of
# ~2,860 rows each — some 60,000 dicts — and it was being rebuilt on EVERY universe
# snapshot, i.e. every five minutes, for a table that changes once a day after the close.
_delivery_cache: tuple[float, dict[str, dict]] | None = None
DELIVERY_CACHE_TTL = 1800.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v):
    try:
        s = str(v).strip().replace(",", "")
        if s in ("", "-", "nan"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


async def fetch_day(day: datetime) -> dict:
    """One trading day's bhavcopy. Returns {ok, date, rows, error}."""
    ddmmyyyy = day.strftime("%d%m%Y")
    iso = day.date().isoformat()
    url = ARCHIVE.format(ddmmyyyy=ddmmyyyy)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                     headers=BROWSER_HEADERS) as c:
            # Prime a session on the main site first; the archive host checks the referer
            # chain and serves a block page to a bare request.
            try:
                await c.get(HOME)
            except httpx.HTTPError:
                pass
            r = await c.get(url)
    except httpx.HTTPError as exc:
        return {"ok": False, "date": iso, "rows": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    if r.status_code != 200:
        # A 404 on a weekend or holiday is expected, not a failure worth alarming about.
        return {"ok": False, "date": iso, "rows": [],
                "error": f"HTTP {r.status_code} (no file published for {iso})"}

    rows = []
    # The header and every cell carry leading spaces in NSE's file — strip both or every
    # lookup silently misses.
    reader = csv.DictReader(io.StringIO(r.text))
    for raw in reader:
        rec = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        series = rec.get("SERIES", "")
        if series not in KEEP_SERIES:
            continue
        sym = rec.get("SYMBOL", "").upper()
        if not sym:
            continue
        deliv_qty = _num(rec.get("DELIV_QTY"))
        total_qty = _num(rec.get("TTL_TRD_QNTY"))
        deliv_pct = _num(rec.get("DELIV_PER"))
        if deliv_pct is None and deliv_qty and total_qty:
            deliv_pct = deliv_qty / total_qty * 100
        rows.append({
            "symbol": sym,
            "series": series,
            "close": _num(rec.get("CLOSE_PRICE")),
            "prev_close": _num(rec.get("PREV_CLOSE")),
            "volume": total_qty,
            "turnover_lacs": _num(rec.get("TURNOVER_LACS")),
            "trades": _num(rec.get("NO_OF_TRADES")),
            "delivery_qty": deliv_qty,
            "delivery_pct": round(deliv_pct, 2) if deliv_pct is not None else None,
        })
    return {"ok": True, "date": iso, "rows": rows, "error": None}


async def capture(day: datetime | None = None, force: bool = False) -> dict:
    """Store one day. Idempotent — re-running the same day overwrites."""
    day = day or datetime.now(IST)
    iso = day.date().isoformat()
    if not force and await screener_bhavcopy_collection.find_one({"_id": iso, "ok": True}):
        return {"captured": False, "reason": "already stored", "date": iso}

    res = await fetch_day(day)
    doc = {"_id": iso, "date": iso, "ts": _now(), "ok": res["ok"],
           "error": res["error"], "count": len(res["rows"]), "rows": res["rows"]}
    await screener_bhavcopy_collection.replace_one({"_id": iso}, doc, upsert=True)
    if res["ok"]:
        _status["last_ok"] = iso
        logger.info("bhavcopy: stored %s rows for %s", len(res["rows"]), iso)
    else:
        _status["last_error"] = f"{iso}: {res['error']}"
    return {"captured": True, "ok": res["ok"], "count": len(res["rows"]),
            "date": iso, "error": res["error"]}


async def backfill(days: int = LOOKBACK_DAYS) -> dict:
    """Walk back `days` calendar days, storing whatever published.

    Paced, and weekends are skipped rather than requested — asking the archive for a
    Sunday just earns a 404 and a pointless round trip.
    """
    today = datetime.now(IST)
    ok = missing = 0
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        if await screener_bhavcopy_collection.find_one({"_id": d.date().isoformat(), "ok": True}):
            ok += 1
            continue
        res = await capture(d)
        if res.get("ok"):
            ok += 1
        else:
            missing += 1
        await asyncio.sleep(0.6)
    _status["days_stored"] = ok
    logger.info("bhavcopy backfill: %s days stored, %s unavailable", ok, missing)
    return {"stored": ok, "unavailable": missing, "looked_back_days": days}


async def delivery_stats() -> dict[str, dict]:
    """Per-symbol delivery today and against its own recent habit.

    Returns {symbol: {delivery_pct, delivery_avg, delivery_ratio, trades, date}}. A symbol
    with no stored bhavcopy simply does not appear — callers must treat absence as unknown,
    which is why this returns a dict rather than filling in zeros.
    """
    global _delivery_cache
    import time as _time

    if _delivery_cache and _time.monotonic() - _delivery_cache[0] < DELIVERY_CACHE_TTL:
        return _delivery_cache[1]

    docs = [d async for d in screener_bhavcopy_collection.find(
        {"ok": True}, {"_id": 0, "date": 1, "rows": 1}).sort("date", -1).limit(DELIVERY_AVG_WINDOW + 1)]
    if not docs:
        return {}

    latest = docs[0]
    history: dict[str, list[float]] = {}
    for d in docs[1:]:
        for r in d.get("rows") or []:
            if r.get("delivery_pct") is not None:
                history.setdefault(r["symbol"], []).append(r["delivery_pct"])

    out: dict[str, dict] = {}
    for r in latest.get("rows") or []:
        pct = r.get("delivery_pct")
        if pct is None:
            continue
        prior = history.get(r["symbol"], [])
        avg = sum(prior) / len(prior) if prior else None
        out[r["symbol"]] = {
            "delivery_pct": pct,
            "delivery_avg": round(avg, 2) if avg is not None else None,
            # The ratio is what actually carries information — see the module docstring.
            "delivery_ratio": round(pct / avg, 2) if avg and avg > 0 else None,
            "delivery_qty": r.get("delivery_qty"),
            "trades": r.get("trades"),
            "turnover_lacs": r.get("turnover_lacs"),
            "date": latest["date"],
        }
    # Drop the raw documents before returning: `docs` holds tens of thousands of row dicts
    # and would otherwise stay reachable for as long as the caller keeps the result.
    docs.clear()
    _delivery_cache = (_time.monotonic(), out)
    return out


async def status() -> dict:
    days = await screener_bhavcopy_collection.count_documents({"ok": True})
    latest = await screener_bhavcopy_collection.find_one({"ok": True}, sort=[("date", -1)])
    return {
        "days_stored": days,
        "latest_date": (latest or {}).get("date"),
        "symbols_latest": (latest or {}).get("count", 0),
        "last_error": _status["last_error"],
        "source": "nsearchives.nseindia.com sec_bhavdata_full (EOD archive)",
        "note": ("Delivery % is only meaningful against a stock's own average, which is why "
                 f"a {DELIVERY_AVG_WINDOW}-day history is kept. Absent data reads as n/a, never 0."),
    }
