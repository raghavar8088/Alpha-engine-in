"""Async Dhan REST client, following the request/response shape of the official
DhanHQ-py SDK (see DhanHQ-py/src/dhanhq/dhan_http.py and _order.py) but rewritten
with httpx to match the rest of this async FastAPI codebase."""

import base64
import json as json_module

import httpx

from app.core.config import settings


class DhanAPIError(Exception):
    def __init__(self, remarks: str):
        self.remarks = remarks
        super().__init__(remarks)


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
            response = await client.request(method, path, headers=self.headers, json=json)
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

    async def quote_data(self, exchange_segment: str, security_id: int) -> dict:
        payload = {exchange_segment: [security_id]}
        return await self._request("POST", "/marketfeed/quote", json=payload)

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

    async def option_chain_expiry_list(self, under_security_id: int, under_exchange_segment: str) -> dict:
        payload = {"UnderlyingScrip": under_security_id, "UnderlyingSeg": under_exchange_segment}
        return await self._request("POST", "/optionchain/expirylist", json=payload)

    async def option_chain(self, under_security_id: int, under_exchange_segment: str, expiry: str) -> dict:
        """`expiry` is "YYYY-MM-DD". Response: {"data": {"last_price": <spot>, "oc":
        {"<strike>.000000": {"ce": {...greeks,iv,oi,ltp,bid/ask...}, "pe": {...}}}}}."""
        payload = {"UnderlyingScrip": under_security_id, "UnderlyingSeg": under_exchange_segment, "Expiry": expiry}
        return await self._request("POST", "/optionchain", json=payload)
