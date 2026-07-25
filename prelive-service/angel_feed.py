"""Angel One (SmartAPI) price feed — the standby the desks fall back to when Dhan's
quote feed is unusable.

WHY A SECOND FEED AT ALL
------------------------
The desks' single documented failure mode is not bad strategy logic, it is a blind feed.
Dhan permits exactly one active token per account, so any component that mints a token
silently invalidates whoever else was holding one, and the desk spends the session
taking 401s. It also rate-limits per account (429). Both have produced whole zero-trade
sessions on the buying desk. A second, independent broker session removes the single
point of failure for PRICES specifically — not for orders, which this desk never places.

WHAT CHANGED (broker-clients consolidation, 2026-07-25)
------------------------------------------------------
Login/session/quoting now come from the shared `tradingai-broker-clients` package
(`AngelSyncClient`) — the same Angel implementation the backend and market-data-service
use — instead of a second hand-rolled copy that had drifted (different env-var names, its
own TOTP fallback, its own session handling).

Instrument identity also changed: the old in-process `AngelScripMap` (which rebuilt a
NIFTY-only Dhan→Angel token map from the scrip master on every process start) is gone.
Both desks and the backend point at the SAME Mongo `instruments` collection, and the
backend's `refresh_angel_tokens()` already stamps `angel_token`/`angel_exchange` on every
mappable contract there — with WIDER coverage than the old NIFTY-only map (~3700 index
options mapped vs ~1475). So this feed now just reads that stamp. The critical safety
property is unchanged: a contract without a stamped token is left unpriceable, never
guessed — a WRONG mark on a short option is far more dangerous than no mark.

CREDENTIALS come from `ANGELONE_*` env vars (via `AngelCredentials.from_env()`), the one
convention now shared across all services.
"""

import time

from tradingai_broker_clients.angel import AngelAPIError, AngelCredentials, AngelSyncClient

from db_selling import instruments_collection


def _angel_ref(security_id, exchange_segment) -> tuple[str, str] | None:
    """(angel_token, angel_exchange) for a Dhan (security_id, segment), read off the
    stamped `instruments` collection. None when unmapped — which stays unpriceable, never
    approximated. Security ids appear as both strings and ints across the collection, so
    match either form."""
    variants: list = [str(security_id)]
    try:
        variants.append(int(security_id))
    except (TypeError, ValueError):
        pass
    doc = instruments_collection.find_one(
        {"security_id": {"$in": variants}, "exchange_segment": exchange_segment},
        {"angel_token": 1, "angel_exchange": 1},
    )
    if not doc or not doc.get("angel_token"):
        return None
    return str(doc["angel_token"]), doc.get("angel_exchange") or "NSE"


class AngelOneFeed:
    """Batched LTP over Angel One. Same call shape the desks already use for Dhan:
    prefetch(...) then ltp(security_id, segment). Costs nothing while Dhan is healthy —
    the shared client only logs in on the first real quote."""

    def __init__(self, client: AngelSyncClient | None = None):
        self.client = client or AngelSyncClient(AngelCredentials.from_env())
        self.available = self.client.configured()
        self._cache: dict[tuple[str, str], float] = {}

    def prefetch(self, segment_ids: dict[str, list]) -> None:
        self._cache = {}
        if not self.available:
            return

        by_exchange: dict[str, list[str]] = {}
        token_to_key: dict[str, tuple[str, str]] = {}
        for seg, ids in segment_ids.items():
            for sid in ids:
                ref = _angel_ref(sid, seg)
                if ref is None:
                    continue  # unmapped contract — unpriceable, never guessed
                token, exchange = ref
                by_exchange.setdefault(exchange, []).append(token)
                token_to_key[token] = (str(sid), seg)
        if not by_exchange:
            return

        try:
            prices = self.client.ltp(by_exchange)  # {token: last_price}
        except AngelAPIError as exc:
            print(f"[angel] quote failed: {exc}", flush=True)
            return
        for token, price in prices.items():
            key = token_to_key.get(token)
            if key is not None:
                self._cache[key] = price

    def spot(self) -> float | None:
        return self.ltp(13, "IDX_I")

    def ltp(self, security_id, exchange_segment) -> float | None:
        return self._cache.get((str(security_id), exchange_segment))


class FailoverFeed:
    """Dhan first, Angel One when Dhan cannot answer.

    Failover is per-TICK and evidence-based, never a permanent switch: Dhan is retried
    on every tick, and the standby is used only for the securities Dhan actually failed
    to price. Dhan remains the desk's book of record because it is the account the
    strategies were qualified against; Angel exists so a token rotation or a 429 costs
    the desk visibility rather than the whole session.

    Presents exactly the DhanFeed surface (prefetch/spot/ltp/rate_limited/...) so both
    daemons can use it without knowing a second broker exists.
    """

    def __init__(self, dhan_feed, angel_feed: AngelOneFeed | None = None):
        self.dhan = dhan_feed
        self.angel = angel_feed or AngelOneFeed()
        self.failover_ticks = 0
        self.failover_prices = 0
        self._last_note = 0.0

    # --- pass-throughs the daemons read for feed-health reporting ---
    @property
    def rate_limited(self):
        return self.dhan.rate_limited

    @property
    def throttled_ticks(self):
        return self.dhan.throttled_ticks

    @property
    def auth_failed_ticks(self):
        return self.dhan.auth_failed_ticks

    def prefetch(self, segment_ids: dict[str, list]) -> None:
        self.dhan.prefetch(segment_ids)
        # Which securities did Dhan fail to price this tick?
        missing: dict[str, list] = {}
        for seg, ids in segment_ids.items():
            for sid in ids:
                if self.dhan.ltp(sid, seg) is None:
                    missing.setdefault(seg, []).append(sid)
        if not missing or not self.angel.available:
            return
        self.failover_ticks += 1
        if time.time() - self._last_note > 60:
            self._last_note = time.time()
            total = sum(len(v) for v in missing.values())
            print(f"[failover] Dhan could not price {total} security(s) — asking Angel One",
                  flush=True)
        self.angel.prefetch(missing)

    def spot(self) -> float | None:
        return self.ltp(13, "IDX_I")

    def ltp(self, security_id, exchange_segment) -> float | None:
        price = self.dhan.ltp(security_id, exchange_segment)
        if price is not None:
            return price
        price = self.angel.ltp(security_id, exchange_segment)
        if price is not None:
            self.failover_prices += 1
        return price
