"""Intraday check of the premium model against REAL 5-minute BANKNIFTY option prices.

Angel serves 5m candles for LIVE contracts only; bn_fetch_optcandles.py pulled the October and
November 2026 monthlies, strikes 53,500-57,000, calls and puts (3 Aug .. 9 Oct 2026). For every
session, entry times 09:30, 10:00 .. 14:30 and holds of 30 / 60 / 120 minutes and to 15:15, on
the strike nearest the spot at entry (both bars must have traded), the model's premium change
(bn_price, anchored on the previous session's real smile) is compared with the real one.
These sessions are after both research periods' calibration choices, so this is out of sample.
"""

import gzip
import json
import os
import statistics
from bisect import bisect_right
from datetime import date

import bn_common as C
from bn_price import Pricer


def main():
    bn = C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
    C.set_trading_days(bn.all_days)
    px = Pricer()
    with gzip.open(os.path.join(C.DATA, "bn_optcandles.json.gz"), "rt") as f:
        raw = json.load(f)
    opt = {}
    for key, rows in raw.items():
        exp, K, typ = key.split("|")
        ek = C.dk(date.fromisoformat(exp))
        opt[(ek, float(K), typ)] = {int(r[0]): (r[4], r[5]) for r in rows}   # bar start -> (close, volume)
    out = {"30": [], "60": [], "120": [], "eod": []}
    level = []
    for k in sorted({C.dkey(t) for v in opt.values() for t in v}):
        kp = px.prev_session(k)
        if kp is None or k not in bn.bars:
            continue
        bars = {int(b[0]): b for b in bn.bars[k]}
        for ek in px.surf[kp]:
            if C.trading_sessions_left(k, ek) < 3:
                continue
            for m0 in range(9 * 60 + 30, 14 * 60 + 31, 30):
                b0 = bars.get(C.at(k, m0 - 5))
                if not b0:
                    continue
                S0 = b0[4]
                K = round(S0 / C.STEP) * C.STEP
                for typ in ("CE", "PE"):
                    series = opt.get((ek, K, typ))
                    if not series:
                        continue
                    r0 = series.get(C.at(k, m0 - 5))
                    if not r0 or r0[1] <= 0:
                        continue
                    call = typ == "CE"
                    e0 = C.at(k, m0)
                    m_0 = px.premium(e0, S0, K, call, ek, kp)
                    level.append((m_0 - r0[0]) / r0[0])
                    for hold, m1 in (("30", m0 + 30), ("60", m0 + 60), ("120", m0 + 120), ("eod", C.SQUARE_OFF_MIN)):
                        if m1 > C.SQUARE_OFF_MIN:
                            continue
                        b1 = bars.get(C.at(k, m1 - 5))
                        r1 = series.get(C.at(k, m1 - 5))
                        if not b1 or not r1 or r1[1] <= 0:
                            continue
                        m_1 = px.premium(C.at(k, m1), b1[4], K, call, ek, kp)
                        out[hold].append(((m_1 - m_0) - (r1[0] - r0[0])) / r0[0])
    res = {"level_error": {"n": len(level), "mean": statistics.mean(level), "median": statistics.median(level),
                           "sd": statistics.pstdev(level)}}
    print(f"level error at entry: n {len(level)} mean {res['level_error']['mean'] * 100:+.2f}% "
          f"median {res['level_error']['median'] * 100:+.2f}% sd {res['level_error']['sd'] * 100:.2f}%")
    for hold, xs in out.items():
        if len(xs) < 20:
            continue
        res[hold] = {"n": len(xs), "mean": statistics.mean(xs), "median": statistics.median(xs), "sd": statistics.pstdev(xs)}
        print(f"hold {hold:>4}: n {len(xs):5d}  change error mean {res[hold]['mean'] * 100:+.2f}%  "
              f"median {res[hold]['median'] * 100:+.2f}%  sd {res[hold]['sd'] * 100:.2f}% of premium")
    with open(os.path.join(C.DATA, "intraday_check.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


if __name__ == "__main__":
    main()
