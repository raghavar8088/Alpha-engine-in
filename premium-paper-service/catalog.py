"""Every paper account: one per strategy, Rs 10 lakh each, trading the variant and markets the research chose.

The chosen variants are copied from the studies' results (backend/research/*/results/summary.json): each was picked
on development + validation data before the hold-out was opened. They are frozen here and must never be re-tuned on
paper results. A strategy on several markets trades them all from its one account.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BB, YT, VW = "booming_bulls", "youtube_top20", "vwap"


@dataclass(frozen=True)
class Money:
    """How a position is sized in this market."""
    group: str                  # the cycle that runs it: index, stocks, global, daily
    ccy: str = "INR"
    risk_pct: float = 0.01      # of current equity
    margin: float = 0.05        # fraction of notional held as margin
    lot: int = 0                # whole lots (0 = use step)
    step: float = 1.0           # smallest size
    notional_cap: float = 0.0   # fraction of equity one position may reach (0 = no cap beyond margin)
    max_open: int = 0           # pools of many stocks: positions open at once (first come, ties to the more liquid)
    overnight: bool = False


NSE_POOL = dict(group="stocks", risk_pct=0.0025, margin=0.20, step=1, notional_cap=0.25, max_open=4)
MONEY = {
    "NIFTY": Money("index", margin=0.12, lot=65),
    "BANKNIFTY": Money("index", margin=0.12, lot=30),
    "XAUUSD": Money("global", "USD", step=1.0),
    "EURUSD": Money("global", "USD", step=1000.0),
    "GBPUSD": Money("global", "USD", step=1000.0),
    "NAS100": Money("global", "USD", step=0.1),
    "AAPL": Money("global", "USD", margin=0.20, step=1.0),
    "SPX500_D": Money("daily", "USD", step=0.1, overnight=True),
    "NAS100_D": Money("daily", "USD", step=0.1, overnight=True),
    "NIFTY_D": Money("daily", margin=0.12, lot=65, overnight=True),
    "NSE15": Money(**NSE_POOL),
    "NSE5": Money(**NSE_POOL),
    "NSED": Money("daily", risk_pct=0.01, margin=1.0, step=1, notional_cap=0.10, max_open=10, overnight=True),
    "VWAP": Money(**NSE_POOL),
}
ONE_LOT_MAX_RISK = 0.05         # a lot-sized market still takes 1 lot when that risks at most 5% of equity
LABEL = {"NIFTY": "Nifty", "BANKNIFTY": "Bank Nifty", "XAUUSD": "Gold", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
         "NAS100": "Nasdaq 100", "AAPL": "Apple", "SPX500_D": "S&P 500 daily", "NAS100_D": "Nasdaq 100 daily",
         "NIFTY_D": "Nifty daily", "NSE15": "NSE stocks 15m", "NSE5": "NSE stocks 5m", "NSED": "NSE stocks daily",
         "VWAP": "NSE stocks 5m"}


@dataclass(frozen=True)
class Account:
    id: str
    source: str
    name: str
    channel: str
    books: tuple = field(default_factory=tuple)      # (market, variant)


def _a(id_, source, name, channel, *books):
    return Account(id_, source, name, channel, tuple(books))


_BBC = "Booming Bulls"
ACCOUNTS: list[Account] = [
    _a("VWAP-A", VW, "Original A: VWAP retest", _BBC, ("VWAP", "A")),
    _a("VWAP-B", VW, "Original B: sweep to VWAP", _BBC, ("VWAP", "B")),
    _a("VWAP-U1", VW, "U1: in-play retest", "Upgrade of the VWAP video", ("VWAP", "U1")),
    _a("VWAP-U2", VW, "U2: trend ride", "Upgrade of the VWAP video", ("VWAP", "U2")),
    _a("VWAP-U3", VW, "U3: capitulation reversal", "Upgrade of the VWAP video", ("VWAP", "U3")),
    _a("VWAP-U4", VW, "U4: first-hour trend", "Upgrade of the VWAP video", ("VWAP", "U4")),

    _a("BB-01", BB, "Previous-day high/low: breakout, trap, gap fill, retest", _BBC, ("NIFTY", "R1")),
    _a("BB-02", BB, "15-minute opening-range breakout, 5-minute close", _BBC, ("NIFTY", "S2")),
    _a("BB-03", BB, "Nifty + Bank Nifty synchronised level break", _BBC, ("NIFTY", "V0")),
    _a("BB-04", BB, "Zone trap with RSI divergence (15m)", _BBC, ("NIFTY", "R1")),
    _a("BB-05", BB, "SMC structure break into an order block", _BBC, ("BANKNIFTY", "S1")),
    _a("BB-06", BB, "Gap day + first candle through the 15m 200 MA", _BBC, ("NIFTY", "V0")),
    _a("BB-07", BB, "Liquidity sweep of previous-day high/low", _BBC, ("XAUUSD", "S1"), ("NAS100", "V0")),
    _a("BB-08", BB, "Previous-day high/low trap after 10:00 IST", _BBC, ("XAUUSD", "V0"), ("EURUSD", "S3"), ("GBPUSD", "S3")),
    _a("BB-09", BB, "Value-area (volume profile) trap", _BBC, ("XAUUSD", "R2")),
    _a("BB-10", BB, "Gold 11:30-12:30 IST range sweep", _BBC, ("XAUUSD", "V0")),
    _a("BB-11", BB, "Forex 10:00 IST range trap", _BBC, ("EURUSD", "S1"), ("GBPUSD", "R1"), ("XAUUSD", "R1")),
    _a("BB-12", BB, "400 EMA trap (15m)", _BBC, ("XAUUSD", "V0")),
    _a("BB-13", BB, "'Prop-firm' inside-body breakout", _BBC, ("NAS100", "R1"), ("XAUUSD", "R1")),
    _a("BB-14", BB, "Inside candle with the poke filter", _BBC, ("NAS100", "R1")),
    _a("BB-15", BB, "Apple opening-range trap", _BBC, ("AAPL", "V0")),
    _a("BB-16", BB, "Retracement-zone (Fibonacci 50-61.8%) sweep", _BBC, ("XAUUSD", "S2")),
    _a("BB-17", BB, "Order-block 50% trap", _BBC, ("XAUUSD", "S1"), ("EURUSD", "S1")),
    _a("BB-18", BB, "15m 200 EMA breakout-retest", _BBC, ("EURUSD", "S1"), ("GBPUSD", "S1")),

    _a("YT-01", YT, "5 EMA alert candle", "Power of Stocks; Pushkar Raj Thakur", ("NIFTY", "S1"), ("BANKNIFTY", "S1")),
    _a("YT-02", YT, "Market-structure pullback, ATR stop", "The Trading Channel", ("EURUSD", "R1"), ("GBPUSD", "V0")),
    _a("YT-03", YT, "50 MA double bottom / top", "The Trading Channel", ("EURUSD", "R1"), ("GBPUSD", "V0")),
    _a("YT-04", YT, "ICT Silver Bullet", "The Inner Circle Trader", ("EURUSD", "V0"), ("NAS100", "V0")),
    _a("YT-05", YT, "ICT Judas Swing", "The Inner Circle Trader", ("EURUSD", "R1"), ("GBPUSD", "V0")),
    _a("YT-06", YT, "ICT OTE 62% retracement", "The Inner Circle Trader", ("EURUSD", "V0")),
    _a("YT-07", YT, "Connors RSI(10) pullback", "Rayner Teo", ("SPX500_D", "V0"), ("NAS100_D", "V0"), ("NIFTY_D", "V0")),
    _a("YT-08", YT, "Inside candle (15m)", "Power of Stocks", ("NIFTY", "R1"), ("BANKNIFTY", "R1"), ("NSE15", "V0")),
    _a("YT-09", YT, "Traffic light candle pair", "Power of Stocks", ("NIFTY", "S1"), ("BANKNIFTY", "V0")),
    _a("YT-10", YT, "Gap + shooting star / hammer first candle", "Ghanshyam Tech", ("NIFTY", "S1"), ("BANKNIFTY", "V0")),
    _a("YT-11", YT, "Momentum loss into a swing level", "Wysetrade", ("EURUSD", "R1"), ("GBPUSD", "R1"), ("XAUUSD", "R1")),
    _a("YT-12a", YT, "44 SMA bullish candle (daily)", "Siddharth Bhanushali", ("NSED", "R1")),
    _a("YT-12b", YT, "44 SMA + big green opening candle (15m)", "Siddharth Bhanushali", ("NSE15", "V0")),
    _a("YT-13", YT, "Daily bear / bull trap", "Siddharth Bhanushali", ("NSED", "V0"), ("NIFTY_D", "V0")),
    _a("YT-14", YT, "MA fan + engulfing / three-line strike, RSI 50", "The Moving Average", ("EURUSD", "R1"), ("GBPUSD", "V0"), ("XAUUSD", "R1")),
    _a("YT-15", YT, "MA alignment + Williams fractal, 10 pips", "The Moving Average", ("EURUSD", "V0"), ("GBPUSD", "V0")),
    _a("YT-16", YT, "MA pullback + engulfing / pin bar, 1:2", "Adam Khoo", ("EURUSD", "V0"), ("GBPUSD", "V0"), ("SPX500_D", "V0"), ("NAS100_D", "V0")),
    _a("YT-17", YT, "Breakout, pullback, continuation", "Wealth Secret", ("NIFTY", "V0"), ("BANKNIFTY", "R1")),
    _a("YT-18", YT, "Heikin-Ashi colour change + RSI 50", "The Secret Mindset", ("EURUSD", "S1"), ("GBPUSD", "S1"), ("XAUUSD", "S1")),
    _a("YT-19", YT, "Supertrend(10,3) at 09:20 (futures proxy)", "Elearnmarkets / Vishal Mehta", ("NIFTY", "V0"), ("BANKNIFTY", "V0")),
    _a("YT-20", YT, "3-EMA 1-minute scalp", "The Secret Mindset", ("EURUSD", "V0"), ("GBPUSD", "V0")),
    _a("YT-21", YT, "Bollinger 2.5 SD range fade", "The Secret Mindset", ("EURUSD", "V0"), ("GBPUSD", "V0")),
    _a("YT-22", YT, "Heikin-Ashi pair + Stochastic RSI 20/80", "Nitin Bhatia", ("NIFTY", "V0"), ("BANKNIFTY", "V0"), ("NSE15", "V0")),
    _a("YT-23", YT, "Vortex crossover outside congestion", "Nitin Bhatia", ("NIFTY", "V0"), ("NSE15", "V0")),
    _a("YT-24", YT, "5-8-13 EMA ribbon", "Nitin Bhatia", ("NIFTY", "V0"), ("BANKNIFTY", "V0"), ("NSE15", "V0")),
    _a("YT-25", YT, "RSI 70/30 reversal", "Super Trader Lakshya", ("NSE15", "V0")),
    _a("YT-26", YT, "5-minute ORB on gappers with VWAP (proxy)", "Bear Bull Traders", ("NSE5", "V0")),
    _a("YT-27", YT, "Camarilla R3/S3 fade, R4/S4 breakout", "Bear Bull Traders", ("NIFTY", "V0"), ("BANKNIFTY", "V0"), ("NAS100", "V0")),
]
BY_ID = {a.id: a for a in ACCOUNTS}


def books_in(group: str) -> list[tuple[Account, str, str]]:
    """(account, market, variant) of every book a cycle group runs."""
    return [(a, mk, v) for a in ACCOUNTS for mk, v in a.books if MONEY[mk].group == group]
