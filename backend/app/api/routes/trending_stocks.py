"""Trending Stocks API — a LONG-ONLY desk over the basket the user names.

  GET    /api/trending-stocks/summary                  desk totals, gate config, breakers
  GET    /api/trending-stocks/basket                   the basket + bar coverage + live quote
  POST   /api/trending-stocks/basket                   add one symbol (queues its backfill)
  POST   /api/trending-stocks/basket/bulk              replace the whole basket
  DELETE /api/trending-stocks/basket/{symbol}          stop new entries (open trades still managed)
  POST   /api/trending-stocks/basket/{symbol}/release  clear a quarantine
  GET    /api/trending-stocks/basket/search            instrument autocomplete
  POST   /api/trending-stocks/basket/backfill          force a full bar backfill (background)
  GET    /api/trending-stocks/coverage                 symbol x timeframe bar coverage grid
  GET    /api/trending-stocks/research/{symbol}        the seven research pillars, live
  GET    /api/trending-stocks/library                  the 678 strategies, filterable
  GET    /api/trending-stocks/recipes                  the 86 hypotheses behind them
  GET    /api/trending-stocks/strategy/{id}            rules, backtest, walk-forward, Monte Carlo
  GET    /api/trending-stocks/signals                  the alert stream
  GET    /api/trending-stocks/positions                open + closed, each with its reason
  GET    /api/trending-stocks/trades                   closed blotter, net of costs
  GET    /api/trending-stocks/rejections               why NO TRADE, grouped by stage
  GET    /api/trending-stocks/equity                   desk equity curve
  POST   /api/trending-stocks/backtest                 run the sweep (background)
  POST   /api/trending-stocks/validate                 walk-forward + Monte Carlo (background)
  POST   /api/trending-stocks/run                      one scan+manage cycle, on demand
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import (
    ts_equity_collection,
    ts_evidence_collection,
    ts_positions_collection,
    ts_signals_collection,
    ts_trades_collection,
    ts_validation_collection,
)
from app.schemas.trending import (
    AddSymbolRequest, SetBasketRequest, SweepRequest, ValidateRequest,
)
from app.services.trending_stocks import basket as ts_basket
from app.services.trending_stocks import bars as ts_bars
from app.services.trending_stocks import evidence as ts_evidence
from app.services.trending_stocks.catalog import (
    ALL_RECIPES, LONG_BY_ID, LONG_CATALOG, TIMEFRAMES, family_counts, style_counts,
)
from app.services.trending_stocks.engine import (
    leaderboard as ts_leaderboard, rejection_summary, run_backtests, run_paper_cycle,
    run_validation, summary as ts_summary,
)
from app.services.trending_stocks.feasibility import MIN_RR
from app.services.trending_stocks.recipes import SHORT_ONLY_KEYS

logger = logging.getLogger("trending_stocks.api")

router = APIRouter(prefix="/api/trending-stocks", tags=["trending-stocks"])

# Background tasks are held in a module-level set so the event loop keeps a strong
# reference to them; a task referenced only by a local can be garbage-collected mid-run.
_BACKGROUND: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


def _ser(doc: dict, ts=()) -> dict:
    doc.pop("_id", None)
    for k in ts:
        v = doc.get(k)
        if v is not None and not isinstance(v, str):
            try:
                doc[k] = v.isoformat()
            except AttributeError:
                doc[k] = str(v)
    return doc


POSITION_TS = ("opened_at", "updated_at", "closed_at", "entry_bar_ts")


# --------------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------------


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await ts_summary()


# --------------------------------------------------------------------------------
# Basket
# --------------------------------------------------------------------------------


@router.get("/basket/search")
async def search_endpoint(q: str = Query(..., min_length=1),
                          _u: dict = Depends(get_current_user)):
    return {"results": await ts_basket.search(q)}


@router.get("/basket")
async def basket_endpoint(include_removed: bool = Query(False),
                          _u: dict = Depends(get_current_user)):
    rows = await ts_basket.list_basket(include_removed=include_removed)
    active = [r["symbol"] for r in rows if r.get("status") == ts_basket.STATUS_ACTIVE]
    cov = await ts_bars.coverage([r["symbol"] for r in rows]) if rows else {}
    open_counts: dict[str, int] = {}
    async for p in ts_positions_collection.find({"status": "OPEN"}, {"symbol": 1}):
        open_counts[p["symbol"]] = open_counts.get(p["symbol"], 0) + 1
    for r in rows:
        r["coverage"] = cov.get(r["symbol"], {})
        r["open_positions"] = open_counts.get(r["symbol"], 0)
    return {"basket": rows, "active": active, "timeframes": ts_bars.TIMEFRAMES,
            "benchmark": ts_bars.BENCHMARK_SYMBOL,
            "native_timeframes": sorted(ts_bars.NATIVE),
            "derived_timeframes": ts_bars.DERIVED_FROM}


@router.post("/basket")
async def add_symbol(payload: AddSymbolRequest, _u: dict = Depends(get_current_user)):
    res = await ts_basket.add(payload.symbol, payload.note)
    if res.get("ok"):
        _spawn(_backfill_one(payload.symbol))
        res["note"] = ("Backfilling 1m/5m/15m/1h/1d from Angel in the background — the "
                       "candle endpoint is paced at 3s a request, so coverage fills in "
                       "over the next few minutes.")
    return res


@router.post("/basket/bulk")
async def set_basket(payload: SetBasketRequest, _u: dict = Depends(get_current_user)):
    symbols = payload.resolved()
    if not symbols:
        return {"error": "no symbols given"}
    res = await ts_basket.set_all(symbols)
    _spawn(_backfill_all())
    return res


@router.delete("/basket/{symbol}")
async def remove_symbol(symbol: str, _u: dict = Depends(get_current_user)):
    return await ts_basket.remove(symbol)


@router.post("/basket/{symbol}/release")
async def release_quarantine(symbol: str, _u: dict = Depends(get_current_user)):
    return await ts_basket.unquarantine(symbol)


@router.post("/basket/backfill")
async def force_backfill(full: bool = Query(True), _u: dict = Depends(get_current_user)):
    _spawn(_backfill_all(full=full))
    return {"started": True, "full": full,
            "note": "Paced at one candle request every 3 seconds. Watch /coverage."}


async def _backfill_one(symbol: str) -> None:
    try:
        inst = await ts_bars.resolve_instrument(symbol)
        if inst is None:
            return
        written = await ts_bars.refresh_symbol(symbol, inst, full=True)
        await ts_basket.mark_backfilled(symbol, written)
    except Exception:  # noqa: BLE001
        logger.exception("[trending_stocks] backfill failed for %s", symbol)


async def _backfill_all(full: bool = True) -> None:
    try:
        universe = await ts_basket.active()
        result = await ts_bars.refresh_many(universe, full=full)
        for sym, written in (result.get("symbols") or {}).items():
            await ts_basket.mark_backfilled(sym, written)
    except Exception:  # noqa: BLE001
        logger.exception("[trending_stocks] basket backfill failed")


@router.get("/coverage")
async def coverage_endpoint(_u: dict = Depends(get_current_user)):
    universe = await ts_basket.active()
    syms = sorted(universe) + [ts_bars.BENCHMARK_SYMBOL]
    return {"coverage": await ts_bars.coverage(syms),
            "timeframes": ts_bars.TIMEFRAMES,
            "derived": ts_bars.DERIVED_FROM,
            "note": "Derived timeframes (30m/45m/4h) report their parent's coverage — "
                    "that is what actually limits them. Angel serves no 45m or 4h, so "
                    "those are resampled on the NSE 09:15 anchor."}


# --------------------------------------------------------------------------------
# Research
# --------------------------------------------------------------------------------


@router.get("/research/{symbol}")
async def research_endpoint(symbol: str, timeframe: str = Query("1d"),
                            _u: dict = Depends(get_current_user)):
    """All seven pillars for one symbol, computed live.

    This is the same code the entry gate runs, minus the pattern pillar — that one needs a
    signal to describe, and this endpoint is asked about a symbol rather than a trade."""
    sym = symbol.upper()
    universe = await ts_basket.active()
    inst = universe.get(sym) or await ts_bars.resolve_instrument(sym)
    if inst is None:
        return {"error": f"{sym} is not a tradable instrument on file"}

    tf = timeframe if timeframe in ts_bars.TIMEFRAMES else "1d"
    series = await ts_bars.load_bars(sym, tf, 600)
    daily = await ts_bars.load_bars(sym, "1d", 400)
    bench_daily = await ts_bars.load_benchmark("1d", 400)

    ltp = None
    try:
        from app.services.trending_stocks.engine import live_quotes
        ltp = (await live_quotes({sym: inst})).get(sym)
    except Exception:  # noqa: BLE001
        ltp = None
    ok, note = await ts_bars.quote_sanity(sym, ltp)

    pillars = [
        ts_evidence.volume_pillar(series) if series else None,
        ts_evidence.momentum_pillar(daily, bench_daily),
        await ts_evidence.news_pillar(sym, inst.get("name")),
        ts_evidence.price_action_pillar(series, daily) if series else None,
        ts_evidence.regime_pillar(series, bench_daily) if series else None,
        ts_evidence.liquidity_pillar(daily, ltp, ok, note, "angel_quote"),
    ]
    live = [p.as_doc() for p in pillars if p is not None]
    return {
        "symbol": sym, "name": inst.get("name"), "timeframe": tf, "ltp": ltp,
        "quote_ok": ok, "quote_note": note,
        "pillars": live,
        "supports": sum(1 for p in live if p["verdict"] == ts_evidence.SUPPORTS),
        "vetoes": [p["sentence"] for p in live if p["verdict"] == ts_evidence.VETO],
        "min_pillars": ts_evidence.MIN_PILLARS,
        "bars_loaded": len(series), "daily_bars": len(daily),
        "note": "The pattern pillar is absent here because it describes a specific "
                "signal, not a symbol. It is filled in when a strategy actually fires.",
    }


# --------------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------------


@router.get("/library")
async def library_endpoint(
    family: str | None = Query(None, description="chart|candlestick|structure|indicator|hybrid"),
    timeframe: str | None = Query(None),
    style: str | None = Query(None, description="scalp|intraday|swing|positional"),
    grade: int | None = Query(None, ge=0, le=5),
    status: str | None = Query(None),
    limit: int = Query(700, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    rows = await ts_leaderboard(family=family, timeframe=timeframe, grade=grade,
                               style=style, status=status, limit=limit)
    return {"library": rows, "total": len(rows), "timeframes": TIMEFRAMES,
            "families": family_counts(), "styles": style_counts(),
            "strategy_count": len(LONG_CATALOG), "direction": "LONG ONLY",
            "min_rr": MIN_RR}


@router.get("/recipes")
async def recipes_endpoint(_u: dict = Depends(get_current_user)):
    """The hypotheses, not the instantiations — 86 distinct ideas, each run on 8 charts."""
    return {
        "recipes": [{
            "key": r.key, "name": r.name, "family": r.family, "sub_family": r.sub_family,
            "hypothesis": r.hypothesis, "detector": r.detector, "target_r": r.target_r,
            "regimes": sorted(r.regimes) or ["any"],
            "confirmations": [n for n, _ in r.confirmations],
            "intraday_only": r.intraday_only, "uses_htf": r.uses_htf,
            "new_here": r.key.startswith("ts_"),
        } for r in ALL_RECIPES],
        "count": len(ALL_RECIPES),
        "excluded": [{"key": k, "why": why} for k, why in SHORT_ONLY_KEYS.items()],
        "note": "Two of the Strategy Factory's 69 recipes are structurally short-only and "
                "are excluded rather than kept as strategies that can never fire.",
    }


@router.get("/strategy/{strategy_id}")
async def strategy_detail(strategy_id: str, _u: dict = Depends(get_current_user)):
    s = LONG_BY_ID.get(strategy_id)
    if s is None:
        return {"error": "unknown strategy_id"}
    from app.core.db import ts_backtests_collection
    backtests = [_ser(d, ("updated_at", "validated_at")) async for d in
                 ts_backtests_collection.find({"strategy_id": strategy_id}).sort("grade", -1)]
    validation = [_ser(d, ("updated_at",)) async for d in
                  ts_validation_collection.find({"strategy_id": strategy_id})]
    positions = [_ser(d, POSITION_TS) async for d in
                 ts_positions_collection.find({"strategy_id": strategy_id})
                 .sort("opened_at", -1).limit(50)]
    trades = [_ser(d, ("opened_at", "closed_at")) async for d in
              ts_trades_collection.find({"strategy_id": strategy_id})
              .sort("closed_at", -1).limit(100)]
    return {
        "strategy": {
            "strategy_id": s.strategy_id, "name": s.name, "family": s.family,
            "sub_family": s.sub_family, "hypothesis": s.hypothesis,
            "detector": s.detector, "timeframe": s.timeframe, "htf": s.htf,
            "style": s.style, "target_r": s.target_r, "min_rr": MIN_RR,
            "direction": "LONG", "regimes": sorted(s.regimes),
            "confirmations": [{"name": n, "params": p} for n, p in s.confirmations],
            "params": {k: v for k, v in s.params.items() if not k.startswith("_")},
            "min_bars": s.min_bars, "fingerprint": s.fingerprint,
        },
        "backtests": backtests, "validation": validation,
        "positions": positions, "trades": trades,
    }


# --------------------------------------------------------------------------------
# Book
# --------------------------------------------------------------------------------


@router.get("/positions")
async def positions_endpoint(
    status: str | None = Query(None), symbol: str | None = Query(None),
    strategy_id: str | None = Query(None), limit: int = Query(300, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    q: dict = {}
    if status:
        q["status"] = status.upper()
    if symbol:
        q["symbol"] = symbol.upper()
    if strategy_id:
        q["strategy_id"] = strategy_id
    rows = [_ser(d, POSITION_TS) async for d in
            ts_positions_collection.find(q).sort("opened_at", -1).limit(limit)]
    return {"positions": rows,
            "open": [r for r in rows if r.get("status") == "OPEN"],
            "closed": [r for r in rows if r.get("status") != "OPEN"]}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(300, ge=1, le=1000),
                          _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ("opened_at", "closed_at")) async for d in
            ts_trades_collection.find({}).sort("closed_at", -1).limit(limit)]
    return {"trades": rows}


@router.get("/signals")
async def signals_endpoint(limit: int = Query(200, ge=1, le=500),
                           _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ("created_at",)) async for d in
            ts_signals_collection.find({}).sort("created_at", -1).limit(limit)]
    return {"signals": rows, "min_rr": MIN_RR}


@router.get("/evidence/{position_id}")
async def evidence_endpoint(position_id: str, _u: dict = Depends(get_current_user)):
    doc = await ts_evidence_collection.find_one({"position_id": position_id})
    if doc is None:
        return {"error": "no evidence stored for that position"}
    return _ser(doc, ("created_at",))


@router.get("/rejections")
async def rejections_endpoint(cycles: int = Query(20, ge=1, le=100),
                              _u: dict = Depends(get_current_user)):
    return await rejection_summary(limit=cycles)


@router.get("/equity")
async def equity_endpoint(limit: int = Query(600, ge=1, le=2000),
                          _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ("ts",)) async for d in
            ts_equity_collection.find({}).sort("ts", -1).limit(limit)]
    rows.reverse()
    return {"equity": rows}


# --------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------


@router.post("/backtest")
async def backtest_endpoint(payload: SweepRequest | None = None,
                            _u: dict = Depends(get_current_user)):
    body = payload or SweepRequest()
    _spawn(run_backtests(symbols=body.symbols, strategy_ids=body.strategy_ids,
                         redo_after_hours=body.redo_after_hours))
    return {"started": True, "strategies": len(LONG_CATALOG),
            "note": "Resumable: rows already refreshed inside the redo window are "
                    "skipped, so a restart continues the sweep. Watch /summary."}


@router.post("/validate")
async def validate_endpoint(payload: ValidateRequest | None = None,
                            _u: dict = Depends(get_current_user)):
    body = payload or ValidateRequest()
    _spawn(run_validation(limit=body.limit, min_base_grade=body.min_base_grade))
    return {"started": True,
            "note": "Walk-forward + Monte Carlo on strategies already graded "
                    f"{body.min_base_grade}+. Grade 3 is the paper floor and needs no "
                    "further evidence; 4 and 5 are the claims worth stress-testing."}


@router.post("/run")
async def run_endpoint(_u: dict = Depends(get_current_user)):
    return await run_paper_cycle()
