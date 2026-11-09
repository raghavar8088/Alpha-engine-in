"""One book on one market: the study's own signal function, fill engine and forced exit, unchanged.

A partial session needs no special handling in the rules. A bar still forming ends on the last row of the data, so a
signal on it has no next row to fill on, and an exit flag on it lands past the end of the data. The research's
truncation tests prove the rest (signals do not change when later data is cut off). The only addition here is telling a
real "time" exit from a position that is simply still open at the end of the data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

import bb15
from research import BE, BM, BS, CS, YCR, YCS, YE, YS


def _bars(m, tfs, cache: dict) -> dict:
    for tf in tfs:
        if tf not in cache:
            cache[tf] = BM.bars(m, tf)
    return cache


def is_overnight(sid: str, market: str) -> bool:
    """Positions may stay open across sessions, so the whole paper period is replayed every time."""
    if sid in YCS.STRATEGIES:
        return YCS.STRATEGIES[sid].is_overnight(market)
    if sid.startswith("YT"):
        st = YS.STRATEGIES[sid]
        return st.kind in ("overnight", "daily", "stockdaily") or market in ("SPX500_D", "NAS100_D", "NIFTY_D", "NSED")
    return False


def run_bb(sid: str, variant: str, m, cache: dict, other=None) -> tuple[list, dict]:
    if sid == "BB-15":
        B = _bars(m, (bb15.TF,), cache)
        ex = BE.Exits(**bb15.EXITS)
        clock, minute = bb15.EXIT_CLOCK
        S, eng, ke = bb15.signals(m, B), BE.Engine(m), live_k_end(m, BE.forced_exit_rows(m, clock, minute))
        tr, rej = BE.run_book(eng, S, ex, bb15.LIMITS, ke, sid, variant)
        note_signals(f"{sid}|{m.name}", m, S, tr, rej, lambda S2: BE.run_book(eng, S2, ex, bb15.LIMITS, ke, sid, variant))
        return tr, rej
    st = BS.STRATEGIES[sid]
    v = next(x for x in st.variants if x.tag == variant)
    tfs = set(st.tfs) | {v.sig.get("tf", st.base_sig.get("tf", st.tfs[0]))}
    if v.exits.get("trail_tf"):
        tfs.add(v.exits["trail_tf"])
    B = _bars(m, sorted(tfs), cache)
    S = BS.signals(st, m, B, v.sig, other)
    ex = BS.exits_for(v, B)
    clock, minute = st.exit_clock[m.name]
    eng, ke = BE.Engine(m), live_k_end(m, BE.forced_exit_rows(m, clock, minute))
    tr, rej = BE.run_book(eng, S, ex, st.limits, ke, sid, variant)
    note_signals(f"{sid}|{m.name}", m, S, tr, rej, lambda S2: BE.run_book(eng, S2, ex, st.limits, ke, sid, variant))
    return tr, rej


def run_yt(sid: str, variant: str, market: str, m, cache: dict) -> tuple[list, dict]:
    st = YS.STRATEGIES[sid]
    st._mk = market
    v = next(x for x in st.variants if x.tag == variant)
    if st.kind == "overnight" and not m.overnight:      # as yt_run.markets_for
        m = copy.copy(m)
        m.overnight = True
    tfs = set(st.tfs) | {v.sig.get("tf", st.tfs[0])}
    if v.exits.get("trail_tf"):
        tfs.add(v.exits["trail_tf"])
    B = _bars(m, sorted(tfs), cache)
    S = st.fn(m, B, v.sig)
    if not S:
        note_signals(f"{sid}|{market}", m, S, [], {})
        return [], {}
    ex = YS.exits_for(st, v, m, B)
    clock, minute = st.exit_clock[market]
    eng, ke = YE.Engine(m), live_k_end(m, YE.forced_exit_rows(m, clock, minute))
    tr, rej = YE.run_book(eng, S, ex, st.limits, ke, sid, variant)
    note_signals(f"{sid}|{market}", m, S, tr, rej,
                 None if market in POOLS else (lambda S2: YE.run_book(eng, S2, ex, st.limits, ke, sid, variant)))
    return tr, rej


def run_cp(sid: str, market: str, m, cache: dict, other=None, since_t: int | None = None) -> tuple[list, dict]:
    """A Crypto-playlist strategy (backend/research/crypto_playlist_2026_11) through the YouTube study's engine.
    `other` is the companion market of CP-24 (SMT divergence), already cut to the same span. `since_t`: a book that
    starts mid-session starts flat, so only setups whose entry bar opens at or after it can trade."""
    st = CS.STRATEGIES[sid]
    tfs = CS.tfs_of(st, market)
    B = _bars(m, tfs, cache)
    o = (other, {tf: BM.bars(other, tf) for tf in tfs}) if other is not None else None
    S = CS.signals(st, market, m, B, cache, o)
    if since_t is not None:
        S = [s for s in S if int(m.t[min(s.k + 1, len(m.t) - 1)]) >= since_t]
    if not S:
        note_signals(f"{sid}|{market}", m, S, [], {})
        return [], {}
    clock, minute = st.exit_clock[market]
    eng, ex, ke = YE.Engine(m), CS.exits_for(st), live_k_end(m, YE.forced_exit_rows(m, clock, minute))
    tr, rej = YE.run_book(eng, S, ex, st.limits, ke, sid, "V0")
    note_signals(f"{sid}|{market}", m, S, tr, rej, lambda S2: YE.run_book(eng, S2, ex, st.limits, ke, sid, "V0"))
    return tr, rej


def fear_greed_docs(acct: str, fng: dict, btc, start: str, cost_pct: float = 0.0007) -> list[dict]:
    """CP-29: every Monday from `start` with the Fear & Greed Index below 45, a buy at that UTC day's first minute.
    Positions are never closed; each is marked at the last price, net of a round trip of costs."""
    if btc is None or not len(btc.t):
        return []
    last = float(btc.c[-1])
    out = []
    for d in range(btc.n_days):
        day = str(btc.date[d])
        if day < start or np.datetime64(day, "D").astype(object).weekday() != 0:
            continue
        v = fng.get(day)
        if v is None or v >= 45:
            continue
        k = int(btc.d0[d])
        entry = float(btc.o[k])
        cost = cost_pct * (entry + last)
        out.append({"_id": f"{acct}|BTC_SPOT|BTC|{int(btc.t[k])}|1", "acct": acct, "book": f"{acct}|BTC_SPOT", "mkt": "BTC_SPOT",
                    "sym": "BTC", "variant": "V0", "setup": f"FEAR_{int(v)}", "side": 1, "date": day, "entry_t": int(btc.t[k]),
                    "exit_t": None, "exit_date": day, "entry": entry, "stop": None, "target": None, "exit": last, "reason": "open",
                    "unit": entry, "r_net": (last - entry - cost) / entry, "r_gross": (last - entry) / entry, "cost_r": cost / entry,
                    "open": True, "last": last, "rank": None})
    return out


def num(x):
    x = float(x)
    return x if np.isfinite(x) else None


def run_sh(sid: str, m, cache: dict, since_t: int | None = None) -> tuple[list, dict]:
    """A Sniper-headshot book (sniper.py) on bitcoin: its first entries through the YouTube study's engine and book rules
    (one at a time, at most 3 a day), then each first entry's second entry, the retest add, as its own position while
    the first is still open. `since_t` as in run_cp: the book starts flat."""
    import sniper as SH
    v = SH.VERSIONS[sid]
    B = _bars(m, tuple(sorted({v.tf, v.htf})), cache)
    S = SH.signals(sid, m, B, cache)
    if since_t is not None:
        S = [s for s in S if int(m.t[min(s.k + 1, len(m.t) - 1)]) >= since_t]
    key = f"{sid}|BTCUSD"
    if not S:
        note_signals(key, m, S, [], {})
        return [], {}
    ex = SH.exits(sid)
    clock, minute = SH.EXIT_CLOCK
    eng, ke = YE.Engine(m), live_k_end(m, YE.forced_exit_rows(m, clock, minute))
    tr, rej = YE.run_book(eng, S, ex, SH.LIMITS, ke, sid, "E1")
    note_signals(key, m, S, tr, rej, lambda S2: YE.run_book(eng, S2, ex, SH.LIMITS, ke, sid, "E1"))
    by_k = {s.k: s for s in S}
    adds = []
    for t in tr:
        s2 = SH.pyramid(sid, m, B, cache, t, by_k[t.sig_k]) if t.sig_k in by_k else None
        k_end = ke(s2.day) if s2 is not None else None
        if s2 is not None and k_end is not None:
            t2, _ = eng.trade(s2, ex, k_end, sid, "E2")
            if t2 is not None:
                adds.append(t2)
    return sorted(tr + adds, key=lambda x: x.entry_k), rej


def run_yc(sid: str, market: str, m, cache: dict, p: dict | None = None, other=None, since_t: int | None = None,
           risk_pct: float = 0.01) -> tuple[list, dict]:
    """An 11-channel book (backend/research/youtube_channels11_2026_11): yc_run.run, the code the look-ahead checks ran.
    `since_t` as in run_cp: the book starts flat at that minute."""
    rules_mk = YC_RULES_MARKET.get(market, market)
    tr, rej, S = YCR.run(sid, rules_mk, m, cache, p, other, since_t, risk_pct)
    key = f"{sid}|{market}"
    st = YCS.STRATEGIES[sid]
    if st.kind == "signals" and market not in POOLS and S:
        from yc_engine import XEngine, forced_exit_rows_x, run_book_x
        mm = YCR.prepare(sid, rules_mk, m)
        ex = st.exits(mm, YCR.LazyBars(mm, cache), {**st.params, **(p or {})}, cache.setdefault(YCR.YC_CACHE, {}))
        clock, minute = st.exit_clock(rules_mk)
        ke = YCR.live_k_end(mm, forced_exit_rows_x(mm, clock, minute))
        eng = XEngine(mm)
        note_signals(key, mm, S, tr, rej, lambda S2: run_book_x(eng, S2, ex, st.limits, ke, sid, "V0", st.reverse))
    else:
        note_signals(key, m, S, tr, rej)
    return tr, rej


YC_RULES_MARKET = {"XAUTUSD": "XAUUSD"}       # a book market -> the market its strategy's rules were written for


def yc_docs(trades, m, acct: str, market: str, overnight: bool, live_day: str | None, rank=None) -> list[dict]:
    """docs_from with ids made unique: a multi-leg book (PR-12's ladder, IT-02's two lots) can open two legs of one side
    in the same minute; the later ones get #2, #3 (trades are in a fixed order, so the ids are stable)."""
    out = docs_from(trades, m, acct, market, overnight, live_day, rank)
    seen: dict = {}
    for d in out:
        n = seen.get(d["_id"], 0) + 1
        seen[d["_id"]] = n
        if n > 1:
            d["_id"] = f"{d['_id']}#{n}"
    return out


def docs_from(trades, m, acct: str, market: str, overnight: bool, live_day: str | None, rank=None) -> list[dict]:
    """Engine trades as ledger documents (per-unit economics; the account sizes them later)."""
    last = len(m.t) - 1
    out = []
    for t in trades:
        exit_date = str(m.date[m.day[t.exit_k]])
        still_open = t.reason == "time" and t.exit_k == last and (overnight or exit_date == live_day)
        sym = m.name if market in ("NSE15", "NSE5", "NSED") else market
        entry_t = int(m.t[t.entry_k])
        out.append({
            "_id": f"{acct}|{market}|{sym}|{entry_t}|{t.side}", "acct": acct, "book": f"{acct}|{market}", "mkt": market, "sym": sym,
            "variant": t.variant, "setup": t.setup, "side": int(t.side), "date": t.date, "entry_t": entry_t,
            "exit_t": None if still_open else int(m.t[t.exit_k]), "exit_date": exit_date, "entry": num(t.entry),
            "stop": num(t.stop), "target": num(t.target), "exit": num(t.exit), "reason": "open" if still_open else t.reason,
            "unit": num(t.risk), "r_net": num(t.r_net), "r_gross": num(t.r_gross), "cost_r": num(t.cost_r),
            "open": bool(still_open), "last": num(m.c[last]), "rank": rank(t) if callable(rank) else rank,
        })
    return out


def take_slots(docs: list[dict], max_open: int) -> list[dict]:
    """The VWAP study's book rule for pools of stocks: time order, ties to the more liquid (or, for U4, the highest
    relative volume); at most max_open positions; a position exiting in this row still holds its slot at the row's open."""
    docs = sorted(docs, key=lambda d: (d["entry_t"], d["rank"] if d["rank"] is not None else 1e9, d["sym"]))
    taken, busy = [], []
    for d in docs:
        busy = [x for x in busy if x is None or x >= d["entry_t"]]
        if len(busy) < max_open:
            taken.append(d)
            busy.append(d["exit_t"])            # None: still open
    return taken


# ── the live day, and each book's latest setup ──────────────────────────────────────────

LAST_SIGNALS: dict = {}
WHY = {"position_open": "a trade was already open", "day_closed": "the day was already closed by a stop or a target",
       "day_limit": "the day's trade limit was reached", "needs_prior_stop": "a second trade needs a stop first",
       "after_forced_exit": "too close to the session's end", "no_row_left": "no bar was left to fill on",
       "stop_entry_not_triggered": "its entry order did not trigger", "stop_entry_expired": "its entry order expired",
       "limit_not_filled": "its limit order was not filled", "limit_expired": "its limit order expired",
       "entry_beyond_stop": "price opened beyond the stop", "entry_beyond_target": "price opened beyond the target",
       "oco_both_same_row": "both entry orders triggered in the same minute"}


def live_k_end(m, f):
    """The study's forced exit per day, except that the last, still-running day has no exit row until its session end
    arrives: there the last bar so far is the end, so its setups are taken and its trades stay open."""
    last_day = m.n_days - 1
    end = int(m.d1[last_day] - 1) if m.n_days else -1

    def k_end(d):
        r = f(d)
        return end if (r is None and d == last_day) else r
    return k_end


POOLS = {"NSE15", "NSE5", "NSED", "MIRROR15", "VWAP"}     # one book over many stocks, run one stock at a time


def note_signals(key: str, m, signals, trades, rejects, rerun=None) -> None:
    """For the status page: a book's setups on the market's latest day, and what became of the latest one. The reason
    is the engine's own: the book is run once more without that setup, and the reject count that changes names it.
    A pool of stocks is run one stock at a time: its counts add up and it has no single reason."""
    try:
        prev = LAST_SIGNALS.get(key)
        if not len(m.t) or not m.n_days or not signals:
            if prev is None:
                LAST_SIGNALS[key] = {"n_today": 0, "last_t": None, "today": False, "taken": None, "why": None}
            return
        last_day = m.n_days - 1
        i = max(range(len(signals)), key=lambda j: (signals[j].k, j))
        s = signals[i]
        info = {"n_today": sum(1 for x in signals if x.day == last_day), "last_t": int(m.t[min(s.k, len(m.t) - 1)]),
                "today": bool(s.day == last_day), "taken": None, "why": None}
        if prev is not None:
            info["n_today"] += prev.get("n_today") or 0
            if (prev.get("last_t") or 0) > info["last_t"]:
                info["last_t"], info["today"] = prev["last_t"], prev.get("today")
            info["pool"] = True
        elif info["today"] and rerun is not None:
            tr0, rej0 = rerun(signals[:i] + signals[i + 1:])
            info["taken"] = len(trades) > len(tr0)
            if not info["taken"]:
                grew = [k for k, n in rejects.items() if n > rej0.get(k, 0)]
                info["why"] = WHY.get(grew[0], grew[0]) if grew else None
        LAST_SIGNALS[key] = info
    except Exception:  # noqa: BLE001 - a status note must never stop a book
        pass
