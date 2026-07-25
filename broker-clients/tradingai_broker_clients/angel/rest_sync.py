"""Sync Angel One client (requests) — for the synchronous services (prelive daemons,
market-data-service).

Same auth/quote/candle logic as the async client (all shared via `auth.py`), but with a
blocking `requests` transport and the inter-request self-throttle the prelive feed already
relied on (`REQUEST_GAP_SECONDS`) — a gentle per-second cap so the desks never trip Angel's
own rate limit. A 401 nulls the session so the next call re-logs in.
"""

import logging
import threading
import time

import requests

from .auth import (
    ANGEL_INTERVALS,
    CANDLE_PATH,
    LOGIN_PATH,
    QUOTE_PATH,
    SESSION_REFRESH_MARGIN_SECONDS,
    AngelAPIError,
    batches,
    client_headers,
    jwt_expiry,
    login_payload,
    parse_full,
    parse_ltp,
    parse_session,
    totp_now,
)
from .credentials import AngelCredentials

logger = logging.getLogger("angel_sync")

# Keep well under Angel's per-second quote limit; the daemons poll every ~15s so this only
# paces the rare multi-chunk burst.
REQUEST_GAP_SECONDS = 0.35


class AngelSyncClient:
    """Synchronous Angel One market-data client. Quotes and candles only — never orders."""

    def __init__(self, creds: AngelCredentials | None = None) -> None:
        self.creds = creds or AngelCredentials.from_env()
        self._jwt: str | None = None
        self._feed_token: str | None = None
        self._expires_at: float = 0.0
        self._last_request: float = 0.0
        self._lock = threading.Lock()

    def configured(self) -> bool:
        return self.creds.configured()

    @property
    def feed_token(self) -> str | None:
        return self._feed_token

    def _throttle(self) -> None:
        gap = REQUEST_GAP_SECONDS - (time.monotonic() - self._last_request)
        if gap > 0:
            time.sleep(gap)
        self._last_request = time.monotonic()

    def _session(self) -> str:
        with self._lock:
            if self._jwt and time.time() < self._expires_at - SESSION_REFRESH_MARGIN_SECONDS:
                return self._jwt
            if not self.configured():
                raise AngelAPIError("Angel One credentials are not configured")
            totp = totp_now(self.creds.totp_secret)
            r = requests.post(
                self.creds.base_url + LOGIN_PATH,
                headers=client_headers(self.creds.api_key, self.creds.public_ip),
                json=login_payload(self.creds.client_code, self.creds.pin, totp),
                timeout=15,
            )
            body = r.json() if r.content else {}
            sess = parse_session(body if isinstance(body, dict) else {}, r.status_code)
            self._jwt = sess["jwt"]
            self._feed_token = sess["feed_token"]
            self._expires_at = jwt_expiry(self._jwt) or (time.time() + 12 * 3600)
            logger.info("Angel One session established (sync)")
            return self._jwt

    def _post(self, path: str, payload: dict) -> dict:
        jwt = self._session()
        self._throttle()
        r = requests.post(
            self.creds.base_url + path,
            headers=client_headers(self.creds.api_key, self.creds.public_ip, jwt),
            json=payload,
            timeout=15,
        )
        if r.status_code == 401:
            self._jwt = None  # session died; next call re-logs in
            raise AngelAPIError("Angel session expired (401)")
        try:
            body = r.json()
        except Exception:
            raise AngelAPIError(f"Angel returned non-JSON ({r.status_code})")
        if not body.get("status"):
            raise AngelAPIError(f"Angel error: {body.get('message') or body.get('errorcode')}")
        return body

    def ltp(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for grouped in batches(tokens_by_exchange):
            body = self._post(QUOTE_PATH, {"mode": "LTP", "exchangeTokens": grouped})
            out.update(parse_ltp(body))
        return out

    def full_quote(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for grouped in batches(tokens_by_exchange):
            body = self._post(QUOTE_PATH, {"mode": "FULL", "exchangeTokens": grouped})
            out.update(parse_full(body))
        return out

    def candles(
        self, exchange: str, symbol_token: str, resolution: str, from_dt: str, to_dt: str
    ) -> list[list]:
        interval = ANGEL_INTERVALS.get(resolution)
        if interval is None:
            raise AngelAPIError(f"Angel has no interval for resolution {resolution}")
        body = self._post(
            CANDLE_PATH,
            {
                "exchange": exchange,
                "symboltoken": str(symbol_token),
                "interval": interval,
                "fromdate": from_dt,
                "todate": to_dt,
            },
        )
        return body.get("data") or []
