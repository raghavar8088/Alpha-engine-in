"""Buy Low Options — buy a cheap OTM CALL on any F&O stock that crashed today.

THE BET, PLAINLY
At 15:00 IST on a trading day, every stock with listed options is checked against its
previous close. Anything down more than 4% on the day gets a cheap out-of-the-money CALL
bought on it — a bounded-risk bet that a sharp one-day fall is overdone and snaps back.
Ten stocks fall, ten calls; twenty fall, twenty calls. The same stock falling again on a
later day is a fresh, separate bet.

WHY THE RULES ARE SHAPED THIS WAY
  * Long calls only, so the most any single position can lose is the premium paid — that
    is what makes "no limit on how many positions" survivable at all.
  * Every position must cost <= Rs5,100 all-in (premium x lot size). Stock-option lots run
    from 250 to 1,725 shares, so the nearest OTM strike is usually far too expensive; the
    engine walks UP the strike ladder until one fits the budget. A strike that never fits
    is skipped and logged, never force-sized.
  * Exit on the POSITION's rupee P&L: +Rs2,000 target, -Rs2,000 stop, whichever comes
    first. Because a position is capped at Rs5,100, the stop usually binds before the
    premium goes to zero — but if a gap takes it below that, the loss is still bounded by
    the premium, which is the point of buying rather than selling.
  * Desk capital is Rs2,00,000, so ~39 concurrent positions fit. The cap is enforced, and
    a signal that cannot be funded is recorded with that reason rather than silently lost.

Stock options expire MONTHLY, and a long call has no overnight restriction, so positions
are carried until target/stop/expiry rather than squared off at the close.

Data is Angel One throughout, batched to the 50-token quote cap and paced.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    buy_low_equity_collection,
    buy_low_positions_collection,
    buy_low_signals_collection,
    buy_low_state_collection,
    buy_low_trades_collection,
    instruments_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.stock_options import batched_ltp, current_expiry
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("buy_low")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "engine"

FALL_PCT = float(os.getenv("BUY_LOW_FALL_PCT", "4.0"))          # trigger: down >4% on the day
MAX_POSITION_COST = float(os.getenv("BUY_LOW_MAX_COST", "5100"))  # premium x lot, per position
TARGET_RUPEES = float(os.getenv("BUY_LOW_TARGET", "2000"))
STOP_RUPEES = float(os.getenv("BUY_LOW_STOP", "2000"))
TOTAL_CAPITAL = float(os.getenv("BUY_LOW_CAPITAL", "200000"))    # ₹2 lakh desk
SCAN_FROM = os.getenv("BUY_LOW_SCAN_FROM", "15:00")              # the 3 PM check
SCAN_TO = os.getenv("BUY_LOW_SCAN_TO", "15:25")
MAX_STRIKES_UP = int(os.getenv("BUY_LOW_MAX_STRIKES_UP", "12"))  # how far OTM to hunt for a fit
QUOTE_PACE = 0.15


class BuyLowError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _is_trading_day() -> bool:
    return datetime.now(IST).weekday() < 5


# ── universe + fall detection ────────────────────────────────────────────────────


async def _fno_equities() -> dict[str, dict]:
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
    eq = await _fno_equities()
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


# ── contract selection ───────────────────────────────────────────────────────────


async def _otm_calls(symbol: str, spot: float, expiry: str) -> list[dict]:
    """OTM call strikes for the nearest expiry, cheapest-fit order (nearest OTM first)."""
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol, "expiry": expiry,
         "option_type": "CE", "strike": {"$gt": spot}, "angel_token": {"$ne": None}},
        {"symbol": 1, "strike": 1, "lot_size": 1, "angel_token": 1,
         "angel_tradingsymbol": 1}).sort("strike", 1).limit(MAX_STRIKES_UP)]
    return rows


# ── capital ──────────────────────────────────────────────────────────────────────


async def _deployed() -> float:
    total = 0.0
    async for p in buy_low_positions_collection.find({"status": "OPEN"}, {"cost": 1}):
        total += p.get("cost") or 0.0
    return total


async def _realized() -> float:
    total = 0.0
    async for p in buy_low_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


# ── cycle ────────────────────────────────────────────────────────────────────────


async def run_cycle(force_scan: bool = False) -> dict:
    notes: list[str] = []
    managed = await _manage()

    if not _is_trading_day():
        notes.append("Not a trading day — open positions still managed.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "fell": 0, "notes": notes}

    hhmm = _hhmm()
    if not force_scan and not (SCAN_FROM <= hhmm <= SCAN_TO):
        notes.append(f"Outside the {SCAN_FROM}–{SCAN_TO} IST entry window (now {hhmm}) — "
                     f"this desk only buys at the 3 PM check.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "fell": 0, "notes": notes}

    rows = await scan_falls()
    if not rows:
        notes.append("No F&O stock quotes this cycle.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "fell": 0, "notes": notes}

    fell = [r for r in rows if r["change_pct"] <= -FALL_PCT]
    notes.append(f"{len(rows)} F&O stocks checked, {len(fell)} down more than {FALL_PCT:g}%.")
    if not fell:
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "fell": 0, "notes": notes}

    session = _today()
    opened = 0
    free = TOTAL_CAPITAL + await _realized() - await _deployed()

    for r in fell:
        sym = r["symbol"]
        # One bet per stock per session; the SAME stock falling again another day is a new bet.
        if await buy_low_positions_collection.find_one({"symbol": sym, "session": session}):
            continue

        sig = {"signal_id": uuid4().hex[:12], "ts": _now(), "session": session,
               "symbol": sym, "change_pct": r["change_pct"], "spot": r["ltp"],
               "prev_close": r["prev_close"], "taken": False, "reason": None}

        if free < 1:
            sig["reason"] = f"desk capital exhausted (₹{TOTAL_CAPITAL:,.0f} fully deployed)"
            await buy_low_signals_collection.insert_one(sig)
            continue

        expiry = await current_expiry(sym)
        if not expiry:
            sig["reason"] = "no live option expiry for this stock"
            await buy_low_signals_collection.insert_one(sig)
            continue

        cands = await _otm_calls(sym, r["ltp"], expiry)
        if not cands:
            sig["reason"] = "no OTM call strikes listed"
            await buy_low_signals_collection.insert_one(sig)
            continue

        prices = await batched_ltp({"NFO": [str(c["angel_token"]) for c in cands]})
        # Walk UP the ladder: the nearest OTM strike is usually too dear for a ₹5,100
        # budget once the lot size is applied, so take the first strike that fits.
        pick = None
        for c in cands:
            prem = prices.get(str(c["angel_token"]))
            lot = int(c.get("lot_size") or 0)
            if not prem or prem <= 0 or lot <= 0:
                continue
            cost = prem * lot
            if cost <= MAX_POSITION_COST and cost <= free:
                pick = (c, prem, lot, cost)
                break
        if pick is None:
            cheapest = min(
                ((prices.get(str(c["angel_token"])) or 0) * int(c.get("lot_size") or 0) for c in cands),
                default=0)
            sig["reason"] = (f"no OTM call fits the ₹{MAX_POSITION_COST:,.0f} budget "
                             f"(cheapest ≈ ₹{cheapest:,.0f})")
            await buy_low_signals_collection.insert_one(sig)
            continue

        c, prem, lot, cost = pick
        sig["taken"] = True
        sig["strike"] = c["strike"]
        sig["premium"] = round(prem, 2)
        sig["cost"] = round(cost, 2)
        await buy_low_signals_collection.insert_one(sig)

        await buy_low_positions_collection.insert_one({
            "position_id": uuid4().hex[:12], "symbol": sym, "session": session,
            "change_pct_at_entry": r["change_pct"], "spot_at_entry": r["ltp"],
            "prev_close": r["prev_close"],
            "option_type": "CE", "strike": c["strike"], "expiry": expiry,
            "angel_tradingsymbol": c.get("angel_tradingsymbol"),
            "token": str(c["angel_token"]), "lot_size": lot, "qty": lot,
            "entry_premium": round(prem, 2), "ltp": round(prem, 2),
            "cost": round(cost, 2),
            # Target/stop are on the POSITION's rupees, converted to the premium that
            # produces them, so the manage loop can compare like with like.
            "target_premium": round(prem + TARGET_RUPEES / lot, 2),
            "stop_premium": round(max(prem - STOP_RUPEES / lot, 0.0), 2),
            "target_rupees": TARGET_RUPEES, "stop_rupees": STOP_RUPEES,
            "unrealized_pnl": 0.0, "realized_pnl": None, "exit_premium": None,
            "exit_reason": None, "status": "OPEN",
            "opened_at": _now(), "updated_at": _now(), "closed_at": None,
        })
        free -= cost
        opened += 1

    await _persist(opened, managed, notes)
    return {"opened": opened, "managed": managed, "fell": len(fell), "notes": notes}


async def _manage() -> int:
    pos = [p async for p in buy_low_positions_collection.find({"status": "OPEN"})]
    if not pos:
        return 0
    prices = await batched_ltp({"NFO": [p["token"] for p in pos]})
    today = _today()
    updated = 0
    for p in pos:
        cur = prices.get(p["token"])
        expired = bool(p.get("expiry")) and p["expiry"] <= today
        if cur is None:
            if not expired:
                continue
            cur = 0.0                      # an expired call that cannot be quoted is worth zero
        pnl = round((cur - p["entry_premium"]) * p["qty"], 2)
        reason = None
        if pnl >= p.get("target_rupees", TARGET_RUPEES):
            reason = "target"
        elif pnl <= -p.get("stop_rupees", STOP_RUPEES):
            reason = "stoploss"
        elif expired:
            reason = "expired_worthless" if cur <= 0.05 else "expiry"

        changes = {"ltp": round(cur, 2), "unrealized_pnl": pnl, "updated_at": _now()}
        if reason:
            changes.update({"status": "CLOSED", "exit_premium": round(cur, 2),
                            "exit_reason": reason, "realized_pnl": pnl,
                            "unrealized_pnl": 0.0, "closed_at": _now()})
            await buy_low_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "symbol": p["symbol"], "session": p["session"],
                "strike": p["strike"], "option_type": p["option_type"], "expiry": p.get("expiry"),
                "qty": p["qty"], "lot_size": p.get("lot_size"),
                "change_pct_at_entry": p.get("change_pct_at_entry"),
                "entry_premium": p["entry_premium"], "exit_premium": round(cur, 2),
                "cost": p.get("cost"), "realized_pnl": pnl, "exit_reason": reason,
                "opened_at": p["opened_at"], "closed_at": _now(),
            })
        await buy_low_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})
        updated += 1
    return updated


async def _persist(opened: int, managed: int, notes: list[str]) -> None:
    snap = await summary()
    await buy_low_equity_collection.insert_one({
        "ts": _now(), "session": _today(), "equity": snap["equity"],
        "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
        "open_positions": snap["open_positions"],
    })
    await buy_low_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"last_run_at": _now(), "last_opened": opened, "last_managed": managed,
                  "last_notes": notes}},
        upsert=True,
    )


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = unreal = 0.0
    async for p in buy_low_positions_collection.find({"status": "OPEN"}, {"cost": 1, "unrealized_pnl": 1}):
        deployed += p.get("cost") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
    realized = await _realized()
    closed = await buy_low_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    wins = await buy_low_positions_collection.count_documents(
        {"status": {"$ne": "OPEN"}, "realized_pnl": {"$gt": 0}})
    st = await buy_low_state_collection.find_one({"_id": STATE_ID}) or {}
    return {
        "mode": "paper",
        "total_capital": TOTAL_CAPITAL,
        "max_position_cost": MAX_POSITION_COST,
        "fall_pct": FALL_PCT,
        "target_rupees": TARGET_RUPEES,
        "stop_rupees": STOP_RUPEES,
        "scan_window": f"{SCAN_FROM}–{SCAN_TO} IST",
        "deployed_capital": round(deployed, 2),
        "free_capital": round(TOTAL_CAPITAL + realized - deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unreal, 2),
        "equity": round(TOTAL_CAPITAL + realized + unreal, 2),
        "open_positions": await buy_low_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": closed,
        "wins": wins,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "max_concurrent": int(TOTAL_CAPITAL // MAX_POSITION_COST),
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_notes": st.get("last_notes", []),
    }


def _ser(d: dict, ts: tuple[str, ...]) -> dict:
    d.pop("_id", None)
    for k in ts:
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def positions(status: str = "OPEN", limit: int = 500) -> list[dict]:
    q = {"status": status.upper()} if status else {}
    return [_ser(p, ("opened_at", "updated_at", "closed_at"))
            async for p in buy_low_positions_collection.find(q).sort("opened_at", -1).limit(limit)]


async def trades(limit: int = 500) -> list[dict]:
    return [_ser(t, ("opened_at", "closed_at"))
            async for t in buy_low_trades_collection.find({}).sort("closed_at", -1).limit(limit)]


async def signals(limit: int = 500) -> list[dict]:
    return [_ser(s, ("ts",))
            async for s in buy_low_signals_collection.find({}).sort("ts", -1).limit(limit)]


async def daily_pnl(limit: int = 60) -> list[dict]:
    rows = []
    async for r in buy_low_trades_collection.aggregate([
        {"$group": {"_id": "$session", "net_pnl": {"$sum": "$realized_pnl"},
                    "trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}}}},
        {"$sort": {"_id": -1}}, {"$limit": limit},
    ]):
        rows.append({"session": r["_id"], "net_pnl": round(r["net_pnl"] or 0, 2),
                     "trades": r["trades"], "wins": r["wins"],
                     "win_rate": round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0})
    return rows


async def fallers(limit: int = 40) -> list[dict]:
    """Live board of today's biggest F&O fallers, with the trigger marked."""
    rows = await scan_falls()
    for r in rows:
        r["triggers"] = r["change_pct"] <= -FALL_PCT
    return rows[:limit]


# ── F&O screener: biggest movers over 1 day / 1 week / 1 month ───────────────────

SCREENER_BARS_DAYS = int(os.getenv("BUY_LOW_SCREENER_BARS_DAYS", "45"))
BARS_PACE = float(os.getenv("BUY_LOW_BARS_PACE", "0.4"))


async def refresh_fno_bars() -> dict:
    """Pull recent daily candles from Angel for every F&O stock so the week/month columns
    are measured against REAL recent closes.

    This exists because the shared daily-bar store is refreshed on its own slower schedule
    and was ~12 days stale when this screener was built — computing a '1 week' change off a
    12-day-old close would have quietly mislabelled the number. Paced for Angel's history
    limit, so it takes ~90s for 208 symbols; run daily, not per request."""
    from pymongo import UpdateOne

    eq = await _fno_equities()
    if not eq:
        return {"ok": 0, "failed": 0}
    now = datetime.now(IST)
    frm = (now - timedelta(days=SCREENER_BARS_DAYS)).strftime("%Y-%m-%d 09:15")
    to = now.strftime("%Y-%m-%d %H:%M")
    try:
        await angel_client._session()
    except AngelAPIError:
        pass

    ok = fail = 0
    for sym, d in eq.items():
        try:
            rows = await angel_client.candles("NSE", str(d["angel_token"]), "D", frm, to)
        except Exception:
            fail += 1
            await asyncio.sleep(BARS_PACE)
            continue
        ops = []
        for r in rows or []:
            try:
                ts = datetime.fromisoformat(r[0]).astimezone(timezone.utc).isoformat()
                ops.append(UpdateOne(
                    {"symbol": sym, "timeframe": "1d", "ts": ts},
                    {"$set": {"symbol": sym, "timeframe": "1d", "ts": ts,
                              "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
                              "close": float(r[4]), "volume": float(r[5]), "oi": None}},
                    upsert=True))
            except (ValueError, TypeError, IndexError):
                continue
        if ops:
            from app.core.db import bars_collection
            await bars_collection.bulk_write(ops, ordered=False)
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(BARS_PACE)
    logger.info("F&O screener bars refreshed: %s ok, %s failed", ok, fail)
    return {"ok": ok, "failed": fail, "symbols": len(eq)}


async def _ref_closes(symbols: list[str], cutoff_iso: str) -> dict[str, tuple[float, str]]:
    """For each symbol, the last daily close AT OR BEFORE the cutoff, with its actual date.

    The date is returned, not assumed: if the store is stale the caller can say what it
    really measured from instead of calling a 12-day move a '1 week' move."""
    from app.core.db import bars_collection

    out: dict[str, tuple[float, str]] = {}
    async for r in bars_collection.aggregate([
        {"$match": {"timeframe": "1d", "symbol": {"$in": symbols}, "ts": {"$lte": cutoff_iso}}},
        {"$sort": {"ts": 1}},
        {"$group": {"_id": "$symbol", "close": {"$last": "$close"}, "ts": {"$last": "$ts"}}},
    ]):
        if r.get("close"):
            out[r["_id"]] = (float(r["close"]), str(r["ts"])[:10])
    return out


async def screener(limit: int = 15) -> dict:
    """Biggest F&O movers over 1 day, 1 week and 1 month — gainers and losers for each.

    1-day comes from the live quote's previous close (always exact). Week and month are
    measured against the last stored daily close on or before the cutoff, and each row
    carries the date that close actually came from."""
    live = await scan_falls()                      # symbol, ltp, prev_close, change_pct
    if not live:
        return {"as_of": None, "windows": []}
    by_sym = {r["symbol"]: r for r in live}
    symbols = list(by_sym)

    today = datetime.now(IST).date()
    windows = [("1 day", 1), ("1 week", 7), ("1 month", 30)]
    out = []
    per_window: dict[str, dict[str, dict]] = {}
    for label, days in windows:
        if days == 1:
            rows = [{"symbol": r["symbol"], "ltp": r["ltp"], "ref": r["prev_close"],
                     "ref_date": "previous close", "change_pct": r["change_pct"]}
                    for r in live]
            ref_dates = ["previous close"]
        else:
            cutoff = (today - timedelta(days=days)).isoformat() + "T23:59:59+00:00"
            refs = await _ref_closes(symbols, cutoff)
            rows = []
            for s, (close, d) in refs.items():
                ltp = by_sym[s]["ltp"]
                if close > 0:
                    rows.append({"symbol": s, "ltp": ltp, "ref": round(close, 2), "ref_date": d,
                                 "change_pct": round((ltp / close - 1) * 100, 2)})
            ref_dates = sorted({r["ref_date"] for r in rows})
        per_window[label] = {r["symbol"]: r for r in rows}
        rows.sort(key=lambda r: r["change_pct"], reverse=True)
        out.append({
            "window": label,
            "measured_from": ref_dates[-1] if ref_dates else None,
            "covered": len(rows),
            "gainers": rows[:limit],
            "losers": list(reversed(rows[-limit:])) if rows else [],
        })

    # The whole universe in ONE row per stock, so all three horizons can be read together
    # and filtered/sorted client-side. A window with no reference close for a stock returns
    # null rather than 0 — an unmeasurable move must not look like a flat one.
    d1, d7, d30 = per_window["1 day"], per_window["1 week"], per_window["1 month"]
    all_rows = []
    for s in symbols:
        r = by_sym[s]
        w, m = d7.get(s), d30.get(s)
        all_rows.append({
            "symbol": s,
            "ltp": r["ltp"],
            "prev_close": r["prev_close"],
            "change_1d": d1[s]["change_pct"] if s in d1 else None,
            "ref_1w": w["ref"] if w else None,
            "change_1w": w["change_pct"] if w else None,
            "ref_1m": m["ref"] if m else None,
            "change_1m": m["change_pct"] if m else None,
            "triggers": r["change_pct"] <= -FALL_PCT,
        })
    all_rows.sort(key=lambda r: (r["change_1d"] is None, r["change_1d"] or 0))

    return {"as_of": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "universe": len(symbols), "windows": out,
            "week_from": next((w["measured_from"] for w in out if w["window"] == "1 week"), None),
            "month_from": next((w["measured_from"] for w in out if w["window"] == "1 month"), None),
            "all": all_rows}
