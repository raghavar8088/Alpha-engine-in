"""Correctness checks of the four-topic study's strategies with the 11-channel study's harness (yc_checks): the
truncation (look-ahead) test - every market cut at random minutes, the signals and the closed trades known at the cut
must equal the full run's field by field - and the fill test (every fill inside its row's range plus costs).
Counts only: nothing here measures performance.

The MCX books run on zd_common.mcx_proxy (research gold minutes cut to MCX hours) because no crude, natural gas or
silver minutes exist locally: the checks test the code's use of time, not the market. Writes results/checks.json.

    python -I zd_checks.py [cuts=3] [SID,SID,...]
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zd_common as Z  # noqa: E402
import zd_strategies as ZS  # noqa: E402  (registers the records first)

_argv = sys.argv[1:]
sys.argv = [sys.argv[0]] + _argv
import numpy as np  # noqa: E402

import yc_checks as YCK  # noqa: E402
import yc_markets as MK  # noqa: E402
import yc_run as R  # noqa: E402

YCK.ONLY = set(_argv[1].split(",")) if len(_argv) > 1 else set(ZS.NEW)
YCK.HERE = HERE
YCK.DAYS = {"NIFTY": 150, "BANKNIFTY": 45, "XAUUSD": 45, "BTCUSD": 60, "MCXCRUDE": 90, "MCXNG": 90, "MCXSILVER": 90}

_full = MK.full


def _full_x(name: str):
    if name in Z.MCX_MARKETS:
        if name not in MK._FULL:
            MK._FULL[name] = Z.mcx_proxy(name)
        return MK._FULL[name]
    return _full(name)


MK.full = _full_x
_orig_load = YCK.load_base


def _load_base():
    base = _orig_load()
    for nm in ("EURUSD", "GBPUSD", "NAS100", "ETHUSD"):
        base.pop(nm, None)
    return base


YCK.load_base = _load_base


def run_strategy(sid: str, U) -> dict:
    st = R.STRATEGIES[sid]
    out = {}
    for market in st.markets:
        ms = U.market(market)
        if ms is None:
            continue
        zneeds = {n for n in st.needs if str(n).startswith("zd_")}
        pool = ms if isinstance(ms, list) else None
        cx = R.contexts(set(st.needs), nifty=U.market("NIFTY"), pool=pool) if (zneeds and pool is not None) else {}
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
