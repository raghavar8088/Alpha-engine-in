"""Market data for the paper desk, in the studies' Minutes layout.

  NIFTY, BANKNIFTY   the box's 1-minute store (/data/intraday/idx1m, read-only) through the app's own cleaner, plus
                     today's finished minutes from the backend's index feed
  NSE stocks         the box's 5-minute store (/data/intraday/5m, read-only), plus today's closed bars from the backend
  EUR/USD, GBP/USD,  Yahoo 1-minute bars, kept in our own append-only store (a stored minute is never rewritten).
  Nasdaq 100, Apple  Nasdaq 100 is the cash index. Silver (SI=F) is only CP-24's comparison market.
  bitcoin, gold      Delta Exchange India's BTCUSD and XAUTUSD perpetuals, 1-minute candles (gold: the gold week only)
  S&P 500, Nasdaq    Yahoo daily bars, appended once each session has finished
  daily
  NSE stocks daily   the study's bhavcopy panel (seeded from research data), extended from NSE's daily bhavdata file
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research import BM, CPM, II, YM
from settings import APP_SECRET, BACKEND, DATA, INTRADAY, IST, NSE_FINAL_HHMM, NY

log = logging.getLogger("premium.feeds")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SESSION_ROWS = 375


# ── the backend's live bars ──────────────────────────────────────────────────────────

LIVE_LAST: dict = {}     # {feed: start of the last live bar that really arrived this cycle}, for the status page

def today_bars(group: str) -> dict:
    """Today's finished bars held in the backend's memory. Empty if the backend cannot answer: the day's trades then
    simply appear once its bars reach the store after the close."""
    req = urllib.request.Request(f"{BACKEND}/api/premium-paper/today-bars?group={group}&fresh=1",
                                 headers={"x-app-secret": APP_SECRET} if APP_SECRET else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except Exception as exc:  # noqa: BLE001
        log.warning("today-bars %s: %s", group, exc)
        return {}


def nse_final_day(now: datetime, disk_last: str | None) -> str:
    """The last session whose bars are final: the session has ended, Angel's candles have replaced the stream's, and
    the store holds it."""
    d = now.date() if now.strftime("%H:%M") >= NSE_FINAL_HHMM else now.date() - timedelta(days=1)
    final = d.isoformat()
    return min(final, disk_last) if disk_last else "0000-00-00"


# ── indices ──────────────────────────────────────────────────────────────────────────

def index_market(name: str, since: date, live_rows, now: datetime):
    """(Minutes, the live day or None, the last day in the store). Same layout as bb_markets._load_index."""
    d = II._build(name, II._read(name, since))
    keep = d.dates >= np.datetime64(since)
    d = II.Days(d.name, d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep], d.quality)
    disk_last = str(d.dates[-1]) if len(d.dates) else None
    today, live_day = now.date(), None
    if live_rows and disk_last != today.isoformat():
        upto = min(SESSION_ROWS, now.hour * 60 + now.minute - (9 * 60 + 15))
        minutes = {int(r[0]): tuple(float(x) for x in r[1:6]) for r in live_rows}
        open_t = int(datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST).timestamp())
        real = [x for x in minutes if open_t <= x < open_t + 60 * SESSION_ROWS]
        # The day runs to the last minute that really arrived, never further: a stalled feed stops the day instead of
        # repeating its last price (with_today fills only the gaps before that minute, as the study's cleaner does).
        upto = min(upto, (max(real) - open_t) // 60 + 1) if real else 0
        if real:
            LIVE_LAST[name] = max(real)
        if upto > 0:
            d = II.with_today(d, minutes, today, upto)
            live_day = today.isoformat()
    dates = np.array(d.dates, dtype="datetime64[D]")
    base = dates.astype("datetime64[s]").astype(np.int64) + 9 * 3600 + 15 * 60 - 19800
    t = (base[:, None] + 60 * np.arange(SESSION_ROWS)[None, :]).ravel()
    o, h, l, c = (np.asarray(a, float).ravel() for a in (d.o, d.h, d.l, d.c))
    key = np.repeat(dates.astype(np.int64), SESSION_ROWS)
    z = np.zeros_like(o)
    return BM._finish(name, t, o, h, l, c, z, np.ones_like(o), key, False), live_day, disk_last


# ── Yahoo: 1-minute store ────────────────────────────────────────────────────────────

# gold is no longer read from Yahoo (GC=F): it comes from Delta Exchange (XAUTUSD), below
YF = {"EURUSD": "6E=F", "GBPUSD": "6B=F", "NAS100": "NQ=F", "AAPL": "AAPL", "XAGUSD": "SI=F"}
CASH = ("NAS100", "AAPL")                       # one regular session a day, by New York date
GOLD_HALF = 0.18                                # the research's median half-spread on gold (Dukascopy quotes)
MAX_DEV = {"XAUUSD": 0.03, "EURUSD": 0.015, "GBPUSD": 0.015, "NAS100": 0.05, "AAPL": 0.08, "XAGUSD": 0.05}


def _chart(sym: str, **params) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym, safe='')}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                res = json.load(r)["chart"]["result"]
            return res[0] if res else {}
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429:                 # told to slow down: take the next cycle, do not push
                break
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(3 + 5 * attempt)
    raise RuntimeError(f"yahoo {sym}: {last}")


def _rows(res: dict) -> tuple[np.ndarray, ...]:
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    t = np.asarray(ts, dtype=np.int64)
    a = [np.asarray(q.get(k) or [np.nan] * len(ts), dtype=float) for k in ("open", "high", "low", "close", "volume")]
    return (t, *a)


def _month_file(name: str, ym: str) -> Path:
    return DATA / "min1" / name / f"{ym}.npz"


def _read_months(name: str, first_ym: str = "") -> tuple[np.ndarray, ...]:
    parts = []
    folder = DATA / "min1" / name
    for f in sorted(folder.glob("*.npz")) if folder.exists() else []:
        if f.stem >= first_ym:
            with np.load(f) as z:
                parts.append(tuple(z[k] for k in ("t", "o", "h", "l", "c", "v")))
    if not parts:
        return (np.empty(0, np.int64), *(np.empty(0) for _ in range(5)))
    return tuple(np.concatenate([p[i] for p in parts]) for i in range(6))


def _ym(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m")


def update_minutes(name: str, now_ts: int | None = None) -> dict:
    """Append finished minutes from Yahoo. Yahoo serves about 30 days of 1-minute bars, in requests of at most 8 days."""
    now_ts = now_ts or int(time.time())
    stored = _read_months(name, _ym(now_ts - 40 * 86400))[0]
    last = int(stored[-1]) if len(stored) else 0
    start = max(last + 60, now_ts - 29 * 86400)
    got = []
    p1 = start
    while p1 < now_ts:
        p2 = min(p1 + 7 * 86400, now_ts)
        got.append(_rows(_chart(YF[name], interval="1m", period1=p1, period2=p2, includePrePost="false")))
        p1 = p2
        if p1 < now_ts:
            time.sleep(1.0)
    if not got:
        return {"new": 0, "last": last}
    t, o, h, l, c, v = (np.concatenate([g[i] for g in got]) for i in range(6))
    # Whole, finished minutes only: the row still forming is never stored, so a stored row can never change.
    keep = (t > last) & (t % 60 == 0) & (t <= now_ts - 120) & np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
    t, o, h, l, c, v = (a[keep] for a in (t, o, h, l, c, v))
    if not len(t):
        return {"new": 0, "last": last}
    t, idx = np.unique(t, return_index=True)
    o, h, l, c, v = (a[idx] for a in (o, h, l, c, v))
    v = np.nan_to_num(v, nan=0.0)
    months = np.array([_ym(int(x)) for x in t])
    for ym in np.unique(months):
        m = months == ym
        path = _month_file(name, str(ym))
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = dict(t=t[m], o=o[m], h=h[m], l=l[m], c=c[m], v=v[m])
        if path.exists():
            with np.load(path) as z:
                cols = {k: np.concatenate([z[k], cols[k]]) for k in cols}
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **cols)
        tmp.replace(path)
    return {"new": int(len(t)), "last": int(t[-1])}


def last_minute(name: str) -> int:
    t = _read_months(name, _ym(int(time.time()) - 40 * 86400))[0]
    return int(t[-1]) if len(t) else 0


def global_market(name: str, since: date):
    """Minutes since `since` (the day structure of bb_markets: 17:00 New York roll, or the cash session)."""
    t0 = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp()) - 86400
    t, o, h, l, c, v = _read_months(name, _ym(t0))
    keep = t >= t0
    t, o, h, l, c, v = (a[keep] for a in (t, o, h, l, c, v))
    if not len(t):
        return None
    mid = (o + c) / 2
    sane = np.maximum(h / mid - 1, 1 - l / mid) <= MAX_DEV[name]      # a bad print would be a fake stop or target
    t, o, h, l, c, v = (a[sane] for a in (t, o, h, l, c, v))
    if name in CASH:
        _, ny = BM._clocks(t)
        reg = (ny >= 9 * 60 + 30) & (ny < 16 * 60)
        t, o, h, l, c, v = (a[reg] for a in (t, o, h, l, c, v))
        key = BM._ny_date_key(t)
    else:
        key = BM._ny_roll_key(t)
    half = GOLD_HALF if name == "XAUUSD" else BM.COSTS[name].half_spread
    vol = np.where(v > 0, v, 1.0).astype(np.float32) if name == "XAUUSD" else np.ones(len(t), np.float32)
    return BM._finish(name, t, o, h, l, c, np.full(len(t), half), vol, key, False)


def slice_from(m, since: date):
    """The same Minutes without the days before `since`."""
    d = int(np.searchsorted(m.date, np.datetime64(since)))
    if d <= 0:
        return m
    a = int(m.d0[d]) if d < m.n_days else len(m.t)
    if a >= len(m.t):
        return None
    counts = (m.d1 - m.d0)[d:]
    key = np.repeat(m.date[d:].astype(np.int64), counts)
    out = BM._finish(m.name, m.t[a:], m.o[a:], m.h[a:], m.l[a:], m.c[a:], m.half[a:], m.vol[a:], key, False)
    out.cost = m.cost
    return out


def global_final_day(name: str, now: datetime | None = None) -> str:
    n = (now or datetime.now(NY)).astimezone(NY)
    done = (n.hour * 60 + n.minute) >= (16 * 60 + 30 if name in CASH else 17 * 60 + 30)
    return (n.date() if done else n.date() - timedelta(days=1)).isoformat()


def usdinr() -> dict:
    """{date: rate} for the last few months, to convert dollar P&L into rupees."""
    res = _chart("INR=X", interval="1d", range="6mo")
    t, _, _, _, c, _ = _rows(res)
    return {datetime.fromtimestamp(int(x), IST).date().isoformat(): round(float(y), 4) for x, y in zip(t, c) if np.isfinite(y)}


# ── daily markets ────────────────────────────────────────────────────────────────────

US_DAILY = {"SPX500_D": ("^GSPC", "SPX500"), "NAS100_D": ("^NDX", "NAS100")}


def us_daily(name: str):
    """Daily rows as yt_markets.daily builds them. Only finished sessions; stored rows are never rewritten."""
    sym, base = US_DAILY[name]
    path = DATA / "daily" / f"{name}.npz"
    have = {}
    if path.exists():
        with np.load(path) as z:
            have = {str(z["date"][i]): tuple(float(z[k][i]) for k in "ohlc") for i in range(len(z["date"]))}
    try:
        t, o, h, l, c, _ = _rows(_chart(sym, interval="1d", range="3y"))
        n = datetime.now(NY)
        today = n.date().isoformat()
        for i in range(len(t)):
            d = datetime.fromtimestamp(int(t[i]), NY).date().isoformat()
            if d in have or not all(np.isfinite(x) for x in (o[i], h[i], l[i], c[i])):
                continue
            if d == today and n.hour * 60 + n.minute < 16 * 60 + 20:
                continue
            have[d] = (float(o[i]), float(h[i]), float(l[i]), float(c[i]))
        if have:
            ds = sorted(have)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, date=np.array(ds), **{k: np.array([have[x][j] for x in ds]) for j, k in enumerate("ohlc")})
            tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("us daily %s: %s", name, exc)
    if len(have) < 210:
        return None
    ds = sorted(have)
    dates = np.array(ds, dtype="datetime64[D]")
    o, h, l, c = (np.array([have[x][j] for x in ds]) for j in range(4))
    t = dates.astype("datetime64[s]").astype(np.int64) + 14 * 3600 + 30 * 60
    ist, ny = BM._clocks(t)
    n = len(t)
    cost = YM.COSTS[base]
    gap = np.r_[99, np.diff(dates.astype(np.int64))]
    k = YM.Mkt(name, t, o, h, l, c, np.full(n, cost.half_spread), np.ones(n, np.float32), ist, ny,
               np.arange(n, dtype=np.int32), np.arange(n, dtype=np.int64), np.arange(1, n + 1, dtype=np.int64), dates,
               gap <= 4, np.zeros(n, bool), cost)
    k.split_key, k.overnight = base, True
    return k


def nifty_daily(since: date, now: datetime):
    m, _, _ = index_market("NIFTY", since, None, now)
    return YM.daily(YM._as_mkt(m, "NIFTY", "NIFTY", YM.COSTS["NIFTY"]))


CM_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"


def _bhav(day: date) -> pd.DataFrame | None:
    req = urllib.request.Request(CM_URL.format(day.strftime("%d%m%Y")),
                                 headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/all-reports"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    df = pd.read_csv(io.BytesIO(raw), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
    out = pd.DataFrame({"symbol": df["SYMBOL"].astype(str).str.strip()})
    for k, col in (("o", "OPEN_PRICE"), ("h", "HIGH_PRICE"), ("l", "LOW_PRICE"), ("c", "CLOSE_PRICE"), ("lacs", "TURNOVER_LACS")):
        out[k] = pd.to_numeric(df[col], errors="coerce")
    out = out.dropna()
    return out[(out["c"] > 0) & (out["h"] >= out["l"])]


NSE_ROOT = DATA / "nse"
NSE_FILE = NSE_ROOT / "data" / "nse_daily.npz"
NSE_KEEP_DAYS = 560                 # calendar days kept in the panel


def nse_daily_update(now: datetime) -> dict:
    """Extend the panel with any finished session NSE has published. Prices are back-adjusted as in yt_bhav_convert.py:
    an overnight ratio below 0.6 or above 1.6 is a corporate action, and every earlier price is multiplied by it."""
    if not NSE_FILE.exists():
        return {"error": "no seed panel"}
    with np.load(NSE_FILE, allow_pickle=False) as zf:
        z = {k: zf[k] for k in zf.files}
    names = [str(x) for x in z["names"]]
    syms = np.array(names)[z["code"]]
    last = pd.Timestamp(z["date"].max()).date()
    wanted = []
    d = last + timedelta(days=1)
    latest = now.date() if now.strftime("%H:%M") >= "19:00" else now.date() - timedelta(days=1)
    while d <= latest:
        if d.weekday() < 5:
            wanted.append(d)
        d += timedelta(days=1)
    frames = []
    for day in wanted:
        df = _bhav(day)
        if df is not None and len(df):
            df["date"] = np.datetime64(day)
            frames.append(df)
        time.sleep(1.0)
    if not frames:
        return {"new": 0, "last": str(last)}
    p = pd.DataFrame({"symbol": syms, "date": z["date"], "o": z["o"], "h": z["h"], "l": z["l"], "c": z["c"], "value": z["value"]})
    add = pd.concat(frames)
    add = pd.DataFrame({"symbol": add["symbol"], "date": add["date"], "o": add["o"], "h": add["h"], "l": add["l"], "c": add["c"],
                        "value": add["lacs"] * 1e5})
    p = pd.concat([p, add], ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    first_new = np.datetime64(wanted[0])
    sym = p["symbol"].to_numpy()
    dts = p["date"].to_numpy().astype("datetime64[D]")
    o, h, l, c = (p[k].to_numpy(float, copy=True) for k in "ohlc")
    starts = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1]])
    ends = np.r_[starts[1:], len(sym)]
    events = 0
    for a, b in zip(starts, ends):
        for i in range(max(a + 1, int(np.searchsorted(dts[a:b], first_new)) + a), b):
            ratio = o[i] / c[i - 1]
            if ratio < 0.6 or ratio > 1.6:
                o[a:i] *= ratio
                h[a:i] *= ratio
                l[a:i] *= ratio
                c[a:i] *= ratio
                events += 1
    keep = dts >= (dts.max() - np.timedelta64(NSE_KEEP_DAYS, "D"))
    cat = pd.Categorical(sym[keep])
    tmp = NSE_FILE.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, code=cat.codes.astype(np.int32), names=np.array(cat.categories.tolist()), date=dts[keep],
                        o=o[keep], h=h[keep], l=l[keep], c=c[keep], value=p["value"].to_numpy(float)[keep])
    tmp.replace(NSE_FILE)
    return {"new": len(frames), "last": str(dts.max()), "adjustments": events}


def nse_daily_markets() -> list:
    """yt_markets.nse_daily on our panel (the same liquidity filter, the same layout)."""
    YM.HERE = NSE_ROOT
    markets = YM.nse_daily()
    with np.load(NSE_FILE, allow_pickle=False) as z:
        code, names, value = z["code"], z["names"], z["value"]
    starts = np.flatnonzero(np.r_[True, code[1:] != code[:-1]])
    ends = np.r_[starts[1:], len(code)]
    where = {str(names[code[a]]): (a, b) for a, b in zip(starts, ends)}
    for m in markets:
        a, b = where[m.name]
        cs = np.cumsum(np.r_[0.0, value[a:b]])
        lo = np.maximum(np.arange(b - a) - 20, 0)
        m.turnover20 = (cs[np.arange(b - a)] - cs[lo]) / np.maximum(np.arange(b - a) - lo, 1)    # the 20 sessions before each row
    return markets


# ── NSE stocks: the 5-minute panel ───────────────────────────────────────────────────

NOT_STOCKS = {"FINNIFTY", "INDIAVIX"}
PANEL_FILE = DATA / "stocks" / "panel.npz"
BARS_A_DAY = 75
OPEN_S = 9 * 3600 + 15 * 60


def _ibar(path: Path):
    raw = zlib.decompress(path.read_bytes())
    if not raw.startswith(b"IBAR1\n"):
        raise ValueError(f"{path}: not a bar file")
    end = raw.index(b"\n", 6)
    n = int(json.loads(raw[6:end])["n"])
    pos = end + 1
    out = []
    for dtype in ("q", "d", "d", "d", "d", "q"):
        arr = np.frombuffer(raw, dtype=f"<{dtype}", count=n, offset=pos)
        pos += n * 8
        out.append(arr)
    return out


def stock_names() -> list[str]:
    return sorted(p.stem for p in (INTRADAY / "5m").glob("*.ibar") if p.stem not in NOT_STOCKS and not p.stem.startswith("NIFTY"))


def build_panel(now: datetime, sessions: int = 56) -> dict:
    """The last `sessions` sessions per stock as (stocks, sessions, 75) arrays, and each session's liquidity rank
    computed as lib_data.Market does (median traded value of the 60 sessions before it, listed 120+ sessions, previous
    close at least Rs 50). Today is left out until its bars are final, so a mid-session flush cannot sneak in half a day."""
    cut = now.date() if now.strftime("%H:%M") >= NSE_FINAL_HHMM else now.date() - timedelta(days=1)
    cut_key = (cut - date(1970, 1, 1)).days
    names, per = [], []
    counts: dict[int, int] = {}
    for sym in stock_names():
        t, o, h, l, c, v = _ibar(INTRADAY / "5m" / f"{sym}.ibar")
        loc = t + 19800
        mins = (loc % 86400) // 60
        day = loc // 86400
        keep = (mins >= 9 * 60 + 15) & (mins < 15 * 60 + 30) & (h >= l) & (c > 0) & (day <= cut_key)
        if keep.sum() < 400:
            continue
        t, o, h, l, c, v, day = (a[keep] for a in (t, o, h, l, c, v, day))
        starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
        days = day[starts]
        bars_per = np.diff(np.r_[starts, len(day)])
        for x, b in zip(days, bars_per):
            if b >= 60:
                counts[int(x)] = counts.get(int(x), 0) + 1
        names.append(sym)
        recent = t >= t[-1] - 110 * 86400
        per.append({"days": days, "value": np.add.reduceat(c * v, starts), "close": c[np.r_[starts[1:], len(c)] - 1],
                    "t": t[recent].copy(), "o": o[recent].copy(), "h": h[recent].copy(), "l": l[recent].copy(),
                    "c": c[recent].copy(), "v": v[recent].astype(float)})
    need = 0.5 * len(names)
    all_days = np.array(sorted(x for x, n in counts.items() if n >= need), dtype=np.int64)     # normal sessions only
    S, T = len(names), len(all_days)
    val, cls = np.full((T, S), np.nan), np.full((T, S), np.nan)
    for i, q in enumerate(per):
        idx = np.searchsorted(all_days, q["days"])
        ok = (idx < T) & (all_days[np.minimum(idx, T - 1)] == q["days"])
        val[idx[ok], i] = q["value"][ok]
        cls[idx[ok], i] = q["close"][ok]
    V = pd.DataFrame(val)
    med = V.rolling(60, min_periods=40).median()
    listed = V.notna().cumsum()
    elig = (listed >= 120) & (pd.DataFrame(cls).ffill() >= 50) & med.notna()
    rank_after = med.where(elig).rank(axis=1, ascending=False, method="first").to_numpy()     # known after each session
    D = min(sessions, T)
    panel_days = all_days[-D:]
    arrs = {k: np.full((S, D, BARS_A_DAY), np.nan) for k in "ohlcv"}
    for i, q in enumerate(per):
        loc = q["t"] + 19800
        di = np.searchsorted(panel_days, loc // 86400)
        bi = ((loc % 86400) - OPEN_S) // 300
        ok = (di < D) & (bi >= 0) & (bi < BARS_A_DAY)
        ok &= panel_days[np.minimum(di, D - 1)] == loc // 86400
        for k in "ohlcv":
            arrs[k][i, di[ok], bi[ok]] = q[k][ok]
    # rank[j] is the rank to use ON panel day j; rank[D] is for the next session.
    rank = np.vstack([rank_after[T - D - 1:T]]) if T > D else np.vstack([np.full((1, S), np.nan), rank_after[-D:]])
    PANEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PANEL_FILE.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, names=np.array(names), days=panel_days, rank=rank, **arrs)
    tmp.replace(PANEL_FILE)
    return {"stocks": S, "sessions": D, "last": str(np.datetime64(int(panel_days[-1]), "D"))}


class Panel:
    def __init__(self, live: dict | None, now: datetime):
        with np.load(PANEL_FILE, allow_pickle=False) as z:
            self.names = [str(x) for x in z["names"]]
            self.day_keys = z["days"].astype(np.int64)
            self.rank = z["rank"]
            self.a = {k: z[k] for k in "ohlcv"}
        self.live = live or {}
        self.live_day = None
        last = max((int(r[0]) for rows in self.live.values() for r in rows or []), default=None)
        if last:
            LIVE_LAST["NSE"] = last
        self.today_key = (now.date() - date(1970, 1, 1)).days
        if self.live and self.day_keys[-1] < self.today_key:
            self.live_day = now.date().isoformat()
            self.day_keys = np.r_[self.day_keys, self.today_key]
        self.days = [str(np.datetime64(int(x), "D")) for x in self.day_keys]

    @property
    def disk_last(self) -> str:
        return self.days[-2] if self.live_day else self.days[-1]

    def rank_on(self, j: int, i: int):
        """Liquidity rank of stock i on session j (the last row is the next session's)."""
        r = self.rank[min(j, len(self.rank) - 1), i]
        return float(r) if r == r else None

    def matrix(self, i: int) -> dict:
        """(sessions, 75) arrays of one stock, today's closed bars included."""
        out = {k: self.a[k][i] for k in "ohlcv"}
        if not self.live_day:
            return out
        row = {k: np.full((1, BARS_A_DAY), np.nan) for k in "ohlcv"}
        base = self.today_key * 86400 - 19800 + OPEN_S
        for r in self.live.get(self.names[i]) or []:
            b = (int(r[0]) - base) // 300
            if 0 <= b < BARS_A_DAY and r[2] >= r[3] and r[4] > 0:
                for k, x in zip("ohlcv", r[1:6]):
                    row[k][0, b] = x
        return {k: np.vstack([out[k], row[k]]) for k in "ohlcv"}

    def market(self, i: int, mat: dict | None = None):
        """One stock as yt_markets.nse_intraday builds it (5-minute rows, IST-date trading days)."""
        mat = mat or self.matrix(i)
        base = self.day_keys[:, None] * 86400 - 19800 + OPEN_S + 300 * np.arange(BARS_A_DAY)[None, :]
        c = mat["c"]
        ok = np.isfinite(c) & np.isfinite(mat["o"]) & np.isfinite(mat["h"]) & np.isfinite(mat["l"])
        if ok.sum() < 400:
            return None
        key = np.repeat(self.day_keys, BARS_A_DAY).reshape(c.shape)[ok]
        return YM._finish_stock(self.names[i], base[ok].astype(np.int64), mat["o"][ok], mat["h"][ok], mat["l"][ok], c[ok],
                                np.nan_to_num(mat["v"][ok]), key)


# ── Crypto-playlist markets: silver, Fear & Greed (bitcoin from Delta Exchange is below) ─────

BM.COSTS.setdefault("XAGUSD", BM.CostModel(0.01, 0.01, 0.0))
YM.COSTS.setdefault("XAGUSD", YM.Cost(0.01, 0.01, 0.0))


def _read_cols(name: str, first_ym: str, cols: tuple) -> tuple:
    parts = []
    folder = DATA / "min1" / name
    for f in sorted(folder.glob("*.npz")) if folder.exists() else []:
        if f.stem >= first_ym:
            with np.load(f) as z:
                parts.append(tuple(z[k] for k in cols))
    if not parts:
        return tuple(np.empty(0) for _ in cols)
    return tuple(np.concatenate([p[i] for p in parts]) for i in range(len(cols)))


def btc_final_day(now: datetime | None = None) -> str:
    """A UTC day is final half an hour after it ends."""
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    done = n.hour * 60 + n.minute >= 30
    return ((n.date() - timedelta(days=1)) if done else (n.date() - timedelta(days=2))).isoformat()


FNG_FILE = DATA / "daily" / "fear_greed.json"


def fear_greed() -> dict:
    """{UTC date: index value} of the Crypto Fear & Greed Index (alternative.me), kept on disk; stored days never change."""
    have = {}
    if FNG_FILE.exists():
        have = json.loads(FNG_FILE.read_text())
    try:
        with urllib.request.urlopen(urllib.request.Request("https://api.alternative.me/fng/?limit=60&format=json",
                                                           headers={"User-Agent": UA}), timeout=30) as r:
            data = json.load(r).get("data") or []
        for x in data:
            d = datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).date().isoformat()
            have.setdefault(d, int(x["value"]))
        FNG_FILE.parent.mkdir(parents=True, exist_ok=True)
        FNG_FILE.write_text(json.dumps(dict(sorted(have.items()))))
    except Exception as exc:  # noqa: BLE001
        log.warning("fear & greed: %s", exc)
    return have


# ── bitcoin from Delta Exchange (BTCUSD perpetual): 1-minute candles, plus the recorded order flow ─────

DELTA_API = "https://api.india.delta.exchange"
DELTA_STORES = {"BTCUSD": "DELTA_BTCUSD", "XAUTUSD": "DELTA_XAUTUSD", "ETHUSD": "DELTA_ETHUSD"}   # ETHUSD: NJ-33's second coin
DELTA_STORE = DELTA_STORES["BTCUSD"]
# Delta India BTCUSD: 0.001 BTC a contract, tick $0.5, taker fee 0.05% + 18% GST = 0.059% a side; 2 bp of slippage
DELTA_COST = YM.Cost(0.0, 0.0, 0.0, False, 1, pct_slip=0.0002, pct_comm=0.00059)
DELTA_HALF = 0.5                                   # half a $1 spread


def update_delta_candles(now_ts: int | None = None, symbol: str = "BTCUSD") -> dict:
    """Append finished 1-minute candles of a Delta India perpetual (BTCUSD, XAUTUSD); the forming minute is never stored."""
    store = DELTA_STORES[symbol]
    now_ts = now_ts or int(time.time())
    have = _read_cols(store, _ym(now_ts - 60 * 86400), ("t",))[0]
    last = int(have[-1]) if len(have) else now_ts - 46 * 86400
    rows, start = [], last + 60
    while start < now_ts - 120:
        end = min(start + 2000 * 60, now_ts - 120)
        url = f"{DELTA_API}/v2/history/candles?" + urllib.parse.urlencode({"resolution": "1m", "symbol": symbol, "start": start, "end": end})
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            rows += json.load(r).get("result") or []
        start = end
        time.sleep(0.3)
    if not rows:
        return {"new": 0, "last": last}
    a = np.array([[float(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x.get("volume") or 0)]
                  for x in rows])
    t = a[:, 0].astype(np.int64)
    keep = (t > last) & (t <= now_ts - 120) & (t % 60 == 0)
    a, t = a[keep], t[keep]
    if not len(t):
        return {"new": 0, "last": last}
    t, idx = np.unique(t, return_index=True)
    a = a[idx]
    months = np.array([_ym(int(x)) for x in t])
    for ym in np.unique(months):
        m = months == ym
        path = _month_file(store, str(ym))
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = dict(t=t[m], o=a[m, 1], h=a[m, 2], l=a[m, 3], c=a[m, 4], v=a[m, 5])
        if path.exists():
            with np.load(path) as z:
                cols = {k: np.concatenate([z[k], cols[k]]) for k in cols}
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **cols)
        tmp.replace(path)
    return {"new": int(len(t)), "last": int(t[-1])}


def btc_market(since: date):
    """Delta BTCUSD minutes from `since` (UTC days), with each minute's taker buy and total taker volume where the
    order-flow recorder saw the whole minute; NaN elsewhere, so a candle's delta is only known when it was recorded."""
    import delta_flow
    t0 = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
    t, o, h, l, c, v = _read_cols(DELTA_STORE, _ym(t0), ("t", "o", "h", "l", "c", "v"))
    keep = t >= t0
    if not keep.any():
        return None
    t, o, h, l, c, v = (x[keep] for x in (t, o, h, l, c, v))
    m = CPM.btc_market(t.astype(np.int64), o, h, l, c, v, np.zeros(len(t)))
    flow = delta_flow.read(t0)
    buy = np.array([flow[int(x)][0] if int(x) in flow else np.nan for x in m.t])
    sell = np.array([flow[int(x)][1] if int(x) in flow else np.nan for x in m.t])
    m.bv, m.vol_all = buy, buy + sell
    m.half = np.full(len(m.t), DELTA_HALF)
    m.cost = DELTA_COST
    return m


BM.COSTS.setdefault("ETHUSD", BM.CostModel(0.0, 0.0, 0.0))


def eth_market(since: date):
    """Delta ETHUSD minutes from `since` (UTC days): only read, never traded (NJ-33 compares its swings with bitcoin's)."""
    t0 = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
    t, o, h, l, c, v = _read_cols(DELTA_STORES["ETHUSD"], _ym(t0), ("t", "o", "h", "l", "c", "v"))
    keep = t >= t0
    if not keep.any():
        return None
    t, o, h, l, c, v = (x[keep] for x in (t, o, h, l, c, v))
    return CPM.btc_market(t.astype(np.int64), o, h, l, c, v, np.zeros(len(t)), name="ETHUSD")


def backfill_delta_candles(symbol: str, days: int, now_ts: int | None = None) -> dict:
    """Fetch older finished 1-minute candles once, so the store reaches `days` back (the 11-channel bitcoin books read
    4-hour EMA 200s). A marker file records the attempt, so a history the exchange does not serve is not asked again."""
    store = DELTA_STORES[symbol]
    folder = DATA / "min1" / store
    now_ts = now_ts or int(time.time())
    want = (now_ts - days * 86400) // 60 * 60
    files = sorted(folder.glob("*.npz")) if folder.exists() else []
    marker = folder / "backfill.json"
    if not files:
        return {"new": 0, "why": "empty store"}
    done = json.loads(marker.read_text()) if marker.exists() else {}
    if int(done.get("want") or 1e18) <= want:
        return {"new": 0, "why": "already tried"}
    with np.load(files[0]) as z:
        first = int(z["t"][0])
    rows, start = [], want
    while start < first - 60:
        end = min(start + 2000 * 60, first - 60)
        url = f"{DELTA_API}/v2/history/candles?" + urllib.parse.urlencode({"resolution": "1m", "symbol": symbol, "start": start, "end": end})
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            rows += json.load(r).get("result") or []
        start = end
        time.sleep(0.3)
    marker.write_text(json.dumps({"want": want, "at": now_ts, "rows": len(rows)}))
    if not rows:
        return {"new": 0, "first": first}
    a = np.array([[float(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x.get("volume") or 0)]
                  for x in rows])
    t = a[:, 0].astype(np.int64)
    keep = (t < first) & (t >= want) & (t % 60 == 0)
    a, t = a[keep], t[keep]
    if not len(t):
        return {"new": 0, "first": first}
    t, idx = np.unique(t, return_index=True)
    a = a[idx]
    months = np.array([_ym(int(x)) for x in t])
    for ym in np.unique(months):
        mm = months == ym
        path = _month_file(store, str(ym))
        cols = dict(t=t[mm], o=a[mm, 1], h=a[mm, 2], l=a[mm, 3], c=a[mm, 4], v=a[mm, 5])
        if path.exists():
            with np.load(path) as z:
                cols = {k: np.concatenate([cols[k], z[k]]) for k in cols}
            tt, ix = np.unique(cols["t"], return_index=True)
            cols = {k: (tt if k == "t" else cols[k][ix]) for k in cols}
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **cols)
        tmp.replace(path)
    return {"new": int(len(t)), "from": int(t[0]), "first_before": first}


# ── gold from Delta Exchange: the XAUTUSD perpetual (Tether Gold, one token = one troy ounce) ─────
# Delta India: contracts of 0.001 XAUT, tick $0.01, taker fee 0.01% + 18% GST a side. The book is tight (about $0.02 half
# spread); $0.10 of slippage a fill is kept from the gold study. XAUTUSD trades every day, but the gold strategies follow
# the gold market's week (Sunday 17:00 to Friday 17:00 New York), so weekend minutes are left out of their data.
GOLD_DELTA_HALF = 0.02
GOLD_DELTA_SLIP = 0.10
GOLD_DELTA_FEE = 0.000118


def gold_market(since: date):
    t0 = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp()) - 86400
    t, o, h, l, c, v = _read_cols(DELTA_STORES["XAUTUSD"], _ym(t0), ("t", "o", "h", "l", "c", "v"))
    keep = t >= t0
    if not keep.any():
        return None
    t, o, h, l, c, v = (x[keep] for x in (t, o, h, l, c, v))
    t = t.astype(np.int64)
    ny = pd.to_datetime(t, unit="s", utc=True).tz_convert("America/New_York")
    wd, hm = ny.weekday.to_numpy(), (ny.hour * 60 + ny.minute).to_numpy()
    weekend = (wd == 5) | ((wd == 4) & (hm >= 17 * 60)) | ((wd == 6) & (hm < 17 * 60))
    t, o, h, l, c, v = (x[~weekend] for x in (t, o, h, l, c, v))
    mid = (o + c) / 2
    sane = np.maximum(h / mid - 1, 1 - l / mid) <= MAX_DEV["XAUUSD"]      # a bad print would be a fake stop or target
    t, o, h, l, c, v = (x[sane] for x in (t, o, h, l, c, v))
    if not len(t):
        return None
    vol = np.where(v > 0, v, 1.0).astype(np.float32)
    m = BM._finish("XAUUSD", t, o, h, l, c, np.full(len(t), GOLD_DELTA_HALF), vol, BM._ny_roll_key(t), False)
    m.cost = BM.CostModel(None, GOLD_DELTA_SLIP, GOLD_DELTA_FEE * float(np.median(c[-1440:])))
    return m


def yt_cost(name: str):
    """The YouTube engine's cost model for a market: gold on Delta's fee schedule, the others as the study set them."""
    if name == "XAUUSD":
        return YM.Cost(None, GOLD_DELTA_SLIP, 0.0, False, 1, pct_slip=0.0, pct_comm=GOLD_DELTA_FEE)
    return YM.COSTS[name]
