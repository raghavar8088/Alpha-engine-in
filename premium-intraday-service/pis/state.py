"""Today's five-minute bars as they arrive, and the running quantities every screen reads (VWAP, opening range,
relative volume). A bar is (t, o, h, l, c, v) with t = its START (09:15 = bar 0). Only CLOSED bars ever enter.

`complete(sym, k)` is the guard every decision uses: a stock counts at bar k only if it has every bar 0..k. A stock
with a hole (a stream outage) is reported as missing, never filled in."""
from __future__ import annotations

from .timeutil import bar_index


class SymDay:
    __slots__ = ("bars", "ks", "cumv", "cumpv", "hi", "lo", "arrived")

    def __init__(self):
        self.bars = []        # in k order
        self.ks = []          # bar index of each bar
        self.cumv = []        # cumulative volume after each bar
        self.cumpv = []       # cumulative typical price x volume
        self.hi = []          # running high
        self.lo = []          # running low
        self.arrived = []     # when the desk received each bar (epoch; replay: the bar's close)


class DayState:
    def __init__(self, day):
        self.day = day
        self.s: dict[str, SymDay] = {}
        self.opens: dict[str, float] = {}       # 09:15 open (from the first bar, or a live quote at 09:15)
        self.open_src: dict[str, str] = {}

    # ── input ────────────────────────────────────────────────────────────────────
    def add(self, sym: str, bar, arrived: float | None = None) -> bool:
        t, o, h, l, c, v = bar[:6]
        k = bar_index(t)
        if k < 0 or k >= 75 or not (l > 0 and h >= l):
            return False
        sd = self.s.get(sym)
        if sd is None:
            sd = self.s[sym] = SymDay()
        if sd.ks and k <= sd.ks[-1]:
            return False                         # duplicate or out of order: the first copy stands
        tp = (h + l + c) / 3.0
        pv = (sd.cumpv[-1] if sd.cumpv else 0.0) + tp * v
        cv = (sd.cumv[-1] if sd.cumv else 0) + int(v)
        sd.bars.append((int(t), float(o), float(h), float(l), float(c), int(v)))
        sd.ks.append(k)
        sd.cumv.append(cv)
        sd.cumpv.append(pv)
        sd.hi.append(max(h, sd.hi[-1]) if sd.hi else h)
        sd.lo.append(min(l, sd.lo[-1]) if sd.lo else l)
        sd.arrived.append(float(arrived if arrived is not None else t + 300))
        if k == 0 and sym not in self.opens:
            self.opens[sym] = float(o)
            self.open_src[sym] = "first bar"
        return True

    def set_open(self, sym: str, price: float, src: str = "quote") -> None:
        if price and price > 0 and sym not in self.opens:
            self.opens[sym] = float(price)
            self.open_src[sym] = src

    # ── reads at bar k (all bars 0..k closed) ───────────────────────────────────
    def complete(self, sym: str, k: int) -> bool:
        sd = self.s.get(sym)
        return bool(sd) and len(sd.ks) > k and sd.ks[k] == k

    def bar(self, sym: str, k: int):
        sd = self.s.get(sym)
        if not sd or len(sd.ks) <= k or sd.ks[k] != k:
            # holes: find by search
            if sd and k in sd.ks:
                return sd.bars[sd.ks.index(k)]
            return None
        return sd.bars[k]

    def last_k(self, sym: str) -> int:
        sd = self.s.get(sym)
        return sd.ks[-1] if sd and sd.ks else -1

    def close(self, sym: str, k: int) -> float | None:
        b = self.bar(sym, k)
        return b[4] if b else None

    def open(self, sym: str) -> float | None:
        return self.opens.get(sym)

    def vwap(self, sym: str, k: int) -> float | None:
        if not self.complete(sym, k):
            return None
        sd = self.s[sym]
        v = sd.cumv[k]
        return sd.cumpv[k] / v if v > 0 else sd.bars[k][4]

    def cumvol(self, sym: str, k: int) -> int | None:
        return self.s[sym].cumv[k] if self.complete(sym, k) else None

    def high(self, sym: str, k: int) -> float | None:
        return self.s[sym].hi[k] if self.complete(sym, k) else None

    def low(self, sym: str, k: int) -> float | None:
        return self.s[sym].lo[k] if self.complete(sym, k) else None

    def or15(self, sym: str):
        """(high, low, open, close) of 09:15-09:30, once bars 0-2 are all in."""
        if not self.complete(sym, 2):
            return None
        b = self.s[sym].bars
        return (max(b[0][2], b[1][2], b[2][2]), min(b[0][3], b[1][3], b[2][3]), b[0][1], b[2][4])

    def ret_open(self, sym: str, k: int) -> float | None:
        o, c = self.open(sym), self.close(sym, k)
        return (c / o - 1) * 100 if o and c and self.complete(sym, k) else None

    def ret_pc(self, sym: str, k: int, prev_close: float | None) -> float | None:
        c = self.close(sym, k)
        return (c / prev_close - 1) * 100 if prev_close and c and self.complete(sym, k) else None

    def rvol(self, sym: str, k: int, base: dict) -> float | None:
        cv = self.cumvol(sym, k)
        b = (base or {}).get(k)
        return cv / b if cv is not None and b else None

    def bars_upto(self, sym: str, k: int) -> list:
        sd = self.s.get(sym)
        if not sd:
            return []
        return [b for kk, b in zip(sd.ks, sd.bars) if kk <= k]
