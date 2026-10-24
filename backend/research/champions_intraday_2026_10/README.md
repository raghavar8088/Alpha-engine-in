# Champion traders' intraday rules — research code

Tests the published intraday rules of Toby Crabel, Larry Williams and Andrea Unger on gold (XAUUSD) and on the stock-index markets they built them for (S&P 500, Nasdaq 100, DAX). The rules, settings, costs and pass bars are in `PREREGISTRATION.md`, written before any strategy ran. Results are in `REPORT.md` and `report/champions-intraday-test.html`.

**Run, in order:**

1. `python ch_fetch.py` — HistData one-minute bars for SPXUSD, NSXUSD and GRXEUR. Not committed.
2. `python ch_data.py` — regular-session arrays; gold's come from `../xauusd_intraday_2026_10/data/minute.npz`.
3. `python ch_checks.py` — clock, roll-jump and coverage checks. They decide the data cleaning only.
4. `python ch_run.py select` — in-sample; locks one setting per rule and market with a code hash.
5. `python ch_run.py evaluate` — out of sample, once. It refuses to run if the code changed after the lock.
6. `python ch_diagnostics.py` — checks on the portfolio, added after the out-of-sample run and reported only.
7. `python ch_report.py`

**Pipeline test without the real out-of-sample data:** set `CH_DEBUG_WINDOWS=1`. Both stages then run inside the in-sample period and write to `results_debug/`.

**Fill engine:** reused unchanged from `../xauusd_intraday_2026_10/xi_engine.py`. It fills at the worst case inside each minute.
