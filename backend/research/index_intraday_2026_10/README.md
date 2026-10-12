# Index intraday research (October 2026)

The study behind the **Indian Index Intraday Trading** module. The findings are in
[INDEX_INTRADAY_RESEARCH_2026_10.md](../../../INDEX_INTRADAY_RESEARCH_2026_10.md); this folder is the
machinery and the record.

**Question.** Can an intraday rule on an Indian index make money after real costs, in the cash market,
with no options, futures or leverage? A long or short position is held within one session only.

## Files

| file | what it does |
|---|---|
| `ii_fetch.py` | Stage 0, run **on the server**: Angel One's 1-minute candles for 8 indexes, India VIX and 7 index ETFs, 2016 → 2026-10-09, one gzip CSV per symbol and 30-day window under `/data/intraday/idx1m/`. Resumable. |
| `ii_spreads.py` | Each ETF's effective half-spread, estimated from its own minute prices (Roll; Corwin–Schultz), plus its median traded value a minute. Feeds `costs.ROUTE`. |
| `ii_round.py ROUND INDEX…` | Runs a round's registered variants (`families.ROUND1..4`) on **selection 2016–21** and **validation 2022–23** only; writes every trial to `data/registry.csv` and its daily returns to `data/returns_r<N>_<INDEX>.npz`. Round 4 (2026-10-12) covers round 1's indicator grid at the 10m and 30m bars it had left out. |
| `ii_final.py stage3` | Stage 3 on 2016–23 only: deflated Sharpe over the effective number of trials, neighbours, breadth, walk-forward, 1.5× costs, the ETF-only tradability route, Monte Carlo. Writes `data/stage3.csv` and `data/stage3_summary.json`. |
| `ii_final.py holdout` | Opens 2024-01-01 → 2026-10-09 **once**, for Validated strategies only. **Never run**: no strategy reached Validated. |
| `ii_catalog.py` | Publishes every trial to `backend/app/services/index_intraday/catalog.json`, which the Strategy Dashboard reads. Each trial carries its status and the first gate it failed. |

The simulator, the strategy families, the cost model and the data loader live in the module itself
(`backend/app/services/index_intraday/`). So the backtest, the Backtesting Lab and the paper engine
share one rule book, held to each other by `backend/tests/index_intraday/verify_index_intraday.py`.

## Reproduce

```bash
# the 1-minute history: on the server (see ii_fetch.py), then copied to data/1m/<SYMBOL>/
python backend/research/index_intraday_2026_10/ii_spreads.py
for r in 1 2 3 4; do
  python backend/research/index_intraday_2026_10/ii_round.py $r NIFTY BANKNIFTY SENSEX FINNIFTY NIFTYNXT50 NIFTY100 BANKEX MIDCPNIFTY
done
python backend/research/index_intraday_2026_10/ii_final.py stage3
python backend/research/index_intraday_2026_10/ii_catalog.py
```

`ii_round.py` only **adds** trials to `registry.csv`. To rerun a round from scratch, move the old
registry away first.

## The record

`data/` keeps the trial record (`stage3.csv`, one row per variant × index with every metric),
`stage3_summary.json` and the round logs. The 1-minute history (120 MB) and the per-trial returns
are not in git.

`data/run1_uncorrected_data/` is the **first run** (2026-10-11). It ran on data with three defects
that the loader's quality rules then missed:

- Angel's `-0.01` placeholder prints in FINNIFTY (8, 10 and 11 August 2022);
- stray 09:15 prints 15–19% off the market in NIFTYBEES, BANKBEES and JUNIORBEES (2020–21);
- India VIX served divided by 100 from 2016-01-01 to 2016-09-08 and on 2021-03-01.

The defects were found while the report was being written: 31 FINNIFTY trials showed millions of
basis points a trade in 2022–23. The loader now drops such prints and rescales VIX, and every round
was rerun on the corrected data with the same registered variants and gates, and round 4 was added.
The report compares the two runs.
