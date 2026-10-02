"""NSE's nightly archives, kept: delivery %, F&O open interest, participant positions.

Three files are published each trading evening and nothing else carries their content:
  cm    sec_bhavdata_full_DDMMYYYY.csv        delivery quantity and % for every EQ stock
  fo    BhavCopy_NSE_FO_..._YYYYMMDD_F.csv    stock and index futures: price, OI, change in OI
  part  fao_participant_oi_DDMMYYYY.csv       FII / DII / Client / Pro long and short OI

They are stored one JSON file per day under DATA_DIR/nse/<kind>/YYYY-MM-DD.json, compact:
  cm   {"x": {sym: [close, prev_close, deliv_pct, ttl_qty, turnover_lacs, trades]}}
  fo   {"x": {sym: [near_close, near_prev_close, oi_all_expiries, chg_oi_all, vol_all,
                     near_settle, near_expiry]}, "idx": {NIFTY/BANKNIFTY: same}}
  part {"x": {client_type: {column: value}}}

WHAT THE RESEARCH FOUND THEM WORTH (2026-10-02, 516 sessions): as DIRECTION signals for
the next session, none of them — delivery spikes, open-interest buildup and participant
positioning all failed out of sample. They are kept because they are context the
Scanner Board shows, because new hypotheses need them, and because NSE only offers a
rolling window of these files: what is not collected now cannot be researched later.

The two-year history collected on 2026-10-02 (universe symbols only) seeds the store.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import zipfile
from datetime import date, datetime, timedelta, timezone

from app.services import market_calendar
from app.services.nse_client import nse

logger = logging.getLogger("nse_archives")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = os.getenv("INTRADAY_DATA_DIR", "/data/intraday")
ROOT = os.path.join(DATA_DIR, "nse")
KINDS = ("cm", "fo", "part")
CM = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
FO = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
PART = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv"

status: dict = {"last_ingest": None, "last_error": None, "days_ingested": 0}


def _num(v):
    try:
        s = str(v).strip().replace(",", "")
        return float(s) if s not in ("", "-", "nan") else None
    except ValueError:
        return None


def path(kind: str, day: date) -> str:
    return os.path.join(ROOT, kind, f"{day.isoformat()}.json")


def has(kind: str, day: date) -> bool:
    return os.path.exists(path(kind, day))


def load(kind: str, day: date) -> dict | None:
    try:
        with open(path(kind, day)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(kind: str, day: date, doc: dict) -> None:
    p = path(kind, day)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    os.replace(tmp, p)


def recent(kind: str, before: date, n: int) -> list[tuple[date, dict]]:
    """The last `n` stored sessions strictly before `before`, oldest first."""
    out = []
    d = before - timedelta(days=1)
    tries = 0
    while len(out) < n and tries < n * 3 + 10:
        doc = load(kind, d)
        if doc is not None:
            out.append((d, doc))
        d -= timedelta(days=1)
        tries += 1
    return list(reversed(out))


# ── parsers ──────────────────────────────────────────────────────────────────────


def parse_cm(text: str) -> dict:
    rec = {}
    for raw in csv.DictReader(io.StringIO(text)):
        x = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if x.get("SERIES") not in ("EQ", "BE") or not x.get("SYMBOL"):
            continue
        rec[x["SYMBOL"]] = [_num(x.get("CLOSE_PRICE")), _num(x.get("PREV_CLOSE")), _num(x.get("DELIV_PER")),
                            _num(x.get("TTL_TRD_QNTY")), _num(x.get("TURNOVER_LACS")), _num(x.get("NO_OF_TRADES"))]
    return rec


def parse_fo(blob: bytes) -> tuple[dict, dict]:
    z = zipfile.ZipFile(io.BytesIO(blob))
    text = z.read(z.namelist()[0]).decode("utf-8", errors="ignore")
    per: dict = {}
    for x in csv.DictReader(io.StringIO(text)):
        tp, sym = x.get("FinInstrmTp"), x.get("TckrSymb")
        if tp in ("STF", "IDF") and sym:
            per.setdefault((tp, sym), []).append(x)
    rec, idx = {}, {}
    for (tp, sym), rows in per.items():
        rows.sort(key=lambda r: r.get("XpryDt", ""))
        near = rows[0]
        v = [_num(near.get("ClsPric")), _num(near.get("PrvsClsgPric")),
             sum(_num(r.get("OpnIntrst")) or 0 for r in rows),
             sum(_num(r.get("ChngInOpnIntrst")) or 0 for r in rows),
             sum(_num(r.get("TtlTradgVol")) or 0 for r in rows),
             _num(near.get("SttlmPric")), near.get("XpryDt")]
        (idx if tp == "IDF" else rec)[sym] = v
    return rec, idx


def parse_part(text: str) -> dict:
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().strip('"').startswith("Client Type")), None)
    rec = {}
    if start is None:
        return rec
    for x in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        x = {(k or "").strip(): (v or "").strip() for k, v in x.items()}
        ct = x.get("Client Type")
        if ct:
            rec[ct] = {k: _num(v) for k, v in x.items() if k != "Client Type"}
    return rec


# ── ingestion ────────────────────────────────────────────────────────────────────


async def ingest_day(day: date) -> dict:
    """Fetch whatever of the day's three files is missing. Returns {kind: True/False}."""
    got = {}
    ddmmyyyy, yyyymmdd = day.strftime("%d%m%Y"), day.strftime("%Y%m%d")
    if not has("cm", day):
        r = await nse.get(CM.format(ddmmyyyy=ddmmyyyy))
        if r is not None:
            _save("cm", day, {"d": day.isoformat(), "x": parse_cm(r.text)})
    got["cm"] = has("cm", day)
    if not has("fo", day):
        r = await nse.get(FO.format(yyyymmdd=yyyymmdd))
        if r is not None:
            try:
                rec, idx = parse_fo(r.content)
                _save("fo", day, {"d": day.isoformat(), "x": rec, "idx": idx})
            except (zipfile.BadZipFile, KeyError, IndexError) as exc:
                logger.warning("F&O bhavcopy for %s unreadable: %s", day, exc)
    got["fo"] = has("fo", day)
    if not has("part", day):
        r = await nse.get(PART.format(ddmmyyyy=ddmmyyyy))
        if r is not None:
            rec = parse_part(r.text)
            if rec:
                _save("part", day, {"d": day.isoformat(), "x": rec})
    got["part"] = has("part", day)
    return got


async def catch_up(days_back: int = 10) -> dict:
    """Ingest every trading day of the last `days_back` that is missing anything."""
    today = datetime.now(IST).date()
    done, missing = 0, []
    d = today - timedelta(days=days_back)
    while d <= today:
        if market_calendar.is_listed_trading_day(d) and not all(has(k, d) for k in KINDS):
            if d == today and datetime.now(IST).strftime("%H:%M") < "18:00":
                break                                   # today's files are not out yet
            got = await ingest_day(d)
            if all(got.values()):
                done += 1
            else:
                missing.append((d.isoformat(), [k for k, v in got.items() if not v]))
        d += timedelta(days=1)
    status.update({"last_ingest": datetime.now(timezone.utc).isoformat(), "days_ingested": status["days_ingested"] + done,
                   "missing": missing})
    return {"ingested": done, "missing": missing}


def seed_from_jsonl(src_dir: str) -> dict:
    """One-off: split the 2026-10-02 research collection (one JSON line per day) into the
    per-day store. Existing days are left alone."""
    n = 0
    for kind in KINDS:
        p = os.path.join(src_dir, f"{kind}.jsonl")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                j = json.loads(line)
                if not j.get("ok"):
                    continue
                d = date.fromisoformat(j["d"])
                if has(kind, d):
                    continue
                doc = {"d": j["d"], "x": j["x"], "seeded": "research-collection-2026-10-02"}
                if kind == "fo":
                    doc["idx"] = j.get("idx", {})
                _save(kind, d, doc)
                n += 1
    return {"seeded_files": n}


def coverage() -> dict:
    out = {}
    for kind in KINDS:
        d = os.path.join(ROOT, kind)
        files = sorted(os.listdir(d)) if os.path.isdir(d) else []
        out[kind] = {"days": len(files), "first": files[0][:10] if files else None,
                     "last": files[-1][:10] if files else None}
    return out


def describe() -> dict:
    return {**status, "coverage": coverage(), "client": dict(nse.stats)}
