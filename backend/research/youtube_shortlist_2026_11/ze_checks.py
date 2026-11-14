"""Correctness checks of the channel-shortlist strategies with the 11-channel study's harness (yc_checks): the truncation
(look-ahead) test - every market cut at random minutes, the signals and the closed trades known at the cut must equal
the full run's field by field - and the fill test (every fill inside its row's range plus costs). Counts only: nothing
here measures performance. Writes results/checks.json.

    python -I ze_checks.py [cuts=3] [SID,SID,...]
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ze_strategies as ZS  # noqa: E402  (registers the records first)

_argv = sys.argv[1:]
sys.argv = [sys.argv[0]] + _argv

import yc_checks as YCK  # noqa: E402
import yc_run as R  # noqa: E402

YCK.ONLY = set(_argv[1].split(",")) if len(_argv) > 1 else set(ZS.NEW)
YCK.HERE = HERE
YCK.DAYS = {"NIFTY": 90, "BANKNIFTY": 60, "XAUUSD": 45, "EURUSD": 60, "GBPUSD": 60, "NAS100": 90, "BTCUSD": 75}
_orig_load = YCK.load_base
_BASE: dict = {}


def _load_base():
    base = _orig_load()              # ETHUSD (cut to bitcoin's window) stays: the fifth batch trades it
    _BASE.update(base)
    return base


YCK.load_base = _load_base


def run_strategy(sid: str, U) -> dict:
    st = R.STRATEGIES[sid]
    out = {}
    for market in st.markets:
        ms = U.market(market)
        if ms is None:
            continue
        pool = ms if isinstance(ms, list) else None
        needs = {n for n in st.needs if str(n).startswith("ze_")}
        cx = R.contexts(set(st.needs), nifty=U.market("NIFTY"), pool=pool) if (needs and pool is not None) else {}
        p = {"ctx": cx} if cx else {}
        for m in (ms if isinstance(ms, list) else [ms]):
            cache = U.cache.setdefault((market, m.name), {})
            tr, _, S = R.run(sid, market, m, cache, p, None)
            out[f"{market}|{m.name}"] = ({YCK.sig_key(s) for s in S}, tr, m)
    return out


YCK.run_strategy = run_strategy

def check_eth(cuts: int) -> dict:
    """yc_checks draws no cut times for ETHUSD (a companion market there); the fifth batch trades it, so the same
    truncation test runs on its own minutes and is ANDed into each strategy's look-ahead result."""
    import json
    import numpy as np
    sids = sorted(s for s in YCK.ONLY if "ETHUSD" in R.STRATEGIES[s].markets)
    eth = _BASE.get("ETHUSD")
    if not sids or eth is None:
        return {}
    base = {"ETHUSD": eth}
    t = eth.t
    cut_t = [int(t[i]) for i in np.random.default_rng(11).integers(len(t) // 3, len(t) - 5, cuts)]
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
        res[sid] = {"eth_signals": sum(len(v[0]) for v in F.values()), "eth_trades": sum(len(v[1]) for v in F.values()),
                    "eth_cuts": len(cut_t), "eth_lookahead_ok": not diffs, "eth_diffs": diffs[:4]}
        print(sid, "ETHUSD signals", res[sid]["eth_signals"], "trades", res[sid]["eth_trades"], "look-ahead",
              "ok" if not diffs else "DIFFERS", flush=True)
    path = HERE / "results" / "checks.json"
    d = json.loads(path.read_text())
    for sid, r in res.items():
        prev = d["results"].get(sid, {})
        d["results"][sid] = {**prev, **r, "lookahead_ok": bool(prev.get("lookahead_ok", True)) and r["eth_lookahead_ok"]}
    path.write_text(json.dumps(d, indent=1, default=str))
    return res


if __name__ == "__main__":
    YCK.main()
    check_eth(YCK.CUTS)
    import json
    res = json.loads((HERE / "results" / "checks.json").read_text())["results"]
    bad = [s for s, r in res.items() if r.get("error") or not r.get("lookahead_ok") or r.get("fill_problems")]
    print("checked", len(res), "failed", bad)
