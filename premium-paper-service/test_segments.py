"""Market segments, statuses, gold from Delta Exchange and the live-day exits, through the desk's own code:
    python -I test_segments.py            (needs mongomock on the path: an in-memory stand-in for the database)
1. the live day: a bitcoin setup before 18:30 UTC used to be rejected ("after_forced_exit") because today's 23:55 UTC
   exit row does not exist yet; now it is taken and stays open, and the engine's own reason is kept for untaken setups;
2. gold from Delta XAUTUSD: weekend minutes left out, 17:00 New York days, Delta's fees, every gold book runs on it;
3. a whole global cycle on live Delta and Yahoo data, into a temporary folder and an in-memory database, with the paper
   start moved back (to 26 Oct, bitcoin to 6 Nov) so that the books have days to trade on;
4. the status written after it: feeds, books and segments, and the states on a weekend and with a stale feed.
Nothing here touches the real desk: the data folder is temporary, the database lives in memory."""

import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# always a temporary folder (or one named for the test only), never the desk's own data folder
os.environ["PREMIUM_DATA_DIR"] = os.getenv("PREMIUM_TEST_DATA_DIR") or tempfile.mkdtemp(prefix="premium_seg_")
os.environ.setdefault("PREMIUM_PAPER_START", "2026-10-26")
os.environ.setdefault("PREMIUM_BTC_START", "2026-11-06T00:00:00+00:00")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import resource  # noqa: F401
except ImportError:          # Windows: cycle.py only reads its peak memory from it
    import types
    sys.modules["resource"] = types.SimpleNamespace(getrusage=lambda *_: types.SimpleNamespace(ru_maxrss=0), RUSAGE_SELF=0)

import mongomock  # noqa: E402
import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import cycle  # noqa: E402
import feeds as F  # noqa: E402
import ledger as L  # noqa: E402
import runner as R  # noqa: E402
import segments as SG  # noqa: E402
from research import CS, YE  # noqa: E402
from settings import IST, now_ist  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


db = mongomock.MongoClient().premium_test

# ── 3 first (it fetches the data the other checks use): one global cycle ──────────────
t0 = datetime.now(timezone.utc)
info = cycle.run_global(db, now_ist())
L.note_cycle(db, "global", True, (datetime.now(timezone.utc) - t0).total_seconds(), info)
SG.refresh(db, "global", info)
print("global cycle:", {k: v for k, v in info.items() if k != "errors"}, "errors:", info.get("errors"))
check("global cycle: no book errors", not [k for k in (info.get("errors") or {}) if "|" in k], info.get("errors"))
if not os.getenv("PREMIUM_TEST_DATA_DIR"):       # a fresh folder: the first cycle backfills 46 days of both
    check("Delta candles stored for bitcoin and gold", info["new"].get("BTCUSD", 0) > 1000 and info["new"].get("XAUUSD", 0) > 1000, info["new"])

# ── 1. the live day ──────────────────────────────────────────────────────────────────
bm = F.btc_market(date(2026, 10, 20))
last_day, last = bm.n_days - 1, len(bm.t) - 1
st = CS.STRATEGIES["CP-01"]
clock, minute = st.exit_clock["BTCUSD"]
old_k_end = YE.forced_exit_rows(bm, clock, minute)
new_k_end = R.live_k_end(bm, old_k_end)
k = int(bm.d1[last_day]) - 40
sig = YE.Signal(day=last_day, k=k, side=1, stop=float(bm.c[k]) * 0.5, setup="test")
ex = CS.exits_for(st)
utc_now = datetime.now(timezone.utc)
if utc_now.hour * 60 + utc_now.minute < 18 * 60 + 30:
    tr_old, rej_old = YE.run_book(YE.Engine(bm), [sig], ex, st.limits, old_k_end, "T", "V0")
    check("before 18:30 UTC the old exit rule rejects today's setup", not tr_old and rej_old.get("after_forced_exit") == 1, rej_old)
tr_new, rej_new = YE.run_book(YE.Engine(bm), [sig], ex, st.limits, new_k_end, "T", "V0")
check("the live-day rule takes it", len(tr_new) == 1, rej_new)
docs = R.docs_from(tr_new, bm, "T", "BTCUSD", False, str(bm.date[last_day]))
check("and it stays open, marked at the last bar", docs and docs[0]["open"] and docs[0]["last"] == float(bm.c[last]), docs[:1])
check("a finished day keeps its own exit row", new_k_end(last_day - 1) == old_k_end(last_day - 1) is not None)
# the engine's own reason for an untaken setup: a second setup while the first is still open
sig2 = YE.Signal(day=last_day, k=k + 10, side=1, stop=float(bm.c[k + 10]) * 0.5, setup="test2")
R.LAST_SIGNALS.pop("T|BTCUSD", None)
S = [sig, sig2]
eng = YE.Engine(bm)
tr, rej = YE.run_book(eng, S, ex, st.limits, new_k_end, "T", "V0")
R.note_signals("T|BTCUSD", bm, S, tr, rej, lambda S2: YE.run_book(eng, S2, ex, st.limits, new_k_end, "T", "V0"))
n = R.LAST_SIGNALS["T|BTCUSD"]
check("untaken setup: the engine's reason", n["today"] and n["taken"] is False and n["why"] == R.WHY["position_open"] and n["n_today"] == 2, n)

# ── 2. gold from Delta XAUTUSD ───────────────────────────────────────────────────────
gm = F.gold_market(date(2026, 10, 1))
import pandas as pd  # noqa: E402
nyt = pd.to_datetime(gm.t, unit="s", utc=True).tz_convert("America/New_York")
wd, hm = nyt.weekday.to_numpy(), (nyt.hour * 60 + nyt.minute).to_numpy()
check("gold: no weekend minutes", not (((wd == 5) | ((wd == 4) & (hm >= 1020)) | ((wd == 6) & (hm < 1020))).any()))
first_rows = gm.t[gm.d0]
fr = pd.to_datetime(first_rows[1:], unit="s", utc=True).tz_convert("America/New_York")
check("gold: every day starts at 17:00 New York (or right after)", ((fr.hour == 17) & (fr.minute <= 5)).mean() > 0.9,
      f"{((fr.hour == 17) & (fr.minute <= 5)).sum()} of {len(fr)}")
check("gold: Delta's costs", gm.cost.half_spread is None and abs(gm.cost.commission - 0.000118 * float(np.median(gm.c[-1440:]))) < 1e-9
      and float(gm.half[0]) == 0.02, gm.cost)
check("gold: a sliced market keeps the cost model", F.slice_from(gm, date(2026, 10, 20)).cost is gm.cost)
gold_books = [(a, mk, v) for a, mk, v in C.books_in("global") if mk == "XAUUSD"]
print("gold books:", len(gold_books), sorted({a.id for a, _, _ in gold_books}))
g_trades = list(db.premium_trades.find({"mkt": "XAUUSD", "qty": {"$gt": 0}}))
check("gold books traded on Delta data since the (test) start", len(g_trades) > 0, len(g_trades))
if g_trades:
    gt = g_trades[0]
    raw_t, raw_c = F._read_cols(F.DELTA_STORES["XAUTUSD"], "2026-09", ("t", "c"))
    i = int(np.searchsorted(raw_t, gt["entry_t"]))
    check("a gold entry sits on a Delta XAUTUSD minute", i < len(raw_t) and raw_t[i] == gt["entry_t"], (gt["acct"], gt["entry_t"], gt["entry"]))

# ── 3 (continued): bitcoin trades and the status ─────────────────────────────────────
b_trades = list(db.premium_trades.find({"mkt": "BTCUSD"}))
check("bitcoin books traded on Delta data since the (test) start", len(b_trades) > 0, len(b_trades))
check("no bitcoin trade before its start", all(d["entry_t"] >= int(datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp()) for d in b_trades))
status = db.premium_meta.find_one({"_id": "status"})
fd = status["feeds"]
print({k: (v["state"], v.get("last_t")) for k, v in fd.items()})
slow = (datetime.now(timezone.utc) - t0).total_seconds() > 480          # a first 46-day backfill on a slow network
check("feeds: bitcoin from Delta, live (or stale, rightly, after a slow backfill)", fd["BTCUSD"]["source"].startswith("Delta")
      and (fd["BTCUSD"]["state"] == "live" or (slow and fd["BTCUSD"]["state"] == "stale" and "old prices" in fd["BTCUSD"]["reason"])), fd["BTCUSD"])
check("feeds: gold from Delta XAUTUSD", fd["XAUUSD"]["source"].startswith("Delta") and "XAUTUSD" in fd["XAUUSD"]["instrument"], fd["XAUUSD"])
wk = SG.weekly_closed(datetime.now(timezone.utc))
check("feeds: gold closed at the weekend, live in the week", fd["XAUUSD"]["state"] == ("closed" if wk else "live"), fd["XAUUSD"]["reason"])
books = status["books"]
check("books: every account has its rows", set(books) == {a.id for a in C.ACCOUNTS} and all(len(books[a.id]) == len(a.books) for a in C.ACCOUNTS))
cp01 = {r["mkt"]: r for r in books["CP-01"]}
print("CP-01:", {m: (r["state"], r["reason"][:90]) for m, r in cp01.items()})
check("books: CP-01 bitcoin is live or in a trade", cp01["BTCUSD"]["state"] in ("live", "in trade"), cp01["BTCUSD"])
segs = status["segments"]
print({k: (v["books"], v["trades"], v["states"]) for k, v in segs.items()})
n_crypto = sum(1 for a in C.ACCOUNTS for mk, _ in a.books if mk in ("BTCUSD", "BTC_SPOT"))
n_gold = sum(1 for a in C.ACCOUNTS for mk, _ in a.books if mk == "XAUUSD")
check("segments: crypto and gold are separate", segs["crypto"]["books"] == n_crypto and segs["gold"]["books"] == n_gold, (n_crypto, n_gold))
crypto_rows = [(a, r) for a, rows in books.items() for r in rows if r["segment"] == "crypto"]
for a, r in crypto_rows:
    print("  ", a, r["mkt"], r["state"], "|", r["reason"])
check("books: only the order-flow books wait for the trade feed (not running in this test)",
      all(a in ("CP-14", "CP-15", "CP-29") for a, r in crypto_rows if r["state"] == "waiting"))
check("segments: every book counted once", sum(v["books"] for v in segs.values()) == sum(len(a.books) for a in C.ACCOUNTS))
check("segments: crypto recent trades are bitcoin only", all(t["mkt"] in ("BTCUSD", "BTC_SPOT") for t in segs["crypto"]["recent"]))

# ── 4. states on other days ──────────────────────────────────────────────────────────
sat = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
wed = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
check("Saturday: gold closed, with the reason", SG.feed_state("XAUUSD", {"last_t": int(sat.timestamp()) - 60}, sat)[0] == "closed")
check("Wednesday: gold live on a fresh bar", SG.feed_state("XAUUSD", {"last_t": int(wed.timestamp()) - 90}, wed)[0] == "live")
st_, why, short = SG.feed_state("BTCUSD", {"last_t": int(wed.timestamp()) - 3600, "fetch_error": "timed out"}, wed)
check("bitcoin an hour old: stale, never replaced", st_ == "stale" and "not trading on old prices" in why and "timed out" in why
      and short == "No new bar for 60 min: not trading on old prices.", (why, short))
gold_rows = [r for rows in books.values() for r in rows if r["mkt"] == "XAUUSD" and r["state"] == "closed"]
check("a closed gold book gives the short reason (the feed card has the long one)", all(r["reason"] == fd["XAUUSD"]["short"] for r in gold_rows)
      and (not wk or gold_rows), gold_rows[:1])
check("NSE on a Sunday: closed", SG.feed_state("NSE", {"last_t": None}, datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc))[0] == "closed")
check("NSE in session with no bars: no data", SG.feed_state("NIFTY", {"last_t": None}, datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc))[0] == "no data")
check("next gold session after a Saturday", SG.next_week_open_ist(sat) == "Mon 09 Nov, 03:30 IST", SG.next_week_open_ist(sat))

if os.getenv("PREMIUM_TEST_DUMP"):          # the in-memory desk as the API would serve it, to look at the page with
    import json
    dump = {"accounts": list(db.premium_accounts.find({})), "status": db.premium_meta.find_one({"_id": "status"}), "trades": {}}
    for a in dump["accounts"]:
        dump["trades"][a["_id"]] = list(db.premium_trades.find({"acct": a["_id"]}).sort("entry_t", -1).limit(500))
        dump["trades"][a["_id"] + "#n"] = db.premium_trades.count_documents({"acct": a["_id"]})
    Path(os.environ["PREMIUM_TEST_DUMP"]).write_text(json.dumps(dump, default=str), encoding="utf-8")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
