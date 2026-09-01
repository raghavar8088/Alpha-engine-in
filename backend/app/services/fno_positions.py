"""F&O Positions module — a user-initiated paper trading desk for Index/Stock
OPTIONS and FUTURES, separate from the equity-only Manual Positions desk (see
app.services.manual_positions, whose capital-pool/fill/exit shape this mirrors).

The user picks an underlying (index or F&O-enabled stock), an expiry, and for
options a strike+CE/PE — resolved to a real Dhan security_id from the
`instruments` collection (asset_class INDEX_OPTION/EQUITY_OPTION/INDEX_FUTURE/
EQUITY_FUTURE) — then buys/sells in lots at the live premium/futures price.
Margin comes from Dhan's own /margincalculator, same as Manual Positions; no
leverage or premium is invented locally.

NOTE: stock OPTIONS (OPTSTK) are excluded from the instrument universe by
market-data-service/universe.py (deferred there to keep the FNO row count
down) — only stock FUTURES are loaded today, so the option chain picker only
lists index underlyings until that's re-enabled and universe.py is re-run.
"""

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    fno_accounts_collection,
    fno_orders_collection,
    fno_positions_collection,
    instruments_collection,
)
from app.services.broker_data import get_ltp
from app.services.dhan_client import DhanAPIError, DhanClient
from app.services.fno_margin import portfolio_margin, solve_iv
from app.services.stock_options import batched_ltp
from app.services.angel_option_chain import (
    ChainError,
    option_chain as angel_option_chain,
    option_expiries as angel_option_expiries,
)

DEFAULT_INITIAL_CAPITAL = float(os.getenv("FNO_POSITIONS_INITIAL_CAPITAL", "10000000"))  # ₹1 crore
PRODUCT_TYPES = ("INTRADAY", "MARGIN")
OPTION_CLASSES = ("INDEX_OPTION", "EQUITY_OPTION")
FUTURE_CLASSES = ("INDEX_FUTURE", "EQUITY_FUTURE")
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}


class OrderError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------
# Accounts — multiple independent named paper accounts, each with its own capital
# pool, mirroring app.services.manual_positions. Every position/order belongs to
# exactly one account_id; a "Default" account is auto-created and pre-existing
# account-less data migrated into it the first time accounts are listed, so this
# upgrade never loses the old single-book data.
# --------------------------------------------------------------------------------


async def ensure_default_account() -> dict:
    existing = await fno_accounts_collection.find_one(sort=[("created_at", 1)])
    if existing is not None:
        return existing
    account = {
        "account_id": uuid4().hex[:12], "name": "Default",
        "initial_capital": DEFAULT_INITIAL_CAPITAL, "created_at": _now(),
    }
    await fno_accounts_collection.insert_one(account)
    await fno_positions_collection.update_many(
        {"account_id": {"$exists": False}}, {"$set": {"account_id": account["account_id"]}}
    )
    await fno_orders_collection.update_many(
        {"account_id": {"$exists": False}}, {"$set": {"account_id": account["account_id"]}}
    )
    account.pop("_id", None)
    return account


async def list_accounts() -> list[dict]:
    await ensure_default_account()
    cursor = fno_accounts_collection.find({}, {"_id": 0}).sort("created_at", 1)
    return [d async for d in cursor]


async def get_account(account_id: str) -> dict:
    doc = await fno_accounts_collection.find_one({"account_id": account_id}, {"_id": 0})
    if doc is None:
        raise OrderError(f"Unknown account {account_id}")
    return doc


async def create_account(name: str, initial_capital: float | None = None) -> dict:
    name = name.strip()
    if not name:
        raise OrderError("Account name cannot be empty")
    if await fno_accounts_collection.find_one({"name": name}):
        raise OrderError(f'An account named "{name}" already exists')
    account = {
        "account_id": uuid4().hex[:12], "name": name,
        "initial_capital": initial_capital if initial_capital and initial_capital > 0 else DEFAULT_INITIAL_CAPITAL,
        # The day the per-day averages are measured from.
        "roi_start_date": date.today().isoformat(),
        "created_at": _now(),
    }
    await fno_accounts_collection.insert_one(account)
    account.pop("_id", None)
    return account


async def edit_account(account_id: str, name: str | None = None,
                       initial_capital: float | None = None,
                       roi_start_date: str | None = None) -> dict:
    """Rename an account and/or change its starting capital. Editing the balance
    changes only the base capital pool — realized/unrealized P&L and every open
    position are untouched, so available_cash simply re-derives from the new base
    (initial_capital + realized - deployed). A brand-new account defaults to ₹1 cr;
    here the user can set any positive figure at any time."""
    account = await get_account(account_id)
    changes: dict = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise OrderError("Account name cannot be empty")
        clash = await fno_accounts_collection.find_one({"name": name, "account_id": {"$ne": account_id}})
        if clash is not None:
            raise OrderError(f'An account named "{name}" already exists')
        changes["name"] = name
    if roi_start_date is not None:
        changes["roi_start_date"] = _parse_roi_start(roi_start_date)
    if initial_capital is not None:
        if initial_capital <= 0:
            raise OrderError("Account balance must be a positive number")
        changes["initial_capital"] = float(initial_capital)
    if not changes:
        raise OrderError("Nothing to update — provide a new name and/or balance")
    await fno_accounts_collection.update_one({"account_id": account_id}, {"$set": changes})
    return {**account, **changes}


async def delete_account(account_id: str) -> dict:
    """Remove a paper account and everything in it.

    Refuses while positions are still open: `sync_positions` walks every OPEN row on a
    timer and would keep marking them to market against a book that no longer exists.
    Close first, then delete. Also refuses the last account, where Reset is what is meant."""
    account = await get_account(account_id)
    open_count = await fno_positions_collection.count_documents(
        {"account_id": account_id, "status": "OPEN"})
    if open_count:
        raise OrderError(
            f"{account['name']} still has {open_count} open position"
            f"{'s' if open_count > 1 else ''}. Close them first — deleting the account "
            "would leave them being marked to market against a book that is gone.")
    if await fno_accounts_collection.count_documents({}) <= 1:
        raise OrderError(
            "This is the only paper account. Create another before deleting this one, "
            "or use Reset to empty it instead.")
    pos = await fno_positions_collection.delete_many({"account_id": account_id})
    orders = await fno_orders_collection.delete_many({"account_id": account_id})
    await fno_accounts_collection.delete_one({"account_id": account_id})
    return {"deleted": account["name"], "closed_positions_removed": pos.deleted_count,
            "orders_removed": orders.deleted_count}


async def _underlying_instrument(symbol: str) -> dict:
    doc = await instruments_collection.find_one({
        "symbol": symbol.upper(),
        "asset_class": "INDEX" if symbol.upper() in INDEX_UNDERLYINGS else "EQUITY",
    })
    if doc is None:
        raise OrderError(f"{symbol} has no F&O underlying instrument on file")
    return doc


async def underlyings() -> list[dict]:
    """Index underlyings (whitelisted) plus equities that have at least one
    stock-futures contract loaded — the current tradable F&O universe."""
    index_docs = await instruments_collection.find(
        {"asset_class": "INDEX"}, {"_id": 0, "symbol": 1, "name": 1}
    ).to_list(None)
    stock_symbols = await instruments_collection.distinct("underlying_symbol", {"asset_class": "EQUITY_FUTURE"})
    stock_docs = await instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": stock_symbols}}, {"_id": 0, "symbol": 1, "name": 1}
    ).to_list(None) if stock_symbols else []
    return [{**d, "kind": "INDEX"} for d in index_docs] + [{**d, "kind": "EQUITY"} for d in stock_docs]


async def option_expiries(dhan: DhanClient, symbol: str) -> list[str]:
    # Off Dhan: expiries come from the instrument master (no broker call, no Data-API
    # subscription needed). `dhan` is kept for signature compatibility and ignored.
    return await angel_option_expiries(symbol)


async def option_chain(dhan: DhanClient, symbol: str, expiry: str) -> dict:
    # Off Dhan: the chain is assembled from Angel-One FULL quotes (Dhan's option-chain
    # endpoint needs a paid Data-API subscription this account doesn't have).
    try:
        return await angel_option_chain(symbol, expiry)
    except ChainError as exc:
        raise OrderError(exc.detail)


async def future_expiries(symbol: str) -> list[str]:
    today = _now().date().isoformat()
    rows = await instruments_collection.distinct(
        "expiry", {"underlying_symbol": symbol.upper(), "asset_class": {"$in": list(FUTURE_CLASSES)}}
    )
    return sorted(e for e in rows if e and e >= today)


async def _resolve_option(symbol: str, expiry: str, strike: float, option_type: str) -> dict:
    doc = await instruments_collection.find_one({
        "underlying_symbol": symbol.upper(), "expiry": expiry, "strike": strike,
        "option_type": option_type.upper(), "asset_class": {"$in": list(OPTION_CLASSES)},
    })
    if doc is None:
        raise OrderError(f"No option contract for {symbol} {expiry} {strike:g}{option_type.upper()} on file")
    return doc


async def _resolve_future(symbol: str, expiry: str) -> dict:
    doc = await instruments_collection.find_one({
        "underlying_symbol": symbol.upper(), "expiry": expiry, "asset_class": {"$in": list(FUTURE_CLASSES)},
    })
    if doc is None:
        raise OrderError(f"No futures contract for {symbol} expiring {expiry}")
    return doc


async def _ltp_with_source(dhan: DhanClient, security_id: str, exchange_segment: str) -> tuple[float | None, str]:
    """Live price plus which broker produced it — falls back to Angel One when Dhan
    can't answer, so a rotated-out Dhan token no longer blinds position marking."""
    return await get_ltp(dhan, security_id, exchange_segment)


async def _ltp(dhan: DhanClient, security_id: str, exchange_segment: str) -> float | None:
    price, _source = await get_ltp(dhan, security_id, exchange_segment)
    return price




# --------------------------------------------------------------------------------
# Portfolio (SPAN-lite) margin — the account's deployed margin is NOT the sum of each
# leg's standalone margin; it is the netted, hedge-aware figure computed per
# (underlying, expiry) group by app.services.fno_margin. So a long option that caps a
# short's loss reduces the whole account's blocked capital, exactly like a real broker.
# Each position still stores its OWN standalone margin (margin_used) for display; the
# gap between the sum of those and the netted deployed figure is the hedge benefit.
# --------------------------------------------------------------------------------


def _years_to_expiry(expiry: str | None) -> float:
    if not expiry:
        return 30 / 365.0
    try:
        days = (date.fromisoformat(expiry) - _now().date()).days
    except (ValueError, TypeError):
        return 30 / 365.0
    return max(days, 0.5) / 365.0


def _pos_to_leg(pos: dict) -> dict:
    inst = pos.get("instrument", {})
    return {
        "kind": pos.get("instrument_kind", "OPTION"),
        "option_type": inst.get("option_type"),
        "strike": inst.get("strike"),
        "qty": pos.get("quantity", 0),
        "side": pos.get("side", "BUY"),
        "premium": pos.get("avg_price", 0.0),
        "iv": pos.get("iv"),
    }


def _same_contract(pos: dict, inst: dict) -> bool:
    pi = pos.get("instrument", {})
    return (
        pi.get("strike") == inst.get("strike")
        and pi.get("option_type") == inst.get("option_type")
        and pi.get("expiry") == inst.get("expiry")
    )


def _group_spot(positions: list[dict]) -> float:
    """A spot for the (underlying, expiry) group: the freshest one stored on any leg
    (all share an underlying), else an ATM proxy from the strikes, else a future's
    price — so margin can still be estimated when a live spot is momentarily absent."""
    spots = [p.get("spot") for p in positions if p.get("spot")]
    if spots:
        return float(max(spots))
    strikes = [p["instrument"].get("strike") for p in positions if p.get("instrument", {}).get("strike")]
    if strikes:
        return float(sum(strikes) / len(strikes))
    prices = [p.get("avg_price") for p in positions if p.get("avg_price")]
    return float(sum(prices) / len(prices)) if prices else 0.0


async def _underlying_spot(dhan: DhanClient, symbol: str, fallback: float | None = None) -> float | None:
    try:
        inst = await _underlying_instrument(symbol)
        spot = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        if spot and spot > 0:
            return float(spot)
    except Exception:
        pass
    return fallback


async def _group_positions(account_id: str, symbol: str | None, expiry: str | None) -> list[dict]:
    return [
        p async for p in fno_positions_collection.find({
            "account_id": account_id, "status": "OPEN",
            "instrument.underlying_symbol": symbol, "instrument.expiry": expiry,
        })
    ]


async def _deployed_margin(account_id: str) -> float:
    """Netted portfolio margin: group every open position by (underlying, expiry) and
    sum each group's SPAN-lite portfolio margin. Hedges within a group net."""
    groups: dict[tuple, list[dict]] = {}
    async for p in fno_positions_collection.find({"account_id": account_id, "status": "OPEN"}):
        inst = p.get("instrument", {})
        groups.setdefault((inst.get("underlying_symbol"), inst.get("expiry")), []).append(p)
    total = 0.0
    for (_symbol, expiry), positions in groups.items():
        spot = _group_spot(positions)
        legs = [_pos_to_leg(p) for p in positions]
        total += portfolio_margin(legs, spot, _years_to_expiry(expiry))["total"]
    return round(total, 2)


async def _standalone_margin_total(account_id: str) -> float:
    """Sum of each open leg's OWN standalone margin (no netting) — the pre-hedge
    figure; deployed subtracted from this is the account's total hedge benefit."""
    total = 0.0
    async for p in fno_positions_collection.find({"account_id": account_id, "status": "OPEN"}, {"margin_used": 1}):
        total += p.get("margin_used") or 0.0
    return round(total, 2)


async def _realized_pnl_all_time(account_id: str) -> float:
    total = 0.0
    async for p in fno_positions_collection.find({"account_id": account_id}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def available_cash(account_id: str) -> float:
    account = await get_account(account_id)
    deployed = await _deployed_margin(account_id)
    realized = await _realized_pnl_all_time(account_id)
    return account["initial_capital"] + realized - deployed


async def top_movers(dhan: DhanClient, limit: int = 10) -> dict:
    """Scans the nearest expiry's chain for every whitelisted index and ranks
    CE/PE legs by intraday % change off the previous close — the closest honest
    proxy for "today's top performing options" without a dedicated Dhan
    FNO-gainers endpoint."""
    calls, puts = [], []
    for symbol in INDEX_UNDERLYINGS:
        try:
            exps = await option_expiries(dhan, symbol)
            if not exps:
                continue
            chain = await option_chain(dhan, symbol, exps[0])
        except OrderError:
            continue
        for row in chain["strikes"]:
            for side, bucket in (("ce", calls), ("pe", puts)):
                leg = row[side]
                ltp, prev = leg.get("last_price") or 0, leg.get("previous_close_price") or 0
                if ltp <= 0 or prev <= 0:
                    continue
                bucket.append({
                    "symbol": symbol, "expiry": exps[0], "strike": row["strike"],
                    "option_type": side.upper(), "ltp": ltp,
                    "change_pct": round((ltp / prev - 1) * 100, 2),
                    "volume": leg.get("volume") or 0, "oi": leg.get("oi") or 0,
                })
    calls.sort(key=lambda r: r["change_pct"], reverse=True)
    puts.sort(key=lambda r: r["change_pct"], reverse=True)
    return {"top_calls": calls[:limit], "top_puts": puts[:limit]}


async def estimate_margin(
    dhan: DhanClient, security_id: str, exchange_segment: str, transaction_type: str,
    quantity: int, product_type: str, price: float,
) -> dict:
    """Standalone SPAN-lite margin for a single leg (the same engine the fill gate and
    deployed margin use). Contract details are resolved from the bare security_id."""
    contract = await instruments_collection.find_one(
        {"security_id": security_id, "exchange_segment": exchange_segment},
        {"strike": 1, "option_type": 1, "underlying_symbol": 1, "expiry": 1},
    ) or {}
    underlying = contract.get("underlying_symbol")
    t = _years_to_expiry(contract.get("expiry"))
    spot = (await _underlying_spot(dhan, underlying, fallback=contract.get("strike") or price)) if underlying else (contract.get("strike") or price)
    iv = solve_iv(price, spot, contract.get("strike"), t, contract.get("option_type")) if contract.get("option_type") else None
    leg = {
        "kind": "OPTION" if contract.get("option_type") else "FUTURE",
        "option_type": contract.get("option_type"), "strike": contract.get("strike"),
        "qty": quantity, "side": transaction_type, "premium": price, "iv": iv,
    }
    m = portfolio_margin([leg], spot or (contract.get("strike") or price), t)
    return {
        "margin_required": m["total"], "span": m["span"], "exposure": m["exposure"],
        "notional_value": round(price * quantity, 2), "source": "span_lite",
    }


async def _resolve_contract(instrument_kind: str, symbol: str, expiry: str, strike: float | None, option_type: str | None) -> dict:
    if instrument_kind == "OPTION":
        if strike is None or option_type not in ("CE", "PE"):
            raise OrderError("Options need a strike and option_type (CE/PE)")
        return await _resolve_option(symbol, expiry, strike, option_type)
    if instrument_kind == "FUTURE":
        return await _resolve_future(symbol, expiry)
    raise OrderError("instrument_kind must be OPTION or FUTURE")


def _build_base_order(
    account_id: str, inst: dict, instrument_kind: str, symbol: str, expiry: str, transaction_type: str,
    lots: int, order_type: str, product_type: str, limit_price: float, strike: float | None, option_type: str | None,
) -> dict:
    now = _now()
    label = f"{symbol} {expiry} {strike:g}{option_type}" if instrument_kind == "OPTION" else f"{symbol} {expiry} FUT"
    return {
        "order_id": f"FNO-{uuid4().hex[:12]}", "account_id": account_id, "symbol": inst["symbol"],
        "display_name": label, "instrument_kind": instrument_kind,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
            "tick_size": inst.get("tick_size", 0.05), "underlying_symbol": inst.get("underlying_symbol"),
            "expiry": inst.get("expiry"), "strike": inst.get("strike"), "option_type": inst.get("option_type"),
        },
        "transaction_type": transaction_type, "lots": lots, "quantity": lots * inst.get("lot_size", 1),
        "order_type": order_type, "limit_price": limit_price if order_type == "LIMIT" else None,
        "product_type": product_type, "placed_at": now, "updated_at": now,
    }


async def place_order(
    dhan: DhanClient, *, account_id: str, instrument_kind: str, symbol: str, expiry: str, transaction_type: str,
    lots: int, order_type: str, product_type: str, strike: float | None = None,
    option_type: str | None = None, limit_price: float = 0.0,
) -> dict:
    await get_account(account_id)  # 404s cleanly if the account_id is bogus
    if lots < 1:
        raise OrderError("Lots must be at least 1")
    if product_type not in PRODUCT_TYPES:
        raise OrderError(f"product_type must be one of {PRODUCT_TYPES}")
    if order_type == "LIMIT" and limit_price <= 0:
        raise OrderError("Limit orders need a positive limit_price")

    inst = await _resolve_contract(instrument_kind, symbol, expiry, strike, option_type)
    ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline?) — cannot price this order")

    base_order = _build_base_order(
        account_id, inst, instrument_kind, symbol, expiry, transaction_type, lots, order_type, product_type,
        limit_price, strike, option_type,
    )

    marketable = (
        order_type == "MARKET"
        or (transaction_type == "BUY" and ltp <= limit_price)
        or (transaction_type == "SELL" and ltp >= limit_price)
    )
    if not marketable:
        doc = {**base_order, "status": "PENDING", "fill_price": None, "filled_at": None,
               "margin_used": None, "leverage": None}
        await fno_orders_collection.insert_one(doc)
        doc.pop("_id", None)
        return doc

    fill_price = ltp if order_type == "MARKET" else limit_price
    return await _fill(dhan, base_order, fill_price)


async def _fill(dhan: DhanClient, base_order: dict, fill_price: float, check_margin: bool = True) -> dict:
    inst = base_order["instrument"]
    account_id = base_order["account_id"]
    transaction_type, quantity, product_type = base_order["transaction_type"], base_order["quantity"], base_order["product_type"]
    contract_key = {"account_id": account_id, "symbol": base_order["symbol"], "instrument.expiry": inst.get("expiry"),
                     "instrument.strike": inst.get("strike"), "instrument.option_type": inst.get("option_type")}

    existing = await fno_positions_collection.find_one({**contract_key, "product_type": product_type, "status": "OPEN"})
    lot_size = inst.get("lot_size", 1) or 1

    # Positions net per contract+product, the way a real broker book does: an order
    # on the same side as the open position adds to it, the opposite side reduces or
    # closes it, and with nothing open either side may open one — BUY goes long,
    # SELL opens a short (option writing). Legacy docs predate `side`, so any
    # position without it is a long.
    existing_side = existing.get("side", "BUY") if existing else None
    opening = existing is None or existing_side == transaction_type

    # SPAN-lite margin context for this contract's (underlying, expiry) group.
    underlying = inst.get("underlying_symbol") or base_order["symbol"]
    expiry = inst.get("expiry")
    t_years = _years_to_expiry(expiry)
    spot = await _underlying_spot(dhan, underlying, fallback=inst.get("strike") or fill_price)

    if opening:
        side = transaction_type
        new_qty = (existing["quantity"] + quantity) if existing else quantity
        new_avg = (
            (existing["quantity"] * existing["avg_price"] + quantity * fill_price) / new_qty
            if existing else fill_price
        )
        group = await _group_positions(account_id, underlying, expiry)
        group_spot = spot or _group_spot(group) or (inst.get("strike") or fill_price)
        iv = solve_iv(new_avg, group_spot, inst.get("strike"), t_years, inst["option_type"]) if inst.get("option_type") else None
        proj_leg = {
            "kind": base_order["instrument_kind"], "option_type": inst.get("option_type"),
            "strike": inst.get("strike"), "qty": new_qty, "side": side, "premium": new_avg, "iv": iv,
        }
        # Group-incremental balance gate: block only what this order ADDS to the
        # account's NETTED portfolio margin — so a hedge (which lowers the group
        # margin) is always allowed, and only genuinely risk-increasing orders can be
        # capital-constrained. This is the hedge-aware version of the old per-leg check.
        old_legs = [_pos_to_leg(p) for p in group]
        new_legs = [_pos_to_leg(p) for p in group if not _same_contract(p, inst)] + [proj_leg]
        old_group = portfolio_margin(old_legs, group_spot, t_years)["total"]
        new_group = portfolio_margin(new_legs, group_spot, t_years)["total"]
        added = new_group - old_group
        if check_margin:
            # Skipped when a basket has already gated the WHOLE set of legs together —
            # otherwise a naked short would be rejected before its hedge leg is added.
            cash = await available_cash(account_id)
            if added > cash + 0.01:
                raise OrderError(
                    f"Insufficient paper capital: this order adds ₹{added:,.2f} of portfolio margin "
                    f"(net of hedges), only ₹{cash:,.2f} available in this account"
                )
        standalone = portfolio_margin([proj_leg], group_spot, t_years)["total"]

        if existing is None:
            position = {
                "position_id": uuid4().hex[:12], "account_id": account_id, "symbol": base_order["symbol"],
                "display_name": base_order["display_name"], "instrument_kind": base_order["instrument_kind"],
                "instrument": inst, "product_type": product_type, "side": side,
                "lots": base_order["lots"], "quantity": quantity, "avg_price": fill_price,
                "margin_used": standalone, "margin_source": "span_lite", "leverage": None,
                "iv": iv, "spot": group_spot,
                "ltp": fill_price, "ltp_source": "dhan_quote",
                "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": 0.0,
                "status": "OPEN", "opened_at": _now(), "updated_at": _now(), "closed_at": None,
            }
            await fno_positions_collection.insert_one(position)
            position.pop("_id", None)
        else:
            await fno_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"quantity": new_qty, "lots": new_qty // lot_size, "avg_price": round(new_avg, 4),
                          "margin_used": standalone, "margin_source": "span_lite", "leverage": None,
                          "iv": iv, "spot": group_spot, "updated_at": _now()}},
            )
            position = await fno_positions_collection.find_one({"_id": existing["_id"]})
            position.pop("_id", None)

    else:  # opposite side — reduce or close the open position
        if existing["quantity"] < quantity:
            verb = "sell" if transaction_type == "SELL" else "buy back"
            raise OrderError(f"Cannot {verb} {quantity} {base_order['display_name']} — only {existing['quantity']} open")
        # A long earns (exit - entry); a short earns (entry - exit).
        direction = 1 if existing_side == "BUY" else -1
        realized = round((fill_price - existing["avg_price"]) * quantity * direction, 2)
        remaining_qty = existing["quantity"] - quantity
        group_spot = spot or existing.get("spot") or (inst.get("strike") or fill_price)
        if remaining_qty == 0:
            await fno_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "status": "CLOSED", "quantity": 0, "lots": 0, "margin_used": 0.0,
                    "realized_pnl": round(existing.get("realized_pnl", 0.0) + realized, 2),
                    "unrealized_pnl": 0.0, "ltp": fill_price, "updated_at": _now(), "closed_at": _now(),
                }},
            )
        else:
            remain_leg = {
                "kind": existing.get("instrument_kind", "OPTION"), "option_type": inst.get("option_type"),
                "strike": inst.get("strike"), "qty": remaining_qty, "side": existing_side,
                "premium": existing["avg_price"], "iv": existing.get("iv"),
            }
            standalone = portfolio_margin([remain_leg], group_spot, t_years)["total"]
            await fno_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "quantity": remaining_qty, "lots": remaining_qty // lot_size, "margin_used": standalone,
                    "margin_source": "span_lite",
                    "realized_pnl": round(existing.get("realized_pnl", 0.0) + realized, 2), "updated_at": _now(),
                }},
            )
        position = await fno_positions_collection.find_one({"_id": existing["_id"]})
        position.pop("_id", None)

    order_doc = {**base_order, "status": "FILLED", "fill_price": fill_price, "filled_at": _now(),
                 "margin_used": position.get("margin_used"), "leverage": position.get("leverage")}
    await fno_orders_collection.insert_one(order_doc)
    order_doc.pop("_id", None)
    order_doc["position"] = position
    return order_doc


async def exit_position(dhan: DhanClient, account_id: str, position_id: str, lots: int | None = None) -> dict:
    position = await fno_positions_collection.find_one(
        {"position_id": position_id, "account_id": account_id, "status": "OPEN"}
    )
    if position is None:
        raise OrderError("Position not found (in this account) or already closed")
    lot_size = position["instrument"].get("lot_size", 1) or 1
    qty = (lots * lot_size) if lots else position["quantity"]
    if qty > position["quantity"]:
        raise OrderError(f"Cannot exit {qty} — position only holds {position['quantity']}")

    inst = position["instrument"]
    base_order = {
        "order_id": f"FNO-{uuid4().hex[:12]}", "account_id": account_id, "symbol": position["symbol"], "display_name": position["display_name"],
        "instrument_kind": position["instrument_kind"], "instrument": inst,
        # Exiting means trading the opposite side: sell to close a long, buy back a short.
        "transaction_type": "BUY" if position.get("side", "BUY") == "SELL" else "SELL",
        "lots": qty // lot_size, "quantity": qty, "order_type": "MARKET",
        "limit_price": None, "product_type": position["product_type"], "placed_at": _now(), "updated_at": _now(),
    }
    ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline?) — cannot exit right now")
    return await _fill(dhan, base_order, ltp)


# --------------------------------------------------------------------------------
# Basket orders — build several legs (a vertical spread, an iron condor, a custom
# multi-leg) and place them as ONE order, gated on the COMBINED netted margin. This
# is what lets a condor go on in a single click at its true small hedged margin
# instead of being blocked leg-by-leg on the naked short before its wing is added.
# --------------------------------------------------------------------------------


async def _price_basket(dhan: DhanClient, legs: list[dict]) -> list[dict]:
    """Resolve + live-price every leg, failing the WHOLE basket if any leg can't be
    resolved or priced — a basket goes on complete or not at all."""
    if not legs:
        raise OrderError("Basket is empty")
    if len(legs) > 10:
        raise OrderError("A basket can hold at most 10 legs")
    priced = []
    for leg in legs:
        kind = str(leg.get("instrument_kind", "OPTION")).upper()
        side = str(leg.get("transaction_type", "")).upper()
        lots = int(leg.get("lots") or 0)
        if lots < 1:
            raise OrderError("Every basket leg needs at least 1 lot")
        if side not in ("BUY", "SELL"):
            raise OrderError("Each leg's transaction_type must be BUY or SELL")
        inst = await _resolve_contract(kind, leg["symbol"], leg["expiry"], leg.get("strike"), leg.get("option_type"))
        ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        label = (
            f"{leg['symbol']} {leg['expiry']} {float(leg['strike']):g}{leg.get('option_type')}"
            if kind == "OPTION" else f"{leg['symbol']} {leg['expiry']} FUT"
        )
        if ltp is None:
            raise OrderError(f"Live quote unavailable for {label} — cannot price the basket right now")
        priced.append({
            "leg": leg, "inst": inst, "kind": kind, "side": side, "lots": lots,
            "qty": lots * inst.get("lot_size", 1), "ltp": ltp, "label": label,
        })
    return priced


async def _basket_margin_delta(dhan: DhanClient, account_id: str, priced: list[dict]) -> tuple[float, float]:
    """(added_margin, net_premium). added_margin = the rise in the account's NETTED
    portfolio margin from adding every leg, summed across (underlying, expiry) groups
    — so hedges inside the basket (and against existing positions) net. net_premium is
    the credit(+) received / debit(-) paid to open the basket."""
    groups: dict[tuple, list[dict]] = {}
    net_premium = 0.0
    for p in priced:
        inst = p["inst"]
        groups.setdefault((inst.get("underlying_symbol"), inst.get("expiry")), []).append(p)
        net_premium += p["ltp"] * p["qty"] * (1 if p["side"] == "SELL" else -1)
    added = 0.0
    for (underlying, expiry), plist in groups.items():
        t = _years_to_expiry(expiry)
        current = await _group_positions(account_id, underlying, expiry)
        old_legs = [_pos_to_leg(q) for q in current]
        spot = await _underlying_spot(
            dhan, underlying,
            fallback=_group_spot(current) or plist[0]["inst"].get("strike") or plist[0]["ltp"],
        )
        add_legs = []
        for p in plist:
            ot = p["inst"].get("option_type")
            add_legs.append({
                "kind": p["kind"], "option_type": ot, "strike": p["inst"].get("strike"),
                "qty": p["qty"], "side": p["side"], "premium": p["ltp"],
                "iv": solve_iv(p["ltp"], spot, p["inst"].get("strike"), t, ot) if ot else None,
            })
        old = portfolio_margin(old_legs, spot, t)["total"]
        new = portfolio_margin(old_legs + add_legs, spot, t)["total"]
        added += new - old
    # SIGNED — see `_basket_allowed` below. Clamping a margin-reducing basket to zero made
    # the gate compare the wrong total and refuse a re-hedge that leaves the book solvent.
    return round(added, 2), round(net_premium, 2)


def _basket_allowed(added: float, cash: float) -> bool:
    """Fund the extra margin, OR ask for no extra margin at all.

    The second clause stops the desk trapping you. Closing one leg of a hedged pair raises
    the margin on the leg left behind — the offset is gone — which can push available cash
    negative without a single new trade. Gating only on `added <= cash` then refuses the
    re-hedge that would repair the book. A basket that does not increase required margin
    cannot reduce solvency, so it always goes on."""
    return added <= cash + 0.01 or added <= 0.01


async def estimate_basket_margin(dhan: DhanClient, account_id: str, legs: list[dict], product_type: str = "MARGIN") -> dict:
    await get_account(account_id)
    priced = await _price_basket(dhan, legs)
    added, net_premium = await _basket_margin_delta(dhan, account_id, priced)
    cash = await available_cash(account_id)
    return {
        "margin_required": added,
        "margin_released": round(max(0.0, -added), 2),
        "net_premium": net_premium,
        "available_cash": round(cash, 2),
        "affordable": _basket_allowed(added, cash),
        "legs": [
            {"label": p["label"], "side": p["side"], "lots": p["lots"], "qty": p["qty"], "ltp": round(p["ltp"], 2)}
            for p in priced
        ],
    }


async def execute_basket(dhan: DhanClient, account_id: str, legs: list[dict], product_type: str = "MARGIN") -> dict:
    await get_account(account_id)
    if product_type not in PRODUCT_TYPES:
        raise OrderError(f"product_type must be one of {PRODUCT_TYPES}")
    priced = await _price_basket(dhan, legs)
    added, net_premium = await _basket_margin_delta(dhan, account_id, priced)
    cash = await available_cash(account_id)
    if not _basket_allowed(added, cash):
        raise OrderError(
            f"Insufficient paper capital: this basket adds ₹{added:,.2f} of portfolio margin "
            f"(net of hedges), only ₹{cash:,.2f} available in this account"
        )
    # Fill BUYS first so any protective long is in place before its short — keeps every
    # intermediate book state within margin, even though the combined gate already cleared.
    positions = []
    for p in sorted(priced, key=lambda x: 0 if x["side"] == "BUY" else 1):
        base_order = _build_base_order(
            account_id, p["inst"], p["kind"], p["leg"]["symbol"], p["leg"]["expiry"], p["side"],
            p["lots"], "MARKET", product_type, 0.0, p["inst"].get("strike"), p["inst"].get("option_type"),
        )
        result = await _fill(dhan, base_order, p["ltp"], check_margin=False)
        positions.append(result["position"])
    return {"filled": len(positions), "positions": positions, "margin_added": added, "net_premium": net_premium}



# Hard ceiling on single-token Angel calls per sync, so one rate-limited sweep can
# never cascade into hundreds more.
MAX_SINGLE_QUOTE_FALLBACKS = 25


MAX_LOTS_PER_ORDER = int(os.getenv("FNO_MAX_LOTS_PER_ORDER", "500"))


async def max_lots(dhan: DhanClient, account_id: str, legs: list[dict],
                   cap: int = MAX_LOTS_PER_ORDER) -> dict:
    """The largest EQUAL lot count this account can carry across the given legs.

    Not `cash / one_lot_margin`: margin is not linear in lots once legs hedge each other,
    and a short straddle is margined as one side's risk rather than the sum of both, so
    the linear guess is wrong in both directions depending on the basket.

    Everything that does not depend on SIZE — the spot, time to expiry, the legs already
    open in the group — is resolved once and reused, so the search is pure arithmetic.
    Prices are fetched once at one lot, not once per probe.

    The scan runs DOWN from the cap rather than binary searching: added margin is not
    monotonic in lots when the basket hedges something already open — it falls as the new
    legs offset existing risk, bottoms out, then climbs once the new side dominates — and
    a binary search assumes one crossing."""
    await get_account(account_id)
    if not legs:
        raise OrderError("Nothing to size — pick a contract first")
    cash = await available_cash(account_id)
    priced = await _price_basket(dhan, [{**leg, "lots": 1} for leg in legs])

    groups: dict[tuple, list[dict]] = {}
    for p in priced:
        inst = p["inst"]
        groups.setdefault((inst.get("underlying_symbol"), inst.get("expiry")), []).append(p)

    context: list[tuple] = []
    for (underlying, expiry), plist in groups.items():
        t = _years_to_expiry(expiry)
        current = await _group_positions(account_id, underlying, expiry)
        spot = await _underlying_spot(
            dhan, underlying,
            fallback=_group_spot(current) or plist[0]["inst"].get("strike") or plist[0]["ltp"])
        open_legs = [_pos_to_leg(q) for q in current]
        before = portfolio_margin(open_legs, spot, t)["total"] if open_legs else 0.0
        context.append((spot, t, open_legs, before, plist))

    def margin_for(n: int) -> float:
        added = 0.0
        for spot, t, open_legs, before, plist in context:
            add = []
            for p in plist:
                ot = p["inst"].get("option_type")
                qty = n * int(p["inst"].get("lot_size", 1) or 1)
                add.append({
                    "kind": p["kind"], "option_type": ot, "strike": p["inst"].get("strike"),
                    "qty": qty, "side": p["side"], "premium": p["ltp"],
                    "iv": solve_iv(p["ltp"], spot, p["inst"].get("strike"), t, ot) if ot else None,
                })
            added += portfolio_margin(open_legs + add, spot, t)["total"] - before
        return round(added, 2)

    premium = round(sum(p["ltp"] * int(p["inst"].get("lot_size", 1) or 1)
                        * (1 if p["side"] == "SELL" else -1) for p in priced), 2)
    shape = {"legs": len(priced), "premium_per_lot": premium,
             "margin_per_lot": margin_for(1), "available_cash": round(cash, 2)}

    for n in range(cap, 0, -1):
        added = margin_for(n)
        if _basket_allowed(added, cash):
            note = (f"{n} lot{'s' if n > 1 else ''} per leg "
                    + (f"frees ₹{-added:,.0f}" if added < 0
                       else f"blocks ₹{added:,.0f} of ₹{cash:,.0f}")
                    + (f" (capped at {cap})" if n >= cap else ""))
            return {**shape, "max_lots": n, "margin": added,
                    "margin_at_next": None if n >= cap else margin_for(n + 1),
                    "reason": note}

    one = margin_for(1)
    return {**shape, "max_lots": 0, "margin": one, "margin_at_next": one,
            "reason": (f"one lot needs ₹{one:,.0f} but only ₹{cash:,.0f} is free"
                       if cash < one else "this account cannot carry one lot here")}


async def atm_strike(dhan: DhanClient, underlying: str, expiry: str,
                     option_type: str) -> tuple[float, float]:
    """(strike, spot) — the listed strike nearest the underlying's live spot."""
    spot = await _underlying_spot(dhan, underlying)
    if not spot:
        raise OrderError(
            f"No live {underlying} price, so there is no reference to pick an "
            "at-the-money strike from. The market may be closed.")
    strikes = await instruments_collection.distinct(
        "strike", {"underlying_symbol": underlying.upper(), "expiry": expiry,
                   "option_type": option_type.upper(),
                   "asset_class": {"$in": list(OPTION_CLASSES)}})
    strikes = [float(k) for k in strikes if k is not None]
    if not strikes:
        raise OrderError(
            f"No listed {underlying} {option_type} strikes for {expiry} to roll into.")
    return min(strikes, key=lambda k: abs(k - spot)), float(spot)


async def reopen_at_the_money(dhan: DhanClient, account_id: str, position_id: str) -> dict:
    """Close a position and immediately re-open the SAME contract at today's ATM strike.

    Same underlying, expiry, option type, side and lots — only the strike moves. A strike
    chosen weeks ago drifts as the underlying moves, and a far-OTM call against a spot
    that has run away from it is no longer the trade that was put on.

    The margin gate runs on the NET effect — old leg gone, new one in its place — before
    anything is touched. Checking the new leg alone would refuse a roll that is
    self-financing, since the position being closed releases the margin that funds it."""
    return (await reopen_all_at_the_money(dhan, account_id, [position_id]))


async def reopen_all_at_the_money(dhan: DhanClient, account_id: str,
                                  position_ids: list[str] | None = None) -> dict:
    """Roll open option legs to their at-the-money strike, in one operation.

    Every open leg by default; only the ones named in `position_ids` when given.

    Deliberately not a loop over the single-leg roll. A straddle rolled one leg at a time
    is, in between, a naked leg — and a naked leg costs MORE margin than the pair did,
    because the leg that was offsetting it is gone. On a tight book that intermediate
    state can refuse the second roll and strand the position half-rolled.

    So the work is done per (underlying, expiry) group, which is the unit margin nets
    over: every leg in the group is closed first, releasing its margin, and the
    replacements go on as ONE all-or-none basket. The whole plan is projected and gated
    before anything is touched."""
    await get_account(account_id)
    query: dict = {"account_id": account_id, "status": "OPEN"}
    if position_ids is not None:
        wanted = [pid for pid in dict.fromkeys(position_ids) if pid]
        if not wanted:
            raise OrderError("No positions were selected to roll.")
        query["position_id"] = {"$in": wanted}
    positions = [p async for p in fno_positions_collection.find(query)]
    if position_ids is not None:
        missing = set(wanted) - {p["position_id"] for p in positions}
        if missing:
            raise OrderError(
                f"{len(missing)} of the {len(wanted)} selected position(s) are no longer "
                "open in this account. Nothing was closed — refresh and select again.")
    if not positions:
        raise OrderError("This account has no open positions to roll.")

    rollable, skipped = [], []
    for pos in positions:
        inst = pos.get("instrument") or {}
        if inst.get("option_type") and inst.get("strike") is not None:
            rollable.append(pos)
        else:
            skipped.append(pos["display_name"])
    if not rollable:
        raise OrderError(
            "Nothing here has an at-the-money strike — a future is already the underlying.")

    groups: dict[tuple, list[dict]] = {}
    for pos in rollable:
        inst = pos["instrument"]
        groups.setdefault((inst["underlying_symbol"], inst["expiry"]), []).append(pos)

    plans, total_delta = [], 0.0
    for (underlying, expiry), members in groups.items():
        t = _years_to_expiry(expiry)
        legs, moves, spot = [], [], None
        for pos in members:
            inst = pos["instrument"]
            strike, spot = await atm_strike(dhan, underlying, expiry, inst["option_type"])
            legs.append({"instrument_kind": "OPTION", "symbol": underlying,
                         "expiry": expiry, "strike": strike,
                         "option_type": inst["option_type"],
                         "transaction_type": pos["side"], "lots": int(pos["lots"])})
            moves.append({"contract": pos["display_name"],
                          "from_strike": float(inst.get("strike") or 0),
                          "to_strike": strike, "lots": int(pos["lots"]),
                          "side": pos["side"], "option_type": inst["option_type"]})

        priced = await _price_basket(dhan, legs)
        whole = await _group_positions(account_id, underlying, expiry)
        ids = {pos["position_id"] for pos in members}
        survivors = [q for q in whole if q["position_id"] not in ids]
        before = portfolio_margin([_pos_to_leg(q) for q in whole], spot, t)["total"]
        add = []
        for p in priced:
            ot = p["inst"].get("option_type")
            add.append({"kind": p["kind"], "option_type": ot,
                        "strike": p["inst"].get("strike"), "qty": p["qty"],
                        "side": p["side"], "premium": p["ltp"],
                        "iv": solve_iv(p["ltp"], spot, p["inst"].get("strike"), t, ot) if ot else None})
        after = portfolio_margin([_pos_to_leg(q) for q in survivors] + add, spot, t)["total"]
        total_delta += after - before
        plans.append({"underlying": underlying, "expiry": expiry, "members": members,
                      "legs": legs, "moves": moves, "spot": round(float(spot), 2),
                      "product": members[0].get("product_type", "MARGIN")})

    total_delta = round(total_delta, 2)
    cash = await available_cash(account_id)
    if not _basket_allowed(total_delta, cash):
        scope = "the selected" if position_ids is not None else "all"
        raise OrderError(
            f"Rolling {scope} {len(rollable)} leg(s) to the money would add "
            f"₹{total_delta:,.0f} of margin and only ₹{cash:,.0f} is free. Nothing was "
            "closed — every position is exactly as it was.")

    rolled, failed, realized = [], [], 0.0
    for plan in plans:
        closed_here = []
        try:
            for pos in plan["members"]:
                fill = await exit_position(dhan, account_id, pos["position_id"])
                doc = await fno_positions_collection.find_one(
                    {"position_id": pos["position_id"], "account_id": account_id})
                realized += float((doc or {}).get("realized_pnl") or 0.0)
                closed_here.append({"contract": pos["display_name"],
                                    "exit_price": fill.get("fill_price")})
            res = await execute_basket(dhan, account_id, plan["legs"], plan["product"])
            rolled.append({
                "underlying": plan["underlying"], "expiry": plan["expiry"],
                "spot": plan["spot"], "legs": len(plan["legs"]),
                "moves": plan["moves"], "closed": closed_here,
                "net_premium": res.get("net_premium"),
                "margin_added": res.get("margin_added"),
            })
        except OrderError as exc:
            failed.append({"underlying": plan["underlying"], "expiry": plan["expiry"],
                           "closed": closed_here, "reason": exc.detail})

    moved = sum(1 for r in rolled for m in r["moves"] if m["from_strike"] != m["to_strike"])
    total_legs = sum(r["legs"] for r in rolled)
    note = (f"Rolled {total_legs} leg(s) across {len(rolled)} group(s) to the money — "
            f"{moved} changed strike, {total_legs - moved} re-entered at the same one.")
    if skipped:
        note += f" Skipped {len(skipped)} future(s), which have no at-the-money strike."
    if failed:
        flat = ", ".join(c["contract"] for f in failed for c in f["closed"])
        note += (f" {len(failed)} group(s) FAILED to re-open and are now flat: {flat}. "
                 "Re-open them by hand from the chain.")

    return {"rolled": rolled, "failed": failed, "skipped": skipped,
            "legs_rolled": total_legs, "strikes_changed": moved,
            "realized": round(realized, 2), "margin_delta": total_delta, "note": note}


async def _batch_quote_positions(positions: list[dict]) -> dict[str, float]:
    """Price every open leg in ONE set of batched Angel calls, keyed by security_id.

    Why this exists: sync_positions used to fetch a quote PER position, and per underlying
    on top. With a few hundred open legs that is 600+ sequential requests per refresh,
    which walks straight into Angel's rate limiter — it starts returning a non-JSON 403,
    and then the option chain and the Exit button fail too, because they share the same
    limiter. Angel prices 50 tokens per request, so the whole book costs ~10 calls instead.

    Returns {security_id: ltp}. Anything Angel cannot price is simply absent, and the
    caller falls back to its original per-leg path for those few.
    """
    ids = {str(p["instrument"].get("security_id")) for p in positions if p.get("instrument")}
    if not ids:
        return {}
    tok_by_id: dict[str, str] = {}
    by_ex: dict[str, list[str]] = {}
    async for d in instruments_collection.find(
        {"security_id": {"$in": list(ids)}, "angel_token": {"$ne": None}},
        {"security_id": 1, "angel_token": 1, "angel_exchange": 1},
    ):
        sid, tok = str(d["security_id"]), str(d["angel_token"])
        tok_by_id[tok] = sid
        by_ex.setdefault(d.get("angel_exchange") or "NFO", []).append(tok)
    if not by_ex:
        return {}
    prices = await batched_ltp(by_ex)
    return {tok_by_id[t]: v for t, v in prices.items() if t in tok_by_id}



async def _batch_underlying_spots(underlyings: set[str]) -> dict[str, float]:
    """Spot for many underlyings in one batched sweep, keyed by symbol.

    The companion to _batch_quote_positions. Batching only the option legs was half a fix:
    the spot lookup stayed one Angel call per underlying, so a 208-name book still fired
    ~208 single-token requests on EVERY positions refresh and kept the limiter pinned
    (5,117 non-JSON 403s in five minutes). Both sweeps are batched now.
    """
    if not underlyings:
        return {}
    by_ex: dict[str, list[str]] = {}
    tok_sym: dict[str, str] = {}
    async for d in instruments_collection.find(
        {"symbol": {"$in": list(underlyings)}, "asset_class": {"$in": ["EQUITY", "INDEX"]},
         "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
    ):
        tok = str(d["angel_token"])
        tok_sym[tok] = d["symbol"]
        by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(tok)
    if not by_ex:
        return {}
    prices = await batched_ltp(by_ex)
    return {tok_sym[t]: v for t, v in prices.items() if t in tok_sym}


async def sync_positions(dhan: DhanClient) -> int:
    open_positions = [p async for p in fno_positions_collection.find({"status": "OPEN"})]
    updated = 0
    # One batched sweep for the whole book instead of a quote per leg (see the helper).
    batched = await _batch_quote_positions(open_positions)
    spot_cache = await _batch_underlying_spots(
        {p["instrument"].get("underlying_symbol") for p in open_positions
         if p.get("instrument", {}).get("underlying_symbol")})
    # A per-leg fallback is fine for a handful of misses, but firing one Angel call per
    # position AFTER the batch already failed is what turned a rate-limit blip into 800+
    # 403s a minute: the fallback re-hits the very limiter that rejected the batch. Cap it,
    # and let the rest keep their last known mark until the next sweep.
    fallback_budget = MAX_SINGLE_QUOTE_FALLBACKS
    for pos in open_positions:
        inst = pos["instrument"]
        sid = str(inst.get("security_id"))
        if sid in batched:
            ltp, ltp_source = batched[sid], "angel_quote"
        elif fallback_budget > 0:
            fallback_budget -= 1
            ltp, ltp_source = await _ltp_with_source(dhan, inst["security_id"], inst["exchange_segment"])
        else:
            continue
        if ltp is None:
            continue
        direction = 1 if pos.get("side", "BUY") == "BUY" else -1
        unrealized = round((ltp - pos["avg_price"]) * pos["quantity"] * direction, 2)
        pnl_pct = round((ltp / pos["avg_price"] - 1) * 100 * direction, 2) if pos["avg_price"] else 0.0
        changes = {"ltp": ltp, "ltp_source": ltp_source, "unrealized_pnl": unrealized, "pnl_pct": pnl_pct, "updated_at": _now()}
        # Keep a fresh underlying spot on each open leg so the netted portfolio margin
        # (_deployed_margin, which has no broker handle) re-derives off live prices.
        underlying = inst.get("underlying_symbol")
        if underlying:
            if underlying not in spot_cache:
                if fallback_budget <= 0:
                    spot_cache[underlying] = pos.get("spot")
                else:
                    fallback_budget -= 1
                    spot_cache[underlying] = await _underlying_spot(dhan, underlying, fallback=pos.get("spot"))
            if spot_cache[underlying]:
                changes["spot"] = spot_cache[underlying]
                # Keep each leg's standalone margin engine-consistent and current as the
                # underlying moves (also backfills legacy legs that stored an old figure).
                leg = _pos_to_leg({**pos, "spot": spot_cache[underlying]})
                changes["margin_used"] = portfolio_margin([leg], spot_cache[underlying], _years_to_expiry(inst.get("expiry")))["total"]
                changes["margin_source"] = "span_lite"
        await fno_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        updated += 1

    pending = [o async for o in fno_orders_collection.find({"status": "PENDING"})]
    for order in pending:
        inst = order["instrument"]
        ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        if ltp is None:
            continue
        limit_price = order["limit_price"]
        crossed = (order["transaction_type"] == "BUY" and ltp <= limit_price) or (order["transaction_type"] == "SELL" and ltp >= limit_price)
        if crossed:
            try:
                await _fill(dhan, {k: v for k, v in order.items() if k not in ("_id", "status", "fill_price", "filled_at", "margin_used", "leverage")}, limit_price)
                await fno_orders_collection.delete_one({"_id": order["_id"]})
            except OrderError:
                continue
    return updated


async def reset_account(account_id: str) -> dict:
    """Wipe ONE account back to pristine: delete every position and order in it so
    realized P&L clears and available_cash returns to exactly its initial_capital.
    Other accounts are untouched. Irreversible — the caller confirms first."""
    account = await get_account(account_id)
    positions_deleted = (await fno_positions_collection.delete_many({"account_id": account_id})).deleted_count
    orders_deleted = (await fno_orders_collection.delete_many({"account_id": account_id})).deleted_count
    return {"positions_deleted": positions_deleted, "orders_deleted": orders_deleted,
            "initial_capital": account["initial_capital"]}


def _parse_roi_start(value: str | None) -> str:
    """Validate an ISO date. Raises rather than falling back — a mistyped start would
    silently rebase every per-day number on the page."""
    if not value:
        raise OrderError("A start date is required")
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise OrderError(f"{value!r} is not a date (expected YYYY-MM-DD)") from exc
    if d > date.today():
        raise OrderError("The start date cannot be in the future")
    return d.isoformat()


def _roi_as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str) and v:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


async def performance(account_id: str, start: str | None = None) -> dict:
    """Profit since a chosen day, and what it averages per day.

    ATTRIBUTION, because this is the part that can quietly mislead. Realised counts where
    the position CLOSED inside the window; unrealised only for positions OPENED inside it.
    A leg carried from before the window holds gains earned outside it, and crediting
    those to the window is exactly how a per-day average gets flattered — so they are
    reported separately instead of blended in.
    """
    account = await get_account(account_id)
    initial = float(account.get("initial_capital") or 0)
    start_iso = _parse_roi_start(
        start
        or account.get("roi_start_date")
        or (_roi_as_date(account.get("created_at")) or date.today()).isoformat())
    start_d = date.fromisoformat(start_iso)
    today = date.today()

    # "Ten days back" reads as ten days, so the span is the gap. Same day means one day,
    # never zero — nothing may be divided by zero here.
    days = max(1, (today - start_d).days)
    # Counted over the SAME span, so trading days can never exceed calendar days and
    # invert the two averages.
    trading_days = max(1, sum(1 for i in range(1, (today - start_d).days + 1)
                              if (start_d + timedelta(days=i)).weekday() < 5))

    realised_in = realised_before = 0.0
    unrealised_in = unrealised_carried = 0.0
    opened_in = closed_in = 0

    async for p in fno_positions_collection.find(
            {"account_id": account_id},
            {"_id": 0, "status": 1, "opened_at": 1, "closed_at": 1,
             "realized_pnl": 1, "unrealized_pnl": 1}):
        r = float(p.get("realized_pnl") or 0.0)
        u = float(p.get("unrealized_pnl") or 0.0)
        o_d, c_d = _roi_as_date(p.get("opened_at")), _roi_as_date(p.get("closed_at"))
        if p.get("status") == "OPEN":
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
            f"{round(unrealised_carried, 2):,.2f} of unrealised profit sits in legs opened "
            f"before {start_iso}. It is excluded from the window, because it was not "
            f"earned inside it."
            if abs(unrealised_carried) > 0.005 else None),
        "note": ("Realised counts where the position CLOSED in the window; unrealised only "
                 "for positions OPENED in it. Per-day is the window profit divided by "
                 f"{days} calendar days ({trading_days} of them trading days)."),
    }


async def summary(account_id: str) -> dict:
    account = await get_account(account_id)
    initial_capital = account["initial_capital"]
    deployed = await _deployed_margin(account_id)
    standalone = await _standalone_margin_total(account_id)
    realized = await _realized_pnl_all_time(account_id)
    unrealized = 0.0
    async for p in fno_positions_collection.find({"account_id": account_id, "status": "OPEN"}, {"unrealized_pnl": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
    equity = initial_capital + realized + unrealized
    open_count = await fno_positions_collection.count_documents({"account_id": account_id, "status": "OPEN"})
    closed_count = await fno_positions_collection.count_documents({"account_id": account_id, "status": "CLOSED"})
    wins = await fno_positions_collection.count_documents(
        {"account_id": account_id, "status": "CLOSED", "realized_pnl": {"$gt": 0}}
    )
    win_rate = round(wins / closed_count * 100, 1) if closed_count else None
    return {
        "account_id": account_id,
        "initial_capital": initial_capital,
        "available_cash": round(initial_capital + realized - deployed, 2),
        "deployed_margin": round(deployed, 2),
        "standalone_margin": round(standalone, 2),
        "margin_benefit": round(max(0.0, standalone - deployed), 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(realized + unrealized, 2),
        "equity": round(equity, 2),
        "roi_pct": round((equity - initial_capital) / initial_capital * 100, 2) if initial_capital else 0.0,
        "open_positions": open_count,
        "closed_positions": closed_count,
        "win_rate": win_rate,
        "performance": await performance(account_id),
    }
