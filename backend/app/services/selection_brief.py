"""The pre-market brief and the evidence registry — what the morning can know, and what
each piece of it is good for.

The research (2026-10-02, 515 sessions) splits the morning's information in two:

  It tells you what the OPEN will look like and HOW MUCH stocks will move:
    - the previous US session sets NIFTY's opening gap. S&P 500 alone: corr 0.47 over 515
      sessions, the same in both halves (0.52 / 0.47); fitted on the first two-thirds and
      scored on the last third it called the gap's direction on 70% of days, 87% when it
      called 30 bp or more. Adding the dollar, crude, yields, USD/INR or Asia made the
      held-out forecast WORSE, so it is the S&P 500 alone.
    - India VIX, results days, gaps and early volume set the size of the day's moves
      (the expected-move model on the Scanner Board).

  It does NOT tell you which way stocks go after the open. Global cues vs NIFTY 09:45->close:
  corr -0.04. Breadth, FII positioning, NIFTY's own first half hour: nothing out of sample.
  So the brief carries no long/short call of its own. The only side it shows is the
  CANDIDATE opening-range break, where price — not a forecast — picks the side.

The gap forecast is written to market_brief before the open (09:06) and scored against
NIFTY's actual open after the close, so its record is visible rather than asserted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone

from app.services import (global_cues, intraday_universe, market_calendar, nse_archives,
                          results_calendar, scanner_board)
from app.services.intraday_store import day_key, read_file, store

logger = logging.getLogger("selection_brief")

IST = timezone(timedelta(hours=5, minutes=30))
brief_coll = global_cues.brief_coll
GAP_SERIES = "SPX"

MARKET_EVIDENCE = {
    "us_session": {"status": "proven", "predicts": "NIFTY's opening gap", "title": "Previous US session (S&P 500)",
                   "evidence": "corr 0.47 with NIFTY's gap over 515 sessions; held out, the forecast had the gap's "
                               "direction right on 70% of days and 87% when it called 30 bp or more. No bearing on "
                               "NIFTY after 09:45 (corr -0.04)."},
    "other_global": {"status": "context", "predicts": "nothing beyond the S&P 500",
                     "title": "Dollar, crude, US yields, USD/INR, Asia",
                     "evidence": "added to the S&P 500 each made the held-out gap forecast worse (corr 0.47 -> "
                                 "0.39-0.45); Asia's previous session is already in India's previous close"},
    "india_vix": {"status": "proven", "predicts": "how far stocks move", "title": "India VIX",
                  "evidence": "universe 09:45->15:00 move 92 bp in the calmest VIX bucket vs 140 bp in the most "
                              "fearful; direction: nothing"},
    "nifty_first30": {"status": "context", "predicts": "nothing", "title": "NIFTY's first 30 minutes",
                      "evidence": "does not predict NIFTY's rest of day (corr -0.07, not significant); tying stock "
                                  "trades to it changed nothing in two years of backtests"},
    "breadth": {"status": "context", "predicts": "nothing", "title": "Yesterday's breadth",
                "evidence": "rules on advance/decline breadth flipped sign out of sample"},
    "fii_positioning": {"status": "context", "predicts": "nothing", "title": "FII / client index-futures positions",
                        "evidence": "positioning and its change did not predict the next session out of sample"},
    "drift": {"status": "context", "predicts": "a structural headwind", "title": "Overnight vs intraday drift",
              "evidence": "the universe earned +13.1 bp a night (t 4.1) and lost 7.5 bp a session, 4.7 bp of it "
                          "before 09:45: an intraday long starts against the tide"},
    "nr7": {"status": "context", "predicts": "nothing", "title": "NR7 / inside days",
            "evidence": "the 'narrow day breaks out' rule worked backwards in this universe"},
}


def evidence() -> dict:
    """Every input the selection work considered, with its verdict and the numbers."""
    return {"market": MARKET_EVIDENCE, "stock_lists": scanner_board.EVIDENCE,
            "statuses": {"proven": "held out of sample; use it for what it predicts (never for direction "
                                   "unless it says direction)",
                         "candidate": "positive in both periods but about break-even after costs; under test",
                         "context": "a direction idea that failed out of sample; shown, never a trigger",
                         "forward": "no history exists; being recorded so it can be tested"}}


# ── the expected NIFTY gap ───────────────────────────────────────────────────────


def _nifty_sessions() -> list[tuple[date, float, float]]:
    """(day, open, close) of every complete NIFTY session in the 15m store."""
    b = read_file("NIFTY")
    days: dict[int, list[int]] = {}
    for i in range(len(b)):
        days.setdefault(day_key(b.t[i]), []).append(i)
    out = []
    for k in sorted(days):
        ix = days[k]
        if ((b.t[ix[0]] + 19800) % 86400) // 60 != 555 or len(ix) < 20:
            continue
        out.append((date(1970, 1, 1) + timedelta(days=k), b.o[ix[0]], b.c[ix[-1]]))
    return out


def _close_before(rows, day_iso: str) -> float | None:
    last = None
    for d, c in rows:
        if d < day_iso:
            last = c
        else:
            break
    return last


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** 0.5
    sb = sum((y - mb) ** 2 for y in b) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else None


def _ols1(x: list[float], y: list[float]) -> tuple[float, float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx if sxx else 0.0
    return slope, my - slope * mx


def _fit_gap_sync() -> dict | None:
    """NIFTY gap (bp) on the US move since NIFTY's previous close: the last US close
    dated before today over the last one dated before NIFTY's previous session (so a
    Monday sees Friday's US session, and the day after an NSE holiday sees both US
    sessions it missed)."""
    us = sorted(global_cues.history(GAP_SERIES))
    sess = _nifty_sessions()
    X, Y, D = [], [], []
    for (pd_, _po, pc), (d, o, _c) in zip(sess[:-1], sess[1:]):
        a, z = _close_before(us, pd_.isoformat()), _close_before(us, d.isoformat())
        if a and z:
            X.append((z / a - 1) * 1e4)
            Y.append((o / pc - 1) * 1e4)
            D.append(d)
    if len(Y) < 150:
        return None
    cut = len(Y) * 2 // 3
    s, i = _ols1(X[:cut], Y[:cut])
    pred = [s * x + i for x in X[cut:]]
    act = Y[cut:]
    mean_fit = sum(Y[:cut]) / cut
    big = [(p, y) for p, y in zip(pred, act) if abs(p) >= 30]
    oos = {"sessions": len(act), "from": D[cut].isoformat(), "corr": round(_corr(pred, act) or 0, 3),
           "mae_bp": round(sum(abs(p - y) for p, y in zip(pred, act)) / len(act), 1),
           "naive_mae_bp": round(sum(abs(mean_fit - y) for y in act) / len(act), 1),
           "direction_hit": round(sum(1 for p, y in zip(pred, act) if (p > 0) == (y > 0)) / len(act), 3),
           "big_calls": len(big),
           "big_direction_hit": round(sum(1 for p, y in big if (p > 0) == (y > 0)) / len(big), 3) if big else None}
    slope, icpt = _ols1(X, Y)
    return {"series": GAP_SERIES, "slope": round(slope, 4), "intercept_bp": round(icpt, 2), "sessions": len(Y),
            "through": D[-1].isoformat(), "corr_all": round(_corr(X, Y) or 0, 3), "held_out": oos,
            "abs_gap_mean_bp": round(sum(abs(y) for y in Y) / len(Y), 1)}


_gap_cache: dict = {"day": None, "model": None}


async def gap_model() -> dict | None:
    today = datetime.now(IST).date().isoformat()
    if _gap_cache["day"] != today:
        _gap_cache.update({"day": today, "model": await asyncio.to_thread(_fit_gap_sync)})
    return _gap_cache["model"]


async def forecast_gap(day: date, snap: dict | None) -> dict | None:
    """The expected NIFTY opening gap for `day` from that morning's global snapshot."""
    model = await gap_model()
    if not model or not snap:
        return None
    s = (snap.get("series") or {}).get(GAP_SERIES) or {}
    rows = [tuple(r) for r in s.get("recent") or []]
    prev = market_calendar.previous_trading_day(day)
    a, z = _close_before(rows, prev.isoformat()), _close_before(rows, day.isoformat())
    if a and z:
        us_bp = (z / a - 1) * 1e4
        basis = f"S&P 500 closes after NIFTY's {prev:%d %b} close"
    elif (s.get("session") or {}).get("ret_pct") is not None:
        us_bp = s["session"]["ret_pct"] * 100
        basis = "S&P 500's last session"
    else:
        return None
    pred = model["slope"] * us_bp + model["intercept_bp"]
    return {"us_move_bp": round(us_bp, 1), "pred_bp": round(pred, 1), "basis": basis,
            "call": ("gap up" if pred >= 15 else "gap down" if pred <= -15 else "flat open"),
            "confidence": ("high" if abs(pred) >= 30 else "moderate" if abs(pred) >= 15 else "low"),
            "typical_abs_gap_bp": model["abs_gap_mean_bp"], "model": {k: model[k] for k in ("slope", "intercept_bp", "held_out")}}


async def record_gap_forecast(day: date | None = None) -> dict | None:
    """Before the open: freeze the forecast so the close can score it."""
    day = day or datetime.now(IST).date()
    doc = await global_cues.latest_brief(day)
    fc = await forecast_gap(day, (doc or {}).get("global"))
    if fc:
        fc["made_at"] = datetime.now(IST).isoformat()
        await brief_coll.update_one({"_id": day.isoformat()}, {"$set": {"gap_forecast": fc}}, upsert=True)
    return fc


async def score_gap(day: date) -> dict | None:
    """After the close: NIFTY's actual gap against the morning's forecast."""
    sess = {d: (o, c) for d, o, c in await asyncio.to_thread(_nifty_sessions)}
    prev = market_calendar.previous_trading_day(day)
    if day not in sess or prev not in sess:
        return None
    actual = (sess[day][0] / sess[prev][1] - 1) * 1e4
    await brief_coll.update_one({"_id": day.isoformat()}, {"$set": {"gap_actual_bp": round(actual, 1)}}, upsert=True)
    return {"date": day.isoformat(), "gap_actual_bp": round(actual, 1)}


async def gap_record(n: int = 30) -> dict:
    rows = []
    async for d in brief_coll.find({"gap_forecast": {"$exists": True}},
                                   {"gap_forecast.pred_bp": 1, "gap_forecast.call": 1, "gap_actual_bp": 1}
                                   ).sort("_id", -1).limit(n):
        rows.append({"date": d["_id"], "pred_bp": d["gap_forecast"].get("pred_bp"),
                     "call": d["gap_forecast"].get("call"), "actual_bp": d.get("gap_actual_bp")})
    scored = [r for r in rows if r["actual_bp"] is not None and r["pred_bp"] is not None]
    return {"days": rows, "scored": len(scored),
            "direction_hit": round(sum(1 for r in scored if (r["pred_bp"] > 0) == (r["actual_bp"] > 0)) / len(scored), 3)
            if scored else None,
            "mae_bp": round(sum(abs(r["pred_bp"] - r["actual_bp"]) for r in scored) / len(scored), 1) if scored else None}


# ── VIX, breadth, positioning ────────────────────────────────────────────────────


def _vix_sync(day: date) -> dict | None:
    b = read_file("INDIAVIX")
    closes: dict[int, float] = {}
    for i in range(len(b)):
        closes[day_key(b.t[i])] = b.c[i]
    k_today = (day - date(1970, 1, 1)).days
    hist = [closes[k] for k in sorted(closes) if k < k_today][-250:]
    if len(hist) < 60:
        return None
    return {"prev_close": hist[-1], "history": hist}


async def vix_regime(day: date, now: datetime) -> dict | None:
    v = await asyncio.to_thread(_vix_sync, day)
    if not v:
        return None
    level, live = v["prev_close"], False
    rows, _prev = scanner_board._sessions("INDIAVIX", int(now.timestamp()), 0)
    if rows:
        level, live = rows[-1][4], True
    hist = v["history"]
    pct = sum(1 for x in hist if x <= level) / len(hist)
    regime = "high" if pct >= 2 / 3 else "low" if pct <= 1 / 3 else "normal"
    return {"level": round(level, 2), "prev_close": round(v["prev_close"], 2), "live": live,
            "percentile_1y": round(pct, 3), "regime": regime,
            "means": {"high": "bigger moves than usual: wider stops, smaller size",
                      "normal": "ordinary day sizes", "low": "smaller moves: fewer setups clear costs"}[regime]}


def breadth_prev(day: date, universe: set[str]) -> dict | None:
    hist = nse_archives.recent("cm", day, 1)
    if not hist:
        return None
    d, doc = hist[-1]
    x = doc["x"]

    def ad(keys):
        a = sum(1 for k in keys if x[k][0] and x[k][1] and x[k][0] > x[k][1])
        dn = sum(1 for k in keys if x[k][0] and x[k][1] and x[k][0] < x[k][1])
        return {"advances": a, "declines": dn, "ratio": round(a / dn, 2) if dn else None}
    return {"session": d.isoformat(), "market": ad(list(x)), "universe": ad([k for k in x if k in universe])}


def positioning(day: date) -> dict | None:
    hist = nse_archives.recent("part", day, 2)
    if not hist:
        return None
    out = {"session": hist[-1][0].isoformat()}
    for who in ("FII", "Client", "Pro", "DII"):
        cur = hist[-1][1]["x"].get(who) or {}
        L, S = cur.get("Future Index Long"), cur.get("Future Index Short")
        if L is None or S is None:
            continue
        row = {"index_fut_long": L, "index_fut_short": S, "long_share": round(L / (L + S), 3) if L + S else None,
               "net": L - S}
        if len(hist) > 1:
            p = hist[0][1]["x"].get(who) or {}
            if p.get("Future Index Long") is not None:
                row["net_change"] = (L - S) - (p["Future Index Long"] - p["Future Index Short"])
        out[who] = row
    return out


def _global_view(snap: dict | None) -> list[dict]:
    if not snap:
        return []
    out = []
    for key, s in (snap.get("series") or {}).items():
        if not s.get("available"):
            continue
        out.append({"key": key, "label": s["label"], "group": s["group"],
                    "session_ret_pct": (s.get("session") or {}).get("ret_pct"),
                    "session_date": (s.get("session") or {}).get("date"),
                    "live_chg_pct": (s.get("live") or {}).get("chg_pct") if s.get("read") == "live" else None,
                    "used_for": "NIFTY gap forecast" if key == GAP_SERIES else "context"})
    return out


# ── the brief ────────────────────────────────────────────────────────────────────

_cache: dict = {"at": 0.0, "brief": None}
_live: dict = {"at": 0.0, "snap": None}
LIVE_GLOBAL_TTL_S = 900


async def _live_global() -> dict | None:
    """Before the session's own 08:40 snapshot exists (evenings, weekends, holidays): a live
    read, NOT stored — the stored ones are the record the gap forecast is scored on."""
    if _live["snap"] is None or time.monotonic() - _live["at"] > LIVE_GLOBAL_TTL_S:
        _live.update({"at": time.monotonic(), "snap": await global_cues.snapshot(save=False)})
    return _live["snap"]


async def brief(use_cache: bool = True) -> dict:
    if use_cache and _cache["brief"] and time.monotonic() - _cache["at"] < 60:
        return _cache["brief"]
    now = datetime.now(IST)
    today = now.date()
    trading = market_calendar.is_trading_day(today)
    target = today if trading else market_calendar.next_trading_day(today)
    doc = await global_cues.latest_brief(target)
    if doc and doc.get("global"):
        doc_g, snap_from = doc["global"], f"stored {doc['global'].get('at', '')[:16]}"
    else:
        doc_g = await _live_global()
        snap_from = f"live {doc_g.get('at', '')[:16]} (not stored)" if doc_g else None
    universe = set(await intraday_universe.symbols())
    gap = (doc or {}).get("gap_forecast") or await forecast_gap(target, doc_g)
    if gap and not (doc or {}).get("gap_forecast"):
        gap = {**gap, "provisional": True,
               "note": "from the US closes known now; the forecast of record is frozen at 09:05 on the day"}
    board = await scanner_board.board()
    model = board.get("model") or {}
    em = list(board.get("expected_move_all", {}).values())
    expected_day = None
    if em and model.get("y_mean_bp"):
        mean_em = sum(em) / len(em)
        expected_day = {"universe_expected_move_bp": round(mean_em, 1), "typical_bp": model["y_mean_bp"],
                        "ratio": round(mean_em / model["y_mean_bp"], 2),
                        "as_of": board["hhmm"], "note": "09:45->15:00 move the model expects for the average stock"}
    react = await results_calendar.reacting_on(target)
    upcoming = await results_calendar.upcoming(7)
    sides = [r for r in board["scanners"]["or_break"]["rows"] if r.get("side")]
    out = {
        "at": now.isoformat(), "date": today.isoformat(), "session": target.isoformat(),
        "trading_today": trading, "closed_reason": None if trading else market_calendar.holiday_name(today) or "weekend",
        "global": {"snapshot_of": snap_from, "series": _global_view(doc_g)},
        "gap_forecast": gap,
        "vix": await vix_regime(target, now),
        "breadth_prev": await asyncio.to_thread(breadth_prev, target, universe),
        "positioning": await asyncio.to_thread(positioning, target),
        "results": {"today": [{"symbol": s, **v} for s, v in sorted(react.items())],
                    "in_universe_today": sorted(s for s in react if s in universe),
                    "next_7_days": len(upcoming)},
        "preopen": (doc or {}).get("preopen"),
        "expected_day": expected_day,
        "stock_bias": {"status": "candidate",
                       "rule": "No proven input says which way a stock goes. The only side shown is the first break "
                               "of the 09:15-09:45 range on the top-20 expected-move names — price picks it, and it "
                               "is about break-even after costs, under test.",
                       "rows": sides},
        "gap_record": await gap_record(20),
        "evidence": evidence(),
    }
    _cache.update({"at": time.monotonic(), "brief": out})
    return out
