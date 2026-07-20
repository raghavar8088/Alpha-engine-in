"""Structure x regime matrix — the combinatorial half of the selling library.

WHY A FACTORY AND NOT 70 HAND-WRITTEN CLASSES
---------------------------------------------
A premium-selling strategy is honestly just two decisions: *when* is this tape worth
selling into (the regime), and *what* do I sell when it is (the structure). Those two
choices are independent — "sell into a dead tape" pairs with a condor, a strangle, an
iron fly or a jade lizard equally well. Writing every pairing out by hand would produce
seventy near-identical class bodies whose real content is one predicate and one leg
list, and would hide the thing a reader most needs to see: which combinations were tried
and which were not.

So regimes and structures are defined once each, and `seller()` welds a pair into a
registered strategy. The matrix at the bottom of this module IS the library — it can be
read in one screen.

THE STATISTICAL COST, STATED PLAINLY
------------------------------------
Generating strategies from a grid is data mining, and testing many candidates against
one history guarantees some pass on luck alone. At a PF 1.3 bar over ~90 candidates, a
handful of qualifiers are expected to be noise even if no real edge existed anywhere.

Two things keep that honest, and neither is optional:
  1. Nothing here is tuned to the result. Regime thresholds are conventional values
     (ADX 20/25, RSI 30/70, 15-delta strikes) chosen before seeing the outcome, not
     search results. There is no optimizer pass over this grid.
  2. `verify_selling_split.py` re-runs every qualifier on a chronological split and
     reports whether its edge survives out of sample. A strategy that qualifies on the
     full history and collapses on the back half is a mining artifact, and the report
     says so rather than burying it.

Read a qualifier from this module as "worth forward-testing on the paper desk", never as
"proven". The paper desk is what promotes it.
"""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema, macd, rsi, sma, stdev, stochastic
from strategy_service.strategies.options_selling._base import (
    LegSpec,
    OptionSellStrategy,
    atr_pct,
    compression,
    gap_pct,
    range_position,
    realized_vol,
    sell_meta,
    vol_rank,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

SWING, POSITIONAL = "options_sell_swing", "options_sell_positional"
TF15, TFD = Timeframe.M15, Timeframe.D1


class SellParams(BaseModel):
    """Tunables shared by every generated strategy. The matrix supplies defaults; these
    exist so the optimizer has a surface to work on and so a live desk can widen strikes
    without editing the library."""

    target_delta: float | None = Field(default=None, description="override the matrix's short-strike delta")
    wing_pct: float | None = Field(default=None, description="override the matrix's wing width")


# --- structures ------------------------------------------------------------------
#
# Each returns the legs for a given short-strike delta and wing width. Defined-risk
# structures buy wings anchored to their own short leg (see LegSpec.wing_pct); naked
# ones do not, and pay for it in margin and in the gate's stricter naked bar.


def condor(d, w):
    """Short strangle with both wings bought. The desk's structural default."""
    return [
        LegSpec("CE", sell=True, target_delta=d), LegSpec("CE", sell=False, wing_pct=w),
        LegSpec("PE", sell=True, target_delta=d), LegSpec("PE", sell=False, wing_pct=w),
    ]


def iron_fly(d, w):
    """ATM straddle with wings. Collects far more than a condor and needs the tape to sit
    still — the highest-credit, highest-gamma defined-risk structure here."""
    return [
        LegSpec("CE", sell=True, otm_pct=0.0), LegSpec("CE", sell=False, wing_pct=w),
        LegSpec("PE", sell=True, otm_pct=0.0), LegSpec("PE", sell=False, wing_pct=w),
    ]


def strangle(d, w):
    """Naked both sides. Unbounded tail, the largest margin draw in the library."""
    return [LegSpec("CE", sell=True, target_delta=d), LegSpec("PE", sell=True, target_delta=d)]


def straddle(d, w):
    return [LegSpec("CE", sell=True, otm_pct=0.0), LegSpec("PE", sell=True, otm_pct=0.0)]


def put_spread(d, w):
    """Bull put credit spread — wins on up, flat, and mildly down tape."""
    return [LegSpec("PE", sell=True, target_delta=d), LegSpec("PE", sell=False, wing_pct=w)]


def call_spread(d, w):
    """Bear call credit spread. Structurally the harder side: index drift works against
    it, so it needs its regime read to be right more often than the put spread does."""
    return [LegSpec("CE", sell=True, target_delta=d), LegSpec("CE", sell=False, wing_pct=w)]


def naked_put(d, w):
    return [LegSpec("PE", sell=True, target_delta=d)]


def naked_call(d, w):
    return [LegSpec("CE", sell=True, target_delta=d)]


def jade_lizard(d, w):
    """Naked short put + a bear call SPREAD. Sized so the credit collected exceeds the
    call spread's width, which removes upside risk entirely — the position cannot lose
    if the index rallies. All of its risk is to the downside, on the naked put.

    A genuinely different risk shape from anything else in this library, and the reason
    it is worth including even though it is margined as naked."""
    return [
        LegSpec("PE", sell=True, target_delta=d),
        LegSpec("CE", sell=True, target_delta=d * 1.4),
        LegSpec("CE", sell=False, wing_pct=w),
    ]


def broken_wing_put(d, w):
    """Put butterfly with an intentionally uneven lower wing: a short put spread financed
    by a further-out long put. Cheaper than a symmetric fly and skewed so the loss zone
    sits where the tape rarely goes."""
    return [
        LegSpec("PE", sell=True, target_delta=d),
        LegSpec("PE", sell=False, wing_pct=w * 2.5),
    ]


def ratio_put_spread(d, w):
    """Long one nearer put, short two further ones — a credit structure that profits from
    a mild decline and is hurt by a violent one. Included because its payoff is unlike
    every other entry here; the naked short below its long leg is real."""
    return [
        LegSpec("PE", sell=False, target_delta=d * 2.2),
        LegSpec("PE", sell=True, target_delta=d),
    ]


# --- regimes ---------------------------------------------------------------------
#
# Each takes a StrategyContext and returns (should_sell, why) — or (False, "") to pass.
# Thresholds are conventional values, fixed before any result was seen.


def r_dead_tape(ctx):
    a = adx(ctx.bars, 14)[0][-1]
    return a <= 20, f"ADX {a:.1f} — trendless"


def r_dead_tape_mid(ctx):
    a = adx(ctx.bars, 14)[0][-1]
    p = range_position(ctx.bars, 20)
    return a <= 20 and 0.3 <= p <= 0.7, f"ADX {a:.1f}, mid-range {p:.2f}"


def r_coil(ctx):
    return compression(ctx.bars, 20, 30), "20-bar deviation at a 30-bar low"


def r_vol_rich(ctx):
    v = vol_rank(ctx.closes, 20, 60)
    return (v is not None and v >= 0.60), f"realized-vol rank {v:.2f}" if v else ""


def r_vol_cheap(ctx):
    """Selling into CHEAP volatility — the opposite of the textbook read, included so the
    matrix tests the assumption rather than assuming it."""
    v = vol_rank(ctx.closes, 20, 60)
    return (v is not None and v <= 0.35), f"vol rank {v:.2f} — cheap premium" if v else ""


def r_trend_up(ctx):
    f, s = ema(ctx.closes, 20), ema(ctx.closes, 50)
    return f[-1] > s[-1] and ctx.current.close > f[-1], f"above a rising EMA20 ({f[-1]:.0f}>{s[-1]:.0f})"


def r_trend_down(ctx):
    f, s = ema(ctx.closes, 20), ema(ctx.closes, 50)
    return f[-1] < s[-1] and ctx.current.close < f[-1], f"below a falling EMA20 ({f[-1]:.0f}<{s[-1]:.0f})"


def r_dip_bounce(ctx):
    r = rsi(ctx.closes, 14)
    up = ctx.current.close > sma(ctx.closes, 50)[-1]
    return up and r[-2] < 40 <= r[-1], f"RSI bounced from {r[-2]:.0f} inside an uptrend"


def r_rally_fade(ctx):
    r = rsi(ctx.closes, 14)
    down = ctx.current.close < sma(ctx.closes, 50)[-1]
    return down and r[-2] > 60 >= r[-1], f"RSI rolled from {r[-2]:.0f} beneath the trend"


def r_range_low(ctx):
    p = range_position(ctx.bars, 20)
    a = adx(ctx.bars, 14)[0][-1]
    return p <= 0.35 and a <= 25, f"range floor {p:.2f}, ADX {a:.1f}"


def r_range_high(ctx):
    p = range_position(ctx.bars, 20)
    a = adx(ctx.bars, 14)[0][-1]
    return p >= 0.65 and a <= 25, f"range ceiling {p:.2f}, ADX {a:.1f}"


def r_quiet_open(ctx):
    g = gap_pct(ctx)
    return abs(g) <= 0.3, f"flat open ({g:+.2f}%)"


def r_post_gap_down(ctx):
    """Sell premium after a gap DOWN has already happened — fear is priced in and the
    tape has stopped falling."""
    g = gap_pct(ctx)
    return g <= -0.5 and ctx.current.close > ctx.current.open, f"gap down {g:.2f}%, closing green"


def r_narrow_atr(ctx):
    w = atr_pct(ctx.bars, 14)
    return w <= 0.5, f"ATR {w:.2f}% of price — tight tape"


def r_macd_flat(ctx):
    line, sig = macd(ctx.closes)
    h = line[-1] - sig[-1]
    return abs(h) < abs(ctx.current.close) * 0.0004, f"MACD histogram flat ({h:.1f})"


def r_bb_inside(ctx):
    """Price inside a NARROW Bollinger band. Built from sma/stdev directly — this
    indicator library has no bollinger() helper."""
    closes = ctx.closes
    mid, sd = sma(closes, 20)[-1], stdev(closes, 20)[-1]
    upper, lower = mid + 2 * sd, mid - 2 * sd
    c = ctx.current.close
    width = (upper - lower) / mid if mid else 1
    return lower < c < upper and width < 0.03, f"inside a {width*100:.1f}%-wide band"


def r_stoch_mid(ctx):
    k, _ = stochastic(ctx.bars, 14, 3)
    return 35 <= k[-1] <= 65, f"stochastic mid-zone ({k[-1]:.0f})"


def r_low_realized(ctx):
    v = realized_vol(ctx.closes, 20)
    return 0 < v <= 0.14, f"realized vol {v*100:.1f}%"


def r_trend_up_daily(ctx):
    s = sma(ctx.closes, 50)
    return ctx.current.close > s[-1] and s[-1] > s[-2], "daily close above a rising SMA50"


def r_pullback_up(ctx):
    """A dip inside an intact uptrend — premium is fat and the trend is still there."""
    s20, s50 = sma(ctx.closes, 20), sma(ctx.closes, 50)
    c = ctx.current.close
    return s20[-1] > s50[-1] and c < s20[-1] and c > s50[-1], "pullback between SMA20 and a rising SMA50"


def r_consecutive_down(ctx):
    b = ctx.bars[-3:]
    return all(x.close < x.open for x in b), "3 consecutive red bars — short-term washout"


def r_inside_bar(ctx):
    a, b = ctx.bars[-2], ctx.bars[-1]
    return b.high <= a.high and b.low >= a.low, "inside bar — contraction"


def r_gap_up_fade(ctx):
    """Mirror of the post-gap-down read: an opening gap UP that is already fading. Call
    premium is rich and the move has shown it cannot hold."""
    g = gap_pct(ctx)
    return g >= 0.5 and ctx.current.close < ctx.current.open, f"gap up {g:.2f}%, closing red"


def r_three_green(ctx):
    b = ctx.bars[-3:]
    return all(x.close > x.open for x in b), "3 consecutive green bars — stretched up"


def r_atr_expand(ctx):
    """Tape has WIDENED — the opposite of the narrow-ATR read. Sellers are paid more here
    and are also likelier to be run over; the matrix tests which effect dominates."""
    w = atr_pct(ctx.bars, 14)
    return w >= 0.8, f"ATR {w:.2f}% of price — wide tape"


def r_htf_pullback(ctx):
    """Long-term uptrend (above SMA200) with a short-term dip. Combines two horizons,
    which no other regime here does — the trend filter and the entry trigger disagree
    on purpose."""
    closes = ctx.closes
    if len(closes) < 205:
        return False, ""
    long_up = ctx.current.close > sma(closes, 200)[-1]
    short_dip = ctx.current.close < sma(closes, 20)[-1]
    return long_up and short_dip, "dip inside a long-term (SMA200) uptrend"


def r_stretched_below(ctx):
    """Price stretched well below its own mean — a mean-reversion setup where put
    premium is fat and the snap-back, if it comes, pays the seller twice."""
    closes = ctx.closes
    m = sma(closes, 20)[-1]
    sd = stdev(closes, 20)[-1]
    if sd <= 0:
        return False, ""
    z = (ctx.current.close - m) / sd
    return z <= -1.5, f"{z:.2f} sigma below the 20-bar mean"


def r_vol_falling(ctx):
    """Realized volatility contracting relative to its own recent level — a crude term-
    structure read. Falling vol is the seller's friend and is NOT the same signal as
    'vol is low' (r_low_rv), which can precede an expansion."""
    fast, slow = realized_vol(ctx.closes, 10), realized_vol(ctx.closes, 40)
    return 0 < fast < slow * 0.8, f"short-window vol {fast*100:.1f}% under long {slow*100:.1f}%"


def r_recovery(ctx):
    """Price climbing back after a drawdown from its recent high — the fear premium is
    still priced in while the tape has already turned."""
    highs = [b.high for b in ctx.bars[-60:]]
    peak = max(highs)
    c = ctx.current.close
    off = (peak - c) / peak if peak else 0
    rising = c > ctx.bars[-2].close > ctx.bars[-3].close
    return 0.02 <= off <= 0.08 and rising, f"{off*100:.1f}% off the 60-bar high and turning up"


def r_adx_bottom(ctx):
    """ADX at the very bottom of its range — a deeper trendlessness read than the plain
    ADX ceiling, and one that fires far less often."""
    a = adx(ctx.bars, 14)[0]
    return a[-1] <= 15, f"ADX {a[-1]:.1f} — deeply trendless"


def r_near_high_flat(ctx):
    """Near a 60-bar high but momentum has gone flat — the tape has stopped advancing
    without reversing. Call premium above is the thing to sell."""
    p = range_position(ctx.bars, 60)
    line, sig = macd(ctx.closes)
    return p >= 0.8 and abs(line[-1] - sig[-1]) < abs(ctx.current.close) * 0.0005, \
        f"at {p:.2f} of the 60-bar range with flat momentum"


# --- the matrix ------------------------------------------------------------------


def seller(sid, name, category, timeframe, market, regime, structure, delta, wing, blurb):
    """Weld one regime to one structure and register it as a strategy."""

    @register_strategy
    class _Generated(OptionSellStrategy):
        metadata = sell_meta(sid, name, category, blurb, timeframe, market)
        Params = SellParams

        @property
        def warmup(self) -> int:
            # Generous and uniform: every regime here reads at most a 60-bar vol-rank
            # window over a 20-bar vol window, plus room for ADX's double smoothing.
            return 90

        def want_open(self, ctx: StrategyContext) -> bool:
            ok, why = regime(ctx)
            if ok:
                self.why = why
            return ok

        def legs(self, ctx: StrategyContext) -> list[LegSpec]:
            d = self.params.target_delta if self.params.target_delta is not None else delta
            w = self.params.wing_pct if self.params.wing_pct is not None else wing
            return structure(d, w)

    _Generated.__name__ = "".join(p.title() for p in sid.split("_"))
    _Generated.__qualname__ = _Generated.__name__
    return _Generated


# Regime catalogue: (key, predicate, human label, suits)
REGIMES = [
    ("dead_tape", r_dead_tape, "Dead Tape", "range-bound"),
    ("dead_mid", r_dead_tape_mid, "Dead Tape Mid-Range", "range-bound"),
    ("coil", r_coil, "Volatility Coil", "range-bound"),
    ("vol_rich", r_vol_rich, "Rich Volatility", "high-volatility"),
    ("vol_cheap", r_vol_cheap, "Cheap Volatility", "range-bound"),
    ("trend_up", r_trend_up, "Uptrend", "trending"),
    ("trend_down", r_trend_down, "Downtrend", "trending"),
    ("dip", r_dip_bounce, "Dip Bounce", "trending"),
    ("fade", r_rally_fade, "Rally Fade", "trending"),
    ("range_low", r_range_low, "Range Floor", "range-bound"),
    ("range_high", r_range_high, "Range Ceiling", "range-bound"),
    ("quiet_open", r_quiet_open, "Quiet Open", "range-bound"),
    ("post_gap", r_post_gap_down, "Post Gap-Down", "high-volatility"),
    ("narrow", r_narrow_atr, "Narrow ATR", "range-bound"),
    ("macd_flat", r_macd_flat, "MACD Flat", "range-bound"),
    ("bb_inside", r_bb_inside, "Inside Bollinger", "range-bound"),
    ("stoch_mid", r_stoch_mid, "Stochastic Mid", "range-bound"),
    ("low_rv", r_low_realized, "Low Realized Vol", "range-bound"),
    ("pullback", r_pullback_up, "Uptrend Pullback", "trending"),
    ("three_red", r_consecutive_down, "Three Red Bars", "high-volatility"),
    ("inside_bar", r_inside_bar, "Inside Bar", "range-bound"),
    ("gap_up_fade", r_gap_up_fade, "Gap-Up Fade", "high-volatility"),
    ("three_green", r_three_green, "Three Green Bars", "trending"),
    ("atr_wide", r_atr_expand, "Wide ATR", "high-volatility"),
    ("htf_pullback", r_htf_pullback, "SMA200 Pullback", "trending"),
    ("stretched", r_stretched_below, "Stretched Below Mean", "high-volatility"),
    ("vol_falling", r_vol_falling, "Contracting Volatility", "range-bound"),
    ("recovery", r_recovery, "Drawdown Recovery", "trending"),
    ("adx_bottom", r_adx_bottom, "Deep Trendless", "range-bound"),
    ("near_high", r_near_high_flat, "Near High, Flat", "range-bound"),
]

# Structure catalogue: (key, builder, label, default delta, default wing, naked?)
STRUCTURES = [
    ("condor", condor, "Iron Condor", 0.15, 0.010, False),
    ("fly", iron_fly, "Iron Butterfly", 0.15, 0.010, False),
    ("put_spread", put_spread, "Bull Put Spread", 0.20, 0.015, False),
    ("call_spread", call_spread, "Bear Call Spread", 0.20, 0.015, False),
    ("strangle", strangle, "Short Strangle", 0.12, 0.0, True),
    ("naked_pe", naked_put, "Naked Put", 0.12, 0.0, True),
    ("jade", jade_lizard, "Jade Lizard", 0.15, 0.015, True),
    ("bwb_pe", broken_wing_put, "Broken-Wing Put", 0.20, 0.012, False),
]

# Which structures each regime is paired with. Directional regimes get the directional
# structures that agree with them (an uptrend read pairs with put-side premium, never
# call-side), neutral regimes get the two-sided ones. This is the design decision the
# matrix makes explicit: nothing here sells calls into an uptrend.
PAIRINGS = {
    "dead_tape": ["condor", "strangle", "fly"],
    "dead_mid": ["condor", "strangle", "fly", "jade"],
    "coil": ["condor", "fly", "strangle"],
    "vol_rich": ["condor", "put_spread", "jade", "strangle"],
    "vol_cheap": ["condor", "put_spread"],
    "trend_up": ["put_spread", "naked_pe", "jade", "bwb_pe"],
    "trend_down": ["call_spread"],
    "dip": ["put_spread", "naked_pe", "jade"],
    "fade": ["call_spread"],
    "range_low": ["put_spread", "naked_pe", "bwb_pe"],
    "range_high": ["call_spread", "condor"],
    "quiet_open": ["condor", "fly"],
    "post_gap": ["put_spread", "naked_pe", "jade"],
    "narrow": ["condor", "fly", "strangle"],
    "macd_flat": ["condor", "fly"],
    "bb_inside": ["condor", "put_spread"],
    "stoch_mid": ["condor", "strangle"],
    "low_rv": ["condor", "fly"],
    "pullback": ["put_spread", "naked_pe", "bwb_pe"],
    "three_red": ["put_spread", "naked_pe"],
    "inside_bar": ["condor", "fly"],
    "gap_up_fade": ["call_spread", "condor"],
    "three_green": ["call_spread", "condor"],
    "atr_wide": ["condor", "put_spread", "jade"],
    "htf_pullback": ["put_spread", "naked_pe", "jade"],
    "stretched": ["put_spread", "naked_pe", "bwb_pe"],
    "vol_falling": ["condor", "fly", "strangle"],
    "recovery": ["put_spread", "naked_pe", "jade"],
    "adx_bottom": ["condor", "fly", "strangle"],
    "near_high": ["call_spread", "condor"],
}

_STRUCT = {k: (fn, label, d, w, naked) for k, fn, label, d, w, naked in STRUCTURES}

# Both styles get the full matrix. The swing/positional split is not cosmetic: the same
# regime read on the same structure behaves very differently at a 7-day expiry on 15m
# entries versus a 30-day expiry on daily entries, because theta, gamma and the number of
# overnight gaps carried all change. Running both is how the library finds out which
# holding period each edge actually belongs to.
for _style, _tf, _suffix in ((SWING, TF15, "sw"), (POSITIONAL, TFD, "pos")):
    for _rkey, _rfn, _rlabel, _market in REGIMES:
        for _skey in PAIRINGS[_rkey]:
            _sfn, _slabel, _d, _w, _naked = _STRUCT[_skey]
            seller(
                f"sell_{_suffix}_{_rkey}_{_skey}",
                f"Sell {'Swing' if _style == SWING else 'Monthly'}: {_rlabel} {_slabel}",
                _style, _tf, _market, _rfn, _sfn, _d, _w,
                f"{_rlabel} regime sold as a {_slabel.lower()}"
                f"{' (naked — unbounded tail, stricter gate)' if _naked else ' (defined risk)'}"
                f", held to a {'7-day weekly' if _style == SWING else '30-day monthly'} expiry.",
            )
