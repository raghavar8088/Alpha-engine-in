# Channels 13–16: Adam Khoo, Wealth Secret, Elearnmarkets, The Secret Mindset

Read as **rule digests** of the Video Explainer transcripts. The two Secret Mindset videos with missing exit rules were read in full. Tags: **E** = stated or shown, **I** = inferred.

## #13 Adam Khoo (1.11M subscribers, English)

### lHhtVfeoCdQ, "Trade Like a Casino Part 2: Creating a Profitable Stock Trading System" (28:17)

| Rule | Type | Evidence |
|---|---|---|
| **Risk 1R to make 2R:** the profit target is always double the stop distance | E | 05:30 |
| Enter only when the odds are at least 50%, using trend + price action; expectancy = win% × avg win − loss% × avg loss | E | 06:00, 08:30 |
| **Trend:** the 50 MA above the 150 MA (uptrend) | E | 14:00 |
| **Entry:** price pulls back to the key moving average and bounces with a candlestick pattern → buy. "Over-stretched" moves far from the MA snap back | E | 14:00–14:30 |

### MVI7Jm_abrg, "The Most Powerful Forex Trading Indicator" (25:57)

| Rule | Type | Evidence |
|---|---|---|
| Three entry types: trend retracements, breakouts, reversals; he trades retracements | E | 00:30 |
| **Retracement:** in an uptrend (higher highs and lows), price dips to support at a moving average (the 50 MA in examples), then a **bullish engulfing or pin bar** → buy | E | 03:30–06:30 |
| **Stop:** below the candle; **target: always 2R** ("risking 8 pips to make 16") | E | 24:00–24:30 |
| **Currency-strength filter:** buy strong vs weak currencies; timeframes 15m, 1h and 4h | E | 13:30 |

**Testability: testable with documented assumptions.** Spec **YT-16**, shared by both videos:
- uptrend = 50 MA > 150 MA, both rising over 5 bars;
- pullback = a bar whose low touches the 50 MA;
- trigger = a bullish engulfing or a pin bar (lower wick at least 2× the body) closing above the 50 MA;
- stop below the trigger's low, target 2R;
- mirror for shorts.

Markets: EURUSD and GBPUSD (1-hour), and the S&P 500 and Nasdaq 100 (daily). The currency-strength filter is omitted: it needs a currency-strength table that isn't defined.

## #14 Wealth Secret (1.08M subscribers, Hindi)

### J9mz71XaF3I, "Finding Every Breakout & Breakdown Trade, BankNifty" (17:54)

- Enter 50% of the size on the break of a level and add 50% on the retest with a confirming red candle. Never average against the move (E 04:30–06:30, 12:00).
- Stop above the broken level; morning moves of 150–200 points (E 01:30).
- **Levels are drawn by hand: insufficiently defined.** The breakout-retest mechanism is covered by YT-17.

### oEc3_vjg6PE, "Pullback Setup to Identify Fake Breakouts" (17:41)

| Rule | Type | Evidence |
|---|---|---|
| Don't enter the running (breakout) candle; wait for the **pullback**: after a range break, an opposite-colour candle, then continuation | E | 07:00–07:30, 09:30 |
| **Entry** on the continuation after the pullback; **stop below the pullback candle** (above it for shorts) | E | 07:30, 14:00 |
| The pullback keeps the stop small (about 20 Bank Nifty points) | E | 17:00 |

### QqQLqWMjcsc, "Effective Pullback Strategy for Options Trading" (13:17)

- The same rule: never enter in the running candle; always wait for a pullback (E 04:00–10:00).
- **5-minute** chart for intraday options; 15-minute pullbacks are rarer with bigger stops (E 10:00–11:00).

**Testability: testable with documented assumptions.** Spec **YT-17**:
- the range = the first 30 minutes (09:15–09:45);
- after a 5-minute close beyond it, the first opposite-colour candle is the pullback;
- buy when a later candle breaks the pullback candle's high, stop below its low;
- target 2R; one trade a day.

Markets: Bank Nifty and Nifty on futures. The videos trade options, which can't be evaluated here.

## #15 Elearnmarkets (1.02M subscribers, Hindi; "Face2Face" guest traders)

### bj6hVKjweZ8, "Nifty and BankNifty Systematic Trading Rules", with Vishal Mehta (1:27:58)

Read from the video's **human-made English subtitles**. The app's default Hindi auto-captions were garbled, so it was re-run with `--lang=en`.

| Rule | Type | Evidence |
|---|---|---|
| Rule-based trading; don't over-optimise moving-average parameters; forward-test before going live | E | 01:30, 16:30 |
| Stops must respect volatility: about 2–3 × ATR | E | 34:30 |
| **System:** Bank Nifty weekly options, **5-minute** chart, **Supertrend (10, 3)** on Bank Nifty futures | E | 37:00 |
| **From 09:20** (wait for the first 5 minutes): if futures are above the Supertrend (positive or crossing up) → **sell a put**; mirror → sell a call | E / I | 37:00 |
| **Initial stop:** 50% of the premium on Wednesdays, 100% on expiry Thursday | E | 38:30–39:30 |
| **Trailing stop:** a close above the Supertrend value on the short option's chart | E | 39:30–44:30 |

**Testability:**
- **Option selling: unable to evaluate** (no intraday option prices).
- **Spec YT-19, a research proxy:** the same Supertrend signal on Bank Nifty futures. Entry at 09:20 in the Supertrend direction, exit when the Supertrend flips or at 15:15. It tells whether the direction signal has value; it is **not** the video's option P&L.

### dwuTRDcsgDg, "Profitable Options Trading using CPR Pivot System", with Gomathi Shankar (1:11:34)

The only caption track is a Hindi auto-transcript of speech that isn't Hindi: unreadable. **Unable to extract** (would need Whisper).

## #16 The Secret Mindset (997K subscribers, English)

### 7XhVy9z5SbM, "The '3-EMA' 1-Minute Forex Scalping Strategy" (10:30)

| Rule | Type | Evidence |
|---|---|---|
| **1-minute** chart; **EMA 50, 100 and 150** (EURJPY example; also DAX and Dow) | E | 01:00, 07:00 |
| **Trend:** all three EMAs aligned, nearly parallel, sloping about 45° | E | 01:30–02:00 |
| **Pullback:** price tests the 50 or 100 EMA. It may close beyond the 50, but not beyond the 100 or near the 150 | E | 04:00 |
| **Entry:** price closes back beyond the 50 EMA in the trend direction (traps the traders who sold the break of the 50) | E | 04:30, 06:30, 07:30–08:00 |
| **Stop:** beneath the low of the bar that tested the 50/100 EMA | E | 07:00 |
| **Management:** breakeven at +5–6 pips; or a trailing stop, a fixed target, or the next level | E | 05:00–05:30 |

**Testability: ready to test.** Spec **YT-20**: EURUSD and GBPUSD (EURJPY isn't on disk), 1-minute.
- V0 = breakeven at +5 pips with a 2R target (A).
- Variant = a fixed 1.5R target with no breakeven.

### Ci1hKIHL9VY, "Heiken Ashi CHEAT Strategies For Scalping & Day Trading" (10:10)

| Rule | Type | Evidence |
|---|---|---|
| Heikin-Ashi colour changes mark trend turns; no lower wicks = a strong uptrend | E | 02:00, 06:30 |
| **Strategy 1:** buy when the HA candle turns red→green on **two consecutive timeframes**; sell on green→red | E | 04:30 |
| **Strategy 2:** buy when the HA candle turns red→green **and RSI is above 50**; sell on green→red with RSI below 50 | E | 06:00 |
| **Strategy 3:** the same with the Ichimoku cloud | E | 09:00 |
| Exit: not stated (the opposite colour change, I) | I | — |

**Testability: testable with documented assumptions** (exit on the opposite HA colour change; protective stop at the signal bar's extreme; timeframe 15-minute, with 1-hour as a variant). Spec **YT-18** (strategy 2): EURUSD, GBPUSD and gold.

### 2G9fHBEsauE, "Bollinger Bands Strategies THAT ACTUALLY WORK" (11:15)

| Rule | Type | Evidence |
|---|---|---|
| Bands (20, 2) by default; he prefers wider bands (2.5–3 SD) for fewer, higher-probability signals | E | 02:00, 03:30–04:00 |
| **Ranges:** buy near the lower band and sell near the upper band when the bands are parallel, preferably at support/resistance | E | 05:30–06:30 |
| **Trends:** don't fade a trend; buy the lower band only in uptrends (higher highs and lows), sell the upper band only in downtrends | E | 07:00–07:30 |
| **Squeeze:** narrow bands precede a breakout; trade it when the upper band hooks up and the lower band hooks down | E | 08:30–10:00 |

**Testability: testable with documented assumptions** (parallel bands = the 20-period width's slope within ±5% over 10 bars; the exit is the middle band, the usual mean-reversion exit the video mentions at 04:00). Spec **YT-21**:
- the range fade with 2.5 SD bands;
- exit at the middle band, stop 1 × ATR(14) beyond the entry;
- 15-minute, EURUSD and GBPUSD.
