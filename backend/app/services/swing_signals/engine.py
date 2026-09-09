"""Scan the universe, publish the signals that survive, and hand them to the desk.

The scan is deliberately transparent about what it REJECTED. A screener that shows only
its hits is unfalsifiable — you cannot tell a strict filter from a broken one, because
both produce a short list. Every rejection is counted by reason and the counts are
returned, so a day with no signals can be read as "nothing set up" rather than "something
is wrong with the scanner".
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.core.db import stock_universe_collection
from app.core.db import swing_signal_positions_collection as POS
from app.core.db import swing_signals_collection as SIGNALS
from app.services.screener import horizons as H
from app.services.swing_signals import desk
from app.services.swing_signals.research import evaluate
from app.services.swing_signals.signals import build

logger = logging.getLogger("swing_signals")

UNIVERSE_INDEX = "nifty500"
BENCHMARK = "NIFTY 50"
MAX_NEW_PER_DAY = 12       # a desk that opens 60 positions a day is not selecting
SCAN_TTL = 900.0

_cache: dict[str, tuple[float, dict]] = {}
_lock = asyncio.Lock()


def _today() -> str:
    return H.ist_date().isoformat()


async def _load_benchmark(bars_by_sym: dict) -> list:
    for key in (BENCHMARK, "NIFTY50", "NIFTY"):
        if bars_by_sym.get(key):
            return bars_by_sym[key]
    got = await H.load_daily_bars([BENCHMARK])
    return got.get(BENCHMARK) or []


def _scan_sync(universe, bars_by_sym, bench, today):
    """CPU-bound body: research every name, build a call for the ones that pass."""
    signals, rejects = [], {}
    for symbol, name, sector in universe:
        bars = bars_by_sym.get(symbol) or []
        res = evaluate(symbol, bars, bench)
        if not res.ok:
            key = (res.reject or "unknown").split("—")[0].strip()[:70]
            rejects[key] = rejects.get(key, 0) + 1
            continue
        sig, why = build(res, bars, name, sector, today)
        if sig is None:
            key = (why or "unbuildable").split("—")[0].strip()[:70]
            rejects[key] = rejects.get(key, 0) + 1
            continue
        signals.append(sig.to_dict())
    signals.sort(key=lambda s: (-s["score"], -s["rr2"]))
    return signals, rejects


async def scan(fresh: bool = False) -> dict:
    key = f"swing:{UNIVERSE_INDEX}"
    if not fresh:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < SCAN_TTL:
            return hit[1]

    async with _lock:
        hit = _cache.get(key)
        if hit and not fresh and time.monotonic() - hit[0] < SCAN_TTL:
            return hit[1]

        started = time.monotonic()
        docs = [d async for d in stock_universe_collection.find(
            {"indices": UNIVERSE_INDEX}, {"_id": 0, "symbol": 1, "name": 1, "sector": 1})]
        universe = [(d["symbol"], d.get("name"), d.get("sector")) for d in docs]
        symbols = [u[0] for u in universe]

        bars_by_sym = await H.load_daily_bars(symbols)
        bench = await _load_benchmark(bars_by_sym)
        today = _today()
        signals, rejects = await asyncio.to_thread(
            _scan_sync, universe, bars_by_sym, bench, today)

        result = {
            "as_of": today,
            "index": UNIVERSE_INDEX,
            "scanned": len(universe),
            "with_bars": sum(1 for s in symbols if bars_by_sym.get(s)),
            "benchmark": BENCHMARK if bench else None,
            "signals": signals,
            "signal_count": len(signals),
            "rejected": sum(rejects.values()),
            "reject_reasons": sorted(rejects.items(), key=lambda kv: -kv[1])[:12],
            "elapsed_s": round(time.monotonic() - started, 1),
            "note": ("Every name is judged on seven independent conditions and must pass at "
                     "least five of them plus a confluence score. Rejections are counted by "
                     "reason so a quiet day is distinguishable from a broken scanner."),
        }
        _cache[key] = (time.monotonic(), result)
        return result


async def publish(fresh: bool = True) -> dict:
    """Run the scan, store today's signals, and open a ₹1 lakh paper position on each.

    Idempotent per (symbol, day): re-running does not double-publish or double-trade."""
    res = await scan(fresh=fresh)
    today = res["as_of"]
    stored = taken = skipped = 0
    errors: list[str] = []

    for sig in res["signals"][:MAX_NEW_PER_DAY]:
        try:
            existing = await SIGNALS.find_one(
                {"symbol": sig["symbol"], "generated_on": today}, {"_id": 1})
            if existing:
                skipped += 1
                continue
            await SIGNALS.insert_one({**sig, "published_at": datetime.now(timezone.utc)})
            stored += 1
            pos = await desk.take(sig)
            if pos:
                taken += 1
            else:
                # The desk declining is a fact about the signal, recorded on it. Otherwise
                # the board shows a call the desk never actually took.
                await SIGNALS.update_one(
                    {"symbol": sig["symbol"], "generated_on": today},
                    {"$set": {"desk": "DECLINED — already open, or capital exhausted"}})
        except Exception as exc:      # noqa: BLE001 — one bad name must not stop the run
            errors.append(f"{sig['symbol']}: {str(exc)[:120]}")
            logger.warning("swing publish failed for %s", sig["symbol"], exc_info=True)

    return {"as_of": today, "generated": len(res["signals"]),
            "published": stored, "positions_opened": taken,
            "already_published": skipped, "errors": errors,
            "capped_at": MAX_NEW_PER_DAY, "scan": {k: res[k] for k in
                                                   ("scanned", "rejected", "elapsed_s")}}


async def run_daily() -> dict:
    """Publish today's signals, then mark and resolve every open position."""
    pub = await publish(fresh=True)
    open_syms = [p["symbol"] async for p in POS.find({"status": "OPEN"}, {"symbol": 1})]
    bars = await H.load_daily_bars(open_syms) if open_syms else {}
    marks = await desk.mark_and_exit(bars, pub["as_of"])
    return {**pub, "desk": marks}


async def board(horizon: str | None = None, conviction: str | None = None,
                limit: int = 60) -> dict:
    """Today's published signals, newest day first — the card list the page renders."""
    q: dict = {}
    if horizon:
        q["horizon"] = horizon
    if conviction:
        q["conviction"] = conviction.upper()
    rows = [r async for r in SIGNALS.find(q, {"_id": 0})
            .sort([("generated_on", -1), ("score", -1)]).limit(limit)]
    return {"count": len(rows), "signals": rows,
            "filters": {"horizon": horizon, "conviction": conviction}}
