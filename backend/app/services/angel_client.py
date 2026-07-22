"""Angel One SmartAPI client — the standby market-data broker behind Dhan.

Exists because Dhan allows exactly one active access token per account, so a token
rotated out from under this app takes every quote and candle with it (see the
2026-07-17 desk outage). Angel One is a second, independent source for the two
read paths that matter when that happens: live LTP and historical candles. It is
NOT an order path — placing trades stays with Dhan.

Auth is TOTP-based (loginByPassword -> jwtToken), same shape as the Dhan flow, and
the session is cached in-process until shortly before it expires. Angel enforces
IP whitelisting, so this only works from a whitelisted host (the AWS box).
Docs: https://smartapi.angelbroking.com/docs
"""

import asyncio
import base64
import json
import logging
import time

import httpx
import pyotp

from app.core.config import settings

logger = logging.getLogger("angel_client")

# Angel caps a quote request at 50 tokens; chunk anything larger.
QUOTE_BATCH_SIZE = 50
# Refresh the session a little before the JWT actually lapses.
SESSION_REFRESH_MARGIN_SECONDS = 10 * 60

# TradingView-ish resolution -> Angel interval name.
ANGEL_INTERVALS = {
    "1": "ONE_MINUTE",
    "5": "FIVE_MINUTE",
    "15": "FIFTEEN_MINUTE",
    "60": "ONE_HOUR",
    "D": "ONE_DAY",
}


class AngelAPIError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _headers(api_key: str, jwt: str | None = None) -> dict:
    """Angel rejects requests missing the client-info headers, even though the
    values aren't verified — the public IP must match a whitelisted one."""
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": settings.angelone_public_ip,
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": api_key,
    }
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    return h


def _jwt_expiry(token: str) -> float | None:
    """`exp` off Angel's JWT. Unverified decode — Angel validates it server-side;
    we only need to know when to log in again."""
    try:
        seg = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        exp = payload.get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


class AngelClient:
    """One shared session per process. Concurrent callers coalesce on a single login."""

    def __init__(self) -> None:
        self._jwt: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def configured() -> bool:
        return bool(
            settings.angelone_api_key
            and settings.angelone_client_code
            and settings.angelone_pin
            and settings.angelone_totp_secret
        )

    async def _session(self) -> str:
        async with self._lock:
            if self._jwt and time.time() < self._expires_at - SESSION_REFRESH_MARGIN_SECONDS:
                return self._jwt
            if not self.configured():
                raise AngelAPIError("Angel One credentials are not configured")
            totp = pyotp.TOTP(settings.angelone_totp_secret).now()
            async with httpx.AsyncClient(base_url=settings.angelone_base_url, timeout=30) as c:
                r = await c.post(
                    "/rest/auth/angelbroking/user/v1/loginByPassword",
                    headers=_headers(settings.angelone_api_key),
                    json={
                        "clientcode": settings.angelone_client_code,
                        "password": settings.angelone_pin,
                        "totp": totp,
                    },
                )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            jwt = ((body.get("data") or {}).get("jwtToken")) if isinstance(body, dict) else None
            if not jwt:
                raise AngelAPIError(
                    f"Angel login failed: {body.get('message') or body.get('errorcode') or r.status_code}"
                )
            self._jwt = jwt
            # Angel sessions run ~24h; trust the JWT when it says otherwise.
            self._expires_at = _jwt_expiry(jwt) or (time.time() + 12 * 3600)
            logger.info("Angel One session established")
            return jwt

    async def _post(self, path: str, payload: dict) -> dict:
        jwt = await self._session()
        async with httpx.AsyncClient(base_url=settings.angelone_base_url, timeout=30) as c:
            r = await c.post(path, headers=_headers(settings.angelone_api_key, jwt), json=payload)
        try:
            body = r.json()
        except Exception:
            raise AngelAPIError(f"Angel returned non-JSON ({r.status_code})")
        if not body.get("status"):
            raise AngelAPIError(f"Angel error: {body.get('message') or body.get('errorcode')}")
        return body

    async def ltp(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, float]:
        """{"NSE": ["3045"], "NFO": [...]} -> {token: last_price}. Missing/illiquid
        tokens are simply absent rather than zero-filled, so callers can tell the
        difference between "no price" and "price is 0"."""
        out: dict[str, float] = {}
        flat = [(ex, t) for ex, toks in tokens_by_exchange.items() for t in toks]
        for i in range(0, len(flat), QUOTE_BATCH_SIZE):
            chunk = flat[i : i + QUOTE_BATCH_SIZE]
            grouped: dict[str, list[str]] = {}
            for ex, t in chunk:
                grouped.setdefault(ex, []).append(t)
            body = await self._post(
                "/rest/secure/angelbroking/market/v1/quote",
                {"mode": "LTP", "exchangeTokens": grouped},
            )
            for row in (body.get("data") or {}).get("fetched") or []:
                token, price = row.get("symbolToken"), row.get("ltp")
                if token is not None and price is not None:
                    out[str(token)] = float(price)
        return out

    async def full_quote(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, dict]:
        """{"NSE": ["3045"], ...} -> {token: {ltp, open, high, low, close, volume}}.

        FULL mode carries the day OHLC and traded volume that the intraday equity
        setups need; LTP mode (see `ltp`) does not. Missing/illiquid tokens are simply
        absent — a caller can tell "no quote" from a real 0 the same way `ltp` lets it.
        """
        out: dict[str, dict] = {}
        flat = [(ex, t) for ex, toks in tokens_by_exchange.items() for t in toks]
        for i in range(0, len(flat), QUOTE_BATCH_SIZE):
            chunk = flat[i : i + QUOTE_BATCH_SIZE]
            grouped: dict[str, list[str]] = {}
            for ex, t in chunk:
                grouped.setdefault(ex, []).append(t)
            body = await self._post(
                "/rest/secure/angelbroking/market/v1/quote",
                {"mode": "FULL", "exchangeTokens": grouped},
            )
            for row in (body.get("data") or {}).get("fetched") or []:
                token, ltp = row.get("symbolToken"), row.get("ltp")
                if token is None or ltp is None:
                    continue
                out[str(token)] = {
                    "ltp": float(ltp),
                    "open": float(row["open"]) if row.get("open") else None,
                    "high": float(row["high"]) if row.get("high") else None,
                    "low": float(row["low"]) if row.get("low") else None,
                    "close": float(row["close"]) if row.get("close") else None,
                    "volume": float(row.get("tradeVolume") or 0),
                }
        return out

    async def candles(
        self, exchange: str, symbol_token: str, resolution: str, from_dt: str, to_dt: str
    ) -> list[list]:
        """Rows of [timestamp, open, high, low, close, volume]; timestamps are
        ISO strings with IST offset. `from_dt`/`to_dt` are "YYYY-MM-DD HH:MM"."""
        interval = ANGEL_INTERVALS.get(resolution)
        if interval is None:
            raise AngelAPIError(f"Angel has no interval for resolution {resolution}")
        body = await self._post(
            "/rest/secure/angelbroking/historical/v1/getCandleData",
            {
                "exchange": exchange,
                "symboltoken": str(symbol_token),
                "interval": interval,
                "fromdate": from_dt,
                "todate": to_dt,
            },
        )
        return body.get("data") or []


angel_client = AngelClient()
