from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import broker_credentials_collection, paper_orders_collection
from app.core.encryption import decrypt_secret, encrypt_secret
from app.schemas.broker import (
    BrokerConnectionResponse,
    ConnectBrokerRequest,
    OrderResponse,
    PlaceOrderRequest,
)
from app.services.dhan_client import DhanAPIError, DhanClient, extract_client_id_from_token, totp_login
from app.services.portfolio_analytics import get_risk_status

router = APIRouter(prefix="/api/broker", tags=["broker"])

# The 20h background refresh loop (see app/main.py) is only a baseline — it has
# no way to notice if something else invalidates the token in between cycles
# (Dhan allows one active session token per account, so anything else logging
# in with the same TOTP credentials silently kills whatever token we're
# holding). Proactively refreshing here whenever the stored token is older than
# this bounds the real-world staleness window instead of waiting up to 20h for
# a human to notice "Invalid Token" and hit the manual refresh endpoint.
DHAN_TOKEN_MAX_AGE_SECONDS = 3 * 60 * 60  # 3 hours


async def _get_dhan_client(user_id: str) -> DhanClient:
    creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"})
    if creds is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dhan account not connected")

    age_seconds = (datetime.now(timezone.utc) - creds["connected_at"]).total_seconds()
    can_auto_refresh = settings.dhan_client_id and settings.dhan_pin and settings.dhan_totp_secret
    if age_seconds > DHAN_TOKEN_MAX_AGE_SECONDS and can_auto_refresh:
        try:
            data = await totp_login(settings.dhan_client_id, settings.dhan_pin, settings.dhan_totp_secret)
            await store_dhan_credentials(
                user_id, str(data["dhanClientId"]), data["accessToken"], data.get("dhanClientName"),
            )
            return DhanClient(client_id=str(data["dhanClientId"]), access_token=data["accessToken"])
        except (DhanAPIError, Exception):
            pass  # Dhan may be mid-cooldown from a very recent login elsewhere — fall through
            # to the possibly-stale stored token rather than hard-failing the whole request here.

    return DhanClient(client_id=creds["client_id"], access_token=decrypt_secret(creds["access_token_encrypted"]))


async def store_dhan_credentials(user_id: str, client_id: str, access_token: str, dhan_name: str | None = None) -> None:
    """Shared upsert used by both the manual connect flow and the TOTP auto-refresh
    loop so a refreshed token replaces the stored one without disturbing anything
    else in the credentials document."""
    await broker_credentials_collection.find_one_and_update(
        {"user_id": user_id, "broker": "dhan"},
        {
            "$set": {
                "user_id": user_id,
                "broker": "dhan",
                "client_id": client_id,
                "access_token_encrypted": encrypt_secret(access_token),
                "connected_at": datetime.now(timezone.utc),
                **({"dhan_name": dhan_name} if dhan_name else {}),
            }
        },
        upsert=True,
    )


@router.get("/status", response_model=BrokerConnectionResponse | None)
async def broker_status(current_user: dict = Depends(get_current_user)):
    creds = await broker_credentials_collection.find_one({"user_id": str(current_user["_id"]), "broker": "dhan"})
    if creds is None:
        return None
    return BrokerConnectionResponse(
        broker="dhan",
        client_id=creds["client_id"],
        connected_at=creds["connected_at"],
        dhan_name=creds.get("dhan_name"),
    )


@router.post("/connect", response_model=BrokerConnectionResponse)
async def connect_broker(payload: ConnectBrokerRequest, current_user: dict = Depends(get_current_user)):
    client_id = extract_client_id_from_token(payload.access_token)
    if client_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read a client ID from that access token")
    if payload.client_id and payload.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client ID entered ({payload.client_id}) doesn't match the one embedded in the access token ({client_id})",
        )

    client = DhanClient(client_id=client_id, access_token=payload.access_token)
    try:
        profile = await client.user_profile()
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Dhan validation failed: {exc.remarks}")

    dhan_name = profile.get("data", {}).get("dhanClientName") if isinstance(profile.get("data"), dict) else None
    await store_dhan_credentials(str(current_user["_id"]), client_id, payload.access_token, dhan_name)
    return BrokerConnectionResponse(
        broker="dhan",
        client_id=client_id,
        connected_at=datetime.now(timezone.utc),
        dhan_name=dhan_name,
    )


@router.post("/refresh-token")
async def refresh_dhan_token(current_user: dict = Depends(get_current_user)):
    """Manually trigger a TOTP-based token refresh (the same thing the background
    loop in app/main.py does automatically every ~20h) — useful for testing the
    TOTP setup without waiting for the scheduled refresh."""
    if not (settings.dhan_client_id and settings.dhan_pin and settings.dhan_totp_secret):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not configured",
        )
    try:
        data = await totp_login(settings.dhan_client_id, settings.dhan_pin, settings.dhan_totp_secret)
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"TOTP login failed: {exc.remarks}")

    await store_dhan_credentials(
        str(current_user["_id"]), str(data["dhanClientId"]), data["accessToken"], data.get("dhanClientName"),
    )
    return {"refreshed": True, "client_id": data["dhanClientId"], "expiry_time": data.get("expiryTime")}


@router.get("/holdings")
async def get_holdings(current_user: dict = Depends(get_current_user)):
    client = await _get_dhan_client(str(current_user["_id"]))
    try:
        return await client.get_holdings()
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.remarks)


@router.get("/positions")
async def get_positions(current_user: dict = Depends(get_current_user)):
    client = await _get_dhan_client(str(current_user["_id"]))
    try:
        return await client.get_positions()
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.remarks)


@router.get("/funds")
async def get_funds(current_user: dict = Depends(get_current_user)):
    client = await _get_dhan_client(str(current_user["_id"]))
    try:
        return await client.get_fund_limits()
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.remarks)


@router.post("/orders", response_model=OrderResponse)
async def place_order(payload: PlaceOrderRequest, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    now = datetime.now(timezone.utc)

    client = await _get_dhan_client(user_id)
    risk = await get_risk_status(client)
    if risk["kill_switch_active"]:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Risk kill-switch active ({', '.join(risk['kill_switch_reasons'])}) — order placement halted",
        )

    if payload.paper_trading:
        try:
            quote = await client.quote_data({payload.exchange_segment: [int(payload.security_id)]})
        except DhanAPIError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.remarks)

        fill_price = _extract_ltp(quote) or payload.price
        order_id = f"PAPER-{uuid4().hex[:12]}"
        doc = {
            "order_id": order_id,
            "user_id": user_id,
            "status": "FILLED",
            "security_id": payload.security_id,
            "exchange_segment": payload.exchange_segment,
            "transaction_type": payload.transaction_type,
            "quantity": payload.quantity,
            "order_type": payload.order_type,
            "product_type": payload.product_type,
            "price": fill_price,
            "paper_trading": True,
            "created_at": now,
        }
        await paper_orders_collection.insert_one(doc)
        # insert_one mutates doc in place, adding a non-JSON-serializable ObjectId _id.
        doc.pop("_id", None)
        return OrderResponse(**doc)

    try:
        result = await client.place_order(
            security_id=payload.security_id,
            exchange_segment=payload.exchange_segment,
            transaction_type=payload.transaction_type,
            quantity=payload.quantity,
            order_type=payload.order_type,
            product_type=payload.product_type,
            price=payload.price,
            trigger_price=payload.trigger_price,
        )
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.remarks)

    return OrderResponse(
        order_id=result.get("data", {}).get("orderId", ""),
        status=result.get("data", {}).get("orderStatus", "PENDING"),
        security_id=payload.security_id,
        exchange_segment=payload.exchange_segment,
        transaction_type=payload.transaction_type,
        quantity=payload.quantity,
        order_type=payload.order_type,
        product_type=payload.product_type,
        price=payload.price,
        paper_trading=False,
        created_at=now,
    )


@router.get("/orders")
async def list_orders(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    paper_cursor = paper_orders_collection.find({"user_id": user_id}).sort("created_at", -1)
    paper_orders = [{**doc, "_id": str(doc["_id"])} async for doc in paper_cursor]

    live_orders: list = []
    creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"})
    if creds is not None:
        client = DhanClient(client_id=creds["client_id"], access_token=decrypt_secret(creds["access_token_encrypted"]))
        try:
            result = await client.get_order_list()
            if isinstance(result, list):
                live_orders = result
            elif isinstance(result.get("data"), list):
                live_orders = result["data"]
        except DhanAPIError:
            pass

    return {"paper_orders": paper_orders, "live_orders": live_orders}


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str, current_user: dict = Depends(get_current_user)):
    client = await _get_dhan_client(str(current_user["_id"]))
    try:
        return await client.cancel_order(order_id)
    except DhanAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.remarks)


def _extract_ltp(quote: dict) -> float | None:
    data = quote.get("data", {})
    for segment_data in data.values() if isinstance(data, dict) else []:
        for security_data in segment_data.values() if isinstance(segment_data, dict) else []:
            ltp = security_data.get("last_price")
            if ltp is not None:
                return float(ltp)
    return None
