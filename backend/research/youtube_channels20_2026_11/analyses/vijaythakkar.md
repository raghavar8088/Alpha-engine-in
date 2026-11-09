# Vijay Thakkar (@VijayThakkar, UCHvscyzKoKxhLcaz1LQ6mHg) - "MastersInOne" interviews

Hindi; long podcast interviews with Indian traders. Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## VT-01 The 33 EMA band on 9 minutes: body close beyond the band + RSI beyond 55/45 + VWAP side, stop at the signal candle (Sankalp Chaturvedi): i6h9Swn2X2Y
"How to Trade Option Buying Using 33 EMA Strategy | Ft Sankalp Chaturvedi | MastersInOne EP 69" (2026-02-28, 92:15), https://youtu.be/i6h9Swn2X2Y
- 9-minute chart (his "sweet spot" covering short and long term); options on the 3-minute chart [E 40:32-42:30].
- Band = EMA 33 on highs and EMA 33 on lows; long only when part of the candle BODY closes above the band (a wick is
  confusion), RSI above 55 (below 45 for shorts; 45-55 = no-trade zone) and price above VWAP [E 42:30-49:30, 56:30].
- Risk:reward must be acceptable versus the next supply / demand level, else skip [E 48:30-50:00].
- Entry: the next candle (or the break of the strong "king" candle); stop = that candle's low (high) or just beyond the
  next level [E 56:30-58:00]. Daily target and a daily loss ceiling - stop trading for the day at either [E 55:11-56:00].
  Gap days: the 3-candle rule [E 59:27]. Exits in T1, T2, T3 [E 01:07:05].
- Code [A]: NIFTY and BANK NIFTY, 9-minute bars anchored at 09:15 (from 1-minute data); RSI 14; session VWAP; body
  rule = close beyond the band edge and open on the other side of that edge or inside the band; entry next bar open;
  stop = signal candle's low (high); one third each at 1R, 2R, 3R; the 1:2 check against levels is not coded; after
  a win or two losses, no more trades that day; on gap days (|gap| > 0.5%) the first 3 candles are skipped; exit 15:15.
- Status: ready with documented assumptions.

## VT-02 Weekly Supertrend (10, 3) on stocks: flip on a strong "king" candle, enter on a close above that candle's high, Supertrend stop/trail, 40/40/20 booking (Vijay Khant): 8WOYvhvvXo0
"SuperTrend Indicator Masterclass | Simple Strategy + 5 Hacks | ft Vijay Khant | MastersInOne EP 59" (2025-08-23, 60:14), https://youtu.be/8WOYvhvvXo0
- Stocks, weekly chart only (monthly for bigger trends, never below weekly); Supertrend 10 / 3 [E 17:16-18:00, 24:30-25:00].
- Positive flip = a weekly close above the Supertrend line. Hacks: the flip candle must be strong (big body, little
  shadow - "king candle"); mark its high and enter only when a later weekly candle closes above that high; rank several
  breakouts by candle strength [E 23:33-34:00].
- Stop = the Supertrend line itself (not the candle low); the same line trails; exit when it turns negative [E 35:35-36:30].
  Profit booking 40 / 40 / 20 at his targets [E 20:40]. Allocate 5-7% of capital per stock [E 11:30].
- 50 EMA band (weekly) for adding on pullbacks [E 43:14-45:30] - not coded.
- Code [A]: NSE daily pool resampled to weekly bars (Monday-Friday); strong candle = body >= 60% of range and close in
  the top 25%; entry at the next week's open after a weekly close above the flip candle's high within 8 weeks; stop and
  exit = a weekly close below the Supertrend (10, 3); the 40/40/20 targets are not given numerically -> whole position
  rides the Supertrend [A]; long only; holds across weeks.
- Status: ready with documented assumptions.

### VT-02 second source (same system, merged): OH9EvJMmaW4
"Life-Changing Indicator - A Simple Strategy to Buy & Sell ft. Vijay Khant | MastersInOne EP10" (2023-05-13, 42:50), https://youtu.be/OH9EvJMmaW4
- The same weekly Supertrend ("magnetic line") system: buy when a weekly candle has turned it positive and the next
  week breaks that candle's high; exit when price goes back below the line; pre-decided allocation; book 40% of the
  quantity after a 40% move [E 07:30, 16:00-25:00]. Merged into VT-02 (duplicate video).

## VT-03 Rule-based swing (Sunil Gurjar): price above EMA 20/50/200, resistance breakout, stop under the breakout candle or swing low (max 8-10%), 9 EMA two-candle exit: hH7VfOq0120
"Learn a Simple Rule Based Swing Trading strategy | ft. Sunil Gurjar | MastersInOne EP 23" (2023-11-11, 62:16), https://youtu.be/hH7VfOq0120
- Trend: EMA 200 (long term), 50 (mid), 20 (short); trade long only when the stock is above all three [E 19:20-24:48].
- Entry: a breakout above resistance (e.g. a 200-EMA / pattern breakout) [E 24:48-27:00, 32:52-41:00].
- Stop: a big breakout candle -> its low; otherwise the recent swing low; on daily never risk more than 8-10% - skip
  bigger [E 24:48-28:30].
- Trailing exit with EMA 9 on any timeframe: a bearish candle closes below EMA 9, then a second bearish candle closes
  below the first one's low -> exit [E 30:12-33:30]. Pattern targets (cup-and-handle depth) as an alternative [E 33:30-41:00].
- Code [A]: NSE daily pool; resistance = the highest high of the previous 50 sessions; breakout = a close above it with
  close > EMA20 > ... (close above EMA 20, 50 and 200); big candle = range >= 4% of the close; else stop = the lowest low
  of the last 10 sessions; skip if the stop is more than 10% away; entry next open; exit by the 9 EMA rule (next open);
  long only; no fixed target.
- Status: ready with documented assumptions.

## Vijay Thakkar summary
Coded: VT-01, VT-02, VT-03. OH9EvJMmaW4 merged into VT-02.
