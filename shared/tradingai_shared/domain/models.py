from datetime import date, datetime

from pydantic import BaseModel, Field

from tradingai_shared.domain.enums import (
    AssetClass,
    ExchangeSegment,
    OptionType,
    SignalAction,
    Timeframe,
    TradeStatus,
    TransactionType,
)


class Instrument(BaseModel):
    """One tradeable instrument from the universe (Mongo `instruments` collection).
    security_id/exchange_segment are Dhan's identifiers so orders and history requests
    need no lookup translation."""

    symbol: str
    name: str = ""
    security_id: str
    exchange_segment: ExchangeSegment
    asset_class: AssetClass
    lot_size: int = 1
    tick_size: float = 0.05
    # Derivatives only
    underlying_symbol: str | None = None
    expiry: date | None = None
    strike: float | None = None
    option_type: OptionType | None = None


class Bar(BaseModel):
    """One OHLCV candle (Mongo `bars` collection, unique on symbol+timeframe+ts)."""

    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    oi: int | None = None  # open interest, derivatives only


class Signal(BaseModel):
    """The normalized trade-idea schema. Every producer — strategies, the research
    engine, AI modules — emits exactly this; risk/execution consume exactly this."""

    symbol: str
    timeframe: Timeframe
    signal: SignalAction
    confidence: float = Field(ge=0, le=1, default=0.5)
    stop_loss: float | None = None
    target: float | None = None
    source: str  # strategy id or research source name
    timestamp: datetime
    reasoning: str = ""


class Fill(BaseModel):
    """One execution (real from broker-service's order-update stream, or simulated
    by the paper/backtest path)."""

    order_id: str
    symbol: str
    transaction_type: TransactionType
    quantity: int
    price: float
    ts: datetime
    charges: float = 0.0  # total costs attributed to this fill (backtest cost model)


class Trade(BaseModel):
    """One round-trip (entry fill → exit fill) attributed to a strategy — the unit the
    backtester and portfolio analytics aggregate over."""

    trade_id: str
    strategy_id: str
    symbol: str
    direction: TransactionType  # BUY = long trade, SELL = short trade
    quantity: int
    entry_price: float
    entry_ts: datetime
    exit_price: float | None = None
    exit_ts: datetime | None = None
    stop_loss: float | None = None
    target: float | None = None
    status: TradeStatus = TradeStatus.OPEN
    pnl: float | None = None  # net of charges, set on close
    charges: float = 0.0
    exit_reason: str = ""  # "target" | "stop_loss" | "signal" | "eod" | ...


class Position(BaseModel):
    """Current net position in one instrument for one strategy (or 'portfolio' for
    the aggregate view)."""

    symbol: str
    strategy_id: str
    quantity: int  # signed: negative = short
    avg_price: float
    last_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0


class RiskDecision(BaseModel):
    """Output of Risk.approve()/size(): every Signal must pass through one of these
    before becoming an order, in every mode (backtest, paper, live)."""

    approved: bool
    quantity: int = 0
    reasons: list[str] = []  # populated on rejection or size reduction


class BacktestResult(BaseModel):
    """Summary of one backtest run (full metric set lands in Phase 2; this carries the
    core fields the strategy registry and validation gate need from day one)."""

    strategy_id: str
    symbol: str
    timeframe: Timeframe
    start: datetime
    end: datetime
    initial_capital: float
    net_profit: float
    total_trades: int
    win_rate: float | None = None
    profit_factor: float | None = None
    expectancy: float | None = None
    max_drawdown_pct: float | None = None
    cagr: float | None = None
    sharpe: float | None = None
    params: dict = {}
    metrics: dict = {}  # extended Phase-2 metric set, keyed by metric name
