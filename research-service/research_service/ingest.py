"""Fetch each configured RSS feed, normalize every entry, and upsert into the Mongo
`research_signals` collection (deduplicated by a stable id derived from source+link)."""

import hashlib
import os

import feedparser
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from research_service.normalize import normalize_entry
from research_service.rss_feeds import FEEDS

load_dotenv()


def _client():
    return MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))


def _entry_id(source: str, entry: dict) -> str:
    key = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:24]


def fetch_feed(source: str, url: str, timeout: int = 15) -> list[dict]:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    return parsed.entries


def ingest_all(limit_per_feed: int = 30) -> dict:
    db = _client()[os.getenv("MONGO_DB_NAME", "tradingai")]
    collection = db["research_signals"]
    collection.create_index("entry_id", unique=True)

    counts: dict[str, int] = {}
    for source, url in FEEDS.items():
        try:
            entries = fetch_feed(source, url)[:limit_per_feed]
        except Exception as exc:
            counts[source] = f"error: {exc}"
            continue

        new_count = 0
        for entry in entries:
            signal = normalize_entry(entry, source)
            doc = {
                "entry_id": _entry_id(source, entry),
                **signal.model_dump(mode="json"),
                "link": entry.get("link"),
            }
            result = collection.update_one(
                {"entry_id": doc["entry_id"]}, {"$setOnInsert": doc}, upsert=True
            )
            if result.upserted_id is not None:
                new_count += 1
        counts[source] = new_count
    return counts


if __name__ == "__main__":
    result = ingest_all()
    print("research-service ingest:")
    for source, count in result.items():
        print(f"  {source}: {count}")
