"""Check HistData minute bars against Dukascopy's hourly bid/ask (python xi_verify.py):
which UTC offset lines the clocks up (HistData says New York standard time all year, UTC-5),
and whether HistData's prices are bids, asks or mids."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import io
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DUKA = ROOT.parent / "xauusd_2026_10"
sys.path.insert(0, str(DUKA))
import xa_data  # noqa: E402  (the hourly study's loaders)


def histdata_year(tag: str) -> pd.DataFrame:
    z = zipfile.ZipFile(ROOT / "data" / "raw" / "histdata" / f"XAUUSD_M1_{tag}.zip")
    name = next(n for n in z.namelist() if n.endswith(".csv"))
    df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None, names=["ts", "o", "h", "l", "c", "v"])
    df.index = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    return df[["o", "h", "l", "c"]]


if __name__ == "__main__":
    bid = xa_data._side_hours("BID")
    ask = xa_data._side_hours("ASK")
    bid, ask = bid[bid["v"] > 0], ask[ask["v"] > 0]
    for tag in ("2019", "2024"):
        m1 = histdata_year(tag)
        for off in (4, 5, 6):
            utc = m1.copy()
            utc.index = (utc.index + pd.Timedelta(hours=off)).tz_localize("UTC")
            hc = utc["c"].resample("1h").last().dropna()
            j = pd.DataFrame({"hd": hc, "duka_bid": bid["c"]}).dropna()
            r = np.log(j).diff().dropna()
            for season, months in (("winter", [1, 2, 12]), ("summer", [6, 7, 8])):
                rs = r[r.index.month.isin(months)]
                print(f"{tag} offset UTC-{off} {season}: hourly return correlation {rs.corr().iloc[0, 1]:.4f} ({len(rs)} hours)")
        utc = m1.copy()
        utc.index = (utc.index + pd.Timedelta(hours=5)).tz_localize("UTC")
        hc = utc["c"].resample("1h").last().dropna()
        j = pd.DataFrame({"hd": hc, "bid": bid["c"], "ask": ask["c"]}).dropna()
        d_bid = (j["hd"] - j["bid"]).median()
        d_ask = (j["hd"] - j["ask"]).median()
        print(f"{tag}: HistData close minus Dukascopy BID close: median {d_bid:+.3f}; minus ASK: {d_ask:+.3f}; "
              f"Dukascopy spread median {(j['ask'] - j['bid']).median():.3f}  ({len(j)} hours)")
