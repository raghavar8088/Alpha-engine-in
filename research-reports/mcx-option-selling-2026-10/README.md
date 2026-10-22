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

`engine.py` is the backtest. `test_engine.py` is its hand-checked tests, and `b76.py` is
Black-76 (implied vol and delta only; no P&L ever comes from a model price).
