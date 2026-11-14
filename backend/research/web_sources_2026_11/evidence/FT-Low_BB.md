# FT-Low_BB — Low_BB

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/Low_BB.py#L21-L109
- Author: Thorsten (file tag 'author@')
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 36e058d11b438beeab017d293558d06976e950542b6568b2207b7f42940ff63b

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 1m | L47 | `timeframe = '1m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.9, "1": 0.05, "10": 0.04, "15": 0.5} | L35 | `minimal_roi = { "0": 0.9, "1": 0.05, "10": 0.04, "15": 0.5 }` |
| stop | E | Stop-loss -0.015 (price level from the entry) | L44 | `stoploss = -0.015` |
| indicator | E | Indicators as computed in populate_indicators | L49-81 | `bollinger = qtpylib.bollinger_bands( qtpylib.typical_price(dataframe), window=20, stds=2 ) dataframe['bb_lowerband'] = bollinger['lower'] dataframe['bb_middleband'] = bollinger['mid'] dataframe['bb_upperband'] = bollinger['upper'] macd = ta.MACD(dataframe) dataframe['macd'] = macd['macd'] dataframe[` |
| entry | E | Entry signal conditions (populate_entry_trend) | L83-98 | `Based on TA indicators, populates the buy signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( (dataframe['close'] <= 0.98 * dataframe['bb_lowerband']) ) , 'enter_long'] = 1` |
| exit | E | Exit signal conditions (populate_exit_trend) | L100-109 | `Based on TA indicators, populates the sell signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ (), 'exit_long'] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
