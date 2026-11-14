# FT-MultiRSI — MultiRSI

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/MultiRSI.py#L9-L71
- Author: Gert Wohlgemuth (file tag 'author@'; 'based on work from Creslin')
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 0bd453350bdf32db4355277d79a3c7268d166d043bab59e30403a1e97687aa06

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L26 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.01} | L18 | `minimal_roi = { "0": 0.01 }` |
| stop | E | Stop-loss -0.05 (price level from the entry) | L23 | `stoploss = -0.05` |
| indicator | E | Indicators as computed in populate_indicators | L31-52 | `dataframe['sma5'] = ta.SMA(dataframe, timeperiod=5) dataframe['sma200'] = ta.SMA(dataframe, timeperiod=200) dataframe_short = resample_to_interval(dataframe, self.get_ticker_indicator() * 2) dataframe_long = resample_to_interval(dataframe, self.get_ticker_indicator() * 8) dataframe_short['rsi'] = ta` |
| entry | E | Entry signal conditions (populate_entry_trend) | L54-62 | `dataframe.loc[ ( (dataframe['sma5'] >= dataframe['sma200']) & (dataframe['rsi'] < (dataframe['resample_{}_rsi'.format(self.get_ticker_indicator() * 8)] - 20)) ), 'enter_long'] = 1` |
| exit | E | Exit signal conditions (populate_exit_trend) | L64-71 | `dataframe.loc[ ( (dataframe['rsi'] > dataframe['resample_{}_rsi'.format(self.get_ticker_indicator()*2)]) & (dataframe['rsi'] > dataframe['resample_{}_rsi'.format(self.get_ticker_indicator()*8)]) ), 'exit_long'] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
