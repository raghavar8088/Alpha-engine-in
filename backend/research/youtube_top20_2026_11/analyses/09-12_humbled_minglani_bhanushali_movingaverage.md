# Channels 9–12: Humbled Trader, Sunil Minglani, Siddharth Bhanushali, The Moving Average

Read as **rule digests** of the Video Explainer transcripts. Tags: **E** = stated or shown, **I** = inferred.

## #9 Humbled Trader, Shay Huang (1.50M subscribers, English)

### IWk9kf2wQJo, "VWAP Trading Strategies for Day Trading Beginners" (12:09)

**Only indicators:** VWAP and volume (E 00:00).

| Setup | What she does | Evidence |
|---|---|---|
| VWAP-cross long | A beaten-down stock crosses above VWAP **with volume** | E 01:30–02:00 |
| VWAP hold | A pullback on falling volume that holds above VWAP; the stop goes "some room beneath VWAP", never on it | E 03:00 |
| Short trap | A stock kept under VWAP on low volume, then reclaims it → short squeeze | E 05:30–06:30 |
| VWAP rejection short | Price fails at VWAP and breaks down | E 08:30 |

**Unable to evaluate:** the setups are for US small caps and large caps and need their tape. Related VWAP rules from another channel were already tested on NSE stocks (`D:\NSE-Intraday-Research\vwap`), with no edge.

### Jh5rJskkEkU, "ChatGPT AI Made Me A TRADING STRATEGY" (21:12, 1.8M views)

**The rules ChatGPT wrote for her** (E 05:30, 10:00, 16:30):
- Long when price crosses above VWAP, short when it crosses below.
- Take profit at 3%, stop at 1%.
- Tested in TradingView's strategy tester on US stocks.

**Her own verdict:** profitability changes completely from stock to stock (E 18:00).

**Not tested:** US stocks on an unstated chart timeframe; it is a demonstration, not her strategy.

## #10 Sunil Minglani (1.38M subscribers, Hindi; interview format)

Two of his four picked videos have **no captions**: EE3AftNnVNk "best simple intraday strategy" and uy7GXqCmhNY "favourite indicator". F9W8clfvp2k has none either. Without Whisper they cannot be read.

### 9FCmraBvyVc, "Jackpot Pattern" (16:45)

- "The pattern that works is a lottery; the pattern that **fails** is the jackpot" (E 07:00).
- When a well-known pattern (for example head-and-shoulders) breaks and then reverses, the traders who acted on it are trapped and won't reverse, so trade the reversal (E 06:30–07:30).
- **Insufficiently defined:** patterns are drawn by eye. The idea is a failed-breakout trap, the same mechanism as the trap strategies tested in the Booming Bulls study (none worked).

### hvG7tOqhUgo, "Nine Golden Rules for Intraday Trading" (21:41, 3.0M views)

**Discipline rules** (E 09:00–16:00):
- the "double trade rule": the stop-loss order goes in with the entry;
- exit at the planned target;
- never average a loser;
- ignore noise.

**Not a strategy.**

## #11 Siddharth Bhanushali (1.25M subscribers, Hindi/English mix)

### 0igedWz9xD0, "Intraday Trading Strategy" (38:15, 6.3M views)

| Rule | Type | Evidence |
|---|---|---|
| The night before (about 21:30), shortlist stocks standing on or near the **44 moving average** | E | 10:30, 24:00 |
| His example: "a **bullish candle at the 44 moving average** on 6 April; **buy above the high, stop below the low, target 1:2**" | E | 14:00 |
| Intraday on 5- or 15-minute ("your choice"): the **first or second candle must be a big green candle** → buy above its high, stop below its low | E | 10:30–11:30 |
| **Target 1:2** (entry 100, stop 95, target 110) | E | 11:30–12:00 |
| **Size:** quantity = risk per trade ÷ (entry − stop) | E | 19:00–21:00 |
| The 44 MA itself is taught in a separate playlist (period 44; simple MA assumed) | E / I | 14:00 |

**Testability: testable with documented assumptions.** Two specs:
- **YT-12a, daily swing:** on the daily chart, a rising 44-day SMA; a green candle whose low touches or comes within 1% of the 44 SMA and closes above it. Buy above its high the next day (stop order), stop below its low, target 2R. Run on the NSE stock universe from daily bhavcopy, which includes stocks delisted later.
- **YT-12b, intraday:** the stock's previous close is within 2% of a rising 44-day SMA. The first or second 15-minute candle is a big green candle (range at least 1.5× the stock's 20-day average 15-minute range). Buy above its high, stop below its low, 2R, square off at 15:15. Run on the two years of NSE 15-minute bars (today's liquid universe, so survivorship bias).

### 1e4-gkQnhQs, "Intraday Trading strategy Secret" (17:36)

**Filters:**
- don't trade against Nifty's direction on the same timeframe (E 01:00–03:30);
- don't buy after the stock has already used its average true range upward, or short after it has used it downward (E 09:00, 13:30).

They are used as **declared variants** of YT-12b, not as a strategy of their own.

### EIA095N86Vk, "Price Action Trading – Bull trap / Bear trap" (30:29)

| Rule | Type | Evidence |
|---|---|---|
| **Bear trap:** price breaks down below support; the next day a **big white (green) candle** forms → buy above its high, stop below its low | E | 11:00, 15:30–16:30 |
| **Target:** twice the candle's height (entry 100, stop 90, target 120), i.e. 2R | E | 11:30 |
| **Bull trap:** price breaks out above resistance; next day a **big black candle** → short below its low, stop above its high, target 2× its height | E | 22:30, 27:00 |
| A failed breakout can also be a "stop and reverse" signal | E | 19:30 |
| Daily candles ("next day"); stocks and indices | E / I | 11:00 |

**Testability: testable with documented assumptions** (daily):
- support/resistance = the 20-day closing low/high;
- a "big" candle = range at least 1.5× the 20-day average range.

Spec **YT-13**: NSE stocks (bhavcopy) and Nifty.

## #12 The Moving Average, "Artie" (1.14M subscribers, English)

### wbfXaqjIrJ0, "5 Minute Scalping Strategy **HIGHEST WIN RATE**" (15:10, 2.7M views)

| Rule | Type | Evidence |
|---|---|---|
| 5-minute chart; **21, 50 and 200 smoothed moving averages** | E | 04:30 |
| **Trend:** longs only above the 200, with the 21, 50 and 200 lined up and rising ("fanned out"); shorts the mirror | E | 04:30–05:00 |
| **Signal:** a bullish **engulfing candle** or a **three-line strike** (three bearish candles, then one bullish candle engulfing all three); counter-trend signals are ignored | E | 05:30–06:00 |
| **RSI above 50** and rising for longs (below 50 for shorts) | E | 06:00–06:30 |
| **Entry:** at the close of the signal candle | E | 12:00 |
| **Stop:** twice the length of the entry candle (or the swing low) | E | 08:00, 12:00 |
| **Target:** a fixed 1:2, set on every trade | E | 08:00, 12:00 |

**Testability: ready to test** (smoothed MA = Wilder's RMA). Spec **YT-14**: EURUSD, GBPUSD and gold, 5-minute.

### oDOCBTYgCQM, "XAUUSD Scalping Strategy" (9:55)

- The same framework on **gold, 5-minute** (E 03:00–03:30):
  - 21/50/200 smoothed MAs fanned out, with no trades when they are "smashed together";
  - RSI vs 50.
- **Entry:** after price crosses the 200 and retests a moving average, a three-line strike or an engulfing candle covering at least 50% of the move (E 04:00–04:30).
- **Stop:** usually double the engulfing candle; in his example, $2 (E 04:30–05:00).
- **Exit:** on an RSI divergence or consolidation (discretionary, E 05:00–06:30).

**Treatment:** YT-14 on gold, with the 2R exit of the 5-minute video; the discretionary exit is not modelled.

### MK47z07tGNM, "Best Scalping Strategy Period" (11:56)

| Rule | Type | Evidence |
|---|---|---|
| **21, 50 and 200 moving averages aligned** (all rising, price above) → only buys; the mirror for sells | E | 04:30–05:00 |
| **Entry:** the first **Williams fractal** signal after the alignment, once its candle has closed; enter at the candle's top or bottom | E | 05:00–06:00 |
| **Stop:** below the low of the candle that printed the fractal | E | 06:00 |
| **Target:** 10 pips (example: 5.9-pip stop, 10-pip target on GBPJPY, 5-minute) | E | 07:00 |
| **RSI above 50** for buys, below 50 for sells | E | 07:00, 10:30 |
| **Management:** at +10 pips move the stop to +1–2 pips, or take 80% off and trail on the 21 | E | 08:00, 10:30 |

**Testability: ready to test**, with the fractal used only once confirmed (two bars later). Spec **YT-15**: EURUSD and GBPUSD (no GBPJPY on disk), 5-minute, 10-pip target.
