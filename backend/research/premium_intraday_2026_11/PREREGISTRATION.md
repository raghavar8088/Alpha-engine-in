# Premium Intraday Strategies: pre-registration (frozen 22 Nov 2026, before the final period was opened)

The machine-readable record is [prereg.json](prereg.json). Its sha256 is printed by `freeze.py`, and
`run_replay.py final` refuses to run without it. This file explains the same record in prose.

## What is frozen
- **Rules.** The six new strategies are defined in `premium-intraday-service/pis/strategies.py`. The workflow,
  sector, fill, risk and cost code is the rest of `pis/`. Every one of those files is pinned by its sha256 in
  `prereg.json` (`code_sha256`).
- **The one fitted choice.** Each strategy's target multiple is chosen from 1.5R, 2R and 3R by walk-forward. For the
  final period, the choice made on Nov 2025 – Apr 2026 is frozen in `frozen_final_targets`.
- **Promotion criteria.** These are in `criteria`, and long and short are judged separately.
  - **Backtest Qualified** needs all of the following:
    - Walk-forward out-of-sample: at least 60 trades, mean net R > 0, and at least 3 of 4 folds positive.
    - Final period: at least 30 trades, mean net R > 0, profit factor ≥ 1.10, mean net R ≥ 0 at twice the
      slippage, and book drawdown ≤ 5%.
    - Pooled walk-forward plus final: day-clustered t ≥ 2.0, still positive without the best 5% of days, and no
      single stock carrying more than 35% of the profit.
  - **Portfolio Eligible** also needs forward paper evidence:
    - at least 30 trades over at least 15 sessions, with forward mean net R > 0;
    - pooled backtest-plus-forward t ≥ 3.29, the Bonferroni bar for K = 100 trials;
    - forward results not significantly worse than the backtest;
    - a missed-entry rate of 50% or less, and no unresolved exits.
- **Trials counted.**
  - 144 configurations were replayed: 6 strategies × 2 sides × 4 ladder levels × 3 targets.
  - Of these, 36 are candidates, because only each strategy's primary level can qualify.
  - 62 imported strategies are judged on the same criteria.
  - K = 100 is used for the multiple-testing bar.

## Periods
| Period | Dates | Use |
|---|---|---|
| Development | 4 Nov 2024 – 30 Apr 2026 | Four walk-forward folds (train 6 months, test the next 3) |
| Final | 1 May 2026 – 3 Nov 2026 | Untouched; opened once, after this freeze |
| Post-final | 4 – 20 Nov 2026 | Only if the box's bars can be read; reported separately |

## Development-phase fixes (made before the freeze, all from code defects, none from results)
1. **Previous close on two price bases.** The broker's 5-minute history is back-adjusted for later splits and
   bonuses; NSE's bhavcopy is not. For example, HDFCBANK's June 2025 bars read about ₹990 while the bhavcopy says
   ₹1,978.9. That created fake −50% gaps. The official close is now used only when it is within 2% of the last bar.
2. **Corporate actions on the day.** A stock opening more than 15% from its previous close is set aside for the day
   as a probable corporate action.
3. **t with too few days.** Day-clustered t is reported only with 10 or more trading days; two similar days had
   produced t = −897.

The development run was repeated after fix 1. Both runs are kept in `D:/premium_intraday_data/runs`.

## What the development period showed (before the freeze)
- Nearly every configuration loses after costs out of sample.
- The best is N01 Sector-confirmed ORB at L1, long: +0.07R a trade over 130 trades, t 0.81, 3 of 4 folds
  positive. That is far below the bar.
- N04 Failed-gap reversal fires about once a month as written (14 triggers in 18 months at L0), so it cannot
  reach a qualifying sample.
- N06's rule without news loses 0.4R a trade on the long side.

None of this was used to change a rule.
