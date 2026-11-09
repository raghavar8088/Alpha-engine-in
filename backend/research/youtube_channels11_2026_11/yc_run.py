"""One book of the 11-channel study on one market: signals, exits and fills exactly as the paper desk runs them (the desk's
runner calls `run`), plus the pool-level pieces (the NIFTY gap for NJ-01, the daily context for NJ-20, the 09:25 breadth
for SS-03, the NSE daily turnover the volume rules read, and NJ-25's basket)."""

from __future__ import annotations

import copy

import numpy as np

import yc_strategies as YS
from yc_engine import XEngine, forced_exit_rows_x, run_book_x
from yc_strategies import STRATEGIES

YC_CACHE = "__yc__"            # the study's indicator caches live under this key of the desk's per-market cache


class LazyBars(dict):
    """tf -> Bars, built on first use (bb_markets.bars) and kept in the shared per-market cache."""

    def __init__(self, m, cache: dict):
        super().__init__()
        self.m, self.cache = m, cache

    def __missing__(self, tf):
        import bb_markets as BM
        if tf not in self.cache:
            self.cache[tf] = BM.bars(self.m, tf)
        self[tf] = self.cache[tf]
        return self[tf]


def live_k_end(m, f):
    """The forced exit per day, except that the last, still-running day has no exit row until its session end arrives:
    there the last row so far is the end (as the desk's runner.live_k_end)."""
    last_day = m.n_days - 1
    end = int(m.d1[last_day] - 1) if m.n_days else -1

    def k_end(d):
        r = f(d)
        return end if (r is None and d == last_day) else r
    return k_end


def prepare(sid: str, market: str, m):
    """The market as the book sees it: overnight books may hold positions across sessions."""
    st = STRATEGIES[sid]
    if st.is_overnight(market) and not getattr(m, "overnight", False):
        m = copy.copy(m)
        m.overnight = True
    return m


def signals(sid: str, market: str, m, cache: dict, p: dict | None = None, other=None):
    """The strategy's signals on one market, sorted by row (only for kind 'signals')."""
    st = STRATEGIES[sid]
    m = prepare(sid, market, m)
    yc = cache.setdefault(YC_CACHE, {})
    B = LazyBars(m, cache)
    p = p or {}
    if "ETHUSD" in st.needs:
        o = None if other is None else (other, LazyBars(other, {}))
        S = st.fn(m, B, p, yc, o)
    else:
        S = st.fn(m, B, p, yc)
    S = sorted(S, key=lambda s: (s.k, s.side, s.setup))
    return S


def run(sid: str, market: str, m, cache: dict, p: dict | None = None, other=None, since_t: int | None = None,
        risk_pct: float = 0.01):
    """(trades, rejects, signals) of one book. `since_t`: a book that starts at a given minute starts flat, so only
    entries at or after it count (signals whose entry row starts before it are dropped; multi-leg books keep the legs
    entered from it)."""
    st = STRATEGIES[sid]
    m = prepare(sid, market, m)
    yc = cache.setdefault(YC_CACHE, {})
    B = LazyBars(m, cache)
    p = p or {}
    eng = XEngine(m)
    clock, minute = st.exit_clock(market)
    ke = live_k_end(m, forced_exit_rows_x(m, clock, minute))
    since_k = 0 if since_t is None else int(np.searchsorted(m.t, since_t, "left"))
    if st.kind == "signals":
        S = signals(sid, market, m, cache, p, other)
        if since_t is not None:
            S = [s for s in S if int(m.t[min(s.k + 1, len(m.t) - 1)]) >= since_t]
        if not S:
            return [], {}, S
        ex = st.exits(m, B, p, yc)
        tr, rej = run_book_x(eng, S, ex, st.limits, ke, sid, "V0", st.reverse)
        return tr, rej, S
    if st.kind == "trades":
        tr = st.fn(m, B, p, yc, eng, ke, sid)
    elif st.kind == "room":
        tr = st.fn(m, B, p, yc, eng, sid, since_k)
    elif st.kind == "ladder":
        tr = st.fn(m, B, p, yc, eng, risk_pct, since_k, sid)
    else:
        raise ValueError(f"{sid}: kind {st.kind} runs over the whole pool (run_basket)")
    tr = [t for t in tr if t.entry_k >= since_k]
    return sorted(tr, key=lambda t: (t.entry_k, t.side)), {}, []


def run_basket(sid: str, markets, since_t: int | None = None) -> dict:
    """NJ-25 over the NSE daily pool: {symbol: trades}."""
    st = STRATEGIES[sid]
    ms = [prepare(sid, "NSED", m) for m in markets]
    out = st.fn(ms, sid)
    if since_t is not None:
        by = {m.name: m for m in ms}
        out = {k: [t for t in v if int(by[k].t[t.entry_k]) >= since_t] for k, v in out.items()}
    return out


# ── pool contexts ─────────────────────────────────────────────────────────────────────────

def nifty_gap(nifty) -> dict:
    """{date: the 09:15 open over the previous session's close, less one} from the NIFTY index minutes (NJ-01)."""
    out = {}
    if nifty is None:
        return out
    for d in range(1, nifty.n_days):
        if not nifty.prev_ok[d]:
            continue
        a = int(nifty.d0[d])
        if int(nifty.ist[a]) != 9 * 60 + 15:
            continue
        pc = float(nifty.c[nifty.d1[d - 1] - 1])
        if pc > 0:
            out[str(nifty.date[d])] = float(nifty.o[a]) / pc - 1
    return out


def attach_value(daily_markets, npz_path) -> None:
    """Each NSE daily market's traded value per row (the bhavcopy turnover), read from the panel file the markets were
    built from: the volume rules (NJ-19, NJ-26) and NJ-20's top-100 list use it."""
    with np.load(npz_path, allow_pickle=False) as z:
        code, names, value = z["code"], z["names"], z["value"]
    starts = np.flatnonzero(np.r_[True, code[1:] != code[:-1]])
    ends = np.r_[starts[1:], len(code)]
    where = {str(names[code[a]]): (a, b) for a, b in zip(starts, ends)}
    for m in daily_markets:
        a, b = where[m.name]
        if b - a == len(m.c):
            m.value = np.asarray(value[a:b], float)


def contexts(needs: set, *, nifty=None, nsed=None, pool=None) -> dict:
    """The p["ctx"] a pool book needs."""
    ctx = {}
    if "nifty_gap" in needs:
        ctx["nifty_gap"] = nifty_gap(nifty)
    if "nj20" in needs and nsed is not None:
        import yc_nj_india as NI
        ctx.update(NI.nj20_context(nsed))
    if "ss03" in needs and pool is not None:
        import yc_channels as C
        ctx["ss03"] = C.ss03_context(pool)
    return ctx


def needs_of(sids) -> set:
    return {n for s in sids for n in YS.STRATEGIES[s].needs}
