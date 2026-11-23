"""One trading day of the desk, decided bar close by bar close. Replay and live both drive `DayEngine.step(k)`
after bar k (09:15+5k .. 09:20+5k) has closed for the stocks that have it.

  step(0)   09:15 snapshot (opens, gaps, coverage) and the 09:20 screen (first completed bar)
  step(2)   09:30 screen: opening range, sector ranking, market condition, provisional long/short lists
  step(4)   09:40 persistence check
  step(5)   09:45 trade plan published (no order is placed by the plan)
  step(6+)  exits first (stops, targets, time exits, 15:05 square-off, 15:10 retry), then triggers -> entries

Every checkpoint is stored as it was computed (what the desk knew then); every setup and every book decision is a
journal row with the facts it was taken on.
"""
from __future__ import annotations

from statistics import median

from . import sectors as SEC
from .book import Book
from .strategies import Setup, close_min
from .timeutil import bar_close, hhmm, OPEN_MIN

PLAN_K = 5
SQUAREOFF_K = 69          # 15:00-15:05 bar, closes 15:05
FLAT_K = 70               # 15:05-15:10 bar, closes 15:10


class Session:
    """Everything a strategy may read at bar k. Caches per k so a dozen strategies share one sector table."""

    def __init__(self, day, ctx: dict, members: list, state, index_prev: dict, announcements: list | None,
                 settings):
        self.day = day
        self.ctx = ctx
        self.members = members
        self.state = state
        self.index_prev = index_prev
        self.settings = settings
        self.news_available = announcements is not None
        self._ann = {}
        for a in announcements or []:
            self._ann.setdefault(a["symbol"], []).append(a)
        self._sec = {}
        self._mkt = {}
        self._by_sector = {}
        for s in members:
            self._by_sector.setdefault(ctx[s].sector, []).append(s)
        self.catalysts = {}               # symbol -> material announcements known so far (set by the engine)
        self.preopen_catalysts = {}       # symbol -> material announcements disseminated before 09:15

    def refresh_catalysts(self, t0: float, t_open: float, t_now: float) -> None:
        """Point in time: only announcements whose EXCHANGE dissemination time is before `t_now`."""
        if not self.news_available:
            return
        self.catalysts = {s: c for s in self.members if (c := self.catalysts_between(s, t0, t_now))}
        self.preopen_catalysts = {s: c for s in self.members if (c := self.catalysts_between(s, t0, t_open))}

    def drop_members(self, syms: set) -> None:
        self.members = [s for s in self.members if s not in syms]
        self._by_sector = {}
        for s in self.members:
            self._by_sector.setdefault(self.ctx[s].sector, []).append(s)
        self._sec.clear()
        self._mkt.clear()

    def sectors(self, k: int) -> list:
        if k not in self._sec:
            self._sec[k] = SEC.sector_table(self.state, k, self.members, self.ctx, self.index_prev)
        return self._sec[k]

    def sector_row(self, sector: str, k: int) -> dict | None:
        return next((r for r in self.sectors(k) if r["sector"] == sector), None)

    def market(self, k: int) -> dict:
        if k not in self._mkt:
            self._mkt[k] = SEC.market_condition(self.state, k, self.members, self.ctx, self.index_prev)
        return self._mkt[k]

    def stock_rel(self, sym: str, k: int) -> float | None:
        return SEC.stock_vs_sector(self.state, k, sym, self._by_sector.get(self.ctx[sym].sector, []))

    def catalysts_between(self, sym: str, t0: float, t1: float) -> list:
        return [a for a in self._ann.get(sym, []) if t0 <= a["ts"] < t1 and a.get("material")]


class DayEngine:
    def __init__(self, session: Session, strategies: list, books: dict, portfolio: Book | None,
                 eligible: dict | None = None, journal: list | None = None, keep_detail: bool = True,
                 prev_close_epoch: float | None = None):
        """strategies: Strategy instances; books: {strategy key -> observation Book}; portfolio: the shared Book
        (admits only strategies in `eligible`: {strategy key: {"mean_R": x, "conditions": {side: [...]}}})."""
        self.S = session
        self.strats = strategies
        self.books = books
        self.portfolio = portfolio
        self.eligible = eligible or {}
        self.journal = journal if journal is not None else []
        self.detail = keep_detail
        self.snap: dict = {}
        self.setups: list[Setup] = []
        self.cands: dict = {}
        self.done_k = -1
        self.prev_close_epoch = prev_close_epoch
        self.clock = session.settings.clock
        self.scanning = True          # False (module OFF): no checkpoints, no setups, no entries; exits continue
        self.resume_k = -1            # bars before this were processed while the desk was down: nothing enters there
        self.consumed: set = set()    # setup keys that already ended before a restart (never re-armed)

    # ── journal ─────────────────────────────────────────────────────────────────
    def _j(self, k: int, kind: str, **kw) -> None:
        row = {"day": str(self.S.day), "k": k, "t": hhmm(bar_close(self.S.day, k)) if k >= 0 else "pre", "kind": kind}
        row.update(kw)
        self.journal.append(row)

    # ── checkpoints ─────────────────────────────────────────────────────────────
    def checkpoint_0915(self) -> dict:
        S = self.S
        rows, missing, set_aside = [], [], []
        ca = S.settings.universe.ca_gap * 100
        for s in list(S.members):
            o = S.state.open(s)
            c = S.ctx[s]
            if o is None:
                missing.append(s)
                continue
            gap = (o / c.prev_close - 1) * 100
            if abs(gap) > ca:
                set_aside.append({"symbol": s, "gap_pct": gap,
                                  "why": f"opened {gap:+.1f}% from its previous close: probable split/bonus/corporate "
                                         f"action, prices not comparable - set aside for the day"})
                continue
            rows.append({"symbol": s, "sector": c.sector, "open": o, "prev_close": c.prev_close,
                         "prev_close_src": c.prev_close_src, "gap_pct": gap, "gap_atr": gap / max(c.atr_pct, 1e-6),
                         "open_src": S.state.open_src.get(s)})
        if set_aside:
            S.drop_members({x["symbol"] for x in set_aside})
        rows.sort(key=lambda r: -abs(r["gap_pct"]))
        watch = [r for r in rows if abs(r["gap_pct"]) >= max(1.0, 0.5 * S.ctx[r["symbol"]].atr_pct)]
        cat = {s for s in S.members if S.catalysts.get(s)}
        snap = {"stage": "0915", "coverage": len(rows) / len(S.members) if S.members else 0,
                "with_open": len(rows), "members": len(S.members), "missing": missing[:40],
                "set_aside": set_aside,
                "gap_up": sum(1 for r in rows if r["gap_pct"] > 0), "gap_down": sum(1 for r in rows if r["gap_pct"] < 0),
                "spreads": "not observable: the app's live stream is Angel QUOTE mode (no bid/ask); costs use the "
                           "measured slippage band of each stock",
                "watchlist": [{**r, "catalyst": r["symbol"] in cat} for r in watch[:25]],
                "catalyst_names": sorted(cat)[:40]}
        self.snap["0915"] = snap
        self._j(-1, "checkpoint", stage="0915", summary={k: snap[k] for k in ("coverage", "gap_up", "gap_down")})
        return snap

    def _0920(self, k: int) -> dict:
        S = self.S
        rows = []
        for s in S.members:
            if not S.state.complete(s, 0):
                continue
            c = S.ctx[s]
            b = S.state.bar(s, 0)
            o = S.state.open(s)
            gap = (o / c.prev_close - 1) * 100
            rv = S.state.rvol(s, 0, c.cum_base)
            body = (b[4] - b[1]) / b[1] * 100
            verdict = None
            if abs(gap) >= 0.5:
                verdict = "continuation" if body * gap > 0 else "rejection"
            rows.append({"symbol": s, "sector": c.sector, "gap_pct": gap, "first_bar_pct": body, "rvol": rv,
                         "gap_verdict": verdict})
        by = {}
        for r in rows:
            by.setdefault(r["sector"], []).append(r["first_bar_pct"])
        diverge = []
        for r in rows:
            peers = [x for x in by.get(r["sector"], []) if x is not r["first_bar_pct"]]
            if len(peers) >= 3:
                med = median(peers)
                if med * r["first_bar_pct"] < 0 and abs(r["first_bar_pct"] - med) >= 0.5:
                    diverge.append({**r, "sector_median_pct": med})
        mk = S.market(0)
        snap = {"stage": "0920", "with_first_bar": len(rows), "members": len(S.members),
                "unusual_volume": sorted([r for r in rows if (r["rvol"] or 0) >= 2.0], key=lambda r: -r["rvol"])[:20],
                "gap_continuation": [r for r in rows if r["gap_verdict"] == "continuation"][:20],
                "gap_rejection": [r for r in rows if r["gap_verdict"] == "rejection"][:20],
                "breadth": {"adv": mk["adv"], "dec": mk["dec"], "up_open": mk["up_open"]},
                "diverging_from_sector": sorted(diverge, key=lambda r: -abs(r["first_bar_pct"]))[:15],
                "market": mk}
        self.snap["0920"] = snap
        self._j(k, "checkpoint", stage="0920", summary={"with_first_bar": len(rows), "breadth": snap["breadth"]})
        return snap

    def _0930(self, k: int) -> dict:
        S = self.S
        mk = S.market(k)
        secs = S.sectors(k)
        prov = {}
        for st in self.strats:
            cs = st.screen(S, k)
            self.cands[self._key(st)] = cs
            prov[self._key(st)] = [{"symbol": x["symbol"], "side": "LONG" if x["side"] > 0 else "SHORT",
                                    "score": round(x["score"], 3)} for x in cs][:20]
        snap = {"stage": "0930", "market": mk, "sectors": secs, "provisional": prov}
        self.snap["0930"] = snap
        self._j(k, "checkpoint", stage="0930", summary={"condition": mk["condition"],
                                                        "strong": [r["sector"] for r in secs if r.get("strong")],
                                                        "weak": [r["sector"] for r in secs if r.get("weak")]})
        return snap

    def _0940(self, k: int) -> dict:
        S = self.S
        mk = S.market(k)
        secs = S.sectors(k)
        prev = {r["sector"]: r for r in self.snap.get("0930", {}).get("sectors", [])}
        rotation, narrowing = [], []
        top_then = {r["sector"] for r in self.snap.get("0930", {}).get("sectors", []) if r.get("rank") and r["rank"] <= 2}
        top_now = {r["sector"] for r in secs if r.get("rank") and r["rank"] <= 2}
        for s in top_now - top_then:
            rotation.append(f"{s} moved into the top two")
        for s in top_then - top_now:
            rotation.append(f"{s} dropped out of the top two")
        for r in secs:
            p = prev.get(r["sector"])
            if p and p.get("up_open") is not None and r.get("up_open") is not None and p["up_open"] - r["up_open"] >= 0.10:
                narrowing.append({"sector": r["sector"], "from": p["up_open"], "to": r["up_open"]})
        failed, weakening, kept, dropped = [], [], {}, {}
        for st in self.strats:
            key = self._key(st)
            keep, drop = st.confirm(S, k, self.cands.get(key, []))
            self.cands[key] = keep
            kept[key] = [x["symbol"] for x in keep]
            dropped[key] = [{"symbol": x["symbol"], "why": x.get("why")} for x in drop]
        for s in S.members:
            orr = S.state.or15(s)
            c = S.state.close(s, k)
            if not orr or c is None:
                continue
            H, L, _, _ = orr
            hi, lo = S.state.high(s, k), S.state.low(s, k)
            if hi > H and c <= H:
                failed.append({"symbol": s, "side": "LONG", "or_high": H, "close": c})
            if lo < L and c >= L:
                failed.append({"symbol": s, "side": "SHORT", "or_low": L, "close": c})
        snap = {"stage": "0940", "market": mk, "sectors": secs, "rotation": rotation, "narrowing": narrowing,
                "failed_breakouts": failed[:25], "kept": kept, "dropped": dropped,
                "spreads": "not observable (no bid/ask in the live stream)"}
        self.snap["0940"] = snap
        self._j(k, "checkpoint", stage="0940", summary={"condition": mk["condition"], "rotation": rotation,
                                                        "narrowing": [n["sector"] for n in narrowing]})
        return snap

    def _0945(self, k: int) -> dict:
        S = self.S
        out, by_sym = [], {}
        for st in self.strats:
            setups = [su for su in st.plan(S, k, self.cands.get(self._key(st), []))
                      if su.side in getattr(st, "sides", (1, -1))]
            for su in setups:
                su.status = "armed" if su.key not in self.consumed else "consumed"
                self.setups.append(su)
                by_sym.setdefault(su.symbol, []).append(su)
                out.append(su.public())
        no_trade = []
        if not out:
            no_trade.append("no strategy found a setup that met all of its conditions this morning")
        elig = [x for x in out if self._eligible(x["strategy"], x["variant"], x["level"])]
        if self.portfolio is not None and not elig:
            no_trade.append("the portfolio admits only Portfolio Eligible strategies, and none has a setup today"
                            if self.eligible else
                            "no strategy has earned Portfolio Eligible status yet, so the portfolio places no trade; "
                            "every setup is still followed in its strategy's observation book")
        snap = {"stage": "0945", "market": S.market(k), "setups": out, "no_trade": no_trade,
                "duplicates": {s: [f"{x.strategy} {x.level}" for x in v] for s, v in by_sym.items() if len(v) > 1}}
        self.snap["0945"] = snap
        self._j(k, "plan", setups=len(out), no_trade=no_trade)
        for su in self.setups:
            self._j(k, "setup", **{kk: v for kk, v in su.public().items() if kk in (
                "strategy", "variant", "level", "symbol", "side", "reason", "trigger", "entry_range", "window",
                "time_exit")})
        return snap

    # ── helpers ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _key(st) -> str:
        return f"{st.id}|{st.variant}|{st.level}"

    def _eligible(self, sid: str, variant: str, level: str) -> bool:
        return f"{sid}|{variant}|{level}" in self.eligible

    def _knew(self, su: Setup, k: int, ref: float, bar) -> dict:
        S = self.S
        sec = S.sector_row(su.sector, PLAN_K) or {}
        sec_now = S.sector_row(su.sector, k) or {}
        arrived = S.state.s[su.symbol].arrived[-1] if su.symbol in S.state.s else None
        return {"plan": {kk: v for kk, v in su.public().items() if kk in ("reason", "trigger", "entry_range",
                                                                          "stop_rule", "target_R", "window", "facts")},
                "market_0945": {kk: S.market(PLAN_K).get(kk) for kk in ("condition", "nifty_ret_open", "up_open",
                                                                         "above_vwap", "coverage")},
                "market_now": {kk: S.market(k).get(kk) for kk in ("condition", "nifty_ret_open", "up_open")},
                "sector_0945": {kk: sec.get(kk) for kk in ("rank", "rel", "up_open", "above_vwap", "narrow", "why")},
                "sector_now": {kk: sec_now.get(kk) for kk in ("rank", "rel", "up_open", "narrow")},
                "trigger_bar": {"start": hhmm(bar[0]), "o": bar[1], "h": bar[2], "l": bar[3], "c": bar[4], "v": bar[5],
                                "arrived": arrived},
                "ref_price": ref, "vwap": S.state.vwap(su.symbol, k)}

    # ── the bar loop ────────────────────────────────────────────────────────────
    def step(self, k: int) -> None:
        if k <= self.done_k:
            return
        S = self.S
        t_open = bar_close(S.day, -1)                      # 09:15
        t0 = self.prev_close_epoch or (t_open - 18 * 3600)  # previous session's 15:30
        for kk in range(self.done_k + 1, k + 1):
            if not self.scanning:
                if kk in (0, 2, 4, PLAN_K) and f"skip{kk}" not in self.snap:
                    self.snap[f"skip{kk}"] = True
                    self._j(kk, "checkpoint", stage={0: "0920", 2: "0930", 4: "0940", PLAN_K: "0945"}[kk],
                            summary={"skipped": "module switched OFF: no new scans or entries"})
            elif kk == 0:
                if "0915" not in self.snap:
                    S.refresh_catalysts(t0, t_open, t_open)
                    self.checkpoint_0915()
                self._0920(kk)
            elif kk == PLAN_K:
                S.refresh_catalysts(t0, t_open, bar_close(S.day, PLAN_K))
            elif kk == 2:
                self._0930(kk)
            elif kk == 4:
                self._0940(kk)
            if kk == PLAN_K and self.scanning:
                self._0945(kk)
            if kk > PLAN_K:
                self._bar(kk)
            self.done_k = kk

    def _all_books(self):
        bs = list(self.books.values())
        if self.portfolio is not None:
            bs.append(self.portfolio)
        return bs

    def _bar(self, k: int) -> None:
        S = self.S
        t_close = bar_close(S.day, k)
        # 1. exits on bar k
        for b in self._all_books():
            for p in b.manage(S.state, k, t_close):
                self._j(k, "exit", book=b.name, symbol=p.symbol, strategy=p.strategy, level=p.level,
                        reason=p.reason, price=round(p.exit, 4), net=round(p.net, 2), r=round(p.r_net or 0, 3))
            if k == SQUAREOFF_K or k == FLAT_K:
                for p in b.square_off(S.state, k, t_close, final=(k == FLAT_K)):
                    self._j(k, "exit", book=b.name, symbol=p.symbol, strategy=p.strategy, level=p.level,
                            reason=p.reason, price=round(p.exit, 4), net=round(p.net, 2), r=round(p.r_net or 0, 3),
                            failed=p.failed_exit)
            b.check_loss_stop(S.state, k)
        # 2. setups on bar k -> entries
        if not self.scanning:
            return
        if close_min(k) > self.clock.last_entry_min:
            for su in self.setups:
                if su.status == "armed":
                    su.status = "expired"
                    self._j(k, "setup_end", strategy=su.strategy, symbol=su.symbol, level=su.level,
                            status="expired", why="entries closed at 14:30")
            return
        intents = []
        for su in self.setups:
            if su.status != "armed":
                continue
            ev = self._strategy(su).on_bar(su, S, k)
            if ev is None:
                continue
            kind = ev[0]
            if kind == "enter":
                _, ref, stop, target, note = ev
                bar = S.state.bar(su.symbol, k)
                su.status = "triggered"
                su.events.append({"k": k, "type": "triggered", "note": note})
                intents.append((su, ref, stop, target, bar, note))
                if su.oco:
                    for other in self.setups:
                        if other is not su and other.oco == su.oco and other.status == "armed" \
                                and other.variant == su.variant and other.level == su.level:
                            other.status = "cancelled"
                            self._j(k, "setup_end", strategy=other.strategy, symbol=other.symbol, level=other.level,
                                    status="cancelled", why="the other side of its OCO pair triggered")
            else:
                su.status = {"invalid": "invalidated", "expire": "expired", "missed": "missed", "skip": "skipped"}[kind]
                su.events.append({"k": k, "type": su.status, "why": ev[1]})
                self._j(k, "setup_end", strategy=su.strategy, symbol=su.symbol, level=su.level, variant=su.variant,
                        side="LONG" if su.side > 0 else "SHORT", status=su.status, why=ev[1])
        if not intents:
            return
        if k < self.resume_k:
            for su, ref, *_ in intents:
                su.status = "missed"
                self._j(k, "setup_end", strategy=su.strategy, symbol=su.symbol, level=su.level, variant=su.variant,
                        side="LONG" if su.side > 0 else "SHORT", status="missed",
                        why=f"triggered at {hhmm(bar_close(S.day, k))} while the desk was offline: not entered late")
            return
        cond = S.market(k)["condition"]
        # observation books: each strategy's own
        for su, ref, stop, target, bar, note in intents:
            key = f"{su.strategy}|{su.variant}|{su.level}"
            intent = {"strategy": su.strategy, "variant": su.variant, "level": su.level, "symbol": su.symbol,
                      "sector": su.sector, "side": su.side, "ref": ref, "stop": stop, "target": target,
                      "slip_bp": S.ctx[su.symbol].slip_bp, "bar_volume": bar[5], "time_exit_min": su.time_exit_min,
                      "knew": self._knew(su, k, ref, bar) if self.detail else {}}
            book = self.books.get(key)
            if book is not None:
                p, why = book.admit(intent, k, t_close, self.clock.last_entry_min)
                self._j(k, "entry" if p else "rejected", book=book.name, strategy=su.strategy, level=su.level,
                        variant=su.variant, symbol=su.symbol, side="LONG" if su.side > 0 else "SHORT",
                        why=why, note=note, ref=round(ref, 4), stop=round(stop, 4), target=round(target, 4),
                        qty=p.qty if p else None, knew=intent["knew"] if self.detail else None)
            su._intent = intent
        # the shared portfolio: eligible strategies only, best evidence first, one position per stock
        if self.portfolio is None:
            return
        ranked = sorted(intents, key=lambda x: (
            0 if self._eligible(x[0].strategy, x[0].variant, x[0].level) else 1,
            -self.eligible.get(f"{x[0].strategy}|{x[0].variant}|{x[0].level}", {}).get("mean_R", 0.0),
            -x[0].score, x[0].symbol))
        taken = set()
        for su, ref, stop, target, bar, note in ranked:
            key = f"{su.strategy}|{su.variant}|{su.level}"
            if not self._eligible(su.strategy, su.variant, su.level):
                self._j(k, "portfolio_skip", strategy=su.strategy, level=su.level, symbol=su.symbol,
                        why="strategy is not Portfolio Eligible (followed in its observation book only)")
                continue
            ok_conds = self.eligible[key].get("conditions", {}).get("LONG" if su.side > 0 else "SHORT", [])
            if cond not in ok_conds:
                self._j(k, "portfolio_skip", strategy=su.strategy, level=su.level, symbol=su.symbol,
                        why=f"market is {cond}; this strategy is validated only for {', '.join(ok_conds) or 'none'}")
                continue
            if su.symbol in taken:
                self._j(k, "portfolio_skip", strategy=su.strategy, level=su.level, symbol=su.symbol,
                        why="another strategy with stronger evidence took this stock at the same bar")
                continue
            p, why = self.portfolio.admit(su._intent, k, t_close, self.clock.last_entry_min)
            if p:
                taken.add(su.symbol)
            self._j(k, "portfolio_entry" if p else "portfolio_rejected", strategy=su.strategy, level=su.level,
                    symbol=su.symbol, why=why, qty=p.qty if p else None)

    def restore(self, book_name: str, open_positions: list, closed_today: list) -> None:
        """After a worker restart: put back what the desk already held and closed today, exactly as stored. Bars
        that arrived while the desk was down are then managed (exits only) and their exits are flagged late."""
        b = self.portfolio if self.portfolio is not None and book_name == self.portfolio.name else self.books.get(book_name)
        if b is None:
            return
        have = {p.pid for p in b.open} | {p.pid for p in b.closed}
        for p in open_positions:
            if p.pid not in have:
                b.open.append(p)
        for p in closed_today:
            if p.pid not in have:
                b.closed.append(p)
                b.day_realized += p.net or 0.0
        b._n = max([b._n] + [int(str(p.pid).rsplit("|", 1)[-1]) for p in b.open + b.closed
                             if str(p.pid).rsplit("|", 1)[-1].isdigit()])

    def _strategy(self, su: Setup):
        for st in self.strats:
            if st.id == su.strategy and st.variant == su.variant and st.level == su.level:
                return st
        raise KeyError(su.key)

    def finish(self, last_k: int = 74) -> None:
        """After the session: anything still open (a feed that never delivered 15:05/15:10) is a failed exit."""
        for b in self._all_books():
            for p in b.square_off(self.S.state, max(FLAT_K, last_k), bar_close(self.S.day, max(FLAT_K, last_k)), final=True):
                self._j(last_k, "exit", book=b.name, symbol=p.symbol, strategy=p.strategy, reason=p.reason,
                        net=round(p.net, 2), failed=True)
