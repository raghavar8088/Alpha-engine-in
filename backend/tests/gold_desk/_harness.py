"""Test harness for the Gold Desk: import the real modules with no Mongo, no Angel, no network.

Puts the repo's own packages FIRST on the path (a stale `TradingAI/shared` shadows `shared/`
under this machine's default interpreter — D17), stubs the import-time drivers, and provides an
in-memory stand-in for the handful of Motor collection operations the desk uses.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "shared", ROOT / "strategy-service", ROOT / "broker-clients", ROOT / "backtesting-service",
          ROOT / "backend"):
    if str(p) in sys.path:
        sys.path.remove(str(p))
    sys.path.insert(0, str(p))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()
for name in ("redis", "redis.asyncio"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            root = name.split(".")[0]
            mod = sys.modules.get(root) or types.ModuleType(root)
            sys.modules[root] = mod
            if "." in name:
                sub = types.ModuleType(name)
                setattr(mod, name.split(".")[1], sub)
                sys.modules[name] = sub
if not hasattr(sys.modules["redis.asyncio"], "Redis"):
    # `broker_data` annotates a module-level `redis.Redis | None`, evaluated at import.
    sys.modules["redis.asyncio"].Redis = type("Redis", (), {})
    sys.modules["redis.asyncio"].from_url = lambda *a, **k: None
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── an in-memory collection ──────────────────────────────────────────────────────


def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _norm(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def _match(doc, q) -> bool:
    for k, cond in q.items():
        if k == "$or":
            if not any(_match(doc, c) for c in cond):
                return False
            continue
        val = _norm(_get(doc, k))
        if isinstance(cond, dict) and any(str(x).startswith("$") for x in cond):
            for op, arg in cond.items():
                arg = _norm(arg)
                if op == "$ne" and val == arg:
                    return False
                if op == "$in" and val not in arg:
                    return False
                if op == "$gte" and (val is None or val < arg):
                    return False
                if op == "$gt" and (val is None or val <= arg):
                    return False
                if op == "$lt" and (val is None or val >= arg):
                    return False
                if op == "$lte" and (val is None or val > arg):
                    return False
        elif val != _norm(cond):
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        self.docs.sort(key=lambda d: (_norm(_get(d, key)) is None, _norm(_get(d, key)) or 0), reverse=direction < 0)
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __aiter__(self):
        async def gen():
            for d in list(self.docs):
                yield dict(d)
        return gen()


class _Res:
    def __init__(self, n=0):
        self.deleted_count = n
        self.modified_count = n


class Coll:
    def __init__(self, name="c"):
        self.name = name
        self.docs: list[dict] = []
        self.writes = 0           # every insert / modifying update / delete

    # reads
    async def find_one(self, q=None, projection=None, sort=None):
        rows = [d for d in self.docs if _match(d, q or {})]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda d: _norm(_get(d, key)) or 0, reverse=direction < 0)
        return dict(rows[0]) if rows else None

    def find(self, q=None, projection=None):
        return _Cursor([d for d in self.docs if _match(d, q or {})])

    async def count_documents(self, q):
        return sum(1 for d in self.docs if _match(d, q))

    async def distinct(self, key, q=None):
        return sorted({_get(d, key) for d in self.docs if _match(d, q or {})} - {None})

    def aggregate(self, pipeline):
        rows = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                rows = [d for d in rows if _match(d, stage["$match"])]
            elif "$sort" in stage:
                for key, direction in reversed(list(stage["$sort"].items())):
                    rows.sort(key=lambda d: _norm(_get(d, key)) or 0, reverse=direction < 0)
            elif "$group" in stage:
                g = stage["$group"]
                if g["_id"] is not None:
                    raise NotImplementedError("grouped aggregate")
                out = {"_id": None}
                for field_name, spec in g.items():
                    if field_name == "_id":
                        continue
                    (op, arg), = spec.items()
                    if op != "$sum":
                        raise NotImplementedError(op)
                    total = 0
                    for d in rows:
                        if isinstance(arg, (int, float)):
                            total += arg
                        elif isinstance(arg, str):
                            total += _get(d, arg[1:]) or 0
                        elif isinstance(arg, dict) and "$cond" in arg:
                            (cmp, (a, b)), = arg["$cond"][0].items()
                            v = _get(d, a[1:]) or 0
                            hit = v > b if cmp == "$gt" else False
                            total += arg["$cond"][1] if hit else arg["$cond"][2]
                    out[field_name] = total
                rows = [out] if rows else []

        class _A:
            def __aiter__(self_inner):
                async def gen():
                    for r in rows:
                        yield r
                return gen()
        return _A()

    # writes
    async def insert_one(self, d):
        d = dict(d)
        if "_id" in d and any(x.get("_id") == d["_id"] for x in self.docs):
            raise RuntimeError("duplicate _id")
        d.setdefault("_id", f"{self.name}-{len(self.docs) + 1}-{id(d)}")
        self.docs.append(d)
        self.writes += 1
        return _Res(1)

    async def insert_many(self, ds, ordered=False):
        for d in ds:
            await self.insert_one(d)

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if _match(d, q):
                before = dict(d)
                for k, val in (upd.get("$set") or {}).items():
                    _set(d, k, val)
                if before != d:
                    self.writes += 1
                return _Res(1 if before != d else 0)
        if upsert:
            nd = {k: v for k, v in q.items() if not isinstance(v, dict)}
            for k, val in (upd.get("$set") or {}).items():
                _set(nd, k, val)
            for k, val in (upd.get("$setOnInsert") or {}).items():
                _set(nd, k, val)
            nd.setdefault("_id", f"{self.name}-{len(self.docs) + 1}")
            self.docs.append(nd)
            self.writes += 1
            return _Res(1)
        return _Res(0)

    async def delete_many(self, q):
        keep = [d for d in self.docs if not _match(d, q)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        self.writes += n
        return _Res(n)

    async def bulk_write(self, ops, ordered=False):
        for op in ops:
            await self.update_one(op._filter, op._doc, upsert=op._upsert)

    async def create_index(self, *a, **k):
        return "ok"


def _set(d, path, val):
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = val


FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + str(detail)) if detail not in ('', None) else ''}")
    if not ok:
        FAILURES.append(label)


def section(t):
    print(f"\n{t}\n{'-' * len(t)}")


def finish():
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all checks passed")
