"""Cross-check the 5-minute bars against a second vendor: Yahoo Finance's NIFTYBEES.NS 5-minute chart.

    python -I backend/research/niftybees_orb_2026_10/orb_crosscheck.py data/yahoo_5m_60d.json

Yahoo serves 5-minute history for the last 60 days only, so this covers about 2026-07-28 .. 2026-10-23.
The file is one download of
https://query1.finance.yahoo.com/v8/finance/chart/NIFTYBEES.NS?interval=5m&range=60d (2026-10-24).
It checks two things: that the bars built from Angel's minutes are the market's bars, and whether the
stray 09:15 prints (orb_data.py rule 4) are in another vendor's record too, i.e. are exchange prints.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))


def main(path: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with open(path) as f:
        y = json.load(f)["chart"]["result"][0]
    q = y["indicators"]["quote"][0]
    yb = {}
    for i, ts in enumerate(y["timestamp"]):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in vals[:4]):
            continue
        t = datetime.fromtimestamp(ts, IST)
        yb[(t.strftime("%Y-%m-%d"), t.strftime("%H:%M"))] = [round(v, 2) for v in vals[:4]] + [vals[4] or 0]
    ours = {}
    with gzip.open(HERE / "data" / "NIFTYBEES_5m.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            ours[(r["date"], r["time"])] = [float(r[k]) for k in ("open", "high", "low", "close")] + [int(r["volume"])]
    keys = sorted(set(yb) & set(ours))
    days = sorted({k[0] for k in keys})
    out = {"yahoo_bars": len(yb), "common_bars": len(keys), "days": [days[0], days[-1]], "sessions": len(days)}
    for label, sel in (("09:30-15:10 (the bars the strategy trades)", lambda k: "09:30" <= k[1] <= "15:10"),
                       ("09:15 bar", lambda k: k[1] == "09:15"), ("09:20 and 09:25 bars", lambda k: k[1] in ("09:20", "09:25"))):
        ks = [k for k in keys if sel(k)]
        a = np.array([ours[k][:4] for k in ks])
        b = np.array([yb[k][:4] for k in ks])
        d = np.abs(a - b)
        va = np.array([ours[k][4] for k in ks], float)
        vb = np.array([yb[k][4] for k in ks], float)
        out[label] = {"bars": len(ks),
                      **{f"{f}_exact_pct": round(float((d[:, j] < 0.005).mean() * 100), 1) for j, f in enumerate("ohlc")},
                      **{f"{f}_within_1_tick_pct": round(float((d[:, j] < 0.015).mean() * 100), 1) for j, f in enumerate("ohlc")},
                      "max_abs_diff_rs": round(float(d.max()), 2),
                      # which vendor holds the extremes: Angel's minutes keep trades Yahoo's bars leave out
                      "angel_high_above_yahoo_pct": round(float((a[:, 1] - b[:, 1] > 0.005).mean() * 100), 1),
                      "angel_high_below_yahoo_pct": round(float((a[:, 1] - b[:, 1] < -0.005).mean() * 100), 1),
                      "angel_low_below_yahoo_pct": round(float((b[:, 2] - a[:, 2] > 0.005).mean() * 100), 1),
                      "angel_low_above_yahoo_pct": round(float((b[:, 2] - a[:, 2] < -0.005).mean() * 100), 1),
                      "volume_ratio_yahoo_to_angel_median": round(float(np.median(vb / np.maximum(va, 1))), 3)}
    # the opening range: first three bars, ours (raw) vs Yahoo
    opening = {r["date"]: r for r in json.load(open(HERE / "data" / "opening_ranges.json"))}
    rows = []
    for d in days:
        if not all((d, t) in yb for t in ("09:15", "09:20", "09:25")) or d not in opening:
            continue
        yh = max(yb[(d, t)][1] for t in ("09:15", "09:20", "09:25"))
        yl = min(yb[(d, t)][2] for t in ("09:15", "09:20", "09:25"))
        o = opening[d]
        rows.append({"date": d, "yahoo": [yl, yh], "angel_raw": [o["raw_orl"], o["raw_orh"]], "clean": [o["orl"], o["orh"]],
                     "yahoo_0915_open": yb[(d, "09:15")][0], "angel_0915_open": ours[(d, "09:15")][0]})
    same_raw = sum(1 for r in rows if abs(r["yahoo"][0] - r["angel_raw"][0]) < 0.005 and abs(r["yahoo"][1] - r["angel_raw"][1]) < 0.005)
    same_clean = sum(1 for r in rows if abs(r["yahoo"][0] - r["clean"][0]) < 0.005 and abs(r["yahoo"][1] - r["clean"][1]) < 0.005)
    same_open = sum(1 for r in rows if abs(r["yahoo_0915_open"] - r["angel_0915_open"]) < 0.005)
    w = lambda lo, hi: (hi / lo - 1) * 1e4  # noqa: E731
    out["opening_range"] = {
        "sessions": len(rows), "yahoo_equals_angel_raw": same_raw, "yahoo_equals_clean": same_clean,
        "same_0915_open": same_open,
        "median_width_bp": {"yahoo": round(float(np.median([w(*r["yahoo"]) for r in rows])), 1),
                            "angel_raw": round(float(np.median([w(*r["angel_raw"]) for r in rows])), 1),
                            "clean": round(float(np.median([w(*r["clean"]) for r in rows])), 1)},
        "examples": rows[-5:]}
    with open(HERE / "results" / "crosscheck_yahoo.json", "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "data" / "yahoo_5m_60d.json"))
