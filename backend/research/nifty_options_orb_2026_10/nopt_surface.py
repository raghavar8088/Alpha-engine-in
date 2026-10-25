"""Per-session implied-volatility surfaces of NIFTY options, from real NSE closing prices.

    python -I backend/research/nifty_options_orb_2026_10/nopt_surface.py

For every bhavcopy session k and every NIFTY option expiry after k (weeklies included; they have no
future, so the forward comes from the options themselves, as ../banknifty_2026_10/bn_surface.py):
  F      put-call-parity forward at the five strikes nearest the index close (both sides traded)
  T      variance-clock sessions from k's 15:30 to 15:30 on the expiry day
  smile  iv(x) = a + b x + c x^2, x = ln(K/F), fitted on OUT-of-the-money closes within 4% of F that
         traded at least MIN_CONTRACTS contracts; a is the ATM vol
Also kept for the checks: each expiry's real open/high/low/close near the money, the listed expiries
and strikes, and the lot size (UDiFF files carry it from July 2024).

Output (data/): surface.json.gz {k: {ek: [F, T_sessions, a, b, c, n, S]}}, closes.json.gz
{k: {ek: {K: [c_close, p_close, c_contracts, p_contracts, c_open, c_high, c_low, p_open, p_high, p_low]}}},
listing.json.gz {k: {ek: [strikes]}}; results/surface_quality.json.
"""

from __future__ import annotations

import glob
import gzip
import json
import math
import os
import statistics
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nopt_common as C  # noqa: E402

MIN_CONTRACTS = 100
FIT_BAND = 0.04
# NSE moved the 2023 Bakri Id holiday from 28 to 29 June at short notice: the files list that week's
# expiry as 29 June up to 27 June, but the contracts expired on Wednesday 28 June. The one such case
# in the window (every other listed expiry is a trading day).
EXPIRY_FIX = {"2023-06-29": "2023-06-28"}


def index_closes() -> dict[int, float]:
    z = np.load(C.DATA / "minutes.npz")
    out = {}
    for d, row, pres in zip(z["days"], z["c"], z["present"]):
        idx = np.where(pres)[0]
        if len(idx):
            out[C.dk(date.fromisoformat(str(d)))] = float(row[idx[-1]])
    return out


def build(k: int, rows: list, S: float | None):
    books: dict[str, dict[float, list]] = {}
    fut = sorted((r for r in rows if r[0] == "FUT" and r[6] > 0), key=lambda r: r[1])
    ref = S or (fut[0][6] if fut else None)
    for r in rows:
        if r[0] not in ("CE", "PE"):
            continue
        b = books.setdefault(r[1], {}).setdefault(r[2], [0.0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        if r[0] == "CE":
            b[0], b[2], b[4], b[5], b[6] = r[6], r[8], r[3], r[4], r[5]
        else:
            b[1], b[3], b[7], b[8], b[9] = r[6], r[8], r[3], r[4], r[5]
    surf, px, listing = {}, {}, {}
    if not ref:
        return surf, px, listing
    for exp, book in books.items():
        ek = C.dk(date.fromisoformat(exp))
        listing[ek] = sorted(book)
        if ek <= k:
            continue
        e = C.at(k, C.CLOSE_MIN)
        T = C.sessions_left(e, ek) / C.SESS_PER_YEAR
        disc = math.exp(-C.R * C.T_cal(e, ek))
        both = sorted((K for K, b in book.items() if b[0] > 0 and b[1] > 0 and b[2] > 0 and b[3] > 0),
                      key=lambda K: abs(K - ref))[:5]
        if len(both) < 3:
            continue
        F = statistics.median(K + (book[K][0] - book[K][1]) / disc for K in both)
        pts = []
        for K, b in book.items():
            if abs(K / F - 1) > FIT_BAND:
                continue
            call = K >= F
            p, n = (b[0], b[2]) if call else (b[1], b[3])
            if p <= 0 or n < MIN_CONTRACTS:
                continue
            iv = C.implied_vol(p, F, K, T, call, disc)
            if iv and 0.02 < iv < 3.0:
                pts.append((math.log(K / F), iv))
        sm = C.fit_smile(pts)
        if sm is None:
            continue
        a, b_, c = sm
        if not (0.02 < a < 3.0):
            continue
        surf[ek] = [round(F, 2), round(T * C.SESS_PER_YEAR, 4), round(a, 5), round(b_, 5), round(c, 5), len(pts),
                    round(S, 2) if S else None]
        px[ek] = {K: v for K, v in book.items() if abs(K / F - 1) <= 0.03}
    return surf, px, listing


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    C.set_calendar()
    closes_idx = index_closes()
    files = sorted(glob.glob(str(C.DATA / "bhav" / "*.json.gz")))
    surface, closes, listing, lots, missing_spot = {}, {}, {}, {}, []
    for f in files:
        d = date.fromisoformat(os.path.basename(f)[:10])
        k = C.dk(d)
        if k not in C._TRADING_SET:          # Diwali Muhurat files: an hour of thin evening trading, no anchor
            continue
        with gzip.open(f, "rt") as g:
            rows = json.load(g)
        for r in rows:
            r[1] = EXPIRY_FIX.get(r[1], r[1])
        S = closes_idx.get(k)
        if S is None:
            missing_spot.append(d.isoformat())
        s, p, lst = build(k, rows, S)
        lot = [r[11] for r in rows if r[0] in ("CE", "PE") and r[11]]
        if lot:
            lots[k] = int(statistics.median(lot))
        if s:
            surface[k] = s
        if p:
            closes[k] = {ek: {str(K): v for K, v in book.items()} for ek, book in p.items()}
        listing[k] = {ek: v for ek, v in lst.items()}
    with gzip.open(C.DATA / "surface.json.gz", "wt") as g:
        json.dump(surface, g, separators=(",", ":"))
    with gzip.open(C.DATA / "closes.json.gz", "wt") as g:
        json.dump(closes, g, separators=(",", ":"))
    with gzip.open(C.DATA / "listing.json.gz", "wt") as g:
        json.dump(listing, g, separators=(",", ":"))
    # quality: the nearest expiry's ATM vol and smile points per year; lot sizes seen
    by_year: dict[int, list] = {}
    for k, s in surface.items():
        ek = min(s)
        by_year.setdefault(C.kdate(k).year, []).append((s[ek][2], s[ek][5], (s[ek][0] / s[ek][6] - 1) if s[ek][6] else 0.0,
                                                          ek - k))
    q = {"bhav_files": len(files), "sessions_with_surface": len(surface), "sessions_without_index_close": missing_spot,
         "by_year": {y: {"sessions": len(v), "nearest_expiry_atm_iv_median": round(statistics.median(a for a, _, _, _ in v), 4),
                         "smile_points_median": statistics.median(n for _, n, _, _ in v),
                         "forward_over_index_minus_1_median_pct": round(statistics.median(x for _, _, x, _ in v) * 100, 3)}
                     for y, v in sorted(by_year.items())},
         "lot_sizes_seen": {str(C.kdate(k)): v for k, v in sorted(lots.items()) if k == min(lots) or lots.get(k - 1) != v}}
    C.RES.mkdir(exist_ok=True)
    with open(C.RES / "surface_quality.json", "w", encoding="utf-8") as f:
        json.dump(q, f, indent=1)
    print(json.dumps(q, indent=1)[:3000])


if __name__ == "__main__":
    main()
