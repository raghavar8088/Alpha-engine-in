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
from datetime import date, datetime, timezone
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
    "SILVER100":  ("100 kg",        "₹ per kg",       100),
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

# SPAN price-scan range per underlying. Energies move multiples of what the metals do, and
# one shared number would over-margin gold or under-margin natural gas.
PRICE_SCAN: dict[str, float] = {
    "GOLD": 0.05, "GOLDM": 0.05, "SILVER": 0.08, "SILVERM": 0.08,
    "CRUDEOIL": 0.09, "NATURALGAS": 0.13, "COPPER": 0.06, "ZINC": 0.06,
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
               "created_at": _now()}
    await commodity_accounts_collection.insert_one(dict(account))
    return account


async def edit_account(account_id: str, name: str | None = None,
                       initial_capital: float | None = None) -> dict:
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
    if changes:
        await commodity_accounts_collection.update_one(
            {"account_id": account_id}, {"$set": changes})
    return await get_account(account_id)


# --------------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------------


async def underlyings() -> list[dict]:
    """The MCX underlyings with at least one unexpired, Angel-mapped contract.

    Reported per underlying rather than per contract, with the counts behind each one, so
    an underlying whose options have not been token-mapped reads as a coverage gap rather
    than as an empty chain later."""
    await prime_lotsizes()
    today = _today()
    out: list[dict] = []
    names = await instruments_collection.distinct(
        "underlying_symbol",
        {"asset_class": {"$in": [FUTURE_CLASS, OPTION_CLASS]}, "expiry": {"$gte": today},
         "angel_token": {"$ne": None}})
    for sym in sorted(n for n in names if n):
        futs = await instruments_collection.count_documents(
            {"asset_class": FUTURE_CLASS, "underlying_symbol": sym,
             "expiry": {"$gte": today}, "angel_token": {"$ne": None}})
        opts = await instruments_collection.count_documents(
            {"asset_class": OPTION_CLASS, "underlying_symbol": sym,
             "expiry": {"$gte": today}, "angel_token": {"$ne": None}})
        out.append({"symbol": sym, "futures": futs, "options": opts,
                    "has_options": opts > 0, **spec_doc(sym)})
    return out


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
        raise OrderError(
            f"No Angel-mapped {symbol} option contracts for {expiry}. The chain is built "
            "from the instrument master, so this is a token-mapping gap, not a quiet market.")

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
    return PRICE_SCAN.get((underlying or "").upper(), DEFAULT_SCAN)


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


async def reset_account(account_id: str) -> dict:
    await get_account(account_id)
    pos = await commodity_pos_positions_collection.delete_many({"account_id": account_id})
    orders = await commodity_pos_orders_collection.delete_many({"account_id": account_id})
    return {"positions_deleted": pos.deleted_count, "orders_deleted": orders.deleted_count}


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
        "exchange": "MCX", "priced_by": "angel",
        "note": "Margin is a local SPAN-lite estimate: Dhan does not cover MCX, so there "
                "is no broker number to quote. Contract exposure is the full notional of "
                "the open book, which for commodities is many times the margin blocked.",
    }


__all__ = [
    "OrderError", "ensure_indexes", "CONTRACT_SPEC", "PRICE_SCAN", "DEFAULT_INITIAL_CAPITAL",
    "multiplier", "contract_value", "spec_doc", "check_specs", "tick_rupees",
    "prime_lotsizes",
    "ensure_default_account", "list_accounts", "get_account", "create_account",
    "edit_account", "underlyings", "future_expiries", "option_expiries",
    "option_chain", "futures_board", "underlying_future", "future_price",
    "estimate_margin", "place_order", "exit_position", "sync_positions",
    "reset_account", "summary", "available_cash",
]
