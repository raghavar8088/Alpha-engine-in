"""The Crypto-playlist books through the desk's own plumbing, on research data and on the live feeds:
    python -I test_cp.py
1. every CP book: runner.run_cp on 40 research days, documents built, accounts sized;
2. CP-24 with its companion market; CP-29 from a Fear & Greed series;
3. the live feeds into a temporary folder: Delta Exchange candles, silver (SI=F), the Fear & Greed index;
4. the order-flow recorder's minute coverage."""

import json
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
r = F.update_delta_candles()
check("delta exchange candles", r["new"] > 50_000, r)
bm = F.btc_market(np.datetime64(str(np.datetime64("today") - np.timedelta64(10, "D"))).astype(object))
check("btc market from the delta store", bm is not None and len(bm.bv) == len(bm.t) and np.isnan(bm.bv).all() and bm.cost.pct_comm == 0.00059,
      f"rows {len(bm.t) if bm is not None else 0}")
r = F.update_minutes("XAGUSD")
check("silver minutes (SI=F)", r["new"] > 1000, r)
g = F.fear_greed()
check("fear & greed index", len(g) >= 30 and all(0 <= v <= 100 for v in g.values()), f"{len(g)} days, last {max(g) if g else None}")
tr, _ = R.run_cp("CP-14", "BTCUSD", bm, {})
check("CP-14 makes no trade on minutes the order-flow recorder did not see", len(tr) == 0, len(tr))
tr, _ = R.run_cp("CP-01", "BTCUSD", bm, {})
check("CP-01 on delta bitcoin", len(tr) > 0, f"{len(tr)} trades in 10 days")

# the order-flow recorder: coverage, zero minutes, a reconnect
import delta_flow  # noqa: E402
out = Path(os.environ["PREMIUM_DATA_DIR"]) / "flow_test"
rec = delta_flow.Recorder(out)
t0 = 1_794_120_000                       # a minute boundary
rec.connected(t0 + 10)                   # coverage from t0 + 60
rec.trade((t0 + 30) * 1_000_000, 5, True)          # before coverage: ignored
rec.trade((t0 + 70) * 1_000_000, 10, True)
rec.trade((t0 + 80) * 1_000_000, 4, False)
rec.flush(t0 + 215)                      # minutes t0+60 and t0+120 have ended
rec.trade((t0 + 200) * 1_000_000, 7, False)        # minute t0+180, still in progress
rec.lost()                               # the connection drops: t0+180 is never written
rec.connected(t0 + 400)                  # coverage again from t0+420
rec.flush(t0 + 545)                      # t0+420 and t0+480 ended with no trades: zeros
lines = [json.loads(x) for f in sorted(out.glob("*.jsonl")) for x in f.read_text().splitlines()]
check("recorder writes only fully seen minutes", [l[0] - t0 for l in lines] == [60, 120, 420, 480] and lines[0][1:3] == [10.0, 4.0]
      and lines[1][1:3] == [0.0, 0.0] and delta_flow.read.__module__ == "delta_flow", lines)
sys.exit(0 if ok else 1)
