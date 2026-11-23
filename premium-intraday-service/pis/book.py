"""A paper book: sizing, the risk limits, fills and exits. The shared portfolio and every strategy's observation
book are instances of the same class with the same limits (pis.config.Risk).

FILL MODEL (identical in replay and live; decisions at five-minute bar closes)
  entry   the trigger bar's close +/- slippage (side-adverse); quantity capped at max_participation of that bar's
          volume (a PARTIAL fill when the cap binds; refused when it allows no whole share)
  stop    market order: a bar that OPENS through the stop fills at its open, otherwise at the stop; slippage adverse
  target  limit order: fills when the bar trades THROUGH the target by one tick (max(Rs 0.05, 1 bp)), at the target,
          no slippage; a bar that opens through it fills at the open
  both    a bar that reaches the stop and the target is counted as the stop (pessimistic)
  time    the strategy's time exit and the 15:05 square-off are market orders at that bar's close
  failed  no price for a stock at 15:05 nor 15:10 = a FAILED EXIT: closed at the last known price, flagged, alerted
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import costs as C
from .timeutil import hhmm, OPEN_MIN


def _cmin(k: int) -> int:
    return OPEN_MIN + (k + 1) * 5


def exit_check(side: int, stop: float, target: float | None, slip_bp: float, time_exit_min: int, bar, k: int):
    """The one exit rule (books and the imported-strategy harness both call it). bar = (t, o, h, l, c, v) of a bar
    AFTER the entry bar. Returns (reference price, fill price, reason) or None."""
    _, o, h, l, c, _ = bar
    s = side
    slip = slip_bp / 1e4
    if (o - stop) * s <= 0:
        return o, o * (1 - s * slip), "stop (opened through it)"
    if (l <= stop) if s > 0 else (h >= stop):
        return stop, stop * (1 - s * slip), "stop"
    if target is not None:
        tick = max(0.05, target * 0.0001)
        if (o - target) * s >= 0:
            return o, o, "target (opened through it)"
        if (h >= target + tick) if s > 0 else (l <= target - tick):
            return target, target, "target"
    if _cmin(k) >= time_exit_min:
        return c, c * (1 - s * slip), f"time exit {time_exit_min // 60:02d}:{time_exit_min % 60:02d}"
    return None


@dataclass
class Position:
    pid: str
    book: str
    strategy: str
    variant: str
    level: str
    symbol: str
    sector: str
    side: int
    qty: int
    qty_wanted: int
    ref: float
    entry: float
    stop: float
    target: float
    slip_bp: float
    planned_risk: float
    k_entry: int
    t_entry: int
    time_exit_min: int
    notional: float
    status: str = "OPEN"
    exit: float | None = None
    exit_ref: float | None = None
    k_exit: int | None = None
    t_exit: int | None = None
    reason: str | None = None
    gross: float | None = None
    fees: dict | None = None
    net: float | None = None
    r_net: float | None = None
    failed_exit: bool = False
    partial: bool = False
    holes: int = 0
    knew: dict = field(default_factory=dict)

    def mark(self, price: float) -> float:
        return (price - self.entry) * self.side * self.qty

    def public(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "knew"}
        d["side"] = "LONG" if self.side > 0 else "SHORT"
        d["entry_time"] = hhmm(self.t_entry)
        d["exit_time"] = hhmm(self.t_exit) if self.t_exit else None
        return d


class Book:
    def __init__(self, name: str, risk, admits=None, journal=None):
        self.name = name
        self.R = risk
        self.equity = float(risk.capital)
        self.admits = admits                  # None = any strategy; else a predicate(strategy_id, side, cond) -> bool
        self.open: list[Position] = []
        self.closed: list[Position] = []
        self.journal = journal if journal is not None else []
        self.day = None
        self.day_start = self.equity
        self.day_realized = 0.0
        self.blocked = None                   # why new entries are blocked for the rest of the day
        self.peak_gross = 0.0
        self.days_traded = set()
        self.alerts: list[dict] = []
        self._n = 0

    # ── the day ─────────────────────────────────────────────────────────────────
    def start_day(self, day) -> None:
        self.day = day
        self.day_start = self.equity
        self.day_realized = 0.0
        self.blocked = None
        self.peak_gross = 0.0

    def open_risk(self, sector: str | None = None) -> float:
        return sum(abs(p.entry - p.stop) * p.qty for p in self.open if sector is None or p.sector == sector)

    def gross(self) -> float:
        return sum(p.entry * p.qty for p in self.open)

    def unrealized(self, state, k: int) -> float:
        u = 0.0
        for p in self.open:
            px = state.close(p.symbol, k) if k >= 0 else None
            if px is None:
                b = state.bars_upto(p.symbol, k)
                px = b[-1][4] if b else p.entry
            u += p.mark(px)
        return u

    # ── admission ───────────────────────────────────────────────────────────────
    def admit(self, intent: dict, k: int, t_close: int, last_entry_min: int) -> tuple[Position | None, str]:
        """intent: strategy, variant, level, symbol, sector, side, ref, stop, target, slip_bp, bar_volume,
        time_exit_min, knew. Returns (position or None, decision text)."""
        R = self.R
        sym, side = intent["symbol"], intent["side"]
        if _cmin(k) > last_entry_min:
            return None, f"entries closed at {last_entry_min // 60:02d}:{last_entry_min % 60:02d}"
        if self.blocked:
            return None, self.blocked
        if len(self.open) >= R.max_positions:
            return None, f"already {len(self.open)} open positions (limit {R.max_positions})"
        held = next((p for p in self.open if p.symbol == sym), None)
        if held:
            return None, f"already holds {sym} ({held.strategy} {held.level})"
        if sum(1 for p in self.open if p.sector == intent["sector"]) >= R.max_per_sector:
            return None, f"{R.max_per_sector} positions already in {intent['sector']}"
        ref, stop = intent["ref"], intent["stop"]
        slip = intent["slip_bp"]
        fill = ref * (1 + side * slip / 1e4)
        per_share_risk = abs(fill - stop)
        cost_ps = C.est_cost_per_share(fill, max(1, int(R.risk_per_trade * self.day_start / max(per_share_risk, 1e-9))),
                                       side, slip)
        budget = R.risk_per_trade * self.day_start
        qty = int(budget // (per_share_risk + cost_ps)) if per_share_risk + cost_ps > 0 else 0
        reasons = []
        cap_n = int(R.max_notional_frac * self.day_start // fill)
        if qty > cap_n:
            qty = cap_n
            reasons.append(f"notional capped at {R.max_notional_frac:.0%} of equity")
        room = R.max_gross_frac * self.day_start - self.gross()
        cap_g = int(max(0.0, room) // fill)
        if qty > cap_g:
            qty = cap_g
            reasons.append("gross exposure cap")
        want = qty
        cap_v = int(R.max_participation * intent.get("bar_volume", 0))
        partial = False
        if qty > cap_v:
            qty, partial = cap_v, True
        if qty < 1:
            if want < 1:
                return None, "cannot size one share inside the risk budget and caps"
            return None, f"bar volume {intent.get('bar_volume', 0):,} allows no fill at {R.max_participation:.0%} participation"
        risk_rs = qty * (per_share_risk + cost_ps)
        if self.open_risk() + qty * per_share_risk > R.max_open_risk * self.day_start + 1e-6:
            return None, f"open stop risk would pass {R.max_open_risk:.2%} of equity"
        if self.open_risk(intent["sector"]) + qty * per_share_risk > R.max_sector_risk * self.day_start + 1e-6:
            return None, f"stop risk in {intent['sector']} would pass {R.max_sector_risk:.2%} of equity"
        self._n += 1
        p = Position(pid=f"{self.name}|{self.day}|{self._n}", book=self.name, strategy=intent["strategy"],
                     variant=intent["variant"], level=intent["level"], symbol=sym, sector=intent["sector"],
                     side=side, qty=qty, qty_wanted=want, ref=ref, entry=fill, stop=stop, target=intent["target"],
                     slip_bp=slip, planned_risk=risk_rs, k_entry=k, t_entry=t_close,
                     time_exit_min=intent["time_exit_min"], notional=fill * qty, partial=partial,
                     knew=intent.get("knew", {}))
        self.open.append(p)
        self.peak_gross = max(self.peak_gross, self.gross())
        self.days_traded.add(self.day)
        note = "; ".join(reasons + ([f"PARTIAL: {qty} of {want} (bar volume cap)"] if partial else []))
        return p, ("admitted" + (f" ({note})" if note else ""))

    # ── exits ───────────────────────────────────────────────────────────────────
    def _close(self, p: Position, ref: float, price: float, k: int, t: int, reason: str, failed: bool = False):
        p.exit_ref, p.exit, p.k_exit, p.t_exit, p.reason = ref, price, k, t, reason
        p.gross = (price - p.entry) * p.side * p.qty
        p.fees = C.charges(p.entry, price, p.qty, p.side)
        p.net = p.gross - p.fees["total"]
        p.r_net = p.net / p.planned_risk if p.planned_risk > 0 else None
        p.status = "CLOSED"
        p.failed_exit = failed
        self.equity += p.net
        self.day_realized += p.net
        self.open.remove(p)
        self.closed.append(p)

    def manage(self, state, k: int, t_close: int) -> list[Position]:
        """Stops, targets and time exits on bar k for positions opened before bar k."""
        done = []
        for p in list(self.open):
            if k <= p.k_entry:
                continue
            b = state.bar(p.symbol, k)
            if b is None:
                p.holes += 1
                continue
            ex = exit_check(p.side, p.stop, p.target, p.slip_bp, p.time_exit_min, b, k)
            if ex is None:
                continue
            self._close(p, ex[0], ex[1], k, t_close, ex[2])
            done.append(p)
        return done

    def square_off(self, state, k: int, t_close: int, final: bool) -> list[Position]:
        done = []
        for p in list(self.open):
            b = state.bar(p.symbol, k)
            if b is not None:
                c = b[4]
                self._close(p, c, c * (1 - p.side * p.slip_bp / 1e4), k, t_close, "square-off 15:05" if not final else "square-off 15:10 (retry)")
                done.append(p)
            elif final:
                bars = state.bars_upto(p.symbol, k)
                last = bars[-1] if bars else None
                px = last[4] if last else p.entry
                at = hhmm(last[0] + 300) if last else "entry"
                self._close(p, px, px * (1 - p.side * p.slip_bp / 1e4), k, t_close,
                            f"FAILED EXIT: no price at 15:05 or 15:10; closed at the last known price ({at})", failed=True)
                self.alerts.append({"type": "failed_exit", "symbol": p.symbol, "pid": p.pid, "qty": p.qty,
                                    "side": "LONG" if p.side > 0 else "SHORT", "last_price": px, "at": at})
                done.append(p)
        return done

    def check_loss_stop(self, state, k: int) -> None:
        if self.blocked:
            return
        pnl = self.day_realized + self.unrealized(state, k)
        if pnl <= -self.R.daily_loss_stop * self.day_start:
            self.blocked = (f"daily loss stop: {pnl:,.0f} is past -{self.R.daily_loss_stop:.0%} of the day's "
                            f"starting equity; no new entries today")
