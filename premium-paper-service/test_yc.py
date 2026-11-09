"""The 11-channel books through the desk's own plumbing, on research data:
    python -I test_yc.py
1. the catalog's accounts are the registry's strategies (ids, names, channels, markets), and every market has money
   rules and a segment;
2. every book runs through runner.run_yc (pool books on a few stocks, NJ-25 over the NSE daily pool, NJ-33 with its
   ETHUSD companion), its documents have unique ids, and the ledger sizes them;
3. a book that starts mid-way starts flat: no entry before its start minute;
4. the desk's ETHUSD reader and the backfill's merge on a temporary store."""

import os
import sys
import tempfile
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_yc_")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend" / "research" / "youtube_channels11_2026_11"))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import feeds as F  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
import segments as SG  # noqa: E402
import yc_markets as MK  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


# 1. catalog = registry
ys = {a.id: a for a in C.ACCOUNTS if a.source == C.YC}
reg = R.YCS.STRATEGIES
check("103 accounts, one per strategy", set(ys) == set(reg) and len(ys) == 103, f"{len(ys)} accounts")
bad = [s for s, a in ys.items() if a.name != reg[s].name or tuple(C.YC_BOOK_MARKET.get(mk, mk) for mk, _ in a.books) != reg[s].markets
       or a.channel != C.YC_CHANNELS[reg[s].channel]]
check("names, channels and markets agree", not bad, str(bad[:5]))
mk_all = {mk for a in ys.values() for mk, _ in a.books}
check("every market has money rules and a segment", all(mk in C.MONEY and mk in SG.SEGMENT for mk in mk_all), str(sorted(mk_all)))

# 2. every book on research data
data = {nm: MK.window(nm, 45) for nm in ("NIFTY", "BANKNIFTY", "XAUUSD", "EURUSD", "GBPUSD", "NAS100")}
data["BTCUSD"] = MK.window("BTCUSD", 75)
eth = MK.full("ETHUSD")
data["NIFTY_D"] = MK._cut_daily(MK.full("NIFTY_D"), len(MK.full("NIFTY_D").t) - 400, len(MK.full("NIFTY_D").t))
nsed = MK.nsed(limit=30)
pool = MK.nse_pool([m.name for m in nsed if (Path("D:/intraday_ai_data/intraday/5m") / f"{m.name}.ibar").exists()][:4], 30)
ctx = R.YCR.contexts({"nifty_gap", "nj20", "ss03"}, nifty=data["NIFTY"], nsed=nsed, pool=pool)
rates = {"2026-10-01": 88.0}
for sid, a in ys.items():
    st = reg[sid]
    docs = []
    for mk, _v in a.books:
        if st.kind == "basket":
            for sym, tr in R.YCR.run_basket(sid, nsed).items():
                m = next(x for x in nsed if x.name == sym)
                docs += R.yc_docs(tr, m, sid, mk, True, None)
            continue
        ms = pool if mk in ("NSE5", "NSE15") else (nsed if mk == "NSED" else [data[C.YC_BOOK_MARKET.get(mk, mk)]])
        for m in ms:
            p = {"ctx": ctx}
            if "box" in st.needs:
                p["box"] = 1000.0
            tr, _ = R.run_yc(sid, mk, m, {}, p, eth if "ETHUSD" in st.needs else None, risk_pct=C.MONEY[mk].risk_pct)
            docs += R.yc_docs(tr, m, sid, mk, R.is_overnight(sid, mk), None)
    ids = [d["_id"] for d in docs]
    res = L.walk(docs, rates, "2026-12-31")
    sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
    check(f"{sid} {','.join(mk for mk, _ in a.books)}", len(ids) == len(set(ids)) and np.isfinite(res["summary"]["equity"])
          and (sized > 0 or not docs), f"trades {len(docs)} sized {sized} equity {res['summary']['equity']:,.0f}")

# 3. starts flat
btc = data["BTCUSD"]
t_mid = int(btc.t[len(btc.t) // 2])
for sid in ("NJ-27", "PR-13", "IT-02", "NJ-30"):
    tr, _ = R.run_yc(sid, "BTCUSD", btc, {}, {}, None, since_t=t_mid)
    check(f"{sid} starts flat at its start minute", all(int(btc.t[t.entry_k]) >= t_mid for t in tr), f"{len(tr)} trades")

# 4. the ETHUSD reader and the backfill merge
store = F.DATA / "min1" / F.DELTA_STORES["ETHUSD"]
store.mkdir(parents=True, exist_ok=True)
t = np.arange(1_790_000_040, 1_790_000_040 + 600 * 60, 60, dtype=np.int64)
px = 3000 + np.cumsum(np.random.default_rng(1).normal(0, 1, len(t)))
np.savez_compressed(store / f"{F._ym(int(t[0]))}.npz", t=t, o=px, h=px + 1, l=px - 1, c=px, v=np.ones(len(t)))
em = F.eth_market(F.datetime.fromtimestamp(int(t[0]), F.timezone.utc).date())
check("ETHUSD reader", em is not None and len(em.t) == len(t) and em.name == "ETHUSD")
check("backfill does nothing on an empty store", F.backfill_delta_candles("BTCUSD", 10).get("why") == "empty store")
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
