"""The 20-channel books through the desk's own plumbing, on research data:
    python -I test_yc2.py
1. the catalog's accounts are the registry's new strategies (ids, names, channels, markets; gold on Delta XAUTUSD), every
   market has money rules and a segment, and no blocked strategy has an account;
2. every book runs through runner.run_yc (pool books on a few stocks with DH-02's movers, AB-06 with its Bank Nifty
   companion, DR-04 on ether), its documents have unique ids, and the ledger sizes them;
3. a book that starts mid-way starts flat: no entry before its start minute (warm-up bars never become trades);
4. the 20-channel states: a closed market reads "Armed - waiting for market open.", a live one with no setup
   "Running - waiting for signal.", a stale feed blocks entries."""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_yc2_")
os.environ.setdefault("PREMIUM_YC2_START", "2026-01-01T00:00:00+00:00")     # the states test needs a started book
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend" / "research" / "youtube_channels11_2026_11"))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
import segments as SG  # noqa: E402
import yc_markets as MK  # noqa: E402
import zc_strategies as ZS  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


# 1. catalog = registry
ys = {a.id: a for a in C.ACCOUNTS if a.source == C.YC2}
reg = ZS.NEW
check("90 accounts, one per strategy", set(ys) == set(reg) and len(ys) == 90, f"{len(ys)} accounts")
bad = [s for s, a in ys.items() if a.name != reg[s].name or tuple(C.YC_BOOK_MARKET.get(mk, mk) for mk, _ in a.books) != reg[s].markets
       or a.channel != C.YC2_CHANNELS[reg[s].channel]]
check("names, channels and markets agree", not bad, str(bad[:5]))
check("gold books trade Delta XAUTUSD", all(mk != "XAUUSD" for a in ys.values() for mk, _ in a.books))
mk_all = {mk for a in ys.values() for mk, _ in a.books}
check("every market has money rules and a segment", all(mk in C.MONEY and mk in SG.SEGMENT for mk in mk_all), str(sorted(mk_all)))
check("no blocked strategy has an account", not ({b[0] for b in ZS.BLOCKED} & set(C.BY_ID)))
check("ids unique across the desk", len(C.BY_ID) == len(C.ACCOUNTS))

# 2. every book on research data
data = {nm: MK.window(nm, 40) for nm in ("NIFTY", "BANKNIFTY", "XAUUSD")}
data["BTCUSD"] = MK.window("BTCUSD", 60)
data["ETHUSD"] = MK.full("ETHUSD")
nd = MK.full("NIFTY_D")
data["NIFTY_D"] = MK._cut_daily(nd, len(nd.t) - 400, len(nd.t))
nsed = MK.nsed(limit=25)
pool = MK.nse_pool([m.name for m in nsed if (Path("D:/intraday_ai_data/intraday/5m") / f"{m.name}.ibar").exists()][:5], 30)
ctx = R.YCR.contexts({"movers"}, pool=pool)
rates = {"2026-10-01": 88.0}
for sid, a in ys.items():
    st = R.YCS.STRATEGIES[sid]
    docs = []
    for mk, _v in a.books:
        rules = C.YC_BOOK_MARKET.get(mk, mk)
        ms = pool if mk in ("NSE5", "NSE15") else (nsed if mk == "NSED" else [data[rules]])
        for m in ms:
            other = data["BANKNIFTY"] if "BANKNIFTY" in st.needs else None
            tr, _ = R.run_yc(sid, mk, m, {}, {"ctx": ctx}, other, risk_pct=C.MONEY[mk].risk_pct)
            docs += R.yc_docs(tr, m, sid, mk, R.is_overnight(sid, mk), None)
    ids = [d["_id"] for d in docs]
    res = L.walk(docs, rates, "2026-12-31")
    sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
    check(f"{sid} {','.join(mk for mk, _ in a.books)}", len(ids) == len(set(ids)) and np.isfinite(res["summary"]["equity"])
          and (sized > 0 or not docs), f"trades {len(docs)} sized {sized} equity {res['summary']['equity']:,.0f}")

# 3. starts flat
for sid, mk in (("TD-03", "BTCUSD"), ("DE-04", "XAUTUSD"), ("JR-01", "XAUTUSD"), ("DH-01", "NIFTY"), ("AX-05", "NIFTY")):
    m = data[C.YC_BOOK_MARKET.get(mk, mk)]
    t_mid = int(m.t[len(m.t) // 2])
    tr, _ = R.run_yc(sid, mk, m, {}, {}, None, since_t=t_mid)
    check(f"{sid} starts flat at its start minute", all(int(m.t[t.entry_k]) >= t_mid for t in tr), f"{len(tr)} trades")

# 4. the states
acct = C.BY_ID["TD-03"]
now = datetime.now(timezone.utc)
blank = {"open": 0, "open_since": None}
closed = {"state": "closed", "reason": "Gold's week is closed.", "short": "Gold's week is closed."}
st, why = SG._book_state(acct, "XAUTUSD", "TD-03|XAUTUSD", blank, closed, {}, {}, {}, now)
check("a closed market arms the book", st == "armed" and why.startswith("Armed — waiting for market open."), why)
live = {"state": "live", "reason": "Last bar now.", "short": ""}
st, why = SG._book_state(acct, "BTCUSD", "TD-03|BTCUSD", blank, live, {"n_today": 0}, {}, {}, now)
check("a live market without a setup is running", st == "running" and why == "Running — waiting for signal.", why)
stale = {"state": "stale", "reason": "No new bar.", "short": "No new bar for 30 min: not trading on old prices."}
st, why = SG._book_state(acct, "BTCUSD", "TD-03|BTCUSD", blank, stale, {}, {}, {}, now)
check("a stale feed blocks entries", st == "stale" and why.startswith("No new entries"), why)
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
