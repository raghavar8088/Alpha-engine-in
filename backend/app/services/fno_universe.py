"""The F&O stock universe and its day-change, shared by the desks that need it.

Extracted from the retired Buy Low Options desk, which originated it: a '% down on
the day' or '% up on the day' rule needs every optionable stock's last price against
the PREVIOUS session's close, batched to Angel's 50-token quote cap and paced.
"""

import asyncio
import logging

from app.core.db import instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("fno_universe")

QUOTE_PACE = 0.15


async def fno_equities() -> dict[str, dict]:
    """Every stock that has listed options AND a quotable Angel equity token."""
    unders = [u for u in await instruments_collection.distinct(
        "underlying_symbol", {"asset_class": "EQUITY_OPTION"}) if u]
    return {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": unders}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1})}


async def scan_falls() -> list[dict]:
    """Today's day-change for every F&O stock, worst first. `close` from Angel's FULL
    quote is the PREVIOUS session's close during market hours, which is exactly the
    reference a '% down on the day' rule needs."""
    eq = await fno_equities()
    if not eq:
        return []
    by_ex: dict[str, list[str]] = {}
    tok2sym: dict[str, str] = {}
    for sym, d in eq.items():
        tok = str(d["angel_token"])
        by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(tok)
        tok2sym[tok] = sym

    try:
        await angel_client._session()
    except AngelAPIError:
        pass
    quotes: dict[str, dict] = {}
    for grouped in batches(by_ex):
        try:
            quotes.update(await angel_client.full_quote(grouped))
        except AngelAPIError:
            pass
        await asyncio.sleep(QUOTE_PACE)

    rows = []
    for tok, q in quotes.items():
        sym = tok2sym.get(tok)
        ltp, prev = q.get("ltp"), q.get("close")
        if not sym or not ltp or not prev:
            continue
        chg = (float(ltp) / float(prev) - 1) * 100
        rows.append({"symbol": sym, "ltp": round(float(ltp), 2),
                     "prev_close": round(float(prev), 2), "change_pct": round(chg, 2)})
    rows.sort(key=lambda r: r["change_pct"])
    return rows
