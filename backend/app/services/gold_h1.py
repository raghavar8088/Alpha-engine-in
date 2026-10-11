"""Gold Desk H1 — does the 4h breakout / trend family earn its costs on Delta, going forward?

WHY THIS IS THE ONE EXPERIMENT (GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md §3.3, §8 H1)
-----------------------------------------------------------------------------------
The desk's 353 strategies were replayed on six gold histories with honest fills and measured
costs (backend/research/gold_2026_10). Below 4h nothing earns its fees; at 1d, 39 of 40
templates lose to simply holding gold. ONE effect has the same sign on every history that can
show it: the nine breakout / trend-structure templates at 4h earned +16.2, +12.2 and +12.0 bp a
trade net (Binance PAXG 2025-26, Delta's own 2026 data, COMEX in MCX hours 2024-26), with a
known mechanism — short-horizon trend-following. It was FOUND in that data, so history cannot
confirm it; only trades taken after this rule was written down can.

PRE-REGISTERED
--------------
The rule, the metric and the decision are below and are stored ONCE, with a fingerprint,
before the first H1 position can open (gold_desk refuses to open one otherwise). If this
file's rule ever differs from the stored one, the stored one governs and the report says so.

Power is stated up front: at the replay's own edge the expected weekly t is ~1.5 after one year
and ~2.1 after two; at half that edge, 0.7 and 1.0. A NO-GO is the likely outcome even if a
small edge exists. A GO would mean something.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone

from app.core.db import gold_positions_collection, gold_state_collection
from app.services import gold_delta_feed

logger = logging.getLogger("gold_h1")

PREREG_ID = "h1_preregistration"
BOUNDARIES_ID = "h1_xaut_boundaries"   # XAUT's price at each week boundary, recorded once

H1_TEMPLATES: tuple[str, ...] = (
    "donchian_fast", "donchian_slow", "keltner_break", "prior_session_break",
    "round_number_break", "pivot_break", "hh_hl_shift", "atr_thrust", "ema_ribbon",
)
H1_TIMEFRAME = "4h"
H1_SYMBOL = "XAUTUSD"

PREREGISTRATION = {
    "id": "GOLD-H1",
    "title": "The 4h breakout / trend-structure family on Delta XAUTUSD, forward, paper",
    "written": "2026-10-11",
    "hypothesis": (
        "Pooled over the nine templates below at 4h on Delta's XAUTUSD perpetual, trades taken "
        "after this rule was stored earn a positive mean net of the venue's fee, the spread "
        "paid and funding — and more than holding XAUT would have earned on the same weeks."),
    "evidence_at_registration": {
        "binance_paxg_2025_26": {"net_bp": 16.2, "trades": 1693},
        "delta_2026": {"net_bp": 12.2, "trades": 1045},
        "comex_mcx_hours_2024_26": {"net_bp": 12.0, "trades": 1129},
        "no_single_strategy_survives_deflation": True,
        "source": "GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md §3.3; backend/research/gold_2026_10",
    },
    "rule": {
        "venue": "Delta Exchange India perpetual", "symbol": H1_SYMBOL,
        "templates": list(H1_TEMPLATES), "timeframe": H1_TIMEFRAME,
        "evaluation": ("commodity_patterns.evaluate() on the last 250 CLOSED 4h bars, buckets "
                       "anchored to UTC midnight; every closed bar including weekends, exactly as "
                       "replayed; one decision per template per bar, taken once the store has "
                       "re-read the bar after its close (never on a bar stored while forming)"),
        "positions": ("one per template at a time, each in its own sleeve of capital / 9 at 1x "
                      "(whole 0.001 oz contracts); templates are recorded independently — no shared "
                      "slots, no netting between them, no daily breaker (each would censor the "
                      "sample the hypothesis is about); a 50% book floor stays as a ruin guard"),
        "entry": ("market at the best bid / ask once the desk has the final closed bar (normally "
                  "within ~5 minutes of its close; the book walked if the order exceeds the touch); "
                  "a bar first seen more than 15 minutes after its close is skipped, never traded "
                  "late; target and stop scaled by fill / signal close"),
        "exits": ("walked on FINAL 1-minute bars from the minute after the fill (gold_fills."
                  "walk_exit): a level inside a minute fills at the level, a minute opening past a "
                  "level fills at that open, a minute touching both is a stop; hold limit = the "
                  "close of the 60th 4h bar after the signal bar, at the last minute's close"),
        "costs": ("Delta's taker commission from the product spec x 1.18 (GST) on both legs; the "
                  "spread paid at entry as filled; market exits (stop, time) pay 0.04 bp "
                  "(the measured median half-spread for a sleeve, 2026-10-10); funding at every "
                  "4-hourly exchange the position is open across, at the FUNDING:XAUTUSD rate in "
                  "force (the hour ending at the exchange) read as % per exchange — a time exit "
                  "leaves before the exchange at its hold limit"),
        "capital_usd": 10_000,
    },
    "metric": ("per-trade net return in bp of the trade's entry notional; pooled over all H1 "
               "trades; tested on WEEKLY sums (trades overlap); weeks counted from the moment this "
               "rule was stored; alpha = intercept of the weekly H1 book return (realised P&L of "
               "trades closed that week / capital) regressed on XAUT's return over the same week, "
               "XAUT priced at each week boundary as it passes; a week whose XAUT price could not "
               "be read is left out of the regression, never filled in"),
    "decision": {
        "final_week": 104,
        "go": "pooled net mean > 0 AND weekly t >= 2 AND weekly alpha t >= 2",
        "no_go": "anything else at week 104",
        "futility_week": 52,
        "futility": "stop at week 52 if the pooled net mean <= 0 OR the weekly t <= -1",
        "min_trades_for_any_verdict": 100,
        "what_go_means": ("eligible for the Commodity Lab gate and an incubation on real fills — "
                          "not permission to trade money"),
    },
    "power": ("expected weekly t at the replay's edge (+10 to +14 bp a trade, ~18.5 trades a "
              "week): 1.5 after 52 weeks, 2.1 after 104; at half that edge 0.7 and 1.0"),
}

GO_T = 2.0
FUTILITY_T = -1.0


def fingerprint(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


async def ensure_preregistered() -> dict:
    """Write the pre-registration once. Never overwrites; reports drift. Never raises."""
    try:
        stored = await gold_state_collection.find_one({"_id": PREREG_ID})
        fp = fingerprint(PREREGISTRATION)
        if stored is None:
            await gold_state_collection.insert_one({"_id": PREREG_ID, "doc": PREREGISTRATION,
                                                    "fingerprint": fp, "stored_at": datetime.now(timezone.utc)})
            logger.warning("[gold H1] pre-registration stored (%s)", fp)
            return {"stored": True, "fingerprint": fp}
        if stored.get("fingerprint") != fp:
            logger.error("[gold H1] the code's rule differs from the stored pre-registration — the "
                         "STORED one governs (%s vs %s)", stored.get("fingerprint"), fp)
        return {"stored": False, "fingerprint": stored.get("fingerprint"), "code_fingerprint": fp}
    except Exception:  # noqa: BLE001
        logger.exception("[gold H1] could not ensure the pre-registration")
        return {"stored": False, "error": True}


async def stored() -> dict | None:
    return await gold_state_collection.find_one({"_id": PREREG_ID})


def is_h1(template: str, timeframe: str, symbol: str) -> bool:
    return template in H1_TEMPLATES and timeframe == H1_TIMEFRAME and symbol == H1_SYMBOL


# ── the decision (pure) ──────────────────────────────────────────────────────────


def _t(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else None


def _ols_alpha_t(y: list[float], x: list[float]) -> tuple[float | None, float | None, float | None]:
    """(alpha, beta, t of alpha) for y = a + b x. None when underdetermined."""
    n = len(y)
    if n < 4 or len(x) != n:
        return None, None, None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx <= 0:
        return None, None, None
    b = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sxx
    a = my - b * mx
    resid = [yi - (a + b * xi) for xi, yi in zip(x, y)]
    s2 = sum(r * r for r in resid) / (n - 2)
    se_a = math.sqrt(s2 * (1 / n + mx * mx / sxx)) if s2 > 0 else 0.0
    return a, b, (a / se_a if se_a > 0 else None)


def week_index(ts: datetime, start: datetime) -> int:
    return int((ts - start).total_seconds() // (7 * 86400))


def decide(trades: list[dict], weekly_book: list[float], weekly_xaut: list[float | None],
           weeks_elapsed: int, rule: dict | None = None) -> dict:
    """The pre-registered verdict from the closed H1 trades.

    trades: [{"net_bp": float, "week": int}]; weekly_book / weekly_xaut: the H1 book's weekly
    return and XAUT's, aligned by week, over completed weeks — a week whose XAUT return is None
    (unmeasured) is left out of the regression. Pure — the same inputs always give the same
    answer, and nothing here can see anything but the stored rule's thresholds."""
    d = (rule or PREREGISTRATION)["decision"]
    final_w, fut_w = int(d["final_week"]), int(d["futility_week"])
    min_n = int(d["min_trades_for_any_verdict"])
    weeks = max(int(weeks_elapsed), 0)

    def window(upto: int) -> dict:
        """Statistics on trades closed in weeks [0, upto) — a look never sees later trades."""
        tr = [t for t in trades if 0 <= int(t["week"]) < upto]
        net = [float(t["net_bp"]) for t in tr]
        by_week = [0.0] * upto
        for t in tr:
            by_week[int(t["week"])] += float(t["net_bp"])
        pairs = [(float(bk), float(x)) for bk, x in zip(weekly_book[:upto], weekly_xaut[:upto]) if x is not None]
        a, b, at = _ols_alpha_t([p[0] for p in pairs], [p[1] for p in pairs])
        return {"trades": len(tr), "mean": (sum(net) / len(net)) if net else None,
                "wt": _t(by_week) if upto >= 3 else None, "alpha": a, "beta": b, "alpha_t": at,
                "xaut_weeks": len(pairs)}

    span = min(weeks, final_w)
    cur = window(span)
    out = {"trades": cur["trades"], "weeks": weeks,
           "net_bp_mean": round(cur["mean"], 3) if cur["mean"] is not None else None,
           "weekly_t": round(cur["wt"], 3) if cur["wt"] is not None else None,
           "alpha_weekly": cur["alpha"], "beta": round(cur["beta"], 4) if cur["beta"] is not None else None,
           "alpha_t": round(cur["alpha_t"], 3) if cur["alpha_t"] is not None else None,
           "xaut_weeks_measured": cur["xaut_weeks"],
           "progress_pct": round(min(weeks / final_w, 1.0) * 100, 1)}

    # ONE interim look, at week 52, on the first 52 weeks only.
    if weeks >= fut_w:
        f = window(fut_w)
        if f["mean"] is None or f["mean"] <= 0 or (f["wt"] is not None and f["wt"] <= FUTILITY_T):
            out.update(status="FUTILE", futility_look={"trades": f["trades"], "net_bp_mean": f["mean"],
                                                       "weekly_t": f["wt"]},
                       why=("week %d futility look: pooled net <= 0 or weekly t <= -1 — the test "
                            "stops; the record stays" % fut_w))
            return out
    if weeks >= final_w:
        go = (cur["trades"] >= min_n and cur["mean"] is not None and cur["mean"] > 0
              and cur["wt"] is not None and cur["wt"] >= GO_T
              and cur["alpha_t"] is not None and cur["alpha_t"] >= GO_T)
        out.update(status="GO" if go else "NO-GO",
                   why=("pooled net > 0, weekly t >= 2 and alpha t >= 2 over weeks 1-%d" % final_w if go else
                        "at week %d the pre-registered GO conditions are not all met" % final_w))
        return out
    out.update(status="COLLECTING", why="week %d of %d" % (weeks, final_w))
    return out


# ── the report ───────────────────────────────────────────────────────────────────


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def snapshot_boundaries(now: datetime | None = None) -> dict[int, float]:
    """XAUT's price at each H1 week boundary (week w starts at stored_at + 7w days), recorded ONCE
    as soon as the store can give it — normally from the 1m bars within minutes of the boundary,
    since the Delta cycle calls this every few minutes — and never rewritten. So H1's benchmark
    never depends on how long any bar store keeps its history. Returns {week: price}. Never raises."""
    try:
        st = await stored()
        if not st:
            return {}
        start = _aware(st["stored_at"])
        now = now or datetime.now(timezone.utc)
        weeks = week_index(now, start)
        doc = await gold_state_collection.find_one({"_id": BOUNDARIES_ID}) or {}
        have = {int(k): float(v["price"]) for k, v in (doc.get("px") or {}).items()}
        new: dict[str, dict] = {}
        for w in range(max(weeks, 0) + 1):
            if w in have:
                continue
            got = await gold_delta_feed.price_at(H1_SYMBOL, start + timedelta(days=7 * w))
            if got:
                new[str(w)] = {"price": got[0], "tf": got[1], "at": now}
                have[w] = got[0]
        if new:
            await gold_state_collection.update_one(
                {"_id": BOUNDARIES_ID}, {"$set": {f"px.{k}": v for k, v in new.items()}}, upsert=True)
        return have
    except Exception:  # noqa: BLE001
        logger.exception("[gold H1] could not record the week-boundary prices")
        return {}


async def report() -> dict:
    """What the page shows: the stored rule, its fingerprint, progress and the verdict so far."""
    st = await stored()
    if st is None:
        return {"preregistered": False, "rule": PREREGISTRATION, "fingerprint": None,
                "code_matches_stored": None, "status": "NOT STORED"}
    rule = st.get("doc") or PREREGISTRATION
    start = _aware(st["stored_at"])
    now = datetime.now(timezone.utc)
    weeks = week_index(now, start)
    trades, book_weekly = [], [0.0] * max(weeks, 0)
    cap = float(rule["rule"]["capital_usd"])
    open_n = 0
    async for p in gold_positions_collection.find({"venue": "delta", "h1": True, "void": {"$ne": True}}):
        if p.get("status") == "OPEN":
            open_n += 1
            continue
        ca = p.get("closed_at")
        if not isinstance(ca, datetime):
            continue
        w = week_index(_aware(ca), start)
        notional = float(p.get("notional") or 0)
        net = float(p.get("realized_pnl") or 0)
        if notional > 0:
            trades.append({"net_bp": net / notional * 1e4, "week": w})
        if 0 <= w < weeks:
            book_weekly[w] += net / cap
    px = await snapshot_boundaries(now)
    xaut = [(px[w + 1] / px[w] - 1) if (w in px and w + 1 in px and px[w] > 0) else None for w in range(max(weeks, 0))]
    verdict = decide(trades, book_weekly, xaut, weeks, rule)
    return {"preregistered": True, "fingerprint": st.get("fingerprint"),
            "code_matches_stored": st.get("fingerprint") == fingerprint(PREREGISTRATION),
            "stored_at": start.isoformat(), "rule": rule, "open_positions": open_n, **verdict}
