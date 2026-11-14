# FT-CCIStrategy — CCIStrategy

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/CCIStrategy.py#L12-L120
- Author: Gert Wohlgemuth (first git author, 2018-06-27)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 c3b1f8b57850d12a1e1b4e1ec42e92b842b2384f439e177f9e711bd20d698aad

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 1m | L25 | `timeframe = '1m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.1} | L16 | `minimal_roi = { "0": 0.1 }` |
| stop | E | Stop-loss -0.02 (price level from the entry) | L22 | `stoploss = -0.02` |
| indicator | E | Indicators as computed in populate_indicators | L27-43 | `dataframe = self.resample(dataframe, self.timeframe, 5) dataframe['cci_one'] = ta.CCI(dataframe, timeperiod=170) dataframe['cci_two'] = ta.CCI(dataframe, timeperiod=34) dataframe['rsi'] = ta.RSI(dataframe) dataframe['mfi'] = ta.MFI(dataframe) dataframe['cmf'] = self.chaikin_mf(dataframe) bollinger =` |
| entry | E | Entry signal conditions (populate_entry_trend) | L45-65 | `Based on TA indicators, populates the buy signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( (dataframe['cci_one'] < -100) & (dataframe['cci_two'] < -100) & (dataframe['cmf'] < -0.1) & (dataframe['mfi'] < 25) & (dataframe['resample_medium']` |
| exit | E | Exit signal conditions (populate_exit_trend) | L67-83 | `Based on TA indicators, populates the sell signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( (dataframe['cci_one'] > 100) & (dataframe['cci_two'] > 100) & (dataframe['cmf'] > 0.3) & (dataframe['resample_sma'] < dataframe['resample_medium']` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
