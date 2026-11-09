# Upsurge Club (@Upsurge_club, UCQQojT_AmVWGb4Eg-QniuBA)

Interview channel (Hindi/English) - each video is a guest trader explaining his setup. Tags: **[E]** stated, **[I]**
inferred, **[A]** research assumption.

## UP-01 The 9:15 AM open-price cross (Rajesh Jain): after the first 30 seconds, price crossing back through the open -> ATM option that way, out by 9:30: GAr-2Cw4LIQ
"The 9:15 AM Options Strategy (Stupid, Simple and Proven) | Ft. Rajesh Jain" (2026-07-17, 74:13), https://youtu.be/GAr-2Cw4LIQ
- Sit at 09:15, be out by 09:30 ("good night") [E 12:29-17:00]. Pick the first F&O stock that shows at the top of the
  gainers / losers list after 09:15 (he likes selling losers); NIFTY / BANK NIFTY / SENSEX also work [E 18:00-19:30, 42:00-47:00].
- Wait 30 seconds after 09:15; if price made a high and then breaks back below the open price, it will not go up -> buy
  the ATM put (mirror: ATM call); only ATM strikes [E 00:00-00:30, 19:30-26:30, 32:00-33:00].
- Exit by 09:25-09:30, book the profit; typical index targets: NIFTY ~20 points, BANK NIFTY 25-60, SENSEX 60-80 [E 46:00-48:30, 50:30].
  A stop-loss is used (level not given numerically); on losing days usually about 3 stops in 20 days [E 49:00].
- Code [A]: index version only - NIFTY and BANK NIFTY 1-minute index data (the stock version needs sub-minute stock data
  the desk does not have; options proxied by the index); signal = the 09:15 one-minute bar trades above (below) the open
  and closes back below (above) it; entry at the 09:16 open the opposite way; stop = the 09:15 bar's extreme; target =
  20 points (NIFTY) / 40 points (BANK NIFTY); time exit 09:30.
- Status: ready with documented assumptions (index proxy, 1-minute resolution instead of 30 seconds).

## UP-02 Gap-up trap: first hour closes below VWAP with a big upper wick -> after 10:15 short at the VWAP retest (10-minute), stop = two closes above VWAP, pivots as targets (Chirag Rathod): 1IgiogVjyq0
"Intraday Option Buying Strategy using VWAP | Ft. Chirag Rathod" (2025-10-17, 33:39), https://youtu.be/1IgiogVjyq0
- Stocks (stock options, the strike just beyond ATM); the market "opens at 10:15" for him - never enter before 10:15 [E 09:00-09:30, 21:00].
- Setup (short): a stock gaps up (e.g. 4-5%), makes a big upper wick (a trap / pin bar) and the first 1-hour candle
  closes below VWAP [E 09:30-10:00, 22:00-23:30]. Mirror for gap-downs with a long lower wick closing above VWAP [I].
- Entry: after 10:15, on 10 minutes, when price comes back to VWAP ("the station") [E 23:00-25:00, 27:30].
- Stop: two 10-minute candles closing above VWAP [E 24:30-25:00]. Targets: the pivot levels (S1, then S2; R1/R2 for longs)
  [E 12:00]. Typical move ~2% in the stock, 25-40% in the option [E 10:00, 24:30].
- Code [A]: NSE pool, 10-minute bars (two 5-minute bars); gap >= 1% from the previous close; first 60 minutes: upper wick
  >= 50% of its range and close below VWAP; limit sell at VWAP from 10:15 to 13:30; exit when two consecutive 10-minute
  closes are above VWAP; protective stop at the day's high; half at classic pivot S1, rest at S2 or 15:15; mirror for
  gap-downs; one trade per stock a day.
- Status: ready with documented assumptions.

## UP-03 15-minute ADX "curve": DI side for the trend, ADX rising up from below into the DI lines, break of the signal candle, exit when the curve leaves (Rajesh Jain): b7-oxVP8tBc
"ADX Trading Strategy: Entry, Exit & Stop-Loss Explained | Ft. Rajesh Jain" (2026-09-13, 38:36), https://youtu.be/b7-oxVP8tBc
- 15-minute chart for intraday (125 minutes for swing); single timeframe, no multi-timeframe [E 24:30, 30:30-32:00].
- Trend = the DI lines: -DI (red) above +DI (green) = negative trend; the numbers do not matter, the curves do [E 00:00, 04:10-17:10].
- Entry: when the ADX line comes up from below into / through the DI lines (rising strength); a candle in the trend's
  direction; the trade activates when its high (low) breaks; stop = that candle's low (high) [E 13:30-14:00, 17:00-20:00, 35:20-36:30].
  Do not take an ADX that comes down from above [E 31:30]. A first 15-minute candle against the trend whose high does
  not break -> stay with the trend [E 11:30-12:00].
- Exit: when the curve leaves (ADX turns and drops back out of the lines) - "strength over" [E 13:30-14:00, 20:00-21:30, 30:30].
- Code [A]: NSE pool 15-minute; DMI/ADX 14 (Wilder); setup when ADX crosses up through the lower of the two DI lines
  while rising, with the trend side from +DI vs -DI; signal candle = the current bar if it closes in the trend direction;
  stop-order at its high (low) valid 2 bars; stop at its low (high); exit when ADX falls for 2 consecutive bars or the DI
  lines cross, or 15:15; one trade per stock a day.
- Status: ready with documented assumptions (ADX length, exit "curve" reading).

## UP-04 NIFTY 5-minute: previous day's Heikin Ashi colour for the side, EMA 200 high/low band, Squeeze Momentum (34) turning light, Supertrend (5, 1) stop (Animesh Kumar): MtBcbuYR8Wg
"The 5-Minute Setup for Intraday Options Trading | Ft. Animesh Kumar" (2026-08-16, 39:34), https://youtu.be/MtBcbuYR8Wg
- Side: the previous day's daily Heikin Ashi candle - green -> think calls only the next day, red -> puts [E 06:00, 10:30-12:00].
- NIFTY 5-minute Heikin Ashi chart with a band of EMA 200 on highs and EMA 200 on lows (above the band = bullish chance),
  Supertrend 5 / 1 (instead of 10 / 3) and the LazyBear Squeeze Momentum with Bollinger length 34 [E 07:30-12:00, 20:40-21:30].
- Entry: Supertrend on the trade side, and the Squeeze Momentum bar turns light green above zero (confirmation; the
  aggressive version enters on the turn from dark red); buy above the high of that Heikin Ashi candle [E 12:00-16:30, 17:00].
- Stop: the Supertrend line with a 10-20 point buffer, closing basis [E 18:00-18:30]. Dark-green momentum = alert;
  exit on a Supertrend flip; re-enter when momentum turns light again while Supertrend holds; 1:2 or the swing high
  [E 18:30-20:30, 29:00].
- Options: ATM / slightly ITM on the matching side [E 31:10] - the desk trades the NIFTY index signal [A].
- Code [A]: NIFTY 5-minute; Heikin Ashi from 5-minute bars for the trigger; long only when price closes above EMA200(high)
  (short below EMA200(low)); squeeze value = LazyBear linreg(close - avg(avg(HH20, LL20), SMA20), 20) with BB 34 / 2.0
  and KC 20 / 1.5 (only the momentum value is used); light green = value > 0 and rising; buy-stop at the trigger HA
  candle's high valid 2 bars; stop = Supertrend(5, 1) - 10 points; exit on a 5-minute close below the Supertrend or at
  2R or 15:15.
- Status: ready with documented assumptions (squeeze formula defaults, index proxy).

## UP-05 Stretch from the 20 MA beyond 0.9%, then EMA 20 / 50 cross the other way, 30 / 40-point targets, trail the rest (Himanshu Arora): es1kMDAiaYs
"Scalping strategy using EMA & DMA by Himanshu Arora" (2025-03-19, 30:17), https://youtu.be/es1kMDAiaYs
- Index (NIFTY / BANK NIFTY / SENSEX) on 1-2 minutes (5 max) [E 06:45-08:16, 27:19-28:30].
- "DMA": the percentage gap between price and the 20-period moving average; for scalping the extreme is about 0.9%
  (~1%) - below -0.9% = buy zone, above +0.9% = sell zone; use percent, not points [E 09:00-11:00, 14:00-15:30, 28:30].
  Such extremes come mostly at 09:30-10:00 [E 15:30].
- Then the entry: EMA 20 crosses above EMA 50; buy above the high of the cross candle [E 16:30-17:00].
- Exit: if not in profit, exit when EMA 20 crosses back below EMA 50 (below that candle's low) - about 20-22 NIFTY
  points of loss; targets 30 then 35-40 points, book ~70% there and trail the rest until the opposite cross [E 17:00-18:30].
- Code [A]: NIFTY 2-minute (from 1-minute data); gap = (close - EMA20) / EMA20; setup when it reaches -0.9% (buys) or
  +0.9% (sells); the EMA 20/50 cross must come within 60 bars; buy-stop at the cross candle's high valid 2 bars; hard
  stop 22 points; 35% at +30, 35% at +40, the rest exits on the opposite cross or 15:15.
- Status: ready with documented assumptions.

## UP-06 Reversal scalp: a 3-minute candle at least 50% outside a Supertrend-logic volatility band with the stochastic-type oscillator beyond 80/20, trailing stop order, 1:1 + 1:2 (Adib Noorani): u8zTNH3lJbU
"My "ONE INDICATOR" Scalping Strategy I Will Use for Life ft. Adib Noorani" (2025-10-31, 44:30), https://youtu.be/u8zTNH3lJbU
- NIFTY 3-minute (1-5 minutes possible); skip 09:15-09:45 and stop looking after ~15:00 [E 05:20-07:00, 12:00-13:30].
- His own indicator: a volatility band built on Supertrend logic (ATR x multiplier) plus a single-line oscillator built
  on stochastic maths (80 / 20 lines); candles closing outside the upper band print white, below the lower band black
  [E 08:50-10:30, 21:30-22:00]. Exact lengths / multipliers are not given.
- Sell: a candle with at least 50% of its height (high-low) above the upper band and the oscillator above 80 -> sell
  order below its low (with a buffer); if the next candle does not break that low, move the order to the new candle's
  low; stop above the signal candle [E 13:30-17:00, 22:00-28:00]. Buy: the mirror (below the lower band, oscillator < 20).
- Two lots: one out at 1:1, the other's stop to cost, booked at 1:2 (later 1:3 / trail) [E 31:00-39:00].
- Code [A]: band = Supertrend (10, 3)'s ratcheted final bands as of the bar before (Supertrend's own band logic; a first draft used the plain hl2 +/- 3 x ATR(10) band and had an order-side bug that gave no signal - both fixed before activation, no paper trade used the draft); oscillator = average of Stochastic %K(14, 3) and %D(3);
  order life 5 bars, trailed to each new bar's low (high); buffer 0.01%; stop = signal candle's high + buffer; 50% at
  1R, stop to entry, 50% at 2R; exit 15:15.
- Status: **requires documented assumptions** - the indicator's exact settings are not disclosed; the coded version is a
  stated approximation.

## UP-07 Change-in-OI PCR after 11:00 (above 1.25 calls, below 0.75 puts), entry at the option's VWAP, stop under the option's day low (CA Nitin Murarka): u_TGW73x9Uk - **blocked**
"Stop Gambling In Options Try This Rules-Based Intraday Options Strategy | Ft. CA Nitin Murarka" (2025-12-27, 59:57), https://youtu.be/u_TGW73x9Uk
- After 11:00 compute (change in put OI) / (change in call OI) over ATM +/- N strikes (N = days to expiry; 1 on expiry
  day); > 1.25 -> buy calls, < 0.75 -> buy puts, between -> no trade [E 06:15-17:18, 22:07-37:00].
- Entry at the option premium's VWAP, never far from it; stop at / below the option's day low; target 30-35 points;
  gap days: wait until 14:00 [E 24:30, 36:00-37:00, 42:00-43:30].
- Needs the live and historical NSE option chain (open interest by strike) and option premium bars - the desk has
  neither (no option-chain history for a backtest, no intraday premium path). Not coded.

## Upsurge Club summary
Coded: UP-01 to UP-06 (UP-06 with stated indicator approximations). Blocked: UP-07 (option-chain data).
