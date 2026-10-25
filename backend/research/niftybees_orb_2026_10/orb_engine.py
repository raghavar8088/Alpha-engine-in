"""NIFTYBEES opening-range breakout: the rule book and the simulator.

THE RULES (fixed before any result was seen; see README.md)
  Opening range   high and low of the 09:15, 09:20 and 09:25 five-minute candles (09:15:00-09:29:59),
                  from NIFTYBEES prints (opening prints cleaned, orb_data.py rule 4).
  Entry           price crossing: from 09:30 a buy-stop rests one tick (Rs0.01) above the range high and
                  a sell-stop one tick below the range low, one cancelling the other. A stop that
                  triggers fills at the trigger price, or at the candle's open if the candle opens beyond
                  it, plus slippage. Orders still unfilled at 15:00 are cancelled.
  Stop-loss       the other side of the range: long at the range low, short at the range high; a stop
                  triggers when price touches it, and fills at that price (or a worse open) less slippage.
  Target          2 x the distance from the actual fill to the stop, on the far side; a resting limit
                  order, so no slippage, but it counts as filled only when price trades one tick through it.
  Trades a day    one. No re-entry and no reversal once a trade has been taken.
  End of day      anything still open is sold / bought back at 15:15 IST, the close of the 15:10-15:15
                  candle, less slippage.
  Size            Rs10,00,000 of NIFTYBEES a trade (whole units), on a Rs10,00,000 account: no leverage,
                  no compounding.
  Costs           Angel One's intraday rate card from the app's own model (app.services.angel_fees):
                  brokerage min(Rs20, 0.25%) an order, STT 0.025% on the sell, NSE 0.00297%, SEBI and IPFT
                  0.0001% each, stamp duty 0.003% on the buy, GST 18% on the services.
  Slippage        1 bp of price a side on every market or stop fill (the entry, a stop-loss, the 15:15
                  exit), rounded to the next whole tick against the trade: about Rs0.03 at Rs270.

INSIDE A CANDLE the order of the high and the low is unknown. Each candle is walked both ways, open ->
high -> low -> close and open -> low -> high -> close, and the way that leaves the account worse at the
candle's close is the one used ("worst"). So a candle that touches both the stop and the target counts as
a stop-loss; an entry candle that also reaches the stop counts as stopped; a candle that triggers both
entries counts as whichever loses more. `intrabar="best"` takes the other way, as a bound, and walking the
1-minute candles inside each 5-minute candle (`bars=1`) shows what actually happened, to the minute.

All prices are integer paise inside the simulator, so tick comparisons are exact.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
for _p in (_ROOT / "shared", _ROOT / "backend"):          # the repo's own packages first
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

from app.services import angel_fees as AF  # noqa: E402

OPEN_MIN = 9 * 60 + 15


@dataclass(frozen=True)
class Config:
    name: str = "primary"
    entry: str = "stop"            # "stop" (price crossing) | "close" (a 5-minute close beyond the range,
    #                                filled at the next candle's open)
    max_trades: int = 1
    reverse: bool = False          # after a stop-loss the opposite side's order stays live (max_trades 2)
    first_entry_min: int = 15      # 09:30, minutes after 09:15
    last_entry_min: int = 345      # 15:00: no entry from this minute on
    exit_min: int = 360            # 15:15: the close of the candle ending here is the end-of-day exit
    rr: float = 2.0
    tick: int = 1                  # paise
    slip_bp: float = 1.0
    target_fill: str = "through"   # "through" | "touch"
    intrabar: str = "worst"        # "worst" | "best"
    sizing: str = "notional"       # "notional" | "risk"
    notional: float = 1_000_000.0
    capital: float = 1_000_000.0
    risk: float = 10_000.0         # rupees lost at the stop before costs (sizing="risk")
    max_lev: float = 5.0           # notional cap for sizing="risk", x capital (Angel's intraday margin)
    costs: bool = True
    orb: str = "clean"             # "clean" (0.2% band) | "clean05" | "raw"
    bars: int = 5                  # walk 5-minute candles, or 1-minute candles


def fees(entry: float, exit_: float, qty: int, side: int) -> float:
    """Angel One intraday round trip, identical to app.services.angel_fees.round_trip (orb_verify.py
    checks it), inlined because the simulator calls it for every candle it walks both ways."""
    if qty <= 0:
        return 0.0
    buy_t = (entry if side > 0 else exit_) * qty
    sell_t = (exit_ if side > 0 else entry) * qty
    t = buy_t + sell_t
    brk = min(AF.BROKERAGE_CAP, buy_t * AF.BROKERAGE_PCT["INTRADAY"]) + \
        min(AF.BROKERAGE_CAP, sell_t * AF.BROKERAGE_PCT["INTRADAY"])
    stt = sell_t * AF.STT_SELL["INTRADAY"] + buy_t * AF.STT_BUY["INTRADAY"]
    exch, sebi, ipft = t * AF.EXCHANGE_TXN, t * AF.SEBI_TURNOVER, t * AF.NSE_IPFT
    stamp = buy_t * AF.STAMP_DUTY_BUY["INTRADAY"]
    gst = AF.GST_RATE * (brk + exch + sebi + ipft)
    return round(brk + stt + exch + sebi + ipft + stamp + gst, 2)


@dataclass
class Trade:
    date: str
    side: int
    entry_bar: int                 # minute (after 09:15) the entry candle starts
    entry_level: int               # trigger / signal price, paise
    entry_fill: int
    stop: int
    target: int
    qty: int
    exit_bar: int = -1
    exit_reason: str = ""
    exit_level: int = 0
    exit_fill: int = 0
    gross: float = 0.0
    fees: float = 0.0
    net: float = 0.0
    slippage: float = 0.0          # rupees given up to slippage, both legs
    ambiguous: bool = False        # the order of the high and the low inside a candle decided its result

    @property
    def risk_rs(self) -> float:
        return self.qty * abs(self.entry_fill - self.stop) / 100.0


@dataclass
class State:
    pos: int = 0
    trade: Trade | None = None
    trades: int = 0
    used: set = field(default_factory=set)      # sides already traded today
    last_exit: str = ""                        # "stop" | "target" | "eod"
    closed: list = field(default_factory=list)  # trades closed in the candle being walked

    def copy(self) -> "State":
        s = State(self.pos, replace(self.trade) if self.trade else None, self.trades, set(self.used),
                  self.last_exit, [])
        return s


class Day:
    """One session: the candles to walk and the range."""

    def __init__(self, date: str, o, h, l, c, start, length: int, orh: int, orl: int, close_signal=None):
        self.date, self.o, self.h, self.l, self.c = date, o, h, l, c
        self.start, self.length = start, length
        self.orh, self.orl = orh, orl
        self.close_signal = close_signal          # (minute of the entry candle, side) for entry="close"


def _ceil_tick(x: float, tick: int) -> int:
    return int(math.ceil(x / tick - 1e-9)) * tick


def _floor_tick(x: float, tick: int) -> int:
    return int(math.floor(x / tick + 1e-9)) * tick


class Sim:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.slip = cfg.slip_bp / 1e4

    # fills -----------------------------------------------------------------------------------
    def buy_fill(self, p: int) -> int:
        return _ceil_tick(p * (1 + self.slip), self.cfg.tick)

    def sell_fill(self, p: int) -> int:
        return _floor_tick(p * (1 - self.slip), self.cfg.tick)

    def size(self, fill: int, stop: int) -> int:
        cfg = self.cfg
        px = fill / 100.0
        if cfg.sizing == "risk":
            r = abs(fill - stop) / 100.0
            q = int(cfg.risk // r) if r > 0 else 0
            return max(0, min(q, int(cfg.max_lev * cfg.capital // px)))
        return int(cfg.notional // px)

    def _fees(self, t: Trade, exit_fill: int) -> float:
        return fees(t.entry_fill / 100.0, exit_fill / 100.0, t.qty, t.side) if self.cfg.costs else 0.0

    # events ------------------------------------------------------------------------------------
    def enter(self, s: State, day: Day, side: int, level: int, at_open_price: int | None, bar: int) -> bool:
        cfg = self.cfg
        px = at_open_price if at_open_price is not None else level
        fill = self.buy_fill(px) if side > 0 else self.sell_fill(px)
        stop = day.orl if side > 0 else day.orh
        r = (fill - stop) * side
        if r <= 0:                      # a close-mode entry that opened beyond its own stop: no trade
            s.used.add(side)
            s.trades += 1
            return False
        tgt = fill + side * _ceil_tick(cfg.rr * r, cfg.tick)
        qty = self.size(fill, stop)
        if qty <= 0:
            return False
        s.trade = Trade(day.date, side, bar, level, fill, stop, tgt, qty)
        s.trade.slippage = qty * abs(fill - px) / 100.0
        s.pos = side
        s.trades += 1
        s.used.add(side)
        return True

    def exit(self, s: State, reason: str, level: int, fill: int, bar: int, ref: int | None = None) -> None:
        """`level` is the stop / target / 15:15 price; `ref` the price the order met before slippage
        (the candle's open when it gapped through the stop)."""
        t = s.trade
        t.exit_bar, t.exit_reason, t.exit_level, t.exit_fill = bar, reason, level, fill
        t.gross = t.qty * (fill - t.entry_fill) * t.side / 100.0
        t.fees = self._fees(t, fill)
        t.net = t.gross - t.fees
        t.slippage += t.qty * abs(fill - (level if ref is None else ref)) / 100.0
        s.closed.append(t)
        s.trade, s.pos, s.last_exit = None, 0, reason

    def sides_open(self, s: State, bar_start: int) -> list[int]:
        """Entry orders live in this candle (stop mode)."""
        cfg = self.cfg
        if cfg.entry != "stop" or s.pos != 0 or s.trades >= cfg.max_trades:
            return []
        if not (cfg.first_entry_min <= bar_start < cfg.last_entry_min):
            return []
        if s.trades == 0:
            return [1, -1]
        if cfg.reverse and s.last_exit == "stop":
            return [x for x in (1, -1) if x not in s.used]
        return []

    def tgt_trigger(self, t: Trade) -> int:
        through = self.cfg.target_fill == "through"
        return t.target + t.side * (self.cfg.tick if through else 0)

    # one candle, one path ------------------------------------------------------------------------
    def walk(self, s: State, day: Day, k: int, hi_first: bool) -> State:
        s = s.copy()
        o, h, l, c = day.o[k], day.h[k], day.l[k], day.c[k]
        bar = int(day.start[k])
        tick = self.cfg.tick
        bt, st = day.orh + tick, day.orl - tick
        # at the open: an open trade's stop / target first (a gap), then a scheduled close-mode entry,
        # then resting entry orders the open is already beyond
        if s.pos != 0:
            t = s.trade
            if (o - t.stop) * t.side <= 0:
                self.exit(s, "stop", t.stop, self.sell_fill(o) if t.side > 0 else self.buy_fill(o), bar, ref=o)
            elif (o - self.tgt_trigger(t)) * t.side >= 0:
                self.exit(s, "target", t.target, t.target, bar)
        if day.close_signal is not None and s.trades == 0 and bar == day.close_signal[0]:
            self.enter(s, day, day.close_signal[1], o, o, bar)
        sides = self.sides_open(s, bar)
        if s.pos == 0 and 1 in sides and o >= bt:
            self.enter(s, day, 1, bt, o, bar)
        elif s.pos == 0 and -1 in sides and o <= st:
            self.enter(s, day, -1, st, o, bar)
        pts = (o, h, l, c) if hi_first else (o, l, h, c)
        for a, b in zip(pts[:-1], pts[1:]):
            cur = a
            while cur != b:
                up = b > cur
                levels = []                          # (level, event)
                sides = self.sides_open(s, bar)
                if s.pos == 0:
                    if up and 1 in sides and cur < bt <= b:
                        levels.append((bt, "long"))
                    if not up and -1 in sides and b <= st < cur:
                        levels.append((st, "short"))
                else:
                    t = s.trade
                    tt = self.tgt_trigger(t)
                    if t.side > 0:
                        if up and cur < tt <= b:
                            levels.append((tt, "target"))
                        if not up and b <= t.stop < cur:
                            levels.append((t.stop, "stop"))
                    else:
                        if not up and b <= tt < cur:
                            levels.append((tt, "target"))
                        if up and cur < t.stop <= b:
                            levels.append((t.stop, "stop"))
                if not levels:
                    break
                lvl, ev = min(levels, key=lambda x: abs(x[0] - cur))
                if ev == "long":
                    self.enter(s, day, 1, bt, None, bar)
                elif ev == "short":
                    self.enter(s, day, -1, st, None, bar)
                elif ev == "target":
                    self.exit(s, "target", s.trade.target, s.trade.target, bar)
                else:
                    t = s.trade
                    self.exit(s, "stop", t.stop, self.sell_fill(t.stop) if t.side > 0 else self.buy_fill(t.stop), bar)
                cur = lvl
        if s.pos != 0 and bar + day.length >= self.cfg.exit_min:
            t = s.trade
            self.exit(s, "eod", c, self.sell_fill(c) if t.side > 0 else self.buy_fill(c), bar, ref=c)
        return s

    def value(self, s: State, c: int) -> float:
        """The account at the candle's close if everything were closed there (net of costs)."""
        v = sum(t.net for t in s.closed)
        if s.trade is not None:
            t = s.trade
            v += t.qty * (c - t.entry_fill) * t.side / 100.0 - self._fees(t, c)
        return v

    # one session -------------------------------------------------------------------------------------
    def run_day(self, day: Day) -> tuple[list[Trade], list[dict]]:
        cfg = self.cfg
        s = State()
        trades, amb = [], []
        for k in range(len(day.start)):
            bar = int(day.start[k])
            if bar < cfg.first_entry_min:
                continue
            if bar >= cfg.exit_min:
                break
            live = s.pos != 0 or self.sides_open(s, bar) or (
                day.close_signal is not None and s.trades == 0 and bar == day.close_signal[0])
            if not live:
                if s.trades >= cfg.max_trades or bar >= cfg.last_entry_min:
                    if s.pos == 0 and (day.close_signal is None or s.trades > 0 or bar > day.close_signal[0]):
                        break
                continue
            a = self.walk(s, day, k, True)
            b = self.walk(s, day, k, False)
            va, vb = self.value(a, day.c[k]), self.value(b, day.c[k])
            pick_a = (va <= vb) if cfg.intrabar == "worst" else (va >= vb)
            nxt, other = (a, b) if pick_a else (b, a)
            if abs(va - vb) > 1e-6:
                amb.append({"date": day.date, "bar": bar, "chosen": _events(s, nxt), "other": _events(s, other)})
                if nxt.trade is not None:
                    nxt.trade.ambiguous = True
                for t in nxt.closed:
                    t.ambiguous = True
            trades.extend(nxt.closed)
            nxt.closed = []
            s = nxt
        if s.trade is not None:                     # cannot happen: the 15:15 candle closes it
            raise RuntimeError(f"{day.date}: position left open")
        return trades, amb


def _events(before: State, after: State) -> str:
    """What happened in a candle, for the ambiguity log: e.g. 'long>stop', 'target', 'short'."""
    ev = []
    prev = (before.trade.entry_bar, before.trade.side) if before.trade is not None else None
    for t in after.closed:
        if (t.entry_bar, t.side) != prev:
            ev.append("long" if t.side > 0 else "short")
        ev.append(t.exit_reason)
    if after.trade is not None and (after.trade.entry_bar, after.trade.side) != prev:
        ev.append("long" if after.trade.side > 0 else "short")
    return ">".join(ev) or "nothing"


# ── the data ──────────────────────────────────────────────────────────────────────────────────────


def to_paise(x) -> np.ndarray:
    return np.rint(np.asarray(x, dtype=float) * 100).astype(np.int64)


def load(data_dir: Path) -> dict:
    """The minute matrices (orb_data.py) and the opening ranges, in paise."""
    import json
    z = np.load(data_dir / "NIFTYBEES_1m.npz")
    with open(data_dir / "opening_ranges.json") as f:
        opening = {r["date"]: r for r in json.load(f)}
    days = [str(d) for d in z["days"]]
    return {"days": days, "o": to_paise(z["o"]), "h": to_paise(z["h"]), "l": to_paise(z["l"]),
            "c": to_paise(z["c"]), "opening": opening}


def or_levels(rec: dict, orb: str) -> tuple[int, int]:
    if orb == "raw":
        lo, hi = rec["raw_orl"], rec["raw_orh"]
    elif orb == "clean05":
        lo, hi = rec["clean_by_tol"]["0.005"]
    else:
        lo, hi = rec["orl"], rec["orh"]
    return int(round(hi * 100)), int(round(lo * 100))


def make_days(data: dict, cfg: Config) -> list[Day]:
    out = []
    n = data["o"].shape[1]
    s5 = np.arange(0, n, 5)
    for i, d in enumerate(data["days"]):
        o1, h1, l1, c1 = data["o"][i], data["h"][i], data["l"][i], data["c"][i]
        o5, c5 = o1[s5], c1[s5 + 4]
        h5, l5 = h1.reshape(-1, 5).max(axis=1), l1.reshape(-1, 5).min(axis=1)
        orh, orl = or_levels(data["opening"][d], cfg.orb)
        sig = None
        if cfg.entry == "close":
            for k, st in enumerate(s5):
                if st < cfg.first_entry_min:
                    continue
                if st + 5 >= cfg.last_entry_min:
                    break
                if c5[k] > orh:
                    sig = (int(st + 5), 1)
                    break
                if c5[k] < orl:
                    sig = (int(st + 5), -1)
                    break
            if sig is None:
                sig = (-1, 0)
        if cfg.bars == 5:
            out.append(Day(d, o5, h5, l5, c5, s5, 5, orh, orl, sig if cfg.entry == "close" else None))
        else:
            out.append(Day(d, o1, h1, l1, c1, np.arange(n), 1, orh, orl, sig if cfg.entry == "close" else None))
    return out


def run(cfg: Config, data: dict) -> dict:
    sim = Sim(cfg)
    trades, amb = [], []
    days = make_days(data, cfg)
    for day in days:
        if day.close_signal is not None and day.close_signal[1] == 0:
            continue
        t, a = sim.run_day(day)
        trades.extend(t)
        amb.extend(a)
    return {"cfg": cfg, "trades": trades, "ambiguous": amb, "sessions": [d.date for d in days]}


def hhmm(minute: int) -> str:
    t = OPEN_MIN + minute
    return f"{t // 60:02d}:{t % 60:02d}"
