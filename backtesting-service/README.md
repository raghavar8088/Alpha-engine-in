# backtesting-service

Event-driven backtesting engine over the Mongo `bars` stream and the shared `Strategy`
contract (roadmap Phase 2). Custom-built rather than Backtrader/VectorBT so the exact
same strategy modules run unchanged here and in the future live engine, with an Indian
cost stack no off-the-shelf engine models.

## What it models

- **No look-ahead:** signals fill at the NEXT bar's open, slippage-adjusted (bps,
  applied against you). Stops/targets trigger intra-bar off high/low; if both could hit
  in one bar the stop is assumed first (worst case). Gap-through-stop exits at the open.
- **Indian costs** (`costs.py`, all rates configurable): brokerage (Dhan defaults),
  STT (post-Oct-2024 rates), NSE transaction charges, SEBI fee, stamp duty, 18% GST.
- **Partial fills:** order size capped at `max_volume_participation` × bar volume.
- **Metrics** (`metrics.py`): net/CAGR, win rate, profit factor, expectancy, Sharpe,
  Sortino, Calmar, max DD, recovery factor, avg win/loss, holding time, streaks,
  exposure, monthly/yearly returns.
- **Charts** (`charts.py`): render-ready JSON — equity, drawdown, rolling return,
  trade distribution, trade list (downsampled to ≤2k points).
- **Analyses:** grid optimization (`optimizer.py`), anchored walk-forward with per-window
  re-optimization (`walkforward.py`; n_windows=1 ≡ plain OOS split), bootstrap Monte
  Carlo with ruin probability (`montecarlo.py`).
- **Risk-checked sizing (Phase 4):** every entry is sized and approved by
  `risk-service`'s `RiskEngine` before becoming a trade — pick `sizing_method` on
  `BacktestConfig` (capital_pct / fixed_fractional / atr / volatility / kelly) and
  optional `risk_limits` (exposure/sector/heat caps, daily-loss and max-drawdown
  kill-switches). Defaults reproduce pre-Phase-4 behavior exactly; a run's blocked/
  trimmed entries show up in `BacktestRun.risk_rejections`.

`service.py: run_backtest()` is the single entry point (CLI and backend both call it);
results persist to the Mongo `backtests` collection.

## Usage

```
pip install -r requirements.txt

python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --years 5
python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --walk-forward --monte-carlo
python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --grid "{\"fast\": [10,20,30], \"slow\": [50,100]}"
```

Or via the backend: `POST /api/backtest`, `GET /api/backtest`, `GET /api/backtest/{id}`,
and the `/backtesting` screen in the frontend.

Known v1 simplifications (each is a later-phase item): short trades use long-notional
cash accounting (no margin model), no forced intraday square-off, options pricing waits
for Phase 7 (options-service).
