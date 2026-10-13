"""NIFTY BANK paper desk - Index Option Buying > NIFTY BANK (2026-10-11).

Runs, on PAPER, the ten strategies the BANKNIFTY option-buying research chose
(backend/research/banknifty_2026_10, shipped as app/data/banknifty_research.json, which names
them, their evidence tier and their backtests). Nothing here is tuned on forward data, and the
tier on each strategy says how strong its evidence is: ten strategies are not ten proven edges.

WHAT IT BUYS - the research's contract rule, exactly
  BANKNIFTY MONTHLY options (NSE has listed no BANKNIFTY weekly since Nov 2024), 1 lot, the
  strike nearest the spot at the decision. Intraday rules: the nearest monthly with >= 7
  sessions left (today counted); daily rules: >= 15, closed - and re-bought in the next monthly
  if still wanted - once it has <= 3 left.

HOW IT DECIDES - on the bars the research replayed
  Intraday rules read CLOSED NIFTY BANK 5m / 15m bars from the backend's bar store, one decision
  per closed bar, no new position on a bar ending after 15:00, flat by 15:15. Library strategies
  are fresh each session, warmed on their last 400 bars, asked for a signal only while flat (at
  most 6 trades a session), as the replay ran them. Daily rules decide once, at 15:20, with
  today's bar cut at 15:20.

HOW IT FILLS - twice, as every desk here has since Oct 2026
  paper at the last traded price; real-money at the order book - bought at the ask, sold at the
  bid - with Angel's charges. A book wider than 2% of its mid is refused and the refusal noted.
Paper only: nothing in this module can place an order.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import statistics
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

from app.core.db import db, instruments_collection
from app.services import banknifty_strategies as B
from app.services import market_calendar

logger = logging.getLogger("banknifty_desk")

IST = timezone(timedelta(hours=5, minutes=30))
SWITCH_KEY = "banknifty_desk"
RESEARCH_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "banknifty_research.json")
INDEX = "NIFTYBANK"
INDEX_TOKEN = "99926009"
UNDERLYING = "BANKNIFTY"
STEP = 100
LOTS = 1
CAPITAL_PER_STRATEGY = float(os.getenv("BN_DESK_CAPITAL", "200000"))
MIN_LEFT_INTRADAY, MIN_LEFT_DAILY, ROLL_AT_LEFT = 7, 15, 3
MAX_TRADES_LIBRARY = 6
MAX_SPREAD_PCT = float(os.getenv("BN_DESK_MAX_SPREAD_PCT", "0.02"))
EST_HALF_SPREAD_PCT = 0.0025
TICK_SECONDS = 15

positions = db["bn_desk_positions"]
signals = db["bn_desk_signals"]
state_coll = db["bn_desk_state"]

status: dict = {"running": False, "last_cycle": None, "last_action": None, "errors": 0, "last_error": None,
                "notes": [], "session": None}
_research: dict | None = None
_lib: dict[str, dict] = {}          # library intraday slots, rebuilt each session
_daily_built: dict[str, dict] = {}  # library daily instances, rebuilt each decision day
_hist_cache: dict = {}
_processed: dict[str, int] = {}     # last closed bar epoch acted on, per timeframe


# ── research file ───────────────────────────────────────────────────────────────


def research() -> dict:
    global _research
    if _research is None:
        try:
            with open(RESEARCH_FILE, encoding="utf-8") as f:
                _research = json.load(f)
        except (OSError, ValueError):
            logger.exception("banknifty research file unreadable")
            _research = {"selected": [], "meta": {}, "trials": []}
    return _research


def selected() -> list[dict]:
    return research().get("selected") or []


def _note(msg: str) -> None:
    status["notes"] = (status["notes"] + [f"{datetime.now(IST):%H:%M} {msg}"])[-30:]


# ── calendar and contracts ──────────────────────────────────────────────────────


def sessions_left(day: date, expiry: str) -> int:
    """NSE sessions from `day` to the expiry day, both counted."""
    end = date.fromisoformat(expiry)
    n, d = 0, day
    while d <= end:
        if market_calendar.is_listed_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


async def monthly_expiries(day: date) -> list[str]:
    """Expiries that carry a BANKNIFTY future - the monthlies - still open on `day`."""
    futs = await instruments_collection.distinct("expiry", {"asset_class": "INDEX_FUTURE", "underlying_symbol": UNDERLYING})
    opts = set(await instruments_collection.distinct("expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING}))
    return sorted(e for e in futs if e and e >= day.isoformat() and e in opts)


async def choose_expiry(day: date, min_left: int) -> str | None:
    for e in await monthly_expiries(day):
        if sessions_left(day, e) >= min_left:
            return e
    return None


async def _instrument(expiry: str, strike: float, typ: str) -> dict | None:
    return await instruments_collection.find_one(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING, "expiry": expiry, "strike": float(strike),
         "option_type": typ, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_tradingsymbol": 1, "lot_size": 1, "strike": 1})


async def _quotes(tokens: list[str]) -> dict[str, dict]:
    from app.services.angel_client import angel_client
    if not tokens:
        return {}
    return await angel_client.full_quote({"NFO": tokens})


def _est(px: float) -> float:
    return max(0.05, px * EST_HALF_SPREAD_PCT)


# ── bars ────────────────────────────────────────────────────────────────────────


def _rows(series) -> list[list]:
    return [[int(series.epochs[i]), series.o[i], series.h[i], series.l[i], series.c[i]] for i in range(len(series.epochs))]


def _day_key(e: int) -> int:
    return (e + 19800) // 86400


def today_bars(symbol: str, now: datetime) -> list[list]:
    """Today's CLOSED 5m bars of `symbol`."""
    from app.services.intraday_store import store5
    k = (now.date() - date(1970, 1, 1)).days
    return [r for r in _rows(store5.series(symbol, "5m", n=120, now=now)) if _day_key(r[0]) == k]


def history_sessions(symbol: str, before: date, n: int) -> list[list[list]]:
    """The last `n` complete sessions (>= 60 bars from 09:15) of 5m bars before `before`."""
    key = (symbol, before, n)
    if key in _hist_cache:
        return _hist_cache[key]
    from app.services.intraday_store import read_file, store5
    kb = (before - date(1970, 1, 1)).days
    seen: dict[int, list] = {}
    for b in (read_file(symbol, "5m"), store5.get(symbol)):     # disk, then the in-memory window
        for i in range(len(b)):
            if _day_key(b.t[i]) < kb:
                seen[int(b.t[i])] = [int(b.t[i]), b.o[i], b.h[i], b.l[i], b.c[i]]
    by: dict[int, list] = {}
    for t in sorted(seen):
        by.setdefault(_day_key(t), []).append(seen[t])
    good = [by[k] for k in sorted(by) if len(by[k]) >= 60 and ((by[k][0][0] + 19800) % 86400) // 60 == B.OPEN_MIN]
    out = good[-n:]
    if len(_hist_cache) > 16:
        _hist_cache.clear()
    _hist_cache[key] = out
    return out


def _bar_end_min(r) -> int:
    return B.bar_minute(int(r[0])) + 5


# ── fills ───────────────────────────────────────────────────────────────────────


async def open_position(strat: dict, kind: str, spot: float, now: datetime, decision: dict) -> dict | None:
    daily = strat["source"] == "daily"
    expiry = await choose_expiry(now.date(), MIN_LEFT_DAILY if daily else MIN_LEFT_INTRADAY)
    if not expiry:
        _note(f"{strat['key']}: no monthly with enough sessions left - skipped")
        return None
    strike = round(spot / STEP) * STEP
    legs = []
    for typ in (("CE", "PE") if kind == "STRADDLE" else (kind,)):
        doc = await _instrument(expiry, strike, typ)
        if not doc:
            _note(f"{strat['key']}: {expiry} {strike:.0f}{typ} not in the instrument master - skipped")
            return None
        legs.append({"type": typ, "strike": float(strike), "expiry": expiry, "token": str(doc["angel_token"]),
                     "tradingsymbol": doc.get("angel_tradingsymbol"), "lot_size": int(doc.get("lot_size") or 30)})
    q = await _quotes([lg["token"] for lg in legs])
    for lg in legs:
        x = q.get(lg["token"]) or {}
        ltp, bid, ask = x.get("ltp"), x.get("bid"), x.get("ask")
        if not ltp:
            _note(f"{strat['key']}: no live price for {lg['tradingsymbol']} - skipped")
            return None
        if bid and ask and (ask - bid) / ((ask + bid) / 2) > MAX_SPREAD_PCT:
            _note(f"{strat['key']}: {lg['tradingsymbol']} book {bid}/{ask} wider than {MAX_SPREAD_PCT:.0%} - skipped")
            return None
        lg.update({"qty": lg["lot_size"] * LOTS, "entry_ltp": ltp, "entry_bid": bid, "entry_ask": ask,
                   "real_entry": ask or ltp + _est(ltp), "entry_basis": "book" if ask else "estimated"})
    doc = {"strategy": strat["key"], "sid": strat["sid"], "source": strat["source"], "tier": strat.get("tier"),
           "kind": kind, "status": "OPEN", "session": now.date().isoformat(), "opened_at": now.astimezone(timezone.utc),
           "spot_entry": spot, "legs": legs, "decision": decision, "expiry": expiry}
    res = await positions.insert_one(doc)
    doc["_id"] = res.inserted_id
    status["last_action"] = f"{now:%H:%M} {strat['key']} bought {expiry} {strike:.0f} {kind}"
    logger.info("banknifty desk: %s bought %s %s %s @ %s", strat["key"], expiry, strike, kind,
                [lg["real_entry"] for lg in legs])
    return doc


async def close_position(pos: dict, reason: str, now: datetime) -> dict | None:
    from tradingai_shared.option_fees import option_round_trip
    q = await _quotes([lg["token"] for lg in pos["legs"]])
    paper = real = fee_p = fee_r = 0.0
    legs = []
    for lg in pos["legs"]:
        x = q.get(lg["token"]) or {}
        ltp, bid = x.get("ltp"), x.get("bid")
        if not ltp:
            _note(f"{pos['strategy']}: no live price to close {lg.get('tradingsymbol')} - kept open")
            return None
        real_exit = bid or max(0.05, ltp - _est(ltp))
        fp = option_round_trip(lg["entry_ltp"], ltp, lg["qty"], on=now.date())["total"]
        fr = option_round_trip(lg["real_entry"], real_exit, lg["qty"], on=now.date())["total"]
        paper += (ltp - lg["entry_ltp"]) * lg["qty"] - fp
        real += (real_exit - lg["real_entry"]) * lg["qty"] - fr
        fee_p, fee_r = fee_p + fp, fee_r + fr
        legs.append({**lg, "exit_ltp": ltp, "exit_bid": bid, "exit_ask": x.get("ask"), "real_exit": real_exit,
                     "exit_basis": "book" if bid else "estimated"})
    upd = {"status": "CLOSED", "closed_at": now.astimezone(timezone.utc), "exit_reason": reason, "legs": legs,
           "paper_pnl": round(paper, 2), "real_pnl": round(real, 2), "fees_paper": round(fee_p, 2),
           "fees_real": round(fee_r, 2),
           "real_basis": "book" if all(lg["entry_basis"] == "book" and lg["exit_basis"] == "book" for lg in legs) else "estimated"}
    await positions.update_one({"_id": pos["_id"]}, {"$set": upd})
    status["last_action"] = f"{now:%H:%M} {pos['strategy']} closed ({reason}): real Rs{real:,.0f}"
    logger.info("banknifty desk: %s closed %s real %.0f paper %.0f", pos["strategy"], reason, real, paper)
    return {**pos, **upd}


async def _log_signal(strat: dict, now: datetime, what: str, detail: dict) -> None:
    try:
        await signals.insert_one({"strategy": strat["key"], "at": now.astimezone(timezone.utc),
                                  "session": now.date().isoformat(), "what": what, **detail})
    except Exception:  # noqa: BLE001 - the audit log must never stop the desk
        logger.exception("banknifty desk: signal log write failed")


# ── intraday: the bank's own rules ──────────────────────────────────────────────


async def _custom_intraday(strat: dict, now: datetime, bars: list, hist: list, nifty: list, open_pos: dict | None,
                           traded_today: int, fresh: list) -> None:
    """`fresh` = the bars closed since the last cycle that acted (normally one); exits read all of
    them, so a late tick cannot step over the bar that hit a stop. Entries read only the newest."""
    rule = _custom_rules().get(strat["sid"])
    if rule is None:
        return
    new_bar = fresh[-1]
    if open_pos:
        d = open_pos.get("decision") or {}
        end = _bar_end_min(new_bar)
        call = open_pos["kind"] == "CE"
        since = [b for b in fresh if b[0] > (d.get("entry_bar") or 0)] or [new_bar]
        lo, hi = min(b[3] for b in since), max(b[2] for b in since)
        reason = None
        if d.get("stop") is not None and ((call and lo <= d["stop"]) or (not call and hi >= d["stop"])):
            reason = "stop"
        elif d.get("target") is not None and ((call and hi >= d["target"]) or (not call and lo <= d["target"])):
            reason = "target"
        elif end >= min(d.get("exit_min") or B.SQUARE_OFF_MIN, B.SQUARE_OFF_MIN):
            reason = "time"
        if reason:
            await close_position(open_pos, reason, now)
        return
    if traded_today:
        return
    entry = rule.decide(B.Day(bars=bars, hist=hist, nifty=nifty))
    if entry is None:
        return
    kind = "CE" if entry.side > 0 else "PE"
    decision = {"stop": entry.stop, "target": entry.target, "exit_min": entry.exit_min, "why": entry.why,
                "bar_end": _bar_end_min(new_bar), "entry_bar": int(new_bar[0])}
    await _log_signal(strat, now, kind, decision)
    await open_position(strat, kind, new_bar[4], now, decision)


_CUSTOM: dict | None = None


def _custom_rules() -> dict:
    global _CUSTOM
    if _CUSTOM is None:
        _CUSTOM = {r.id: r for r in B.intraday_rules()}
    return _CUSTOM


# ── intraday: library strategies ────────────────────────────────────────────────


def _bar_objects(rows: list, tf: str):
    from tradingai_shared.domain import Bar, Timeframe
    return [Bar.model_construct(symbol="BANKNIFTY", timeframe=Timeframe(tf), ts=datetime.fromtimestamp(r[0], IST),
                                open=r[1], high=r[2], low=r[3], close=r[4], volume=0, oi=None) for r in rows]


def _tf_rows(tf: str, now: datetime) -> list[list]:
    """Closed bars of NIFTY BANK at `tf` (5m or 15m), the last ~6 sessions plus today."""
    from app.services.intraday_store import store, store5
    if tf == "5m":
        return _rows(store5.series(INDEX, "5m", n=700, now=now))
    return _rows(store.series(INDEX, "15m", n=450, now=now))


async def _library_intraday(strat: dict, now: datetime, open_pos: dict | None, traded_today: int) -> None:
    import strategy_service.strategies.options_buying  # noqa: F401
    from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
    from tradingai_shared.domain import SignalAction
    sid, tf = strat["sid"], strat["tf"]
    cls = STRATEGY_REGISTRY.get(sid)
    if cls is None:
        return
    rows = _tf_rows(tf, now)
    if not rows:
        return
    k = (now.date() - date(1970, 1, 1)).days
    slot = _lib.get(strat["key"])
    if slot is None or slot["session"] != now.date():
        before = [r for r in rows if _day_key(r[0]) < k]
        inst = cls(params={})
        ctx = StrategyContext(max_bars=max(500, inst.warmup + 5))
        for b in _bar_objects(before[-400:], tf):
            ctx.push(b)
        # bars of today that closed before this slot existed (a restart) are pushed, not acted on
        today_done = [r for r in rows if _day_key(r[0]) == k]
        for b in _bar_objects(today_done, tf):
            ctx.push(b)
        slot = {"session": now.date(), "inst": inst, "ctx": ctx, "last": rows[-1][0]}
        _lib[strat["key"]] = slot
        return
    new = [r for r in rows if r[0] > slot["last"] and _day_key(r[0]) == k]
    if not new:
        return
    style_stop, style_tgt = strat.get("stop"), strat.get("target")
    for r in new:
        slot["last"] = r[0]
        slot["ctx"].push(_bar_objects([r], tf)[0])
        tf_min = 5 if tf == "5m" else 15
        end_min = B.bar_minute(r[0]) + tf_min
        if open_pos or traded_today >= MAX_TRADES_LIBRARY or end_min > B.NO_ENTRY_AFTER_MIN \
                or len(slot["ctx"].bars) < slot["inst"].warmup:
            continue
        try:
            sg = slot["inst"].on_bar(slot["ctx"])
        except Exception:  # noqa: BLE001 - one strategy's bug must not stop the desk
            sg = None
        if sg is None or sg.signal not in (SignalAction.BUY, SignalAction.SELL):
            continue
        kind = "CE" if sg.signal == SignalAction.BUY else "PE"
        decision = {"premium_stop_pct": style_stop, "premium_target_pct": style_tgt, "bar_end": end_min,
                    "why": (sg.reasoning or "")[:160]}
        await _log_signal(strat, now, kind, decision)
        pos = await open_position(strat, kind, r[4], now, decision)
        if pos:
            open_pos = pos
            traded_today += 1


async def _library_premium_exits(open_pos: dict, now: datetime) -> None:
    d = open_pos.get("decision") or {}
    stop, tgt = d.get("premium_stop_pct"), d.get("premium_target_pct")
    if stop is None and tgt is None:
        return
    lg = open_pos["legs"][0]
    q = await _quotes([lg["token"]])
    ltp = (q.get(lg["token"]) or {}).get("ltp")
    if not ltp:
        return
    if stop is not None and ltp <= lg["entry_ltp"] * (1 - stop):
        await close_position(open_pos, "stop", now)
    elif tgt is not None and ltp >= lg["entry_ltp"] * (1 + tgt):
        await close_position(open_pos, "target", now)


# ── daily rules ─────────────────────────────────────────────────────────────────


def _daily_bars(hist: list, today: list) -> list[dict]:
    out = []
    for s in hist:
        dec = [b for b in s if _bar_end_min(b) <= B.DAILY_DECISION_MIN]
        out.append({"k": _day_key(s[0][0]), "o": s[0][1], "h": max(b[2] for b in s), "l": min(b[3] for b in s),
                    "c": s[-1][4], "dh": max(b[2] for b in dec), "dl": min(b[3] for b in dec), "dc": dec[-1][4]})
    if today:
        dec = [b for b in today if _bar_end_min(b) <= B.DAILY_DECISION_MIN]
        out.append({"k": _day_key(today[0][0]), "o": today[0][1], "h": max(b[2] for b in dec), "l": min(b[3] for b in dec),
                    "c": dec[-1][4], "dh": max(b[2] for b in dec), "dl": min(b[3] for b in dec), "dc": dec[-1][4]})
    return out


def _library_daily_want(strat: dict, days: list[dict]) -> str | None:
    """Replay the library strategy over the daily history exactly as the research did (each day
    decided on its bar cut at 15:20, then the full bar kept) and return what it wants today."""
    import strategy_service.strategies.options_buying  # noqa: F401
    from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
    from tradingai_shared.domain import Bar, SignalAction, Timeframe
    cls = STRATEGY_REGISTRY.get(strat["sid"])
    if cls is None:
        return None
    inst = cls(params={})
    ctx = StrategyContext(max_bars=max(600, inst.warmup + 5))
    want = None

    def bar(d, partial):
        return Bar.model_construct(symbol="BANKNIFTY", timeframe=Timeframe("1d"),
                                   ts=datetime.fromtimestamp(d["k"] * 86400 - 19800 + B.OPEN_MIN * 60, IST),
                                   open=d["o"], high=d["dh"] if partial else d["h"], low=d["dl"] if partial else d["l"],
                                   close=d["dc"] if partial else d["c"], volume=0, oi=None)

    for d in days:
        ctx.push(bar(d, True))
        sg = None
        if len(ctx.bars) >= inst.warmup:
            try:
                sg = inst.on_bar(ctx)
            except Exception:  # noqa: BLE001
                sg = None
        ctx.bars[-1] = bar(d, False)
        if sg is not None:
            if sg.signal == SignalAction.BUY:
                want = "CE"
            elif sg.signal == SignalAction.SELL:
                want = "PE"
            elif sg.signal in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT):
                want = None
    return want


def _sessions_to_event(day: date) -> int | None:
    events = sorted(date.fromisoformat(x) for x in B.RBI_POLICY + B.UNION_BUDGET)
    for ev in events:
        d = ev
        while not market_calendar.is_listed_trading_day(d):
            d += timedelta(days=1)
        if d < day:
            continue
        n, x = 0, day
        while x < d:
            x += timedelta(days=1)
            if market_calendar.is_listed_trading_day(x):
                n += 1
        return n if n <= 10 else None
    return None


async def _atm_iv(day: date, spot: float) -> float | None:
    """Today's ATM implied vol of the daily contract, from live CE/PE mids (trading-day vol)."""
    expiry = await choose_expiry(day, MIN_LEFT_DAILY)
    if not expiry:
        return None
    K = round(spot / STEP) * STEP
    ce, pe = await _instrument(expiry, K, "CE"), await _instrument(expiry, K, "PE")
    if not ce or not pe:
        return None
    q = await _quotes([str(ce["angel_token"]), str(pe["angel_token"])])
    c, p = (q.get(str(ce["angel_token"])) or {}).get("ltp"), (q.get(str(pe["angel_token"])) or {}).get("ltp")
    if not c or not p:
        return None
    T = max(sessions_left(day, expiry) - 0.15, 0.2) / 252
    F = K + (c - p)
    lo, hi = 0.01, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        v = mid * math.sqrt(T)
        d1 = (math.log(F / K) + 0.5 * v * v) / v
        price = F * _ncdf(d1) - K * _ncdf(d1 - v) + K * _ncdf(-(d1 - v)) - F * _ncdf(-d1)
        if price > c + p:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


async def _daily(strat: dict, now: datetime, open_pos: dict | None, today: list, hist: list) -> None:
    days = _daily_bars(hist, today)
    if not days:
        return
    custom = {r.id: r for r in B.daily_rules()}.get(strat["sid"])
    age = 0
    if open_pos:
        age = max(0, sessions_left(date.fromisoformat(open_pos["session"]), now.date().isoformat()) - 1)
    if custom:
        bars = [B.DailyBar(d["k"], d["o"], d["h"], d["l"], d["c"]) for d in days[-261:]]
        ctx = {"holding": open_pos["kind"] if open_pos else None, "age": age,
               "sessions_to_event": _sessions_to_event(now.date())}
        if custom.fn is B._cheap_vol:
            ctx["atm_iv"] = await _atm_iv(now.date(), days[-1]["c"])
        want = custom.target(bars, ctx)
        stop_pct, tgt_pct, max_hold = custom.stop_pct, custom.target_pct, custom.max_hold
    else:
        want = _library_daily_want(strat, days)
        stop_pct, tgt_pct, max_hold = 0.40, 0.80, 60
    await _log_signal(strat, now, f"daily want {want}", {"age": age})
    reason = None
    if open_pos:
        q = await _quotes([lg["token"] for lg in open_pos["legs"]])
        marks = [(q.get(lg["token"]) or {}).get("ltp") for lg in open_pos["legs"]]
        if all(marks):
            ret = sum(marks) / sum(lg["entry_ltp"] for lg in open_pos["legs"]) - 1
            if stop_pct is not None and ret <= -stop_pct:
                reason = "stop"
            elif tgt_pct is not None and ret >= tgt_pct:
                reason = "target"
        if reason is None and want != open_pos["kind"]:
            reason = "signal"
        if reason is None and age >= max_hold:
            reason = "max_hold"
        if reason is None and sessions_left(now.date(), open_pos["expiry"]) <= ROLL_AT_LEFT:
            reason = "roll"
        if reason:
            closed = await close_position(open_pos, reason, now)
            if closed is None:
                return
            open_pos = None
            if reason in ("stop", "target", "max_hold"):
                return
    if open_pos is None and want:
        await open_position(strat, want, days[-1]["c"], now, {"why": f"daily rule wants {want}", "bar": "15:20"})


# ── the cycle ───────────────────────────────────────────────────────────────────


async def _open_by_strategy() -> dict[str, dict]:
    return {p["strategy"]: p async for p in positions.find({"status": "OPEN"})}


async def _traded_today(day: date) -> dict[str, int]:
    out: dict[str, int] = {}
    async for p in positions.find({"session": day.isoformat()}, {"strategy": 1}):
        out[p["strategy"]] = out.get(p["strategy"], 0) + 1
    return out


async def cycle(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    status["last_cycle"] = now.isoformat()
    if not market_calendar.is_trading_day(now) or not market_calendar.in_session(now):
        status["session"] = "closed"
        return {}
    status["session"] = "open"
    strats = selected()
    if not strats:
        return {}
    hm = now.hour * 60 + now.minute
    open_by = await _open_by_strategy()
    traded = await _traded_today(now.date())
    # 15:15 - every intraday position goes, whatever its rule says
    if hm >= B.SQUARE_OFF_MIN:
        for s in strats:
            p = open_by.get(s["key"])
            if p and s["source"] != "daily":
                await close_position(p, "square_off", now)
                open_by.pop(s["key"], None)
    bars = today_bars(INDEX, now)
    last = _processed.get("5m", 0)
    fresh = [b for b in bars if b[0] > last]
    if fresh and hm < B.SQUARE_OFF_MIN:
        _processed["5m"] = bars[-1][0]
        hist = history_sessions(INDEX, now.date(), 20)
        nifty = today_bars("NIFTY", now)
        nifty = nifty if len(nifty) == len(bars) else None
        for s in strats:
            if s["source"] == "custom_intraday":
                await _custom_intraday(s, now, bars, hist, nifty, open_by.get(s["key"]), traded.get(s["key"], 0), fresh)
    if hm < B.SQUARE_OFF_MIN:
        for s in strats:
            if s["source"] == "library_intraday":
                p = open_by.get(s["key"])
                if p:
                    await _library_premium_exits(p, now)
                    p = (await positions.find_one({"_id": p["_id"], "status": "OPEN"}))
                await _library_intraday(s, now, p, traded.get(s["key"], 0))
    # 15:20 - the daily rules, once a session
    if B.DAILY_DECISION_MIN <= hm < 15 * 60 + 29 and status.get("daily_done") != now.date().isoformat():
        daily = [s for s in strats if s["source"] == "daily"]
        if daily and bars and _bar_end_min(bars[-1]) >= B.DAILY_DECISION_MIN:
            hist = history_sessions(INDEX, now.date(), 400)
            for s in daily:
                await _daily(s, now, open_by.get(s["key"]), bars, hist)
            status["daily_done"] = now.date().isoformat()
        elif not daily:
            status["daily_done"] = now.date().isoformat()
    return {"open": len(open_by)}


async def banknifty_desk_loop() -> None:
    from app.services import desk_switches
    logger.info("banknifty desk: %d strategies from %s", len(selected()), os.path.basename(RESEARCH_FILE))
    status["running"] = True
    while True:
        try:
            await desk_switches.gated(SWITCH_KEY, cycle)
        except Exception as exc:  # noqa: BLE001 - retried next tick
            status["errors"] += 1
            status["last_error"] = f"{type(exc).__name__}: {exc}"[:240]
            logger.exception("banknifty desk cycle failed")
        await asyncio.sleep(TICK_SECONDS)


# ── read side ───────────────────────────────────────────────────────────────────


def _clean(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    for k in ("opened_at", "closed_at", "at"):
        if isinstance(out.get(k), datetime):
            v = out[k]
            out[k] = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return out


async def summary() -> dict:
    strats = selected()
    closed: dict[str, list] = {}
    trades = []
    async for p in positions.find({"status": "CLOSED"}).sort("closed_at", -1):
        closed.setdefault(p["strategy"], []).append(p)
        if len(trades) < 120:
            trades.append(_clean(p))
    open_docs = [p async for p in positions.find({"status": "OPEN"})]
    marks = {}
    try:
        marks = await _quotes(sorted({lg["token"] for p in open_docs for lg in p["legs"]}))
    except Exception:  # noqa: BLE001 - a quote outage must not blank the page
        logger.warning("banknifty desk: marks unavailable")
    open_rows = []
    for p in open_docs:
        unreal, live = 0.0, True
        for lg in p["legs"]:
            x = marks.get(lg["token"]) or {}
            bid = x.get("bid") or x.get("ltp")
            if not bid:
                live = False
                continue
            unreal += (bid - lg["real_entry"]) * lg["qty"]
            lg["mark"] = x.get("ltp")
            lg["mark_bid"] = x.get("bid")
        open_rows.append({**_clean(p), "unrealized_real": round(unreal, 2) if live else None})
    rows = []
    for s in strats:
        cs = closed.get(s["key"], [])
        real = [c.get("real_pnl") or 0.0 for c in cs]
        rows.append({**s, "forward": {"trades": len(cs), "wins": sum(1 for x in real if x > 0),
                                      "real_net": round(sum(real), 2),
                                      "paper_net": round(sum(c.get("paper_pnl") or 0.0 for c in cs), 2),
                                      "open": any(p["strategy"] == s["key"] for p in open_docs)}})
    real_all = [t.get("real_pnl") or 0.0 for cs in closed.values() for t in cs]
    unreal_all = sum(r["unrealized_real"] or 0.0 for r in open_rows)
    sw = True
    try:
        from app.services import desk_switches
        sw = await desk_switches.is_on(SWITCH_KEY)
    except Exception:  # noqa: BLE001
        pass
    return {
        "engine": {**{k: v for k, v in status.items() if k != "daily_done"}, "switch_on": sw},
        "account": {"per_strategy_capital": CAPITAL_PER_STRATEGY, "strategies": len(strats),
                    "total_capital": CAPITAL_PER_STRATEGY * len(strats), "lots_per_trade": LOTS, "lot_size": 30},
        "totals": {"trades": len(real_all), "wins": sum(1 for x in real_all if x > 0), "real_net": round(sum(real_all), 2),
                   "paper_net": round(sum(t.get("paper_pnl") or 0.0 for cs in closed.values() for t in cs), 2),
                   "unrealized_real": round(unreal_all, 2), "open": len(open_rows)},
        "strategies": rows, "open": open_rows, "trades": trades, "research": research().get("meta", {}),
    }


def research_table() -> dict:
    r = research()
    return {"meta": r.get("meta", {}), "trials": r.get("trials", [])}
