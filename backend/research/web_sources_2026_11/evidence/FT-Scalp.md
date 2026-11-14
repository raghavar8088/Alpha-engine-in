# FT-Scalp — Scalp

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/Scalp.py#L10-L75
- Author: Gert Wohlgemuth (first git author, 2018-06-27)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 3163f460f08db33b4aded14c00f880f6b5e5f2413489137e522c1f93a8954a65

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 1m | L32 | `timeframe = '1m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.01} | L22 | `minimal_roi = { "0": 0.01 }` |
| stop | E | Stop-loss -0.04 (price level from the entry) | L29 | `stoploss = -0.04` |
| indicator | E | Indicators as computed in populate_indicators | L34-49 | `dataframe['ema_high'] = ta.EMA(dataframe, timeperiod=5, price='high') dataframe['ema_close'] = ta.EMA(dataframe, timeperiod=5, price='close') dataframe['ema_low'] = ta.EMA(dataframe, timeperiod=5, price='low') stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0) dataframe['fastd'] = stoch_fast['fastd'] ` |
| entry | E | Entry signal conditions (populate_entry_trend) | L51-63 | `dataframe.loc[ ( (dataframe['open'] < dataframe['ema_low']) & (dataframe['adx'] > 30) & ( (dataframe['fastk'] < 30) & (dataframe['fastd'] < 30) & (qtpylib.crossed_above(dataframe['fastk'], dataframe['fastd'])) ) ), 'enter_long'] = 1` |
| exit | E | Exit signal conditions (populate_exit_trend) | L65-75 | `dataframe.loc[ ( (dataframe['open'] >= dataframe['ema_high']) ) \| ( (qtpylib.crossed_above(dataframe['fastk'], 70)) \| (qtpylib.crossed_above(dataframe['fastd'], 70)) ), 'exit_long'] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
