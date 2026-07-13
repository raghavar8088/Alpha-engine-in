from pydantic import BaseModel, Field


class StartRunRequest(BaseModel):
    strategy_id: str
    symbol: str
    timeframe: str = "1d"
    mode: str = Field(description="HISTORICAL | BACKTEST | REPLAY | SIMULATION | PAPER | LIVE")
    params: dict = {}
    initial_capital: float = Field(default=1_000_000, gt=0)
    years: float | None = Field(default=None, gt=0, description="REPLAY: lookback window")
    simulation_bars: int | None = Field(default=None, gt=0, description="SIMULATION: bar count")
    sizing: dict | None = None
    risk_limits: dict | None = None
    confirm_live: bool = Field(default=False, description="must be true to start a LIVE run")


class RunSummary(BaseModel):
    run_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    mode: str
    status: str
    started_at: str
    stopped_at: str | None
    # snapshot keys: cash, equity, position, last_signal, last_action (entry/
    # stop_loss/target/signal_exit — what actually changed the position, distinct
    # from last_signal which may be a no-op), closed_trades, total_pnl, recent_trades
    snapshot: dict | None = None


class RunDetail(RunSummary):
    result: dict | None = None
    error: str | None = None
