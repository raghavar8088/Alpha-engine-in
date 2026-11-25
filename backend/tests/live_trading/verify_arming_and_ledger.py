"""The real-money desk: can it be armed, and does its ledger match the broker?

Run:  python backend/tests/live_trading/verify_arming_and_ledger.py

No Mongo, no Angel, no network. Every collection is an in-memory fake and Angel is a fake
that RECORDS every order it is asked to place — because the most important property tested
here is a negative one: in the situations below, NO real order may be sent.

WHY THIS EXISTS (measured 2026-10-10, see INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md)
- 78 real orders went out 10-20 Aug 2026 on strategies with no forward validation, because
  arming was a bare flag. -> C4: arming needs a CONFIRMED verdict for every enabled strategy.
- The ledger recorded no charges on any real trade. -> C3: every close is charged.
- 49 positions Angel squared off on its own were booked a day later at the next session's
  price. -> C3: Angel's position book is read BEFORE any exit decision, and a position the
  broker already closed is closed at the broker's fill, with no order sent.
- 10 Nov 2026: the desk now COPIES one tournament strategy (Selected ORB 15-min) whose gate the
  owner overrode. The gate's machinery is still checked, on eight stand-in strategies without an
  override; the copy desk has its own sections at the end.
- 16 Nov 2026: four more strategies (Gap and Go, RSI(2) Extreme 15 min, Supertrend Flip 45 min and
  1 hour) were added, switched OFF until the owner turns each on. All share one pool of five
  positions, one per stock, and each exits at its paper target too.
- 25 Nov 2026: the desk copies six Premium Strategies equity-intraday books instead (YT-23, SS-03,
  VWAP-U4, TW-01, DH-05, UP-03) from the paper desk's premium_trades, a fake here; the five tournament
  strategies are gone. The copy sections at the end are rewritten for that source.
"""

import asyncio
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
for p in ("broker-clients", "shared", "backtesting-service"):
    sys.path.insert(0, str(ROOT / p))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()


def _stub_missing(*names: str) -> None:
    for name in names:
        if name in sys.modules:
            continue
        try:
            __import__(name)
        except ImportError:
            root = name.split(".")[0]
            mod = sys.modules.get(root) or types.ModuleType(root)
            sys.modules[root] = mod
            cur = mod
            for part in name.split(".")[1:]:
                sub = types.ModuleType(f"{cur.__name__}.{part}")
                setattr(cur, part, sub)
                sys.modules[sub.__name__] = sub
                cur = sub


_stub_missing("redis", "redis.asyncio")

import app.services.intraday_v2_registry as REG  # noqa: E402
import app.services.live_trading_engine as LT  # noqa: E402
from app.services.angel_fees import round_trip  # noqa: E402

FAILURES: list[str] = []
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date().isoformat()
YESTERDAY = (datetime.now(IST).date() - timedelta(days=1)).isoformat()


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


# ── fakes ────────────────────────────────────────────────────────────────────────


def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(doc, query):
    for key, want in query.items():
        if key == "$or":
            if not any(_matches(doc, q) for q in want):
                return False
            continue
        got = _get(doc, key)
        if isinstance(want, dict):
            for op, val in want.items():
                if op == "$lt" and not (got is not None and got < val):
                    return False
                if op == "$gte" and not (got is not None and got >= val):
                    return False
                if op == "$gt" and not (got is not None and got > val):
                    return False
                if op == "$lte" and not (got is not None and got <= val):
                    return False
                if op == "$ne" and got == val:
                    return False
                if op == "$in" and got not in val:
                    return False
                if op == "$nin" and got in val:
                    return False
        elif got != want:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class FakeCollection:
    _seq = 0

    def __init__(self, docs=None):
        self.docs = [self._with_id(d) for d in (docs or [])]

    @classmethod
    def _with_id(cls, d):
        d = dict(d)
        if "_id" not in d:
            cls._seq += 1
            d["_id"] = f"oid{cls._seq}"
        return d

    async def find_one(self, query, projection=None, sort=None):
        hits = [d for d in self.docs if _matches(d, query)]
        return dict(hits[0]) if hits else None

    def find(self, query=None, projection=None):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query or {})])

    async def insert_one(self, doc):
        self.docs.append(self._with_id(doc))

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                d.update(update.get("$set", {}))
                return types.SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            doc = self._with_id({**{k: v for k, v in query.items() if not isinstance(v, dict)},
                                 **update.get("$setOnInsert", {}), **update.get("$set", {})})
            self.docs.append(doc)
            return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])
        return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    async def update_many(self, query, update):
        n = 0
        for d in self.docs:
            if _matches(d, query):
                d.update(update.get("$set", {}))
                n += 1
        return types.SimpleNamespace(modified_count=n)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))


class FakeAngel:
    """Records every order. Any test that expects silence asserts `orders == []`."""

    def __init__(self, book=None, trades=None, order_book=None, fail_book=False):
        self.book = book if book is not None else []
        self.trades = trades or []
        self._orders = order_book or []
        self.fail_book = fail_book
        self.orders: list[dict] = []
        self.book_reads = 0

    def configured(self):
        return True

    async def funds(self):
        return {"availablecash": "50000", "net": "50000"}

    async def broker_positions(self):
        self.book_reads += 1
        if self.fail_book:
            raise RuntimeError("Angel 502")
        return self.book

    async def trade_book(self):
        return self.trades

    async def order_book(self):
        if self._orders == "fail":
            raise RuntimeError("Angel 502 on the order book")
        return self._orders

    async def place_order(self, **kw):
        self.orders.append(kw)
        return {"data": {"orderid": f"EXIT{len(self.orders)}"}}

    async def profile(self):
        return {}


class FakeSession:
    def __init__(self, cas=(), due=False):
        self._cas = set(cas)
        self._due = due

    async def ensure_cas(self):
        return None

    def is_cas(self, symbol):
        return symbol in self._cas

    def squareoff_due(self, symbol, now=None):
        return self._due


# The Premium paper desk's database (the box's own MongoDB): its trades and its meta documents.
PAPER = types.SimpleNamespace(premium_trades=FakeCollection(), premium_meta=FakeCollection())
LT._paper_db = lambda: PAPER


def fresh(angel=None, positions=None, registry=None, flags=None, session=None, gate=True):
    """A clean desk: new collections, a new Angel, a new session, the throttle reset."""
    PAPER.premium_trades = FakeCollection()
    PAPER.premium_meta = FakeCollection()
    LT._priority_at = None
    LT.live_trading_positions_collection = FakeCollection(positions)
    LT.live_trading_trades_collection = FakeCollection()
    LT.live_trading_state_collection = FakeCollection([{"_id": LT.STATE_ID, "armed": False}])
    LT.live_trading_flags_collection = FakeCollection(flags)
    LT.live_trading_scores_collection = FakeCollection()
    LT.live_trading_equity_collection = FakeCollection()
    REG.registry = FakeCollection(registry)
    LT.angel_client = angel or FakeAngel()
    LT.session = session or FakeSession()
    LT.ARMING_GATE = gate
    LT._broker_checked_at = 0.0
    LT._balance_cache.update({"at": 0.0, "data": None})
    return LT.angel_client


def run(coro):
    return asyncio.run(coro)


# The desk's own strategies trade by the owner's override of the gate (since 25 Nov 2026 the six Premium
# books). The gate's own machinery is checked on eight stand-ins with no override: it must still hold for
# anything added.
REAL_DESK = (LT.SELECTED, LT.SELECTED_BY_ID, dict(LT.OWNER_OVERRIDE))
GATE_SET = [LT.CopyStrategy(f"gate_s{i}", f"Gate stand-in {i}", "momentum") for i in range(8)]


def use_gate_set():
    LT.SELECTED, LT.SELECTED_BY_ID, LT.OWNER_OVERRIDE = GATE_SET, {g.strategy_id: g for g in GATE_SET}, {}


def use_real_desk():
    LT.SELECTED, LT.SELECTED_BY_ID, LT.OWNER_OVERRIDE = REAL_DESK[0], REAL_DESK[1], dict(REAL_DESK[2])


use_gate_set()
IDS = [ls.strategy_id for ls in LT.SELECTED]
ONE = IDS[0]


def pos(**kw):
    base = {"position_id": "p1", "strategy_id": ONE, "strategy_name": "s", "symbol": "INFY",
            "side": "BUY", "qty": 10, "entry_price": 1500.0, "target": 1530.0,
            "stoploss": 1485.0, "status": "OPEN", "opened_on": TODAY,
            "opened_at": datetime.now(timezone.utc), "entry_order_id": "E1",
            "exit_order_id": None, "entry_fill_price": 1500.0, "exit_fill_price": None,
            "capital_deployed": 15000.0, "unrealized_pnl": 0.0,
            "instrument": {"symbol": "INFY", "security_id": "1594",
                           "exchange_segment": "NSE_EQ", "angel_token": "1594",
                           "angel_tradingsymbol": "INFY-EQ"}}
    base.update(kw)
    return base


# ═════════════════════════════════════════════════════════════════════════════════
section("C4 · THE ARMING GATE")

check("the gate's machinery is checked on eight stand-in strategies, none overridden",
      len(IDS) == 8 and LT.OWNER_OVERRIDE == {}, f"{len(IDS)} strategies")

fresh()
chk = run(LT.arming_check())
check("with no verdicts on file, arming is not allowed", chk["allowed"] is False)
check("the refusal names how many enabled strategies lack a verdict",
      any(f"{len(IDS)} of {len(IDS)} enabled" in b for b in chk["blockers"]), chk["blockers"][:1])
check("every strategy row says it was never registered",
      all(r["verdict"] == "NOT_REGISTERED" for r in chk["strategies"]))

try:
    run(LT.set_armed(True))
    check("set_armed(True) is refused", False, "no exception")
except LT.LiveTradingError as exc:
    check("set_armed(True) is refused", True)
    check("the refusal is ONE readable string (the page shows `detail` verbatim)",
          isinstance(exc.detail, str) and exc.detail.startswith("Live Trading cannot be armed"),
          exc.detail[:90] + "…")
st = run(LT.get_state())
check("the desk is still disarmed after a refused arm", st["armed"] is False)
state_doc = LT.live_trading_state_collection.docs[0]
check("the refused attempt is recorded with its reasons",
      bool((state_doc.get("last_arm_refusal") or {}).get("blockers")))

run(LT.set_armed(False, reason="manual disarm"))
check("disarming is never gated", run(LT.get_state())["armed"] is False)

# one CONFIRMED, the rest still enabled
fresh(registry=[{"_id": ONE, "status": "CONFIRMED"}])
check("one confirmed strategy is not enough while unconfirmed ones are enabled",
      run(LT.arming_check())["allowed"] is False)

# disable every unconfirmed strategy -> allowed
flags = [{"strategy_id": sid, "enabled": False} for sid in IDS[1:]]
fresh(registry=[{"_id": ONE, "status": "CONFIRMED"}], flags=flags)
chk = run(LT.arming_check())
check("with only CONFIRMED strategies enabled, arming is allowed", chk["allowed"] is True,
      chk["blockers"])
run(LT.set_armed(True))
check("…and set_armed(True) succeeds", run(LT.get_state())["armed"] is True)

# a FAILED / INCUBATING verdict is not confirmation
for status in ("FAILED", "INCUBATING"):
    fresh(registry=[{"_id": ONE, "status": status}], flags=flags)
    check(f"a {status} verdict does not allow arming", run(LT.arming_check())["allowed"] is False)

# nothing enabled at all
fresh(flags=[{"strategy_id": sid, "enabled": False} for sid in IDS])
chk = run(LT.arming_check())
check("with nothing enabled there is nothing to arm",
      chk["allowed"] is False and any("nothing to trade" in b for b in chk["blockers"]))

# ledger blockers
base_ok = dict(registry=[{"_id": ONE, "status": "CONFIRMED"}], flags=flags)
fresh(**base_ok)
LT.live_trading_state_collection.docs[0]["kill_switch"] = True
check("the kill switch blocks arming", run(LT.arming_check())["allowed"] is False)

fresh(**base_ok, positions=[pos(opened_on=YESTERDAY)])
chk = run(LT.arming_check())
check("an earlier session's position still OPEN blocks arming",
      chk["allowed"] is False and any("earlier session" in b for b in chk["blockers"]))

fresh(**base_ok, positions=[pos(reconcile_status="mismatch")])
check("an open position that disagrees with Angel blocks arming",
      run(LT.arming_check())["allowed"] is False)

fresh(**base_ok, positions=[pos(status="CLOSED", reconcile_status="needs_contract_note")])
chk = run(LT.arming_check())
check("trades awaiting a contract note warn but do not block",
      chk["allowed"] is True and any("contract note" in w for w in chk["warnings"]))

# the environment switch bypasses verdicts, never the ledger
fresh(gate=False)
chk = run(LT.arming_check())
check("with the gate switched off, missing verdicts no longer block",
      chk["allowed"] is True and chk["gate"] == "off")
check("…but the bypass is announced", any("DISABLED" in w for w in chk["warnings"]))
fresh(gate=False, positions=[pos(opened_on=YESTERDAY)])
check("…and ledger blockers still apply with the gate off",
      run(LT.arming_check())["allowed"] is False)

# leaderboard carries the verdict
fresh(registry=[{"_id": ONE, "status": "CONFIRMED"}])
board = run(LT.leaderboard())
row = next(r for r in board if r["strategy_id"] == ONE)
check("the leaderboard shows each strategy's verdict",
      row["verdict"] == "CONFIRMED" and row["validated"] is True)
check("…and unregistered strategies are visibly unvalidated",
      all(not r["validated"] for r in board if r["strategy_id"] != ONE))

# ── re-checked every scan ────────────────────────────────────────────────────────
section("C4 · RE-CHECKED ON EVERY SCAN")

fresh(registry=[{"_id": ONE, "status": "FAILED"}], flags=flags)
LT.live_trading_state_collection.docs[0]["armed"] = True        # armed behind the gate's back
res = run(LT.scan_cycle(None))
st = run(LT.get_state())
check("an armed desk whose only enabled strategy FAILED disarms itself on the next scan",
      st["armed"] is False and "arming gate" in (st["disarmed_reason"] or ""), st["disarmed_reason"])
check("…and opens nothing", res["opened"] == 0)
check("…and places no order", LT.angel_client.orders == [])

# ═════════════════════════════════════════════════════════════════════════════════
section("C3 · CHARGES ON EVERY REAL CLOSE")

m = LT._charge(1500.0, 1530.0, 10, "BUY")
fb = round_trip(entry_price=1500.0, exit_price=1530.0, qty=10, side="BUY", product="INTRADAY")
check("gross is the price move times quantity", m["gross_pnl"] == 300.0, m["gross_pnl"])
check("charges are Angel's rate card", m["fees"] == fb.total and m["fees"] > 0, m["fees"])
check("realised P&L is net of charges", m["realized_pnl"] == round(300.0 - fb.total, 2))
s = LT._charge(1500.0, 1530.0, 10, "SELL")
check("a short that rises loses, before charges", s["gross_pnl"] == -300.0)

angel = fresh(positions=[pos()])
p0 = LT.live_trading_positions_collection.docs[0]
ok = run(LT._close_real(dict(p0), 1530.0, "target"))
p1 = LT.live_trading_positions_collection.docs[0]
check("a desk exit sends exactly one opposite-side order",
      ok and len(angel.orders) == 1 and angel.orders[0]["transactiontype"] == "SELL")
check("the closed position carries its charges", (p1.get("fees") or 0) > 0, p1.get("fees"))
check("…and realised P&L is net", p1["realized_pnl"] == round(p1["gross_pnl"] - p1["fees"], 2))
check("…and the day it closed", p1.get("closed_on") == TODAY)
t1 = LT.live_trading_trades_collection.docs[0]
check("the trade blotter row carries the same charges", t1.get("fees") == p1["fees"])

# reconcile_fills re-prices a closed position from real fills, charged
closed = pos(status="CLOSED", exit_order_id="X9", exit_price=1530.0, realized_pnl=300.0,
             entry_fill_price=None, entry_price=1500.0, signal_price=1500.0)
angel = fresh(positions=[closed], angel=FakeAngel(trades=[
    {"orderid": "E1", "fillprice": "1501.0", "fillsize": "10"},
    {"orderid": "X9", "fillprice": "1528.5", "fillsize": "6"},
    {"orderid": "X9", "fillprice": "1528.0", "fillsize": "4"}]))
LT.live_trading_trades_collection.docs.append({"_id": "t", "entry_order_id": "E1",
                                               "strategy_id": ONE, "realized_pnl": 300.0})
run(LT.reconcile_fills())
p = LT.live_trading_positions_collection.docs[0]
exp_exit = round((1528.5 * 6 + 1528.0 * 4) / 10, 2)
check("the real exit fill replaces the decision price (size-weighted)",
      p["exit_price"] == exp_exit, p["exit_price"])
check("the real entry fill replaces the signal price", p["entry_price"] == 1501.0)
exp = LT._charge(1501.0, exp_exit, 10, "BUY")
check("the reconciled position is charged on its REAL prices",
      p["realized_pnl"] == exp["realized_pnl"], f"{p['realized_pnl']} vs {exp['realized_pnl']}")
check("…and marked reconciled", p.get("reconcile_status") == "reconciled")
check("…and the blotter row follows it",
      LT.live_trading_trades_collection.docs[0]["realized_pnl"] == exp["realized_pnl"])
check("reconciliation never places an order", angel.orders == [])

# ═════════════════════════════════════════════════════════════════════════════════
section("C3 · BROKER FIRST — Angel's book is read before any exit")

book_flat = [{"tradingsymbol": "INFY-EQ", "producttype": "INTRADAY", "netqty": "0",
              "buyavgprice": "1500", "sellavgprice": "1519"}]
sq_fill = [{"tradingsymbol": "INFY-EQ", "producttype": "INTRADAY", "transactiontype": "SELL",
            "orderid": "RMS77", "fillprice": "1520.0", "fillsize": "10"}]

angel = fresh(positions=[pos()], angel=FakeAngel(book=book_flat, trades=sq_fill))
r = run(LT.reconcile_broker_closes(force=True))
p = LT.live_trading_positions_collection.docs[0]
check("a position Angel squared off is closed in the ledger",
      r["closed_by_broker"] == 1 and p["status"] == "CLOSED", r)
check("…at Angel's own closing fill, not a later price", p["exit_price"] == 1520.0)
check("…labelled as the broker's close", p["exit_reason"] == "broker_squared_off")
check("…with the broker's order id", p.get("exit_order_id") == "RMS77")
check("…charged", (p.get("fees") or 0) > 0)
check("…reconciled exactly (quantities agree)", p.get("reconcile_status") == "reconciled")
check("…and NO order was sent", angel.orders == [], angel.orders)

# the same day, the manage cycle now has nothing to exit
angel = fresh(positions=[pos(target=1510.0)], angel=FakeAngel(book=book_flat, trades=sq_fill))
LT._equity_quote_map = lambda dhan, eqs: _async((
    {("NSE_EQ", "1594"): {"last_price": 1525.0}}, {("NSE_EQ", "1594"): "test"}))
LT.instruments_collection = FakeCollection([{"symbol": "INFY", "asset_class": "EQUITY",
                                             "exchange_segment": "NSE_EQ", "security_id": "1594"}])


async def _async_value(v):
    return v


def _async(v):
    return _async_value(v)


run(LT.manage_cycle(None))
check("a manage cycle after a broker square-off sends NO exit order — even with the target hit",
      angel.orders == [], angel.orders)

# agreement: nothing happens
angel = fresh(positions=[pos()], angel=FakeAngel(book=[{**book_flat[0], "netqty": "10"}]))
r = run(LT.reconcile_broker_closes(force=True))
check("when Angel and the ledger agree, nothing is touched",
      LT.live_trading_positions_collection.docs[0]["status"] == "OPEN"
      and not r.get("closed_by_broker") and not r.get("mismatch"))

# partial disagreement -> mismatch, and no exit sent for it
angel = fresh(positions=[pos(target=1510.0)],
              angel=FakeAngel(book=[{**book_flat[0], "netqty": "4"}]))
run(LT.reconcile_broker_closes(force=True))
p = LT.live_trading_positions_collection.docs[0]
check("a broker quantity matching neither the ledger nor flat is marked, not guessed",
      p["status"] == "OPEN" and p.get("reconcile_status") == "mismatch", p.get("reconcile_note"))
LT._broker_checked_at = 0.0
run(LT.manage_cycle(None))
check("…and a mismatched position is never sent an automatic exit", angel.orders == [],
      angel.orders)

# both sides in one symbol, broker flat -> mismatch (could be internal netting)
angel = fresh(positions=[pos(position_id="a", qty=5), pos(position_id="b", side="SELL", qty=3,
                                                          strategy_id=IDS[1])],
              angel=FakeAngel(book=book_flat, trades=sq_fill))
r = run(LT.reconcile_broker_closes(force=True))
check("positions on both sides of a symbol are never inferred closed",
      r.get("closed_by_broker", 0) == 0 and r.get("mismatch") == 2, r)

# entry rejected after acceptance -> VOID, not a trade
angel = fresh(positions=[pos()], angel=FakeAngel(
    book=[{"tradingsymbol": "TCS-EQ", "producttype": "INTRADAY", "netqty": "0"}],
    order_book=[{"orderid": "E1", "status": "rejected", "text": "insufficient funds"}]))
r = run(LT.reconcile_broker_closes(force=True))
p = LT.live_trading_positions_collection.docs[0]
check("an entry Angel rejected becomes VOID — it never existed", p["status"] == "VOID", r)
check("…with the broker's reason", "insufficient funds" in (p.get("reconcile_note") or ""))
run(LT._update_score(ONE))
sc = LT.live_trading_scores_collection.docs[0]
check("…and a VOID row is not counted as a trade", sc["trades"] == 0, sc)

# empty book / unreadable book -> nothing inferred
angel = fresh(positions=[pos()], angel=FakeAngel(book=[]))
run(LT.reconcile_broker_closes(force=True))
check("an empty position book is not evidence that anything closed",
      LT.live_trading_positions_collection.docs[0]["status"] == "OPEN")
angel = fresh(positions=[pos()], angel=FakeAngel(fail_book=True))
r = run(LT.reconcile_broker_closes(force=True))
check("an unreadable position book changes nothing and says why",
      LT.live_trading_positions_collection.docs[0]["status"] == "OPEN" and "error" in r)

# broker flat, closing fills do not add up -> closed, but flagged for the contract note
angel = fresh(positions=[pos()], angel=FakeAngel(
    book=book_flat, trades=[{**sq_fill[0], "fillsize": "7"}]))
run(LT.reconcile_broker_closes(force=True))
p = LT.live_trading_positions_collection.docs[0]
check("a flat broker with an odd closing quantity still closes the ledger…", p["status"] == "CLOSED")
check("…but flags it for the contract note", p.get("reconcile_status") == "needs_contract_note")

# throttle
angel = fresh(positions=[pos()], angel=FakeAngel(book=[{**book_flat[0], "netqty": "10"}]))
run(LT.reconcile_broker_closes())
r2 = run(LT.reconcile_broker_closes())
check("the position book is read at most once per throttle window",
      angel.book_reads == 1 and r2.get("throttled"), angel.book_reads)

# nothing open -> no API call at all
angel = fresh(positions=[pos(status="CLOSED")], angel=FakeAngel())
run(LT.reconcile_broker_closes(force=True))
check("with nothing open today, Angel is not asked at all", angel.book_reads == 0)

# ═════════════════════════════════════════════════════════════════════════════════
section("C3 · NO EXIT ORDERS INTO THE BROKER'S OWN SQUARE-OFF")

LT.BROKER_SQUAREOFF_HHMM, LT.BROKER_SQUAREOFF_CAS_HHMM = "15:15", "15:10"
LT.session = FakeSession(cas={"SBIN"})
at = lambda hh, mm: datetime(2026, 10, 12, hh, mm, tzinfo=IST)  # noqa: E731
check("15:14 non-CAS: the desk may still exit", not LT._broker_squaring_off("INFY", at(15, 14)))
check("15:15 non-CAS: the broker's window — the desk stops", LT._broker_squaring_off("INFY", at(15, 15)))
check("15:09 CAS: the desk may still exit", not LT._broker_squaring_off("SBIN", at(15, 9)))
check("15:10 CAS: the broker's window — the desk stops", LT._broker_squaring_off("SBIN", at(15, 10)))

angel = fresh(positions=[pos(target=1510.0)], angel=FakeAngel(book=[{**book_flat[0], "netqty": "10"}]),
              session=FakeSession(due=True))
real = LT._broker_squaring_off
LT._broker_squaring_off = lambda sym, now: True
run(LT.manage_cycle(None))
LT._broker_squaring_off = real
check("inside the broker's window, a hit target sends NO order",
      angel.orders == [] and LT.live_trading_positions_collection.docs[0]["status"] == "OPEN")

# ═════════════════════════════════════════════════════════════════════════════════
section("C3 · A POSITION FOUND NEXT DAY IS PRICED AT ITS OWN DAY'S CLOSE")


class _Bar:
    def __init__(self, day, close):
        self.ts = datetime.fromisoformat(day).replace(tzinfo=IST).astimezone(timezone.utc)
        self.close = close


LT.load_bars = lambda symbol, tf, years=None: [_Bar(YESTERDAY, 1512.0), _Bar(TODAY, 1490.0)]
angel = fresh(positions=[pos(opened_on=YESTERDAY)], angel=FakeAngel(book=[]))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("a stale MIS position is closed WITHOUT an order", angel.orders == [] and p["status"] == "CLOSED")
check("…at ITS OWN session's close, not today's price", p["exit_price"] == 1512.0, p["exit_price"])
check("…charged", (p.get("fees") or 0) > 0)
check("…dated the day it actually closed", p.get("closed_on") == YESTERDAY)
check("…and flagged as an estimate until the contract note", p.get("reconcile_status") == "needs_contract_note")
check("…with the basis written down", "NSE close" in (p.get("exit_basis") or ""), p.get("exit_basis"))

LT.load_bars = lambda symbol, tf, years=None: []
angel = fresh(positions=[pos(opened_on=YESTERDAY)], angel=FakeAngel(book=[]))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("with no bar for that day, it falls back to the quote — and says so",
      p["exit_price"] == 1525.0 and "next-session LTP" in (p.get("exit_basis") or ""))

# ═════════════════════════════════════════════════════════════════════════════════
section("LEDGER HEALTH")
fresh(positions=[pos(status="CLOSED", reconcile_status="reconciled", fees=5.0),
                 pos(status="CLOSED", reconcile_status="needs_contract_note", fees=5.0),
                 pos(status="CLOSED", fees=None),
                 pos(status="VOID", reconcile_status="void")])
h = run(LT.ledger_health())
check("the summary reports how much of the record is the broker's truth",
      h["reconciled"] == 1 and h["needs_contract_note"] == 1 and h["void"] == 1, h)
check("…and how many closed trades still have no charges", h["charges_missing"] == 1)

# ═════════════════════════════════════════════════════════════════════════════════
section("THE OWNER'S DECISION (25 Nov 2026): SIX PREMIUM BOOKS")

use_real_desk()
SIXIDS = ["YT-23", "SS-03", "VWAP-U4", "TW-01", "DH-05", "UP-03"]
MKT = {"YT-23": "NSE15", "SS-03": "NSE5", "VWAP-U4": "VWAP", "TW-01": "NSE15", "DH-05": "NSE5", "UP-03": "NSE15"}
SEL = "YT-23"
check("the desk lists the six Premium books, in the order of the owner's screenshot",
      [ls.strategy_id for ls in LT.SELECTED] == SIXIDS, [ls.strategy_id for ls in LT.SELECTED])
check("…each with its paper book's market", {ls.strategy_id: ls.mkt for ls in LT.SELECTED} == MKT,
      {ls.strategy_id: ls.mkt for ls in LT.SELECTED})
check("none of the five tournament strategies is left on the desk",
      not any(s.startswith("iv2_") for s in LT.SELECTED_BY_ID) and LT.COPY_SOURCE == SEL, list(LT.SELECTED_BY_ID))
check("each override is written down, dated 25 Nov 2026, and only for the six",
      set(LT.OWNER_OVERRIDE) == set(SIXIDS) and all("25 Nov 2026" in LT.OWNER_OVERRIDE[s] for s in SIXIDS),
      LT.OWNER_OVERRIDE)
check("the tournament's positions are no longer read at all", not hasattr(LT, "intraday_lab_positions_collection"))
fresh()
check("with no saved switch all six are on, and the desk itself stays disarmed",
      run(LT._enabled_map()) == {s: True for s in SIXIDS} and run(LT.get_state())["armed"] is False,
      run(LT._enabled_map()))
check("size unchanged: up to five at once, about Rs 30,000 each on 5x (Rs 1.5 lakh across the desk)",
      LT.MAX_OPEN_POSITIONS == 5 and LT.COPY_NOTIONAL == 30000.0 and LT.MIS_LEVERAGE == 5.0
      and LT.DESK_CEILING == 150000.0 and LT.PER_STRATEGY_ALLOCATION == 150000.0)
check("the copy window fits the paper desk's delay: 20 minutes", LT.COPY_WINDOW_S == 1200.0, LT.COPY_WINDOW_S)

fresh()
chk = run(LT.arming_check())
check("with no verdict on file, the six may be armed by the override", chk["allowed"] is True, chk["blockers"])
check("…the override is announced for each of them",
      sum("OVERRIDDEN" in w for w in chk["warnings"]) == 6, chk["warnings"])
check("…every row keeps its real verdict and says why it may trade",
      all(r["verdict"] == "NOT_REGISTERED" and r["validated"] is True and "overridden" in r["reason"]
          for r in chk["strategies"]), chk["strategies"][:1])
check("…and the overridden count is reported apart", chk.get("overridden_enabled") == 6, chk.get("overridden_enabled"))
run(LT.set_armed(True))
check("set_armed(True) succeeds", run(LT.get_state())["armed"] is True)

fresh(positions=[pos(opened_on=YESTERDAY, strategy_id=SEL)])
check("the override never bypasses the ledger: a stale OPEN position still blocks arming",
      run(LT.arming_check())["allowed"] is False)
fresh(flags=[{"strategy_id": s, "enabled": False} for s in SIXIDS])
check("all six switched off: there is nothing to arm", run(LT.arming_check())["allowed"] is False)
fresh()
board = run(LT.leaderboard())
check("the leaderboard shows the override beside the verdict, for all six",
      len(board) == 6 and all(b["validated"] is True and b["override"] and b["verdict"] == "NOT_REGISTERED" for b in board))

# ═════════════════════════════════════════════════════════════════════════════════
section("COPYING THE PAPER DESK — copy_check")

NOW = datetime.now(timezone.utc)


def parent(**kw):
    """A paper trade as _paper_parent gives it to the copy code."""
    base = {"position_id": "YT-23|NSE15|INFY|1|1", "strategy_id": SEL, "book": "YT-23|NSE15", "symbol": "INFY",
            "side": "BUY", "entry_price": 1500.0, "stoploss": 1485.0, "target": None, "status": "OPEN",
            "opened_on": TODAY, "opened_at": NOW - timedelta(seconds=420)}
    base.update(kw)
    return base


cc = LT.copy_check
check("a paper entry 7 minutes old, near its fill, is copied (the paper desk's normal delay)",
      cc(parent(), 1501.0, 0, NOW) == (None, True))
w, f = cc(parent(opened_at=NOW - timedelta(seconds=1300)), 1501.0, 0, NOW)
check("a paper entry older than 20 minutes is final", f is True and "minutes old" in (w or ""), w)
check("a naive (Mongo) timestamp is read as UTC",
      cc(parent(opened_at=(NOW - timedelta(seconds=420)).replace(tzinfo=None)), 1501.0, 0, NOW) == (None, True))
check("four real positions open: a fifth is copied", cc(parent(), 1501.0, 4, NOW) == (None, True))
w, f = cc(parent(), 1501.0, 5, NOW)
check("five real positions open: wait (not final)", w and "the most at once is 5" in w and f is False, w)
w, f = cc(parent(), None, 0, NOW)
check("no live quote: wait (not final)", w == "no live quote" and f is False)
w, f = cc(parent(), 1484.0, 0, NOW)
check("a BUY with the price already under its stop: final", w and "beyond the stop" in w and f is True)
w, f = cc(parent(), 1509.0, 0, NOW)
check("a BUY that ran more than half the stop distance: wait (not final)", w and "moved" in w and f is False, w)
check("a BUY within half the stop distance is copied", cc(parent(), 1507.0, 0, NOW) == (None, True))
check("a SELL above its stop: final", cc(parent(side="SELL", stoploss=1515.0), 1516.0, 0, NOW)[1] is True
      and cc(parent(side="SELL", stoploss=1515.0), 1516.0, 0, NOW)[0])
check("a SELL that fell more than half the stop distance waits",
      cc(parent(side="SELL", stoploss=1515.0), 1492.0, 0, NOW)[1] is False)
check("a SELL near its fill is copied", cc(parent(side="SELL", stoploss=1515.0), 1499.0, 0, NOW) == (None, True))
check("no usable stop: final", cc(parent(stoploss=None), 1501.0, 0, NOW)[1] is True)
check("no side (a paper side of 0): final", cc(parent(side=None), 1501.0, 0, NOW)[1] is True)
w, f = cc(parent(target=1505.0), 1506.0, 0, NOW)
check("a BUY already at its paper target is final (no round trip for nothing)", w and "target" in w and f is True, (w, f))
w, f = cc(parent(side="SELL", stoploss=1515.0, target=1495.0), 1494.0, 0, NOW)
check("a SELL already at its paper target is final", w and "target" in w and f is True, (w, f))
check("short of the target it is copied", cc(parent(target=1530.0), 1502.0, 0, NOW) == (None, True))

# ═════════════════════════════════════════════════════════════════════════════════
section("COPYING THE PAPER DESK — reading premium_trades")


def ptrade(sym="INFY", acct=SEL, side=1, entry=1500.0, stop=1485.0, target=None, age=420, open_=True, qty=60,
           day=None, mkt=None, **kw):
    """One premium_trades document, as the paper desk writes it (runner.docs_from / vwap_run, sized by the ledger)."""
    mkt = mkt or MKT.get(acct, "NSE15")
    et = int((NOW - timedelta(seconds=age)).timestamp())
    d = {"_id": f"{acct}|{mkt}|{sym}|{et}|{side}", "acct": acct, "book": f"{acct}|{mkt}", "mkt": mkt, "sym": sym,
         "side": side, "date": day or TODAY, "entry_t": et, "entry": entry, "stop": stop, "target": target,
         "open": open_, "reason": "open" if open_ else "stop", "qty": qty, "setup": "TEST", "exit": None}
    d.update(kw)
    return d


t = ptrade(target=1530.0)
p = LT._paper_parent(t)
check("a paper trade becomes a parent the copy code reads",
      p["position_id"] == t["_id"] and p["strategy_id"] == SEL and p["symbol"] == "INFY" and p["side"] == "BUY"
      and p["entry_price"] == 1500.0 and p["stoploss"] == 1485.0 and p["target"] == 1530.0 and p["status"] == "OPEN"
      and p["book"] == "YT-23|NSE15" and p["opened_at"] == datetime.fromtimestamp(t["entry_t"], timezone.utc), p)
check("…a short (-1) is a SELL", LT._paper_parent(ptrade(side=-1))["side"] == "SELL")
check("…a closed one says so, with the paper's reason",
      LT._paper_parent(ptrade(open_=False))["status"] == "CLOSED" and LT._paper_parent(ptrade(open_=False))["exit_reason"] == "stop")

INST = {"symbol": "INFY", "asset_class": "EQUITY", "exchange_segment": "NSE_EQ", "security_id": "1594",
        "angel_token": "1594", "angel_tradingsymbol": "INFY-EQ"}


class CashAngel(FakeAngel):
    def __init__(self, cash="50000", fail_order=None, **kw):
        super().__init__(**kw)
        self.cash = cash
        self.fail_order = fail_order

    async def funds(self):
        return {"availablecash": self.cash, "net": self.cash}

    async def place_order(self, **kw):
        if self.fail_order:
            self.orders.append({**kw, "refused": True})
            raise RuntimeError(self.fail_order)
        return await super().place_order(**kw)


def quote(ltp):
    return lambda dhan, eqs: _async(({("NSE_EQ", "1594"): {"last_price": ltp}} if ltp else {},
                                     {("NSE_EQ", "1594"): "test"} if ltp else {}))


def copy_desk(trades, ltp=1501.0, positions=None, angel=None, armed=True):
    a = fresh(angel=angel or CashAngel(), positions=positions)
    LT.live_trading_state_collection.docs[0]["armed"] = armed
    PAPER.premium_trades = FakeCollection(trades)
    LT.instruments_collection = FakeCollection([INST])
    LT._equity_quote_map = quote(ltp)
    LT._copy_waiting.clear()
    LT._refused_symbols.clear()
    return a


def claim(pid):
    return next((d for d in LT.live_trading_state_collection.docs if d["_id"] == f"copy|{pid}"), None)


def real_rows(status="OPEN"):
    return [d for d in LT.live_trading_positions_collection.docs if d.get("status") == status]


LT.ENTRY_CUTOFF_HHMM = "24:00"          # the tests run at any hour; the cutoff is checked on its own below

t1 = ptrade()
a = copy_desk([t1])
r = run(LT.scan_cycle(None))
rows = real_rows()
check("an armed desk copies a paper trade 7 minutes after its fill: ONE real order",
      r["opened"] == 1 and len(a.orders) == 1, r)
check("…same side, MIS market order", a.orders[0]["transactiontype"] == "BUY"
      and a.orders[0]["producttype"] == "INTRADAY" and a.orders[0]["ordertype"] == "MARKET")
check("…sized to about Rs 30,000 at the live price", a.orders[0]["quantity"] == int(30000 // 1501.0),
      a.orders[0]["quantity"])
check("…recorded with its paper trade, book, stop and no fixed target",
      rows and rows[0]["parent_id"] == t1["_id"] and rows[0]["parent_book"] == "YT-23|NSE15"
      and rows[0]["stoploss"] == 1485.0 and rows[0]["target"] is None and rows[0]["copied_from"] == "premium_paper"
      and rows[0]["strategy_id"] == SEL and rows[0]["strategy_name"].startswith("YT-23"),
      rows and {k: rows[0].get(k) for k in ("parent_id", "parent_book", "copied_from", "strategy_name")})
check("…and the decision is claimed in the ledger", (claim(t1["_id"]) or {}).get("decision") == "opened", claim(t1["_id"]))
run(LT.scan_cycle(None))
check("the same paper trade is never ordered twice", len(a.orders) == 1, len(a.orders))

t2 = ptrade(sym="TCS", age=400)
a = copy_desk([ptrade(), t2])
LT.instruments_collection = FakeCollection([INST, {**INST, "symbol": "TCS", "security_id": "11536",
                                                   "angel_token": "11536", "angel_tradingsymbol": "TCS-EQ"}])
LT._equity_quote_map = lambda dhan, eqs: _async((
    {("NSE_EQ", "1594"): {"last_price": 1501.0}, ("NSE_EQ", "11536"): {"last_price": 1501.0}},
    {("NSE_EQ", "1594"): "test", ("NSE_EQ", "11536"): "test"}))
run(LT.scan_cycle(None))
check("two paper trades at once: both are copied, the earlier entry first",
      [o["tradingsymbol"] for o in a.orders] == ["INFY-EQ", "TCS-EQ"], [o["tradingsymbol"] for o in a.orders])

SIX = ["INFY", "TCS", "SBIN", "ITC", "LT", "WIPRO"]
SIX_INST = [{**INST, "symbol": s, "security_id": str(100 + i), "angel_token": str(100 + i),
             "angel_tradingsymbol": f"{s}-EQ"} for i, s in enumerate(SIX)]
six_trades = [ptrade(sym=s, age=430 - i) for i, s in enumerate(SIX)]
a = copy_desk(six_trades, angel=CashAngel(cash="34272"))
LT.instruments_collection = FakeCollection(SIX_INST)
LT._equity_quote_map = lambda dhan, eqs: _async((
    {("NSE_EQ", str(100 + i)): {"last_price": 1501.0} for i in range(6)},
    {("NSE_EQ", str(100 + i)): "test" for i in range(6)}))
run(LT.scan_cycle(None))
check("six paper trades at once (Rs 34,272 account): the first five are copied, each about Rs 30,000",
      [o["tradingsymbol"] for o in a.orders] == [f"{s}-EQ" for s in SIX[:5]]
      and all(o["quantity"] == int(30000 // 1501.0) for o in a.orders),
      [(o["tradingsymbol"], o["quantity"]) for o in a.orders])
check("…the sixth waits, unclaimed, while its paper entry is in the window",
      claim(six_trades[5]["_id"]) is None and six_trades[5]["_id"] in LT._copy_waiting, LT._copy_waiting)
check("…and the desk never holds more than Rs 1.5 lakh of notional, or 5x the cash",
      sum(p["capital_deployed"] for p in real_rows()) <= min(150000.0, 34272 * 5),
      sum(p["capital_deployed"] for p in real_rows()))
next(d for d in LT.live_trading_positions_collection.docs if d["symbol"] == "TCS")["status"] = "CLOSED"
run(LT.scan_cycle(None))
check("…and is copied once a slot frees (still in the window)",
      len(a.orders) == 6 and a.orders[-1]["tradingsymbol"] == "WIPRO-EQ", [o["tradingsymbol"] for o in a.orders])

old = ptrade(age=1230)
a = copy_desk([old])
run(LT.scan_cycle(None))
check("a paper trade first seen past the window is not copied, and the decision is final",
      a.orders == [] and "minutes old" in (claim(old["_id"]) or {}).get("decision", ""), claim(old["_id"]))

a = copy_desk([t1], ltp=None)
run(LT.scan_cycle(None))
check("no live quote: no order, no claim (retried next tick)", a.orders == [] and claim(t1["_id"]) is None)
LT._equity_quote_map = quote(1502.0)
run(LT.scan_cycle(None))
check("…and copied on the next tick once a quote arrives", len(a.orders) == 1)

a = copy_desk([t1], ltp=1480.0)
run(LT.scan_cycle(None))
check("price already through the paper stop: no order, final",
      a.orders == [] and "beyond the stop" in (claim(t1["_id"]) or {}).get("decision", ""))

a = copy_desk([t1], ltp=1510.0)
run(LT.scan_cycle(None))
check("price ran past half the stop distance: no order, waiting", a.orders == [] and claim(t1["_id"]) is None)

a = copy_desk([t1], armed=False)
run(LT.scan_cycle(None))
check("a disarmed desk places no order", a.orders == [])
a = copy_desk([t1])
LT.live_trading_state_collection.docs[0]["kill_switch"] = True
run(LT.scan_cycle(None))
check("the kill switch places no order", a.orders == [])

never = [ptrade(acct="NJ-14", mkt="NSE5"),            # a Premium book that is not on the desk
         ptrade(sym="SBIN", open_=False),             # closed on paper
         ptrade(sym="ITC", day=YESTERDAY),            # an earlier session's
         ptrade(sym="LT", qty=0, skip="no cash left"),  # the paper account did not take it
         ptrade(sym="WIPRO", mkt="NIFTY"),            # YT-23's OTHER book (index futures), not the one on the desk
         ptrade(sym="HDFC", side=0)]                  # no side
a = copy_desk(never)
LT.instruments_collection = FakeCollection(SIX_INST + [{**INST, "symbol": "HDFC", "security_id": "1333"}])
LT._equity_quote_map = lambda dhan, eqs: _async(({("NSE_EQ", i["security_id"]): {"last_price": 1501.0}
                                                  for i in SIX_INST}, {}))
run(LT.scan_cycle(None))
check("never copied: other books, closed, earlier-day, untaken (qty 0), another market of a picked account",
      a.orders == [] and real_rows() == [], a.orders)

a = copy_desk([t1], angel=CashAngel(cash="1500"))
run(LT.scan_cycle(None))
check("a Rs 1,500 account funds 5x on MIS (Rs 7,500), never more",
      len(a.orders) == 1 and a.orders[0]["quantity"] == int(1500 * LT.MIS_LEVERAGE // 1501.0), a.orders)
a = copy_desk([t1], angel=CashAngel(cash="200"))
run(LT.scan_cycle(None))
check("an account that cannot fund one share orders nothing", a.orders == [], a.orders)

a = copy_desk([t1], angel=CashAngel(fail_order="RMS: insufficient margin"))
run(LT.scan_cycle(None))
check("an order Angel refuses records no position", real_rows() == [] and len(a.orders) == 1)
check("…counts toward the auto-disarm streak", run(LT.get_state())["consecutive_rejects"] == 1)
check("…and is final: never retried", "not opened" in (claim(t1["_id"]) or {}).get("decision", ""))
run(LT.scan_cycle(None))
check("…(no second attempt)", len(a.orders) == 1)

a = copy_desk([t1])
LT.ENTRY_CUTOFF_HHMM = "00:00"
r = run(LT.scan_cycle(None))
LT.ENTRY_CUTOFF_HHMM = "24:00"
check("past the entry cutoff nothing is copied", a.orders == [] and "cutoff" in r["notes"][0])

a = copy_desk([t1])
_saved_db = LT._paper_db
LT._paper_db = lambda: None
r = run(LT.scan_cycle(None))
LT._paper_db = _saved_db
check("the paper desk's database not configured: no order, and the note says why",
      a.orders == [] and claim(t1["_id"]) is None and "could not be read" in r["notes"][0], r["notes"])


class _BrokenTrades(FakeCollection):
    def find(self, query=None, projection=None):
        raise RuntimeError("server selection timeout")


a = copy_desk([t1])
PAPER.premium_trades = _BrokenTrades()
r = run(LT.scan_cycle(None))
check("the paper desk unreachable: no order, no claim, retried next tick",
      a.orders == [] and claim(t1["_id"]) is None and "could not be read" in r["notes"][0], r["notes"])

# ═════════════════════════════════════════════════════════════════════════════════
section("COPYING THE PAPER DESK — exits")

LT._broker_squaring_off = lambda sym, now: False
LT.load_bars = lambda symbol, tf, years=None: []


def copied(**kw):
    base = pos(strategy_id=SEL, parent_id=t1["_id"], target=None, entry_fill_price=None, qty=33,
               entry_order_id="E1", capital_deployed=49500.0)
    base.update(kw)
    return base


held = [{**{"tradingsymbol": "INFY-EQ", "producttype": "INTRADAY"}, "netqty": "33",
         "buyavgprice": "1500", "sellavgprice": "0"}]
done = [{"orderid": "E1", "status": "complete"}]
closed_t1 = {**t1, "open": False, "reason": "stop"}

a = copy_desk([closed_t1], ltp=1490.0, positions=[copied()], angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("the paper trade closes -> the real one is closed: ONE opposite order",
      len(a.orders) == 1 and a.orders[0]["transactiontype"] == "SELL" and a.orders[0]["quantity"] == 33, a.orders)
check("…labelled with the paper's reason", p["exit_reason"] == "paper closed (stop)", p["exit_reason"])

a = copy_desk([t1], ltp=1490.0, positions=[copied()], angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
check("paper still open, price between stop and entry, no target: no order",
      a.orders == [] and real_rows() and real_rows()[0]["unrealized_pnl"] == round((1490.0 - 1500.0) * 33, 2))

a = copy_desk([t1], ltp=1480.0, positions=[copied()], angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
check("the paper stop on the live price closes the real position", len(a.orders) == 1
      and LT.live_trading_positions_collection.docs[0]["exit_reason"] == "stoploss")
check("…after confirming with Angel that the entry filled",
      LT.live_trading_positions_collection.docs[0].get("entry_confirmed") is True)

a = copy_desk([t1], ltp=1531.0, positions=[copied(target=1530.0, entry_confirmed=True)],
              angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("the paper target on the live price closes the real position: ONE opposite order",
      len(a.orders) == 1 and a.orders[0]["transactiontype"] == "SELL" and p["exit_reason"] == "target",
      (a.orders, p.get("exit_reason")))

a = copy_desk([t1], ltp=1480.0, positions=[copied()],
              angel=CashAngel(book=[], order_book=[{"orderid": "E1", "status": "rejected", "text": "RMS margin"}]))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("an entry Angel REJECTED gets NO exit order (it would open a new position)", a.orders == [], a.orders)
check("…and is voided with Angel's reason", p["status"] == "VOID" and "RMS margin" in (p.get("reconcile_note") or ""))

a = copy_desk([t1], ltp=1480.0, positions=[copied()],
              angel=CashAngel(book=[], order_book=[{"orderid": "E1", "status": "open"}]))
run(LT.manage_cycle(None))
check("an entry still pending at Angel: no exit yet, position kept", a.orders == [] and real_rows())

a = copy_desk([t1], ltp=1480.0, positions=[copied()], angel=CashAngel(book=[], order_book="fail"))
run(LT.manage_cycle(None))
check("an unreadable order book: no exit this tick, position kept", a.orders == [] and real_rows())

a = copy_desk([t1], ltp=1480.0, positions=[copied(entry_fill_price=1500.5)],
              angel=CashAngel(book=held, order_book="fail"))
run(LT.manage_cycle(None))
check("an entry whose real fill is already known exits without asking the order book", len(a.orders) == 1)

flat = [{**held[0], "netqty": "0", "sellavgprice": "1488"}]
fill = [{"tradingsymbol": "INFY-EQ", "producttype": "INTRADAY", "transactiontype": "SELL",
         "orderid": "RMS9", "fillprice": "1488.0", "fillsize": "33"}]
a = copy_desk([closed_t1], ltp=1488.0, positions=[copied(entry_confirmed=True)],
              angel=CashAngel(book=flat, trades=fill, order_book=done))
import time as _time  # noqa: E402
LT._broker_checked_at = _time.monotonic()          # the 30-second check has just run: throttled
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("before an exit the broker is asked even inside the throttle: Angel already flat -> NO order",
      a.orders == [] and p["status"] == "CLOSED" and p["exit_reason"] == "broker_squared_off", (a.orders, p.get("exit_reason")))


class _Bar2:
    def __init__(self, close):
        self.ts = datetime.now(timezone.utc)
        self.close = close


a = copy_desk([t1], ltp=None, positions=[copied(entry_confirmed=True)], angel=CashAngel(book=held, order_book=done))
LT.load_bars = lambda symbol, tf, years=None: [_Bar2(1400.0)]
run(LT.manage_cycle(None))
LT.load_bars = lambda symbol, tf, years=None: []
check("no live quote: a daily bar's close never triggers a stop", a.orders == [] and real_rows())

a = copy_desk([{**t1, "open": False, "reason": "time"}], ltp=None, positions=[copied(entry_confirmed=True)],
              angel=CashAngel(book=held, order_book=done))
LT.load_bars = lambda symbol, tf, years=None: [_Bar2(1490.0)]
run(LT.manage_cycle(None))
LT.load_bars = lambda symbol, tf, years=None: []
check("…but the paper trade's close is still followed without a live quote", len(a.orders) == 1)

# a paper trade that disappears: its replay replaced it
a = copy_desk([], ltp=1495.0, positions=[copied(entry_confirmed=True)], angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("a paper trade gone from the paper desk: first seen gone, no order, the clock starts",
      a.orders == [] and p["status"] == "OPEN" and p.get("paper_missing_since") is not None, p.get("paper_missing_since"))
run(LT.manage_cycle(None))
check("…still inside the grace: no order", a.orders == [])
PAPER.premium_trades = FakeCollection([t1])
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("…back on the paper desk: the clock is cleared", a.orders == [] and p.get("paper_missing_since") is None)
PAPER.premium_trades = FakeCollection([])
run(LT.manage_cycle(None))
LT.live_trading_positions_collection.docs[0]["paper_missing_since"] = datetime.now(timezone.utc) - timedelta(
    seconds=LT.MISSING_GRACE_S + 5)
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("…gone longer than the grace: the real position is closed, ONE opposite order",
      len(a.orders) == 1 and a.orders[0]["transactiontype"] == "SELL" and p["exit_reason"] == "paper trade withdrawn",
      (a.orders, p.get("exit_reason")))

a = copy_desk([], ltp=1495.0, positions=[copied(entry_confirmed=True)], angel=CashAngel(book=held, order_book=done))
PAPER.premium_trades = _BrokenTrades()
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("the paper desk unreadable: nothing is taken as gone, no order",
      a.orders == [] and p["status"] == "OPEN" and p.get("paper_missing_since") is None)
LT._equity_quote_map = quote(1480.0)
run(LT.manage_cycle(None))
check("…and the paper stop still closes it on the live price", len(a.orders) == 1
      and LT.live_trading_positions_collection.docs[0]["exit_reason"] == "stoploss")

# ═════════════════════════════════════════════════════════════════════════════════
section("THE PAPER DESK IS TOLD WHICH BOOKS TO RUN FIRST")

fresh()
ok1 = run(LT.publish_priority(force=True))
doc = next((d for d in PAPER.premium_meta.docs if d["_id"] == LT.PRIORITY_DOC), None)
check("the desk names its six books to the paper desk (premium_meta 'live_priority_nse')",
      ok1 and doc and doc["books"] == [f"{s}|{MKT[s]}" for s in SIXIDS], doc)
check("…switched on or not (the paper record is the strategy's own either way)", len(doc["books"]) == 6)
check("…and not again until the refresh interval has passed", run(LT.publish_priority()) is False)
LT._priority_at -= LT.PRIORITY_REFRESH_S + 1
check("…then again", run(LT.publish_priority()) is True)
_saved_db = LT._paper_db
LT._paper_db = lambda: None
LT._priority_at = 0.0
check("no paper database: nothing written, no error", run(LT.publish_priority(force=True)) is False)
LT._paper_db = _saved_db
check("the Delta desks' own list (premium_meta 'live_priority') is never touched",
      LT.PRIORITY_DOC == "live_priority_nse"
      and not any(d["_id"] == "live_priority" for d in PAPER.premium_meta.docs))

# ═════════════════════════════════════════════════════════════════════════════════
section("THE FAST LOOP — a few real ticks")

import app.services.desk_switches as _DS  # noqa: E402
import app.services.market_calendar as _MC  # noqa: E402

_switch = {"on": True}


async def _is_on(key):
    return _switch["on"]


_DS.is_on = _is_on
_MC.is_trading_day = lambda when=None: True
LT.COPY_START_DELAY_S, LT.COPY_TICK_S, LT.COPY_SESSION = 0.0, 0.02, ("00:00", "24:00")


def ticks(seconds=0.3):
    async def go():
        task = asyncio.create_task(LT.copy_loop())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    run(go())


# the broker holds exactly what the loop bought (a different quantity would be a mismatch: never auto-exited)
held_copy = [{**held[0], "netqty": str(int(LT.COPY_NOTIONAL // 1501.0))}]
a = copy_desk([dict(t1)], angel=CashAngel(book=held_copy, order_book=[{"orderid": "EXIT1", "status": "complete"}]))
ticks()
check("an armed desk: the loop copies the paper trade once, however many ticks run",
      len(a.orders) == 1 and len(real_rows()) == 1, len(a.orders))
check("…and names its books to the paper desk on its first tick",
      any(d["_id"] == LT.PRIORITY_DOC for d in PAPER.premium_meta.docs))
PAPER.premium_trades.docs[0].update(open=False, reason="target")
LT._equity_quote_map = quote(1503.0)
ticks()
check("…and closes it within ticks of the paper trade's close", len(a.orders) == 2
      and a.orders[1]["transactiontype"] == "SELL" and real_rows() == [], [o["transactiontype"] for o in a.orders])

a = copy_desk([t1], armed=False)
ticks()
check("a disarmed desk: the loop places nothing", a.orders == [])

a = copy_desk([t1], angel=CashAngel(book=held, order_book=done))
_switch["on"] = False
ticks()
_switch["on"] = True
check("Main Control switched off: the loop places nothing", a.orders == [])

a = copy_desk([t1], angel=CashAngel(book=held, order_book=done))
_MC.is_trading_day = lambda when=None: False
ticks()
_MC.is_trading_day = lambda when=None: True
check("a market holiday: the loop places nothing", a.orders == [])

# ═════════════════════════════════════════════════════════════════════════════════
section("BALANCE READS AND REASONS (12 Nov 2026)")


class FlakyAngel(CashAngel):
    """funds() fails its first `fails` calls, the way Angel's RMS read failed 24 times on 12 Nov."""

    def __init__(self, fails=1, **kw):
        super().__init__(**kw)
        self.fails, self.funds_calls = fails, 0

    async def funds(self):
        self.funds_calls += 1
        if self.funds_calls <= self.fails:
            raise AttributeError("'NoneType' object has no attribute 'getpeername'")
        return await super().funds()


LT._BALANCE_RETRY_S = 0.0
a = fresh(angel=FlakyAngel(fails=1))
b = run(LT.account_balance(force=True))
check("one failed balance read is retried at once and succeeds", b["ok"] and a.funds_calls == 2, (b, a.funds_calls))
a = fresh(angel=FlakyAngel(fails=2))
b = run(LT.account_balance(force=True))
check("two in a row: the read fails, and says what failed", b["ok"] is False and "getpeername" in b["error"], b.get("error"))
LT._balance_cache["at"] -= LT._BALANCE_FAIL_TTL + 1
b = run(LT.account_balance())
check("a failure is kept seconds, not a minute: the next read asks Angel again", b["ok"] and a.funds_calls == 3, a.funds_calls)

a = copy_desk([t1], angel=FlakyAngel(fails=2))
run(LT.scan_cycle(None))
check("a signal while the balance cannot be read: no order, no claim, waiting",
      a.orders == [] and claim(t1["_id"]) is None and "balance" in LT._copy_waiting.get(t1["_id"], ""), LT._copy_waiting)
LT._balance_cache["at"] -= LT._BALANCE_FAIL_TTL + 1
run(LT.scan_cycle(None))
check("…and copied on the next tick once the balance reads again", len(a.orders) == 1, len(a.orders))

a = copy_desk([t1], angel=CashAngel(
    fail_order="Angel error: The order cannot be processed as the token is categorised under cautionary listings by the exchange."))
run(LT.scan_cycle(None))
d = (claim(t1["_id"]) or {}).get("decision", "")
check("a stock on the exchange's caution list: the record says so", "caution" in d and "surveillance" in d, d)
st = run(LT.get_state())
check("…it is not counted as a reject, and the desk stays armed", st["consecutive_rejects"] == 0 and st["armed"], st)
ct = run(LT.copy_decisions_today())
check("today's signals are listed for the page, with what happened",
      len(ct) == 1 and ct[0]["symbol"] == "INFY" and "caution" in ct[0]["decision"] and ct[0]["at"]
      and ct[0]["strategy_id"] == SEL and ct[0]["parent_id"] == t1["_id"], ct)

# ═════════════════════════════════════════════════════════════════════════════════
section("SIX STRATEGIES, ONE POOL")


def switch_on(*sids, off=()):
    LT.live_trading_flags_collection = FakeCollection(
        [{"strategy_id": s, "enabled": True} for s in sids] + [{"strategy_id": s, "enabled": False} for s in off])


def multi_quotes(insts, ltp=1501.0):
    LT.instruments_collection = FakeCollection(insts)
    LT._equity_quote_map = lambda dhan, eqs: _async((
        {("NSE_EQ", i["security_id"]): {"last_price": ltp} for i in insts},
        {("NSE_EQ", i["security_id"]): "test" for i in insts}))


for sid in SIXIDS:
    tr = ptrade(acct=sid, target=1530.0)
    a = copy_desk([tr])
    run(LT.scan_cycle(None))
    rows = real_rows()
    check(f"{sid}: its paper trade becomes ONE real order, recorded under its own name with the paper stop and target",
          len(a.orders) == 1 and bool(rows) and rows[0]["strategy_id"] == sid
          and rows[0]["strategy_name"] == LT.SELECTED_BY_ID[sid].name and rows[0]["stoploss"] == 1485.0
          and rows[0]["target"] == 1530.0 and (claim(tr["_id"]) or {}).get("strategy_id") == sid,
          (a.orders, rows and {k: rows[0].get(k) for k in ("strategy_id", "target")}))

tr = ptrade(acct="TW-01", target=1530.0)
a = copy_desk([tr])
switch_on(off=("TW-01",))
run(LT.scan_cycle(None))
check("one strategy switched off: its paper trade places no order and is not claimed",
      a.orders == [] and claim(tr["_id"]) is None)

u1 = ptrade(acct="SS-03", age=430)
u2 = ptrade(acct="DH-05", age=420, target=1530.0)
a = copy_desk([u1, u2])
run(LT.scan_cycle(None))
check("two strategies, one stock: only the earlier entry is ordered",
      len(a.orders) == 1 and [r["strategy_id"] for r in real_rows()] == ["SS-03"], [r["strategy_id"] for r in real_rows()])
check("…the second is final, and says the desk already holds the stock",
      "already holds" in (claim(u2["_id"]) or {}).get("decision", ""), claim(u2["_id"]))
run(LT.scan_cycle(None))
check("…and it is never ordered later", len(a.orders) == 1)

b2 = ptrade(acct="UP-03", side=-1, stop=1515.0, target=1490.0)
a = copy_desk([b2], positions=[copied(entry_confirmed=True)])
run(LT.scan_cycle(None))
check("an opposite-side signal in a stock the desk holds is never ordered (Angel nets the stock)",
      a.orders == [] and "already holds" in (claim(b2["_id"]) or {}).get("decision", ""), claim(b2["_id"]))

mix = ["YT-23", "SS-03", "VWAP-U4", "TW-01", "DH-05", "UP-03"]
mixed = [ptrade(sym=s, acct=mix[i], age=430 - i, target=None if i % 2 else 1530.0) for i, s in enumerate(SIX)]
a = copy_desk(mixed, angel=CashAngel(cash="34272"))
multi_quotes(SIX_INST)
run(LT.scan_cycle(None))
check("six strategies share ONE pool: six entries at once -> the first five are ordered",
      [o["tradingsymbol"] for o in a.orders] == [f"{s}-EQ" for s in SIX[:5]], [o["tradingsymbol"] for o in a.orders])
check("…each real position carries its own strategy",
      [r["strategy_id"] for r in real_rows()] == mix[:5], [r["strategy_id"] for r in real_rows()])
check("…the sixth waits for a slot, unclaimed",
      claim(mixed[5]["_id"]) is None and mixed[5]["_id"] in LT._copy_waiting, LT._copy_waiting)
check("…and the desk still never holds more than Rs 1.5 lakh of notional",
      sum(p["capital_deployed"] for p in real_rows()) <= 150000.0, sum(p["capital_deployed"] for p in real_rows()))

# ═════════════════════════════════════════════════════════════════════════════════
section("WHAT THE PAGE READS")

a = copy_desk([t1], positions=[copied()])
sm = run(LT.summary())
check("the summary names where it copies from, the size and the override",
      sm["copy_from"] == "premium_paper" and sm["copy_source"] == SEL and sm["copy_notional"] == 30000.0
      and sm["max_open_positions"] == 5 and set(sm["gate_override"]) == set(SIXIDS) and sm["copy_window_s"] == 1200.0,
      {k: sm.get(k) for k in ("copy_from", "copy_source", "copy_notional", "copy_window_s")})
check("…every strategy it can copy, with its switch, paper book and category (all six on)",
      [(c["strategy_id"], c["enabled"], c["book"]) for c in sm.get("copy_strategies", [])]
      == [(s, True, f"{s}|{MKT[s]}") for s in SIXIDS] and sm.get("copy_sources") == SIXIDS
      and all(c.get("category") for c in sm["copy_strategies"]), sm.get("copy_strategies"))
check("…and today's paper signals", isinstance(sm.get("copy_today"), list))
op = run(LT.open_positions())
check("open positions carry their paper trade and no target", op[0]["parent_id"] == t1["_id"] and op[0]["target"] is None)
LT.live_trading_state_collection.docs.append({"_id": "copy|DH-05|NSE5|SBIN|1|1", "at": datetime.now(timezone.utc),
                                               "symbol": "SBIN", "side": "BUY", "decision": "opened",
                                               "strategy_id": "DH-05", "strategy_name": LT.SELECTED_BY_ID["DH-05"].name})
ct = {c["parent_id"]: c for c in run(LT.copy_decisions_today())}
check("today's signals name their strategy and keep the paper trade's whole id",
      ct["DH-05|NSE5|SBIN|1|1"]["strategy_name"].startswith("DH-05"), ct)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
