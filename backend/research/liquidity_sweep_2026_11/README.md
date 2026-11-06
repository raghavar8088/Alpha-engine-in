# Liquidity Sweep (Booming Bulls, Nov 2026): research code

This folder tests the Booming Bulls "Liquidity Sweep" video and PDF (NIFTY, 5-minute) as a mechanical strategy.

- **Strategy:** `bb_liquidity_sweep`, Booming Bulls D9, in `strategy-service/strategy_service/strategies/options_buying/booming_bulls.py`. It sits in the app's option-buying library next to D1–D8.
- **Harness:** these scripts drive that class, so the app and the test run the same code.
- **Rules:** [PREREGISTRATION.md](PREREGISTRATION.md). Its hash was recorded in `PREREGISTRATION.sha256` before the first run.
- **Results:** [REPORT.md](REPORT.md). The verdict is no edge: 0R a trade before costs, and −0.4 to −0.6R after.

The scripts need Python 3.12 with numpy, pandas and pydantic. Run them with `python -I` so the local venv's stale `tradingai_shared` stays out; `ls_common.py` puts the repo's own packages first.

| Step | Command | What it does |
|---|---|---|
| 1 | (data) | 1-minute NIFTY candles come from `../index_intraday_2026_10/data/1m/NIFTY/` (to 9 Oct 2026) and `../niftybees_orb_2026_10/data/box_1m/NIFTY/` (12–23 Oct 2026). Later days from the server's `/data/intraday/idx1m/NIFTY/` go in `data/box_1m/NIFTY/`. The index-intraday module's `_build` cleans them. |
| 2 | `python -I ls_datacheck.py` | Lists the sessions and the cleaning counts. Checks each PDF trade's entry against the minute data (writes `results/pdf_datacheck.json`). |
| 3 | `python -I ls_verify.py` | 29 checks: hand-built sessions with known answers, the fee formula against `angel_fees.futures_round_trip`, context-size independence and backfill safety on real candles. |
| 4 | `python -I ls_run.py` | Runs A (5-min), B (5-min + 200-EMA) and C (3-min) over every session on disk. It fills each entry on 1-minute candles, costs it as a futures lot, replays and matches the PDF's 42 trades (`pdf_examples.csv`), and scores run A in the app's options engine. Writes `results/summary.json`, `trades_{A,B,C}.csv` and `pdf_trades.csv`. Takes about 25 s. |
| 5 | `python -I ls_verify.py --real` | Adds 3 checks: on every real trade, the strategy's own exit candle equals the 1-minute fill's. |

`data/` is not in git. The candles are Angel One's licensed data and the repository is public.
