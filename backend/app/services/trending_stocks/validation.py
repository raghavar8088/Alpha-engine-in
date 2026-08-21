"""Validation beyond a single backtest: walk-forward, Monte Carlo, and the final grade.

WHY A GOOD BACKTEST IS NOT EVIDENCE
------------------------------------
One replay over one history produces one number, and with 678 strategies swept over a
basket of stocks, some of them will produce a good one by arithmetic alone. The brief is
right to demand more, and this module is what stands between "profitable in the sample"
and "allowed to trade paper".

WALK-FORWARD, HONESTLY DESCRIBED
---------------------------------
These strategies have no fitted parameters — nothing is optimised on the data, so there is
no in-sample fit to walk forward FROM in the classical Pardo sense. What can still fail,
and routinely does, is that an edge exists in one market period and not the next. So the
walk-forward here splits the BAR SERIES into contiguous windows and replays each one
separately, each with its own warm-up prefix, then reports how many windows were
profitable. That answers the question that actually matters — *does this keep working as
conditions change* — and it is described as what it is rather than borrowing authority
from a technique it is not.

It costs one replay per window, so it runs only on strategies that already earned a
passing grade on the full history. Running five extra replays for 678 strategies x every
symbol, most of which are already rejected, would multiply a sweep measured in hours by
five to learn nothing about strategies that are not going anywhere.

MONTE CARLO
-----------
Resample the trade sequence with replacement and rebuild the equity path 1,000 times. The
ORDER of trades is what produces a drawdown, and the observed order is one sample from a
distribution — a strategy whose losses happened to be spaced out looks far safer than it
is. Reported at the 5th percentile, not the mean, because the question being asked is
"how bad does this get", and the mean of a distribution of bad outcomes is not that.

The bootstrap is seeded per strategy so the leaderboard does not reshuffle on every
refresh. That is reproducibility, not curve-fitting: the seed does not touch the trades.
"""

from __future__ import annotations

import hashlib
import os
import random
import statistics
from dataclasses import dataclass, field

from app.services.strategy_factory.backtest import BacktestResult, backtest
from app.services.strategy_factory.primitives import DEFAULT_CAPITAL, DEFAULT_RISK_PCT

from .feasibility import FAILED_RR_LABEL, MIN_RR
from .signals import make_evaluator

WF_WINDOWS = int(os.getenv("TS_WF_WINDOWS", "5"))
MC_ITERATIONS = int(os.getenv("TS_MC_ITERATIONS", "1000"))
# The drawdown at which a strategy is considered to have blown up in a Monte Carlo path.
MC_RUIN_PCT = float(os.getenv("TS_MC_RUIN_PCT", "25"))

# Grade thresholds on top of the factory's.
WF_PROFITABLE_FOR_5 = float(os.getenv("TS_WF_G5", "0.70"))
WF_PROFITABLE_FOR_4 = float(os.getenv("TS_WF_G4", "0.55"))

GRADE_FAILED_RR = 0        # stored as 0 and labelled FAILED — never as a 1, which means
                           # "measured and rejected" rather than "structurally ineligible"


@dataclass
class WalkForward:
    windows: int = 0
    profitable: int = 0
    fraction: float = 0.0
    detail: list[dict] = field(default_factory=list)
    note: str = ""

    def as_doc(self) -> dict:
        return {"windows": self.windows, "profitable": self.profitable,
                "fraction": round(self.fraction, 3), "detail": self.detail,
                "note": self.note}


@dataclass
class MonteCarlo:
    iterations: int = 0
    median_final: float = 0.0
    p5_final: float = 0.0
    p95_final: float = 0.0
    median_max_dd_pct: float = 0.0
    p95_max_dd_pct: float = 0.0
    prob_of_ruin: float = 0.0
    prob_of_loss: float = 0.0
    note: str = ""

    def as_doc(self) -> dict:
        return {"iterations": self.iterations,
                "median_final": round(self.median_final, 2),
                "p5_final": round(self.p5_final, 2),
                "p95_final": round(self.p95_final, 2),
                "median_max_dd_pct": round(self.median_max_dd_pct, 2),
                "p95_max_dd_pct": round(self.p95_max_dd_pct, 2),
                "prob_of_ruin": round(self.prob_of_ruin, 4),
                "prob_of_loss": round(self.prob_of_loss, 4),
                "ruin_threshold_pct": MC_RUIN_PCT, "note": self.note}


def run_backtest(strategy, bars, symbol: str, *, bench=None, cost_model: str,
                 capital: float = DEFAULT_CAPITAL, slippage_bps: float = 5.0,
                 risk_pct: float = DEFAULT_RISK_PCT, htf_bars=None,
                 min_rr: float | None = None,
                 min_trades_for_grade: int = 20) -> BacktestResult:
    """The shared no-look-ahead replay, driven by THIS desk's decision function.

    `evaluate_fn` is the whole reason there is no second replay in this module: the
    backtest and the paper desk call the same `evaluate_long`, so a backtest number
    describes what the desk will actually do."""
    return backtest(
        strategy, bars, symbol, exchange="NSE", htf_bars=htf_bars, capital=capital,
        cost_model=cost_model, slippage_bps=slippage_bps, risk_pct=risk_pct, lot_size=1,
        min_trades_for_grade=min_trades_for_grade,
        evaluate_fn=make_evaluator(bench=bench, cost_model=cost_model,
                                   slippage_bps=slippage_bps, min_rr=min_rr))


def walk_forward(strategy, bars, symbol: str, *, bench=None, cost_model: str,
                 capital: float = DEFAULT_CAPITAL, slippage_bps: float = 5.0,
                 htf_bars=None, windows: int = WF_WINDOWS,
                 min_rr: float | None = None) -> WalkForward:
    """Replay each contiguous window of the history separately.

    Every window carries a warm-up prefix of `strategy.min_bars` so its detectors see a
    full lookback — without it the first bars of each window would be evaluated on a
    truncated series and the windows would not be comparable to each other."""
    warm = strategy.min_bars + 20
    usable = len(bars) - warm
    if usable < windows * 60:
        return WalkForward(note=f"only {len(bars)} bars — not enough for {windows} "
                                f"windows of at least 60 evaluable bars each")

    size = usable // windows
    detail: list[dict] = []
    profitable = 0
    for w in range(windows):
        start = warm + w * size
        end = start + size if w < windows - 1 else len(bars)
        # Prefix the warm-up so the window's first signal has its full lookback.
        window_bars = bars[max(0, start - warm):end]
        if len(window_bars) < strategy.min_bars + 30:
            continue
        res = run_backtest(strategy, window_bars, symbol, bench=bench,
                           cost_model=cost_model, capital=capital,
                           slippage_bps=slippage_bps, htf_bars=htf_bars,
                           min_rr=min_rr, min_trades_for_grade=1)
        net = res.overall.net_pnl
        detail.append({
            "window": w + 1,
            "from": window_bars[warm].ts.isoformat() if len(window_bars) > warm else None,
            "to": window_bars[-1].ts.isoformat(),
            "trades": res.overall.trades, "net_pnl": net,
            "win_rate": res.overall.win_rate,
            "profit_factor": res.overall.profit_factor,
            "max_dd_pct": res.overall.max_drawdown_pct,
        })
        if net > 0:
            profitable += 1

    measured = [d for d in detail if d["trades"] > 0]
    if not measured:
        return WalkForward(windows=len(detail), detail=detail,
                           note="no window produced a single trade — the strategy is not "
                                "firing, which is a coverage or filter finding, not a "
                                "performance one")
    frac = profitable / len(measured)
    return WalkForward(windows=len(measured), profitable=profitable, fraction=frac,
                       detail=detail,
                       note=f"{profitable} of {len(measured)} windows with trades were "
                            "profitable after costs")


def monte_carlo(trades, capital: float, seed_key: str = "",
                iterations: int = MC_ITERATIONS) -> MonteCarlo:
    """Bootstrap the trade sequence and rebuild the equity path."""
    pnls = [t.net for t in trades]
    if len(pnls) < 10:
        return MonteCarlo(note=f"only {len(pnls)} trades — a bootstrap on this few is "
                               "noise dressed as a distribution")

    rng = random.Random(int(hashlib.sha1(seed_key.encode()).hexdigest()[:8], 16))
    n = len(pnls)
    finals: list[float] = []
    dds: list[float] = []
    ruined = 0
    ruin_level = capital * (1 - MC_RUIN_PCT / 100)

    for _ in range(iterations):
        eq = capital
        peak = capital
        worst = 0.0
        blew_up = False
        for _ in range(n):
            eq += pnls[rng.randrange(n)]
            peak = max(peak, eq)
            if peak > 0:
                worst = max(worst, (peak - eq) / peak * 100)
            if eq <= ruin_level:
                blew_up = True
        finals.append(eq)
        dds.append(worst)
        ruined += 1 if blew_up else 0

    finals.sort()
    dds.sort()

    def pct(seq, q):
        return seq[min(len(seq) - 1, max(0, int(len(seq) * q)))]

    return MonteCarlo(
        iterations=iterations,
        median_final=statistics.median(finals),
        p5_final=pct(finals, 0.05), p95_final=pct(finals, 0.95),
        median_max_dd_pct=statistics.median(dds), p95_max_dd_pct=pct(dds, 0.95),
        prob_of_ruin=ruined / iterations,
        prob_of_loss=sum(1 for f in finals if f < capital) / iterations,
        note=f"{iterations} bootstrapped paths over {n} trades, seeded for reproducibility")


def extended_grade(base_grade: int, base_reasons: list[str], wf: WalkForward | None,
                   mc: MonteCarlo | None, capital: float,
                   feasible_signals: int) -> tuple[int, list[str], str]:
    """The factory's grade, then this desk's two extra hurdles.

    Returns (grade, reasons, status). A strategy that never produced a single feasible
    1:6 setup is not graded at all — it is structurally ineligible, which is a different
    statement from "measured and found wanting", and it gets its own label."""
    reasons = list(base_reasons)

    if feasible_signals <= 0:
        return GRADE_FAILED_RR, [
            f"no setup in the whole history could support a {MIN_RR:.0f}R target — "
            "structural stops, volatility budget, overhead supply or costs ruled every "
            "one of them out"], FAILED_RR_LABEL

    if base_grade <= 2:
        return base_grade, reasons, "rejected" if base_grade == 1 else "weak"

    # Grade 3 is the paper-trading floor and needs nothing more than the factory's bar.
    if base_grade == 3:
        return 3, reasons, "promising"

    if wf is None or wf.windows == 0:
        reasons.append("walk-forward not run — capped at grade 3 until it is")
        return 3, reasons, "promising"

    reasons.append(f"walk-forward: {wf.profitable}/{wf.windows} windows profitable "
                   f"({wf.fraction*100:.0f}%)")

    if base_grade == 5:
        mc_ok = mc is not None and mc.iterations > 0 and mc.p5_final > capital
        if mc is not None and mc.iterations:
            reasons.append(f"Monte Carlo 5th percentile equity "
                           f"{mc.p5_final:,.0f} vs {capital:,.0f} starting, "
                           f"{mc.prob_of_ruin*100:.1f}% of paths hit -{MC_RUIN_PCT:.0f}%")
        if wf.fraction >= WF_PROFITABLE_FOR_5 and mc_ok:
            return 5, reasons, "production candidate"
        if wf.fraction >= WF_PROFITABLE_FOR_4:
            reasons.append("strong in-sample but did not clear the grade-5 robustness bar")
            return 4, reasons, "strong"
        reasons.append("in-sample strength did not persist across forward windows")
        return 3, reasons, "promising"

    # base_grade == 4
    if wf.fraction >= WF_PROFITABLE_FOR_4:
        return 4, reasons, "strong"
    reasons.append("did not hold up across forward windows")
    return 3, reasons, "promising"


__all__ = ["run_backtest", "walk_forward", "monte_carlo", "extended_grade",
           "WalkForward", "MonteCarlo", "WF_WINDOWS", "MC_ITERATIONS",
           "GRADE_FAILED_RR", "FAILED_RR_LABEL"]
