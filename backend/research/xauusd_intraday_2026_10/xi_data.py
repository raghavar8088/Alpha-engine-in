"""One-minute XAUUSD bars for the intraday study (python xi_data.py builds data/minute.npz).

Source: HistData.com XAUUSD M1, 2009-01 .. 2026-10. Checked against Dukascopy (xi_verify.py):
  - HistData's prices ARE Dukascopy's BID (median difference $0.000 on hourly closes), so this is the
    same feed at minute resolution, not an independent source;
  - its timestamps are New York LOCAL time including daylight saving (UTC-5 winter, UTC-4 summer;
    hourly-return correlation 0.9997-1.0000 only on that alignment), not the fixed UTC-5 it documents.
Mid = bid + half the spread Dukascopy quoted in that UTC hour (its hourly ask - bid; the year's median
where an hour is missing).

Clock: sessions roll at 17:00 New York, as in the hourly study. For each minute the arrays keep the
UTC time, the session index, the minute of the session (0 = 18:00 New York, 1379 = 16:59) and the
London clock minute (for the London fixes).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import io
import json
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw" / "histdata"
CACHE = ROOT / "data" / "minute.npz"
DUKA = ROOT.parent / "xauusd_2026_10"


def _read_zip(p: Path) -> pd.DataFrame:
    z = zipfile.ZipFile(p)
    name = next(n for n in z.namelist() if n.endswith(".csv"))
    df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None, names=["ts", "o", "h", "l", "c", "v"])
    idx = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    df.index = idx
    return df[["o", "h", "l", "c"]]


def build() -> dict:
    frames = [_read_zip(p) for p in sorted(RAW.glob("XAUUSD_M1_*.zip"))]
    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="last")]
    ny = m1.index.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    keep = ~ny.isna()
    m1, ny = m1[keep], ny[keep]
    utc = ny.tz_convert("UTC")
    # half-spread from Dukascopy's hourly bid/ask (same feed); the year's median where an hour is missing
    sys.path.insert(0, str(DUKA))
    import xa_data
    bid, ask = xa_data._side_hours("BID"), xa_data._side_hours("ASK")
    sp = (ask["c"] - bid["c"]).where((bid["v"] > 0) & (ask["v"] > 0)).dropna()
    sp = sp[(sp > 0) & (sp < 20)]
    hour = utc.floor("h")
    spread = pd.Series(sp.reindex(hour).values, index=utc)
    yr_med = sp.groupby(sp.index.year).median()
    fill = pd.Series(utc.year, index=utc).map(yr_med).fillna(float(sp.median()))
    spread = spread.fillna(fill)
    half = spread.values / 2
    ny_min = (ny.hour * 60 + ny.minute).values
    sess_date = (ny + pd.Timedelta(hours=7)).date
    sess_dates, sess = np.unique(np.array(sess_date, dtype="datetime64[D]"), return_inverse=True)
    sm = (ny_min - 18 * 60) % 1440
    lon = utc.tz_convert("Europe/London")
    lon_min = (lon.hour * 60 + lon.minute).values
    o, h, l, c = (m1[k].values + half for k in ("o", "h", "l", "c"))
    # sessions: drop stubs (< 120 minutes: holiday fragments)
    counts = np.bincount(sess)
    good = counts[sess] >= 120
    arrays = {"t": utc.values.astype("datetime64[s]").astype(np.int64)[good], "sess": sess[good], "sm": sm[good].astype(np.int16),
              "lon_min": lon_min[good].astype(np.int16), "o": o[good], "h": h[good], "l": l[good], "c": c[good],
              "spread": spread.values[good].astype(np.float32)}
    # re-index sessions after dropping stubs
    used, new = np.unique(arrays["sess"], return_inverse=True)
    arrays["sess"] = new.astype(np.int32)
    arrays["sess_date"] = sess_dates[used]
    starts = np.searchsorted(arrays["sess"], np.arange(len(used)), side="left")
    ends = np.searchsorted(arrays["sess"], np.arange(len(used)), side="right")
    arrays["s_start"], arrays["s_end"] = starts, ends
    # daily (session) OHLC of the mids
    arrays["d_o"] = arrays["o"][starts]
    arrays["d_c"] = arrays["c"][ends - 1]
    arrays["d_h"] = np.maximum.reduceat(arrays["h"], starts)
    arrays["d_l"] = np.minimum.reduceat(arrays["l"], starts)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(CACHE, **arrays)
    info = {"minutes": int(len(arrays["t"])), "sessions": int(len(used)), "first": str(utc[0]), "last": str(utc[-1]),
            "dropped_dst_ambiguous": int((~keep).sum()), "stub_minutes_dropped": int((~good).sum()),
            "median_spread_by_year": {int(k): round(float(v), 3) for k, v in yr_med.items()}}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "data_minute.json").write_text(json.dumps(info, indent=1))
    return info


def load() -> dict:
    if not CACHE.exists():
        build()
    z = np.load(CACHE)
    return {k: z[k] for k in z.files}


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
