"""Orchestration: market breadth, the tradable setup shortlists, source honesty, snapshots.

BREADTH IS COMPUTED, NOT SCRAPED. The Chartink "Market Matrix" dashboard the plan started
from is largely a breadth board — % of stocks above their 20/50/200 SMA, new highs versus
new lows, advances versus declines. Every one of those is a count over the universe
snapshot this module already builds, so they are computed here from our own bars: live
rather than delayed, and with no dependency on a third party staying reachable.

One of its widgets genuinely cannot be reproduced locally: stocks above VWAP. VWAP is an
intraday construct and this app stores daily bars, so that number is reported as
unavailable with the reason attached, rather than substituted with something adjacent and
presented as if it were the same measurement.

THE SETUPS TAB IS THE POINT OF THE MODULE. Everything else describes the market; this
answers "what do I actually trade today", and it is the screen most likely to be trusted
without reading the small print. So it is the strictest: a stock reaches a shortlist only
by passing that mode's gate, and every row carries reward-to-risk NET of real Angel One
charges. A setup whose net R:R falls below 1 is still shown — with `worth_taking: false` —
because silently hiding it would leave the reader unable to tell "no setups today" from
"the setups today are not worth the costs", and those are very different market states.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.core.db import screener_momentum_collection, screener_sectors_collection
from app.services.screener import chartink, nse_breadth, patterns, plans, sectors
from app.services.screener import horizons as H
from app.services.screener import momentum as M

logger = logging.getLogger("screener.engine")

SETUP_KINDS = ["intraday", "swing", "breakout"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def summary(index: str | None = None, fresh: bool = False) -> dict:
    """The breadth header: advances/declines, moving-average breadth, highs vs lows."""
    index = index or M.DEFAULT_INDEX
    snap = await M.universe_snapshot(index, fresh=fresh)
    rows = snap["rows"]

    def _share(pred) -> dict:
        eligible = [r for r in rows if pred(r) is not None]
        if not eligible:
            return {"pct": None, "n": 0, "of": 0}
        hit = sum(1 for r in eligible if pred(r))
        return {"pct": round(hit / len(eligible) * 100, 1), "n": hit, "of": len(eligible)}

    def _above(key):
        return lambda r: (r["ltp"] > r[key]) if r.get(key) else None

    day = [r["returns"].get("1d") for r in rows if r["returns"].get("1d") is not None]
    advances = sum(1 for v in day if v > 0)
    declines = sum(1 for v in day if v < 0)

    new_highs = sum(1 for r in rows
                    if r.get("pct_from_52w_high") is not None and r["pct_from_52w_high"] >= -0.5)
    new_lows = sum(1 for r in rows
                   if r.get("pct_from_52w_low") is not None and r["pct_from_52w_low"] <= 0.5)

    nse = await nse_breadth.snapshot() if fresh else {"market_open": None, "endpoints": {}}

    return {
        "index": snap["index"],
        "label": snap["label"],
        "universe": len(rows),
        "advances": advances,
        "declines": declines,
        "unchanged": len(day) - advances - declines,
        "advance_decline_ratio": round(advances / declines, 2) if declines else None,
        "above_sma20": _share(_above("sma20")),
        "above_sma50": _share(_above("sma50")),
        "above_sma200": _share(_above("sma200")),
        "new_52w_highs": new_highs,
        "new_52w_lows": new_lows,
        "above_vwap": {
            "available": False,
            "reason": ("VWAP is an intraday measure and this app stores daily bars. Not "
                       "approximated — a daily proxy would be a different statistic wearing "
                       "the same name."),
        },
        "benchmark": snap["benchmark"],
        "coverage": snap["coverage"],
        "quotes_live": snap["quotes_live"],
        "market_open": nse.get("market_open"),
        "computed_at": snap["computed_at"],
    }


async def setups(kind: str, index: str | None = None, limit: int = 40,
                 fresh: bool = False) -> dict:
    """The tradable shortlist for one mode, priced net of real costs."""
    if kind not in SETUP_KINDS:
        raise M.ScreenerError(f"unknown setup kind {kind!r}; expected one of {SETUP_KINDS}")

    index = index or M.DEFAULT_INDEX
    snap, scan = await asyncio.gather(
        M.universe_snapshot(index, fresh=fresh),
        patterns.scan(index, fresh=fresh),
    )
    hits_by_sym: dict[str, list[dict]] = {}
    for h in scan["rows"]:
        hits_by_sym.setdefault(h["symbol"], []).append(h)

    horizon = {"intraday": "1d", "swing": "1m", "breakout": "1w"}[kind]
    sector_board = sectors.roll_up(snap, horizon)
    sector_index = {s["sector"]: s for s in sector_board["sectors"]}
    bench = snap["benchmark"]["returns"].get(horizon)

    qualified, rejected = [], 0
    for row in snap["rows"]:
        passes, why_not = plans.gate(row, kind)
        if not passes:
            rejected += 1
            continue
        plan = {"intraday": plans.intraday_plan,
                "swing": plans.swing_plan,
                "breakout": plans.breakout_plan}[kind](row)
        if plan is None:
            rejected += 1
            continue

        hits = hits_by_sym.get(row["symbol"], [])
        plan["confirming_patterns"] = plans.confirming(plan, hits)
        plan["worth_taking"] = bool(
            plan.get("net_rr") is not None and plan["net_rr"] >= plans.MIN_RR and plan["tradable"])

        sec = sector_index.get(row["sector"]) or {}
        ret = row["returns"].get(horizon)
        from app.services.screener import reasons as R
        metrics = {**row, "rs_index": H.relative_strength(ret, bench),
                   "rs_sector": H.relative_strength(ret, sec.get("return_pct"))}
        stack = R.build(
            metrics,
            sector_ctx={"sector": row["sector"], "return_pct": sec.get("return_pct"),
                        "rank": sec.get("rank"), "of": sector_board["count"]} if sec else None,
            fundamentals=row.get("_fund"),
        )

        qualified.append({
            "symbol": row["symbol"],
            "name": row.get("name"),
            "sector": row["sector"],
            "ltp": row["ltp"],
            "return_pct": ret,
            "volume_x": row["volume_x"],
            "rs_index": _r(metrics["rs_index"]),
            "sector_return_pct": sec.get("return_pct"),
            "plan": plan,
            "why": R.chips(stack),
            "why_summary": R.summarise(row["symbol"], ret, stack, narrative_available=False),
            "character": R.classify(stack),
            "patterns": [{"pattern": h["pattern"], "state": h["state"],
                          "timeframe": h["timeframe"]} for h in hits[:3]],
        })

    # Rank by net reward-to-risk, then by the strength of the move behind it. Untradable
    # plans sink but stay visible.
    qualified.sort(key=lambda q: (
        0 if q["plan"]["worth_taking"] else 1,
        -(q["plan"].get("net_rr") or 0),
        -(q["return_pct"] or 0),
    ))

    worth = sum(1 for q in qualified if q["plan"]["worth_taking"])
    return {
        "kind": kind,
        "index": snap["index"],
        "horizon": horizon,
        "universe": len(snap["rows"]),
        "qualified": len(qualified),
        "worth_taking": worth,
        "rejected": rejected,
        "capital_per_trade": plans.PER_TRADE_CAPITAL,
        "note": ("Reward-to-risk is NET of the real Angel One schedule for this mode "
                 "(intraday vs delivery). Rows with worth_taking=false are shown, not "
                 "hidden — 'no setups today' and 'today's setups do not clear their costs' "
                 "are different facts."),
        "rows": qualified[:limit],
    }


def _r(v, nd: int = 2):
    return round(v, nd) if v is not None else None


async def sources(index: str | None = None) -> dict:
    """Per-feed honesty for the Sources tab.

    This tab exists so a silent data failure reads as a data failure. Without it, an Angel
    outage or an NSE block looks identical to a quiet market — the tables just come back
    thin — and that ambiguity is how a screener starts lying without anyone changing a line
    of code.
    """
    from app.services.angel_client import angel_client

    index = index or M.DEFAULT_INDEX
    try:
        snap = await M.universe_snapshot(index)
        universe_ok, universe_err = True, None
        coverage = snap["coverage"]
        quotes_live = snap["quotes_live"]
        bench = snap["benchmark"]
    except M.ScreenerError as exc:
        universe_ok, universe_err = False, exc.detail
        coverage, quotes_live, bench = {}, False, {}

    return {
        "index": index,
        "feeds": [
            {
                "name": "Angel One",
                "role": "primary — live LTP",
                "ok": bool(angel_client.configured() and quotes_live),
                "detail": ("live quotes flowing" if quotes_live else
                           "configured but no quotes returned this cycle — rows fall back "
                           "to their last stored close"
                           if angel_client.configured() else "not configured"),
            },
            {
                "name": "Stored daily bars",
                "role": "spine — every momentum, sector and pattern number",
                "ok": universe_ok,
                "detail": universe_err or (
                    f"{coverage.get('1d', {}).get('with_history', 0)} symbols with history; "
                    f"6-month coverage {coverage.get('6m', {}).get('pct', 0)}%"),
                "coverage": coverage,
            },
            {
                "name": f"Benchmark ({bench.get('symbol', 'NIFTY')})",
                "role": "relative strength",
                "ok": bool(bench.get("available")),
                "detail": ("benchmark bars present" if bench.get("available") else
                           "no benchmark bars stored — relative-strength columns read as "
                           "unavailable rather than zero"),
            },
            {
                "name": "NSE",
                "role": "enrichment — breadth, gainers, delivery %",
                "ok": any(v.get("ok") for v in nse_breadth.last_status().values()) or None,
                "detail": ("NSE blocks many datacentre IP ranges. Endpoint results below "
                           "reflect the last attempt from THIS host."),
                "endpoints": nse_breadth.last_status(),
            },
            {
                "name": "Chartink",
                "role": "secondary idea feed (delayed)",
                "ok": chartink.ENABLED,
                "detail": ("enabled — free tier is 30-45 min delayed"
                           if chartink.ENABLED else "disabled (SCREENER_CHARTINK_ENABLED=0)"),
                "verified": chartink.status()["verified"],
            },
            {
                "name": "Yahoo fundamentals",
                "role": "corroborating reasons only",
                "ok": None,
                "detail": "refreshed daily by the existing stock_fundamentals job",
            },
            {
                "name": "AI narrative",
                "role": "tier-3 reasons (news, filings)",
                "ok": False,
                "detail": ("ANTHROPIC_API_KEY not set — news is not checked, and no "
                           "narrative is invented in its place"),
            },
        ],
        "checked_at": _now().isoformat(),
    }


async def persist_snapshot(index: str | None = None) -> dict:
    """Store the day's momentum and sector boards so history survives a restart."""
    index = index or M.DEFAULT_INDEX
    snap = await M.universe_snapshot(index, fresh=True)
    day = datetime.now(H.IST).date().isoformat()
    ts = _now()

    mom = {
        "_id": f"{index}:{day}",
        "date": day, "ts": ts, "index": index,
        "universe": len(snap["rows"]),
        "benchmark": snap["benchmark"],
        # Strip the private close series before storing — it is a compute aid, not history.
        "rows": [{k: v for k, v in r.items() if not k.startswith("_")} for r in snap["rows"]],
    }
    await screener_momentum_collection.replace_one({"_id": mom["_id"]}, mom, upsert=True)

    sec = sectors.all_horizons(snap)
    sec_doc = {
        "_id": f"{index}:{day}",
        "date": day, "ts": ts, "index": index,
        "count": sec["count"], "sectors": sec["sectors"], "benchmark": sec["benchmark"],
    }
    await screener_sectors_collection.replace_one({"_id": sec_doc["_id"]}, sec_doc, upsert=True)

    logger.info("screener snapshot stored: %s stocks, %s sectors (%s)",
                len(snap["rows"]), sec["count"], day)
    return {"date": day, "index": index, "stocks": len(snap["rows"]), "sectors": sec["count"]}


async def refresh_all(index: str | None = None) -> dict:
    """Force a full recompute — what POST /api/screener/refresh and the scheduler call."""
    index = index or M.DEFAULT_INDEX
    started = time.monotonic()
    snap_result, pattern_result, nse_result = await asyncio.gather(
        persist_snapshot(index),
        patterns.persist(index),
        nse_breadth.snapshot(persist=True),
        return_exceptions=True,
    )

    def _outcome(r, label):
        if isinstance(r, Exception):
            logger.warning("screener refresh: %s failed (%s)", label, r)
            return {"ok": False, "error": f"{type(r).__name__}: {str(r)[:160]}"}
        return {"ok": True, **(r if isinstance(r, dict) else {})}

    return {
        "elapsed_s": round(time.monotonic() - started, 1),
        "momentum": _outcome(snap_result, "momentum snapshot"),
        "patterns": _outcome(pattern_result, "pattern scan"),
        # NSE returns a large body; only its health matters in a refresh receipt.
        "nse": ({"ok": nse_result.get("ok"), "endpoints": nse_result.get("endpoints")}
                if isinstance(nse_result, dict) else _outcome(nse_result, "nse")),
    }
