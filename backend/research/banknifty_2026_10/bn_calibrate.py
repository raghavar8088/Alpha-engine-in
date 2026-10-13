"""Calibrate the premium model on EXPLORE (2016-2021), check it on HOLDOUT (2022-2026-10).

Two choices, scored on the day-over-day change of REAL closing premiums (ATM and +-300, calls
and puts, >= 5 sessions left, >= 50 contracts traded both days):
  VIX_BETA   vol *= (VIX ratio) ** beta, beta in 0 .. 1
  smile      "moneyness": yesterday's smile moves with the forward (x = ln K/F_today)
             "strike":    each strike keeps yesterday's vol (x = ln K/F_yesterday)
The pair with the lowest root-mean-square change error on EXPLORE is chosen; bias and RMSE on
HOLDOUT are reported for it. Output: calibration.json.
"""

import gzip
import json
import math
import os
import statistics
from datetime import date

import bn_common as C
from bn_price import Pricer

BETAS = [0.0, 0.25, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def collect():
    bn = C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
    C.set_trading_days(bn.all_days)
    px = Pricer()
    with gzip.open(os.path.join(C.DATA, "closes.json.gz"), "rt") as f:
        closes = {int(k): {int(e): v for e, v in d.items()} for k, d in json.load(f).items()}
    rows = []
    for k in px.sk:
        if C.kdate(k) < C.RESEARCH_START or k not in bn.bars:
            continue
        kp = px.prev_session(k)
        if kp is None or kp not in bn.bars or kp not in closes or k not in closes:
            continue
        S_kp, S_k = bn.last_close(kp), bn.last_close(k)
        e_kp, e_k = C.at(kp, C.CLOSE_MIN), C.at(k, C.CLOSE_MIN)
        v_k, v_kp = px.vix.last_close(k), px.vix.last_close(kp)
        if not (v_k and v_kp):
            continue
        for ek, row in px.surf[kp].items():
            if C.trading_sessions_left(k, ek) < 5 or ek not in closes[k] or ek not in closes[kp]:
                continue
            F_par_kp, a, b, c = row[0], row[2], row[3], row[4]
            K0 = round(S_kp / C.STEP) * C.STEP
            for dK in (-300, 0, 300):
                K = K0 + dK
                x0, x1 = closes[kp][ek].get(str(float(K))), closes[k][ek].get(str(float(K)))
                if not x0 or not x1:
                    continue
                for call, i, n in ((True, 0, 2), (False, 1, 3)):
                    if x0[n] < 50 or x1[n] < 50 or x0[i] < 5 or x1[i] < 5:
                        continue
                    rows.append({"k": k, "K": K, "call": call, "real_kp": x0[i], "real_k": x1[i],
                                 "Fk": S_k * math.exp(C.CARRY * C.T_cal(e_k, ek)),
                                 "Fkp": S_kp * math.exp(C.CARRY * C.T_cal(e_kp, ek)), "Fpar": F_par_kp,
                                 "Tk": C.T_years(e_k, ek), "Tkp": C.T_years(e_kp, ek),
                                 "dk": math.exp(-C.R * C.T_cal(e_k, ek)), "dkp": math.exp(-C.R * C.T_cal(e_kp, ek)),
                                 "abc": (a, b, c), "ratio": min(2.0, max(0.5, v_k / v_kp))})
    return rows


def iv_at(abc, x):
    a, b, c = abc
    return max(a + b * x + c * x * x, 0.5 * a)


def change_errors(rows, beta, smile):
    out = []
    for r in rows:
        own = C.b76(r["Fkp"], r["K"], r["Tkp"], iv_at(r["abc"], math.log(r["K"] / r["Fkp"])), r["call"], r["dkp"])
        xk = math.log(r["K"] / (r["Fk"] if smile == "moneyness" else r["Fkp"]))
        mk = C.b76(r["Fk"], r["K"], r["Tk"], iv_at(r["abc"], xk) * r["ratio"] ** beta, r["call"], r["dk"])
        out.append((r["k"], ((mk - own) - (r["real_k"] - r["real_kp"])) / r["real_kp"]))
    return out


def summarize(errs):
    xs = [e for _, e in errs]
    return {"n": len(xs), "bias": statistics.mean(xs), "rmse": math.sqrt(statistics.mean(x * x for x in xs)),
            "median": statistics.median(xs)}


def main():
    rows = collect()
    explore = [r for r in rows if C.kdate(r["k"]) <= C.EXPLORE_END]
    holdout = [r for r in rows if C.kdate(r["k"]) > C.EXPLORE_END]
    print(f"{len(explore)} explore / {len(holdout)} holdout option-days")
    grid = []
    for smile in ("moneyness", "strike"):
        for beta in BETAS:
            ex = summarize(change_errors(explore, beta, smile))
            grid.append({"smile": smile, "beta": beta, "explore": ex})
            print(f"  {smile:<9} beta {beta:.2f}: EXPLORE bias {ex['bias'] * 100:+.2f}%  rmse {ex['rmse'] * 100:.2f}%  median {ex['median'] * 100:+.2f}%")
    best = min(grid, key=lambda g: g["explore"]["rmse"])
    best["holdout"] = summarize(change_errors(holdout, best["beta"], best["smile"]))
    base = summarize(change_errors(holdout, 1.0, "moneyness"))
    print(f"CHOSEN on EXPLORE: smile={best['smile']} beta={best['beta']} -> HOLDOUT bias {best['holdout']['bias'] * 100:+.2f}% "
          f"rmse {best['holdout']['rmse'] * 100:.2f}% (uncalibrated beta 1 / moneyness: bias {base['bias'] * 100:+.2f}% rmse {base['rmse'] * 100:.2f}%)")
    with open(os.path.join(C.DATA, "calibration.json"), "w") as f:
        json.dump({"grid": grid, "chosen": best, "holdout_uncalibrated": base}, f, indent=1)


if __name__ == "__main__":
    main()
