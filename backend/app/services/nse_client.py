"""One NSE session for every nseindia.com / nsearchives.nseindia.com fetch.

NSE serves its JSON API and its archives only to a session that looks like a browser that
has visited the site: a bare request gets a 401 or an Akamai block page. This client
primes the session on the home page (and the page the API belongs to), retries with a
growing pause, re-primes after a refusal, and paces itself so a burst of archive
downloads never trips the site's limits. Measured from this host on 2026-10-02: the
archives, the pre-open API, the board-meetings API and the financial-results API all
answer this way; BSE's API does not (Akamai "Access Denied" to data-centre addresses).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger("nse_client")

HOME = "https://www.nseindia.com"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
           "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
MIN_GAP_S = 0.6


class NSEClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._primed_at = 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0
        self.stats = {"requests": 0, "ok": 0, "refused": 0}

    async def _session(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=45, follow_redirects=True, headers=HEADERS)
        if time.monotonic() - self._primed_at > 600:
            await self.prime()
        return self._client

    async def prime(self, page: str | None = None) -> None:
        c = self._client or httpx.AsyncClient(timeout=45, follow_redirects=True, headers=HEADERS)
        self._client = c
        for url in (HOME, f"{HOME}{page}" if page else None):
            if not url:
                continue
            try:
                await c.get(url, headers={**HEADERS, "Accept": "text/html"})
            except httpx.HTTPError:
                pass
        self._primed_at = time.monotonic()

    async def _pace(self) -> None:
        async with self._lock:
            wait = self._next - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next = time.monotonic() + MIN_GAP_S

    async def get(self, url: str, referer: str | None = None, tries: int = 4,
                  json_api: bool = False) -> httpx.Response | None:
        """GET with retries. None for a 404 (no file published) or after `tries` failures."""
        c = await self._session()
        headers = {**HEADERS, "Referer": f"{HOME}{referer}" if referer else f"{HOME}/all-reports"}
        if json_api:
            headers["Accept"] = "application/json, text/plain, */*"
        for k in range(tries):
            await self._pace()
            self.stats["requests"] += 1
            try:
                r = await c.get(url, headers=headers)
                if r.status_code == 200:
                    if json_api:
                        try:
                            r.json()
                        except ValueError:
                            raise httpx.HTTPError("non-JSON answer")
                    self.stats["ok"] += 1
                    return r
                if r.status_code == 404:
                    return None
                self.stats["refused"] += 1
            except httpx.HTTPError as exc:
                logger.debug("NSE %s attempt %d: %s", url, k + 1, exc)
            await asyncio.sleep(2 + 3 * k)
            await self.prime(referer)
        return None

    async def api(self, path: str, referer: str) -> dict | list | None:
        r = await self.get(f"{HOME}{path}", referer=referer, json_api=True)
        return r.json() if r is not None else None


nse = NSEClient()
