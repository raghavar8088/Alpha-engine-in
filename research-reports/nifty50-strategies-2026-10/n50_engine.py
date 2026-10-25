"""NIFTY 50 intraday momentum, PREREG_A1.md (sha256 2c554087...): the 09:30 screen, setups S1-S3, Angel One
intraday costs, the book's limits and the matched baselines B1-B3.

Candle index b counts the 5-minute candles from 09:15: 0 = 09:15, 3 = 09:30, 26 = 11:25, 50 = 13:25,
71 = 15:10, 74 = 15:25. The screen reads candles 0 .. rb-1 (rb = 3: all closed by 09:30) and earlier
sessions only; test_n50.py checks that nothing later can move it.

Points the pre-registration leaves open, resolved here and disclosed in the report:
  * S1's stop order is live on the candles 09:30 .. 11:25 and is cancelled at 11:30.
  * S3 uses the FIRST candle after 09:30 that touches the session VWAP; its signal candle must close by
    13:30 (the 13:25 candle at the latest).
  * Filters act before the top-N cut: the N strongest CONFIRMED candidates are taken.
  * If the 15:10 candle is missing, the square-off fills at the next candle's open.
  * "Costs x1.5 / x2" scale the charges AND the slippage.
  * R is a trade's net P&L over the risk it actually carried, |entry - stop| x quantity.
"""
from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "shared", ROOT / "backend"):          # the repo's own packages first
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))
from app.services import angel_fees  # noqa: E402  (the app's own Angel One cost model)

NB = 75
B930, B1125, B1325, B1510 = 3, 26, 50, 71
CAPITAL, RISK, CAP_TRADE, CAP_BOOK = 1_000_000.0, 5_000.0, 1_000_000.0, 5_000_000.0
MAX_OPEN = MAX_ENTRIES = 5
EXTRA_SLIP_BP = 2.0
PERIODS = {"dev": ("2021-10-01", "2023-12-31"), "val": ("2024-01-01", "2024-12-31"),
           "final": ("2025-01-01", "2026-10-23")}
FILTERS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
SETUPS = ("S1", "S2", "S3")
REASONS = {0: "square-off", 1: "stop", 2: "target", 3: "vwap trail"}


# ---------------------------------------------------------------------------- costs
def fees(buy_val, sell_val):
    """angel_fees.round_trip(product="INTRADAY") on arrays of buy-leg and sell-leg values (rupees)."""
    p = "INTRADAY"
    pct, cap = angel_fees.BROKERAGE_PCT[p], angel_fees.BROKERAGE_CAP
    brk = np.minimum(cap, buy_val * pct) + np.minimum(cap, sell_val * pct)
    turn = buy_val + sell_val
    stt = sell_val * angel_fees.STT_SELL[p] + buy_val * angel_fees.STT_BUY[p]
    exch, sebi, ipft = turn * angel_fees.EXCHANGE_TXN, turn * angel_fees.SEBI_TURNOVER, turn * angel_fees.NSE_IPFT
    stamp = buy_val * angel_fees.STAMP_DUTY_BUY[p]
    gst = angel_fees.GST_RATE * (brk + exch + sebi + ipft)
    return np.round(brk + stt + exch + sebi + ipft + stamp + gst, 2)


def cs_half_spread_bp(h, l, v, pair_ok):
    """Corwin-Schultz (2012) half-spread in bp from consecutive candles' ranges, as
    backend/research/index_intraday_2026_10/ii_spreads.py computes it (negative spreads clipped to 0),
    except that pairs straddling two sessions (pair_ok False) are left out."""
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = pair_ok & (v[:-1] > 0) & (v[1:] > 0) & (l[:-1] > 0) & (l[1:] > 0)
        if ok.sum() < 200:
            return None
        b = np.log(h[:-1] / l[:-1]) ** 2 + np.log(h[1:] / l[1:]) ** 2
        g = np.log(np.maximum(h[:-1], h[1:]) / np.minimum(l[:-1], l[1:])) ** 2
        k = 3 - 2 * math.sqrt(2)
        alpha = (np.sqrt(2 * b) - np.sqrt(b)) / k - np.sqrt(g / k)
        s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return float(np.mean(np.clip(s[ok], 0, None)) / 2 * 1e4)


# ---------------------------------------------------------------------------- the panel
class Panel:
    """The clean 5-minute panel as cubes [name, session, candle], plus the daily context the screen needs.
    `end` drops every session after it, so a run over development and validation data cannot read the
    final-test candles at all."""

    def __init__(self, clean, membership_json, universe_json, swap_date="2026-03-31", end=None):
        p = clean if isinstance(clean, pd.DataFrame) else pd.read_pickle(clean)
        if end is not None:
            p = p[p.day <= pd.Timestamp(end)]
        mins = (p.ts.dt.hour * 60 + p.ts.dt.minute - (9 * 60 + 15)).to_numpy()
        if (mins % 5 != 0).any() or (mins < 0).any() or (mins >= NB * 5).any():
            raise ValueError("candles off the 09:15-15:25 five-minute grid")
        p = p.assign(b=mins // 5)
        u = json.load(open(universe_json))
        self.days = pd.DatetimeIndex(np.sort(p.day.unique()))
        idx_names = set(u["indices"])
        self.stocks = sorted(set(p.symbol) - idx_names)
        self.indices = sorted(set(p.symbol) & idx_names)
        self.si = {s: i for i, s in enumerate(self.stocks)}
        self.ii = {s: i for i, s in enumerate(self.indices)}
        self.S = self._cube(p, self.stocks)
        self.I = self._cube(p, self.indices)
        self.member = self._membership(json.load(open(membership_json)), swap_date)
        self.sector = {s: u["stocks"].get(s, {}).get("sector", "") for s in self.stocks}
        self.sector_index = {s: u["sector_index"].get(self.sector[s], "NIFTY") for s in self.stocks}
        self.vbase = {}
        self._context()

    def _cube(self, p, names):
        q = p[p.symbol.isin(names)]
        si = pd.Index(names).get_indexer(q.symbol)
        di = self.days.get_indexer(q.day)
        bi = q.b.to_numpy()
        out = {}
        for k in ("o", "h", "l", "c", "v"):
            a = np.full((len(names), len(self.days), NB), np.nan)
            a[si, di, bi] = q[k].to_numpy(dtype=float)
            out[k] = a
        return out

    def _membership(self, m, swap_date):
        """A change is in force from its effective date's session onward (a non-trading effective date
        takes effect on the next session). Only the uncertain BSE-for-WIPRO swap moves with swap_date."""
        changes = sorted(((pd.Timestamp(swap_date if c.get("uncertain") else c["date"]), set(c["in"]), set(c["out"]))
                          for c in m["changes"]), key=lambda x: x[0])
        mem = np.zeros((len(self.stocks), len(self.days)), bool)
        for di, day in enumerate(self.days):
            cur = set(m["start_members_2021_10_01"])
            for eff, add, drop in changes:
                if eff <= day:
                    cur = (cur - drop) | add
            for s in cur:
                if s in self.si:
                    mem[self.si[s], di] = True
        return mem

    @staticmethod
    def _prev(x, present):
        """The value from the stock's previous session."""
        out = np.full_like(x, np.nan)
        for s in range(x.shape[0]):
            idx = np.nonzero(present[s])[0]
            out[s, idx[1:]] = x[s, idx[:-1]]
        return out

    @staticmethod
    def _prior_mean(x, n):
        """Mean of the previous n valid values; the session's own value is never included."""
        out = np.full_like(x, np.nan)
        for s in range(x.shape[0]):
            idx = np.nonzero(np.isfinite(x[s]))[0]
            out[s, idx] = pd.Series(x[s, idx]).rolling(n, min_periods=n).mean().shift(1).to_numpy()
        return out

    @staticmethod
    def _last(c):
        fin = np.isfinite(c)
        last = NB - 1 - np.argmax(fin[..., ::-1], axis=-1)
        return np.where(fin.any(axis=-1), np.take_along_axis(c, last[..., None], axis=-1)[..., 0], np.nan)

    def _context(self):
        o, h, l, c, v = (self.S[k] for k in ("o", "h", "l", "c", "v"))
        present = np.isfinite(c).any(axis=2)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            dH, dL = np.nanmax(h, axis=2), np.nanmin(l, axis=2)
            turn = np.nansum(c * v, axis=2) / np.isfinite(c).sum(axis=2)
        dC = self._last(c)
        self.present, self.dH, self.dL, self.dC = present, dH, dL, dC
        self.prevC, self.prevH, self.prevL = (self._prev(x, present) for x in (dC, dH, dL))
        self.hist = np.cumsum(present, axis=1) - present
        tr = np.fmax(dH - dL, np.fmax(np.abs(dH - self.prevC), np.abs(dL - self.prevC)))
        self.atr = self._prior_mean(np.where(present, tr, np.nan), 14)
        self.turn5 = self._prior_mean(np.where(present, turn, np.nan), 20)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.vwap = (np.cumsum(np.nan_to_num((h + l + c) / 3 * v), axis=2)
                         / np.cumsum(np.nan_to_num(v), axis=2))
        # Corwin-Schultz half-spread per stock and calendar year, floored at 1 bp
        years = self.days.year.to_numpy()
        self.half_spread = np.full(present.shape, np.nan)
        self.spread_table = {}
        for s in range(len(self.stocks)):
            for y in np.unique(years):
                cols = np.nonzero(years == y)[0]
                hh, ll, vv = (x[s, cols].reshape(-1) for x in (h, l, v))
                dayid = np.repeat(np.arange(len(cols)), NB)
                hs = cs_half_spread_bp(hh, ll, vv, dayid[:-1] == dayid[1:])
                if hs is None:
                    continue                                   # no candles that year (not yet listed)
                self.half_spread[s, cols] = max(hs, 1.0)
                self.spread_table[f"{self.stocks[s]} {y}"] = round(max(hs, 1.0), 2)
        # market context, for the breakdowns only
        iC = self._last(self.I["c"])
        nc = iC[self.ii["NIFTY"]]
        self.nifty_dayret = nc / np.concatenate([[np.nan], nc[:-1]]) - 1
        vx = iC[self.ii["INDIAVIX"]].copy()
        vx[~(vx > 0)] = np.nan
        prev = pd.Series(vx).shift(1)
        self.vix_high = (prev > prev.rolling(60, min_periods=40).median()).to_numpy()

    def screen(self, rb=3):
        """The screen's features per (stock, session), from candles 0 .. rb-1 and earlier sessions."""
        S, I = self.S, self.I
        o, h, l, c, v = (S[k][:, :, :rb] for k in ("o", "h", "l", "c", "v"))
        complete = np.isfinite(o).all(axis=2) & np.isfinite(c).all(axis=2)
        Vr = np.where(complete, v.sum(axis=2), np.nan)
        if rb not in self.vbase:
            self.vbase[rb] = self._prior_mean(Vr, 20)
        n = self.ii["NIFTY"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            O, H, L, P = S["o"][:, :, 0], np.nanmax(h, axis=2), np.nanmin(l, axis=2), c[:, :, rb - 1]
            vwap = ((h + l + c) / 3 * v).sum(axis=2) / v.sum(axis=2)
            r = P / O - 1
            nret = I["c"][n, :, rb - 1] / I["o"][n, :, 0] - 1
            sret = np.empty_like(r)
            fallback = 0
            for s, name in enumerate(self.stocks):
                k = self.ii.get(self.sector_index[name], n)
                x = I["c"][k, :, rb - 1] / I["o"][k, :, 0] - 1
                bad = ~np.isfinite(x)
                fallback += int((bad & complete[s] & self.member[s]).sum())
                sret[s] = np.where(bad, nret, x)               # sector index missing that day: NIFTY
            f = {"O": O, "H": H, "L": L, "P": P, "VWAP": vwap, "prevH": self.prevH, "prevL": self.prevL,
                 "or_move": (P - O) / self.atr, "gap": O / self.prevC - 1, "or_pos": (P - L) / (H - L),
                 "rvol": Vr / self.vbase[rb], "rs_nifty": r - nret[None, :], "rs_sector": r - sret,
                 "nifty_ret": np.broadcast_to(nret[None, :], r.shape)}
            f["eligible"] = (self.member & complete & (self.hist >= 20) & (self.atr > 0)
                             & np.isfinite(f["or_move"]) & np.isfinite(f["rvol"]) & np.isfinite(f["gap"]))
        f["rb"], f["sector_fallback"] = rb, fallback
        return f


# ---------------------------------------------------------------------------- the confirmation filters
def _f5(f, sd):
    return f["or_pos"] >= 0.75 if sd > 0 else f["or_pos"] <= 0.25


def _f8(f, sd):
    return f["P"] > f["prevH"] if sd > 0 else f["P"] < f["prevL"]


FILTER = {
    "F1": lambda f, sd: f["rvol"] >= 1.5,
    "F2": lambda f, sd: (f["P"] - f["VWAP"]) * sd > 0,
    "F3": lambda f, sd: f["rs_nifty"] * sd > 0,
    "F4": lambda f, sd: f["rs_sector"] * sd > 0,
    "F5": _f5,
    "F6": lambda f, sd: f["nifty_ret"] * sd > 0,
    "F7": lambda f, sd: f["gap"] * sd > 0,
    "F8": _f8,
}


# ---------------------------------------------------------------------------- one candle row per trade
def first_true(m):
    return np.where(m.any(axis=1), m.argmax(axis=1), NB)


def take(A, j):
    jj = np.clip(j, 0, NB - 1)
    return np.where(j < NB, A[np.arange(len(A)), jj], np.nan)


def take_i(A, j):
    jj = np.clip(j, 0, NB - 1)
    return np.where(j < NB, A[np.arange(len(A)), jj], NB)


def square_off(O):
    """The 15:10 candle; if it is missing, the next candle that exists (else the last one before it)."""
    fin, bars = np.isfinite(O), np.arange(NB)
    after = np.where(fin & (bars >= B1510), bars, NB).min(axis=1)
    before = np.where(fin & (bars < B1510), bars, -1).max(axis=1)
    return np.where(after < NB, after, before)


def next_valid(O):
    """next_valid(O)[r, j] = the first candle after j that exists (NB if none)."""
    idx = np.where(np.isfinite(O), np.arange(NB), NB)
    rev = np.minimum.accumulate(idx[:, ::-1], axis=1)[:, ::-1]
    return np.concatenate([rev[:, 1:], np.full((len(O), 1), NB)], axis=1)


def walk(G, i, side, entry, stop, target, sq, slip, trail=False):
    """The exit of each trade entered at candle i. On a shared candle the stop counts before the target and
    the trail. A stop on the entry candle fills at the stop; a later one at the worse of the stop and the
    candle's open (a gap through it). A target fills at its level only when traded through. The trail
    exits at the next open after a close on the wrong side of the session VWAP. What is still open squares
    off at the open of candle sq. Returns (exit candle, exit price, reason: 0 square-off, 1 stop,
    2 target, 3 trail)."""
    O, H, L, C = G["o"], G["h"], G["l"], G["c"]
    n = len(i)
    bars = np.arange(NB)[None, :]
    act = (bars >= i[:, None]) & (bars < sq[:, None]) & np.isfinite(O)
    up = (side > 0)[:, None]
    with np.errstate(invalid="ignore"):
        js = first_true(act & np.where(up, L <= stop[:, None], H >= stop[:, None]))
        jt = first_true(act & np.where(up, H > target[:, None], L < target[:, None]))
        jr = first_true(act & np.where(up, C < G["vw"], C > G["vw"])) if trail else np.full(n, NB)
    e = np.minimum(np.minimum(js, jt), jr)
    reason = np.select([e >= NB, js == e, jt == e], [0, 1, 2], default=3)
    xb = np.where(reason == 0, sq, np.where(reason == 3, take_i(next_valid(O), e), e))
    Oe = take(O, e)
    stop_px = np.where(e == i, stop, np.where(side > 0, np.fmin(Oe, stop), np.fmax(Oe, stop)))
    px = np.select([reason == 1, reason == 2], [stop_px * (1 - side * slip), target],
                   default=take(O, xb) * (1 - side * slip))
    return xb, px, reason


def s1_entry(G, side, Hr, Lr, rb, slip):
    """S1: a stop order at the range high (long) / low (short), live on the candles max(rb, 09:30) .. 11:25;
    fills at the worse of the level and the candle's open, plus slippage."""
    O, H, L = G["o"], G["h"], G["l"]
    sq = square_off(O)
    bars = np.arange(NB)[None, :]
    level = np.where(side > 0, Hr, Lr)
    win = (bars >= max(rb, B930)) & (bars <= B1125) & (bars < sq[:, None]) & np.isfinite(O)
    with np.errstate(invalid="ignore"):
        j = first_true(win & np.where((side > 0)[:, None], H >= level[:, None], L <= level[:, None]))
    Oj = take(O, j)
    entry = np.where(side > 0, np.fmax(level, Oj), np.fmin(level, Oj)) * (1 + side * slip)
    return j, entry, j < NB, sq


def s2_entry(G, side, rb, slip):
    """S2: at the open of the first candle after the range (09:30 for the 15-minute range)."""
    O = G["o"]
    sq = square_off(O)
    i = np.full(len(O), max(rb, B930))
    Oi = take(O, i)
    return i, Oi * (1 + side * slip), np.isfinite(Oi) & (i < sq), sq


def s3_entry(G, side, rb, slip):
    """S3: the first candle after the range whose low (long) touches the session VWAP; then the first later
    candle, by the 13:25 candle, that closes above the touch candle's high; entry at the next open; the stop
    is the lowest low from the touch to the signal. Shorts mirror it."""
    O, H, L, C, VW = G["o"], G["h"], G["l"], G["c"], G["vw"]
    sq = square_off(O)
    bars = np.arange(NB)[None, :]
    fin = np.isfinite(O)
    up = (side > 0)[:, None]
    with np.errstate(invalid="ignore"):
        t = first_true((bars >= max(rb, B930)) & (bars < sq[:, None]) & fin & np.where(up, L <= VW, H >= VW))
        ref = np.where(side > 0, take(H, t), take(L, t))
        u = first_true((bars > t[:, None]) & (bars <= B1325) & (bars < sq[:, None]) & fin
                       & np.where(up, C > ref[:, None], C < ref[:, None]))
    seg = (bars >= t[:, None]) & (bars <= u[:, None]) & fin
    stop = np.where(side > 0, np.where(seg, L, np.inf).min(axis=1), np.where(seg, H, -np.inf).max(axis=1))
    k = take_i(next_valid(O), u)
    entry = take(O, k) * (1 + side * slip)
    return k, entry, stop, (t < NB) & (u < NB) & (k < sq), sq


def gather(panel, s, d):
    G = {k: panel.S[k][s, d] for k in ("o", "h", "l", "c")}
    G["vw"] = panel.vwap[s, d]
    return G


def settle(panel, s, d, side, i, entry, stop, xb, px, reason, ok, cost_mult=1.0):
    """Quantity (Rs5,000 risk, at most Rs10 lakh and 1% of the 20-session mean 5-minute turnover),
    Angel One charges and the trade's R."""
    dist = np.abs(entry - stop)
    t5 = panel.turn5[s, d]
    with np.errstate(invalid="ignore", divide="ignore"):
        q = np.floor(np.fmin(np.fmin(RISK / dist, CAP_TRADE / entry), np.where(t5 > 0, 0.01 * t5 / entry, np.inf)))
        ok = ok & np.isfinite(q) & (q >= 1) & np.isfinite(px)
        q = np.where(ok, q, 0.0)
        buy = np.where(side > 0, entry, px) * q
        sell = np.where(side > 0, px, entry) * q
        fee = np.where(ok, fees(np.nan_to_num(buy), np.nan_to_num(sell)) * cost_mult, 0.0)
        gross = np.where(ok, side * (px - entry) * q, 0.0)
        risk = dist * q
        R = np.where(ok, (gross - fee) / risk, np.nan)
    return {"ok": ok, "entry_bar": i, "exit_bar": xb, "entry": entry, "stop": stop, "exit": px, "reason": reason,
            "qty": q, "notional": np.where(ok, entry * q, 0.0), "gross": gross, "fees": fee, "net": gross - fee,
            "risk": risk, "R": R}


def simulate(panel, f, s, d, side, setup, slip_bp=EXTRA_SLIP_BP, cost_mult=1.0, target_r=2.0, stop_mid=False,
             chunk=20_000):
    """Simulate `setup` on the stock-days (s, d) in direction side (arrays of the same length)."""
    parts = []
    for a in range(0, len(s), chunk):
        sl = slice(a, a + chunk)
        parts.append(_simulate(panel, f, s[sl], d[sl], side[sl], setup, slip_bp, cost_mult, target_r, stop_mid))
    if not parts:
        return {}
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def _simulate(panel, f, s, d, side, setup, slip_bp, cost_mult, target_r, stop_mid):
    G = gather(panel, s, d)
    rb = f["rb"]
    slip = (panel.half_spread[s, d] + slip_bp) * cost_mult / 1e4
    Hr, Lr = f["H"][s, d], f["L"][s, d]
    range_stop = (Hr + Lr) / 2 if stop_mid else np.where(side > 0, Lr, Hr)
    if setup == "S1":
        i, entry, ok, sq = s1_entry(G, side, Hr, Lr, rb, slip)
        stop = range_stop
    elif setup == "S2":
        i, entry, ok, sq = s2_entry(G, side, rb, slip)
        stop, target_r = range_stop, None
    elif setup == "S3":
        i, entry, stop, ok, sq = s3_entry(G, side, rb, slip)
    else:
        raise ValueError(setup)
    with np.errstate(invalid="ignore"):
        ok = ok & ((entry - stop) * side > 0)
    target = entry + side * target_r * np.abs(entry - stop) if target_r else np.full(len(s), np.nan)
    xb, px, reason = walk(G, i, side, entry, stop, target, sq, slip, trail=(setup == "S2"))
    return settle(panel, s, d, side, i, entry, stop, xb, px, reason, ok, cost_mult)


# ---------------------------------------------------------------------------- candidates, selection, the book
def pool(panel, f, setup, side, thr_min=0.25, **kw):
    """Every eligible stock-day with side x or_move >= thr_min, simulated, with its filter flags."""
    with np.errstate(invalid="ignore"):
        mv = f["or_move"] * side
        s, d = np.nonzero(f["eligible"] & (mv >= thr_min))
    sd = np.full(len(s), side)
    df = pd.DataFrame({"s": s, "d": d, "side": sd, "mv": mv[s, d], **simulate(panel, f, s, d, sd, setup, **kw)})
    with np.errstate(invalid="ignore"):
        for k, fn in FILTER.items():
            df[k] = np.asarray(fn(f, side))[s, d]
    df["stock"] = np.array(panel.stocks, dtype=object)[s]
    df["day"] = panel.days[d]
    df["gap"] = f["gap"][s, d]
    return df


def book(C):
    """The book's limits, session by session: entries in time order (screen rank breaks ties), at most 5
    open, at most Rs50 lakh of open notional, at most 5 entries. A position exiting in the candle a new
    one enters is still counted as open."""
    if C.empty:
        return C
    C = C.sort_values(["d", "entry_bar", "mv"], ascending=[True, True, False], kind="stable")
    dd, eb, xb, nt = (C[k].to_numpy() for k in ("d", "entry_bar", "exit_bar", "notional"))
    keep = np.zeros(len(C), bool)
    a = 0
    while a < len(C):
        b = a
        while b < len(C) and dd[b] == dd[a]:
            b += 1
        open_, entries = [], 0
        for r in range(a, b):
            open_ = [(x, v) for x, v in open_ if x >= eb[r]]
            if entries < MAX_ENTRIES and len(open_) < MAX_OPEN and sum(v for _, v in open_) + nt[r] <= CAP_BOOK:
                keep[r] = True
                entries += 1
                open_.append((xb[r], nt[r]))
        a = b
    return C[keep]


def select(pools, filters, n=5, thr=0.25, sides=(1, -1)):
    """pools: {side: pool DataFrame}; filters: {side: [codes]}. Threshold and filters, the n strongest per
    session and side, then the book across every side given."""
    picks = []
    for sd in sides:
        P = pools[sd]
        m = P.mv.to_numpy() >= thr
        for fl in filters[sd]:
            m &= P[fl].to_numpy()
        Q = P[m].sort_values(["d", "mv"], ascending=[True, False], kind="stable")
        picks.append(Q[(Q.groupby("d").cumcount() < n).to_numpy()])
    C = pd.concat(picks, ignore_index=True)
    return book(C[C.ok.to_numpy()])


# ---------------------------------------------------------------------------- baselines
def baseline_b1(panel, f, day_mask, slip_bp=EXTRA_SLIP_BP, cost_mult=1.0, seed=11):
    """B1: a plain two-sided opening-range breakout on every eligible member - OCO stop orders at the range
    high and low (09:30 .. 11:25), the stop at the other side, a 2R target, the 15:10 square-off; the
    first 5 triggers each session (a random draw breaks a tie within a candle). A candle that reaches
    both levels is a stopped-out trade either way; its side is the level nearer that candle's open."""
    s, d = np.nonzero(f["eligible"] & day_mask[None, :])
    parts = []
    for a in range(0, len(s), 20_000):
        ss, dd = s[a:a + 20_000], d[a:a + 20_000]
        G = gather(panel, ss, dd)
        O, H, L = G["o"], G["h"], G["l"]
        sq = square_off(O)
        bars = np.arange(NB)[None, :]
        Hr, Lr = f["H"][ss, dd], f["L"][ss, dd]
        win = (bars >= B930) & (bars <= B1125) & (bars < sq[:, None]) & np.isfinite(O)
        with np.errstate(invalid="ignore"):
            jl = first_true(win & (H >= Hr[:, None]))
            jsh = first_true(win & (L <= Lr[:, None]))
        j = np.minimum(jl, jsh)
        Oj = take(O, j)
        tie_long = (Oj >= Hr) | ((Oj > Lr) & (Hr - Oj <= Oj - Lr))
        side = np.where(jl < jsh, 1, np.where(jsh < jl, -1, np.where(tie_long, 1, -1)))
        slip = (panel.half_spread[ss, dd] + slip_bp) * cost_mult / 1e4
        level = np.where(side > 0, Hr, Lr)
        entry = np.where(side > 0, np.fmax(level, Oj), np.fmin(level, Oj)) * (1 + side * slip)
        stop = np.where(side > 0, Lr, Hr)
        with np.errstate(invalid="ignore"):
            ok = (j < NB) & ((entry - stop) * side > 0)
        target = entry + side * 2.0 * np.abs(entry - stop)
        xb, px, reason = walk(G, j, side, entry, stop, target, sq, slip)
        r = settle(panel, ss, dd, side, j, entry, stop, xb, px, reason, ok, cost_mult)
        parts.append(pd.DataFrame({"s": ss, "d": dd, "side": side, **r}))
    C = pd.concat(parts, ignore_index=True)
    C["mv"] = np.random.default_rng(seed).random(len(C))
    C = book(C[C.ok.to_numpy()])
    C["stock"] = np.array(panel.stocks, dtype=object)[C.s.to_numpy()]
    C["day"] = panel.days[C.d.to_numpy()]
    return C


def baseline_random(panel, T, draws=200, random_side=True, seed=7, slip_bp=EXTRA_SLIP_BP, cost_mult=1.0):
    """B2 (random_side) / B3 (the screen's side): for each strategy trade in T, the same stock-day, a uniformly
    random entry candle 09:30 .. 11:25 (a missing candle moves to the next one), the same stop distance, a 2R
    target, the same square-off and sizing; drawn `draws` times."""
    s, d, side0 = T.s.to_numpy(), T.d.to_numpy(), T.side.to_numpy()
    dist = np.abs(T.entry.to_numpy() - T.stop.to_numpy())
    G = gather(panel, s, d)
    O, n = G["o"], len(s)
    sq, nv = square_off(O), next_valid(O)
    slip = (panel.half_spread[s, d] + slip_bp) * cost_mult / 1e4
    rng = np.random.default_rng(seed)
    ar = np.arange(n)
    means, nets = np.zeros(draws), np.zeros(draws)
    r_sum, r_cnt = np.zeros(n), np.zeros(n)
    for k in range(draws):
        i = rng.integers(B930, B1125 + 1, size=n)
        i = np.where(np.isfinite(O[ar, i]), i, nv[ar, i])
        sd = rng.choice(np.array([-1, 1]), size=n) if random_side else side0
        entry = take(O, i) * (1 + sd * slip)
        stop = entry - sd * dist
        target = entry + sd * 2.0 * dist
        xb, px, reason = walk(G, i, sd, entry, stop, target, sq, slip)
        r = settle(panel, s, d, sd, i, entry, stop, xb, px, reason, (i < sq) & np.isfinite(entry), cost_mult)
        ok = r["ok"]
        means[k] = r["R"][ok].mean() if ok.any() else np.nan
        nets[k] = r["net"][ok].sum()
        r_sum[ok] += r["R"][ok]
        r_cnt[ok] += 1
    return {"draw_mean_R": means, "draw_net": nets,
            "trade_mean_R": np.where(r_cnt > 0, r_sum / np.maximum(r_cnt, 1), np.nan)}


# ---------------------------------------------------------------------------- measures
def period_days(panel, name):
    a, b = PERIODS[name]
    return panel.days[(panel.days >= pd.Timestamp(a)) & (panel.days <= pd.Timestamp(b))]


def in_period(T, name):
    a, b = PERIODS[name]
    return T[((T.day >= pd.Timestamp(a)) & (T.day <= pd.Timestamp(b))).to_numpy()]


def daily_net(T, days):
    if T.empty:
        return pd.Series(0.0, index=days)
    return T.groupby("day").net.sum().reindex(days, fill_value=0.0)


def summarize(T, days):
    """The pre-registered measures for the trades T over the trading days `days` (no compounding)."""
    n = len(T)
    daily = daily_net(T, days)
    eq = daily.cumsum()
    dd = float((eq - eq.cummax()).min()) if len(eq) else 0.0
    monday = days - pd.to_timedelta(days.weekday, unit="D")
    wk = daily.groupby(monday).sum() / CAPITAL * 100
    pos = float(T.net[T.net > 0].sum()) if n else 0.0
    neg = float(-T.net[T.net < 0].sum()) if n else 0.0
    sd = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sh = float(daily.mean()) / sd if sd > 0 else 0.0
    out = {"trades": n, "net": round(float(T.net.sum()), 0) if n else 0.0,
           "net_pct": round(100 * float(T.net.sum()) / CAPITAL, 2) if n else 0.0,
           "gross": round(float(T.gross.sum()), 0) if n else 0.0, "fees": round(float(T.fees.sum()), 0) if n else 0.0,
           "win_rate": round(float((T.net > 0).mean()), 4) if n else None,
           "mean_R": round(float(T.R.mean()), 4) if n else None,
           "mean_gross_R": round(float((T.gross / T.risk).mean()), 4) if n else None,
           "pf": round(pos / neg, 3) if neg > 0 else None,
           "max_dd": round(dd, 0), "max_dd_pct": round(100 * dd / CAPITAL, 2),
           "sharpe_daily": round(sh, 5), "sharpe_ann": round(sh * math.sqrt(250), 3),
           "skew": round(float(daily.skew()), 3) if sd > 0 else 0.0,
           "kurt": round(float(daily.kurt()) + 3, 3) if sd > 0 else 3.0,
           "days": len(days), "weeks": len(wk),
           "week_mean_pct": round(float(wk.mean()), 3) if len(wk) else None,
           "week_positive_share": round(float((wk > 0).mean()), 3) if len(wk) else None,
           "week_worst_pct": round(float(wk.min()), 3) if len(wk) else None,
           "week_best_pct": round(float(wk.max()), 3) if len(wk) else None,
           "weeks_at_least_2pct": int((wk >= 2).sum())}
    if n:
        out["exits"] = {REASONS[int(k)]: int(v) for k, v in T.reason.value_counts().sort_index().items()}
    return out


def vs_random(T, rnd):
    """The strategy's mean net R against the matched random draws. Two statistics, and the smaller counts:
    the draw z-score (against the spread of the draws' means) and a t whose error adds the strategy's own
    session-clustered standard error."""
    m = float(T.R.mean())
    dm = rnd["draw_mean_R"][np.isfinite(rnd["draw_mean_R"])]
    z = (m - dm.mean()) / dm.std(ddof=1)
    g = T.groupby("day").R.agg(["sum", "count"])
    G, N = len(g), float(g["count"].sum())
    se = math.sqrt(float(((g["sum"] - g["count"] * m) ** 2).sum()) / N ** 2 * G / (G - 1)) if G > 1 else float("nan")
    t = (m - dm.mean()) / math.sqrt(se ** 2 + dm.var(ddof=1) / len(dm))
    return {"mean_R": round(m, 4), "random_mean_R": round(float(dm.mean()), 4),
            "random_draw_sd": round(float(dm.std(ddof=1)), 4), "z_draws": round(float(z), 2),
            "t_clustered": round(float(t), 2), "t": round(float(min(z, t)), 2),
            "p_draws": round(float((1 + (dm >= m).sum()) / (1 + len(dm))), 4),
            "random_mean_net": round(float(rnd["draw_net"].mean()), 0)}


def deflated_sharpe(sr, T, skew, kurt, sr_var, n_trials):
    """Bailey & Lopez de Prado (2014): the probability that the true Sharpe exceeds the expected maximum of
    n_trials unskilled trials. sr in per-session units; kurt is the non-excess kurtosis."""
    nd = NormalDist()
    emc = 0.5772156649015329
    sr0 = math.sqrt(sr_var) * ((1 - emc) * nd.inv_cdf(1 - 1 / n_trials) + emc * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    return (nd.cdf((sr - sr0) * math.sqrt(T - 1) / math.sqrt(den)) if den > 0 else float("nan")), sr0
