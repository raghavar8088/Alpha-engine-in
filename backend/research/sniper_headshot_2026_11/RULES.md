# Sniper Headshot Entry: exact rules (bitcoin, Delta Exchange)

Source: Booming Bulls, "Best Intraday Trading Strategy! || Sniper Headshot Entry", https://www.youtube.com/watch?v=jvzd7UPlb5Y
(1 Mar 2025, 21:38). The code is `premium-paper-service/sniper.py`; this file is its readable form and feeds the
strategy cards (`premium-paper-service/build_library.py`). Each rule is tagged **E** when the video states it, **A**
when the video leaves it open and a value had to be chosen. Timestamps point to where the video says it.

Asked for on 8 Nov 2026: the strategy as exact rules, upgraded versions, all paper trading bitcoin in the Premium
Strategies desk's Crypto tab on Delta Exchange's live prices. **Not backtested.** Paper trading is their first test.

**Delta's costs decide most of this.** A round trip at market on Delta India's BTCUSD (0.05% taker fee + 18% GST each
way, 2 bp of slippage each way, half a $1 spread) costs about 0.16% of price. On the 45 days of Delta candles up to
8 Nov 2026, the video's stop (under half the reversal candle's body) was a median 0.044% of price on 5-minute bars, so
costs came to about 3.6R a trade. Moving the stop under the sweep (SH-01) gives about 0.12% and 1.3R. Only the 1-hour
version (SH-04) gets the stop wide enough (about 0.7%, costs about 0.2R). These are properties of the rules and the
fee schedule, not results.

## The video's rules

### SH-00 Sniper headshot entry: the video's rules (jvzd7UPlb5Y)

- **Idea:** skip the obvious trade at a visible support or resistance. Wait for price to run through it and set off the stops resting there, then trade the reversal from the next zone beyond it (E, 01:24-01:51, 05:01-07:22).
- **Market and bars:** bitcoin, Delta Exchange BTCUSD perpetual, 1-minute candles built into 5-minute bars (E: 5 or 15 minutes, 1 minute "very risky", 16:29; bitcoin is one of the markets he names, 16:41).
- **Trend:** buys only while the 1-hour swing structure makes higher highs and higher lows, sells only in the reverse (E: "higher high and higher low", 05:53; A: the 1-hour structure, swings of 2 bars).
- **Support:** a double bottom on 5-minute bars: two swing lows (each the lowest of 2 bars either side) within 0.25 ATR(14) of each other, 3 bars to 6 hours apart, with nothing lower between them. The support is the lower of the two (E: double or triple bottom, two buying points, 06:00-06:24, 13:58-14:05; A: the tolerances).
- **Demand zone:** the nearest earlier swing low below the support, from the last 24 hours and at most 5 ATR below it, drawn from its wick to its body, at least 0.1 ATR thick (E: extend a wick or body, 14:55, 18:35; A: which swing).
- **Sweep:** within 3 hours, a 5-minute low trades below the support. A close above the range high first is a breakout, which the video does not trade (E: 06:41-07:22, 11:37-12:04; A: 3 hours).
- **Zone touch:** within 1 hour of the sweep, price reaches the demand zone (E: 07:44-07:58; A: 1 hour). A close more than 0.5 ATR below the zone ends the setup (A).
- **Reversal candle:** within 30 minutes of the touch, a green 5-minute candle closing above the zone, with a body of at least 0.5 ATR or a pin bar at least 1 ATR long. A touch alone is not an entry (E: "big green candle", 12:22-12:28; no buy on a mere touch, 15:03-15:08; A: the sizes).
- **First entry:** at the next minute's open after that candle closes (E: entry 1, 08:04; A: the next open).
- **Stop:** 40% of the way up the candle's body from its open: under half the body, a little lower (E: 12:39-12:47, 19:31-19:39; A: "a little" = 10% of the body).
- **Target:** 93% of the way to the range high above the double bottom (E: keep the target a little short of the level, 12:49-12:57, 15:39; A: 93%, from his 2.6 of 2.8).
- **Skip:** when the target is less than 1.5x the risk away (A: "very small stop loss and a very big target", 08:09).
- **Second entry:** while the first is open, after a close back above the support, the first green candle that dips to within 0.15 ATR of the support and closes above it. Its stop goes 0.1 ATR under that candle, its target is the first entry's; it is its own position, sized like any other (E: the retest add, 15:50-16:06, 19:56-20:06; A: the distances). One second entry per first entry.
- **Sells:** the mirror: a swept double top, a supply zone above it, a red candle (E: 08:37-10:30).
- **Day:** at most 3 first entries a day, one at a time; everything out by 23:55 UTC, the end of bitcoin's day on this desk (E: about 3 a day, 05:24; A: the day end).
- **Not used:** fair value gaps (named as optional, 02:18) and averaging (promised at 02:23 and 16:09, never explained).

## Upgrades (each changes one thing)

### SH-01 Upgrade: enter on the reclaim of the swept level (jvzd7UPlb5Y)

- **This version:** the first entry waits for a 5-minute close back above the swept support (within 1 hour of the zone touch) instead of the first strong green candle at the zone, and the stop goes 0.1 ATR under the sweep's lowest low.
- **Why:** the reclaim shows the sweep has failed, the way the video's examples turn; the stop sits under the low the stop-run made rather than inside one candle (median 0.12% of price instead of 0.044%).

### SH-02 Upgrade: Delta order-flow confirmation (jvzd7UPlb5Y)

- **This version:** the first entry is taken only when Delta's takers sold more than they bought from the sweep to the candle before the reversal, and bought at least 55% of the reversal candle's volume (mirror for sells). Read from Delta's live trade feed, minute by minute; a minute the recorder did not see whole makes the setup unknown, and no trade is taken.
- **Why:** the video's story is that stops are triggered into a big buyer. Delta's trade feed shows who was aggressive, so the story is checked instead of assumed.

### SH-03 Upgrade: 1-hour 50-EMA trend filter (jvzd7UPlb5Y)

- **This version:** buys only when the last completed 1-hour close is above the 1-hour 50-EMA, sells only below it.
- **Why:** a second, slower trend check on top of the swing structure, so sweeps in a weakening trend are skipped.

### SH-04 Upgrade: built to pay Delta's costs (1-hour bars) (jvzd7UPlb5Y)

- **This version:** the same pattern on 1-hour bars with the trend from 4-hour swing structure (the time windows are the same number of bars), the stop 0.1 ATR under the reversal candle's low (the video's first choice, before he offers half the body for traders who find that stop too big, 15:17-15:30), and no trade whose round-trip cost is more than 40% of its risk.
- **Why:** on 5- and 15-minute bitcoin candles every stop this pattern produces is so close that Delta's taker costs are 1.2-5.6R a trade. On 1-hour bars the stop is about 0.7% of price and costs about 0.2R. Setups are rare (4 in 45 days).
