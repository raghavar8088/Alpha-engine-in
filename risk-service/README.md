# risk-service

Position sizing + exposure/drawdown limits + kill-switch (roadmap Phase 4). Every entry
Signal is sized and approved here before it becomes an order — in the backtester
today, and live via the backend's `POST /api/broker/orders` guard and
`GET /api/risk/status`.

## Layout

- `risk_service/sizing.py` — pure sizing functions: `fixed_capital_pct_quantity` (the
  original % of equity), `fixed_fractional_quantity` (risk % of equity off a stop
  distance), `atr_quantity` (stop distance = N x ATR), `volatility_target_quantity`
  (size inversely to instrument volatility), `kelly_quantity`/`kelly_fraction`
  (capped at quarter-Kelly by default).
- `risk_service/engine.py` — `RiskEngine`: entry-only `evaluate()` (exits are never
  gated — the engine prevents taking on MORE risk, not reducing it) that runs, in
  order: kill-switch checks (daily loss limit, max drawdown — the drawdown trip
  persists across day boundaries, the daily one resets each day), max open positions,
  the chosen sizing method, then trims (never silently ignores) for max exposure,
  max sector exposure, and portfolio heat (sum of at-risk capital).

## Defaults are permissive by design

`RiskLimits()` with no arguments disables every limit (100%+ thresholds) so wiring
this into the backtester didn't shift any already-validated Phase 3 result — a caller
must opt into tighter limits. The backend's live `/api/risk/status` uses its own
tighter defaults (3% daily loss, 15% max drawdown, 5 max positions, 80%/30%/6% for
exposure/sector/heat), configurable via `GET/PUT /api/risk/config`.

## Usage

```python
from risk_service import RiskEngine, RiskLimits, SizingConfig, SizingMethod, PositionSnapshot

engine = RiskEngine(RiskLimits(daily_loss_limit_pct=2.0, max_drawdown_pct=10.0))
engine.update_equity(current_equity, day_key=today)  # call once per bar/tick
decision = engine.evaluate(
    price=101.5, equity=current_equity, open_positions=[],
    sizing=SizingConfig(method=SizingMethod.FIXED_FRACTIONAL, risk_pct=1.0),
    stop_loss=98.0, lot_size=1,
)
if decision.approved:
    place_order(quantity=decision.quantity)
```

## Known v1 scope

- The backtester only ever holds one position at a time, so `open_positions` is
  always `[]` there — `max_open_positions`/sector-exposure limits are exercised
  meaningfully once Phase 5's live engine runs multiple strategies concurrently.
- The live `/api/risk/status` is a point-in-time approximation from Dhan's own
  day-scoped position P&L (no persisted equity curve yet), so max-drawdown and
  portfolio-heat aren't truly tracked live — that lands with Phase 5 (per-position
  stop tracking) and Phase 8 (scheduler-persisted equity snapshots).
