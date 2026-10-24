"""XAUUSD bars for the study, built from the raw downloads (xa_fetch.py), with data checks.

Bars
  hourly   Dukascopy BID and ASK candles merged per UTC hour; MID = (bid + ask) / 2 for each of
           open / high / low / close (a close approximation of the true mid's high and low);
           SPREAD = ask close - bid close. Hours with no ticks on either side (Dukascopy pads
           closed hours with flat zero-volume candles) are dropped.
  daily    one bar per New York trading session, rolling at 17:00 New York (the FX / metals
           convention: Sunday-evening hours belong to Monday), built from the hourly MID bars.
           A session's close is the close of its last hour, i.e. ~17:00 New York.
  rates    13-week US T-bill yield (Yahoo ^IRX, % a year), the financing rate, carried forward
           over days without a print.

Checks (python xa_data.py)  ->  results/data_quality.json
  coverage per year, sessions and hours; weekday sessions with no data; gaps inside a session;
  spread distribution per year; ask < bid; the largest hourly moves; agreement with Dukascopy's
  own daily candles (UTC days) and with COMEX GC=F (Yahoo) daily and hourly returns.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path

import json
import lzma
import os
import pickle
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
# XA_BID_ONLY=1: pipeline development before the ASK download finishes - bid + a 0.35 placeholder
# spread, cached separately; never used for a reported result
BID_ONLY = os.environ.get("XA_BID_ONLY") == "1"
CACHE = ROOT / "data" / ("bars_bidonly.pkl" if BID_ONLY else "bars.pkl")
RESULTS = ROOT / "results"
NY = "America/New_York"
POINT = 1000.0                      # Dukascopy XAUUSD prices are integers of 0.001 USD
REC = np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"), ("l", ">i4"), ("h", ">i4"), ("v", ">f4")])


# ── decoding ────────────────────────────────────────────────────────────────────


def _decode(path: Path, base: datetime, step_s: int) -> pd.DataFrame:
    raw = lzma.decompress(path.read_bytes())
    a = np.frombuffer(raw, dtype=REC)
    ts = pd.to_datetime(np.int64(base.timestamp()) + a["t"].astype(np.int64), unit="s", utc=True)
    return pd.DataFrame({"o": a["o"] / POINT, "h": a["h"] / POINT, "l": a["l"] / POINT, "c": a["c"] / POINT,
                         "v": a["v"].astype(float)}, index=ts)


def _side_hours(side: str) -> pd.DataFrame:
    frames = []
    for p in sorted((RAW / "dukascopy" / "hour" / side).glob("*.bi5")):
        y, m = map(int, p.stem.split("-"))
        frames.append(_decode(p, datetime(y, m, 1, tzinfo=timezone.utc), 3600))
    # the current month: minute candles -> hours
    mins = []
    for p in sorted((RAW / "dukascopy" / "minute" / side).glob("*.bi5")):
        d = date.fromisoformat(p.stem)
        mins.append(_decode(p, datetime(d.year, d.month, d.day, tzinfo=timezone.utc), 60))
    if mins:
        m1 = pd.concat(mins)
        m1 = m1[m1["v"] > 0]
        g = m1.groupby(m1.index.floor("h"))
        frames.append(pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(),
                                    "v": g["v"].sum()}))
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="last")]


def _yahoo(name: str) -> pd.DataFrame:
    j = json.loads((RAW / "yahoo" / name).read_text())["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")},
                      index=pd.to_datetime(np.array(j["timestamp"], dtype=np.int64), unit="s", utc=True))
    return df.dropna(subset=["close"])


# ── bars ────────────────────────────────────────────────────────────────────────


def session_dates(utc_index: pd.DatetimeIndex) -> np.ndarray:
    """New York session each UTC hour belongs to: the session ends at 17:00 New York."""
    ny = utc_index.tz_convert(NY)
    return np.array((ny + pd.Timedelta(hours=7)).date, dtype="datetime64[D]")


def build() -> dict:
    bid = _side_hours("BID")
    if BID_ONLY:
        ask = bid.copy()
        for k in ("o", "h", "l", "c"):
            ask[k] = bid[k] + 0.35
    else:
        ask = _side_hours("ASK")
    # Warm-up years (before 2008) were fetched on the bid side only: their ask is the bid plus the
    # median spread measured over 2008. Allowed only before 2010, where no trade is ever taken.
    synth = bid.index.difference(ask.index)
    synth = synth[bid.loc[synth, "v"].values > 0] if len(synth) else synth
    if len(synth):
        if synth.max() >= pd.Timestamp("2010-01-01", tz="UTC"):
            raise ValueError(f"bid hours without an ask after 2009: {synth[synth >= pd.Timestamp('2010-01-01', tz='UTC')][:5]}")
        first_year = ask[(ask.index.year == ask.index.year.min())]
        ref = (first_year["c"] - bid["c"].reindex(first_year.index)).dropna()
        fill = float(ref[(ref > 0) & (ref < 5)].median())
        extra = bid.loc[synth].copy()
        for k in ("o", "h", "l", "c"):
            extra[k] = extra[k] + fill
        ask = pd.concat([ask, extra]).sort_index()
    both = bid.join(ask, how="inner", lsuffix="_b", rsuffix="_a")
    live = (both["v_b"] > 0) & (both["v_a"] > 0)
    one_sided = int(((both["v_b"] > 0) ^ (both["v_a"] > 0)).sum())
    both = both[live]
    H = pd.DataFrame({k: (both[f"{k}_b"] + both[f"{k}_a"]) / 2 for k in ("o", "h", "l", "c")}, index=both.index)
    H["spread"] = both["c_a"] - both["c_b"]
    H["spread_o"] = both["o_a"] - both["o_b"]
    H["v"] = both["v_b"]
    # an hour's high cannot be below its open/close after averaging; guard rounding
    H["h"] = H[["h", "o", "c"]].max(axis=1)
    H["l"] = H[["l", "o", "c"]].min(axis=1)
    H["session"] = session_dates(H.index)
    g = H.groupby("session", sort=True)
    D = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(),
                      "hours": g["c"].size(), "spread": g["spread"].median(),
                      "first_hour": g["c"].apply(lambda s: s.index[0]), "last_hour": g["c"].apply(lambda s: s.index[-1])})
    D.index = pd.to_datetime(D.index)
    # a "session" of a stray hour or two (e.g. ticks after Friday's close) is not a session
    stray = D[D["hours"] < 4]
    D = D[D["hours"] >= 4]
    H = H[H["session"].isin(np.array(D.index.values, dtype="datetime64[D]"))]
    irx = _yahoo("IRX_1d.json")["close"]
    irx.index = irx.index.tz_convert(NY).normalize().tz_localize(None)
    irx = irx[~irx.index.duplicated(keep="last")]
    days = pd.date_range(min(D.index[0], irx.index[0]), max(D.index[-1], irx.index[-1]) + pd.Timedelta(days=7), freq="D")
    rate = (irx.reindex(days).ffill().bfill() / 100.0).rename("rate")
    out = {"H": H, "D": D, "rate": rate, "meta": {"one_sided_hours": one_sided, "stray_sessions": [str(x.date()) for x in stray.index],
                                                     "warmup_hours_with_synthetic_ask": int(len(synth)),
                                                     "warmup_synthetic_ask_last": str(synth.max()) if len(synth) else None,
                                                     "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(out, f)
    return out


def load() -> dict:
    if CACHE.exists():
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    return build()


# ── checks ──────────────────────────────────────────────────────────────────────


def quality(bars: dict) -> dict:
    H, D = bars["H"], bars["D"]
    q: dict = {"source": "Dukascopy Bank SA public datafeed (datafeed.dukascopy.com), XAUUSD BID+ASK hourly candles; "
                         "current month from minute candles", "timezone": "UTC timestamps (hour start); sessions roll at 17:00 America/New_York",
               "first_hour": str(H.index[0]), "last_hour": str(H.index[-1]), "hours": int(len(H)), "sessions": int(len(D)),
               "one_sided_hours_dropped": bars["meta"]["one_sided_hours"], "stray_sessions_dropped": bars["meta"]["stray_sessions"]}
    yrs = {}
    for y, h in H.groupby(H.index.year):
        dy = D[D.index.year == y]
        sp = h["spread"]
        yrs[int(y)] = {"hours": int(len(h)), "sessions": int(len(dy)), "median_hours_per_session": float(dy["hours"].median()),
                       "spread_median": round(float(sp.median()), 3), "spread_p90": round(float(sp.quantile(0.9)), 3),
                       "spread_max": round(float(sp.max()), 3), "ask_below_bid_hours": int((sp < 0).sum()),
                       "price_first": round(float(h["c"].iloc[0]), 2), "price_last": round(float(h["c"].iloc[-1]), 2)}
    q["by_year"] = yrs
    # how far gold moves in a session: why rules that are flat within a session or two cannot average 2%
    dt = D[D.index >= pd.Timestamp("2010-01-01")]
    rng = (dt["h"] - dt["l"]) / dt["c"]
    oc = (dt["c"] - dt["o"]).abs() / dt["o"]
    q["session_moves_2010_on"] = {"sessions": int(len(dt)), "median_high_low_range_pct": round(float(rng.median()) * 100, 2),
                                  "share_range_2pct_or_more": round(float((rng >= 0.02).mean()), 4),
                                  "share_open_to_close_2pct_or_more": round(float((oc >= 0.02).mean()), 4)}
    # weekdays with no session at all
    allwd = pd.bdate_range(D.index[0], D.index[-1])
    missing = sorted(set(allwd.date) - set(D.index.date))
    q["weekdays_without_a_session"] = [str(d) for d in missing]
    # gaps inside sessions (hours missing between consecutive hours of one session, beyond the 1-hour daily break)
    gaps = []
    t = H.index.values.astype("datetime64[s]").astype(np.int64)
    s = H["session"].values
    for i in range(1, len(t)):
        if s[i] == s[i - 1] and t[i] - t[i - 1] > 3 * 3600:
            gaps.append({"from": str(H.index[i - 1]), "to": str(H.index[i]), "hours": int((t[i] - t[i - 1]) // 3600) - 1})
    q["intra_session_gaps_over_2h"] = gaps
    # largest hourly moves (plausibility: are these real market events?)
    r = np.log(H["c"]).diff()
    big = r.abs().sort_values(ascending=False).head(12)
    q["largest_hourly_moves"] = [{"hour": str(k), "log_return_pct": round(float(r[k]) * 100, 2), "close": round(float(H.loc[k, "c"]), 2)}
                                 for k in big.index]
    # Dukascopy's own daily candles (UTC days, BID) against UTC-day aggregation of the hourly BID-derived mid
    try:
        from xa_fetch import FIRST_YEAR
        dd = []
        for p in sorted((RAW / "dukascopy" / "day").glob("BID-*.bi5")):
            yr = int(p.stem.split("-")[1])
            dd.append(_decode(p, datetime(yr, 1, 1, tzinfo=timezone.utc), 86400))
        dday = pd.concat(dd)
        dday = dday[dday["v"] > 0]
        bidh = _side_hours("BID")
        bidh = bidh[bidh["v"] > 0]
        g = bidh.groupby(bidh.index.floor("D"))
        mine = pd.DataFrame({"c": g["c"].last(), "h": g["h"].max(), "l": g["l"].min()})
        j = dday.join(mine, how="inner", rsuffix="_m")
        bad = j[(j["c"] - j["c_m"]).abs() > 1]
        other = bad[bad.index.dayofweek != 4]
        q["vs_dukascopy_daily_candles_note"] = (
            f"{int((bad.index.dayofweek == 4).sum())} of the {len(bad)} days that differ by more than $1 are Friday closes (the daily candle "
            "includes ticks after the last hourly bar). The others: "
            + "; ".join(f"{d.date()} (${(r.c - r.c_m):+.2f})" for d, r in other.iterrows())
            + ". On 2024-12-12 Dukascopy's daily candle ($2,714-2,717) contradicts its own hourly file (~$2,680) and COMEX; the hourly file is used.")
        q["vs_dukascopy_daily_candles"] = {"days_compared": int(len(j)),
                                           "close_abs_diff_median": round(float((j["c"] - j["c_m"]).abs().median()), 4),
                                           "close_abs_diff_max": round(float((j["c"] - j["c_m"]).abs().max()), 4),
                                           "days_close_diff_over_1usd": int(((j["c"] - j["c_m"]).abs() > 1).sum())}
    except Exception as exc:  # noqa: BLE001
        q["vs_dukascopy_daily_candles"] = f"not run: {exc}"
    # COMEX GC=F (Yahoo): daily close-to-close returns, and hourly returns over the last 730 days
    try:
        gc = _yahoo("GC=F_1d.json")
        gc.index = gc.index.tz_convert(NY).normalize().tz_localize(None)
        gc = gc[~gc.index.duplicated(keep="last")]
        j = pd.DataFrame({"duka": D["c"], "comex": gc["close"]}).dropna()
        rr = np.log(j).diff().dropna()
        diff = (rr["duka"] - rr["comex"]).abs()
        # Yahoo's GC=F daily close is the COMEX settlement (~13:30 New York): align Dukascopy to it too
        ny = H.index.tz_convert(NY)
        h13 = H[ny.hour == 13]
        p13 = pd.Series(h13["o"].values, index=pd.to_datetime(ny[ny.hour == 13].date))
        p13 = p13[~p13.index.duplicated(keep="last")]
        j13 = pd.DataFrame({"duka": p13, "comex": gc["close"]}).dropna()
        r13 = np.log(j13[j13.index >= "2010-01-01"]).diff().dropna()
        q["vs_comex_daily_at_settlement"] = {"days": int(len(r13)), "return_correlation": round(float(r13.corr().iloc[0, 1]), 4),
                                             "days_return_diff_over_1pct": int(((r13["duka"] - r13["comex"]).abs() > 0.01).sum()),
                                             "note": "Dukascopy at 13:00 New York against Yahoo's GC=F close (the COMEX settlement)"}
        q["vs_comex_daily"] = {"days": int(len(rr)), "return_correlation": round(float(rr.corr().iloc[0, 1]), 4),
                               "days_return_diff_over_1pct": int((diff > 0.01).sum()),
                               "median_abs_return_diff_bp": round(float(diff.median() * 1e4), 2),
                               "basis_median_pct": round(float(((j["comex"] / j["duka"]) - 1).median() * 100), 3),
                               "note": "COMEX continuous front month: roll days carry the futures basis; Yahoo's daily close is not "
                                       "exactly 17:00 New York, so single-day differences are expected"}
        gh = _yahoo("GC=F_1h.json")
        gh = gh[~gh.index.duplicated(keep="last")]
        jh = pd.DataFrame({"duka": H["c"], "comex": gh["close"].reindex(H.index)}).dropna()
        jh = jh[jh.index >= gh.index[0]]
        rh = np.log(jh).diff().dropna()
        rh = rh[(rh.index.to_series().diff() == pd.Timedelta(hours=1)).values]
        q["vs_comex_hourly"] = {"hours": int(len(rh)), "from": str(jh.index[0]), "return_correlation": round(float(rh.corr().iloc[0, 1]), 4),
                                "hours_return_diff_over_0.5pct": int(((rh["duka"] - rh["comex"]).abs() > 0.005).sum())}
    except Exception as exc:  # noqa: BLE001
        q["vs_comex_daily"] = f"not run: {exc}"
    return q


if __name__ == "__main__":
    bars = build()
    q = quality(bars)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "data_quality.json").write_text(json.dumps(q, indent=1))
    print(json.dumps({k: v for k, v in q.items() if k not in ("by_year", "intra_session_gaps_over_2h", "weekdays_without_a_session")}, indent=1))
    print("weekdays without a session:", len(q["weekdays_without_a_session"]), q["weekdays_without_a_session"][:40])
    print("gaps > 2h inside sessions:", len(q["intra_session_gaps_over_2h"]))
    for g in q["intra_session_gaps_over_2h"][:25]:
        print("  ", g)
    print("by year:")
    for y, v in q["by_year"].items():
        print("  ", y, v)
