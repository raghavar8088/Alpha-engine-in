"""Data checks, run BEFORE any strategy (results/data_checks.json):

  clock     the minute of the regular session with the largest average absolute one-minute move, summer
            vs winter. If HistData's clock is New York time with daylight saving (as verified for gold), the
            opening burst sits at the session's first minutes in both seasons.
  rolls     the price change across each weekday daily break (no trading for 45 minutes to 20 hours).
            Index and crude CFDs that follow a futures contract jump there when the contract rolls; gold
            spot does not. The largest jumps and their dates show whether a roll rule is needed.
  coverage  minutes per kept session, sessions dropped (< 80% of their minutes), first and last dates.

    python ch_checks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json

import numpy as np
import pandas as pd

import ch_data

ROOT = Path(__file__).resolve().parent


def clock(D: dict) -> dict:
    ret = np.abs(np.diff(np.log(D["c"])))
    same = D["sess"][1:] == D["sess"][:-1]
    sm = D["sm"][1:][same]
    r = ret[same]
    month = pd.to_datetime(D["t"][1:][same], unit="s").month
    out = {}
    for season, months in (("summer", (6, 7, 8)), ("winter", (12, 1, 2))):
        m = np.isin(month, months)
        prof = pd.Series(r[m]).groupby(sm[m]).mean()
        top = prof.sort_values(ascending=False).head(3)
        out[season] = {"busiest_session_minutes": [int(x) for x in top.index], "first5_vs_median": float(prof.iloc[:5].mean() / prof.median())}
    return out


def rolls(D: dict) -> dict:
    j = pd.Series(D["reopen_jump"], index=pd.to_datetime(D["sess_date"]))
    j = j.dropna()
    a = j.abs()
    q = a.quantile([0.5, 0.9, 0.99]).to_dict()
    top = a.sort_values(ascending=False).head(25)
    return {"n": int(len(a)), "median": float(q[0.5]), "p90": float(q[0.9]), "p99": float(q[0.99]),
            "largest": [(str(k.date()), round(float(j[k]) * 100, 3)) for k in top.index],
            "count_over": {f"{x}%": int((a > x / 100).sum()) for x in (0.1, 0.2, 0.3, 0.5, 1.0)}}


def coverage(sym: str, D: dict) -> dict:
    n = D["s_end"] - D["s_start"]
    m = ch_data.MARKETS[sym]
    return {"sessions": int(len(n)), "expected_minutes": m.length, "median_minutes": float(np.median(n)), "min_minutes": int(n.min()),
            "dropped_sessions": int(D["dropped_sessions"]), "first": str(D["sess_date"][0]), "last": str(D["sess_date"][-1]),
            "sessions_per_year": {int(y): int(c) for y, c in pd.Series(pd.to_datetime(D["sess_date"]).year).value_counts().sort_index().items()}}


if __name__ == "__main__":
    out = {}
    for sym in ch_data.MARKETS:
        D = ch_data.load(sym)
        out[sym] = {"coverage": coverage(sym, D), "clock": clock(D), "rolls": rolls(D)}
        print(sym, json.dumps(out[sym], indent=1)[:2500], flush=True)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "data_checks.json").write_text(json.dumps(out, indent=1))
