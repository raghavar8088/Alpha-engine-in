# FT-BinHV27 — BinHV27

- Source: GitHub · freqtrade/freqtrade-strategies — https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/BinHV27.py#L19-L137
- Author: Gert Wohlgemuth (first git author, 2018-06-27)
- Retrieved: 2026-11-13
- Licence / attribution: GPL-3.0 (repository LICENSE); attribution to the author and the freqtrade-strategies repository
- Version: commit f3340ce11f5bdf62f598522e64d1f5638eaa13f5; file sha256 e94ea092f9d277f29ce593f5adc1d9efffb846c27f1c1abfa51c57f1c53257b5

| Kind | Tag | Rule | Where | Excerpt |
|---|---|---|---|---|
| timeframe | E | Candle timeframe 5m | L31 | `timeframe = '5m'` |
| target | E | ROI table (minutes since entry: net profit ratio) {"0": 1} | L26 | `minimal_roi = { "0": 1 }` |
| stop | E | Stop-loss -0.5 (price level from the entry) | L30 | `stoploss = -0.50` |
| indicator | E | Indicators as computed in populate_indicators | L33-56 | `dataframe['rsi'] = numpy.nan_to_num(ta.RSI(dataframe, timeperiod=5)) rsiframe = DataFrame(dataframe['rsi']).rename(columns={'rsi': 'close'}) dataframe['emarsi'] = numpy.nan_to_num(ta.EMA(rsiframe, timeperiod=5)) dataframe['adx'] = numpy.nan_to_num(ta.ADX(dataframe)) dataframe['minusdi'] = numpy.nan_` |
| entry | E | Entry signal conditions (populate_entry_trend) | L58-94 | `dataframe.loc[ dataframe['slowsma'].gt(0) & dataframe['close'].lt(dataframe['highsma']) & dataframe['close'].lt(dataframe['lowsma']) & dataframe['minusdi'].gt(dataframe['minusdiema']) & dataframe['rsi'].ge(dataframe['rsi'].shift()) & ( ( ~dataframe['preparechangetrend'] & ~dataframe['continueup'] & ` |
| exit | E | Exit signal conditions (populate_exit_trend) | L96-137 | `dataframe.loc[ ( ( ~dataframe['preparechangetrendconfirm'] & ~dataframe['continueup'] & (dataframe['close'].gt(dataframe['lowsma']) \| dataframe['close'].gt(dataframe['highsma'])) & dataframe['highsma'].gt(0) & dataframe['bigdown'] ) \| ( ~dataframe['preparechangetrendconfirm'] & ~dataframe['continu` |
| timing | I | Signals are evaluated on CLOSED candles; freqtrade's backtester enters at the next candle's open | - | |
| order | I | No order types set in the strategy: the bot configuration decides (limit or market) | - | |
| sizing | I | Stake size and max open trades are not in the strategy: they come from the bot configuration | - | |
| management | I | No cooldown or pyramiding in the code: a new entry may follow the next signal after an exit | - | |
| session | I | No session or time filter: trades around the clock | - | |
| market | A | Tested on Binance BTC/USDT (2018-2026) and ETH/USDT (2021-2026) spot candles built from the repository's 1-minute data, $10,000 per trade, one position at a time, costs 0.10% + 2 bp a side, exits walked on 1-minute bars | - | |
| market | A | Perpetual adaptation (separate version): the same signals with Delta India taker 5.9 bp + 2 bp a side and Binance USDT-M funding, 2020-2026; spot prices stand in for the perpetual | - | |
