# The Trading School (@thetradingschool-trafi, UCUzGUWt1zx8krC5i3Lzv7rA)

Hindi; NIFTY intraday price action, Fibonacci, SMC, gold. Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## TS-01 NIFTY first 1-hour candle wick zones: 5-minute break-and-confirm or reject-and-confirm, 1:2: XWxaZBrx3QU
"This "First Candle Rule" Is The Easiest Intraday Trading Strategy For Beginners" (2025-11-26, 19:45), https://youtu.be/XWxaZBrx3QU
- The first 1-hour candle (09:15-10:15) must have a strong body (not a doji); mark its upper-wick zone and lower-wick
  zone (a line if there is no wick) [E 00:30-04:00, 12:30, 15:30-16:00].
- After 10:15, on 5 minutes, only strong / normal candles count as signals [E 04:00-05:00]:
  break - a strong candle closes beyond a zone and the next candle confirms -> trade the break; reject - a strong candle
  rejects from the zone and the next candle closes beyond the signal candle (e.g. below its low) -> trade the reversal;
  retest after a break -> enter again [E 01:00-02:30, 05:30-11:30, 13:00-17:00].
- Stop: beyond the zone (above the high for shorts) or the signal candle; target at least 1:2 [E 06:30-08:30, 11:00-12:00, 17:00].
- Code [A]: NIFTY (and BANK NIFTY) 5-minute; strong first hour = body >= 50% of its range; strong 5-minute candle = body
  >= 60% of range and range >= 0.8 ATR(14); confirmation = the next bar closes beyond the signal bar's far end; entry next
  bar open; stop = beyond the zone's outer edge for rejections / beyond the signal bar for breaks, + 0.02% buffer; 2R;
  at most 2 trades a day; entries 10:15-14:30; exit 15:15.
- Relation: an Indian-session cousin of the New York "first candle" books (JR-01..05), but with 1-hour wick zones and both
  break and rejection trades - kept.
- Status: ready with documented assumptions.

## TS-02 NIFTY first 1-hour range: a later 1-hour candle sweeps its high (low) and closes back inside -> fade; target min(1:2, the far side): -w0LCfL5Eqs
"The Most Powerful NIFTY Intraday Trading Strategy" (2026-05-29, 33:26), https://youtu.be/-w0LCfL5Eqs
- NIFTY, 1-hour timeframe; mark the 09:15-10:15 candle's high and low (any colour, gap or not) [E 00:30-01:30].
- Wait for any later 1-hour candle that trades above the high (below the low) and closes back inside - a liquidity
  sweep; enter as it closes [E 01:30-03:00, 04:30, 11:00].
- Stop: the sweeping candle's high (low); target = whichever comes first: 1:2 or the first candle's opposite extreme
  [E 03:00-04:30].
- Code: NIFTY and BANK NIFTY 60-minute bars (session-anchored 09:15) [A for BANK NIFTY]; entry at the next bar open
  after the close [I]; one trade a day; exit 15:15.
- Status: ready (explicit).

## TS-03 Multi-day squeeze range in a stock, breakout on high volume, exit on a close back inside, at least 1:3: 3jIJJu_vTfg
"My Intraday Strategy For Everyday (Simple & Proven)" (2025-08-25, 17:55), https://youtu.be/3jIJJu_vTfg
- Money first: risk at most 1% of capital a trade (about 10% of capital in one trade), minimum 1:2, aim 1:3+ [E 04:00-09:00].
- Setup: a stock squeezed in a tight range for 2-3 days (e.g. 16 points on a 1,240 stock); the break of that recent range
  with high volume (big participants) [E 09:00-13:30]. Entry on the follow-through or a pullback with good behaviour [E 12:00].
- Exit: if a candle closes back inside the range; target the recent 1-hour swing high, never below 1:2, 1:3 preferred;
  an early exit on a 15-minute change of behaviour [E 13:30-15:00].
- Code [A]: NSE pool; range = high and low of the previous two sessions, width <= 2% of price; break = a 15-minute close
  beyond it on volume >= 2x the 20-bar average; entry next bar open; exit on a 15-minute close back inside the range;
  hard stop at the range midpoint; target 3R; one trade per stock a day; entries until 14:00; exit 15:15.
- Status: ready with documented assumptions.

## TS-04 Gold: previous-day wick zones (mother candle if inside day), 15-minute sweep of the prior candle inside the zone, close-through entry, 1:2: ctLHzjrH3Rk
"Gold Trading Strategy That Every Trader Should Know!" (2026-10-29, 25:19), https://youtu.be/ctLHzjrH3Rk
- Daily chart: the previous day's upper wick = supply / resistance zone, lower wick = demand / support zone; if the
  previous day is an inside bar, use the mother candle's wicks [E 03:00-04:00].
- Sell only in the supply zone, buy only in the demand zone [E 05:00-06:00].
- On 15 minutes (not 5 or 3): a candle sweeps the previous candle's high and closes back below it (liquidity sweep);
  then a candle closes below the sweep candle's low -> sell at that close; stop above the sweep high; 1:2 [E 06:00-07:30].
- Code [A]: XAUUSD 15-minute, New York 17:00 trading day for the daily candle; the sweep candle's high must be inside the
  zone (between the body top and the high of the reference candle, buys mirrored); confirmation within 4 bars; entry
  next bar open; 2R; at most 2 trades a day; exit at the 17:00 NY session end.
- Status: ready with documented assumptions.

## TS-05 Bitcoin 1-minute Fibonacci retracement: pullback into 0.5-0.786, close back out (or 0.786 rejection), 1:1: qz3UPcGbnMk
"Fibonacci Scalping Strategy | 1 din men 4-5 Trades kaise len?" (2026-10-15, 21:00), https://youtu.be/qz3UPcGbnMk
- BTC (on MEXC), 1-minute chart; a move without retracement is not traded - wait for the pullback [E 00:30, 06:30-09:00].
- Fibonacci from the swing high to the swing low of the impulse; only the 0.5 to 0.786 band is used [E 09:00-10:30].
- Entry (downtrend): price retraces into the band and a candle closes back below it, or price rejects 0.786 and closes
  back inside -> sell at that close; stop above the highest candle of the retracement / above 0.786; 1:1 first (more is
  possible); re-draw the Fibonacci on each new swing low [E 12:00-18:00]. 4-5 trades a day [E title].
- Code [A]: BTC 1-minute; swings = fractal n=5; impulse leg >= 0.4% from a confirmed swing high to the later swing low
  (mirror for longs); entry next open after a bar that touched the band closes beyond the 0.5 level on the trend side;
  stop = the retracement's extreme + 0.1 ATR; target 1R; setup valid for 60 bars; at most 5 trades a day; exit 23:55 UTC.
- Relation: different from NJ-28 (0.618 tap with an FVG, 15/60-minute) - kept.
- Status: ready with documented assumptions.

## The Trading School summary
Coded: TS-01 to TS-05.
