"""Intraday engine on one-minute bars: every trade opens and closes inside one New York session.

FILLS (worst case inside a minute)
  market     at the open of the minute bar named by the rule (always a bar AFTER the one the
             decision was read from: no look-ahead);
  stop entry at the level when a minute's high (low) reaches it, or at the minute's open if it
             gapped past;
  limit      at the level when touched, or at the open if it opened beyond it (a better price);
  stop-loss  at the level, or at the open if the minute opened beyond it; a stop touched in the
             minute a stop/limit entry filled counts against the trade;
  target     at the level (or a better open); never in the minute the entry filled inside;
             a stop and a target touched in the same minute -> the stop;
  time exit  at the close of the last minute of the trade's window.
No position is held across 17:00 New York, so there is no overnight financing.

COSTS per round trip, on mid prices: spread (half each side), slippage each side, commission each
side; C3 charges the spread Dukascopy actually quoted in the entry and exit hours.
LEVERAGE: an account at leverage L gains L x the trade's unlevered net return; costs scale with it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Costs:
    name: str
    spread: float
    slippage: float
    commission: float
    measured: bool = False


COSTS = {
    "C1": Costs("C1 base: spread $0.40, slippage $0.10 a side, commission $0.035/oz a side (intraday: no financing)", 0.40, 0.10, 0.035),
    "C2": Costs("C2 harsh: spread $0.50, slippage $0.25 a side, commission $0.05/oz a side", 0.50, 0.25, 0.05),
    "C3": Costs("C3 measured: Dukascopy's quoted spread in the entry and exit hours + C1 slippage and commission", 0.40, 0.10, 0.035, True),
}


def first_true(a: np.ndarray) -> int:
    """Index of the first True, or len(a) if none."""
    if a.size == 0:
        return 0
    i = int(np.argmax(a))
    return i if a[i] else a.size


def stop_entry(D: dict, a: int, b: int, buy: float, sell: float):
    """First fill of a buy-stop / sell-stop pair over minutes [a, b] -> (index, side, price, inside) or None."""
    if b < a:
        return None
    h, l, o = D["h"][a:b + 1], D["l"][a:b + 1], D["o"][a:b + 1]
    ib = first_true(h >= buy) if buy == buy else h.size
    is_ = first_true(l <= sell) if sell == sell else h.size
    if ib == h.size and is_ == h.size:
        return None
    if ib == is_:                                   # both in one minute: the one nearer the open
        ib, is_ = (ib, h.size) if (buy - o[ib]) <= (o[ib] - sell) else (h.size, is_)
    if ib < is_:
        px = max(o[ib], buy)
        return a + ib, 1, px, not (o[ib] >= buy)
    px = min(o[is_], sell)
    return a + is_, -1, px, not (o[is_] <= sell)


def limit_entry(D: dict, a: int, b: int, buy_lim: float, sell_lim: float):
    """First fill of a buy-limit below / sell-limit above over [a, b] -> (index, side, price, inside) or None."""
    if b < a:
        return None
    h, l, o = D["h"][a:b + 1], D["l"][a:b + 1], D["o"][a:b + 1]
    ib = first_true(l <= buy_lim) if buy_lim == buy_lim else h.size
    is_ = first_true(h >= sell_lim) if sell_lim == sell_lim else h.size
    if ib == h.size and is_ == h.size:
        return None
    if ib == is_:
        ib, is_ = (ib, h.size) if (o[ib] - buy_lim) <= (sell_lim - o[ib]) else (h.size, is_)
    if ib < is_:
        return a + ib, 1, min(o[ib], buy_lim), not (o[ib] <= buy_lim)
    return a + is_, -1, max(o[is_], sell_lim), not (o[is_] >= sell_lim)


def run_exit(D: dict, side: int, ei: int, ep: float, stop: float, target: float, last: int, inside: bool,
             be_trigger: float = np.nan):
    """Exit of a trade entered at minute ei (inside that minute if `inside`), held to `last` at most.
    Returns (exit index, exit price, reason)."""
    o, h, l, c = D["o"][ei:last + 1], D["h"][ei:last + 1], D["l"][ei:last + 1], D["c"][ei:last + 1]
    n = h.size
    if n == 0:
        return ei, ep, "none"
    if side == 1:
        s_hit = (l <= stop) if stop == stop else np.zeros(n, bool)
        t_hit = (h >= target) if target == target else np.zeros(n, bool)
    else:
        s_hit = (h >= stop) if stop == stop else np.zeros(n, bool)
        t_hit = (l <= target) if target == target else np.zeros(n, bool)
    if inside:
        t_hit = t_hit.copy()
        t_hit[0] = False
    js = first_true(s_hit)
    s_lvl = stop
    if be_trigger == be_trigger:
        be = (h >= be_trigger) if side == 1 else (l <= be_trigger)
        k = first_true(be)
        if k < n - 1:
            rest = (l[k + 1:] <= ep) if side == 1 else (h[k + 1:] >= ep)
            j2 = first_true(rest)
            if j2 < rest.size and (k + 1 + j2) < js:
                js, s_lvl = k + 1 + j2, ep
    jt = first_true(t_hit)
    if js < n and js <= jt:
        if js == 0 and inside:
            px = s_lvl
        else:
            px = min(o[js], s_lvl) if side == 1 else max(o[js], s_lvl)
        return ei + js, px, "stop"
    if jt < n:
        px = max(o[jt], target) if side == 1 else min(o[jt], target)
        return ei + jt, px, "target"
    return last, c[-1], "time"


def trades_frame(D: dict, rows: list[tuple]) -> pd.DataFrame:
    cols = ["day", "side", "ei", "ep", "xi", "xp", "reason"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["date"] = D["sess_date"][df["day"].values]
    df["gross"] = df["side"] * (df["xp"] / df["ep"] - 1.0)
    df["minutes"] = ((D["t"][df["xi"].values] - D["t"][df["ei"].values]) // 60).astype(int)
    return df


def net_returns(D: dict, tf: pd.DataFrame, c: Costs) -> np.ndarray:
    if tf.empty:
        return np.array([])
    side = tf["side"].values
    if c.measured:
        adv_in = D["spread"][tf["ei"].values] / 2 + c.slippage
        adv_out = D["spread"][tf["xi"].values] / 2 + c.slippage
    else:
        adv_in = adv_out = c.spread / 2 + c.slippage
    ef = tf["ep"].values + side * adv_in
    xf = tf["xp"].values - side * adv_out
    return (side * (xf - ef) - 2 * c.commission) / ef


def stats(r: np.ndarray) -> dict:
    n = len(r)
    if n == 0:
        return {"trades": 0}
    w, ls = r[r > 0], r[r < 0]
    streak = best = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    sd = r.std(ddof=1) if n > 1 else np.nan
    return {"trades": n, "avg": float(r.mean()), "median": float(np.median(r)), "win_rate": float(len(w) / n),
            "avg_win": float(w.mean()) if len(w) else np.nan, "avg_loss": float(ls.mean()) if len(ls) else np.nan,
            "profit_factor": float(w.sum() / -ls.sum()) if len(ls) and ls.sum() < 0 else (np.inf if len(w) else np.nan),
            "t_stat": float(r.mean() / (sd / np.sqrt(n))) if n > 1 and sd > 0 else np.nan,
            "longest_losing_streak": int(best), "sd": float(sd) if sd == sd else None}


def account(r: np.ndarray, dates: np.ndarray, lev: float, start: str, end: str) -> dict:
    """The account at leverage `lev`: compounding trade by trade; ruin when a trade takes it to zero."""
    years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1e-9)
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    ruined = None
    path = []
    for x, d in zip(r, dates):
        eq *= max(1.0 + lev * x, 0.0)
        path.append((d, eq))
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1.0)
        if eq <= 0:
            ruined = str(d)[:10]
            break
    total = eq - 1.0
    cagr = (eq ** (1 / years) - 1) if eq > 0 else -1.0
    return {"leverage": lev, "total_return": total, "cagr": cagr, "max_drawdown": mdd, "ruined_on": ruined,
            "avg_per_trade": float(lev * r.mean()) if len(r) else None, "path": path}
