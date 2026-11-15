"""The channel-shortlist books through the desk's own plumbing, on research data (run from a patched desk copy):
    python -I test_yc3.py
1. the catalog's YC3 accounts are the registry's strategies (ids, names, markets; gold on Delta XAUTUSD), every market
   has money rules and a segment, no blocked strategy has an account, ids are unique across the desk;
2. every book runs through runner.run_yc (pool books on a few stocks, with DF-01's contexts; the tenth batch's option
   books on the recorded NIFTY option chain, with their own contexts), its documents have unique ids, and the ledger sizes
   them (option books in whole lots of 65);
3. a book that starts mid-way starts flat;
4. the YC3 books get the 20-channel states and their own start (the second to tenth batches their own, later
   ones); the option books' market has its own feed, closed with NSE."""

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
os.environ.setdefault("PREMIUM_YC3E_START", "2026-01-05T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3F_START", "2026-01-06T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3G_START", "2026-01-07T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3H_START", "2026-01-08T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3I_START", "2026-01-09T00:00:00+00:00")
os.environ.setdefault("PREMIUM_YC3J_START", "2026-01-10T00:00:00+00:00")
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
data["ETHUSD"] = MK.window("ETHUSD", 60)          # the fifth batch trades ether (Delta ETHUSD)
# the ninth batch trades Apple: the research caches hold no Apple minutes, so its book runs here on the Nasdaq 100
# minutes (the same 09:30-16:00 session) brought to an Apple-like price with Apple's cost model (the ledger buys
# whole shares)
import dataclasses  # noqa: E402
import yt_markets as YM  # noqa: E402
_nq = data["NAS100"]
data["AAPL"] = dataclasses.replace(_nq, name="AAPL", o=_nq.o * 0.01, h=_nq.h * 0.01, l=_nq.l * 0.01, c=_nq.c * 0.01,
                                   half=np.full(len(_nq.t), YM.COSTS["AAPL"].half_spread), cost=YM.COSTS["AAPL"])
data["AAPL"].split_key, data["AAPL"].overnight = _nq.split_key, _nq.overnight
nsed = MK.nsed(limit=25)
pool = MK.nse_pool([m.name for m in nsed if (Path("D:/intraday_ai_data/intraday/5m") / f"{m.name}.ibar").exists()][:6], 30)
ctx = R.YCR.contexts({"ze_rank930", "ze_nifty930"}, pool=pool, nifty=data["NIFTY"])
check("DF-01 contexts built", bool(ctx.get("ze_rank930")) and bool(ctx.get("ze_nifty930")),
      f"{len(ctx.get('ze_rank930', {}))} days ranked")
# the tenth batch's option books trade the recorded NIFTY option chain (market NIFTY_OPT): here its research copy
import ze_more9 as X9  # noqa: E402
import ze_opt as O  # noqa: E402
opt_days = O.load_days(folder=Path("D:/intraday_ai_data/optchain"))
opt_ctx, opt_picks = X9.CONTEXT(opt_days)
opt_pool = O.pool_of(opt_days, opt_picks)
check("the recorded NIFTY option chain loads", len(opt_days) > 0 and len(opt_pool) > 0,
      f"{len(opt_days)} sessions, {len(opt_pool)} contract-days")
rates = {"2026-10-01": 88.0}
for sid, a in sorted(ys.items()):
    docs = []
    for mk, _v in a.books:
        rules = "XAUUSD" if mk == "XAUTUSD" else mk
        ms = (pool if mk in ("NSE5", "NSE15") else nsed if mk == "NSED" else opt_pool if mk == "NIFTY_OPT"
              else [data[rules]])
        p = {"ctx": opt_ctx} if mk == "NIFTY_OPT" else {"ctx": ctx}
        for m in ms:
            tr, _ = R.run_yc(sid, mk, m, {}, p, None, risk_pct=C.MONEY[mk].risk_pct)
            docs += R.yc_docs(tr, m, sid, mk, R.is_overnight(sid, mk), None)
    ids = [d["_id"] for d in docs]
    res = L.walk(docs, rates, "2026-12-31")
    sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
    check(f"{sid} {','.join(mk for mk, _ in a.books)}", len(ids) == len(set(ids)) and np.isfinite(res["summary"]["equity"])
          and (sized > 0 or not docs), f"trades {len(docs)} sized {sized} equity {res['summary']['equity']:,.0f}")
    if a.books == (("NIFTY_OPT", "V0"),) and docs:
        qtys = sorted({f["qty"] for f in res["fields"].values() if f["qty"] > 0})
        check(f"{sid} buys whole lots of 65 of named contracts", all(q % 65 == 0 for q in qtys)
              and all(d["sym"].startswith("NIFTY ") and d["sym"][-2:] in ("CE", "PE") for d in docs), f"qty {qtys[:4]}")

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
check("YC3D_IDS is the registry's fourth batch", set(C.YC3D_IDS) == {r.sid for r in ZS._NEW[69:90]})
b5 = C.BY_ID["BX-02"]
check("fifth-batch books start at YC3E_START_T", SG._start_of("ETHUSD", b5) == datetime.fromtimestamp(S.YC3E_START_T, timezone.utc))
check("YC3E_IDS is the registry's fifth batch", set(C.YC3E_IDS) == {r.sid for r in ZS._NEW[90:100]})
b6 = C.BY_ID["TL-06"]
check("sixth-batch books start at YC3F_START_T", SG._start_of("XAUTUSD", b6) == datetime.fromtimestamp(S.YC3F_START_T, timezone.utc))
check("YC3F_IDS is the registry's sixth batch", set(C.YC3F_IDS) == {r.sid for r in ZS._NEW[100:105]})
b7 = C.BY_ID["JO-01"]
check("seventh-batch books start at YC3G_START_T", SG._start_of("XAUTUSD", b7) == datetime.fromtimestamp(S.YC3G_START_T, timezone.utc))
check("YC3G_IDS is the registry's seventh batch", set(C.YC3G_IDS) == {r.sid for r in ZS._NEW[105:113]})
b8 = C.BY_ID["TC-05"]
check("eighth-batch books start at YC3H_START_T", SG._start_of("XAUTUSD", b8) == datetime.fromtimestamp(S.YC3H_START_T, timezone.utc))
check("YC3H_IDS is the registry's eighth batch", set(C.YC3H_IDS) == {r.sid for r in ZS._NEW[113:130]})
b9 = C.BY_ID["CT-05"]
check("ninth-batch books start at YC3I_START_T", SG._start_of("BTCUSD", b9) == datetime.fromtimestamp(S.YC3I_START_T, timezone.utc))
check("YC3I_IDS is the registry's ninth batch", set(C.YC3I_IDS) == {r.sid for r in ZS._NEW[130:141]})
b10 = C.BY_ID["IM-02"]
check("tenth-batch books start at YC3J_START_T", SG._start_of("NIFTY_OPT", b10) == datetime.fromtimestamp(S.YC3J_START_T, timezone.utc))
check("YC3J_IDS is the registry's tenth batch", set(C.YC3J_IDS) == {r.sid for r in ZS._NEW[141:]})
check("the tenth batch's option books trade NIFTY_OPT, its index books the index",
      all(C.BY_ID[s].books == (("NIFTY_OPT", "V0"),) for s in ("IM-02", "AA-01", "DH-12", "RK-01", "QM-02", "QM-01"))
      and C.BY_ID["TE-01"].books == (("BANKNIFTY", "V0"),) and C.BY_ID["SJ-01"].books == (("NIFTY", "V0"),))
check("NIFTY_OPT runs in the index cycle: whole lots of 65, the premium paid in full, two contracts at once",
      C.MONEY["NIFTY_OPT"].group == "index" and C.MONEY["NIFTY_OPT"].lot == 65 and C.MONEY["NIFTY_OPT"].margin == 1.0
      and C.MONEY["NIFTY_OPT"].max_open == 2 and "NIFTY_OPT" in R.POOLS)
_sunday = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
_monday = datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)
check("NIFTY_OPT has its own feed, closed with NSE, stale without new snapshots",
      SG.FEED_OF.get("NIFTY_OPT", "NIFTY_OPT") == "NIFTY_OPT" and SG.feed_state("NIFTY_OPT", {"last_t": None}, _sunday)[0] == "closed"
      and SG.feed_state("NIFTY_OPT", {"last_t": int(_monday.timestamp()) - 1200}, _monday)[0] == "stale"
      and SG.feed_state("NIFTY_OPT", {"last_t": int(_monday.timestamp()) - 60}, _monday)[0] == "live")
check("a skipped index cycle still reports the option chain's feed (from the recorder's newest file)",
      (SG.feeds_now("index", {"skipped": "no new bars"}).get("NIFTY_OPT") or {}).get("last_t") is not None
      and SG.feeds_now("index", {"optchain_to": 123}).get("NIFTY_OPT", {}).get("last_t") == 123)
check("the ninth batch's Apple book trades the desk's Apple market", C.BY_ID["QN-01"].books == (("AAPL", "V0"),))
check("eighth-batch order-flow books trade bitcoin only", all(C.BY_ID[s].books == (("BTCUSD", "V0"),) for s in ("SC-02", "SC-03", "SC-04")))
check("ether books close at the UTC day's end unless held overnight",
      ZS.YS.STRATEGIES["TC-04"].exit_clock("ETHUSD") == ("ist", 5 * 60 + 25) and ZS.YS.STRATEGIES["BX-02"].exit_clock("ETHUSD") == ("end", 0))
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
