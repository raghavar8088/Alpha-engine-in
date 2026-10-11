"""Gold strategy lab, stage 0: the daily histories every round is tested on.

    python backend/research/gold_lab_2026_10/gl_fetch.py

Yahoo daily OHLC, as far back as each series goes, into data/<name>_1d.csv.gz:

  gold        GLD (ETF, 2004-11 -) — the primary series: a spot-gold proxy with no futures-roll
              jumps; GC=F (COMEX front month, 2000 -) as the longer, rougher cross-check; IAU.
  metals      SI=F / SLV (silver), PL=F (platinum), PA=F (palladium), HG=F (copper) — a rule
              whose mechanism is general (trend, reversal) must also work outside gold.
  drivers     DX-Y.NYB (dollar index), TIP (TIPS ETF: real yields, inverted), IEF / TLT
              (treasuries), ^TNX (10y yield), ^IRX (13-week bill: the cash rate), ^GVZ (gold
              implied vol, 2008 -), ^VIX, ^GSPC, CL=F (oil), INR=X.

Nothing here is a signal; the data is only collected.
"""

from __future__ import annotations

import csv
import gzip
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)

SERIES = {
    "GLD": "GLD", "IAU": "IAU", "GC": "GC=F",
    "SI": "SI=F", "SLV": "SLV", "PL": "PL=F", "PA": "PA=F", "HG": "HG=F",
    "DXY": "DX-Y.NYB", "TIP": "TIP", "IEF": "IEF", "TLT": "TLT", "TNX": "^TNX", "IRX": "^IRX",
    "GVZ": "^GVZ", "VIX": "^VIX", "SPX": "^GSPC", "CL": "CL=F", "INR": "INR=X",
    "GDX": "GDX", "GDXJ": "GDXJ", "UUP": "UUP",
}


def main(names: list[str]) -> None:
    import yfinance as yf

    for name in names:
        ticker = SERIES[name]
        for attempt in range(4):
            try:
                df = yf.download(ticker, period="max", interval="1d", progress=False, auto_adjust=False)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  retry {attempt + 1} {ticker}: {exc}")
                time.sleep(3 * (attempt + 1))
        else:
            print(f"  FAILED {ticker}")
            continue
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] for c in df.columns]
        rows = []
        for ts, r in df.iterrows():
            t = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
            o, h, lo, c = (float(r[k]) for k in ("Open", "High", "Low", "Close"))
            adj = float(r["Adj Close"]) if "Adj Close" in r and r["Adj Close"] == r["Adj Close"] else c
            if c != c or c <= 0:
                continue
            rows.append((int(t.timestamp()), o, h, lo, c, adj, float(r.get("Volume", 0) or 0)))
        path = DATA / f"{name}_1d.csv.gz"
        with gzip.open(path, "wt", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "open", "high", "low", "close", "adj_close", "volume"])
            w.writerows(rows)
        day = lambda s: (datetime(1970, 1, 1) + timedelta(seconds=s)).strftime("%Y-%m-%d")  # noqa: E731 - pre-1970 safe on Windows
        first = day(rows[0][0]) if rows else "-"
        last = day(rows[-1][0]) if rows else "-"
        print(f"  {name:4} {ticker:9} {len(rows):6,} days  {first} .. {last}")
        time.sleep(0.5)


if __name__ == "__main__":
    main(sys.argv[1:] or list(SERIES))
