"""Our implementations of the QuantConnect candidates (STEP 5), version v1 = the source's logic as published.

QuantConnect algorithms run on LEAN, which is not available here, so each is re-implemented from its code (line
references in the cards) and writes signals in the same format as ws_ft_signals.py; ws_engine.py fills them on
one-minute bars with our costs. Where the source behaves oddly, v1 keeps that behaviour and the card says so (QC-11340
returns before its exit check while the EMAs are bearish; QC-13690 only goes long first from flat; QC-20960 uses
LEAN's default New York clock although its post says UTC, and blocks a day-of-month rather than a date; QC-5079 seeds
TA-Lib's EMA on each 250-close window). Labelled approximations (A in the cards):
  - fills: LEAN fills a market order at the bar's close; here at the next minute's open after the bar closes;
  - LEAN's EMA starts from the first value, as pandas ewm(adjust=False); LEAN's Wilder RSI starts from an SMA (here
    from the first value: it converges within the warm-up);
  - QC-18379's 10% trailing stop follows minute HIGHS here (the engine's trailing stop), minute closes in the source;
  - crypto candles are Binance spot (the sources used Bitfinex, Coinbase, Binance or Bybit); gold candles are
    Dukascopy-based XAUUSD mid (the sources used OANDA XAUUSD CFD or the GLD ETF).

    python -I ws_strategies.py [SID,SID,...]        writes D:/Strategy-Web-Sources/signals_qc/<SID>__<market>.npz
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ws_engine as E  # noqa: E402

OUT = Path(r"D:\Strategy-Web-Sources\signals_qc")
NY = "America/New_York"


# ── bars and indicators ──────────────────────────────────────────────────────────────────────────────────────
def bars(m: E.Minutes, rule: str, tz: str = "UTC") -> pd.DataFrame:
    """OHLC bars from minutes, labelled by their OPEN time in `tz`; columns t0 / t1 = open / close in unix seconds."""
    idx = pd.to_datetime(m.t, unit="s", utc=True).tz_convert(tz)
    df = pd.DataFrame({"o": m.o, "h": m.h, "l": m.l, "c": m.c}, index=idx)
    b = df.resample(rule, label="left", closed="left").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    b["t0"] = (b.index.tz_convert("UTC") - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    step = int(pd.Timedelta(rule).total_seconds())
    b["t1"] = b["t0"] + step
    return b


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def rsi_wilder(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def rsi_simple(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = d.clip(lower=0).rolling(n).mean(), (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr_simple(b: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = b["c"].shift(1)
    tr = np.maximum(b["h"] - b["l"], np.maximum((b["h"] - pc).abs(), (b["l"] - pc).abs()))
    return tr.rolling(n).mean()


def save(sid: str, market: str, known: np.ndarray, el, xl, es=None, xs=None, settings: dict | None = None) -> None:
    """Signals keyed by the time they become KNOWN (a bar's close): stored as t = known - 60 with tf = 1 minute."""
    OUT.mkdir(parents=True, exist_ok=True)
    n = len(known)
    z = lambda a: np.zeros(n, np.int8) if a is None else np.asarray(a, dtype=np.int8)  # noqa: E731
    np.savez_compressed(OUT / f"{sid}__{market}.npz", t=np.asarray(known, np.int64) - 60, tf=np.int64(1),
                        enter_long=z(el), exit_long=z(xl), enter_short=z(es), exit_short=z(xs), filled=np.zeros(n, np.int8))
    s = {"minimal_roi": {}, "stoploss": -1.0, "trailing_stop": False, "use_exit_signal": True, "can_short": es is not None,
         "mode": "QuantConnect re-implementation v1"}
    s.update(settings or {})
    (OUT / f"{sid}.settings.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    print(f"{sid:10} {market:9} rows={n:>8} enterL={int(z(el).sum()):>6} exitL={int(z(xl).sum()):>6} "
          f"enterS={int(z(es).sum()):>6} exitS={int(z(xs).sum()):>6}")


# ── QC-11340  BTC 3-EMAs (daily, long only, 5% trailing on closes) ─────────────────────────────────────────────
def qc_11340(m: E.Minutes, market: str) -> None:
    b = bars(m, "1D")
    c = b["c"]
    e20, e50, e100 = ema(c, 20), ema(c, 50), ema(c, 100)
    n = len(b)
    el, xl = np.zeros(n, np.int8), np.zeros(n, np.int8)
    inv, hi = False, 0.0
    for i in range(100, n):                                  # SetWarmUp(100 days)
        p, a, f_, h_ = c.iloc[i], e20.iloc[i], e50.iloc[i], e100.iloc[i]
        if a < f_ < h_:                                      # L45-46: return BEFORE the entry and exit checks
            continue
        if not inv and a > p > f_ > h_:                      # L49: entry
            el[i], inv, hi = 1, True, p
        if p > hi:                                           # L56-57
            hi = p
        if (inv and p <= f_) or (p < hi * 0.95):             # L60 (Python precedence: the trailing part stands alone)
            if inv:
                xl[i] = 1
            inv, hi = False, 0.0
    save("QC-11340", market, b["t1"].to_numpy(), el, xl)


# ── QC-13690  EMA 13/48 long/short reversal (daily) ───────────────────────────────────────────────────────────
def qc_13690(m: E.Minutes, market: str) -> None:
    b = bars(m, "1D")
    fast, slow = ema(b["c"], 13), ema(b["c"], 48)
    n = len(b)
    el, xl, es, xs = (np.zeros(n, np.int8) for _ in range(4))
    pos = 0
    for i in range(5 * 48, n):                               # SetWarmUp(5 * EMA_S days)
        f_, s_ = fast.iloc[i], slow.iloc[i]
        if pos <= 0:                                         # not IsLong
            if f_ >= s_:
                if pos < 0:
                    xs[i] = 1
                el[i], pos = 1, 1
        elif pos > 0:                                        # elif not IsShort
            if f_ < s_:
                xl[i], es[i], pos = 1, 1, -1
    save("QC-13690", market, b["t1"].to_numpy(), el, xl, es, xs)


# ── QC-15987  ETH momentum RSI (hourly RSI, daily SMA25 filter, 10% stop) ─────────────────────────────────────
def qc_15987(m: E.Minutes, market: str) -> None:
    h = bars(m, "1h")
    d = bars(m, "1D")
    sma = d["c"].rolling(25).mean()
    # the daily SMA known at each hourly close: the last DAILY bar that closed at or before it
    sma_known = pd.Series(sma.to_numpy(), index=d["t1"].to_numpy())
    pos = np.searchsorted(sma_known.index.to_numpy(), h["t1"].to_numpy(), side="right") - 1
    trend = np.where(pos >= 0, sma_known.to_numpy()[np.maximum(pos, 0)], np.nan)
    r = rsi_wilder(h["c"], 14).to_numpy()
    above = h["c"].to_numpy() > trend                        # L19-20: below the trend nothing is checked
    el = (above & (r > 15) & (r < 20)).astype(np.int8)       # L26
    xl = (above & (r > 95)).astype(np.int8)                  # L32
    save("QC-15987", market, h["t1"].to_numpy(), el, xl, settings={"stoploss": -0.10})   # L28 stop at price * 0.9


# ── QC-18379  EMA 10/20/50 + RSI on hourly values, checked every minute, long/short, 10% trailing ───────────────
def qc_18379(m: E.Minutes, market: str) -> None:
    h = bars(m, "1h")
    c = h["c"]
    r, e10, e20, e50 = rsi_wilder(c, 14), ema(c, 10), ema(c, 20), ema(c, 50)
    lc = ((r > 40) & (e10 > e20) & (e20 > e50)).to_numpy()
    sc = (~lc & (r < 70) & (e10 < e20) & (e20 < e50)).to_numpy()
    ok = np.arange(len(h)) >= 110                            # warm-up: 100 + 10 hourly bars
    lc, sc = lc & ok, sc & ok
    # every minute uses the values of the last hourly bar that has closed; a signal row per minute
    k = np.searchsorted(h["t1"].to_numpy(), m.t, side="right") - 1
    valid = k >= 0
    L = np.where(valid, lc[np.maximum(k, 0)], False)
    S = np.where(valid, sc[np.maximum(k, 0)], False)
    known = m.t + 60                                         # a minute's close
    save("QC-18379", market, known, L, S, S, L, settings={"stoploss": -0.10, "trailing_stop": True})


# ── QC-20960  GoldDeepSweepV5 (XAUUSD, hourly bars, New York clock) ───────────────────────────────────────────
def qc_20960(g: E.GoldMinutes) -> None:
    b = bars(g, "1h", tz=NY)
    b["end_hour"] = ((b.index + pd.Timedelta(hours=1)).hour)   # LEAN's self.time for an hourly bar = its END
    b["end_day"] = ((b.index + pd.Timedelta(hours=1)).day)
    atr, rsi = atr_simple(b, 14), rsi_wilder(b["c"], 14)
    n = len(b)
    el, xl, es, xs = (np.zeros(n, np.int8) for _ in range(4))
    ah = al = 0.0
    hp, lp = [], []
    dh = dl = False
    qty, sl, tp, last_day = 0, 0.0, 0.0, -1
    H, L, C = b["h"].to_numpy(), b["l"].to_numpy(), b["c"].to_numpy()
    hrs, days = b["end_hour"].to_numpy(), b["end_day"].to_numpy()
    A, R = atr.to_numpy(), rsi.to_numpy()
    for i in range(48, n):                                   # set_warm_up(48 hours)
        hr = hrs[i]
        if hr == 17:                                         # L35
            continue
        if not (A[i] == A[i]) or not (R[i] == R[i]):         # L38 indicators ready
            continue
        cp, hpx, lpx = C[i], H[i], L[i]
        if hr == 22:                                         # L46-51 the Asia pool
            hp, lp = [hpx], [lpx]
        elif hr == 23 or 0 <= hr <= 5:
            hp.append(hpx)
            lp.append(lpx)
        if hr == 6 and hp and lp:                            # L53-58
            ah, al, dh, dl = max(hp), min(lp), False, False
        if qty != 0:                                         # L61-70 exits on the bar CLOSE
            if (qty > 0 and (cp <= sl or cp >= tp)):
                xl[i], qty = 1, 0
            elif (qty < 0 and (cp >= sl or cp <= tp)):
                xs[i], qty = 1, 0
            continue
        if not (7 <= hr <= 16) or days[i] == last_day or ah == 0 or al == 0:   # L73-75
            continue
        a = A[i]
        if a <= 0:
            continue
        if hpx >= ah + a * 0.7:                              # L81-83
            dh, dl = True, False
        if dh and cp < ah and R[i] >= 65:                    # L86-94 short
            sl, tp = cp + a * 2.5, (ah + al) / 2.0
            es[i], qty, dh, last_day = 1, -1, False, days[i]
            continue
        if lpx <= al - a * 0.7:                              # L97-99
            dl, dh = True, False
        if dl and cp > al and R[i] <= 35:                    # L102-109 long
            sl, tp = cp - a * 2.5, (ah + al) / 2.0
            el[i], qty, dl, last_day = 1, 1, False, days[i]
    save("QC-20960", "XAUUSD", b["t1"].to_numpy(), el, xl, es, xs)


# ── QC-5079  GLD 200-EMA timing (decision 2 minutes before the NYSE close) -> XAUUSD spot (ADAPTATION) ──────────
def talib_ema_last(x: np.ndarray, n: int) -> float:
    """TA-Lib's EMA of a window: seeded with the mean of the first n values, then smoothed to the window's end."""
    k = 2.0 / (n + 1)
    v = float(np.mean(x[:n]))
    for p in x[n:]:
        v = p * k + v * (1 - k)
    return v


def qc_5079(g: E.GoldMinutes) -> None:
    ny = pd.to_datetime(g.t, unit="s", utc=True).tz_convert(NY)
    df = pd.DataFrame({"c": g.c, "t": g.t}, index=ny)
    wk = df[df.index.dayofweek < 5]
    # the GLD daily close stands in as XAUUSD at 16:00 New York (the close of the 15:59 minute)
    close16 = wk[(wk.index.hour == 15) & (wk.index.minute == 59)]["c"]
    close16.index = close16.index.normalize()
    close16 = close16[~close16.index.duplicated(keep="last")]
    dec = wk[(wk.index.hour == 15) & (wk.index.minute == 58)]   # the scheduled decision minute (BeforeMarketClose 2)
    days = dec.index.normalize()
    el, xl, known = [], [], []
    pos = False
    cl = close16.to_numpy()
    cd = close16.index
    for when, day in zip(dec.index, days):
        j = int(np.searchsorted(cd, day, side="left"))       # closes strictly BEFORE today (today's bar is incomplete)
        if j < 250:
            continue
        h = cl[j - 250:j]                                    # History(['GLD'], 250, Resolution.Daily)
        avg = talib_ema_last(h, 200)
        close = h[-1]
        e = x = 0
        if close > avg * 1.001 and not pos:
            e, pos = 1, True
        elif close < avg * 0.999 and pos:
            x, pos = 1, False
        el.append(e)
        xl.append(x)
        known.append(int((when.tz_convert("UTC") - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)))
    save("QC-5079", "XAUUSD", np.array(known), np.array(el), np.array(xl))


def main(argv: list[str]) -> None:
    want = set(argv[0].split(",")) if argv else {"QC-11340", "QC-13690", "QC-15987", "QC-18379", "QC-20960", "QC-5079"}
    crypto = {"BTC/USDT": None, "ETH/USDT": None}
    for p in crypto:
        if want & {"QC-11340", "QC-13690", "QC-15987", "QC-18379"}:
            crypto[p] = E.Minutes(p)
    for p, mm in crypto.items():
        if mm is None:
            continue
        mk = p.replace("/", "_")
        if "QC-11340" in want:
            qc_11340(mm, mk)
        if "QC-13690" in want:
            qc_13690(mm, mk)
        if "QC-15987" in want:
            qc_15987(mm, mk)
        if "QC-18379" in want:
            qc_18379(mm, mk)
    if want & {"QC-20960", "QC-5079"}:
        g = E.GoldMinutes()
        if "QC-20960" in want:
            qc_20960(g)
        if "QC-5079" in want:
            qc_5079(g)


if __name__ == "__main__":
    main(sys.argv[1:])
