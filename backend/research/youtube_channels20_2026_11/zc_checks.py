"""Correctness checks of the 20-channel strategies, with the 11-channel study's harness (yc_checks): the truncation
(look-ahead) test and the fill test, unchanged, plus the two companions these books need (DH-02's 09:20 movers from the
pool; AB-06's Bank Nifty). Counts only - nothing here measures performance. Writes results/checks.json.

    python -I zc_checks.py [cuts=3] [SID,SID,...]
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "youtube_channels11_2026_11"))

import zc_strategies as ZS  # noqa: E402  (registers the records first)

_argv = sys.argv[1:]
sys.argv = [sys.argv[0]] + _argv
import yc_checks as YCK  # noqa: E402
import yc_run as R  # noqa: E402

YCK.ONLY = set(_argv[1].split(",")) if len(_argv) > 1 else set(ZS.NEW)
YCK.HERE = HERE
YCK.DAYS = {**YCK.DAYS, "NIFTY": 45, "BANKNIFTY": 45, "XAUUSD": 45, "BTCUSD": 60}
for _k in ("EURUSD", "GBPUSD", "NAS100"):
    YCK.DAYS.pop(_k, None)


def run_strategy(sid: str, U) -> dict:
    st = R.STRATEGIES[sid]
    out = {}
    for market in st.markets:
        ms = U.market(market)
        if ms is None:
            continue
        pool = U.market(market) if ({"ss03", "movers"} & set(st.needs)) else None
        cx = R.contexts(set(st.needs), nifty=U.market("NIFTY") if "nifty_gap" in st.needs else None,
                        nsed=U.market("NSED") if "nj20" in st.needs else None, pool=pool)
        p = {"ctx": cx} if cx else {}
        other = U.market("ETHUSD") if "ETHUSD" in st.needs else (U.market("BANKNIFTY") if "BANKNIFTY" in st.needs else None)
        for m in (ms if isinstance(ms, list) else [ms]):
            cache = U.cache.setdefault((market, m.name), {})
            if st.kind == "basket":
                continue
            o = other
            if o is not None and len(o.t) and len(m.t):        # the companion cut to the book's own span
                import numpy as np
                z = int(np.searchsorted(o.t, int(m.t[-1]), "right"))
                o = YCK.MK.cut(o, z - 1) if 1 < z < len(o.t) else o
            tr, _, S = R.run(sid, market, m, cache, p, o)
            out[f"{market}|{m.name}"] = ({YCK.sig_key(s) for s in S}, tr, m)
    return out


YCK.run_strategy = run_strategy


def check_eth(cuts: int = 3) -> dict:
    """yc_checks draws no cut times for ETHUSD (a companion there); here it is a book market (DR-04): the same
    truncation test on its own minutes."""
    import json
    import numpy as np
    sids = [s for s in YCK.ONLY if "ETHUSD" in R.STRATEGIES[s].markets]
    if not sids:
        return {}
    eth = YCK.MK.full("ETHUSD")
    base = {"ETHUSD": eth}
    rng = np.random.default_rng(11)
    t = eth.t
    cut_t = [int(t[i]) for i in rng.integers(len(t) // 3, len(t) - 5, cuts)]
    res = {}
    for sid in sids:
        F = run_strategy(sid, YCK.Universe(base, None))
        diffs = []
        for tc in cut_t:
            P = run_strategy(sid, YCK.Universe(base, tc))
            for key, (fs, ftr, _) in F.items():
                ps, ptr, pm = P.get(key, (set(), [], None))
                if pm is None:
                    continue
                cr = len(pm.t) - 1
                if {x for x in fs if x[0] < cr - 1} != {x for x in ps if x[0] < cr - 1}:
                    diffs.append(f"{key} signals differ at cut {tc}")
                if {YCK.trade_key(x) for x in ftr if x.exit_k < cr - 1} != {YCK.trade_key(x) for x in ptr if x.exit_k < cr - 1}:
                    diffs.append(f"{key} trades differ at cut {tc}")
        n_sig = sum(len(v[0]) for v in F.values())
        n_tr = sum(len(v[1]) for v in F.values())
        res[sid] = {"signals": n_sig, "trades": n_tr, "lookahead_ok": not diffs, "diffs": diffs[:4]}
        print(sid, "ETHUSD signals", n_sig, "trades", n_tr, "look-ahead", "ok" if not diffs else "DIFFERS", flush=True)
    path = HERE / "results" / "checks.json"
    d = json.loads(path.read_text())
    for sid, r in res.items():
        d["results"][sid] = {**d["results"].get(sid, {}), **r}
    path.write_text(json.dumps(d, indent=1, default=str))
    return res


if __name__ == "__main__":
    YCK.main()
    check_eth(YCK.CUTS)
