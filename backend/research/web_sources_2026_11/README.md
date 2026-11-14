# Web-sourced crypto and gold strategies (13-14 Nov 2026)

Collects crypto and gold trading strategies from public web sources, extracts their exact rules with evidence, reviews
implementation risks, backtests the ones whose rules are complete, and publishes the records on the Premium Strategies
page (tab **Web sources: crypto & gold**). Research only: nothing here trades or changes a paper account.

## What was collected

| Source (priority order) | Access | Result |
|---|---|---|
| TradingView Community Scripts | **not collected**: robots.txt disallows `/scripts/*` and `/script/*` for AI agents | Paste open-source scripts into the Trading Video Lab's Pine analyser (`#pine`) to bring them in |
| freqtrade-strategies (GitHub) | `git clone`, commit `f3340ce1`, GPL-3.0 | 68 classes inventoried; 20 in the batch + 3 variations; the rest recorded |
| QuantConnect forum and research | public pages (robots allow `/forum`, disallow `/api`); code is embedded in each page | 29 pages read; 5 crypto + 5 gold in the batch (one gold record merges a second post) |
| Tradeciety | public pages | 4 setups read (all need clarification), 18 named setups recorded from headings |
| Capital.com gold guide | public page | 9 educational ideas (2 Pepperstone sections merged in) |
| Pepperstone gold guide | public page | 4 more educational ideas |
| CME Group Education | **not collected**: 403, automated access prohibited by its Data Terms of Use | – |
| IBKR Campus | sitemaps + 6 posts | no trading rules (analyses and commentary) |

Batch: 25 crypto and 18 gold (target 25: shortfall 7; no MCX gold source was found). `registry/INVENTORY.md` has the
ranked list; `registry/candidates.json` the full records.

## Pipeline (run from this folder)

The local evidence store `D:/Strategy-Web-Sources` (not committed: third-party content and large data) holds the clone,
the saved pages, the freqtrade venv, the signals and the trade lists. Downloaded code is never run during discovery.

| Step | Command | What it does |
|---|---|---|
| 1 | `python -I ws_freqtrade_inventory.py <clone>` | Static inventory (ast only): settings, rule lines, risk flags -> `registry/freqtrade_inventory.json` |
| 2 | `python -I ws_qc_extract.py <pages> <out.json>` | QuantConnect posts, authors, dates, attached files with SHA-256 |
| 3 | `<venv> -I ws_ft_data.py <datadir>` | freqtrade-format candles from the repository's Binance 1-minute data (BTC 2017-2026, ETH 2021-2026) |
| 4 | `<venv> -I ws_ft_signals.py ...` | each freqtrade strategy's OWN code computes its signals, in the isolated venv (after the static review) |
| 5 | `python -I ws_strategies.py` | our line-by-line re-implementations of the QuantConnect strategies |
| 6 | `python -I ws_run.py`, `python -I ws_run_qc.py` | backtests on `ws_engine.py`; windows fixed in the scripts before results were seen |
| 7 | `python -I ws_verify.py`, `python -I ws_checks.py`, `python -I ws_ft_bias.py <classes>` | independent trade re-walk, truncation test, freqtrade lookahead/recursive analysis |
| 8 | `python -I ws_records.py`, `python -I ws_export.py` | the records, the inventory, `evidence/`, and the app's `webSourcesData.ts` |

## Conventions

- **Rule tags** (as the Video Lab cards): E stated or implemented in the source (with its line or section), I our
  interpretation, A our adaptation or assumption. Each record keeps its source URL, author, retrieval date, licence
  and version (commit, file SHA-256 or page SHA-256).
- **Engine** (`ws_engine.py`): follows the crypto intraday harness (`antigravity .../crypto_intraday20_2026_11/ci_core.py`):
  signal on a closed bar, entry at the next 1-minute open, exits walked minute by minute (gap fills at the open, the stop
  wins a minute that touches both), plus freqtrade's exit model (net-of-fee ROI table, price stop, trailing, exit
  signals). Costs: Binance spot 0.10% + 2 bp a side (original market); Delta India 5.9 bp + 2 bp + Binance funding
  (perpetual adaptation); gold uses the repository's XAUUSD model (spread $0.40, slippage $0.10, commission
  $0.035/oz a side, CFD financing). $10,000 a trade, no compounding.
- **Windows**: crypto dev 2018-2022 / out of sample 2023-Oct 2026 (BTC/USDT); ETH/USDT 2021-2022 / 2023-Jul 2026 as the
  second pair; the gold sweep (QC-20960) is judged on 2010-2020, outside its author's 2021-2026 window.
- **Statuses**: DISCOVERED, NEEDS_CLARIFICATION, READY_FOR_IMPLEMENTATION, READY_FOR_BACKTEST, BACKTESTED,
  PAPER_TRADING_CANDIDATE, REJECTED, BLOCKED. The paper-trading gate (in `ws_records.py`) needs: no look-ahead, net
  positive in dev and out of sample, still positive at 2x costs, >= 30 out-of-sample trades with t >= 2, positive on the
  second pair, and above buy-and-hold scaled by time in the market. **None passed.** Paper activation would be a separate
  step on the desk; it is not wired here.

## Checks that ran

- Independent re-walk of 400 sampled trades across 10 strategies: 0 mismatches (it found one engine bug first: an ROI
  table without a "0" key wrapped to its last entry; fixed and re-run).
- Truncation test of our QuantConnect re-implementations: 0 differences over about 5.9 million signal rows.
- freqtrade lookahead-analysis: 2 biased (CCIStrategy, ReinforcedQuickie: an interpolated resample reads the next bar),
  20 clean. recursive-analysis: most strategies declare `startup_candle_count = 0`, which freqtrade refuses; run with
  an analysis-only override of 200, indicator differences are negligible from 200 candles on.

## Findings

- freqtrade 1-5 minute scalpers lose after costs: gross edges of a few basis points against about 24 bp a round trip.
- Positive out-of-sample results are long-biased trend followers in rising markets (QC-11340, QC-13690, QC-5079) with
  t near 1 on about 30 trades and below buy-and-hold for their time in the market.
- The XAUUSD Tokyo-range sweep (QC-20960) wins 69% of trades in its author's window but breaks even over 2010-2020.
- Source defects found: an exit that can never fire (UniversalMACD), an exit that depends on the pandas version
  (Low_BB), a hyperopted exit out of reach (MACDStrategy), a strategy that no longer loads (FReinforcedStrategy), a
  time-zone mismatch between a post and its code (QC-20960).

## To continue

- TradingView: paste open-source strategy scripts into the Pine analyser; its static extraction feeds this workflow.
- QC-R18811 (GLD/SPY HMM rotation): needs hmmlearn and GLD/SPY daily data (proxies exist: XAUUSD, S&P 500 CFD).
- The educational gold ideas need the missing rules listed in each record before anything can be tested.
