# Sagar Sinha (@coachsagarsinha): video analyses

Tags as in neerajjoshi.md: E = stated or shown; I = inferred; A = research assumption. Times HH:MM:SS. Several videos
are interviews with guest traders; the guest is named.

-AHJGdaVYJ4 (market timing for NIFTY options, 19 Sep 2026, 27 min): 09:15-09:20 no-trade zone (overnight news, gift
NIFTY gap), 09:20-09:45 observe (most fake breakouts), 09:45-11:00 prime time (institutions have entered, premiums
settle), midday slow, 14:45 onwards institutions square off (volatility that is not a trend), no fresh entries
15:00-15:30 for new traders. A timing guide, no entry rule: used as background only.

7es2AnoWe1w (guest Vishal, "one indicator", 30 Nov 2025, 29 min): supply/demand target zones from a paid indicator
(daily, 4-hour and weekly zones, 3-minute entries): the indicator is paid and its logic is not shown: not
reproducible.

## SS-01 Bollinger Band + Heikin Ashi alert candle, daily NIFTY, guest Kushal Varshney (4VMQaVoK8Rk, 11 Feb 2026,
25 min)

Market: NIFTY positional (futures/options), daily candles; his 2025 back-test: about 15-20 trades, +6,786 NIFTY points
(E 00:04:00). Read the rule parts in full.

- Set-up (E 00:04:00-00:05:00): Bollinger Bands; sells are planned only at the upper band, buys only at the lower
  band; Heikin Ashi candles show the trend.
- Alert candle (E 00:06:00-00:08:00): after a Heikin Ashi candle touches the band, the next candle that closes inside
  the band without touching it is the alert candle (any colour).
- Entry and stop (E 00:08:30-00:09:30): note the alert candle's date, switch to normal candles: sell below that day's
  low, stop at that day's high (buy above the high, stop at the low, at the lower band). If the high breaks before the
  low, the alert is invalid (E 00:12:00-00:13:00).
- Target (E 00:10:00): the opposite (lower) band is the first target; exit earlier if the signal changes.
- A: the desk's daily NIFTY market; Bollinger 20, 2 on the Heikin Ashi series (as TradingView plots it on a Heikin
  Ashi chart); a stop-entry at the alert day's real low (high), valid until filled or invalidated by a break of the
  other side; stop at the alert day's high (low); target the opposite band (value at the alert day); exit early at
  the next open if an opposite alert candle appears; time stop 25 sessions.

## SS-02 EMA 5/13 cross at the previous day's high or low, 15 minutes (II4B6AlOwQg, 16 Apr 2026, 55 min)

Market: crypto (bitcoin shown; "works in every market"), 15-minute candles, for intraday traders and scalpers.
Read the rule parts in full.

- Signal (E 00:16:00-00:18:00, 00:26:00-00:28:00): EMA 5 crossing above EMA 13 = long; crossing below = short.
- Range (E 00:19:30-00:22:00, 00:32:00-00:34:00): first mark the previous day's high (resistance) and low (support)
  on the daily chart; take crosses near those edges (long near support, short near resistance); ignore crosses in
  the middle of the range, where the market is sideways (E 00:36:00, 00:38:00).
- Entry (E 00:40:00): after the cross wait for the next candle to complete (the gap between the EMAs widening), then
  enter at the start of the following candle.
- Stop and target (E 00:42:00-00:48:00): swing to swing: the stop at the nearest swing low, the target the nearest
  swing high (or an equal or double distance when no swing is there); skip the trade if the reward is below 1:1, or
  cut the size when the swing is far.
- A: BTCUSD 15-minute; previous day = the previous UTC day (TradingView's daily candle); "near" = the cross candle's
  low within 0.5 x ATR 14 of the previous day's low or below it (high mirrored); enter at the open two candles after
  the cross; stop 0.1 x ATR beyond the latest confirmed 3-candle fractal low (high); target the nearest confirmed
  fractal high (low) beyond the entry if at least 1R away, else 2R; skip if the stop is more than 3 x ATR away.

## SS-03 Lowest-volume opposite candle, guest Kushal Varshney (b0D4mvFZa5k, 4 Feb 2025, 44 min, 1.7M views)

Market: NSE F&O stocks, 5-minute candles. Read the rule parts in full.

- Direction (E 00:04:00-00:06:00): at 09:25 compare advances and declines of the NIFTY 50: more declines = a short
  day, more advances = a long day.
- Stocks (E 00:06:00-00:10:00, 00:24:00): for a short day the weakest sector at 09:25 and its F&O stocks (liquid, no
  circuit limits); with many stocks, the top losers at 09:25-09:30.
- Entry (E 00:12:00-00:18:30): ignore the first three 5-minute candles (09:15-09:30); on a short day wait for an
  opposite-colour (green) candle whose volume is the lowest of the day so far ("the train is empty"); place a sell
  order below its low with the stop at its high; if a later green candle has an even lower volume before the order
  fills, move the order to it.
- Exit (E 00:20:00-00:22:00): book half at 1:2 and move the stop on the rest to cost; trail the rest with EMA 10:
  exit when a candle closes beyond EMA 10.
- A: the desk's NSE 5-minute stock pool; direction from the pool's stocks at 09:25 (price above / below the previous
  close) since the pool is not exactly the NIFTY 50, and sectors are not in the pool, so the three weakest (strongest)
  stocks by 09:25 change are traded instead of the weakest sector; a stop-entry at the candle's low (high), valid
  until 14:30 or until a newer lower-volume candle replaces it; half off at 2R with the stop to breakeven, the rest
  exits at the next open after a 5-minute close beyond EMA 10; out at 15:15; one trade per stock per day.

## SS-04 The same 5-minute candle every day, guest Subhasish (Power of Stocks) (Ib29qwuKZVE, 9 Aug 2024, 32 min)

Market: BANKNIFTY (any instrument), 5-minute candles; "choose any 5-minute candle before 12:00" - the guest builds it
live on 09:45-09:50 (E 00:05:00-00:06:00). Read the rule parts in full.

- Rule (E 00:06:00-00:08:00): mark that candle's high and low; buy if price crosses above the high, sell if it goes
  below the low (stop at the other side); trading only one side (like an investor, only buys) raises the probability
  and cuts trades and charges.
- Expect stops on sideways days and the money on trending days (1:3-1:4 when held for the day, E 00:08:00-00:10:00);
  judge it over 20-40 trades (E 00:15:30).
- A: BANKNIFTY; the 09:45-09:50 candle; both sides as stop-entries (whichever triggers first, the other side may
  still trigger after a stop); stop at the candle's other end; exit at 15:15; at most two trades a day.

## SS-05 BTST: Heikin Ashi close vs the real close at 15:15, guest Kushal Varshney (LxiS75iIpPc, 11 Mar 2025, 37 min)

Market: NIFTY (also BANKNIFTY), daily candles read at 15:15, the trade held overnight for the next day's gap. Read
the rule parts in full.

- Rule 1 (E 00:06:00-00:08:00): at 15:15 read today's daily close on the Heikin Ashi chart and on the normal chart.
  If the Heikin Ashi close is greater than the normal close, tomorrow is likely to gap down: sell.
- Rule 2 (E 00:08:00): if the normal close is greater than the Heikin Ashi close, tomorrow is likely to gap up: buy.
- Filter (E 00:10:00-00:12:00): the two closes must differ by at least 10 NIFTY points; less is confusion: skip.
- His day-by-day check (E 00:08:00-00:12:00) shows the reading matching the next day's direction repeatedly; he
  trades it by selling a hedged option in the predicted direction rather than buying an option (E 00:12:00).
- A: NIFTY on the desk's index feed; at 15:15 the day's open, high, low (so far) and the 15:15 price; Heikin Ashi close
  = (open + high + low + close) / 4; difference at least 10 points; enter at 15:16 in the predicted direction; exit at
  09:20 the next session; a protective stop of 1 x the daily ATR 14 (overnight gaps fill at the open).

## SS-06 EMA 30/50/100 stacked, enter at EMA 30, guest Priyank (kCxz5ESvlt4, 2 May 2025, 26 min)

Market: bitcoin; daily, 4-hour and 15-minute charts; trades on 15 minutes (E 00:04:00, 00:20:00). Read the rule parts
in full.

- Set-up (E 00:07:00-00:16:30): EMA 30, 50 and 100 in order (30 on top, then 50, then 100) and moving apart; when
  they are flat and tangled ("lazy"), wait; once they line up and price breaks a high, the trade is on.
- Entry (E 00:18:00): either on that breakout or, better, when price first comes back to EMA 30 (the closer to EMA
  30, the better the reward).
- Stop and target (E 00:18:00, 00:22:00): stop below the swing low; target 1.5R-2R (he mostly takes 1.5 or 2); trail
  below EMA 100 for a bigger move; add on later set-ups at EMA 30/50. Shorts mirror it (EMA 100 on top), e.g. on the
  break of a swing low.
- A: BTCUSD 15-minute; stacked = EMA 30 > EMA 50 > EMA 100, all three higher than 4 candles ago and EMA 30 - EMA 100 at
  least 1 x ATR 14; entry = a limit at EMA 30 on the first pullback after the stack forms (valid 12 candles); stop 0.1
  x ATR below the latest confirmed 3-candle fractal low; target 2R; one trade per stack.

9a41ZKEicts (operators' traps), OFbl_R4dB6k (option selling for beginners), ROShVG0ylGg (support/resistance class 6):
theory. Bh1C7zPZNXs (expiry-day option selection, guest Nitin) needs the option chain after 14:00: not implemented.

Desk markets: SS-01 and SS-05 NIFTY (daily market, index feed); SS-03 NSE 5-minute stock pool; SS-04 BANKNIFTY; SS-02
and SS-06 BTCUSD.
