"""Global cues before the Indian open — what they are good for, and what they are not.

Measured on 516 sessions (2026-10-02 research): the previous US session's return explains
NIFTY's OPENING GAP (S&P 500 corr 0.42, Nasdaq 0.36, dollar index -0.18, crude -0.16) and
says nothing about NIFTY from 09:45 to the close (corr -0.04). Asian markets' previous
session: nothing (their day is already in India's previous close). So these feed the
pre-market brief and the expected-gap estimate, and are never a long/short trigger.

Data: Yahoo's public chart API (JSON, no pandas — importing yfinance would add ~70 MB to
the backend permanently). Two reads:
  previous session   last two DAILY closes of markets that closed before the Indian open
  live               regularMarketPrice vs previous close, for markets trading at 08:40 IST
                     (US index futures overnight, Nikkei, Hang Seng, Kospi, dollar, crude)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

from app.core.db import db

logger = logging.getLogger("global_cues")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = os.getenv("INTRADAY_DATA_DIR", "/data/intraday")
HIST_DIR = os.path.join(DATA_DIR, "global")
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"), "Accept": "application/json"}

# key: (yahoo symbol, label, group, read)  read: "session" = previous completed session,
# "live" = trading at the Indian pre-open
SERIES = {
    "SPX": ("^GSPC", "S&P 500", "us", "session"),
    "NASDAQ": ("^IXIC", "Nasdaq", "us", "session"),
    "DOW": ("^DJI", "Dow Jones", "us", "session"),
    "ES": ("ES=F", "S&P 500 futures", "us_futures", "live"),
    "NQ": ("NQ=F", "Nasdaq futures", "us_futures", "live"),
    "NIKKEI": ("^N225", "Nikkei 225", "asia", "live"),
    "HANGSENG": ("^HSI", "Hang Seng", "asia", "live"),
    "KOSPI": ("^KS11", "Kospi", "asia", "live"),
    "DXY": ("DX-Y.NYB", "Dollar index", "fx", "live"),
    "USDINR": ("INR=X", "USD/INR", "fx", "live"),
    "CRUDE": ("CL=F", "WTI crude", "commodities", "live"),
    "BRENT": ("BZ=F", "Brent crude", "commodities", "live"),
    "GOLD": ("GC=F", "Gold", "commodities", "live"),
    "US10Y": ("^TNX", "US 10-year yield", "rates", "live"),
    "INDIAVIX": ("^INDIAVIX", "India VIX", "india", "session"),
    "NIFTY": ("^NSEI", "NIFTY 50", "india", "session"),
}

brief_coll = db["market_brief"]


async def _chart(client: httpx.AsyncClient, sym: str, rng: str = "10d") -> dict | None:
    try:
        r = await client.get(CHART.format(sym=sym, rng=rng))
        if r.status_code != 200:
            return None
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
        # Date each daily bar in its EXCHANGE's local time: Yahoo stamps USD/INR at 23:00
        # UTC of the day before (London midnight), so a UTC date put today's bar a day
        # early — the live read then compared the price with today's own bar (~0%).
        off = int((res.get("meta") or {}).get("gmtoffset") or 0)
        rows = [(datetime.fromtimestamp(t + off, timezone.utc).date().isoformat(), c)
                for t, c in zip(ts, closes) if c is not None]
        return {"meta": res.get("meta", {}), "rows": rows}
    except Exception:  # noqa: BLE001
        return None


async def snapshot(save: bool = True) -> dict:
    """The pre-open global picture. Never raises; missing series are reported as such."""
    now = datetime.now(IST)
    out: dict = {"at": now.isoformat(), "series": {}}
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as c:
        for key, (sym, label, group, read) in SERIES.items():
            ch = await _chart(c, sym)
            await asyncio.sleep(0.3)
            if not ch or len(ch["rows"]) < 2:
                out["series"][key] = {"label": label, "group": group, "available": False}
                continue
            meta, rows = ch["meta"], ch["rows"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            # previous completed session: the last daily row dated before today (IST),
            # against the row before it
            done = [r for r in rows if r[0] < now.date().isoformat()]
            sess = None
            if len(done) >= 2:
                sess = {"date": done[-1][0], "close": done[-1][1],
                        "ret_pct": round((done[-1][1] / done[-2][1] - 1) * 100, 2)}
            live = None
            if price and done:
                live = {"price": price, "vs": done[-1][1],
                        "chg_pct": round((price / done[-1][1] - 1) * 100, 2)}
            out["series"][key] = {"label": label, "group": group, "read": read, "available": True,
                                  "session": sess, "live": live, "recent": done[-8:]}
    if save:
        try:
            await brief_coll.update_one({"_id": now.date().isoformat()},
                                        {"$set": {"global": out, "global_at": datetime.now(timezone.utc)}},
                                        upsert=True)
        except Exception:  # noqa: BLE001
            logger.exception("could not store the global snapshot")
    return out


async def refresh_history(rng: str = "3y") -> dict:
    """Daily closes per series to DATA_DIR/global/<KEY>.json — for the expected-gap model."""
    os.makedirs(HIST_DIR, exist_ok=True)
    n = 0
    async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as c:
        for key, (sym, *_r) in SERIES.items():
            ch = await _chart(c, sym, rng)
            await asyncio.sleep(0.5)
            if not ch or not ch["rows"]:
                continue
            with open(os.path.join(HIST_DIR, f"{key}.json"), "w") as f:
                json.dump(ch["rows"], f)
            n += 1
    return {"series_saved": n}


def history(key: str) -> list[tuple[str, float]]:
    try:
        with open(os.path.join(HIST_DIR, f"{key}.json")) as f:
            return [tuple(r) for r in json.load(f)]
    except (OSError, ValueError):
        return []


async def latest_brief(day: date | None = None) -> dict | None:
    d = (day or datetime.now(IST).date()).isoformat()
    doc = await brief_coll.find_one({"_id": d})
    if doc:
        doc.pop("_id", None)
    return doc
