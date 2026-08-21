"""NSE enrichment: market status, sectoral indices, top gainers/losers, delivery %.

THIS IS ENRICHMENT, NEVER THE SPINE. Momentum, sector rotation and chart patterns are all
computed from our own stored bars, so every function here can fail and the module still
works — it loses columns, not capability. That is deliberate: NSE blocks many datacentre IP
ranges outright, and this backend runs on one. The endpoints below have been confirmed
working from an Indian residential connection; whether they answer from the deployment box
is a separate question that only the box can settle, which is why every call records its
own outcome instead of throwing.

NSE IS NOT AN API. It is a website that serves JSON to its own front end and rejects
anything that does not look like a browser session — the endpoints 401 or hang unless the
caller first loads a real page and carries the cookies it sets. The priming sequence, the
header set, and the deliberate omission of Accept-Encoding are all lifted from
`nse_volume_gainers`, which paid for that knowledge already: advertising Brotli made NSE
return Brotli, httpx could not decode it without an optional package, and the module
reported a decode failure as "blocked" — a wrong diagnosis that cost real time.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

from app.core.db import screener_breadth_collection
from app.services.screener.horizons import IST

logger = logging.getLogger("screener.nse")

HOME = "https://www.nseindia.com"
PRIME_PAGES = ["/", "/market-data/live-market-indices"]
TIMEOUT = float(os.getenv("NSE_TIMEOUT", "25"))

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # No Accept-Encoding — see the module docstring. Letting httpx set it means NSE is only
    # ever asked for an encoding httpx can actually read.
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Endpoint -> the page NSE expects as its Referer. Sending a plausible referer is part of
# looking like the site's own front end.
ENDPOINTS = {
    "market_status": ("/api/marketStatus", "/"),
    "all_indices": ("/api/allIndices", "/market-data/live-market-indices"),
    "gainers": ("/api/live-analysis-variations?index=gainers", "/market-data/top-gainers-losers"),
    "losers": ("/api/live-analysis-variations?index=loosers", "/market-data/top-gainers-losers"),
}

_status: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


async def _fetch(client: httpx.AsyncClient, path: str, referer: str) -> tuple[dict | list | None, str | None]:
    try:
        r = await client.get(path, headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{HOME}{referer}",
        })
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        return r.json(), None
    except ValueError:
        ctype = r.headers.get("content-type", "")
        # Distinguish a real block (an HTML challenge page) from our own content
        # negotiation problem. Reporting both as "blocked" sends the next person
        # debugging NSE when the bug is local.
        return None, ("HTML challenge page — NSE refused this client"
                      if "html" in ctype else f"non-JSON body (content-type {ctype!r})")


async def fetch_all() -> dict:
    """Pull every NSE endpoint in one primed session. Never raises."""
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(base_url=HOME, timeout=TIMEOUT,
                                     follow_redirects=True, headers=BROWSER_HEADERS) as c:
            # The homepage 403s from some hosts; that is fine, it still seeds cookies and
            # the second page completes the session. Only the endpoint's own answer counts.
            for page in PRIME_PAGES:
                try:
                    await c.get(page)
                except httpx.HTTPError:
                    pass
            for key, (path, referer) in ENDPOINTS.items():
                body, err = await _fetch(c, path, referer)
                out[key] = {"ok": err is None, "error": err, "body": body}
                await asyncio.sleep(0.3)
    except Exception as exc:  # noqa: BLE001 — an NSE outage must never take a page down
        logger.warning("NSE fetch failed wholesale: %s", exc)
        return {k: {"ok": False, "error": f"session failed: {exc}", "body": None}
                for k in ENDPOINTS}

    _status.update({k: {"ok": v["ok"], "error": v["error"], "at": _now().isoformat()}
                    for k, v in out.items()})
    return out


def parse_indices(body) -> list[dict]:
    """Sectoral and broad indices with their day change."""
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for d in rows:
        name = (d.get("index") or "").strip()
        if not name:
            continue
        out.append({
            "index": name,
            "symbol": (d.get("indexSymbol") or "").strip(),
            "last": _num(d.get("last")),
            "change": _num(d.get("variation")),
            "change_pct": _num(d.get("percentChange")),
            "open": _num(d.get("open")),
            "high": _num(d.get("high")),
            "low": _num(d.get("low")),
            "year_high": _num(d.get("yearHigh")),
            "year_low": _num(d.get("yearLow")),
            "key": (d.get("key") or "").strip(),
        })
    return out


def parse_variations(body) -> list[dict]:
    """NSE's top gainers / losers. The payload nests the rows under a legend key that
    varies by segment, so this walks whatever dicts carry a `data` list."""
    if not isinstance(body, dict):
        return []
    rows = []
    for value in body.values():
        if isinstance(value, dict) and isinstance(value.get("data"), list):
            rows.extend(value["data"])
    out = []
    for d in rows:
        sym = (d.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "ltp": _num(d.get("ltp") or d.get("lastPrice")),
            "change_pct": _num(d.get("perChange") or d.get("pChange")),
            "volume": _num(d.get("trade_quantity") or d.get("totalTradedVolume")),
            "turnover_cr": _num(d.get("turnover")),
        })
    # NSE repeats a symbol across segment legends; keep the first sighting of each.
    seen, unique = set(), []
    for r in out:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            unique.append(r)
    return unique


def sector_indices(indices: list[dict]) -> list[dict]:
    """Just the sectoral ones — NSE tags them in the `key` field."""
    return [i for i in indices
            if "SECTORAL" in (i.get("key") or "").upper()
            or i["index"].upper().startswith("NIFTY ")
            and any(w in i["index"].upper() for w in
                    ("BANK", "IT", "PHARMA", "AUTO", "METAL", "FMCG", "REALTY",
                     "MEDIA", "ENERGY", "PSU", "FIN", "CONSUMER", "HEALTHCARE",
                     "OIL", "CHEMICAL"))]


async def snapshot(persist: bool = False) -> dict:
    """One combined NSE read for the Sources tab and the breadth strip."""
    raw = await fetch_all()

    indices = parse_indices(raw["all_indices"]["body"]) if raw["all_indices"]["ok"] else []
    gainers = parse_variations(raw["gainers"]["body"]) if raw["gainers"]["ok"] else []
    losers = parse_variations(raw["losers"]["body"]) if raw["losers"]["ok"] else []

    status_body = raw["market_status"]["body"] if raw["market_status"]["ok"] else None
    market_open = None
    if isinstance(status_body, dict):
        states = status_body.get("marketState") or []
        cap = next((s for s in states if s.get("market") == "Capital Market"), None)
        if cap:
            market_open = (cap.get("marketStatus") or "").lower() == "open"

    result = {
        "ok": any(v["ok"] for v in raw.values()),
        "market_open": market_open,
        "indices": indices,
        "sector_indices": sector_indices(indices),
        "gainers": gainers[:25],
        "losers": losers[:25],
        "endpoints": {k: {"ok": v["ok"], "error": v["error"]} for k, v in raw.items()},
        "fetched_at": _now().isoformat(),
        "note": ("NSE is enrichment here, not the data spine. Every momentum, sector and "
                 "pattern number on this page comes from stored bars and works without it."),
    }

    if persist:
        day = datetime.now(IST).date().isoformat()
        await screener_breadth_collection.replace_one(
            {"_id": day},
            {"_id": day, "date": day, "ts": _now(),
             "ok": result["ok"], "endpoints": result["endpoints"],
             "sector_indices": result["sector_indices"],
             "gainers": result["gainers"], "losers": result["losers"]},
            upsert=True,
        )
    return result


def last_status() -> dict:
    """Whatever the last attempt reported, for the Sources tab — without re-fetching."""
    return dict(_status)
