"""Verify the Stock Momentum Trading desk's cycle (app.services.screener.morning_desk.tick) offline. No network.

Run:  python backend/tests/screener/verify_morning_desk.py

The clock, the quotes, the five-minute bars, the 09:30 scan and the book's Mongo document are faked; the desk's own
exit, rescan and entry-gate code runs as is. What must hold (21 Nov 2026):
* EXITS do not need the five-second quote ENTRIES need: a stop or target is judged on a quote up to a minute old,
  a due position (15:10) on any quote from the last 15 minutes, and 10 minutes past the deadline with no quote at
  all it closes at its last stored five-minute close. A position left from an earlier session closes at its last
  close before its own square-off, never at today's price. Each close records its exit, why and on what price.
* The 09:30 board is scanned again, at most once a minute until 09:45, while stocks still lack opening bars.
* Main Control OFF (a draining cycle): open positions are still closed, nothing new is opened.
* The module is its own Main Control entry: /api/screener/morning resolves to it, its page is /stock-momentum,
  OFF drains, and open_count() counts every universe's open positions.
"""

import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"   # never the real cluster
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "shared"))
sys.path.insert(0, str(ROOT))

from app.services import desk_switches as sw  # noqa: E402
from app.services.module_registry import REGISTRY, pages_for, resolve  # noqa: E402
from app.services.screener import morning_desk as M  # noqa: E402

IST = M.m.store.IST
FAILS: list[str] = []
N = [0]


def check(cond, msg, detail=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + msg + ("" if cond else f"  -- {detail}"))
    if not cond:
        FAILS.append(msg)


class Coll:
    """Just enough of a Motor collection for the desk's book document: $set, $inc, a revision filter, upsert."""

    def __init__(self, docs=()):
        self.docs = {d["_id"]: dict(d) for d in docs}

    async def find_one(self, q):
        d = self.docs.get(q["_id"])
        return dict(d) if d else None

    def find(self, q, projection=None):
        rx = re.compile(q["_id"]["$regex"])
        docs = [dict(d) for k, d in self.docs.items() if rx.search(k)]

        async def gen():
            for d in docs:
                yield d
        return gen()

    async def update_one(self, q, upd, upsert=False):
        d = self.docs.get(q["_id"])
        if d is None:
            if not upsert:
                return
            d = self.docs[q["_id"]] = {"_id": q["_id"]}
        if "revision" in q and d.get("revision") != q["revision"]:
            return
        for k, v in (upd.get("$set") or {}).items():
            d[k] = v
        for k, v in (upd.get("$inc") or {}).items():
            d[k] = (d.get(k) or 0) + v


class Universe:
    def __init__(self, members):
        self.members = members

    def find(self, q, projection=None):
        async def gen():
            for s, sec in self.members.items():
                yield {"symbol": s, "sector": sec}
        return gen()


DAY = datetime(2026, 11, 23, tzinfo=IST)              # a Monday
START = int(DAY.replace(hour=9, minute=15).timestamp())
DEADLINE = START + 21300                              # 15:10
CLOCK = [DAY]


class FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return CLOCK[0]


def at(h, mi, s=0):
    CLOCK[0] = DAY.replace(hour=h, minute=mi, second=s)
    return CLOCK[0]


QUOTES: dict[str, tuple[float, int]] = {}             # symbol -> (ltp, age in seconds)
BARS: dict[str, M.m.store.Bars] = {}


async def fake_quotes(symbols):
    out = {}
    for s in symbols:
        if s in QUOTES:
            ltp, age = QUOTES[s]
            out[s] = {"ltp": ltp, "trade_time": datetime.fromtimestamp(CLOCK[0].timestamp() - age, IST)
                      .strftime("%d-%b-%Y %H:%M:%S")}
    return out


def bars(sym, closes, first=START):
    b = M.m.store.Bars.from_rows((first + 300 * k, c, c + 1, c - 1, c, 1000, 1) for k, c in enumerate(closes))
    BARS[sym] = b
    return b


def pos(sym, side=1, entry=100.0, stop=99.0, target=102.0, qty=50, deadline=DEADLINE, rule="orb15"):
    return {"symbol": sym, "rule": rule, "side": side, "entry": entry, "qty": qty, "stop": stop, "target": target,
            "id": f"x/{sym}/{rule}", "opened": "2026-11-23T10:00:00+05:30", "deadline": deadline}


SCANS: list[float] = []
SCAN_OUT = [([], {})]


def fake_scan(start, members, load):
    SCANS.append(CLOCK[0].timestamp())
    return SCAN_OUT[0]


TRIGGER_CALLS: list[str] = []


def fake_triggers(row, bars_):
    TRIGGER_CALLS.append(row["symbol"])
    return []


def book(**kw):
    d = {"_id": M.key("nifty50"), "scan": True, "paper": False, "approved": [], "positions": [], "recent": [],
         "revision": 1, "board": {"day": DAY.date().isoformat(), "rows": [{"symbol": "ZZZ"}], "excluded": {},
                                  "scanned_at": START + 900}}
    d.update(kw)
    M.db = Coll([d])
    return M.db


async def tick():
    await M.tick("nifty50", CLOCK[0])
    return M.db.docs[M.key("nifty50")]


async def main():
    M.datetime = FakeDT
    M._live_quotes = fake_quotes
    M.m.store.store5.get = lambda sym: BARS.get(sym) or M.m.store.Bars()
    M.m.scan = fake_scan
    M.m.triggers = fake_triggers
    M.market_calendar.in_session = lambda now: True
    M.stock_universe_collection = Universe({"AAA": "Bank", "BBB": "Bank"})

    async def elig():
        return {"AAA", "BBB", "ZZZ"}, {"AAA"}
    M._eligible_symbols = elig

    print("\n1. Exits judge a stop or target on a quote up to a minute old (entries still need five seconds)")
    at(11, 0)
    bars("AAA", [100.0] * 20)
    book(positions=[pos("AAA")])
    QUOTES.clear(); QUOTES["AAA"] = (98.5, 40)               # through the 99 stop, quote 40 s old
    d = await tick()
    r = (d["recent"] or [{}])[-1]
    check(not d["positions"] and r.get("why") == "stop" and r.get("basis") == "quote",
          "a 40-second-old quote through the stop closes the position (before: held until a 5 s quote)", d)
    check(r.get("exit") == round(98.5 * (1 - .0005), 4) and r.get("net") is not None and r["net"] < 0,
          "the close records its exit price (5 bp slippage) and its net after costs", r)
    book(positions=[pos("AAA")])
    QUOTES["AAA"] = (98.5, 120)                               # two minutes old: too old to judge a stop
    d = await tick()
    check(len(d["positions"]) == 1 and not d["recent"], "a two-minute-old quote does not close it before 15:10", d)
    book(positions=[pos("AAA")])
    QUOTES["AAA"] = (102.6, 10)
    d = await tick()
    check(not d["positions"] and d["recent"][-1]["why"] == "target" and d["recent"][-1]["net"] > 0,
          "a fresh quote through the target closes it as a target", d["recent"])

    print("\n2. At the 15:10 square-off: any quote from the last 15 minutes, then the last stored close")
    at(15, 11)
    book(positions=[pos("AAA")])
    QUOTES["AAA"] = (100.4, 600)                              # ten minutes old
    d = await tick()
    check(not d["positions"] and d["recent"][-1]["why"] == "square-off" and d["recent"][-1]["basis"] == "quote",
          "due at 15:10: a ten-minute-old quote squares it off", d["recent"])
    at(15, 15)
    book(positions=[pos("AAA")])
    QUOTES.clear()
    d = await tick()
    check(len(d["positions"]) == 1 and "x/AAA/orb15" in d["failed"],
          "15:15 with no quote at all: still held, listed as a missed square-off", d)
    at(15, 21)
    closes = [100.0 + k * 0.1 for k in range(72)]
    bars("AAA", closes)
    d = await tick()
    last = closes[(DEADLINE - 300 - START) // 300]
    r = d["recent"][-1] if d["recent"] else {}
    check(not d["positions"] and r.get("basis", "").startswith("last 5-minute close") and r.get("why") == "square-off"
          and r.get("exit") == round(last * (1 - .0005), 4),
          "15:21 and still no quote: closed at its last stored five-minute close before 15:10", r)

    print("\n3. A position left from an earlier session closes at its own square-off price, never today's")
    at(9, 31)
    yday = START - 86400 * 3                                   # the Friday before
    bars("AAA", [90.0 + k * 0.1 for k in range(72)], first=yday)
    book(positions=[pos("AAA", deadline=yday + 21300)])
    QUOTES["AAA"] = (150.0, 1)                                 # a fresh quote on Monday morning: must not be used
    d = await tick()
    r = d["recent"][-1] if d["recent"] else {}
    want = 90.0 + ((21300 - 300) // 300) * 0.1
    check(not d["positions"] and abs(r.get("exit", 0) - round(want * (1 - .0005), 4)) < 1e-6
          and "before its square-off" in r.get("basis", ""),
          "Friday's position: closed at Friday's 15:05 bar close (about 97.0), not Monday's 150", r)

    print("\n4. The 09:30 board is scanned again while stocks still lack opening bars (once a minute, until 09:45)")
    SCANS.clear()
    SCAN_OUT[0] = ([{"symbol": "AAA", "rank": 1, "side": 1}], {"BBB": M.MISSING_OPEN})
    at(9, 30, 2)
    book(board={})
    await tick()
    check(len(SCANS) == 1, "09:30:02: the first scan of the day", SCANS)
    at(9, 30, 40)
    await tick()
    check(len(SCANS) == 1, "09:30:40: BBB still lacks its opening bars, but under a minute since: no rescan", SCANS)
    at(9, 31, 5)
    d = await tick()
    check(len(SCANS) == 2 and d["board"]["scanned_at"] == CLOCK[0].timestamp(),
          "09:31:05: rescanned, because BBB was missing its opening bars", SCANS)
    SCAN_OUT[0] = ([{"symbol": "AAA", "rank": 1, "side": 1}, {"symbol": "BBB", "rank": 2, "side": 1}], {})
    at(9, 32, 10)
    await tick()
    at(9, 33, 20)
    await tick()
    check(len(SCANS) == 3, "complete at 09:32: no further rescans", SCANS)
    SCAN_OUT[0] = ([{"symbol": "AAA", "rank": 1, "side": 1}], {"BBB": M.MISSING_OPEN})
    book(board={"day": DAY.date().isoformat(), "rows": [{"symbol": "AAA"}], "excluded": {"BBB": M.MISSING_OPEN},
                "scanned_at": START + 1700})
    at(9, 46)
    await tick()
    check(len(SCANS) == 3, "09:46: the board is frozen for the day, even if a stock never got its bars", SCANS)
    book(board={"day": "2026-11-20", "rows": [{"symbol": "AAA"}], "excluded": {}, "scanned_at": START - 86400})
    at(9, 30, 5)
    await tick()
    check(len(SCANS) == 4, "a board from an earlier day is always replaced", SCANS)

    print("\n5. Main Control OFF (a draining cycle): exits still happen, no entry is looked for")
    at(11, 0)
    row = {"symbol": "BBB", "side": 1, "rank": 1, "turnover": 5e7, "gap": 0.2, "prev": 99.0, "volume": 2,
           "market": 1, "relative": 1, "change": 1, "vwap": 1}
    bars("BBB", [100.0] * 30)
    bars("AAA", [100.0] * 30)
    QUOTES.clear(); QUOTES["AAA"] = (98.5, 2); QUOTES["BBB"] = (100.0, 1)
    TRIGGER_CALLS.clear()
    book(paper=True, approved=["orb15"], positions=[pos("AAA")],
         board={"day": DAY.date().isoformat(), "rows": [row], "excluded": {}, "scanned_at": START + 900})
    token = sw._DRAINING.set("stock_momentum")
    try:
        d = await tick()
    finally:
        sw._DRAINING.reset(token)
    check(not d["positions"] and d["recent"][-1]["why"] == "stop" and TRIGGER_CALLS == [],
          "OFF with an open position: it is stopped out, and no entry trigger is even evaluated", (d, TRIGGER_CALLS))
    book(paper=True, approved=["orb15"], positions=[],
         board={"day": DAY.date().isoformat(), "rows": [row], "excluded": {}, "scanned_at": START + 900})
    await tick()
    check(TRIGGER_CALLS == ["BBB"], "ON (outside the drain): the same board's entries are evaluated", TRIGGER_CALLS)

    print("\n6. Its own Main Control module")
    m = REGISTRY.get("stock_momentum")
    check(m is not None and m.href == "/stock-momentum" and m.drains
          and m.positions == ("app.services.screener.morning_desk:open_count",),
          "registered: page /stock-momentum, OFF drains, its open-position probe", m)
    check(resolve("/api/screener/morning/nifty500") == "stock_momentum" and resolve("/api/screener/summary") == "screener",
          "its API is its own (the longer prefix wins); the rest of /api/screener stays the Stock Screener's")
    check("stock_momentum" in pages_for("/stock-momentum") and "stock_momentum" not in pages_for("/stock-screener"),
          "its switch shows on its own page, not on the Stock Screener's")
    M.db = Coll([{"_id": M.key("nifty50"), "positions": [pos("AAA"), pos("BBB")]},
                 {"_id": M.key("nifty500"), "positions": [pos("CCC")]}, {"_id": "other-doc", "positions": [pos("X")]}])
    check(await M.open_count() == 3, "open_count(): every universe's open positions, nothing else", await M.open_count())
    check(await sw._count("app.services.screener.morning_desk:open_count") == 3,
          "Main Control's probe reads it through the registry reference")

    print("\n" + (f"{len(FAILS)} FAILED of {N[0]}" if FAILS else f"all {N[0]} checks passed"))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
