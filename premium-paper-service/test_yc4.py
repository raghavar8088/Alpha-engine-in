"""The Trade Room books through the desk's own plumbing, on research data (run from a patched desk copy):
    python -I test_yc4.py
1. the catalog's YC4 accounts are the registry's strategies (ids, names, markets; gold on Delta XAUTUSD), every market
   has money rules and a segment, ids are unique across the desk, the source is a YouTube-channel source;
2. every book runs through runner.run_yc, its documents have unique ids, and the ledger sizes them;
3. a book that starts mid-way starts flat;
4. the YC4 books get their own start (cycle and segments alike) and the channel books' states, and enter only on fresh
   bars like the 20-channel and shortlist books."""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_yc4_")
os.environ.setdefault("PREMIUM_YC4_START", "2026-01-11T00:00:00+00:00")
HERE = Path.cwd()
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend" / "research" / "youtube_channels11_2026_11"))

import numpy as np  # noqa: E402

if sys.platform == "win32" and "resource" not in sys.modules:    # cycle.py reads its memory peak with Linux's resource
    import types
    sys.modules["resource"] = types.SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _w: types.SimpleNamespace(ru_maxrss=0))

import catalog as C  # noqa: E402
import cycle as CY  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
import segments as SG  # noqa: E402
import settings as S  # noqa: E402
import yc_markets as MK  # noqa: E402
import zt_strategies as ZT  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


ys = {a.id: a for a in C.ACCOUNTS if a.source == C.YC4}
reg = {r.sid: r for r in ZT._NEW}
check(f"{len(reg)} accounts, one per strategy", set(ys) == set(reg), f"{len(ys)} accounts")
bad = [s for s, a in ys.items() if a.name != reg[s].name
       or tuple(C.YC_RULES_MARKET.get(mk, mk) if hasattr(C, "YC_RULES_MARKET") else ("XAUUSD" if mk == "XAUTUSD" else mk)
                for mk, _ in a.books) != reg[s].markets]
check("names and markets agree", not bad, str(bad[:5]))
check("gold books trade Delta XAUTUSD", all(mk != "XAUUSD" for a in ys.values() for mk, _ in a.books))
mk_all = {mk for a in ys.values() for mk, _ in a.books}
check("every market has money rules and a segment", all(mk in C.MONEY and mk in SG.SEGMENT for mk in mk_all), str(sorted(mk_all)))
check("ids unique across the desk", len(C.BY_ID) == len(C.ACCOUNTS), f"{len(C.ACCOUNTS)} accounts")
check("YC4 is a YouTube-channel source", C.YC4 in C.YC_SOURCES and all(CY._is_yc(a) for a in ys.values()))
check("Rs 10 lakh each", S.CAPITAL == 1_000_000)

data = {nm: MK.window(nm, 40) for nm in ("NIFTY", "BANKNIFTY", "XAUUSD")}
data["BTCUSD"] = MK.window("BTCUSD", 60)
rates = {"2026-10-01": 88.0}
for sid, a in sorted(ys.items()):
    docs = []
    for mk, _v in a.books:
        m = data["XAUUSD" if mk == "XAUTUSD" else mk]
        tr, _ = R.run_yc(sid, mk, m, {}, {}, None, risk_pct=C.MONEY[mk].risk_pct)
        docs += R.yc_docs(tr, m, sid, mk, R.is_overnight(sid, mk), None)
    ids = [d["_id"] for d in docs]
    res = L.walk(docs, rates, "2026-12-31")
    sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
    check(f"{sid} {','.join(mk for mk, _ in a.books)}", len(ids) == len(set(ids)) and np.isfinite(res["summary"]["equity"])
          and (sized > 0 or not docs), f"trades {len(docs)} sized {sized} equity {res['summary']['equity']:,.0f}")
    check(f"{sid} books are intraday", not any(R.is_overnight(sid, mk) for mk, _ in a.books))

for sid, mk in (("TR-02", "NIFTY"), ("TR-03", "BTCUSD"), ("TR-04", "XAUTUSD")):
    m = data["XAUUSD" if mk == "XAUTUSD" else mk]
    t_mid = int(m.t[len(m.t) // 2])
    tr, _ = R.run_yc(sid, mk, m, {}, {}, None, since_t=t_mid)
    check(f"{sid} starts flat at its start minute", all(int(m.t[t.entry_k]) >= t_mid for t in tr), f"{len(tr)} trades")

start = datetime.fromtimestamp(S.YC4_START_T, timezone.utc)
for sid, mk in (("TR-02", "BANKNIFTY"), ("TR-03", "XAUTUSD"), ("TR-04", "BTCUSD")):
    a = C.BY_ID[sid]
    check(f"{sid} starts at YC4_START_T (cycle and segments)", CY._yc_start(a) == (S.YC4_START_T, S.YC4_START_DATE)
          and SG._start_of(mk, a) == start)
acct = C.BY_ID["TR-04"]
now = datetime.now(timezone.utc)
blank = {"open": 0, "open_since": None}
live = {"state": "live", "reason": "Last bar now.", "short": ""}
st, why = SG._book_state(acct, "BTCUSD", "TR-04|BTCUSD", blank, live, {"n_today": 0}, {}, {}, now)
check("a live market without a setup is running", st == "running" and why == "Running — waiting for signal.", why)
closed = {"state": "closed", "reason": "NSE is closed.", "short": "NSE is closed."}
st, why = SG._book_state(C.BY_ID["TR-02"], "NIFTY", "TR-02|NIFTY", blank, closed, {}, {}, {}, now)
check("a closed market arms the index book for the open", st == "armed", why)


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
kept = [d["_id"] for d in CY._fresh_only(_DB(), acct, "BTCUSD", docs)]
check("new entries only on fresh bars (a known trade stays)", kept == ["known", "fresh"], str(kept))
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
