# FT-ReinforcedSmoothScalp — ReinforcedSmoothScalp

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/ReinforcedSmoothScalp.py#L14-L138
- Author: Gert Wohlgemuth
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 d510b70a62dfcde39697184f62b48e93cae8a6c87a67670e0fadb8bed51b73c5

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 1m | L34 | `timeframe = '1m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 0.02} | L24 | `minimal_roi = { "0": 0.02 }` |
| stop | E | Stop-loss -0.1 (price level from the entry) | L31 | `stoploss = -0.1` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L39,40,41,42,43,44,45,46,48,49,50,51,52,54,55,56,57,58 | `buy_adx = IntParameter(20, 50, default=32, space='buy') \| buy_fastd = IntParameter(15, 45, default=30, space='buy') \| buy_fastk = IntParameter(15, 45, default=26, space='buy') \| buy_mfi = IntParameter(10, 25, default=22, space='buy') \| buy_adx_enabled = BooleanParameter(default=True, space='buy'` |
| indicator | E | Indicators as computed in populate_indicators | L60-84 | `tf_res = timeframe_to_minutes(self.timeframe) * 5 df_res = resample_to_interval(dataframe, tf_res) df_res['sma'] = ta.SMA(df_res, 50, price='close') dataframe = resampled_merge(dataframe, df_res, fill_na=True) dataframe['resample_sma'] = dataframe[f'resample_{tf_res}_sma'] dataframe['ema_high'] = ta` |
| entry | E | Entry signal conditions (populate_entry_trend) | L86-110 | `conditions = [] if self.buy_mfi_enabled.value: conditions.append(dataframe['mfi'] < self.buy_mfi.value) if self.buy_fastd_enabled.value: conditions.append(dataframe['fastd'] < self.buy_fastd.value) if self.buy_fastk_enabled.value: conditions.append(dataframe['fastk'] < self.buy_fastk.value) if self.` |
| exit | E | Exit signal conditions (populate_exit_trend) | L112-138 | `conditions = [] conditions.append(dataframe['open'] > dataframe['ema_high']) if self.sell_mfi_enabled.value: conditions.append(dataframe['mfi'] > self.sell_mfi.value) if self.sell_fastd_enabled.value: conditions.append(dataframe['fastd'] > self.sell_fastd.value) if self.sell_fastk_enabled.value: con` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
