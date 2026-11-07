"""Books that may hold overnight, and the daily markets, as the desk will run them at launch:
  - forex overnight books with only about 21 sessions of warm-up (what Yahoo's 30 days of 1-minute bars allow),
  - intraday forex, gold and Nasdaq books with the same short warm-up,
  - S&P 500, Nasdaq and Nifty daily rows from about 480 sessions,
  - NSE daily stocks from the desk's trimmed seed panel (written here to a temp folder).
Each is compared with the study's saved trades.     python -I test_daily.py [sessions=30]
"""

import csv
import gzip
import os
import sys
import tempfile
from dataclasses import replace  # noqa: F401
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_daily_")
os.environ.setdefault("IDX1M_DIR", str(HERE.parent / "backend/research/index_intraday_2026_10/data/1m"))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import feeds as F  # noqa: E402
import make_seed  # noqa: E402
import runner as R  # noqa: E402
from research import BM, RESEARCH, YM  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
T = {C.BB: RESEARCH / "booming_bulls_2026_11" / "results" / "trades", C.YT: RESEARCH / "youtube_top20_2026_11" / "results" / "trades"}
LAUNCH_WARM = 21


def saved(a, market, v, first):
    p = T[a.source] / f"{a.id}_{market}_{v}.csv.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rt", newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["date"] >= first]


def cut_days(m, d_from):
    a = int(m.d0[d_from])
    key = np.repeat(m.date[d_from:].astype(np.int64), (m.d1 - m.d0)[d_from:])
    return BM._finish(m.name, m.t[a:], m.o[a:], m.h[a:], m.l[a:], m.c[a:], m.half[a:], m.vol[a:], key, False)


def cut_daily(m, a):
    n = len(m.t) - a
    k = YM.Mkt(m.name, m.t[a:], m.o[a:], m.h[a:], m.l[a:], m.c[a:], m.half[a:], m.vol[a:], m.ist[a:], m.ny[a:], np.arange(n, dtype=np.int32),
               np.arange(n, dtype=np.int64), np.arange(1, n + 1, dtype=np.int64), m.date[a:], m.prev_ok[a:], m.excluded[a:], m.cost)
    k.split_key, k.overnight = m.split_key, True
    return k


# ── global books, the short warm-up they will have at launch ─────────────────────────
tot = {"saved": 0, "paper": 0, "same": 0}
diffs = []
fulls = {}
for a in C.ACCOUNTS:
    if a.source not in T:
        continue
    for market, v in a.books:
        if C.MONEY[market].group != "global" or market == "AAPL":
            continue
        full = fulls.setdefault(market, BM.load(market))
        d0 = full.n_days - N - LAUNCH_WARM
        first = str(full.date[full.n_days - N])
        want = saved(a, market, v, first)
        if want is None:
            diffs.append((a.id, market, "no saved trades"))
            continue
        m = cut_days(full, d0)
        tr = R.run_bb(a.id, v, m, {})[0] if a.source == C.BB else R.run_yt(a.id, v, market, YM._as_mkt(m, market, market, YM.COSTS[market]), {})[0]
        got = {int(m.t[t.entry_k]): (int(t.side), t.reason, float(t.r_net)) for t in tr if t.date >= first}
        w = {int(full.t[int(r["entry_k"])]): (int(r["side"]), r["reason"], float(r["r_net"])) for r in want}
        same = sum(1 for k in w if k in got and got[k][:2] == w[k][:2] and abs(got[k][2] - w[k][2]) < 0.002)   # saved files round to 6 places
        tot["saved"] += len(w); tot["paper"] += len(got); tot["same"] += same
        if same != len(w) or len(got) != len(w):
            diffs.append((a.id, market, v, "saved", len(w), "paper", len(got), "same", same, "overnight" if R.is_overnight(a.id, market) else "intraday"))
print("GLOBAL at launch warm-up:", tot)
for x in diffs:
    print("  ", x)

# ── daily indices ────────────────────────────────────────────────────────────────────
tot = {"saved": 0, "paper": 0, "same": 0}
for a in C.ACCOUNTS:
    if a.source != C.YT:
        continue
    for market, v in a.books:
        if market not in ("SPX500_D", "NAS100_D", "NIFTY_D"):
            continue
        full = YM.load(market)
        m = cut_daily(full, max(0, len(full.t) - 480))
        want = saved(a, market, v, str(m.date[260]))
        tr = R.run_yt(a.id, v, market, m, {})[0]
        got = {t.date: (int(t.side), t.reason, round(float(t.r_net), 2)) for t in tr if t.date >= str(m.date[260])}
        w = {r["date"]: (int(r["side"]), r["reason"], round(float(r["r_net"]), 2)) for r in want}
        same = sum(1 for k in w if got.get(k) == w[k])
        tot["saved"] += len(w); tot["paper"] += len(got); tot["same"] += same
        if same != len(w) or len(got) != len(w):
            print("   differs", a.id, market, "saved", w, "paper", got)
print("DAILY indices:", tot)

# ── NSE daily stocks from the seed panel ─────────────────────────────────────────────
print("seed", make_seed.write_seed(F.NSE_FILE))
ms = F.nse_daily_markets()
print("daily stock markets", len(ms), "last", max(str(m.date[-1]) for m in ms))
last = max(str(m.date[-1]) for m in ms)
all_dates = sorted({str(d) for m in ms[:200] for d in m.date})
first = all_dates[-N]
for a, market, v in [x for x in C.books_in("daily") if x[1] == "NSED"]:
    got = {}
    for m in ms:
        for t in R.run_yt(a.id, v, market, m, {})[0]:
            if t.date >= first:
                got[(m.name, t.date, int(t.side))] = (t.reason, round(float(t.r_net), 2))
    want = saved(a, market, v, first) or []
    w = {(r["market"], r["date"], int(r["side"])): (r["reason"], round(float(r["r_net"]), 2)) for r in want}
    same = sum(1 for k in w if got.get(k) == w[k])
    print(a.id, market, v, "saved", len(w), "paper", len(got), "same", same,
          "| differ", [(k, w[k], got.get(k)) for k in list(w) if got.get(k) != w[k]][:3], "| only paper", [k for k in got if k not in w][:3])
