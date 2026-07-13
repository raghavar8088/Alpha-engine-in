"""Strategy validation gate — batch-runs every registered strategy through the
backtester and records a 3-state status per strategy in Mongo `strategy_validation`:

  pass               >=1 (symbol, timeframe) run clears the gate
  fail               runs traded enough but none cleared the gate
  insufficient_data  no run produced >= min_trades (awaiting data or filters too strict)

Gate per run: trades>=5, PF>1, win rate>=40%, expectancy>0, max DD<=25%.

REAL-MONEY TIER: passing strategies additionally face an anchored walk-forward on
their best passing run (small re-optimization grid). real_money_ready requires
consistency >= 50% of OOS windows profitable AND total OOS net > 0. This is the bar
for live capital — a plain in-sample pass is not.

Run:  python validate.py                (all strategies)
      python validate.py ema_cross     (one strategy)
      python validate.py --no-wf      (skip the walk-forward tier, faster)
"""

import sys
from datetime import datetime, timezone

from backtesting_service.engine import BacktestConfig, BacktestEngine
from backtesting_service.metrics import compute_metrics
from backtesting_service.service import _db, load_bars
from backtesting_service.walkforward import walk_forward
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import Timeframe

DAILY_SET = (
    ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN"],
    Timeframe.D1,
    5.0,
)
INTRADAY_SET = (["NIFTY", "RELIANCE", "HDFCBANK"], Timeframe.M15, 1.0)

GATE = {"min_trades": 5, "min_pf": 1.0, "min_win_rate": 0.40, "max_dd_pct": 25.0}
RM_MIN_CONSISTENCY = 0.5  # fraction of OOS windows that must be profitable
WF_WINDOWS = 3

_BENCH_CACHE: dict = {}


def _benchmark(timeframe: Timeframe, years: float):
    key = (timeframe, years)
    if key not in _BENCH_CACHE:
        _BENCH_CACHE[key] = load_bars("NIFTY", timeframe, years)
    return _BENCH_CACHE[key]


def gate_check(m: dict) -> tuple[bool, list[str]]:
    reasons = []
    if m["total_trades"] < GATE["min_trades"]:
        reasons.append(f"trades {m['total_trades']} < {GATE['min_trades']}")
    if m["profit_factor"] is None or m["profit_factor"] <= GATE["min_pf"]:
        reasons.append(f"profit factor {m['profit_factor']} <= {GATE['min_pf']}")
    if m["win_rate"] is None or m["win_rate"] < GATE["min_win_rate"]:
        wr = f"{m['win_rate']:.0%}" if m["win_rate"] is not None else "n/a"
        reasons.append(f"win rate {wr} < {GATE['min_win_rate']:.0%}")
    if m["expectancy"] is None or m["expectancy"] <= 0:
        reasons.append(f"expectancy {m['expectancy']} <= 0")
    if m["max_drawdown_pct"] > GATE["max_dd_pct"]:
        reasons.append(f"max DD {m['max_drawdown_pct']}% > {GATE['max_dd_pct']}%")
    return (not reasons), reasons


def _small_grid(strategy_id: str) -> dict:
    """Walk-forward re-optimization grid: first two int params, x0.5/x1/x1.5 each —
    bounded so the real-money tier stays computable across the whole library."""
    defaults = STRATEGY_REGISTRY[strategy_id].Params().model_dump()
    grid = {}
    for key, value in sorted(defaults.items()):
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        grid[key] = sorted({max(2, value // 2), value, value + value // 2})
        if len(grid) == 2:
            break
    return grid


def validate_strategy(strategy_id: str, with_wf: bool = True) -> dict:
    cls = STRATEGY_REGISTRY[strategy_id]
    declared = cls.metadata.timeframes
    sets = []
    if any(tf in (Timeframe.D1, Timeframe.W1, Timeframe.H1) for tf in declared):
        sets.append(DAILY_SET)
    if any(tf in (Timeframe.M1, Timeframe.M5, Timeframe.M15) for tf in declared):
        sets.append(INTRADAY_SET)

    runs = []
    for symbols, timeframe, years in sets:
        for symbol in symbols:
            bars = load_bars(symbol, timeframe, years)
            if not bars:
                continue
            strategy = cls()
            benchmark = (
                _benchmark(timeframe, years)
                if getattr(strategy, "requires_benchmark", False) and symbol != "NIFTY"
                else None
            )
            config = BacktestConfig(strategy_id=strategy_id, symbol=symbol, timeframe=timeframe)
            metrics = compute_metrics(BacktestEngine(strategy, config).run(bars, benchmark_bars=benchmark))
            passed, reasons = gate_check(metrics)
            runs.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.value,
                    "bar_count": len(bars),
                    "passed": passed,
                    "fail_reasons": reasons,
                    "metrics": {
                        k: metrics[k]
                        for k in (
                            "net_profit", "total_return_pct", "cagr_pct", "total_trades",
                            "win_rate", "profit_factor", "expectancy", "sharpe",
                            "max_drawdown_pct", "exposure_pct",
                        )
                    },
                }
            )

    passing = [r for r in runs if r["passed"]]
    traded = [r for r in runs if r["metrics"]["total_trades"] >= GATE["min_trades"]]
    if passing:
        status = "pass"
    elif traded:
        status = "fail"
    else:
        status = "insufficient_data"

    best = max(runs, key=lambda r: (r["passed"], r["metrics"]["profit_factor"] or 0)) if runs else None

    # Real-money tier: honest out-of-sample re-test of the best PASSING run
    real_money = None
    if status == "pass" and with_wf:
        target = max(passing, key=lambda r: r["metrics"]["profit_factor"] or 0)
        tf = Timeframe(target["timeframe"])
        years = DAILY_SET[2] if tf == Timeframe.D1 else INTRADAY_SET[2]
        bars = load_bars(target["symbol"], tf, years)
        config = BacktestConfig(strategy_id=strategy_id, symbol=target["symbol"], timeframe=tf)
        wf_benchmark = (
            _benchmark(tf, years)
            if getattr(cls(), "requires_benchmark", False) and target["symbol"] != "NIFTY"
            else None
        )
        try:
            wf = walk_forward(
                config, bars, _small_grid(strategy_id), n_windows=WF_WINDOWS,
                benchmark_bars=wf_benchmark,
            )
            real_money = {
                "symbol": target["symbol"],
                "timeframe": tf.value,
                "consistency": wf["consistency"],
                "oos_net_profit": wf["oos_net_profit"],
                "oos_total_trades": wf["oos_total_trades"],
                "ready": wf["consistency"] >= RM_MIN_CONSISTENCY and wf["oos_net_profit"] > 0,
            }
        except ValueError as exc:  # windows too short for warmup etc.
            real_money = {"symbol": target["symbol"], "timeframe": tf.value, "ready": False, "error": str(exc)}

    return {
        "strategy_id": strategy_id,
        "gate": GATE,
        "status": status,
        "passed": status == "pass",
        "passing_runs": len(passing),
        "total_runs": len(runs),
        "runs": runs,
        "best_run": best,
        "real_money": real_money,
        "real_money_ready": bool(real_money and real_money.get("ready")),
        "validated_at": datetime.now(timezone.utc),
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-wf"]
    with_wf = "--no-wf" not in sys.argv
    only = args[0] if args else None
    ids = [only] if only else sorted(STRATEGY_REGISTRY)
    if only and only not in STRATEGY_REGISTRY:
        raise SystemExit(f"unknown strategy {only!r}")

    collection = _db()["strategy_validation"]
    collection.create_index("strategy_id", unique=True, name="strategy_id")

    counts = {"pass": 0, "fail": 0, "insufficient_data": 0, "real_money": 0}
    for sid in ids:
        doc = validate_strategy(sid, with_wf=with_wf)
        collection.replace_one({"strategy_id": sid}, doc, upsert=True)
        counts[doc["status"]] += 1
        if doc["real_money_ready"]:
            counts["real_money"] += 1
            tag = "REAL-MONEY"
        else:
            tag = {"pass": "PASS      ", "fail": "fail      ", "insufficient_data": "no-data   "}[doc["status"]]
        rm = doc.get("real_money") or {}
        extra = (
            f"  WF consistency={rm['consistency']:.0%} OOS net={rm['oos_net_profit']:,.0f}"
            if "consistency" in rm
            else ""
        )
        print(f"[{tag}] {sid:26s} {doc['passing_runs']}/{doc['total_runs']} runs pass{extra}")

    print(
        f"\n{counts['pass']} pass ({counts['real_money']} real-money ready), "
        f"{counts['fail']} fail, {counts['insufficient_data']} insufficient data"
    )
