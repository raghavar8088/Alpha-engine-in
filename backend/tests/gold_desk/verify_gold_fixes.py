"""The Gold Desk after its research: every C- / I-item and H1, tested. No Mongo, no network.

Run:  python backend/tests/gold_desk/verify_gold_fixes.py

What is held here (GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md):
  fills    the live exit rule IS the research replay's rule, case for case (gd_replay._resolve)
  C1       signals on closed bars only — and only once the store re-read the bar after its close;
           one decision per closed bar; no decision on a stale bar; none taken late
  FINAL    exits walk only minutes the store re-read after they closed; a pruned stretch is read
           from the venue; the hold limit waits for the store to reach it; funding is charged
           only over the stretch the walk has cleared, at the rate of the hour before each exchange
  C2       MCX positions priced on their own contract; roll exit; expired contracts settle
  C3       touch fills; minute-walked exits; market exits pay the measured half-spread; funding
           at every exchange; a fee the venue does not publish refuses the trade
  C4       the hold limit is bars, not wall clock
  C5/I2    no offsetting entry; net-lot and notional caps; per-lot risk budget
  C6       the breaker measures from the day's opening equity
  C7       the Delta feed is incremental and an unchanged candle is not rewritten; equity rows
           only while a book is live and only when something changed
  C8       RECORD, never READY; the scheduler manages stops with Main Control off
  C9/I1    session templates off a 24/7 venue; nothing below 4h; MCX trades nothing by default
  H1       pre-registered once, before any H1 position; the decision applies exactly its rule
"""

from __future__ import annotations

import asyncio
import random
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import ROOT, Coll, check, finish, section  # noqa: E402

import numpy as np  # noqa: E402

from app.services import gold_delta_feed as F  # noqa: E402
from app.services import gold_desk as G  # noqa: E402
from app.services import gold_fills as GF  # noqa: E402
from app.services import gold_h1 as H  # noqa: E402

UTC = timezone.utc


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


asyncio.set_event_loop(asyncio.new_event_loop())

# ═════════════════════════════════════════════════════════════════════════════════
section("FILLS — the live rule is the research replay's rule")

sys.path.insert(0, str(ROOT / "backend" / "research" / "gold_2026_10"))
import gd_replay as R  # noqa: E402

rng = random.Random(20261011)
mismatch, cases = 0, 0
for trial in range(4000):
    n = rng.randint(3, 40)
    px = 100.0
    ts = np.arange(n, dtype=np.int64) * 60 + 1_700_000_000
    o, h, lo, c = (np.zeros(n) for _ in range(4))
    for i in range(n):
        gap = rng.gauss(0, 0.6) if rng.random() < 0.15 else rng.gauss(0, 0.05)
        o[i] = px + gap
        moves = [o[i] + rng.gauss(0, 0.4) for _ in range(3)]
        h[i], lo[i] = max(o[i], *moves), min(o[i], *moves)
        c[i] = moves[-1]
        px = c[i]
    side = rng.choice([1, -1])
    entry = float(o[0])
    tgt = entry * (1 + side * rng.uniform(0.002, 0.02))
    stp = entry * (1 - side * rng.uniform(0.002, 0.02))
    X = {"o": o, "h": h, "l": lo, "c": c, "ts": ts, "full": np.ones(n, dtype=bool)}
    k, price, why = R._resolve(side, 0, n - 1, tgt, stp, X)
    mins = [(int(ts[i]), o[i], h[i], lo[i], c[i]) for i in range(n)]
    ex = GF.walk_exit(side, mins, tgt, stp, entry_minute_ts=int(ts[0]))
    cases += 1
    if why in (0, 1):
        ok = ex is not None and ex.reason == ("target" if why == 0 else "stoploss") and \
            abs(ex.price - price) < 1e-9 and ex.ts == int(ts[k])
    else:
        ok = ex is None
    mismatch += 0 if ok else 1
check(f"walk_exit == the replay's _resolve on {cases} random paths (gaps, both sides, wicks)", mismatch == 0,
      f"{mismatch} mismatches")

m = [(0, 100.0, 100.4, 99.9, 100.3), (60, 100.3, 101.5, 100.2, 101.2)]
e = GF.walk_exit(1, m, 101.0, 99.0)
check("a long's target touched inside a minute fills AT the target, not at the high", e.price == 101.0 and e.reason == "target")
e = GF.walk_exit(1, [(0, 102.0, 102.5, 101.8, 102.2)], 101.0, 99.0)
check("a minute OPENING past the target fills at that open (a resting limit)", e.price == 102.0 and e.basis == "gap_open")
e = GF.walk_exit(1, [(0, 100.0, 101.2, 98.8, 100.0)], 101.0, 99.0)
check("a minute touching both levels is a stop", e.reason == "stoploss" and e.price == 99.0)
e = GF.walk_exit(-1, [(0, 101.5, 101.8, 101.2, 101.4)], 99.0, 101.0)
check("a short gapped through its stop fills at the (worse) open", e.reason == "stoploss" and e.price == 101.5)
check("no level touched: no exit", GF.walk_exit(1, [(0, 100.0, 100.5, 99.5, 100.1)], 101.0, 99.0) is None)
check("a market exit pays the half-spread: a long sells lower",
      abs(GF.market_exit_price(100.0, 1, 1.0) - 99.99) < 1e-9 and abs(GF.market_exit_price(100.0, -1, 1.0) - 100.01) < 1e-9)
check("the hold limit exits at the close of the last minute before the 60th bar's close",
      GF.time_exit([(0, 1, 1, 1, 1.0), (60, 1, 1, 1, 2.0), (120, 1, 1, 1, 3.0)], 120) == (60, 2.0))
check("funding exchanges in (since, until] on the interval's multiples",
      GF.funding_exchanges(14000, 43200, 14400) == [14400, 28800, 43200] and GF.funding_exchanges(14400, 14500, 14400) == [])
check("a positive rate costs a long and pays a short",
      GF.funding_cost(1, 1000.0, 0.005) == 0.05 and GF.funding_cost(-1, 1000.0, 0.005) == -0.05)

# ═════════════════════════════════════════════════════════════════════════════════
section("DELTA FEED — C1 closed bars, C7 incremental writes, D7 fail-closed fee, touch fills")

bars_c, state_c, log_c = Coll("bars"), Coll("state"), Coll("book_log")
F.gold_bars_collection, F.gold_state_collection, F.book_log_collection = bars_c, state_c, log_c
G.gold_state_collection = state_c
H.gold_state_collection = state_c

now = datetime.now(UTC).replace(second=0, microsecond=0)
four_h = now.replace(minute=0) - timedelta(hours=now.hour % 4)          # the forming 4h bar's start
for k in range(70, -1, -1):                                              # 70 closed + 1 forming
    ts = four_h - timedelta(hours=4 * k)
    bars_c.docs.append({"symbol": "XAUTUSD", "timeframe": "4h", "ts": ts, "open": 1.0, "high": 2.0,
                        "low": 0.5, "close": 1.5, "volume": 1})
got = run(F.load_bars("XAUTUSD", "4h", limit=250, closed_only=True))
check("closed_only drops the 4h bar still forming", got[-1].ts == four_h - timedelta(hours=4), got[-1].ts)
got_all = run(F.load_bars("XAUTUSD", "4h", limit=250, closed_only=False))
check("…which the plain read includes", got_all[-1].ts == four_h)

calls = []


async def fake_get(path, params):
    calls.append((path, dict(params)))
    if path.startswith("/v2/history/candles"):
        start, end = int(params["start"]), int(params["end"])
        step = 3600 * 4 if params["resolution"] == "4h" else 60
        first = (start // step) * step
        px = 7.0 if params["resolution"] == "1m" else 1.5     # venue-read minutes are told apart below
        return {"result": [{"time": t, "open": 1.0, "high": 2.0, "low": 0.5, "close": px, "volume": 1}
                           for t in range(first, end + 1, step)]}
    if path.startswith("/v2/products/"):
        return {"result": {"contract_value": "0.001", "tick_size": "0.01", "taker_commission_rate": "0",
                           "maker_commission_rate": "0.0001", "product_specs": {"rate_exchange_interval": 14400}}}
    raise AssertionError(path)

F._get = fake_get
writes_before = bars_c.writes
res = run(F.refresh_symbol("XAUTUSD", ["4h"]))
start_param = [p for (pa, p) in calls if pa.startswith("/v2/history/candles")][0]["start"]
latest = int((four_h).timestamp())
check("an incremental refresh fetches from the last stored bar (minus 3 to re-read a forming one)",
      start_param == latest - 3 * 4 * 3600, (start_param, latest))
check("…and an unchanged candle is not rewritten (no updated_at churn)",
      bars_c.writes - writes_before == 0, bars_c.writes - writes_before)
check("no `updated_at` is set on candles any more", all("updated_at" not in d for d in bars_c.docs))
read_at = run(F.fetched_at("XAUTUSD", "4h"))
check("a successful read records WHEN it happened — what makes a stored bar final",
      read_at is not None and abs(read_at - int(datetime.now(UTC).timestamp())) < 60
      and run(F.fetched_at("XAUTUSD", "45m")) is None and run(F.fetched_at("XAUTUSD", "1m")) is None)


async def failing_get(path, params):
    raise RuntimeError("venue down")
F._get = failing_get
state_c.docs = [d for d in state_c.docs if d.get("_id") != "delta_bars"]
run(F.refresh_symbol("XAUTUSD", ["4h"]))
check("…and a failed read records nothing, so nothing counts as final on it",
      run(F.fetched_at("XAUTUSD", "4h")) is None)
F._get = fake_get
F._PRODUCTS.clear()
spec = run(F.product("XAUTUSD"))
check("a product publishing a ZERO taker rate yields None — the desk refuses rather than charges 0 (D7)",
      spec["taker_fee_rate"] is None and spec["funding_interval_s"] == 14400)

old = datetime(2020, 1, 1, tzinfo=UTC)
bars_c.docs.append({"symbol": "PAXGUSD", "timeframe": "1m", "ts": old, "open": 1, "high": 1, "low": 1, "close": 1})
removed = run(F.prune(["PAXGUSD"]))
check("prune removes bars beyond KEEP_BARS (a symbol no longer refreshed ages out)", removed == 1)

T = 14400 * 1000                                   # an exchange
s = [(T - 7200, 0.004), (T - 3600, 0.005), (T, 0.009)]
check("the rate in force at an exchange is the hour that ENDED at it — the hour starting there "
      "is the NEXT exchange's quote",
      F.rate_at(s, T) == (0.005, "series") and F.rate_at(s, T + 3600) == (0.009, "series")
      and F.rate_at(s, T - 7200) == (0.004, "series_edge") and F.rate_at([], 5) == (None, "none"))

nowi = int(datetime.now(UTC).timestamp()) // 60 * 60 - 120
bars_c.docs = [d for d in bars_c.docs if d["timeframe"] != "1m"]
for k in range(5, -1, -1):
    bars_c.docs.append({"symbol": "XAUTUSD", "timeframe": "1m", "ts": datetime.fromtimestamp(nowi - 60 * k, UTC),
                        "open": 1, "high": 1, "low": 1, "close": 1})


def set_fetched(tf, epoch, sym="XAUTUSD"):
    doc = next((d for d in state_c.docs if d.get("_id") == "delta_bars"), None)
    if doc is None:
        doc = {"_id": "delta_bars"}
        state_c.docs.append(doc)
    doc.setdefault("fetched", {}).setdefault(sym, {})[tf] = epoch


check("no record of a 1m read: no minute is walked", run(F.minutes("XAUTUSD", nowi - 600, nowi + 600)) == [])
set_fetched("1m", nowi + 5)                         # read 5 s into minute `nowi`: minute nowi-60 closed 5 s before
mm = run(F.minutes("XAUTUSD", nowi - 300, nowi + 600))
check("a minute read only seconds after its close — or while forming — is not walked yet",
      mm and mm[-1][0] == nowi - 120, [m[0] - nowi for m in mm])
set_fetched("1m", nowi + 75)
mm = run(F.minutes("XAUTUSD", nowi - 300, nowi + 600))
check("…and is walked once the store re-reads it after its close", mm and mm[-1][0] == nowi, [m[0] - nowi for m in mm])
calls.clear()
mm = run(F.minutes("XAUTUSD", nowi - 900, nowi + 600))
venue_mins = [m for m in mm if m[4] == 7.0]
check("a stretch the store no longer holds (pruned across an outage) is read from the venue, not skipped",
      mm[0][0] == nowi - 900 and len(venue_mins) == 10 and any(p["resolution"] == "1m" for _, p in calls),
      (len(mm), len(venue_mins)))
F._get = failing_get
check("…and if the venue cannot be read, nothing is walked (the walk waits)",
      run(F.minutes("XAUTUSD", nowi - 900, nowi + 600)) == [])
F._get = fake_get

# price_at: H1's benchmark price at a week boundary (its own symbol, so nothing above interferes)
tb_s = nowi - 90                                   # a boundary 30 s into the minute opening at nowi-120
tb = datetime.fromtimestamp(tb_s, UTC)
for ts_, c_ in ((nowi - 240, 0.9), (nowi - 180, 1.0), (nowi - 120, 1.1)):
    bars_c.docs.append({"symbol": "PXTEST", "timeframe": "1m", "ts": datetime.fromtimestamp(ts_, UTC),
                        "open": c_, "high": c_, "low": c_, "close": c_})
bars_c.docs.append({"symbol": "PXTEST", "timeframe": "4h", "open": 3.5, "high": 3.5, "low": 3.5, "close": 3.5,
                    "ts": datetime.fromtimestamp((tb_s - 14400) // 14400 * 14400, UTC)})
for tf_ in ("1m", "4h", "1d"):
    set_fetched(tf_, nowi - 100, "PXTEST")
check("no price at a boundary until the store has been re-read past it", run(F.price_at("PXTEST", tb)) is None)
set_fetched("1m", nowi + 75, "PXTEST")
got = run(F.price_at("PXTEST", tb))
check("the boundary price is the close of the last FINAL minute that ended at or before it — not the "
      "minute it falls inside", got == (1.0, "1m"), got)
bars_c.docs = [d for d in bars_c.docs if not (d["symbol"] == "PXTEST" and d["timeframe"] == "1m" and d["ts"] <= tb)]
set_fetched("4h", nowi + 75, "PXTEST")
got = run(F.price_at("PXTEST", tb))
check("…falling back to the last 4h close when the minutes are gone", got == (3.5, "4h"), got)


async def fake_ticker(sym):
    return {"bid": 100.0, "ask": 100.1, "bid_size": 50.0, "ask_size": 50.0, "mid": 100.05, "spread_bp": 9.995,
            "mark": 100.04, "funding_rate": 0.005}


async def fake_book(sym, depth=50):
    return {"bids": [(100.0, 50), (99.9, 100)], "asks": [(100.1, 50), (100.2, 100)]}

F.ticker, F.l2_book = fake_ticker, fake_book
f1 = run(F.fill_price("XAUTUSD", "BUY", 20))
check("an order inside the touch fills at the ask", f1["price"] == 100.1 and f1["basis"] == "touch")
f2 = run(F.fill_price("XAUTUSD", "BUY", 100))
check("an order bigger than the touch walks the book", f2["basis"] == "book_walk" and abs(f2["price"] - 100.15) < 1e-9)
check("a book that cannot fill the order gives no fill", run(F.fill_price("XAUTUSD", "BUY", 1000)) is None)

calls.clear()
F._last_book_sample = 0.0
F.sample_book = lambda s: asyncio.sleep(0, result={"ok": True})
run(F.idle_pass())
check("while no Delta book is live the feed fetches no candles (C7)",
      not any(pa.startswith("/v2/history/candles") for pa, _ in calls))

# ═════════════════════════════════════════════════════════════════════════════════
section("CATALOGUE — I1 nothing below 4h, C9 no session templates on 24/7, MCX off by default")

dspecs = G.specs_for(G.VENUES["delta"])
check("Delta trades exactly H1: nine templates at 4h",
      len(dspecs) == 9 and {s.timeframe for s in dspecs} == {"4h"} and {s.template for s in dspecs} == set(H.H1_TEMPLATES))
check("MCX trades nothing by default — every strategy was retired by the research",
      G.specs_for(G.VENUES["mcx"]) == [])
fake = G.Venue(**{**G.VENUES["delta"].__dict__, "allowed": (("opening_range", "4h"), ("gap_fade", "4h"),
                                                            ("donchian_fast", "1h"), ("donchian_fast", "4h"))})
names = {(s.template, s.timeframe) for s in G.specs_for(fake)}
check("session templates never run on a 24/7 venue, and nothing below 4h runs anywhere",
      names == {("donchian_fast", "4h")}, names)
check("GOLD (1 kg) is no longer on the MCX book; Delta trades one token", G.VENUES["mcx"].symbols == ("GOLDM",)
      and G.VENUES["delta"].symbols == ("XAUTUSD",))

# ═════════════════════════════════════════════════════════════════════════════════
section("H1 — stored once, before any H1 position; the decision is exactly the rule")

state_c.docs = []
r1 = run(H.ensure_preregistered())
r2 = run(H.ensure_preregistered())
check("the rule is stored once, with a fingerprint", r1["stored"] and not r2["stored"] and r1["fingerprint"] == r2["fingerprint"])
state_c.docs[0]["fingerprint"] = "drifted00000000"
pos_c = Coll("positions")
H.gold_positions_collection = pos_c


async def no_bars(*a, **k):
    return []
F.load_bars = no_bars
rep = run(H.report())
check("a code rule that drifts from the stored one is reported, and the stored one governs",
      rep["code_matches_stored"] is False and rep["status"] == "COLLECTING")
state_c.docs[0]["fingerprint"] = H.fingerprint(H.PREREGISTRATION)

pos_t = [{"net_bp": 5.0 + (i % 7) - 3, "week": i % 104} for i in range(400)]
xa = [0.001 * ((i % 5) - 2) for i in range(104)]
bw = [0.002 + 0.0001 * ((i % 3) - 1) + 0.3 * x for i, x in enumerate(xa)]
check("before week 52: COLLECTING whatever the numbers", H.decide(pos_t, bw[:30], xa[:30], 30)["status"] == "COLLECTING")
neg = [{"net_bp": -1.0 - (i % 3), "week": i % 52} for i in range(150)]
check("at week 52 a non-positive pooled net is FUTILE", H.decide(neg, bw[:52], xa[:52], 52)["status"] == "FUTILE")
late = [{"net_bp": 4.0 + (i % 3), "week": i % 52} for i in range(150)] + \
       [{"net_bp": -30.0, "week": 52 + (i % 40)} for i in range(150)]
d70 = H.decide(late, bw[:70], xa[:70], 70)
check("the futility rule is ONE look at week 52 — a later slump does not trigger it", d70["status"] == "COLLECTING", d70)
go = H.decide(pos_t, bw, xa, 104)
check("at week 104 with a positive mean, weekly t >= 2 and alpha t >= 2: GO", go["status"] == "GO", go)
few = H.decide(pos_t[:50], bw, xa, 104)
check("…but not on fewer than 100 trades", few["status"] == "NO-GO")
after = H.decide(pos_t + [{"net_bp": -500.0, "week": 120}] * 50, bw, xa, 130)
check("trades after week 104 are not part of the test", after["status"] == "GO" and after["trades"] == len(pos_t))
xa_gap = list(xa)
xa_gap[5] = xa_gap[17] = None
dg = H.decide(pos_t, bw, xa_gap, 104)
check("a week whose XAUT price could not be read is left out of the regression — never filled with zero",
      dg["xaut_weeks_measured"] == 102 and dg["status"] == "GO", dg.get("xaut_weeks_measured"))

stored_at = datetime.now(UTC) - timedelta(days=21, hours=1)
state_c.docs = [{"_id": H.PREREG_ID, "doc": H.PREREGISTRATION, "fingerprint": H.fingerprint(H.PREREGISTRATION),
                 "stored_at": stored_at}]
prices = {0: 4000.0, 1: 4040.0, 2: 4020.0, 3: 4100.0}


async def fake_price_at(sym, t):
    w = round((t - stored_at).total_seconds() / (7 * 86400))
    return (prices[w], "1m") if w in prices else None
real_price_at, F.price_at = F.price_at, fake_price_at
got = run(H.snapshot_boundaries())
check("XAUT's price at each week boundary is recorded as soon as it can be read", got == prices, got)
prices = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0}
got = run(H.snapshot_boundaries())
check("…and never rewritten afterwards", got == {0: 4000.0, 1: 4040.0, 2: 4020.0, 3: 4100.0}, got)
pos_c.docs = [{"_id": "h1a", "venue": "delta", "h1": True, "status": "CLOSED", "notional": 1000.0, "realized_pnl": 2.0,
               "closed_at": stored_at + timedelta(days=8)},
              {"_id": "h1b", "venue": "delta", "h1": True, "status": "CLOSED", "notional": 1000.0, "realized_pnl": 50.0,
               "closed_at": stored_at - timedelta(days=1)},
              {"_id": "h1c", "venue": "delta", "h1": True, "status": "VOID", "void": True, "notional": 1000.0,
               "realized_pnl": 99.0, "closed_at": stored_at + timedelta(days=2)}]
rep = run(H.report())
check("the report pairs the book's week with XAUT's own week, from the recorded boundaries",
      rep["weeks"] == 3 and rep["xaut_weeks_measured"] == 3, rep)
check("…counting only trades closed after the rule was stored, and never a void one",
      rep["trades"] == 1 and rep["net_bp_mean"] == 20.0, (rep["trades"], rep["net_bp_mean"]))
F.price_at = real_price_at
state_c.docs = []
pos_c.docs = []
check("is_h1 only for the nine templates at 4h on XAUTUSD",
      H.is_h1("keltner_break", "4h", "XAUTUSD") and not H.is_h1("keltner_break", "1h", "XAUTUSD")
      and not H.is_h1("engulfing", "4h", "XAUTUSD") and not H.is_h1("keltner_break", "4h", "PAXGUSD"))

# ═════════════════════════════════════════════════════════════════════════════════
section("DESK — switches, C1 decisions, C3 fills and funding, C4 holds, C8 records")

eq_c, tr_c, cb_c = Coll("equity"), Coll("trades"), Coll("commodity_bars")
pos_c = Coll("positions")
G.gold_positions_collection = H.gold_positions_collection = pos_c
G.gold_equity_collection, G.gold_trades_collection, G.commodity_bars_collection = eq_c, tr_c, cb_c
state_c.docs = []

try:
    run(G.set_enabled(G.VENUES["mcx"], True))
    check("enabling a venue with nothing to trade is refused", False)
except G.GoldDeskError as exc:
    check("enabling a venue with nothing to trade is refused, with the reason", "retired" in exc.detail)


async def prod(sym):
    return {"symbol": sym, "contract_value": 0.001, "taker_fee_rate": 0.0001, "funding_interval_s": 14400}
F.product = prod


async def mark(sym):
    return 4000.0
F.mark_price = mark
run(G.set_enabled(G.VENUES["delta"], True))
check("switching the H1 book on stores its pre-registration first",
      any(d.get("_id") == H.PREREG_ID for d in state_c.docs))


class Bar:
    def __init__(self, ts, c):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, c, c + 1, c - 1, c, 1


closed_bars = [Bar(four_h - timedelta(hours=4 * k), 4000.0) for k in range(80, 0, -1)]


async def d_load(sym, tf, limit=250, closed_only=False, now=None):
    assert closed_only is True, "the desk must ask for closed bars"
    return list(closed_bars)
F.load_bars = d_load


class Sig:
    side, entry, target, stoploss, pattern, rationale, confidence = "BUY", 4000.0, 4040.0, 3980.0, "p", "r", 0.6

evaluated = []


def fake_eval(spec, bars):
    evaluated.append((spec.template, bars[-1].ts))
    return Sig() if spec.template == "donchian_fast" else None
G.evaluate = fake_eval


async def tick(sym):
    return {"bid": 3999.9, "ask": 4000.1, "bid_size": 9e9, "ask_size": 9e9, "mid": 4000.0, "spread_bp": 0.5,
            "mark": 4000.0, "funding_rate": 0.005}
F.ticker = tick


async def fp(sym, side, n):
    return {"price": 4000.1 if side == "BUY" else 3999.9, "basis": "touch", "spread_bp": 0.5,
            "bid": 3999.9, "ask": 4000.1, "mark": 4000.0, "mid": 4000.0}
F.fill_price = fp
dv = G.VENUES["delta"]
G._now = lambda: four_h + timedelta(minutes=2)           # two minutes after the last 4h bar closed
set_fetched("4h", int(four_h.timestamp()) - 30)          # …but the store last read it before its close
out0 = run(G.scan_cycle(dv, entries_allowed=True))
check("a bar closed by the clock but not re-read since its close is not decided — nor marked, so the "
      "next cycle decides it", out0["evaluated"] == 0 and any("re-read" in n for n in out0["notes"])
      and not any(d.get("_id") == "delta:entry_bars" for d in state_c.docs), out0["notes"])
set_fetched("4h", int(four_h.timestamp()) + 60)
out = run(G.scan_cycle(dv, entries_allowed=True))
check("the scan evaluates the LAST CLOSED bar, once per template", out["evaluated"] == 9 and
      all(ts == closed_bars[-1].ts for _t, ts in evaluated), out)
p = pos_c.docs[0] if pos_c.docs else {}
check("a signal opens one position at the ask (a touch fill), H1-stamped with the stored fingerprint",
      out["opened"] == 1 and p.get("entry_price") == 4000.1 and p.get("entry_basis") == "touch" and p.get("h1") is True
      and p.get("prereg_fingerprint") == H.fingerprint(H.PREREGISTRATION))
sleeve = dv.capital / 9
check("sized to one sleeve of capital / 9 at 1x", p.get("units") == int(sleeve // (4000.0 * 0.001)), p.get("units"))
check("levels scaled by fill / signal close", abs(p["target"] - 4040.0 * 4000.1 / 4000.0) < 1e-3)
check("the hold limit is the close of the 60th 4h bar after the signal bar (C4)",
      G._aware(p["hold_until"]) == G._aware(p["signal_bar_close"]) + timedelta(hours=4 * 60))
evaluated.clear()
out2 = run(G.scan_cycle(dv, entries_allowed=True))
check("one decision per closed bar: the same bar is not evaluated again", out2["evaluated"] == 0 and not evaluated)
check("Main Control off blocks entries", "Main Control" in run(G.scan_cycle(dv, entries_allowed=False))["notes"][0])

pos_c.docs.clear()
state_c.docs = [d for d in state_c.docs if d.get("_id") != "delta:entry_bars"]
G._now = lambda: four_h + timedelta(minutes=20)
evaluated.clear()
out_late = run(G.scan_cycle(dv, entries_allowed=True))
G._now = lambda: four_h + timedelta(minutes=2)
out_late2 = run(G.scan_cycle(dv, entries_allowed=True))
check("a bar first seen 20 minutes after its close is skipped — never traded late — and stays decided",
      out_late["evaluated"] == 0 and out_late["opened"] == 0 and not evaluated and not pos_c.docs
      and any("never traded late" in n for n in out_late["notes"]) and out_late2["evaluated"] == 0, out_late["notes"])

stale_bars = [Bar(four_h - timedelta(hours=4 * k), 4000.0) for k in range(90, 10, -1)]


async def stale_load(sym, tf, limit=250, closed_only=False, now=None):
    return list(stale_bars)
F.load_bars = stale_load
state_c.docs = [d for d in state_c.docs if d.get("_id") != "delta:entry_bars"]
out3 = run(G.scan_cycle(dv, entries_allowed=True))
check("no decision on a bar that closed more than a bar ago", out3["evaluated"] == 0 and any("stale" in n for n in out3["notes"]))
F.load_bars = d_load


async def noprod(sym):
    return {"symbol": sym, "contract_value": 0.001, "taker_fee_rate": None, "funding_interval_s": 14400}
F.product = noprod
pos_c.docs.clear()
state_c.docs = [d for d in state_c.docs if d.get("_id") != "delta:entry_bars"]
out4 = run(G.scan_cycle(dv, entries_allowed=True))
check("no published fee: the entry is refused, never charged at zero (D7)",
      out4["opened"] == 0 and any("taker fee" in n for n in out4["notes"]))
F.product = prod
state_c.docs = [d for d in state_c.docs if d.get("_id") != "delta:entry_bars"]
run(G.scan_cycle(dv, entries_allowed=True))
pos = dict(pos_c.docs[0])

# exits walked over minutes
t0 = int(pos["checked_through"])
F.minutes = lambda sym, a, b: asyncio.sleep(0, result=[(t0, 4000.1, 4010.0, 3995.0, 4005.0),
                                                       (t0 + 60, 4005.0, 4060.0, 4004.0, 4050.0)])
G.time = types.SimpleNamespace(time=lambda: t0 + 600)
F.funding_series = lambda s: asyncio.sleep(0, result=[])
r = run(G._manage_delta(dv, pos, {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
cl = pos_c.docs[0]
check("a target crossed inside a minute closes AT the target — not at the minute's high",
      r == "target" and abs(cl["exit_price"] - pos["target"]) < 1e-9 and cl["exit_basis"] == "minute_level")
fee = 4000.1 * pos["qty"] * 0.0001 * 1.18 + cl["exit_price"] * pos["qty"] * 0.0001 * 1.18
check("costs = the venue fee x GST on both legs (+ funding)", abs(cl["costs"] - fee) < 1e-3, (cl["costs"], fee))

pos_c.docs[0] = {**pos, "status": "OPEN"}
F.minutes = lambda sym, a, b: asyncio.sleep(0, result=[(t0, 4000.1, 4001.0, 3970.0, 3975.0)])
run(G._manage_delta(dv, dict(pos_c.docs[0]), {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
cl = pos_c.docs[0]
check("a stop is a market order: the stop level less the measured half-spread",
      abs(cl["exit_price"] - pos["stoploss"] * (1 - dv.exit_slip_bp / 1e4)) < 1e-4 and cl["exit_reason"] == "stoploss")

hold_ts = int(G._aware(pos["hold_until"]).timestamp())
check("the hold limit falls on a funding exchange (4h bars close on them)", hold_ts % 14400 == 0)
pos_c.docs[0] = {**pos, "status": "OPEN", "funding_through": hold_ts - 14400 - 100, "ltp": 4000.0}
G.time = types.SimpleNamespace(time=lambda: hold_ts + 120)
F.minutes = lambda sym, a, b: asyncio.sleep(0, result=[(hold_ts - 120, 4001, 4002, 4000, 4001.5),
                                                       (hold_ts - 60, 4001.5, 4003, 4001, 4002.0)])
F.funding_series = lambda s: asyncio.sleep(0, result=[(hold_ts - 14400 - 3600, 0.005)])
set_fetched("1m", hold_ts - 30)                          # the store has not reached the hold limit yet
r = run(G._manage_delta(dv, dict(pos_c.docs[0]), {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
check("past the hold limit but before the store reaches it: the position waits",
      r is None and pos_c.docs[0]["status"] == "OPEN")
set_fetched("1m", hold_ts + 60)
r = run(G._manage_delta(dv, dict(pos_c.docs[0]), {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
cl = pos_c.docs[0]
check("at the hold limit the position exits at the last minute's close, as a market order, stamped at the limit",
      r == "max_hold" and abs(cl["exit_price"] - 4002.0 * (1 - dv.exit_slip_bp / 1e4)) < 1e-4
      and G._aware(cl["closed_at"]) == datetime.fromtimestamp(hold_ts, UTC))
check("…and leaves before the exchange AT the hold limit: one exchange paid, not two",
      cl["funding_events"] == 1 and abs(cl["funding_paid"] - pos["qty"] * 4000.0 * 0.005 / 100) < 1e-9,
      (cl["funding_events"], cl["funding_paid"]))
pos_c.docs[0] = {**pos, "status": "OPEN"}
set_fetched("1m", hold_ts - 30)
G.time = types.SimpleNamespace(time=lambda: hold_ts + 700)
r = run(G._manage_delta(dv, dict(pos_c.docs[0]), {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
check("a store still short of the hold limit ten minutes later: out on the live book, labelled",
      r == "max_hold" and pos_c.docs[0]["exit_basis"] == "quote_fallback" and pos_c.docs[0]["exit_price"] == 3999.9)

E = int(four_h.timestamp()) + 2 * 14400                  # an exchange well inside the hold
pos_c.docs[0] = {**pos, "status": "OPEN", "checked_through": E - 300, "funding_through": E - 300,
                 "funding_paid": 0.0, "funding_events": 0, "ltp": 4000.0}
G.time = types.SimpleNamespace(time=lambda: E + 600)
F.minutes = lambda sym, a, b: asyncio.sleep(0, result=[(t, 4000.0, 4000.0, 4000.0, 4000.0)
                                                       for t in range(int(a), min(int(b), E - 120), 60)])
F.funding_series = lambda s: asyncio.sleep(0, result=[(E - 3600, 0.005)])
set_fetched("1m", E + 600)
run(G._manage_delta(dv, dict(pos_c.docs[0]), {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
p1 = pos_c.docs[0]
check("funding is charged only over the stretch the walk has cleared — not the exchange the clock has "
      "passed while the minutes still lag", p1["checked_through"] == E - 120 and p1.get("funding_events") == 0,
      (p1["checked_through"] - E, p1.get("funding_events")))
F.minutes = lambda sym, a, b: asyncio.sleep(0, result=[(t, 4000.0, 4000.0, 4000.0, 4000.0)
                                                       for t in range(int(a), min(int(b), E + 180), 60)])
run(G._manage_delta(dv, dict(pos_c.docs[0]), {"taker_fee_rate": 0.0001, "funding_interval_s": 14400}))
p2 = pos_c.docs[0]
check("…and once the walk clears the exchange, it is paid", p2["checked_through"] == E + 180
      and p2["funding_events"] == 1, (p2["checked_through"] - E, p2.get("funding_events")))

pos_c.docs[0] = {**pos, "status": "OPEN", "funding_through": 14400 * 1000 + 100, "ltp": 4000.0}
G.time = types.SimpleNamespace(time=lambda: 14400 * 1003 + 50)
F.funding_series = lambda s: asyncio.sleep(0, result=[(14400 * 1000, 0.005)])
F.minutes = lambda sym, a, b: asyncio.sleep(0, result=[])
fund = run(G._accrue_funding(dv, dict(pos_c.docs[0]), 14400 * 1003 + 50, {"funding_interval_s": 14400}))
expect = 3 * pos["qty"] * 4000.0 * 0.005 / 100
check("funding: three exchanges crossed, a long pays rate% x notional at each",
      abs(fund["funding_paid"] - expect) < 1e-9 and fund["funding_events"] == 3, fund)

# ═════════════════════════════════════════════════════════════════════════════════
section("MCX — C2 own contract and rolls, C5 exposure, C6 breaker (account mode)")

mv = G.Venue(**{**G.VENUES["mcx"].__dict__, "allowed": G.H1_PAIRS})


class Q:
    def __init__(self, ltp, fresh=True, bid=None, ask=None, why=""):
        self.ltp, self.fresh, self.bid, self.ask, self.why = ltp, fresh, bid or ltp - 5, ask or ltp + 5, why
        self.spread_bp = (self.ask - self.bid) / ltp * 1e4

    def touch(self, side):
        return (self.ask if side == "BUY" else self.bid) if self.fresh else None

    def as_doc(self):
        return {"ltp": self.ltp, "bid": self.bid, "ask": self.ask, "fresh": self.fresh}


seen_tokens = []


async def quotes(contracts):
    out = {}
    for ct in contracts:
        tok = str(ct.get("angel_token") or ct.get("security_id"))
        seen_tokens.append(tok)
        out[tok] = Q(150000.0) if tok != "STALE" else Q(150000.0, fresh=False, why="no trade for 30 min")
    return out
G.mcx_market.quotes = quotes
pos_c.docs.clear()
own = {"_id": "m1", "venue": "mcx", "status": "OPEN", "symbol": "GOLDM", "side": "BUY", "qty": 10.0, "units": 1,
       "entry_price": 149000.0, "entry_costs": 92.0, "target": 152000.0, "stoploss": 148000.0, "notional": 1490000.0,
       "margin_used": 137000.0, "timeframe": "4h", "max_hold_bars": 60, "checked_through": 0,
       "signal_bar_ts": datetime.now(UTC) - timedelta(hours=8), "opened_at": datetime.now(UTC),
       "instrument": {"angel_token": "NOV", "security_id": "NOV", "expiry": "2099-11-05", "symbol": "GOLDM05NOV"}}
pos_c.docs.append(dict(own))
G.mcx_market.forced_exit = lambda p, today=None: None
G._mcx_minutes = lambda *a: asyncio.sleep(0, result=[])
G.time = types.SimpleNamespace(time=lambda: 10_000)
run(G._manage_mcx(mv, dict(pos_c.docs[0])))
check("a position is quoted on ITS OWN contract's token, not the new front month (C2)", seen_tokens[-1] == "NOV")

G.mcx_market.forced_exit = lambda p, today=None: "roll_exit"
run(G._manage_mcx(mv, dict(pos_c.docs[0])))
check("inside the roll window the position is closed at its own contract's bid", pos_c.docs[0]["exit_reason"] == "roll_exit"
      and pos_c.docs[0]["exit_price"] == 150000.0 - 5)

pos_c.docs[0] = dict(own)
G.mcx_market.forced_exit = lambda p, today=None: "contract_expired"
G.last_contract_price = lambda s, e: asyncio.sleep(0, result=(151234.0, datetime.now(UTC)))
run(G._manage_mcx(mv, dict(pos_c.docs[0])))
check("an expired contract settles at its own last print", pos_c.docs[0]["exit_reason"] == "contract_expired"
      and pos_c.docs[0]["exit_price"] == 151234.0 and pos_c.docs[0]["exit_basis"] == "contract_last_bar")

pos_c.docs[0] = {**own, "instrument": {**own["instrument"], "angel_token": "STALE", "security_id": "STALE"}}
G.mcx_market.forced_exit = lambda p, today=None: "roll_exit"
run(G._manage_mcx(mv, dict(pos_c.docs[0])))
check("a frozen quote fills nothing — the position waits, labelled", pos_c.docs[0]["status"] == "OPEN"
      and "waiting" in pos_c.docs[0].get("quote_status", ""))

G.mcx_market.forced_exit = lambda p, today=None: None
pos_c.docs = [dict(own)]
G.margin_pct = lambda s: 0.092
inst = {"angel_token": "NOV", "security_id": "NOV", "expiry": "2099-11-05", "symbol": "GOLDM05NOV"}


class SSig(Sig):
    side, entry, target, stoploss = "SELL", 150000.0, 147000.0, 151500.0

bar = Bar(four_h - timedelta(hours=4), 150000.0)
ok, why = run(G._open(mv, G.specs_for(mv)[0], "GOLDM", inst, SSig(), bar, 240, 3_000_000.0, None))
check("an entry offsetting an open position on the same contract is refused (C5)", not ok and "net it" in why, why)
ok, why = run(G._open(mv, G.specs_for(mv)[1], "GOLDM", inst, Sig.__new__(type("B", (Sig,), {"entry": 150000.0,
              "target": 152000.0, "stoploss": 148500.0})), bar, 240, 3_000_000.0, None))
check("a second long lot is allowed within the net and notional caps", ok, why)
ok, why = run(G._open(mv, G.specs_for(mv)[2], "GOLDM", inst, Sig.__new__(type("B2", (Sig,), {"entry": 150000.0,
              "target": 152000.0, "stoploss": 148500.0})), bar, 240, 3_000_000.0, None))
check("a third lot is refused — net lots / notional cap (2 GOLDM lots on Rs 30 lakh)", not ok, why)
pos_c.docs = []
ok, why = run(G._open(mv, G.specs_for(mv)[0], "GOLDM", inst, Sig.__new__(type("W", (Sig,), {"entry": 150000.0,
              "target": 160000.0, "stoploss": 140000.0})), bar, 240, 3_000_000.0, None))
check("a lot whose stop risk exceeds the 1.5% budget is refused (I2)", not ok and "risks" in why, why)

state_c.docs = [d for d in state_c.docs if not str(d.get("_id", "")).startswith("mcx")]
G._day_key = lambda v: "2026-10-12"
pos_c.docs = [{"_id": "o1", "venue": "mcx", "status": "OPEN", "unrealized_pnl": 0.0, "margin_used": 1.0,
               "notional": 1.0}]
b0 = run(G.book(mv))
run(G.day_open_equity(mv, b0["equity"]))
pos_c.docs[0]["unrealized_pnl"] = -95_000.0          # opened on an earlier day, losing today
state_c.docs.append({"_id": "mcx", "enabled": True})
G._mcx_entries_known = lambda: True
out5 = run(G.scan_cycle(mv, entries_allowed=True))
check("the breaker counts a position opened on an earlier day (C6: from the day's opening equity)",
      out5["opened"] == 0 and "breaker" in out5["notes"][0].lower(), out5["notes"])

# ═════════════════════════════════════════════════════════════════════════════════
section("C7 equity rows, C8 records and the scheduler")

eq_c.docs.clear()
pos_c.docs.clear()
state_c.docs = [d for d in state_c.docs if d.get("_id") not in ("delta", "delta:equity_last")]
state_c.docs.append({"_id": "delta", "enabled": False})
G.manage_cycle = lambda v: asyncio.sleep(0, result=0)
run(G.run_cycle(dv, entries_allowed=True))
check("an OFF book with nothing open writes no equity row", len(eq_c.docs) == 0)
state_c.docs = [d for d in state_c.docs if d.get("_id") != "delta"] + [{"_id": "delta", "enabled": True}]
G.scan_cycle = lambda v, e=True: asyncio.sleep(0, result={"opened": 0, "evaluated": 0, "notes": []})
run(G.run_cycle(dv))
run(G.run_cycle(dv))
check("a live book writes a row, then nothing while unchanged", len(eq_c.docs) == 1, len(eq_c.docs))

pos_c.docs = [{"_id": "c1", "venue": "delta", "status": "CLOSED", "strategy_template": "keltner_break",
               "timeframe": "4h", "symbol": "XAUTUSD", "realized_pnl": 5.0, "costs": 0.3, "net_bp": 30.0,
               "closed_at": datetime.now(UTC)}]
rows = run(G.strategies(dv))
check("every row is a RECORD — never READY (C8)", rows and all(r["verdict"] == "RECORD" for r in rows))
check("all nine enabled H1 strategies are listed, traded or not", sum(1 for r in rows if r["enabled"]) == 9)

import app.services.desk_switches as DS  # noqa: E402
import app.services.gold_scheduler as S  # noqa: E402
DS.is_on = lambda key: asyncio.sleep(0, result=False)
G.open_count = lambda v: asyncio.sleep(0, result=1)
on, has_open, may_enter = run(S.venue_activity("delta"))
check("Main Control off: entries blocked, but a venue holding a position still gets its cycle (C8)",
      on is False and has_open is True and may_enter is False)

finish()
