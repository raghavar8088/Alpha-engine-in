"""End-to-end check of app.services.prelive_pick_books (Index Option Buying's three picked-strategy paper accounts)
with an in-memory Mongo. Needs `pip install mongomock-motor motor fastapi httpx`; run from the repo root:
    python backend/tests/prelive_pick_books/verify_prelive_pick_books.py
Real: prelive_pick_books, top10_books (its prelive loader, _option_parent, _row, _close_fields), plan_book,
angel_fees.option_round_trip (Angel's option card from the repo's shared/), the routes module.
Stubbed: app.core.db (in-memory), factory_desks (only its POSITIONS collection), intraday_v2_strategies, deps."""
import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "shared"))
from bson import ObjectId  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

DB = AsyncMongoMockClient()["test"]


class _DbModule(types.ModuleType):
    def __getattr__(self, name):          # any `*_collection` the imported modules ask for
        if name.startswith("__"):
            raise AttributeError(name)
        return DB[name]


dbmod = _DbModule("app.core.db")
dbmod.db = DB
sys.modules["app.core.db"] = dbmod
v2 = types.ModuleType("app.services.intraday_v2_strategies")
sys.modules[v2.__name__] = v2
fd = types.ModuleType("app.services.factory_desks")
fd.POSITIONS = DB["factory_desk_positions"]          # in production: the tab's own MongoDB
sys.modules[fd.__name__] = fd
deps = types.ModuleType("app.api.deps")


async def get_current_user():
    return {}


deps.get_current_user = get_current_user
sys.modules[deps.__name__] = deps

from app.services import prelive_pick_books as pb          # noqa: E402
from app.services.angel_fees import option_round_trip      # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


NOW = utc_naive(datetime.now(timezone.utc)).replace(microsecond=0)
START = NOW - timedelta(hours=3)
IST = timezone(timedelta(hours=5, minutes=30))
LOT = 65


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def fpos(pid, sid, entry, t_open, *, token="45396", status="OPEN", exit_=None, t_close=None, mark=None,
         desk="index-buying", kind="option_buy"):
    """A Strategy Factory tab position, as factory_desks writes it."""
    d = {"position_id": pid, "desk": desk, "strategy_id": sid, "strategy_name": sid, "kind": kind,
         "timeframe": "15m", "symbol": "NIFTY", "signal_side": "BUY", "side": "BUY",
         "legs": [{"token": token, "tradingsymbol": f"NIFTY17NOV26{token}CE", "strike": 25250.0, "option_type": "CE",
                   "expiry": "2026-11-17", "side": "BUY", "entry": entry}],
         "lots": 1, "lot_size": LOT, "entry_px": entry, "capital_deployed": round(entry * LOT, 2), "status": status,
         "opened_at": t_open, "opened_on": day(t_open), "closed_at": None, "closed_on": None, "exit_reason": None}
    if mark is not None:
        d["mark_legs"] = [mark]
    if status == "CLOSED":
        d.update({"exit_legs": [exit_], "closed_at": t_close, "closed_on": day(t_close), "exit_reason": "target"})
    return d


def option_net(entry, exit_, lots, on):
    gross = (exit_ - entry) * LOT * lots
    fb = option_round_trip(entry, max(exit_, 0.0), lots, LOT, on=datetime.fromisoformat(on).date())
    return round(gross, 2), round(gross - fb.total, 2), fb.total


async def factory_books():
    F = DB["factory_desk_positions"]
    for b in pb.BOOKS:
        await pb.STATE.insert_one({"_id": f"start:{b}", "started_at": START, "book": b})
    await F.insert_one(fpos("old", "SF0400", 150.0, START - timedelta(hours=2)))            # before the start
    await F.insert_one(fpos("f1", "SF0400", 150.0, NOW - timedelta(hours=2), mark=160.0))   # Top 10 #1, open
    await F.insert_one(fpos("f2", "SF0400", 120.0, NOW - timedelta(hours=1, minutes=30), token="45400"))  # while held
    await F.insert_one(fpos("f3", "SF0107", 100.0, NOW - timedelta(minutes=80), token="45401", status="CLOSED",
                            exit_=130.0, t_close=NOW - timedelta(minutes=20)))              # opened + closed between looks
    await F.insert_one(fpos("f4", "SF0116", 90.0, NOW - timedelta(minutes=70), token="45402", mark=95.0))  # #11
    await F.insert_one(fpos("f5", "SF9999", 90.0, NOW - timedelta(minutes=60), token="45403"))  # in no book
    await F.insert_one(fpos("f6a", "SF0474", 110.0, NOW - timedelta(minutes=50), token="45404", mark=111.0))
    await F.insert_one(fpos("f6b", "SF0330", 110.0, NOW - timedelta(minutes=50), token="45404", mark=111.0))
    await F.insert_one(fpos("f7", "SF0400", 80.0, NOW - timedelta(minutes=45), token="45405",
                            desk="index-selling", kind="credit_spread"))                     # another tab
    # SF0401 (#6) loses nearly all of its Rs 10 lakh, then signals again: no cash. Its neighbours are untouched.
    await F.insert_one(fpos("g1", "SF0401", 100.0, NOW - timedelta(minutes=40), token="45406", status="CLOSED",
                            exit_=2.0, t_close=NOW - timedelta(minutes=35)))
    # About Rs 25,000 is left; one lot at 500 costs Rs 32,500.
    await F.insert_one(fpos("g2", "SF0401", 500.0, NOW - timedelta(minutes=30), token="45407"))

    out = await pb.sync(entries=True)
    errs = {k: v for k, v in out.items() if "error" in v}
    check("first pass: every account of every book ran without an error",
          len(out) == sum(len(b.accounts()) for b in pb.BOOKS.values()) and not errs, str(errs or len(out)))
    out2 = await pb.sync(entries=True)                     # a copy opened in a pass is marked on the next
    check("second pass is clean", not [k for k, v in out2.items() if "error" in v])
    rows = [r async for r in pb.POSITIONS.find({})]
    by = {r["parent_position_id"]: r for r in rows}

    check("nothing opened before the book's start is copied", "old" not in by)
    check("a strategy in no book is never copied", "f5" not in by)
    check("another Strategy Factory tab's trade is never copied", "f7" not in by)
    f1 = by.get("f1")
    lots = int(1_000_000 // (150.0 * LOT))
    check("open copy: whole lots up to the strategy's own Rs 10 lakh", f1 is not None and f1["qty"] == lots
          and f1["status"] == "OPEN" and abs(f1["capital_deployed"] - lots * 150.0 * LOT) < 0.01,
          f"{f1 and f1.get('qty')} vs {lots}")
    check("open copy is marked at the tab's own mark (its bid)", f1 is not None
          and abs(f1["unrealized_pnl"] - (160.0 - 150.0) * LOT * lots) < 0.01, str(f1 and f1.get("unrealized_pnl")))
    check("open copy carries book, account, source, allocation, name and contract", f1 is not None
          and f1["book"] == "sf_top10" and f1["account"] == "SF0400" and f1["source"] == "pick"
          and f1["allocation"] == 1_000_000 and f1["strategy_name"] == "MACD Histogram Turn · 5m"
          and f1["label"] == "NIFTY 25250 CE 2026-11-17" and f1["expiry"] == "2026-11-17")
    check("a second signal while the strategy holds a position is skipped (one at a time)", "f2" not in by)
    f3 = by.get("f3")
    l3 = int(1_000_000 // (100.0 * LOT))
    g3, n3, fee3 = option_net(100.0, 130.0, l3, day(NOW - timedelta(minutes=20)))
    check("opened-and-closed copy: booked closed at the tab's exit, Angel's option card on its own lots",
          f3 is not None and f3["status"] == "CLOSED" and f3["qty"] == l3 and abs(f3["gross_pnl"] - g3) < 0.01
          and abs(f3["realized_pnl"] - n3) < 0.01 and abs(f3["fees"] - round(fee3, 2)) < 0.01,
          f"{f3 and (f3.get('qty'), f3.get('gross_pnl'), f3.get('realized_pnl'))} vs {(l3, g3, n3)}")
    f4 = by.get("f4")
    check("a Rank 11-20 strategy lands only in Top 10-20", f4 is not None and f4["book"] == "sf_top10_20"
          and f4["account"] == "SF0116" and len([r for r in rows if r["parent_position_id"] == "f4"]) == 1)
    check("two strategies on the same contract at once: each copied into its own account",
          "f6a" in by and "f6b" in by and by["f6a"]["account"] == "SF0474" and by["f6b"]["account"] == "SF0330")
    check("a strategy that lost its money cannot take the next trade (no cash)", "g1" in by and "g2" not in by)
    sc = await pb.SCORES.find_one({"book": "sf_top10", "key": "SF0401"})
    check("that skip is counted as no_cash", sc is not None and sc["skipped"].get("no_cash") == 1, str(sc))
    sc0 = await pb.SCORES.find_one({"book": "sf_top10", "key": "SF0400"})
    check("the held-position skip is counted as full", sc0 is not None and sc0["skipped"].get("full") == 1, str(sc0))

    # The tab closes f1 at 170: the copy closes at the same price.
    await F.update_one({"position_id": "f1"}, {"$set": {"status": "CLOSED", "exit_legs": [170.0],
                                                        "closed_at": NOW - timedelta(minutes=5),
                                                        "closed_on": day(NOW - timedelta(minutes=5)),
                                                        "exit_reason": "eod"}})
    await pb.sync(entries=True)
    f1b = await pb.POSITIONS.find_one({"parent_position_id": "f1"})
    g1_, n1_, _ = option_net(150.0, 170.0, lots, day(NOW - timedelta(minutes=5)))
    check("when the tab closes, the copy closes at the tab's exit", f1b["status"] == "CLOSED"
          and abs(f1b["realized_pnl"] - n1_) < 0.01 and f1b["exit_reason"] == "eod", str(f1b.get("realized_pnl")))
    n_before = await pb.POSITIONS.count_documents({})
    await pb.sync(entries=True)
    check("passes are idempotent: no duplicate copies", await pb.POSITIONS.count_documents({}) == n_before)

    s = await pb.summary("sf_top10")
    realized = sum(r["realized_pnl"] for r in rows if r["book"] == "sf_top10" and r["status"] == "CLOSED"
                   and r["parent_position_id"] != "f1") + f1b["realized_pnl"]
    check("Top 10 summary: Rs 10 lakh a strategy, Rs 1 crore in all, one position each",
          s["desk_capital"] == 10_000_000 and s["per_strategy_capital"] == 1_000_000 and s["position_cap"] == 1_000_000
          and s["max_open_positions"] == 10 and s["strategies"] == 10 and s["board_ranks"] == list(range(1, 11)))
    check("Top 10 summary adds up its accounts", abs(s["realized_pnl"] - realized) < 0.05,
          f"{s['realized_pnl']} vs {realized}")
    lb = await pb.leaderboard("sf_top10")
    r401 = next(r for r in lb if r["key"] == "SF0401")
    check("leaderboard: ten rows in rank order, each on its own Rs 10 lakh", [r["picked_rank"] for r in lb] == list(range(1, 11))
          and all(r["allocation"] == 1_000_000 for r in lb))
    check("leaderboard: the losing strategy's equity is its own Rs 10 lakh less its loss",
          abs(r401["equity"] - (1_000_000 + r401["net_pnl"])) < 0.01 and r401["net_pnl"] < -900_000, str(r401["equity"]))
    s2 = await pb.summary("sf_top10_20")
    check("Top 10-20 summary: ranks 11-20", s2["board_ranks"] == list(range(11, 21)) and s2["open_positions"] == 1)


async def best_book():
    P, T = DB["prelive_positions"], DB["prelive_trades"]
    t_a = NOW - timedelta(minutes=100)
    iso = lambda t: t.replace(tzinfo=timezone.utc).isoformat()   # noqa: E731 - the daemon's open rows keep an ISO string
    # intra_ha_reversal: an open position (ask 151, mark 160).
    await P.insert_one({"key": "intra_ha_reversal@15m", "entry_ts": iso(t_a), "entry_premium": 150.0, "entry_ask": 151.0,
                        "mark": 160.0, "security_id": "50001", "strike": 25300, "option_type": "PE",
                        "expiry": "2026-11-17", "lot_size": LOT})
    # it_fake_breakout wants the SAME contract a minute later: one contract per account -> skipped.
    await P.insert_one({"key": "it_fake_breakout@15m", "entry_ts": iso(t_a + timedelta(minutes=1)), "entry_premium": 150.5,
                        "entry_ask": 151.5, "mark": 160.0, "security_id": "50001", "strike": 25300,
                        "option_type": "PE", "expiry": "2026-11-17", "lot_size": LOT})
    # it_fake_breakout, a different contract: takes the second slot.
    await P.insert_one({"key": "it_fake_breakout@15m", "entry_ts": iso(t_a + timedelta(minutes=5)), "entry_premium": 90.0,
                        "entry_ask": 90.5, "mark": 92.0, "security_id": "50002", "strike": 25400,
                        "option_type": "CE", "expiry": "2026-11-17", "lot_size": LOT})
    # intra_ha_reversal again while both slots are used -> full.
    await P.insert_one({"key": "intra_ha_reversal@15m", "entry_ts": iso(t_a + timedelta(minutes=10)), "entry_premium": 70.0,
                        "entry_ask": 70.4, "mark": 71.0, "security_id": "50003", "strike": 25500,
                        "option_type": "CE", "expiry": "2026-11-17", "lot_size": LOT})
    # A Top 10 strategy that is not one of the two: never copied.
    await P.insert_one({"key": "ema_200_trend@15m", "entry_ts": iso(t_a), "entry_premium": 80.0, "entry_ask": 80.4,
                        "mark": 81.0, "security_id": "50004", "strike": 25200, "option_type": "CE",
                        "expiry": "2026-11-17", "lot_size": LOT})
    await pb.sync(entries=True, only="best2L")
    await pb.sync(entries=True, only="best2L")
    # Premium Option Buying Strategies (16 Nov 2026): the same two, the same trades, on one Rs 50,000 account.
    await pb.sync(entries=True, only="premium50k")
    await pb.sync(entries=True, only="premium50k")
    prem = [r async for r in pb.POSITIONS.find({"book": "premium50k"})]
    check("premium50k: the same two positions as best2L, the shared contract skipped",
          sorted((r["key"], r["symbol"]) for r in prem) == [("intra_ha_reversal@15m", "50001"), ("it_fake_breakout@15m", "50002")],
          str(prem))
    pa = next(r for r in prem if r["key"] == "intra_ha_reversal@15m")
    pbx = next(r for r in prem if r["key"] == "it_fake_breakout@15m")
    lots_pa, lots_pb = int(25_000 // (151.0 * LOT)), int(25_000 // (90.5 * LOT))
    check("premium50k: each position up to Rs 25,000 of premium (Rs 50,000 over two slots), at the ask, paid in full",
          pa["qty"] == lots_pa and pbx["qty"] == lots_pb and pa["entry_px"] == 151.0
          and pa["capital_deployed"] <= 25_000 and pbx["capital_deployed"] <= 25_000
          and abs(pa["capital_deployed"] - 151.0 * LOT * lots_pa) < 0.01, f"{pa['qty']}/{lots_pa} {pbx['qty']}/{lots_pb}")
    psc = {s["key"]: s["skipped"] async for s in pb.SCORES.find({"book": "premium50k"})}
    check("premium50k: its own skip counts (shared contract, then full)",
          psc.get("it_fake_breakout@15m", {}).get("symbol_held") == 1 and psc.get("intra_ha_reversal@15m", {}).get("full") == 1,
          str(psc))
    rows = [r async for r in pb.POSITIONS.find({"book": "best2L"})]
    keys = sorted((r["key"], r["symbol"]) for r in rows)
    check("best2L: two positions, one per slot, the second contract taken and the shared one skipped",
          keys == [("intra_ha_reversal@15m", "50001"), ("it_fake_breakout@15m", "50002")], str(keys))
    a = next(r for r in rows if r["key"] == "intra_ha_reversal@15m")
    lots_a = int(100_000 // (151.0 * LOT))
    check("best2L: a position is up to Rs 1 lakh (Rs 2 lakh over two slots), bought at the ask",
          a["qty"] == lots_a and a["entry_px"] == 151.0 and a["account"] == "book" and a["allocation"] is None,
          f"{a['qty']} vs {lots_a}")
    check("best2L: marked at the tournament's mark", abs(a["unrealized_pnl"] - (160.0 - 151.0) * LOT * lots_a) < 0.01)
    sc = {s["key"]: s["skipped"] async for s in pb.SCORES.find({"book": "best2L"})}
    check("best2L: the shared contract counted as symbol_held, the third position as full",
          sc.get("it_fake_breakout@15m", {}).get("symbol_held") == 1 and sc.get("intra_ha_reversal@15m", {}).get("full") == 1,
          str(sc))
    # The daemon closes intra_ha_reversal's first trade: the open row leaves prelive_positions and a closed row lands
    # in prelive_trades with the same key and entry time (a Mongo date, milliseconds) and the bid it sold at.
    await P.delete_one({"key": "intra_ha_reversal@15m", "security_id": "50001"})
    t_x = NOW - timedelta(minutes=10)
    await T.insert_one({"key": "intra_ha_reversal@15m", "entry_ts": t_a, "entry_premium": 150.0, "entry_ask": 151.0,
                        "exit_premium": 171.0, "exit_bid": 170.5, "exit_ts": t_x, "security_id": "50001",
                        "strike": 25300, "option_type": "PE", "expiry": "2026-11-17", "lot_size": LOT,
                        "session": day(t_a), "exit_reason": "target"})
    await pb.sync(entries=True, only="best2L")
    a2 = await pb.POSITIONS.find_one({"book": "best2L", "key": "intra_ha_reversal@15m", "symbol": "50001"})
    g, n, _ = option_net(151.0, 170.5, lots_a, day(t_x))
    check("best2L: the copy closes at the tournament's exit bid", a2["status"] == "CLOSED"
          and abs(a2["realized_pnl"] - n) < 0.01, f"{a2.get('realized_pnl')} vs {n}")
    await pb.sync(entries=True, only="premium50k")
    pa2 = await pb.POSITIONS.find_one({"book": "premium50k", "key": "intra_ha_reversal@15m", "symbol": "50001"})
    pg, pn, _ = option_net(151.0, 170.5, lots_pa, day(t_x))
    check("premium50k: closes at the same exit bid, charged on its own lots", pa2["status"] == "CLOSED"
          and abs(pa2["realized_pnl"] - pn) < 0.01 and abs(pa2["gross_pnl"] - pg) < 0.01, f"{pa2.get('realized_pnl')} vs {pn}")
    ps = await pb.summary("premium50k")
    check("premium50k summary: Rs 50,000, two slots, cap Rs 25,000, one account, the two picks, its own label",
          ps["desk_capital"] == 50_000 and ps["max_open_positions"] == 2 and ps["position_cap"] == 25_000
          and ps["per_strategy"] is False and ps["strategies"] == 2
          and ps["label"] == "Premium Option Buying Strategies · ₹50k", str({k: ps.get(k) for k in ("desk_capital", "position_cap", "label")}))
    plb = await pb.leaderboard("premium50k")
    check("premium50k leaderboard: the two, with their share of Rs 50,000",
          [r["key"] for r in plb] == ["intra_ha_reversal@15m", "it_fake_breakout@15m"]
          and abs(plb[0]["roi_pct"] - (plb[0]["net_pnl"] + plb[0]["unrealized_pnl"]) / 50_000 * 100) < 1e-3)
    s = await pb.summary("best2L")
    check("best2L summary: Rs 2 lakh, two slots, cap Rs 1 lakh, one account",
          s["desk_capital"] == 200_000 and s["max_open_positions"] == 2 and s["position_cap"] == 100_000
          and s["per_strategy"] is False and s["per_strategy_capital"] is None and s["strategies"] == 2)
    lb = await pb.leaderboard("best2L")
    check("best2L leaderboard: the two, with their share of the book", [r["key"] for r in lb]
          == ["intra_ha_reversal@15m", "it_fake_breakout@15m"] and lb[0]["allocation"] is None
          and abs(lb[0]["roi_pct"] - (lb[0]["net_pnl"] + lb[0]["unrealized_pnl"]) / 200_000 * 100) < 1e-3)


BN_LOT = 30
BN_QUOTES: dict[str, dict] = {}
BN_CALLS: list[list[str]] = []


async def fake_bn_quotes(tokens):
    BN_CALLS.append(list(tokens))
    if BN_QUOTES.get("__down__"):
        raise RuntimeError("Angel quote outage")
    return {t: BN_QUOTES[t] for t in tokens if t in BN_QUOTES}


def bnpos(strategy, entry, t_open, *, token="60001", status="OPEN", exit_=None, t_close=None, strike=58000,
          typ="CE", reason="target", straddle=False):
    """A NIFTY BANK desk position, as banknifty_desk.open_position / close_position write it."""
    def leg(t, tok):
        lg = {"type": t, "strike": float(strike), "expiry": "2026-11-24", "token": tok,
              "tradingsymbol": f"BANKNIFTY24NOV26{strike}{t}", "lot_size": BN_LOT, "qty": BN_LOT,
              "entry_ltp": entry - 2.0, "entry_bid": entry - 4.0, "entry_ask": entry, "real_entry": entry,
              "entry_basis": "book"}
        if status == "CLOSED":
            lg.update({"exit_ltp": exit_ + 2.0, "exit_bid": exit_, "exit_ask": exit_ + 4.0, "real_exit": exit_,
                       "exit_basis": "book"})
        return lg
    legs = [leg("CE", token), leg("PE", token + "9")] if straddle else [leg(typ, token)]
    d = {"_id": ObjectId(), "strategy": strategy, "sid": strategy.split("@")[0], "source": "daily", "tier": "C",
         "kind": "STRADDLE" if straddle else typ, "status": status, "session": day(t_open), "opened_at": t_open,
         "spot_entry": 58010.0, "legs": legs, "decision": {}, "expiry": "2026-11-24"}
    if status == "CLOSED":
        d.update({"closed_at": t_close, "exit_reason": reason, "real_pnl": (exit_ - entry) * BN_LOT,
                  "paper_pnl": (exit_ - entry) * BN_LOT})
    return d


def bn_net(entry, exit_, lots, on):
    gross = (exit_ - entry) * BN_LOT * lots
    fb = option_round_trip(entry, max(exit_, 0.0), lots, BN_LOT, on=datetime.fromisoformat(on).date())
    return round(gross, 2), round(gross - fb.total, 2), fb.total


async def banknifty_books():
    """bn2L / bn10L (17 Nov 2026): the NIFTY BANK desk's ten strategies, Rs 2 lakh and Rs 10 lakh EACH."""
    D = DB[pb.BN_POSITIONS]
    pb._bn_quotes = fake_bn_quotes
    pb._bn_marks.clear()
    for b in ("bn2L", "bn10L"):
        await pb.STATE.update_one({"_id": f"start:{b}"}, {"$set": {"started_at": START, "book": b}}, upsert=True)
    ten = [p.key for p in pb.BOOKS["bn2L"].picks]
    check("bn2L / bn10L: the desk's ten, in the research's order, frozen with their research record",
          ten == [s for s in ("livermore_pivotal_point@1d", "swing_fractal@1d", "wt_btst@1d", "swing_gap_trend@1d",
                              "bn_d_donchian_10@1d", "bn_d_donchian_20@1d", "swing_3day_momo@1d",
                              "qullamaggie_flag@1d", "swing_cci@1d", "bn_gap_go_80bp_1515@5m")]
          and [p.key for p in pb.BOOKS["bn10L"].picks] == ten
          and [p.rank for p in pb.BOOKS["bn2L"].picks] == list(range(1, 11)), str(ten))
    research = Path(ROOT / "backend" / "app" / "data" / "banknifty_research.json")
    if research.exists():
        import json
        sel = json.loads(research.read_text(encoding="utf-8"))["selected"]
        check("the frozen ten are the research file's ten, with its trades and net",
              [(s["key"], s["rank"], s["research"]["all"]["trades"], round(s["research"]["all"]["net"], 2)) for s in sel]
              == [(p.key, p.rank, p.trades, p.net) for p in pb.BOOKS["bn2L"].picks])

    old = bnpos("livermore_pivotal_point@1d", 1385.5, START - timedelta(hours=1), token="60000")   # before the start
    b1 = bnpos("swing_fractal@1d", 1359.0, NOW - timedelta(hours=2))
    b1b = bnpos("swing_fractal@1d", 1200.0, NOW - timedelta(minutes=60), token="60009")            # while it holds b1
    b2 = bnpos("wt_btst@1d", 1004.8, NOW - timedelta(minutes=100), token="60002", typ="PE", status="CLOSED",
               exit_=721.45, t_close=NOW - timedelta(minutes=30), reason="signal")
    b3 = bnpos("wt_btst@1d", 1484.8, NOW - timedelta(minutes=20), token="60003")                    # after its loss
    same = [bnpos(k, 1385.5, NOW - timedelta(minutes=50), token="60005") for k in
            ("qullamaggie_flag@1d", "bn_d_donchian_20@1d", "bn_d_donchian_10@1d", "swing_gap_trend@1d")]
    strad = bnpos("swing_cci@1d", 900.0, NOW - timedelta(minutes=40), token="60007", straddle=True)
    other = bnpos("bn_d_breakout_5@1d", 900.0, NOW - timedelta(minutes=40), token="60008")          # not one of the ten
    await D.insert_many([old, b1, b1b, b2, b3, *same, strad, other])
    BN_QUOTES.update({"60001": {"ltp": 1402.0, "bid": 1400.0, "ask": 1404.0},
                      "60003": {"ltp": 1490.0, "bid": 1488.0, "ask": 1492.0},
                      "60005": {"ltp": 1391.0, "bid": 1390.0, "ask": 1392.0}})
    BN_CALLS.clear()
    out = {}
    for b in ("bn2L", "bn10L"):
        out.update(await pb.sync(entries=True, only=b))
        out.update(await pb.sync(entries=True, only=b))           # a copy opened in a pass is marked on the next
    check("bn books: every one of the 20 accounts ran without an error",
          len(out) == 20 and not [k for k, v in out.items() if "error" in v], str(out))
    asked = [t for c in BN_CALLS for t in c]
    check("bn books: only the contracts the accounts hold are quoted, each once for all twenty (a 45 s cache)",
          sorted(asked) == ["60001", "60003", "60005"], str(BN_CALLS))
    rows = [r async for r in pb.POSITIONS.find({"book": {"$in": ["bn2L", "bn10L"]}})]
    by = {(r["book"], r["parent_position_id"]): r for r in rows}
    check("bn: nothing the desk opened before the book's start is copied", not [r for r in rows
          if r["parent_position_id"] == str(old["_id"])])
    check("bn: a strategy outside the ten is never copied", not [r for r in rows
          if r["parent_position_id"] == str(other["_id"])])
    check("bn: a straddle (two legs) is not copied - none of the ten trades one", not [r for r in rows
          if r["parent_position_id"] == str(strad["_id"])])
    for book, cap in (("bn2L", 200_000), ("bn10L", 1_000_000)):
        r1 = by.get((book, str(b1["_id"])))
        lots = int(cap // (1359.0 * BN_LOT))
        check(f"{book}: whole lots up to the strategy's own ₹{cap:,}, at the desk's ask", r1 is not None
              and r1["qty"] == lots and r1["entry_px"] == 1359.0 and r1["account"] == "swing_fractal@1d"
              and abs(r1["capital_deployed"] - lots * 1359.0 * BN_LOT) < 0.01 and r1["allocation"] == cap,
              f"{r1 and r1.get('qty')} vs {lots}")
        check(f"{book}: marked at the bid now", r1 is not None
              and abs(r1["unrealized_pnl"] - (1400.0 - 1359.0) * BN_LOT * lots) < 0.01 and r1["ltp"] == 1400.0,
              str(r1 and r1.get("unrealized_pnl")))
        check(f"{book}: the contract, name and expiry", r1 is not None and r1["label"] == "BANKNIFTY 58000 CE 2026-11-24"
              and r1["strategy_name"] == "Swing: Fractal Break" and r1["expiry"] == "2026-11-24" and r1["symbol"] == "60001")
        check(f"{book}: a second signal while the strategy holds a position is skipped",
              (book, str(b1b["_id"])) not in by)
        r2 = by.get((book, str(b2["_id"])))
        l2 = int(cap // (1004.8 * BN_LOT))
        g2, n2, f2 = bn_net(1004.8, 721.45, l2, day(NOW - timedelta(minutes=30)))
        check(f"{book}: opened-and-closed between looks: closed at the desk's bid, Angel's charges on its own lots",
              r2 is not None and r2["status"] == "CLOSED" and r2["qty"] == l2 and abs(r2["gross_pnl"] - g2) < 0.01
              and abs(r2["realized_pnl"] - n2) < 0.01 and abs(r2["fees"] - round(f2, 2)) < 0.01
              and r2["exit_reason"] == "signal" and r2["label"].startswith("BANKNIFTY 58000 PE"),
              f"{r2 and (r2.get('qty'), r2.get('realized_pnl'))} vs {(l2, n2)}")
        r3 = by.get((book, str(b3["_id"])))
        l3 = int((cap + n2) // (1484.8 * BN_LOT))
        check(f"{book}: the next trade is sized on the money left after the loss", r3 is not None and r3["qty"] == l3,
              f"{r3 and r3.get('qty')} vs {l3}")
        accts = sorted(r["account"] for r in rows if r["book"] == book and r["symbol"] == "60005")
        check(f"{book}: four strategies on one contract at once - each in its own account",
              accts == sorted(s["strategy"] for s in same), str(accts))
    sc = await pb.SCORES.find_one({"book": "bn2L", "key": "swing_fractal@1d"})
    check("bn2L: the held-position skip is counted as full", sc is not None and sc["skipped"].get("full") == 1, str(sc))

    # A quote outage: the copy still runs and the open rows keep their last mark.
    pb._bn_marks.clear()
    BN_QUOTES["__down__"] = True
    out = await pb.sync(entries=True, only="bn2L")
    r1 = await pb.POSITIONS.find_one({"book": "bn2L", "parent_position_id": str(b1["_id"])})
    check("bn: an Angel quote outage stops nothing; the open copy keeps its last mark",
          not [k for k, v in out.items() if "error" in v] and r1["ltp"] == 1400.0, str(out))
    BN_QUOTES.pop("__down__")
    pb._bn_marks.clear()

    # The desk closes swing_fractal's position at the bid 1,523.4: both copies close there.
    await D.update_one({"_id": b1["_id"]}, {"$set": {
        "status": "CLOSED", "closed_at": NOW - timedelta(minutes=5), "exit_reason": "target",
        "legs": [{**b1["legs"][0], "real_exit": 1523.4, "exit_bid": 1523.4, "exit_ltp": 1525.0}]}})
    for b in ("bn2L", "bn10L"):
        await pb.sync(entries=True, only=b)
    for book, cap in (("bn2L", 200_000), ("bn10L", 1_000_000)):
        r = await pb.POSITIONS.find_one({"book": book, "parent_position_id": str(b1["_id"])})
        lots = int(cap // (1359.0 * BN_LOT))
        g, n, _ = bn_net(1359.0, 1523.4, lots, day(NOW - timedelta(minutes=5)))
        check(f"{book}: when the desk closes, the copy closes at the desk's bid", r["status"] == "CLOSED"
              and abs(r["realized_pnl"] - n) < 0.01 and r["exit_px"] == 1523.4 and r["exit_reason"] == "target",
              f"{r.get('realized_pnl')} vs {n}")
    n_before = await pb.POSITIONS.count_documents({"book": {"$in": ["bn2L", "bn10L"]}})
    for b in ("bn2L", "bn10L"):
        await pb.sync(entries=True, only=b)
    check("bn: passes are idempotent", await pb.POSITIONS.count_documents({"book": {"$in": ["bn2L", "bn10L"]}}) == n_before)

    got = await pb._load_banknifty(NOW + timedelta(days=1), {"wt_btst@1d"}, [str(b3["_id"]), "not-an-id"])
    check("bn loader: an open copy's parent is found by its id however old it is",
          [p["position_id"] for p in got] == [str(b3["_id"])])

    for book, cap in (("bn2L", 200_000), ("bn10L", 1_000_000)):
        s = await pb.summary(book)
        check(f"{book} summary: ₹{cap:,} each, ten accounts, one position each, its own date, desk and caveat",
              s["desk_capital"] == cap * 10 and s["per_strategy_capital"] == cap and s["position_cap"] == cap
              and s["max_open_positions"] == 10 and s["strategies"] == 10 and s["board_ranks"] == list(range(1, 11))
              and s["per_strategy"] is True and s["picked_at"] == pb.BN_PICKED_AT
              and s["source_label"] == "the NIFTY BANK desk" and s["route"] == "/prelive?index=banknifty"
              and s["caveat_title"] == "Chosen by research, and none is proven." and s["skipped"]["full"] == 1,
              str({k: s.get(k) for k in ("desk_capital", "per_strategy_capital", "picked_at", "skipped")}))
        mine = [r async for r in pb.POSITIONS.find({"book": book})]
        check(f"{book} summary adds up its accounts", abs(s["realized_pnl"] - sum(
            r["realized_pnl"] for r in mine if r["status"] == "CLOSED")) < 0.05 and s["open_positions"] == len(
            [r for r in mine if r["status"] == "OPEN"]))
        lb = await pb.leaderboard(book)
        wt = next(r for r in lb if r["key"] == "wt_btst@1d")
        check(f"{book} leaderboard: ten rows in research order, each on its own ₹{cap:,}",
              [r["picked_rank"] for r in lb] == list(range(1, 11)) and all(r["allocation"] == cap for r in lb)
              and abs(wt["equity"] - (cap + wt["net_pnl"] + wt["unrealized_pnl"])) < 0.01 and wt["trades"] == 1)
    s0 = await pb.summary("best2L")
    check("the NIFTY 50 books keep their own date, wording and caveat", s0["picked_at"] == pb.PICKED_AT
          and s0["source_label"] == "the tab" and s0["caveat_title"].startswith("Picked on a short"))


def routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import prelive_pick_books as r
    app = FastAPI()
    app.include_router(r.router)
    check("the router hands its startup loop to the app", r._start_loop in app.router.on_startup)
    paths = {getattr(x, "path", "") for x in r.router.routes}
    check("four read-only routes, no write route", paths == {
        "/api/prelive-pick-books/books", "/api/prelive-pick-books/summary",
        "/api/prelive-pick-books/leaderboard", "/api/prelive-pick-books/positions"}
        and all(x.methods == {"GET"} for x in r.router.routes), str(paths))
    c = TestClient(app)                                    # no `with`: the startup loop is not started
    s = c.get("/api/prelive-pick-books/summary", params={"book": "sf_top10"})
    lb = c.get("/api/prelive-pick-books/leaderboard", params={"book": "sf_top10_20"})
    pos = c.get("/api/prelive-pick-books/positions", params={"book": "sf_top10", "status": "CLOSED"})
    check("GET summary / leaderboard / positions answer over HTTP", s.status_code == 200 and lb.status_code == 200
          and pos.status_code == 200 and s.json()["label"] == "Top 10 Performing Strategies · ₹10 lakh each"
          and lb.json()["total"] == 10 and len(pos.json()["positions"]) >= 2,
          f"{s.status_code} {lb.status_code} {pos.status_code}")
    bn = c.get("/api/prelive-pick-books/summary", params={"book": "bn10L"})
    check("GET summary of a NIFTY BANK book over HTTP", bn.status_code == 200
          and bn.json()["label"] == "NIFTY BANK Strategies · ₹10 lakh each" and bn.json()["desk_capital"] == 10_000_000)
    books = pb.books()
    check("books(): six, with the owner's names", [b["label"] for b in books] == [
        "Best Strategies of Top 10 · ₹2 lakh", "Premium Option Buying Strategies · ₹50k",
        "Top 10 Performing Strategies · ₹10 lakh each", "Top 10-20 Performing Strategies · ₹10 lakh each",
        "NIFTY BANK Strategies · ₹2 lakh each", "NIFTY BANK Strategies · ₹10 lakh each"]
        and [b["capital"] for b in books] == [200_000, 50_000, 10_000_000, 10_000_000, 2_000_000, 10_000_000]
        and books[4]["picked_at"] == pb.BN_PICKED_AT and books[0]["picked_at"] == pb.PICKED_AT,
        str([b["capital"] for b in books]))
    check("unknown book names fall back to the first", pb.normalize_book("nope") == "best2L")


async def main():
    await factory_books()
    await best_book()
    await banknifty_books()
    routes()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
