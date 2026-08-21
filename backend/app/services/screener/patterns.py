"""Chart-pattern scan over the equity universe, on DAILY and WEEKLY candles.

DETECTORS ARE REUSED, NOT REWRITTEN. `commodity_patterns` already implements all of them —
head & shoulders, double top/bottom (the "W"), triple tops/bottoms, the three triangles,
wedges, flags, pennants, cup & handle, rounding, diamond, broadening, ten candlestick
patterns and sixteen structure rules — as geometry over detected swing pivots, returning a
`PatternSignal` with entry, target, stop, confidence and a rationale saying which
measurements fired. That is exactly the shape a screener needs. Writing a third copy of
this library (a second already exists in `nifty_scalp_strategies`) would be the worst
possible outcome.

TRIGGERED VERSUS FORMING — and how FORMING is detected honestly.

The library deliberately fires only once price has CLOSED THROUGH the pattern's own
boundary. That is correct for a trading engine, and it is the reason these patterns avoid
being imaginary: an unbroken shape is not a signal. But a screener has a second, legitimate
job — showing shapes that are complete and waiting, so a trader can set an alert at the
level instead of finding out about it a week late.

The dishonest way to do that is to relax the detectors. This does not. Instead it PROBES:
it appends one synthetic bar that closes just beyond the recent range and re-runs the
unmodified detector. If the pattern then fires, the shape is genuinely complete and only
the break is missing — and the probe price is, by construction, the exact level the break
would happen at. So FORMING rows carry a real trigger level rather than a vague "watch
this". If the detector still does not fire, the shape is not there and nothing is reported.

The probe cannot distort the shape it is testing: `pivots()` uses a 3-bar right-hand
lookahead, so the last three bars can never be swing points, and one appended bar therefore
cannot invent a pivot or move an existing one.

COST. Pure Python over stored bars — no API calls at all. It is CPU-bound, so it runs in a
worker thread and its result is cached for the trading day; the scheduler recomputes it
after the close.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from app.core.db import screener_patterns_collection, stock_universe_collection
from app.services.screener.horizons import Bar
from app.services.commodity_patterns import (
    FAMILY_LABELS,
    INTRADAY_ONLY,
    PatternSpec,
    TEMPLATES,
    evaluate,
)
from app.services.screener import horizons as H

logger = logging.getLogger("screener.patterns")

TIMEFRAMES = ["1d", "1w"]
TIMEFRAME_LABELS = {"1d": "Daily", "1w": "Weekly"}

# Templates that read a SESSION's internal structure. A daily bar has no opening range and
# no intra-session gap to fade, so instantiating these on 1d/1w would silently compare
# yesterday to the day before and call it something it is not.
SESSION_ONLY = set(INTRADAY_ONLY) | {"gap_fade"}

# Only the geometric chart patterns get the FORMING probe. A candlestick pattern is a
# statement about the last one to three bars — there is no "forming engulfing candle", it
# either happened or it did not — and probing one would manufacture a signal rather than
# find one.
PROBE_FAMILIES = {"chart"}
PROBE_EDGE = 0.001         # break the extreme by 0.1% to count as "closed through"

SCAN_TTL = float(os.getenv("SCREENER_PATTERN_TTL", "3600"))
MIN_BARS_WEEKLY = 45       # below this the longer shapes cannot form at all

_cache: dict[str, tuple[float, dict]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _spec(key: str, timeframe: str) -> PatternSpec:
    family, label, _fn, params, min_bars = TEMPLATES[key]
    return PatternSpec(
        strategy_id=f"scr_{key}_{timeframe}",
        name=f"{label} · {TIMEFRAME_LABELS[timeframe]}",
        family=family, template=key, timeframe=timeframe,
        rationale=f"{label} evaluated on {TIMEFRAME_LABELS[timeframe].lower()} equity bars.",
        params=dict(params), min_bars=min_bars,
    )


SPECS: dict[str, list[PatternSpec]] = {
    tf: [_spec(k, tf) for k in TEMPLATES if k not in SESSION_ONLY] for tf in TIMEFRAMES
}

# Never assert an exact catalog size here. An exact-count assert on a template catalog once
# crash-looped the whole backend the day someone added templates.
assert len(SPECS["1d"]) >= 20, "pattern catalog looks empty — check the commodity import"


def _probe_bar(bars: list[Bar], direction: str, window: int) -> Bar | None:
    """A synthetic bar that closes just beyond the extreme of the last `window` bars.

    THE WINDOW MUST COVER THE PATTERN'S OWN STRUCTURE, which is why it is a parameter
    rather than a constant. A double bottom's neckline is the peak BETWEEN its two lows,
    and on a 70-bar shape that peak can sit thirty bars back — probing only past the last
    20 bars would clear a level the pattern does not care about while leaving its real
    boundary untouched, so the shape would never be found. Passing each spec's own
    `min_bars` means every pattern is probed just past the structure it actually reads.
    """
    if len(bars) < 5:
        return None
    span = bars[-min(window, len(bars)):]
    last = bars[-1]
    if direction == "up":
        level = max(b.high for b in span) * (1 + PROBE_EDGE)
        return Bar(last.ts, last.close, level, min(last.close, level * 0.995), level, last.volume)
    level = min(b.low for b in span) * (1 - PROBE_EDGE)
    return Bar(last.ts, last.close, max(last.close, level * 1.005), level, level, last.volume)


def _scan_symbol(symbol: str, sector: str | None, bars: list[Bar],
                 timeframe: str) -> list[dict]:
    """Every pattern hit for one symbol on one timeframe."""
    hits: list[dict] = []
    if len(bars) < 40:
        return hits

    last_date = H.ist_date(bars[-1].ts).isoformat()
    probe_cache: dict[tuple[str, int], Bar | None] = {}

    for spec in SPECS[timeframe]:
        sig = evaluate(spec, bars)
        if sig is not None:
            hits.append(_row(symbol, sector, spec, sig, "TRIGGERED", timeframe,
                             last_date, trigger_level=None))
            continue

        family = TEMPLATES[spec.template][0]
        if family not in PROBE_FAMILIES:
            continue

        for direction in ("up", "down"):
            key = (direction, spec.min_bars)
            if key not in probe_cache:
                probe_cache[key] = _probe_bar(bars, direction, spec.min_bars)
            probe = probe_cache[key]
            if probe is None:
                continue
            probed = evaluate(spec, bars + [probe])
            if probed is None:
                continue
            # The probe must have produced a signal in the direction it probed — an
            # up-probe yielding a SELL means the shape resolved the other way and the
            # probe told us nothing about it.
            if (direction == "up") != (probed.side == "BUY"):
                continue
            hits.append(_row(symbol, sector, spec, probed, "FORMING", timeframe,
                             last_date, trigger_level=probe.close))
            break

    return hits


def _row(symbol: str, sector: str | None, spec: PatternSpec, sig, state: str,
         timeframe: str, as_of: str, trigger_level: float | None) -> dict:
    family = TEMPLATES[spec.template][0]
    return {
        "symbol": symbol,
        "sector": sector,
        "pattern": sig.pattern,
        "template": spec.template,
        "family": family,
        "family_label": FAMILY_LABELS.get(family, family),
        "timeframe": timeframe,
        "timeframe_label": TIMEFRAME_LABELS[timeframe],
        "state": state,
        "side": sig.side,
        "direction": "bullish" if sig.side == "BUY" else "bearish",
        "entry": round(sig.entry, 2),
        "target": round(sig.target, 2),
        "stoploss": round(sig.stoploss, 2),
        "trigger_level": round(trigger_level, 2) if trigger_level is not None else None,
        "confidence": round(sig.confidence, 2),
        "rationale": sig.rationale,
        "as_of": as_of,
        "reward_risk": _rr(sig.entry, sig.target, sig.stoploss),
    }


def _rr(entry: float, target: float, stop: float) -> float | None:
    risk = abs(entry - stop)
    return round(abs(target - entry) / risk, 2) if risk > 0 else None


def _scan_sync(universe: list[tuple[str, str | None]],
               bars_by_sym: dict[str, list[Bar]]) -> list[dict]:
    """The CPU-bound body, run in a worker thread so it never blocks the event loop."""
    out: list[dict] = []
    for symbol, sector in universe:
        daily = bars_by_sym.get(symbol) or []
        if len(daily) < 40:
            continue
        out.extend(_scan_symbol(symbol, sector, daily, "1d"))
        weekly = H.to_weekly(daily)
        if len(weekly) >= MIN_BARS_WEEKLY:
            out.extend(_scan_symbol(symbol, sector, weekly, "1w"))
    return out


async def scan(index: str | None = None, fresh: bool = False) -> dict:
    """Scan the universe on both timeframes. Cached for the trading day."""
    from app.services.screener.momentum import DEFAULT_INDEX

    index = index or DEFAULT_INDEX
    key = f"patterns:{index}"
    now = time.monotonic()
    if not fresh:
        hit = _cache.get(key)
        if hit and now - hit[0] < SCAN_TTL:
            return hit[1]

    docs = [d async for d in stock_universe_collection.find(
        {"indices": index}, {"_id": 0, "symbol": 1, "sector": 1})]
    universe = [(d["symbol"], d.get("sector") or "Unclassified") for d in docs]
    symbols = [s for s, _ in universe]

    bars_by_sym = await H.load_daily_bars(symbols, fresh=fresh)
    started = time.monotonic()
    hits = await asyncio.to_thread(_scan_sync, universe, bars_by_sym)
    elapsed = time.monotonic() - started

    weekly_ready = sum(1 for s in symbols
                       if len(H.to_weekly(bars_by_sym.get(s) or [])) >= MIN_BARS_WEEKLY)

    result = {
        "index": index,
        "scanned": len(universe),
        "hits": len(hits),
        "triggered": sum(1 for h in hits if h["state"] == "TRIGGERED"),
        "forming": sum(1 for h in hits if h["state"] == "FORMING"),
        "rows": hits,
        "elapsed_s": round(elapsed, 1),
        "weekly_coverage": {
            "symbols": len(symbols),
            "with_enough_weekly_bars": weekly_ready,
            "pct": round(weekly_ready / len(symbols) * 100, 1) if symbols else 0.0,
            "note": (f"A weekly bar needs {MIN_BARS_WEEKLY} weeks of history before the "
                     f"longer shapes (cup & handle, rounding) can form. The daily backfill "
                     f"currently stored decides this — deepen it to widen weekly coverage."),
        },
        "computed_at": time.time(),
    }
    _cache[key] = (now, result)
    return result


async def board(index: str | None = None, timeframe: str | None = None,
                pattern: str | None = None, family: str | None = None,
                state: str | None = None, direction: str | None = None,
                sector: str | None = None, limit: int = 300,
                fresh: bool = False) -> dict:
    """The filtered pattern table. TRIGGERED always sorts above FORMING."""
    res = await scan(index, fresh=fresh)
    rows = res["rows"]

    if timeframe:
        rows = [r for r in rows if r["timeframe"] == timeframe]
    if pattern:
        rows = [r for r in rows if r["template"] == pattern]
    if family:
        rows = [r for r in rows if r["family"] == family]
    if state:
        rows = [r for r in rows if r["state"] == state.upper()]
    if direction:
        rows = [r for r in rows if r["direction"] == direction]
    if sector:
        rows = [r for r in rows if r["sector"] == sector]

    rows = sorted(rows, key=lambda r: (
        0 if r["state"] == "TRIGGERED" else 1,
        -(r["confidence"] or 0),
        -(r["reward_risk"] or 0),
    ))

    return {
        "index": res["index"],
        "scanned": res["scanned"],
        "count": len(rows),
        "triggered": sum(1 for r in rows if r["state"] == "TRIGGERED"),
        "forming": sum(1 for r in rows if r["state"] == "FORMING"),
        "weekly_coverage": res["weekly_coverage"],
        "elapsed_s": res["elapsed_s"],
        "filters": {"timeframe": timeframe, "pattern": pattern, "family": family,
                    "state": state, "direction": direction, "sector": sector},
        "catalog": catalog(),
        "rows": rows[:limit],
    }


async def for_symbol(symbol: str, index: str | None = None, fresh: bool = False) -> list[dict]:
    """Every pattern hit for one stock, both timeframes — for the row drawer."""
    res = await scan(index, fresh=fresh)
    sym = symbol.strip().upper()
    rows = [r for r in res["rows"] if r["symbol"] == sym]
    return sorted(rows, key=lambda r: (0 if r["state"] == "TRIGGERED" else 1,
                                       -(r["confidence"] or 0)))


def catalog() -> list[dict]:
    """The selectable pattern list for the UI filter."""
    return [
        {"key": k, "label": v[1], "family": v[0],
         "family_label": FAMILY_LABELS.get(v[0], v[0]),
         "probeable": v[0] in PROBE_FAMILIES}
        for k, v in sorted(TEMPLATES.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        if k not in SESSION_ONLY
    ]


async def persist(index: str | None = None) -> dict:
    """Store today's scan so the history survives a restart and the UI has something to
    read before the first live scan completes."""
    res = await scan(index, fresh=True)
    day = datetime.now(H.IST).date().isoformat()
    doc = {
        "_id": f"{res['index']}:{day}",
        "date": day, "ts": _now(), "index": res["index"],
        "scanned": res["scanned"], "hits": res["hits"],
        "triggered": res["triggered"], "forming": res["forming"],
        "rows": res["rows"],
    }
    await screener_patterns_collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    logger.info("screener patterns: stored %s hits for %s (%s)",
                res["hits"], res["index"], day)
    return {"stored": res["hits"], "date": day, "index": res["index"],
            "triggered": res["triggered"], "forming": res["forming"]}
