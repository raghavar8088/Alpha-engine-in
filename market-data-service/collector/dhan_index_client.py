"""Live index quotes from Dhan — replaces the old niftyindices.com feed, which was
found serving data frozen months in the past (its own payload timestamp read
"Jan 16, 2026" while live-tested in July) for every index in it, not just one. Dhan is
already the authoritative price source everywhere else on this platform (backtesting,
options chain, broker positions), so this makes the dashboard consistent with that
instead of a second, unmonitored, free scraped feed.

Covers the 5 indices Dhan actually lists as tradeable instruments (security IDs read
from the `instruments` collection, populated by universe.py) — NIFTY, BANKNIFTY,
FINNIFTY, SENSEX, MIDCPNIFTY. The old feed's other three names (NIFTY IT, NIFTY 100,
NIFTY MIDCAP 100) have no Dhan equivalent and are dropped rather than left silently
stale.
"""

import time

import requests

from credentials import get_dhan_access

DHAN_BASE_URL = "https://api.dhan.co/v2"

# security_id, exchange_segment come from the `instruments` collection (asset_class
# INDEX) — hardcoded here too since this module has no DB access of its own and these
# 5 index security IDs are Dhan platform constants, not something that changes.
DHAN_INDEX_IDS = {
    "NIFTY": ("13", "IDX_I"),
    "BANKNIFTY": ("25", "IDX_I"),
    "FINNIFTY": ("27", "IDX_I"),
    "SENSEX": ("51", "IDX_I"),
    "MIDCPNIFTY": ("442", "IDX_I"),
}


class DhanIndexClient:
    """One batched LTP call per poll cycle covers all 5 indices (Dhan's endpoint
    accepts multiple security IDs per exchange segment) — avoids hitting the API 5x
    as fast as a per-symbol loop would, which was tripping Dhan's rate limit."""

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}
        self._cache_stamp = 0.0

    def _headers(self) -> dict:
        # re-read creds each call so a daily token rotation doesn't need a restart
        client_id, token = get_dhan_access()
        return {"access-token": token, "client-id": client_id,
                "Content-Type": "application/json", "Accept": "application/json"}

    def _refresh(self) -> None:
        # Stamp BEFORE the call, success or failure — otherwise a failed attempt never
        # updates the timestamp, and every remaining symbol in this same poll
        # iteration immediately retries too, turning one rate-limit hit into five.
        self._cache_stamp = time.time()
        by_segment: dict[str, list[int]] = {}
        for sec_id, segment in DHAN_INDEX_IDS.values():
            by_segment.setdefault(segment, []).append(int(sec_id))
        try:
            resp = requests.post(f"{DHAN_BASE_URL}/marketfeed/ltp", headers=self._headers(),
                                 json=by_segment, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            fresh = {}
            for symbol, (sec_id, segment) in DHAN_INDEX_IDS.items():
                row = data.get(segment, {}).get(str(sec_id))
                last = row.get("last_price") if row else None
                if last is not None:
                    fresh[symbol] = {"symbol": symbol, "price": last, "change": None,
                                     "pct_change": None, "volume": None}
            self._cache = fresh
        except Exception as exc:
            print(f"[warn] Dhan index batch quote failed: {exc}", flush=True)
            self._cache = {}

    def get_index_quote(self, symbol: str) -> dict | None:
        if symbol not in DHAN_INDEX_IDS:
            return None
        if time.time() - self._cache_stamp > 3:  # refresh at most once per poll cycle
            self._refresh()
        return self._cache.get(symbol)
