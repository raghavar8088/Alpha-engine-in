"""Phase 0 data checks (PLAN.md) on the 5-minute files pulled by n50_fetch.py. No strategy is run here.

    python n50_checks.py <n50data dir> <out dir>

Checks, per stock and index:
  - sessions present vs NIFTY's own trading days; candles per session (75 = 09:15..15:25)
  - duplicate stamps, off-grid stamps, candles outside 09:15-15:25, special sessions (Muhurat, Saturday)
  - bad prices (h < l, close outside [l, h], <= 0), zero-volume candles, extreme 5-minute moves
  - overnight jumps beyond 15% or 6x the stock's own typical move -> listed for corporate-action review
  - volume steps across known split / bonus dates (is VOLUME adjusted as well as price?)
  - each stock's 5-minute returns vs NIFTY's (correlation): catches misaligned stamps or wrong tokens
Writes checks.json, sessions.csv (one row per stock-session) and bars.parquet-like gzip CSV of the
clean panel used by later phases.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

# Splits, bonuses and demergers among NIFTY 50 stocks in the window (ex-dates). Used only to check
# whether Angel's prices AND volumes are adjusted across them - not to adjust anything.
KNOWN_EVENTS = {
    "TATASTEEL": "2022-07-28", "BAJAJFINSV": "2022-09-13", "NESTLEIND": "2024-01-05",
    "RELIANCE": "2024-10-28", "WIPRO": "2024-12-03", "BAJFINANCE": "2025-06-16",
    "HDFCBANK": "2025-08-26", "TATAMOTORS": "2025-10-14",
}


def load_symbol(d):
    parts = []
    for f in sorted(glob.glob(os.path.join(d, "*.csv.gz"))):
        x = pd.read_csv(f, header=None, names=["ts", "o", "h", "l", "c", "v"])
        parts.append(x)
    if not parts:
        return None
    x = pd.concat(parts, ignore_index=True)
    x["ts"] = pd.to_datetime(x.ts.str.slice(0, 19))           # stamps are IST (+05:30)
    return x


def main(root, out):
    os.makedirs(out, exist_ok=True)
    syms = sorted(os.path.basename(p) for p in glob.glob(os.path.join(root, "5m", "*")))
    nifty = load_symbol(os.path.join(root, "5m", "NIFTY"))
    days = sorted(nifty.ts.dt.normalize().unique())
    nifty_days = set(days)
    nr = nifty.set_index("ts").c.pct_change()
    report, sess_rows, panel = {}, [], []
    for s in syms:
        x = load_symbol(os.path.join(root, "5m", s))
        if x is None:
            report[s] = {"bars": 0}
            continue
        dup = int(x.duplicated("ts").sum())
        x = x.drop_duplicates("ts").sort_values("ts")
        t = x.ts.dt.strftime("%H:%M")
        off_grid = int((x.ts.dt.minute % 5 != 0).sum())
        outside = int(((t < "09:15") | (t > "15:25")).sum())
        x["day"] = x.ts.dt.normalize()
        g = x.groupby("day")
        per = g.size()
        special = [str(d.date()) for d in per.index if d.weekday() >= 5 or d not in nifty_days]
        bad_px = int(((x.h < x.l) | (x.c > x.h + 1e-9) | (x.c < x.l - 1e-9) | (x[["o", "h", "l", "c"]] <= 0).any(axis=1)).sum())
        zero_v = int((x.v <= 0).sum())
        r5 = x.set_index("ts").c.pct_change()
        same_day = x.set_index("ts").day.eq(x.set_index("ts").day.shift())
        r5 = r5[same_day]
        extreme = int((r5.abs() > 0.10).sum())
        # overnight jumps
        first = g.o.first()
        last = g.c.last()
        on = (first / last.shift() - 1).dropna()
        typ = on.abs().median() or 0.001
        jumps = on[on.abs() > max(0.10, 8 * typ)]
        # volume step across a known event: median 15-day volume after / before
        vol_step = None
        if s in KNOWN_EVENTS:
            ev = pd.Timestamp(KNOWN_EVENTS[s])
            dv = g.v.sum()
            before, after = dv[(dv.index < ev)].tail(15), dv[(dv.index >= ev)].head(15)
            px_b, px_a = last[last.index < ev].tail(1), first[first.index >= ev].head(1)
            if len(before) and len(after):
                vol_step = {"volume_after_over_before": round(float(after.median() / before.median()), 2),
                            "price_jump_at_event": round(float(px_a.iloc[0] / px_b.iloc[0] - 1), 4) if len(px_a) and len(px_b) else None}
        # alignment with NIFTY
        j = pd.concat([r5.rename("s"), nr.rename("n")], axis=1, join="inner").dropna()
        corr = float(j.s.corr(j.n)) if len(j) > 500 else None
        full = per[per.index.isin(nifty_days)]
        report[s] = {"bars": int(len(x)), "first_day": str(per.index.min().date()), "last_day": str(per.index.max().date()),
                     "sessions": int(len(per)), "nifty_sessions_in_range": int(sum(1 for d in days if per.index.min() <= d <= per.index.max())),
                     "full_sessions_75": int((full == 75).sum()), "short_sessions": int((full < 70).sum()),
                     "duplicates": dup, "off_grid": off_grid, "outside_session": outside, "special_sessions": special[:20],
                     "bad_prices": bad_px, "zero_volume_candles": zero_v, "zero_volume_share": round(zero_v / max(len(x), 1), 4),
                     "extreme_5m_moves_gt10pct": extreme, "overnight_jumps": {str(k.date()): round(float(v), 4) for k, v in jumps.items()},
                     "known_event_check": vol_step, "corr_with_nifty_5m": round(corr, 3) if corr is not None else None}
        for d, n in per.items():
            sess_rows.append({"symbol": s, "day": d.date(), "candles": int(n), "nifty_day": d in nifty_days})
        x["symbol"] = s
        panel.append(x[["symbol", "ts", "o", "h", "l", "c", "v"]])
        print(f"{s:12s} {report[s]['first_day']}..{report[s]['last_day']} sessions {report[s]['sessions']:4d}/"
              f"{report[s]['nifty_sessions_in_range']:4d} full {report[s]['full_sessions_75']:4d} short {report[s]['short_sessions']:3d} "
              f"dup {dup} zeroV {report[s]['zero_volume_share']:.2%} bad {bad_px} ext {extreme} jumps {len(jumps)} "
              f"corr {report[s]['corr_with_nifty_5m']}{' EVENT ' + str(vol_step) if vol_step else ''}", flush=True)
    json.dump(report, open(os.path.join(out, "checks.json"), "w"), indent=1, default=str)
    pd.DataFrame(sess_rows).to_csv(os.path.join(out, "sessions.csv"), index=False)
    pd.concat(panel, ignore_index=True).to_pickle(os.path.join(out, "panel_5m.pkl"))
    print(f"\n{len(syms)} series; NIFTY trading days {len(days)} ({days[0].date()}..{days[-1].date()})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
