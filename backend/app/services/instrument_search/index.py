"""The in-process instrument index — built once, answered in microseconds.

WHY NOT LET THE DATABASE DO IT
-------------------------------
Three reasons, all measured rather than assumed:

* The old approach interpolated the query straight into a Mongo `$regex`. On production a
  query of `(` returned `OperationFailure: missing closing parenthesis` — a 500 — and
  `.*` executed as a wildcard. Building regexes from user input is the bug, not the
  implementation of it.
* Mongo here is self-hosted (8.0 in Docker), so Atlas Search / `$search` does not exist.
  `$text` does, but it is whole-word only: no prefix, no fuzzy, and no control over
  ranking — and ranking was the actual problem.
* The whole universe is 2,457 instruments. That is a few hundred kilobytes. A linear scan
  with a real scoring function beats any index round-trip, and lets the ranking be exactly
  what we choose and explain.

WHAT IT JOINS
-------------
The instrument master alone is not enough — its names are truncated at ~25 characters
(`BALKRISHNA PAPER MILLS L`). So the index also folds in:

  stock_universe      clean names, sector, index membership   (Nifty 500)
  screener_momentum   turnover, and today's strongest movers  (refreshed daily)
  bars                which symbols have daily history at all

REBUILT, NOT LIVE
-----------------
Built at startup and refreshed on a timer. A search never touches Mongo, so a slow database
cannot make typing feel slow. The cost of staleness is bounded and stated: a symbol listed
today appears after the next refresh.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from app.core.db import (
    bars_collection,
    instruments_collection,
    screener_momentum_collection,
    stock_universe_collection,
)

from .aliases import CURATED, normalise, squash, tokens, trigrams
from .scoring import Hit, score, score_fuzzy

logger = logging.getLogger("instrument_search")

REFRESH_SECONDS = int(os.getenv("SEARCH_INDEX_REFRESH_S", str(6 * 3600)))
# Mirrors evidence.MIN_TURNOVER so the search's warning and the desk's veto agree. Imported
# lazily rather than at module import to keep this package free of desk dependencies.
TRENDING_TOP_N = int(os.getenv("SEARCH_TRENDING_TOP_N", "50"))
MAX_QUERY_LEN = 64

# The intervals the broker actually serves; everything else is resampled.
NATIVE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "1d")


@dataclass(slots=True)
class Record:
    symbol: str
    broker_name: str = ""
    clean_name: str = ""
    sector: str = ""
    indices: tuple[str, ...] = ()
    tightest_index: str = ""
    angel_token: str | None = None
    security_id: str | None = None
    exchange_segment: str = "NSE_EQ"
    asset_class: str = "EQUITY"
    lot_size: int = 1
    tradable: bool = True
    no_bars: bool = False
    illiquid: bool = False
    liquidity_unknown: bool = True
    turnover: float | None = None
    # Which of the broker's native intervals actually have bars stored. 30m/45m/4h are
    # resampled from these, so they are not tracked separately.
    timeframes: tuple[str, ...] = ()
    # precomputed for scoring
    symbol_squashed: str = ""
    name_squashed: str = ""
    name_tokens: list[str] = field(default_factory=list)
    symbol_trigrams: set[str] = field(default_factory=set)
    name_trigrams: set[str] = field(default_factory=set)

    @property
    def display_name(self) -> str:
        """The clean index name when we have it, the broker's truncated one otherwise."""
        return self.clean_name or self.broker_name or self.symbol

    def as_doc(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.display_name,
            "broker_name": self.broker_name, "sector": self.sector or None,
            "indices": list(self.indices), "index_label": _index_label(self.tightest_index),
            "security_id": self.security_id, "exchange_segment": self.exchange_segment,
            "angel_token": self.angel_token, "asset_class": self.asset_class,
            "lot_size": self.lot_size, "tradable": self.tradable,
        }


_INDEX_LABELS = {"nifty50": "Nifty 50", "nifty100": "Nifty 100",
                 "nifty250": "Nifty Midcap 250", "nifty500": "Nifty 500"}


def _index_label(key: str) -> str | None:
    return _INDEX_LABELS.get(key or "")


class InstrumentIndex:
    def __init__(self) -> None:
        self.records: dict[str, Record] = {}
        self.aliases: dict[str, str] = {}
        self.trigram_postings: dict[str, set[str]] = {}
        self.trending_top: frozenset[str] = frozenset()
        self.built_at: float = 0.0
        self.dropped_aliases: list[str] = []

    @property
    def size(self) -> int:
        return len(self.records)

    @property
    def stale(self) -> bool:
        return (time.monotonic() - self.built_at) > REFRESH_SECONDS

    # ---- build ------------------------------------------------------------------

    async def build(self) -> dict:
        started = time.monotonic()
        records: dict[str, Record] = {}

        async for d in instruments_collection.find(
                {"asset_class": {"$in": ["EQUITY", "ETF"]}},
                {"symbol": 1, "name": 1, "security_id": 1, "exchange_segment": 1,
                 "angel_token": 1, "asset_class": 1, "lot_size": 1}):
            sym = (d.get("symbol") or "").upper()
            if not sym or sym in records:
                continue
            records[sym] = Record(
                symbol=sym, broker_name=d.get("name") or "",
                security_id=str(d["security_id"]) if d.get("security_id") is not None else None,
                exchange_segment=d.get("exchange_segment") or "NSE_EQ",
                angel_token=str(d["angel_token"]) if d.get("angel_token") else None,
                asset_class=d.get("asset_class") or "EQUITY",
                lot_size=int(d.get("lot_size") or 1),
                tradable=bool(d.get("angel_token")),
            )

        # Clean names, sector and index membership for the Nifty 500.
        async for u in stock_universe_collection.find(
                {}, {"symbol": 1, "name": 1, "sector": 1, "indices": 1, "tightest_index": 1}):
            rec = records.get((u.get("symbol") or "").upper())
            if rec is None:
                continue
            rec.clean_name = u.get("name") or ""
            rec.sector = u.get("sector") or ""
            rec.indices = tuple(u.get("indices") or ())
            rec.tightest_index = u.get("tightest_index") or ""

        # Turnover and today's movers, from the screener's own daily snapshot.
        from app.services.trending_stocks.evidence import MIN_TURNOVER
        snap = await screener_momentum_collection.find_one({}, sort=[("ts", -1)])
        rows = (snap or {}).get("rows") or []
        ranked: list[tuple[float, str]] = []
        for r in rows:
            rec = records.get((r.get("symbol") or "").upper())
            if rec is None:
                continue
            t = r.get("turnover")
            if isinstance(t, (int, float)):
                rec.turnover = float(t)
                rec.liquidity_unknown = False
                rec.illiquid = float(t) < MIN_TURNOVER
            ret = (r.get("returns") or {}).get("1m")
            if isinstance(ret, (int, float)):
                ranked.append((float(ret), rec.symbol))
        ranked.sort(reverse=True)
        self.trending_top = frozenset(s for _, s in ranked[:TRENDING_TOP_N])

        # Which of the five native intervals each symbol actually has. Five `distinct`
        # calls, not a group-by over the whole bars collection — that would scan millions
        # of rows to answer a question about a few hundred symbols.
        per_tf: dict[str, set[str]] = {}
        for tf in NATIVE_TIMEFRAMES:
            per_tf[tf] = set(await bars_collection.distinct("symbol", {"timeframe": tf}))
        for rec in records.values():
            rec.timeframes = tuple(tf for tf in NATIVE_TIMEFRAMES if rec.symbol in per_tf[tf])
            rec.no_bars = "1d" not in rec.timeframes

        # Precompute everything the scorer needs, once.
        postings: dict[str, set[str]] = {}
        for rec in records.values():
            rec.symbol_squashed = squash(rec.symbol)
            name = rec.display_name
            rec.name_squashed = squash(name)
            rec.name_tokens = tokens(name)
            rec.symbol_trigrams = trigrams(rec.symbol)
            rec.name_trigrams = trigrams(name)
            for tri in rec.symbol_trigrams | rec.name_trigrams:
                postings.setdefault(tri, set()).add(rec.symbol)

        # Curated aliases, VALIDATED. One that no longer resolves is dropped and named —
        # a map that silently points at a delisted ticker is worse than no map.
        aliases: dict[str, str] = {}
        dropped: list[str] = []
        for phrase, target in CURATED.items():
            if target in records:
                aliases[normalise(phrase)] = target
            else:
                dropped.append(f"{phrase} -> {target}")
        if dropped:
            logger.warning("[instrument_search] %d curated aliases dropped (target not in "
                           "the master): %s", len(dropped), ", ".join(dropped[:8]))

        self.records = records
        self.aliases = aliases
        self.trigram_postings = postings
        self.dropped_aliases = dropped
        self.built_at = time.monotonic()

        stats = {
            "instruments": len(records),
            "tradable": sum(1 for r in records.values() if r.tradable),
            "with_clean_name": sum(1 for r in records.values() if r.clean_name),
            "with_daily_bars": sum(1 for r in records.values() if not r.no_bars),
            "with_intraday_bars": sum(1 for r in records.values()
                                      if set(r.timeframes) - {"1d"}),
            "illiquid_flagged": sum(1 for r in records.values() if r.illiquid),
            "aliases": len(aliases), "aliases_dropped": len(dropped),
            "trending_top": len(self.trending_top),
            "trigrams": len(postings),
            "build_ms": round((time.monotonic() - started) * 1000, 1),
        }
        logger.info("[instrument_search] index built: %s", stats)
        return stats

    # ---- query ------------------------------------------------------------------

    def search(self, query: str, limit: int = 12, include_untradable: bool = False,
               ) -> list[tuple[Record, Hit]]:
        q_raw = (query or "").strip()[:MAX_QUERY_LEN]
        if not q_raw:
            return []
        q_norm = normalise(q_raw)
        q_squash = squash(q_raw)
        q_tokens = tokens(q_raw)
        if not q_squash:
            return []
        alias_symbol = self.aliases.get(q_norm)

        hits: list[tuple[Record, Hit]] = []
        for rec in self.records.values():
            if not include_untradable and not rec.tradable:
                continue
            h = score(rec, q_norm, q_squash, q_tokens, alias_symbol, self.trending_top)
            if h.score > 0:
                hits.append((rec, h))

        # Fuzzy only when the literal pass found little — a typo-corrected guess must
        # never displace something the user typed correctly.
        if len(hits) < 3:
            hits.extend(self._fuzzy(q_raw, include_untradable,
                                    already={r.symbol for r, _ in hits}))

        # Demotion first: a name the desk cannot trade never outranks one it can,
        # whatever its text score. Then score, then the shorter ticker.
        hits.sort(key=lambda rh: (rh[1].demotion, -rh[1].score,
                                  len(rh[0].symbol), rh[0].symbol))
        return hits[:limit]

    def _fuzzy(self, q_raw: str, include_untradable: bool,
               already: set[str]) -> list[tuple[Record, Hit]]:
        q_tri = trigrams(q_raw)
        if not q_tri:
            return []
        # Candidates from the trigram postings rather than the whole universe: only
        # instruments sharing at least one trigram can possibly clear the floor.
        counts: dict[str, int] = {}
        for tri in q_tri:
            for sym in self.trigram_postings.get(tri, ()):
                counts[sym] = counts.get(sym, 0) + 1
        out: list[tuple[Record, Hit]] = []
        for sym, _n in sorted(counts.items(), key=lambda kv: -kv[1])[:400]:
            if sym in already:
                continue
            rec = self.records.get(sym)
            if rec is None or (not include_untradable and not rec.tradable):
                continue
            h = score_fuzzy(rec, q_tri, self.trending_top)
            if h.score > 0:
                out.append((rec, h))
        return out

    def get(self, symbol: str) -> Record | None:
        return self.records.get((symbol or "").upper())


_INDEX = InstrumentIndex()
_LOCK = asyncio.Lock()


async def ensure_index(force: bool = False) -> InstrumentIndex:
    """The index, built if it is missing or stale. Safe under concurrent callers."""
    if _INDEX.size and not _INDEX.stale and not force:
        return _INDEX
    async with _LOCK:
        if _INDEX.size and not _INDEX.stale and not force:
            return _INDEX
        await _INDEX.build()
    return _INDEX


def current_index() -> InstrumentIndex:
    return _INDEX


__all__ = ["InstrumentIndex", "Record", "ensure_index", "current_index",
           "REFRESH_SECONDS", "MAX_QUERY_LEN", "NATIVE_TIMEFRAMES"]
