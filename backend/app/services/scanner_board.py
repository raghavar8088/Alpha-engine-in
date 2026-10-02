"""The Scanner Board — which stocks to watch today, and what the evidence says about each list.

WHAT THE RESEARCH SETTLED (2026-10-02; 200 liquid NSE stocks, 516 sessions, ideas developed
on the first two-thirds and checked unchanged on the last third; cost hurdle 10 bp):

  WHERE a stock will move is predictable. Mean |09:45->15:00| move rises with relative
  volume (96 -> 166 bp), ATR% (60 -> 145), opening gap (98 -> 168), first-30-minute move
  (91 -> 223), India VIX (92 -> 140) and on results days (177 vs 106). A walk-forward
  model of these has an out-of-sample rank correlation of 0.25 with the move; its daily
  top 20 moved 167 bp against 102 for the universe.

  WHICH WAY is not — every direction rule tried (day % change, first-30 momentum, gaps,
  strength vs NIFTY/sector, NIFTY's direction, breadth, global cues, delivery, F&O OI
  buildup, FII/client positioning, results drift, previous candle, NR7) flipped or vanished
  out of sample. The one that held is letting PRICE choose: the first break of the 09:15-
  09:45 range on the highest expected-move names, about +11 bp gross a trade in both
  periods — roughly break-even after real costs, so a CANDIDATE under test, not proven.

So every list here carries an evidence label, and only the label decides how a list may be
used:
  proven      it selects WHERE moves are large — use it to choose what to trade
  candidate   the opening-range-break side — under test, shown, not yet traded on
  context     a direction idea that FAILED out of sample — shown because traders look at
              it, never a reason to go long or short
  forward     no history exists (the NSE pre-open) — recorded daily to be tested later

Everything is point-in-time: at a time T only bars that had CLOSED by T, archives published
before today, and results known before T are read. Snapshots at 08:55, 09:16, 09:45, 10:15
and 11:15 are written to DATA_DIR/selection/<date>/<HHMM>.json exactly as computed, with the
expected move of EVERY stock, so each list can later be checked against what happened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone

from app.core.db import db
from app.services import intraday_universe, market_calendar, nse_archives, preopen, results_calendar
from app.services.intraday_store import day_key, read_file, store

logger = logging.getLogger("scanner_board")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = os.getenv("INTRADAY_DATA_DIR", "/data/intraday")
SNAP_DIR = os.path.join(DATA_DIR, "selection")
SNAPSHOT_TIMES = ("08:55", "09:16", "09:45", "10:15", "11:15")
TOP_N = 30
models = db["selection_models"]
accuracy = db["selection_accuracy"]

EVIDENCE = {
    "expected_move": {"status": "proven", "use": "where", "title": "Expected move (model)",
                      "evidence": "walk-forward rank correlation 0.25 with the 09:45->15:00 move; its top 20 "
                                  "moved 167 bp vs 102 bp for the universe"},
    "in_play": {"status": "proven", "use": "where", "title": "Stocks in play (relative volume)",
                "evidence": "09:45->15:00 move 96 bp at the quietest volume vs 166 bp at 4x normal"},
    "volatility": {"status": "proven", "use": "where", "title": "Volatility (ATR %)",
                   "evidence": "move 60 bp at ATR 1-1.5% vs 145 bp above 3.5%"},
    "gappers": {"status": "proven", "use": "where", "title": "Gappers",
                "evidence": "move 98 bp for gaps under 0.25% vs 168 bp above 4%; the gap's DIRECTION failed "
                            "(fading it +11.8 bp, then -7.2 bp out of sample)"},
    "opening_drive": {"status": "proven", "use": "where", "title": "Opening drive (first 30 min)",
                      "evidence": "move 91 bp after a quiet first half hour vs 223 bp after a 4%+ one; its "
                                  "DIRECTION failed (+4.2 bp, then -3.5 bp)"},
    "results_today": {"status": "proven", "use": "where", "title": "Results reaction today",
                      "evidence": "177 bp on reaction days vs 106 bp otherwise; neither following nor fading "
                                  "the reaction held out of sample"},
    "or_break": {"status": "candidate", "use": "side", "title": "Opening-range break (price picks the side)",
                 "evidence": "first break of 09:15-09:45 on the top expected-move names: ~+11 bp gross in both "
                             "periods, ~break-even after costs, weakening — under test, not traded on"},
    "day_change": {"status": "context", "use": "none", "title": "Top gainers / losers",
                   "evidence": "momentum -3.2 bp then +4.6 bp; reversal the mirror image — no edge either way"},
    "relative_strength": {"status": "context", "use": "none", "title": "Strength vs NIFTY and sector",
                          "evidence": "vs NIFTY +1.7 bp then -1.0 bp; following the sector +8.9 bp then -2.5 bp"},
    "oi_buildup": {"status": "context", "use": "none", "title": "F&O open-interest buildup (yesterday)",
                   "evidence": "long/short buildup did not predict the next session beyond the intraday drift"},
    "delivery": {"status": "context", "use": "none", "title": "Delivery spikes (yesterday)",
                 "evidence": "delivery at 1.5x its habit: +0.1 bp, then -6.3 bp — no edge"},
    "near_extremes": {"status": "context", "use": "none", "title": "Near 20-day high / low",
                      "evidence": "at the 20-day high and up at 09:45: -5.4 bp, then +0.3 bp"},
    "preopen": {"status": "forward", "use": "none", "title": "NSE pre-open movers and imbalance",
                "evidence": "no history exists anywhere; recorded daily from 2026-10-05 to be tested"},
}


# ── point-in-time state ──────────────────────────────────────────────────────────


def _sessions(sym: str, cutoff: int, n_prev: int = 25) -> tuple[list[tuple], list[list[tuple]]]:
    """(today's 15m rows that had CLOSED by `cutoff`, the previous sessions' rows, oldest first)."""
    b = store.get(sym)
    hi = bisect_right(b.t, cutoff - 900)
    t0 = bisect_left(b.t, day_key(cutoff) * 86400 - 19800, 0, hi)
    rows_today = [(b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i]) for i in range(t0, hi)]
    prev: list[list[tuple]] = []
    j = t0 - 1
    while j >= 0 and len(prev) < n_prev:
        k = day_key(b.t[j])
        start = j
        while start > 0 and day_key(b.t[start - 1]) == k:
            start -= 1
        prev.append([(b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i]) for i in range(start, j + 1)])
        j = start - 1
    prev.reverse()
    return rows_today, prev


def _minute(epoch: int) -> int:
    return ((epoch + 19800) % 86400) // 60


def _summ(rows: list[tuple]) -> dict:
    return {"o": rows[0][1], "h": max(r[2] for r in rows), "l": min(r[3] for r in rows), "c": rows[-1][4],
            "v30": sum(r[5] for r in rows[:2])}


def _ist_text(iso: str | None) -> str | None:
    try:
        return datetime.fromisoformat(iso).astimezone(IST).strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return None


def _features(sym: str, cutoff: int, ctx: dict) -> dict | None:
    rows_today, prev = _sessions(sym, cutoff)
    if len(prev) < 15:
        return None
    days = [_summ(p) for p in prev]
    pc = days[-1]["c"]
    trs = [max(d["h"] - d["l"], abs(d["h"] - p["c"]), abs(d["l"] - p["c"])) for p, d in zip(days[-15:-1], days[-14:])]
    atr = sum(trs) / len(trs)
    if not atr or not pc:
        return None
    res = ctx["results"].get(sym)
    f = {"symbol": sym, "prev_close": pc, "atr_pct": atr / pc * 100,
         "prev_range_atr": (days[-1]["h"] - days[-1]["l"]) / atr,
         "ret5": (pc / days[-6]["c"] - 1) * 100 if len(days) >= 6 else None,
         "hi20": max(d["h"] for d in days[-20:]), "lo20": min(d["l"] for d in days[-20:]),
         "results": res is not None, "sector": ctx["sector_of"].get(sym), "bars_today": len(rows_today)}
    if res:
        f["results_info"] = {"kind": res["kind"], "at": _ist_text(res.get("at"))}
    pre = ctx["pre"]
    if pre and sym in pre:
        iep, _ppc, pchg, fq, tb, ts_ = pre[sym]
        f["pre_gap_pct"] = pchg
        f["pre_iep"] = iep
        f["pre_imbalance"] = (tb - ts_) / (tb + ts_) if tb is not None and ts_ is not None and (tb + ts_) else None
        f["pre_qty"] = fq
    # a session is usable only from its 09:15 bar on (a hole there would misplace everything)
    if rows_today and _minute(rows_today[0][0]) == 555:
        k = len(rows_today)
        f.update({"open": rows_today[0][1], "last": rows_today[-1][4],
                  "day_high": max(r[2] for r in rows_today), "day_low": min(r[3] for r in rows_today)})
        f["gap_pct"] = (f["open"] / pc - 1) * 100
        f["chg_pct"] = (f["last"] / pc - 1) * 100
        base = [sum(r[5] for r in p[:k]) for p in prev[-14:] if len(p) >= k]
        if base and sum(base):
            f["rvol"] = sum(r[5] for r in rows_today) / (sum(base) / len(base))
        if k >= 2 and _minute(rows_today[1][0]) == 570:
            base30 = [d["v30"] for d in days[-14:]]
            if sum(base30):
                f["rvol30"] = sum(r[5] for r in rows_today[:2]) / (sum(base30) / len(base30))
            or_hi, or_lo = max(r[2] for r in rows_today[:2]), min(r[3] for r in rows_today[:2])
            f.update({"or_high": or_hi, "or_low": or_lo, "first30_pct": (rows_today[1][4] / f["open"] - 1) * 100})
            brk = None
            for r in rows_today[2:]:
                up, dn = r[2] > or_hi, r[3] < or_lo
                if up and dn:
                    brk = {"side": None, "at": r[0], "note": "both sides broke in one bar"}
                    break
                if up or dn:
                    brk = {"side": "LONG" if up else "SHORT", "at": r[0], "level": or_hi if up else or_lo}
                    break
            f["or_break"] = brk
        if ctx["nifty_chg"] is not None:
            f["rs_nifty"] = f["chg_pct"] - ctx["nifty_chg"]
        sec = intraday_universe.sector_index(f["sector"])
        if sec != "NIFTY" and sec in ctx["sector_chg"]:
            f["sector_index"] = sec
            f["rs_sector"] = f["chg_pct"] - ctx["sector_chg"][sec]
    d1 = ctx["cm_last"].get(sym)
    if d1 and d1[2] is not None and ctx["habit"].get(sym):
        f["deliv_pct"] = d1[2]
        f["deliv_rel"] = d1[2] / ctx["habit"][sym]
        f["prev_ret_pct"] = (d1[0] / d1[1] - 1) * 100 if d1[0] and d1[1] else None
    fo = ctx["fo_last"].get(sym)
    if fo and fo[0] and fo[1] and fo[2]:
        oi_prev = fo[2] - (fo[3] or 0)
        if oi_prev > 0:
            fc, oc = (fo[0] / fo[1] - 1) * 100, (fo[3] or 0) / oi_prev * 100
            f["oi_chg_pct"], f["fut_chg_pct"] = oc, fc
            f["buildup"] = ("long buildup" if fc > 0 and oc > 0 else "short buildup" if fc < 0 and oc > 0
                            else "short covering" if fc > 0 else "long unwinding")
    return f


def _index_chg(sym: str, cutoff: int) -> float | None:
    rows, prev = _sessions(sym, cutoff, 1)
    if not rows or not prev:
        return None
    return (rows[-1][4] / prev[-1][-1][4] - 1) * 100


async def build_state(now: datetime | None = None) -> dict:
    """Everything the scanners read, as of `now` (closed bars only)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    cutoff = int(now.timestamp())
    # on a closed day the board is about the NEXT session: its results, its archives
    today = now.date()
    if not market_calendar.is_listed_trading_day(today):
        today = market_calendar.next_trading_day(today)
    members = await intraday_universe.members()
    syms = [m["symbol"] for m in members]
    meta = {m["symbol"]: m for m in members}
    await store.preload(syms + list(intraday_universe.INDEX_TOKENS))     # no-op once loaded
    sector_of = {d["symbol"]: d.get("sector") async for d in
                 db["stock_universe"].find({"symbol": {"$in": syms}}, {"symbol": 1, "sector": 1})}
    sector_chg = {}
    for s_ in set(intraday_universe.SECTOR_INDEX.values()):
        c = _index_chg(s_, cutoff)
        if c is not None:
            sector_chg[s_] = c
    hist = await asyncio.to_thread(nse_archives.recent, "cm", today, 21)     # published before today
    habit = {}
    if len(hist) >= 11:
        for sym in syms:
            vals = [h[1]["x"][sym][2] for h in hist[:-1] if sym in h[1]["x"] and h[1]["x"][sym][2] is not None]
            if len(vals) >= 10:
                habit[sym] = sum(vals) / len(vals)
    fo_hist = await asyncio.to_thread(nse_archives.recent, "fo", today, 1)
    pre_doc = preopen.load(today) if (today == now.date() and now.strftime("%H:%M") >= "09:08") else None
    ctx = {"nifty_chg": _index_chg("NIFTY", cutoff), "sector_chg": sector_chg, "sector_of": sector_of,
           "cm_last": hist[-1][1]["x"] if hist else {}, "habit": habit,
           "fo_last": fo_hist[-1][1]["x"] if fo_hist else {},
           "results": await results_calendar.reacting_on(today), "pre": (pre_doc or {}).get("x")}
    feats = []
    for n, sym in enumerate(syms):
        try:
            f = _features(sym, cutoff, ctx)
        except Exception:  # noqa: BLE001 - one bad symbol never empties the board
            logger.exception("features failed for %s", sym)
            f = None
        if f:
            f["turnover_cr"] = meta[sym].get("turnover_cr")
            feats.append(f)
        if n % 25 == 24:
            await asyncio.sleep(0)
    model = await load_model()
    variants: dict[str, int] = {}
    for f in feats:
        f["expected_move_bp"], f["em_variant"] = predict(model, f)
        variants[f["em_variant"] or "none"] = variants.get(f["em_variant"] or "none", 0) + 1
    return {"at": now.isoformat(), "hhmm": now.strftime("%H:%M"), "date": now.date().isoformat(),
            "session": today.isoformat(),
            "nifty_chg_pct": ctx["nifty_chg"], "sector_chg_pct": sector_chg, "stocks": feats,
            "universe": len(syms), "archives_from": hist[-1][0].isoformat() if hist else None,
            "preopen": bool(ctx["pre"]), "results_today": len(ctx["results"]),
            "model": ({k: model.get(k) for k in ("trained_at", "samples", "oos", "y_mean_bp")} | {"variants": variants})
            if model else None}


# ── the expected-move model ──────────────────────────────────────────────────────

# Three nested variants; the richest whose inputs exist is used: before the open only what
# yesterday left (08:55), then the pre-open/opening gap (09:16), then the first half hour.
BASE = ("log_rvol30", "atr_pct", "abs_gap", "abs_first30", "prev_range_atr", "results")
VARIANTS = (
    ("0945", BASE),
    ("open", ("atr_pct", "abs_gap", "prev_range_atr", "results")),
    ("pre", ("atr_pct", "prev_range_atr", "results")),
)


def _vector(f: dict, names: tuple) -> list[float] | None:
    out = []
    for n in names:
        if n == "log_rvol30":
            v = math.log(max(f["rvol30"], 0.05)) if f.get("rvol30") else None
        elif n == "abs_gap":
            g = f.get("gap_pct") if f.get("gap_pct") is not None else f.get("pre_gap_pct")
            v = abs(g) if g is not None else None
        elif n == "abs_first30":
            v = abs(f["first30_pct"]) if f.get("first30_pct") is not None else None
        elif n == "results":
            v = 1.0 if f.get("results") else 0.0
        else:
            v = f.get(n)
        if v is None:
            return None
        out.append(float(v))
    return out + [1.0]


def predict(model: dict | None, f: dict) -> tuple[float | None, str | None]:
    """Expected |move| (bp) from 09:45 to 15:00 and which variant produced it. A RANKING
    quantity: what it is for is the order it puts the stocks in."""
    if not model:
        return None, None
    for name, feats in VARIANTS:
        w = (model.get("weights") or {}).get(name)
        if not w:
            continue
        x = _vector(f, feats)
        if x is not None:
            return round(sum(a * b for a, b in zip(x, w)), 1), name
    return None, None


async def load_model() -> dict | None:
    return await models.find_one({"_id": "expected_move"})


def _samples(symbols: list[str], reaction: dict[str, set[int]], sessions_back: int) -> tuple[list, list, list]:
    """(day keys, BASE feature rows, |09:45->15:00| bp) from the stored 15m history. Rows,
    not dicts: ~50k samples as dicts would be ~30 MB in a backend that runs near its cap."""
    D, F, Y = [], [], []
    for sym in symbols:
        b = read_file(sym)
        if len(b) < 1000:
            continue
        days: dict[int, list[int]] = {}
        for i in range(len(b)):
            days.setdefault(day_key(b.t[i]), []).append(i)
        keys = sorted(days)[-(sessions_back + 16):]
        summ = {k: {"h": max(b.h[i] for i in days[k]), "l": min(b.l[i] for i in days[k]),
                    "c": b.c[days[k][-1]], "v30": sum(b.v[i] for i in days[k][:2])} for k in keys}
        for n in range(16, len(keys)):
            k = keys[n]
            ix = days[k]
            if len(ix) < 22 or _minute(b.t[ix[0]]) != 555 or _minute(b.t[ix[1]]) != 570:
                continue
            p1500 = next((b.o[i] for i in ix if _minute(b.t[i]) == 900), None)
            if p1500 is None:
                continue
            prev = [summ[keys[j]] for j in range(n - 15, n)]
            pc = prev[-1]["c"]
            trs = [max(d["h"] - d["l"], abs(d["h"] - p["c"]), abs(d["l"] - p["c"])) for p, d in zip(prev[:-1], prev[1:])]
            atr = sum(trs) / len(trs)
            base = sum(p["v30"] for p in prev[-14:]) / 14
            if not atr or not base or not pc:
                continue
            o, p0945 = b.o[ix[0]], b.c[ix[1]]
            x = _vector({"rvol30": summ[k]["v30"] / base, "atr_pct": atr / pc * 100, "gap_pct": (o / pc - 1) * 100,
                         "first30_pct": (p0945 / o - 1) * 100,
                         "prev_range_atr": (prev[-1]["h"] - prev[-1]["l"]) / atr,
                         "results": k in reaction.get(sym, ())}, BASE)
            if x is None:
                continue
            F.append(tuple(x[:-1]))
            Y.append(abs(p1500 / p0945 - 1) * 1e4)
            D.append(k)
    return D, F, Y


def _daily_scores(days, pred, y, top: int = 20) -> dict:
    """Mean of each day's cross-sectional rank correlation, and the top-20's mean move vs
    everyone's — the two numbers that say whether the ranking picks movers."""
    import numpy as np
    ics, tops, alls = [], [], []
    for d in np.unique(days):
        m = days == d
        if m.sum() < 30:
            continue
        p, a = pred[m], y[m]
        ics.append(float(np.corrcoef(np.argsort(np.argsort(p)), np.argsort(np.argsort(a)))[0, 1]))
        tops.append(float(a[np.argsort(-p)[:top]].mean()))
        alls.append(float(a.mean()))
    if not ics:
        return {"days": 0}
    return {"days": len(ics), "rank_ic": round(sum(ics) / len(ics), 3),
            "ic_positive_days": round(sum(1 for x in ics if x > 0) / len(ics), 3),
            "top20_move_bp": round(sum(tops) / len(tops), 1), "all_move_bp": round(sum(alls) / len(alls), 1)}


def _train_sync(symbols: list[str], reaction: dict[str, set[int]], sessions_back: int = 260,
                holdout: int = 60) -> dict:
    """OLS of |09:45->15:00| (bp) on each variant's features. Scored first on the last
    `holdout` sessions with weights fitted only on the sessions before them (the honest
    number), then refitted on everything for live use. CPU-bound: run it in a thread."""
    import numpy as np
    D, F, Y = _samples(symbols, reaction, sessions_back)
    if len(Y) < 5000:
        raise RuntimeError(f"only {len(Y)} samples — the 15m history is incomplete")
    days, y, R = np.array(D), np.array(Y), np.array(F)
    del F
    cut = np.unique(days)[-holdout]
    fit, test = days < cut, days >= cut
    weights, oos = {}, {}
    for name, feats in VARIANTS:
        X = np.c_[R[:, [BASE.index(n) for n in feats]], np.ones(len(y))]
        w_is = np.linalg.lstsq(X[fit], y[fit], rcond=None)[0]
        oos[name] = _daily_scores(days[test], X[test] @ w_is, y[test])
        weights[name] = [round(float(v), 4) for v in np.linalg.lstsq(X, y, rcond=None)[0]]
    return {"weights": weights, "features": {n: list(fs) for n, fs in VARIANTS}, "samples": len(y),
            "sessions": int(len(np.unique(days))), "holdout_sessions": holdout, "oos": oos,
            "y_mean_bp": round(float(y.mean()), 1)}


async def train() -> dict:
    """Retrain on the last ~260 sessions. Weekly (Saturday), or on demand."""
    syms = await intraday_universe.symbols()
    reaction: dict[str, set[int]] = {}
    async for d in results_calendar.coll.find({"kind": "filed"}, {"symbol": 1, "reaction_day": 1}):
        try:
            noon = datetime.fromisoformat(d["reaction_day"]).replace(hour=12, tzinfo=IST)
            reaction.setdefault(d["symbol"], set()).add(day_key(int(noon.timestamp())))
        except (KeyError, TypeError, ValueError):
            continue
    t0 = time.monotonic()
    res = await asyncio.to_thread(_train_sync, syms, reaction)
    doc = {"_id": "expected_move", **res, "trained_at": datetime.now(timezone.utc),
           "train_seconds": round(time.monotonic() - t0, 1),
           "note": "OLS of the |09:45->15:00| move in bp; for RANKING stocks, not a forecast of size"}
    await models.replace_one({"_id": "expected_move"}, doc, upsert=True)
    logger.info("expected-move model: %s samples over %s sessions; held-out %s", res["samples"],
                res["sessions"], {k: v.get("rank_ic") for k, v in res["oos"].items()})
    return {k: v for k, v in doc.items() if k != "_id"}


# ── the scanners ─────────────────────────────────────────────────────────────────


def _row(f: dict, score, value: str, side: str | None, reasons: list[str], **extra) -> dict:
    return {"symbol": f["symbol"], "score": round(score, 3) if isinstance(score, float) else score,
            "value": value, "side": side, "reasons": reasons, "sector": f.get("sector"),
            "last": f.get("last"), "chg_pct": round(f["chg_pct"], 2) if f.get("chg_pct") is not None else None,
            "expected_move_bp": f.get("expected_move_bp"), "turnover_cr": f.get("turnover_cr"), **extra}


def _top(items, key, n=TOP_N, reverse=True):
    xs = [(key(f), f) for f in items]
    xs = [x for x in xs if x[0] is not None]
    xs.sort(key=lambda x: x[0], reverse=reverse)
    return [f for _k, f in xs[:n]]


def _gap(f):
    return f.get("gap_pct") if f.get("gap_pct") is not None else f.get("pre_gap_pct")


def _em_reason(f: dict) -> str:
    bits = [f"ATR {f['atr_pct']:.1f}%"]
    if f.get("rvol30"):
        bits.insert(0, f"volume {f['rvol30']:.1f}x by 09:45")
    if _gap(f) is not None:
        bits.append(f"gap {_gap(f):+.1f}%")
    if f.get("first30_pct") is not None:
        bits.append(f"first 30 min {f['first30_pct']:+.1f}%")
    if f.get("results"):
        bits.append("results today")
    return ", ".join(bits)


def run_scanners(state: dict) -> dict:
    S = state["stocks"]
    out: dict[str, list[dict]] = {}
    out["expected_move"] = [_row(f, f["expected_move_bp"], f"{f['expected_move_bp']:.0f} bp", None, [_em_reason(f)],
                                 variant=f["em_variant"])
                            for f in _top(S, lambda f: f.get("expected_move_bp"))]
    out["in_play"] = [_row(f, f["rvol"], f"{f['rvol']:.1f}x volume", None,
                           [f"{f['rvol']:.1f}x its usual volume for this time of day"])
                      for f in _top(S, lambda f: f.get("rvol") if (f.get("rvol") or 0) >= 1.3 else None)]
    out["volatility"] = [_row(f, f["atr_pct"], f"ATR {f['atr_pct']:.2f}%", None, ["14-session average true range"])
                         for f in _top(S, lambda f: f.get("atr_pct"))]
    out["gappers"] = [_row(f, abs(_gap(f)), f"gap {_gap(f):+.2f}%", None,
                           [("pre-open price" if f.get("gap_pct") is None else "open") + f" {_gap(f):+.2f}% vs yesterday",
                            "size only: the gap's direction is not a signal"])
                      for f in _top(S, lambda f: abs(_gap(f)) if _gap(f) is not None and abs(_gap(f)) >= 1.0 else None)]
    out["opening_drive"] = [_row(f, abs(f["first30_pct"]), f"first 30 min {f['first30_pct']:+.2f}%", None,
                                 ["size only: its direction failed out of sample"])
                            for f in _top(S, lambda f: abs(f["first30_pct"])
                                          if f.get("first30_pct") is not None and abs(f["first30_pct"]) >= 1.0 else None)]
    out["results_today"] = [_row(f, f.get("expected_move_bp"), "results " + f["results_info"]["kind"], None,
                                 [("filed " + f["results_info"]["at"]) if f["results_info"].get("at")
                                  else "board meeting today (time not yet known)"])
                            for f in _top(S, lambda f: (f.get("expected_move_bp") or 0.0) if f.get("results") else None, 200)]
    # candidate: the opening-range break on the highest expected-move names
    top_em = {f["symbol"] for f in _top(S, lambda f: f.get("expected_move_bp") if f.get("em_variant") == "0945" else None, 20)}
    br = []
    for f in S:
        b = f.get("or_break")
        if f["symbol"] not in top_em or not b:
            continue
        t = datetime.fromtimestamp(b["at"], IST).strftime("%H:%M")
        if b.get("side"):
            br.append(_row(f, f.get("expected_move_bp"), f"broke {'up' if b['side'] == 'LONG' else 'down'} at {t}",
                           b["side"], [f"first break of the opening range {f['or_low']:.2f}-{f['or_high']:.2f} "
                                       f"in the {t} bar", "candidate: about break-even after costs, under test"],
                           or_high=f["or_high"], or_low=f["or_low"]))
        else:
            br.append(_row(f, f.get("expected_move_bp"), f"both sides at {t}", None,
                           ["both edges of the opening range broke in one bar: no side"],
                           or_high=f["or_high"], or_low=f["or_low"]))
    waiting = [_row(f, f.get("expected_move_bp"), "inside the range", None,
                    [f"watch {f['or_low']:.2f} / {f['or_high']:.2f}"], or_high=f["or_high"], or_low=f["or_low"])
               for f in S if f["symbol"] in top_em and f.get("or_high") is not None and not f.get("or_break")]
    out["or_break"] = sorted(br, key=lambda r: -(r["score"] or 0)) + sorted(waiting, key=lambda r: -(r["score"] or 0))
    # context lists — direction ideas that failed: shown, never a trigger
    out["day_change"] = ([_row(f, f["chg_pct"], f"{f['chg_pct']:+.2f}%", None, ["gainer — context only"])
                          for f in _top(S, lambda f: f.get("chg_pct"), 15)]
                         + [_row(f, f["chg_pct"], f"{f['chg_pct']:+.2f}%", None, ["loser — context only"])
                            for f in _top(S, lambda f: f.get("chg_pct"), 15, reverse=False)])

    def rs_why(f):
        return (f"vs {f['sector_index']} {f['rs_sector']:+.2f}%" if f.get("rs_sector") is not None
                else "no sector index") + " — context only"
    out["relative_strength"] = ([_row(f, f["rs_nifty"], f"{f['rs_nifty']:+.2f}% vs NIFTY", None, [rs_why(f)])
                                 for f in _top(S, lambda f: f.get("rs_nifty"), 15)]
                                + [_row(f, f["rs_nifty"], f"{f['rs_nifty']:+.2f}% vs NIFTY", None, [rs_why(f)])
                                   for f in _top(S, lambda f: f.get("rs_nifty"), 15, reverse=False)])
    out["oi_buildup"] = [_row(f, abs(f["oi_chg_pct"]), f"{f['buildup']}: OI {f['oi_chg_pct']:+.1f}%", None,
                              [f"futures {f['fut_chg_pct']:+.2f}% yesterday — context only"])
                         for f in _top(S, lambda f: abs(f["oi_chg_pct"]) if f.get("oi_chg_pct") is not None else None)]
    out["delivery"] = [_row(f, f["deliv_rel"], f"delivery {f['deliv_pct']:.0f}% ({f['deliv_rel']:.1f}x usual)", None,
                            [f"yesterday {f['prev_ret_pct']:+.2f}% — context only" if f.get("prev_ret_pct") is not None
                             else "context only"])
                       for f in _top(S, lambda f: f.get("deliv_rel") if (f.get("deliv_rel") or 0) >= 1.5 else None)]
    near = []
    for f in S:
        px = f.get("last") or f["prev_close"]
        if px >= 0.99 * f["hi20"]:
            near.append(_row(f, px / f["hi20"], "at the 20-day high", None, ["context only"]))
        elif px <= 1.01 * f["lo20"]:
            near.append(_row(f, f["lo20"] / px, "at the 20-day low", None, ["context only"]))
    out["near_extremes"] = sorted(near, key=lambda r: -r["score"])
    out["preopen"] = [_row(f, abs(f["pre_gap_pct"]),
                           f"pre-open {f['pre_gap_pct']:+.2f}%" + (f", book {f['pre_imbalance']:+.2f}"
                                                                  if f.get("pre_imbalance") is not None else ""),
                           None, ["buy/sell imbalance of the pre-open book — recorded for a forward test"])
                      for f in _top(S, lambda f: abs(f["pre_gap_pct"]) if f.get("pre_gap_pct") is not None else None)]
    return {name: {**EVIDENCE[name], "count": len(rows), "rows": rows[:TOP_N]} for name, rows in out.items()}


# ── board, snapshots, accuracy ───────────────────────────────────────────────────

_cache: dict = {"at": 0.0, "board": None}


async def board(now: datetime | None = None, use_cache: bool = True) -> dict:
    if use_cache and now is None and _cache["board"] and time.monotonic() - _cache["at"] < 60:
        return _cache["board"]
    state = await build_state(now)
    out = {k: state[k] for k in ("at", "hhmm", "date", "session", "nifty_chg_pct", "sector_chg_pct", "universe",
                                 "archives_from", "preopen", "results_today", "model")}
    out["stocks"] = len(state["stocks"])
    out["scanners"] = run_scanners(state)
    out["expected_move_all"] = {f["symbol"]: f["expected_move_bp"] for f in state["stocks"]
                                if f.get("expected_move_bp") is not None}
    out["or_levels"] = {f["symbol"]: [round(f["or_low"], 2), round(f["or_high"], 2)] for f in state["stocks"]
                        if f.get("or_high") is not None}
    if now is None:
        _cache.update({"at": time.monotonic(), "board": out})
    return out


def snap_path(day: str, label: str) -> str:
    return os.path.join(SNAP_DIR, day, f"{label.replace(':', '')}.json")


async def snapshot(label: str, now: datetime | None = None) -> dict:
    """Compute the board as of now and freeze it to disk under `label` (e.g. "09:45")."""
    b = await board(now, use_cache=False)
    b["label"] = label
    p = snap_path(b["date"], label)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(b, fh, separators=(",", ":"), default=str)
    os.replace(tmp, p)
    return {"saved": p, "stocks": b["stocks"], "lists": {k: v["count"] for k, v in b["scanners"].items()}}


def snapshots(day: str) -> list[str]:
    d = os.path.join(SNAP_DIR, day)
    if not os.path.isdir(d):
        return []
    return sorted(f[:2] + ":" + f[2:4] for f in os.listdir(d) if f.endswith(".json"))


def snapshot_days(n: int = 30) -> list[str]:
    if not os.path.isdir(SNAP_DIR):
        return []
    return sorted((d for d in os.listdir(SNAP_DIR) if len(d) == 10), reverse=True)[:n]


def load_snapshot(day: str, label: str) -> dict | None:
    try:
        with open(snap_path(day, label)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _actual_moves(day: date, symbols: list[str]) -> dict[str, float]:
    """|09:45 -> 15:00| in bp for each symbol that has both bars on `day`."""
    k = day_key(int(datetime(day.year, day.month, day.day, 12, tzinfo=IST).timestamp()))
    out = {}
    for sym in symbols:
        b = store.get(sym)
        lo = bisect_left(b.t, k * 86400 - 19800)
        hi = bisect_left(b.t, (k + 1) * 86400 - 19800)
        by = {_minute(b.t[i]): i for i in range(lo, hi)}
        if 570 in by and 900 in by:
            out[sym] = abs(b.o[by[900]] / b.c[by[570]] - 1) * 1e4
    return out


async def score_day(day: date) -> dict | None:
    """After the close: how well the 09:45 expected-move ranking ordered the day's actual
    09:45->15:00 moves — rank correlation over every stock, and the top 20 against the
    rest. Stored per day, so the live accuracy of the model is always visible."""
    snap = load_snapshot(day.isoformat(), "09:45")
    if not snap or not snap.get("expected_move_all"):
        return None
    pred = snap["expected_move_all"]
    actual = _actual_moves(day, list(pred))
    common = [s for s in pred if s in actual]
    if len(common) < 50:
        return None
    import numpy as np
    p = np.array([pred[s] for s in common])
    a = np.array([actual[s] for s in common])
    order = np.argsort(-p)
    doc = {"_id": day.isoformat(), "n": len(common),
           "rank_ic": round(float(np.corrcoef(np.argsort(np.argsort(p)), np.argsort(np.argsort(a)))[0, 1]), 3),
           "top20_move_bp": round(float(a[order[:20]].mean()), 1),
           "all_move_bp": round(float(a.mean()), 1),
           "bottom50_move_bp": round(float(a[order[-50:]].mean()), 1),
           "at": datetime.now(timezone.utc)}
    doc["lift_top20"] = round(doc["top20_move_bp"] / doc["all_move_bp"], 2) if doc["all_move_bp"] else None
    await accuracy.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return doc


async def accuracy_history(n: int = 60) -> dict:
    rows = []
    async for d in accuracy.find({}).sort("_id", -1).limit(n):
        d["date"] = d.pop("_id")
        d.pop("at", None)
        rows.append(d)
    ics = [r["rank_ic"] for r in rows if r.get("rank_ic") is not None]
    lifts = [r["lift_top20"] for r in rows if r.get("lift_top20")]
    return {"days": rows, "mean_rank_ic": round(sum(ics) / len(ics), 3) if ics else None,
            "mean_lift_top20": round(sum(lifts) / len(lifts), 2) if lifts else None}
