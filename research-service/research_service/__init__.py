"""TradingAI Trade Intelligence Engine (roadmap Phase 6): ingests ONLY legally-clean
public sources (RSS feeds, official/licensed APIs) and normalizes every item into the
shared `Signal` schema. Never scrapes or redistributes copyrighted trade calls or
premium research — see `rss_feeds.py` for the source list and licensing rationale."""

from research_service.ingest import ingest_all

__all__ = ["ingest_all"]
