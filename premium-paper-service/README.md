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
| Bitcoin | Delta Exchange India: BTCUSD perpetual 1-minute candles (`/v2/history/candles`), plus the taker side of every trade from its websocket (`delta_flow.py`) | 2 min |
| Gold | Delta Exchange India: XAUTUSD perpetual (Tether Gold) 1-minute candles, the gold week only (Sunday 17:00 to Friday 17:00 New York) | 2 min |
| EUR/USD, GBP/USD, Nasdaq 100, Apple, silver | Yahoo 1-minute bars of 6E=F, 6B=F, NQ=F (cash-market hours), AAPL, SI=F, in our own append-only store | 9 min |
| S&P 500, Nasdaq 100, Nifty daily | Yahoo ^GSPC and ^NDX daily; Nifty daily from the 1-minute store | hourly check |
| NSE stocks, daily | seed panel from the study, extended from NSE's `sec_bhavdata_full` | hourly check, new after 19:00 IST |

Why futures: Yahoo's spot forex 1-minute bars have no real high or low (100% zero-range minutes), and Dukascopy throttles this box (503s). Compared
with the study's data on 10-16 Oct 2026, correlation of 5-minute changes: 6E 0.991, 6B 0.962, GC 0.995, NQ 1.000. Yahoo keeps about 30 days of
1-minute bars, so a feed stopped for longer than that leaves a gap.

Gold moved from Yahoo's GC=F to Delta's XAUTUSD on 8 Nov 2026, before its first paper day, so every gold trade is on Delta's prices
and fees: 0.01% plus 18% GST a side, a $0.02 half spread and $0.10 of slippage a fill (the gold study's slippage).

## Market segments and status

After every cycle `segments.py` adds to the status document (`premium_meta` "status") what the page's market tabs show: Indian Market
(Options & F&O, Equity intraday, Equity daily), Crypto, Gold, and Forex & US.

- `feeds`: each feed's source, instrument, last real bar and price, and its state (live / closed / stale / no data) with the reason. The
  state is worked out again at every refresh from the time of the last bar, so a feed that stops shows as stale within minutes; a book on
  a stale or closed feed does not trade, and nothing is substituted for the missing price. The index's live day now ends at the last
  minute that really arrived (it used to be filled flat up to the clock).
- `recorder`: Delta's trade-feed recorder (connected, recording since, last message), written by `delta_flow.py` every 20 seconds.
- `books`: every book's state and its reason: waiting for its start, market closed, stale data, in a trade, or live; for a live book
  whose latest setup was not taken, the engine's own reason (the book is replayed without that setup, and the reject count that changes
  names it).
- `segments`: each segment's totals, its latest 40 closed trades and its open positions.

The live day: a market's forced-exit row for today (bitcoin 23:55 UTC, gold 16:55 New York) does not exist until that time arrives,
and the engines rejected every setup of the day as "after_forced_exit" until then. `runner.live_k_end` uses the last bar so far
instead, so a setup is taken when it happens and its trade stays open until its exit. Checks: `python -I test_segments.py`
(it needs `mongomock` importable; a temporary data folder and an in-memory database, so the real desk is never touched).

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

## Booming Bulls liquidity sweep: LS-00 to LS-22, LS-R1 to LS-R3

26 accounts from `backend/research/liquidity_sweep_2026_11`:

- **LS-00:** the app's strategy `bb_liquidity_sweep` (D9).
- **LS-01 to LS-22:** its 22 one-change versions.
- **LS-R1 to LS-R3:** three of the study's research-only runs (15-minute candles, 3-minute candles, Bank Nifty).

All were pre-registered and backtested on 2016-2026 Nifty data. None has an edge: about 0R a trade before costs and
-0.3R to -0.7R after. Paper trading from 9 Nov 2026 is their forward test.

- **The rules are imported:** `liquidity_sweep.py` runs the app's own strategy classes from strategy-service. The image
  carries `tradingai_shared` and the three strategy files those classes import, not the library's package `__init__`s.
  pydantic is the one new dependency.
- **Fills as in the study's harness:** entry at the confirming candle's close, stop or target on 1-minute rows (stop
  first), v13's breakeven, no target for v15, out at 15:15.
- **Costs:** Angel One's futures charges on one lot (`bb_engine.futures_fees`) plus 1 index point of slippage a fill.
- **Schedule:** the books run in the index cycle with the other Nifty and Bank Nifty books. The ledger's money rules and
  Main Control's switch apply unchanged.
- **Check:** `python -I test_liquidity.py 25` reproduced 681 of 681 study trades over the last 25 sessions, with the
  desk's 20-session warm-up. The same run cut 5 times into the last session checked 337 trades: finished ones
  unchanged, running ones flagged open, none invented.

## Sniper Headshot Entry: SH-00 to SH-04 (bitcoin)

Booming Bulls' "Sniper Headshot Entry" video (jvzd7UPlb5Y) as exact rules on bitcoin from Delta Exchange (`sniper.py`;
readable form with E/A tags in `backend/research/sniper_headshot_2026_11/RULES.md`), asked for on 8 Nov 2026 with
upgraded versions "for the live trading". Five Rs 10 lakh accounts in the Crypto tab, paper only, trading forward from
`settings.SH_START_T` (flat at the start, nothing back-filled). Not backtested.

- **SH-00, the video:** in a 1-hour uptrend, a 5-minute double bottom is swept into a demand zone below it; a strong
  green candle there is the first entry, stop under half its body, target 93% of the way to the range high; a second
  entry (its own position, same target) on the retest of the swept level while the first is open. Sells mirror it.
- **SH-01** enters on the close back above the swept level, stop under the sweep. **SH-02** needs Delta's takers to
  have sold the sweep and bought the reversal candle (`delta_flow.py`'s recorded minutes; unrecorded = no trade).
  **SH-03** adds a 1-hour 50-EMA filter. **SH-04** runs the pattern on 1-hour bars (4-hour trend), stop under the
  reversal candle, and skips any trade whose round-trip cost is over 40% of its risk.
- **Costs decide it:** Delta's round trip at market is about 0.16% of price. On 5-minute bars the video's stop is a
  median 0.044% of price (about 3.6R of costs a trade), SH-01's 0.12% (1.3R); SH-04's 1-hour stop about 0.7% (0.2R).
- `runner.run_sh` runs the first entries through the YouTube engine's book rules (one at a time, at most 3 a day, out
  by 23:55 UTC) and simulates each second entry with the same engine while its first entry is open.
- Checks: `python -I test_sniper.py` (no look-ahead at 29 cut points for every version, the rules re-checked on every
  entry, SH-02's flow filter on a known setup, the accounts through the ledger).
