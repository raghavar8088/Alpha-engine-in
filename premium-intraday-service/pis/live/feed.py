"""Everything the desk reads, and only reads.

  backend (internal compose network, read-only routes in backend/app/api/routes/premium_intraday.py)
    /api/premium-intraday/feed/bars?since=   today's closed five-minute bars from the bar store's memory
    /api/premium-intraday/feed/quotes        the stream's day open / previous close / LTP (09:15 snapshot)
    /api/premium-intraday/feed/context       stored results calendar, morning brief, stored intraday universe
  files on the shared bar volume, mounted READ-ONLY at /data/intraday
    5m/<SYM>.ibar                           history (finished sessions; flushed by the backend at 15:40)
    nse/cm/<prev>.json, nse/fo/<prev>.json  official previous close; F&O underlyings (short eligibility)
    nse_events/ann/<day>.json.gz            NSE announcements with exchange dissemination times

No broker client exists in this package; the desk never asks any module to scan, refresh, backtest or approve.
Every read reports when it was made and what it returned, so the journal can say what the desk knew.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from .. import ibar, news
from ..context import aggregate_session
from ..timeutil import IST

log = logging.getLogger("pis.feed")


class Feed:
    def __init__(self, backend: str, secret: str, data_root: str, timeout: float = 20.0):
        self.backend = backend.rstrip("/")
        self.secret = secret
        self.root = data_root
        self.timeout = timeout
        self.stats = {"calls": 0, "errors": 0, "last_error": None, "last_ok": None, "bytes": 0}

    # ── backend ─────────────────────────────────────────────────────────────────
    def _get(self, path: str, **params):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(self.backend + path + q,
                                     headers={"x-app-secret": self.secret} if self.secret else {})
        self.stats["calls"] += 1
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
            self.stats["bytes"] += len(raw)
            self.stats["last_ok"] = time.time()
            out = json.loads(raw)
            out["_fetched_at"] = time.time()
            out["_seconds"] = round(time.time() - t0, 3)
            return out
        except Exception as exc:  # noqa: BLE001 - any failure: report it, the caller marks the input unavailable
            self.stats["errors"] += 1
            self.stats["last_error"] = f"{path}: {type(exc).__name__}: {exc}"[:300]
            log.warning("feed %s failed: %s", path, exc)
            return None

    def bars_since(self, since: int):
        return self._get("/api/premium-intraday/feed/bars", since=int(since))

    def quotes(self):
        return self._get("/api/premium-intraday/feed/quotes")

    def context(self, day: date):
        return self._get("/api/premium-intraday/feed/context", day=day.isoformat())

    # ── files (read-only volume) ───────────────────────────────────────────────
    def symbols(self) -> list[str]:
        return ibar.symbols(self.root, "5m")

    def history(self, symbol: str, before: date, n: int = 61, sparse: bool = False):
        """The symbol's last n finished sessions before `before`, as DayAggs; with sparse=True also the rows the
        Stock Momentum scan reads (each session's first three bars and its last bar). One read of the file; the
        tail is found by binary search and sessions are split on integer day keys (no datetime per bar)."""
        from bisect import bisect_left
        a = ibar.read(self.root, symbol, "5m")
        t = a["t"]
        if not len(t):
            return ([], []) if sparse else []
        end_t = int(datetime(before.year, before.month, before.day, tzinfo=IST).timestamp())
        hi = bisect_left(t, end_t)
        lo = bisect_left(t, end_t - int(n * 1.6 + 14) * 86400)  # n sessions fit in ~1.4n calendar days + holidays
        by_day, order = {}, []
        for ti, oi, hi_, li, ci, vi in zip(t[lo:hi], a["o"][lo:hi], a["h"][lo:hi], a["l"][lo:hi], a["c"][lo:hi],
                                           a["v"][lo:hi]):
            dk = (ti + 19800) // 86400
            k = (ti + 19800) % 86400 // 300 - 111                  # 09:15 IST = 33300 s = bar 111 of the day
            if 0 <= k < 75 and li > 0 and hi_ >= li:
                row = by_day.get(dk)
                if row is None:
                    row = by_day[dk] = []
                    order.append(dk)
                row.append((ti, oi, hi_, li, ci, vi))
        keep = order[-n:]
        aggs = []
        for dk in keep:
            x = aggregate_session(date.fromordinal(date(1970, 1, 1).toordinal() + dk), by_day[dk])
            if x is not None:
                aggs.append(x)
        if not sparse:
            return aggs
        rows = []
        for dk in order[-22:]:
            r = by_day[dk]
            rows += [b for b in r if (b[0] + 19800) % 86400 // 300 - 111 < 3]
            if (r[-1][0] + 19800) % 86400 // 300 - 111 >= 3:
                rows.append(r[-1])
        return aggs, rows

    def _arch(self, kind: str, d: date):
        p = os.path.join(self.root, "nse", kind, f"{d.isoformat()}.json")
        if not os.path.exists(p):
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def official_closes(self, d: date) -> dict | None:
        x = self._arch("cm", d)
        if x is None:
            return None
        return {s: float(v[0]) for s, v in x.get("x", {}).items() if v and v[0]}

    def fno(self, d: date) -> set | None:
        x = self._arch("fo", d)
        return set(x.get("x", {}).keys()) if x is not None else None

    def announcements(self, prev_day: date, day: date, symbols: set) -> list | None:
        rows, cur, have_today = [], prev_day, False
        while cur <= day:
            x = news.read_day(self.root, cur)
            if x is not None:
                rows += news.parse_rows(x, symbols)
                have_today = have_today or cur == day
            cur += timedelta(days=1)
        return rows if have_today else None
