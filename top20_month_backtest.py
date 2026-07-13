"""Top-20 basket month backtest — run from your terminal:

    & "D:\\INDIAN MARKET\\TradingAI\\backend\\.venv\\Scripts\\python.exe" "D:\\INDIAN MARKET\\top20_month_backtest.py" 2026 6

Args: YEAR MONTH. Uses real Dhan NIFTY candles from MongoDB + the audited
Black-Scholes premium engine (expiry-aligned DTE, daily-vol IV). Prints each
session's P&L, peak capital, ROI, the month total, and the per-strategy split.
Real-premium audits are only possible for still-listed contracts (right now:
entries from 2026-07-08 onward) — for older months this model is the only
option, since Dhan purges expired contracts' history."""

import sys
from collections import defaultdict
from datetime import date, timedelta

import strategy_service  # noqa: F401  (registers all strategies)
from backtesting_service.service import load_bars
from options_service.options_backtest import run_options_backtest
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import Timeframe

ROWS = [
    ("scalp_ibs", "5m"), ("intra_heikin_trend", "15m"), ("intra_ichimoku_tk", "5m"),
    ("scalp_roc_thrust", "15m"), ("intra_cci_trend", "5m"), ("intra_psar", "15m"),
    ("intra_dema_cross", "15m"), ("swing_fractal", "1h"), ("scalp_atr_burst", "5m"),
    ("intra_keltner_trend", "5m"), ("intra_bb_ride", "5m"), ("scalp_rsi2", "5m"),
    ("intra_donchian", "5m"), ("intra_linreg_slope", "5m"), ("intra_hull_cross", "15m"),
    ("intra_cci_trend", "15m"), ("scalp_psar", "15m"), ("scalp_keltner_surf", "5m"),
    ("scalp_pctb", "5m"), ("scalp_cci_burst", "15m"),
]
LOT, STEP = 75, 50.0


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    year, month = int(sys.argv[1]), int(sys.argv[2])

    # window must reach back far enough from "now" to cover the target month + warmup
    today = date.today()
    months_back = (today.year - year) * 12 + (today.month - month)
    window_intraday = min(0.25 + months_back * 0.085, 9.0)
    window_hourly = min(0.6 + months_back * 0.085, 9.0)

    # sessions = trading dates present in the real 15m data for that month
    probe = load_bars("NIFTY", Timeframe.M15, window_intraday)
    sessions = sorted({b.ts.date() for b in probe if b.ts.year == year and b.ts.month == month})
    if not sessions:
        print(f"No NIFTY bars found for {year}-{month:02d} — backfill that period first.")
        sys.exit(1)
    cuts = [sessions[0]] + [s + timedelta(days=1) for s in sessions]
    print(f"{len(sessions)} sessions in {year}-{month:02d}: {sessions[0]} .. {sessions[-1]}\n")

    daily = defaultdict(float)
    day_events = defaultdict(list)
    per_row = {}
    for n, (sid, tfv) in enumerate(ROWS, 1):
        cls = STRATEGY_REGISTRY[sid]
        cat = cls.metadata.category
        tf = Timeframe(tfv)
        expiry_wd = 1 if cat in ("options_scalp", "options_intraday", "options_breakout") else None
        window = window_hourly if tfv == "1h" else window_intraday
        bars = load_bars("NIFTY", tf, window)
        eqs, trades = [], None
        for i, cut in enumerate(cuts):
            prefix = [b for b in bars if b.ts.date() < cut]
            r = run_options_backtest(sid, "NIFTY", tf, prefix, quantity_lots=1, lot_size=LOT,
                                     strike_step=STEP, expiry_weekday=expiry_wd,
                                     include_trades=(i == len(cuts) - 1))
            eqs.append(r["metrics"]["final_equity"])
            if i == len(cuts) - 1:
                trades = r["trades"]
        per_row[f"{sid}@{tfv}"] = eqs[-1] - eqs[0]
        for i, s in enumerate(sessions):
            daily[s] += eqs[i + 1] - eqs[i]
        for t in trades:
            ed = t["entry_ts"].date()
            if ed in sessions:
                debit = max(-t["entry_price"], 0.0) * LOT
                day_events[ed].append((t["entry_ts"].isoformat(), debit))
                day_events[ed].append(((t["exit_ts"] or t["entry_ts"]).isoformat(), -debit))
        print(f"[{n:2d}/20] {sid}@{tfv}: month {eqs[-1]-eqs[0]:+,.0f}", flush=True)

    print(f"\n{'day':12s} {'P&L':>10s} {'peak cap':>10s} {'ROI':>8s}")
    total, month_peak = 0.0, 0.0
    for s in sessions:
        evs = sorted(day_events[s], key=lambda e: (e[0], -e[1]))
        cur = peak = 0.0
        for _, d in evs:
            cur += d
            peak = max(peak, cur)
        p = daily[s]
        total += p
        month_peak = max(month_peak, peak)
        print(f"{s.strftime('%a %b %d'):12s} {p:10,.0f} {peak:10,.0f} {p/peak*100 if peak else 0:7.2f}%")
    print("-" * 44)
    print(f"MONTH {year}-{month:02d}: {total:+,.0f} | peak capital {month_peak:,.0f} "
          f"| ROI {total/month_peak*100 if month_peak else 0:.2f}%\n")
    for k, v in sorted(per_row.items(), key=lambda kv: -kv[1]):
        print(f"{k:30s} {v:+10,.0f}")


if __name__ == "__main__":
    main()
