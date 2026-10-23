# Amendment A3: Phase 3, more structures and a second untouched test period (2026-10-23, before any A3 backtest)

## Why a second test period
The Jun 2024 - Oct 2026 holdout has already been used in Phase 1 and Phase 2, for other
strategies. A third round tested only there gets less credible every time.

Crude options also traded in **Jun 2018 - Dec 2019**: 19 monthly cycles of CRUDEOIL options,
with an ATM straddle traded on every entry day and 22-30 traded strikes a day. No strategy
selection has ever touched that period.

One caveat: Phase 1's descriptive volatility table showed 2019 in aggregate (IV 33%, RV 33%,
straddle beat the move in 75% of cycles). No strategy has ever been run on 2018-19.

## New families
Execution is exactly as in PROTOCOL.md / A2:
- fill at the close, only traded strikes;
- 1% slippage, minimum one tick;
- Angel's fee card;
- capital = margin plus premium paid;
- no devolvement.

Strikes are picked by delta as in A2.

| Family | Market | Structure | Grid |
|---|---|---|---|
| K1 | crude | calendar: sell the front month, buy the next month at the SAME strike | type: ATM straddle / put at front delta 0.25 / call at front delta 0.25; entry 15/10/5; exit at the front's expiry close or 1 day before (= 18) |
| K2 | crude | ratio: buy 1 at delta a, sell 2 at delta b, same type | put or call; (a, b) = (0.30, 0.15) or (0.25, 0.10); entry 15/10/5; stop none, or loss >= 1x the short legs' premium (= 24) |
| K3 | crude | delta-hedged strangle (10 lots), hedged at every close in whole futures lots | delta 0.25/0.35; entry 20/15/10 (= 6) |
| K4 | crude | C-E with a hedge band: re-hedge only when the gap reaches b lots per 10 | b = 2/3; entry 15/10/5 (= 6) |
| K5 | crude | rolled strangle: sell both sides at delta d0; at any close where a short leg's delta exceeds t, buy it back and re-sell that side at d0; at most 2 rolls | d0 = 0.15/0.20; t = 0.30/0.40; entry 15/10 (= 8) |
| K6 | crude | expiry-week | call or strangle; delta 0.10/0.15/0.20; entry 3/2 (= 12) |
| G1 | natural gas | calendar | same as K1 (= 18) |
| G2 | natural gas | calm-IV delta-hedged ATM straddle (10 lots) | ivpct <= 50 or <= 40; entry 15/10 (= 4) |
| G3 | natural gas | seasonal strangle: only expiries Apr-Oct, never Nov-Mar | delta 0.10/0.15/0.20; entry 15/10; stop none/1x (= 12) |
| G4 | natural gas | rolled strangle | same as K5 (= 8) |
| G5 | natural gas | ratio | same as K2 (= 24) |

That is 140 variants in total.

Additional rules:
- **Calendars:** capital = the short front leg's margin plus the long back leg's premium. No
  stop. The back leg is sold at the exit close.
- **Ratios:** the stop is measured against the short legs' entry premium, because a ratio can
  be entered for a net debit.

## Selection (discovery: crude Jan 2020 - May 2024, natural gas Mar 2022 - Apr 2024)
- A2's eligibility rules apply: coverage >= 70%, counted over the months a filter allows; net
  > 0; PF >= 1.3; t >= 1.5; net > 0 at 2x slippage; worst trade >= -30% of capital.
- The best eligible variant per family, ranked by bootstrap 5th percentile, is frozen.

## Tests (each frozen candidate is run ONCE on each)
| | Crude | Natural gas |
|---|---|---|
| T1: Jun 2018 - Dec 2019, parent prices, never used | must pass | (no data) |
| T2: Jun 2024 - Oct 2026, the minis' own prices | must pass | must pass |
| Walk-forward per family (A2 method) | reported | reported |

**Pass rule, on each test:**
- net > 0;
- PF >= 1.15;
- net > 0 at 2% slippage;
- worst trade >= -45% of capital.

A crude family must pass BOTH T1 and T2.

## Re-test of earlier passers on T1 (fixed now)
CO-1, CO-2, CO-3 (Phase 1) and C-B, C-C, C-E (Phase 2) each run ONCE on T1, unchanged, with
the same pass rule. This is the first time any of them meets 2018-19. A failure is reported
as a failure.
