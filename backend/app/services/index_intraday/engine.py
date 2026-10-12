"""Indian Index Intraday: the trade simulator and its statistics (research, Backtesting Lab and
the paper engine all use this one).

ONE RULE FOR EVERY STRATEGY (no look-ahead, no flattering fills)
---------------------------------------------------------------
* A signal is read at a bar's CLOSE (the bar's last minute has finished). A MARKET entry fills
  at the OPEN of the next minute, paying slippage. A STOP entry (a breakout order resting at a
  level) fills at the level on the first minute that trades through it — or at that minute's
  open if it gaps past — paying slippage.
* No new entry after ENTRY_CUTOFF (14:30). Every position is out by SQUARE_OFF (15:12, three
  minutes inside Angel's own 15:15 MIS square-off for non-auction instruments), at that
  minute's open, paying slippage.
* Exits are walked minute by minute from the entry minute itself: a market entry filled at that
  minute's open, so all of it counts; a stop entry filled inside it, so an adverse stop touch
  there counts and a target touch does not (pessimistic). A stop or target inside a minute
  fills at its level; a minute opening beyond a level fills at that open; a minute touching
  both is a stop.
  Targets are resting limits (no slippage); stops, trailing stops, time and signal exits are
  market orders (slippage).
* Trailing stops trail the best price SEEN BEFORE the minute being tested (the minute's own
  extreme cannot both raise and trigger the stop).
Returns are per trade in bp of the trade's notional (one unit of capital, no leverage), net of
the round-trip charges and slippage. A day's return is the sum of its trades' returns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .data import SESSION_MIN, minute_of

ENTRY_CUTOFF = minute_of("14:30")      # last minute a new position may open
SQUARE_OFF = minute_of("15:12")        # every position closes at this minute's open


@dataclass(frozen=True)
class Costs:
    fee_rt_bp: float = 4.02            # Angel intraday charges, Rs10 lakh round trip (ii_costs)
    slip_bp: float = 1.0               # half-spread + impact per market fill


@dataclass
class ExitCfg:
    stop: str = "none"                 # none | atr | pct | level (the entry spec supplies the level)
    stop_mult: float = 0.0             # x day-ATR (atr) or % (pct)
    target_r: float = 0.0              # target at R x initial risk; 0 = none
    trail: str = "none"                # none | atr | pct
    trail_mult: float = 0.0
    max_hold: int = 0                  # minutes; 0 = until square-off
    signal_exit: bool = False          # leave when the signal turns flat / opposite (at a bar close)


@dataclass
class Trade:
    day: int
    side: int
    entry_min: int
    entry_px: float
    exit_min: int
    exit_px: float
    reason: str
    gross_bp: float
    net_bp: float


def _first(mask: np.ndarray) -> int:
    i = int(np.argmax(mask)) if mask.size else 0
    return i if mask.size and mask[i] else -1


def walk_exit(o, h, l, c, start: int, end: int, side: int, entry: float, stop: float | None,
              target: float | None, trail_dist: float | None, sig_exit_min: int | None,
              max_hold_end: int | None, entry_kind: str = "market") -> tuple[int, float, str]:
    """(exit minute, raw exit price before slippage, reason) for one position, walked over the
    minutes [start, end) of one day; `start` is the ENTRY minute, `end` the square-off minute
    (exit at its open).

    The entry minute itself: a MARKET entry filled at its open, so all of it is after the fill —
    its stop / target touches count, only its open cannot be a 'gap'. A STOP entry filled
    somewhere inside it, so the order is unknown: an adverse stop touch counts (pessimistic), a
    target touch does not."""
    last = end
    if sig_exit_min is not None:
        last = min(last, sig_exit_min)
    if max_hold_end is not None:
        last = min(last, max_hold_end)
    if start >= last:
        return last, float(o[last]), ("square_off" if last == end else "signal" if last == sig_exit_min else "time")
    rng = slice(start, last)
    O, H, L = o[rng].copy(), h[rng], l[rng]
    O[0] = entry                                    # the entry minute cannot gap past a level
    n = len(O)
    if trail_dist is not None:
        if side > 0:
            best = np.maximum.accumulate(np.r_[entry, H[:-1]])
            tlev = best - trail_dist
        else:
            best = np.minimum.accumulate(np.r_[entry, L[:-1]])
            tlev = best + trail_dist
        if stop is not None:
            tlev = np.maximum(tlev, stop) if side > 0 else np.minimum(tlev, stop)
        slev = tlev
    elif stop is not None:
        slev = np.full(n, stop)
    else:
        slev = None
    if side > 0:
        s_hit = (L <= slev) if slev is not None else np.zeros(n, bool)
        t_hit = (H >= target) if target is not None else np.zeros(n, bool)
    else:
        s_hit = (H >= slev) if slev is not None else np.zeros(n, bool)
        t_hit = (L <= target) if target is not None else np.zeros(n, bool)
    if entry_kind == "stop":
        t_hit = t_hit.copy()
        t_hit[0] = False
    ks, kt = _first(s_hit), _first(t_hit)
    if ks < 0 and kt < 0:
        reason = "square_off" if last == end else ("signal" if last == sig_exit_min else "time")
        return last, float(o[last]), reason
    if kt >= 0 and (ks < 0 or kt < ks):
        px = float(O[kt])
        better = px >= target if side > 0 else px <= target
        return start + kt, (px if better else float(target)), "target"
    lvl = float(slev[ks])
    px = float(O[ks])
    worse = px <= lvl if side > 0 else px >= lvl
    return start + ks, (px if worse else lvl), ("trail" if trail_dist is not None else "stop")


@dataclass
class EntrySpec:
    """What a strategy asks for on one day."""
    side: int
    minute: int                        # the minute the entry fills in (market: its open)
    kind: str = "market"               # market | stop
    level: float | None = None         # stop entries: the trigger price
    stop: float | None = None          # an explicit initial stop price (kind 'level' stops)


def simulate_day(o, h, l, c, specs_fn, exit_cfg: ExitCfg, atr: float, costs: Costs,
                 sig_exit_fn=None, max_trades: int = 1, day: int = 0, cutoff: int = ENTRY_CUTOFF) -> list[Trade]:
    """Run one day: ask `specs_fn(after_minute)` for the next entry at or after a minute, fill
    it, walk its exit, repeat up to `max_trades`. `cutoff` is the last entry minute (14:30 by
    default; a family that is ABOUT the last half hour may set 14:45)."""
    trades: list[Trade] = []
    t = 0
    atr = atr if atr == atr else 0.0
    while len(trades) < max_trades:
        spec = specs_fn(t)
        if spec is None or spec.minute > cutoff or spec.minute >= SQUARE_OFF:
            break
        m = spec.minute
        side = spec.side
        if spec.kind == "stop":
            px = float(o[m])
            lvl = float(spec.level)
            gapped = px >= lvl if side > 0 else px <= lvl
            raw_entry = px if gapped else lvl
        else:
            raw_entry = float(o[m])
        entry = raw_entry * (1 + side * costs.slip_bp / 1e4)
        risk = None
        stop = None
        if spec.stop is not None:
            stop = float(spec.stop)
        elif exit_cfg.stop == "atr" and atr > 0:
            stop = raw_entry - side * exit_cfg.stop_mult * atr
        elif exit_cfg.stop == "pct":
            stop = raw_entry * (1 - side * exit_cfg.stop_mult / 100)
        if stop is not None:
            risk = abs(raw_entry - stop)
            if risk <= 0:
                stop, risk = None, None
        target = None
        if exit_cfg.target_r > 0 and risk:
            target = raw_entry + side * exit_cfg.target_r * risk
        trail = None
        if exit_cfg.trail == "atr" and atr > 0:
            trail = exit_cfg.trail_mult * atr
        elif exit_cfg.trail == "pct":
            trail = raw_entry * exit_cfg.trail_mult / 100
        sig_exit = sig_exit_fn(m, side) if (exit_cfg.signal_exit and sig_exit_fn) else None
        hold_end = (m + exit_cfg.max_hold) if exit_cfg.max_hold else None
        x_min, x_raw, reason = walk_exit(o, h, l, c, m, SQUARE_OFF, side, raw_entry, stop, target, trail,
                                         sig_exit, hold_end, spec.kind)
        slip_exit = 0.0 if reason == "target" else costs.slip_bp
        exit_px = x_raw * (1 - side * slip_exit / 1e4)
        gross = side * (x_raw - raw_entry) / raw_entry * 1e4
        net = side * (exit_px - entry) / entry * 1e4 - costs.fee_rt_bp
        trades.append(Trade(day, side, m, entry, x_min, exit_px, reason, gross, net))
        t = x_min + 1
    return trades


# ── statistics ───────────────────────────────────────────────────────────────────

DAYS_PER_YEAR = 248


def summarize(trades: list[Trade], ndays: int, dates: np.ndarray, extra_cost_bp: float = 0.0) -> dict:
    """Per-trade and per-day statistics. `ndays` = trading days in the period (no-trade days
    count as zero-return days)."""
    if not trades:
        return {"trades": 0}
    net = np.array([t.net_bp - extra_cost_bp for t in trades])
    gross = np.array([t.gross_bp for t in trades])
    days = np.array([t.day for t in trades])
    daily = np.zeros(ndays)
    np.add.at(daily, days, net)
    wins, losses = net[net > 0], net[net <= 0]
    eq = np.cumsum(daily)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq)) if len(eq) else 0.0
    sd = daily.std(ddof=1)
    down = daily[daily < 0]
    dsd = math.sqrt((down ** 2).sum() / max(len(daily) - 1, 1)) if len(down) else 0.0
    months = dates.astype("datetime64[M]")
    mret = {}
    for m, x in zip(months, daily):
        mret[m] = mret.get(m, 0.0) + x
    mvals = np.array(list(mret.values()))
    years = dates.astype("datetime64[Y]")
    yret = {}
    for y, x in zip(years, daily):
        yret[y] = yret.get(y, 0.0) + x
    return {
        "trades": int(len(net)), "days": int(ndays),
        "trades_per_day": round(len(net) / max(ndays, 1), 3),
        "win_rate": float((net > 0).mean()),
        "mean_net_bp": float(net.mean()), "mean_gross_bp": float(gross.mean()),
        "t_trade": float(net.mean() / (net.std(ddof=1) / math.sqrt(len(net)))) if len(net) > 2 and net.std() > 0 else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "expectancy_bp": float(net.mean()),
        "avg_win_bp": float(wins.mean()) if len(wins) else 0.0, "avg_loss_bp": float(losses.mean()) if len(losses) else 0.0,
        "rr": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else float("nan"),
        "total_bp": float(daily.sum()), "ann_bp": float(daily.mean() * DAYS_PER_YEAR),
        "sharpe": float(daily.mean() / sd * math.sqrt(DAYS_PER_YEAR)) if sd > 0 else 0.0,
        "sortino": float(daily.mean() / dsd * math.sqrt(DAYS_PER_YEAR)) if dsd > 0 else 0.0,
        "max_dd_bp": dd,
        "months_positive": float((mvals > 0).mean()) if len(mvals) else 0.0,
        "avg_month_bp": float(mvals.mean()) if len(mvals) else 0.0,
        "years_positive": int(sum(1 for v in yret.values() if v > 0)), "years": int(len(yret)),
        "skew": float(((daily - daily.mean()) ** 3).mean() / sd ** 3) if sd > 0 else 0.0,
        "kurt": float(((daily - daily.mean()) ** 4).mean() / sd ** 4) if sd > 0 else 3.0,
        "sr_daily": float(daily.mean() / sd) if sd > 0 else 0.0,
        "reasons": {r: int(sum(1 for t in trades if t.reason == r)) for r in {t.reason for t in trades}},
    }


def daily_series(trades: list[Trade], ndays: int) -> np.ndarray:
    daily = np.zeros(ndays)
    for t in trades:
        daily[t.day] += t.net_bp
    return daily


ND = None


def deflated_sr(sr: float, n: int, skew: float, kurt: float, sr_var: float, trials: int) -> float:
    """Bailey & Lopez de Prado (2014). SR per period (daily)."""
    from statistics import NormalDist
    nd = NormalDist()
    if n < 3 or not np.isfinite(sr) or trials < 2:
        return float("nan")
    g = 0.5772156649
    sr0 = math.sqrt(max(sr_var, 1e-12)) * ((1 - g) * nd.inv_cdf(1 - 1 / trials) + g * nd.inv_cdf(1 - 1 / (trials * math.e)))
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return float(nd.cdf((sr - sr0) * math.sqrt(n - 1) / den))
