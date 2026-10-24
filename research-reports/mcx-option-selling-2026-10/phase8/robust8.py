"""Phase 8 robustness (descriptive; after the one-time run; nothing here selects or re-tunes).

The one A8 pass was LONG-US on crude: long at the 18:30 NYMEX open, out at the MCX close, over
Aug-Oct 2026, a window in which crude rose 37%. Two checks on whether that is an intraday edge or
just the rally:
  1. the same idea on the EARLIER bars (May-Aug 2026, when crude fell 24%), from the 1-hour store:
     long 18:00 -> close (the hourly bar that holds the 18:30 open) and long 09:00 -> close;
  2. "long the MCX session" (09:00 open -> 23:30 close) on MCX's own daily OPEN and CLOSE for every
     day since 2005 (crude) / 2006 (gas), front contract rolled 3 trading days before expiry, with the
     same costs: is there a persistent session drift, year by year?

    python robust8.py <bars.csv.gz> <fut.pkl from phase 6> <out_dir>
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


def summary(r):
    r = np.asarray(r, dtype=float)
    n = len(r)
    sd = r.std(ddof=1) if n > 1 else np.nan
    return {"n": n, "net_pct": round(float(r.sum() * 100), 1), "mean_bp": round(float(r.mean() * 1e4), 1) if n else 0.0,
            "t": round(float(r.mean() / (sd / math.sqrt(n))), 2) if n > 1 and sd > 0 else None,
            "win": round(float((r > 0).mean()), 2) if n else 0.0}


def earlier_window(bars_path):
    b = E8.load(bars_path)
    out = {}
    for sym in ("CRUDEOIL", "NATURALGAS"):
        days = [d for d in E8.sessions(b, sym, "1h") if d.day < pd.Timestamp("2026-08-06")]
        tick = E8.TICK[sym]
        for label, hm in (("long 18:00 -> close", "18:00"), ("long 09:00 -> close", "09:00")):
            r = []
            for d in days:
                a = d.idx(hm)
                if a is None:
                    continue
                e, x = d.o[a] + tick, d.c[-1] - tick
                r.append((x - e) / e - E8.COST)
            out[f"{sym} {label} ({days[0].day.date()}..{days[-1].day.date()})"] = summary(r)
        out[f"{sym} price {days[0].day.date()} -> {days[-1].day.date()}"] = f"{days[0].o[0]:.1f} -> {days[-1].c[-1]:.1f}"
    return out


def daily_session_drift(fut_path):
    fut = pd.read_pickle(fut_path)
    out = {}
    for sym in ("CRUDEOIL", "NATURALGAS"):
        f = fut[fut.sym == sym]
        days = sorted(f.date.unique())
        di = {d: i for i, d in enumerate(days)}
        darr = np.array(days, dtype="datetime64[ns]")
        exps = sorted(f.expiry.unique())
        roll = {e: int(np.searchsorted(darr, np.datetime64(e), side="right")) - 1 - 3 for e in exps}
        px = {(r.expiry, r.date): (float(r.open), float(r.close), bool(r.traded)) for r in f.itertuples()}
        rows = []
        k = 0
        for i, d in enumerate(days):
            while k < len(exps) and roll[exps[k]] < i:        # the contract held INTO day i (rolled after day roll[e])
                k += 1
            if k >= len(exps):
                break
            e = exps[k]
            if (e, d) not in px:
                continue
            o, c, tr = px[(e, d)]
            if not tr or o <= 0 or c <= 0:
                continue
            tick = E8.TICK[sym]
            gross = c / o - 1
            net_long = (c - tick - (o + tick)) / (o + tick) - E8.COST
            net_short = -((c + tick) - (o - tick)) / (o - tick) - E8.COST
            rows.append({"date": d, "expiry": e, "open": o, "close": c, "gross": gross, "long": net_long, "short": net_short})
        df = pd.DataFrame(rows)
        yr = df.groupby(df.date.dt.year)
        out[sym] = {"all_years_long": summary(df.long), "all_years_short": summary(df.short),
                    "all_years_gross_mean_bp": round(float(df.gross.mean() * 1e4), 2),
                    "by_year": {int(y): {"long": summary(g.long), "gross_mean_bp": round(float(g.gross.mean() * 1e4), 1)} for y, g in yr},
                    "years_long_positive": int(sum(g.long.sum() > 0 for _, g in yr)), "years": int(len(yr))}
        check = df[(df.date >= "2026-08-06") & (df.date <= "2026-10-23")]
        out[sym]["Aug-Oct 2026 check (should match the 5m LONG-DAY)"] = summary(check.long)
    return out


def clean_days(bars_path, fut_path):
    """Days whose recorded bars agree with MCX's official daily open/high/low for the SAME contract:
    each of the three ratios within 0.3% of 1, or all three shifted alike (spread < 0.3%), which
    means a whole day of one other contract (its intraday returns are still valid). Everything else
    (no official row, or a splice inside the day) is flagged."""
    import run_phase8 as R8
    b = E8.load(bars_path)
    fut = pd.read_pickle(fut_path).set_index(["sym", "expiry", "date"]).sort_index()
    keep, flagged = {}, {}
    for sym in R8.SYMS:
        for tf in ("5m", "15m", "1h"):
            ok, bad = [], 0
            for d in E8.sessions(b, sym, tf):
                key = (sym, d.expiry, d.day)
                if key not in fut.index:
                    bad += 1
                    continue
                r = fut.loc[key]
                ratios = np.array([d.o[0] / r.open, d.h.max() / r.high, d.l.min() / r.low])
                if (np.abs(ratios - 1) < 0.003).all() or (ratios.max() - ratios.min()) < 0.003:
                    ok.append(d)
                else:
                    bad += 1
            keep[(sym, tf)] = ok
            flagged[f"{sym} {tf}"] = {"kept": len(ok), "flagged": bad}
    return keep, flagged


def rerun_clean(bars_path, fut_path):
    import run_phase8 as R8
    keep, flagged = clean_days(bars_path, fut_path)
    rows = []
    for sym in R8.SYMS:
        for code, tf, fn in R8.STRATS:
            days = keep[(sym, tf)]
            if len(days) < 10:
                continue
            s1 = R8.stats(fn(days, E8.TICK[sym], sym), days, sym)
            s2 = R8.stats(fn(days, 2 * E8.TICK[sym], sym), days, sym)
            rows.append({"sym": sym, "strategy": code, "days": s1["days"], "trades": s1["trades"], "net_pct": round(s1["net_pct"], 1),
                         "net_pct_2tick": round(s2["net_pct"], 1), "t": None if not np.isfinite(s1["t"]) else round(s1["t"], 2),
                         "halves": (round(s1["half1_pct"], 1), round(s1["half2_pct"], 1)),
                         "week_mean_pct": round(s1["week_mean_pct"], 2), "weeks_profitable": round(s1["weeks_profitable"], 2)})
    return flagged, rows


def main(bars_path, fut_path, out_dir):
    res = {"earlier_window_1h": earlier_window(bars_path), "daily_session_drift": daily_session_drift(fut_path)}
    res["clean_days"], res["rerun_on_clean_days"] = rerun_clean(bars_path, fut_path)
    print("days kept / flagged against MCX's official open-high-low:", res["clean_days"])
    for r in res["rerun_on_clean_days"]:
        print("   clean:", r)
    for k, v in res["earlier_window_1h"].items():
        print(f"{k}: {v}")
    for sym, v in res["daily_session_drift"].items():
        print(f"\n{sym}: every session since the market opened, long 09:00 open -> 23:30 close: {v['all_years_long']}; "
              f"short: {v['all_years_short']}; gross mean {v['all_years_gross_mean_bp']} bp; "
              f"years positive (long) {v['years_long_positive']}/{v['years']}")
        print("   by year (long, net):", {y: (x["long"]["net_pct"], x["long"]["t"]) for y, x in v["by_year"].items()})
        print("   Aug-Oct 2026 on daily open/close:", v["Aug-Oct 2026 check (should match the 5m LONG-DAY)"])
    json.dump(res, open(os.path.join(out_dir, "p8_robust.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
