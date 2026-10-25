"""Phase 0, step 2: the clean 5-minute panel the strategies will read.

    python n50_adjust.py <work dir with panel_5m.pkl> <out dir>

1. Only the regular-session grid: candles stamped 09:15 .. 15:25.
2. Three corporate-action errors in Angel's history, each proven by turnover (price x volume) staying
   continuous only after the fix (see DATA_REPORT.md):
     TATASTEEL  volume x10 before 2022-07-26; price /10 and volume x10 on 2022-07-26 and 2022-07-27
     NESTLEIND  price /10 and volume x10 before 2021-12-31
     BAJAJFINSV volume x10 before 2022-09-13
3. TMPV is the same Angel token as TATAMOTORS (renamed after the Oct 2025 demerger): one series, kept
   as TATAMOTORS.
4. Sessions dropped: Muhurat trading (5), the two Saturday disaster-recovery drill sessions, and any
   stock-session with fewer than 70 candles (from 2026-08-03 NSE's closing auction leaves 72-73
   candles - those are full sessions and are kept).
"""
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

SPECIAL = {"2021-11-04", "2022-10-24", "2023-11-12", "2024-11-01", "2025-10-21",   # Muhurat
           "2024-03-02", "2024-05-18"}                                              # DR drills (Saturday)
FIXES = [("TATASTEEL", None, "2022-07-25", 1.0, 10.0), ("TATASTEEL", "2022-07-26", "2022-07-27", 0.1, 10.0),
         ("NESTLEIND", None, "2021-12-30", 0.1, 10.0), ("BAJAJFINSV", None, "2022-09-12", 1.0, 10.0)]


def main(work, out):
    os.makedirs(out, exist_ok=True)
    p = pd.read_pickle(os.path.join(work, "panel_5m.pkl"))
    p["day"] = p.ts.dt.normalize()
    hm = p.ts.dt.strftime("%H:%M")
    p = p[(hm >= "09:15") & (hm <= "15:25")].copy()
    a, b = p[p.symbol == "TATAMOTORS"].set_index("ts").c, p[p.symbol == "TMPV"].set_index("ts").c
    identical = bool(len(a) == len(b) and np.allclose(a.sort_index().values, b.sort_index().values))
    p = p[p.symbol != "TMPV"]
    log = {"tmpv_identical_to_tatamotors": identical}
    for sym, frm, to, px, vol in FIXES:
        m = (p.symbol == sym) & (p.day <= pd.Timestamp(to))
        if frm:
            m &= p.day >= pd.Timestamp(frm)
        for col in ("o", "h", "l", "c"):
            p.loc[m, col] = p.loc[m, col] * px
        p.loc[m, "v"] = p.loc[m, "v"] * vol
        log[f"{sym} {frm or 'start'}..{to}"] = {"rows": int(m.sum()), "price_x": px, "volume_x": vol}
    p["turnover"] = p.c * p.v
    n = p.groupby(["symbol", "day"]).size().rename("candles")
    p = p.join(n, on=["symbol", "day"])
    keep = (~p.day.dt.strftime("%Y-%m-%d").isin(SPECIAL)) & (p.candles >= 70)
    log["dropped_special_session_rows"] = int((p.day.dt.strftime("%Y-%m-%d").isin(SPECIAL)).sum())
    log["dropped_short_session_rows"] = int(((p.candles < 70) & ~p.day.dt.strftime("%Y-%m-%d").isin(SPECIAL)).sum())
    p = p[keep].drop(columns="candles").sort_values(["symbol", "ts"]).reset_index(drop=True)
    # re-check: overnight jumps and turnover steps after the fixes
    g = p.groupby(["symbol", "day"])
    d = pd.DataFrame({"o": g.o.first(), "c": g.c.last(), "t": g.turnover.sum()}).reset_index()
    rows = []
    for s, x in d.groupby("symbol"):
        x = x.set_index("day")
        gap = x.o / x.c.shift() - 1
        tb = x.t.rolling(20).median().shift(1)
        ta = x.t[::-1].rolling(20).median()[::-1]
        rows.append({"symbol": s, "max_abs_gap": round(float(gap.abs().max()), 4),
                     "max_turnover_step": round(float((ta / tb).max()), 2), "min_turnover_step": round(float((ta / tb).min()), 2)})
    chk = pd.DataFrame(rows)
    log["after_fix_worst_gaps"] = chk.nlargest(8, "max_abs_gap")[["symbol", "max_abs_gap"]].to_dict("records")
    log["after_fix_turnover_steps_over_3_5x"] = chk[(chk.max_turnover_step > 3.5) | (chk.min_turnover_step < 1 / 3.5)][
        ["symbol", "max_turnover_step", "min_turnover_step"]].to_dict("records")
    path = os.path.join(out, "n50_clean.pkl")
    p.to_pickle(path)
    log["rows"] = int(len(p))
    log["symbols"] = sorted(p.symbol.unique())
    log["sessions"] = int(p.day.nunique())
    log["sha256_clean_pickle"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    json.dump(log, open(os.path.join(out, "adjust_log.json"), "w"), indent=1, default=str)
    for k, v in log.items():
        if k != "symbols":
            print(f"{k}: {v}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
