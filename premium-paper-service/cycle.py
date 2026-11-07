"""One cycle of one group, run as its own short process so all its memory goes back to the box when it ends.

    python cycle.py index | stocks | global | daily

A cycle replays each book from its first unsealed day over the bars known now. Bars are append-only and final bars
never change, so replays agree; once a session is final its trades are sealed.
"""

from __future__ import annotations

import logging
import resource
import sys
import time
from datetime import date, datetime, timedelta

import catalog as C
import feeds as F
import ledger as L
import runner as R
import vwap_run
from research import YM
from settings import DAILY_WARM_DAYS, PAPER_START, now_ist

log = logging.getLogger("premium.cycle")
INDEX_WARM_DAYS, GLOBAL_WARM_DAYS = 95, 45
POOLS = ("NSE15", "NSE5", "NSED")


def _next(day: str) -> date:
    return date.fromisoformat(day) + timedelta(days=1)


def replay_from(db, acct: str, market: str, overnight: bool) -> date:
    if overnight:
        return PAPER_START
    s = L.sealed_through(db, acct, market)
    return max(PAPER_START, _next(s)) if s else PAPER_START


def _save_book(db, a, market, trades, m, overnight, start, final, live_day):
    docs = [d for d in R.docs_from(trades, m, a.id, market, overnight, live_day) if d["date"] >= start.isoformat()]
    return L.persist(db, a.id, market, docs, start.isoformat(), final, overnight)


# ── index ────────────────────────────────────────────────────────────────────────────

def run_index(db, now: datetime) -> dict:
    books = [(a, mk, v, replay_from(db, a.id, mk, False)) for a, mk, v in C.books_in("index")]
    first = min(b[3] for b in books)
    live = F.today_bars("index")
    since = first - timedelta(days=INDEX_WARM_DAYS)
    mk: dict = {}
    for name in ("NIFTY", "BANKNIFTY"):
        mk[name] = F.index_market(name, since, live.get(name), now)
    final = F.nse_final_day(now, mk["NIFTY"][2])
    sig = f"{mk['NIFTY'][0].t[-1]}|{mk['BANKNIFTY'][0].t[-1]}|{final}"
    if sig == L.signature(db, "index"):
        return {"skipped": "no new bars", "final": final}
    if now.date() < PAPER_START:
        L.set_signature(db, "index", sig)
        return {"waiting_for": PAPER_START.isoformat(), "bars_to": str(mk["NIFTY"][0].date[-1])}
    yt_m = {n: YM._as_mkt(mk[n][0], n, n, YM.COSTS[n]) for n in mk}
    caches = {n: {} for n in mk}
    other = (mk["BANKNIFTY"][0], R._bars(mk["BANKNIFTY"][0], (5,), caches["BANKNIFTY"]))
    n_docs, errors = 0, {}
    touched = set()
    for a, market, v, start in books:
        m, live_day, _ = mk[market]
        try:
            if a.source == C.BB:
                tr, _ = R.run_bb(a.id, v, m, caches[market], other if a.id == "BB-03" else None)
            else:
                tr, _ = R.run_yt(a.id, v, market, yt_m[market], caches[market])
            n_docs += _save_book(db, a, market, tr, m, False, start, final, live_day)
            touched.add(a.id)
        except Exception as exc:  # noqa: BLE001 - one broken book must not stop the others
            log.exception("%s %s", a.id, market)
            errors[f"{a.id}|{market}"] = str(exc)[:200]
    L.update_accounts(db, sorted(touched))
    L.set_signature(db, "index", sig)
    return {"trades": n_docs, "final": final, "live_day": mk["NIFTY"][1], "bars_to": int(mk["NIFTY"][0].t[-1]), "errors": errors}


# ── NSE stocks, intraday ─────────────────────────────────────────────────────────────

def _panel_stale(now: datetime) -> bool:
    if not F.PANEL_FILE.exists():
        return True
    ref = F.INTRADAY / "5m" / "RELIANCE.ibar"
    if not ref.exists():
        return False
    # The store is flushed after the close; only then can the panel gain a session.
    return ref.stat().st_mtime > F.PANEL_FILE.stat().st_mtime and now.strftime("%H:%M") >= "17:30"


def run_stocks(db, now: datetime) -> dict:
    info: dict = {}
    if _panel_stale(now):
        info["panel"] = F.build_panel(now)
    live_in_session = "09:15" <= now.strftime("%H:%M") <= "17:29"
    live = F.today_bars("stocks").get("stocks") if live_in_session else None
    panel = F.Panel(live, now)
    final = F.nse_final_day(now, panel.disk_last)
    last_live = max((r[-1][0] for r in (live or {}).values() if r), default=0)
    sig = f"{panel.days[-1]}|{last_live}|{final}"
    if sig == L.signature(db, "stocks"):
        return {**info, "skipped": "no new bars", "final": final}
    if now.date() < PAPER_START:
        L.set_signature(db, "stocks", sig)
        return {**info, "waiting_for": PAPER_START.isoformat(), "bars_to": panel.days[-1]}
    pool_books = [(a, mk, v, replay_from(db, a.id, mk, False)) for a, mk, v in C.books_in("stocks") if mk != "VWAP"]
    first = min(b[3] for b in pool_books).isoformat()
    collected: dict[tuple, list] = {(a.id, mk): [] for a, mk, _, _ in pool_books}
    errors: dict = {}
    day_index = {d: j for j, d in enumerate(panel.days)}
    for i in range(len(panel.names)):
        m = panel.market(i)
        if m is None or str(m.date[-1]) < first:
            continue
        cache: dict = {}
        rank = lambda t, i=i: panel.rank_on(day_index[t.date], i)  # noqa: E731
        for a, mk, v, start in pool_books:
            try:
                tr, _ = R.run_yt(a.id, v, mk, m, cache)
            except Exception as exc:  # noqa: BLE001
                errors.setdefault(f"{a.id}|{mk}", str(exc)[:200])
                continue
            if tr:
                collected[(a.id, mk)] += [d for d in R.docs_from(tr, m, a.id, mk, False, panel.live_day, rank) if d["date"] >= start.isoformat()]
    n_docs, touched = 0, set()
    for a, mk, v, start in pool_books:
        docs = R.take_slots(collected[(a.id, mk)], C.MONEY[mk].max_open)
        n_docs += L.persist(db, a.id, mk, docs, start.isoformat(), final, False)
        touched.add(a.id)
    vw_books = {a.id: replay_from(db, a.id, "VWAP", False) for a, mk, _ in C.books_in("stocks") if mk == "VWAP"}
    days = {d for d in panel.days if d >= min(vw_books.values()).isoformat()}
    if days:
        out = vwap_run.run(panel, days)
        for setup, docs in out.items():
            acct = vwap_run.ACCOUNT[setup]
            start = vw_books[acct].isoformat()
            docs = R.take_slots([d for d in docs if d["date"] >= start], C.MONEY["VWAP"].max_open)
            n_docs += L.persist(db, acct, "VWAP", docs, start, final, False)
            touched.add(acct)
    L.update_accounts(db, sorted(touched))
    L.set_signature(db, "stocks", sig)
    return {**info, "trades": n_docs, "final": final, "live_day": panel.live_day, "bars_to": panel.days[-1], "errors": errors}


# ── forex, gold, US ──────────────────────────────────────────────────────────────────

def run_global(db, now: datetime) -> dict:
    new, errors = {}, {}
    for name in F.YF:
        try:
            new[name] = F.update_minutes(name)["new"]
        except Exception as exc:  # noqa: BLE001 - a market that cannot be fetched just waits for the next cycle
            errors[f"feed {name}"] = str(exc)[:200]
        time.sleep(0.5)
    try:
        rates = F.usdinr()
        if rates:
            db.premium_meta.update_one({"_id": "fx"}, {"$set": {f"rates.{k}": v for k, v in rates.items()}}, upsert=True)
    except Exception as exc:  # noqa: BLE001
        errors["usdinr"] = str(exc)[:200]
    sig = "|".join(f"{n}:{F.last_minute(n)}" for n in sorted(F.YF)) + "|" + "|".join(F.global_final_day(n) for n in ("EURUSD", "NAS100"))
    if sig == L.signature(db, "global"):
        return {"skipped": "no new bars", "errors": errors}
    if now.date() < PAPER_START - timedelta(days=1):
        L.set_signature(db, "global", sig)
        return {"waiting_for": PAPER_START.isoformat(), "new": new, "errors": errors}
    books = [(a, mk, v, R.is_overnight(a.id, mk)) for a, mk, v in C.books_in("global")]
    n_docs, touched = 0, set()
    fixed_since = PAPER_START - timedelta(days=GLOBAL_WARM_DAYS)
    for name in F.YF:
        full = F.global_market(name, fixed_since)
        if full is None:
            continue
        final = F.global_final_day(name)
        last_day = str(full.date[-1])
        live_day = last_day if last_day > final else None
        mine = [b for b in books if b[1] == name]
        firsts = [replay_from(db, a.id, name, False) for a, _, _, on in mine if not on]
        recent = F.slice_from(full, min(firsts) - timedelta(days=GLOBAL_WARM_DAYS)) if firsts else None
        ym_full, ym_recent = YM._as_mkt(full, name, name, YM.COSTS[name]), YM._as_mkt(recent, name, name, YM.COSTS[name]) if recent is not None else None
        c_full, c_recent = {}, {}
        for a, _, v, on in mine:
            m = full if on else recent
            if m is None:
                continue
            start = replay_from(db, a.id, name, on)
            try:
                if a.source == C.BB:
                    tr, _ = R.run_bb(a.id, v, m, c_full if on else c_recent)
                else:
                    tr, _ = R.run_yt(a.id, v, name, ym_full if on else ym_recent, c_full if on else c_recent)
                n_docs += _save_book(db, a, name, tr, m, on, start, final, live_day)
                touched.add(a.id)
            except Exception as exc:  # noqa: BLE001
                log.exception("%s %s", a.id, name)
                errors[f"{a.id}|{name}"] = str(exc)[:200]
    if touched:
        L.update_accounts(db, sorted(touched))
    L.set_signature(db, "global", sig)
    return {"trades": n_docs, "new": new, "errors": errors}


# ── daily markets ────────────────────────────────────────────────────────────────────

def run_daily(db, now: datetime) -> dict:
    info = {"nse": F.nse_daily_update(now)}
    since = PAPER_START - timedelta(days=DAILY_WARM_DAYS)
    idx = {"SPX500_D": F.us_daily("SPX500_D"), "NAS100_D": F.us_daily("NAS100_D"), "NIFTY_D": F.nifty_daily(since, now)}
    lasts = {k: str(v.date[-1]) if v is not None else None for k, v in idx.items()}
    sig = f"{lasts}|{info['nse'].get('last')}"
    if sig == L.signature(db, "daily"):
        return {**info, "skipped": "no new sessions"}
    if now.date() < PAPER_START:
        L.set_signature(db, "daily", sig)
        return {**info, "waiting_for": PAPER_START.isoformat(), "lasts": lasts}
    books = C.books_in("daily")
    n_docs, errors, touched = 0, {}, set()
    for a, mk, v in books:
        if mk == "NSED":
            continue
        m = idx[mk]
        if m is None:
            errors[f"{a.id}|{mk}"] = "no data"
            continue
        try:
            tr, _ = R.run_yt(a.id, v, mk, m, {})
            n_docs += _save_book(db, a, mk, tr, m, True, PAPER_START, lasts[mk], None)
            touched.add(a.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s %s", a.id, mk)
            errors[f"{a.id}|{mk}"] = str(exc)[:200]
    pool = [(a, mk, v) for a, mk, v in books if mk == "NSED"]
    if pool:
        collected = {a.id: [] for a, _, _ in pool}
        markets = F.nse_daily_markets()
        final = max(str(m.date[-1]) for m in markets) if markets else "0000-00-00"
        for m in markets:
            cache: dict = {}
            # Ties go to the more liquid stock, judged only on what was known at that entry (frozen for ever).
            rank = lambda t, m=m: -float(m.turnover20[t.entry_k])  # noqa: E731
            for a, mk, v in pool:
                try:
                    tr, _ = R.run_yt(a.id, v, mk, m, cache)
                except Exception as exc:  # noqa: BLE001
                    errors.setdefault(f"{a.id}|NSED", str(exc)[:200])
                    continue
                if tr:
                    collected[a.id] += [d for d in R.docs_from(tr, m, a.id, mk, True, None, rank) if d["date"] >= PAPER_START.isoformat()]
        for a, mk, _ in pool:
            docs = R.take_slots(collected[a.id], C.MONEY["NSED"].max_open)
            n_docs += L.persist(db, a.id, mk, docs, PAPER_START.isoformat(), final, True)
            touched.add(a.id)
    if touched:
        L.update_accounts(db, sorted(touched))
    L.set_signature(db, "daily", sig)
    return {**info, "trades": n_docs, "lasts": lasts, "errors": errors}


GROUPS = {"index": run_index, "stocks": run_stocks, "global": run_global, "daily": run_daily}


def main(group: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db = L.database()
    t0 = time.time()
    try:
        L.ensure_indexes(db)
        info = GROUPS[group](db, now_ist())
        info["peak_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
        L.note_cycle(db, group, True, time.time() - t0, info)
        log.info("%s done in %.1fs: %s", group, time.time() - t0, info)
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("%s failed", group)
        L.note_cycle(db, group, False, time.time() - t0, {}, str(exc)[:500])
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
