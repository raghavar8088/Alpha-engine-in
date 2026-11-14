# FT-Strategy005 — Strategy005

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/Strategy005.py#L14-L185
- Author: Gerald Lonlas (file tag 'author@')
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 797b293f5acd809f8c77f26b38c004c87b75d8847be4cde4d0224040cc591030

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L40 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"1440": 0.01, "80": 0.02, "40": 0.03, "20": 0.04, "0": 0.05} | L27 | `minimal_roi = { "1440": 0.01, "80": 0.02, "40": 0.03, "20": 0.04, "0":  0.05 }` |
| stop | E | Stop-loss -0.1 (price level from the entry) | L37 | `stoploss = -0.10` |
| management | E | Trailing: trailing_stop = False, trailing_stop_positive = 0.01, trailing_stop_positive_offset = 0.02 | L43,44,45 | `trailing_stop = False / trailing_stop_positive = 0.01 / trailing_stop_positive_offset = 0.02` |
| management | E | use_exit_signal = True | L51 | `use_exit_signal = True` |
| management | E | exit_profit_only = True | L52 | `exit_profit_only = True` |
| management | E | ignore_roi_if_entry_signal = False | L53 | `ignore_roi_if_entry_signal = False` |
| management | E | process_only_new_candles = True | L48 | `process_only_new_candles = True` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L63,64,65,66,68,69,70,71,75,83 | `buy_volumeAVG = IntParameter(low=50, high=300, default=70, space='buy', optimize=True) \| buy_rsi = IntParameter(low=1, high=100, default=30, space='buy', optimize=True) \| buy_fastd = IntParameter(low=1, high=100, default=30, space='buy', optimize=True) \| buy_fishRsiNorma = IntParameter(low=1, hig` |
| indicator | E | Indicators as computed in populate_indicators | L103-143 | `Adds several different TA indicators to the given DataFrame Performance Note: For the best performance be frugal on the number of indicators you are using. Let uncomment only the indicator you are using in your strategies or your hyperopt configuration, otherwise you will waste your memory and CPU u` |
| entry | E | Entry signal conditions (populate_entry_trend) | L145-164 | `Based on TA indicators, populates the buy signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( (dataframe['close'] > 0.00000200) & (dataframe['volume'] > dataframe['volume'].rolling(self.buy_volumeAVG.value).mean() * 4) & (dataframe['close'] ` |
| exit | E | Exit signal conditions (populate_exit_trend) | L166-185 | `Based on TA indicators, populates the sell signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column conditions = [] if self.sell_trigger.value == 'rsi-macd-minusdi': conditions.append(qtpylib.crossed_above(dataframe['rsi'], self.sell_rsi.value)) conditions.append` |
| management | E | Callback informative_pairs | L90-101 | `Define additional, informative pair/interval combinations to be cached from the exchange. These pair/interval combinations are non-tradeable, unless they are part of the whitelist as well. For more information, please consult the documentation :return: List of tuples in the format (pair, interval) S` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
