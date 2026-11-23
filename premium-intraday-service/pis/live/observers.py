"""Forward observation of the imported Top 25 on this desk's capital, costs and fills (observation books only: an
imported strategy never enters the shared portfolio unless it earns Portfolio Eligible like any other).

  MorningObserver     Stock Momentum Trading's rules, run from the desk's own morning.py (pis.imported.load_morning)
                      on today's bars; its 09:30 board is computed here, never asked of the Stock Momentum desk.
  TournamentObserver  the Intraday Stocks tournament's signals, READ from its decision ledger (find() only) and
                      re-filled here; when the tournament is off or its ledger is unreachable, the day is reported as
                      "source unavailable" and nothing is guessed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..book import Book
from ..imported import BarsAdapter, load_morning, morning_intent, tournament_time_exit
from ..timeutil import OPEN_MIN, bar_close, bar_index, hhmm, open_epoch

log = logging.getLogger("pis.observers")


def _cmin(k: int) -> int:
    return OPEN_MIN + (k + 1) * 5


class _Base:
    def __init__(self, books: dict, journal: list, day):
        self.books = books
        self.journal = journal
        self.day = day
        self.status = {"state": "waiting", "signals": 0, "entries": 0}

    def _j(self, k, kind, **kw):
        self.journal.append({"day": str(self.day), "k": k, "t": hhmm(bar_close(self.day, k)), "kind": kind, **kw})

    def manage(self, state, k):
        t_close = bar_close(self.day, k)
        for b in self.books.values():
            for p in b.manage(state, k, t_close):
                self._j(k, "exit", book=b.name, symbol=p.symbol, strategy=p.strategy, level=p.level,
                        reason=p.reason, price=round(p.exit, 4), net=round(p.net, 2), r=round(p.r_net or 0, 3))
            if k in (69, 70):
                for p in b.square_off(state, k, t_close, final=(k == 70)):
                    self._j(k, "exit", book=b.name, symbol=p.symbol, strategy=p.strategy, level=p.level,
                            reason=p.reason, price=round(p.exit, 4), net=round(p.net, 2), failed=p.failed_exit)

    def _admit(self, state, k, name, intent, resume_k, scanning):
        b = self.books.get(name)
        if b is None:
            return
        self.status["signals"] += 1
        if not scanning:
            return
        if k < resume_k:
            self._j(k, "setup_end", strategy=name, symbol=intent["symbol"], level="imported", status="missed",
                    why="signalled while the desk was offline")
            return
        p, why = b.admit(intent, k, bar_close(self.day, k), 14 * 60 + 30)
        if p:
            self.status["entries"] += 1
        self._j(k, "entry" if p else "rejected", book=b.name, strategy=name, level="imported", variant="as-built",
                symbol=intent["symbol"], side="LONG" if intent["side"] > 0 else "SHORT", why=why,
                ref=round(intent["ref"], 4), stop=round(intent["stop"], 4),
                target=round(intent["target"], 4) if intent["target"] else None, qty=p.qty if p else None)


class MorningObserver(_Base):
    def __init__(self, morning_path: str, rules: list, books: dict, journal: list, day, members: list, ctx: dict,
                 industry: dict, sparse_history: dict):
        super().__init__(books, journal, day)
        self.rules = set(rules)
        self.members = members
        self.ctx = ctx
        self.industry = industry
        self.hist = sparse_history
        self.rows = []
        self.used = set()
        try:
            self.m = load_morning(morning_path)
            self.status["source"] = morning_path
        except Exception as exc:  # noqa: BLE001
            self.m = None
            self.status.update(state="source unavailable", why=f"{type(exc).__name__}: {exc}"[:200])

    def on_bar(self, state, k, resume_k=-1, scanning=True):
        if self.m is None:
            return
        self.manage(state, k)
        start = open_epoch(self.day)
        if k == 2 and scanning:
            loader = lambda sym, tf="5m": BarsAdapter(self.hist.get(sym, []) + state.bars_upto(sym, 2))
            try:
                rows, _ = self.m.scan(start, {s: self.industry.get(s) for s in self.members}, loader)
                self.rows = [r for r in rows if r.get("rank", 999) <= 10 and r["turnover"] >= 1e7]
                self.status.update(state="board", board=len(self.rows))
            except Exception as exc:  # noqa: BLE001
                self.status.update(state="scan failed", why=f"{type(exc).__name__}: {exc}"[:200])
                self.rows = []
            return
        if k < 3 or _cmin(k) > 14 * 60 + 30:
            return
        for r in self.rows:
            sym = r["symbol"]
            bars = state.bars_upto(sym, k)
            if len(bars) != k + 1 or any(b[0] != start + 300 * i for i, b in enumerate(bars)):
                continue
            c = self.ctx.get(sym)
            for rule, side in self.m.triggers(r, bars):
                name = f"SM:{rule}"
                if name not in self.rules or side != r["side"] or (sym, rule) in self.used:
                    continue
                if side < 0 and not (c and c.fno):
                    continue
                it = morning_intent(rule, side, r, bars[-1], k, c.slip_bp if c else 4.12, c.sector if c else "Other")
                if it is None:
                    continue
                self.used.add((sym, rule))
                self._admit(state, k, name, it, resume_k, scanning)


class TournamentObserver(_Base):
    def __init__(self, reader, sids: list, books: dict, journal: list, day, ctx: dict):
        super().__init__(books, journal, day)
        self.reader = reader
        self.sids = set(sids)
        self.ctx = ctx
        self.seen = set()
        self.armed = []
        self.last_t = None

    def poll(self, state, k, resume_k=-1, scanning=True):
        self.manage(state, k)
        if self.reader is None:
            self.status.update(state="source unavailable", why="no access to the tournament's ledger")
            return
        try:
            rows = self.reader.rows(str(self.day), self.sids, self.last_t)
        except Exception as exc:  # noqa: BLE001
            self.status.update(state="source unavailable", why=f"{type(exc).__name__}: {exc}"[:200])
            return
        self.status["state"] = "reading"
        for r in rows:
            t = r.get("t")
            if t is None:
                continue
            t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
            self.last_t = t if self.last_t is None or t > self.last_t else self.last_t
            key = (r.get("src"), r.get("sid"), r.get("sym"), t.isoformat(), r.get("side"))
            if key in self.seen or r.get("oco") or r.get("sym") not in self.ctx:
                continue
            self.seen.add(key)
            side = 1 if r.get("side") == "BUY" else -1 if r.get("side") == "SELL" else 0
            if not side or r.get("px") is None or r.get("stop") is None:
                continue
            kk = int((t.timestamp() - open_epoch(self.day)) // 300)       # the bar containing t
            if r.get("src") == "close":
                if r.get("trig") is not None:
                    continue                                              # armed stop entry: wait for its trigger row
                kk -= 1                                                   # t is a bar CLOSE: the bar ending at t
            if kk < 0 or kk > 74:
                continue
            self.armed.append((kk, r, side))
        for item in list(self.armed):
            kk, r, side = item
            if kk > k:
                continue
            self.armed.remove(item)
            b = state.bar(r["sym"], kk)
            if b is None:
                continue
            c = self.ctx[r["sym"]]
            if r.get("src") == "trigger":
                trig = float(r["px"])
                ref = max(trig, b[1]) if side > 0 else min(trig, b[1])
            else:
                ref = b[4]
            stop_dist = abs(float(r["px"]) - float(r["stop"]))
            tgt_dist = abs(float(r["tgt"]) - float(r["px"])) if r.get("tgt") is not None else None
            it = {"strategy": r["sid"], "variant": "as-built", "level": "imported", "symbol": r["sym"],
                  "sector": c.sector, "side": side, "ref": ref, "stop": ref - side * stop_dist,
                  "target": ref + side * tgt_dist if tgt_dist else None, "slip_bp": c.slip_bp, "bar_volume": b[5],
                  "time_exit_min": tournament_time_exit(r["sid"], _cmin(kk)), "knew": {"ledger": {
                      kx: (str(v) if kx == "t" else v) for kx, v in r.items() if kx in ("t", "src", "px", "stop", "tgt", "dec", "why", "mb")}}}
            self._admit(state, kk, r["sid"], it, resume_k, scanning)
            bk = self.books.get(r["sid"])
            if bk is not None and kk < k:
                # the ledger row arrived after its bar: walk the bars since then for this book (idempotent for
                # positions that already survived them)
                for j in range(kk + 1, k + 1):
                    for p in bk.manage(state, j, bar_close(self.day, j)):
                        self._j(j, "exit", book=bk.name, symbol=p.symbol, strategy=p.strategy, level=p.level,
                                reason=p.reason, price=round(p.exit, 4), net=round(p.net, 2), r=round(p.r_net or 0, 3))
