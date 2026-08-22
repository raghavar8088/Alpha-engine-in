"""Enrichment — what turns a match into something you can decide on.

A ticker and a company name are not enough to answer the only question that matters when
you are naming stocks for a trading desk: *would this desk actually trade it, and is it
moving?* Both answers already exist in this app and were simply never shown at the point of
choosing.

WHERE THE DATA COMES FROM
--------------------------
`screener_momentum` recomputes a full row per Nifty 500 symbol every day and it is far
richer than it looks — `ltp`, returns over 1d/1w/1m/6m, `turnover`, `volume_x`,
`pct_from_ath`, `pct_from_52w_high`, the SMA stack, `atr14`, `up_streak` and `sessions`.
So enrichment is one dictionary lookup, not five joins, and it costs nothing per keystroke.

THE VERDICT IS THE FEATURE
---------------------------
`tradability()` runs the same turnover floor the desk's own liquidity pillar vetoes on, and
reads the same bar coverage the strategies need. It is deliberately the SAME constant
(`evidence.MIN_TURNOVER`), not a copy — if the desk's floor moves, the search's warning
moves with it. Otherwise the search would promise something the engine then refuses, which
is exactly the silent failure this upgrade exists to remove.

Nothing here is invented. A symbol outside the Nifty 500 has no screener row, so its
liquidity is reported as UNKNOWN rather than assumed good or assumed bad.
"""

from __future__ import annotations

import logging
import os
import time

from app.core.db import screener_momentum_collection, stock_highs_collection

logger = logging.getLogger("instrument_search.enrich")

SNAPSHOT_TTL_S = int(os.getenv("SEARCH_SNAPSHOT_TTL_S", "900"))   # 15 minutes

_snapshot: dict[str, dict] = {}
_highs: dict[str, dict] = {}
_snapshot_at: float = 0.0
_snapshot_date: str | None = None


async def ensure_snapshot(force: bool = False) -> dict:
    """The latest screener snapshot, cached. Returns a small status dict."""
    global _snapshot, _highs, _snapshot_at, _snapshot_date
    if _snapshot and not force and (time.monotonic() - _snapshot_at) < SNAPSHOT_TTL_S:
        return {"symbols": len(_snapshot), "date": _snapshot_date, "cached": True}

    doc = await screener_momentum_collection.find_one({}, sort=[("ts", -1)])
    rows = (doc or {}).get("rows") or []
    _snapshot = {(r.get("symbol") or "").upper(): r for r in rows if r.get("symbol")}
    _snapshot_date = (doc or {}).get("date")

    highs: dict[str, dict] = {}
    async for h in stock_highs_collection.find(
            {}, {"symbol": 1, "all_time_high": 1, "all_time_high_date": 1, "sessions": 1}):
        highs[(h.get("symbol") or "").upper()] = h
    _highs = highs
    _snapshot_at = time.monotonic()
    return {"symbols": len(_snapshot), "date": _snapshot_date,
            "highs": len(_highs), "cached": False}


def snapshot_date() -> str | None:
    return _snapshot_date


def market_row(symbol: str) -> dict | None:
    return _snapshot.get((symbol or "").upper())


def all_rows() -> list[dict]:
    """Every screener row in the cached snapshot — what the filters run over."""
    return list(_snapshot.values())


def tradability(rec, row: dict | None) -> dict:
    """Would the desk trade this name — and if not, why not, in words.

    Three independent reasons it might refuse, reported separately because they need
    different fixes: no broker token (nothing can price it), no bars (a data gap the
    backfill can close), and too little turnover (nothing can fix that)."""
    from app.services.trending_stocks.evidence import MIN_TURNOVER

    blockers: list[str] = []
    warnings: list[str] = []

    if not rec.tradable:
        blockers.append("No broker token on file — the desk cannot fetch candles or a "
                        "quote for it.")
    if rec.no_bars:
        blockers.append("No daily bars yet. Adding it starts a backfill; until that "
                        "finishes every timeframe is a data gap, not a verdict.")

    turnover = (row or {}).get("turnover")
    if isinstance(turnover, (int, float)):
        if turnover < MIN_TURNOVER:
            blockers.append(
                f"Median turnover ₹{turnover/1e7:.2f} crore is below the "
                f"₹{MIN_TURNOVER/1e7:.0f} crore floor — the liquidity pillar would veto "
                "every signal on it.")
    elif rec.liquidity_unknown:
        warnings.append("Outside the Nifty 500, so turnover is unmeasured here — the "
                        "liquidity pillar will decide at scan time.")

    sessions = (row or {}).get("sessions")
    if isinstance(sessions, (int, float)) and sessions < 250:
        warnings.append(f"Only {int(sessions)} sessions of history — the slower "
                        "timeframes need more before they can fire.")

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "verdict": ("tradable" if not blockers else "blocked"),
    }


def enrich(rec, hit=None) -> dict:
    """One search result, ready for the palette."""
    row = market_row(rec.symbol)
    high = _highs.get(rec.symbol)
    returns = (row or {}).get("returns") or {}
    doc = rec.as_doc()
    doc.update({
        "ltp": (row or {}).get("ltp"),
        "returns": {k: returns.get(k) for k in ("1d", "1w", "1m", "6m")} if returns else None,
        "turnover": (row or {}).get("turnover"),
        "volume_x": (row or {}).get("volume_x"),
        "pct_from_ath": (row or {}).get("pct_from_ath"),
        "pct_from_52w_high": (row or {}).get("pct_from_52w_high"),
        "up_streak": (row or {}).get("up_streak"),
        "breakout": (row or {}).get("breakout"),
        "sessions": (row or {}).get("sessions") or (high or {}).get("sessions"),
        "all_time_high": (high or {}).get("all_time_high"),
        "all_time_high_date": (high or {}).get("all_time_high_date"),
        "above_sma": _sma_stack(row),
        "coverage": list(rec.timeframes),
        "coverage_note": _coverage_note(rec),
        "tradability": tradability(rec, row),
        "as_of": _snapshot_date,
    })
    if hit is not None:
        doc["score"] = round(hit.score, 1)
        doc["matched_on"] = hit.matched_on
        # Exposed so the UI can group blocked names below tradable ones without
        # re-deriving the rule from the individual flags.
        doc["demotion"] = hit.demotion
        doc["why"] = hit.reasons
    return doc


def _sma_stack(row: dict | None) -> dict | None:
    """Where price sits against its own moving averages — the cheapest read on trend."""
    if not row:
        return None
    ltp = row.get("ltp")
    if not isinstance(ltp, (int, float)):
        return None
    out = {}
    for k, label in (("sma20", "20"), ("sma50", "50"), ("sma200", "200")):
        v = row.get(k)
        out[label] = bool(ltp > v) if isinstance(v, (int, float)) and v else None
    return out


def _coverage_note(rec) -> str:
    have = len(rec.timeframes)
    if have == 0:
        return "no bars stored yet"
    if have >= 5:
        return f"all {have} broker intervals stored (30m/45m/4h are resampled from these)"
    return f"{have} of 5 broker intervals stored — the rest are a data gap"


__all__ = ["ensure_snapshot", "enrich", "tradability", "market_row", "all_rows",
           "snapshot_date", "SNAPSHOT_TTL_S"]
