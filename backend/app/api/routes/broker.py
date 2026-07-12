from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import broker_credentials_collection, paper_orders_collection
from app.core.encryption import decrypt_secret, encrypt_secret
from app.schemas.broker import (
    BrokerConnectionResponse,
    ConnectBrokerRequest,
    OrderResponse,
    PlaceOrderRequest,
)
from app.services.dhan_client import DhanAPIError, DhanClient, extract_client_id_from_token
from app.services.portfolio_analytics import get_risk_status

router = APIRouter(prefix="/api/broker", tags=["broker"])


async def _get_dhan_client(user_id: str) -> DhanClient:
    creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"})
    if creds is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dhan account not connected")
    return DhanClient(client_id=creds["client_id"], access_token=decrypt_secret(creds["access_token_encrypted"]))


@router.get("/status", response_model=BrokerConnectionResponse | None)
async def broker_status(current_user: dict = Depends(get_current_user)):
    creds = await broker_credentials_collection.find_one({"user_id": str(current_user["_id"]), "broker": "dhan"})
    if creds is None:
        return None
    return BrokerConnectionResponse(
        broker="dhan",
        client_id=creds["client_id"],
        connected_at=creds["connected_at"],
        dhan_name=None,
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

    now = datetime.now(timezone.utc)
    await broker_credentials_collection.find_one_and_update(
        {"user_id": str(current_user["_id"]), "broker": "dhan"},
        {
            "$set": {
                "user_id": str(current_user["_id"]),
                "broker": "dhan",
                "client_id": client_id,
                "access_token_encrypted": encrypt_secret(payload.access_token),
                "connected_at": now,
            }
        },
        upsert=True,
    )
    return BrokerConnectionResponse(
        broker="dhan",
        client_id=client_id,
        connected_at=now,
        dhan_name=profile.get("data", {}).get("dhanClientName") if isinstance(profile.get("data"), dict) else None,
    )


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
            quote = await client.quote_data(payload.exchange_segment, int(payload.security_id))
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
