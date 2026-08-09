"""NSE stock options (OPTSTK) — instrument master + a rate-limit-safe ATM chain.

Why this module exists: the instrument master shipped from Dhan carries INDEX options
(NIFTY/BANKNIFTY/...) and COMMODITY options, but ZERO stock options — so a stock-option
desk had no contracts to trade. Angel's public scrip master does carry them (~27k NSE
OPTSTK contracts across ~208 underlyings), so we load them from there and stamp the Angel
token on each, which also makes them quotable through the same Angel feed everything else
already uses.

Two facts about Indian stock options that differ from the NIFTY desk and drive the design:
  * they expire MONTHLY, not weekly, so "current expiry" is the nearest monthly;
  * lot size and strike step vary PER STOCK (RELIANCE is not TCS), so nothing may be
    hardcoded the way the NIFTY desk hardcodes 75 / 50.

Rate limits: Angel prices at most 50 tokens per quote request. We therefore never pull a
full chain for the universe — only the few strikes around ATM that a desk can actually
trade, batched across every symbol at once and paced between chunks. `atm_quotes()` for a
20-stock universe is 2-3 requests, not 200.
"""

import asyncio
import gc
import logging
import re
from datetime import date, datetime, timezone

import httpx
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from app.core.db import instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from app.services.angel_instruments import SCRIP_MASTER_URL
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("stock_options")

QUOTE_PACE_SECONDS = 0.15
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_EXPIRY_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{4})$")


def _iso_expiry(angel_expiry: str) -> str | None:
    """27OCT2026 -> 2026-10-27."""
    m = _EXPIRY_RE.match((angel_expiry or "").upper())
    if not m:
        return None
    d, mon, y = m.groups()
    if mon not in _MONTHS:
        return None
    return f"{y}-{_MONTHS.index(mon) + 1:02d}-{int(d):02d}"


async def refresh_stock_options() -> dict:
    """Load every NSE stock-option contract from Angel's scrip master into `instruments`
    as asset_class EQUITY_OPTION, already carrying its Angel token/tradingsymbol.

    Idempotent: keyed on (underlying, expiry, strike, option_type) so re-running only
    updates. Expired contracts are dropped so the collection cannot grow without bound."""
    async with httpx.AsyncClient(timeout=300) as c:
        rows = (await c.get(SCRIP_MASTER_URL)).json()

    # The master is ~152k rows; holding all of them AND 27k pending writes at once is what
    # OOM-killed the container. Narrow to just the NSE stock-option rows, keep only the
    # seven fields we use, then drop the full parse before building any writes.
    compact = [
        (r.get("token"), r.get("symbol"), r.get("name"), r.get("expiry"),
         r.get("strike"), r.get("lotsize"), r.get("tick_size"))
        for r in rows
        if r.get("instrumenttype") == "OPTSTK" and r.get("exch_seg") == "NFO"
    ]
    del rows
    gc.collect()

    today = date.today().isoformat()
    ops: list[UpdateOne] = []
    kept = skipped = 0
    written = dupes = 0
    underlyings: set[str] = set()

    async def _flush() -> None:
        """Write and release the pending ops so memory stays flat over the whole master."""
        nonlocal ops, written, dupes
        if not ops:
            return
        try:
            res = await instruments_collection.bulk_write(ops, ordered=False)
            written += (res.upserted_count or 0) + (res.modified_count or 0)
        except BulkWriteError as exc:
            det = exc.details or {}
            written += (det.get("nUpserted") or 0) + (det.get("nModified") or 0)
            errs = det.get("writeErrors") or []
            dupes += sum(1 for e in errs if e.get("code") == 11000)
            other = [e for e in errs if e.get("code") != 11000]
            if other:
                logger.warning("stock options: %s non-duplicate write errors, e.g. %s",
                               len(other), other[0].get("errmsg"))
        ops = []

    for token, rsym, rname, rexp, rstrike, rlot, rtick in compact:
        r = {"token": token, "tick_size": rtick}
        sym = (rsym or "").upper()
        name = (rname or "").upper()
        expiry = _iso_expiry(rexp or "")
        if not (sym and name and expiry):
            skipped += 1
            continue
        if expiry < today:  # already expired — never load it
            continue
        kind = sym[-2:]
        if kind not in ("CE", "PE"):
            skipped += 1
            continue
        try:
            # Angel quotes strikes in paise.
            strike = round(float(rstrike or 0) / 100.0, 2)
            lot = int(float(rlot or 0))
        except (TypeError, ValueError):
            skipped += 1
            continue
        if strike <= 0 or lot <= 0:
            skipped += 1
            continue

        underlyings.add(name)
        our_symbol = f"{name}-{expiry}-{strike:g}-{kind}"
        ops.append(UpdateOne(
            {"asset_class": "EQUITY_OPTION", "underlying_symbol": name,
             "expiry": expiry, "strike": strike, "option_type": kind},
            {"$set": {
                "symbol": our_symbol, "asset_class": "EQUITY_OPTION",
                "underlying_symbol": name, "expiry": expiry, "strike": strike,
                "option_type": kind, "lot_size": lot,
                "exchange_segment": "NSE_FNO",
                # Angel-native contracts: there is no Dhan security id for them. The
                # collection has a UNIQUE (security_id, exchange_segment) index, and raw
                # Angel tokens collide numerically with the Dhan ids already stored under
                # NSE_FNO — so the id is namespaced. Nothing sends this to Dhan; every read
                # path for this desk quotes off angel_token.
                "security_id": f"ANGEL{r.get('token')}",
                "angel_token": str(r.get("token")), "angel_exchange": "NFO",
                "angel_tradingsymbol": sym,
                "tick_size": float(r.get("tick_size") or 0) / 100.0,
                "source": "angel_scrip_master",
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        ))
        kept += 1
        if len(ops) >= 500:
            await _flush()

    await _flush()
    del compact
    gc.collect()

    purged = (await instruments_collection.delete_many(
        {"asset_class": "EQUITY_OPTION", "expiry": {"$lt": today}})).deleted_count

    logger.info("stock options refreshed: %s contracts, %s underlyings, %s written, %s dup-skipped, %s expired purged",
                kept, len(underlyings), written, dupes, purged)
    return {"contracts": kept, "underlyings": len(underlyings), "written": written,
            "duplicate_skipped": dupes, "expired_purged": purged, "skipped": skipped}


# --------------------------------------------------------------------------------
# Universe + chain helpers
# --------------------------------------------------------------------------------


async def option_underlyings() -> list[str]:
    """Every stock that currently has listed options."""
    return sorted(u for u in await instruments_collection.distinct(
        "underlying_symbol", {"asset_class": "EQUITY_OPTION"}) if u)


async def current_expiry(symbol: str, on: str | None = None) -> str | None:
    """Nearest non-expired MONTHLY expiry for this stock."""
    on = on or date.today().isoformat()
    exps = [e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol}) if e and e >= on]
    return min(exps) if exps else None


async def atm_contracts(symbol: str, spot: float, expiry: str | None = None) -> dict[str, dict]:
    """The ATM CE and PE for this stock's nearest expiry, chosen from the REAL listed
    strike ladder (strike steps differ per stock, so the nearest listed strike is found
    rather than computed from a hardcoded step)."""
    expiry = expiry or await current_expiry(symbol)
    if not expiry or not spot:
        return {}
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol, "expiry": expiry},
        {"symbol": 1, "strike": 1, "option_type": 1, "lot_size": 1,
         "angel_token": 1, "angel_exchange": 1, "angel_tradingsymbol": 1, "security_id": 1})]
    if not rows:
        return {}
    strikes = sorted({r["strike"] for r in rows})
    atm = min(strikes, key=lambda s: abs(s - spot))
    out: dict[str, dict] = {}
    for r in rows:
        if r["strike"] == atm and r["option_type"] in ("CE", "PE"):
            out[r["option_type"]] = r
    return out


async def batched_ltp(tokens_by_exchange: dict[str, list[str]]) -> dict[str, float]:
    """LTP for many tokens with Angel's 50-per-request cap respected, paced, and tolerant
    of a single failing chunk — the same shape the equity desks use. This is what keeps a
    multi-symbol option desk inside the rate limit."""
    out: dict[str, float] = {}
    if not any(tokens_by_exchange.values()):
        return out
    for attempt in range(2):
        try:
            await angel_client._session()
            break
        except AngelAPIError:
            if attempt == 0:
                await asyncio.sleep(0.7)
    for grouped in batches(tokens_by_exchange):
        try:
            out.update(await angel_client.ltp(grouped))
        except AngelAPIError:
            pass
        await asyncio.sleep(QUOTE_PACE_SECONDS)
    return out
