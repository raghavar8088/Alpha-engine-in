"""Calibrate the premium model on EXPLORE (2021-10 .. 2023-12), check it on HOLDOUT (2024-01 .. 2026-10).

As ../banknifty_2026_10/bn_calibrate.py, on the contracts this test trades: NIFTY options with at most
7 calendar days to expiry (the same-week weekly), strikes at the money and +-100, calls and puts, at
least 1,000 contracts traded on both days, priced at least Rs2. Scored on the day-over-day change of
REAL closing premiums:
  beta    vol *= (India VIX ratio) ** beta, beta in 0 .. 2 (same-week options move more than the 30-day VIX)
  smile   "strike": each strike keeps yesterday's vol | "moneyness": the smile moves with the forward
The model's price at session k's close uses k's own put-call-parity forward (so the index's closing
auction timing does not enter) and k-1's smile. The pair with the lowest RMS error on EXPLORE is
chosen; bias and RMS on HOLDOUT are reported. Output: results/calibration.json.
"""

from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nopt_common as C  # noqa: E402
from nopt_price import Pricer  # noqa: E402

BETAS = [0.0, 0.25, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0]
EXPLORE_END = date(2023, 12, 31)


def collect(px: Pricer) -> list[dict]:
    with gzip.open(C.DATA / "closes.json.gz", "rt") as f:
        closes = {int(k): {int(e): v for e, v in d.items()} for k, d in json.load(f).items()}
    rows = []
    for i, k in enumerate(px.sk):
        if i == 0:
            continue
        kp = px.sk[i - 1]
        if kp not in closes or k not in closes:
            continue
        v_k, v_kp = px.vix_last.get(k), px.vix_last.get(kp)
        if not (v_k and v_kp):
            continue
        for ek, row in px.surf[kp].items():
            if ek - k > 7 or ek <= k or ek not in px.surf[k] or ek not in closes[k] or ek not in closes[kp]:
                continue
            F_kp, F_k = row[0], px.surf[k][ek][0]
            K0 = round(F_kp / C.STEP) * C.STEP
            e_kp, e_k = C.at(kp, C.CLOSE_MIN), C.at(k, C.CLOSE_MIN)
            for dK in (-100, 0, 100):
                K = float(K0 + dK)
                x0, x1 = closes[kp][ek].get(str(K)), closes[k][ek].get(str(K))
                if not x0 or not x1:
                    continue
                for call, i_p, i_n in ((True, 0, 2), (False, 1, 3)):
                    if x0[i_n] < 1000 or x1[i_n] < 1000 or x0[i_p] < 2 or x1[i_p] < 2:
                        continue
                    rows.append({"k": k, "K": K, "call": call, "real_kp": x0[i_p], "real_k": x1[i_p], "Fk": F_k, "Fkp": F_kp,
                                 "Tk": C.T_years(e_k, ek), "Tkp": C.T_years(e_kp, ek),
                                 "dk": math.exp(-C.R * C.T_cal(e_k, ek)), "dkp": math.exp(-C.R * C.T_cal(e_kp, ek)),
                                 "abc": tuple(row[2:5]), "ratio": min(2.0, max(0.5, v_k / v_kp)), "dte": ek - k})
    return rows


def iv_at(abc, x):
    a, b, c = abc
    return max(a + b * x + c * x * x, 0.5 * a)


def errors(rows, beta, smile):
    out = []
    for r in rows:
        own = C.b76(r["Fkp"], r["K"], r["Tkp"], iv_at(r["abc"], math.log(r["K"] / r["Fkp"])), r["call"], r["dkp"])
        xk = math.log(r["K"] / (r["Fk"] if smile == "moneyness" else r["Fkp"]))
        mk = C.b76(r["Fk"], r["K"], r["Tk"], iv_at(r["abc"], xk) * r["ratio"] ** beta, r["call"], r["dk"])
        out.append(((mk - own) - (r["real_k"] - r["real_kp"])) / r["real_kp"])
    return out


def summarize(xs):
    if not xs:
        return {"n": 0, "bias": float("nan"), "rmse": float("nan"), "median": float("nan")}
    return {"n": len(xs), "bias": statistics.mean(xs), "rmse": math.sqrt(statistics.mean(x * x for x in xs)),
            "median": statistics.median(xs)}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    C.set_calendar()
    px = Pricer(beta=0.0, smile="strike")
    rows = collect(px)
    ex = [r for r in rows if C.kdate(r["k"]) <= EXPLORE_END]
    ho = [r for r in rows if C.kdate(r["k"]) > EXPLORE_END]
    print(f"{len(ex)} explore / {len(ho)} holdout option-days")
    grid = []
    for smile in ("strike", "moneyness"):
        for beta in BETAS:
            s = summarize(errors(ex, beta, smile))
            grid.append({"smile": smile, "beta": beta, "explore": s})
            print(f"  {smile:<9} beta {beta:.2f}: EXPLORE bias {s['bias'] * 100:+.2f}%  rmse {s['rmse'] * 100:.2f}%  median {s['median'] * 100:+.2f}%")
    best = min(grid, key=lambda g: g["explore"]["rmse"])
    best["holdout"] = summarize(errors(ho, best["beta"], best["smile"]))
    by_dte = {}
    for d in sorted({r["dte"] for r in ho}):
        sub = [r for r in ho if r["dte"] == d]
        if len(sub) >= 30:
            by_dte[str(d)] = summarize(errors(sub, best["beta"], best["smile"]))
    best["holdout_by_calendar_days_to_expiry"] = by_dte
    print(f"CHOSEN on EXPLORE: smile={best['smile']} beta={best['beta']} -> HOLDOUT bias {best['holdout']['bias'] * 100:+.2f}% "
          f"rmse {best['holdout']['rmse'] * 100:.2f}% (n {best['holdout']['n']})")
    for d, s in by_dte.items():
        print(f"   holdout, {d} calendar days to expiry: n {s['n']}  bias {s['bias'] * 100:+.2f}%  rmse {s['rmse'] * 100:.2f}%")
    with open(C.RES / "calibration.json", "w", encoding="utf-8") as f:
        json.dump({"grid": grid, "chosen": best}, f, indent=1)


if __name__ == "__main__":
    main()
