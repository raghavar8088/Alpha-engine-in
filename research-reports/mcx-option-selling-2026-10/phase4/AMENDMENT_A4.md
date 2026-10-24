# Amendment A4: Phase 4, one trade a week, selling AND buying; target "at least 2% every week" (2026-10-24, before any A4 backtest)

## The request
The owner asked for crude oil and natural gas option strategies, selling and buying, that are
profitable **every week, by at least 2% a week**. Compounded, 2% a week is +180% a year. This
amendment tests that target directly, week by week, on real MCX prices.

## Data
- MCX's official bhavcopy, refreshed to Fri 23 Oct 2026 with `refresh_mcx.py`: 28 live contracts
  re-fetched; finished contracts unchanged.
- Built with `build_dataset.py`; cycles from `engine.build_cycles` as in Phases 1–3.

## The week
- **Week:** a Monday–Friday calendar week.
- **Entry:** at the close of the previous week's last trading day.
- **Exit:** at the close of the week's last trading day. It is earlier if:
  - a stop or target triggers (checked at closes); or
  - the contract expires during the week (exit at the expiry close).
- **Contract:** the front month, meaning the nearest expiry strictly after the entry date that
  traded on that date.
- **"Skip expiry week" variants:** skip any week in which that contract expires on or before the
  week's last trading day.
- **WB8 is the exception:** it enters at the close before a report day and exits at the report
  day's close. Report days are crude Wednesday (EIA) and natural gas Thursday (storage), taken
  by weekday.
- **Weekly return:** the week's P&L divided by that week's capital. A week with no trade counts
  as 0 and as **not profitable**.

## Execution (exactly as PROTOCOL.md / A2)
- **Fills:** at the daily close ± 1% slippage (minimum one tick). The slippage is 3× at exit if
  that leg did not trade.
- **Fees:** Angel's MCX option fee card per leg. Delta-hedge futures as in A2: ₹20 an order,
  exchange fees, CTT or stamp duty, GST and 2 bp slippage.
- **Strikes:** by Black-76 |delta| on traded closes, accepting 0.5–1.5× of the target. Only OTM
  strikes, and only strikes that traded that day. ATM is the nearest strike where both the call
  and the put traded.
- **Capital:**
  - for a short: 1.2 × the measured futures margin rate × notional per short leg, with no netting;
  - for a long: the premium paid;
  - for a delta-hedged position: the hedge's futures margin is added.

## Families (494 variants per instrument; run on both crude and natural gas, 988 in total)
Abbreviations used in the grids:
- **ivp:** the causal percentile of front-month ATM implied vol against the previous 250
  trading days (as in A2).
- **stop k×:** exit at a close where the loss is at least k × the credit.
- **tpX/slY:** exit at a close where the position is up X% or down Y% on its premium.

**Selling (348 per instrument)**

| Code | Structure | Grid |
|---|---|---|
| WS1 | Short strangle | delta 0.10/0.15/0.20/0.25/0.30; stop none/1×/2×; filter none/ivp ≥ 50/ivp ≤ 50; expiry week trade/skip (90) |
| WS2 | Short ATM straddle | stop 3 × filter 3 × expiry 2 (18) |
| WS3 | Short put | delta 0.10/0.15/0.20/0.30 × stop 3 × filter 3 × expiry 2 (72) |
| WS4 | Short call | same as WS3 (72) |
| WS5 | Trend side: short put if the futures are above their 20-day SMA, else short call | delta 0.15/0.25/0.35 × stop 3 × filter 3 × expiry 2 (54) |
| WS6 | Iron condor (short, long delta) | (0.20, 0.08)/(0.25, 0.10)/(0.30, 0.15) × stop none/1× × filter 3 × expiry 2 (36) |
| WS7 | Delta-hedged ATM straddle, 10 lots, re-hedged at every close | filter 3 × expiry 2 (6) |

**Buying (146 per instrument)**

| Code | Structure | Grid |
|---|---|---|
| WB1 | Long ATM straddle | filter none/ivp ≤ 20/ivp ≤ 35/IV < RV20 × exit week-end/tp50-sl40 × expiry 2 (16) |
| WB2 | Long strangle | delta 0.25/0.15 × filter none/ivp ≤ 20/ivp ≤ 35 × exit week-end/tp100-sl50 × expiry 2 (24) |
| WB3 | Trend option: call if futures > SMA20 and SMA10 > SMA20; put if both are below; else no trade | delta 0.50/0.35/0.20 × exit week-end/tp50-sl50/tp100-sl50 × expiry 2 (18) |
| WB4 | Breakout: call if the futures close above the prior N-day high; put if below the N-day low | N 10/20 × delta 0.50/0.30 × exit 3 × expiry 2 (24) |
| WB5 | Momentum: call if last week's futures return > +x; put if < −x | x 2%/4% × delta 0.50/0.30 × exit 3 × expiry 2 (24) |
| WB6 | Reversal: the opposite of WB5 | same as WB5 (24) |
| WB7 | Far-OTM "lottery" at delta 0.10 | call + put / call / put × exit week-end/tp200 × all weeks / expiry weeks only (12) |
| WB8 | Report-day buy | ATM straddle / delta-0.25 strangle × expiry trade/skip (4) |

## Selection (discovery: crude Jan 2020 – May 2024; natural gas Mar 2022 – Apr 2024; parent prices)
- **Eligibility.** Every condition must hold:
  - coverage ≥ 70% of the weeks the variant's own conditions allow;
  - net > 0, and net > 0 at 2× slippage;
  - PF ≥ 1.3;
  - weekly t ≥ 1.5;
  - sellers only: worst week ≥ −30% of capital. A buyer's loss is capped at its premium.
- **Ranking.** Among eligible variants, rank by the bootstrap 5th percentile of the **mean
  weekly return over all weeks**. Flat weeks count as 0. Uses 5,000 draws, seed 7, as in
  search.py.
- **Freezing.** The best eligible variant of each family is frozen before any test is run.

## Tests (each frozen candidate run ONCE on each)
| | Crude | Natural gas |
|---|---|---|
| T1: Jun 2018 – Dec 2019, parent prices | must pass | (no options then) |
| T2: Jun 2024 – Oct 2026, the minis' own prices | must pass | must pass |
| T2 on parent prices | reported | reported |
| Walk-forward per family (A2 method; crude training from 2020) | reported | reported |

**Three verdicts on each test:**
1. **Your target, literally:** every week of the period returned at least +2% of capital. The
   share of such weeks is reported for every candidate.
2. **Near target:** mean weekly return ≥ +2.0% of capital, at least 75% of all weeks
   profitable, and verdict 3.
3. **Tradeable** (the Phase 1–3 rule, on weekly trades):
   - net > 0, and net > 0 at 2× slippage;
   - PF ≥ 1.15;
   - sellers only: worst week ≥ −45% of capital.

A crude family must pass on both T1 and T2.

## Translation to a ₹10 lakh account (descriptive)
For each candidate, f* = 2% ÷ its mean weekly return: the share of the account that must be
committed each week (as margin or as premium) to average 2% a week. Reported with it:
- the worst week at f*;
- the share of weeks reaching 2% at f*;
- whether f* exceeds 100%, which is impossible.

## Reference, not selection
The weekly mark-to-market profile of CO-1, CO-2 and N-B on T2 (marked at each Friday close),
to show what the strategies that held up look like week by week.

## Disclosures fixed now
- **T1 and T2 were used before, for other strategies:** T2 in Phases 1–3 and T1 in Phase 3.
  None of these weekly families has ever been run on either.
- **Multiple testing:** 988 new variants. The tests and the walk-forward guard against luck but
  cannot remove it.
- **Not testable:** intraday strategies. No source we can reach has historical intraday prices
  for these options, so every decision here is at a daily close.
