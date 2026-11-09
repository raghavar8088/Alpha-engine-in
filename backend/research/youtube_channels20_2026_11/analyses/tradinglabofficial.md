# TradingLab (@TradingLabOfficial, UCCbv0qixG-cyokxEY3kELtg)

English; short indicator-strategy videos for crypto, forex and stocks with "100 trades" TradingView tests (claims).
Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## TL-01 MACD cross on the far side of zero in the EMA 200 trend, stop beyond the EMA 200, 1.5R: rf_EQvubKlk
"BEST MACD Trading Strategy [86% Win Rate]" (2021-10-03, 7:06), https://youtu.be/rf_EQvubKlk
- Long: MACD line crosses above the signal line while both are below the zero line, and price is above the 200-period
  moving average; short mirror (cross down above zero, price below the 200) [E 02:00-04:00].
- Stop: below the 200 moving average ("a wall"); target 1.5x the risk [E 04:00-05:21].
- Advanced: only at a support / resistance level that held before [E 05:21-06:00] - discretionary, not coded.
- Timeframe not stated [A: 1 hour]. Code [A]: BTC and XAUUSD 1-hour; EMA 200 (the video says "200 day moving average"
  for the chart's own bars); stop = EMA 200 at the signal bar - 0.1 ATR, skipped when farther than 3 ATR(14); 1.5R;
  overnight allowed.
- Relation: the classic MACD + 200 line strategy (also taught by TRADING RUSH, RU-01) - see the dedupe table.
- Status: ready with documented assumptions.

## TL-02 Bollinger Band (30, 2) + RSI (13) mean reversion: a close beyond the band with RSI past 25/75, target the middle band: pCmJ8wsAS_w
"Bollinger Band + RSI Trading Strategy That Actually Works" (2021-10-07, 6:40), https://youtu.be/pCmJ8wsAS_w
- Transcript: YouTube's only caption track is a Dutch auto-caption of English speech, so the audio was transcribed with
  Whisper (small model) in the Video Lab (1,273 words, good quality).
- Bollinger Bands length 30, standard deviation 2; RSI length 13 with 70/30 lines [E 00:20-01:45].
- Long when price goes below the lower band and RSI is below 25; short when price goes above the upper band and RSI is
  above 75; the target is the return to the average (the middle band) [E 01:45-03:30].
- Avoid sideways squeezes: skinny bands with a tame RSI mean a break with momentum is coming - do not catch the knife
  [E 03:30-05:00]. A bullish RSI divergence after a lower-band break is a bonus [E 05:00-06:00] (not required).
- No stop and no timeframe are given.
- Code [A]: BTC and XAUUSD 15-minute; entry next bar open after a close beyond the band with RSI past 25/75; target =
  the middle band at the signal (a moving target is not used); stop = 2 x ATR(14) beyond the signal close; squeeze =
  band width (upper - lower) / middle below the 20th percentile of the last 100 bars -> skip; out at the session end.
- Status: requires documented assumptions (stop, timeframe, squeeze definition).

## TL-03 DEMA 200 side + Supertrend (12, 3) flip, stop at the Supertrend line, exit on the opposite flip: g-PLctW8aU0
"Highly Profitable DEMA + SuperTrend Trading Strategy" (2021-11-18, 8:24), https://youtu.be/g-PLctW8aU0
- DEMA length 200; Supertrend ATR 12, multiplier 3; example DOGE/USD 15 minutes [E 00:46-02:20].
- Long: price above the DEMA 200 and the Supertrend gives a buy signal; enter after that candle closes; also enter when
  price crosses above the DEMA after a Supertrend buy already printed [E 02:20-04:00, 05:06-06:00]. Short mirror [E 04:46].
- Stop: the Supertrend line at the signal; exit only on the opposite Supertrend signal (no fixed target) [E 02:20-04:46].
- Optional Fibonacci Bollinger Band exit (not backtested by them) [E 06:00] - not coded.
- Their test: DOGE and LTC, 100 trades in 2.5 months, 60% winners, +130% [E 07:19].
- Code [A]: BTC 15-minute (DOGE/LTC are not desk markets); entry next bar open; overnight allowed.
- Status: ready (Supertrend and DEMA settings explicit).

## TL-04 EMA 200 trend + RSI above 50 + closed engulfing candle, stop 2x the candle, 2R: XBcMiYK7qYY
"BEST Scalping Trading Strategy For Beginners (How To Scalp Forex, Stocks, and Crypto)" (2021-11-04, 7:22), https://youtu.be/XBcMiYK7qYY
- Rule 1: only with the trend - price above the EMA 200 for longs [E 00:48-01:47]. Rule 2: RSI above its 50 line
  (bullish divergence is a bonus, not required) [E 01:47-03:20]. Rule 3: a bullish engulfing candle (the indicator's
  green arrow), entered only after it closes [E 03:20-04:28].
- Stop: two times the length of the entry candle; target 2:1 [E 04:28-06:08]. Shorts are the mirror (red arrows) [I].
- "All markets, all timeframes" [E 00:00]. Code [A]: BTC and XAUUSD 15-minute; engulfing = body engulfs the previous
  opposite body (yc bull_engulf); RSI 14; stop = entry -/+ 2 x the engulfing candle's range; 2R; out at the session end.
- Status: ready with documented assumptions (timeframe).

## TL-05 Chandelier Exit (1, 2.3) + "BJ SuperScript" + RSI 25 over its SMA 150 + EMA 200, four targets: cxZOD1iOKVc - **blocked**
"I Tested A CRAZY RSI Scalping Strategy 100 Times" (2022-05-16, 6:12), https://youtu.be/cxZOD1iOKVc
- Rules are explicit except one: the "BJ SuperScript" community indicator (setting changed from 5 to 6) must be blue
  [E 00:14-03:02]; its formula is not given, so the entry cannot be reproduced. Stop at the recent swing; 25% off at 1,
  1.5, 2 and 3R [E 03:40-05:18]. Results only "in my Discord" [E 05:40].
- Not coded (no modified version invented).

## TradingLab summary
Coded: TL-01, TL-02 (Whisper transcript; assumed stop), TL-03, TL-04. Blocked: TL-05 (unknown indicator).
