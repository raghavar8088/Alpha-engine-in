# Pre-registration: Booming Bulls strategies (Phases 4, 6, 7, 8)

Written 7 Nov 2026, before any backtest of these rules. Its SHA-256 (LF line ends) is recorded in `PREREG_HASH.txt` and stamped into every result file. If the rules change after a run, the change is logged in the change log at the end and the hash changes.

The video rules come from `../analyses/` and are summarised in [LIBRARY.md](LIBRARY.md). Tags: **E** = stated in the video, **I** = inferred from it, **A** = my research assumption.
- **V0** is the source-faithful version.
- **S-variants** are other settings **the video itself names** (for example "beginners 1:1.5").
- **R-variants** are research additions and are **not** attributed to Booming Bulls.

## 1. Common execution rules (all strategies)

**Signals and entries**
1. **Bars.** Every timeframe is built from 1-minute data. Bars start on the timeframe grid of the market's clock: NIFTY from 09:15 IST, others from 00:00 UTC. A bar's values are known only after its last minute.
2. **Signals** are evaluated on completed bars only. A market entry fills at the **open of the first minute after the signal bar**. Nothing fills inside the signal bar.
3. **Entry price.** Longs buy at the ask, shorts sell at the bid, each with slippage against us.
   - NIFTY and BANKNIFTY have no spread in the data (index-price futures proxy): bid = ask = the index price, and slippage alone applies.
4. **Rejected entries.** The entry is rejected and logged if the fill is already at or beyond the stop or the target, or if the risk is zero.

**Exits**

5. **Stops and targets** are resting orders checked minute by minute from the entry minute on.
   - **Long:** the stop triggers when the bid's minute low ≤ stop and fills at min(stop, bid open) − slippage, so a gap fills at the open. The target triggers when the bid's minute high ≥ target and fills at the target (no slippage, no improvement).
   - **Short:** the same, mirrored with the ask.
   - **Same minute:** if a minute touches both the stop and the target, **the stop fills**.
6. **Breakeven** (where used): when a minute's favourable extreme reaches the trigger, the stop moves to the entry fill from the next minute.
7. **9-EMA trail** (where used): it activates when a minute reaches the activation R. From then on, a completed strategy-timeframe bar that closes beyond the EMA(9) of closes exits at the next minute's open. The fixed stop stays and the fixed target is dropped.
8. **Forced exits:** NIFTY/BANKNIFTY at the close of the 15:14 minute (15:15 square-off), and each strategy's session end otherwise (section 4). Entries may happen only inside each strategy's window.

**Positions and sizing**

9. **One position at a time** per strategy, market and variant. Per-day trade limits are per strategy.
10. **Sizing:** 1% of current equity is risked per trade, where risk = |entry fill − stop| × units.
    - **CFDs:** units are fractional.
    - **NIFTY:** a second simulation uses a ₹10 lakh account in whole lots of 65, with a margin cap of 12% of notional per lot. A trade whose risk-based size rounds to zero lots is skipped and logged.
11. **Trade result:** R = net P&L ÷ (|entry fill − stop| × units). Gross R excludes costs.

## 2. Costs (base; stressed in section 7)

| Market | Spread | Slippage per side | Commission / fees |
|---|---|---|---|
| NIFTY futures (index proxy) | 0 | 1.0 point | Angel One futures formula as in `liquidity_sweep_2026_11/ls_common.py`: ₹20 brokerage a side, STT on the sell (0.0125% to Sep 2024, 0.02% from Oct 2024, 0.05% from Apr 2026), exchange, SEBI, IPFT, stamp, GST. Lot 65 for the rupee figures |
| BANKNIFTY futures (index proxy) | 0 | 3.0 points | Same formula; lot 30 assumed for rupee figures (R does not depend on it) |
| XAUUSD | Dukascopy's quoted spread in that hour (in the minute data) | $0.10 | $0.035/oz a side |
| EURUSD | 0.2 pip | 0.1 pip | $3.50 per 100k a side (0.35 pip) |
| GBPUSD | 0.4 pip | 0.2 pip | $3.50 per 100k a side |
| NAS100 (HistData NSXUSD) | 1.0 point | 0.25 point | 0 |
| US30 (Dukascopy) | 2.0 points (modelled; BID only fetched) | 0.5 point | 0 |
| AAPL (Dukascopy) | $0.05 (modelled; BID only fetched) | $0.01 | 0 |

## 3. Data (Phase 6)

**On disk**

| Market | Source | Span | Known defects and handling |
|---|---|---|---|
| NIFTY, BANKNIFTY | Index 1-minute, `index_intraday_2026_10/data/1m` + box files, cleaned by the app's `index_intraday.data._build` | 2016-01 to 2026-10 | Bad prints dropped and short sessions dropped by the app's cleaner. **An index cannot be traded:** signals come from the index and the fills are a futures proxy at the index price (intraday basis drift ignored; contract roll irrelevant to a flat-by-15:15 strategy) |
| XAUUSD | HistData M1 (= Dukascopy bid) + Dukascopy hourly spread → mid | 2009-03 to 2026-10 | **2023-02-01 to 2023-07-31: about 50% of minutes missing; those days are excluded.** Hourly tick volume (Dukascopy) for the BB-09 profile |
| EURUSD, GBPUSD | HistData M1 bids + fixed spread | 2009-01 to 2026-10 | Same 2023 window excluded |
| NAS100 | HistData NSXUSD M1, regular session 09:30–16:00 NY | 2010-11 to 2026-10 | Same 2023 window excluded |
| US30, AAPL | Dukascopy M1 BID, fetched for this study (`bb_fetch_dukascopy.py`) | 2024-01 to 2026-10 (as fetched) | Short history; ask modelled |

**Clocks and session days**
- **IST** = UTC+5:30. The US open is 09:30 New York (DST-aware via the tz database).
- **Gold and FX trading days** roll at **17:00 New York**. "Previous day" means the previous such session, as on TradingView with session breaks.
- **NIFTY's day** is its 09:15–15:30 IST session.

**Survivorship and coverage.** No strategy picks instruments from today's lists; every market is a fixed index, pair or contract. AAPL is a single named stock chosen by the video.

## 4. Strategies

Price-scaled thresholds use p = the previous session's close.

### BB-01 Nifty previous-day high/low (gNoByC3ZEOo), NIFTY 5m

**Levels and thresholds**
- **Levels:** PDH = the highest 5m body top (max(open, close)) of the previous session; PDL = the lowest body bottom (E, "bodies").
- **Thresholds**, scaled from the video's ₹ figures at Nifty 25,000 (A):
  - BIG = 0.32%·p (₹80);
  - GAPMIN = 0.12%·p (₹30);
  - WIDE = 0.20%·p (about ₹50);
  - MINSTOP = 0.04%·p.
- **Candle quality** (E): a long entry candle is green with an upper wick ≤ 15% of its range; a short entry candle is red with a lower wick ≤ 15% (A: the 15%).

**Breaks**
- **Break up:** a candle closes above PDH while the previous close (the open, for the first candle) was at or below it.
- **Gap opens:** if the day opens above PDH, the level is idle until a candle closes back at or below it (I: 17 and 26 Sep "opened outside range, no trade").
- Mirror for PDL.

**Setups** (the first qualifying signal of the day is taken; one trade a day, E)
- **B, breakout (E):** after a break up, the next candle that closes above PDH, green, quality-passing → long at its close.
  - If the breaking candle's body ≥ BIG and it passes quality → long at the breaking candle's close (E).
  - If a candle closes back at or below PDH first, setup B is off for that break.
- **T, trap (E):** after a break up, the first candle that closes back below PDH → short at its close if it is red and passes quality. If it fails quality, no trade and the break is spent.
- **G, gap fill (E):**
  - **Gap up:** day open − previous close ≥ GAPMIN. The gap line is the first candle's body low.
  - **Trigger:** before 11:00 (signal bar closing ≤ 11:00), a candle closes below the gap line with (close − previous close) ≥ GAPMIN, red and quality-passing → short.
  - Mirror for a gap down.
- **R, retest (E):** after a break up with no trade taken, a later candle with low ≤ PDH + 0.03%·p (A), close > PDH, green and quality-passing → long. Mirror for PDL.

**Stop** (E: "where the move started, plus 10–20%"; A for the anchors)
- **Anchor ("base"):**
  - B: the lower low of the breaking and confirming candles;
  - big-candle B: the breaking candle's midpoint (E, "50% of a big candle");
  - T: the highest high since the break;
  - G: the session's extreme so far on the far side;
  - R: the retest candle's low.
- **Stop = base ∓ 15% of |entry − base|.**
- If the stop is wider than WIDE, use one candle back instead: the entry candle's extreme ∓ 15% (E). If it is narrower than MINSTOP, widen it to MINSTOP (A, "never tight").

**Target, window and exit**
- **Target:** 2R (E).
- **Window:** entries 09:20–15:00 (A).
- **Exit:** 15:15.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | target 1.5R ("beginners") | E |
| S2 | 2R with breakeven at 50% of the target | E |
| R1 | wick-based levels | R |

### BB-02 15-minute opening-range breakout (yKtI-VEMwC0, 4iPEKSo_vwY), NIFTY 5m

**Range and trigger**
- **Range:** the high and low of 09:15–09:30 (E, wicks).
- **Trigger:** the first 5m candle from 09:30 that **closes** above the range high (long) or below the range low (short), with body ≥ 30% of its range (A, "a real body").

**Stop**
- Beyond the breakout candle's far extreme ± 0.02%·p (A, "with space").
- If that is wider than 0.18%·p (E, ₹45), use the broken range edge ± 0.02%·p instead (I), when that is closer.
- Widened to at least 0.04%·p (A).

**Trades, window and exit**
- **Trades:** up to two a day. The second is allowed only after a stop-out, in either direction (E).
- **Window:** entries until 15:00 (A).
- **Exit:** 15:15.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R ("experienced") | E |
| S1 | 1.5R | E |
| S2 | 1R | E |
| S3 | no target; 9-EMA (5m) trail from 2R ("1:3 by trailing") | E/A |
| S4 | 2R with breakeven at 50% | E (from examples) |

### BB-03 Nifty + BankNifty synchronised break (0MasZZQiL5s), NIFTY traded, 5m

**Signal**
- **Short:** on the same 5m candle (09:30–14:30, A), both NIFTY and BANKNIFTY make a **fresh close** below one of their key levels, and both candles are red (E).
  - The key levels are the current-day low before that candle and the previous-day low on wicks (E).
  - A fresh close means the previous close was above that level.
- **Long:** the mirror on highs (I).

**Exits and limits**
- **Stop:** NIFTY signal candle's far extreme ± 0.02%·p (A).
- **Target:** 2R (A).
- **Limits:** one trade a day (A); exit at 15:15.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| R1 | previous-day levels only | R |

### BB-04 Zone trap with RSI divergence (SxQwiHBfHUs), NIFTY 15m

**Zone and trap**
- **Zone:** the band from the previous session's highest 15m close up to its high (A, "resistance not closed above").
- **Trap:** a 15m candle closes above the zone top. Within the next 6 candles (A), a **red** candle closes below the zone bottom → short at its close (E).
- **Mirror:** the bear trap at the previous low band (I, v5AUeTSUiiM) → long.

**RSI divergence filter** (E as confluence)
- RSI(14) runs on continuous 15m closes.
- **Bearish divergence:** the highest high since the break is above the most recent confirmed pivot high within 30 bars, and the RSI at that bar is lower than the RSI at the pivot.
- **Pivot:** a high that is the maximum of 2 bars on each side, known 2 bars later. Mirror for longs.

**Exits and limits**
- **Stop:** the trap's extreme ± 0.02%·p (A).
- **Target:** 2R (E, "more than 1:2").
- **Limits:** one trade a day (A); exit at 15:15.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | RSI divergence required | E/A |
| R1 | no RSI filter | R |

### BB-05 SMC break of structure / change of character into an order block (hXtpVnpjuXg), BANKNIFTY 5m

**Structure** (A throughout)
- **Swings:** fractal pivots, 2 bars each side, confirmed 2 bars later, within the session.
- **Breaks:** a close above the last confirmed swing high is a bullish structure break (BOS if the prior break was bullish, CHoCH if it was bearish). Mirror for lows.

**Order block and entry**
- **Order block:** the last red candle before the up-move that made the break. Its range is the block (A, standard SMC; the video draws blocks by eye).
- **Entry:** price returns into the block (low ≤ block high) without closing below the block low, and a green reversal candle closes → long (E: "never the direct trade after CHoCH; wait for the block and a reversal candle").
- **Expiry:** a block lapses after 24 bars or a close through it. Mirror for shorts.

**Exits and limits**
- **Stop:** beyond the block ± 0.02%·p (E, "a little above the block").
- **Target:** 2R (E). At 1R, book half and move the stop to breakeven (E).
- **Limits:** up to 3 trades a day, one at a time (E, "about 3 a day"); entries 09:30–15:00 (A); exit at 15:15.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | half off at 1R + breakeven | E/A |
| S1 | plain 2R | E |

### BB-06 Gap day + first candle through the 15m 200 MA (zm9emzopBi0), NIFTY 15m

**Signal** (one trade a day)
- **Long:** the day opens ≥ GAPMIN above the previous close (A). The first 15m candle closes above SMA(200) of continuous 15m closes, the previous session's close was below it, and the candle is green (E/A) → long at its close.
- **Short:** mirror for a gap down (I).

**Exits**
- **Stop:** the first candle's far extreme ± 0.02%·p (A).
- **Exit:** 15:15.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | A: the video trails, undefined |
| S1 | 9-EMA (15m) trail from 1R | E: "exits by trailing" / A |

### BB-07 Liquidity sweep of previous-day levels, masterclass (IOBoaM71MUA), XAUUSD 5m (and NAS100)

**Levels and sweep**
- **Levels:** PDH and PDL on wicks (E).
- **Sweep and confirmation:** the first 5m candle of the day trading beyond the level (high > PDH) starts a sweep (E). Within 6 candles (A), a candle closes back across the level → trade the other way at its close (E). No close back, no trade (E).

**Exits**
- **Stop:** the sweep extreme ± 0.07%·p (E: "$3 beyond" at about $4,300, scaled; A).
- **Target:** 2R (E/I, "about 1:2").
- **Limits:** one trade a day (E).
- **Window:** entries 10:00–22:00 IST (A, "night hours not tradable").
- **Exit:** the session end (16:55 New York) (A).

**Markets:** XAUUSD (V0), and NAS100 regular session (E, "Nasdaq too") with PDH/PDL from the previous regular session and entries 10:00–15:30 New York (A).

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | also the current-day high/low, once the day's range ≥ 0.75 × ATR(14) of daily ranges | E: "ATR minus 20–30%" |

### BB-08 Previous-day "manipulation" trap after 10:00 IST (HxBwAconvqA, 7LLm0HSarPc, TIQeTWWc1-8), XAUUSD / EURUSD / GBPUSD 5m

**Levels and entry**
- **Levels:** PDH and PDL on wicks (E).
- **Entry:** a sweep (a trade beyond the level) and then, within 6 candles (A), a candle closes back inside **in the trade colour** (red for a short) → enter at its close (E). If the close-back candle has the wrong colour, the next candle may qualify (E: "wait for one more candle").

**Exits**
- **Stop:** the extreme of the manipulation ± 0.02%·p (E, "a little beyond"; A for the size).
- **Limits:** one trade a day (E).
- **Window:** 10:00–22:00 IST (E, after 10:00; A for the end).
- **Exit:** the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 1.5R ("beginners") | E |
| S1 | 1.5R with breakeven at 50% | E |
| S2 | 9-EMA trail from 1.5R ("experienced") | E |
| S3 | 2R | E, TIQeTWWc1-8 |

### BB-09 Value-area trap (zYGUL82NsS4, rFrFhpwJJOc B), XAUUSD 5m

**Profile** (E for the span, A for the volume)
- **Span:** from the start of the previous trading day to 16:00 IST today.
- **Rows:** 24 equal rows between the span's low and high.
- **Volume weights:** each minute's weight is its UTC hour's Dukascopy tick volume divided by that hour's minutes (A, proxy for the broker volume TradingView uses). It is spread evenly over the rows the minute's range covers.
- **POC and value area:** the POC is the heaviest row. Grow the value area one adjacent row at a time, taking the heavier side, until it holds ≥ 70% of the volume (E: 70%; A: the method). VAH is the top of the value area, VAL the bottom.

**Entry**
- **Window:** after 16:00 IST until 22:00 IST (A).
- **Sides:** VAH gives only sells, VAL only buys (E).
- **Trigger:** price trades beyond VAH and within 6 candles (A) a candle closes back below VAH → short at its close (E: "trap only"). Mirror at VAL.

**Exits and limits**
- **Stop:** the trap extreme ± 0.05%·p, widened to at least 0.18%·p from the entry (E: "$7–10, not stingy", scaled from about $4,000; A).
- **Limits:** up to two trades a day; none after a target; a second only after a stop (E).
- **Exit:** the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | E |
| S1 | 1.5R | E |
| S2 | 3R, with the stop moved to +1R once 2R is reached | E/A |
| R1 | value area 60% | E: "homework" |
| R2 | value area 80% | E: "homework" |

### BB-10 Gold 11:30–12:30 IST range sweep (1hZMOSd34vQ), XAUUSD 5m

**Range and entry**
- **Range:** the highest body top and lowest body bottom of the 5m candles from 11:30 to 12:30 IST (E).
- **Window:** entries from 14:30 IST (E, after Tokyo) to 22:00 IST (A).
- **Trigger:** a sweep beyond the range high or low; then within 6 candles (A) a candle closes back inside → trade back into the range (E).

**Exits and limits**
- **Stop:** the sweep extreme ± 0.03%·p (A).
- **Target:** 2R (E).
- **Limits:** one trade a day (A); exit at the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| R1 | range on wicks | R |

### BB-11 Forex 10:00 IST range trap (uUa61jN45vM), EURUSD 15m (GBPUSD, XAUUSD as out-of-market checks)

**Range**
- At 10:00 IST, take the session's highest body top and lowest body bottom so far (E).
- If the high was set by the last candle and that candle is green, the high keeps updating until a red candle closes (E, "wait for the turn"). Mirror for the low.

**Trap and void rule**
- **Trap:** a 15m candle closes outside the range, then a candle closes back inside → trade the other way at its close (E).
- **Void:** if any trap completes on a candle starting before 11:45 IST, the day is void (E).
- **Entry candles:** from the 11:45 IST candle until the one starting 21:00 IST (A for the end).
- **Bad entry candle** (an adverse wick > 30% of its range, A): wait up to 2 more candles for a good one that closes inside the range in the trade direction (E).

**Exits and limits**
- **Stop:** beyond the trap extreme ± 0.02%·p (E/A). If wider than 0.6 × the range height, use 0.55 × the range height (E, "about 50–60% of the range"; I: as a distance).
- **Target:** 2R (E).
- **Limits:** one trade a day (E); exit at the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | breakeven once past 1.5R | E: one example |
| R1 | no void rule | R |

### BB-12 400 EMA trap (DI3ydbq9b6M), XAUUSD and US30 15m

**Day side and setup**
- **Day side:** the 12:00–12:15 IST candle closes above the EMA(400) of continuous 15m closes → longs only; below → shorts only (E).
- **Setup:**
  - a candle trades through the EMA (its low < EMA for longs);
  - within 6 candles (A), two consecutive green candles close above the EMA, the second closing above the first;
  - each has body ≥ 50% of its range, and at least one has an upper wick ≤ 10% of its range (E/A);
  - enter at the second's close (E).
- **One-candle exception:** a green candle closing above the EMA whose range exceeds each of the previous 10 candles → enter at its close (E). Mirror for shorts.

**Exits and limits**
- **Stop:** the lowest low from the through-candle to the entry candle ± 0.02%·p (E: "logical"; A: this choice).
- **Window:** signals 12:00–22:00 IST (E). Positions may run to the session end (E/A).
- **Limits:** one trade a day (E).

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 1.5R | E |
| S1 | 2R | E |
| R1 | stop just beyond the EMA instead | E alternative / A |

### BB-13 "Prop-firm" inside-body breakout (Lb4yel3nCws, NwCyONUCsC0), NAS100 and XAUUSD 5m

**Pattern** (long; mirror for short)
- Candle 1 is red; candle 2's body lies inside candle 1's body (E).
- Candle 3 or 4 **closes** above candle 1's high with body ≥ 70% of its range → long at its close (E).
- No break by candle 4: void (E).

**Exits and limits**
- **Stop:** the entry candle's low − 0.02%·p (E/A).
- **Limits:** one trade a day per market (E).

**Windows**
- **NAS100:** entries from 10:00 New York (E: 30 minutes after the open) to 15:00 New York (A); exit at 15:55 (A).
- **XAUUSD:** entries from 08:30 New York (E: New York session start 08:00 plus the 30-minute wait) to 22:00 IST (E); exit at the session end (A).

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 1R | E, prop-firm |
| S1 | 1.5R | E |
| S2 | 2R | E |
| R1 | stop beyond two candles | E alternative |

### BB-14 Inside candle with the 10-point filter (kakFchv-ylo), US30

**Mother candle and range**
- The mother has body ≥ 60% of its range, range ≥ the mean range of the previous 20 candles, and wicks on both sides (E: "big body, wicks"; A for the thresholds).
- The next 2 candles' open and close lie within the mother's range (E). The range is the mother's high and low.

**Breakout and filter**
- **Breakout:** within 6 candles after the second inside candle (A), a close above the mother's high → long; below its low → short (E).
- **Filter:** before the breakout, a wick more than 10 points below the mother's low that closed back inside cancels longs; above the high, it cancels shorts (E).

**Exits and limits**
- **Stop:** the breakout candle's far extreme ± 2 points (E: "beyond the entry candle"; A for the 2 points).
- **Window:** entries from 09:30 New York to 00:00 IST (E); exit at 16:00 New York (A).
- **Limits:** up to 2 trades a day; stop after 2 stops (E).

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | 5m, target 1.5R | E: minimum; timeframe A |
| S1 | 15m, 1.5R | timeframe A |
| S2 | 5m, 2R | E |
| R1 | 5m, stop beyond the mother range | E alternative |

### BB-15 Apple opening-range trap (T_VlPXyqj0U), AAPL 3m

**Range and filter**
- **Opening range:** 09:30–09:45 New York (E, DST-aware; A for winter).
- **Day filter:** skip the day if the range is ≥ 1% of the price (E).

**Trap and window**
- **Trap:** price trades beyond the range, then a 3m candle closes back inside → trade the other way at its close (E).
- **Window:** entries until 11:30 New York (E: "within about 2 hours"; A: DST-aware).

**Exits and limits**
- **Stop:** if the trap candle's range is ≥ 1.5 × the session's mean 3m range so far, beyond that candle; otherwise beyond the last two candles; ± $0.02 (E/A).
- **Target:** 2R (E).
- **Limits:** one trade a day (E); exit at 15:55 New York (A).

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | breakeven at 1R | E: "breakeven instead of trailing"; A: the trigger |
| S2 | 9-EMA trail from 2R | E: experienced |

### BB-16 Retracement-zone sweep (rFrFhpwJJOc A, 3gj7MbZ0vHs), XAUUSD 1h + 5m

**Leg and zone**
- **1h swings:** fractal pivots, 3 bars each side, confirmed 3 bars later (A).
- **The leg:** the latest confirmed low → high (an up-leg), with size ≥ 3 × ATR(14) on 1h (A: "big move").
- **Zone:** 50–61.8% retracement (E).
- **Invalidation:** a 5m close beyond the zone ends the leg (E: "never close beyond the box").

**Entry**
- While price is in the zone (5m low ≤ 50% line), a 5m candle trades below the latest confirmed 5m internal swing low (fractal, 2 bars each side) and closes back above it → long at its close (E).
- Mirror for down-legs.

**Exits and limits**
- **Stop:** the sweep extreme ± 0.05%·p (A).
- **Target:** 2.5R (E, "at least 1:2.5").
- **Limits:** one trade per leg and per day (A); entries 10:00–22:00 IST (A); exit at the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | zone 70.5–79% (the ICT OTE) | E, 37uPX6Li-xE |
| S2 | 2R | E, B4 of rFrFhpwJJOc |

### BB-17 Order-block 50% trap (RTbVZfriRrw), XAUUSD and EURUSD 15m + 5m

**Order block**
- **FVG:** on 15m, candle 3's low > candle 1's high, wick to wick (A: the strictest of the three gaps the video allows).
- **Impulse:** candle 2's body ≥ 1.5 × the mean body of the previous 20 candles (A, "explosive").
- **Block:** candle 1's range, with its 50% line (E).

**Entry**
- After the triple completes, a 5m candle trades below the 50% line and a 5m candle closes back above it → long at its close (E).
- **Expiry:** the block lapses after 48 fifteen-minute bars or a 15m close below its low (A).
- Mirror for bearish blocks.

**Exits and limits**
- **Stop:** the trap's lowest low ± 0.03%·p (E: "below the 50% line"; A for the size).
- **Target:** 2R (E).
- **Limits:** up to 2 trades a day (A); entries 10:00–22:00 IST (A); exit at the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | as above | E/A |
| S1 | stop below the block's low | E: an alternative stop |

### BB-18 15m 200 EMA breakout-retest (Hj56fabq2c8), EURUSD and GBPUSD 15m

**Setup**
- **Break:** a close above the EMA(200) after a close at or below it (E).
- **Retest:** within 8 candles (A), a candle's low ≤ EMA + 0.02%·p, it closes above the EMA and it is green → long at its close (E). Mirror for shorts.
- **Window:** signals 16:00–20:00 IST (E).
- **Omitted:** the currency-strength filter is not implemented (insufficiently defined).

**Exits and limits**
- **Stop:** the retest candle's low − 0.02%·p (E).
- **Limits:** one trade a day (A); exit at the session end.

**Variants**

| Variant | Change | Tag |
|---|---|---|
| V0 | target 2R | E |
| S1 | 3R | E |

## 5. Splits (Phase 8)

| Market | Development | Validation | Hold-out (opened once) |
|---|---|---|---|
| NIFTY, BANKNIFTY | 2016-01 to 2021-12 | 2022-01 to 2023-12 | 2024-01 to the end |
| XAUUSD, EURUSD, GBPUSD, NAS100 | first day to 2019-12 | 2020-01 to 2022-12 | 2023-01 to the end (2023-02 to 2023-07 excluded) |
| US30, AAPL | 2024-01 to 2024-12 | 2025-01 to 2025-06 | 2025-07 to the end |

**The post-publication span** (each video's upload date to the end) is reported separately. It is the only period the presenter could not have seen.

**Choosing a variant (decided before any run)**
- For each strategy and market, the variant with the highest **net mean R over development + validation** is chosen, among variants with ≥ 30 trades there. A tie goes to V0.
- The hold-out is evaluated once, for V0 and for the chosen variant. No rule or parameter changes after the hold-out is opened.

**Walk-forward.** From the fourth calendar year on, each year trades the variant with the best net mean R over all prior years. The stitched out-of-sample years are reported.

## 6. Classification gates (Phase 9)

**Candidate for paper trading** requires every one of:
1. hold-out net mean R > 0 with t ≥ 2.0;
2. a Holm-adjusted one-sided p < 0.05 across all hold-out tests in the study;
3. development and validation net mean R both > 0;
4. at least 50 hold-out trades;
5. hold-out net mean R > 0 at 2× costs and with a one-minute delayed entry;
6. the top 5 hold-out trades provide less than 50% of the hold-out net profit;
7. hold-out maximum drawdown < 20% at 1% risk.

The other classes:
- **Needs more evidence:** the hold-out and development+validation net mean R are both > 0, but at least one gate fails.
- **Not supported:** any other outcome with enough trades.
- **Unable to evaluate:** no usable data, or fewer than 30 trades in total.

## 7. Robustness (Phase 8), run on V0 and the chosen variant

- **Costs:** ×0 (gross), ×2; slippage ×3.
- **Delayed entry:** fill one minute later; fill one bar later.
- **Sensitivity:** target ±0.5R.
- **Concentration:** share of net profit from the top 5 trades and the top 10% of trades.
- **By period:** each year, and each split.

## Change log

- 2026-11-07: first version (before any run).
- 2026-11-07, before any backtest run (data blocker, no results seen):
  - **What happened:** the Dukascopy fetch of US30 and AAPL failed. In about 40 minutes it saved 3 days; the rest were HTTP 503 and connection timeouts, even at one request every 6 seconds. No other US30 or AAPL minute history is on disk.
  - **BB-14** therefore runs on **NAS100** (HistData NSXUSD), which kakFchv-ylo sets as "homework" (E). Its point thresholds are scaled from US30 at about 40,000 to a share of price:
    - poke filter 10 points → 0.025%·p;
    - stop buffer 2 points → 0.005%·p.
  - **BB-12** runs on XAUUSD only. Its US30 market is dropped.
  - **BB-15** (Apple) is **unable to evaluate**, blocked on data.
  - The US30/AAPL rows of the split table are unused.
