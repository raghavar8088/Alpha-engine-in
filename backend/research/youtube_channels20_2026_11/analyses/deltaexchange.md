# Delta Exchange (@deltaexchange, UCaw-1cUd74wvEatvZna0TzQ)

The exchange's own channel (Delta Exchange India), Hindi with English terms; bitcoin and ether futures and options.
This is the venue the paper desk prices crypto and gold on. Tags: **[E]** stated, **[I]** inferred from the chart
demonstration or wording, **[A]** research assumption needed to code it.

## DE-01 EMA 9/30 cross with a strong candle that breaks the last swing, 3 minutes: QElRfGfoxjI
"Best Scalping Strategy 9:30 EMA | Intraday Trading Bitcoin" (2025-05-31, 8:35), https://youtu.be/QElRfGfoxjI

- Market: BTC (and ETH) perpetual futures; timeframe 3 minutes [E 02:00, description].
- Indicators: EMA 9 and EMA 30 [E 01:00-02:00]. Sideways when price winds around both EMAs: no trade [E 01:00, 07:00].
- Short (3 rules) [E 02:40-05:00]: (1) no trade without EMA 9 crossing below EMA 30; (2) no trade if the candle at the
  cross closes far away from the cross (bad risk:reward, price returns to the average); (3) trade when, at the cross, a
  strong bearish candle closes close to the cross and breaks the previous swing low. Long mirror [E 05:27-07:00].
- Entry: the next candle after the cross [E 04:00-05:00, 06:00].
- Stop: "at the previous candle's close" - small stop [E 04:00-05:00, 06:00]. Code: the close of the bar before the
  signal bar, at least 0.25 ATR(14) from the entry [I/A].
- Target and management: risk:reward 1:2 (1:3 possible); trail while price stays beyond the 30 EMA / until a candle
  closes back beyond the 9 EMA; partial booking in strong trends [E 05:00, 07:00]. Code: half at 2R, the rest exits on
  a 3-minute close beyond EMA 9 against the trade, stop to entry after 2R [A for the split].
- Code: cross on the signal bar or one bar earlier [A]; strong candle = body >= 50% of its range and close beyond the
  lowest low (highest high) of the previous 10 bars [A]; "close to the cross" = |close - EMA 30| <= 0.6 ATR(14) [A].
- Status: ready with documented assumptions.

## DE-02 EMA 20/50/100 stack + Williams fractal + previous-high break, 1 minute: LfqOU_dM6IU
"Best Scalping Trading Strategy for Beginners | Bitcoin & Crypto F&O Special" (2025-11-05, 11:49), https://youtu.be/LfqOU_dM6IU

- Market: BTC futures; timeframe 1 minute (1, 3, 5 suit scalpers) [E 01:00].
- Trend: "3 moving averages" EMA 20, 50, 100; long only with 20 above 50 above 100 and price above all three; short the
  mirror [E 01:00-03:00, 09:00-10:00]. Lines must be spread apart, not clustered (clustered = confusion, no trade)
  [E 03:00, 05:00]. Check the 4-hour trend first and scalp only its way [E 04:00-05:00].
- Entry signal: Williams fractal signal in the trend direction (down-fractal arrow for buys, up-fractal for sells) and
  price breaking the previous high (low for shorts); enter at the close of that candle [E 03:35-04:00, 06:00-07:00].
- Stop: below EMA 20 (or beyond the previous swing / EMA 50 / EMA 100 when the pullback was deeper) [E 06:00, 08:00, 10:00-11:00].
- Target: 1:2 for scalps, 1:3 with conviction; trail to cost or book partly after the target [E 06:00-08:00].
- Code: Williams fractal n=2, usable only once confirmed (2 bars after the pivot) [I]; the fractal must be confirmed
  within the last 5 bars [A]; "spread" = |EMA20 - EMA100| >= 0.1% of price [A]; "previous high" = the latest confirmed
  up-fractal [A]; 4-hour trend = last completed 4-hour close above its EMA 50 (below for shorts) [A]; stop = EMA 20 at
  the signal bar minus 0.1 ATR, at least 0.25 ATR from entry [A]; target 2R [E].
- Status: ready with documented assumptions.

## DE-03 "Neela Peela": EMA 57 / EMA 111 first retest, multi-timeframe agreement, 1-minute trail: HfZjaGM7c_U
"High-Accuracy Trading Strategy for Bitcoin Futures!" (2025-01-04, 21:19), https://youtu.be/HfZjaGM7c_U
Guest: "Shanky's Trading" (podcast format; Hindi and English mixed, captions rough).

- Market: BTC futures [E]. Lines: moving average 57 and "triple one" (111), exponential [E 00:00-01:00] - blue and
  yellow ("neela peela").
- Agreement: candles below both lines on the 1-, 3-, 5- (and 15-) minute charts = shorts only; above = longs only; check
  5-3-1 for shorts and 1-3-5 for longs [E 01:00-03:00, 08:00-09:00, 12:00-13:00, 19:00]. Trade the 5-minute chart [E 03:00].
- Entry: after the candles break through the lines, do not chase; wait for price to come back and touch the yellow or
  blue line, then a small candle; enter beyond that small candle [E 03:00-05:00].
- Stop: the far line ("this low line is your stop-loss") [E 04:00]; a candle that reverses back across the lines =
  exit [E 10:00].
- Management: trail the stop; for a 5-minute entry trail with the 1-minute chart's lines - exit when 1-minute candles
  come back across them [E 05:00-08:00, 11:00-12:00]. No fixed target [E].
- Cycles: the first retest after a break is the good trade; the second is riskier, the third more [E 06:00].
- Crosses of the two lines mean nothing; lines close together = a big break is near [E 18:00].
- Timing (IST): Monday-Friday 06:00-09:30 is best; avoid the US open (19:00-22:30) and weekends [E 09:00-10:00, 16:00-20:00].
- Code: EMA 57 / 111 on 1, 3 and 5 minutes [E]; break = a 5-minute close beyond both lines after a close on the other
  side within the last 48 bars [A]; touch = a later bar's high (shorts) reaching the nearer line; small candle = range
  <= 0.6 ATR(14) [A]; sell-stop below it valid 2 bars [A]; only the first touch after each break [E]; stop above the
  farther line + 0.1 ATR [I/A]; exit when a 1-minute bar closes above both 1-minute lines (below for longs) [E]; entries
  06:00-09:30 IST Monday-Friday [E]; positions run at most until 12:00 IST [A].
- Status: ready with documented assumptions.

## DE-04 Gold 4-hour Supertrend (10, 4) long-only with a one-time 30% add on a 40-bar closing breakout: FZ7YFTl_xF4
"Supertrend Gold Strategy 4H Rules Explained" (2026-10-13, 11:30), https://youtu.be/FZ7YFTl_xF4

- Market: gold (PAXG on TradingView; Delta's gold contract for execution) [E 05:52, 08:00]. Timeframe 4 hours; every
  decision only on a closed candle [E 01:00-02:00]. Long only - no short rules [E 00:40].
- Entry: Supertrend (ATR 10, multiplier 4) flips bearish -> bullish; buy 100% at the next 4-hour open [E 02:00-03:00].
- Add-on: on a 4-hour close above the highest close of the previous 40 candles, add 30% at the next open, once per
  trend; never average down [E 03:00-04:00].
- Exit: Supertrend flips bullish -> bearish; close everything at the next open. No stop-loss, no target [E 04:04].
- Their backtest (stated, not verified): PAXG 4h, Jan 2022 - Sep 2026, 0.03% commission: about +212%, max drawdown
  8.21%, profit factor 3.13, 118 trades, 47% winners [E 05:52-07:00]. Ours is run independently.
- Code: XAUUSD 4-hour bars built from minutes in UTC [A: the desk's gold research series]; sizing 100% of the book's
  notional for the base and 30% for the add-on (no stop, so the R unit is set to 2% of the entry price for reporting)
  [A]; the book holds across sessions and weekends [E].
- Status: ready (all rules explicit; only the sizing unit and data series are assumptions).

## DE-05 BTC daily-expiry short strangle at 23:30 IST, OTM15 legs, 50% leg stops, 4 re-entries at cost: dK3FCfA6PcI
"BTC Daily Expiry Option Selling Setup (11:30 PM) | AlgoTest" (2025-11-28, 11:07), https://youtu.be/dK3FCfA6PcI

- Instrument: Delta Exchange BTC options, daily expiry (expires 17:30 IST next day) [E 01:00-02:00].
- Entry 23:30 IST: sell the OTM15 call and the OTM15 put (15 strikes from ATM), 1 BTC each (1,000 lots) [E 02:00-03:00, 05:00].
- Stop per leg: 50% above that leg's premium; legs are independent (a call stop does not close the put) [E 02:00, 04:00].
- Re-entry: up to 4 times per leg, when the premium comes back to the original sale price ("re-cost") [E 04:00-05:00].
- Exit: 17:15 IST [E 02:00]. Their AlgoTest backtest (stated): Dec 2024 - Nov 2025, after fees and 10% slippage
  +8.38 lakh rupees, 86% winners, max drawdown 2 days to recover [E 06:20-10:00].
- Status: **blocked** for automation here: the paper desk has no BTC option prices (neither history for a backtest nor
  a live option-quote path in the desk); recorded for a later options build.

## DE-06 BTC short strangle at 21:00 IST, ~2% OTM, 70% decay target, 100% combined-premium stop, no weekends: nI3xJ1SZuJ0
"Bitcoin Short Strangle Strategy for Sideways Markets | 73% Win Rate Backtest | Rule-Based" (2026-07-22, 17:01), https://youtu.be/nI3xJ1SZuJ0

- Instrument: Delta BTC options, next-day expiry [E 02:48-04:15]. Entry 21:00 IST Monday-Friday (no Saturday/Sunday:
  thin premiums) [E 02:48-03:30, 08:15-09:00].
- Legs: sell one call and one put about 2% from spot (delta ~0.18); re-check the distance every 3 months from the last
  365 days of BTC peak moves [E 03:00-04:15, 09:45].
- Target: buy back when the combined premium has decayed 70% [E 05:56-06:30]. Stop: exit when the combined premium has
  risen by 100% of the collected premium [E 07:13-08:15, 09:45]. Time exit: next day 17:00 IST [E 10:30].
- Avoid event (macro) days [E 15:23, 16:00]. Their backtest (stated): 73% winners, average win $190, average loss $397,
  one losing month (Nov 2025) [E 11:43-14:21].
- Status: **blocked** for the same reason as DE-05 (no BTC option prices in the desk).

## DE-07 The 7:30 PM IST bitcoin trade: 30-minute candle in the 4-hour trend's direction, stop beyond it, 1:1: UjNHWEHxAuU
"Best Trading Strategy For Beginners to trade Crypto Futures!" (2024-11-16, 66:01), https://youtu.be/UjNHWEHxAuU
Guest: CA Rahul Jadhav (podcast episode 1).

- Market: BTC futures [E]. Timeframes: 4 hours for the trend, 1 hour for levels, 30 minutes for the trade [E 42:00-43:00].
- Direction: 4-hour trend bullish = buys only; bearish = sells only [E 42:00-43:00, 46:00].
- Entry: at 19:30 IST, on the 30-minute candle shown as "7 PM" (open 19:00 IST, closes 19:30 IST), enter as it closes
  [E 33:00-35:00, 43:00-44:00]. Watch 19:30-21:30 IST; most moves start there [E 33:00, 37:00].
- Stop: beyond that 30-minute candle (its low for buys, high for sells) [E 34:00-35:00, 44:00, 46:00].
- Target: start with 1:1 (most hit by 21:30); later 1:3-1:5 with experience [E 44:00-45:00, 46:00].
- Risk management: about 600 BTC points of stop; risk 5% a trade (he took 10%); at 1:1 cut the risk in half, at 1:2
  move to zero risk [E 40:00, 50:30-53:30].
- Monday-Friday only (US market closed at weekends) [E 45:00-46:00]. His screenshots: 140 days of examples [E 35:00-36:00] (not verified).
- 1-hour levels / trend lines are discretionary context [E 43:00] - not coded.
- Code: 4-hour trend = the last completed 4-hour close above (below) its EMA 50 [A]; entry at the 14:00 UTC open (19:30
  IST) in the trend's direction [E]; stop beyond the 13:30-14:00 UTC 30-minute candle, at least 0.15% from entry [A];
  target 1R [E]; no fill by then -> exit 16:00 UTC (21:30 IST) [A]; Monday-Friday [E].
- Status: ready with documented assumptions (trend definition, time exit).

## DE-08 Session strategy (Tokyo close 13:30 IST / New York open 19:00 IST) with "Double AI SuperTrend", multi-layer volume profile and 1-hour FVG: fWtaHzVCln0
"Top Crypto Trader Shares SECRET Session Strategies" (2025-09-23, 77:43), https://youtu.be/fWtaHzVCln0
Guest: Rahul (Delta podcast); BTC and ETH futures.

- Top-down weekly -> daily -> 4 hours -> 1 hour, never below 1 hour [E 11:30-12:00]. Be active only at the Tokyo close
  (13:30 IST) or the New York open (19:00 IST) [E 15:00-19:30].
- Direction and levels from two community TradingView indicators on 4 hours - "Double AI SuperTrend" (adaptive, "AI"
  parameters change by timeframe) and a "multi-layer volume profile" [E 22:45-36:15]; entry on the 1-hour chart at a
  fair value gap with a rejection / engulfing candle, stop above it [E 40:05-47:00, 56:30-58:00].
- Risk: max stop 2,000 BTC points (100 ETH points); trail - at 2R move to cost, at 3R lock 1R; targets up to 1:10 [E 07:30, 45:00-47:30, 55:00].
- Status: **blocked** - the trend filter and levels come from adaptive community indicators whose exact settings and
  formulas are not given, and the levels are chosen by eye; coding it would mean inventing the core rule.

## Delta Exchange videos read but not coded
DE-05, DE-06 (no option prices in the desk) and DE-08 (incomplete rules) are recorded above as blocked.
