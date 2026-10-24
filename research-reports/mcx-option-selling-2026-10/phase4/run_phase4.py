"""Phase 4 (AMENDMENT_A4.md): one trade a week, selling and buying, crude and natural gas; the target
is "at least 2% every week". Discovery -> frozen candidates -> one-time tests -> walk-forward.

    python run_phase4.py <work_dir> build
    python run_phase4.py <work_dir> discover
    python run_phase4.py <work_dir> test
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
import engine4 as E4  # noqa: E402
from search import bootstrap_p5  # noqa: E402

X2 = ("trade", "skip")
F3 = ("none", "ivp>=50", "ivp<=50")
ST3 = (None, 1.0, 2.0)
EX3 = ("week", "tp50sl50", "tp100sl50")
FAM = {
    "WS1": ("strangle", [(d, s, f, x) for d in (0.10, 0.15, 0.20, 0.25, 0.30) for s in ST3 for f in F3 for x in X2]),
    "WS2": ("straddle", [(s, f, x) for s in ST3 for f in F3 for x in X2]),
    "WS3": ("put", [(d, s, f, x) for d in (0.10, 0.15, 0.20, 0.30) for s in ST3 for f in F3 for x in X2]),
    "WS4": ("call", [(d, s, f, x) for d in (0.10, 0.15, 0.20, 0.30) for s in ST3 for f in F3 for x in X2]),
    "WS5": ("trendside", [(d, s, f, x) for d in (0.15, 0.25, 0.35) for s in ST3 for f in F3 for x in X2]),
    "WS6": ("condor", [(ds, dl, s, f, x) for ds, dl in ((0.20, 0.08), (0.25, 0.10), (0.30, 0.15))
                       for s in (None, 1.0) for f in F3 for x in X2]),
    "WS7": ("dh", [(f, x) for f in F3 for x in X2]),
    "WB1": ("lstraddle", [(f, e, x) for f in ("none", "ivp<=20", "ivp<=35", "iv<rv") for e in ("week", "tp50sl40") for x in X2]),
    "WB2": ("lstrangle", [(d, f, e, x) for d in (0.25, 0.15) for f in ("none", "ivp<=20", "ivp<=35")
                          for e in ("week", "tp100sl50") for x in X2]),
    "WB3": ("trend", [(d, e, x) for d in (0.50, 0.35, 0.20) for e in EX3 for x in X2]),
    "WB4": ("breakout", [(n, d, e, x) for n in (10, 20) for d in (0.50, 0.30) for e in EX3 for x in X2]),
    "WB5": ("momentum", [(th, d, e, x) for th in (0.02, 0.04) for d in (0.50, 0.30) for e in EX3 for x in X2]),
    "WB6": ("reversal", [(th, d, e, x) for th in (0.02, 0.04) for d in (0.50, 0.30) for e in EX3 for x in X2]),
    "WB7": ("lottery", [(lg, e, w) for lg in ("both", "call", "put") for e in ("week", "tp200") for w in ("all", "expiry")]),
    "WB8": ("report", [(s, x) for s in ("straddle", "strangle25") for x in X2]),
}
assert sum(len(v[1]) for k, v in FAM.items() if k.startswith("WS")) == 348   # AMENDMENT_A4's grid
assert sum(len(v[1]) for k, v in FAM.items() if k.startswith("WB")) == 146
SELLERS = {k for k in FAM if k.startswith("WS")}
FILT = {
    "none": lambda p, c, j: True,
    "ivp>=50": lambda p, c, j: bool(np.isfinite(p) and p >= 50),
    "ivp<=50": lambda p, c, j: bool(np.isfinite(p) and p <= 50),
    "ivp<=35": lambda p, c, j: bool(np.isfinite(p) and p <= 35),
    "ivp<=20": lambda p, c, j: bool(np.isfinite(p) and p <= 20),
    "iv<rv": lambda p, c, j: bool(np.isfinite(c.iv[j]) and np.isfinite(c.rv20[j]) and c.iv[j] < c.rv20[j]),
}
INSTS = ("CRUDEOILM", "NATGASMINI")
SRC = {"CRUDEOILM": ("CRUDEOIL", "CRUDEOILM"), "NATGASMINI": ("NATURALGAS", "NATGASMINI")}
START = {"CRUDEOILM": "2018-06-01", "NATGASMINI": "2022-03-01"}
DISC = {"CRUDEOILM": ("2020-01-01", "2024-05-31"), "NATGASMINI": ("2022-03-01", "2024-04-30")}
T1 = ("2018-06-01", "2019-12-31")
T2 = ("2024-06-01", "2026-10-31")
WF_YEARS = {"CRUDEOILM": [2022, 2023, 2024, 2025, 2026], "NATGASMINI": [2024, 2025, 2026]}
LAST = pd.Timestamp("2026-10-23")


def cache(work, name):
    return os.path.join(work, f"p4_{name}.pkl")


# ---------------------------------------------------------------------------- build
def build(work):
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    for inst, (parent, mini) in SRC.items():
        for tag, sym, a in (("parent", parent, START[inst]), ("mini", mini, "2024-06-01")):
            cyc = E.build_cycles(opt, fut, sym, sym, a, "2027-06-30", require_expiry=False)
            cyc = [c for c in cyc if c.dates[-1] == c.expiry or c.dates[-1] == LAST]      # finished, or live today
            pd.to_pickle(cyc, cache(work, f"{inst}_{tag}"))
            print(f"{inst} {tag}: {len(cyc)} cycles {cyc[0].expiry.date()}..{cyc[-1].expiry.date()}", flush=True)
        full = pd.read_pickle(cache(work, f"{inst}_parent"))
        pd.to_pickle(E2.iv_percentile(E2.front_iv_series(full)).to_dict(), cache(work, f"ivp_{inst}"))


def books(work, inst):
    ivp = pd.read_pickle(cache(work, f"ivp_{inst}"))
    return (E4.Book(pd.read_pickle(cache(work, f"{inst}_parent")), ivp, inst),
            E4.Book(pd.read_pickle(cache(work, f"{inst}_mini")), ivp, inst))


# ---------------------------------------------------------------------------- one week of one variant
def direction(kind, v, c, j0):
    F = c.F
    if kind == "trend":
        s10, s20 = c.sma10[j0], c.sma20[j0]
        if not (np.isfinite(s10) and np.isfinite(s20)):
            return None
        if F[j0] > s20 and s10 > s20:
            return "up"
        if F[j0] < s20 and s10 < s20:
            return "down"
        return None
    if kind == "breakout":
        n = v[0]
        if j0 < n:
            return None
        w = F[j0 - n:j0]
        w = w[np.isfinite(w)]
        if len(w) < n - 2:
            return None
        return "up" if F[j0] > w.max() else "down" if F[j0] < w.min() else None
    th = v[0]                                     # momentum / reversal: last week's futures return
    if j0 < 5 or not np.isfinite(F[j0 - 5]):
        return None
    r = F[j0] / F[j0 - 5] - 1
    d = "up" if r > th else "down" if r < -th else None
    if kind == "reversal" and d:
        d = "down" if d == "up" else "up"
    return d


def week_trade(fam, v, s, book, inst, slip):
    """(allowed, trade-or-None) for one week; `allowed` = the variant's own conditions permit a trade."""
    kind = FAM[fam][0]
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    c, j0, j1 = s.c, s.j0, s.j1
    p = book.ivp.get(s.d0, np.nan)

    def pick(cp, d):
        return book.pick(c, cp, j0, d)

    def run(legs, **kw):
        return E4.run_legs(c, legs, j0, j1, mult, family, tick, slip, **kw) if legs else None

    if kind == "lottery":
        if v[2] == "expiry" and not s.exp_in_week:
            return False, None
    elif v[-1] == "skip" and s.exp_in_week:
        return False, None
    if kind in ("strangle", "put", "call", "trendside"):
        d, stop, f = v[0], v[1], v[2]
        if not FILT[f](p, c, j0):
            return False, None
        if kind == "strangle":
            kc, kp = pick("CE", d), pick("PE", d)
            legs = [("CE", -1, kc), ("PE", -1, kp)] if kc and kp else None
        elif kind in ("put", "call"):
            cp = "PE" if kind == "put" else "CE"
            k = pick(cp, d)
            legs = [(cp, -1, k)] if k else None
        else:
            s20 = c.sma20[j0]
            if not np.isfinite(s20) or c.F[j0] == s20:
                return False, None
            cp = "PE" if c.F[j0] > s20 else "CE"
            k = pick(cp, d)
            legs = [(cp, -1, k)] if k else None
        return True, run(legs, stop=stop)
    if kind == "straddle":
        stop, f = v[0], v[1]
        if not FILT[f](p, c, j0):
            return False, None
        k = c.katm[j0]
        return True, run([("CE", -1, k), ("PE", -1, k)] if np.isfinite(k) else None, stop=stop)
    if kind == "condor":
        ds, dl, stop, f = v[0], v[1], v[2], v[3]
        if not FILT[f](p, c, j0):
            return False, None
        kcs, kps, kcl, kpl = pick("CE", ds), pick("PE", ds), pick("CE", dl), pick("PE", dl)
        ok = all((kcs, kps, kcl, kpl)) and kcl > kcs and kpl < kps
        return True, run([("CE", -1, kcs), ("PE", -1, kps), ("CE", +1, kcl), ("PE", +1, kpl)] if ok else None, stop=stop)
    if kind == "dh":
        if not FILT[v[0]](p, c, j0):
            return False, None
        return True, E4.run_dh_week(c, j0, j1, 10, mult, family, tick, slip)
    if kind == "lstraddle":
        f, e = v[0], v[1]
        if not FILT[f](p, c, j0):
            return False, None
        k = c.katm[j0]
        tp, sl = E4.EXITS[e]
        return True, run([("CE", +1, k), ("PE", +1, k)] if np.isfinite(k) else None, tp=tp, sl=sl)
    if kind == "lstrangle":
        d, f, e = v[0], v[1], v[2]
        if not FILT[f](p, c, j0):
            return False, None
        kc, kp = pick("CE", d), pick("PE", d)
        tp, sl = E4.EXITS[e]
        return True, run([("CE", +1, kc), ("PE", +1, kp)] if kc and kp else None, tp=tp, sl=sl)
    if kind in ("trend", "breakout", "momentum", "reversal"):
        dirn = direction(kind, v, c, j0)
        if dirn is None:
            return False, None
        d, e = (v[0], v[1]) if kind == "trend" else (v[1], v[2])
        cp = "CE" if dirn == "up" else "PE"
        k = pick(cp, d)
        tp, sl = E4.EXITS[e]
        return True, run([(cp, +1, k)] if k else None, tp=tp, sl=sl)
    if kind == "lottery":
        lg, e = v[0], v[1]
        sides = {"both": ("CE", "PE"), "call": ("CE",), "put": ("PE",)}[lg]
        ks = [pick(cp, 0.10) for cp in sides]
        tp, sl = E4.EXITS[e]
        return True, run([(cp, +1, k) for cp, k in zip(sides, ks)] if all(ks) else None, tp=tp, sl=sl)
    if kind == "report":
        if v[0] == "straddle":
            k = c.katm[j0]
            legs = [("CE", +1, k), ("PE", +1, k)] if np.isfinite(k) else None
        else:
            kc, kp = pick("CE", 0.25), pick("PE", 0.25)
            legs = [("CE", +1, kc), ("PE", +1, kp)] if kc and kp else None
        return True, run(legs)
    raise ValueError(kind)


def slots_for(fam, book, a, b):
    """The weeks of [a, b] (by each week's last trading day) with this family's entry slot, or None."""
    wk = [(d1, s) for d1, s in book.week_slots() if pd.Timestamp(a) <= d1 <= pd.Timestamp(b)]
    if FAM[fam][0] != "report":
        return wk
    rep = {tuple(d.isocalendar()[:2]): s for d, s in book.report_slots()}
    return [(d1, rep.get(tuple(d1.isocalendar()[:2]))) for d1, _ in wk]


def run_variant(fam, v, book, inst, a, b, slip):
    rows = []
    for d1, s in slots_for(fam, book, a, b):
        if s is None:
            rows.append({"week": d1, "allowed": False, "trade": None})
            continue
        allowed, t = week_trade(fam, v, s, book, inst, slip)
        rows.append({"week": d1, "allowed": allowed, "trade": t})
    return rows


def ret_all(rows):
    return np.array([r["trade"]["ret"] if r["trade"] is not None else 0.0 for r in rows], dtype=float)


def eligible(fam, m, m2):
    ok = (m["traded"] >= 3 and m["coverage"] >= 0.70 and m["net"] > 0 and m.get("pf", 0) >= 1.3
          and np.isfinite(m.get("t", np.nan)) and m["t"] >= 1.5 and m2["net"] > 0)
    if fam in SELLERS:
        ok = ok and m["worst_ret"] >= -0.30
    return bool(ok)


def pick_best(fam, book, inst, a, b):
    best, rows = None, []
    for v in FAM[fam][1]:
        r1 = run_variant(fam, v, book, inst, a, b, 0.01)
        r2 = run_variant(fam, v, book, inst, a, b, 0.02)
        m, m2 = E4.wstats(r1), E4.wstats(r2)
        ok = eligible(fam, m, m2)
        p5 = bootstrap_p5(ret_all(r1)) if ok else np.nan
        rows.append({"family": fam, "inst": inst, "variant": str(v), **{k: m.get(k) for k in (
            "weeks", "allowed", "traded", "coverage", "net", "pf", "t", "mean_ret", "pos_weeks", "ge2_weeks",
            "worst_ret", "maxdd", "avg_capital")}, "net_2x": m2["net"], "eligible": ok, "p5": p5})
        if ok and (best is None or p5 > best[0]):
            best = (p5, v)
    return best, rows


# ---------------------------------------------------------------------------- discovery
def discover(work):
    cands, allrows = [], []
    for inst in INSTS:
        parent, _ = books(work, inst)
        for fam in FAM:
            best, rows = pick_best(fam, parent, inst, *DISC[inst])
            allrows += rows
            n_el = sum(r["eligible"] for r in rows)
            top = max(rows, key=lambda r: r["mean_ret"] if r["mean_ret"] is not None else -9)
            line = (f"{inst} {fam} {FAM[fam][0]:<10} {n_el:>3}/{len(rows)} eligible | highest mean: {top['variant']} "
                    f"mean {top['mean_ret']:.2%}/wk, profitable weeks {top['pos_weeks']:.0%}, >=2% weeks {top['ge2_weeks']:.0%}")
            if best:
                r = next(x for x in rows if x["variant"] == str(best[1]))
                cands.append({"family": fam, "inst": inst, "variant": list(best[1]), "disc": r})
                line += (f"\n      -> FROZEN {best[1]}: n={r['traded']} net=Rs{r['net']:,.0f} pf={r['pf']:.2f} t={r['t']:.2f} "
                         f"mean {r['mean_ret']:.2%}/wk, profitable weeks {r['pos_weeks']:.0%}, >=2% weeks {r['ge2_weeks']:.0%}, "
                         f"worst {r['worst_ret']:.1%}")
            else:
                line += "\n      -> no eligible variant"
            print(line, flush=True)
    pd.DataFrame(allrows).to_csv(os.path.join(work, "p4_discovery.csv"), index=False)
    json.dump(cands, open(os.path.join(work, "p4_candidates.json"), "w"), indent=1, default=float)
    print(f"\n{len(cands)} candidates frozen")


# ---------------------------------------------------------------------------- tests
def tradeable(fam, s1, s2):
    ok = s1["traded"] > 0 and s1["net"] > 0 and s1.get("pf", 0) >= 1.15 and s2["net"] > 0
    if fam in SELLERS:
        ok = ok and s1["worst_ret"] >= -0.45
    return bool(ok)


def to_variant(raw):
    return tuple(x for x in raw)


def verdicts(fam, s1, s2):
    tr = tradeable(fam, s1, s2)
    return {"literal_every_week_2pct": bool(s1.get("ge2_weeks", 0) >= 1.0),
            "near_target": bool(tr and s1.get("mean_ret", 0) >= 0.02 and s1.get("pos_weeks", 0) >= 0.75),
            "tradeable": tr}


def keep(s):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}


def test(work):
    cands = json.load(open(os.path.join(work, "p4_candidates.json")))
    out = []
    for cd in cands:
        fam, inst = cd["family"], cd["inst"]
        v = to_variant(cd["variant"])
        parent, mini = books(work, inst)
        tests = {}
        if inst == "CRUDEOILM":
            tests["T1_2018_19"] = (parent, T1)
        tests["T2_2024_26_mini"] = (mini, T2)
        tests["T2_parent_crosscheck"] = (parent, T2)
        row = {"family": fam, "kind": FAM[fam][0], "inst": inst, "variant": str(v), "disc": cd["disc"]}
        ok_all = {"literal_every_week_2pct": True, "near_target": True, "tradeable": True}
        for name, (bk, (a, b)) in tests.items():
            r1 = run_variant(fam, v, bk, inst, a, b, 0.01)
            r2 = run_variant(fam, v, bk, inst, a, b, 0.02)
            s1, s2 = E4.wstats(r1), E4.wstats(r2)
            vd = verdicts(fam, s1, s2)
            row[name] = {**keep(s1), "net_2x": round(s2["net"]), **vd}
            if name != "T2_parent_crosscheck":
                for k in ok_all:
                    ok_all[k] &= vd[k]
            pd.DataFrame([{"week": r["week"], "allowed": r["allowed"], **(r["trade"] or {})} for r in r1]).to_csv(
                os.path.join(work, f"p4_weeks_{inst}_{fam}_{name}.csv"), index=False)
        wf = []
        for Y in WF_YEARS[inst]:
            a0 = DISC[inst][0]
            b0 = f"{Y - 1}-12-31"
            if len([1 for d1, _ in parent.week_slots() if pd.Timestamp(a0) <= d1 <= pd.Timestamp(b0)]) < 60:
                continue
            best, _ = pick_best(fam, parent, inst, a0, b0)
            if best is None:
                wf.append({"year": Y, "pick": None, "net": 0.0, "mean_ret": 0.0})
                continue
            st = E4.wstats(run_variant(fam, best[1], parent, inst, f"{Y}-01-01", f"{Y}-12-31", 0.01))
            wf.append({"year": Y, "pick": str(best[1]), "net": round(st["net"]), "mean_ret": round(st["mean_ret"], 4),
                       "pos_weeks": round(st["pos_weeks"], 3)})
        row["walkforward"] = wf
        row["walkforward_total"] = round(sum(w["net"] for w in wf))
        row["PASSED"] = ok_all
        out.append(row)
        print(f"\n{inst} {fam} {FAM[fam][0]} {v} -> tradeable {'PASS' if ok_all['tradeable'] else 'fail'} | "
              f"near-target {'PASS' if ok_all['near_target'] else 'fail'} | literal {'PASS' if ok_all['literal_every_week_2pct'] else 'fail'}")
        for name in tests:
            s = row[name]
            print(f"   {name}: weeks {s['weeks']} traded {s['traded']} net Rs{s['net']:,.0f} pf {s.get('pf', 0):.2f} "
                  f"mean {s['mean_ret']:.2%}/wk profitable {s['pos_weeks']:.0%} >=2% {s['ge2_weeks']:.0%} "
                  f"worst {s.get('worst_ret', 0):.1%} 2x Rs{s['net_2x']:,} f* {s.get('f_star', float('nan')):.2f}")
        print(f"   walk-forward: {[(w['year'], w['net']) for w in wf]} total {row['walkforward_total']}", flush=True)
    json.dump(out, open(os.path.join(work, "p4_results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    {"build": build, "discover": discover, "test": test}[sys.argv[2]](sys.argv[1])
