"""Phase 5 (AMENDMENT_A5.md): the transfer test (Part A) and three new families (Part B) across every
MCX option market.

    python run_phase5.py specs    <data5> <work5>          contract multipliers + ticks, checked
    python run_phase5.py build_energy <work4> <work5>      crude / natural-gas cycles with opens
    python run_phase5.py build_metals <work5>              metal cycles with opens, IV percentiles
    python run_phase5.py discover <work5>                  Part B on crude Jan 2020 - May 2024
    python run_phase5.py test     <work5>                  every frozen rule once on every market
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import statistics
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "phase4"), HERE):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import engine2 as E2  # noqa: E402
import engine4 as E4  # noqa: E402
import engine5 as E5  # noqa: E402
import run_phase2 as R2  # noqa: E402
import run_phase4 as R4  # noqa: E402
from search import bootstrap_p5  # noqa: E402

METALS = ("GOLD", "SILVER", "COPPER", "ZINC", "NICKEL")
CROSS = ("GOLDM", "SILVERM")
LAST = pd.Timestamp("2026-10-23")
END = "2026-10-31"
DISC = ("2020-01-01", "2024-05-31")
T1, T2 = ("2018-06-01", "2019-12-31"), ("2024-06-01", "2026-10-31")
NG_ALL = ("2022-03-01", END)
FAM = {
    "F1": ("weekend", [(s, f, x) for s in ("straddle", "strangle25", "strangle15") for f in ("none", "ivp>=50") for x in ("open", "close")]),
    "F2": ("shock", [(k, e, s, h) for k in (2.0, 2.5) for e in ("same", "next") for s in ("strangle15", "strangle25", "straddle")
                     for h in (5, 10)]),
    "F3": ("report", [(s, f) for s in ("straddle", "strangle25", "strangle15") for f in ("none", "ivp>=50")]),
}
assert sum(len(v[1]) for v in FAM.values()) == 42          # AMENDMENT_A5's grid
RUN = {"weekend": E5.f1_trades, "shock": E5.f2_trades, "report": E5.f3_trades}
TRANSFER = {
    "CO-1": ("co", ("shortput", 0.5, 0.0, 15, "ivrv", None, 2.0, 0)),
    "CO-2": ("co", ("trend20", 1.0, 0.0, 15, "ivrv110", None, 1.0, 1)),
    "N-B": ("p2", ("dstrangle", 0.10, 10, ("le", 50), None)),
    "C-E": ("p2", ("dh", None, 10, None, None)),
    "P4-W": ("p4", ("WS1", (0.1, None, "ivp<=50", "trade"))),
}


def cache(work, name):
    return os.path.join(work, f"p5_{name}.pkl")


# ---------------------------------------------------------------------------- specs
def specs(data5, work5):
    """Multiplier = 1e5 x traded value (Rs lakh) / (lots x price), from the futures rows; tick = the
    smallest step between option closes. Checked against AMENDMENT_A5's multipliers."""
    out, bad = {}, []
    opt = pd.read_pickle(os.path.join(work5, "opt.pkl"))
    for sym in METALS + CROSS:
        ratios = []
        for path in glob.glob(os.path.join(data5, "FUTCOM", sym, "*.json.gz")):
            for r in json.load(gzip.open(path, "rt", encoding="utf-8")):
                try:
                    v, q, c = float(r["Value"]), float(r["Volume"]), float(r["Close"])
                except (TypeError, ValueError, KeyError):
                    continue
                if v > 0 and q > 0 and c > 0:
                    ratios.append(1e5 * v / (q * c))
        mult = statistics.median(ratios) if ratios else float("nan")
        px = np.unique(np.round(opt.loc[(opt.sym == sym) & opt.traded, "close"].to_numpy(), 4))
        steps = np.diff(px)
        tick = float(np.round(steps[steps > 0].min(), 4)) if len(steps) else float("nan")
        declared = E5.NEW_MULT[sym]
        out[sym] = {"multiplier_from_data": round(mult, 3), "declared": declared, "tick": tick, "n_futures_rows": len(ratios)}
        if not (abs(mult / declared - 1) < 0.02):
            bad.append(sym)
        print(sym, out[sym], flush=True)
    json.dump(out, open(os.path.join(work5, "p5_specs.json"), "w"), indent=1)
    if bad:
        raise SystemExit(f"multiplier mismatch: {bad}")


def load_specs(work5):
    sp = json.load(open(os.path.join(work5, "p5_specs.json")))
    E5.register({k: v["tick"] for k, v in sp.items()})


# ---------------------------------------------------------------------------- build
def build_energy(work4, work5):
    opt4 = pd.read_pickle(os.path.join(work4, "opt.pkl"))
    for inst, (parent, mini) in R4.SRC.items():
        for tag, sym in (("parent", parent), ("mini", mini)):
            cyc = E5.attach_opens(pd.read_pickle(os.path.join(work4, f"p4_{inst}_{tag}.pkl")), opt4, sym)
            pd.to_pickle(cyc, cache(work5, f"{inst}_{tag}"))
            print(f"{inst} {tag}: {len(cyc)} cycles with opens", flush=True)
        pd.to_pickle(pd.read_pickle(os.path.join(work4, f"p4_ivp_{inst}.pkl")), cache(work5, f"ivp_{inst}"))


def build_metals(work5):
    load_specs(work5)
    opt = pd.read_pickle(os.path.join(work5, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work5, "fut.pkl"))
    for sym in METALS + CROSS:
        cyc = E.build_cycles(opt, fut, sym, sym, "2017-01-01", "2027-12-31", require_expiry=False)
        cyc = [c for c in cyc if c.dates[-1] == c.expiry or c.dates[-1] == LAST]
        cyc = E5.attach_opens(cyc, opt, sym)
        pd.to_pickle(cyc, cache(work5, sym))
        ivp = E2.iv_percentile(E2.front_iv_series(cyc)).to_dict()
        pd.to_pickle(ivp, cache(work5, f"ivp_{sym}"))
        atm = np.mean([np.isfinite(c.katm).mean() for c in cyc])
        print(f"{sym}: {len(cyc)} cycles {cyc[0].expiry.date()}..{cyc[-1].expiry.date()}, ATM straddle available "
              f"{atm:.0%} of cycle-days", flush=True)


def book(work5, key, inst):
    """key: a metal symbol, or '<energy inst>_<parent|mini>'."""
    ivp_key = key if key in METALS + CROSS else inst
    return E4.Book(pd.read_pickle(cache(work5, key)), pd.read_pickle(cache(work5, f"ivp_{ivp_key}")), inst)


def full_period(bk):
    return (str(bk.days[0].date()), END)


# ---------------------------------------------------------------------------- Part B discovery
def eligible(s, s2, den):
    return bool(s.get("n", 0) >= 3 and s["n"] / max(den, 1) >= 0.70 and s["net"] > 0 and s["pf"] >= 1.3
                and np.isfinite(s.get("t", np.nan)) and s["t"] >= 1.5 and s2["net"] > 0 and s["worst_roc"] >= -0.30)


def discover(work5):
    bk = book(work5, "CRUDEOILM_parent", "CRUDEOILM")
    cands, rows = [], []
    for fam, (kind, grid) in FAM.items():
        best = None
        for v in grid:
            tr, den = RUN[kind](bk, "CRUDEOILM", v, *DISC, 0.01)
            tr2, _ = RUN[kind](bk, "CRUDEOILM", v, *DISC, 0.02)
            s, s2 = E5.tstats(tr), E5.tstats(tr2)
            ok = eligible(s, s2, den)
            p5 = bootstrap_p5(np.array([t["roc"] for t in tr])) if ok else np.nan
            rows.append({"family": fam, "variant": str(v), "den": den, **s, "net_2x": s2["net"], "eligible": ok, "p5": p5})
            if ok and (best is None or p5 > best[0]):
                best = (p5, v)
        fr = [r for r in rows if r["family"] == fam]
        top = max(fr, key=lambda r: r["net"])
        print(f"{fam} {kind:<8} {sum(r['eligible'] for r in fr)}/{len(fr)} eligible | most profitable {top['variant']}: "
              f"n={top['n']} net Rs{top['net']:,.0f} pf {top.get('pf', 0):.2f} t {top.get('t', 0):.2f}", flush=True)
        if best:
            r = next(x for x in fr if x["variant"] == str(best[1]))
            cands.append({"family": fam, "variant": list(best[1]), "disc": r})
            print(f"      -> FROZEN {best[1]}: n={r['n']} net Rs{r['net']:,.0f} pf {r['pf']:.2f} t {r['t']:.2f} "
                  f"worst {r['worst_roc']:.1%} p5 {r['p5']:.3%}", flush=True)
        else:
            print("      -> no eligible variant", flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(work5, "p5_discovery.csv"), index=False)
    json.dump(cands, open(os.path.join(work5, "p5_candidates.json"), "w"), indent=1, default=float)


# ---------------------------------------------------------------------------- tests
def run_transfer(name, bk, inst, a, b, slip):
    kind, v = TRANSFER[name]
    cyc = [c for c in bk.cycles if pd.Timestamp(a) <= c.expiry <= pd.Timestamp(b)]
    if kind == "co":
        s, k, w, e, f, pt, sl, tx = v
        return E.run_variant(cyc, s, k, w, e, f, pt, sl, tx, E.MULT[inst], E.FAMILY[inst], E.TICK[inst], slip)
    if kind == "p2":
        return R2.run_variant(cyc, inst, v, bk.ivp, slip)[0]
    fam, vv = v
    return [E5.with_roc(r["trade"]) for r in R4.run_variant(fam, vv, bk, inst, a, b, slip) if r["trade"] is not None]


def summarise(tr1, tr2):
    s1, s2 = E5.tstats(tr1), E5.tstats(tr2)
    return {**{k: (round(x, 4) if isinstance(x, float) else x) for k, x in s1.items()}, "net_2x": round(s2["net"]),
            "verdict": E5.verdict(s1, s2)}


def generalises(results, counted):
    vs = [results[m]["verdict"] for m in counted if m in results]
    passes = sum(v == "pass" for v in vs)
    with_verdict = sum(v != "too few" for v in vs)
    return {"passes": passes, "markets_with_verdict": with_verdict,
            "GENERALISES": bool(passes >= 3 and passes > with_verdict / 2)}


def test(work5):
    load_specs(work5)
    out = {"partA": {}, "partB": []}
    books = {m: book(work5, m, m) for m in METALS + CROSS}
    print("=== Part A: transfer test (frozen rules, untouched markets)", flush=True)
    for name in TRANSFER:
        res = {}
        for m in METALS + CROSS:
            bk = books[m]
            a, b = full_period(bk)
            tr1, tr2 = run_transfer(name, bk, m, a, b, 0.01), run_transfer(name, bk, m, a, b, 0.02)
            res[m] = summarise(tr1, tr2)
            pd.DataFrame(tr1).to_csv(os.path.join(work5, f"p5_A_{name}_{m}.csv"), index=False)
        g = generalises(res, METALS)
        out["partA"][name] = {"markets": res, **g}
        print(f"\n{name}: {'GENERALISES' if g['GENERALISES'] else 'does not generalise'} "
              f"({g['passes']} passes of {g['markets_with_verdict']} markets with a verdict)", flush=True)
        for m, s in res.items():
            print(f"   {m:8s} {s['verdict']:8s} n={s['n']:4d} net Rs{s['net']:>12,.0f} pf {s.get('pf', 0):5.2f} "
                  f"win {s.get('win', 0):.0%} worst {s.get('worst_roc', 0):.1%} 2x Rs{s['net_2x']:,}", flush=True)
    print("\n=== Part B: new families (picked on crude 2020-24), run once everywhere else", flush=True)
    cands = json.load(open(os.path.join(work5, "p5_candidates.json")))
    energy = {"crude T1 2018-19": (book(work5, "CRUDEOILM_parent", "CRUDEOILM"), "CRUDEOILM", T1),
              "crude T2 2024-26 mini": (book(work5, "CRUDEOILM_mini", "CRUDEOILM"), "CRUDEOILM", T2),
              "natural gas 2022-26": (book(work5, "NATGASMINI_parent", "NATGASMINI"), "NATGASMINI", NG_ALL),
              "crude T2 parent (check)": (book(work5, "CRUDEOILM_parent", "CRUDEOILM"), "CRUDEOILM", T2),
              "natural gas mini 2024-26 (check)": (book(work5, "NATGASMINI_mini", "NATGASMINI"), "NATGASMINI", T2)}
    for cd in cands:
        fam, v = cd["family"], tuple(cd["variant"])
        kind = FAM[fam][0]
        res = {}
        targets = dict(energy)
        if kind != "report":
            for m in METALS + CROSS:
                targets[m] = (books[m], m, full_period(books[m]))
        for label, (bk, inst, (a, b)) in targets.items():
            tr1, _ = RUN[kind](bk, inst, v, a, b, 0.01)
            tr2, _ = RUN[kind](bk, inst, v, a, b, 0.02)
            res[label] = summarise(tr1, tr2)
            pd.DataFrame(tr1).to_csv(os.path.join(work5, f"p5_B_{fam}_{label.split(' (')[0].replace(' ', '_')}.csv"), index=False)
        counted = ["crude T1 2018-19", "crude T2 2024-26 mini", "natural gas 2022-26"] + ([] if kind == "report" else list(METALS))
        g = generalises(res, counted)
        out["partB"].append({"family": fam, "kind": kind, "variant": str(v), "disc": cd["disc"], "markets": res, **g})
        print(f"\n{fam} {kind} {v}: {'GENERALISES' if g['GENERALISES'] else 'does not generalise'} "
              f"({g['passes']} passes of {g['markets_with_verdict']} markets with a verdict)", flush=True)
        for m, s in res.items():
            print(f"   {m:32s} {s['verdict']:8s} n={s['n']:4d} net Rs{s['net']:>12,.0f} pf {s.get('pf', 0):5.2f} "
                  f"win {s.get('win', 0):.0%} worst {s.get('worst_roc', 0):.1%} 2x Rs{s['net_2x']:,}", flush=True)
    json.dump(out, open(os.path.join(work5, "p5_results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    mode = sys.argv[1]
    {"specs": lambda: specs(sys.argv[2], sys.argv[3]), "build_energy": lambda: build_energy(sys.argv[2], sys.argv[3]),
     "build_metals": lambda: build_metals(sys.argv[2]),
     "discover": lambda: discover(sys.argv[2]), "test": lambda: test(sys.argv[2])}[mode]()
