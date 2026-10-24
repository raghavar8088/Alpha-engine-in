# NIFTY 50 stocks: chart-pattern, indicator and breakout strategies. Research plan (24 Oct 2026)

## The goal
Find a **few high-quality, rule-based strategies** for NIFTY 50 stocks that survive an honest
5-year backtest after Angel One's charges. The candidates are:
- chart patterns and candlesticks;
- indicators, structure breaks and breakouts;
- combinations of these.

The starting library is your own 69 Strategy Factory recipes.

## What already exists, and what it tells us
**The 69 recipes are already code** (`backend/app/services/strategy_factory/`):
- `detectors.py` holds the setup detectors. Chart patterns such as head & shoulders,
  triangles, flags and cup & handle come from the wrapped `commodity_patterns` templates.
- `confirmations.py` holds the volume, RSI, EMA-trend, ADX, ATR, MACD, VWAP and higher-timeframe
  checks.
- `catalog.py` holds the per-timeframe parameters and the regimes and reward multiple of each
  recipe. It refuses duplicate recipes.
- `backtest.py` is a no-look-ahead replay: it fills on the next bar, counts the stop first
  inside an ambiguous bar, and charges costs.
- `angel_fees.py` already models Angel's delivery charges: STT 0.1% on both legs, stamp
  0.015%, a ₹20 + GST depository charge per sale. A round trip is about 0.25–0.3%.

**The app's earlier evidence:**
- The Strategy Factory desk produced **0 trades** that passed its own gates.
- Intraday stock patterns lost **−₹11.51 crore** over a 2-year walk-forward.
- A 5-minute opening-range study (5,184 variants) found **none** that passed the
  deflated-Sharpe test.

**So this study:**
- focuses on **daily (swing) holding**, where costs are small next to the moves;
- adds the two controls the earlier work lacked: point-in-time membership and a
  random-entry comparison.

## Phase 0 · Data: pull and verify
1. **Universe as it really was.** Use NIFTY 50 membership on each date, rebuilt from NSE's index
   change notices. Today's 50 would be biased, because today's members are the past winners.
   That is about 60–70 stocks over 5 years.
2. **Daily prices.** OHLCV from Oct 2021 to Oct 2026, from Angel One. The pull runs read-only in
   a throwaway, memory-capped container on the server, as in Phase 8.
3. **Hourly bars for 5 years**, if Angel serves that depth. This is checked first. Hourly bars
   allow the swing and 1h recipes.
4. **Splits and bonuses adjusted** from NSE's corporate-action records.
5. **The NIFTY 50 index**, for the regime filter and the benchmark.

**Accepted when:**
- at least 99% of trading days are present per stock;
- every split and bonus is adjusted;
- spot checks match NSE's official bhavcopy.

## Phase 1 · Harness and detector tests
- **Offline:** run the app's own detectors on the files, with no database and no live services.
- **Tests:**
  - every detector fires on a textbook synthetic example and stays silent on random noise;
  - signals are identical whether computed bar by bar or on the full series (no look-ahead);
  - costs match `angel_fees.py` exactly;
  - slippage is 0.05% a side (NIFTY 50 liquidity).

## Phase 2 · Pre-registration (written and fingerprinted before any result)
- **Recipes.** The **63 recipes that work on daily bars**. Six are intraday-only (opening
  range, prior-session high/low, three VWAP recipes, gap continuation); they run on hourly bars
  only if Phase 0 gets 5 years of them.
- **Rules per recipe,** exactly as the catalog defines them:
  - its detector, its confirmations, its regimes and its reward multiple;
  - entry at the next day's open;
  - stop from the detector; target = reward × risk; time stop 40 bars.
- **Direction.** Long-only (cash). Short setups run separately as stock futures and are
  labelled as such.
- **Sizing.** Risk 1% of ₹10 lakh per trade, at most 10 positions, at most 3 per sector.
- **Periods.**
  - discovery: Oct 2021 – Sep 2024;
  - **holdout: Oct 2024 – Oct 2026, run once;**
  - plus a walk-forward by year.
- **Controls.**
  1. **Random entries** with identical exits, stops, sizing, regime filter and trade count per
     stock and month. A recipe must beat this, not just make money in a rising market.
  2. Buy-and-hold, equal-weight NIFTY 50.
- **"High quality" means all of:**
  - holdout net > 0 after costs, and also at 2× costs;
  - beats the random-entry control (t ≥ 2.5);
  - deflated Sharpe ≥ 0.95, counting every recipe and combination tried;
  - profitable in at least 60% of the stocks it traded and in each year;
  - no single stock more than 25% of the profit.
- **Stop rule.** The search ends when these phases are complete. It does not go on until a
  number appears.

## Phase 3 · Discovery
- **Run all 63 recipes on 2021–24.** Report each one:
  - trades, win rate, expectancy in R (multiples of the risk) and profit factor;
  - result against the random-entry control;
  - results by regime and by sector.
- **Build at most 10 combinations** from the best, on discovery data only, each with a written
  reason. An example is pattern + volume + trend filter.
- **Freeze** every single recipe and combination that passes.

## Phase 4 · Holdout and robustness (once)
Run the frozen set on Oct 2024 – Oct 2026, then check it:
- walk-forward;
- costs × 2;
- results by year, sector and regime;
- without the best stock;
- with a different start date.

## Phase 5 · The few high-quality strategies
- **A one-page rule card for each passer:** setup, confirmations, entry, stop, target, sizing,
  when not to trade, its numbers and its worst month.
- **A ₹10 lakh portfolio of the passers:** weekly and monthly returns, drawdown, against NIFTY.
- **A paper-trading plan** on an existing desk. No new desk, and no real money.

## Phase 6 · Report and commit
`REPORT.md`, every trade list, and the code. Commit and push the research folder only.

## Time
| Phase | Effort |
|---|---|
| 0 Data | 1 session (the data pull runs 1–2 hours in the background) |
| 1 Harness and tests | 1 session |
| 2 Pre-registration | half a session |
| 3–4 Discovery and holdout | 1–2 sessions |
| 5–6 Rule cards, portfolio, report | 1 session |

## What to expect, honestly
- **2021–26 was a strong bull market for Indian large caps.** Many long-only patterns will make
  money just by being long. The random-entry control is what separates a real pattern from the
  market.
- **Expect 0–5 strategies to pass.** If any do, a realistic return is something like 10–25% a
  year, with drawdowns. That is not 2% a week.
- **Your reset plan (rule 2, one idea at a time):** this would be a second active research idea
  beside S1. It does not touch NIFTY options, so S1's untouched data stays untouched.

## Defaults (change them if you want)
- Long-only on cash. Shorts, if wanted, run as a separate stock-futures study.
- Daily first. Hourly is added if Angel gives 5 years of it.
