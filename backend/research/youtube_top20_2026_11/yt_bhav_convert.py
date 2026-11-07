"""Convert the NSE daily bhavcopy panel (D:/NSE-Intraday-Research/data/clean/bhav_panel.parquet, every EQ stock
traded 2011-06 to 2026-11, delisted names included) into data/nse_daily.npz for this study's Python.

Run with the NSE research environment (it has pyarrow):
    D:/NSE-Intraday-Research/env/Scripts/python.exe yt_bhav_convert.py

Prices are back-adjusted for splits and bonuses: NSE's PREVCLOSE is not adjusted on ex-dates, so an
overnight ratio open / previous close below 0.6 or above 1.6 (far beyond any circuit limit) is treated as a
corporate action, and all earlier prices of that symbol are multiplied by that ratio. This sets the ex-date's
overnight return to zero (approximation; the corporate-actions file is not used).
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = Path("D:/NSE-Intraday-Research/data/clean/bhav_panel.parquet")

p = pd.read_parquet(SRC, columns=["symbol", "series", "open", "high", "low", "close", "value", "date"])
p = p[p["series"] == "EQ"].drop(columns="series")
p = p[(p["close"] > 0) & (p["high"] >= p["low"])].sort_values(["symbol", "date"]).reset_index(drop=True)
syms = p["symbol"].astype("category")
codes = syms.cat.codes.to_numpy().astype(np.int32)
names = np.array(syms.cat.categories.tolist())
o, h, l, c = (p[k].to_numpy(float) for k in ("open", "high", "low", "close"))
v = p["value"].to_numpy(float)
dates = p["date"].to_numpy().astype("datetime64[D]")
adj = np.ones(len(p))
n_events = 0
starts = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1]])
ends = np.r_[starts[1:], len(codes)]
for a, z in zip(starts, ends):
    ratio = o[a + 1:z] / c[a:z - 1]
    ev = np.flatnonzero((ratio < 0.6) | (ratio > 1.6))
    f = np.ones(z - a)
    for e in ev:
        f[: e + 1] *= ratio[e]          # rows a .. a+e are before the ex-date (row a+e+1)
        n_events += 1
    adj[a:z] = f
np.savez_compressed(HERE / "data" / "nse_daily.npz", code=codes, names=names, date=dates,
                    o=o * adj, h=h * adj, l=l * adj, c=c * adj, value=v)
print("rows", len(p), "symbols", len(names), "adjustments", n_events, dates.min(), dates.max())
