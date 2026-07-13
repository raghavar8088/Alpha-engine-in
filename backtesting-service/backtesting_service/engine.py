"""Event-driven backtest core.

Execution model (deliberately conservative, no look-ahead):
- A signal produced on bar t's close fills at bar t+1's OPEN, slippage-adjusted.
- Stops/targets are checked intra-bar against each bar's high/low; if both could have
  triggered in the same bar, the STOP is assumed to have hit first (worst case).
- An opposite entry while positioned is a stop-and-reverse: close, then open.
- Partial fills: order quantity is capped at `max_volume_participation` x bar volume.
- Equity is marked to market on every bar close -> the equity curve series.
- Whatever is open at the end is closed at the last bar's close ("end" exit).
"""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from backtesting_service.costs import CostModel
from risk_service import RiskEngine, RiskLimits, SizingConfig, SizingMethod
from strategy_service.indicators import atr as _atr_series
from strategy_service.indicators import stdev as _stdev_series
from tradingai_shared.contracts import Strategy, StrategyContext
from tradingai_shared.domain import (
    AssetClass,
    Bar,
    SignalAction,
    Timeframe,
    Trade,
    TradeStatus,
    TransactionType,
)

INTRADAY_TIMEFRAMES = {Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1}
_SIZING_ATR_PERIOD = 14
_SIZING_VOL_PERIOD = 20
_SIZING_KELLY_MIN_TRADES = 10


class BacktestConfig(BaseModel):
    strategy_id: str
    symbol: str
    timeframe: Timeframe
    initial_capital: float = Field(default=1_000_000, gt=0)
    position_size_pct: float = Field(default=100.0, gt=0, le=100.0)  # % of equity per entry (CAPITAL_PCT sizing)
    slippage_bps: float = Field(default=5.0, ge=0)  # applied against you on every fill
    max_volume_participation: float = Field(default=0.1, ge=0)  # 0 disables the cap
    allow_short: bool = True
    asset_class: AssetClass = AssetClass.INDEX
    lot_size: int = Field(default=1, ge=1)
    sector: str | None = None
    params: dict = {}
    costs: CostModel = CostModel()

    # Phase 4: every entry is sized and approved by RiskEngine. Defaults reproduce
    # pre-Phase-4 behavior exactly (CAPITAL_PCT sizing off position_size_pct, every
    # limit permissive) so already-validated Phase 3 results don't shift silently.
    sizing_method: SizingMethod = SizingMethod.CAPITAL_PCT
    risk_pct: float = Field(default=1.0, gt=0, description="for FIXED_FRACTIONAL / ATR / KELLY fallback")
    atr_stop_mult: float = Field(default=2.0, gt=0, description="for ATR sizing's implied stop distance")
    target_daily_vol_pct: float = Field(default=1.0, gt=0, description="for VOLATILITY sizing")
    kelly_cap: float = Field(default=0.25, gt=0, le=1)
    risk_limits: RiskLimits = RiskLimits()


class BacktestRun(BaseModel):
    """Raw simulation output; metrics.py and charts.py derive everything else from it."""

    config: BacktestConfig
    trades: list[Trade]
    equity_ts: list[datetime]
    equity: list[float]
    bars_in_market: int
    total_bars: int
    total_charges: float
    risk_rejections: list[str] = []  # reasons RiskEngine blocked/trimmed an entry, deduplicated


class _OpenPosition:
    def __init__(self, trade: Trade, entry_charges: float):
        self.trade = trade
        self.entry_charges = entry_charges


class BacktestEngine:
    def __init__(self, strategy: Strategy, config: BacktestConfig):
        self.strategy = strategy
        self.config = config
        self.product = config.costs.product_for(
            config.asset_class, config.timeframe in INTRADAY_TIMEFRAMES
        )
        self.risk = RiskEngine(config.risk_limits)
        self.sizing = SizingConfig(
            method=config.sizing_method,
            capital_pct=config.position_size_pct,
            risk_pct=config.risk_pct,
            atr_mult=config.atr_stop_mult,
            target_daily_vol_pct=config.target_daily_vol_pct,
            kelly_cap=config.kelly_cap,
        )
        self._risk_rejections: list[str] = []

    def run(self, bars: list[Bar], benchmark_bars: list[Bar] | None = None) -> BacktestRun:
        cfg = self.config
        benchmark_by_ts = (
            {b.ts: b.close for b in benchmark_bars}
            if benchmark_bars and getattr(self.strategy, "requires_benchmark", False)
            else None
        )
        ctx = StrategyContext(
            max_bars=max(500, self.strategy.warmup + 2), benchmark_by_ts=benchmark_by_ts
        )
        cash = cfg.initial_capital
        position: _OpenPosition | None = None
        pending: SignalAction | None = None  # signal awaiting next-bar-open execution
        pending_signal_meta: dict = {}
        trades: list[Trade] = []
        equity_ts: list[datetime] = []
        equity: list[float] = []
        bars_in_market = 0
        total_charges = 0.0

        for i, bar in enumerate(bars):
            # 1) Execute last bar's signal at this bar's open (risk-checked entries)
            if pending is not None:
                cash, position, charges = self._execute(
                    pending, pending_signal_meta, bar, cash, position, trades, ctx
                )
                total_charges += charges
                pending = None

            # 2) Intra-bar stop/target on the open position (stop wins ties)
            if position is not None:
                exit_price, reason = self._check_stop_target(position.trade, bar)
                if exit_price is not None:
                    delta, charges = self._close(position, exit_price, bar.ts, reason, trades)
                    cash += delta
                    total_charges += charges
                    position = None

            # 3) Feed the strategy; queue any signal for next bar's open
            ctx.push(bar)
            if i + 1 >= self.strategy.warmup:
                signal = self.strategy.on_bar(ctx)
                if signal is not None and signal.signal != SignalAction.HOLD:
                    pending = signal.signal
                    pending_signal_meta = {"stop_loss": signal.stop_loss, "target": signal.target}

            # 4) Mark to market, then advance the risk engine's peak/day tracking so
            # next bar's entry decision (step 1) sees today's kill-switch state.
            if position is not None:
                bars_in_market += 1
            equity_ts.append(bar.ts)
            equity_now = cash + self._position_value(position, bar.close)
            equity.append(equity_now)
            self.risk.update_equity(equity_now, day_key=bar.ts.date())

        # 5) Force-close anything still open at the last close
        if position is not None:
            delta, charges = self._close(position, bars[-1].close, bars[-1].ts, "end", trades)
            cash += delta
            total_charges += charges
            equity[-1] = cash

        return BacktestRun(
            config=cfg,
            trades=trades,
            equity_ts=equity_ts,
            equity=equity,
            bars_in_market=bars_in_market,
            total_bars=len(bars),
            total_charges=round(total_charges, 2),
            risk_rejections=sorted(set(self._risk_rejections)),
        )

    # -- execution helpers -------------------------------------------------

    def _execute(
        self,
        action: SignalAction,
        meta: dict,
        bar: Bar,
        cash: float,
        position: _OpenPosition | None,
        trades: list[Trade],
        ctx: StrategyContext,
    ) -> tuple[float, _OpenPosition | None, float]:
        charges_sum = 0.0

        wants_long = action == SignalAction.BUY
        wants_short = action == SignalAction.SELL and self.config.allow_short
        exits_long = action == SignalAction.EXIT_LONG
        exits_short = action == SignalAction.EXIT_SHORT

        if position is not None:
            direction = position.trade.direction
            should_close = (
                (exits_long and direction == TransactionType.BUY)
                or (exits_short and direction == TransactionType.SELL)
                or (wants_long and direction == TransactionType.SELL)  # reverse
                or (wants_short and direction == TransactionType.BUY)
            )
            if should_close:
                fill = self._slip(bar.open, selling=direction == TransactionType.BUY)
                delta, charges = self._close(position, fill, bar.ts, "signal", trades)
                cash += delta
                charges_sum += charges
                position = None

        if position is None and (wants_long or wants_short):
            fill = self._slip(bar.open, selling=wants_short)
            quantity = self._size(cash, fill, bar.volume, meta.get("stop_loss"), trades, ctx)
            if quantity > 0:
                is_buy = wants_long
                charges = self.config.costs.order_charges(self.product, fill, quantity, is_buy)
                charges_sum += charges
                trade = Trade(
                    trade_id=uuid4().hex[:12],
                    strategy_id=self.strategy.metadata.strategy_id,
                    symbol=self.config.symbol,
                    direction=TransactionType.BUY if wants_long else TransactionType.SELL,
                    quantity=quantity,
                    entry_price=round(fill, 2),
                    entry_ts=bar.ts,
                    stop_loss=meta.get("stop_loss"),
                    target=meta.get("target"),
                    charges=round(charges, 2),
                )
                # Cash accounting is long-notional for both directions (a v1
                # simplification: shorts earn/lose the same P&L, margin not modelled).
                cash -= fill * quantity + charges
                position = _OpenPosition(trade, charges)

        return cash, position, charges_sum

    def _check_stop_target(self, trade: Trade, bar: Bar) -> tuple[float | None, str]:
        if trade.direction == TransactionType.BUY:
            if trade.stop_loss is not None and bar.low <= trade.stop_loss:
                return self._slip(min(trade.stop_loss, bar.open), selling=True), "stop_loss"
            if trade.target is not None and bar.high >= trade.target:
                return self._slip(max(trade.target, bar.open), selling=True), "target"
        else:
            if trade.stop_loss is not None and bar.high >= trade.stop_loss:
                return self._slip(max(trade.stop_loss, bar.open), selling=False), "stop_loss"
            if trade.target is not None and bar.low <= trade.target:
                return self._slip(min(trade.target, bar.open), selling=False), "target"
        return None, ""

    def _close(
        self, position: _OpenPosition, price: float, ts: datetime, reason: str, trades: list[Trade]
    ) -> tuple[float, float]:
        trade = position.trade
        is_buy_to_cover = trade.direction == TransactionType.SELL
        charges = self.config.costs.order_charges(self.product, price, trade.quantity, is_buy_to_cover)

        sign = 1 if trade.direction == TransactionType.BUY else -1
        gross = (price - trade.entry_price) * trade.quantity * sign
        trade.exit_price = round(price, 2)
        trade.exit_ts = ts
        trade.status = TradeStatus.CLOSED
        trade.exit_reason = reason
        trade.charges = round(trade.charges + charges, 2)
        trade.pnl = round(gross - trade.charges, 2)
        trades.append(trade)

        # Long-notional cash accounting (see _execute): the CASH DELTA to add back —
        # entry notional + gross P&L - exit charges (entry charges were paid on entry)
        cash_delta = trade.entry_price * trade.quantity + gross - charges
        return cash_delta, charges

    def _position_value(self, position: _OpenPosition | None, mark: float) -> float:
        if position is None:
            return 0.0
        trade = position.trade
        sign = 1 if trade.direction == TransactionType.BUY else -1
        return trade.entry_price * trade.quantity + (mark - trade.entry_price) * trade.quantity * sign

    def _slip(self, price: float, selling: bool) -> float:
        """Slippage-adjusted fill, rounded to the paisa — real fills are tick-quantized,
        and cash/trade records must use the SAME price or sub-paisa residue leaks."""
        adj = price * self.config.slippage_bps / 10_000
        return round(price - adj if selling else price + adj, 2)

    def _size(
        self, cash: float, price: float, bar_volume: int, stop_loss: float | None,
        trades: list[Trade], ctx: StrategyContext,
    ) -> int:
        """Every entry is sized and approved by RiskEngine (Phase 4). This engine only
        ever holds 0 or 1 position, so `open_positions` is always empty here — the
        limits still bound the size of THIS entry against equity (exposure, heat),
        they just never see a second concurrent position (that's Phase 5's job, across
        multiple concurrently-run strategies)."""
        atr_value = None
        price_stdev_pct = None
        if self.sizing.method == SizingMethod.ATR and len(ctx.bars) > _SIZING_ATR_PERIOD:
            atr_value = _atr_series(ctx.bars, _SIZING_ATR_PERIOD)[-1]
        if self.sizing.method == SizingMethod.VOLATILITY and len(ctx.bars) > _SIZING_VOL_PERIOD:
            price_stdev_pct = _stdev_series(ctx.closes, _SIZING_VOL_PERIOD)[-1] / ctx.bars[-1].close * 100

        win_rate = avg_win = avg_loss = None
        if self.sizing.method == SizingMethod.KELLY:
            closed = [t for t in trades if t.pnl is not None]
            if len(closed) >= _SIZING_KELLY_MIN_TRADES:
                wins = [t.pnl for t in closed if t.pnl > 0]
                losses = [-t.pnl for t in closed if t.pnl <= 0]
                if wins and losses:
                    win_rate = len(wins) / len(closed)
                    avg_win = sum(wins) / len(wins)
                    avg_loss = sum(losses) / len(losses)

        decision = self.risk.evaluate(
            price=price,
            equity=cash,
            open_positions=[],
            sizing=self.sizing,
            instrument_sector=self.config.sector,
            stop_loss=stop_loss,
            lot_size=self.config.lot_size,
            atr=atr_value,
            price_stdev_pct=price_stdev_pct,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
        )
        if not decision.approved:
            self._risk_rejections.extend(decision.reasons)
            return 0

        quantity = decision.quantity
        if self.config.max_volume_participation > 0 and bar_volume > 0:
            cap = int(bar_volume * self.config.max_volume_participation)
            cap -= cap % self.config.lot_size  # keep lot multiples
            quantity = min(quantity, cap)  # partial fill: liquidity-capped
        return max(quantity, 0)
