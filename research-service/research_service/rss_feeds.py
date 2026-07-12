"""Legal source list — RSS feeds these publishers themselves syndicate for reuse (that
is the entire purpose of publishing an RSS feed, unlike scraping a paywalled article
body). Verified reachable directly (not from behind a login) as of this build.

Explicitly NOT included: any source's premium research, subscriber-only calls, or
paywalled article content — this ingests headlines/summaries only, which is what the
feeds themselves publish for syndication."""

FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol Business": "https://www.moneycontrol.com/rss/business.xml",
    "LiveMint Markets": "https://www.livemint.com/rss/markets",
}

# NSE's corporate-announcements/economic-calendar JSON endpoints sit behind the same
# Akamai WAF that blocked equity quotes in Phase 1 (confirmed: non-browser clients get
# 403). FII/DII activity, bulk/block deals, and corporate actions are real roadmap
# targets but need either a licensed data vendor or a browser-automation approach this
# service deliberately does not take (scope: officially-syndicated feeds only) — left
# as a documented gap, not silently faked.
