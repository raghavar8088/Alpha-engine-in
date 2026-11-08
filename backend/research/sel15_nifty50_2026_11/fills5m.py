"""One stop-entry fill model for the ORB replays (selected ORB 15/30, ORB in-play on 5-minute bars).

A leg is (direction of the rule, trigger, absolute stop or None). The first leg crossed fills;
a bar crossing two legs takes the one nearer the bar's open. Levels are placed from the RULE's
own fill. The mirror enters at the same moment and reference price, the other way, with its
target at the rule's stop level and its stop at the rule's target level. On the trigger bar only
the stop can fill, for both versions (the production convention). After it: a bar opening beyond
a level fills at the open, a bar touching both counts as the stop, targets are limits.
"""
from __future__ import annotations

from bisect import bisect_left


def at(dk: int, hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return dk * 86400 - 19800 + (h * 60 + m) * 60


class Reader:
    """Bars of one symbol at a time, so two years of 5-minute files never pile up in memory."""

    def __init__(self, read_file):
        self.read_file = read_file
        self.key = None
        self.cache = {}

    def day(self, sym: str, dk: int):
        if self.key != sym:
            self.key, self.cache = sym, {}
        for tf, step, need in (("5m", 300, 60), ("15m", 900, 24)):
            if tf not in self.cache:
                self.cache[tf] = self.read_file(sym, tf)
            b = self.cache[tf]
            i0, i1 = bisect_left(b.t, at(dk, "09:15")), bisect_left(b.t, at(dk, "15:30"))
            if i1 - i0 >= need:
                return tf, step, [(b.t[i], b.o[i], b.h[i], b.l[i], b.c[i]) for i in range(i0, i1)]
        return None, 0, []


def sim_entry(rows, step, legs, t_from, t_until, sq, sd, rr, mirror, bp, book, trigger_stop=True):
    """-> (trade tuple or None, note). `sd` = stop distance from the fill for legs without an
    absolute stop. `rr` = target in R (None: no target; the mirror needs one). `sq` = (time,
    "open"|"close"): the square-off. `book(entry_t, exit_t, side, fill, px, reason, market, bp)`.
    `trigger_stop=False` is the optimistic reading: nothing fills on the trigger bar."""
    k = next((i for i, r in enumerate(rows) if r[0] >= t_from), None)
    if k is None:
        return None, "no bars"
    cross = []
    while k < len(rows) and rows[k][0] < t_until:
        t, o, h, l, c = rows[k]
        cross = [x for x in legs if (x[0] > 0 and h >= x[1]) or (x[0] < 0 and l <= x[1])]
        if cross:
            break
        k += 1
    if not cross:
        return None, "no break"
    s0, trig, abs_stop = min(cross, key=lambda x: abs(o - x[1]))     # ties: the first leg
    entry = max(trig, o) if s0 > 0 else min(trig, o)
    f0 = entry * (1 + s0 * bp / 1e4)
    if abs_stop is not None:
        s_lvl = abs_stop
        d = s0 * (f0 - s_lvl)
        if d <= 0:
            return None, "fill beyond the stop"
    else:
        d = sd
        s_lvl = f0 - s0 * d
    t_lvl = f0 + s0 * rr * d if rr else None
    if mirror:
        sign = -s0
        fill = entry * (1 + sign * bp / 1e4)
        stop, target = t_lvl, s_lvl
        if sign * (target - fill) <= 0 or sign * (stop - fill) >= 0:
            return None, "mirror level on the wrong side"
    else:
        sign, fill, stop, target = s0, f0, s_lvl, t_lvl
    side = "BUY" if sign > 0 else "SELL"
    note = "both" if len(cross) > 1 else "one"
    if trigger_stop and ((sign > 0 and l <= stop) or (sign < 0 and h >= stop)):
        return book(t, t + step, side, fill, stop, "stoploss", True, bp), note + "/trigger-bar stop"
    t_sq, sq_kind = sq
    for j in range(k + 1, len(rows)):
        t2, o2, h2, l2, c2 = rows[j]
        if t2 >= t_sq:
            if sq_kind == "open":
                return book(t, t2, side, fill, o2, "eod", True, bp), note
            return book(t, t2 + step, side, fill, c2, "eod", True, bp), note
        if sign * (o2 - stop) <= 0:
            return book(t, t2, side, fill, o2, "stoploss", True, bp), note
        if target is not None and sign * (o2 - target) >= 0:
            return book(t, t2, side, fill, o2, "target", False, bp), note
        if (sign > 0 and l2 <= stop) or (sign < 0 and h2 >= stop):
            return book(t, t2 + step, side, fill, stop, "stoploss", True, bp), note
        if target is not None and ((sign > 0 and h2 >= target) or (sign < 0 and l2 <= target)):
            return book(t, t2 + step, side, fill, target, "target", False, bp), note
    t2, o2, h2, l2, c2 = rows[-1]
    return book(t, t2 + step, side, fill, c2, "eod", True, bp), note
