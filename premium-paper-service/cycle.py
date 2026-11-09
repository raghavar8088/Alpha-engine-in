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
from datetime import date, datetime, timedelta, timezone

import numpy as np

import catalog as C
import feeds as F
import ledger as L
import runner as R
import vwap_run
from research import CS, YM
from settings import (BTC_START_DATE, BTC_START_T, DAILY_WARM_DAYS, PAPER_START, SH_START_T, YC_BTC_WARM_DAYS, YC_START_DATE,
                      YC_START_T, now_ist)

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
    to_docs = R.yc_docs if a.source == C.YC else R.docs_from
    docs = [d for d in to_docs(trades, m, a.id, market, overnight, live_day) if d["date"] >= start.isoformat()]
    return L.persist(db, a.id, market, docs, start.isoformat(), final, overnight)


def _yc_from(db, acct: str, market: str, overnight: bool) -> date:
    """An 11-channel book replays from its start day; an overnight one replays all of its period every time."""
    if overnight:
        return YC_START_DATE
    s = L.sealed_through(db, acct, market)
    return max(YC_START_DATE, _next(s)) if s else YC_START_DATE


def _from(db, a, market: str, overnight: bool = False) -> date:
    return _yc_from(db, a.id, market, R.is_overnight(a.id, market)) if a.source == C.YC else replay_from(db, a.id, market, overnight)


# ── index ────────────────────────────────────────────────────────────────────────────

def run_index(db, now: datetime) -> dict:
    books = [(a, mk, v, _from(db, a, mk)) for a, mk, v in C.books_in("index")]
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
            elif a.source == C.LS:
                import liquidity_sweep as LSW          # here, so the other groups never load the strategy classes
                tr = LSW.run(v, market, m, start, caches[market])
            elif a.source == C.YC:
                tr, _ = R.run_yc(a.id, market, yt_m[market], caches[market], since_t=YC_START_T)
            else:
                tr, _ = R.run_yt(a.id, v, market, yt_m[market], caches[market])
            n_docs += _save_book(db, a, market, tr, m, R.is_overnight(a.id, market) if a.source == C.YC else False, start, final,
                                 live_day)
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
    pool_books = [(a, mk, v, _from(db, a, mk)) for a, mk, v in C.books_in("stocks") if mk != "VWAP"]
    yc_ctx = _yc_stock_context(pool_books, panel, now)
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
                if a.source == C.YC:
                    tr, _ = R.run_yc(a.id, mk, m, cache, {"ctx": yc_ctx}, since_t=YC_START_T)
                else:
                    tr, _ = R.run_yt(a.id, v, mk, m, cache)
            except Exception as exc:  # noqa: BLE001
                errors.setdefault(f"{a.id}|{mk}", str(exc)[:200])
                continue
            if tr:
                to_docs = R.yc_docs if a.source == C.YC else R.docs_from
                collected[(a.id, mk)] += [d for d in to_docs(tr, m, a.id, mk, False, panel.live_day, rank) if d["date"] >= start.isoformat()]
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


def _yc_stock_context(pool_books, panel, now: datetime) -> dict:
    """What the 11-channel stock books read beyond each stock's own bars: NIFTY's opening gap (NJ-01), the NSE daily
    candidates (NJ-20) and the pool's 09:25 breadth (SS-03). Built only when such a book is in the cycle."""
    needs = R.YCR.needs_of([a.id for a, _, _, _ in pool_books if a.source == C.YC])
    ctx: dict = {}
    try:
        if "nifty_gap" in needs:
            nf = F.index_market("NIFTY", YC_START_DATE - timedelta(days=10), F.today_bars("index").get("NIFTY"), now)[0]
            ctx["nifty_gap"] = R.YCR.nifty_gap(nf)
        if "nj20" in needs:
            dm = F.nse_daily_markets()
            R.YCR.attach_value(dm, F.NSE_FILE)
            ctx.update(R.YCR.contexts({"nj20"}, nsed=dm))
        if "ss03" in needs:
            ctx.update(R.YCR.contexts({"ss03"}, pool=(panel.market(i) for i in range(len(panel.names)))))
    except Exception:  # noqa: BLE001 - a missing context only leaves its book without setups
        log.exception("11-channel stock context")
    return ctx


# ── forex, gold, US ──────────────────────────────────────────────────────────────────

YAHOO_EVERY_S = 540      # the cycle runs every 2 minutes for Delta Exchange; Yahoo is asked at most every 9 minutes


def run_global(db, now: datetime) -> dict:
    new, errors = {}, {}
    yahoo_due = time.time() - float((db.premium_meta.find_one({"_id": "yahoo_at"}) or {}).get("t") or 0) >= YAHOO_EVERY_S
    for name in (F.YF if yahoo_due else ()):
        try:
            new[name] = F.update_minutes(name)["new"]
        except Exception as exc:  # noqa: BLE001 - a market that cannot be fetched just waits for the next cycle
            errors[f"feed {name}"] = str(exc)[:200]
        time.sleep(0.5)
    for _sym, _mk in (("BTCUSD", "BTCUSD"), ("XAUTUSD", "XAUUSD"), ("ETHUSD", "ETHUSD")):
        try:
            new[_mk] = F.update_delta_candles(symbol=_sym)["new"]
        except Exception as exc:  # noqa: BLE001
            errors[f"feed {_mk}"] = str(exc)[:200]
    try:                                       # once: older bitcoin minutes for the 11-channel books' warm-up
        warm = (now.date() - YC_START_DATE).days + YC_BTC_WARM_DAYS + 1
        bf = F.backfill_delta_candles("BTCUSD", warm)
        if bf.get("new"):
            new["BTCUSD_backfill"] = bf["new"]
    except Exception as exc:  # noqa: BLE001
        errors["feed BTCUSD backfill"] = str(exc)[:200]
    try:
        rates = F.usdinr() if yahoo_due else None
        if rates:
            db.premium_meta.update_one({"_id": "fx"}, {"$set": {f"rates.{k}": v for k, v in rates.items()}}, upsert=True)
    except Exception as exc:  # noqa: BLE001
        errors["usdinr"] = str(exc)[:200]
    if yahoo_due:
        db.premium_meta.update_one({"_id": "yahoo_at"}, {"$set": {"t": time.time()}}, upsert=True)
    sig = "|".join(f"{n}:{F.last_minute(n)}" for n in sorted(F.YF) + sorted(F.DELTA_STORES.values())) + "|" + "|".join(F.global_final_day(n) for n in ("EURUSD", "NAS100"))
    if sig == L.signature(db, "global"):
        return {"skipped": "no new bars", "errors": errors}
    if now.date() < min(PAPER_START - timedelta(days=1), BTC_START_DATE):
        L.set_signature(db, "global", sig)
        return {"waiting_for": PAPER_START.isoformat(), "new": new, "errors": errors}
    books = [(a, mk, v, R.is_overnight(a.id, mk)) for a, mk, v in C.books_in("global")]
    n_docs, touched = 0, set()
    fixed_since = PAPER_START - timedelta(days=GLOBAL_WARM_DAYS)
    for name in list(F.YF) + ["XAUUSD"]:
        full = F.gold_market(fixed_since) if name == "XAUUSD" else F.global_market(name, fixed_since)
        if full is None:
            continue
        final = F.global_final_day(name)
        last_day = str(full.date[-1])
        live_day = last_day if last_day > final else None
        mine = [b for b in books if b[1] == name or C.YC_BOOK_MARKET.get(b[1]) == name]
        firsts = [_from(db, a, bmk) for a, bmk, _, on in mine if not on]
        recent = F.slice_from(full, min(firsts) - timedelta(days=GLOBAL_WARM_DAYS)) if firsts else None
        ym_full, ym_recent = YM._as_mkt(full, name, name, F.yt_cost(name)), YM._as_mkt(recent, name, name, F.yt_cost(name)) if recent is not None else None
        c_full, c_recent = {}, {}
        for a, bmk, v, on in mine:
            m = full if on else recent
            if m is None:
                continue
            start = _from(db, a, bmk, on)
            try:
                if a.source == C.BB:
                    tr, _ = R.run_bb(a.id, v, m, c_full if on else c_recent)
                elif a.source == C.YC:
                    tr, _ = R.run_yc(a.id, bmk, ym_full if on else ym_recent, c_full if on else c_recent, since_t=YC_START_T,
                                     risk_pct=C.MONEY[bmk].risk_pct)
                elif a.source == C.CP:
                    tr, _ = R.run_cp(a.id, name, ym_full if on else ym_recent, c_full if on else c_recent,
                                     _companion(a.id, name, m))
                else:
                    tr, _ = R.run_yt(a.id, v, name, ym_full if on else ym_recent, c_full if on else c_recent)
                n_docs += _save_book(db, a, bmk, tr, m, on, start, final, live_day)
                touched.add(a.id)
            except Exception as exc:  # noqa: BLE001
                log.exception("%s %s", a.id, bmk)
                errors[f"{a.id}|{bmk}"] = str(exc)[:200]
    # bitcoin (Delta Exchange BTCUSD): the Crypto-playlist books, all intraday, trading from BTC_START_T
    btc_books = [b for b in books if b[1] == "BTCUSD" and b[0].source != C.YC]
    if btc_books:
        firsts = [_btc_replay_from(db, a.id) for a, _, _, _ in btc_books]
        bm = F.btc_market(min(firsts) - timedelta(days=GLOBAL_WARM_DAYS))
        if bm is not None:
            final = F.btc_final_day()
            last_day = str(bm.date[-1])
            live_day = last_day if last_day > final else None
            cache: dict = {}
            for a, _, v, _ in btc_books:
                start, t_start = _btc_replay_from(db, a.id), _btc_start(a.id)
                try:
                    if a.source == C.SH:
                        tr, _ = R.run_sh(a.id, bm, cache, since_t=t_start)
                    else:
                        tr, _ = R.run_cp(a.id, "BTCUSD", bm, cache, since_t=t_start)
                    docs = [d for d in R.docs_from(tr, bm, a.id, "BTCUSD", False, live_day)
                            if d["date"] >= start.isoformat() and d["entry_t"] >= t_start]
                    n_docs += L.persist(db, a.id, "BTCUSD", docs, start.isoformat(), final, False)
                    touched.add(a.id)
                except Exception as exc:  # noqa: BLE001
                    log.exception("%s BTCUSD", a.id)
                    errors[f"{a.id}|BTCUSD"] = str(exc)[:200]
    yc_btc = [b for b in books if b[1] == "BTCUSD" and b[0].source == C.YC]
    if yc_btc:
        n_docs += _run_yc_btc(db, yc_btc, errors, touched)
    if touched:
        L.update_accounts(db, sorted(touched))
    L.set_signature(db, "global", sig)
    return {"trades": n_docs, "new": new, "errors": errors}


def _run_yc_btc(db, books, errors: dict, touched: set) -> int:
    """The 11-channel bitcoin books: Delta BTCUSD from YC_BTC_WARM_DAYS before their start (4-hour EMA 200s), flat at
    YC_START_T; NJ-33 also reads Delta ETHUSD over the same days."""
    bm = F.btc_market(YC_START_DATE - timedelta(days=YC_BTC_WARM_DAYS))
    if bm is None:
        return 0
    final = F.btc_final_day()
    last_day = str(bm.date[-1])
    live_day = last_day if last_day > final else None
    eth = None
    if any("ETHUSD" in R.YCS.STRATEGIES[a.id].needs for a, *_ in books):
        try:
            eth = F.eth_market(date.fromisoformat(str(bm.date[0])))
        except Exception as exc:  # noqa: BLE001
            errors["feed ETHUSD"] = str(exc)[:200]
    k0 = min(int(np.searchsorted(bm.t, YC_START_T, "left")), len(bm.t) - 1)
    box = float(max(1.0, round(float(bm.c[k0]) * 0.01)))      # TH-04: 1% of the first close of its window, then fixed
    cache: dict = {}
    n_docs = 0
    for a, _, _v, on in books:
        start = _yc_from(db, a.id, "BTCUSD", on)
        try:
            st = R.YCS.STRATEGIES[a.id]
            tr, _ = R.run_yc(a.id, "BTCUSD", bm, cache, {"box": box} if "box" in st.needs else {},
                             eth if "ETHUSD" in st.needs else None, since_t=YC_START_T, risk_pct=C.MONEY["BTCUSD"].risk_pct)
            n_docs += _save_book(db, a, "BTCUSD", tr, bm, on, start, final, live_day)
            touched.add(a.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s BTCUSD", a.id)
            errors[f"{a.id}|BTCUSD"] = str(exc)[:200]
    return n_docs


def _btc_start(acct: str) -> int:
    """When a bitcoin book starts: the Crypto-playlist books at BTC_START_T, the Sniper-headshot books at SH_START_T."""
    return SH_START_T if C.BY_ID[acct].source == C.SH else BTC_START_T


def _btc_replay_from(db, acct: str) -> date:
    first = datetime.fromtimestamp(_btc_start(acct), timezone.utc).date()
    s = L.sealed_through(db, acct, "BTCUSD")
    return max(first, _next(s)) if s else first


def _companion(sid: str, market: str, m):
    """CP-24's partner market (silver for gold, GBP/USD for EUR/USD) over the same days as `m`."""
    comp = CS.STRATEGIES[sid].companion.get(market)
    if not comp:
        return None
    since = date.fromisoformat(str(m.date[0]))
    om = F.global_market(comp, since)
    return YM._as_mkt(om, comp, comp, YM.COSTS[comp]) if om is not None else None


# ── daily markets ────────────────────────────────────────────────────────────────────

def run_daily(db, now: datetime) -> dict:
    info = {"nse": F.nse_daily_update(now)}
    since = PAPER_START - timedelta(days=DAILY_WARM_DAYS)
    idx = {"SPX500_D": F.us_daily("SPX500_D"), "NAS100_D": F.us_daily("NAS100_D"), "NIFTY_D": F.nifty_daily(since, now)}
    lasts = {k: str(v.date[-1]) if v is not None else None for k, v in idx.items()}
    sig = f"{lasts}|{info['nse'].get('last')}|btc{F.last_minute('BTCUSD') // 3600}"
    if sig == L.signature(db, "daily"):
        return {**info, "skipped": "no new sessions", "lasts": lasts}
    if now.date() < PAPER_START:
        L.set_signature(db, "daily", sig)
        return {**info, "waiting_for": PAPER_START.isoformat(), "lasts": lasts}
    books = C.books_in("daily")
    n_docs, errors, touched = 0, {}, set()
    for a, mk, v in books:
        if mk in ("NSED", "BTC_SPOT"):
            continue
        m = idx[mk]
        if m is None:
            errors[f"{a.id}|{mk}"] = "no data"
            continue
        try:
            if a.source == C.YC:
                tr, _ = R.run_yc(a.id, mk, m, {}, since_t=YC_START_T)
                n_docs += _save_book(db, a, mk, tr, m, True, YC_START_DATE, lasts[mk], None)
                touched.add(a.id)
                continue
            tr, _ = R.run_yt(a.id, v, mk, m, {})
            n_docs += _save_book(db, a, mk, tr, m, True, PAPER_START, lasts[mk], None)
            touched.add(a.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s %s", a.id, mk)
            errors[f"{a.id}|{mk}"] = str(exc)[:200]
    for a, mk, v in [b for b in books if b[1] == "BTC_SPOT"]:
        try:
            fng = F.fear_greed()
            bm = F.btc_market(PAPER_START - timedelta(days=2))
            docs = R.fear_greed_docs(a.id, fng, bm, PAPER_START.isoformat())
            n_docs += L.persist(db, a.id, mk, docs, PAPER_START.isoformat(), "0000-00-00", True)
            touched.add(a.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s %s", a.id, mk)
            errors[f"{a.id}|{mk}"] = str(exc)[:200]
    pool = [(a, mk, v) for a, mk, v in books if mk == "NSED"]
    if pool:
        collected = {a.id: [] for a, _, _ in pool}
        markets = F.nse_daily_markets()
        R.YCR.attach_value(markets, F.NSE_FILE)        # the traded value per session, read by the 11-channel volume rules
        final = max(str(m.date[-1]) for m in markets) if markets else "0000-00-00"
        for m in markets:
            cache: dict = {}
            # Ties go to the more liquid stock, judged only on what was known at that entry (frozen for ever).
            rank = lambda t, m=m: -float(m.turnover20[t.entry_k])  # noqa: E731
            for a, mk, v in pool:
                try:
                    if a.source == C.YC:
                        if R.YCS.STRATEGIES[a.id].kind == "basket":
                            continue
                        tr, _ = R.run_yc(a.id, mk, m, cache, since_t=YC_START_T)
                    else:
                        tr, _ = R.run_yt(a.id, v, mk, m, cache)
                except Exception as exc:  # noqa: BLE001
                    errors.setdefault(f"{a.id}|NSED", str(exc)[:200])
                    continue
                if tr:
                    to_docs, first = (R.yc_docs, YC_START_DATE) if a.source == C.YC else (R.docs_from, PAPER_START)
                    collected[a.id] += [d for d in to_docs(tr, m, a.id, mk, True, None, rank) if d["date"] >= first.isoformat()]
        by_sym = {m.name: m for m in markets}
        for a, mk, v in pool:
            if a.source != C.YC or R.YCS.STRATEGIES[a.id].kind != "basket":
                continue
            try:                                        # NJ-25: the whole pool's basket at once
                for sym, tr in R.YCR.run_basket(a.id, markets, since_t=YC_START_T).items():
                    m = by_sym[sym]
                    rank = lambda t, m=m: -float(m.turnover20[t.entry_k])  # noqa: E731
                    collected[a.id] += [d for d in R.yc_docs(tr, m, a.id, mk, True, None, rank)
                                        if d["date"] >= YC_START_DATE.isoformat()]
            except Exception as exc:  # noqa: BLE001
                log.exception("%s NSED", a.id)
                errors[f"{a.id}|NSED"] = str(exc)[:200]
        for a, mk, _ in pool:
            docs = R.take_slots(collected[a.id], C.MONEY["NSED"].max_open)
            first = YC_START_DATE if a.source == C.YC else PAPER_START
            n_docs += L.persist(db, a.id, mk, docs, first.isoformat(), final, True)
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
        import segments as SG
        SG.refresh(db, group, info)
        log.info("%s done in %.1fs: %s", group, time.time() - t0, info)
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("%s failed", group)
        L.note_cycle(db, group, False, time.time() - t0, {}, str(exc)[:500])
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
