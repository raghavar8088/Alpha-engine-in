"""A4 reference (descriptive, no selection): the strategies that held up in Phases 1-3 (CO-1, CO-2, N-B)
marked to market at every week's last close on Jun 2024 - Oct 2026 mini prices, alone and as the
Rs10 lakh core (CO-1 3 lots + CO-2 3 + N-B 5).

    python reference4.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), HERE):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import run_phase2 as R2  # noqa: E402
import run_phase4 as R4  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402

CAP = 1_000_000
CO = {"CO-1": ("shortput", 0.5, 0.0, 15, "ivrv", None, 2.0, 0), "CO-2": ("trend20", 1.0, 0.0, 15, "ivrv110", None, 1.0, 1)}
NB = ("dstrangle", 0.10, 10, ("le", 50), None)
CORE = {"CO-1": 3, "CO-2": 3, "N-B": 5}


def parse_legs(s):
    out = []
    for x in s.split(";"):
        out.append((x[1:3], -1 if x[0] == "S" else +1, float(x[3:])))
    return out


def weekly_mtm(trades, cycles, week_ends, mult, tick, slip=0.01):
    """P&L per week: the change in each open position's value between week-end closes; entry fees
    in the entry week, the realised result (exit slippage and fees included) in the exit week."""
    by_exp = {c.expiry: c for c in cycles}
    pnl = pd.Series(0.0, index=week_ends)
    for t in trades:
        c = by_exp[t["expiry"]]
        legs = parse_legs(t["legs"])
        j0, je = c.dates.index(t["entry"]), c.dates.index(t["exit"])
        rows = [(cp, side, c.close[cp][E._row(c, cp, k)]) for cp, side, k in legs]
        fills = [cl[j0] - max(tick, slip * cl[j0]) if side < 0 else cl[j0] + max(tick, slip * cl[j0]) for cp, side, cl in rows]
        credit = sum(-side * f for (cp, side, cl), f in zip(rows, fills))
        fee_in = sum(mcx_option_leg(f, mult, sell=side < 0)["total"] for (cp, side, cl), f in zip(rows, fills))
        prev = 0.0
        for we in week_ends:
            if we < t["entry"]:
                continue
            if we >= t["exit"]:
                pnl[we] += t["pnl"] - prev
                break
            j = max(i for i, d in enumerate(c.dates) if d <= we)
            mtm = (credit + sum(side * cl[j] for cp, side, cl in rows)) * mult - fee_in
            pnl[we] += mtm - prev
            prev = mtm
    return pnl


def describe(p, capital=None):
    r = p / capital if capital is not None else None
    out = {"weeks": len(p), "net": round(float(p.sum())), "profitable_weeks": round(float((p > 0).mean()), 3),
           "flat_weeks": round(float((p == 0).mean()), 3), "avg_week": round(float(p.mean())),
           "best_week": round(float(p.max())), "worst_week": round(float(p.min()))}
    if r is not None:
        out.update({"avg_week_pct": round(float(r.mean()) * 100, 3), "weeks_ge_2pct": round(float((r >= 0.02).mean()), 3),
                    "best_week_pct": round(float(r.max()) * 100, 2), "worst_week_pct": round(float(r.min()) * 100, 2)})
    return out


def main(work):
    _, cmini = R4.books(work, "CRUDEOILM")
    _, nmini = R4.books(work, "NATGASMINI")
    ivp = pd.read_pickle(R4.cache(work, "ivp_NATGASMINI"))
    week_ends = [d1 for d1, _ in cmini.week_slots() if pd.Timestamp(R4.T2[0]) <= d1 <= pd.Timestamp(R4.T2[1])]
    ccyc = [c for c in cmini.cycles if c.expiry <= pd.Timestamp(R4.T2[1])]
    ncyc = [c for c in nmini.cycles if c.expiry <= pd.Timestamp(R4.T2[1])]
    per, caps = {}, {}
    for name, (s, k, w, e, f, pt, sl, tx) in CO.items():
        tr = E.run_variant(ccyc, s, k, w, e, f, pt, sl, tx, 10, "CRUDEOIL", 0.05, 0.01)
        per[name] = weekly_mtm(tr, ccyc, week_ends, 10, 0.05)
        caps[name] = float(np.mean([t["capital"] for t in tr]))
    tr = R2.run_variant(ncyc, "NATGASMINI", NB, ivp, 0.01)[0]
    per["N-B"] = weekly_mtm(tr, ncyc, week_ends, E.MULT["NATGASMINI"], E.TICK["NATGASMINI"])
    caps["N-B"] = float(np.mean([t["capital"] for t in tr]))
    out = {}
    for name, p in per.items():
        out[name] = {**describe(p), "avg_capital_per_lot": round(caps[name]),
                     "avg_week_pct_of_its_margin": round(float(p.mean()) / caps[name] * 100, 3)}
    core = sum(per[n] * lots for n, lots in CORE.items())
    out["core_on_10_lakh"] = describe(core, CAP)
    out["core_by_week"] = {str(k.date()): round(float(v)) for k, v in core.items()}
    for k, v in out.items():
        if k != "core_by_week":
            print(f"{k}: {v}")
    json.dump(out, open(os.path.join(work, "p4_reference.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
