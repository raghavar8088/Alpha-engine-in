"""Trade simulator for imported strategies: signals in, trades out, walked on 1-minute bars with honest costs.

It follows the conventions of the repository's crypto intraday harness (antigravity engine/research/
crypto_intraday20_2026_11/ci_core.py: signal on a CLOSED bar, entry at the next 1-minute open, exits walked minute by
minute, a minute that opens beyond a level fills at that open, a minute that reaches both stop and target takes the
stop, costs per leg, signed funding inside the holding period) and adds freqtrade's exit model, because the
freqtrade strategies define their exits with it:

  minimal_roi   {minutes since entry: ratio}; the ratio in force is the one with the largest key <= elapsed minutes.
                As in freqtrade it is a NET profit ratio after the entry and exit fee:
                exit price >= entry * (1 + fee) * (1 + roi) / (1 - fee). -1 disables it.
  stoploss      a PRICE level, entry * (1 + stoploss) (long), as freqtrade sets it.
  trailing_stop trailing_stop_positive (+ offset, only after the offset is reached if trailing_only_offset_is_reached)
                or, without it, the stoploss distance below the highest price. The level is raised with the highs of
                EARLIER minutes only (freqtrade's backtester raises it with the same candle's high first; that order
                is optimistic and not used here).
  exit signal   exit_long on a candle (and no entry signal on it) closes at the next candle's open; with
                exit_profit_only only when the net profit then is above exit_profit_offset.
One position at a time per pair; a signal inside a position is ignored; entries on a filled (volume 0) candle are
skipped. A position open at the end of the data closes at the last minute's close ("END").

Costs (COSTS): fee + slippage per leg on the notional, $10,000 per trade, no leverage, no compounding. Funding (perp
profile only): Binance USDT-M prints strictly inside the holding period, signed (a long pays positive funding).

    python -I ws_engine.py <signals dir> <Class> [pair] [profile]      (prints one run; the study driver is ws_run.py)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HIST = Path(r"D:\INDIAN MARKET\antigravity-main\antigravity-main\engine\data\historical")
CACHE = Path(r"D:\Strategy-Web-Sources\minute_cache")
NOTIONAL = 10_000.0


@dataclass(frozen=True)
class Cost:
    name: str
    fee: float
    slip: float
    funding: bool
    label: str
    abs_side: float = 0.0                 # $ per unit (ounce) per side, on top of the fractional fee/slippage
    fin_long_add: float | None = None     # CFD financing a year: long pays T-bill + this; None = no financing
    fin_short_add: float | None = None    # short pays this - T-bill (negative = receives)


GOLD_DIR = Path(r"D:\INDIAN MARKET\backend\research")
COSTS_GOLD = {
    # the repository's gold cost model (backend/research/xauusd_2026_10 xa_engine C1, xauusd_intraday xi_engine C1)
    "gold": Cost("gold", 0.0, 0.0, False, "XAUUSD CFD: spread $0.40 (half a side) + slippage $0.10 a side + commission "
                 "$0.035/oz a side + overnight financing (long T-bill + 0.5% a year, short 1.5% - T-bill)",
                 abs_side=0.20 + 0.10 + 0.035, fin_long_add=0.005, fin_short_add=0.015),
    "gold_x2": Cost("gold_x2", 0.0, 0.0, False, "stress: twice the gold trading costs, same financing",
                    abs_side=2 * (0.20 + 0.10 + 0.035), fin_long_add=0.005, fin_short_add=0.015),
}

COSTS = {
    "spot": Cost("spot", 0.0010, 0.0002, False, "Binance spot taker 0.10% a side + 2 bp slippage a side (original market)"),
    "perp": Cost("perp", 0.00059, 0.0002, True,
                 "Delta India taker 0.05% + 18% GST = 5.9 bp a side + 2 bp slippage + Binance USDT-M funding (adaptation)"),
    "spot_x2": Cost("spot_x2", 0.0020, 0.0004, False, "stress: twice the spot costs"),
}


class Minutes:
    """1-minute OHLC of one pair (cached as npz) and its funding prints."""

    def __init__(self, pair: str):
        CACHE.mkdir(parents=True, exist_ok=True)
        p = CACHE / f"{pair.replace('/', '_')}.npz"
        if not p.exists():
            if pair == "BTC/USDT":
                df = pd.read_csv(HIST / "deep" / "BTCUSDT_1m.csv", usecols=["time", "open", "high", "low", "close"])
                t = df["time"].to_numpy(np.int64)
            else:
                df = pd.DataFrame(json.loads((HIST / f"{pair.replace('/', '')}_1m.json").read_text()))
                t = df["time"].to_numpy(np.int64)
            order = np.argsort(t, kind="stable")
            np.savez(p, t=t[order], o=df["open"].to_numpy(float)[order], h=df["high"].to_numpy(float)[order],
                     l=df["low"].to_numpy(float)[order], c=df["close"].to_numpy(float)[order])
        z = np.load(p)
        self.t, self.o, self.h, self.l, self.c = z["t"], z["o"], z["h"], z["l"], z["c"]
        self.n = len(self.t)
        self.fund_t = np.zeros(0, np.int64)
        self.fund_r = np.zeros(0)
        if pair == "BTC/USDT":
            f = pd.read_csv(HIST / "deep" / "BTCUSDT_funding.csv")
            self.fund_t, self.fund_r = f["time"].to_numpy(np.int64), f["rate"].to_numpy(float)

    def at(self, ts: int) -> int:
        """Index of the first minute starting at or after ts."""
        return int(np.searchsorted(self.t, ts, side="left"))


class GoldMinutes(Minutes):
    """XAUUSD one-minute MID prices of the repository's intraday gold study (xauusd_intraday_2026_10/data/minute.npz:
    HistData = Dukascopy bid + half the quoted spread, UTC times, 2009-03 .. 2026-10) and the daily T-bill rate of the
    position study (xauusd_2026_10/data/bars.pkl 'rate', Yahoo ^IRX, decimal a year) for CFD financing."""

    def __init__(self):  # noqa: D107  (no crypto files)
        z = np.load(GOLD_DIR / "xauusd_intraday_2026_10" / "data" / "minute.npz")
        self.t, self.o, self.h, self.l, self.c = z["t"], z["o"], z["h"], z["l"], z["c"]
        self.n = len(self.t)
        self.fund_t, self.fund_r = np.zeros(0, np.int64), np.zeros(0)
        rate = pd.read_pickle(GOLD_DIR / "xauusd_2026_10" / "data" / "bars.pkl")["rate"]
        self.rate_days = np.array([d.toordinal() for d in rate.index.date])
        self.rate_cum = np.concatenate([[0.0], np.cumsum(rate.to_numpy(float))])

    @staticmethod
    def session_ordinal(ts: int) -> int:
        """The New York session (rolling at 17:00 New York) a UTC time belongs to, as a date ordinal."""
        ny = pd.Timestamp(ts, unit="s", tz="UTC").tz_convert("America/New_York") + pd.Timedelta(hours=7)
        return ny.date().toordinal()

    def financing(self, side: int, t0: int, t1: int, cost: Cost) -> float:
        """Financing as a fraction of the notional for the calendar nights between the entry and exit sessions."""
        if cost.fin_long_add is None:
            return 0.0
        a, b = self.session_ordinal(t0), self.session_ordinal(t1)
        nights = b - a
        if nights <= 0:
            return 0.0
        ia = int(np.clip(np.searchsorted(self.rate_days, a), 0, len(self.rate_days) - 1))
        ib = int(np.clip(np.searchsorted(self.rate_days, b), ia + 1, len(self.rate_days)))
        avg = (self.rate_cum[ib] - self.rate_cum[ia]) / max(ib - ia, 1)
        ann = (avg + cost.fin_long_add) if side > 0 else (cost.fin_short_add - avg)
        return ann * nights / 365.0


def roi_table(s: dict) -> tuple[np.ndarray, np.ndarray]:
    items = sorted((int(float(k)), float(v)) for k, v in (s.get("minimal_roi") or {}).items())
    if not items:
        return np.array([0]), np.array([-1.0])
    return np.array([k for k, _ in items]), np.array([v for _, v in items])


def simulate(sig: dict, s: dict, m: Minutes, cost: Cost, start: int, end: int, allow_short: bool | None = None,
             stop_scale: float = 1.0, roi_scale: float = 1.0) -> list[dict]:
    tf = int(sig["tf"]) * 60
    t = sig["t"].astype(np.int64)
    known = t + tf                                   # when a candle's signal is known (its close)
    el, xl = sig["enter_long"].astype(bool), sig["exit_long"].astype(bool)
    es, xs = sig["enter_short"].astype(bool), sig["exit_short"].astype(bool)
    filled = sig["filled"].astype(bool)
    shorts = bool(s.get("can_short")) if allow_short is None else allow_short
    both = el & es
    ent_long = el & ~both & ~filled
    ent_short = (es & ~both & ~filled) if shorts else np.zeros_like(es)
    use_exit = s.get("use_exit_signal", True) is not False
    exit_long_t = known[xl & ~el] if use_exit else np.zeros(0, np.int64)
    exit_short_t = known[xs & ~es] if use_exit else np.zeros(0, np.int64)
    roi_k, roi_v = roi_table(s)
    roi_v = np.where(roi_v < 0, roi_v, roi_v * roi_scale)
    sl = float(s.get("stoploss") or -1.0) * stop_scale
    trail = bool(s.get("trailing_stop"))
    tsp = s.get("trailing_stop_positive")
    tso = float(s.get("trailing_stop_positive_offset") or 0.0)
    only_off = bool(s.get("trailing_only_offset_is_reached"))
    profit_only = bool(s.get("exit_profit_only"))
    profit_off = float(s.get("exit_profit_offset") or 0.0)
    f, sp = cost.fee, cost.slip
    # every exit signal's minute index, found once per run (a trade then only moves a pointer)
    xk_long = np.searchsorted(m.t, exit_long_t, side="left").astype(np.int64)
    xk_short = np.searchsorted(m.t, exit_short_t, side="left").astype(np.int64)
    idx = np.flatnonzero(ent_long | ent_short)
    idx = idx[(known[idx] >= start) & (known[idx] < end)]
    out, busy = [], -1
    for i in idx:
        T0 = int(known[i])
        if T0 < busy:
            continue
        side = 1 if ent_long[i] else -1
        k0 = m.at(T0)
        if k0 >= m.n or m.t[k0] - T0 > tf:          # no minute data soon enough after the signal: no trade
            continue
        P0 = m.o[k0]
        xt_sig = exit_long_t if side > 0 else exit_short_t
        stop0 = P0 * (1 + sl) if side > 0 else P0 * (1 - sl)
        exit_k, exit_px, why = None, None, None
        # exit signals after the entry, in order (their minute indices); with exit_profit_only the first in profit
        sig_k = xk_long if side > 0 else xk_short
        sig_ptr = int(np.searchsorted(xt_sig, T0, side="right"))
        kcur, hwm_prev = k0, P0
        CH = 240                                         # minutes walked per step, doubling while the trade is open
        last_k = min(m.n - 1, m.at(end + 30 * 86400))   # an open trade may run past the window end, to its exit
        while exit_k is None and kcur <= last_k:
            kend = min(kcur + CH, last_k + 1)
            CH = min(CH * 2, 40_000)
            o, h, l = m.o[kcur:kend], m.h[kcur:kend], m.l[kcur:kend]
            mt = m.t[kcur:kend]
            el_min = (mt - T0) // 60
            # the ROI in force has the largest key <= elapsed minutes; before the first key there is none (-1),
            # as in freqtrade (a table that starts at "10" has no ROI exit in the first 10 minutes)
            ri = np.searchsorted(roi_k, el_min, side="right") - 1
            r = np.where(ri >= 0, roi_v[np.maximum(ri, 0)], -1.0)
            if side > 0:
                tgt = np.where(r < 0, np.inf, P0 * (1 + f) * (1 + r) / (1 - f))
                hw = np.maximum.accumulate(np.concatenate([[hwm_prev], h[:-1]]))
                hw = np.maximum(hw, hwm_prev)
                stop = np.full(len(o), stop0)
                if trail:
                    if tsp is None:
                        stop = np.maximum(stop, hw * (1 + sl))
                    else:
                        on = (hw / P0 - 1 >= tso) if only_off else np.ones(len(o), bool)
                        stop = np.where(on, np.maximum(stop, hw * (1 - float(tsp))), stop)
                gap_s, hit_s = o <= stop, l <= stop
                gap_t, hit_t = o >= tgt, h >= tgt
            else:
                tgt = np.where(r < 0, -np.inf, P0 * (1 - f) * (1 - r) / (1 + f))
                lw = np.minimum.accumulate(np.concatenate([[hwm_prev], l[:-1]]))
                lw = np.minimum(lw, hwm_prev)
                stop = np.full(len(o), stop0)
                if trail:
                    if tsp is None:
                        stop = np.minimum(stop, lw * (1 - sl))
                    else:
                        on = (1 - lw / P0 >= tso) if only_off else np.ones(len(o), bool)
                        stop = np.where(on, np.minimum(stop, lw * (1 + float(tsp))), stop)
                gap_s, hit_s = o >= stop, h >= stop
                gap_t, hit_t = o <= tgt, l <= tgt
            if kcur == k0:
                gap_s[0] = gap_t[0] = False           # the entry minute's open is the fill itself
            # exit-signal minutes inside this chunk
            sx = np.zeros(len(o), bool)
            while sig_ptr < len(sig_k) and sig_k[sig_ptr] < kend:
                kk = int(sig_k[sig_ptr])
                if kk >= kcur and kk > k0:
                    px = m.o[kk]
                    net = side * (px - P0) / P0 - 2 * f
                    if not profit_only or net > profit_off:
                        sx[kk - kcur] = True
                sig_ptr += 1
            hit = sx | gap_s | hit_s | gap_t | hit_t
            if hit.any():
                q = int(np.argmax(hit))
                exit_k = kcur + q
                if sx[q]:
                    exit_px, why = o[q], "EXIT_SIGNAL"
                elif gap_s[q]:
                    exit_px, why = o[q], "STOP"
                elif hit_s[q]:
                    exit_px, why = stop[q], ("TRAIL" if trail and stop[q] != stop0 else "STOP")
                elif gap_t[q]:
                    exit_px, why = o[q], "ROI"
                else:
                    exit_px, why = tgt[q], "ROI"
                break
            if side > 0:
                hwm_prev = max(hwm_prev, float(h.max()))
            else:
                hwm_prev = min(hwm_prev, float(l.min()))
            kcur = kend
        if exit_k is None:
            exit_k, exit_px, why = last_k, m.c[last_k], "END"
        xt = int(m.t[exit_k]) + (60 if why in ("STOP", "TRAIL", "ROI") and exit_px not in (m.o[exit_k],) else 0)
        gross = side * (exit_px - P0) / P0
        fund = 0.0
        if cost.funding and len(m.fund_t):
            sel = (m.fund_t > T0) & (m.fund_t < xt)
            fund = side * float(m.fund_r[sel].sum())
        if isinstance(m, GoldMinutes):
            fund = m.financing(side, T0, xt, cost)          # CFD overnight financing (gold)
        net = gross - 2 * (f + sp) - 2 * cost.abs_side / P0 - fund
        out.append({"side": side, "entry_t": T0, "exit_t": xt, "entry": float(P0), "exit": float(exit_px), "why": why,
                    "gross": gross, "funding": fund, "net": net, "pnl": net * NOTIONAL,
                    "hold_min": (xt - T0) / 60})
        busy = xt
    return out


def stats(trades: list[dict], start: int, end: int) -> dict:
    tr = [x for x in trades if start <= x["entry_t"] < end]
    n = len(tr)
    if not n:
        return {"trades": 0}
    pnl = np.array([x["pnl"] for x in tr])
    eq = NOTIONAL + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[NOTIONAL], eq]))[1:]
    dd = max(float(((eq - peak) / peak).min()), -1.0)           # an account cannot lose more than all of it
    ruin = int(np.argmax(eq <= 0)) if (eq <= 0).any() else None   # a $10,000 account would be empty from here
    wins = pnl > 0
    gp, gl = float(pnl[wins].sum()), float(-pnl[~wins].sum())
    years = (end - start) / (365.25 * 86400)
    hold = np.array([x["hold_min"] for x in tr])
    return {"trades": n, "net": float(pnl.sum()), "ret_pct": float(pnl.sum() / NOTIONAL * 100),
            "win_rate": float(wins.mean() * 100), "pf": (gp / gl) if gl > 0 else None, "max_dd_pct": dd * 100,
            "exp_usd": float(pnl.mean()), "exp_pct": float(np.mean([x["net"] for x in tr]) * 100),
            "gross_pct": float(np.mean([x["gross"] for x in tr]) * 100), "funding_pct": float(np.mean([x["funding"] for x in tr]) * 100),
            "avg_hold_min": float(hold.mean()), "trades_per_year": n / years if years > 0 else None,
            "exposure_pct": float(hold.sum() * 60 / (end - start) * 100),
            "by_reason": {k: int(sum(1 for x in tr if x["why"] == k)) for k in sorted({x["why"] for x in tr})},
            "ruined_on": (pd.Timestamp(tr[ruin]["exit_t"], unit="s", tz="UTC").date().isoformat() if ruin is not None else None),
            # no t-stat when every trade made the same (a stop-only record): the ratio is meaningless
            "t_stat": float(pnl.mean() / (pnl.std(ddof=1) / np.sqrt(n))) if n > 2 and pnl.std(ddof=1) > 1e-6 * max(1.0, abs(pnl.mean())) else None}


def load_signals(sigdir: Path, name: str, pair: str) -> tuple[dict, dict]:
    s = json.loads((sigdir / f"{name}.settings.json").read_text(encoding="utf-8"))
    fut = str(s.get("mode", "")).startswith("futures")
    p = pair + ":USDT" if fut and ":" not in pair else pair
    z = np.load(sigdir / f"{name}__{p.replace('/', '_').replace(':', '_')}.npz")
    return {k: z[k] for k in z.files}, s


if __name__ == "__main__":
    a = sys.argv[1:]
    sigdir, name = Path(a[0]), a[1]
    pair = a[2] if len(a) > 2 else "BTC/USDT"
    prof = COSTS[a[3] if len(a) > 3 else "spot"]
    sig, s = load_signals(sigdir, name, pair)
    m = Minutes(pair)
    st, en = int(pd.Timestamp("2018-01-01", tz="UTC").timestamp()), int(pd.Timestamp("2026-10-31", tz="UTC").timestamp())
    tr = simulate(sig, s, m, prof, st, en)
    print(json.dumps(stats(tr, st, en), indent=1))
