"""Booming Bulls' "Sniper Headshot Entry" (jvzd7UPlb5Y, 1 Mar 2025) as exact rules on bitcoin (Delta Exchange BTCUSD),
with four one-change upgrades. backend/research/sniper_headshot_2026_11/RULES.md is the readable form, saying which
rules the video states (E) and which had to be assumed (A); this file is the exact form. Not backtested: paper trading
on Delta's live prices is their first test.

Run by the YouTube study's fill engine like the Crypto-playlist books: signals use completed 5-minute bars, are stamped
with the bar's last minute row, and fill at the next minute's open plus half the spread and slippage.

  SH-00  the video: in a 1-hour uptrend, a double bottom on 5-minute bars is swept, price reaches a demand zone below
         it, and a strong green candle there is the first entry; stop under half its body, target just short of the
         range high; a second entry when price retests the swept level from above. Shorts mirror it.
  SH-01  entry on the first close back above the swept level, stop under the sweep's low
  SH-02  only when Delta's takers sold into the sweep and bought the reversal candle (the live trade feed)
  SH-03  only when the last 1-hour close is on the trade's side of the 1-hour 50-EMA
  SH-04  built to pay Delta's costs: the same pattern on 1-hour bars (trend from 4-hour structure), the video's default
         stop under the reversal candle, and no trade whose round-trip cost is more than 40% of its risk. On 5- and
         15-minute bitcoin candles every version's stop is so close that Delta's taker fees cost 1.2-5.6R a trade.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from research import BM, CS, YE
import yt_ind as I  # noqa: E402  (on the path through research.py)

SOURCE = "sniper_headshot"
VIDEO = "jvzd7UPlb5Y"
TF, HTF = 5, 60             # entries on 5-minute bars (E: 5 or 15 minutes, not 1); trend on 1-hour structure (A)
PIV = 2                     # a swing low is the lowest bar of 2 either side, known 2 bars later (A)
EQ_ATR = 0.25               # two swing lows within 0.25 ATR(14) of each other are a double bottom (A)
BASE_MIN = 360              # both bottoms within 6 hours (A)
MIN_GAP = 3                 # at least 3 bars apart (A)
SWEEP_MIN = 180             # the sweep within 3 hours of the base being known (A)
ZONE_MIN = 1440             # the demand zone comes from a swing low of the last 24 hours (A)
ZONE_MIN_W = 0.10           # a zone at least 0.1 ATR thick (A)
ZONE_MAX_DEPTH = 5.0        # and at most 5 ATR beyond the level (A)
TOUCH_MIN = 60              # the zone reached within 1 hour of the sweep (A)
TRIGGER_MIN = 30            # the reversal candle within 30 minutes of the touch (A)
RECLAIM_MIN = 60            # SH-01: the close back across the level within 1 hour of the touch (A)
FAIL_ATR = 0.5              # a close 0.5 ATR through the far side of the zone ends the setup (A)
BIG_BODY = 0.5              # a "big" reversal candle: body at least 0.5 ATR (A) ...
PIN_RANGE = 1.0             # ... or a pin bar at least 1 ATR long (A)
STOP_BODY = 0.4             # stop at 40% of the body from its open: "below 50% of the body, a little lower" (E, A)
SWEEP_STOP_ATR = 0.1        # SH-01: stop 0.1 ATR beyond the sweep's extreme (A)
LOW_STOP_ATR = 0.1          # SH-04: stop 0.1 ATR under the reversal candle's low, the video's first choice (E, A)
COST_MULT = 2.5             # SH-04: risk at least 2.5x the round-trip cost, so costs are at most 40% of R (A)
TARGET_FRAC = 0.93          # target 93% of the way to the range high: "keep it a little below" (E; 2.6 of 2.8)
MIN_RR = 1.5                # skipped when the target is less than 1.5x the risk away (A: "small stop, big target")
MAX_PER_DAY = 3             # "it will be 3 times in a day" (E)
RETEST_ATR = 0.15           # the second entry: a retest comes within 0.15 ATR of the level (A)
E2_STOP_ATR = 0.1           # its stop 0.1 ATR beyond the retest candle (E: "the new level"; A: the distance)
E2_MIN_RR = 1.0             # and its target at least 1x its risk away (A)
FLOW_SHARE = 0.55           # SH-02: takers bought at least 55% of the reversal candle's volume (A)
EMA_N = 50                  # SH-03: the 1-hour 50-EMA (A)

LIMITS = YE.Limits(MAX_PER_DAY, stop_after_target=False, second_only_after_stop=False, max_stops_per_day=99)
EXIT_CLOCK = CS.BTC_X       # out by 23:55 UTC, the end of bitcoin's (UTC) day, like the other bitcoin books


@dataclass(frozen=True)
class Version:
    sid: str
    name: str
    tf: int = TF
    htf: int = HTF              # the timeframe whose swing structure gives the trend
    scale: int = 0              # minutes a bar for the time windows (0: the version's own timeframe)
    entry: str = "candle"       # "candle": a strong reversal candle at the zone; "reclaim": the close back across the level
    stop: str = "body"          # "body": under half the candle's body; "low": under the candle; "sweep": under the sweep
    flow: bool = False
    ema: bool = False
    cost_mult: float | None = None
    be_r: float | None = None

    def bars(self, minutes: int) -> int:
        return max(1, minutes // (self.scale or self.tf))


VERSIONS = {v.sid: v for v in (
    Version("SH-00", "Sniper headshot entry (the video's rules)"),
    Version("SH-01", "Upgrade: enter on the reclaim of the swept level", entry="reclaim", stop="sweep"),
    Version("SH-02", "Upgrade: Delta order-flow confirmation", flow=True),
    Version("SH-03", "Upgrade: 1-hour 50-EMA trend filter", ema=True),
    Version("SH-04", "Upgrade: built to pay Delta's costs (1-hour bars, stop under the candle)", tf=60, htf=240, scale=TF,
            stop="low", cost_mult=COST_MULT),
)}


def exits(sid: str):
    return YE.Exits(target_r=None, be_at_r=VERSIONS[sid].be_r)


@dataclass
class Setup:
    side: int                   # +1: a swept double bottom, buy; -1: a swept double top, sell
    level: float                # the double bottom's low (top's high)
    first: int                  # bar of the first bottom
    armed: int                  # bar at which the base is known
    ref: float                  # the range high (low) above (below) the base: the target's reference
    zlo: float                  # the demand (supply) zone
    zhi: float
    state: str = "sweep"        # sweep -> touch -> trigger -> done / void
    sweep: int = -1
    touch: int = -1
    extreme: float = float("nan")


class Ctx:
    """Per-market pieces computed once: 5-minute ATR and pivots, 1-hour trend and EMA, and taker flow per 5-minute bar."""

    def __init__(self, m, B, cache, tf, htf):
        b, bh = B[tf], B[htf]
        self.b, self.bh = b, bh
        self.atr = I.atr(b, 14)
        self.ph, self.pl = I.fractals(b, PIV)
        self.trend = CS.struct_cached(B, htf, cache)[0]           # +1 higher high and higher low, -1 the reverse, 0
        self.ema = BM.ema(np.asarray(bh.c, float), EMA_N)
        self.jh = np.searchsorted(bh.i1, b.i1, "right") - 1         # the last 1-hour bar complete at each 5-minute close
        bv, va = getattr(m, "bv", None), getattr(m, "vol_all", None)
        if bv is not None and va is not None and len(bv) == len(m.t):
            self.buy = np.add.reduceat(np.asarray(bv, float), b.i0)  # NaN where a minute was not recorded whole
            self.vol = np.add.reduceat(np.asarray(va, float), b.i0)
        else:
            self.buy = self.vol = None
        cost = getattr(m, "cost", None)
        self.pct = (getattr(cost, "pct_comm", 0.0) + getattr(cost, "pct_slip", 0.0)) if cost is not None else 0.0
        self.half = float(np.nanmedian(m.half)) if len(m.half) else 0.0

    def rt_cost(self, price: float) -> float:
        """A round trip at market: fees and slippage both ways plus the spread."""
        return 2 * self.pct * price + 2 * self.half


def ctx(m, B, cache, tf, htf=HTF) -> Ctx:
    if ("sh_ctx", tf, htf) not in cache:
        cache[("sh_ctx", tf, htf)] = Ctx(m, B, cache, tf, htf)
    return cache[("sh_ctx", tf, htf)]


def _price(b, q, side):
    return b.l[q] if side > 0 else b.h[q]


def _zone(c: Ctx, v: Version, pivots: list, first: int, j: int, level: float, side: int):
    """The nearest earlier swing beyond the level, drawn from its wick to its body (the video's "pull the wick or body
    forward"). None when there is none within reach."""
    b, a = c.b, c.atr[j]
    best = None
    for p in pivots:
        if p >= first or p < j - v.bars(ZONE_MIN):
            continue
        if side > 0:
            lo = b.l[p]
            hi = max(min(b.o[p], b.c[p]), lo + ZONE_MIN_W * a)
            if hi >= level or lo < level - ZONE_MAX_DEPTH * a:
                continue
            if best is None or hi > best[1]:
                best = (lo, hi)
        else:
            hi = b.h[p]
            lo = min(max(b.o[p], b.c[p]), hi - ZONE_MIN_W * a)
            if lo <= level or hi > level + ZONE_MAX_DEPTH * a:
                continue
            if best is None or lo < best[0]:
                best = (lo, hi)
    return best


def _base(c: Ctx, v: Version, pivots: list, q: int, j: int, side: int) -> Setup | None:
    """A double bottom (top) completed by the swing at bar q, known at bar j, inside a 1-hour trend the same way."""
    b = c.b
    tol = EQ_ATR * c.atr[q]
    price = _price(b, q, side)
    match = [p for p in pivots if q - v.bars(BASE_MIN) <= p <= q - MIN_GAP and abs(_price(b, p, side) - price) <= tol]
    if not match:
        return None
    first = match[-1]
    jh = c.jh[j]
    if jh < 0 or c.trend[jh] != side:
        return None
    level = min(b.l[first], b.l[q]) if side > 0 else max(b.h[first], b.h[q])
    # the two bottoms are the floor of the range: nothing between them went lower (or higher, for a top)
    if (b.l[first:q + 1].min() < level - tol) if side > 0 else (b.h[first:q + 1].max() > level + tol):
        return None
    ref = float(b.h[first:j + 1].max()) if side > 0 else float(b.l[first:j + 1].min())
    zone = _zone(c, v, pivots, first, j, level, side)
    if zone is None:
        return None
    return Setup(side, float(level), first, j, ref, float(zone[0]), float(zone[1]))


def _flow_ok(c: Ctx, st: Setup, j: int) -> bool:
    """SH-02: takers sold into the sweep (from the sweep bar to the bar before the reversal) and bought the reversal
    candle (the mirror for shorts). Any minute the live recorder did not see whole makes it unknown: no trade."""
    if c.buy is None or j <= st.sweep:
        return False
    buy, vol = c.buy[st.sweep:j].sum(), c.vol[st.sweep:j].sum()
    bj, vj = c.buy[j], c.vol[j]
    if not (np.isfinite(buy) and np.isfinite(vol) and np.isfinite(bj) and np.isfinite(vj) and vol > 0 and vj > 0):
        return False
    leg = 2 * buy - vol                      # taker buys minus taker sells over the sweep
    share = bj / vj
    return (leg < 0 and share >= FLOW_SHARE) if st.side > 0 else (leg > 0 and share <= 1 - FLOW_SHARE)


def _ema_ok(c: Ctx, j: int, side: int) -> bool:
    jh = c.jh[j]
    return jh >= EMA_N - 1 and (c.bh.c[jh] - c.ema[jh]) * side > 0


def _trigger(c: Ctx, v: Version, st: Setup, j: int):
    b, atr, s = c.b, c.atr[j], st.side
    if v.entry == "reclaim":
        if (b.c[j] - st.level) * s <= 0:
            return None
        stop, setup = st.extreme - s * SWEEP_STOP_ATR * atr, "Reclaim of the swept level"
    else:
        r, bd = b.h[j] - b.l[j], abs(b.c[j] - b.o[j])
        if s > 0:
            ok = b.c[j] > b.o[j] and b.c[j] > st.zhi and (bd >= BIG_BODY * atr or (CS.pin_bull(b, j) and r >= PIN_RANGE * atr))
        else:
            ok = b.c[j] < b.o[j] and b.c[j] < st.zlo and (bd >= BIG_BODY * atr or (CS.pin_bear(b, j) and r >= PIN_RANGE * atr))
        if not ok or (v.flow and not _flow_ok(c, st, j)) or (v.ema and not _ema_ok(c, j, s)):
            return None
        if v.stop == "low":
            stop = (b.l[j] - LOW_STOP_ATR * atr) if s > 0 else (b.h[j] + LOW_STOP_ATR * atr)
        else:
            stop = b.o[j] + STOP_BODY * (b.c[j] - b.o[j])
        setup = "Sweep, zone, reversal candle"
    e = b.c[j]
    risk, room = (e - stop) * s, (st.ref - e) * s
    st.state = "void"                        # one decision per setup: taken now, or never
    if risk <= 0 or room <= 0 or TARGET_FRAC * room < MIN_RR * risk:
        return None
    if v.cost_mult is not None and risk < v.cost_mult * c.rt_cost(e):
        return None
    st.state = "done"
    return CS.sig(b, j, s, stop, setup, target_px=float(e + s * TARGET_FRAC * room),
                  info={"level": st.level, "ref": st.ref, "bar": j, "zone": [st.zlo, st.zhi], "sweep_extreme": st.extreme,
                        "sweep_bar": st.sweep, "atr": float(atr)})


def _step(c: Ctx, v: Version, st: Setup, j: int):
    b, s = c.b, st.side
    if st.state == "sweep":
        if (b.c[j] - st.ref) * s > 0 or j - st.armed > v.bars(SWEEP_MIN):    # a breakout or too late: the video skips it
            st.state = "void"
            return None
        if not ((b.l[j] < st.level) if s > 0 else (b.h[j] > st.level)):
            st.ref = max(st.ref, b.h[j]) if s > 0 else min(st.ref, b.l[j])
            return None
        st.state, st.sweep, st.extreme = "touch", j, float(_price(b, j, s))
    else:
        st.extreme = float(min(st.extreme, b.l[j]) if s > 0 else max(st.extreme, b.h[j]))
    if st.state == "touch":
        if (b.l[j] <= st.zhi) if s > 0 else (b.h[j] >= st.zlo):
            st.state, st.touch = "trigger", j
        else:
            if j - st.sweep >= v.bars(TOUCH_MIN) - 1 or (b.c[j] - st.ref) * s > 0:
                st.state = "void"
            return None
    if (b.c[j] < st.zlo - FAIL_ATR * c.atr[j]) if s > 0 else (b.c[j] > st.zhi + FAIL_ATR * c.atr[j]):
        st.state = "void"
        return None
    out = _trigger(c, v, st, j)
    if out is None and st.state == "trigger" and j - st.touch >= v.bars(TRIGGER_MIN if v.entry == "candle" else RECLAIM_MIN) - 1:
        st.state = "void"
    return out


def signals(sid: str, m, B: dict, cache: dict) -> list:
    """First entries (E1) of one version, in time order: at most one a bar a side."""
    key = ("sh_sig", sid)
    if key in cache:
        return cache[key]
    v = VERSIONS[sid]
    c = ctx(m, B, cache, v.tf, v.htf)
    b = c.b
    lows: list = []
    highs: list = []
    active: list = []
    out = []
    for j in range(len(b.c)):
        q = j - PIV
        if q >= 0 and np.isfinite(c.atr[q]) and np.isfinite(c.atr[j]):
            for side, flags, pivots in ((1, c.pl, lows), (-1, c.ph, highs)):
                if flags[q]:
                    st = _base(c, v, pivots, q, j, side)
                    pivots.append(q)
                    if st is not None:      # the newest base replaces an older one still waiting for its sweep
                        active = [a for a in active if not (a.side == side and a.state == "sweep")] + [st]
        fired = set()
        keep = []
        for st in active:
            if j > st.armed:
                sg = _step(c, v, st, j)
                if sg is not None and st.side not in fired:
                    out.append(sg)
                    fired.add(st.side)
            if st.state not in ("done", "void"):
                keep.append(st)
        active = keep[-6:]
    cache[key] = out
    return out


def pyramid(sid: str, m, B: dict, cache: dict, first, sig) -> object | None:
    """The second entry (E2) of a first entry that is still open: after a close back across the swept level, the first
    candle that retests the level and closes away from it, in the trade's direction (E: "retests and goes up"). Its stop
    goes beyond that candle, its target is the first entry's."""
    v = VERSIONS[sid]
    c = ctx(m, B, cache, v.tf, v.htf)
    b, atr = c.b, c.atr
    side, level, g = sig.side, sig.info["level"], sig.info["bar"]
    target = sig.target_px
    reclaimed = (b.c[g] - level) * side > 0
    for r in range(g + 1, len(b.c)):
        if b.i1[r] + 1 >= first.exit_k or b.day[r] != b.day[g]:
            return None
        if not reclaimed:
            reclaimed = (b.c[r] - level) * side > 0
            continue
        near = (b.l[r] <= level + RETEST_ATR * atr[r]) if side > 0 else (b.h[r] >= level - RETEST_ATR * atr[r])
        away = (b.c[r] > b.o[r] and b.c[r] > level) if side > 0 else (b.c[r] < b.o[r] and b.c[r] < level)
        if not (near and away):
            continue
        stop = (b.l[r] - E2_STOP_ATR * atr[r]) if side > 0 else (b.h[r] + E2_STOP_ATR * atr[r])
        risk, room = (b.c[r] - stop) * side, (target - b.c[r]) * side
        if risk <= 0 or room < E2_MIN_RR * risk:
            return None
        return CS.sig(b, r, side, stop, "Second entry on the retest", target_px=float(target), info={"level": level, "bar": r})
    return None
