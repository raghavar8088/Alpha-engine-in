"""The channel-shortlist books through the desk's own plumbing, on research data (run from a patched desk copy):
    python -I test_yc3.py
1. the catalog's YC3 accounts are the registry's strategies (ids, names, markets; gold on Delta XAUTUSD), every market
   has money rules and a segment, no blocked strategy has an account, ids are unique across the desk;
2. every book runs through runner.run_yc (pool books on a few stocks, with DF-01's contexts), its documents have unique
   ids, and the ledger sizes them;
3. a book that starts mid-way starts flat;
4. the YC3 books get the 20-channel states and their own start (the second, third and fourth batches their own,
   later ones)."""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_yc3_")
os.environ.setdefault("PREMIUM_YC3_START", "2026-01-01T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3B_START", "2026-01-02T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3C_START", "2026-01-03T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3D_START", "2026-01-04T00:00:00+00:00")
HERE = Path.cwd()
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend" / "research" / "youtube_channels11_2026_11"))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
import segments as SG  # noqa: E402
import settings as S  # noqa: E402
import yc_markets as MK  # noqa: E402
import ze_strategies as ZS  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


ys = {a.id: a for a in C.ACCOUNTS if a.source == C.YC3}
reg = {r.sid: r for r in ZS._NEW}
check(f"{len(reg)} accounts, one per strategy", set(ys) == set(reg), f"{len(ys)} accounts")
bad = [s for s, a in ys.items() if a.name != reg[s].name
       or tuple(C.YC_RULES_MARKET.get(mk, mk) if hasattr(C, "YC_RULES_MARKET") else ("XAUUSD" if mk == "XAUTUSD" else mk)
                for mk, _ in a.books) != reg[s].markets]
check("names and markets agree", not bad, str(bad[:5]))
check("gold books trade Delta XAUTUSD", all(mk != "XAUUSD" for a in ys.values() for mk, _ in a.books))
mk_all = {mk for a in ys.values() for mk, _ in a.books}
check("every market has money rules and a segment", all(mk in C.MONEY and mk in SG.SEGMENT for mk in mk_all), str(sorted(mk_all)))
check("no blocked strategy has an account", not (set(ZS.BLOCKED) & set(ys)))
check("ids unique across the desk", len(C.BY_ID) == len(C.ACCOUNTS), f"{len(C.ACCOUNTS)} accounts")
check("YC3 is a YouTube-channel source", C.YC3 in C.YC_SOURCES)

data = {nm: MK.window(nm, 40) for nm in ("NIFTY", "BANKNIFTY", "XAUUSD", "EURUSD", "GBPUSD", "NAS100")}
data["BTCUSD"] = MK.window("BTCUSD", 60)
nsed = MK.nsed(limit=25)
pool = MK.nse_pool([m.name for m in nsed if (Path("D:/intraday_ai_data/intraday/5m") / f"{m.name}.ibar").exists()][:6], 30)
ctx = R.YCR.contexts({"ze_rank930", "ze_nifty930"}, pool=pool, nifty=data["NIFTY"])
check("DF-01 contexts built", bool(ctx.get("ze_rank930")) and bool(ctx.get("ze_nifty930")),
      f"{len(ctx.get('ze_rank930', {}))} days ranked")
rates = {"2026-10-01": 88.0}
for sid, a in sorted(ys.items()):
    docs = []
    for mk, _v in a.books:
        rules = "XAUUSD" if mk == "XAUTUSD" else mk
        ms = pool if mk in ("NSE5", "NSE15") else (nsed if mk == "NSED" else [data[rules]])
        for m in ms:
            tr, _ = R.run_yc(sid, mk, m, {}, {"ctx": ctx}, None, risk_pct=C.MONEY[mk].risk_pct)
            docs += R.yc_docs(tr, m, sid, mk, R.is_overnight(sid, mk), None)
    ids = [d["_id"] for d in docs]
    res = L.walk(docs, rates, "2026-12-31")
    sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
    check(f"{sid} {','.join(mk for mk, _ in a.books)}", len(ids) == len(set(ids)) and np.isfinite(res["summary"]["equity"])
          and (sized > 0 or not docs), f"trades {len(docs)} sized {sized} equity {res['summary']['equity']:,.0f}")

for sid, mk in (("DF-02", "NIFTY"), ("BN-01", "BTCUSD"), ("RU-05", "XAUTUSD"), ("NK-01", "EURUSD"), ("UK-01", "NAS100")):
    m = data["XAUUSD" if mk == "XAUTUSD" else mk]
    t_mid = int(m.t[len(m.t) // 2])
    tr, _ = R.run_yc(sid, mk, m, {}, {}, None, since_t=t_mid)
    check(f"{sid} starts flat at its start minute", all(int(m.t[t.entry_k]) >= t_mid for t in tr), f"{len(tr)} trades")

acct = C.BY_ID["BN-01"]
now = datetime.now(timezone.utc)
blank = {"open": 0, "open_since": None}
live = {"state": "live", "reason": "Last bar now.", "short": ""}
st, why = SG._book_state(acct, "BTCUSD", "BN-01|BTCUSD", blank, live, {"n_today": 0}, {}, {}, now)
check("a live market without a setup is running", st == "running" and why == "Running — waiting for signal.", why)
check("YC3 books start at YC3_START_T", SG._start_of("BTCUSD", acct) == datetime.fromtimestamp(S.YC3_START_T, timezone.utc))
b2 = C.BY_ID["CT-02"]
check("second-batch books start at YC3B_START_T", SG._start_of("BTCUSD", b2) == datetime.fromtimestamp(S.YC3B_START_T, timezone.utc))
check("YC3B_IDS is the registry's second batch", set(C.YC3B_IDS) == {r.sid for r in ZS._NEW[31:54]})
b3 = C.BY_ID["CD-01"]
check("third-batch books start at YC3C_START_T", SG._start_of("BTCUSD", b3) == datetime.fromtimestamp(S.YC3C_START_T, timezone.utc))
check("YC3C_IDS is the registry's third batch", set(C.YC3C_IDS) == {r.sid for r in ZS._NEW[54:69]})
b4 = C.BY_ID["AV-01"]
check("fourth-batch books start at YC3D_START_T", SG._start_of("BTCUSD", b4) == datetime.fromtimestamp(S.YC3D_START_T, timezone.utc))
check("YC3D_IDS is the registry's fourth batch", set(C.YC3D_IDS) == {r.sid for r in ZS._NEW[69:]})
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
