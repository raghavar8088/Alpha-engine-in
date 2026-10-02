"""The v2 tournament engine: evaluate at bar closes, fill like a broker, exit where a stop
would really have triggered.

ON ITS OWN FAST TASK. The shared intraday loop ticks every 3 minutes; a stop checked every
3 minutes fills wherever the price happens to be when it is finally noticed. This loop
runs every few seconds in the session and reads the Angel stream's minute bars, so:

  STOPS AND TARGETS fill at their own level, found by walking the minute bars since the
  last check in order — the first level crossed wins, and when one minute crosses both,
  the STOP is assumed to have hit first (a minute bar cannot say which came first;
  assuming the target would manufacture edge). A minute that OPENS beyond a level fills
  at that open — a gap through a stop costs the gap.
  ENTRIES at a bar close fill at the live price seconds after the close; ORB stop-entries
  fill at their trigger the minute price crosses it (or at the open of a minute that gaps
  through it).
  SLIPPAGE is charged on every market fill (entries, stops, time and end-of-day exits) by
  the name's liquidity; targets are limit orders and pay none. Costs are Angel One's real
  intraday rate card, short-side STT included.

WHEN THE STREAM IS DOWN, exits fall back to live quotes (the old behaviour, labelled) and
the shared close-out job still squares everything off — a missing stream degrades
accuracy, never safety.

SLOTS, RANKED. Each strategy holds at most five positions at a time, each a fifth of its
Rs 10 lakh. When more signals arrive at one bar close than there are free slots, they are
taken in order of the rule's own priority (relative volume, or stretch size) — not in the
order the universe happens to be stored, which is how the first catalog ended up trading
the alphabet. At most two different strategies may hold one symbol at once.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (intraday_lab_positions_collection, intraday_lab_scores_collection,
                         intraday_lab_state_collection, intraday_lab_trades_collection)
from app.services import desk_switches, in_play, intraday_universe, market_calendar
from app.services import intraday_session as session
from app.services import intraday_v2_strategies as v2
from app.services.angel_fees import round_trip
from app.services.angel_stream import stream
from app.services.intraday_store import BASE_MIN, SESSION_OPEN_MIN, store
from app.services.promotion_gate import grade

logger = logging.getLogger("intraday_v2_engine")

IST = timezone(timedelta(hours=5, minutes=30))
PER_STRATEGY_CAPITAL = float(os.getenv("INTRADAY_LAB_PER_STRATEGY_CAPITAL", "1000000"))
SLOT_NOTIONAL = PER_STRATEGY_CAPITAL / v2.SLOTS_PER_STRATEGY
MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("INTRADAY_LAB_MAX_STRATEGIES_PER_SYMBOL", "2"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("INTRADAY_LAB_DAILY_LOSS_PCT", "0.03"))
PAUSE_NEW_ENTRIES = os.getenv("INTRADAY_LAB_PAUSE_ENTRIES", "1").lower() not in ("0", "false", "")
LOOP_SECONDS = float(os.getenv("INTRADAY_V2_LOOP_SECONDS", "3"))
EVAL_DELAY_S = 20            # after a 15m boundary: the stream emits at +5 s
MARK_EVERY_S = 30            # how often open positions' marks are written
SWITCH_KEY = "intraday_lab"
STATE_ID = "v2_engine"
PENDING_ID = "v2_pending"
TOTAL_CAPITAL = PER_STRATEGY_CAPITAL * len(v2.CATALOG)
# Bars handed to the rules: enough for EMA50 to settle and for 15 sessions of daily ATR
# (15m), no more — indicators are recomputed at every close, so window = cost.
WINDOW = {"15m": 420, "45m": 220, "1h": 220}


def slippage_bp(turnover_cr: float | None) -> float:
    """Per-side cost of crossing the spread for a ~Rs 2 lakh order, by liquidity. The
    universe is the 200 most-traded names, where ₹2 lakh is a sliver of a minute's
    volume, so this is mostly the half-spread. Same function for the Phase 3 backtest."""
    t = turnover_cr or 0.0
    if t >= 1000:
        return 1.0
    if t >= 300:
        return 2.0
    if t >= 150:
        return 3.0
    return 4.0


def _adverse(price: float, side: str, bp: float, opening: bool) -> float:
    """A market fill `bp` basis points worse than `price` for the trader."""
    buying = (side == "BUY") == opening
    return price * (1 + bp / 1e4) if buying else price * (1 - bp / 1e4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ist() -> datetime:
    return datetime.now(IST)


# ── state shared across one process ──────────────────────────────────────────────

_members: dict[str, dict] = {}
_last_eval_boundary = 0
_last_mark = 0.0
_last_state_write = 0.0
_lock = asyncio.Lock()
# Open positions and pending stop-entries, held in memory. This loop runs every few
# seconds and the cluster is Atlas M0, which stalls for seconds at a time; reading both
# from the database on every tick would make the exit checks only as fast as Atlas.
# Only this module writes v2 positions, so the cache is refreshed every 30 s as a guard
# and immediately after any open or close.
_open_cache: list[dict] = []
_open_cache_at = 0.0
_pending: list[dict] | None = None
_pending_day: str | None = None
status: dict = {"evaluations": 0, "signals": 0, "opened": 0, "closed": 0, "skipped": {},
                "last_eval": None, "last_notes": [], "exit_source": None}


def _skip(reason: str) -> None:
    status["skipped"][reason] = status["skipped"].get(reason, 0) + 1


async def _universe() -> dict[str, dict]:
    global _members
    members = await intraday_universe.members()
    _members = {m["symbol"]: m for m in members}
    return _members


# ── book keeping ─────────────────────────────────────────────────────────────────


async def _open_rows(fresh: bool = False) -> list[dict]:
    global _open_cache, _open_cache_at
    if fresh or time.monotonic() - _open_cache_at > 30:
        _open_cache = [p async for p in intraday_lab_positions_collection.find(
            {"status": "OPEN", "engine": "v2"})]
        _open_cache_at = time.monotonic()
    return list(_open_cache)


def _invalidate() -> None:
    global _open_cache_at
    _open_cache_at = 0.0


async def _today_pnl() -> float:
    start = datetime.combine(_ist().date(), datetime.min.time(), IST).astimezone(timezone.utc)
    total = 0.0
    async for p in intraday_lab_positions_collection.find(
            {"engine": "v2", "$or": [{"status": "OPEN"}, {"closed_at": {"$gte": start}}]},
            {"status": 1, "realized_pnl": 1, "unrealized_pnl": 1}):
        total += (p.get("realized_pnl") or 0.0) if p["status"] != "OPEN" else (p.get("unrealized_pnl") or 0.0)
    return total


async def _strategy_cash(strategy_id: str) -> float:
    realized = deployed = 0.0
    async for p in intraday_lab_positions_collection.find(
            {"strategy_id": strategy_id}, {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if p["status"] == "OPEN":
            deployed += p.get("capital_deployed") or 0.0
        else:
            realized += p.get("realized_pnl") or 0.0
    return PER_STRATEGY_CAPITAL + realized - deployed


async def update_score(strategy_id: str) -> None:
    spec = v2.BY_ID.get(strategy_id)
    if spec is None:
        return
    pnls = [float(p.get("realized_pnl") or 0.0) async for p in intraday_lab_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}).sort("closed_at", 1)]
    graded = grade(pnls, PER_STRATEGY_CAPITAL, len(v2.CATALOG))
    await intraday_lab_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "name": spec.name, "category": spec.category,
                  "family": spec.family, "timeframe": spec.tf, **graded,
                  "allocated_capital": round(PER_STRATEGY_CAPITAL + graded["net_pnl"], 2),
                  "updated_at": _now()}}, upsert=True)


# ── prices ───────────────────────────────────────────────────────────────────────


def _stream_ltp(symbol: str, max_age_s: float = 90) -> float | None:
    st = stream.states.get(symbol)
    if st is None or st.last_ltp is None or time.time() - st.last_tick > max_age_s:
        return None
    return st.last_ltp


async def _quote_ltps(symbols: list[str]) -> dict[str, float]:
    """Fallback marks from Angel's quote endpoint when the stream has nothing fresh."""
    from app.services.angel_client import angel_client
    toks = {(_members.get(s) or {}).get("token"): s for s in symbols if (_members.get(s) or {}).get("token")}
    if not toks:
        return {}
    try:
        res = await angel_client.ltp({"NSE": [t for t in toks if t]})
    except Exception:  # noqa: BLE001
        return {}
    return {toks[t]: float(px) for t, px in res.items() if t in toks and px}


def _minutes(symbol: str, since: int) -> list[tuple[int, float, float, float, float]]:
    """Stream minute bars (start, o, h, l, c) from `since` on, including the forming one."""
    st = stream.states.get(symbol)
    if st is None:
        return []
    out = [(st.mt[i], st.mo[i], st.mh[i], st.ml[i], st.mc[i]) for i in range(len(st.mt)) if st.mt[i] >= since]
    if st.cur is not None and st.cur[0] >= since:
        out.append(tuple(st.cur))
    return out


# ── entries ──────────────────────────────────────────────────────────────────────


async def _nifty_ret(at: datetime) -> float | None:
    s = store.series("NIFTY", "15m", n=40, now=at)
    day = at.date()
    today = [i for i in range(len(s)) if datetime.fromisoformat(s.ts[i]).date() == day]
    if not today:
        live = stream.day_stats("NIFTY")
        if live and live.get("open") and live.get("ltp"):
            return (live["ltp"] - live["open"]) / live["open"] * 100
        return None
    first, last = s.o[today[0]], s.c[today[-1]]
    return (last - first) / first * 100 if first else None


def _closed_tfs(boundary: datetime) -> list[str]:
    m = boundary.hour * 60 + boundary.minute - SESSION_OPEN_MIN
    out = ["15m"]
    if m % 45 == 0:
        out.append("45m")
    if m % 60 == 0:
        out.append("1h")
    return out


def _complete_through(symbol: str, boundary: datetime) -> bool:
    """Today's 15m bars present from 09:15 up to `boundary` — no holes. An aggregated bar
    built over a hole would have the wrong high, low and volume and look complete."""
    want = (boundary.hour * 60 + boundary.minute - SESSION_OPEN_MIN) // BASE_MIN
    b_ts = int(boundary.timestamp())
    open_ts = b_ts - want * BASE_MIN * 60                       # 09:15 that day
    return store.count_between(symbol, open_ts, b_ts - BASE_MIN * 60) >= want


async def evaluate_close(boundary: datetime, open_positions: bool = True) -> dict:
    """Evaluate every strategy whose bar closed at `boundary`; open the best signals."""
    members = await _universe()
    tfs = _closed_tfs(boundary)
    day_setup = boundary.strftime("%H:%M") == v2.ENTRY_FROM
    notes: list[str] = []
    ranked = await in_play.ranked(top=len(members), now=boundary + timedelta(seconds=1))
    rv = {r["symbol"]: (r["rvol_raw"], i + 1) for i, r in enumerate(ranked["top"])}
    nifty = await _nifty_ret(boundary + timedelta(seconds=1))
    if nifty is None:
        notes.append("NIFTY bars missing for today — trend strategies (which trade only with "
                     "the market's direction) cannot fire this bar.")
    cands: list[tuple[float, v2.V2Spec, str, v2.V2Signal]] = []
    incomplete = 0
    for sym, m in members.items():
        if not _complete_through(sym, boundary):
            incomplete += 1
            continue
        await asyncio.sleep(0)       # let the API breathe between symbols
        at = boundary + timedelta(seconds=1)
        s15 = store.series(sym, "15m", n=WINDOW["15m"], now=at)
        rvol, rank = rv.get(sym, (None, None))
        for tf in tfs + (["day"] if day_setup else []):
            s = s15 if tf in ("15m", "day") else store.series(sym, tf, n=WINDOW[tf], now=at)
            ctx = v2.build_ctx(sym, "15m" if tf == "day" else tf, boundary, s, s15, rvol, rank, nifty)
            if ctx is None:
                continue
            for spec in v2.CATALOG:
                if spec.tf != tf:
                    continue
                sig = v2.evaluate(spec, ctx)
                if sig is not None:
                    cands.append((sig.priority, spec, sym, sig))
    status["evaluations"] += 1
    status["signals"] += len(cands)
    if incomplete:
        notes.append(f"{incomplete} of {len(members)} names skipped: today's bars not complete "
                     "through this close (stream gap; the gap-fill will repair them).")
    opened = 0
    if open_positions and cands:
        cands.sort(key=lambda c: -c[0])
        opened = await _take(cands, boundary)
    status["last_eval"] = {"boundary": boundary.strftime("%H:%M"), "timeframes": tfs,
                           "day_setups": day_setup, "signals": len(cands), "opened": opened,
                           "incomplete": incomplete, "universe": len(members),
                           "nifty_ret_pct": round(nifty, 2) if nifty is not None else None}
    status["last_notes"] = notes
    return status["last_eval"]


async def _take(cands, boundary: datetime) -> int:
    """Open signals in priority order, inside every limit."""
    opened_rows = await _open_rows()
    per_strategy: dict[str, int] = {}
    per_symbol: dict[str, set] = {}
    held = set()
    for p in opened_rows:
        per_strategy[p["strategy_id"]] = per_strategy.get(p["strategy_id"], 0) + 1
        per_symbol.setdefault(p["symbol"], set()).add(p["strategy_id"])
        held.add((p["strategy_id"], p["symbol"]))
    pending = await _pending_today()
    opened = 0
    for _prio, spec, sym, sig in cands:
        if per_strategy.get(spec.strategy_id, 0) >= v2.SLOTS_PER_STRATEGY:
            _skip("strategy slots full"); continue
        if (spec.strategy_id, sym) in held:
            _skip("already holding"); continue
        if len(per_symbol.get(sym, set()) - {spec.strategy_id}) >= MAX_STRATEGIES_PER_SYMBOL:
            _skip("symbol crowded"); continue
        if sig.trigger is not None:
            if any(x["strategy_id"] == spec.strategy_id and x["symbol"] == sym for x in pending):
                continue
            pending.append({"strategy_id": spec.strategy_id, "symbol": sym, "side": sig.side,
                            "trigger": sig.trigger, "stop_dist": sig.stop_dist,
                            "target_dist": sig.target_dist, "priority": sig.priority,
                            "rationale": sig.rationale, "since": int(boundary.timestamp())})
            continue
        price = _stream_ltp(sym)
        source = "stream"
        if price is None:
            price = (await _quote_ltps([sym])).get(sym)
            source = "quote"
        if not price:
            _skip("no live price"); continue
        if await _open(spec, sym, sig, price, source, boundary):
            opened += 1
            per_strategy[spec.strategy_id] = per_strategy.get(spec.strategy_id, 0) + 1
            per_symbol.setdefault(sym, set()).add(spec.strategy_id)
            held.add((spec.strategy_id, sym))
    await _save_pending(pending)
    return opened


async def _open(spec: v2.V2Spec, sym: str, sig: v2.V2Signal, price: float, source: str,
                signal_at: datetime, fill_note: str = "market") -> bool:
    m = _members.get(sym) or {}
    bp = slippage_bp(m.get("turnover_cr"))
    fill = _adverse(price, sig.side, bp, opening=True)   # a triggered stop-entry is a market order too
    qty = int(SLOT_NOTIONAL // fill)
    if qty < 1:
        _skip("price above slot size"); return False
    if await _strategy_cash(spec.strategy_id) < qty * fill:
        _skip("strategy cash"); return False
    sign = 1 if sig.side == "BUY" else -1
    stop = fill - sign * sig.stop_dist
    if sig.target_price is not None:
        target = sig.target_price
        if sign * (target - fill) <= 0:          # the mean was already reached by the fill
            _skip("target already passed"); return False
    elif sig.target_dist:
        target = fill + sign * sig.target_dist
    else:
        target = None
    doc = {
        "position_id": uuid4().hex[:12], "engine": "v2",
        "strategy_id": spec.strategy_id, "strategy_name": spec.name, "category": spec.category,
        "family": spec.family, "timeframe": spec.tf,
        "symbol": sym, "display_name": sym,
        "instrument": {"symbol": sym, "security_id": m.get("security_id"),
                       "exchange_segment": m.get("exchange_segment"), "lot_size": 1},
        "side": sig.side, "entry_price": round(fill, 2), "signal_price": round(sig.entry, 2),
        "fill_basis": f"{fill_note} @ {price:.2f} ({source}) + {bp:g} bp slippage",
        "slippage_bp": bp, "qty": qty, "capital_deployed": round(fill * qty, 2),
        "target": round(target, 2) if target else None, "stoploss": round(stop, 2),
        "max_bars": sig.max_bars, "tf_seconds": v2.TF_SECONDS.get(spec.tf, 0),
        "ltp": round(price, 2), "ltp_source": source, "unrealized_pnl": 0.0, "pnl_pct": 0.0,
        "realized_pnl": None, "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": None, "rationale": sig.rationale, "max_hold_days": 0,
        "cas": bool(m.get("cas")), "turnover_cr": m.get("turnover_cr"),
        "signal_bar_close": signal_at.astimezone(timezone.utc),
        "checked_through": int(time.time()) // 60 * 60 + 60,   # exits scan from the next minute
        "opened_at": _now(), "opened_on": _ist().date().isoformat(), "updated_at": _now(),
        "closed_at": None,
    }
    await intraday_lab_positions_collection.insert_one(doc)
    _invalidate()
    status["opened"] += 1
    return True


# ── ORB stop-entries ─────────────────────────────────────────────────────────────


async def _pending_today() -> list[dict]:
    global _pending, _pending_day
    today = _ist().date().isoformat()
    if _pending is None or _pending_day != today:
        doc = await intraday_lab_state_collection.find_one({"_id": PENDING_ID}) or {}
        _pending = doc.get("items", []) if doc.get("date") == today else []
        _pending_day = today
    return list(_pending)


async def _save_pending(items: list[dict]) -> None:
    global _pending, _pending_day
    if _pending == items and _pending_day == _ist().date().isoformat():
        return
    _pending, _pending_day = list(items), _ist().date().isoformat()
    await intraday_lab_state_collection.update_one(
        {"_id": PENDING_ID}, {"$set": {"date": _pending_day, "items": items}}, upsert=True)


async def _fill_triggers() -> int:
    items = await _pending_today()
    if not items or not v2.in_entry_window(_ist()):
        return 0
    left, filled = [], 0
    rows = await _open_rows()
    per_strategy: dict[str, int] = {}
    per_symbol: dict[str, set] = {}
    for p in rows:
        per_strategy[p["strategy_id"]] = per_strategy.get(p["strategy_id"], 0) + 1
        per_symbol.setdefault(p["symbol"], set()).add(p["strategy_id"])
    for x in sorted(items, key=lambda r: -r["priority"]):
        hit = None
        for t, o, h, l, _c in _minutes(x["symbol"], x["since"]):
            if x["side"] == "BUY" and h >= x["trigger"]:
                hit = max(x["trigger"], o); break
            if x["side"] == "SELL" and l <= x["trigger"]:
                hit = min(x["trigger"], o); break
        if hit is None:
            left.append(x); continue
        spec = v2.BY_ID.get(x["strategy_id"])
        if spec is None:
            continue
        if per_strategy.get(spec.strategy_id, 0) >= v2.SLOTS_PER_STRATEGY or \
                len(per_symbol.get(x["symbol"], set()) - {spec.strategy_id}) >= MAX_STRATEGIES_PER_SYMBOL:
            _skip("trigger crossed but no slot"); continue
        sig = v2.V2Signal(x["side"], x["trigger"], x["stop_dist"], x.get("target_dist"), 0,
                          x["priority"], x["rationale"])
        if await _open(spec, x["symbol"], sig, hit, "stream", _ist(), fill_note="stop-entry"):
            filled += 1
            per_strategy[spec.strategy_id] = per_strategy.get(spec.strategy_id, 0) + 1
            per_symbol.setdefault(x["symbol"], set()).add(spec.strategy_id)
    await _save_pending(left)
    return filled


# ── exits ────────────────────────────────────────────────────────────────────────


def _scan_exit(p: dict) -> tuple[str, float, int] | None:
    """Walk the stream's minute bars since the last check: (reason, level price, minute)."""
    sign = 1 if p["side"] == "BUY" else -1
    stop, target = p["stoploss"], p.get("target")
    for t, o, h, l, _c in _minutes(p["symbol"], p.get("checked_through", 0)):
        lo, hi = (l, h) if sign > 0 else (-h, -l)
        s_lvl = sign * stop
        o_s = sign * o
        if o_s <= s_lvl:
            return "stoploss", o, t                      # opened through the stop
        if target is not None and o_s >= sign * target:
            return "target", o, t                        # opened through the target
        if lo <= s_lvl:
            return "stoploss", stop, t                   # stop first when both in one minute
        if target is not None and hi >= sign * target:
            return "target", target, t
    return None


async def _close(p: dict, price: float, reason: str, market: bool) -> None:
    bp = p.get("slippage_bp") or slippage_bp(p.get("turnover_cr"))
    fill = _adverse(price, p["side"], bp, opening=False) if market else price
    sign = 1 if p["side"] == "BUY" else -1
    gross = round(sign * (fill - p["entry_price"]) * p["qty"], 2)
    fb = round_trip(entry_price=p["entry_price"], exit_price=fill, qty=p["qty"], side=p["side"],
                    product="INTRADAY")
    net = round(gross - fb.total, 2)
    today = _ist().date().isoformat()
    await intraday_lab_positions_collection.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 2), "exit_reason": reason,
        "exit_basis": f"{'market' if market else 'level'} @ {price:.2f}" + (f" - {bp:g} bp" if market else ""),
        "gross_pnl": gross, "fees": fb.total, "fee_breakdown": fb.as_dict(), "realized_pnl": net,
        "unrealized_pnl": 0.0, "ltp": round(price, 2), "closed_at": _now(), "closed_on": today,
        "updated_at": _now()}})
    await intraday_lab_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "engine": "v2", "strategy_id": p["strategy_id"],
        "strategy_name": p["strategy_name"], "symbol": p["symbol"], "side": p["side"],
        "entry_price": p["entry_price"], "exit_price": round(fill, 2), "qty": p["qty"],
        "gross_pnl": gross, "fees": fb.total, "realized_pnl": net, "exit_reason": reason,
        "opened_at": p["opened_at"], "closed_at": _now()})
    _invalidate()
    status["closed"] += 1


async def manage(force_marks: bool = False) -> int:
    """Exits for every open v2 position. Safe to call often; serialised by a lock."""
    global _last_mark
    async with _lock:
        rows = await _open_rows()
        if not rows:
            return 0
        if not _members:
            await _universe()
        await session.ensure_cas()
        now = _ist()
        need_quote = [p["symbol"] for p in rows if _stream_ltp(p["symbol"]) is None]
        quotes = await _quote_ltps(need_quote) if need_quote else {}
        status["exit_source"] = "stream" if not need_quote else (
            "stream + quotes" if len(need_quote) < len(rows) else "quotes")
        touched, closed = set(), 0
        mark_due = force_marks or time.time() - _last_mark >= MARK_EVERY_S
        for p in rows:
            sym = p["symbol"]
            ltp = _stream_ltp(sym) or quotes.get(sym)
            hit = _scan_exit(p)
            if hit is None and ltp is not None:
                sign = 1 if p["side"] == "BUY" else -1
                if sign * (ltp - p["stoploss"]) <= 0:
                    hit = ("stoploss", ltp, None)           # quote fallback: a market exit
                elif p.get("target") is not None and sign * (ltp - p["target"]) >= 0:
                    hit = ("target", p["target"], None)
            if hit is not None:
                reason, px, _t = hit
                await _close(p, px, reason, market=(reason == "stoploss"))
                touched.add(p["strategy_id"]); closed += 1
                continue
            if ltp is None and session.squareoff_due(sym, now):
                # No live price at the close. A real MIS position would be squared off by the
                # broker whatever we knew, so the paper one closes too — at the last price we
                # have, labelled as such — rather than being carried overnight.
                st = stream.states.get(sym)
                last = (st.last_ltp if st is not None else None)
                if last is None:
                    srs = store.series(sym, "15m", n=1, now=now)
                    last = srs.c[-1] if len(srs) else None
                if last is not None:
                    await _close(p, last, "eod_last_known_price", market=True)
                    touched.add(p["strategy_id"]); closed += 1
                continue
            bars_held = int((_now() - p["opened_at"].replace(tzinfo=timezone.utc)).total_seconds()
                            // max(p.get("tf_seconds") or 1, 1)) if p.get("max_bars") else 0
            if ltp is not None and (session.squareoff_due(sym, now) or
                                    (p.get("max_bars") and bars_held >= p["max_bars"])):
                await _close(p, ltp, "eod" if session.squareoff_due(sym, now) else "time", market=True)
                touched.add(p["strategy_id"]); closed += 1
                continue
            if ltp is not None and mark_due:
                sign = 1 if p["side"] == "BUY" else -1
                await intraday_lab_positions_collection.update_one({"_id": p["_id"], "status": "OPEN"}, {"$set": {
                    "ltp": round(ltp, 2), "ltp_source": "stream" if _stream_ltp(sym) else "quote",
                    "unrealized_pnl": round(sign * (ltp - p["entry_price"]) * p["qty"], 2),
                    "pnl_pct": round(sign * (ltp - p["entry_price"]) / p["entry_price"] * 100, 2),
                    "checked_through": int(time.time()) // 60 * 60, "updated_at": _now()}})
        if mark_due:
            _last_mark = time.time()
        for sid in touched:
            await update_score(sid)
        return closed


# ── the loop ─────────────────────────────────────────────────────────────────────


async def _entries_allowed() -> tuple[bool, str]:
    if PAUSE_NEW_ENTRIES:
        return False, "INTRADAY_LAB_PAUSE_ENTRIES is set — no new positions"
    if not await desk_switches.is_on(SWITCH_KEY):
        return False, "switched off in Main Control — open positions are still managed"
    if await _today_pnl() <= -DAILY_LOSS_BREAKER_PCT * TOTAL_CAPITAL:
        return False, f"daily loss breaker ({DAILY_LOSS_BREAKER_PCT:.0%} of capital) tripped"
    return True, ""


async def tick() -> None:
    global _last_eval_boundary, _last_state_write
    now = _ist()
    if not market_calendar.is_trading_day(now):
        return
    m = now.hour * 60 + now.minute
    if not (SESSION_OPEN_MIN <= m <= 15 * 60 + 40):
        return
    await manage()
    if await _pending_today() and v2.in_entry_window(now):
        ok, _why = await _entries_allowed()
        if ok:
            await _fill_triggers()
    k = (m - SESSION_OPEN_MIN) // BASE_MIN
    boundary = now.replace(hour=0, minute=0, second=0, microsecond=0) + \
        timedelta(minutes=SESSION_OPEN_MIN + k * BASE_MIN)
    b_ts = int(boundary.timestamp())
    if k >= 1 and b_ts > _last_eval_boundary and (now - boundary).total_seconds() >= EVAL_DELAY_S:
        _last_eval_boundary = b_ts
        if v2.in_entry_window(boundary):
            ok, why = await _entries_allowed()
            if ok:
                r = await evaluate_close(boundary)
                logger.info("v2 %s: %s", boundary.strftime("%H:%M"), r)
            else:
                status["last_notes"] = [why]
    if time.monotonic() - _last_state_write > 30:
        _last_state_write = time.monotonic()
        await intraday_lab_state_collection.update_one(
            {"_id": STATE_ID}, {"$set": {"last_tick": _now(), "status": status}}, upsert=True)


async def v2_loop() -> None:
    logger.info("intraday v2 engine: %d strategies, %d slots x Rs %.0f each, entries %s-%s",
                len(v2.CATALOG), v2.SLOTS_PER_STRATEGY, SLOT_NOTIONAL, v2.ENTRY_FROM, v2.ENTRY_UNTIL)
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001
            logger.exception("v2 tick failed — retrying")
        await asyncio.sleep(LOOP_SECONDS)


def describe() -> dict:
    return {"strategies": len(v2.CATALOG), "slots_per_strategy": v2.SLOTS_PER_STRATEGY,
            "slot_notional": SLOT_NOTIONAL, "paused": PAUSE_NEW_ENTRIES, **status}
