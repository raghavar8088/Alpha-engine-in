"""One module per strategy; importing a module registers it. Add a strategy = add a
module + an import line here. Nothing else changes.

Covers all 50 roadmap strategies in 49 modules — opening_range_breakout serves both
roadmap slots #19 (momentum ORB) and #36 (intraday opening range)."""

from strategy_service.strategies import (  # noqa: F401
    # trend (1-10)
    adx_trend,
    atr_trend,
    donchian_breakout,
    ema_cross,
    ichimoku,
    macd_trend,
    mtf_ema,
    sma_cross,
    supertrend,
    vwap_trend,
    # momentum (11-20; ORB shared with intraday)
    gap_momentum,
    macd_momentum,
    momentum_ignition,
    price_breakout,
    relative_strength,
    roc_momentum,
    rsi_momentum,
    stochastic_momentum,
    volume_breakout,
    # mean reversion (21-25)
    atr_reversion,
    bollinger_reversion,
    keltner_reversion,
    rsi_reversal,
    vwap_reversion,
    # swing (26-35)
    cpr_breakout,
    cup_handle,
    darvas_box,
    delivery_breakout,
    earnings_momentum,
    flag_pattern,
    high_volume_breakout,
    pivot_swing,
    sector_rotation,
    triangle_breakout,
    # intraday (36-40)
    gap_fade,
    opening_range_breakout,
    trend_pullback,
    volume_spike,
    vwap_scalping,
    # futures (41-45)
    breakout_futures,
    calendar_spread,
    oi_buildup,
    trend_futures,
    vwap_futures,
    # options (46-50; underlying-proxy until Phase 7)
    bull_put_spread,
    covered_call,
    iron_condor,
    long_call,
    long_put,
    # option-buying library (51-100): 15 scalp + 20 intraday + 15 swing
    options_buying,
    # option-SELLING library: neutral + directional-credit-spread + naked books
    options_selling,
)
