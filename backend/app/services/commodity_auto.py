"""Commodity Auto Positions (2026-10-30): 220 paper accounts that sell an MCX option strangle every
evening on the four mini contracts.

The owner's rules, as confirmed:
  - Four commodities: NATGASMINI, CRUDEOILM, GOLDM, SILVERM - the minis, the smallest lot per market.
  - Eleven strategies each: sell the call k strikes above the at-the-money strike and the put k
    strikes below it, k = 0 (ATM) .. 10, counted on the listed strike ladder.
  - Five account sizes per strategy: Rs 5 lakh, 10 lakh, 20 lakh, 50 lakh and 1 crore. 4 x 11 x 5 =
    220 accounts; no capital is shared between any two of them.
  - Entry at 22:00 IST on every MCX trading day whose evening session is open; exit at 22:00 on the
    next such day, then a fresh entry. Entries are taken only 22:00-22:30, so a restart late in the
    evening never opens a whole day's trades at 23:20; an exit that falls due is taken whenever MCX
    is next open.
  - Expiry: the nearest listed option expiry with MORE than two MCX trading days left (expiry day =
    1), checked per commodity at every entry - so a trade is never held into expiry day.
  - Sizing: the whole account is allocated. Lots = account equity / the broker's margin for one
    call + put lot pair, rounded down; the stop is 20% of that allocation on the combined pair, and
    after a stop the account waits for the next 22:00 entry.
  - Fills: sold at the bid, bought back at the ask, from Angel's FULL quote. A leg with no fresh
    two-sided quote at entry skips that strategy for the day. Every order pays Angel's MCX option
    charges (angel_commodity_ledger's card, which matched Angel's own report to the paisa).

ATM is the listed strike nearest the underlying FUTURE: MCX options are written on the future. The
stop is checked every 30 s while MCX is open, on what buying both legs back at the ask would cost
against the premium collected; between sessions nothing trades, so a gap can carry the loss past 20%
before the first quote. Fills assume the touch for any size - the biggest accounts would move a thin
book - and the margin shown is the broker's figure at entry.

Records live in the box's second MongoDB (FACTORY_MONGO_URL, the compose `mongodb` service), not on
the Atlas cluster that holds everything else. Contracts, quotes and margins come from the main app.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time, timedelta, timezone

from pymongo import UpdateOne

from app.core.db import db, instruments_collection
from tradingai_shared import mcx_calendar as mc

logger = logging.getLogger("commodity_auto")

IST = timezone(timedelta(hours=5, minutes=30))
MINIS = ("NATGASMINI", "CRUDEOILM", "GOLDM", "SILVERM")
OFFSETS = tuple(range(11))                       # 0 = ATM, k = k strikes away
SIZES = (500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000)
ENTRY_AT = time(22, 0)
ENTRY_WINDOW_MIN = 30
MIN_DAYS_LEFT = 2                                # an expiry needs MORE MCX trading days left than this
STOP_PCT = 0.20
TICK_S = 30
SWITCH = "commodity_auto"                        # Main Control: OFF stops entries, never exits

_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
_DB = os.getenv("COMMODITY_AUTO_MONGO_DB", "alpha_engine_commodity_auto")


def _open_store():
    if not _URL:
        return db
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(_URL, serverSelectionTimeoutMS=5000, maxPoolSize=10)[_DB]


STORE = _open_store()
POSITIONS = STORE["cauto_positions"]
RUNS = STORE["cauto_runs"]
EQUITY = STORE["cauto_equity"]


def account_id(commodity: str, offset: int, size: int) -> str:
    return f"{commodity}:{offset}:{size}"


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


def cycle_time(d: date) -> datetime | None:
    """22:00 IST on `d` when an MCX session is open then, else None (a holiday or weekend)."""
    t = datetime.combine(d, ENTRY_AT, tzinfo=IST)
    return t if any(start <= t < end for start, end, _name in mc.sessions(d)) else None


def next_cycle_after(t: datetime) -> datetime | None:
    d = _ist(t).date()
    for _ in range(20):
        c = cycle_time(d)
        if c is not None and c > _ist(t):
            return c
        d += timedelta(days=1)
    return None


# -- quotes, charges -----------------------------------------------------------------------------------


async def _quotes(tokens: list[str]):
    """{token: McxQuote} from Angel's FULL quote, judged fresh by the commodity desk's own rule (a
    trade this session, recently, and a two-sided book). Not written to the desk's quote log."""
    from app.services.angel_client import angel_client
    from app.services.mcx_market import McxQuote, judge, parse_trade_time
    toks = [str(t) for t in dict.fromkeys(tokens) if t]
    raw: dict[str, dict] = {}
    for i in range(0, len(toks), 50):
        try:
            raw.update(await angel_client.full_quote({"MCX": toks[i:i + 50]}))
        except Exception as exc:  # noqa: BLE001 - an unpriced leg waits, it is never invented
            logger.warning("[commodity_auto] MCX FULL quote failed: %s", str(exc)[:160])
    now = _ist()
    out = {}
    for tok in toks:
        r = raw.get(tok)
        if not r:
            out[tok] = McxQuote(token=tok, ltp=None, fresh=False, why="no quote returned")
            continue
        tt = parse_trade_time(r.get("trade_time"))
        fresh, why, session = judge(tt, now)
        q = McxQuote(token=tok, ltp=r.get("ltp"), bid=r.get("bid"), ask=r.get("ask"),
                     bid_qty=r.get("bid_qty"), ask_qty=r.get("ask_qty"), oi=r.get("oi"),
                     volume=r.get("volume"), trade_time=tt.isoformat() if tt else None,
                     fresh=fresh, why=why, session=session)
        if q.fresh and q.mid is None:
            q.fresh, q.why = False, "one-sided or crossed book"
        out[tok] = q
    return out


def _order_fees(premium: float, qty: int, sell: bool, on: date) -> dict:
    """Angel's charges for one MCX option ORDER (qty in price units: lots x multiplier)."""
    from app.services.angel_commodity_ledger import _option_order_breakdown
    return _option_order_breakdown(max(premium, 0.0) * qty, sell, on)


# -- the book --------------------------------------------------------------------------------------------


async def _book() -> dict[str, dict]:
    """Per account: realised P&L, closed trades, wins (summed by the database) and the open trade."""
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


async def _plan(commodity: str, day: date) -> dict:
    """One mini's entry for the day: the expiry, the future, the ATM strike and, per strategy, the
    call/put pair with its quotes and the broker's margin for one lot pair - or why there is none."""
    from app.services import commodity_positions as cp
    expiries = await cp.option_expiries(commodity)
    expiry = next((e for e in expiries if mc.trading_days_to(e, day) > MIN_DAYS_LEFT), None)
    if not expiry:
        return {"why": "no listed expiry with more than 2 MCX trading days left"}
    ref, fut = await cp.future_price(commodity, expiry)
    if not ref:
        return {"why": f"no live {commodity} future to set the at-the-money strike from"}
    by: dict[tuple[float, str], dict] = {}
    async for r in instruments_collection.find(
            {"underlying_symbol": commodity, "expiry": expiry, "asset_class": cp.OPTION_CLASS,
             "angel_token": {"$ne": None}},
            {"strike": 1, "option_type": 1, "angel_token": 1, "angel_tradingsymbol": 1, "symbol": 1}):
        if r.get("strike") is not None and r.get("option_type") in ("CE", "PE"):
            by[(float(r["strike"]), r["option_type"])] = r
    ladder = sorted({k for k, t in by if (k, "CE") in by and (k, "PE") in by})
    if not ladder:
        return {"why": f"no listed {commodity} {expiry} strikes"}
    atm = min(ladder, key=lambda k: abs(k - ref))
    i = ladder.index(atm)
    pairs: dict[int, dict] = {}
    for k in OFFSETS:
        if i + k >= len(ladder) or i - k < 0:
            pairs[k] = {"why": f"no listed strike {k} away from {atm:g}"}
        else:
            pairs[k] = {"call": by[(ladder[i + k], "CE")], "put": by[(ladder[i - k], "PE")]}
    quotes = await _quotes([str(p[leg]["angel_token"]) for p in pairs.values() if "call" in p for leg in ("call", "put")])
    for k, p in pairs.items():
        if "why" in p:
            continue
        qc, qp = quotes.get(str(p["call"]["angel_token"])), quotes.get(str(p["put"]["angel_token"]))
        bad = [f"{p[leg]['strike']:g} {leg[0].upper()}E: {q.why if q else 'no quote'}"
               for leg, q in (("call", qc), ("put", qp)) if not (q and q.fresh and q.bid and q.ask)]
        if bad:
            p["why"] = "no fresh two-sided quote (" + "; ".join(bad) + ")"
            continue
        legs = [cp._broker_leg(p["call"], "SELL", 1, ref_price=ref, underlying=commodity),
                cp._broker_leg(p["put"], "SELL", 1, ref_price=ref, underlying=commodity)]
        m = await cp._margin_now(legs)
        if not m.get("total") or m["total"] <= 0:
            p["why"] = "no margin figure for the pair"
            continue
        p.update(qc=qc, qp=qp, margin=m)
    return {"expiry": expiry, "future": float(ref), "future_symbol": (fut or {}).get("angel_tradingsymbol"),
            "atm": atm, "pairs": pairs, "multiplier": cp.multiplier(commodity)}


def _leg_doc(inst: dict, q, price: float) -> dict:
    return {"strike": float(inst["strike"]), "type": inst["option_type"], "token": str(inst["angel_token"]),
            "symbol": inst.get("angel_tradingsymbol") or inst.get("symbol"), "entry": float(price),
            "entry_bid": q.bid, "entry_ask": q.ask, "entry_ltp": q.ltp,
            "touch_qty": q.bid_qty}


def _new_position(commodity: str, k: int, size: int, plan: dict, pair: dict, equity: float,
                  now: datetime) -> dict | str:
    m1 = float(pair["margin"]["total"])
    lots = int(equity // m1)
    if lots < 1:
        return f"one call+put lot pair needs Rs {m1:,.0f} of margin, the account has Rs {equity:,.0f}"
    qty = lots * int(plan["multiplier"])
    day = _ist(now).date()
    call, put = _leg_doc(pair["call"], pair["qc"], pair["qc"].bid), _leg_doc(pair["put"], pair["qp"], pair["qp"].bid)
    fc, fp = _order_fees(call["entry"], qty, True, day), _order_fees(put["entry"], qty, True, day)
    entry_fees = round(fc["total"] + fp["total"], 2)
    return {
        "account_id": account_id(commodity, k, size), "commodity": commodity, "instrument": commodity, "offset": k,
        "strategy": strategy_label(k), "size": size, "entry_day": day.isoformat(),
        "expiry": plan["expiry"], "future_at_entry": plan["future"], "future_symbol": plan["future_symbol"],
        "atm_strike": plan["atm"], "call": call, "put": put,
        "lots": lots, "multiplier": int(plan["multiplier"]), "qty": qty,
        "credit": round((call["entry"] + put["entry"]) * qty, 2),
        "margin_per_pair": round(m1, 2), "margin_source": pair["margin"].get("source"),
        "margin_blocked": round(m1 * lots, 2), "allocated": round(equity, 2),
        "stop_loss": round(STOP_PCT * equity, 2),
        "entry_fees": entry_fees, "entry_fee_parts": {"call": fc, "put": fp},
        "entry_at": now, "scheduled_exit_at": next_cycle_after(now),
        "status": "OPEN", "unrealized_pnl": -entry_fees, "mark": None, "updated_at": now,
        "exit_at": None, "exit_reason": None, "exit_basis": None, "exit": None,
        "gross_pnl": None, "fees": None, "realized_pnl": None,
    }


async def _enter(now: datetime, book: dict[str, dict]) -> dict:
    """The 22:00 entry for all 220 accounts; returns what each did."""
    from app.services import commodity_positions as cp
    await cp.prime_lotsizes()
    day = _ist(now).date()
    outcome: dict[str, str] = {}
    rows: list[dict] = []
    for u in MINIS:
        try:
            plan = await _plan(u, day)
        except Exception as exc:  # noqa: BLE001 - one market's failure must not stop the other three
            logger.warning("[commodity_auto] %s plan failed: %s", u, exc, exc_info=True)
            plan = {"why": f"could not plan: {str(exc)[:120]}"}
        for k in OFFSETS:
            pair = (plan.get("pairs") or {}).get(k) or {}
            why = plan.get("why") or pair.get("why")
            for s in SIZES:
                aid = account_id(u, k, s)
                if (book.get(aid) or {}).get("open"):
                    outcome[aid] = "skipped: its previous trade is still open"
                    continue
                if why:
                    outcome[aid] = f"skipped: {why}"
                    continue
                doc = _new_position(u, k, s, plan, pair, _equity(s, book.get(aid)), now)
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
            logger.warning("[commodity_auto] some entries were not written: %s", str(exc)[:200])
    return outcome


# -- managing --------------------------------------------------------------------------------------------


def _exit_px(q, leg: dict) -> tuple[float | None, str]:
    """Buying a short leg back: the fresh ask; failing that a stale ask, then the LTP - labelled."""
    if q is None:
        return None, "no quote"
    if q.fresh and q.ask:
        return float(q.ask), "ask"
    if q.ask:
        return float(q.ask), "stale ask"
    if q.ltp:
        return float(q.ltp), "last traded price"
    return None, q.why or "no price"


async def _settle(p: dict, leg: str, q) -> tuple[float | None, str]:
    """A leg past its expiry (only when every exit before it was missed) settles the commodity
    desk's way - intrinsic against the future's settlement, else its own last mark, labelled -
    and only then on whatever its quote still shows."""
    from app.services import commodity_positions as cp
    try:
        return await cp.settlement_price({"underlying_symbol": p["commodity"], "expiry": p["expiry"],
                                          "strike": p[leg]["strike"], "option_type": p[leg]["type"]},
                                         (p.get("mark") or {}).get(leg))
    except Exception:  # noqa: BLE001
        return _exit_px(q, p[leg])


async def _close(p: dict, call_px: float, put_px: float, reason: str, basis: str, now: datetime) -> bool:
    qty, day = int(p["qty"]), _ist(now).date()
    fc, fp = _order_fees(call_px, qty, False, day), _order_fees(put_px, qty, False, day)
    gross = (p["call"]["entry"] - call_px) * qty + (p["put"]["entry"] - put_px) * qty
    fees = round(p.get("entry_fees", 0.0) + fc["total"] + fp["total"], 2)
    res = await POSITIONS.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
        "status": "CLOSED", "exit_at": now, "exit_reason": reason, "exit_basis": basis,
        "exit": {"call": round(call_px, 2), "put": round(put_px, 2)},
        "exit_fee_parts": {"call": fc, "put": fp}, "gross_pnl": round(gross, 2), "fees": fees,
        "realized_pnl": round(gross - fees, 2), "unrealized_pnl": 0.0, "updated_at": now}})
    return res.modified_count == 1


async def _manage(now: datetime) -> dict:
    """Mark every open trade, take its stop, and close it once its scheduled exit has come."""
    open_rows = [p async for p in POSITIONS.find({"status": "OPEN"})]
    if not open_rows:
        return {"closed": {}, "marked": 0}
    quotes = await _quotes([p[leg]["token"] for p in open_rows for leg in ("call", "put")])
    closed: dict[str, int] = {}
    marks: list[UpdateOne] = []
    today = _ist(now).date().isoformat()
    for p in open_rows:
        qc, qp = quotes.get(p["call"]["token"]), quotes.get(p["put"]["token"])
        qty = int(p["qty"])
        # the stop: what buying both legs back at a FRESH ask would cost, against the premium collected
        if qc and qp and qc.fresh and qp.fresh and qc.ask and qp.ask:
            loss = -((p["call"]["entry"] - qc.ask) * qty + (p["put"]["entry"] - qp.ask) * qty)
            if loss >= p["stop_loss"]:
                if await _close(p, float(qc.ask), float(qp.ask), "stoploss", "ask", now):
                    closed["stoploss"] = closed.get("stoploss", 0) + 1
                continue
        due = p.get("scheduled_exit_at") and now >= _utc(p["scheduled_exit_at"])
        expired = p.get("expiry") and p["expiry"] < today
        if due or expired:
            if expired:
                (cx, cb), (px, pb) = await _settle(p, "call", qc), await _settle(p, "put", qp)
            else:
                (cx, cb), (px, pb) = _exit_px(qc, p["call"]), _exit_px(qp, p["put"])
            if cx is not None and px is not None:
                basis = cb if cb == pb else f"call {cb}, put {pb}"
                reason = "expired" if expired else "scheduled"
                if await _close(p, cx, px, reason, basis, now):
                    closed[reason] = closed.get(reason, 0) + 1
                continue
        # the mark: the ask when it is fresh, else the last traded price (labelled)
        cm = (qc.ask if qc and qc.fresh and qc.ask else (qc.ltp if qc else None))
        pm = (qp.ask if qp and qp.fresh and qp.ask else (qp.ltp if qp else None))
        if cm is None or pm is None:
            continue
        gross = (p["call"]["entry"] - cm) * qty + (p["put"]["entry"] - pm) * qty
        marks.append(UpdateOne({"_id": p["_id"], "status": "OPEN"}, {"$set": {
            "unrealized_pnl": round(gross - p.get("entry_fees", 0.0), 2), "updated_at": now,
            "mark": {"call": round(cm, 2), "put": round(pm, 2),
                     "basis": "ask" if (qc.fresh and qp.fresh) else "last traded price"}}}))
    if marks:
        await POSITIONS.bulk_write(marks, ordered=False)
    return {"closed": closed, "marked": len(marks)}


# -- the cycle -------------------------------------------------------------------------------------------


_lock = asyncio.Lock()
_indexed = False


async def _snapshot(day: str, book: dict[str, dict]) -> None:
    now = _now()
    ops = []
    for u in MINIS:
        for k in OFFSETS:
            for s in SIZES:
                aid = account_id(u, k, s)
                b = book.get(aid) or {}
                ops.append(UpdateOne({"_id": f"{day}:{aid}"}, {"$set": {
                    "day": day, "account_id": aid, "equity": round(_equity(s, b), 2),
                    "realized": round(b.get("realized", 0.0), 2), "at": now}}, upsert=True))
    await EQUITY.bulk_write(ops, ordered=False)


async def tick(now: datetime | None = None) -> dict:
    """One pass: while MCX is open, manage every open trade; at 22:00-22:30 on a cycle day, enter."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    now = now or _now()
    ist = _ist(now)
    if not mc.is_open(ist):
        return {"mcx": "closed"}
    async with _lock:
        out = {"manage": await _manage(now)}
        c = cycle_time(ist.date())
        if c is None or not (c <= ist < c + timedelta(minutes=ENTRY_WINDOW_MIN)):
            return out
        day = ist.date().isoformat()
        if await RUNS.find_one({"_id": day, "finished_at": {"$ne": None}}, {"_id": 1}):
            return out
        from app.services.desk_switches import is_on
        await RUNS.update_one({"_id": day}, {"$set": {"started_at": now}}, upsert=True)
        if not await is_on(SWITCH):
            outcome = {account_id(u, k, s): "skipped: Main Control has Commodity Auto Positions OFF"
                       for u in MINIS for k in OFFSETS for s in SIZES}
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
        logger.warning("[commodity_auto] FACTORY_MONGO_URL is unset: records go to the main database %r", STORE.name)
    await asyncio.sleep(60)
    while True:
        try:
            r = await tick()
            if r.get("entry") or (r.get("manage") or {}).get("closed"):
                logger.warning("[commodity_auto] %s", r)        # WARNING: the app shows no INFO lines
        except Exception:  # noqa: BLE001
            logger.warning("[commodity_auto] tick failed", exc_info=True)
        await asyncio.sleep(TICK_S)


async def ensure_indexes() -> None:
    try:
        await POSITIONS.create_index([("status", 1)], name="ca_status")
        await POSITIONS.create_index([("account_id", 1), ("entry_day", 1)], name="ca_account_day", unique=True)
        await POSITIONS.create_index([("commodity", 1), ("status", 1), ("exit_at", -1)], name="ca_commodity_exit")
        await EQUITY.create_index([("account_id", 1), ("day", 1)], name="ca_equity_account_day")
    except Exception:  # noqa: BLE001 - an index is a speed-up, never a precondition
        logger.warning("[commodity_auto] index creation skipped", exc_info=True)


# -- read side -------------------------------------------------------------------------------------------


def _pos_view(p: dict | None) -> dict | None:
    if not p:
        return None
    keep = ("commodity", "instrument", "offset", "strategy", "size", "entry_day", "expiry", "future_at_entry", "atm_strike",
            "call", "put", "lots", "multiplier", "qty", "credit", "margin_per_pair", "margin_source",
            "margin_blocked", "allocated", "stop_loss", "entry_fees", "status", "unrealized_pnl", "mark",
            "exit_reason", "exit_basis", "exit", "gross_pnl", "fees", "realized_pnl", "account_id")
    out = {k: p.get(k) for k in keep}
    for k in ("entry_at", "scheduled_exit_at", "exit_at", "updated_at"):
        out[k] = _iso(p.get(k))
    out["id"] = str(p.get("_id"))
    out["instrument"] = p.get("commodity")
    return out


LOT_LABEL = {"NATGASMINI": "250 mmBtu a lot", "CRUDEOILM": "10 barrels a lot", "GOLDM": "100 grams a lot",
             "SILVERM": "5 kg a lot"}


async def summary() -> dict:
    from app.services.desk_switches import is_on
    book = await _book()
    per: dict[str, dict] = {}
    for u in MINIS:
        t = {"starting": 0.0, "equity": 0.0, "realized": 0.0, "unrealized": 0.0, "open": 0, "trades": 0, "wins": 0}
        for k in OFFSETS:
            for s in SIZES:
                b = book.get(account_id(u, k, s)) or {}
                t["starting"] += s
                t["equity"] += _equity(s, b)
                t["realized"] += b.get("realized", 0.0)
                t["trades"] += b.get("trades", 0)
                t["wins"] += b.get("wins", 0)
                if b.get("open"):
                    t["open"] += 1
                    t["unrealized"] += b["open"].get("unrealized_pnl") or 0.0
        per[u] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()}
    last = await RUNS.find_one({}, {"outcome": 0}, sort=[("_id", -1)])
    now = _ist()
    nxt = cycle_time(now.date())
    if nxt is None or now >= nxt + timedelta(minutes=ENTRY_WINDOW_MIN):
        nxt = next_cycle_after(now)
    return {
        "commodities": list(MINIS), "strategies": [{"offset": k, "label": strategy_label(k)} for k in OFFSETS],
        "sizes": list(SIZES), "accounts": len(MINIS) * len(OFFSETS) * len(SIZES), "stop_pct": STOP_PCT,
        "per_commodity": per, "mcx_open": mc.is_open(now), "switch_on": await is_on(SWITCH),
        # the same, under the names the shared auto-selling view reads (Indian Market Option Auto Selling too)
        "instruments": list(MINIS), "per_instrument": per, "market_open": mc.is_open(now), "market_label": "MCX",
        "instrument_info": {u: {"label": u, "sub": LOT_LABEL.get(u, "")} for u in MINIS},
        "entry_label": "22:00 IST → 22:00 IST next MCX trading day",
        "next_entry_at": _iso(nxt),
        "last_run": ({"day": last["_id"], "started_at": _iso(last.get("started_at")),
                      "finished_at": _iso(last.get("finished_at")), "counts": last.get("counts") or {},
                      "closed_before": last.get("closed_before") or {}} if last else None),
        "store": STORE.name,
    }


async def accounts(commodity: str) -> list[dict]:
    """The 55 accounts of one commodity: balance, the open trade and the last closed one."""
    book = await _book()
    last_run = await RUNS.find_one({}, sort=[("_id", -1)]) or {}
    outcome = last_run.get("outcome") or {}
    last_closed: dict[str, dict] = {}
    async for p in POSITIONS.find({"commodity": commodity, "status": "CLOSED"}).sort("exit_at", -1).limit(400):
        last_closed.setdefault(p["account_id"], p)
    rows = []
    for k in OFFSETS:
        for s in SIZES:
            aid = account_id(commodity, k, s)
            b = book.get(aid) or {}
            o = b.get("open")
            eq = _equity(s, b)
            rows.append({
                "account_id": aid, "commodity": commodity, "instrument": commodity, "offset": k,
                "strategy": strategy_label(k), "size": s,
                "starting_capital": s, "equity": round(eq, 2),
                "available": round(eq - ((o or {}).get("margin_blocked") or 0.0), 2),
                "margin_used": round((o or {}).get("margin_blocked") or 0.0, 2),
                "realized": round(b.get("realized", 0.0), 2), "trades": b.get("trades", 0), "wins": b.get("wins", 0),
                "fees": round(b.get("fees", 0.0), 2),
                "open": _pos_view(o), "last_closed": _pos_view(last_closed.get(aid)),
                "last_entry": {"day": last_run.get("_id"), "outcome": outcome.get(aid)} if last_run else None,
            })
    return rows


async def trades(commodity: str | None = None, offset: int | None = None, size: int | None = None,
                 limit: int = 200) -> list[dict]:
    q: dict = {"status": "CLOSED"}
    if commodity:
        q["commodity"] = commodity
    if offset is not None:
        q["offset"] = offset
    if size is not None:
        q["size"] = size
    return [_pos_view(p) async for p in POSITIONS.find(q).sort("exit_at", -1).limit(limit)]


async def runs(limit: int = 10) -> list[dict]:
    return [{"day": r["_id"], "started_at": _iso(r.get("started_at")), "finished_at": _iso(r.get("finished_at")),
             "counts": r.get("counts") or {}, "closed_before": r.get("closed_before") or {}}
            async for r in RUNS.find({}, {"outcome": 0}).sort("_id", -1).limit(limit)]
