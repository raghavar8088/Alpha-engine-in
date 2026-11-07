"""Fill engine for the YouTube top-20 study: the Booming Bulls engine (../booming_bulls_2026_11/bb_engine.py)
extended for stop-entry orders, indicator exits, holding limits, explicit target prices, percentage costs
(NSE stocks) and multi-day trades (daily data). The fill rules are unchanged:
  market entries fill at the open of the row after the signal bar at the ask (longs) / bid (shorts) plus
  slippage; stop-entry orders fill at max(trigger, open) (longs) once a row's ask high reaches the trigger;
  stops and targets are resting orders checked row by row; stop first when a row touches both; a row
  opening beyond the stop fills at its open; exits on indicator flags happen at the next row's open.
"rows" are minutes for most markets, 5-minute bars for NSE stocks and days for daily markets.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date

import numpy as np

_FUT_STT = [(date(2026, 4, 1), 0.0005), (date(2024, 10, 1), 0.0002), (date(1900, 1, 1), 0.000125)]
_FUT_EXCH = [(date(2024, 10, 1), 0.0000173), (date(1900, 1, 1), 0.00002)]


def _rate(schedule, on: date) -> float:
    for start, rate in schedule:
        if on >= start:
            return rate
    return schedule[-1][1]


def futures_fees(entry: float, exit_: float, qty: int, side: int, on: date) -> float:
    """Angel One NIFTY/BANKNIFTY futures charges for one round trip of qty units (rupees)."""
    buy = (entry if side > 0 else exit_) * qty
    sell = (exit_ if side > 0 else entry) * qty
    turnover = buy + sell
    brokerage = 40.0
    stt = sell * _rate(_FUT_STT, on)
    exch = turnover * _rate(_FUT_EXCH, on)
    sebi = turnover * 0.000001
    ipft = turnover * 0.000001
    stamp = buy * 0.00002
    gst = 0.18 * (brokerage + exch + sebi + ipft)
    return brokerage + stt + exch + sebi + ipft + stamp + gst


@dataclass
class Signal:
    day: int
    k: int                       # last row of the signal bar; orders start at row k + 1
    side: int
    stop: float
    setup: str = ""
    info: dict = field(default_factory=dict)
    entry_stop: float | None = None   # stop-entry trigger price (None = market order at the next open)
    expire_k: int | None = None       # last row the stop-entry order may fill
    target_px: float | None = None    # explicit target price (overrides Exits.target_r)
    entry_limit: float | None = None  # limit-entry price (longs fill when the ask trades down to it)
    alt: "Signal | None" = None        # OCO partner: an opposite stop-entry; whichever triggers first fills


@dataclass
class Exits:
    target_r: float | None = 2.0
    target_abs: float | None = None       # fixed target distance from the entry fill (price units)
    be_at_frac: float | None = None
    be_at_r: float | None = None
    be_at_abs: float | None = None        # breakeven once price is this far in favour (price units)
    trail_from_r: float | None = None
    trail_bars: object = None
    trail_ema: np.ndarray | None = None
    partial_at_r: float | None = None
    lock_at_r: float | None = None
    lock_to_r: float | None = None
    xbars: object = None                  # bars whose closes carry exit flags
    xlong: np.ndarray | None = None       # per xbar: exit a long at the next row's open
    xshort: np.ndarray | None = None
    max_hold: int | None = None           # exit at the open of row entry + max_hold


@dataclass
class Limits:
    max_per_day: int = 1
    stop_after_target: bool = True
    second_only_after_stop: bool = True
    max_stops_per_day: int = 99


@dataclass
class Trade:
    market: str
    strategy: str
    variant: str
    setup: str
    day: int
    date: str
    split: str
    excluded: bool
    side: int
    sig_k: int
    entry_k: int
    exit_k: int
    entry: float
    stop: float
    target: float
    exit: float
    reason: str
    risk: float
    r_gross: float
    r_net: float
    cost_r: float
    rows_held: int
    mfe_r: float
    mae_r: float


def _first(mask: np.ndarray) -> int:
    if not len(mask):
        return -1
    i = int(np.argmax(mask))
    return i if mask[i] else -1


class Engine:
    def __init__(self, m, spread_x=1.0, slip_x=1.0, comm_x=1.0, entry_delay=0):
        self.m = m
        c = m.cost
        self.slip_abs = c.slip * slip_x
        self.slip_pct = getattr(c, "pct_slip", 0.0) * slip_x
        self.comm_abs = c.commission * comm_x
        self.comm_pct = getattr(c, "pct_comm", 0.0) * comm_x
        self.fut = c.futures_fees
        self.lot = c.lot
        self.fee_x = comm_x
        self.entry_delay = entry_delay
        self.half = m.half * spread_x
        self.overnight = getattr(m, "overnight", False)

    def _slip(self, px):
        return self.slip_abs + self.slip_pct * px

    def _walk(self, k0, k_end, side, entry, stop, target, ex: Exits, slip):
        m, hf = self.m, self.half[k0:k_end + 1]
        if side > 0:
            lo, hi, op, cl = m.l[k0:k_end + 1] - hf, m.h[k0:k_end + 1] - hf, m.o[k0:k_end + 1] - hf, m.c[k0:k_end + 1] - hf
        else:
            lo, hi, op, cl = m.l[k0:k_end + 1] + hf, m.h[k0:k_end + 1] + hf, m.o[k0:k_end + 1] + hf, m.c[k0:k_end + 1] + hf
        risk = abs(entry - stop)
        fav = (hi - entry) if side > 0 else (entry - lo)
        adv = (entry - lo) if side > 0 else (hi - entry)
        n = len(lo)

        def stop_hits(level, start=0):
            return lo[start:] <= level if side > 0 else hi[start:] >= level

        def tgt_hits(level, start=0):
            if level is None:
                return np.zeros(n - start, bool)
            return hi[start:] >= level if side > 0 else lo[start:] <= level

        def stop_fill(j, level):
            g = op[j]
            return (min(level, g) - slip) if side > 0 else (max(level, g) + slip)

        cur_stop, start, booked = stop, 0, None
        be_level = None
        if ex.be_at_frac is not None and target is not None:
            be_level = ex.be_at_frac * abs(target - entry)
        elif ex.be_at_r is not None:
            be_level = ex.be_at_r * risk
        elif ex.be_at_abs is not None:
            be_level = ex.be_at_abs
        events = []
        if be_level is not None:
            events.append(("be", be_level, entry))
        if ex.lock_at_r is not None:
            events.append(("lock", ex.lock_at_r * risk, entry + side * ex.lock_to_r * risk))
        if ex.partial_at_r is not None:
            events.append(("partial", ex.partial_at_r * risk, entry))
        triggers = sorted((j, kind, ns) for kind, lvl, ns in events for j in [_first(fav >= lvl)] if j >= 0)
        for j, kind, new_stop in triggers:
            if j >= start:
                s = _first(stop_hits(cur_stop, start)[: j - start + 1])
                t = _first(tgt_hits(target, start)[: j - start + 1])
                if s >= 0 and (t < 0 or s <= t):
                    r = start + s
                    return r, stop_fill(r, cur_stop), "stop" if cur_stop == stop else "be_stop", booked, float(fav[:r + 1].max()), float(adv[:r + 1].max())
                if t >= 0:
                    r = start + t
                    return r, target, "target", booked, float(fav[:r + 1].max()), float(adv[:r + 1].max())
            if kind == "partial":
                booked = ex.partial_at_r
            if side * (new_stop - cur_stop) > 0:
                cur_stop = new_stop
            start = max(start, j + 1)
            if start >= n:
                break
        if start >= n:
            return n - 1, cl[n - 1] - side * slip, "time", booked, float(fav.max()), float(adv.max())
        s = _first(stop_hits(cur_stop, start))
        t = _first(tgt_hits(target, start))
        s_abs = start + s if s >= 0 else n
        t_abs = start + t if t >= 0 else n
        x_abs = n
        # 9-EMA trail
        if ex.trail_from_r is not None and ex.trail_bars is not None:
            ta = _first(fav >= ex.trail_from_r * risk)
            if ta >= 0:
                b = ex.trail_bars
                lo_b = int(np.searchsorted(b.i1, k0 + ta, "left"))
                hi_b = int(np.searchsorted(b.i1, k_end, "right"))
                if hi_b > lo_b:
                    cross = b.c[lo_b:hi_b] < ex.trail_ema[lo_b:hi_b] if side > 0 else b.c[lo_b:hi_b] > ex.trail_ema[lo_b:hi_b]
                    q = _first(cross)
                    if q >= 0:
                        x_abs = min(x_abs, int(b.i1[lo_b + q]) + 1 - k0)
        # indicator exit flags: the first flagged bar ending at or after the entry row
        if ex.xbars is not None:
            b = ex.xbars
            flags = ex.xlong if side > 0 else ex.xshort
            lo_b = int(np.searchsorted(b.i1, k0, "left"))
            hi_b = int(np.searchsorted(b.i1, k_end, "right"))
            if hi_b > lo_b:
                q = _first(flags[lo_b:hi_b])
                if q >= 0:
                    x_abs = min(x_abs, int(b.i1[lo_b + q]) + 1 - k0)
        if ex.max_hold is not None:
            x_abs = min(x_abs, ex.max_hold)
        end = min(s_abs, t_abs, x_abs)
        if end >= n:
            return n - 1, cl[n - 1] - side * slip, "time", booked, float(fav.max()), float(adv.max())
        mfe, mae = float(fav[:end + 1].max()), float(adv[:end + 1].max())
        if s_abs == end:
            return end, stop_fill(end, cur_stop), "stop" if cur_stop == stop else "be_stop", booked, mfe, mae
        if t_abs == end:
            return end, target, "target", booked, mfe, mae
        return end, op[end] - side * slip, "exit_signal", booked, mfe, mae

    def _trigger_row(self, sig: Signal, k: int, k_end: int):
        m = self.m
        last = min(sig.expire_k if sig.expire_k is not None else k_end, k_end)
        if last < k:
            return None
        hf = self.half[k:last + 1]
        hit = _first(m.h[k:last + 1] + hf >= sig.entry_stop) if sig.side > 0 else _first(m.l[k:last + 1] - hf <= sig.entry_stop)
        return None if hit < 0 else k + hit

    def trade(self, sig: Signal, ex: Exits, k_end: int, strategy: str, variant: str):
        m = self.m
        k = sig.k + 1 + self.entry_delay
        if k > k_end or (not self.overnight and m.day[min(k, len(m.day) - 1)] != sig.day):
            return None, "no_row_left"
        if sig.alt is not None:                       # OCO: take whichever stop-entry triggers first
            ra, rb = self._trigger_row(sig, k, k_end), self._trigger_row(sig.alt, k, k_end)
            if ra is None and rb is None:
                return None, "stop_entry_not_triggered"
            if ra is not None and rb is not None and ra == rb:
                return None, "oco_both_same_row"
            if ra is None or (rb is not None and rb < ra):
                a = sig.alt
                sig = Signal(sig.day, sig.k, a.side, a.stop, a.setup, a.info, a.entry_stop, a.expire_k, a.target_px)
        if sig.entry_limit is not None:
            last = min(sig.expire_k if sig.expire_k is not None else k_end, k_end)
            if last < k:
                return None, "limit_expired"
            hf = self.half[k:last + 1]
            if sig.side > 0:
                hit = _first(m.l[k:last + 1] + hf <= sig.entry_limit)
            else:
                hit = _first(m.h[k:last + 1] - hf >= sig.entry_limit)
            if hit < 0:
                return None, "limit_not_filled"
            k = k + hit
            hfk = self.half[k]
            slip = self._slip(sig.entry_limit)
            entry = min(sig.entry_limit, m.o[k] + hfk) if sig.side > 0 else max(sig.entry_limit, m.o[k] - hfk)
        elif sig.entry_stop is None:
            hf = self.half[k]
            slip = self._slip(m.o[k])
            entry = (m.o[k] + hf + slip) if sig.side > 0 else (m.o[k] - hf - slip)
        else:
            last = min(sig.expire_k if sig.expire_k is not None else k_end, k_end)
            if last < k:
                return None, "stop_entry_expired"
            hf = self.half[k:last + 1]
            if sig.side > 0:
                hit = _first(m.h[k:last + 1] + hf >= sig.entry_stop)
            else:
                hit = _first(m.l[k:last + 1] - hf <= sig.entry_stop)
            if hit < 0:
                return None, "stop_entry_not_triggered"
            k = k + hit
            slip = self._slip(sig.entry_stop)
            hfk = self.half[k]
            if sig.side > 0:
                entry = max(sig.entry_stop, m.o[k] + hfk) + slip
            else:
                entry = min(sig.entry_stop, m.o[k] - hfk) - slip
        risk = (entry - sig.stop) * sig.side
        if not risk > 0:
            return None, "entry_beyond_stop"
        unit = float(sig.info.get("risk_unit", risk))     # a strategy without a real stop sizes on a risk unit
        if ex.target_abs is not None:
            target = entry + sig.side * ex.target_abs
        elif sig.target_px is not None:
            target = sig.target_px
            if (target - entry) * sig.side <= 0:
                return None, "entry_beyond_target"
        else:
            target = None if ex.target_r is None else entry + sig.side * ex.target_r * risk
        # search a growing window (same result as walking to k_end; multi-day trades on minute rows stay fast)
        win = 20000
        while True:
            ke = min(k_end, k + win)
            r, px, reason, booked, mfe, mae = self._walk(k, ke, sig.side, entry, sig.stop, target, ex, slip)
            if reason == "time" and ke < k_end:
                win *= 8
                continue
            break
        exit_row = k + r
        pnl = sig.side * (px - entry)
        if booked is not None:
            pnl = 0.5 * booked * risk + 0.5 * pnl
        comm = 2 * self.comm_abs + self.comm_pct * (entry + px)
        d = m.day_date(m.day[k] if self.overnight else sig.day)
        if self.fut:
            comm += futures_fees(entry, px, self.lot, sig.side, d) / self.lot * self.fee_x
        net = pnl - comm
        paid = self.half[k] + slip + self.half[exit_row] + (0.0 if reason == "target" else self._slip(px))
        gross = pnl + paid
        day_of_entry = int(m.day[k]) if self.overnight else sig.day
        t = Trade(m.name, strategy, variant, sig.setup, day_of_entry, str(d), m.split_of(day_of_entry),
                  bool(m.excluded[day_of_entry]), sig.side, sig.k, k, exit_row, entry, sig.stop,
                  float("nan") if target is None else target, px, reason, unit, gross / unit, net / unit,
                  (gross - net) / unit, exit_row - k + 1, mfe / unit, mae / unit)
        return t, None


def run_book(engine: Engine, signals, ex: Exits, limits: Limits, k_end_of_day, strategy: str, variant: str):
    trades, rejects = [], {}
    busy_until = -1
    day_state = {}

    def rej(why):
        rejects[why] = rejects.get(why, 0) + 1

    for s in signals:
        st = day_state.setdefault(s.day, {"n": 0, "stops": 0, "done": False, "last": None})
        if s.k <= busy_until:
            rej("position_open")
            continue
        if st["done"]:
            rej("day_closed")
            continue
        if st["n"] >= limits.max_per_day:
            rej("day_limit")
            continue
        if st["n"] > 0 and limits.second_only_after_stop and st["last"] != "stop":
            rej("needs_prior_stop")
            continue
        k_end = k_end_of_day(s.day)
        if k_end is None or s.k >= k_end:
            rej("after_forced_exit")
            continue
        t, why = engine.trade(s, ex, k_end, strategy, variant)
        if t is None:
            rej(why)
            continue
        trades.append(t)
        busy_until = t.exit_k
        st["n"] += 1
        st["last"] = t.reason
        if t.reason == "stop":
            st["stops"] += 1
            if st["stops"] >= limits.max_stops_per_day:
                st["done"] = True
        if t.reason == "target" and limits.stop_after_target:
            st["done"] = True
    return trades, rejects


def forced_exit_rows(m, clock: str, minute_of_day: int):
    """Per day: the last row whose clock time is <= minute_of_day (17:00-roll markets: after-midnight part only).
    clock 'end' = the market's last row (daily data: trades may run to the end of the data)."""
    if clock == "end":
        last = len(m.t) - 1
        return lambda d: last
    clk = m.ist if clock == "ist" else m.ny
    out = np.full(m.n_days, -1, np.int64)
    ok = clk <= minute_of_day
    for d in range(m.n_days):
        a, b = m.d0[d], m.d1[d]
        seg = ok[a:b]
        if m.name in ("XAUUSD", "EURUSD", "GBPUSD"):
            seg = seg & (clk[a:b] < 17 * 60)
        idx = np.flatnonzero(seg)
        if len(idx):
            out[d] = a + idx[-1]
    return lambda d: (None if out[d] < 0 else int(out[d]))


def trades_to_rows(trades) -> list[dict]:
    return [asdict(t) for t in trades]
