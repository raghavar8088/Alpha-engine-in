"""Backtest engine: daily decisions, hourly execution, one position at a time, costs applied per trade.

TIMING (no look-ahead)
  Every decision is made at a session's CLOSE (~17:00 New York) from bars up to and including
  that session. It is acted on in the NEXT session:
    market orders  fill at the next session's first hourly OPEN (~18:00 New York);
    stop entries   (breakouts) are working orders for the next session: they fill when an hourly
                   bar trades through the level - at the level, or at the bar's open if it gaps past;
    exits          signal exits fill at the next open; stops, trailing stops and targets are checked
                   hour by hour inside each session.
  Within one hour the order of the high and the low is unknown, so the engine assumes the WORST:
  a stop and a target touched in the same hour -> the stop; a stop touched in the hour a stop-entry
  filled -> stopped in that hour. A trailing stop moves only at a session close, from that session on.

PRICES are mid prices (bid + ask) / 2. Costs (spread, slippage, commission, financing) are added
per trade by `net_returns`, so one simulation serves every cost scenario.

POSITION SIZE is 1x notional: each trade puts the whole equity into gold, unlevered, so a trade's
return is the percentage move it captured, net of costs. Equity compounds trade to trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ── market context ──────────────────────────────────────────────────────────────


@dataclass
class Market:
    d_date: np.ndarray          # datetime64[D] per session
    d_o: np.ndarray
    d_h: np.ndarray
    d_l: np.ndarray
    d_c: np.ndarray
    h_t: np.ndarray             # int64 epoch seconds, hour start (UTC)
    h_o: np.ndarray
    h_h: np.ndarray
    h_l: np.ndarray
    h_c: np.ndarray
    h_ny_hour: np.ndarray       # New York clock hour of each bar (0-23)
    s_start: np.ndarray         # first hourly index of each session
    s_end: np.ndarray           # one past the last hourly index of each session
    rate: pd.Series             # financing rate per calendar day (decimal a year)
    h_sp: np.ndarray = field(repr=False, default=None)   # quoted spread of each hour (the wider of open and close), USD
    D: pd.DataFrame = field(repr=False, default=None)
    H: pd.DataFrame = field(repr=False, default=None)

    @classmethod
    def from_bars(cls, bars: dict) -> "Market":
        D, H = bars["D"], bars["H"]
        sess = H["session"].values.astype("datetime64[D]")
        d_date = D.index.values.astype("datetime64[D]")
        pos = np.searchsorted(d_date, sess)
        assert (d_date[pos] == sess).all()
        s_start = np.searchsorted(pos, np.arange(len(d_date)), side="left")
        s_end = np.searchsorted(pos, np.arange(len(d_date)), side="right")
        ny_hour = H.index.tz_convert("America/New_York").hour.values
        return cls(d_date=d_date, d_o=D["o"].values, d_h=D["h"].values, d_l=D["l"].values, d_c=D["c"].values,
                   h_t=H.index.values.astype("datetime64[s]").astype(np.int64), h_o=H["o"].values, h_h=H["h"].values,
                   h_l=H["l"].values, h_c=H["c"].values, h_ny_hour=ny_hour, s_start=s_start, s_end=s_end,
                   rate=bars["rate"], h_sp=np.maximum(H["spread"].values, H["spread_o"].values), D=D, H=H)

    def session_index(self, day: str) -> int:
        """First session on or after `day`."""
        return int(np.searchsorted(self.d_date, np.datetime64(day, "D"), side="left"))


# ── the plan a strategy hands the engine ────────────────────────────────────────


@dataclass
class Plan:
    """Arrays are per session d and describe what to do in session d+1, from data through d."""
    long_entry: np.ndarray | None = None     # bool: buy at the next open
    short_entry: np.ndarray | None = None
    buy_stop: np.ndarray | None = None       # float level: buy-stop working during the next session (nan = none)
    sell_stop: np.ndarray | None = None
    long_exit: np.ndarray | None = None      # bool: leave a long at the next open
    short_exit: np.ndarray | None = None
    stop_dist: np.ndarray | None = None      # initial protective stop distance, price units, fixed at the signal session
    tp_dist: np.ndarray | None = None        # take-profit distance
    exit_level_long: np.ndarray | None = None   # e.g. Turtle's 10-day low: a long is stopped if price trades below it next session
    exit_level_short: np.ndarray | None = None
    trail: tuple | None = None               # ("chandelier", k, atr) | ("close_atr", k, atr) | ("sar", af0, af_step, af_max)
    max_hold: int | None = None              # sessions; leave at the open after this many sessions held
    reverse: bool = False                    # an opposite entry signal while in a trade closes it and opens the other side
    state: bool = False                      # entries are a desired position re-asserted every session
    oco: bool = False                        # buy_stop and sell_stop on the same session cancel each other
    buy_from_open: np.ndarray | None = None  # buy-stop at the next session's OPEN + this offset (Williams)
    sell_from_open: np.ndarray | None = None # sell-stop at the next session's open - this offset
    bailout: bool = False                    # leave at the first session open that shows a profit (Williams)


@dataclass
class Trade:
    side: int
    entry_session: int
    entry_hour: int
    entry_px: float
    exit_session: int
    exit_hour: int
    exit_px: float
    reason: str


def run(m: Market, plan: Plan, first: int, last: int) -> list[Trade]:
    """Trades whose ENTRY falls in sessions [first, last]; anything open is closed at last's close.
    Signals from the session before `first` may act at first's open."""
    nd = len(m.d_date)
    last = min(last, nd - 1)
    trades: list[Trade] = []
    pos = 0
    entry_s = entry_h = 0
    entry_px = stop = tp = np.nan
    hi_since = lo_since = np.nan
    sar = ep = af = np.nan
    trail = plan.trail
    max_hold = plan.max_hold

    def arr(a, d, default=False):
        return a[d] if a is not None else default

    for d in range(max(first, 1), last + 1):
        p = d - 1                                   # the decision session
        hs, he = m.s_start[d], m.s_end[d]
        if hs >= he:
            continue
        # ---- at the open of session d ----
        want_long = bool(arr(plan.long_entry, p)) and d <= last
        want_short = bool(arr(plan.short_entry, p)) and d <= last
        exit_now = False
        if pos == 1 and (bool(arr(plan.long_exit, p)) or (plan.reverse and want_short)):
            exit_now = True
        elif pos == -1 and (bool(arr(plan.short_exit, p)) or (plan.reverse and want_long)):
            exit_now = True
        reason = "signal"
        if pos != 0 and max_hold is not None and (d - entry_s) >= max_hold:
            exit_now, reason = True, "time"
        if pos != 0 and plan.bailout and d > entry_s and pos * (m.h_o[hs] - entry_px) > 0:
            exit_now, reason = True, "bailout"
        if exit_now:
            trades.append(Trade(pos, entry_s, entry_h, entry_px, d, hs, m.h_o[hs], reason))
            pos = 0
        if pos == 0 and (want_long or want_short) and not (want_long and want_short):
            side = 1 if want_long else -1
            pos, entry_s, entry_h, entry_px = side, d, hs, m.h_o[hs]
            sd = arr(plan.stop_dist, p, np.nan)
            td = arr(plan.tp_dist, p, np.nan)
            stop = entry_px - side * sd if sd == sd else np.nan
            tp = entry_px + side * td if td == td else np.nan
            hi_since, lo_since = m.h_h[hs], m.h_l[hs]
            sar = ep = af = np.nan
            if trail is not None and trail[0] == "sar":
                sar = m.d_l[p] if side == 1 else m.d_h[p]
                ep, af = (m.d_h[p] if side == 1 else m.d_l[p]), trail[1]
                if stop != stop:
                    stop = sar
        bstop = arr(plan.buy_stop, p, np.nan) if pos == 0 and d <= last else np.nan
        sstop = arr(plan.sell_stop, p, np.nan) if pos == 0 and d <= last else np.nan
        if pos == 0 and plan.buy_from_open is not None:
            off = plan.buy_from_open[p]
            bstop = m.h_o[hs] + off if off == off else np.nan
        if pos == 0 and plan.sell_from_open is not None:
            off = plan.sell_from_open[p]
            sstop = m.h_o[hs] - off if off == off else np.nan
        xl = arr(plan.exit_level_long, p, np.nan)
        xs = arr(plan.exit_level_short, p, np.nan)
        # ---- inside session d, hour by hour (only when something can happen) ----
        need = (pos != 0 and (stop == stop or tp == tp or xl == xl or xs == xs)) or (pos == 0 and (bstop == bstop or sstop == sstop))
        if need:
            for i in range(hs, he):
                o, h, l = m.h_o[i], m.h_h[i], m.h_l[i]
                filled_now = False
                if pos == 0 and (bstop == bstop or sstop == sstop):
                    hit_b = bstop == bstop and h >= bstop
                    hit_s = sstop == sstop and l <= sstop
                    if hit_b and hit_s:            # both sides in one hour: take the one nearer the open
                        hit_b = (bstop - o) <= (o - sstop)
                        hit_s = not hit_b
                    if hit_b or hit_s:
                        side = 1 if hit_b else -1
                        lvl = bstop if hit_b else sstop
                        px = max(o, lvl) if side == 1 else min(o, lvl)
                        pos, entry_s, entry_h, entry_px = side, d, i, px
                        sd = arr(plan.stop_dist, p, np.nan)
                        td = arr(plan.tp_dist, p, np.nan)
                        stop = px - side * sd if sd == sd else np.nan
                        tp = px + side * td if td == td else np.nan
                        hi_since, lo_since = h, l
                        sar = ep = af = np.nan
                        if trail is not None and trail[0] == "sar":
                            sar = m.d_l[p] if side == 1 else m.d_h[p]
                            ep, af = (m.d_h[p] if side == 1 else m.d_l[p]), trail[1]
                            if stop != stop:
                                stop = sar
                        bstop = sstop = np.nan
                        filled_now = True
                if pos == 0:
                    continue
                # protective level: the tighter of the stop and the exit level
                if pos == 1:
                    lvl = stop
                    if xl == xl and (lvl != lvl or xl > lvl):
                        lvl = xl
                    if lvl == lvl and (l <= lvl):
                        px = min(o, lvl) if not filled_now else lvl
                        trades.append(Trade(1, entry_s, entry_h, entry_px, d, i, px, "stop"))
                        pos = 0
                        continue
                    if not filled_now and tp == tp and h >= tp:
                        trades.append(Trade(1, entry_s, entry_h, entry_px, d, i, max(o, tp), "target"))
                        pos = 0
                        continue
                else:
                    lvl = stop
                    if xs == xs and (lvl != lvl or xs < lvl):
                        lvl = xs
                    if lvl == lvl and (h >= lvl):
                        px = max(o, lvl) if not filled_now else lvl
                        trades.append(Trade(-1, entry_s, entry_h, entry_px, d, i, px, "stop"))
                        pos = 0
                        continue
                    if not filled_now and tp == tp and l <= tp:
                        trades.append(Trade(-1, entry_s, entry_h, entry_px, d, i, min(o, tp), "target"))
                        pos = 0
                        continue
                hi_since = max(hi_since, h)
                lo_since = min(lo_since, l)
        elif pos != 0:
            hi_since = max(hi_since, m.d_h[d])
            lo_since = min(lo_since, m.d_l[d])
        # ---- at the close of session d: move the trailing stop ----
        if pos != 0 and trail is not None:
            kind = trail[0]
            if kind == "chandelier":
                k, atr = trail[1], trail[2]
                new = hi_since - k * atr[d] if pos == 1 else lo_since + k * atr[d]
            elif kind == "close_atr":
                k, atr = trail[1], trail[2]
                closes = m.d_c[entry_s:d + 1]
                new = closes.max() - k * atr[d] if pos == 1 else closes.min() + k * atr[d]
            elif kind == "sar":
                af0, step, afmax = trail[1], trail[2], trail[3]
                if pos == 1:
                    if m.d_h[d] > ep:
                        ep, af = m.d_h[d], min(af + step, afmax)
                    sar = sar + af * (ep - sar)
                    sar = min(sar, m.d_l[d], m.d_l[d - 1])
                else:
                    if m.d_l[d] < ep:
                        ep, af = m.d_l[d], min(af + step, afmax)
                    sar = sar + af * (ep - sar)
                    sar = max(sar, m.d_h[d], m.d_h[d - 1])
                new = sar
            else:
                new = np.nan
            if new == new:
                if pos == 1 and (stop != stop or new > stop):
                    stop = new
                elif pos == -1 and (stop != stop or new < stop):
                    stop = new
        if d == last and pos != 0:
            he1 = m.s_end[d] - 1
            trades.append(Trade(pos, entry_s, entry_h, entry_px, d, he1, m.h_c[he1], "window end"))
            pos = 0
    return trades


# ── costs and statistics ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Costs:
    name: str
    spread: float               # USD per ounce, paid once per round trip (half on each side)
    slippage: float             # USD per ounce, per side
    commission: float           # USD per ounce, per side
    fin_long_add: float | None  # long financing = T-bill rate + this (a year); None = no financing
    fin_short_add: float | None # short financing = this - T-bill rate (a year)
    measured: bool = False      # spread = the bid/ask actually quoted in the entry and exit hours (spread field: marks only)


COSTS = {
    "C0": Costs("C0 brief: spread 0.40 + commission + slippage, no financing", 0.40, 0.10, 0.035, None, None),
    "C1": Costs("C1 base: C0 + overnight financing (long T-bill + 0.5%, short 1.5% - T-bill)", 0.40, 0.10, 0.035, 0.005, 0.015),
    "C2": Costs("C2 harsh: spread 0.50, slippage 0.25, commission 0.05; long T-bill + 2%, short 3% - T-bill", 0.50, 0.25, 0.05, 0.020, 0.030),
    "C3": Costs("C3 measured: the bid/ask quoted in each fill's hour + C1's slippage, commission and financing", 0.40, 0.10, 0.035, 0.005, 0.015, True),
}


def trades_frame(m: Market, trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["side", "entry_session", "exit_session", "entry_px", "exit_px", "reason", "entry_date",
                                     "exit_date", "nights", "entry_hour", "exit_hour"])
    df = pd.DataFrame([t.__dict__ for t in trades])
    df["entry_date"] = m.d_date[df["entry_session"].values]
    df["exit_date"] = m.d_date[df["exit_session"].values]
    df["nights"] = (df["exit_date"] - df["entry_date"]).dt.days.astype(int)
    df["gross"] = df["side"] * (df["exit_px"] / df["entry_px"] - 1.0)
    return df


def net_returns(m: Market, tf: pd.DataFrame, c: Costs) -> np.ndarray:
    if tf.empty:
        return np.array([])
    side = tf["side"].values
    e_mid, x_mid = tf["entry_px"].values, tf["exit_px"].values
    if c.measured and m.h_sp is not None:
        adv_in = m.h_sp[tf["entry_hour"].values.astype(int)] / 2 + c.slippage
        adv_out = m.h_sp[tf["exit_hour"].values.astype(int)] / 2 + c.slippage
    else:
        adv_in = adv_out = c.spread / 2 + c.slippage
    e_fill = e_mid + side * adv_in
    x_fill = x_mid - side * adv_out
    r = (side * (x_fill - e_fill) - 2 * c.commission) / e_fill
    if c.fin_long_add is not None:
        rate = m.rate
        cum = np.concatenate([[0.0], np.cumsum(rate.values)])     # rate-days, to average the rate over a holding
        idx0 = rate.index.get_indexer(pd.to_datetime(tf["entry_date"].values))
        nights = tf["nights"].values
        idx1 = idx0 + nights
        avg_rate = np.where(nights > 0, (cum[idx1] - cum[idx0]) / np.maximum(nights, 1), 0.0)
        ann = np.where(side == 1, avg_rate + c.fin_long_add, c.fin_short_add - avg_rate)
        r = r - ann * nights / 365.0
    return r


def stats(r: np.ndarray) -> dict:
    n = len(r)
    if n == 0:
        return {"trades": 0}
    wins, losses = r[r > 0], r[r < 0]
    streak = best = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    sd = r.std(ddof=1) if n > 1 else np.nan
    return {
        "trades": n, "avg": float(r.mean()), "median": float(np.median(r)), "win_rate": float(len(wins) / n),
        "avg_win": float(wins.mean()) if len(wins) else np.nan, "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else (np.inf if len(wins) else np.nan),
        "t_stat": float(r.mean() / (sd / np.sqrt(n))) if n > 1 and sd > 0 else np.nan,
        "longest_losing_streak": int(best), "compound_return": float(np.prod(1 + r) - 1), "best": float(r.max()), "worst": float(r.min()),
    }


def equity_curve(m: Market, tf: pd.DataFrame, r_net: np.ndarray, first: int, last: int, c: Costs) -> pd.Series:
    """Daily marked-to-market equity (start 1.0) over sessions [first, last], 1x notional, compounding.
    Inside a trade the mark is the gross move from entry less the entry side's costs and the
    financing accrued so far; the exit session books the trade's exact net return."""
    eq = np.ones(last - first + 1)
    level = 1.0
    cursor = first
    if not tf.empty:
        adv = c.spread / 2 + c.slippage
        for k, t in enumerate(tf.itertuples(index=False)):
            es, xs = int(t.entry_session), int(t.exit_session)
            eq[cursor - first:es - first] = level
            e_fill = t.entry_px + t.side * adv
            entry_cost = (adv + c.commission) / t.entry_px
            fin_rate = 0.0
            if c.fin_long_add is not None:
                rr = float(m.rate.iloc[m.rate.index.get_indexer([pd.Timestamp(t.entry_date)])[0]])
                fin_rate = (rr + c.fin_long_add) if t.side == 1 else (c.fin_short_add - rr)
            for s in range(es, xs):
                days = int((m.d_date[s] - m.d_date[es]).astype(int))
                mark = t.side * (m.d_c[s] / e_fill - 1.0) - entry_cost - fin_rate * days / 365.0
                eq[s - first] = level * (1 + mark)
            level *= (1 + r_net[k])
            eq[xs - first] = level
            cursor = xs + 1
    eq[cursor - first:] = level
    return pd.Series(eq, index=pd.to_datetime(m.d_date[first:last + 1]))


def curve_stats(eq: pd.Series) -> dict:
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ret = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    by_year = {}
    prev = float(eq.iloc[0])
    for y, s in eq.groupby(eq.index.year):
        by_year[int(y)] = float(s.iloc[-1] / prev - 1)
        prev = float(s.iloc[-1])
    return {"total_return": total, "cagr": float((1 + total) ** (1 / years) - 1) if total > -1 else -1.0,
            "max_drawdown": float(dd.min()), "sharpe": float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else np.nan,
            "years": years, "by_year": by_year}
