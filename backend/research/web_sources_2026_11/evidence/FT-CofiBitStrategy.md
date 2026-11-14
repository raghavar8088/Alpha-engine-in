# FT-CofiBitStrategy — CofiBitStrategy

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/CofiBitStrategy.py#L12-L94
- Author: Gert Wohlgemuth (first git author, 2018-06-27)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 c565296f014ade283b684cae3ff375bd1b80c8696d7b8498b2b5915d2a6553ff

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L43 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"40": 0.05, "30": 0.06, "20": 0.07, "0": 0.1} | L31 | `minimal_roi = { "40": 0.05, "30": 0.06, "20": 0.07, "0": 0.10 }` |
| stop | E | Stop-loss -0.25 (price level from the entry) | L40 | `stoploss = -0.25` |
| indicator | E | Shipped parameter values (hyperopt dictionaries override Parameter defaults) | L19,25,45,46,47 | `buy_params = {'buy_fastx': 25, 'buy_adx': 25} \| sell_params = {'sell_fastx': 75} \| buy_fastx = IntParameter(20, 30, default=25) \| buy_adx = IntParameter(20, 30, default=25) \| sell_fastx = IntParameter(70, 80, default=75)` |
| indicator | E | Indicators as computed in populate_indicators | L49-58 | `stoch_fast = ta.STOCHF(dataframe, 5, 3, 0, 3, 0) dataframe['fastd'] = stoch_fast['fastd'] dataframe['fastk'] = stoch_fast['fastk'] dataframe['ema_high'] = ta.EMA(dataframe, timeperiod=5, price='high') dataframe['ema_close'] = ta.EMA(dataframe, timeperiod=5, price='close') dataframe['ema_low'] = ta.E` |
| entry | E | Entry signal conditions (populate_entry_trend) | L60-76 | `Based on TA indicators, populates the buy signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( (dataframe['open'] < dataframe['ema_low']) & (qtpylib.crossed_above(dataframe['fastk'], dataframe['fastd'])) & (dataframe['fastk'] < self.buy_fastx` |
| exit | E | Exit signal conditions (populate_exit_trend) | L78-94 | `Based on TA indicators, populates the sell signal for the given dataframe :param dataframe: DataFrame :return: DataFrame with buy column dataframe.loc[ ( (dataframe['open'] >= dataframe['ema_high']) ) \| ( (qtpylib.crossed_above(dataframe['fastk'], self.sell_fastx.value)) \| (qtpylib.crossed_above(d` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
