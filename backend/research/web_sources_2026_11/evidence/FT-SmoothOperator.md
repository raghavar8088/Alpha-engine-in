# FT-SmoothOperator — SmoothOperator

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/SmoothOperator.py#L15-L205
- Author: Gert Wohlgemuth (file tag 'author@')
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 46f608cc51f9b18e9bb52983776a6d55d9b13814a93f7666cc8ecdb4f86c3915

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L39 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.1} | L29 | `minimal_roi = { "0": 0.10 }` |
| stop | E | Stop-loss -0.05 (price level from the entry) | L36 | `stoploss = -0.05` |
| indicator | E | Indicators as computed in populate_indicators | L41-103 | `dataframe['cci'] = ta.CCI(dataframe, timeperiod=20) dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14) dataframe['adx'] = ta.ADX(dataframe) dataframe['mfi'] = ta.MFI(dataframe) dataframe['mfi_smooth'] = ta.EMA(dataframe, timeperiod=11, price='mfi') dataframe['cci_smooth'] = ta.EMA(dataframe, timepe` |
| entry | E | Entry signal conditions (populate_entry_trend) | L105-173 | `dataframe.loc[ ( ( ( (dataframe['average'].shift(5) > dataframe['average'].shift(4)) & (dataframe['average'].shift(4) > dataframe['average'].shift(3)) & (dataframe['average'].shift(3) > dataframe['average'].shift(2)) & (dataframe['average'].shift(2) > dataframe['average'].shift(1)) & (dataframe['ave` |
| exit | E | Exit signal conditions (populate_exit_trend) | L175-205 | `dataframe.loc[ ( ( ( (dataframe['mfi_rsi_cci_smooth'] > 100) & (dataframe['mfi_rsi_cci_smooth'].shift(1) > dataframe['mfi_rsi_cci_smooth']) & (dataframe['mfi_rsi_cci_smooth'].shift(2) < dataframe['mfi_rsi_cci_smooth'].shift(1)) & (dataframe['mfi_rsi_cci_smooth'].shift(3) < dataframe['mfi_rsi_cci_smo` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
