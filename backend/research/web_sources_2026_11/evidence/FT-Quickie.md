# FT-Quickie — Quickie

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/Quickie.py#L12-L78
- Author: Gert Wohlgemuth (file tag 'author@')
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 85733568de6bb80c3db87e26faff93ab5e5da95dbb298cc42737365d3e6500a7

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L36 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"100": 0.01, "30": 0.03, "15": 0.06, "10": 0.15} | L24 | `minimal_roi = { "100": 0.01, "30": 0.03, "15": 0.06, "10": 0.15, }` |
| stop | E | Stop-loss -0.25 (price level from the entry) | L33 | `stoploss = -0.25` |
| indicator | E | Indicators as computed in populate_indicators | L38-56 | `macd = ta.MACD(dataframe) dataframe['macd'] = macd['macd'] dataframe['macdsignal'] = macd['macdsignal'] dataframe['macdhist'] = macd['macdhist'] dataframe['tema'] = ta.TEMA(dataframe, timeperiod=9) dataframe['sma_200'] = ta.SMA(dataframe, timeperiod=200) dataframe['sma_50'] = ta.SMA(dataframe, timep` |
| entry | E | Entry signal conditions (populate_entry_trend) | L58-68 | `dataframe.loc[ ( (dataframe['adx'] > 30) & (dataframe['tema'] < dataframe['bb_middleband']) & (dataframe['tema'] > dataframe['tema'].shift(1)) & (dataframe['sma_200'] > dataframe['close']) ), 'enter_long'] = 1` |
| exit | E | Exit signal conditions (populate_exit_trend) | L70-78 | `dataframe.loc[ ( (dataframe['adx'] > 70) & (dataframe['tema'] > dataframe['bb_middleband']) & (dataframe['tema'] < dataframe['tema'].shift(1)) ), 'exit_long'] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
