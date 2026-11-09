# Neeraj Joshi (@Neerajjoshi): video analyses

Tags: E = stated or shown in the video; I = inferred from the video's reasoning or examples; A = a research
assumption added to make the rule testable. Times are HH:MM:SS in the video.

## NJ-01 9:20 VWAP + EMA(7) first-candle breakout (GXSNSC3LHZY, 12 Sep 2022, 16 min, 1.7M views)

Market: NSE stocks (cash, intraday), 5-minute candles (E 00:01:30). Read in full.

- Direction from the index (E 00:00:15-00:00:30): if Nifty opens gap-up / the market is positive, take only longs;
  gap-down / negative, only shorts. A: "gap" = Nifty's 09:15 open vs the previous close; up if open > previous close.
- Indicators (E 00:01:30-00:03:30): VWAP (bands switched off) and EMA with its length changed from 9 to 7.
- Long conditions on the first 5-minute candle, 09:15-09:20 (E 00:03:30-00:06:00, 00:13:00-00:13:45 his screener):
  1. the candle is green (close > open);
  2. VWAP passes through the candle body: the candle opens below VWAP and closes above VWAP (screener wording);
  3. EMA(7) is below VWAP (screener: "VWAP above EMA").
- Short conditions (E 00:11:00-00:12:00): first candle red; VWAP inside the body (opens above, closes below); EMA(7)
  above VWAP.
- Entry (E 00:06:30-00:07:00): after 09:20 mark the first candle's high and low; buy when a later candle breaks the
  high (sell when one breaks the low). I: a stop-entry order at the first candle's high/low, valid the rest of the day.
- Stop (E 00:07:00, 00:12:30): the first candle's other side (low for longs, high for shorts).
- Exit (E 00:07:00-00:08:00, 00:15:00): no fixed target. 1:2 or 1:3 "can be used but will not always work"; the best
  way is a trailing stop. His example: buy 893, stop 885 (risk 8); at 900 the stop goes to 893; at 905 to 900; at 910
  to 905. I: the stop steps up behind price, first to breakeven once price is about +1R, then it trails about
  0.6R below the highest price reached. A: breakeven at +1R, then a trail 0.6R behind the best price; out at the
  session's end (intraday).
- Once a day per stock (E 00:14:20): the setup exists only on the first candle.
- Stock selection (E 00:13:00-00:14:20): a screener at exactly 09:20 with the four conditions above, run over all
  stocks. A: the desk's NSE 5-minute pool (the same liquid universe as the other stock books).
- Limits (E 00:14:20-00:15:00): use only at 09:20, target unclear.
- Frames needed: none essential (indicator settings are spoken: VWAP, EMA 7).

## NJ-02 Pivot points + CPR open-side trade (F1S6OF5LFV8, 21 Jan 2023, 19 min)

Market: shares and index (cash/futures, or options as the vehicle), intraday. Read in full.

- Levels (E 00:00:30-00:03:00): classic floor pivots from the previous day's high, low and close: P = (H+L+C)/3, with
  R1-R3 and S1-S3 (TradingView "Pivot Points Standard", traditional). CPR (E 00:09:00-00:11:30): TC, P and BC from the
  previous day (A: the standard formulas BC = (H+L)/2, TC = 2P - BC, swapped when BC > TC).
- Bias (E 00:03:00-00:04:30): opening above P means a bullish day (buy); opening below P a bearish day (sell or buy
  puts).
- Entry zone and targets (E 00:04:30-00:06:00, 00:16:30): buy when price is between P and R1; first target R1, then R2
  if R1 is reached. Sell when price is between P and S1; targets S1 then S2.
- Don't chase (E 00:06:00-00:07:30): above R2 the share is "overbought", don't buy there; below S2 "oversold", don't
  sell there.
- Filter (E 00:07:30-00:13:30, 00:17:30): pivots alone give many false signals. A wide CPR (gaps between the three
  lines) means a sideways day: no trade. A narrow CPR (the three lines nearly one line) means a trending day: trade
  in the direction of the open (above P buy, below P sell). The width threshold is not given. A: narrow = today's CPR
  width (TC - BC) is in the narrowest third of the last 20 sessions' widths; otherwise no trade.
- Virgin CPR (E 00:14:15-00:15:30): if price never touches the day's CPR, extend it to the next day, where it acts
  as strong resistance/support (reversal trade). No stop or target is given: noted, not implemented.
- Stop: not given ("don't trade without risk management", E 00:18:30). A: the stop is on the far side of the CPR (BC
  for longs, TC for shorts), which is where the open-side bias is proved wrong.
- Entry timing: not given beyond "opens above/below". A: the decision is taken on the first 5-minute candle's close
  (09:20); enter at the next open if price is still between P and R1 (long) or P and S1 (short).
- Exit (A, from the two targets): half off at R1 (S1), stop to breakeven, the rest at R2 (S2); otherwise out at the
  session's end. The engine's partial books half at a fixed R multiple, so the R1 partial is placed at the R1 price
  for each trade.
- Universe: the video uses single shares (Tata Motors examples). A: the desk's NSE 5-minute stock pool and NIFTY.

## NJ-03 9 EMA + ADX trend breakout (tCDjjppruBo, 5 Sep 2024, 17 min)

Market: shares and options, intraday. Read in full. Timeframe not stated (A: 5-minute).

- Trend strength (E 00:02:15-00:05:15): ADX below about 25 means a sideways market, no trade; above 25 a trending
  market (it says nothing about direction).
- DMI cross (E 00:05:15-00:09:00): +DI crossing above -DI is bullish, -DI above +DI bearish; fails in sideways
  markets, which is why ADX is added. Shown as a lead-in, not the final strategy.
- Final strategy (E 00:09:00-00:16:30): EMA 9 (default length, unchanged).
  - Long: candles above EMA 9 (uptrend), and ADX above 25 and rising (E 00:11:45: "not only above, it must be rising").
    When ADX moves above 25, mark that candle's high and low; buy on the candle that breaks the high; stop below that
    candle's low (E 00:12:00-00:12:45: a big signal candle means a big stop, accepted).
  - Short: candles below EMA 9, ADX above 25 and rising; mark the candle where price went below the EMA; sell on the
    break of its low; stop above its high (E 00:15:00-00:16:00).
  - Exit (E 00:12:45-00:13:30): not on the EMA; exit as soon as the ADX line starts to fall (trend strength fading).
    A: the first closed candle whose ADX is below the previous candle's ADX; exit at the next open. Out at the
    session's end otherwise.
- A: the signal candle is the first candle on which all conditions hold (price on the EMA side, ADX > 25 and rising);
  the stop-entry is valid for the next 3 candles; ADX and DI use Wilder smoothing, length 14 (TradingView default).

## NJ-04 10 EMA failed-pullback breakout, Anant Ladha (HJu_Nxj495I, 18 Nov 2024, 11 min)

Guest: Anant Ladha. Market: "mostly the index" (E 00:02:00), 5- or 15-minute candles, shown on 5-minute (E
00:02:15). Read in full. (Pushkar Raj Thakur's 2dnl5TggSJw is the same guest strategy: cross-checked there.)

- Indicator (E 00:02:00): EMA 10, default settings.
- Short (E 00:02:30-00:04:00): candles are forming below EMA 10 (market under pressure); a green candle forms that does
  not touch EMA 10; if the very next candle breaks that green candle's low, short. If the next candle does not break
  it, it is not a trigger candle (E 00:04:30).
- Long (E 00:05:00-00:06:45): the mirror: above EMA 10, a red candle that does not touch EMA 10, the next candle
  breaks its high: buy.
- Stop (E 00:03:30, 00:06:45): the trigger candle's other end (the lower-risk choice for new traders), or ultimately
  the EMA 10 line. A: the trigger candle's other end.
- Targets (E 00:03:45, 00:06:45-00:07:30): 1:2 minimum, 1:3 normal. Trail: a candle closing back across EMA 10 ends
  the trade (E 00:04:00). Morning entries: trail beyond 1:2, aim for 1:3-1:4 (E 00:09:00). Entries around 12:30-13:30:
  book at 1:2 (E 00:09:00-00:09:30).
- Five extra points (E 00:08:00-00:09:45): avoid Tuesdays (volatile); Wednesday and Thursday give the best results; the
  two windows to watch are 09:15-10:00 and 13:45-14:15.
- A (testable form): signals only in 09:15-10:00 and 13:45-14:15, no Tuesdays; "below EMA 10" = the trigger candle's
  high is below EMA 10 and the previous candle closed below it (mirror for longs); the stop-entry is valid for the
  next candle only; target 3R in the morning window and 2R in the afternoon window; exit at the next open after a
  5-minute close across EMA 10; out at the session's end. Market: NIFTY.

## NJ-05 EMA 50/100 + Stochastic scalp (cZYwHdF-GpM, 31 May 2023, 11 min, live trade)

Market: BANKNIFTY (options as the vehicle), 1-minute candles (E 00:00:15-00:00:30). Read in full.

- Indicators (E 00:00:30-00:03:00): EMA 50 (green), EMA 100 (red), Stochastic oscillator (default settings; A:
  TradingView default %K 14, smoothing 1, %D 3).
- Long / call (E 00:03:00-00:05:30): EMA 50 above EMA 100 (only calls then); the Stochastic %K (blue) crosses above %D
  (orange) near 20, the low end of its range. Buy.
- Short / put (E 00:06:00-00:07:00): EMA 100 above EMA 50; %K crosses below %D near 80. Buy puts.
- Stop (E 00:05:30, 00:07:00): longs: the low of the candle before the entry candle (= the cross candle); shorts: just
  above the candle the trade was taken on.
- Exit (E 00:05:30-00:06:00, 00:07:15-00:07:30): either a fixed 15-25 BankNifty points, or when the Stochastic reaches
  80 (longs) / 20 (shorts). Live trade (E 00:09:30-00:10:00): exited at about +10% on the option premium.
- A: "near 20" = %D at or below 25 on the cross candle ("near 80" = at or above 75); enter at the next 1-minute open;
  stop at the cross candle's low (long) / high (short); exit at the next open after %K reaches 80 (long) / 20
  (short), or the stop; out at the session's end. Up to 3 trades a day, stopping after 2 stops (A, scalping).

## NJ-06 Bollinger squeeze breakout (X-cXuxvSg0c, 2 Jul 2021, 12 min)

Market: shares (his screener "Neeraj Joshi Bollinger Band Squeeze Breakout"), intraday on 15-minute candles (5 or 10
also allowed, E 00:07:30). Digest read (rule part in full).

- Bands (E 00:03:00): Bollinger 20, 2 standard deviations, the defaults ("don't change them").
- First use (E 00:01:00-00:06:30): buy near the lower band once a second candle confirms the turn, sell near the upper
  band; wait for the second candle after a touch, because price can ride outside a band. No stop given; the 2023
  masterclass (NJ-07) says the plain touch approach is wrong, so this use is not implemented.
- Squeeze breakout (E 00:06:30-00:09:30): when the bands become very narrow (a squeeze), the first candle that breaks
  out through the upper band is an immediate buy (through the lower band, a short). Stop: the breakout candle's low
  (high for shorts). Target: book when any candle closes back inside the bands.
- A: squeeze = band width (upper - lower) / middle is in the lowest 20% of the last 100 candles at some point in the
  5 candles before the breakout; "breaks the upper band" = a candle closing above the upper band; enter at the next
  open; exit at the next open after a close back inside the bands; out at the session's end. One trade per stock per
  day. Universe: the desk's NSE 15-minute stock pool.

## NJ-07 Bollinger band turn + MACD cross + volume (4o5OOAyuJ1Y, 26 Dec 2023, 13 min)

Market: shares (daily examples; 5-minute for intraday, E 00:09:00). Digest read (rule part in full).

- Bands (E 00:00:30-00:02:00): Bollinger 20 SMA, 2 standard deviations.
- Way 1 (E 00:02:30-00:05:30): a touch is not a signal. Sell when price touches the upper band and turns down while
  volume falls; buy when price touches the lower band and turns up.
- Way 2 (E 00:05:30-00:07:30): squeeze then expansion, with volume rising (same idea as NJ-06's squeeze).
- Way 3 (E 00:07:30-00:08:30): the middle band acts as support/resistance; add on a cross of it.
- Combined strategy (E 00:09:30-00:12:00): price touches the lower band and starts rising, the MACD line crosses above
  its signal line, and volume is rising: buy at the MACD cross. Stop: the nearest swing low, or a little below it.
  Target: hold until the MACD line crosses back below the signal line. Shorts mirror it at the upper band.
- A: MACD 12/26/9; "touched the lower band" = a low at or below the lower band in the last 5 candles; "rising volume"
  = the cross candle's volume above its 20-candle average; stop = the lowest low of the last 5 candles; exit at the
  next open after the opposite MACD cross; out at the session's end. Universe: the desk's NSE 5-minute stock pool
  (the index has no volume).

## NJ-08 RSI 50 + EMA 14 cross (mEqAjWoJUBg, 5 Apr 2024, 12 min: four RSI strategies)

Market: options, intraday and swing (E 00:00:00). Digest read (rule parts in full). Of the four strategies:

1. Traditional (E 00:00:30-00:02:30): RSI 14 above 50 = bullish, take buys only; below 50 = sells only; overbought is
   confirmed only when RSI comes back below 70 (oversold when back above 30). He says not to trade on this alone.
2. Divergence + price trendline break (E 00:03:00-00:05:30): on a bullish divergence draw a trendline and buy on the
   candle after the breakout; stop below the breakout candle; target when RSI crosses 70 and turns back down.
3. RSI trendline break (E 00:06:00-00:08:30): a trendline drawn on RSI breaks, and price breaks its own trendline too;
   enter on the next candle; stop beyond the breakout candle (or the nearby biggest candle); target RSI back from 70
   (30 for shorts).
   Strategies 2 and 3 depend on hand-drawn trendlines: not implemented.
4. RSI 50 + EMA 14 (E 00:09:00-00:11:30): add an EMA with length 14 (to match RSI 14). Buy when price crosses above
   the EMA and RSI is above 50 (both required); enter on the candle after the cross candle; stop below the cross
   candle (or the nearest low if that is not too far). Short: RSI below 50 and price crosses below the EMA; stop above
   the cross candle; target: hold until RSI has gone below 30 and starts rising again.
- A for strategy 4: "price crosses the EMA" = a close above EMA 14 after a close below it; the long target mirrors
  the short one (hold until RSI has gone above 70 and turns back below it); exit at the next open after that; stop =
  the cross candle's low (high); out at the session's end; 5-minute candles (intraday choice 5/10/15 minutes from
  icml_txwHdY 00:11:30); market NIFTY.

icml_txwHdY (RSI "you are using it wrong", 25 Nov 2023, 14 min): RSI levels, the cross-back reading of 70/30, double
bottoms/tops on RSI below 30 / above 70, divergence that must be confirmed by a candlestick pattern (hammer), and
weekly/monthly RSI momentum reading. No stop or target: theory, not implemented. It supports NJ-08's reading of
70/30 (a level only counts when RSI crosses back).

## NJ-09 MACD signal-line cross (zJ3FCKcin_k, 1 Dec 2023, 19 min)

Market: shares/options, intraday on 5-minute candles (E 00:14:00-00:14:30: intraday no more than 5/10/15 minutes; the
trade example is on 5-minute, E 00:17:30). Digest read (rule parts in full).

- Readings (E 00:05:00-00:13:30): histogram above zero = bullish momentum; MACD/signal cross; both lines crossing the
  zero line; divergence (confirm with a candlestick pattern).
- Trade (E 00:15:30-00:18:30): when the MACD line crosses above the signal line, buy on the next candle; stop a little
  below the lowest candle nearby (on 5-minute; on long timeframes use the nearest candle instead when the lowest one
  makes the stop too big, about 2%). Target: a trailing stop, or hold until a bearish divergence appears. Shorts are
  the mirror (stop above the highest nearby candle; hold until a bullish divergence).
- A: MACD 12/26/9 (default); stop = the lowest low (highest high) of the last 5 candles; the divergence exit is
  replaced by the opposite MACD cross (exit at the next open); out at the session's end; market NIFTY 5-minute.

pMFP4UuFmjI (moving-average masterclass, 3 Nov 2023, 19 min): trend from price vs a moving average, a cross of it as a
reversal, moving averages as support/resistance (fit the length to the chart), golden/death cross of 20 and 50 (not
to be traded alone). Theory: no strategy.

## NJ-10 Heikin Ashi doji turn (bA4GYgh13fk, 28 Jun 2024, 16 min)

Market: index/shares; examples on the NIFTY daily chart, timeframe for trading not stated. Digest read (rule parts in
full).

- Candle types (E 00:06:00-00:09:30): strong bullish = green Heikin Ashi candle with no lower wick; strong bearish =
  red with no upper wick; small-bodied candles with wicks on both sides = indecision (doji).
- Entry (E 00:12:00-00:12:30, 00:14:30): in a falling market a green indecision doji forms, then two strong green
  candles: buy (on the candle after the doji's follow-through, i.e. after the second strong candle). Stop: a little
  below the doji. Target: a trailing stop. Check that the stop is not too big for the reward (E 00:15:00).
- Shorts: the mirror (implied by the four candle types; not shown in the rule part). A: mirrored.
- A: 15-minute NIFTY; "falling market" = the three Heikin Ashi candles before the doji are red; doji = body at most a
  third of its range with both wicks present; strong = no wick on the opposite side; enter at the open after the
  second strong candle; stop = the doji's low; trail: exit at the next open after the first opposite-colour Heikin
  Ashi candle; out at the session's end.

## NJ-11 Renko pullback patterns (Vg6H5dlwzrs, 14 Aug 2024, 21 min)

Market: index/shares; daily chart in the theory part, intraday shown with an ATR brick size on 5-minute (E
00:19:00-00:19:30: 1-min 26 points, 5-min 130, 15-min 74 points on his symbol, i.e. the brick size comes from ATR on the
chosen timeframe). Digest read.

- Bricks only form on price movement of the brick size (E 00:02:30-00:03:30).
- Range break (E 00:12:30-00:13:30): after a top, a pullback and a return to the same high, buy when that high breaks;
  stop a little below the red brick before it.
- 1-back (E 00:14:00-00:15:00): in an uptrend one red brick, then a green brick: draw a line at it and buy when the
  next brick goes above; stop below the red brick. 1-back bearish: the mirror (stop above the green brick).
- 2-back (E 00:15:00-00:16:30): the uptrend needs at least three bricks; then two red bricks; when green bricks return
  and the high breaks, buy on the next brick; stop below the red bricks. Mirror for shorts.
- Zig-zag (E 00:16:30-00:18:30): red, green, red, green, then a fifth green brick: buy, stop below the first and third
  bricks; bearish mirror. Rare.
- Target: not given.
- A: one strategy that takes the 1-back and 2-back continuation (the frequent patterns): bricks from 1-minute closes
  with a brick size fixed for the day at ATR 14 of the previous session's 5-minute bars (NIFTY); trend = at least 3
  bricks one way; 1 or 2 opposite bricks; enter when a new brick in the trend direction closes beyond the last trend
  brick; stop beyond the opposite bricks; exit at 2R or when one opposite brick forms after entry (the 2026 video's
  exit, below), or at the session's end.
- td3gb3cZ_Qc (Renko masterclass, 21 Aug 2026, 22 min) repeats the same patterns (1-back, 2-back, zig-zag) and gives
  the exit (E 00:09:30, 00:11:00, 00:14:00, 00:18:00): a 1:2 target, or hold until one brick prints the other way.
  Stop: below the pullback with a small margin (E 00:09:00). Brick size from ATR; a small timeframe for intraday (E
  00:21:00). It confirms NJ-11; no separate strategy.

## NJ-12 PVT cross of its EMA 20 (5h7_96ioFWY, 10 Aug 2024, 14 min)

Market: shares (swing on daily, intraday on 5-minute) and BANKNIFTY futures (the index itself has no volume, E
00:11:30-00:12:00). Digest read (rule parts in full).

- Indicator (E 00:00:30-00:05:00): Price Volume Trend; add an EMA of length 20 with the PVT as its source.
- Rules (E 00:05:00-00:06:00, 00:09:00-00:09:30): PVT crossing above its EMA = buy; crossing below = sell/short. A
  position is closed by the opposite cross (always in the market on the swing chart).
- Entry on the cross candle or the next one (E 00:07:30). No stop is given.
- A: intraday on the desk's NSE 5-minute stock pool; enter at the next open after the cross; exit at the next open
  after the opposite cross (no reversal into the other side within the same trade; the opposite cross can open a new
  trade); a protective stop 1.5 x ATR 14 from the entry because the desk needs a stop to size the trade; at most 3
  trades per stock per day; out at the session's end.

## NJ-13 Hammer after a fall, with volume (QGXmyjwJ1aE, 22 Aug 2021, 9 min; IRBrPbPrKME, 19 Jan 2024, 13 min)

Market: shares (his 15-minute hammer screener) and BANKNIFTY; 15- or 5-minute candles, keep to the timeframe the
pattern formed on (E QGX 00:04:00-00:04:30). Both read in full (digest).

- Hammer (E QGX 00:01:00-00:03:30): long lower wick, small body, no upper wick (a small upper wick is acceptable,
  but no wick is better); colour does not matter. Meaning: sellers pushed price down, then extreme buying.
- Where (E QGX 00:02:30-00:03:00): after the price has been falling.
- Entry and stop (E QGX 00:05:30-00:06:00): buy once the hammer candle has closed; stop at the low of the hammer's
  wick. Support/resistance improves results (not quantified). No target given.
- Volume (E IRB 00:05:30-00:10:30): volume above its moving average confirms a move; a move on below-average
  volume is weak. IRB 00:11:00-00:12:00: a hammer (bullish pattern) with volume rising = take the buy.
- A: hammer = lower wick at least 2 x the body, upper wick at most 25% of the candle's range, body at least 5% of the
  range; "after a fall" = the hammer's low is the lowest low of the last 10 candles; volume above its 20-candle
  average; enter at the next open; stop at the hammer's low; target 2R (not given); out at the session's end; one
  trade per stock per day; long only (the video only teaches the bullish hammer). Universe: the desk's NSE
  15-minute stock pool.

## NJ-14 Supertrend 21/1 + RSI 50 (2jF09vG3HD4, 26 Feb 2023, 23 min: hollow candles)

Market: shares, intraday on 5-minute (E 00:15:00-00:16:00). Read the trading part in full (00:14:00-00:21:30).

- Chart (E 00:00:00-00:12:00): hollow candles (filled/hollow from open vs close, colour from close vs the previous
  close). They are the chart type; the rules below do not use their colours.
- Supertrend (E 00:14:00-00:15:00): the default 10/3 gives many false signals; use ATR length 21, factor 1.
- RSI (E 00:16:30-00:18:00): RSI 14 with its moving average (the two lines). Look for buys only while both lines are
  below 50, sells only while both are above 50.
- Entry (E 00:18:30-00:20:00): buy when Supertrend gives a buy signal and both RSI lines are below 50; sell when
  Supertrend gives a sell signal and both lines are above 50.
- Exit (E 00:20:00-00:21:00): when Supertrend flips to the other signal, or both RSI lines cross to the other side of
  50 ("if any of your conditions fails, take the target").
- Stop (E 00:21:00): as much as you can risk, or about 2% per trade for stock intraday.
- A: RSI's moving average is a 14-period SMA (TradingView's RSI default); enter at the next open after the flip; stop
  2% from the entry; exit at the next open after either exit condition; out at the session's end; up to 3 trades per
  stock per day. Universe: the desk's NSE 5-minute stock pool.

## NJ-15 Three-touch level breakout with volume (E4Q4vgRCpok, 18 Mar 2024, 11 min)

Market: options/intraday, any chart; shown on 1-minute index charts (E 00:09:30), volume from futures for indices
(E 00:07:30-00:08:00). Digest read.

- Three-touch resistance (E 00:01:30-00:02:30): buy when price breaks out upward after touching the same resistance
  at least three times (three is the minimum). Three-touch support (E 00:02:30-00:03:00): short on the break down
  after at least three touches. A range touched at least three times on both sides works the same way (E 00:05:00).
- Volume (E 00:07:00-00:07:30): a breakout with volume above its moving average is a genuine one; use volume with
  these strategies.
- Hacks (E 00:09:00-00:09:30): wait for the breakout candle to close beyond the level before entering; a retest of
  the broken level that holds is an even stronger signal; check several timeframes.
- Stop and target: not given.
- A: a level = at least 3 swing highs (lows) within 0.25 x ATR 14 of each other in the session so far, the first at
  least 6 candles before the break (5-candle fractal swings, confirmed with no look-ahead); a 5-minute close beyond
  the highest (lowest) touch with volume above its 20-candle average; enter at the next open; stop beyond the
  breakout candle's other end; target 2R; out at the session's end; one trade per stock per day. Universe: the
  desk's NSE 5-minute stock pool.

jWyAH_hs68A (fake breakout masterclass, 15 May 2024, 14 min): ways to avoid false breakouts: check several timeframes
(15 > 5 > 3 > 1 minute), skip breakouts made by one big candle (the stop is too large), wait 2-3 candles and enter on
a break of the recent high, and for trendline breaks wait for price beyond the 0.382 Fibonacci level of the last
swing. Filters, not a stand-alone strategy; NJ-15 already waits for the close and uses volume.

## NJ-16 Double bottom / double top neckline break (OzIt1SEisBY, 17 Nov 2021, 10 min)

Market: BANKNIFTY options (calls on W, puts on M), any timeframe (E 00:02:30-00:03:00). Read in full (digest).

- W (E 00:00:30-00:02:30): in a down trend price takes support, rises to a resistance (the neckline), falls back to
  about the same support and rises again: two bottoms.
- Entry (E 00:03:00-00:04:00): draw the support line under the two bottoms and the neckline at the resistance; when
  a candle closes above the neckline, enter on the next candle. Stop: the low of the candle that closed above the
  neckline. Target: the support-to-neckline distance added above (example E 00:05:30: entry 39,430, stop 39,380,
  neckline 39,385, support 39,315, target 39,500).
- M (E 00:06:00-00:08:00): the mirror; puts / short.
- A: 5-minute BANKNIFTY; bottoms = two confirmed 5-candle fractal lows within 0.25 x ATR 14 of each other, at least 5
  candles apart, after a lower prior trend (the first bottom is the lowest low of the 20 candles before it); neckline
  = the highest high between them; the close above it must come within 20 candles of the second bottom; target = the
  neckline plus the pattern height measured from the entry fill's neckline (as in his example); out at the session's
  end.

## NJ-17 Gap open, first 15-minute close limit order (5G7l_rDrnlo, 23 May 2021, 13 min: "The Day Sniper")

Market: shares, 15-minute candles (5 or 10 allowed, 15 recommended, E 00:09:00-00:09:30); options did not work well
for him (E 00:09:00). Read in full (digest plus the end).

- Stock (E 00:00:30-00:02:30): one that opened gap-up (a visible space between the previous day's last candle and
  today's first candle; his example closes 321.50, opens 325.95).
- Wait (E 00:02:30-00:03:30): do not buy during the first 15-minute candle; after it closes (09:30) place a limit buy
  at its closing price; it must fill within the next 15 minutes, otherwise skip the stock that day (E 00:09:30-
  00:10:00).
- Stop (E 00:04:30-00:05:00, 00:08:00): just below the first candle's low (50 paise below in his example).
- Exit: no target; his example shows the day's high three hours later and the close (E 00:06:00-00:07:00).
- Gap-down (E 00:10:00-00:11:00): the mirror: limit sell at the first 15-minute candle's close; stop at its high.
- Note: he says the limit order fills only if the next candle is positive (E 00:04:00-00:04:30). A limit buy fills
  when price trades down to it, not up; the testable form keeps the order he tells viewers to place (the limit).
- A: gap-up = the first candle's low above the previous close (gap-down: its high below the previous close); limit
  order at the first candle's close, valid 09:30-09:45; stop 0.05% beyond the first candle's low (high); exit at the
  session's end; one trade per stock per day. Universe: the desk's NSE 15-minute stock pool.

## NJ-18 Gap open, first 15-minute range breakout (CdXPfxB08_o strategy 4, 28 Mar 2024; Br8-ipCt4mg, 20 Oct 2023)

Market: shares, 15-minute candles (E Br8 00:01:30, CdX 00:15:00). Both read (digest; CdX strategy part in full).

- Br8-ipCt4mg (2023, 8 min): gap-up stock: draw lines at the first 15-minute candle's high and low; buy when a candle
  closes above the high (E 00:04:00); stop at the first candle's low; no fixed target: hold until a candlestick
  pattern says price may fall (E 00:02:30); rising volume adds confirmation (E 00:03:00-00:03:30). Gap-down: short on
  a close below the low, stop at the high (E 00:05:00-00:05:30). One trade a day (E 00:07:30).
- CdXPfxB08_o strategy 4 (2024, the later version): after a gap-up open, mark the first 15-minute candle's high and
  low; enter on the candle that breaks the high; stop below the first candle's low; target 2 x the stop distance, or
  a trailing stop for a bigger move; volume above its average raises the odds (E 00:15:00-00:17:00). Gap-down: enter
  on the break of the low, stop above the first candle's high, target 2x or trail (E 00:17:00-00:18:30).
- A (the 2024 version): gap-up = today's open above the previous close by at least 0.3%, gap-down mirrored; a
  stop-entry at the first candle's high (low), valid until 14:30; stop at the first candle's other end; target 2R;
  out at the session's end; volume is not a hard filter (the video says it only raises the odds); one trade per stock
  per day. Universe: the desk's NSE 15-minute stock pool.

## NJ-19 EMA 50/200 cross with volume, daily (CdXPfxB08_o strategy 3, 28 Mar 2024)

- E 00:12:00-00:14:30: EMA 50 (green) and EMA 200 (red) plus volume. EMA 50 crossing above EMA 200 is a buy, crossing
  below a sell; confirm with rising volume (a cross on normal volume is riskier). Intraday it gives many false
  signals; use it on daily candles for swing trades.
- A: daily candles on the desk's NSE daily stock pool, long only (cash shares); volume on the cross day above its
  20-day average; enter at the next open; exit at the next open after the opposite cross; a protective stop 2 x ATR
  14 below the entry (none given; the desk needs one to size the trade).

CdXPfxB08_o strategy 1 (E 00:00:00-00:06:30) is NJ-01 again (VWAP + EMA 7, first 5-minute candle; here the targets are
2 x the stop, a trailing stop, or for shorts a close back above the EMA). Strategy 2 (E 00:06:30-00:12:00): a
sideways range on 5 or 15 minutes, enter on the candle after one closes beyond the range, stop beyond the breakout
candle (or beyond the range's other side when it was tight), target 2 x the stop, and only with volume clearly above
average; skip breakouts made by one very large candle. It supplies NJ-15's target (2R is stated here, not assumed)
and its volume rule.

## NJ-20 200-DMA cross candidates from the top 100 by turnover (aFwdDq1hFgo, 16 Jan 2023, 14 min)

Market: shares, intraday "for tomorrow". Read in full (digest plus end).

- Universe (E 00:00:30-00:03:00): the NSE bhavcopy; sort by total traded value and keep the top 100.
- Moving averages (E 00:07:00-00:08:30): 10, 30, 60, 90, 120 and 200-day.
- Buy list (E 00:08:30-00:10:00): price above the 10/30/60/90/120-day averages but still below the 200-day; buy when
  it crosses above the 200-day ("breakout"). Sell list: below the 10-120-day averages but above the 200-day; short
  when it crosses below the 200-day. The trigger price is the 200-day average (E 00:12:00, example: short Bharti below
  775.17).
- No stop or target is given.
- A: candidates fixed from the previous session's daily closes; a stop-entry at the 200-day average during 09:15-
  14:30; stop 0.5 x the daily ATR 14 beyond the trigger; target 2R; out at the session's end; one trade per stock per
  day. Needs 200 days of daily closes per stock: implement only if the desk's stock pool has the daily history.

iCtkq7jRnys (intraday crash course part 3, 13 Nov 2024, 20 min, guest Varun Shetty, Quants app): stocks are picked
from 20 days of futures open-interest build-up (at least 14 of the last 20 days long build-up or long unwinding =
bullish; short build-up or short covering = bearish), with option open-interest levels as pressure points; the
entry is left to the next video. Needs daily futures OI per stock and has no entry or exit: not implemented.

xEcoUrUUhWg (best shares for intraday, 19 Jan 2021, 12 min): stock-picking advice (high liquidity, large/mid caps,
avoid circuit-prone stocks, follow a few stocks or a sector, top gainers/losers, check global markets, always set a
stop and a target, book at the target). No strategy.

## NJ-21 EMA 5/20 cross scalp with a 10-minute time stop (YEswhH1-5Jo, 30 Mar 2024, 11 min)

Market: options/intraday/forex (any). Digest read (rule parts in full).

- Strategy 1 (E 00:03:00-00:04:30): EMA 5 and EMA 20 crossover: buy when EMA 5 crosses above EMA 20, sell when it
  crosses below; volume helps to avoid false signals; take small points, not the whole move (E 00:04:00).
- Strategy 2 (E 00:05:00-00:06:00): Parabolic SAR: dots below price = buy, above = sell; with volume near or above its
  average; take a little and re-enter while the trend lasts. (Pushkar Raj Thakur has a full PSAR video, VShXp7GA0js:
  handled there.)
- Exit discipline (E 00:09:30): if neither the target nor the stop is hit within about 10 minutes, exit ("10 minutes is
  my number, choose your own"). Big losses must not eat the small profits (E 00:07:30).
- A for strategy 1: NIFTY 1-minute; enter at the next open after the cross; stop = the lowest low (highest high) of
  the last 5 candles; target 1R (a scalp: small points); time stop 10 minutes; up to 6 trades a day, stopping after 3
  stops; no volume filter (the index has none).

## NJ-22 MACD + Stochastic 50 + Parabolic SAR scalp (Idw7qPqBWSA, 20 Feb 2023, 14 min)

Market: options (BANKNIFTY-sized moves: "181 points in 20 minutes"), 5-minute candles (1 or 3 also allowed, not 15:
E 00:01:00). Read the rule parts in full.

- MACD (E 00:02:00-00:03:00): MACD line crossing above its signal line = buy, below = sell; alone it gives many
  false signals.
- Stochastic (E 00:03:00-00:06:00): both lines above 50 = look only for buys; both below 50 = only sells.
- Parabolic SAR (E 00:07:30-00:08:00): dots below the candle = buy, above = sell.
- Entry (E 00:08:00-00:11:30): enter on the candle where all three agree (MACD crossed up, both Stochastic lines
  above 50, SAR dots below the candle); shorts mirror it.
- Exit (E 00:12:30-00:13:00): stay in while all three hold; exit as soon as any one fails (e.g. the MACD condition),
  or take your own target. Stop: as little as you can risk (a scalp), and it can be trailed.
- A: BANKNIFTY 5-minute; MACD 12/26/9, Stochastic 14/1/3, SAR 0.02/0.02/0.2 (defaults); the signal is the first
  closed candle where all three agree with the MACD cross within the last 3 candles; enter at the next open; stop at
  that candle's SAR value; exit at the next open after any condition fails; out at the session's end; up to 4 trades
  a day.

0rZcz6dGpOQ (cascade order, 14 Sep 2024, 13 min): position building, not an entry rule: buy one lot with a 1:2 plan;
at the target add another lot and raise every stop (e.g. 100 entry, stop 90, target 120: at 120 add a lot and move
both stops to 115; at 140 add a third and move all stops to 135). Money management on top of any entry: noted, not
implemented as its own strategy.

6E11fzL4_8A ("secret" RPT strategy, 12 Aug 2024, 11 min): risk per trade and position sizing (size = capital x risk%
/ stop distance; keep the stop where the strategy puts it, 2-5% risk per trade). Money management: no strategy.

## NJ-23 Harami with a confirmation candle (V5nm2aCtfN8, 4 Aug 2024, 25 min: "top 10 strategies")

The video is a compilation of his strategies (chapters): range breakout/breakdown (= NJ-15 / CdX strategy 2),
trendline breakout/breakdown with volume (hand-drawn: not implemented), Renko bullish/bearish (= NJ-11), double
bottom/top (= NJ-16, with the same pattern-height target), candlestick patterns (new, below), MACD (= NJ-09; adds that a
cross with growing histogram bars is strong, small bars weak), moving-average cross 20/50 with volume (lagging, not
to be traded alone), gap up/down (= NJ-17/18).

- Candlestick strategy (E 00:14:40-00:17:30): in a down trend a big red candle, then a small green candle whose body
  sits inside the red body (bullish harami); then a green candle that closes above the red candle: enter on that
  candle or, for more confirmation, the next one; stop below the red candle. Bearish mirror after an up trend (big
  green, small red inside it, then a red candle closing below it; stop above the green candle). No target given.
- A: NIFTY 5-minute; "big" = body at least 1.2 x the average body of the last 20 candles; "down trend" = the big
  candle closes below EMA 20; the confirming candle must come within 3 candles of the harami; enter at the next open
  after the confirming close; stop at the big candle's low (high); target 2R; out at the session's end.

## NJ-24 Triangle breakout (ogZR_2gZFxY, 21 Oct 2022, 24 min)

Market: shares (daily examples, e.g. "about 12% return"), calls/puts as the vehicle. Digest read (rule parts in full).

- Ascending triangle (E 00:07:30-00:12:30): in an up trend price makes a resistance R1, a support S1, comes back to
  about the same resistance (R2 at R1's level) and makes a higher support (S2 above S1). Draw the horizontal
  resistance through R1/R2 and the rising line through S1/S2. Buy on the candle after the one that breaks out above
  the resistance; stop below the breakout candle (its low); target = the resistance-to-first-support height, or a
  trailing stop (E 00:15:30, 00:18:30).
- Descending triangle (E 00:13:00-00:15:30): in a down trend, S1 and S2 at the same level and R2 below R1: short on
  the candle after a close below support; stop at the breakdown candle's high; same target rule (example: a 9%
  height, 12% achieved).
- Symmetrical triangle (E 00:16:00-00:19:00): lower highs and higher lows; trade the break in the direction of the
  prior trend; wait for a clean break if price hugs the line.
- A: daily candles on the desk's NSE daily stock pool, long only (ascending, and symmetrical in an up trend):
  pivots = 3-candle fractals confirmed with no look-ahead; R1 and R2 within 1.5% of each other, S2 at least 1% above
  S1, the pattern spanning 10-60 sessions; up trend = the close above SMA 50 at R1; a close above max(R1, R2) within
  15 sessions of R2; enter at the next open; stop = the breakout candle's low; target = the entry plus (R - S1);
  time stop 30 sessions.

b4LbA6DtiVk (expiry-day options, 13 Mar 2022, 16 min): option price = intrinsic + time value; time decay; OTM/ATM/ITM;
expiry-day buying is cheap and volatile, exit quickly; his live example bought a BANKNIFTY 34,700 put for 33. No rules:
not a strategy.

6xIJVG4CRjk ("PE + CE strategy", 11 Apr 2021, 11 min, 4.1M views): a long strangle: buy an OTM call and an OTM put of
the same index, same expiry, same lots and about the same money (E 00:02:30-00:03:00), several days before expiry
(premium decays fast on expiry day), only in a volatile market, carried forward (not intraday; E 00:05:00). Book the
side that multiplies when the market moves hard; hold the losing side in case the market comes back (E 00:07:00-
00:09:00). The strikes, timing and exit are discretionary and it needs option prices: recorded, not implemented.

NEIdghSvHOc (option selling for beginners, 18 Sep 2023, 18 min): option-selling basics and margin; buying a far OTM
option of the same type before selling cuts the margin (e.g. 1.13 lakh to 42,400 or 24,000), i.e. a credit spread for
low capital. The direction is the trader's view: no entry or exit rule, not implemented.

## NJ-25 BTST momentum basket, buy the last half hour, sell the next open (IKuQYg0jcO0, 24 Apr 2024, 22 min)

Read the rule parts in full.

- Idea (E 00:00:00-00:02:00): the biggest moves come before the open; intraday traders' exits put selling pressure on
  stocks at 15:00-15:15, and their buying lifts prices at the next open.
- Options version (E 00:02:30-00:14:30): buy both an ATM call and an ATM put of equal value between 15:00 and 15:30
  and sell both at 09:15-09:30 next day; it profits from a big gap either way and loses (theta) when the open is
  flat. Needs option prices: recorded, not implemented.
- Stock version (E 00:15:00-00:21:00): pick 5-6 stocks with strong momentum (prices moving a lot, in an up trend),
  high volume, large or mid caps, each from a different sector; buy equal amounts between 15:00 and 15:30 every day
  and sell between 09:15 and 09:30 next day; replace a stock that stops trending (falls for several days) with a
  stronger one. Judge it over a long period, not one day.
- A: daily candles on the desk's NSE daily stock pool; each day pick the 5 liquid stocks with the highest 20-day
  return among those closing above their 50-day average, ranked on the previous session's close (the basket is set
  before the session, as his list is; ranking on the same close that fills the order would peek at it); the pool has
  no sector data, so the one-stock-per-sector rule is dropped; buy at the close, sell at the next open; equal money
  per stock; no stop (the hold is one night), and a protective 3 x daily ATR 14 distance is used only to size the
  trade.

## Swing notes

3w-fQPYWcIc (Mark Minervini swing strategy, 12 Sep 2024, 15 min): Minervini's SEPA ideas: up trend, improving
fundamentals, a catalyst, a low-risk entry, a planned exit; the VCP (volatility contraction pattern: each pullback
smaller, lower highs and higher lows) on daily/weekly charts; enter near the higher lows (the "cheat area") with the
stop just below the first support; small/mid caps and recent IPOs; never lose more than 8% on a trade. The pattern
details are left to a future course: not defined well enough to test objectively; not implemented.

## NJ-26 EMA 50 cross on Heikin Ashi with volume and RSI 50, swing (10SwCXmeTyE, 11 May 2024, 15 min)

Market: shares, swing; 4-hour candles (or daily; nothing lower, nothing as high as weekly: E 00:00:00-00:00:30).
Read the rule parts in full (digest).

- Chart (E 00:00:30): Heikin Ashi candles to see the trend; EMA 50 (E 00:01:00).
- Long (E 00:03:00-00:04:30): a green Heikin Ashi candle crosses above EMA 50; volume above its moving average; RSI
  above 50. Draw a line at that candle's close; when it is broken, buy on the next candle (E 00:04:30-00:05:00).
- Stop (E 00:05:00, 00:10:30): a little below the candle that crossed EMA 50, or below a nearby swing low.
- Exit (E 00:05:30-00:06:30): hide EMA 50 and add EMA 20; the target is reached when a candle closes below EMA 20, or
  when RSI falls below 50. Examples: 10% in 35 days, 20% in 45 days.
- Short (E 00:11:00-00:13:00): mirror (close below EMA 50, volume above average, RSI below 50; exit on a close above
  EMA 20); in swing trading mostly longs.
- A: daily candles on the desk's NSE daily stock pool, long only; the indicators are computed on the Heikin Ashi
  series (as TradingView does on a Heikin Ashi chart); RSI 14; volume above its 20-day average; a stop-entry at the
  cross candle's Heikin Ashi close, valid 3 sessions; stop at the cross candle's real low; exit at the next open after
  a Heikin Ashi close below EMA 20 or RSI below 50.

## NJ-27 20-candle channel breakout with EMA 200, ATR stops, crypto (sUcvpDSsQz0, 21 Oct 2026, 17 min)

Market: bitcoin and ether on Delta Exchange (fees 0.05% included in his test), 4-hour candles, about 5 trades a
month, backtested 5 years (E 00:00:30-00:03:00). Read in full. The description links his Pine Script (public Google
Doc 1xjLs3vcGU4ok3fnAA5FslJPca76r5keMcS1TvWCdw3Y); the rules below are taken from that code where the video is
looser.

- Channel (E 00:03:00-00:04:00; code): the highest high and lowest low of the previous 20 completed 4-hour candles
  (the current candle excluded).
- Trend (E 00:08:30, 00:09:30; code): longs only when the close is above EMA 200, shorts only below it.
- Entry (E 00:05:30-00:06:00; code): a 4-hour candle closes above the 20-candle high (below the 20-candle low for
  shorts); enter at the next candle's open.
- Initial stop (E 00:06:00-00:07:00; code): 2.5 x ATR 14 from the entry (the code's ATR is a simple average of true
  range).
- Trail (E 00:07:00-00:07:30, 00:09:30; code): no fixed target; a trailing stop 3 x ATR behind the best price,
  updated after each completed candle and applied from the next one; the video also describes moving to breakeven at
  1:1, which the code replaces with the ATR trail.
- Exit channel (code): a close below the lowest low of the previous 10 candles (above the highest high for shorts)
  closes the trade.
- Sizing (code): 3% of the balance at risk per trade, compounding.
- Desk form: BTCUSD on Delta (the desk has no ether account), 4-hour candles built from its minute bars (UTC 4-hour
  boundaries, as TradingView); exit-channel closes fill at the next open; risk per the desk's account rules.

mOSuaJONpXI (Fibonacci retracement full course, 25 Aug 2025, 18 min): draw swing low to swing high (the outermost
swing); pullbacks tend to stop at 38.2%, 50% or most often 61.8%; a close beyond 61.8% means the trend has changed;
buy near 61.8% with the stop a little below (ETH, 1-hour). No target: folded into NJ-28, which is the 2026 version.

## NJ-28 Fibonacci OTE: 0.618 tap with an FVG, 1:2 (TQYEWBhMQM0, 3 Sep 2026, 23 min)

Market: crypto (bitcoin-sized stops: "2,000 points"), analysis on 1-hour, entries on 5 or 15 minutes (E 00:13:00).
Digest read (rule parts in full).

- Levels (E 00:08:00-00:09:30): draw the retracement over the last swing; 0.5, 0.618 and 0.786 are the levels (the
  smart-money "optimal trade entry"); premium above 0.5, discount below (E 00:17:00-00:18:30): buy only in discount,
  sell only in premium.
- Entry (E 00:08:00, 00:12:00, 00:15:00, 00:20:00): wait for price to reach 0.618; a larger-than-normal candle that
  leaves a fair value gap there is the confirmation; when price taps that FVG again, enter.
- Stop (E 00:08:00, 00:13:30, 00:15:00, 00:20:00): above 0.786 for shorts (below 0.786 for longs on 15-minute; a
  break of 0.786 means the trend has turned).
- Target (E 00:12:00, 00:15:30, 00:20:00): 1:2; or the Fibonacci "standard deviation" levels 0, -0.5, -1, -1.5
  (E 00:21:30-00:22:30).
- Overlap: CP-25 (crypto playlist) is ICT OTE 0.705-0.79 with different entry and stop rules; NJ-28 keeps Neeraj
  Joshi's own version.
- A: BTCUSD; swings = 1-hour 5-candle fractals (the last confirmed swing low and high); up leg (high after low) gives
  longs, down leg gives shorts; a 15-minute candle with a body at least 1.5 x the average of the last 20 bodies that
  leaves a bullish (bearish) FVG while its range touches 0.618-0.786; enter on a limit at the FVG's near edge, valid
  12 candles; stop just beyond 0.786 (0.25 x ATR 14 margin); target 2R; one open trade at a time.

## ICT / smart-money videos

The crypto-playlist study (CP-13 order block on a 5-minute FVG, CP-17 FVG third touch, CP-18 order block 50%, CP-20
inverse FVG, CP-21 breaker, CP-22 CISD after a sweep) already covers these ideas from another channel. Neeraj
Joshi's versions use different entries, stops and targets, so two of his are kept as his own strategies.

## NJ-29 Order block retest with a 5-minute CISD, 1:2 (NBN3iZOK6Ow, 27 Aug 2026, 26 min; Qu9_ugsG6Z8, 14 Jul 2025;
hkqw42lxGLg, 13 Sep 2025)

Market: crypto first (Delta links), "works on every timeframe". Digests read; NBN3's strategy part in full.

- Order block (Qu9 00:00:30-00:03:00; NBN3 00:08:00): after a correction, a big momentum candle (only big money can
  make it); the last opposite-colour candle before that impulsive move, from its high to its low, is the order
  block. It is valid when the move leaves a fair value gap (Qu9 00:03:00).
- Simple use (Qu9 00:04:00; NBN3 00:09:00-00:11:00): when price returns to the block, enter; stop a little beyond
  the block; target 1:2 (NBN3). A block that price closes through becomes a breaker block for the other side (NBN3
  00:17:00-00:20:00).
- Strategy (NBN3 00:20:30-00:25:00): mark the order block on a higher timeframe (1-hour shown); when price comes back
  to it, do not enter at once: go to 5 minutes and wait for a CISD: draw a line at the close of the last opposite
  candle before the latest 5-minute impulse; a candle closing beyond that line confirms; enter when price retests
  the line; stop a little beyond the swing (or the block); target 1:2, or the next swing for more (book early if the
  move stalls).
- hkqw42lxGLg adds the multi-timeframe frame: support/resistance and blocks/FVGs on 4 hours, entries on 15 minutes,
  targets at the next 4-hour level (1:8 in his best example).
- A: BTCUSD; order blocks on 1-hour candles (the last opposite candle before two same-direction candles whose
  combined body is at least 2 x ATR 14, with a 3-candle FVG inside the move); a block is live for 5 days or until a
  close beyond its far side; when a 5-minute candle trades into a live block, look for a CISD within the next 36
  five-minute candles (a close beyond the close of the last opposite candle before the latest 2-candle impulse
  against the move, the line he draws at E 00:20:30); enter on a limit at the CISD line, valid 12 candles; stop beyond the block's far side with a
  0.1 x 1-hour ATR margin; target 2R; one trade at a time.

## NJ-30 Fair value gap 50% limit entry (UTO6e69GGSM, 24 Jul 2025, 20 min; 1F2qE6yabfM, ICT course ep. 4, 23 Jun 2026)

- FVG (UTO 00:00:30-00:03:00; 1F2 00:02:00): three candles, the middle one larger than normal; the gap between the
  first candle's high and the third candle's low (bullish), or the first's low and the third's high (bearish).
  Without a gap there is no FVG (UTO 00:12:00).
- Entry (UTO 00:06:30, 00:10:00-00:12:30): when price returns into the gap, buy with a limit order at (just below)
  its 50% line; stop a little beyond the far edge; target the recent swing high (1:3-1:4 in his examples; skip if it
  only gives 1:1, UTO 00:11:00).
- Inverse FVG (UTO 00:13:00+; 1F2 00:04:00-00:05:00): a gap that price closes through flips to the other side.
- CISD (1F2 00:06:00-00:07:30): line at the close of the last opposite candle before an impulse; a close beyond it
  confirms; enter on the retest; 1:2. (Used in NJ-29.)
- A: BTCUSD 15-minute; middle candle body at least 1.5 x the average of the last 20 bodies; gap at least 0.2 x ATR
  14; limit at the gap's 50%, valid 24 candles; stop beyond the far edge plus 0.1 x ATR; target the latest confirmed
  15-minute fractal high (low) beyond the entry; skip the gap when that target is less than 1.5R away (his 1:1
  rule), and use 2R when no such swing exists.

## NJ-31 4-hour swing sweep + 5-minute engulfing, 1:2 (WLR6S3mgOkk, 31 Aug 2026, 22 min: "I tested 10,000 sweeps")

Market: bitcoin (78,000 levels), 5-minute candles, his 5-year backtest (397,300 bars) at 1:2 and 1% risk. Read the
results and the strategy part in full.

- His test (E 00:00:30-00:07:00): four entries after a sweep: engulfing; FVG then tap; FVG without waiting for the
  tap (loses at every R:R and risk); inverse FVG (36.7% win rate, +84.7% in 5 years). The engulfing entry was the best
  (about +70% after 200 trades while the others were negative, E 00:20:00), and better still with wick-only sweeps
  (E 00:20:30-00:21:00). 1:2 beat 1:3 and 1:4.
- Levels (E 00:09:00-00:10:30): mark the 4-hour highs and lows (Williams fractals on 4 hours); the nearer one matters.
- Sweep (E 00:12:00): on 5 minutes price trades below the 4-hour low and comes back above it (stops of the earlier
  buyers are hit).
- Entry (E 00:12:00-00:13:30): after the low is swept wait for a bullish engulfing candle (opens at/below the prior
  red candle's close, closes above its open; the red body fits inside the green body); enter on the next candle.
  Stop below the sweep; target 1:2. Highs mirror it with a bearish engulfing.
- A: BTCUSD; 4-hour 5-candle fractals, confirmed (two 4-hour candles after the pivot); a sweep = a 5-minute low below
  the level with the close back above it (wick sweep); the engulfing must come within 6 five-minute candles of the
  sweep; enter at the next open; stop 0.1 x 5-minute ATR 14 below the lowest low since the sweep; target 2R; a level
  is used once.

## NJ-32 Candle range theory on 1 hour, target 2 x the range (LrILW6JRNq8, 8 Jul 2025, 16 min)

Market: "crypto, stocks, options, forex"; 1-hour minimum, bigger is better (E 00:00:30-00:01:00). Digest read (rule
parts in full).

- Trend (E 00:00:30): buys only in an up trend, sells only in a down trend; no trades sideways.
- Range (E 00:01:00, 00:04:00): in an up trend a big red candle forms: its high and low are the candle range.
- Sweep (E 00:02:00-00:02:30, 00:04:30-00:05:00): the next candle trades below the range low with a long wick and
  closes back above it (any colour).
- Entry (E 00:02:30-00:03:00): buy on the next candle; stop below the range low (or below the wick when it is short);
  target 2 x the range height (example: 400-point range, 300-point stop, 800-point target, E 00:10:30).
- If the next candle does not sweep, re-draw the range on the latest candle and wait again (E 00:07:00-00:09:00).
- Shorts mirror it in a down trend (big green candle, a sweep of its high, a close back below).
- CRT 2.0 (KrEpE3TP8xk, 6 Aug 2026, 14 min): the 2025 version "no longer works as well", so three changes (E
  00:04:00-00:05:00): the range candle's location matters more than its size (at a support zone for longs); a setup is
  invalid if, after the low is swept and price closes back inside, the high is also swept and closed back inside;
  the entry waits for a 5-minute FVG (or inverse FVG) after the sweep and enters on its retest (E 00:02:30, 00:06:30-
  00:07:00); stop below the sweep wick; target 1:2 (E 00:05:00).
- The desk keeps the 2026 version (the creator's update). A: BTCUSD; 1-hour trend = close above EMA 50 and EMA 50
  rising over 10 candles; the range candle is an opposite-colour candle whose low is within 0.5 x 1-hour ATR 14 of a
  confirmed 1-hour fractal low (support; mirrored for shorts); the next 1-hour candle sweeps the range low and closes
  back inside; within that and the next 1-hour candle, a 5-minute bullish FVG (middle body at least 1.5 x the average)
  gives a limit at its near edge, valid 12 five-minute candles; cancelled if the range high is swept and closed back
  inside first; stop 0.1 x 5-minute ATR below the sweep wick; target 2R.

VAZXz_ieec4 (daily bias, 7 Oct 2026, 20 min): three ways to pick the day's side: yesterday's close below the day
before's (bearish close) means look for sells, above means buys; a sweep of the previous day's low (high) that
closes back inside means a bullish (bearish) bias; on lower timeframes use the nearer levels. A filter for other
entries, not a strategy on its own.

## NJ-33 BTC/ETH SMT divergence, 5 minutes, 1:2 (oo_bmEgt6o8, 19 May 2026, 25 min)

Market: bitcoin and ether, 5-minute candles; his one-month backtest at 1:2: 119 trades, 44% wins on BTC, 57% on ETH
(E 00:00:30-00:02:30). Digest read (rule parts in full).

- SMT (E 00:04:00-00:07:30): BTC and ETH normally move together; when one makes a higher high and the other a lower
  high, buyers are weakening: sell; when one makes a lower low and the other a higher low, sellers are weakening:
  buy.
- Entry (E 00:14:00-00:14:30): once the SMT has formed, skip two candles (10 minutes; that is how his backtest did
  it), then enter.
- Stop (E 00:14:30): above the swing high that formed the divergence (below the swing low for buys).
- Target (E 00:15:00): 1:2, or the opposite swing.
- Overlap: CP-24 is an SMT strategy from the crypto playlist; this is Neeraj Joshi's own timing and stop.
- A: trades BTCUSD; swings = 5-minute 3-candle fractals on both coins at the same timestamps; the divergence compares
  the two latest swing highs (lows) of each coin within 36 candles; enter at the open of the third candle after the
  confirming candle; stop 0.1 x ATR beyond BTC's swing; target 2R; needs ETHUSD 5-minute candles from Delta's public
  feed as a second input.

rzxv2IyBuK8 (liquidity sweep explained, 22 Jun 2025, 19 min): why stops below support and above resistance are swept
(institutions need the other side for size). Theory; NJ-31 is his tested sweep entry.

## NJ-34 Hidden (breakeven) liquidity re-entry, 5 minutes (yaOGOlSBUOY, 25 Sep 2026, 14 min)

Market: crypto (Delta), 5-minute candles; examples run day by day from 1 September. Read the rule part in full.

- Logic (E 00:01:00-00:02:30): when a move starts from a candle (a red candle starting a down move), many traders
  enter on the next candle at that candle's close/low; once the move goes their way they move the stop to breakeven
  at that entry. Price comes back to that level to take those breakeven stops before continuing.
- Entry (E 00:02:30): place the entry at that level (where the others have their breakeven); stop a little above the
  swing high; target 1:2 (often 1:3 is available). It repeats at each new candle that starts the next leg (E
  00:03:00-00:04:30). Buys mirror it (E 00:06:30-00:07:00: after a low, the first green candle; followers enter on
  the next candle).
- A: BTCUSD 5-minute; the level L = the close of the first red candle after a confirmed 3-candle fractal swing high
  (the candle that starts the leg); the leg must then extend at least 1 x (swing high - L) beyond L within 12 candles
  (so the followers' stops have been moved to breakeven); then a limit sell at L, valid 24 candles; stop 0.1 x ATR
  above the swing high; target 2R; mirror for longs.

bV1OkS_-Pjg (liquidity scalping 2026, 28 Feb 2026, 13 min): swing high/low, wait for one side to be swept (broken
and closed back inside), confirm with a CISD-style line at the last opposite candle of the move, enter on its retest,
stop beyond the sweep, target the opposite swing. Same mechanics as NJ-29's CISD and NJ-31's sweep (and CP-22): no
separate strategy.

## NJ-35 Manipulation model at the New York open, 5 minutes (QBIsYw8iqPY, ICT course ep. 9, 11 Jul 2026, 24 min;
CYYRkXeoNkQ, ep. 8, 7 Jul 2026, 26 min)

Market: crypto (Delta), 5-minute candles. Digests read (rule parts in full).

- Power of three (ep. 9 E 00:01:00-00:06:30): accumulation (a range), manipulation (price runs one side to take the
  stops of both breakout traders and range traders), distribution (the real move the other way).
- Time (ep. 8 E 00:07:30-00:11:30; ep. 9 E 00:12:00): the kill zone in Indian time is about 17:30-21:30; the open is
  manipulated, so skip its first hour; ep. 9 watches the 9:00 New York hour, i.e. 18:30-19:30 IST.
- Entry (ep. 9 E 00:08:00, 00:12:30-00:14:00): in that hour wait for a liquidity sweep of a level; then draw the CISD
  line (close of the last opposite candle before the impulse away from the sweep); a close beyond it confirms; enter
  when price retests the line; stop a little beyond the manipulation high (low); target 1:2 or the opposite level.
- A: BTCUSD; the accumulation range = the high and low of 17:30-18:30 IST; a sweep = a 5-minute candle between 18:30
  and 19:30 IST trading beyond the range and closing back inside; then a CISD within 24 candles; enter on a limit at
  the CISD line, valid 12 candles; stop 0.1 x ATR beyond the sweep extreme; target 2R; one trade a day; out at 23:30
  IST.

lLoNbjzhMIU (10 ICT strategies in 15 minutes, 21 Jan 2026) and 8thmPwMx6NQ / XC6AL1mEZIQ (course wrap-ups) list the
same building blocks: silver bullet (15-minute high/low sweep then a CISD or FVG, 1:2, best in the London/New York
sessions), FVG, CISD, CRT, power of three, order blocks. Covered by NJ-29 to NJ-35 and CP-22 / CP-28 (silver bullet).

## Time-of-day crypto strategies (all three are 2026 videos with his own short backtests)

The Indian times he gives move by an hour with US daylight saving (he says so in n2eHieivtXw, E 00:05:00), so the
desk anchors them to New York or London time.

## NJ-36 The 5:30 PM two-hour range sweep (n2eHieivtXw, 25 Aug 2026, 10 min)

- His July 2026 test (E 00:00:00-00:02:00): 31 days, no entry on 12, 19 trades, 10 targets, 8 stops, 1 breakeven at
  1:2: +12R.
- Range (E 00:03:30-00:05:00): on the 2-hour chart mark the 17:30-19:30 IST candle (New York opens 17:30 IST; in
  winter use 18:30-20:30).
- Entry (E 00:05:30-00:07:30): after 19:30, on 5 minutes, wait for price to go above the range and a candle to close
  back inside (a sweep of the high) - short on the next candle; a sweep of the low that closes back inside - buy.
  Stop beyond the sweep; target 1:2; one trade a day.
- A: BTCUSD; range = 08:00-10:00 New York time; sweeps until 14:00 New York; enter at the next 5-minute open; stop
  0.1 x ATR beyond the sweep extreme; target 2R; out at 16:00 New York.

## NJ-37 The 7 PM fair value gap (BaF-joXcm3o, 15 Aug 2026, 11 min, live demo)

- Setup (E 00:01:00-00:02:00): at about 19:00 IST (the US stock market open, high volume) a larger-than-normal
  15-minute candle forms an FVG; mark it; when price returns into it, enter (short for a bearish FVG, buy for a
  bullish one). Stop above the swing high with a margin; target 1:2.
- Skip Saturdays and Sundays (the US market is shut, E 00:04:30).
- His test (E 00:05:00): 83 trades, 36 winners (43.37%) at 1:2.
- A: BTCUSD; the FVG's middle 15-minute candle starts between 09:15 and 10:00 New York time (19:00 IST in US summer)
  and its body is at least 1.5 x the average of the last 20; limit at the gap's near edge, valid until 14:30 New
  York; stop 0.1 x ATR beyond the FVG's first candle extreme (the swing); target 2R; weekdays only.

## NJ-38 Golden-hour 15-minute range breakout (t_y7c4xsBlM, 15 Jan 2026, 24 min)

- Golden hours (E 00:05:00-00:13:30): Asia is quiet (stops get hit); the best volume with the least manipulation is
  in 13:45-14:45 and 18:45-19:45 IST (January, i.e. US/UK winter).
- Rules (E 00:13:30-00:16:00): on 15 minutes mark the first candle of the session (13:30-13:45 IST); on 5 minutes, the
  first candle that closes above its high is a buy (below its low a sell); stop a little below the range low; target
  1:2 (1:3 often available; trail if wanted). His 13-day test is shown day by day (E 00:22:00).
- A: BTCUSD; two sessions a day: London (range 08:00-08:15 London time, signals until 09:15) and New York (range
  08:00-08:15 New York time, signals until 09:15); the first 5-minute close beyond the range; enter at the next open;
  stop 0.1 x ATR beyond the range's other side; target 2R; one trade per session.

## NJ-39 Long-wick rejection at a 1-hour support or resistance (eY9bWGZDN9c, 4 Aug 2025, 19 min, live BTC demo)

- E 00:02:30-00:06:30: breakouts of support/resistance often trap traders: a 1-hour candle drops through support
  (looks like a breakdown) but closes back above it with a long lower wick: sellers pushed, buyers came back.
- Entry (E 00:06:30-00:08:30): at support, a long-wick candle is a buy, not a short; enter on the next candle; stop a
  little below the wick's low; target the recent high (resistance). Shorts mirror it at resistance (E 00:10:30-
  00:11:00: long upper wick after a fake breakout; stop above the wick; target the recent low).
- A: BTCUSD 1-hour; support = a confirmed 5-candle fractal low from the last 100 candles; the signal candle trades
  below it and closes back above it, with a lower wick at least 2 x its body and at least half its range; enter at
  the next open; stop 0.1 x ATR below the wick; target the nearest confirmed fractal high above the entry, if it is
  at least 1.5R away (else 2R); time stop 48 candles.

fG5U4dsY1SA (crypto for beginners, 16 Sep 2025, 24 min) and DCtyfOCigdg (crypto strategies, 12 Mar 2025, 30 min):
platform, leverage and money management (risk 10% of capital per trade at most, 1:3 reward), daily trend plus a
1-hour entry with EMA 50 and his FVG method. No new rules.

-gem0ZcOhGE (crypto strategy, 19 Feb 2025, 22 min): levels from the daily chart, checked on 4 hours; buy at a support
touched several times, stop below the previous low (about 2%), first target the next resistance (3.38% in the SOL
example), 10x leverage. Hand-drawn levels: not implemented separately (NJ-39 is the objective form of buying a held
support).

## NJ-40 Ichimoku triple confirmation, 1 hour (JO_HVljXOYo, 25 Jan 2025, 19 min)

Market: crypto, 1-hour candles (E 00:05:30). Digest read (rule parts in full).

- Ichimoku (E 00:01:00-00:08:00): conversion line (blue), base line (maroon), the cloud projected 26 candles ahead.
- Buy (E 00:08:30-00:10:30): three confirmations: the conversion line crosses above the base line; price is above
  the cloud; the cloud 26 candles ahead is bullish (green). Enter on the candle after the cross.
- Stop (E 00:10:30): at the candle where the cross happened (A: its low).
- Exit (E 00:11:00): hold until the conversion line crosses back below the base line, or trail.
- Shorts (E 00:12:00+): the mirror.
- A: BTCUSD 1-hour; Ichimoku 9/26/52 (defaults); "above the cloud" = close above both spans plotted for that candle;
  "bullish future cloud" = span A above span B as computed on the signal candle; all three true on the cross candle
  (or within 2 candles after it); enter at the next open; stop at the cross candle's low (high), at least 0.5 x ATR
  away; exit at the next open after the opposite cross.

U2DGJtNS03M (free crypto course, 16 Jan 2025, 50 min): exchange basics, leverage, liquidation price, BTC options on
Delta; trend read from the daily and 4-hour charts (price above a moving average = buys only). No new rules.

qM8XpTKke8s (big moves = US news, 8 Aug 2026, 17 min): scheduled US releases (Fed rate decision 23:30 IST, CPI 18:00
IST, Fed chair speeches) cause the big candles in gold and bitcoin; read actual vs forecast (actual worse for the
dollar = good for BTC and gold). A calendar method without fixed entry rules: not implemented.

yeDdFfEVSKE (multi-timeframe entries, 17 Mar 2026, 11 min): direction on 1 hour, levels on 15 minutes (a line chart
helps), entry on 5 minutes with any strategy. A framework: no strategy.

## NJ-41 Richard Dennis zone breakout, 2 x ATR stop, 4 hours (SV5-LHF91Bw, 27 Nov 2025, 14 min)

Market: ether on 4-hour candles (instead of the daily chart Dennis used, E 00:05:00). Digest read (rule parts in
full).

- Zone (E 00:05:30): an important support/resistance zone is one price has reversed from at least twice.
- Entry (E 00:06:00-00:07:00): when an important zone breaks, trade the break (short below support, buy above
  resistance).
- Stop (E 00:04:00, 00:07:00): ATR with length 20; the stop is about 2 x ATR (80 x 2 = 160 points in his example).
- Target (E 00:07:00): at least 1:2.
- Principles (E 00:07:30-00:08:00 and on): cut losses quickly (a stop-out is part of the plan), then the rest of
  Dennis's rules (follow the rules, let the system work over many trades).
- A: BTCUSD 4-hour (the desk has no ether account); a zone = at least 2 confirmed 5-candle fractal highs (lows) within
  0.5 x ATR 20 of each other in the last 120 candles; a 4-hour close beyond the zone's outer touch; enter at the next
  open; stop 2 x ATR 20 from the entry; target 2R; one trade at a time.

LexC498CNGE (Larry Williams' strategy, 20 Nov 2025, 17 min): BTC 5-minute; a Donchian channel breakout after a flat
band, volume above its average, and the "LWTI" (Larry Williams Large Trade Index, a TradingView community indicator)
above +50 for longs / below -50 for shorts; stop beyond the channel's middle line or a swing; target the next swing
(about 1:2.3). The LWTI's formula is not given in the video, so the rule cannot be reproduced faithfully: not
implemented.

## NJ-42 EMA 200 + double-tested level + MACD cross, 15 minutes (pgiuaNZdAQw, 17 Nov 2025, 11 min: "30 days")

Market: crypto (his 30-day October 2025 test: 20,000 capital, 1,000 risk and 2,000 target per trade), 15-minute
candles (1-hour gives fewer, better trades, E 00:02:00). Read the rule parts in full.

- Trend (E 00:04:30-00:05:00): above EMA 200 only buys; below only shorts.
- Level (E 00:05:30): a level price has bounced from at least twice.
- Trigger (E 00:06:00-00:07:30; 00:09:00): a MACD cross (default settings): for buys a bullish cross below the zero
  line at the support; for shorts a bearish cross above the zero line at the resistance.
- Stop (E 00:07:30): a little below the recent swing low / the support; target the recent swing high (his test used a
  fixed 1:2).
- A: BTCUSD 15-minute; a level = at least 2 confirmed 5-candle fractal lows (highs) within 0.5 x ATR 14 of each other
  in the last 100 candles, with the cross candle's low within 1 x ATR of it; MACD 12/26/9; enter at the next open;
  stop 0.1 x ATR beyond the level or the latest swing, whichever is farther; target 2R (his test).

QBjhVcW0OJQ ("my favourite strategy for beginners", 8 Nov 2025, 11 min): 4-hour structure (break of structure =
trend continues; change of character = trend turned), then a 1-hour FVG entry in the trend direction. The FVG entry
is NJ-30; no separate strategy.

## NJ-43 Williams Alligator pullback to the teeth (VHUIE8sfHwk, 29 Sep 2025, 13 min)

Market: crypto-style charts (any). Digest read (rule parts in full).

- Indicator (E 00:01:00-00:02:30): three moving averages, 5, 8 and 13 (the Alligator); phases: sleeping (the three
  lines together: no trade, fake moves), awakening, feeding (the gaps widen: the move is on).
- Buy (E 00:06:30-00:07:30): the lines spread apart and price is above all three; when price comes back to the middle
  line, buy; stop at the third (slowest) line; target the recent swing high.
- Short (E 00:08:30-00:09:00): the mirror: all three lines above price, price comes back up to the middle line.
- A: BTCUSD 1-hour; TradingView's Williams Alligator (smoothed averages of the median price: jaw 13 shifted 8, teeth
  8 shifted 5, lips 5 shifted 3); "spread" = lips > teeth > jaw with lips - jaw at least 1 x ATR 14 (mirror for
  shorts); a limit buy at the teeth value when price trades down to it, valid while the order holds; stop 0.1 x ATR
  below the jaw at entry; target the latest confirmed 5-candle fractal high above the entry if at least 1.5R away,
  else 2R; time stop 48 candles.

Bj4ckno_O-w ("my strategy for 30 days", 22 Sep 2025, 10 min): a trade-by-trade replay of a Heikin Ashi trend +
pullback strategy from an earlier video at 1:3 with 500 risk on 2,000 capital; it does not restate the entry rules.
Not used as a source (the rules are in the earlier videos).

mnI8i_DLwSc (10 strategies that work every day, 18 Aug 2026, 19 min): FVG (higher-timeframe gap, lower-timeframe
entry, 1:2), CRT, CISD, liquidity sweep, order block, and similar smart-money set-ups: the same entries as NJ-29 to
NJ-35.

## Scalping videos

4iGdnVu_pwk (scalping masterclass, 22 Jul 2025, 18 min): a 5-minute FVG scalp after a big institutional candle, with
a tighter stop inside the gap; NJ-30's mechanics on 5 minutes. dMEZFnN9HrU (scalping masterclass 2026, 24 Dec 2025,
21 min): 1-hour levels, then a 5-minute CISD at the level, stop beyond the level, target the next swing: NJ-29/NJ-35's
mechanics. No separate strategies.

## NJ-44 4-hour fractal sweep, enter on the close back inside, 5 minutes (_kzobEWVgKE, 13 Aug 2026, 15 min)

- E 00:00:30-00:02:30: Williams fractals mark the 4-hour highs and lows; on 5 minutes wait for price to go above the
  4-hour high and a candle to close back below it (the sweep); short right after that close; stop a little above the
  sweep high; target 1:2. Lows mirror it (E 00:05:00). Use the nearer level; a far level matters less (E 00:06:00).
- This is the no-confirmation form of NJ-31 (his later 10,000-sweep test, 31 Aug 2026, found an engulfing
  confirmation better); both are kept, as two separate videos with separate rules.
- A: BTCUSD; confirmed 4-hour 5-candle fractals; the 5-minute candle that trades beyond the level and closes back
  inside; enter at the next open; stop 0.1 x ATR beyond the sweep extreme; target 2R; a level is used once.

## NJ-45 Two-candle turn level breakout, 4 trades a day (UeV17V0YldM, 27 Sep 2026, 11 min)

Market: crypto (BTC, ETH, gold on Delta), 15-minute chart ("15 minat kaa taaim phrem hai", E 00:05:00). Read the rule
parts in full.

- Short (E 00:00:30-00:02:00): a red candle, then a green candle that opens where the red one closed (a U-turn): that
  low becomes support; do not buy there; wait for a break below it, then short. Long (E 00:02:30-00:03:30): a green
  candle, then a red candle opening where the green closed: that top is resistance; buy the break above it.
- Conditions (E 00:01:30-00:02:00): trade only between 08:00 and 24:00 IST (not at 1-3 AM); the break must come within
  2-3 candles; avoid it after a very big move (manipulation), the market should be moving sideways near the level.
- Entry, stop, target (E 00:04:00-00:05:00): enter on the candle after the break (or with the breaking candle); stop a
  little beyond the breaking candle; target 1:2.
- A: BTCUSD 15-minute; "opens where it closed" = |open of the second candle - close of the first| at most 0.05 x ATR
  14; the break = a close beyond that level within the next 3 candles; enter at the next open; stop 0.1 x ATR beyond
  the breaking candle's other end; target 2R; skip when the 8 candles before the pair span more than 3 x ATR;
  signals 08:00-23:45 IST.

mERN3m0kDzg (5 strategies in 15 minutes, 30 May 2026): CRT on 1 hour with a 5-minute FVG or CISD entry and 1:2, and
the other smart-money set-ups already listed. Covered.

MOCbUrKWVtU (guest Pushkar Raj Thakur, 22 Feb 2026, 13 min): selling ATM BTC/ETH options on Delta for the month: the
option premiums imply a monthly range (ETH 2,000 straddle: about 1,700-2,300, 26-27% for ETH); profit if the price
stays inside the range at expiry. Option selling: needs option prices; recorded for the option-selling decision
(see the README), not a desk account here.

## NJ-46 EMA 10/20 cross with a Marubozu candle, Anant Ladha (zKgQwXt3z9o, 22 Dec 2025, 12 min)

Guest: Anant Ladha. Market: stocks on daily candles (indices also on 15 minutes or daily; crypto not tested by him,
E 00:06:00). Read the rule parts in full.

- Candle (E 00:01:30-00:02:00): a Marubozu = a strong full-bodied candle (one side won the whole session; small wicks
  are fine).
- Trend (E 00:04:30-00:05:00, 00:08:00): EMA 10 above EMA 20 = bullish "health", below = bearish.
- Trigger (E 00:05:00-00:05:30, 00:06:30): EMA 10 crosses above EMA 20 and a bullish Marubozu forms at the cross:
  that is the trigger (for shorts a bearish Marubozu at the cross down; short when its low breaks; stop around its
  high).
- Target (E 00:05:30): 1:3 is the normal reward (1:10 happened once). Retests of EMA 20 while the trend holds give
  re-entries (E 00:08:00). Win rate about 35%: it never misses a trend, stops come in sideways markets (E 00:08:00).
- A: the desk's NSE daily stock pool, long only; EMA 10 crosses above EMA 20 on the Marubozu day or one of the two
  days before; Marubozu = green body at least 70% of the range and the range at least 1 x ATR 14; a buy-stop at its
  high valid for the next 3 sessions; stop at its low; target 3R; exit also if EMA 10 crosses back below EMA 20 (next
  open); time stop 40 sessions.

bRCLewwFH4E (trendline masterclass, 30 May 2025, 16 min): drawing trendlines through lower highs / higher lows, the
break and the flip of resistance into support. Hand-drawn: not implemented. VrvNUyzBwXs (trendline 2026) repeats it.

la52ZjU-5nI (fixed range volume profile, 16 Aug 2025, 15 min): the point of control of a hand-picked range acts as
support/resistance. The range choice is discretionary: not implemented. 2QWI9nwHBvo (order flow full course, 3 Oct
2026, 26 min): footprint charts, delta, absorption (negative delta while price holds = a buyer absorbing): needs
footprint data; CP-14 already trades Delta order-flow absorption. ZnGTeEKownM (supply and demand with SMC, 20 Feb
2026, 24 min): break of structure, change of character, liquidity sweeps, supply/demand zones: covered by NJ-29 to
NJ-35.

## NJ-47 Smoothed Heikin Ashi retest, 1:3 (kUIfdwlKdaM, 10 Sep 2025, 13 min; tested in Bj4ckno_O-w, 22 Sep 2025)

Market: crypto (Delta), timeframe not stated. Read the rule parts in full.

- Indicator (E 00:01:00-00:01:30): "Smoothed Heikin Ashi" drawn over the real candles: green = up trend, red = down
  trend; shrinking candles warn the trend is weakening (E 00:04:30).
- Trend trade (E 00:06:30-00:08:30): in an up trend, when the real price comes back to the smoothed Heikin Ashi
  candles, buy on the next decent green candle (not a weak one); in a down trend, when price comes back up to them
  and a big red candle forms, short. Stop at the recent high (low); target the swing low (high); take only trades
  that give 1:3 or 1:4 (E 00:12:00).
- Reversal trade (E 00:08:30-00:11:00): after the colour flips and the new candles grow, the first retest of the
  smoothed candles is the entry.
- The 30-day test (Bj4ckno_O-w) used a fixed 1:3 (500 risk, 1,500 target).
- A: BTCUSD 1-hour; smoothed Heikin Ashi = EMA 10 of open/high/low/close, Heikin Ashi of those, then EMA 10 of the
  Heikin Ashi open and close (TradingView's common script defaults); trend = smoothed close above smoothed open for
  the last 3 candles; retest = a real low at or below the top of the smoothed body; signal = the next green candle
  with a body at least the 20-candle average, closing above the smoothed body; enter at the next open; stop 0.1 x ATR
  below the lowest low of the last 5 candles; target 3R; mirror for shorts.

## Index of Neeraj Joshi's strategies (desk market)

NIFTY index: NJ-04, NJ-08, NJ-09, NJ-10, NJ-11, NJ-21, NJ-23. BANKNIFTY: NJ-05, NJ-16, NJ-22. NIFTY + stock pool: NJ-02.
NSE 5-minute stock pool: NJ-01, NJ-07, NJ-12, NJ-14, NJ-15, NJ-20. NSE 15-minute stock pool: NJ-06, NJ-13, NJ-17,
NJ-18. NSE daily stock pool: NJ-19, NJ-24, NJ-25, NJ-26, NJ-46. NIFTY 5-minute: NJ-03 (A: index for the stock-or-option
example). BTCUSD (crypto tab): NJ-27 to NJ-45 and NJ-47 except the stock ones above; NJ-33 also reads ETHUSD.
