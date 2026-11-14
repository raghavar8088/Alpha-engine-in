# FT-Bandtastic — Bandtastic

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/Bandtastic.py#L21-L163
- Author: Robert Roman (__author__)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 15dcb60d49a3681241cd39645f0fe8e6dc247687bf878c2026f37bb1c5790b57

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 15m | L24 | `timeframe = '15m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.162, "69": 0.097, "229": 0.061, "566": 0} | L27 | `minimal_roi = { "0": 0.162, "69": 0.097, "229": 0.061, "566": 0 }` |
| stop | E | Stop-loss -0.345 (price level from the entry) | L35 | `stoploss = -0.345` |
| management | E | Trailing: trailing_stop = True, trailing_stop_positive = 0.01, trailing_stop_positive_offset = 0.058, trailing_only_offset_is_reached = False | L40,41,42,43 | `trailing_stop = True / trailing_stop_positive = 0.01 / trailing_stop_positive_offset = 0.058 / trailing_only_offset_is_reached = False` |
| data | E | startup_candle_count = 999 | L37 | `startup_candle_count = 999` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L46,47,48,49,51,52,53,54,57,58,59,60,62,63,64,65 | `buy_fastema = IntParameter(low=1, high=236, default=211, space='buy', optimize=True, load=True) \| buy_slowema = IntParameter(low=1, high=250, default=250, space='buy', optimize=True, load=True) \| buy_rsi = IntParameter(low=15, high=70, default=52, space='buy', optimize=True, load=True) \| buy_mfi ` |
| indicator | E | Indicators as computed in populate_indicators | L67-101 | `dataframe['rsi'] = ta.RSI(dataframe) dataframe['mfi'] = ta.MFI(dataframe) bollinger1 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=1) dataframe['bb_lowerband1'] = bollinger1['lower'] dataframe['bb_middleband1'] = bollinger1['mid'] dataframe['bb_upperband1'] = bollinger1` |
| entry | E | Entry signal conditions (populate_entry_trend) | L103-132 | `conditions = [] if self.buy_rsi_enabled.value: conditions.append(dataframe['rsi'] < self.buy_rsi.value) if self.buy_mfi_enabled.value: conditions.append(dataframe['mfi'] < self.buy_mfi.value) if self.buy_ema_enabled.value: conditions.append(dataframe[f'EMA_{self.buy_fastema.value}'] > dataframe[f'EM` |
| exit | E | Exit signal conditions (populate_exit_trend) | L134-163 | `conditions = [] if self.sell_rsi_enabled.value: conditions.append(dataframe['rsi'] > self.sell_rsi.value) if self.sell_mfi_enabled.value: conditions.append(dataframe['mfi'] > self.sell_mfi.value) if self.sell_ema_enabled.value: conditions.append(dataframe[f'EMA_{self.sell_fastema.value}'] < datafram` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
