# Amendment A7: Phase 7, the last route to "2% a week": diversified cross-commodity portfolios (2026-10-24, before any A7 backtest)

## Why this is the route that is left
2% a week, compounded, is a log-growth of 52 × ln(1.02) = 1.03 a year.

**The ceiling.** A strategy with annualised Sharpe ratio S, run at its growth-optimal (Kelly)
leverage, grows at most S²/2 a year. Any other leverage grows it more slowly.

**What that means for the target:**
- reaching 2% a week therefore needs **S ≥ 1.44**, sustained, out of sample, after costs;
- even at that S, full Kelly has a 50% chance of halving the account at some point.

**What we have:**
- every single strategy found in Phases 1–6 has an out-of-sample S of 0.2–0.6;
- the only way to raise S is to combine many weakly related return streams.

This amendment tests the best-documented diversified futures strategies across every MCX
commodity with a long history. It also measures one combined portfolio of everything with
evidence.

## Universe and data
- **Nine MCX futures:**
  - bullion: GOLD, SILVER;
  - base metals: COPPER, NICKEL, ALUMINIUM, ZINC, LEAD;
  - energy: CRUDEOIL, NATURALGAS.
- **Prices:** every contract's official bhavcopy, from `download_all.py` to Fri 23 Oct 2026.
- **Index:** a held-contract index per market (`engine6.build_daily`).
- **Roll:** 3 trading days before expiry for energy; **6 for bullion and base metals**, which are
  physically delivered, so the roll comes before the delivery period.
- **Costs and margin:**
  - Angel's MCX futures card, as in A6, with slippage of max(1 tick, 2 bp). Ticks are read from
    the data.
  - Margin uses Angel's measured futures rates (9 Oct 2026):

    | GOLD | SILVER | COPPER | NICKEL | ALUMINIUM | ZINC | LEAD | CRUDEOIL | NATURALGAS |
    |---|---|---|---|---|---|---|---|---|
    | 9.2% | 12.7% | 9.2% | 9.3% | 9.3% | 9.1% | 7.4% | 31.1% | 16.7% |

## The weekly portfolio
- **Decision:** at each week's last close, each market gets a signal s in {−1, 0, +1} from the
  family's rule.
- **Sizing:** each active market's exposure is s × 10% ÷ its 60-day realised vol (equal risk).
  A market with no vol estimate yet stays flat.
- **Hold:** to the next week's last close.
- **Portfolio return:** the sum of the markets' weekly returns after their own costs (rolls
  included), as a fraction of the account.

## Families (22 variants)
| Code | Rule | Grid |
|---|---|---|
| XM | Cross-sectional momentum: rank the markets by their L-week index return; long the top k, short the bottom k | L 4/13/26/52 × k 2/3 (8) |
| XC | Cross-sectional carry: rank by annualised roll yield (front vs next); long the most backwardated k, short the most contango k | today's carry / 4-week average × k 2/3 (4) |
| XX | Momentum + carry: rank by z(26-week return) + z(4-week average carry) | k 2/3 (2) |
| TP | Time-series momentum in every market (diversified trend) | L 4/13/26/52, plus the average of the four signs (5) |
| CP | Time-series carry in every market: long if backwardated, short if contango | today's / 4-week average (2) |
| LB | Long every market, equal risk (benchmark) | (1) |

## Selection (discovery: weeks of 2008–2016)
- **Eligibility.** Every condition must hold:
  - net > 0 after costs, and net > 0 at 2× costs;
  - weekly t ≥ 2.0;
  - at least 26 weeks in the market.
- **Ranking.** Rank by the bootstrap 5th percentile of the mean weekly return (5,000 draws, seed
  7). The best eligible variant of each family is frozen.

## Tests (each frozen candidate run ONCE), and verdicts
- **Test:** weeks of Jan 2017 – Oct 2026. Plus a walk-forward that re-picks each family every
  year on all earlier years.
- **Tradeable:**
  - net > 0, and net > 0 at 2× costs;
  - annualised Sharpe ≥ 0.30.
- **Meets 2% a week:** every condition must hold:
  - test Sharpe ≥ 1.44;
  - the leverage that averages 2% a week needs no more margin than the account holds (summed
    over markets, each at its rate);
  - the levered maximum drawdown stays below 100%.

## The combined portfolio (descriptive, composition fixed now)
**Window:** the common Jun 2024 – Oct 2026 weeks.

**Three streams:**
1. the options core (CO-1 3 lots + CO-2 3 + N-B 5 on the crude and gas minis), marked weekly as
   in Phase 4;
2. CO-1 on gold mini, 4 lots, marked weekly;
3. the best frozen A7 futures candidate, at its unit size.

**Method:**
- each stream is scaled to equal risk using its own trailing 26-week vol, starting once 26 weeks
  are available;
- report the combination's Sharpe, the Kelly ceiling, and the most it averages a week at a 30%
  and at a 50% maximum drawdown.

## Stop rule (fixed now)
- The search ends when the families above, the walk-forward and the combined portfolio are
  complete.
- It is NOT extended toward the target.

## Disclosures fixed now
- **The Kelly ceiling is optimistic.** It assumes a known Sharpe and normal returns. Real
  strategies have fat tails, and their Sharpe is estimated with error. Over-betting an
  estimated Sharpe is the usual way leveraged traders are ruined, so the real requirement is
  stricter than 1.44.
- **The years have been seen before.** The app's earlier futures study saw 2004–2026 on Yahoo
  data.
- **Multiple testing:** 22 variants.
