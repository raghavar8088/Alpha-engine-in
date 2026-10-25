"""Post-hoc diagnostics, run AFTER the one-time final test and outside its gate: they explain the result and
cannot change it (PREREG_A1 section 10). Nothing here is a new strategy.

    python n50_diagnostics.py <data dir: n50_clean.pkl, universe.json> <out dir>

  1. The frozen configurations with every cost set to zero (no charges, no slippage): is there a signal at all?
  2. What a round trip costs the frozen configurations, in bp of notional and in R.
  3. Plain continuation: the screen's top-5 candidates per side (base screen, and with the frozen filters),
     bought or sold at the 09:30 open and closed at the 15:10 open - no stop, no target - in bp, before costs.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n50_engine as E  # noqa: E402

PERS = ("dev", "val", "final")


def per_period(T, P, fn):
    return {per: fn(E.in_period(T, per)) for per in PERS}


def main(data, out):
    data, out = Path(data), Path(out)
    frozen = json.load(open(HERE / "FROZEN_A1.json"))
    P = E.Panel(data / "n50_clean.pkl", HERE / "phase0" / "membership.json", data / "universe.json")
    f = P.screen(3)
    pools0 = {st: {sd: E.pool(P, f, st, sd, cost_mult=0.0) for sd in (1, -1)} for st in E.SETUPS}
    pools1 = {st: {sd: E.pool(P, f, st, sd) for sd in (1, -1)} for st in E.SETUPS}
    res = {"zero_cost": {}, "cost_per_round_trip": {}, "continuation_bp": {}}
    for key, cfg in frozen["configs"].items():
        filt = {int(k): v for k, v in cfg["filters"].items()}
        sides = tuple(cfg["sides"])
        T0 = E.select(pools0[cfg["setup"]], filt, sides=sides)
        res["zero_cost"][key] = per_period(T0, P, lambda t: {"trades": len(t), "mean_R": round(float(t.R.mean()), 4),
                                                             "net": round(float(t.net.sum()), 0)})
        T1 = E.select(pools1[cfg["setup"]], filt, sides=sides)
        slip_bp = 2 * (P.half_spread[T1.s, T1.d] + E.EXTRA_SLIP_BP)
        T1 = T1.assign(fee_bp=T1.fees / T1.notional * 1e4, slip_bp=slip_bp, cost_R=T1.fees / T1.risk)

        def cost(t):
            return {"fees_bp": round(float(t.fee_bp.mean()), 2), "slippage_bp": round(float(t.slip_bp.mean()), 2),
                    "fees_R": round(float(t.cost_R.mean()), 4),
                    "risk_bp_of_notional": round(float((t.risk / t.notional * 1e4).mean()), 1)}
        res["cost_per_round_trip"][key] = per_period(T1, P, cost)

    O, o930 = P.S["o"], P.S["o"][:, :, E.B930]
    o1510 = O[:, :, E.B1510]
    for label, use_filters in (("base screen", False), ("frozen filters", True)):
        res["continuation_bp"][label] = {}
        for sd, name in ((1, "long"), (-1, "short")):
            filt = frozen["configs"][f"S2 {name}"]["filters"][str(sd)] if use_filters else []
            with np.errstate(invalid="ignore"):
                ok = f["eligible"] & (f["or_move"] * sd >= 0.25)
                for fl in filt:
                    ok &= np.asarray(E.FILTER[fl](f, sd))
            s, d = np.nonzero(ok)
            df = pd.DataFrame({"s": s, "d": d, "mv": (f["or_move"] * sd)[s, d],
                               "ret": sd * (o1510[s, d] / o930[s, d] - 1) * 1e4,
                               "day": P.days[d]}).dropna()
            df = df.sort_values(["d", "mv"], ascending=[True, False])
            df = df[(df.groupby("d").cumcount() < 5).to_numpy()]
            res["continuation_bp"][label][name] = {
                per: {"n": int(len(x)), "mean_bp": round(float(x.ret.mean()), 2),
                      "t": round(float(x.ret.mean() / (x.groupby("day").ret.mean().std(ddof=1)
                                                       / np.sqrt(x.day.nunique()))), 2)}
                for per in PERS for x in [E.in_period(df, per)]}
    # 4. Charges only, no slippage at all (an impossible best case), and the slippage at which each frozen
    #    configuration breaks even: zero-cost R minus charges R, times the stop distance, in bp per round trip.
    P.half_spread = np.zeros_like(P.half_spread)
    poolsC = {st: {sd: E.pool(P, f, st, sd, slip_bp=0.0) for sd in (1, -1)} for st in E.SETUPS}
    res["charges_only"], res["breakeven_slippage_bp_round_trip"] = {}, {}
    for key, cfg in frozen["configs"].items():
        filt = {int(k): v for k, v in cfg["filters"].items()}
        TC = E.select(poolsC[cfg["setup"]], filt, sides=tuple(cfg["sides"]))
        res["charges_only"][key] = per_period(TC, P, lambda t: {"trades": len(t), "mean_R": round(float(t.R.mean()), 4),
                                                                "net": round(float(t.net.sum()), 0)})
        res["breakeven_slippage_bp_round_trip"][key] = per_period(
            TC, P, lambda t: round(float(t.R.mean() * (t.risk / t.notional * 1e4).mean()), 1))
    json.dump(res, open(out / "diagnostics_A1.json", "w"), indent=1)
    for k in res["charges_only"]:
        print(f"{k:9} charges only, no slippage: mean R {[v['mean_R'] for v in res['charges_only'][k].values()]}"
              f"  break-even slippage (bp, round trip) {list(res['breakeven_slippage_bp_round_trip'][k].values())}")
    for k, v in res["zero_cost"].items():
        c = res["cost_per_round_trip"][k]["final"]
        print(f"{k:9} zero-cost mean R  dev {v['dev']['mean_R']:>7}  val {v['val']['mean_R']:>7}  final {v['final']['mean_R']:>7}"
              f"   | final costs: fees {c['fees_bp']} bp + slippage {c['slippage_bp']} bp of notional; fees {c['fees_R']} R;"
              f" stop {c['risk_bp_of_notional']} bp")
    print(json.dumps(res["continuation_bp"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
