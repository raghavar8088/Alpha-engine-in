# Selected ORB 15-min, 1:1, on the NIFTY 50 (Nov 2026)

The Intraday Stocks tournament's pre-registered rule `iv2_orb_sel15` ("Selected ORB 15-min, top-5 expected move"), with two
changes asked for by the owner: it may pick only NIFTY 50 stocks, and it takes a 1R target. Shown in the Premium
Strategies module as IS-01. Research only: it is not a tournament strategy and it is not paper trading yet.

## Rule

- **Stocks:** the NIFTY 50 (`nifty50_constituents_2026-11-08.csv`, niftyindices.com, after the September 2026 rebalance).
- **Pick at 09:30:** the Scanner Board's expected-move model (the `open` variant: ATR %, opening gap, yesterday's range in ATRs,
  results day) ranks the 50; the top 5 are candidates. The model is trained as live: every Saturday, on earlier data only, on the
  Intraday Stocks universe.
- **Volume:** the 09:15-09:30 candle at least 1.5x that candle's average over the previous 14 sessions.
- **Entry:** buy stop at the 15-minute range's high, sell stop at its low, 09:30-14:30; the first fill cancels the other.
- **Stop:** the opposite edge of the range. **Target:** 1R from the fill (the registered rule has none and holds to the close).
- **Exit:** stop, target, or 15:05 (closing-auction stocks) / 15:10.
- **Sizing:** 5 slots of Rs 10 lakh on Rs 50 lakh (1x); at 5x, 5 slots of Rs 50 lakh on the same Rs 50 lakh.
- **Costs:** Angel One intraday charges and the measured slippage (`intraday_fills.slippage_bp`, priced at the order's size);
  targets fill as limits.

## Result, last month only (6 Oct - 5 Nov 2026, 22 sessions)

| Version | Leverage | Trades | Win % | Net P&L | Return | PF | Max DD |
|---|---|---|---|---|---|---|---|
| 1:1 target | 1x | 40 | 65.0 | +Rs 2,21,593 | +4.43% | 2.93 | 0.42% |
| 1:1 target | 5x | 40 | 65.0 | +Rs 10,74,497 | +21.49% | 2.78 | 2.37% |
| As registered | 1x | 40 | 57.5 | +Rs 1,72,854 | +3.46% | 2.13 | 0.84% |
| As registered | 5x | 40 | 57.5 | +Rs 7,91,384 | +15.83% | 1.99 | 4.73% |

October alone: +3.71% (1x) and +18.20% (5x) with the 1:1 target. On its usual top-200 universe over the same month the
1:1 version made +2.79%. Every number comes from `results/summary.json`, written by `export_app_data.py`, which asserts
these totals against the saved runs.

**Caution:** one month and 40 trades. Over two years on its usual universe the 1:1 version made +15.81% (t 1.36), and the rule
was chosen in the S4 study on that same period, so this is not independent evidence.

## Files

- `replay.py`: the replay (production code from git HEAD through `../intraday_ai/stubpkg.py`), `--universe nifty50`,
  `--leverage`, `--windows`. It writes to `work/` (git-ignored).
- `fills5m.py`: the stop-entry fill model on 5-minute bars.
- `fetch_results.py`: NSE board meetings for the results-day flag.
- `export_app_data.py`: writes `results/summary.json` and `frontend/app/premium-strategies/sel15Nifty50Data.ts`.

Runs used for the page: `replay.py --start 2026-10-01 --windows trailing:2026-10-06:2026-11-05,october:2026-10-01:2026-10-31`
with `--universe nifty50 --leverage 1`, `--universe nifty50 --leverage 5` and `--universe module`.
