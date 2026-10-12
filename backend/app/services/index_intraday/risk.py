"""Indian Index Intraday — the risk manager.

Every new paper entry asks `allow()` first and is sized by `size()`. Nothing here ever
blocks an EXIT: a stop, a target, a square-off or an emergency flatten always goes through.

LIMITS (each configurable from the Risk panel; defaults below)
  capital                    Rs10 lakh virtual
  risk_per_trade_pct   0.5   loss to the initial stop as % of equity — the size follows
                             from it; a strategy with no stop is sized as if its stop were
                             0.5 x the day's ATR away (volatility-based sizing)
  max_position_pct     100   notional cap a position, % of equity (no leverage)
  max_daily_loss_pct   1.5   new entries stop for the day below this realised + open loss
  max_trades_per_day   10
  max_concurrent       3
  max_drawdown_pct     8.0   from peak equity: new entries stop until a manual reset
  loss_streak          3     consecutive losing trades ...
  streak_cooldown_min  60    ... pause entries this long
  cooldown_after_exit_min 0  pause after ANY exit (per strategy)
  entry window         09:20 - 14:30 (14:45 for a last-half-hour family); square-off 15:12
  emergency_stop       False when set: flatten everything at the market and block entries
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class RiskConfig:
    capital: float = 1_000_000.0
    risk_per_trade_pct: float = 0.5
    max_position_pct: float = 100.0
    max_daily_loss_pct: float = 1.5
    max_trades_per_day: int = 10
    max_concurrent: int = 3
    max_drawdown_pct: float = 8.0
    loss_streak: int = 3
    streak_cooldown_min: int = 60
    cooldown_after_exit_min: int = 0
    entry_from: str = "09:20"
    entry_until: str = "14:30"
    square_off: str = "15:12"
    emergency_stop: bool = False

    @classmethod
    def from_doc(cls, doc: dict | None) -> "RiskConfig":
        base = cls()
        if not doc:
            return base
        for k, v in doc.items():
            if hasattr(base, k) and v is not None:
                cur = getattr(base, k)
                try:
                    setattr(base, k, type(cur)(v) if not isinstance(cur, bool) else bool(v))
                except (TypeError, ValueError):
                    pass
        return base

    def as_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> list[str]:
        bad_times = [k for k in ("entry_from", "entry_until", "square_off")
                     if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(getattr(self, k)))]
        if bad_times:
            return [f"{', '.join(bad_times)}: times are HH:MM, e.g. 09:20"]
        problems = []
        if self.capital <= 0:
            problems.append("capital must be positive")
        if not 0 < self.risk_per_trade_pct <= 5:
            problems.append("risk per trade must be in (0, 5]%")
        if not 0 < self.max_position_pct <= 100:
            problems.append("position cap must be in (0, 100]% — no leverage in the cash market")
        if not 0 < self.max_daily_loss_pct <= 20:
            problems.append("daily loss limit must be in (0, 20]%")
        if self.max_trades_per_day < 1 or self.max_concurrent < 1:
            problems.append("trade and position limits must be at least 1")
        if not 0 < self.max_drawdown_pct <= 50:
            problems.append("drawdown threshold must be in (0, 50]%")
        if self.entry_from >= self.entry_until or self.entry_until >= self.square_off:
            problems.append("entry window must close before the square-off")
        if not "09:15" <= self.entry_from:
            problems.append("entries cannot start before the 09:15 open")
        if self.square_off > "15:12":
            problems.append("square-off must be 15:12 or earlier — the research's, and before Angel's 15:15 MIS "
                            "auto square-off")
        if self.loss_streak < 0 or self.streak_cooldown_min < 0 or self.cooldown_after_exit_min < 0:
            problems.append("streak and cooldown settings cannot be negative")
        return problems


@dataclass
class DayState:
    day: str
    trades: int = 0
    realized: float = 0.0
    loss_streak: int = 0
    paused_until: str | None = None          # HH:MM
    halted: bool = False                     # drawdown breach: manual reset needed
    peak_equity: float = 0.0


def allow(cfg: RiskConfig, st: DayState, now: datetime, open_positions: int, open_pnl: float,
          equity: float, last_exit_hhmm: str | None = None, family_until: str | None = None) -> tuple[bool, str]:
    """May a new position open now? (ok, reason when not)."""
    hhmm = now.strftime("%H:%M")
    until = family_until or cfg.entry_until
    if cfg.emergency_stop:
        return False, "emergency stop is on"
    if st.halted:
        return False, f"drawdown beyond {cfg.max_drawdown_pct}% of peak equity — reset to resume"
    if hhmm < cfg.entry_from or hhmm > until:
        return False, f"outside the entry window ({cfg.entry_from}-{until})"
    if st.paused_until and hhmm < st.paused_until:
        return False, f"cooling down after {cfg.loss_streak} losses in a row (until {st.paused_until})"
    if st.trades >= cfg.max_trades_per_day:
        return False, f"{cfg.max_trades_per_day} trades already today"
    if open_positions >= cfg.max_concurrent:
        return False, f"{cfg.max_concurrent} positions already open"
    if st.realized + open_pnl <= -cfg.max_daily_loss_pct / 100 * cfg.capital:
        return False, f"daily loss limit ({cfg.max_daily_loss_pct}% of capital) reached"
    if cfg.cooldown_after_exit_min and last_exit_hhmm:
        h, m = map(int, last_exit_hhmm.split(":"))
        resume = h * 60 + m + cfg.cooldown_after_exit_min
        if now.hour * 60 + now.minute < resume:
            return False, f"{cfg.cooldown_after_exit_min}-minute cooldown after the last exit"
    return True, ""


def size(cfg: RiskConfig, equity: float, entry: float, stop: float | None, atr: float | None) -> tuple[float, str]:
    """Notional for a new position (Rs) and how it was sized."""
    cap = cfg.max_position_pct / 100 * equity
    dist = abs(entry - stop) if stop else (0.5 * atr if atr and atr == atr else None)
    if not dist or dist <= 0:
        return cap, "position cap (no stop or ATR to size from)"
    risk_rs = cfg.risk_per_trade_pct / 100 * equity
    by_risk = risk_rs / dist * entry
    if by_risk < cap:
        return by_risk, f"risk {cfg.risk_per_trade_pct}% of equity to a stop {dist / entry * 1e4:.0f} bp away"
    return cap, f"position cap {cfg.max_position_pct:.0f}% (risk sizing allowed more)"


def after_close(cfg: RiskConfig, st: DayState, net: float, now: datetime, equity: float) -> DayState:
    """Book a closed trade into the day: streak, pause, drawdown halt."""
    st.realized += net
    st.loss_streak = st.loss_streak + 1 if net < 0 else 0
    if cfg.loss_streak and st.loss_streak >= cfg.loss_streak:
        m = now.hour * 60 + now.minute + cfg.streak_cooldown_min
        st.paused_until = f"{min(m // 60, 23):02d}:{m % 60:02d}"
        st.loss_streak = 0
    st.peak_equity = max(st.peak_equity, equity)
    if st.peak_equity > 0 and equity <= st.peak_equity * (1 - cfg.max_drawdown_pct / 100):
        st.halted = True
    return st


def units_for(notional: float, price: float, whole: bool) -> float:
    """ETF shares are whole; index-point units are notional / level."""
    if price <= 0:
        return 0.0
    q = notional / price
    return float(math.floor(q)) if whole else q
