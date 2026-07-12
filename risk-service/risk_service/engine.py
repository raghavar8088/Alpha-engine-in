"""RiskEngine — the gate every entry Signal passes through before becoming an order
(roadmap Phase 4 definition of done). Exits are NEVER gated here: the engine's job is
to prevent taking on more risk, not to block a strategy from reducing it, so callers
must only call `evaluate()` for entries and let exits (stop/target/signal) proceed
directly.

Defaults are deliberately permissive (every limit effectively disabled) so wiring this
into the backtester does not change any already-validated Phase 3 result unless a
caller opts into tighter limits."""

from enum import Enum

from pydantic import BaseModel, Field

from risk_service.sizing import (
    atr_quantity,
    fixed_capital_pct_quantity,
    fixed_fractional_quantity,
    kelly_quantity,
    to_lot_multiple,
    volatility_target_quantity,
)
from tradingai_shared.domain import RiskDecision


class SizingMethod(str, Enum):
    CAPITAL_PCT = "capital_pct"
    FIXED_FRACTIONAL = "fixed_fractional"
    ATR = "atr"
    VOLATILITY = "volatility"
    KELLY = "kelly"


class SizingConfig(BaseModel):
    method: SizingMethod = SizingMethod.CAPITAL_PCT
    capital_pct: float = Field(default=100.0, gt=0, le=100, description="for CAPITAL_PCT")
    risk_pct: float = Field(default=1.0, gt=0, description="for FIXED_FRACTIONAL / ATR / KELLY-less trades")
    atr_mult: float = Field(default=2.0, gt=0, description="for ATR")
    target_daily_vol_pct: float = Field(default=1.0, gt=0, description="for VOLATILITY")
    kelly_cap: float = Field(default=0.25, gt=0, le=1, description="for KELLY (0.25 = quarter-Kelly)")


class RiskLimits(BaseModel):
    daily_loss_limit_pct: float = Field(default=100.0, gt=0, description="kill-switch: halt entries for the day")
    max_drawdown_pct: float = Field(default=100.0, gt=0, description="kill-switch: halt entries since inception")
    max_open_positions: int = Field(default=10, ge=1)
    max_exposure_pct: float = Field(default=1000.0, gt=0, description="total notional / equity")
    max_sector_exposure_pct: float = Field(default=1000.0, gt=0, description="per-sector notional / equity")
    max_portfolio_heat_pct: float = Field(default=1000.0, gt=0, description="sum of at-risk capital / equity")


class PositionSnapshot(BaseModel):
    """Minimal view of one open position the engine needs to evaluate a NEW entry
    against — callers build this from their own position bookkeeping."""

    symbol: str
    sector: str | None = None
    notional: float  # quantity * current/entry price
    at_risk: float = 0.0  # |entry - stop| * quantity; 0 if no stop set


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.peak_equity: float | None = None
        self._day_key = None
        self._day_start_equity: float | None = None
        self._daily_kill_switch = False
        self._drawdown_kill_switch = False

    def update_equity(self, equity: float, day_key) -> None:
        """Call once per bar/tick before evaluating any signal on it. Tracks the
        peak (for max-drawdown) and detects day boundaries (for the daily-loss
        kill-switch, which resets each new day — unlike the drawdown kill-switch,
        which persists until `reset_drawdown_kill_switch()` is called explicitly)."""
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        if day_key != self._day_key:
            self._day_key = day_key
            self._day_start_equity = equity
            self._daily_kill_switch = False
        if self.peak_equity and (self.peak_equity - equity) / self.peak_equity * 100 >= self.limits.max_drawdown_pct:
            self._drawdown_kill_switch = True
        if self._day_start_equity and (equity - self._day_start_equity) / self._day_start_equity * 100 <= -self.limits.daily_loss_limit_pct:
            self._daily_kill_switch = True

    def reset_drawdown_kill_switch(self) -> None:
        """Manual reset (e.g. an operator acknowledging the breach) — unlike the daily
        kill-switch, drawdown does not clear itself on a new day."""
        self._drawdown_kill_switch = False

    @property
    def kill_switch_active(self) -> bool:
        return self._daily_kill_switch or self._drawdown_kill_switch

    def status(self, equity: float) -> dict:
        day_pnl_pct = None
        if self._day_start_equity:
            day_pnl_pct = (equity - self._day_start_equity) / self._day_start_equity * 100
        drawdown_pct = None
        if self.peak_equity:
            drawdown_pct = (self.peak_equity - equity) / self.peak_equity * 100
        return {
            "kill_switch_active": self.kill_switch_active,
            "daily_kill_switch": self._daily_kill_switch,
            "drawdown_kill_switch": self._drawdown_kill_switch,
            "day_pnl_pct": round(day_pnl_pct, 3) if day_pnl_pct is not None else None,
            "drawdown_pct": round(drawdown_pct, 3) if drawdown_pct is not None else None,
            "peak_equity": self.peak_equity,
            "limits": self.limits.model_dump(),
        }

    def evaluate(
        self,
        *,
        price: float,
        equity: float,
        open_positions: list[PositionSnapshot],
        sizing: SizingConfig,
        instrument_sector: str | None = None,
        stop_loss: float | None = None,
        lot_size: int = 1,
        atr: float | None = None,
        price_stdev_pct: float | None = None,
        win_rate: float | None = None,
        avg_win: float | None = None,
        avg_loss: float | None = None,
    ) -> RiskDecision:
        """Entry-only. Returns approved=False with reasons if a kill-switch is active,
        sizing produces nothing, or a limit can't be satisfied even after trimming."""
        if self._daily_kill_switch:
            return RiskDecision(approved=False, quantity=0, reasons=["daily loss limit breached — kill switch active"])
        if self._drawdown_kill_switch:
            return RiskDecision(approved=False, quantity=0, reasons=["max drawdown breached — kill switch active"])
        if len(open_positions) >= self.limits.max_open_positions:
            return RiskDecision(approved=False, quantity=0, reasons=[f"max open positions ({self.limits.max_open_positions}) reached"])

        quantity = self._size(
            sizing, equity, price, stop_loss, atr, price_stdev_pct, win_rate, avg_win, avg_loss, lot_size
        )
        if quantity <= 0:
            return RiskDecision(approved=False, quantity=0, reasons=["sizing produced zero quantity"])

        reasons: list[str] = []
        open_notional = sum(p.notional for p in open_positions)

        total_notional = open_notional + quantity * price
        if equity > 0 and total_notional / equity * 100 > self.limits.max_exposure_pct:
            allowed = max(self.limits.max_exposure_pct / 100 * equity - open_notional, 0)
            quantity = to_lot_multiple(allowed / price, lot_size) if price > 0 else 0
            if quantity <= 0:
                reasons.append(f"max exposure {self.limits.max_exposure_pct}% would be exceeded")

        if quantity > 0 and instrument_sector is not None:
            sector_notional = sum(p.notional for p in open_positions if p.sector == instrument_sector)
            projected = sector_notional + quantity * price
            if equity > 0 and projected / equity * 100 > self.limits.max_sector_exposure_pct:
                allowed = max(self.limits.max_sector_exposure_pct / 100 * equity - sector_notional, 0)
                quantity = to_lot_multiple(allowed / price, lot_size) if price > 0 else 0
                if quantity <= 0:
                    reasons.append(f"max sector exposure {self.limits.max_sector_exposure_pct}% would be exceeded")

        if quantity > 0 and stop_loss is not None:
            per_share_risk = abs(price - stop_loss)
            open_heat = sum(p.at_risk for p in open_positions)
            total_heat = open_heat + per_share_risk * quantity
            if equity > 0 and total_heat / equity * 100 > self.limits.max_portfolio_heat_pct:
                allowed_heat = max(self.limits.max_portfolio_heat_pct / 100 * equity - open_heat, 0)
                quantity = to_lot_multiple(allowed_heat / per_share_risk, lot_size) if per_share_risk > 0 else 0
                if quantity <= 0:
                    reasons.append(f"portfolio heat limit ({self.limits.max_portfolio_heat_pct}%) reached")

        if quantity <= 0:
            return RiskDecision(approved=False, quantity=0, reasons=reasons or ["sizing produced zero quantity"])
        return RiskDecision(approved=True, quantity=quantity, reasons=[])

    def _size(
        self, sizing: SizingConfig, equity: float, price: float, stop_loss: float | None,
        atr: float | None, price_stdev_pct: float | None,
        win_rate: float | None, avg_win: float | None, avg_loss: float | None, lot_size: int,
    ) -> int:
        if sizing.method == SizingMethod.CAPITAL_PCT:
            return fixed_capital_pct_quantity(equity, sizing.capital_pct, price, lot_size)
        if sizing.method == SizingMethod.FIXED_FRACTIONAL:
            if stop_loss is None:
                return 0
            return fixed_fractional_quantity(equity, sizing.risk_pct, price, stop_loss, lot_size)
        if sizing.method == SizingMethod.ATR:
            if atr is None:
                return 0
            return atr_quantity(equity, sizing.risk_pct, price, atr, sizing.atr_mult, lot_size)
        if sizing.method == SizingMethod.VOLATILITY:
            if price_stdev_pct is None:
                return 0
            return volatility_target_quantity(equity, sizing.target_daily_vol_pct, price, price_stdev_pct, lot_size)
        if sizing.method == SizingMethod.KELLY:
            if win_rate is None or avg_win is None or avg_loss is None:
                return 0
            return kelly_quantity(equity, win_rate, avg_win, avg_loss, price, lot_size, sizing.kelly_cap)
        raise ValueError(f"unknown sizing method {sizing.method!r}")
