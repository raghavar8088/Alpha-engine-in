# strategy-service

The strategy library: every trading strategy as an independent module implementing the
shared `Strategy` contract (`shared/tradingai_shared/contracts/strategy.py`). Importing
`strategy_service` registers all strategies into `STRATEGY_REGISTRY`; the backend's
`GET /api/strategies` and the backtesting engine read that registry.

**All 50 roadmap strategies are implemented** (49 modules — `opening_range_breakout`
serves both roadmap slots #19 and #36) across trend, momentum, mean-reversion, swing,
intraday, futures, and options categories. Data-dependent caveats, stated in each
module's docstring: options strategies (#46-50) and directional futures strategies run
as documented underlying-proxies until options-service (Phase 7) wires real
premiums/chains; `oi_buildup` needs futures bars with OI; `calendar_spread` needs
two-leg data and emits nothing until then; `delivery_breakout`/`earnings_momentum` use
tape-signature proxies until the research service (Phase 6) provides real delivery %
and earnings-calendar feeds. Qualification for real capital is earned through
`backtesting-service/validate.py`'s gate + walk-forward tier — never assumed.

## Layout

- `strategy_service/strategies/` — one module per strategy (`ema_cross.py` is the
  reference implementation). Adding a strategy = new module + one import line in
  `strategies/__init__.py`; nothing else changes.
- `strategy_service/indicators.py` — dependency-free indicator helpers (EMA, …).
- `strategy_service/runner.py` — `run_historical(strategy, bars) -> signals`, the pure
  core the backtester builds on.
- `main.py` — CLI to run a strategy over bars stored in Mongo.

## Usage

```
pip install -r requirements.txt        # installs ../shared + this package editable

python main.py --list
python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d
python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --params "{\"fast\": 9, \"slow\": 21}"
```

Bars come from the Mongo `bars` collection — populate it first with
`market-data-service/universe.py` (instrument universe) then
`market-data-service/backfill.py` (historical candles from Dhan).

## Writing a strategy

Subclass `Strategy`, declare `metadata` (`StrategyMetadata` — category, timeframes,
asset classes, expected win rate, risk-reward) and a `Params` pydantic model (defaults
double as the optimizer's parameter schema), implement `on_bar(ctx) -> Signal | None`,
and decorate with `@register_strategy`. Strategies are pure signal generators: no
broker, storage, or risk logic inside — that's what makes the same module run unchanged
in backtest, paper, replay, and live modes.

## Live modes (Phase 5)

`strategy_service/live/synthetic.py` generates synthetic OHLCV bars (a bounded random
walk) for SIMULATION-mode runs that need no real market data. The actual mode-dispatch
runner (`StrategyRunner`) lives in the backend, not here — see
`backend/app/services/strategy_runner.py` for why (avoiding a dependency cycle with
backtesting-service, which already depends on this package).
