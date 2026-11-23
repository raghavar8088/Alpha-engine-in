"""The forward paper desk's scheduler. One process, its own container, IST clock, the NSE trading calendar.

  08:40     PRE: universe, previous closes, F&O list, announcements, the stored results calendar and morning brief;
            every input is recorded with its status (ok / missing / stale) and when it arrived
  09:15:30  the 09:15 snapshot from the stream's opening quotes
  each five-minute bar close + ~20 s
            today's new bars from the backend's memory -> DayEngine.step(k): 09:20, 09:30, 09:40 screens, the 09:45
            plan, then triggers, entries, exits; the bar is stepped once 80% of the universe has it, or 90 s late
  15:05 / 15:10  square-off, retry; anything still open is a FAILED EXIT with an alert
  15:31     the day is closed; books and the strategy registry's forward numbers are updated

The module's switch (its own database) is read every cycle: OFF stops new scans and entries; exits continue.
A restart mid-session restores today's positions from the store and replays today's bars without entering anything
in the past; exits that fell in the gap are applied and flagged late.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
try:
    import resource
except ImportError:  # Windows (local tests)
    resource = None
import time
import traceback
from dataclasses import fields as dc_fields
from datetime import date, datetime, timedelta, timezone

from .. import VERSION
from ..book import Book, Position
from ..config import Risk, Settings
from ..context import build_symctx, choose_universe
from ..engine import DayEngine, PLAN_K, Session
from ..sectors import sector_map, sector_of
from ..state import DayState
from ..strategies import REGISTRY
from ..timeutil import IST, at, bar_close, bar_index, hhmm, now_ist, open_epoch
from .feed import Feed
from .observers import MorningObserver, TournamentObserver
from .store import LedgerReader, Store

log = logging.getLogger("pis.worker")
INDICES = ("NIFTY", "INDIAVIX", "NIFTYBANK", "NIFTYIT", "FINNIFTY", "NIFTYPVTBANK", "NIFTYPSUBANK", "NIFTYAUTO",
           "NIFTYPHARMA", "NIFTYFMCG", "NIFTYMETAL", "NIFTYENERGY", "NIFTYREALTY", "NIFTYINFRA", "NIFTYMEDIA",
           "NIFTYCOMMODITIES", "NIFTYCONSUMPTION", "NIFTYMIDCAP100", "NIFTYNXT50")
PRE_AT = (8, 40)
READY_SHARE = 0.80
LATE_S = 90
POLL_OFFSET_S = 20


def trading_day(d: date) -> bool:
    try:
        from tradingai_shared.nse_calendar import is_listed_trading_day
        return is_listed_trading_day(d)
    except Exception:  # noqa: BLE001 - the shared list missing: weekdays, and the day's bars decide
        return d.weekday() < 5


def live_config() -> dict:
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "live_config.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _rid(row: dict) -> str:
    keep = {k: row.get(k) for k in ("day", "k", "kind", "stage", "book", "strategy", "variant", "level", "symbol", "side",
                                    "status", "why", "reason", "qty")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _pday(p) -> str:
    """Positions are named <book>|<day>|<n> and book names contain '|': the day is the second-to-last part."""
    parts = str(p.pid).rsplit("|", 2)
    return parts[-2] if len(parts) == 3 else ""


def _pos_from(doc: dict) -> Position:
    names = {f.name for f in dc_fields(Position)}
    d = {k: v for k, v in doc.items() if k in names}
    d["pid"] = doc["_id"]
    d.setdefault("knew", {})
    return Position(**d)


class DayRun:
    def __init__(self, d: date, feed: Feed, store: Store, settings: Settings, cfg: dict, ledger=None,
                 morning_path: str | None = None):
        self.d, self.feed, self.store, self.S, self.cfg = d, feed, store, settings, cfg
        self.ledger = ledger
        self.morning_path = morning_path
        self.state = DayState(d)
        self.engine = None
        self.session = None
        self.last_t = 0
        self.persisted = 0
        self.inputs = {}
        self.coverage = []
        self.observers = []
        self.done = False
        self._saved_pos = {}          # pid -> status last written
        self._book_sig = {}           # book -> signature last written
        self._once_done = set()       # checkpoint keys already written this process
        self._sparse_rows = {}

    # ── PRE ─────────────────────────────────────────────────────────────────────
    def prepare(self) -> None:
        d, S, feed = self.d, self.S, self.feed
        t0 = time.time()
        syms = feed.symbols()
        stocks = [s for s in syms if s not in INDICES]
        nifty = feed.history("NIFTY", d, 2)
        prev = nifty[-1].d if nifty else None
        self.inputs["bars_history"] = {"status": "ok" if prev else "missing", "files": len(syms), "prev_session": str(prev),
                                       "asof": time.time()}
        closes = feed.official_closes(prev) if prev else None
        self.inputs["official_close"] = {"status": "ok" if closes else "missing (last bar close used)",
                                         "file": f"nse/cm/{prev}.json"}
        fno = feed.fno(prev) if prev else None
        self.inputs["fno_list"] = {"status": "ok" if fno else "missing (no shorts today)", "count": len(fno or ())}
        ctxs, sparse = {}, {}
        for s in stocks:
            h, sp = feed.history(s, d, 61, sparse=True)     # one read per file: history aggregates + scan rows
            sparse[s] = sp
            if not h or h[-1].d != prev:
                continue
            sec, idx = sector_of(s)
            c = build_symctx(s, h, (closes or {}).get(s), s in (fno or set()), sec, idx, S)
            if c is not None:
                ctxs[s] = c
        members, excluded = choose_universe(ctxs, S)
        index_prev = {}
        for ix in INDICES:
            h, sp = feed.history(ix, d, 1, sparse=True)
            if ix == "NIFTY":
                sparse[ix] = sp
            if h and h[-1].d == prev:
                index_prev[ix] = h[-1].c
        self._sparse_rows = sparse
        ann = feed.announcements(prev, d, set(stocks)) if prev else None
        self.inputs["announcements"] = {"status": "ok" if ann is not None else "not yet available (re-read at 09:40)",
                                        "rows": len(ann or []), "material": sum(1 for a in ann or [] if a["material"])}
        ctx_doc = feed.context(d)
        self.inputs["results_calendar"] = {"status": "ok" if ctx_doc and ctx_doc.get("results") is not None else "missing",
                                           "names": len((ctx_doc or {}).get("results") or {})}
        self.inputs["morning_brief"] = {"status": "ok" if ctx_doc and ctx_doc.get("brief") else "missing",
                                        "gap_forecast": ((ctx_doc or {}).get("brief") or {}).get("gap_forecast")}
        self.inputs["backend"] = {"status": "ok" if ctx_doc else "unreachable"}
        self.session = Session(d, {s: ctxs[s] for s in members}, members, self.state, index_prev, ann, S)
        self.prev = prev
        self._build_engine()
        pre = {"stage": "PRE", "computed_at": time.time(), "seconds": round(time.time() - t0, 1),
               "universe": len(members), "excluded": dict(list(excluded.items())[:60]),
               "excluded_count": len(excluded), "inputs": self.inputs, "prev_session": str(prev),
               "results_today": sorted(((ctx_doc or {}).get("results") or {}).keys())[:60],
               "catalysts": {s: [{"desc": a["desc"], "at": a["at"]} for a in v][:3]
                             for s, v in self.session.catalysts.items()} if ann else {},
               "global": (ctx_doc or {}).get("brief"),
               "members": [{"symbol": s, "sector": ctxs[s].sector, "band": ctxs[s].band, "prev_close": ctxs[s].prev_close,
                            "atr_pct": round(ctxs[s].atr_pct, 3), "fno": ctxs[s].fno, "nr7": ctxs[s].nr7} for s in members]}
        self.store.set_day(str(d), {"checkpoints.PRE": pre, "status": "prepared",
                                    "version": VERSION, "config": {"risk": S.risk.as_dict()}}, once=("checkpoints.PRE",))
        self._restore_if_restart()
        self._persist()
        log.info("PRE %s: universe %d, prev %s, %.1fs", d, len(members), prev, time.time() - t0)

    def _build_engine(self) -> None:
        S = self.S
        strats, books = [], {}
        for spec in self.cfg["strategies"]:
            st = REGISTRY[spec["sid"]](level=spec["level"], target_R=spec["target_R"])
            st.sides = tuple(spec["sides"])
            strats.append(st)
            key = f"{st.id}|{st.variant}|{st.level}"
            books[key] = self._book(key)
        port = self._book("portfolio")
        eligible = {k: v for k, v in self.cfg.get("eligible", {}).items()}
        self.engine = DayEngine(self.session, strats, books, port, eligible=eligible, journal=[], keep_detail=True,
                                prev_close_epoch=at(self.prev, 15 * 60 + 30) if self.prev else None)
        # imported top 25, observation only
        imp = self.cfg.get("imported", {})
        jr = self.engine.journal
        if imp.get("morning_rules") and self.morning_path:
            mbooks = {f"SM:{r}": self._book(f"SM:{r}") for r in imp["morning_rules"]}
            industry = {s: (sector_map().get(s) or {}).get("industry") for s in self.session.members}
            sparse = {s: self._sparse_rows.get(s, []) for s in self.session.members + ["NIFTY"]}
            self.observers.append(MorningObserver(self.morning_path, [f"SM:{r}" for r in imp["morning_rules"]], mbooks, jr,
                                                  self.d, self.session.members, self.session.ctx, industry, sparse))
        if imp.get("tournament"):
            tbooks = {sid: self._book(sid) for sid in imp["tournament"]}
            self.observers.append(TournamentObserver(self.ledger, imp["tournament"], tbooks, jr, self.d, self.session.ctx))

    def _book(self, name: str) -> Book:
        b = Book(name, self.S.risk)
        st = self.store.book_state(name) or {}
        if st.get("day") == str(self.d):
            b.equity = float(st.get("day_start", b.equity))      # a restart today: start from the morning's equity
        elif st.get("equity") is not None:
            b.equity = float(st["equity"])
        b.start_day(str(self.d))
        return b

    def _all_books(self):
        bs = list(self.engine.books.values()) + [self.engine.portfolio]
        for o in self.observers:
            bs += list(o.books.values())
        return bs

    # ── restart ─────────────────────────────────────────────────────────────────
    def _restore_if_restart(self) -> None:
        day = self.store.day(str(self.d)) or {}
        done = (day.get("progress") or {}).get("done_k", -1)
        mins = (now_ist().hour * 60 + now_ist().minute)
        if done < 0 and mins < 9 * 60 + 20:
            return
        pos = self.store.positions({"day": str(self.d)})
        by_book = {}
        for doc in pos:
            by_book.setdefault(doc["book"], []).append(_pos_from(doc))
        for b in self._all_books():
            ps = by_book.get(b.name, [])
            opn = [p for p in ps if p.status == "OPEN"]
            cls = [p for p in ps if p.status != "OPEN"]
            have = {p.pid for p in b.open} | {p.pid for p in b.closed}
            b.open += [p for p in opn if p.pid not in have]
            b.closed += [p for p in cls if p.pid not in have]
            b.day_realized = sum(p.net or 0 for p in b.closed)
            b.equity = b.day_start + b.day_realized
        for r in self.store.journal_keys(str(self.d)):
            side = 1 if r.get("side") == "LONG" else -1
            self.engine.consumed.add(f"{r.get('strategy')}|{r.get('variant')}|{r.get('level')}|{r.get('symbol')}|{side}")
        k_now = max(-1, min(74, (mins - (9 * 60 + 15)) // 5 - 1))
        self.engine.resume_k = k_now + 1
        self.store.set_day(str(self.d), {"restarted_at": time.time(), "restart_resume_k": k_now + 1})
        log.warning("restart on %s: restored %d positions, resume at bar %d", self.d, len(pos), k_now + 1)

    # ── session ─────────────────────────────────────────────────────────────────
    def snapshot_0915(self) -> None:
        if not self.engine.scanning or "0915" in self.engine.snap:
            return
        q = self.feed.quotes()
        got = 0
        if q and q.get("ok"):
            for s, v in (q.get("quotes") or {}).items():
                if v.get("open"):
                    self.state.set_open(s, float(v["open"]), "stream quote 09:15")
                    got += 1
        self.inputs["opening_quotes"] = {"status": "ok" if got else "unavailable (opens from the first bar)",
                                         "symbols": got, "arrived": time.time()}
        if got:
            t_open = open_epoch(self.d)
            t0 = self.engine.prev_close_epoch or (t_open - 18 * 3600)
            self.session.refresh_catalysts(t0, t_open, t_open)
            self.engine.checkpoint_0915()
            self._persist()

    def poll(self, now: float) -> int:
        """Fetch new bars, step every bar that is ready. Returns the last stepped bar index."""
        r = self.feed.bars_since(max(0, self.last_t - 600))      # two bars of overlap: duplicates are ignored
        if r and r.get("ok"):
            for sym, rows in (r.get("bars") or {}).items():
                if sym not in self.session.ctx and sym not in INDICES:
                    continue
                for row in rows:
                    if self.state.add(sym, row, arrived=r["_fetched_at"]):
                        self.last_t = max(self.last_t, int(row[0]))
            self.inputs["stream"] = {"status": "ok", "fetched": r["_fetched_at"], "seconds": r.get("_seconds"),
                                     "stream": r.get("stream")}
        else:
            self.inputs["stream"] = {"status": "unavailable", "at": now, "why": self.feed.stats.get("last_error")}
        members = self.session.members
        while self.engine.done_k < 74:
            k = self.engine.done_k + 1
            due = bar_close(self.d, k)
            if now < due:
                break
            have = sum(1 for s in members if self.state.bar(s, k) is not None)
            share = have / len(members) if members else 0
            if share < READY_SHARE and now < due + LATE_S:
                break
            if k in (4, PLAN_K) and not self.session.news_available:
                ann = self.feed.announcements(self.prev, self.d, set(members)) if self.prev else None
                if ann is not None:
                    self.session.news_available = True
                    self.session._ann = {}
                    for a in ann:
                        self.session._ann.setdefault(a["symbol"], []).append(a)
                    self.inputs["announcements"] = {"status": "ok (read at 09:40)", "rows": len(ann)}
            self.coverage.append({"k": k, "t": hhmm(due), "with_bar": have, "members": len(members),
                                  "late_s": round(now - due, 1)})
            self.engine.step(k)
            for o in self.observers:
                try:
                    if isinstance(o, MorningObserver):
                        o.on_bar(self.state, k, self.engine.resume_k, self.engine.scanning)
                    else:
                        o.poll(self.state, k, self.engine.resume_k, self.engine.scanning)
                except Exception:  # noqa: BLE001 - an observer must never stop the desk
                    log.exception("observer failed at bar %s", k)
            self._persist()
        return self.engine.done_k

    def finish(self) -> None:
        self.engine.finish()
        for o in self.observers:
            for b in o.books.values():
                b.square_off(self.state, 74, bar_close(self.d, 74), final=True)
        self.done = True
        self._persist(final=True)

    # ── persistence ─────────────────────────────────────────────────────────────
    def _persist(self, final: bool = False) -> None:
        e = self.engine
        rows = e.journal[self.persisted:]
        for i, r in enumerate(rows, start=self.persisted):
            r.setdefault("seq", i)
            r["_id"] = f"{self.d}|{_rid(r)}"
        self.store.add_journal(rows)
        self.persisted = len(e.journal)
        day = str(self.d)
        for b in self._all_books():
            for p in b.open + [p for p in b.closed if _pday(p) == day]:
                if self._saved_pos.get(p.pid) != p.status:        # write on entry and on exit only
                    self.store.save_position(p, day)
                    self._saved_pos[p.pid] = p.status
            for a in b.alerts:
                self.store.alert(f"failed_exit|{a['pid']}", {"type": "failed_exit", "book": b.name, **a,
                                                             "message": f"{a['symbol']}: no price at 15:05/15:10; "
                                                                        f"closed at the last known price {a['last_price']}"})
            b.alerts.clear()
            today = [p for p in b.closed if _pday(p) == day]
            sig = (round(b.equity, 2), len(b.open), round(b.day_realized, 2), b.blocked, len(today), b.day)
            if self._book_sig.get(b.name) == sig and not final:
                continue
            self._book_sig[b.name] = sig
            self.store.save_book(b.name, {
                "day": day, "day_start": b.day_start, "equity": b.equity, "day_realized": b.day_realized,
                "open": len(b.open), "open_risk": b.open_risk(), "blocked": b.blocked, "trades_today": len(today),
                "summary": {"open": [p.symbol for p in b.open], "net_today": round(sum(p.net or 0 for p in today), 2)}})
        snaps = {f"checkpoints.{k}": v for k, v in e.snap.items()
                 if not k.startswith("skip") and f"checkpoints.{k}" not in self._once_done}
        self._once_done |= set(snaps)
        self.store.set_day(day, {**snaps, "inputs": self.inputs, "coverage": self.coverage[-80:],
                                 "progress": {"done_k": e.done_k, "t": time.time(), "scanning": e.scanning,
                                              "resume_k": e.resume_k},
                                 "observers": [o.status for o in self.observers],
                                 "status": "closed" if final else ("running" if e.done_k >= 0 else "prepared")},
                           once=tuple(snaps.keys()))


def _rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 if resource else 0.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    url = os.getenv("FACTORY_MONGO_URL", "").strip()
    if not url:
        log.error("FACTORY_MONGO_URL is not set: the desk has nowhere to write; idling")
        while True:
            time.sleep(3600)
    from pymongo import MongoClient
    client = MongoClient(url, serverSelectionTimeoutMS=5000, maxPoolSize=4, appname="premium-intraday")
    store = Store(url, client=client)
    store.ensure_indexes()
    ledger = LedgerReader(client) if os.getenv("PIS_FOLLOW_TOURNAMENT", "1") != "0" else None
    feed = Feed(os.getenv("PIS_BACKEND_URL", "http://backend:8080"), os.getenv("APP_SHARED_SECRET", ""),
                os.getenv("PIS_DATA_DIR", "/data/intraday"))
    settings = Settings(risk=Risk.from_env())
    cfg = live_config()
    morning = os.getenv("PIS_MORNING_RULES", "/app/vendor/morning.py")
    morning = morning if os.path.exists(morning) else None
    run: DayRun | None = None
    enabled = True
    log.info("premium intraday desk %s starting; strategies %d", VERSION, len(cfg["strategies"]))
    while True:
        try:
            now = now_ist()
            d = now.date()
            ctl = store.control()
            if ctl.get("enabled") is not None:
                enabled = bool(ctl["enabled"])
            mins = now.hour * 60 + now.minute
            hb = {"version": VERSION, "enabled": enabled, "day": str(d), "trading_day": trading_day(d),
                  "rss_mb": round(_rss_mb(), 1), "feed": feed.stats, "pid": os.getpid()}
            if not trading_day(d):
                store.heartbeat({**hb, "state": "idle (not a trading day)"})
                time.sleep(300)
                continue
            if run is not None and run.d != d:
                run = None
            if run is None and not enabled:
                store.heartbeat({**hb, "state": "paused (OFF): no scans today"})
                time.sleep(60)
                continue
            if run is None and (mins >= PRE_AT[0] * 60 + PRE_AT[1]) and mins < 15 * 60 + 31:
                run = DayRun(d, feed, store, settings, cfg, ledger=ledger, morning_path=morning)
                try:
                    run.prepare()
                except Exception:  # noqa: BLE001
                    log.exception("PRE failed")
                    store.alert(f"pre|{d}", {"type": "pre_failed", "message": traceback.format_exc()[-800:]})
                    run = None
                    time.sleep(60)
                    continue
            if run is None or run.done:
                store.heartbeat({**hb, "state": "waiting for the session" if mins < 9 * 60 else "session closed"})
                time.sleep(60 if mins < 15 * 60 + 31 else 600)
                continue
            # holding positions while OFF: keep managing exits; flat while OFF: skip new work
            run.engine.scanning = enabled
            if mins >= 9 * 60 + 15 and "0915" not in run.engine.snap and enabled:
                run.snapshot_0915()
            k = run.poll(time.time()) if mins >= 9 * 60 + 20 else -1
            if mins >= 15 * 60 + 31 and not run.done:
                run.finish()
            open_n = sum(len(b.open) for b in run._all_books())
            store.heartbeat({**hb, "state": ("running" if enabled else ("stopping: managing exits" if open_n else "paused (OFF)")),
                             "done_k": run.engine.done_k, "open_positions": open_n,
                             "last_bar": hhmm(bar_close(d, run.engine.done_k)) if run.engine.done_k >= 0 else None})
            # sleep to the next bar close + offset
            nxt = bar_close(d, max(run.engine.done_k + 1, 0)) + POLL_OFFSET_S
            time.sleep(max(5.0, min(60.0, nxt - time.time())))
        except Exception:  # noqa: BLE001 - the loop never dies; the error is visible on the page
            log.exception("cycle failed")
            try:
                store.alert("worker_cycle", {"type": "worker_error", "message": traceback.format_exc()[-800:]})
            except Exception:  # noqa: BLE001
                pass
            time.sleep(30)
