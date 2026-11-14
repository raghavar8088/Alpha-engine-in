# FT-FReinforcedStrategy — FReinforcedStrategy

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/futures/FReinforcedStrategy.py#L27-L144
- Author: freqtrade-strategies futures folder (see file)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 4148d3d2d736a454a470649646a59b77a62f7d4ccb7f7bc6d2ecc5ad0ec01152

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L30 | `timeframe = "5m"` |
| target | E | ROI table (minutes since entry: net profit ratio) {"60": 0.075, "30": 0.1, "0": 0.05} | L33 | `minimal_roi = {"60": 0.075, "30": 0.1, "0": 0.05}` |
| stop | E | Stop-loss -0.05 (price level from the entry) | L36 | `stoploss = -0.05` |
| management | E | Trailing: trailing_stop = False | L40 | `trailing_stop = False` |
| management | E | can_short = True | L37 | `can_short = True` |
| data | E | startup_candle_count = 14 | L49 | `startup_candle_count: int = 14` |
| management | E | process_only_new_candles = True | L46 | `process_only_new_candles = True` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L54,55,58,59,60 | `pos_entry_adx = DecimalParameter(15, 40, decimals=1, default=30.0, space='buy') \| pos_exit_adx = DecimalParameter(15, 40, decimals=1, default=30.0, space='sell') \| adx_period = IntParameter(4, 24, default=14) \| ema_short_period = IntParameter(4, 24, default=8) \| ema_long_period = IntParameter(12` |
| indicator | E | Indicators as computed in populate_indicators | L62-87 | `for val in self.adx_period.range: dataframe[f"adx_{val}"] = ta.ADX(dataframe, timeperiod=val) for val in self.ema_short_period.range: dataframe[f"ema_short_{val}"] = ta.EMA(dataframe, timeperiod=val) for val in self.ema_long_period.range: dataframe[f"ema_long_{val}"] = ta.EMA(dataframe, timeperiod=v` |
| entry | E | Entry signal conditions (populate_entry_trend) | L89-125 | `conditions_long = [] conditions_short = [] conditions_long.append( dataframe["close"] > dataframe[f"resample_{self.resample_interval}_sma"] ) conditions_short.append( dataframe["close"] < dataframe[f"resample_{self.resample_interval}_sma"] ) conditions_long.append( qtpylib.crossed_above( dataframe[f` |
| exit | E | Exit signal conditions (populate_exit_trend) | L127-144 | `conditions_close = [] conditions_close.append( dataframe[f"adx_{self.adx_period.value}"] < self.pos_entry_adx.value ) dataframe.loc[ reduce(lambda x, y: x & y, conditions_close), "exit_long", ] = 1 dataframe.loc[ reduce(lambda x, y: x & y, conditions_close), "exit_short", ] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
