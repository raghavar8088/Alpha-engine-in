"""Telegram Signal Copier — read-only view over signals captured by the standalone
`telegram-signal-service` daemon (which owns all writes: it listens to the channel,
parses ideas via Groq, and optionally opens paper positions through
/api/manual-positions). This router just lets the frontend list what came in,
what happened to it, and view the original screenshot for image-based signals.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.core.db import telegram_signals_collection

router = APIRouter(prefix="/api/telegram-signals", tags=["telegram-signals"])

# Shared with telegram-signal-service/pipeline.py's IMAGES_DIR default — both
# resolve to the same repo-root sibling directory when run locally.
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", Path(__file__).resolve().parents[4] / "telegram_signal_images"))


def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    if doc.get("received_at") is not None:
        doc["received_at"] = doc["received_at"].isoformat()
    return doc


@router.get("")
async def list_signals(
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    cursor = telegram_signals_collection.find().sort("received_at", -1).limit(limit)
    return {"signals": [_serialize(d) async for d in cursor]}


@router.get("/image/{message_id}")
async def get_image(message_id: int, current_user: dict = Depends(get_current_user)):
    path = IMAGES_DIR / f"{message_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No image stored for this message")
    return FileResponse(path, media_type="image/jpeg")
