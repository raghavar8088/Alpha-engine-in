"""Phase 3 (AMENDMENT_A3.md): discovery -> frozen candidates -> tests T1 (crude 2018-19, untouched) and
T2 (Jun 2024 - Oct 2026 minis), walk-forward per family, and a T1 re-test of earlier passers.

    python run_phase3.py <work_dir> build
    python run_phase3.py <work_dir> discover
    python run_phase3.py <work_dir> test
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2")):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import engine2 as E2  # noqa: E402
import engine3 as E3  # noqa: E402
from search import bootstrap_p5, metrics  # noqa: E402

FAM = {
    "K1": ("CRUDEOILM", "cal", [(k, e, tx) for k in ("straddle", "put", "call") for e in (15, 10, 5) for tx in (0, 1)]),
    "K2": ("CRUDEOILM", "ratio", [(cp, a, b, e, sl) for cp in ("PE", "CE") for a, b in ((0.30, 0.15), (0.25, 0.10)) for e in (15, 10, 5) for sl in (None, 1.0)]),
    "K3": ("CRUDEOILM", "dhstrangle", [(d, e) for d in (0.25, 0.35) for e in (20, 15, 10)]),
    "K4": ("CRUDEOILM", "dhband", [(b, e) for b in (2, 3) for e in (15, 10, 5)]),
    "K5": ("CRUDEOILM", "roll", [(d0, t, e) for d0 in (0.15, 0.20) for t in (0.30, 0.40) for e in (15, 10)]),
    "K6": ("CRUDEOILM", "expweek", [(s, d, e) for s in ("dcall", "dstrangle") for d in (0.10, 0.15, 0.20) for e in (3, 2)]),
    "G1": ("NATGASMINI", "cal", [(k, e, tx) for k in ("straddle", "put", "call") for e in (15, 10, 5) for tx in (0, 1)]),
    "G2": ("NATGASMINI", "calmdh", [(th, e) for th in (50, 40) for e in (15, 10)]),
    "G3": ("NATGASMINI", "season", [(d, e, sl) for d in (0.10, 0.15, 0.20) for e in (15, 10) for sl in (None, 1.0)]),
    "G4": ("NATGASMINI", "roll", [(d0, t, e) for d0 in (0.15, 0.20) for t in (0.30, 0.40) for e in (15, 10)]),
    "G5": ("NATGASMINI", "ratio", [(cp, a, b, e, sl) for cp in ("PE", "CE") for a, b in ((0.30, 0.15), (0.25, 0.10)) for e in (15, 10, 5) for sl in (None, 1.0)]),
}
assert sum(len(v[2]) for v in FAM.values()) == 140
SRC = {"CRUDEOILM": ("CRUDEOIL", "CRUDEOILM"), "NATGASMINI": ("NATURALGAS", "NATGASMINI")}
DISC = {"CRUDEOILM": ("2020-01-01", "2024-05-31"), "NATGASMINI": ("2022-03-01", "2024-04-30")}
T1 = ("2018-06-01", "2019-12-31")
T2 = ("2024-06-01", "2026-10-31")
WF_YEARS = {"CRUDEOILM": [2022, 2023, 2024, 2025, 2026], "NATGASMINI": [2024, 2025, 2026]}


def cache(work, name):
    return os.path.join(work, f"p3_{name}.pkl")


def build(work):
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    for inst, (parent, mini) in SRC.items():
        start = "2018-06-01" if inst == "CRUDEOILM" else "2022-03-01"
        for tag, sym, a in (("parent", parent, start), ("mini", mini, "2024-06-01")):
            front = E.build_cycles(opt, fut, sym, sym, a, "2026-10-31")
            back = E.build_cycles(opt, fut, sym, sym, a, "2027-02-28", require_expiry=False)
            pd.to_pickle(front, cache(work, f"{inst}_{tag}_front"))
            pd.to_pickle(back, cache(work, f"{inst}_{tag}_back"))
            print(f"{inst} {tag}: {len(front)} front cycles ({front[0].expiry.date()}..{front[-1].expiry.date()}), {len(back)} back", flush=True)
    full = pd.read_pickle(cache(work, "NATGASMINI_parent_front"))
    pd.to_pickle(E2.iv_percentile(E2.front_iv_series(full)).to_dict(), cache(work, "ivpct_NATGASMINI"))


def load(work, inst, tag):
    front = pd.read_pickle(cache(work, f"{inst}_{tag}_front"))
    back = sorted(pd.read_pickle(cache(work, f"{inst}_{tag}_back")), key=lambda c: c.expiry)
    nxt = {}
    for c in front:
        later = [b for b in back if b.expiry > c.expiry]
        nxt[c.expiry] = later[0] if later else None
    return front, nxt


def run_one(fam, v, front, nxt, inst, ivpct, slip):
    kind = FAM[fam][1]
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    trades, den = [], 0
    for c in front:
        e = {"cal": v[1] if kind == "cal" else None, "ratio": v[3] if kind == "ratio" else None,
             "dhstrangle": v[1] if kind == "dhstrangle" else None, "dhband": v[1] if kind == "dhband" else None,
             "roll": v[2] if kind == "roll" else None, "expweek": v[2] if kind == "expweek" else None,
             "calmdh": v[1] if kind == "calmdh" else None, "season": v[1] if kind == "season" else None}[kind]
        j0 = E.entry_index(c, e)
        if j0 is None:
            continue
        if kind == "calmdh":
            p = ivpct.get(c.dates[j0], np.nan)
            if not (np.isfinite(p) and p <= v[0]):
                continue
        if kind == "season" and not (4 <= c.expiry.month <= 10):
            continue
        den += 1
        t = None
        if kind == "cal":
            cb = nxt.get(c.expiry)
            t = E3.run_calendar(c, cb, j0, v[0], mult, family, tick, slip, v[2]) if cb is not None else None
        elif kind == "ratio":
            t = E3.run_ratio(c, j0, v[0], v[1], v[2], mult, family, tick, slip, v[4])
        elif kind == "dhstrangle":
            kc, kp = E2.pick_delta(c, "CE", j0, v[0]), E2.pick_delta(c, "PE", j0, v[0])
            t = E3.run_dh(c, j0, [("CE", kc), ("PE", kp)], 10, mult, family, tick, slip) if kc and kp else None
        elif kind in ("dhband", "calmdh"):
            k = c.katm[j0]
            band = v[0] if kind == "dhband" else 1
            t = E3.run_dh(c, j0, [("CE", k), ("PE", k)], 10, mult, family, tick, slip, band) if np.isfinite(k) else None
        elif kind == "roll":
            t = E3.run_roll(c, j0, v[0], v[1], 2, mult, family, tick, slip)
        elif kind == "expweek":
            legs = E2.legs_delta(c, v[0], v[1], j0)
            t = E.run_trade(c, legs, j0, mult, family, tick, slip, None, None, 0) if legs else None
        elif kind == "season":
            legs = E2.legs_delta(c, "dstrangle", v[0], j0)
            t = E.run_trade(c, legs, j0, mult, family, tick, slip, None, v[2], 0) if legs else None
        if t is not None:
            trades.append(t)
    return trades, den


def eligible(m, m2):
    return (m.get("n", 0) >= 3 and m["coverage"] >= 0.70 and m["net"] > 0 and m["pf"] >= 1.3 and m["t"] >= 1.5
            and m2.get("net", -1) > 0 and m["worst_roc"] >= -0.30)


def pick(fam, front, nxt, inst, ivpct):
    best, rows = None, []
    for v in FAM[fam][2]:
        tr, den = run_one(fam, v, front, nxt, inst, ivpct, 0.01)
        tr2, _ = run_one(fam, v, front, nxt, inst, ivpct, 0.02)
        m, m2 = metrics(tr, den), metrics(tr2, den)
        ok = eligible(m, m2)
        p5 = bootstrap_p5(np.array([t["roc"] for t in tr])) if ok else np.nan
        rows.append({"family": fam, "variant": str(v), **{k: m.get(k) for k in ("n", "coverage", "net", "pf", "t", "worst_roc")},
                     "net_2x": m2.get("net"), "eligible": ok, "p5": p5})
        if ok and (best is None or p5 > best[0]):
            best = (p5, v)
    return best, rows


def sub(front, a, b):
    return [c for c in front if pd.Timestamp(a) <= c.expiry <= pd.Timestamp(b)]


def discover(work):
    ivpct = pd.read_pickle(cache(work, "ivpct_NATGASMINI"))
    cands, allrows = [], []
    for fam, (inst, kind, grid) in FAM.items():
        front, nxt = load(work, inst, "parent")
        d = sub(front, *DISC[inst])
        best, rows = pick(fam, d, nxt, inst, ivpct)
        allrows += rows
        n_el = sum(r["eligible"] for r in rows)
        if best:
            r = next(x for x in rows if x["variant"] == str(best[1]))
            cands.append({"family": fam, "inst": inst, "variant": list(best[1]), "disc": r})
            print(f"{fam} {kind:<10} ({inst}): {n_el}/{len(rows)} eligible -> best {best[1]} | n={r['n']} net=Rs{r['net']:,.0f} "
                  f"pf={r['pf']:.2f} t={r['t']:.2f} worst={r['worst_roc']:.1%} p5={r['p5']:.2%}", flush=True)
        else:
            top = max(rows, key=lambda x: x["net"] if x["net"] is not None else -1e12)
            print(f"{fam} {kind:<10} ({inst}): 0/{len(rows)} eligible -> NO CANDIDATE (best net Rs{(top['net'] or 0):,.0f}, "
                  f"pf {(top['pf'] or 0):.2f}, t {(top['t'] or 0):.2f}, worst {(top['worst_roc'] or 0):.1%})", flush=True)
    pd.DataFrame(allrows).to_csv(os.path.join(work, "p3_discovery.csv"), index=False)
    json.dump(cands, open(os.path.join(work, "p3_candidates.json"), "w"), indent=1, default=float)
    print(f"\n{len(cands)} candidates")


def st(tr):
    if not tr:
        return {"n": 0, "net": 0.0}
    p = np.array([t["pnl"] for t in tr])
    r = np.array([t["roc"] for t in tr])
    eq = np.concatenate([[0], np.cumsum(p)])
    return {"n": len(p), "net": round(float(p.sum())), "win": round(float((p > 0).mean()), 3),
            "pf": round(float(p[p > 0].sum() / -p[p < 0].sum()), 2) if (p < 0).any() else float("inf"),
            "worst": round(float(p.min())), "worst_roc": round(float(r.min()), 3),
            "maxdd": round(float((np.maximum.accumulate(eq) - eq).max())),
            "avg_capital": round(float(np.mean([t["capital"] for t in tr])))}


def passes(s1, s2):
    return s1["n"] > 0 and s1["net"] > 0 and s1["pf"] >= 1.15 and s2["net"] > 0 and s1["worst_roc"] >= -0.45


def to_variant(fam, raw):
    out = []
    for x in raw:
        out.append(tuple(x) if isinstance(x, list) else x)
    return tuple(out)


def test(work):
    ivpct = pd.read_pickle(cache(work, "ivpct_NATGASMINI"))
    cands = json.load(open(os.path.join(work, "p3_candidates.json")))
    results = []
    for cd in cands:
        fam, inst = cd["family"], cd["inst"]
        v = to_variant(fam, cd["variant"])
        if FAM[fam][1] in ("dhband",) or FAM[fam][1] in ("calmdh",):
            v = (int(v[0]), int(v[1]))
        pf_front, pf_nxt = load(work, inst, "parent")
        mf, mn = load(work, inst, "mini")
        row = {"family": fam, "kind": FAM[fam][1], "inst": inst, "variant": str(v), "disc": cd["disc"]}
        tests = {}
        if inst == "CRUDEOILM":
            t1 = sub(pf_front, *T1)
            tests["T1_2018_19"] = (t1, pf_nxt)
        tests["T2_2024_26_mini"] = (sub(mf, *T2), mn)
        tests["T2_parent_crosscheck"] = (sub(pf_front, *T2), pf_nxt)
        ok_all = True
        for name, (fr, nx) in tests.items():
            tr1, _ = run_one(fam, v, fr, nx, inst, ivpct, 0.01)
            tr2, _ = run_one(fam, v, fr, nx, inst, ivpct, 0.02)
            s1, s2 = st(tr1), st(tr2)
            p = passes(s1, s2)
            row[name] = {**s1, "net_2x": s2["net"], "pass": p}
            if name != "T2_parent_crosscheck":
                ok_all &= p
            pd.DataFrame(tr1).to_csv(os.path.join(work, f"p3_trades_{fam}_{name}.csv"), index=False)
        # walk-forward per family (cycles from 2020 for crude, so T1 stays untouched)
        years = WF_YEARS[inst]
        base = [c for c in pf_front if c.expiry >= pd.Timestamp(DISC[inst][0])]
        wf = []
        for Y in years:
            train = [c for c in base if c.expiry.year < Y]
            if len(train) < 20:
                continue
            best, _ = pick(fam, train, pf_nxt, inst, ivpct)
            if best is None:
                wf.append({"year": Y, "pick": None, "net": 0.0, "n": 0})
                continue
            tr, _ = run_one(fam, best[1], [c for c in base if c.expiry.year == Y], pf_nxt, inst, ivpct, 0.01)
            wf.append({"year": Y, "pick": str(best[1]), "net": round(float(sum(t["pnl"] for t in tr))), "n": len(tr)})
        row["walkforward"] = wf
        row["walkforward_total"] = round(sum(w["net"] for w in wf))
        row["PASSED"] = bool(ok_all)
        results.append(row)
        print(f"\n{fam} {FAM[fam][1]} {v} ({inst}) -> {'PASS' if ok_all else 'fail'}")
        for name in tests:
            print(f"   {name}: {row[name]}")
        print(f"   walk-forward: {[(w['year'], w['net']) for w in wf]} total {row['walkforward_total']}")
    # earlier passers, ONCE on T1 (crude 2018-19)
    print("\n=== earlier crude passers on T1 (2018-19, never seen):")
    pf_front, pf_nxt = load(work, "CRUDEOILM", "parent")
    t1 = sub(pf_front, *T1)
    earlier = {
        "CO-1": dict(struct="shortput", k=0.5, w=0.0, entry=15, filt="ivrv", pt=None, sl=2.0, texit=0),
        "CO-2": dict(struct="trend20", k=1.0, w=0.0, entry=15, filt="ivrv110", pt=None, sl=1.0, texit=1),
        "CO-3": dict(struct="trend20", k=0.5, w=0.0, entry=10, filt="ivrv110", pt=None, sl=2.0, texit=0),
    }
    retest = {}
    for name, r in earlier.items():
        s = {}
        for slip in (0.01, 0.02):
            tr = E.run_variant(t1, r["struct"], r["k"], r["w"], r["entry"], r["filt"], r["pt"], r["sl"], r["texit"], 10, "CRUDEOIL", 0.05, slip)
            s[slip] = st(tr)
        retest[name] = {**s[0.01], "net_2x": s[0.02]["net"], "pass": passes(s[0.01], s[0.02])}
    for name, (struct, d, e) in {"C-B": ("dput", 0.15, 5), "C-C": ("dstrangle", 0.15, 5)}.items():
        s = {}
        for slip in (0.01, 0.02):
            tr = []
            for c in t1:
                j0 = E.entry_index(c, e)
                legs = E2.legs_delta(c, struct, d, j0) if j0 is not None else None
                t = E.run_trade(c, legs, j0, 10, "CRUDEOIL", 0.05, slip, None, None, 0) if legs else None
                if t:
                    tr.append(t)
            s[slip] = st(tr)
        retest[name] = {**s[0.01], "net_2x": s[0.02]["net"], "pass": passes(s[0.01], s[0.02])}
    s = {}
    for slip in (0.01, 0.02):
        tr = [t for t in (E2.run_dh_straddle(c, E.entry_index(c, 10), 10, 10, "CRUDEOIL", 0.05, slip)
                          for c in t1 if E.entry_index(c, 10) is not None) if t]
        s[slip] = st(tr)
    retest["C-E (10 lots)"] = {**s[0.01], "net_2x": s[0.02]["net"], "pass": passes(s[0.01], s[0.02])}
    for k, v in retest.items():
        print(f"   {k}: {'PASS' if v['pass'] else 'FAIL'} {v}")
    json.dump({"phase3": results, "earlier_on_T1": retest}, open(os.path.join(work, "p3_results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    {"build": build, "discover": discover, "test": test}[sys.argv[2]](sys.argv[1])
