"""Option-chain recorder (U2 of the 2026-10-02 Pre-Live plan) — real NIFTY option prices,
every minute, kept forever on the data volume.

WHY. Every NIFTY option backtest here has had to INVENT premiums: Dhan purges expired
contracts and no other source we can reach keeps them. The invented ones were wrong in a
way that flattered option buying — Black-Scholes at India VIX priced expiry-day options 52%
too cheap — and even a model calibrated on the desk's 5,800 real trades is only good to about
+-5-8% of an option's price month to month, which is more than the edges being looked for. The
only cure is to keep the real prices ourselves, from now on.

WHAT. Each minute of the session: NIFTY's current and next weekly expiry, the ATM strike +-10
strikes, calls and puts (84 contracts), from Angel One's FULL quote — best bid and ask with
their quantities, last traded price, open interest and day volume — plus NIFTY spot and India
VIX from the same request. One JSON line per minute in DATA_DIR/optchain/YYYY-MM-DD.jsonl,
gzipped after the close (~0.2 MB a day). Atlas is near its quota, so none of this goes there.

  {"t": epoch, "spot": 22450.1, "vix": 14.4, "exp": ["2026-10-06", "2026-10-13"],
   "rows": [[expiry_index, strike, "C"|"P", ltp, bid, bid_qty, ask, ask_qty, oi, volume], ...]}

After ~3 months the Buying Lab can test on these instead of a model.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import shutil
import time
from datetime import date, datetime, timedelta, timezone

from app.core.db import instruments_collection
from app.services import market_calendar

logger = logging.getLogger("option_chain_recorder")

IST = timezone(timedelta(hours=5, minutes=30))
ENABLED = os.getenv("OPTION_CHAIN_RECORDER_ENABLED", "1").lower() not in ("0", "false", "no")
DATA_DIR = os.path.join(os.getenv("INTRADAY_DATA_DIR", "/data/intraday"), "optchain")
UNDERLYING = "NIFTY"
STEP = 50
STRIKES_EACH_SIDE = int(os.getenv("OPTION_CHAIN_STRIKES_EACH_SIDE", "10"))
EXPIRIES = 2
INDEX_TOKENS = {"NIFTY": "99926000", "INDIAVIX": "99926017"}
status: dict = {"enabled": ENABLED, "today_rows": 0, "last_t": None, "contracts": 0, "errors": 0,
                "last_error": None, "files": 0, "last_gzip": None}
_contracts: dict = {"key": None, "rows": [], "expiries": []}
_spot: dict = {"v": None}


def path(day: date, gz: bool = False) -> str:
    return os.path.join(DATA_DIR, f"{day.isoformat()}.jsonl" + (".gz" if gz else ""))


async def _expiries(today: date) -> list[str]:
    exps = sorted(e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING}) if e and e >= today.isoformat())
    weekly = [e for e in exps if (date.fromisoformat(e) - today).days <= 13]
    return weekly[:EXPIRIES] or exps[:EXPIRIES]


async def _contract_set(spot: float, today: date) -> tuple[list[dict], list[str]]:
    atm = round(spot / STEP) * STEP
    exps = await _expiries(today)
    key = (atm, tuple(exps))
    if _contracts["key"] == key:
        return _contracts["rows"], _contracts["expiries"]
    lo, hi = atm - STRIKES_EACH_SIDE * STEP, atm + STRIKES_EACH_SIDE * STEP
    rows = []
    async for d in instruments_collection.find(
            {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING, "expiry": {"$in": exps},
             "strike": {"$gte": lo, "$lte": hi}, "angel_token": {"$ne": None}},
            {"expiry": 1, "strike": 1, "option_type": 1, "angel_token": 1, "angel_exchange": 1}):
        rows.append({"e": exps.index(d["expiry"]), "k": float(d["strike"]), "c": "C" if d["option_type"] == "CE" else "P",
                     "tok": str(d["angel_token"]), "ex": d.get("angel_exchange") or "NFO"})
    rows.sort(key=lambda r: (r["e"], r["k"], r["c"]))
    _contracts.update({"key": key, "rows": rows, "expiries": exps})
    return rows, exps


async def snapshot(now: datetime | None = None) -> dict | None:
    """Quote the chain once and return the record (not written)."""
    from app.services.angel_client import angel_client
    now = now or datetime.now(IST)
    idx = await angel_client.full_quote({"NSE": list(INDEX_TOKENS.values())})
    spot = (idx.get(INDEX_TOKENS["NIFTY"]) or {}).get("ltp") or _spot["v"]
    vix = (idx.get(INDEX_TOKENS["INDIAVIX"]) or {}).get("ltp")
    if not spot:
        return None
    _spot["v"] = spot
    rows, exps = await _contract_set(spot, now.date())
    by_ex: dict[str, list[str]] = {}
    for r in rows:
        by_ex.setdefault(r["ex"], []).append(r["tok"])
    q = await angel_client.full_quote(by_ex) if by_ex else {}
    out = []
    for r in rows:
        x = q.get(r["tok"])
        if not x:
            continue
        out.append([r["e"], r["k"], r["c"], x.get("ltp"), x.get("bid"), x.get("bid_qty"), x.get("ask"),
                    x.get("ask_qty"), x.get("oi"), x.get("volume")])
    return {"t": int(now.timestamp()), "spot": spot, "vix": vix, "exp": exps, "rows": out}


def _append(day: date, rec: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path(day), "a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _gzip(day: date) -> bool:
    src = path(day)
    if not os.path.exists(src):
        return False
    with open(src, "rb") as a, gzip.open(path(day, gz=True), "wb", compresslevel=6) as b:
        shutil.copyfileobj(a, b)
    os.remove(src)
    return True


def load_day(day: date):
    """Yield the day's minute records (gzipped or still raw)."""
    for p, opener in ((path(day, gz=True), gzip.open), (path(day), open)):
        if os.path.exists(p):
            with opener(p, "rt") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
            return


def coverage() -> dict:
    if not os.path.isdir(DATA_DIR):
        return {"days": 0}
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith((".jsonl", ".jsonl.gz")))
    return {"days": len(files), "first": files[0][:10] if files else None, "last": files[-1][:10] if files else None,
            "bytes": sum(os.path.getsize(os.path.join(DATA_DIR, f)) for f in files)}


async def recorder_loop() -> None:
    logger.info("option-chain recorder: NIFTY, %d expiries, ATM +-%d strikes, every minute -> %s",
                EXPIRIES, STRIKES_EACH_SIDE, DATA_DIR)
    last_minute = None
    while True:
        try:
            now = datetime.now(IST)
            hm = now.strftime("%H:%M")
            if market_calendar.is_trading_day(now) and "09:15" <= hm <= "15:30" and now.second >= 2:
                minute = now.replace(second=0, microsecond=0)
                if minute != last_minute:
                    last_minute = minute
                    t0 = time.monotonic()
                    rec = await snapshot(now)
                    if rec:
                        await asyncio.to_thread(_append, now.date(), rec)
                        status.update({"today_rows": status["today_rows"] + 1 if status.get("day") == now.date().isoformat() else 1,
                                       "day": now.date().isoformat(), "last_t": now.isoformat(),
                                       "contracts": len(rec["rows"]), "last_ms": round((time.monotonic() - t0) * 1000)})
            elif hm >= "15:36" and status.get("last_gzip") != now.date().isoformat():
                if await asyncio.to_thread(_gzip, now.date()):
                    logger.info("option chain %s compressed", now.date())
                status["last_gzip"] = now.date().isoformat()
                status.update(coverage())
        except Exception as exc:  # noqa: BLE001 - a missed minute is logged, never fatal
            status["errors"] += 1
            status["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("option-chain snapshot failed: %s", exc)
        await asyncio.sleep(5)
