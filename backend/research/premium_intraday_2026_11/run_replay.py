"""Replay the six new strategies at every ladder level and target multiple over a period.

  python run_replay.py dev                 development period (walk-forward folds are cut from it afterwards)
  python run_replay.py final --prereg H    the untouched final period; refuses unless prereg.json hashes to H
  python run_replay.py final --prereg H --stress 2    the same with slippage x2 (x3: --stress 3)

One process per strategy (12 configurations each: 4 levels x 3 targets). Output in D:/premium_intraday_data/runs/<tag>/.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import pickle
import sys
import time
from dataclasses import replace

from common import DATA, PANEL, RUNS, HERE
import protocol as P
from pis.book import Book
from pis.config import Costs, Settings
from pis.replay import Panel, run
from pis.strategies import REGISTRY

STRIP = ("knew",)


def _pos(p):
    d = p.public()
    for k in STRIP:
        d.pop(k, None)
    d["side"] = p.side
    return d


def worker(args):
    sid, days, stress, out_dir, detail = args
    settings = Settings(costs=Costs(stress=stress))
    panel = Panel(str(PANEL), DATA)
    days = [d for d in panel.days if d in set(days)]
    strats, books = [], {}
    for lv in P.LEVELS:
        for tr in P.TARGETS:
            s = REGISTRY[sid](level=lv, target_R=tr)
            strats.append(s)
            key = f"{s.id}|{s.variant}|{s.level}"
            books[key] = Book(key, settings.risk)
    journal = [] if detail else None
    ends = {}

    def on_day(d, eng):
        for su in eng.setups:
            key = f"{su.strategy}|{su.variant}|{su.level}"
            e = ends.setdefault(key, {})
            e[su.status] = e.get(su.status, 0) + 1
        if journal is not None and len(journal) > 400_000:
            del journal[:200_000]

    t = time.time()
    log = run(panel, days, strats, settings, books, None, eligible={}, detail=bool(detail), journal=journal,
              on_day=on_day)
    res = {"sid": sid, "stress": stress, "log": log, "setup_ends": ends,
           "trades": {k: [_pos(p) for p in b.closed] for k, b in books.items()},
           "sessions": log["days"], "seconds": time.time() - t}
    with open(os.path.join(out_dir, f"{sid}.pkl"), "wb") as f:
        pickle.dump(res, f)
    if journal is not None:
        with open(os.path.join(out_dir, f"{sid}_journal.pkl"), "wb") as f:
            pickle.dump(journal, f)
    return sid, log["days"], round(time.time() - t, 1)


def prereg_hash() -> str:
    return hashlib.sha256((HERE / "prereg.json").read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("period", choices=["dev", "final", "post"])
    ap.add_argument("--prereg", default="")
    ap.add_argument("--stress", type=float, default=1.0)
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if a.period == "dev":
        lo, hi = P.DEV_START, P.DEV_END
    else:
        if not (HERE / "prereg.json").exists() or prereg_hash() != a.prereg:
            sys.exit("REFUSED: the final period opens only with the frozen prereg.json and its sha256 (--prereg)")
        lo, hi = (P.FINAL_START, P.FINAL_END) if a.period == "final" else (P.POST_START, P.POST_END)
    panel = Panel(str(PANEL), DATA)
    days = [d for d in panel.days if lo <= d <= hi]
    tag = f"{a.period}_x{a.stress:g}" + ("_detail" if a.detail else "")
    out = RUNS / tag
    out.mkdir(parents=True, exist_ok=True)
    sids = [s for s in REGISTRY if not a.only or s in a.only.split(",")]
    meta = {"period": a.period, "from": str(lo), "to": str(hi), "sessions": len(days), "stress": a.stress,
            "prereg": a.prereg or None, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    with mp.Pool(min(6, len(sids))) as pool:
        for r in pool.imap_unordered(worker, [(s, days, a.stress, str(out), a.detail) for s in sids]):
            print(r, flush=True)
    print("done", out)


if __name__ == "__main__":
    main()
