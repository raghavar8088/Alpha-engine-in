# Liquidity Sweep (Booming Bulls): rules and test plan, fixed before the first run

**Source.** The Booming Bulls "Liquidity Sweep" video for NIFTY on 5-minute candles, and its 25-page PDF. The PDF has 42 example trades dated 24 Sep 2025 to 19 Oct 2026. The owner shared both on 6 Nov 2026.

**Code.** The strategy is `bb_liquidity_sweep` (D9) in `strategy-service/strategy_service/strategies/options_buying/booming_bulls.py`. The test harness in this folder drives that same class, so the app and this test run the same rules.

This file was written, and its SHA-256 recorded, before any result was seen. Nothing in it changes after the run. A later idea becomes a new, separately labelled run.

## 1. The strategy

### Levels

Each level is marked using only data available at that moment.

| Level | Definition |
|---|---|
| **PDH / PDL** | The previous session's high and low. |
| **PDC** | The previous session's last price. If it is above today's open it acts as a high; if below, as a low. |
| **Equal highs / lows** | Two swing highs (or lows) on the trading chart within 0.04% of each other and at least 3 candles apart, with no trade beyond them in between. Both swings come from the previous or the current session. The level is the outer of the two. |
| **1-hour swings** | A 1-hour candle whose high is the highest of the 2 hourly candles on each side (or whose low is the lowest). Hourly candles are 09:15-aligned and cover 09:15–15:15. |

- A swing on the trading chart is a candle whose high is at least the 2 candles before it and above the 2 candles after it, all in the same session. Lows are the mirror image.
- A level is live until price trades beyond it once. Equal highs/lows and 1-hour swings expire after 5 sessions; PDH/PDL/PDC last for one session.
- At the open, a high below the open or a low above it is dropped, because the gap already took it.
- Same-side levels within 0.04% of each other merge into one level at the outermost price.
- Not used: session highs and lows (the video says to avoid them for India; most likely it means forex sessions), round numbers on their own, and single 5-minute swings.

### Sweep and confirmation

- **Sweep:** a candle trades beyond a level, with its high above a high or its low below a low.
- **Confirmation:** a candle closes back on the original side of the level within 30 minutes of the first candle beyond it. That first candle counts, so it can be the confirming candle itself.
- If 30 minutes pass with no such close, the break was accepted. That is a breakout, and it is not traded: the video says never to trade a direct breakout.
- Each level is used once. Once it is swept, broken, or resolved while a trade is open, it is gone.

### Trade

- A swept high is traded short (buy a PE). A swept low is traded long (buy a CE).
- **Entry:** the close of the confirmation candle.
- **Stop:** the most extreme price since the sweep began, plus a 0.02% buffer.
- **Target:** 2 × risk (1:2).
- The trade is skipped if the risk is below 0.05% or above 0.35% of price. That is about 12 to 85 NIFTY points at 24,000.
- Entries only come from candles that close between 09:20 and 14:45 IST. An open trade is closed at 15:15.
- One trade at a time, and at most 2 a day.
- No new entry on the candle where a trade exits.
- No trade when one candle confirms both a swept high and a swept low.

### Choices the video leaves open, settled here

The video and PDF don't specify any of these. Each value below is mine, chosen before the run and not tuned afterwards.

| Item | Value | Why |
|---|---|---|
| Equal-high tolerance | 0.04% (≈10 pts) | The PDF's equal-high boxes are 5–15 points tall. |
| Swing size | 2 candles each side | The usual fractal swing. |
| Time allowed beyond a level | 30 minutes | The PDF's slowest rejections, 18 Jun and 7 May, take about 20–25 minutes. |
| Stop buffer | 0.02% (≈5 pts) | The PDF's stops sit a few points past the sweep wick. |
| Risk band | 0.05%–0.35% | All 42 PDF trades fall inside it (15–71 points). |
| Trades per day | 2 | The PDF never shows more than 2 on a day. |
| Entry cut-off / exit | 14:45 / 15:15 | Intraday. Since 3 Aug 2026 the index has no minutes between 15:15 and the closing print. |

## 2. Test plan

**Data.** NIFTY 50 index 1-minute candles from Angel One: the index-intraday store, plus the server's daily files to 23 Oct 2026. They are cleaned by that module's own `index_intraday.data._build`, which drops bad prints, days with no morning and short sessions such as Muhurat. 5-minute and 3-minute candles are built from these, aligned to 09:15.

**Runs.** All three are reported and none is chosen afterwards.

- **A, primary:** the rules above on 5-minute candles.
- **B:** A plus a 200-EMA side filter. Longs are taken only above the 5-minute 200 EMA, shorts only below. This is my reading of the video's "200 MA confluence".
- **C:** A on 3-minute candles, since half of the PDF's charts are 3-minute.

**Periods.**

- **P, primary:** 24 Sep 2025 – 19 Oct 2026, the span the PDF's 42 examples come from.
- **F:** 20 Oct 2026 – 23 Oct 2026, the sessions after the PDF that are on disk. These are only for completeness and too few to judge from.
- **H:** 1 Jan 2016 – 23 Sep 2025, every earlier session on disk.

**Fills.**

- The harness takes each entry from the library class's own signal. It then walks the 1-minute candles.
- The stop or target fills when touched. If one minute touches both, the stop is taken first. A minute that opens beyond the stop fills at its open.
- Otherwise the trade exits at 15:15, at the close of the 15:14 minute.

**Costs.** Each trade is costed as one NIFTY futures lot of 65.

- Charges are Angel One's futures charges on the trade date, using the same formula as `angel_fees.futures_round_trip`. STT is 0.05% of the sell side from 1 Apr 2026 and 0.02% before that.
- On top of that, 1 index point of slippage on every fill.
- The spot index stands in for the future.

The app's own Options Buying Lab engine (`run_options_backtest`, synthetic premiums) is also shown for A on P.

**Verdict rule, fixed now.** A counts as working only if both of these hold:

1. In P, the average trade after costs is above 0R with a t-statistic of at least 2.
2. In H, the average trade after costs is above 0R.

Anything else means no demonstrated edge.

**Checks against the PDF.**

1. **Replay.** Each of the 42 PDF trades is run with its own entry, stop and target, from its marked candle, on the 1-minute data.
2. **Replication.** For each PDF trade, check whether the rules took a trade on the same day, in the same direction, within 30 minutes of the PDF's marked time. Run A is used for 5-minute charts and run C for 3-minute charts.
