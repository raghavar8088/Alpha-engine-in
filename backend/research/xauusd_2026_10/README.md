# XAUUSD strategies targeting 2% a trade — research code

Re-runnable study behind the report. Python 3.12 with pandas and numpy only; no other packages.

| Step | Command | What it does |
|---|---|---|
| 1 | `python xa_fetch.py` | Downloads free data into `data/raw/` (not committed): Dukascopy XAUUSD bid **and** ask hourly candles from 2004 (the current month from minute candles), Dukascopy daily candles, Yahoo COMEX GC=F daily/hourly and the 13-week T-bill (^IRX). Sequential and paced; Dukascopy throttles bursts, so a full download takes 30–90 minutes. |
| 2 | `python xa_data.py` | Builds hourly mid bars and New-York-close daily sessions (`data/bars.pkl`) and writes `results/data_quality.json`: coverage, gaps, spreads by year, and agreement with Dukascopy's own daily candles and with COMEX. |
| 3 | `python xa_test_engine.py` | Checks every fill rule of the engine on hand-built price paths. |
| 4 | `python xa_run.py select` | **In-sample only (2010-01-01 → 2021-09-30).** Backtests every configuration, picks one per family by the fixed rule, and writes `results/selection_locked.json` with a hash of the code. |
| 5 | `python xa_run.py evaluate` | **Out of sample (2021-10-01 → latest)**, once, for the locked choices; refuses to run if the code changed after the lock. Writes `results/summary.csv`, `results/oos_detail.json`, `results/trades/*.csv`. |
| 6 | `python xa_walkforward.py presample` then `walk` | Two checks added after the locked run (rules fixed before they ran; they change no verdict): the locked choices on 2005–2009, which no stage had read, and an expanding-window walk-forward from 2014 that re-chooses each year's parameters from earlier years only. Writes `results/supplementary.json`. |
| 7 | `python xa_monthly.py` | Month-by-month returns of the six configurations chosen in-sample and of holding gold, rebuilt from the stored trades as daily marked-to-market equity (checks that it reproduces each trade's stored net return exactly). Writes `results/monthly.json`. |
| 8 | `python xa_report.py` | Builds the report page (`report/xauusd-2pct-study.html`) and `REPORT.md` from the results. |

`python xa_spotcheck.py` prints a few trades of five strategies next to the values that should have produced them (in-sample dates only), to confirm the rules fire where the published rules say.

`XA_DEBUG_WINDOWS=1` runs steps 4–5 on 2010–2017 / 2018–2021-09 (inside the in-sample period) to test the code without reading the real out-of-sample data. `XA_BID_ONLY=1` builds development bars from bid prices before the ask download finishes. Neither is used for a reported result.

## Files

- `xa_fetch.py`: downloads.
- `xa_data.py`: bars and data checks.
- `xa_engine.py`: the engine. Daily decisions take effect at the next session's open; stops, targets and stop entries are checked hour by hour, with the worst case taken inside an hour; costs are added per trade. It also computes the statistics.
- `xa_strategies.py`: every candidate family, with its source, rules, published position sizing, deviations from the source, parameter grid and published default. It also lists the discarded candidates and why each was dropped.
- `xa_run.py`: the two locked stages, the selection and pass rules, and the diagnostics: harsher costs, a random-entry timing test, a bootstrap interval, the 2021-23 vs 2024-26 split, neighbouring parameters, and buy-and-hold.
- `xa_test_engine.py`: engine checks.
- `xa_walkforward.py`: the two later checks.
- `xa_spotcheck.py`: strategy spot checks on real bars.
- `xa_report.py`: the report (HTML and Markdown).
