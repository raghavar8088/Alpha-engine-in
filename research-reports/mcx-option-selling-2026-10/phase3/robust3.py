"""Phase 3 follow-up (after the one-time tests; nothing here selects or re-tunes a strategy):
G2 robustness, why C-E weakened in 2018-19, T1 trade lists of the earlier passers, and the Rs10 lakh
portfolios on both test periods.

    python robust3.py <work_dir>               (everything)
    python robust3.py <work_dir> portfolios    (recompute only the portfolio section)
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
import engine2 as E2  # noqa: E402
import engine3 as E3  # noqa: E402
import run_phase2 as R2  # noqa: E402
import run_phase3 as R3  # noqa: E402

CAP = 1_000_000
G2 = (50, 10)
NG = "NATGASMINI"
LAST30 = pd.Timestamp("2026-09-23")
CO = {
    "CO-1": dict(struct="shortput", k=0.5, w=0.0, entry=15, filt="ivrv", pt=None, sl=2.0, texit=0),
    "CO-2": dict(struct="trend20", k=1.0, w=0.0, entry=15, filt="ivrv110", pt=None, sl=1.0, texit=1),
    "CO-3": dict(struct="trend20", k=0.5, w=0.0, entry=10, filt="ivrv110", pt=None, sl=2.0, texit=0),
}
NB = ("dstrangle", 0.10, 10, ("le", 50), None)


def cap(t):
    return t["capital"] + t.get("hedge_margin_peak", 0.0)


def st(tr):
    return R3.st(tr)


def by_year(tr):
    out = {}
    for t in tr:
        out.setdefault(int(pd.Timestamp(t["expiry"]).year), []).append(t["pnl"])
    return {y: round(sum(p)) for y, p in sorted(out.items())}


def g2_run(front, ivpct, v=G2, slip=0.01, lots=10, band=1, sel="le"):
    out = []
    for c in front:
        j0 = E.entry_index(c, v[1])
        if j0 is None:
            continue
        p = ivpct.get(c.dates[j0], np.nan)
        if sel == "le" and not (np.isfinite(p) and p <= v[0]):
            continue
        if sel == "gt" and not (np.isfinite(p) and p > v[0]):
            continue
        k = c.katm[j0]
        if not np.isfinite(k):
            continue
        t = E3.run_dh(c, j0, [("CE", k), ("PE", k)], lots, E.MULT[NG], E.FAMILY[NG], E.TICK[NG], slip, band)
        if t:
            t["ivpct"] = p
            out.append(t)
    return out


def co_run(cycles, name, slip=0.01):
    r = CO[name]
    return E.run_variant(cycles, r["struct"], r["k"], r["w"], r["entry"], r["filt"], r["pt"], r["sl"], r["texit"],
                         10, "CRUDEOIL", 0.05, slip)


def delta_run(cycles, struct, d, e, slip=0.01):
    out = []
    for c in cycles:
        j0 = E.entry_index(c, e)
        legs = E2.legs_delta(c, struct, d, j0) if j0 is not None else None
        t = E.run_trade(c, legs, j0, 10, "CRUDEOIL", 0.05, slip, None, None, 0) if legs else None
        if t:
            out.append(t)
    return out


def ce_run(cycles, lots=10, slip=0.01, with_rv=False):
    out = []
    for c in cycles:
        j0 = E.entry_index(c, 10)
        if j0 is None:
            continue
        t = E2.run_dh_straddle(c, j0, lots, 10, "CRUDEOIL", 0.05, slip)
        if not t:
            continue
        if with_rv:
            f = np.array(c.F[j0:], dtype=float)
            r = np.diff(np.log(f[np.isfinite(f)]))
            t["rv_hold"] = float(np.sqrt(252 * np.mean(r * r))) if len(r) else np.nan
        out.append(t)
    return out


def g2_section(work):
    ivpct = pd.read_pickle(R3.cache(work, "ivpct_NATGASMINI"))
    mf, _ = R3.load(work, NG, "mini")
    pf, _ = R3.load(work, NG, "parent")
    t2 = R3.sub(mf, *R3.T2)
    base = g2_run(t2, ivpct)
    ref, _ = R3.run_one("G2", G2, t2, {}, NG, ivpct, 0.01)
    assert abs(sum(t["pnl"] for t in base) - sum(t["pnl"] for t in ref)) < 1, "g2_run must reproduce run_one"
    rep = {"test_T2_mini": st(base), "by_year_T2": by_year(base)}
    best = max(base, key=lambda t: t["pnl"])
    rep["T2_without_best_trade"] = round(sum(t["pnl"] for t in base) - best["pnl"])
    rep["best_trade"] = {"expiry": str(best["expiry"].date()), "pnl": round(best["pnl"])}
    rep["neighbours_T2"] = {str(v): st(g2_run(t2, ivpct, v)) for v in ((50, 15), (40, 10), (40, 15))}
    rep["entry_shift_T2"] = {str(e): st(g2_run(t2, ivpct, (50, e))) for e in (8, 12)}
    rep["hedge_band2_T2"] = st(g2_run(t2, ivpct, band=2))
    rep["lots_T2_per10"] = {f"{n} lots": round(sum(t["pnl"] for t in g2_run(t2, ivpct, lots=n)) * 10 / n) for n in (5, 20)}
    keep = E2.FUT_SLIP
    E2.FUT_SLIP = keep * 2
    rep["futures_slip_2x_T2"] = st(g2_run(t2, ivpct))
    rep["futures_and_option_slip_2x_T2"] = st(g2_run(t2, ivpct, slip=0.02))
    E2.FUT_SLIP = keep
    rep["same_trade_when_ivpct_above_50_T2"] = st(g2_run(t2, ivpct, sel="gt"))
    rep["same_trade_unfiltered_T2"] = st(g2_run(t2, ivpct, sel="all"))
    full = R3.sub(pf, "2022-03-01", "2026-10-31")
    rep["parent_2022_26_by_year"] = by_year(g2_run(full, ivpct))
    rep["parent_2022_26_unfiltered_by_year"] = by_year(g2_run(full, ivpct, sel="all"))
    rep["capital_incl_hedge_margin_T2"] = {"avg": round(float(np.mean([t["capital"] for t in base]))),
                                           "max": round(float(np.max([t["capital"] for t in base]))),
                                           "avg_peak_hedge_lots": round(float(np.mean([t["max_hedge_lots"] for t in base])), 1)}
    rep["trades_T2"] = [{"expiry": str(t["expiry"].date()), "entry": str(t["entry"].date()), "ivpct": round(float(t["ivpct"]), 1),
                         "iv0": round(float(t["iv0"]), 3), "pnl": round(t["pnl"]), "capital": round(t["capital"]),
                         "max_hedge_lots": t["max_hedge_lots"]} for t in base]
    pd.DataFrame(base).to_csv(os.path.join(work, "p3_G2_T2_trades.csv"), index=False)
    return rep, base


def ce_section(work):
    pf, _ = R3.load(work, "CRUDEOILM", "parent")
    mf, _ = R3.load(work, "CRUDEOILM", "mini")
    rows, per = [], {}
    for label, cyc in (("T1 2018-19 (parent)", R3.sub(pf, *R3.T1)),
                       ("discovery 2020-24 (parent)", R3.sub(pf, "2020-01-01", "2024-05-31")),
                       ("T2 2024-26 (mini)", R3.sub(mf, *R3.T2))):
        tr = ce_run(cyc, with_rv=True)
        per[label] = tr
        iv = np.array([t["iv0"] for t in tr])
        rv = np.array([t["rv_hold"] for t in tr])
        pnl = np.array([t["pnl"] for t in tr])
        gap = iv - rv
        fees = np.array([t["fees"] for t in tr])
        rows.append({"period": label, "n": len(tr), "net_per10": round(float(pnl.sum())),
                     "avg_per_cycle": round(float(pnl.mean())), "pf": st(tr)["pf"],
                     "mean_iv_entry": round(float(np.nanmean(iv)), 3), "mean_rv_hold": round(float(np.nanmean(rv)), 3),
                     "mean_iv_minus_rv": round(float(np.nanmean(gap)), 3), "share_iv_above_rv": round(float(np.nanmean(gap > 0)), 2),
                     "corr_gap_pnl": round(float(pd.Series(gap).corr(pd.Series(pnl))), 2),
                     "avg_fees_per_cycle": round(float(fees.mean()))})
    t1 = per["T1 2018-19 (parent)"]
    pd.DataFrame(t1).to_csv(os.path.join(work, "p3_T1_trades_C-E.csv"), index=False)
    return {"by_period": rows, "T1_by_year": by_year(t1),
            "T1_trades": [{"expiry": str(t["expiry"].date()), "iv0": round(float(t["iv0"]), 3), "rv_hold": round(float(t["rv_hold"]), 3),
                           "pnl": round(t["pnl"]), "fees": round(t["fees"])} for t in t1]}


def t1_lists(work):
    pf, _ = R3.load(work, "CRUDEOILM", "parent")
    t1 = R3.sub(pf, *R3.T1)
    out = {}
    for n in CO:
        out[n] = co_run(t1, n)
    out["C-B"] = delta_run(t1, "dput", 0.15, 5)
    out["C-C"] = delta_run(t1, "dstrangle", 0.15, 5)
    for n, tr in out.items():
        pd.DataFrame(tr).to_csv(os.path.join(work, f"p3_T1_trades_{n}.csv"), index=False)
    return {n: {"stats": st(tr), "by_year": by_year(tr)} for n, tr in out.items()}


def book(parts, a, b):
    rows = []
    for name, tr, n in parts:
        for t in tr:
            rows.append({"name": name, "entry": pd.Timestamp(t["entry"]), "exit": pd.Timestamp(t["exit"]),
                         "pnl": t["pnl"] * n, "capital": cap(t) * n})
    df = pd.DataFrame(rows).sort_values("exit").reset_index(drop=True)
    months = pd.period_range(pd.Timestamp(a), min(pd.Timestamp(b), df.exit.max()), freq="M")
    mon = df.groupby(df.exit.dt.to_period("M")).pnl.sum().reindex(months, fill_value=0.0)
    eq = np.concatenate([[0.0], df.pnl.cumsum().to_numpy()])
    meq = np.concatenate([[0.0], mon.cumsum().to_numpy()])
    days = pd.bdate_range(df.entry.min(), df.exit.max())
    used = [float(df.capital[(df.entry <= d) & (df.exit >= d)].sum()) for d in days]
    return {"net": round(float(df.pnl.sum())), "pct_of_10L": round(float(df.pnl.sum()) / CAP * 100, 1), "months": len(months),
            "avg_per_month": round(float(mon.mean())), "months_positive": int((mon > 0).sum()),
            "worst_month": round(float(mon.min())), "worst_month_at": str(mon.idxmin()),
            "max_drawdown_trade_by_trade": round(float((np.maximum.accumulate(eq) - eq).max())),
            "max_drawdown_month_end": round(float((np.maximum.accumulate(meq) - meq).max())),
            "peak_capital_in_use": round(max(used)), "avg_capital_in_use": round(float(np.mean(used))),
            "last_30_days": round(float(df.pnl[df.exit >= LAST30].sum())),
            "by_strategy": {k: round(float(v)) for k, v in df.groupby("name").pnl.sum().items()},
            "by_year": {int(k): round(float(v)) for k, v in df.groupby(df.exit.dt.year).pnl.sum().items()},
            "by_strategy_year": {f"{k[0]} {k[1]}": round(float(v)) for k, v in df.groupby(["name", df.exit.dt.year]).pnl.sum().items()}}


def portfolios(work, g2_t2):
    cyc = R2.load(work)
    ivp = cyc[(NG, "ivpct")]
    ivpct3 = pd.read_pickle(R3.cache(work, "ivpct_NATGASMINI"))
    cm, nm = R3.sub(cyc[("CRUDEOILM", "mini")], *R3.T2), R3.sub(cyc[(NG, "mini")], *R3.T2)
    pf, _ = R3.load(work, "CRUDEOILM", "parent")
    t1 = R3.sub(pf, *R3.T1)
    t2 = {"CO-1": co_run(cm, "CO-1"), "CO-2": co_run(cm, "CO-2"), "C-E5": ce_run(cm, lots=5),
          "N-B": R2.run_variant(nm, NG, NB, ivp, 0.01)[0], "G2-5": g2_run(nm, ivpct3, lots=5)}
    t1r = {"CO-1": co_run(t1, "CO-1"), "CO-2": co_run(t1, "CO-2"), "C-E5": ce_run(t1, lots=5)}
    per_lot = {k: {"T2": st(v)} for k, v in t2.items()}
    for k, v in t1r.items():
        per_lot[k]["T1"] = st(v)
    a = [("C-E 5 lots", t2["C-E5"], 1), ("CO-1 3 lots", t2["CO-1"], 3), ("CO-2 3 lots", t2["CO-2"], 3), ("N-B 5 lots", t2["N-B"], 5)]
    b = [("CO-1 3 lots", t2["CO-1"], 3), ("CO-2 3 lots", t2["CO-2"], 3), ("N-B 5 lots", t2["N-B"], 5), ("G2 5 lots", t2["G2-5"], 1)]
    a1 = [("C-E 5 lots", t1r["C-E5"], 1), ("CO-1 3 lots", t1r["CO-1"], 3), ("CO-2 3 lots", t1r["CO-2"], 3)]
    b1 = [("CO-1 3 lots", t1r["CO-1"], 3), ("CO-2 3 lots", t1r["CO-2"], 3)]
    corr = {}
    for k in ("N-B", "G2-5", "CO-1", "CO-2", "C-E5"):
        s = pd.Series({pd.Timestamp(t["expiry"]): t["pnl"] for t in t2[k]})
        corr[k] = s
    return {"per_strategy": per_lot,
            "A_phase2_portfolio_T2": book(a, *R3.T2), "A_phase2_portfolio_T1_crude_part": book(a1, *R3.T1),
            "B_revised_T2": book(b, *R3.T2), "B_revised_T1_crude_part": book(b1, *R3.T1),
            "B_without_G2_T2": book(b[:3], *R3.T2),
            "T2_per_expiry_corr": pd.DataFrame(corr).corr().round(2).to_dict()}


def main(work, only=None):
    if only == "portfolios":
        path = os.path.join(work, "p3_robust.json")
        out = json.load(open(path))
        out["portfolios"] = portfolios(work, None)
        for k, v in out["portfolios"].items():
            print(f"  {k}: {v}")
        json.dump(out, open(path, "w"), indent=1, default=str)
        return
    out = {}
    out["G2"], g2_t2 = g2_section(work)
    print("=== G2 robustness")
    for k, v in out["G2"].items():
        if k != "trades_T2":
            print(f"  {k}: {v}")
    for t in out["G2"]["trades_T2"]:
        print("   ", t)
    out["C-E_diagnosis"] = ce_section(work)
    print("\n=== C-E (10 lots): volatility premium by period")
    for r in out["C-E_diagnosis"]["by_period"]:
        print("  ", r)
    print("   T1 by year:", out["C-E_diagnosis"]["T1_by_year"])
    out["earlier_T1"] = t1_lists(work)
    print("\n=== earlier passers on T1, by year")
    for k, v in out["earlier_T1"].items():
        print(f"   {k}: {v['by_year']}  {v['stats']}")
    out["portfolios"] = portfolios(work, g2_t2)
    print("\n=== Rs10 lakh portfolios")
    for k, v in out["portfolios"].items():
        print(f"  {k}: {v}")
    json.dump(out, open(os.path.join(work, "p3_robust.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
