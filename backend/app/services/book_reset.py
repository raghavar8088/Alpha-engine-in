"""Reset a PAPER book on the Intraday Stocks page back to its starting capital (2026-10-12).

Behind the "Reset account" button on the Paper Trade (Rs50k / Rs2 lakh - the pattern books) and
Live Intraday (Rs80k / Rs30k / Rs10k / Rs2 lakh / Rs10 lakh) tabs. These books never place an order, so a reset moves no
money anywhere; it deletes the book's paper record so it starts again from its capital.

A RESET IS A FULL RESTART OF THAT ONE BOOK
  Every position (open AND closed), trade, per-strategy score and equity snapshot of the book is
  deleted. Open positions go too: the Live Intraday books carry delivery positions overnight, so
  "wait until flat" would mean never. Nothing of any other book or desk is touched - every query
  is scoped to the one desk's collections and the one book.

NOTHING IS LOST FOR GOOD
  Everything about to be deleted is first written to a backup file on the server's data volume
  (BSON-faithful JSON, restorable exactly), and the reset itself is logged in `book_resets`
  (when, what was deleted, where the backup is). A reset is refused unless the caller sends
  confirm="RESET", so a stray request cannot wipe a book.

AND IT STAYS RESET
  The pattern books COPY the Patterns desk's positions. Without a guard, a reset book would
  re-copy every parent position still open at its old entry price on the very next cycle.
  `reset_at()` gives the book's last reset time, and the mirror refuses parents opened before it.
"""

from __future__ import annotations

import gzip
import logging
import os
import time
from datetime import datetime, timezone

from bson import json_util

from app.core.db import db

logger = logging.getLogger("book_reset")

CONFIRM_WORD = "RESET"
BACKUP_DIR = os.getenv("BOOK_RESET_BACKUP_DIR", os.path.join(os.getenv("INTRADAY_DATA_DIR", "/data/intraday"), "backups", "book-resets"))
resets = db["book_resets"]

DESKS: dict[str, dict] = {
    "pattern-books": {
        "label": "Paper Trade",
        "books": {"50k": "Rs50,000", "2L": "Rs2,00,000"},
        "collections": ["pattern_book_positions", "pattern_book_trades", "pattern_book_scores", "pattern_book_equity"],
    },
    "live-intraday": {
        "label": "Live Intraday",
        "books": {"80k": "Rs80,000", "30k": "Rs30,000", "10k": "Rs10,000",
                  "2L": "Rs2,00,000", "10L": "Rs10,00,000"},
        "collections": ["live_intraday_positions", "live_intraday_trades", "live_intraday_scores", "live_intraday_equity"],
    },
}

_reset_cache: dict[tuple[str, str], tuple[float, datetime | None]] = {}
CACHE_SECONDS = 60


def naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


async def reset_at(desk: str, book: str) -> datetime | None:
    """When this book was last reset (naive UTC, as Mongo returns it), or None. Cached briefly:
    the pattern mirror asks once per parent position per cycle."""
    key = (desk, book)
    hit = _reset_cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    doc = await resets.find_one({"desk": desk, "book": book}, sort=[("at", -1)])
    val = naive_utc(doc["at"]) if doc else None
    _reset_cache[key] = (time.monotonic(), val)
    return val


async def preview(desk: str, book: str) -> dict:
    """What a reset of this book would delete, without deleting anything."""
    spec = _spec(desk, book)
    counts = {c: await db[c].count_documents({"book": book}) for c in spec["collections"]}
    counts["open_positions"] = await db[spec["collections"][0]].count_documents({"book": book, "status": "OPEN"})
    return {"desk": desk, "book": book, "label": f"{spec['label']} - {spec['books'][book]}", "counts": counts}


def _spec(desk: str, book: str) -> dict:
    spec = DESKS.get(desk)
    if spec is None:
        raise ValueError(f"unknown desk {desk!r}")
    if book not in spec["books"]:
        raise ValueError(f"{desk} has no book {book!r} (books: {', '.join(spec['books'])})")
    return spec


async def reset(desk: str, book: str, confirm: str, requested_by: str = "ui") -> dict:
    spec = _spec(desk, book)
    if (confirm or "").strip().upper() != CONFIRM_WORD:
        raise PermissionError(f'type {CONFIRM_WORD} to confirm the reset')
    now = datetime.now(timezone.utc)
    docs = {c: [d async for d in db[c].find({"book": book})] for c in spec["collections"]}
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{desk}_{book}_{now:%Y%m%dT%H%M%SZ}.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json_util.dumps({"desk": desk, "book": book, "taken_at": now, "db": db.name, "docs": docs}))
    deleted = {}
    for c, rows in docs.items():
        ids = [d["_id"] for d in rows]
        deleted[c] = (await db[c].delete_many({"_id": {"$in": ids}})).deleted_count if ids else 0
    open_deleted = sum(1 for d in docs[spec["collections"][0]] if d.get("status") == "OPEN")
    entry = {"desk": desk, "book": book, "at": now, "requested_by": requested_by, "deleted": deleted,
             "open_positions_deleted": open_deleted, "backup": path}
    await resets.insert_one(dict(entry))
    _reset_cache[(desk, book)] = (time.monotonic(), naive_utc(now))
    logger.warning("book reset: %s %s - deleted %s (backup %s)", desk, book, deleted, path)
    entry["at"] = now.isoformat()
    return entry


async def history(desk: str) -> dict:
    """The last reset of each of the desk's books."""
    spec = DESKS.get(desk) or {"books": {}}
    out = {}
    for book in spec["books"]:
        doc = await resets.find_one({"desk": desk, "book": book}, sort=[("at", -1)])
        if doc:
            at = doc["at"]
            out[book] = {"at": (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).isoformat(),
                         "deleted": doc.get("deleted"), "open_positions_deleted": doc.get("open_positions_deleted", 0)}
    return out
