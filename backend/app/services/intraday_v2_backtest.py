"""Walk-forward backtest of the v2 tournament catalog on stored 15-minute history.

THE SAME RULES, THE SAME FILL MODEL
Every strategy is the live function from `intraday_v2_strategies`, called with the bar
index walking through the full history (indicators computed once per series). Fills
follow `intraday_v2_engine`'s model on 15-minute bars:
  - entry at the signal bar's close, plus slippage by liquidity (live fills at the price
    seconds after that close);
  - ORB stop-entries fill on the first later bar that reaches the trigger, at the trigger
    or that bar's open if it gapped through. Live, minute bars decide what happened after
    the trigger inside that bar; here a 15-minute bar cannot, so if the trigger bar also
    reaches the stop the trade is counted as STOPPED — the pessimistic reading;
  - stop and target checked bar by bar after entry: a bar opening beyond a level fills at
    the open; a bar reaching both counts as the STOP; targets pay no slippage (limit),
    every other exit does;
  - time stop after `max_bars` of the strategy's timeframe; end of day at the
    closing-auction-aware square-off (CAS stocks: the 15:00 bar's open, ~15:05 live;
    others: its close, ~15:12 live);
  - Angel One's intraday rate card on every round trip, short-side STT included.
Slots are exact: a trade's outcome never depends on whether it was taken, so trades are
simulated per symbol and then accepted in time order under the live limits (five slots
and the strategy's own cash). The live cap of two strategies per symbol couples the
strategies and is NOT applied — each strategy's record here is its own.

WHAT MAKES A RESULT BELIEVABLE (the gate)
Fifty-two strategies tried at once guarantee a few good-looking ones by luck. The gate
therefore asks four separate questions:
  1. Deflated Sharpe Ratio (Bailey & López de Prado 2014): the probability that the
     strategy's true Sharpe exceeds zero AFTER accounting for how many were tried and
     for the variance, skew and fat tails of its daily returns. Required >= 0.95.
  2. Probability of Backtest Overfitting by CSCV (Bailey, Borwein, López de Prado & Zhu
     2017): split the history into 16 blocks, and over all 12,870 ways of choosing half
     of them, how often does the in-sample winner finish in the bottom half out of
     sample? Above 0.5, picking "the best backtest" is worse than picking at random, and
     NOTHING is promoted.
  3. A holdout: the most recent 20% of the history is not used to select anything. A
     promoted strategy must also be profitable there.
  4. Enough trades (>= 100), profit factor >= 1.1, drawdown <= 25% of its capital, and
     profitable in >= 55% of months.
The thresholds are written into every result, so they cannot quietly move later.

SURVIVORSHIP. Each past day only trades the names that were in THAT day's top 200 by
traded value (point-in-time, from the daily bars) and that have stored intraday history.
Names that were liquid then but were never backfilled are missing; the coverage is
reported per run rather than hidden.

Run as a job, not inside the API process:
    python -m app.services.intraday_v2_backtest --days 730
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import heapq
import itertools
import json
import logging
import math
import os
import sqlite3
import statistics
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import NormalDist

from app.services import intraday_v2_strategies as v2
from app.services.angel_fees import round_trip
from app.services.intraday_store import (BARS_PER_SESSION, DATA_DIR, SESSION_OPEN_MIN, Series,
                                         aggregate, day_key, read_file)

logger = logging.getLogger("intraday_v2_backtest")

IST = timezone(timedelta(hours=5, minutes=30))
CAPITAL = v2.STRATEGY_CAPITAL          # the live sizing, unless --slot overrides it
SLOTS = v2.SLOTS_PER_STRATEGY
SLOT = v2.SLOT_NOTIONAL
HOLDOUT_FRAC = 0.20
CSCV_BLOCKS = 16
GATE = {"min_trades": 100, "min_dsr": 0.95, "max_pbo": 0.5, "min_profit_factor": 1.1,
        "max_drawdown_pct": 25.0, "min_positive_month_share": 0.55,
        "holdout_must_be_positive": True}
MIN_15 = 900
OPT_SUFFIX = "~opt"      # shadow record: the optimistic reading of ambiguous trigger bars
_ENTRY_FROM_MIN = int(v2.ENTRY_FROM[:2]) * 60 + int(v2.ENTRY_FROM[3:])
_ENTRY_UNTIL_MIN = int(v2.ENTRY_UNTIL[:2]) * 60 + int(v2.ENTRY_UNTIL[3:])


def slippage_bp(turnover_cr: float | None) -> float:
    from app.services.intraday_v2_engine import slippage_bp as live
    return live(turnover_cr)


# ── series helpers ───────────────────────────────────────────────────────────────


def _series(rows: list[tuple]) -> Series:
    s = Series([datetime.fromtimestamp(r[0], IST).isoformat() for r in rows], [r[1] for r in rows],
               [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows],
               [float(r[5]) for r in rows])
    s.epochs = [r[0] for r in rows]
    return s


def _end(t: int, minutes: int) -> int:
    d = datetime.fromtimestamp(t, IST)
    close = d.replace(hour=15, minute=30, second=0, microsecond=0)
    return int(min(d + timedelta(minutes=minutes), close).timestamp())


class Day:
    """One session of one symbol: index range in the 15m series and running sums."""

    __slots__ = ("key", "j0", "j1", "cumvol", "vwap")

    def __init__(self, key, j0, j1, s15):
        self.key, self.j0, self.j1 = key, j0, j1
        self.cumvol, self.vwap = [], []
        cv = pv = 0.0
        for k in range(j0, j1 + 1):
            cv += s15.v[k]
            pv += (s15.h[k] + s15.l[k] + s15.c[k]) / 3 * s15.v[k]
            self.cumvol.append(cv)
            self.vwap.append(pv / cv if cv else s15.c[k])


def _days(s15: Series) -> list[Day]:
    out, start = [], 0
    ep = s15.epochs
    for k in range(1, len(ep) + 1):
        if k == len(ep) or day_key(ep[k]) != day_key(ep[start]):
            out.append(Day(day_key(ep[start]), start, k - 1, s15))
            start = k
    return out


def _rvol(days: list[Day], di: int, k: int) -> float | None:
    """Relative volume after k bars of day di vs the 14 prior sessions."""
    if k < 1:
        return None
    base = [d.cumvol[k - 1] for d in days[max(0, di - 14):di] if len(d.cumvol) >= k]
    if not base or not sum(base):
        return None
    return days[di].cumvol[k - 1] / (sum(base) / len(base))


# ── point-in-time universe ───────────────────────────────────────────────────────


async def pit_universe(start: date, end: date, need: set[int], size: int = 200) -> dict[int, set[str]]:
    """day_key -> the top-`size` symbols by 20-session average traded value as of that
    MORNING: only sessions before the day count — no look-ahead. Computed for the day keys
    in `need` (the sessions being replayed), each kept as a capped heap."""
    from app.core.db import bars_collection
    from app.services.call_engine import INDICES
    since = datetime.combine(start - timedelta(days=45), datetime.min.time(), timezone.utc)
    until = datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc)
    tv: dict[str, list[tuple[int, float]]] = defaultdict(list)
    n = 0
    async for b in bars_collection.find({"timeframe": "1d", "ts": {"$gte": since, "$lt": until}},
                                        {"symbol": 1, "ts": 1, "close": 1, "volume": 1, "_id": 0}):
        sym = b.get("symbol")
        if not sym or sym in INDICES or not isinstance(b.get("ts"), datetime):
            continue
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=timezone.utc)
        tv[sym].append((day_key(int(ts.timestamp())), float(b.get("close") or 0) * float(b.get("volume") or 0)))
        n += 1
    logger.info("point-in-time universe: %d daily bars, %d symbols", n, len(tv))
    needed = sorted(need)
    heaps: dict[int, list[tuple[float, str]]] = {d: [] for d in needed}
    for sym, rows in tv.items():
        rows.sort()
        keys = [r[0] for r in rows]
        vals = [r[1] for r in rows]
        for d in needed:
            k = bisect_left(keys, d)               # sessions strictly before d
            if k < 15:
                continue
            w = vals[max(0, k - 20):k]
            avg = sum(w) / len(w)
            h = heaps[d]
            if len(h) < size:
                heapq.heappush(h, (avg, sym))
            elif avg > h[0][0]:
                heapq.heapreplace(h, (avg, sym))
    return {d: {sym for _a, sym in h} for d, h in heaps.items() if h}


# ── per-symbol replay ────────────────────────────────────────────────────────────


def replay_symbol(sym: str, s15: Series, tfs: dict[str, Series], nifty: dict[int, float],
                  allowed_days: set[int] | None, first_day: int, last_day: int,
                  turnover_cr: float | None, cas: bool, orb_ranks: dict[int, int],
                  signals_out: list | None = None) -> list[tuple]:
    """Every trade every strategy would have made in `sym`. Returns compact tuples:
    (strategy_id, sym, entry_t, exit_t, side, entry_px, exit_px, qty, gross, fees, net,
     reason, priority)."""
    days = _days(s15)
    day_at = {d.key: i for i, d in enumerate(days)}
    bp = slippage_bp(turnover_cr)
    ep15 = s15.epochs
    trades: list[tuple] = []
    by_tf: dict[str, list[v2.V2Spec]] = defaultdict(list)
    for spec in v2.CATALOG:
        by_tf[spec.tf].append(spec)

    def sim(spec, sig, t_signal: int, j_from: int, di: int, optimistic: bool = False):
        d = days[di]
        side, sign = sig.side, (1 if sig.side == "BUY" else -1)
        k = j_from
        # entry
        if sig.trigger is not None:
            entry = None
            while k <= d.j1 and ep15[k] + MIN_15 <= _cutoff(d, "14:30"):
                o, h, l = s15.o[k], s15.h[k], s15.l[k]
                if (sign > 0 and h >= sig.trigger) or (sign < 0 and l <= sig.trigger):
                    entry = max(sig.trigger, o) if sign > 0 else min(sig.trigger, o)
                    break
                k += 1
            if entry is None:
                return None
            fill = entry * (1 + sign * bp / 1e4)
            stop = fill - sign * sig.stop_dist
            # A 15m bar cannot order the trigger and the stop. Pessimistic: count the stop.
            # Optimistic (the ~opt shadow record): assume the stop was not touched after the
            # trigger inside that bar. The truth is between; live minute bars decide it.
            if not optimistic and ((sign > 0 and s15.l[k] <= stop) or (sign < 0 and s15.h[k] >= stop)):
                return _book(spec, sym, ep15[k], ep15[k] + MIN_15, side, fill, stop, "stoploss", True, bp, sig.priority)
            entry_t = ep15[k]
            k += 1
        else:
            fill = sig.entry * (1 + sign * bp / 1e4)
            entry_t = t_signal
        stop = fill - sign * sig.stop_dist
        if sig.target_price is not None:
            target = sig.target_price
            if sign * (target - fill) <= 0:
                return None
        elif sig.target_dist:
            target = fill + sign * sig.target_dist
        else:
            target = None
        sq = _squareoff_bar(d, ep15, cas)
        t_stop = entry_t + sig.max_bars * v2.TF_SECONDS.get(spec.tf, 900) if sig.max_bars else None
        while k <= d.j1:
            t, o, h, l, c = ep15[k], s15.o[k], s15.h[k], s15.l[k], s15.c[k]
            if sq is not None and k >= sq[0]:
                px = o if sq[1] == "open" else c
                return _book(spec, sym, entry_t, t + (0 if sq[1] == "open" else MIN_15), side, fill, px, "eod", True, bp, sig.priority)
            if sign * (o - stop) <= 0:
                return _book(spec, sym, entry_t, t, side, fill, o, "stoploss", True, bp, sig.priority)
            if target is not None and sign * (o - target) >= 0:
                return _book(spec, sym, entry_t, t, side, fill, o, "target", False, bp, sig.priority)
            lo, hi = (l, h) if sign > 0 else (-h, -l)
            if lo <= sign * stop:
                return _book(spec, sym, entry_t, t + MIN_15, side, fill, stop, "stoploss", True, bp, sig.priority)
            if target is not None and hi >= sign * target:
                return _book(spec, sym, entry_t, t + MIN_15, side, fill, target, "target", False, bp, sig.priority)
            if t_stop is not None and t + MIN_15 >= t_stop:
                return _book(spec, sym, entry_t, t + MIN_15, side, fill, c, "time", True, bp, sig.priority)
            k += 1
        # ran off the end of the day's bars (missing data): close at the last close
        return _book(spec, sym, entry_t, ep15[d.j1] + MIN_15, side, fill, s15.c[d.j1], "eod", True, bp, sig.priority)

    for tf, specs in list(by_tf.items()):
        s = s15 if tf in ("15m", "day") else tfs[tf]
        ep = s.epochs
        minutes = {"15m": 15, "45m": 45, "1h": 60, "day": 15}[tf]
        first_i = max(30, bisect_left(ep, first_day * 86400 - 19800))
        for i in range(first_i, len(ep)):
            t = ep[i]
            dk = day_key(t)
            if dk > last_day:
                break
            if allowed_days is not None and dk not in allowed_days:
                continue
            # integer minutes of the day, not a datetime per bar
            ds = dk * 86400 - 19800
            end = min(t + minutes * 60, ds + 930 * 60)
            mod = (end - ds) // 60
            if tf == "day":
                if mod != _ENTRY_FROM_MIN:
                    continue
            elif not (_ENTRY_FROM_MIN <= mod < _ENTRY_UNTIL_MIN):
                continue
            di = day_at.get(dk)
            if di is None:
                continue
            d = days[di]
            j = bisect_right(ep15, end - MIN_15) - 1        # last 15m bar closed by `end`
            if j < d.j0:
                continue
            kk = j - d.j0 + 1
            rv = _rvol(days, di, kk)
            now = datetime.fromtimestamp(end, IST)
            ctx = v2.build_ctx(sym, "15m" if tf == "day" else tf, now, s, s15, rv,
                               orb_ranks.get(dk) if tf == "day" else None,
                               nifty.get(end), None, i=(j if tf == "day" else i), j=j,
                               vwap=d.vwap[:kk])
            if ctx is None:
                continue
            for spec in specs:
                sig = v2.evaluate(spec, ctx)
                if sig is None:
                    continue
                if signals_out is not None:
                    signals_out.append((end, spec.strategy_id, sym, sig.side))
                tr = sim(spec, sig, end, j + 1, di)
                if tr is not None:
                    trades.append(tr)
                if sig.trigger is not None:
                    opt = sim(spec, sig, end, j + 1, di, optimistic=True)
                    if opt is not None:
                        trades.append((opt[0] + OPT_SUFFIX,) + opt[1:])
    return trades


def _cutoff(d: Day, hhmm: str) -> int:
    base = d.key * 86400 - 19800
    h, m = map(int, hhmm.split(":"))
    return base + (h * 60 + m) * 60


def _squareoff_bar(d: Day, ep15: list[int], cas: bool) -> tuple[int, str] | None:
    """The 15:00 bar: its open (CAS, ~15:05 live) or close (others, ~15:12 live)."""
    t1500 = _cutoff(d, "15:00")
    k = bisect_left(ep15, t1500, d.j0, d.j1 + 1)
    if k > d.j1:
        return None
    return (k, "open" if cas else "close")


def _book(spec, sym, entry_t, exit_t, side, fill, px, reason, market, bp, priority):
    sign = 1 if side == "BUY" else -1
    exit_px = px * (1 - sign * bp / 1e4) if market else px
    qty = int(SLOT // fill)
    if qty < 1:
        return None
    gross = sign * (exit_px - fill) * qty
    fees = round_trip(entry_price=fill, exit_price=exit_px, qty=qty, side=side, product="INTRADAY").total
    return (spec.strategy_id, sym, entry_t, exit_t, side, round(fill, 4), round(exit_px, 4), qty,
            round(gross, 2), round(fees, 2), round(gross - fees, 2), reason, float(sig_priority(priority)))


def sig_priority(p) -> float:
    try:
        return float(p)
    except (TypeError, ValueError):
        return 0.0


# ── portfolio pass: slots and cash, in time order ────────────────────────────────


def accept(trades: list[tuple]) -> dict[str, list[tuple]]:
    """Take each strategy's candidate trades in time order (ties: higher priority first)
    under the live limits: at most SLOTS open at once, and never more deployed than the
    strategy's capital plus what it has realised so far."""
    by_s: dict[str, list[tuple]] = defaultdict(list)
    for t in trades:
        by_s[t[0]].append(t)
    out = {}
    for sid, rows in by_s.items():
        rows.sort(key=lambda r: (r[2], -r[12]))
        open_heap: list[tuple[int, int, float, float]] = []   # (exit_t, seq, net, deployed)
        deployed = realized = 0.0
        taken = []
        for seq, r in enumerate(rows):
            while open_heap and open_heap[0][0] <= r[2]:
                _x, _s, net, dep = heapq.heappop(open_heap)
                realized += net
                deployed -= dep
            cost = r[5] * r[7]
            if len(open_heap) >= SLOTS or CAPITAL + realized - deployed < cost:
                continue
            heapq.heappush(open_heap, (r[3], seq, r[10], cost))
            deployed += cost
            taken.append(r)
        out[sid] = taken
    return out


# ── statistics ───────────────────────────────────────────────────────────────────

_EULER = 0.5772156649


def _moments(x: list[float]) -> tuple[float, float, float, float]:
    n = len(x)
    m = sum(x) / n
    var = sum((v - m) ** 2 for v in x) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    if sd == 0:
        return m, 0.0, 0.0, 3.0
    skew = sum(((v - m) / sd) ** 3 for v in x) / n
    kurt = sum(((v - m) / sd) ** 4 for v in x) / n
    return m, sd, skew, kurt


def deflated_sharpe(daily: list[float], sr_var: float, n_trials: int) -> float | None:
    """DSR: P(true SR > 0 | the best of n_trials), daily (non-annualised) Sharpe."""
    if len(daily) < 30:
        return None
    m, sd, g3, g4 = _moments(daily)
    if sd == 0:
        return None
    sr = m / sd
    nd = NormalDist()
    sr0 = math.sqrt(max(sr_var, 0.0)) * ((1 - _EULER) * nd.inv_cdf(1 - 1 / n_trials)
                                          + _EULER * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    denom = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    if denom <= 0:
        return None
    return nd.cdf((sr - sr0) * math.sqrt(len(daily) - 1) / math.sqrt(denom))


def pbo_cscv(matrix: list[list[float]], blocks: int = CSCV_BLOCKS) -> dict:
    """matrix[t][n]: daily return of strategy n on day t. Returns PBO and the logit list."""
    T = len(matrix)
    N = len(matrix[0]) if T else 0
    if T < blocks * 5 or N < 2:
        return {"pbo": None, "combinations": 0, "reason": "not enough days or strategies"}
    size = T // blocks
    parts = [matrix[b * size:(b + 1) * size] for b in range(blocks)]

    # per-block sums let the half-sample statistics be assembled without re-reading days
    block_stats = []
    for p in parts:
        sums = [sum(r[n] for r in p) for n in range(N)]
        sq = [sum(r[n] * r[n] for r in p) for n in range(N)]
        block_stats.append((sums, sq, len(p)))

    def sr_from(idx):
        cnt = sum(block_stats[b][2] for b in idx)
        out = []
        for n in range(N):
            s = sum(block_stats[b][0][n] for b in idx)
            q = sum(block_stats[b][1][n] for b in idx)
            m = s / cnt
            var = max((q - cnt * m * m) / max(cnt - 1, 1), 0.0)
            out.append(m / math.sqrt(var) if var > 0 else 0.0)
        return out

    logits = []
    for combo in itertools.combinations(range(blocks), blocks // 2):
        is_idx = set(combo)
        oos_idx = [b for b in range(blocks) if b not in is_idx]
        is_sr, oos_sr = sr_from(combo), sr_from(oos_idx)
        best = max(range(N), key=lambda n: is_sr[n])
        rank = sum(1 for n in range(N) if oos_sr[n] <= oos_sr[best])      # 1..N
        w = rank / (N + 1)
        logits.append(math.log(w / (1 - w)))
    return {"pbo": sum(1 for x in logits if x <= 0) / len(logits), "combinations": len(logits),
            "median_logit": statistics.median(logits)}


def metrics(taken: list[tuple], days: list[int]) -> dict:
    """Per-strategy record over the given trading days (day keys)."""
    pnl_day: dict[int, float] = defaultdict(float)
    for r in taken:
        pnl_day[day_key(r[3])] += r[10]
    daily = [pnl_day.get(d, 0.0) / CAPITAL for d in days]
    nets = [r[10] for r in taken]
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [-x for x in nets if x < 0]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for d in days:
        eq += pnl_day.get(d, 0.0)
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    months: dict[str, float] = defaultdict(float)
    for d in days:
        months[datetime.fromtimestamp(d * 86400, timezone.utc).strftime("%Y-%m")] += pnl_day.get(d, 0.0)
    m, sd, _, _ = _moments(daily) if len(daily) > 2 else (0.0, 0.0, 0.0, 3.0)
    t_stat = None
    if n > 2:
        mm, ss = sum(nets) / n, statistics.stdev(nets)
        t_stat = mm / (ss / math.sqrt(n)) if ss else None
    return {
        "trades": n, "net_pnl": round(sum(nets), 2), "gross_pnl": round(sum(r[8] for r in taken), 2),
        "fees": round(sum(r[9] for r in taken), 2),
        "win_rate": round(len(wins) / n, 4) if n else 0.0,
        "expectancy": round(sum(nets) / n, 2) if n else 0.0,
        "trade_sd": round(statistics.stdev(nets), 2) if n > 1 else None,
        "profit_factor": round(sum(wins) / sum(losses), 3) if losses else (None if not wins else 99.0),
        "max_drawdown_pct": round(mdd / CAPITAL * 100, 2),
        "sharpe_annual": round(m / sd * math.sqrt(250), 3) if sd else None,
        "daily_sr": m / sd if sd else 0.0,
        "t_stat": round(t_stat, 3) if t_stat is not None else None,
        "positive_month_share": round(sum(1 for v in months.values() if v > 0) / len(months), 3) if months else None,
        "months": {k: round(v, 2) for k, v in sorted(months.items())},
        "by_reason": {k: sum(1 for r in taken if r[11] == k) for k in ("target", "stoploss", "time", "eod")},
        "_daily": daily,
    }


# ── the job ──────────────────────────────────────────────────────────────────────


async def run(days_back: int = 730, symbols: list[str] | None = None, pit: bool = True,
              save: bool = True) -> dict:
    from app.core.db import db, instruments_collection
    from app.services import intraday_universe

    t0 = time.monotonic()
    today = datetime.now(IST).date()
    start = today - timedelta(days=days_back)
    members = await intraday_universe.members()
    meta = {m["symbol"]: m for m in members}
    files = sorted(f[:-5] for f in os.listdir(os.path.join(DATA_DIR, "15m")) if f.endswith(".ibar"))
    syms = [s for s in (symbols or files) if s != "NIFTY" and s in set(files)]
    if not set(meta) >= set(syms):
        extra = {d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": [s for s in syms if s not in meta]}},
            {"symbol": 1, "is_cas_enabled": 1})}
        for s_, d in extra.items():
            meta[s_] = {"symbol": s_, "cas": bool(d.get("is_cas_enabled")), "turnover_cr": None}

    # NIFTY's return since the open at every 15m close — fetched first if not stored yet
    nf = read_file("NIFTY")
    if len(nf) < 25 * 200:
        from app.services.intraday_backfill import NIFTY_MEMBER, backfill_symbol
        r = await backfill_symbol(NIFTY_MEMBER, start - timedelta(days=30), {})
        logger.info("NIFTY history fetched for the backtest: %s", r)
        nf = read_file("NIFTY")
    nifty: dict[int, float] = {}
    day_open = None
    cur = None
    for k in range(len(nf)):
        t = nf.t[k]
        dk = day_key(t)
        if dk != cur:
            cur, day_open = dk, nf.o[k]
        if day_open:
            nifty[t + MIN_15] = (nf.c[k] - day_open) / day_open * 100
    if not nifty:
        raise RuntimeError("no NIFTY 15m history — run the backfill (it includes NIFTY) first")

    first_day = day_key(int(datetime(start.year, start.month, start.day, tzinfo=IST).timestamp()))
    last_day = day_key(int(time.time()))
    sessions = {day_key(t) for t in nf.t if first_day <= day_key(t) <= last_day}
    pit_days = await pit_universe(start, today, sessions) if pit else {}

    # pass 1: rvol at 09:45 for every symbol-day, to rank "stocks in play"
    rv945: dict[int, list[tuple[float, str]]] = defaultdict(list)
    for sym in syms:
        b = read_file(sym)
        rows = list(b.rows())
        s15 = _series(rows)
        dlist = _days(s15)
        for di, d in enumerate(dlist):
            if d.key < first_day or len(d.cumvol) < 2:
                continue
            if pit and d.key in pit_days and sym not in pit_days[d.key]:
                continue
            r = _rvol(dlist, di, 2)
            if r is not None:
                rv945[d.key].append((r, sym))
        del b, rows, s15, dlist
    ranks: dict[str, dict[int, int]] = defaultdict(dict)
    for dk, lst in rv945.items():
        lst.sort(reverse=True)
        for i, (_r, sym) in enumerate(lst):
            ranks[sym][dk] = i + 1

    # pass 2: replay. Candidate trades go to an on-disk table, not a list: two years of
    # 200 names is ~a million candidates, ~350 MB as Python tuples in a 700 MB container.
    db_path = os.path.join("/tmp", f"v2bt-{os.getpid()}.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE c (sid TEXT, sym TEXT, et INTEGER, xt INTEGER, side TEXT, ep REAL, "
                "xp REAL, qty INTEGER, gross REAL, fees REAL, net REAL, reason TEXT, prio REAL)")
    n_cand = 0
    coverage: dict[int, int] = defaultdict(int)
    for n_sym, sym in enumerate(syms):
        b = read_file(sym)
        rows = list(b.rows())
        if len(rows) < 500:
            continue
        s15 = _series(rows)
        tfs = {"45m": _series(aggregate(rows, 45, 2 ** 40)), "1h": _series(aggregate(rows, 60, 2 ** 40))}
        allowed = None
        if pit:
            allowed = {dk for dk, ss in pit_days.items() if sym in ss}
        for d in _days(s15):
            if allowed is None or d.key in allowed:
                coverage[d.key] += 1
        m = meta.get(sym, {})
        cand = replay_symbol(sym, s15, tfs, nifty, allowed, first_day, last_day,
                             m.get("turnover_cr"), bool(m.get("cas", True)), ranks.get(sym, {}))
        con.executemany("INSERT INTO c VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", cand)
        n_cand += len(cand)
        if n_sym % 20 == 0:
            con.commit()
            logger.info("replayed %d/%d symbols, %d candidate trades, %.0fs", n_sym + 1, len(syms),
                        n_cand, time.monotonic() - t0)
        del b, rows, s15, tfs, cand
        await asyncio.sleep(0)
    con.commit()
    con.execute("CREATE INDEX ix ON c (sid, et, prio)")

    all_days = sorted(d for d in coverage if first_day <= d <= last_day)
    cut = all_days[int(len(all_days) * (1 - HOLDOUT_FRAC))] if all_days else 0
    sel_days = [d for d in all_days if d < cut]
    hold_days = [d for d in all_days if d >= cut]

    # one strategy at a time: accept under the live limits, measure, write, forget
    run_id = datetime.now(IST).strftime("%Y%m%d-%H%M")
    trades_path = None
    out_f = None
    if save:
        path = os.path.join(DATA_DIR, "backtests")
        os.makedirs(path, exist_ok=True)
        trades_path = os.path.join(path, f"v2-{run_id}-trades.jsonl.gz")
        out_f = gzip.open(trades_path, "wt")
    per: dict[str, dict] = {}
    n_taken = 0
    sids = [r[0] for r in con.execute("SELECT DISTINCT sid FROM c")]
    for sid in sorted(set(sids) | {sp.strategy_id for sp in v2.CATALOG}):
        rows = [tuple(r) for r in con.execute("SELECT * FROM c WHERE sid=? ORDER BY et, prio DESC", (sid,))]
        tk = accept(rows).get(sid, [])
        n_taken += len(tk) if not sid.endswith(OPT_SUFFIX) else 0
        per[sid] = {
            "selection": metrics([r for r in tk if day_key(r[3]) < cut], sel_days),
            "holdout": metrics([r for r in tk if day_key(r[3]) >= cut], hold_days),
            "full": metrics(tk, all_days),
        }
        if out_f is not None:
            for r in tk:
                out_f.write(json.dumps(list(r)) + "\n")
        del rows, tk
    if out_f is not None:
        out_f.close()
    con.close()
    os.remove(db_path)

    ids = [s.strategy_id for s in v2.CATALOG]
    srs = [per[i]["selection"]["daily_sr"] for i in ids]
    sr_var = statistics.pvariance(srs) if len(srs) > 1 else 0.0
    matrix = [[per[i]["selection"]["_daily"][k] for i in ids] for k in range(len(sel_days))]
    pbo = pbo_cscv(matrix)
    results = []
    for spec in v2.CATALOG:
        r = per[spec.strategy_id]
        sel, hold, full = r["selection"], r["holdout"], r["full"]
        dsr = deflated_sharpe(sel["_daily"], sr_var, len(ids))
        checks = {
            "trades": full["trades"] >= GATE["min_trades"],
            "dsr": dsr is not None and dsr >= GATE["min_dsr"],
            "profit_factor": (sel["profit_factor"] or 0) >= GATE["min_profit_factor"],
            "drawdown": sel["max_drawdown_pct"] <= GATE["max_drawdown_pct"],
            "months": (sel["positive_month_share"] or 0) >= GATE["min_positive_month_share"],
            "holdout": hold["net_pnl"] > 0,
            "pbo": pbo["pbo"] is not None and pbo["pbo"] <= GATE["max_pbo"],
            "selection_positive": sel["net_pnl"] > 0,
        }
        for part in (sel, hold, full):
            part.pop("_daily", None)
        bound = None
        if spec.strategy_id + OPT_SUFFIX in per:
            o_sel = per[spec.strategy_id + OPT_SUFFIX]["selection"]
            o_hold = per[spec.strategy_id + OPT_SUFFIX]["holdout"]
            bound = {"note": "optimistic reading of trigger bars that also reached the stop; the "
                             "gate uses the pessimistic record above. If even this loses, the rule "
                             "fails on any reading; if it wins, only minute data (live incubation) "
                             "can settle it.",
                     "selection_net": o_sel["net_pnl"], "selection_pf": o_sel["profit_factor"],
                     "selection_win_rate": o_sel["win_rate"], "holdout_net": o_hold["net_pnl"],
                     "ambiguous": o_sel["net_pnl"] > 0 >= sel["net_pnl"]}
        results.append({"strategy_id": spec.strategy_id, "name": spec.name, "family": spec.family,
                        "optimistic_bound": bound,
                        "timeframe": spec.tf, "kind": spec.kind, "dsr": round(dsr, 4) if dsr is not None else None,
                        "per_trade_sd": full.get("trade_sd"),
                        "checks": checks, "passed": all(checks.values()),
                        "selection": sel, "holdout": hold, "full": full})
    results.sort(key=lambda r: -(r["selection"]["net_pnl"]))
    summary = {
        "_id": f"v2bt:{run_id}", "run_id": run_id, "created_at": datetime.now(timezone.utc),
        "days_back": days_back, "first_day": str(datetime.fromtimestamp(first_day * 86400, timezone.utc).date()),
        "holdout_from": str(datetime.fromtimestamp(cut * 86400, timezone.utc).date()) if cut else None,
        "sessions": len(all_days), "selection_sessions": len(sel_days), "holdout_sessions": len(hold_days),
        "symbols": len(syms), "point_in_time": pit,
        "coverage_median": statistics.median([coverage[d] for d in all_days]) if all_days else 0,
        "candidate_trades": n_cand, "taken_trades": n_taken, "trades_file": trades_path,
        "pbo": pbo, "sr_variance_daily": sr_var, "n_trials": len(ids), "gate": GATE,
        "passed": [r["strategy_id"] for r in results if r["passed"]],
        "elapsed_s": round(time.monotonic() - t0, 1),
        "fill_model": "signal-bar close + slippage; 15m-bar stop/target, stop first; ORB trigger bar "
                      "touching the stop counts as stopped; CAS-aware EOD; Angel intraday costs",
    }
    if save:
        bt = db["intraday_v2_backtests"]
        await bt.replace_one({"_id": summary["_id"]}, summary, upsert=True)
        await bt.replace_one({"_id": f"v2bt:{run_id}:strategies"},
                             {"_id": f"v2bt:{run_id}:strategies", "run_id": run_id, "results": results},
                             upsert=True)
        await bt.replace_one({"_id": "latest"}, {"_id": "latest", "run_id": run_id}, upsert=True)
        from app.services.intraday_v2_registry import register_from_backtest
        summary["registered"] = await register_from_backtest(run_id)
    summary["results"] = results
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--no-pit", action="store_true")
    ap.add_argument("--dry", action="store_true", help="do not save results")
    ap.add_argument("--no-align", action="store_true", help="trend rules ignore NIFTY's direction")
    ap.add_argument("--slot", type=float, default=None, help="rupees per position (capital = 5 x slot)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    global CAPITAL, SLOT
    if a.slot:
        SLOT = a.slot
        CAPITAL = a.slot * SLOTS
    if a.no_align:
        v2.ALIGN_WITH_NIFTY = False
    print(f"config: slot Rs {SLOT:,.0f}, capital Rs {CAPITAL:,.0f}, NIFTY alignment {v2.ALIGN_WITH_NIFTY}")
    out = asyncio.run(run(a.days, [s for s in a.symbols.split(",") if s] or None,
                          pit=not a.no_pit, save=not a.dry))
    res = out.pop("results")
    print(json.dumps({k: v for k, v in out.items() if k != "created_at"}, default=str, indent=1))
    for r in res:
        s, h = r["selection"], r["holdout"]
        print(f"{r['strategy_id']:<28} sel {s['trades']:>5} tr {s['net_pnl']:>12,.0f} PF {s['profit_factor']} "
              f"DSR {r['dsr']} | hold {h['trades']:>4} tr {h['net_pnl']:>10,.0f} | {'PASS' if r['passed'] else ''}"
              f" {[k for k, v in r['checks'].items() if not v]}")


if __name__ == "__main__":
    main()
