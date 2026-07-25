"""Shared broker clients for TradingAI services.

Before this package there were TWO independent, hand-rolled Angel One implementations —
`backend/app/services/angel_client.py` (async, httpx) and `prelive-service/angel_feed.py`
(sync, requests) — each with its own TOTP login, JWT-expiry handling, batched quoting and
instrument mapping, using different env-var names. They drifted apart and only one carried
things like the request self-throttle. This package is the single source of truth: one
auth flow, one credential convention (`ANGELONE_*`), one set of quote/candle parsing, with
an async and a sync transport over the same shared logic.

Angel One is a market-DATA standby only — never an order path (orders stay on Dhan).
"""

from .angel import (
    AngelAPIError,
    AngelClient,
    AngelCredentials,
    AngelSyncClient,
)

__all__ = ["AngelAPIError", "AngelClient", "AngelCredentials", "AngelSyncClient"]
