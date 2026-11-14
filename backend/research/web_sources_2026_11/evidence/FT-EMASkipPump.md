# FT-EMASkipPump — EMASkipPump

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/EMASkipPump.py#L12-L86
- Author: Gert Wohlgemuth (first git author, 2018-06-27)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 74117c68b3407a775d80fc4d4f1b27852689baad2255f19a7026a2b0c45b2085

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L35 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.1} | L25 | `minimal_roi = { "0": 0.1 }` |
| stop | E | Stop-loss -0.05 (price level from the entry) | L32 | `stoploss = -0.05` |
| indicator | E | Indicators as computed in populate_indicators | L37-61 | `dataframe['ema_{}'.format(self.EMA_SHORT_TERM)] = ta.EMA( dataframe, timeperiod=self.EMA_SHORT_TERM ) dataframe['ema_{}'.format(self.EMA_MEDIUM_TERM)] = ta.EMA( dataframe, timeperiod=self.EMA_MEDIUM_TERM ) dataframe['ema_{}'.format(self.EMA_LONG_TERM)] = ta.EMA( dataframe, timeperiod=self.EMA_LONG_T` |
| entry | E | Entry signal conditions (populate_entry_trend) | L63-74 | `dataframe.loc[ (dataframe['volume'] < (dataframe['volume'].rolling(window=30).mean().shift(1) * 20)) & (dataframe['close'] < dataframe['ema_{}'.format(self.EMA_SHORT_TERM)]) & (dataframe['close'] < dataframe['ema_{}'.format(self.EMA_MEDIUM_TERM)]) & (dataframe['close'] == dataframe['min']) & (datafr` |
| exit | E | Exit signal conditions (populate_exit_trend) | L76-86 | `dataframe.loc[ (dataframe['close'] > dataframe['ema_{}'.format(self.EMA_SHORT_TERM)]) & (dataframe['close'] > dataframe['ema_{}'.format(self.EMA_MEDIUM_TERM)]) & (dataframe['close'] >= dataframe['max']) & (dataframe['close'] >= dataframe['bb_upperband']), 'exit_long' ] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
