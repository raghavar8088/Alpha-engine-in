"""Indian Index Intraday — the Strategy Factory's 546 strategies, traded intraday on the indexes.

WHAT THIS ADDS
The Strategy Factory (app/services/strategy_factory) composes its strategies from 69 hypotheses —
chart patterns, candlesticks, price structure, indicators and multi-condition hybrids — on 8
timeframes (1m .. 1d): 546 in all. This module runs every one of them on each index it trades, under
its own rules, beside the research's own catalogue. The factory's code is used as it is; nothing in
it changes.

THE RULES (one decision path for the catalogue, the Backtesting Lab and the paper engine)
* The decision is the factory's own `signals.evaluate()` on the index's bars of the strategy's
  timeframe (session-anchored at 09:15). Each decision sees the last `lookback(strategy)` bars:
  twice the strategy's longest lookback (its `min_bars`), at least 300 and at most the factory
  desk's 600 (400 on 4h, 230 on 1d, so the live engine's ~280 sessions of history can always
  supply it) — and, for a higher-timeframe confirmation, only higher-timeframe bars that had
  CLOSED by the decision minute (the factory's own replay hands it the bar still forming).
* INTRADAY ONLY. A decision is read at a bar's close between 09:20 and 14:30 and filled at the next
  minute's open; every position is flat by 15:12. A daily strategy reads yesterday's daily bar and
  enters at 09:20; a 4h strategy decides once a day, at 13:15 (the close of the 09:15-13:15 bar).
  No signal is carried overnight. At most 4 trades a day (1 on 4h and 1d), one at a time.
* Exits: the factory's structural stop and its target (a measured move or R multiple), re-anchored
  to the fill as the factory does; the factory's maximum hold where it is shorter than the session
  (1m: 2 hours); the 15:12 square-off — walked minute by minute by `engine.walk_exit`, the
  module's one exit rule (stop first on a shared minute, targets fill at their level).
* VOLUME. An index prints none. The factory's volume confirmations, OBV and VWAP read the tracking
  ETF's traded volume in the same minutes (NIFTYBEES for NIFTY, BANKBEES for BANK NIFTY ...). BANKEX
  has no ETF, so its volume-dependent strategies never fire — shown, not hidden.
* Costs: the index route's measured all-in cost (costs.py), as for every other strategy here.
* Regimes are the factory's own (classify_regime_series), computed over each series, which starts
  `rows_needed(tf)` days before the first day decided on (at least 3,000 bars, or all the history
  the live engine holds). The classifier is causal and settles within a few hundred bars, so the
  catalogue, the Lab and the live engine give the same tags (checked by the tests).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD
from app.services.strategy_factory.catalog import FACTORY_BY_ID, FACTORY_CATALOG, RECIPES, Strategy
from app.services.strategy_factory.primitives import RegimeState, classify_regime_series
from app.services.strategy_factory.signals import evaluate
from app.services.strategy_factory.sources import Bar

from .costs import ROUTE
from .data import SESSION_MIN, Days, bars as session_bars, minute_of
from .engine import ENTRY_CUTOFF, SQUARE_OFF, Costs, EntrySpec, ExitCfg, Trade, walk_exit

IST = timezone(timedelta(hours=5, minutes=30))
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "4h": 240, "1d": 0}
BARS_PER_DAY = {tf: (math.ceil(SESSION_MIN / m) if m else 1) for tf, m in TF_MINUTES.items()}
FIRST_DECISION = minute_of("09:20")          # also the daily strategies' entry minute
LOOKBACK_CAP = {"4h": 400, "1d": 230}        # most bars a decision sees; 600 otherwise (the factory desk's)
LOOKBACK_MIN = 300
HTF_LOOKBACK = {"1d": 230}                   # higher-timeframe bars; 400 otherwise (the factory desk's)
REGIME_TAIL = 3000                           # bars of warm-up for the regimes (and the series)
MAX_TRADES = {"4h": 1, "1d": 1}              # a day; 4 otherwise
FAMILY_LABEL = {"chart": "Chart Pattern", "candlestick": "Candlestick", "structure": "Price Structure",
                "indicator": "Indicator", "hybrid": "Multi-Condition"}
RECIPE_OF = {}                               # factory strategy id -> its recipe
for _s in FACTORY_CATALOG:
    RECIPE_OF[_s.strategy_id] = next(r for r in RECIPES if r.name == _s.name.split(" · ")[0])
VOLUME_CONFIRMS = {"volume", "vwap"}
VOLUME_DETECTORS = {"obv_breakout", "vwap_reclaim"}
SID = re.compile(r"(SF\d{4})-([A-Z0-9]+)")


def lookback(s: Strategy) -> int:
    """Bars one decision of `s` sees: twice its longest lookback, within [300, the timeframe's cap].
    Every indicator it reads has settled by then (EMA(50) keeps 5e-5 of its seed after 250 bars)."""
    cap = LOOKBACK_CAP.get(s.timeframe, 600)
    return cap if s.timeframe == "1d" else min(cap, max(LOOKBACK_MIN, 2 * s.min_bars))


def htf_lookback(tf: str) -> int:
    return HTF_LOOKBACK.get(tf, 400)


def max_hold_minutes(tf: str) -> int:
    """The factory's maximum hold in minutes, where it is shorter than the session (else 0: none)."""
    m = DEFAULT_MAX_HOLD.get(tf, 0) * TF_MINUTES[tf]
    return m if 0 < m < SQUARE_OFF else 0


EXITS = {f"sf_{tf}": ExitCfg(max_hold=max_hold_minutes(tf)) for tf in TF_MINUTES}


def sid_for(sf_id: str, index: str) -> str:
    return f"{sf_id}-{index}"


def parse_sid(sid: str | None) -> tuple[Strategy, str] | None:
    """'SF0123-NIFTY' -> (the factory strategy, 'NIFTY'); None when it is not a factory id."""
    m = SID.fullmatch(sid or "")
    if not m or m.group(1) not in FACTORY_BY_ID or m.group(2) not in ROUTE:
        return None
    return FACTORY_BY_ID[m.group(1)], m.group(2)


def needs_volume(s: Strategy) -> bool:
    return bool({n for n, _ in s.confirmations} & VOLUME_CONFIRMS) or s.detector in VOLUME_DETECTORS


@dataclass
class SFSpec(EntrySpec):
    """A factory entry: the stop and target as distances from the fill (re-anchored like the factory)."""
    stop_dist: float = 0.0
    target_dist: float = 0.0
    signal: dict = field(default_factory=dict)


# ── one index's bars on one timeframe ──────────────────────────────────────────


class Series:
    """The index's COMPLETE bars of one timeframe as factory Bars (volume from its ETF), with the
    position of each (day row, bar) in the list. `rows_from` skips early rows — the live engine
    builds only what its windows need."""

    def __init__(self, d: Days, etf: Days | None, tf: str, rows_from: int = 0):
        self.tf = tf
        self.rows_from = rows_from
        n = len(d.dates)
        self.bars: list[Bar] = []
        if tf == "1d":
            nb = 1
            self.end = np.array([SESSION_MIN - 1])
            vol = np.zeros(n)
            if etf is not None and len(etf.dates):
                vrow = {dt: r for r, dt in enumerate(etf.dates)}
                for i, dt in enumerate(d.dates):
                    r = vrow.get(dt)
                    if r is not None:
                        vol[i] = float(np.nansum(etf.v[r]))
            cols = (d.o[:, :1], d.h.max(axis=1)[:, None], d.l.min(axis=1)[:, None], d.c[:, -1:], vol[:, None])
        else:
            m = TF_MINUTES[tf]
            B = session_bars(d, m)
            nb = len(B["start"])
            self.end = B["end"]
            vol = np.zeros((n, nb))
            if etf is not None and len(etf.dates):
                E = session_bars(etf, m)
                vrow = {dt: r for r, dt in enumerate(etf.dates)}
                for i, dt in enumerate(d.dates):
                    r = vrow.get(dt)
                    if r is not None:
                        vol[i] = np.nan_to_num(E["v"][r])
            cols = (B["o"], B["h"], B["l"], B["c"], vol)
            starts = B["start"]
        o, h, l, c, v = cols
        self.pos = np.full((n, nb), -1, dtype=np.int64)
        for i in range(rows_from, n):
            dt = d.dates[i].astype(object)
            base = datetime(dt.year, dt.month, dt.day, 9, 15, tzinfo=IST)
            for k in range(nb):
                oo, hh, ll, cc = o[i, k], h[i, k], l[i, k], c[i, k]
                if not (oo == oo and hh == hh and ll == ll and cc == cc):
                    continue                                    # not complete yet (today, live)
                ts = base if tf == "1d" else base + timedelta(minutes=int(starts[k]))
                self.pos[i, k] = len(self.bars)
                self.bars.append(Bar(ts, float(oo), float(hh), float(ll), float(cc), float(v[i, k])))
        table: dict = {}
        self.regimes = []
        for r in classify_regime_series(self.bars):
            k = (r.primary, frozenset(r.tags))
            self.regimes.append(table.setdefault(k, RegimeState(primary=r.primary, tags=set(r.tags))))

    def decisions(self, i: int) -> list[tuple[int, int, int]]:
        """(bar, decision minute, position of the bar a decision reads) for day row i, in order."""
        if self.tf == "1d":
            prev = self.pos[:i, 0]
            prev = prev[prev >= 0]
            return [(0, FIRST_DECISION, int(prev[-1]))] if len(prev) else []
        out = []
        for k, e in enumerate(self.end):
            dec = int(e) + 1
            j = int(self.pos[i, k])
            if j >= 0 and FIRST_DECISION <= dec <= ENTRY_CUTOFF:
                out.append((k, dec, j))
        return out

    def closed_before(self, i: int, minute: int) -> int:
        """How many bars had closed by `minute` of day row i (a slice end for a higher timeframe)."""
        if self.tf == "1d":
            prev = self.pos[:i, 0]
            prev = prev[prev >= 0]
            return int(prev[-1]) + 1 if len(prev) else 0
        done = self.pos[i][(self.end + 1 <= minute) & (self.pos[i] >= 0)]
        if len(done):
            return int(done[-1]) + 1
        prev = self.pos[:i][self.pos[:i] >= 0]
        return int(prev.max()) + 1 if len(prev) else 0


def rows_needed(tf: str) -> int:
    """Day rows of warm-up a timeframe's series is built with before the first day it decides on:
    enough for the longest decision window, the higher-timeframe window and the regime window."""
    per = BARS_PER_DAY[tf]
    return math.ceil(max(LOOKBACK_CAP.get(tf, 600), htf_lookback(tf), REGIME_TAIL) / per) + 3


# ── the family: the module's interface to the paper engine and the Lab ──────────

_LIVE_CACHE: dict = {}                        # (sid, day, bar, data checksum) -> decision; live only


def series_for(ctx, tf: str) -> Series:
    """The timeframe's series, built from `rows_needed(tf)` rows before the first day decided on (the
    live engine: today; a backtest: its first day). Its regimes are computed over all of it."""
    key = ("sf_series", tf)
    if key not in ctx.cache:
        first = getattr(ctx, "first_row", None)
        first = len(ctx.d.dates) - 1 if first is None else first
        ctx.cache[key] = Series(ctx.d, getattr(ctx, "etf", None), tf, max(0, first - rows_needed(tf)))
    return ctx.cache[key]


def _checksum(ctx, i: int, minute: int) -> float:
    d = ctx.d
    s = float(np.nansum(d.h[i, :minute]) + np.nansum(d.l[i, :minute]) + np.nansum(d.c[i, :minute]))
    etf = getattr(ctx, "etf", None)
    if etf is not None and len(etf.dates) and etf.dates[-1] == d.dates[i]:
        s += float(np.nansum(etf.v[-1, :minute]))
    return round(s, 4)


def decide(strat: Strategy, ctx, i: int, k: int, dec: int, j: int):
    """The factory's evaluate() on the bars a decision at minute `dec` of day row i could see."""
    S = series_for(ctx, strat.timeframe)
    L = lookback(strat)
    sl = S.bars[max(0, j + 1 - L): j + 1]
    htf = None
    if strat.htf:
        H = series_for(ctx, strat.htf)
        cut = H.closed_before(i, dec)
        htf = H.bars[max(0, cut - htf_lookback(strat.htf)): cut] or None
    return evaluate(strat, sl, ctx.d.name, "NSE", htf, regime=S.regimes[j])


def _spec(sig, side: int, dec: int, tf: str) -> SFSpec:
    return SFSpec(side, dec, "market", stop_dist=abs(sig.entry - sig.stop), target_dist=abs(sig.target - sig.entry),
                  signal={"pattern": sig.pattern, "detail": sig.detail, "confidence": sig.confidence,
                          "regime": sig.regime_primary, "confirmations": sig.confirmations,
                          "stop_basis": sig.stop_basis, "target_basis": sig.target_basis,
                          "r_multiple": sig.r_multiple, "bar": sig.bar_ts.isoformat(), "timeframe": tf})


def fam_sf(ctx, p: dict, rejections: dict | None = None):
    """The module's family interface for one factory strategy: p = {"sf": "SF0123"}. Cheap to build:
    bars and regimes are made the first time a day is asked for."""
    strat = FACTORY_BY_ID[p["sf"]]
    tf = strat.timeframe
    live = getattr(ctx, "live", False)

    def day_specs(i: int):
        def specs(after: int):
            S = series_for(ctx, tf)
            day = str(ctx.d.dates[i])
            for k, dec, j in S.decisions(i):
                if dec < after:
                    continue
                key = None
                if live:
                    key = (strat.strategy_id, ctx.d.name, day, k, _checksum(ctx, i, dec) if tf != "1d" else 0.0)
                    if key in _LIVE_CACHE:
                        got = _LIVE_CACHE[key]
                        if got is not None:
                            return got
                        continue
                sig, rej = decide(strat, ctx, i, k, dec, j)
                spec = None
                if sig is not None:
                    spec = _spec(sig, 1 if sig.side == "BUY" else -1, dec, tf)
                elif rejections is not None and rej is not None:
                    rejections[rej.stage] = rejections.get(rej.stage, 0) + 1
                if key is not None:
                    if len(_LIVE_CACHE) > 200_000:
                        _LIVE_CACHE.clear()
                    _LIVE_CACHE[key] = spec
                if spec is not None:
                    return spec
            return None
        return specs
    return day_specs, None, MAX_TRADES.get(tf, 4)


# ── the simulator (engine.simulate_day, with the factory's own stop and target) ──


def simulate_day(o, h, l, c, specs_fn, costs: Costs, max_trades: int, max_hold: int, day: int) -> list[Trade]:
    """engine.simulate_day's rules exactly — market entry at the decision minute's open plus
    slippage, walk_exit to the 15:12 square-off, targets without slippage — except that the stop
    and target are the signal's, re-anchored to the fill."""
    trades: list[Trade] = []
    t = 0
    while len(trades) < max_trades:
        spec = specs_fn(t)
        if spec is None or spec.minute > ENTRY_CUTOFF or spec.minute >= SQUARE_OFF:
            break
        m, side = spec.minute, spec.side
        raw = float(o[m])
        entry = raw * (1 + side * costs.slip_bp / 1e4)
        stop = raw - side * spec.stop_dist
        target = raw + side * spec.target_dist
        hold_end = (m + max_hold) if max_hold else None
        x_min, x_raw, reason = walk_exit(o, h, l, c, m, SQUARE_OFF, side, raw, stop, target, None, None, hold_end,
                                         "market")
        exit_px = x_raw * (1 - side * (0.0 if reason == "target" else costs.slip_bp) / 1e4)
        gross = side * (x_raw - raw) / raw * 1e4
        net = side * (exit_px - entry) / entry * 1e4 - costs.fee_rt_bp
        trades.append(Trade(day, side, m, entry, x_min, exit_px, reason, gross, net))
        t = x_min + 1
    return trades


class _Ctx:
    """What fam_sf needs from a context, for a backtest: the index, its ETF and a cache."""

    def __init__(self, d: Days, etf: Days | None, first_row: int = 0):
        self.d, self.etf, self.cache, self.live, self.first_row = d, etf, {}, False, first_row


def run(strat: Strategy, d: Days, etf: Days | None, lo: int, costs: Costs, ctx=None,
        rejections: dict | None = None) -> list[Trade]:
    """Every trade of one factory strategy on day rows lo .. end of `d` (Trade.day = row - lo)."""
    ctx = ctx or _Ctx(d, etf, lo)
    day_specs, _x, max_trades = fam_sf(ctx, {"sf": strat.strategy_id}, rejections)
    hold = max_hold_minutes(strat.timeframe)
    out: list[Trade] = []
    for i in range(lo, len(d.dates)):
        out += simulate_day(d.o[i], d.h[i], d.l[i], d.c[i], day_specs(i), costs, max_trades, hold, i - lo)
    return out


# ── grading: the factory's rules (factory backtest._grade), on this module's numbers ──

MIN_TRADES = 20


def grade(all_s: dict, oos: dict) -> tuple[int, list[str]]:
    """1-5 on several axes, never on win rate alone. Out-of-sample (2022-23) failure caps a strategy
    at 2 and names it likely overfit. Drawdown is in % of the capital a trade uses (no leverage)."""
    n = all_s.get("trades", 0)
    if n < MIN_TRADES:
        return 1, [f"only {n} trades in 2019-23 (needs {MIN_TRADES}) — not enough evidence"]
    total, pf = all_s["total_bp"], all_s["profit_factor"]
    if total <= 0:
        return 1, [f"net {total / 100:+.2f}% over 2019-23 after costs ({n} trades)"]
    if pf is None or pf <= 1.0:
        return 1, [f"profit factor {pf:.2f} is not above 1"]
    ot, onet = oos.get("trades", 0), oos.get("total_bp", 0.0)
    if ot < max(5, MIN_TRADES // 4) or onet <= 0:
        return 2, [f"out of sample (2022-23) not profitable: {ot} trades, net {onet / 100:+.2f}% — likely overfit"]
    dd = all_s["max_dd_bp"] / 100
    sh = all_s.get("sharpe") or 0.0
    why = [f"profit factor {pf:.2f}, out of sample net {onet / 100:+.2f}% over {ot} trades"]
    if pf >= 1.6 and dd <= 15 and n >= 2 * MIN_TRADES and sh >= 1.0:
        return 5, why + ["strong profit factor, contained drawdown, deep sample"]
    if pf >= 1.4 and dd <= 25:
        return 4, why
    if pf >= 1.15:
        return 3, why
    return 2, why + ["edge too thin once costs are charged"]


def describe(s: Strategy) -> dict:
    """A factory strategy's rules, for the catalogue and the page."""
    r = RECIPE_OF[s.strategy_id]
    return {"sf": s.strategy_id, "name": s.name, "recipe": r.key, "hypothesis_name": r.name,
            "family": s.family, "family_label": FAMILY_LABEL.get(s.family, s.family), "sub_family": s.sub_family,
            "timeframe": s.timeframe, "htf": s.htf, "detector": s.detector, "hypothesis": s.hypothesis,
            "confirmations": [n for n, _ in s.confirmations], "regimes": sorted(s.regimes),
            "target_r": s.target_r, "style": s.style, "volume_dependent": needs_volume(s),
            "max_trades_a_day": MAX_TRADES.get(s.timeframe, 4), "max_hold_min": max_hold_minutes(s.timeframe),
            "lookback_bars": lookback(s), "fingerprint": s.fingerprint}
