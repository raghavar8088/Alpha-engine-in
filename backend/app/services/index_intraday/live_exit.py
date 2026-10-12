"""Indian Index Intraday — checking an open position one minute at a time, by the backtest's rules.

The backtest (engine.walk_exit) sees a position's whole path at once. Live, the minutes arrive
one by one. `step` replays exactly the same rules incrementally — a test drives both over
thousands of random paths and requires identical exits (minute, price and reason):

* the entry minute: a market entry filled at its open (all of it counts, its open is not a gap);
  a stop entry filled inside it (an adverse stop touch counts, a target touch does not);
* a stop or target inside a minute fills at its level; a minute opening beyond one fills at
  that open; a minute touching both is a stop;
* a trailing stop trails the best price seen BEFORE the minute being tested;
* a signal exit, the time limit and the square-off fill at the open of their minute, with no
  level checks inside that minute.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Live:
    side: int
    entry_min: int
    entry: float                     # the raw entry price (index points)
    kind: str                        # market | stop
    stop: float | None
    target: float | None
    trail: float | None
    best: float                      # best price seen before `next_min`
    next_min: int                    # the next minute to check


def start(side: int, entry_min: int, entry: float, kind: str, stop, target, trail) -> Live:
    return Live(side, entry_min, entry, kind, stop, target, trail, entry, entry_min)


def step(p: Live, o, h, l, upto: int, square_off: int, sig_exit_min: int | None = None,
         hold_end: int | None = None) -> tuple[int, float, str] | None:
    """Walk the minutes [p.next_min, upto) — those now complete — and return the exit
    (minute, raw price, reason) if one happened, else None (p.next_min / p.best advanced).
    `upto` is the first minute NOT yet complete. Exits at the open of a minute (signal, time,
    square-off) need only that minute to have STARTED, so they are taken when m <= upto."""
    last = square_off
    if sig_exit_min is not None:
        last = min(last, sig_exit_min)
    if hold_end is not None:
        last = min(last, hold_end)
    m = p.next_min
    while m < min(upto, last):
        O = p.entry if m == p.entry_min else float(o[m])
        H, L = float(h[m]), float(l[m])
        if p.trail is not None:
            lvl = p.best - p.trail if p.side > 0 else p.best + p.trail
            if p.stop is not None:
                lvl = max(lvl, p.stop) if p.side > 0 else min(lvl, p.stop)
        else:
            lvl = p.stop
        if p.side > 0:
            s_hit = lvl is not None and L <= lvl
            t_hit = p.target is not None and H >= p.target
        else:
            s_hit = lvl is not None and H >= lvl
            t_hit = p.target is not None and L <= p.target
        if p.kind == "stop" and m == p.entry_min:
            t_hit = False
        if t_hit and not s_hit:
            better = O >= p.target if p.side > 0 else O <= p.target
            return m, (O if better else float(p.target)), "target"
        if s_hit:
            worse = O <= lvl if p.side > 0 else O >= lvl
            return m, (O if worse else float(lvl)), ("trail" if p.trail is not None else "stop")
        p.best = max(p.best, H) if p.side > 0 else min(p.best, L)
        m += 1
    p.next_min = m
    if m >= last and last <= upto:
        reason = "square_off" if last == square_off else ("signal" if last == sig_exit_min else "time")
        return last, float(o[last]), reason
    return None
