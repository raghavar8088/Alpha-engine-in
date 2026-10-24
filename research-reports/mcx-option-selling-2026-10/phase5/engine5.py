"""Phase 5 (AMENDMENT_A5.md): the other MCX option markets, and three new families -
F1 weekend decay, F2 after a volatility shock, F3 report-day premium (sellers' side).
Fill / fee / margin conventions exactly as engine.run_trade."""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "phase4"),
          os.path.join(HERE, "..", "..", "..", "shared")):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import engine4 as E4  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402

# Angel, futures leg, measured by the app on 2026-10-09 (backend/app/services/commodity_broker_margin.py)
NEW_MARGIN = {"GOLD": 0.092, "SILVER": 0.127, "COPPER": 0.092, "ZINC": 0.091, "NICKEL": 0.093}
NEW_MULT = {"GOLD": 100, "SILVER": 30, "COPPER": 2500, "ZINC": 5000, "NICKEL": 1500, "GOLDM": 10, "SILVERM": 5}
NEW_FAMILY = {"GOLD": "GOLD", "GOLDM": "GOLD", "SILVER": "SILVER", "SILVERM": "SILVER", "COPPER": "COPPER",
              "ZINC": "ZINC", "NICKEL": "NICKEL"}


def register(ticks: dict):
    """Add the new markets to the engine's tables (in this process only)."""
    E.MULT.update(NEW_MULT)
    E.FAMILY.update(NEW_FAMILY)
    E.MARGIN_RATE.update(NEW_MARGIN)
    E.TICK.update(ticks)


def attach_opens(cycles, opt, sym):
    """c.open[cp][strike_idx, date_idx]: the day's first traded price (nan where there is no row)."""
    o = opt[opt.sym == sym]
    for c in cycles:
        g = o[o.expiry == c.expiry]
        didx = {d: i for i, d in enumerate(c.dates)}
        c.open = {}
        for cp in ("CE", "PE"):
            gc = g[(g.cp == cp) & (g.date.isin(didx))]
            kidx = {k: i for i, k in enumerate(c.strikes[cp])}
            arr = np.full((len(c.strikes[cp]), len(c.dates)), np.nan)
            ki, di = gc.strike.map(kidx), gc.date.map(didx)
            ok = (ki.notna() & di.notna()).to_numpy()
            arr[ki[ok].astype(int).to_numpy(), di[ok].astype(int).to_numpy()] = gc.open.to_numpy()[ok]
            c.open[cp] = arr
    return cycles


def _slip(px, tick, pct, k=1.0):
    return max(tick, pct * px) * k


def with_roc(t):
    if t is not None and "roc" not in t:
        t["roc"] = t["ret"]
    return t


# ---------------------------------------------------------------------------- F1 weekend decay
def weekend_slots(book, a, b):
    """(entry day, Slot): enter at a week's last close, exit on the next trading day."""
    out = []
    for prev, cur in zip(book.weeks[:-1], book.weeks[1:]):
        if not (pd.Timestamp(a) <= prev[-1] <= pd.Timestamp(b)):
            continue
        out.append((prev[-1], book._slot(prev[-1], cur[0])))
    return out


def run_short_open_exit(c, legs, j0, j1, mult, family, tick, slip):
    """Short `legs` at close j0; each leg bought back at day j1's OPEN if it traded that day, else at
    j1's close with 3x slippage (a stale exit)."""
    rows = []
    for cp, side, k in legs:
        i = E._row(c, cp, k)
        if i is None or not c.traded[cp][i, j0]:
            return None
        rows.append((cp, k, i))
    entry = [c.close[cp][i, j0] - _slip(c.close[cp][i, j0], tick, slip) for cp, k, i in rows]
    if min(entry) <= 0:
        return None
    exits, stale = [], 0
    for cp, k, i in rows:
        op = c.open[cp][i, j1]
        if c.traded[cp][i, j1] and np.isfinite(op) and op > 0:
            exits.append(op + _slip(op, tick, slip))
        else:
            px = c.close[cp][i, j1]
            exits.append(px + _slip(px, tick, slip, 3.0))
            stale += 1
    fees = sum(mcx_option_leg(x, mult, sell=True)["total"] for x in entry)
    fees += sum(mcx_option_leg(x, mult, sell=False)["total"] for x in exits)
    F0 = c.F[j0]
    capital = len(rows) * E.SHORT_OPTION_FACTOR * E.MARGIN_RATE[family] * F0 * mult
    pnl = (sum(entry) - sum(exits)) * mult - fees
    return {"expiry": c.expiry, "entry": c.dates[j0], "exit": c.dates[j1], "reason": "open", "F0": F0,
            "legs": ";".join(f"S{cp}{k:g}" for cp, k, i in rows), "credit": sum(entry) * mult, "fees": fees,
            "pnl": pnl, "capital": capital, "ret": pnl / capital, "roc": pnl / capital, "stale_exit_legs": stale}


def short_legs(book, c, j0, struct):
    if struct == "straddle":
        k = c.katm[j0]
        return [("CE", -1, k), ("PE", -1, k)] if np.isfinite(k) else None
    d = {"strangle25": 0.25, "strangle15": 0.15}[struct]
    kc, kp = book.pick(c, "CE", j0, d), book.pick(c, "PE", j0, d)
    return [("CE", -1, kc), ("PE", -1, kp)] if kc and kp else None


def f1_trades(book, inst, v, a, b, slip):
    struct, filt, exit_at = v
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    trades, den = [], 0
    for d0, s in weekend_slots(book, a, b):
        if s is None or s.j1 != s.j0 + 1:
            continue
        p = book.ivp.get(s.d0, np.nan)
        if filt == "ivp>=50" and not (np.isfinite(p) and p >= 50):
            continue
        den += 1
        legs = short_legs(book, s.c, s.j0, struct)
        if not legs:
            continue
        if exit_at == "open":
            t = run_short_open_exit(s.c, legs, s.j0, s.j1, mult, family, tick, slip)
        else:
            t = with_roc(E4.run_legs(s.c, legs, s.j0, s.j1, mult, family, tick, slip))
        if t:
            trades.append(t)
    return trades, den


# ---------------------------------------------------------------------------- F2 after a volatility shock
def f2_trades(book, inst, v, a, b, slip):
    k_sig, entry, struct, hold = v
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    trades, den, busy = [], 0, None
    lo, hi = pd.Timestamp(a), pd.Timestamp(b)
    for d in book.days:
        if not (lo <= d <= hi) or (busy is not None and d <= busy):
            continue
        ci = book.front(d)
        if ci is None:
            continue
        c, j = book.cycles[ci], book.pos[ci][d]
        if j < 1 or not (np.isfinite(c.F[j]) and np.isfinite(c.F[j - 1]) and np.isfinite(c.rv20[j - 1])):
            continue
        if abs(math.log(c.F[j] / c.F[j - 1])) < k_sig * c.rv20[j - 1] / math.sqrt(252):
            continue
        j0 = j if entry == "same" else j + 1
        last = len(c.dates) - 1
        if j0 > last - 2 or not np.isfinite(c.F[j0]):
            continue
        den += 1
        legs = short_legs(book, c, j0, struct)
        t = with_roc(E4.run_legs(c, legs, j0, min(j0 + hold, last), mult, family, tick, slip, stop=2.0)) if legs else None
        if t:
            trades.append(t)
            busy = t["exit"]
    return trades, den


# ---------------------------------------------------------------------------- F3 report-day premium
def f3_trades(book, inst, v, a, b, slip):
    struct, filt = v
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    trades, den = [], 0
    lo, hi = pd.Timestamp(a), pd.Timestamp(b)
    for d, s in book.report_slots():
        if s is None or not (lo <= d <= hi):
            continue
        p = book.ivp.get(s.d0, np.nan)
        if filt == "ivp>=50" and not (np.isfinite(p) and p >= 50):
            continue
        den += 1
        legs = short_legs(book, s.c, s.j0, struct)
        t = with_roc(E4.run_legs(s.c, legs, s.j0, s.j1, mult, family, tick, slip)) if legs else None
        if t:
            trades.append(t)
    return trades, den


# ---------------------------------------------------------------------------- per-trade statistics
def tstats(trades):
    if not trades:
        return {"n": 0, "net": 0.0}
    p = np.array([t["pnl"] for t in trades])
    r = np.array([t["roc"] for t in trades])
    eq = np.concatenate([[0.0], np.cumsum(p)])
    sd = p.std(ddof=1) if len(p) > 1 else np.nan
    months = max(1, len({(t["exit"].year, t["exit"].month) for t in trades}))
    return {"n": len(p), "net": float(p.sum()), "win": float((p > 0).mean()),
            "pf": float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else float("inf"),
            "t": float(p.mean() / (sd / np.sqrt(len(p)))) if sd and sd > 0 else np.nan,
            "mean_roc": float(r.mean()), "worst": float(p.min()), "worst_roc": float(r.min()),
            "maxdd": float((np.maximum.accumulate(eq) - eq).max()),
            "avg_capital": float(np.mean([t["capital"] for t in trades])), "months_with_exits": months}


def verdict(s1, s2, min_trades=10):
    if s1.get("n", 0) < min_trades:
        return "too few"
    ok = s1["net"] > 0 and s1["pf"] >= 1.15 and s2["net"] > 0 and s1["worst_roc"] >= -0.45
    return "pass" if ok else "fail"
