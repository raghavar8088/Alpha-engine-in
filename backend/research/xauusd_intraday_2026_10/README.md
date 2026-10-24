# Intraday XAUUSD strategies targeting 2% a trade — research code

The intraday companion to `../xauusd_2026_10` (position trades). Python 3.12, pandas and numpy only.

| Step | Command | What it does |
|---|---|---|
| 1 | `python xi_fetch.py` | HistData.com XAUUSD one-minute bars 2009 → latest into `data/raw/` (not committed); about 27 files, a minute or two. |
| 2 | `python xi_verify.py` | Lines HistData up with Dukascopy's hourly bid/ask: the prices are Dukascopy's bid, and the timestamps are New York time **with** daylight saving (not the fixed UTC−5 HistData documents). |
| 3 | `python xi_data.py` | Builds `data/minute.npz`: mid = bid + half Dukascopy's quoted hourly spread; New-York-close sessions; session and London clocks. Needs `../xauusd_2026_10/data/raw` (the Dukascopy download). |
| 4 | `python xi_spotcheck.py` | Prints a few in-sample trades of each rule with New York times and the levels behind them. |
| 5 | `python xi_run.py select` | In-sample only (2010-01 → 2021-09); locks one configuration per family with a hash of the code. |
| 6 | `python xi_run.py evaluate` | Out of sample once; refuses to run if the code changed after the lock. |
| 7 | `python xi_diagnostics.py` | Stress tests of the pass (slippage, late fills, a placebo), added after the locked run; they change no verdict. |
| 8 | `python xi_report.py` | `report/xauusd-intraday-study.html` and `REPORT.md`. |

`XI_DEBUG_WINDOWS=1` runs steps 5–6 on 2010–2017 / 2018–2021-09 to test code without reading the real out-of-sample data.

The 2% target: gold's median session spans 1.25% from high to low, so 2% a trade is only reachable on the account with leverage. Up to 20× is allowed, so the position must make +0.10% a trade after costs.
