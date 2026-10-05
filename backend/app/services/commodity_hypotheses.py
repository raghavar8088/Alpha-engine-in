"""Pre-registered commodity hypotheses (C5) — frozen rules, frozen priors, forward verdicts.

WHY PRE-REGISTER (the 2026-10-03 Commodity Trading audit)
The pattern desk ran ~350 strategies and let a 30-trade gate pick: 11 of its 16 READY picks
lost money afterwards and nothing persisted. Replaying 44 daily templates over 22 years found
none with explore t > 2; four classic trend rules, once the cost of carry is charged, found
no rule that beats simply being long the same commodities. So anything that may ever trade
real money enters here: its rule, its prior and the numbers that would confirm or fail it are
written down BEFORE forward data exists, and the frozen fields are never overwritten
($setOnInsert). Verdicts are read off forward paper P&L at the touch with Angel's charges.

  HC1  5-commodity 12-month trend, whole lots of mini/micro contracts — INCUBATING, weak prior.
  HC2  gold 12-month trend — REJECTED on history: plain long gold did better.
  HC3  fading intraday breakouts on honest fills (15m-1h pooled) — RECORD ONLY to 2026-12-31.
  HC4  carry (futures-curve slope) — WAITING FOR DATA from the MCX curve recorder.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from app.core.db import db

hypotheses = db["commodity_hypotheses"]
REGISTERED_AT = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)

PREREGISTERED = {
    "HC1": {
        "name": "5-commodity 12-month trend (mini contracts)",
        "rule": ("Gold, silver, copper, crude oil, natural gas. Each month on the first MCX trading day from "
                 "11:00 IST (first entry 2026-10-05): long if the commodity's 12-month (252-day) rupee return "
                 "on the Lab series is positive, short if negative; size min(10% / 60-day vol, 3) x capital / 5, "
                 "in whole lots of GOLDPETAL, SILVERMIC, COPPER, CRUDEOILM, NATGASMINI; a leg that rounds to 0 "
                 "lots is not held. Roll before each contract's exit window. Fills at the touch, Angel charges, "
                 "worst-day stress cap 25% of capital."),
        "book": "commodity_trend_book (Rs 50 lakh paper)",
        "prior": {"heldout_2016_2026": {"sharpe": 0.30, "ann_ret_pct": 1.7, "t": 0.99, "max_dd_pct": 20.3},
                  "explore_2004_2015": {"sharpe": 0.26}, "dsr_over_36_trials": 0.28,
                  "always_long_heldout_sharpe": 0.62,
                  "source": "backend/research/commodity_2026_10/cmd_carry.py (carry-corrected, INR, MCX costs + rolls)",
                  "honest_reading": "Positive in both periods but not significant, and it LOST to always-long "
                                    "over 2016-2026. Copper (one lot ~Rs 35 lakh) is not held at Rs 50 lakh, so "
                                    "the traded book is four commodities."},
        "thresholds": {"confirm_min_months": 24, "confirm_t": 2.0, "must_beat_long": True,
                       "fail_min_months": 12, "fail_t": -1.0, "fail_drawdown_pct": 40.0},
        "expectation": "At a true Sharpe near 0.3, a forward t of 2 takes decades. Expect INCUBATING for a long "
                       "time; real money stays locked until the forward record alone is significant.",
        "origin": "user plan C5",
    },
    "HC2": {
        "name": "Gold 12-month trend",
        "rule": "Long gold when its 12-month rupee return is positive, short when negative; vol-targeted 10%.",
        "prior": {"heldout_sharpe": 0.49, "always_long_gold_heldout_sharpe": 0.65, "share_of_days_long": 0.87,
                  "corr_with_long_only": 0.75, "dsr": 0.495},
        "verdict_reason": "Rejected on history: it was long 87% of the time and plain long gold beat it "
                          "(0.65 vs 0.49 held-out Sharpe) with a smaller drawdown. No timing skill to pay for.",
        "origin": "user plan C5",
    },
    "HC3": {
        "name": "Fade intraday breakouts on honest fills (15m-1h pooled)",
        "rule": ("Take the opposite side of every pattern-desk signal on 15m, 30m, 45m and 1h, at the same fill "
                 "and exit. Measured on the desk's own HONEST trades (live quote, MCX open, own contract) "
                 "opened 2026-10-05 .. 2026-12-31, all four timeframes pooled — never one timeframe picked "
                 "after the fact."),
        "test": ("fade net per trade = -(raw move) - charges - 10 bp slippage; decision on or after "
                 "2026-12-31: pooled t >= 3 -> INCUBATING (a paper fade book is then built); otherwise REJECTED."),
        "decision_date": "2026-12-31",
        "prior": {"sample": "2026-09-25..10-02, 6 sessions, forming-bar signals", "raw_bp_15m": -17.9,
                  "raw_bp_30m": -43.2, "raw_bp_45m": -35.0, "raw_bp_1h": 1.6,
                  "caveat": "Signals now use CLOSED bars only (C2), so the prior may not transfer; 30m alone "
                            "(+27 bp after costs) would be cherry-picking one of eight timeframes."},
        "thresholds": {"pass_t": 3.0, "timeframes": ["15m", "30m", "45m", "1h"],
                       "from": "2026-10-05", "to": "2026-12-31", "slippage_bp": 10.0},
        "origin": "user plan C5",
    },
    "HC4": {
        "name": "Carry (futures-curve slope)",
        "rule": ("Monthly on the first trading day: rank GOLD, SILVER, COPPER, ZINC, ALUMINIUM, LEAD, NICKEL, "
                 "CRUDEOIL, NATURALGAS by the annualised slope between their first two listed contracts (mean of "
                 "the last 5 trading days of mcx_curve); long the 2 most backwardated, short the 2 most in "
                 "contango, equal volatility weights."),
        "test": "first evaluation after >= 126 trading days of curve data; forward t >= 2 over >= 12 months to pass.",
        "prior": {"note": "Untestable on MCX history (no source keeps old MCX curves). The literature's carry "
                          "premium is measured across 20+ commodities; with 9 the breadth is low."},
        "thresholds": {"min_curve_days": 126, "confirm_t": 2.0, "confirm_min_months": 12},
        "origin": "user plan C5",
    },
}
INITIAL_STATUS = {"HC1": "INCUBATING", "HC2": "REJECTED_ON_HISTORY", "HC3": "RECORD_ONLY", "HC4": "WAITING_FOR_DATA"}


async def register() -> None:
    """Insert the frozen definitions once. Never overwrites a frozen field."""
    for hid, spec in PREREGISTERED.items():
        await hypotheses.update_one({"_id": hid}, {"$setOnInsert": {**spec, "registered_at": REGISTERED_AT,
                                                                     "status": INITIAL_STATUS[hid]}}, upsert=True)


def _t(xs: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


async def _hc1(doc: dict) -> dict:
    from app.services.commodity_trend_book import CAPITAL, equity_collection

    eq = [e async for e in equity_collection.find({}, {"_id": 0, "date": 1, "equity": 1}).sort("date", 1)]
    if not eq:
        return {"status": doc.get("status", "INCUBATING"), "forward": {"days": 0}}
    month_end: dict[str, float] = {}
    for e in eq:
        month_end[e["date"][:7]] = e["equity"]
    vals = [CAPITAL] + [month_end[k] for k in sorted(month_end)]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    peak, mdd = CAPITAL, 0.0
    for e in eq:
        peak = max(peak, e["equity"])
        mdd = max(mdd, (peak - e["equity"]) / peak * 100)
    fwd = {"days": len(eq), "months": len(rets), "return_pct": round((eq[-1]["equity"] / CAPITAL - 1) * 100, 3),
           "monthly_t": round(_t(rets), 2) if _t(rets) is not None else None, "max_dd_pct": round(mdd, 2)}
    # The benchmark it must beat: always-long the same five commodities, same vol targeting,
    # same costs and carry, simulated on the Lab series over the same forward days.
    try:
        from app.services import commodity_lab as lab
        from app.services import commodity_lab_data as data

        hist = await data.load()
        start = datetime.fromisoformat(eq[0]["date"]).date()
        longp = lab.portfolio([lab.run_rule(hist.closes[k], k, "LONG") for k in data.COMMODITIES])
        fwd["always_long_return_pct"] = round(sum(v for d, v in longp.items() if d >= start) * 100, 3)
    except Exception:  # noqa: BLE001 — no benchmark, no confirmation
        fwd["always_long_return_pct"] = None
    th = doc.get("thresholds") or PREREGISTERED["HC1"]["thresholds"]
    status = doc.get("status", "INCUBATING")
    beats_long = fwd["always_long_return_pct"] is not None and fwd["return_pct"] > fwd["always_long_return_pct"]
    if mdd > th["fail_drawdown_pct"] or (len(rets) >= th["fail_min_months"] and (fwd["monthly_t"] or 0) <= th["fail_t"]):
        status = "REJECTED_FORWARD"
    elif len(rets) >= th["confirm_min_months"] and (fwd["monthly_t"] or 0) >= th["confirm_t"] and beats_long:
        status = "CONFIRMED"
    fwd["beats_always_long"] = beats_long
    return {"status": status, "forward": fwd}


async def _hc3(doc: dict) -> dict:
    from app.core.db import commodity_positions_collection

    th = doc.get("thresholds") or PREREGISTERED["HC3"]["thresholds"]
    lo = datetime.fromisoformat(th["from"]).replace(tzinfo=timezone.utc)
    hi = datetime.fromisoformat(th["to"]).replace(tzinfo=timezone.utc)
    xs = []
    async for p in commodity_positions_collection.find(
            {"status": {"$ne": "OPEN"}, "honest": True, "timeframe": {"$in": th["timeframes"]},
             "opened_at": {"$gte": lo, "$lt": hi}},
            {"raw_bp": 1, "costs": 1, "entry_price": 1, "qty": 1}):
        notional = (p.get("entry_price") or 0) * (p.get("qty") or 0)
        if p.get("raw_bp") is None or not notional:
            continue
        charges_bp = (p.get("costs") or 0) / notional * 1e4
        xs.append(-p["raw_bp"] - charges_bp - th["slippage_bp"])
    t = _t(xs)
    stats = {"trades": len(xs), "fade_net_bp": round(statistics.mean(xs), 2) if xs else None,
             "t": round(t, 2) if t is not None else None}
    status = "RECORD_ONLY"
    if datetime.now(timezone.utc) >= hi:
        status = "INCUBATING" if (t is not None and t >= th["pass_t"]) else "REJECTED_FORWARD"
    return {"status": status, "forward": stats}


async def _hc4(doc: dict) -> dict:
    from app.services.mcx_curve_recorder import curve_collection

    days = len(await curve_collection.distinct("date"))
    th = doc.get("thresholds") or PREREGISTERED["HC4"]["thresholds"]
    return {"status": "WAITING_FOR_DATA" if days < th["min_curve_days"] else "READY_TO_EVALUATE",
            "forward": {"curve_days": days, "needed": th["min_curve_days"]}}


async def evaluate_all() -> dict:
    await register()
    out = {}
    for hid in PREREGISTERED:
        doc = await hypotheses.find_one({"_id": hid}) or {}
        if hid == "HC1":
            r = await _hc1(doc)
        elif hid == "HC3":
            r = await _hc3(doc)
        elif hid == "HC4":
            r = await _hc4(doc)
        else:
            r = {"status": doc.get("status", INITIAL_STATUS[hid]), "forward": None}
        await hypotheses.update_one({"_id": hid}, {"$set": {"status": r["status"], "forward": r["forward"],
                                                            "evaluated_at": datetime.now(timezone.utc)}})
        out[hid] = r
    return out


async def listing() -> list[dict]:
    await register()
    rows = []
    async for h in hypotheses.find({}).sort("_id", 1):
        h["id"] = h.pop("_id")
        for k in ("registered_at", "evaluated_at"):
            if isinstance(h.get(k), datetime):
                h[k] = h[k].isoformat()
        rows.append(h)
    return rows
