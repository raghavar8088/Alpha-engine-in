"""NSE Stock Ratings: market data. A rolling store of NSE's daily price files, and what the
table reads from it.

WHAT IT HOLDS
One gzipped file per session for the last KEEP_SESSIONS sessions (about 1.3 years, ~11 MB):
  prices/YYYY-MM-DD.json.gz   {symbol: [close, prev_close, qty, turnover_lacs, trades, deliv_pct]}
  indices/YYYY-MM-DD.json.gz  {index name: close}
They live on the intraday data volume, not in Atlas, because this is bulk history and
Atlas is near its quota. The format is the one backend/research/nse_forecast_2026_11 uses,
so the validation and production read the same files the same way.

HOLIDAY FILES ARE CHECKED BY THEIR OWN DATE
On a holiday NSE serves the previous session's file under the holiday's date. 26 Jan 2022
is 25 Jan's file, close for close. Every file's DATE1 is checked against the date asked
for, so a holiday never becomes a fake session with zero returns.

WHAT IT COMPUTES, ONCE A DAY AFTER THE CLOSE (refresh_market)
  historical returns  1D 1W 1M 2M 3M 6M 1Y from the store, and 2Y 5Y from that day's anchor
                      files. All of them use closes adjusted for bonuses, splits and
                      consolidations, from NSE's corporate-actions feed
  relative            1Y against the Nifty 500, and 3M and 1Y against the sector median
  risk and liquidity  1-year volatility, max drawdown and beta to the Nifty 500; distance
                      from the 52-week high; median daily traded value, no-trade days and
                      delivery %
  momentum            12-1 month, 6-month and 52-week-high percentiles, combined into a
                      0-10 score
  estimates           1D 1W 1M 3M ranges (nse_ratings_logic.estimate)
A daily move beyond |ln| 0.40 (-33% / +49%) is outside every NSE price band, so it is an
unrecorded corporate action or a data error. No volatility, drawdown or estimate is read
across one, and a return that spans one is withheld with a note, never shown wrong.
"""

from __future__ import annotations

import asyncio
import bisect
import csv
import gzip
import io
import json
import logging
import math
import os
import warnings
from datetime import date, datetime, timedelta, timezone

import numpy as np
from pymongo import UpdateOne

from app.core.db import db
from app.services import market_calendar
from app.services import nse_ratings_logic as L
from app.services.nse_client import nse

logger = logging.getLogger("nse_market")

rows = db["nse_stock_ratings"]
meta = db["nse_stock_ratings_meta"]

DATA_DIR = os.getenv("NSE_RATINGS_DATA_DIR") or os.path.join(
    os.getenv("INTRADAY_DATA_DIR") or "/data/intraday", "nse_ratings")
KEEP_SESSIONS = int(os.getenv("NSE_RATINGS_KEEP_SESSIONS", "330"))
RETURNS_AFTER_HHMM = "19:30"
BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
INDEX = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
SYMBOL_CHANGES = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
CA_API = "/api/corporates-corporateActions?index=equities&from_date={a}&to_date={b}"
CA_REFERER = "/companies-listing/corporate-filings-actions"
KEEP_SERIES = ("EQ", "BE", "BZ")
BREAK = 0.40
YEAR = 252
BENCHMARK = "Nifty 500"
INDEX_NAMES = ("Nifty 50", "Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250")
STORE_HORIZONS = (("r1d", None, 1), ("r1w", None, 5), ("r1m", 1, None), ("r2m", 2, None),
                  ("r3m", 3, None), ("r6m", 6, None), ("r1y", 12, None))
ANCHOR_HORIZONS = (("r2y", 24, "2Y"), ("r5y", 60, "5Y"))
# Version of the market fields alone. A bump recomputes them on the next cycle without rebuilding the rating rows
# (L.ROW_VERSION does that). 2 = the all-time-high fields.
MARKET_V = 2


def ath_fields(close: float | None, traded_today: bool, store_hi: float | None, store_hi_day: str | None,
               prior_hi: float | None, stored: float | None, stored_day: str | None, listed_on: date | None,
               store_start: date, today: str) -> dict:
    """A stock's all-time high and how far its latest close is below it.

    The high is the higher of two numbers:
      - `stored`: the All Time High desk's full-history high (stock_highs). It is Angel's daily candles walked back to
        the listing date, and is the app's one genuine all-time-high source;
      - `store_hi`: the highest adjusted close in this module's own price store, which keeps it current where
        stock_highs has not been raised since it was seeded.
    With no stored high, the store alone answers only for a stock that listed inside the store, since it then holds the
    whole history. Anything else is unknown and stays out of every all-time-high filter, never guessed.

    `ath_new`: the latest session made a new all-time high. Either stock_highs moved to today, or today's close is above
    every earlier high, including the stored intraday peak.
    """
    none = {"ath": None, "ath_date": None, "from_ath": None, "ath_new": None, "ath_basis": None}
    if close is None or close <= 0:
        return none
    if stored:
        basis = "history"
    elif store_hi is not None and listed_on is not None and listed_on >= store_start:
        basis = "listing"
    else:
        return none
    cands = [(float(stored), stored_day)] if stored else []
    if store_hi is not None:
        cands.append((float(store_hi), store_hi_day))
    ath, ath_day = max(cands, key=lambda x: x[0])
    earlier = max([x for x in (prior_hi, float(stored) if stored and stored_day != today else None) if x is not None],
                  default=None)
    new = bool(stored and stored_day == today) or (traded_today and earlier is not None and close >= earlier)
    return {"ath": round(ath, 2), "ath_date": ath_day, "from_ath": round(min(0.0, (close / ath - 1) * 100), 2),
            "ath_new": new, "ath_basis": basis}


def _ist_now() -> datetime:
    return datetime.now(L.IST)


# ── the store ────────────────────────────────────────────────────────────────────


def _path(kind: str, d: date) -> str:
    return os.path.join(DATA_DIR, kind, f"{d.isoformat()}.json.gz")


def _read(path: str) -> dict | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


def _missing() -> dict[str, int]:
    try:
        with open(os.path.join(DATA_DIR, "missing.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_missing(m: dict[str, int]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "missing.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh)


def stored_days() -> list[date]:
    try:
        names = os.listdir(os.path.join(DATA_DIR, "prices"))
    except OSError:
        return []
    out = []
    for n in names:
        if n.endswith(".json.gz"):
            try:
                out.append(date.fromisoformat(n[:10]))
            except ValueError:
                continue
    return sorted(out)


def _num(v):
    try:
        s = str(v).strip().replace(",", "")
        return None if s in ("", "-", "nan") else float(s)
    except ValueError:
        return None


def parse_bhav(text: str, day: date) -> dict | None:
    """{symbol: [close, prev, qty, turnover, trades, deliv]}, or None for a holiday copy."""
    if text[:2] == "PK":                    # an Excel workbook, as on 8 Aug 2022
        return None
    rec, seen = {}, None
    try:
        for raw in csv.DictReader(io.StringIO(text, newline="")):
            x = {(k or "").strip(): (v.strip() if isinstance(v, str) else "")
                 for k, v in raw.items() if isinstance(k, str)}
            if seen is None and x.get("DATE1"):
                seen = L.parse_nse_date(x["DATE1"])
            if x.get("SERIES") in KEEP_SERIES and x.get("SYMBOL"):
                rec[x["SYMBOL"].upper()] = [_num(x.get("CLOSE_PRICE")), _num(x.get("PREV_CLOSE")),
                                            _num(x.get("TTL_TRD_QNTY")), _num(x.get("TURNOVER_LACS")),
                                            _num(x.get("NO_OF_TRADES")), _num(x.get("DELIV_PER"))]
    except csv.Error:
        return None
    if seen is not None and seen != day:
        return None                          # the previous session's file, served for a holiday
    return rec if len(rec) > 500 else None


async def _fetch_session(d: date) -> bool:
    """Fetch one session's price and index files. True when the price file was stored."""
    r = await nse.get(BHAV.format(d=d.strftime("%d%m%Y")), tries=2)
    if r is None:
        return False
    rec = parse_bhav(r.text, d)
    if rec is None:
        return False
    _write(_path("prices", d), rec)
    ri = await nse.get(INDEX.format(d=d.strftime("%d%m%Y")), tries=2)
    if ri is not None:
        idx = {}
        try:
            for raw in csv.DictReader(io.StringIO(ri.text, newline="")):
                x = {(k or "").strip(): (v.strip() if isinstance(v, str) else "")
                     for k, v in raw.items() if isinstance(k, str)}
                if x.get("Index Name"):
                    idx[x["Index Name"]] = _num(x.get("Closing Index Value"))
        except csv.Error:
            idx = {}
        if idx:
            _write(_path("indices", d), idx)
    return True


def expected_close_day(now: datetime) -> date:
    """The latest session whose bhavcopy should be out by now."""
    d = now.date()
    if d.weekday() < 5 and market_calendar.is_listed_trading_day(d) and now.strftime("%H:%M") >= RETURNS_AFTER_HHMM:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5 or not market_calendar.is_listed_trading_day(d):
        d -= timedelta(days=1)
    return d


async def sync_store(latest: date, max_fetches: int = 900) -> dict:
    """Fill the store back from `latest` until it holds KEEP_SESSIONS sessions, then prune.

    Newest first, so a first fill is useful long before it is finished. A weekday NSE
    has no file for is tried on up to three runs and then left alone, like nse_events.
    """
    have = set(stored_days())
    miss = _missing()
    fetched = added = 0
    d, sessions = latest, 0
    floor = latest - timedelta(days=int(KEEP_SESSIONS * 1.6) + 20)
    while d >= floor and sessions < KEEP_SESSIONS:
        if d.weekday() < 5:
            if d in have:
                sessions += 1
            elif miss.get(d.isoformat(), 0) < 3 and fetched < max_fetches:
                fetched += 1
                if await _fetch_session(d):
                    have.add(d)
                    sessions += 1
                    added += 1
                elif (latest - d).days > 3:
                    # The last few days are always asked for again: a file published late
                    # in the evening must not be written off after three early tries.
                    miss[d.isoformat()] = miss.get(d.isoformat(), 0) + 1
        d -= timedelta(days=1)
    _save_missing(miss)
    days = sorted(have)
    pruned = 0
    for old in days[:-(KEEP_SESSIONS + 10)] if len(days) > KEEP_SESSIONS + 10 else []:
        for kind in ("prices", "indices"):
            try:
                os.remove(_path(kind, old))
                pruned += 1
            except OSError:
                pass
    return {"sessions": min(sessions, KEEP_SESSIONS), "added": added, "fetched": fetched, "pruned": pruned}


# ── reference data: corporate actions and symbol changes ─────────────────────────


async def corporate_actions(frm: date, to: date) -> dict[str, list[dict]] | None:
    """{symbol: [action...]} over the window, asked for a year at a time."""
    out: dict[str, list[dict]] = {}
    cur = frm
    while cur <= to:
        end = min(to, cur + timedelta(days=365))
        body = await nse.api(CA_API.format(a=cur.strftime("%d-%m-%Y"), b=end.strftime("%d-%m-%Y")), CA_REFERER)
        items = body if isinstance(body, list) else (body.get("data") if isinstance(body, dict) else None)
        if items is None:
            return None
        for it in items:
            if not isinstance(it, dict) or (it.get("series") or "EQ") not in KEEP_SERIES:
                continue
            act = L.parse_action(it.get("subject") or "")
            ex = L.parse_nse_date(it.get("exDate"))
            sym = (it.get("symbol") or "").strip().upper()
            if act and ex and sym:
                out.setdefault(sym, []).append({**act, "ex": ex, "subject": it.get("subject")})
        cur = end + timedelta(days=1)
    return out


async def symbol_changes() -> dict[str, tuple[str, date]]:
    """old symbol -> (new symbol, effective date)."""
    r = await nse.get(SYMBOL_CHANGES, tries=2)
    out: dict[str, tuple[str, date]] = {}
    if r is None:
        return out
    for raw in csv.DictReader(io.StringIO(r.text, newline="")):
        x = {(k or "").strip().upper(): (v.strip() if isinstance(v, str) else "")
             for k, v in raw.items() if isinstance(k, str)}
        old, new = x.get("OLD SYMBOL", "").upper(), x.get("NEW SYMBOL", "").upper()
        eff = L.parse_nse_date(x.get("EFFECTIVE DATE"))
        if old and new and eff and old != new and (old not in out or out[old][1] < eff):
            out[old] = (new, eff)
    return out


def canon(sym: str, d: date, renames: dict) -> str:
    """The symbol a row from day `d` belongs to today."""
    for _ in range(5):
        hit = renames.get(sym)
        if not hit or d >= hit[1]:
            return sym
        sym = hit[0]
    return sym


# ── the computation (numpy, run in a worker thread) ──────────────────────────────


def _months_idx(days: list[date], latest: date, months: int) -> int | None:
    target = L.months_back(latest, months)
    for i in range(len(days) - 1, -1, -1):
        if days[i] <= target:
            return i
    return None


def compute(days: list[date], renames: dict, actions: dict, meta_rows: dict,
            anchors: dict, cal: dict, highs: dict | None = None) -> tuple[dict, dict]:
    """Every market field for every listed symbol, plus index returns for the header.
    `highs`: {symbol: stock_highs document} for the all-time-high fields (empty: listing-only)."""
    # Stocks with no trade in a window produce all-NaN slices; that is expected, not news.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return _compute(days, renames, actions, meta_rows, anchors, cal, highs or {})


def _compute(days: list[date], renames: dict, actions: dict, meta_rows: dict,
             anchors: dict, cal: dict, highs: dict | None = None) -> tuple[dict, dict]:
    highs = highs or {}
    # Two passes over the files, keeping none of them: 330 parsed days held at once would be
    # some 350 MB of Python objects in a backend that runs near its 800 MB cap. float32 and
    # int16 keep the whole computation near 35 MB.
    T = len(days)
    symset = set()
    for d in days:
        symset.update(canon(s, d, renames) for s in (_read(_path("prices", d)) or {}))
    syms = sorted(symset)
    col = {s: i for i, s in enumerate(syms)}
    N = len(syms)
    C = np.full((T, N), np.nan, dtype=np.float32)
    TV = np.zeros((T, N), dtype=np.float32)
    DL = np.full((T, N), np.nan, dtype=np.float32)
    for t, d in enumerate(days):
        for s, v in (_read(_path("prices", d)) or {}).items():
            j = col[canon(s, d, renames)]
            if v[0]:
                C[t, j] = v[0]
                TV[t, j] = (v[3] or 0.0) / 100.0          # Rs lakh -> Rs crore
                if v[5] is not None:
                    DL[t, j] = v[5]

    # adjust for share-count changes; mark the rest as breaks
    brk = np.zeros((T, N), dtype=bool)
    brk_label: dict[tuple[int, int], str] = {}
    for sym, acts in actions.items():
        for a in acts:
            ex = a["ex"]
            j = col.get(canon(sym, ex, renames))
            if j is None or ex <= days[0] or ex > days[-1]:
                continue
            t_ex = bisect.bisect_left(days, ex)
            if a.get("factor"):
                C[:t_ex, j] *= a["factor"]
            if a.get("unadjusted"):
                brk[t_ex, j] = True
                brk_label[(t_ex, j)] = f"a {', '.join(a['unadjusted'])} (ex {L.fmt_day(ex)})"

    traded = ~np.isnan(C)
    R = np.full((T, N), np.nan, dtype=np.float32)
    last = np.full(N, np.nan, dtype=np.float32)
    jump = np.zeros((T, N), dtype=bool)
    for t in range(T):
        ok = traded[t]
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.log(C[t] / last)
        j_ = ok & ~np.isnan(r) & (np.abs(r) > BREAK)
        jump[t] = j_
        for j in np.nonzero(j_)[0]:
            brk_label.setdefault((t, int(j)), f"a one-day move of {math.expm1(r[j]) * 100:+.0f}% on "
                                              f"{L.fmt_day(days[t])} with no corporate action in NSE's feed")
        r[~ok | brk[t] | j_] = np.nan
        R[t] = r
        last = np.where(ok, C[t], last)

    # forward-filled closes (a non-trading day is marked at the last trade, up to 5 sessions)
    Cf = C.copy()
    age = np.zeros(N)
    for t in range(1, T):
        m = np.isnan(Cf[t])
        age = np.where(m, age + 1, 0)
        Cf[t] = np.where(m & (age <= 5), Cf[t - 1], Cf[t])

    t0 = T - 1
    lastidx = np.where(traded.any(axis=0), T - 1 - np.argmax(traded[::-1], axis=0), -1)
    stale = np.where(lastidx >= 0, t0 - lastidx, 999)
    close = np.where(stale <= 5, C[np.clip(lastidx, 0, None), np.arange(N)], np.nan)

    # all-time high inputs (ath_fields): the highest adjusted close in the store and on which day, and the highest
    # before the latest session
    Cm = np.where(np.isnan(C), -np.inf, C)
    hi_t = np.argmax(Cm, axis=0)
    store_hi = Cm[hi_t, np.arange(N)]
    prior_hi = Cm[:t0].max(axis=0) if t0 > 0 else np.full(N, -np.inf, dtype=np.float32)
    del Cm

    # volatility state
    v = np.full(N, np.nan, dtype=np.float64)
    lam = cal.get("lambda", 0.94)
    for t in range(T):
        x2 = np.nan_to_num(R[t]) ** 2
        ok = ~np.isnan(R[t])
        v = np.where(ok, np.where(np.isnan(v), x2, lam * v + (1 - lam) * x2), v)
    win = R[max(0, T - YEAR):]
    n_ret = (~np.isnan(win)).sum(axis=0)
    with np.errstate(invalid="ignore"):
        lr = np.nanvar(win, axis=0, ddof=1)
    lr[n_ret < L.EST_MIN_RETURNS] = np.nan

    # index series, each file read once
    idx_close = {nm: np.full(T, np.nan) for nm in INDEX_NAMES}
    for t, d in enumerate(days):
        got = _read(_path("indices", d)) or {}
        for nm in INDEX_NAMES:
            if got.get(nm):
                idx_close[nm][t] = got[nm]
    bench = idx_close[BENCHMARK]
    with np.errstate(invalid="ignore", divide="ignore"):
        bench_r = np.log(bench[1:] / bench[:-1])
    bench_r = np.concatenate([[np.nan], bench_r])

    # returns over each horizon, on adjusted, forward-filled closes
    ret: dict[str, np.ndarray] = {}
    ret_note: dict[str, dict[int, str]] = {}
    idx_ret: dict[str, dict[str, float | None]] = {nm: {} for nm in INDEX_NAMES}
    cum_brk = np.cumsum(brk | jump, axis=0, dtype=np.int16)
    cum_jump = np.cumsum(jump, axis=0, dtype=np.int16)
    del brk
    for key, months, sessions in STORE_HORIZONS:
        a = (t0 - sessions) if sessions else _months_idx(days, days[t0], months)
        if a is None or a < 0:
            ret[key] = np.full(N, np.nan)
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            r_ = (close / Cf[a] - 1) * 100
        span_jump = (cum_jump[t0] - cum_jump[a]) > 0
        r_[span_jump] = np.nan
        notes = {}
        for j in np.nonzero(((cum_brk[t0] - cum_brk[a]) > 0))[0]:
            lab = next((brk_label[(t, int(j))] for t in range(a + 1, T) if (t, int(j)) in brk_label), None)
            if lab:
                notes[int(j)] = ("withheld: " if span_jump[j] else "not adjusted for ") + lab
        ret[key], ret_note[key] = r_, notes
        for nm in INDEX_NAMES:
            s_ = idx_close[nm]
            idx_ret[nm][key] = (round(float((s_[t0] / s_[a] - 1) * 100), 2)
                                if not (np.isnan(s_[t0]) or np.isnan(s_[a])) else None)

    # risk and liquidity over the last year
    w0 = max(0, T - YEAR)
    W = Cf[w0:]
    valid_cnt = (~np.isnan(W)).sum(axis=0)
    with np.errstate(invalid="ignore"):
        runmax = np.fmax.accumulate(np.where(np.isnan(W), -np.inf, W), axis=0)
        dd = np.where(np.isnan(W), np.nan, W / runmax - 1)
        mdd = np.nanmin(dd, axis=0) * 100
        hi = np.nanmax(W, axis=0)
        from_high = (close / hi - 1) * 100
        vol_1y = np.sqrt(lr) * math.sqrt(YEAR) * 100
    year_jump = (cum_jump[t0] - cum_jump[w0]) > 0
    mdd[(valid_cnt < 120) | year_jump] = np.nan
    from_high[year_jump] = np.nan
    bw = bench_r[w0:]
    beta = np.full(N, np.nan)
    for j in range(N):
        x = win[:, j]
        m = ~np.isnan(x) & ~np.isnan(bw)
        if m.sum() >= 120:
            vb = np.var(bw[m], ddof=1)
            if vb > 0:
                beta[j] = np.cov(x[m], bw[m], ddof=1)[0, 1] / vb
    tv_3m = np.median(TV[max(0, T - 63):], axis=0)
    notrade = 1 - traded[max(0, T - 63):].sum(axis=0) / min(63, T)
    deliv = np.full(N, np.nan)
    for j in range(N):
        dj = DL[:, j][traded[:, j]][-20:]
        dj = dj[~np.isnan(dj)]
        if len(dj):
            deliv[j] = float(dj.mean())

    # momentum: 12-1 month, 6 month, 52-week high, as cross-sectional percentiles
    a12, a1 = _months_idx(days, days[t0], 12), _months_idx(days, days[t0], 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mom = (Cf[a1] / Cf[a12] - 1) if (a12 is not None and a1 is not None) else np.full(N, np.nan)
    if a12 is not None:
        mom[(cum_jump[t0] - cum_jump[a12]) > 0] = np.nan

    listed = [j for j, s in enumerate(syms) if s in meta_rows]

    def pct(arr):
        out = np.full(N, np.nan)
        ids = [j for j in listed if not np.isnan(arr[j])]
        if len(ids) < 20:
            return out
        vals = arr[ids]
        order = vals.argsort().argsort()
        out[ids] = (order + 0.5) / len(ids)
        return out

    p_mom, p_6m, p_hi, p_vol = pct(mom), pct(ret["r6m"]), pct(from_high), pct(vol_1y)

    # sector medians for relative returns
    by_sector: dict[str, list[int]] = {}
    for j in listed:
        by_sector.setdefault(meta_rows[syms[j]].get("sector") or "Unclassified", []).append(j)

    def sector_rel(arr):
        out = np.full(N, np.nan)
        for sec, ids in by_sector.items():
            vals = arr[ids]
            ok = ~np.isnan(vals)
            if ok.sum() >= 5 and sec != "Unclassified":
                med = float(np.median(vals[ok]))
                out[ids] = vals - med
        return out

    r1y_sec, r3m_sec = sector_rel(ret["r1y"]), sector_rel(ret["r3m"])
    n500_1y = idx_ret[BENCHMARK].get("r1y")

    result: dict[str, dict] = {}
    for j in listed:
        s = syms[j]
        m = meta_rows[s]
        f = lambda arr, d=2: (None if np.isnan(arr[j]) else round(float(arr[j]), d))  # noqa: E731
        doc = {key: f(ret[key]) for key, _, _ in STORE_HORIZONS}
        notes = [ret_note[key][j] for key, _, _ in STORE_HORIZONS if j in ret_note.get(key, {})]
        # 2Y and 5Y from that day's anchor files
        an = anchors.get(s) or {}
        for key, _m, label in ANCHOR_HORIZONS:
            doc[key] = an.get(key)
        notes += an.get("notes") or []
        score, comp = L.momentum_score(None if np.isnan(p_mom[j]) else float(p_mom[j]),
                                       None if np.isnan(p_6m[j]) else float(p_6m[j]),
                                       None if np.isnan(p_hi[j]) else float(p_hi[j]))
        recent = next((brk_label[(t, j)] for t in range(max(0, T - 63), T) if (t, j) in brk_label), None)
        terc = None if np.isnan(p_vol[j]) else min(2, int(p_vol[j] * 3))
        # The same three percentiles the validation ranked on: 12-1 month return, close
        # against the 52-week high, and low volatility (1 - the volatility percentile).
        sigs = {"mom_12_1": None if np.isnan(p_mom[j]) else float(p_mom[j]),
                "prox_52w": None if np.isnan(p_hi[j]) else float(p_hi[j]),
                "low_vol": None if np.isnan(p_vol[j]) else 1.0 - float(p_vol[j])}
        est = L.estimate(None if np.isnan(close[j]) else float(close[j]),
                         None if np.isnan(v[j]) else float(v[j]),
                         None if np.isnan(lr[j]) else float(lr[j]),
                         int(n_ret[j]), float(notrade[j]), int(stale[j]), recent, m.get("series"),
                         terc, float(tv_3m[j]), cal, sigs)
        doc.update({
            "ret_asof": days[t0].isoformat(),
            "ret_close": f(close),
            "ret_notes": list(dict.fromkeys(notes)),
            "r1y_vs_n500": (round(doc["r1y"] - n500_1y, 2) if doc.get("r1y") is not None and n500_1y is not None else None),
            "r1y_vs_sector": f(r1y_sec), "r3m_vs_sector": f(r3m_sec),
            "vol_1y": f(vol_1y, 1), "mdd_1y": f(mdd, 1), "beta_1y": f(beta), "from_high": f(from_high, 1),
            "tv_3m": f(tv_3m), "notrade_3m": round(float(notrade[j]) * 100, 1), "deliv_20d": f(deliv, 1),
            "mom_12_1": None if np.isnan(mom[j]) else round(float(mom[j]) * 100, 1),
            "mom_score": score, "mom_pct": comp, "vol_tercile": terc,
            "est": est, "est_asof": days[t0].isoformat(),
        })
        hdoc = highs.get(s) or {}
        doc.update(ath_fields(
            None if np.isnan(close[j]) else float(close[j]), bool(lastidx[j] == t0),
            None if np.isinf(store_hi[j]) else float(store_hi[j]),
            None if np.isinf(store_hi[j]) else days[int(hi_t[j])].isoformat(),
            None if np.isinf(prior_hi[j]) else float(prior_hi[j]),
            hdoc.get("all_time_high"), hdoc.get("all_time_high_date"), L.as_date(m.get("listed_on")),
            days[0], days[t0].isoformat()))
        for hk, _lbl in L.EST_HORIZONS:
            e = est.get(hk) or {}
            ok = e.get("status") == "ok"
            doc[f"e{hk}_base"] = e.get("base") if ok else None
            doc[f"e{hk}_down"] = e.get("down") if ok else None
            doc[f"e{hk}_conf"] = e.get("conf") if ok else "insufficient"
        result[s] = doc
    header = {"as_of": days[t0].isoformat(), "sessions": T, "indices": idx_ret,
              "symbols_priced": int((~np.isnan(close)).sum())}
    return result, header


# ── 2Y and 5Y from anchor files ──────────────────────────────────────────────────


async def _bhav_day(d: date, cache: dict) -> dict | None:
    if d in cache:
        return cache[d]
    stored = _read(_path("prices", d))
    if stored is None:
        r = await nse.get(BHAV.format(d=d.strftime("%d%m%Y")), tries=2)
        stored = parse_bhav(r.text, d) if r is not None else None
    cache[d] = stored
    return stored


async def _on_or_before(d: date, cache: dict, tries: int = 8) -> tuple[date | None, dict | None]:
    for _ in range(tries):
        if d.weekday() < 5:
            got = await _bhav_day(d, cache)
            if got:
                return d, got
        d -= timedelta(days=1)
    return None, None


async def _after(d: date, limit: date, cache: dict, tries: int = 8) -> dict | None:
    d += timedelta(days=1)
    for _ in range(tries):
        if d > limit:
            return None
        if d.weekday() < 5:
            got = await _bhav_day(d, cache)
            if got:
                return got
        d += timedelta(days=1)
    return None


async def anchor_returns(latest_day: date, latest: dict, renames: dict, actions: dict,
                         meta_rows: dict) -> dict:
    """{symbol: {"r2y", "r5y", "notes"}} from the anchor sessions' own files."""
    cache: dict = {latest_day: latest}
    anchors = {}
    for key, months, label in ANCHOR_HORIZONS:
        ad, adata = await _on_or_before(L.months_back(latest_day, months), cache)
        ndata = await _after(ad, latest_day, cache) if ad else None
        anchors[key] = (ad, adata, ndata)
    back = {}
    for old, (new, eff) in renames.items():
        back.setdefault(new, []).append((old, eff))
    out = {}
    for sym, m in meta_rows.items():
        names = [sym] + [o for o, _ in back.get(sym, [])]
        lc = next((latest[n][0] for n in names if latest and n in latest and latest[n][0]), None)
        vals = {}
        for key, (ad, adata, ndata) in anchors.items():
            if ad is None:
                vals[key] = (None, None)
                continue
            cands = [sym] + [o for o, eff in back.get(sym, []) if eff > ad]
            c = None
            for n in cands:
                c = ((adata or {}).get(n) or [None])[0] or ((ndata or {}).get(n) or [None, None])[1]
                if c:
                    break
            vals[key] = (ad, c)
        acts = [a for n in names for a in actions.get(n, [])]
        res = L.compute_returns((latest_day, lc) if lc else None, vals, acts,
                                L.as_date(m.get("listed_on")), horizons=ANCHOR_HORIZONS)
        out[sym] = {"r2y": res.get("r2y"), "r5y": res.get("r5y"), "notes": res.get("ret_notes") or [],
                    "detail": res.get("ret_detail") or {}}
    return out


# ── the step ─────────────────────────────────────────────────────────────────────


async def refresh_market(force: bool = False) -> dict:
    """Bring the store up to the latest close and recompute every market field."""
    want = expected_close_day(_ist_now())
    stored = await meta.find_one({"_id": "market"}, {"as_of": 1, "v": 1, "cal": 1, "mv": 1})
    cal = L.calibration()
    cal_version = cal.get("version")
    synced = await sync_store(want)
    days = stored_days()[-KEEP_SESSIONS:]
    if len(days) < 30:
        raise RuntimeError(f"the price store holds only {len(days)} sessions")
    latest_day = days[-1]
    if (not force and stored and stored.get("as_of") == latest_day.isoformat()
            and stored.get("v") == L.ROW_VERSION and stored.get("cal") == cal_version
            and stored.get("mv") == MARKET_V):
        await meta.update_one({"_id": "market"}, {"$set": {"checked_at": datetime.now(timezone.utc)}})
        return {"skipped": f"already computed for {latest_day.isoformat()}", "store": synced}

    since = L.months_back(latest_day, 60) - timedelta(days=10)
    actions = await corporate_actions(since, latest_day)
    if actions is None:
        raise RuntimeError("NSE's corporate-actions feed did not answer; market fields not recomputed")
    renames = await symbol_changes()
    meta_rows = {d["_id"]: d async for d in rows.find(
        {"listed": True}, {"sector": 1, "series": 1, "listed_on": 1})}
    latest = _read(_path("prices", latest_day)) or {}
    anchors = await anchor_returns(latest_day, latest, renames, actions, meta_rows)
    try:                                     # the All Time High desk's full-history highs; without them, listing-only
        highs = {d["symbol"]: d async for d in db["stock_highs"].find(
            {}, {"_id": 0, "symbol": 1, "all_time_high": 1, "all_time_high_date": 1})}
    except Exception:                        # noqa: BLE001 - never let it stop the returns
        logger.warning("nse market: stock_highs unreadable; all-time highs from the store only")
        highs = {}

    result, header = await asyncio.to_thread(compute, days, renames, actions, meta_rows, anchors, cal, highs)

    ops = []
    for sym, doc in result.items():
        detail = (anchors.get(sym) or {}).get("detail")
        ops.append(UpdateOne({"_id": sym}, {"$set": {**doc, "ret_detail": detail}}))
    for i in range(0, len(ops), 500):
        await rows.bulk_write(ops[i:i + 500], ordered=False)
    doc = {"_id": "market", "at": datetime.now(timezone.utc), "checked_at": datetime.now(timezone.utc),
           "as_of": latest_day.isoformat(), "v": L.ROW_VERSION, "cal": cal_version, "mv": MARKET_V,
           "store": synced, "rows": len(ops), **header}
    await meta.replace_one({"_id": "market"}, doc, upsert=True)
    logger.info("nse market fields as of %s: %d rows, %d sessions in the store", latest_day, len(ops), header["sessions"])
    return {k: v for k, v in doc.items() if k not in ("_id", "indices")}
