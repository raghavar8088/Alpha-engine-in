# Phase 1 uses NSE's public live-indices feed only. It has no bot-protection and needs
# no session/cookies, unlike nseindia.com's equity quote-api which sits behind an Akamai
# WAF that blocks non-browser clients (confirmed: even curl_cffi Chrome-impersonation gets
# 403). Equity-level quotes will come from authenticated broker APIs (Dhan/Angel One) in
# Phase 2, so no more scraping effort goes in here for Phase 1.
#
# SENSEX is a BSE index and isn't on this NSE feed; adding it needs a BSE data source.
INDEX_SYMBOLS = ["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY 100", "NIFTY MIDCAP 100"]

EQUITY_SYMBOLS: list[str] = []

WATCHLIST = INDEX_SYMBOLS + EQUITY_SYMBOLS
