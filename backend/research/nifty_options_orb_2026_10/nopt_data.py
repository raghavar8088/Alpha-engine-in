"""NIFTY 50 and India VIX 1-minute history, 2021-10-01 -> 2026-10-23, as day x minute matrices.

    python -I backend/research/nifty_options_orb_2026_10/nopt_data.py

Sources: Angel One ONE_MINUTE candles, the index-intraday study's download to 2026-10-09
(../index_intraday_2026_10/data/1m/) and the server's daily files after it
(../niftybees_orb_2026_10/data/box_1m/NIFTY and data/box_1m/INDIAVIX here).

Rules (as ../niftybees_orb_2026_10/orb_data.py, with the index-intraday module's closing-auction rule):
* regular session 09:15-15:29 only; a day needs its 09:15 minute and 360 of the 375 minutes, or, from
  2026-08-03 (NSE's closing auction: Angel serves almost no index minutes 15:15-15:29), 345 of the
  360 minutes before 15:15;
* a missing minute is flat at the previous close; a print <= 0 or > 15% off the day's median is dropped.
The NIFTY 50 index needs no opening-print cleaning: its 09:15 minute is computed from the stocks.

Output: data/minutes.npz with NIFTY o/h/l/c (days x 375), INDIAVIX c (aligned to NIFTY's days, NaN
where missing) and results/data_quality.json.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ORB = HERE.parent / "niftybees_orb_2026_10"
sys.path.insert(0, str(ORB))
import orb_data as OD  # noqa: E402

START, END = date(2021, 10, 1), date(2026, 10, 23)
AUCTION_FROM = np.datetime64("2026-08-03", "D")


def read(name: str) -> np.ndarray:
    files = sorted((OD.SRC_STUDY / name).glob("*.csv.gz"))
    for box in (ORB / "data" / "box_1m" / name, HERE / "data" / "box_1m" / name):
        files += sorted(box.glob("*.csv.gz"))
    import pandas as pd
    parts = []
    for f in files:
        a = pd.read_csv(f, usecols=range(6)).apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        a = a[~np.isnan(a[:, :5]).any(axis=1)]
        a[np.isnan(a[:, 5]), 5] = 0.0
        parts.append(a)
    return np.concatenate(parts)


def build(name: str, rows: np.ndarray) -> dict:
    """orb_data.build with the closing-auction rule for days from 2026-08-03."""
    OD.START, OD.END = START, END
    saved = OD.MIN_MINUTES
    OD.MIN_MINUTES = 0                       # keep every day with a 09:15, decide below
    d = OD.build(name, rows)
    OD.MIN_MINUTES = saved
    pres = d["present"]
    before = pres[:, :360].sum(axis=1)
    total = pres.sum(axis=1)
    auction = d["days"] >= AUCTION_FROM
    keep = np.where(auction, before >= 345, total >= 360)
    dropped = [{"date": str(x), "minutes": int(t)} for x, t, k in zip(d["days"], total, keep) if not k]
    for k in ("days", "o", "h", "l", "c", "v", "present"):
        d[k] = d[k][keep]
    d["quality"]["days_dropped_short"] = dropped
    d["quality"]["kept_days"] = int(keep.sum())
    return d


def vix_minutes(rows: np.ndarray, days: np.ndarray) -> tuple[np.ndarray, dict]:
    """India VIX needs no session rules, only "the last value at or before this minute": VIX
    often starts at 09:16, and a missing minute just carries the last one. Values under 2 are
    Angel's /100 prints (rescaled); a print more than 30% off the day's median is dropped."""
    ts = rows[:, 0].astype(np.int64) + 19800
    dayn, m = ts // 86400, (ts % 86400) // 60 - OD.OPEN_MIN
    c = rows[:, 4].copy()
    c = np.where((c > 0) & (c < 2), c * 100, c)
    ok = (m >= 0) & (m < OD.SESSION) & (c > 0)
    out = np.full((len(days), OD.SESSION), np.nan)
    pos = {int(np.datetime64(str(d), "D").astype(np.int64)): i for i, d in enumerate(days)}
    bad = 0
    for dn in np.unique(dayn[ok]):
        i = pos.get(int(dn))
        if i is None:
            continue
        sel = ok & (dayn == dn)
        med = np.median(c[sel])
        good = sel & (np.abs(c / med - 1) <= 0.30)
        bad += int(sel.sum() - good.sum())
        out[i, m[good]] = c[good]
    # forward fill within each day
    for i in range(len(days)):
        row = out[i]
        idx = np.where(~np.isnan(row), np.arange(OD.SESSION), -1)
        np.maximum.accumulate(idx, out=idx)
        out[i] = np.where(idx >= 0, row[np.maximum(idx, 0)], np.nan)
    return out, {"vix_prints_dropped": bad, "nifty_days_without_vix": [str(days[i]) for i in range(len(days)) if np.isnan(out[i]).all()],
                 "nifty_days_vix_starts_after_0930": [str(days[i]) for i in range(len(days))
                                                      if not np.isnan(out[i]).all() and np.isnan(out[i, 15])]}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    nifty = build("NIFTY", read("NIFTY"))
    vix_c, vq = vix_minutes(read("INDIAVIX"), nifty["days"])
    vix = {"quality": vq}
    (HERE / "data").mkdir(exist_ok=True)
    np.savez_compressed(HERE / "data" / "minutes.npz", days=nifty["days"].astype(str), o=nifty["o"], h=nifty["h"],
                        l=nifty["l"], c=nifty["c"], present=nifty["present"], vix=vix_c)
    q = {"window": [START.isoformat(), END.isoformat()],
         "nifty": {k: v for k, v in nifty["quality"].items() if k != "kept_days_with_missing_minutes"},
         "nifty_days_with_missing_minutes": len(nifty["quality"]["kept_days_with_missing_minutes"]),
         "vix": vix["quality"],
         "nifty_days_without_vix": vix["quality"]["nifty_days_without_vix"]}
    (HERE / "results").mkdir(exist_ok=True)
    with open(HERE / "results" / "data_quality_minutes.json", "w", encoding="utf-8") as f:
        json.dump(q, f, indent=1, default=str)
    print("NIFTY kept", nifty["quality"]["kept_days"], "first", nifty["days"][0], "last", nifty["days"][-1],
          "| dropped", [x["date"] for x in nifty["quality"]["days_dropped"]][:20], q["nifty"]["days_dropped_short"][:10])
    print("NIFTY days without VIX:", q["nifty_days_without_vix"], "| VIX starts after 09:30 on:",
          vix["quality"]["nifty_days_vix_starts_after_0930"][:20], "| VIX prints dropped:", vix["quality"]["vix_prints_dropped"])
    print("NIFTY minutes filled flat:", nifty["quality"]["minutes_filled_flat"], " bad prints:",
          len(nifty["quality"]["prints_dropped_nonpositive_or_15pct"]))


if __name__ == "__main__":
    main()
