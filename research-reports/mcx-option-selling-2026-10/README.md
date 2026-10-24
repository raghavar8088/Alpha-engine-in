# MCX Crude Oil Mini / Natural Gas Mini option selling: research (Oct 2026)

Reproduce it in this order. Python 3.12 with pandas, numpy and curl_cffi; run with
`PYTHONPATH=<repo>/shared`.

| Step | Command | What it does |
|---|---|---|
| 1 | `python download_mcx.py <data>` | Fetches MCX's official bhavcopy for every option and futures contract (about 460 requests, paced, cached, resumable) |
| 2 | `python build_dataset.py <data> <work>` | Builds clean option and futures tables, and drops bad rows |
| 3 | `python data_checks.py <work>` | Data checks: ticks, mini vs parent, put-call parity, liquidity. No P&L |
| 4 | `python vrp.py <work>` | Descriptive: implied vs realised volatility per cycle |
| 5 | `python search.py <work>` | DISCOVERY: 9,180 variants per instrument; applies PROTOCOL.md's rules and writes `candidates.json` |
| 6 | `python validate.py <work>` | VALIDATION, run once: candidates on the minis' own prices, giving the finalists |
| 7 | `python robustness.py <work>` | Finalists: slippage x2/x3, entry ±2 days, k ±1 step, best month removed, by year |
| 8 | `python make_tables.py <work>` | Every table the report quotes |

The rules are in `PROTOCOL.md` (pre-registered; sha256 in `PROTOCOL.sha256`). The one
deviation is in `DEVIATIONS.md`. The method is explained in `METHOD.md`, and the results are
in `REPORT.md`.

## Phase 2 (`phase2/`): strategies built from the option data
| Step | Command | What it does |
|---|---|---|
| 9 | `python phase2/analytics.py <work>` | Premium map, skew, IV level, OI walls, weekday and delta-hedged straddle, on discovery data only |
| 10 | `python phase2/run_phase2.py <work> discover` | Best variant per family (rules in `phase2/AMENDMENT_A2.md`); freeze `p2_candidates.json` |
| 11 | `python phase2/run_phase2.py <work> holdout` | One-time holdout on the minis' prices, plus a walk-forward per family |
| 12 | `python phase2/robust2.py <work>` | Robustness, last 30 days and ₹10 lakh sizing |

Results are in `phase2/REPORT_PHASE2.md`.

## Phase 3 (`phase3/`): more structures, and a second untouched test period
| Step | Command | What it does |
|---|---|---|
| 13 | `python phase3/run_phase3.py <work> build` | Cycles for both parents and both minis, front and next month, plus the natural-gas IV percentile |
| 14 | `python phase3/run_phase3.py <work> discover` | Best variant of each of 11 new families (rules in `phase3/AMENDMENT_A3.md`); freeze `p3_candidates.json` |
| 15 | `python phase3/run_phase3.py <work> test` | One-time tests: crude 2018–19 AND 2024–26, a walk-forward per family, and a 2018–19 re-test of every earlier passer |
| 16 | `python phase3/robust3.py <work>` | G2 robustness, why C-E weakened in 2018–19, 2018–19 trade lists, ₹10 lakh portfolios |

Results are in `phase3/REPORT_PHASE3.md`. Phase 3 added `require_expiry` to
`engine.build_cycles`, so a calendar's back month can be loaded before it expires; the
default behaviour is unchanged.

## Phase 4 (`phase4/`): one trade a week, selling and buying; target "2% every week"
| Step | Command | What it does |
|---|---|---|
| 17 | `python phase4/refresh_mcx.py <data> 2026-10-23 2026-10-20` | Re-fetches the contracts still trading, so the data runs to 23 Oct 2026 |
| 18 | `python build_dataset.py <data> <work4>` | Clean tables from the refreshed data (a separate work folder) |
| 19 | `python phase4/run_phase4.py <work4> build` | Cycles (finished and live) and the causal IV percentile for both instruments |
| 20 | `python phase4/test_engine4.py <work4>` | Weekly trades must reproduce the audited engines exactly |
| 21 | `python phase4/run_phase4.py <work4> discover` | 988 weekly variants (rules in `phase4/AMENDMENT_A4.md`); freeze `p4_candidates.json` |
| 22 | `python phase4/run_phase4.py <work4> test` | One-time tests on 2018–19 and 2024–26, plus a walk-forward per family |
| 23 | `python phase4/reference4.py <work4>` | CO-1, CO-2, N-B and the ₹10 lakh core, marked to market every week |
| 24 | `python phase4/robust4.py <work4>` | Robustness of the one pass, and what 2% a week would take |

Results are in `phase4/REPORT_PHASE4.md`.

## Phase 5 (`phase5/`): the winners on markets they never saw, and three new families
| Step | Command | What it does |
|---|---|---|
| 25 | `python phase5/download_more.py <data5> 2026-10-23` | GOLD, SILVER, COPPER, ZINC, NICKEL, GOLDM, SILVERM options and futures (836 contracts) |
| 26 | `python build_dataset.py <data5> <work5>` | Clean tables for the new markets |
| 27 | `python phase5/run_phase5.py specs <data5> <work5>` | Multipliers checked against traded value; ticks from the data |
| 28 | `python phase5/run_phase5.py build_energy <work4> <work5>` | Crude / natural-gas cycles with opening prices |
| 29 | `python phase5/run_phase5.py build_metals <work5>` | Metal cycles with opening prices, IV percentiles |
| 30 | `python phase5/test_engine5.py <work4> <work5>` | 16 checks: opens, open exits, shock days, no overlaps |
| 31 | `python phase5/run_phase5.py discover <work5>` | New families on crude 2020–24 (rules in `phase5/AMENDMENT_A5.md`) |
| 32 | `python phase5/run_phase5.py test <work5>` | Every frozen rule once on every market |
| 33 | `python phase5/robust5.py <work5>` | By year, before / after 2024, ₹10 lakh sizing |

Results are in `phase5/REPORT_PHASE5.md`.

## Phase 6 (`phase6/`): crude-oil and natural-gas FUTURES, week by week; target 2% a week
| Step | Command | What it does |
|---|---|---|
| 34 | `python phase6/download_futures.py <data6> 2026-10-23 <data4>` | Every CRUDEOIL (2005–) and NATURALGAS (2006–) futures contract, plus the minis (663) |
| 35 | `python phase6/build_futures.py <data6> <work6>` | The futures table |
| 36 | `python phase6/test_engine6.py <work6>` | 16 checks: index = held contract, rolls, carry, costs, no look-ahead |
| 37 | `python phase6/run_phase6.py <work6> discover` | 208 weekly variants on 2008–16 (rules and stop rule in `phase6/AMENDMENT_A6.md`) |
| 38 | `python phase6/run_phase6.py <work6> walkforward` | Re-pick every year 2017–26 on all earlier years |
| 39 | `python phase6/run_phase6.py <work6> relaxed` | Descriptive: each family's best of 2008–16 run on 2017–26, with the 2%-a-week arithmetic |

Results are in `phase6/REPORT_PHASE6.md`.

`engine.py` is the backtest. `test_engine.py` is its hand-checked tests, and `b76.py` is
Black-76 (implied vol and delta only; no P&L ever comes from a model price).
