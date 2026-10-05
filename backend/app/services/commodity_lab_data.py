"""Daily history for the Commodity Lab: 2004 onward, in rupees, carry-corrected.

SOURCES. MCX's own history is not reachable from here (Angel serves ~2 years of candles
for LIVE contracts and nothing for expired ones), so the Lab uses the international
futures every MCX contract is priced off — Yahoo's continuous GC=F, SI=F, HG=F, CL=F,
NG=F — converted at USD/INR (INR=X), plus FRED spot for crude and natural gas (DCOILWTICO,
DHHNGSP) as a roll-free check on the energies. Fetched fresh each run and cached in Mongo
(`commodity_lab_history`), so a run still works if a source is down.

THE CARRY CORRECTION (decisive — see backend/research/commodity_2026_10/cmd_carry.py).
Yahoo's continuous futures are NOT roll-adjusted: their path tracks SPOT. A long MCX future
earns spot MINUS the cost of carry it pays at every roll: for metals the full rupee rate
(MCX gold = spot x e^(r_INR t)), for energy the INR forward premium (r_INR - r_USD) on top
of NYMEX's own roll yield (not modelled; it costs longs in contango). Without it a long
bias looks like skill: the 12-month trend portfolio's held-out Sharpe fell from 0.47 to
0.30 once carry was charged. Rates below are coarse annual averages, good to ~1 point.
"""

from __future__ import annotations

import csv
import io
import logging
from bisect import bisect_right
from datetime import date, datetime, timezone

import httpx

from app.core.db import db

logger = logging.getLogger("commodity_lab_data")

history_collection = db["commodity_lab_history"]

YAHOO = {"GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F", "CRUDE": "CL=F", "NATGAS": "NG=F", "USDINR": "INR=X"}
FRED = {"CRUDE_SPOT": "DCOILWTICO", "NATGAS_SPOT": "DHHNGSP"}
COMMODITIES = ["GOLD", "SILVER", "COPPER", "CRUDE", "NATGAS"]
ENERGY = {"CRUDE", "NATGAS", "CRUDE_SPOT", "NATGAS_SPOT"}
START = date(2004, 1, 1)
EXPLORE_END = date(2015, 12, 31)
HELDOUT_START = date(2016, 1, 1)

# MCX underlying for each research series (the desk's universe; minis follow their parent)
MCX_OF = {"GOLD": ["GOLD", "GOLDM"], "SILVER": ["SILVER", "SILVERM"], "COPPER": ["COPPER"],
          "CRUDE": ["CRUDEOIL", "CRUDEOILM"], "NATGAS": ["NATURALGAS", "NATGASMINI"]}
FAMILY_OF = {"GOLD": "GOLD", "SILVER": "SILVER", "COPPER": "COPPER", "CRUDE": "CRUDEOIL", "NATGAS": "NATURALGAS"}

R_INR = {**{y: 0.065 for y in range(2000, 2009)}, 2009: 0.045, 2010: 0.055, **{y: 0.08 for y in range(2011, 2015)},
         **{y: 0.065 for y in range(2015, 2020)}, 2020: 0.04, 2021: 0.035, 2022: 0.055,
         **{y: 0.067 for y in range(2023, 2031)}}
R_USD = {**{y: 0.03 for y in range(2000, 2008)}, **{y: 0.003 for y in range(2008, 2016)}, 2016: 0.004, 2017: 0.01,
         2018: 0.02, 2019: 0.021, 2020: 0.004, 2021: 0.001, 2022: 0.02, 2023: 0.052, 2024: 0.051,
         **{y: 0.04 for y in range(2025, 2031)}}
ROLLS_PER_YEAR = {"GOLD": 6, "SILVER": 6, "COPPER": 12, "CRUDE": 12, "NATGAS": 12}
COST_SIDE = 0.0006     # MCX charges ~3 bp + slippage, a side
ROLL_COST = 0.0010     # a roll: two legs plus the spread


def carry_rate(key: str, d: date) -> float:
    """Annual cost of carry a LONG pays (a short earns)."""
    if key in ENERGY:
        return R_INR.get(d.year, 0.065) - R_USD.get(d.year, 0.04)
    return R_INR.get(d.year, 0.065)


async def _fetch_yahoo(symbol: str) -> list[list]:
    end = int(datetime.now(timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=946684800&period2={end}&interval=1d"
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = (await c.get(url)).json()["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    off = r["meta"].get("gmtoffset") or 0
    out = []
    for t, o, h, l, cl in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if cl and o and h and l:
            out.append([datetime.fromtimestamp(t + off, timezone.utc).date().isoformat(), o, h, l, cl])
    return out


async def _fetch_fred(series: str) -> list[list]:
    async with httpx.AsyncClient(timeout=60) as c:
        text = (await c.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")).text
    out = []
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].startswith("observation") or row[0].startswith("DATE") or row[1] in ("", "."):
            continue
        out.append([row[0], float(row[1])])
    return out


async def refresh() -> dict:
    """Fetch every series; keep the cached copy of any that fails."""
    report = {}
    for key, sym in YAHOO.items():
        try:
            rows = await _fetch_yahoo(sym)
            if len(rows) > 1000:
                await history_collection.update_one({"_id": key}, {"$set": {"rows": rows, "source": f"yahoo {sym}",
                                                                            "fetched_at": datetime.now(timezone.utc)}},
                                                    upsert=True)
            report[key] = len(rows)
        except Exception as exc:  # noqa: BLE001
            report[key] = f"failed: {str(exc)[:80]}"
    for key, sid in FRED.items():
        try:
            rows = await _fetch_fred(sid)
            if len(rows) > 1000:
                await history_collection.update_one({"_id": key}, {"$set": {"rows": rows, "source": f"fred {sid}",
                                                                            "fetched_at": datetime.now(timezone.utc)}},
                                                    upsert=True)
            report[key] = len(rows)
        except Exception as exc:  # noqa: BLE001
            report[key] = f"failed: {str(exc)[:80]}"
    return report


async def ensure_fresh(max_age_hours: float = 20.0) -> dict | None:
    """Refresh the cache when its newest fetch is older than `max_age_hours`."""
    doc = await history_collection.find_one({"_id": "USDINR"}, {"fetched_at": 1})
    at = (doc or {}).get("fetched_at")
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if at is not None and (datetime.now(timezone.utc) - at).total_seconds() < max_age_hours * 3600:
        return None
    return await refresh()


class History:
    """Rupee OHLC per commodity and rupee closes per series, from the cache."""

    def __init__(self, raw: dict[str, list]):
        fx_rows = [(date.fromisoformat(r[0]), r[4]) for r in raw.get("USDINR", []) if r[4]]
        self._fx_days = [d for d, _ in fx_rows]
        self._fx = [v for _, v in fx_rows]
        self.ohlc: dict[str, list[tuple]] = {}
        for k in COMMODITIES:
            out = []
            for r in raw.get(k, []):
                d = date.fromisoformat(r[0])
                f = self.fx_on(d)
                if d >= START and f:
                    out.append((d, r[1] * f, r[2] * f, r[3] * f, r[4] * f, 0.0))
            self.ohlc[k] = out
        self.closes: dict[str, list[tuple[date, float]]] = {k: [(r[0], r[4]) for r in v] for k, v in self.ohlc.items()}
        for k in FRED:
            out = []
            for r in raw.get(k, []):
                d = date.fromisoformat(r[0])
                f = self.fx_on(d)
                if d >= START and f and r[1] > 0:
                    out.append((d, r[1] * f))
            self.closes[k] = out

    def fx_on(self, d: date) -> float | None:
        i = bisect_right(self._fx_days, d) - 1
        return self._fx[i] if i >= 0 else None

    def span(self) -> dict:
        return {k: [v[0][0].isoformat(), v[-1][0].isoformat(), len(v)] for k, v in self.closes.items() if v}


async def load() -> History:
    raw = {d["_id"]: d.get("rows", []) async for d in history_collection.find({})}
    return History(raw)
