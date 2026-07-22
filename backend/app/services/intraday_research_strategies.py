"""Research catalog — candidate strategies under test, NOT traded by the desk.

WHY THIS IS A SEPARATE MODULE FROM `intraday_strategies.py`
----------------------------------------------------------
That module is the LIVE catalog: the paper desk trades everything in it every cycle.
Adding an unvalidated idea there would put it straight into trading on the strength of
somebody having thought of it. Candidates live here until a backtest earns them a place,
which is the same qualify-before-trading rule the option desks follow.

WHAT THE EVIDENCE SAYS, AND WHY THESE RULES LOOK NOTHING LIKE THE LIVE CATALOG
-----------------------------------------------------------------------------
The live catalog's 16 measurable strategies lost 16/16 on 5y of real NSE history, and the
post-mortem was unambiguous: gross edge ~Rs11/trade against ~Rs132/trade of real charges.
The problem was never the entry logic, it was turnover — they hold 1-5 days, so statutory
costs (delivery STT alone is 0.1% BOTH sides) dwarf the move being captured.

Published evidence on Indian equities points the same way: momentum profitability
"disappears for shorter horizons but remains for longer horizons", with post-cost profits
observed only for ranking/holding periods beyond ~6 months, as turnover falls. NSE's own
Nifty 500 Momentum 50 index scores stocks on 6- and 12-month returns adjusted for daily
volatility, skips the most recent month (short-term reversal), and rebalances twice a
year. George & Hwang's 52-week-high signal earns ~0.65%/month vs ~0.38% for classic
12-1 momentum.

So every family here is deliberately LOW TURNOVER and LONG HOLD: months, not days. That
is the one lever that changes the cost arithmetic, and it is why these are not "intraday"
strategies. A strategy that trades less is the only kind that survived the last test.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
Cross-sectional ranking (buy the top-N ranked names, as the Nifty Momentum 50 does) is
the single best-documented version of this effect, and it is absent because the replay
harness scores ONE SYMBOL AT A TIME — it cannot see the other names on the same bar to
rank against. Implementing it honestly needs a portfolio-level harness, not a per-symbol
one. Everything below is therefore the TIME-SERIES (absolute, own-history) form, which
the per-symbol harness can measure without pretending.

Sources: George & Hwang (52-week high); Moskowitz/Ooi/Pedersen (time-series momentum);
NSE Nifty500 Momentum 50 factsheet methodology.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from app.services.intraday_strategies import Ctx, Signal, StrategySpec
from strategy_service.indicators import sma

TRADING_DAYS_MONTH = 21
TRADING_DAYS_YEAR = 252


def _return_pct(closes: list[float], lookback: int, skip: int) -> Optional[float]:
    """Return over `lookback` bars ending `skip` bars ago.

    `skip` implements the "excluding the most recent month" convention every serious
    momentum construction uses — the latest month tends to REVERSE, so including it
    systematically buys exactly what is about to mean-revert.
    """
    need = lookback + skip + 1
    if len(closes) < need:
        return None
    end = closes[-1 - skip]
    start = closes[-1 - skip - lookback]
    if start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _ann_vol_pct(closes: list[float], lookback: int) -> Optional[float]:
    """Annualized daily-return volatility, the denominator of a risk-adjusted score."""
    window = closes[-(lookback + 1):]
    if len(window) < 20:
        return None
    rets = [
        math.log(window[i] / window[i - 1])
        for i in range(1, len(window))
        if window[i - 1] > 0 and window[i] > 0
    ]
    if len(rets) < 20:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var) * math.sqrt(TRADING_DAYS_YEAR) * 100.0
    return vol if vol > 0 else None


def _trend_ok(closes: list[float], ma_period: int) -> bool:
    """Price above a long moving average that is itself rising.

    A rising-MA condition as well as a price-above one: buying a stock above a MA that is
    still falling is buying a bounce in a downtrend, which is the losing half of momentum.
    """
    if len(closes) < ma_period + TRADING_DAYS_MONTH:
        return False
    ma = sma(closes, ma_period)
    if not ma or ma[-1] <= 0:
        return False
    return closes[-1] > ma[-1] and ma[-1] > ma[-1 - TRADING_DAYS_MONTH]


def _signal(entry: float, atr14: float, spec: StrategySpec, confidence: float,
            rationale: str) -> Optional[Signal]:
    """Wide disaster-stop, wide target, long max-hold.

    These are hold-for-months positions: the exit that matters is the holding-period
    expiry (`max_hold_days`), not a target. The target is set far enough away that it is
    a windfall rather than the plan, and the stop is wide enough that ordinary volatility
    cannot shake the position out — a tight stop on a 6-month thesis just converts it back
    into the high-turnover strategy that already failed.
    """
    stop = entry - spec.params["stop_atr"] * atr14
    if stop <= 0 or atr14 <= 0:
        return None
    return Signal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14,
        stoploss=stop, confidence=confidence, rationale=rationale,
    )


def ts_momentum_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Time-series (absolute) momentum: the stock's own trailing return, skipping the
    most recent month, gated by a rising long-term trend. Hold for months."""
    closes = [b.close for b in ctx["bars"]]
    mom = _return_pct(closes, spec.params["lookback"], spec.params["skip"])
    if mom is None or mom < spec.params["min_return_pct"]:
        return None
    if not _trend_ok(closes, spec.params["ma_period"]):
        return None
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=min(0.85, 0.45 + mom / 100),
        rationale=(
            f"Time-series momentum: +{mom:.1f}% over {spec.params['lookback']}d "
            f"(skipping the last {spec.params['skip']}d) with price above a rising "
            f"{spec.params['ma_period']}DMA — held up to {spec.max_hold_days}d"
        ),
    )


def near_52w_high_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """George & Hwang: proximity to the 52-week high predicts returns better than raw
    momentum. Buy what is already near its high, not what has merely risen a lot."""
    bars = ctx["bars"]
    if len(bars) < TRADING_DAYS_YEAR:
        return None
    closes = [b.close for b in bars]
    high_52w = max(b.high for b in bars[-TRADING_DAYS_YEAR:])
    if high_52w <= 0:
        return None
    ratio = closes[-1] / high_52w
    if ratio < spec.params["min_ratio"]:
        return None
    mom = _return_pct(closes, spec.params["lookback"], spec.params["skip"])
    if mom is None or mom <= 0:
        return None  # near a high only counts inside an uptrend, not after a long base
    if not _trend_ok(closes, spec.params["ma_period"]):
        return None
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=min(0.85, 0.4 + ratio / 3),
        rationale=(
            f"52-week-high proximity: trading at {ratio * 100:.1f}% of its 52w high "
            f"({high_52w:.0f}) with +{mom:.1f}% trailing momentum — held up to "
            f"{spec.max_hold_days}d"
        ),
    )


def risk_adj_momentum_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """NSE's Nifty500-Momentum-50 construction: trailing return divided by annualized
    volatility, so a steady climber outranks a violent one with the same total return."""
    closes = [b.close for b in ctx["bars"]]
    mom = _return_pct(closes, spec.params["lookback"], spec.params["skip"])
    vol = _ann_vol_pct(closes, spec.params["lookback"])
    if mom is None or vol is None or mom <= 0:
        return None
    score = mom / vol
    if score < spec.params["min_score"]:
        return None
    if not _trend_ok(closes, spec.params["ma_period"]):
        return None
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=min(0.85, 0.4 + score / 4),
        rationale=(
            f"Risk-adjusted momentum: +{mom:.1f}% over {spec.params['lookback']}d against "
            f"{vol:.0f}% annualized vol (score {score:.2f}) — held up to {spec.max_hold_days}d"
        ),
    )


def dual_momentum_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Absolute momentum on two horizons at once: a stock must be up over BOTH a long and
    a short lookback. Agreement across horizons filters out one-off spikes that a single
    lookback reads as trend."""
    closes = [b.close for b in ctx["bars"]]
    slow = _return_pct(closes, spec.params["lookback"], spec.params["skip"])
    fast = _return_pct(closes, spec.params["fast_lookback"], spec.params["skip"])
    if slow is None or fast is None:
        return None
    if slow < spec.params["min_return_pct"] or fast <= 0:
        return None
    if not _trend_ok(closes, spec.params["ma_period"]):
        return None
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=min(0.85, 0.45 + slow / 120),
        rationale=(
            f"Dual-horizon momentum: +{slow:.1f}% over {spec.params['lookback']}d and "
            f"+{fast:.1f}% over {spec.params['fast_lookback']}d, above a rising "
            f"{spec.params['ma_period']}DMA — held up to {spec.max_hold_days}d"
        ),
    )


def _price_above_ma(closes: list[float], ma_period: int) -> bool:
    """Weaker than `_trend_ok`: price above a long MA, without requiring the MA itself to
    be rising. Used by families whose whole point is NOT trend strength (low-vol,
    reversal) — demanding a rising MA on top would just re-test momentum with different
    weights rather than measure a genuinely different factor."""
    if len(closes) < ma_period:
        return False
    ma = sma(closes, ma_period)
    return bool(ma) and ma[-1] > 0 and closes[-1] > ma[-1]


def ts_momentum_score(bars: list, params: dict) -> Optional[float]:
    """Cross-sectional companion to `ts_momentum_family`: the RANKING score (trailing
    return) instead of a single-name Signal, for use by a portfolio harness that buys the
    top-K names across the whole universe rather than trading each name in isolation.

    This is the construction the evidence actually describes: NSE's own Nifty500
    Momentum 50 buys a BASKET of top-ranked names, which is what diversifies away the
    idiosyncratic (and, in a systemic event like 2020, the correlated) drawdown a single
    name carries alone. The per-symbol family functions above cannot express that — they
    decide per-symbol, with no notion of "top-K across the universe" — so a harness that
    only replays one symbol at a time will always overstate concentrated-position risk.
    Returns None when the name is not eligible at all (fails its trend filter)."""
    closes = [b.close for b in bars]
    mom = _return_pct(closes, params["lookback"], params["skip"])
    if mom is None or mom < params["min_return_pct"]:
        return None
    if not _trend_ok(closes, params["ma_period"]):
        return None
    return mom


def near_52w_high_score(bars: list, params: dict) -> Optional[float]:
    if len(bars) < TRADING_DAYS_YEAR:
        return None
    closes = [b.close for b in bars]
    high_52w = max(b.high for b in bars[-TRADING_DAYS_YEAR:])
    if high_52w <= 0:
        return None
    ratio = closes[-1] / high_52w
    if ratio < params["min_ratio"]:
        return None
    mom = _return_pct(closes, params["lookback"], params["skip"])
    if mom is None or mom <= 0:
        return None
    if not _trend_ok(closes, params["ma_period"]):
        return None
    return ratio


def risk_adj_momentum_score(bars: list, params: dict) -> Optional[float]:
    closes = [b.close for b in bars]
    mom = _return_pct(closes, params["lookback"], params["skip"])
    vol = _ann_vol_pct(closes, params["lookback"])
    if mom is None or vol is None or mom <= 0:
        return None
    score = mom / vol
    if score < params["min_score"]:
        return None
    if not _trend_ok(closes, params["ma_period"]):
        return None
    return score


def dual_momentum_score(bars: list, params: dict) -> Optional[float]:
    closes = [b.close for b in bars]
    slow = _return_pct(closes, params["lookback"], params["skip"])
    fast = _return_pct(closes, params["fast_lookback"], params["skip"])
    if slow is None or fast is None:
        return None
    if slow < params["min_return_pct"] or fast <= 0:
        return None
    if not _trend_ok(closes, params["ma_period"]):
        return None
    return slow


def low_vol_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Betting-Against-Beta / low-volatility anomaly: the least volatile names earn
    higher RISK-ADJUSTED returns than CAPM implies, evidenced specifically in India (BAB
    "dominates the returns on size, value and momentum factors" there). Unlike the
    momentum families, this is deliberately NOT gated on trend strength — the effect is
    about volatility, not direction — only a basic price-above-MA filter to avoid buying
    a quiet stock in a structural decline."""
    closes = [b.close for b in ctx["bars"]]
    vol = _ann_vol_pct(closes, spec.params["lookback"])
    if vol is None or vol > spec.params["max_vol_pct"]:
        return None
    if not _price_above_ma(closes, spec.params["ma_period"]):
        return None
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=min(0.8, 0.9 - vol / 100),
        rationale=(
            f"Low-volatility: {vol:.0f}% annualized vol (<= {spec.params['max_vol_pct']:.0f}%) "
            f"with price above its {spec.params['ma_period']}DMA — held up to "
            f"{spec.max_hold_days}d (BAB anomaly, evidenced in Indian equities)"
        ),
    )


def relative_strength_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Relative strength vs the benchmark — the mechanic behind every sector-rotation
    approach (buy what is beating the index, not just what is rising in absolute terms).
    Needs `ctx["benchmark_closes"]` aligned 1:1 with `ctx["bars"]`; skipped honestly when
    that alignment isn't available rather than approximated."""
    bench = ctx.get("benchmark_closes")
    closes = [b.close for b in ctx["bars"]]
    if not bench or len(bench) != len(closes):
        return None
    stock_ret = _return_pct(closes, spec.params["lookback"], spec.params["skip"])
    bench_ret = _return_pct(bench, spec.params["lookback"], spec.params["skip"])
    if stock_ret is None or bench_ret is None:
        return None
    excess = stock_ret - bench_ret
    if excess < spec.params["min_excess_pct"]:
        return None
    if not _price_above_ma(closes, spec.params["ma_period"]):
        return None
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=min(0.85, 0.4 + excess / 60),
        rationale=(
            f"Relative strength: +{stock_ret:.1f}% vs benchmark's {bench_ret:.1f}% over "
            f"{spec.params['lookback']}d ({excess:+.1f}% excess) — held up to "
            f"{spec.max_hold_days}d"
        ),
    )


def long_reversal_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """De Bondt-Thaler long-horizon overreaction: 3-5yr LOSERS tend to outperform 3-5yr
    WINNERS over the following years. Evidence has weakened in more recent decades (a
    post-2000 replication found the winner/loser return differential "minimal"), so this
    is tested honestly rather than assumed — the gate decides, not the citation. A
    stabilization filter (the recent slide has to have flattened) guards against buying a
    name still actively falling, which is not what the anomaly describes."""
    closes = [b.close for b in ctx["bars"]]
    long_ret = _return_pct(closes, spec.params["lookback"], spec.params["skip"])
    if long_ret is None or long_ret > spec.params["max_return_pct"]:
        return None  # only the laggards, not merely "not a winner"
    recent_ret = _return_pct(closes, spec.params["stabilize_lookback"], 0)
    if recent_ret is None or recent_ret < spec.params["min_recent_pct"]:
        return None  # still actively falling — not a stabilized loser yet
    return _signal(
        closes[-1], ctx["atr14"], spec,
        confidence=0.5,
        rationale=(
            f"Long-horizon reversal: {long_ret:.1f}% over {spec.params['lookback']}d "
            f"(<= {spec.params['max_return_pct']:.0f}%, a multi-year laggard) with the "
            f"recent {spec.params['stabilize_lookback']}d slide stabilizing "
            f"({recent_ret:+.1f}%) — held up to {spec.max_hold_days}d"
        ),
    )


def low_vol_score(bars: list, params: dict) -> Optional[float]:
    closes = [b.close for b in bars]
    vol = _ann_vol_pct(closes, params["lookback"])
    if vol is None or vol > params["max_vol_pct"]:
        return None
    if not _price_above_ma(closes, params["ma_period"]):
        return None
    return -vol  # lower vol => higher score => ranked first


def relative_strength_score(bars: list, params: dict, bench_closes: list[float]) -> Optional[float]:
    closes = [b.close for b in bars]
    if len(bench_closes) != len(closes):
        return None
    stock_ret = _return_pct(closes, params["lookback"], params["skip"])
    bench_ret = _return_pct(bench_closes, params["lookback"], params["skip"])
    if stock_ret is None or bench_ret is None:
        return None
    excess = stock_ret - bench_ret
    if excess < params["min_excess_pct"]:
        return None
    if not _price_above_ma(closes, params["ma_period"]):
        return None
    return excess


def long_reversal_score(bars: list, params: dict) -> Optional[float]:
    closes = [b.close for b in bars]
    long_ret = _return_pct(closes, params["lookback"], params["skip"])
    if long_ret is None or long_ret > params["max_return_pct"]:
        return None
    recent_ret = _return_pct(closes, params["stabilize_lookback"], 0)
    if recent_ret is None or recent_ret < params["min_recent_pct"]:
        return None
    return -long_ret  # the worst long-run performers rank first


PORTFOLIO_SCORE_FUNCS: dict[str, Callable[[list, dict], Optional[float]]] = {
    "ts_momentum": ts_momentum_score,
    "near_52w_high": near_52w_high_score,
    "risk_adj_momentum": risk_adj_momentum_score,
    "dual_momentum": dual_momentum_score,
    "low_vol": low_vol_score,
    "long_reversal": long_reversal_score,
    # "relative_strength" deliberately absent: relative_strength_score takes an extra
    # `bench_closes` argument (it must compare against a benchmark series), so it does
    # not fit this dict's (bars, params) -> score shape. Callers that need it call
    # relative_strength_score directly.
}


RESEARCH_FAMILY_FUNCS: dict[str, Callable[[StrategySpec, str, Ctx], Optional[Signal]]] = {
    "ts_momentum": ts_momentum_family,
    "near_52w_high": near_52w_high_family,
    "risk_adj_momentum": risk_adj_momentum_family,
    "dual_momentum": dual_momentum_family,
    "low_vol": low_vol_family,
    "relative_strength": relative_strength_family,
    "long_reversal": long_reversal_family,
}


def evaluate_research(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    fn = RESEARCH_FAMILY_FUNCS.get(spec.family)
    if fn is None:
        return None
    try:
        return fn(spec, symbol, ctx)
    except Exception:
        return None


def _build_catalog() -> list[StrategySpec]:
    """A deliberately MODEST grid.

    Spraying hundreds of parameter combinations at a fixed history and keeping whatever
    clears the gate is how a backtest manufactures winners that do not exist. The grid
    below varies only the parameters the literature actually identifies as meaningful —
    lookback (6m vs 12m), holding period, and the strength threshold — and the survivors
    still have to clear an out-of-sample split afterwards.
    """
    specs: list[StrategySpec] = []
    n = 0

    def add(name, category, rationale, hold_days, risk_pct, family, params):
        nonlocal n
        n += 1
        specs.append(StrategySpec(
            strategy_id=f"research_{n:03d}", name=name, category=category,
            timeframe="1d", rationale=rationale, max_hold_days=hold_days,
            risk_pct=risk_pct, family=family, params=params,
        ))

    # --- time-series momentum: 6m/12m lookback x 3m/6m/12m hold x 2 thresholds ---
    for lookback, lb_label in ((126, "6m"), (252, "12m")):
        for hold, hold_label in ((63, "3m"), (126, "6m"), (252, "12m")):
            for min_ret in (10.0, 25.0):
                add(
                    f"TS Momentum {lb_label}/{hold_label} >{min_ret:.0f}%", "momentum",
                    f"Up more than {min_ret:.0f}% over {lb_label} (excluding the last month) "
                    f"and above a rising 200DMA; held {hold_label}.",
                    hold, 0.35, "ts_momentum",
                    {"lookback": lookback, "skip": TRADING_DAYS_MONTH,
                     "min_return_pct": min_ret, "ma_period": 200,
                     "stop_atr": 4.0, "target_atr": 12.0},
                )

    # --- 52-week-high proximity: 2 ratios x 3 holds ---
    for ratio in (0.90, 0.95):
        for hold, hold_label in ((63, "3m"), (126, "6m"), (252, "12m")):
            add(
                f"52W-High Proximity {ratio:.0%} /{hold_label}", "momentum",
                f"Trading within {(1 - ratio) * 100:.0f}% of its 52-week high with positive "
                f"trailing momentum; held {hold_label}.",
                hold, 0.35, "near_52w_high",
                {"min_ratio": ratio, "lookback": 252, "skip": TRADING_DAYS_MONTH,
                 "ma_period": 200, "stop_atr": 4.0, "target_atr": 12.0},
            )

    # --- risk-adjusted momentum (NSE momentum-score style): 2 lookbacks x 3 holds ---
    for lookback, lb_label in ((126, "6m"), (252, "12m")):
        for hold, hold_label in ((126, "6m"), (252, "12m")):
            for min_score in (0.5, 1.0):
                add(
                    f"Risk-Adj Momentum {lb_label}/{hold_label} >{min_score:.1f}", "momentum",
                    f"{lb_label} return divided by annualized volatility above {min_score:.1f}, "
                    f"above a rising 200DMA; held {hold_label}.",
                    hold, 0.35, "risk_adj_momentum",
                    {"lookback": lookback, "skip": TRADING_DAYS_MONTH,
                     "min_score": min_score, "ma_period": 200,
                     "stop_atr": 4.0, "target_atr": 12.0},
                )

    # --- dual-horizon agreement: 2 holds x 2 thresholds ---
    for hold, hold_label in ((126, "6m"), (252, "12m")):
        for min_ret in (10.0, 25.0):
            add(
                f"Dual-Horizon Momentum {hold_label} >{min_ret:.0f}%", "momentum",
                f"Up over both 12m and 3m (excluding the last month) by more than "
                f"{min_ret:.0f}%, above a rising 200DMA; held {hold_label}.",
                hold, 0.35, "dual_momentum",
                {"lookback": 252, "fast_lookback": 63, "skip": TRADING_DAYS_MONTH,
                 "min_return_pct": min_ret, "ma_period": 200,
                 "stop_atr": 4.0, "target_atr": 12.0},
            )

    # --- low-volatility (BAB): 2 lookbacks x 2 vol caps x 2 holds ---
    for lookback, lb_label in ((126, "6m"), (252, "12m")):
        for max_vol in (25.0, 35.0):
            for hold, hold_label in ((126, "6m"), (252, "12m")):
                add(
                    f"Low-Vol {lb_label} <{max_vol:.0f}% /{hold_label}", "low_volatility",
                    f"Annualized volatility over {lb_label} below {max_vol:.0f}%, price above "
                    f"its 200DMA; held {hold_label}. Betting-against-beta anomaly.",
                    hold, 0.35, "low_vol",
                    {"lookback": lookback, "max_vol_pct": max_vol, "ma_period": 200,
                     "stop_atr": 4.0, "target_atr": 10.0},
                )

    # --- relative strength vs benchmark: 2 lookbacks x 2 excess thresholds x 2 holds ---
    for lookback, lb_label in ((126, "6m"), (252, "12m")):
        for min_excess in (5.0, 15.0):
            for hold, hold_label in ((126, "6m"), (252, "12m")):
                add(
                    f"Relative Strength {lb_label} >{min_excess:.0f}% /{hold_label}", "sector_rotation",
                    f"Beating the benchmark by more than {min_excess:.0f}% over {lb_label} "
                    f"(excluding the last month), above its 200DMA; held {hold_label}.",
                    hold, 0.35, "relative_strength",
                    {"lookback": lookback, "skip": TRADING_DAYS_MONTH, "min_excess_pct": min_excess,
                     "ma_period": 200, "stop_atr": 4.0, "target_atr": 12.0},
                )

    # --- long-horizon reversal (De Bondt-Thaler): 2 lookbacks x 2 thresholds, 12m hold ---
    # Held only 12m (not shorter): the anomaly is explicitly a MULTI-YEAR-horizon effect;
    # a short hold would not give a multi-year overreaction time to correct at all.
    for lookback, lb_label in ((756, "3y"), (1260, "5y")):
        for max_ret in (-20.0, 0.0):
            add(
                f"Long Reversal {lb_label} <{max_ret:.0f}%", "long_reversal",
                f"Among the worst performers over the trailing {lb_label} (return below "
                f"{max_ret:.0f}%) whose recent 3-month slide has stabilized; held 12m. "
                "Evidence has weakened in recent decades — tested, not assumed.",
                252, 0.35, "long_reversal",
                {"lookback": lookback, "skip": TRADING_DAYS_MONTH, "max_return_pct": max_ret,
                 "stabilize_lookback": 63, "min_recent_pct": -10.0,
                 "stop_atr": 4.0, "target_atr": 10.0},
            )

    return specs


RESEARCH_CATALOG: list[StrategySpec] = _build_catalog()
RESEARCH_BY_ID: dict[str, StrategySpec] = {s.strategy_id: s for s in RESEARCH_CATALOG}
