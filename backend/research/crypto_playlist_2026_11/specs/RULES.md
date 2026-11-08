# Booming Bulls "Crypto Trading" playlist: the strategies as exact rules

Source: the 8 videos of playlist PLHqOiFE9RQj8, read in full from their captions (notes: `../README.md`). The code
(`cp_strategies.py`) is the exact form of these rules. Where a video was vague, the rule below is an assumption (A);
everything else is as stated (E). No strategy here was backtested before paper trading.

**Common to every strategy** (videos qPBdLsiEa3s, Z0T-OWvruGo, lYr7pBtCORs):
- **Target:** 2R, the minimum the videos allow (E).
- **Breakeven:** the stop moves to the entry once price has covered half the way to the target (E).
- **Limits:** at most 2 trades a day, one at a time, none after a stop-loss that day (E: "SL hit, day closed").
- **Timeframes:** gold enters on 5-minute bars and reads its trend on 15-minute bars. Bitcoin enters on 15-minute bars and reads its trend on 1-hour bars (E).
- **Swings:** fractal pivots of 2 bars each side, known 2 bars later (A). A trend is higher high + higher low, or lower high + lower low (E).
- **Candles:** power candle = body at least 70% of the range, range at least the mean of the previous 20 bars (A). Pin bar = wick at least half the candle (A).
- **Exit:** gold by 16:55 New York; bitcoin by 23:55 UTC (A).
- **Paper account:** Rs 10 lakh, 1% of equity at risk per trade, the desk's usual sizing.

### CP-01 Trend pullback at the 5th point (qPBdLsiEa3s, mb0AeY9YyPg)
- **Markets:** Bitcoin and gold.
- **Setup:** the higher timeframe is in an uptrend (points 1-4: low, high, higher low, higher high).
- **Entry:** a bullish pin bar that pulls back below the previous bar's low, into the lower half of the last swing range, above the last swing low (point 5) -> buy at the next open.
- **Stop:** below the pin bar (0.05% of price beyond).
- **Mirror:** in a downtrend, sell a bearish pin bar in the upper half below the last swing high.

### CP-02 Power-candle breakout of the last swing (qPBdLsiEa3s, mb0AeY9YyPg)
- **Markets:** Bitcoin and gold.
- **Entry:** in an uptrend, a power candle closes above the last swing high -> buy. In a downtrend, below the last swing low -> sell.
- **Stop:** the far end of the breakout candle.
- **Note:** the "N-shape" of video mb0AeY9YyPg (low, high, higher low, then the break) is the uptrend condition itself.

### CP-03 Range ping-pong and range breakout (qPBdLsiEa3s, mb0AeY9YyPg)
- **Markets:** Bitcoin and gold.
- **Range:** the last 20 higher-timeframe bars, at most 4 ATRs tall, with at least 3 bars touching the top 10% and 3 touching the bottom 10% (E: "3-4 touches"; A: the numbers).
- **Fade:** a bearish pin bar at the top that closes back inside -> sell, target the other side (only if that is at least 2R). Mirror at the bottom.
- **Breakout:** a power candle closing outside the range -> trade the break, 2R.

### CP-04 Trend-line rejection (qPBdLsiEa3s)
- **Market:** Bitcoin.
- **Line:** through the last two falling swing highs of the 1-hour chart (A); the latest hourly close is still below it.
- **Entry:** a 15-minute candle reaches the line and closes back below it, red -> sell. Mirror: a line through two rising swing lows, green close back above -> buy.
- **Stop:** beyond the candle (0.1%).

### CP-05 Turning-point zones (mb0AeY9YyPg, his core method)
- **Market:** gold.
- **Zone:** three 5-minute turning points whose zones (body to wick) overlap, within the last 300 bars (E: "2 OK, 3 best").
- **Entry:** the next touch: a pin bar that rejects the zone and closes beyond its near edge -> sell at resistance / buy at support.
- **Bias:** with the 15-minute trend; both directions when it is flat (E).
- **Stop:** a quarter ATR beyond the zone (E: "do not make the stop tight").

### CP-06 Triple top / triple bottom (mb0AeY9YyPg)
- **Market:** gold.
- **Pattern:** three swing highs within a quarter ATR of each other, at least 3 bars apart, within 150 bars (E: "triple, not double"; A: tolerances).
- **Entry:** once the third top is confirmed, if price is still within 1.5 ATR of it -> sell. Mirror for bottoms.
- **Stop:** just above the highest top.

### CP-07 Head and shoulders / inverted (mb0AeY9YyPg)
- **Market:** gold.
- **Pattern:** three swing highs, the middle at least half an ATR above the others, shoulders within half an ATR (A).
- **Entry:** the first close below the lower trough (neckline) within 24 bars -> sell. Mirror for the inverted pattern.
- **Stop:** above the right shoulder.

### CP-08 Flag and pole (mb0AeY9YyPg)
- **Market:** gold.
- **Pole:** a 6-bar move of at least 2.5 ATR (A).
- **Flag:** at least 4 bars, no taller than half the pole, retracing no more than half of it (A).
- **Entry:** a close beyond the flag in the pole's direction, within 15 bars -> trade it. Stop beyond the far side of the flag.

### CP-09 Trap of a swing level (mb0AeY9YyPg: "the best strategy of all time")
- **Market:** gold.
- **Trap:** a strong candle (body at least 60%) closes beyond the last 15-minute swing high or low.
- **Entry:** within 3 bars a candle closes back inside, coloured against the break -> trade against the break. Stop beyond the trap's extreme.

### CP-10 Retest of a broken level (mb0AeY9YyPg)
- **Market:** gold.
- **Break:** a power candle closes beyond the last 15-minute swing level.
- **Entry:** within 24 bars price returns to the level and a candle rejects it in the break's direction -> enter. Stop beyond the retest.

### CP-12 Current-day high/low sweep (IOBoaM71MUA)
- **Market:** gold.
- **Condition:** the day's range so far is at least 75% of the daily ATR(14) (E: "ATR minus 20-30%").
- **Entry:** a 5-minute candle trades beyond the day's high or low and closes back inside -> trade the reversal. First one each day.
- **Stop:** 0.07% beyond the sweep (E: "past the round number").
- **Related:** the previous-day sweep of the same video already trades as BB-07.

### CP-13 15-minute order block entered on a 5-minute FVG (IOBoaM71MUA)
- **Market:** gold.
- **Order block:** the first candle of a 15-minute fair value gap, at the lowest low (buys) or highest high (sells) of the previous 20 bars (A: video 37uPX6Li-xE's definition).
- **Entry:** once price returns into the block, the next 5-minute fair value gap in the trade's direction: a limit order at the gap's edge, valid 12 bars.
- **Stop:** beyond that gap (E: "drop to 5 minutes and use the FVG when the stop is too wide").

### CP-14 Order-flow absorption (ieZ--wMeSxE)
- **Market:** Bitcoin (E: "it works in bitcoin too"; real taker volume from Binance, delta = taker buy minus taker sell).
- **Trap candle:** at the 6-hour high, a 15-minute candle with positive delta but a bearish result (red, or an upper wick at least half the candle).
- **Entry:** the next candle closes below its low, red with negative delta -> sell. Mirror at the 6-hour low.
- **Stop:** beyond the trap candle.

### CP-15 Delta-filtered morning / evening star (ieZ--wMeSxE)
- **Market:** Bitcoin.
- **Pattern:** a large candle (body at least 60%), a small star (body at most 30% of it), then a candle closing past the first one's midpoint.
- **Filter:** at the 6-hour extreme, the star's delta shows the trapped side (negative for a morning star, positive for an evening star).
- **Stop:** beyond the star.

### CP-16 ICT previous-day / previous-week high-low sweep (37uPX6Li-xE)
- **Market:** gold.
- **Levels:** the previous day's and the previous week's high and low (external range liquidity).
- **Entry:** a 5-minute candle wicks beyond a level and closes back inside -> trade back into the range. Each level once a day, any hour.

### CP-17 Fair value gap, third touch (37uPX6Li-xE)
- **Market:** gold.
- **Gap:** a 5-minute fair value gap in the discount half (buys) or premium half (sells) of the 15-minute dealing range (E: premium / discount).
- **Entry:** the first two touches are not traded; the third must run past both and close back on the gap's side -> enter (E: "trust it after it has held twice").
- **Stop:** beyond the third touch.

### CP-18 Order block at its 50% (37uPX6Li-xE)
- **Market:** gold.
- **Order block:** the first candle of a 5-minute fair value gap (E: "only blocks that leave a gap"), in the discount (buys) or premium (sells) half of the 15-minute dealing range.
- **Entry:** a limit order at the block's middle (E: "the right half of the block"), valid one day.
- **Stop:** beyond the block.

### CP-20 Inverse fair value gap (37uPX6Li-xE)
- **Market:** gold.
- **Entry:** a fair value gap that price closes through is retested from the other side within 48 bars, and a candle closes away from it -> trade in the break's direction. Stop beyond the gap.

### CP-21 Breaker block (37uPX6Li-xE)
- **Market:** gold.
- **Entry:** an order block that price closes through is retested within 48 bars and rejected -> trade in the break's direction. Stop beyond the block.

### CP-22 CISD after a liquidity sweep (37uPX6Li-xE)
- **Market:** gold.
- **Sweep:** a 5-minute candle wicks beyond the last 15-minute swing and closes back inside.
- **Level:** the body of the first opposite-coloured candle of the move into the sweep (E).
- **Entry:** a close beyond that body within 12 bars -> enter. Stop beyond the sweep.

### CP-23 Inducement (37uPX6Li-xE)
- **Market:** gold.
- **Setup:** after a 5-minute close beyond the last swing high (a break of structure), the swing low before it is the inducement.
- **Entry:** wait until price sweeps below it, then buy the first green close back above it, within 48 bars. Mirror for sells.
- **Stop:** below the sweep.

### CP-24 SMT divergence (37uPX6Li-xE)
- **Markets:** gold against silver (E: his first example), EUR/USD against GBP/USD (E).
- **Entry:** the traded market makes a higher high while its partner makes a lower high -> sell; a lower low against a higher low -> buy.
- **Stop:** beyond the new extreme.

### CP-25 Optimal trade entry 0.705-0.79 (37uPX6Li-xE)
- **Market:** gold.
- **Leg:** a 15-minute impulse from a swing low to a swing high of at least 3 ATR.
- **Entry:** a limit order at the 0.705 retracement (the top of the 0.705-0.79 zone), valid 8 hours. Stop below the leg's start.

### CP-26 Turtle soup (37uPX6Li-xE)
- **Market:** gold.
- **Entry:** a 5-minute candle wicks beyond the 20-bar high or low and closes back inside -> trade against it. Stop beyond the wick.

### CP-27 Unicorn model (37uPX6Li-xE)
- **Market:** gold.
- **Steps:** a sweep of the last 15-minute swing; within 12 bars a displacement candle (range at least 1.5x the average) that breaks the last 5-minute swing (structure shift); the fair value gap it leaves.
- **Entry:** a limit order at that gap, valid 24 bars. Stop beyond the sweep.

### CP-28 Silver bullet (37uPX6Li-xE)
- **Market:** gold.
- **Rule:** the unicorn model, only when the gap forms between 19:30 and 20:30 IST; the order expires at 20:30.

### CP-29 Fear & Greed accumulation (qPBdLsiEa3s)
- **Market:** Bitcoin, spot, no leverage.
- **Rule:** every Monday that the Crypto Fear & Greed Index is below 45 (fear or extreme fear), buy Rs 25,000 of Bitcoin at that day's open (A: the amount and day). Never sell (E: "hold for years").
- **Account:** the Rs 10 lakh is invested 40 buys at a time; what is not yet invested stays as cash.
