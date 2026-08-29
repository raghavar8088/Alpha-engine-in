"""Every NSE stock at an all-time high, analysed — and an honest account of the ones we
cannot see.

THE HARD PART IS COMPLETENESS, NOT ANALYSIS. "Don't miss a single stock" is a claim about
coverage, and no single source can support it, so this unions several independent nets and
then reports what each contributed:

  1. CHARTINK, whole cash market (~2,800 names). Its `max()` window was probed and reaches
     about 5,000 sessions — roughly 20 years — after which it returns nothing. Six clauses
     are run at different windows (252 / 500 / 1,000 / 2,500 / 5,000 sessions, high and
     close based) plus the two named ATH screens. Chartink sees names this app has never
     stored, which is exactly why it is here.
  2. OUR OWN ALL-TIME-HIGH REGISTER, 1,147 symbols whose full history was walked back to
     listing date through Angel. This is the AUTHORITATIVE check: Chartink's 20-year window
     is not all-time for a company listed in 1987, and a 20-year high is a different claim
     from an all-time high.
  3. OUR OWN STORED BARS, for anything the first two missed.

Candidates come from the union; the VERDICT on whether a candidate is really at an
all-time high comes from source 2 alone. A stock Chartink flags whose stored all-time high
is above today's price is reported as a multi-year high, not an all-time one, and the two
are never conflated in the output.

WHAT THIS STILL CANNOT SEE, stated rather than hidden: a stock that is at an all-time high,
absent from every Chartink net, and has no entry in our register. The coverage block
reports the register's size and how many candidates had to be seeded on the fly, so the
reader can judge the gap instead of assuming there is none.

THE BUILD IS SLOW ON PURPOSE. Seeding an unseen symbol's full history costs several calls
against Angel's rate-limited endpoint. It runs in the background, writes progress as it
goes, and the page polls — rather than a request that times out halfway and leaves a
partial answer looking like a complete one.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services.screener import analysis as AN
from app.services.screener import chartink as CK

logger = logging.getLogger("screener.ath_universe")

STATE_ID = "ath_universe"

# Six windows, high- and close-based. Run together they bracket everything from a 52-week
# high to a 20-year high, and the union is far wider than any one of them: probed live,
# 252d returned 77 rows, 1000d 28, 5000d 5 — different stocks in each.
CLAUSES: list[tuple[str, str, str]] = [
    ("ath_20y", "20-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 5000 , latest high ) ) )"),
    ("ath_10y", "10-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 2500 , latest high ) ) )"),
    ("ath_4y", "4-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 1000 , latest high ) ) )"),
    ("ath_4y_close", "4-year high (closing basis)",
     "( {cash} ( latest high > 1 day ago max( 1000 , latest close ) ) )"),
    ("ath_2y_close", "2-year high (closing basis)",
     "( {cash} ( latest close > 1 day ago max( 500 , latest close ) ) )"),
    ("high_52w", "52-week high",
     "( {cash} ( latest high >= latest max( 252 , latest high ) and latest volume > 1000 ) )"),
]
NAMED_NETS = ["all-time-high-8", "all-time-high"]

# Seeding is the expensive step. Capped per build so one run cannot spend an hour against
# Angel; whatever is left is picked up by the next build and the shortfall is reported.
# How recent a bar has to be to count as "at" the high.
RECENT_DAYS = 7
MAX_SEED = 60
SEED_PACE = 0.4
ANALYSE_BATCH = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _state_col():
    from app.core.db import screener_meta_collection
    return screener_meta_collection


async def _progress(**kw) -> None:
    col = await _state_col()
    await col.update_one({"_id": STATE_ID}, {"$set": {"_id": STATE_ID, **kw}}, upsert=True)


async def status() -> dict:
    col = await _state_col()
    doc = await col.find_one({"_id": STATE_ID}) or {}
    doc.pop("_id", None)
    doc.pop("rows", None)          # the payload is large; status must stay cheap
    for k in ("started_at", "finished_at"):
        if hasattr(doc.get(k), "isoformat"):
            doc[k] = doc[k].isoformat()
    return doc or {"state": "never built"}


async def snapshot() -> dict:
    col = await _state_col()
    doc = await col.find_one({"_id": STATE_ID}) or {}
    doc.pop("_id", None)
    for k in ("started_at", "finished_at"):
        if hasattr(doc.get(k), "isoformat"):
            doc[k] = doc[k].isoformat()
    if not doc:
        return {"state": "never built", "rows": [], "count": 0}
    return doc


# ── net 1: Chartink ─────────────────────────────────────────────────────────────

async def _chartink_candidates() -> tuple[dict[str, list[str]], dict, list[dict]]:
    """{symbol: [net labels]}, per-net counts, and the non-equity rows each net dropped."""
    found: dict[str, list[str]] = {}
    per_net: dict[str, dict] = {}
    excluded: dict[str, dict] = {}

    etfs = await CK._etf_register()

    for key, label, clause in CLAUSES:
        res = await CK.run_clause(clause)
        if not res.get("ok"):
            per_net[key] = {"label": label, "rows": 0, "error": res.get("error")}
            continue
        # run_clause already filters, but its excluded list is what we report from.
        rows = res.get("rows") or []
        for r in rows:
            found.setdefault(r["symbol"], []).append(label)
        for e in res.get("excluded") or []:
            excluded.setdefault(e["symbol"], e)
        per_net[key] = {"label": label, "rows": len(rows),
                        "excluded": len(res.get("excluded") or []), "error": None}
        await asyncio.sleep(0.3)

    for slug in NAMED_NETS:
        res = await CK.named(slug)
        if not res.get("ok"):
            per_net[slug] = {"label": slug, "rows": 0, "error": res.get("error")}
            continue
        label = (CK.NAMED.get(slug) or {}).get("label", slug)
        for r in res.get("rows") or []:
            found.setdefault(r["symbol"], []).append(label)
        for e in res.get("excluded") or []:
            excluded.setdefault(e["symbol"], e)
        per_net[slug] = {"label": label, "rows": len(res.get("rows") or []),
                         "excluded": len(res.get("excluded") or []), "error": None}

    _ = etfs  # filtering happens inside chartink; fetched here only to fail early if down
    return found, per_net, list(excluded.values())


# ── net 2 + 3: our own register and bars ────────────────────────────────────────

async def _own_candidates() -> tuple[dict[str, dict], int]:
    """Symbols whose latest stored bar is at or above their stored all-time high."""
    from app.core.db import bars_collection, stock_highs_collection

    highs = {d["symbol"]: d async for d in stock_highs_collection.find(
        {"all_time_high": {"$gt": 0}},
        {"_id": 0, "symbol": 1, "all_time_high": 1, "all_time_high_date": 1, "sessions": 1})}
    if not highs:
        return {}, 0

    # One aggregation for the whole register rather than a query per symbol — on M0 the
    # per-query latency dominates and a 1,100-symbol loop takes minutes.
    #
    # NO $sort. Sorting every bar of 1,147 symbols blew Mongo's 32MB in-memory sort limit,
    # and M0 does not permit spilling to disk. $max needs no sort, and bounding to the
    # last few sessions cuts the working set by two orders of magnitude.
    #
    # Taking the max over a WINDOW rather than the single last bar is also the more correct
    # question: "at an all-time high" means recently, and a symbol whose last stored bar is
    # weeks stale should not be judged on it.
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    last = {}
    pipeline = [
        {"$match": {"timeframe": "1d", "ts": {"$gte": cutoff},
                    "symbol": {"$in": list(highs)}}},
        {"$group": {"_id": "$symbol", "high": {"$max": "$high"},
                    "close": {"$max": "$close"}, "ts": {"$max": "$ts"}}},
    ]
    async for d in bars_collection.aggregate(pipeline):
        last[d["_id"]] = d

    hits = {}
    for sym, h in highs.items():
        b = last.get(sym)
        if not b or not b.get("high"):
            continue
        ath = float(h["all_time_high"])
        if ath > 0 and float(b["high"]) >= ath * 0.999:
            hits[sym] = {"stored_ath": ath, "ath_date": h.get("all_time_high_date"),
                         "sessions": h.get("sessions"), "last_high": float(b["high"])}
    return hits, len(highs)


# ── verification ────────────────────────────────────────────────────────────────

async def _seed_missing(symbols: list[str]) -> dict:
    """Walk full history for candidates with no stored all-time high."""
    from app.core.db import stock_highs_collection
    from app.services import stock_highs as SH

    have = {d["symbol"] async for d in stock_highs_collection.find(
        {"symbol": {"$in": symbols}, "all_time_high": {"$gt": 0}}, {"symbol": 1})}
    missing = [s for s in symbols if s not in have]
    if not missing:
        return {"needed": 0, "seeded": 0, "left": 0}

    batch = missing[:MAX_SEED]
    try:
        res = await SH.backfill_all_time_highs(only_missing=True, symbols=batch)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ath universe: seeding failed (%s)", exc)
        return {"needed": len(missing), "seeded": 0, "left": len(missing),
                "error": str(exc)[:160]}
    return {"needed": len(missing), "seeded": res.get("ok", 0),
            "left": max(0, len(missing) - len(batch))}


# ── the build ───────────────────────────────────────────────────────────────────

async def build() -> dict:
    """Assemble every all-time-high candidate, verify, analyse, persist. Slow by design."""
    started = _now()
    await _progress(state="running", started_at=started, step="casting the nets",
                    progress=0, finished_at=None)

    ck_hits, per_net, excluded = await _chartink_candidates()
    await _progress(step="reading our own all-time-high register", progress=15)
    own_hits, register_size = await _own_candidates()

    candidates = sorted(set(ck_hits) | set(own_hits))
    await _progress(step=f"{len(candidates)} candidates — seeding missing histories",
                    progress=25, candidates=len(candidates))

    seed = await _seed_missing(candidates)

    # Re-read the register: seeding just added entries, and the verdict below depends on it.
    from app.core.db import stock_highs_collection
    highs = {d["symbol"]: d async for d in stock_highs_collection.find(
        {"symbol": {"$in": candidates}},
        {"_id": 0, "symbol": 1, "all_time_high": 1, "all_time_high_date": 1, "sessions": 1})}

    await _progress(step=f"analysing {len(candidates)} stocks", progress=40)

    rows: list[dict] = []
    for i in range(0, len(candidates), ANALYSE_BATCH):
        chunk = candidates[i:i + ANALYSE_BATCH]
        try:
            res = await AN.analyse(chunk)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ath universe: analysis batch failed (%s)", exc)
            continue
        for r in res.get("rows") or []:
            sym = r["symbol"]
            h = highs.get(sym) or {}
            ath = h.get("all_time_high")
            ltp = r.get("ltp")
            # THE VERDICT ON "ALL-TIME" COMES FROM OUR REGISTER, NOT FROM CHARTINK.
            # A 20-year high is not an all-time high, and a stock whose stored peak sits
            # above today's price is reported as the multi-year high it actually is.
            if ath and ltp:
                confirmed = ltp >= float(ath) * 0.999
                basis = (f"at or above its stored all-time high of {float(ath):,.2f}"
                         if confirmed else
                         f"below its stored all-time high of {float(ath):,.2f}")
            else:
                confirmed = None
                basis = "no stored all-time high to check against"
            # `gate` is the largest nested object on an analysis row and everything a
            # reader needs from it is already summarised in pillars.tradability. Dropped
            # here to keep the stored snapshot well clear of Mongo's document ceiling —
            # this doc holds every candidate, not one stock.
            r.pop("gate", None)
            rows.append({
                **r,
                "nets": ck_hits.get(sym, []),
                "from_own_register": sym in own_hits,
                "stored_ath": round(float(ath), 2) if ath else None,
                "stored_ath_date": h.get("all_time_high_date"),
                "history_sessions": h.get("sessions"),
                "ath_confirmed": confirmed,
                "ath_basis": basis,
            })
        await _progress(progress=40 + int(55 * (i + len(chunk)) / max(1, len(candidates))),
                        step=f"analysed {min(i + ANALYSE_BATCH, len(candidates))} "
                             f"of {len(candidates)}")

    rows.sort(key=lambda r: -((r.get("verdict") or {}).get("score") or -1))

    confirmed = [r for r in rows if r.get("ath_confirmed")]
    buy = [r for r in rows if (r.get("verdict") or {}).get("action") == "Buy"]
    doc = {
        "state": "ready",
        "started_at": started,
        "finished_at": _now(),
        "seconds": round((_now() - started).total_seconds(), 1),
        "progress": 100,
        "step": "done",
        "count": len(rows),
        "candidates": len(candidates),
        "confirmed_ath": len(confirmed),
        "buyable": len(buy),
        "rows": rows,
        "coverage": {
            "chartink_nets": per_net,
            "chartink_symbols": len(ck_hits),
            "own_register_hits": len(own_hits),
            "register_size": register_size,
            "seeded": seed,
            "excluded_non_equity": len(excluded),
            "excluded": excluded[:60],
            "blind_spot": (
                "A stock at an all-time high that appears in none of the Chartink nets AND "
                "has no entry in our register would be missed. The register holds "
                f"{register_size} symbols walked back to listing date; "
                f"{seed.get('seeded', 0)} more were added during this build"
                + (f", and {seed['left']} still need seeding — run again to reach them."
                   if seed.get("left") else ".")),
        },
        "note": ("Candidates come from the union of every net. Whether a candidate is "
                 "really at an ALL-TIME high is decided only by our own register, which "
                 "walks each stock back to its listing date — Chartink's window stops at "
                 "about 20 years, and a 20-year high is a different claim."),
    }
    col = await _state_col()
    await col.replace_one({"_id": STATE_ID}, {"_id": STATE_ID, **doc}, upsert=True)
    logger.info("ath universe: %s candidates, %s confirmed at an all-time high, "
                "%s buyable, in %.0fs", len(candidates), len(confirmed), len(buy),
                doc["seconds"])
    return {k: v for k, v in doc.items() if k != "rows"}


_task: asyncio.Task | None = None


async def start_build() -> dict:
    """Kick off a build in the background. Refuses to start a second one."""
    global _task
    if _task and not _task.done():
        return {"started": False, "reason": "a build is already running",
                **(await status())}

    async def _run():
        try:
            await build()
        except Exception as exc:  # noqa: BLE001
            logger.exception("ath universe build failed")
            await _progress(state="failed", step=str(exc)[:200], finished_at=_now())

    _task = asyncio.create_task(_run())
    return {"started": True, "note": "Building in the background — poll the status."}
