"""Does the Patterns desk fill like a broker, and can its strategies still pile onto one name?

Run:  python backend/tests/intraday_patterns/verify_fills_and_caps.py

No Mongo, no Angel, no network: collections are in-memory fakes, the Angel stream is a fake
holding minute bars, and the quote endpoint is a fake.

WHY THIS EXISTS (INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md, D1/D2). The desk closed every
trade at the LTP its three-minute poll happened to see, so price that had run past a target
was booked as profit, and it charged no slippage: +Rs53 lakh reported over 6-9 Oct 2026,
-Rs23 lakh once targets fill at the target and slippage is paid. And 504 strategies on 25
names meant 88% of trades duplicated another strategy's bet — up to 32 strategies, Rs3.18
crore, on one BBOX trade. The real row from the audit is replayed below.
"""

import asyncio
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
for p in ("broker-clients", "shared", "backtesting-service"):
    sys.path.insert(0, str(ROOT / p))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()
for name in ("redis", "redis.asyncio"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            root = name.split(".")[0]
            mod = sys.modules.get(root) or types.ModuleType(root)
            sys.modules[root] = mod
            if "." in name:
                sub = types.ModuleType(name)
                setattr(mod, name.split(".")[1], sub)
                sys.modules[name] = sub

import app.services.intraday_fills as F  # noqa: E402
import app.services.intraday_pattern_engine as PE  # noqa: E402
import app.services.pattern_books_engine as PB  # noqa: E402
from app.services.angel_fees import product_for, round_trip  # noqa: E402

# A Windows console cannot encode every character a detail may hold; never crash on it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

FAILURES: list[str] = []
IST = timezone(timedelta(hours=5, minutes=30))


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
                if op == "$ne" and got == val:
                    return False
                if op == "$in" and got not in val:
                    return False
        elif got != want:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class FakeCollection:
    _seq = 0

    def __init__(self, docs=None):
        self.docs = [self._id(d) for d in (docs or [])]

    @classmethod
    def _id(cls, d):
        d = dict(d)
        if "_id" not in d:
            cls._seq += 1
            d["_id"] = f"o{cls._seq}"
        return d

    async def find_one(self, query, projection=None):
        hits = [d for d in self.docs if _matches(d, query)]
        return dict(hits[0]) if hits else None

    def find(self, query=None, projection=None):
        return _Cursor([dict(d) for d in self.docs if _matches(d, query or {})])

    async def insert_one(self, doc):
        self.docs.append(self._id(doc))

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append(self._id({**query, **update.get("$set", {})}))

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))


class FakeState:
    """One symbol's stream state: closed minute bars + the forming one."""

    def __init__(self, minutes, ltp=None):
        self.mt = [m[0] for m in minutes]
        self.mo = [m[1] for m in minutes]
        self.mh = [m[2] for m in minutes]
        self.ml = [m[3] for m in minutes]
        self.mc = [m[4] for m in minutes]
        self.cur = None
        self.last_ltp = ltp
        self.last_tick = time.time() if ltp is not None else 0


class FakeStream:
    def __init__(self, states=None):
        self.states = states or {}


class FakeSession:
    def __init__(self, due=False):
        self._due = due

    async def ensure_cas(self):
        return None

    def squareoff_due(self, symbol, now=None):
        return self._due


QUOTES: dict[str, float] = {}


async def fake_quote(symbols):
    return {s: QUOTES[s] for s in symbols if s in QUOTES}


def fresh(positions=None, stream=None, due=False, quotes=None):
    PE.pattern_positions_collection = FakeCollection(positions)
    PE.pattern_trades_collection = FakeCollection()
    PE.pattern_scores_collection = FakeCollection()
    PE.pattern_state_collection = FakeCollection()
    F.stream = stream or FakeStream()
    PE.session = FakeSession(due)
    PE._quote = fake_quote
    QUOTES.clear()
    QUOTES.update(quotes or {})


def run(c):
    return asyncio.run(c)


NOW_MIN = int(time.time()) // 60 * 60
TODAY = datetime.now(IST).date().isoformat()
ST15 = next(s for s in PE.CATALOG if s.timeframe == "15m")


def pos(**kw):
    base = {"position_id": "p", "strategy_id": ST15.strategy_id, "strategy_name": ST15.name,
            "template": ST15.template, "family": ST15.family, "timeframe": "15m",
            "style": "intraday", "symbol": "ABDL", "side": "BUY", "entry_price": 699.15,
            "qty": 1430, "target": 705.44, "stoploss": 694.96, "slippage_bp": 3.0,
            "turnover_cr": 200.0, "max_hold_bars": 10, "status": "OPEN", "opened_on": TODAY,
            "opened_at": datetime.now(timezone.utc) - timedelta(minutes=20),
            "checked_through": NOW_MIN - 600}
    base.update(kw)
    return base


def closed():
    return PE.pattern_positions_collection.docs[0]


# ═════════════════════════════════════════════════════════════════════════════════
section("C1 · THE ROW FROM THE AUDIT, REPLAYED")

# ABDL 2026-10-06: entry 699.15, target 705.44 — booked at 714.65 because that was the LTP
# when the 3-minute poll looked. With minute bars, the minute that crossed 705.44 decides.
mins = [(NOW_MIN - 540, 700.0, 702.0, 699.5, 701.5),
        (NOW_MIN - 480, 701.5, 708.9, 701.0, 708.0),      # crosses the target
        (NOW_MIN - 420, 708.0, 715.0, 707.5, 714.65)]     # where the poll first looked
fresh([pos()], stream=FakeStream({"ABDL": FakeState(mins, ltp=714.65)}))
run(PE._manage())
p = closed()
check("the trade closes as a target", p["exit_reason"] == "target")
check("…AT the target, not at the LTP the poll saw", p["exit_price"] == 705.44,
      f"{p['exit_price']} (was booked at 714.65)")
gross = round((705.44 - 699.15) * 1430, 2)
check("…so gross is the target's move, not the overshoot",
      p["gross_pnl"] == gross, f"Rs {p['gross_pnl']:,.0f} vs the Rs 22,165 first booked")
check("…a target is a limit order: no slippage on it", "level @ 705.44" in p["exit_basis"], p["exit_basis"])

# ═════════════════════════════════════════════════════════════════════════════════
section("C1 · FILL RULES ON STREAM MINUTE BARS")

both = [(NOW_MIN - 300, 700.0, 706.0, 694.0, 700.0)]          # one minute crosses BOTH
fresh([pos()], stream=FakeStream({"ABDL": FakeState(both, ltp=700.0)}))
run(PE._manage())
p = closed()
check("a minute crossing both levels counts as the STOP", p["exit_reason"] == "stoploss")
check("…at the stop level, less slippage (a stop is a market order)",
      abs(p["exit_price"] - round(694.96 * (1 - 3 / 1e4), 2)) < 0.011, p["exit_price"])

gap = [(NOW_MIN - 300, 690.0, 692.0, 688.0, 691.0)]           # opens below the stop
fresh([pos()], stream=FakeStream({"ABDL": FakeState(gap, ltp=691.0)}))
run(PE._manage())
p = closed()
check("a minute that opens through the stop fills at that open, less slippage",
      abs(p["exit_price"] - round(690.0 * (1 - 3 / 1e4), 2)) < 0.011, p["exit_price"])

short = [(NOW_MIN - 300, 700.0, 700.5, 692.0, 693.0)]         # a short's target is below
fresh([pos(side="SELL", entry_price=699.15, target=693.0, stoploss=703.0)],
      stream=FakeStream({"ABDL": FakeState(short, ltp=693.0)}))
run(PE._manage())
p = closed()
check("a short's target fills at the target", p["exit_reason"] == "target" and p["exit_price"] == 693.0)

old = [(NOW_MIN - 900, 700.0, 710.0, 699.0, 709.0)]           # before checked_through
fresh([pos(checked_through=NOW_MIN - 600)], stream=FakeStream({"ABDL": FakeState(old, ltp=701.0)}))
run(PE._manage())
check("minutes already checked are not walked again",
      closed()["status"] == "OPEN", closed().get("exit_reason"))
check("…and the mark advances checked_through to the current minute",
      closed()["checked_through"] >= NOW_MIN - 60)

# ═════════════════════════════════════════════════════════════════════════════════
section("C1 · WITHOUT STREAM BARS — THE QUOTE FALLBACK")

fresh([pos()], quotes={"ABDL": 714.65})
run(PE._manage())
p = closed()
check("a quote beyond the target still fills AT the target", p["exit_price"] == 705.44, p["exit_price"])
check("…labelled as the quote path", "(quote)" in p["exit_basis"], p["exit_basis"])

fresh([pos()], quotes={"ABDL": 690.0})
run(PE._manage())
p = closed()
check("a quote beyond the stop is a market exit at that price, less slippage",
      p["exit_reason"] == "stoploss" and abs(p["exit_price"] - round(690.0 * (1 - 3 / 1e4), 2)) < 0.011)

fresh([pos()], quotes={})
run(PE._manage())
check("no stream and no quote: nothing is decided, nothing invented", closed()["status"] == "OPEN")

# ═════════════════════════════════════════════════════════════════════════════════
section("C1 · TIME EXITS PAY SLIPPAGE")

fresh([pos()], quotes={"ABDL": 701.0}, due=True)
run(PE._manage())
p = closed()
check("end of day is a market exit at the quote, less slippage",
      p["exit_reason"] == "eod" and abs(p["exit_price"] - round(701.0 * (1 - 3 / 1e4), 2)) < 0.011)
check("…dated today", p["closed_on"] == TODAY)
fb = round_trip(699.15, p["exit_price"], 1430, side="BUY", product=product_for(None, 0))
check("…charged Angel's intraday card", p["fees"] == fb.total, p["fees"])
check("…and recorded in the blotter with its basis",
      PE.pattern_trades_collection.docs[0].get("exit_basis") == p["exit_basis"])

# ═════════════════════════════════════════════════════════════════════════════════
section("C1 · ENTRIES PAY SLIPPAGE, AND LEVELS COME FROM THE FILL")

fresh()
PE._cash = lambda sid: _val(10_000_000.0)


async def _v(x):
    return x


def _val(x):
    return _v(x)


inst = {"symbol": "ABDL"}
ok = run(PE._open(ST15, inst, 700.0, 1, "bar", turnover_cr=200.0))
p = closed()
bp = F.slippage_bp(200.0)
check("an entry fills a market order's worth above the signal price",
      ok and abs(p["entry_price"] - round(700.0 * (1 + bp / 1e4), 2)) < 0.011, p["entry_price"])
check("…the signal price and the basis are kept",
      p["signal_price"] == 700.0 and f"{bp:g} bp" in p["fill_basis"], p["fill_basis"])
tf = PE.TF_BY_KEY["15m"]
check("…and the target is measured from the fill, not the signal",
      abs(p["target"] - round(p["entry_price"] * (1 + tf.target_pct / 100), 2)) < 0.011)
check("…exits are scanned from the next minute on", p["checked_through"] > time.time() - 60)

fresh()
run(PE._open(ST15, inst, 700.0, -1, "bar", turnover_cr=None))
p = closed()
check("a short entry fills below the signal; an unknown name pays the thinnest bucket",
      abs(p["entry_price"] - round(700.0 * (1 - 4 / 1e4), 2)) < 0.011 and p["slippage_bp"] == 4.0)

# ═════════════════════════════════════════════════════════════════════════════════
section("C2 · NO MORE THAN TWO STRATEGIES ON ONE NAME")

others = [s for s in PE.CATALOG if s.strategy_id != ST15.strategy_id][:3]
fresh([pos(strategy_id=others[0].strategy_id), pos(strategy_id=others[1].strategy_id, side="SELL")])
ok = run(PE._open(ST15, inst, 700.0, 1, "bar", turnover_cr=200.0))
check("a third strategy is refused a name two already hold", ok is False)
check("…whatever side the holders are on", len(PE.pattern_positions_collection.docs) == 2)
fresh([pos(strategy_id=others[0].strategy_id)])
check("a second strategy is still allowed",
      run(PE._open(ST15, inst, 700.0, 1, "bar", turnover_cr=200.0)) is True)

# ranking: candidates ordered by target size, not catalog order
by_tf = {}
for s in PE.CATALOG:
    by_tf.setdefault(s.timeframe, s)
ranked = sorted([by_tf["1m"], by_tf["5m"], by_tf["30m"], by_tf["1h"]], key=PE._priority)
check("competing signals are ranked by target size — longer timeframes first",
      [s.timeframe for s in ranked] == ["1h", "30m", "5m", "1m"], [s.timeframe for s in ranked])
check("…so the 1-minute strategies no longer take every slot by being evaluated first",
      ranked[-1].timeframe == "1m")

# ═════════════════════════════════════════════════════════════════════════════════
section("C2 · THE DESK LOSS BREAKER")

PE._hhmm = lambda: "10:00"
loss = -PE.DAILY_LOSS_BREAKER_PCT * PE.TOTAL_CAPITAL - 1
fresh([pos(status="CLOSED", closed_on=TODAY, realized_pnl=loss)])
res = run(PE.scan())
check("past the breaker, the scan opens nothing", res["opened"] == 0 and "BREAKER" in res["notes"][0],
      res["notes"][:1])
fresh([pos(status="CLOSED", closed_on="2020-01-01", realized_pnl=loss)])
check("…and yesterday's loss does not count against today",
      run(PE._today_pnl()) == 0.0)

# ═════════════════════════════════════════════════════════════════════════════════
section("PAPER TRADE BOOKS FOLLOW THE CORRECTED PARENT")

PB.pattern_book_trades_collection = FakeCollection()
PB.pattern_book_positions_collection = FakeCollection([{
    "book": "50k", "strategy_id": ST15.strategy_id, "symbol": "ABDL", "side": "BUY",
    "entry_price": 699.15, "qty": 71, "opened_at": datetime.now(timezone.utc), "status": "OPEN"}])
book = PB.pattern_book_positions_collection.docs[0]
parent = {"exit_price": 705.44, "exit_reason": "target", "opened_on": TODAY, "closed_on": TODAY,
          "exit_basis": "level @ 705.44 (stream minute)"}
run(PB._close_mirror(dict(book), parent))
b = PB.pattern_book_positions_collection.docs[0]
check("a book closes at its parent's corrected price", b["exit_price"] == 705.44)
check("…and now records the day it closed (it never did)", b.get("closed_on") == TODAY)
check("…with the parent's fill basis", b.get("exit_basis") == parent["exit_basis"])
check("…and its blotter row carries the day too",
      PB.pattern_book_trades_collection.docs[0].get("closed_on") == TODAY)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
