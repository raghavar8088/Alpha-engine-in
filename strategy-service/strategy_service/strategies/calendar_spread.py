"""Strategy #41 — Calendar Spread. Trades the NEAR/FAR contract basis: enter when the
spread z-score stretches, exit on normalization. Structurally a TWO-LEG strategy — it
needs synchronized near+far contract series, which the single-series backtest context
cannot supply. The module defines the full parameterization now; it activates when the
options/futures service (Phase 7) provides multi-leg data, and until then emits no
signals (validation will report it as awaiting data, not as failed)."""

from pydantic import BaseModel, Field

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, Timeframe


@register_strategy
class CalendarSpread(Strategy):
    metadata = StrategyMetadata(
        strategy_id="calendar_spread",
        name="Calendar Spread",
        category="futures",
        description="Near/far futures basis mean-reversion (spread z-score entry, "
        "normalization exit). Requires two synchronized contract legs - activates "
        "with the Phase 7 futures-chain feed.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.INDEX_FUTURE, AssetClass.EQUITY_FUTURE],
        suitable_market="range-bound",
        expected_win_rate=0.55,
        risk_reward=1.2,
    )

    class Params(BaseModel):
        spread_window: int = Field(default=20, ge=5, description="z-score window over the basis")
        entry_z: float = Field(default=2.0, gt=0)
        exit_z: float = Field(default=0.5, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.spread_window + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        # Two-leg data (near + far contract) is not representable in the single-series
        # context; the live/backtest multi-leg runner lands with options-service.
        return None
