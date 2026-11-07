"""Does the paper desk reproduce the backtest? Run on a research machine (needs the studies' data caches):

    python -I test_fidelity.py [sessions_to_compare=10]

1. WINDOW: each book is run on only a recent slice of history (warm-up plus the last sessions), as the desk does, and its
   trades are compared with the study's saved trades over those last sessions. Differences here mean too short a warm-up.
2. AS-OF: each book is run on data cut at several moments of a session. Every trade already finished at the cut must be
   identical to the full-day run, and no trade may appear that the full day does not have.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("IDX1M_DIR", str(Path(__file__).resolve().parents[1] / "backend" / "research" / "index_intraday_2026_10" / "data" / "1m"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import runner as R  # noqa: E402
from research import BM, RESEARCH, YM  # noqa: E402

COMPARE = int(sys.argv[1]) if len(sys.argv) > 1 else 10
WARM = {"NIFTY": 60, "BANKNIFTY": 60, "XAUUSD": 30, "EURUSD": 30, "GBPUSD": 30, "NAS100": 30}
RES = {C.BB: RESEARCH / "booming_bulls_2026_11" / "results" / "trades", C.YT: RESEARCH / "youtube_top20_2026_11" / "results" / "trades"}


def cut_days(m, d_from: int, d_to: int | None = None):
    """Days d_from .. d_to-1 of a Minutes, rebuilt with the same builder the desk uses."""
    d_to = m.n_days if d_to is None else d_to
    a, z = int(m.d0[d_from]), int(m.d1[d_to - 1])
    key = np.repeat(m.date[d_from:d_to].astype(np.int64), (m.d1 - m.d0)[d_from:d_to])
    return BM._finish(m.name, m.t[a:z], m.o[a:z], m.h[a:z], m.l[a:z], m.c[a:z], m.half[a:z], m.vol[a:z], key, False)


def cut_row(m, last_row: int):
    key = np.repeat(m.date.astype(np.int64), m.d1 - m.d0)[:last_row + 1]
    return BM._finish(m.name, m.t[:last_row + 1], m.o[:last_row + 1], m.h[:last_row + 1], m.l[:last_row + 1], m.c[:last_row + 1],
                      m.half[:last_row + 1], m.vol[:last_row + 1], key, False)


def run(a, market, v, m):
    cache: dict = {}
    if a.source == C.BB:
        other = None
        if a.id == "BB-03":
            bn = BM.load("BANKNIFTY")
            days = np.searchsorted(bn.date, m.date[0])
            bn = cut_days(bn, int(days))
            other = (bn, R._bars(bn, (5,), {}))
        return R.run_bb(a.id, v, m, cache, other)[0]
    return R.run_yt(a.id, v, market, YM._as_mkt(m, market, market, YM.COSTS[market]), cache)[0]


def saved(a, market, v, full, first_date):
    path = RES[a.source] / f"{a.id}_{market}_{v}.csv.gz"
    if not path.exists():
        return None
    out = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["date"] >= first_date:
                out[int(full.t[int(r["entry_k"])])] = (int(r["side"]), int(full.t[int(r["exit_k"])]), r["reason"], round(float(r["r_net"]), 3))
    return out


def trades_as(tr, m):
    return {int(m.t[t.entry_k]): (int(t.side), int(m.t[t.exit_k]), t.reason, round(float(t.r_net), 3)) for t in tr}


def main():
    report = {"window": {}, "asof": {}}
    fulls: dict = {}
    for a in C.ACCOUNTS:
        for market, v in a.books:
            if a.source not in RES or C.MONEY[market].group not in ("index", "global") or market == "AAPL":
                continue
            if R.is_overnight(a.id, market):
                continue                      # replayed from a fixed start, so the warm-up never moves
            full = fulls.setdefault(market, BM.load(market))
            d0 = full.n_days - COMPARE - WARM[market]
            m = cut_days(full, d0)
            first = str(full.date[full.n_days - COMPARE])
            want = saved(a, market, v, full, first)
            if want is None:
                report["window"][f"{a.id}|{market}"] = "no saved trades"
                continue
            got = {k: x for k, x in trades_as(run(a, market, v, m), m).items() if str(np.datetime64(int(k), "s").astype("datetime64[D]")) >= first[:4]}
            got = {k: x for k, x in got.items() if k >= int(full.t[full.d0[full.n_days - COMPARE]])}
            same = sum(1 for k in want if got.get(k) == want[k])
            report["window"][f"{a.id}|{market}"] = {"saved": len(want), "paper": len(got), "same": same}
            # as-of: three cuts inside the last compared session
            d = full.n_days - 2
            base_m = cut_days(full, d0, full.n_days)
            whole = trades_as(run(a, market, v, base_m), base_m)
            a0, a1 = int(base_m.d0[base_m.n_days - 2]), int(base_m.d1[base_m.n_days - 2])
            bad = checked = 0
            for frac in (0.3, 0.55, 0.8):
                row = a0 + int((a1 - a0) * frac)
                cm = cut_row(base_m, row)
                part = trades_as(run(a, market, v, cm), cm)
                tcut = int(base_m.t[row])
                for k, x in part.items():
                    if k > tcut:
                        continue
                    finished = x[1] < tcut        # exit strictly before the end of the data
                    if finished:
                        checked += 1
                        if whole.get(k) != x:
                            bad += 1
                    elif k not in whole:
                        bad += 1
            report["asof"][f"{a.id}|{market}"] = {"checked": checked, "bad": bad}
    w = {k: v for k, v in report["window"].items() if isinstance(v, dict)}
    print("WINDOW books", len(w), "trades saved", sum(v["saved"] for v in w.values()), "paper", sum(v["paper"] for v in w.values()),
          "identical", sum(v["same"] for v in w.values()))
    for k, v in w.items():
        if v["saved"] != v["same"] or v["paper"] != v["saved"]:
            print("  differs", k, v)
    print("  not comparable:", [k for k, v in report["window"].items() if not isinstance(v, dict)])
    s = report["asof"]
    print("AS-OF books", len(s), "trades checked", sum(v["checked"] for v in s.values()), "bad", sum(v["bad"] for v in s.values()))
    for k, v in s.items():
        if v["bad"]:
            print("  bad", k, v)
    (Path(__file__).parent / "fidelity_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
