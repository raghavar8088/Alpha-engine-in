from pydantic import BaseModel

from risk_service import RiskLimits


class RiskStatus(BaseModel):
    total_capital: float
    day_start_equity: float
    day_pnl: float
    day_pnl_pct: float | None
    open_positions_count: int
    limits: RiskLimits
    kill_switch_active: bool
    kill_switch_reasons: list[str]
    note: str


class RiskLimitsUpdate(BaseModel):
    daily_loss_limit_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_open_positions: int | None = None
    max_exposure_pct: float | None = None
    max_sector_exposure_pct: float | None = None
    max_portfolio_heat_pct: float | None = None
