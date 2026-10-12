"""Indian Index Intraday: the strategy families of the brief, each with a fixed grid.

Every family turns one series (ii_data.Days) into, per day, a function `specs(after_minute)`
returning the next EntrySpec at or after a minute (or None), plus an optional signal-exit
function. Indicators are computed CAUSALLY on the continuous intraday series (days x bars
flattened, so the first bars of a day see the previous day's bars — never the future), and a
decision on bar k is acted on at minute end[k] + 1. Daily ATR(14) uses prior days only.

Families (the brief's list): opening-range breakout, previous-day high/low breakout,
volatility breakout from the open, intraday momentum (first half hour -> last half hour), EMA
crossover, Supertrend (with and without an ADX trend-strength filter), RSI momentum and RSI
mean reversion, Bollinger mean reversion, VWAP reversion and VWAP trend (index: a session
time-weighted average — indexes print no volume; ETF track: true VWAP), trend pullback,
multi-timeframe confirmation, a VIX-regime switch, and gap fade / gap follow.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np

from .data import SESSION_MIN, Days, bars, minute_of
from .engine import ENTRY_CUTOFF, EntrySpec, ExitCfg


# ── causal indicators on a flattened (days x bars) series ───────────────────────


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x)
    s = x[0]
    for i in range(len(x)):
        s = a * x[i] + (1 - a) * s if i else x[0]
        out[i] = s
    return out


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's moving average."""
    out = np.empty_like(x)
    s = np.nan
    for i in range(len(x)):
        if i < n - 1:
            out[i] = np.nan
            continue
        if i == n - 1:
            s = np.nanmean(x[:n])
        else:
            s = (s * (n - 1) + x[i]) / n
        out[i] = s
    return out


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        out = 100 - 100 / (1 + rs)
    out[ad == 0] = 100.0
    return out


def true_range(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def supertrend(h, l, c, n: int, mult: float) -> np.ndarray:
    """+1 / -1 trend of the classic Supertrend."""
    atr = rma(true_range(h, l, c), n)
    mid = (h + l) / 2
    ub, lb = mid + mult * atr, mid - mult * atr
    fub, flb = ub.copy(), lb.copy()
    trend = np.ones(len(c))
    for i in range(1, len(c)):
        if np.isnan(atr[i]):
            trend[i] = trend[i - 1]
            continue
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if trend[i - 1] > 0:
            trend[i] = -1 if c[i] < flb[i] else 1
        else:
            trend[i] = 1 if c[i] > fub[i] else -1
    return trend


def adx(h, l, c, n: int = 14) -> np.ndarray:
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = rma(true_range(h, l, c), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * rma(pdm, n) / atr
        ndi = 100 * rma(ndm, n) / atr
        dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
    return rma(np.nan_to_num(dx), n)


def rolling_mean_std(x: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    cs = np.cumsum(np.r_[0.0, x])
    cs2 = np.cumsum(np.r_[0.0, x * x])
    m = np.full(len(x), np.nan)
    s = np.full(len(x), np.nan)
    if len(x) >= n:
        tot = cs[n:] - cs[:-n]
        tot2 = cs2[n:] - cs2[:-n]
        mu = tot / n
        var = np.maximum(tot2 / n - mu * mu, 0.0) * n / max(n - 1, 1)
        m[n - 1:] = mu
        s[n - 1:] = np.sqrt(var)
    return m, s


# ── the per-series context ───────────────────────────────────────────────────────


class Ctx:
    """One series plus cached bars / indicators. `vix` (optional) is India VIX Days aligned by date."""

    def __init__(self, d: Days, vix: Days | None = None):
        self.d = d
        self.vix = vix
        self.cache: dict = {}
        dl = d.daily()
        tr = true_range(dl["h"], dl["l"], dl["c"])
        atr = rma(tr, 14)
        self.day_atr = np.r_[np.nan, atr[:-1]]                 # ATR(14) of PRIOR days
        self.prev_high = np.r_[np.nan, dl["h"][:-1]]
        self.prev_low = np.r_[np.nan, dl["l"][:-1]]
        self.prev_close = np.r_[np.nan, dl["c"][:-1]]
        if vix is not None:
            vmap = {dt: i for i, dt in enumerate(vix.dates)}
            vprev = np.full(len(d), np.nan)
            for i, dt in enumerate(d.dates):
                j = vmap.get(dt)
                if j is not None and j > 0:
                    vprev[i] = vix.c[j - 1, -1]                # yesterday's VIX close
            self.vix_prev = vprev
        else:
            self.vix_prev = None

    def tf(self, tf: int) -> dict:
        k = ("bars", tf)
        if k not in self.cache:
            self.cache[k] = bars(self.d, tf)
        return self.cache[k]

    def flat(self, tf: int, key: str) -> np.ndarray:
        return self.tf(tf)[key].reshape(-1)

    def ind(self, name: str, fn):
        if name not in self.cache:
            self.cache[name] = fn()
        return self.cache[name]


def _first_signal_after(sig_row: np.ndarray, ends: np.ndarray, after_minute: int, want=None) -> tuple[int, int] | None:
    """The first bar k whose decision minute end[k]+1 >= after_minute with a nonzero signal."""
    dec = ends + 1
    row = np.nan_to_num(np.asarray(sig_row, float))     # a not-yet-known (NaN) bar is no signal
    ks = np.nonzero((dec >= after_minute) & (row != 0) & (dec < SESSION_MIN))[0]
    if want is not None:
        ks = ks[row[ks] == want]
    if not len(ks):
        return None
    k = int(ks[0])
    return k, int(row[k])


def _sig_exit(sig_row: np.ndarray, ends: np.ndarray, mode: str = "flat"):
    """Exit at the first bar close after entry where the signal is no longer the trade's side
    ('flat') or is the opposite side ('opposite')."""
    dec = ends + 1

    def fn(entry_minute: int, side: int) -> int | None:
        if mode == "opposite":
            ks = np.nonzero((dec > entry_minute) & (sig_row == -side))[0]
        else:
            ks = np.nonzero((dec > entry_minute) & (sig_row != side))[0]
        return int(dec[ks[0]]) if len(ks) and dec[ks[0]] < SESSION_MIN else None
    return fn


# ── families ─────────────────────────────────────────────────────────────────────
# Each returns (specs_fn_for_day(day) -> specs(after) | None, sig_exit_for_day(day) | None, max_trades)


def fam_orb(ctx: Ctx, p: dict):
    """Opening-range breakout: the range of the first `orm` minutes; break of its high / low."""
    d = ctx.d
    orm = p["orm"]
    hi = d.h[:, :orm].max(axis=1)
    lo = d.l[:, :orm].min(axis=1)
    mid = (hi + lo) / 2
    entry = p["entry"]
    b5 = ctx.tf(5)

    def day_specs(i: int):
        H, L, C = d.h[i], d.l[i], d.c[i]
        atr = ctx.day_atr[i]

        def stop_for(side):
            if p["stop"] == "opp":
                return lo[i] if side > 0 else hi[i]
            if p["stop"] == "mid":
                return mid[i]
            return None                                         # 'atr': ExitCfg supplies it

        def specs(after: int):
            if after > orm:                                     # one break per day: first only
                return None
            if entry == "stop":
                seg_h, seg_l = H[orm:ENTRY_CUTOFF + 1], L[orm:ENTRY_CUTOFF + 1]
                up = np.nonzero(seg_h >= hi[i])[0]
                dn = np.nonzero(seg_l <= lo[i])[0]
                ku = int(up[0]) if len(up) else 10 ** 9
                kd = int(dn[0]) if len(dn) else 10 ** 9
                if ku == kd == 10 ** 9 or ku == kd:
                    return None                                 # no break, or both in one minute
                if ku < kd:
                    return EntrySpec(1, orm + ku, "stop", hi[i], stop_for(1))
                return EntrySpec(-1, orm + kd, "stop", lo[i], stop_for(-1))
            # 'close': a 5-minute close beyond the range, entered at the next minute's open
            cl, ends = b5["c"][i], b5["end"]
            for k in range(len(ends)):
                if ends[k] < orm - 1:
                    continue
                if ends[k] + 1 > ENTRY_CUTOFF:
                    break
                if cl[k] > hi[i]:
                    return EntrySpec(1, int(ends[k] + 1), "market", None, stop_for(1))
                if cl[k] < lo[i]:
                    return EntrySpec(-1, int(ends[k] + 1), "market", None, stop_for(-1))
            return None
        return specs
    return day_specs, None, 1


def fam_pdhl(ctx: Ctx, p: dict):
    """Previous-day high / low breakout, stop orders resting from `start` until `until`."""
    d = ctx.d
    s, u = minute_of(p["start"]), minute_of(p["until"])

    def day_specs(i: int):
        ph, pl = ctx.prev_high[i], ctx.prev_low[i]
        if not (ph == ph and pl == pl):
            return lambda after: None
        H, L = d.h[i], d.l[i]
        o0 = d.o[i, 0]

        def specs(after: int):
            if after > s:
                return None
            # a day that OPENS beyond the level has no breakout to trade at the level
            seg_h, seg_l = H[s:u + 1], L[s:u + 1]
            up = np.nonzero(seg_h >= ph)[0] if o0 < ph else np.array([], int)
            dn = np.nonzero(seg_l <= pl)[0] if o0 > pl else np.array([], int)
            ku = int(up[0]) if len(up) else 10 ** 9
            kd = int(dn[0]) if len(dn) else 10 ** 9
            if ku == kd:
                return None
            if ku < kd:
                return EntrySpec(1, s + ku, "stop", ph)
            return EntrySpec(-1, s + kd, "stop", pl)
        return specs
    return day_specs, None, 1


def _vix_regime(ctx: Ctx) -> np.ndarray:
    """+1 where yesterday's India VIX close is above its trailing 250-day median, -1 below, 0 unknown."""
    if ctx.vix_prev is None:
        return np.zeros(len(ctx.d))
    v = ctx.vix_prev
    med = np.array([np.nanmedian(v[max(0, i - 250):i]) if i > 20 else np.nan for i in range(len(v))])
    return np.where(np.isnan(v) | np.isnan(med), 0, np.where(v > med, 1, -1))


def fam_volbreak(ctx: Ctx, p: dict):
    """Volatility breakout from the open: stop orders at open +/- k x prior-day ATR, resting from
    `start` (default 09:16) to `until` (default the entry cutoff); optionally only in one VIX regime."""
    d = ctx.d
    s = minute_of(p["start"]) if p.get("start") else 1
    u = minute_of(p["until"]) if p.get("until") else ENTRY_CUTOFF
    regime = _vix_regime(ctx) if p.get("vix") else None

    def day_specs(i: int):
        atr = ctx.day_atr[i]
        if not atr == atr:
            return lambda after: None
        if regime is not None and regime[i] != (1 if p["vix"] == "high" else -1):
            return lambda after: None
        o0 = d.o[i, 0]
        up_l, dn_l = o0 + p["k"] * atr, o0 - p["k"] * atr
        H, L = d.h[i], d.l[i]

        def specs(after: int):
            if after > s:
                return None
            seg_h, seg_l = H[s:u + 1], L[s:u + 1]
            up = np.nonzero(seg_h >= up_l)[0]
            dn = np.nonzero(seg_l <= dn_l)[0]
            ku = int(up[0]) if len(up) else 10 ** 9
            kd = int(dn[0]) if len(dn) else 10 ** 9
            if ku == kd:
                return None
            if ku < kd:
                return EntrySpec(1, s + ku, "stop", up_l)
            return EntrySpec(-1, s + kd, "stop", dn_l)
        return specs
    return day_specs, None, 1


def fam_intraday_momentum(ctx: Ctx, p: dict):
    """Gao, Han, Li & Zhou (2018): the first half hour's return predicts the last half hour's.
    Signal over [09:15, signal_end); trade from `enter` to the square-off, in its direction."""
    d = ctx.d
    se, en = minute_of(p["signal_end"]), minute_of(p["enter"])
    pc = ctx.prev_close

    def day_specs(i: int):
        base = pc[i] if p["from"] == "prev_close" else d.o[i, 0]
        if not base == base:
            return lambda after: None
        r = d.c[i, se - 1] / base - 1
        atr = ctx.day_atr[i]
        thr = p["thr"] * atr / base if atr == atr else 0.0
        side = 1 if r > thr else (-1 if r < -thr else 0)

        def specs(after: int):
            if after > en or side == 0:
                return None
            return EntrySpec(side, en, "market")
        return specs
    return day_specs, None, 1


def _indicator_family(ctx: Ctx, tf: int, sig_flat: np.ndarray, p: dict, max_trades: int, exit_mode: str):
    """Shared plumbing: a (days x bars) signal; entries at bar closes; optional signal exits."""
    B = ctx.tf(tf)
    nb = B["c"].shape[1]
    sig = sig_flat.reshape(-1, nb)
    ends = B["end"]
    first_dec = minute_of(p.get("first", "09:30"))

    def day_specs(i: int):
        row = sig[i]

        def specs(after: int):
            got = _first_signal_after(row, ends, max(after, first_dec))
            if got is None:
                return None
            k, side = got
            return EntrySpec(side, int(ends[k] + 1), "market")
        return specs

    def day_exit(i: int):
        return _sig_exit(sig[i], ends, exit_mode)
    return day_specs, (day_exit if exit_mode else None), max_trades


def fam_ema(ctx: Ctx, p: dict):
    tf = p["tf"]
    c = ctx.flat(tf, "c")
    f = ctx.ind(("ema", tf, p["fast"]), lambda: ema(c, p["fast"]))
    s = ctx.ind(("ema", tf, p["slow"]), lambda: ema(c, p["slow"]))
    sig = np.sign(f - s)
    if p.get("mode") == "cross":                       # only the bar where it crosses
        prev = np.r_[0, sig[:-1]]
        sig = np.where(sig != prev, sig, 0)
    return _indicator_family(ctx, tf, sig, p, p.get("max_trades", 4), "flat" if p.get("mode") != "cross" else "opposite")


def fam_supertrend(ctx: Ctx, p: dict):
    tf = p["tf"]
    h, l, c = ctx.flat(tf, "h"), ctx.flat(tf, "l"), ctx.flat(tf, "c")
    st = ctx.ind(("st", tf, p["n"], p["mult"]), lambda: supertrend(h, l, c, p["n"], p["mult"]))
    sig = st.copy()
    if p.get("adx"):
        a = ctx.ind(("adx", tf), lambda: adx(h, l, c, 14))
        sig = np.where(a >= p["adx"], sig, 0)
    return _indicator_family(ctx, tf, sig, p, p.get("max_trades", 4), "flat")


def fam_rsi(ctx: Ctx, p: dict):
    tf = p["tf"]
    c = ctx.flat(tf, "c")
    r = ctx.ind(("rsi", tf, p["n"]), lambda: rsi(c, p["n"]))
    if p["mode"] == "momentum":
        sig = np.where(r > p["hi"], 1, np.where(r < p["lo"], -1, 0))
        return _indicator_family(ctx, tf, sig, p, p.get("max_trades", 4), "flat")
    sig = np.where(r < p["lo"], 1, np.where(r > p["hi"], -1, 0))          # mean reversion
    exit_sig = np.where((r >= 50), 1, 0)
    # exit a reversion long when RSI recovers to 50 (and a short when it falls to 50)
    fam = _indicator_family(ctx, tf, sig, p, p.get("max_trades", 4), "")
    B = ctx.tf(tf)
    nb = B["c"].shape[1]
    rr = r.reshape(-1, nb)
    ends = B["end"]

    def day_exit(i: int):
        row = rr[i]
        dec = ends + 1

        def fn(entry_minute: int, side: int):
            cond = (row >= 50) if side > 0 else (row <= 50)
            ks = np.nonzero((dec > entry_minute) & cond)[0]
            return int(dec[ks[0]]) if len(ks) and dec[ks[0]] < SESSION_MIN else None
        return fn
    return fam[0], day_exit, fam[2]


def fam_bollinger(ctx: Ctx, p: dict):
    tf = p["tf"]
    c = ctx.flat(tf, "c")
    m, s = ctx.ind(("bb", tf, p["n"]), lambda: rolling_mean_std(c, p["n"]))
    up, dn = m + p["k"] * s, m - p["k"] * s
    if p["mode"] == "revert":
        sig = np.where(c < dn, 1, np.where(c > up, -1, 0))
    else:                                               # band walk: follow the break
        sig = np.where(c > up, 1, np.where(c < dn, -1, 0))
    B = ctx.tf(tf)
    nb = B["c"].shape[1]
    mm = m.reshape(-1, nb)
    cc = c.reshape(-1, nb)
    ends = B["end"]
    fam = _indicator_family(ctx, tf, sig, p, p.get("max_trades", 4), "")

    def day_exit(i: int):
        dec = ends + 1
        row_m, row_c = mm[i], cc[i]

        def fn(entry_minute: int, side: int):
            if p["mode"] == "revert":
                cond = (row_c >= row_m) if side > 0 else (row_c <= row_m)      # back to the mean
            else:
                cond = (row_c < row_m) if side > 0 else (row_c > row_m)
            ks = np.nonzero((dec > entry_minute) & cond)[0]
            return int(dec[ks[0]]) if len(ks) and dec[ks[0]] < SESSION_MIN else None
        return fn
    return fam[0], day_exit, fam[2]


def _session_avg(d: Days) -> np.ndarray:
    """Session time-weighted average of the typical price, minute by minute (an index has no
    volume; this is the TWAP stand-in for VWAP)."""
    tp = (d.h + d.l + d.c) / 3
    if d.v.sum() > 0 and (d.v > 0).mean() > 0.8:
        pv = np.cumsum(tp * d.v, axis=1)
        vv = np.cumsum(d.v, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.where(vv > 0, pv / vv, np.nan)
        return out
    return np.cumsum(tp, axis=1) / np.arange(1, SESSION_MIN + 1)


def fam_vwap(ctx: Ctx, p: dict):
    """VWAP (TWAP for an index) — 'revert': fade a stretch beyond k x the day's ATR-scaled band,
    exit back at the average; 'trend': follow a close across the average after `first`."""
    d = ctx.d
    vw = ctx.ind("vwap", lambda: _session_avg(d))
    tf = p["tf"]
    B = ctx.tf(tf)
    ends = B["end"]
    cc = B["c"]
    vw_at = vw[:, ends]
    atr = ctx.day_atr[:, None]
    if p["mode"] == "revert":
        dev = (cc - vw_at) / atr
        sig = np.where(dev < -p["k"], 1, np.where(dev > p["k"], -1, 0))
    else:
        prev = np.c_[cc[:, :1], cc[:, :-1]]
        pvw = np.c_[vw_at[:, :1], vw_at[:, :-1]]
        sig = np.where((cc > vw_at) & (prev <= pvw), 1, np.where((cc < vw_at) & (prev >= pvw), -1, 0))
    sig = np.nan_to_num(sig).astype(float)
    fam = _indicator_family(ctx, tf, sig.reshape(-1), p, p.get("max_trades", 3), "")

    def day_exit(i: int):
        dec = ends + 1
        row_c, row_v = cc[i], vw_at[i]

        def fn(entry_minute: int, side: int):
            if p["mode"] == "revert":
                cond = (row_c >= row_v) if side > 0 else (row_c <= row_v)
            else:
                cond = (row_c < row_v) if side > 0 else (row_c > row_v)
            ks = np.nonzero((dec > entry_minute) & cond)[0]
            return int(dec[ks[0]]) if len(ks) and dec[ks[0]] < SESSION_MIN else None
        return fn
    return fam[0], day_exit, fam[2]


def fam_pullback(ctx: Ctx, p: dict):
    """Trend pullback: with the day trending (close above the session average and the 15m EMA20
    rising), buy a 5m close back above EMA20 after a dip below it; mirror for shorts."""
    d = ctx.d
    c5 = ctx.flat(5, "c")
    l5, h5 = ctx.flat(5, "l"), ctx.flat(5, "h")
    e5 = ctx.ind(("ema", 5, 20), lambda: ema(c5, 20))
    c15 = ctx.flat(15, "c")
    e15 = ctx.ind(("ema", 15, 20), lambda: ema(c15, 20))
    B5, B15 = ctx.tf(5), ctx.tf(15)
    nb5, nb15 = B5["c"].shape[1], B15["c"].shape[1]
    e15r = e15.reshape(-1, nb15)
    slope15 = np.c_[np.zeros((e15r.shape[0], 1)), np.diff(e15r, axis=1)]
    # map each 5m bar to the last COMPLETED 15m bar
    idx15 = np.array([max(-1, (int(B5["end"][k]) + 1) // 15 - 1) for k in range(nb5)])
    s15 = np.where(idx15 >= 0, slope15[:, np.clip(idx15, 0, None)], 0)
    vw = ctx.ind("vwap", lambda: _session_avg(d))[:, B5["end"]]
    c5r, l5r, h5r, e5r = c5.reshape(-1, nb5), l5.reshape(-1, nb5), h5.reshape(-1, nb5), e5.reshape(-1, nb5)
    up = (c5r > vw) & (s15 > 0) & (np.c_[l5r[:, :1], l5r[:, :-1]] < np.c_[e5r[:, :1], e5r[:, :-1]]) & (c5r > e5r)
    dn = (c5r < vw) & (s15 < 0) & (np.c_[h5r[:, :1], h5r[:, :-1]] > np.c_[e5r[:, :1], e5r[:, :-1]]) & (c5r < e5r)
    sig = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    return _indicator_family(ctx, 5, sig.reshape(-1), p, p.get("max_trades", 2), "")


def fam_mtf(ctx: Ctx, p: dict):
    """Multi-timeframe confirmation: a 5m EMA(9/21) cross taken only in the direction of the 30m
    EMA(20) trend (last completed 30m bar)."""
    c5 = ctx.flat(5, "c")
    f, s = ctx.ind(("ema", 5, 9), lambda: ema(c5, 9)), ctx.ind(("ema", 5, 21), lambda: ema(c5, 21))
    sig5 = np.sign(f - s)
    cross = np.where(sig5 != np.r_[0, sig5[:-1]], sig5, 0)
    c30 = ctx.flat(30, "c")
    e30 = ctx.ind(("ema", 30, 20), lambda: ema(c30, 20))
    B5, B30 = ctx.tf(5), ctx.tf(30)
    nb5, nb30 = B5["c"].shape[1], B30["c"].shape[1]
    tr30 = np.sign(c30 - e30).reshape(-1, nb30)
    idx30 = np.array([max(-1, (int(B5["end"][k]) + 1) // 30 - 1) for k in range(nb5)])
    tr_at = np.where(idx30 >= 0, tr30[:, np.clip(idx30, 0, None)], 0)
    # before the day's first 30m bar closes, use the previous day's last 30m trend
    prev_last = np.r_[0, tr30[:-1, -1]] if len(tr30) else np.zeros(0)
    tr_at = np.where(idx30[None, :] >= 0, tr_at, prev_last[:, None])
    sig = cross.reshape(-1, nb5) * (cross.reshape(-1, nb5) == tr_at)
    return _indicator_family(ctx, 5, sig.reshape(-1).astype(float), p, p.get("max_trades", 3), "opposite")


def fam_regime(ctx: Ctx, p: dict):
    """VIX-regime switch: when yesterday's India VIX is above its 1-year median, trade the 15-minute
    ORB (momentum); otherwise fade Bollinger(20, 2) extremes on 5m (reversion)."""
    if ctx.vix_prev is None:
        return (lambda i: (lambda after: None)), None, 1
    v = ctx.vix_prev
    med = np.array([np.nanmedian(v[max(0, i - 250):i]) if i > 20 else np.nan for i in range(len(v))])
    high = v > med
    orb = fam_orb(ctx, {"orm": 15, "entry": "stop", "stop": "opp"})
    bb = fam_bollinger(ctx, {"tf": 5, "n": 20, "k": 2.0, "mode": "revert"})

    def day_specs(i: int):
        return orb[0](i) if high[i] else bb[0](i)

    def day_exit(i: int):
        return None if high[i] else bb[1](i)
    return day_specs, day_exit, 2


def fam_gap(ctx: Ctx, p: dict):
    """Gap fade / gap follow: an open beyond k x ATR from yesterday's close; enter at 09:20
    (after the opening print settles) against ('fade') or with ('follow') the gap."""
    d = ctx.d
    en = minute_of(p.get("enter", "09:20"))

    def day_specs(i: int):
        pc, atr = ctx.prev_close[i], ctx.day_atr[i]
        if not (pc == pc and atr == atr):
            return lambda after: None
        g = (d.o[i, 0] - pc) / atr
        side = 0
        if abs(g) >= p["k"]:
            side = int(np.sign(g)) * (1 if p["mode"] == "follow" else -1)

        def specs(after: int):
            if after > en or side == 0:
                return None
            return EntrySpec(side, en, "market")
        return specs
    return day_specs, None, 1


def fam_trendday(ctx: Ctx, p: dict):
    """Trend-day continuation: at `at`, if the day has already moved more than k x the prior-day
    ATR from its open, enter in that direction (one trade, held to the exit rule). Why: large
    early moves on index days mark information days whose drift tends to persist into the close."""
    d = ctx.d
    at = minute_of(p["at"])

    def day_specs(i: int):
        atr = ctx.day_atr[i]
        if not atr == atr:
            return lambda after: None
        move = d.c[i, at - 1] - d.o[i, 0]
        side = 1 if move > p["k"] * atr else (-1 if move < -p["k"] * atr else 0)
        if move != move:
            side = 0

        def specs(after: int):
            if after > at or side == 0:
                return None
            return EntrySpec(side, at, "market")
        return specs
    return day_specs, None, 1


FAMILIES = {
    "trendday": fam_trendday,
    "orb": fam_orb, "pdhl": fam_pdhl, "volbreak": fam_volbreak, "imom": fam_intraday_momentum,
    "ema": fam_ema, "supertrend": fam_supertrend, "rsi": fam_rsi, "bollinger": fam_bollinger,
    "vwap": fam_vwap, "pullback": fam_pullback, "mtf": fam_mtf, "regime": fam_regime, "gap": fam_gap,
}


# ── the round-1 grid (fixed before it ran) ───────────────────────────────────────


def _grid(**axes) -> list[dict]:
    keys = list(axes)
    return [dict(zip(keys, v)) for v in itertools.product(*(axes[k] for k in keys))]


EXITS = {
    "eod": ExitCfg(),
    "r2": ExitCfg(stop="atr", stop_mult=0.5, target_r=2.0),
    "trail": ExitCfg(stop="atr", stop_mult=0.5, trail="atr", trail_mult=0.5),
    "atr_eod": ExitCfg(stop="atr", stop_mult=0.5),
    "sig": ExitCfg(stop="atr", stop_mult=0.75, signal_exit=True),
    "sig_nostop": ExitCfg(signal_exit=True),
    "time60": ExitCfg(stop="atr", stop_mult=0.5, max_hold=60, signal_exit=True),
    "trail_wide": ExitCfg(stop="atr", stop_mult=0.75, trail="atr", trail_mult=1.0),
}

ROUND1: list[tuple[str, dict, str]] = (
    # opening-range breakout: range x entry x stop x exit
    [("orb", p, x) for p in _grid(orm=[5, 15, 30], entry=["stop", "close"], stop=["opp", "mid"])
     for x in ("eod", "trail")]
    + [("orb", p, x) for p in _grid(orm=[5, 15, 30], entry=["stop", "close"], stop=["atr"]) for x in ("r2", "trail", "atr_eod")]
    + [("pdhl", p, x) for p in _grid(start=["09:30"], until=["11:00", "14:30"]) for x in ("r2", "trail", "atr_eod")]
    + [("volbreak", p, x) for p in _grid(k=[0.25, 0.5, 0.75]) for x in ("r2", "trail", "atr_eod")]
    + [("imom", p, "eod") for p in _grid(signal_end=["09:45", "10:15"], enter=["14:40"], **{"from": ["prev_close", "open"]}, thr=[0.0])]
    + [("imom", p, "eod") for p in _grid(signal_end=["09:45"], enter=["14:40"], **{"from": ["prev_close"]}, thr=[0.25])]
    + [("ema", p, x) for p in _grid(tf=[3, 5, 15], fast=[9], slow=[21], mode=["state"]) for x in ("sig", "sig_nostop")]
    + [("ema", p, "sig") for p in _grid(tf=[5, 15], fast=[20], slow=[50], mode=["state"])]
    + [("supertrend", p, "sig") for p in _grid(tf=[5, 15], n=[10], mult=[2.0, 3.0], adx=[0, 25])]
    + [("rsi", p, "sig") for p in _grid(tf=[5, 15], n=[14], mode=["momentum"], hi=[60], lo=[40])]
    + [("rsi", p, x) for p in _grid(tf=[5, 15], n=[2, 14], mode=["revert"], hi=[80], lo=[20]) for x in ("time60",)]
    + [("bollinger", p, "time60") for p in _grid(tf=[5, 15], n=[20], k=[2.0, 2.5], mode=["revert"])]
    + [("bollinger", p, "sig") for p in _grid(tf=[5, 15], n=[20], k=[2.0], mode=["walk"])]
    + [("vwap", p, "time60") for p in _grid(tf=[5], mode=["revert"], k=[0.3, 0.5])]
    + [("vwap", p, "sig") for p in _grid(tf=[5, 15], mode=["trend"], first=["10:00"])]
    + [("pullback", p, x) for p in _grid(first=["09:45"]) for x in ("r2", "trail", "atr_eod")]
    + [("mtf", p, x) for p in _grid(first=["09:45"]) for x in ("sig", "trail")]
    + [("regime", {}, "atr_eod")]
    + [("gap", p, x) for p in _grid(k=[0.3, 0.6], mode=["fade", "follow"]) for x in ("eod", "r2")]
)


ROUND2: list[tuple[str, dict, str]] = (
    # the breakout cluster, round 1's only family with a gross edge above costs
    [("volbreak", {"k": k}, x) for k in (0.4, 0.6, 1.0) for x in ("r2", "trail", "atr_eod")]
    + [("volbreak", {"k": k}, x) for k in (0.5, 0.75) for x in ("trail_wide", "eod")]
    + [("volbreak", {"k": 0.75, "until": "11:30"}, x) for x in ("trail", "atr_eod")]
    + [("volbreak", {"k": k, "vix": v}, "trail") for k in (0.5, 0.75) for v in ("high", "low")]
    + [("pdhl", {"start": "09:30", "until": u}, x) for u in ("11:00", "14:30") for x in ("trail_wide", "eod")]
    + [("orb", {"orm": m, "entry": "stop", "stop": "opp"}, "trail_wide") for m in (15, 30)]
)


ROUND3: list[tuple[str, dict, str]] = (
    # bigger moves a trade on the liquid indexes: costs weigh less on a trend day
    [("trendday", {"at": at, "k": k}, x) for at in ("10:15", "11:15", "12:15") for k in (0.4, 0.7)
     for x in ("eod", "trail_wide")]
    + [("orb", {"orm": 60, "entry": "stop", "stop": st}, x) for st in ("opp", "atr")
       for x in ("eod", "trail_wide")]
    + [("volbreak", {"k": k, "start": "10:15"}, "trail") for k in (0.5, 0.75)]
)


ROUND4: list[tuple[str, dict, str]] = (
    # coverage, not a hunch: round 1's indicator grid at the two bar lengths it left out (10 and
    # 30 minutes), same parameters and exits — so every family was tried at 1/3/5/10/15/30m
    [("ema", p, x) for p in _grid(tf=[10, 30], fast=[9], slow=[21], mode=["state"]) for x in ("sig", "sig_nostop")]
    + [("ema", p, "sig") for p in _grid(tf=[10, 30], fast=[20], slow=[50], mode=["state"])]
    + [("supertrend", p, "sig") for p in _grid(tf=[10, 30], n=[10], mult=[2.0, 3.0], adx=[0, 25])]
    + [("rsi", p, "sig") for p in _grid(tf=[10, 30], n=[14], mode=["momentum"], hi=[60], lo=[40])]
    + [("rsi", p, "time60") for p in _grid(tf=[10, 30], n=[2, 14], mode=["revert"], hi=[80], lo=[20])]
    + [("bollinger", p, "time60") for p in _grid(tf=[10, 30], n=[20], k=[2.0, 2.5], mode=["revert"])]
    + [("bollinger", p, "sig") for p in _grid(tf=[10, 30], n=[20], k=[2.0], mode=["walk"])]
    + [("vwap", p, "time60") for p in _grid(tf=[10, 30], mode=["revert"], k=[0.3, 0.5])]
    + [("vwap", p, "sig") for p in _grid(tf=[10, 30], mode=["trend"], first=["10:00"])]
)


def variant_key(fam: str, p: dict, exit_name: str) -> str:
    return f"{fam}|{','.join(f'{k}={p[k]}' for k in sorted(p))}|{exit_name}"
