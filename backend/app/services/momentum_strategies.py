"""Momentum Trading desk — strategy catalog.

Momentum is the "strength attracts strength" trade: buy what is already rising and
ride it. This module holds the catalog; `momentum_engine.py` runs it as a fee-honest
₹10,000-per-strategy paper desk on the live Angel One feed.

WHAT IS BUILT HERE, AND WHY THESE SEVEN FAMILIES
------------------------------------------------
Six of the families are the setups Indian momentum desks actually run (52-week-high
breakout, relative strength vs Nifty, opening-range breakout, moving-average stack,
sector rotation, volume+price-action breakout). The seventh is the published index
rule itself:

  `risk_adjusted` implements the **Nifty200 Momentum 30 normalised momentum score** —
  6-month and 12-month price return, each divided by the stock's annualised daily-return
  volatility, z-scored across the universe, averaged, then mapped through
  `1+z if z>=0 else 1/(1-z)`. That is the same construction NSE rebalances a real index
  on twice a year, so it is the one family here with a live, investable benchmark.

Cross-sectional families (relative_strength, risk_adjusted, sector_rotation) are ranked
across the whole scanned universe each cycle — a stock qualifies by being in the top
decile/quintile of its measure, not by clearing an absolute threshold. That is what
"momentum" means in the literature (Jegadeesh-Titman is a cross-sectional sort), and it
is why `Ctx` carries a `uni` table of universe-wide percentiles rather than each family
recomputing from bars.

DATA REALITY (same honesty convention as call_engine.py / intraday_strategies.py)
---------------------------------------------------------------------------------
This backend keeps **daily** bars for equities; true 1m/5m history is not backfilled.
So the ORB family cannot mark a literal 09:15-09:30 range. It uses the live day OHLC
from a single Angel quote — how far price has extended above today's OPEN while still
printing new day highs — which is the same proxy `intraday_strategies.orb_family` and
call_engine's GAP-GO/PDH setups already use here. It is labelled as a proxy in every
rationale string, and every quote-dependent family returns None (no trade) when no live
quote is available rather than inventing an intraday print.

TRAILING STOPS ARE PART OF THE SIGNAL
--------------------------------------
Momentum's edge is asymmetry, not accuracy — the published Indian ORB record is a ~49%
win rate with a 1.23 profit factor over eight years, i.e. it wins by letting winners run.
So a signal carries a `trail_mode`/`trail_param` and the engine ratchets the stop up as
price makes new highs. A fixed target alone would cap exactly the tail this desk exists
to capture.

Long-only. These are cash equities and 6 of the 7 families are structurally long ideas;
shorting them intraday-only would test a different strategy than the one described.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from strategy_service.indicators import adx, donchian, ema, rsi, sma
from tradingai_shared.domain import Bar

# --------------------------------------------------------------------------------
# Signal + spec contracts
# --------------------------------------------------------------------------------


@dataclass
class MomentumSignal:
    side: str  # always "BUY" — long-only cash equities
    entry: float
    target: float
    stoploss: float
    confidence: float
    rationale: str
    trail_mode: str = "none"  # none | pct | ema | chandelier
    trail_param: float = 0.0  # pct: fraction below running high; ema: period; chandelier: ATR mult


@dataclass
class MomentumSpec:
    strategy_id: str
    name: str
    style: str  # breakout_52w | relative_strength | risk_adjusted | ma_stack | orb | sector_rotation | volume_breakout
    horizon: str  # intraday | swing | positional
    timeframe: str  # human label
    rationale: str
    max_hold_days: int  # 0 = must square off same day (EOD 15:15 IST)
    family: str
    params: dict = field(default_factory=dict)

    @property
    def needs_quote(self) -> bool:
        """Intraday families are meaningless without today's live day OHLC."""
        return self.horizon == "intraday"

    @property
    def is_intraday(self) -> bool:
        return self.max_hold_days == 0


@dataclass
class SymbolMomentum:
    """Everything the cross-sectional families need about one symbol, plus its
    percentile rank inside the scanned universe. Built once per cycle by the engine
    (`build_universe`) so 37 strategies never recompute the same returns 37 times."""

    symbol: str
    close: float
    ret_21: Optional[float] = None
    ret_63: Optional[float] = None
    ret_126: Optional[float] = None
    ret_252: Optional[float] = None
    vol_ann: Optional[float] = None  # annualised stdev of daily returns (252d)
    rs_63: Optional[float] = None  # excess return vs benchmark, percentage points
    rs_126: Optional[float] = None
    rs_252: Optional[float] = None
    norm_score: Optional[float] = None  # NSE normalised momentum score (6M+12M)
    norm_score_6m: Optional[float] = None
    norm_score_12m: Optional[float] = None
    high_52w: Optional[float] = None
    dist_52w: Optional[float] = None  # close / 52-week high, 1.0 = at the high
    # percentiles across the scanned universe, 0..1 where 1 = strongest
    pct_norm: Optional[float] = None
    pct_norm_6m: Optional[float] = None
    pct_norm_12m: Optional[float] = None
    pct_rs_63: Optional[float] = None
    pct_rs_126: Optional[float] = None
    pct_rs_252: Optional[float] = None
    sector: Optional[str] = None
    sector_rank: Optional[int] = None  # 1 = strongest sector this cycle
    sector_count: int = 0
    rank_in_sector: Optional[int] = None  # 1 = strongest name inside its sector


Ctx = dict
"""{"bars": list[Bar], "atr14": float, "quote": dict|None, "prev_bar": Bar,
     "uni": SymbolMomentum}"""


# --------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------


def _quote_ohlc(ctx: Ctx) -> Optional[tuple[float, float, float, float, float]]:
    """(day_open, day_high, day_low, ltp, day_volume) from the live quote, or None when
    there is no live quote — callers must skip honestly rather than guess an intraday
    high/low from a stale daily bar."""
    q = ctx.get("quote")
    if not q:
        return None
    ohlc = q.get("ohlc") or {}
    day_open = float(ohlc.get("open") or 0)
    day_high = float(ohlc.get("high") or 0)
    day_low = float(ohlc.get("low") or 0)
    ltp = float(q.get("last_price") or 0)
    vol = float(q.get("volume") or 0)
    if day_open <= 0 or ltp <= 0:
        return None
    return day_open, day_high, day_low, ltp, vol


def _entry_price(ctx: Ctx) -> float:
    """The live LTP when a quote is available, else the last daily close. Swing and
    positional families are daily-bar signals and are allowed to enter off the close
    (that is how a real end-of-day momentum system fills); only the intraday family
    strictly requires the live print."""
    o = _quote_ohlc(ctx)
    if o is not None:
        return o[3]
    return ctx["bars"][-1].close


def _avg_volume(bars: list[Bar], n: int = 20) -> float:
    rows = bars[-n:]
    return sum(b.volume for b in rows) / max(len(rows), 1)


def _today_volume(ctx: Ctx, bars: list[Bar]) -> float:
    """Today's traded volume: the live quote's running day volume when present, else
    the last daily bar's volume."""
    o = _quote_ohlc(ctx)
    if o is not None and o[4] > 0:
        return o[4]
    return float(bars[-1].volume)


def pct_return(bars: list[Bar], lookback: int) -> Optional[float]:
    """Percent price return over `lookback` sessions, or None when history is short."""
    if len(bars) < lookback + 1:
        return None
    past = bars[-(lookback + 1)].close
    if past <= 0:
        return None
    return (bars[-1].close / past - 1.0) * 100.0


def annualised_vol(bars: list[Bar], lookback: int = 252) -> Optional[float]:
    """Annualised standard deviation of daily returns, in percent. This is the
    denominator of the Nifty200 Momentum 30 risk adjustment."""
    rows = bars[-(lookback + 1):]
    if len(rows) < 60:  # under ~3 months the estimate is too noisy to divide by
        return None
    rets = []
    for prev, cur in zip(rows, rows[1:]):
        if prev.close > 0:
            rets.append(cur.close / prev.close - 1.0)
    if len(rets) < 40:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var) * math.sqrt(252) * 100.0
    return vol if vol > 0 else None


def normalise_z(z: float) -> float:
    """NSE / MSCI momentum-score normalisation: `1+z` above the mean, `1/(1-z)` below,
    which keeps every score positive (it is used as a *weight multiplier* in the index)
    while compressing the downside tail."""
    return 1.0 + z if z >= 0 else 1.0 / (1.0 - z)


def _min_bars(spec: MomentumSpec) -> int:
    """Longest lookback the spec can possibly need — the engine skips symbols with
    less history rather than letting a family silently read a truncated series."""
    p = spec.params
    return max(
        p.get("lookback", 0),
        p.get("window", 0),
        p.get("donchian", 0),
        p.get("slow", 0),
        p.get("mid", 0),
        60,
    )


# --------------------------------------------------------------------------------
# Family evaluators — (spec, symbol, ctx) -> MomentumSignal | None
# --------------------------------------------------------------------------------


def breakout_52w_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """52-week-high breakout with volume confirmation.

    The oldest momentum anomaly with a name of its own (George & Hwang's 52-week-high
    effect): nearness to the 52-week high predicts returns better than raw past return,
    because the high is a salient anchor traders under-react to. Two modes: `require_new_high`
    demands today actually take out the 52-week high; otherwise being within `near_pct`
    of it is enough (the consolidation-then-go setup)."""
    bars = ctx["bars"]
    uni: SymbolMomentum = ctx["uni"]
    if uni.high_52w is None or uni.dist_52w is None:
        return None
    entry = _entry_price(ctx)
    atr14 = ctx["atr14"]
    if entry <= 0 or atr14 <= 0:
        return None

    if spec.params["require_new_high"]:
        # A new high must be made on TODAY's action, not merely be the stored high.
        if entry < uni.high_52w * 0.9995:
            return None
    elif uni.dist_52w < spec.params["near_pct"]:
        return None

    vol_mult = spec.params["vol_mult"]
    avg_vol = _avg_volume(bars, 20)
    today_vol = _today_volume(ctx, bars)
    if avg_vol <= 0 or today_vol < avg_vol * vol_mult:
        return None

    stop = entry - spec.params["stop_atr"] * atr14
    if stop <= 0 or stop >= entry:
        return None
    return MomentumSignal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.9, 0.5 + (today_vol / avg_vol - vol_mult) * 0.05),
        rationale=(
            f"52W-high breakout: {entry:.2f} is {uni.dist_52w * 100:.1f}% of the 52-week high "
            f"{uni.high_52w:.2f} on {today_vol / avg_vol:.1f}x the 20-day average volume"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


def relative_strength_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """Relative strength vs the Nifty benchmark — buy what is beating the index.

    Cross-sectional: the stock must both (a) beat the benchmark by `min_excess` points
    over the lookback and (b) sit in the top `1 - min_percentile` of the scanned universe
    on that same measure. Requiring the percentile as well as the absolute excess is what
    stops the whole desk piling in during a broad rally, when *everything* beats a flat
    index by 10%."""
    uni: SymbolMomentum = ctx["uni"]
    lookback = spec.params["lookback"]
    rs = {63: uni.rs_63, 126: uni.rs_126, 252: uni.rs_252}[lookback]
    pctile = {63: uni.pct_rs_63, 126: uni.pct_rs_126, 252: uni.pct_rs_252}[lookback]
    if rs is None or pctile is None:
        return None
    if rs < spec.params["min_excess"] or pctile < spec.params["min_percentile"]:
        return None
    if spec.params.get("require_dual") and (uni.rs_126 is None or uni.rs_252 is None
                                            or uni.rs_126 <= 0 or uni.rs_252 <= 0):
        return None

    entry = _entry_price(ctx)
    atr14 = ctx["atr14"]
    if entry <= 0 or atr14 <= 0:
        return None
    stop = entry - spec.params["stop_atr"] * atr14
    if stop <= 0 or stop >= entry:
        return None
    months = lookback // 21
    return MomentumSignal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.9, 0.4 + pctile * 0.5),
        rationale=(
            f"Relative strength {months}M: beat the benchmark by {rs:+.1f} points and ranks in the "
            f"top {(1 - pctile) * 100:.0f}% of the scanned universe"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


def risk_adjusted_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """The Nifty200 Momentum 30 normalised momentum score.

    NSE ranks its momentum index on 6-month and 12-month price return divided by the
    stock's own daily-return volatility, z-scored across the universe. Dividing by
    volatility is the point: it stops the screen filling with the jumpiest small-caps,
    whose raw return is large only because their risk is. `leg` selects the blend
    (both / 6m only / 12m only) so the desk can measure whether the index's own 50-50
    combination beats either half on its own."""
    uni: SymbolMomentum = ctx["uni"]
    leg = spec.params["leg"]
    pctile = {"both": uni.pct_norm, "6m": uni.pct_norm_6m, "12m": uni.pct_norm_12m}[leg]
    score = {"both": uni.norm_score, "6m": uni.norm_score_6m, "12m": uni.norm_score_12m}[leg]
    if pctile is None or score is None or pctile < spec.params["min_percentile"]:
        return None

    entry = _entry_price(ctx)
    atr14 = ctx["atr14"]
    if entry <= 0 or atr14 <= 0:
        return None
    stop = entry - spec.params["stop_atr"] * atr14
    if stop <= 0 or stop >= entry:
        return None
    leg_label = {"both": "6M+12M", "6m": "6M", "12m": "12M"}[leg]
    return MomentumSignal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.9, 0.4 + pctile * 0.5),
        rationale=(
            f"NSE normalised momentum score ({leg_label}, volatility-adjusted) = {score:.2f}, "
            f"top {(1 - pctile) * 100:.0f}% of the scanned universe"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


def ma_stack_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """Stacked moving averages — price > fast EMA > mid EMA (> slow SMA when required).

    The swing trader's default momentum filter, and the one the user's brief describes:
    enter while the stack is bullish, exit when price closes back below the fast EMA
    (handled by the engine as `trail_mode="ema"`). Optional RSI and ADX confirmations —
    RSI > 60 is treated as *momentum confirmation*, not an overbought exit, which is the
    distinction that separates trend traders from oscillator traders."""
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    fast_p, mid_p, slow_p = spec.params["fast"], spec.params["mid"], spec.params["slow"]
    fast = ema(closes, fast_p)
    mid = ema(closes, mid_p)
    if not fast or not mid:
        return None
    entry = _entry_price(ctx)
    if entry <= 0:
        return None
    if not (entry > fast[-1] > mid[-1]):
        return None

    if spec.params["require_slow"]:
        slow = sma(closes, slow_p)
        if not slow or mid[-1] <= slow[-1]:
            return None

    rsi_min = spec.params.get("rsi_min")
    rsi_now = None
    if rsi_min is not None:
        series = rsi(closes, 14)
        if not series or series[-1] < rsi_min:
            return None
        rsi_now = series[-1]

    adx_min = spec.params.get("adx_min")
    adx_now = None
    if adx_min is not None:
        adx_series, _, _ = adx(bars, 14)
        if not adx_series or adx_series[-1] < adx_min:
            return None
        adx_now = adx_series[-1]

    atr14 = ctx["atr14"]
    if atr14 <= 0:
        return None
    stop = max(entry - spec.params["stop_atr"] * atr14, mid[-1] * 0.995)
    if stop <= 0 or stop >= entry:
        return None
    extras = []
    if rsi_now is not None:
        extras.append(f"RSI {rsi_now:.0f}")
    if adx_now is not None:
        extras.append(f"ADX {adx_now:.0f}")
    suffix = f" ({', '.join(extras)})" if extras else ""
    return MomentumSignal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.6,
        rationale=(
            f"MA stack: price {entry:.2f} > {fast_p} EMA {fast[-1]:.2f} > {mid_p} EMA {mid[-1]:.2f}"
            f"{suffix} — trend intact, trail the {fast_p} EMA"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


def orb_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """Opening Range Breakout — intraday, squared off the same session.

    PROXY, stated plainly: with no intraday bars stored, the "opening range" is
    approximated by how far price has extended above TODAY'S OPEN while still printing
    new day highs. A tighter `range_pct` fires early (15-minute-style), a wider one waits
    for more range to build (60-minute-style). The published Indian record for ORB is a
    sub-50% win rate carried by asymmetry, so the stop is the day's low (or a half-ATR,
    whichever is tighter) and the target is a multiple of ATR, never 1:1."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, day_high, day_low, ltp, day_vol = o
    range_pct = spec.params["range_pct"]
    if ltp < day_open * (1 + range_pct / 100.0):
        return None
    if day_high <= 0 or ltp < day_high * 0.999:  # only while making new day highs
        return None

    bars = ctx["bars"]
    avg_vol = _avg_volume(bars, 20)
    vol_mult = spec.params["vol_mult"]
    if vol_mult > 0 and (avg_vol <= 0 or day_vol < avg_vol * vol_mult):
        return None

    min_pctile = spec.params.get("min_rs_percentile")
    if min_pctile is not None:
        pctile = ctx["uni"].pct_rs_63
        if pctile is None or pctile < min_pctile:
            return None

    atr14 = ctx["atr14"]
    if atr14 <= 0:
        return None
    stop = max(day_low, ltp - 0.5 * atr14)
    if stop <= 0 or stop >= ltp:
        return None
    return MomentumSignal(
        side="BUY", entry=ltp,
        target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.85, 0.4 + range_pct / 3),
        rationale=(
            f"ORB proxy ({range_pct:.2f}% above the day's open {day_open:.2f}, no intraday bars "
            f"stored): still making new day highs on {day_vol / avg_vol:.1f}x average volume"
            if avg_vol > 0 else
            f"ORB proxy ({range_pct:.2f}% above the day's open {day_open:.2f}): making new day highs"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


def sector_rotation_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """Sector rotation — find the strongest sectors, then the strongest names inside them.

    Indian equities rotate in sector blocks (IT → Banks → PSU → Defence), so a stock's
    sector explains a large share of its move. The engine ranks sectors by the average
    lookback return of their members, then this family takes the top `top_names` inside
    the top `top_sectors`. Symbols whose sector is unknown are skipped rather than lumped
    into an "Unclassified" bucket that would then be ranked as if it were a real sector."""
    uni: SymbolMomentum = ctx["uni"]
    if uni.sector is None or uni.sector_rank is None or uni.rank_in_sector is None:
        return None
    if uni.sector_rank > spec.params["top_sectors"]:
        return None
    if uni.rank_in_sector > spec.params["top_names"]:
        return None

    entry = _entry_price(ctx)
    atr14 = ctx["atr14"]
    if entry <= 0 or atr14 <= 0:
        return None
    stop = entry - spec.params["stop_atr"] * atr14
    if stop <= 0 or stop >= entry:
        return None
    return MomentumSignal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.6,
        rationale=(
            f"Sector rotation: {uni.sector} ranks #{uni.sector_rank} of {uni.sector_count} sectors on "
            f"{spec.params['lookback'] // 21}M return, and {symbol} is #{uni.rank_in_sector} inside it"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


def volume_breakout_family(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    """Price clearing an N-day Donchian resistance on a volume surge.

    The generic "breakout above key resistance on 2-3x volume" setup, made testable by
    defining resistance as the highest high of the last `donchian` sessions (excluding
    today, so the level is not the very bar being tested). Volume is the filter that
    separates a real breakout from a drift through an old level."""
    bars = ctx["bars"]
    period = spec.params["donchian"]
    if len(bars) < period + 2:
        return None
    upper, _ = donchian(bars[:-1], period)  # exclude today so the level pre-dates the break
    if not upper:
        return None
    resistance = upper[-1]
    entry = _entry_price(ctx)
    if entry <= 0 or entry <= resistance:
        return None

    avg_vol = _avg_volume(bars, 20)
    today_vol = _today_volume(ctx, bars)
    if avg_vol <= 0 or today_vol < avg_vol * spec.params["vol_mult"]:
        return None

    rsi_min = spec.params.get("rsi_min")
    if rsi_min is not None:
        series = rsi([b.close for b in bars], 14)
        if not series or series[-1] < rsi_min:
            return None

    atr14 = ctx["atr14"]
    if atr14 <= 0:
        return None
    # Stop under the broken level — a breakout that loses its own trigger is wrong.
    stop = min(resistance * 0.995, entry - spec.params["stop_atr"] * atr14)
    if stop <= 0 or stop >= entry:
        return None
    return MomentumSignal(
        side="BUY", entry=entry,
        target=entry + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.9, 0.45 + (today_vol / avg_vol) * 0.05),
        rationale=(
            f"Volume breakout: cleared the {period}-day high {resistance:.2f} on "
            f"{today_vol / avg_vol:.1f}x the 20-day average volume"
        ),
        trail_mode=spec.params["trail_mode"], trail_param=spec.params["trail_param"],
    )


FAMILIES: dict[str, Callable[[MomentumSpec, str, Ctx], Optional[MomentumSignal]]] = {
    "breakout_52w": breakout_52w_family,
    "relative_strength": relative_strength_family,
    "risk_adjusted": risk_adjusted_family,
    "ma_stack": ma_stack_family,
    "orb": orb_family,
    "sector_rotation": sector_rotation_family,
    "volume_breakout": volume_breakout_family,
}


def evaluate(spec: MomentumSpec, symbol: str, ctx: Ctx) -> Optional[MomentumSignal]:
    fn = FAMILIES.get(spec.family)
    if fn is None:
        return None
    if len(ctx["bars"]) < _min_bars(spec):
        return None
    try:
        return fn(spec, symbol, ctx)
    except (KeyError, IndexError, ZeroDivisionError, TypeError, ValueError):
        # A malformed/short series must cost one signal, never the whole scan.
        return None


# --------------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------------

STYLE_LABELS = {
    "breakout_52w": "52-Week High Breakout",
    "relative_strength": "Relative Strength vs Nifty",
    "risk_adjusted": "Risk-Adjusted Momentum (NSE)",
    "ma_stack": "Moving-Average Momentum",
    "orb": "Opening Range Breakout",
    "sector_rotation": "Sector Rotation",
    "volume_breakout": "Volume + Price Action",
}


def _build_catalog() -> list[MomentumSpec]:
    specs: list[MomentumSpec] = []

    def add(name, style, horizon, timeframe, rationale, max_hold_days, family, params):
        specs.append(MomentumSpec(
            strategy_id=f"mom_{len(specs) + 1:03d}", name=name, style=style, horizon=horizon,
            timeframe=timeframe, rationale=rationale, max_hold_days=max_hold_days,
            family=family, params=params,
        ))

    # ---- 1. 52-week-high breakout (6) ------------------------------------------
    for label, p in [
        ("New High · 1.5x Vol", dict(require_new_high=True, near_pct=0.0, vol_mult=1.5, target_atr=3.0, stop_atr=1.5, trail_mode="pct", trail_param=0.08)),
        ("New High · 2.5x Vol", dict(require_new_high=True, near_pct=0.0, vol_mult=2.5, target_atr=4.0, stop_atr=1.5, trail_mode="pct", trail_param=0.08)),
        ("Within 1% · 2x Vol", dict(require_new_high=False, near_pct=0.99, vol_mult=2.0, target_atr=3.0, stop_atr=1.5, trail_mode="pct", trail_param=0.10)),
        ("Within 3% · 1.5x Vol", dict(require_new_high=False, near_pct=0.97, vol_mult=1.5, target_atr=2.5, stop_atr=1.5, trail_mode="pct", trail_param=0.10)),
        ("New High · Wide 10% Trail", dict(require_new_high=True, near_pct=0.0, vol_mult=1.5, target_atr=6.0, stop_atr=2.0, trail_mode="pct", trail_param=0.10)),
        ("New High · Chandelier Trail", dict(require_new_high=True, near_pct=0.0, vol_mult=1.5, target_atr=5.0, stop_atr=2.0, trail_mode="chandelier", trail_param=3.0)),
    ]:
        add(f"52W High Breakout · {label}", "breakout_52w", "swing", "1d",
            "Buy strength at the 52-week high with volume confirmation (George-Hwang 52-week-high effect).",
            20, "breakout_52w", p)

    # ---- 2. Relative strength vs Nifty (6) -------------------------------------
    for label, p in [
        ("3M · +10% & Top 20%", dict(lookback=63, min_excess=10.0, min_percentile=0.80, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.10)),
        ("6M · +15% & Top 20%", dict(lookback=126, min_excess=15.0, min_percentile=0.80, target_atr=5.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("12M · +25% & Top 20%", dict(lookback=252, min_excess=25.0, min_percentile=0.80, target_atr=6.0, stop_atr=2.5, trail_mode="pct", trail_param=0.15)),
        ("3M · Top Decile", dict(lookback=63, min_excess=0.0, min_percentile=0.90, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.10)),
        ("6M · Top Decile", dict(lookback=126, min_excess=0.0, min_percentile=0.90, target_atr=5.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("Dual 6M+12M · Top 20%", dict(lookback=126, min_excess=5.0, min_percentile=0.80, require_dual=True, target_atr=5.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
    ]:
        add(f"Relative Strength · {label}", "relative_strength", "positional", "1d",
            "Cross-sectional relative strength vs the Nifty benchmark — the mechanic behind momentum index funds.",
            63, "relative_strength", p)

    # ---- 3. NSE normalised momentum score (5) ----------------------------------
    for label, p in [
        ("Top 10%", dict(leg="both", min_percentile=0.90, target_atr=5.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("Top 20%", dict(leg="both", min_percentile=0.80, target_atr=5.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("Top 30%", dict(leg="both", min_percentile=0.70, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("6M Leg · Top 15%", dict(leg="6m", min_percentile=0.85, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("12M Leg · Top 15%", dict(leg="12m", min_percentile=0.85, target_atr=6.0, stop_atr=2.5, trail_mode="pct", trail_param=0.15)),
    ]:
        add(f"NSE Momentum Score · {label}", "risk_adjusted", "positional", "1d",
            "Nifty200 Momentum 30's own rule: 6M/12M return divided by daily-return volatility, z-scored across the universe.",
            126, "risk_adjusted", p)

    # ---- 4. Moving-average momentum stack (6) ----------------------------------
    for label, p in [
        ("20>50 EMA", dict(fast=20, mid=50, slow=200, require_slow=False, target_atr=3.0, stop_atr=2.0, trail_mode="ema", trail_param=20)),
        ("20>50>200", dict(fast=20, mid=50, slow=200, require_slow=True, target_atr=4.0, stop_atr=2.0, trail_mode="ema", trail_param=20)),
        ("10>30 EMA Fast", dict(fast=10, mid=30, slow=200, require_slow=False, target_atr=2.5, stop_atr=1.5, trail_mode="ema", trail_param=10)),
        ("20>50>200 + RSI60", dict(fast=20, mid=50, slow=200, require_slow=True, rsi_min=60.0, target_atr=4.0, stop_atr=2.0, trail_mode="ema", trail_param=20)),
        ("20>50 + ADX25", dict(fast=20, mid=50, slow=200, require_slow=False, adx_min=25.0, target_atr=4.0, stop_atr=2.0, trail_mode="ema", trail_param=20)),
        ("20>50 + RSI60 + ADX25", dict(fast=20, mid=50, slow=200, require_slow=False, rsi_min=60.0, adx_min=25.0, target_atr=5.0, stop_atr=2.0, trail_mode="ema", trail_param=20)),
    ]:
        add(f"MA Momentum · {label}", "ma_stack", "swing", "1d",
            "Stacked moving averages with RSI>60 read as momentum confirmation, not an overbought exit.",
            20, "ma_stack", p)

    # ---- 5. Opening range breakout (5, intraday) -------------------------------
    for label, p in [
        ("0.50% · 1.5x Vol", dict(range_pct=0.50, vol_mult=1.5, target_atr=1.0, trail_mode="chandelier", trail_param=1.5)),
        ("0.75% · 2x Vol", dict(range_pct=0.75, vol_mult=2.0, target_atr=1.25, trail_mode="chandelier", trail_param=1.5)),
        ("1.00% · 1.5x Vol", dict(range_pct=1.00, vol_mult=1.5, target_atr=1.5, trail_mode="chandelier", trail_param=1.5)),
        ("1.50% Wide Range", dict(range_pct=1.50, vol_mult=0.0, target_atr=2.0, trail_mode="chandelier", trail_param=2.0)),
        ("0.75% · RS Top 30%", dict(range_pct=0.75, vol_mult=1.5, min_rs_percentile=0.70, target_atr=1.5, trail_mode="chandelier", trail_param=1.5)),
    ]:
        add(f"ORB · {label}", "orb", "intraday", "day OHLC proxy",
            "Opening-range-breakout continuation, squared off the same session (proxy: extension above the day's open).",
            0, "orb", p)

    # ---- 6. Sector rotation (4) ------------------------------------------------
    for label, p in [
        ("Top Sector · Top 2 · 3M", dict(top_sectors=1, top_names=2, lookback=63, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.10)),
        ("Top 2 Sectors · Top 3 · 3M", dict(top_sectors=2, top_names=3, lookback=63, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.10)),
        ("Top Sector · Top 3 · 6M", dict(top_sectors=1, top_names=3, lookback=126, target_atr=5.0, stop_atr=2.0, trail_mode="pct", trail_param=0.12)),
        ("Top 3 Sectors · Top 2 · 1M", dict(top_sectors=3, top_names=2, lookback=21, target_atr=3.0, stop_atr=1.5, trail_mode="pct", trail_param=0.08)),
    ]:
        add(f"Sector Rotation · {label}", "sector_rotation", "positional", "1d",
            "Rank sectors by average member return, then take the strongest names inside the strongest sectors.",
            63, "sector_rotation", p)

    # ---- 7. Volume + price-action breakout (5) ---------------------------------
    for label, p in [
        ("20D High · 2x Vol", dict(donchian=20, vol_mult=2.0, target_atr=3.0, stop_atr=1.5, trail_mode="pct", trail_param=0.08)),
        ("20D High · 3x Vol", dict(donchian=20, vol_mult=3.0, target_atr=3.5, stop_atr=1.5, trail_mode="pct", trail_param=0.08)),
        ("50D High · 2x Vol", dict(donchian=50, vol_mult=2.0, target_atr=4.0, stop_atr=2.0, trail_mode="pct", trail_param=0.10)),
        ("55D High · 2.5x Vol", dict(donchian=55, vol_mult=2.5, target_atr=5.0, stop_atr=2.0, trail_mode="chandelier", trail_param=3.0)),
        ("20D High · 2x Vol · RSI60", dict(donchian=20, vol_mult=2.0, rsi_min=60.0, target_atr=3.5, stop_atr=1.5, trail_mode="pct", trail_param=0.08)),
    ]:
        add(f"Volume Breakout · {label}", "volume_breakout", "swing", "1d",
            "Price clearing an N-day resistance on a 2-3x volume surge — the classic results/news breakout.",
            20, "volume_breakout", p)

    return specs


MOMENTUM_CATALOG: list[MomentumSpec] = _build_catalog()
MOMENTUM_BY_ID: dict[str, MomentumSpec] = {s.strategy_id: s for s in MOMENTUM_CATALOG}

# Every family is represented and every id is unique — a silent duplicate id would make
# two strategies share one ₹10,000 account and one leaderboard row.
assert len(MOMENTUM_CATALOG) == 37, f"expected 37 momentum strategies, built {len(MOMENTUM_CATALOG)}"
assert len(MOMENTUM_BY_ID) == len(MOMENTUM_CATALOG), "duplicate momentum strategy_id"
assert set(s.family for s in MOMENTUM_CATALOG) == set(FAMILIES), "catalog/family mismatch"


__all__ = [
    "MOMENTUM_CATALOG", "MOMENTUM_BY_ID", "MomentumSignal", "MomentumSpec", "SymbolMomentum",
    "STYLE_LABELS", "evaluate", "pct_return", "annualised_vol", "normalise_z",
]
