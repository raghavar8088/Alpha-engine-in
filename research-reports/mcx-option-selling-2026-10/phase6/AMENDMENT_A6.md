# Amendment A6: Phase 6, crude-oil and natural-gas FUTURES, judged week by week; target "2% a week" (2026-10-24, before any A6 backtest)

## The request
The owner asked for better crude-oil and natural-gas **futures** strategies, backtested per
week, making **2% profit a week**, and said not to stop until they are found.

## The stop rule (fixed now)
**The search ends when this amendment's families are complete:**
- the discovery run;
- one run of each frozen candidate on the test period;
- a walk-forward.

**It is NOT extended in pursuit of the target.** A search that continues until a backtest
shows 2% a week will find luck, which loses real money. If nothing meets the target, that is
the answer.

## What is new compared with earlier work
- The app's earlier 22-year study (C0–C6, Oct 2026) used Yahoo's continuous futures, which
  track spot and so leave out the cost of carry. It found trend rules weak once carry was
  charged.
- This study uses **MCX's own price for every contract**, and so has two things that study
  lacked:
  - every roll and the carry are in the prices;
  - the **futures curve** (front vs next month) is known every day, which makes carry testable.
    The app's carry hypothesis HC4 was waiting for exactly this.

## Data
- MCX's official bhavcopy for every futures contract, from `download_futures.py` (to Fri 23 Oct
  2026):
  - CRUDEOIL from April 2005;
  - NATURALGAS from August 2006.
- **Prices:** parent prices with the minis' economics, as in Phases 1–5. Account figures use
  exposure, as a multiple of a ₹10 lakh account.

## Construction
- **Held contract:** the nearest expiry, rolled at the close 3 trading days before it expires.
- **Excess-return index:** `I` compounds the day-to-day change of the contract actually held
  (never a roll jump). All trend signals read `I`.
- **Carry:** annualised roll yield y = ln(front ÷ next) × 365 ÷ the days between their expiries.
  It counts only when both contracts traded that day. Positive means backwardation.
- **The week:**
  - decide at the close of a week's last trading day, using only that close and earlier;
  - hold to the next week's last close;
  - a week with no position counts as 0 and as not profitable.
- **Sizing:**
  - "1x": exposure = ±1 × the account;
  - "vol": exposure = ±(20% ÷ realised annual vol of `I` over the previous 60 days, at least
    40 days), capped at the margin limit.
- **Margin limit:** exposure ≤ 1 ÷ Angel's measured futures margin (9 Oct 2026): crude
  31.1% → 3.2×; natural gas 16.7% → 6.0×.
- **Costs, every side:**
  - ₹20 a order brokerage;
  - MCX 0.0021%;
  - CTT 0.01% on sells, stamp 0.002% on buys;
  - SEBI fee, and 18% GST;
  - slippage of max(1 tick, 2 bp). Ticks: crude ₹1, natural gas ₹0.10.
  - Every roll pays both sides on the whole position.

## Families (104 variants per instrument, 208 in total)
Modes: ls = long or short; lo = long or flat; so = short or flat.

| Code | Rule | Grid |
|---|---|---|
| TS | Time-series momentum (Moskowitz, Ooi & Pedersen 2012): the sign of `I`'s L-week return | L 4/8/13/26/52 × mode ls/lo/so × sizing 1x/vol (30) |
| MA | Moving-average crossover on `I` (fast vs slow, in days) | (5,20)/(10,50)/(20,100)/(50,200) × mode 3 × sizing 2 (24) |
| BO | Donchian breakout: long at an N-day high, short at an N-day low; exit at the opposite M-day extreme | N 20/55 × M 10/20 × mode ls/lo × sizing 2 (16) |
| CY | Carry: long if y > θ, short if y < −θ, else flat | θ 0/5%/10% × mode 3 × sizing 2 (18) |
| CT | Carry and trend together: take a position only when carry's sign and TS-L's sign agree | L 13/26 × sizing 2, mode ls (4) |
| SE | Seasonality: each calendar month takes the sign of that month's average weekly return in the data before it (re-learned each year in walk-forward) | sizing 2 (2) |
| MR | Weekly reversal: after a week beyond ±k × the 26-week weekly σ, take the opposite side for one week | k 1.0/1.5/2.0 × sizing 2 (6) |
| BH | Always long / always short (benchmarks; also candidates) | sizing 2 (4) |

## Selection (discovery: weeks of 2008–2016)
- **Eligibility.** Every condition must hold:
  - net > 0 after costs, and net > 0 at 2× costs;
  - weekly t ≥ 2.0;
  - weekly PF ≥ 1.10;
  - at least 26 weeks with a position.
- **Ranking.** Rank by the bootstrap 5th percentile of the mean weekly return (5,000 draws, seed
  7). The best eligible variant per family and instrument is frozen.

## Tests (each frozen candidate run ONCE)
| | |
|---|---|
| Test | Weeks of Jan 2017 – Oct 2026 |
| Walk-forward | Each family re-picked every year (2017–2026) on all earlier years, then traded that year |

**Verdicts on the test:**
1. **Tradeable:**
   - net > 0, and net > 0 at 2× costs;
   - annualised Sharpe ≥ 0.30.
2. **Your target, average:** L* = 2% ÷ mean weekly return is the leverage needed to average 2%
   a week. It passes if:
   - L* × the average gross exposure stays within the margin limit; and
   - the levered account never loses everything (max drawdown < 100%).

   "Practical" also requires a max drawdown ≤ 50%.
3. **Your target, every week:** the share of weeks at or above +2%, at L*.

## Disclosures fixed now
- **The years are not untouched.** The app's earlier study looked at 2004–2026 with different
  (Yahoo) data and rules. So the 2017–2026 test is clean of THIS study's selection, but not of
  the whole app's.
- **Multiple testing:** 208 variants.
- **Intraday is not tested.** There are no historical intraday MCX prices to test on, and the
  app's intraday futures record (37,053 trades) already lost before costs.
