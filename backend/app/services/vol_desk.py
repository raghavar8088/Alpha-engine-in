"""The volatility desk: paper incubation of the pre-registered hypotheses H1 and H1b
(app.services.option_hypotheses), on real NIFTY option prices.

Every trading day at 09:45 it computes the frozen signal (log VIX, VIX change, gap,
first-30-minute range, recent realized variance against the VIX-implied variance, expiry
day) exactly as the research defined it, and records the decision whether or not it trades —
so the signal itself is auditable day by day. On a flagged day:
  H1   buys 1 lot each of the ATM CE and PE of NEXT week's expiry at 09:45, sells at 15:15
  H1b  buys the same straddle at 15:15, sells at 09:30 the next session
Fills are recorded twice: the paper fill at the last traded price, and the real-money fill
at the order book (bought at the ask, sold at the bid; an estimated half spread only when the
book is unavailable, labelled so). Costs: Angel One's rate card. Verdicts are read off the
REAL-money P&L by option_hypotheses.evaluate(). Paper only — nothing here places an order.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

from app.core.db import db, instruments_collection
from app.services import market_calendar
from app.services.option_hypotheses import FROZEN_SIGNAL
from tradingai_shared.option_fees import option_round_trip

logger = logging.getLogger("vol_desk")

IST = timezone(timedelta(hours=5, minutes=30))
ENABLED = os.getenv("VOL_DESK_ENABLED", "1").lower() not in ("0", "false", "no")
decisions = db["vol_desk_decisions"]
positions = db["vol_desk_positions"]
trades = db["vol_desk_trades"]
EST_HALF_SPREAD_PCT = float(os.getenv("PRELIVE_EST_HALF_SPREAD_PCT", "0.0025"))
status: dict = {"enabled": ENABLED, "last_decision": None, "last_action": None, "errors": 0, "last_error": None}


# ── the frozen signal ────────────────────────────────────────────────────────────


def _minute(e: int) -> int:
    return ((e + 19800) % 86400) // 60


def _dkey(e: int) -> int:
    return (e + 19800) // 86400


def _sessions_5m(upto_key: int, n: int) -> list[list[tuple]]:
    """The last `n` complete sessions of NIFTY 5m bars strictly before day `upto_key`."""
    from app.services.intraday_store import read_file
    b = read_file("NIFTY", "5m")
    by: dict[int, list[tuple]] = {}
    for i in range(len(b)):
        k = _dkey(b.t[i])
        if k < upto_key:
            by.setdefault(k, []).append((b.t[i], b.o[i], b.h[i], b.l[i], b.c[i]))
    good = [by[k] for k in sorted(by) if len(by[k]) >= 70 and _minute(by[k][0][0]) == 555]
    return good[-n:]


def _rv(rows: list[tuple]) -> float:
    return sum(math.log(rows[i][4] / rows[i - 1][4]) ** 2 for i in range(1, len(rows)))


async def current_weekly_expiry(day: date) -> str | None:
    exps = sorted(e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": "NIFTY"}) if e and e >= day.isoformat())
    if not exps or (date.fromisoformat(exps[0]) - day).days > 7:
        return None
    return exps[0]


async def next_week_expiry(day: date) -> str | None:
    """The weekly after the current one: the first listed expiry >= current + 6 days (a holiday
    can move an expiry a day earlier, e.g. 19 Oct 2026 for the Dussehra Tuesday)."""
    cur = await current_weekly_expiry(day)
    if not cur:
        return None
    floor = (date.fromisoformat(cur) + timedelta(days=6)).isoformat()
    exps = sorted(e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": "NIFTY"}) if e and e >= floor)
    return exps[0] if exps and (date.fromisoformat(exps[0]) - day).days <= 14 else None


def _features_sync(day: date, now: datetime) -> dict:
    """Everything the frozen model reads at 09:45, from closed bars only."""
    from app.services.intraday_store import read_file, store
    k = (day - date(1970, 1, 1)).days
    cutoff = int(now.timestamp())
    n15 = store.get("NIFTY")
    today = [(n15.t[i], n15.o[i], n15.h[i], n15.l[i], n15.c[i]) for i in range(len(n15))
             if _dkey(n15.t[i]) == k and n15.t[i] <= cutoff - 900]
    if len(today) < 2 or _minute(today[0][0]) != 555 or _minute(today[1][0]) != 570:
        raise ValueError(f"NIFTY 09:15/09:30 15m bars not both in ({len(today)} closed today)")
    prev = _sessions_5m(k, 6)
    if len(prev) < 6:
        raise ValueError(f"only {len(prev)} complete 5m sessions of history")
    vb = store.get("INDIAVIX")
    vt = list(vb.t)
    i = bisect_right(vt, cutoff - 900) - 1
    if i < 0 or _dkey(vt[i]) != k:
        raise ValueError("India VIX 09:30 bar missing")
    v = vb.c[i] / 100
    j = bisect_right(vt, k * 86400 - 19800) - 1
    vprev = vb.c[j] / 100 if j >= 0 else None
    if not vprev:
        raise ValueError("previous India VIX close missing")
    o = today[0][1]
    hi30, lo30 = max(today[0][2], today[1][2]), min(today[0][3], today[1][3])
    s945 = today[1][4]
    prev_close = prev[-1][-1][4]
    iv_win = v * v * (330 / 375) / 252
    rv_prev = _rv(prev[-1])
    rv5 = sum(_rv(p) for p in prev[-5:]) / 5
    return {"vix": round(v * 100, 2), "vix_prev": round(vprev * 100, 2), "dvix": v / vprev - 1,
            "gap_pct": abs(o / prev_close - 1) * 100, "r30_pct": (hi30 - lo30) / o * 100,
            "rv_prev": rv_prev, "rv5": rv5, "iv_win": iv_win, "spot_0945": s945, "open": o, "prev_close": prev_close,
            "x": [math.log(v), v / vprev - 1, abs(o / prev_close - 1) * 100, (hi30 - lo30) / o * 100,
                  math.log(rv_prev / iv_win), math.log(rv5 / iv_win)]}


async def decide(day: date, now: datetime) -> dict:
    """Compute (once) and store the day's frozen-signal decision."""
    existing = await decisions.find_one({"_id": day.isoformat()})
    if existing:
        return existing
    f = await asyncio.to_thread(_features_sync, day, now)
    cur = await current_weekly_expiry(day)
    x = f.pop("x") + [1.0 if cur == day.isoformat() else 0.0, 1.0]
    pred = sum(a * b for a, b in zip(x, FROZEN_SIGNAL["weights"]))
    doc = {"_id": day.isoformat(), "at": now, "features": f, "x": x, "prediction": round(pred, 4),
           "threshold": FROZEN_SIGNAL["threshold"], "flagged": pred >= FROZEN_SIGNAL["threshold"],
           "current_expiry": cur, "next_week_expiry": await next_week_expiry(day)}
    await decisions.insert_one(doc)
    logger.info("vol desk %s: prediction %.3f vs threshold %.3f -> %s", day, pred, FROZEN_SIGNAL["threshold"],
                "FLAGGED" if doc["flagged"] else "no trade")
    return doc


# ── fills ────────────────────────────────────────────────────────────────────────


async def _straddle(expiry: str, spot: float) -> list[dict] | None:
    atm = round(spot / 50) * 50
    legs = []
    for kind in ("CE", "PE"):
        d = await instruments_collection.find_one(
            {"asset_class": "INDEX_OPTION", "underlying_symbol": "NIFTY", "expiry": expiry, "strike": float(atm),
             "option_type": kind, "angel_token": {"$ne": None}},
            {"symbol": 1, "security_id": 1, "angel_token": 1, "angel_exchange": 1, "lot_size": 1, "strike": 1})
        if not d:
            return None
        legs.append({"kind": kind, "symbol": d["symbol"], "security_id": d["security_id"], "token": str(d["angel_token"]),
                     "exchange": d.get("angel_exchange") or "NFO", "lot_size": int(d.get("lot_size") or 65),
                     "strike": float(d["strike"])})
    return legs


async def _quote(legs: list[dict]) -> dict[str, dict]:
    from app.services.angel_client import angel_client
    by: dict[str, list[str]] = {}
    for leg in legs:
        by.setdefault(leg["exchange"], []).append(leg["token"])
    return await angel_client.full_quote(by)


def _est(px: float) -> float:
    return max(0.05, px * EST_HALF_SPREAD_PCT)


async def open_straddle(hyp: str, day: date, expiry: str, spot: float, now: datetime) -> dict | None:
    if await positions.find_one({"hypothesis": hyp, "status": "OPEN"}):
        return None
    legs = await _straddle(expiry, spot)
    if not legs:
        raise ValueError(f"no ATM straddle listed for {expiry} near {spot:.0f}")
    q = await _quote(legs)
    for leg in legs:
        x = q.get(leg["token"]) or {}
        if not x.get("ltp"):
            raise ValueError(f"no price for {leg['symbol']}")
        leg.update({"entry_ltp": x["ltp"], "entry_bid": x.get("bid"), "entry_ask": x.get("ask"),
                    "real_entry": x.get("ask") or x["ltp"] + _est(x["ltp"]),
                    "entry_basis": "book" if x.get("ask") else "estimated"})
    doc = {"hypothesis": hyp, "status": "OPEN", "session": day.isoformat(), "expiry": expiry, "spot_entry": spot,
           "opened_at": now, "legs": legs, "lots": 1}
    await positions.insert_one(doc)
    await _mirror_real(hyp, "open", legs)
    status["last_action"] = f"{now:%Y-%m-%d %H:%M} {hyp} bought the {expiry} {legs[0]['strike']:.0f} straddle"
    logger.info("vol desk %s: bought %s %s straddle @ ask %s", hyp, expiry, legs[0]["strike"],
                [round(leg["real_entry"], 2) for leg in legs])
    return doc


async def close_straddle(pos: dict, now: datetime, spot: float | None) -> dict:
    q = await _quote(pos["legs"])
    paper = real = 0.0
    fee_p = fee_r = 0.0
    legs = []
    for leg in pos["legs"]:
        x = q.get(leg["token"]) or {}
        ltp = x.get("ltp") or leg["entry_ltp"]
        real_exit = x.get("bid") or max(0.05, ltp - _est(ltp))
        qty = leg["lot_size"] * pos["lots"]
        fp = option_round_trip(leg["entry_ltp"], ltp, qty, on=now.date())["total"]
        fr = option_round_trip(leg["real_entry"], real_exit, qty, on=now.date())["total"]
        paper += (ltp - leg["entry_ltp"]) * qty - fp
        real += (real_exit - leg["real_entry"]) * qty - fr
        fee_p += fp
        fee_r += fr
        legs.append({**leg, "exit_ltp": ltp, "exit_bid": x.get("bid"), "exit_ask": x.get("ask"), "real_exit": real_exit,
                     "exit_basis": "book" if x.get("bid") else "estimated"})
    t = {"hypothesis": pos["hypothesis"], "session": pos["session"], "expiry": pos["expiry"],
         "opened_at": pos["opened_at"], "closed_at": now, "spot_entry": pos["spot_entry"], "spot_exit": spot,
         "legs": legs, "paper_pnl": round(paper, 2), "real_pnl": round(real, 2), "fees_paper": round(fee_p, 2),
         "fees_real": round(fee_r, 2),
         "real_basis": "book" if all(lg["entry_basis"] == "book" and lg["exit_basis"] == "book" for lg in legs) else "estimated"}
    await trades.insert_one(t)
    await positions.update_one({"_id": pos["_id"]}, {"$set": {"status": "CLOSED", "closed_at": now}})
    await _mirror_real(pos["hypothesis"], "close", legs)
    status["last_action"] = f"{now:%Y-%m-%d %H:%M} {pos['hypothesis']} closed: real Rs{real:,.0f} (paper Rs{paper:,.0f})"
    logger.info("vol desk %s closed: real %.0f paper %.0f", pos["hypothesis"], real, paper)
    return t


async def _mirror_real(hyp: str, purpose: str, legs: list[dict]) -> None:
    """Hand the paper decision to the real-money executor — which acts ONLY if it is armed for
    this hypothesis (a CONFIRMED verdict + server switch + the user's arming). Today nothing
    is confirmed, so this records nothing and sends nothing. Never raises into the desk."""
    try:
        from app.services import live_options_executor as lx
        st = await lx.get_state()
        open_real = await lx.lpositions.count_documents({"hypothesis": hyp, "status": "OPEN"})
        if purpose == "open" and not (st["armed"] and st["armed_hypothesis"] == hyp):
            return
        if purpose == "close" and not open_real:
            return
        product = "CARRYFORWARD" if hyp == "H1b" else "INTRADAY"
        real_legs = []
        for leg in legs:
            inst = await instruments_collection.find_one({"security_id": leg["security_id"], "exchange_segment": "NSE_FNO"},
                                                         {"angel_tradingsymbol": 1})
            ref = leg["real_entry"] if purpose == "open" else leg.get("real_exit") or leg.get("exit_ltp")
            real_legs.append({"tradingsymbol": (inst or {}).get("angel_tradingsymbol"), "token": leg["token"],
                              "exchange": leg["exchange"], "side": "BUY" if purpose == "open" else "SELL",
                              "qty": leg["lot_size"], "lot_size": leg["lot_size"], "ref_price": ref})
        if any(not r["tradingsymbol"] for r in real_legs):
            logger.error("vol desk %s: no Angel trading symbol for a leg — real order not attempted", hyp)
            return
        res = await lx.execute(hyp, purpose, real_legs, product=product)
        if purpose == "open" and res.get("orders"):
            for r in res["orders"]:
                await lx.lpositions.insert_one({"hypothesis": hyp, "status": "OPEN", "opened_at": datetime.now(timezone.utc),
                                                "tradingsymbol": r["tradingsymbol"], "token": r["token"],
                                                "exchange": r["exchange"], "qty": r["qty"], "lot_size": r["lot_size"],
                                                "entry": r.get("fill"), "product": product, "dry_run": r.get("dry_run")})
        elif purpose == "close":
            fills = {r["token"]: r.get("fill") for r in res.get("orders", [])}
            async for p in lx.lpositions.find({"hypothesis": hyp, "status": "OPEN"}):
                exit_px = fills.get(p["token"])
                pnl = (exit_px - p["entry"]) * p["qty"] if exit_px and p.get("entry") else None
                await lx.lpositions.update_one({"_id": p["_id"]}, {"$set": {"status": "CLOSED", "closed_at": datetime.now(timezone.utc),
                                                                         "exit": exit_px, "realized_pnl": pnl}})
        logger.warning("vol desk %s %s mirrored to the real-money executor: %s", hyp, purpose,
                       {k: res.get(k) for k in ("sent", "dry_run", "refused")})
    except Exception:  # noqa: BLE001 - the paper desk must never fail because of the real path
        logger.exception("real-money mirror failed for %s %s", hyp, purpose)


async def _spot_now() -> float | None:
    from app.services.angel_client import angel_client
    q = await angel_client.full_quote({"NSE": ["99926000"]})
    return (q.get("99926000") or {}).get("ltp")


# ── the loop ─────────────────────────────────────────────────────────────────────


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.now(IST)
    day = now.date()
    if not market_calendar.is_trading_day(now):
        return
    hm = now.strftime("%H:%M")
    # H1b exit: the overnight straddle closes at 09:30 the next session
    if "09:30" <= hm < "10:30":
        async for pos in positions.find({"hypothesis": "H1b", "status": "OPEN", "session": {"$lt": day.isoformat()}}):
            await close_straddle(pos, now, await _spot_now())
    # the decision and the H1 entry
    if "09:45" <= hm < "10:15" and now.second >= 30:
        d = await decide(day, now)
        status["last_decision"] = {k: d.get(k) for k in ("_id", "prediction", "threshold", "flagged")}
        if d["flagged"] and d.get("next_week_expiry") and not await trades.find_one({"hypothesis": "H1", "session": day.isoformat()}) \
                and not await positions.find_one({"hypothesis": "H1", "session": day.isoformat()}):
            await open_straddle("H1", day, d["next_week_expiry"], await _spot_now() or d["features"]["spot_0945"], now)
    # 15:15: H1 out, H1b in
    if "15:15" <= hm < "15:28":
        async for pos in positions.find({"hypothesis": "H1", "status": "OPEN"}):
            await close_straddle(pos, now, await _spot_now())
        d = await decisions.find_one({"_id": day.isoformat()})
        if d and d.get("flagged") and d.get("next_week_expiry") \
                and not await positions.find_one({"hypothesis": "H1b", "session": day.isoformat()}):
            await open_straddle("H1b", day, d["next_week_expiry"], await _spot_now() or d["features"]["spot_0945"], now)


async def vol_desk_loop() -> None:
    logger.info("vol desk: H1/H1b paper incubation (frozen 09:45 signal, threshold %.4f)", FROZEN_SIGNAL["threshold"])
    while True:
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 - retried next tick
            status["errors"] += 1
            status["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("vol desk tick failed: %s", exc)
        await asyncio.sleep(20)


async def summary() -> dict:
    out = {"status": status, "open": [], "trades": [], "decisions": []}
    async for p in positions.find({"status": "OPEN"}, {"_id": 0}):
        out["open"].append(p)
    async for t in trades.find({}, {"_id": 0}).sort("closed_at", -1).limit(60):
        out["trades"].append(t)
    async for d in decisions.find({}).sort("_id", -1).limit(30):
        d["date"] = d.pop("_id")
        out["decisions"].append(d)
    for h in ("H1", "H1b"):
        xs = [t async for t in trades.find({"hypothesis": h}, {"real_pnl": 1, "paper_pnl": 1})]
        out[h] = {"trades": len(xs), "real_net": round(sum(t["real_pnl"] for t in xs), 2),
                  "paper_net": round(sum(t["paper_pnl"] for t in xs), 2)}
    return out
