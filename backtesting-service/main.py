"""Backtesting-service CLI.

Examples:
    python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --years 5
    python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --walk-forward --monte-carlo
    python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --grid "{\"fast\": [10,20,30], \"slow\": [50,100]}"
"""

import argparse
import json

from tradingai_shared.domain import Timeframe

from backtesting_service.service import run_backtest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a backtest over stored bars")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--years", type=float, default=None)
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--params", default="{}", help="JSON param overrides")
    parser.add_argument("--grid", default=None, help="JSON param grid for optimization/WF")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--monte-carlo", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    doc = run_backtest(
        strategy_id=args.strategy,
        symbol=args.symbol,
        timeframe=Timeframe(args.timeframe),
        years=args.years,
        initial_capital=args.capital,
        params=json.loads(args.params),
        param_grid=json.loads(args.grid) if args.grid else None,
        with_walk_forward=args.walk_forward,
        with_monte_carlo=args.monte_carlo,
        persist=not args.no_persist,
    )

    m = doc["metrics"]
    print(f"\n=== {args.strategy} on {args.symbol} {args.timeframe} "
          f"({doc['start']:%Y-%m-%d} to {doc['end']:%Y-%m-%d}, {doc['bar_count']} bars) ===")
    rows = [
        ("Net profit", f"{m['net_profit']:,.0f} ({m['total_return_pct']:+.1f}%)"),
        ("CAGR", f"{m['cagr_pct']}%" if m["cagr_pct"] is not None else "-"),
        ("Trades", f"{m['total_trades']} (win rate {m['win_rate']:.0%})" if m["win_rate"] is not None else str(m["total_trades"])),
        ("Profit factor", m["profit_factor"]),
        ("Expectancy/trade", m["expectancy"]),
        ("Sharpe / Sortino", f"{m['sharpe']} / {m['sortino']}"),
        ("Calmar", m["calmar"]),
        ("Max drawdown", f"{m['max_drawdown_pct']}% ({m['max_drawdown_value']:,.0f})"),
        ("Recovery factor", m["recovery_factor"]),
        ("Avg win / loss", f"{m['avg_win']} / {m['avg_loss']}"),
        ("Streaks (W/L)", f"{m['max_win_streak']} / {m['max_loss_streak']}"),
        ("Exposure", f"{m['exposure_pct']}%"),
        ("Total charges", f"{m['total_charges']:,.0f}"),
        ("Final equity", f"{m['final_equity']:,.0f}"),
    ]
    for label, value in rows:
        print(f"  {label:20s} {value}")

    if "walk_forward" in doc:
        wf = doc["walk_forward"]
        print(f"\n--- Walk-forward ({wf['n_windows']} windows, consistency {wf['consistency']:.0%}) ---")
        for w in wf["windows"]:
            om = w["oos_metrics"]
            print(f"  W{w['window']}: {w['test_start'][:10]} to {w['test_end'][:10]}  "
                  f"params={w['best_params']}  OOS net={om['net_profit']:,.0f} "
                  f"trades={om['total_trades']}")
        print(f"  OOS total: net={wf['oos_net_profit']:,.0f} trades={wf['oos_total_trades']}")

    if "monte_carlo" in doc:
        mc = doc["monte_carlo"]
        if "error" in mc:
            print(f"\n--- Monte Carlo: {mc['error']} ---")
        else:
            fe, dd = mc["final_equity"], mc["max_drawdown_pct"]
            print(f"\n--- Monte Carlo ({mc['n_runs']} runs) ---")
            print(f"  Final equity  p5={fe['p5']:,.0f}  p50={fe['p50']:,.0f}  p95={fe['p95']:,.0f}")
            print(f"  Max drawdown  p5={dd['p5']}%  p50={dd['p50']}%  p95={dd['p95']}%")
            print(f"  P(profit)={mc['prob_profit']:.0%}  P(DD>{mc['ruin_threshold_pct']}%)={mc['prob_ruin']:.1%}")

    if "optimization" in doc:
        print("\n--- Optimization (top 5) ---")
        for r in doc["optimization"][:5]:
            rm = r["metrics"]
            print(f"  {r['params']}  PF={rm['profit_factor']} net={rm['net_profit']:,.0f} "
                  f"trades={rm['total_trades']} maxDD={rm['max_drawdown_pct']}%")

    if "_id" in doc:
        print(f"\nsaved as backtest {doc['_id']}")
