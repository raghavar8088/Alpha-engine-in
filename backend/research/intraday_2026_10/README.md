# Intraday Stocks audit and research — 2026-10-10

Scripts behind [`INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md`](../../../INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md). All are read-only and run inside the backend image:

```
docker cp <script> alpha-engine-backend-1:/tmp/
docker exec -e PYTHONPATH=/app/backend alpha-engine-backend-1 python /tmp/<script>
```

The walk-forward trades file (`/data/intraday/backtests/v2-<run_id>-trades.jsonl.gz`) is regenerated nightly; the figures in the plan are from run `20261010-0605`. Point `PATH` at a newer run to refresh them.

| Script | Settles |
|---|---|
| `ids_live_audit.py` | the tournament's live paper record 2026-10-06..09: 1,596 trades, gross +Rs2.47 L, Angel charges Rs6.41 L (2.60x gross), net -Rs3.94 L; cost components (STT 62%); per-strategy table; exit reasons; holding time; the gate's verdicts (0 ready, 26 rejected, 27 pending) |
| `ids_live_split.py` | the same record by catalog category and timeframe; why four sessions cannot speak to edge (per-session t -0.71, n = 4); cost per trade 4.0 bp against a median move of 53 bp; every fill from the stream with 1-4 bp slippage; largest position 0.083% of its stock's daily value |
| `ids_walkforward.py` | the two-year walk-forward per strategy (495 sessions): gross -Rs5.35 cr, net -Rs11.51 cr; 5 of 52 positive gross, 0 net; the survival funnel; selection vs holdout. The two `~opt` rows are an optimistic bound on ambiguous ORB bars, not strategies |
| `ids_walkforward_cuts.py` | the same record cut every way: category, kind, timeframe, side, ex-ante trend and volatility regime (NIFTY daily from `bars`), day type, entry time, holding time, exit reason, fee sensitivity, drawdown (-42.6% of Rs27 cr, 0 of 25 months positive, Sharpe -9.28), monthly, symbols. Every ex-ante cut is negative; the stop-loss is the gross loss (-78 bp a stop-out) |
| `ids_friction.py` | slippage separated from edge (2.76 bp a side, the live desk's mean, as an assumption): frictionless edge +1.67 bp vs 9.19 bp of friction; 37 of 52 strategies have a positive raw edge, 6 clear t 3.31 on it; break-even slippage per strategy (donchian_45m 1.80, donchian_1h 1.50, vwap_trend_1h 1.29 bp a side); the mirrored book loses 10.86 bp a trade; the Live Intraday picks' four-session record |
| `ids_strategy_table.py` | generates the plan's 54-row assessment table and its mechanical decision rule (3 OPTIMIZE, 7 RESEARCH ONLY, 42 DISABLE, 2 INCUBATE), and the Patterns desk by timeframe and family with targets filled at the target and 3 bp a side of slippage. Output: `ids_strategy_table_out.md` |
| `ids_patterns_overshoot.py` | the Patterns fill defect: target exits booked Rs52.8 L better than their own levels, stop exits Rs40.7 L worse; reported +Rs52.97 L becomes +Rs19,035 with targets at the target and -Rs23.1 L with 3 bp slippage |
| `ids_concentration.py` | strategies stacking on one bet: 88% of Patterns trades share a (symbol, side, price, minute) with another strategy, up to 32 at once (BBOX, Rs3.18 cr on one idea); the tournament's cap of two holds (23%, one cluster of three) |
| `ids_live_trading_ledger.py` | the REAL-money desk: disarmed, all eight strategies flagged enabled; 78 real Angel orders 2026-08-10..20, Rs2.76 L notional; no charges recorded on any; 49 closed by Angel's MIS auto-square-off and booked at the next session's price (`stale_session_reconciled`, no exit order id) |
| `ids_fee_card.py` | (no database) Angel One's intraday equity card on a Rs10 L round trip against the desk's measured charges: Rs402.01 vs Rs401.42, 4.02 bp. The cost model is right; STT cannot be sized away |

Data is read from production and not committed. Nothing here writes.
