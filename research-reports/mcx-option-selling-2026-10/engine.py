"""Daily backtest engine for MCX option-selling structures (see PROTOCOL.md).

Every fill is a traded bhavcopy close +/- slippage; fees follow Angel's MCX option card; capital is
broker-style margin (1.2 x measured futures rate x notional per short leg, no netting) plus
premium paid. Nothing here reads a price a trader could not have had at that day's close.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "shared"))
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402

import b76  # noqa: E402

MULT = {"CRUDEOILM": 10, "CRUDEOIL": 100, "NATGASMINI": 250, "NATURALGAS": 1250}
MARGIN_RATE = {"CRUDEOIL": 0.311, "NATURALGAS": 0.167}      # Angel, futures, 2026-10-09
SHORT_OPTION_FACTOR = 1.20
FAMILY = {"CRUDEOIL": "CRUDEOIL", "CRUDEOILM": "CRUDEOIL", "NATURALGAS": "NATURALGAS",
          "NATGASMINI": "NATURALGAS"}

# ---------------------------------------------------------------------------- structures
# (name, [(cp, side, distance_key)]) ; side -1 short, +1 long ; distance: "k" or "k+w" or "k-w"
STRUCT_LEGS = {
    "strangle": [("CE", -1, "k"), ("PE", -1, "k")],
    "straddle": [("CE", -1, "k"), ("PE", -1, "k")],
    "condor": [("CE", -1, "k"), ("PE", -1, "k"), ("CE", +1, "kw"), ("PE", +1, "kw")],
    "fly": [("CE", -1, "k"), ("PE", -1, "k"), ("CE", +1, "kw"), ("PE", +1, "kw")],
    "putspread": [("PE", -1, "k"), ("PE", +1, "kw")],
    "callspread": [("CE", -1, "k"), ("CE", +1, "kw")],
    "shortput": [("PE", -1, "k")],
    "shortcall": [("CE", -1, "k")],
}


def structure_grid() -> list[tuple[str, float, float]]:
    g = [("strangle", k, 0.0) for k in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    g += [("straddle", 0.0, 0.0)]
    g += [("condor", k, w) for k in (0.5, 0.75, 1.0, 1.25, 1.5) for w in (0.5, 1.0)]
    g += [("fly", 0.0, w) for w in (0.5, 1.0)]
    g += [("putspread", k, w) for k in (0.0, 0.5, 0.75, 1.0, 1.25) for w in (0.5, 1.0)]
    g += [("callspread", k, w) for k in (0.0, 0.5, 0.75, 1.0, 1.25) for w in (0.5, 1.0)]
    g += [("shortput", k, 0.0) for k in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    g += [("shortcall", k, 0.0) for k in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    assert len(g) == 51
    return g


ENTRIES = (20, 15, 10, 7, 5)
PTS = (None, 0.50, 0.75)
SLS = (None, 1.0, 2.0)
TEXITS = (0, 1)
FILTERS = ("none", "ivrv")


# ---------------------------------------------------------------------------- cycles
@dataclass
class Cycle:
    sym: str
    expiry: pd.Timestamp
    dates: list                      # trading dates of this cycle, ascending, last = expiry day
    tdte: np.ndarray                 # trading days to expiry for each date
    F: np.ndarray                    # underlying futures close (nan if it did not trade)
    straddle: np.ndarray             # ATM straddle (traded legs) ; nan if unavailable
    katm: np.ndarray                 # ATM strike
    iv: np.ndarray                   # ATM implied vol
    rv20: np.ndarray                 # 20-day realised vol of the underlying future
    sma10: np.ndarray = None         # 10/20-session SMA of the underlying future's closes (A1)
    sma20: np.ndarray = None
    strikes: dict = field(default_factory=dict)   # cp -> sorted np.array of strikes
    close: dict = field(default_factory=dict)     # (cp) -> 2d array [strike_idx, date_idx]
    high: dict = field(default_factory=dict)
    traded: dict = field(default_factory=dict)    # (cp) -> 2d bool array
    step: float = 0.0                # typical strike step near the money


def underlying_map(fut: pd.DataFrame, sym: str) -> dict:
    """option expiry -> futures expiry (the same symbol's first futures expiry on/after it)."""
    fexp = np.array(sorted(fut.loc[fut.sym == sym, "expiry"].unique()))
    def m(e):
        later = fexp[fexp >= np.datetime64(e)]
        return pd.Timestamp(later[0]) if len(later) else None
    return m


def build_cycles(opt: pd.DataFrame, fut: pd.DataFrame, sym: str, fut_sym: str,
                 exp_from: str, exp_to: str) -> list[Cycle]:
    o = opt[(opt.sym == sym) & (opt.expiry >= exp_from) & (opt.expiry <= exp_to)]
    f = fut[fut.sym == fut_sym]
    umap = underlying_map(fut, fut_sym)
    out = []
    for exp, g in o.groupby("expiry"):
        fe = umap(exp)
        if fe is None:
            continue
        fc = f[f.expiry == fe].set_index("date").sort_index()
        dates = sorted(d for d in g.date.unique() if d <= exp)
        dates = [d for d in dates if d in fc.index]
        if len(dates) < 6 or dates[-1] != exp:
            continue
        n = len(dates)
        tdte = np.arange(n - 1, -1, -1)
        Fv = np.array([fc.at[d, "close"] if fc.at[d, "traded"] else np.nan for d in dates], dtype=float)
        # realised vol: the underlying contract's own closes, 20 sessions back
        fcl = fc["close"].where(fc["traded"]).astype(float)
        lr = np.log(fcl).diff()
        rv = lr.rolling(20, min_periods=15).std() * math.sqrt(252)
        rv20 = np.array([rv.get(d, np.nan) for d in dates], dtype=float)
        s10 = fcl.rolling(10, min_periods=8).mean()
        s20 = fcl.rolling(20, min_periods=15).mean()
        c = Cycle(sym=sym, expiry=exp, dates=dates, tdte=tdte, F=Fv,
                  straddle=np.full(n, np.nan), katm=np.full(n, np.nan), iv=np.full(n, np.nan),
                  rv20=rv20, sma10=np.array([s10.get(d, np.nan) for d in dates], dtype=float),
                  sma20=np.array([s20.get(d, np.nan) for d in dates], dtype=float))
        didx = {d: i for i, d in enumerate(dates)}
        for cp in ("CE", "PE"):
            gc = g[(g.cp == cp) & (g.date.isin(dates))]
            ks = np.array(sorted(gc.strike.unique()), dtype=float)
            kidx = {k: i for i, k in enumerate(ks)}
            cl = np.full((len(ks), n), np.nan)
            hi = np.full((len(ks), n), np.nan)
            tr = np.zeros((len(ks), n), dtype=bool)
            ki = gc.strike.map(kidx).to_numpy()
            di = gc.date.map(didx).to_numpy()
            cl[ki, di] = gc.close.to_numpy()
            hi[ki, di] = gc.high.to_numpy()
            tr[ki, di] = gc.traded.to_numpy()
            # carry the last close forward where a strike has no row (exchange carries it)
            cl = pd.DataFrame(cl).ffill(axis=1).to_numpy()
            c.strikes[cp], c.close[cp], c.high[cp], c.traded[cp] = ks, cl, hi, tr
        allk = np.union1d(c.strikes["CE"], c.strikes["PE"])
        for j in range(n):
            if not np.isfinite(Fv[j]):
                continue
            both = [k for k in allk if _traded(c, "CE", k, j) and _traded(c, "PE", k, j)]
            if not both:
                continue
            k0 = min(both, key=lambda k: abs(k - Fv[j]))
            ce, pe = _close(c, "CE", k0, j), _close(c, "PE", k0, j)
            c.katm[j], c.straddle[j] = k0, ce + pe
            T = max((exp - dates[j]).days, 0.5) / 365.0
            ivs = b76.implied_vol(np.array([ce, pe]), np.array([Fv[j]] * 2), np.array([k0] * 2),
                                  np.array([T] * 2), np.array([True, False]))
            c.iv[j] = np.nanmean(ivs) if np.isfinite(ivs).any() else np.nan
        near = allk[(allk > np.nanmedian(Fv) * 0.9) & (allk < np.nanmedian(Fv) * 1.1)]
        c.step = float(np.median(np.diff(near))) if len(near) > 2 else float(np.median(np.diff(allk)))
        out.append(c)
    return out


def _row(c: Cycle, cp: str, k: float):
    ks = c.strikes[cp]
    i = np.searchsorted(ks, k)
    if i < len(ks) and ks[i] == k:
        return i
    return None


def _traded(c: Cycle, cp: str, k: float, j: int) -> bool:
    i = _row(c, cp, k)
    return i is not None and bool(c.traded[cp][i, j])


def _close(c: Cycle, cp: str, k: float, j: int) -> float:
    i = _row(c, cp, k)
    return float(c.close[cp][i, j]) if i is not None else np.nan


# ---------------------------------------------------------------------------- legs
def pick_strike(c: Cycle, cp: str, target: float, j: int, side: str = "any") -> float | None:
    """The traded strike nearest `target` on day j, within two strike steps."""
    ks = c.strikes[cp]
    tr = c.traded[cp][:, j]
    cand = ks[tr]
    if side == "above":
        cand = cand[cand > target - 1e-9]
    elif side == "below":
        cand = cand[cand < target + 1e-9]
    if not len(cand):
        return None
    k = cand[np.argmin(np.abs(cand - target))]
    if abs(k - target) > 2 * c.step + 1e-9:
        return None
    return float(k)


TREND = {"trend10": 10, "trend20": 20, "trendspread10": 10, "trendspread20": 20}


def resolve_trend(c: Cycle, struct: str, j: int) -> str | None:
    """A1: above its n-day average the future is trending up -> sell the put side; below -> the call side."""
    n = TREND[struct]
    sma = c.sma10[j] if n == 10 else c.sma20[j]
    if sma is None or not (np.isfinite(sma) and np.isfinite(c.F[j])):
        return None
    up = c.F[j] > sma
    if struct.startswith("trendspread"):
        return "putspread" if up else "callspread"
    return "shortput" if up else "shortcall"


def legs_for(c: Cycle, struct: str, k: float, w: float, j: int):
    """[(cp, side, strike)] for this structure on entry day j, or None (skip the cycle)."""
    if struct in TREND:
        struct = resolve_trend(c, struct, j)
        if struct is None:
            return None
    F, S = c.F[j], c.straddle[j]
    if not (np.isfinite(F) and np.isfinite(S) and S > 0):
        return None
    legs = []
    if struct in ("straddle", "fly"):
        katm = c.katm[j]
        legs += [("CE", -1, katm), ("PE", -1, katm)]
    for cp, side, dist in STRUCT_LEGS[struct]:
        if struct in ("straddle", "fly") and dist == "k":
            continue
        d = k if dist == "k" else k + w
        if cp == "CE":
            kk = pick_strike(c, "CE", F + d * S, j, "above" if dist == "kw" else "any")
        else:
            kk = pick_strike(c, "PE", F - d * S, j, "below" if dist == "kw" else "any")
        if kk is None:
            return None
        legs.append((cp, side, kk))
    # wings must sit beyond their short strike
    shorts = {cp: kk for cp, s, kk in legs if s < 0}
    for cp, s, kk in legs:
        if s > 0 and cp in shorts:
            if (cp == "CE" and kk <= shorts["CE"]) or (cp == "PE" and kk >= shorts["PE"]):
                return None
    return legs


# ---------------------------------------------------------------------------- one trade
TICK = {"CRUDEOIL": 0.10, "CRUDEOILM": 0.05, "NATURALGAS": 0.05, "NATGASMINI": 0.05}


def run_trade(c: Cycle, legs, j0: int, mult: int, family: str, tick: float, slip_pct: float,
              pt, sl, texit: int) -> dict | None:
    n = len(c.dates)
    rows = []
    for cp, side, kk in legs:
        i = _row(c, cp, kk)
        rows.append((cp, side, kk, c.close[cp][i], c.traded[cp][i]))
    def slip(px, k=1.0):
        return max(tick, slip_pct * px) * k
    entry = []
    for cp, side, kk, cl, tr in rows:
        px = cl[j0]
        fill = px - slip(px) if side < 0 else px + slip(px)
        if fill <= 0:
            return None
        entry.append(fill)
    credit = sum(-side * f for (cp, side, kk, cl, tr), f in zip(rows, entry))
    if credit <= 0 and any(s < 0 for _, s, _ in legs):
        return None
    last = n - 1 - texit
    if last <= j0:
        return None
    j_exit, reason = last, "time"
    for j in range(j0 + 1, last + 1):
        # cost to close at today's close: buy back every short, sell every long
        cost_to_close = sum(-side * cl[j] for cp, side, kk, cl, tr in rows)
        pnl_now = credit - cost_to_close
        if pt is not None and pnl_now >= pt * credit:
            j_exit, reason = j, "target"
            break
        if sl is not None and -pnl_now >= sl * credit:
            j_exit, reason = j, "stop"
            break
    exit_fills, stale = [], 0
    for cp, side, kk, cl, tr in rows:
        px = cl[j_exit]
        mult_slip = 1.0 if tr[j_exit] else 3.0
        stale += 0 if tr[j_exit] else 1
        fill = px + slip(px, mult_slip) if side < 0 else max(px - slip(px, mult_slip), 0.0)
        exit_fills.append(fill)
    gross_unit = credit + sum(side * f for (cp, side, kk, cl, tr), f in zip(rows, exit_fills))
    fees = 0.0
    for (cp, side, kk, cl, tr), fe, fx in zip(rows, entry, exit_fills):
        fees += mcx_option_leg(fe, mult, sell=side < 0)["total"]
        if fx > 0:
            fees += mcx_option_leg(fx, mult, sell=side > 0)["total"]
    F0 = c.F[j0]
    margin = sum(SHORT_OPTION_FACTOR * MARGIN_RATE[family] * F0 * mult for _, s, _ in legs if s < 0)
    paid = sum(f * mult for (cp, side, kk, cl, tr), f in zip(rows, entry) if side > 0)
    capital = margin + paid
    pnl = gross_unit * mult - fees
    return {"expiry": c.expiry, "entry": c.dates[j0], "exit": c.dates[j_exit], "reason": reason,
            "F0": F0, "straddle0": c.straddle[j0], "iv0": c.iv[j0], "rv0": c.rv20[j0],
            "legs": ";".join(f"{'S' if s < 0 else 'L'}{cp}{kk:g}" for cp, s, kk in legs),
            "credit": credit * mult, "gross": gross_unit * mult, "fees": fees, "pnl": pnl,
            "capital": capital, "roc": pnl / capital if capital > 0 else np.nan, "stale_exit_legs": stale}


def passes_filter(c: Cycle, j0: int, filt: str) -> bool:
    if filt == "none":
        return True
    if not (np.isfinite(c.iv[j0]) and np.isfinite(c.rv20[j0])):
        return False
    return c.iv[j0] > (1.10 if filt == "ivrv110" else 1.0) * c.rv20[j0]


def grid_a1() -> list[tuple[str, float, float]]:
    """PROTOCOL.md's 51 structures plus A1's 30 trend-aware ones."""
    g = structure_grid()
    g += [(s, k, 0.0) for s in ("trend10", "trend20") for k in (0.5, 0.75, 1.0, 1.25, 1.5)]
    g += [(s, k, w) for s in ("trendspread10", "trendspread20") for k in (0.5, 0.75, 1.0, 1.25, 1.5)
          for w in (0.5, 1.0)]
    assert len(g) == 81
    return g


def entry_index(c: Cycle, n_tdte: int):
    hit = np.where(c.tdte == n_tdte)[0]
    return int(hit[0]) if len(hit) else None


def run_variant(cycles: list[Cycle], struct: str, k: float, w: float, n_entry: int, filt: str,
                pt, sl, texit: int, mult: int, family: str, tick: float, slip_pct: float = 0.01):
    trades = []
    for c in cycles:
        j0 = entry_index(c, n_entry)
        if j0 is None:
            continue
        if not passes_filter(c, j0, filt):
            continue
        legs = legs_for(c, struct, k, w, j0)
        if legs is None:
            continue
        t = run_trade(c, legs, j0, mult, family, tick, slip_pct, pt, sl, texit)
        if t is not None:
            trades.append(t)
    return trades
