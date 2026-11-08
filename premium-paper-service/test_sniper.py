"""The Sniper-headshot books (sniper.py) through the desk's own plumbing:
    python -I test_sniper.py            (part 4 needs mongomock importable)
1. no look-ahead: every version's trades, computed on data cut at many points, equal the full data's up to the cut
   (a signal on the bar still forming at the cut is left out: it has no next row to fill on);
2. the rules hold for every first entry of the full data (stop, target, zone, candle, reward to risk), and every second
   entry adds to a first entry that is still open, with the same target;
3. SH-02's order-flow filter on a known setup: taken with takers selling the sweep and buying the candle, skipped
   without them, and never on minutes the recorder did not see;
4. the books as paper accounts: documents, sizing, both entries in the ledger, and a book that starts mid-session
   trades only setups from its start.
Uses Delta's BTCUSD candles: PREMIUM_TEST_DATA_DIR if set, else fetched into a temporary folder. Nothing here touches
the real desk."""

import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

os.environ["PREMIUM_DATA_DIR"] = os.getenv("PREMIUM_TEST_DATA_DIR") or tempfile.mkdtemp(prefix="premium_sh_")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import catalog as C  # noqa: E402
import feeds as F  # noqa: E402
import runner as R  # noqa: E402
import sniper as SH  # noqa: E402
from research import CPM  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


if not os.getenv("PREMIUM_TEST_DATA_DIR"):
    print("fetching Delta BTCUSD candles:", F.update_delta_candles(symbol="BTCUSD"))
bm = F.btc_market(date.fromordinal(date.today().toordinal() - 44))
print("bitcoin minutes", len(bm.t), "days", bm.n_days, str(bm.date[0]), "->", str(bm.date[-1]))
check("enough data", bm.n_days >= 30, bm.n_days)


def cut_market(m, cut: int):
    """The same market as it looked when only its first `cut` minutes existed."""
    k = CPM.btc_market(m.t[:cut], m.o[:cut], m.h[:cut], m.l[:cut], m.c[:cut], np.asarray(m.vol[:cut], float), np.zeros(cut))
    k.bv, k.vol_all = np.asarray(m.bv[:cut], float), np.asarray(m.vol_all[:cut], float)
    k.half, k.cost = np.full(cut, F.DELTA_HALF), F.DELTA_COST
    return k


def entries(trades, upto: int) -> set:
    return {(t.variant, int(t.sig_k), int(t.side), round(float(t.stop), 6), round(float(t.target), 6))
            for t in trades if t.sig_k <= upto}


# ── 1. no look-ahead ─────────────────────────────────────────────────────────────────
full = {sid: R.run_sh(sid, bm, {})[0] for sid in SH.VERSIONS}
cuts = list(range(int(bm.d0[8]), len(bm.t) - 30, 1440 + 377))
for sid in SH.VERSIONS:
    bad = []
    for cut in cuts:
        got = entries(R.run_sh(sid, cut_market(bm, cut), {})[0], cut - 2)
        want = entries(full[sid], cut - 2)
        if got != want:
            bad.append((cut, sorted(got ^ want)[:2]))
    check(f"{sid}: trades unchanged when later data is cut off ({len(cuts)} cuts)", not bad, bad[:2])

# ── 2. the rules, re-checked on every entry ──────────────────────────────────────────
for sid, v in SH.VERSIONS.items():
    cache: dict = {}
    B = R._bars(bm, (v.tf, v.htf), cache)
    S = SH.signals(sid, bm, B, cache)
    b = B[v.tf]
    errs = []
    for s in S:
        j, lvl, ref, (zlo, zhi) = s.info["bar"], s.info["level"], s.info["ref"], s.info["zone"]
        e, side, atr = b.c[j], s.side, s.info["atr"]
        if side > 0 and not (zhi < lvl and s.info["sweep_extreme"] < lvl):
            errs.append((sid, j, "zone or sweep not below the level"))
        if side < 0 and not (zlo > lvl and s.info["sweep_extreme"] > lvl):
            errs.append((sid, j, "zone or sweep not above the level"))
        if v.entry == "candle":
            if (b.c[j] - b.o[j]) * side <= 0:
                errs.append((sid, j, "the reversal candle is the wrong colour"))
            want_stop = (b.l[j] - SH.LOW_STOP_ATR * atr if side > 0 else b.h[j] + SH.LOW_STOP_ATR * atr) if v.stop == "low" \
                else b.o[j] + SH.STOP_BODY * (b.c[j] - b.o[j])
        else:
            if (b.c[j] - lvl) * side <= 0:
                errs.append((sid, j, "no close back across the level"))
            want_stop = s.info["sweep_extreme"] - side * SH.SWEEP_STOP_ATR * atr
        if abs(s.stop - want_stop) > 1e-6:
            errs.append((sid, j, "stop", s.stop, want_stop))
        if (ref - e) * side <= 0 or abs(s.target_px - (e + SH.TARGET_FRAC * (ref - e))) > 1e-6:
            errs.append((sid, j, "target"))
        risk = (e - s.stop) * side
        if not (risk > 0 and (s.target_px - e) * side >= SH.MIN_RR * risk - 1e-9):
            errs.append((sid, j, "reward to risk"))
        if v.cost_mult and risk < v.cost_mult * SH.ctx(bm, B, cache, v.tf, v.htf).rt_cost(e) - 1e-9:
            errs.append((sid, j, "cost guard"))
    check(f"{sid}: {len(S)} first entries follow the rules", not errs, errs[:3])
    trades = full[sid]
    firsts = [t for t in trades if t.variant == "E1"]
    adds = [t for t in trades if t.variant == "E2"]
    lost = [t for t in adds if not any(f.entry_k < t.entry_k < f.exit_k and f.side == t.side and abs(f.target - t.target) < 1e-6
                                       for f in firsts)]
    check(f"{sid}: {len(adds)} second entries each add to an open first entry with its target", not lost, lost[:1])
    per_day = len(firsts) / bm.n_days
    print(f"     {sid}: {len(S)} setups, {len(firsts)} first entries ({per_day:.2f} a day), {len(adds)} adds")

# ── 3. SH-02's order flow on a known setup ───────────────────────────────────────────
cache = {}
B = R._bars(bm, (5, 60), cache)
pick = [s for s in SH.signals("SH-00", bm, B, cache) if s.info["sweep_bar"] < s.info["bar"]]
check("a SH-00 setup with a separate sweep to test on", bool(pick))
if pick:
    s0 = pick[0]
    b5 = B[5]
    sw, j = s0.info["sweep_bar"], s0.info["bar"]

    def with_flow(leg_buy: float, candle_buy: float, hole: bool = False):
        m2 = cut_market(bm, len(bm.t))
        m2.vol_all = np.full(len(m2.t), 10.0)
        m2.bv = np.full(len(m2.t), 5.0)                              # neutral everywhere
        m2.bv[b5.i0[sw]:b5.i1[j - 1] + 1] = leg_buy                 # the sweep, up to the candle
        m2.bv[b5.i0[j]:b5.i1[j] + 1] = candle_buy                   # the reversal candle
        if hole:
            m2.bv[b5.i0[j]] = np.nan                                 # one minute the recorder did not see
        return [x for x in SH.signals("SH-02", m2, R._bars(m2, (5, 60), {}), {}) if x.info["bar"] == j]

    side = s0.side
    seller, buyer = (3.0, 7.0) if side > 0 else (7.0, 3.0)
    check("SH-02 takes it when takers sold the sweep and bought the candle", len(with_flow(seller, buyer)) == 1)
    check("SH-02 skips it with neutral flow", len(with_flow(5.0, 5.0)) == 0)
    check("SH-02 skips it when one minute of the candle was not recorded", len(with_flow(seller, buyer, hole=True)) == 0)
if np.isnan(bm.bv).all():
    check("SH-02 never trades where no flow was recorded", not full["SH-02"])

# ── 4. as paper accounts ─────────────────────────────────────────────────────────────
try:
    import mongomock
except ImportError:
    mongomock = None
    print("skip  part 4: mongomock is not importable")
if mongomock is not None:
    import ledger as L
    db = mongomock.MongoClient().sh_test
    since = int(bm.t[int(bm.d0[bm.n_days - 15])]) + 9 * 3600          # 09:00 UTC, 15 days back: a mid-session start
    live_day = str(bm.date[-1])
    for a in [x for x in C.ACCOUNTS if x.source == C.SH]:
        tr, _ = R.run_sh(a.id, bm, {}, since_t=since)
        docs = [d for d in R.docs_from(tr, bm, a.id, "BTCUSD", False, live_day) if d["entry_t"] >= since]
        check(f"{a.id}: nothing before its start", all(int(bm.t[t.entry_k]) >= since for t in tr), len(tr))
        L.persist(db, a.id, "BTCUSD", docs, str(bm.date[bm.n_days - 15]), str(bm.date[-2]), False)
        L.update_accounts(db, [a.id])
        acct = db.premium_accounts.find_one({"_id": a.id})
        n = db.premium_trades.count_documents({"acct": a.id})
        sized = db.premium_trades.count_documents({"acct": a.id, "qty": {"$gt": 0}})
        e2 = db.premium_trades.count_documents({"acct": a.id, "variant": "E2"})
        check(f"{a.id}: ledgered {n} trades ({e2} adds), {sized} sized, equity {acct['equity']:,.0f}",
              acct is not None and n == len(docs) and (n == 0 or sized > 0))

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
