"""Operations for the intraday desks: alarms, and a daily edge report.

ALARMS (checked every minute; each kind is raised once per session and RESOLVES ITSELF
when its condition clears, so the list shows what is wrong now, not what was once wrong)
  stream_down             in session, the Angel stream is disconnected or silent > 2 min
  v2_engine_stalled       in session, the v2 engine has not ticked for > 2 min
  universe_incomplete     > 20% of the universe skipped at the last bar close (bar holes)
  memory_high             backend resident memory >= 88% of its cap, or swapping > 50 MB
  angel_throttled         > 40% of candle calls refused over the last 10 minutes
  stream_bars_inaccurate  the last reconcile found live bars' closes > 10 bp off Angel's (p95)
  history_incomplete      before the open, < 90% of the universe has stored bar history
  calendar_expiring       the NSE holiday list ends within 30 days
  squareoff_missed        (raised by intraday_session's close-out job)
  market_closed_unlisted  (raised by market_calendar's self-check)

THE EDGE REPORT (after the close) answers, per v2 strategy and for the desk: what did
the day make before costs, what did slippage and fees take, and how does the forward
record compare with what the backtest said to expect? That last comparison is the live
check on the backtest's fill model: if forward trades keep coming in well below the
backtest's per-trade mean across many strategies, the simulator is flattering itself.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.core.db import db, intraday_lab_positions_collection
from app.services import market_calendar

logger = logging.getLogger("intraday_ops")

IST = timezone(timedelta(hours=5, minutes=30))
alarms = db["system_alarms"]
reports = db["intraday_edge_reports"]
V2_LAUNCH = datetime(2026, 10, 5, tzinfo=IST)

_pacer_prev: list[tuple[float, int, int]] = []      # (monotonic, calls, refused) samples


async def _set(kind: str, active: bool, detail: dict | None = None) -> None:
    today = datetime.now(IST).date().isoformat()
    _id = f"{kind}:{today}"
    now = datetime.now(timezone.utc)
    try:
        if active:
            await alarms.update_one({"_id": _id}, {
                "$set": {"kind": kind, "session": today, "detail": detail or {}, "last_at": now,
                         "resolved": False, "active": True},
                "$setOnInsert": {"first_at": now}, "$inc": {"count": 1}}, upsert=True)
        else:
            await alarms.update_one({"_id": _id, "active": True},
                                    {"$set": {"active": False, "resolved": True, "resolved_at": now}})
    except Exception:  # noqa: BLE001 - monitoring must never break anything
        logger.exception("alarm write failed: %s", kind)


async def check_once() -> dict:
    """Evaluate every alarm condition once."""
    now = datetime.now(IST)
    hhmm = now.strftime("%H:%M")
    trading = market_calendar.is_trading_day(now)
    in_session = trading and "09:20" <= hhmm <= "15:28"
    state: dict[str, bool] = {}

    from app.services.angel_stream import ENABLED as STREAM_ON, stream
    sd = stream.describe()
    down = in_session and STREAM_ON and (not sd["connected"] or (sd["seconds_since_message"] or 1e9) > 120)
    state["stream_down"] = down
    await _set("stream_down", down, {"connected": sd["connected"], "last_error": sd["last_error"],
                                     "seconds_since_message": sd["seconds_since_message"]})

    try:
        st = await db["intraday_lab_state"].find_one({"_id": "v2_engine"}) or {}
        last = st.get("last_tick")
        if isinstance(last, datetime) and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        stalled = in_session and (not isinstance(last, datetime)
                                  or (datetime.now(timezone.utc) - last).total_seconds() > 120)
        state["v2_engine_stalled"] = stalled
        await _set("v2_engine_stalled", stalled, {"last_tick": last.isoformat() if isinstance(last, datetime) else None})
        le = (st.get("status") or {}).get("last_eval") or {}
        inc, uni = le.get("incomplete"), le.get("universe")
        bad = bool(in_session and inc is not None and uni and inc / uni > 0.20)
        state["universe_incomplete"] = bad
        await _set("universe_incomplete", bad, {"skipped": inc, "universe": uni, "at": le.get("boundary")})
    except Exception:  # noqa: BLE001
        logger.exception("v2 state check failed")

    from app.api.routes.diagnostics import _proc_memory
    mem = _proc_memory()
    hot = (mem.get("used_pct") or 0) >= 88 or (mem.get("VmSwap") or 0) > 50
    state["memory_high"] = hot
    await _set("memory_high", hot, {k: mem.get(k) for k in ("VmRSS", "VmSwap", "limit_mb", "used_pct")})

    from app.services.angel_client import candle_pacer
    mono = time.monotonic()
    _pacer_prev.append((mono, candle_pacer.stats["calls"], candle_pacer.stats["refused"]))
    while _pacer_prev and mono - _pacer_prev[0][0] > 600:
        _pacer_prev.pop(0)
    d_calls = _pacer_prev[-1][1] - _pacer_prev[0][1]
    d_ref = _pacer_prev[-1][2] - _pacer_prev[0][2]
    thr = d_calls >= 30 and d_ref / d_calls > 0.40
    state["angel_throttled"] = thr
    await _set("angel_throttled", thr, {"calls_10m": d_calls, "refused_10m": d_ref})

    from app.services.intraday_backfill import last_reconcile
    rec = await last_reconcile() or {}
    p95 = (rec.get("close_bp") or {}).get("p95")
    drift = bool(rec.get("bars_compared", 0) >= 100 and p95 is not None and p95 > 10)
    state["stream_bars_inaccurate"] = drift
    await _set("stream_bars_inaccurate", drift, {"date": rec.get("date"), "close_bp": rec.get("close_bp"),
                                                 "volume_pct": rec.get("volume_pct")})

    if trading and "08:45" <= hhmm < "09:15":
        from app.services import intraday_universe
        from app.services.intraday_store import store
        syms = await intraday_universe.symbols()
        cov = store.coverage(syms) if syms else {"with_history": 0, "symbols": 0}
        short = bool(cov["symbols"] and cov["with_history"] / cov["symbols"] < 0.90)
        state["history_incomplete"] = short
        await _set("history_incomplete", short, cov)

    cal = market_calendar.describe(now)
    ends = date.fromisoformat(cal["list_covers_through"])
    expiring = (ends - now.date()).days <= 30
    state["calendar_expiring"] = expiring
    await _set("calendar_expiring", expiring, {"list_covers_through": cal["list_covers_through"],
                                               "action": "add next year's NSE holiday circular to "
                                                         "market_calendar.NSE_HOLIDAYS"})
    return state


async def monitor_loop() -> None:
    while True:
        try:
            await check_once()
        except Exception:  # noqa: BLE001
            logger.exception("ops monitor tick failed")
        await asyncio.sleep(60)


async def open_alarms(days: int = 7) -> list[dict]:
    since = (datetime.now(IST).date() - timedelta(days=days)).isoformat()
    out = []
    async for a in alarms.find({"session": {"$gte": since}}).sort("session", -1):
        a["id"] = a.pop("_id")
        for k in ("first_at", "last_at", "resolved_at", "at"):
            if isinstance(a.get(k), datetime):
                a[k] = a[k].isoformat()
        a.setdefault("active", not a.get("resolved", False))
        out.append(a)
    return out


# ── the daily edge report ────────────────────────────────────────────────────────


async def _backtest_expectation() -> dict[str, float]:
    bt = db["intraday_v2_backtests"]
    latest = await bt.find_one({"_id": "latest"})
    if not latest:
        return {}
    doc = await bt.find_one({"_id": f"v2bt:{latest['run_id']}:strategies"}) or {}
    return {r["strategy_id"]: (r.get("full") or {}).get("expectancy") for r in doc.get("results", [])}


async def build_edge_report(day: date | None = None) -> dict:
    day = day or datetime.now(IST).date()
    iso = day.isoformat()
    per: dict[str, dict] = defaultdict(lambda: {"trades": 0, "gross": 0.0, "fees": 0.0, "net": 0.0,
                                                "slippage": 0.0, "wins": 0, "reasons": defaultdict(int)})
    async for p in intraday_lab_positions_collection.find(
            {"engine": "v2", "status": "CLOSED", "closed_on": iso},
            {"strategy_id": 1, "strategy_name": 1, "gross_pnl": 1, "fees": 1, "realized_pnl": 1,
             "slippage_bp": 1, "capital_deployed": 1, "exit_reason": 1}):
        r = per[p["strategy_id"]]
        r["name"] = p.get("strategy_name")
        r["trades"] += 1
        r["gross"] += p.get("gross_pnl") or 0.0
        r["fees"] += p.get("fees") or 0.0
        r["net"] += p.get("realized_pnl") or 0.0
        r["wins"] += 1 if (p.get("realized_pnl") or 0) > 0 else 0
        # entry always pays it; exits pay it unless they were a target (limit) fill
        legs = 1 + (0 if p.get("exit_reason") == "target" else 1)
        r["slippage"] += (p.get("slippage_bp") or 0) / 1e4 * (p.get("capital_deployed") or 0) * legs
        r["reasons"][p.get("exit_reason") or "?"] += 1
    expected = await _backtest_expectation()
    # forward since launch, per strategy, against the backtest's per-trade mean
    fwd: dict[str, list[float]] = defaultdict(list)
    async for p in intraday_lab_positions_collection.find(
            {"engine": "v2", "status": "CLOSED", "closed_at": {"$gte": V2_LAUNCH.astimezone(timezone.utc)}},
            {"strategy_id": 1, "realized_pnl": 1}):
        fwd[p["strategy_id"]].append(float(p.get("realized_pnl") or 0.0))
    calib = []
    for sid, nets in fwd.items():
        e = expected.get(sid)
        if e is None or len(nets) < 5:
            continue
        calib.append({"strategy_id": sid, "trades": len(nets), "forward_mean": round(sum(nets) / len(nets), 2),
                      "backtest_mean": e, "gap": round(sum(nets) / len(nets) - e, 2)})
    gaps = [c["gap"] for c in calib]
    rec = await db["intraday_data_state"].find_one({"_id": f"reconcile:{iso}"}) or {}
    rows = []
    for sid, r in per.items():
        rows.append({"strategy_id": sid, "name": r.get("name"), "trades": r["trades"],
                     "gross_pnl": round(r["gross"], 2), "fees": round(r["fees"], 2),
                     "slippage_est": round(r["slippage"], 2), "net_pnl": round(r["net"], 2),
                     "win_rate": round(r["wins"] / r["trades"], 3) if r["trades"] else 0.0,
                     "exit_reasons": dict(r["reasons"]), "backtest_per_trade": expected.get(sid)})
    rows.sort(key=lambda x: -x["net_pnl"])
    tot = {k: round(sum(x[k] for x in rows), 2) for k in ("gross_pnl", "fees", "slippage_est", "net_pnl")}
    tot["trades"] = sum(x["trades"] for x in rows)
    st = await db["intraday_lab_state"].find_one({"_id": "v2_engine"}) or {}
    report = {
        "_id": iso, "date": iso, "built_at": datetime.now(timezone.utc), "desk": tot,
        "strategies": rows,
        "calibration": {
            "strategies_compared": len(calib),
            "median_gap_per_trade": round(statistics.median(gaps), 2) if gaps else None,
            "share_below_backtest": round(sum(1 for g in gaps if g < 0) / len(gaps), 3) if gaps else None,
            "rows": sorted(calib, key=lambda c: c["gap"])[:20],
            "reading": "forward per-trade net minus the backtest's, since the v2 launch. Consistently "
                       "negative across many strategies means the backtest's fill model is optimistic.",
        },
        "stream_quality": {k: rec.get(k) for k in ("bars_compared", "close_bp", "high_bp", "low_bp",
                                                   "volume_pct", "exact_close_share")} if rec else None,
        "engine": {k: (st.get("status") or {}).get(k) for k in ("evaluations", "signals", "opened",
                                                                "closed", "skipped", "exit_source")},
        "alarms": [a for a in await open_alarms(1) if a.get("session") == iso],
    }
    await reports.replace_one({"_id": iso}, report, upsert=True)
    report.pop("_id", None)
    return report
