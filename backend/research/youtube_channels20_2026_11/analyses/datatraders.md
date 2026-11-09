# Data Trader (@DataTraders, UCwIsRM8qBXobpAnzVJ0c4IQ)

English; indicator strategies for crypto, forex and stocks, several "tested 100 times" backtests on TradingView
(taken as claims). Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## DT-01 MACD signal-line cross in the EMA 100 trend, swing stop, 1.5R: Yj0yEBxwLVw
"Most Effective MACD Strategy for Daytrading Crypto, Forex & Stocks" (2021-07-04, 9:49), https://youtu.be/Yj0yEBxwLVw
- MACD default (12, 26, 9); trend = price above / below the EMA 100 [E 03:28-04:30].
- Long: price above EMA 100 and the MACD line crosses above the signal line; short mirror [E 04:30-06:00].
- Stop: the nearest swing low (high); target 1.5x the stop [E 04:30-06:00].
- Advanced version: a hand-drawn 4-hour key level, entry on a MACD cross two timeframes lower [E 06:03-09:27] -
  discretionary level, not coded.
- Timeframe not stated for the beginner version [A: 1 hour]. Code [A]: BTC and XAUUSD 1-hour; swing = the lowest low
  (highest high) of the last 10 bars; target 1.5R; one position at a time; positions may run overnight.
- Status: ready with documented assumptions (timeframe, swing definition).

## DT-02 MACD cross + Parabolic SAR side + EMA 200, stop at the SAR dot, 1:1: sbKTRVWppZY
"70% Win Rate MACD + Parabolic SAR + 200 EMA Trading Strategy (Proven 100 Trades)" (2021-06-03, 10:07), https://youtu.be/sbKTRVWppZY
- Indicators default: MACD (12, 26, 9), Parabolic SAR (0.02, 0.02, 0.2), EMA 200; timeframe any, preferably 30 minutes
  [E description, 00:18-04:16].
- Long: price above EMA 200, MACD line crosses above the signal line while the SAR dots are below the candle; if the
  dots are still above at the cross, wait for them to flip below while the MACD stays crossed up [E 04:16-06:00]. Short mirror.
- Stop: at the SAR dot; target 1:1 [E 04:30-06:00]. Tip: cap the stop at 0.7 (no matter how far the dot is) [E 08:39-09:31].
- Their test (stated): EURUSD 30 minutes, 100 trades in 106 days, 69% winners, +51% at 2% risk [E 07:38].
- Code [A]: BTC and XAUUSD 30-minute; "0.7" read as 0.7% of price; the MACD line must still be above the signal line
  when the SAR flips (within 5 bars of the cross); 1R target; overnight allowed.
- Status: ready with documented assumptions (unit of the stop cap).

## DT-03 Stochastic both lines oversold -> RSI above 50 -> MACD cross up before stochastic overbought, 1.5R: hh3BKTFE1dc
"Most Effective Stochastic + RSI + MACD Trading Strategy (Proven 100x)" (2021-03-24, 10:22), https://youtu.be/hh3BKTFE1dc
- Settings: Stochastic 14 3 3, RSI 14 with a single 50 line, MACD 12 26 9; timeframe any, preferably 15 minutes - 1 hour
  [E description, 00:20-03:13].
- Buy: both %K and %D reach oversold; RSI above 50 (uptrend); then the MACD line crosses above the signal line while
  both stochastic lines have not yet reached overbought [E 03:13-04:39]. Sell mirror.
- Stop below the nearest swing low (above the swing high); target 1.5x the stop; cap the stop at 0.15%; one trade at a
  time [E 04:39-05:02, 08:35-09:56]. Their test: EURUSD 30 minutes, 100 trades, 56% winners, +28% at 2% risk [E 06:32].
- Code [A]: BTC and XAUUSD 30-minute; oversold < 20, overbought > 80; the MACD cross must come within 12 bars of the
  oversold touch; RSI > 50 at the cross; swing = last 10 bars' extreme; the 0.15% cap (an EURUSD number) is kept as a
  cap of 0.5% for BTC / 0.3% for gold [A, scaled by typical 30-minute range - documented]; 1.5R.
- Status: ready with documented assumptions.

## DT-04 Bitcoin daily Ichimoku cloud (lead lines, displacement 1), long only: 8blv0NdYeRc
"EASY Bitcoin Trading Strategy That BEATS Buy & Hold (WITH PROOF)" (2021-04-21, 9:25), https://youtu.be/8blv0NdYeRc
- Ichimoku with only Lead 1 / Lead 2 shown and displacement 1 (default 9/26/52 periods) [E 00:37-01:30].
- Long when a green daily candle closes above the cloud while Lead 1 is above Lead 2; exit when a red candle closes below
  Lead 1. Long only [E 01:30-03:58]. Their test: BTCUSDT daily 2017-2021, 37 trades, +2,087% vs buy-and-hold +1,019% [E 03:58-05:38].
- Code: BTC daily bars (UTC days) [A]; no stop (exit rule only); R unit = 5% of entry for reporting [A]; notional sizing
  at 100% of the book [A].
- Status: ready.

## DT-05 15-minute Chaikin Money Flow side + MACD cross, swing stop, 1.5R (the bonus in 8blv0NdYeRc)
- CMF above its zero line -> longs only (below -> shorts only); enter on a MACD signal-line cross in that direction;
  stop below the nearest swing low (above the high); target 1.5x [E 05:38-07:30]. CMF length default 20 [A].
- Code [A]: BTC 15-minute; swing = last 10 bars; 1.5R; out at the UTC day end.
- Status: ready with documented assumptions.

## DT-06 First New York 4-hour candle range: 5-minute close outside, then close back inside -> fade, stop at the breakout extreme, 2R: O5eC5lY7ZXY
"The BEST 5 Minute Scalping Strategy Ever (Simple and Proven)" (2025-08-29, 15:14), https://youtu.be/O5eC5lY7ZXY
- Step 1: the high and low of the day's first 4-hour candle in New York time (00:00-04:00 NY), marked only after it
  closes, extended to the day's end [E 00:37-02:17].
- Step 2: on 5 minutes, a candle closes outside the range (wicks do not count), then a candle closes back inside, the
  same day [E 02:17-03:16, 04:00].
- Step 3: fade it - back inside from above = short, from below = long; stop at the exact extreme of the breakout move;
  target 2x the stop; more trades the same day if new setups form [E 03:16-06:00]. If the breakout was very large, use
  the nearest key level / order block for the stop instead [E 06:00, 12:00].
- Their examples: BTC, forex, gold (10 gold trades: 6 wins, 4 losses, +8R) [E 05:08-14:25].
- Code [A]: BTC and XAUUSD 5-minute; New York day from 00:00 NY; "very large" = breakout extreme more than 1.0x the range
  width beyond the range -> setup skipped (the key-level stop is discretionary); entry at the next bar open; 2R; all
  setups until 16:00 NY, one position at a time; exit 16:55 NY (gold) / 23:55 UTC (BTC).
- Relation: a range-fakeout fade; the library's liquidity-sweep family trades NIFTY levels with other entries - kept.
- Status: ready with documented assumptions.

## DT-07 "SLC": 4-hour structure, fresh 5-minute supply/demand zone, stochastic hook confirmation, 2R: ExvoIqNglOk
"The BEST Day Trading Strategy For Beginners in 2026 (Simple and Proven)" (2026-03-26, 11:12), https://youtu.be/ExvoIqNglOk
- S: 4-hour structure - higher highs and higher lows = longs only; lower highs and lower lows = shorts only;
  consolidation = no trades [E 03:39-04:14].
- L: on 5 minutes, supply = the last candle before a sharp aggressive drop (demand mirror); trade only fresh (untested)
  zones, or a zone broken exactly once and retested from the other side [E 04:14-08:00].
- C: as price taps the zone, the stochastic's fast line crosses above the upper level and then back down (shorts) [E 08:42-10:00].
  The stochastic uses "custom settings" shown only on screen [E 08:42] - not in the transcript; frames not fetched.
- Stop slightly beyond the zone; target 2R [E 10:00]. Example market: Nasdaq futures [E 04:14].
- Code [A]: BTC and XAUUSD 5-minute; 4-hour structure = the last two confirmed 4-hour swing highs and lows (fractal n=2)
  both rising (falling); zone = the last opposite-colour 5-minute candle before a run of 3 candles that moves >= 2 ATR(14)
  within 3 bars; fresh = untouched since; stochastic 14 3 3 with 80/20 [A: the video's custom settings are unknown];
  confirmation = %K crosses back below 80 (above 20) while price is inside the zone; entry next bar open; stop = zone far
  edge + 0.1 ATR; 2R; the break-and-retest scenario is not coded.
- Status: ready with documented assumptions (stochastic settings unknown, zone definition).

## DT-08 "Manipulation": sweep of an obvious level, inverse FVG close, 2R: vK28i-qy8Ec
"The PERFECT SCALPING Strategy That Actually Works..." (2026-02-26, 12:48), https://youtu.be/vK28i-qy8Ec
- Step 1: an obvious liquidity level - a swing point price moved away from significantly, marked on 15 minutes to 4
  hours [E 02:06-03:40]. Step 2: manipulation - price breaks the level and quickly reverses [E 03:40].
- Step 3: an inverse fair value gap near the sweep - a FVG made by the move into the sweep that price then closes
  through the other way [E 03:40-05:53]. Step 4: enter at that close; stop slightly beyond the gap; target 2R (or the
  opposite liquidity) [E 05:53-06:21].
- Examples on Nasdaq futures 3-5 minutes and BTC; paid "ManipulationX" indicator automates it [E 06:21-10:00] - the
  manual rules are used here.
- Code [A]: BTC and XAUUSD 5-minute; levels = confirmed 15-minute swing points (fractal n=3) from the last 3 days that
  price moved >= 1.5 ATR(15m) away from; sweep = a 5-minute bar trades beyond the level and the sweep extreme is within
  the last 12 bars; FVG = 3-bar gap formed in the 12 bars into the sweep; IFVG = a later 5-minute close beyond the gap's
  far edge within 12 bars of the sweep; stop = "slightly beyond the gap": the gap's far side + 0.1 ATR [E/A]; 2R;
  one position at a time.
- Relation: liquidity-sweep family, but on BTC/gold with an IFVG entry (the library's sweep books trade NIFTY levels or
  use engulfing/CISD entries) - kept as a variant.
- Status: ready with documented assumptions.

## Data Trader summary
Coded: DT-01 to DT-08 (DT-05 is the bonus strategy inside 8blv0NdYeRc).
