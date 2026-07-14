"""Async Dhan REST client, following the request/response shape of the official
DhanHQ-py SDK (see DhanHQ-py/src/dhanhq/dhan_http.py and _order.py) but rewritten
with httpx to match the rest of this async FastAPI codebase."""

import asyncio
import base64
import json as json_module
import time

import httpx
import pyotp

from app.core.config import settings


class DhanAPIError(Exception):
    def __init__(self, remarks: str):
        self.remarks = remarks
        super().__init__(remarks)


# Dhan enforces a per-account rate limit; a fresh DhanClient is constructed on
# every request (see _get_dhan_client), so pacing has to live at module scope
# to actually throttle the account's *total* call rate, not just one instance's.
# Concurrent features (market-data polling, trading-calls scan, manual-positions
# quote/margin/order calls) all share this one real Dhan account.
_rate_lock = asyncio.Lock()
_last_call_at = 0.0
_MIN_GAP_SECONDS = 0.34  # ~3 req/s — conservative, well under Dhan's limit
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = (0.5, 1.5, 3.0)


async def _paced_request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    global _last_call_at
    for attempt in range(_MAX_RETRIES + 1):
        async with _rate_lock:
            wait = _MIN_GAP_SECONDS - (time.monotonic() - _last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call_at = time.monotonic()
        response = await client.request(method, path, **kwargs)
        if response.status_code != 429 or attempt == _MAX_RETRIES:
            return response
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
    return response  # unreachable, satisfies type checkers


async def totp_login(client_id: str, pin: str, totp_secret: str) -> dict:
    """Programmatic Dhan login via TOTP — generates a fresh access token with no
    browser/2FA prompt. Requires TOTP-based API auth enabled once on the Dhan
    account first (Dhan Web -> DhanHQ Trading APIs -> Setup TOTP), which is a
    one-time manual step outside this app.

    Response shape: {dhanClientId, dhanClientName, dhanClientUcc,
    givenPowerOfAttorney, accessToken, expiryTime}.
    Docs: https://dhanhq.co/docs/v2/authentication/
    """
    code = pyotp.TOTP(totp_secret).now()
    async with httpx.AsyncClient(base_url=settings.dhan_auth_base_url, timeout=30) as client:
        response = await client.post(
            "/app/generateAccessToken",
            params={"dhanClientId": client_id, "pin": pin, "totp": code},
        )
    data = response.json()
    if response.status_code >= 300 or not data.get("accessToken"):
        raise DhanAPIError(data.get("remarks") or data.get("errorMessage") or "TOTP login failed")
    return data


def extract_client_id_from_token(access_token: str) -> str | None:
    """Dhan's access token is a JWT with a 'dhanClientId' claim in its payload.
    Decoding it (no signature check needed - Dhan itself validates the token on
    every request) sidesteps needing the user to type/paste a client ID separately,
    which is error-prone (browser autofill, copy/paste mistakes)."""
    try:
        payload_segment = access_token.split(".")[1]
        padded = payload_segment + "=" * (-len(payload_segment) % 4)
        payload = json_module.loads(base64.urlsafe_b64decode(padded))
        client_id = payload.get("dhanClientId")
        return str(client_id) if client_id else None
    except Exception:
        return None


class DhanClient:
    def __init__(self, client_id: str, access_token: str):
        self.client_id = client_id
        self.access_token = access_token
        self.headers = {
            "access-token": access_token,
            "client-id": client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict | list:
        if json is not None:
            json = {**json, "dhanClientId": self.client_id}
        async with httpx.AsyncClient(base_url=settings.dhan_base_url, timeout=30) as client:
            response = await _paced_request(client, method, path, headers=self.headers, json=json)
        if response.status_code == 429:
            raise DhanAPIError("Dhan rate limit — too many requests, try again in a moment")
        data = response.json()
        # Some endpoints (holdings, positions, order list) return a bare JSON array on
        # success instead of the {"status": ..., "data": ...} envelope others use.
        # Dhan only ever returns error details as an object, so a list is always success.
        if isinstance(data, dict) and (response.status_code >= 300 or data.get("status") == "failure"):
            raise DhanAPIError(data.get("remarks") or data.get("errorMessage") or "Dhan API request failed")
        if not isinstance(data, dict) and response.status_code >= 300:
            raise DhanAPIError("Dhan API request failed")
        return data

    async def user_profile(self) -> dict:
        return await self._request("GET", "/profile")

    async def get_fund_limits(self) -> dict:
        return await self._request("GET", "/fundlimit")

    async def get_holdings(self) -> dict:
        return await self._request("GET", "/holdings")

    async def get_positions(self) -> dict:
        return await self._request("GET", "/positions")

    async def get_order_list(self) -> dict:
        return await self._request("GET", "/orders")

    async def cancel_order(self, order_id: str) -> dict:
        return await self._request("DELETE", f"/orders/{order_id}")

    async def place_order(
        self,
        security_id: str,
        exchange_segment: str,
        transaction_type: str,
        quantity: int,
        order_type: str,
        product_type: str,
        price: float,
        trigger_price: float = 0,
        disclosed_quantity: int = 0,
        validity: str = "DAY",
    ) -> dict:
        payload = {
            "transactionType": transaction_type.upper(),
            "exchangeSegment": exchange_segment.upper(),
            "productType": product_type.upper(),
            "orderType": order_type.upper(),
            "validity": validity.upper(),
            "securityId": security_id,
            "quantity": int(quantity),
            "disclosedQuantity": int(disclosed_quantity),
            "price": float(price),
            "afterMarketOrder": False,
            "triggerPrice": float(trigger_price),
        }
        return await self._request("POST", "/orders", json=payload)

    async def quote_data(self, securities_by_segment: dict[str, list[int]]) -> dict:
        """Batch full quote (same request shape as ltp_data, up to 1000 ids):
        {"NSE_EQ": [11536, ...]} -> {"data": {segment: {security_id: {"last_price",
        "ohlc": {"open","high","low","close"}, "volume", "net_change", ...}}}}.
        Unlike LTP, "ohlc.close" here is the PREVIOUS session's close during
        market hours — the live day-so-far levels are open/high/low + last_price."""
        return await self._request("POST", "/marketfeed/quote", json=dict(securities_by_segment))

    async def ltp_data(self, securities_by_segment: dict[str, list[int]]) -> dict:
        """Batch LTP: {"NSE_EQ": [11536, ...], "NSE_FNO": [...]} ->
        {"data": {segment: {security_id: {"last_price": ...}}}}."""
        return await self._request("POST", "/marketfeed/ltp", json=dict(securities_by_segment))

    async def historical_daily(
        self, security_id: str, exchange_segment: str, instrument_type: str,
        from_date: str, to_date: str,
    ) -> dict:
        """Daily candles as parallel arrays (open/high/low/close/volume/timestamp),
        same endpoint the market-data-service backfill uses."""
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument_type,
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        }
        return await self._request("POST", "/charts/historical", json=payload)

    async def margin_calculator(
        self, security_id: str, exchange_segment: str, transaction_type: str,
        quantity: int, product_type: str, price: float, trigger_price: float = 0,
    ) -> dict:
        """POST /margincalculator — margin/brokerage/leverage Dhan would actually
        apply to this order. product_type "MTF" is what surfaces real per-stock
        margin-trade-funding leverage (no separate "list of MTF stocks" endpoint
        exists; this is the documented way to get it, one instrument at a time).
        Response: {totalMargin, spanMargin, exposureMargin, availableBalance,
        variableMargin, insufficientBalance, brokerage, leverage}."""
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "transactionType": transaction_type.upper(),
            "quantity": int(quantity),
            "productType": product_type.upper(),
            "price": float(price),
            "triggerPrice": float(trigger_price),
        }
        return await self._request("POST", "/margincalculator", json=payload)

    async def option_chain_expiry_list(self, under_security_id: int, under_exchange_segment: str) -> dict:
        payload = {"UnderlyingScrip": under_security_id, "UnderlyingSeg": under_exchange_segment}
        return await self._request("POST", "/optionchain/expirylist", json=payload)

    async def option_chain(self, under_security_id: int, under_exchange_segment: str, expiry: str) -> dict:
        """`expiry` is "YYYY-MM-DD". Response: {"data": {"last_price": <spot>, "oc":
        {"<strike>.000000": {"ce": {...greeks,iv,oi,ltp,bid/ask...}, "pe": {...}}}}}."""
        payload = {"UnderlyingScrip": under_security_id, "UnderlyingSeg": under_exchange_segment, "Expiry": expiry}
        return await self._request("POST", "/optionchain", json=payload)
