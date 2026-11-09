# Tanisha Garg (@TanishaGarg101): video analyses

Tags as in neerajjoshi.md: E = stated or shown; I = inferred; A = research assumption. Times HH:MM:SS.

## Elephant Edge (her own indicator): not reproducible

Ten of her strategy videos are built on "Elephant Edge", her team's TradingView indicator (access is handed out
through her Telegram, 68gMJewN8FE 00:00:30). It draws buy zones (blue/green) and sell zones (orange) and "operator
candle" areas; the levels appear at 09:16 on the 1-minute chart for Indian scripts and change at 12:00 for crypto
(NUu9LZNLf-4 00:11:00), and the operator candle is where "our system detects institutional activity" in the candle
after a red candle (NUu9LZNLf-4 00:16:00). The videos teach the entries around the zones (1.0: a doji or pin bar at a
zone, buy the break of its high / sell the break of its low; stop at the zone's own line, never a candle's high or
low, 68gMJewN8FE 00:02:00-00:03:30; 2.0: half the capital at the zone, 30% more on a retest of the operator-candle
area, NUu9LZNLf-4 00:15:00-00:16:30), but never how the zones are calculated. Without the zone formula the rules
cannot be tested or paper traded faithfully, so none of the Elephant Edge videos becomes a desk strategy (qeE1CJ84h3k,
A2rZqzCz73A, 3dyf3VCygWE, 5k5t8nonFb4, 8KWifV8fZiQ, 68gMJewN8FE, EpeP3xBlrR8, nY5mbAP00iM, NUu9LZNLf-4, lHuS74qpflI,
and the secondaries SXWlUXVX8Ko, 6pcjJ6t91ZU, 75p1o5qQuYs).

Also Elephant-dependent: MSi8byaWnII ("1 setup for 30 days", 1 Oct 2026: ETH 15-minute on the Elephant zones, his
12-lakh account shown) and qZaY5z7m5SQ ("3 scalping indicators", 25 Oct 2026: VWAP to tell trend from range - price
crossing VWAP back and forth means range-bound, no trade; RSI 21 with only the 50 line - above 50 calls, below 50
puts; and the Elephant zones for the entry and the next zone as the target, E 00:10:00). Not reproducible.

Elephant-dependent as well: Cs_9RcJzbJU ("perfect scalping setup", 1 Jun 2026: scalper rules - 3 or 5-minute charts,
at least 1:2, a stop smaller than the profit, exit when momentum fades, never let a scalp become a held intraday
loser; the trades shown are Elephant 1.0 entries with the zone line as the stop) and yUCYvEDhBBI ("best entry
timing", 18 May 2026: take Elephant entries only before 10:30, the morning rally; after 12:00 the market is
range-bound). MJNDpdvnVZ4 ("one-sided setup", 19 May 2026) reads the day type from the ATM call + put premium around
09:20-09:25 against a VWAP-based number: needs live option premiums, which the desk does not trade; not implemented.

## TG-01 Failed breakout: trade the trap (Whu0KMg9ga0, 19 Jun 2026, 20 min)

Market: NIFTY shown on 15 minutes (any timeframe, 5 or 15 minutes, E 00:10:00); ETH used in her live trade. Read the
rule parts in full.

- Idea (E 00:04:30-00:08:00): do not try to judge whether a breakout is real. When a resistance that price has
  respected breaks, two cases follow: the breakout holds (the trade is simply missed) or price comes back below the
  resistance after the retest. In the second case the breakout buyers are trapped, their stops turn into sell orders
  and new sellers join: short ("sell on top"). About 7 of 10 breakouts fail (E 00:10:00, 00:18:00).
- Entry (E 00:12:00-00:14:00): wait for the break, the retest, and a close back below the resistance; enter then
  (never on the breakout itself). Supports mirror it (a failed breakdown is a buy).
- A strong old resistance trapping buyers can turn the trend for the next 4-5 days (E 00:16:00).
- Stop and target: not stated as a rule (her trade showed a first and a second target). A: stop 0.1 x ATR above the
  highest high made above the level; target 2R.
- A: NIFTY 15-minute; resistance = at least 2 confirmed 5-candle fractal highs within 0.25 x ATR 14 of each other in
  the last 60 candles; breakout = a close above the higher of them; trap = within 6 candles of the breakout, a close
  back below the level; enter at the next open; one trade a day per side; out at the session's end.

## TG-02 RSI 21 roof (60) and floor (40) break, 15 minutes (rZHjNu5zD9Q, 2 Aug 2025, 26 min)

Market: NIFTY (calls/puts as the vehicle), 15-minute candles for beginners (30-60 minutes if you have more time, E
00:04:00-00:05:30). Read the rule parts in full.

- RSI (E 00:06:00-00:08:00): length 21; only two lines: 60 (the "roof") and 40 (the "floor").
- Short (E 00:08:00-00:10:30): when RSI falls below the roof (crosses down through 60), price heads for the floor:
  mark the low of that cross candle; when the next candle breaks it, enter (puts).
- Long: RSI comes up off the floor (crosses up through 40): mark the cross candle's high; buy its break.
- Exit (E 00:10:30-00:12:00): the stop is the high (low) of the candle the trade was taken in: if it breaks, take the
  loss; do not wait for RSI to reach the other line: book the profit on the way.
- A: NIFTY 15-minute; a stop-entry at the cross candle's low (high), valid for the next candle; stop at the entry
  candle's high (low): A uses the cross candle's other end, known in advance; exit at the next open after RSI reaches
  50 (half-way, "book in the middle"), or the stop; out at the session's end; up to 2 trades a day.

## TG-03 Candle outside the Bollinger Band, back inside (IVwAoiwaJMg, 6 Jan 2026, 21 min)

Market: not named (she says she tested it for 5 years); intraday charts. Read the rule parts in full.

- Bands (E 00:06:00-00:08:00): Bollinger 20, 2 (95% of the time inside the bands; that is why 2, not 3).
- Wrong use (E 00:05:00): selling every touch of the upper band and buying every touch of the lower band.
- Rule (E 00:08:30-00:11:00): when a candle (e.g. a doji) forms completely outside the band, without touching it,
  price must come back inside: sell when that candle's low breaks; first target the middle band, second the lower
  band; stop: a close above that candle's high (closing basis). Mirror: a candle completely below the lower band,
  buy the break of its high, targets the middle band then the upper band.
- A: NIFTY 15-minute; "completely outside" = the candle's low above the upper band (high below the lower band); a
  stop-entry at its low (high) valid for the next 3 candles; target = the middle band at the signal candle; stop = a
  15-minute close beyond the signal candle's high (low), exit at the next open, with a hard stop 1.5 x ATR 14 beyond
  it for safety; size on the distance to the signal candle's high; out at the session's end.

## TG-05 EMA 20 cross with a held pullback candle, 1:4 (s7p-ymy_yEg, 31 Jan 2026, 25 min)

Market: crypto (she practises it on ETH, E 00:24:00; her live short was ETH), built for range-bound markets. Read the
rule parts in full.

- E 00:05:30-00:06:00: EMA 20 (exponential: the latest candle weighs more).
- Not this (E 00:08:30): buying the first green candle that closes above EMA 20 ("breakout"): in a range that traps.
- Long (E 00:09:30-00:12:30): after a green candle closes above EMA 20, one of the next two candles must be red and
  must not close below EMA 20 (a wick below is fine); when one of the next two candles breaks that red candle's high,
  buy at once (no waiting for a close).
- Stop (E 00:12:30-00:14:00): the lower of the two candles' lows (the green one or the red one); counted only on a
  candle closing below that line.
- Target (E 00:14:00): 1:4; do not try to ride the whole rally (E 00:20:00: with 1:4 a losing week is recovered).
- Short: the mirror (red candle closes below EMA 20, a green candle that does not close above it, short the break of
  its low).
- Ranges filter themselves out: the conditions keep failing (E 00:16:00).
- A: BTCUSD 15-minute (the desk has no ether account); the stop-entry at the pullback candle's high, valid for the
  2 candles after it; the stop counted on a 15-minute close below the line (exit at the next open) with a hard stop
  1.5 x ATR 14 below it; size on the line's distance; target 4R from the line distance.

## TG-06 Gann "special numbers": the nearer level pulls the next session (3_NIX-QQQyE, 25 Jun 2026, 32 min)

Market: NIFTY (also any script: BTC, ETH), overnight (BTST) with options as the vehicle. Read the rule parts in full.

- Special numbers (E 00:06:00-00:12:00): take the natural numbers n; n squared is a special number when n is odd; when
  n is even use n squared + 1 (e.g. 154 x 154 = 23,716 -> 23,717; 155 x 155 = 24,025). Around the price take the five
  levels below and five above.
- Reading (E 00:18:00-00:21:00): where the session closes between two levels, the next session goes to the level the
  close is nearer to ("it closed near the lower line, so it will go down"); this also predicts the next day's gap.
- Skip (E 00:20:00): a day on which price already touched both the upper and the lower level.
- Risk (E 00:21:30): a wrong gap prediction loses on the overnight position; she accepts that loss.
- A: NIFTY on the desk's daily NIFTY market; at the close, the two special levels around the close; long if the close
  is nearer the upper one, short if nearer the lower one; skip if the session's range touched both; enter at the
  close; target the nearer level; stop at the farther level; exit at the next session's close if neither is hit.

## TG-04 Engulfing of several candles, daily swing (IPXKi3fic_c, basics ep. 6, 2 Jan 2025, 13 min)

- E 00:01:30-00:04:30: after small candles in a fall, one green candle swallows the previous 3-4 candles (buyers took
  over); enter above its high; stop 1-2 points below its low (not exactly at the low). Bearish mirror. On daily or
  weekly charts for swing trades (E 00:04:30-00:05:30).
- No target given. A: the desk's NSE daily stock pool, long only; the green body covers the bodies of at least the
  previous 3 candles and closes below EMA 20 or within 1 x ATR of the 20-day low (after a fall); a buy-stop at its high
  valid 3 sessions; stop 0.2% below its low; target 2R; time stop 20 sessions.

## Other videos

q3NL2z0a-sk (sweeps + order blocks + FVGs, 9 Sep 2026, 20 min): her order block is the candle that made the last low
before the rally (colour does not matter), the FVG is measured on candle bodies; shown on XAUT (gold) and crypto;
the entry, stop and target are left to feel ("I am teaching you to feel the chart", E 00:14:00): not defined well
enough to test; the mechanics are NJ-29 / CP-13. hrr0tQypElY, d41zCFpEoio, iHCzV0vUay4 (SMC liquidity, order blocks,
trend reversal = the low that made the highest high breaks): theory. raW-ZcsXXgs (scalping) and XlfMEKV3lNo (BTC for
beginners, 15 minutes) are Elephant-zone trades. EITmOSIhzn4 (option chain: open interest of call and put writers)
needs option-chain data: not implemented. The crypto course parts (fxJBob4qORo, 5sBhLQjof7M, VKVBzL--SE8) are basics.

Desk markets: TG-01, TG-02, TG-03 NIFTY 15-minute; TG-06 the daily NIFTY market; TG-04 the NSE daily stock pool; TG-05
BTCUSD 15-minute.
