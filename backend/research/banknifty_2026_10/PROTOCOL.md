# BANKNIFTY option buying — research protocol (fixed 2026-10-11, before any full-sample result)

Written after the data download and the pricing-model check, and before the replays of the
complete 2016-2026 sample. Only three smoke-test strategies were run on 2016-17 data, to test the code;
they are not looked at again.

## What is tested (every trial is counted)

| Source | Trials |
|---|---|
| Library intraday option-buying strategies (strategy_service, 5m + 15m), live-desk rules | 167 |
| Library daily swing strategies (1d), real option closes | 48 |
| BANKNIFTY intraday rules (app/services/banknifty_strategies.py) | 66 |
| BANKNIFTY daily rules (same file) | 16 |
| **Total** | **297** |

No family, parameter or variant is added after results are seen. Contract, costs and
periods are fixed:

* **Contract**: BANKNIFTY monthly options (the only expiry listed since Nov 2024), lot 30,
  strike step 100, ATM by the price at entry. Intraday: nearest monthly with >= 7 sessions
  left. Daily: nearest monthly with >= 15 sessions left, rolled at <= 3.
* **Prices**: daily rules trade REAL NSE closing premiums. Intraday rules are priced by the
  model in `bn_price.py` (previous session's real smile for that contract, India VIX scaling,
  variance clock), whose accuracy against real closes is reported in `model_check.json`.
* **Costs**: Angel One rate card at today's rates (Rs20/order, STT 0.15% of premium sold,
  exchange 0.0355%, SEBI, stamp, GST) + a half spread of 0.25% of premium each side.
  Robustness: everything again at a 0.50% half spread.
* **Periods**: EXPLORE 2016-01-01 .. 2021-12-31; HOLDOUT 2022-01-01 .. 2026-10-09.
* **No entry on a bar ending after 15:00**; intraday square-off 15:15.

## Gate (net rupees per trade, 1 lot)

* **Tier A — PASSED**: EXPLORE n >= 60 (daily rules: 25), mean > 0, t >= 2.0; HOLDOUT
  n >= 40 (daily: 15), mean > 0, t >= 2.0; deflated Sharpe >= 0.95 over all 297 trials;
  still positive in both periods at the 0.50% half spread; positive in >= 60% of the calendar
  years with >= 5 trades.
* **Tier B — CONFIRMED (weak)**: EXPLORE mean > 0 with t >= 2.0; HOLDOUT mean > 0 with t >= 1.0;
  still positive in both periods at the 0.50% half spread.
* **Tier C — POSITIVE BOTH**: mean > 0 in both periods (with the same minimum trade counts).
  Expected by luck alone: ~25% of all trials. Shown, never described as proven.
* t is day-clustered for intraday rules (trades on one day summed into one observation);
  per-trade for daily rules (one position at a time, so trades do not overlap).

## Choosing ten

Rank Tier A, then B, then C; inside a tier by HOLDOUT t, then deflated Sharpe. Walk the list and
skip a candidate whose daily P&L correlates > 0.7 with one already chosen (on shared trading
days) or whose family already has three chosen. The first ten go to the NIFTY BANK paper desk,
each labelled with its tier. Paper only: a forward record at real bid/ask decides anything
further, and real money stays locked.

## Luck line (reported with the results)

Under no edge at all, with 297 trials: about 74 would be positive in both periods (Tier C),
about 1 would reach Tier B, and about 0.2 Tier A. The counts actually observed are reported
next to these.

## Amendment — made AFTER the results were known (2026-10-12), disclosed as such

Result under the protocol as written: Tier A 0, Tier B 0, Tier C 11 of 280 eligible trials
(17 had too few trades). Walking the ranking with the "three per family" rule stopped at six:
the rule counted all 48 library swing strategies — written by different authors, on different
ideas — as ONE family, so the 4th-8th positive ones were cut although they barely correlate
with each other (max daily-P&L correlation 0.49 among them).

Amendment: the "three per family" rule is dropped. The near-duplicate filter stays (daily P&L
correlation > 0.7 with a strategy already chosen): it removes `mr_btst_finnifty` (0.76 with
`wt_btst`), the only pair above it. No evidence threshold, tier, period, cost or price changed.
The ten chosen are therefore exactly the ten DISTINCT strategies that made money in both periods.

Read with that in mind: none is statistically proven, the weakest four are barely positive after
2022, and two of them (`swing_cci`, `bn_gap_go_80bp_1515`) turn negative after 2022 at double
spreads. The forward paper record, at the real order book, is what decides.
