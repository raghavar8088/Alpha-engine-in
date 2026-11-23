"""Test harness: a feed that serves a recorded day bar by bar on a simulated clock, and a MongoDB recorder.

FakeFeed subclasses the real Feed, so history, official closes, F&O lists and announcements are read by the SAME
file code the container runs (from the research copy of the bar volume); only the backend calls are simulated, from
the day's recorded five-minute bars, released when the simulated clock passes each bar's close + 5 s (as the
stream emits them).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = os.path.dirname(HERE)
ROOT = os.path.dirname(SERVICE)
for p in (SERVICE, os.path.join(ROOT, "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)

from pis.live.feed import Feed  # noqa: E402
from pis.timeutil import IST, bar_index, open_epoch  # noqa: E402

DATA = os.getenv("PIS_RESEARCH_DATA", "D:/intraday_ai_data/intraday")
PANEL = os.getenv("PIS_PANEL", "D:/premium_intraday_data/panel")


def have_data() -> bool:
    return os.path.isdir(os.path.join(DATA, "5m")) and os.path.isdir(os.path.join(PANEL, "days"))


class SimClock:
    def __init__(self, d: date, hh: int, mm: int, ss: int = 0):
        self.t = datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=IST).timestamp()

    def now(self) -> float:
        return self.t

    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.t, IST)

    def set(self, hh, mm, ss=0):
        d = self.dt()
        self.t = datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=IST).timestamp()


class FakeFeed(Feed):
    def __init__(self, day: date, clock: SimClock, panel_bars: dict, drop: dict | None = None,
                 outage: tuple | None = None, duplicate: bool = False):
        super().__init__("http://backend.invalid", "", DATA)
        self.day, self.clock, self.bars = day, clock, panel_bars
        self.drop = drop or {}          # {symbol: from_bar_index}: that stock's bars stop arriving
        self.outage = outage            # (from_epoch, to_epoch): the backend does not answer
        self.duplicate = duplicate
        self.urls = []

    def _down(self) -> bool:
        return bool(self.outage) and self.outage[0] <= self.clock.now() < self.outage[1]

    def bars_since(self, since: int):
        self.urls.append(("/api/premium-intraday/feed/bars", since))
        self.stats["calls"] += 1
        if self._down():
            self.stats["errors"] += 1
            self.stats["last_error"] = "simulated backend outage"
            return None
        now = self.clock.now()
        out = {}
        for sym, rows in self.bars.items():
            cut = self.drop.get(sym, 99)
            got = [list(r) for r in rows if r[0] >= since and r[0] + 305 <= now and bar_index(r[0]) < cut]
            if got:
                out[sym] = got + (got if self.duplicate else [])
        return {"ok": True, "now": now, "bars": out, "_fetched_at": now, "_seconds": 0.0, "stream": {"connected": True}}

    def quotes(self):
        self.urls.append(("/api/premium-intraday/feed/quotes", None))
        if self._down():
            return None
        q = {s: {"open": rows[0][1], "ltp": rows[0][1]} for s, rows in self.bars.items()
             if rows and bar_index(rows[0][0]) == 0}
        return {"ok": True, "quotes": q, "_fetched_at": self.clock.now()}

    def context(self, day):
        self.urls.append(("/api/premium-intraday/feed/context", str(day)))
        return None if self._down() else {"day": str(day), "results": {}, "brief": None, "universe": None}


class Recorder:
    """Wraps a (mongomock) client; records (db, collection, method) for every call."""

    WRITES = {"insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many",
              "bulk_write", "create_index", "drop", "find_one_and_update", "find_one_and_replace",
              "find_one_and_delete"}

    def __init__(self, client):
        self._client = client
        self.calls = []

    def __getitem__(self, db_name):
        return _DB(self, self._client[db_name], db_name)

    def writes(self):
        return [c for c in self.calls if c[2] in self.WRITES]


class _DB:
    def __init__(self, rec, db, name):
        self._rec, self._db, self._name = rec, db, name

    def __getitem__(self, coll):
        return _Coll(self._rec, self._db[coll], self._name, coll)

    def __getattr__(self, coll):
        if coll.startswith("_"):
            raise AttributeError(coll)
        return self[coll]


class _Coll:
    def __init__(self, rec, coll, db, name):
        self._rec, self._c, self._db, self._name = rec, coll, db, name

    def __getattr__(self, method):
        fn = getattr(self._c, method)

        def call(*a, **kw):
            self._rec.calls.append((self._db, self._name, method))
            return fn(*a, **kw)
        return call
