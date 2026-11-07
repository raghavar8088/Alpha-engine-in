# Channels 5–8: Power of Stocks, Warrior Trading, Ghanshyam Tech, Wysetrade

Read as **rule digests** of the Video Explainer transcripts. Tags: **E** = stated or shown, **I** = inferred.

## #5 Power of Stocks, Subasish Pani (2.15M subscribers, Hindi with English subtitles)

### fBTMspiqjS4, "5 EMA The only Trading Strategy You Need" (23:35, 1.8M views)

| Rule | Type | Evidence |
|---|---|---|
| One indicator: the **5 EMA**. **Sell on the 5-minute chart, buy on the 15-minute chart** | E | 03:00 |
| **Alert candle (sell):** a candle that closes above the 5 EMA with neither its body nor its wick touching the EMA | E | 03:00, 04:00 |
| **Entry:** the next candle breaks the alert candle's low → sell; stop = the alert candle's high | E | 03:00 |
| If the next candle doesn't break and stays clear of the EMA, it becomes the new alert candle | E | 03:30 |
| **Buy:** the same on 15-minute candles closing below the 5 EMA without touching it | E | 04:00 |
| **Target:** "if we lose 10 rupees, think of earning 30" (1:3, matching Pushkar Raj Thakur's restatement) | E | 06:30 |
| Don't change the rules (no 4 EMA, no 3-minute variants); small stops, big profits | E | 06:30 |
| Larger size when the setup forms at a breakout/range level; discretionary | E | 16:30, 21:30 |
| Market: Nifty / Bank Nifty (examples in Bank Nifty points) | E | 21:30 |

**Testability: ready to test.** Spec **YT-01**: Nifty and Bank Nifty, 5-minute sells and 15-minute buys, target 3R. The size rule is not modelled.

### 42J_foitsdI, "Intraday Trading Strategies – Inside Candle" (13:20, 1.4M views)

| Rule | Type | Evidence |
|---|---|---|
| A big **mother candle** followed by a **baby (inside) candle** | E | 09:00–09:30 |
| **Sell:** when the inside candle's low breaks, sell one unit; when the mother candle's low breaks, sell another. Stop above the **inside candle's high** | E | 09:30–10:00 |
| **Target:** the mother candle's range projected from the break | E | 09:00 |
| Re-entry allowed after a stop | E | 09:30 |
| Timeframe **15 minutes minimum** (best for intraday); stocks; a viewer's journal shows 70–75% accuracy | E | 02:30, 10:00 |
| Buy side: the mirror | I | — |

**Testability: testable with documented assumptions** (one entry at the inside-candle break, the second unit as a variant). Spec **YT-08**:
- NSE stocks, 15-minute, two years on disk. Caveat: today's liquid universe, so survivorship bias.
- Nifty and Bank Nifty.

### djC2hSdNo74, "Traffic Light Strategy" (25:58, 1.0M views)

| Rule | Type | Evidence |
|---|---|---|
| Scalping on the **1-minute** chart; **ignore the 09:15–09:16 candle** (5- or 15-minute charts keep it) | E | 02:00, 03:00, 15:00 |
| Look for a **pair: a red candle and a green candle** (either order) | E | 03:00, 15:30 |
| Trade the break of the pair; stop at the other side of the pair (example: entry 298, stop 268 on the option) | E | 09:30 |
| If the pair's range is more than 100 points, ignore it and wait for the next pair | E | 17:00–18:00 |
| Entry and exit details are promised for a later video | E | 02:00 |

**Testability: testable with documented assumptions:**
- the first qualifying pair of the day;
- a break of the pair high → long, the pair low → short;
- target 2R;
- Bank Nifty points.

Spec **YT-09**: Bank Nifty and Nifty, 1-minute.

## #6 Warrior Trading, Ross Cameron (2.12M subscribers, English)

### 5X_ZcifasBg, "The Simplest Day Trading Strategy for Beginners" (18:28)

- **Universe:** the day's leading percentage gainers, the "2020 rule": float under 20M shares, price under $20, a catalyst (E 00:30, 11:30).
- **Entry:** the first 5-minute pullback to VWAP / the 9 EMA, buying the first candle to make a new high (E 14:30–15:00).
- **Unable to evaluate:** no US small-cap intraday data. Picking the top gainers requires the whole market's tape.

### mfGQr2tHoX0, "How I Nailed Trading with the MACD Indicator" (21:58)

- MACD at default 12/26/9 on 1- and 5-minute charts (E 06:00).
- Trade the front side while MACD is open; stop trading once it crosses down (E 15:00).
- It is a filter on the same small-cap momentum trades. **Unable to evaluate** (same data).

## #7 Ghanshyam Tech (1.54M subscribers, Hindi)

### 8X67v5NfY6I, "Best LDHCL Strategy Level For Expiry Day" (6:55)

**What he says:**
- Bank Nifty levels for the next (expiry) day from the previous day's high, close and low (E 01:30, 04:30).
- If the day closed inside the previous day's range, trade half size the next day (E 04:30).
- If it opens above a level and crosses it → buy, with targets about +100 and +150 points. A break below the level → sell (E 05:00–05:30).
- After a 1.5–2 hour range of 100–150 points, trade its breakout (E 05:00).

**Testability: insufficiently defined.** The levels are hand-picked for one day, and there is no stop rule. Its previous-day-high/low core is covered by the earlier BB-01 study.

### 3v9nvXaW0QQ, "Nifty Opening SETUP" (7:04)

| Rule | Type | Evidence |
|---|---|---|
| Normally follow price after the open, gap or not | E | 05:00–06:00 |
| **A big gap up** with a **shooting-star first candle** → look for sells until price trades above that candle | E | 06:00 |
| **A big gap down (about 150 points)** with a **hammer first candle** (15- or 5-minute) → buy, risking below it | E | 06:00 |

**Testability: testable with documented assumptions:**
- gap at least 0.5% (about 120–150 Nifty points);
- shooting star / hammer = a wick at least twice the body, with the opposite wick at most 25% of the range;
- entry on the break of the candle;
- stop beyond its far side;
- target 2R.

Spec **YT-10**: Nifty and Bank Nifty.

### Nyc8KXziAQU, "MY Golden Rules of IntraDay Trading" (12:30)

Money management only:
- never average a loser; cut losses fast;
- never sell strong stocks or buy weak ones;
- don't let a winner turn into a loser: book half and trail the rest.

**Not a strategy.**

## #8 Wysetrade (1.53M subscribers, English)

### jdYNaE5GJ0k, "Best Moving Average Trading Strategy" (14:55)

- **Trend:** the 50 EMA defines it (price above = bullish, E 01:30).
- **Reaction:** price reacts at a key level plus the 50 EMA (E 02:30, 04:30).
- **Trigger:** the entry needs a lower-timeframe **trendline break** closing outside the line (E 05:30, 11:30).

**Insufficiently defined:** trendlines are drawn by eye.

### 4dVB_g5YeSE, "Best RSI Indicator Trading Strategy – Wysetrade Method" (44:02)

- RSI divergence at a key level, in three variants (E 18:00). One looks inside long-wick candles at a key level for divergence on the lower timeframe (E 23:00–24:30).
- The confirmation is a momentum candle breaking a trendline (E 24:30).
- **Testable only with research assumptions:** key levels, trendlines and divergence pivots would all be my definitions. Low fidelity; not prioritised.

### asDBegQaupM, "Best Price Action Trading Strategy That Will Change The Way You Trade" (9:30, 3.4M views)

| Rule | Type | Evidence |
|---|---|---|
| Identify a **key level** first: where price reversed before (support/resistance, double top) | E | 00:00, 02:30 |
| **Momentum loss:** candles get smaller and smaller as price approaches the level | E | 00:30–01:00 |
| **Trigger:** a long-wick candle rejecting the level, or an inside bar / doji | E | 01:00–01:30, 08:00 |
| **Avoid** large candles approaching the level (momentum, likely to break) | E | 05:00–05:30 |
| Examples on forex pairs; entry "through the intraday timeframe" | E | 07:30 |

**Testability: testable with documented assumptions:**
- key level = the latest confirmed swing high/low on 4-hour bars;
- momentum loss = three consecutively smaller candle ranges on the approach;
- trigger = a rejection candle closing back on the near side with a wick at least half its range;
- stop beyond the wick;
- target 2R.

Spec **YT-11**: EURUSD, GBPUSD and gold, 1-hour.
