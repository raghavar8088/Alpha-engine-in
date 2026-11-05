"""Offline check of nse_events.catch_up's backfill — no network, a temporary folder.

    python backend/tests/intraday_v2/verify_nse_events_backfill.py

Loads app/services/nse_events.py with a fake NSE and a fake calendar, seeds the store the
way the server held it on 5 Nov 2026 (ban lists back to 19 May, announcements back to 9 Jul
— where the first run's 120-fetch cap left them), then runs ten evenings and checks:
  1. the backfill continues past the seeded days, at most MAX_FETCHES_PER_RUN a run;
  2. it ends at the horizon (730 days of ban lists, 365 of announcements);
  3. a day NSE never serves is asked for on exactly MAX_TRIES_PER_DAY runs, then given up;
  4. a day that failed once is saved on the next run;
  5. a missing day inside the last `days_back` days is retried on every run;
  6. once complete, a run costs only the latest-day files.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import tempfile
import types
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app", "services", "nse_events.py")
TODAY = date(2026, 11, 5)
HOL_2026 = {date(2026, 11, 10)}                           # what the 2026-only list knows
UNLISTED = {date(2025, 10, 2), date(2025, 8, 15), date(2025, 1, 26) + timedelta(days=1),
            date(2024, 12, 25)}                            # 2024-25 holidays: no archive file
ANN_GONE = {date(2026, 2, 2)}                              # never served
ANN_FLAKY = {date(2026, 6, 1)}                             # fails on the first ask only
ANN_RECENT_GONE = {TODAY - timedelta(days=1)}              # inside days_back: always retried


def listed(d: date) -> bool:
    return d.weekday() < 5 and d not in HOL_2026


def next_td(d: date) -> date:
    d = d + timedelta(days=1)
    while not listed(d):
        d += timedelta(days=1)
    return d


class Resp:
    def __init__(self, text: str):
        self.text = text


class FakeNSE:
    def __init__(self):
        self.asks: dict[tuple[str, date], int] = {}
        self.calls = 0

    async def get(self, url, referer=None, tries=4, **_k):
        self.calls += 1
        if url.endswith(("bulk.csv", "block.csv")):
            return Resp("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
                        "Trade Price / Wght. Avg. Price,Remarks\n04-Nov-2026,ABC,Abc Ltd,X,BUY,1000,10.5,-\n")
        d = datetime.strptime(re.search(r"fo_secban_(\d{8})", url).group(1), "%d%m%Y").date()
        self.asks[("ban", d)] = self.asks.get(("ban", d), 0) + 1
        if d in UNLISTED or d > next_td(TODAY):
            return None
        return Resp(f"Securities in Ban For Trade Date {d.strftime('%d-%b-%Y').upper()}:\n1,XYZ\n")

    async def api(self, path, referer):
        self.calls += 1
        d = datetime.strptime(re.search(r"from_date=(\d{2}-\d{2}-\d{4})", path).group(1), "%d-%m-%Y").date()
        n = self.asks[("ann", d)] = self.asks.get(("ann", d), 0) + 1
        if d in ANN_GONE or d in ANN_RECENT_GONE or (d in ANN_FLAKY and n == 1):
            return None
        return [{"symbol": "ABC", "desc": "Outcome of board meeting", "an_dt": d.strftime("%d-%b-%Y") + " 10:00:00"}]


def load(tmp: str, nse: FakeNSE):
    os.environ["INTRADAY_DATA_DIR"] = tmp
    app, services = types.ModuleType("app"), types.ModuleType("app.services")
    cal, client = types.ModuleType("app.services.market_calendar"), types.ModuleType("app.services.nse_client")
    cal.is_listed_trading_day, cal.next_trading_day = listed, next_td
    client.nse = nse
    services.market_calendar = cal
    sys.modules.update({"app": app, "app.services": services, "app.services.market_calendar": cal,
                        "app.services.nse_client": client})
    spec = importlib.util.spec_from_file_location("nse_events_under_test", SRC)
    ne = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ne)

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(TODAY.year, TODAY.month, TODAY.day, 21, 0, tzinfo=IST)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)
    ne.datetime = Fixed
    return ne


def main() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    with tempfile.TemporaryDirectory() as tmp:
        nse = FakeNSE()
        ne = load(tmp, nse)
        # the server's store on 5 Nov 2026
        d = next_td(TODAY)
        while d >= date(2026, 5, 19):
            if listed(d):
                ne._save("ban", d, {"d": d.isoformat(), "symbols": [], "fetched_at": "seed"})
            d -= timedelta(days=1)
        d = date(2026, 11, 3)
        while d >= date(2026, 7, 9):
            ne._save("ann", d, {"d": d.isoformat(), "rows": [], "n": 0, "fetched_at": "seed"})
            d -= timedelta(days=1)
        seeded = {k: ne.coverage()[k]["days"] for k in ("ban", "ann")}

        runs = []
        for _ in range(10):
            before = nse.calls
            res = asyncio.run(ne.catch_up(10))
            runs.append((res, nse.calls - before))
        cov = ne.coverage()
        print("fetches per run:", [n for _r, n in runs])
        print("coverage:", cov)

        check(all(n <= ne.MAX_FETCHES_PER_RUN for _r, n in runs), "no run asks NSE more than the cap")
        check(runs[0][0]["saved"]["ban"] > 100, "the first run continues the ban backfill past the seeded days")
        check(cov["ban"]["days"] > seeded["ban"] + 300 and cov["ann"]["days"] > seeded["ann"] + 200,
              "both kinds fill far beyond where the cap had left them")
        ban_stop, ann_stop = TODAY - timedelta(days=730), TODAY - timedelta(days=365)
        want_ban = {x for x in (ban_stop + timedelta(days=i) for i in range((next_td(TODAY) - ban_stop).days + 1))
                    if listed(x)} - UNLISTED
        have_ban = {date.fromisoformat(x) for x in ne._days_stored("ban")}
        check(want_ban <= have_ban, f"every servable ban day back to {ban_stop} is stored")
        want_ann = {ann_stop + timedelta(days=i) for i in range((TODAY - ann_stop).days)} - ANN_GONE - ANN_RECENT_GONE
        have_ann = {date.fromisoformat(x) for x in ne._days_stored("ann")}
        check(want_ann <= have_ann, f"every servable announcement day back to {ann_stop} is stored")
        in_range = {x for x in UNLISTED if x >= ban_stop}
        check(all(nse.asks.get(("ban", x)) == ne.MAX_TRIES_PER_DAY for x in in_range),
              f"each unlisted holiday is asked for exactly {ne.MAX_TRIES_PER_DAY} times")
        check(nse.asks.get(("ann", min(ANN_GONE))) == ne.MAX_TRIES_PER_DAY,
              f"an announcement day NSE never serves is given up after {ne.MAX_TRIES_PER_DAY} runs")
        check(cov["ban"]["given_up"] == len(in_range) and cov["ann"]["given_up"] == len(ANN_GONE),
              "status reports the given-up days")
        check(min(ANN_FLAKY) in have_ann and nse.asks.get(("ann", min(ANN_FLAKY))) == 2,
              "a day that failed once is saved on the next run")
        check(nse.asks.get(("ann", min(ANN_RECENT_GONE))) == len(runs),
              "a missing day inside days_back is retried on every run")
        check(runs[-1][1] <= 4, f"a run after completion costs only the latest-day files ({runs[-1][1]} requests)")
        check(not any(f.endswith(".tmp") for _r, _d, fs in os.walk(tmp) for f in fs), "no temporary files left")

    print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
