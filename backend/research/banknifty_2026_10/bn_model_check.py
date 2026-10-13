"""Does the premium model reproduce REAL BANKNIFTY option prices? (out of sample, day by day)

For every session k since 2016 and every listed monthly with >= 2 sessions left, take the ATM
strike of the previous close and the strikes 300 either side, calls and puts, that traded at
least 50 contracts on both days. The model prices session k's close from the PREVIOUS session's
smile + session k's spot and India VIX (exactly what a replay knows at that moment). Compared
with NSE's real close:
  level error   (model_k - real_k) / real_k
  change error  (model change - real change) / real_(k-1), where the model change is measured
                from its own fit at k-1 - the P&L error a one-day hold would carry
by sessions left. Output: model_check.json and a printed table.
"""

import gzip
import json
import math
import os
import statistics
from datetime import date

import bn_common as C
from bn_price import Pricer


def main():
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
        for ek in px.surf[kp]:
            left = C.trading_sessions_left(k, ek)
            if left < 2 or ek not in closes[k] or ek not in closes[kp]:
                continue
            K0 = round(S_kp / C.STEP) * C.STEP
            for dK in (-300, 0, 300):
                K = K0 + dK
                a, b = closes[kp][ek].get(str(float(K))), closes[k][ek].get(str(float(K)))
                if not a or not b:
                    continue
                for call, i, n in ((True, 0, 2), (False, 1, 3)):
                    if a[n] < 50 or b[n] < 50 or a[i] < 5 or b[i] < 5:
                        continue
                    # session k's close off k-1's smile (what a replay knows), and k-1's close
                    # off its own smile (the real close up to the smile-fit error)
                    m_k = px.premium(e_k, S_k, K, call, ek, kp)
                    own = own_fit(px, kp, ek, S_kp, K, call, e_kp)
                    v_k, v_kp = px.vix.last_close(k), px.vix.last_close(kp)
                    rows.append({"k": k, "kp": kp, "ek": ek, "left": left, "dK": dK, "call": call, "real_kp": a[i],
                                 "real_k": b[i], "model_k": m_k, "own_kp": own, "spot_move_bp": (S_k / S_kp - 1) * 1e4,
                                 "vix_chg": (v_k / v_kp - 1) if v_k and v_kp else None})
    report(rows)
    return rows


def own_fit(px: Pricer, kp: int, ek: int, S: float, K: float, call: bool, e: int) -> float:
    """Session kp's close priced off kp's OWN smile at kp's own VIX (ratio 1): the fitted price."""
    row = px.surf[kp][ek]
    a, b, c = row[2], row[3], row[4]
    Tc = C.T_cal(e, ek)
    F = S * math.exp(C.CARRY * Tc)
    x = math.log(K / F)
    iv = max(a + b * x + c * x * x, 0.5 * a)
    return C.b76(F, K, C.T_years(e, ek), iv, call, math.exp(-C.R * Tc))


def bucket(left: int) -> str:
    return "2-4" if left <= 4 else "5-9" if left <= 9 else "10-19" if left <= 19 else "20-39" if left <= 39 else "40+"


def report(rows):
    out = {}
    print(f"{len(rows)} option-days compared")
    print(f"{'left':>6} {'n':>6} {'fit err':>8} {'level err':>10} {'|lvl|':>7} {'chg err':>8} {'chg sd':>7} {'slope':>6} {'corr':>5}")
    for bk in ("2-4", "5-9", "10-19", "20-39", "40+", "ALL"):
        rs = [r for r in rows if bk == "ALL" or bucket(r["left"]) == bk]
        if len(rs) < 30:
            continue
        fit = [(r["own_kp"] - r["real_kp"]) / r["real_kp"] for r in rs]
        lvl = [(r["model_k"] - r["real_k"]) / r["real_k"] for r in rs]
        dm = [r["model_k"] - r["own_kp"] for r in rs]
        dr = [r["real_k"] - r["real_kp"] for r in rs]
        chg = [(m - x) / r["real_kp"] for m, x, r in zip(dm, dr, rs)]
        mx, my = statistics.mean(dm), statistics.mean(dr)
        cov = sum((x - mx) * (y - my) for x, y in zip(dm, dr))
        vx = sum((x - mx) ** 2 for x in dm)
        vy = sum((y - my) ** 2 for y in dr)
        slope = cov / vx if vx else None
        corr = cov / math.sqrt(vx * vy) if vx and vy else None
        out[bk] = {"n": len(rs), "fit_err_mean": statistics.mean(fit), "level_err_mean": statistics.mean(lvl),
                   "level_abs_median": statistics.median(abs(x) for x in lvl), "change_err_mean": statistics.mean(chg),
                   "change_err_sd": statistics.pstdev(chg), "slope_real_on_model": slope, "corr": corr}
        o = out[bk]
        print(f"{bk:>6} {o['n']:>6} {o['fit_err_mean'] * 100:>7.2f}% {o['level_err_mean'] * 100:>9.2f}% "
              f"{o['level_abs_median'] * 100:>6.2f}% {o['change_err_mean'] * 100:>7.2f}% {o['change_err_sd'] * 100:>6.2f}% "
              f"{slope:>6.3f} {corr:>5.3f}")
    by_year = {}
    for r in rows:
        by_year.setdefault(C.kdate(r["k"]).year, []).append((r["model_k"] - r["own_kp"] - (r["real_k"] - r["real_kp"])) / r["real_kp"])
    for y in sorted(by_year):
        v = by_year[y]
        print(f"  {y}: n {len(v)}  change error mean {statistics.mean(v) * 100:+.2f}%  sd {statistics.pstdev(v) * 100:.2f}%")
        out.setdefault("by_year", {})[y] = {"n": len(v), "mean": statistics.mean(v), "sd": statistics.pstdev(v)}
    with open(os.path.join(C.DATA, "model_check.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
