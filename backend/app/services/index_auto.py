"""Indian Market Option Auto Selling (2026-10-30): the Commodity Auto Positions design on Indian index
options - per index, 11 strategies x 5 account sizes, each account selling one call + put pair a day.

The owner's rules, as confirmed:
  - Indices: NIFTY 50, BANK NIFTY, SENSEX, BANKEX by default. The list is configurable
    (INDEX_AUTO_INDICES); any index in INDEX_SPECS can be added - FINNIFTY and MIDCPNIFTY are there.
  - Strategies: sell the ATM call and put, or the call k strikes above and the put k strikes below
    the at-the-money strike, k = 1..10, on the listed strike ladder. ATM is set from the INDEX price.
  - Accounts: Rs 5 lakh, 10 lakh, 20 lakh, 50 lakh and 1 crore per strategy - 220 for four indices;
    no capital is shared between any two.
  - Schedule: entry at 15:15 IST and exit at 15:15 on the next NSE trading day, then a fresh entry
    (INDEX_AUTO_ENTRY / INDEX_AUTO_EXIT; an exit later than the entry on the same clock means the
    same day). Entries are taken only in the 15 minutes from the entry time; an exit that falls due
    is taken whenever the market is next open.
  - Expiry: the nearest listed expiry with MORE than two exchange trading days left (expiry day = 1),
    per index at every entry - so a trade is never held into expiry day.
  - Sizing: the whole account is allocated. Lots = account equity / the broker's margin for one
    call + put lot pair, rounded down; the stop is 20% of that allocation on the combined pair, and
    after a stop the account waits for the next entry.
  - Fills: sold at the bid, bought back at the ask, from Angel's FULL quote; a leg with no fresh
    two-sided quote at entry skips that strategy for the day. Angel's option charges on every order
    (tradingai_shared.option_fees; BSE contracts at BSE's own exchange rate).

Margin is Angel's own calculator for the basket (margin_batch); when Angel cannot be reached, the
app's SPAN-lite model (fno_margin), labelled as an estimate. The stop is checked every 30 s in the
session, on buying both legs back at a fresh ask; nothing trades overnight, so a gap can carry the
loss past 20% before the stop can act. Fills assume the touch for any size.

SENSEX and BANKEX options are not in the app's instrument master (NSE only), so this module loads
BSE's index options itself from Angel's contract file once a day into its own store.

Records live in the box's second MongoDB (FACTORY_MONGO_URL), not on Atlas.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone

from pymongo import UpdateOne

from app.core.db import db, instruments_collection

logger = logging.getLogger("index_auto")

IST = timezone(timedelta(hours=5, minutes=30))

# index -> label, option exchange, the index's own quote, where its option contracts come from
INDEX_SPECS: dict[str, dict] = {
    "NIFTY": {"label": "NIFTY 50", "exchange": "NFO", "spot": ("NSE", "99926000"), "source": "master"},
    "BANKNIFTY": {"label": "BANK NIFTY", "exchange": "NFO", "spot": ("NSE", "99926009"), "source": "master"},
    "FINNIFTY": {"label": "FIN NIFTY", "exchange": "NFO", "spot": ("NSE", "99926037"), "source": "master"},
    "MIDCPNIFTY": {"label": "MIDCAP NIFTY", "exchange": "NFO", "spot": ("NSE", "99926074"), "source": "master"},
    "SENSEX": {"label": "SENSEX", "exchange": "BFO", "spot": ("BSE", "99919000"), "source": "bse"},
    "BANKEX": {"label": "BANKEX", "exchange": "BFO", "spot": ("BSE", "99919012"), "source": "bse"},
}
INDICES: tuple[str, ...] = tuple(
    i for i in (s.strip().upper() for s in os.getenv("INDEX_AUTO_INDICES", "NIFTY,BANKNIFTY,SENSEX,BANKEX").split(","))
    if i in INDEX_SPECS)
OFFSETS = tuple(range(11))                       # 0 = ATM, k = k strikes away
SIZES = (500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000)


def _hhmm(v: str, default: time) -> time:
    try:
        h, m = (int(x) for x in v.strip().split(":"))
        return time(h, m)
    except (ValueError, AttributeError):
        return default


ENTRY_AT = _hhmm(os.getenv("INDEX_AUTO_ENTRY", "15:15"), time(15, 15))
EXIT_AT = _hhmm(os.getenv("INDEX_AUTO_EXIT", "15:15"), time(15, 15))
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
ENTRY_WINDOW_MIN = 15
MIN_DAYS_LEFT = 2                                # an expiry needs MORE trading days left than this
STOP_PCT = 0.20
TICK_S = 30
QUOTE_STALE_MIN = 10                             # no trade for longer than this: not a price to sell at
BSE_EXCHANGE_RATE = 0.000325                     # BSE index-option transaction charge on premium (NSE 0.03503%)
SWITCH = "index_auto"                            # Main Control: OFF stops entries, never exits

_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
_DB = os.getenv("INDEX_AUTO_MONGO_DB", "alpha_engine_index_auto")


def _open_store():
    if not _URL:
        return db
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(_URL, serverSelectionTimeoutMS=5000, maxPoolSize=10)[_DB]


STORE = _open_store()
POSITIONS = STORE["iauto_positions"]
RUNS = STORE["iauto_runs"]
EQUITY = STORE["iauto_equity"]
CONTRACTS = STORE["iauto_bse_contracts"]
STATE = STORE["iauto_state"]


def account_id(index: str, offset: int, size: int) -> str:
    return f"{index}:{offset}:{size}"


def strategy_label(offset: int) -> str:
    return "ATM" if offset == 0 else f"{offset} strike{'s' if offset > 1 else ''} away"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ist(t: datetime | None = None) -> datetime:
    return (t or _now()).astimezone(IST)


def _utc(t) -> datetime | None:
    if t is None:
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(t) -> str | None:
    t = _utc(t)
    return t.isoformat() if t else None


# -- the calendar ------------------------------------------------------------------------------------


def _trading_day(d: date) -> bool:
    from app.services import market_calendar
    return market_calendar.is_listed_trading_day(d)


def in_session(t: datetime | None = None) -> bool:
    from app.services import market_calendar
    t = _ist(t)
    return market_calendar.is_trading_day(t) and SESSION_OPEN <= t.time() < SESSION_CLOSE


def sessions_to(expiry: str, today: date) -> int:
    """Trading days from `today` to `expiry`, both counted (expiry day = 1, expired = 0)."""
    try:
        exp = date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return 0
    n, d = 0, today
    while d <= exp:
        n += _trading_day(d)
        d += timedelta(days=1)
    return n


def _next_trading_day_at(after: datetime, at: time, same_day_ok: bool) -> datetime | None:
    d = _ist(after).date()
    for i in range(20):
        if (i > 0 or same_day_ok) and _trading_day(d):
            t = datetime.combine(d, at, tzinfo=IST)
            if t > _ist(after):
                return t
        d += timedelta(days=1)
    return None


def scheduled_exit(entry: datetime) -> datetime | None:
    """EXIT_AT on the same day when it is later than the entry, else on the next trading day."""
    return _next_trading_day_at(entry, EXIT_AT, same_day_ok=EXIT_AT > _ist(entry).time())


def next_entry(after: datetime) -> datetime | None:
    t = _ist(after)
    today = datetime.combine(t.date(), ENTRY_AT, tzinfo=IST)
    if _trading_day(t.date()) and today <= t < today + timedelta(minutes=ENTRY_WINDOW_MIN):
        return today
    return _next_trading_day_at(after, ENTRY_AT, same_day_ok=True)


# -- BSE contracts: loaded from Angel's contract file, NSE ones come from the app's master --------------


_EXP = re.compile(r"^(\d{1,2})([A-Z]{3})(\d{4})$")
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _iso_expiry(v: str) -> str | None:
    m = _EXP.match((v or "").upper())
    if not m or m.group(2) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"


async def refresh_bse_contracts() -> dict:
    """SENSEX / BANKEX (and any other configured BSE index) options from Angel's contract file.

    The file is ~150k rows; it is walked one object at a time (JSONDecoder.raw_decode) so the
    150k dicts never exist at once - only the few thousand BFO index options are kept."""
    import httpx
    from app.services.angel_instruments import SCRIP_MASTER_URL
    names = {i for i in INDICES if INDEX_SPECS[i]["source"] == "bse"}
    if not names:
        return {"skipped": "no BSE index configured"}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(SCRIP_MASTER_URL)
        r.raise_for_status()
        text = r.content.decode("utf-8")
    del r
    dec, i, n = json.JSONDecoder(), text.index("[") + 1, len(text)
    today = _ist().date().isoformat()
    rows: list[dict] = []
    while i < n:
        while i < n and text[i] in " \r\n\t,":
            i += 1
        if i >= n or text[i] == "]":
            break
        obj, i = dec.raw_decode(text, i)
        if obj.get("exch_seg") != "BFO" or obj.get("instrumenttype") != "OPTIDX" or obj.get("name") not in names:
            continue
        sym = str(obj.get("symbol") or "")
        expiry = _iso_expiry(obj.get("expiry") or "")
        kind = sym[-2:]
        try:
            strike = round(float(obj.get("strike") or 0) / 100.0, 2)        # Angel quotes strikes in paise
            lot = int(float(obj.get("lotsize") or 0))
        except ValueError:
            continue
        if not expiry or expiry < today or kind not in ("CE", "PE") or strike <= 0 or lot <= 0:
            continue
        rows.append({"underlying_symbol": obj["name"], "expiry": expiry, "strike": strike, "option_type": kind,
                     "angel_token": str(obj.get("token")), "angel_tradingsymbol": sym, "lot_size": lot,
                     "angel_exchange": "BFO"})
    del text
    if rows:
        await CONTRACTS.delete_many({"underlying_symbol": {"$in": sorted(names)}})
        await CONTRACTS.insert_many(rows, ordered=False)
    await STATE.update_one({"_id": "bse_contracts"}, {"$set": {"at": _now(), "rows": len(rows)}}, upsert=True)
    return {"rows": len(rows), "indices": sorted(names)}


async def _contracts(index: str) -> tuple[dict[str, list[dict]], str]:
    """{expiry: [contract docs with an Angel token]} for an index, and its option exchange."""
    spec = INDEX_SPECS[index]
    coll = CONTRACTS if spec["source"] == "bse" else instruments_collection
    q = {"underlying_symbol": index, "angel_token": {"$ne": None}, "expiry": {"$gte": _ist().date().isoformat()}}
    if spec["source"] == "master":
        q["asset_class"] = "INDEX_OPTION"
    out: dict[str, list[dict]] = {}
    async for r in coll.find(q, {"strike": 1, "option_type": 1, "angel_token": 1, "angel_tradingsymbol": 1,
                                 "lot_size": 1, "expiry": 1}):
        out.setdefault(r["expiry"], []).append(r)
    return out, spec["exchange"]


# -- quotes, margin, charges -----------------------------------------------------------------------------


async def _spot(index: str) -> float | None:
    from app.services.angel_client import angel_client
    ex, tok = INDEX_SPECS[index]["spot"]
    try:
        q = await angel_client.full_quote({ex: [tok]})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[index_auto] %s index quote failed: %s", index, str(exc)[:120])
        return None
    v = (q.get(tok) or {}).get("ltp")
    return float(v) if v else None


def _trade_time(raw: str | None) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(raw or "", fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


async def _quotes(by_exchange: dict[str, list[str]]) -> dict[str, dict]:
    """{token: {ltp, bid, ask, bid_qty, fresh, why}} - fresh only in session, traded within
    QUOTE_STALE_MIN minutes, with both sides of the book."""
    from app.services.angel_client import angel_client
    raw: dict[str, dict] = {}
    for ex, toks in by_exchange.items():
        toks = [str(t) for t in dict.fromkeys(toks) if t]
        for i in range(0, len(toks), 50):
            try:
                raw.update(await angel_client.full_quote({ex: toks[i:i + 50]}))
            except Exception as exc:  # noqa: BLE001 - an unpriced leg waits, it is never invented
                logger.warning("[index_auto] %s FULL quote failed: %s", ex, str(exc)[:160])
            await asyncio.sleep(0.15)
    now = _ist()
    live = in_session(now)
    out: dict[str, dict] = {}
    for toks in by_exchange.values():
        for t in toks:
            r = raw.get(str(t))
            if not r:
                out[str(t)] = {"ltp": None, "bid": None, "ask": None, "bid_qty": None, "fresh": False, "why": "no quote"}
                continue
            q = {"ltp": r.get("ltp"), "bid": r.get("bid"), "ask": r.get("ask"), "bid_qty": r.get("bid_qty"),
                 "fresh": False, "why": ""}
            tt = _trade_time(r.get("trade_time"))
            if not live:
                q["why"] = "market closed"
            elif tt is None:
                q["why"] = "no last-trade time"
            elif (now - tt).total_seconds() / 60 > QUOTE_STALE_MIN:
                q["why"] = f"no trade for {(now - tt).total_seconds() / 60:.0f} min"
            elif not (q["bid"] and q["ask"] and q["ask"] >= q["bid"] > 0):
                q["why"] = "one-sided book"
            else:
                q["fresh"] = True
            out[str(t)] = q
    return out


async def _pair_margin(call: dict, put: dict, exchange: str, spot: float, expiry: str,
                       call_px: float, put_px: float) -> tuple[float | None, str]:
    """The broker's margin for ONE lot of each leg sold - Angel's calculator, else the SPAN-lite
    estimate."""
    from app.services.angel_client import angel_client
    positions = [{"exchange": exchange, "qty": int(c["lot_size"]), "price": 0, "productType": "CARRYFORWARD",
                  "token": str(c["angel_token"]), "tradeType": "SELL", "orderType": "MARKET"} for c in (call, put)]
    try:
        m = await angel_client.margin_batch(positions)
        if m and m > 0:
            return float(m), "angel"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[index_auto] Angel margin failed: %s", str(exc)[:120])
    try:
        from app.services import fno_margin
        t = max((datetime.combine(date.fromisoformat(expiry), SESSION_CLOSE, tzinfo=IST) - _ist()).total_seconds()
                / (365 * 86400), fno_margin.MIN_T_YEARS)
        legs = [{"kind": "OPTION", "option_type": c["option_type"], "strike": float(c["strike"]), "qty": int(c["lot_size"]),
                 "side": "SELL", "premium": px,
                 "iv": fno_margin.solve_iv(px, spot, float(c["strike"]), t, c["option_type"])}
                for c, px in ((call, call_px), (put, put_px))]
        m = fno_margin.portfolio_margin(legs, spot, t)["total"]
        return (float(m), "estimated (SPAN-lite)") if m and m > 0 else (None, "no margin figure")
    except Exception as exc:  # noqa: BLE001
        return None, f"no margin figure ({str(exc)[:80]})"


def _order_fees(premium: float, qty: int, sell: bool, on: date, exchange: str) -> dict:
    """Angel's charges for one executed option ORDER; BSE contracts at BSE's exchange rate."""
    from tradingai_shared.option_fees import GST, KEYS, option_leg
    f = option_leg(premium, qty, sell, on)
    if exchange == "BFO" and f["total"]:
        ex = max(premium, 0.0) * qty * BSE_EXCHANGE_RATE
        f = {**f, "exchange": round(ex, 2), "gst": round(GST * (f["brokerage"] + ex + f["sebi"]), 2)}
        f["total"] = round(sum(f[k] for k in KEYS), 2)
    return f


# -- the book --------------------------------------------------------------------------------------------


async def _book() -> dict[str, dict]:
    out: dict[str, dict] = {}
    async for r in POSITIONS.aggregate([
            {"$match": {"status": "CLOSED"}},
            {"$group": {"_id": "$account_id", "realized": {"$sum": {"$ifNull": ["$realized_pnl", 0]}},
                        "trades": {"$sum": 1},
                        "wins": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$realized_pnl", 0]}, 0]}, 1, 0]}},
                        "fees": {"$sum": {"$ifNull": ["$fees", 0]}}}}]):
        out[r["_id"]] = {"realized": float(r["realized"]), "trades": int(r["trades"]), "wins": int(r["wins"]),
                         "fees": float(r["fees"]), "open": None}
    async for p in POSITIONS.find({"status": "OPEN"}):
        out.setdefault(p["account_id"], {"realized": 0.0, "trades": 0, "wins": 0, "fees": 0.0})["open"] = p
    return out


def _equity(size: int, b: dict | None) -> float:
    b = b or {}
    o = b.get("open")
    return size + b.get("realized", 0.0) + ((o or {}).get("unrealized_pnl") or 0.0)


# -- entries ---------------------------------------------------------------------------------------------


async def _plan(index: str, day: date) -> dict:
    by_expiry, exchange = await _contracts(index)
    expiry = next((e for e in sorted(by_expiry) if sessions_to(e, day) > MIN_DAYS_LEFT), None)
    if not expiry:
        return {"why": "no listed expiry with more than 2 trading days left"
                       + ("" if by_expiry else " (no contracts on file)")}
    spot = await _spot(index)
    if not spot:
        return {"why": f"no live {INDEX_SPECS[index]['label']} price to set the at-the-money strike from"}
    by = {(float(c["strike"]), c["option_type"]): c for c in by_expiry[expiry]}
    ladder = sorted({k for k, t in by if (k, "CE") in by and (k, "PE") in by})
    atm = min(ladder, key=lambda k: abs(k - spot))
    i = ladder.index(atm)
    pairs: dict[int, dict] = {}
    for k in OFFSETS:
        if i + k >= len(ladder) or i - k < 0:
            pairs[k] = {"why": f"no listed strike {k} away from {atm:g}"}
        else:
            pairs[k] = {"call": by[(ladder[i + k], "CE")], "put": by[(ladder[i - k], "PE")]}
    quotes = await _quotes({exchange: [str(p[leg]["angel_token"]) for p in pairs.values() if "call" in p
                                       for leg in ("call", "put")]})
    for k, p in pairs.items():
        if "why" in p:
            continue
        qc, qp = quotes.get(str(p["call"]["angel_token"])), quotes.get(str(p["put"]["angel_token"]))
        bad = [f"{p[leg]['strike']:g} {p[leg]['option_type']}: {q['why'] if q else 'no quote'}"
               for leg, q in (("call", qc), ("put", qp)) if not (q and q["fresh"])]
        if bad:
            p["why"] = "no fresh two-sided quote (" + "; ".join(bad) + ")"
            continue
        m, src = await _pair_margin(p["call"], p["put"], exchange, spot, expiry, qc["bid"], qp["bid"])
        if not m:
            p["why"] = src
            continue
        p.update(qc=qc, qp=qp, margin=m, margin_source=src)
    return {"expiry": expiry, "spot": spot, "atm": atm, "pairs": pairs, "exchange": exchange,
            "lot_size": int(by_expiry[expiry][0]["lot_size"])}


def _leg_doc(c: dict, q: dict) -> dict:
    return {"strike": float(c["strike"]), "type": c["option_type"], "token": str(c["angel_token"]),
            "symbol": c.get("angel_tradingsymbol"), "entry": float(q["bid"]), "entry_bid": q["bid"],
            "entry_ask": q["ask"], "entry_ltp": q["ltp"], "touch_qty": q.get("bid_qty")}


def _new_position(index: str, k: int, size: int, plan: dict, pair: dict, equity: float, now: datetime) -> dict | str:
    m1 = float(pair["margin"])
    lots = int(equity // m1)
    if lots < 1:
        return f"one call+put lot pair needs Rs {m1:,.0f} of margin, the account has Rs {equity:,.0f}"
    lot_size = int(pair["call"]["lot_size"])
    qty = lots * lot_size
    day, ex = _ist(now).date(), plan["exchange"]
    call, put = _leg_doc(pair["call"], pair["qc"]), _leg_doc(pair["put"], pair["qp"])
    fc, fp = _order_fees(call["entry"], qty, True, day, ex), _order_fees(put["entry"], qty, True, day, ex)
    entry_fees = round(fc["total"] + fp["total"], 2)
    return {
        "account_id": account_id(index, k, size), "index": index, "instrument": index, "offset": k,
        "strategy": strategy_label(k), "size": size, "entry_day": day.isoformat(), "exchange": ex,
        "expiry": plan["expiry"], "spot_at_entry": plan["spot"], "atm_strike": plan["atm"],
        "call": call, "put": put, "lots": lots, "lot_size": lot_size, "qty": qty,
        "credit": round((call["entry"] + put["entry"]) * qty, 2),
        "margin_per_pair": round(m1, 2), "margin_source": pair["margin_source"],
        "margin_blocked": round(m1 * lots, 2), "allocated": round(equity, 2), "stop_loss": round(STOP_PCT * equity, 2),
        "entry_fees": entry_fees, "entry_fee_parts": {"call": fc, "put": fp},
        "entry_at": now, "scheduled_exit_at": scheduled_exit(now),
        "status": "OPEN", "unrealized_pnl": -entry_fees, "mark": None, "updated_at": now,
        "exit_at": None, "exit_reason": None, "exit_basis": None, "exit": None,
        "gross_pnl": None, "fees": None, "realized_pnl": None,
    }


async def _enter(now: datetime, book: dict[str, dict]) -> dict:
    day = _ist(now).date()
    outcome: dict[str, str] = {}
    rows: list[dict] = []
    for ix in INDICES:
        try:
            plan = await _plan(ix, day)
        except Exception as exc:  # noqa: BLE001 - one index's failure must not stop the others
            logger.warning("[index_auto] %s plan failed: %s", ix, exc, exc_info=True)
            plan = {"why": f"could not plan: {str(exc)[:120]}"}
        for k in OFFSETS:
            pair = (plan.get("pairs") or {}).get(k) or {}
            why = plan.get("why") or pair.get("why")
            for s in SIZES:
                aid = account_id(ix, k, s)
                if (book.get(aid) or {}).get("open"):
                    outcome[aid] = "skipped: its previous trade is still open"
                    continue
                if why:
                    outcome[aid] = f"skipped: {why}"
                    continue
                doc = _new_position(ix, k, s, plan, pair, _equity(s, book.get(aid)), now)
                if isinstance(doc, str):
                    outcome[aid] = f"skipped: {doc}"
                    continue
                rows.append(doc)
                outcome[aid] = (f"opened {doc['lots']} lot pair{'s' if doc['lots'] > 1 else ''} "
                                f"{doc['call']['strike']:g} CE / {doc['put']['strike']:g} PE {doc['expiry']}")
    if rows:
        try:
            await POSITIONS.insert_many(rows, ordered=False)
        except Exception as exc:  # noqa: BLE001 - a duplicate (account, day) is refused by the index
            logger.warning("[index_auto] some entries were not written: %s", str(exc)[:200])
    return outcome


# -- managing --------------------------------------------------------------------------------------------


def _exit_px(q: dict | None) -> tuple[float | None, str]:
    """Buying a short leg back: the fresh ask; failing that a stale ask, then the LTP - labelled."""
    if not q:
        return None, "no quote"
    if q["fresh"] and q["ask"]:
        return float(q["ask"]), "ask"
    if q["ask"]:
        return float(q["ask"]), "stale ask"
    if q["ltp"]:
        return float(q["ltp"]), "last traded price"
    return None, q.get("why") or "no price"


async def _close(p: dict, call_px: float, put_px: float, reason: str, basis: str, now: datetime) -> bool:
    qty, day, ex = int(p["qty"]), _ist(now).date(), p.get("exchange", "NFO")
    fc, fp = _order_fees(call_px, qty, False, day, ex), _order_fees(put_px, qty, False, day, ex)
    gross = (p["call"]["entry"] - call_px) * qty + (p["put"]["entry"] - put_px) * qty
    fees = round(p.get("entry_fees", 0.0) + fc["total"] + fp["total"], 2)
    res = await POSITIONS.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
        "status": "CLOSED", "exit_at": now, "exit_reason": reason, "exit_basis": basis,
        "exit": {"call": round(call_px, 2), "put": round(put_px, 2)},
        "exit_fee_parts": {"call": fc, "put": fp}, "gross_pnl": round(gross, 2), "fees": fees,
        "realized_pnl": round(gross - fees, 2), "unrealized_pnl": 0.0, "updated_at": now}})
    return res.modified_count == 1


def _intrinsic(leg: dict, spot: float) -> float:
    return max(0.0, spot - leg["strike"]) if leg["type"] == "CE" else max(0.0, leg["strike"] - spot)


async def _manage(now: datetime) -> dict:
    """Mark every open trade, take its stop, and close it once its scheduled exit has come."""
    open_rows = [p async for p in POSITIONS.find({"status": "OPEN"})]
    if not open_rows:
        return {"closed": {}, "marked": 0}
    by_ex: dict[str, list[str]] = {}
    for p in open_rows:
        by_ex.setdefault(p.get("exchange", "NFO"), []).extend([p["call"]["token"], p["put"]["token"]])
    quotes = await _quotes(by_ex)
    closed: dict[str, int] = {}
    marks: list[UpdateOne] = []
    today = _ist(now).date().isoformat()
    spots: dict[str, float | None] = {}
    for p in open_rows:
        qc, qp = quotes.get(p["call"]["token"]), quotes.get(p["put"]["token"])
        qty = int(p["qty"])
        if qc and qp and qc["fresh"] and qp["fresh"]:
            loss = -((p["call"]["entry"] - qc["ask"]) * qty + (p["put"]["entry"] - qp["ask"]) * qty)
            if loss >= p["stop_loss"]:
                if await _close(p, float(qc["ask"]), float(qp["ask"]), "stoploss", "ask", now):
                    closed["stoploss"] = closed.get("stoploss", 0) + 1
                continue
        due = p.get("scheduled_exit_at") and now >= _utc(p["scheduled_exit_at"])
        expired = p.get("expiry") and p["expiry"] < today
        if due or expired:
            if expired:
                # only when every exit before expiry was missed: intrinsic on the index now, labelled
                if p["index"] not in spots:
                    spots[p["index"]] = await _spot(p["index"])
                s = spots[p["index"]]
                (cx, cb), (px, pb) = ((_intrinsic(p["call"], s), "intrinsic on the index now"),
                                      (_intrinsic(p["put"], s), "intrinsic on the index now")) if s else ((None, ""), (None, ""))
            else:
                (cx, cb), (px, pb) = _exit_px(qc), _exit_px(qp)
            if cx is not None and px is not None:
                reason = "expired" if expired else "scheduled"
                if await _close(p, cx, px, reason, cb if cb == pb else f"call {cb}, put {pb}", now):
                    closed[reason] = closed.get(reason, 0) + 1
                continue
        cm = qc["ask"] if qc and qc["fresh"] else (qc["ltp"] if qc else None)
        pm = qp["ask"] if qp and qp["fresh"] else (qp["ltp"] if qp else None)
        if cm is None or pm is None:
            continue
        gross = (p["call"]["entry"] - cm) * qty + (p["put"]["entry"] - pm) * qty
        marks.append(UpdateOne({"_id": p["_id"], "status": "OPEN"}, {"$set": {
            "unrealized_pnl": round(gross - p.get("entry_fees", 0.0), 2), "updated_at": now,
            "mark": {"call": round(cm, 2), "put": round(pm, 2),
                     "basis": "ask" if (qc["fresh"] and qp["fresh"]) else "last traded price"}}}))
    if marks:
        await POSITIONS.bulk_write(marks, ordered=False)
    return {"closed": closed, "marked": len(marks)}


# -- the cycle -------------------------------------------------------------------------------------------


_lock = asyncio.Lock()
_indexed = False


async def _snapshot(day: str, book: dict[str, dict]) -> None:
    now = _now()
    ops = [UpdateOne({"_id": f"{day}:{account_id(ix, k, s)}"}, {"$set": {
        "day": day, "account_id": account_id(ix, k, s),
        "equity": round(_equity(s, book.get(account_id(ix, k, s))), 2),
        "realized": round((book.get(account_id(ix, k, s)) or {}).get("realized", 0.0), 2), "at": now}}, upsert=True)
        for ix in INDICES for k in OFFSETS for s in SIZES]
    if ops:
        await EQUITY.bulk_write(ops, ordered=False)


async def _contracts_fresh(now: datetime) -> None:
    """Reload the BSE contracts once a day, never inside the entry window."""
    if not any(INDEX_SPECS[i]["source"] == "bse" for i in INDICES):
        return
    t = _ist(now)
    start = datetime.combine(t.date(), ENTRY_AT, tzinfo=IST)
    if start - timedelta(minutes=10) <= t < start + timedelta(minutes=ENTRY_WINDOW_MIN):
        return
    st = await STATE.find_one({"_id": "bse_contracts"}) or {}
    if st.get("at") and _now() - _utc(st["at"]) < timedelta(hours=20) and st.get("rows"):
        return
    try:
        r = await refresh_bse_contracts()
        logger.warning("[index_auto] BSE option contracts loaded: %s", r)   # WARNING: the app shows no INFO lines
    except Exception:  # noqa: BLE001
        logger.warning("[index_auto] BSE contract load failed", exc_info=True)
        await STATE.update_one({"_id": "bse_contracts"}, {"$set": {"failed_at": _now()}}, upsert=True)


async def tick(now: datetime | None = None) -> dict:
    """One pass: in session, manage every open trade; in the entry window on a trading day, enter."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    now = now or _now()
    await _contracts_fresh(now)
    ist = _ist(now)
    if not in_session(ist):
        return {"market": "closed"}
    async with _lock:
        out = {"manage": await _manage(now)}
        start = datetime.combine(ist.date(), ENTRY_AT, tzinfo=IST)
        if not (start <= ist < start + timedelta(minutes=ENTRY_WINDOW_MIN)):
            return out
        day = ist.date().isoformat()
        if await RUNS.find_one({"_id": day, "finished_at": {"$ne": None}}, {"_id": 1}):
            return out
        from app.services.desk_switches import is_on
        await RUNS.update_one({"_id": day}, {"$set": {"started_at": now}}, upsert=True)
        if not await is_on(SWITCH):
            outcome = {account_id(ix, k, s): "skipped: Main Control has Indian Market Option Auto Selling OFF"
                       for ix in INDICES for k in OFFSETS for s in SIZES}
        else:
            outcome = await _enter(now, await _book())
        counts: dict[str, int] = {}
        for v in outcome.values():
            key = "opened" if v.startswith("opened") else v.split(" (")[0]
            counts[key] = counts.get(key, 0) + 1
        await RUNS.update_one({"_id": day}, {"$set": {
            "finished_at": _now(), "outcome": outcome, "counts": counts, "closed_before": out["manage"]["closed"]}})
        await _snapshot(day, await _book())
        out["entry"] = counts
        return out


async def loop() -> None:
    if not _URL:
        logger.warning("[index_auto] FACTORY_MONGO_URL is unset: records go to the main database %r", STORE.name)
    await asyncio.sleep(75)
    while True:
        try:
            r = await tick()
            if r.get("entry") or (r.get("manage") or {}).get("closed"):
                logger.warning("[index_auto] %s", r)        # WARNING: the app shows no INFO lines
        except Exception:  # noqa: BLE001
            logger.warning("[index_auto] tick failed", exc_info=True)
        await asyncio.sleep(TICK_S)


async def ensure_indexes() -> None:
    try:
        await POSITIONS.create_index([("status", 1)], name="ia_status")
        await POSITIONS.create_index([("account_id", 1), ("entry_day", 1)], name="ia_account_day", unique=True)
        await POSITIONS.create_index([("index", 1), ("status", 1), ("exit_at", -1)], name="ia_index_exit")
        await EQUITY.create_index([("account_id", 1), ("day", 1)], name="ia_equity_account_day")
        await CONTRACTS.create_index([("underlying_symbol", 1), ("expiry", 1)], name="ia_contract_expiry")
    except Exception:  # noqa: BLE001 - an index is a speed-up, never a precondition
        logger.warning("[index_auto] index creation skipped", exc_info=True)


# -- read side -------------------------------------------------------------------------------------------


def _pos_view(p: dict | None) -> dict | None:
    if not p:
        return None
    keep = ("index", "instrument", "exchange", "offset", "strategy", "size", "entry_day", "expiry", "spot_at_entry",
            "atm_strike", "call", "put", "lots", "lot_size", "qty", "credit", "margin_per_pair", "margin_source",
            "margin_blocked", "allocated", "stop_loss", "entry_fees", "status", "unrealized_pnl", "mark",
            "exit_reason", "exit_basis", "exit", "gross_pnl", "fees", "realized_pnl", "account_id")
    out = {k: p.get(k) for k in keep}
    for k in ("entry_at", "scheduled_exit_at", "exit_at", "updated_at"):
        out[k] = _iso(p.get(k))
    out["id"] = str(p.get("_id"))
    return out


async def _lot_sizes() -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for ix in INDICES:
        spec = INDEX_SPECS[ix]
        coll = CONTRACTS if spec["source"] == "bse" else instruments_collection
        q = {"underlying_symbol": ix, "angel_token": {"$ne": None}, "expiry": {"$gte": _ist().date().isoformat()}}
        if spec["source"] == "master":
            q["asset_class"] = "INDEX_OPTION"
        d = await coll.find_one(q, {"lot_size": 1}, sort=[("expiry", 1)])
        out[ix] = int(d["lot_size"]) if d and d.get("lot_size") else None
    return out


async def summary() -> dict:
    from app.services.desk_switches import is_on
    book = await _book()
    per: dict[str, dict] = {}
    for ix in INDICES:
        t = {"starting": 0.0, "equity": 0.0, "realized": 0.0, "unrealized": 0.0, "open": 0, "trades": 0, "wins": 0}
        for k in OFFSETS:
            for s in SIZES:
                b = book.get(account_id(ix, k, s)) or {}
                t["starting"] += s
                t["equity"] += _equity(s, b)
                t["realized"] += b.get("realized", 0.0)
                t["trades"] += b.get("trades", 0)
                t["wins"] += b.get("wins", 0)
                if b.get("open"):
                    t["open"] += 1
                    t["unrealized"] += b["open"].get("unrealized_pnl") or 0.0
        per[ix] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()}
    lots = await _lot_sizes()
    last = await RUNS.find_one({}, {"outcome": 0}, sort=[("_id", -1)])
    bse = await STATE.find_one({"_id": "bse_contracts"}) or {}
    return {
        "instruments": list(INDICES),
        "instrument_info": {ix: {"label": INDEX_SPECS[ix]["label"],
                                 "sub": f"{INDEX_SPECS[ix]['exchange']} · lot {lots.get(ix) or '—'}"} for ix in INDICES},
        "strategies": [{"offset": k, "label": strategy_label(k)} for k in OFFSETS],
        "sizes": list(SIZES), "accounts": len(INDICES) * len(OFFSETS) * len(SIZES), "stop_pct": STOP_PCT,
        "per_instrument": per, "market_open": in_session(), "market_label": "NSE / BSE",
        "entry_label": f"{ENTRY_AT:%H:%M} IST → {EXIT_AT:%H:%M} IST{' next trading day' if EXIT_AT <= ENTRY_AT else ''}",
        "switch_on": await is_on(SWITCH), "next_entry_at": _iso(next_entry(_now())),
        "last_run": ({"day": last["_id"], "started_at": _iso(last.get("started_at")),
                      "finished_at": _iso(last.get("finished_at")), "counts": last.get("counts") or {},
                      "closed_before": last.get("closed_before") or {}} if last else None),
        "bse_contracts": {"at": _iso(bse.get("at")), "rows": bse.get("rows")},
        "store": STORE.name,
    }


async def accounts(index: str) -> list[dict]:
    book = await _book()
    last_run = await RUNS.find_one({}, sort=[("_id", -1)]) or {}
    outcome = last_run.get("outcome") or {}
    last_closed: dict[str, dict] = {}
    async for p in POSITIONS.find({"index": index, "status": "CLOSED"}).sort("exit_at", -1).limit(400):
        last_closed.setdefault(p["account_id"], p)
    rows = []
    for k in OFFSETS:
        for s in SIZES:
            aid = account_id(index, k, s)
            b = book.get(aid) or {}
            o = b.get("open")
            eq = _equity(s, b)
            rows.append({
                "account_id": aid, "instrument": index, "offset": k, "strategy": strategy_label(k), "size": s,
                "starting_capital": s, "equity": round(eq, 2),
                "available": round(eq - ((o or {}).get("margin_blocked") or 0.0), 2),
                "margin_used": round((o or {}).get("margin_blocked") or 0.0, 2),
                "realized": round(b.get("realized", 0.0), 2), "trades": b.get("trades", 0), "wins": b.get("wins", 0),
                "fees": round(b.get("fees", 0.0), 2),
                "open": _pos_view(o), "last_closed": _pos_view(last_closed.get(aid)),
                "last_entry": {"day": last_run.get("_id"), "outcome": outcome.get(aid)} if last_run else None,
            })
    return rows


async def trades(index: str | None = None, offset: int | None = None, size: int | None = None,
                 limit: int = 200) -> list[dict]:
    q: dict = {"status": "CLOSED"}
    if index:
        q["index"] = index
    if offset is not None:
        q["offset"] = offset
    if size is not None:
        q["size"] = size
    return [_pos_view(p) async for p in POSITIONS.find(q).sort("exit_at", -1).limit(limit)]


async def runs(limit: int = 10) -> list[dict]:
    return [{"day": r["_id"], "started_at": _iso(r.get("started_at")), "finished_at": _iso(r.get("finished_at")),
             "counts": r.get("counts") or {}, "closed_before": r.get("closed_before") or {}}
            async for r in RUNS.find({}, {"outcome": 0}).sort("_id", -1).limit(limit)]
