"""BB-15, Apple opening-range trap (video T_VlPXyqj0U), written from its pre-registered rule
(backend/research/booming_bulls_2026_11/specs/PREREGISTRATION.md). The study could not run it because the
Apple minute download was blocked, so it has NO backtest: paper trading is its first test. V0 only.

  Range:   09:30-09:45 New York. Skip the day if the range is 1% of the price or more.
  Trap:    price trades beyond the range, then a 3-minute candle closes back inside: trade the other way at
           its close. Signals until 11:30 New York.
  Stop:    beyond the trap candle if its range is at least 1.5 x the session's mean 3-minute range so far,
           otherwise beyond the last two candles; plus $0.02.
  Target:  2R. One trade a day. Exit at 15:55 New York.
"""

from __future__ import annotations

from research import BE, BM

Signal, Limits, Exits = BE.Signal, BE.Limits, BE.Exits
TF = 3
LIMITS = Limits(1)
EXIT_CLOCK = ("ny", 15 * 60 + 55)
OPEN, RANGE_END, LAST_SIGNAL_END = 9 * 60 + 30, 9 * 60 + 45, 11 * 60 + 30
EXITS = {"target_r": 2.0}


def signals(m, B) -> list:
    b = B[TF]
    out = []
    for d in range(m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        rng = [j for j in range(s0, s1) if OPEN <= b.ny0[j] < RANGE_END]
        if len(rng) < 5:                                    # the whole range must be known
            continue
        hi, lo = float(b.h[rng].max()), float(b.l[rng].min())
        if hi - lo >= 0.01 * float(b.c[rng[-1]]):
            continue
        beyond = 0                                          # +1 / -1: the side price last traded beyond
        for j in range(rng[-1] + 1, s1):
            if b.ny0[j] + TF > LAST_SIGNAL_END:
                break
            if b.h[j] > hi:
                beyond = 1
            if b.l[j] < lo:
                beyond = -1 if not b.h[j] > hi else (1 if b.c[j] >= b.o[j] else -1)
            if beyond and lo <= b.c[j] <= hi:
                side = -beyond
                mean_range = float((b.h[s0:j + 1] - b.l[s0:j + 1]).mean())
                big = (b.h[j] - b.l[j]) >= 1.5 * mean_range
                first = j if big else max(s0, j - 1)
                ext_hi, ext_lo = float(b.h[first:j + 1].max()), float(b.l[first:j + 1].min())
                stop = ext_hi + 0.02 if side < 0 else ext_lo - 0.02
                out.append(Signal(d, int(b.i1[j]), side, stop, "AAPL_OR_TRAP"))
                break
    return out


def make_bars(m) -> dict:
    return {TF: BM.bars(m, TF)}
