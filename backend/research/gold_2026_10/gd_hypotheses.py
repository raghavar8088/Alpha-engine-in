"""Gold-specific alternatives to the pattern library — each a single rule, fixed before it was run.

    python backend/research/gold_2026_10/gd_hypotheses.py

Every rule here was written down (this docstring) before its first result was seen, with no
parameter search; each is reported on two halves of its sample, after the venue's measured
costs. One configuration each, so there is nothing to deflate but nothing to pick from either.

H-G1  INTRADAY MOMENTUM (Gao, Han, Li & Zhou 2018 for the S&P 500; Jin, Kearney, Li & Yang 2020
      for Chinese metal futures; untested on gold). The COMEX day session opens 08:20 New York
      time. Rule: the sign of the first half hour's return (08:20-08:50 NY) is the side taken
      for the last half hour (13:00-13:30 NY). Predictive slope and the rule's net mean.
      Data: Binance PAXG 1m from 2025, Delta XAUT/PAXG 2026. Costs: Delta round trip.

H-G2  SESSION DRIFT. Does gold's return accrue in particular hours? Mean 1h return by UTC hour
      block, and one rule: long 23:00-13:00 UTC (Asia + London), flat otherwise, against
      holding all day. Data: COMEX GC 1h 2024-05..2026-10, Binance PAXG 2025-26 (weekdays).

H-G3  TOKEN BASIS REVERSION on Delta. XAUT and PAXG are both one troy ounce; their perps'
      ratio wanders (sd 13 bp). Rule: z = (basis - its 1-day mean) / its 1-day sd, on 15m
      closes; |z| >= 2 opens the pair (short the rich leg, long the cheap one, equal dollars),
      z crossing 0 or 48 h closes it. Cost: four legs at the venue fee + measured half-spreads
      = 5.2 bp of one leg's notional per round trip. Funding nets out (same 0.005% both sides,
      96-100% of hours).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

import gd_data as D

DELTA_RT = 2.36 + 0.24        # fee both legs + PAXG spread (the costlier of the two)


def t(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))))


def ny_window(df: pd.DataFrame, start: str, end: str) -> pd.Series:
    """Log return from the price at `start` to the price at `end`, New York local time, per day."""
    d = df.copy()
    d.index = d.index.tz_convert("America/New_York")
    d = d[d.index.dayofweek < 5]
    p0 = d["open"].between_time(start, start)
    p1 = d["close"].between_time(end, end)
    p0.index = p0.index.normalize()
    p1.index = p1.index.normalize()
    j = pd.concat([p0.rename("a"), p1.rename("b")], axis=1).dropna()
    return np.log(j.b / j.a)


def hg1(name: str, df: pd.DataFrame) -> None:
    first = ny_window(df, "08:20", "08:49")
    last = ny_window(df, "13:00", "13:29")
    j = pd.concat([first.rename("f"), last.rename("l")], axis=1).dropna()
    j = j[(j.f != 0)]
    if len(j) < 40:
        print(f"  H-G1 {name}: too few days ({len(j)})")
        return
    b = np.polyfit(j.f, j.l, 1)[0]
    resid = j.l - (j.l.mean() + b * (j.f - j.f.mean()))
    se = math.sqrt((resid ** 2).sum() / (len(j) - 2) / ((j.f - j.f.mean()) ** 2).sum())
    rule = np.sign(j.f) * j.l * 1e4
    half = j.index[len(j) // 2]
    a, c = rule[rule.index < half], rule[rule.index >= half]
    print(f"  H-G1 {name}: {len(j)} days {j.index[0]:%Y-%m-%d}..{j.index[-1]:%Y-%m-%d}; slope {b:+.3f} (t {b / se:+.2f}); "
          f"rule gross {rule.mean():+.2f} bp (t {t(rule):+.2f}), net {rule.mean() - DELTA_RT:+.2f} bp; "
          f"halves gross {a.mean():+.2f} / {c.mean():+.2f} bp; |last half-hour| median {np.abs(j.l).median() * 1e4:.1f} bp")


def hg2(name: str, df: pd.DataFrame, rt_cost: float) -> None:
    h = df["close"].resample("1h").last().dropna()
    r = np.log(h).diff().dropna()
    r = r[r.index.dayofweek < 5]
    blocks = pd.cut(r.index.hour, [-1, 6, 12, 20, 23], labels=["00-07 Asia", "07-13 London", "13-21 NY", "21-24 late"])
    g = r.groupby(blocks, observed=True)
    print(f"  H-G2 {name}: {r.index[0]:%Y-%m-%d}..{r.index[-1]:%Y-%m-%d}, mean bp per hour by block: "
          + " | ".join(f"{k} {v.mean() * 1e4:+.2f} (t {t(v):+.1f}, n {len(v)})" for k, v in g))
    # rule: long 23:00-13:00 UTC; one round trip a day
    in_rule = (r.index.hour >= 23) | (r.index.hour < 13)
    day = r.index.normalize()
    rule_d = r[in_rule].groupby(day[in_rule]).sum() * 1e4 - rt_cost
    hold_d = r.groupby(day).sum() * 1e4
    j = pd.concat([rule_d.rename("rule"), hold_d.rename("hold")], axis=1).dropna()
    half = j.index[len(j) // 2]
    for lab, part in (("all", j), ("1st half", j[j.index < half]), ("2nd half", j[j.index >= half])):
        print(f"     {lab:8}: rule net {part.rule.mean():+.2f} bp/day (t {t(part.rule):+.2f}, ann SR {part.rule.mean() / part.rule.std() * math.sqrt(252):+.2f}) "
              f"vs hold {part.hold.mean():+.2f} bp/day (ann SR {part.hold.mean() / part.hold.std() * math.sqrt(252):+.2f}); "
              f"rule - hold {(part.rule - part.hold).mean():+.2f} (t {t(part.rule - part.hold):+.2f})")


def hg3(x: pd.DataFrame, p: pd.DataFrame) -> None:
    j = pd.concat([x["close"].rename("x"), p["close"].rename("p")], axis=1).dropna()
    j = j.resample("15min").last().dropna()
    basis = np.log(j.x / j.p) * 1e4                  # bp; >0 = XAUT rich
    mu = basis.rolling(96).mean().shift(1)            # the last day, known before this bar
    sd = basis.rolling(96).std().shift(1)
    z = (basis - mu) / sd
    cost = 4 * (1.18 + 0.06) + 0                      # 4 legs: fee x GST + half-spreads (~0.024 / 0.12)
    trades = []
    pos, t0, b0 = 0, None, None
    for ts, zz, bb in zip(z.index, z.to_numpy(), basis.to_numpy()):
        if not np.isfinite(zz):
            continue
        if pos == 0 and abs(zz) >= 2:
            pos, t0, b0 = (-1 if zz > 0 else 1), ts, bb   # z>0: short the basis (sell XAUT, buy PAXG)
        elif pos != 0 and ((pos < 0 and zz <= 0) or (pos > 0 and zz >= 0) or (ts - t0) >= pd.Timedelta(hours=48)):
            trades.append((t0, ts, pos * (bb - b0) - cost, pos * (bb - b0)))
            pos = 0
    tr = pd.DataFrame(trades, columns=["t0", "t1", "net", "gross"])
    if tr.empty:
        print("  H-G3: no trades")
        return
    half = tr.t0.iloc[len(tr) // 2]
    a, c = tr[tr.t0 < half], tr[tr.t0 >= half]
    print(f"  H-G3 XAUT/PAXG basis on Delta {j.index[0]:%Y-%m-%d}..{j.index[-1]:%Y-%m-%d}: {len(tr)} pair trades, "
          f"gross {tr.gross.mean():+.2f} bp, net {tr.net.mean():+.2f} bp (t {t(tr.net):+.2f}), win {(tr.net > 0).mean():.0%}, "
          f"median hold {(tr.t1 - tr.t0).median()}; halves net {a.net.mean():+.2f} (n {len(a)}) / {c.net.mean():+.2f} (n {len(c)})")


def main() -> None:
    b = D.load_1m("binance_PAXGUSDT_1m.csv.gz").loc["2025-01-01":]
    xa = D.load_1m("delta_XAUTUSD_1m.csv.gz")
    pa = D.load_1m("delta_PAXGUSD_1m.csv.gz")
    gc = D.load_1m("yahoo_GC_1h.csv.gz")
    print("H-G1 intraday momentum (first half hour of the COMEX day session -> its last half hour)")
    hg1("Binance PAXG 2025-26", b)
    hg1("Delta XAUT 2026", xa)
    hg1("Delta PAXG 2026", pa)
    print("\nH-G2 session drift")
    hg2("COMEX GC=F 1h", gc, 3.3)
    hg2("Binance PAXG", b, DELTA_RT)
    print("\nH-G3 token basis reversion")
    hg3(xa, pa)


if __name__ == "__main__":
    main()
