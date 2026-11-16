"""Refresh the NSE stock-option contract list (Angel's scrip master -> `instruments`, asset_class EQUITY_OPTION).

WHY THIS EXISTS (16 Nov 2026). The list was loaded once, on 9 Aug 2026, by the manual route
POST /api/stock-desk/refresh-contracts, and never again: it held the Aug, Sep and Oct expiries only. After the
27 Oct expiry no stock had a listed contract, so the Stock Pre-Live desks stopped trading, and with them every
account that copies them (the Top 10 Paper Trade books, the Strategy Factory · 546 tab: "no listed contract").

WHY OUTSIDE THE BACKEND. stock_options.refresh_stock_options parses the whole scrip master (~150k rows): it peaked at
300 MB on 16 Nov 2026, and the backend runs at ~650 of its 800 MB cap. So the box runs this file in a throwaway
container from the production image (scripts/refresh_stock_options_cron.sh; meant to run every weekday before the
open from /etc/cron.d/stockopt-refresh once the owner approves). Same code as the route; idempotent.

Exit code 1 if, after the refresh, no stock has a contract that has not expired - the desks could not trade.
"""

from __future__ import annotations

import asyncio
import resource
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import instruments_collection        # noqa: E402
from app.services.stock_options import refresh_stock_options  # noqa: E402


async def main() -> int:
    t = time.time()
    today = date.today().isoformat()
    # Expired contracts go FIRST. Angel reuses a token for a later expiry, and `instruments` has a unique
    # (security_id, exchange_segment) index, so while an expired contract still holds ANGEL<token> the new one is
    # refused as a duplicate (7,998 were, on 16 Nov 2026) until the next run - refresh_stock_options purges only
    # after its upserts.
    purged = (await instruments_collection.delete_many(
        {"asset_class": "EQUITY_OPTION", "expiry": {"$lt": today}})).deleted_count
    res = await refresh_stock_options()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"purged first: {purged} expired; refresh: {res} in {time.time() - t:.0f}s, peak {peak:.0f} MB", flush=True)
    if res.get("duplicate_skipped"):
        print(f"WARNING: {res['duplicate_skipped']} contracts refused as duplicates", flush=True)
    live = 0
    async for g in instruments_collection.aggregate([
            {"$match": {"asset_class": "EQUITY_OPTION", "expiry": {"$gte": today}}},
            {"$group": {"_id": "$expiry", "n": {"$sum": 1}, "u": {"$addToSet": "$underlying_symbol"}}},
            {"$sort": {"_id": 1}}]):
        live += g["n"]
        print(f"expiry {g['_id']}: {g['n']} contracts, {len(g['u'])} stocks", flush=True)
    if not live:
        print("NO LIVE STOCK-OPTION CONTRACT: the stock desks cannot trade", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
