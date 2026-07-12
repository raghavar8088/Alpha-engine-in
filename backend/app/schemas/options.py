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
