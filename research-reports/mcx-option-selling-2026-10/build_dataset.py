"""Cached MCX bhavcopy JSON -> two clean tables (pickled pandas), plus a data-quality report.

    python build_dataset.py <data_dir> <work_dir>

opt.pkl : sym, expiry, date, strike, cp, open, high, low, close, prev, vol, value, oi, traded
fut.pkl : sym, expiry, date, open, high, low, close, prev, vol, oi, traded
`traded` = the contract printed a trade that day (volume > 0 and a positive high). A close on a
day with no trade is the exchange's carried/theoretical price and is never used as a fill.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import sys

import pandas as pd

COLS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "PreviousClose": "prev",
        "Volume": "vol", "Value": "value", "OpenInterest": "oi", "StrikePrice": "strike",
        "OptionType": "cp"}


def load(data_dir: str, inst: str) -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(data_dir, inst, "*", "*.json.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows = json.load(fh)
        if rows:
            frames.append(pd.DataFrame(rows))
    df = pd.concat(frames, ignore_index=True)
    df["sym"] = df["Symbol"].str.strip()
    df["date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    df["expiry"] = pd.to_datetime(df["ExpiryDate"].str.strip(), format="%d%b%Y")
    df = df.rename(columns=COLS)
    keep = ["sym", "expiry", "date", "open", "high", "low", "close", "prev", "vol", "value", "oi"]
    if inst == "OPTFUT":
        keep[3:3] = ["strike", "cp"]
        df["cp"] = df["cp"].str.strip()
    df = df[keep].copy()
    for c in ("open", "high", "low", "close", "prev", "value"):
        df[c] = df[c].astype(float)
    for c in ("vol", "oi"):
        df[c] = df[c].fillna(0).astype("int64")
    key = ["sym", "expiry", "date"] + (["strike", "cp"] if inst == "OPTFUT" else [])
    before = len(df)
    df = df.drop_duplicates(subset=key, keep="last")
    df["traded"] = (df["vol"] > 0) & (df["high"] > 0)
    df = df.sort_values(key).reset_index(drop=True)
    return df, before - len(df)


def main(data_dir: str, work_dir: str) -> None:
    os.makedirs(work_dir, exist_ok=True)
    opt, d1 = load(data_dir, "OPTFUT")
    fut, d2 = load(data_dir, "FUTCOM")
    print(f"options: {len(opt):,} rows ({d1} duplicate rows dropped); futures: {len(fut):,} rows ({d2} dropped)")
    bad = opt[(opt.traded) & ((opt.low > opt.high) | (opt.close > opt.high + 1e-9) | (opt.close < opt.low - 1e-9) | (opt.close <= 0))]
    print(f"traded option rows with inconsistent OHLC: {len(bad)}")
    opt = opt.drop(bad.index)
    badf = fut[(fut.traded) & ((fut.low > fut.high) | (fut.close <= 0))]
    print(f"traded futures rows with inconsistent OHLC: {len(badf)}")
    fut = fut.drop(badf.index)
    for sym, g in opt.groupby("sym"):
        t = g[g.traded]
        print(f"  {sym:<11} expiries {g.expiry.nunique():>3}  days {g.date.min().date()} -> {g.date.max().date()}  "
              f"rows {len(g):>9,}  traded rows {len(t):>8,}  lots {int(t.vol.sum()):>13,}")
    for sym, g in fut.groupby("sym"):
        print(f"  FUT {sym:<11} expiries {g.expiry.nunique():>3}  days {g.date.min().date()} -> {g.date.max().date()}  rows {len(g):,}")
    opt.to_pickle(os.path.join(work_dir, "opt.pkl"))
    fut.to_pickle(os.path.join(work_dir, "fut.pkl"))
    print("saved", work_dir)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
