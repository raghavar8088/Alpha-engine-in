"""Phase 8 (AMENDMENT_A8.md + A8_1): intraday strategies on the app's recorded MCX bars.

Every signal is read at a bar's close and filled at the NEXT bar's open; breakouts fill at the level
(or at the open if the bar gapped past it); stops and targets are checked against later bars'
high/low, the stop first when one bar could have hit both; everything is flat at the session close.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TICK = {"CRUDEOIL": 1.0, "NATURALGAS": 0.10}
MARGIN = {"CRUDEOIL": 0.311, "NATURALGAS": 0.167}             # Angel futures, measured 2026-10-09
EXCH, SEBI, GST, CTT, STAMP = 0.000021, 0.000001, 0.18, 0.0001, 0.00002
ORDER = 20.0 * (1 + GST) / 1_000_000                           # one order, at 1x exposure on Rs10 lakh
COST = 2 * ((EXCH + SEBI) * (1 + GST) + ORDER) + CTT + STAMP   # round trip, excluding slippage
FULL = {"5m": 174, "15m": 58, "1h": 15}
MIN_FRAC = 0.90


def load(path):
    b = pd.read_csv(path)
    b["ts"] = pd.to_datetime(b.ts, utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    b["expiry"] = pd.to_datetime(b.expiry)
    b["day"] = b.ts.dt.normalize()
    return b


class Day:
    __slots__ = ("day", "expiry", "t", "hm", "o", "h", "l", "c", "v")

    def __init__(self, day, expiry, g):
        self.day, self.expiry = day, expiry
        self.t = g.ts.to_numpy()
        self.hm = g.ts.dt.strftime("%H:%M").to_numpy()
        self.o, self.h, self.l, self.c = (g[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        self.v = g.volume.fillna(0).to_numpy(dtype=float)

    def idx(self, hm):
        k = np.where(self.hm == hm)[0]
        return int(k[0]) if len(k) else None


def sessions(b, sym, tf):
    """Ordered list of Day objects: per day, the contract with the most bars (tie: nearest expiry),
    kept only with >= 90% of a full session."""
    x = b[(b.symbol == sym) & (b.timeframe == tf)]
    need = math.ceil(MIN_FRAC * FULL[tf])
    out = []
    for day, g in x.groupby("day"):
        cnt = g.groupby("expiry").size()
        best = cnt[cnt == cnt.max()].index.min()
        gg = g[g.expiry == best].sort_values("ts").reset_index(drop=True)
        if len(gg) >= need:
            out.append(Day(day, best, gg))
    return out


def trade(d, side, entry, exit_, i, j, reason):
    return {"day": d.day, "side": side, "entry": entry, "exit": exit_, "t_in": d.t[i], "t_out": d.t[j], "reason": reason,
            "net": side * (exit_ - entry) / entry - COST}


def run_exit(d, i, side, entry, slip, stop=None, target=None, last=None, entry_at_open=True):
    """Walk from the entry bar i. Stop first if a bar could hit both; a bar that opens past the stop fills
    at its open. Without a hit, exit at the last bar's close. Returns (exit price, bar, reason)."""
    last = len(d.o) - 1 if last is None else last
    for j in range(i, last + 1):
        o, h, l = d.o[j], d.h[j], d.l[j]
        if stop is not None:
            if side > 0 and l <= stop:
                px = min(o, stop) if (j > i or entry_at_open) else stop
                return px - slip, j, "stop"
            if side < 0 and h >= stop:
                px = max(o, stop) if (j > i or entry_at_open) else stop
                return px + slip, j, "stop"
        if target is not None:
            if side > 0 and h >= target:
                return target, j, "target"
            if side < 0 and l <= target:
                return target, j, "target"
    return d.c[last] - side * slip, last, "close"


def breakout(d, hi, lo, start, slip, stop_fn):
    """First break of [lo, hi] from bar `start`; stop_fn(side, entry) gives the stop. One trade."""
    for j in range(start, len(d.o)):
        up, dn = d.h[j] >= hi, d.l[j] <= lo
        if not (up or dn):
            continue
        if up and dn:                      # both sides in one bar: assume the worse order
            side = 1 if abs(d.o[j] - hi) <= abs(d.o[j] - lo) else -1
        else:
            side = 1 if up else -1
        level = hi if side > 0 else lo
        entry = (max(level, d.o[j]) + slip) if side > 0 else (min(level, d.o[j]) - slip)
        stop = stop_fn(side, entry)
        if (up and dn) or (side > 0 and d.l[j] <= stop) or (side < 0 and d.h[j] >= stop):
            return trade(d, side, entry, stop - side * slip, j, j, "stop")   # the entry bar also reached the stop
        px, k, why = run_exit(d, j + 1, side, entry, slip, stop=stop) if j + 1 < len(d.o) else (d.c[j] - side * slip, j, "close")
        return trade(d, side, entry, px, j, k, why)
    return None


# ---------------------------------------------------------------------------- the A8 strategies (5m unless stated)
def s_orb(days, slip, rng_from, rng_to, trig_from, n_range):
    out = []
    for d in days:
        m = (d.hm >= rng_from) & (d.hm < rng_to)
        k = d.idx(trig_from)
        if m.sum() < n_range or k is None:
            continue
        hi, lo = d.h[m].max(), d.l[m].min()
        t = breakout(d, hi, lo, k, slip, lambda side, e: lo if side > 0 else hi)
        if t:
            out.append(t)
    return out


def s_pdhl(days, slip):
    out = []
    for prev, d in zip(days[:-1], days[1:]):
        if prev.expiry != d.expiry:
            continue
        H, L = prev.h.max(), prev.l.min()
        dist = 0.5 * (H - L)
        k = d.idx("09:30")
        if k is None or dist <= 0:
            continue
        t = breakout(d, H, L, k, slip, lambda side, e: e - side * dist)
        if t:
            out.append(t)
    return out


def s_vwap(days, slip):
    out = []
    for d in days:
        tp = (d.h + d.l + d.c) / 3
        cv, cpv = np.cumsum(d.v), np.cumsum(tp * d.v)
        n, trades, t = len(d.o), 0, 11
        while t < n - 1 and trades < 3:
            if cv[t] <= 0:
                t += 1
                continue
            vw = cpv[:t + 1] / np.where(cv[:t + 1] > 0, cv[:t + 1], np.nan)
            dev = d.c[:t + 1] - vw
            sd = np.nanstd(dev)
            if not np.isfinite(sd) or sd <= 0:
                t += 1
                continue
            z = dev[-1] / sd
            if abs(z) <= 2:
                t += 1
                continue
            side = -1 if z > 0 else 1
            i = t + 1
            entry = d.o[i] + side * slip
            px, j, why = run_exit(d, i, side, entry, slip, stop=entry - side * sd, target=vw[-1])
            out.append(trade(d, side, entry, px, i, j, why))
            trades += 1
            t = j
    return out


def rsi2(c):
    r = np.full(len(c), np.nan)
    if len(c) < 3:
        return r
    ch = np.diff(c)
    ag, al = max(ch[0], 0.0), max(-ch[0], 0.0)
    for k in range(1, len(ch)):
        ag = (ag + max(ch[k], 0.0)) / 2
        al = (al + max(-ch[k], 0.0)) / 2
        r[k + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return r


def s_rsi2(days, slip):
    out = []
    for d in days:
        r, n, t = rsi2(d.c), len(d.o), 2
        while t < n - 1:
            if not np.isfinite(r[t]) or d.hm[t + 1] >= "23:00" or 10 <= r[t] <= 90:
                t += 1
                continue
            side = 1 if r[t] < 10 else -1
            i = t + 1
            entry = d.o[i] + side * slip
            stop = entry * (1 - side * 0.005)
            done = None
            for j in range(i, n):
                if (side > 0 and d.l[j] <= stop) or (side < 0 and d.h[j] >= stop):
                    px = (min(d.o[j], stop) if side > 0 else max(d.o[j], stop)) - side * slip
                    done = (px, j, "stop")
                    break
                if j == n - 1:
                    done = (d.c[j] - side * slip, j, "close")
                    break
                if (side > 0 and r[j] > 50) or (side < 0 and r[j] < 50):
                    done = (d.o[j + 1] - side * slip, j + 1, "rsi")
                    break
            out.append(trade(d, side, entry, done[0], i, done[1], done[2]))
            t = done[1]
    return out


def ema(x, n):
    a, out = 2 / (n + 1), np.empty(len(x))
    out[0] = x[0]
    for k in range(1, len(x)):
        out[k] = a * x[k] + (1 - a) * out[k - 1]
    return out


def s_emax(days, slip):
    out = []
    for d in days:
        diff = ema(d.c, 9) - ema(d.c, 21)
        n, pos, entry, i0 = len(d.o), 0, None, None
        for t in range(1, n - 1):
            if np.sign(diff[t]) == np.sign(diff[t - 1]) or diff[t] == 0:
                continue
            new = 1 if diff[t] > 0 else -1
            px = d.o[t + 1]
            if pos:
                ex = px - pos * slip
                out.append(trade(d, pos, entry, ex, i0, t + 1, "cross"))
                pos = 0
            if d.hm[t + 1] < "23:00":
                pos, entry, i0 = new, px + new * slip, t + 1
        if pos:
            out.append(trade(d, pos, entry, d.c[n - 1] - pos * slip, i0, n - 1, "close"))
    return out


def s_momlh(days, slip, start_hm, at_hm="22:25"):
    out = []
    for d in days:
        a, k = d.idx(start_hm), d.idx(at_hm)
        if a is None or k is None or k < 1:
            continue
        r = d.c[k - 1] / d.o[a] - 1
        if r == 0:
            continue
        side = 1 if r > 0 else -1
        entry = d.o[k] + side * slip
        out.append(trade(d, side, entry, d.c[-1] - side * slip, k, len(d.o) - 1, "close"))
    return out


def s_event(days, slip, weekday):
    out = []
    for d in days:
        if d.day.weekday() != weekday:
            continue
        a, k = d.idx("20:00"), d.idx("20:15")
        if a is None or k is None:
            continue
        r = d.c[k - 1] / d.o[a] - 1
        if r == 0:
            continue
        side = 1 if r > 0 else -1
        entry = d.o[k] + side * slip
        px, j, why = run_exit(d, k, side, entry, slip, stop=d.o[a])
        out.append(trade(d, side, entry, px, k, j, why))
    return out


def s_bb(days, slip):
    out = []
    for d in days:
        n, pos, t = len(d.o), 0, 19
        while t < n - 1:
            w = d.c[t - 19:t + 1]
            mid, sd = w.mean(), w.std()
            if pos == 0 and sd > 0 and (d.c[t] > mid + 2 * sd or d.c[t] < mid - 2 * sd):
                side = 1 if d.c[t] > mid else -1
                i = t + 1
                entry = d.o[i] + side * slip
                done = None
                for j in range(i, n):
                    if j == n - 1:
                        done = (d.c[j] - side * slip, j, "close")
                        break
                    if j >= 19:
                        m2 = d.c[j - 19:j + 1].mean()
                        if (side > 0 and d.c[j] < m2) or (side < 0 and d.c[j] > m2):
                            done = (d.o[j + 1] - side * slip, j + 1, "mid")
                            break
                out.append(trade(d, side, entry, done[0], i, done[1], done[2]))
                t = done[1]
                continue
            t += 1
    return out


def s_gap(days, slip):
    out = []
    for prev, d in zip(days[:-1], days[1:]):
        if prev.expiry != d.expiry or len(d.o) < 2:
            continue
        pc = prev.c[-1]
        g = d.o[0] / pc - 1
        if abs(g) <= 0.005:
            continue
        side = -1 if g > 0 else 1
        entry = d.o[1] + side * slip
        px, j, why = run_exit(d, 1, side, entry, slip, stop=entry * (1 - side * 0.005), target=pc)
        out.append(trade(d, side, entry, px, 1, j, why))
    return out


def s_long(days, slip, from_hm):
    out = []
    for d in days:
        a = d.idx(from_hm)
        if a is None:
            continue
        out.append(trade(d, 1, d.o[a] + slip, d.c[-1] - slip, a, len(d.o) - 1, "close"))
    return out


# ---------------------------------------------------------------------------- hourly
def h_momlh(days, slip):
    out = []
    for d in days:
        a, k = d.idx("09:00"), d.idx("22:00")
        if a is None or k is None:
            continue
        r = d.c[k - 1] / d.o[a] - 1
        if r == 0:
            continue
        side = 1 if r > 0 else -1
        entry = d.o[k] + side * slip
        out.append(trade(d, side, entry, d.c[-1] - side * slip, k, len(d.o) - 1, "close"))
    return out


def h_emax(days, slip):
    """EMA 5/20 on the contract's continuous hourly closes; positions intraday only (A8.1)."""
    out = []
    hist_c, hist_exp = [], None
    for d in days:
        if d.expiry != hist_exp:
            hist_c, hist_exp = [], d.expiry
        n, pos, entry, i0 = len(d.o), 0, None, None
        for t in range(n):
            series = np.array(hist_c, dtype=float)
            want = 0
            if len(series) >= 20:
                diff = ema(series, 5)[-1] - ema(series, 20)[-1]
                want = 1 if diff > 0 else (-1 if diff < 0 else 0)
            if d.hm[t] >= "23:00":
                want = 0 if want != pos else pos          # no new entries on the last bar
            if want != pos:
                px = d.o[t]
                if pos:
                    out.append(trade(d, pos, entry, px - pos * slip, i0, t, "cross"))
                pos = 0
                if want:
                    pos, entry, i0 = want, px + want * slip, t
            hist_c.append(d.c[t])
        if pos:
            out.append(trade(d, pos, entry, d.c[-1] - pos * slip, i0, n - 1, "close"))
    return out


def h_orbus(days, slip):
    out = []
    for d in days:
        a, k = d.idx("18:00"), d.idx("19:00")
        if a is None or k is None:
            continue
        hi, lo = d.h[a], d.l[a]
        t = breakout(d, hi, lo, k, slip, lambda side, e: lo if side > 0 else hi)
        if t:
            out.append(t)
    return out
