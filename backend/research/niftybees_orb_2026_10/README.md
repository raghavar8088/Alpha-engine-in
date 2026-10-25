# NIFTYBEES opening-range breakout (October 2026): research code

A five-year backtest of one intraday rule on NSE NIFTYBEES, as the owner specified it:

- the opening range is the 09:15, 09:20 and 09:25 five-minute candles;
- buy a break above it, or sell a break below it, from 09:30;
- the stop-loss is the other side of the range and the target is twice the risk (1:2).

The execution rules the brief left open (price-crossing entry, one trade a day, no reversal, ₹10 lakh a trade, out at 15:15, Angel One charges, 1 bp slippage) are in `orb_engine.py`. They were fixed before the first run, as was every comparison run in `orb_run.py`.

**Results:** [REPORT.md](REPORT.md), also published as the private page https://claude.ai/artifact/VM5cwRqaQf1qc6HtJFSk3c. **Verdict:** the rules lose money after costs: 1,205 trades, 40.7% winners, net −₹5,48,885 on ₹10 lakh, profit factor 0.77.

Python 3.12 with numpy and pandas. Run from the repository root; `-I` keeps the stale `tradingai_shared` in the local venv out of the way (each script puts the repo's `shared/` and `backend/` first itself).

| Step | Command | What it does |
|---|---|---|
| 1 | copy the server's newest daily files | The 1-minute candles to 9 Oct 2026 are the index-intraday study's download in `../index_intraday_2026_10/data/1m/`. Later sessions come from the app's daily store on the server (`/data/intraday/idx1m/NIFTYBEES/` and `NIFTY/` in the backend container) and go into `data/box_1m/`. |
| 2 | `python -I backend/research/niftybees_orb_2026_10/orb_data.py` | Builds `data/NIFTYBEES_5m.csv.gz` (75 five-minute candles a session) and the 1-minute matrices. It also writes the raw and cleaned opening ranges and `results/data_quality.json` (calendar audit, gaps, dropped prints, opening-print cleaning). |
| 3 | `python -I backend/research/niftybees_orb_2026_10/orb_verify.py` | 49 checks: the fee function equals the app's `angel_fees.round_trip`, hand-built sessions with known answers, and invariants on the real run. |
| 4 | `python -I backend/research/niftybees_orb_2026_10/orb_run.py` | The primary test and 13 one-rule-changed runs. Writes `results/summary.json`, `sensitivity.csv`, the trade logs, the yearly tables, the daily equity and the ambiguous-candle record. |
| 5 | `python -I backend/research/niftybees_orb_2026_10/orb_crosscheck.py data/yahoo_5m_60d.json` | Compares the candles with one download of Yahoo's 5-minute NIFTYBEES chart (last 60 sessions). |
| 6 | `python -I backend/research/niftybees_orb_2026_10/orb_report.py` | Writes `REPORT.md` and `report/niftybees-orb-backtest.html` from the results. The page's design lives in `report_template.html`. |

## What is not in git

`data/` holds the candles and is ignored (`data/.gitignore`): the candles are Angel One's licensed data and the repository is public. Steps 1 and 2 rebuild it.

## Things a rerun should know

- **The 09:15 candle opens with NIFTYBEES's pre-open auction print.** The open sits a median 0.49% from the NIFTY-implied price and is more than 2.3% away on 1 day in 10. Raw, it sets the opening range on most days. `orb_data.py` rule 4 cleans it, and the raw range is run as a comparison.
- **Eight sessions have no morning.** Each is the first day of a 30-day bulk request, where Angel returned only about 8,000 minutes (13:25 onward). A one-day request on the server would fill them; they are left out and listed.
- **A 5-minute candle hides the order of its high and low.** The simulator takes the worse order. Only 8 of the 1,205 trades depend on it, and the 1-minute walk (`bars=1`) shows what happened inside those candles.
