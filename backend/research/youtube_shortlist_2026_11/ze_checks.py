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


def _load_base():
    base = _orig_load()
    base.pop("ETHUSD", None)
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

if __name__ == "__main__":
    YCK.main()
    import json
    res = json.loads((HERE / "results" / "checks.json").read_text())["results"]
    bad = [s for s, r in res.items() if r.get("error") or not r.get("lookahead_ok") or r.get("fill_problems")]
    print("checked", len(res), "failed", bad)
