from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    strategy_id: str
    symbol: str
    timeframe: str = "1d"
    years: float | None = Field(default=None, gt=0, le=25)
    initial_capital: float = Field(default=1_000_000, gt=0)
    params: dict = {}
    param_grid: dict | None = None  # enables optimization (and feeds walk-forward)
    walk_forward: bool = False
    monte_carlo: bool = False
    slippage_bps: float = Field(default=5.0, ge=0)
    position_size_pct: float = Field(default=100.0, gt=0, le=100)


class BacktestSummary(BaseModel):
    """List-view row: everything except the heavy charts/analysis payloads."""

    id: str
    strategy_id: str
    symbol: str
    timeframe: str
    start: str
    end: str
    bar_count: int
    created_at: str
    metrics: dict
