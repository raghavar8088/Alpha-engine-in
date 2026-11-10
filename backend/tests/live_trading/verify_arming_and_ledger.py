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


def fresh(angel=None, positions=None, registry=None, flags=None, session=None, gate=True):
    """A clean desk: new collections, a new Angel, a new session, the throttle reset."""
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


# The desk itself trades ONE strategy whose gate the owner overrode (10 Nov 2026). The gate's own
# machinery is checked on eight stand-ins with no override: it must still hold for anything added.
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
section("THE OWNER'S OVERRIDE (10 Nov 2026)")

use_real_desk()
SEL = "iv2_orb_sel15"
check("the desk trades exactly one strategy: the tournament's Selected ORB 15-min",
      [ls.strategy_id for ls in LT.SELECTED] == [SEL], [ls.strategy_id for ls in LT.SELECTED])
check("its override is written down, dated, in the code", "10 Nov 2026" in LT.OWNER_OVERRIDE.get(SEL, ""))
check("one real position at a time, about Rs 50,000 of notional",
      LT.MAX_OPEN_POSITIONS == 1 and LT.COPY_NOTIONAL == 50000.0 and LT.DESK_CEILING == 50000.0)

fresh()
chk = run(LT.arming_check())
row = chk["strategies"][0]
check("with no verdict on file, the overridden strategy may be armed", chk["allowed"] is True, chk["blockers"])
check("…the override is announced first among the warnings", "OVERRIDDEN" in (chk["warnings"] or [""])[0],
      chk["warnings"][:1])
check("…its row keeps its real verdict and says why it may trade",
      row["verdict"] == "NOT_REGISTERED" and row["validated"] is True and "overridden" in row["reason"], row)
check("…and the overridden count is reported apart", chk.get("overridden_enabled") == 1)
run(LT.set_armed(True))
check("set_armed(True) succeeds", run(LT.get_state())["armed"] is True)

fresh(positions=[pos(opened_on=YESTERDAY, strategy_id=SEL)])
check("the override never bypasses the ledger: a stale OPEN position still blocks arming",
      run(LT.arming_check())["allowed"] is False)
fresh(flags=[{"strategy_id": SEL, "enabled": False}])
check("disabled, there is nothing to arm", run(LT.arming_check())["allowed"] is False)

board = run(LT.leaderboard())
check("the leaderboard shows the override beside the verdict",
      board[0]["validated"] is True and board[0]["override"] and board[0]["verdict"] == "NOT_REGISTERED")

# ═════════════════════════════════════════════════════════════════════════════════
section("COPYING THE TOURNAMENT — copy_check")

NOW = datetime.now(timezone.utc)


def parent(**kw):
    base = {"position_id": "T1", "engine": "v2", "strategy_id": SEL, "symbol": "INFY", "side": "BUY",
            "entry_price": 1500.0, "stoploss": 1485.0, "target": None, "status": "OPEN",
            "opened_on": TODAY, "opened_at": NOW - timedelta(seconds=20), "rationale": "range break"}
    base.update(kw)
    return base


cc = LT.copy_check
check("a fresh BUY near its paper fill is copied", cc(parent(), 1501.0, 0, NOW) == (None, True))
check("a paper entry older than the window is final", cc(parent(opened_at=NOW - timedelta(seconds=400)), 1501.0, 0, NOW)[1] is True
      and "old" in cc(parent(opened_at=NOW - timedelta(seconds=400)), 1501.0, 0, NOW)[0])
check("a naive (Mongo) timestamp is read as UTC",
      cc(parent(opened_at=(NOW - timedelta(seconds=20)).replace(tzinfo=None)), 1501.0, 0, NOW) == (None, True))
w, f = cc(parent(), 1501.0, 1, NOW)
check("one real position open: wait (not final)", w and "one real position" in w and f is False, w)
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

# ═════════════════════════════════════════════════════════════════════════════════
section("COPYING THE TOURNAMENT — real entries")

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


def copy_desk(parents, ltp=1501.0, positions=None, angel=None, armed=True):
    a = fresh(angel=angel or CashAngel(), positions=positions)
    LT.live_trading_state_collection.docs[0]["armed"] = armed
    LT.intraday_lab_positions_collection = FakeCollection(parents)
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

a = copy_desk([parent()])
r = run(LT.scan_cycle(None))
rows = real_rows()
check("an armed desk copies a fresh tournament entry: ONE real order", r["opened"] == 1 and len(a.orders) == 1, r)
check("…same side, MIS market order", a.orders[0]["transactiontype"] == "BUY"
      and a.orders[0]["producttype"] == "INTRADAY" and a.orders[0]["ordertype"] == "MARKET")
check("…sized to about Rs 50,000 at the live price", a.orders[0]["quantity"] == int(50000 // 1501.0),
      a.orders[0]["quantity"])
check("…recorded with its tournament parent, the paper stop and no fixed target",
      rows and rows[0]["parent_id"] == "T1" and rows[0]["stoploss"] == 1485.0 and rows[0]["target"] is None
      and rows[0]["copied_from"] == "tournament")
check("…and the decision is claimed in the ledger", (claim("T1") or {}).get("decision") == "opened", claim("T1"))
run(LT.scan_cycle(None))
check("the same tournament position is never ordered twice", len(a.orders) == 1, len(a.orders))

a = copy_desk([parent(), parent(position_id="T2", symbol="TCS")])
LT.instruments_collection = FakeCollection([INST, {**INST, "symbol": "TCS", "security_id": "11536",
                                                   "angel_token": "11536", "angel_tradingsymbol": "TCS-EQ"}])
LT._equity_quote_map = lambda dhan, eqs: _async((
    {("NSE_EQ", "1594"): {"last_price": 1501.0}, ("NSE_EQ", "11536"): {"last_price": 1501.0}},
    {("NSE_EQ", "1594"): "test", ("NSE_EQ", "11536"): "test"}))
r = run(LT.scan_cycle(None))
check("two tournament entries at once: only the first is copied (one at a time)",
      len(a.orders) == 1 and a.orders[0]["tradingsymbol"] == "INFY-EQ", [o["tradingsymbol"] for o in a.orders])
check("…the second waits, unclaimed, while its paper entry is fresh",
      claim("T2") is None and "T2" in LT._copy_waiting, LT._copy_waiting)
LT.live_trading_positions_collection.docs[0]["status"] = "CLOSED"     # the first one closes
run(LT.scan_cycle(None))
check("…and is copied once the first real position has closed (still fresh)",
      len(a.orders) == 2 and a.orders[1]["tradingsymbol"] == "TCS-EQ", [o["tradingsymbol"] for o in a.orders])

a = copy_desk([parent(opened_at=NOW - timedelta(seconds=200))])
run(LT.scan_cycle(None))
check("a paper entry past the window is not copied, and the decision is final",
      a.orders == [] and "old" in (claim("T1") or {}).get("decision", ""), claim("T1"))

a = copy_desk([parent()], ltp=None)
run(LT.scan_cycle(None))
check("no live quote: no order, no claim (retried next tick)", a.orders == [] and claim("T1") is None)
LT._equity_quote_map = quote(1502.0)
run(LT.scan_cycle(None))
check("…and copied on the next tick once a quote arrives", len(a.orders) == 1)

a = copy_desk([parent()], ltp=1480.0)
run(LT.scan_cycle(None))
check("price already through the paper stop: no order, final",
      a.orders == [] and "beyond the stop" in (claim("T1") or {}).get("decision", ""))

a = copy_desk([parent()], ltp=1510.0)
run(LT.scan_cycle(None))
check("price ran past half the stop distance: no order, waiting", a.orders == [] and claim("T1") is None)

for label, kw in (("a disarmed desk", dict(armed=False)),):
    a = copy_desk([parent()], **kw)
    run(LT.scan_cycle(None))
    check(f"{label} places no order", a.orders == [])
a = copy_desk([parent()])
LT.live_trading_state_collection.docs[0]["kill_switch"] = True
run(LT.scan_cycle(None))
check("the kill switch places no order", a.orders == [])

a = copy_desk([parent(strategy_id="iv2_orb_5m"), parent(position_id="T3", status="CLOSED"),
               parent(position_id="T4", opened_on=YESTERDAY), parent(position_id="T5", engine="v1")])
run(LT.scan_cycle(None))
check("other strategies, closed, earlier-day and non-v2 paper positions are never copied", a.orders == [])

a = copy_desk([parent()], angel=CashAngel(cash="10000"))
run(LT.scan_cycle(None))
check("a Rs 10,000 account funds about 4.5x on MIS, never more",
      len(a.orders) == 1 and a.orders[0]["quantity"] == int(10000 * LT.MIS_LEVERAGE // 1501.0), a.orders)

a = copy_desk([parent()], angel=CashAngel(fail_order="RMS: insufficient margin"))
run(LT.scan_cycle(None))
check("an order Angel refuses records no position", real_rows() == [] and len(a.orders) == 1)
check("…counts toward the auto-disarm streak", run(LT.get_state())["consecutive_rejects"] == 1)
check("…and is final: never retried", "not opened" in (claim("T1") or {}).get("decision", ""))
run(LT.scan_cycle(None))
check("…(no second attempt)", len(a.orders) == 1)

a = copy_desk([parent()])
LT.ENTRY_CUTOFF_HHMM = "00:00"
r = run(LT.scan_cycle(None))
LT.ENTRY_CUTOFF_HHMM = "24:00"
check("past the entry cutoff nothing is copied", a.orders == [] and "cutoff" in r["notes"][0])

# ═════════════════════════════════════════════════════════════════════════════════
section("COPYING THE TOURNAMENT — exits")

LT._broker_squaring_off = lambda sym, now: False
LT.load_bars = lambda symbol, tf, years=None: []


def copied(**kw):
    base = pos(strategy_id=SEL, parent_id="T1", target=None, entry_fill_price=None, qty=33,
               entry_order_id="E1", capital_deployed=49500.0)
    base.update(kw)
    return base


held = [{**{"tradingsymbol": "INFY-EQ", "producttype": "INTRADAY"}, "netqty": "33",
         "buyavgprice": "1500", "sellavgprice": "0"}]
done = [{"orderid": "E1", "status": "complete"}]

a = copy_desk([parent(status="CLOSED", exit_reason="stoploss")], ltp=1490.0, positions=[copied()],
              angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("the tournament closes its position -> the real one is closed: ONE opposite order",
      len(a.orders) == 1 and a.orders[0]["transactiontype"] == "SELL" and a.orders[0]["quantity"] == 33, a.orders)
check("…labelled with the tournament's reason", p["exit_reason"] == "tournament closed (stoploss)", p["exit_reason"])

a = copy_desk([parent()], ltp=1490.0, positions=[copied()], angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
check("tournament still open, price between stop and entry, no target: no order",
      a.orders == [] and real_rows() and real_rows()[0]["unrealized_pnl"] == round((1490.0 - 1500.0) * 33, 2))

a = copy_desk([parent()], ltp=1480.0, positions=[copied()], angel=CashAngel(book=held, order_book=done))
run(LT.manage_cycle(None))
check("the paper stop on the live price closes the real position", len(a.orders) == 1
      and LT.live_trading_positions_collection.docs[0]["exit_reason"] == "stoploss")
check("…after confirming with Angel that the entry filled",
      LT.live_trading_positions_collection.docs[0].get("entry_confirmed") is True)

a = copy_desk([parent()], ltp=1480.0, positions=[copied()],
              angel=CashAngel(book=[], order_book=[{"orderid": "E1", "status": "rejected", "text": "RMS margin"}]))
run(LT.manage_cycle(None))
p = LT.live_trading_positions_collection.docs[0]
check("an entry Angel REJECTED gets NO exit order (it would open a new position)", a.orders == [], a.orders)
check("…and is voided with Angel's reason", p["status"] == "VOID" and "RMS margin" in (p.get("reconcile_note") or ""))

a = copy_desk([parent()], ltp=1480.0, positions=[copied()],
              angel=CashAngel(book=[], order_book=[{"orderid": "E1", "status": "open"}]))
run(LT.manage_cycle(None))
check("an entry still pending at Angel: no exit yet, position kept", a.orders == [] and real_rows())

a = copy_desk([parent()], ltp=1480.0, positions=[copied()], angel=CashAngel(book=[], order_book="fail"))
run(LT.manage_cycle(None))
check("an unreadable order book: no exit this tick, position kept", a.orders == [] and real_rows())

a = copy_desk([parent()], ltp=1480.0, positions=[copied(entry_fill_price=1500.5)],
              angel=CashAngel(book=held, order_book="fail"))
run(LT.manage_cycle(None))
check("an entry whose real fill is already known exits without asking the order book", len(a.orders) == 1)

flat = [{**held[0], "netqty": "0", "sellavgprice": "1488"}]
fill = [{"tradingsymbol": "INFY-EQ", "producttype": "INTRADAY", "transactiontype": "SELL",
         "orderid": "RMS9", "fillprice": "1488.0", "fillsize": "33"}]
a = copy_desk([parent(status="CLOSED", exit_reason="stoploss")], ltp=1488.0,
              positions=[copied(entry_confirmed=True)], angel=CashAngel(book=flat, trades=fill, order_book=done))
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


a = copy_desk([parent()], ltp=None, positions=[copied(entry_confirmed=True)], angel=CashAngel(book=held, order_book=done))
LT.load_bars = lambda symbol, tf, years=None: [_Bar2(1400.0)]
run(LT.manage_cycle(None))
LT.load_bars = lambda symbol, tf, years=None: []
check("no live quote: a daily bar's close never triggers a stop", a.orders == [] and real_rows())

a = copy_desk([parent(status="CLOSED", exit_reason="eod")], ltp=None, positions=[copied(entry_confirmed=True)],
              angel=CashAngel(book=held, order_book=done))
LT.load_bars = lambda symbol, tf, years=None: [_Bar2(1490.0)]
run(LT.manage_cycle(None))
LT.load_bars = lambda symbol, tf, years=None: []
check("…but the tournament's close is still followed without a live quote", len(a.orders) == 1)

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


a = copy_desk([parent()], angel=CashAngel(book=held, order_book=[{"orderid": "EXIT1", "status": "complete"}]))
ticks()
check("an armed desk: the loop copies the tournament entry once, however many ticks run",
      len(a.orders) == 1 and len(real_rows()) == 1, len(a.orders))
LT.intraday_lab_positions_collection.docs[0].update(status="CLOSED", exit_reason="target")
LT._equity_quote_map = quote(1503.0)
ticks()
check("…and closes it within ticks of the tournament's close", len(a.orders) == 2
      and a.orders[1]["transactiontype"] == "SELL" and real_rows() == [], [o["transactiontype"] for o in a.orders])

a = copy_desk([parent()], armed=False)
ticks()
check("a disarmed desk: the loop places nothing", a.orders == [])

a = copy_desk([parent()], angel=CashAngel(book=held, order_book=done))
_switch["on"] = False
ticks()
_switch["on"] = True
check("Main Control switched off: the loop places nothing", a.orders == [])

a = copy_desk([parent()], angel=CashAngel(book=held, order_book=done))
_MC.is_trading_day = lambda when=None: False
ticks()
_MC.is_trading_day = lambda when=None: True
check("a market holiday: the loop places nothing", a.orders == [])

# ═════════════════════════════════════════════════════════════════════════════════
section("WHAT THE PAGE READS")

a = copy_desk([parent()], positions=[copied()])
sm = run(LT.summary())
check("the summary names the copied strategy, the size and the override",
      sm["copy_source"] == SEL and sm["copy_notional"] == 50000.0 and sm["max_open_positions"] == 1
      and SEL in sm["gate_override"], {k: sm.get(k) for k in ("copy_source", "copy_notional", "gate_override")})
op = run(LT.open_positions())
check("open positions carry their tournament parent and no target", op[0]["parent_id"] == "T1" and op[0]["target"] is None)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
