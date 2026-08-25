"""Maps our Dhan-keyed instruments onto Angel One symboltokens.

Every instrument in this app is identified by a Dhan security_id; Angel addresses
the same contract by its own `symboltoken` plus an exchange segment. Failing over
a quote or a candle therefore needs a translation table, which this builds from
Angel's public scrip master and stores as `angel_token`/`angel_exchange` on each
instrument doc.

Coverage is deliberately not expected to be 100%: Dhan lists a far wider option
strike ladder than Angel does, so deep-OTM strikes legitimately have no Angel
counterpart. What matters is that everything liquid enough to hold or chart maps.
"""

import logging

import httpx
from pymongo import UpdateOne

from app.core.db import instruments_collection

# Cash-segment series we accept. Restricting this to "-EQ" silently dropped every
# Trade-to-Trade (-BE) stock — real NSE listings like STLTECH (Rs33,460cr), MODISONLTD and
# WELINV simply never got an Angel token, so no module could quote or trade them. BE is a
# settlement restriction (delivery only, no intraday), not a lesser listing, and it is
# exactly the segment a delivery-held desk should be able to reach. -BZ and -SM are the
# surveillance and SME series and are included for the same reason: absent is worse than
# present-and-labelled.
CASH_SUFFIXES = ("-EQ", "-BE", "-BZ", "-SM")

logger = logging.getLogger("angel_instruments")

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

DERIVATIVE_CLASSES = {
    "INDEX_OPTION", "EQUITY_OPTION", "INDEX_FUTURE", "EQUITY_FUTURE",
    "COMMODITY_FUTURE", "COMMODITY_OPTION",
}
CASH_CLASSES = {"EQUITY", "ETF"}

# Which Angel exchange lists the same contract as a given Dhan segment. Angel
# carries some commodities on both MCX and NCO (NSE's commodity segment) under
# identical name/expiry/strike, so without this preference whichever row appears
# later in the master silently wins — which mapped MCX gold to the NSE listing.
PREFERRED_ANGEL_EXCHANGE = {
    "NSE_EQ": "NSE",
    "BSE_EQ": "BSE",
    "IDX_I": "NSE",
    "NSE_FNO": "NFO",
    "BSE_FNO": "BFO",
    "MCX_COMM": "MCX",
}


def _pick(candidates: dict[str, str] | None, dhan_segment: str | None) -> tuple[str, str] | None:
    """Choose the listing on the venue matching the Dhan segment, else any of them."""
    if not candidates:
        return None
    preferred = PREFERRED_ANGEL_EXCHANGE.get(dhan_segment or "")
    if preferred and preferred in candidates:
        return candidates[preferred], preferred
    exchange, token = next(iter(candidates.items()))
    return token, exchange


def to_angel_expiry(iso_date: str) -> str:
    """2026-07-21 -> 21JUL2026, the format Angel's master uses."""
    y, m, d = iso_date.split("-")
    return f"{int(d):02d}{_MONTHS[int(m) - 1]}{y}"


def _build_lookups(rows: list[dict]) -> tuple[dict, dict, dict, dict]:
    """Four indexes: derivatives by contract identity, cash by ticker, cash TRADING SYMBOLS
    by ticker (the full Angel symbol like "RELIANCE-EQ", needed to place an order — the
    token alone isn't enough), and indices by name. Each maps to {angel_exchange: value}
    because the same contract can be listed on more than one Angel venue."""
    deriv: dict[tuple, dict[str, str]] = {}
    cash: dict[str, dict[str, str]] = {}
    cash_ts: dict[str, dict[str, str]] = {}
    indices: dict[str, dict[str, str]] = {}
    for row in rows:
        seg = row.get("exch_seg")
        itype = row.get("instrumenttype") or ""
        sym = row.get("symbol") or ""
        token = row.get("token")
        if not token:
            continue
        if itype.startswith(("OPT", "FUT")):
            is_future = itype.startswith("FUT")
            if is_future:
                strike = -1.0
            else:
                try:
                    # Angel quotes strikes in paise.
                    strike = round(float(row.get("strike") or -1) / 100.0, 2)
                except (TypeError, ValueError):
                    continue
            kind = "FUT" if is_future else sym[-2:]
            if kind not in ("FUT", "CE", "PE"):
                continue
            deriv.setdefault((row.get("name"), row.get("expiry"), strike, kind), {}).setdefault(seg, str(token))
        elif seg in ("NSE", "BSE") and sym.upper().endswith(CASH_SUFFIXES):
            base = sym.rsplit("-", 1)[0].upper()
            # -EQ wins if a symbol somehow lists in two series: it is the normal rolling
            # segment, and setdefault below would otherwise freeze whichever row the
            # scrip master happened to emit first.
            if sym.upper().endswith("-EQ"):
                cash[base] = {**cash.get(base, {}), seg: str(token)}
                cash_ts[base] = {**cash_ts.get(base, {}), seg: sym.upper()}
            else:
                cash.setdefault(base, {}).setdefault(seg, str(token))
                cash_ts.setdefault(base, {}).setdefault(seg, sym.upper())
        elif seg in ("NSE", "BSE"):
            indices.setdefault((row.get("name") or "").upper(), {}).setdefault(seg, str(token))
    return deriv, cash, cash_ts, indices


def _match(doc: dict, deriv: dict, cash: dict, indices: dict) -> tuple[str, str] | None:
    asset_class = doc.get("asset_class")
    segment = doc.get("exchange_segment")
    if asset_class in CASH_CLASSES:
        return _pick(cash.get((doc.get("symbol") or "").upper()), segment)
    if asset_class == "INDEX":
        found = indices.get((doc.get("symbol") or "").upper()) or indices.get((doc.get("name") or "").upper())
        return _pick(found, segment)
    if asset_class in DERIVATIVE_CLASSES:
        expiry = doc.get("expiry")
        if not expiry:
            return None
        kind = (doc.get("option_type") or "FUT").upper()
        strike = round(float(doc["strike"]), 2) if doc.get("strike") is not None else -1.0
        if kind == "FUT":
            strike = -1.0
        return _pick(deriv.get((doc.get("underlying_symbol"), to_angel_expiry(expiry), strike, kind)), segment)
    return None


async def refresh_angel_tokens() -> dict:
    """Re-map every instrument. Safe to re-run; only writes docs whose token changed."""
    async with httpx.AsyncClient(timeout=180) as client:
        rows = (await client.get(SCRIP_MASTER_URL)).json()
    deriv, cash, cash_ts, indices = _build_lookups(rows)

    ops: list[UpdateOne] = []
    matched = 0
    total = 0
    per_class: dict[str, list[int]] = {}
    async for doc in instruments_collection.find(
        {},
        {"security_id": 1, "exchange_segment": 1, "asset_class": 1, "symbol": 1, "name": 1,
         "underlying_symbol": 1, "expiry": 1, "strike": 1, "option_type": 1,
         "angel_token": 1, "angel_tradingsymbol": 1},
    ):
        total += 1
        hit = _match(doc, deriv, cash, indices)
        stats = per_class.setdefault(doc.get("asset_class") or "?", [0, 0])
        stats[1] += 1
        if not hit:
            continue
        matched += 1
        stats[0] += 1
        token, exchange = hit
        set_fields = {"angel_token": token, "angel_exchange": exchange}
        # For cash equities also stamp the Angel TRADING SYMBOL (e.g. "RELIANCE-EQ") — an
        # order needs it, the token alone won't place one.
        is_cash = doc.get("asset_class") in CASH_CLASSES
        if is_cash:
            ts = cash_ts.get((doc.get("symbol") or "").upper(), {}).get(exchange)
            if ts:
                set_fields["angel_tradingsymbol"] = ts
        # Skip only when nothing would change: same token AND (not cash, or its trading
        # symbol is already stored). This lets a first run backfill the new field.
        if doc.get("angel_token") == token and (not is_cash or doc.get("angel_tradingsymbol")):
            continue
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": set_fields}))

    written = 0
    for i in range(0, len(ops), 1000):
        result = await instruments_collection.bulk_write(ops[i : i + 1000], ordered=False)
        written += result.modified_count

    summary = {
        "angel_rows": len(rows),
        "instruments": total,
        "matched": matched,
        "written": written,
        "by_class": {k: {"matched": v[0], "total": v[1]} for k, v in sorted(per_class.items())},
    }
    logger.info("Angel token map refreshed: %s/%s matched, %s updated", matched, total, written)
    return summary
