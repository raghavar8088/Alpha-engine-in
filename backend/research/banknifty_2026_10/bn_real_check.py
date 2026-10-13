"""Re-price the replays' own trades with REAL option prices, where real prices exist.

Angel's 5m candles cover the live October / November 2026 monthlies (strikes 53,500-57,000) from
early August to 9 Oct 2026. Every intraday trade in that window whose contract is covered is
priced twice with identical costs: the model's entry/exit premiums (as the replay did) and the
real option's close on the entry and exit bars. A stop or target fills mid-bar in the replay;
here it is the real close of that bar, so single trades differ - the question is whether the
model is systematically kinder than the market on the trades strategies actually take.
"""

import glob
import gzip
import json
import os
import statistics
from datetime import date

import bn_common as C
from bn_price import Pricer


def main(keys: list[str] | None = None):
    bn = C.Sessions("NIFTYBANK", start=date(2015, 6, 1))
    C.set_trading_days(bn.all_days)
    px = Pricer()
    with gzip.open(os.path.join(C.DATA, "bn_optcandles.json.gz"), "rt") as f:
        raw = json.load(f)
    real = {}
    for key, rows in raw.items():
        exp, K, typ = key.split("|")
        real[(C.dk(date.fromisoformat(exp)), float(K), typ)] = {int(r[0]): (r[4], r[5]) for r in rows}
    k_lo = min(C.dkey(t) for v in real.values() for t in v)
    per: dict[str, list] = {}
    for sub in ("lib", "fam"):
        for f in glob.glob(os.path.join(C.DATA, "results", sub, "*.json")):
            d = json.load(open(f))
            key = f"{d['sid']}@{d['tf']}"
            if keys and key not in keys:
                continue
            cols = d["cols"]
            for t in d["trades"]:
                k = t[cols.index("k")]
                if k < k_lo:
                    continue
                cp = px.contract_for(k)
                if not cp:
                    continue
                ek = cp[0]
                K, side = float(t[cols.index("K")]), t[cols.index("side")]
                series = real.get((ek, K, "CE" if side > 0 else "PE"))
                if not series:
                    continue
                e0 = t[cols.index("entry_e")]
                e1 = e0 + 60 * t[cols.index("hold_min")]
                r0, r1 = series.get(e0 - 300), series.get(e1 - 300)
                if not r0 or not r1 or r0[1] <= 0 or r1[1] <= 0:
                    continue
                model = t[cols.index("net")]
                actual = C.net_pnl(r0[0], r1[0])
                per.setdefault(key, []).append((model, actual, t[cols.index("p0")], r0[0]))
    allp = [x for v in per.values() for x in v]
    out = {"trades": len(allp), "strategies": len(per)}
    if allp:
        diff = [m - a for m, a, _, _ in allp]
        lvl = [(p0 - r0) / r0 for _, _, p0, r0 in allp]
        out.update({"model_minus_real_mean": statistics.mean(diff), "model_minus_real_median": statistics.median(diff),
                    "model_mean": statistics.mean(m for m, _, _, _ in allp), "real_mean": statistics.mean(a for _, a, _, _ in allp),
                    "entry_level_err_mean": statistics.mean(lvl), "entry_level_err_median": statistics.median(lvl)})
        print(f"{len(allp)} trades from {len(per)} strategies re-priced with real candles")
        print(f"  per trade: model {out['model_mean']:+.0f}  real {out['real_mean']:+.0f}  (model - real: mean "
              f"{out['model_minus_real_mean']:+.0f}, median {out['model_minus_real_median']:+.0f})")
        print(f"  entry premium: model vs real {out['entry_level_err_mean'] * 100:+.2f}% mean, {out['entry_level_err_median'] * 100:+.2f}% median")
    out["per_strategy"] = {k: {"n": len(v), "model": statistics.mean(m for m, _, _, _ in v), "real": statistics.mean(a for _, a, _, _ in v)}
                           for k, v in per.items()}
    with open(os.path.join(C.DATA, "real_check.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)
