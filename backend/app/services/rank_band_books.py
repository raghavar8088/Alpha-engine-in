"""Commodity Trading: four rank-band paper accounts (12 Nov 2026) - Top 5, Top 5-10, Top 10-15, Top 15-20.

The owner asked for four paper accounts on Commodity Trading, one per band of its Rank (the "Strategy records" board:
each strategy's multi-factor rank on its honest record), with Rs 10 lakh for each strategy.

WHAT A BOOK IS
- Five strategies, each with its OWN Rs 10,00,000 inside the book (Rs 50 lakh a book). A strategy's losses never
  shrink another's money: every strategy is replayed as its own account, by the same plan_book the Top-10 books use.
- Like the desk itself (commodity_engine.MAX_POSITIONS_PER_STRATEGY = 1), each strategy holds one position at a time.
- It copies the desk's own trades of those strategies exactly as the Commodity Top-10 books do (top10_books): whole
  lots of the trade's own contract on the broker's measured margin (`_commodity_parent`), in at the touch, out at the
  desk's exit, Angel One's MCX charges on the account's own lots (`_futures_pnl`). A signal whose one lot needs more
  margin than the strategy's free cash is skipped and counted.
- Copies start at the first cycle after this went live; nothing is back-filled.

THE TWENTY ARE FROZEN as ranked when picked (PICKED_AT); they are not re-picked as ranks move. The board's #9 and #11
are retired 1-minute strategies (no entries since 5 Oct 2026: commodity_engine retired 1m and 5m), so each band holds
the next LIVE strategies in rank order. Every pick keeps its board rank, score, trades, net bp a trade and net P&L
there.

Paper only: nothing here places an order.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.db import db
from app.services import top10_books as t10
from app.services.book_reset import naive_utc
from app.services.live_intraday_mirror import pending_since, plan_book

logger = logging.getLogger(__name__)

POSITIONS = db["rank_band_positions"]
SCORES = db["rank_band_scores"]
STATE = db["rank_band_state"]
EQUITY = db["rank_band_equity"]
SOURCE_TAG = "rank_band"
DESK_KEY = "commodity"
PER_STRATEGY = float(os.getenv("RANK_BAND_PER_STRATEGY", "1000000"))      # Rs 10 lakh each
SLOTS_PER_STRATEGY = 1                                                     # as the desk
ENABLED = os.getenv("RANK_BAND_BOOKS_ENABLED", "1").lower() not in ("0", "false", "")
LOOKBACK = t10.LOOKBACK
SKIP_REASONS = ("full", "symbol_held", "price_above_cap", "no_cash")

PICKED_AT = "2026-11-12T22:43:00+05:30"      # /api/strategy-rank/commodity, 313 ranked strategies

# (strategy_id, board rank, score, trades, net bp a trade, name, net P&L on the desk) at the pick
BANDS: dict[str, tuple[str, tuple[t10.Pick, ...]]] = {
    "top5": ("Top 5 Paper Trading", t10._picks([
        ("cmd_0246", 1, 85.4, 44, 19.23, "Heikin Ashi Flip · 1h", 27530.84),
        ("cmd_0238", 2, 84.0, 48, 25.25, "Hammer / Shooting Star · 1h", 35899.83),
        ("cmd_0201", 3, 81.4, 58, 29.96, "Donchian Breakout (fast) · 45m", 165492.65),
        ("cmd_0149", 4, 81.4, 50, 18.79, "Inside Bar Breakout · 30m", 88941.26),
        ("cmd_0250", 5, 81.0, 33, 29.33, "Bollinger %B Extreme · 1h", 93993.94),
    ])),
    "top5_10": ("Top 5-10 Paper Trading", t10._picks([
        ("cmd_0226", 6, 80.6, 38, 35.52, "Triple Top / Bottom · 1h", 138640.32),
        ("cmd_0202", 7, 78.1, 25, 86.32, "Donchian Breakout (slow) · 45m", 209120.79),
        ("cmd_0206", 8, 77.5, 66, 20.17, "Round Number Break · 45m", 125788.8),
        ("cmd_0122", 10, 76.9, 57, 11.01, "Fibonacci 61.8% Bounce · 15m", 55292.31),
        ("cmd_0087", 12, 75.7, 145, 2.2, "Double Top / Bottom · 15m", 15340.28),
    ])),
    "top10_15": ("Top 10-15 Paper Trading", t10._picks([
        ("cmd_0199", 13, 75.1, 23, 25.19, "Pin Bar at Extreme · 45m", 53233.01),
        ("cmd_0212", 14, 74.4, 63, 4.23, "Opening Range Breakout · 45m", 12652.18),
        ("cmd_0195", 15, 74.3, 41, 6.24, "Inside Bar Breakout · 45m", 23469.02),
        ("cmd_0162", 16, 74.1, 28, 9.43, "TTM Squeeze · 30m", 27384.18),
        ("cmd_0259", 17, 73.7, 23, 39.97, "Pivot R1/S1 Break · 1h", 93507.98),
    ])),
    "top15_20": ("Top 15-20 Paper Trading", t10._picks([
        ("cmd_0136", 18, 72.8, 21, 16.36, "Descending Triangle · 30m", 30324.26),
        ("cmd_0261", 19, 72.5, 19, 39.2, "Trend Pullback to EMA · 1h", 70895.22),
        ("cmd_0178", 20, 72.3, 36, 13.44, "Head & Shoulders · 45m", 27569.55),
        ("cmd_0098", 21, 71.8, 24, 26.63, "Broadening Formation · 15m", 56557.73),
        ("cmd_0165", 22, 69.7, 31, 3.34, "HH/HL Structure Shift · 30m", 3166.21),
    ])),
}
BOOKS = list(BANDS)
BOOK_LABEL = {k: v[0] for k, v in BANDS.items()}
BOARD = "the Commodity Trading Rank on its honest record (313 strategies with closed trades)"
NOTES = (
    "Each strategy has its own ₹10,00,000 in the book and holds one position at a time, as on the desk; a "
    "strategy's losses never reduce another's money.",
    "The board's #9 (Pin Bar at Extreme · 1m) and #11 (Doji Reversal · 1m) are retired 1-minute strategies that "
    "no longer trade, so the bands hold the next live strategies in rank order.",
    "Whole lots on the broker's margin, each copy priced on its own contract, in at the touch and out at the desk's "
    "exit, with Angel One's MCX charges. A signal whose one lot needs more margin than the strategy's free cash is "
    "skipped and counted.",
)


def normalize_book(book: str | None) -> str:
    return book if book in BANDS else BOOKS[0]


def picks(book: str) -> tuple[t10.Pick, ...]:
    return BANDS[normalize_book(book)][1]


def book_capital(book: str) -> float:
    return PER_STRATEGY * len(picks(book))


def _desk(book: str) -> t10.Desk:
    """The commodity desk's adapters, with this band's five as its roster (so copies carry their names)."""
    return dataclasses.replace(t10.DESKS[DESK_KEY], picks=picks(book), max_open=SLOTS_PER_STRATEGY,
                               board=BOARD, notes=NOTES)


# -- state ------------------------------------------------------------------------------------


async def _start(book: str) -> datetime:
    """When the book began copying - one start for its five, set on the first cycle."""
    key = f"start:{book}"
    doc = await STATE.find_one({"_id": key})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    await STATE.update_one({"_id": key}, {"$setOnInsert": {"started_at": t10._now(), "book": book}}, upsert=True)
    doc = await STATE.find_one({"_id": key})
    return naive_utc(doc["started_at"])


def _skip_doc(book: str, key: str, day: str) -> str:
    return f"skipped:{book}:{key}:{day}"


async def _decided(book: str, key: str, parents: list[dict]) -> set[str]:
    ids = [p["position_id"] for p in parents]
    out: set[str] = set()
    async for r in POSITIONS.find({"book": book, "parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
        out.add(r["parent_position_id"])
    days = sorted({p.get("opened_on") for p in parents if p.get("opened_on")})
    if days:
        async for s in STATE.find({"_id": {"$in": [_skip_doc(book, key, day) for day in days]}}, {"ids": 1}):
            out.update(s.get("ids") or [])
    return out


async def _totals(book: str, key: str) -> tuple[float, float]:
    """The strategy's own realised P&L and the capital its open position ties up."""
    realized = deployed = 0.0
    async for r in POSITIONS.find({"book": book, "key": key}, {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if r.get("status") == "OPEN":
            deployed += r.get("capital_deployed") or 0.0
        else:
            realized += r.get("realized_pnl") or 0.0
    return realized, deployed


async def _closed_after(book: str, key: str, t0: datetime | None) -> list[dict]:
    if t0 is None:
        return []
    return [r async for r in POSITIONS.find(
        {"book": book, "key": key, "status": "CLOSED", "closed_at": {"$gt": t0}},
        {"symbol": 1, "capital_deployed": 1, "realized_pnl": 1, "opened_at": 1, "closed_at": 1})]


# -- the copy ------------------------------------------------------------------------------------


async def _sync_strategy(d: t10.Desk, book: str, pick: t10.Pick, entries: bool) -> dict:
    """One strategy's Rs 10 lakh account inside the book: the desk's trades of that strategy, replayed in time order."""
    floor = max(await _start(book), naive_utc(t10._now()) - LOOKBACK)
    open_rows = [r async for r in POSITIONS.find({"book": book, "key": pick.key, "status": "OPEN"})]
    pointed = [r["parent_position_id"] for r in open_rows if r.get("parent_position_id")]
    parents = [p for p in await d.load(floor, {pick.key}, pointed)
               if p.get("opened_at") is not None and (p["opened_at"] >= floor or p["position_id"] in pointed)]
    parents.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    realized, deployed = await _totals(book, pick.key)
    decided = await _decided(book, pick.key, parents) if entries else set()
    t0 = pending_since(parents, decided, open_rows, SOURCE_TAG) if entries else None
    closed_rows = await _closed_after(book, pick.key, t0) if entries else []
    plan = plan_book(capital=PER_STRATEGY, realized=realized, deployed=deployed, open_rows=open_rows,
                     parents=parents, decided=decided, breaker_tripped=False, entries=entries,
                     max_open=SLOTS_PER_STRATEGY, net_fn=t10._net_fn(d), source_tag=SOURCE_TAG,
                     closed_rows=closed_rows)

    n = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
    for c in plan["closes"]:
        res = await POSITIONS.update_one({"_id": c["row"]["_id"], "status": "OPEN"},
                                         {"$set": t10._close_fields(c["parent"], c)})
        n["closed"] += res.modified_count
    for o in plan["opens"]:
        p = o["parent"]
        doc = t10._row(d, book, p, o["qty"], o["spend"])
        doc.update({"source": SOURCE_TAG, "allocation": PER_STRATEGY})
        if o["close"] is not None:
            doc.update(t10._close_fields(p, o["close"]))
        try:
            await POSITIONS.insert_one(doc)
        except DuplicateKeyError:
            continue
        n["opened"] += 1
        n["closed"] += 1 if o["close"] is not None else 0
    per: dict[str, int] = {}
    ids_by_day: dict[str, list[str]] = {}
    for s in plan["skips"]:
        p = s["parent"]
        per[s["reason"]] = per.get(s["reason"], 0) + 1
        ids_by_day.setdefault(p.get("opened_on") or "", []).append(p["position_id"])
        n["skipped"] += 1
    for day, ids in ids_by_day.items():
        await STATE.update_one({"_id": _skip_doc(book, pick.key, day)},
                               {"$addToSet": {"ids": {"$each": ids}},
                                "$set": {"book": book, "key": pick.key, "day": day}}, upsert=True)
    if per:
        await SCORES.update_one({"book": book, "key": pick.key},
                                {"$inc": {f"skipped.{k}": v for k, v in per.items()},
                                 "$set": {"updated_at": t10._now()}}, upsert=True)

    by_id = {p["position_id"]: p for p in parents}
    closed_now = {c["row"]["_id"] for c in plan["closes"]}
    for r in open_rows:
        if r["_id"] in closed_now:
            continue
        p = by_id.get(r.get("parent_position_id"))
        if not p or p.get("status") != "OPEN":
            continue
        u = d.mark(p, int(r["qty"]))
        if u is None:
            continue
        await POSITIONS.update_one({"_id": r["_id"], "status": "OPEN"},
                                   {"$set": {"ltp": p.get("px_ltp"), "unrealized_pnl": u, "updated_at": t10._now()}})
        n["marked"] += 1
    return n


_lock = asyncio.Lock()
_indexed = False


async def sync(entries: bool = True, only: str | None = None) -> dict:
    """Copy the desk into every band's five strategy accounts once."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    out: dict = {}
    async with _lock:
        for book in BOOKS:
            if only and book != only:
                continue
            d = _desk(book)
            for pick in d.picks:
                try:
                    out[f"{book}:{pick.key}"] = await _sync_strategy(d, book, pick, entries)
                except Exception as exc:  # noqa: BLE001 - one strategy's bad row must not stop the rest
                    logger.warning("[rank_band_books] %s %s failed: %s", book, pick.key, exc, exc_info=True)
                    out[f"{book}:{pick.key}"] = {"error": str(exc)[:200]}
            try:
                await _snapshot(book)
            except Exception:  # noqa: BLE001
                logger.warning("[rank_band_books] snapshot %s failed", book, exc_info=True)
    return out


async def _snapshot(book: str) -> None:
    s = await summary(book)
    last = await EQUITY.find_one({"book": book}, sort=[("ts", -1)])
    stale = last is None or (naive_utc(t10._now()) - naive_utc(last["ts"])) > timedelta(minutes=30)
    if stale or abs((last or {}).get("equity", 0.0) - s["equity"]) > 0.005:
        await EQUITY.insert_one({"ts": t10._now(), "book": book, "equity": s["equity"],
                                 "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"],
                                 "open_positions": s["open_positions"]})


async def loop() -> None:
    """Every minute in market hours (NSE day, then MCX's evening), every ten minutes otherwise - as the Top-10 books."""
    await asyncio.sleep(35)
    while True:
        if ENABLED:
            try:
                await sync(entries=True)
            except Exception:  # noqa: BLE001
                logger.warning("[rank_band_books] cycle failed", exc_info=True)
        await asyncio.sleep(60 if t10._market_minutes() else 600)


# -- read models: the same shapes as top10_books, plus each strategy's own account ---------------


async def summary(book: str) -> dict:
    book = normalize_book(book)
    d = _desk(book)
    cap = book_capital(book)
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = wins = 0
    async for r in POSITIONS.find({"book": book}):
        if r.get("status") == "OPEN":
            open_n += 1
            deployed += r.get("capital_deployed") or 0.0
            unrealized += r.get("unrealized_pnl") or 0.0
        else:
            closed_n += 1
            v = r.get("realized_pnl") or 0.0
            realized += v
            wins += 1 if v > 0 else 0
            fees += r.get("fees") or 0.0
            gross += r.get("gross_pnl") or 0.0
    skipped = {k: 0 for k in SKIP_REASONS}
    async for s in SCORES.find({"book": book}, {"skipped": 1}):
        for k, v in (s.get("skipped") or {}).items():
            if k in skipped:
                skipped[k] += int(v or 0)
    start = await STATE.find_one({"_id": f"start:{book}"})
    started = start.get("started_at") if start else None
    equity = cap + realized + unrealized
    band = [p.rank for p in d.picks]
    return {
        "desk": DESK_KEY, "desk_label": d.label, "book": book, "books": BOOKS, "label": BOOK_LABEL[book],
        "book_labels": BOOK_LABEL, "mode": "paper", "enabled": ENABLED,
        "instrument": d.instrument, "cost_basis": d.cost_basis, "board": d.board, "notes": list(d.notes),
        "picked_at": PICKED_AT, "roster": list(d.roster), "strategies": len(d.picks),
        "board_ranks": band, "per_strategy_capital": PER_STRATEGY,
        "max_open_positions": SLOTS_PER_STRATEGY * len(d.picks), "positions_per_strategy": SLOTS_PER_STRATEGY,
        "position_cap": PER_STRATEGY,
        "desk_capital": cap, "equity": round(equity, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "deployed": round(deployed, 2), "available_cash": round(cap + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "roi_pct": round((equity - cap) / cap * 100, 4) if cap else 0.0, "skipped": skipped,
        "copying_since": (naive_utc(started).replace(tzinfo=timezone.utc).isoformat() if started else None),
    }


async def leaderboard(book: str) -> list[dict]:
    """The five, in rank order, each with its own Rs 10 lakh account in this book and where it stood when picked."""
    book = normalize_book(book)
    ps = picks(book)
    rec: dict[str, dict] = {p.key: {"trades": 0, "wins": 0, "net": 0.0, "gross": 0.0, "fees": 0.0, "open": 0,
                                    "unrealized": 0.0, "deployed": 0.0} for p in ps}
    async for r in POSITIONS.find({"book": book}):
        x = rec.get(r.get("key"))
        if x is None:
            continue
        if r.get("status") == "OPEN":
            x["open"] += 1
            x["unrealized"] += r.get("unrealized_pnl") or 0.0
            x["deployed"] += r.get("capital_deployed") or 0.0
            continue
        v = r.get("realized_pnl") or 0.0
        x["trades"] += 1
        x["wins"] += 1 if v > 0 else 0
        x["net"] += v
        x["gross"] += r.get("gross_pnl") or 0.0
        x["fees"] += r.get("fees") or 0.0
    sk: dict[str, dict] = {}
    async for s in SCORES.find({"book": book}, {"key": 1, "skipped": 1}):
        sk[s["key"]] = {k: int((s.get("skipped") or {}).get(k, 0)) for k in SKIP_REASONS}
    rows = []
    for p in ps:
        x = rec[p.key]
        skipped = sk.get(p.key) or {k: 0 for k in SKIP_REASONS}
        equity = PER_STRATEGY + x["net"] + x["unrealized"]
        rows.append({
            "key": p.key, "strategy_id": p.key, "name": p.name,
            "picked_rank": p.rank, "picked_score": p.score, "picked_trades": p.trades,
            "picked_bp": p.bp, "picked_net_pnl": p.net,
            "trades": x["trades"], "wins": x["wins"], "win_rate": round(x["wins"] / x["trades"], 4) if x["trades"] else 0.0,
            "net_pnl": round(x["net"], 2), "gross_pnl": round(x["gross"], 2), "fees": round(x["fees"], 2),
            "unrealized_pnl": round(x["unrealized"], 2), "deployed": round(x["deployed"], 2),
            "allocation": PER_STRATEGY, "equity": round(equity, 2),
            "roi_pct": round((equity - PER_STRATEGY) / PER_STRATEGY * 100, 4) if PER_STRATEGY else 0.0,
            "open_positions": x["open"], "skipped": skipped, "skipped_total": sum(skipped.values()),
        })
    return rows


async def positions(book: str, status: str = "OPEN", limit: int = 200) -> list[dict]:
    book = normalize_book(book)
    q: dict = {"book": book}
    if status.upper() != "ALL":
        q["status"] = status.upper()
    sort_key = "opened_at" if status.upper() == "OPEN" else "closed_at"
    return [t10._jsonable(r) async for r in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


def books() -> list[dict]:
    return [{"book": b, "label": BOOK_LABEL[b], "capital": book_capital(b), "per_strategy_capital": PER_STRATEGY,
             "picked_at": PICKED_AT,
             "picks": [{"key": p.key, "rank": p.rank, "score": p.score, "trades": p.trades, "bp": p.bp,
                        "name": p.name, "net": p.net} for p in picks(b)]} for b in BOOKS]


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await POSITIONS.create_index([("book", 1), ("parent_position_id", 1)], name="rb_parent_unique", unique=True)
        await POSITIONS.create_index([("book", 1), ("key", 1), ("status", 1)], name="rb_book_key_status")
        await SCORES.create_index([("book", 1), ("key", 1)], name="rb_score_key", unique=True)
        await EQUITY.create_index([("book", 1), ("ts", -1)], name="rb_equity_ts")
    except Exception:  # noqa: BLE001
        logger.warning("[rank_band_books] index creation skipped", exc_info=True)
