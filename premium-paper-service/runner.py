"""One book on one market: the study's own signal function, fill engine and forced exit, unchanged.

A partial session needs no special handling in the rules. A bar still forming ends on the last row of the data, so a
signal on it has no next row to fill on, and an exit flag on it lands past the end of the data. The research's
truncation tests prove the rest (signals do not change when later data is cut off). The only addition here is telling a
real "time" exit from a position that is simply still open at the end of the data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

import bb15
from research import BE, BM, BS, CS, YE, YS


def _bars(m, tfs, cache: dict) -> dict:
    for tf in tfs:
        if tf not in cache:
            cache[tf] = BM.bars(m, tf)
    return cache


def is_overnight(sid: str, market: str) -> bool:
    """Positions may stay open across sessions, so the whole paper period is replayed every time."""
    if sid.startswith("YT"):
        st = YS.STRATEGIES[sid]
        return st.kind in ("overnight", "daily", "stockdaily") or market in ("SPX500_D", "NAS100_D", "NIFTY_D", "NSED")
    return False


def run_bb(sid: str, variant: str, m, cache: dict, other=None) -> tuple[list, dict]:
    if sid == "BB-15":
        B = _bars(m, (bb15.TF,), cache)
        ex = BE.Exits(**bb15.EXITS)
        clock, minute = bb15.EXIT_CLOCK
        return BE.run_book(BE.Engine(m), bb15.signals(m, B), ex, bb15.LIMITS, BE.forced_exit_rows(m, clock, minute), sid, variant)
    st = BS.STRATEGIES[sid]
    v = next(x for x in st.variants if x.tag == variant)
    tfs = set(st.tfs) | {v.sig.get("tf", st.base_sig.get("tf", st.tfs[0]))}
    if v.exits.get("trail_tf"):
        tfs.add(v.exits["trail_tf"])
    B = _bars(m, sorted(tfs), cache)
    S = BS.signals(st, m, B, v.sig, other)
    ex = BS.exits_for(v, B)
    clock, minute = st.exit_clock[m.name]
    return BE.run_book(BE.Engine(m), S, ex, st.limits, BE.forced_exit_rows(m, clock, minute), sid, variant)


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
        return [], {}
    ex = YS.exits_for(st, v, m, B)
    clock, minute = st.exit_clock[market]
    return YE.run_book(YE.Engine(m), S, ex, st.limits, YE.forced_exit_rows(m, clock, minute), sid, variant)


def run_cp(sid: str, market: str, m, cache: dict, other=None) -> tuple[list, dict]:
    """A Crypto-playlist strategy (backend/research/crypto_playlist_2026_11) through the YouTube study's engine.
    `other` is the companion market of CP-24 (SMT divergence), already cut to the same span."""
    st = CS.STRATEGIES[sid]
    tfs = CS.tfs_of(st, market)
    B = _bars(m, tfs, cache)
    o = (other, {tf: BM.bars(other, tf) for tf in tfs}) if other is not None else None
    S = CS.signals(st, market, m, B, cache, o)
    if not S:
        return [], {}
    clock, minute = st.exit_clock[market]
    return YE.run_book(YE.Engine(m), S, CS.exits_for(st), st.limits, YE.forced_exit_rows(m, clock, minute), sid, "V0")


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
