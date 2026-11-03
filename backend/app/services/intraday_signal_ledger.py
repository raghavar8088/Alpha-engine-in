"""Decision ledger for the intraday tournament: every candidate signal, taken or not.

Phase 1 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md (gate 9, "record every decision"). Until now the
engine kept only COUNTS of what it turned down (`status["skipped"]` in intraday_v2_engine):
the trades it took were recorded in full, the signals it refused were not. A model meant to
tell good signals from bad ones (Phase 7) needs both, and so does any check that the engine
did what its rules say.

WHAT IS RECORDED
  intraday_signal_ledger   one row per candidate signal: when, which rule (and the version of
                           that rule), which stock, the side, the signal's price / stop /
                           target / trigger / priority, the stock's turnover and relative
                           volume, NIFTY's move since the open, how many slots the strategy had
                           in use and how many other strategies held the stock — and the
                           DECISION: "opened" (with the position id), "pending" (a stop-entry
                           was armed), or "rejected" (with the engine's own reason, the same
                           words as its skip counters). A stop-entry that later triggers gets a
                           second row (src "trigger") with that decision.
  intraday_ledger_closes   one row per evaluated bar close: the engine's own signal count beside
                           the rows written for it, so completeness is checkable at every
                           close; also the closes at which entries were blocked, and why.
  intraday_versions        what each rule / gate version string means (written once each).

VERSIONS. A rule version is a hash of the strategy's definition (family, timeframe, kind,
params) plus a hash of the rules' code; a gate version is a hash of the engine's limits
(slots, slot size, per-stock cap, loss breaker, entry window, cost model) plus the engine's,
fill model's and fee card's code. Any change makes a new version; nothing is edited in place.

WHERE. The box's second MongoDB (FACTORY_MONGO_URL — the compose `mongodb` service), never
Atlas: Atlas is the M0 tier near its 512 MB quota, and this is a few thousand rows a session.
Without FACTORY_MONGO_URL the ledger is OFF — it never falls back to Atlas. Rows expire after
INTRADAY_LEDGER_RETENTION_DAYS (default 180).

NEVER IN THE WAY. Recording is in memory; each close's rows go to the database in one batch,
written by a background task. A failed write is logged and counted, never raised into the
engine, and the engine never waits for the database.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("intraday_signal_ledger")

IST = timezone(timedelta(hours=5, minutes=30))
_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
_DB = os.getenv("INTRADAY_LEDGER_MONGO_DB", "alpha_engine_intraday")
ENABLED = bool(_URL) and os.getenv("INTRADAY_LEDGER", "1").strip().lower() not in ("0", "false", "no", "off")
RETENTION_DAYS = int(os.getenv("INTRADAY_LEDGER_RETENTION_DAYS", "180"))
ROWS = "intraday_signal_ledger"
CLOSES = "intraday_ledger_closes"
VERSIONS = "intraday_versions"

stats: dict = {"rows_written": 0, "closes_written": 0, "write_errors": 0, "undecided": 0,
               "last_error": None, "last_write": None}

_handle = None
_indexes_ready = False
_registered: set[str] = set()
_version_defs: dict[str, dict] = {}
_tasks: set = set()
_buf: list[dict] = []
_cur: dict | None = None
_ctx: dict = {"rv": {}, "nifty": None}
_gate: str | None = None


def _db():
    global _handle
    if _handle is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        _handle = AsyncIOMotorClient(_URL, serverSelectionTimeoutMS=5000, maxPoolSize=4)[_DB]
    return _handle


# ── versions ─────────────────────────────────────────────────────────────────────


def _code_fp(*modules: str) -> str:
    """Hash of these app.services modules' source files, read once at import."""
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for name in modules:
        try:
            with open(os.path.join(here, f"{name}.py"), "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(f"missing:{name}".encode())
    return h.hexdigest()[:12]


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


RULES_CODE = _code_fp("intraday_v2_strategies", "nifty_scalp_strategies")
ENGINE_CODE = _code_fp("intraday_v2_engine", "intraday_fills", "angel_fees")
_rule_cache: dict[str, str] = {}


def rule_version(spec) -> str:
    """'<definition hash>-<rules code hash>' for one strategy."""
    v = _rule_cache.get(spec.strategy_id)
    if v is None:
        d = {"strategy_id": spec.strategy_id, "family": spec.family, "tf": spec.tf,
             "kind": spec.kind, "params": spec.params}
        v = f"{_sha(d)}-{RULES_CODE}"
        _rule_cache[spec.strategy_id] = v
        _version_defs[v] = {"kind": "rule", "strategy_id": spec.strategy_id, "definition": d,
                            "rules_code": RULES_CODE}
    return v


def gate_version(config: dict) -> str:
    """'<limits hash>-<engine code hash>'; the latest one registered is stamped on rows."""
    global _gate
    v = f"{_sha(config)}-{ENGINE_CODE}"
    _version_defs[v] = {"kind": "gate", "definition": config, "engine_code": ENGINE_CODE}
    _gate = v
    return v


# ── recording (in memory, called by the engine) ──────────────────────────────────


def _num(x, nd: int = 4):
    try:
        return None if x is None else round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _levels(side: str, px, stop_dist, stop_price, target_dist, target_price):
    sign = 1 if side == "BUY" else -1
    stop = stop_price if stop_price is not None else (px - sign * stop_dist if px and stop_dist else None)
    tgt = target_price if target_price is not None else (px + sign * target_dist if px and target_dist else None)
    return _num(stop), _num(tgt)


def context(rvol_by_symbol: dict | None, nifty: float | None) -> None:
    """What the engine knew at this close: {symbol: (relative volume, in-play rank)}, NIFTY %."""
    _ctx["rv"], _ctx["nifty"] = rvol_by_symbol or {}, nifty


def _start(row: dict) -> None:
    global _cur
    finish()
    _cur = row


def begin(spec, sym: str, sig, at: datetime, member: dict | None = None, slots: int = 0,
          holders: int = 0) -> None:
    """A signal from a bar close is about to be judged (before the engine's first check)."""
    if not ENABLED:
        return
    rv, rank = (_ctx["rv"].get(sym) or (None, None))
    oco = [[leg[0], _num(leg[1])] for leg in sig.oco] if getattr(sig, "oco", None) else None
    side = "OCO" if oco else sig.side
    stop, tgt = (None, None) if oco else _levels(sig.side, sig.entry, sig.stop_dist, sig.stop_price,
                                                  sig.target_dist, sig.target_price)
    _start({"t": at.astimezone(timezone.utc), "d": at.astimezone(IST).date().isoformat(), "src": "close",
            "sid": spec.strategy_id, "rv": rule_version(spec), "gv": _gate, "sym": sym, "side": side,
            "px": _num(sig.entry), "stop": stop, "tgt": tgt, "trig": _num(sig.trigger), "oco": oco,
            "mb": sig.max_bars, "prio": _num(sig.priority),
            "turn": _num((member or {}).get("turnover_cr"), 1), "rvol": _num(rv, 3), "rk": rank,
            "nifty": _num(_ctx["nifty"], 3), "slots": slots, "hold": holders})


def begin_pending(x: dict, spec, member: dict | None = None, slots: int = 0, holders: int = 0) -> None:
    """An armed stop-entry has crossed its trigger and is about to be judged."""
    if not ENABLED:
        return
    now = datetime.now(timezone.utc)
    stop, tgt = _levels(x["side"], x.get("trigger"), x.get("stop_dist"), x.get("stop_price"),
                        x.get("target_dist"), None)
    _start({"t": now, "d": now.astimezone(IST).date().isoformat(), "src": "trigger",
            "sid": x["strategy_id"], "rv": rule_version(spec) if spec is not None else None, "gv": _gate,
            "sym": x["symbol"], "side": x["side"], "px": _num(x.get("trigger")), "stop": stop, "tgt": tgt,
            "trig": _num(x.get("trigger")), "oco": None, "mb": None, "prio": _num(x.get("priority")),
            "turn": _num((member or {}).get("turnover_cr"), 1), "rvol": None, "rk": None, "nifty": None,
            "slots": slots, "hold": holders,
            "armed": datetime.fromtimestamp(x["since"], timezone.utc) if x.get("since") else None})


def _decide(dec: str, why: str | None = None, pid: str | None = None) -> None:
    global _cur
    if _cur is None:
        return
    _cur.update({"dec": dec, "why": why, "pid": pid})
    _buf.append(_cur)
    _cur = None


def reject(why: str) -> None:
    """The engine's first reason wins; later skips for the same signal are not recorded."""
    _decide("rejected", why)


def pending() -> None:
    _decide("pending")


def opened(position_id: str) -> None:
    _decide("opened", pid=position_id)


def finish() -> None:
    """A signal left without a decision (an exception mid-way) is kept, labelled as such."""
    if _cur is not None:
        stats["undecided"] += 1
        _decide("undecided")


# ── writing (background, never raises) ──────────────────────────────────────────


def _spawn(coro) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _ensure(db) -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    ttl = RETENTION_DAYS * 86400
    await db[ROWS].create_index("t", expireAfterSeconds=ttl, name="ttl_t")
    await db[ROWS].create_index([("d", 1), ("sid", 1)], name="d_sid")
    await db[ROWS].create_index([("d", 1), ("dec", 1)], name="d_dec")
    await db[CLOSES].create_index("t", expireAfterSeconds=ttl, name="ttl_t")
    await db[CLOSES].create_index("d", name="d")
    _indexes_ready = True


async def _register(db) -> None:
    for v, d in list(_version_defs.items()):
        if v in _registered:
            continue
        await db[VERSIONS].update_one(
            {"_id": v}, {"$setOnInsert": {**d, "first_seen": datetime.now(timezone.utc)}}, upsert=True)
        _registered.add(v)


async def _write(rows: list[dict], close: dict | None) -> None:
    try:
        db = _db()
        await _ensure(db)
        await _register(db)
        if rows:
            await db[ROWS].insert_many(rows, ordered=False)
            stats["rows_written"] += len(rows)
        if close is not None:
            await db[CLOSES].replace_one({"_id": close["_id"]}, close, upsert=True)
            stats["closes_written"] += 1
        stats["last_write"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:  # noqa: BLE001 - the ledger must never break the engine
        stats["write_errors"] += 1
        stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("[ledger] write failed (%d rows): %s", len(rows), exc)


def _close_id(boundary: datetime) -> str:
    return boundary.astimezone(IST).strftime("%Y-%m-%dT%H:%M")


def flush(close: dict | None = None) -> None:
    """Hand the buffered rows (and, at a bar close, that close's summary) to a background
    write. `close`: {"boundary", "signals", "opened", "incomplete", "members", "nifty", "taken"}."""
    global _buf
    finish()
    rows, _buf = _buf, []
    if not ENABLED or (not rows and close is None):
        return
    doc = None
    if close is not None:
        b = close["boundary"]
        mine = [r for r in rows if r["src"] == "close"]
        counts = {k: sum(1 for r in mine if r["dec"] == k) for k in ("opened", "pending", "rejected", "undecided")}
        doc = {"_id": _close_id(b), "t": b.astimezone(timezone.utc), "d": b.astimezone(IST).date().isoformat(),
               "signals": close.get("signals"), "rows": len(mine), **counts,
               "incomplete": close.get("incomplete"), "members": close.get("members"),
               "nifty": _num(close.get("nifty"), 3), "taken": bool(close.get("taken", True)),
               "blocked": None, "gv": _gate, "written_at": datetime.now(timezone.utc)}
    _spawn(_write(rows, doc))


def blocked(boundary: datetime, why: str) -> None:
    """A bar close at which entries were not allowed (pause, Main Control, loss breaker)."""
    if not ENABLED:
        return
    _spawn(_write([], {"_id": _close_id(boundary), "t": boundary.astimezone(timezone.utc),
                       "d": boundary.astimezone(IST).date().isoformat(), "signals": 0, "rows": 0,
                       "taken": False, "blocked": why, "gv": _gate,
                       "written_at": datetime.now(timezone.utc)}))


# ── reading (the API) ────────────────────────────────────────────────────────────


def describe() -> dict:
    return {"enabled": ENABLED, "database": _DB if ENABLED else None, "retention_days": RETENTION_DAYS,
            "gate_version": _gate, "rules_code": RULES_CODE, "engine_code": ENGINE_CODE,
            "pending_writes": len(_tasks), **stats,
            **({} if ENABLED else {"why_off": "FACTORY_MONGO_URL is not set — the ledger never writes to Atlas"})}


async def summary(day: str | None = None) -> dict:
    """One day's decisions and the completeness check (rows written = signals evaluated)."""
    out = describe()
    if not ENABLED:
        return out
    db = _db()
    if not day:
        last = await db[CLOSES].find_one({}, {"d": 1}, sort=[("t", -1)])
        day = last["d"] if last else datetime.now(IST).date().isoformat()
    closes = [c async for c in db[CLOSES].find({"d": day}).sort("t", 1)]
    judged = [c for c in closes if c.get("taken", True) and not c.get("blocked")]
    mismatched = [{"close": c["_id"], "signals": c.get("signals"), "rows": c.get("rows")}
                  for c in judged if (c.get("signals") or 0) != (c.get("rows") or 0)]
    decisions: dict[str, dict] = {}
    reasons: dict[str, int] = {}
    async for r in db[ROWS].aggregate([{"$match": {"d": day}},
                                       {"$group": {"_id": {"src": "$src", "dec": "$dec", "why": "$why"},
                                                   "n": {"$sum": 1}}}]):
        k = r["_id"]
        src = decisions.setdefault(k.get("src") or "?", {})
        src[k.get("dec") or "?"] = src.get(k.get("dec") or "?", 0) + r["n"]
        if k.get("dec") == "rejected":
            reasons[k.get("why") or "?"] = reasons.get(k.get("why") or "?", 0) + r["n"]
    by_strategy: dict[str, dict] = {}
    async for r in db[ROWS].aggregate([{"$match": {"d": day, "src": "close"}},
                                       {"$group": {"_id": {"sid": "$sid", "dec": "$dec"}, "n": {"$sum": 1}}}]):
        s = by_strategy.setdefault(r["_id"]["sid"], {})
        s[r["_id"]["dec"]] = r["n"]
    storage = None
    try:
        cs = await db.command("collStats", ROWS)
        storage = {"rows": cs.get("count"), "data_mb": round((cs.get("size") or 0) / 1e6, 2),
                   "disk_mb": round(((cs.get("storageSize") or 0) + (cs.get("totalIndexSize") or 0)) / 1e6, 2)}
    except Exception:  # noqa: BLE001 - informational only
        pass
    signals = sum(c.get("signals") or 0 for c in judged)
    rows_written = sum(c.get("rows") or 0 for c in judged)
    return {**out, "day": day, "closes": len(closes), "closes_judged": len(judged),
            "blocked_closes": [{"close": c["_id"], "why": c.get("blocked")} for c in closes if c.get("blocked")],
            "signals": signals, "rows_at_closes": rows_written,
            "complete": bool(judged) and not mismatched,
            "mismatched_closes": mismatched[:20], "decisions": decisions,
            "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "by_strategy": by_strategy, "storage": storage}


async def rows(day: str | None = None, strategy_id: str | None = None, symbol: str | None = None,
               dec: str | None = None, limit: int = 200) -> list[dict]:
    if not ENABLED:
        return []
    q: dict = {"d": day or datetime.now(IST).date().isoformat()}
    if strategy_id:
        q["sid"] = strategy_id
    if symbol:
        q["sym"] = symbol.upper()
    if dec:
        q["dec"] = dec
    out = []
    async for r in _db()[ROWS].find(q, {"_id": 0}).sort("t", 1).limit(max(1, min(int(limit), 2000))):
        for k in ("t", "armed"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
        out.append(r)
    return out
