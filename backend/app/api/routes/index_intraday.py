"""Indian Index Intraday Trading — research, backtesting lab and paper trading (never real orders).

  GET  /api/index-intraday/overview          live index values, VIX, session and feed status, ETF liquidity
  GET  /api/index-intraday/research          the research headline (trials, luck bar, periods, verdict)
  GET  /api/index-intraday/families          per family: variants tested, how far they got, the best
  GET  /api/index-intraday/strategies        the catalogue (?index=&family=&status=&min_trades=&stage=&sort=&limit=)
  GET  /api/index-intraday/strategies/{sid}  one strategy with its monthly curve
  GET  /api/index-intraday/deployments       what the paper engine runs
  POST /api/index-intraday/deployments       {"sid", "enabled", "model": "etf"|"index"}
  GET  /api/index-intraday/terminal          account, open positions, today's trades, engine notes, risk state
  GET  /api/index-intraday/journal           closed trades (?sid=&day=&limit=)
  GET  /api/index-intraday/equity            equity snapshots
  GET  /api/index-intraday/events            entries, exits, refusals, misses, switches
  GET  /api/index-intraday/report            the daily report (?day=YYYY-MM-DD)
  GET  /api/index-intraday/risk              the risk configuration and today's state
  POST /api/index-intraday/risk              update the configuration (validated)
  POST /api/index-intraday/risk/emergency    {"on": bool} — on flattens everything and blocks entries
  POST /api/index-intraday/risk/reset-halt   clear a drawdown halt
  POST /api/index-intraday/backtest          {"sid"} or {"family","params","exit","index"} + {"start","end",
                                             "cost_scale", "cost_basis": "measured"|"research"}
  POST /api/index-intraday/run               one engine tick now
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.index_intraday import backtest as BT
from app.services.index_intraday import catalog as cat
from app.services.index_intraday import paper as P
from app.services.index_intraday import report as REP
from app.services.index_intraday.costs import MINUTE_VALUE_LAKH, ROUTE, fee_rt_bp, max_etf_order
from app.services.index_intraday.feed import INSTRUMENTS, LABELS, feed

router = APIRouter(prefix="/api/index-intraday", tags=["index-intraday"])
IST = timezone(timedelta(hours=5, minutes=30))


def _iso(x):
    return x.isoformat() if isinstance(x, datetime) else x


def _clean(doc: dict) -> dict:
    doc.pop("_id", None)
    return {k: _iso(v) for k, v in doc.items()}


@router.get("/overview")
async def overview(_u: dict = Depends(get_current_user)):
    from app.services import market_calendar
    now = datetime.now(IST)
    rows = []
    for sym, (exch, tok, kind, tracks) in INSTRUMENTS.items():
        f = feed.day_fields(sym)
        ltp, pc = f.get("ltp"), f.get("prev_close")
        row = {"symbol": sym, "label": LABELS.get(sym, sym), "exchange": exch, "kind": kind, "tracks": tracks,
               "ltp": ltp, "prev_close": pc, "open": f.get("open"), "high": f.get("high"), "low": f.get("low"),
               "change_pct": round((ltp / pc - 1) * 100, 2) if ltp and pc else None,
               "ticked_s_ago": f.get("ticked_s_ago")}
        if kind == "index":
            etf, px, slip = ROUTE[sym]
            row.update({"etf": etf, "slip_bp": slip, "fee_rt_bp": round(fee_rt_bp(px), 2),
                        "all_in_rt_bp": round(fee_rt_bp(px) + 2 * slip, 2),
                        "etf_minute_value_lakh": MINUTE_VALUE_LAKH.get(etf) if etf else None,
                        "etf_order_cap": round(max_etf_order(etf)) if etf else 0,
                        "tradable": bool(etf) and (MINUTE_VALUE_LAKH.get(etf, 0) >= 2.0)})
        rows.append(row)
    hhmm = now.strftime("%H:%M")
    trading = market_calendar.is_trading_day(now)
    session = ("closed (holiday / weekend)" if not trading else "pre-open" if hhmm < "09:15" else
               "open" if hhmm < "15:30" else "closed")
    return {"at": now.isoformat(), "session": session, "instruments": rows, "feed": feed.describe(),
            "entry_window": "09:20-14:30 (14:45 for the last-half-hour family)", "square_off": "15:12"}


@router.get("/research")
async def research(_u: dict = Depends(get_current_user)):
    return {**cat.header(), "statuses": list(cat.STATUSES),
            "verdict": ("No strategy reached Validated, so none is Paper Trading Approved. The holdout (2024-01 .. "
                        "2026-10) was never opened. Strategies can still be run in paper as OBSERVATION, "
                        "labelled with their status.")}


@router.get("/families")
async def families(_u: dict = Depends(get_current_user)):
    return {"families": cat.families()}


@router.get("/strategies")
async def strategies(index: str | None = None, family: str | None = None, status: str | None = None,
                     min_trades: int = Query(0, ge=0), sort: str = "sv_sharpe", limit: int = Query(200, ge=1, le=1500),
                     stage: int | None = Query(None, ge=1, le=2), _u: dict = Depends(get_current_user)):
    rows = cat.strategies(index, family, status, min_trades, sort, 5000, stage=stage)
    return {"strategies": rows[:limit], "matched": len(rows)}


@router.get("/strategies/{sid}")
async def strategy(sid: str, _u: dict = Depends(get_current_user)):
    s = cat.get(sid)
    if s is None:
        raise HTTPException(404, f"no strategy {sid}")
    return s


@router.get("/deployments")
async def get_deployments(_u: dict = Depends(get_current_user)):
    return {"deployments": await P.deployments()}


@router.post("/deployments")
async def post_deployment(payload: dict = Body(...), _u: dict = Depends(get_current_user)):
    try:
        items = await P.set_deployment(str(payload.get("sid")), bool(payload.get("enabled")), payload.get("model") or "etf")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deployments": items}


@router.get("/terminal")
async def terminal(_u: dict = Depends(get_current_user)):
    cfg = await P.get_config()
    acct = await P.account(cfg)
    today = datetime.now(IST).date()
    st = await P.get_day(today, acct["equity"])
    open_pos = [_clean(p) async for p in P.POS.find({"status": "OPEN"}).sort("opened_at", -1)]
    trades = [_clean(t) async for t in P.TRADES.find({"day": today.isoformat()}).sort("closed_at", -1)]
    eng = await P.STATE.find_one({"_id": "engine"}) or {}
    return {"account": acct, "risk": cfg.as_dict(), "day": st.__dict__, "open_positions": open_pos,
            "today_trades": trades, "deployments": await P.deployments(),
            "engine": {"last_tick": _iso(eng.get("last_tick")), "notes": eng.get("notes", []),
                       "last_opened": eng.get("last_opened", 0), "last_closed": eng.get("last_closed", 0)}}


@router.get("/journal")
async def journal(sid: str | None = None, day: str | None = None, limit: int = Query(300, ge=1, le=3000),
                  _u: dict = Depends(get_current_user)):
    q = {}
    if sid:
        q["sid"] = sid
    if day:
        q["day"] = day
    return {"trades": [_clean(t) async for t in P.TRADES.find(q).sort("closed_at", -1).limit(limit)]}


@router.get("/equity")
async def equity(limit: int = Query(2000, ge=1, le=20000), _u: dict = Depends(get_current_user)):
    rows = [_clean(r) async for r in P.EQUITY.find({}).sort("at", -1).limit(limit)]
    return {"equity": list(reversed(rows))}


@router.get("/events")
async def events(limit: int = Query(200, ge=1, le=2000), _u: dict = Depends(get_current_user)):
    return {"events": [_clean(e) async for e in P.EVENTS.find({}).sort("at", -1).limit(limit)]}


@router.get("/report")
async def report(day: str | None = None, _u: dict = Depends(get_current_user)):
    d = date.fromisoformat(day) if day else datetime.now(IST).date()
    return await REP.get(d)


@router.get("/risk")
async def get_risk(_u: dict = Depends(get_current_user)):
    cfg = await P.get_config()
    acct = await P.account(cfg)
    st = await P.get_day(datetime.now(IST).date(), acct["equity"])
    return {"config": cfg.as_dict(), "day": st.__dict__, "account": acct}


@router.post("/risk")
async def post_risk(payload: dict = Body(...), _u: dict = Depends(get_current_user)):
    cfg, problems = await P.set_config(payload)
    if problems:
        raise HTTPException(422, "; ".join(problems))
    await P.event("risk", f"risk settings changed: {payload}")
    return {"config": cfg.as_dict()}


@router.post("/risk/emergency")
async def emergency(payload: dict = Body(...), _u: dict = Depends(get_current_user)):
    on = bool(payload.get("on"))
    cfg, _ = await P.set_config({"emergency_stop": on})
    out = {"emergency_stop": on}
    if on:
        out.update(await P.engine.flatten_all("emergency_stop"))
    await P.event("risk", f"EMERGENCY STOP {'ON — everything flattened' if on else 'OFF'}")
    return out


@router.post("/risk/reset-halt")
async def reset_halt(_u: dict = Depends(get_current_user)):
    acct = await P.account()
    st = await P.get_day(datetime.now(IST).date(), acct["equity"])
    st.halted, st.peak_equity = False, acct["equity"]
    await P.save_day(st)
    await P.event("risk", "drawdown halt cleared; peak reset to current equity")
    return {"day": st.__dict__}


@router.post("/backtest")
async def backtest(payload: dict = Body(...), _u: dict = Depends(get_current_user)):
    try:
        return await BT.run(payload.get("sid"), payload.get("family"), payload.get("params"), payload.get("exit"),
                            payload.get("index"), payload.get("start"), payload.get("end"),
                            float(payload.get("cost_scale") or 1.0), payload.get("cost_basis") or "measured")
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/run")
async def run_now(_u: dict = Depends(get_current_user)):
    from app.services.desk_switches import is_on
    return await P.engine.tick(entries_allowed=await is_on("index_intraday"))
