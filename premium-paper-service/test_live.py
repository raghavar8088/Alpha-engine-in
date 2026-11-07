"""The live path, on a past session replayed as if it were today: the store is cut at the evening before, the day's bars up to a
chosen time are handed in as the backend would hand them, and the books run. Every trade finished by that time must equal
the same trade from the full day, every position still running must be flagged open, and nothing may appear that the
full day does not have. Needs the box's stores.     python -I test_live.py <day> [<day before>]"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("PREMIUM_DATA_DIR", "/tmp/premium_live_test")

import feeds as F  # noqa: E402
import catalog as C  # noqa: E402
import runner as R  # noqa: E402
import vwap_run  # noqa: E402
from research import YM  # noqa: E402
from settings import IST  # noqa: E402

DAY = sys.argv[1]
BEFORE = sys.argv[2]


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=IST)


def key(d):
    return (d["sym"], d["entry_t"], d["side"])


def compare(name, partial, full, cut_t):
    fm = {key(d): d for d in full}
    bad, finished, running = [], 0, 0
    for d in partial:
        k = key(d)
        if k not in fm:
            bad.append(("not in the full day", k))
        elif d["open"]:
            running += 1
            if d["exit_t"] is not None:
                bad.append(("open with an exit", k))
        else:
            finished += 1
            f = fm[k]
            if (d["exit_t"], d["reason"]) != (f["exit_t"], f["reason"]) or abs(d["exit"] - f["exit"]) > 1e-6:
                bad.append(("differs", k, d["reason"], f["reason"], d["exit"], f["exit"]))
    missed = [k for k, f in fm.items() if f["entry_t"] < cut_t - 1800 and k not in {key(d) for d in partial}]
    return {"name": name, "partial": len(partial), "finished": finished, "running": running, "full": len(full), "bad": bad[:4], "missed": missed[:4]}


out = []
since = datetime.fromisoformat(DAY).date() - timedelta(days=95)

# ── indices ───────────────────────────────────────────────────────────────────────────
evening = at(DAY, "18:00")
for name in ("NIFTY", "BANKNIFTY"):
    full, _, _ = F.index_market(name, since, None, evening)
    minutes = F.II._read(name, since)
    base = int(at(DAY, "09:15").timestamp())
    for hhmm in ("10:33", "12:07", "14:41"):
        now = at(DAY, hhmm)
        rows = [[int(r[0]), *map(float, r[1:6])] for r in minutes if base <= r[0] < int(now.timestamp()) - (now.minute * 0)]
        real_read = F.II._read

        def before_today(n, s):
            a = real_read(n, s)
            return a[a[:, 0] < base]

        F.II._read = before_today
        try:
            part, live_day, disk = F.index_market(name, since, rows, now)
        finally:
            F.II._read = real_read
        assert live_day == DAY and disk < DAY, (live_day, disk)
        for a, mk, v in C.books_in("index"):
            if mk != name:
                continue
            if a.source == C.BB:
                other = None
                if a.id == "BB-03":
                    continue
                pt = R.run_bb(a.id, v, part, {}, other)[0]
                ft = R.run_bb(a.id, v, full, {}, other)[0]
            else:
                pt = R.run_yt(a.id, v, mk, YM._as_mkt(part, mk, mk, YM.COSTS[mk]), {})[0]
                ft = R.run_yt(a.id, v, mk, YM._as_mkt(full, mk, mk, YM.COSTS[mk]), {})[0]
            pd = [d for d in R.docs_from(pt, part, a.id, mk, False, live_day) if d["date"] == DAY]
            fd = [d for d in R.docs_from(ft, full, a.id, mk, False, None) if d["date"] == DAY]
            out.append(compare(f"{a.id}|{mk}|{hhmm}", pd, fd, int(now.timestamp())))

# ── stocks ────────────────────────────────────────────────────────────────────────────
print("panel full", F.build_panel(evening))
full_panel = F.Panel(None, evening)
assert full_panel.days[-1] == DAY, full_panel.days[-1]
fdocs = {}
j = len(full_panel.days) - 1
for i in range(len(full_panel.names)):
    m = full_panel.market(i)
    if m is None:
        continue
    cache = {}
    for a, mk, v in C.books_in("stocks"):
        if mk == "VWAP":
            continue
        tr = R.run_yt(a.id, v, mk, m, cache)[0]
        fdocs.setdefault(a.id, []).extend(d for d in R.docs_from(tr, m, a.id, mk, False, None) if d["date"] == DAY)
fv = vwap_run.run(full_panel, {DAY})
base = int(at(DAY, "09:15").timestamp())
rows_by_sym = {}
for i, s in enumerate(full_panel.names):
    mat = {k: full_panel.a[k][i, j] for k in "ohlcv"}
    rows_by_sym[s] = [[base + 300 * b, *(float(mat[k][b]) for k in "ohlcv")] for b in range(75) if mat["c"][b] == mat["c"][b]]
print("panel before", F.build_panel(at(BEFORE, "18:00")))
for hhmm in ("10:33", "12:07", "14:41"):
    now = at(DAY, hhmm)
    close_t = int(now.timestamp()) - 300
    live = {s: [r for r in rows if r[0] <= close_t] for s, rows in rows_by_sym.items()}
    p = F.Panel(live, now)
    assert p.live_day == DAY and p.days[-1] == DAY and p.disk_last == BEFORE, (p.live_day, p.days[-1], p.disk_last)
    pdocs = {}
    for i in range(len(p.names)):
        m = p.market(i)
        if m is None:
            continue
        cache = {}
        for a, mk, v in C.books_in("stocks"):
            if mk == "VWAP":
                continue
            tr = R.run_yt(a.id, v, mk, m, cache)[0]
            pdocs.setdefault(a.id, []).extend(d for d in R.docs_from(tr, m, a.id, mk, False, DAY) if d["date"] == DAY)
    for sid, docs in pdocs.items():
        out.append(compare(f"{sid}|NSE|{hhmm}", docs, fdocs.get(sid, []), int(now.timestamp())))
    pv = vwap_run.run(p, {DAY})
    for setup, docs in pv.items():
        out.append(compare(f"VWAP-{setup}|{hhmm}", docs, fv[setup], int(now.timestamp())))

bad = [o for o in out if o["bad"] or o["missed"]]
print(json.dumps({"checks": len(out), "partial_trades": sum(o["partial"] for o in out), "finished": sum(o["finished"] for o in out),
                  "running": sum(o["running"] for o in out), "with_problems": len(bad)}))
for o in bad[:25]:
    print(o)
