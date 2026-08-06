"""Stocks Range — a watch-table of the Nifty 50 / 100 / 250 / 500 universe with a
user-set manual "buy range" per stock.

Data sources, all Angel/local (no Dhan):
  * index membership + sector: the official niftyindices.com constituent CSVs (each row
    is Company Name, Industry=sector, Symbol). The four lists nest (50 ⊂ 100 ⊂ 250 ⊂
    500), so a stock's "belongs to" is the TIGHTEST index it appears in.
  * LTP + previous close (1-day change): Angel One FULL quotes.
  * 1-week change + stock/sector trend: the stored daily bars (bars_collection).
  * buy range: the user's own price, stored per (user, symbol); a stock is in the BUY
    ZONE when the live price is within ±6% of that entered price.
"""

import csv
import io
import logging
from datetime import datetime, timezone

import httpx
from pymongo import UpdateOne

from app.core.db import (
    bars_collection,
    instruments_collection,
    stock_ranges_collection,
    stock_universe_collection,
)
from app.services.angel_client import AngelAPIError, angel_client

logger = logging.getLogger("stocks_range")

BUY_ZONE_PCT = 0.06  # within ±6% of the entered price = buy zone

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
    q_by_sym: dict[str, dict] = {}
    for ex, toks in by_ex.items():
        try:
            for tok, q in (await angel_client.full_quote({ex: toks})).items():
                if tok in tok_sym:
                    q_by_sym[tok_sym[tok]] = q
        except AngelAPIError:
            continue

    # recent daily closes (oldest→newest) per symbol
    closes_by_sym: dict[str, list[float]] = {}
    async for b in bars_collection.find(
        {"timeframe": "1d", "symbol": {"$in": symbols}}, {"symbol": 1, "close": 1, "ts": 1}
    ).sort("ts", 1):
        closes_by_sym.setdefault(b["symbol"], []).append(b["close"])

    ranges = {r["symbol"]: r["buy_price"] async for r in stock_ranges_collection.find({"user_id": user_id})}

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
    q = q.strip()
    if not q:
        return []
    cursor = stock_universe_collection.find(
        {"$or": [
            {"symbol": {"$regex": f"^{q.upper()}"}},
            {"name": {"$regex": q, "$options": "i"}},
        ]},
        {"_id": 0, "symbol": 1, "name": 1, "sector": 1, "belongs_to": 1, "tightest_index": 1},
    ).limit(limit)
    out = []
    async for d in cursor:
        out.append({"symbol": d["symbol"], "name": d.get("name"), "sector": d.get("sector"),
                    "belongs_to": INDEX_LABELS.get(d.get("tightest_index")),
                    "tightest_index": d.get("tightest_index")})
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
