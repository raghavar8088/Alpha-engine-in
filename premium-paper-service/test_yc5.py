"""The gold channels 21-40 books (source youtube_gold) through the desk's own plumbing (run from a patched desk copy):
    python -I test_yc5.py                      research gold minutes (the look-ahead checks' data)
    PREMIUM_TEST_GOLD_DIR=<dir with DELTA_XAUTUSD/*.npz> python -I test_yc5.py     also the desk's own Delta candles
1. the catalog's YC5 accounts are the registry's strategies (ids, names, channels; gold on Delta XAUTUSD), every market
   has money rules and a segment, ids are unique across the desk, the source is a YouTube-channel source;
2. every book runs through runner.run_yc, its documents have unique ids, the ledger sizes them; MA-02 is the one
   overnight book, the others are intraday;
3. a book that starts mid-way starts flat;
4. the YC5 books get their own start (cycle and segments alike), the channel books' states, and enter only on fresh
   bars like the 20-channel, shortlist and Trade Room books."""

import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_yc5_")
HERE = Path.cwd()
ROOT = Path(os.getenv("PREMIUM_REPO_ROOT") or HERE.parent)
os.environ.setdefault("PREMIUM_REPO_ROOT", str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend" / "research" / "youtube_channels11_2026_11"))
GOLD_DIR = os.getenv("PREMIUM_TEST_GOLD_DIR", "")
if GOLD_DIR:
    shutil.copytree(GOLD_DIR, Path(os.environ["PREMIUM_DATA_DIR"]) / "min1" / "DELTA_XAUTUSD")

import numpy as np  # noqa: E402

if sys.platform == "win32" and "resource" not in sys.modules:    # cycle.py reads its memory peak with Linux's resource
    import types
    sys.modules["resource"] = types.SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _w: types.SimpleNamespace(ru_maxrss=0))

import catalog as C  # noqa: E402
import cycle as CY  # noqa: E402
import feeds as F  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
import segments as SG  # noqa: E402
import settings as S  # noqa: E402
import yc_markets as MK  # noqa: E402
import yt_markets as YM  # noqa: E402
import zg_strategies as ZG  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


ys = {a.id: a for a in C.ACCOUNTS if a.source == C.YC5}
reg = {r.sid: r for r in ZG._NEW}
check(f"{len(reg)} accounts, one per strategy", set(ys) == set(reg), f"{len(ys)} accounts")
bad = [s for s, a in ys.items() if a.name != reg[s].name or a.channel != reg[s].chan]
check("names and channels agree with the registry", not bad, str(bad[:5]))
check("every book is gold on Delta XAUTUSD", all(a.books == (("XAUTUSD", "V0"),) for a in ys.values()))
check("every market has money rules and a segment", all(mk in C.MONEY and mk in SG.SEGMENT for a in ys.values() for mk, _ in a.books))
check("ids unique across the desk", len(C.BY_ID) == len(C.ACCOUNTS), f"{len(C.ACCOUNTS)} accounts")
check("YC5 is a YouTube-channel source", C.YC5 in C.YC_SOURCES and all(CY._is_yc(a) for a in ys.values()))
check("Rs 10 lakh each", S.CAPITAL == 1_000_000)
check("the gold week start", S.YC5_START_T == int(datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc).timestamp())
      or os.getenv("PREMIUM_YC5_START") is not None, str(S.YC5_START_T))

markets = {"research gold (60 days)": MK.window("XAUUSD", 60)}
if GOLD_DIR:
    m = F.gold_market(date(2026, 9, 24))
    markets["Delta XAUTUSD (the desk's store)"] = YM._as_mkt(m, "XAUUSD", "XAUUSD", F.yt_cost("XAUUSD"))
rates = {"2026-10-01": 94.0}
for label, m in markets.items():
    print(f"-- {label}: {m.n_days} days, {len(m.t)} minutes")
    cache: dict = {}
    for sid, a in sorted(ys.items()):
        tr, _ = R.run_yc(sid, "XAUTUSD", m, cache, {}, None, risk_pct=C.MONEY["XAUTUSD"].risk_pct)
        docs = R.yc_docs(tr, m, sid, "XAUTUSD", R.is_overnight(sid, "XAUTUSD"), None)
        ids = [d["_id"] for d in docs]
        res = L.walk(docs, rates, "2026-12-31")
        sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
        check(f"{sid} runs and sizes", len(ids) == len(set(ids)) and np.isfinite(res["summary"]["equity"])
              and (sized > 0 or not docs), f"trades {len(docs)} sized {sized} equity {res['summary']['equity']:,.0f}")
check("MA-02 is the one overnight book", [s for s in ys if R.is_overnight(s, "XAUTUSD")] == ["MA-02"])

m = markets["research gold (60 days)"]
t_mid = int(m.t[len(m.t) // 2])
for sid in ("AF-03", "PF-01", "MA-02", "CA-01", "TQ-05"):
    tr, _ = R.run_yc(sid, "XAUTUSD", m, {}, {}, None, since_t=t_mid)
    check(f"{sid} starts flat at its start minute", all(int(m.t[t.entry_k]) >= t_mid for t in tr), f"{len(tr)} trades")

start = datetime.fromtimestamp(S.YC5_START_T, timezone.utc)
for sid in ("AF-04", "MA-02", "TQ-05"):
    a = C.BY_ID[sid]
    check(f"{sid} starts at YC5_START_T (cycle and segments)", CY._yc_start(a) == (S.YC5_START_T, S.YC5_START_DATE)
          and SG._start_of("XAUTUSD", a) == start)
acct = C.BY_ID["TU-02"]
now = datetime.now(timezone.utc)
blank = {"open": 0, "open_since": None}
live = {"state": "live", "reason": "Last bar now.", "short": ""}
if now >= start:
    st, why = SG._book_state(acct, "XAUTUSD", "TU-02|XAUTUSD", blank, live, {"n_today": 0}, {}, {}, now)
    check("a live market without a setup is running", st == "running" and why == "Running — waiting for signal.", why)
else:
    st, why = SG._book_state(acct, "XAUTUSD", "TU-02|XAUTUSD", blank, live, {"n_today": 0}, {}, {}, now)
    check("before its start the book waits", st == "waiting", why)
closed = {"state": "closed", "reason": "Gold is closed for the weekend.", "short": "Gold is closed for the weekend."}
st, why = SG._book_state(acct, "XAUTUSD", "TU-02|XAUTUSD", blank, closed, {}, {}, {}, max(now, start))
check("a closed market arms the book for the open", st == "armed", why)


class _Trades:
    def __init__(self, ids):
        self.ids = ids

    def find(self, *_a, **_k):
        return [{"_id": i} for i in self.ids]


class _DB:
    premium_trades = _Trades(["known"])


old = int(datetime.now(timezone.utc).timestamp()) - 6 * 3600
fresh = int(datetime.now(timezone.utc).timestamp()) - 60
docs = [{"_id": "known", "entry_t": old}, {"_id": "late", "entry_t": old}, {"_id": "fresh", "entry_t": fresh}]
kept = [d["_id"] for d in CY._fresh_only(_DB(), acct, "XAUTUSD", docs)]
check("new entries only on fresh bars (a known trade stays)", kept == ["known", "fresh"], str(kept))
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
