from pydantic import BaseModel, Field


class PayoffLegRequest(BaseModel):
    option_type: str = Field(description="CE or PE")
    strike: float
    premium: float
    quantity: int = Field(gt=0)
    direction: str = Field(description="BUY or SELL")


class PayoffRequest(BaseModel):
    legs: list[PayoffLegRequest]
    spot: float | None = Field(default=None, description="current underlying price, for net Greeks")
    days_to_expiry: int = Field(default=30, gt=0)
    iv_pct: float = Field(default=15.0, gt=0, description="flat IV assumption for net Greeks, in percent")


class OptionsBacktestRequest(BaseModel):
    strategy_id: str = Field(
        description="one of the 5 structures (long_call, long_put, covered_call, bull_put_spread, "
        "iron_condor) or any registered option-buying strategy (options_scalp/intraday/swing)"
    )
    symbol: str
    timeframe: str = "1d"
    years: float = Field(default=5.0, gt=0, le=25)
    initial_capital: float = Field(default=1_000_000, gt=0)
    lot_size: int = Field(default=75, gt=0)
    quantity_lots: int = Field(default=1, gt=0)
    dte_days: int | None = Field(default=None, gt=0, description="None = the strategy style's default")
    otm_pct: float = Field(default=0.03, ge=0)
    strike_step: float = Field(default=50.0, gt=0)
    iv_lookback: int = Field(default=20, gt=1)
    params: dict = {}


class OptionsSweepRequest(BaseModel):
    """Run every registered option-buying strategy (the 50-strategy library) in one sweep."""

    symbol: str = "NIFTY"
    years: float = Field(default=10.0, gt=0, le=25)
    initial_capital: float = Field(default=1_000_000, gt=0)
    lot_size: int = Field(default=75, gt=0)
    quantity_lots: int = Field(default=1, gt=0)
    min_win_rate: float = Field(default=0.40, ge=0, le=1, description="qualification gate")
    min_trades: int = Field(
        default=10, ge=1, description="fewer trades than this can't qualify (no 1-trade 100% winners)"
    )
    min_expectancy: float = Field(
        default=0.0, ge=0,
        description="minimum net profit per trade (Rs) to qualify — filters strategies whose "
        "edge is thinner than real-world spread+brokerage friction",
    )
    adx_regime: float | None = Field(
        default=None, gt=0,
        description="if set, trend-following strategies (suitable_market='trending') only take "
        "new entries while ADX(14) on the underlying is at or above this value",
    )


class OptionsSellingSweepRequest(BaseModel):
    """Run every registered option-SELLING strategy in one sweep.

    Deliberately does NOT carry a win-rate gate. Premium selling routinely shows 70-90%
    win rates while losing money, because its P&L is decided by the size of the rare
    losers, not the count of the frequent winners — so the gate here is built from profit
    factor, single-trade tail size and drawdown instead. See
    `options_service.options_selling_backtest.SELLING_GATE` for the reasoning behind
    each default.
    """

    symbol: str = "NIFTY"
    years: float = Field(default=10.0, gt=0, le=25)
    initial_capital: float = Field(default=1_000_000, gt=0)
    lot_size: int = Field(default=75, gt=0)
    quantity_lots: int = Field(default=1, gt=0)
    min_profit_factor: float = Field(
        default=1.3, gt=0,
        description="gross wins / gross losses; above 1.0 by a margin that survives the "
        "gap between modelled and real premiums",
    )
    min_trades: int = Field(
        default=20, ge=1,
        description="selling needs a bigger sample than buying — a run that has not yet "
        "hit one of its rare large losers looks far better than it is",
    )
    max_worst_trade_pct_capital: float = Field(
        default=1.5, gt=0,
        description="the tail gate: no single trade may cost more than this share of "
        "capital. Stricter than the engine's own capital backstop by design",
    )
    max_drawdown_pct: float = Field(default=10.0, gt=0)
    naked_min_profit_factor: float = Field(
        default=1.6, gt=0,
        description="naked structures clear a higher bar: this engine fills stops at the "
        "stop level, so a naked short's true gap risk is understated and needs margin",
    )
    naked_max_worst_trade_pct_capital: float = Field(default=1.0, gt=0)
    train_fraction: float = Field(
        default=0.6, gt=0.2, lt=0.95,
        description="chronological split: this share of bars is selected on, the rest is "
        "held back. Testing ~180 candidates against one history guarantees some clear the "
        "gate on noise; the held-back tail is what separates edge from luck",
    )
    min_test_trades: int = Field(
        default=15, ge=1,
        description="a held-back period with fewer trades than this is too thin to judge, "
        "so the strategy is treated as unproven rather than robust",
    )
    overlap_threshold: float = Field(
        default=0.60, gt=0, le=1.0,
        description="two survivors whose ENTRY DAYS overlap by more than this are the same "
        "bet; the lower out-of-sample profit factor is dropped from the basket. Without "
        "this a desk can hold five names of one trade and believe it is diversified",
    )
