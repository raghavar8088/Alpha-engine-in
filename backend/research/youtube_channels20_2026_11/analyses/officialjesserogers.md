# Jesse Rogers | Casper Trading (@officialjesserogers, UCEAq-8Ih0WI6R7wYoCFiWmA)

English; Nasdaq / S&P futures day trader ("First Candle Rule"); some crypto and gold. Futures examples are applied
here to the desk's BTC and gold books [A]. Tags: **[E]** stated, **[I]** inferred, **[A]** research assumption.

## JR-01 "First Candle Rule": first 15-minute New York candle, FVG displacement through it, limit at the FVG, stop candle 1, 2R: Qxlu8v_6G3Y
"The "First Candle Rule" Is The Easiest Way To Become Profitable FAST" (2025-10-22, 14:31), https://youtu.be/Qxlu8v_6G3Y
- Step 1: high and low of the first 15-minute candle at the New York open (9:30-9:45) [E 04:23-06:00].
- Step 2 (direction): on 5 minutes, a displacement break = a fair value gap through the range, with one of the three FVG
  candles closing outside it; wicks or a plain close do not count [E 06:00-07:44].
- Step 3: limit order at the FVG as soon as it prints; stop at the low (high) of FVG candle 1; fixed 2R; no
  micromanagement [E 07:44-09:53]. His last-month stats on NQ: 16 trades, 81% winners [E 09:53] (claims).
- Code [A]: BTC and XAUUSD 5-minute; limit at the FVG's near edge (top of a bullish gap), valid until 12:00 New York;
  first FVG break of the day only; exit 16:00 New York.
- Relation: same opening range as TP-03/TP-05, but a plain limit at the FVG with a candle-1 stop (no engulfing, no zone)
  - kept as a separate, fully mechanical variant.
- Status: ready (fixed-time range and FVG rules explicit; market mapping assumed).

## JR-02 "First Candle Value": value area of the first 15 minutes, failed acceptance back inside -> fade to the range's far side: sXR8HQyXdhc
"I Found A Secret To The First Candle Rule" (2026-04-09, 22:39), https://youtu.be/sXR8HQyXdhc
- Mark the volume-profile value area (70% of volume) and point of control of 9:30-9:45 New York, on 5 minutes [E 04:00-10:00].
- Two setups: breakout = price leaves the value area, retests it and goes; reversal (higher probability in his data) =
  price trades outside the value area high, then a 5-minute candle closes back inside -> short (mirror at the value
  area low) [E 06:00-12:00].
- Target the first-15-minute range low (where trapped buyers' stops sit); trail the stop to each new candle's high [E 12:00-13:00].
- Needs real volume at price (ATAS / NQ futures) [E 08:00-10:00]. Code [A]: BTC only (Delta minute volumes; gold has no
  real volume); value area from 1-minute bars of 9:30-9:45 NY (each minute's volume at its typical price, 70% around the
  POC); reversal setup only; stop = the extreme outside the value area + 0.1 ATR; target = the opposite edge of the
  15-minute range (at least 1R) with the stop trailed to each closed 5-minute candle's high (low) after 1R; one trade a
  day; exit 16:00 NY.
- Status: ready with documented assumptions (volume profile approximated from 1-minute bars).

## JR-03 First 5-minute candle range, 1-minute FVG break, market entry, stop at the break candle, 2R: mzFXoK2pbNE
"This Scalping Strategy Works Everyday (Stupid Simple And Proven)" (2025-06-16, 11:44), https://youtu.be/mzFXoK2pbNE
- Step 1: high and low of the 9:30-9:35 New York 5-minute candle; "works for stocks, futures, options, forex, crypto"
  [E 01:00]. Step 2: on 1 minute wait for a break that is not just a wick [E 01:00-02:40].
- Step 3: a fair value gap created outside the range by the break; enter as the third FVG candle closes; stop at the base
  of the candle that broke and closed beyond the level; fixed 2R [E 02:40-04:00].
- If the break has no FVG: wait for price to come back to the range; a FVG created away from it then gives the entry,
  stop beyond the original break candle [E 06:00-07:00].
- Code [A]: BTC and XAUUSD 1-minute; both entry paths; first valid setup of the day; setups until 11:00 New York;
  exit 16:00 NY.
- Relation: a variant of JR-01 (5-minute range on 1-minute bars, market entry, break-candle stop) - kept.
- Status: ready with documented assumptions.

## JR-04 9:30-9:35 range, 5-minute close outside, retest candle that closes back outside, stop at the range midpoint, 2R: nBOLIrNX_PU
"The 5 Minute Scalping Strategy (That Actually Works)" (2026-02-17, 14:21), https://youtu.be/nBOLIrNX_PU
- Levels: the first 5-minute candle (9:30-9:35 New York) high and low [E 01:24-02:09, 04:30-05:00].
- Direction: a 5-minute candle body closing fully outside the range; do not chase it [E 02:09-02:30, 05:30].
- Entry: a retest - a candle trades back into the range but closes back outside; enter at that close [E 02:30-03:30, 06:00-07:00].
- Stop just beyond the range midpoint (50% of the first candle); target 2R [E 07:00-08:30].
- His one-month test: 70% winners with the retest vs 33% without [E 12:55-13:00] (claims).
- Code [A]: BTC and XAUUSD 5-minute; first setup of the day; setups until 12:00 NY; exit 16:00 NY.
- Status: ready (all rules explicit; market mapping assumed).

## JR-05 9:30-9:35 range, 1-minute FVG break, pullback into the FVG, engulfing of the retest candle, 3R: 8v-Z5oyKVG0
"The 1 Minute Scalping Strategy (That Actually Works)" (2025-10-05, 14:50), https://youtu.be/8v-Z5oyKVG0
- Levels from the 9:30-9:35 candle; on 1 minute a FVG through the high (low) with at least one of its three candles
  closing beyond the level [E 01:04-04:56].
- Entry: wait for price to pull back into the FVG; then a candle that engulfs the retest candle's body -> enter; stop
  one tick beyond the retest candle; target 3R; no higher-timeframe levels needed [E 04:56-06:50].
- Code [A]: BTC and XAUUSD 1-minute; pullback within 30 bars of the FVG; first setup of the day; exit 16:00 NY.
- Relation: a variant of JR-03 (pullback + engulfing entry, retest-candle stop, 3R) - kept.
- Status: ready (explicit).

### JR-02 second source (merged): Ub_dil32xZY
"The DARK Secret of ORB Trading (Nobody Tells You This)" (2026-05-17, 19:44), https://youtu.be/Ub_dil32xZY
- 15-minute ORB is his preferred range (5- and 30-minute compared) [E 02:46-04:20]. Fakeouts: when liquidity sits just
  outside the ORB, skip the first break, wait for the liquidity to be taken and a candle to close back inside the value
  area, then trade the reversal; stop beyond that candle; target the obvious opposite low / high [E 05:32-11:34].
- Same logic as JR-02 (value-area failure fade) - merged as a duplicate video.

## Jesse Rogers summary
Coded: JR-01 to JR-05. Ub_dil32xZY merged into JR-02.
