"""Trending Stocks desk — ₹10,00,000 paper per strategy, long only, on the user's basket.

WHAT THIS DESK IS AND IS NOT
-----------------------------
It is a gate with a research layer bolted to the front of it. 678 long-only strategies get
their own ₹10L paper account, but a strategy firing is not enough to open a position: the
signal must clear the 1:6 feasibility test (`feasibility.py`) AND at least five of seven
independent research pillars must support it with no veto (`evidence.py`). The sentences
those pillars produce are stored on the position, so every open trade can say why it was
taken in words a person can argue with.

FIVE DESIGN CHOICES THAT COME FROM THIS APP'S OWN LOSSES
---------------------------------------------------------
1. **Real Indian transaction costs on every paper fill**, charged by holding style —
   intraday rates for scalp/intraday strategies, delivery rates (STT both sides, roughly
   4x the drag) for swing and positional ones. The Intraday Lab charged zero costs and its
   paper P&L turned out to be evidence of nothing; when the same catalog met a fee-honest
   backtest, 16 of 16 measurable strategies lost.

2. **A hard cap on how many strategies may hold one symbol.** The options buying desk lost
   29% in a day because six near-identical strategies bought the same strike at once. This
   desk is MORE exposed to that than any other in the app, because 678 strategies are
   pointed at a basket of perhaps fifteen names — crowding is the default, not the
   accident.

3. **A market-regime veto that lives in the evidence layer, not in a config flag.** New
   longs are withheld while the index is below its 200-day average or index volatility is
   in its top quartile. Open positions keep being managed either way; a desk that stopped
   managing its book would leave real risk untracked, which is worse.

4. **Paper trading is earned.** Only strategies graded 3 or better on their own backtest
   may open a position. An ungraded strategy is held back rather than let loose.

5. **Rejections are counted, not discarded.** "No trades today" and "forty setups all
   failed the 1:6 reachability test" look identical from the outside and mean completely
   different things.

FILLS AND QUOTES
----------------
Live Angel One quotes, with a stale/deviant-quote guard: the strategies gate on BAR
statistics but fill at the LIVE price, so those two must describe the same instrument. A
symbol whose quote disagrees with its own last close by more than 20% is quarantined
rather than traded — an unadjusted split reads as spectacular momentum.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from anyio import to_thread
from pymongo import UpdateOne

from app.core.db import (
    ts_backtests_collection,
    ts_basket_collection,
    ts_equity_collection,
    ts_evidence_collection,
    ts_positions_collection,
    ts_rejections_collection,
    ts_scores_collection,
    ts_signals_collection,
    ts_state_collection,
    ts_trades_collection,
    ts_validation_collection,
)
from app.services.stock_options import batched_ltp
from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD
from app.services.strategy_factory.primitives import (
    Levels, position_size, round_trip_cost, slippage_price,
)

from . import basket, bars as bar_store, evidence as ev
from .catalog import (
    LONG_BY_ID, LONG_CATALOG, bars_needed, family_counts, needs_benchmark, style_counts,
)
from .feasibility import FAILED_RR_LABEL, MIN_RR
from .signals import evaluate_long
from .validation import (
    GRADE_FAILED_RR, extended_grade, monte_carlo, run_backtest, walk_forward,
)

logger = logging.getLogger("trending_stocks")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "trending_stocks"

# ── capital ──────────────────────────────────────────────────────────────────────
# ₹10,00,000 per strategy, exactly as briefed, in an INDEPENDENT virtual account. With
# 678 strategies that is a ₹678 crore notional book — stated on the summary tile rather
# than hidden, because it is the arithmetic consequence of the brief and not a typo.
PER_STRATEGY_CAPITAL = float(os.getenv("TS_PER_STRATEGY_CAPITAL", "1000000"))
INITIAL_CAPITAL = PER_STRATEGY_CAPITAL * max(len(LONG_CATALOG), 1)
RISK_PCT = float(os.getenv("TS_RISK_PCT", "0.01"))              # 1% of the strategy's own capital

MAX_POSITIONS_PER_STRATEGY = int(os.getenv("TS_MAX_POSITIONS", "1"))
MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("TS_MAX_PER_SYMBOL", "8"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("TS_MAX_CONSEC_LOSSES", "6"))
SLIPPAGE_BPS = float(os.getenv("TS_SLIPPAGE_BPS", "5"))

# ── breakers ─────────────────────────────────────────────────────────────────────
DAILY_LOSS_PCT = float(os.getenv("TS_DAILY_LOSS_PCT", "0.02"))
WEEKLY_LOSS_PCT = float(os.getenv("TS_WEEKLY_LOSS_PCT", "0.05"))
MAX_DRAWDOWN_PCT = float(os.getenv("TS_MAX_DRAWDOWN_PCT", "0.15"))

# ── session ──────────────────────────────────────────────────────────────────────
ENTRY_CUTOFF_HHMM = os.getenv("TS_ENTRY_CUTOFF", "15:00")
EOD_SQUAREOFF_HHMM = os.getenv("TS_SQUAREOFF", "15:15")
PAUSE_NEW_ENTRIES = os.getenv("TS_PAUSE_ENTRIES", "0").lower() not in ("0", "false", "")

# ── gating ───────────────────────────────────────────────────────────────────────
MIN_GRADE_TO_TRADE = int(os.getenv("TS_MIN_GRADE", "3"))
REQUIRE_GRADE = os.getenv("TS_REQUIRE_GRADE", "1").lower() not in ("0", "false", "")
SCORE_REFRESH_EVERY = int(os.getenv("TS_SCORE_REFRESH_EVERY", "300"))

# Detailed rejection rows kept per cycle. 678 strategies x 15 symbols is ~10,000
# rejections a tick; storing them all would be the highest-churn write in the app and
# would tell you nothing you cannot get from the counts. So: every rejection is COUNTED,
# and a bounded sample of the interesting ones (the 1:6 failures, which name a blocking
# level) is kept in full.
REJECTION_SAMPLE = int(os.getenv("TS_REJECTION_SAMPLE", "40"))

# Holding style -> NSE cost model. A swing strategy pays STT on both sides; an intraday
# one does not. Charging one rate for both would flatter whichever is wrong.
STYLE_COST_MODEL = {"scalp": "equity_intraday", "intraday": "equity_intraday",
                    "swing": "equity_delivery", "positional": "equity_delivery"}
INTRADAY_STYLES = {"scalp", "intraday"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cost_model_for(strategy) -> str:
    return STYLE_COST_MODEL.get(strategy.style, "equity_delivery")


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


# --------------------------------------------------------------------------------
# Indexes
# --------------------------------------------------------------------------------


async def ensure_indexes() -> None:
    """Indexes the sweep, the resume check and every summary depend on.

    Each index is created in its OWN try block, not one shared one. Seen in the first
    production boot: `main.py`'s generic `ensure_desk_indexes()` had already created the
    same `updated_at` key under Mongo's auto-generated name, so creating it again under a
    chosen name raised IndexOptionsConflict — and because every creation shared a single
    try, that one conflict silently skipped the EIGHT indexes after it, including the
    unique key on `ts_scores`. A collection whose indexes depend on the one before it
    succeeding is a collection that will be missing indexes.

    `updated_at` is deliberately absent below: `main.py` owns that one. Two places
    creating the same key under different names is what caused the conflict."""
    specs = [
        (ts_backtests_collection, [("strategy_id", 1), ("symbol", 1)], "ts_bt_key", True),
        (ts_backtests_collection, [("grade", -1)], "ts_bt_grade", False),
        (ts_scores_collection, [("strategy_id", 1)], "ts_scores_key", True),
        (ts_positions_collection, [("status", 1)], "ts_pos_status", False),
        (ts_positions_collection, [("strategy_id", 1), ("status", 1)], "ts_pos_strategy", False),
        (ts_positions_collection, [("symbol", 1), ("status", 1)], "ts_pos_symbol", False),
        (ts_trades_collection, [("closed_at", -1)], "ts_trades_closed", False),
        (ts_signals_collection, [("created_at", -1)], "ts_signals_recent", False),
        (ts_evidence_collection, [("symbol", 1), ("created_at", -1)], "ts_evidence_key", False),
        (ts_rejections_collection, [("created_at", -1)], "ts_rej_recent", False),
        (ts_validation_collection, [("strategy_id", 1), ("symbol", 1)], "ts_val_key", True),
        (ts_basket_collection, [("status", 1)], "ts_basket_status", False),
    ]
    made = skipped = 0
    for coll, keys, name, unique in specs:
        try:
            await coll.create_index(keys, name=name, unique=unique, background=True)
            made += 1
        except Exception as exc:  # noqa: BLE001 — one conflict must not skip the rest
            skipped += 1
            logger.warning("[trending_stocks] index %s skipped: %s", name, exc)
    logger.info("[trending_stocks] indexes ensured (%d created/present, %d skipped)",
                made, skipped)


# --------------------------------------------------------------------------------
# Bar / quote helpers
# --------------------------------------------------------------------------------


class _Cycle:
    """Per-cycle memo for bars, quotes and the symbol-level evidence pillars.

    678 strategies share only 8 timeframes and 7 pillars, most of which depend on the
    symbol rather than the strategy. Recomputing them per strategy would be roughly a
    hundred times the database work and a hundred times the news lookups for identical
    answers."""

    def __init__(self):
        self.bars: dict[tuple[str, str], list] = {}
        self.daily: dict[str, list] = {}
        self.bench: dict[str, list] = {}
        self.quotes: dict[str, float] = {}
        self.quote_ok: dict[str, tuple[bool, str]] = {}
        self.sym_pillars: dict[str, list] = {}
        self.tf_pillars: dict[tuple[str, str], list] = {}

    async def get_bars(self, symbol: str, timeframe: str, limit: int) -> list:
        key = (symbol, timeframe)
        cached = self.bars.get(key)
        if cached is None or len(cached) < limit:
            self.bars[key] = await bar_store.load_bars(symbol, timeframe, limit)
        return self.bars[key]

    async def get_daily(self, symbol: str) -> list:
        if symbol not in self.daily:
            self.daily[symbol] = await bar_store.load_bars(symbol, "1d", 400)
        return self.daily[symbol]

    async def get_bench(self, timeframe: str) -> list:
        if timeframe not in self.bench:
            self.bench[timeframe] = await bar_store.load_benchmark(timeframe, 400)
        return self.bench[timeframe]


async def live_quotes(instruments: dict[str, dict]) -> dict[str, float]:
    """Live LTP per symbol from Angel, batched and paced. A symbol Angel cannot price is
    simply absent — the caller then treats it as unquotable rather than inventing a
    price from the last close."""
    by_exchange: dict[str, list[str]] = {}
    token_to_symbol: dict[str, str] = {}
    for sym, inst in instruments.items():
        token = str(inst.get("angel_token") or "")
        if not token:
            continue
        by_exchange.setdefault(inst.get("angel_exchange") or "NSE", []).append(token)
        token_to_symbol[token] = sym
    if not by_exchange:
        return {}
    try:
        raw = await batched_ltp(by_exchange)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[trending_stocks] quote fetch failed: %s", exc)
        return {}
    return {token_to_symbol[t]: p for t, p in raw.items() if t in token_to_symbol}


# --------------------------------------------------------------------------------
# Backtesting
# --------------------------------------------------------------------------------


def _metrics_doc(m) -> dict:
    return {k: getattr(m, k) for k in (
        "trades", "wins", "win_rate", "net_pnl", "gross_profit", "gross_loss",
        "total_costs", "profit_factor", "expectancy", "avg_r", "max_drawdown_pct",
        "return_pct", "cagr_pct", "sharpe", "sortino", "largest_win", "largest_loss",
        "max_consecutive_wins", "max_consecutive_losses", "exposure_pct")}


async def run_backtests(symbols: list[str] | None = None,
                        strategy_ids: list[str] | None = None,
                        redo_after_hours: float = 20.0) -> dict:
    """Replay every strategy over every basket symbol and persist one row each.

    Stored per (strategy, symbol), never averaged: "works on TITAN, fails on VEDL" is the
    actionable answer, and blending unrelated instruments destroys it.

    RESUMABLE. A full sweep is 678 x basket replays and hours long, so a restart — a
    deploy, a container recycle — used to throw the work away and begin again, meaning it
    never reached the end. Rows refreshed within `redo_after_hours` are skipped."""
    universe = await basket.active()
    names = [s for s in (symbols or sorted(universe)) if s in universe]
    if not names:
        return {"error": "the basket is empty — add the stocks this desk should trade"}

    strategies = ([LONG_BY_ID[i] for i in strategy_ids if i in LONG_BY_ID]
                  if strategy_ids else LONG_CATALOG)

    done: set[tuple[str, str]] = set()
    if redo_after_hours > 0:
        cutoff = _now() - timedelta(hours=redo_after_hours)
        async for d in ts_backtests_collection.find(
                {"updated_at": {"$gte": cutoff}}, {"strategy_id": 1, "symbol": 1}):
            done.add((d["strategy_id"], d["symbol"]))

    cache: dict[tuple[str, str], list] = {}

    async def bars_for(sym: str, tf: str) -> list:
        key = (sym, tf)
        if key not in cache:
            cache[key] = await bar_store.load_bars(sym, tf, 3000)
        return cache[key]

    async def bench_for(tf: str) -> list:
        key = ("__BENCH__", tf)
        if key not in cache:
            cache[key] = await bar_store.load_benchmark(tf, 3000)
        return cache[key]

    written = skipped = resumed = failed_rr = 0
    graded: dict[int, int] = {}
    rejection_totals: dict[str, int] = {}

    for sym in names:
        for strat in strategies:
            if (strat.strategy_id, sym) in done:
                resumed += 1
                continue
            series = await bars_for(sym, strat.timeframe)
            if len(series) < strat.min_bars + 30:
                skipped += 1
                continue
            htf = await bars_for(sym, strat.htf) if strat.htf else None
            bench = await bench_for(strat.timeframe) if needs_benchmark(strat) else None
            cm = cost_model_for(strat)

            # Off the event loop: one replay is seconds of pure CPU and this loop runs
            # thousands of them. Left inline it stalls every other desk's scheduler tick
            # and every HTTP request, for hours.
            res = await to_thread.run_sync(
                lambda st=strat, b=series, sy=sym, h=htf, bn=bench, c=cm: run_backtest(
                    st, b, sy, bench=bn, cost_model=c, capital=PER_STRATEGY_CAPITAL,
                    slippage_bps=SLIPPAGE_BPS, risk_pct=RISK_PCT, htf_bars=h))

            for stage, n in (res.rejections or {}).items():
                rejection_totals[stage] = rejection_totals.get(stage, 0) + n

            feasible = res.overall.trades
            grade, reasons, status = extended_grade(
                res.grade, res.grade_reasons, None, None, PER_STRATEGY_CAPITAL, feasible)
            if grade == GRADE_FAILED_RR:
                failed_rr += 1
            graded[grade] = graded.get(grade, 0) + 1

            await ts_backtests_collection.update_one(
                {"strategy_id": strat.strategy_id, "symbol": sym},
                {"$set": {
                    "strategy_id": strat.strategy_id, "name": strat.name,
                    "family": strat.family, "sub_family": strat.sub_family,
                    "timeframe": strat.timeframe, "htf": strat.htf, "style": strat.style,
                    "hypothesis": strat.hypothesis, "detector": strat.detector,
                    "target_r": strat.target_r, "regimes": sorted(strat.regimes),
                    "symbol": sym, "exchange": "NSE", "cost_model": cm,
                    "min_rr": MIN_RR, "direction": "LONG",
                    "bars_tested": res.bars_tested, "span_days": res.span_days,
                    "overall": _metrics_doc(res.overall),
                    "in_sample": _metrics_doc(res.in_sample),
                    "out_of_sample": _metrics_doc(res.out_of_sample),
                    "base_grade": res.grade, "grade": grade, "grade_reasons": reasons,
                    "status": status, "feasible_trades": feasible,
                    "rejections": res.rejections,
                    "equity_curve": [round(v, 2) for v in res.equity_curve[-400:]],
                    "walk_forward": None, "monte_carlo": None,
                    "updated_at": _now(),
                }}, upsert=True)
            written += 1
            if written % SCORE_REFRESH_EVERY == 0:
                await _refresh_scores()

    await _refresh_scores()
    await ts_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_backtest_at": _now(), "backtests_written": written,
        "backtests_skipped": skipped, "grade_histogram": graded,
        "failed_rr": failed_rr, "rejection_totals": rejection_totals,
    }}, upsert=True)
    return {"written": written, "skipped_thin_history": skipped, "already_done": resumed,
            "symbols": len(names), "strategies": len(strategies),
            "grade_histogram": graded, "failed_1_6_rr": failed_rr,
            "rejection_totals": rejection_totals, "min_rr": MIN_RR}


async def run_validation(limit: int = 400, min_base_grade: int = 4) -> dict:
    """Walk-forward + Monte Carlo, on survivors only.

    Deliberately not run on everything: five extra replays for 678 strategies x every
    symbol would multiply an already-long sweep by five, most of it spent re-proving that
    strategies already graded 1 or 2 do not work. Grade 3 is the paper floor and needs no
    more evidence than it already has; grades 4 and 5 are the claims worth stress-testing,
    because those are the ones that would otherwise be promoted on one lucky history."""
    universe = await basket.active()
    if not universe:
        return {"error": "the basket is empty"}

    rows = [d async for d in ts_backtests_collection.find(
        {"base_grade": {"$gte": min_base_grade}}).sort("base_grade", -1).limit(limit)]
    if not rows:
        return {"validated": 0,
                "note": f"no strategy is graded {min_base_grade}+ yet — run the backtest "
                        "sweep first"}

    cache: dict[tuple[str, str], list] = {}

    async def bars_for(sym: str, tf: str) -> list:
        key = (sym, tf)
        if key not in cache:
            cache[key] = await bar_store.load_bars(sym, tf, 3000)
        return cache[key]

    validated = promoted = demoted = 0
    for row in rows:
        strat = LONG_BY_ID.get(row["strategy_id"])
        sym = row.get("symbol")
        if strat is None or sym not in universe:
            continue
        series = await bars_for(sym, strat.timeframe)
        if len(series) < strat.min_bars + 60:
            continue
        htf = await bars_for(sym, strat.htf) if strat.htf else None
        bench = await bars_for(bar_store.BENCHMARK_SYMBOL, strat.timeframe) \
            if needs_benchmark(strat) else None
        cm = cost_model_for(strat)

        wf = await to_thread.run_sync(
            lambda st=strat, b=series, sy=sym, h=htf, bn=bench, c=cm: walk_forward(
                st, b, sy, bench=bn, cost_model=c, capital=PER_STRATEGY_CAPITAL,
                slippage_bps=SLIPPAGE_BPS, htf_bars=h))
        full = await to_thread.run_sync(
            lambda st=strat, b=series, sy=sym, h=htf, bn=bench, c=cm: run_backtest(
                st, b, sy, bench=bn, cost_model=c, capital=PER_STRATEGY_CAPITAL,
                slippage_bps=SLIPPAGE_BPS, risk_pct=RISK_PCT, htf_bars=h))
        mc = monte_carlo(full.trades, PER_STRATEGY_CAPITAL,
                         seed_key=f"{strat.strategy_id}:{sym}")

        grade, reasons, status = extended_grade(
            full.grade, full.grade_reasons, wf, mc, PER_STRATEGY_CAPITAL,
            full.overall.trades)
        before = row.get("grade", 0)
        promoted += 1 if grade > before else 0
        demoted += 1 if grade < before else 0

        await ts_backtests_collection.update_one(
            {"strategy_id": strat.strategy_id, "symbol": sym},
            {"$set": {"grade": grade, "grade_reasons": reasons, "status": status,
                      "walk_forward": wf.as_doc(), "monte_carlo": mc.as_doc(),
                      "validated_at": _now()}})
        await ts_validation_collection.update_one(
            {"strategy_id": strat.strategy_id, "symbol": sym},
            {"$set": {"strategy_id": strat.strategy_id, "symbol": sym,
                      "name": strat.name, "timeframe": strat.timeframe,
                      "walk_forward": wf.as_doc(), "monte_carlo": mc.as_doc(),
                      "grade": grade, "status": status, "updated_at": _now()}},
            upsert=True)
        validated += 1

    await _refresh_scores()
    await ts_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_validation_at": _now(), "validated": validated}}, upsert=True)
    return {"validated": validated, "promoted": promoted, "demoted": demoted,
            "candidates": len(rows)}


async def _refresh_scores() -> None:
    """Roll per-(strategy, symbol) backtests into one row per strategy.

    Done SERVER-SIDE. Streaming every backtest document to the client and picking the best
    in Python is what made the factory's leaderboard time out once the sweep passed a few
    thousand rows — each document carries an equity curve. The pipeline projects the heavy
    fields away first, then sorts and groups inside Mongo.

    A strategy's grade is its BEST grade on any symbol, and the row records which symbol
    earned it. "Works on TITAN, fails on VEDL" is the answer this library exists to give,
    and an average across the basket destroys it."""
    light = {"strategy_id": 1, "name": 1, "family": 1, "sub_family": 1, "timeframe": 1,
             "style": 1, "hypothesis": 1, "symbol": 1, "grade": 1, "base_grade": 1,
             "status": 1, "grade_reasons": 1, "overall": 1, "out_of_sample": 1,
             "walk_forward": 1, "monte_carlo": 1, "feasible_trades": 1}
    pipeline = [
        {"$project": light},
        {"$sort": {"grade": -1, "overall.net_pnl": -1}},
        {"$group": {"_id": "$strategy_id", "doc": {"$first": "$$ROOT"}}},
    ]
    ops: list[UpdateOne] = []
    async for row in ts_backtests_collection.aggregate(pipeline, allowDiskUse=True):
        d = row["doc"]
        o = d.get("overall") or {}
        oos = d.get("out_of_sample") or {}
        wf = d.get("walk_forward") or {}
        mc = d.get("monte_carlo") or {}
        ops.append(UpdateOne({"strategy_id": d["strategy_id"]}, {"$set": {
            "strategy_id": d["strategy_id"], "name": d.get("name"),
            "family": d.get("family"), "sub_family": d.get("sub_family"),
            "timeframe": d.get("timeframe"), "style": d.get("style"),
            "hypothesis": d.get("hypothesis"), "best_symbol": d.get("symbol"),
            "grade": d.get("grade", 0), "base_grade": d.get("base_grade", 0),
            "status": d.get("status"), "grade_reasons": d.get("grade_reasons", []),
            "bt_trades": o.get("trades", 0), "bt_win_rate": o.get("win_rate", 0.0),
            "bt_profit_factor": o.get("profit_factor"),
            "bt_expectancy": o.get("expectancy", 0.0), "bt_avg_r": o.get("avg_r", 0.0),
            "bt_net_pnl": o.get("net_pnl", 0.0), "bt_costs": o.get("total_costs", 0.0),
            "bt_max_dd_pct": o.get("max_drawdown_pct", 0.0),
            "bt_cagr_pct": o.get("cagr_pct"), "bt_sharpe": o.get("sharpe"),
            "bt_sortino": o.get("sortino"),
            "oos_net_pnl": oos.get("net_pnl", 0.0), "oos_trades": oos.get("trades", 0),
            "wf_fraction": wf.get("fraction"), "wf_windows": wf.get("windows"),
            "mc_p5_final": mc.get("p5_final"), "mc_prob_ruin": mc.get("prob_of_ruin"),
            "feasible_trades": d.get("feasible_trades", 0),
            "updated_at": _now(),
        }}, upsert=True))
        if len(ops) >= 300:
            await ts_scores_collection.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        await ts_scores_collection.bulk_write(ops, ordered=False)


# --------------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------------


async def _tradable_ids() -> set[str]:
    if not REQUIRE_GRADE:
        return {s.strategy_id for s in LONG_CATALOG}
    out: set[str] = set()
    async for d in ts_scores_collection.find({"grade": {"$gte": MIN_GRADE_TO_TRADE}},
                                             {"strategy_id": 1}):
        out.add(d["strategy_id"])
    return out


async def _cash(sid: str) -> float:
    realized = deployed = 0.0
    async for p in ts_positions_collection.find(
            {"strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    async for p in ts_positions_collection.find(
            {"strategy_id": sid, "status": "OPEN"}, {"capital_deployed": 1}):
        deployed += p.get("capital_deployed", 0.0)
    return PER_STRATEGY_CAPITAL + realized - deployed


async def _consecutive_losses(sid: str) -> int:
    """How many closed trades in a row this strategy has lost, most recent first."""
    run = 0
    async for t in ts_trades_collection.find(
            {"strategy_id": sid}, {"realized_pnl": 1}).sort("closed_at", -1).limit(
            MAX_CONSECUTIVE_LOSSES + 1):
        if (t.get("realized_pnl") or 0.0) < 0:
            run += 1
        else:
            break
    return run


async def _pnl_since(start: datetime) -> float:
    total = 0.0
    async for p in ts_positions_collection.find(
            {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    async for p in ts_positions_collection.find(
            {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    """Daily, weekly and drawdown breakers, evaluated together.

    All three are checked BEFORE sizing, never after: a limit enforced after a position is
    opened is not a limit, it is a report."""
    now_ist = datetime.now(IST)
    day_start = now_ist.replace(hour=0, minute=0, second=0,
                               microsecond=0).astimezone(timezone.utc)
    week_start = (now_ist - timedelta(days=now_ist.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    today = await _pnl_since(day_start)
    week = await _pnl_since(week_start)

    realized = unrealized = 0.0
    async for p in ts_positions_collection.find({"status": {"$ne": "OPEN"}},
                                                {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    async for p in ts_positions_collection.find({"status": "OPEN"}, {"unrealized_pnl": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
    equity = INITIAL_CAPITAL + realized + unrealized
    drawdown = max(0.0, (INITIAL_CAPITAL - equity) / INITIAL_CAPITAL) if INITIAL_CAPITAL else 0.0

    reasons = []
    if today <= -DAILY_LOSS_PCT * INITIAL_CAPITAL:
        reasons.append(f"daily loss {today:,.0f} past the {DAILY_LOSS_PCT*100:.0f}% limit")
    if week <= -WEEKLY_LOSS_PCT * INITIAL_CAPITAL:
        reasons.append(f"weekly loss {week:,.0f} past the {WEEKLY_LOSS_PCT*100:.0f}% limit")
    if drawdown >= MAX_DRAWDOWN_PCT:
        reasons.append(f"drawdown {drawdown*100:.1f}% past the {MAX_DRAWDOWN_PCT*100:.0f}% limit")

    return {"breaker_tripped": bool(reasons), "breaker_reasons": reasons,
            "today_pnl": round(today, 2), "week_pnl": round(week, 2),
            "drawdown_pct": round(drawdown * 100, 3),
            "daily_loss_limit": round(DAILY_LOSS_PCT * INITIAL_CAPITAL, 2),
            "weekly_loss_limit": round(WEEKLY_LOSS_PCT * INITIAL_CAPITAL, 2)}


# --------------------------------------------------------------------------------
# Paper cycle
# --------------------------------------------------------------------------------


async def run_paper_cycle() -> dict:
    """One manage+scan pass. Managing comes first, always: an open position's stop matters
    more than a new opportunity, and a scan that raised an exception must never be the
    reason a stop went unchecked."""
    cycle = _Cycle()
    managed, closed = await _manage(cycle)

    notes: list[str] = []
    opened = 0
    rejections: dict[str, int] = {}
    breaker = await breaker_state()

    if PAUSE_NEW_ENTRIES:
        notes.append("Entries paused (TS_PAUSE_ENTRIES=1); open positions still managed.")
    elif breaker["breaker_tripped"]:
        notes.append("Risk breaker tripped — " + "; ".join(breaker["breaker_reasons"])
                     + ". No new entries; open positions still managed.")
    elif _hhmm() >= ENTRY_CUTOFF_HHMM:
        notes.append(f"Past the {ENTRY_CUTOFF_HHMM} entry cutoff — managing only.")
    else:
        try:
            opened, scan_notes, rejections = await _scan(cycle)
            notes += scan_notes
        except Exception as exc:  # noqa: BLE001
            logger.exception("[trending_stocks] scan failed")
            notes.append(f"Scan failed: {exc}")

    snap = await summary()
    await ts_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "open_positions": snap["open_positions"]})
    await ts_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_run_at": _now(), "last_opened": opened, "last_managed": managed,
        "last_closed": closed, "last_notes": notes,
        "last_rejections": rejections}}, upsert=True)
    return {"opened": opened, "managed": managed, "closed": closed,
            "rejections": rejections, "notes": notes}


async def _symbol_pillars(cycle: _Cycle, symbol: str, name: str | None,
                          daily, bench_daily, ltp, quote_ok, quote_note) -> list:
    """The three pillars that depend only on the SYMBOL, computed once per cycle."""
    if symbol not in cycle.sym_pillars:
        cycle.sym_pillars[symbol] = [
            ev.momentum_pillar(daily, bench_daily),
            await ev.news_pillar(symbol, name),
            ev.liquidity_pillar(daily, ltp, quote_ok, quote_note, "angel_quote"),
        ]
    return cycle.sym_pillars[symbol]


def _tf_pillars(cycle: _Cycle, symbol: str, timeframe: str, series, daily,
                bench_daily, pivot: int) -> list:
    """The three that depend on the symbol AND the timeframe."""
    key = (symbol, timeframe)
    if key not in cycle.tf_pillars:
        cycle.tf_pillars[key] = [
            ev.volume_pillar(series),
            ev.price_action_pillar(series, daily, pivot),
            ev.regime_pillar(series, bench_daily),
        ]
    return cycle.tf_pillars[key]


async def _scan(cycle: _Cycle) -> tuple[int, list[str], dict[str, int]]:
    notes: list[str] = []
    rejections: dict[str, int] = {}
    samples: list[dict] = []

    tradable = await _tradable_ids()
    if not tradable:
        return 0, [f"No strategy has earned a paper allocation yet — run the backtest "
                   f"sweep first; only grade >= {MIN_GRADE_TO_TRADE} strategies trade."], {}

    universe = await basket.active()
    if not universe:
        return 0, ["The basket is empty — name the stocks this desk should trade."], {}

    quotes = await live_quotes(universe)
    if not quotes:
        notes.append("No live Angel quotes this cycle — nothing can be filled honestly, "
                     "so no entries were attempted.")
        return 0, notes, {}

    holders: dict[str, int] = {}
    async for p in ts_positions_collection.find({"status": "OPEN"}, {"symbol": 1}):
        holders[p["symbol"]] = holders.get(p["symbol"], 0) + 1

    strategies = [s for s in LONG_CATALOG if s.strategy_id in tradable]
    opened = capped = thin = 0

    for sym, inst in universe.items():
        ltp = quotes.get(sym)
        ok, note = await bar_store.quote_sanity(sym, ltp)
        if not ok:
            await basket.quarantine(sym, note)
            rejections["quarantine"] = rejections.get("quarantine", 0) + 1
            notes.append(f"{sym} quarantined: {note}")
            continue

        daily = await cycle.get_daily(sym)
        bench_daily = await cycle.get_bench("1d")
        name = (inst or {}).get("name")

        for strat in strategies:
            if holders.get(sym, 0) >= MAX_STRATEGIES_PER_SYMBOL:
                capped += 1
                continue
            series = await cycle.get_bars(sym, strat.timeframe, bars_needed(strat))
            if len(series) < strat.min_bars:
                thin += 1
                rejections["bars"] = rejections.get("bars", 0) + 1
                continue
            htf = await cycle.get_bars(sym, strat.htf, 400) if strat.htf else None
            bench = await cycle.get_bench(strat.timeframe) if needs_benchmark(strat) else None

            sig, rej = evaluate_long(
                strat, series, sym, "NSE", htf, None, bench=bench,
                cost_model=cost_model_for(strat), slippage_bps=SLIPPAGE_BPS)
            if sig is None:
                if rej is not None:
                    rejections[rej.stage] = rejections.get(rej.stage, 0) + 1
                    if rej.stage == "feasibility" and len(samples) < REJECTION_SAMPLE:
                        samples.append({"strategy_id": rej.strategy_id, "symbol": sym,
                                        "timeframe": strat.timeframe,
                                        "stage": rej.stage, "reason": rej.reason,
                                        "detail": rej.detail})
                continue

            # ---- research gate --------------------------------------------------
            pillars = (await _symbol_pillars(cycle, sym, name, daily, bench_daily,
                                             ltp, ok, note)
                       + _tf_pillars(cycle, sym, strat.timeframe, series, daily,
                                     bench_daily, int(strat.params.get("pivot", 4)))
                       + [ev.pattern_pillar(sig)])
            evidence = ev.assemble(pillars)

            if not evidence.ok:
                vetoes = evidence.vetoes
                supports = evidence.supports
                stage = "evidence_veto" if vetoes else "evidence_thin"
                rejections[stage] = rejections.get(stage, 0) + 1
                if len(samples) < REJECTION_SAMPLE:
                    samples.append({"strategy_id": strat.strategy_id, "symbol": sym,
                                    "timeframe": strat.timeframe, "stage": stage,
                                    "reason": evidence.summary(),
                                    "detail": (vetoes[0] if vetoes else
                                               f"{supports} of {len(pillars)} pillars "
                                               f"supported (needs {ev.MIN_PILLARS})")})
                continue

            if await _consecutive_losses(strat.strategy_id) >= MAX_CONSECUTIVE_LOSSES:
                rejections["consecutive_losses"] = rejections.get("consecutive_losses", 0) + 1
                continue

            if await _open(strat, sig, inst, evidence, ltp):
                opened += 1
                holders[sym] = holders.get(sym, 0) + 1
            else:
                rejections["sizing_or_slot"] = rejections.get("sizing_or_slot", 0) + 1

    if samples or rejections:
        await ts_rejections_collection.insert_one({
            "created_at": _now(), "counts": rejections, "samples": samples,
            "strategies_evaluated": len(strategies), "symbols": len(universe)})

    if thin:
        notes.append(f"{thin} (symbol, timeframe) series were too short to evaluate — "
                     "the bar store is still filling for those timeframes.")
    if capped:
        notes.append(f"{capped} evaluations skipped: symbol already held by "
                     f"{MAX_STRATEGIES_PER_SYMBOL} strategies.")
    notes.append(f"{len(strategies)} of {len(LONG_CATALOG)} strategies are graded "
                 f">= {MIN_GRADE_TO_TRADE} and eligible to trade.")
    return opened, notes, rejections


async def _open(strat, sig, inst: dict, evidence, ltp: float) -> bool:
    """Open one paper position, at the live price with adverse slippage.

    Levels are re-anchored to the actual fill so the risk recorded is the risk taken — a
    position whose stop distance was measured from the signal price and filled somewhere
    else is not risking what its row claims."""
    if await ts_positions_collection.count_documents(
            {"strategy_id": strat.strategy_id, "status": "OPEN"}) >= MAX_POSITIONS_PER_STRATEGY:
        return False
    if await ts_positions_collection.find_one(
            {"strategy_id": strat.strategy_id, "symbol": sig.symbol, "status": "OPEN"}):
        return False

    fill = slippage_price(ltp, SLIPPAGE_BPS, adverse_for_buy=True)
    shift = fill - sig.entry
    stop, target = sig.stop + shift, sig.target + shift
    risk = fill - stop
    if risk <= 0 or fill <= 0:
        return False

    cash = await _cash(strat.strategy_id)
    levels = Levels(fill, stop, target, risk, target - fill,
                    (target - fill) / risk, sig.stop_basis, sig.target_basis)
    qty = position_size(PER_STRATEGY_CAPITAL, cash, levels, risk_pct=RISK_PCT, lot_size=1)
    if qty < 1:
        return False

    cm = cost_model_for(strat)
    intraday = strat.style in INTRADAY_STYLES
    position_id = uuid4().hex[:12]

    doc = {
        "position_id": position_id, "strategy_id": strat.strategy_id,
        "strategy_name": strat.name, "family": strat.family,
        "sub_family": strat.sub_family, "timeframe": strat.timeframe, "htf": strat.htf,
        "style": strat.style, "intraday": intraday,
        "symbol": sig.symbol, "exchange": "NSE",
        "instrument": {"symbol": inst.get("symbol"),
                       "security_id": str(inst.get("security_id")),
                       "angel_token": inst.get("angel_token"),
                       "exchange_segment": inst.get("exchange_segment"), "lot_size": 1},
        "side": "BUY", "direction": "LONG",
        "signal_price": round(sig.entry, 4), "entry_price": round(fill, 4),
        "stoploss": round(stop, 4), "target": round(target, 4), "qty": qty,
        "risk_per_unit": round(risk, 4), "risk_amount": round(risk * qty, 2),
        "reward_amount": round((target - fill) * qty, 2),
        "r_multiple": round((target - fill) / risk, 3), "min_rr": MIN_RR,
        "capital_deployed": round(fill * qty, 2),
        "capital_allocated": PER_STRATEGY_CAPITAL,
        "pattern": sig.pattern, "detail": sig.detail, "confirmations": sig.confirmations,
        "regime_primary": sig.regime_primary, "regime_tags": sig.regime_tags,
        "confidence": sig.confidence, "hypothesis": sig.hypothesis,
        "feasibility": (sig.meta or {}).get("feasibility"),
        # THE REASON. Written once, from the data available at entry, never regenerated.
        "reasons": evidence.reasons,
        "evidence": evidence.as_doc(),
        "evidence_score": round(evidence.score, 3),
        "cost_model": cm, "ltp_source": "angel_quote",
        "ltp": round(fill, 4), "unrealized_pnl": 0.0, "pnl_pct": 0.0,
        "realized_pnl": None, "costs": None, "exit_price": None, "exit_reason": None,
        "status": "OPEN", "bars_held": 0,
        "max_hold_bars": DEFAULT_MAX_HOLD.get(strat.timeframe, 60),
        "entry_bar_ts": sig.bar_ts, "opened_at": _now(), "updated_at": _now(),
        "closed_at": None, "closed_on": None,
    }
    await ts_positions_collection.insert_one(doc)

    await ts_evidence_collection.insert_one({
        "position_id": position_id, "strategy_id": strat.strategy_id,
        "symbol": sig.symbol, "timeframe": strat.timeframe,
        "evidence": evidence.as_doc(), "feasibility": (sig.meta or {}).get("feasibility"),
        "created_at": _now()})

    await ts_signals_collection.insert_one({
        "signal_id": uuid4().hex[:12], "position_id": position_id,
        "strategy_id": strat.strategy_id, "strategy_name": strat.name,
        "symbol": sig.symbol, "exchange": "NSE", "timeframe": strat.timeframe,
        "htf": strat.htf, "direction": "LONG", "entry": round(fill, 4),
        "stop": round(stop, 4), "target": round(target, 4),
        "risk": round(risk * qty, 2), "reward": round((target - fill) * qty, 2),
        "r_multiple": round((target - fill) / risk, 3), "qty": qty,
        "capital_allocated": PER_STRATEGY_CAPITAL,
        "pattern": sig.pattern, "confirmations": sig.confirmations,
        "regime": sig.regime_primary, "confidence": sig.confidence,
        "evidence_score": round(evidence.score, 3),
        "pillars_supporting": evidence.supports, "reasons": evidence.reasons,
        "taken": True, "created_at": _now()})
    return True


async def _manage(cycle: _Cycle) -> tuple[int, int]:
    """Mark open positions to the last completed bar and close what has resolved.

    The exit rule is deliberately the SAME pessimistic one the replay uses: when a bar's
    range contains both the stop and the target, the stop is assumed to have come first.
    Bar data cannot say which happened first, and the optimistic assumption manufactures
    winners out of exactly the volatile bars where real fills are worst."""
    open_positions = [p async for p in ts_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0, 0

    squareoff = _hhmm() >= EOD_SQUAREOFF_HHMM
    updated = closed = 0
    touched: set[str] = set()

    for pos in open_positions:
        series = await cycle.get_bars(pos["symbol"], pos["timeframe"], 5)
        if not series:
            continue
        bar = series[-1]
        qty = pos["qty"]
        entry = pos["entry_price"]

        hit_stop = bar.low <= pos["stoploss"]
        hit_target = bar.high >= pos["target"]
        held = pos.get("bars_held", 0) + 1
        expired = held >= pos.get("max_hold_bars", 60)
        eod = squareoff and pos.get("intraday")

        reason = ("stoploss" if hit_stop else "target" if hit_target
                  else "eod_squareoff" if eod else "max_hold" if expired else None)
        exit_px = (pos["stoploss"] if reason == "stoploss" else
                   pos["target"] if reason == "target" else bar.close)

        gross = (bar.close - entry) * qty
        projected = round_trip_cost(pos.get("cost_model", "equity_delivery"),
                                    entry, bar.close, qty, True)
        await ts_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "ltp": round(bar.close, 4), "bars_held": held,
            "unrealized_pnl": round(gross - projected, 2),
            "pnl_pct": round((bar.close - entry) / entry * 100, 3) if entry else 0.0,
            "r_now": round((bar.close - entry) / pos["risk_per_unit"], 3)
            if pos.get("risk_per_unit") else None,
            "updated_at": _now()}})
        updated += 1

        if not reason:
            continue

        fill = slippage_price(exit_px, SLIPPAGE_BPS, adverse_for_buy=False)
        g = (fill - entry) * qty
        costs = round_trip_cost(pos.get("cost_model", "equity_delivery"),
                                entry, fill, qty, True)
        net = g - costs
        risk_amount = pos.get("risk_amount") or 0
        now = _now()
        await ts_trades_collection.insert_one({
            "trade_id": uuid4().hex[:12], "position_id": pos.get("position_id"),
            "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
            "family": pos.get("family"), "timeframe": pos.get("timeframe"),
            "style": pos.get("style"), "symbol": pos["symbol"], "side": "BUY",
            "entry_price": entry, "exit_price": round(fill, 4), "qty": qty,
            "gross_pnl": round(g, 2), "costs": round(costs, 2),
            "realized_pnl": round(net, 2),
            "r_realised": round(net / risk_amount, 3) if risk_amount else 0.0,
            "exit_reason": reason, "pattern": pos.get("pattern"),
            "reasons": pos.get("reasons", []),
            "evidence_score": pos.get("evidence_score"),
            "opened_at": pos["opened_at"], "closed_at": now})
        await ts_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
            "gross_pnl": round(g, 2), "costs": round(costs, 2),
            "realized_pnl": round(net, 2), "unrealized_pnl": 0.0,
            "closed_at": now, "closed_on": datetime.now(IST).date().isoformat(),
            "updated_at": now}})
        closed += 1
        touched.add(pos["strategy_id"])

    for sid in touched:
        await _update_paper_score(sid)
    return updated, closed


async def _update_paper_score(sid: str) -> None:
    closed = [p async for p in ts_positions_collection.find(
        {"strategy_id": sid, "status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "costs": 1})]
    pnls = [p.get("realized_pnl") or 0.0 for p in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gl = abs(sum(losses))
    await ts_scores_collection.update_one({"strategy_id": sid}, {"$set": {
        "paper_trades": len(pnls),
        "paper_win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
        "paper_net_pnl": round(sum(pnls), 2),
        "paper_profit_factor": round(sum(wins) / gl, 3) if gl > 0 else None,
        "paper_costs": round(sum(p.get("costs") or 0.0 for p in closed), 2),
        "paper_updated_at": _now(),
    }}, upsert=True)


# --------------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------------


async def summary() -> dict:
    deployed = realized = unrealized = costs = 0.0
    async for p in ts_positions_collection.find({"status": "OPEN"},
                                                {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in ts_positions_collection.find({"status": {"$ne": "OPEN"}},
                                                {"realized_pnl": 1, "costs": 1}):
        realized += p.get("realized_pnl") or 0.0
        costs += p.get("costs") or 0.0

    grades: dict[str, int] = {}
    async for d in ts_scores_collection.find({}, {"grade": 1}):
        g = str(d.get("grade", 0))
        grades[g] = grades.get(g, 0) + 1

    state = await ts_state_collection.find_one({"_id": STATE_ID}) or {}
    basket_rows = await basket.list_basket()

    return {
        "module": "Trending Stocks", "direction": "LONG ONLY", "mode": "paper",
        "strategy_count": len(LONG_CATALOG),
        "family_counts": family_counts(), "style_counts": style_counts(),
        "per_strategy_capital": PER_STRATEGY_CAPITAL,
        "initial_capital": INITIAL_CAPITAL,
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "total_costs": round(costs, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        "open_positions": await ts_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": await ts_positions_collection.count_documents(
            {"status": {"$ne": "OPEN"}}),
        "backtest_rows": await ts_backtests_collection.count_documents({}),
        "validated_rows": await ts_validation_collection.count_documents({}),
        "failed_1_6_rr": await ts_backtests_collection.count_documents(
            {"grade": GRADE_FAILED_RR}),
        "grade_counts": grades,
        "basket": [{"symbol": b["symbol"], "name": b.get("name"),
                    "status": b.get("status"),
                    "quarantine_reason": b.get("quarantine_reason")}
                   for b in basket_rows],
        "basket_size": len([b for b in basket_rows if b.get("status") == basket.STATUS_ACTIVE]),
        "gate": {
            "min_rr": MIN_RR, "min_pillars": ev.MIN_PILLARS, "pillars": ev.PILLARS,
            "min_grade_to_trade": MIN_GRADE_TO_TRADE, "require_grade": REQUIRE_GRADE,
            "max_strategies_per_symbol": MAX_STRATEGIES_PER_SYMBOL,
            "max_positions_per_strategy": MAX_POSITIONS_PER_STRATEGY,
            "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
            "risk_pct": RISK_PCT, "slippage_bps": SLIPPAGE_BPS,
            "min_turnover": ev.MIN_TURNOVER,
            "entry_cutoff": ENTRY_CUTOFF_HHMM, "squareoff": EOD_SQUAREOFF_HHMM,
        },
        "costs_charged": True, "paused": PAUSE_NEW_ENTRIES,
        "market_open": bar_store.is_market_open(),
        "benchmark": bar_store.BENCHMARK_SYMBOL,
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
        "last_backtest_at": state["last_backtest_at"].isoformat()
        if state.get("last_backtest_at") else None,
        "last_validation_at": state["last_validation_at"].isoformat()
        if state.get("last_validation_at") else None,
        "last_notes": state.get("last_notes", []),
        "last_rejections": state.get("last_rejections", {}),
        **(await breaker_state()),
    }


async def leaderboard(family: str | None = None, timeframe: str | None = None,
                      grade: int | None = None, style: str | None = None,
                      status: str | None = None, limit: int = 700) -> list[dict]:
    scores = {d["strategy_id"]: d async for d in ts_scores_collection.find({})}
    open_counts: dict[str, int] = {}
    async for p in ts_positions_collection.find({"status": "OPEN"}, {"strategy_id": 1}):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1

    rows = []
    for s in LONG_CATALOG:
        if family and s.family != family:
            continue
        if timeframe and s.timeframe != timeframe:
            continue
        if style and s.style != style:
            continue
        sc = scores.get(s.strategy_id) or {}
        g = sc.get("grade")
        if grade is not None and (g or 0) != grade:
            continue
        st = sc.get("status") or ("untested" if g is None else None)
        if status and st != status:
            continue
        rows.append({
            "strategy_id": s.strategy_id, "name": s.name, "family": s.family,
            "sub_family": s.sub_family, "timeframe": s.timeframe, "htf": s.htf,
            "style": s.style, "target_r": s.target_r, "min_rr": MIN_RR,
            "hypothesis": s.hypothesis, "regimes": sorted(s.regimes),
            "detector": s.detector, "direction": "LONG",
            "grade": g, "base_grade": sc.get("base_grade"),
            "status": st, "grade_reasons": sc.get("grade_reasons", []),
            "failed_rr": g == GRADE_FAILED_RR,
            "failed_rr_label": FAILED_RR_LABEL if g == GRADE_FAILED_RR else None,
            "best_symbol": sc.get("best_symbol"),
            "bt_trades": sc.get("bt_trades", 0), "bt_win_rate": sc.get("bt_win_rate", 0.0),
            "bt_profit_factor": sc.get("bt_profit_factor"),
            "bt_expectancy": sc.get("bt_expectancy", 0.0),
            "bt_avg_r": sc.get("bt_avg_r", 0.0), "bt_net_pnl": sc.get("bt_net_pnl", 0.0),
            "bt_costs": sc.get("bt_costs", 0.0),
            "bt_max_dd_pct": sc.get("bt_max_dd_pct", 0.0),
            "bt_cagr_pct": sc.get("bt_cagr_pct"), "bt_sharpe": sc.get("bt_sharpe"),
            "oos_net_pnl": sc.get("oos_net_pnl", 0.0), "oos_trades": sc.get("oos_trades", 0),
            "wf_fraction": sc.get("wf_fraction"), "wf_windows": sc.get("wf_windows"),
            "mc_p5_final": sc.get("mc_p5_final"), "mc_prob_ruin": sc.get("mc_prob_ruin"),
            "paper_trades": sc.get("paper_trades", 0),
            "paper_net_pnl": sc.get("paper_net_pnl", 0.0),
            "paper_win_rate": sc.get("paper_win_rate", 0.0),
            "open_positions": open_counts.get(s.strategy_id, 0),
            "eligible": (not REQUIRE_GRADE) or (g or 0) >= MIN_GRADE_TO_TRADE,
        })
    rows.sort(key=lambda r: (-(r["grade"] or 0), -(r["bt_profit_factor"] or 0),
                             -r["bt_net_pnl"]))
    return rows[:limit]


async def rejection_summary(limit: int = 20) -> dict:
    """Why the desk did not trade, aggregated over recent cycles.

    This is the answer to the only question a selective desk gets asked: 'why is nothing
    happening?'. Counts come from every evaluation; the samples are the interesting subset
    — the 1:6 failures, which name the level or the number that blocked them."""
    rows = [d async for d in ts_rejections_collection.find({}).sort("created_at", -1).limit(limit)]
    totals: dict[str, int] = {}
    samples: list[dict] = []
    for r in rows:
        for k, v in (r.get("counts") or {}).items():
            totals[k] = totals.get(k, 0) + v
        samples.extend(r.get("samples") or [])
    state = await ts_state_collection.find_one({"_id": STATE_ID}) or {}
    return {
        "cycles": len(rows), "totals": dict(sorted(totals.items(), key=lambda kv: -kv[1])),
        "samples": samples[:60],
        "backtest_rejection_totals": state.get("rejection_totals", {}),
        "legend": {
            "bars": "not enough history on that timeframe — a DATA gap, not a signal",
            "regime": "the market state is not one this strategy claims to work in",
            "detector": "the setup simply was not present",
            "direction": "the setup fired SHORT and this desk is long only",
            "confirmation": "a confirmation the strategy requires did not pass",
            "feasibility": f"could not support a {MIN_RR:.0f}R target — see the sample detail",
            "evidence_veto": "a research pillar vetoed it (index regime, liquidity, quote or news)",
            "evidence_thin": f"fewer than {ev.MIN_PILLARS} of 7 research pillars supported it",
            "quarantine": "the live quote disagreed with the stored bars",
            "consecutive_losses": "the strategy is in a losing streak and is benched",
            "sizing_or_slot": "position size rounded to zero, or the strategy already holds",
        },
    }


__all__ = ["run_backtests", "run_validation", "run_paper_cycle", "summary", "leaderboard",
           "rejection_summary", "breaker_state", "ensure_indexes", "cost_model_for",
           "live_quotes",
           "PER_STRATEGY_CAPITAL", "INITIAL_CAPITAL", "STATE_ID",
           "MIN_GRADE_TO_TRADE", "MAX_STRATEGIES_PER_SYMBOL"]
