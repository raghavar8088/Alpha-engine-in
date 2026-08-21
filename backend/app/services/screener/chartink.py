"""Optional Chartink scan adapter — a SECONDARY idea feed, off by default.

WHAT WAS ACTUALLY VERIFIED (probe, 2026-08-21, not documentation):

  * `POST https://chartink.com/screener/process` works with NO login. Prime a session on
    `/screener/`, read the `csrf-token` meta tag, then POST `scan_clause` with the token in
    an `x-csrf-token` header on the same cookie jar. It returns
    `{"data":[{"nsecode","name","bsecode","close","per_chg","volume"}, ...]}`.
  * Dashboard 11543 is PUBLIC — `is_private: false`. `GET /dashboard/11543/widgets` returns
    all 20 widget definitions and their query strings without logging in.
  * BUT the dashboard's widget query language is NOT executable through
    `/screener/process`: posting a widget query verbatim returns
    `{"data":[],"scan_error":"There was a error in running your scan"}`. Their JS bundle
    exposes only `/screener/process` and `/backtest/process`, so the dashboard's RENDERED
    NUMBERS cannot be fetched at all. Its definitions are readable; its output is not.

WHY THIS IS OFF BY DEFAULT. Free-tier Chartink data is delayed — commonly reported at
30-45 minutes intraday — which makes it unusable for anything this app would trade. The
endpoint is undocumented and can change or throttle without notice, and scraping it is a
grey area against their terms when the app already pays for a licensed Angel One feed.

WHAT IT IS STILL GOOD FOR. A handful of scans that are genuinely cheaper to ask Chartink
than to compute — chiefly anything needing INTRADAY bars across the whole market, which
this app does not store. Those are the presets below. Everything else the Stock Screener
shows is computed on our own data, live, and does not come from here.

The module fails soft in every path: a Chartink outage returns `ok: false` with a reason
and never raises into a page.
"""

from __future__ import annotations

import logging
import os
import re
import time

import httpx

logger = logging.getLogger("screener.chartink")

ENABLED = os.getenv("SCREENER_CHARTINK_ENABLED", "0").lower() not in ("0", "false", "")
BASE = "https://chartink.com"
SCREENER_PAGE = "/screener/"
PROCESS = "/screener/process"
TIMEOUT = float(os.getenv("CHARTINK_TIMEOUT", "30"))
CACHE_TTL = float(os.getenv("CHARTINK_CACHE_TTL", "900"))  # 15 min; the data is older than that

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Segment tokens Chartink uses inside a scan clause. {33489} is its Nifty 500 group.
NIFTY500 = "{33489}"

# Only scans that need something we do NOT store. Anything computable from our daily bars
# belongs in the local engine, not here — duplicating it would mean showing a delayed
# number beside a live one with no way for a reader to tell which was which.
PRESETS: dict[str, dict] = {
    "volume_spurt_5m": {
        "label": "5-minute volume spurt",
        "why": "Needs intraday bars across the whole market, which this app does not store.",
        "clause": (f"( {NIFTY500} ( [0] 5 minute volume > 3 * [0] 5 minute sma( [0] 5 minute volume , 20 ) "
                   f"and [0] 5 minute close > [0] 5 minute open ) )"),
    },
    "above_vwap": {
        "label": "Trading above VWAP",
        "why": "VWAP is an intraday construct; daily bars cannot produce it.",
        "clause": f"( {NIFTY500} ( [0] 15 minute close > [0] 15 minute vwap ) )",
    },
    "opening_range_break": {
        "label": "Opening-range breakout",
        "why": "Requires the first 15 minutes of the session, which we do not store.",
        "clause": (f"( {NIFTY500} ( [0] 15 minute close > [-1] 15 minute high "
                   f"and [0] 15 minute volume > [-1] 15 minute volume ) )"),
    },
}

_cache: dict[str, tuple[float, dict]] = {}


class ChartinkUnavailable(Exception):
    pass


async def _session_and_token(client: httpx.AsyncClient) -> str:
    """Prime a session and lift the CSRF token from the screener page.

    Both halves must come from the SAME client: the token is bound to the session cookie,
    and pairing a token from one request with cookies from another is the "CSRF token
    mismatch" that makes this look broken when it is not.
    """
    r = await client.get(SCREENER_PAGE, follow_redirects=True)
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text)
    if not m:
        raise ChartinkUnavailable("no csrf-token on the screener page — layout changed")
    return m.group(1)


async def run_clause(clause: str, referer: str = SCREENER_PAGE) -> dict:
    """Execute one scan clause. Returns {ok, rows, error, delayed}."""
    if not ENABLED:
        return {"ok": False, "rows": [], "error": "Chartink adapter disabled "
                "(set SCREENER_CHARTINK_ENABLED=1)", "delayed": True}
    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT,
                                     headers={"User-Agent": UA}) as c:
            token = await _session_and_token(c)
            r = await c.post(
                PROCESS,
                data={"scan_clause": clause},
                headers={
                    "x-csrf-token": token,
                    "x-requested-with": "XMLHttpRequest",
                    "Referer": f"{BASE}{referer}",
                },
            )
            if r.status_code != 200:
                return {"ok": False, "rows": [], "error": f"HTTP {r.status_code}", "delayed": True}
            body = r.json()
    except ChartinkUnavailable as exc:
        return {"ok": False, "rows": [], "error": str(exc), "delayed": True}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "rows": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                "delayed": True}

    if isinstance(body, dict) and body.get("scan_error"):
        return {"ok": False, "rows": [], "error": body["scan_error"], "delayed": True}

    rows = []
    for d in (body.get("data") or []) if isinstance(body, dict) else []:
        sym = (d.get("nsecode") or "").strip().upper()
        if not sym:
            continue
        rows.append({
            "symbol": sym,
            "name": (d.get("name") or "").strip(),
            "close": d.get("close"),
            "change_pct": d.get("per_chg"),
            "volume": d.get("volume"),
        })
    return {"ok": True, "rows": rows, "error": None, "delayed": True}


async def preset(key: str, fresh: bool = False) -> dict:
    """Run one of the curated presets, cached."""
    spec = PRESETS.get(key)
    if not spec:
        return {"ok": False, "rows": [], "error": f"unknown preset {key!r}",
                "available": sorted(PRESETS)}

    now = time.monotonic()
    if not fresh:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]

    res = await run_clause(spec["clause"])
    out = {
        **res,
        "preset": key,
        "label": spec["label"],
        "why_not_local": spec["why"],
        "source": "chartink.com (free tier)",
        "warning": ("Chartink's free tier serves DELAYED data — commonly 30-45 minutes "
                    "intraday. Do not trade this as a live price. Every other number on "
                    "this page is live Angel One or computed from stored bars."),
        "fetched_at": time.time(),
    }
    _cache[key] = (now, out)
    return out


def presets() -> list[dict]:
    return [{"key": k, "label": v["label"], "why_not_local": v["why"]}
            for k, v in PRESETS.items()]


def status() -> dict:
    return {
        "enabled": ENABLED,
        "presets": presets(),
        "verified": {
            "scan_api": "works without login (POST /screener/process with scan_clause)",
            "dashboard_11543": "public; GET /dashboard/11543/widgets returns 20 widget "
                               "definitions without login",
            "dashboard_numbers": "NOT retrievable — widget queries are not executable via "
                                 "/screener/process, and no public execute-widget route exists",
        },
        "policy": ("Secondary idea feed only. Delayed, undocumented and ToS-grey; the "
                   "screener's own numbers never depend on it."),
    }
