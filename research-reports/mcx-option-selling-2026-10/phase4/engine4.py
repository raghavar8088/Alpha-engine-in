"""Phase 4 (AMENDMENT_A4.md): one trade a week on the front month, selling or buying, and weekly
returns. Fill / fee / margin conventions exactly as engine.run_trade (PROTOCOL.md / A2)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "..", "..", "shared")):
    sys.path.insert(0, p)
import b76  # noqa: E402
import engine as E  # noqa: E402
import engine2 as E2  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402

REPORT_WEEKDAY = {"CRUDEOILM": 2, "NATGASMINI": 3}     # EIA on Wednesday, gas storage on Thursday (A4)
EXITS = {"week": (None, None), "tp50sl40": (0.5, 0.4), "tp50sl50": (0.5, 0.5), "tp100sl50": (1.0, 0.5),
         "tp200": (2.0, None)}


def _slip(px, tick, pct, k=1.0):
    return max(tick, pct * px) * k


@dataclass
class Slot:
    """One week's entry for a strategy: the front cycle, entry/exit indices, and dates."""
    c: object
    j0: int
    j1: int
    d0: pd.Timestamp
    d1: pd.Timestamp
    exp_in_week: bool


class Book:
    """Front-month lookup and the weekly (and report-day) entry slots for one set of cycles."""

    def __init__(self, cycles, ivp: dict, inst: str):
        self.cycles = sorted(cycles, key=lambda c: c.expiry)
        self.ivp, self.inst = ivp, inst
        self.pos = [{d: i for i, d in enumerate(c.dates)} for c in self.cycles]
        self.days = sorted(set(d for c in self.cycles for d in c.dates))
        wk = {}
        for d in self.days:
            wk.setdefault(tuple(d.isocalendar()[:2]), []).append(d)
        self.weeks = [wk[k] for k in sorted(wk)]
        self._memo = {}

    def front(self, d0):
        for ci, c in enumerate(self.cycles):
            if c.expiry > d0 and d0 in self.pos[ci]:
                return ci
        return None

    def _slot(self, d0, d1):
        ci = self.front(d0)
        if ci is None:
            return None
        c, pos = self.cycles[ci], self.pos[ci]
        j0 = pos[d0]
        exp_in = c.expiry <= d1
        if exp_in:
            j1 = len(c.dates) - 1
        else:
            later = [d for d in c.dates if d <= d1]
            j1 = pos[later[-1]]
        if j1 <= j0 or not np.isfinite(c.F[j0]):
            return None
        return Slot(c, j0, j1, d0, c.dates[j1], bool(exp_in))

    def week_slots(self):
        """(week's last trading day, Slot or None) for every week after the first."""
        out = []
        for prev, cur in zip(self.weeks[:-1], self.weeks[1:]):
            out.append((cur[-1], self._slot(prev[-1], cur[-1])))
        return out

    def report_slots(self):
        """(report day, Slot or None): enter at the close before the report day, exit at its close."""
        wd = REPORT_WEEKDAY[self.inst]
        out = []
        for i, d in enumerate(self.days):
            if d.weekday() == wd and i > 0:
                out.append((d, self._slot(self.days[i - 1], d)))
        return out

    def pick(self, c, cp, j, target):
        key = (c.sym, c.expiry, cp, j, target)
        if key not in self._memo:
            self._memo[key] = E2.pick_delta(c, cp, j, target)
        return self._memo[key]


# ---------------------------------------------------------------------------- generic legs, one week
def run_legs(c, legs, j0, j1, mult, family, tick, slip, stop=None, tp=None, sl=None):
    """Open `legs` [(cp, side, strike)] at close j0 (side -1 short, +1 long), close at j1 or earlier.
    Shorts present: stop when the loss reaches stop x credit. All long: target when up tp x debit,
    stop when down sl x debit. All checks at closes."""
    rows = []
    for cp, side, k in legs:
        i = E._row(c, cp, k)
        if i is None or not c.traded[cp][i, j0]:
            return None
        rows.append((cp, side, k, c.close[cp][i], c.traded[cp][i]))
    entry = []
    for cp, side, k, cl, tr in rows:
        px = cl[j0]
        f = px - _slip(px, tick, slip) if side < 0 else px + _slip(px, tick, slip)
        if not np.isfinite(f) or f <= 0:
            return None
        entry.append(f)
    credit = sum(-side * f for (cp, side, k, cl, tr), f in zip(rows, entry))
    has_short = any(side < 0 for _, side, _ in legs)
    if has_short and credit <= 0:
        return None
    debit = -credit
    j_exit, reason = j1, "expiry" if j1 == len(c.dates) - 1 else "week"
    for j in range(j0 + 1, j1 + 1):
        pnl_now = credit + sum(side * cl[j] for cp, side, k, cl, tr in rows)
        if has_short:
            if stop is not None and -pnl_now >= stop * credit:
                j_exit, reason = j, "stop"
                break
        else:
            if tp is not None and pnl_now >= tp * debit:
                j_exit, reason = j, "target"
                break
            if sl is not None and -pnl_now >= sl * debit:
                j_exit, reason = j, "stop"
                break
    exits, stale = [], 0
    for cp, side, k, cl, tr in rows:
        px = cl[j_exit]
        m = 1.0 if tr[j_exit] else 3.0
        stale += 0 if tr[j_exit] else 1
        exits.append(px + _slip(px, tick, slip, m) if side < 0 else max(px - _slip(px, tick, slip, m), 0.0))
    gross = credit + sum(side * f for (cp, side, k, cl, tr), f in zip(rows, exits))
    fees = 0.0
    for (cp, side, k, cl, tr), fe, fx in zip(rows, entry, exits):
        fees += mcx_option_leg(fe, mult, sell=side < 0)["total"]
        if fx > 0:
            fees += mcx_option_leg(fx, mult, sell=side > 0)["total"]
    F0 = c.F[j0]
    margin = sum(E.SHORT_OPTION_FACTOR * E.MARGIN_RATE[family] * F0 * mult for _, s, _ in legs if s < 0)
    paid = sum(f * mult for (cp, side, k, cl, tr), f in zip(rows, entry) if side > 0)
    capital = margin + paid
    pnl = gross * mult - fees
    return {"expiry": c.expiry, "entry": c.dates[j0], "exit": c.dates[j_exit], "reason": reason, "F0": F0,
            "legs": ";".join(f"{'S' if s < 0 else 'L'}{cp}{k:g}" for cp, s, k in legs), "credit": credit * mult,
            "fees": fees, "pnl": pnl, "capital": capital, "ret": pnl / capital if capital > 0 else np.nan,
            "stale_exit_legs": stale}


def run_dh_week(c, j0, j1, lots, mult, family, tick, slip):
    """Short `lots` ATM straddles at close j0; hold round(straddle delta x lots) futures, re-hedged at every
    close; close everything at j1. Capital = option margin + the hedge's peak futures margin (A2/A3)."""
    k = c.katm[j0]
    if not np.isfinite(k):
        return None
    ser = []
    for cp in ("CE", "PE"):
        i = E._row(c, cp, k)
        if i is None or not c.traded[cp][i, j0]:
            return None
        ser.append((cp, c.close[cp][i], c.traded[cp][i]))
    sell_in = [cl[j0] - _slip(cl[j0], tick, slip) for _, cl, _ in ser]
    if min(sell_in) <= 0:
        return None
    fees = sum(mcx_option_leg(x, mult * lots, sell=True)["total"] for x in sell_in)
    hedge, hpnl, max_h = 0, 0.0, 0
    for j in range(j0, j1 + 1):
        if j > j0 and np.isfinite(c.F[j]) and np.isfinite(c.F[j - 1]):
            hpnl += hedge * (c.F[j] - c.F[j - 1]) * mult
        if j == j1:
            break
        F = c.F[j]
        if not np.isfinite(F):
            continue
        T = max((c.expiry - c.dates[j]).days, 0.5) / 365.0
        px = np.array([cl[j] for _, cl, _ in ser])
        isc = np.array([True, False])
        iv = b76.implied_vol(px, np.full(2, F), np.full(2, k), np.full(2, T), isc)
        if not np.isfinite(iv).all():
            continue
        dl = b76.delta(np.full(2, F), np.full(2, k), np.full(2, T), iv, isc)
        target = int(round(float(dl.sum()) * lots))
        if target != hedge:
            ch = target - hedge
            fees += E2.fut_cost(abs(ch), F, mult, buy=ch > 0)
            hedge = target
            max_h = max(max_h, abs(hedge))
    if hedge and np.isfinite(c.F[j1]):
        fees += E2.fut_cost(abs(hedge), c.F[j1], mult, buy=hedge < 0)
    out, stale = [], 0
    for _, cl, tr in ser:
        out.append(cl[j1] + _slip(cl[j1], tick, slip, 1.0 if tr[j1] else 3.0))
        stale += 0 if tr[j1] else 1
    fees += sum(mcx_option_leg(x, mult * lots, sell=False)["total"] for x in out)
    opt = (sum(sell_in) - sum(out)) * mult * lots
    margin = 2 * lots * E.SHORT_OPTION_FACTOR * E.MARGIN_RATE[family] * c.F[j0] * mult
    capital = margin + max_h * E.MARGIN_RATE[family] * c.F[j0] * mult
    pnl = opt + hpnl - fees
    return {"expiry": c.expiry, "entry": c.dates[j0], "exit": c.dates[j1], "reason": "expiry" if j1 == len(c.dates) - 1 else "week",
            "F0": c.F[j0], "legs": f"S{lots}xCE{k:g};S{lots}xPE{k:g}+hedge", "credit": sum(sell_in) * mult * lots,
            "fees": fees, "pnl": pnl, "capital": capital, "ret": pnl / capital if capital > 0 else np.nan,
            "stale_exit_legs": stale, "max_hedge_lots": max_h}


# ---------------------------------------------------------------------------- weekly statistics
def wstats(rows, slip_rows=None):
    """rows: one dict per week {'allowed', 'trade'}; weeks without a trade count as 0 and not profitable."""
    n = len(rows)
    allowed = sum(r["allowed"] for r in rows)
    tr = [r["trade"] for r in rows if r["trade"] is not None]
    ret_all = np.array([r["trade"]["ret"] if r["trade"] is not None else 0.0 for r in rows], dtype=float)
    pnl_all = np.array([r["trade"]["pnl"] if r["trade"] is not None else 0.0 for r in rows], dtype=float)
    out = {"weeks": n, "allowed": allowed, "traded": len(tr), "coverage": len(tr) / max(allowed, 1)}
    if not tr:
        return {**out, "net": 0.0, "mean_ret": 0.0, "pos_weeks": 0.0, "ge2_weeks": 0.0}
    p = np.array([t["pnl"] for t in tr])
    r = np.array([t["ret"] for t in tr])
    sd = p.std(ddof=1) if len(p) > 1 else np.nan
    eq = np.concatenate([[0.0], np.cumsum(pnl_all)])
    streak = best = 0
    for x in pnl_all:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    m = float(ret_all.mean())
    out.update({
        "net": float(p.sum()), "pf": float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else float("inf"),
        "t": float(p.mean() / (sd / np.sqrt(len(p)))) if sd and sd > 0 else np.nan,
        "win_traded": float((p > 0).mean()), "pos_weeks": float((pnl_all > 0).mean()),
        "ge2_weeks": float((ret_all >= 0.02).mean()), "mean_ret": m, "median_ret": float(np.median(ret_all)),
        "worst_ret": float(r.min()), "best_ret": float(r.max()), "worst_pnl": float(p.min()),
        "maxdd": float((np.maximum.accumulate(eq) - eq).max()), "avg_capital": float(np.mean([t["capital"] for t in tr])),
        "longest_nonprofit_run": int(best), "stops": sum(t["reason"] == "stop" for t in tr),
        "targets": sum(t["reason"] == "target" for t in tr)})
    if m > 0:
        f = 0.02 / m
        out.update({"f_star": f, "worst_week_at_f_star": f * out["worst_ret"], "ge2_weeks_at_f_star": float((ret_all >= m).mean())})
    else:
        out.update({"f_star": np.nan, "worst_week_at_f_star": np.nan, "ge2_weeks_at_f_star": 0.0})
    return out
