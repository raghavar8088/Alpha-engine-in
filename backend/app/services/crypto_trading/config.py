"""Every crypto-specific choice of the Crypto Trading module, in one place.

The strategy DEFINITIONS are not here and are not copied: both libraries are imported from where
they live (app.services.strategy_factory and strategy_service). What a crypto market changes is
configuration - the venue, the unit traded, the costs, the session, the history windows, the risk
limits - and that is all this file holds.
"""

from __future__ import annotations

import os
from datetime import timedelta, timezone

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

# -- the venue ------------------------------------------------------------------------------------
# Delta Exchange India: the venue the owner's crypto app trades. It lists perpetual futures, not
# spot, so the instrument is the coin's USD-quoted perpetual - long and short both allowed.
VENUE = "Delta Exchange India"
DELTA_BASE_URL = os.getenv("CRYPTO_TRADING_DELTA_URL", "https://api.india.delta.exchange").rstrip("/")
DELTA_PACE_S = float(os.getenv("CRYPTO_TRADING_DELTA_PACE_S", "0.35"))   # between REST calls
DELTA_PAGE = 3990                     # Delta returns at most ~4,000 candles a request
DELTA_GST = 0.18                      # Delta India charges 18% GST on its trading fees
DEFAULT_TAKER_FEE = 0.0005            # only when the product spec has none (it always has, 2026-10-31)

# -- the universe ---------------------------------------------------------------------------------
RANKING_SOURCE = "CoinGecko /api/v3/coins/markets (vs_currency=usd, order=market_cap_desc)"
COINGECKO_URL = os.getenv("CRYPTO_TRADING_COINGECKO_URL", "https://api.coingecko.com/api/v3/coins/markets")
TOP_N = 10
CANDIDATES = 120                      # market-cap ranks read before the screens
MIN_TURNOVER_24H_USD = float(os.getenv("CRYPTO_TRADING_MIN_TURNOVER", "1000000"))
MIN_OPEN_INTEREST_USD = float(os.getenv("CRYPTO_TRADING_MIN_OI", "250000"))
MIN_HISTORY_DAYS = int(os.getenv("CRYPTO_TRADING_MIN_HISTORY_DAYS", "365"))

# Excluded before any market check. A stablecoin tracks a fiat currency, a wrapped or staked token
# is a second claim on an asset already in the list, and a tokenised asset (gold, a loan book) is
# not a cryptocurrency's own market. The lists are explicit; the name screen below catches the
# ones a list will always be behind on.
STABLECOIN_IDS = {
    "tether", "usd-coin", "usds", "dai", "ethena-usde", "usd1-wlfi", "first-digital-usd", "paypal-usd",
    "true-usd", "frax", "usdd", "global-dollar", "ripple-usd", "falcon-finance", "binance-usd", "gemini-dollar",
    "pax-dollar", "usual-usd", "agora-dollar", "eurc", "stasis-eurs", "susds", "sky-dollar", "resolv-usr",
    "ethena-staked-usde", "usdx-money-usdx", "lusd", "liquity-usd", "crvusd", "gho",
}
WRAPPED_OR_STAKED_IDS = {
    "wrapped-bitcoin", "staked-ether", "wrapped-steth", "wrapped-eeth", "coinbase-wrapped-btc", "weth",
    "wrapped-beacon-eth", "rocket-pool-eth", "jito-staked-sol", "binance-bitcoin", "lombard-staked-btc",
    "solv-btc", "mantle-staked-ether", "renzo-restaked-eth", "kelp-dao-restaked-eth", "marinade-staked-sol",
    "jupiter-staked-sol", "binance-staked-sol", "bitcoin-avalanche-bridged-btc-b", "wrapped-bnb",
    "wrapped-avax", "wrapped-tron", "coinbase-wrapped-staked-eth", "stakewise-v3-oseth", "liquid-staked-ethereum",
    "ether-fi-staked-eth", "wrapped-hype", "kinetic-staked-hype", "tbtc", "frax-ether", "staked-frax-ether",
}
TOKENISED_ASSET_IDS = {"tether-gold", "pax-gold", "figure-heloc", "blackrock-usd-institutional-digital-liquidity-fund"}
NAME_SCREENS = ("wrapped ", "staked ", "bridged ", "restaked ", "liquid staked", "tokenized ", " usd")

# -- accounts -------------------------------------------------------------------------------------
ACCOUNT_CAPITAL_USD = 10_000.0        # every strategy-cryptocurrency pair, independently

# -- timeframes and data --------------------------------------------------------------------------
TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"]
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "45m": 2700, "1h": 3600, "4h": 14400, "1d": 86400}
# Delta's own resolution per timeframe; 45m has none and is resampled from 15m on the UTC-midnight
# anchor (1440 / 45 = 32, so every UTC day holds whole 45m bars and no stub).
DELTA_RESOLUTION = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
DERIVED_FROM = {"45m": "15m"}

# History each backtest replays, per timeframe: long enough for a strategy of that speed to trade
# a few dozen times, short enough that the slowest pair finishes in seconds. None = everything the
# venue has (Delta India's listings date from 2023-12 for BTC, 2024-04 for most, later for some).
BACKTEST_DAYS = {"1m": 14, "5m": 60, "15m": 182, "30m": 365, "45m": 365, "1h": 365, "4h": None, "1d": None}

# Each decision sees the latest EVAL_WINDOW bars (HTF_WINDOW of the higher timeframe) - in the
# backtest AND live, exactly as the Factory's own paper desk evaluates - so the replay and the desk
# cannot disagree about what a strategy saw.
EVAL_WINDOW = 600
HTF_WINDOW = 400
SM_CONTEXT_BARS = 500                 # the Strategies module's own StrategyContext size

# -- the crypto session ---------------------------------------------------------------------------
# Crypto trades 24/7, so a "session" has to be defined. Here it is the UTC calendar day: it opens
# at 00:00 UTC (05:30 IST) and closes at 24:00 UTC. The Factory groups sessions by the bar's own
# date, so UTC bars give it exactly this. Strategies-module strategies written against the NSE
# clock read the same wall-clock times in UTC: their 09:15-09:30 opening range is 09:15-09:30 UTC,
# their 15:00 square-off is 15:00 UTC - the European session into the US open, crypto's busiest
# hours - and "today" is the UTC day.
SESSION_TZ = "UTC"
SESSION_NOTE = ("Crypto session = the UTC calendar day (00:00-24:00 UTC). NSE-clock strategies keep their "
                "times but read them in UTC: 09:15-15:30 becomes 09:15-15:30 UTC.")
NSE_CLOCK_STRATEGIES = {"gap_fade", "opening_range_breakout", "trend_pullback", "volume_spike",
                        "vwap_futures", "vwap_reversion", "vwap_scalping", "vwap_trend"}
BENCHMARK_STRATEGIES = {"relative_strength", "sector_rotation"}
BENCHMARK_SYMBOL = "BTCUSD"           # the crypto market's benchmark, as NIFTY is for NSE

# -- costs and fills ------------------------------------------------------------------------------
# Slippage is charged on every fill in basis points of price, per coin: half the quoted spread plus
# the price impact of a $10,000 market order on the venue's book, measured when the universe is
# selected and stored with it; never below MIN_SLIPPAGE_BPS, because a snapshot of a quiet book
# understates what a fill costs in the fast markets these strategies trade into.
MIN_SLIPPAGE_BPS = 3.0
FALLBACK_SLIPPAGE_BPS = 5.0
FUNDING_RES_S = 3600                  # Delta publishes FUNDING:<symbol> as hourly candles

# -- data quality ---------------------------------------------------------------------------------
# A bar with no trade in it is the last trade carried forward (O=H=L=C, volume 0), not a price
# anyone could have dealt at, and a stop that "held" through it may only have held because nothing
# printed. On Delta India 55-63% of the 1-minute bars of BNB, HYPE, LINK and BCH are such bars
# (measured 2026-11-01), against 0-3% for BTC, ETH, SOL and XRP. A series with more than this share
# of no-trade bars is not graded and not traded: "insufficient data", with the share as the reason.
MAX_NO_TRADE_BAR_PCT = float(os.getenv("CRYPTO_TRADING_MAX_NO_TRADE_PCT", "5"))

# -- grading and eligibility (the Factory's own rule, on crypto results) --------------------------
MIN_GRADE_TO_TRADE = int(os.getenv("CRYPTO_TRADING_MIN_GRADE", "3"))
MIN_TRADES_FOR_GRADE = 20
OOS_FRACTION = 0.3

# -- account risk limits --------------------------------------------------------------------------
RISK_PCT = 0.01                       # the Factory's: a stop-out costs 1% of the account
MAX_NOTIONAL_PCT = 1.0                # 1x: no leverage, the position is fully collateralised
DAILY_LOSS_PCT = 0.03                 # the Factory's breaker: -3% in a UTC day pauses the account to the next
MAX_DRAWDOWN_PCT = 0.50               # an account at half its capital stops trading until reset
