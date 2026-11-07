"""Fill engine (Phase 7): turns strategy signals into trades under the rules of PREREGISTRATION.md section 1.

A strategy emits Signal objects in time order (bb_strategies.py). The engine takes them one at a time:
one open position per book, the day's trade limits, entry at the open of the minute after the signal bar,
then a minute-by-minute walk of the bid (longs) or ask (shorts) for the stop, target, breakeven, trailing
exit and the day's forced exit. Stop first when a minute touches both. Every skipped signal is logged with
a reason (Phase 5 "log signals and rejections").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date

import numpy as np

from bb_markets import Bars, CostModel, Minutes, ema

# Angel One futures fees (the formula of backend/app/services/angel_fees.futures_round_trip,
# as in ../liquidity_sweep_2026_11/ls_common.py)
_FUT_STT = [(date(2026, 4, 1), 0.0005), (date(2024, 10, 1), 0.0002), (date(1900, 1, 1), 0.000125)]
_FUT_EXCH = [(date(2024, 10, 1), 0.0000173), (date(1900, 1, 1), 0.00002)]


def _rate(schedule, on: date) -> float:
    for start, rate in schedule:
        if on >= start:
            return rate
    return schedule[-1][1]


def futures_fees(entry: float, exit_: float, qty: int, side: int, on: date) -> float:
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
    k: int               # last minute row of the signal bar; entry fills at row k + 1
    side: int            # +1 long, -1 short
    stop: float
    setup: str = ""
    info: dict = field(default_factory=dict)


@dataclass
class Exits:
    """How a trade is managed (the variant)."""
    target_r: float | None = 2.0          # None = no fixed target (trailing variants)
    be_at_frac: float | None = None       # breakeven once this fraction of the target distance is reached
    be_at_r: float | None = None          # ... or once this many R are reached
    trail_from_r: float | None = None     # 9-EMA trail activates at this R
    trail_bars: Bars | None = None
    trail_ema: np.ndarray | None = None
    partial_at_r: float | None = None     # book half here, stop to breakeven for the rest
    lock_at_r: float | None = None        # BB-09 S2: once lock_at_r is reached ...
    lock_to_r: float | None = None        # ... the stop moves to +lock_to_r


@dataclass
class Limits:
    max_per_day: int = 1
    stop_after_target: bool = True        # a target ends the day
    second_only_after_stop: bool = True   # a further trade only after a stop-out
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
    risk: float          # |entry - stop| in price units
    r_gross: float
    r_net: float
    cost_r: float
    minutes_held: int
    mfe_r: float
    mae_r: float


def _first(mask: np.ndarray) -> int:
    i = int(np.argmax(mask)) if len(mask) else 0
    return i if len(mask) and mask[i] else -1


class Engine:
    """spread_x / slip_x / comm_x scale the base costs (comm_x also scales the futures fees);
    entry_delay > 0 fills that many minutes later than the rule (robustness)."""

    def __init__(self, m: Minutes, spread_x: float = 1.0, slip_x: float = 1.0, comm_x: float = 1.0,
                 entry_delay: int = 0):
        self.m = m
        self.cost = m.cost.scaled(spread_x, slip_x, comm_x)
        self.fee_x = comm_x
        self.entry_delay = entry_delay
        self.half = m.half * spread_x        # loaders store the fixed half-spread per row where there is one

    # ── one trade ──────────────────────────────────────────────────────────────────
    def _walk(self, k0: int, k_end: int, side: int, entry: float, stop: float, target: float | None, ex: Exits):
        """Walk rows k0..k_end inclusive. Returns (exit_row, exit_price, reason, booked_half_r or None, mfe, mae)."""
        m, hf, slip = self.m, self.half[k0:k_end + 1], self.cost.slip
        if side > 0:
            lo, hi, op, cl = m.l[k0:k_end + 1] - hf, m.h[k0:k_end + 1] - hf, m.o[k0:k_end + 1] - hf, m.c[k0:k_end + 1] - hf
        else:
            lo, hi, op, cl = m.l[k0:k_end + 1] + hf, m.h[k0:k_end + 1] + hf, m.o[k0:k_end + 1] + hf, m.c[k0:k_end + 1] + hf
        risk = abs(entry - stop)
        fav = (hi - entry) if side > 0 else (entry - lo)          # favourable excursion per row
        adv = (entry - lo) if side > 0 else (hi - entry)
        n = len(lo)

        def stop_hits(level, start=0):
            if side > 0:
                return lo[start:] <= level
            return hi[start:] >= level

        def tgt_hits(level, start=0):
            if level is None:
                return np.zeros(n - start, bool)
            if side > 0:
                return hi[start:] >= level
            return lo[start:] <= level

        def stop_fill(j, level):
            g = op[j]
            if side > 0:
                return min(level, g) - slip
            return max(level, g) + slip

        cur_stop, start, booked = stop, 0, None
        # stage changes: breakeven / lock / partial / trail activation, each from the row after the trigger
        be_level = None
        if ex.be_at_frac is not None and target is not None:
            be_level = ex.be_at_frac * abs(target - entry)
        elif ex.be_at_r is not None:
            be_level = ex.be_at_r * risk
        events = []
        if be_level is not None:
            events.append(("be", be_level, entry))
        if ex.lock_at_r is not None:
            events.append(("lock", ex.lock_at_r * risk, entry + side * ex.lock_to_r * risk))
        if ex.partial_at_r is not None:
            events.append(("partial", ex.partial_at_r * risk, entry))
        trail_on_row = None
        if ex.trail_from_r is not None:
            ta = _first(fav >= ex.trail_from_r * risk)
            trail_on_row = ta if ta >= 0 else None

        # process event triggers in time order
        triggers = []
        for kind, lvl, new_stop in events:
            j = _first(fav >= lvl)
            if j >= 0:
                triggers.append((j, kind, new_stop))
        triggers.sort()
        seg_targets = target
        for j, kind, new_stop in triggers:
            # does the trade end before (or on) row j under the current rules?
            s = _first(stop_hits(cur_stop, start)[: j - start + 1]) if j >= start else -1
            t = _first(tgt_hits(seg_targets, start)[: j - start + 1]) if j >= start else -1
            if s >= 0 and (t < 0 or s <= t):
                r = start + s
                return r, stop_fill(r, cur_stop), "stop" if cur_stop == stop else "be_stop", booked, float(fav[:r + 1].max()), float(adv[:r + 1].max())
            if t >= 0:
                r = start + t
                return r, seg_targets, "target", booked, float(fav[:r + 1].max()), float(adv[:r + 1].max())
            if kind == "partial":
                booked = ex.partial_at_r
            cur_stop = new_stop if side * (new_stop - cur_stop) > 0 else cur_stop
            start = j + 1
            if start >= n:
                break
        if start >= n:
            r = n - 1
            return r, cl[r] - side * slip, "time", booked, float(fav.max()), float(adv.max())
        s = _first(stop_hits(cur_stop, start))
        t = _first(tgt_hits(seg_targets, start))
        s_abs = start + s if s >= 0 else n
        t_abs = start + t if t >= 0 else n
        x_abs = n
        if trail_on_row is not None and ex.trail_bars is not None:
            b = ex.trail_bars
            k_act = k0 + trail_on_row
            lo_b = int(np.searchsorted(b.i1, k_act, "left"))
            hi_b = int(np.searchsorted(b.i1, k_end, "right"))
            if hi_b > lo_b:
                cls_ = b.c[lo_b:hi_b]
                e9 = ex.trail_ema[lo_b:hi_b]
                cross = cls_ < e9 if side > 0 else cls_ > e9
                q = _first(cross)
                if q >= 0:
                    x_abs = int(b.i1[lo_b + q]) + 1 - k0      # exit at the next minute's open
        end = min(s_abs, t_abs, x_abs)
        if end >= n:
            r = n - 1
            return r, cl[r] - side * slip, "time", booked, float(fav.max()), float(adv.max())
        mfe, mae = float(fav[:end + 1].max()), float(adv[:end + 1].max())
        if s_abs == end:
            return end, stop_fill(end, cur_stop), "stop" if cur_stop == stop else "be_stop", booked, mfe, mae
        if t_abs == end:
            return end, seg_targets, "target", booked, mfe, mae
        return end, op[end] - side * slip, "trail", booked, mfe, mae

    def trade(self, sig: Signal, ex: Exits, k_end: int, strategy: str, variant: str):
        """Returns (Trade | None, reject_reason | None)."""
        m = self.m
        k = sig.k + 1 + self.entry_delay
        if k > k_end or m.day[k] != sig.day:
            return None, "no_minute_left"
        hf, slip = self.half[k], self.cost.slip
        entry = (m.o[k] + hf + slip) if sig.side > 0 else (m.o[k] - hf - slip)
        risk = (entry - sig.stop) * sig.side
        if not risk > 0:
            return None, "entry_beyond_stop"
        target = None if ex.target_r is None else entry + sig.side * ex.target_r * risk
        if target is not None:
            bidask_now = (m.o[k] - hf) if sig.side > 0 else (m.o[k] + hf)
            if sig.side * (bidask_now - target) >= 0:
                return None, "entry_beyond_target"
        r, px, reason, booked, mfe, mae = self._walk(k, k_end, sig.side, entry, sig.stop, target, ex)
        exit_row = k + r
        pnl = sig.side * (px - entry)
        if booked is not None:                       # half booked at partial_at_r, rest as walked
            pnl = 0.5 * booked * risk + 0.5 * pnl
        # costs: spreads and slippage are already in the fills; commission per unit a side; futures fees
        c = self.cost
        comm = 2 * c.commission
        d = m.day_date(sig.day)
        if c.futures_fees:
            comm += futures_fees(entry, px, c.lot, sig.side, d) / c.lot * self.fee_x
        net = pnl - comm
        # gross = the same path with no spread, slippage, commission or fees. Paid per unit: half-spread +
        # slippage on the market entry; on the exit, half-spread (a target is a resting bid/ask order, so
        # no slippage) or half-spread + slippage (stop, trail, time). A partial's two exits use the exit
        # row's spread for both halves (approximation).
        paid = hf + slip + self.half[exit_row] + (0.0 if reason == "target" else slip)
        gross = pnl + paid
        t = Trade(m.name, strategy, variant, sig.setup, sig.day, str(d), m.split_of(sig.day), bool(m.excluded[sig.day]),
                  sig.side, sig.k, k, exit_row, entry, sig.stop, float("nan") if target is None else target, px, reason,
                  risk, gross / risk, net / risk, (gross - net) / risk, exit_row - k + 1, mfe / risk, mae / risk)
        return t, None


def run_book(engine: Engine, signals: list[Signal], ex: Exits, limits: Limits, k_end_of_day, strategy: str,
             variant: str) -> tuple[list[Trade], dict]:
    """Sequential book: one position at a time and the day's limits. k_end_of_day(day) -> forced-exit row."""
    trades: list[Trade] = []
    rejects: dict[str, int] = {}
    busy_until = -1
    day_state: dict[int, dict] = {}

    def rej(why):
        rejects[why] = rejects.get(why, 0) + 1

    for s in signals:
        st = day_state.setdefault(s.day, {"n": 0, "stops": 0, "done": False, "last_reason": None})
        if s.k <= busy_until:
            rej("position_open")
            continue
        if st["done"]:
            rej("day_closed")
            continue
        if st["n"] >= limits.max_per_day:
            rej("day_limit")
            continue
        if st["n"] > 0 and limits.second_only_after_stop and st["last_reason"] not in ("stop",):
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
        st["last_reason"] = t.reason
        if t.reason in ("stop",):
            st["stops"] += 1
            if st["stops"] >= limits.max_stops_per_day:
                st["done"] = True
        if t.reason == "target" and limits.stop_after_target:
            st["done"] = True
    return trades, rejects


def forced_exit_rows(m: Minutes, clock: str, minute_of_day: int):
    """Per day: the last row whose clock time (ist/ny minutes) is <= minute_of_day, searching backwards from
    the day's end (for 17:00-roll days, only the after-midnight part qualifies when minute_of_day < 17:00)."""
    clk = m.ist if clock == "ist" else m.ny
    out = np.full(m.n_days, -1, np.int64)
    ok = clk <= minute_of_day
    for d in range(m.n_days):
        a, b = m.d0[d], m.d1[d]
        seg = ok[a:b]
        if m.name in ("XAUUSD", "EURUSD", "GBPUSD"):
            # rows before NY midnight belong to the session's first evening (clock >= 17:00), never the end
            seg = seg & (clk[a:b] < 17 * 60)
        idx = np.flatnonzero(seg)
        if len(idx):
            out[d] = a + idx[-1]
    return lambda d: (None if out[d] < 0 else int(out[d]))


def trades_to_rows(trades: list[Trade]) -> list[dict]:
    return [asdict(t) for t in trades]
