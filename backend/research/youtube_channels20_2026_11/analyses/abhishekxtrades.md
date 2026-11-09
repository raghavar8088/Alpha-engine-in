# AbhishekXTrades (@AbhishekXTrades, UCUJmHX01pQAsP8yQ_TfsmZw)

Abhishek Nautiyal; Hindi with English terms; NIFTY intraday, option buying, crypto and gold scalping live streams.
Tags: **[E]** stated, **[I]** inferred from the chart demonstration, **[A]** research assumption needed to code it.

## AX-01 EMA 5/20 cross, one or two counter candles, break of the counter candle within 3 bars: AgDZVDuxrec
"Perfect Entry & Exit with 5-20 EMA Strategy (Intraday Reversal Mastery)" (2025-06-15, 28:41), https://youtu.be/AgDZVDuxrec

- Timeframe 5 minutes ("best intraday timeframe") [E]; Indian index intraday (NIFTY / Sensex charts) [I].
- Rule 1: an EMA 5 / EMA 20 crossover is required; only the first two crossovers of the day are traded - a third means
  sideways [E 11:00-12:00]. Bullish = EMA 5 above EMA 20 [E 07:00].
- Rules 2-3: after a bullish cross wait for a red (counter) candle - one or two are fine; three red candles in a row =
  reversal, no trade ("do matlab correction, teen matlab reversal") [E 12:00-14:00]. Mirror for bearish crosses.
- Rule 4: mark the counter candle's high (+ small buffer); entry when one of the next three candles breaks it; the
  crossover candle itself may be the trigger candle [E 14:00-16:00, 17:00-18:00].
- Rule 5 (stop): the nearest swing low (high); if that stop is too large, halve it [E 17:00, 19:30, 24:00].
- Rule 6: risk:reward at least 1:2 (2-3 as you like) [E 16:00, 24:00-25:00].
- Rule 7: crossovers in the morning (09:15-10:15) are the high-probability ones; reduce size in the afternoon [E 16:00-17:00].
- No overtrading after a stop-loss [E 25:00].
- Code: NIFTY and BANKNIFTY 5-minute [A]; up to 2 crossovers a day [E]; buy-stop = counter candle high + 0.02% [A];
  stop = the lowest low of the last 10 bars, halved toward entry when wider than 1.5 ATR(14) [A for the thresholds];
  target 2R [E]; entries until 14:30, afternoon size not reduced (one size) [A]; stop trading for the day after a loss
  [E]; exit 15:15.
- Status: ready with documented assumptions.

## AX-02 Previous-day high/low bias, counter-candle open break on 15 minutes, partial at 1:1, rest to 15:15: slAtZyGfAlI
"Zero to Hero Option Buying Strategy | 3 Step Entry-Exit for Nifty Options" (2026-07-25, 32:39), https://youtu.be/slAtZyGfAlI

- Market: NIFTY (bought through options; the desk trades the NIFTY index signal [A]). Timeframe 15 minutes [E 04:00, 10:00].
- Levels: only the previous day's high and low [E 04:00-05:00].
- Bias: price above the previous high -> buys only; below the previous low -> sells only; in between -> no-trade day
  [E 05:00-08:00].
- Entry (sell below the low): wait for a "buyer" - a green 15-minute candle; then a candle that closes below that green
  candle's open (not its wick) within the next two candles -> sell; three green candles in a row = reversal, no entry
  until the colour flips again [E 09:00-12:30, 14:00-14:30]. Buys above the high are the mirror (a red candle, then a
  close above its open) [E 14:00-14:30].
- Stop: beyond the entry candle with a small buffer [E 17:00, 28:00].
- Exit: partial at 1:1 (e.g. 3 of 5 lots), the rest to 1:2 or held to 15:15 for the big move [E 17:00-18:30, 25:00-29:30].
- Re-entry after a stop-loss is allowed [E 20:30-22:00]. Hero-zero expiry trades are a separate idea [E 01:00] - not coded.
- Code [A]: NIFTY 15-minute bars; the signal close must be beyond the previous day's level on the bias side; counter run
  of at most 2 candles; entry at the next bar open; stop = the signal bar's high (sells) / low (buys) + 0.03% buffer;
  60% off at 1R, the remaining 40% holds to 15:15 with the original stop; at most 3 entries a day.
- Status: ready with documented assumptions (index proxy instead of option premiums).

## AX-03 NIFTY 9:30-10:00 range (2nd and 3rd 15-minute candles) break, fixed 25-point scalp: UKxK6uY2WRg
"BEST 5 Minute Scalping Strategy (CRAZY WIN RATE!)" (2025-11-02, 18:42), https://youtu.be/UKxK6uY2WRg

- Market: NIFTY 50 on 15-minute candles (despite the title) [E 03:00-03:30]. Do nothing until 10:00 [E 04:00, 15:00].
- Rule 1: ignore the first candle (09:15-09:30); resistance = the higher high of the 2nd and 3rd candles, support = the
  lower low of the two (09:30-10:00) [E 05:30-07:00].
- Rule 2: resistance breaks -> buy; support breaks -> sell [E 07:00-07:30, 08:00].
- Target: only 20-25 NIFTY points, then stop trading for the day ("naa laalach naa dar") [E 08:00-12:00, 15:00].
- No overtrading on a day the trade fails [E 15:00]. Optional sizing from his FII / proprietary data sheet [E 16:00] - not coded.
- Their test (stated): October 2025, 22 sessions, 17 wins, 5 losses (77%); expects 70-80% over years [E 00:00-00:30, 16:00].
- Stop: not stated; a stop-out is shown on a two-sided day [E 13:30]. Code [A]: stop at the opposite edge of the
  09:30-10:00 range; stop-order entry at the broken level from 10:00 until 14:30; target +25 points; one trade a day;
  exit 15:15.
- Status: ready with documented assumptions (stop level).

## AX-04 "All-touch candle" (EMA 5/9/15 + SMA 20) in the first 45 minutes, 1:1, stop-and-reverse once: YbQa2rX8w80
"My 1 Minute Scalping Strategy (Complete Course)" (2025-12-23, 24:19), https://youtu.be/YbQa2rX8w80

- Market: NIFTY (options as the vehicle); shown on 15 minutes - "15 minutes is the best for NIFTY", 1 or 5 minutes
  possible [E 10:30-11:00]. Coded on 15 minutes [E].
- Lines: EMA 5, EMA 9, EMA 15 and SMA 20 - used only to qualify the entry candle, not for direction [E 03:00].
- Rule 1: a candle whose body or wick touches all four lines ("all-touch candle") [E 04:30]; Rule 2: it closes above all
  four -> buy; below all four -> sell [E 05:00]; Rule 3: a strong candle, not a tiny one [E 05:30].
- Only the first valid setup between 09:15 and 10:00; no setup by then = no trade that day [E 02:00, 11:30-12:00].
- Stop: the candle's low (buys) / high (sells); if very large (e.g. 50 points) cut it by 50%; never below 15 points [E 06:00-07:00].
- Target: 10-20 option-premium points, or 1:1 / 1:2 on chart structure [E 07:00-08:00].
- If the stop is hit, stop-and-reverse once with the same rules; two losses = day closed; at most 3 trades a day
  [E 02:00, 21:00-22:30]. FII/DII data as an optional filter [E 21:00] - not coded.
- Code [A]: entry at the next bar open; strong = body >= 40% of range and range >= 0.6 ATR(14); stop rules as stated
  [E]; target 1R [E: 1:1 option]; one reversal after a stop-out (entry next bar open, stop = the extreme of the bar that
  hit the stop, at least 15 points, target 1R); exit 15:15.
- Status: ready with documented assumptions.

## AX-05 CPR relationship bias, touch-and-close entry, stop beyond the CPR, 1:2, stop-and-reverse: d14BGHrCZDk
"CPR Trading Strategy: Entry and Exit - Part 2" (2025-08-14, 27:19), https://youtu.be/d14BGHrCZDk

- Market: NIFTY 50, 15-minute chart (not 5 minutes - fakeouts) [E 02:00, 06:00].
- Bias: today's CPR above yesterday's CPR (even slightly) -> buys only; below -> sells only [E 05:00-06:00].
- Entry (buys): price touches the CPR at any time of day; then the same candle or any later candle closes above the CPR
  -> enter at that close; colour of the candle does not matter [E 06:00-07:00, 08:00-09:00, 19:00-20:30]. Sells: touch,
  then a close below the CPR's bottom line [E 07:00].
- Stop: safe = beyond the far side of the CPR; aggressive = a buffer inside it (small capital) [E 09:00, 15:00, 22:30].
- Target: at least 1:2 [E 12:30, 15:00, 21:30].
- Stop-and-reverse: if the first trade is stopped, take the opposite trade when price closes on the other side of the
  CPR, again 1:2 [E 14:00-15:00, 18:00].
- Code [A]: CPR from the previous session's high, low, close (pivot, BC = (H+L)/2, TC = 2*pivot - BC); "above" = today's
  pivot above yesterday's pivot; touch = bar range overlaps the CPR band; entry = next bar open after the first close
  beyond the band on the bias side; stop = the far edge of the band - 0.02% (safe version); target 2R; at most one
  reversal; entries until 14:30; exit 15:15.
- Relation: different from NJ-02 (narrow-CPR + opening side) - kept.
- Status: ready with documented assumptions.

## (not a separate strategy) Stop-and-reverse overlay: 90ALPU-qFdU
"Stop & Reverse Full Course: The Only Intraday Strategy You Need!" (2025-03-28, 15:23), https://youtu.be/90ALPU-qFdU
- A management rule on top of any entry: small stop, target twice the stop; if the stop is hit before the trade went
  1:1, book the loss, wait for a candle CLOSE beyond the stop level, then enter the opposite way with the same 1:2 plan;
  at most two (three) such trades per setup [E 05:00-13:30]. "Use your own entry" [E 05:00].
- No entry rule of its own -> **blocked** as a standalone strategy (incomplete); the overlay is already part of AX-04
  and AX-05, which the same channel teaches with it.

## AX-06 Bitcoin "20-20 EMA": EMA 20 on 15 minutes and EMA 20 on 1 hour, touch both, close back over the 15-minute EMA: -2EWviNvQrI
"20-20 EMA Crypto Trading Strategy | 2026 How to Get Perfect Trades" (2026-01-19, 18:47), https://youtu.be/-2EWviNvQrI

- Market: BTC (Delta Exchange); chart 15 minutes for intraday [E 02:00-03:00].
- Lines: EMA 20 with the chart's 15-minute timeframe and EMA 20 with the 60-minute timeframe [E 03:00].
- Direction: price above both -> buys only; below both -> sells only; no counter-trend trades [E 04:00].
- Buy: price comes down and touches both EMAs (any time), then a candle closes back above the 15-minute EMA -> buy at
  that close; the touch and the close can be the same candle [E 04:00-05:00, 10:30, 13:00].
- Stop: the lowest point after the touch (the entry candle's low) with a buffer [E 10:00, 13:30, 15:00].
- Exit by style: scalper 1:1 (max 1:2) or out after 1 hour; intraday at least 1:2-1:3 or at the day's end; swing on
  1-hour charts, hold until a close back through the 60-minute EMA [E 06:00-06:30, 13:00-15:00]. After 1:1 move the
  stop just past break-even [E 11:00-11:30, 16:00].
- Trend filter: the trend-angle tool must show more than 20 degrees (25+ = fruitful); below 20 = sideways, skip
  [E 07:00-08:00].
- Code [A]: BTC 15-minute intraday version; 20-degree angle (chart-scale dependent, not reproducible) replaced by the
  60-minute EMA 20 having moved >= 0.4% in the trade's direction over the last 6 hours; touch = a bar's low (high) reaching
  the 60-minute EMA after the last close beyond both; entry at the first close back beyond the 15-minute EMA with the
  close beyond both lines; stop = the extreme since the touch - 0.1 ATR(14); target 2R; stop to entry + 0.1R at 1R; out
  at the UTC day end.
- Status: ready with documented assumptions (trend-angle substitute).

## AbhishekXTrades summary
Coded: AX-01 to AX-06. The stop-and-reverse course (90ALPU-qFdU) is a management overlay without an entry rule (not a
separate strategy; used inside AX-04 and AX-05).
