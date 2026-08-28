"""NSE price bands and the surveillance frameworks (ASM / GSM), by symbol.

WHY THIS EXISTS. A ±20% stop is an assumption about what the market will let you do, and
these three files are what decide whether that assumption holds. A stock in a 2% circuit
band cannot fall 20% in under ten sessions, and on every one of those sessions it is locked
limit-down with no bid — the "stop" is not a stop, it is a hope. The desk was sizing and
stopping as if every stock behaved like DIVISLAB.

WHAT WAS VERIFIED FROM THE AWS BOX (probe, 2026-08-28, not documentation):

  * `nsearchives.nseindia.com/content/equities/sec_list.csv` — 200, ~170KB, NO cookie
    priming needed. Columns: Symbol, Series, Security Name, Band, Remarks. 3,520 rows.
    Band values observed: 20 (2,416), 5 (649), "No Band" (210), 10 (195), 2 (48), 40 (2).
    "No Band" means an F&O security — no fixed circuit, only a dynamic operating range.
    Remarks carries the GSM stage as free text for some rows.
  * `www.nseindia.com/api/reportASM` — 200 after priming `nseindia.com/`. A dict of
    `longterm` (140 rows) and `shortterm` (81), each `{data: [...]}`.
  * `www.nseindia.com/api/reportGSM` — 200, a bare LIST of 82 rows.
  * ASM and GSM rows both carry a `symbol` field, so NO ISIN join is needed. The archive
    CSV forms of these two (ASMSHORTTERM.csv, GSMSTAGES.csv) all 404 — do not retry them.

EVERY PATH FAILS SOFT. NSE is the least reliable feed this app touches, and a surveillance
outage must never stop the desk trading; it degrades to "unknown", which the gate treats as
a warning rather than a block. Silence is not the same as a clean bill of health, and the
two are kept distinguishable all the way to the UI.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.db import screener_meta_collection

logger = logging.getLogger("nse.surveillance")

SEC_LIST = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"
ASM_API = "https://www.nseindia.com/api/reportASM"
GSM_API = "https://www.nseindia.com/api/reportGSM"
NSE_HOME = "https://www.nseindia.com/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 30.0
CACHE_TTL = 6 * 3600.0  # bands and stages move once a day at most
DOC_ID = "nse_surveillance"

# Trade-to-Trade. Delivery only, no intraday netting, and usually a step on the way into
# or out of surveillance. This desk holds overnight anyway, so the restriction itself is
# harmless — it is what the flag SAYS about the stock that matters.
T2T_SERIES = {"BE", "BZ"}

_cache: tuple[float, dict] | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    """Mongo hands back tz-aware datetimes here; a naive one would raise on subtraction.

    Both shapes exist in the wild — a document written before this module used aware
    timestamps is naive — so the read side normalises rather than assuming.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num_band(v: str) -> float | None:
    """Band as a percentage. 'No Band' is an F&O security — returns None, not zero.

    None here means "no fixed circuit limit", which is the BEST case for a wide stop. Zero
    would mean the opposite, so the distinction is load-bearing and must not collapse.
    """
    v = (v or "").strip()
    if not v or v.lower().startswith("no band"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


async def _fetch_sec_list(client: httpx.AsyncClient) -> dict[str, dict]:
    r = await client.get(SEC_LIST)
    r.raise_for_status()
    out: dict[str, dict] = {}
    for raw in csv.DictReader(io.StringIO(r.text)):
        rec = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        sym = rec.get("Symbol", "").upper()
        if not sym:
            continue
        remarks = rec.get("Remarks", "").strip()
        out[sym] = {
            "series": rec.get("Series", "").upper(),
            "band_pct": _num_band(rec.get("Band", "")),
            "band_raw": rec.get("Band", "").strip(),
            "remarks": None if remarks in ("", "-") else remarks,
        }
    return out


async def _fetch_json(client: httpx.AsyncClient, url: str) -> object:
    """NSE's JSON API needs a browser-ish session; the archive CSVs do not."""
    try:
        await client.get(NSE_HOME, headers={"Accept": "text/html,application/xhtml+xml"})
    except httpx.HTTPError:
        pass  # priming is best-effort; the call below may still succeed
    r = await client.get(url, headers={"Accept": "application/json", "Referer": NSE_HOME,
                                       "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    return r.json()


def _asm_rows(body: object) -> list[dict]:
    """ASM arrives as {longterm: {data: []}, shortterm: {data: []}}."""
    rows = []
    if isinstance(body, dict):
        for horizon, block in body.items():
            data = block.get("data") if isinstance(block, dict) else block
            for d in (data or []):
                if isinstance(d, dict) and d.get("symbol"):
                    rows.append({"symbol": str(d["symbol"]).upper(),
                                 "horizon": horizon,
                                 "stage": d.get("asmSurvIndicator") or d.get("survCode"),
                                 "desc": d.get("survDesc")})
    return rows


def _gsm_rows(body: object) -> list[dict]:
    """GSM arrives as a bare list."""
    rows = []
    for d in (body or []) if isinstance(body, list) else []:
        if isinstance(d, dict) and d.get("symbol"):
            rows.append({"symbol": str(d["symbol"]).upper(),
                         "stage": d.get("gsmStage") or d.get("survCode"),
                         "desc": d.get("survDesc")})
    return rows


async def refresh() -> dict:
    """Re-read all three sources and persist. Partial success is a success.

    The three are fetched independently and a failure in one does not discard the other
    two: bands come from a plain archive CSV that has never needed priming, while ASM and
    GSM come from the JSON API that regularly 401s. Treating them as one transaction would
    mean the flakiest source could veto the most reliable one.
    """
    global _cache
    bands: dict[str, dict] = {}
    asm: list[dict] = []
    gsm: list[dict] = []
    errors: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA},
                                 follow_redirects=True) as c:
        try:
            bands = await _fetch_sec_list(c)
        except Exception as exc:  # noqa: BLE001
            errors["bands"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        try:
            asm = _asm_rows(await _fetch_json(c, ASM_API))
        except Exception as exc:  # noqa: BLE001
            errors["asm"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        try:
            gsm = _gsm_rows(await _fetch_json(c, GSM_API))
        except Exception as exc:  # noqa: BLE001
            errors["gsm"] = f"{type(exc).__name__}: {str(exc)[:120]}"

    if not bands and not asm and not gsm:
        logger.warning("nse surveillance: every source failed %s", errors)
        return {"ok": False, "errors": errors, "bands": 0, "asm": 0, "gsm": 0}

    doc = {
        "_id": DOC_ID,
        "bands": bands,
        "asm": {r["symbol"]: r for r in asm},
        "gsm": {r["symbol"]: r for r in gsm},
        "errors": errors,
        "fetched_at": _utcnow(),
    }
    await screener_meta_collection.replace_one({"_id": DOC_ID}, doc, upsert=True)
    _cache = (time.monotonic(), doc)
    logger.info("nse surveillance: %s bands, %s ASM, %s GSM%s",
                len(bands), len(asm), len(gsm), f", errors {errors}" if errors else "")
    return {"ok": True, "bands": len(bands), "asm": len(asm), "gsm": len(gsm),
            "errors": errors}


async def load(max_age_hours: float = 24.0) -> dict:
    """The stored snapshot, refreshed if stale. Never raises.

    Falls back to a stale snapshot rather than to nothing: a band that is a day old is far
    better information than no band at all, and the age is reported so a caller can say so.
    """
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_TTL:
        return _cache[1]

    doc = await screener_meta_collection.find_one({"_id": DOC_ID})
    fresh_enough = False
    if doc and doc.get("fetched_at"):
        age = (_utcnow() - _aware(doc["fetched_at"])).total_seconds() / 3600
        fresh_enough = age < max_age_hours

    if not fresh_enough:
        try:
            await refresh()
            doc = await screener_meta_collection.find_one({"_id": DOC_ID}) or doc
        except Exception as exc:  # noqa: BLE001
            logger.warning("nse surveillance refresh failed, using stored: %s", exc)

    doc = doc or {"bands": {}, "asm": {}, "gsm": {}, "errors": {"all": "never fetched"}}
    _cache = (time.monotonic(), doc)
    return doc


async def for_symbol(symbol: str) -> dict:
    snap = await load()
    return _read(snap, symbol)


def _read(snap: dict, symbol: str) -> dict:
    sym = (symbol or "").upper()
    b = (snap.get("bands") or {}).get(sym)
    asm = (snap.get("asm") or {}).get(sym)
    gsm = (snap.get("gsm") or {}).get(sym)
    return {
        "symbol": sym,
        # `known` separates "NSE says this stock is clean" from "we could not ask NSE".
        # Collapsing the two would silently upgrade an outage into an all-clear.
        "known": b is not None,
        "series": (b or {}).get("series"),
        "band_pct": (b or {}).get("band_pct"),
        "band_raw": (b or {}).get("band_raw"),
        "t2t": ((b or {}).get("series") or "") in T2T_SERIES,
        "asm": asm,
        "gsm": gsm or ((b or {}).get("remarks") if "GSM" in ((b or {}).get("remarks") or "")
                       else None),
    }


async def snapshot_reader():
    """Load once, then read many symbols without re-hitting the store.

    The gate scores hundreds of symbols per cycle; awaiting `for_symbol` for each would
    re-read the same document hundreds of times.
    """
    snap = await load()
    return lambda sym: _read(snap, sym)


async def status() -> dict:
    doc = await screener_meta_collection.find_one({"_id": DOC_ID})
    if not doc:
        return {"ok": False, "detail": "never fetched", "bands": 0, "asm": 0, "gsm": 0}
    fetched = _aware(doc.get("fetched_at"))
    age_h = (_utcnow() - fetched).total_seconds() / 3600 if fetched else None
    return {
        "ok": bool(doc.get("bands")),
        "bands": len(doc.get("bands") or {}),
        "asm": len(doc.get("asm") or {}),
        "gsm": len(doc.get("gsm") or {}),
        "errors": doc.get("errors") or {},
        "fetched_at": fetched.isoformat() if fetched else None,
        "age_hours": round(age_h, 1) if age_h is not None else None,
        "sources": {
            "bands": SEC_LIST,
            "asm": ASM_API,
            "gsm": GSM_API,
        },
    }
