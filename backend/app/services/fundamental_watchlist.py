"""Named watchlists, and a paper book that asks whether the grades actually predict returns.

THE QUESTION THIS EXISTS TO ANSWER
The rest of this module grades companies. Grading is cheap; being right is not. So a
watchlist can be funded as a paper book — a fixed rupee amount in every name, bought at the
price on the day it was funded — and from then on each day's move is recorded per stock AND
aggregated by the grade the stock held. That turns "explosive fundamentals" from an opinion
into a line on a chart: if the explosive basket does not out-earn the average basket over
months, the scale is decorative and should be retuned.

EQUAL RUPEES, NOT EQUAL WEIGHTS OR EQUAL LOTS
Every stock gets the same rupee amount, so the comparison between tiers is a comparison of
the stocks and not of their market caps. Whole shares only, and the remainder is left as
cash rather than quietly rounded away — with Rs1,00,000 a share and a Rs1,154 stock, the
book holds 86 shares and Rs734 in cash, and the P&L says so.

THE BUY PRICE IS THE PRICE WHEN IT WAS FUNDED, AND IT IS NEVER REWRITTEN
A position records the live price at the moment it was added. Re-funding an existing book
does not re-price what is already in it — it only adds names that are new. Otherwise every
refresh would quietly reset the cost base and the book would report a permanent zero.

THE GRADE IS FROZEN AT ENTRY, AND ALSO TRACKED LIVE
`grade_key_at_entry` is what the tier aggregation uses, because the honest question is
"did the stocks I called explosive go up", not "did the stocks that are explosive today
happen to have gone up" — the second is survivorship dressed as a result. The current grade
is stored alongside so a drift between the two is visible.

DAILY MARKS ARE TAKEN AFTER THE CLOSE
A snapshot written mid-session would record a number that the closing auction then moves.
The daily series is written once, after 15:35 IST, and is idempotent per day, so running
the loop more often costs one indexed lookup and changes nothing.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.core.db import (
    fundamental_paper_equity_collection,
    fundamental_paper_positions_collection,
    fundamental_ratings_collection,
    fundamental_watchlists_collection,
    instruments_collection,
)
from app.services.screener_in import normalise_symbol, split_symbols
from app.services.stock_options import batched_ltp

logger = logging.getLogger("fundamental_watchlist")

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_PER_STOCK = 100000.0        # Rs 1 lakh a name
SNAPSHOT_AFTER = "15:35"            # IST, after the closing auction has settled


class WatchlistError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


# ── watchlists ───────────────────────────────────────────────────────────────────


async def save_watchlist(name: str, symbols_text: str) -> dict:
    """Create or replace a named list. Accepts pasted TradingView text too."""
    name = (name or "").strip()
    if not name:
        raise WatchlistError("Give the watchlist a name.")
    symbols = split_symbols(symbols_text)
    if not symbols:
        raise WatchlistError("No usable symbols in that list.")
    doc = {"_id": name, "name": name, "symbols": symbols,
           "count": len(symbols), "updated_at": _now()}
    await fundamental_watchlists_collection.replace_one({"_id": name}, doc, upsert=True)
    doc.pop("_id", None)
    return doc


async def watchlists() -> list[dict]:
    out = []
    async for d in fundamental_watchlists_collection.find({}).sort("updated_at", -1):
        d.pop("_id", None)
        out.append(d)
    return out


async def delete_watchlist(name: str) -> dict:
    r = await fundamental_watchlists_collection.delete_one({"_id": name})
    return {"deleted": r.deleted_count}


# ── prices ───────────────────────────────────────────────────────────────────────


async def _tokens(symbols: list[str]) -> dict[str, dict]:
    return {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1})}


async def live_prices(symbols: list[str]) -> dict[str, float]:
    """LTP per symbol from Angel, batched to its 50-token cap.

    A symbol with no Angel token simply has no price; the caller keeps the position and
    marks it at its last known price rather than dropping it from the book.
    """
    if not symbols:
        return {}
    toks = await _tokens(symbols)
    by_ex: dict[str, list[str]] = {}
    tok2sym: dict[str, str] = {}
    for sym, d in toks.items():
        t = str(d["angel_token"])
        by_ex.setdefault(d.get("angel_exchange") or "NSE", []).append(t)
        tok2sym[t] = sym
    raw = await batched_ltp(by_ex)
    return {tok2sym[t]: float(p) for t, p in raw.items() if t in tok2sym and p}


# ── the paper book ───────────────────────────────────────────────────────────────


async def fund(name: str, per_stock: float = DEFAULT_PER_STOCK) -> dict:
    """Open a position in every name on the list that does not already have one."""
    wl = await fundamental_watchlists_collection.find_one({"_id": name})
    if not wl:
        raise WatchlistError(f"No watchlist called '{name}'.")
    symbols = wl.get("symbols") or []

    existing = {d["symbol"] async for d in
                fundamental_paper_positions_collection.find({"book": name}, {"symbol": 1})}
    wanted = [s for s in symbols if s not in existing]
    if not wanted:
        return {"book": name, "opened": 0, "already_held": len(existing),
                "note": "Every name on this list is already in the book."}

    prices = await live_prices(wanted)
    ratings = {d["_id"]: d async for d in fundamental_ratings_collection.find(
        {"_id": {"$in": wanted}})}

    opened, skipped = 0, []
    for sym in wanted:
        px = prices.get(sym)
        if not px or px <= 0:
            skipped.append({"symbol": sym, "reason": "no live price from Angel One"})
            continue
        qty = int(per_stock // px)
        if qty < 1:
            skipped.append({"symbol": sym,
                            "reason": f"one share costs Rs{px:,.0f}, more than the "
                                      f"Rs{per_stock:,.0f} per name"})
            continue
        r = ratings.get(sym) or {}
        await fundamental_paper_positions_collection.replace_one(
            {"_id": f"{name}::{sym}"},
            {"_id": f"{name}::{sym}", "book": name, "symbol": sym,
             "name": r.get("name"), "qty": qty, "buy_price": round(px, 2),
             "invested": round(qty * px, 2),
             "cash_left": round(per_stock - qty * px, 2),
             "allocated": per_stock,
             # Frozen at entry — see the module docstring.
             "grade_key_at_entry": r.get("grade_key"),
             "grade_at_entry": r.get("grade"),
             "score_at_entry": r.get("score"),
             "results_grade_key_at_entry": r.get("results_grade_key"),
             "pnl_grade_key_at_entry": r.get("pnl_grade_key"),
             "sector": r.get("nse_sector") or r.get("sector"),
             "ltp": round(px, 2), "opened_on": _today_ist(), "opened_at": _now()},
            upsert=True)
        opened += 1

    return {"book": name, "opened": opened, "already_held": len(existing),
            "skipped": skipped, "per_stock": per_stock}


async def mark(name: str | None = None) -> dict:
    """Refresh LTP and unrealised P&L on every open position."""
    q = {"book": name} if name else {}
    rows = [d async for d in fundamental_paper_positions_collection.find(q)]
    if not rows:
        return {"marked": 0}
    prices = await live_prices(sorted({r["symbol"] for r in rows}))
    marked = 0
    for r in rows:
        px = prices.get(r["symbol"])
        if not px:
            continue
        await fundamental_paper_positions_collection.update_one(
            {"_id": r["_id"]},
            {"$set": {"ltp": round(px, 2),
                      "unrealized_pnl": round((px - r["buy_price"]) * r["qty"], 2),
                      "return_pct": round((px / r["buy_price"] - 1) * 100, 2),
                      "marked_at": _now()}})
        marked += 1
    return {"marked": marked, "priced": len(prices)}


def _tier_rows(rows: list[dict]) -> list[dict]:
    """Aggregate positions into one row per grade tier — the point of the whole book."""
    buckets: dict[str, dict] = {}
    for r in rows:
        key = r.get("grade_key_at_entry") or "unrated"
        b = buckets.setdefault(key, {"grade_key": key, "stocks": 0, "invested": 0.0,
                                     "value": 0.0, "pnl": 0.0, "winners": 0,
                                     "best": None, "worst": None,
                                     "grade": r.get("grade_at_entry")})
        ltp = r.get("ltp") or r["buy_price"]
        value = ltp * r["qty"]
        ret = (ltp / r["buy_price"] - 1) * 100
        b["stocks"] += 1
        b["invested"] += r["invested"]
        b["value"] += value
        b["pnl"] += value - r["invested"]
        b["winners"] += 1 if ret > 0 else 0
        if b["best"] is None or ret > b["best"]["return_pct"]:
            b["best"] = {"symbol": r["symbol"], "return_pct": round(ret, 2)}
        if b["worst"] is None or ret < b["worst"]["return_pct"]:
            b["worst"] = {"symbol": r["symbol"], "return_pct": round(ret, 2)}

    out = []
    for b in buckets.values():
        # The average of the per-stock returns, which is what "how did the explosive
        # stocks do" means — not the money-weighted return of the bucket, which would
        # let one expensive name speak for the tier.
        b["avg_return_pct"] = round(b["pnl"] / b["invested"] * 100, 2) if b["invested"] else 0.0
        b["win_rate"] = round(b["winners"] / b["stocks"] * 100, 1) if b["stocks"] else 0.0
        for k in ("invested", "value", "pnl"):
            b[k] = round(b[k], 2)
        out.append(b)
    return sorted(out, key=lambda x: -x["avg_return_pct"])


async def summary(name: str) -> dict:
    rows = [d async for d in fundamental_paper_positions_collection.find({"book": name})]
    for d in rows:
        d.pop("_id", None)
    if not rows:
        return {"book": name, "funded": False, "positions": [], "tiers": [],
                "note": "This list has not been funded as a paper book yet."}

    invested = sum(r["invested"] for r in rows)
    cash = sum(r.get("cash_left") or 0 for r in rows)
    value = sum((r.get("ltp") or r["buy_price"]) * r["qty"] for r in rows)
    for r in rows:
        ltp = r.get("ltp") or r["buy_price"]
        r["value"] = round(ltp * r["qty"], 2)
        r["unrealized_pnl"] = round(ltp * r["qty"] - r["invested"], 2)
        r["return_pct"] = round((ltp / r["buy_price"] - 1) * 100, 2)

    winners = sum(1 for r in rows if r["return_pct"] > 0)
    return {
        "book": name, "funded": True, "stocks": len(rows),
        "allocated": round(sum(r.get("allocated") or 0 for r in rows), 2),
        "invested": round(invested, 2), "cash_left": round(cash, 2),
        "value": round(value, 2), "pnl": round(value - invested, 2),
        "return_pct": round((value / invested - 1) * 100, 2) if invested else 0.0,
        "winners": winners, "losers": len(rows) - winners,
        "win_rate": round(winners / len(rows) * 100, 1) if rows else 0.0,
        "positions": sorted(rows, key=lambda r: -r["return_pct"]),
        "tiers": _tier_rows(rows),
        "marked_at": max((r.get("marked_at") for r in rows if r.get("marked_at")), default=None),
    }


# ── the daily series ─────────────────────────────────────────────────────────────


async def snapshot(name: str, force: bool = False) -> dict:
    """Write one row per day per book, with the per-tier numbers frozen into it."""
    day = _today_ist()
    if not force and await fundamental_paper_equity_collection.find_one(
            {"_id": f"{name}::{day}"}):
        return {"written": False, "reason": "already snapshotted today"}

    s = await summary(name)
    if not s.get("funded"):
        return {"written": False, "reason": "book not funded"}

    prev = await fundamental_paper_equity_collection.find_one(
        {"book": name, "session": {"$lt": day}}, sort=[("session", -1)])

    tiers = s["tiers"]
    prev_tiers = {t["grade_key"]: t for t in (prev or {}).get("tiers", [])}
    for t in tiers:
        # The DAY's move for this tier, against the same tier's value yesterday.
        p = prev_tiers.get(t["grade_key"])
        t["day_pnl"] = round(t["value"] - p["value"], 2) if p else None
        t["day_return_pct"] = (round((t["value"] / p["value"] - 1) * 100, 2)
                               if p and p.get("value") else None)

    doc = {
        "_id": f"{name}::{day}", "book": name, "session": day,
        "value": s["value"], "invested": s["invested"], "pnl": s["pnl"],
        "return_pct": s["return_pct"], "stocks": s["stocks"],
        "win_rate": s["win_rate"],
        "day_pnl": round(s["value"] - prev["value"], 2) if prev else None,
        "day_return_pct": (round((s["value"] / prev["value"] - 1) * 100, 2)
                           if prev and prev.get("value") else None),
        "tiers": tiers,
        "movers": {
            "best": s["positions"][0] if s["positions"] else None,
            "worst": s["positions"][-1] if s["positions"] else None,
        },
        "written_at": _now(),
    }
    await fundamental_paper_equity_collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"written": True, "session": day, "value": s["value"], "pnl": s["pnl"]}


async def daily(name: str, limit: int = 120) -> dict:
    rows = [d async for d in fundamental_paper_equity_collection.find({"book": name})
            .sort("session", -1).limit(limit)]
    for d in rows:
        d.pop("_id", None)
    return {"book": name, "days": rows, "count": len(rows)}


# ── the loop ─────────────────────────────────────────────────────────────────────


async def tick() -> dict:
    """Mark every book, and snapshot once a day after the close."""
    names = [d["_id"] async for d in fundamental_watchlists_collection.find({}, {"_id": 1})]
    if not names:
        return {"books": 0}
    out = {"books": 0, "marked": 0, "snapshots": []}
    for n in names:
        held = await fundamental_paper_positions_collection.count_documents({"book": n})
        if not held:
            continue
        out["books"] += 1
        try:
            m = await mark(n)
            out["marked"] += m.get("marked", 0)
        except Exception:
            logger.exception("marking book %s failed", n)
        now_ist = datetime.now(IST)
        if now_ist.weekday() < 5 and now_ist.strftime("%H:%M") >= SNAPSHOT_AFTER:
            try:
                r = await snapshot(n)
                if r.get("written"):
                    out["snapshots"].append(n)
            except Exception:
                logger.exception("snapshotting book %s failed", n)
    return out


async def loop(interval_seconds: int = 300) -> None:
    """Runs alongside the other desk loops; every failure is isolated to one cycle."""
    while True:
        try:
            now = datetime.now(IST)
            # Marks are only meaningful while there are prices, but the post-close
            # snapshot has to be able to fire, so the window runs past the close.
            if now.weekday() < 5 and "09:10" <= now.strftime("%H:%M") <= "16:10":
                r = await tick()
                if r.get("marked") or r.get("snapshots"):
                    logger.info("fundamental paper books: %s", r)
        except Exception:
            logger.exception("fundamental watchlist loop tick failed")
        await asyncio.sleep(interval_seconds)
