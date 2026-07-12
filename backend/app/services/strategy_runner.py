"""StrategyRunner — the roadmap Phase 5 mode switch.

Lives in the backend (not strategy-service) deliberately: it needs BOTH
`backtesting_service.BacktestEngine` (for REPLAY/SIMULATION/BACKTEST) and
`app.services.dhan_client` (for LIVE order placement), and backtesting-service
already depends on strategy-service — putting it there would create a cycle.

REPLAY / SIMULATION / BACKTEST are one-shot: they hand a bar sequence straight to
`BacktestEngine.run()`, so "the same strategy switches to Replay with identical
logic" is true by construction (it's the literal same engine), not by re-implementing
the rules. PAPER / LIVE process one live, FINALIZED bar at a time, reusing the exact
same `Strategy`/`StrategyContext`/`RiskEngine` objects but filling immediately at the
bar's close (real-time execution has no look-ahead problem to dodge, unlike a
backtest) instead of waiting a bar for an "open" that doesn't exist yet in real time.
"""

from datetime import datetime, timezone
from uuid import uuid4

from backtesting_service.costs import CostModel
from backtesting_service.engine import INTRADAY_TIMEFRAMES, BacktestConfig, BacktestEngine
from backtesting_service.metrics import compute_metrics
from risk_service import PositionSnapshot, RiskEngine, RiskLimits, SizingConfig
from tradingai_shared.contracts import STRATEGY_REGISTRY, Strategy, StrategyContext
from tradingai_shared.domain import (
    AssetClass,
    Bar,
    ExecutionMode,
    Fill,
    Signal,
    SignalAction,
    Timeframe,
    Trade,
    TradeStatus,
    TransactionType,
)

ONE_SHOT_MODES = {ExecutionMode.HISTORICAL, ExecutionMode.BACKTEST, ExecutionMode.REPLAY, ExecutionMode.SIMULATION}


class PaperExecutor:
    """Simulated fill at the reference price, costed like the backtester."""

    def __init__(self, cost_model: CostModel, product: str):
        self.cost_model = cost_model
        self.product = product

    async def execute(self, symbol: str, direction: TransactionType, quantity: int, price: float) -> Fill:
        charges = self.cost_model.order_charges(self.product, price, quantity, direction == TransactionType.BUY)
        return Fill(
            order_id=f"PAPER-{uuid4().hex[:10]}", symbol=symbol, transaction_type=direction,
            quantity=quantity, price=price, ts=datetime.now(timezone.utc), charges=round(charges, 2),
        )


class LiveExecutor:
    """Places a REAL market order via Dhan. The recorded `price`/`charges` are our
    reference/estimate, logged at signal time — the real fill price comes from Dhan
    and isn't reconciled back into this record in v1 (that needs the order-update
    stream broker-service already runs; wiring it into this ledger is a follow-up)."""

    def __init__(self, dhan_client, security_id: str, exchange_segment: str, product_type: str, cost_model: CostModel, product: str):
        self.client = dhan_client
        self.security_id = security_id
        self.exchange_segment = exchange_segment
        self.product_type = product_type
        self.cost_model = cost_model
        self.product = product

    async def execute(self, symbol: str, direction: TransactionType, quantity: int, price: float) -> Fill:
        result = await self.client.place_order(
            security_id=self.security_id, exchange_segment=self.exchange_segment,
            transaction_type=direction.value, quantity=quantity, order_type="MARKET",
            product_type=self.product_type, price=0,
        )
        order_id = result.get("data", {}).get("orderId", "") if isinstance(result, dict) else ""
        charges = self.cost_model.order_charges(self.product, price, quantity, direction == TransactionType.BUY)
        return Fill(
            order_id=order_id or f"LIVE-{uuid4().hex[:10]}", symbol=symbol, transaction_type=direction,
            quantity=quantity, price=price, ts=datetime.now(timezone.utc), charges=round(charges, 2),
        )


def _check_stop_target(trade: Trade, bar: Bar) -> tuple[float | None, str]:
    """Mirrors BacktestEngine._check_stop_target (worst-case: stop wins a same-bar
    tie) — duplicated rather than imported from a private method, so a change to one
    doesn't silently change the other's execution semantics."""
    if trade.direction == TransactionType.BUY:
        if trade.stop_loss is not None and bar.low <= trade.stop_loss:
            return trade.stop_loss, "stop_loss"
        if trade.target is not None and bar.high >= trade.target:
            return trade.target, "target"
    else:
        if trade.stop_loss is not None and bar.high >= trade.stop_loss:
            return trade.stop_loss, "stop_loss"
        if trade.target is not None and bar.low <= trade.target:
            return trade.target, "target"
    return None, ""


class StrategyRunner:
    def __init__(
        self,
        run_id: str,
        strategy: Strategy,
        symbol: str,
        timeframe: Timeframe,
        mode: ExecutionMode,
        risk: RiskEngine,
        sizing: SizingConfig,
        cost_model: CostModel,
        asset_class: AssetClass,
        lot_size: int,
        executor: PaperExecutor | LiveExecutor | None,
        initial_capital: float,
        bootstrap_bars: list[Bar],
    ):
        self.run_id = run_id
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self.mode = mode
        self.risk = risk
        self.sizing = sizing
        self.executor = executor
        self.lot_size = lot_size
        self.product = cost_model.product_for(asset_class, timeframe in INTRADAY_TIMEFRAMES)

        self.cash = initial_capital
        self.position: Trade | None = None
        self.trades: list[Trade] = []
        self.last_signal: Signal | None = None
        self.last_action: str | None = None  # what actually happened last: "entry" / "stop_loss" / "target" / "signal_exit"

        self.ctx = StrategyContext(max_bars=max(500, strategy.warmup + 2))
        for bar in bootstrap_bars:
            self.ctx.push(bar)

    @property
    def equity(self) -> float:
        if self.position is None:
            return self.cash
        sign = 1 if self.position.direction == TransactionType.BUY else -1
        mark = self.ctx.current.close if self.ctx.bars else self.position.entry_price
        return self.cash + self.position.entry_price * self.position.quantity + (
            mark - self.position.entry_price
        ) * self.position.quantity * sign

    def snapshot(self) -> dict:
        """`last_signal` is whatever the strategy most recently computed — it may be a
        no-op (e.g. an EXIT_LONG re-fired while already flat). `last_action` is what
        actually changed the position, so a stop-loss firing ahead of the strategy's
        own lagging exit signal doesn't get misreported as a signal-driven close."""
        return {
            "run_id": self.run_id,
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "position": self.position.model_dump(mode="json") if self.position else None,
            "last_signal": self.last_signal.model_dump(mode="json") if self.last_signal else None,
            "last_action": self.last_action,
            "closed_trades": len(self.trades),
            "total_pnl": round(sum(t.pnl or 0 for t in self.trades), 2),
            "recent_trades": [t.model_dump(mode="json") for t in self.trades[-20:]],
        }

    async def on_finalized_bar(self, bar: Bar) -> dict:
        """PAPER/LIVE only: process one just-completed live bar. Returns the run's
        latest snapshot for the caller to persist."""
        # 1) intrabar stop/target on any open position, off the bar just completed
        if self.position is not None:
            exit_price, reason = _check_stop_target(self.position, bar)
            if exit_price is not None:
                await self._close(exit_price, bar.ts, reason)

        # 2) feed the strategy
        self.ctx.push(bar)
        if len(self.ctx.bars) < self.strategy.warmup:
            return self.snapshot()
        signal = self.strategy.on_bar(self.ctx)
        if signal is None or signal.signal == SignalAction.HOLD:
            return self.snapshot()
        self.last_signal = signal

        # 3) act on it at the bar's close (no look-ahead concern live - this IS "now")
        await self._act(signal, bar)
        return self.snapshot()

    async def _act(self, signal: Signal, bar: Bar) -> None:
        wants_long = signal.signal == SignalAction.BUY
        wants_short = signal.signal == SignalAction.SELL
        exits_long = signal.signal == SignalAction.EXIT_LONG
        exits_short = signal.signal == SignalAction.EXIT_SHORT

        if self.position is not None:
            direction = self.position.direction
            should_close = (
                (exits_long and direction == TransactionType.BUY)
                or (exits_short and direction == TransactionType.SELL)
                or (wants_long and direction == TransactionType.SELL)
                or (wants_short and direction == TransactionType.BUY)
            )
            if should_close:
                await self._close(bar.close, bar.ts, "signal")

        if self.position is None and (wants_long or wants_short) and self.executor is not None:
            decision = self.risk.evaluate(
                price=bar.close, equity=self.equity, open_positions=[], sizing=self.sizing,
                stop_loss=signal.stop_loss, lot_size=self.lot_size,
            )
            if not decision.approved:
                return
            direction = TransactionType.BUY if wants_long else TransactionType.SELL
            fill = await self.executor.execute(self.symbol, direction, decision.quantity, bar.close)
            self.cash -= fill.price * fill.quantity + fill.charges
            self.position = Trade(
                trade_id=uuid4().hex[:12], strategy_id=self.strategy.metadata.strategy_id,
                symbol=self.symbol, direction=direction, quantity=fill.quantity,
                entry_price=fill.price, entry_ts=fill.ts,
                stop_loss=signal.stop_loss, target=signal.target, charges=fill.charges,
            )
            self.last_action = "entry"

    async def _close(self, price: float, ts: datetime, reason: str) -> None:
        trade = self.position
        direction_to_close = TransactionType.SELL if trade.direction == TransactionType.BUY else TransactionType.BUY
        fill = await self.executor.execute(self.symbol, direction_to_close, trade.quantity, price)

        sign = 1 if trade.direction == TransactionType.BUY else -1
        gross = (fill.price - trade.entry_price) * trade.quantity * sign
        trade.exit_price = fill.price
        trade.exit_ts = fill.ts
        trade.status = TradeStatus.CLOSED
        trade.exit_reason = reason
        trade.charges = round(trade.charges + fill.charges, 2)
        trade.pnl = round(gross - trade.charges, 2)

        self.cash += trade.entry_price * trade.quantity + gross - fill.charges
        self.trades.append(trade)
        self.position = None
        self.last_action = reason


def run_one_shot(
    strategy_id: str, symbol: str, timeframe: Timeframe, bars: list[Bar],
    mode: ExecutionMode, initial_capital: float = 1_000_000,
    params: dict | None = None, config_overrides: dict | None = None,
    benchmark_bars: list[Bar] | None = None,
) -> dict:
    """REPLAY / SIMULATION / BACKTEST / HISTORICAL: a single BacktestEngine pass, no
    live loop. This is what makes "identical logic" to the backtester a fact rather
    than a promise."""
    strategy_cls = STRATEGY_REGISTRY[strategy_id]
    strategy = strategy_cls(params=params or {})
    if mode == ExecutionMode.HISTORICAL:
        from strategy_service.runner import run_historical

        signals = run_historical(strategy, bars)
        return {"mode": mode.value, "signals": [s.model_dump(mode="json") for s in signals]}

    config = BacktestConfig(
        strategy_id=strategy_id, symbol=symbol, timeframe=timeframe,
        initial_capital=initial_capital, params=params or {}, **(config_overrides or {}),
    )
    run = BacktestEngine(strategy, config).run(bars, benchmark_bars=benchmark_bars)
    return {"mode": mode.value, "metrics": compute_metrics(run), "trades": len(run.trades)}
