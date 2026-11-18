"""Remove every commodity but the desk's own contracts from the Commodity Trading module's records.

The owner's decision (18 Nov 2026): Commodity Trading keeps natural gas and crude oil only, in both sizes -
NATGASMINI, CRUDEOILM, NATURALGAS and CRUDEOIL (first the two minis were named; the full-size two were kept
as well when asked). The other six underlyings' records (GOLD, GOLDM, SILVER, SILVERM, COPPER, ZINC) are
deleted from this module. The desk stops TRADING them in commodity_engine.DESK_UNDERLYINGS; this script
removes their HISTORY. The keep list is --keep (default: the desk's own DESK_UNDERLYINGS).

WHAT IT TOUCHES - and nothing else
  main database (Atlas)
    commodity_positions, commodity_trades            rows of the six                          DELETED
    top10_book_positions {desk: "commodity"}          Top 10 Paper Trade books' copies           DELETED
    rank_band_positions                               Top 5 / 5-10 / 10-15 / 15-20 books' copies DELETED
    commodity_scores                                  recomputed from what remains (rescore_all) REBUILT
    commodity_equity, top10_book_equity {desk:
      "commodity"}, rank_band_equity                  replayed from what remains, same times     REBUILT
    top10_book_scores {desk: "commodity"} and
      rank_band_scores: `skipped`                     counted across all commodities, not
                                                      attributable to one - restart at zero       RESET
  the box's local MongoDB (intraday_signal_ledger._db(), FACTORY_MONGO_URL)
    ai_positions, ai_gate_decisions {module: "commodity"}   rows of the six                      DELETED

A row is "of the six" when its symbol's underlying (the letters before a contract's date, so
NATGASMINI26NOVFUT is NATGASMINI) is one of commodity_bars.LIQUID_UNDERLYINGS that is not kept. A row with
no symbol, or an underlying outside that list, is KEPT and reported - nothing is deleted by inference.

NOT TOUCHED: the bar store (commodity_bars - the Gold desk, the Pre-Live desk and the Strategy Factory read
it), the Commodity Lab (its trial count must only grow, or its luck correction understates the tries),
every real-money record, and every other module (Commodity Positions, Commodity Auto, Pre-Live Commodity,
Natural Gas book, Gold desk, Commodity Options).

SAFETY
  * Dry run by default: it prints what it would do, and the exact confirmation to type.
  * --apply needs --confirm "DELETE <n> ROWS" with the count the dry run printed.
  * Before any write, every document it will delete or rebuild is STREAMED into ONE gzipped file: one
    canonical extended-JSON line per document (json_util: exact types, exact restore), a meta line first
    and an end line with the counts last. The file is read back and counted before anything is deleted.
    Memory holds one batch at a time, so the run fits a 400 MB container on the box.
  * Disk: it refuses unless the backup still leaves --min-free-mb free (default 150 - the box's own MongoDB
    and Docker write to the same disk, which had ~380 MB free on 18 Nov 2026), sizing the backup at 1 KB a
    document (real rows measured 0.17-0.29 KB gzipped). While writing it re-checks the disk, and stops -
    removing the partial file, nothing deleted - if the disk falls below that.
  * --restore <file> checks the whole file first (a cut-short file restores nothing), then puts every
    deleted row back and every rebuilt collection back as it was. It can be run again safely.
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

KEEP_DEFAULT = ("NATGASMINI", "CRUDEOILM", "NATURALGAS", "CRUDEOIL")     # = commodity_engine.DESK_UNDERLYINGS
BATCH = 500
IST = timezone(timedelta(hours=5, minutes=30))
_BASE = re.compile(r"^([A-Z]+?)(?=\d|$)")
BACKUP_FORMAT = "commodity-purge-jsonl-1"
EST_BACKUP_BYTES_PER_DOC = 1024     # one gzipped canonical-JSON line; real rows measured 165-294 B (18 Nov 2026)
MIN_FREE_MB_DEFAULT = 150           # left free on the backup's disk: the box's local MongoDB and Docker share it
_JSON = json_util.CANONICAL_JSON_OPTIONS


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


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def disk_check(free: int, docs: int, min_free: int) -> tuple[bool, int]:
    """(room?, bytes wanted): a backup of `docs` documents at EST_BACKUP_BYTES_PER_DOC, plus `min_free` kept."""
    need = docs * EST_BACKUP_BYTES_PER_DOC + min_free
    return free >= need, need


def _nz(counts: dict) -> dict:
    return {k: v for k, v in counts.items() if v}


def _lines(path: Path):
    """The backup's records, one at a time."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json_util.loads(line)


def backup_counts(path: Path) -> dict:
    """Read a backup through and count its documents. Refuses a file without its meta or end line, or
    whose documents disagree with the end line's counts - a file cut short."""
    seen: dict[str, Counter] = {"deleted": Counter(), "replaced": Counter()}
    meta = end = None
    for rec in _lines(path):
        kind = rec.get("kind")
        if kind == "meta":
            meta = rec
        elif kind == "end":
            end = rec
        elif kind in seen:
            seen[kind][rec["store"]] += 1
    if meta is None or meta.get("format") != BACKUP_FORMAT or end is None:
        raise RuntimeError(f"{path}: not a complete {BACKUP_FORMAT} backup (meta or end line missing) - refusing")
    got = {k: _nz(dict(v)) for k, v in seen.items()}
    if got != {k: _nz(end.get(k, {})) for k in seen}:
        raise RuntimeError(f"{path}: documents {got} disagree with the end line {end} - refusing")
    return {k: dict(end.get(k, {})) for k in seen}


async def write_backup(path: Path, db, fdb, plan: dict, stamp: str, *,
                       min_free: int = MIN_FREE_MB_DEFAULT * 2**20) -> dict:
    """Every row to delete and every document to rebuild, STREAMED into one gzipped file (one canonical
    JSON line each, meta line first, counts on the end line), then read back and counted. Memory holds one
    batch at a time. The disk is re-checked as the file grows; below `min_free` the write stops and the
    partial file is removed. Nothing has been deleted at that point."""
    stores = {label: coll for label, coll, _ in deletion_targets(db, fdb)}
    tmp = path.with_suffix(path.suffix + ".part")
    counts: dict[str, dict] = {"deleted": {}, "replaced": {}}

    def room() -> None:
        free = _free_bytes(path.parent)
        if free < min_free:
            raise SystemExit(f"refused: the disk fell to {free / 2**20:.0f} MB free while the backup was written "
                             f"(keeping {min_free / 2**20:.0f} MB) - stopped, partial file removed, nothing deleted")

    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            def put(rec: dict) -> None:
                fh.write(json_util.dumps(rec, json_options=_JSON) + "\n")

            put({"kind": "meta", "format": BACKUP_FORMAT, "stamp": stamp, "keep": plan["keep"],
                 "delete_set": plan["delete_set"], "made_at": datetime.now(timezone.utc).isoformat(),
                 "total": plan["total"]})
            for label, s in plan["stores"].items():
                n = 0
                for i in range(0, len(s["ids"]), BATCH):
                    async for d in stores[label].find({"_id": {"$in": s["ids"][i:i + BATCH]}}):
                        put({"kind": "deleted", "store": label, "doc": d})
                        n += 1
                    room()
                if n != len(s["ids"]):
                    raise RuntimeError(f"backup of {label}: read {n} of {len(s['ids'])} rows - refusing")
                counts["deleted"][label] = n
            for label, coll, scope in rebuild_scopes(db):
                put({"kind": "scope", "store": label, "filter": scope})
                n = 0
                async for d in coll.find(scope):
                    put({"kind": "replaced", "store": label, "doc": d})
                    n += 1
                    if n % BATCH == 0:
                        room()
                counts["replaced"][label] = n
            room()
            put({"kind": "end", **counts})
        back = backup_counts(tmp)
        if {k: _nz(v) for k, v in back.items()} != {k: _nz(v) for k, v in counts.items()}:
            raise RuntimeError(f"backup verify failed: wrote {counts}, read back {back} - refusing")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return {**counts, "bytes": path.stat().st_size}


async def apply_purge(db, fdb, keep: set[str], known: set[str], *, confirm: str, backup_dir: Path,
                      force_hours: bool = False, rebuild=rebuild_after,
                      min_free_mb: int = MIN_FREE_MB_DEFAULT) -> dict:
    plan = await plan_purge(db, fdb, keep, known)
    if confirm != confirm_phrase(plan):
        raise SystemExit(f'refused: --confirm must be exactly "{confirm_phrase(plan)}" (got "{confirm}")')
    preflight()
    if not force_hours and mcx_open_now():
        raise SystemExit("refused: MCX is open - run after 23:55 IST or before 09:00 IST (or --force-hours)")
    backup_dir.mkdir(parents=True, exist_ok=True)
    min_free = min_free_mb * 2**20
    docs = plan["total"] + sum([await coll.count_documents(scope) for _, coll, scope in rebuild_scopes(db)])
    free = _free_bytes(backup_dir)
    ok, need = disk_check(free, docs, min_free)
    if not ok:
        raise SystemExit(f"refused: {free / 2**20:.0f} MB free in {backup_dir}; a backup of {docs:,} documents "
                         f"is sized at {(need - min_free) / 2**20:.0f} MB and {min_free_mb} MB must stay free")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"commodity_purge_{stamp}.json.gz"
    backed = await write_backup(path, db, fdb, plan, stamp, min_free=min_free)
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
    return {"backup": str(path), "deleted": deleted, "rebuilt": rebuilt, "left_to_delete": left["total"]}


async def restore(path: Path, db, fdb) -> dict:
    """Put every deleted row back; put every rebuilt scope back exactly as it was. The whole file is checked
    first - a cut-short file restores nothing - then streamed back in batches. Safe to run again: rows
    already back are skipped as duplicates, and each rebuilt scope is cleared before it is refilled."""
    from pymongo.errors import BulkWriteError

    backup_counts(path)                                   # raises on an incomplete file, before any write
    stores = {label: coll for label, coll, _ in deletion_targets(db, fdb)}
    scopes = {label: coll for label, coll, _ in rebuild_scopes(db)}
    out: dict[str, dict] = {"inserted": {}, "replaced": {}, "not_reachable": {}}
    buf: list = []
    cur: tuple | None = None                              # (kind, store) the buffer belongs to

    async def flush() -> None:
        if not buf:
            return
        kind, label = cur
        if kind == "deleted":
            try:
                r = await stores[label].insert_many(buf, ordered=False)
                n = len(r.inserted_ids)
            except BulkWriteError as e:                   # rows already back: duplicates are fine
                n = e.details.get("nInserted", 0)
            out["inserted"][label] = out["inserted"].get(label, 0) + n
        else:
            await scopes[label].insert_many(buf, ordered=False)
            out["replaced"][label] = out["replaced"].get(label, 0) + len(buf)
        buf.clear()

    for rec in _lines(path):
        kind = rec.get("kind")
        if kind not in ("deleted", "scope", "replaced"):
            continue
        label = rec["store"]
        if kind == "scope":
            await flush()
            await scopes[label].delete_many(rec["filter"])
            out["replaced"].setdefault(label, 0)
            cur = ("replaced", label)
            continue
        if (kind, label) != cur:
            await flush()
            cur = (kind, label)
        if kind == "deleted" and label not in stores:
            out["not_reachable"][label] = out["not_reachable"].get(label, 0) + 1
            continue
        buf.append(rec["doc"])
        if len(buf) >= BATCH:
            await flush()
    await flush()
    for label, n in out["not_reachable"].items():
        print(f"  {label}: its database is not reachable here - skipped ({n} rows NOT restored)")
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
                            force_hours=args.force_hours, min_free_mb=args.min_free_mb))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", default=",".join(KEEP_DEFAULT), help="underlyings to keep (default: %(default)s)")
    ap.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    ap.add_argument("--confirm", help='exactly "DELETE <n> ROWS", as the dry run printed')
    ap.add_argument("--backup-dir", default=".", help="where the backup file is written")
    ap.add_argument("--restore", help="a backup file to put back")
    ap.add_argument("--force-hours", action="store_true", help="allow running while MCX is open")
    ap.add_argument("--min-free-mb", type=int, default=MIN_FREE_MB_DEFAULT,
                    help="MB that must stay free on the backup's disk (default: %(default)s)")
    return asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
