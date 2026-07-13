from pydantic import BaseModel


class ValidationRun(BaseModel):
    symbol: str
    timeframe: str
    bar_count: int
    passed: bool
    fail_reasons: list[str]
    metrics: dict


class RealMoneyCheck(BaseModel):
    """Walk-forward tier result: the bar for live capital (validate.py)."""

    symbol: str
    timeframe: str
    ready: bool
    consistency: float | None = None
    oos_net_profit: float | None = None
    oos_total_trades: int | None = None
    error: str | None = None


class ValidationSummary(BaseModel):
    """Latest gate result from the `strategy_validation` collection (validate.py)."""

    status: str  # "pass" | "fail" | "insufficient_data"
    passed: bool
    passing_runs: int
    total_runs: int
    validated_at: str
    best_run: ValidationRun | None = None
    runs: list[ValidationRun] = []
    real_money: RealMoneyCheck | None = None
    real_money_ready: bool = False


class StrategyInfo(BaseModel):
    """One registered strategy's metadata + parameter schema, for the strategies UI."""

    strategy_id: str
    name: str
    category: str
    description: str
    timeframes: list[str]
    asset_classes: list[str]
    suitable_market: str
    expected_win_rate: float | None = None
    risk_reward: float | None = None
    params_schema: dict  # JSON Schema of the strategy's Params model (defaults included)
    validation: ValidationSummary | None = None  # None = never validated
