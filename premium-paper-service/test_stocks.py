"""Stock pools: build the desk's panel from the research copy of the 5-minute store, as of a past evening, and compare each
pool's trades over the last sessions with the study's saved trades. Also times a cycle.
    python -I test_stocks.py [as_of=2026-10-30] [sessions=5]"""
import csv, gzip, os, sys, tempfile, time
from datetime import datetime
from pathlib import Path

os.environ["INTRADAY_DATA_DIR"] = "D:/intraday_ai_data/intraday"
os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_test_")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("IDX1M_DIR", str(HERE.parent / "backend/research/index_intraday_2026_10/data/1m"))

import catalog as C  # noqa: E402
import feeds as F  # noqa: E402
import runner as R  # noqa: E402
import vwap_run  # noqa: E402
from research import RESEARCH  # noqa: E402
from settings import IST  # noqa: E402

as_of = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
compare = int(sys.argv[2]) if len(sys.argv) > 2 else 5
now = datetime.fromisoformat(as_of + "T18:00:00").replace(tzinfo=IST)
t0 = time.time()
print("panel", F.build_panel(now), f"{time.time() - t0:.1f}s", flush=True)
t0 = time.time()
panel = F.Panel(None, now)
print("load", f"{time.time() - t0:.1f}s", "days", panel.days[0], panel.days[-1], flush=True)
days = set(panel.days[-compare:])
books = [(a, mk, v) for a, mk, v in C.books_in("stocks") if mk != "VWAP" and a.source == C.YT]   # the saved study books
got = {(a.id, mk): [] for a, mk, _ in books}
t0 = time.time()
per = {}
for i in range(len(panel.names)):
    m = panel.market(i)
    if m is None:
        continue
    cache = {}
    for a, mk, v in books:
        t1 = time.time()
        tr, _ = R.run_yt(a.id, v, mk, m, cache)
        per[a.id] = per.get(a.id, 0) + time.time() - t1
        got[(a.id, mk)] += [x for x in R.docs_from(tr, m, a.id, mk, False, None) if x["date"] in days]
print("pool run", f"{time.time() - t0:.1f}s", {k: round(v, 1) for k, v in per.items()}, flush=True)
t0 = time.time()
vw = vwap_run.run(panel, set(panel.days[-1:]))
print("vwap run, one day", f"{time.time() - t0:.1f}s", {k: len(v) for k, v in vw.items()}, flush=True)
T = RESEARCH / "youtube_top20_2026_11" / "results" / "trades"
for a, mk, v in books:
    path = T / f"{a.id}_{mk}_{v}.csv.gz"
    want = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["date"] in days:
                want[(r["market"], r["date"], int(r["side"]), round(float(r["entry"]), 2))] = (round(float(r["exit"]), 2), r["reason"])
    have = {(x["sym"], x["date"], x["side"], round(x["entry"], 2)): (round(x["exit"], 2), x["reason"]) for x in got[(a.id, mk)]}
    same = sum(1 for k in want if have.get(k) == want[k])
    print(a.id, mk, "saved", len(want), "paper", len(have), "identical", same, flush=True)
    print("   after the 4-slot rule:", len(R.take_slots([{**x, "rank": 1} for x in got[(a.id, mk)]], 4)), "of", len(got[(a.id, mk)]), flush=True)
