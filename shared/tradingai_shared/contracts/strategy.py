"""The Strategy plugin contract and registry.

A strategy is a pure signal generator: it sees bars via a StrategyContext and may emit a
Signal. It never talks to brokers, risk, or storage — those consume its Signals. This is
what lets the same strategy module run unchanged in backtest, paper, replay, and live."""

from abc import ABC, abstractmethod
from typing import Type

from pydantic import BaseModel

from tradingai_shared.domain.enums import AssetClass, Timeframe
from tradingai_shared.domain.models import Bar, Signal


class StrategyMetadata(BaseModel):
    """The spec block every strategy must declare (surfaced by GET /api/strategies)."""

    strategy_id: str  # stable slug, e.g. "ema_cross"
    name: str
    category: str  # "trend" | "momentum" | "mean_reversion" | "swing" | "intraday" | "futures" | "options"
    description: str
    timeframes: list[Timeframe]
    asset_classes: list[AssetClass]
    suitable_market: str  # e.g. "trending", "range-bound", "high-volatility"
    expected_win_rate: float | None = None  # historical expectation, not a promise
    risk_reward: float | None = None  # typical target/stop ratio


class StrategyContext:
    """Rolling view of market state handed to Strategy.on_bar(). The runner (backtester
    or live engine) owns and updates it; strategies only read from it.

    `benchmark_by_ts` (optional) maps bar timestamp -> benchmark close (e.g. NIFTY) for
    relative-strength style strategies; runners populate it only for strategies that
    declare `requires_benchmark = True`."""

    def __init__(self, max_bars: int = 500, benchmark_by_ts: dict | None = None):
        self.bars: list[Bar] = []
        self._max_bars = max_bars
        self.benchmark_by_ts = benchmark_by_ts or {}

    def push(self, bar: Bar) -> None:
        self.bars.append(bar)
        if len(self.bars) > self._max_bars:
            del self.bars[: len(self.bars) - self._max_bars]

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def current(self) -> Bar:
        return self.bars[-1]

    def benchmark_closes(self) -> list[float] | None:
        """Benchmark closes aligned to self.bars (None if any timestamp is missing —
        strategies should return no signal rather than misalign)."""
        if not self.benchmark_by_ts:
            return None
        out = []
        for bar in self.bars:
            value = self.benchmark_by_ts.get(bar.ts)
            if value is None:
                return None
            out.append(value)
        return out


class Strategy(ABC):
    """Base class for all strategies. Subclasses must set `metadata`, may set `Params`
    (a pydantic model defining their tunable parameters + defaults, which doubles as the
    optimizer's parameter schema), and implement `on_bar`.

    Strategy instances are per-run and may hold state (position flags, counters); never
    reuse an instance across runs."""

    metadata: StrategyMetadata
    requires_benchmark: bool = False  # runners feed ctx.benchmark_by_ts when True

    class Params(BaseModel):
        pass

    def __init__(self, params: dict | None = None):
        self.params = self.Params(**(params or {}))

    @property
    def warmup(self) -> int:
        """Bars needed before on_bar() output is meaningful; runners feed history
        through the context but discard signals until warmup is reached."""
        return 0

    @abstractmethod
    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        """Called once per completed bar (ctx.current). Return a Signal or None."""


STRATEGY_REGISTRY: dict[str, Type[Strategy]] = {}


def register_strategy(cls: Type[Strategy]) -> Type[Strategy]:
    """Class decorator: adds the strategy to STRATEGY_REGISTRY keyed by its
    metadata.strategy_id. Importing a strategy module is all it takes to register it."""
    sid = cls.metadata.strategy_id
    if sid in STRATEGY_REGISTRY and STRATEGY_REGISTRY[sid] is not cls:
        raise ValueError(f"Duplicate strategy_id {sid!r}")
    STRATEGY_REGISTRY[sid] = cls
    return cls
