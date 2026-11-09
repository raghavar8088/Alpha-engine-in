# TRADING RUSH (@TRADINGRUSH, UCgY_eHY4NCTcRnU6CCZXWng)

Ids use the prefix RU-: the library's TR- prefix already belongs to The Trade Room (11-channel study).

English; each video tests one indicator strategy 100 times by hand on forex charts (results are the channel's own
claims). His standard test: 1% risk, 1.5R target. Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## RU-01 MACD crossover below zero in the EMA 200 trend, stop below the pullback, 1.5R: nmffSjdZbWQ
"I risked MACD Trading Strategy 100 TIMES Here's What Happened..." (2020-01-23, 10:07), https://youtu.be/nmffSjdZbWQ
- Buy: price above EMA 200 and the MACD line crosses above the signal line well below the zero line; sell mirror
  (above zero, price below EMA 200) [E 00:00-02:30]. Stop below the pullback (swing low); his test target 1.5R; he
  personally takes 25% at 1R, stop to break-even, rest at 2R [E 02:30-05:00]. Skip confusing signals [E 05:00].
- "Works on all timeframes" [E 05:00]. His result: 100 trades, ~62% winners, +50% at 1% risk [E 07:00-08:00].
- Code [A]: BTC and XAUUSD 1-hour; swing = the lowest low (highest high) of the last 10 bars; 1.5R (his test rule);
  overnight allowed.
- Relation: TL-01 (TradingLab) is the same entry with the stop beyond the EMA 200 - kept as two stop variants.
- Status: ready with documented assumptions (timeframe).

## (not a strategy) Fibonacci retracement study: 26s8e-92AzY
"I tested Fibonacci Trading Strategy 100 TIMES to find the truth about Fibonacci Retracements" (2020-10-08, 9:42), https://youtu.be/26s8e-92AzY
- A measurement of where 100 trending pullbacks (zig-zag swings, EMA 200 trend) reversed: 23.6% 6%, 38.2% 18%, 50% 14%,
  61.8% 15%, 78.6% 14%, through all levels 33% - his conclusion: the levels show no special value [E 05:00-08:00].
  No trading rules -> educational / research content, not coded.

## RU-02 Stochastic %K below 20, then a MACD bullish cross (either side of zero), swing stop, 1.5R: ifekTKhtCKU
"I took 100 trades with MACD + STOCHASTIC Trading Strategy and the results were..." (2020-10-14, 8:38), https://youtu.be/ifekTKhtCKU
- Buy: %K goes below 20 (oversold); then the next bullish MACD signal-line cross (need not be below zero) -> buy; stop
  below the swing low. Sell mirror (%K above 80, then a bearish cross; stop above the swing high) [E 03:00-05:00].
- Better: buys only if %K is still below 80 at entry (sells only if above 20) [E 06:00-07:00]. 1.5R; ~53% winners [E 07:00-08:30].
- Code [A]: BTC and XAUUSD 30-minute; Stochastic 14 3 3 [A: default]; the cross must come within 20 bars of the
  oversold reading; the %K < 80 filter included; swing = last 10 bars; 1.5R.
- Relation: DT-03 adds an RSI-50 filter and requires both stochastic lines; this one does not - kept.
- Status: ready with documented assumptions.

## RU-03 "Opposite RSI" momentum: RSI crosses above 70 with ADX > 25 in the EMA 200 trend, stop beyond EMA 21, 1.5R: uSkGE0ujyn4
"I tested RSI + ADX Trading Strategy 100 TIMES and you should..." (2021-01-09, 10:01), https://youtu.be/uSkGE0ujyn4
- Buy when RSI crosses above 70, ADX above 25 and price above EMA 200; sell when RSI crosses below 30, ADX > 25,
  price below EMA 200; stop beyond the EMA 21; 1.5R [E 01:30-05:30].
- His result: ~36% winners, 13 losses in a row - "one of the worst strategies" [E 05:30-08:00]. Coded anyway as a
  source-faithful book (the paper desk records it like any other; a negative claim is not a reason to skip it).
- Code [A]: BTC and XAUUSD 30-minute; RSI 14, ADX 14; stop = EMA 21 at the signal -/+ 0.1 ATR, skipped if closer than 0.3 ATR.
- Status: ready.

## RU-04 Williams fractal breakout in the 200 MA trend: close beyond the latest fractal candle, stop at the opposite fractal, 1.5R: f5ZW47Wlaek
"I tested FRACTAL Breakout Trading Strategy 100 TIMES and then this happened..." (2020-11-18, 9:27), https://youtu.be/f5ZW47Wlaek
- Price above the 200-period moving average: when a candle closes above the high of the latest up-fractal candle, buy
  at that close; stop below the latest down-fractal candle; sells mirror below the 200 [E 02:00-05:00]. Only the latest
  fractal counts; take trades only when the fractal candle and the entry candle are on the same side of the MA [E 05:00-06:00].
- His result: ~48% winners at 1.5R [E 07:30-08:30].
- Code [A]: BTC and XAUUSD 30-minute; Williams fractal n=2 (usable once confirmed); EMA 200 [A: "200 period moving
  average"]; entry next bar open after the close; 1.5R.
- Relation: DE-02 uses fractals as pullback signals inside an EMA stack - different entry - kept.
- Status: ready.

### RU-01 second source (same strategy on bitcoin, merged): 2NI44nAh3co
"BEST Bitcoin Trading Strategy EVER with PROOF tested 100 TIMES" (2021-07-24, 8:49), https://youtu.be/2NI44nAh3co
- The only caption track is a Portuguese auto-caption of English speech; transcribed with Whisper (small model) in the
  Video Lab (1,446 words).
- The same MACD strategy tested 100 times on bitcoin: buy on a MACD cross up below zero with the entry candle above the
  200-period moving average; sell the mirror; stop beyond the pullback; target 1.5x the stop [E 01:00-02:30]. His
  bitcoin result: about 62% winners at 1.5R, at most 3 losses in a row [E 07:30-08:30] (claims).
- Merged into RU-01 as a duplicate video (it confirms the rule on BTC).

## TRADING RUSH summary
Coded: RU-01 to RU-04 (ids renamed from TR- because the library's TR- prefix belongs to The Trade Room). Not a
strategy: 26s8e-92AzY (Fibonacci study). Duplicate video: 2NI44nAh3co (RU-01 on bitcoin).
