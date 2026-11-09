"""Fill engine for the 11-channel strategies: the YouTube study's yt_engine, unchanged for every strategy whose exits it
already has, plus the per-trade exits some of these videos need, and simulators for the two multi-leg strategies.

The fill rules are yt_engine's: market entries fill at the next row's open at the ask (longs) / bid (shorts) plus
slippage; stop-entries at max(trigger, open); limits at min(limit, open) once the ask trades down to them; resting
stops and targets row by row, the stop first when a row touches both; a row opening beyond the stop fills at its open;
exits on closing conditions at the next row's open.

XExits adds, per trade:
  trail          ("dist_r", start_r, dist_r): once price is start_r R in favour, the stop trails dist_r R behind the
                 best price; ("dist_frac", start_frac, dist_frac): the same in fractions of the entry price;
                 ("chand", bars, atr, mult[, "high"]): at each completed bar the stop rises to the best close (or, with
                 "high", the best price) since entry minus mult x atr[bar];
                 ("level", bars, long_level, short_level): at each completed bar the stop moves to the
                 bar's level when that is better. A new stop applies from the next row.
  partial_px     book half at sig.info["partial_px"] (a resting limit) and move the stop to the entry
  partial_flag   (bars, long_flags, short_flags): book half at the next open after the first flagged close
  tgt_level      (bars, long_level, short_level): a moving target; after bar j completes the target is level[j]
  close_stop     (bars,): exit at the next open after a close beyond sig.info["close_stop"]
  be_close       (bars,): stop to the entry after a close beyond sig.info["be_close"]
  x_from_r       the xbars exit flags count only after the trade has been x_from_r R in favour ("the rest exits on ...")
With a partial, the trade's result is half the booked part plus half the rest. A signal with sig.info["stop_dist"]
has its stop placed that far from the actual entry fill (as a Pine strategy's `loss=` exit), not at sig.stop (and
"stop_frac" / "target_frac": a stop / target that fraction of the fill away); one with sig.info["k_last"] is closed at
that row's close if nothing else closed it first (a time exit of its own).
run_book_x keeps one position at a time in the order orders fill (yt_engine.run_book's order of placement lets a late
fill block an earlier one), plus sig.info["group"]: once a group has given a trade its other orders are skipped ("one
trade per zone / per stack").
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

import numpy as np

import yt_engine as YE
from yt_engine import Exits, Limits, Signal, Trade, forced_exit_rows, futures_fees, run_book  # noqa: F401


@dataclass
class XExits(Exits):
    trail: tuple | None = None
    partial_px: bool = False
    partial_flag: tuple | None = None
    tgt_level: tuple | None = None
    close_stop: tuple | None = None
    be_close: tuple | None = None
    x_from_r: float | None = None       # the xbars exit flags count only once the trade has been this many R in favour
    partial_be: bool = True             # move the stop to the entry once a partial is booked


def _bar_end_map(bars, k0: int, k1: int) -> dict:
    """{last row of a bar: bar index} for bars ending within rows k0..k1."""
    a = int(np.searchsorted(bars.i1, k0, "left"))
    z = int(np.searchsorted(bars.i1, k1, "right"))
    return {int(bars.i1[j]): j for j in range(a, z)}


class XEngine(YE.Engine):
    """yt_engine.Engine; trades with XExits take the row-by-row walk below, all others the parent's own."""

    def _enter(self, sig: Signal, k_end: int):
        """The parent's entry rules: (row, entry price, slippage, signal) or (None, reason)."""
        m = self.m
        k = sig.k + 1 + self.entry_delay
        if k > k_end or (not self.overnight and m.day[min(k, len(m.day) - 1)] != sig.day):
            return None, "no_row_left"
        if sig.alt is not None:
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
            hit = YE._first(m.l[k:last + 1] + hf <= sig.entry_limit) if sig.side > 0 else YE._first(m.h[k:last + 1] - hf >= sig.entry_limit)
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
            hit = YE._first(m.h[k:last + 1] + hf >= sig.entry_stop) if sig.side > 0 else YE._first(m.l[k:last + 1] - hf <= sig.entry_stop)
            if hit < 0:
                return None, "stop_entry_not_triggered"
            k = k + hit
            slip = self._slip(sig.entry_stop)
            hfk = self.half[k]
            entry = (max(sig.entry_stop, m.o[k] + hfk) + slip) if sig.side > 0 else (min(sig.entry_stop, m.o[k] - hfk) - slip)
        return (k, float(entry), float(slip), sig), None

    def trade(self, sig: Signal, ex: Exits, k_end: int, strategy: str, variant: str):
        special = any(sig.info.get(k) is not None for k in ("stop_dist", "stop_frac", "target_frac", "k_last"))
        if not isinstance(ex, XExits):
            if not special:
                return super().trade(sig, ex, k_end, strategy, variant)
            ex = XExits(**{f.name: getattr(ex, f.name) for f in fields(Exits)})
        if sig.info.get("k_last") is not None:          # a time exit of its own (e.g. the next session's close)
            k_end = min(k_end, int(sig.info["k_last"]))
        got, why = self._enter(sig, k_end)
        if got is None:
            return None, why
        k, entry, slip, sig = got
        side = sig.side
        if sig.info.get("stop_dist") is not None:        # a stop placed from the actual fill (a Pine `loss=` order)
            sig = replace(sig, stop=float(entry - side * float(sig.info["stop_dist"])))
        elif sig.info.get("stop_frac") is not None:      # a stop a fixed fraction of the fill away ("a 2% stop")
            sig = replace(sig, stop=float(entry * (1 - side * float(sig.info["stop_frac"]))))
        risk = (entry - sig.stop) * side
        if not risk > 0:
            return None, "entry_beyond_stop"
        unit = float(sig.info.get("risk_unit", risk))
        if sig.info.get("target_frac") is not None:      # a target a fixed fraction of the fill away ("+15%")
            target = entry * (1 + side * float(sig.info["target_frac"]))
        elif ex.target_abs is not None:
            target = entry + side * ex.target_abs
        elif sig.target_px is not None:
            target = float(sig.target_px)
            if (target - entry) * side <= 0:
                return None, "entry_beyond_target"
        else:
            target = None if ex.target_r is None else entry + side * ex.target_r * risk
        r, px, reason, booked, mfe, mae = self._walk_x(sig, k, k_end, entry, risk, target, ex, slip)
        m = self.m
        exit_row = k + r
        pnl = side * (px - entry)
        if booked is not None:
            pnl = 0.5 * booked + 0.5 * pnl
        comm = 2 * self.comm_abs + self.comm_pct * (entry + px)
        d = m.day_date(m.day[k] if self.overnight else sig.day)
        if self.fut:
            comm += futures_fees(entry, px, self.lot, side, d) / self.lot * self.fee_x
        net = pnl - comm
        paid = self.half[k] + slip + self.half[exit_row] + (0.0 if reason == "target" else self._slip(px))
        gross = pnl + paid
        day_of_entry = int(m.day[k]) if self.overnight else sig.day
        t = Trade(m.name, strategy, variant, sig.setup, day_of_entry, str(d), m.split_of(day_of_entry),
                  bool(m.excluded[day_of_entry]), side, sig.k, k, exit_row, entry, sig.stop,
                  float("nan") if target is None else target, px, reason, unit, gross / unit, net / unit,
                  (gross - net) / unit, exit_row - k + 1, mfe / unit, mae / unit)
        return t, None

    def _walk_x(self, sig, k0, k_end, entry, risk, target, ex: XExits, slip):
        """Row by row from the entry row to k_end. Returns (rows after k0, exit price, reason, booked part or None,
        max favourable, max adverse) in price units."""
        m, side = self.m, sig.side
        hf = self.half
        sgn = -1.0 if side > 0 else 1.0                 # longs sell at the bid, shorts buy at the ask
        cur_stop = float(sig.stop)
        stop_kind = "stop"
        best_px = entry                                  # best price reached (bid for longs, ask for shorts)
        best_close = entry
        mfe = mae = 0.0
        booked = None
        pending_exit = False
        pending_partial = False
        partial_level = None
        if ex.partial_at_r is not None:
            partial_level = entry + side * ex.partial_at_r * risk
        elif ex.partial_px and sig.info.get("partial_px") is not None:
            pl = float(sig.info["partial_px"])
            partial_level = pl if (pl - entry) * side > 0 else None
        be_level = None
        if ex.be_at_frac is not None and target is not None:
            be_level = ex.be_at_frac * abs(target - entry)
        elif ex.be_at_r is not None:
            be_level = ex.be_at_r * risk
        elif ex.be_at_abs is not None:
            be_level = ex.be_at_abs
        cur_target = target
        ends = {}
        for name in ("xbars", "close_stop", "partial_flag", "tgt_level", "be_close"):
            spec = getattr(ex, name)
            bars = spec if name == "xbars" else (spec[0] if spec else None)
            if bars is not None:
                ends[name] = (bars, _bar_end_map(bars, k0, k_end))
        tr = ex.trail
        if tr is not None and tr[0] in ("chand", "level"):
            ends["trail"] = (tr[1], _bar_end_map(tr[1], k0, k_end))
        if ex.trail_from_r is not None and ex.trail_bars is not None:
            ends["trail_ema"] = (ex.trail_bars, _bar_end_map(ex.trail_bars, k0, k_end))
        trail_ema_on = False
        cs = sig.info.get("close_stop")
        bc = sig.info.get("be_close")
        n = k_end - k0 + 1
        for i in range(n):
            r = k0 + i
            o = m.o[r] + sgn * hf[r]
            lo = m.l[r] + sgn * hf[r]
            hi = m.h[r] + sgn * hf[r]
            cl = m.c[r] + sgn * hf[r]
            if pending_exit:
                return i, o - side * slip, "exit_signal", booked, mfe, mae
            if pending_partial and booked is None:
                booked = side * (o - side * slip - entry)
                if ex.partial_be and side * (entry - cur_stop) > 0:
                    cur_stop, stop_kind = entry, "be_stop"
                pending_partial = False
            if ex.max_hold is not None and i >= ex.max_hold:
                return i, o - side * slip, "exit_signal", booked, mfe, mae
            fav = (hi - entry) if side > 0 else (entry - lo)
            adv = (entry - lo) if side > 0 else (hi - entry)
            stop_hit = (lo <= cur_stop) if side > 0 else (hi >= cur_stop)
            if stop_hit:
                fill = (min(cur_stop, o) - slip) if side > 0 else (max(cur_stop, o) + slip)
                return i, fill, stop_kind, booked, max(mfe, fav), max(mae, adv)
            if partial_level is not None and booked is None:
                p_hit = (hi >= partial_level) if side > 0 else (lo <= partial_level)
                if p_hit:
                    booked = side * (partial_level - entry)
                    if cur_target is not None and ((hi >= cur_target) if side > 0 else (lo <= cur_target)):
                        return i, cur_target, "target", booked, max(mfe, fav), max(mae, adv)
                    if ex.partial_be and side * (entry - cur_stop) > 0:
                        cur_stop, stop_kind = entry, "be_stop"
            if cur_target is not None and ((hi >= cur_target) if side > 0 else (lo <= cur_target)):
                px = cur_target if (side > 0 and o < cur_target) or (side < 0 and o > cur_target) else o
                return i, px, "target", booked, max(mfe, fav), max(mae, adv)
            mfe, mae = max(mfe, fav), max(mae, adv)
            best_px = max(best_px, hi) if side > 0 else min(best_px, lo)
            best_close = max(best_close, cl) if side > 0 else min(best_close, cl)
            # breakeven and lock after this row; they apply from the next row
            if be_level is not None and mfe >= be_level and side * (entry - cur_stop) > 0:
                cur_stop, stop_kind = entry, "be_stop"
            if ex.lock_at_r is not None and mfe >= ex.lock_at_r * risk:
                lk = entry + side * ex.lock_to_r * risk
                if side * (lk - cur_stop) > 0:
                    cur_stop, stop_kind = lk, "be_stop"
            if tr is not None and tr[0] in ("dist_r", "dist_frac"):
                start = tr[1] * (risk if tr[0] == "dist_r" else entry)
                dist = tr[2] * (risk if tr[0] == "dist_r" else entry)
                if mfe >= start:
                    ns = best_px - side * dist
                    if side * (ns - cur_stop) > 0:
                        cur_stop, stop_kind = ns, "trail_stop"
            if ex.trail_from_r is not None and mfe >= ex.trail_from_r * risk:
                trail_ema_on = True
            # bar-close conditions; their actions start at the next row
            for name, (bars, ends_at) in ends.items():
                j = ends_at.get(r)
                if j is None:
                    continue
                bclose = bars.c[j]
                if name == "xbars":
                    flags = ex.xlong if side > 0 else ex.xshort
                    if flags[j] and (ex.x_from_r is None or mfe >= ex.x_from_r * risk):
                        pending_exit = True
                elif name == "close_stop" and cs is not None:
                    if (bclose < cs) if side > 0 else (bclose > cs):
                        pending_exit = True
                elif name == "partial_flag" and booked is None:
                    flags = ex.partial_flag[1] if side > 0 else ex.partial_flag[2]
                    if flags[j]:
                        pending_partial = True
                elif name == "tgt_level":
                    lv = (ex.tgt_level[1] if side > 0 else ex.tgt_level[2])[j]
                    if np.isfinite(lv) and (lv - entry) * side > 0:
                        cur_target = float(lv)
                elif name == "be_close" and bc is not None:
                    if ((bclose > bc) if side > 0 else (bclose < bc)) and side * (entry - cur_stop) > 0:
                        cur_stop, stop_kind = entry, "be_stop"
                elif name == "trail":
                    if tr[0] == "chand":
                        a = tr[2][j]
                        if np.isfinite(a):
                            if len(tr) > 4 and tr[4] == "high":       # the best price (high for longs) since entry
                                bcl = best_px
                            else:                                     # the best close since entry
                                bcl = max(best_close, bclose) if side > 0 else min(best_close, bclose)
                            ns = bcl - side * tr[3] * a
                            if side * (ns - cur_stop) > 0:
                                cur_stop, stop_kind = float(ns), "trail_stop"
                    else:
                        lv = (tr[2] if side > 0 else tr[3])[j]
                        if np.isfinite(lv) and side * (lv - cur_stop) > 0:
                            cur_stop, stop_kind = float(lv), "trail_stop"
                elif name == "trail_ema" and trail_ema_on:
                    e = ex.trail_ema[j]
                    if (bclose < e) if side > 0 else (bclose > e):
                        pending_exit = True
        last = k0 + n - 1
        return n - 1, m.c[last] + sgn * hf[last] - side * slip, "time", booked, mfe, mae


def xengine(m, **kw) -> XEngine:
    return XEngine(m, **kw)


def run_book_x(engine: XEngine, signals, ex, limits: Limits, k_end_of_day, strategy: str, variant: str, reverse: bool = False):
    """One position at a time, taken in the order the orders FILL. (yt_engine.run_book takes signals in the order they
    were placed, so a pending order that fills late could block a newer order that filled first, and whether it did
    depended on data after that newer fill: a look-ahead once orders rest for several bars.) An order is placed only
    while flat (its signal row after the last exit); the first order to fill takes the position and every order still
    pending is cancelled; the daily limits and the setup groups (sig.info["group"]: one trade per group) apply in fill
    order. With market orders, which all fill on the row after their signal, this is exactly yt_engine.run_book.
    reverse=True lets an order placed on the row before an exit-signal exit fill at that exit's open (stop and reverse)."""
    trades, rejects = [], {}

    def rej(why):
        rejects[why] = rejects.get(why, 0) + 1

    cands = []
    for s in signals:
        k_end = k_end_of_day(s.day)
        if k_end is None or s.k >= k_end:
            rej("after_forced_exit")
            continue
        ke = k_end if s.info.get("k_last") is None else min(k_end, int(s.info["k_last"]))
        got, why = engine._enter(s, ke)
        if got is None:
            rej(why)
            continue
        cands.append((int(got[0]), int(s.k), int(s.side), s.setup, s, k_end))
    cands.sort(key=lambda c: c[:4])
    busy_until = -1
    day_state: dict = {}
    used: set = set()
    for _fill_k, _k, _side, _setup, s, k_end in cands:
        g = s.info.get("group")
        if g is not None and g in used:
            rej("group_used")
            continue
        if s.k <= busy_until:                    # placed while in a position, or cancelled when one opened
            rej("position_open")
            continue
        st = day_state.setdefault(s.day, {"n": 0, "stops": 0, "done": False, "last": None})
        if st["done"]:
            rej("day_closed")
            continue
        if st["n"] >= limits.max_per_day:
            rej("day_limit")
            continue
        if st["n"] > 0 and limits.second_only_after_stop and st["last"] != "stop":
            rej("needs_prior_stop")
            continue
        t, why = engine.trade(s, ex, k_end, strategy, variant)
        if t is None:
            rej(why)
            continue
        trades.append(t)
        # an exit signal fills at the open of exit_k: a reversal stamped on the row before may enter there
        busy_until = t.exit_k - 2 if (reverse and t.reason == "exit_signal") else t.exit_k
        st["n"] += 1
        st["last"] = t.reason
        if t.reason == "stop":
            st["stops"] += 1
            if st["stops"] >= limits.max_stops_per_day:
                st["done"] = True
        if t.reason == "target" and limits.stop_after_target:
            st["done"] = True
        if g is not None:
            used.add(g)
    return trades, rejects


def forced_exit_rows_x(m, clock: str, minute_of_day: int):
    """yt_engine.forced_exit_rows plus a 'utc' clock: per day, the last row at or before minute_of_day UTC (bitcoin's
    trading day is the UTC date, so its UTC clock only rises through a day)."""
    if clock != "utc":
        return forced_exit_rows(m, clock, minute_of_day)
    utc = (np.asarray(m.t, np.int64) // 60) % 1440
    out = np.full(m.n_days, -1, np.int64)
    for d in range(m.n_days):
        a, z = int(m.d0[d]), int(m.d1[d])
        idx = np.flatnonzero(utc[a:z] <= minute_of_day)
        if len(idx):
            out[d] = a + int(idx[-1])
    return lambda d: (None if out[d] < 0 else int(out[d]))


# ── multi-leg trades ──────────────────────────────────────────────────────────────────

def _leg(eng: YE.Engine, strategy, setup, sig_k, side, k_in, px_in, k_out, px_out, reason, unit, market_in, market_out):
    """One leg as a Trade. Market fills already carry the spread and slippage in px_in / px_out; costs are the
    market's commission per side."""
    m = eng.m
    pnl = side * (px_out - px_in)
    comm = 2 * eng.comm_abs + eng.comm_pct * (px_in + px_out)
    net = pnl - comm
    paid = eng.half[k_in] + eng.half[k_out] + (eng._slip(px_in) if market_in else 0.0) + (eng._slip(px_out) if market_out else 0.0)
    gross = pnl + paid
    d = int(m.day[k_in])
    fav = (m.h[k_in:k_out + 1].max() - px_in) if side > 0 else (px_in - m.l[k_in:k_out + 1].min())
    adv = (px_in - m.l[k_in:k_out + 1].min()) if side > 0 else (m.h[k_in:k_out + 1].max() - px_in)
    return Trade(m.name, strategy, "V0", setup, d, str(m.day_date(d)), m.split_of(d), bool(m.excluded[d]), side, sig_k,
                 k_in, k_out, float(px_in), float("nan"), float("nan"), float(px_out), reason, float(unit),
                 gross / unit, net / unit, (gross - net) / unit, k_out - k_in + 1, fav / unit, adv / unit)


def _buy_fill(eng, k, limit=None):
    """Ask-side fill at row k: a market buy at the open, or a buy limit (fills at min(limit, open))."""
    m, hf = eng.m, eng.half[k]
    if limit is None:
        return m.o[k] + hf + eng._slip(m.o[k])
    return min(limit, m.o[k] + hf)


def _sell_fill(eng, k, limit=None):
    m, hf = eng.m, eng.half[k]
    if limit is None:
        return m.o[k] - hf - eng._slip(m.o[k])
    return max(limit, m.o[k] - hf)


def _fill(eng, side, k, limit=None):
    return _buy_fill(eng, k, limit) if side > 0 else _sell_fill(eng, k, limit)


def _touch_buy(eng, k, level) -> bool:
    """Does the ask trade down to a buy limit at `level` in row k?"""
    return eng.m.l[k] + eng.half[k] <= level


def _touch_sell(eng, k, level) -> bool:
    return eng.m.h[k] - eng.half[k] >= level


def _touch_exit(eng, k, leg_side, level) -> bool:
    """Does a resting order that closes a position of `leg_side` at `level` fill in row k? (A long closes by selling.)"""
    return _touch_sell(eng, k, level) if leg_side > 0 else _touch_buy(eng, k, level)


def _market_at(eng, k, trade_side, level) -> float:
    """A market order sent when price is at `level` in row k: level plus the half spread and slippage against us."""
    return level + trade_side * (eng.half[k] + eng._slip(level))


def room_trades(eng: YE.Engine, signals: list, strategy: str, max_rows: int, k_last: int) -> list:
    """IT-02, the "room" trade. Per signal (one position at a time): lot 1 (a third) at the next open; lot 2 (two
    thirds) on a limit one room against it; before lot 2: stop 1.8 rooms from lot 1, target one room in its favour;
    after lot 2: stop 0.8 room beyond the average, target one room in its favour; a time stop of max_rows rows.
    sig.info["room"] is the room. Leg units are 2.4 and 1.2 rooms, so the account's 1% risk sizes the lots 1:2 and a
    full stop loses that 1%."""
    out = []
    busy = -1
    for s in signals:
        if s.k <= busy:
            continue
        room = float(s.info["room"])
        side = s.side
        k1 = s.k + 1
        if k1 > k_last or not room > 0:
            continue
        e1 = _fill(eng, side, k1)
        lot2_limit = e1 - side * room
        e2 = None
        k2 = None
        stop = e1 - side * 1.8 * room
        target = e1 + side * room
        end = min(k_last, k1 + max_rows)
        exit_k, exit_px, reason = None, None, None
        for k in range(k1, end + 1):
            filled_now = False
            if e2 is None and ((_touch_buy(eng, k, lot2_limit)) if side > 0 else (_touch_sell(eng, k, lot2_limit))):
                e2 = _fill(eng, side, k, lot2_limit)
                k2 = k
                filled_now = True
                avg = (e1 + 2 * e2) / 3
                stop = avg - side * 0.8 * room
                target = avg + side * room
            lo = eng.m.l[k] - (eng.half[k] if side > 0 else -eng.half[k])
            hi = eng.m.h[k] - (eng.half[k] if side > 0 else -eng.half[k])
            op = eng.m.o[k] - (eng.half[k] if side > 0 else -eng.half[k])
            if (lo <= stop) if side > 0 else (hi >= stop):
                exit_k, reason = k, "stop"
                exit_px = (min(stop, op) - eng._slip(stop)) if side > 0 else (max(stop, op) + eng._slip(stop))
                break
            # the row that filled lot 2 went against us; its high is not taken as reaching the new target
            if not filled_now and ((hi >= target) if side > 0 else (lo <= target)):
                exit_k, exit_px, reason = k, _fill(eng, -side, k, target), "target"   # a limit: a gap fills at the open
                break
        if exit_k is None:
            exit_k = end
            exit_px = (eng.m.c[end] - side * eng.half[end]) - side * eng._slip(eng.m.c[end])
            reason = "time"
        out.append(_leg(eng, strategy, "ROOM_LOT1", s.k, side, k1, e1, exit_k, exit_px, reason, 2.4 * room, True,
                        reason != "target"))
        if e2 is not None:
            out.append(_leg(eng, strategy, "ROOM_LOT2", s.k, side, k2, e2, exit_k, exit_px, reason, 1.2 * room, False,
                            reason != "target"))
        busy = exit_k
    return out


def ladder_trades(eng: YE.Engine, b4, direction: np.ndarray, strategy: str, risk_pct: float, since_k: int,
                  take_profit: float | None = None) -> list:
    """PR-12 / PR-13, the 4-hour Supertrend ladder. A phase starts at the open after a flip bar closes: 50% of the
    planned notional at once (the core), five 10% limits every 0.5% against that entry (the grid), and at every further
    1% in favour of the core entry a 10% opposite leg with a 1% target (the counter legs; opened only while the open
    trend legs are at least twice the open counter legs, counting the new one). No stops. Every open leg closes at the
    open after the opposite flip, where the next phase starts. With take_profit (PR-13: 0.10), every leg closes when
    price reaches that far from the core entry, and one fresh 10% trend leg opens there and runs to the flip.
    Legs are sized through their unit: risk_pct x entry / fraction, so the account's risk_pct buys that fraction of
    its equity in notional."""
    m = eng.m
    flips = [j for j in range(1, len(direction)) if direction[j] != direction[j - 1] and direction[j] != 0]
    out = []
    unit = lambda px, frac: risk_pct * px / frac  # noqa: E731
    for n_f, j in enumerate(flips):
        k0 = int(b4.i1[j]) + 1
        if k0 >= len(m.t) or k0 < since_k:
            continue
        side = int(direction[j])
        k_end = int(b4.i1[flips[n_f + 1]]) + 1 if n_f + 1 < len(flips) else len(m.t) - 1
        k_end = min(k_end, len(m.t) - 1)
        closes_at_flip = n_f + 1 < len(flips) and int(b4.i1[flips[n_f + 1]]) + 1 <= len(m.t) - 1
        e0 = _fill(eng, side, k0)
        legs = [{"kind": "core", "side": side, "k": k0, "px": e0, "frac": 0.5, "market": True, "tp": None}]
        grid = [e0 * (1 - side * 0.005 * i) for i in range(1, 6)]
        grid_done = [False] * 5
        counter_next = 1
        done_tp = False
        closed: list = []

        def close_all(k, px_fn, reason):
            for lg in legs:
                if lg.get("out") is None:
                    lg["out"] = (k, px_fn(lg), reason)

        for k in range(k0, k_end + 1):
            last_row = k == k_end
            if last_row and closes_at_flip:
                close_all(k, lambda lg: _fill(eng, -lg["side"], k), "flip")
                break
            if k == k0:
                continue
            # grid limits
            if not done_tp:
                for gi in range(5):
                    if not grid_done[gi] and ((_touch_buy(eng, k, grid[gi])) if side > 0 else (_touch_sell(eng, k, grid[gi]))):
                        grid_done[gi] = True
                        legs.append({"kind": "grid", "side": side, "k": k, "px": _fill(eng, side, k, grid[gi]), "frac": 0.1,
                                     "market": False, "tp": None})
            # counter legs' targets (resting limits: a gap through one fills at the open)
            for lg in legs:
                if lg["kind"] == "counter" and lg.get("out") is None and lg["k"] < k:
                    t = lg["tp"]
                    if _touch_exit(eng, k, lg["side"], t):
                        lg["out"] = (k, _fill(eng, -lg["side"], k, t), "target")
            # take profit of the whole ladder: trend legs on their resting order, counter legs bought back at market
            if take_profit is not None and not done_tp:
                tp_px = e0 * (1 + side * take_profit)
                if _touch_exit(eng, k, side, tp_px):
                    done_px = _fill(eng, -side, k, tp_px)      # where the trend legs' limit filled
                    for lg in legs:
                        if lg.get("out") is None:
                            if lg["side"] == side:
                                lg["out"] = (k, done_px, "target")
                            else:
                                lg["out"] = (k, _market_at(eng, k, -lg["side"], done_px), "tp_close")
                    done_tp = True
                    legs.append({"kind": "fresh", "side": side, "k": k, "px": _market_at(eng, k, side, done_px), "frac": 0.1,
                                 "market": True, "tp": None})
                    continue
            # new counter legs at every further 1% in favour
            if not done_tp:
                while True:
                    lvl = e0 * (1 + side * 0.01 * counter_next)
                    reached = (_touch_sell(eng, k, lvl)) if side > 0 else (_touch_buy(eng, k, lvl))
                    if not reached:
                        break
                    trend_units = sum(5 if lg["kind"] == "core" else 1 for lg in legs
                                      if lg["kind"] in ("core", "grid") and lg.get("out") is None)
                    counters = sum(1 for lg in legs if lg["kind"] == "counter" and lg.get("out") is None)
                    if trend_units >= 2 * (counters + 1):
                        px = _fill(eng, -side, k, lvl)
                        legs.append({"kind": "counter", "side": -side, "k": k, "px": px, "frac": 0.1, "market": False,
                                     "tp": px * (1 - side * 0.01)})
                    counter_next += 1
        for lg in legs:
            if lg.get("out") is None:
                kk = k_end
                px = m.c[kk] - lg["side"] * eng.half[kk]
                lg["out"] = (kk, px, "time")
            ko, po, why = lg["out"]
            setup = {"core": "LADDER_CORE", "grid": "LADDER_GRID", "counter": "LADDER_COUNTER", "fresh": "LADDER_FRESH"}[lg["kind"]]
            closed.append(_leg(eng, strategy, setup, int(b4.i1[j]), lg["side"], lg["k"], lg["px"], ko, po, why,
                               unit(lg["px"], lg["frac"]), lg["market"], why in ("flip", "time", "tp_close")))
        out += closed
    return sorted(out, key=lambda t: (t.entry_k, t.side))
