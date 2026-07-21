"""Persistence for the Chart module's workspace (Phase 7): drawings, saved
layouts, and alerts.

All three are scoped by `user_id` even though this app currently runs as a
single auto-provisioned local user (see `api/deps.get_current_user`) — storing
the owner now means multi-user later is a query change, not a migration.

**On alert delivery.** The plan calls for alerts to go out through the existing
notification-service. That service is a stub — `notification-service/README.md`
reads "Not yet implemented" — and the only Telegram integration in this repo is
*inbound* (telegram-signal-service consumes a channel; it cannot send). Rather
than quietly stand up a new outbound channel, alerts here are evaluated and
recorded server-side and surfaced in-app; `triggered_at`/`triggered_price` are
stored so a real delivery channel can be attached later without changing this
schema or re-evaluating history.
"""

from datetime import datetime, timezone
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING

from app.core.db import (
    chart_alerts_collection,
    chart_drawings_collection,
    chart_layouts_collection,
)

# Anything else is rejected rather than stored — an unknown shape would be dead
# weight the frontend can't render.
DRAWING_KINDS = {"trendline", "horizontal", "rectangle", "text", "fibonacci"}

ALERT_CONDITIONS = {"crosses_above", "crosses_below"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def ensure_indexes() -> None:
    await chart_drawings_collection.create_index(
        [("user_id", ASCENDING), ("security_id", ASCENDING), ("exchange_segment", ASCENDING)],
        name="chart_drawings_owner_instrument",
    )
    await chart_layouts_collection.create_index(
        [("user_id", ASCENDING), ("name", ASCENDING)], unique=True, name="chart_layouts_owner_name",
    )
    await chart_alerts_collection.create_index(
        [("user_id", ASCENDING), ("status", ASCENDING)], name="chart_alerts_owner_status",
    )


# --- drawings --------------------------------------------------------------

def _drawing_out(doc: dict) -> dict:
    return {
        "drawing_id": doc["drawing_id"],
        "kind": doc["kind"],
        "points": doc.get("points", []),
        "text": doc.get("text"),
        "color": doc.get("color"),
        "created_at": _iso(doc.get("created_at")),
    }


async def list_drawings(user_id: str, security_id: str, exchange_segment: str) -> list[dict]:
    cursor = chart_drawings_collection.find(
        {"user_id": user_id, "security_id": security_id, "exchange_segment": exchange_segment}
    ).sort("created_at", ASCENDING)
    return [_drawing_out(doc) async for doc in cursor]


async def save_drawing(
    user_id: str, security_id: str, exchange_segment: str, payload: dict,
) -> dict:
    kind = payload.get("kind")
    if kind not in DRAWING_KINDS:
        raise ValueError(f"kind must be one of {sorted(DRAWING_KINDS)}")
    points = payload.get("points") or []
    if not isinstance(points, list) or not points:
        raise ValueError("points must be a non-empty list of {time, price}")
    for point in points:
        if not isinstance(point, dict) or "time" not in point or "price" not in point:
            raise ValueError("each point needs a time and a price")

    doc = {
        "drawing_id": uuid4().hex[:12],
        "user_id": user_id,
        "security_id": security_id,
        "exchange_segment": exchange_segment,
        "kind": kind,
        "points": [{"time": int(p["time"]), "price": float(p["price"])} for p in points],
        "text": payload.get("text"),
        "color": payload.get("color"),
        "created_at": _now(),
    }
    await chart_drawings_collection.insert_one(doc)
    return _drawing_out(doc)


async def delete_drawing(user_id: str, drawing_id: str) -> bool:
    result = await chart_drawings_collection.delete_one({"user_id": user_id, "drawing_id": drawing_id})
    return result.deleted_count > 0


# --- layouts ---------------------------------------------------------------

def _layout_out(doc: dict) -> dict:
    return {
        "layout_id": doc["layout_id"],
        "name": doc["name"],
        "resolution": doc.get("resolution"),
        "indicators": doc.get("indicators") or {},
        "overlays": doc.get("overlays") or {},
        "updated_at": _iso(doc.get("updated_at")),
    }


async def list_layouts(user_id: str) -> list[dict]:
    cursor = chart_layouts_collection.find({"user_id": user_id}).sort("updated_at", DESCENDING)
    return [_layout_out(doc) async for doc in cursor]


async def save_layout(user_id: str, payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    # Upsert by name so re-saving an existing layout updates it rather than
    # accumulating duplicates the user then has to prune by hand.
    existing = await chart_layouts_collection.find_one({"user_id": user_id, "name": name})
    doc = {
        "user_id": user_id,
        "name": name,
        "resolution": payload.get("resolution"),
        "indicators": payload.get("indicators") or {},
        "overlays": payload.get("overlays") or {},
        "updated_at": _now(),
        "layout_id": existing["layout_id"] if existing else uuid4().hex[:12],
    }
    await chart_layouts_collection.update_one(
        {"user_id": user_id, "name": name}, {"$set": doc}, upsert=True,
    )
    return _layout_out(doc)


async def delete_layout(user_id: str, layout_id: str) -> bool:
    result = await chart_layouts_collection.delete_one({"user_id": user_id, "layout_id": layout_id})
    return result.deleted_count > 0


# --- alerts ----------------------------------------------------------------

def _alert_out(doc: dict) -> dict:
    return {
        "alert_id": doc["alert_id"],
        "symbol": doc.get("symbol"),
        "display_name": doc.get("display_name"),
        "security_id": doc.get("security_id"),
        "exchange_segment": doc.get("exchange_segment"),
        "condition": doc.get("condition"),
        "price": doc.get("price"),
        "note": doc.get("note"),
        "status": doc.get("status"),
        "created_at": _iso(doc.get("created_at")),
        "triggered_at": _iso(doc.get("triggered_at")),
        "triggered_price": doc.get("triggered_price"),
        "delivery": doc.get("delivery"),
    }


async def list_alerts(user_id: str, security_id: str | None = None) -> list[dict]:
    query: dict = {"user_id": user_id}
    if security_id:
        query["security_id"] = security_id
    cursor = chart_alerts_collection.find(query).sort("created_at", DESCENDING).limit(100)
    return [_alert_out(doc) async for doc in cursor]


async def create_alert(user_id: str, payload: dict) -> dict:
    condition = payload.get("condition")
    if condition not in ALERT_CONDITIONS:
        raise ValueError(f"condition must be one of {sorted(ALERT_CONDITIONS)}")
    try:
        price = float(payload["price"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("price must be a number")
    if not payload.get("security_id") or not payload.get("exchange_segment"):
        raise ValueError("security_id and exchange_segment are required")

    doc = {
        "alert_id": uuid4().hex[:12],
        "user_id": user_id,
        "symbol": payload.get("symbol"),
        "display_name": payload.get("display_name") or payload.get("symbol"),
        "security_id": str(payload["security_id"]),
        "exchange_segment": payload["exchange_segment"],
        "condition": condition,
        "price": price,
        "note": payload.get("note"),
        "status": "ACTIVE",
        "created_at": _now(),
        "triggered_at": None,
        "triggered_price": None,
        # Honest about where this can currently go. notification-service is a
        # stub, so nothing leaves the app until it exists.
        "delivery": "in_app",
    }
    await chart_alerts_collection.insert_one(doc)
    return _alert_out(doc)


async def delete_alert(user_id: str, alert_id: str) -> bool:
    result = await chart_alerts_collection.delete_one({"user_id": user_id, "alert_id": alert_id})
    return result.deleted_count > 0


async def evaluate_alerts(
    user_id: str, security_id: str, exchange_segment: str, last_price: float, previous_price: float | None,
) -> list[dict]:
    """Fire any active alert this price move crossed.

    A *cross* needs both sides of the move, so the previous price is required —
    without it an alert set below a price that has been sitting there all day
    would fire the moment it was created. On the first tick after load there is
    no previous price and nothing fires, which is the correct conservative
    behaviour.
    """
    if previous_price is None:
        return []

    cursor = chart_alerts_collection.find({
        "user_id": user_id, "security_id": security_id,
        "exchange_segment": exchange_segment, "status": "ACTIVE",
    })
    fired = []
    async for doc in cursor:
        level = doc["price"]
        crossed_up = previous_price <= level < last_price
        crossed_down = previous_price >= level > last_price
        if (doc["condition"] == "crosses_above" and crossed_up) or (
            doc["condition"] == "crosses_below" and crossed_down
        ):
            await chart_alerts_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "TRIGGERED", "triggered_at": _now(), "triggered_price": last_price}},
            )
            fired.append(_alert_out({
                **doc, "status": "TRIGGERED", "triggered_at": _now(), "triggered_price": last_price,
            }))
    return fired
