# Trader-style gold setups — research code

Rules: `PREREGISTRATION.md` (written before any result). Run: `python ts_fetch.py` (silver, EUR/USD, GBP/USD minutes from HistData) → `python ts_data.py` → `python ts_run.py select` (gold in-sample, locked) → `python ts_run.py evaluate` (gold out-of-sample + the three other markets, once) → `python ts_report.py`. Gold minutes and the fill engine come from `../xauusd_intraday_2026_10`. `XT_DEBUG_WINDOWS=1` tests the pipeline inside the in-sample period.
