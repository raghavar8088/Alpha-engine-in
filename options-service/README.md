# options-service

Options & futures analytics (roadmap Phase 7): Black-Scholes pricing/Greeks/IV, live
Dhan option-chain analytics, multi-leg payoff, and a synthetic-premium backtester for
strategies #46-50 (which ran as underlying-price proxies until this phase).

## Modules

- `greeks.py` — pure-python Black-Scholes price/Greeks/IV solver (Newton-Raphson +
  bisection fallback). Verified: put-call parity holds exactly, IV solver round-trips.
- `chain.py` — normalizes Dhan's raw `/optionchain` response (fetched by
  `backend/app/services/dhan_client.py`'s `option_chain()`/`option_chain_expiry_list()`
  — this package stays broker-call-free and unit-testable). Fills Greeks/IV gaps for
  illiquid strikes (0 from Dhan) with our own Black-Scholes when a last-traded price
  exists, tagging every leg `"source": "broker"` or `"source": "computed"` so a caller
  never mistakes a modeled value for an exchange quote. Also: PCR (put/call OI ratio),
  max pain, per-contract OI build-up classification (Long/Short Build-up, Long
  Unwinding, Short Covering).
- `payoff.py` — multi-leg payoff diagram, breakeven(s) (root-found, works for any leg
  count), max profit/loss (`None` + `*_unbounded: true` for naked positions — never a
  truncated number pretending to be the true max), net Greeks.
- `options_backtest.py` — see its module docstring for the full rationale: Dhan has no
  continuous multi-year option-chain history (each contract trades one expiry cycle),
  so premiums are Black-Scholes-modeled from the underlying's own realized volatility —
  the standard institutional fallback when true historical chains aren't available,
  never presented as historical-quoted. Each strategy's own `on_bar` (unchanged) reads
  the UNDERLYING's bars for entry/exit; this module turns each signal into a real
  options structure (1-4 legs) and produces a `BacktestRun` — the same object the
  equity backtester emits, so `compute_metrics`/`compute_charts` need no changes.

## Verified

- Greeks: put-call parity, ATM delta ≈ 0.5, IV round-trip — all exact.
- Chain: live NIFTY chain (234 strikes) parses correctly; PCR/max-pain/OI-buildup all
  computed from real Dhan data.
- Payoff: Bull Put Spread and Iron Condor max-profit/loss/breakeven match textbook
  values exactly; naked long/short correctly flagged unbounded.
- Options backtest: **a P&L sign bug was found and fixed during this build** — closing
  a structure reverses every leg's direction, so P&L is `entry_net_premium - exit_value`,
  not the other way around (verified against a worked example, then confirmed all 5
  strategies flipped from economically implausible results — e.g. a net-credit spread
  showing a 17% win rate — to plausible ones — that same spread at 83%). Equity
  reconciles exactly with summed trade P&L for all 5 strategies.

## Usage

```python
from options_service.options_backtest import run_options_backtest
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

bars = load_bars("NIFTY", Timeframe.D1, 5)
result = run_options_backtest("bull_put_spread", "NIFTY", Timeframe.D1, bars, lot_size=75)
print(result["metrics"])  # same shape as backtesting-service's compute_metrics()
```

Or via the backend: `GET /api/options/expiries/{symbol}`, `GET /api/options/chain/{symbol}`,
`POST /api/options/payoff`, `POST /api/options/backtest`, and the `/options` screen
(chain / payoff builder / strategy backtest tabs).

Only the 5 whitelisted index underlyings (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY,
SENSEX) have option-chain support — matches the instrument universe from Phase 1;
individual stock options were deliberately deferred there.

## Option-Buying Lab (strategies #51-100)

`options_backtest.py` also backtests any strategy in the `options_scalp` /
`options_intraday` / `options_swing` categories (the 50-strategy option-buying library
in `strategy-service/strategy_service/strategies/options_buying/`): a BUY signal buys
the ATM CE, a SELL buys the ATM PE, and the engine applies per-style defaults
(`OPTION_BUYING_CATEGORIES`) — scalp: 2-DTE, 25%/50% premium stop/target, EOD
square-off; intraday: 3-DTE, 30%/60%, EOD square-off; swing: 30-DTE, 40%/80%, carried.
EOD square-off also blocks new entries on a session's last bar.

`POST /api/options/backtest-all` sweeps all 50 over one window and stores a leaderboard
document in `option_sweeps`; a strategy **qualifies** when `win_rate >= min_win_rate`
(default 40%) AND `total_trades >= min_trades` (default 10 — a 1-trade 100% "winner"
must not qualify). `GET /api/options/qualified` returns the latest sweep. The
`/options` screen's "Buying Lab (50)" tab drives both. Scalp strategies want 5m bars
and fall back to 15m (labeled) until the 5m backfill exists.
