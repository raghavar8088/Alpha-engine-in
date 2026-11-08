"""Look-ahead check (the truncation test of the earlier studies): for every strategy and market, signals computed on
data cut at a random minute must equal the full run's signals that were already known at that minute. A rule that
peeks at later bars fails this. Writes results/checks.json.     python -I cp_checks.py [cuts=4]"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import cp_markets as CM  # noqa: E402
import cp_strategies as CS  # noqa: E402
from research_window import window  # noqa: E402

CUTS = int(sys.argv[1]) if len(sys.argv) > 1 else 4


def cut_rows(m, last_row: int):
    """The market's rows up to last_row (a partial day stays partial), rebuilt with the same builder."""
    if m.name == "BTCUSD":
        k = last_row + 1
        return CM.btc_market(m.t[:k], m.o[:k], m.h[:k], m.l[:k], m.c[:k], m.vol_all[:k], m.bv[:k])
    key = np.repeat(m.date.astype(np.int64), m.d1 - m.d0)[:last_row + 1]
    mm = CM.BM._finish(m.name, m.t[:last_row + 1], m.o[:last_row + 1], m.h[:last_row + 1], m.l[:last_row + 1],
                       m.c[:last_row + 1], m.half[:last_row + 1], m.vol[:last_row + 1], key, False)
    return CM.YM._as_mkt(mm, m.name, m.name, m.cost)


def sigs(st, market, m, other=None):
    B = CS.build_bars(m, CS.tfs_of(st, market))
    o = None
    if other is not None:
        o = (other, CS.build_bars(other, CS.tfs_of(st, market)))
    return {(s.k, s.side, round(s.stop, 6), round(s.entry_limit or 0.0, 6)) for s in CS.signals(st, market, m, B, {}, o)}


def main():
    rng = np.random.default_rng(7)
    out = {}
    mk_cache = {}
    for st in CS.STRATEGIES.values():
        for market in st.markets:
            if market not in mk_cache:
                mk_cache[market] = window(market, days=40)
            m = mk_cache[market]
            other = None
            comp = st.companion.get(market)
            if comp:
                if comp not in mk_cache:
                    mk_cache[comp] = window(comp, days=40)
                other = mk_cache[comp]
                if other is None:
                    out[f"{st.sid}|{market}"] = "no companion data"
                    continue
            full = sigs(st, market, m, other)
            ok = True
            for cut in rng.integers(len(m.t) // 3, len(m.t) - 10, CUTS):
                cm = cut_rows(m, int(cut))
                co = None
                if other is not None:
                    tcut = m.t[int(cut)]
                    oc = int(np.searchsorted(other.t, tcut, "right")) - 1
                    co = cut_rows(other, oc)
                part = sigs(st, market, cm, co)
                known_full = {x for x in full if x[0] < int(cut) - 1}
                known_part = {x for x in part if x[0] < int(cut) - 1}
                if known_full != known_part:
                    ok = False
                    diff = sorted(known_full ^ known_part)[:3]
                    out[f"{st.sid}|{market}|cut{int(cut)}"] = [list(map(float, d)) for d in diff]
            out[f"{st.sid}|{market}"] = ok
            print(st.sid, market, "signals", len(full), "look-ahead ok" if ok else "DIFFERS", flush=True)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "checks.json").write_text(json.dumps(out, indent=1))
    bad = [k for k, v in out.items() if v is False]
    print("combinations", sum(1 for v in out.values() if isinstance(v, bool)), "failed", bad)


if __name__ == "__main__":
    main()
