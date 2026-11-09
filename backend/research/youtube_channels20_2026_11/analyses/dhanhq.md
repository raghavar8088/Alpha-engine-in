# Dhan (@DhanHQ, UCEzHCpvFWoF85UabbzKTkOQ)

Broker channel; most strategy videos are presented by Mukul Choudhary (a trader, 13 years in the business). Hindi with
English trading terms. Transcripts: YouTube's Hindi auto-captions, read in Latin letters. Tags: **[E]** stated in the
video, **[I]** inferred from the chart demonstration or wording, **[A]** research assumption needed to code it.

## DH-01 VWAP pullback with an engulfing turn after a liquidity sweep: pUg_7sPauQA
"VWAP Scalping Setup: 3 Rules Every Trader Should Know" (2026-03-07, 18:00), https://youtu.be/pUg_7sPauQA

- Market: NIFTY futures (VWAP read on the futures chart, not spot) [E 01:30-02:15, 06:00]; stocks also allowed [E 16:30].
- Timeframe: 1 to 5 minutes, never above 5 [E 16:30-17:15]. Code: 5 minutes [A].
- Window: 09:15-12:00 only; VWAP goes flat after noon [E 14:15, 17:15].
- Rule 1: trade only in the direction of the higher-timeframe trend; "if the market is up on 1 hour, only longs" [E 04:30-05:15].
  Code: last completed 1-hour bar's close above the 1-hour EMA 20 = up, below = down [A].
- Rule 2: the first touch of VWAP is not an entry; entries come after a liquidity sweep or a trap [E 05:15-06:00].
- Rule 3 (entry candle): long needs a bullish engulfing (or morning star) near VWAP after a sweep of a recent low;
  short needs a bearish engulfing (or evening star) near VWAP after a sweep of a recent high [E 08:15-09:00, 10:30, 15:00].
  "A hammer alone is not a buy" [E 10:30]. Code: the engulfing bar or the bar before it took out the lowest low of the
  previous 6 bars (long) and the engulfing bar's range comes within 0.1% of VWAP or crosses it [A]; entry next bar open.
- No trade when VWAP is flat / crossed again and again (sideways) or on news days [E 04:30, 09:00, 16:30].
  Code: skip if price crossed VWAP 4 or more times since the open [A].
- Stop: below the engulfing / sweep candle (or ATR-based) [E 10:30, 12:45, 15:00]. Code: beyond the setup's extreme [I].
- Target: 1:2 to 1:3, start with 1:2; else cost-to-cost [E 10:30, 12:45, 15:45]. Code: 1:2 [E].
- Second entry: VWAP touch again, or a "bracket" (flag) breakout in the trend direction [E 12:45-13:30] - not coded (vague).
- 1-2 trades a day, one instrument [E 16:30]. Code: 2 trades a day [E].
- Status: ready with documented assumptions (sweep lookback, VWAP proximity, HTF filter, flat-VWAP filter).

## DH-02 9:20 F&O top movers: VWAP pullback, inside bar, engulfing break: M50LMwoqgVE
"9:20 AM Intraday Stock Selection | VWAP + Inside Bar Setup" (2026-10-07, 11:04), https://youtu.be/M50LMwoqgVE

- Market: NSE F&O stocks (Dhan's list of ~208) [E 00:00-01:00]. Universe at 09:15-09:20: top 10 gainers and top 10
  losers [E 02:00, 05:00]; trade gainers long, losers short [E 08:00]. Code: the 5-minute pool's stocks ranked by the
  change from the previous close to the 09:20 close; 10 up / 10 down [A for the pool = our 5-minute NSE pool].
- Sector must agree (e.g. most of the IT sector green) [E 05:00-06:00]. Not coded: no sector map in the pool [A: dropped,
  documented].
- Setup (long): price above VWAP after a strong move, pulls back to VWAP (touch or near), forms an inside bar, then a
  bullish engulfing / close above the inside bar's high [E 01:00, 04:00, 06:00-07:00]. Nothing before 09:20-09:30
  [E 04:00]. Without an inside bar a direct engulfing also counts but with smaller risk (5,000 -> 3,000) [E 07:00, 09:00].
  Code: inside bar whose range touches VWAP or sits within 0.2% of it, then a 5-minute close beyond the inside bar's
  high (low for shorts) that also engulfs the prior bar's body [A]; timeframe 5 minutes [I].
- Stop: below the inside bar, preferably below VWAP [E 04:00, 06:00]. Code: the lower of the inside bar low and VWAP [I].
- Target: at least 1:2; book 50% at 1:2 and trail the rest, or exit all [E 04:00]. Code: half at 2R, rest to 3R or the
  15:15 exit [A: the trail is not described; fixed 3R].
- Entry window: before 11:00 best; 11:30, at most 12:00 [E 07:00].
- Size: fixed rupee risk (5,000) [E 07:00]. Desk: 1% of the book a trade.
- Status: ready with documented assumptions (sector filter dropped).

## DH-03 3-minute Heikin Ashi pullback scalp with EMA 100: JchD2CK6dM0
"3 Minute NIFTY Scalping Strategy | Find High Probability Trades in Minutes" (2026-10-15, 19:10), https://youtu.be/JchD2CK6dM0
Presenter: Priyanka (stock market mentor).

- Market: NIFTY futures; chart shown on spot, same rules on futures [E 00:00-01:00].
- Timeframe: 3 minutes, Heikin Ashi candles [E 03:00-04:00]. EMA 100 on the chart [E 04:00].
- Window: 10:00-12:00 only [E 04:00-05:00]. Many trades a day allowed (scalping) [E 02:00, 13:00].
- Bias: HA candles above EMA 100 = longs only; below = shorts only [E 09:00-10:00].
- Setup (long): a pullback of red HA candles; then skip the first two (or three) green HA candles; then the first doji or
  spinning top (small body, shadows both sides) is the trigger candle [E 11:00-13:00, 17:00]. Short mirror: after a green
  pullback, two or three red HA candles, then a doji / spinning top [E 15:00, 18:00].
- Entry: buy-stop above the trigger candle's high (sell-stop below its low) [E 13:00, 15:00, 17:00].
- Stop: the trigger candle's low (high for shorts) [E 13:00, 15:00].
- Target: 1:1 [E 13:00, 15:00, 18:00].
- Code: HA built from 3-minute bars; doji / spinning top = HA body <= 35% of the HA range with an upper and a lower
  shadow each >= 15% of the range [A]; the trigger must come within 6 bars of the second trend-colour candle [A]; stop
  orders are filled on the real futures-proxy price when it trades through the HA level [I]; pending order cancelled if
  not filled on the next bar [A].
- Status: ready with documented assumptions (doji definition, trigger window, order life).

## DH-04 First 30 minutes range, break, pullback, confirmation: rd3Rnh_5i9g
"First 30 Minutes Scalping Strategy for Nifty 50 (High-Probability Setup)" (2026-03-24, 20:17), https://youtu.be/rd3Rnh_5i9g
Presenter: Mukul Choudhary.

- Market: NIFTY (also Sensex, Bank Nifty, stocks) [E 00:00]; options mentioned only as the vehicle [E 15:00, 19:00].
- Timeframe: 5 minutes [E 06:00]. No trade before 09:45 [E 01:00-02:00, 06:00, 11:00].
- Range: high and low of 09:15-09:45 (the first 30 minutes), extended right [E 01:00-02:00].
- Break: price leaves the range (above = long side, below = short side) [E 02:00-03:00].
- Never trade the break directly on gap days; wait for a pullback towards the range, then a confirmation candle in the
  break direction with a big body and small wicks; trade when a candle closes beyond the pullback candle [E 03:00-05:00,
  12:00, 15:00, 17:00]. Code: after a 5-minute close beyond the range, at least one counter-colour candle (the pullback),
  then a trend-colour candle whose body is >= 60% of its range that closes beyond the pullback candle's low (shorts) /
  high (longs); entry next bar open [A for the 60% body].
- Stop: above (below) the confirmation candle, 1-2 points of buffer [E 04:00-05:00]. Code: the confirmation candle's
  extreme [E].
- Huge range candles are not traded; wait for a pullback [E 16:30-17:00]. Code: skip a confirmation candle whose range is
  more than 2.5x the 20-bar average range [A].
- Entry window 09:45-11:30; the trade may run until 14:00 or later [E 07:00]. 1-2 trades a day [E 13:00, 15:00].
- Target: half at the first 20-30 index points, rest trailed or all out [E 16:00]; the presenter's own NIFTY backtest:
  1:1.5 ~67% win, 1:2 ~60%, 1:3 ~51% [E 18:00]. Code: 1:2 [A, from the stated backtest], exit 15:15.
- Day filter: best on gap-up / gap-down days (normal gaps, not event gaps of hundreds of points) and when the previous
  day's 14:00-15:30 range was narrow [E 06:00, 08:00-09:00]. Code v1: gap between 0.2% and 1.2% of the previous close [A];
  the narrow-afternoon-range scenario is not coded.
- Status: ready with documented assumptions.

## DH-05 9:15-9:20 opening range breakout with a 1-1.5% move, RSI 55, rising ADX, Supertrend 7/2 trail: gr7J_LwPP60
"How to Trade the 9:15-9:20 Opening Range Breakout? | Find MORNING MOMENTUM Stocks" (2026-10-16, 9:16), https://youtu.be/gr7J_LwPP60

- Market: NSE stocks (F&O names in the demo; Bank Nifty also works) [E 02:00, 05:00]. Timeframe 5 minutes [E 01:00, 04:00].
- Opening range: the 09:15-09:20 candle's high and low [E 01:00].
- Long conditions at the break (scanner run 09:20-10:30 only) [E 06:00]: day change from the previous close above 1%
  and below 1.5% (no huge gaps) [E 02:00, 07:00]; close above today's open (green day) [E 02:00-03:00, 06:00];
  RSI above 55 on the 5-minute chart [E 03:00, 07:00]; volume "good" [E 03:00]; ADX rising (its level does not matter)
  [E 03:00-04:00, 07:00]. Shorts: "you can build the sell side too" [E 05:00] - mirrored [I].
- Exit: trail with Supertrend (7, 2); exit when price comes below it [E 04:00]; book part at about +0.7% [E 04:00].
- Longer time inside the opening range before the break = better [E 05:00] (not coded).
- Code: a 5-minute close above the 09:15 bar's high between 09:20 and 10:30 with all filters on that bar; RSI 14 [A];
  ADX 14 rising = above its value one bar earlier [A]; volume = bar volume above its 20-bar average [A]; entry next bar
  open; initial stop = the Supertrend (7, 2) line at the signal bar [I]; half at +0.7% [E], the rest exits on a 5-minute
  close beyond the Supertrend or at 15:15 [E/A]; one trade per stock a day [A].
- Status: ready with documented assumptions.

## DH-06 "9:20 BYR": 1%+ gainers above Supertrend with RSI 55 and volume, buy the 9:20 high, 0.65% target: 7_VhduccinA
"It's Boring. But It Works. | 9:20 AM Intraday Strategy for Beginners" (2026-11-03, 8:22), https://youtu.be/7_VhduccinA

- Market: NSE stocks; run the scan once at 09:20-09:25 [E 01:00, 06:00]. Long only (buy screener) [E].
- Conditions at 09:20 [E 01:00-02:00, 05:00-06:00]: day change >= 1% (screener caps at 4%); the 09:20 close above the
  day's open; price above Supertrend (5-minute); volume above average ("unusual"); RSI (5-minute) above 55.
- Entry: buy when the signal candle's high breaks (alert / stop order at that high) [E 02:00-03:00, 04:00].
- Target: 0.65% (0.65-1%), then out [E 03:00-04:00]. Stop: "you can place a stop-loss order" - level not given [E 03:00].
- 2-3 trades a day when NIFTY supports [E 06:00].
- Code: signal bar = the 09:15 5-minute bar (closes 09:20); change from the previous close 1-4% [E]; Supertrend (10, 3)
  [A: settings not shown]; volume of that bar above its 20-bar average [A]; RSI 14 [A]; buy-stop at its high valid until
  10:30 [A]; stop at its low [A]; target +0.65% [E]; exit 15:15; up to 3 stocks a day, the largest day change first [A].
- Relation: a variant of DH-05 (same opening scan family) with a fixed 0.65% target instead of a Supertrend trail and a
  volume filter instead of rising ADX - kept as a separate strategy because entry, exit and filters differ.
- Status: ready with documented assumptions (stop level, Supertrend settings).

## DH-07 Supertrend direction + Fisher Transform cross near zero + rising ADX (option buying on NIFTY): rgVCDtx1yLc
"Stop Losing in Intraday Option Buying: Try This 3-Indicator Setup" (2026-11-04, 28:47), https://youtu.be/rgVCDtx1yLc
Presenter: Dr. Priyanka.

- Market: NIFTY 50; the vehicle is an ATM call (up) or ATM put (down) [E 17:00-17:30, 26:00]. Timeframe 5 minutes [E 06:00, 26:00].
- 1 Direction: Supertrend green and candles above it = calls only; red and below = puts only [E 06:30-07:00, 26:00].
- 2 Momentum: Fisher Transform bullish cross (Fisher over its signal line) in the negative zone; do not buy at the cross,
  wait until the lines come up towards zero, then enter (mirror for puts) [E 10:00-12:30, 18:00-18:30, 26:00].
  Ignore crosses while the Fisher lines move sideways in a narrow band [E 12:30-13:00].
- 3 Strength: ADX sloping up and rising; a falling ADX means sideways, skip [E 14:00-17:00, 22:00, 26:30].
- Trigger: the three in this order, then the entry candle's high must break (low for puts) [E 21:30, 22:30, 27:00].
- Stop: the previous candle's low (high for puts), or the one before if too tight [E 21:30, 24:00, 27:00].
- Exit: hold while Supertrend keeps its colour; exit when it flips or goes flat (stagnant) [E 25:00, 27:00].
- Code (index proxy, not options [A: the desk has no intraday option premiums; the NIFTY index is traded instead and the
  option is only noted]): Supertrend (10, 3) [A]; Fisher Transform length 9, signal = previous Fisher value (TradingView
  convention) [A]; "near zero" = a bullish cross below zero, then the first bar with Fisher >= -0.3 while still above its
  signal, within 6 bars of the cross [A]; sideways Fisher = the 20-bar range of Fisher under 1.5 [A]; ADX 14 rising for 2
  bars [A]; buy-stop above the entry bar's high, valid one bar [A]; stop the previous bar's low; exit on a Supertrend
  flip, a flat Supertrend for 6 bars, or 15:15 [A for 6 bars].
- Status: ready with documented assumptions (index proxy, indicator settings, "near zero").

## DH-08 1-minute box breakout scalp (OCO stop orders on a tight consolidation): fn7wWaVZ3so
"1-Minute Box Scalping Strategy Every Scalper Should Know!" (2026-09-05, 30:15), https://youtu.be/fn7wWaVZ3so
Presenter: Dr. Priyanka; examples on NIFTY (futures) 1-minute charts.

- Timeframe: 1 minute [E 06:30-07:00]. Holding 2-10 minutes; many trades a day [E 17:30, 23:30].
- Box: a consolidation of "neutral" candles (small bodies, shadows both sides) whose highs sit at about one level and
  lows at about one level, about 10 NIFTY points wide [E 15:00-16:00, 20:30-21:00, 26:00]. The longer the consolidation,
  the stronger the break [E 16:00].
- Orders: buy-stop just above the box high and sell-stop just below the box low; when one fills, cancel the other; or
  wait for the breakout candle's close and enter on the next candle [E 17:00-17:30, 26:30-27:30].
- Stop: the other side of the box (base of the consolidation), 5-10 points; target 1:2, may hold for 1:3 [E 18:00, 26:30-27:30].
- Code: box = the last 10 completed 1-minute bars with (highest high - lowest low) <= 0.05% of price and at least 7 of
  them with body <= 50% of range [A]; OCO stop orders at the box edges valid for 10 bars [A]; stop = opposite edge [E];
  target 2R [E]; time stop 15 minutes [A]; window 09:30-15:00 [A]; at most 6 trades a day [A].
- Status: ready with documented assumptions (box width and length, order life, time stop).

## Dhan videos read but not coded
None of the eight selected videos was left out; DH-06 is kept as a separate variant of DH-05 (see above).
