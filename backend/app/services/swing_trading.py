"""Swing Trading desk — YOUR buy prices, watched and filled automatically.

Every other desk here decides what to buy. This one does not: you search any listed Indian
equity, name the price you want it at, and the desk waits. When the market reaches that
price it fills, then manages the position to a stop and a target you can change at any
time — before the fill or after it.

WHAT "REACHES THAT PRICE" MEANS. A buy price below the market is a DIP order: it triggers
when the last traded price falls to it. A buy price above the market is a BREAKOUT order:
it triggers when price rises to it. The direction is decided once, when you add the watch,
from where the stock is trading at that moment — and stored on the watch, so a stock that
drifts past your level overnight cannot silently flip the meaning of an order you placed
yesterday. Both are legitimate ways to name a price; guessing at fill time is not.

SIZING: Rs1,00,000 per position out of a Rs10 crore desk, so up to 1,000 names can be held
at once. Whole shares only, so a share priced above Rs1,00,000 simply cannot be taken and
the watch says so rather than filling for zero.

DRIFT: a gap-up does not have to mean a missed trade. Naming Rs102 on a stock at Rs100
and finding it open at Rs104 is still the move you wanted, so the desk fills it — but only
inside a DRIFT BAND of 2% above your price by default. Beyond that band it refuses: a
stock that opened Rs130 against your Rs102 is not the trade you asked for at any price,
and filling it "because the trigger was crossed" would be the desk overruling you. The
watch stays live when that happens and records how far past it gapped, so a pullback back
into the band still fills and you can see exactly what was skipped and why. The band works
the same way below for a dip order, because an unbounded gap-down fill is the same hazard
in the opposite direction.

STOP AND TARGET are set from the price actually FILLED, so a drifted entry measures its
risk from where the money really went in — buy at Rs104 with a 10% stop and the stop is
Rs93.60, not Rs91.80 off the Rs102 you named. Both are editable at any point, before the
fill or after, and an edit takes effect on the very next cycle.

COSTS are the real Angel One DELIVERY schedule, charged on close: a swing position sleeps
overnight, so it pays 0.1% STT on both legs plus a DP charge on exit — roughly four times
the intraday sell-side rate. Charging intraday rates here would understate the cost of
every trade this desk makes.

PAPER, on live Angel One prices. Fills are the real traded price at trigger time, but no
order reaches a broker.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    swing_equity_collection,
    swing_positions_collection,
    swing_state_collection,
    swing_trades_collection,
    swing_watchlist_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.angel_fees import round_trip
from app.services.call_engine import IST
from app.services.desk_totals import split as _totals_split

logger = logging.getLogger("swing_trading")

TOTAL_CAPITAL = float(os.getenv("SWING_CAPITAL", "100000000"))        # Rs10 crore
POSITION_SIZE = float(os.getenv("SWING_POSITION_SIZE", "100000"))     # Rs1 lakh
DEFAULT_SL_PCT = float(os.getenv("SWING_SL_PCT", "10"))
DEFAULT_TP_PCT = float(os.getenv("SWING_TP_PCT", "10"))
# How far past your price a gap may open and still be filled. Per-watch overridable.
DEFAULT_DRIFT_PCT = float(os.getenv("SWING_DRIFT_PCT", "2"))
QUOTE_PACE = float(os.getenv("SWING_QUOTE_PACE", "0.15"))
QUOTE_BATCH = 50
ENABLED = os.getenv("SWING_ENABLED", "1").lower() not in ("0", "false", "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _clean(d: dict, ts=("created_at", "updated_at", "triggered_at", "opened_at",
                        "closed_at", "edited_at")) -> dict:
    d.pop("_id", None)
    for k in ts:
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d



# ── universe search ────────────────────────────────────────────────────────────


async def search(q: str, limit: int = 25) -> list[dict]:
    """Every listed Indian equity Angel can quote, by symbol or company name.

    Ranking has to happen across ALL matches, not a slice of them. Fetching N*4 rows and
    sorting those looked fine until "TATA" returned TATACAP and TATAELXSI but not
    TATASTEEL — Mongo had handed back an arbitrary first 24 and the ranking only reordered
    those. So the tiers are queried separately, best first, and each is already the answer
    it claims to be: exact symbol, then symbol prefix, then symbol contains, then company
    name. Cheap because every tier is capped and later tiers usually go unused.
    """
    q = (q or "").strip().upper()
    if not q:
        return []
    esc = re.escape(q)
    proj = {"symbol": 1, "name": 1, "angel_token": 1, "angel_exchange": 1,
            "angel_tradingsymbol": 1, "security_id": 1, "exchange_segment": 1}
    base = {"asset_class": "EQUITY", "angel_token": {"$ne": None}}
    tiers = [
        {"symbol": q},
        {"symbol": {"$regex": f"^{esc}", "$options": "i"}},
        {"symbol": {"$regex": esc, "$options": "i"}},
        {"name": {"$regex": esc, "$options": "i"}},
    ]
    seen: set[str] = set()
    out: list[dict] = []
    for tier in tiers:
        if len(out) >= limit:
            break
        rows = [d async for d in instruments_collection.find({**base, **tier}, proj)
                .sort("symbol", 1).limit(limit * 3)]
        for d in rows:
            sym = d.get("symbol")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            d.pop("_id", None)
            out.append(d)
            if len(out) >= limit:
                break
    return out


async def _quote(symbols: list[str]) -> dict[str, float]:
    """Batched LTP for a set of symbols, paced and per-chunk guarded so one bad batch
    cannot blank the whole desk."""
    if not symbols:
        return {}
    insts = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1})}
    by_ex: dict[str, list[str]] = {}
    tok2sym: dict[str, str] = {}
    for sym, d in insts.items():
        tok = str(d["angel_token"])
        tok2sym[tok] = sym
        by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(tok)
    try:
        await angel_client._session()
    except AngelAPIError:
        pass
    out: dict[str, float] = {}
    for ex, toks in by_ex.items():
        for i in range(0, len(toks), QUOTE_BATCH):
            try:
                q = await angel_client.full_quote({ex: toks[i:i + QUOTE_BATCH]})
            except AngelAPIError as exc:
                logger.warning("swing: quote batch failed (%s)", exc)
                continue
            for tok, row in q.items():
                if row.get("ltp") and str(tok) in tok2sym:
                    out[tok2sym[str(tok)]] = float(row["ltp"])
            await asyncio.sleep(QUOTE_PACE)
    return out


# ── watchlist ──────────────────────────────────────────────────────────────────


async def add_watch(symbol: str, buy_price: float, sl_pct: float | None = None,
                    tp_pct: float | None = None, note: str = "",
                    drift_pct: float | None = None) -> dict:
    symbol = (symbol or "").strip().upper()
    inst = await instruments_collection.find_one(
        {"asset_class": "EQUITY", "symbol": symbol, "angel_token": {"$ne": None}})
    if not inst:
        raise ValueError(f"{symbol!r} is not a listed equity Angel can quote")
    if buy_price <= 0:
        raise ValueError("buy price must be positive")
    if await swing_watchlist_collection.find_one({"symbol": symbol, "status": "WAITING"}):
        raise ValueError(f"{symbol} already has a waiting buy order")

    ltp = (await _quote([symbol])).get(symbol)
    # Direction fixed HERE, from where the stock trades now — see the module docstring.
    side = "DIP" if (ltp is None or buy_price <= ltp) else "BREAKOUT"
    sl_pct = DEFAULT_SL_PCT if sl_pct is None else float(sl_pct)
    tp_pct = DEFAULT_TP_PCT if tp_pct is None else float(tp_pct)
    drift_pct = DEFAULT_DRIFT_PCT if drift_pct is None else float(drift_pct)
    doc = {
        "watch_id": uuid4().hex[:12], "symbol": symbol,
        "name": inst.get("name") or symbol,
        "angel_token": str(inst["angel_token"]),
        "angel_exchange": inst.get("angel_exchange") or "NSE",
        "buy_price": round(float(buy_price), 2),
        "trigger_side": side,
        "ltp_at_add": round(ltp, 2) if ltp else None,
        "sl_pct": sl_pct, "tp_pct": tp_pct, "drift_pct": drift_pct,
        # The band a gap may open inside and still be filled.
        "max_fill_price": round(buy_price * (1 + drift_pct / 100), 2),
        "min_fill_price": round(buy_price * (1 - drift_pct / 100), 2),
        # Indicative only — the real levels are set from the FILL when it happens.
        "stop_price": round(buy_price * (1 - sl_pct / 100), 2),
        "target_price": round(buy_price * (1 + tp_pct / 100), 2),
        "gapped_past": False, "last_gap_pct": None,
        "note": note, "status": "WAITING", "ltp": round(ltp, 2) if ltp else None,
        "created_at": _now(), "updated_at": _now(), "triggered_at": None,
    }
    await swing_watchlist_collection.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def edit_watch(watch_id: str, buy_price: float | None = None,
                     sl_pct: float | None = None, tp_pct: float | None = None,
                     drift_pct: float | None = None) -> dict:
    w = await swing_watchlist_collection.find_one({"watch_id": watch_id})
    if not w:
        raise ValueError("watch not found")
    if w["status"] != "WAITING":
        raise ValueError("this watch already triggered — edit the position instead")
    bp = float(buy_price) if buy_price is not None else w["buy_price"]
    sl = float(sl_pct) if sl_pct is not None else w["sl_pct"]
    tp = float(tp_pct) if tp_pct is not None else w["tp_pct"]
    dr = float(drift_pct) if drift_pct is not None else w.get("drift_pct", DEFAULT_DRIFT_PCT)
    if bp <= 0:
        raise ValueError("buy price must be positive")
    if dr < 0:
        raise ValueError("drift cannot be negative")
    upd = {"buy_price": round(bp, 2), "sl_pct": sl, "tp_pct": tp, "drift_pct": dr,
           "max_fill_price": round(bp * (1 + dr / 100), 2),
           "min_fill_price": round(bp * (1 - dr / 100), 2),
           "stop_price": round(bp * (1 - sl / 100), 2),
           "target_price": round(bp * (1 + tp / 100), 2),
           "gapped_past": False, "updated_at": _now()}
    if buy_price is not None and w.get("ltp"):
        # Moving the price can change what the order MEANS, so re-decide the direction
        # rather than leaving a dip order that now sits above the market.
        upd["trigger_side"] = "DIP" if bp <= w["ltp"] else "BREAKOUT"
    await swing_watchlist_collection.update_one({"watch_id": watch_id}, {"$set": upd})
    return _clean({**w, **upd})


async def remove_watch(watch_id: str) -> bool:
    r = await swing_watchlist_collection.delete_one({"watch_id": watch_id, "status": "WAITING"})
    return r.deleted_count > 0


async def edit_position(position_id: str, sl_pct: float | None = None,
                        tp_pct: float | None = None,
                        stop_price: float | None = None,
                        target_price: float | None = None) -> dict:
    """Change the stop or target on a LIVE position. Percentages stay anchored to the
    buy price you named, so editing after a gap-fill does not silently re-scale the risk;
    absolute prices override outright when you want a specific level."""
    p = await swing_positions_collection.find_one({"position_id": position_id, "status": "OPEN"})
    if not p:
        raise ValueError("open position not found")
    # Anchored to the FILL, matching how the levels were set at entry — a percentage
    # edit that silently measured from a different price than the original would be a
    # different risk than the one on screen.
    anchor = p.get("anchor_price") or p["entry_price"]
    upd: dict = {"updated_at": _now()}
    if sl_pct is not None:
        upd["sl_pct"] = float(sl_pct)
        upd["stop_price"] = round(anchor * (1 - float(sl_pct) / 100), 2)
    if tp_pct is not None:
        upd["tp_pct"] = float(tp_pct)
        upd["target_price"] = round(anchor * (1 + float(tp_pct) / 100), 2)
    if stop_price is not None:
        upd["stop_price"] = round(float(stop_price), 2)
    if target_price is not None:
        upd["target_price"] = round(float(target_price), 2)
    if upd.get("stop_price", 1) <= 0 or upd.get("target_price", 1) <= 0:
        raise ValueError("stop and target must be positive")
    if upd.get("stop_price", 0) >= upd.get("target_price", float("inf")):
        raise ValueError("stop must sit below target on a long position")
    upd["edited_at"] = _now()
    await swing_positions_collection.update_one({"position_id": position_id}, {"$set": upd})
    return _clean({**p, **upd})


# ── capital ────────────────────────────────────────────────────────────────────


async def _deployed() -> float:
    t = 0.0
    async for p in swing_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1}):
        t += p.get("capital_deployed") or 0.0
    return t


async def _realized() -> float:
    t = 0.0
    async for p in swing_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        t += p.get("realized_pnl") or 0.0
    return t


# ── the cycle ──────────────────────────────────────────────────────────────────


async def _fill(w: dict, price: float) -> bool:
    """Open a position at the traded price that triggered the watch."""
    qty = int(POSITION_SIZE // price)
    if qty < 1:
        await swing_watchlist_collection.update_one(
            {"watch_id": w["watch_id"]},
            {"$set": {"status": "UNFILLABLE", "updated_at": _now(),
                      "note": f"one share costs Rs{price:,.0f}, above the "
                              f"Rs{POSITION_SIZE:,.0f} per-position size"}})
        return False
    deployed = await _deployed()
    if deployed + price * qty > TOTAL_CAPITAL:
        return False                       # desk full; the watch simply keeps waiting
    drifted = price > w["buy_price"] + 0.005
    drift_actual = (price / w["buy_price"] - 1) * 100 if w["buy_price"] else 0.0
    await swing_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "watch_id": w["watch_id"],
        "symbol": w["symbol"], "name": w.get("name"),
        "angel_token": w["angel_token"], "angel_exchange": w["angel_exchange"],
        "side": "BUY", "trigger_side": w["trigger_side"],
        # buy_price is the level YOU named; entry_price is what it actually filled at.
        "buy_price": w["buy_price"], "entry_price": round(price, 2), "qty": qty,
        "slippage": round(price - w["buy_price"], 2),
        # DRIFTED means the gap carried the fill past your price, inside the allowed band.
        "drifted": drifted, "drift_pct_actual": round(drift_actual, 2),
        "drift_pct_allowed": w.get("drift_pct", DEFAULT_DRIFT_PCT),
        "capital_deployed": round(price * qty, 2),
        "sl_pct": w["sl_pct"], "tp_pct": w["tp_pct"],
        # Anchored to the FILL: risk is measured from where the money actually went in.
        "anchor_price": round(price, 2),
        "stop_price": round(price * (1 - w["sl_pct"] / 100), 2),
        "target_price": round(price * (1 + w["tp_pct"] / 100), 2),
        "ltp": round(price, 2), "unrealized_pnl": 0.0, "pnl_pct": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "opened_at": _now(), "opened_on": _today(), "closed_at": None, "closed_on": None,
        "updated_at": _now(),
    })
    await swing_watchlist_collection.update_one(
        {"watch_id": w["watch_id"]},
        {"$set": {"status": "TRIGGERED", "triggered_at": _now(),
                  "fill_price": round(price, 2), "updated_at": _now()}})
    logger.warning("swing: FILLED%s %s x%d @ Rs%.2f (wanted Rs%.2f%s)",
                   " DRIFTED" if drifted else "", w["symbol"], qty, price, w["buy_price"],
                   f", drift {drift_actual:+.2f}%" if drifted else "")
    return True


async def run_cycle() -> dict:
    if not ENABLED:
        return {"filled": 0, "closed": 0, "watching": 0, "notes": ["desk disabled"]}
    waiting = [w async for w in swing_watchlist_collection.find({"status": "WAITING"})]
    open_pos = [p async for p in swing_positions_collection.find({"status": "OPEN"})]

    symbols = sorted({w["symbol"] for w in waiting} | {p["symbol"] for p in open_pos})
    prices = await _quote(symbols)

    filled = 0
    for w in waiting:
        ltp = prices.get(w["symbol"])
        if ltp is None:
            continue
        await swing_watchlist_collection.update_one(
            {"watch_id": w["watch_id"]}, {"$set": {"ltp": round(ltp, 2), "updated_at": _now()}})
        # A crossed trigger is not enough on its own — the price has to be INSIDE the
        # drift band. Outside it the gap has carried the stock past the trade that was
        # actually asked for, so the watch stays live and records the miss instead.
        drift = w.get("drift_pct", DEFAULT_DRIFT_PCT)
        hi = w.get("max_fill_price") or round(w["buy_price"] * (1 + drift / 100), 2)
        lo = w.get("min_fill_price") or round(w["buy_price"] * (1 - drift / 100), 2)
        if w["trigger_side"] == "BREAKOUT":
            hit, gapped = w["buy_price"] <= ltp <= hi, ltp > hi
        else:
            hit, gapped = lo <= ltp <= w["buy_price"], ltp < lo
        if gapped:
            gap_pct = (ltp / w["buy_price"] - 1) * 100
            await swing_watchlist_collection.update_one(
                {"watch_id": w["watch_id"]},
                {"$set": {"gapped_past": True, "last_gap_pct": round(gap_pct, 2),
                          "gapped_at": _now(), "updated_at": _now()}})
            continue
        if hit and await _fill(w, ltp):
            filled += 1

    closed = 0
    for p in open_pos:
        ltp = prices.get(p["symbol"])
        if ltp is None:
            continue
        gross = round((ltp - p["entry_price"]) * p["qty"], 2)
        changes: dict = {"ltp": round(ltp, 2), "unrealized_pnl": gross,
                         "pnl_pct": round((ltp / p["entry_price"] - 1) * 100, 2),
                         "updated_at": _now()}
        reason = ("target" if ltp >= p["target_price"]
                  else "stoploss" if ltp <= p["stop_price"] else None)
        if reason:
            # DELIVERY: a swing position sleeps overnight and pays the heavier schedule.
            fb = round_trip(p["entry_price"], ltp, p["qty"], side="BUY", product="DELIVERY")
            net = round(gross - fb.total, 2)
            changes.update({
                "status": "CLOSED", "exit_price": round(ltp, 2), "exit_reason": reason,
                "gross_pnl": gross, "fees": fb.total, "fee_breakdown": fb.as_dict(),
                "realized_pnl": net, "unrealized_pnl": 0.0,
                "closed_at": _now(), "closed_on": _today(),
            })
            closed += 1
            await swing_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "position_id": p["position_id"],
                "symbol": p["symbol"], "qty": p["qty"],
                "buy_price": p.get("buy_price"), "entry_price": p["entry_price"],
                "exit_price": round(ltp, 2), "gross_pnl": gross, "fees": fb.total,
                "realized_pnl": net, "exit_reason": reason,
                "opened_at": p["opened_at"], "closed_at": _now(),
            })
        await swing_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})

    snap = await summary()
    await swing_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"],
        "roi_pct": snap["roi_pct"], "open_positions": snap["open_positions"],
    })
    await swing_state_collection.update_one(
        {"_id": "engine"},
        {"$set": {"last_run_at": _now(), "last_filled": filled, "last_closed": closed,
                  "watching": len(waiting), "quoted": len(prices)}},
        upsert=True)
    return {"filled": filled, "closed": closed, "watching": len(waiting),
            "quoted": len(prices), "notes": []}


# ── reporting ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    op, cl = await _totals_split(swing_positions_collection)
    deployed, unrealized = op["deployed"], op["unrealized"]
    realized, fees = cl["realized"], cl["fees"]
    equity = TOTAL_CAPITAL + realized + unrealized
    today = _today()
    today_pnl = 0.0
    async for p in swing_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_on": today}, {"realized_pnl": 1}
    ):
        today_pnl += p.get("realized_pnl") or 0.0
    async for p in swing_positions_collection.find(
        {"status": "OPEN", "opened_on": today}, {"unrealized_pnl": 1}
    ):
        today_pnl += p.get("unrealized_pnl") or 0.0
    state = await swing_state_collection.find_one({"_id": "engine"}) or {}
    return {
        "mode": "paper", "enabled": ENABLED,
        "initial_capital": TOTAL_CAPITAL,
        "position_size": POSITION_SIZE,
        "max_positions": int(TOTAL_CAPITAL // POSITION_SIZE),
        "default_sl_pct": DEFAULT_SL_PCT, "default_tp_pct": DEFAULT_TP_PCT,
        "deployed_capital": round(deployed, 2),
        "available_cash": round(TOTAL_CAPITAL + realized - deployed, 2),
        "realized_pnl": round(realized, 2),
        "gross_realized_pnl": round(realized + fees, 2),
        "total_fees": round(fees, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(equity, 2),
        # Three different questions, so three different denominators.
        "roi_pct": round((equity - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100, 4),
        "today_pnl": round(today_pnl, 2),
        "today_roi_pct": round(today_pnl / TOTAL_CAPITAL * 100, 4),
        # Return on the money actually AT RISK — on a desk this large relative to what it
        # deploys, total-capital ROI will always look tiny and says little about the
        # trades themselves.
        "deployed_roi_pct": round((realized + unrealized) / deployed * 100, 3) if deployed else 0.0,
        "open_positions": op["n"],
        "closed_positions": cl["n"],
        "waiting": await swing_watchlist_collection.count_documents({"status": "WAITING"}),
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
    }


async def watchlist(status: str | None = None, limit: int = 500) -> list[dict]:
    q = {"status": status.upper()} if status and status.upper() != "ALL" else {}
    return [_clean(d) async for d in
            swing_watchlist_collection.find(q).sort("created_at", -1).limit(limit)]


async def positions(status: str = "OPEN", limit: int = 500) -> list[dict]:
    q = {} if status.upper() == "ALL" else {"status": status.upper()}
    return [_clean(d) async for d in
            swing_positions_collection.find(q).sort("opened_at", -1).limit(limit)]


async def equity_curve(limit: int = 500) -> list[dict]:
    rows = [_clean(d, ("ts",)) async for d in
            swing_equity_collection.find({}).sort("ts", -1).limit(limit)]
    return list(reversed(rows))


async def daily(limit: int = 90) -> list[dict]:
    buckets: dict[str, dict] = {}
    async for p in swing_positions_collection.find(
        {"status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "gross_pnl": 1, "fees": 1, "closed_on": 1, "capital_deployed": 1},
    ):
        day = p.get("closed_on")
        if not day:
            continue
        b = buckets.setdefault(day, {"date": day, "trades": 0, "wins": 0, "realized_pnl": 0.0,
                                     "fees": 0.0, "gross_pnl": 0.0, "deployed": 0.0})
        net = p.get("realized_pnl") or 0.0
        b["trades"] += 1
        b["wins"] += 1 if net > 0 else 0
        b["realized_pnl"] += net
        b["fees"] += p.get("fees") or 0.0
        b["gross_pnl"] += p.get("gross_pnl") or 0.0
        b["deployed"] += p.get("capital_deployed") or 0.0
    rows = sorted(buckets.values(), key=lambda r: r["date"], reverse=True)[:limit]
    for r in rows:
        for k in ("realized_pnl", "fees", "gross_pnl", "deployed"):
            r[k] = round(r[k], 2)
        r["win_rate"] = round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0
        r["roi_pct"] = round(r["realized_pnl"] / TOTAL_CAPITAL * 100, 4)
        r["deployed_roi_pct"] = round(r["realized_pnl"] / r["deployed"] * 100, 3) if r["deployed"] else 0.0
    return rows
