from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import broker_credentials_collection, paper_orders_collection
from app.core.encryption import decrypt_secret
from app.schemas.broker import (
    BrokerConnectionResponse,
    ConnectBrokerRequest,
    OrderResponse,
    PlaceOrderRequest,
)
from app.services.dhan_client import DhanAPIError, DhanClient, extract_client_id_from_token
from app.services.dhan_token import health as dhan_token_health
from app.services.dhan_token import refresh_locked, should_refresh, store_token, totp_configured
from app.services.portfolio_analytics import get_risk_status

router = APIRouter(prefix="/api/broker", tags=["broker"])


async def _get_dhan_client(user_id: str) -> DhanClient:
    """The single read path every Dhan-backed feature goes through.

    Refreshing here is a safety net for the background loop in app/main.py, which
    can't notice a token invalidated out of band (Dhan allows one active session
    per account, so any other login silently kills ours). Two things keep that
    safety net from becoming the problem it used to be:

    * the decision is made from the token's real expiry, so a healthy token
      triggers no login at all — previously any request past a wall-clock age
      minted unconditionally, and N concurrent requests minted N times; and
    * the mint itself is serialised across processes by a Redis lock, so even a
      simultaneous burst produces exactly one login.

    A failed refresh is deliberately not fatal: fall through to the stored token,
    which is usually still valid, rather than 500-ing every Dhan feature at once.
    """
    creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"})
    if creds is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dhan account not connected")

    if should_refresh(creds):
        await refresh_locked(user_id)
        creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"}) or creds

    return DhanClient(client_id=creds["client_id"], access_token=decrypt_secret(creds["access_token_encrypted"]))


async def store_dhan_credentials(user_id: str, client_id: str, access_token: str, dhan_name: str | None = None) -> None:
    """Shared upsert used by the manual connect flow and the TOTP auto-refresh
    loop so a refreshed token replaces the stored one without disturbing anything
    else in the credentials document. Delegates to the token manager so the
    token's expiry is recorded the same way no matter who stored it."""
    await store_token(user_id, client_id, access_token, dhan_name)


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
        # Surfacing expiry/remaining here is what makes "is the auto-refresh
        # actually working?" answerable without reading container logs — the
        # question that previously needed log archaeology because only failures
        # were ever visible.
        auto_refresh_enabled=totp_configured(),
        **dhan_token_health(creds),
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
    """Manually trigger a TOTP-based token refresh — useful for testing the TOTP
    setup, or forcing a new token after one was invalidated out of band.

    Goes through the same cross-process lock as every other login, so pressing it
    repeatedly (or while the background loop happens to be minting) produces one
    login, not several. `minted` distinguishes "this call did the work" from
    "someone else was already minting and we took their result"; both leave a
    usable token behind.
    """
    if not totp_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not configured",
        )
    user_id = str(current_user["_id"])
    minted = await refresh_locked(user_id)
    creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"})
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TOTP refresh did not produce a usable token — check DHAN_* credentials and Dhan's auth status.",
        )
    return {"refreshed": True, "minted": minted, "client_id": creds["client_id"], **dhan_token_health(creds)}


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
