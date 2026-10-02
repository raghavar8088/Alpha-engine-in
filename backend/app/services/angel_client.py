"""Backend Angel One client — now a thin wrapper over the shared `tradingai-broker-clients`
package, so backend, prelive-service and market-data-service all use ONE Angel
implementation instead of three drifting copies.

Kept as a module (rather than importing the package at every call site) so existing
imports keep working unchanged:

    from app.services.angel_client import angel_client, AngelAPIError

The backend resolves credentials from its pydantic settings (its `.env` is loaded by
BaseSettings, which `AngelCredentials.from_env()` reading `os.environ` would not see), so
it builds the credentials explicitly and hands them to the shared client. Everything else
— session/login, batched LTP/FULL quotes, candles — lives in the package.

ONE PACER FOR EVERY CANDLE CALL IN THIS PROCESS
Angel documents 3 requests a second for its candle endpoint. Measured from this box on
2026-10-02 it refuses erratically and far below that: 6 of 20 calls spaced 0.4 s apart came
back "Access denied because of exceeding access rate" (a 403); at 1.0 s and at 1.5 s, 4 of
25 each; at 2.0 s and 0.7 s, none; four back-to-back calls were refused and the refusal
cleared within ~2 s. The SmartAPI forum carries the same report (post 19227). So the
shape that works is modest spacing plus a short, growing pause after a refusal and a
retry — not a single "safe" rate, which does not exist. Every desk here paced itself on its own
— the pattern desk at 1 s, the commodity desks at 3 s — so two of them running together
still collided, which is what the pattern desk's "candles failed … (403)" log lines were.
`candles()` now goes through one shared pacer: a minimum spacing between ANY two calls,
and after a refusal a cooldown that doubles on each consecutive refusal and resets on the
first success. Bulk jobs (the intraday backfill) take a slot only when no live caller is
queued for one, so a history download never delays a desk — and, unlike an earlier "wait
for N quiet seconds" rule, is not starved by desks that call every couple of seconds.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections import Counter

from tradingai_broker_clients.angel import AngelAPIError, AngelClient, AngelCredentials

from app.core.config import settings

__all__ = ["angel_client", "AngelClient", "AngelCredentials", "AngelAPIError",
           "candle_pacer", "is_rate_limited"]

logger = logging.getLogger("angel_client")

CANDLE_MIN_GAP = float(os.getenv("ANGEL_CANDLE_MIN_GAP", "1.1"))
CANDLE_COOLDOWN_BASE = float(os.getenv("ANGEL_CANDLE_COOLDOWN", "3"))
CANDLE_COOLDOWN_MAX = float(os.getenv("ANGEL_CANDLE_COOLDOWN_MAX", "60"))


def is_rate_limited(exc: Exception) -> bool:
    text = str(exc).lower()
    return "403" in text or "access rate" in text or "exceeding" in text


class CandlePacer:
    def __init__(self, gap: float, cooldown: float, cooldown_max: float):
        self.gap, self.cooldown, self.cooldown_max = gap, cooldown, cooldown_max
        self._lock = asyncio.Lock()
        self._next = 0.0
        self._cool_until = 0.0
        self._strikes = 0
        self._normal_waiting = 0
        self.stats = {"calls": 0, "refused": 0, "bulk_calls": 0, "waited_s": 0.0}
        # Who spends the candle budget — the endpoint is shared by a dozen desks, and
        # "the backfill is slow" is only answerable by knowing who else is calling.
        self.by_caller: Counter = Counter()
        self.refused_by_caller: Counter = Counter()

    async def acquire(self, bulk: bool = False) -> None:
        if bulk:
            # Priority without starvation: step aside only while a live caller is waiting.
            while self._normal_waiting > 0:
                await asyncio.sleep(0.2)
        else:
            self._normal_waiting += 1
        try:
            async with self._lock:
                wait = max(self._next, self._cool_until) - time.monotonic()
                if wait > 0:
                    self.stats["waited_s"] += wait
                    await asyncio.sleep(wait)
                self._next = time.monotonic() + self.gap
                self.stats["calls"] += 1
                if bulk:
                    self.stats["bulk_calls"] += 1
        finally:
            if not bulk:
                self._normal_waiting -= 1

    def refused(self) -> None:
        self._strikes += 1
        pause = min(self.cooldown_max, self.cooldown * 2 ** (self._strikes - 1))
        self._cool_until = max(self._cool_until, time.monotonic() + pause)
        self.stats["refused"] += 1
        if self._strikes in (1, 3, 6):
            logger.warning("Angel candle endpoint refused (%d in a row) — every candle call in "
                           "this process pauses %.0fs", self._strikes, pause)

    def succeeded(self) -> None:
        self._strikes = 0

    def describe(self) -> dict:
        now = time.monotonic()
        return {**{k: round(v, 1) if isinstance(v, float) else v for k, v in self.stats.items()},
                "min_gap_s": self.gap, "cooling_for_s": round(max(0.0, self._cool_until - now), 1),
                "consecutive_refusals": self._strikes,
                "by_caller": dict(self.by_caller.most_common(12)),
                "refused_by_caller": dict(self.refused_by_caller.most_common(12))}


candle_pacer = CandlePacer(CANDLE_MIN_GAP, CANDLE_COOLDOWN_BASE, CANDLE_COOLDOWN_MAX)


class _PacedAngelClient(AngelClient):
    async def candles(self, exchange, symbol_token, resolution, from_dt, to_dt, *,
                      bulk: bool = False):
        caller = sys._getframe(1).f_globals.get("__name__", "?").rsplit(".", 1)[-1]
        candle_pacer.by_caller[caller] += 1
        await candle_pacer.acquire(bulk=bulk)
        try:
            rows = await super().candles(exchange, symbol_token, resolution, from_dt, to_dt)
        except AngelAPIError as exc:
            if is_rate_limited(exc):
                candle_pacer.refused()
                candle_pacer.refused_by_caller[caller] += 1
            raise
        candle_pacer.succeeded()
        return rows


angel_client = _PacedAngelClient(
    AngelCredentials(
        api_key=settings.angelone_api_key,
        client_code=settings.angelone_client_code,
        pin=settings.angelone_pin,
        totp_secret=settings.angelone_totp_secret,
        public_ip=settings.angelone_public_ip,
        base_url=settings.angelone_base_url,
    )
)
