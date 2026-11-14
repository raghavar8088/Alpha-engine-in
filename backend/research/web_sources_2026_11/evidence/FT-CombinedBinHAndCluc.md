# FT-CombinedBinHAndCluc — CombinedBinHAndCluc

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/CombinedBinHAndCluc.py#L17-L76
- Author: Gert Wohlgemuth (first git author, 2018-06-27)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 546256271db535f1e326130c6b2d9849dd9a5efb602eb92ed45dad282967f45d

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L28 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.05} | L24 | `minimal_roi = { "0": 0.05 }` |
| stop | E | Stop-loss -0.05 (price level from the entry) | L27 | `stoploss = -0.05` |
| management | E | use_exit_signal = True | L30 | `use_exit_signal = True` |
| management | E | exit_profit_only = True | L31 | `exit_profit_only = True` |
| management | E | ignore_roi_if_entry_signal = False | L32 | `ignore_roi_if_entry_signal = False` |
| indicator | E | Indicators as computed in populate_indicators | L34-48 | `mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2) dataframe['lower'] = lower dataframe['bbdelta'] = (mid - dataframe['lower']).abs() dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs() dataframe['tail'] = (dataframe['close'] - dataframe['low` |
| entry | E | Entry signal conditions (populate_entry_trend) | L50-67 | `dataframe.loc[ (  # strategy BinHV45 dataframe['lower'].shift().gt(0) & dataframe['bbdelta'].gt(dataframe['close'] * 0.008) & dataframe['closedelta'].gt(dataframe['close'] * 0.0175) & dataframe['tail'].lt(dataframe['bbdelta'] * 0.25) & dataframe['close'].lt(dataframe['lower'].shift()) & dataframe['c` |
| exit | E | Exit signal conditions (populate_exit_trend) | L69-76 | `dataframe.loc[ (dataframe['close'] > dataframe['bb_middleband']), 'exit_long' ] = 1` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
