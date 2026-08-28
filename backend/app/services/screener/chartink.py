"""Optional Chartink scan adapter — a SECONDARY idea feed, off by default.

WHAT WAS ACTUALLY VERIFIED (probe, 2026-08-21, not documentation):

  * `POST https://chartink.com/screener/process` works with NO login. Prime a session on
    `/screener/`, read the `csrf-token` meta tag, then POST `scan_clause` with the token in
    an `x-csrf-token` header on the same cookie jar. It returns
    `{"data":[{"nsecode","name","bsecode","close","per_chg","volume"}, ...]}`.
  * Dashboard 11543 is PUBLIC — `is_private: false`. `GET /dashboard/11543/widgets` returns
    all 20 widget definitions and their query strings without logging in.
  * ANY PUBLIC NAMED SCREENER can be both READ and RUN, e.g.
    `/screener/short-term-breakouts`. The clause is NOT in the page as `scan_clause` — the
    page is a Vue app and the scan arrives as a prop: `<scanner :scan-json="{...}">`,
    HTML-escaped JSON whose `atlas_query` field IS the executable clause. Feed that to
    `/screener/process` and it returns rows. Verified from the AWS box on 2026-08-28:
    short-term-breakouts 33 rows, breakouts 139, volume-shockers 44, rsi-crossing-60 150,
    each in well under a second. A bad slug 404s cleanly. This is what makes the adapter
    worth more than a fixed preset list — it can be pointed at any screener URL.
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

import html
import json
import logging
import os
import re
import time

import httpx

logger = logging.getLogger("screener.chartink")

ENABLED = os.getenv("SCREENER_CHARTINK_ENABLED", "1").lower() not in ("0", "false", "")
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
    # ── things we cannot compute: they need INTRADAY bars, which this app does not store ──
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
    "intraday_reversal": {
        "label": "Intraday reversal off the low",
        "why": "Compares the session's own low to where it is now — an intraday shape.",
        "clause": (f"( {NIFTY500} ( [0] 15 minute close > [0] 15 minute open "
                   f"and [-2] 15 minute close < [-2] 15 minute open "
                   f"and [0] 15 minute rsi( 14 ) > 50 ) )"),
    },

    # ── whole-market scans: genuinely additive because our own universe stops at the
    #    Nifty 500, and most volume surprises happen outside it ──
    "all_market_gainers": {
        "label": "Whole-market gainers (beyond Nifty 500)",
        "why": "Our universe is the Nifty 500; this reaches the ~1,800 names outside it.",
        "clause": ("( {cash} ( latest close > 1 day ago close * 1.05 "
                   "and latest volume > 200000 and latest close > 30 ) )"),
    },
    "all_market_volume_breakout": {
        "label": "Whole-market volume breakout",
        "why": "Same reach beyond our universe, filtered to real participation.",
        "clause": ("( {cash} ( latest volume > 3 * latest sma( latest volume , 20 ) "
                   "and latest close > latest max( 20 , latest high ) * 0.99 "
                   "and latest close > 30 ) )"),
    },
    "all_market_52w_high": {
        "label": "Whole-market 52-week highs",
        "why": "Catches names at new highs that never enter a Nifty index.",
        "clause": ("( {cash} ( latest high >= latest max( 252 , latest high ) "
                   "and latest volume > 100000 and latest close > 30 ) )"),
    },
}

# Public screeners worth having one click away. Every one of these was RUN from the AWS
# box on 2026-08-28 and returned rows — none is a guess. `why` says what it adds over the
# local engine, because a scan this app can already compute has no business being fetched
# from a delayed third party and shown beside live numbers.
NAMED: dict[str, dict] = {
    "short-term-breakouts": {
        "label": "Short term breakouts",
        "why": "5-day close 5% above the 6-month high, on volume above its own 5-day mean.",
    },
    "breakouts": {
        "label": "Breakouts (RSI + ADX + MACD)",
        "why": "Multi-indicator confluence — broader than our single-signal setups.",
    },
    "volume-shockers": {
        "label": "Volume shockers",
        "why": "Volume above 5x its 20-day mean across the WHOLE cash market.",
    },
    "rsi-crossing-60": {
        "label": "RSI crossing 60",
        "why": "Momentum ignition on the day it happens, whole market.",
    },
    "bullish-marubozu-1": {
        "label": "Bullish marubozu",
        "why": "Single-candle conviction; our pattern engine reads multi-bar structures.",
    },
    "nr7-narrow-range-7": {
        "label": "NR7 narrow range",
        "why": "Compression before expansion — a setup we do not screen for locally.",
    },
}

# The scan arrives as a Vue prop, HTML-escaped; `atlas_query` inside it is the clause.
_SCAN_JSON_RE = re.compile(r':scan-json="([^"]+)"')
_CSRF_RE = re.compile(r'name="csrf-token"\s+content="([^"]+)"')
_BEHIND_RE = re.compile(r"scanBehindByTimeInMins\s*=\s*[\"\']?(\d+)")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,80}$")
_URL_RE = re.compile(r"chartink\.com/screener/([a-z0-9\-]+)")

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

    return {"ok": True, "rows": _rows(body), "error": None, "delayed": True}


def _rows(body: object) -> list[dict]:
    out = []
    for d in (body.get("data") or []) if isinstance(body, dict) else []:
        sym = (d.get("nsecode") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "name": (d.get("name") or "").strip(),
            "close": d.get("close"),
            "change_pct": d.get("per_chg"),
            "volume": d.get("volume"),
        })
    return out


def parse_slug(value: str) -> str | None:
    """Accept a slug or a full Chartink URL; None if it is neither.

    Validated rather than trusted. This string is interpolated into the path of an outbound
    request, so a value like `../../admin` or one carrying a query string would build a
    request we never meant to make.
    """
    v = (value or "").strip().lower()
    if not v:
        return None
    m = _URL_RE.search(v)
    if m:
        v = m.group(1)
    v = v.strip("/").split("?")[0].split("#")[0]
    return v if _SLUG_RE.match(v) else None


async def _fetch_scan(client: httpx.AsyncClient, slug: str) -> tuple[str, dict]:
    """Return (csrf token, the screener's own definition) for a public named screener."""
    r = await client.get(f"/screener/{slug}", follow_redirects=True)
    if r.status_code == 404:
        raise ChartinkUnavailable(f"no public Chartink screener called {slug!r}")
    if r.status_code != 200:
        raise ChartinkUnavailable(f"HTTP {r.status_code} fetching /screener/{slug}")

    tok = _CSRF_RE.search(r.text)
    if not tok:
        raise ChartinkUnavailable("no csrf-token on the page — layout changed")

    m = _SCAN_JSON_RE.search(r.text)
    if not m:
        # A private screener still renders a page but withholds the prop. Name that case:
        # "returned nothing" and "not yours to read" call for opposite responses.
        raise ChartinkUnavailable(
            f"{slug!r} exists but its definition is not public — a private screener is only "
            "readable while signed in as its owner")
    try:
        scan = json.loads(html.unescape(m.group(1)))
    except ValueError as exc:
        raise ChartinkUnavailable(f"could not parse the scan definition: {exc}") from exc

    if not scan.get("atlas_query"):
        raise ChartinkUnavailable(f"{slug!r} carries no runnable clause")

    # Chartink stamps its own lag on the page. It is empty outside market hours, which is
    # why the caller falls back to a stated range rather than inventing a number.
    lag = _BEHIND_RE.search(r.text)
    scan["_behind_mins"] = int(lag.group(1)) if lag else None
    return tok.group(1), scan


async def named(slug_or_url: str, fresh: bool = False) -> dict:
    """Read a public Chartink screener by name and RUN it.

    Two steps, both required: the page holds the scan definition but not its results, and
    `/screener/process` runs a clause but knows no screener by name.
    """
    slug = parse_slug(slug_or_url)
    if not slug:
        return {"ok": False, "rows": [], "error":
                "That is not a Chartink screener. Paste a URL like "
                "https://chartink.com/screener/short-term-breakouts — or just the last "
                "part of it."}
    if not ENABLED:
        return {"ok": False, "rows": [], "error":
                "Chartink adapter disabled (set SCREENER_CHARTINK_ENABLED=1)"}

    ck = f"named:{slug}"
    now = time.monotonic()
    if not fresh:
        hit = _cache.get(ck)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]

    clause = None
    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT,
                                     headers={"User-Agent": UA}) as c:
            tok, scan = await _fetch_scan(c, slug)
            clause = scan["atlas_query"]
            r = await c.post(
                PROCESS,
                data={"scan_clause": clause},
                headers={"x-csrf-token": tok, "x-requested-with": "XMLHttpRequest",
                         "Referer": f"{BASE}/screener/{slug}"},
            )
            if r.status_code != 200:
                return {"ok": False, "rows": [], "clause": clause,
                        "error": f"HTTP {r.status_code} running the scan"}
            body = r.json()
    except ChartinkUnavailable as exc:
        return {"ok": False, "rows": [], "error": str(exc)}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "rows": [], "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    if isinstance(body, dict) and body.get("scan_error"):
        return {"ok": False, "rows": [], "error": body["scan_error"], "clause": clause}

    behind = scan.get("_behind_mins")
    out = {
        "ok": True,
        "rows": _rows(body),
        "error": None,
        "slug": slug,
        "url": f"{BASE}/screener/{slug}",
        "name": scan.get("name") or slug,
        "description": scan.get("description"),
        # The clause is shown, never hidden. It is the only way a reader can tell whether
        # the screen means what its name suggests — "Breakouts" is a title, not a definition.
        "clause": clause,
        "delayed": True,
        "behind_mins": behind,
        "warning": (
            f"Chartink reports this scan running {behind} minutes behind live."
            if behind else
            "Chartink's free tier serves DELAYED data — commonly 30-45 minutes intraday. "
            "Do not trade these as live prices. Every other number in this module is live "
            "Angel One or computed from stored bars."),
        "fetched_at": time.time(),
        "source": "chartink.com (free tier)",
    }
    _cache[ck] = (now, out)
    return out


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
        "named": [{"slug": k, "label": v["label"], "why": v["why"],
                   "url": f"{BASE}/screener/{k}"} for k, v in NAMED.items()],
        "verified": {
            "scan_api": "works without login (POST /screener/process with scan_clause)",
            "named_screeners": "readable AND runnable — the clause is the atlas_query "
                               "field inside the page's :scan-json prop, which "
                               "/screener/process then executes. Any public screener works.",
            "dashboard_11543": "public; GET /dashboard/11543/widgets returns 20 widget "
                               "definitions without login",
            "dashboard_numbers": "NOT retrievable — widget queries are not executable via "
                                 "/screener/process, and no public execute-widget route exists",
        },
        "policy": ("Secondary idea feed only. Delayed, undocumented and ToS-grey; the "
                   "screener's own numbers never depend on it."),
    }
