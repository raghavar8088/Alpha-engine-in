from pydantic import BaseModel


class SectorAllocationItem(BaseModel):
    sector: str
    value: float
    pct: float


class CapitalAllocation(BaseModel):
    total_capital: float
    cash_available: float
    deployed: float


class PortfolioAnalytics(BaseModel):
    unrealized_pnl: float
    unrealized_pnl_holdings: float
    unrealized_pnl_positions: float
    realized_pnl_today: float
    holdings_value: float
    positions_notional: float
    capital_allocation: CapitalAllocation
    exposure_pct: float | None
    exposure_note: str
    holdings_pct_of_portfolio: float | None
    sector_allocation: list[SectorAllocationItem]
    beta: float | None
    alpha_annual_pct: float | None
    volatility_annual_pct: float | None
    beta_symbols_used: list[str]
    beta_note: str | None
    computed_at: str
