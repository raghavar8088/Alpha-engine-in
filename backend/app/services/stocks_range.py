"""Stocks Range — a watch-table of the Nifty 50 / 100 / 250 / 500 universe with a
user-set manual "buy range" per stock.

Data sources, all Angel/local (no Dhan):
  * index membership + sector: the official niftyindices.com constituent CSVs (each row
    is Company Name, Industry=sector, Symbol). The four lists nest (50 ⊂ 100 ⊂ 250 ⊂
    500), so a stock's "belongs to" is the TIGHTEST index it appears in.
  * LTP + previous close (1-day change): Angel One FULL quotes.
  * 1-week change + stock/sector trend: the stored daily bars (bars_collection).
  * buy range: the user's own price, stored per (user, symbol); a stock is in the BUY
    ZONE when the live price is within ±10% of that entered price.
"""

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import UpdateOne

from app.core.db import (
    bars_collection,
    instruments_collection,
    stock_ranges_collection,
    stock_universe_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("stocks_range")

BUY_ZONE_PCT = 0.10  # within ±10% of the entered price = buy zone
IST = timezone(timedelta(hours=5, minutes=30))
QUOTE_PACE_SECONDS = 0.15  # small gap between 50-token quote chunks (Angel rate limit)
BARS_LOOKBACK_DAYS = 500   # ~1.4y of sessions: enough for SMA200 / 52-week high / the
                           # bullish screen's 3-month structure, not just 1-week change
BARS_PACE_SECONDS = 0.4    # gap between historical-candle calls (Angel's stricter limit)

# (index key, label, official constituent CSV). The lists nest largest-to-smallest.
INDEX_CSVS = [
    ("nifty50", "Nifty 50", "https://niftyindices.com/IndexConstituent/ind_nifty50list.csv"),
    ("nifty100", "Nifty 100", "https://niftyindices.com/IndexConstituent/ind_nifty100list.csv"),
    ("nifty250", "Nifty 250", "https://niftyindices.com/IndexConstituent/ind_niftylargemidcap250list.csv"),
    ("nifty500", "Nifty 500", "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"),
]
INDEX_LABELS = {k: lbl for k, lbl, _ in INDEX_CSVS}
TIGHTEST_ORDER = ["nifty50", "nifty100", "nifty250", "nifty500"]


class RangeError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------


async def refresh_stock_universe() -> dict:
    """(Re)load the four index constituent lists from niftyindices.com into
    stock_universe. Idempotent; run on startup and periodically. A stock carries the
    set of indices it is in and its tightest (smallest) index for the 'belongs to'."""
    members: dict[str, dict] = {}
    fetched = {}
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for idx, _label, url in INDEX_CSVS:
            try:
                text = (await client.get(url)).text
            except Exception as exc:
                logger.warning("stock universe: could not fetch %s (%s)", idx, exc)
                continue
            rows = list(csv.DictReader(io.StringIO(text)))
            fetched[idx] = len(rows)
            for row in rows:
                sym = (row.get("Symbol") or "").strip().upper()
                if not sym:
                    continue
                m = members.setdefault(sym, {
                    "name": (row.get("Company Name") or "").strip(),
                    "sector": (row.get("Industry") or "").strip() or "Unclassified",
                    "indices": set(),
                })
                m["indices"].add(idx)

    ops = []
    for sym, m in members.items():
        tightest = next((i for i in TIGHTEST_ORDER if i in m["indices"]), None)
        ops.append(UpdateOne(
            {"symbol": sym},
            {"$set": {
                "symbol": sym, "name": m["name"], "sector": m["sector"],
                "indices": sorted(m["indices"]), "tightest_index": tightest, "updated_at": _now(),
            }},
            upsert=True,
        ))
    if ops:
        await stock_universe_collection.bulk_write(ops, ordered=False)
    logger.info("stock universe refreshed: %s symbols (%s)", len(members), fetched)
    return {"symbols": len(members), "by_index": fetched}


async def backfill_universe_bars() -> dict:
    """Fetch ~90 days of daily candles from Angel for EVERY universe symbol and upsert into
    bars_collection ('1d'), so the 1-week change and stock/sector trend columns are filled
    for the whole Nifty 500 — not just the ~200 symbols that carried bars from an old load.

    Paced for Angel's historical-data rate limit; per-symbol failures are non-fatal. The ts
    is stored as a UTC isoformat string (e.g. '...T18:30:00+00:00'), matching the existing
    daily bars so the upsert dedupes by (symbol, timeframe, ts) instead of doubling days."""
    if not angel_client.configured():
        logger.info("universe bars backfill skipped — Angel One not configured")
        return {"ok": 0, "failed": 0, "skipped": True}

    syms = [d["symbol"] async for d in stock_universe_collection.find({}, {"symbol": 1})]
    # include any custom stock a user has set a buy range for (e.g. one outside the Nifty
    # 500) so its 1-week change / trend columns fill in too.
    ranged = await stock_ranges_collection.distinct("symbol")
    syms = list({*syms, *ranged})
    inst = {
        d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": syms}, "angel_token": {"$ne": None}},
            {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
        )
    }
    now = _now()
    to_dt = now.astimezone(IST).strftime("%Y-%m-%d 15:30")
    from_dt = (now - timedelta(days=BARS_LOOKBACK_DAYS)).astimezone(IST).strftime("%Y-%m-%d 09:15")

    try:
        await angel_client._session()  # warm once; per-symbol calls then reuse the JWT
    except AngelAPIError:
        pass

    ok = fail = 0
    for sym, i in inst.items():
        token = str(i["angel_token"])
        ex = i.get("angel_exchange") or "NSE"
        try:
            rows = await angel_client.candles(ex, token, "D", from_dt, to_dt)
        except Exception:
            fail += 1
            await asyncio.sleep(BARS_PACE_SECONDS)
            continue
        ops = []
        for row in rows or []:
            try:
                stamp = datetime.fromisoformat(row[0]).astimezone(timezone.utc)
                ts = stamp.isoformat()
                ops.append(UpdateOne(
                    {"symbol": sym, "timeframe": "1d", "ts": ts},
                    {"$set": {
                        "symbol": sym, "timeframe": "1d", "ts": ts,
                        "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
                        "close": float(row[4]), "volume": float(row[5]), "oi": None,
                    }},
                    upsert=True,
                ))
            except (ValueError, TypeError, IndexError):
                continue
        if ops:
            await bars_collection.bulk_write(ops, ordered=False)
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(BARS_PACE_SECONDS)

    logger.info("universe bars backfill: %s ok, %s failed (of %s)", ok, fail, len(inst))
    return {"ok": ok, "failed": fail, "symbols": len(inst)}


# --------------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------------


def _stock_trend(closes: list[float], ltp: float | None) -> str | None:
    """Up / Down / Sideways from price vs its 20- and 50-day SMAs."""
    if ltp is None or len(closes) < 20:
        return None
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else sma20
    if ltp > sma20 >= sma50:
        return "Up"
    if ltp < sma20 <= sma50:
        return "Down"
    return "Sideways"


def _trend_label(avg_pct: float) -> str:
    return "Up" if avg_pct > 0.5 else "Down" if avg_pct < -0.5 else "Flat"


# --------------------------------------------------------------------------------
# Table
# --------------------------------------------------------------------------------


async def list_universe(user_id: str, index: str) -> dict:
    if index not in INDEX_LABELS:
        raise RangeError(f"Unknown index '{index}' — pick one of {list(INDEX_LABELS)}")
    docs = [d async for d in stock_universe_collection.find({"indices": index})]
    if not docs:
        raise RangeError("Stock universe not seeded yet — try again in a moment.")

    ranges = {r["symbol"]: r["buy_price"] async for r in stock_ranges_collection.find({"user_id": user_id})}

    # Also surface every stock the user has set a buy range for, even when it sits outside
    # the selected index — or outside the Nifty 500 entirely (e.g. KANSAINER). Those are the
    # user's own watch list and should appear on any tab. Pull index members from the
    # universe (keeps their real sector/belongs-to); for symbols not in any Nifty index,
    # synthesise a doc from the instrument master so they can still be quoted and shown.
    present = {d["symbol"] for d in docs}
    extra = [s for s in ranges if s not in present]
    if extra:
        async for d in stock_universe_collection.find({"symbol": {"$in": extra}}):
            docs.append(d)
            present.add(d["symbol"])
        missing = [s for s in extra if s not in present]
        if missing:
            async for i in instruments_collection.find(
                {"asset_class": "EQUITY", "symbol": {"$in": missing}, "angel_token": {"$ne": None}},
                {"symbol": 1, "name": 1},
            ):
                docs.append({"symbol": i["symbol"], "name": i.get("name"),
                             "sector": "Unclassified", "indices": [], "tightest_index": None})
                present.add(i["symbol"])

    symbols = [d["symbol"] for d in docs]

    # Angel tokens for live quotes
    inst = {
        d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": symbols}},
            {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
        )
    }
    by_ex: dict[str, list[str]] = {}
    tok_sym: dict[str, str] = {}
    for sym, i in inst.items():
        if i.get("angel_token"):
            tok = str(i["angel_token"])
            by_ex.setdefault(i.get("angel_exchange") or "NSE", []).append(tok)
            tok_sym[tok] = sym
    # Pre-warm the Angel session ONCE. Otherwise, the first quote of the batch may trigger
    # a login, and if that login is momentarily rate-limited (403) the whole quote call
    # raises and EVERY price falls back to (often missing) daily bars — which is exactly
    # why the Nifty 500 tail showed ₹-. One retry covers a transient login hiccup.
    for attempt in range(2):
        try:
            await angel_client._session()
            break
        except AngelAPIError:
            if attempt == 0:
                await asyncio.sleep(0.7)

    # Quote in 50-token chunks with light pacing, and — crucially — catch per chunk so a
    # single failed chunk can't blank the other ~450 stocks. Whatever a chunk can't return
    # still falls back to daily bars below.
    q_by_sym: dict[str, dict] = {}
    for grouped in batches(by_ex):
        try:
            for tok, q in (await angel_client.full_quote(grouped)).items():
                if tok in tok_sym:
                    q_by_sym[tok_sym[tok]] = q
        except AngelAPIError:
            pass
        await asyncio.sleep(QUOTE_PACE_SECONDS)

    # recent daily closes (oldest→newest) per symbol
    closes_by_sym: dict[str, list[float]] = {}
    async for b in bars_collection.find(
        {"timeframe": "1d", "symbol": {"$in": symbols}}, {"symbol": 1, "close": 1, "ts": 1}
    ).sort("ts", 1):
        closes_by_sym.setdefault(b["symbol"], []).append(b["close"])

    rows = []
    for d in docs:
        sym = d["symbol"]
        q = q_by_sym.get(sym)
        closes = closes_by_sym.get(sym, [])
        ltp = (q.get("ltp") if q else None) or (closes[-1] if closes else None)
        prev = (q.get("close") if q else None) or (closes[-2] if len(closes) >= 2 else None)
        chg1d = (ltp - prev) if (ltp is not None and prev) else None
        close_1w = closes[-6] if len(closes) >= 6 else None
        chg1w = (ltp - close_1w) if (ltp is not None and close_1w) else None
        buy = ranges.get(sym)
        in_zone = bool(buy and ltp and abs(ltp / buy - 1) <= BUY_ZONE_PCT)
        rows.append({
            "symbol": sym, "name": d.get("name"),
            "belongs_to": INDEX_LABELS.get(d.get("tightest_index")),
            "sector": d.get("sector"),
            "ltp": round(ltp, 2) if ltp is not None else None,
            "change_1d": round(chg1d, 2) if chg1d is not None else None,
            "change_1d_pct": round(chg1d / prev * 100, 2) if (chg1d is not None and prev) else None,
            "change_1w": round(chg1w, 2) if chg1w is not None else None,
            "change_1w_pct": round(chg1w / close_1w * 100, 2) if (chg1w is not None and close_1w) else None,
            "stock_trend": _stock_trend(closes, ltp),
            "buy_price": buy,
            "in_buy_zone": in_zone,
            "range_move_pct": round((ltp / buy - 1) * 100, 2) if (buy and ltp) else None,
            "_rank": TIGHTEST_ORDER.index(d.get("tightest_index")) if d.get("tightest_index") in TIGHTEST_ORDER else 99,
        })

    # sector trend = average 1-week %change of the sector's stocks
    sec_pct: dict[str, list[float]] = {}
    for r in rows:
        if r["change_1w_pct"] is not None:
            sec_pct.setdefault(r["sector"], []).append(r["change_1w_pct"])
    sec_trend = {s: _trend_label(sum(v) / len(v)) for s, v in sec_pct.items()}
    for r in rows:
        r["sector_trend"] = sec_trend.get(r["sector"])

    rows.sort(key=lambda r: (r["_rank"], r["symbol"]))
    for r in rows:
        r.pop("_rank", None)
    return {"index": index, "label": INDEX_LABELS[index], "count": len(rows), "rows": rows}


# --------------------------------------------------------------------------------
# Search + buy range
# --------------------------------------------------------------------------------


async def search_stocks(q: str, limit: int = 15) -> list[dict]:
    """Search the Nifty 50/100/250/500 universe FIRST (those carry sector + index), then
    fall back to any other Angel-quotable NSE equity in the instrument master — so stocks
    outside the Nifty 500 (e.g. KANSAINER) can still be found and given a buy range."""
    q = q.strip()
    if not q:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    async for d in stock_universe_collection.find(
        {"$or": [{"symbol": {"$regex": f"^{q.upper()}"}}, {"name": {"$regex": q, "$options": "i"}}]},
        {"_id": 0, "symbol": 1, "name": 1, "sector": 1, "tightest_index": 1},
    ).limit(limit):
        out.append({"symbol": d["symbol"], "name": d.get("name"), "sector": d.get("sector"),
                    "belongs_to": INDEX_LABELS.get(d.get("tightest_index")),
                    "tightest_index": d.get("tightest_index")})
        seen.add(d["symbol"])

    if len(out) < limit:
        async for i in instruments_collection.find(
            {"asset_class": "EQUITY", "angel_token": {"$ne": None},
             "symbol": {"$nin": list(seen)},
             "$or": [{"symbol": {"$regex": f"^{q.upper()}"}}, {"name": {"$regex": q, "$options": "i"}}]},
            {"_id": 0, "symbol": 1, "name": 1},
        ).limit(limit - len(out)):
            if i["symbol"] in seen:
                continue
            out.append({"symbol": i["symbol"], "name": i.get("name"), "sector": None,
                        "belongs_to": None, "tightest_index": None})
            seen.add(i["symbol"])
    return out


async def get_range(user_id: str, symbol: str) -> dict:
    d = await stock_ranges_collection.find_one({"user_id": user_id, "symbol": symbol.upper()})
    return {"symbol": symbol.upper(), "buy_price": d.get("buy_price") if d else None}


async def set_range(user_id: str, symbol: str, buy_price: float) -> dict:
    symbol = symbol.strip().upper()
    if not symbol:
        raise RangeError("Symbol is required")
    if buy_price is None or buy_price <= 0:
        raise RangeError("Enter a positive buy price")
    existing = await stock_ranges_collection.find_one({"user_id": user_id, "symbol": symbol})
    old = existing.get("buy_price") if existing else None
    await stock_ranges_collection.update_one(
        {"user_id": user_id, "symbol": symbol},
        {"$set": {"user_id": user_id, "symbol": symbol, "buy_price": float(buy_price), "updated_at": _now()}},
        upsert=True,
    )
    return {
        "symbol": symbol, "buy_price": float(buy_price), "previous": old,
        "pct_diff": round((buy_price / old - 1) * 100, 2) if old else None,
    }
