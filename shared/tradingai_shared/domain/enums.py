from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY_FUTURE = "EQUITY_FUTURE"
    INDEX_FUTURE = "INDEX_FUTURE"
    EQUITY_OPTION = "EQUITY_OPTION"
    INDEX_OPTION = "INDEX_OPTION"
    COMMODITY_FUTURE = "COMMODITY_FUTURE"
    COMMODITY_OPTION = "COMMODITY_OPTION"


class ExchangeSegment(str, Enum):
    """Dhan exchange-segment strings, reused verbatim so no mapping layer is needed
    when talking to the Dhan REST API (see backend/app/services/dhan_client.py)."""

    NSE_EQ = "NSE_EQ"
    NSE_FNO = "NSE_FNO"
    BSE_EQ = "BSE_EQ"
    BSE_FNO = "BSE_FNO"
    IDX_I = "IDX_I"
    MCX_COMM = "MCX_COMM"


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"

    @property
    def dhan_interval(self) -> int | None:
        """Dhan /charts/intraday interval in minutes; None for daily/weekly which use
        /charts/historical (weekly is aggregated from daily locally)."""
        return {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(self.value)


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    HOLD = "HOLD"


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"


class ProductType(str, Enum):
    CNC = "CNC"
    INTRADAY = "INTRADAY"
    MARGIN = "MARGIN"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExecutionMode(str, Enum):
    """How a strategy run sources bars and turns signals into (simulated or real)
    orders — the roadmap Phase 5 mode switch."""

    HISTORICAL = "HISTORICAL"  # pure signal generation over stored bars, no execution
    BACKTEST = "BACKTEST"  # full BacktestEngine run (costs, risk-sized fills)
    REPLAY = "REPLAY"  # BacktestEngine over a recent/specific historical window
    SIMULATION = "SIMULATION"  # BacktestEngine over synthetic bars, no real data needed
    PAPER = "PAPER"  # live bars, simulated fills at the live quote, no broker order
    LIVE = "LIVE"  # live bars, REAL orders placed via Dhan — requires explicit confirm


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
