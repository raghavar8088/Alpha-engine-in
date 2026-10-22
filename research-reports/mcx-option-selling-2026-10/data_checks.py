"""Data-quality checks run BEFORE any strategy result is computed (no P&L anywhere here).

    python data_checks.py <work_dir>
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

import b76

work = sys.argv[1]
opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
tr = opt[opt.traded]

print("1. TICK SIZE (every traded close is a multiple of it)")
for sym, g in tr.groupby("sym"):
    c = np.round(g.close.to_numpy() * 100).astype(np.int64)
    for tick in (10, 5, 1):
        if np.all(c % tick == 0):
            print(f"   {sym:<11} tick Rs{tick / 100:.2f}  ({len(c):,} traded closes)")
            break

print("\n2. OPTION EXPIRIES: mini vs parent (same dates?)")
for mini, big in (("CRUDEOILM", "CRUDEOIL"), ("NATGASMINI", "NATURALGAS")):
    em = set(opt[opt.sym == mini].expiry.dt.date)
    eb = set(opt[opt.sym == big].expiry.dt.date)
    print(f"   {mini}: {len(em)} expiries, {len(em & eb)} shared with {big}; mini-only {sorted(em - eb)[:6]}")

print("\n3. MINI vs PARENT PREMIUM (same date, expiry, strike, type; both traded)")
for mini, big in (("CRUDEOILM", "CRUDEOIL"), ("NATGASMINI", "NATURALGAS")):
    a = tr[tr.sym == mini][["date", "expiry", "strike", "cp", "close", "vol"]]
    b = tr[tr.sym == big][["date", "expiry", "strike", "cp", "close", "vol"]]
    m = a.merge(b, on=["date", "expiry", "strike", "cp"], suffixes=("_m", "_b"))
    m = m[(m.close_b >= 5 if mini == "CRUDEOILM" else m.close_b >= 1)]
    d = (m.close_m - m.close_b) / m.close_b
    if not len(d):
        print(f"   {mini}: no matched rows yet")
        continue
    print(f"   {mini}: {len(m):,} matched rows; median |diff| {np.median(np.abs(d)):.2%}, "
          f"90th pct {np.percentile(np.abs(d), 90):.2%}, mean diff {d.mean():+.2%}")

print("\n4. PUT-CALL PARITY vs the mapped future (validates the option -> future mapping)")
def umap(sym):
    fexp = np.array(sorted(fut.loc[fut.sym == sym, "expiry"].unique()))
    return lambda e: pd.Timestamp(fexp[fexp >= np.datetime64(e)][0]) if (fexp >= np.datetime64(e)).any() else None
for sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI"):
    g = tr[tr.sym == sym]
    ce = g[g.cp == "CE"].set_index(["date", "expiry", "strike"]).close
    pe = g[g.cp == "PE"].set_index(["date", "expiry", "strike"]).close
    j = pd.concat([ce.rename("c"), pe.rename("p")], axis=1, join="inner").reset_index()
    if not len(j) or not (fut.sym == sym).any():
        print(f"   {sym:<11} no data yet")
        continue
    m = umap(sym)
    j["fexp"] = j.expiry.map({e: m(e) for e in j.expiry.unique()})
    f = fut[(fut.sym == sym) & fut.traded][["date", "expiry", "close"]].rename(columns={"expiry": "fexp", "close": "F"})
    j = j.merge(f, on=["date", "fexp"])
    T = (j.expiry - j.date).dt.days.clip(lower=0.5) / 365
    j["F_impl"] = j.strike + (j.c - j.p) * np.exp(b76.R * T)
    j["dev"] = (j.F_impl - j.F) / j.F
    near = j[(j.strike - j.F).abs() / j.F < 0.03]
    print(f"   {sym:<11} {len(near):,} near-money pairs: median |F_impl - F| {near.dev.abs().median():.3%}, "
          f"95th pct {near.dev.abs().quantile(0.95):.3%}")

print("\n5. LIQUIDITY BY ENTRY DAY: traded strikes within +/-10% of F and lots traded at that strike set")
for sym in ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI"):
    g = opt[(opt.sym == sym) & (opt.expiry <= "2026-10-31")]
    out = {}
    for exp, ge in g.groupby("expiry"):
        dates = sorted(ge.date.unique())
        if not dates or dates[-1] != exp:
            continue
        for n in (20, 15, 10, 7, 5):
            if len(dates) > n:
                d = dates[-1 - n]
                day = ge[(ge.date == d)]
                fx = fut[(fut.sym == sym) & (fut.date == d)]
                F = fx.sort_values("expiry").close.iloc[0] if len(fx) else np.nan
                if not np.isfinite(F):
                    continue
                w = day[(day.traded) & ((day.strike - F).abs() / F < 0.10)]
                out.setdefault(n, []).append((len(w), int(w.vol.sum())))
    print(f"   {sym:<11} " + "  ".join(f"T-{n}: {np.median([a for a, b in v]):.0f} strikes / "
                                         f"{np.median([b for a, b in v]):,.0f} lots" for n, v in sorted(out.items(), reverse=True)))
