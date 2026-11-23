"""Historical replay of the whole morning workflow, day by day, with the SAME engine the live desk runs.

Data (research machine; licensed broker data, never committed):
  5m bars    D:/intraday_ai_data/intraday/5m/*.ibar   (Angel candles, 3 Oct 2024 - 3 Nov 2026, 249 stocks + 19 indices)
  NSE cm     .../intraday/nse/cm/YYYY-MM-DD.json      official close per stock (bhavcopy)
  NSE fo     .../intraday/nse/fo/YYYY-MM-DD.json      F&O underlyings that day (short eligibility)
  news       .../intraday/nse_events/ann/*.json.gz    announcements with exchange timestamps (Nov 2025 onward)

Point in time: a day's context uses only sessions before it; inside the day, bar k is added to the state only when
step(k) runs, exactly as the live feed delivers it, so no screen can read a bar that has not closed.

`build_panel` converts the bar files once into one compact file per day plus each symbol's session aggregates, so
replays stream days from disk (a few MB in memory) instead of holding 10 million bars.
"""
from __future__ import annotations

import gzip
import json
import os
import pickle
from datetime import date, datetime, timedelta

from . import ibar, news
from .config import Settings
from .context import aggregate_session, build_symctx, choose_universe
from .engine import DayEngine, Session
from .sectors import sector_of
from .state import DayState
from .timeutil import IST, bar_index, day_of, at

INDICES = ("NIFTY", "INDIAVIX", "NIFTYBANK", "NIFTYIT", "FINNIFTY", "NIFTYPVTBANK", "NIFTYPSUBANK", "NIFTYAUTO",
           "NIFTYPHARMA", "NIFTYFMCG", "NIFTYMETAL", "NIFTYENERGY", "NIFTYREALTY", "NIFTYINFRA", "NIFTYMEDIA",
           "NIFTYCOMMODITIES", "NIFTYCONSUMPTION", "NIFTYMIDCAP100", "NIFTYNXT50")


def build_panel(src_root: str, out_root: str) -> dict:
    """Bars -> out_root/days/YYYY-MM-DD.pkl.gz ({sym: [(t,o,h,l,c,v), ...]}) and out_root/aggs.pkl."""
    os.makedirs(os.path.join(out_root, "days"), exist_ok=True)
    syms = ibar.symbols(src_root, "5m")
    by_day: dict = {}
    aggs: dict = {}
    for i, sym in enumerate(syms):
        a = ibar.read(src_root, sym, "5m")
        cur, rows = None, []
        out = []

        def flush():
            if rows:
                out.append(aggregate_session(cur, rows))
                by_day.setdefault(cur, {})[sym] = list(rows)

        for t, o, h, l, c, v in zip(a["t"], a["o"], a["h"], a["l"], a["c"], a["v"]):
            k = bar_index(t)
            if k < 0 or k >= 75 or not (l > 0 and h >= l):
                continue
            d = day_of(t)
            if d != cur:
                flush()
                cur, rows = d, []
            rows.append((int(t), float(o), float(h), float(l), float(c), int(v)))
        flush()
        aggs[sym] = [x for x in out if x is not None]
    for d, m in by_day.items():
        with gzip.open(os.path.join(out_root, "days", f"{d.isoformat()}.pkl.gz"), "wb", compresslevel=3) as f:
            pickle.dump(m, f, protocol=pickle.HIGHEST_PROTOCOL)
    with open(os.path.join(out_root, "aggs.pkl"), "wb") as f:
        pickle.dump(aggs, f, protocol=pickle.HIGHEST_PROTOCOL)
    return {"symbols": len(syms), "days": len(by_day)}


class Panel:
    def __init__(self, panel_root: str, data_root: str):
        self.root = panel_root
        self.data = data_root
        with open(os.path.join(panel_root, "aggs.pkl"), "rb") as f:
            self.aggs = pickle.load(f)
        self.days = sorted(date.fromisoformat(fn[:10]) for fn in os.listdir(os.path.join(panel_root, "days")))
        self._cm, self._fo = {}, {}
        self.stocks = sorted(s for s in self.aggs if s not in INDICES)
        self._agg_idx = {s: {a.d: i for i, a in enumerate(v)} for s, v in self.aggs.items()}

    def bars(self, d: date) -> dict:
        with gzip.open(os.path.join(self.root, "days", f"{d.isoformat()}.pkl.gz"), "rb") as f:
            return pickle.load(f)

    def _arch(self, kind: str, d: date) -> dict | None:
        cache = self._cm if kind == "cm" else self._fo
        if d not in cache:
            p = os.path.join(self.data, "nse", kind, f"{d.isoformat()}.json")
            cache[d] = json.load(open(p)) if os.path.exists(p) else None
        return cache[d]

    def official_close(self, d: date, sym: str) -> float | None:
        x = self._arch("cm", d)
        row = (x or {}).get("x", {}).get(sym)
        return float(row[0]) if row and row[0] else None

    def fno(self, d: date) -> set:
        x = self._arch("fo", d)
        return set((x or {}).get("x", {}).keys())

    def announcements(self, prev_day: date, d: date) -> list | None:
        """Material and routine rows disseminated between the previous session's day and d (inclusive).
        None when d's own file is missing (news unavailable that day)."""
        rows, cur = [], prev_day
        have_today = False
        while cur <= d:
            x = news.read_day(self.data, cur)
            if x is not None:
                rows += news.parse_rows(x, set(self.stocks))
                if cur == d:
                    have_today = True
            cur += timedelta(days=1)
        return rows if have_today else None

    def prev_session(self, d: date) -> date | None:
        i = self.days.index(d)
        return self.days[i - 1] if i > 0 else None

    def history(self, sym: str, d: date, n: int = 60) -> list:
        """The symbol's DayAggs strictly before d (last n)."""
        v = self.aggs.get(sym, [])
        lo, hi = 0, len(v)
        while lo < hi:
            mid = (lo + hi) // 2
            if v[mid].d < d:
                lo = mid + 1
            else:
                hi = mid
        return v[max(0, lo - n):lo]


def day_context(panel: Panel, d: date, settings: Settings):
    prev = panel.prev_session(d)
    if prev is None:
        return None
    fno = panel.fno(prev)
    ctxs = {}
    for s in panel.stocks:
        h = panel.history(s, d)
        if not h or h[-1].d != prev:
            continue                       # no bars on the previous session: not tradable today
        sec, idx = sector_of(s)
        c = build_symctx(s, h, panel.official_close(prev, s), s in fno, sec, idx, settings)
        if c is not None:
            ctxs[s] = c
    members, excluded = choose_universe(ctxs, settings)
    index_prev = {}
    for ix in INDICES:
        h = panel.history(ix, d, 1)
        if h and h[-1].d == prev:
            index_prev[ix] = h[-1].c
    return {"prev": prev, "ctx": {s: ctxs[s] for s in members}, "members": members, "excluded": excluded,
            "index_prev": index_prev}


def run(panel: Panel, days: list, strategies: list, settings: Settings, books: dict, portfolio=None,
        eligible: dict | None = None, detail: bool = False, journal: list | None = None,
        on_day=None) -> dict:
    """Replay `days` in order. books: {strategy key -> Book} (persist across days: equity compounds)."""
    log = {"days": 0, "skipped_days": [], "coverage": []}
    for d in days:
        dc = day_context(panel, d, settings)
        if dc is None or not dc["members"]:
            log["skipped_days"].append(str(d))
            continue
        ann = panel.announcements(dc["prev"], d)
        state = DayState(d)
        S = Session(d, dc["ctx"], dc["members"], state, dc["index_prev"], ann, settings)
        for b in list(books.values()) + ([portfolio] if portfolio else []):
            b.start_day(d)
        eng = DayEngine(S, strategies, books, portfolio, eligible=eligible, journal=journal, keep_detail=detail,
                        prev_close_epoch=at(dc["prev"], 15 * 60 + 30))
        bars = panel.bars(d)
        feed_syms = [s for s in dc["members"] + list(INDICES) if s in bars]
        by_k = {}
        for s in feed_syms:
            for b in bars[s]:
                by_k.setdefault(bar_index(b[0]), []).append((s, b))
        for k in range(75):
            for s, b in by_k.get(k, ()):
                state.add(s, b)
            eng.step(k)
        eng.finish()
        log["days"] += 1
        log["coverage"].append((str(d), len(dc["members"]), sum(1 for s in dc["members"] if state.complete(s, 5))))
        if on_day:
            on_day(d, eng)
    return log
