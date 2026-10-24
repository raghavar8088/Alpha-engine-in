"""Phase 5 follow-up (after the one-time tests; nothing here selects or re-tunes): where the transfer
profits came from (by year, against the underlying's own move), whether they survive without the
best trade and outside the 2024-26 bull run, and what a Rs10 lakh account could actually carry.

    python robust5.py <work5>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "phase4"), HERE):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import run_phase5 as R5  # noqa: E402

CAP = 1_000_000
RULES = ("CO-1", "CO-2", "N-B", "C-E")
MARKETS = ("GOLD", "SILVER", "COPPER", "ZINC", "GOLDM", "SILVERM")


def yearly_move(work5, m):
    """The front-month futures' % change per calendar year (first to last close of the year)."""
    cyc = pd.read_pickle(R5.cache(work5, m))
    front = {}
    for c in sorted(cyc, key=lambda x: x.expiry):
        for d, f in zip(c.dates, c.F):
            if d < c.expiry and d not in front and np.isfinite(f):
                front[d] = f
    s = pd.Series(front).sort_index()
    out = {}
    for y, g in s.groupby(s.index.year):
        out[int(y)] = round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 1)
    return out


def load(work5, name, m):
    p = os.path.join(work5, f"p5_A_{name}_{m}.csv")
    t = pd.read_csv(p, parse_dates=["entry", "exit", "expiry"]) if os.path.exists(p) and os.path.getsize(p) > 5 else pd.DataFrame()
    if not t.empty and "hedge_margin_peak" in t:
        t["capital"] = t["capital"] + t["hedge_margin_peak"].fillna(0)
    return t


def main(work5):
    R5.load_specs(work5)
    out = {"moves": {m: yearly_move(work5, m) for m in MARKETS}}
    rows = []
    for name in RULES:
        for m in MARKETS:
            t = load(work5, name, m)
            if t.empty:
                continue
            by_year = t.groupby(t.exit.dt.year).pnl.sum().round().astype(int).to_dict()
            best = t.pnl.max()
            pre = t[t.exit < "2024-01-01"]
            post = t[t.exit >= "2024-01-01"]
            yrs = (t.exit.max() - t.entry.min()).days / 365.25
            pre_pf = (float(pre.pnl[pre.pnl > 0].sum() / -pre.pnl[pre.pnl < 0].sum())
                      if (pre.pnl < 0).any() else (float("inf") if len(pre) else float("nan")))
            rows.append({"rule": name, "market": m, "n": len(t), "net": round(t.pnl.sum()),
                         "pf_before_2024": round(pre_pf, 2), "win_before_2024": round(float((pre.pnl > 0).mean()), 2) if len(pre) else None,
                         "net_without_best": round(t.pnl.sum() - best),
                         "net_before_2024": round(pre.pnl.sum()), "n_before_2024": len(pre),
                         "net_2024_on": round(post.pnl.sum()), "n_2024_on": len(post),
                         "losing_years": sum(v < 0 for v in by_year.values()), "years": len(by_year),
                         "by_year": by_year, "avg_capital_per_trade": round(t.capital.mean()),
                         "net_per_year": round(t.pnl.sum() / yrs), "return_on_capital_per_year_pct":
                         round(t.pnl.sum() / yrs / t.capital.mean() * 100, 1), "worst_trade": round(t.pnl.min()),
                         "worst_trade_pct_of_capital": round(float(t.roc.min()) * 100, 1)})
    out["rules"] = rows
    # Rs10 lakh view: one lot of each rule on the contracts a Rs10 lakh account can carry (minis, copper, zinc)
    retail = []
    for r in rows:
        if r["market"] in ("GOLDM", "SILVERM", "COPPER", "ZINC") and r["rule"] != "C-E":
            lots = max(0, int(0.4 * CAP // r["avg_capital_per_trade"]))
            retail.append({"rule": r["rule"], "market": r["market"], "margin_per_lot": r["avg_capital_per_trade"],
                           "lots_at_40pct_of_10L": lots, "profit_per_year_at_that_size": r["net_per_year"] * lots,
                           "worst_trade_at_that_size": r["worst_trade"] * lots})
    out["retail_one_rule_at_a_time"] = retail
    f2 = {}
    for label in ("crude_T2_2024-26_mini", "natural_gas_2022-26", "GOLD", "SILVER", "COPPER", "ZINC", "GOLDM", "SILVERM"):
        p = os.path.join(work5, f"p5_B_F2_{label}.csv")
        if not os.path.exists(p) or os.path.getsize(p) < 5:
            continue
        t = pd.read_csv(p, parse_dates=["entry", "exit"])
        f2[label] = {"by_year": t.groupby(t.exit.dt.year).pnl.sum().round().astype(int).to_dict(),
                     "net_before_2024": round(t.pnl[t.exit < "2024-01-01"].sum()), "net_2024_on": round(t.pnl[t.exit >= "2024-01-01"].sum())}
    out["F2_by_market"] = f2
    for k in ("moves",):
        print(k, json.dumps(out[k]))
    for r in rows:
        print(f"{r['rule']:5s} {r['market']:8s} n={r['n']:3d} net Rs{r['net']:>12,} | w/o best Rs{r['net_without_best']:>12,} | "
              f"pre-2024 Rs{r['net_before_2024']:>11,} ({r['n_before_2024']}) | 2024+ Rs{r['net_2024_on']:>11,} ({r['n_2024_on']}) | "
              f"losing years {r['losing_years']}/{r['years']} | {r['return_on_capital_per_year_pct']}%/yr on margin | "
              f"worst {r['worst_trade_pct_of_capital']}% | {r['by_year']}")
        print(f"      before 2024: PF {r['pf_before_2024']}, wins {r['win_before_2024']}")
    print()
    for r in retail:
        print(r)
    print()
    for k, v in f2.items():
        print("F2", k, v)
    json.dump(out, open(os.path.join(work5, "p5_robust.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
