# FT-UniversalMACD — UniversalMACD

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/UniversalMACD.py#L21-L113
- Author: Masoud Azizi (@mablue) (code comment 'By:')
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 b3a62e0d8a26024e7ab5f3613d0964e3954373bc3735c1ffd0678d84ce1b1e32

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L30 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.213, "27": 0.099, "60": 0.03, "164": 0} | L60 | `minimal_roi = { "0": 0.213, "27": 0.099, "60": 0.03, "164": 0 }` |
| stop | E | Stop-loss -0.318 (price level from the entry) | L68 | `stoploss = -0.318` |
| management | E | Trailing: trailing_stop = False, trailing_stop_positive = None, trailing_stop_positive_offset = 0.0, trailing_only_offset_is_reached = False | L71,72,73,74 | `trailing_stop = False  # value loaded from strategy / trailing_stop_positive = None  # value loaded from strategy / trailing_stop_positive_offset = 0.0  # value loaded from strategy / trailing_only_offset_is_reached = False  # value loaded from strategy` |
| management | E | can_short = False | L33 | `can_short: bool = False` |
| data | E | startup_candle_count = 30 | L77 | `startup_candle_count: int = 30` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L80,81,82,83 | `buy_umacd_max = DecimalParameter(-0.05, 0.05, decimals=5, default=-0.01176, space='buy') \| buy_umacd_min = DecimalParameter(-0.05, 0.05, decimals=5, default=-0.01416, space='buy') \| sell_umacd_max = DecimalParameter(-0.05, 0.05, decimals=5, default=-0.02323, space='sell') \| sell_umacd_min = Decim` |
| indicator | E | Indicators as computed in populate_indicators | L85-94 | `dataframe['ma12'] = ta.EMA(dataframe, timeperiod=12) dataframe['ma26'] = ta.EMA(dataframe, timeperiod=26) dataframe['umacd'] = (dataframe['ma12'] / dataframe['ma26']) - 1` |
| entry | E | Entry signal conditions (populate_entry_trend) | L96-104 | `dataframe.loc[ ( (dataframe['umacd'].between(self.buy_umacd_min.value, self.buy_umacd_max.value)) ), 'enter_long'] = 1` |
| exit | E | Exit signal conditions (populate_exit_trend) | L106-113 | `dataframe.loc[ ( (dataframe['umacd'].between(self.sell_umacd_min.value, self.sell_umacd_max.value)) ), 'exit_long'] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
