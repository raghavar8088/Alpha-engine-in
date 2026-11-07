# Premium Strategies paper desk

52 research strategies, each paper trading its own Rs 10 lakh account from 9 Nov 2026. Paper only: this service holds no
broker client and no broker credentials. None of these strategies passed its test.

- **Strategies:** 6 from the VWAP study, 18 from Booming Bulls (`backend/research/booming_bulls_2026_11`), 28 from the YouTube top 20
  (`backend/research/youtube_top20_2026_11`). The variant per market is the one each study chose before opening its hold-out, frozen in
  `catalog.py`. Never re-tune it on paper results.
- **Runs in its own container** (`premium-paper` in `docker-compose.yml`), because the backend sits at its memory cap. `main.py` starts
  each cycle (`cycle.py <group>`) as a short process, one at a time, so its memory returns to the box when it ends.
- **The rules are not copied:** the image carries the studies' own `bb_*.py` and `yt_*.py` at the same relative paths. The VWAP rules live
  outside this repo, so `vwap_rules.py` is generated from them by `extract_vwap.py`. `bb15.py` is written from BB-15's pre-registered rule; it
  has no backtest, because the study could not download Apple's data.

## Data

| Markets | Source | Refresh |
|---|---|---|
| Nifty, Bank Nifty | `/data/intraday/idx1m` (read-only) through the app's cleaner, plus today's minutes from `/api/premium-paper/today-bars` | 5 min |
| NSE stocks, intraday | `/data/intraday/5m` (read-only), plus today's bars from the same route | 15 min |
| EUR/USD, GBP/USD, gold, Nasdaq 100, Apple | Yahoo 1-minute bars of 6E=F, 6B=F, GC=F, NQ=F (cash-market hours), AAPL, in our own append-only store | 10 min |
| S&P 500, Nasdaq 100, Nifty daily | Yahoo ^GSPC and ^NDX daily; Nifty daily from the 1-minute store | hourly check |
| NSE stocks, daily | seed panel from the study, extended from NSE's `sec_bhavdata_full` | hourly check, new after 19:00 IST |

Why futures: Yahoo's spot forex 1-minute bars have no real high or low (100% zero-range minutes), and Dukascopy throttles this box (503s). Compared
with the study's data on 10-16 Oct 2026, correlation of 5-minute changes: 6E 0.991, 6B 0.962, GC 0.995, NQ 1.000. Yahoo keeps about 30 days of
1-minute bars, so a feed stopped for longer than that leaves a gap.

## Ledger

- `premium_trades`: what each strategy did, per unit, as the study's engine says. A trade is `sealed` once its bars are final (NSE 17:30 IST; New
  York markets about 30 minutes after their close) and is never rewritten.
- `premium_accounts`: the Rs 10 lakh account, a pure function of those trades, recomputed from the first trade every cycle.
- Records are in the box's second MongoDB (`FACTORY_MONGO_URL`, db `alpha_engine_premium`), never on Atlas. Data files are on the `premium_data` volume.

## Checks, before launch

| Test | Command | Result |
|---|---|---|
| Recent trades, desk vs saved backtest, on a short window | `python -I test_fidelity.py 10` | 728 of 728 (3 differ only in the 3rd decimal of R) |
| Cut mid-session: finished trades unchanged, nothing invented | same | 10,326 trades checked, 0 bad |
| Forex, gold, Nasdaq with launch's 21-session warm-up, 30 sessions | `python -I test_daily.py 30` | 1,635 of 1,635 |
| Daily indices from about 480 sessions | same | 10 of 10 |
| NSE daily stocks from the seed panel, 30 sessions | same | 555 of 562 (the other 7: too little recent history for `nse_daily`'s 260-row rule) |
| Stock pools | `python -I test_stocks.py 2026-10-30 5` | 4,263 of 4,263 (the study also traded index "stocks", left out here) |
| VWAP glue, on the study's own data and environment | `test_vwap_port.py` | 2,366 of 2,366 |
| Money layer | `python -I test_ledger.py` | all pass |
| A past session replayed as live, cut at 3 moments (run on the box) | `python test_live.py 2026-11-06 2026-11-05` | 1,195 finished trades unchanged, 758 running flagged open, none missed; 4 provisional trades differ (see below) |

**Provisional trades can be replaced.** The study's engine takes signals in order, so a resting stop order that fills later still has priority over a newer signal that
filled first. A mid-session replay does not yet know about the later fill, so it can show the newer trade until the older order fills (YT-08 stocks, 4 of 158 at one
cut). Sealed trades follow the study's engine exactly.

## Operating

- Seed once: `python -I make_seed.py nse_daily.npz`, then copy to `/data/premium/nse/data/nse_daily.npz` on the volume.
- Main Control's `premium_strategies` switch stops all cycles. A session missed while OFF is replayed when switched back on.
- Dry run on other dates or another database: `PREMIUM_PAPER_START`, `PREMIUM_MONGO_DB`, `PREMIUM_DATA_DIR`.
