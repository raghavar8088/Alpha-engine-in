"""NSE event lists, collected every day from now on: the F&O ban list, bulk and block deals,
and corporate announcements with the exchange's own timestamps.

Phase 1 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md: start the slow collectors early. Phase 6
(market and sector context) and Phase 8 (news and events) need history, and NSE serves some
of these only for the latest day — what is not collected now cannot be researched later.

  ban    F&O securities in the ban period, per trade date: nsearchives
         .../archives/fo/sec_ban/fo_secban_DDMMYYYY.csv (dated archives exist, so history
         is backfilled; the next trade date's list is out the evening before).
  bulk   bulk deals: .../content/equities/bulk.csv — the LATEST day only. NSE's historical
         bulk-deal API refuses this host, so this kind is collected forward from 4 Nov 2026.
  block  block deals: .../content/equities/block.csv — latest day only, forward from 4 Nov.
  ann    corporate announcements: the /api/corporate-announcements API, one calendar day per
         call (weekends too — a Sunday filing matters on Monday). Each row keeps the exchange
         timestamp (an_dt), which is what Phase 8 needs to stay point-in-time.

Measured from this host on 2026-11-04 through the shared NSE session (nse_client): all four
answer. Stored one gzipped JSON file per day per kind under
DATA_DIR/nse_events/<kind>/YYYY-MM-DD.json.gz — the intraday data volume, like nse_archives;
never Atlas. A run fetches at most MAX_FETCHES_PER_RUN files, newest first, so a first
backfill spreads over several evening runs instead of holding the NSE session for long.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from app.services import market_calendar
from app.services.nse_client import nse

logger = logging.getLogger("nse_events")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = os.getenv("INTRADAY_DATA_DIR", "/data/intraday")
ROOT = os.path.join(DATA_DIR, "nse_events")
KINDS = ("ban", "bulk", "block", "ann")
BAN = "https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_{ddmmyyyy}.csv"
BULK = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK = "https://nsearchives.nseindia.com/content/equities/block.csv"
ANN_API = "/api/corporate-announcements?index=equities&from_date={d}&to_date={d}"
ANN_REFERER = "/companies-listing/corporate-filings-announcements"
BACKFILL_DAYS = {"ban": 730, "ann": 365}       # how far back an EMPTY store reaches
MAX_FETCHES_PER_RUN = 120
ANN_TEXT_MAX = 1000
ANN_KEYS = ("symbol", "desc", "an_dt", "sort_date", "exchdisstime", "attchmntText", "attchmntFile",
            "smIndustry", "sm_name", "seq_id")

status: dict = {"last_run": None, "last_result": None, "last_error": None}


# ── storage ──────────────────────────────────────────────────────────────────────


def path(kind: str, day: date) -> str:
    return os.path.join(ROOT, kind, f"{day.isoformat()}.json.gz")


def has(kind: str, day: date) -> bool:
    return os.path.exists(path(kind, day))


def load(kind: str, day: date) -> dict | None:
    try:
        with gzip.open(path(kind, day), "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(kind: str, day: date, doc: dict) -> None:
    p = path(kind, day)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, p)


def _days_stored(kind: str) -> list[str]:
    d = os.path.join(ROOT, kind)
    return sorted(f[:10] for f in os.listdir(d) if f.endswith(".json.gz")) if os.path.isdir(d) else []


# ── parsers ──────────────────────────────────────────────────────────────────────


def _num(v):
    try:
        s = str(v).strip().replace(",", "")
        return float(s) if s not in ("", "-", "nan") else None
    except ValueError:
        return None


def parse_ban(text: str) -> tuple[date | None, list[str]]:
    """'Securities in Ban For Trade Date 04-NOV-2026:' then '1,KAYNES' lines (or none)."""
    m = re.search(r"Trade Date\s+(\d{2}-[A-Za-z]{3}-\d{4})", text)
    day = datetime.strptime(m.group(1), "%d-%b-%Y").date() if m else None
    syms = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1]:
            syms.append(parts[1].upper())
    return day, syms


def parse_deals(text: str) -> dict[date, list[dict]]:
    """bulk.csv / block.csv -> {deal date: [{sym, name, client, side, qty, price, remarks}]}."""
    out: dict[date, list[dict]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        try:
            d = datetime.strptime(row.get("Date", ""), "%d-%b-%Y").date()
        except ValueError:
            continue
        price_key = next((k for k in row if k.startswith("Trade Price")), None)
        out.setdefault(d, []).append({
            "sym": row.get("Symbol", "").upper(), "name": row.get("Security Name"),
            "client": row.get("Client Name"), "side": row.get("Buy/Sell"),
            "qty": _num(row.get("Quantity Traded")), "price": _num(row.get(price_key)) if price_key else None,
            "remarks": row.get("Remarks") or None})
    return out


def _an_time(s) -> str | None:
    """'03-Nov-2026 23:53:02' (IST) -> ISO 8601 with +05:30."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt).replace(tzinfo=IST).isoformat()
        except ValueError:
            continue
    return None


def parse_ann(items: list) -> list[dict]:
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        row = {k: it.get(k) for k in ANN_KEYS if it.get(k) not in (None, "")}
        if isinstance(row.get("attchmntText"), str) and len(row["attchmntText"]) > ANN_TEXT_MAX:
            row["attchmntText"] = row["attchmntText"][:ANN_TEXT_MAX]
        row["t"] = _an_time(it.get("an_dt"))
        out.append(row)
    out.sort(key=lambda r: r.get("t") or "")
    return out


# ── collection ───────────────────────────────────────────────────────────────────


async def catch_up(days_back: int = 10) -> dict:
    """Fetch what is missing: the latest bulk/block deals, ban lists and announcements for the
    last `days_back` days (BACKFILL_DAYS when a kind's store is still empty), newest first,
    at most MAX_FETCHES_PER_RUN requests."""
    now = datetime.now(IST)
    today = now.date()
    fetches = 0
    saved = {k: 0 for k in KINDS}
    missing: list[str] = []
    try:
        # latest-day files: stored under the date printed in the file itself
        for kind, url in (("bulk", BULK), ("block", BLOCK)):
            r = await nse.get(url, tries=2)
            fetches += 1
            if r is None:
                missing.append(f"{kind}:latest")
                continue
            for d, rows in parse_deals(r.text).items():
                if not has(kind, d):
                    _save(kind, d, {"d": d.isoformat(), "rows": rows, "fetched_at": now.isoformat()})
                    saved[kind] += 1

        # ban lists by trade date: from the next trading day back
        back = days_back if _days_stored("ban") else BACKFILL_DAYS["ban"]
        d = market_calendar.next_trading_day(today)
        stop = today - timedelta(days=back)
        while d >= stop and fetches < MAX_FETCHES_PER_RUN:
            if market_calendar.is_listed_trading_day(d) and not has("ban", d):
                r = await nse.get(BAN.format(ddmmyyyy=d.strftime("%d%m%Y")), tries=2)
                fetches += 1
                if r is not None:
                    td, syms = parse_ban(r.text)
                    if td == d:
                        _save("ban", d, {"d": d.isoformat(), "symbols": syms, "fetched_at": now.isoformat()})
                        saved["ban"] += 1
                    else:
                        missing.append(f"ban:{d.isoformat()}:dated-{td}")
                elif d <= today:
                    missing.append(f"ban:{d.isoformat()}")
            d -= timedelta(days=1)

        # announcements: complete calendar days only (filings arrive until late at night)
        back = days_back if _days_stored("ann") else BACKFILL_DAYS["ann"]
        d = today - timedelta(days=1)
        stop = today - timedelta(days=back)
        while d >= stop and fetches < MAX_FETCHES_PER_RUN:
            if not has("ann", d):
                ds = d.strftime("%d-%m-%Y")
                items = await nse.api(ANN_API.format(d=ds), ANN_REFERER)
                fetches += 1
                if isinstance(items, list):
                    rows = parse_ann(items)
                    _save("ann", d, {"d": d.isoformat(), "rows": rows, "n": len(rows), "fetched_at": now.isoformat()})
                    saved["ann"] += 1
                else:
                    missing.append(f"ann:{d.isoformat()}")
            d -= timedelta(days=1)
        status["last_error"] = None
    except Exception as exc:  # noqa: BLE001 - one bad day must not stop the archive job
        status["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("[nse_events] catch-up failed")
    result = {"saved": saved, "fetches": fetches, "missing": missing[:20], "missing_count": len(missing),
              "capped": fetches >= MAX_FETCHES_PER_RUN}
    status.update({"last_run": datetime.now(timezone.utc).isoformat(), "last_result": result})
    return result


def coverage() -> dict:
    out = {}
    for kind in KINDS:
        days = _days_stored(kind)
        out[kind] = {"days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None}
    return out


def describe() -> dict:
    return {**status, "coverage": coverage()}
