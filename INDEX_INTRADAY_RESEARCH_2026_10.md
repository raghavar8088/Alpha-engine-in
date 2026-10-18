# Indian Index Intraday Trading — research report

*October 2026. Code and record: `backend/research/index_intraday_2026_10/`. Module: `/index-intraday`
(sidebar: Trading → Indian Index Intraday Trading).*

## The answer

**No intraday strategy on an Indian index passed the test.** We ran 1,464 strategy variants on
2016–2023 one-minute data: 14 families, 8 indexes, bars from 1 to 30 minutes. Every trade was
charged Angel One's intraday fees and each ETF's measured spread.

| Stage | Variants |
|---|---|
| Passed selection (2016–21) | 45 |
| Also passed validation (2022–23) | 15 |
| Validated (stage 3) | **0** |
| Paper Trading Approved | **0** |

The 2024–26 holdout was kept for Validated strategies only, so it was **never opened**.

Three findings explain the result:

1. **The costs are larger than the edge.** A ₹10 lakh intraday round trip in a liquid index ETF
   costs 6–8 bp: about 4.0 bp of charges plus the spread paid on the way in and out. In 2016–21
   the breakout families made about 10 bp a trade before costs, which was just enough. In 2022–23
   that gross edge fell to 1–3 bp. On the liquid indexes, **2** of the 536 breakout and trend
   variants were profitable after costs in 2022–23 (by +0.7 and +2.2 bp), against 104 (19%) in
   2016–21.
2. **The only cluster that survived 2022–23 is an artifact.** All 15 survivors are NIFTY NEXT 50
   breakouts. That index's one-minute prices lag its constituents: its one-minute returns are
   autocorrelated at +0.08, against −0.32 for its ETF, JUNIORBEES. Run on JUNIORBEES's own prices,
   which is what a real order would trade, every one of the 15 loses money: **−3.3 to −13.5 bp a
   trade** over 2020–23.
3. **Mean reversion loses before costs.** Bollinger, RSI and VWAP reversion lose 1.6–4.4 bp a
   trade before any charge is paid.

Nothing here was found to make money, and the report says so rather than presenting a "best" one.
The module still runs any of the 1,464 variants in paper trading as an **observation**, labelled
with its research status. It never places a real order.

---

## 1. Scope

- **Cash market and indexes only.** No options, futures, leverage or derivatives. A position is
  long or short for at most one session and is squared off by 15:12.
- **Indexes:** NIFTY 50, NIFTY BANK, NIFTY FINANCIAL SERVICES, NIFTY NEXT 50, NIFTY 100,
  NIFTY MIDCAP SELECT, SENSEX and BANKEX, plus India VIX for the regime filters.
- **Two execution models.** An index cannot be bought, so the module keeps two models apart:
  - **Index model (simulation):** signals and fills on the index level, charged what its tracking
    ETF would cost. The research used this route.
  - **ETF model (real instrument):** the tracking ETF filled at its live bid/ask, in whole units,
    with Angel's charges and an order capped by the ETF's liquidity. BANKEX has no ETF, so it can
    only be simulated.

## 2. Data

Source: Angel One SmartAPI `ONE_MINUTE` candles. These are the app's own licensed broker feed,
fetched on the server by `ii_fetch.py` at 30 days a request.

| Series | History | Sessions kept | Notes |
|---|---|---|---|
| NIFTY 50, BANK, FIN SERVICE, NEXT 50, NIFTY 100, SENSEX | 2016-01-01 → 2026-10-09 | 2,621–2,632 each | complete |
| NIFTY MIDCAP SELECT | 2022-01-10 → | 1,158 | launched 2022 — **no 2016–21 data** |
| BANKEX | 2023-01-12 → | 896 | Angel's history starts 2023 — **no 2016–21 data** |
| India VIX | 2016-01-01 → | 2,569 | see the fixes below |
| NIFTYBEES / BANKBEES / JUNIORBEES | 2019–20 → | 1,515–1,651 | liquid enough to test |
| FINIETF / MIDSELIETF / NIF100BEES / SENSEXIETF | 2023–24 → | 4–46 | so thinly traded that most sessions have empty minutes |

**Quality rules.** Each rule is counted in the loader's quality report.

- A session is kept only if it has a 09:15 print and at least 360 of its 375 minutes.
- A missing minute inside a kept session is filled flat at the last close, with zero volume.
- Rows outside 09:15–15:29 are ignored.

**Three defects were found and fixed** (section 7):

| Defect | Rows affected | Fix |
|---|---|---|
| Angel's `-0.01` placeholder prices in FINNIFTY (8, 10 and 11 August 2022) | 4 | Any print at or below zero is dropped |
| Stray 09:15 prints 15–19% off the market in NIFTYBEES, BANKBEES and JUNIORBEES (2020–21), and similar prints in the four thin ETFs | 28 + 36 | An index or ETF print more than 15% from its session's median is dropped. Index-wide circuit breakers halt trading at 10/15/20%, so such a print cannot be real. A session left without a sane 09:15 print is not kept |
| India VIX served divided by 100 (2016-01-01 → 2016-09-08, and 2021-03-01) | 63,837 | Values under 2 are multiplied by 100. VIX has never traded below 8 |

## 3. Costs

Every trade is charged Angel One's intraday rate card through the app's own fee model
(`angel_fees.round_trip`) at the position's actual size:

- brokerage of min(₹20, 0.25%) a side;
- STT of 0.025% on the sell;
- stamp duty of 0.003% on the buy;
- exchange charges of 0.00297%, plus SEBI and IPFT fees;
- GST of 18% on the services.

That comes to **4.02 bp for a ₹10 lakh round trip**. The spread is added a side, from each ETF's
**measured** effective half-spread (`ii_spreads.py`: Roll and Corwin–Schultz estimators on 2024–26
minute prices). The table never goes below the research's starting assumption.

| Index | Cash route | Spread a side: research / measured | All-in round trip: research / measured | Median ETF value a traded minute | Intraday-tradable at ₹10 lakh? |
|---|---|---|---|---|---|
| NIFTY 50 | NIFTYBEES | 1.0 / 1.0 bp | 6.0 / 6.0 bp | ₹20.2 L | yes |
| NIFTY BANK | BANKBEES | 1.5 / 1.7 | 7.0 / 7.4 | ₹4.1 L | yes |
| NIFTY NEXT 50 | JUNIORBEES | 2.0 / 2.0 | 8.0 / 8.0 | ₹2.3 L | marginal |
| SENSEX | SENSEXIETF | 3.0 / 4.5 | 10.0 / 13.0 | ₹0.2 L | no |
| FINNIFTY | FINIETF | 5.0 / 5.0 | 14.0 / 14.0 | ₹0.2 L | no |
| NIFTY 100 | NIF100BEES | 3.0 / 21.2 | 10.0 / 46.4 | ₹0.4 L | no |
| MIDCAP SELECT | MIDSELIETF | 6.0 / 9.4 | 16.0 / 22.8 | ₹0.1 L | no |
| BANKEX | none | 1.5 / 1.7 (BANKBEES) | 7.0 / 7.4 | — | simulation only |

The research rounds ran on the research column. It under-charges the four thin ETFs, but their
indexes failed even so. The Backtesting Lab offers both columns.

## 4. What was tested

| Family | What it does | Bar lengths |
|---|---|---|
| Opening-range breakout | Break of the first 5/15/30/60 minutes' high or low; stop or close entry; stop at the opposite side, the middle or an ATR | 1m |
| Previous-day high/low | Stop orders at yesterday's high and low | 1m |
| Volatility breakout | Stop orders at the open ± k × prior-day ATR (k 0.25–1.0); optional start/end time or VIX regime | 1m |
| Trend-day continuation | At 10:15/11:15/12:15, follow a day already k × ATR from its open | 1m |
| Gap fade / follow | An open k × ATR beyond yesterday's close, faded or followed from 09:20 | 1m |
| Intraday momentum (Gao, Han, Li & Zhou 2018) | The first half hour's return sets the last half hour's direction | 1m |
| EMA crossover | 9/21 and 20/50 state | 3, 5, 10, 15, 30m |
| Supertrend (+ADX filter) | 10 × 2 or 3, with ADX > 25 optional | 5, 10, 15, 30m |
| RSI | 14 momentum (60/40); 2 and 14 reversion (80/20) | 5, 10, 15, 30m |
| Bollinger Bands | 20 × 2/2.5 reversion; band walk | 5, 10, 15, 30m |
| VWAP (a time-weighted average for an index) | Reversion beyond k × ATR; trend after 10:00 | 5, 10, 15, 30m |
| Trend pullback | A 5m dip below EMA20 bought back inside a 15m uptrend | 5/15m |
| Multi-timeframe | A 5m EMA cross taken only with the 30m trend | 5/30m |
| VIX regime switch | High VIX: the 15m ORB; low VIX: Bollinger reversion | 5/15m |

**Exits** (8 kinds), each combined with the families it fits:

- held to the 15:12 square-off;
- 0.5 ATR stop, then square-off;
- 0.5 ATR stop with a 2R target;
- 0.5 ATR stop with a 0.5 ATR trail;
- 0.75 ATR stop with a 1 ATR trail;
- 0.75 ATR stop with a signal exit;
- signal exit only;
- 0.5 ATR stop with a signal exit and a 60-minute limit.

ATR is the 14-day ATR of *prior* days. Every family has to signal by 14:30 (14:45 for intraday
momentum), and everything is squared off at 15:12.

| Round | Variants × 8 indexes | Why | Passed selection | Passed validation |
|---|---|---|---|---|
| 1 | 108 → 864 trials | every family, a grid of the usual settings | 12 | 4 |
| 2 | 25 → 200 | round 1's only family with a gross edge above costs: the breakouts | 23 | 9 |
| 3 | 18 → 144 | larger moves a trade, so costs weigh less: trend days, 60-minute ORB, late starts | 10 | 2 |
| 4 | 32 → 256 | coverage: round 1's indicator grid at the 10m and 30m bars it had left out | 0 | 0 |
| **Total** | **183 → 1,464** | | **45** | **15** |

## 5. Protocol

The protocol was fixed before round 1 ran, and every trial is in the record (`data/stage3.csv`).

- **Selection, 2016–21** (stage 1). A variant needed all of:
  - 150+ trades;
  - +1.0 bp a trade or more after costs;
  - a daily-return Sharpe of 0.5 or more;
  - a profit factor of 1.10 or more;
  - a profit in at least 4 of the 6 years;
  - still positive at 1.5× costs.
- **Validation, 2022–23** (stage 2): net > 0, Sharpe > 0, profit factor > 1.
- **Stage 3, all on 2016–23:**
  - **Luck.** The deflated Sharpe ratio must be at least 0.95. The trial count is the *effective*
    number of independent strategies among the 1,384 with 100+ trades, which works out at **72**
    (the larger of the participation ratio and the number of components that explain 90% of the
    variance). The best of 72 zero-edge strategies would show an annual Sharpe of about **0.86** by
    chance alone.
  - **Neighbours:** nearby parameter sets keep at least half the Sharpe.
  - **Breadth:** profitable on at least 2 related indexes.
  - **Walk-forward:** re-picking the family's best every 6 months is profitable over 2018–23.
  - **Tradability:** the same rules run wholly on the ETF's own minute prices over 2020–23 make
    money. This gate was added after round 2 and before any holdout number existed, once the NIFTY
    NEXT 50 autocorrelation was found.
  - **Monte Carlo** (reported, not a gate): a block bootstrap of the daily returns.
- **Holdout, 2024-01-01 → 2026-10-09.** It was to be run once, on Validated strategies, on both the
  index and the ETF. **It was not opened.**

**No look-ahead.** Every family is computed on bars up to the decision minute, and stop entries
trigger on the minute's own high or low. A gap through a stop fills at the open. When a minute
touches both the stop and the target, the stop is assumed to have hit first. A test cuts real days
off at minute *u* and checks each family's decision against the full-history computation:
2,438 checks, no mismatch, and no action before the trigger minute.

## 6. Results

**By family** (median per trade, variants with 150+ selection trades):

| Family | Variants | Passed selection | Passed validation | Gross 2016–21 | Net 2016–21 | Net 2022–23 | Best variant | Why the best was rejected |
|---|---|---|---|---|---|---|---|---|
| Volatility breakout | 240 | 38 | 14 | +10.1 bp | +0.8 | −5.8 | NEXT 50, k 0.75, low VIX, trail | luck: deflated Sharpe 0.946; also −10.2 bp on the ETF and weak neighbours |
| Trend-day continuation | 96 | 5 | 0 | +11.5 | +2.6 | −5.0 | NIFTY, 12:15, k 0.7, wide trail | 130 trades in 2016–21 (needs 150) |
| Previous-day high/low | 80 | 1 | 1 | +6.1 | −3.4 | −8.7 | NEXT 50, 09:30–14:30, trail | luck: deflated Sharpe 0.23; −11.4 bp on the ETF |
| Opening-range breakout | 384 | 0 | 0 | +5.4 | −3.2 | −7.0 | NEXT 50, 60-min range, wide trail | negative at 1.5× costs |
| Gap fade / follow | 64 | 1 | 0 | +3.2 | −4.8 | −8.1 | NEXT 50, fade 0.3 ATR | lost in 2022–23 (−2.9 bp) |
| Bollinger Bands | 96 | 0 | 0 | −2.4 | −10.6 | −9.1 | BANK, band walk, 15m | −0.9 bp after costs |
| Supertrend | 128 | 0 | 0 | −2.2 | −12.2 | −8.4 | BANK, 10×2, ADX, 30m | −2.5 bp after costs |
| Trend pullback | 24 | 0 | 0 | +4.7 | −5.0 | −7.8 | NEXT 50, trail | −1.7 bp after costs |
| Multi-timeframe | 16 | 0 | 0 | +1.6 | −7.2 | −9.0 | NEXT 50, trail | −2.4 bp after costs |
| RSI | 96 | 0 | 0 | −0.2 | −9.1 | −8.7 | BANK, 14 reversion, 30m | −6.5 bp after costs |
| VWAP | 80 | 0 | 0 | −3.1 | −10.7 | −9.6 | BANK, reversion 0.5, 10m | −9.8 bp after costs |
| EMA crossover | 112 | 0 | 0 | +2.4 | −7.2 | −7.7 | NEXT 50, 20/50, 10m | −4.1 bp after costs |
| VIX regime switch | 8 | 0 | 0 | +1.6 | −7.3 | −9.2 | BANK | −5.0 bp after costs |
| Intraday momentum | 40 | 0 | 0 | +0.9 | −7.5 | −9.0 | NIFTY, 0.25% threshold | −3.6 bp after costs |

**By index** (median per trade; share of variants profitable after costs):

| Index | Passed selection | Passed validation | Net 2016–21 | Net 2022–23 | Profitable 2016–21 | Profitable 2022–23 |
|---|---|---|---|---|---|---|
| NIFTY NEXT 50 | 25 | 15 | −1.7 bp | −2.8 | 39% | 14% |
| NIFTY 50 | 9 | 0 | −2.4 | −4.8 | 22% | 1% |
| NIFTY BANK | 11 | 0 | −2.6 | −7.1 | 26% | 1% |
| NIFTY 100 | 0 | 0 | −5.8 | −8.3 | 11% | 1% |
| SENSEX | 0 | 0 | −6.4 | −8.7 | 10% | 0% |
| FINNIFTY | 0 | 0 | −8.9 | −13.4 | 2% | 0% |
| MIDCAP SELECT, BANKEX | — | — | no 2016–21 data | | | |

**The 15 that reached stage 3.** All are NIFTY NEXT 50, and none passed. One row each; net is
the mean per trade.

| Variant | Net 2016–21 | Net 2022–23 | Deflated Sharpe (needs 0.95) | Same rules on JUNIORBEES, 2020–23 (needs > 0) | Breadth (needs 2) | Neighbours' median Sharpe |
|---|---|---|---|---|---|---|
| vol. breakout k 0.75, low VIX, trail | +15.1 | +10.1 | 0.946 | −10.2 | 2 of 4 | 0.47 (needs 0.65) |
| vol. breakout k 0.6, trail | +10.9 | +2.8 | 0.91 | −4.3 | 1 of 4 | 1.16 |
| vol. breakout k 0.75, trail | +12.8 | +3.9 | 0.89 | −4.1 | 1 of 4 | 1.00 |
| vol. breakout k 0.5 from 10:15, trail | +7.9 | +2.7 | 0.81 | −11.6 | 1 of 4 | — |
| vol. breakout k 0.75 from 10:15, trail | +11.1 | +4.7 | 0.78 | −13.5 | 2 of 4 | — |
| vol. breakout k 0.6, 2R | +9.7 | +0.9 | 0.77 | −6.0 | 1 of 4 | 0.79 |
| vol. breakout k 0.6, ATR stop to close | +9.6 | +4.2 | 0.77 | −5.0 | 1 of 4 | 0.80 |
| vol. breakout k 0.75 until 11:30, trail | +17.2 | +1.1 | 0.64 | −3.3 | 0 of 4 | — |
| vol. breakout k 0.5, low VIX, trail | +7.7 | +3.1 | 0.58 | −9.7 | 0 of 4 | 0.57 |
| vol. breakout k 0.75, ATR stop to close | +8.6 | +6.7 | 0.51 | −5.3 | 1 of 4 | 0.81 |
| vol. breakout k 0.75, 2R | +8.4 | +3.7 | 0.50 | −6.3 | 1 of 4 | 0.79 |
| vol. breakout k 0.75 until 11:30, ATR stop | +15.4 | +7.2 | 0.47 | −4.1 | 0 of 4 | — |
| vol. breakout k 0.75, wide trail | +8.7 | +5.1 | 0.45 | −4.3 | 1 of 4 | 0.48 |
| vol. breakout k 1.0, trail | +10.5 | +4.7 | 0.32 | −7.8 | 2 of 4 | 1.23 |
| prev-day high/low 09:30–14:30, trail | +4.5 | +0.9 | 0.23 | −11.4 | 0 of 4 | 0.28 |

**Selected for paper trading: none.** Every strategy carries the status *Backtested* and states
the first gate it failed. The Strategy Dashboard shows every gate for the 15 above.

## 7. Two runs: the data defects

The first run (2026-10-11, rounds 1–3) used the data before the fixes in section 2. While this
report was being written, 31 FINNIFTY trials showed means of millions of basis points a trade in
2022–23. That led to the three defects. The loader was corrected and all four rounds and stage 3
were rerun with the same variants and gates (2026-10-12).

| | Run 1 (uncorrected) | Run 2 (corrected) |
|---|---|---|
| Trials (rounds 1–3) | 1,208 | 1,208 (+256 in round 4) |
| Passed selection | 44 | 45 |
| Passed validation | 15 | 15 (the same 15) |
| Validated | 0 | 0 |
| Effective trials / luck Sharpe | 68 / 0.85 | 72 / 0.86 (with round 4) |

The defects changed the selection numbers of only the 30 VIX-dependent trials. One of them
(NIFTY, volatility breakout k 0.75 in low VIX) now passes selection, then loses 4.3 bp a trade in
2022–23. The FINNIFTY placeholders had corrupted only validation numbers, of trials that had already
failed selection. Together, the VIX and JUNIORBEES fixes moved the 15 finalists' ETF results by up
to 2.5 bp, and all stayed negative.

Round 4 (10m and 30m) was added afterwards for coverage. Its 256 trials count in the luck
correction, and none passed selection. Run 1's record is kept in `data/run1_uncorrected_data/`.

## 8. What the module does with this

- **Strategy Dashboard:**
  - every one of the 1,464 variants with its status;
  - each family's funnel;
  - the 15 finalists with every gate;
  - each variant's full metrics for 2016–21, 2022–23 and both;
  - a monthly equity curve for the strongest 137.
- **Backtesting Lab:** the research's own simulator and cost model, run on any window of up to
  three years. On the research cost table, a 2022–23 run reproduces the catalogue's validation
  numbers exactly, which a test checks. A window that reaches 2024–26 is labelled as exploration of
  the holdout period.
- **Paper Trading Terminal.** Nothing runs by default. A user can switch any variant on with either
  model, labelled with its research status.
  - The engine ticks five seconds after every minute, 09:16–15:20.
  - It recomputes the family on about 280 sessions of history plus today's minutes. It needs at
    least 250 for the VIX regime's median; with the 81 it first loaded, 16% of VIX-regime decisions
    differed from the research.
  - It walks open positions with an exit checker that matches the backtest minute for minute, which
    a test checks.
  - It never enters a signal more than two minutes old, and squares everything off at 15:12.
- **Risk Management** (defaults, all editable):
  - 0.5% of equity at risk a trade, with volatility sizing (half the day's ATR when there's no stop);
  - a position of at most 100% of equity (no leverage);
  - a 1.5% daily loss limit, counting open losses;
  - 10 entries a day and 3 open at once;
  - an 8% drawdown halt that needs a manual reset;
  - after 3 losses in a row, a one-hour pause;
  - an optional cooldown after an exit;
  - entries 09:20–14:30 and square-off at 15:12;
  - an emergency stop that flattens everything.
  Limits refuse entries, never exits.
- **Trade Journal:** every trade with its gross, costs and net; the daily report written at 15:40;
  the equity curve; CSV export; the engine's log of entries, exits, refusals and missed signals.
- **Data upkeep:**
  - each session's candles are appended at 15:40;
  - Angel's candle endpoint refuses many calls at busy hours (7 of 16 instruments failed on
    2026-10-16). A refused instrument is retried at once, then every hour outside market hours
    (weekends included), until the store is complete. Any other missing day in the last 30 is
    fetched the same way, and the day's report is corrected;
  - the history is warmed before the open.
  Main Control's switch stops new entries, the feed (unless a position is open) and the append.

## 9. Limitations

- **Index route.** The research trades index *levels* at ETF costs. An index level is not a
  tradable price; the tradability gate exists because of this. Only NIFTY 50, NIFTY BANK and,
  marginally, NIFTY NEXT 50 have an ETF that can absorb a ₹10 lakh intraday position.
- **Spreads are estimated, not quoted.** There is no bid/ask history here. Roll and Corwin–Schultz
  are standard estimators but they are estimates. Market impact beyond the half-spread is not
  modelled; the paper engine instead caps an ETF order at a quarter of a median minute's value.
- **Fill model.**
  - Stop entries fill at their level, or at the open on a gap.
  - Market entries fill at the next minute's open.
  - Targets fill exactly at their level, and there are no partial fills.
  - In paper, market orders fill at the live price a few seconds into the minute.
- **Shorts.** An intraday ETF short is assumed to cost the same as a long; under MIS no borrow is
  needed. Income tax is not modelled.
- **VIX days.** On the 3% of days whose VIX minutes were dropped as incomplete, the research had no
  VIX regime. Live, today's VIX row always exists. No engine can know at 09:16 that today's VIX data
  will later be judged incomplete.
- **The closing auction.** Since 2026-08-03, Angel serves almost none of the index minutes from
  15:15 to 15:29: NSE's closing auction session. These days are kept when 345 of the 360 minutes
  before 15:15 are present (earlier days keep the original rule, so the 2016–23 data is unchanged).
  The missing minutes are filled flat. Every strategy squares off by 15:12, so no trade depends on
  them. But since August a day's last quarter-hour is flat, which slightly changes its close and the
  next day's previous close and ATR. This affects only the 2024–26 holdout era and live trading.
- **The luck correction is an estimate.** The effective number of independent trials is estimated
  from their return correlations.
- **The 2022 break is a hypothesis.** One candidate is the weekly-options era moving intraday
  directional flow out of the cash market. It was not tested.
- **The holdout is untouched.** "No edge" rests on 2016–23. The 2024–26 data can be explored in the
  Lab, but no strategy was chosen on it.

## 10. What would change the verdict

- **A cheaper route.** Index futures cost a fraction of the ETF round trip, but derivatives are out
  of this module's scope by design.
- **A gross edge well above 8 bp a trade that holds after 2022.** None of the 14 families showed one.
- **Something structural that minute bars cannot see**, such as order flow, auctions or
  constituent-level information. A new idea has to be registered as a new round: it is then counted
  in the luck correction, and the untouched holdout stays available to confirm it.
