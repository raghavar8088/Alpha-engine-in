"""Incubation: a backtest pass is a hypothesis; the forward paper record tests it.

PRE-REGISTERED. When a strategy clears the backtest gate it is registered with what the
backtest says it should do — per-trade net mean and spread, trades per session, win rate —
and with the thresholds that will judge it, all frozen at registration. The forward
record (the tournament's own paper trades since that moment, real costs and slippage
included) is then tested against those numbers. Nothing about the test can be changed
after the forward results start arriving, which is the whole difference between
incubation and "looking at it until it looks good".

THE EXPECTATION IS DELIBERATELY THE CONSERVATIVE ONE: the lower of the selection-window
and holdout per-trade means. The selection window is biased upward by the act of
selecting (the winner's curse); the holdout is not, but is short.

VERDICTS (once at least `min_trades` forward trades exist)
  CONFIRMED  forward t-stat >= 2 AND the forward mean is not significantly below
             the expectation (z >= -1). Eligible for Live Trading — which still needs the
             user to arm it; nothing here places a real order.
  FAILED     the forward mean is significantly below the expectation (z <= -2), or it is
             negative with t <= -1. An early stop applies from 20 trades if z <= -3.
  INCUBATING otherwise.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from app.core.db import db, intraday_lab_positions_collection

registry = db["intraday_v2_registry"]
backtests = db["intraday_v2_backtests"]

THRESHOLDS = {"min_trades": 40, "confirm_t": 2.0, "confirm_min_z": -1.0, "fail_z": -2.0,
              "fail_t_if_negative": -1.0, "early_fail_trades": 20, "early_fail_z": -3.0}


def _expectation(result: dict) -> dict:
    sel, hold, full = result["selection"], result["holdout"], result["full"]
    means = [m for m in (sel.get("expectancy"), hold.get("expectancy") if hold.get("trades", 0) >= 10 else None)
             if m is not None]
    return {
        "per_trade_net_mean": min(means) if means else full.get("expectancy"),
        "per_trade_net_mean_selection": sel.get("expectancy"),
        "per_trade_net_mean_holdout": hold.get("expectancy"),
        "per_trade_net_sd": result.get("per_trade_sd"),
        "win_rate": full.get("win_rate"),
        "trades_full_period": full.get("trades"),
        "profit_factor": full.get("profit_factor"),
        "dsr": result.get("dsr"),
    }


async def register_from_backtest(run_id: str | None = None) -> dict:
    """Register every strategy that passed run `run_id` (default: the latest run)."""
    if run_id is None:
        latest = await backtests.find_one({"_id": "latest"})
        if not latest:
            return {"registered": 0, "reason": "no backtest run stored"}
        run_id = latest["run_id"]
    doc = await backtests.find_one({"_id": f"v2bt:{run_id}:strategies"})
    if not doc:
        return {"registered": 0, "reason": f"run {run_id} not found"}
    added, kept = [], []
    now = datetime.now(timezone.utc)
    for r in doc["results"]:
        if not r.get("passed"):
            continue
        existing = await registry.find_one({"_id": r["strategy_id"]})
        if existing and existing.get("status") in ("INCUBATING", "CONFIRMED"):
            kept.append(r["strategy_id"])
            continue
        await registry.replace_one({"_id": r["strategy_id"]}, {
            "_id": r["strategy_id"], "name": r["name"], "status": "INCUBATING",
            "registered_at": now, "run_id": run_id, "expected": _expectation(r),
            "thresholds": dict(THRESHOLDS), "forward": {}, "history": [],
        }, upsert=True)
        added.append(r["strategy_id"])
    return {"run_id": run_id, "registered": len(added), "already": kept, "new": added}


# Registered WITHOUT a gate pass, from the stock-selection study on 5-minute bars (S4,
# 2026-10-02): positive in development (to 2026-03-31) and holdout (2026-04-01..10-01) at
# almost every parameter setting, but its Deflated Sharpe counted against the 5,184
# variants tried is ~0.05 — the gate's 0.95 is out of reach for any backtest of it now. The
# forward record is the test. Expectations follow this module's rule (the LOWER of the two
# periods' per-trade means) and the larger of their spreads; nothing here may be edited
# once forward trades exist.
PREREGISTERED = {
    "iv2_orb_sel30": {
        "name": "Selected ORB 30-min (top-5 expected move)",
        "study": "S4 OR30|touch|w1430|atr|t2r|top5|both|rvol15",
        "expected": {"per_trade_net_mean": 2111.88, "per_trade_net_mean_selection": 2170.27,
                     "per_trade_net_mean_holdout": 2111.88, "per_trade_net_sd": 22928.81,
                     "win_rate": 0.496, "trades_full_period": 767, "profit_factor": 1.29,
                     "net_bp_selection": 21.7, "net_bp_holdout": 21.12,
                     "dsr": 0.0465, "dsr_note": "deflated for 5,184 variants; 0.98 if it had been the only one"},
    },
    "iv2_orb_sel15": {
        "name": "Selected ORB 15-min (top-5 expected move)",
        "study": "S4 OR15|touch|w1430|opp|eod|top5|both|rvol15",
        "expected": {"per_trade_net_mean": 1861.51, "per_trade_net_mean_selection": 3605.87,
                     "per_trade_net_mean_holdout": 1861.51, "per_trade_net_sd": 27743.61,
                     "win_rate": 0.525, "trades_full_period": 548, "profit_factor": 1.34,
                     "net_bp_selection": 36.06, "net_bp_holdout": 18.62,
                     "dsr": None, "dsr_note": "family best 0.047 deflated for 5,184 variants"},
    },
}


async def preregister() -> dict:
    """Register the PREREGISTERED strategies once. Never overwrites an existing entry."""
    added = []
    for sid, p in PREREGISTERED.items():
        if await registry.find_one({"_id": sid}, {"_id": 1}):
            continue
        await registry.insert_one({
            "_id": sid, "name": p["name"], "status": "INCUBATING", "registered_at": datetime.now(timezone.utc),
            "run_id": None, "source": "pre-registered from the S4 stock-selection study, 2026-10-02",
            "study_key": p["study"], "expected": p["expected"], "thresholds": dict(THRESHOLDS),
            "forward": {}, "history": []})
        added.append(sid)
    return {"registered": added}


async def evaluate_forward() -> dict:
    """Test every incubating strategy's forward record against its frozen expectation."""
    changed = []
    async for reg in registry.find({"status": "INCUBATING"}):
        nets = [float(p.get("realized_pnl") or 0.0) async for p in intraday_lab_positions_collection.find(
            {"strategy_id": reg["_id"], "engine": "v2", "status": {"$ne": "OPEN"},
             "closed_at": {"$gte": reg["registered_at"]}}, {"realized_pnl": 1})]
        n = len(nets)
        th = reg["thresholds"]
        exp = reg["expected"]
        fwd: dict = {"trades": n, "net_pnl": round(sum(nets), 2), "evaluated_at": datetime.now(timezone.utc)}
        status = "INCUBATING"
        if n >= 3:
            mean, sd = sum(nets) / n, statistics.stdev(nets)
            fwd.update({"mean": round(mean, 2), "sd": round(sd, 2),
                        "t": round(mean / (sd / math.sqrt(n)), 3) if sd else None})
            ref_sd = exp.get("per_trade_net_sd") or sd
            z = (mean - (exp.get("per_trade_net_mean") or 0.0)) / (ref_sd / math.sqrt(n)) if ref_sd else None
            fwd["z_vs_expected"] = round(z, 3) if z is not None else None
            t = fwd.get("t")
            if z is not None and n >= th["early_fail_trades"] and z <= th["early_fail_z"]:
                status = "FAILED"
            elif n >= th["min_trades"]:
                if t is not None and t >= th["confirm_t"] and z is not None and z >= th["confirm_min_z"]:
                    status = "CONFIRMED"
                elif (z is not None and z <= th["fail_z"]) or (mean < 0 and t is not None and t <= th["fail_t_if_negative"]):
                    status = "FAILED"
        update = {"forward": fwd, "status": status}
        if status != "INCUBATING":
            update["decided_at"] = datetime.now(timezone.utc)
            update["eligible_for_live"] = status == "CONFIRMED"
            changed.append((reg["_id"], status))
        await registry.update_one({"_id": reg["_id"]}, {
            "$set": update,
            "$push": {"history": {"$each": [{"at": fwd["evaluated_at"], "trades": n, "status": status,
                                             "mean": fwd.get("mean"), "z": fwd.get("z_vs_expected")}],
                                  "$slice": -120}}})
    return {"decided": changed}


async def listing() -> list[dict]:
    out = []
    async for r in registry.find({}).sort("registered_at", -1):
        r["strategy_id"] = r.pop("_id")
        r.pop("history", None)
        out.append(r)
    return out
