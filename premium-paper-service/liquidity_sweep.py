"""Booming Bulls' liquidity-sweep strategies on the paper desk (backend/research/liquidity_sweep_2026_11).

Covers D9 (`bb_liquidity_sweep`), its 22 one-change versions (`bb_ls_v01_*` ... `bb_ls_v22_*`) and three of the study's
research-only runs: 15-minute candles, 3-minute candles and Bank Nifty.

The rules are imported, not copied. The strategy classes are the app's own, in strategy-service: the classes the study
tested. This module only does four things:
  - It turns the desk's 1-minute rows into complete, 09:15-aligned candles (5 minutes; 15 or 3 for two research runs).
  - It feeds those candles to a fresh instance of the class, as the study's harness did.
  - It fills each entry exactly as the study did:
      - entry at the confirming candle's close;
      - stop or target on 1-minute rows, stop first when one minute touches both;
      - a minute that opens beyond the stop fills at its open;
      - for v13, the stop moves to entry from the candle after the one that reached +1R;
      - v15 has no target;
      - otherwise out at 15:15 (the close of the 15:14 minute).
  - It costs each trade as one futures lot: Angel One's charges on the trade date (`bb_engine.futures_fees`, the same
    formula the study used) plus 1 index point of slippage a fill.

On the live day, a trade whose rows run out before 15:15 is still open: it is reported as "time" at the last row, as
`runner.docs_from` expects. An entry whose next minute has not printed yet appears in the next cycle.
"""

from __future__ import annotations

import math
import os
import sys
import types
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from research import BE

ROOT = Path(os.getenv("PREMIUM_REPO_ROOT") or Path(__file__).resolve().parents[1])
for _p in (ROOT / "shared", ROOT / "strategy-service"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _package(name: str, path: Path) -> None:
    """Register a package without running its __init__. The full strategy library's __init__ imports about 650
    strategies; the paper desk needs three files of it, and its image carries only those."""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod


_SS = ROOT / "strategy-service" / "strategy_service"
_package("strategy_service", _SS)
_package("strategy_service.strategies", _SS / "strategies")
_package("strategy_service.strategies.options_buying", _SS / "strategies" / "options_buying")

import strategy_service.strategies.options_buying.booming_bulls_sweep_versions  # noqa: E402,F401 (registers D9's versions)
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext  # noqa: E402
from tradingai_shared.domain import Bar, SignalAction, Timeframe  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
OPEN_MIN = 9 * 60 + 15
SESSION_MIN = 375
SQUARE_OFF = 360                 # minute index of 15:15: an open trade leaves at the close of minute 359
SLIP_PTS = 1.0                   # index points a fill, as in the study
LOT = {"NIFTY": 65, "BANKNIFTY": 30}
WARM_SESSIONS = 20               # sessions fed before the first replayed day: levels need 6, the 200 EMA 3
ENTRY = (SignalAction.BUY, SignalAction.SELL)

# variant -> (strategy id, params, candle minutes): the study's VERSIONS table (ls_versions.py)
VERSIONS: dict[str, tuple[str, dict, int]] = {
    "v00": ("bb_liquidity_sweep", {}, 5),
    "v01": ("bb_ls_v01_pdh_pdl", {}, 5),
    "v02": ("bb_ls_v02_pdc_only", {}, 5),
    "v03": ("bb_ls_v03_equal_hl", {}, 5),
    "v04": ("bb_ls_v04_1h_swings", {}, 5),
    "v05": ("bb_ls_v05_round_numbers", {}, 5),
    "v06": ("bb_ls_v06_wick_only", {}, 5),
    "v07": ("bb_ls_v07_strong_reject", {}, 5),
    "v08": ("bb_ls_v08_next_candle", {}, 5),
    "v09": ("bb_ls_v09_retest_entry", {}, 5),
    "v10": ("bb_ls_v10_mss", {}, 5),
    "v11": ("bb_ls_v11_target_1r", {}, 5),
    "v12": ("bb_ls_v12_target_3r", {}, 5),
    "v13": ("bb_ls_v13_breakeven", {}, 5),
    "v14": ("bb_ls_v14_opposite_liq", {}, 5),
    "v15": ("bb_ls_v15_no_target", {}, 5),
    "v16": ("bb_ls_v16_ema200", {}, 5),
    "v17": ("bb_ls_v17_big_sweeps", {}, 5),
    "v18": ("bb_ls_v18_morning", {}, 5),
    "v19": ("bb_ls_v19_afternoon", {}, 5),
    "v20": ("bb_ls_v20_one_a_day", {}, 5),
    "v21": ("bb_ls_v21_break_retest", {}, 5),
    "v22": ("bb_ls_v22_full_video", {}, 5),
    "r1": ("bb_liquidity_sweep", {"bar_minutes": 15}, 15),
    "r2": ("bb_liquidity_sweep", {"bar_minutes": 3}, 3),
    "r3": ("bb_liquidity_sweep", {}, 5),          # on Bank Nifty
}


@dataclass
class Trade:
    """The fields runner.docs_from reads, in the units of the other studies' trades (prices, R per unit)."""
    variant: str
    setup: str
    date: str
    side: int
    entry_k: int
    exit_k: int
    entry: float
    stop: float
    target: float
    exit: float
    reason: str
    risk: float
    r_gross: float
    r_net: float
    cost_r: float


def _day_rows(m, d: int) -> np.ndarray:
    """Row index of each session minute 0..374 of day d (-1 where the minute has not printed)."""
    rows = np.full(SESSION_MIN, -1, dtype=np.int64)
    a, z = int(m.d0[d]), int(m.d1[d])
    mi = m.ist[a:z].astype(np.int64) - OPEN_MIN
    ok = (mi >= 0) & (mi < SESSION_MIN)
    rows[mi[ok]] = np.arange(a, z, dtype=np.int64)[ok]
    return rows


def _candles(m, market: str, minutes: int, d_from: int, cache: dict) -> tuple[list, dict]:
    """(candles as (day, start minute, Bar), day -> minute rows) from day d_from on. Complete candles only."""
    key = ("ls", market, minutes, d_from, len(m.t))
    if key in cache:
        return cache[key]
    tf = Timeframe.M15 if minutes == 15 else Timeframe.M5     # the app has no 3-minute timeframe; the class reads bar_minutes
    out, rows_of = [], {}
    for d in range(d_from, m.n_days):
        rows = _day_rows(m, d)
        rows_of[d] = rows
        y, mo, dd = (int(x) for x in str(m.date[d]).split("-"))
        open_ts = datetime(y, mo, dd, 9, 15, tzinfo=IST)
        for s in range(0, SESSION_MIN, minutes):
            r = rows[s:s + minutes]
            if len(r) < minutes or (r < 0).any():
                continue
            out.append((d, s, Bar.model_construct(
                symbol=market, timeframe=tf, ts=(open_ts + timedelta(minutes=s)).astimezone(timezone.utc),
                open=float(m.o[r[0]]), high=float(m.h[r].max()), low=float(m.l[r].min()), close=float(m.c[r[-1]]),
                volume=0, oi=None)))
    cache[key] = (out, rows_of)
    return out, rows_of


def _walk(m, rows: np.ndarray, m0: int, side: int, entry: float, stop: float, target, be_r: float, risk: float,
          candle: int):
    """(exit price, reason, exit row) or None when the session's rows end first (still open on the live day)."""
    be_from = None
    for mi in range(m0, SQUARE_OFF):
        k = int(rows[mi])
        if k < 0:
            return None
        if be_from is not None and mi >= be_from:
            stop = entry
        o, h, lo = float(m.o[k]), float(m.h[k]), float(m.l[k])
        be = be_from is not None and mi >= be_from
        if side < 0:
            if h >= stop:
                return max(o, stop), ("be_stop" if be else ("stop_gap" if o > stop else "stop")), k
            if target is not None and lo <= target:
                return target, "target", k
            if be_r > 0 and be_from is None and lo <= entry - be_r * risk:
                be_from = (mi // candle + 1) * candle
        else:
            if lo <= stop:
                return min(o, stop), ("be_stop" if be else ("stop_gap" if o < stop else "stop")), k
            if target is not None and h >= target:
                return target, "target", k
            if be_r > 0 and be_from is None and h >= entry + be_r * risk:
                be_from = (mi // candle + 1) * candle
    k = int(rows[SQUARE_OFF - 1])
    return (float(m.c[k]), "time", k) if k >= 0 else None


def run(variant: str, market: str, m, first, cache: dict) -> list[Trade]:
    """Every trade of one version on one market from day `first` on, replayed over the rows known now."""
    sid, params, minutes = VERSIONS[variant]
    first = first.isoformat() if isinstance(first, date) else str(first)
    later = np.flatnonzero(m.date >= np.datetime64(first))
    if not len(later):
        return []
    d_first = int(later[0])
    candles, rows_of = _candles(m, market, minutes, max(0, d_first - WARM_SESSIONS), cache)
    strat = STRATEGY_REGISTRY[sid](params=params)
    ctx = StrategyContext(max_bars=max(500, strat.warmup + 2))
    entries = []
    for d, s, bar in candles:
        ctx.push(bar)
        if len(ctx.bars) < strat.warmup:
            continue
        sig = strat.on_bar(ctx)
        if sig is not None and sig.signal in ENTRY and d >= d_first:
            entries.append((d, s, dict(strat.last_plan)))
    be_r = float(getattr(strat.params, "breakeven_r", 0.0) or 0.0)
    lot, last = LOT[market], len(m.t) - 1
    out = []
    for d, s, plan in entries:
        rows = rows_of[d]
        m0 = s + minutes
        if m0 >= SESSION_MIN or rows[m0] < 0:
            continue                      # the next minute has not printed yet: the entry shows next cycle
        side, entry, stop, target, risk = plan["side"], plan["entry"], plan["stop"], plan["target"], plan["risk"]
        res = _walk(m, rows, m0, side, entry, stop, target, be_r, risk, minutes)
        if res is None:                   # rows ran out before 15:15: open, marked at the last row
            px, reason, k = float(m.c[last]), "time", last
        else:
            px, reason, k = res
        day = date.fromisoformat(str(m.date[d]))
        entry_fill, exit_fill = entry + side * SLIP_PTS, px - side * SLIP_PTS
        fees = round(BE.futures_fees(entry_fill, exit_fill, lot, side, day), 2)
        gross = side * (px - entry)
        net = side * (exit_fill - entry_fill) - fees / lot
        names = sorted({n for lv in plan["levels"] for n in str(lv[0]).split("+")})
        out.append(Trade(variant=variant, setup="+".join(names), date=day.isoformat(), side=int(side),
                         entry_k=int(rows[m0]), exit_k=int(k), entry=float(entry), stop=float(stop),
                         target=math.nan if target is None else float(target), exit=float(px), reason=reason,
                         risk=float(risk), r_gross=gross / risk, r_net=net / risk, cost_r=(gross - net) / risk))
    return out
