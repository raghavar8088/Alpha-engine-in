"""Angel One Commodity Live Trading Data (2026-10-19) - the owner's REAL Angel One MCX account.

READ-ONLY. Nothing in this module can place, modify or cancel an order; it only reads what
Angel's API already shows the owner in the app, keeps it day by day, and works out returns.

WHERE THE NUMBERS COME FROM
  trades     Angel's trade book (getTradeBook), MCX rows - every fill: time, contract, side,
             quantity, price, order id. The API holds TODAY's session only, so this module
             polls it through the day and keeps each day's fills itself.
  P&L        Angel's own position book (getPosition): `realised` + `unrealised` = `pnl` per
             contract for the day - the figure the Angel app shows, gross of charges. A
             position carried overnight is marked from the previous close, as Angel does.
  charges    Angel's published commodity rate card applied to the day's ORDERS (brokerage is
             per executed order, not per fill): options - Rs20, 0.0418% MCX charge, 0.05% CTT
             on sells, 0.003% stamp on buys, SEBI, 18% GST; futures - tradingai_shared.mcx_fees.
             An estimate until Angel's contract note says otherwise; labelled as such.
  capital    "capital invested that day" = the PEAK of Angel's `utiliseddebits` (RMS) seen in
             the day's polls - the broker's own figure for margin + premium in use. For days
             imported from Angel's trade-history download, where no RMS snapshot exists, it is
             reconstructed (premium paid for bought options, Angel's measured margin rates for
             sold options and futures) and marked "estimated".
  ROI        net P&L / capital invested, per day.

OLDER DAYS
  The API cannot return past sessions. Angel One web -> Reports -> Trade History, downloaded as
  CSV, can be imported (preview first): those days' P&L is the REALISED P&L of trades closed
  that day, matched first-in-first-out per contract.

AVERAGES AND PROJECTIONS
  Over the days with MCX activity: average capital, average net P&L a day, average return % a
  day = average net P&L / average capital. One month = 21 MCX sessions and one year = 250,
  both simple (x days) and compounded ((1 + r)^days - 1). They are arithmetic on the past
  average, shown with how many days it rests on - not a forecast.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import math
import os
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.core.db import db

logger = logging.getLogger("angel_commodity")

IST = timezone(timedelta(hours=5, minutes=30))
SWITCH_KEY = "angel_commodity"
POLL_SECONDS = int(os.getenv("ANGEL_COMMODITY_POLL_SECONDS", "60"))
# The trade book is "today's" between these IST minutes. After midnight it still shows the
# evening's fills until Angel clears it, so polling then would file them under the wrong date.
WINDOW = (8 * 60 + 45, 23 * 60 + 59)
SESSIONS_PER_MONTH = 21
SESSIONS_PER_YEAR = 250

fills = db["acl_fills"]
orders = db["acl_orders"]
days = db["acl_days"]
points = db["acl_points"]

status: dict = {"running": False, "last_sync": None, "last_error": None, "errors": 0, "angel_ok": None}

SYM_RE = re.compile(r"^([A-Z][A-Z0-9&]*?)(\d{2}[A-Z]{3}\d{2})(\d+(?:\.\d+)?)?(CE|PE|FUT)$")


def _f(v, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def parse_symbol(tradingsymbol: str) -> dict:
    """CRUDEOILM17NOV269250CE -> underlying CRUDEOILM, expiry 2026-11-17, strike 9250, CE."""
    ts = (tradingsymbol or "").upper().strip()
    m = SYM_RE.match(ts)
    if not m:
        return {"underlying": ts, "expiry": None, "strike": None, "kind": "FUT"}
    und, exp, strike, kind = m.groups()
    try:
        expiry = datetime.strptime(exp, "%d%b%y").date().isoformat()
    except ValueError:
        expiry = None
    return {"underlying": und, "expiry": expiry, "strike": float(strike) if strike else None, "kind": kind}


def spec_factor(underlying: str, lot_units: float | None) -> float | None:
    """Rupees per unit of Angel's QUANTITY: the contract's value multiplier over Angel's
    order quantity for one lot (CRUDEOILM 10 barrels / 10 = 1; GOLD 100 / 1 = 100).
    None when the published spec or the lot is unknown."""
    try:
        from app.services.commodity_positions import CONTRACT_SPEC
        spec = CONTRACT_SPEC.get((underlying or "").upper())
    except Exception:  # noqa: BLE001
        spec = None
    if spec and lot_units:
        return spec[2] / float(lot_units)
    return None


def value_factor(underlying: str, lot_units: float | None, price: float, qty: float, tradevalue: float) -> float:
    """The published spec first; Angel's own trade value (tradevalue / (price x qty)) when the
    spec is unknown; 1 when neither is available."""
    sf = spec_factor(underlying, lot_units)
    if sf:
        return sf
    if tradevalue and price > 0 and qty > 0:
        return round(tradevalue / (price * qty), 6)
    return 1.0


def _family(underlying: str) -> str:
    try:
        from app.services.commodity_positions import family_of
        return family_of(underlying)
    except Exception:  # noqa: BLE001
        return underlying


# ── charges (Angel's published commodity rate card) ─────────────────────────────


COMPONENTS = ("brokerage", "exchange", "ctt", "stamp", "sebi", "gst")


def _option_order_breakdown(turnover: float, sell: bool, on: date) -> dict:
    """One commodity-OPTION order's charges, by component (premium turnover)."""
    try:  # the shared schedule, once it is committed
        from tradingai_shared.mcx_option_fees import mcx_option_leg
        b = mcx_option_leg(turnover, 1, sell=sell, on=on)
        return {**{k: float(b.get(k, 0.0)) for k in COMPONENTS}, "total": float(b["total"])}
    except Exception:  # noqa: BLE001
        brokerage, exchange, sebi = 20.0, turnover * 0.000418, turnover * 0.000001
        parts = {"brokerage": brokerage, "exchange": exchange, "ctt": turnover * 0.0005 if sell else 0.0,
                 "stamp": 0.0 if sell else turnover * 0.00003, "sebi": sebi,
                 "gst": 0.18 * (brokerage + exchange + sebi)}
        return {**{k: round(v, 2) for k, v in parts.items()}, "total": round(sum(parts.values()), 2)}


def _future_order_breakdown(turnover: float, sell: bool, on: date) -> dict:
    """One commodity-FUTURES order's charges, by component (tradingai_shared.mcx_fees)."""
    from tradingai_shared.mcx_fees import leg_breakdown
    b = leg_breakdown(turnover, 1, not sell, on)
    return {**{k: round(float(b.get(k, 0.0)), 2) for k in COMPONENTS}, "total": round(float(b["total"]), 2)}


def day_charges(day_fills: list[dict], on: date) -> tuple[float, dict, dict]:
    """Charges per executed ORDER (brokerage is per order, not per fill): the day's total,
    each order's charges, and the day's total by component."""
    by_order: dict[str, dict] = {}
    for x in day_fills:
        o = by_order.setdefault(str(x.get("orderid") or x.get("fillid")), {"turnover": 0.0, "sell": x["side"] == "SELL",
                                                                             "option": x["kind"] in ("CE", "PE")})
        o["turnover"] += x["value"]
    total, parts = 0.0, {k: 0.0 for k in COMPONENTS}
    for o in by_order.values():
        b = (_option_order_breakdown if o["option"] else _future_order_breakdown)(o["turnover"], o["sell"], on)
        o["charges"], o["breakdown"] = b["total"], b
        total += b["total"]
        for k in COMPONENTS:
            parts[k] += b.get(k, 0.0)
    return round(total, 2), by_order, {k: round(v, 2) for k, v in parts.items()}


# ── capital, reconstructed from fills (for days without an RMS snapshot) ─────────


def fill_factor(x: dict) -> float:
    """Rupees per unit of quantity for a stored fill (older rows predate the field)."""
    f = x.get("value_factor")
    if f:
        return float(f)
    return spec_factor(x.get("underlying") or parse_symbol(x.get("tradingsymbol", ""))["underlying"],
                       x.get("lot_units")) or 1.0


def _position_capital(sym: dict, qty: float, avg_price: float, lot_units: float) -> float:
    """Capital tied up by one open position: premium for a bought option; Angel's measured
    margin rate on the notional for a sold option or a future."""
    if qty == 0:
        return 0.0
    if sym["kind"] in ("CE", "PE") and qty > 0:
        return qty * avg_price
    from app.services.commodity_broker_margin import SHORT_OPTION_FACTOR, measured_rate
    rate = measured_rate(_family(sym["underlying"]))
    if sym["kind"] in ("CE", "PE"):
        notional = (sym["strike"] or avg_price) * abs(qty)
        return rate * SHORT_OPTION_FACTOR * notional
    return rate * avg_price * abs(qty)


def reconstruct(all_fills: list[dict]) -> dict[str, dict]:
    """First-in-first-out per contract over every known fill, in time order. Returns, per date:
    realised P&L of the trades closed that day and the PEAK reconstructed capital in use."""
    out: dict[str, dict] = defaultdict(lambda: {"realised": 0.0, "capital_peak": 0.0})
    open_lots: dict[str, list[list[float]]] = defaultdict(list)      # symbol -> [[signed qty, price], ...]
    meta: dict[str, dict] = {}
    factors: dict[str, float] = {}

    def book_capital() -> float:
        cap = 0.0
        for s, lots in open_lots.items():
            q = sum(l[0] for l in lots)
            if q:
                cap += _position_capital(meta[s], q, sum(l[0] * l[1] for l in lots) / q, 1.0) * factors.get(s, 1.0)
        return cap

    current = None
    for x in sorted(all_fills, key=lambda r: (r["date"], r.get("time") or "", r.get("seq", 0))):
        if x["date"] != current:
            # positions carried into a new day tie up capital on it from the open
            current = x["date"]
            out[current]["capital_peak"] = max(out[current]["capital_peak"], book_capital())
        sym = x["tradingsymbol"]
        meta.setdefault(sym, parse_symbol(sym))
        factors[sym] = fill_factor(x)
        signed = x["qty"] if x["side"] == "BUY" else -x["qty"]
        book = open_lots[sym]
        remaining = signed
        while remaining and book and (book[0][0] > 0) != (remaining > 0):
            q0, p0 = book[0]
            take = min(abs(q0), abs(remaining))
            gain = (x["price"] - p0) * take if q0 > 0 else (p0 - x["price"]) * take
            out[x["date"]]["realised"] += gain * fill_factor(x)
            q0 = q0 - take if q0 > 0 else q0 + take
            remaining = remaining + take if remaining < 0 else remaining - take
            if q0 == 0:
                book.pop(0)
            else:
                book[0][0] = q0
        if remaining:
            book.append([remaining, x["price"]])
        d = out[x["date"]]
        d["capital_peak"] = max(d["capital_peak"], book_capital())
    return {k: {"realised": round(v["realised"], 2), "capital_peak": round(v["capital_peak"], 2)} for k, v in out.items()}


# ── live capture ────────────────────────────────────────────────────────────────


def _fill_doc(r: dict, day: str, seq: int) -> dict:
    sym = parse_symbol(r.get("tradingsymbol"))
    qty, price = _f(r.get("fillsize")), _f(r.get("fillprice"))
    lot = _f(r.get("marketlot")) or None
    tv = _f(r.get("tradevalue"))
    factor = value_factor(sym["underlying"], lot, price, qty, tv)
    return {"date": day, "time": r.get("filltime"), "seq": seq, "tradingsymbol": r.get("tradingsymbol"),
            "underlying": sym["underlying"], "expiry": sym["expiry"], "strike": sym["strike"], "kind": sym["kind"],
            "instrumenttype": r.get("instrumenttype"), "side": (r.get("transactiontype") or "").upper(),
            "qty": qty, "price": price, "value": round(price * qty * factor, 2), "angel_tradevalue": tv or None,
            "value_factor": factor, "lot_units": lot, "product": r.get("producttype"),
            "orderid": str(r.get("orderid") or ""), "fillid": str(r.get("fillid") or ""), "source": "angel-api"}


def _expiry(v) -> str | None:
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%Y-%m-%d", "%d%b%y"):
        try:
            return datetime.strptime(str(v or "").strip().upper(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _position_doc(r: dict) -> dict:
    """One MCX row of Angel's position book, as kept here."""
    sym = parse_symbol(r.get("tradingsymbol"))
    return {"tradingsymbol": r.get("tradingsymbol"), "underlying": r.get("symbolname") or sym["underlying"],
            "token": str(r.get("symboltoken") or "") or None, "product": r.get("producttype"),
            "instrumenttype": r.get("instrumenttype"), "kind": sym["kind"],
            "expiry": _expiry(r.get("expirydate")) or sym["expiry"],
            "strike": _f(r.get("strikeprice")) or sym["strike"], "option_type": r.get("optiontype") or None,
            "netqty": _f(r.get("netqty")), "buyqty": _f(r.get("buyqty")), "sellqty": _f(r.get("sellqty")),
            "buyavg": _f(r.get("buyavgprice")), "sellavg": _f(r.get("sellavgprice")),
            "buyamount": _f(r.get("buyamount")), "sellamount": _f(r.get("sellamount")),
            "netavg": _f(r.get("avgnetprice")) or _f(r.get("netprice")), "netvalue": _f(r.get("netvalue")),
            "ltp": _f(r.get("ltp")), "close": _f(r.get("close")),
            "realised": _f(r.get("realised")), "unrealised": _f(r.get("unrealised")), "pnl": _f(r.get("pnl")),
            "lot_units": _f(r.get("lotsize")) or None,
            "cf_qty": _f(r.get("cfbuyqty")) - _f(r.get("cfsellqty")),
            "cf_buyqty": _f(r.get("cfbuyqty")), "cf_sellqty": _f(r.get("cfsellqty")),
            "cf_buyavg": _f(r.get("cfbuyavgprice")), "cf_sellavg": _f(r.get("cfsellavgprice"))}


def in_window(now: datetime) -> bool:
    m = now.hour * 60 + now.minute
    return now.weekday() < 5 and WINDOW[0] <= m <= WINDOW[1]


async def capture(now: datetime | None = None) -> dict:
    """One poll of Angel: today's MCX fills, orders, positions and capital in use. Only inside
    the window: after midnight Angel's book still holds the evening's fills, and filing them
    then would put them under the wrong date."""
    from app.services.angel_client import angel_client
    now = now or datetime.now(IST)
    if not in_window(now):
        return {"skipped": "outside the MCX window (Mon-Fri 08:45-23:59 IST)"}
    day = now.date().isoformat()
    tb = await angel_client.trade_book()
    ob = await angel_client.order_book()
    pos = await angel_client.broker_positions()
    fund = await angel_client.funds()
    status["angel_ok"] = True
    mcx_t = [r for r in (tb or []) if r.get("exchange") == "MCX"]
    for i, r in enumerate(mcx_t):
        doc = _fill_doc(r, day, i)
        await fills.update_one({"date": day, "orderid": doc["orderid"], "fillid": doc["fillid"]}, {"$setOnInsert": doc}, upsert=True)
    for r in (ob or []):
        if r.get("exchange") != "MCX":
            continue
        await orders.update_one({"date": day, "orderid": str(r.get("orderid"))}, {"$set": {
            "date": day, "orderid": str(r.get("orderid")), "tradingsymbol": r.get("tradingsymbol"),
            "side": r.get("transactiontype"), "qty": _f(r.get("quantity")), "filled": _f(r.get("filledshares")),
            "price": _f(r.get("price")), "avg_price": _f(r.get("averageprice")), "status": r.get("orderstatus") or r.get("status"),
            "ordertype": r.get("ordertype"), "product": r.get("producttype"), "time": r.get("updatetime"),
            "text": r.get("text")}}, upsert=True)
    mcx_p = [r for r in (pos or []) if r.get("exchange") == "MCX"]
    positions = [_position_doc(r) for r in mcx_p]
    funds_now = {k: _f(v) for k, v in (fund or {}).items() if v is not None}
    in_use = funds_now.get("utiliseddebits", 0.0)
    gross = round(sum(p["pnl"] for p in positions), 2)
    active = bool(mcx_t or positions)
    prev = await days.find_one({"_id": day}) or {}
    upd = {"date": day, "basis": "angel-api", "positions": positions, "gross_pnl": gross,
           "realised": round(sum(p["realised"] for p in positions), 2),
           "unrealised": round(sum(p["unrealised"] for p in positions), 2),
           "capital_now": in_use, "available_cash": funds_now.get("availablecash", 0.0),
           "account_net": funds_now.get("net", 0.0), "funds": funds_now,
           "updated_at": datetime.now(timezone.utc), "active": active}
    if active:
        upd["capital_peak"] = max(prev.get("capital_peak") or 0.0, in_use)
        upd.setdefault("capital_source", "angel-rms")
    await days.update_one({"_id": day}, {"$set": upd, "$setOnInsert": {"first_sync": datetime.now(timezone.utc),
                                                                         "funds_open": funds_now}}, upsert=True)
    if active and (now.minute % 5 == 0 or not await points.find_one({"date": day})):
        # one intraday point every 5 minutes (the Atlas cluster's quota is small)
        await points.update_one({"date": day, "slot": now.strftime("%H:%M")},
                                {"$set": {"ts": datetime.now(timezone.utc), "capital": in_use, "gross_pnl": gross,
                                          "realised": upd["realised"], "unrealised": upd["unrealised"],
                                          "available_cash": upd["available_cash"],
                                          "open_positions": sum(1 for p in positions if p["netqty"])}},
                                upsert=True)
    await finalise(day)
    status["last_sync"] = datetime.now(timezone.utc).isoformat()
    return {"date": day, "fills": len(mcx_t), "positions": len(positions), "capital_in_use": in_use, "gross_pnl": gross}


async def finalise(day: str) -> dict | None:
    """Recompute one day's charges, net P&L, capital and ROI from what is stored."""
    d = await days.find_one({"_id": day})
    if not d:
        return None
    dfills = [x async for x in fills.find({"date": day})]
    on = date.fromisoformat(day)
    charges, by_order, parts = day_charges(dfills, on)
    capital = d.get("capital_peak") or 0.0
    source = d.get("capital_source") or "angel-rms"
    if not capital:
        capital = d.get("capital_estimate") or 0.0
        source = "estimated"
    gross = d.get("gross_pnl") if d.get("basis") == "angel-api" else d.get("realised_fifo", 0.0)
    net = round((gross or 0.0) - charges, 2)
    roi = net / capital if capital > 0 else None
    upd = {"charges": charges, "charges_breakdown": parts, "orders": len(by_order), "fills": len(dfills),
           "turnover": round(sum(x["value"] for x in dfills), 2), "net_pnl": net, "capital": round(capital, 2),
           "capital_source": source, "roi": roi,
           "contracts": sorted({x["tradingsymbol"] for x in dfills} | {p["tradingsymbol"] for p in d.get("positions") or []})}
    await days.update_one({"_id": day}, {"$set": upd})
    return {**d, **upd}


async def ensure_indexes() -> None:
    """Never raises: a failed index build (Atlas at quota) must not take the backend down."""
    for coll, keys, unique in ((fills, [("date", 1), ("orderid", 1), ("fillid", 1)], True),
                               (orders, [("date", 1), ("orderid", 1)], True),
                               (points, [("date", 1), ("slot", 1)], True)):
        try:
            await coll.create_index(keys, unique=unique)
        except Exception:  # noqa: BLE001
            logger.exception("angel commodity: index on %s not created", coll.name)


async def angel_commodity_loop() -> None:
    from app.services import desk_switches
    status["running"] = True
    await ensure_indexes()
    logger.info("angel commodity ledger: polling Angel's MCX book every %ss (read-only)", POLL_SECONDS)
    while True:
        try:
            await desk_switches.gated(SWITCH_KEY, capture)
        except Exception as exc:  # noqa: BLE001 - retried next poll
            status["errors"] += 1
            status["angel_ok"] = False
            status["last_error"] = f"{type(exc).__name__}: {exc}"[:240]
            logger.warning("angel commodity capture failed: %s", exc)
        await asyncio.sleep(POLL_SECONDS)


# ── older days: Angel's trade-history download ──────────────────────────────────

WANT = {
    "date": ("trade date", "date", "trade time", "time", "order date"),
    "symbol": ("symbol", "scrip", "tradingsymbol", "trading symbol", "security", "instrument", "contract"),
    "side": ("buy/sell", "transaction type", "trade type", "side", "b/s", "buy / sell", "type"),
    "qty": ("qty", "quantity", "trade qty", "traded qty", "filled qty", "trade quantity"),
    "price": ("trade price", "price", "rate", "avg price", "traded price", "trade rate"),
}
OPTIONAL = {"order": ("order id", "order no", "orderid", "order number"),
            "trade": ("trade id", "trade no", "tradeid", "trade number", "fill id"),
            "exchange": ("exchange", "exch", "segment"),
            "time": ("trade time", "time", "execution time")}


def _pick(norm: dict[str, str], names: tuple, required: bool, key: str) -> str | None:
    hits = [h for h, n in norm.items() if n in names] or [h for h, n in norm.items() if any(x in n for x in names)]
    if len(hits) == 1:
        return hits[0]
    if not hits and not required:
        return None
    raise ValueError(f"column for '{key}' is {'missing' if not hits else 'ambiguous: ' + ', '.join(hits)}")


def _date(v: str) -> str | None:
    v = (v or "").strip()
    fmts = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%m/%d/%Y")
    for text in (v, v.split(" ")[0], v.split("T")[0]):
        for fmt in fmts:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def parse_tradebook(text: str) -> tuple[list[dict], dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = reader.fieldnames or []
    norm = {h: h.strip().lower() for h in header}
    cols = {k: _pick(norm, names, True, k) for k, names in WANT.items()}
    for k, names in OPTIONAL.items():
        try:
            cols[k] = _pick({h: n for h, n in norm.items() if h not in cols.values()}, names, False, k)
        except ValueError:
            cols[k] = None
    out = []
    for i, r in enumerate(reader):
        if cols.get("exchange") and (r.get(cols["exchange"]) or "").strip().upper() not in ("MCX", "MCX-COMM", "COMMODITY", "MCXFO", ""):
            continue
        side = (r.get(cols["side"]) or "").strip().upper()
        side = "BUY" if side.startswith("B") else "SELL" if side.startswith("S") else None
        qty, price = _f(r.get(cols["qty"])), _f(r.get(cols["price"]))
        sym = (r.get(cols["symbol"]) or "").strip().upper().replace(" ", "")
        d = _date(r.get(cols["date"]) or "")
        if not (side and qty and price and sym and d):
            continue
        p = parse_symbol(sym)
        t = (r.get(cols["time"]) or "").strip() if cols.get("time") and cols["time"] != cols["date"] else ""
        if not t and " " in (r.get(cols["date"]) or "").strip():
            t = (r.get(cols["date"]) or "").strip().split(" ", 1)[1]
        order = str(r.get(cols["order"]) or "").strip() if cols.get("order") else ""
        trade = str(r.get(cols["trade"]) or "").strip() if cols.get("trade") else ""
        if not trade:   # stable across re-imports of the same rows, whatever their order in the file
            trade = "h" + hashlib.sha1(f"{d}|{t}|{sym}|{side}|{qty}|{price}|{order}".encode()).hexdigest()[:16]
        factor = 1.0
        try:
            from app.services.commodity_positions import CONTRACT_SPEC, broker_order_qty
            lot = broker_order_qty(p["underlying"])
            if CONTRACT_SPEC.get(p["underlying"]) and lot:
                factor = CONTRACT_SPEC[p["underlying"]][2] / lot
        except Exception:  # noqa: BLE001
            pass
        out.append({"date": d, "time": t, "seq": i, "tradingsymbol": sym, "underlying": p["underlying"],
                    "expiry": p["expiry"], "strike": p["strike"], "kind": p["kind"], "side": side, "qty": qty,
                    "price": price, "value": round(qty * price * factor, 2), "value_factor": factor,
                    "orderid": order, "fillid": trade, "source": "angel-tradebook-csv"})
    return out, cols


async def import_tradebook(text: str, apply: bool = False) -> dict:
    """Preview (default) or apply an import of Angel's trade-history CSV. Days already captured
    live from the API are left alone: the API's record of them is the better one."""
    rows, cols = parse_tradebook(text)
    live_days = {d["_id"] async for d in days.find({"basis": "angel-api"}, {"_id": 1})}
    new = [r for r in rows if r["date"] not in live_days]
    by_day: dict[str, list] = defaultdict(list)
    for r in new:
        by_day[r["date"]].append(r)
    preview = {"columns": cols, "rows_read": len(rows), "days": sorted(by_day),
               "skipped_live_days": sorted({r["date"] for r in rows} & live_days), "fills": len(new)}
    if not apply or not new:
        return {**preview, "applied": False}
    for r in new:
        await fills.update_one({"date": r["date"], "orderid": r["orderid"], "fillid": r["fillid"]}, {"$setOnInsert": r}, upsert=True)
    every = [x async for x in fills.find({})]
    rec = reconstruct(every)
    for d in by_day:
        await days.update_one({"_id": d}, {"$set": {"date": d, "basis": "imported", "realised_fifo": rec.get(d, {}).get("realised", 0.0),
                                                    "capital_estimate": rec.get(d, {}).get("capital_peak", 0.0), "active": True,
                                                    "updated_at": datetime.now(timezone.utc)}}, upsert=True)
        await finalise(d)
    return {**preview, "applied": True}


# ── read model ──────────────────────────────────────────────────────────────────


def _clean(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id",)}
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return out


def averages(rows: list[dict]) -> dict:
    act = [r for r in rows if r.get("capital") and r.get("net_pnl") is not None]
    n = len(act)
    if not n:
        return {"days": 0}
    caps = [r["capital"] for r in act]
    nets = [r["net_pnl"] for r in act]
    rois = [r["roi"] for r in act if r.get("roi") is not None]
    avg_cap, avg_net = statistics.mean(caps), statistics.mean(nets)
    r = avg_net / avg_cap if avg_cap else 0.0
    sd = statistics.stdev(nets) if n > 1 else None
    t = avg_net / (sd / math.sqrt(n)) if sd else None

    def comp(days_n: int) -> float | None:
        try:
            return (1 + r) ** days_n - 1 if r > -1 else -1.0
        except OverflowError:
            return None

    return {
        "days": n, "first": min(x["date"] for x in act), "last": max(x["date"] for x in act),
        "avg_capital": round(avg_cap, 2), "avg_net_pnl": round(avg_net, 2), "avg_return_pct": r,
        "mean_daily_roi": statistics.mean(rois) if rois else None,
        "total_net_pnl": round(sum(nets), 2), "total_charges": round(sum(x.get("charges") or 0 for x in act), 2),
        "green_days": sum(1 for x in nets if x > 0), "t_stat": round(t, 2) if t is not None else None,
        "best_day": max(nets), "worst_day": min(nets),
        "projection": {
            "sessions_month": SESSIONS_PER_MONTH, "sessions_year": SESSIONS_PER_YEAR,
            "month_rupees": round(avg_net * SESSIONS_PER_MONTH, 0), "year_rupees": round(avg_net * SESSIONS_PER_YEAR, 0),
            "month_pct_simple": r * SESSIONS_PER_MONTH, "year_pct_simple": r * SESSIONS_PER_YEAR,
            "month_pct_compound": comp(SESSIONS_PER_MONTH), "year_pct_compound": comp(SESSIONS_PER_YEAR),
        },
    }


async def summary() -> dict:
    rows = [_clean(d) | {"date": d["_id"]} async for d in days.find({"active": True}).sort("_id", -1)]
    today = datetime.now(IST).date().isoformat()
    tdoc = next((r for r in rows if r["date"] == today), None)
    tfills = [_clean(x) async for x in fills.find({"date": today}).sort([("time", -1), ("seq", -1)])]
    tords = [_clean(x) async for x in orders.find({"date": today}).sort("time", -1)]
    pts = [_clean(x) async for x in points.find({"date": today}).sort("slot", 1)]
    for r in rows:
        r.pop("positions", None)
    sw = True
    try:
        from app.services import desk_switches
        sw = await desk_switches.is_on(SWITCH_KEY)
    except Exception:  # noqa: BLE001
        pass
    return {"status": {**status, "switch_on": sw, "window_open": in_window(datetime.now(IST))},
            "today": {"date": today, "day": tdoc, "positions": (await days.find_one({"_id": today}) or {}).get("positions") or [],
                      "fills": tfills, "orders": tords, "points": pts},
            "days": rows, "averages": averages(rows)}
