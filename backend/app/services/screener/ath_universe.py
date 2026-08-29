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
    # ── strict: through the high of an N-session window, intraday basis ──────────
    ("ath_20y", "20-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 5000 , latest high ) ) )"),
    ("ath_14y", "14-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 3500 , latest high ) ) )"),
    ("ath_10y", "10-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 2500 , latest high ) ) )"),
    ("ath_6y", "6-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 1500 , latest high ) ) )"),
    ("ath_4y", "4-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 1000 , latest high ) ) )"),
    ("ath_3y", "3-year high (intraday)",
     "( {cash} ( latest high > 1 day ago max( 750 , latest high ) ) )"),

    # ── closing basis: a different question, and it catches different names. A stock
    #    can close at a record without its intraday high exceeding an old spike. ─────
    ("ath_4y_close", "4-year high (closing basis)",
     "( {cash} ( latest high > 1 day ago max( 1000 , latest close ) ) )"),
    ("ath_2y_close", "2-year high (closing basis)",
     "( {cash} ( latest close > 1 day ago max( 500 , latest close ) ) )"),
    ("ath_1y_close", "52-week high (closing basis)",
     "( {cash} ( latest close > 1 day ago max( 252 , latest close ) ) )"),

    # ── 52-week, with and without a volume floor. The floor version is the standard
    #    screen; the unfloored one reaches illiquid names the floor hides, which the
    #    tradability pillar then judges rather than silently dropping. ──────────────
    ("high_52w", "52-week high",
     "( {cash} ( latest high >= latest max( 252 , latest high ) and latest volume > 1000 ) )"),
    ("high_52w_all", "52-week high (no volume floor)",
     "( {cash} ( latest high >= latest max( 252 , latest high ) ) )"),

    # ── approaching: within 2% of the level. Not at a high yet, so they are labelled
    #    as such — but a stock 1% away today is the one that breaks out tomorrow. ────
    ("near_52w", "Within 2% of the 52-week high",
     "( {cash} ( latest close >= latest max( 252 , latest high ) * 0.98 "
     "and latest volume > 5000 ) )"),
    ("near_4y", "Within 2% of the 4-year high",
     "( {cash} ( latest close >= 1 day ago max( 1000 , latest high ) * 0.98 "
     "and latest volume > 5000 ) )"),
]
# Named public screeners, each verified to run. `all-time-high` was dropped: its owner
# DELETED it between two probes on the same day — the page still returns 200 with a
# scan-json prop whose clause is stripped. Public screeners are not a stable dependency,
# which is the whole reason this sweep unions many nets instead of trusting one.
NAMED_NETS = ["all-time-high-8", "all-time-high-stocks", "stocks-at-all-time-high",
              "52-week-high", "new-52-week-high", "near-52-week-high"]

# How recent a bar has to be to count as "at" the high.
RECENT_DAYS = 7
# How close to its stored all-time high a register symbol has to be to become a candidate.
# Widened from "at or above" so approaching names are analysed too — they are labelled by
# their actual distance, never counted as all-time highs.
NEAR_ATH_PCT = 3.0
# Seeding is the expensive step — several rate-limited Angel calls per symbol. Raised
# because the register is what CONFIRMS an all-time high: every symbol seeded is one more
# that can be judged properly instead of reported as unverified. Whatever is left over is
# picked up by the next build and the shortfall is reported.
MAX_SEED = 200
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
        if ath <= 0:
            continue
        gap = (float(b["high"]) / ath - 1) * 100
        if gap >= -NEAR_ATH_PCT:
            hits[sym] = {"stored_ath": ath, "ath_date": h.get("all_time_high_date"),
                         "sessions": h.get("sessions"), "last_high": float(b["high"]),
                         "gap_pct": round(gap, 2)}
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
            # Judge the high on the SESSION'S HIGH, not the close. Measured live: 11 of
            # 12 rows graded "about 1% away" had a session high sitting exactly on their
            # stored all-time high — they set the record intraday and closed under it.
            # Grading those as near-misses halved the confirmed count and was simply wrong.
            day_high = ((r.get("levels") or {}).get("day_high")) or ltp
            best = max(day_high or 0, ltp or 0)
            if ath and best:
                gap = (best / float(ath) - 1) * 100
                confirmed = gap >= -0.1
                # Three states, not two. "At an all-time high", "1% away from one" and
                # "at a 4-year high while its record still stands 40% above" are different
                # facts, and a reader deciding what to buy needs to tell them apart.
                grade = ("all_time" if confirmed
                         else "near_ath" if gap >= -NEAR_ATH_PCT
                         else "multi_year")
                intraday_only = confirmed and ltp and ltp < float(ath) * 0.999
                basis = (
                    (f"Touched its all-time high of {float(ath):,.2f} intraday and closed "
                     f"{abs((ltp / float(ath) - 1) * 100):.1f}% under it"
                     if intraday_only else
                     f"At or through its all-time high of {float(ath):,.2f}")
                    if confirmed else
                    f"{abs(gap):.1f}% below its all-time high of {float(ath):,.2f}"
                    f" (set {h.get('all_time_high_date') or 'earlier'})")
            else:
                gap, confirmed, grade = None, None, "unverified"
                basis = ("No stored all-time high to check against yet — this is a "
                         "multi-year high on Chartink's window, not a verified record.")
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
                "ath_grade": grade,
                "pct_from_ath": round(gap, 2) if gap is not None else None,
                "ath_basis": basis,
            })
        await _progress(progress=40 + int(55 * (i + len(chunk)) / max(1, len(candidates))),
                        step=f"analysed {min(i + ANALYSE_BATCH, len(candidates))} "
                             f"of {len(candidates)}")

    rows.sort(key=lambda r: -((r.get("verdict") or {}).get("score") or -1))

    confirmed = [r for r in rows if r.get("ath_confirmed")]
    near = [r for r in rows if r.get("ath_grade") == "near_ath"]
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
        "near_ath": len(near),
        "buyable": len(buy),
        "rows": rows,
        "coverage": {
            "register": await register_coverage(),
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


# ── growing the register ────────────────────────────────────────────────────────
# THE REGISTER IS THE REAL COVERAGE LIMIT. Measured: NSE's own sec_list carries 3,137 cash
# equities once ETFs are removed, and only 1,188 of them have a stored all-time high. The
# other 1,949 are invisible to net 2 entirely — they can only be found if a Chartink net
# happens to flag them, and their high can never be CONFIRMED because there is nothing to
# confirm it against.
#
# Closing that gap is the single largest completeness win available, and it is pure
# grinding: several rate-limited Angel calls per symbol, two phases deep.
EXPAND_STATE_ID = "ath_register_expand"
EXPAND_BATCH = 50
RESOLVE_PACE = 0.35


async def register_coverage() -> dict:
    """How much of NSE's cash market has a stored all-time high."""
    from app.core.db import instruments_collection, stock_highs_collection
    from app.services import nse_surveillance as SURV

    snap = await SURV.load()
    bands, etfs = snap.get("bands") or {}, snap.get("etfs") or {}
    cash = {sym for sym, b in bands.items()
            if (b.get("series") or "") in ("EQ", "BE", "BZ", "SM", "ST") and sym not in etfs}
    if not cash:
        return {"universe": 0, "seeded": 0, "missing": 0,
                "note": "NSE's security list was unavailable, so coverage cannot be measured."}

    have = {d["symbol"] async for d in stock_highs_collection.find(
        {"all_time_high": {"$gt": 0}}, {"symbol": 1})}
    missing = sorted(cash - have)
    resolvable = {d["symbol"] async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "angel_token": {"$ne": None},
         "symbol": {"$in": missing}}, {"symbol": 1})}
    return {
        "universe": len(cash),
        "seeded": len(cash & have),
        "missing": len(missing),
        "missing_resolvable": len(resolvable),
        "missing_need_lookup": len(missing) - len(resolvable),
        "pct": round(len(cash & have) / len(cash) * 100, 1),
        "note": ("Every missing symbol is one whose all-time high cannot be CONFIRMED — it "
                 "can still be found by a Chartink net, but only reported as unverified."),
    }


async def expand_status() -> dict:
    col = await _state_col()
    doc = await col.find_one({"_id": EXPAND_STATE_ID}) or {}
    doc.pop("_id", None)
    for k in ("started_at", "finished_at"):
        if hasattr(doc.get(k), "isoformat"):
            doc[k] = doc[k].isoformat()
    return doc or {"state": "never run"}


async def _expand_progress(**kw) -> None:
    col = await _state_col()
    await col.update_one({"_id": EXPAND_STATE_ID},
                         {"$set": {"_id": EXPAND_STATE_ID, **kw}}, upsert=True)


async def expand_register(limit: int | None = None) -> dict:
    """Resolve and seed NSE cash equities that have no stored all-time high.

    Two phases per batch because they fail differently. A symbol absent from the
    instrument master needs Angel's scrip search first — the master is Dhan-derived, so
    its silence says nothing — and `backfill_all_time_highs` silently skips anything it
    cannot resolve, which would otherwise look like a symbol with no history rather than
    one nobody looked up.
    """
    from app.services import ath_trading as ATH
    from app.services import stock_highs as SH
    from app.core.db import instruments_collection

    started = _now()
    cov = await register_coverage()
    if not cov.get("missing"):
        await _expand_progress(state="ready", finished_at=_now(), step="nothing missing")
        return {"seeded": 0, "resolved": 0, **cov}

    from app.core.db import stock_highs_collection
    from app.services import nse_surveillance as SURV
    snap = await SURV.load()
    bands, etfs = snap.get("bands") or {}, snap.get("etfs") or {}
    cash = {sym for sym, b in bands.items()
            if (b.get("series") or "") in ("EQ", "BE", "BZ", "SM", "ST") and sym not in etfs}
    have = {d["symbol"] async for d in stock_highs_collection.find(
        {"all_time_high": {"$gt": 0}}, {"symbol": 1})}
    todo = sorted(cash - have)
    if limit:
        todo = todo[:limit]

    await _expand_progress(state="running", started_at=started, finished_at=None,
                           total=len(todo), done=0, resolved=0, seeded=0, progress=0,
                           step="starting")

    resolved = seeded = failed = 0
    for i in range(0, len(todo), EXPAND_BATCH):
        batch = todo[i:i + EXPAND_BATCH]

        known = {d["symbol"] async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "angel_token": {"$ne": None},
             "symbol": {"$in": batch}}, {"symbol": 1})}
        for sym in batch:
            if sym in known:
                continue
            try:
                found = await ATH._angel_lookup(sym)
                if found:
                    await ATH._adopt_instrument(found)
                    resolved += 1
            except Exception as exc:  # noqa: BLE001
                logger.info("expand: lookup failed for %s (%s)", sym, str(exc)[:90])
            await asyncio.sleep(RESOLVE_PACE)

        try:
            res = await SH.backfill_all_time_highs(only_missing=True, symbols=batch)
            seeded += res.get("ok", 0)
            failed += res.get("failed", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("expand: seeding batch failed (%s)", exc)

        done = min(i + EXPAND_BATCH, len(todo))
        await _expand_progress(done=done, resolved=resolved, seeded=seeded, failed=failed,
                               progress=int(done / max(1, len(todo)) * 100),
                               step=f"{done} of {len(todo)} — {seeded} seeded")

    out = {"state": "ready", "finished_at": _now(), "progress": 100,
           "total": len(todo), "resolved": resolved, "seeded": seeded, "failed": failed,
           "seconds": round((_now() - started).total_seconds(), 1),
           "step": f"done — {seeded} new all-time highs stored"}
    await _expand_progress(**out)
    logger.info("expand register: %s resolved, %s seeded, %s failed in %.0fs",
                resolved, seeded, failed, out["seconds"])
    return out


_expand_task: asyncio.Task | None = None


async def start_expand(limit: int | None = None) -> dict:
    global _expand_task
    if _expand_task and not _expand_task.done():
        return {"started": False, "reason": "an expansion is already running",
                **(await expand_status())}

    async def _run():
        try:
            await expand_register(limit)
        except Exception as exc:  # noqa: BLE001
            logger.exception("register expansion failed")
            await _expand_progress(state="failed", step=str(exc)[:200], finished_at=_now())

    _expand_task = asyncio.create_task(_run())
    return {"started": True,
            "note": "Growing the register in the background. This is slow — several "
                    "rate-limited Angel calls per symbol — but every symbol it adds is one "
                    "whose all-time high can afterwards be confirmed rather than guessed."}


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
