"""Commodity Positions — a user-initiated paper trading desk for MCX FUTURES and OPTIONS.

The commodity twin of `app.services.fno_positions`, whose account/fill/exit/basket shape
this mirrors deliberately so the two desks behave identically where they can. Four things
about MCX genuinely differ, and all four were verified against live production data rather
than assumed.

1. ANGEL ONLY. Dhan cannot price MCX at all — every quote and candle path in this app has
   failed there, which is why the Commodity Trading desk already runs entirely on Angel.
   So there is no `DhanClient` in this module: quotes, chains and spot all come from
   `angel_client`, and margin is computed locally rather than asked of a broker.

2. THE INSTRUMENT MASTER'S `lot_size` IS WRONG FOR MCX — it says 1 for every contract.
   Angel's own scrip master carries the real order-quantity unit, but that is NOT the same
   as the value multiplier, and for three of the eight underlyings they disagree. Settled
   empirically against live prices on 2026-08-22:

       GOLD    price 1,62,688   x Angel lotsize 1    = Rs 1.6 lakh   (a 1 kg gold lot?)
                                x MCX spec     100   = Rs 1.63 crore  <- correct
       ZINC    price    417.50  x Angel lotsize 5    = Rs 2,088      (absurd)
                                x MCX spec    5000   = Rs 20.9 lakh   <- correct
       GOLDM   price 1,61,675   x Angel lotsize 100  = Rs 1.6 crore   (same as GOLD?)
                                x MCX spec      10   = Rs 16.2 lakh   <- correct

   The other five agree. `CONTRACT_SPEC` below therefore carries the published MCX
   quantity-per-lot and price-quotation unit, and `check_specs()` re-derives the contract
   value so a spec that drifts shows up as an implausible number instead of silently
   mis-pricing every trade.

3. MCX OPTIONS ARE OPTIONS ON FUTURES (`OPTFUT`), not on a spot index. The underlying of a
   CRUDEOIL 7000 CE is a CRUDEOIL futures contract, and the option expires BEFORE the
   future it is written on (SILVER options 28 Aug, the SILVER future 04 Sep). So the
   "spot" fed to Greeks and to the margin scan is the price of the nearest future expiring
   ON OR AFTER the option's expiry — not a spot price, which for a commodity does not
   exist in this system at all.

4. SCAN RANGES ARE PER UNDERLYING. The F&O desk uses one 6% price-scan for everything,
   calibrated on NIFTY. Natural gas is not gold: a single number would either wildly
   over-margin the metals or under-margin the energies. `PRICE_SCAN` below is per
   underlying and env-overridable.

STRIKES AND TICKS. The instrument master stores `strike` already converted to rupees
(SILVER 272000 against a 2,42,107 futures price), but `tick_size` is still in PAISE as the
broker publishes it (a NATURALGAS future ticks at 10 = Rs 0.10). `tick_rupees()` is the
only place that conversion happens.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    commodity_accounts_collection,
    commodity_pos_orders_collection,
    commodity_pos_positions_collection,
    instruments_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.fno_margin import portfolio_margin, solve_iv
from options_service.chain import _fill_leg, _years_to_expiry, compute_max_pain, compute_pcr

logger = logging.getLogger("commodity_positions")

DEFAULT_INITIAL_CAPITAL = float(os.getenv("COMMODITY_POSITIONS_INITIAL_CAPITAL", "10000000"))
PRODUCT_TYPES = ("INTRADAY", "MARGIN")
FUTURE_CLASS = "COMMODITY_FUTURE"
OPTION_CLASS = "COMMODITY_OPTION"
MCX_EXCHANGE = "MCX"

# MCX published contract specification per underlying:
#   (quantity per lot, what the quoted price is per, value multiplier)
# The multiplier converts a quoted price into contract value: notional = price x mult.
# Verified against live prices — see the module docstring for the three that disagree with
# the broker's own `lotsize` field.
CONTRACT_SPEC: dict[str, tuple[str, str, int]] = {
    # --- bullion -----------------------------------------------------------------
    "GOLD":       ("1 kg",          "₹ per 10 grams", 100),
    "GOLDM":      ("100 grams",     "₹ per 10 grams", 10),
    "GOLDTEN":    ("10 grams",      "₹ per 10 grams", 1),
    "GOLDGUINEA": ("8 grams",       "₹ per 8 grams",  1),
    "GOLDPETAL":  ("1 gram",        "₹ per 1 gram",   1),
    "SILVER":     ("30 kg",         "₹ per kg",       30),
    "SILVERM":    ("5 kg",          "₹ per kg",       5),
    "SILVERMIC":  ("1 kg",          "₹ per kg",       1),
    # Priced at 2,421 against SILVERMIC's 2,42,275 for 1 kg — a factor of 100, so
    # SILVER100 is quoted per 10 GRAMS, not per kg. The multiplier is unchanged; the
    # label was wrong, and a wrong label on a right number is still something the
    # page would have told you incorrectly.
    "SILVER100":  ("1 kg",          "₹ per 10 grams", 100),
    # --- energy ------------------------------------------------------------------
    "CRUDEOIL":   ("100 barrels",   "₹ per barrel",   100),
    "CRUDEOILM":  ("10 barrels",    "₹ per barrel",   10),
    "NATURALGAS": ("1250 mmBtu",    "₹ per mmBtu",    1250),
    "NATGASMINI": ("250 mmBtu",     "₹ per mmBtu",    250),
    # --- base metals -------------------------------------------------------------
    # The MT-quoted-per-kg family: the broker's lotsize is in TONNES while the price is
    # per KILO, which is exactly the mismatch that made ZINC read Rs 2,088 a lot.
    "COPPER":     ("2500 kg",       "₹ per kg",       2500),
    "ZINC":       ("5 tonnes",      "₹ per kg",       5000),
    "ZINCMINI":   ("1 tonne",       "₹ per kg",       1000),
    "ALUMINIUM":  ("5 tonnes",      "₹ per kg",       5000),
    "ALUMINI":    ("1 tonne",       "₹ per kg",       1000),
    "LEAD":       ("5 tonnes",      "₹ per kg",       5000),
    "LEADMINI":   ("1 tonne",       "₹ per kg",       1000),
    "NICKEL":     ("250 kg",        "₹ per kg",       250),
}

# Underlyings deliberately NOT given a spec: the agriculturals and power contracts
# (CARDAMOM, COTTON, COTTONOIL, KAPAS, MENTHAOIL, STEELREBAR, ELECDMBL). Their
# quotation units vary and asserting one from memory would silently mis-price every
# trade on them by a factor of ten or more. They fall back to the broker's own
# `angel_lotsize` and are reported `verified: false`, with the derived contract value
# shown so it can be checked against the exchange's published spec before trading.

# SPAN price-scan range per COMMODITY, not per contract. Energies move multiples of what
# the metals do, and one shared number would over-margin gold or under-margin natural gas.
#
# Keyed by commodity family on purpose: a mini contract is the same commodity in a smaller
# wrapper and therefore has exactly the same volatility. The first version keyed on the
# contract symbol, so CRUDEOILM and NATGASMINI fell through to the default — which
# under-margined the gas mini by a third against its own parent (8% against 13%). Caught
# by the first live round trip, not by reading the code.
PRICE_SCAN: dict[str, float] = {
    "GOLD": 0.05, "SILVER": 0.08, "CRUDEOIL": 0.09, "NATURALGAS": 0.13,
    "COPPER": 0.06, "ZINC": 0.06, "ALUMINIUM": 0.06, "LEAD": 0.06, "NICKEL": 0.08,
}

# Which family each listed contract belongs to. Everything not named here falls back to
# its own symbol and then to DEFAULT_SCAN.
SCAN_FAMILY: dict[str, str] = {
    "GOLDM": "GOLD", "GOLDTEN": "GOLD", "GOLDGUINEA": "GOLD", "GOLDPETAL": "GOLD",
    "SILVERM": "SILVER", "SILVERMIC": "SILVER", "SILVER100": "SILVER",
    "CRUDEOILM": "CRUDEOIL", "NATGASMINI": "NATURALGAS",
    "ZINCMINI": "ZINC", "ALUMINI": "ALUMINIUM", "LEADMINI": "LEAD",
}
DEFAULT_SCAN = float(os.getenv("COMMODITY_MARGIN_SCAN_PCT", "0.08"))
EXPOSURE_PCT = float(os.getenv("COMMODITY_MARGIN_EXPOSURE_PCT", "0.02"))
QUOTE_PACE_S = float(os.getenv("COMMODITY_POSITIONS_QUOTE_PACE", "0.25"))
# Angel's quote endpoint takes at most this many tokens per call.
QUOTE_BATCH = 50


class OrderError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


# Broker lot sizes, loaded once from the instrument master, for underlyings with no
# published spec above. Populated by `prime_lotsizes()`; empty until then.
_LOTSIZE: dict[str, int] = {}


def multiplier(underlying: str) -> int:
    """Contract value multiplier: notional = price x multiplier x lots.

    Published MCX spec first; the broker's own order-quantity unit second. Never a bare
    1 — that was the original bug, and it understates a ZINC lot by 5,000x."""
    sym = (underlying or "").upper()
    spec = CONTRACT_SPEC.get(sym)
    if spec:
        return spec[2]
    return _LOTSIZE.get(sym, 1)


async def prime_lotsizes() -> dict[str, int]:
    """Cache `angel_lotsize` per underlying, for the ones with no published spec."""
    from app.core.db import instruments_collection as _I
    out: dict[str, int] = {}
    async for d in _I.find(
            {"asset_class": FUTURE_CLASS, "expiry": {"$gte": _today()}},
            {"underlying_symbol": 1, "angel_lotsize": 1, "lot_size": 1}):
        sym = (d.get("underlying_symbol") or "").upper()
        lot = d.get("angel_lotsize") or d.get("lot_size")
        if sym and lot and sym not in out:
            try:
                out[sym] = int(lot)
            except (TypeError, ValueError):
                continue
    _LOTSIZE.update(out)
    return out


def tick_rupees(inst: dict) -> float:
    """The broker publishes MCX ticks in paise; everything user-facing wants rupees."""
    raw = inst.get("tick_size")
    try:
        return round(float(raw) / 100.0, 4) if raw else 0.05
    except (TypeError, ValueError):
        return 0.05


def contract_value(underlying: str, price: float, lots: int = 1) -> float:
    return round(float(price) * multiplier(underlying) * max(lots, 1), 2)


def spec_doc(underlying: str) -> dict:
    sym = (underlying or "").upper()
    spec = CONTRACT_SPEC.get(sym)
    if spec:
        qty, unit, mult = spec
        return {"verified": True, "lot_quantity": qty, "price_unit": unit,
                "multiplier": mult, "spec_source": "MCX published contract specification"}
    lot = _LOTSIZE.get(sym)
    return {
        "verified": False,
        "lot_quantity": f"{lot} (broker unit)" if lot else "unknown",
        "price_unit": "unknown", "multiplier": lot or 1,
        "spec_source": "broker lotsize — no published spec on file",
        "note": f"{sym} has no contract spec in this module, so its lot value is taken "
                "from the broker's order-quantity unit. Check the contract value against "
                "the exchange's published specification before trading it.",
    }


def check_specs(prices: dict[str, float]) -> list[dict]:
    """Re-derive each contract value from live prices so a stale spec is visible.

    An MCX lot is worth roughly Rs 2 lakh to Rs 4 crore. Anything outside that band means
    the multiplier is off by a power of ten and every P&L on that underlying is wrong by
    the same factor — better surfaced on a diagnostics endpoint than discovered in a
    trade."""
    out = []
    for sym, px in sorted(prices.items()):
        if not px:
            continue
        value = contract_value(sym, px)
        out.append({
            "underlying": sym, "price": px, "contract_value": value,
            "multiplier": multiplier(sym),
            # MCX lots run from a 1-gram GOLDPETAL (~Rs 16k) to a 1 kg GOLD bar
            # (~Rs 1.6 crore), so the band is wide on purpose. Outside it, a
            # multiplier is out by a power of ten.
            "plausible": 1e4 <= value <= 5e7,
            **spec_doc(sym),
        })
    return out


# --------------------------------------------------------------------------------
# Indexes
# --------------------------------------------------------------------------------


async def ensure_indexes() -> None:
    """This module owns every `commodity_*` index, with names, in its own try per index.

    Both halves of that are lessons from the Trending Stocks deploy: `main.py`'s generic
    index map creates keys WITHOUT names, so declaring a collection in both places makes
    Mongo reject the named one as a conflict — and wrapping all creations in ONE try meant
    a single conflict silently skipped every index after it."""
    specs = [
        (commodity_accounts_collection, [("account_id", 1)], "cmp_acct_key", True),
        (commodity_pos_positions_collection, [("account_id", 1), ("status", 1)],
         "cmp_pos_account", False),
        (commodity_pos_positions_collection, [("position_id", 1)], "cmp_pos_key", True),
        (commodity_pos_positions_collection, [("closed_on", 1)], "cmp_pos_closed_on", False),
        (commodity_pos_orders_collection, [("account_id", 1), ("placed_at", -1)],
         "cmp_ord_account", False),
        (commodity_pos_orders_collection, [("order_id", 1)], "cmp_ord_key", True),
    ]
    made = skipped = 0
    for coll, keys, name, unique in specs:
        try:
            await coll.create_index(keys, name=name, unique=unique, background=True)
            made += 1
        except Exception as exc:  # noqa: BLE001 — one conflict must not skip the rest
            skipped += 1
            logger.warning("[commodity_positions] index %s skipped: %s", name, exc)
    logger.info("[commodity_positions] indexes ensured (%d present, %d skipped)", made, skipped)


# --------------------------------------------------------------------------------
# Accounts — independent named paper books, mirroring fno_positions exactly.
# --------------------------------------------------------------------------------


async def ensure_default_account() -> dict:
    existing = await commodity_accounts_collection.find_one(sort=[("created_at", 1)])
    if existing is not None:
        existing.pop("_id", None)
        return existing
    account = {"account_id": uuid4().hex[:12], "name": "Default",
               "initial_capital": DEFAULT_INITIAL_CAPITAL, "created_at": _now()}
    await commodity_accounts_collection.insert_one(dict(account))
    # Adopt any account-less rows written before accounts existed, exactly as the F&O
    # desk did on its own upgrade — so this can never orphan earlier data.
    await commodity_pos_positions_collection.update_many(
        {"account_id": {"$exists": False}}, {"$set": {"account_id": account["account_id"]}})
    await commodity_pos_orders_collection.update_many(
        {"account_id": {"$exists": False}}, {"$set": {"account_id": account["account_id"]}})
    return account


async def list_accounts() -> list[dict]:
    await ensure_default_account()
    return [d async for d in commodity_accounts_collection.find({}, {"_id": 0}).sort("created_at", 1)]


async def get_account(account_id: str) -> dict:
    doc = await commodity_accounts_collection.find_one({"account_id": account_id}, {"_id": 0})
    if doc is None:
        raise OrderError(f"Unknown account {account_id}")
    return doc


async def create_account(name: str, initial_capital: float | None = None) -> dict:
    clean = (name or "").strip()
    if not clean:
        raise OrderError("Account name cannot be empty")
    if await commodity_accounts_collection.find_one({"name": clean}):
        raise OrderError(f"An account named {clean!r} already exists")
    account = {"account_id": uuid4().hex[:12], "name": clean,
               "initial_capital": float(initial_capital or DEFAULT_INITIAL_CAPITAL),
               # The day performance is measured from. Defaults to the account's own
               # creation date, which is the only start that cannot be wrong.
               "roi_start_date": _today(),
               "created_at": _now()}
    await commodity_accounts_collection.insert_one(dict(account))
    return account


async def edit_account(account_id: str, name: str | None = None,
                       initial_capital: float | None = None,
                       roi_start_date: str | None = None) -> dict:
    await get_account(account_id)
    changes: dict = {}
    if name is not None:
        clean = name.strip()
        if not clean:
            raise OrderError("Account name cannot be empty")
        clash = await commodity_accounts_collection.find_one(
            {"name": clean, "account_id": {"$ne": account_id}})
        if clash:
            raise OrderError(f"An account named {clean!r} already exists")
        changes["name"] = clean
    if initial_capital is not None:
        if float(initial_capital) <= 0:
            raise OrderError("Capital must be positive")
        changes["initial_capital"] = float(initial_capital)
    if roi_start_date is not None:
        changes["roi_start_date"] = _parse_start(roi_start_date)
    if changes:
        await commodity_accounts_collection.update_one(
            {"account_id": account_id}, {"$set": changes})
    return await get_account(account_id)


async def delete_account(account_id: str) -> dict:
    """Remove a paper account and everything in it.

    Refuses while positions are still open: deleting a book with live positions would
    orphan them — they would keep being marked to market by the sync pass, against an
    account that no longer exists to carry the risk. Close first, then delete."""
    account = await get_account(account_id)
    open_count = await commodity_pos_positions_collection.count_documents(
        {"account_id": account_id, "status": "OPEN"})
    if open_count:
        raise OrderError(
            f"{account['name']} still has {open_count} open position"
            f"{'s' if open_count > 1 else ''}. Close them first — deleting the account "
            "would leave them being marked to market against a book that is gone.")
    if await commodity_accounts_collection.count_documents({}) <= 1:
        raise OrderError(
            "This is the only paper account. Create another before deleting this one, "
            "or use Reset to empty it instead.")

    pos = await commodity_pos_positions_collection.delete_many({"account_id": account_id})
    orders = await commodity_pos_orders_collection.delete_many({"account_id": account_id})
    await commodity_accounts_collection.delete_one({"account_id": account_id})
    return {"deleted": account["name"], "closed_positions_removed": pos.deleted_count,
            "orders_removed": orders.deleted_count}


# --------------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------------


async def underlyings() -> list[dict]:
    """The MCX underlyings with at least one unexpired, Angel-mapped contract.

    ONE aggregation, not a count per underlying. The first version issued two
    `count_documents` per underlying — 56 round trips to Atlas, measured at 2.7 seconds,
    which was enough for the endpoint to time out entirely. Because the page loaded this
    alongside the account list in a single `Promise.all`, that one slow call blanked the
    whole screen: no accounts, no underlyings, every tile a dash. The same grouping now
    takes 37 ms.

    Counts are reported per underlying so an underlying whose options have not been
    token-mapped reads as a coverage gap rather than as an empty chain later."""
    await prime_lotsizes()
    pipeline = [
        {"$match": {"asset_class": {"$in": [FUTURE_CLASS, OPTION_CLASS]},
                    "expiry": {"$gte": _today()}, "angel_token": {"$ne": None}}},
        {"$group": {"_id": {"u": "$underlying_symbol", "c": "$asset_class"},
                    "n": {"$sum": 1}}},
    ]
    tally: dict[str, dict[str, int]] = {}
    async for row in instruments_collection.aggregate(pipeline):
        key = row["_id"]
        sym = key.get("u")
        if not sym:
            continue
        bucket = tally.setdefault(sym, {"futures": 0, "options": 0})
        if key.get("c") == FUTURE_CLASS:
            bucket["futures"] += row["n"]
        else:
            bucket["options"] += row["n"]

    return [{"symbol": sym, "futures": t["futures"], "options": t["options"],
             "has_options": t["options"] > 0, **spec_doc(sym)}
            for sym, t in sorted(tally.items())]


async def future_expiries(symbol: str) -> list[str]:
    rows = await instruments_collection.distinct(
        "expiry", {"underlying_symbol": symbol.upper(), "asset_class": FUTURE_CLASS,
                   "angel_token": {"$ne": None}})
    return sorted(e for e in rows if e and e >= _today())


async def option_expiries(symbol: str) -> list[str]:
    rows = await instruments_collection.distinct(
        "expiry", {"underlying_symbol": symbol.upper(), "asset_class": OPTION_CLASS,
                   "angel_token": {"$ne": None}})
    return sorted(e for e in rows if e and e >= _today())


async def _resolve_future(symbol: str, expiry: str) -> dict:
    inst = await instruments_collection.find_one(
        {"underlying_symbol": symbol.upper(), "expiry": expiry, "asset_class": FUTURE_CLASS})
    if inst is None:
        raise OrderError(f"No {symbol} futures contract for {expiry}")
    return inst


async def _resolve_option(symbol: str, expiry: str, strike: float, option_type: str) -> dict:
    inst = await instruments_collection.find_one(
        {"underlying_symbol": symbol.upper(), "expiry": expiry,
         "strike": float(strike), "option_type": option_type.upper(),
         "asset_class": OPTION_CLASS})
    if inst is None:
        raise OrderError(f"No {symbol} {expiry} {strike:g} {option_type} contract on file")
    return inst


async def underlying_future(symbol: str, option_expiry: str | None = None) -> dict | None:
    """The futures contract an option is actually written on.

    MCX options are OPTFUT — the underlying is a future, and it expires AFTER the option
    does. So the right reference is the nearest future expiring on or after the option's
    expiry; falling back to the nearest live future when nothing matches, which is what
    happens on the last few days of a cycle."""
    q = {"underlying_symbol": symbol.upper(), "asset_class": FUTURE_CLASS,
         "angel_token": {"$ne": None}}
    if option_expiry:
        doc = await instruments_collection.find_one(
            {**q, "expiry": {"$gte": option_expiry}}, sort=[("expiry", 1)])
        if doc:
            return doc
    return await instruments_collection.find_one(
        {**q, "expiry": {"$gte": _today()}}, sort=[("expiry", 1)])


# --------------------------------------------------------------------------------
# Pricing — Angel only
# --------------------------------------------------------------------------------


async def _quote_tokens(tokens: list[str]) -> dict[str, float]:
    """LTP for a list of MCX tokens, batched and paced.

    Angel throttles hard; the commodity bar poller already learned that the hard way. One
    failing chunk is skipped rather than aborting the rest, so a chain renders the strikes
    that answered instead of nothing at all."""
    out: dict[str, float] = {}
    if not tokens:
        return out
    for i in range(0, len(tokens), QUOTE_BATCH):
        chunk = tokens[i:i + QUOTE_BATCH]
        try:
            out.update(await angel_client.ltp({MCX_EXCHANGE: chunk}))
        except AngelAPIError as exc:
            logger.info("[commodity_positions] quote chunk failed (%d tokens): %s",
                        len(chunk), exc)
        if len(tokens) > QUOTE_BATCH:
            await asyncio.sleep(QUOTE_PACE_S)
    return out


async def ltp_for(inst: dict) -> float | None:
    token = inst.get("angel_token")
    if not token:
        return None
    prices = await _quote_tokens([str(token)])
    val = prices.get(str(token))
    return float(val) if val else None


async def future_price(symbol: str, option_expiry: str | None = None) -> tuple[float | None, dict | None]:
    fut = await underlying_future(symbol, option_expiry)
    if fut is None:
        return None, None
    return await ltp_for(fut), fut


# --------------------------------------------------------------------------------
# Option chain
# --------------------------------------------------------------------------------


async def option_chain(symbol: str, expiry: str, around: int = 20) -> dict:
    """One underlying + expiry, priced from Angel FULL quotes.

    Shape-identical to `angel_option_chain.option_chain` so the frontend can render it
    with the same component, but the reference price is the underlying FUTURE, and the
    ladder is trimmed to `around` strikes either side of it — a CRUDEOIL expiry carries
    324 rows and quoting all of them is several throttled round trips for strikes nobody
    is looking at."""
    contracts = [
        c async for c in instruments_collection.find(
            {"underlying_symbol": symbol.upper(), "expiry": expiry,
             "asset_class": OPTION_CLASS, "angel_token": {"$ne": None}},
            {"strike": 1, "option_type": 1, "angel_token": 1, "tick_size": 1})
    ]
    if not contracts:
        # Say which of the three possible causes it actually is, rather than asserting one.
        # The first version always blamed a token-mapping gap; measured on production, every
        # underlying is fully mapped (1044/1044 for CRUDEOILM, 4040/4040 for GOLD) and the
        # real cause was an expiry that belongs to a DIFFERENT commodity — MCX does not run
        # one calendar. Crude expires on the 17th, gas and copper on the 23rd.
        listed = await option_expiries(symbol)
        unmapped = await instruments_collection.count_documents(
            {"underlying_symbol": symbol.upper(), "expiry": expiry,
             "asset_class": OPTION_CLASS})
        if unmapped:
            raise OrderError(
                f"{symbol} has {unmapped} option contracts for {expiry} but none carry a "
                "broker token yet, so none can be priced. That is a mapping gap — reload "
                "the MCX contracts from the Contract Specs tab.")
        if listed:
            raise OrderError(
                f"{symbol} does not have an option expiry on {expiry}. MCX runs a different "
                f"calendar per commodity — {symbol} expires on "
                f"{', '.join(listed[:3])}. Pick one of those.")
        raise OrderError(
            f"{symbol} has no listed option expiries at all — MCX lists options on ten "
            "underlyings only. Use the Futures tab for this one.")

    fut_px, fut = await future_price(symbol, expiry)

    strikes_all = sorted({float(c["strike"]) for c in contracts if c.get("strike") is not None})
    keep = set(strikes_all)
    if fut_px and around > 0 and len(strikes_all) > around * 2:
        nearest = min(range(len(strikes_all)), key=lambda i: abs(strikes_all[i] - fut_px))
        keep = set(strikes_all[max(0, nearest - around): nearest + around + 1])

    tokmap: dict[str, tuple[float, str]] = {}
    for c in contracts:
        if c.get("strike") is None or float(c["strike"]) not in keep:
            continue
        tokmap[str(c["angel_token"])] = (float(c["strike"]), str(c["option_type"]).upper())

    quotes = await _quote_tokens(list(tokmap))

    legs: dict[float, dict] = {}
    for tok, (strike, ot) in tokmap.items():
        px = quotes.get(tok)
        legs.setdefault(strike, {})[ot.lower()] = {
            "last_price": float(px) if px else 0,
            "oi": 0, "volume": 0, "previous_close_price": 0,
        }

    t_years = _years_to_expiry(expiry)
    rows: list[dict] = []
    for strike in sorted(legs):
        row = {"strike": strike, "ce": legs[strike].get("ce") or {},
               "pe": legs[strike].get("pe") or {}}
        if fut_px:
            row["ce"] = _fill_leg(row["ce"], fut_px, strike, t_years, "CE")
            row["pe"] = _fill_leg(row["pe"], fut_px, strike, t_years, "PE")
        rows.append(row)

    return {
        "symbol": symbol.upper(), "expiry": expiry,
        "spot": fut_px or 0.0,
        "underlying_contract": (fut or {}).get("symbol"),
        "underlying_expiry": (fut or {}).get("expiry"),
        "days_to_expiry": round(t_years * 365),
        "strikes": rows,
        "strikes_listed": len(strikes_all), "strikes_shown": len(rows),
        "pcr_oi": compute_pcr(rows), "max_pain": compute_max_pain(rows),
        "source": "angel_full",
        "note": "Priced against the underlying FUTURE, not a spot price — MCX options are "
                "options on futures. Open interest and volume are not published on this "
                "quote path, so they read zero rather than being invented.",
        **spec_doc(symbol),
    }


async def futures_board(symbol: str | None = None) -> dict:
    """Every live futures contract with a price — the Futures tab, and the source of the
    spec cross-check."""
    await prime_lotsizes()
    q = {"asset_class": FUTURE_CLASS, "expiry": {"$gte": _today()},
         "angel_token": {"$ne": None}}
    if symbol:
        q["underlying_symbol"] = symbol.upper()
    rows = [d async for d in instruments_collection.find(q).sort([("underlying_symbol", 1),
                                                                 ("expiry", 1)])]
    prices = await _quote_tokens([str(r["angel_token"]) for r in rows])

    out: list[dict] = []
    front: dict[str, float] = {}
    for r in rows:
        px = prices.get(str(r["angel_token"]))
        sym = r.get("underlying_symbol") or ""
        if px and sym not in front:
            front[sym] = float(px)
        out.append({
            "symbol": r.get("symbol"), "underlying": sym, "expiry": r.get("expiry"),
            "security_id": r.get("security_id"), "angel_token": str(r.get("angel_token")),
            "ltp": float(px) if px else None,
            "tick": tick_rupees(r),
            "contract_value": contract_value(sym, float(px)) if px else None,
            **spec_doc(sym),
        })
    return {"contracts": out, "count": len(out), "spec_check": check_specs(front)}


# --------------------------------------------------------------------------------
# Margin — local SPAN-lite, per-underlying scan
# --------------------------------------------------------------------------------


def _scan_pct(underlying: str) -> float:
    """The price-scan band for this contract's COMMODITY.

    A mini is the same commodity as its parent, so it inherits the parent's band rather
    than the generic default."""
    sym = (underlying or "").upper()
    family = SCAN_FAMILY.get(sym, sym)
    return PRICE_SCAN.get(family, DEFAULT_SCAN)


def _leg_from(inst: dict, side: str, quantity: int, premium: float,
              ref_price: float, t_years: float) -> dict:
    option_type = inst.get("option_type")
    iv = (solve_iv(premium, ref_price, inst.get("strike"), t_years, option_type)
          if option_type else None)
    return {"kind": "OPTION" if option_type else "FUTURE", "option_type": option_type,
            "strike": inst.get("strike"), "qty": quantity, "side": side,
            "premium": premium, "iv": iv}


def _margin_for(legs: list[dict], underlying: str, ref_price: float, t_years: float) -> dict:
    """SPAN-lite with this underlying's own scan range.

    `fno_margin.portfolio_margin` is pure and broker-independent — it walks the underlying
    across a price-scan band, reprices every leg with Black-Scholes and takes the worst
    portfolio loss — so it transfers to MCX unchanged. What must NOT transfer is NIFTY's
    6% calibration: natural gas routinely moves that in a session."""
    return portfolio_margin(legs, ref_price, t_years,
                            price_scan_pct=_scan_pct(underlying),
                            exposure_pct=EXPOSURE_PCT)


async def estimate_margin(*, symbol: str, expiry: str, instrument_kind: str,
                          transaction_type: str, lots: int, price: float,
                          strike: float | None = None,
                          option_type: str | None = None) -> dict:
    inst = await _resolve_contract(instrument_kind, symbol, expiry, strike, option_type)
    mult = multiplier(symbol)
    qty = lots * mult
    ref, _fut = await future_price(symbol, expiry if instrument_kind == "OPTION" else None)
    ref = ref or price
    t = _years_to_expiry(expiry)
    leg = _leg_from(inst, transaction_type, qty, price, ref, t)
    m = _margin_for([leg], symbol, ref, t)
    return {
        "margin_required": m["total"], "span": m["span"], "exposure": m["exposure"],
        "notional_value": contract_value(symbol, price, lots),
        "quantity": qty, "multiplier": mult,
        "scan_pct": _scan_pct(symbol), "reference_price": ref,
        "source": "span_lite_mcx",
        "note": "Computed locally. Dhan's margin calculator does not cover MCX, so no "
                "broker figure is available to quote here.",
    }


# --------------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------------


async def _resolve_contract(instrument_kind: str, symbol: str, expiry: str,
                            strike: float | None, option_type: str | None) -> dict:
    if instrument_kind == "OPTION":
        if strike is None or (option_type or "").upper() not in ("CE", "PE"):
            raise OrderError("Options need a strike and option_type (CE/PE)")
        return await _resolve_option(symbol, expiry, strike, option_type)
    if instrument_kind == "FUTURE":
        return await _resolve_future(symbol, expiry)
    raise OrderError("instrument_kind must be OPTION or FUTURE")


def _build_base_order(account_id: str, inst: dict, instrument_kind: str, symbol: str,
                      expiry: str, transaction_type: str, lots: int, order_type: str,
                      product_type: str, limit_price: float) -> dict:
    now = _now()
    mult = multiplier(symbol)
    label = (f"{symbol} {expiry} {inst.get('strike'):g}{inst.get('option_type')}"
             if instrument_kind == "OPTION" else f"{symbol} {expiry} FUT")
    return {
        "order_id": f"MCX-{uuid4().hex[:12]}", "account_id": account_id,
        "symbol": inst["symbol"], "display_name": label,
        "instrument_kind": instrument_kind,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst.get("security_id"),
            "angel_token": str(inst.get("angel_token") or ""),
            "exchange_segment": inst.get("exchange_segment") or "MCX_COMM",
            "underlying_symbol": symbol.upper(), "expiry": inst.get("expiry"),
            "strike": inst.get("strike"), "option_type": inst.get("option_type"),
            "multiplier": mult, "tick": tick_rupees(inst),
        },
        "transaction_type": transaction_type, "lots": lots, "quantity": lots * mult,
        "order_type": order_type,
        "limit_price": limit_price if order_type == "LIMIT" else None,
        "product_type": product_type, "placed_at": now, "updated_at": now,
    }


async def place_order(*, account_id: str, instrument_kind: str, symbol: str, expiry: str,
                      transaction_type: str, lots: int, order_type: str,
                      product_type: str, strike: float | None = None,
                      option_type: str | None = None, limit_price: float = 0.0) -> dict:
    await get_account(account_id)
    if lots < 1:
        raise OrderError("Lots must be at least 1")
    if transaction_type not in ("BUY", "SELL"):
        raise OrderError("transaction_type must be BUY or SELL")
    if product_type not in PRODUCT_TYPES:
        raise OrderError(f"product_type must be one of {PRODUCT_TYPES}")
    if order_type == "LIMIT" and limit_price <= 0:
        raise OrderError("Limit orders need a positive limit_price")

    inst = await _resolve_contract(instrument_kind, symbol, expiry, strike, option_type)
    ltp = await ltp_for(inst)
    if ltp is None:
        raise OrderError(
            "Angel returned no price for this contract — MCX is closed or the token is "
            "unmapped. Nothing is filled at an invented price.")

    base = _build_base_order(account_id, inst, instrument_kind, symbol, expiry,
                             transaction_type, lots, order_type, product_type, limit_price)

    marketable = (order_type == "MARKET"
                  or (transaction_type == "BUY" and ltp <= limit_price)
                  or (transaction_type == "SELL" and ltp >= limit_price))
    if not marketable:
        doc = {**base, "status": "PENDING", "fill_price": None, "filled_at": None,
               "margin_used": None}
        await commodity_pos_orders_collection.insert_one(dict(doc))
        return doc

    return await _fill(base, ltp if order_type == "MARKET" else limit_price)


async def _fill(base_order: dict, fill_price: float, check_margin: bool = True) -> dict:
    inst = base_order["instrument"]
    account_id = base_order["account_id"]
    symbol = inst["underlying_symbol"]
    side, quantity = base_order["transaction_type"], base_order["quantity"]

    ref, _fut = await future_price(
        symbol, inst["expiry"] if base_order["instrument_kind"] == "OPTION" else None)
    ref = ref or fill_price
    t = _years_to_expiry(inst.get("expiry"))
    leg = _leg_from(inst, side, quantity, fill_price, ref, t)
    margin = _margin_for([leg], symbol, ref, t)["total"]

    if check_margin:
        cash = await available_cash(account_id)
        if margin > cash:
            raise OrderError(
                f"Margin ₹{margin:,.0f} exceeds the ₹{cash:,.0f} available in this account. "
                f"One {symbol} lot is {spec_doc(symbol).get('lot_quantity', 'one contract')} "
                f"— contract value ₹{contract_value(symbol, fill_price, base_order['lots']):,.0f}.")

    now = _now()
    existing = await commodity_pos_positions_collection.find_one(
        {"account_id": account_id, "status": "OPEN", "instrument.symbol": inst["symbol"]})

    if existing is not None:
        merged = _merge(existing, side, base_order["lots"], quantity, fill_price)
        await commodity_pos_positions_collection.update_one(
            {"_id": existing["_id"]}, {"$set": {**merged, "updated_at": now}})
        position_id = existing["position_id"]
    else:
        position_id = uuid4().hex[:12]
        await commodity_pos_positions_collection.insert_one({
            "position_id": position_id, "account_id": account_id,
            "symbol": inst["symbol"], "display_name": base_order["display_name"],
            "instrument_kind": base_order["instrument_kind"], "instrument": inst,
            "underlying_symbol": symbol,
            "side": side, "lots": base_order["lots"], "quantity": quantity,
            "entry_price": round(fill_price, 4), "ltp": round(fill_price, 4),
            "product_type": base_order["product_type"],
            "margin_used": round(margin, 2),
            "capital_deployed": round(margin, 2),
            "contract_value": contract_value(symbol, fill_price, base_order["lots"]),
            "unrealized_pnl": 0.0, "realized_pnl": 0.0, "status": "OPEN",
            "opened_at": now, "updated_at": now, "closed_at": None, "closed_on": None,
        })

    # Re-margin the whole group at its new size. Without this the position keeps the
    # margin of its FIRST fill for ever, and adding to it is free.
    await remargin_group(account_id, symbol, inst.get("expiry"))

    doc = {**base_order, "status": "FILLED", "fill_price": round(fill_price, 4),
           "filled_at": now, "margin_used": round(margin, 2), "position_id": position_id,
           "contract_value": contract_value(symbol, fill_price, base_order["lots"])}
    await commodity_pos_orders_collection.insert_one(dict(doc))
    return doc


def _merge(existing: dict, side: str, lots: int, quantity: int, price: float) -> dict:
    """Add to, reduce, or flip an existing position in the same contract.

    Same rule the F&O desk uses: adding averages the entry, reducing books realised P&L on
    the closed part, and a reduction past zero flips the side and re-bases the entry at
    the new fill."""
    cur_side, cur_lots, cur_qty = existing["side"], existing["lots"], existing["quantity"]
    entry, realized = existing["entry_price"], existing.get("realized_pnl") or 0.0

    if side == cur_side:
        total_qty = cur_qty + quantity
        avg = (entry * cur_qty + price * quantity) / total_qty if total_qty else price
        return {"lots": cur_lots + lots, "quantity": total_qty,
                "entry_price": round(avg, 4), "ltp": round(price, 4)}

    closing = min(cur_qty, quantity)
    direction = 1 if cur_side == "BUY" else -1
    realized += (price - entry) * closing * direction

    if quantity < cur_qty:
        return {"lots": cur_lots - lots, "quantity": cur_qty - quantity,
                "realized_pnl": round(realized, 2), "ltp": round(price, 4)}
    if quantity == cur_qty:
        return {"lots": 0, "quantity": 0, "realized_pnl": round(realized, 2),
                "status": "CLOSED", "ltp": round(price, 4),
                "closed_at": _now(), "closed_on": date.today().isoformat(),
                "unrealized_pnl": 0.0}
    return {"side": side, "lots": lots - cur_lots, "quantity": quantity - cur_qty,
            "entry_price": round(price, 4), "realized_pnl": round(realized, 2),
            "ltp": round(price, 4)}


async def remargin_group(account_id: str, underlying: str, expiry: str) -> float:
    """Re-margin an entire (account, underlying, expiry) group at its CURRENT size.

    THIS EXISTS BECAUSE MARGIN USED TO BE WRITTEN ONCE AND NEVER AGAIN. `margin_used` was
    set when a position was created and `_merge` — which grows a position when you add to
    it — never touched it. So a book could hold 38 lots while still reporting the margin of
    the single lot it opened with. Measured on a live account: a 38-lot NATGASMINI short
    strangle, Rs2.53 lakh of contract exposure on a Rs2 lakh book, blocking Rs14,574 when
    the real portfolio margin was Rs2,59,314. Every subsequent affordability check then saw
    capital that was not there.

    The group is margined as a PORTFOLIO — the same figure the basket gate quotes — and
    that total is then apportioned across the open legs by their standalone margins, so the
    per-position column still means something and the sum still equals the portfolio
    number. Both must be true: the UI reads the parts, `available_cash` reads the sum."""
    positions = await _open_group(account_id, underlying, expiry)
    if not positions:
        return 0.0

    t = _years_to_expiry(expiry)
    ref, _fut = await future_price(underlying, expiry)
    if not ref:
        # No reference price means no honest margin. Leave what is stored rather than
        # overwrite it with a number derived from an option premium standing in for its
        # own underlying — that mistake understates a short by a factor of twenty.
        logger.warning("[commodity_positions] no future price for %s %s — margin left as "
                       "stored for %d positions", underlying, expiry, len(positions))
        return sum(p.get("margin_used") or 0.0 for p in positions)

    legs = [_pos_to_leg(p, ref, t) for p in positions]
    total = _margin_for(legs, underlying, ref, t)["total"]
    standalone = [_margin_for([leg], underlying, ref, t)["total"] for leg in legs]
    denom = sum(standalone) or 1.0

    for pos, alone in zip(positions, standalone):
        share = round(total * alone / denom, 2)
        await commodity_pos_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"margin_used": share, "capital_deployed": share,
                      "standalone_margin": round(alone, 2),
                      "margin_reference_price": ref, "updated_at": _now()}})
    return total


async def atm_strike(underlying: str, expiry: str, option_type: str) -> tuple[float, float]:
    """(strike, future_price) — the listed strike nearest the underlying FUTURE.

    The future, not a spot: MCX does not quote a spot intraday, and the chain this strike
    has to exist on is priced against the future. Only strikes that carry a broker token
    are considered, because a strike with no token cannot be priced or filled."""
    ref, _fut = await future_price(underlying, expiry)
    if not ref:
        raise OrderError(
            f"No live {underlying} future for {expiry}, so there is no reference price to "
            "pick an at-the-money strike from. MCX may be closed.")
    strikes = await instruments_collection.distinct(
        "strike", {"underlying_symbol": underlying.upper(), "expiry": expiry,
                   "asset_class": OPTION_CLASS, "option_type": option_type.upper(),
                   "angel_token": {"$ne": None}})
    strikes = [float(k) for k in strikes if k is not None]
    if not strikes:
        raise OrderError(
            f"No mapped {underlying} {option_type} strikes for {expiry} to roll into.")
    return min(strikes, key=lambda k: abs(k - ref)), float(ref)


async def reopen_at_the_money(account_id: str, position_id: str) -> dict:
    """Close a position and immediately re-open the SAME contract at today's ATM strike.

    Same underlying, same expiry, same option type, same side, same lots — only the strike
    moves, to whichever listed strike now sits nearest the future. That is the whole point:
    a strike chosen weeks ago drifts as the future moves, and a 159000 call against a
    162000 future is no longer the trade that was put on.

    The margin gate runs on the NET effect — the old leg gone and the new one in its place
    — before anything is touched. Checking the new leg alone would refuse a roll that is
    self-financing, since the position being closed is releasing the margin that funds it.

    Ordering is close-then-open, and it cannot be otherwise: holding both legs at once
    would need margin for a doubled position that the account is not being asked to carry.
    The window between them is the real risk, so the gate is deliberately strict about the
    end state, and a failure to re-open is reported as exactly that rather than swallowed."""
    pos = await commodity_pos_positions_collection.find_one(
        {"position_id": position_id, "account_id": account_id, "status": "OPEN"})
    if pos is None:
        raise OrderError("No such open position in this account")

    inst = pos["instrument"]
    option_type = inst.get("option_type")
    if pos.get("instrument_kind") != "OPTION" or not option_type:
        raise OrderError(
            "Only options have an at-the-money strike. A future is already the underlying.")

    underlying, expiry = pos["underlying_symbol"], inst["expiry"]
    old_strike = float(inst.get("strike") or 0)
    lots, side = int(pos["lots"]), pos["side"]

    strike, ref = await atm_strike(underlying, expiry, option_type)

    new_leg = {"instrument_kind": "OPTION", "symbol": underlying, "expiry": expiry,
               "strike": strike, "option_type": option_type,
               "transaction_type": side, "lots": lots}
    priced = await _price_basket([new_leg])

    # Project the end state: this group with the old leg REMOVED and the new one added.
    t = _years_to_expiry(expiry)
    group = await _open_group(account_id, underlying, expiry)
    survivors = [q for q in group if q["position_id"] != position_id]
    before = _margin_for([_pos_to_leg(q, ref, t) for q in group], underlying, ref, t)["total"]
    after_legs = [_pos_to_leg(q, ref, t) for q in survivors] + [
        _leg_from(p["inst"], p["side"], p["qty"], p["ltp"], ref, t) for p in priced]
    after = _margin_for(after_legs, underlying, ref, t)["total"]
    delta = round(after - before, 2)
    cash = await available_cash(account_id)
    if not basket_allowed(delta, cash):
        raise OrderError(
            f"Rolling {pos['display_name']} to the {strike:g} strike would add "
            f"₹{delta:,.0f} of margin and only ₹{cash:,.0f} is free. Nothing was closed — "
            "the position is exactly as it was.")

    closed = await exit_position(account_id, position_id)
    # The order doc carries the fill, not the P&L — that is settled onto the position.
    closed_pos = await commodity_pos_positions_collection.find_one(
        {"position_id": position_id, "account_id": account_id})
    realized = round(float((closed_pos or {}).get("realized_pnl") or 0.0), 2)
    try:
        opened = await execute_basket(account_id, [new_leg],
                                      pos.get("product_type", "MARGIN"))
    except OrderError as exc:
        raise OrderError(
            f"{pos['display_name']} WAS CLOSED at {closed['fill_price']}, but the "
            f"{strike:g}{option_type} could not be opened: {exc.detail} You are flat on "
            "that leg — re-open it by hand from the chain.") from exc

    return {
        "closed": {"contract": pos["display_name"], "strike": old_strike,
                   "lots": lots, "side": side,
                   "exit_price": closed["fill_price"],
                   "realized": realized},
        "opened": {"contract": opened["orders"][0]["display_name"], "strike": strike,
                   "lots": lots, "side": side,
                   "entry_price": opened["orders"][0]["fill_price"]},
        "future": round(ref, 2),
        "strike_moved": round(strike - old_strike, 2),
        "margin_delta": delta,
        "net_premium": opened["net_premium"],
        "note": (f"Rolled {lots} lot{'s' if lots > 1 else ''} of {underlying} "
                 f"{option_type} from {old_strike:g} to {strike:g}, the listed strike "
                 f"nearest the {ref:,.2f} future."),
    }


async def reopen_all_at_the_money(account_id: str,
                                  position_ids: list[str] | None = None) -> dict:
    """Roll open option legs to their at-the-money strike, in one operation.

    Every open leg by default; only the ones named in `position_ids` when given.

    Not a loop over the single-leg roll. Rolling a straddle one leg at a time leaves a
    naked leg in between, and a naked leg costs MORE margin than the pair did — the leg
    that was offsetting it is gone. On a tight book that intermediate state can refuse the
    second roll, leaving the position half-rolled and worse than when it started.

    So the work is done per (underlying, expiry) group, which is the unit margin actually
    nets over: every leg in the group is closed first, releasing all of its margin, and the
    replacements go on as ONE basket that is all-or-none. The whole thing is projected and
    gated before anything is touched, so a book that cannot afford the end state is told
    that while it still holds its original positions.

    Groups are independent. If one fails, the others are unaffected and the failure names
    exactly which legs are now flat rather than reporting a generic error."""
    await get_account(account_id)
    query: dict = {"account_id": account_id, "status": "OPEN"}
    if position_ids is not None:
        wanted = [pid for pid in dict.fromkeys(position_ids) if pid]
        if not wanted:
            raise OrderError("No positions were selected to roll.")
        query["position_id"] = {"$in": wanted}
    positions = [p async for p in commodity_pos_positions_collection.find(query)]
    if position_ids is not None:
        # Name what is missing rather than quietly rolling a subset. A selection that has
        # gone stale — a row closed in another tab, or by an earlier roll in this same
        # click — would otherwise silently do less than the button said it would.
        missing = {pid for pid in wanted} - {p["position_id"] for p in positions}
        if missing:
            raise OrderError(
                f"{len(missing)} of the {len(wanted)} selected position(s) are no longer "
                "open in this account. Nothing was closed — refresh and select again.")
    if not positions:
        raise OrderError("This account has no open positions to roll.")

    rollable, skipped = [], []
    for pos in positions:
        inst = pos.get("instrument") or {}
        if pos.get("instrument_kind") == "OPTION" and inst.get("option_type"):
            rollable.append(pos)
        else:
            skipped.append(pos["display_name"])
    if not rollable:
        raise OrderError(
            "Nothing selected has an at-the-money strike — a future is already the "
            "underlying." if position_ids is not None else
            "Nothing here has an at-the-money strike — every open position is a future, "
            "and a future is already the underlying.")

    # ---- plan every group before touching anything ------------------------------
    groups: dict[tuple, list[dict]] = {}
    for pos in rollable:
        groups.setdefault((pos["underlying_symbol"], pos["instrument"]["expiry"]), []).append(pos)

    plans, total_delta = [], 0.0
    for (underlying, expiry), members in groups.items():
        t = _years_to_expiry(expiry)
        legs, moves = [], []
        ref = None
        for pos in members:
            inst = pos["instrument"]
            strike, ref = await atm_strike(underlying, expiry, inst["option_type"])
            legs.append({"instrument_kind": "OPTION", "symbol": underlying,
                         "expiry": expiry, "strike": strike,
                         "option_type": inst["option_type"],
                         "transaction_type": pos["side"], "lots": int(pos["lots"])})
            moves.append({"contract": pos["display_name"],
                          "from_strike": float(inst.get("strike") or 0),
                          "to_strike": strike, "lots": int(pos["lots"]),
                          "side": pos["side"], "option_type": inst["option_type"]})
        if len(legs) > MAX_BASKET_LEGS:
            raise OrderError(
                f"{underlying} {expiry} has {len(legs)} legs and a basket holds at most "
                f"{MAX_BASKET_LEGS}. Roll those rows individually.")

        priced = await _price_basket(legs)
        whole = await _open_group(account_id, underlying, expiry)
        ids = {pos["position_id"] for pos in members}
        survivors = [q for q in whole if q["position_id"] not in ids]
        before = _margin_for([_pos_to_leg(q, ref, t) for q in whole], underlying, ref, t)["total"]
        after = _margin_for(
            [_pos_to_leg(q, ref, t) for q in survivors]
            + [_leg_from(x["inst"], x["side"], x["qty"], x["ltp"], ref, t) for x in priced],
            underlying, ref, t)["total"]
        total_delta += after - before
        plans.append({"underlying": underlying, "expiry": expiry, "members": members,
                      "legs": legs, "moves": moves, "ref": round(float(ref), 2),
                      "product": members[0].get("product_type", "MARGIN")})

    total_delta = round(total_delta, 2)
    cash = await available_cash(account_id)
    if not basket_allowed(total_delta, cash):
        scope = "the selected" if position_ids is not None else "all"
        raise OrderError(
            f"Rolling {scope} {len(rollable)} leg(s) to the money would add "
            f"₹{total_delta:,.0f} of margin and only ₹{cash:,.0f} is free. Nothing was "
            "closed — every position is exactly as it was.")

    # ---- execute, group by group ------------------------------------------------
    rolled, failed, realized = [], [], 0.0
    for plan in plans:
        closed_here = []
        try:
            for pos in plan["members"]:
                fill = await exit_position(account_id, pos["position_id"])
                doc = await commodity_pos_positions_collection.find_one(
                    {"position_id": pos["position_id"], "account_id": account_id})
                realized += float((doc or {}).get("realized_pnl") or 0.0)
                closed_here.append({"contract": pos["display_name"],
                                    "exit_price": fill["fill_price"]})
            res = await execute_basket(account_id, plan["legs"], plan["product"])
            rolled.append({
                "underlying": plan["underlying"], "expiry": plan["expiry"],
                "future": plan["ref"], "legs": len(plan["legs"]),
                "moves": plan["moves"], "closed": closed_here,
                "net_premium": res["net_premium"], "margin_added": res["margin_added"],
            })
        except OrderError as exc:
            failed.append({"underlying": plan["underlying"], "expiry": plan["expiry"],
                           "closed": closed_here, "reason": exc.detail})

    moved = sum(1 for r in rolled for m in r["moves"] if m["from_strike"] != m["to_strike"])
    note = (f"Rolled {sum(r['legs'] for r in rolled)} leg(s) across "
            f"{len(rolled)} group(s) to the money — {moved} changed strike, "
            f"{sum(r['legs'] for r in rolled) - moved} re-entered at the same one.")
    if skipped:
        note += (f" Skipped {len(skipped)} future(s), which have no at-the-money strike.")
    if failed:
        flat = ", ".join(c["contract"] for f in failed for c in f["closed"])
        note += (f" {len(failed)} group(s) FAILED to re-open and are now flat: {flat}. "
                 "Re-open them by hand from the chain.")

    return {"rolled": rolled, "failed": failed, "skipped": skipped,
            "legs_rolled": sum(r["legs"] for r in rolled),
            "strikes_changed": moved,
            "realized": round(realized, 2),
            "margin_delta": total_delta, "note": note}


async def exit_position(account_id: str, position_id: str, lots: int | None = None) -> dict:
    pos = await commodity_pos_positions_collection.find_one(
        {"position_id": position_id, "account_id": account_id, "status": "OPEN"})
    if pos is None:
        raise OrderError("No such open position in this account")

    inst = pos["instrument"]
    doc = await instruments_collection.find_one({"symbol": inst["symbol"]})
    price = await ltp_for(doc or inst)
    if price is None:
        raise OrderError("Angel returned no price — cannot close at an invented level")

    close_lots = min(lots or pos["lots"], pos["lots"])
    if close_lots < 1:
        raise OrderError("Nothing to close")
    mult = inst.get("multiplier") or multiplier(pos.get("underlying_symbol", ""))
    quantity = close_lots * mult
    opposite = "SELL" if pos["side"] == "BUY" else "BUY"

    base = {
        "order_id": f"MCX-{uuid4().hex[:12]}", "account_id": account_id,
        "symbol": inst["symbol"], "display_name": pos["display_name"],
        "instrument_kind": pos["instrument_kind"], "instrument": inst,
        "transaction_type": opposite, "lots": close_lots, "quantity": quantity,
        "order_type": "MARKET", "limit_price": None,
        "product_type": pos.get("product_type", "MARGIN"),
        "placed_at": _now(), "updated_at": _now(),
    }
    # Closing never re-checks margin: it can only reduce risk, and refusing an exit for
    # want of margin is how a paper desk ends up unable to get out of a losing trade.
    return await _fill(base, price, check_margin=False)


# --------------------------------------------------------------------------------
# Baskets
# --------------------------------------------------------------------------------
# A basket is priced and margined AS A PORTFOLIO before a single leg is filled. That
# matters far more on MCX than on the index desks: one CRUDEOILM lot is 10 barrels and one
# GOLD lot is a kilo, so summing leg margins independently would refuse spreads a broker
# would happily accept, while filling leg by leg would let a basket get halfway in and then
# stop — leaving a naked short where a spread was intended.

MAX_BASKET_LEGS = int(os.getenv("COMMODITY_MAX_BASKET_LEGS", "10"))
# Ceiling for auto-sizing only. A rich account against a cheap contract can afford
# thousands of lots, which is not a size anyone means to put on by clicking "Max".
MAX_LOTS_PER_ORDER = int(os.getenv("COMMODITY_MAX_LOTS_PER_ORDER", "500"))


async def _price_basket(legs: list[dict]) -> list[dict]:
    """Resolve and live-price every leg. The WHOLE basket fails if any one leg cannot be
    priced — a basket goes on complete or not at all."""
    if not legs:
        raise OrderError("The basket is empty")
    if len(legs) > MAX_BASKET_LEGS:
        raise OrderError(f"A basket can hold at most {MAX_BASKET_LEGS} legs")

    priced: list[dict] = []
    for leg in legs:
        kind = str(leg.get("instrument_kind", "OPTION")).upper()
        side = str(leg.get("transaction_type", "")).upper()
        lots = int(leg.get("lots") or 0)
        if lots < 1:
            raise OrderError("Every basket leg needs at least 1 lot")
        if side not in ("BUY", "SELL"):
            raise OrderError("Each leg must be BUY or SELL")
        symbol = str(leg["symbol"]).upper()
        inst = await _resolve_contract(kind, symbol, leg["expiry"],
                                       leg.get("strike"), leg.get("option_type"))
        label = (f"{symbol} {leg['expiry']} {float(leg['strike']):g}{leg.get('option_type')}"
                 if kind == "OPTION" else f"{symbol} {leg['expiry']} FUT")
        ltp = await ltp_for(inst)
        if ltp is None:
            raise OrderError(
                f"Angel returned no price for {label}. The basket is not priced and nothing "
                "was filled — MCX may be closed.")
        mult = multiplier(symbol)
        priced.append({
            "leg": leg, "inst": inst, "kind": kind, "side": side, "lots": lots,
            "symbol": symbol, "qty": lots * mult, "multiplier": mult,
            "ltp": ltp, "label": label,
            "contract_value": contract_value(symbol, ltp, lots),
        })
    return priced


def _pos_to_leg(pos: dict, ref: float | None = None, t_years: float = 0.0) -> dict:
    """An open position as a margin leg, at its CURRENT size.

    `qty` comes from the stored quantity, so a position that has been added to margins as
    what it is now rather than as what it was when it opened."""
    inst = pos.get("instrument") or {}
    option_type = inst.get("option_type")
    premium = pos.get("ltp") or pos.get("entry_price") or 0.0
    iv = (solve_iv(premium, ref, inst.get("strike"), t_years, option_type)
          if option_type and ref else None)
    return {"kind": pos.get("instrument_kind", "FUTURE"),
            "option_type": option_type, "strike": inst.get("strike"),
            "qty": pos.get("quantity", 0), "side": pos.get("side", "BUY"),
            "premium": premium, "iv": iv}


async def _open_group(account_id: str, underlying: str, expiry: str) -> list[dict]:
    return [p async for p in commodity_pos_positions_collection.find(
        {"account_id": account_id, "status": "OPEN",
         "underlying_symbol": underlying, "instrument.expiry": expiry})]


async def basket_margin_delta(account_id: str, priced: list[dict]) -> tuple[float, float]:
    """(added_margin, net_premium).

    The added margin is the RISE in this account's netted portfolio margin once every leg
    is added — computed per (underlying, expiry) group, so a spread inside the basket nets
    against itself and against anything already open in the same group.

    Grouping is deliberately per expiry rather than per commodity: `portfolio_margin` takes
    a single time-to-expiry, and pretending a September option and a December future share
    one is how a calendar spread gets under-margined. The cost is that calendars do not net
    here — margin is over-stated for those, which is the safe direction for a gate that
    decides whether an order is allowed."""
    groups: dict[tuple, list[dict]] = {}
    net_premium = 0.0
    for p in priced:
        groups.setdefault((p["symbol"], p["inst"].get("expiry")), []).append(p)
        # A sold leg brings premium in, a bought leg pays it out.
        net_premium += p["ltp"] * p["qty"] * (1 if p["side"] == "SELL" else -1)

    added = 0.0
    for (underlying, expiry), plist in groups.items():
        t = _years_to_expiry(expiry)
        ref, _fut = await future_price(underlying, expiry)
        ref = ref or plist[0]["ltp"]
        existing = await _open_group(account_id, underlying, expiry)
        old_legs = [_pos_to_leg(q, ref, t) for q in existing]
        add_legs = [_leg_from(p["inst"], p["side"], p["qty"], p["ltp"], ref, t) for p in plist]
        before = _margin_for(old_legs, underlying, ref, t)["total"] if old_legs else 0.0
        after = _margin_for(old_legs + add_legs, underlying, ref, t)["total"]
        added += after - before
    # SIGNED, deliberately. A basket that re-hedges an existing position genuinely REDUCES
    # this account's required margin, and clamping that to zero was not a cosmetic choice:
    # `added <= available_cash` is just `deployed + added <= capital + realised` rearranged,
    # so reporting 0 for a delta of -12,331 made the gate compare the WRONG total and refuse
    # a basket that would have left the book solvent.
    return round(added, 2), round(net_premium, 2)


def basket_allowed(added: float, cash: float) -> bool:
    """Can this basket go on? One definition, shared by the estimate and the fill, so the
    number on screen can never disagree with the one that decides.

    Two ways to pass. The obvious one is having the cash for the extra margin. The second —
    asking for no extra margin at all — is not a convenience, it is what stops the desk
    trapping you:

      * margin is re-derived from the live futures price on every fill, so a book can drift
        over-committed without you trading at all; and
      * closing one leg of a hedged pair RAISES the margin on the leg left behind, because
        the leg that was offsetting it is gone.

    Either leaves available cash negative. A gate of `added <= cash` alone then refuses the
    re-hedge that would repair the book, and the account is locked out of the one trade that
    fixes it — while the position it is stuck holding is the riskier of the two. Anything
    that does not increase required margin cannot reduce solvency, so it is always allowed."""
    return added <= cash + 0.01 or added <= 0.01


async def estimate_basket(account_id: str, legs: list[dict]) -> dict:
    """What this basket would cost, and whether the account can carry it."""
    await get_account(account_id)
    priced = await _price_basket(legs)
    added, net_premium = await basket_margin_delta(account_id, priced)
    cash = await available_cash(account_id)
    exposure = sum(p["contract_value"] for p in priced)
    naive = 0.0
    for p in priced:
        t = _years_to_expiry(p["inst"].get("expiry"))
        ref, _f = await future_price(p["symbol"], p["inst"].get("expiry"))
        ref = ref or p["ltp"]
        naive += _margin_for([_leg_from(p["inst"], p["side"], p["qty"], p["ltp"], ref, t)],
                             p["symbol"], ref, t)["total"]

    return {
        "legs": [{
            "label": p["label"], "symbol": p["symbol"], "expiry": p["inst"].get("expiry"),
            "instrument_kind": p["kind"], "strike": p["inst"].get("strike"),
            "option_type": p["inst"].get("option_type"),
            "side": p["side"], "lots": p["lots"], "qty": p["qty"],
            "multiplier": p["multiplier"], "ltp": round(p["ltp"], 2),
            "contract_value": p["contract_value"],
            **spec_doc(p["symbol"]),
        } for p in priced],
        "margin_required": added,
        # Positive when the basket FREES margin — it hedges something already open, so the
        # book needs less held against it after the fill than before.
        "margin_released": round(max(0.0, -added), 2),
        "margin_if_legged_separately": round(naive, 2),
        "hedge_benefit": round(max(0.0, naive - added), 2),
        "net_premium": net_premium,
        "contract_exposure": round(exposure, 2),
        "available_cash": round(cash, 2),
        "cash_after": round(cash - added, 2),
        "affordable": basket_allowed(added, cash),
        "shortfall": round(max(0.0, added - cash), 2) if added > 0.01 else 0.0,
        "note": "Margin is the portfolio figure for the whole basket, so legs that hedge "
                "each other cost less together than apart. Contract exposure is the full "
                "notional you are controlling, which on MCX is many times the margin.",
    }


async def max_lots(account_id: str, legs: list[dict], cap: int = MAX_LOTS_PER_ORDER) -> dict:
    """The largest EQUAL lot count this account can carry across the given legs.

    Not `cash / one_lot_margin`: margin is not linear in lots once legs hedge each other,
    and a short straddle's margin is one side's risk rather than the sum of both, so the
    linear guess is wrong in both directions depending on the basket. This searches the
    real margin model instead.

    Everything that does not depend on SIZE — the reference future price, time to expiry,
    the legs already open in the group — is resolved once and reused, so the search itself
    is pure arithmetic. Prices are fetched once at one lot, not once per probe; the naive
    version re-quoted every leg through Angel on each of ~18 iterations.

    Returns 0 when even one lot does not fit. That is an answer, not an error."""
    await get_account(account_id)
    if not legs:
        raise OrderError("Nothing to size — pick a contract first")
    cash = await available_cash(account_id)
    priced = await _price_basket([{**leg, "lots": 1} for leg in legs])

    groups: dict[tuple, list[dict]] = {}
    for p in priced:
        groups.setdefault((p["symbol"], p["inst"].get("expiry")), []).append(p)

    context: list[tuple] = []
    for (underlying, expiry), plist in groups.items():
        t = _years_to_expiry(expiry)
        ref, _fut = await future_price(underlying, expiry)
        ref = ref or plist[0]["ltp"]
        open_legs = [_pos_to_leg(q, ref, t)
                     for q in await _open_group(account_id, underlying, expiry)]
        before = _margin_for(open_legs, underlying, ref, t)["total"] if open_legs else 0.0
        context.append((underlying, ref, t, open_legs, before, plist))

    def margin_for(n: int) -> float:
        added = 0.0
        for underlying, ref, t, open_legs, before, plist in context:
            add = [_leg_from(p["inst"], p["side"], n * p["multiplier"], p["ltp"], ref, t)
                   for p in plist]
            added += _margin_for(open_legs + add, underlying, ref, t)["total"] - before
        return round(added, 2)

    premium = round(sum(p["ltp"] * p["multiplier"] * (1 if p["side"] == "SELL" else -1)
                        for p in priced), 2)
    shape = {"legs": len(priced), "premium_per_lot": premium,
             "margin_per_lot": margin_for(1), "available_cash": round(cash, 2)}

    # Scan DOWN from the cap for the largest size that passes, rather than binary
    # searching up. Added margin is not monotonic in lots when the basket hedges something
    # already open: it falls as the new legs offset the existing risk, bottoms out near the
    # size that balances it, then climbs once the new side dominates. A binary search
    # assumes one crossing and can settle on the wrong side of that dip. `margin_for` is
    # pure arithmetic on a handful of legs — prices were fetched once, above — so scanning
    # the whole range costs a few milliseconds and is correct whatever the shape.
    for n in range(cap, 0, -1):
        added = margin_for(n)
        if basket_allowed(added, cash):
            note = (f"{n} lot{'s' if n > 1 else ''} per leg "
                    + (f"frees ₹{-added:,.0f}" if added < 0
                       else f"blocks ₹{added:,.0f} of ₹{cash:,.0f}")
                    + (f" (capped at {cap})" if n >= cap else ""))
            # What one more lot would cost, at the SAME prices this answer was computed
            # from. Quoting it from a later snapshot is not a check on the sizer: at a
            # boundary this fine — one gas lot is 0.2% of a 30L book — ordinary tick drift
            # between two quote calls moves it across the line on its own.
            return {**shape, "max_lots": n, "margin": added,
                    "margin_at_next": None if n >= cap else margin_for(n + 1),
                    "reason": note}

    one = margin_for(1)
    return {**shape, "max_lots": 0, "margin": one, "margin_at_next": one,
            "reason": (f"one lot needs ₹{one:,.0f} but only ₹{cash:,.0f} is free"
                       if cash < one else "this account cannot carry one lot here")}


async def execute_basket(account_id: str, legs: list[dict],
                         product_type: str = "MARGIN") -> dict:
    """Fill every leg, or none.

    The affordability gate runs on the WHOLE basket before anything is filled, and the
    per-leg margin check is then switched off deliberately: re-checking each leg as it
    goes would refuse the second half of a spread whose first half had just consumed the
    margin the pair nets away."""
    await get_account(account_id)
    if product_type not in PRODUCT_TYPES:
        raise OrderError(f"product_type must be one of {PRODUCT_TYPES}")

    priced = await _price_basket(legs)
    added, net_premium = await basket_margin_delta(account_id, priced)
    cash = await available_cash(account_id)
    if not basket_allowed(added, cash):
        raise OrderError(
            f"Not enough paper capital. This basket ADDS ₹{added:,.0f} of portfolio margin "
            f"and the account has ₹{cash:,.0f} — short by ₹{added - cash:,.0f}. Reduce lots "
            "or close something first. Nothing was filled.")

    # Buys first, so a protective long is in place before the short it covers. The
    # combined gate has already cleared, but this keeps every intermediate state sane.
    filled = []
    for p in sorted(priced, key=lambda x: 0 if x["side"] == "BUY" else 1):
        base = _build_base_order(account_id, p["inst"], p["kind"], p["symbol"],
                                 p["inst"].get("expiry"), p["side"], p["lots"],
                                 "MARKET", product_type, 0.0)
        filled.append(await _fill(base, p["ltp"], check_margin=False))

    return {"filled": len(filled), "orders": filled, "margin_added": added,
            "net_premium": net_premium}


# --------------------------------------------------------------------------------
# Book maths
# --------------------------------------------------------------------------------


async def _deployed_margin(account_id: str) -> float:
    total = 0.0
    async for p in commodity_pos_positions_collection.find(
            {"account_id": account_id, "status": "OPEN"}, {"margin_used": 1}):
        total += p.get("margin_used") or 0.0
    return total


async def _realized_all_time(account_id: str) -> float:
    total = 0.0
    async for p in commodity_pos_positions_collection.find(
            {"account_id": account_id}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def available_cash(account_id: str) -> float:
    account = await get_account(account_id)
    return (float(account.get("initial_capital") or 0)
            + await _realized_all_time(account_id)
            - await _deployed_margin(account_id))


async def sync_positions() -> int:
    """Mark every open position to the live Angel price, in one batched pass."""
    positions = [p async for p in commodity_pos_positions_collection.find({"status": "OPEN"})]
    if not positions:
        return 0
    tokens = sorted({str(p["instrument"].get("angel_token")) for p in positions
                     if p["instrument"].get("angel_token")})
    prices = await _quote_tokens(tokens)

    updated = 0
    for pos in positions:
        tok = str(pos["instrument"].get("angel_token") or "")
        px = prices.get(tok)
        if not px:
            continue
        direction = 1 if pos["side"] == "BUY" else -1
        pnl = (float(px) - pos["entry_price"]) * pos["quantity"] * direction
        await commodity_pos_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "ltp": round(float(px), 4), "unrealized_pnl": round(pnl, 2),
            "contract_value": contract_value(pos.get("underlying_symbol", ""),
                                             float(px), pos["lots"]),
            "updated_at": _now()}})
        updated += 1
    return updated


async def remargin_account(account_id: str | None = None) -> dict:
    """Re-margin every open group. Repairs books written before margin was recomputed on
    merge, and is safe to run at any time — it only ever restates margin from the current
    positions and the current futures price."""
    q: dict = {"status": "OPEN"}
    if account_id:
        q["account_id"] = account_id
    groups: set[tuple[str, str, str]] = set()
    async for p in commodity_pos_positions_collection.find(
            q, {"account_id": 1, "underlying_symbol": 1, "instrument.expiry": 1}):
        exp = (p.get("instrument") or {}).get("expiry")
        if p.get("underlying_symbol") and exp:
            groups.add((p["account_id"], p["underlying_symbol"], exp))

    out = []
    for acc, underlying, expiry in sorted(groups):
        total = await remargin_group(acc, underlying, expiry)
        out.append({"account_id": acc, "underlying": underlying, "expiry": expiry,
                    "portfolio_margin": round(total, 2)})
    return {"groups": len(out), "detail": out}


async def reset_account(account_id: str) -> dict:
    await get_account(account_id)
    pos = await commodity_pos_positions_collection.delete_many({"account_id": account_id})
    orders = await commodity_pos_orders_collection.delete_many({"account_id": account_id})
    return {"positions_deleted": pos.deleted_count, "orders_deleted": orders.deleted_count}


def _parse_start(value: str | None) -> str:
    """Validate an ISO date. Raises rather than silently falling back — a mistyped start
    date would quietly rebase every per-day number on the page."""
    if not value:
        raise OrderError("A start date is required")
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise OrderError(f"{value!r} is not a date (expected YYYY-MM-DD)") from exc
    if d > date.today():
        raise OrderError("The start date cannot be in the future")
    return d.isoformat()


def _as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.astimezone(IST).date() if v.tzinfo else v.date()
    if isinstance(v, str) and v:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


async def performance(account_id: str, start: str | None = None) -> dict:
    """Profit since a chosen day, and what that averages per day.

    HOW A POSITION IS ATTRIBUTED TO THE WINDOW, because this is the part that can quietly
    mislead. Realised profit counts when the position CLOSED inside the window. Unrealised
    profit counts only for positions OPENED inside it — a trade opened months ago carries
    gains that were earned before the window and would otherwise be credited to it, which
    is exactly how a per-day average gets flattered.

    Those carried gains are not hidden; they are reported separately so the two numbers can
    be seen apart rather than silently blended.
    """
    account = await get_account(account_id)
    initial = float(account.get("initial_capital") or 0)
    start_iso = _parse_start(start or account.get("roi_start_date") or _today())
    start_d = date.fromisoformat(start_iso)
    today = date.today()

    # "Ten days back" reads as ten days, so the span is the gap between the dates. Same
    # day selected means one day, never zero — nothing may be divided by zero here.
    days = max(1, (today - start_d).days)
    # Counted over the SAME span as `days` — the days after the start, up to today. An
    # inclusive count would make trading days exceed calendar days on a one-day window,
    # which inverts the two averages: per-trading-day must never be the smaller number.
    trading_days = max(1, sum(1 for i in range(1, (today - start_d).days + 1)
                              if (start_d + timedelta(days=i)).weekday() < 5))

    realised_in = realised_before = 0.0
    unrealised_in = unrealised_carried = 0.0
    opened_in = closed_in = 0

    async for p in commodity_pos_positions_collection.find(
            {"account_id": account_id},
            {"_id": 0, "status": 1, "opened_at": 1, "closed_at": 1,
             "realized_pnl": 1, "unrealized_pnl": 1}):
        r = float(p.get("realized_pnl") or 0.0)
        u = float(p.get("unrealized_pnl") or 0.0)
        o_d, c_d = _as_date(p.get("opened_at")), _as_date(p.get("closed_at"))
        is_open = p.get("status") == "OPEN"

        if is_open:
            if o_d and o_d >= start_d:
                opened_in += 1
                unrealised_in += u
                realised_in += r          # partial closes on a position opened in-window
            else:
                unrealised_carried += u
                realised_before += r
        else:
            if c_d and c_d >= start_d:
                closed_in += 1
                realised_in += r
            else:
                realised_before += r

    pnl = realised_in + unrealised_in
    per_day = pnl / days
    return {
        "start_date": start_iso,
        "as_of": today.isoformat(),
        "days": days,
        "trading_days": trading_days,
        "initial_capital": initial,
        "realised_in_window": round(realised_in, 2),
        "unrealised_in_window": round(unrealised_in, 2),
        "pnl_in_window": round(pnl, 2),
        "avg_per_day": round(per_day, 2),
        "avg_per_trading_day": round(pnl / trading_days, 2),
        "roi_pct": round(pnl / initial * 100, 4) if initial else None,
        "avg_roi_pct_per_day": round(per_day / initial * 100, 4) if initial else None,
        "opened_in_window": opened_in,
        "closed_in_window": closed_in,
        "carried_unrealised": round(unrealised_carried, 2),
        "realised_before_window": round(realised_before, 2),
        "carried_note": (
            f"{round(unrealised_carried, 2):,.2f} of unrealised profit sits in positions "
            f"opened before {start_iso}. It is excluded from the window, because it was "
            f"not earned inside it."
            if abs(unrealised_carried) > 0.005 else None),
        "note": ("Realised counts where the position CLOSED in the window; unrealised only "
                 "for positions OPENED in it. Per-day is the window profit divided by "
                 f"{days} calendar days ({trading_days} of them trading days)."),
    }


async def summary(account_id: str) -> dict:
    account = await get_account(account_id)
    initial = float(account.get("initial_capital") or 0)

    open_positions = [p async for p in commodity_pos_positions_collection.find(
        {"account_id": account_id, "status": "OPEN"}, {"_id": 0})]
    closed = [p async for p in commodity_pos_positions_collection.find(
        {"account_id": account_id, "status": {"$ne": "OPEN"}}, {"_id": 0}
    ).sort("closed_at", -1).limit(200)]

    unrealized = sum(p.get("unrealized_pnl") or 0.0 for p in open_positions)
    realized = await _realized_all_time(account_id)
    deployed = sum(p.get("margin_used") or 0.0 for p in open_positions)
    exposure = sum(p.get("contract_value") or 0.0 for p in open_positions)

    return {
        "account": account,
        "initial_capital": initial,
        "available_cash": round(initial + realized - deployed, 2),
        "margin_deployed": round(deployed, 2),
        "contract_exposure": round(exposure, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(initial + realized + unrealized, 2),
        "open_count": len(open_positions),
        "closed_count": await commodity_pos_positions_collection.count_documents(
            {"account_id": account_id, "status": {"$ne": "OPEN"}}),
        "open_positions": open_positions,
        "closed_positions": closed,
        "performance": await performance(account_id),
        "exchange": "MCX", "priced_by": "angel",
        "note": "Margin is a local SPAN-lite estimate: Dhan does not cover MCX, so there "
                "is no broker number to quote. Contract exposure is the full notional of "
                "the open book, which for commodities is many times the margin blocked.",
    }


__all__ = [
    "OrderError", "ensure_indexes", "CONTRACT_SPEC", "PRICE_SCAN", "SCAN_FAMILY", "DEFAULT_INITIAL_CAPITAL",
    "multiplier", "contract_value", "spec_doc", "check_specs", "tick_rupees",
    "prime_lotsizes",
    "ensure_default_account", "list_accounts", "get_account", "create_account",
    "delete_account", "max_lots", "performance",
    "edit_account", "underlyings", "future_expiries", "option_expiries",
    "option_chain", "futures_board", "underlying_future", "future_price",
    "estimate_margin", "place_order", "exit_position", "sync_positions",
    "reset_account", "summary", "available_cash",
    "estimate_basket", "execute_basket", "basket_margin_delta", "basket_allowed",
    "atm_strike", "reopen_at_the_money", "reopen_all_at_the_money",
    "MAX_BASKET_LEGS",
    "remargin_group", "remargin_account",
]
