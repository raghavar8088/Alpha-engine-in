"""Per-session implied-volatility surface of BANKNIFTY MONTHLY options, from real NSE closes.

For every session and every listed monthly expiry (a monthly is an expiry with a future):
  F      the forward implied by put-call parity at the five strikes nearest the future's close
         (option closes are last trades; the index and futures closes are 30-minute averages,
         so parity on the options themselves is the consistent forward)
  T      variance-clock sessions to expiry at 15:30
  smile  IV(x) = a + b x + c x^2, x = ln(K/F), fitted on OUT-of-the-money closes within +-6%
         of F that traded at least MIN_CONTRACTS contracts; a is the ATM vol
It also keeps every monthly close within +-10% (for the swing replays, which trade REAL closes).

Output: surface.json.gz  {day_key: {expiry_key: [F, T, a, b, c, n_points, spot_close]}}
        closes.json.gz   {day_key: {expiry_key: {strike: [call, put, call_contracts, put_contracts]}}}
"""

import glob
import gzip
import json
import math
import os
import statistics
import sys
from datetime import date

import bn_common as C

BHAV = os.environ.get("BN_BHAV", os.path.join(C.DATA, "bhav"))
MIN_CONTRACTS = 20


def fit_smile(pts):
    """Least squares a + b x + c x^2 on (x, iv) points; falls back to the mean."""
    n = len(pts)
    if n < 4:
        return (statistics.mean(v for _, v in pts), 0.0, 0.0) if pts else None
    s = [sum(x ** p for x, _ in pts) for p in range(5)]
    t = [sum(v * x ** p for x, v in pts) for p in range(3)]
    m = [[s[0], s[1], s[2]], [s[1], s[2], s[3]], [s[2], s[3], s[4]]]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if abs(det) < 1e-18:
        return statistics.mean(v for _, v in pts), 0.0, 0.0

    def solve(col):
        mm = [row[:] for row in m]
        for i in range(3):
            mm[i][col] = t[i]
        return (mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1]) - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0])) / det

    return solve(0), solve(1), solve(2)


def build(k, rows, spot):
    futs = {r[1]: r for r in rows if r[0] == "FUT"}
    surf, px = {}, {}
    for exp, fr in futs.items():
        ek = C.dk(date.fromisoformat(exp))
        if ek <= k:
            continue
        T = C.sessions_left(C.at(k, C.CLOSE_MIN), ek) / C.SESS_PER_YEAR
        disc = math.exp(-C.R * C.T_cal(C.at(k, C.CLOSE_MIN), ek))
        book: dict[float, list] = {}
        for r in rows:
            if r[1] != exp or r[0] not in ("CE", "PE"):
                continue
            b = book.setdefault(r[2], [0.0, 0.0, 0, 0])
            if r[0] == "CE":
                b[0], b[2] = r[6], r[8]
            else:
                b[1], b[3] = r[6], r[8]
        fut = fr[6] or fr[7]
        if not book or not fut:
            continue
        both = sorted((K for K, b in book.items() if b[0] > 0 and b[1] > 0 and b[2] > 0 and b[3] > 0),
                      key=lambda K: abs(K - fut))[:5]
        F = statistics.median(K + (book[K][0] - book[K][1]) / disc for K in both) if both else fut
        pts = []
        for K, b in book.items():
            if abs(K / F - 1) > 0.06:
                continue
            call = K >= F
            p, n = (b[0], b[2]) if call else (b[1], b[3])
            if p <= 0 or n < MIN_CONTRACTS:
                continue
            iv = C.implied_vol(p, F, K, T, call, disc)
            if iv and 0.03 < iv < 2.0:
                pts.append((math.log(K / F), iv))
        sm = fit_smile(pts)
        if sm is None:
            continue
        a, b, c = sm
        if not (0.03 < a < 2.0):
            continue
        surf[ek] = [round(F, 2), round(T * C.SESS_PER_YEAR, 4), round(a, 5), round(b, 5), round(c, 5), len(pts), spot]
        px[ek] = {K: v for K, v in book.items() if abs(K / F - 1) <= 0.10}
    return surf, px


def main():
    daily = {C.dkey(int(r[0])): r[4] for r in C.load_rows("NIFTYBANK_D")}
    bn = C.Sessions("NIFTYBANK", start=date(2015, 1, 1))
    C.set_trading_days(bn.all_days)
    files = sorted(glob.glob(os.path.join(BHAV, "*.json.gz")))
    surface, closes = {}, {}
    for f in files:
        d = date.fromisoformat(os.path.basename(f)[:10])
        k = C.dk(d)
        if d < date(2015, 6, 1):
            continue
        with gzip.open(f, "rt") as g:
            rows = json.load(g)
        s, p = build(k, rows, daily.get(k))
        if s:
            surface[k] = s
            closes[k] = {ek: {str(K): v for K, v in book.items()} for ek, book in p.items()}
    with gzip.open(os.path.join(C.DATA, "surface.json.gz"), "wt") as g:
        json.dump(surface, g, separators=(",", ":"))
    with gzip.open(os.path.join(C.DATA, "closes.json.gz"), "wt") as g:
        json.dump(closes, g, separators=(",", ":"))
    # quality report: front-month ATM vol and smile points per year
    by_year: dict[int, list] = {}
    for k, s in surface.items():
        ek = min(s)
        by_year.setdefault(C.kdate(k).year, []).append((s[ek][2], s[ek][5], s[ek][0] / (s[ek][6] or s[ek][0]) - 1))
    for y in sorted(by_year):
        v = by_year[y]
        print(f"{y}: {len(v)} sessions  front-month ATM IV median {statistics.median(a for a, _, _ in v):.3f}"
              f"  smile points median {statistics.median(n for _, n, _ in v)}  F/spot-1 median {statistics.median(x for _, _, x in v) * 100:.2f}%")
    print(f"surface: {len(surface)} sessions")


if __name__ == "__main__":
    main()
