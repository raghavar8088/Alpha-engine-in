"""The desk's own database (alpha_engine_premium_intraday on the box's second MongoDB). Nothing else is written.

WRITE GUARD: the only handle this class exposes is the desk's own Database; every write goes through it. The one
foreign read - the Intraday Stocks tournament's decision ledger, for following imported strategies forward - uses a
separate read-only helper that only calls find(). tests/test_isolation.py records every command the desk sends and
fails on any write outside this database.

Size: the box's disk is nearly full, so rows are small, journals expire after JOURNAL_DAYS, and a day's document
keeps trimmed checkpoint tables only.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

log = logging.getLogger("pis.store")
DB_NAME = os.getenv("PIS_MONGO_DB", "alpha_engine_premium_intraday")
JOURNAL_DAYS = int(os.getenv("PIS_JOURNAL_DAYS", "180"))


class Store:
    def __init__(self, url: str, db_name: str = DB_NAME, client=None):
        if client is None:
            from pymongo import MongoClient
            client = MongoClient(url, serverSelectionTimeoutMS=5000, maxPoolSize=4, appname="premium-intraday")
        self._client = client
        self.db = client[db_name]
        self.name = db_name

    # ── setup ───────────────────────────────────────────────────────────────────
    def ensure_indexes(self) -> dict:
        """Never raises (a failed index must not stop the desk)."""
        made, failed = 0, 0
        specs = [("journal", [("day", 1), ("k", 1), ("seq", 1)], {}),
                 ("journal", [("at", 1)], {"expireAfterSeconds": JOURNAL_DAYS * 86400}),
                 ("positions", [("status", 1), ("book", 1), ("t_entry", -1)], {}),
                 ("positions", [("day", 1)], {}),
                 ("alerts", [("resolved", 1), ("t", -1)], {})]
        for coll, keys, opts in specs:
            try:
                self.db[coll].create_index(keys, **opts)
                made += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.warning("index %s %s: %s", coll, keys, exc)
        return {"made": made, "failed": failed}

    # ── control and heartbeat ──────────────────────────────────────────────────
    def control(self) -> dict:
        try:
            return self.db.control.find_one({"_id": "control"}) or {"enabled": True}
        except Exception as exc:  # noqa: BLE001 - unreadable switch: keep the last known state (caller decides)
            log.warning("control unreadable: %s", exc)
            return {"enabled": None, "error": str(exc)[:200]}

    def heartbeat(self, doc: dict) -> None:
        try:
            self.db.status.update_one({"_id": "worker"}, {"$set": {**doc, "t": datetime.now(timezone.utc)}}, upsert=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("heartbeat: %s", exc)

    # ── day document ───────────────────────────────────────────────────────────
    def day(self, day: str) -> dict | None:
        return self.db.days.find_one({"_id": day})

    def set_day(self, day: str, fields: dict, once: tuple = ()) -> None:
        """Keys in `once` (checkpoint snapshots) are written only if absent: what the desk knew at a checkpoint is
        never overwritten by a later recomputation (a restart). Other keys are plain updates."""
        try:
            self.db.days.update_one({"_id": day}, {"$setOnInsert": {"created": datetime.now(timezone.utc)}}, upsert=True)
            for k in once:
                if k in fields:
                    self.db.days.update_one({"_id": day, k: {"$exists": False}}, {"$set": {k: fields[k]}})
            rest = {k: v for k, v in fields.items() if k not in once}
            if rest:
                self.db.days.update_one({"_id": day}, {"$set": rest})
        except Exception as exc:  # noqa: BLE001
            log.warning("day %s: %s", day, exc)

    # ── journal: deterministic ids, insert-only ────────────────────────────────
    def add_journal(self, rows: list) -> int:
        if not rows:
            return 0
        from pymongo.errors import BulkWriteError
        now = datetime.now(timezone.utc)
        docs = [{**r, "at": now} for r in rows]
        try:
            res = self.db.journal.insert_many(docs, ordered=False)
            return len(res.inserted_ids)
        except BulkWriteError as e:                      # duplicates after a restart: the first record stands
            return e.details.get("nInserted", 0)
        except Exception as exc:  # noqa: BLE001
            log.warning("journal: %s", exc)
            return 0

    def journal_keys(self, day: str) -> list:
        return list(self.db.journal.find({"day": day, "kind": {"$in": ["entry", "rejected", "setup_end"]}},
                                         {"strategy": 1, "variant": 1, "level": 1, "symbol": 1, "side": 1}))

    # ── positions and books ────────────────────────────────────────────────────
    def save_position(self, p, day: str) -> None:
        d = asdict(p)
        pid = d.pop("pid")
        entry_fields = {k: d[k] for k in ("book", "strategy", "variant", "level", "symbol", "sector", "side", "qty",
                                          "qty_wanted", "ref", "entry", "stop", "target", "slip_bp", "planned_risk",
                                          "k_entry", "t_entry", "time_exit_min", "notional", "partial", "knew")}
        exit_fields = {k: d[k] for k in ("status", "exit", "exit_ref", "k_exit", "t_exit", "reason", "gross", "fees",
                                         "net", "r_net", "failed_exit", "holes")}
        try:
            self.db.positions.update_one({"_id": pid}, {"$setOnInsert": {**entry_fields, "day": day},
                                                         "$set": exit_fields}, upsert=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("position %s: %s", pid, exc)

    def positions(self, query: dict) -> list:
        return list(self.db.positions.find(query))

    def book_state(self, name: str) -> dict | None:
        return self.db.books.find_one({"_id": name})

    def save_book(self, name: str, doc: dict) -> None:
        try:
            self.db.books.update_one({"_id": name}, {"$set": {**doc, "updated": datetime.now(timezone.utc)}}, upsert=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("book %s: %s", name, exc)

    def registry(self) -> dict:
        return {d["_id"]: d for d in self.db.registry.find({})}

    def set_registry(self, sid: str, doc: dict) -> None:
        self.db.registry.update_one({"_id": sid}, {"$set": doc}, upsert=True)

    # ── alerts ─────────────────────────────────────────────────────────────────
    def alert(self, key: str, doc: dict) -> None:
        try:
            self.db.alerts.update_one({"_id": key}, {"$set": {**doc, "t": datetime.now(timezone.utc)},
                                                      "$setOnInsert": {"first": datetime.now(timezone.utc)}}, upsert=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert: %s", exc)

    def resolve_alert(self, key: str, note: str) -> None:
        try:
            self.db.alerts.update_one({"_id": key}, {"$set": {"resolved": True, "resolved_note": note,
                                                              "resolved_at": datetime.now(timezone.utc)}})
        except Exception as exc:  # noqa: BLE001
            log.warning("alert resolve: %s", exc)


class LedgerReader:
    """Read-only view of the tournament's decision ledger (another module's database): find() only."""

    def __init__(self, client, db_name: str = "alpha_engine_intraday", coll: str = "intraday_signal_ledger"):
        self._c = client[db_name][coll]

    def rows(self, day: str, sids: set, since=None) -> list:
        q = {"d": day, "sid": {"$in": sorted(sids)}}
        if since is not None:
            q["t"] = {"$gt": since}
        return list(self._c.find(q, {"_id": 0}).sort("t", 1).limit(20000))
