"""Month-by-month returns of the top-ranked strategies and of holding gold (python xa_monthly.py).

Rebuilds each strategy's DAILY marked-to-market equity from its stored trades (results/trades/*.csv,
1x notional, compounding) under base costs C1 and, for comparison, C0 (no financing), then takes the
equity at each month's last session. The in-sample run (2010-01 .. 2021-09) and the out-of-sample run
(2021-10 .. latest) are separate, as in the study: the first out-of-sample month starts flat.
Writes results/monthly.json; nothing is re-selected or re-tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json

import numpy as np
import pandas as pd

import xa_data
from xa_engine import COSTS, Market, Trade, equity_curve, net_returns, trades_frame
from xa_run import RES, _jsonable, windows

TOP = ["tsmom", "winter", "faber_sma", "bbdd_ma", "ma_cross", "bollinger_squeeze"]   # the six configurations chosen in-sample, ranked


def load_trades(m: Market, key: str, window: str) -> pd.DataFrame:
    t = pd.read_csv(RES / "trades" / f"{key}.csv")
    t = t[t["window"] == window].copy()
    for c in ("side", "entry_session", "exit_session", "entry_hour", "exit_hour", "nights"):
        t[c] = t[c].astype(int)
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["exit_date"] = pd.to_datetime(t["exit_date"])
    return t.reset_index(drop=True)


def month_returns(eq: pd.Series) -> pd.Series:
    """Return of each calendar month from the equity at month-ends (the first month from the start value)."""
    me = eq.groupby(eq.index.to_period("M")).last()
    prev = pd.concat([pd.Series([eq.iloc[0]], index=[me.index[0] - 1]), me.iloc[:-1]])
    out = pd.Series(me.values / prev.values - 1.0, index=me.index)
    return out


def summary(r: pd.Series) -> dict:
    if not len(r):
        return {}
    growth = float(np.prod(1 + r.values))
    return {"months": int(len(r)), "mean": float(r.mean()), "compounded": float(growth ** (1 / len(r)) - 1),
            "median": float(r.median()), "positive_share": float((r > 0).mean()), "best": float(r.max()),
            "best_month": str(r.idxmax()), "worst": float(r.min()), "worst_month": str(r.idxmin()),
            "sd": float(r.std(ddof=1)) if len(r) > 1 else None, "total": growth - 1}


def main() -> None:
    m = Market.from_bars(xa_data.load())
    w = windows(m)
    out = {"costs": {"C1": COSTS["C1"].name, "C0": COSTS["C0"].name}, "windows": {k: [str(m.d_date[a]), str(m.d_date[b])] for k, (a, b) in w.items()},
           "strategies": {}}
    rows = {}
    for key in TOP + ["gold"]:
        per = {}
        for ck in ("C1", "C0"):
            c = COSTS[ck]
            series = []
            for wn, (a, b) in w.items():
                if key == "gold":
                    tf = trades_frame(m, [Trade(1, a, int(m.s_start[a]), float(m.h_o[m.s_start[a]]), b, int(m.s_end[b] - 1), float(m.d_c[b]), "hold")])
                else:
                    tf = load_trades(m, key, wn)
                r = net_returns(m, tf, c)
                if key != "gold" and ck == "C1":       # the stored net returns must be reproduced exactly
                    assert np.allclose(r, tf["net_C1"].values, atol=1e-12), key
                mr = month_returns(equity_curve(m, tf, r, a, b, c))
                series.append((wn, mr))
            per[ck] = {wn: {"summary": summary(mr), "months": {str(k): float(v) for k, v in mr.items()}} for wn, mr in series}
            allm = pd.concat([mr for _, mr in series])
            per[ck]["ALL"] = {"summary": summary(allm)}
        out["strategies"][key] = per
        rows[key] = per
    (RES / "monthly.json").write_text(json.dumps(_jsonable(out), indent=1))
    names = {"tsmom": "Time-series momentum 6m L/S", "winter": "Winter effect Dec-Feb", "faber_sma": "Faber 8-month SMA",
             "bbdd_ma": "Bartsch (2,9) monthly MA", "ma_cross": "200-day MA, 1% band", "bollinger_squeeze": "Bollinger squeeze", "gold": "Holding gold"}
    print(f"{'':<30} {'IS mean':>8} {'IS cmpd':>8} {'OOS mean':>9} {'OOS cmpd':>9} {'OOS no-fin':>10} {'OOS +mo':>8} {'best':>8} {'worst':>8} {'last12 cmpd':>11}")
    for key in TOP + ["gold"]:
        i = rows[key]["C1"]["IS"]["summary"]
        o = rows[key]["C1"]["OOS"]["summary"]
        o0 = rows[key]["C0"]["OOS"]["summary"]
        last12 = list(rows[key]["C1"]["OOS"]["months"].values())[-12:]
        l12 = float(np.prod([1 + x for x in last12]) ** (1 / 12) - 1)
        print(f"{names[key]:<30} {i['mean']*100:7.2f}% {i['compounded']*100:7.2f}% {o['mean']*100:8.2f}% {o['compounded']*100:8.2f}% "
              f"{o0['compounded']*100:9.2f}% {o['positive_share']*100:7.0f}% {o['best']*100:7.1f}% {o['worst']*100:7.1f}% {l12*100:10.2f}%")
    print()
    for key in TOP[:1] + ["gold"]:
        mm = rows[key]["C1"]["OOS"]["months"]
        print(names[key], "out-of-sample months:")
        print("  " + "  ".join(f"{k}:{v*100:+.1f}%" for k, v in mm.items()))


if __name__ == "__main__":
    main()
