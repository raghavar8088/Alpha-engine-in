"""The public surface of instrument search — one place the API and any desk can call.

Three ways in, deliberately kept separate rather than merged behind one clever endpoint:

  `search()`     you typed some letters and want the instrument you meant
  `trending()`   you typed nothing and want to know what is worth naming today
  `nl_search()`  you described what you want in English

The third one degrades into the first when no language model is reachable, and says so in
the payload rather than silently returning something narrower than you asked for.
"""

from __future__ import annotations

import logging

from . import enrich as E
from . import nlq
from .index import ensure_index

logger = logging.getLogger("instrument_search.service")

MODE_LEXICAL = "lexical"
MODE_NATURAL = "natural-language"
MODE_TRENDING = "trending"


async def _ready():
    idx = await ensure_index()
    await E.ensure_snapshot()
    return idx


async def search(query: str, limit: int = 12, include_untradable: bool = False,
                 debug: bool = False) -> dict:
    """Ranked instrument matches for typed text."""
    idx = await _ready()
    hits = idx.search(query, limit=limit, include_untradable=include_untradable)
    results = []
    for rec, hit in hits:
        doc = E.enrich(rec, hit)
        if not debug:
            doc.pop("score", None)
        results.append(doc)
    return {
        "mode": MODE_LEXICAL,
        "query": query,
        "results": results,
        "count": len(results),
        "universe": idx.size,
        "as_of": E.snapshot_date(),
    }


async def trending(limit: int = 12, sort: str = "1d") -> dict:
    """The zero-query state: what is actually moving today, straight from the screener.

    This is what turns an empty search box from a dead end into the answer to "what should
    I even name?" — which, on a desk whose whole premise is that YOU supply the trending
    stocks, is the more useful question."""
    idx = await _ready()
    rows = [r for r in _snapshot_rows() if isinstance((r.get("returns") or {}).get(sort),
                                                      (int, float))]
    rows.sort(key=lambda r: r["returns"][sort], reverse=True)

    out = []
    for r in rows[:limit]:
        rec = idx.get(r.get("symbol", ""))
        if rec is None:
            continue
        doc = E.enrich(rec)
        doc["why"] = _why_trending(r)
        out.append(doc)
    return {
        "mode": MODE_TRENDING,
        "sort": sort,
        "results": out,
        "count": len(out),
        "as_of": E.snapshot_date(),
        "note": "Ranked from the daily screener snapshot, not a live scan — the date "
                "above is the session it describes.",
    }


def _snapshot_rows() -> list[dict]:
    return E.all_rows()


def _why_trending(r: dict) -> list[str]:
    """A sentence or two on WHY this name is on the list. Facts only, no adjectives."""
    out: list[str] = []
    ret = r.get("returns") or {}
    parts = [f"{w} {ret[w]:+.1f}%" for w in ("1d", "1w", "1m", "6m")
             if isinstance(ret.get(w), (int, float))]
    if parts:
        out.append("Returns " + ", ".join(parts) + ".")
    vx = r.get("volume_x")
    if isinstance(vx, (int, float)):
        out.append(f"Volume {vx:.1f}x its average.")
    streak = r.get("up_streak")
    if isinstance(streak, (int, float)) and streak >= 2:
        out.append(f"{int(streak)} up sessions in a row.")
    ath = r.get("pct_from_ath")
    if isinstance(ath, (int, float)):
        out.append(f"{abs(ath):.1f}% below its all-time high."
                   if ath < 0 else "At an all-time high.")
    if r.get("breakout"):
        out.append(f"Breakout: {r['breakout']}.")
    return out


async def nl_search(query: str, limit: int = 20) -> dict:
    """English -> filter -> deterministic execution. The filter is always returned."""
    idx = await _ready()
    sectors = {r.sector for r in idx.records.values() if r.sector}
    flt, note = await nlq.parse(query, sectors)

    if flt is None:
        fallback = await search(query, limit=limit)
        fallback["mode"] = MODE_LEXICAL
        fallback["nl_available"] = False
        fallback["nl_note"] = (f"Natural-language search is off ({note}), so this was "
                               "matched as plain text instead.")
        return fallback

    rows = nlq.apply_filter(_snapshot_rows(), flt,
                            index_of=lambda s: (idx.get(s).indices if idx.get(s) else ()))
    results = []
    for r in rows[:limit]:
        rec = idx.get(r.get("symbol", ""))
        if rec is None:
            continue
        doc = E.enrich(rec)
        doc["why"] = _why_trending(r)
        results.append(doc)

    return {
        "mode": MODE_NATURAL,
        "query": query,
        "nl_available": True,
        "nl_note": note,
        "filter": flt,
        "filter_english": nlq.describe(flt),
        "results": results,
        "count": len(results),
        "as_of": E.snapshot_date(),
        "note": "The model only translated your words into the filter shown above. The "
                "filter was then run by ordinary code over the daily screener snapshot.",
    }


async def resolve(symbol: str) -> dict | None:
    """One symbol, fully enriched — what the basket calls before adding."""
    idx = await _ready()
    rec = idx.get(symbol)
    return E.enrich(rec) if rec else None


async def stats() -> dict:
    idx = await _ready()
    snap = await E.ensure_snapshot()
    return {
        "instruments": idx.size,
        "tradable": sum(1 for r in idx.records.values() if r.tradable),
        "with_clean_name": sum(1 for r in idx.records.values() if r.clean_name),
        "with_daily_bars": sum(1 for r in idx.records.values() if not r.no_bars),
        "aliases": len(idx.aliases),
        "aliases_dropped": idx.dropped_aliases,
        "trending_pool": len(idx.trending_top),
        "snapshot": snap,
        "natural_language": nlq.status(),
    }


__all__ = ["search", "trending", "nl_search", "resolve", "stats",
           "MODE_LEXICAL", "MODE_NATURAL", "MODE_TRENDING"]
