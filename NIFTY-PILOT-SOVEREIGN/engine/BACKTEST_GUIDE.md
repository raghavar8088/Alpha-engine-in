# NIFTY-PILOT SOVEREIGN — Backtest Harness & Replay Engine

A read-only walk-forward backtest harness that replays historical NSE candles
through the **exact same** strategy, regime, risk, sizing, and execution code
the live engine runs — zero strategy forks. It validates all 29 strategies
(S1–S29) before they are promoted to live paper trading.

> **PAPER / SIMULATION ONLY.** The harness never places orders. It is a
> separate binary (`engine/cmd/backtest`) from the live engine
> (`engine/cmd/niftypilot`) and modifies no live code.

---

## 1. Design overview

```
HistoricalDataFetcher (Kite | NSE | Synthetic)
        │  fetch 1m/5m/15m/1h candles (+ warmup) per instrument + India VIX
        ▼
ContextBuilder ── reveals only CLOSED bars (no lookahead) into the live
        │          marketdata.NiftyDataBundle; derives spot + prev-close
        │          from the 1m base stream; classifies regime via the live
        │          regime.Classifier
        ▼
BacktestEngine.Run ── per 1m bar close, in market hours only:
        │   1. manage exits (SL/TP on the bar, pessimistic SL-before-TP)
        │   2. evaluate every strategy → walk-forward gate → risk gate →
        │      half-Kelly size (margin book) → fill via execution.Engine
        │   3. mark-to-market equity snapshot
        ▼
Reports ── summary, equity curve (+PNG), trades, leaderboard, daily PnL,
           walk-forward details, regime analysis, execution log
```

**Reuse (PART 7 — zero modifications to live code):**

| Concern            | Reused live component                                  |
|--------------------|--------------------------------------------------------|
| Strategy interface | `strategy.AllStrategies()` / `Strategy.Evaluate`       |
| Regime             | `regime.Classifier.Classify`                           |
| Position sizing    | `sizing.PositionSizeINR` (half-Kelly) + `MarginBook`   |
| Risk gates         | `risk.Engine.CheckEntryAllowed` (daily-loss, ratchet, directional caps, margin breach, kill switch) |
| Execution / costs  | `execution.Engine` (ATR slippage + full Indian cost model on **both** legs) |
| Walk-forward rule  | `validator.ComputeWindowStats` (Sharpe ≥ 0.60, WinRate ≥ 0.48, 30-trade windows) |
| Ledger             | `ledger.Ledger`                                        |
| Calendar           | `calendar.Service` (IST hours, NSE holidays)           |

---

## 2. How to run

```bash
# Build
go build ./engine/cmd/backtest

# 3-month backtest, all 29 strategies, Nifty + Bank Nifty (offline/Synthetic)
go run ./engine/cmd/backtest --backtest-from 2023-10-01 --backtest-to 2024-01-01

# Real Kite data (requires credentials in the environment)
export KITE_API_KEY=xxxx KITE_ACCESS_TOKEN=yyyy
go run ./engine/cmd/backtest \
  --backtest-from 2023-07-01 --backtest-to 2024-01-01 \
  --backtest-data-source Kite --backtest-capital 5000000 --backtest-verbose

# Single instrument
go run ./engine/cmd/backtest --backtest-from 2023-12-01 --backtest-to 2023-12-31 \
  --backtest-instruments NIFTY50
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--backtest-from` | _(required)_ | start date `YYYY-MM-DD` (IST) |
| `--backtest-to` | _(required)_ | end date `YYYY-MM-DD` (IST) |
| `--backtest-capital` | `10000000` | starting capital, INR |
| `--backtest-instruments` | `NIFTY50,BANKNIFTY` | comma-separated |
| `--backtest-data-source` | `Kite` | `Kite` \| `NSE` \| `Synthetic` |
| `--backtest-output-dir` | `backtest_results` | output root |
| `--backtest-warmup-days` | `60` | warmup history before start (≥25 needed so the regime classifier has ≥200 15m bars) |
| `--backtest-verbose` | `false` | echo per-trade events to stdout + log |
| `--backtest-seed` | `42` | deterministic seed for the Synthetic source |

If `--backtest-data-source Kite` is requested without `KITE_API_KEY` /
`KITE_ACCESS_TOKEN`, the harness prints a warning and **falls back to the
deterministic Synthetic source** so a run always completes offline.

### Output (`backtest_results/{YYYY-MM-DD_HHMMSS}_UTC/`)

`summary.json`, `summary.md`, `equity_curve.csv`, `equity_curve.png`,
`trades.csv`, `leaderboard.json`, `daily_pnl.csv`, `walkforward_details.json`,
`regime_analysis.csv`, `backtest.log`.

---

## 3. Interpreting walk-forward results

Each strategy is judged on the **live engine's exact promotion rules**:

- **Window** = 30 trades. **Pass** = per-trade Sharpe ≥ 0.60 **and** WinRate ≥ 0.48.
- **PROMOTED** — Window 1 **and** Window 2 both pass (eligible for live paper).
- **REJECTED** — Window 1 fails (no 2-window confirmation), **or** Window 1
  passes but Window 2 fails (fast-demotion analog).
- **INSUFFICIENT_DATA** — fewer than 30 trades in Window 1, or Window 1 passed
  but fewer than 60 total (confirmation window incomplete).

Two Sharpe notions appear, deliberately:

- **Window / leaderboard `sharpe_per_trade`** — mean ÷ stddev of per-trade PnL,
  identical to `validator.ComputeWindowStats`. This is the **promotion metric**.
- **`portfolio_sharpe_annualized`** in `summary.json` — annualized from daily
  returns with a 6% risk-free rate (PART 9). A portfolio-level descriptor, not
  the promotion gate.

---

## 4. Key design decisions

- **No lookahead.** A bar becomes visible only after it closes
  (`bar.Time + interval ≤ now`). Spot and previous-close come solely from the
  1m base stream.
- **Synchronized replay.** All instruments advance on one sorted 1m-close
  timeline. Each timeframe is revealed by its own close.
- **Market hours.** Entries/exits occur only inside 09:15–15:30 IST on NSE
  trading days (`calendar.IsMarketOpen`). Scalping/intraday positions are
  force-closed at session end (`TIME`); swing positions may hold across days
  until SL/TP.
- **Warmup.** History before `--backtest-from` fills indicator buffers; no
  trades or metrics are recorded during warmup.
- **Determinism (CRITICAL CRITERION 4).** Identical inputs ⇒ identical trades
  and equity. Two subtle non-determinism sources were found and fixed: (a) spot
  was being set from a **map-iterated** timeframe stream — now derived only from
  the 1m stream in fixed order; (b) realized PnL was read via
  `ledger.RealizedPnL()`, which folds a map in random order (float addition is
  not associative) — the engine now sums realized PnL in deterministic
  close-order. Verified by `TestReplayDeterministic`.

---

## 5. Deviations from the spec (with rationale)

These keep the harness **CGO-free, dependency-free, and reproducibly buildable**
on the target Windows environment (a cgo C toolchain failed earlier; pulling
heavy modules requires network fetch). The contracts are preserved; only the
backing engines differ.

| Spec asked for | This build uses | Why |
|----------------|-----------------|-----|
| sqlite3 candle cache | per-`(token,interval)` JSON files (`CandleCache`) | cgo-sqlite needs a C toolchain; pure-Go sqlite adds a large dependency tree. Same cache contract. |
| gonum/plot equity PNG | stdlib `image/png` line renderer | no external dependency; deterministic |
| cobra/pflag CLI | stdlib `flag` (supports `--name`) | no external dependency |
| Kite as default source | Kite default, **auto-fallback to Synthetic** offline | a runnable, deterministic sample without API keys |

The **Kite REST fetcher is fully implemented** (real request construction,
auth headers, response parsing, cache write); it simply needs credentials. The
**NSE FTP fetcher is a documented stub** (returns a clear error) — NSE's
bhavcopy URLs/format change and must be re-verified against the current circular.

---

## 6. Known limitations & future work (PART 11)

1. **Synthetic-data magnitudes are not tradable signal.** The default Synthetic
   source produces regime-cycling but artificial price action. Absolute PnL,
   win rates, and Sharpe on Synthetic data validate **harness mechanics only**.
   Use `--backtest-data-source Kite` for real validation.
2. **Options P&L is in underlying-equivalent terms.** The ledger computes
   `(exit − entry) × qty` on the underlying price for **all** instruments,
   including CE/PE/STRANGLE legs (the live execution engine's existing
   simplification — Signal SL/TP are underlying-equivalent). This **massively
   overstates** option-strategy PnL (e.g. a straddle moving with full underlying
   notional). A premium-based options P&L model with real Greeks is required
   before trusting options-strategy magnitudes. Futures-strategy magnitudes are
   closer to realistic.
3. **Slippage is ATR-based**, not order-book-depth aware.
4. **No margin/carry interest** on overnight (swing) positions.
5. **Multi-leg spreads** (strangles/condors) are margined with a coarse
   percent-of-notional approximation, not real SPAN combined-margin offsets.
6. **Corporate actions / dividends** assumed pre-adjusted by the data source.
7. **Per-day kill clear.** The live daily-loss circuit breaker triggers the
   (manually-cleared) kill switch. To model a multi-month backtest as a series
   of trading days, the harness clears a **per-day** daily-loss/margin halt at
   each session rollover (`KillSwitch.ManualClear`), mirroring a desk's morning
   clear. Every kill event is still recorded (`summary.json` → `kill_events`,
   `backtest.log`).
8. **Holding-family classification** (scalping/intraday/swing) is derived from
   the live registry groups; anything not scalping/swing (incl. S1–S9) is
   treated as intraday (EOD-flat).

---

## 7. REGULATORY FLAGS (verify before any real-data or live use)

- **NSE data distribution** — Kite instrument tokens (NIFTY 50 = `256265`,
  NIFTY BANK = `260105`) and NSE bhavcopy URLs/formats change; re-verify.
- **NSE holidays** — `calendar` uses a static 2026 seed; refresh from the NSE
  circular each December (`Service.RefreshFromNSE`).
- **Weekly expiry schedule** — NSE has repeatedly moved expiry days; the regime
  classifier's `EXPIRY_DAY` and swing strategy assumptions depend on it.
- **F&O costs** — STT/brokerage/exchange/SEBI/stamp/GST rates in `costs` are
  point-in-time (post Oct-2024 STT hike); re-verify against current circulars.
- **Lot sizes** — `instruments.LotSize` (NIFTY 75, BANKNIFTY 30) are seeds;
  NSE revises them.
- **SPAN margin** — `sizing` uses a percent-of-notional approximation, not real
  SPAN risk arrays.

---

## 8. Sample run

`engine/backtest_results/2026-06-25_064333_UTC/` — a 3-month Synthetic backtest
(2023-10-01 → 2024-01-01, Nifty50 + BankNifty, ₹1 cr): 331 trades, 2 kill
events, 1 promoted / 1 rejected / 27 insufficient. See the final report for the
walk-forward reading and the explicit caveat that Synthetic magnitudes are for
mechanics validation only.
```bash
go test ./engine/internal/backtest/...   # 45 tests
go vet  ./engine/internal/backtest/...
go build ./engine/cmd/backtest
```
