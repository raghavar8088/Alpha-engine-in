"""The Crypto-playlist books through the desk's own plumbing, on research data and on the live feeds:
    python -I test_cp.py
1. every CP book: runner.run_cp on 40 research days, documents built, accounts sized;
2. CP-24 with its companion market; CP-29 from a Fear & Greed series;
3. the live feeds into a temporary folder: Binance minutes with taker volume, silver (SI=F), the Fear & Greed index."""

import os
import sys
import tempfile
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="premium_cp_")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend" / "research" / "crypto_playlist_2026_11"))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import feeds as F  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
from research import YM  # noqa: E402
from research_window import window  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


data = {mk: window(mk, days=40) for mk in ("XAUUSD", "EURUSD", "GBPUSD", "BTCUSD")}
rates = {"2026-10-01": 88.0}
for a in C.ACCOUNTS:
    if a.source != C.CP or a.id == "CP-29":
        continue
    docs = []
    for mk, v in a.books:
        m = data[mk]
        mm = m if mk == "BTCUSD" else YM._as_mkt(m, mk, mk, YM.COSTS[mk])
        other = None
        comp = R.CS.STRATEGIES[a.id].companion.get(mk)
        if comp:
            other = data.get(comp)
            if other is not None:
                other = YM._as_mkt(other, comp, comp, YM.COSTS[comp])
        tr, _ = R.run_cp(a.id, mk, mm, {}, other)
        docs += R.docs_from(tr, m, a.id, mk, False, None)
    res = L.walk(docs, rates, "2026-10-10")
    s = res["summary"]
    sized = sum(1 for f in res["fields"].values() if f["qty"] > 0)
    check(f"{a.id} {','.join(mk for mk, _ in a.books)}", len(docs) > 0 and sized > 0 and np.isfinite(s["equity"]),
          f"trades {len(docs)} sized {sized} equity {s['equity']:,.0f} skipped {s['skipped']}")

# CP-29: Mondays with fear, from the BTC research window
btc = data["BTCUSD"]
days = [str(d) for d in btc.date]
fng = {d: (30 if i % 2 == 0 else 60) for i, d in enumerate(days)}
docs = R.fear_greed_docs("CP-29", fng, btc, days[0])
mondays = [d for d in days if np.datetime64(d).astype(object).weekday() == 0 and fng[d] < 45]
check("CP-29 buys only on fearful Mondays", len(docs) == len(mondays) and all(d["open"] for d in docs), f"{len(docs)} buys")
res = L.walk(docs, rates, days[-1])
f0 = res["fields"][docs[0]["_id"]] if docs else {}
check("CP-29 buys Rs 25,000 a time", docs and abs(f0["qty"] * docs[0]["entry"] * 88.0 - 25_000) < 25_000 * 0.01, f0)
check("CP-29 marked, never closed", res["summary"]["closed"] == 0 and res["summary"]["open"] == len(docs), res["summary"]["open"])

# live feeds into the temporary folder
r = F.update_binance()
check("binance minutes with taker volume", r["new"] > 50_000, r)
bm = F.btc_market(np.datetime64(str(np.datetime64("today") - np.timedelta64(10, "D"))).astype(object))
check("btc market from the store", bm is not None and hasattr(bm, "bv") and len(bm.bv) == len(bm.t) and 0.3 < bm.bv.sum() / bm.vol_all.sum() < 0.7,
      f"rows {len(bm.t) if bm is not None else 0}")
r = F.update_minutes("XAGUSD")
check("silver minutes (SI=F)", r["new"] > 1000, r)
g = F.fear_greed()
check("fear & greed index", len(g) >= 30 and all(0 <= v <= 100 for v in g.values()), f"{len(g)} days, last {max(g) if g else None}")
tr, _ = R.run_cp("CP-14", "BTCUSD", bm, {})
check("CP-14 on live bitcoin", True, f"{len(tr)} trades in 10 days")
sys.exit(0 if ok else 1)
