"""Phase 6 (AMENDMENT_A6.md): crude-oil and natural-gas futures, judged week by week.

    python run_phase6.py <work6> discover
    python run_phase6.py <work6> test
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), HERE):
    sys.path.insert(0, p)
import engine6 as E6  # noqa: E402
from search import bootstrap_p5  # noqa: E402

SYMS = ("CRUDEOIL", "NATURALGAS")
MODES = ("ls", "lo", "so")
SIZES = ("1x", "vol")
FAM = {
    "TS": [(L, m, z) for L in (4, 8, 13, 26, 52) for m in MODES for z in SIZES],
    "MA": [(f, s, m, z) for f, s in ((5, 20), (10, 50), (20, 100), (50, 200)) for m in MODES for z in SIZES],
    "BO": [(n, k, m, z) for n in (20, 55) for k in (10, 20) for m in ("ls", "lo") for z in SIZES],
    "CY": [(th, m, z) for th in (0.0, 0.05, 0.10) for m in MODES for z in SIZES],
    "CT": [(L, z) for L in (13, 26) for z in SIZES],
    "SE": [(z,) for z in SIZES],
    "MR": [(k, z) for k in (1.0, 1.5, 2.0) for z in SIZES],
    "BH": [(s, z) for s in ("long", "short") for z in SIZES],
}
assert sum(len(v) for v in FAM.values()) == 104          # AMENDMENT_A6's grid, per instrument
DISC = ("2008-01-01", "2016-12-31")
TEST = ("2017-01-01", "2026-10-31")
WF_YEARS = list(range(2017, 2027))


def features(mk):
    d, D = mk.daily, mk.D
    I = d.I
    f = {"I": mk.I_D, "y": mk.y_D, "vol": mk.vol_D}
    for L in (4, 8, 13, 26, 52):
        f[f"ts{L}"] = (I / I.shift(5 * L) - 1).reindex(D).to_numpy()
    for n in (5, 10, 20, 50, 100, 200):
        f[f"ma{n}"] = I.rolling(n, min_periods=n).mean().reindex(D).to_numpy()
    for n in (10, 20, 55):
        f[f"hi{n}"] = I.shift(1).rolling(n, min_periods=n).max().reindex(D).to_numpy()
        f[f"lo{n}"] = I.shift(1).rolling(n, min_periods=n).min().reindex(D).to_numpy()
    wret = np.concatenate([[np.nan], mk.I_D[1:] / mk.I_D[:-1] - 1])          # the week that ENDED at D[w]
    f["wret"] = wret
    f["wsd26"] = pd.Series(wret).shift(1).rolling(26, min_periods=20).std().to_numpy()
    f["month_next"] = np.array([D[w + 1].month if w + 1 < len(D) else D[w].month for w in range(len(D))])
    f["month_end"] = np.array([x.month for x in D])
    return f


def sgn(x):
    return np.where(np.isfinite(x), np.sign(x), 0.0)


def raw_signal(fam, v, f):
    n = len(f["I"])
    if fam == "TS":
        return sgn(f[f"ts{v[0]}"])
    if fam == "MA":
        return sgn(f[f"ma{v[0]}"] - f[f"ma{v[1]}"])
    if fam == "BO":
        N, M = v[0], v[1]
        s, state = np.zeros(n), 0
        for w in range(n):
            I, hN, lN, hM, lM = f["I"][w], f[f"hi{N}"][w], f[f"lo{N}"][w], f[f"hi{M}"][w], f[f"lo{M}"][w]
            if state == 1 and np.isfinite(lM) and I < lM:
                state = 0
            if state == -1 and np.isfinite(hM) and I > hM:
                state = 0
            if np.isfinite(hN) and I > hN:
                state = 1
            elif np.isfinite(lN) and I < lN:
                state = -1
            s[w] = state
        return s
    if fam == "CY":
        th, y = v[0], f["y"]
        return np.where(np.isfinite(y) & (y > th), 1.0, np.where(np.isfinite(y) & (y < -th), -1.0, 0.0))
    if fam == "CT":
        a, b = sgn(f["y"]), sgn(f[f"ts{v[0]}"])
        return np.where((a == b) & (a != 0), a, 0.0)
    if fam == "SE":
        s = np.zeros(n)
        for w in range(n):
            past = [(f["month_end"][i], f["wret"][i]) for i in range(1, w + 1) if np.isfinite(f["wret"][i])]
            same = [r for m, r in past if m == f["month_next"][w]]
            if len(same) >= 3:
                s[w] = np.sign(np.mean(same))
        return s
    if fam == "MR":
        k, r, sd = v[0], f["wret"], f["wsd26"]
        ok = np.isfinite(r) & np.isfinite(sd)
        return np.where(ok & (r > k * sd), -1.0, np.where(ok & (r < -k * sd), 1.0, 0.0))
    if fam == "BH":
        return np.full(n, 1.0 if v[0] == "long" else -1.0)
    raise ValueError(fam)


def positions(fam, v, f, sym):
    s = raw_signal(fam, v, f)
    mode = v[-2] if fam in ("TS", "MA", "BO", "CY") else "ls"
    if mode == "lo":
        s = np.maximum(s, 0.0)
    elif mode == "so":
        s = np.minimum(s, 0.0)
    if v[-1] == "vol":
        cap = 1.0 / E6.MARGIN[sym]
        vol = f["vol"]
        scale = np.where(np.isfinite(vol) & (vol > 0), np.minimum(cap, 0.20 / np.where(vol > 0, vol, 1)), 0.0)
        s = s * scale
    return s


def evaluate(mk, f, fam, v, a, b):
    pos = positions(fam, v, f, mk.sym)
    w1, w2 = mk.returns(pos, 1.0), mk.returns(pos, 2.0)
    return E6.wstats(w1, a, b), E6.wstats(w2, a, b), w1


def eligible(s, s2):
    return bool(s.get("weeks_in_market", 0) >= 26 and s["net_pct"] > 0 and s2["net_pct"] > 0
                and np.isfinite(s.get("t", np.nan)) and s["t"] >= 2.0 and s.get("pf", 0) >= 1.10)


def pick(mk, f, fam, a, b):
    best, rows = None, []
    for v in FAM[fam]:
        s, s2, w = evaluate(mk, f, fam, v, a, b)
        ok = eligible(s, s2)
        x = w.loc[(w.index >= pd.Timestamp(a)) & (w.index <= pd.Timestamp(b))].net.to_numpy()
        p5 = bootstrap_p5(x) if ok else np.nan
        rows.append({"sym": mk.sym, "family": fam, "variant": str(v), **s, "net_pct_2x": s2["net_pct"], "eligible": ok, "p5": p5})
        if ok and (best is None or p5 > best[0]):
            best = (p5, v)
    return best, rows


def markets(work6):
    fut = pd.read_pickle(os.path.join(work6, "fut.pkl"))
    out = {}
    for sym in SYMS:
        mk = E6.Market(fut, sym)
        out[sym] = (mk, features(mk))
    return out


def discover(work6):
    mks = markets(work6)
    cands, rows = [], []
    for sym, (mk, f) in mks.items():
        print(f"\n=== {sym}: index {mk.daily.index[0].date()}..{mk.daily.index[-1].date()}, {len(mk.D)} weeks, "
              f"{int(mk.daily.roll.sum())} rolls", flush=True)
        for fam in FAM:
            best, rr = pick(mk, f, fam, *DISC)
            rows += rr
            top = max(rr, key=lambda r: r["mean"])
            line = (f"{sym:10s} {fam} {sum(r['eligible'] for r in rr):2d}/{len(rr)} eligible | best mean {top['variant']}: "
                    f"{top['mean']:.3%}/wk, Sharpe {top.get('sharpe', 0):.2f}, weeks >=2% {top.get('ge2_weeks', 0):.0%}")
            if best:
                r = next(x for x in rr if x["variant"] == str(best[1]))
                cands.append({"sym": sym, "family": fam, "variant": list(best[1]), "disc": r})
                line += (f"\n           -> FROZEN {best[1]}: {r['mean']:.3%}/wk, Sharpe {r['sharpe']:.2f}, t {r['t']:.2f}, "
                         f"maxDD {r['maxdd']:.0%}, L* {r.get('L_star', float('nan')):.1f}")
            else:
                line += "\n           -> no eligible variant"
            print(line, flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(work6, "p6_discovery.csv"), index=False)
    json.dump(cands, open(os.path.join(work6, "p6_candidates.json"), "w"), indent=1, default=float)
    print(f"\n{len(cands)} candidates")


def verdicts(sym, s, s2):
    cap = 1.0 / E6.MARGIN[sym]
    tradeable = bool(s["net_pct"] > 0 and s2["net_pct"] > 0 and np.isfinite(s.get("sharpe", np.nan)) and s["sharpe"] >= 0.30)
    feasible = bool("L_star" in s and s["exposure_needed_avg"] <= cap and s["maxdd_at_L"] < 1.0)
    return {"tradeable": tradeable, "target_avg_feasible": feasible,
            "target_avg_practical": bool(feasible and s["maxdd_at_L"] <= 0.5), "margin_cap": cap}


def test(work6):
    mks = markets(work6)
    cands = json.load(open(os.path.join(work6, "p6_candidates.json")))
    out = []
    for cd in cands:
        sym, fam = cd["sym"], cd["family"]
        mk, f = mks[sym]
        v = tuple(cd["variant"])
        s, s2, w = evaluate(mk, f, fam, v, *TEST)
        vd = verdicts(sym, s, s2)
        w.loc[(w.index >= pd.Timestamp(TEST[0]))].to_csv(os.path.join(work6, f"p6_weeks_{sym}_{fam}.csv"))
        wf = []
        for Y in WF_YEARS:
            best, _ = pick(mk, f, fam, DISC[0], f"{Y - 1}-12-31")
            if best is None:
                wf.append({"year": Y, "pick": None, "net_pct": 0.0})
                continue
            sy, _, _ = evaluate(mk, f, fam, best[1], f"{Y}-01-01", f"{Y}-12-31")
            wf.append({"year": Y, "pick": str(best[1]), "net_pct": round(sy["net_pct"], 2), "sharpe": sy.get("sharpe")})
        row = {"sym": sym, "family": fam, "variant": str(v), "disc": cd["disc"], "test": s, "test_net_pct_2x": s2["net_pct"],
               **vd, "walkforward": wf, "walkforward_net_pct": round(sum(x["net_pct"] for x in wf), 2)}
        out.append(row)
        print(f"\n{sym} {fam} {v}: tradeable {'PASS' if vd['tradeable'] else 'fail'} | 2%/wk feasible "
              f"{'YES' if vd['target_avg_feasible'] else 'no'} | practical {'YES' if vd['target_avg_practical'] else 'no'}", flush=True)
        print(f"   test 2017-26: {s['weeks']} weeks, net {s['net_pct']:.1f}% of account, mean {s['mean']:.3%}/wk, "
              f"Sharpe {s.get('sharpe', float('nan')):.2f}, profitable weeks {s.get('pos_weeks', 0):.0%}, "
              f">=2% weeks {s.get('ge2_weeks', 0):.0%}, maxDD {s.get('maxdd', 0):.0%}, 2x costs {s2['net_pct']:.1f}%", flush=True)
        if "L_star" in s:
            print(f"   for 2%/wk: leverage x{s['L_star']:.1f} -> avg exposure {s['exposure_needed_avg']:.1f}x "
                  f"(margin allows {vd['margin_cap']:.1f}x), maxDD {s['maxdd_at_L']:.0%}, worst week {s['worst_week_at_L']:.0%}, "
                  f"weeks >=2% {s['ge2_weeks_at_L']:.0%}", flush=True)
        print(f"   walk-forward 2017-26: {[(x['year'], x['net_pct']) for x in wf]} total {row['walkforward_net_pct']}%", flush=True)
    json.dump(out, open(os.path.join(work6, "p6_results.json"), "w"), indent=1, default=str)


def walkforward(work6):
    """A6's walk-forward, per family and instrument: each year re-pick on all earlier years, trade the year."""
    mks = markets(work6)
    out = []
    for sym, (mk, f) in mks.items():
        for fam in FAM:
            yrs, series = [], []
            for Y in WF_YEARS:
                best, _ = pick(mk, f, fam, DISC[0], f"{Y - 1}-12-31")
                if best is None:
                    yrs.append({"year": Y, "pick": None, "net_pct": 0.0})
                    continue
                pos = positions(fam, best[1], f, sym)
                w = mk.returns(pos).loc[f"{Y}-01-01":f"{Y}-12-31"]
                series.append(w)
                yrs.append({"year": Y, "pick": str(best[1]), "net_pct": round(float(w.net.sum() * 100), 2)})
            allw = pd.concat(series) if series else pd.DataFrame(columns=["pos", "gross", "cost", "net"])
            s = E6.wstats(allw) if len(allw) else {"weeks": 0, "net_pct": 0.0, "mean": 0.0}
            out.append({"sym": sym, "family": fam, "years": yrs, "stats": s})
            picks = sum(y["pick"] is not None for y in yrs)
            print(f"{sym:10s} {fam}: years with an eligible pick {picks}/10, walk-forward net {s['net_pct']:.1f}% "
                  f"mean {s['mean']:.3%}/wk", flush=True)
    json.dump(out, open(os.path.join(work6, "p6_walkforward.json"), "w"), indent=1, default=str)


def relaxed(work6):
    """DESCRIPTIVE, outside A6's verdicts: no variant met the t >= 2 bar, so take each family's best by
    bootstrap p5 among variants that merely made money (also at 2x costs) on 2008-16, and run it once
    on 2017-26 with the 2%-a-week arithmetic."""
    mks = markets(work6)
    out = []
    for sym, (mk, f) in mks.items():
        for fam in FAM:
            best = None
            for v in FAM[fam]:
                s, s2, w = evaluate(mk, f, fam, v, *DISC)
                if s.get("weeks_in_market", 0) >= 26 and s["net_pct"] > 0 and s2["net_pct"] > 0:
                    x = w.loc[DISC[0]:DISC[1]].net.to_numpy()
                    p5 = bootstrap_p5(x)
                    if best is None or p5 > best[0]:
                        best = (p5, v, s)
            if best is None:
                print(f"{sym:10s} {fam}: nothing made money on 2008-16", flush=True)
                continue
            s, s2, w = evaluate(mk, f, fam, best[1], *TEST)
            vd = verdicts(sym, s, s2)
            out.append({"sym": sym, "family": fam, "variant": str(best[1]), "disc": best[2], "test": s,
                        "test_net_pct_2x": s2["net_pct"], **vd})
            line = (f"{sym:10s} {fam} {str(best[1]):28s} 2008-16 {best[2]['mean']:.3%}/wk -> 2017-26 {s['mean']:.3%}/wk, "
                    f"Sharpe {s.get('sharpe', float('nan')):.2f}, net {s['net_pct']:.0f}%, maxDD {s.get('maxdd', 0):.0%}")
            if "L_star" in s:
                line += (f" | 2%/wk needs x{s['L_star']:.1f} (avg exposure {s['exposure_needed_avg']:.1f}x, cap {vd['margin_cap']:.1f}x),"
                         f" maxDD then {s['maxdd_at_L']:.0%}")
            print(line, flush=True)
    json.dump(out, open(os.path.join(work6, "p6_relaxed.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    {"discover": discover, "test": test, "walkforward": walkforward, "relaxed": relaxed}[sys.argv[2]](sys.argv[1])
