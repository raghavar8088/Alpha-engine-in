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
    fixed_inr: float = 0.0      # a fixed rupee amount per buy (accumulation) instead of risk sizing


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
LABEL = {"NIFTY": "Nifty", "BANKNIFTY": "Bank Nifty", "XAUUSD": "Gold (Delta XAUTUSD)", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
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
# The Booming Bulls "Crypto Trading" playlist (PLHqOiFE9RQj8): rules written from the videos
# (backend/research/crypto_playlist_2026_11), not backtested; paper trading is their first test. The previous-day sweep
# of the same playlist already trades as BB-07, and the premium/discount filter is part of CP-17 and CP-18.
CP = "crypto_playlist"
MONEY["BTCUSD"] = Money("global", "USD", margin=0.10, step=0.001)        # Delta contracts of 0.001 BTC; 10x, the video's beginner leverage
MONEY["BTC_SPOT"] = Money("daily", "USD", margin=1.0, step=0.000001, fixed_inr=25_000.0, overnight=True)
LABEL["BTCUSD"] = "Bitcoin"
LABEL["BTC_SPOT"] = "Bitcoin spot"
_CPC = "Booming Bulls (Crypto Trading playlist)"
for _sid, _name, _mkts in (
    ("CP-01", "Trend pullback at the 5th point", ("BTCUSD", "XAUUSD")),
    ("CP-02", "Power-candle breakout of the last swing", ("BTCUSD", "XAUUSD")),
    ("CP-03", "Range ping-pong and range breakout", ("BTCUSD", "XAUUSD")),
    ("CP-04", "Trend-line rejection", ("BTCUSD",)),
    ("CP-05", "Turning-point zones (3 touches)", ("XAUUSD",)),
    ("CP-06", "Triple top / triple bottom", ("XAUUSD",)),
    ("CP-07", "Head and shoulders / inverted", ("XAUUSD",)),
    ("CP-08", "Flag and pole", ("XAUUSD",)),
    ("CP-09", "Trap of a swing level", ("XAUUSD",)),
    ("CP-10", "Retest of a broken level", ("XAUUSD",)),
    ("CP-12", "Current-day high/low sweep", ("XAUUSD",)),
    ("CP-13", "15m order block entered on a 5m FVG", ("XAUUSD",)),
    ("CP-14", "Order-flow absorption", ("BTCUSD",)),
    ("CP-15", "Delta-filtered morning / evening star", ("BTCUSD",)),
    ("CP-16", "ICT previous-day / week high-low sweep", ("XAUUSD",)),
    ("CP-17", "Fair value gap, third touch", ("XAUUSD",)),
    ("CP-18", "Order block at its 50%", ("XAUUSD",)),
    ("CP-20", "Inverse fair value gap", ("XAUUSD",)),
    ("CP-21", "Breaker block", ("XAUUSD",)),
    ("CP-22", "CISD after a liquidity sweep", ("XAUUSD",)),
    ("CP-23", "Inducement", ("XAUUSD",)),
    ("CP-24", "SMT divergence", ("XAUUSD", "EURUSD")),
    ("CP-25", "Optimal trade entry (0.705-0.79)", ("XAUUSD",)),
    ("CP-26", "Turtle soup", ("XAUUSD",)),
    ("CP-27", "Unicorn model", ("XAUUSD",)),
    ("CP-28", "Silver bullet (19:30-20:30 IST)", ("XAUUSD",)),
):
    ACCOUNTS.append(_a(_sid, CP, _name, _CPC, *[(_m, "V0") for _m in _mkts]))
ACCOUNTS.append(_a("CP-29", CP, "Fear & Greed accumulation", _CPC, ("BTC_SPOT", "V0")))
# Booming Bulls' liquidity-sweep video (backend/research/liquidity_sweep_2026_11), written as the app's strategy
# bb_liquidity_sweep (D9), plus its 22 one-change versions and three of the study's research-only runs. All were
# pre-registered and backtested; none passed. The variant is the study's version id, and liquidity_sweep.py runs the
# app's own strategy classes.
LS = "liquidity_sweep"
_LSC = "Booming Bulls (Liquidity Sweep video)"
for _sid, _name, _mkt, _ver in (
    ("LS-00", "Original (D9): sweep a level, close back inside", "NIFTY", "v00"),
    ("LS-01", "Levels: previous-day high/low only", "NIFTY", "v01"),
    ("LS-02", "Levels: previous-day close only", "NIFTY", "v02"),
    ("LS-03", "Levels: equal highs/lows only", "NIFTY", "v03"),
    ("LS-04", "Levels: 1-hour swings only", "NIFTY", "v04"),
    ("LS-05", "Levels: plus round numbers", "NIFTY", "v05"),
    ("LS-06", "Wick sweeps only", "NIFTY", "v06"),
    ("LS-07", "Strong rejection candle", "NIFTY", "v07"),
    ("LS-08", "Next-candle confirmation", "NIFTY", "v08"),
    ("LS-09", "Retest-and-reject entry", "NIFTY", "v09"),
    ("LS-10", "Market-structure shift entry", "NIFTY", "v10"),
    ("LS-11", "Target 1:1", "NIFTY", "v11"),
    ("LS-12", "Target 1:3", "NIFTY", "v12"),
    ("LS-13", "Breakeven at +1R", "NIFTY", "v13"),
    ("LS-14", "Target: the opposite liquidity", "NIFTY", "v14"),
    ("LS-15", "No target: stop or 15:15", "NIFTY", "v15"),
    ("LS-16", "200-EMA side filter", "NIFTY", "v16"),
    ("LS-17", "Big sweeps only", "NIFTY", "v17"),
    ("LS-18", "Morning only", "NIFTY", "v18"),
    ("LS-19", "Afternoon only", "NIFTY", "v19"),
    ("LS-20", "One trade a day", "NIFTY", "v20"),
    ("LS-21", "Breakout and retest (the video's other entry)", "NIFTY", "v21"),
    ("LS-22", "Full video: sweeps and breakout-retests", "NIFTY", "v22"),
    ("LS-R1", "Original on 15-minute candles", "NIFTY", "r1"),
    ("LS-R2", "Original on 3-minute candles", "NIFTY", "r2"),
    ("LS-R3", "Original on Bank Nifty", "BANKNIFTY", "r3"),
):
    ACCOUNTS.append(_a(_sid, LS, _name, _LSC, (_mkt, _ver)))
# Booming Bulls' "Sniper Headshot Entry" video (jvzd7UPlb5Y) on bitcoin, written as exact rules (sniper.py;
# backend/research/sniper_headshot_2026_11/RULES.md) with four one-change upgrades. Not backtested: they trade bitcoin
# on Delta's live prices from settings.SH_START_T, and paper trading is their first test.
SH = "sniper_headshot"
_SHC = "Booming Bulls (Sniper Headshot Entry video)"
for _sid, _name in (
    ("SH-00", "Sniper headshot entry: the video's rules"),
    ("SH-01", "Upgrade: enter on the reclaim of the swept level"),
    ("SH-02", "Upgrade: Delta order-flow confirmation"),
    ("SH-03", "Upgrade: 1-hour 50-EMA trend filter"),
    ("SH-04", "Upgrade: built to pay Delta's costs (1-hour bars)"),
):
    ACCOUNTS.append(_a(_sid, SH, _name, _SHC, ("BTCUSD", "V0")))
# Eleven YouTube channels (backend/research/youtube_channels11_2026_11): 103 strategies written as exact rules from the
# videos (analyses/<channel>.md; specs/RULES.md), checked for look-ahead, not backtested. They trade from
# settings.YC_START_T, flat at the start; paper trading is their first test. Conor Kenny's videos gave no testable rule.
YC = "youtube_channels11"
YC_CHANNELS = {
    "neerajjoshi": "Neeraj Joshi", "thetradinggeek": "Brad Goh (The Trading Geek)", "tanishagarg101": "Tanisha Garg",
    "thetagainers": "Theta Gainers", "stockburnerofficial": "Stock Burner", "pushkarrajthakurofficial": "Pushkar Raj Thakur",
    "iitiantrader": "IITian Trader", "thetraderoomsss": "The Trade Room (Mayank Raj)", "coachsagarsinha": "Sagar Sinha",
    "sayacrypto": "saya crypto",
}
# PR-12's ladder holds legs of 10% of the account: on gold that is a fraction of an ounce, so its book trades Delta's
# XAUTUSD at the exchange's own contract size (0.001 XAUT) instead of the gold books' whole ounces. Same gold data.
MONEY["XAUTUSD"] = Money("global", "USD", step=0.001)
LABEL["XAUTUSD"] = "Gold (Delta XAUTUSD, 0.001 contracts)"
YC_BOOK_MARKET = {"XAUTUSD": "XAUUSD"}         # a book market -> the market its strategy's rules were written for
YC_STRATEGIES = (
    ('NJ-01', '9:20 VWAP + EMA 7 first-candle breakout', 'neerajjoshi', ('NSE5',)),
    ('NJ-02', "Pivot points with a narrow CPR, trade the open's side", 'neerajjoshi', ('NSE5', 'NIFTY',)),
    ('NJ-03', 'EMA 9 + ADX above 25 and rising', 'neerajjoshi', ('NIFTY',)),
    ('NJ-04', 'EMA 10 failed-pullback breakout (Anant Ladha)', 'neerajjoshi', ('NIFTY',)),
    ('NJ-05', 'EMA 50/100 + Stochastic scalp, 1 minute', 'neerajjoshi', ('BANKNIFTY',)),
    ('NJ-06', 'Bollinger squeeze breakout', 'neerajjoshi', ('NSE15',)),
    ('NJ-07', 'Bollinger band turn + MACD cross + volume', 'neerajjoshi', ('NSE5',)),
    ('NJ-08', 'RSI 50 + EMA 14 cross', 'neerajjoshi', ('NIFTY',)),
    ('NJ-09', 'MACD signal-line cross', 'neerajjoshi', ('NIFTY',)),
    ('NJ-10', 'Heikin Ashi doji turn', 'neerajjoshi', ('NIFTY',)),
    ('NJ-11', 'Renko 1-back / 2-back continuation', 'neerajjoshi', ('NIFTY',)),
    ('NJ-12', 'PVT cross of its EMA 20', 'neerajjoshi', ('NSE5',)),
    ('NJ-13', 'Hammer after a fall, with volume', 'neerajjoshi', ('NSE15',)),
    ('NJ-14', 'Supertrend 21/1 flip with RSI and its average', 'neerajjoshi', ('NSE5',)),
    ('NJ-15', 'Three-touch level breakout with volume', 'neerajjoshi', ('NSE5',)),
    ('NJ-16', 'Double bottom / double top neckline break', 'neerajjoshi', ('BANKNIFTY',)),
    ('NJ-17', 'Day Sniper: gap, limit at the first 15-minute close', 'neerajjoshi', ('NSE15',)),
    ('NJ-18', 'Gap of 0.3% + first 15-minute range breakout', 'neerajjoshi', ('NSE15',)),
    ('NJ-19', 'EMA 50/200 golden cross with volume, daily', 'neerajjoshi', ('NSED',)),
    ('NJ-20', '200-DMA cross candidates from the top 100 by turnover', 'neerajjoshi', ('NSE5',)),
    ('NJ-21', 'EMA 5/20 cross scalp, 10-minute time stop', 'neerajjoshi', ('NIFTY',)),
    ('NJ-22', 'MACD + Stochastic 50 + Parabolic SAR', 'neerajjoshi', ('BANKNIFTY',)),
    ('NJ-23', 'Harami with a confirmation candle', 'neerajjoshi', ('NIFTY',)),
    ('NJ-24', 'Ascending triangle breakout, daily', 'neerajjoshi', ('NSED',)),
    ('NJ-25', 'BTST momentum basket', 'neerajjoshi', ('NSED',)),
    ('NJ-26', 'EMA 50 cross on Heikin Ashi with volume and RSI', 'neerajjoshi', ('NSED',)),
    ('NJ-46', 'EMA 10/20 cross with a Marubozu candle (Anant Ladha)', 'neerajjoshi', ('NSED',)),
    ('NJ-27', '20-candle channel breakout with EMA 200 and ATR stops, 4 hours', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-28', 'Fibonacci OTE: a 0.618 tap with an FVG', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-29', 'Order block retest with a 5-minute CISD', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-30', 'Fair value gap 50% limit entry', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-31', '4-hour swing sweep + 5-minute engulfing', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-32', 'Candle range theory 2.0', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-33', 'BTC/ETH SMT divergence', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-34', 'Hidden breakeven liquidity re-entry', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-35', 'Manipulation model at the New York open', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-36', 'The two-hour New York range sweep', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-37', 'The New York open fair value gap', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-38', 'Golden-hour 15-minute range breakout', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-39', 'Long-wick rejection at a 1-hour support or resistance', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-40', 'Ichimoku triple confirmation, 1 hour', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-41', 'Richard Dennis zone breakout, 4 hours', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-42', 'EMA 200 + double-tested level + MACD cross', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-43', 'Williams Alligator pullback to the teeth', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-44', '4-hour fractal sweep, entered on the close back inside', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-45', 'Two-candle turn level breakout', 'neerajjoshi', ('BTCUSD',)),
    ('NJ-47', 'Smoothed Heikin Ashi retest, 1:3', 'neerajjoshi', ('BTCUSD',)),
    ('TG-01', 'Failed breakout: trade the trap', 'tanishagarg101', ('NIFTY',)),
    ('TG-02', 'RSI 21 roof (60) and floor (40) break', 'tanishagarg101', ('NIFTY',)),
    ('TG-03', 'Candle outside the Bollinger Band, back inside', 'tanishagarg101', ('NIFTY',)),
    ('TG-04', 'Engulfing of several candles, daily swing', 'tanishagarg101', ('NSED',)),
    ('TG-05', 'EMA 20 cross with a held pullback candle, 1:4', 'tanishagarg101', ('BTCUSD',)),
    ('TG-06', 'Gann special numbers: the nearer level pulls the next session', 'tanishagarg101', ('NIFTY',)),
    ('IT-01', 'BankNifty first 5-minute candle theory', 'iitiantrader', ('BANKNIFTY',)),
    ('IT-02', 'The room strategy: EMA 45 trend, EMA 9/11 entry, a second lot one room away', 'iitiantrader', ('BTCUSD',)),
    ('TR-01', 'EMA 9/15 scalp on three entry candles', 'thetraderoomsss', ('BANKNIFTY',)),
    ('SS-01', 'Bollinger Band + Heikin Ashi alert candle, daily (Kushal Varshney)', 'coachsagarsinha', ('NIFTY_D',)),
    ('SS-02', "EMA 5/13 cross at the previous day's high or low", 'coachsagarsinha', ('BTCUSD',)),
    ('SS-03', 'Lowest-volume opposite candle (Kushal Varshney)', 'coachsagarsinha', ('NSE5',)),
    ('SS-04', 'The same 5-minute candle every day (Power of Stocks)', 'coachsagarsinha', ('BANKNIFTY',)),
    ('SS-05', 'BTST: Heikin Ashi close vs the real close at 15:15 (Kushal Varshney)', 'coachsagarsinha', ('NIFTY',)),
    ('SS-06', 'EMA 30/50/100 stacked, enter at EMA 30 (Priyank)', 'coachsagarsinha', ('BTCUSD',)),
    ('SY-01', 'Higher-timeframe structure, 1-hour trend break entered on 15 minutes', 'sayacrypto', ('BTCUSD',)),
    ('BG-01', 'Gold: 1-hour structure, 15-minute sweep at the point of interest', 'thetradinggeek', ('XAUUSD',)),
    ('BG-02', 'The liquidation candle scalp, 2R', 'thetradinggeek', ('XAUUSD',)),
    ('BG-03', '1-minute scalp: 15-minute point of interest, 1-minute sweep zone retest', 'thetradinggeek', ('XAUUSD',)),
    ('BG-04', 'Asia range sweep at the London open', 'thetradinggeek', ('GBPUSD',)),
    ('BG-05', 'Gold supply/demand zone with an EMA 8 cross and an engulfing', 'thetradinggeek', ('XAUUSD',)),
    ('BG-06', 'EMA 8/14 cross with an engulfing candle', 'thetradinggeek', ('NAS100',)),
    ('BG-07', 'Silver bullet, his golden-bullet version', 'thetradinggeek', ('NAS100',)),
    ('BG-08', 'Candle range theory on 15 minutes', 'thetradinggeek', ('XAUUSD',)),
    ('BG-09', 'Break and retest with a confirmation candle, 1:3', 'thetradinggeek', ('EURUSD',)),
    ('BG-10', 'Consolidation breakout on a momentum candle', 'thetradinggeek', ('EURUSD',)),
    ('PR-01', 'Brahmastra: Supertrend (20, 2) + MACD + VWAP', 'pushkarrajthakurofficial', ('NSE5',)),
    ('PR-02', '9:20 opening range: wait for the retest, 1:3', 'pushkarrajthakurofficial', ('BANKNIFTY',)),
    ('PR-03', '9:20 gap against the trend, opposite first candle', 'pushkarrajthakurofficial', ('BANKNIFTY',)),
    ('PR-04', 'The third 5-minute candle, exit at 15:00', 'pushkarrajthakurofficial', ('NIFTY',)),
    ('PR-05', "Ghanshyam Tech's window strategy", 'pushkarrajthakurofficial', ('BANKNIFTY',)),
    ('PR-06', "Ghanshyam Yadav's 2:20 candle", 'pushkarrajthakurofficial', ('BANKNIFTY',)),
    ('PR-07', "Ghanshyam Yadav's Fibonacci 0.71 buy", 'pushkarrajthakurofficial', ('BANKNIFTY',)),
    ('PR-08', 'Pivot points: sell the rally to the pivot', 'pushkarrajthakurofficial', ('NSE5',)),
    ('PR-09', 'Golden crossover: EMA 10 / 30 on 3 minutes', 'pushkarrajthakurofficial', ('NIFTY',)),
    ('PR-10', 'RSI divergence with a close-line trigger', 'pushkarrajthakurofficial', ('NIFTY',)),
    ('PR-11', "52-week-high stocks bought on a pullback to the Alligator's teeth", 'pushkarrajthakurofficial', ('NSED',)),
    ('PR-12', 'Gold: 4-hour Supertrend ladder with counter-scalps', 'pushkarrajthakurofficial', ('XAUTUSD',)),
    ('PR-13', 'Bitcoin: the same ladder with a 10% take-profit', 'pushkarrajthakurofficial', ('BTCUSD',)),
    ('SB-01', '9/20 EMA: ride the trend from the first pullback', 'stockburnerofficial', ('NSE5',)),
    ('SB-02', '9/20 EMA rejected pullback, 15 minutes', 'stockburnerofficial', ('BTCUSD',)),
    ('SB-03', '9 EMA rejection scalp', 'stockburnerofficial', ('NIFTY',)),
    ('SB-04', '200 EMA retest with a confirmation candle', 'stockburnerofficial', ('BTCUSD',)),
    ('SB-05', 'The first 5-minute candle breakout, one trade a day', 'stockburnerofficial', ('NIFTY',)),
    ('SB-06', 'Gold liquidity sweep at a tested level, pause-candle or rejection trigger', 'stockburnerofficial', ('XAUUSD',)),
    ('SB-07', 'Pre-breakout: buy under a tested resistance while the lows rise', 'stockburnerofficial', ('BTCUSD',)),
    ('SB-08', 'Bollinger Band breakout on 1-hour bitcoin, 2% stop, 5% target', 'stockburnerofficial', ('BTCUSD',)),
    ('TH-01', 'Bitcoin 6 PM session: anchored VWAP + EMA 25, the N pattern', 'thetagainers', ('BTCUSD',)),
    ('TH-02', 'Standard pivots R1 / S1 with a fast Supertrend (7, 3)', 'thetagainers', ('NIFTY',)),
    ('TH-03', 'Renko + Ichimoku dual system, gold', 'thetagainers', ('XAUUSD',)),
    ('TH-04', 'Renko + Ichimoku dual system, bitcoin', 'thetagainers', ('BTCUSD',)),
    ('TH-05', 'EMA 50/200 trend, pullback to EMA 50 with RSI 40-55', 'thetagainers', ('BTCUSD',)),
    ('TH-06', 'Bitcoin 07:15-07:30 IST range breakout, stop at mid-range', 'thetagainers', ('BTCUSD',)),
    ('TH-07', 'Three-way confirmation on 30 minutes', 'thetagainers', ('BTCUSD',)),
    ('TH-08', 'EMA 288 trend, Supertrend signal, base break, swing trail', 'thetagainers', ('BTCUSD',)),
    ('TH-09', 'Darvas box at 52-week highs', 'thetagainers', ('NSED',)),
)
for _sid, _name, _ch, _mkts in YC_STRATEGIES:
    ACCOUNTS.append(_a(_sid, YC, _name, YC_CHANNELS[_ch], *[(_m, "V0") for _m in _mkts]))
# Twenty more YouTube channels (backend/research/youtube_channels20_2026_11): 90 strategies written as exact rules from
# the videos (analyses/<channel>.md; specs/RULES.md), checked for look-ahead and backtested with costs
# (results/backtest.json); each is version v1. They trade from settings.YC2_START_T, flat at the start, on real market
# data with simulated orders only. Gold trades Delta's XAUTUSD at its 0.001 contract size, bitcoin Delta's BTCUSD, ether
# Delta's ETHUSD (0.01 contracts). Indian option strategies trade the index (or the stock) as a proxy: the desk has no
# intraday option premiums. Blocked strategies (incomplete rules, or data the desk lacks) have no account.
YC2 = "youtube_channels20"
YC_SOURCES = (YC, YC2)
MONEY["ETHUSD"] = Money("global", "USD", margin=0.10, step=0.01)       # Delta ETHUSD contracts of 0.01 ETH
LABEL["ETHUSD"] = "Ether (Delta ETHUSD)"
YC2_BOOK_MARKET = {"XAUUSD": "XAUTUSD"}       # the market the rules were written for -> the desk's book market
YC2_CHANNELS = {
    'dhanhq': 'Dhan',
    'abhishekxtrades': 'AbhishekXTrades',
    'upsurgeclub': 'Upsurge Club',
    'deltaexchange': 'Delta Exchange',
    'tradewithpat': 'Trade with Pat',
    'datatraders': 'Data Trader',
    'tradinglabofficial': 'TradingLab',
    'officialjesserogers': 'Jesse Rogers (Casper Trading)',
    'devanshrai': 'Devansh Rai',
    'stockinvestmentacademy': 'Stock Investment Academy (Amar Bhatia)',
    'thetradingschooltrafi': 'The Trading School',
    'holdwithpriyank': 'HOLD with Priyank',
    'tradingrush': 'TRADING RUSH',
    'tradbuilder': 'TradBuilder',
    'protradingschool6692': 'Pro Trading School',
    'transparentfxacademy': 'Transparent Fx Academy',
    'tradingdata1': 'Trading Data',
    'vijaythakkar': 'Vijay Thakkar (MastersInOne)',
    'faizsmcfx': 'Faiz SMC',
    'mulhamtrading': 'Mulham Trading',
}
YC2_STRATEGIES = (
    ('DH-01', 'VWAP pullback with an engulfing turn after a sweep', 'dhanhq', ('NIFTY',)),
    ('DH-02', '9:20 top movers: VWAP pullback, inside bar, engulfing break', 'dhanhq', ('NSE5',)),
    ('DH-03', '3-minute Heikin Ashi pullback scalp with EMA 100', 'dhanhq', ('NIFTY',)),
    ('DH-04', 'First 30 minutes range: break, pullback, confirmation', 'dhanhq', ('NIFTY',)),
    ('DH-05', '9:15-9:20 opening range breakout, RSI 55, rising ADX, Supertrend trail', 'dhanhq', ('NSE5',)),
    ('DH-06', '9:20 BYR: buy the 9:20 high of a 1-4% gainer, +0.65%', 'dhanhq', ('NSE5',)),
    ('DH-07', 'Supertrend + Fisher Transform near zero + rising ADX (option buying, index proxy)', 'dhanhq', ('NIFTY',)),
    ('DH-08', '1-minute box breakout with OCO stop orders', 'dhanhq', ('NIFTY',)),
    ('AX-01', 'EMA 5/20 cross, break of the counter candle within 3 bars', 'abhishekxtrades', ('NIFTY', 'BANKNIFTY')),
    ('AX-02', "Previous-day high/low bias, close through the counter candle's open (option buying, index proxy)", 'abhishekxtrades', ('NIFTY',)),
    ('AX-03', '9:30-10:00 range break, fixed 25-point scalp', 'abhishekxtrades', ('NIFTY',)),
    ('AX-04', 'All-touch candle (EMA 5/9/15 + SMA 20) before 10:00, 1:1, one reversal (options, index proxy)', 'abhishekxtrades', ('NIFTY',)),
    ('AX-05', 'CPR relationship bias, touch and close, 1:2, one reversal', 'abhishekxtrades', ('NIFTY',)),
    ('AX-06', 'Bitcoin 20-20 EMA (15-minute and 1-hour EMA 20)', 'abhishekxtrades', ('BTCUSD',)),
    ('AB-01', "Gap day: next day's 5-minute close through the gap day's far side", 'stockinvestmentacademy', ('NSE5',)),
    ('AB-02', 'First two 15-minute candles one colour, the second beyond VWAP', 'stockinvestmentacademy', ('NSE15',)),
    ('AB-03', 'EMA 9/21 cross + healthy confirmation candle (15-minute)', 'stockinvestmentacademy', ('NSE15',)),
    ('AB-04', '1-hour close 0.5% above the EMA 50 (BTST / swing)', 'stockinvestmentacademy', ('NSE5',)),
    ('AB-06', 'EMA 9/15 cross + confirmation candle, Bank Nifty agreeing (options, index proxy)', 'stockinvestmentacademy', ('NIFTY',)),
    ('TS-01', 'First 1-hour candle wick zones: break or reject, 5-minute confirmation', 'thetradingschooltrafi', ('NIFTY', 'BANKNIFTY')),
    ('TS-02', 'First 1-hour range sweep fade on 1-hour candles', 'thetradingschooltrafi', ('NIFTY', 'BANKNIFTY')),
    ('TS-03', 'Two-day squeeze breakout on volume (stocks)', 'thetradingschooltrafi', ('NSE15',)),
    ('TS-04', 'Gold: previous-day wick zones, 15-minute sweep and close-through', 'thetradingschooltrafi', ('XAUUSD',)),
    ('TS-05', 'Bitcoin 1-minute Fibonacci 0.5-0.786 pullback, 1:1', 'thetradingschooltrafi', ('BTCUSD',)),
    ('PV-02', "EMA 21 continuation: buy the down-close candle's high", 'holdwithpriyank', ('NIFTY', 'NSE5')),
    ('PV-03', 'RSI divergence, enter on the close through the middle swing', 'holdwithpriyank', ('NIFTY',)),
    ('PV-04', 'No-bias SMC scalp: daily levels, two 1-hour candles, 15-minute sweep and break', 'holdwithpriyank', ('BTCUSD',)),
    ('UP-01', 'The 9:15 open-price cross, out by 9:30 (options, index proxy)', 'upsurgeclub', ('NIFTY', 'BANKNIFTY')),
    ('UP-02', 'Gap trap: first hour back across VWAP, fade the VWAP retest (stock options, stock proxy)', 'upsurgeclub', ('NSE5',)),
    ('UP-03', '15-minute ADX curve: ADX rising through the DI lines', 'upsurgeclub', ('NSE15',)),
    ('UP-04', 'Daily Heikin Ashi side, EMA 200 band, Squeeze turning light, Supertrend (5, 1) (options, index proxy)', 'upsurgeclub', ('NIFTY',)),
    ('UP-05', '0.9% stretch from the 20 average, then EMA 20/50 cross back', 'upsurgeclub', ('NIFTY',)),
    ('UP-06', 'Band-and-oscillator reversal scalp (stated approximation of a private indicator)', 'upsurgeclub', ('NIFTY',)),
    ('VT-01', '33 EMA band on 9 minutes + RSI 55/45 + VWAP (option buying, index proxy)', 'vijaythakkar', ('NIFTY', 'BANKNIFTY')),
    ('VT-02', 'Weekly Supertrend (10, 3) king-candle breakout (stocks)', 'vijaythakkar', ('NSED',)),
    ('VT-03', 'Rule-based swing: above EMA 20/50/200, 50-day breakout, 9 EMA exit', 'vijaythakkar', ('NSED',)),
    ('TB-01', '15-minute two-colour pair breakdown, short only, 1:3', 'tradbuilder', ('NIFTY',)),
    ('TB-02', 'Range of the 2nd and 3rd 5-minute candles, reverse once, hold to the close (index proxy)', 'tradbuilder', ('NIFTY',)),
    ('TB-04', 'Nifty daily EMA 9/20 cross, long only', 'tradbuilder', ('NIFTY_D',)),
    ('DE-01', 'EMA 9/30 cross with a strong candle, 3-minute', 'deltaexchange', ('BTCUSD',)),
    ('DE-02', 'EMA 20/50/100 stack + Williams fractal, 1-minute, 4-hour side', 'deltaexchange', ('BTCUSD',)),
    ('DE-03', 'Neela Peela: EMA 57/111 first retest, 1/3/5-minute agreement', 'deltaexchange', ('BTCUSD',)),
    ('DE-04', 'Gold 4-hour Supertrend (10, 4), long only, 30% add on a 40-bar breakout', 'deltaexchange', ('XAUUSD',)),
    ('DE-07', 'The 7:30 PM IST bitcoin candle in the 4-hour trend, 1:1', 'deltaexchange', ('BTCUSD',)),
    ('TP-01', 'Gold range + impulsive FVG + discount + EMA 200 (5-minute)', 'tradewithpat', ('XAUUSD',)),
    ('TP-01H', 'Gold range + impulsive FVG + discount + EMA 200 (1-hour)', 'tradewithpat', ('XAUUSD',)),
    ('TP-02', 'Gold sweep of a tested level + minor trend-line break, EMA 200 side', 'tradewithpat', ('XAUUSD',)),
    ('TP-03', 'Asian range, London push, New York reversal on the 9:30 displacement ORB', 'tradewithpat', ('XAUUSD', 'BTCUSD')),
    ('TP-04', 'New York 15-minute ORB, limit at edge / midline / far side by impulse', 'tradewithpat', ('XAUUSD', 'BTCUSD')),
    ('TP-05', '9:30 displacement ORB without the session filter', 'tradewithpat', ('XAUUSD', 'BTCUSD')),
    ('DT-01', 'MACD cross in the EMA 100 trend, swing stop, 1.5R (1-hour)', 'datatraders', ('BTCUSD', 'XAUUSD')),
    ('DT-02', 'MACD + Parabolic SAR + EMA 200, stop at the dot, 1:1 (30-minute)', 'datatraders', ('BTCUSD', 'XAUUSD')),
    ('DT-03', 'Stochastic oversold, RSI 50, MACD cross, 1.5R (30-minute)', 'datatraders', ('BTCUSD', 'XAUUSD')),
    ('DT-04', 'Bitcoin daily Ichimoku lead lines, long only', 'datatraders', ('BTCUSD',)),
    ('DT-05', '15-minute Chaikin Money Flow side + MACD cross, 1.5R', 'datatraders', ('BTCUSD',)),
    ('DT-06', 'First New York 4-hour range fakeout fade, 2R', 'datatraders', ('BTCUSD', 'XAUUSD')),
    ('DT-07', 'SLC: 4-hour structure, fresh 5-minute zone, stochastic hook, 2R', 'datatraders', ('BTCUSD', 'XAUUSD')),
    ('DT-08', 'Manipulation: swing sweep + inverse FVG, 2R', 'datatraders', ('BTCUSD', 'XAUUSD')),
    ('TL-01', 'MACD cross beyond zero in the EMA 200 trend, stop past the EMA 200, 1.5R', 'tradinglabofficial', ('BTCUSD', 'XAUUSD')),
    ('TL-02', 'Bollinger (30, 2) + RSI (13) mean reversion to the middle band', 'tradinglabofficial', ('BTCUSD', 'XAUUSD')),
    ('TL-03', 'DEMA 200 + Supertrend (12, 3), exit on the opposite signal', 'tradinglabofficial', ('BTCUSD',)),
    ('TL-04', 'EMA 200 + RSI 50 + engulfing, stop two candles, 2R', 'tradinglabofficial', ('BTCUSD', 'XAUUSD')),
    ('JR-01', 'First Candle Rule: 9:30-9:45 range, FVG limit, candle-1 stop, 2R', 'officialjesserogers', ('BTCUSD', 'XAUUSD')),
    ('JR-02', 'First Candle Value: value-area failure fade (bitcoin volume)', 'officialjesserogers', ('BTCUSD',)),
    ('JR-03', '9:30-9:35 range, 1-minute FVG break, market entry, 2R', 'officialjesserogers', ('BTCUSD', 'XAUUSD')),
    ('JR-04', '9:30-9:35 range, retest close outside, stop at the midpoint, 2R', 'officialjesserogers', ('BTCUSD', 'XAUUSD')),
    ('JR-05', '9:30-9:35 range, 1-minute FVG pullback + engulfing, 3R', 'officialjesserogers', ('BTCUSD', 'XAUUSD')),
    ('DR-01', 'EMA 200 side + counter-trend-line breakout, 1:2 (15-minute)', 'devanshrai', ('BTCUSD', 'XAUUSD')),
    ('DR-02', 'Gold 1-minute EMA 200 reclaim with the 15-minute side, 1:2', 'devanshrai', ('XAUUSD', 'BTCUSD')),
    ('DR-03', '5 EMA untouched candle, close beyond it, 1:2 (bitcoin 15-minute)', 'devanshrai', ('BTCUSD',)),
    ('DR-04', 'Ether: 2% 15-minute momentum candle, then 1-minute trend-line breaks', 'devanshrai', ('ETHUSD',)),
    ('RU-01', 'MACD crossover beyond zero in the EMA 200 trend, swing stop, 1.5R (1-hour)', 'tradingrush', ('BTCUSD', 'XAUUSD')),
    ('RU-02', 'Stochastic below 20, then a MACD cross, 1.5R (30-minute)', 'tradingrush', ('BTCUSD', 'XAUUSD')),
    ('RU-03', 'Opposite RSI: RSI through 70/30 with ADX 25 in the EMA 200 trend, 1.5R', 'tradingrush', ('BTCUSD', 'XAUUSD')),
    ('RU-04', 'Williams fractal breakout in the 200 MA trend, 1.5R', 'tradingrush', ('BTCUSD', 'XAUUSD')),
    ('PT-01', 'Gold stop hunt at a tested level with the 1-hour trend, 2R', 'protradingschool6692', ('XAUUSD',)),
    ('PT-02', 'Gold RSI divergence + engulfing with the 1-hour trend, 2R', 'protradingschool6692', ('XAUUSD',)),
    ('PT-03', 'Sweep and flip: Asian range swept at the London open (15-minute)', 'protradingschool6692', ('XAUUSD', 'BTCUSD')),
    ('PT-04', '4-hour inside-bar breakout in the trend, 2R', 'protradingschool6692', ('BTCUSD', 'XAUUSD')),
    ('TF-01', 'Fibonacci confluence continuation, -0.272 target (15-minute)', 'transparentfxacademy', ('XAUUSD', 'BTCUSD')),
    ('TD-01', '9/20 EMA cross at a tested level with trend and discount, 1.5R', 'tradingdata1', ('XAUUSD', 'BTCUSD')),
    ('TD-02', '9/15 EMA cross filtered by the SMI (7, 2, 2)', 'tradingdata1', ('XAUUSD', 'BTCUSD')),
    ('TD-03', 'UT Bot pair + Schaff Trend Cycle, 2R (15-minute)', 'tradingdata1', ('BTCUSD', 'XAUUSD')),
    ('TD-04', 'UT Bot + linear-regression candles trend ride (1-hour)', 'tradingdata1', ('BTCUSD', 'XAUUSD')),
    ('TD-05', 'ADX/DI with a 200 EMA retest, 2R (15-minute)', 'tradingdata1', ('XAUUSD', 'BTCUSD')),
    ('FZ-01', 'Gold 8 PM / 9 PM New York Midas model (15-minute sweep, 1-minute shift)', 'faizsmcfx', ('XAUUSD',)),
    ('FZ-02', 'Gold London first FVG inversion (15-minute)', 'faizsmcfx', ('XAUUSD',)),
    ('MH-01', 'Gold 8 PM New York hourly candle: reversal or continuation', 'mulhamtrading', ('XAUUSD',)),
    ('MH-02', '15-minute fake-out with a 1-minute flip entry', 'mulhamtrading', ('XAUUSD', 'BTCUSD')),
    ('MH-03', 'Asian liquidity sweep into a PD array, 1-minute FVG entry', 'mulhamtrading', ('XAUUSD', 'BTCUSD')),
)
for _sid, _name, _ch, _mkts in YC2_STRATEGIES:
    ACCOUNTS.append(_a(_sid, YC2, _name, YC2_CHANNELS[_ch], *[(YC2_BOOK_MARKET.get(_m, _m), "V0") for _m in _mkts]))
# The channel-shortlist study (backend/research/youtube_shortlist_2026_11): the owner's three pasted lists of YouTube
# channels, each distinct method written as exact rules from its video (cards/<video>.txt) and checked for look-ahead
# and fills; each is version v1. They trade from settings.YC3_START_T, flat at the start, on real market data with
# simulated orders only, Rs 10 lakh each. Gold trades Delta's XAUTUSD; option-buying videos trade the index as a proxy;
# FX, Nasdaq and index rows carry no real volume, so their VWAP is time-weighted.
YC3 = "youtube_shortlist"
YC_SOURCES = YC_SOURCES + (YC3,)
YC3_STRATEGIES = (
    ('DF-02', 'RSI(14) back through 30/70 on 5 minutes, swing stop with a points filter, VWAP then 200 EMA', 'Definedge', ('NIFTY', 'BANKNIFTY')),
    ('PW-01', 'Previous close\'s last swing (or last-three-candle range) break, no gap entries, 1:1 (index proxy)', 'POWER OF STOCKS', ('NIFTY', 'BANKNIFTY')),
    ('DH-09', 'BB Trend (100, 250) side + fresh MACD (48, 104, 36) cross, part at a fixed target, EMA 5/15 trail', 'Dhan', ('NIFTY', 'BANKNIFTY')),
    ('DH-10', '9:15-9:30 opening range edges + Hull MA colour flips, one minute', 'Dhan', ('NIFTY', 'BANKNIFTY')),
    ('CK-01', 'Connors RSI (3, 2, 100) 80/20 signals in the direction of RSI(14) above 60 / below 40, 5 minutes', 'Trading Chanakya', ('NIFTY', 'BANKNIFTY')),
    ('EC-01', 'Supertrend signals only at pivot support or on a resistance break, Heikin Ashi candles', 'Equity2Commodity', ('NIFTY', 'BANKNIFTY')),
    ('PC-01', 'Trending day, pin bar at a sloping 20 MA, candle stop, quick exit', 'Pivot Call (Vikram Prabhu)', ('NIFTY', 'BANKNIFTY')),
    ('PC-02', 'Rejection candle at the previous day\'s high or low, next-candle exit', 'Pivot Call (Vikram Prabhu)', ('NIFTY', 'BANKNIFTY')),
    ('PC-03', 'Wide CPR: reversal candle at the central pivot after a fall into it, next-candle exit', 'Pivot Call (Vikram Prabhu)', ('NIFTY', 'BANKNIFTY')),
    ('TW-01', '15-minute opening range breakout on a volume expansion, VWAP side, session-low stop', 'Trade With Trend (Raunak A)', ('NSE15',)),
    ('DF-01', 'Ten strongest movers on Nifty\'s side, Point & Figure double-top buy / double-bottom sell', 'Definedge', ('NSE5',)),
    ('VB-01', 'High-activity stock, first 15-minute high/low break on 5 minutes before 2 PM, entry-candle stop', 'Vivek Bajaj', ('NSE5',)),
    ('VB-02', 'Session VWAP and 15-minute Supertrend agreeing', 'Vivek Bajaj', ('NSE15',)),
    ('DH-11', '15-minute Bollinger Band exhaustion + RSI 70/30, first opposite candle, 1% target', 'Dhan', ('NSE15',)),
    ('CK-02', 'Previous-day high/low break with a 0.5% buffer, day-extreme stop, 2R target, out at 3 PM (high-beta)', 'Trading Chanakya', ('NSE5',)),
    ('EC-02', '9:15 candle on 2x closing volume: big candle side, second candle closes beyond it, 2R', 'Equity2Commodity', ('NSE15',)),
    ('TW-02', 'Strong gap out of a range with RSI holding 40 (bullish range), range-low stop, long only on daily bars', 'Trade With Trend (Raunak A)', ('NSED',)),
    ('MV-02', 'Regular RSI divergence 3-10 bars apart, confirmation candle, target the middle swing, RR at least 1:3', 'Malkansview', ('NSED',)),
    ('OF-01', 'Williams %R (10) bullish divergence with RSI below 30 on daily candles', 'Optimus Futures', ('NSED',)),
    ('CC-01', 'Clean double close through a level (failed flip), limit at the level, thrust-candle stop', 'CryptoCred', ('BTCUSD', 'EURUSD', 'GBPUSD')),
    ('BN-01', 'EMA 20/50/100 fanned trend, retest of EMA 20/50 with engulfing or pin bar + Stoch RSI cross, 2-3R', 'The Birb Nest', ('BTCUSD',)),
    ('TC-01', '4-hour breakout, dirty retest back into the pattern, 15-minute break of the retest', 'Tradeciety', ('EURUSD', 'GBPUSD', 'BTCUSD')),
    ('TC-02', 'Trend day, Asian grind back into the daily pivot, London-open 5-minute breakout to S1/R1', 'Tradeciety', ('EURUSD', 'GBPUSD')),
    ('UK-01', 'First one-minute candle bracket at the cash open, out at the close of minute five', 'UKspreadbetting', ('NAS100',)),
    ('UK-02', 'Biggest VWAP excursion in 3 days, first VWAP test outside the first/last hour, 1/3 stop, 3:1', 'UKspreadbetting', ('NAS100', 'BTCUSD')),
    ('AF-01', 'Early drive away from VWAP (gap day), buy the first VWAP test that holds, exit at a new high', 'Axia Futures', ('NAS100',)),
    ('MA-01', 'One-minute impulse that breaks structure, limit at the 0.618, stop past the origin, target the impulse end', 'The Moving Average', ('EURUSD', 'GBPUSD')),
    ('RU-05', 'RSI through 70 (30) with Supertrend agreeing, Supertrend stop, 1.5R', 'TRADING RUSH', ('BTCUSD', 'XAUUSD')),
    ('RU-06', 'Zero-lag MACD cross below/above zero in the 200 EMA trend, pullback stop, 1.5R', 'TRADING RUSH', ('BTCUSD', 'XAUUSD')),
    ('NK-01', 'Close outside the Bollinger Band (20, 2), stop at the middle line, 2R (1-hour)', 'TraderNick', ('EURUSD', 'GBPUSD')),
    ('KA-01', 'Break of the previous hour/day high or low after a staircase approach, two closes, swing stop, 1R', 'Koroush AK', ('BTCUSD',)),
)
for _sid, _name, _ch, _mkts in YC3_STRATEGIES:
    ACCOUNTS.append(_a(_sid, YC3, _name, _ch, *[(YC2_BOOK_MARKET.get(_m, _m), "V0") for _m in _mkts]))
BY_ID = {a.id: a for a in ACCOUNTS}


def books_in(group: str) -> list[tuple[Account, str, str]]:
    """(account, market, variant) of every book a cycle group runs."""
    return [(a, mk, v) for a in ACCOUNTS for mk, v in a.books if MONEY[mk].group == group]
