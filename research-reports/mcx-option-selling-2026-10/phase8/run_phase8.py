"""Phase 8 (AMENDMENT_A8.md + A8_1): the fixed intraday set, run once on the app's recorded MCX bars.

    python run_phase8.py <bars.csv.gz> <out_dir>
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine8 as E8  # noqa: E402

SYMS = ("CRUDEOIL", "NATURALGAS")
STRATS = [
    ("ORB-AM", "5m", lambda d, s, sym: E8.s_orb(d, s, "09:00", "09:30", "09:30", 6)),
    ("ORB-US", "5m", lambda d, s, sym: E8.s_orb(d, s, "18:30", "19:00", "19:00", 6)),
    ("PDHL", "5m", lambda d, s, sym: E8.s_pdhl(d, s)),
    ("VWAP-REV", "5m", lambda d, s, sym: E8.s_vwap(d, s)),
    ("RSI2", "5m", lambda d, s, sym: E8.s_rsi2(d, s)),
    ("EMA-X", "5m", lambda d, s, sym: E8.s_emax(d, s)),
    ("MOM-LH-a", "5m", lambda d, s, sym: E8.s_momlh(d, s, "09:00")),
    ("MOM-LH-b", "5m", lambda d, s, sym: E8.s_momlh(d, s, "18:30")),
    ("EVT", "5m", lambda d, s, sym: E8.s_event(d, s, 2 if sym == "CRUDEOIL" else 3)),
    ("BB-BREAK", "15m", lambda d, s, sym: E8.s_bb(d, s)),
    ("GAP-FADE", "5m", lambda d, s, sym: E8.s_gap(d, s)),
    ("LONG-DAY", "5m", lambda d, s, sym: E8.s_long(d, s, "09:00")),
    ("LONG-US", "5m", lambda d, s, sym: E8.s_long(d, s, "18:30")),
    ("MOM-LH-1h", "1h", lambda d, s, sym: E8.h_momlh(d, s)),
    ("EMA-X-1h", "1h", lambda d, s, sym: E8.h_emax(d, s)),
    ("ORB-US-1h", "1h", lambda d, s, sym: E8.h_orbus(d, s)),
]
assert len(STRATS) == 16                                  # AMENDMENT_A8's set, per instrument
T_BAR = 3.0


def stats(trades, days, sym):
    """Per-trade, daily and weekly statistics on a Rs10 lakh account at 1x exposure."""
    day_ix = pd.DatetimeIndex([d.day for d in days])
    net = np.array([t["net"] for t in trades]) if trades else np.array([])
    daily = pd.Series(0.0, index=day_ix)
    for t in trades:
        daily[t["day"]] += t["net"]
    wk = daily.groupby([daily.index.isocalendar().year, daily.index.isocalendar().week]).sum()
    n = len(net)
    sd = net.std(ddof=1) if n > 1 else np.nan
    mid = day_ix[len(day_ix) // 2]
    h1 = sum(t["net"] for t in trades if t["day"] < mid)
    h2 = sum(t["net"] for t in trades if t["day"] >= mid)
    cum = np.concatenate([[0.0], np.cumsum(daily.to_numpy())])
    dsd = daily.std(ddof=1)
    out = {"days": len(day_ix), "window": f"{day_ix[0].date()}..{day_ix[-1].date()}", "weeks": int(len(wk)), "trades": n,
           "win": float((net > 0).mean()) if n else 0.0, "avg_bp": float(net.mean() * 1e4) if n else 0.0,
           "t": float(net.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else np.nan,
           "net_pct": float(net.sum() * 100), "half1_pct": float(h1 * 100), "half2_pct": float(h2 * 100),
           "sharpe_daily_ann": float(daily.mean() / dsd * math.sqrt(252)) if dsd > 0 else np.nan,
           "week_mean_pct": float(wk.mean() * 100), "weeks_profitable": float((wk > 0).mean()),
           "weeks_ge2pct": float((wk >= 0.02).mean()), "worst_week_pct": float(wk.min() * 100),
           "best_week_pct": float(wk.max() * 100), "maxdd_pct": float((np.maximum.accumulate(cum) - cum).max() * 100)}
    cap = 1 / E8.MARGIN[sym]
    m = wk.mean()
    if m > 0:
        out["L_star"] = float(0.02 / m)
        out["L_fits_margin"] = bool(out["L_star"] <= cap)
        out["worst_week_at_L_pct"] = float(out["L_star"] * wk.min() * 100)
    return out


def main(path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    b = E8.load(path)
    sess = {(sym, tf): E8.sessions(b, sym, tf) for sym in SYMS for tf in ("5m", "15m", "1h")}
    for (sym, tf), days in sess.items():
        print(f"{sym:10s} {tf:3s}: {len(days)} sessions {days[0].day.date()}..{days[-1].day.date()}", flush=True)
    rows = []
    print(f"\nround-trip cost excluding slippage: {E8.COST * 1e4:.2f} bp; slippage 1 tick each side "
          f"(crude Rs1, gas Rs0.10)\n", flush=True)
    for sym in SYMS:
        for code, tf, fn in STRATS:
            days = sess[(sym, tf)]
            t1 = fn(days, E8.TICK[sym], sym)
            t2 = fn(days, 2 * E8.TICK[sym], sym)
            s1, s2 = stats(t1, days, sym), stats(t2, days, sym)
            promising = bool(s2["net_pct"] > 0 and s1["half1_pct"] > 0 and s1["half2_pct"] > 0
                             and np.isfinite(s1["t"]) and s1["t"] >= T_BAR)
            meets = bool(promising and s1.get("L_fits_margin") and s1["weeks_profitable"] >= 0.75)
            rows.append({"sym": sym, "strategy": code, "tf": tf, **s1, "net_pct_2tick": s2["net_pct"],
                         "promising": promising, "meets_2pct_week": meets})
            pd.DataFrame(t1).to_csv(os.path.join(out_dir, f"p8_trades_{sym}_{code}.csv"), index=False)
            print(f"{sym:10s} {code:10s} {tf:3s} n={s1['trades']:4d} win {s1['win']:.0%} avg {s1['avg_bp']:+6.1f}bp "
                  f"t {s1['t']:+5.2f} net {s1['net_pct']:+6.1f}% (2-tick {s2['net_pct']:+6.1f}%) halves "
                  f"{s1['half1_pct']:+5.1f}/{s1['half2_pct']:+5.1f}% | weeks {s1['weeks']} mean {s1['week_mean_pct']:+.2f}% "
                  f"profitable {s1['weeks_profitable']:.0%} >=2% {s1['weeks_ge2pct']:.0%} worst {s1['worst_week_pct']:+.1f}%"
                  + (f" | 2%/wk needs x{s1['L_star']:.1f}" if "L_star" in s1 else "") +
                  f"{'  PROMISING' if promising else ''}{'  MEETS 2%/WK' if meets else ''}", flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(out_dir, "p8_summary.csv"), index=False)
    json.dump(rows, open(os.path.join(out_dir, "p8_results.json"), "w"), indent=1, default=str)
    print(f"\npromising: {sum(r['promising'] for r in rows)} of {len(rows)}; meets 2%/week: {sum(r['meets_2pct_week'] for r in rows)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
