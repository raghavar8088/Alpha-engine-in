"""H1 — what does a Rs 10 lakh market order REALLY cost in the names the best strategies trade?

WHY THIS IS THE ONE EXPERIMENT THAT MATTERS (INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md, §3.4)
Over two years the tournament's 52 replayable strategies lost money net — but 37 of them have
a POSITIVE edge before friction, and six clear the multiple-testing bar on it. Friction is
Angel's charges (4.02 bp a round trip, checked to the rupee, irreducible) plus slippage, which
is MODELLED: 1-4 bp a side by the name's turnover, calibrated for a Rs 2 lakh order and applied
since 2 Oct to Rs 10 lakh ones. For three strategies the whole verdict turns on that model:

    iv2_donchian_45m    breaks even if real slippage <= 1.80 bp a side
    iv2_donchian_1h                                   <= 1.50
    iv2_vwap_trend_1h                                 <= 1.29

At the modelled ~2.76 bp none survives. Below those numbers they might. This module measures
it — WITHOUT placing an order. At every signal of the three, as the tournament decides, it
reads Angel's visible five-level book and computes what a market order of the tournament's own
size would have paid walking it.

PRE-REGISTERED. The hypothesis, the metric, the sample size and the decision rule are written
below and stored ONCE, before any sample is collected, with a fingerprint. Nothing about the
test may be changed after samples start arriving; if this file's rule ever differs from the
stored one, the stored one governs and the report says so. That is the whole difference between
an experiment and looking at numbers until they look good.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import statistics
from datetime import datetime, timezone

from app.core.db import db

logger = logging.getLogger("h1_slippage")

samples = db["intraday_h1_samples"]
meta = db["intraday_h1"]

PREREGISTRATION = {
    "id": "H1",
    "title": "Real per-side cost of a Rs 10 lakh market order, from Angel's visible book",
    "written": "2026-10-10",
    "hypothesis": (
        "For each strategy below, the median cost of a Rs 10 lakh market order on the "
        "signal's side, measured from Angel's five-level book at the moment the tournament "
        "decides, is at most 80% of that strategy's break-even slippage."),
    "strategies": {
        "iv2_donchian_45m": {"break_even_bp": 1.80},
        "iv2_donchian_1h": {"break_even_bp": 1.50},
        "iv2_vwap_trend_1h": {"break_even_bp": 1.29},
    },
    "notional_rs": 1_000_000,
    "metric": ("cost_bp_vs_ltp of ENTRY samples: (book-walk VWAP - LTP) / LTP x 1e4, signed so "
               "that a cost is positive — the same definition the tournament's slippage model "
               "applies to the LTP it fills at"),
    "min_samples_per_strategy": 100,
    "go_fraction_of_break_even": 0.80,
    "insufficient_depth_rule": (
        "a sample whose visible five levels cannot fill the order is priced at its best-case "
        "(the remainder at the worst visible level); if more than 10% of a strategy's samples "
        "are like that, its verdict is NO-GO — the order is too big for the book it trades"),
    "max_insufficient_share": 0.10,
    "decision": (
        "GO for a strategy: n >= min_samples AND median <= go_fraction x break_even AND the "
        "insufficient share <= max_insufficient_share. A GO strategy may then be registered for "
        "a forward paper test with its MEASURED slippage — it is not, by itself, permission to "
        "trade. NO-GO otherwise. Until n >= min_samples: COLLECTING."),
}


def _fingerprint(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


_registered = False

H1_STRATEGIES: dict[str, float] = {
    sid: v["break_even_bp"] for sid, v in PREREGISTRATION["strategies"].items()}


async def ensure_preregistered() -> dict:
    """Write the pre-registration once. Never overwrites; reports any drift. Never raises."""
    try:
        stored = await meta.find_one({"_id": "preregistration"})
        fp = _fingerprint(PREREGISTRATION)
        if stored is None:
            await meta.insert_one({"_id": "preregistration", "doc": PREREGISTRATION,
                                   "fingerprint": fp, "stored_at": datetime.now(timezone.utc)})
            logger.warning("[H1] pre-registration stored (%s)", fp)
            return {"stored": True, "fingerprint": fp}
        if stored.get("fingerprint") != fp:
            logger.error("[H1] this code's rule differs from the stored pre-registration — the "
                         "STORED one governs (%s vs %s)", stored.get("fingerprint"), fp)
        return {"stored": False, "fingerprint": stored.get("fingerprint"), "code_fingerprint": fp}
    except Exception:  # noqa: BLE001
        logger.exception("[H1] could not ensure the pre-registration")
        return {"stored": False, "error": True}


# ── the measurement (pure) ───────────────────────────────────────────────────────


def walk_book(levels: list[list[float]], shares: int) -> tuple[float | None, int]:
    """VWAP of filling `shares` down the given levels (best first), and how many filled."""
    left, cost, got = int(shares), 0.0, 0
    for price, qty in levels:
        if left <= 0:
            break
        take = min(int(qty), left)
        if take <= 0:
            continue
        cost += take * float(price)
        got += take
        left -= take
    return ((cost / got) if got else None), got


def cost_of(side: str, notional: float, ltp: float, bids: list[list[float]],
            asks: list[list[float]]) -> dict | None:
    """What a market order of `notional` rupees would have paid against this book.

    A BUY walks the asks, a SELL the bids. Costs are signed so that paying more than the
    reference is POSITIVE, for either side. When the visible book cannot fill the order, the
    remainder is priced at the worst visible level — a best case, flagged as such."""
    if not ltp or ltp <= 0:
        return None
    levels = asks if side == "BUY" else bids
    if not levels:
        return None
    shares = int(notional // ltp)
    if shares < 1:
        return None
    vwap, filled = walk_book(levels, shares)
    if vwap is None:
        return None
    insufficient = filled < shares
    if insufficient:
        worst = float(levels[-1][0])
        vwap = (vwap * filled + worst * (shares - filled)) / shares
    sign = 1 if side == "BUY" else -1
    bid = float(bids[0][0]) if bids else None
    ask = float(asks[0][0]) if asks else None
    mid = (bid + ask) / 2 if (bid and ask) else None
    return {
        "shares": shares, "filled_visible": filled, "insufficient_depth": insufficient,
        "depth_covered_pct": round(filled / shares * 100, 1),
        "vwap": round(vwap, 4), "ltp": ltp, "bid": bid, "ask": ask,
        "mid": round(mid, 4) if mid else None,
        "half_spread_bp": round((ask - bid) / 2 / mid * 1e4, 3) if mid else None,
        "cost_bp_vs_ltp": round(sign * (vwap - ltp) / ltp * 1e4, 3),
        "cost_bp_vs_mid": round(sign * (vwap - mid) / mid * 1e4, 3) if mid else None,
    }


# ── capture (live) ───────────────────────────────────────────────────────────────


async def capture(items: list[dict]) -> int:
    """Read the book for these signals and store what each order would have paid.

    `items`: {strategy_id, symbol, token, side, phase ("entry"|"exit"), reason, ltp,
    signal_at}. One quote call for the batch. Never raises — it is a measurement riding
    beside a trading engine, and must never be the reason the engine stops."""
    items = [i for i in items if i.get("strategy_id") in H1_STRATEGIES and i.get("token")]
    if not items:
        return 0
    # The rule is stored before the first sample it will judge, never after.
    global _registered
    if not _registered:
        _registered = bool((await ensure_preregistered()).get("fingerprint"))
    try:
        from app.services.angel_client import angel_client
        q = await angel_client.full_quote({"NSE": sorted({str(i["token"]) for i in items})})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[H1] book read failed (%s) — %d signal(s) not measured",
                       type(exc).__name__, len(items))
        return 0
    stored = 0
    now = datetime.now(timezone.utc)
    for i in items:
        row = q.get(str(i["token"])) or {}
        ltp = i.get("ltp") or row.get("ltp")
        c = cost_of(i["side"], PREREGISTRATION["notional_rs"], float(ltp or 0),
                    row.get("depth_buy") or [], row.get("depth_sell") or [])
        doc = {"strategy_id": i["strategy_id"], "symbol": i["symbol"], "side": i["side"],
               "phase": i.get("phase", "entry"), "reason": i.get("reason"),
               "signal_at": i.get("signal_at"), "measured_at": now,
               "lag_s": (now - i["signal_at"]).total_seconds() if i.get("signal_at") else None,
               "trade_time": row.get("trade_time"), "measurable": c is not None, **(c or {})}
        try:
            await samples.insert_one(doc)
            stored += 1
        except Exception:  # noqa: BLE001
            logger.exception("[H1] could not store a sample")
    return stored


def schedule(items: list[dict]) -> None:
    """Fire-and-forget from inside the engine; a failure is logged, never propagated."""
    if not any(i.get("strategy_id") in H1_STRATEGIES for i in items):
        return

    async def _run():
        try:
            await capture(items)
        except Exception:  # noqa: BLE001
            logger.exception("[H1] capture task failed")
    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass


# ── the report, by the stored rule ───────────────────────────────────────────────


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def verdict(entry_costs: list[float], insufficient: int, rule: dict, break_even: float) -> dict:
    """The pre-registered decision for one strategy. Pure."""
    n = len(entry_costs)
    med = round(statistics.median(entry_costs), 3) if entry_costs else None
    threshold = round(rule["go_fraction_of_break_even"] * break_even, 3)
    share = round(insufficient / n, 3) if n else 0.0
    if n < rule["min_samples_per_strategy"]:
        status = "COLLECTING"
    elif share > rule["max_insufficient_share"]:
        status = "NO-GO"
    elif med is not None and med <= threshold:
        status = "GO"
    else:
        status = "NO-GO"
    return {"n": n, "median_bp": med, "threshold_bp": threshold, "break_even_bp": break_even,
            "insufficient_share": share, "status": status,
            "progress_pct": round(min(100.0, n / rule["min_samples_per_strategy"] * 100), 1)}


async def report() -> dict:
    stored = await meta.find_one({"_id": "preregistration"})
    rule = (stored or {}).get("doc") or PREREGISTRATION
    out = {"preregistration": rule, "fingerprint": (stored or {}).get("fingerprint"),
           "code_matches_stored": bool(stored) and stored.get("fingerprint") == _fingerprint(PREREGISTRATION),
           "strategies": {}}
    for sid, cfg in rule["strategies"].items():
        rows = [d async for d in samples.find({"strategy_id": sid, "measurable": True},
                                              {"phase": 1, "cost_bp_vs_ltp": 1, "cost_bp_vs_mid": 1,
                                               "half_spread_bp": 1, "insufficient_depth": 1})]
        entries = [r for r in rows if r.get("phase") == "entry"]
        costs = [float(r["cost_bp_vs_ltp"]) for r in entries if r.get("cost_bp_vs_ltp") is not None]
        v = verdict(costs, sum(1 for r in entries if r.get("insufficient_depth")), rule,
                    cfg["break_even_bp"])
        v.update({
            "p25_bp": _pct(costs, 0.25), "p75_bp": _pct(costs, 0.75),
            "median_vs_mid_bp": _pct([float(r["cost_bp_vs_mid"]) for r in entries
                                      if r.get("cost_bp_vs_mid") is not None], 0.5),
            "median_half_spread_bp": _pct([float(r["half_spread_bp"]) for r in entries
                                           if r.get("half_spread_bp") is not None], 0.5),
            "exit_samples": len(rows) - len(entries),
        })
        out["strategies"][sid] = v
    out["unmeasurable"] = await samples.count_documents({"measurable": False})
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["note"] = ("Collected at every signal of the three strategies, taken or not, about 20 s "
                   "after each bar closes. No order is ever placed.")
    return out
