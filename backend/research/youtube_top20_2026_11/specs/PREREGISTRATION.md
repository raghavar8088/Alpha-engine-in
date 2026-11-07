# Pre-registration: YouTube top-20 strategies (Phases 4, 6, 7, 8)

Written 7 Nov 2026, before any backtest of these rules. Its SHA-256 (LF line ends) is recorded in `PREREG_HASH.txt` and stamped into every result file. Changes after a run go in the change log with a new hash.

**Sources and tags**
- Sources: `../analyses/`, summarised in [LIBRARY.md](LIBRARY.md). The code (`yt_strategies.py`) is the exact form of the rules below.
- **E** = stated in a video, **I** = inferred, **A** = my research assumption.
- **V0** = the source-faithful version; **S** = settings the video names; **R** = research additions, not attributed to the channel.

## 1. Execution (`yt_engine.py`: the Booming Bulls engine, extended)

**Signals and rows**
- Signals are computed on completed bars and stamped with the bar's last row.
- Rows are 1-minute bars for index, FX, gold and US index markets; 5-minute bars for NSE stocks; one row a day for daily markets.

**Order types**
- **Market entries:** the open of the next row, buying at the ask and selling at the bid, plus slippage.
- **Stop-entry orders** ("enter when the alert candle's low breaks"):
  - they fill on the first row whose ask high (bid low) reaches the trigger, at max(trigger, open);
  - they expire at a stated row;
  - an **OCO pair** fills whichever side triggers first, and **neither** if both trigger in the same row.
- **Limit entries** (ICT): they fill when price trades back to the limit, at min(limit, open) for longs.

**Exits**
- Stops and targets are resting orders. **The stop wins when a row touches both**, and a row opening beyond the stop fills at its open.
- **Indicator exits** (RSI above 40, a Heikin-Ashi colour flip, a Supertrend flip, the middle band, an EMA close) fill at the open of the row after the flagged bar.
- **Holding limits** (`max_hold`) exit at the open of row entry + max_hold.
- **Forced exits:**
  - NIFTY and BANKNIFTY at 15:14 IST;
  - FX and gold at 16:55 New York for intraday strategies;
  - NAS100 at 15:55 New York;
  - "end" (no forced exit) for daily and multi-day strategies.

**Sizing and results**
- Risk is 1% of equity per trade, where risk = |entry − stop|.
- **YT-07 has no stop** (E). It sizes on a risk unit of 2 × ATR(14), and its placeholder stop sits 30 × ATR away, so it never triggers.
- R is reported per trade, net of costs.

**Stock pools** (NSE15, NSE5, NSED)
- One book per stock.
- Statistics use per-trade R with the **t-statistic clustered by day**.
- Equity uses a 1% daily risk budget split equally over that day's trades.

## 2. Costs (base; ×2 and slippage ×3 in the stress tests)

| Market | Spread | Slippage a side | Fees |
|---|---|---|---|
| NIFTY, BANKNIFTY futures (index-price proxy) | 0 | 1.0 / 3.0 points | Angel One futures formula (STT 0.0125% → 0.02% Oct 2024 → 0.05% Apr 2026), lot 65 / 30 |
| XAUUSD | Dukascopy's quoted spread | $0.10 | $0.035/oz a side |
| EURUSD / GBPUSD | 0.2 / 0.4 pip | 0.1 / 0.2 pip | $3.50 per 100k a side |
| NAS100 / SPX500 | 1.0 / 0.5 point | 0.25 / 0.125 point | 0 |
| NSE stocks, intraday (NSE15, NSE5) | 0 | 2 bp | 3 bp a side (brokerage, STT 0.025% on the sell, exchange, stamp, GST); about 10 bp a round trip all-in |
| NSE stocks, delivery (NSED) | 0 | 3 bp | 11.5 bp a side (STT 0.1% each side, stamp, exchange); about 29 bp a round trip all-in |

## 3. Data (Phase 6)

**Markets**

| Market | Source | Span | Notes |
|---|---|---|---|
| NIFTY, BANKNIFTY | Index 1-minute (the app's cleaner) | 2016-01 → 2026-10 | Futures proxy at the index price (an index can't be traded) |
| XAUUSD, EURUSD, GBPUSD | HistData M1 bid + spread | 2009 → 2026-10 | 2023-02..07 excluded (thinned feed) |
| NAS100, SPX500 | HistData M1 regular session | 2010-11 → 2026-10 | The 2023 thin window is already cut out |
| *_D (daily) | Session OHLC of the minute data | as above | Overnight trades allowed |
| NSE15 / NSE5 | Angel 5-minute candles, 268 stocks (`D:/intraday_ai_data/intraday/5m`) | 2024-10-03 → 2026-11-05 | **Survivorship bias:** today's liquid F&O universe |
| NSED | NSE daily bhavcopy, every EQ stock incl. delisted (`data/nse_daily.npz`) | 2011-06 → 2026-11 | Split/bonus back-adjusted where the overnight ratio is below 0.6 or above 1.6 (2,081 events) |

**Point-in-time universe (NSED).** On each day, a stock is eligible when its mean turnover over the previous 20 sessions is at least ₹10 crore and its previous close at least ₹50.

**Instruments.** No instrument is chosen with hindsight. US stocks, US small caps, intraday options and crypto minutes are **not on disk**.

## 4. Strategies (measurable rules)

**Common definitions**
- Candle colour from close vs open.
- ATR = Wilder's ATR(14). RSI = Wilder's RSI(14) unless stated. EMA as usual. "Smoothed MA" = Wilder's RMA.
- Fractal pivot of n = a bar that is the extreme of n bars on each side, known n bars later.
- **2R** = target at twice the entry-to-stop distance.

### Indian indices (NIFTY, BANKNIFTY futures proxy)

**YT-01, 5 EMA alert candle**
- **Sell (E):** on 5-minute bars, a candle whose low is above the 5 EMA (the whole candle above the EMA).
  - Sell-stop at its low, valid for the next bar only; stop at its high.
- **Buy (E):** on 15-minute bars, the mirror (the whole candle below the 5 EMA, buy-stop at its high).
- Each non-triggered next bar that is itself an alert candle re-arms (E).
- **Window:** 09:15–14:55 (A); up to 3 trades a day, one at a time (A).

| Variant | Change | Tag |
|---|---|---|
| V0 | target 3R ("lose 10, earn 30") | E |
| S1 | no target; trail on the 5 EMA from 3R | E: "trail after 1:3" |
| R1 | both sides on 5-minute bars | R |

**YT-08, inside candle** (also on NSE15)
- On 15-minute bars:
  - the mother's range is at least the mean range of the previous 20 bars (A);
  - the next bar is inside the mother (high ≤ mother high, low ≥ mother low; A: by wicks).
- **Orders:** an OCO pair of a buy-stop at the inside bar's high and a sell-stop at its low (E), valid 4 bars (A).
- **Stop:** the inside bar's other side (E). **Target:** the mother's range projected from the trigger (E).
- **Window:** 09:30–14:30 setups (A); up to 2 trades a day, the second only after a stop (E: re-entry).

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | target 2R | A |
| R1 | trigger at the mother's high/low | E: the second unit |

**YT-09, traffic light**
- On 1-minute bars, skip 09:15 (E).
- The first consecutive red/green or green/red pair whose combined range is at most 0.2% of the previous close (E: 100 Bank Nifty points, scaled; A).
- **Orders:** OCO stop-entries at the pair's high and low, valid until 15:00 (A). Stop at the other side (E); target 2R (A).
- **Limits:** one trade a day (A).

| Variant | Change | Tag |
|---|---|---|
| V0 | 1-minute | E |
| S1 | 5-minute (the first candle counts) | E |

**YT-10, gap + first-candle reversal pattern**
- **Short:** a gap up of at least 0.5% vs the previous close (A: "big gap"), and the first candle is a shooting star (upper wick ≥ 2 × body, lower wick ≤ 25% of its range; A). Sell-stop at its low until 11:00, stop at its high.
- **Long:** the mirror (a gap down with a hammer → buy-stop at its high).
- **Target:** 2R (A). **Limits:** one trade a day.

| Variant | Change | Tag |
|---|---|---|
| V0 | first 15-minute candle | E |
| S1 | first 5-minute candle | E |

**YT-17, breakout → pullback → continuation**
- **Range:** 09:15–09:45 (six 5-minute bars; A).
- **Breakout:** the first 5-minute close beyond the range.
- **Entry:** the first opposite-colour (pullback) candle after the breakout sets a stop-entry beyond its far extreme, valid 3 bars (A); stop at its other extreme (E).
- **Limits:** one trade a day; setups until 14:30 (A).

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | A |
| R1 | target 1.5R | R |

**YT-19, Supertrend direction at 09:20 (proxy)**
- After the 09:15–09:20 bar, trade in the Supertrend (10, 3) direction on 5-minute bars (E/I).
- Exit at the next open after a Supertrend flip (E: the trailing stop). Protective stop at the Supertrend line.
- **Limits:** one trade a day.
- **Not the video's instrument:** the video sells options.

**YT-22, two Heikin-Ashi candles + Stochastic RSI (14, 14, 3, 3)** (also NSE15)
- **Long:** two green Heikin-Ashi candles with %K below 20 → long at the next open (E). Exit when %K crosses down through 80 (E).
- **Short:** the mirror (two red candles with %K above 80; exit when %K crosses up through 20).
- **Stop:** the two candles' extreme (A).
- **Limits:** up to 2 trades a day; setups 09:30–14:45 (A).

**YT-23, Vortex (14) crossover** (NIFTY, NSE15)
- +VI crosses above −VI with +VI above 1.10 or −VI below 0.90, i.e. outside congestion (E) → long; the mirror → short.
- Exit on the opposite crossover (I); stop at the signal bar's extreme (A).
- **Limits:** up to 2 a day.

**YT-24, 5-8-13 EMA ribbon** (also NSE15)
- **Entry:** 5 > 8 > 13 newly aligned and the close above all three → long (E/A).
- **Exit:** a close below the 8 EMA (E: the 8 EMA as the stop); mirror for shorts.
- **Stop:** the signal bar's extreme (A). **Limits:** up to 2 a day.

**YT-27, Camarilla** (also NAS100)
- **Levels:** from the previous session: R3/S3 = C ± 1.1 × range / 4, R4/S4 = C ± 1.1 × range / 2, pivot P = (H + L + C) / 3.
- **Only on days opening between S3 and R3** (A). The first event in the window decides:
  - **Fade (E):** a 5-minute bar trades above R3 and closes back below → short, stop at R4, target P. Mirror at S3.
  - **Breakout (E):** a 5-minute close beyond R4 or S4 → trade it, stop at R3 / S3, target 2R (A).
- **Window:** 09:20–14:30 IST, or 09:35–15:00 New York (A). **Not modelled:** order flow (E).
- **Limits:** one trade a day.

### NSE stocks

**YT-12a, 44 SMA (daily NSED)**
- The 44-day SMA is rising (vs 5 days earlier).
- **Signal:** a green candle whose low is within 1% of (or below) the 44 SMA and whose close is above it (E/A).
- **Entry:** buy-stop at its high the next day only (E: "buy above the high"); stop at its low (E).
- Liquid on the signal day (point-in-time).

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R, max 20 days | E / A |
| R1 | 3R, max 30 days | R |

**YT-12b, 44 SMA + big green opening candle (NSE15)**
- **Day filter:** the previous close is within 2% of a rising 44-day SMA of daily closes.
- **Signal:** the first or second 15-minute candle is green, with range at least 1.5 × the mean of the previous ~20 sessions' 15-minute ranges and body at least 50% of its range (E/A).
- **Entry:** buy-stop at its high until 11:00; stop at its low; target 2R (E).

**YT-13, daily bear / bull trap** (NSED long only, NIFTY_D both)
- **Bear trap:** yesterday's close is below the lowest close of the 20 days before it (a breakdown, A). Today is a green candle with range at least 1.5 × the 20-day mean range (E: big).
- **Entry:** buy-stop at today's high the next day, stop at today's low, target 2R (E: twice the candle).
- **Bull trap:** the mirror (NIFTY_D only).
- Max 20 days (A).

**YT-25, RSI 70/30 reversal (NSE15)**
- RSI crosses back below 70 → short, stop at the 5-bar high; crosses back above 30 → long, stop at the 5-bar low (A).
- **Target:** 2R (A). **Limits:** up to 2 a day.
- **Low fidelity:** the captions are partly garbled.

**YT-26, ORB on gappers (NSE5, proxy)**
- **Day filter:** the open gaps at least 2% vs the previous close, and the first 5-minute bar's volume is at least 3 × its mean over the previous 20 sessions (A: "in play").
- **Gap up:** after a 5-minute close above session VWAP that is still below the first bar's high, a buy-stop at the first bar's high until 10:30. Stop at the higher of the first bar's low and VWAP − 0.05% (E: just below VWAP).
- **Gap down:** the mirror.
- **Target:** 2R (A). **Not the video's market:** it trades US stocks.

### FX, gold, US indices

**YT-02, market-structure pullback** (EURUSD, GBPUSD; overnight trades)
- **4h trend:** up if the last two confirmed 4h fractal (2) highs and lows both rise; down if both fall (E/A).
- **The zone:** a 1h close above the latest confirmed 1h fractal (2) high creates a zone from that bar's body top to its wick high (E).
- **Entry:** within 30 bars, a green 1h candle whose low enters the zone, with no close below the zone bottom (E: rejection) → long at the next open.
- **Stop:** the lowest low since the break minus ATR(14) (E). Mirror for downtrends.

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | A |
| R1 | 1.5R | R |

**YT-03, 50 MA double bottom** (EURUSD, GBPUSD 1h; overnight)
- **Double bottom:** two confirmed fractal (3) lows 5–40 bars apart and within 0.25 × ATR of each other; one of them at or below the 50 SMA (E: touches); the second close not far below it (A).
- **Entry:** within 10 bars, a green candle closing above the 50 SMA → long (E).
- **Stop:** the lower bottom − 0.1 × ATR (A). Mirror (double top).

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | A |
| R1 | 1.5R | R |

**YT-04, Silver Bullet** (EURUSD, NAS100 1-minute)
- **Windows:** 03:00–04:00, 10:00–11:00 and 14:00–15:00 New York (E). NAS100 has only the latter two (cash session).
- **The first FVG in a window:**
  - bullish: low[j] > high[j−2];
  - the room to the session's high so far is at least 15 pips / 10 points (E: minimum framework).
- **Entry:** limit at the gap's near edge (low[j]; A), valid until the window ends (A).
- **Stop:** below candle 1 (low[j−2]; A). **Target:** the session high so far (E: the liquidity pool).
- Mirror for bearish gaps. **Limits:** up to one per window.

**YT-05, Judas Swing** (EURUSD, GBPUSD 5-minute)
- **Inputs:**
  - the Asian range = 19:00–24:00 New York (A);
  - the midnight New York open (E);
  - **bias** = the previous day's close vs its 20-day average (A: the higher-timeframe premise).
- **Bullish (00:00–05:00 New York):**
  - price first trades above the Asian high, then below both the midnight open and the Asian low (E);
  - the first 5-minute close back above the Asian low → long (A: confirmation);
  - stop: the low since midnight − 10 pips (E: "respectable pips").
- Mirror for bearish. Exit by 12:00 New York (A).

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | A |
| R1 | 3R | R |

**YT-06, OTE 62%** (EURUSD 5-minute)
- **The leg:** the 00:00–08:30 New York low and high, in the order they formed (A: the swing).
- **Entry:** limit at the 62% retracement, valid 08:30–11:00 (E). Stop 2 pips beyond the leg's start (E).
- **Target:** the −0.5 extension (E: the first scale-out), taken only if at least 15 pips away (E).
- Exit by 12:00 (A).

**YT-07, Connors RSI(10)** (SPX500_D; NAS100_D and NIFTY_D as out-of-market checks)
- **Entry:** a close above SMA(200) and Wilder RSI(10) below 30 → buy at the next open (E).
- **Exit:** at the next open after RSI(10) closes above 40, or the open of the 11th day (E: "after 10 trading days").
- Long only (E).

| Variant | Change | Tag |
|---|---|---|
| V0 | no stop | E |
| R1 | a 2 × ATR stop | R |

**YT-11, momentum loss** (EURUSD, GBPUSD, XAUUSD 1h; overnight)
- **Levels:** the last 6 confirmed 4h fractal (2) highs and lows (A).
- **Long at support L:**
  - the three bars before the signal have shrinking ranges and falling closes, all above L (E: momentum loss);
  - the signal bar's low comes within 0.1 × ATR of L, it closes above L, and its lower wick is at least 50% of its range (E: the rejection).
- **Entry and exits:** long at the next open; stop below the low − 0.1 × ATR. Mirror at resistance.

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | A |
| R1 | 1.5R | R |

**YT-14, MA fan** (EURUSD, GBPUSD, XAUUSD 5-minute)
- **Fan (E):**
  - smoothed MAs 21 > 50 > 200, each rising vs 5 bars ago;
  - the close above the 200.
- **Signal (E):**
  - a bullish engulfing candle or a three-line strike (three red bars, then a green bar closing above the first red's open);
  - RSI above 50 and rising.
- **Entry:** long at the next open; stop = entry − 2 × the signal candle's range (E). Mirror for shorts.
- **Limits:** up to 3 a day.

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | E |
| R1 | 1.5R | R |

**YT-15, Williams fractal** (EURUSD, GBPUSD 5-minute)
- **Alignment:** smoothed MAs 21 > 50 > 200, the close above the 21, the 200 rising; RSI above 50 (E).
- **Entry:** a fractal (2) low confirmed in alignment → long at the next open; stop 0.2 pip below the fractal bar's low (E). Mirror for shorts.
- **Limits:** up to 5 a day.

| Variant | Change | Tag |
|---|---|---|
| V0 | fixed 10-pip target | E |
| S1 | 10-pip target, breakeven at +10 pips | E (as close as the engine allows) |

**YT-16, MA pullback + candlestick** (EURUSD, GBPUSD 1h; SPX500_D, NAS100_D; overnight)
- **Trend:** SMA50 > SMA150 with SMA50 rising (E/A).
- **Signal:** a bar touches the SMA50 (low ≤ SMA50 < close) and is a bullish engulfing candle or a pin bar (lower wick ≥ 2 × body; E).
- **Entry and exits:** long at the next open; stop below the bar − 0.1 × ATR (E/A); target 2R (E). Mirror for shorts.

**YT-18, Heikin-Ashi + RSI 50** (EURUSD, GBPUSD, XAUUSD)
- **Entry:** the HA colour turns red → green with RSI above 50 → long (E).
- **Exit:** the first red HA bar (I). Stop below the signal bar − 0.1 × ATR (A). Mirror for shorts.
- **Limits:** up to 3 a day.

| Variant | Change | Tag |
|---|---|---|
| V0 | 15-minute | A |
| S1 | 1-hour | A |

**YT-20, 3-EMA scalp** (EURUSD, GBPUSD 1-minute, 07:00–17:00 UTC)
- **Trend:** EMA 50 > 100 > 150, with the 50 and the 150 rising vs 10 bars ago (E).
- **Pullback:** a close below the 50 but above the 100 starts it (E). It is cancelled by a close below the 100, by the alignment breaking, or after 30 bars (A).
- **Entry:** the first close back above the 50 → long (E). Stop below the pullback's low − 0.2 pip (E). Mirror for shorts.
- **Limits:** up to 5 a day.

| Variant | Change | Tag |
|---|---|---|
| V0 | breakeven at +5 pips (E), target 2R (A) | E / A |
| S1 | fixed 1.5R, no breakeven | E: "fixed target" |

**YT-21, Bollinger range fade** (EURUSD, GBPUSD 15-minute)
- **Bands:** BB(20, 2.5) (E: 2.5–3 SD).
- **Parallel bands** (E):
  - the width is within ±5% of its value 10 bars earlier;
  - the middle band has moved less than 0.25 × the width (A).
- **Entry:** low ≤ lower band < close → long (E). Exit at the first close at or above the middle band (E).
- **Stop:** entry − ATR (A). Mirror at the upper band.
- **Limits:** up to 3 a day.

## 5. Splits (Phase 8)

| Market | Development | Validation | Hold-out (opened once) |
|---|---|---|---|
| NIFTY, BANKNIFTY (incl. _D) | 2016 → 2021 | 2022 → 2023 | 2024 → end |
| FX, gold, NAS100, SPX500 (incl. _D) | first day → 2019 | 2020 → 2022 | 2023 → end |
| NSED stocks | 2011-06 → 2019 | 2020 → 2022 | 2023 → end |
| NSE15 / NSE5 stocks | 2024-10 → 2025-06 | 2025-07 → 2025-12 | 2026-01 → 2026-11 |

**Choosing a variant**
- Per strategy and market, choose the variant with the highest **net mean R over development + validation**, among those with at least 30 trades there. A tie goes to V0.
- The hold-out is evaluated once, for V0 and the chosen variant.
- Walk-forward: from the 4th year, each year trades the variant with the best mean R in all earlier years.
- The post-publication span (the video's upload year on) is reported separately.

## 6. Gates (Phase 9)

These are the same as the Booming Bulls study. **Candidate for paper trading** requires all of:
1. hold-out net mean R > 0 with t ≥ 2 (day-clustered for stock pools);
2. a Holm-adjusted one-sided p < 0.05 across every hold-out test;
3. development and validation mean R both > 0;
4. at least 50 hold-out trades;
5. still > 0 at 2× costs and with a one-row delayed entry;
6. the top 5 trades provide less than 50% of the hold-out net;
7. hold-out max drawdown < 20%.

The other classes:
- **Needs more evidence:** the hold-out and development+validation means are both > 0, but a gate fails.
- **Not supported:** any other outcome.
- **Unable to evaluate:** fewer than 30 trades in total, or no data.

## 7. Robustness

Gross (no costs); costs ×2; slippage ×3; entry delayed one row; target ±0.5R where a fixed R target exists; per-year results.

## Change log

- 2026-11-07: first version (before any run).
- 2026-11-07, before any backtest run: the look-ahead truncation test (`yt_checks.py`) found that YT-17's "skip days shorter than 30 bars" used the day's final length, which is known only at the close.
  - **The fix** removes such day-length filters from YT-17, YT-04, YT-06 and YT-26. YT-06's order now expires at 11:00 or the last available bar.
  - These filters were never part of the rules above. No rule text changes.
- 2026-11-07, after the first full run and before the hold-out was opened:
  - **The defect:** YT-06's order expiry looked for the first bar at or after 11:00 New York from the session's start. Forex sessions start at 17:00 New York the previous evening, so it matched the first evening bar, and 4,531 of 4,534 orders expired before they began (2 trades).
  - **The fix:** search from 08:30 on.
  - YT-06 was re-run. Only its development+validation figures for the 2 buggy trades had been seen.
