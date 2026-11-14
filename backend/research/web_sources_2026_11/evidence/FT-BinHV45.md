# FT-BinHV45 — BinHV45

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/BinHV45.py#L20-L71
- Author: Gert Wohlgemuth (first git author, 2018-06-27; no author tag in the file)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 ae76994b6fc8dd1937d84fc6d5ef0b9d7b702f01f61f5ccf5a2870278a3422a2

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 1m | L28 | `timeframe = '1m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.0125} | L23 | `minimal_roi = { "0": 0.0125 }` |
| stop | E | Stop-loss -0.05 (price level from the entry) | L27 | `stoploss = -0.05` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L30,31,32,35 | `buy_bbdelta = IntParameter(low=1, high=15, default=30, space='buy', optimize=True) \| buy_closedelta = IntParameter(low=15, high=20, default=30, space='buy', optimize=True) \| buy_tail = IntParameter(low=20, high=30, default=30, space='buy', optimize=True) \| buy_params = {'buy_bbdelta': 7, 'buy_clo` |
| indicator | E | Indicators as computed in populate_indicators | L41-51 | `bollinger = qtpylib.bollinger_bands(dataframe['close'], window=40, stds=2) dataframe['upper'] = bollinger['upper'] dataframe['mid'] = bollinger['mid'] dataframe['lower'] = bollinger['lower'] dataframe['bbdelta'] = (dataframe['mid'] - dataframe['lower']).abs() dataframe['pricedelta'] = (dataframe['op` |
| entry | E | Entry signal conditions (populate_entry_trend) | L53-64 | `dataframe.loc[ ( dataframe['lower'].shift().gt(0) & dataframe['bbdelta'].gt(dataframe['close'] * self.buy_bbdelta.value / 1000) & dataframe['closedelta'].gt(dataframe['close'] * self.buy_closedelta.value / 1000) & dataframe['tail'].lt(dataframe['bbdelta'] * self.buy_tail.value / 1000) & dataframe['c` |
| exit | E | Exit signal conditions (populate_exit_trend) | L66-71 | `no sell signal dataframe.loc[:, 'exit_long'] = 0` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
