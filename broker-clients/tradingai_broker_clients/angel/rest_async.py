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
    HOLDING_PATH,
    MARGIN_PATH,
    LOGIN_PATH,
    ORDER_PATH,
    ORDERBOOK_PATH,
    POSITION_PATH,
    PROFILE_PATH,
    QUOTE_PATH,
    RMS_PATH,
    TRADEBOOK_PATH,
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
    """Async Angel One client: quotes, candles, and (with a TRADING API key) real orders."""

    def __init__(self, creds: AngelCredentials | None = None) -> None:
        self.creds = creds or AngelCredentials.from_env()
        self._jwt: str | None = None
        self._feed_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()
        # One pooled connection for READS (quotes, candles), see _read_post.
        self._http: httpx.AsyncClient | None = None
        self._http_loop: asyncio.AbstractEventLoop | None = None

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

    # -- reads over one kept-alive connection ---------------------------------------
    # `_post` opens a new connection per call: a fresh TCP + TLS handshake to Angel every
    # time. Measured from the production box on 2026-10-07, that is 82 ms median for a
    # one-token quote against 24 ms over a reused connection - and quotes and candles are
    # most of what every desk in the backend sends. So READS go through one pooled client.
    #
    # Orders deliberately do NOT. `place_order` still uses `_post`: a fresh connection and no
    # retry. A read can be retried safely when a pooled connection turns out to be dead; an
    # order cannot, because a request that failed on the way back may already have reached
    # Angel, and retrying it would place a second real order.

    def _reader(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        # A client is bound to the loop that created it. A different loop (a script calling
        # asyncio.run twice, a test) gets its own rather than a client it cannot drive.
        if self._http is None or self._http.is_closed or self._http_loop is not loop:
            self._http = httpx.AsyncClient(
                base_url=self.creds.base_url, timeout=30,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5,
                                    keepalive_expiry=60))
            self._http_loop = loop
        return self._http

    async def _read_post(self, path: str, payload: dict) -> dict:
        jwt = await self._session()
        headers = client_headers(self.creds.api_key, self.creds.public_ip, jwt)
        try:
            r = await self._reader().post(path, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise                     # a slow Angel is not a dead socket; do not double the wait
        except httpx.TransportError as exc:
            # The pooled connection was closed under us (idle expiry, a network blip). A
            # read is idempotent, so start a fresh pool and try exactly once more.
            logger.info("Angel read on a pooled connection failed (%s) - retrying fresh",
                        type(exc).__name__)
            self._http = None
            r = await self._reader().post(path, headers=headers, json=payload)
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
            body = await self._read_post(QUOTE_PATH, {"mode": "LTP", "exchangeTokens": grouped})
            out.update(parse_ltp(body))
        return out

    async def full_quote(self, tokens_by_exchange: dict[str, list[str]]) -> dict[str, dict]:
        """{"NSE": ["3045"], ...} -> {token: {ltp, open, high, low, close, volume}}."""
        out: dict[str, dict] = {}
        for grouped in batches(tokens_by_exchange):
            body = await self._read_post(QUOTE_PATH, {"mode": "FULL", "exchangeTokens": grouped})
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
        body = await self._read_post(
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

    async def _get(self, path: str) -> dict:
        jwt = await self._session()
        async with httpx.AsyncClient(base_url=self.creds.base_url, timeout=30) as c:
            r = await c.get(path, headers=client_headers(self.creds.api_key, self.creds.public_ip, jwt))
        try:
            body = r.json()
        except Exception:
            raise AngelAPIError(f"Angel returned non-JSON ({r.status_code})")
        if not body.get("status"):
            raise AngelAPIError(f"Angel error: {body.get('message') or body.get('errorcode')}")
        return body

    async def funds(self) -> dict:
        """RMS limits — the real account money: availablecash, net, utiliseddebits (margin
        in use), collateral, m2mrealized / m2munrealized. Values come back as strings."""
        return (await self._get(RMS_PATH)).get("data") or {}

    async def profile(self) -> dict:
        """Account identity — clientcode, name, and the exchanges/products enabled. Useful
        for confirming WHICH account the desk is about to trade with."""
        return (await self._get(PROFILE_PATH)).get("data") or {}

    async def broker_positions(self) -> list[dict]:
        """Today's positions as ANGEL sees them — the broker's own truth, independent of
        whatever our ledger thinks."""
        return (await self._get(POSITION_PATH)).get("data") or []

    async def holdings(self) -> list[dict]:
        """Delivery holdings (CNC), not intraday positions."""
        return (await self._get(HOLDING_PATH)).get("data") or []

    async def trade_book(self) -> list[dict]:
        """Today's EXECUTED fills, one row per trade.

        This is the only place the real fill price exists. A market order's fill is not
        the price the signal was computed at — between the two sit the spread and whatever
        moved while the order travelled — so any desk that records the signal price is
        reporting a number the broker never charged."""
        return (await self._get(TRADEBOOK_PATH)).get("data") or []

    async def order_book(self) -> list[dict]:
        """Today's orders with their status (complete / rejected / pending)."""
        return (await self._get(ORDERBOOK_PATH)).get("data") or []

    async def margin_batch(self, positions: list[dict]) -> float:
        """SPAN + exposure for a WHOLE basket, as the broker itself would charge it.

        Returns `totalMarginRequired` in rupees. Each position needs every one of:

            {"exchange", "qty", "price", "productType", "token", "tradeType", "orderType"}

        `orderType` is not optional even though the docs imply it — omitting it is
        rejected with "Order type is required", which costs a round trip to discover.
        `qty` is the broker's ORDER quantity (its `lotsize` per lot), which on MCX is NOT
        the value multiplier: GOLD trades in lots of 1 while a lot is worth 100x the
        quoted 10-gram price. Sending the value multiplier asks about a position 100x the
        intended size.

        Verified against the Angel One app on 2026-10-09: a 1-lot CRUDEOILM 8750 short
        straddle returned Rs 60,499 against the app's own Rs 60,603.
        """
        body = await self._read_post(MARGIN_PATH, {"positions": positions})
        data = body.get("data") or {}
        return float(data.get("totalMarginRequired") or 0.0)

    async def place_order(
        self,
        *,
        tradingsymbol: str,
        symboltoken: str,
        transactiontype: str,
        exchange: str,
        quantity: int,
        ordertype: str = "MARKET",
        producttype: str = "INTRADAY",
        duration: str = "DAY",
        price: float = 0,
        variety: str = "NORMAL",
    ) -> dict:
        """Place a REAL order via SmartAPI placeOrder.

        NOTE: this only works when the logged-in app is a TRADING API key — a Market-Data
        or Historical-only key is rejected by Angel here. Returns Angel's response body; the
        broker order id is at body["data"]["orderid"]. A rejected order raises AngelAPIError
        (surfaced by _post when the response's `status` is false)."""
        payload = {
            "variety": variety,
            "tradingsymbol": tradingsymbol,
            "symboltoken": str(symboltoken),
            "transactiontype": transactiontype.upper(),
            "exchange": exchange.upper(),
            "ordertype": ordertype.upper(),
            "producttype": producttype.upper(),
            "duration": duration.upper(),
            "price": str(price),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(int(quantity)),
        }
        return await self._post(ORDER_PATH, payload)
