"""Async Angel One client (httpx) — for the asyncio services (backend, market-data-service).

One shared session per instance; concurrent callers coalesce on a single login via the
asyncio lock. Behaviour is identical to the backend's former `angel_client.py`; the only
change is that credentials are injected (an `AngelCredentials`) rather than read from a
specific settings module, so the same class serves every service.
"""

import asyncio
import logging
import time

import httpx

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

logger = logging.getLogger("angel_client")


class AngelClient:
    """Async Angel One market-data client. Quotes and candles only — never orders."""

    def __init__(self, creds: AngelCredentials | None = None) -> None:
        self.creds = creds or AngelCredentials.from_env()
        self._jwt: str | None = None
        self._feed_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return self.creds.configured()

    @property
    def feed_token(self) -> str | None:
        """Angel's WebSocket feed token, captured at login (used by the streaming client)."""
        return self._feed_token

    async def _session(self) -> str:
        async with self._lock:
            if self._jwt and time.time() < self._expires_at - SESSION_REFRESH_MARGIN_SECONDS:
                return self._jwt
            if not self.configured():
                raise AngelAPIError("Angel One credentials are not configured")
            totp = totp_now(self.creds.totp_secret)
            async with httpx.AsyncClient(base_url=self.creds.base_url, timeout=30) as c:
                r = await c.post(
                    LOGIN_PATH,
                    headers=client_headers(self.creds.api_key, self.creds.public_ip),
                    json=login_payload(self.creds.client_code, self.creds.pin, totp),
                )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            sess = parse_session(body if isinstance(body, dict) else {}, r.status_code)
            self._jwt = sess["jwt"]
            self._feed_token = sess["feed_token"]
            # Angel sessions run ~24h; trust the JWT when it says otherwise.
            self._expires_at = jwt_expiry(self._jwt) or (time.time() + 12 * 3600)
            logger.info("Angel One session established")
            return self._jwt

    async def _post(self, path: str, payload: dict) -> dict:
        jwt = await self._session()
        async with httpx.AsyncClient(base_url=self.creds.base_url, timeout=30) as c:
            r = await c.post(path, headers=client_headers(self.creds.api_key, self.creds.public_ip, jwt), json=payload)
        try:
            body = r.json()
        except Exception:
            raise AngelAPIError(f"Angel returned non-JSON ({r.status_code})")
        if not body.get("status"):
            raise AngelAPIError(f"Angel error: {body.get('message') or body.get('errorcode')}")
        return body

    async def ltp(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, float]:
        """{"NSE": ["3045"], "NFO": [...]} -> {token: last_price}."""
        out: dict[str, float] = {}
        for grouped in batches(tokens_by_exchange):
            body = await self._post(QUOTE_PATH, {"mode": "LTP", "exchangeTokens": grouped})
            out.update(parse_ltp(body))
        return out

    async def full_quote(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, dict]:
        """{"NSE": ["3045"], ...} -> {token: {ltp, open, high, low, close, volume}}."""
        out: dict[str, dict] = {}
        for grouped in batches(tokens_by_exchange):
            body = await self._post(QUOTE_PATH, {"mode": "FULL", "exchangeTokens": grouped})
            out.update(parse_full(body))
        return out

    async def candles(
        self, exchange: str, symbol_token: str, resolution: str, from_dt: str, to_dt: str
    ) -> list[list]:
        """Rows of [timestamp, open, high, low, close, volume]. `from_dt`/`to_dt` are
        "YYYY-MM-DD HH:MM"."""
        interval = ANGEL_INTERVALS.get(resolution)
        if interval is None:
            raise AngelAPIError(f"Angel has no interval for resolution {resolution}")
        body = await self._post(
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
