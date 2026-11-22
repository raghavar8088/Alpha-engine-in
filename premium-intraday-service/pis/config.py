"""Settings of the desk. Every risk number here is an initial research setting the owner can change (env or the
module's own settings document); none is tuned on results."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Risk:
    capital: float = 1_000_000.0          # Rs 10 lakh virtual portfolio
    risk_per_trade: float = 0.0025        # 0.25% of the day's starting equity, planned stop risk incl. costs
    max_open_risk: float = 0.0075         # 0.75% total open stop risk
    max_positions: int = 3
    daily_loss_stop: float = 0.01         # realised + unrealised loss of 1% -> no new entries that day
    max_per_sector: int = 2               # positions in one sector
    max_sector_risk: float = 0.005        # open stop risk in one sector (2/3 of the total)
    max_notional_frac: float = 0.50       # one position <= 50% of equity
    max_gross_frac: float = 1.50          # all positions <= 1.5x equity (MIS margin needs about 20-25% of this)
    max_participation: float = 0.02       # an order takes at most 2% of the trigger bar's volume (else a partial)

    @classmethod
    def from_env(cls) -> "Risk":
        return cls(
            capital=_f("PIS_CAPITAL", cls.capital),
            risk_per_trade=_f("PIS_RISK_PER_TRADE", cls.risk_per_trade),
            max_open_risk=_f("PIS_MAX_OPEN_RISK", cls.max_open_risk),
            max_positions=_i("PIS_MAX_POSITIONS", cls.max_positions),
            daily_loss_stop=_f("PIS_DAILY_LOSS_STOP", cls.daily_loss_stop),
            max_per_sector=_i("PIS_MAX_PER_SECTOR", cls.max_per_sector),
            max_sector_risk=_f("PIS_MAX_SECTOR_RISK", cls.max_sector_risk),
            max_notional_frac=_f("PIS_MAX_NOTIONAL_FRAC", cls.max_notional_frac),
            max_gross_frac=_f("PIS_MAX_GROSS_FRAC", cls.max_gross_frac),
            max_participation=_f("PIS_MAX_PARTICIPATION", cls.max_participation),
        )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Clock:
    """Session times, minutes after midnight IST. Entries are decided at five-minute bar closes."""
    open_min: int = 9 * 60 + 15           # 09:15 first trade
    plan_min: int = 9 * 60 + 45           # 09:45 trade plan published; monitoring starts
    last_entry_min: int = 14 * 60 + 30    # no new entries after a bar closing at 14:30
    squareoff_min: int = 15 * 60 + 5      # square-off begins on the 15:00-15:05 bar's close
    flat_min: int = 15 * 60 + 10          # target: flat by 15:10 (one retry on the 15:05-15:10 bar)
    close_min: int = 15 * 60 + 30
    checkpoints: tuple = ("PRE", "0915", "0920", "0930", "0940", "0945")


@dataclass(frozen=True)
class Universe:
    size: int = 150                       # top N by 20-session median traded value
    min_price: float = 50.0
    min_sessions: int = 15                # sessions of history needed for the baselines
    lookback: int = 20                    # sessions for traded value, volume baselines, OR widths
    ca_gap: float = 0.15                  # |open vs official prev close| above this = probable corporate action


@dataclass(frozen=True)
class Costs:
    # Slippage per side by the stock's 20-session median daily traded value (Rs crore), measured from Angel's live
    # order book at 3,355 tournament entries (H1 study; INTRADAY_STOCKS_54_STRATEGY_AUDIT.md section "Costs").
    bands: tuple = ((1000.0, 1.50), (300.0, 2.85), (150.0, 3.73), (0.0, 4.12))
    stress: float = 1.0                   # multiplier for the stress tests (2x, 3x)


@dataclass(frozen=True)
class Settings:
    risk: Risk = field(default_factory=Risk)
    clock: Clock = field(default_factory=Clock)
    universe: Universe = field(default_factory=Universe)
    costs: Costs = field(default_factory=Costs)
