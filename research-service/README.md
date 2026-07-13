# research-service

Trade Intelligence Engine (roadmap Phase 6): ingests **only legally-clean sources** and
normalizes every item into the shared `Signal` schema
(`{symbol, timeframe, signal, confidence, stop_loss, target, source, timestamp,
reasoning}`).

## Sources (verified reachable)

RSS feeds these publishers themselves syndicate for reuse — that's the point of
publishing one, unlike scraping a paywalled article body:

- Economic Times Markets
- Moneycontrol Business
- LiveMint Markets

(Business Standard's markets RSS returned 403 during this build and was dropped —
`rss_feeds.py` documents this.)

**Deliberately not scraped**: NSE's corporate-announcements/FII-DII/bulk-deals JSON
endpoints sit behind the same Akamai WAF that blocked equity quotes in Phase 1 (403 for
non-browser clients). That's a real gap against the roadmap's full source list
(exchange announcements, FII/DII stats, insider disclosures, bulk/block deals) — it
needs either a licensed data vendor or browser automation this service deliberately
does not do. Documented here rather than silently faked with placeholder data.

## What normalization does (and doesn't do)

`normalize.py` mechanically detects known symbols/indices in each headline+summary
(keyword match against `tradingai_shared.sectors.SECTOR_MAP`) and stores a **neutral
placeholder** signal (`HOLD`, confidence 0.5) — it does not claim a directional call it
didn't derive. Sentiment/direction comes from `ai-service`'s `summarize_news` module,
which reads a batch of these and produces bullish/bearish/neutral scoring via Claude.

Verified live: 75 articles ingested across the 3 feeds in one run; 12 correctly matched
a specific symbol (RELIANCE, DABUR, PERSISTENT, NIFTY, ...), the rest fell back to
`MARKET` (general news, no single-stock reference) — no false directional claims either
way.

## Usage

```
pip install -r requirements.txt
python research_service/ingest.py
```

Writes to the Mongo `research_signals` collection (deduplicated by a hash of
source+link, safe to re-run on a schedule — Phase 8's `scheduler` is the natural home
for periodic re-ingestion).
