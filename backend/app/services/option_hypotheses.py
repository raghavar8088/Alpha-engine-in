"""Pre-registered NIFTY option hypotheses — frozen rules, frozen expectations, forward verdicts.

WHY PRE-REGISTER (the 2026-10-02 Pre-Live audit)
The buying tournament ran 167 strategies and let the leaderboard pick. Nothing in it predicts
NIFTY's direction (two-year replay: 47.8-48.4% hit; 0 of 148 strategies significant), so the
leaderboard ranked luck — and its top rows were sign flips of the worst records, never traded.
Anything that may ever trade real money now enters this way instead: its rule and the numbers
that would confirm or fail it are written down BEFORE the forward data exists, and nothing
here may be edited once forward trades exist. A verdict is read off the forward REAL-MONEY
P&L (fills at the order book's ask/bid, Angel One rate card), never the paper LTP fill.

THE HYPOTHESES (2026-10-02)
  H1   volatility-timed intraday straddle: on days a 09:45 model predicts a high realized/
       implied variance ratio (top 40%), buy the ATM straddle of NEXT week's expiry at 09:45,
       sell 15:15. Research prior, under the premium model calibrated on 5,800 real trades:
       NEGATIVE (-Rs636 a day before 2026, -Rs774 after) — an option loses most of its daily
       value during trading hours, and NIFTY's intraday realized variance is about a third of
       what VIX implies. Registered as the user specified; the forward record decides.
  H1b  the same signal, the straddle held OVERNIGHT instead (15:15 -> 09:30 next session).
       Added by the research: the calibration says the market charges only ~0.2 of a session
       of decay per night, while NIFTY's overnight moves are large. Prior +Rs299 / +Rs958 a
       night, t 1.0 / 1.6 — model extrapolation, since no real trade in the data held overnight.
  H2   buying near expiry (0-1 day) loses more per trade than buying 2+ days out. Tested on
       the tournament's forward trades. Honest prior: NOT supported so far — with the true
       expiries, live trades lost Rs102 (expiry day), made Rs52 (1 day), lost Rs157 (2-6 days).
  H3   buying volatility around scheduled events (RBI, US CPI, FOMC). Researched on history
       first, as the plan said, and REJECTED there: event nights moved no more than others, and
       RBI days lost more (the volatility is crushed once the policy is out). Recorded, not run.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from app.core.db import db

hypotheses = db["option_hypotheses"]
vol_trades = db["vol_desk_trades"]
prelive_trades = db["prelive_trades"]

REGISTERED_AT = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)    # forward data counts from here

FROZEN_SIGNAL = {
    "features": ["log VIX (09:45; fraction, e.g. 0.14)", "VIX change vs the previous session's last bar",
                 "|gap| % (09:15 open vs previous close)", "first-30-minute range % (09:15-09:45, over the open)",
                 "log(previous session RV / IV window)", "log(mean RV of the last 5 sessions / IV window)",
                 "expiry day of the current weekly (1/0)", "constant"],
    "weights": [-0.454764, 1.767328, -0.266526, 1.181477, 0.166004, 0.178961, -0.146338, -2.227025],
    "threshold": -1.105874,
    "rv": "sum of squared 5-minute log returns within the session",
    "iv_window": "VIX^2 x 330/375 / 252, VIX at 09:45",
    "fit": "OLS of log(realized/implied variance 09:45-15:15) on 2024-10-04..2025-12-31; threshold = "
           "60th percentile of those predictions (top 40% of days traded); held-out corr 0.37",
}

PREREGISTERED = {
    "H1": {
        "name": "Volatility-timed intraday straddle",
        "rule": "On flagged days buy 1 lot each of the ATM CE and PE of next week's NIFTY expiry at 09:45 "
                "(at the ask), sell both at 15:15 (at the bid).",
        "signal": FROZEN_SIGNAL, "test_value": "real_pnl per trade (one straddle = one trade)",
        "expected": {"per_trade_net_mean": -636.27, "per_trade_net_sd": 2252.91,
                     "explore": {"n": 121, "mean": -636.27}, "confirm": {"n": 60, "mean": -773.51},
                     "source": "model calibrated on 5,800 real premiums (clock: trading minutes + 0.2 session "
                               "a night; IV = VIX x 0.888); spread 0.5 pt a leg a side; Angel rate card"},
        "thresholds": {"min_trades": 30, "confirm_t": 2.0, "fail_t": -2.0, "fail_if_negative_after": 60,
                       "fail_t_if_negative": -1.0},
        "origin": "user plan U5",
    },
    "H1b": {
        "name": "Volatility-timed overnight straddle",
        "rule": "On flagged days buy 1 lot each of the ATM CE and PE of next week's NIFTY expiry at 15:15 "
                "(at the ask), sell both at 09:30 the next session (at the bid).",
        "signal": FROZEN_SIGNAL, "test_value": "real_pnl per trade",
        "expected": {"per_trade_net_mean": 299.42, "per_trade_net_sd": 3171.89,
                     "explore": {"n": 121, "mean": 299.42}, "confirm": {"n": 60, "mean": 957.82},
                     "source": "same model, overnight extrapolation (no real overnight hold in the calibration data)"},
        "thresholds": {"min_trades": 30, "confirm_t": 2.0, "fail_t": -2.0, "fail_if_negative_after": 60,
                       "fail_t_if_negative": -1.0},
        "origin": "added by the 2026-10-02 research",
    },
    "H2": {
        "name": "Near-expiry buying is worse",
        "rule": "Among the tournament's forward option buys, trades 0-1 days to expiry earn less per trade "
                "(real-money) than trades 2+ days to expiry.",
        "test_value": "difference of mean real_pnl per trade, Welch t",
        "expected": {"prior_live_true_expiry": {"dte_0": -102, "dte_1": 52, "dte_2_6": -157},
                     "prior_replay_model": {"dte_0": -214, "dte_1": -92, "dte_2_plus": 100},
                     "note": "live prior does not support H2; the model replay does"},
        "thresholds": {"min_trades_each": 300, "confirm_t": -2.0, "fail_t": 2.0},
        "origin": "user plan U5",
    },
    "H3": {
        "name": "Buy volatility around scheduled events",
        "rule": "US CPI / FOMC nights: ATM straddle (next week's expiry) 15:15 -> 09:30; RBI decision days: "
                "09:20 -> 11:00 and 09:20 -> 15:15. Each against the same trade on all other days.",
        "status": "REJECTED_ON_HISTORY",
        "expected": {
            "us_events_overnight": {"events": 39, "event_mean": 508, "other_mean": 234, "difference_t": 0.67,
                                    "note": "NIFTY's overnight move on event nights (22 bp) was SMALLER than on others (27 bp)"},
            "rbi_0920_1100": {"events": 12, "event_mean": -1326, "other_mean": -199, "difference_t": -1.23},
            "rbi_0920_1515": {"events": 12, "event_mean": -1871, "other_mean": -634, "difference_t": -1.24,
                              "note": "implied volatility is crushed once the policy is out"},
            "source": "2024-10..2026-10, calibrated premium model; dates from rbi.org.in, federalreserve.gov, bls.gov"},
        "thresholds": {},
        "origin": "user plan U5 — researched on history first, as specified; not taken forward",
    },
}


async def preregister() -> dict:
    """Insert each hypothesis once. Never overwrites."""
    added = []
    for hid, h in PREREGISTERED.items():
        if await hypotheses.find_one({"_id": hid}, {"_id": 1}):
            continue
        await hypotheses.insert_one({"_id": hid, **h, "status": h.get("status", "INCUBATING"),
                                     "registered_at": REGISTERED_AT, "forward": {}, "history": []})
        added.append(hid)
    return {"registered": added}


async def confirmed_ids() -> set[str]:
    """Strategy/hypothesis ids allowed to trade beyond paper incubation (none yet)."""
    return {d["_id"] async for d in hypotheses.find({"status": "CONFIRMED"}, {"_id": 1})}


def _t(xs: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


def _verdict_single(nets: list[float], th: dict) -> tuple[str, dict]:
    n = len(nets)
    fwd = {"trades": n, "net": round(sum(nets), 2)}
    if n >= 3:
        fwd.update({"mean": round(statistics.mean(nets), 2), "sd": round(statistics.stdev(nets), 2), "t": _t(nets)})
    status = "INCUBATING"
    t = fwd.get("t")
    if n >= th["min_trades"] and t is not None:
        if t >= th["confirm_t"] and fwd["mean"] > 0:
            status = "CONFIRMED"
        elif t <= th["fail_t"] or (n >= th["fail_if_negative_after"] and fwd["mean"] < 0 and t <= th["fail_t_if_negative"]):
            status = "FAILED"
    if fwd.get("t") is not None:
        fwd["t"] = round(fwd["t"], 3)
    return status, fwd


async def evaluate() -> dict:
    """Test every incubating hypothesis on its forward data. Run after each close."""
    changed = []
    now = datetime.now(timezone.utc)
    async for h in hypotheses.find({"status": "INCUBATING"}):
        hid, th = h["_id"], h["thresholds"]
        if hid in ("H1", "H1b"):
            nets = [float(t["real_pnl"]) async for t in vol_trades.find(
                {"hypothesis": hid, "closed_at": {"$gte": h["registered_at"]}}, {"real_pnl": 1})]
            status, fwd = _verdict_single(nets, th)
        elif hid == "H2":
            a, b = [], []
            async for t in prelive_trades.find({"exit_ts": {"$gte": h["registered_at"]}, "dte": {"$ne": None}},
                                               {"dte": 1, "real_pnl": 1, "pnl": 1}):
                v = float(t.get("real_pnl", t.get("pnl") or 0.0))
                (a if t["dte"] <= 1 else b).append(v)
            fwd = {"near_expiry": {"n": len(a), "mean": round(statistics.mean(a), 2) if a else None},
                   "further_out": {"n": len(b), "mean": round(statistics.mean(b), 2) if b else None}}
            status = "INCUBATING"
            if len(a) >= 2 and len(b) >= 2:
                se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
                t = (statistics.mean(a) - statistics.mean(b)) / se if se else None
                fwd["welch_t"] = round(t, 3) if t is not None else None
                if t is not None and len(a) >= th["min_trades_each"] and len(b) >= th["min_trades_each"]:
                    status = "CONFIRMED" if t <= th["confirm_t"] else "FAILED" if t >= th["fail_t"] else "INCUBATING"
        else:
            continue
        fwd["evaluated_at"] = now
        update = {"forward": fwd, "status": status}
        if status != "INCUBATING":
            update["decided_at"] = now
            changed.append((hid, status))
        await hypotheses.update_one({"_id": hid}, {"$set": update, "$push": {"history": {
            "$each": [{"at": now, "status": status, "summary": {k: v for k, v in fwd.items() if k != "evaluated_at"}}],
            "$slice": -200}}})
    return {"decided": changed}


async def listing() -> list[dict]:
    out = []
    async for h in hypotheses.find({}).sort("_id", 1):
        h["id"] = h.pop("_id")
        h.pop("history", None)
        out.append(h)
    return out
