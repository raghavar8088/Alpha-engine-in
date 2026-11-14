# FT-MACDStrategy_crossed — MACDStrategy_crossed

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/MACDStrategy_crossed.py#L13-L78
- Author: Gert Wohlgemuth
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 af5aed1cbb9a9d3ed519ea8649363a2cfaa95cbffe443f073d9f96b2aa91b0f6

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L38 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"60": 0.01, "30": 0.03, "20": 0.04, "0": 0.05} | L26 | `minimal_roi = { "60":  0.01, "30":  0.03, "20":  0.04, "0":  0.05 }` |
| stop | E | Stop-loss -0.3 (price level from the entry) | L35 | `stoploss = -0.3` |
| indicator | E | Indicators as computed in populate_indicators | L40-48 | `macd = ta.MACD(dataframe) dataframe['macd'] = macd['macd'] dataframe['macdsignal'] = macd['macdsignal'] dataframe['macdhist'] = macd['macdhist'] dataframe['cci'] = ta.CCI(dataframe)` |
| entry | E | Entry signal conditions (populate_entry_trend) | L50-63 | `Based on TA indicators, populates the buy signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal']) & (dataframe['cci'] <= -50.0) ), 'enter_long'] = 1` |
| exit | E | Exit signal conditions (populate_exit_trend) | L65-78 | `Based on TA indicators, populates the sell signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( qtpylib.crossed_below(dataframe['macd'], dataframe['macdsignal']) & (dataframe['cci'] >= 100.0) ), 'exit_long'] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
