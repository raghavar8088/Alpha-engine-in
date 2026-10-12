"""Indian Index Intraday — the Backtesting Lab: run any catalogued strategy (or a family with your
own parameters) over a chosen window of the stored 1-minute history, with the same simulator the
research used.

Limits that keep it honest and the server healthy: at most three years a run, with 420 calendar
days of warm-up loaded before the window (the VIX regime compares yesterday's VIX with its
trailing 250-session median; ATR and the indicators settle long before), computed off the event
loop, one run at a time. Results
are a BACKTEST — the module's statuses come from the research protocol, not from a run here; a
run over 2024-2026 shows the period the research kept as its untouched holdout, which is
exploration, not validation.

COST BASIS
  measured  (default) each ETF's measured effective half-spread — what a trade costs today
  research  the starting table the research rounds were run on: a run over 2022-23 on this basis
            reproduces the catalogue's validation numbers (held to it by a test)
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta

import numpy as np

from . import catalog as cat
from . import families as F
from .costs import ROUTE, costs_for
from .data import Days, _build, _read, minute_of
from .engine import ENTRY_CUTOFF, Costs, simulate_day, summarize

MAX_SPAN_DAYS = 3 * 366
WARMUP_DAYS = 420                              # >= 250 sessions before the window (the VIX regime's median)
_ONE_AT_A_TIME = asyncio.Semaphore(1)          # a run holds ~100 MB while it loads; never two at once
LAST_HALF_HOUR_CUTOFF = minute_of("14:45")     # the intraday-momentum family trades the last half hour


def _load_window(name: str, start: date, end: date) -> Days:
    d = _build(name, _read(name, start - timedelta(days=WARMUP_DAYS), end))
    keep = d.dates <= np.datetime64(end.isoformat())
    return Days(d.name, d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep], d.quality)


def _finite(v):
    """JSON has no NaN or Infinity (a run with no losing trade has an infinite profit factor)."""
    return None if isinstance(v, float) and not math.isfinite(v) else v


def run_sync(family: str, params: dict, exit_name: str, index: str, start: date, end: date,
             cost_scale: float = 1.0, cost_basis: str = "measured") -> dict:
    if family not in F.FAMILIES or exit_name not in F.EXITS:
        raise ValueError("unknown family or exit")
    if cost_basis not in ("measured", "research"):
        raise ValueError("cost basis must be 'measured' or 'research'")
    if not 0 < cost_scale <= 5:
        raise ValueError("cost scale must be in (0, 5]")
    if end < start:
        raise ValueError("the window ends before it starts")
    if (end - start).days > MAX_SPAN_DAYS:
        raise ValueError("at most three years a run")
    d = _load_window(index, start, end)
    try:
        vix = _load_window("INDIAVIX", start, end)
    except FileNotFoundError:
        vix = None
    ctx = F.Ctx(d, vix)
    costs: Costs = costs_for(index, scale=cost_scale, research=cost_basis == "research")
    xcfg = F.EXITS[exit_name]
    cut = LAST_HALF_HOUR_CUTOFF if family == "imom" else ENTRY_CUTOFF
    lo = int(np.searchsorted(d.dates, np.datetime64(start.isoformat())))
    trades = []
    try:
        day_specs, day_exit, max_trades = F.FAMILIES[family](ctx, params)
        for i in range(lo, len(d.dates)):
            trades += simulate_day(d.o[i], d.h[i], d.l[i], d.c[i], day_specs(i), xcfg, ctx.day_atr[i], costs,
                                   day_exit(i) if day_exit else None, max_trades, i - lo, cut)
    except KeyError as exc:
        raise ValueError(f"the {family} family needs the parameter {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"these parameters do not fit the {family} family: {exc}") from exc
    n = len(d.dates) - lo
    dates = d.dates[lo:]
    stats = summarize(trades, n, dates) if trades else {"trades": 0}
    reasons = stats.pop("reasons", {})
    stats = {k: _finite(v) for k, v in stats.items()}
    daily = np.zeros(n)
    for t in trades:
        daily[t.day] += t.net_bp
    eq = np.cumsum(daily)
    dd = np.maximum.accumulate(np.r_[0, eq])[1:] - eq
    step = max(1, n // 400)
    return {
        "family": family, "params": params, "exit": exit_name, "index": index,
        "start": str(dates[0]) if n else None, "end": str(dates[-1]) if n else None, "days": n,
        "costs": {"fee_rt_bp": round(costs.fee_rt_bp, 3), "slip_bp_a_side": round(costs.slip_bp, 3), "scale": cost_scale,
                  "basis": cost_basis},
        "stats": stats, "exit_reasons": reasons,
        "equity_bp": [[str(dates[k]), round(float(eq[k]), 2)] for k in range(0, n, step)],
        "drawdown_bp": [[str(dates[k]), round(float(-dd[k]), 2)] for k in range(0, n, step)],
        "trades": [{"day": str(dates[t.day]), "side": t.side, "entry_min": t.entry_min, "exit_min": t.exit_min,
                    "entry": round(t.entry_px, 2), "exit": round(t.exit_px, 2), "reason": t.reason,
                    "gross_bp": round(t.gross_bp, 2), "net_bp": round(t.net_bp, 2)} for t in trades[-200:]],
        "note": "A backtest of the index route with the ETF's costs. Status comes from the research protocol.",
    }


async def run(sid: str | None = None, family: str | None = None, params: dict | None = None,
              exit_name: str | None = None, index: str | None = None, start: str | None = None,
              end: str | None = None, cost_scale: float = 1.0, cost_basis: str = "measured") -> dict:
    if sid:
        s = cat.get(sid)
        if s is None:
            raise ValueError(f"no strategy {sid}")
        family, params, exit_name, index = s["family"], s["params"], s["exit"], s["index"]
    if params is not None and not isinstance(params, dict):
        raise ValueError("params must be an object, e.g. {\"k\": 0.5}")
    e = date.fromisoformat(end) if end else date.today()
    st = date.fromisoformat(start) if start else e - timedelta(days=365)
    if index not in ROUTE:
        raise ValueError(f"unknown index {index}")
    async with _ONE_AT_A_TIME:
        return await asyncio.to_thread(run_sync, family, params or {}, exit_name, index, st, e, cost_scale, cost_basis)
