"""Server-side P&L totals for the desks.

Every desk summary was written the same way: open a cursor over the positions collection
and add the numbers up in Python. On a desk with 6,763 closed positions that ships 6,763
documents across the internet from Atlas to compute six numbers, and it gets slower every
day the desk trades. Under any contention — the 180-second scheduler tick, another desk's
cycle — those transfers are what produced the multi-second stalls.

A `$group` does the same arithmetic inside the database and returns ONE row. Same figures,
constant transfer, and it stops degrading as history grows.

`$ifNull` on every field matters: open positions carry `realized_pnl: None` and closed ones
carry `unrealized_pnl: 0`, and a `$sum` over a null yields null for the whole group rather
than skipping it — which would silently zero a desk's P&L.
"""

from motor.motor_asyncio import AsyncIOMotorCollection

_FIELDS = {
    "deployed": "capital_deployed",
    "unrealized": "unrealized_pnl",
    "realized": "realized_pnl",
    "fees": "fees",
    "gross": "gross_pnl",
}


async def totals(coll: AsyncIOMotorCollection, match: dict | None = None) -> dict:
    """Sums plus a count for the matching positions, in one round trip."""
    group: dict = {"_id": None, "n": {"$sum": 1}}
    for out, field in _FIELDS.items():
        group[out] = {"$sum": {"$ifNull": [f"${field}", 0]}}
    pipe = [{"$match": match or {}}, {"$group": group}]
    async for row in coll.aggregate(pipe):
        return {k: round(float(row.get(k) or 0.0), 2) for k in _FIELDS} | {"n": int(row.get("n") or 0)}
    return {k: 0.0 for k in _FIELDS} | {"n": 0}


async def split(coll: AsyncIOMotorCollection, extra: dict | None = None) -> tuple[dict, dict]:
    """(open, closed) totals in ONE aggregation rather than two.

    Grouping on a computed key instead of running two pipelines halves the round trips,
    which is the part that actually costs time here."""
    match = dict(extra or {})
    group: dict = {"_id": {"$cond": [{"$eq": ["$status", "OPEN"]}, "OPEN", "CLOSED"]},
                   "n": {"$sum": 1}}
    for out, field in _FIELDS.items():
        group[out] = {"$sum": {"$ifNull": [f"${field}", 0]}}
    pipe = [{"$match": match}, {"$group": group}]
    blank = {k: 0.0 for k in _FIELDS} | {"n": 0}
    out = {"OPEN": dict(blank), "CLOSED": dict(blank)}
    async for row in coll.aggregate(pipe):
        key = row["_id"]
        out[key] = {k: round(float(row.get(k) or 0.0), 2) for k in _FIELDS} | {"n": int(row.get("n") or 0)}
    return out["OPEN"], out["CLOSED"]


async def since(coll: AsyncIOMotorCollection, start, extra: dict | None = None) -> float:
    """Today's P&L: realised on positions closed since `start` plus unrealised on ones
    opened since, in one aggregation instead of two cursor scans."""
    base = dict(extra or {})
    pipe = [
        {"$match": {**base, "$or": [
            {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}},
            {"status": "OPEN", "opened_at": {"$gte": start}},
        ]}},
        {"$group": {"_id": None, "pnl": {"$sum": {"$add": [
            {"$ifNull": ["$realized_pnl", 0]}, {"$ifNull": ["$unrealized_pnl", 0]}]}}}},
    ]
    async for row in coll.aggregate(pipe):
        return round(float(row.get("pnl") or 0.0), 2)
    return 0.0
