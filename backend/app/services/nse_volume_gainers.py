"""Daily capture of NSE's own volume-gainers list, for the Buy Low Options screener.

WHAT IT ADDS that Angel cannot: Angel gives price and today's volume, but not volume
RELATIVE to a stock's own recent habit. NSE publishes exactly that — today's quantity
against the stock's 1-week and 1-month average — which is the difference between "this
moved" and "this moved on volume it does not normally trade". A 4% fall on ordinary
volume is noise; the same fall on five times normal volume is someone doing something.

NSE IS NOT AN API. It is a website that serves JSON to its own front end, and it rejects
requests that do not look like a browser session: the endpoint 401s or hangs unless the
caller first loads a real page and carries the cookies it sets. So this primes a session
against the homepage, then the market-data page, and only then calls the JSON endpoint —
in one client so the cookie jar persists. It also fails SOFTLY: NSE blocks some datacentre
ranges outright, and this box may be in one, so a failure is recorded as a dated row with
its reason rather than throwing. The screener treats missing NSE data as missing, never as
zero.

Captured at 16:15 IST — after the 15:30 close, so the numbers are final for the day rather
than a mid-session snapshot that would be revised by the closing auction.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

from app.core.db import nse_volume_gainers_collection
from app.services.call_engine import IST

logger = logging.getLogger("nse_volume")

HOME = "https://www.nseindia.com"
PRIME_PAGES = ["/", "/market-data/volume-gainers-spurts"]
ENDPOINT = "/api/live-analysis-volume-gainers"
CAPTURE_HHMM = os.getenv("NSE_VOLUME_CAPTURE_HHMM", "16:15")
TIMEOUT = float(os.getenv("NSE_TIMEOUT", "25"))

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # NO Accept-Encoding here on purpose. Advertising "br" made NSE return Brotli, which
    # httpx cannot decode without the optional brotli package — the body then failed to
    # parse and this module reported it as "blocked", which was wrong and cost a diagnosis.
    # Letting httpx set the header means it only ever asks for what it can actually read.
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


async def fetch_volume_gainers() -> dict:
    """Pull NSE's volume-gainers table. Returns {ok, rows, error}."""
    try:
        async with httpx.AsyncClient(
            base_url=HOME, timeout=TIMEOUT, follow_redirects=True, headers=BROWSER_HEADERS
        ) as c:
            # Priming order matters and the homepage 403s from some hosts — that is fine,
            # it still seeds cookies, and the market-data page then completes the session.
            # A failure here is never fatal; only the endpoint's own answer decides.
            for page in PRIME_PAGES:
                try:
                    await c.get(page)
                except httpx.HTTPError:
                    pass
            # No X-Requested-With: NSE serves its own front end without it, and sending
            # it makes the request look scripted.
            r = await c.get(ENDPOINT, headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{HOME}/market-data/volume-gainers-spurts",
            })
            if r.status_code != 200:
                return {"ok": False, "rows": [], "error": f"NSE returned HTTP {r.status_code}"}
            try:
                body = r.json()
            except ValueError:
                # Distinguish the two failures that look identical from here: a real block
                # serves an HTML challenge page, whereas an undecodable body is our own
                # content-negotiation problem. Reporting both as "blocked" sent me looking
                # at NSE when the bug was local.
                ctype = r.headers.get("content-type", "")
                enc = r.headers.get("content-encoding", "")
                reason = ("HTML challenge page — NSE refused this client"
                          if "html" in ctype else
                          f"undecodable body (content-type {ctype!r}, encoding {enc!r})")
                return {"ok": False, "rows": [], "error": f"NSE returned non-JSON: {reason}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "rows": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    raw = body.get("data") if isinstance(body, dict) else body
    if not isinstance(raw, list):
        return {"ok": False, "rows": [], "error": "unexpected NSE payload shape"}

    rows = []
    for d in raw:
        sym = (d.get("symbol") or "").strip().upper()
        if not sym:
            continue
        today_qty = _num(d.get("volume"))
        wk1 = _num(d.get("week1AvgVolume"))
        wk2 = _num(d.get("week2AvgVolume"))
        # NSE publishes the ratios itself; use its numbers and only compute as a fallback,
        # so this table always agrees with what the exchange's own page shows.
        x1 = _num(d.get("week1volChange"))
        x2 = _num(d.get("week2volChange"))
        if x1 is None and today_qty and wk1:
            x1 = today_qty / wk1
        if x2 is None and today_qty and wk2:
            x2 = today_qty / wk2
        turnover_lakh = _num(d.get("turnover"))
        rows.append({
            "symbol": sym,
            "company": (d.get("companyName") or "").strip(),
            "ltp": _num(d.get("ltp")),
            "change_pct": _num(d.get("pChange")),
            "volume": today_qty,
            # These are 1-WEEK and 2-WEEK averages. NSE's field is `week2AvgVolume`, not a
            # month — naming it "month" would misdescribe the exchange's own data.
            "avg_1week_volume": wk1,
            "avg_2week_volume": wk2,
            # The whole point of this dataset: how unusual is today's participation.
            "volume_x_1week": round(x1, 2) if x1 is not None else None,
            "volume_x_2week": round(x2, 2) if x2 is not None else None,
            # NSE reports turnover in LAKHS on this endpoint.
            "turnover_lakh": turnover_lakh,
            "value_cr": round(turnover_lakh / 100, 2) if turnover_lakh else None,
        })
    rows.sort(key=lambda r: r["volume_x_1week"] or 0, reverse=True)
    return {"ok": True, "rows": rows, "error": None}


async def capture(force: bool = False) -> dict:
    """Store today's snapshot. Idempotent — re-running the same day overwrites."""
    day = _today()
    if not force and await nse_volume_gainers_collection.find_one({"_id": day, "ok": True}):
        return {"captured": False, "reason": "already captured today", "date": day}
    res = await fetch_volume_gainers()
    doc = {
        "_id": day, "date": day, "ts": _now(), "ok": res["ok"],
        "error": res["error"], "count": len(res["rows"]), "rows": res["rows"],
    }
    await nse_volume_gainers_collection.replace_one({"_id": day}, doc, upsert=True)
    if res["ok"]:
        logger.warning("nse-volume: captured %s rows for %s", len(res["rows"]), day)
    else:
        logger.warning("nse-volume: capture FAILED for %s (%s)", day, res["error"])
    return {"captured": True, "ok": res["ok"], "count": len(res["rows"]),
            "date": day, "error": res["error"]}


async def maybe_capture() -> dict:
    """Scheduler hook: run once per day at or after the capture time."""
    if datetime.now(IST).strftime("%H:%M") < CAPTURE_HHMM:
        return {"ran": False, "reason": f"before {CAPTURE_HHMM} IST"}
    if datetime.now(IST).weekday() >= 5:
        return {"ran": False, "reason": "weekend"}
    r = await capture()
    return {"ran": r.get("captured", False), **r}


async def latest(limit_rows: int = 200) -> dict:
    """Most recent successful capture, for the screener."""
    doc = await nse_volume_gainers_collection.find_one(
        {"ok": True}, sort=[("date", -1)])
    if not doc:
        last = await nse_volume_gainers_collection.find_one({}, sort=[("date", -1)])
        return {"date": None, "count": 0, "rows": [], "ok": False,
                "error": (last or {}).get("error") or "no NSE capture recorded yet"}
    return {"date": doc["date"], "count": doc.get("count", 0), "ok": True, "error": None,
            "captured_at": doc["ts"].isoformat() if doc.get("ts") else None,
            "rows": (doc.get("rows") or [])[:limit_rows]}


async def by_symbol() -> dict[str, dict]:
    """Latest capture keyed by symbol, so the screener can join it onto its own table."""
    doc = await nse_volume_gainers_collection.find_one({"ok": True}, sort=[("date", -1)])
    return {r["symbol"]: r for r in (doc.get("rows") or [])} if doc else {}


async def history(limit: int = 30) -> list[dict]:
    out = []
    async for d in nse_volume_gainers_collection.find(
        {}, {"rows": 0}).sort("date", -1).limit(limit):
        d.pop("_id", None)
        if d.get("ts"):
            d["ts"] = d["ts"].isoformat()
        out.append(d)
    return out
