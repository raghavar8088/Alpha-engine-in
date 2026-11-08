"""Does the paper desk reproduce the liquidity-sweep study? Run on a research machine (it needs the study's data):

    python -I test_liquidity.py [sessions_to_compare=25]

1. WINDOW: every LS book is run as the desk runs it, with a 20-session warm-up and then the last sessions. Its trades
   are compared with the study's saved trades (backend/research/liquidity_sweep_2026_11/results/versions/trades.csv.gz)
   over those sessions: entry time, side, entry, stop, target, exit, exit reason and R.
2. AS-OF: the last session is cut at several minutes and replayed as if live.
   - Every trade finished at the cut must equal the full-day run.
   - A trade still running must be flagged open by runner.docs_from.
   - No trade may appear that the full day does not have.
"""

from __future__ import annotations

import csv
import gzip
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("IDX1M_DIR", str(HERE.parents[0] / "backend" / "research" / "index_intraday_2026_10" / "data" / "1m"))
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import runner as R  # noqa: E402
from research import BM, RESEARCH  # noqa: E402

COMPARE = int(sys.argv[1]) if len(sys.argv) > 1 else 25
IST = timezone(timedelta(hours=5, minutes=30))
MARKETS = {"NIFTY": BM.load("NIFTY"), "BANKNIFTY": BM.load("BANKNIFTY")}   # the study's own data, the study's loader
import liquidity_sweep as LSW  # noqa: E402  (after the loader, which may import the full strategy library itself)

REASON = {"15:15": "time", "breakeven": "be_stop", "stop": "stop", "target": "target"}
FAILS: list[str] = []


def hhmm(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), IST).strftime("%H:%M")


def cut_row(m, last_row: int):
    key = np.repeat(m.date.astype(np.int64), m.d1 - m.d0)[:last_row + 1]
    s = slice(0, last_row + 1)
    return BM._finish(m.name, m.t[s], m.o[s], m.h[s], m.l[s], m.c[s], m.half[s], m.vol[s], key, False)


def study_trades() -> dict:
    out: dict = {}
    with gzip.open(RESEARCH / "liquidity_sweep_2026_11" / "results" / "versions" / "trades.csv.gz", "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r["version"], []).append(r)
    return out


def close(a: float, b: float, tol: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= tol


def window_check(study: dict) -> tuple[int, int]:
    total = same = 0
    for a in [x for x in C.ACCOUNTS if x.source == C.LS]:
        market, v = a.books[0]
        m = MARKETS[market]
        minutes = LSW.VERSIONS[v][2]
        first = str(m.date[max(0, m.n_days - COMPARE)])
        got = LSW.run(v, market, m, first, {})
        want = [r for r in study.get(v, []) if r["date"] >= first]
        mine = {(t.date, hhmm(m.t[t.entry_k] - 60 * minutes), "long" if t.side > 0 else "short"): t for t in got}
        theirs = {(r["date"], r["entry_time"], r["side"]): r for r in want}
        total += len(theirs)
        bad = []
        for k, r in theirs.items():
            t = mine.get(k)
            if t is None:
                bad.append(f"missing {k}")
                continue
            tgt = float(r["target"]) if r["target"] not in ("", "None") else math.nan
            reason = "stop" if t.reason == "stop_gap" else t.reason
            ok = (close(t.entry, float(r["entry"]), 0.006) and close(t.stop, float(r["stop"]), 0.006)
                  and close(t.target, tgt, 0.006) and close(t.exit, float(r["exit"]), 0.006)
                  and reason == REASON[r["exit_reason"]] and close(t.r_net, float(r["r_net"]), 2e-4)
                  and close(t.r_gross, float(r["r_gross"]), 2e-4))
            if ok:
                same += 1
            else:
                bad.append(f"{k}: desk {t.entry:.2f}/{t.stop:.2f}/{t.exit:.2f} {t.reason} {t.r_net:+.4f}R vs study "
                           f"{r['entry']}/{r['stop']}/{r['exit']} {r['exit_reason']} {r['r_net']}R")
        extra = [k for k in mine if k not in theirs]
        bad += [f"extra {k}" for k in extra]
        print(f"{a.id:6} {v:4} {market:9} from {first}: study {len(theirs):3d}, desk {len(mine):3d}, identical "
              f"{len(theirs) - sum(1 for b in bad if not b.startswith('extra')):3d}" + (f"  <-- {bad[:3]}" if bad else ""))
        if bad:
            FAILS.append(f"window {a.id}")
    return same, total


def asof_check() -> int:
    checked = 0
    for a in [x for x in C.ACCOUNTS if x.source == C.LS]:
        market, v = a.books[0]
        m = MARKETS[market]
        d = m.n_days - 1
        first = str(m.date[max(0, d - 3)])
        full = {(t.entry_k, t.side): t for t in LSW.run(v, market, m, first, {})}
        for minute in (40, 95, 160, 240, 330):
            last_row = int(m.d0[d]) + minute
            mc = cut_row(m, last_row)
            got = LSW.run(v, market, mc, first, {})
            docs = R.docs_from(got, mc, a.id, market, False, str(m.date[d]))
            for t, doc in zip(got, docs):
                checked += 1
                f = full.get((t.entry_k, t.side))
                if f is None:
                    FAILS.append(f"as-of {a.id} minute {minute}: a trade the full day does not have ({hhmm(m.t[t.entry_k])})")
                elif doc["open"]:
                    if f.exit_k <= last_row:
                        FAILS.append(f"as-of {a.id} minute {minute}: flagged open but the full day closed it by the cut")
                elif (t.exit_k, t.reason, round(t.exit, 4), round(t.r_net, 6)) != (f.exit_k, f.reason, round(f.exit, 4), round(f.r_net, 6)):
                    FAILS.append(f"as-of {a.id} minute {minute}: finished trade differs from the full day")
            for (k, side), f in full.items():   # every full-day trade entered and finished before the cut is present
                if f.exit_k <= last_row and (k, side) not in {(t.entry_k, t.side) for t in got}:
                    FAILS.append(f"as-of {a.id} minute {minute}: a finished trade is missing at the cut")
    return checked


if __name__ == "__main__":
    print("NIFTY rows to", MARKETS["NIFTY"].date[-1], "| BANKNIFTY rows to", MARKETS["BANKNIFTY"].date[-1])
    same, total = window_check(study_trades())
    print(f"\nWINDOW: {same} of {total} study trades reproduced exactly")
    n = asof_check()
    print(f"AS-OF: {n} cut-session trades checked")
    print("FAILED: " + "; ".join(FAILS[:12]) if FAILS else "ALL CHECKS PASS")
    sys.exit(1 if FAILS else 0)
