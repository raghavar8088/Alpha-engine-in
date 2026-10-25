"""NIFTYBEES 5-minute OHLCV, 2021-10-25 -> 2026-10-23, built from Angel One's 1-minute candles.

    python -I backend/research/niftybees_orb_2026_10/orb_data.py

SOURCES (both are Angel One's ONE_MINUTE candles, the app's licensed broker feed; NSE token 10576)
  * 2019-01 .. 2026-10-09  the index-intraday study's download (../index_intraday_2026_10/ii_fetch.py),
                           30-day files in ../index_intraday_2026_10/data/1m/NIFTYBEES/
  * 2026-10-12 .. 2026-10-23  the app's daily appends on the server (/data/intraday/idx1m/), copied
                           into data/box_1m/
  NIFTY 50 index minutes from the same two places give the reference calendar and the check on
  NIFTYBEES's opening prints. NIFTY is never used as a trading price.

  A 5-minute bar is built from its five 1-minute bars (09:15, 09:20, ... 15:25; 75 a day): open of
  the first, highest high, lowest low, close of the last, summed volume. Angel's own FIVE_MINUTE
  candles are built from the same trades. The minutes are kept as well, for the 1-minute check of
  what happened inside a 5-minute candle.

QUALITY RULES (each one counted in results/data_quality.json, never silent)
  1. Only the regular session, 09:15-15:29 IST. A day is kept only if its 09:15 minute exists and it
     has at least 360 of the 375 minutes. That drops Muhurat sessions (2025's ran 13:45-14:45),
     disaster-recovery test sessions and days a download cut short.
  2. A missing minute inside a kept day is flat at the previous close with zero volume: no move is
     invented.
  3. A print at or below zero, or more than 15% from the day's median close, is dropped (the
     index-intraday module's rule).
  4. THE OPENING PRINTS. NIFTYBEES's 09:15 minute carries the pre-open auction price and the first
     trades into a thin book. Its open lies a median 0.49% from where NIFTY 50 puts the ETF, and 10% of
     days lie more than 2.3% away. Its close lies only 0.04% away, and later minutes 0.02%
     (results/data_quality.json, opening_prints.deviation_from_nifty_bp). Those prints
     would set the opening range, so for the range only (09:15-09:29) each minute's open, high and low
     are checked against the band the NIFTY 50 index implies for that same minute: the index's high
     and low x the ETF/index ratio of 09:16-09:29, widened by TOL = 0.2% (99% of continuous-trading
     minutes, 09:45-15:14, sit within 0.17% of the index-implied price). A print outside the band is replaced
     by the minute's own in-band open or close, so the range stays a NIFTYBEES price. A minute whose
     close is outside the band too has no usable print and leaves the range. When NIFTY's own 09:15
     minute is missing, the band comes from the ETF's 09:16-09:19 range instead. The raw range is
     kept too, and the backtest is run on both.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
SRC_STUDY = RESEARCH / "index_intraday_2026_10" / "data" / "1m"
SRC_BOX = HERE / "data" / "box_1m"
OUT = HERE / "data"
RES = HERE / "results"

START, END = date(2021, 10, 25), date(2026, 10, 23)        # five years to the last session
SESSION = 375                                              # minutes 09:15 .. 15:29
OPEN_MIN = 9 * 60 + 15
MIN_MINUTES = 360
MAX_DEV = 0.15
OR_MINUTES = 15                                            # 09:15 .. 09:29
TOL = 0.002                                                # the opening-print band is widened by 0.2%
TOLS = (0.002, 0.005)                                      # primary, and the looser band run for comparison
TICK = 0.01

# NSE weekday closures in the window (exchange circulars; 2026 from tradingai_shared.nse_calendar).
# Diwali Laxmi Pujan days have only the evening Muhurat session.
NSE_HOLIDAYS = {
    "2021-11-04": "Diwali Laxmi Pujan (Muhurat only)", "2021-11-05": "Diwali Balipratipada",
    "2021-11-19": "Gurunanak Jayanti",
    "2022-01-26": "Republic Day", "2022-03-01": "Mahashivratri", "2022-03-18": "Holi",
    "2022-04-14": "Mahavir / Ambedkar Jayanti", "2022-04-15": "Good Friday", "2022-05-03": "Id-ul-Fitr",
    "2022-08-09": "Muharram", "2022-08-15": "Independence Day", "2022-08-31": "Ganesh Chaturthi",
    "2022-10-05": "Dussehra", "2022-10-24": "Diwali Laxmi Pujan (Muhurat only)",
    "2022-10-26": "Diwali Balipratipada", "2022-11-08": "Gurunanak Jayanti",
    "2023-01-26": "Republic Day", "2023-03-07": "Holi", "2023-03-30": "Ram Navami",
    "2023-04-04": "Mahavir Jayanti", "2023-04-07": "Good Friday", "2023-04-14": "Ambedkar Jayanti",
    "2023-05-01": "Maharashtra Day", "2023-06-29": "Bakri Id", "2023-08-15": "Independence Day",
    "2023-09-19": "Ganesh Chaturthi", "2023-10-02": "Gandhi Jayanti", "2023-10-24": "Dussehra",
    "2023-11-14": "Diwali Balipratipada", "2023-11-27": "Gurunanak Jayanti", "2023-12-25": "Christmas",
    "2024-01-22": "Ram Mandir (special holiday)", "2024-01-26": "Republic Day",
    "2024-03-08": "Mahashivratri", "2024-03-25": "Holi", "2024-03-29": "Good Friday",
    "2024-04-11": "Id-ul-Fitr", "2024-04-17": "Ram Navami", "2024-05-01": "Maharashtra Day",
    "2024-05-20": "Lok Sabha election (Mumbai)", "2024-06-17": "Bakri Id", "2024-07-17": "Muharram",
    "2024-08-15": "Independence Day", "2024-10-02": "Gandhi Jayanti",
    "2024-11-01": "Diwali Laxmi Pujan (Muhurat only)", "2024-11-15": "Gurunanak Jayanti",
    "2024-11-20": "Maharashtra assembly election", "2024-12-25": "Christmas",
    "2025-02-26": "Mahashivratri", "2025-03-14": "Holi", "2025-03-31": "Id-ul-Fitr",
    "2025-04-10": "Mahavir Jayanti", "2025-04-14": "Ambedkar Jayanti", "2025-04-18": "Good Friday",
    "2025-05-01": "Maharashtra Day", "2025-08-15": "Independence Day", "2025-08-27": "Ganesh Chaturthi",
    "2025-10-02": "Gandhi Jayanti / Dussehra", "2025-10-21": "Diwali Laxmi Pujan (Muhurat only)",
    "2025-10-22": "Diwali Balipratipada", "2025-11-05": "Gurunanak Jayanti", "2025-12-25": "Christmas",
}
# Weekend days the exchange opened (a full session unless noted).
SPECIAL_SESSIONS = {
    "2024-01-20": "Saturday session (in lieu of 22 Jan)",
    "2024-03-02": "Saturday disaster-recovery drill (two short sessions)",
    "2024-05-18": "Saturday disaster-recovery drill (two short sessions)",
    "2025-02-01": "Saturday session (Union Budget)",
    "2026-02-01": "Sunday session (Union Budget)",
}


def _holidays() -> dict[str, str]:
    sys.path[:0] = [str(RESEARCH.parents[1] / "shared")]
    from tradingai_shared.nse_calendar import NSE_HOLIDAYS as H2026
    out = dict(NSE_HOLIDAYS)
    out.update({k: v for k, v in H2026.items() if k.startswith("2026")})
    return out


def read_rows(name: str) -> tuple[np.ndarray, dict]:
    """Every row of a symbol from both sources: (n, 6) ts, o, h, l, c, v."""
    files = sorted((SRC_STUDY / name).glob("*.csv.gz")) + sorted((SRC_BOX / name).glob("*.csv.gz"))
    parts, bad_rows = [], 0
    for f in files:
        df = pd.read_csv(f, usecols=range(6), on_bad_lines="skip")
        a = df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        ok = ~np.isnan(a[:, :5]).any(axis=1)
        bad_rows += int((~ok).sum())
        a = a[ok]
        a[np.isnan(a[:, 5]), 5] = 0.0
        parts.append(a)
    rows = np.concatenate(parts)
    return rows, {"files": len(files), "unparsable_rows": bad_rows}


def build(name: str, rows: np.ndarray) -> dict:
    """Rows -> per-day minute matrices for the window, with every quality rule counted."""
    ts = rows[:, 0].astype(np.int64)
    local = ts + 19800
    dayn = local // 86400
    m = (local % 86400) // 60 - OPEN_MIN
    lo, hi = np.datetime64(START, "D").astype(np.int64), np.datetime64(END, "D").astype(np.int64)
    inwin = (dayn >= lo) & (dayn <= hi)
    rows, dayn, m, ts = rows[inwin], dayn[inwin], m[inwin], ts[inwin]
    q: dict = {"rows_in_window": int(len(rows))}
    inside = (m >= 0) & (m < SESSION)
    q["rows_outside_0915_1529"] = int((~inside).sum())
    outside_days = sorted({str(np.datetime64(int(d), "D")) for d in np.unique(dayn[~inside])})
    q["days_with_rows_outside_session"] = outside_days
    rows, dayn, m, ts = rows[inside], dayn[inside], m[inside], ts[inside]
    # duplicates: the later file wins (files are read in date order)
    key = dayn * SESSION + m
    _, last_idx = np.unique(key[::-1], return_index=True)
    keep = np.zeros(len(key), bool)
    keep[len(key) - 1 - last_idx] = True
    q["duplicate_minutes"] = int(len(key) - keep.sum())
    rows, dayn, m = rows[keep], dayn[keep], m[keep]
    order = np.lexsort((m, dayn))
    rows, dayn, m = rows[order], dayn[order], m[order]
    # price sanity (rule 3)
    bad = (rows[:, 1:5] <= 0).any(axis=1)
    close = pd.Series(np.where(rows[:, 4] > 0, rows[:, 4], np.nan))
    med = close.groupby(dayn).transform("median").to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        dev = np.abs(rows[:, 1:5] / med[:, None] - 1.0).max(axis=1)
    bad |= ~(dev <= MAX_DEV)
    q["prints_dropped_nonpositive_or_15pct"] = [
        {"date": str(np.datetime64(int(d), "D")), "minute": hhmm(int(mm)), "ohlc": [float(x) for x in r[1:5]]}
        for d, mm, r in zip(dayn[bad], m[bad], rows[bad])]
    rows, dayn, m = rows[~bad], dayn[~bad], m[~bad]
    days_u, first, counts = np.unique(dayn, return_index=True, return_counts=True)
    has_open = m[first] == 0
    keep_day = has_open & (counts >= MIN_MINUTES)
    q["days_with_any_row"] = int(len(days_u))
    q["days_dropped"] = [{"date": str(np.datetime64(int(d), "D")), "minutes": int(c),
                          "first_minute": hhmm(int(m[f])),
                          "reason": "no 09:15 minute" if not ho else f"only {c} of 375 minutes"}
                         for d, c, f, ho, k in zip(days_u, counts, first, has_open, keep_day) if not k]
    kd = days_u[keep_day]
    n = len(kd)
    slot = np.full(len(days_u), -1)
    slot[keep_day] = np.arange(n)
    di = slot[np.searchsorted(days_u, dayn)]
    sel = di >= 0
    O, H, L, C, V = (np.full((n, SESSION), np.nan) for _ in range(5))
    P = np.zeros((n, SESSION), bool)
    for arr, col in ((O, 1), (H, 2), (L, 3), (C, 4), (V, 5)):
        arr[di[sel], m[sel]] = rows[sel, col]
    P[di[sel], m[sel]] = True
    src = np.where(P, np.arange(SESSION)[None, :], 0)
    np.maximum.accumulate(src, axis=1, out=src)
    flat = C[np.arange(n)[:, None], src]
    for arr in (O, H, L, C):
        arr[~P] = flat[~P]
    V[~P] = 0.0
    np.maximum(H, np.maximum(O, C), out=H)
    np.minimum(L, np.minimum(O, C), out=L)
    miss = [{"date": str(np.datetime64(int(d), "D")), "missing": int((~P[i]).sum()),
             "minutes": [hhmm(int(x)) for x in np.where(~P[i])[0]][:40]}
            for i, d in enumerate(kd) if (~P[i]).any()]
    q["kept_days"] = n
    q["kept_days_with_missing_minutes"] = miss
    q["minutes_filled_flat"] = int((~P).sum())
    q["zero_volume_printed_minutes"] = int(((V <= 0) & P).sum())
    return {"name": name, "days": kd.astype("datetime64[D]"), "o": O, "h": H, "l": L, "c": C, "v": V,
            "present": P, "quality": q}


def hhmm(minute: int) -> str:
    t = OPEN_MIN + minute
    return f"{t // 60:02d}:{t % 60:02d}"


def calendar_audit(bees: dict, nifty: dict, extra_bees_days: np.ndarray, extra_nifty_days: np.ndarray) -> dict:
    """Expected NSE sessions (weekdays - holidays + special sessions) vs what each series has."""
    hol = _holidays()
    expected, d = [], START
    while d <= END:
        iso = d.isoformat()
        if (d.weekday() < 5 and iso not in hol) or iso in SPECIAL_SESSIONS:
            expected.append(iso)
        d += timedelta(days=1)
    have_b = {str(x) for x in extra_bees_days}
    have_n = {str(x) for x in extra_nifty_days}
    kept_b = {str(x) for x in bees["days"]}
    exp = set(expected)
    return {
        "expected_sessions": len(expected),
        "holidays_in_window": {k: v for k, v in sorted(hol.items()) if START.isoformat() <= k <= END.isoformat()},
        "special_sessions": SPECIAL_SESSIONS,
        "expected_but_no_niftybees_rows": sorted(exp - have_b),
        "expected_but_no_nifty_rows": sorted(exp - have_n),
        "niftybees_rows_on_unexpected_days": sorted(have_b - exp),
        "nifty_rows_on_unexpected_days": sorted(have_n - exp),
        "niftybees_sessions_kept": len(kept_b),
        "expected_sessions_not_kept": sorted(exp - kept_b),
    }


def clean_opening(bees: dict, nifty: dict, tol: float = TOL) -> list[dict]:
    """Rule 4: the opening range from NIFTYBEES prints that agree with the market (see the docstring).
    Returns one record per kept NIFTYBEES day with the raw and the clean range."""
    TOL = tol  # noqa: N806 - the band width for this pass
    nidx = {str(d): i for i, d in enumerate(nifty["days"])}
    out = []
    for i, d in enumerate(bees["days"]):
        o, h, l, c = (bees[k][i, :OR_MINUTES].copy() for k in "ohlc")
        pres = bees["present"][i, :OR_MINUTES]
        raw_h, raw_l = float(h.max()), float(l.min())
        j = nidx.get(str(d))
        ref = "nifty"
        nb = (nifty["present"][j, 1:OR_MINUTES] & pres[1:]) if j is not None else np.zeros(OR_MINUTES - 1, bool)
        if j is not None and nifty["present"][j, 0] and nb.sum() >= 10:
            k = float(np.median(c[1:][nb] / nifty["c"][j, 1:OR_MINUTES][nb]))
            band_hi = nifty["h"][j, :OR_MINUTES] * k * (1 + TOL)
            band_lo = nifty["l"][j, :OR_MINUTES] * k * (1 - TOL)
            # a NIFTY minute that is itself missing gives no band for that minute
            nok = nifty["present"][j, :OR_MINUTES]
            band_hi = np.where(nok, band_hi, np.inf)
            band_lo = np.where(nok, band_lo, -np.inf)
        else:
            ref = "own 09:16-09:19 range"
            band_hi = np.full(OR_MINUTES, np.inf)
            band_lo = np.full(OR_MINUTES, -np.inf)
            band_hi[0] = h[1:5].max() * (1 + TOL)
            band_lo[0] = l[1:5].min() * (1 - TOL)
        changed = []
        dropped_minutes = []
        use = np.ones(OR_MINUTES, bool)
        for mm in range(OR_MINUTES):
            inb = lambda x: band_lo[mm] <= x <= band_hi[mm]  # noqa: E731
            if not pres[mm]:
                continue
            if not inb(c[mm]):
                use[mm] = False
                dropped_minutes.append(hhmm(mm))
                continue
            sane = [x for x in (o[mm], c[mm]) if inb(x)]
            nh = h[mm] if inb(h[mm]) else max(sane)
            nl = l[mm] if inb(l[mm]) else min(sane)
            if nh != h[mm] or nl != l[mm]:
                changed.append({"minute": hhmm(mm), "raw_hl": [float(h[mm]), float(l[mm])],
                                "clean_hl": [float(nh), float(nl)],
                                "band": [round(float(band_lo[mm]), 2), round(float(band_hi[mm]), 2)]})
            h[mm], l[mm] = nh, nl
        cl_h, cl_l = float(h[use].max()), float(l[use].min())
        out.append({"date": str(d), "raw_orh": raw_h, "raw_orl": raw_l, "orh": cl_h, "orl": cl_l,
                    "reference": ref, "changed": changed, "minutes_left_out": dropped_minutes,
                    "or_minutes_missing": int((~pres).sum())})
    return out


def print_deviation(bees: dict, nifty: dict) -> dict:
    """How far NIFTYBEES prints sit from the price NIFTY 50 implies, in bp: the 09:15 minute's open and
    close (ratio from 09:16-09:29) against continuous trading, 09:45-15:14 closes (ratio of that day's
    09:45-15:14 closes). The numbers behind rule 4."""
    nidx = {str(d): i for i, d in enumerate(nifty["days"])}
    op, cl, cont = [], [], []
    for i, d in enumerate(bees["days"]):
        j = nidx.get(str(d))
        if j is None or not nifty["present"][j, 0]:
            continue
        both = bees["present"][i] & nifty["present"][j]
        nb = both[1:OR_MINUTES]
        if nb.sum() < 10:
            continue
        k = float(np.median(bees["c"][i, 1:OR_MINUTES][nb] / nifty["c"][j, 1:OR_MINUTES][nb]))
        op.append(abs(bees["o"][i, 0] / (nifty["o"][j, 0] * k) - 1) * 1e4)
        cl.append(abs(bees["c"][i, 0] / (nifty["c"][j, 0] * k) - 1) * 1e4)
        cm = both.copy()
        cm[:30] = False
        cm[360:] = False
        if cm.sum() >= 200:
            kd = float(np.median(bees["c"][i][cm] / nifty["c"][j][cm]))
            cont.extend((np.abs(bees["c"][i][cm] / (nifty["c"][j][cm] * kd) - 1) * 1e4).tolist())
    q = lambda a, p: round(float(np.percentile(a, p)), 1)  # noqa: E731
    return {"sessions": len(op),
            "open_0915": {"median": q(op, 50), "p90": q(op, 90), "share_over_50bp_pct": round(float(np.mean(np.array(op) > 50) * 100), 1)},
            "close_0915": {"median": q(cl, 50), "p90": q(cl, 90)},
            "continuous_0945_1514_close": {"minutes": len(cont), "median": q(cont, 50), "p99": q(cont, 99), "p999": q(cont, 99.9)}}


def bars5(d: dict) -> dict:
    starts = np.arange(0, SESSION, 5)
    o = d["o"][:, starts]
    c = d["c"][:, starts + 4]
    h = d["h"].reshape(len(d["days"]), -1, 5).max(axis=2)
    lo = d["l"].reshape(len(d["days"]), -1, 5).min(axis=2)
    v = d["v"].reshape(len(d["days"]), -1, 5).sum(axis=2)
    n = d["present"].reshape(len(d["days"]), -1, 5).sum(axis=2)
    return {"o": o, "h": h, "l": lo, "c": c, "v": v, "n": n, "start": starts}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    RES.mkdir(exist_ok=True)
    rb, qb = read_rows("NIFTYBEES")
    rn, qn = read_rows("NIFTY")
    bees, nifty = build("NIFTYBEES", rb), build("NIFTY", rn)
    bees["quality"].update(qb)
    nifty["quality"].update(qn)

    def days_with_rows(rows):
        loc = rows[:, 0].astype(np.int64) + 19800
        dn = loc // 86400
        mm = (loc % 86400) // 60 - OPEN_MIN
        dn = dn[(mm >= 0) & (mm < SESSION)]
        lo, hi = np.datetime64(START, "D").astype(np.int64), np.datetime64(END, "D").astype(np.int64)
        return np.unique(dn[(dn >= lo) & (dn <= hi)]).astype("datetime64[D]")

    cal = calendar_audit(bees, nifty, days_with_rows(rb), days_with_rows(rn))
    passes = {t: clean_opening(bees, nifty, t) for t in TOLS}
    opening = passes[TOL]
    for t, recs in passes.items():
        for r, p in zip(opening, recs):
            r.setdefault("clean_by_tol", {})[f"{t:.3f}"] = [p["orl"], p["orh"]]
    b5 = bars5(bees)

    # outputs: the 5-minute bars (raw: only rules 1-3), the minutes, the opening ranges
    with gzip.open(OUT / "NIFTYBEES_5m.csv.gz", "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "time", "open", "high", "low", "close", "volume", "minutes_printed"])
        for i, d in enumerate(bees["days"]):
            for k, s in enumerate(b5["start"]):
                w.writerow([str(d), hhmm(int(s)), f"{b5['o'][i, k]:.2f}", f"{b5['h'][i, k]:.2f}",
                            f"{b5['l'][i, k]:.2f}", f"{b5['c'][i, k]:.2f}", int(b5["v"][i, k]), int(b5["n"][i, k])])
    np.savez_compressed(OUT / "NIFTYBEES_1m.npz", days=bees["days"].astype(str), o=bees["o"], h=bees["h"],
                        l=bees["l"], c=bees["c"], v=bees["v"], present=bees["present"])
    with open(OUT / "opening_ranges.json", "w") as f:
        json.dump(opening, f)

    raw_w = np.array([(r["raw_orh"] / r["raw_orl"] - 1) * 1e4 for r in opening])
    cl_w = np.array([(r["orh"] / r["orl"] - 1) * 1e4 for r in opening])
    yrs = np.array([r["date"][:4] for r in opening])
    changed = np.array([bool(r["changed"] or r["minutes_left_out"]) for r in opening])
    by_year = {}
    for y in sorted(set(yrs)):
        s = yrs == y
        by_year[y] = {"sessions": int(s.sum()), "opening_range_cleaned": int(changed[s].sum()),
                      "median_or_bp_raw": round(float(np.median(raw_w[s])), 1),
                      "median_or_bp_clean": round(float(np.median(cl_w[s])), 1)}
    # NIFTY's own opening range, for scale
    nor = (nifty["h"][:, :OR_MINUTES].max(axis=1) / nifty["l"][:, :OR_MINUTES].min(axis=1) - 1) * 1e4
    nyrs = np.array([str(d)[:4] for d in nifty["days"]])
    for y in by_year:
        by_year[y]["median_or_bp_nifty_index"] = round(float(np.median(nor[nyrs == y])), 1)
    qual = {
        "window": [START.isoformat(), END.isoformat()],
        "source": "Angel One ONE_MINUTE candles, NSE NIFTYBEES (token 10576); NIFTY 50 (99926000) as reference",
        "niftybees": bees["quality"], "nifty_reference": {k: v for k, v in nifty["quality"].items()
                                                         if k in ("kept_days", "days_dropped", "rows_in_window")},
        "calendar": cal,
        "opening_prints": {
            "rule": f"09:15-09:29 prints outside NIFTY-implied band +/-{TOL:.1%} replaced by the minute's in-band open/close",
            "deviation_from_nifty_bp": print_deviation(bees, nifty),
            "sessions": len(opening), "sessions_cleaned": int(changed.sum()),
            "sessions_band_from_own_prices": [r["date"] for r in opening if r["reference"] != "nifty"],
            "by_year": by_year,
            "median_or_bp": {"raw": round(float(np.median(raw_w)), 1), "clean": round(float(np.median(cl_w)), 1),
                             "nifty_index": round(float(np.median(nor)), 1)},
            "largest_changes": sorted(
                [{"date": r["date"], "raw": [r["raw_orl"], r["raw_orh"]], "clean": [r["orl"], r["orh"]]}
                 for r in opening if r["changed"]],
                key=lambda x: -(x["raw"][1] - x["raw"][0] - (x["clean"][1] - x["clean"][0])))[:25],
        },
        "price_range": [float(np.nanmin(bees["l"])), float(np.nanmax(bees["h"]))],
        "tick": TICK,
    }
    with open(RES / "data_quality.json", "w") as f:
        json.dump(qual, f, indent=1)
    print(json.dumps({k: qual[k] for k in ("window", "price_range")}, indent=1))
    print("kept sessions:", bees["quality"]["kept_days"], " dropped:", len(bees["quality"]["days_dropped"]))
    print("calendar:", {k: v for k, v in cal.items() if k not in ("holidays_in_window", "special_sessions")})
    print("opening:", json.dumps(qual["opening_prints"]["by_year"], indent=0))
    print("median OR bp:", qual["opening_prints"]["median_or_bp"], " cleaned sessions:", int(changed.sum()))


if __name__ == "__main__":
    main()
