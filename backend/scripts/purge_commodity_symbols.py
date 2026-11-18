"""Remove every commodity but the desk's own contracts from the Commodity Trading module's records.

The owner's decision (18 Nov 2026): Commodity Trading keeps only Natural Gas Mini (NATGASMINI) and Crude
Oil Mini (CRUDEOILM); the other eight underlyings' records are deleted from this module. The desk stops
TRADING them in commodity_engine.DESK_UNDERLYINGS; this script removes their HISTORY.

WHAT IT TOUCHES - and nothing else
  main database (Atlas)
    commodity_positions, commodity_trades            rows of the eight                        DELETED
    top10_book_positions {desk: "commodity"}          Top 10 Paper Trade books' copies           DELETED
    rank_band_positions                               Top 5 / 5-10 / 10-15 / 15-20 books' copies DELETED
    commodity_scores                                  recomputed from what remains (rescore_all) REBUILT
    commodity_equity, top10_book_equity {desk:
      "commodity"}, rank_band_equity                  replayed from what remains, same times     REBUILT
    top10_book_scores {desk: "commodity"} and
      rank_band_scores: `skipped`                     counted across all commodities, not
                                                      attributable to one - restart at zero       RESET
  the box's local MongoDB (intraday_signal_ledger._db(), FACTORY_MONGO_URL)
    ai_positions, ai_gate_decisions {module: "commodity"}   rows of the eight                    DELETED

A row is "of the eight" when its symbol's underlying (the letters before a contract's date, so
NATGASMINI26NOVFUT is NATGASMINI) is one of commodity_bars.LIQUID_UNDERLYINGS that is not kept. A row with
no symbol, or an underlying outside that list, is KEPT and reported - nothing is deleted by inference.

NOT TOUCHED: the bar store (commodity_bars - the Gold desk, the Pre-Live desk and the Strategy Factory read
it), the Commodity Lab (its trial count must only grow, or its luck correction understates the tries),
every real-money record, and every other module (Commodity Positions, Commodity Auto, Pre-Live Commodity,
Natural Gas book, Gold desk, Commodity Options).

SAFETY
  * Dry run by default: it prints what it would do, and the exact confirmation to type.
  * --apply needs --confirm "DELETE <n> ROWS" with the count the dry run printed.
  * Before any write, every document it will delete or rebuild goes into ONE gzipped bson-json file
    (json_util: exact types, exact restore), which is read back and counted; it refuses if that check
    fails or the disk lacks room.
  * --restore <file> puts every deleted row back and every rebuilt collection back as it was.
  * It refuses while MCX is open (the desk must not be closing positions whose history is being removed),
    unless --force-hours.

Run on the box in a throwaway container from the production image, the box tree read-only:
  sudo docker run --rm --memory 400m --network alpha-engine_default --env-file ~/alpha-engine/.env \\
    -v ~/alpha-engine/backend:/app/backend:ro -v ~/alpha-engine/shared:/app/shared:ro \\
    -v /home/ubuntu/backups:/backups -w /app/backend --entrypoint python alpha-engine-backend \\
    scripts/purge_commodity_symbols.py --backup-dir /backups                      # dry run
  ...  scripts/purge_commodity_symbols.py --backup-dir /backups --apply --confirm "DELETE <n> ROWS"
  ...  scripts/purge_commodity_symbols.py --restore /backups/commodity_purge_<stamp>.json.gz
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import json_util

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # backend/

KEEP_DEFAULT = ("NATGASMINI", "CRUDEOILM")
BATCH = 500
IST = timezone(timedelta(hours=5, minutes=30))
_BASE = re.compile(r"^([A-Z]+?)(?=\d|$)")


def underlying(symbol) -> str | None:
    """'NATGASMINI26NOVFUT' -> 'NATGASMINI'; 'CRUDEOILM' -> 'CRUDEOILM'; None/'' -> None."""
    if not symbol or not isinstance(symbol, str):
        return None
    m = _BASE.match(symbol.strip().upper())
    return m.group(1) if m else None


def _naive(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


# ── the stores ─────────────────────────────────────────────────────────────────────────────


def deletion_targets(db, fdb) -> list[tuple[str, object, dict]]:
    """(label, collection, base filter) for every store rows are deleted from."""
    out = [
        ("commodity_positions", db["commodity_positions"], {}),
        ("commodity_trades", db["commodity_trades"], {}),
        ("top10_book_positions", db["top10_book_positions"], {"desk": "commodity"}),
        ("rank_band_positions", db["rank_band_positions"], {}),
    ]
    if fdb is not None:
        out += [("ai_positions", fdb["ai_positions"], {"module": "commodity"}),
                ("ai_gate_decisions", fdb["ai_gate_decisions"], {"module": "commodity"})]
    return out


def rebuild_scopes(db) -> list[tuple[str, object, dict]]:
    """(label, collection, filter) whose documents are rebuilt or reset, backed up whole first."""
    return [
        ("commodity_scores", db["commodity_scores"], {}),
        ("commodity_equity", db["commodity_equity"], {}),
        ("top10_book_equity", db["top10_book_equity"], {"desk": "commodity"}),
        ("top10_book_scores", db["top10_book_scores"], {"desk": "commodity"}),
        ("rank_band_equity", db["rank_band_equity"], {}),
        ("rank_band_scores", db["rank_band_scores"], {}),
    ]


async def plan_purge(db, fdb, keep: set[str], known: set[str]) -> dict:
    """Classify every row; nothing is written."""
    delete_set = sorted(known - keep)
    plan = {"keep": sorted(keep), "delete_set": delete_set, "stores": {}, "total": 0}
    for label, coll, base in deletion_targets(db, fdb):
        ids, by_sym, kept, unknown = [], Counter(), Counter(), Counter()
        async for d in coll.find(base, {"_id": 1, "symbol": 1}):
            u = underlying(d.get("symbol"))
            if u in delete_set:
                ids.append(d["_id"])
                by_sym[u] += 1
            elif u in keep:
                kept[u] += 1
            else:
                unknown[str(u)] += 1
        plan["stores"][label] = {"ids": ids, "delete": len(ids), "by_symbol": dict(by_sym),
                                 "kept": dict(kept), "kept_unknown": dict(unknown)}
        plan["total"] += len(ids)
    return plan


def confirm_phrase(plan: dict) -> str:
    return f"DELETE {plan['total']} ROWS"


def print_plan(plan: dict) -> None:
    print(f"keep: {', '.join(plan['keep'])}   delete: {', '.join(plan['delete_set'])}")
    for label, s in plan["stores"].items():
        print(f"  {label:22s} delete {s['delete']:>7,}  {s['by_symbol']}   keep {s['kept']}"
              + (f"   KEPT, unrecognised symbol: {s['kept_unknown']}" if s["kept_unknown"] else ""))
    print(f"  total rows to delete: {plan['total']:,}")


# ── equity, replayed from what remains ─────────────────────────────────────────────────────


def replay_curve(snapshot_times: list[datetime], positions: list[dict], capital: float) -> list[dict]:
    """For each snapshot time: realised P&L of the remaining CLOSED rows up to then, and the rows open
    then (count and margin). Unrealised is unknowable after the fact, so it is 0 and the point is flagged.
    Pure; `positions` carry opened_at / closed_at / realized_pnl / capital_deployed / status."""
    closes, opens = [], []
    for p in positions:
        oa = _naive(p.get("opened_at"))
        if oa is None:
            continue
        ca = None if p.get("status") == "OPEN" else (_naive(p.get("closed_at")) or _naive(p.get("updated_at")) or oa)
        dep = float(p.get("capital_deployed") or 0.0)
        opens.append((oa, dep))
        if ca is not None:
            closes.append((ca, float(p.get("realized_pnl") or 0.0), dep))
    opens.sort(key=lambda x: x[0])
    closes.sort(key=lambda x: x[0])
    out, oi, ci = [], 0, 0
    n_open = dep_open = realized = 0.0
    for ts in sorted(t for t in (_naive(x) for x in snapshot_times) if t is not None):
        while oi < len(opens) and opens[oi][0] <= ts:
            n_open += 1
            dep_open += opens[oi][1]
            oi += 1
        while ci < len(closes) and closes[ci][0] <= ts:
            realized += closes[ci][1]
            n_open -= 1
            dep_open -= closes[ci][2]
            ci += 1
        out.append({"ts": ts, "equity": round(capital + realized, 2), "realized": round(realized, 2),
                    "unrealized": 0.0, "deployed": round(max(dep_open, 0.0), 2), "open_positions": int(max(n_open, 0))})
    return out


async def _rebuild_equity(coll, scope: dict, positions: list[dict], capital: float, stamp: str) -> int:
    from pymongo import UpdateOne

    snaps = [d async for d in coll.find(scope, {"_id": 1, "ts": 1})]
    times = [_naive(s.get("ts")) for s in snaps]
    pts = {p["ts"]: p for p in replay_curve([t for t in times if t is not None], positions, capital)}
    ops = []
    for s, t in zip(snaps, times):
        p = pts.get(t)
        if p is None:
            continue
        ops.append(UpdateOne({"_id": s["_id"]}, {"$set": {
            "equity": p["equity"], "realized": p["realized"], "unrealized": 0.0, "deployed": p["deployed"],
            "open_positions": p["open_positions"],
            "rebuilt": f"{stamp}: replayed after the commodity symbol purge (realised only)"}}))
    for i in range(0, len(ops), BATCH):
        await coll.bulk_write(ops[i:i + BATCH], ordered=False)
    return len(ops)


async def rebuild_after(db, stamp: str) -> dict:
    """Scores from what remains (the engine's own rescore_all), equity replayed, skip counters reset."""
    from app.services import commodity_engine as ce
    from app.services import top10_books as t10
    rb = _rank_band()

    done = {"scores": await ce.rescore_all()}
    fields = {"opened_at": 1, "closed_at": 1, "updated_at": 1, "status": 1, "realized_pnl": 1, "capital_deployed": 1}
    desk = [p async for p in db["commodity_positions"].find({}, fields)]
    done["commodity_equity"] = await _rebuild_equity(db["commodity_equity"], {}, desk, ce.INITIAL_CAPITAL, stamp)
    n = 0
    for book in t10.book_keys("commodity"):
        rows = [p async for p in db["top10_book_positions"].find({"desk": "commodity", "book": book}, fields)]
        n += await _rebuild_equity(db["top10_book_equity"], {"desk": "commodity", "book": book}, rows,
                                   t10.book_capital("commodity", book), stamp)
    done["top10_book_equity"] = n
    n = 0
    for book in (sorted({d.get("book") async for d in db["rank_band_equity"].find({}, {"book": 1})} - {None})
                 if rb is not None else []):
        rows = [p async for p in db["rank_band_positions"].find({"book": book}, fields)]
        n += await _rebuild_equity(db["rank_band_equity"], {"book": book}, rows, rb.book_capital(book), stamp)
    done["rank_band_equity"] = n
    r1 = await db["top10_book_scores"].update_many({"desk": "commodity"}, {"$set": {"skipped": {}}})
    r2 = await db["rank_band_scores"].update_many({}, {"$set": {"skipped": {}}})
    done["skip_counters_reset"] = r1.modified_count + r2.modified_count
    return done


def _rank_band():
    """The rank-band books' module, or None where this tree does not have it (its collections are then
    empty and there is nothing of it to rebuild)."""
    try:
        from app.services import rank_band_books
        return rank_band_books
    except ImportError:
        return None


def preflight() -> None:
    """Load everything the rebuild needs BEFORE the first write, so a missing module stops the run while
    nothing has been deleted."""
    from app.services import commodity_engine, top10_books  # noqa: F401
    from tradingai_shared import mcx_calendar  # noqa: F401
    _rank_band()


# ── backup, apply, restore ─────────────────────────────────────────────────────────────────


def mcx_open_now() -> bool:
    from tradingai_shared.mcx_calendar import is_open
    return bool(is_open(datetime.now(IST)))


async def write_backup(path: Path, db, fdb, plan: dict, stamp: str) -> dict:
    """Every row to delete, every document to rebuild - into one file, then read back and counted."""
    stores = {label: coll for label, coll, _ in deletion_targets(db, fdb)}
    deleted: dict[str, list] = {}
    for label, s in plan["stores"].items():
        docs = []
        for i in range(0, len(s["ids"]), BATCH):
            docs += [d async for d in stores[label].find({"_id": {"$in": s["ids"][i:i + BATCH]}})]
        if len(docs) != len(s["ids"]):
            raise RuntimeError(f"backup of {label}: read {len(docs)} of {len(s['ids'])} rows - refusing")
        deleted[label] = docs
    replaced = {}
    for label, coll, scope in rebuild_scopes(db):
        replaced[label] = {"filter": scope, "docs": [d async for d in coll.find(scope)]}
    payload = {"meta": {"stamp": stamp, "keep": plan["keep"], "delete_set": plan["delete_set"],
                        "made_at": datetime.now(timezone.utc).isoformat(), "total": plan["total"]},
               "deleted": deleted, "replaced": replaced}
    tmp = path.with_suffix(path.suffix + ".part")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        fh.write(json_util.dumps(payload))
    with gzip.open(tmp, "rt", encoding="utf-8") as fh:
        back = json_util.loads(fh.read())
    for label, docs in deleted.items():
        if len(back["deleted"].get(label, [])) != len(docs):
            raise RuntimeError(f"backup verify failed for {label} - refusing")
    for label, rep in replaced.items():
        if len(back["replaced"].get(label, {}).get("docs", [])) != len(rep["docs"]):
            raise RuntimeError(f"backup verify failed for {label} - refusing")
    tmp.replace(path)
    return {"deleted": {k: len(v) for k, v in deleted.items()},
            "replaced": {k: len(v["docs"]) for k, v in replaced.items()}, "bytes": path.stat().st_size}


async def apply_purge(db, fdb, keep: set[str], known: set[str], *, confirm: str, backup_dir: Path,
                      force_hours: bool = False, rebuild=rebuild_after) -> dict:
    plan = await plan_purge(db, fdb, keep, known)
    if confirm != confirm_phrase(plan):
        raise SystemExit(f'refused: --confirm must be exactly "{confirm_phrase(plan)}" (got "{confirm}")')
    preflight()
    if not force_hours and mcx_open_now():
        raise SystemExit("refused: MCX is open - run after 23:55 IST or before 09:00 IST (or --force-hours)")
    backup_dir.mkdir(parents=True, exist_ok=True)
    need = 3 * 3000 * (plan["total"] + 50000) + 50 * 2**20      # generous: 3 KB a row, x3, + 50 MB
    free = shutil.disk_usage(backup_dir).free
    if free < need:
        raise SystemExit(f"refused: {free / 2**20:.0f} MB free in {backup_dir}, want {need / 2**20:.0f} MB")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"commodity_purge_{stamp}.json.gz"
    backed = await write_backup(path, db, fdb, plan, stamp)
    print(f"backup written and verified: {path} ({backed['bytes'] / 2**20:.1f} MB) {backed}")
    stores = {label: coll for label, coll, _ in deletion_targets(db, fdb)}
    deleted = {}
    for label, s in plan["stores"].items():
        n = 0
        for i in range(0, len(s["ids"]), BATCH):
            r = await stores[label].delete_many({"_id": {"$in": s["ids"][i:i + BATCH]}})
            n += r.deleted_count
        deleted[label] = n
    rebuilt = await rebuild(db, stamp)
    left = await plan_purge(db, fdb, keep, known)
    return {"backup": str(path), "deleted": deleted, "rebuilt": rebuilt, "left_of_the_eight": left["total"]}


async def restore(path: Path, db, fdb) -> dict:
    """Put every deleted row back; put every rebuilt scope back exactly as it was."""
    from pymongo.errors import BulkWriteError

    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json_util.loads(fh.read())
    stores = {label: coll for label, coll, _ in deletion_targets(db, fdb)}
    out = {"inserted": {}, "replaced": {}}
    for label, docs in data["deleted"].items():
        if label not in stores:
            print(f"  {label}: its database is not reachable here - skipped ({len(docs)} rows NOT restored)")
            continue
        n = 0
        for i in range(0, len(docs), BATCH):
            try:
                r = await stores[label].insert_many(docs[i:i + BATCH], ordered=False)
                n += len(r.inserted_ids)
            except BulkWriteError as e:                   # rows already back: duplicates are fine
                n += e.details.get("nInserted", 0)
        out["inserted"][label] = n
    scopes = {label: coll for label, coll, _ in rebuild_scopes(db)}
    for label, rep in data["replaced"].items():
        coll = scopes[label]
        await coll.delete_many(rep["filter"])
        if rep["docs"]:
            for i in range(0, len(rep["docs"]), BATCH):
                await coll.insert_many(rep["docs"][i:i + BATCH], ordered=False)
        out["replaced"][label] = len(rep["docs"])
    return out


# ── command line ───────────────────────────────────────────────────────────────────────────


async def _main(args) -> int:
    from app.core.db import db
    from app.services import intraday_signal_ledger as ledger
    from app.services.commodity_bars import LIQUID_UNDERLYINGS

    fdb = ledger._db() if getattr(ledger, "ENABLED", False) else None
    if fdb is None:
        print("NOTE: FACTORY_MONGO_URL is not set here - the AI Approved records (box-local) are not touched.")
    if args.restore:
        print(await restore(Path(args.restore), db, fdb))
        return 0
    keep = {k.strip().upper() for k in args.keep.split(",") if k.strip()}
    known = {u.strip().upper() for u in LIQUID_UNDERLYINGS}
    if not keep <= known:
        raise SystemExit(f"refused: {sorted(keep - known)} are not commodity underlyings ({sorted(known)})")
    if not args.apply:
        plan = await plan_purge(db, fdb, keep, known)
        print_plan(plan)
        print(f'\nDRY RUN - nothing written. To apply: --apply --confirm "{confirm_phrase(plan)}"')
        return 0
    print(await apply_purge(db, fdb, keep, known, confirm=args.confirm or "", backup_dir=Path(args.backup_dir),
                            force_hours=args.force_hours))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", default=",".join(KEEP_DEFAULT), help="underlyings to keep (default: %(default)s)")
    ap.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    ap.add_argument("--confirm", help='exactly "DELETE <n> ROWS", as the dry run printed')
    ap.add_argument("--backup-dir", default=".", help="where the backup file is written")
    ap.add_argument("--restore", help="a backup file to put back")
    ap.add_argument("--force-hours", action="store_true", help="allow running while MCX is open")
    return asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
