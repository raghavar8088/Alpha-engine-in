"""Gold Lab — the seven Tier-B strategies of the 2026-10 gold strategy search, as one paper book.

WHAT IT IS (GOLD_STRATEGY_LAB_2026_10.md; the rules are gold_lab_rules)
-----------------------------------------------------------------------
Seven daily strategies that were profitable after costs in selection (2004-14), validation
(2015-19) AND an untouched holdout (2020-26) — but NOT proven better than simply holding gold
(none survived the correction for the 157 variants tried). Three ideas, not seven: trend
(gl1, gl3, gl4, gl5), shock continuation (gl6, gl7), macro fair-value reversion (gl2).
This book records what they do from now on, honestly priced. Paper only.

HOW IT TRADES — exactly as the research measured, on a venue this app can price
----------------------------------------------------------------------------------
* Signals: GLD's daily closes (and UUP / TIP / S&P 500 for gl2), read from Yahoo after the New
  York close. A decision is taken once per NYSE session, after 16:30 New York, on THAT session's
  bar — a stale bar decides nothing.
* Execution: at the next NYSE session's open (from 09:35 New York, within two hours of it), on
  Delta's XAUTUSD perpetual: each strategy is rebalanced to its target (a fraction of its sleeve
  = capital / 7) in whole 0.001 oz contracts, at the bid / ask (the book walked if needed). An
  execution missed by more than that window is skipped, never done late. No trade on an NYSE
  holiday; past the end of the holiday calendar no trade at all (fail closed).
* Costs: Delta's own taker rate x 1.18 (GST) on every contract traded, and funding at every
  4-hourly exchange on the contracts held (longs pay, shorts receive) — the venue's real costs,
  under which holding gold long would have earned ~nothing over 2004-26 (funding ~11% a year).
* Accounting: average-price holdings; a cut realises (exit - average) on the part sold; a flip
  closes the old side and opens the new at the same fill.

This module never places an order anywhere.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time as _time
from datetime import date, datetime, time, timedelta, timezone, tzinfo

import pandas as pd

from app.core.db import db
from app.services import gold_delta_feed
from app.services.gold_lab_rules import (LAB_IDS, LAB_STRATEGIES, calendar_known, is_nyse_day,
                                         next_nyse_day, nyse_days, targets)

logger = logging.getLogger("gold_lab")

CAPITAL = float(os.getenv("GOLD_LAB_CAPITAL", "10000"))
SYMBOL = "XAUTUSD"
DELTA_GST = float(os.getenv("GOLD_DELTA_GST_PCT", "0.18"))
DECIDE_AFTER = time(16, 30)        # New York: the session's bar is final
EXECUTE_AFTER = time(9, 35)        # New York: five minutes into the next session
EXECUTE_WINDOW = timedelta(hours=2)
PREREG_ID = "lab:prereg"

state_coll = db["gold_lab_state"]
holdings_coll = db["gold_lab_holdings"]
fills_coll = db["gold_lab_fills"]
equity_coll = db["gold_lab_equity"]


# ── New York time ────────────────────────────────────────────────────────────────


class _NewYork(tzinfo):                            # US Eastern with the 2007+ DST rules
    """Fallback when the system has no tz database: DST from the second Sunday of March 02:00 to
    the first Sunday of November 02:00, local time."""

    def _dst_on(self, dt: datetime) -> bool:
        y = dt.year
        mar1 = date(y, 3, 1)
        start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)       # 2nd Sunday of March
        nov1 = date(y, 11, 1)
        end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)             # 1st Sunday of November
        naive = dt.replace(tzinfo=None)
        return datetime(start.year, start.month, start.day, 2) <= naive < datetime(end.year, end.month, end.day, 2)

    def utcoffset(self, dt):
        return timedelta(hours=-4) if dt is not None and self._dst_on(dt) else timedelta(hours=-5)

    def dst(self, dt):
        return timedelta(hours=1) if dt is not None and self._dst_on(dt) else timedelta(0)

    def tzname(self, dt):
        return "EDT" if self.dst(dt) else "EST"

    def fromutc(self, dt):
        std = dt + timedelta(hours=-5)
        return (dt + timedelta(hours=-4)) if self._dst_on(std + timedelta(hours=1)) else std


try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 - no tz database in the image
    NY = _NewYork()


def ny_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(NY)


def _at(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=NY)


def last_session(now: datetime) -> date:
    """The latest NYSE session whose bar is final (16:30 New York has passed)."""
    d = now.date()
    if not (is_nyse_day(d) and now >= _at(d, DECIDE_AFTER)):
        d -= timedelta(days=1)
        while not is_nyse_day(d):
            d -= timedelta(days=1)
    return d


def decision_due(now: datetime, bar_date: date) -> bool:
    """A decision on `bar_date` may be taken only while it is the latest final session and the
    next session has not opened."""
    return (calendar_known(bar_date) and bar_date == last_session(now)
            and now < _at(next_nyse_day(bar_date), EXECUTE_AFTER))


def execution_due(now: datetime, bar_date: date):
    """True inside the next session's opening window; False before it; "stale" after it."""
    session = next_nyse_day(bar_date)
    if not calendar_known(session):
        return False
    start = _at(session, EXECUTE_AFTER)
    if now < start:
        return False
    if now <= start + EXECUTE_WINDOW:
        return True
    return "stale"


# ── pure book arithmetic ─────────────────────────────────────────────────────────


def contracts_for(fraction: float, sleeve: float, price: float, cv: float) -> int:
    if not price or not cv:
        return 0
    return int(round(float(fraction) * sleeve / (price * cv)))


def apply_fill(h: dict, dq: int, price: float, cv: float, fee_rate: float, gst: float = DELTA_GST) -> dict:
    """Average-price accounting for a fill of `dq` contracts (signed) at `price`."""
    h = dict(h)
    q, a = int(h.get("contracts") or 0), float(h.get("avg_price") or 0.0)
    fee = abs(dq) * cv * price * fee_rate * (1 + gst)
    h["fees"] = float(h.get("fees") or 0.0) + fee
    if q == 0 or (q > 0) == (dq > 0):                       # opening or adding
        nq = q + dq
        h["avg_price"] = (a * abs(q) + price * abs(dq)) / abs(nq) if nq else 0.0
        h["contracts"] = nq
        return h
    closing = min(abs(dq), abs(q))                          # reducing, closing or flipping
    h["realized"] = float(h.get("realized") or 0.0) + closing * cv * (price - a) * (1 if q > 0 else -1)
    nq = q + dq
    h["contracts"] = nq
    if nq == 0:
        h["avg_price"] = 0.0
    elif (nq > 0) != (q > 0):                               # flipped: the rest opens at the fill
        h["avg_price"] = price
    return h


def funding_due(contracts: int, cv: float, mark: float, rate_pct: float) -> float:
    """What one exchange costs a holding (positive = paid; a positive rate charges longs)."""
    return float(contracts) * cv * float(mark) * float(rate_pct) / 100.0


def unrealized(h: dict, mark: float, cv: float) -> float:
    q = int(h.get("contracts") or 0)
    return q * cv * (float(mark) - float(h.get("avg_price") or 0.0)) if q else 0.0


def sleeve() -> float:
    return CAPITAL / len(LAB_IDS)


# ── inputs ───────────────────────────────────────────────────────────────────────

YAHOO = {"gld": "GLD", "uup": "UUP", "tip": "TIP", "spx": "^GSPC"}


async def fetch_closes(rng: str = "5y") -> pd.DataFrame | None:
    """Daily closes on GLD's (NYSE) calendar; the drivers forward-filled onto it, as researched."""
    import httpx

    from app.services.global_cues import HEADERS, _chart
    out = {}
    async with httpx.AsyncClient(timeout=25, headers=HEADERS, follow_redirects=True) as c:
        for col, sym in YAHOO.items():
            ch = await _chart(c, sym, rng)
            if not ch or len(ch["rows"]) < 300:
                logger.warning("gold lab: no daily history for %s", sym)
                return None
            s = pd.Series({pd.Timestamp(d): float(v) for d, v in ch["rows"] if v})
            out[col] = s[~s.index.duplicated(keep="last")].sort_index()
    gld = out["gld"]
    df = pd.DataFrame({"gld": gld})
    for col in ("uup", "tip", "spx"):
        s = out[col]
        df[col] = s.reindex(gld.index.union(s.index)).ffill().reindex(gld.index)
    return df.dropna()


# ── state ────────────────────────────────────────────────────────────────────────


async def get_state() -> dict:
    d = await state_coll.find_one({"_id": "lab"}) or {}
    return {"enabled": bool(d.get("enabled", False)), "last_run_at": d.get("last_run_at"),
            "last_note": d.get("last_note")}


def _fingerprint(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


PREREGISTRATION = {
    "id": "GOLD-LAB-B", "written": "2026-10-11",
    "what": ("Seven daily gold strategies from the 2026-10 search (157 variants, all registered): "
             "profitable after costs in selection 2004-14, validation 2015-19 and a holdout 2020-26 "
             "opened once — but none proven better than holding gold after the luck correction. "
             "Recorded forward, unchanged, on Delta XAUTUSD."),
    "strategies": [{k: s[k] for k in ("id", "key", "name", "how", "evidence")} for s in LAB_STRATEGIES],
    "execution": ("decide after 16:30 New York on the session's GLD bar; rebalance at the next NYSE "
                  "session's open (09:35-11:35 New York) at the bid / ask; sleeve = capital / 7; "
                  "whole 0.001 oz contracts; missed windows skipped, never traded late"),
    "costs": "Delta taker rate x 1.18 per contract traded; funding at every 4-hourly exchange held",
    "capital_usd": CAPITAL,
    "what_a_record_can_mean": ("a record only; any of these reaches money solely through the Commodity "
                               "Lab gate (beat holding gold, survive deflation, incubation on real fills)"),
}


async def ensure_preregistered() -> dict:
    try:
        st = await state_coll.find_one({"_id": PREREG_ID})
        fp = _fingerprint(PREREGISTRATION)
        if st is None:
            await state_coll.insert_one({"_id": PREREG_ID, "doc": PREREGISTRATION, "fingerprint": fp,
                                         "stored_at": datetime.now(timezone.utc)})
            return {"stored": True, "fingerprint": fp}
        return {"stored": False, "fingerprint": st.get("fingerprint"), "code_fingerprint": fp}
    except Exception:  # noqa: BLE001
        logger.exception("gold lab: pre-registration not stored")
        return {"error": True}


async def set_enabled(enabled: bool) -> dict:
    if enabled:
        got = await ensure_preregistered()
        if got.get("error"):
            raise RuntimeError("The Gold Lab's pre-registration could not be stored.")
    await state_coll.update_one({"_id": "lab"}, {"$set": {"enabled": bool(enabled),
                                                          "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    return await summary()


# ── the two steps ────────────────────────────────────────────────────────────────


async def decide(closes: pd.DataFrame, now: datetime | None = None) -> dict:
    """Store each strategy's target for the latest final session — once per session."""
    now = (now or ny_now()).astimezone(NY)
    bar = closes.index[-1].date()
    if not decision_due(now, bar):
        return {"decided": False, "bar_date": bar.isoformat(),
                "why": f"no decision due on the {bar.isoformat()} bar now (latest final session {last_session(now)})"}
    cur = await state_coll.find_one({"_id": "lab:decision"}) or {}
    if cur.get("bar_date") == bar.isoformat():
        return {"decided": False, "unchanged": True, "bar_date": bar.isoformat()}
    future = nyse_days(bar + timedelta(days=1), bar + timedelta(days=20))
    tg = targets(closes, future).iloc[-1]
    tdict = {sid: round(float(tg[sid]), 6) for sid in LAB_IDS}
    doc = {"bar_date": bar.isoformat(), "targets": tdict, "decided_at": datetime.now(timezone.utc),
           "session": next_nyse_day(bar).isoformat(), "executed": False, "skipped": False,
           "closes": {k: round(float(v), 4) for k, v in closes.iloc[-1].items()}}
    await state_coll.update_one({"_id": "lab:decision"}, {"$set": doc}, upsert=True)
    await state_coll.update_one({"_id": f"dec:{bar.isoformat()}"}, {"$set": doc}, upsert=True)
    return {"decided": True, **doc}


async def _holding(sid: str) -> dict:
    return await holdings_coll.find_one({"sid": sid}) or {"sid": sid, "contracts": 0, "avg_price": 0.0,
                                                          "realized": 0.0, "fees": 0.0, "funding": 0.0,
                                                          "funding_through": int(_time.time())}


async def _save(h: dict) -> None:
    h = {k: v for k, v in h.items() if k != "_id"}
    await holdings_coll.update_one({"sid": h["sid"]}, {"$set": h}, upsert=True)


async def accrue_funding(spec: dict, until_ts: int | None = None) -> float:
    """Funding at every exchange each holding was open across, since its last accrual."""
    until = int(until_ts or _time.time())
    interval = int(spec.get("funding_interval_s") or 14400)
    cv = float(spec.get("contract_value") or 0.001)
    series = await gold_delta_feed.funding_series(SYMBOL)
    total = 0.0
    async for h in holdings_coll.find({}):
        since = int(h.get("funding_through") or until)
        if until <= since:
            continue
        q = int(h.get("contracts") or 0)
        first = (since // interval + 1) * interval
        paid = 0.0
        if q:
            mark = float(h.get("mark") or h.get("avg_price") or 0.0)
            for t in range(first, until + 1, interval):
                rate, _basis = gold_delta_feed.rate_at(series, t)
                paid += funding_due(q, cv, mark, rate or 0.0)
        last = first + ((until - first) // interval) * interval if until >= first else since
        await holdings_coll.update_one({"sid": h["sid"]}, {"$set": {
            "funding": float(h.get("funding") or 0.0) + paid, "funding_through": max(last, since)}})
        total += paid
    return total


async def execute(now: datetime | None = None) -> dict:
    """Rebalance every strategy to the pending decision's targets — at the next session's open."""
    now = (now or ny_now()).astimezone(NY)
    dec = await state_coll.find_one({"_id": "lab:decision"})
    if not dec or dec.get("executed") or dec.get("skipped"):
        return {"executed": False, "why": "nothing pending"}
    bar = date.fromisoformat(dec["bar_date"])
    due = execution_due(now, bar)
    if due is False:
        return {"executed": False, "why": f"waiting for the {next_nyse_day(bar).isoformat()} open"}
    if due == "stale":
        await state_coll.update_one({"_id": "lab:decision"}, {"$set": {"skipped": True,
                                    "skip_reason": "the opening window passed — never traded late"}})
        return {"executed": False, "skipped": True}
    spec = await gold_delta_feed.product(SYMBOL)
    fee_rate = spec.get("taker_fee_rate")
    if not fee_rate:
        return {"executed": False, "why": "the venue publishes no taker fee — refusing rather than charging zero"}
    t = await gold_delta_feed.ticker(SYMBOL)
    if not t or not t.get("mid"):
        return {"executed": False, "why": "no two-sided XAUTUSD market"}
    cv = float(spec.get("contract_value") or 0.001)
    await accrue_funding(spec)
    fills, notes = 0, []
    for sid in LAB_IDS:
        h = await _holding(sid)
        want = contracts_for(dec["targets"].get(sid, 0.0), sleeve(), float(t["mid"]), cv)
        dq = want - int(h.get("contracts") or 0)
        if dq == 0:
            continue
        f = await gold_delta_feed.fill_price(SYMBOL, "BUY" if dq > 0 else "SELL", abs(dq))
        if not f:
            notes.append(f"{sid}: the visible book could not fill {abs(dq)} contracts")
            continue
        price = float(f["price"])
        h = apply_fill(h, dq, price, cv, float(fee_rate))
        h["funding_through"] = int(_time.time()) if not h.get("funding_through") else h["funding_through"]
        h["mark"] = float(t.get("mark") or t["mid"])
        await _save(h)
        await fills_coll.insert_one({"sid": sid, "bar_date": dec["bar_date"], "session": dec["session"],
                                     "contracts": int(dq), "price": round(price, 4), "basis": f.get("basis"),
                                     "spread_bp": f.get("spread_bp"), "target": dec["targets"].get(sid),
                                     "fee": round(abs(dq) * cv * price * float(fee_rate) * (1 + DELTA_GST), 6),
                                     "at": datetime.now(timezone.utc)})
        fills += 1
    await state_coll.update_one({"_id": "lab:decision"}, {"$set": {
        "executed": True, "executed_at": datetime.now(timezone.utc), "fills": fills, "notes": notes}})
    await state_coll.update_one({"_id": f"dec:{dec['bar_date']}"}, {"$set": {"executed": True, "fills": fills}})
    return {"executed": True, "fills": fills, "notes": notes}


async def mark_and_snapshot() -> dict:
    """Mark every holding at Delta's mark; write one equity row per New York date."""
    m = await gold_delta_feed.mark_price(SYMBOL)
    spec = await gold_delta_feed.product(SYMBOL)
    cv = float(spec.get("contract_value") or 0.001)
    rows = {}
    async for h in holdings_coll.find({}):
        if m:
            await holdings_coll.update_one({"sid": h["sid"]}, {"$set": {"mark": float(m)}})
            h["mark"] = float(m)
        rows[h["sid"]] = (float(h.get("realized") or 0) - float(h.get("fees") or 0) - float(h.get("funding") or 0)
                          + unrealized(h, float(h.get("mark") or 0), cv))
    today = ny_now().date().isoformat()
    if rows and not await equity_coll.find_one({"date": today}):
        await equity_coll.insert_one({"date": today, "at": datetime.now(timezone.utc),
                                      "equity": CAPITAL + sum(rows.values()),
                                      "by_strategy": {k: round(v, 4) for k, v in rows.items()}, "mark": m})
    return {"mark": m, "net": sum(rows.values())}


async def cycle(entries_allowed: bool = True) -> dict:
    """One pass: fund and mark what is held; decide and execute when due."""
    st = await get_state()
    held = await holdings_coll.count_documents({"contracts": {"$ne": 0}})
    out: dict = {"enabled": st["enabled"], "held": held}
    if not st["enabled"] and not held:
        return out
    spec = await gold_delta_feed.product(SYMBOL)
    if held:
        await gold_delta_feed.refresh_funding(SYMBOL)
        await accrue_funding(spec)
    if st["enabled"] and entries_allowed:
        now = ny_now()
        sess = last_session(now)
        cur = await state_coll.find_one({"_id": "lab:decision"}) or {}
        if cur.get("bar_date") != sess.isoformat() and decision_due(now, sess):
            closes = await fetch_closes()
            if closes is None:
                out["note"] = "inputs unavailable — no decision"
            elif closes.index[-1].date() != sess:
                out["note"] = f"GLD's latest bar is {closes.index[-1].date()}, not {sess} — no decision on a stale bar"
            else:
                out["decision"] = await decide(closes, now)
        out["execution"] = await execute(now)
    out["mark"] = await mark_and_snapshot()
    note = out.get("note") or (out.get("execution") or {}).get("why")
    await state_coll.update_one({"_id": "lab"}, {"$set": {"last_run_at": datetime.now(timezone.utc),
                                                          "last_note": note}}, upsert=True)
    return out


async def close_all() -> dict:
    """Flatten every holding at the touch now (a manual act, recorded as such)."""
    spec = await gold_delta_feed.product(SYMBOL)
    fee_rate = spec.get("taker_fee_rate")
    if not fee_rate:
        return {"closed": 0, "why": "no fee published"}
    cv = float(spec.get("contract_value") or 0.001)
    await accrue_funding(spec)
    closed, left = 0, []
    async for h in holdings_coll.find({"contracts": {"$ne": 0}}):
        dq = -int(h["contracts"])
        f = await gold_delta_feed.fill_price(SYMBOL, "BUY" if dq > 0 else "SELL", abs(dq))
        if not f:
            left.append(h["sid"])
            continue
        h2 = apply_fill(h, dq, float(f["price"]), cv, float(fee_rate))
        await _save(h2)
        await fills_coll.insert_one({"sid": h["sid"], "bar_date": None, "session": None, "contracts": dq,
                                     "price": round(float(f["price"]), 4), "basis": f.get("basis"),
                                     "reason": "manual_close_all", "at": datetime.now(timezone.utc)})
        closed += 1
    return {"closed": closed, "left_open": left}


# ── read model ───────────────────────────────────────────────────────────────────


def _iso(x):
    return x.isoformat() if isinstance(x, datetime) else x


async def summary() -> dict:
    st = await get_state()
    pre = await state_coll.find_one({"_id": PREREG_ID})
    dec = await state_coll.find_one({"_id": "lab:decision"}) or {}
    spec_cv = 0.001
    rows, total = [], {"realized": 0.0, "fees": 0.0, "funding": 0.0, "unrealized": 0.0}
    holds = {h["sid"]: h async for h in holdings_coll.find({})}
    fills_n = {}
    async for f in fills_coll.aggregate([{"$group": {"_id": "$sid", "n": {"$sum": 1}}}]):
        fills_n[f["_id"]] = f["n"]
    for s in LAB_STRATEGIES:
        h = holds.get(s["id"], {})
        mark = float(h.get("mark") or 0.0)
        u = unrealized(h, mark, spec_cv) if h else 0.0
        net = float(h.get("realized") or 0) - float(h.get("fees") or 0) - float(h.get("funding") or 0) + u
        for k, v in (("realized", float(h.get("realized") or 0)), ("fees", float(h.get("fees") or 0)),
                     ("funding", float(h.get("funding") or 0)), ("unrealized", u)):
            total[k] += v
        rows.append({
            "id": s["id"], "name": s["name"], "how": s["how"], "cluster": s["cluster"], "key": s["key"],
            "evidence": s["evidence"], "target": (dec.get("targets") or {}).get(s["id"]),
            "contracts": int(h.get("contracts") or 0), "avg_price": round(float(h.get("avg_price") or 0), 4),
            "mark": mark, "notional": round(abs(int(h.get("contracts") or 0)) * spec_cv * mark, 2),
            "realized": round(float(h.get("realized") or 0), 4), "fees": round(float(h.get("fees") or 0), 4),
            "funding": round(float(h.get("funding") or 0), 4), "unrealized": round(u, 4), "net": round(net, 4),
            "net_pct_of_sleeve": round(net / sleeve() * 100, 3), "fills": fills_n.get(s["id"], 0),
        })
    net_total = total["realized"] - total["fees"] - total["funding"] + total["unrealized"]
    return {
        "label": "Gold Lab · 7 tested strategies", "venue": "Delta XAUTUSD", "currency": "USD",
        "enabled": st["enabled"], "capital": CAPITAL, "sleeve": round(sleeve(), 2),
        "equity": round(CAPITAL + net_total, 2), "net_pnl": round(net_total, 2),
        "net_pct": round(net_total / CAPITAL * 100, 3), **{k: round(v, 4) for k, v in total.items()},
        "strategies": rows,
        "decision": {k: _iso(v) for k, v in dec.items() if k != "_id"} if dec else None,
        "preregistered": bool(pre), "fingerprint": pre.get("fingerprint") if pre else None,
        "stored_at": _iso(pre.get("stored_at")) if pre else None,
        "last_run_at": _iso(st.get("last_run_at")), "last_note": st.get("last_note"),
        "calendar_through": "2028-12-31",
        "tier_note": ("Tier B: profitable after costs in 2004-14, 2015-19 and an untouched 2020-26 holdout; "
                      "NOT proven better than holding gold (0 of 157 variants survived the luck correction)."),
    }


async def fills(limit: int = 200) -> list[dict]:
    out = []
    async for f in fills_coll.find({}).sort("at", -1).limit(limit):
        f.pop("_id", None)
        out.append({k: _iso(v) for k, v in f.items()})
    return out


async def ensure_indexes() -> None:
    try:
        await holdings_coll.create_index("sid", unique=True)
        await fills_coll.create_index([("at", -1)])
        await equity_coll.create_index("date", unique=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gold lab indexes skipped: %s", exc)
