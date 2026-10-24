"""Phase 7 (AMENDMENT_A7.md): cross-commodity weekly futures portfolios, the combined portfolio of
everything with evidence, and the Kelly ceiling on "2% a week".

    python run_phase7.py <work7> discover
    python run_phase7.py <work7> test
    python run_phase7.py <work7> combined <work4> <work5>
"""
from __future__ import annotations

import ast
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "phase4"),
          os.path.join(HERE, "..", "phase5"), os.path.join(HERE, "..", "phase6"), HERE):
    sys.path.insert(0, p)
import engine7 as E7  # noqa: E402
from search import bootstrap_p5  # noqa: E402

FAM = {
    "XM": [(L, k) for L in (4, 13, 26, 52) for k in (2, 3)],
    "XC": [(c, k) for c in ("today", "avg4") for k in (2, 3)],
    "XX": [(k,) for k in (2, 3)],
    "TP": [(L,) for L in (4, 13, 26, 52, "ens")],
    "CP": [(c,) for c in ("today", "avg4")],
    "LB": [("long",)],
}
assert sum(len(v) for v in FAM.values()) == 22            # AMENDMENT_A7's grid
DISC = ("2008-01-01", "2016-12-31")
TEST = ("2017-01-01", "2026-10-31")
WF_YEARS = list(range(2017, 2027))
TARGET_SHARPE = 1.44


def sgn(x):
    return np.where(np.isfinite(x), np.sign(x), 0.0)


def rank_long_short(U, scores, k):
    n = len(U.keys)
    S = {s: np.zeros(n) for s in E7.UNIVERSE}
    for w in range(n):
        valid = sorted((scores[s][w], s) for s in E7.UNIVERSE
                       if np.isfinite(scores[s][w]) and np.isfinite(U.vol[s][w]) and U.vol[s][w] > 0)
        if len(valid) < 2 * k:
            continue
        for _, s in valid[-k:]:
            S[s][w] = 1.0
        for _, s in valid[:k]:
            S[s][w] = -1.0
    return S


def signals(U, fam, v):
    n = len(U.keys)
    if fam == "XM":
        return rank_long_short(U, {s: U.mom(s, v[0]) for s in E7.UNIVERSE}, v[1])
    if fam == "XC":
        return rank_long_short(U, {s: (U.y[s] if v[0] == "today" else U.carry4(s)) for s in E7.UNIVERSE}, v[1])
    if fam == "XX":
        m = {s: U.mom(s, 26) for s in E7.UNIVERSE}
        c = {s: U.carry4(s) for s in E7.UNIVERSE}
        score = {s: np.full(n, np.nan) for s in E7.UNIVERSE}
        for w in range(n):
            ok = [s for s in E7.UNIVERSE if np.isfinite(m[s][w]) and np.isfinite(c[s][w])]
            if len(ok) < 2 * v[0]:
                continue
            mv, cv = np.array([m[s][w] for s in ok]), np.array([c[s][w] for s in ok])
            zm = (mv - mv.mean()) / mv.std() if mv.std() > 0 else np.zeros(len(ok))
            zc = (cv - cv.mean()) / cv.std() if cv.std() > 0 else np.zeros(len(ok))
            for s, z in zip(ok, zm + zc):
                score[s][w] = z
        return rank_long_short(U, score, v[0])
    if fam == "TP":
        if v[0] == "ens":
            out = {}
            for s in E7.UNIVERSE:
                st = np.array([np.where(np.isfinite(U.mom(s, L)), np.sign(U.mom(s, L)), np.nan) for L in (4, 13, 26, 52)])
                with np.errstate(all="ignore"):
                    out[s] = np.nan_to_num(np.nanmean(st, axis=0))
            return out
        return {s: sgn(U.mom(s, v[0])) for s in E7.UNIVERSE}
    if fam == "CP":
        return {s: sgn(U.y[s] if v[0] == "today" else U.carry4(s)) for s in E7.UNIVERSE}
    if fam == "LB":
        return {s: np.where(np.isfinite(U.vol[s]), 1.0, 0.0) for s in E7.UNIVERSE}
    raise ValueError(fam)


_cache = {}


def series(U, fam, v, cost_mult=1.0):
    key = (fam, str(v), cost_mult)
    if key not in _cache:
        _cache[key] = U.run(signals(U, fam, v), cost_mult)
    return _cache[key]


def eligible(s, s2):
    return bool(s.get("weeks_in_market", 0) >= 26 and s["net_pct"] > 0 and s2["net_pct"] > 0
                and np.isfinite(s.get("t", np.nan)) and s["t"] >= 2.0)


def pick(U, fam, a, b):
    best, rows = None, []
    for v in FAM[fam]:
        w1, w2 = series(U, fam, v), series(U, fam, v, 2.0)
        s, s2 = E7.pstats(w1, a, b), E7.pstats(w2, a, b)
        ok = eligible(s, s2)
        x = w1.loc[(w1.index >= pd.Timestamp(a)) & (w1.index <= pd.Timestamp(b))].net.to_numpy()
        p5 = bootstrap_p5(x) if ok else np.nan
        rows.append({"family": fam, "variant": str(v), **s, "net_pct_2x": s2["net_pct"], "eligible": ok, "p5": p5})
        if ok and (best is None or p5 > best[0]):
            best = (p5, v)
    return best, rows


def universe(work7):
    return E7.Universe(pd.read_pickle(os.path.join(work7, "fut.pkl")))


def discover(work7):
    U = universe(work7)
    for s, m in U.mk.items():
        print(f"{s:10s} {m.daily.index[0].date()}..{m.daily.index[-1].date()} rolls {int(m.daily.roll.sum())} tick {U.ticks[s]}", flush=True)
    cands, rows = [], []
    for fam in FAM:
        best, rr = pick(U, fam, *DISC)
        rows += rr
        top = max(rr, key=lambda r: r.get("sharpe") if np.isfinite(r.get("sharpe", np.nan)) else -9)
        line = (f"{fam} {sum(r['eligible'] for r in rr)}/{len(rr)} eligible | best Sharpe {top['variant']}: "
                f"{top.get('sharpe', float('nan')):.2f}, mean {top['mean']:.3%}/wk")
        if best:
            r = next(x for x in rr if x["variant"] == str(best[1]))
            cands.append({"family": fam, "variant": list(best[1]), "disc": r})
            line += (f"\n    -> FROZEN {best[1]}: Sharpe {r['sharpe']:.2f}, t {r['t']:.2f}, mean {r['mean']:.3%}/wk, "
                     f"maxDD {r['maxdd']:.0%}, avg margin {r['avg_margin']:.0%} of the account")
        else:
            line += "\n    -> no eligible variant"
        print(line, flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(work7, "p7_discovery.csv"), index=False)
    json.dump(cands, open(os.path.join(work7, "p7_candidates.json"), "w"), indent=1, default=float)
    print(f"\n{len(cands)} candidates")


def verdicts(s, s2):
    tradeable = bool(s["net_pct"] > 0 and s2["net_pct"] > 0 and np.isfinite(s.get("sharpe", np.nan)) and s["sharpe"] >= 0.30)
    meets = bool(np.isfinite(s.get("sharpe", np.nan)) and s["sharpe"] >= TARGET_SHARPE and "L_star" in s
                 and s["margin_needed_max"] <= 1.0 and s["maxdd_at_L"] < 1.0)
    return {"tradeable": tradeable, "meets_2pct_a_week": meets}


def test(work7):
    U = universe(work7)
    cands = json.load(open(os.path.join(work7, "p7_candidates.json")))
    out = []
    for cd in cands:
        fam, v = cd["family"], tuple(cd["variant"])
        w1, w2 = series(U, fam, v), series(U, fam, v, 2.0)
        s, s2 = E7.pstats(w1, *TEST), E7.pstats(w2, *TEST)
        vd = verdicts(s, s2)
        w1.loc[TEST[0]:].to_csv(os.path.join(work7, f"p7_weeks_{fam}.csv"))
        yrs = {int(y): round(float(g.net.sum() * 100), 1) for y, g in w1.loc[TEST[0]:].groupby(w1.loc[TEST[0]:].index.year)}
        wf = []
        for Y in WF_YEARS:
            best, _ = pick(U, fam, DISC[0], f"{Y - 1}-12-31")
            if best is None:
                wf.append({"year": Y, "pick": None, "net_pct": 0.0})
                continue
            sy = E7.pstats(series(U, fam, best[1]), f"{Y}-01-01", f"{Y}-12-31")
            wf.append({"year": Y, "pick": str(best[1]), "net_pct": round(sy["net_pct"], 2)})
        row = {"family": fam, "variant": str(v), "disc": cd["disc"], "test": s, "test_net_pct_2x": s2["net_pct"],
               "test_by_year_pct": yrs, **vd, "walkforward": wf, "walkforward_net_pct": round(sum(x["net_pct"] for x in wf), 2)}
        out.append(row)
        print(f"\n{fam} {v}: tradeable {'PASS' if vd['tradeable'] else 'fail'} | meets 2%/wk {'YES' if vd['meets_2pct_a_week'] else 'no'}", flush=True)
        print(f"   2017-26: net {s['net_pct']:.1f}% of the account over {s['weeks']} weeks, mean {s['mean']:.3%}/wk, "
              f"Sharpe {s.get('sharpe', float('nan')):.2f}, profitable weeks {s.get('pos_weeks', 0):.0%}, maxDD {s.get('maxdd', 0):.0%}, "
              f"avg margin {s.get('avg_margin', 0):.0%}, 2x costs {s2['net_pct']:.1f}%", flush=True)
        print(f"   Kelly ceiling {s.get('kelly_ceiling_per_week', 0):.2%} a week; by year {yrs}", flush=True)
        if "L_star" in s:
            print(f"   for 2%/wk: x{s['L_star']:.1f} -> margin {s['margin_needed_max']:.0%} of the account at peak, maxDD {s['maxdd_at_L']:.0%}", flush=True)
        print(f"   walk-forward: {[(x['year'], x['net_pct']) for x in wf]} total {row['walkforward_net_pct']}%", flush=True)
    json.dump(out, open(os.path.join(work7, "p7_results.json"), "w"), indent=1, default=str)


# ---------------------------------------------------------------------------- the combined portfolio
def combined(work7, work4, work5):
    import engine as E
    import reference4 as RF
    import run_phase4 as R4
    import run_phase5 as R5
    R5.load_specs(work5)
    _, cmini = R4.books(work4, "CRUDEOILM")
    weeks = [d1 for d1, _ in cmini.week_slots() if pd.Timestamp("2022-06-01") <= d1 <= pd.Timestamp("2026-10-31")]
    key = lambda d: tuple(pd.Timestamp(d).isocalendar()[:2])  # noqa: E731
    # stream A: the options core, marked weekly (Phase 4 reference), as a fraction of Rs10 lakh
    ref = json.load(open(os.path.join(work4, "p4_reference.json")))
    A = pd.Series({key(d): v / 1e6 for d, v in ref["core_by_week"].items()})
    # stream B: CO-1 on gold mini, 4 lots, marked weekly
    gcyc = pd.read_pickle(R5.cache(work5, "GOLDM"))
    gcyc = [c for c in gcyc if c.dates[-1] == c.expiry]
    s, k, w, e, f, pt, sl, tx = RF.CO["CO-1"]
    tr = E.run_variant(gcyc, s, k, w, e, f, pt, sl, tx, E.MULT["GOLDM"], E.FAMILY["GOLDM"], E.TICK["GOLDM"], 0.01)
    gweeks = [d for d in weeks if d <= max(c.expiry for c in gcyc)]
    B = RF.weekly_mtm(tr, gcyc, gweeks, E.MULT["GOLDM"], E.TICK["GOLDM"]) * 4 / 1e6
    B.index = [key(d) for d in B.index]
    # stream C: the best frozen A7 futures portfolio (highest test Sharpe among the frozen candidates)
    res = json.load(open(os.path.join(work7, "p7_results.json")))
    U = universe(work7)
    if res:
        best = max(res, key=lambda r: r["test"].get("sharpe", -9) if r["test"].get("sharpe") is not None else -9)
        fam, v = best["family"], tuple(ast.literal_eval(best["variant"]))
    else:
        fam, v = "LB", ("long",)
    C = series(U, fam, v).net
    C.index = [key(d) for d in C.index]
    df = pd.DataFrame({"A_options_core": A, "B_goldmini_CO1": B, "C_futures_" + fam: C}).sort_index()
    df = df[(df.index >= key("2022-06-01"))].fillna(0.0)
    # equal risk: each stream scaled by 1 / its trailing 26-week sd (only past weeks), once 26 weeks exist
    scaled = pd.DataFrame(index=df.index)
    for col in df.columns:
        x = df[col]
        live = x.ne(0).cumsum() > 0
        sd = x.where(live).shift(1).rolling(26, min_periods=26).std()
        scaled[col] = x / sd
    combo = scaled.dropna().sum(axis=1)
    first = combo.index[0]
    out = {"futures_stream": f"{fam} {v}", "window_start": str(first), "weeks": int(len(combo))}
    for name, x in [("combined", combo)] + [(c, df.loc[combo.index, c]) for c in df.columns]:
        m, sd = float(x.mean()), float(x.std(ddof=1))
        S = m / sd * math.sqrt(52) if sd > 0 else float("nan")
        cum = np.concatenate([[0.0], np.cumsum(x.to_numpy())])
        dd = float((np.maximum.accumulate(cum) - cum).max())
        g, ceil = E7.kelly(S)
        row = {"sharpe": round(S, 2), "kelly_ceiling_per_week": round(ceil, 4), "skew": round(float(x.skew()), 2)}
        if dd > 0 and m > 0:
            for D in (0.30, 0.50):
                row[f"mean_per_week_at_maxdd_{int(D * 100)}pct"] = round(m * D / dd, 5)
        out[name] = row
        print(name, row, flush=True)
    json.dump(out, open(os.path.join(work7, "p7_combined.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    mode = sys.argv[2]
    if mode == "combined":
        combined(sys.argv[1], sys.argv[3], sys.argv[4])
    else:
        {"discover": discover, "test": test}[mode](sys.argv[1])
