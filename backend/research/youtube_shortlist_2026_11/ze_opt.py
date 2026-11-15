"""Real NIFTY option premiums for the channel-shortlist study's option-buying strategies (the owner's list E).

The app's option-chain recorder (backend/app/services/option_chain_recorder.py) saves, every minute of the NSE session,
Angel One's full quote - last price, best bid and ask, open interest, day volume - of NIFTY's current and next weekly
expiry, the ATM strike +-10 strikes, calls and puts, with NIFTY spot and India VIX, as one JSON line per minute in
DATA_DIR/optchain/YYYY-MM-DD.jsonl (gzipped after the close). The paper desk reads the same files (/data/intraday/
optchain, mounted read-only); research reads a copy (D:/intraday_ai_data/optchain). Recorded since 5 Oct 2026.

Each recorded contract-day becomes a market of minute snapshots for the 11-channel fill engine: o = h = l = c = the mid of
the best bid and ask, half = half the spread, so the engine buys at the ask and sells at the bid of the recorded quote;
a minute without a two-sided quote is left out; the previous session's quotes of the same contract come first, as the
history a premium chart shows at the open (strategies trade only the picked day). Costs are NSE option charges per unit for one lot of 65: brokerage Rs 20
an order with 18% GST, STT 0.1% of the sell premium, exchange 0.03503%, stamp 0.003% of the buy, SEBI, as a fixed part
and a share of the premium per side, plus one tick (Rs 0.05) of slippage. A pool of such markets runs like the desk's
stock pools: one book over many contracts, each strategy choosing its contracts through a context built from the whole
day's chain using only what was known at each minute."""

from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import bb_markets as BM
import yt_markets as YM

IST = timezone(timedelta(hours=5, minutes=30))
CHAIN_DIR = Path(os.getenv("ZE_OPTCHAIN_DIR") or ("/data/intraday/optchain" if Path("/data/intraday/optchain").exists()
                                                 else "D:/intraday_ai_data/optchain"))
LOT = 65
# per unit, per side: brokerage Rs 20 an order + 18% GST spread over one lot; STT 0.1% of the sell premium shared over
# both sides (0.05%), exchange 0.03503% + its GST, stamp 0.003% of the buy shared (0.0015%), SEBI Rs 10 a crore
OPT_COST = YM.Cost(None, 0.05, 20 * 1.18 / LOT, False, LOT, pct_slip=0.0, pct_comm=0.0005 + 0.0003503 * 1.18 + 0.000015 + 0.000001)


@dataclass
class ChainDay:
    date: str                                   # IST trading date, YYYY-MM-DD
    t: np.ndarray                               # epoch seconds of each recorded minute
    spot: np.ndarray
    vix: np.ndarray
    exp: list                                   # recorded expiries, nearest first (YYYY-MM-DD)
    q: dict = field(default_factory=dict)       # (expiry, strike, "C"|"P") -> array (n, 5): ltp, bid, ask, oi, volume

    def ist_min(self, i: int) -> int:
        return int(((int(self.t[i]) + 19800) // 60) % 1440)


def _read_lines(path: Path):
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:          # a half-written last line of the live file
                    continue


def load_day(path: Path) -> ChainDay | None:
    rows = [r for r in _read_lines(path) if r.get("rows")]
    if not rows:
        return None
    rows.sort(key=lambda r: r["t"])
    n = len(rows)
    t = np.array([int(r["t"]) for r in rows], np.int64)
    spot = np.array([float(r.get("spot") or np.nan) for r in rows])
    vix = np.array([float(r.get("vix") or np.nan) for r in rows])
    exps: list = []
    for r in rows:
        for e in r.get("exp") or []:
            if e not in exps:
                exps.append(e)
    exps.sort()
    q: dict = {}
    for i, r in enumerate(rows):
        ex = r.get("exp") or []
        for x in r["rows"]:
            ei, strike, cp, ltp, bid, _bq, ask, _aq, oi, vol = x[:10]
            if not (0 <= int(ei) < len(ex)):
                continue
            key = (ex[int(ei)], float(strike), str(cp))
            a = q.get(key)
            if a is None:
                a = q[key] = np.full((n, 5), np.nan)
            a[i] = (ltp or np.nan, bid or np.nan, ask or np.nan, oi if oi is not None else np.nan, vol if vol is not None else np.nan)
    d = datetime.fromtimestamp(int(t[0]), IST).date().isoformat()
    return ChainDay(d, t, spot, vix, exps, q)


def load_days(since: date | None = None, until: date | None = None, folder: Path | None = None) -> list[ChainDay]:
    """Every recorded session from `since` (inclusive), oldest first; today's live file is read as it stands."""
    folder = Path(folder or CHAIN_DIR)
    out = []
    files = {}
    for p in folder.glob("*.jsonl*"):
        d = p.name[:10]
        if p.suffix == ".gz" or d not in files:
            files[d] = p
    for d in sorted(files):
        if since and d < since.isoformat():
            continue
        if until and d > until.isoformat():
            continue
        day = load_day(files[d])
        if day is not None:
            out.append(day)
    return out


def contract_name(key) -> str:
    exp, strike, cp = key
    return f"NIFTY {datetime.strptime(exp, '%Y-%m-%d').strftime('%d%b%y').upper()} {int(strike)} {cp}E"


def _quotes(day: ChainDay | None, key, min_n: int = 30):
    """(epoch, mid, half spread, minute volume) of the contract's two-sided quotes that day, or None (under min_n)."""
    a = day.q.get(key) if day is not None else None
    if a is None:
        return None
    bid, ask, vol = a[:, 1], a[:, 2], a[:, 4]
    ok = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
    if ok.sum() < min_n:
        return None
    mid = (bid[ok] + ask[ok]) / 2.0
    half = np.maximum((ask[ok] - bid[ok]) / 2.0, 0.025)
    cum = np.nan_to_num(vol[ok], nan=0.0)
    v = np.maximum(np.diff(cum, prepend=cum[0]), 0.0).astype(np.float32)
    return day.t[ok], mid, half, v


def contract_market(day: ChainDay, key, prev: ChainDay | None = None):
    """The contract-day as a market of minute snapshots (None if it has no two-sided quote yet: a live day's market
    exists from its first quote, as the full day's does). With `prev`
    (the previous recorded session) the contract's quotes of that day come first, so indicators read from the premium
    chart have their history at the open as a chart would; strategies trade only the last day (`chain_date`)."""
    cur = _quotes(day, key, 1)
    if cur is None:
        return None
    old = _quotes(prev, key)
    segs = [old, cur] if old is not None else [cur]
    dates = ([prev.date] if old is not None else []) + [day.date]
    t = np.concatenate([s[0] for s in segs])
    mid = np.concatenate([s[1] for s in segs])
    half = np.concatenate([s[2] for s in segs])
    v = np.concatenate([s[3] for s in segs])
    sizes = [len(s[0]) for s in segs]
    dayix = np.concatenate([np.full(k, i, np.int32) for i, k in enumerate(sizes)])
    d1 = np.cumsum(sizes).astype(np.int64)
    d0 = (d1 - np.array(sizes)).astype(np.int64)
    ist, ny = BM._clocks(t)
    m = YM.Mkt(contract_name(key), t, mid, mid.copy(), mid.copy(), mid.copy(), half, v, ist, ny, dayix, d0, d1,
               np.array([np.datetime64(x) for x in dates]), np.array([False] + [True] * (len(segs) - 1)),
               np.zeros(len(segs), bool), OPT_COST)
    m.split_key, m.overnight = "NIFTY", False
    m.contract, m.chain_date = key, day.date
    m.spot_at = dict(zip(day.t.tolist(), day.spot.tolist()))
    return m


def prev_hlc(prev: ChainDay | None, key):
    """The contract's high, low and close of mids in the previous session (None if it has under 30 quotes there)."""
    q = _quotes(prev, key)
    if q is None:
        return None
    mid = q[1]
    return float(mid.max()), float(mid.min()), float(mid[-1])


def previous_session(days: list[ChainDay], i: int, max_weekdays: int = 2) -> ChainDay | None:
    """days[i-1] when it is the session before days[i] (at most `max_weekdays` weekdays apart, so a holiday between
    is allowed but a longer recording gap is not)."""
    if i <= 0:
        return None
    prev = days[i - 1]
    return prev if int(np.busday_count(prev.date, days[i].date)) <= max_weekdays else None


def days_to_expiry(day: ChainDay) -> int:
    """Weekdays from the session to its current expiry (0 on expiry day)."""
    return int(np.busday_count(day.date, day.exp[0])) if day.exp else -1


def at_minute(day: ChainDay, hhmm: int) -> int:
    """Index of the first snapshot at or after hh:mm IST (-1 if none)."""
    mins = (day.t + 19800) // 60 % 1440
    j = int(np.searchsorted(mins, hhmm, "left"))
    return j if j < len(day.t) else -1


def ist_ok(day: ChainDay, i: int, hhmm: int, slack: int = 3) -> bool:
    """The snapshot found for hh:mm is no more than `slack` minutes late (a recording gap would make it stale)."""
    return 0 <= i < len(day.t) and day.ist_min(i) <= hhmm + slack


def mid_of(day: ChainDay, key, i: int) -> float:
    a = day.q.get(key)
    if a is None or i < 0:
        return float("nan")
    bid, ask = a[i, 1], a[i, 2]
    if not (np.isfinite(bid) and np.isfinite(ask) and bid > 0 and ask >= bid):
        return float("nan")
    return float((bid + ask) / 2.0)


def closest_premium(day: ChainDay, i: int, target: float, cp: str, itm: bool = False, exp_index: int = 0,
                    below: bool = False):
    """The key of the current (exp_index 0) expiry's cp contract whose mid at snapshot i is closest to `target`
    (in the money only if itm: calls below spot, puts above; at or below the target only if below); None if none."""
    if not day.exp or i < 0:
        return None
    exp = day.exp[min(exp_index, len(day.exp) - 1)]
    s = float(day.spot[i])
    best, bd = None, float("inf")
    for key in day.q:
        if key[0] != exp or key[2] != cp:
            continue
        if itm and not ((key[1] < s) if cp == "C" else (key[1] > s)):
            continue
        p = mid_of(day, key, i)
        if below and np.isfinite(p) and p > target:
            continue
        if np.isfinite(p) and abs(p - target) < bd:
            best, bd = key, abs(p - target)
    return best


def pool_of(days: list[ChainDay], picks: dict) -> list:
    """The markets of the picked contract-days: picks = {date: {key, ...}}; each carries the previous session's quotes
    of the same contract when that session was recorded."""
    out = []
    for i, day in enumerate(days):
        prev = previous_session(days, i, 4)
        for key in sorted(picks.get(day.date, ())):
            m = contract_market(day, key, prev)
            if m is not None:
                out.append(m)
    return out
