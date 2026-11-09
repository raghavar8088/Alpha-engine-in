# Stock Investment Academy by Amar Bhatia Sir (@STOCKINVESTMENTACADEMY, UCPtgdNLXi2QglhJBidB6QNw)

Hindi; Amar Bhatia (SEBI-registered research analyst); NSE intraday and swing. Tags: **[E]** stated, **[I]** inferred,
**[A]** research assumption.

## AB-01 Gap day high/low: next day a 5-minute close through the gap-day low (gap up) / high (gap down): ENIKnSEKXDA
"Intraday JACKPOT Gap Up And Gap Down Strategy | Secret Strategy" (2026-04-18, 31:50), https://youtu.be/ENIKnSEKXDA
- Markets: equities, F&O, commodities, currency [E 00:00]. Gap = a daily candle that does not overlap the previous
  one (above = gap up, below = gap down), any size [E 01:52-05:39].
- After the gap day closes, mark that candle's high and low [E 08:13-10:00].
- Next day, 5-minute chart: gap up -> when a 5-minute candle closes below the gap-day low (the gap was "artificial"),
  short at that close, at any time of day; stop = that 5-minute candle's high [E 10:00-12:56, 15:00]. Gap down -> a
  5-minute close above the gap-day high, long, stop = the candle's low [E 19:53-20:45, 28:13-29:30].
- Targets: beginners exit at 1:2 or 1:3; experienced: half at 1:2, stop to cost, ride the rest to the day's end
  [E 12:56-13:00, 30:53]. Strict stop-loss [E 14:26].
- Code [A]: the NSE 5-minute pool; gap = day T's low above day T-1's high (gap down: high below the low), from the pool's
  own daily candles; trade only on day T+1, first qualifying 5-minute close; entry next bar open; half at 2R with the
  stop moved to entry, the rest exits at 15:15; one trade per stock a day.
- Status: ready with documented assumptions.

## AB-02 First two 15-minute candles the same colour, the second closes beyond VWAP -> enter at 09:45: Eet1sXyCmbQ
"Best Intraday VWAP Trading Strategy | Master VWAP Indicator for Day Trading" (2025-05-24, 24:09), https://youtu.be/Eet1sXyCmbQ
- Stocks, 15-minute candles; never trade before 09:45 [E 07:30, 19:30-20:30].
- Long: the 09:15 and 09:30 candles both green and the second closes above VWAP -> enter at that close; short: both red
  and the second closes below VWAP [E 07:30-09:00, 13:00, 15:30]. Mixed colours -> avoid [E 09:30, 14:00].
- Stop: the lower of VWAP and the second candle's low (higher of the two for shorts) [E 08:30, 19:00].
- Target 1:1 for beginners, 1:2 / 1:3 with practice [E 08:30, 10:00].
- Avoid big gap-up / gap-down openers; if the entry was missed and price ran far from VWAP, skip [E 14:30, 18:30].
- Code [A]: NSE pool, 15-minute bars; entry at the 09:45 bar open; gap filter |open / previous close - 1| > 2% -> skip;
  target 1R [E beginner rule]; one trade per stock a day; exit 15:15.
- Status: ready with documented assumptions (gap size).

## AB-03 EMA 9/21 cross + a healthy confirmation candle, stop = lower of the candle low and EMA 9 (intraday 15-minute): OrYAGL9_0MU
"9 EMA 21 EMA Crossover Strategy | Swing Trading and Intraday" (2026-01-09, 16:42), https://youtu.be/OrYAGL9_0MU
- Any market; daily chart for swing, 15-minute chart for intraday [E 00:00, 13:35-15:00].
- Buy: EMA 9 crosses above EMA 21, then a confirmation candle: a healthy green candle (marubozu-like) or one whose lower
  wick is longer than its upper wick (lower rejection); enter on it [E 04:41-06:43, 08:00]. Sell: the mirror [E 07:48].
- Stop: the lower of the confirmation candle's low and EMA 9 [E 06:43]. Target at least 1:2 (3-5 possible); otherwise
  stay until the opposite cross; exit when the lines are far apart and price is stretched far from EMA 9 [E 06:43-08:00, 14:00].
- Intraday: same rules on 15 minutes, closed at 15:15 [E 14:00-15:00].
- Code [A]: NSE pool, 15-minute bars, intraday version only (the daily version is close to the library's NJ-46, EMA
  10/20 + marubozu, daily); healthy = body >= 60% of range, or lower wick > upper wick and close in the top half;
  confirmation within 3 bars of the cross; entry next bar open; exit at 3R, the opposite cross, or 15:15; one trade per
  stock a day.
- Status: ready with documented assumptions.

## AB-04 1-hour close at least 0.5% beyond the EMA 50 (BTST / swing), stop = lower of the candle low and EMA 50: NNAKTSXc5lU
"BTST and Swing Trading Strategy with 50 EMA" (2025-06-10, 19:36), https://youtu.be/NNAKTSXc5lU
- EMA 50 on 1-hour candles; any market [E 00:00, 02:30, 05:30].
- Buy when a 1-hour candle that crossed the EMA 50 closes at least 0.5% above it (wait for the close) [E 04:00-06:30].
- Stop: the lower of the candle's low and the EMA 50 [E 07:00]. Hold one day (BTST) or 5-7 days (swing); at least 1:2,
  1:3 possible; trail the stop; exit when price stretches far from the line or two candles show long upper wicks at
  the top [E 07:00-09:00]. Short selling is the mirror (F&O) [E 10:00].
- Code [A]: NSE pool, 60-minute bars built from 5-minute bars (sessions 09:15-10:15 ... 15:15-15:30 merged into the last
  hour); long only (cash-equity overnight holding); target 2R; time exit after 5 sessions at 15:15; one open position per
  stock; positions held overnight.
- Status: ready with documented assumptions.

## AB-05 5 EMA "alert candle" (with RSI on the chart), 1:1: KSCBybE9dVw - **duplicate**
"Intraday and Swing Trading Strategy | Alert Candle, Entry and Stop Loss | PART 1" (2026-02-26, 45:05), https://youtu.be/KSCBybE9dVw
- 5 EMA (+ RSI plotted, no rule stated for it in Part 1); alert candle = a candle that has left the EMA (no touch),
  below it for buys / above for sells; the next candle breaking its high (low) = entry; stop the alert candle's other
  end; target 1:1 (beginners); a newer alert candle replaces an older one; daily for swing, 5 minutes intraday
  [E 03:06-13:05, 23:20-27:00].
- Same logic as the library's YT-01 (Power of Stocks 5 EMA alert candle on NIFTY / BANK NIFTY); only the target (1:1)
  and timeframe split differ - merged as a duplicate, not a new book.

## AB-06 EMA 9/15 cross + pin bar / full-body / small-wick confirmation candle, 5-minute NIFTY, 1:1, NIFTY-BANK NIFTY agreement: cHsrNhr5yZ4
"Intraday Options Scalping | When To Enter & When To Exit | Power of Short Selling" (2026-03-21, 30:21), https://youtu.be/cHsrNhr5yZ4
- 5-minute chart, EMA 9 and EMA 15; avoid sideways markets [E 01:39-05:59].
- Buy: EMA 9 crosses above EMA 15, then a confirmation candle above the lines - a pin bar (lower rejection), a
  full-body (marubozu-like) candle, or a healthy candle with small wicks; buy as it closes; sell = mirror [E 06:01-07:28].
- Stop: that candle's low; target 1:1 for beginners; with practice hold to 1:2 / 1:3 while no opposite cross; scalps are
  closed the same day [E 07:28-11:00, 16:08]. Options: ATM or ITM strikes, never OTM [E 18:53]. Check NIFTY and BANK
  NIFTY together [E 25:11].
- Code [A]: NIFTY 5-minute index proxy (the desk has no intraday option premiums); BANK NIFTY's EMA 9 must be on the same
  side of its EMA 15 at the signal; confirmation within 3 bars of the cross; pin bar = lower wick >= 2x body and close
  in the top third; full body = body >= 70% of range; healthy = body >= 50% with each wick <= 25%; target 1R; exit 15:15.
- Status: ready with documented assumptions (index proxy).

## Stock Investment Academy summary
Coded: AB-01, AB-02, AB-03, AB-04, AB-06. Duplicate: AB-05 (library YT-01).
