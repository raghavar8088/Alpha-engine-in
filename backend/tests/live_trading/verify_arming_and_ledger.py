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
                return
        if upsert:
            self.docs.append(self._with_id({**{k: v for k, v in query.items()
                                               if not isinstance(v, dict)},
                                            **update.get("$set", {})}))

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

check("the desk carries more strategies than the eight the page used to describe",
      len(IDS) >= 8, f"{len(IDS)} strategies")

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

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
