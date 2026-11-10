"""AI final gate: Claude reviews every new position in four paper modules (2026-11-10).

The owner asked for an AI final gate between a strategy's signal and its position on Intraday Stocks, Commodity
Trading, Gold Desk and Premium Strategies, run as an A/B test: each module keeps opening every position it opens
today, and each position the AI approves becomes a separate AI POSITION, with its own id and its own timestamps.
The AI book can then be compared with everything the module took, and with what the AI turned down.

HOW IT WORKS
- Every POLL_S seconds the gate reads each module's newly opened positions from that module's own records. No engine
  is edited; a module behaves exactly as before.
- A position first seen more than its module's look-back (minutes) after it opened is never reviewed: the AI does not
  judge a stale signal. Those still count in the module's own record, the control.
- What the AI is shown: the strategy, its rule, the side, entry, stop, target and costs, the bars that had CLOSED by
  the signal, the market index, and the strategy's own record before that moment. Nothing after the signal.
- Claude (AI_GATE_MODEL, default claude-sonnet-5-5, effort AI_GATE_EFFORT, default low) answers in a fixed JSON shape:
  take or skip, its probability of a net profit after costs, its confidence, reasons and the main risk.
- Fail closed (the owner's choice): no API key, an error, a timeout, a refusal or the module's daily cap means "not
  reviewed", and no AI position.
- An approval creates an AI position: ai_position_id AI-<MODULE>-YYYYMMDD-NNNN, the parent position's id, the signal
  time, the decision time (its opened_at), the parent's fill and size, then on the parent's close its exit, close time
  and the parent's realised P&L. The AI book copies the parent's fills, so the comparison is only about WHICH
  positions the AI picked. The decision comes seconds after the parent's fill; the lag is stored with each one.
- Every decision is stored once, with the model and the prompt version. Nothing is asked twice or re-judged later.

Records live in the box's local MongoDB beside the intraday decision ledger (FACTORY_MONGO_URL, never Atlas):
ai_gate_decisions (every reviewed position), ai_positions (the approved ones), ai_gate_state (id sequences).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("ai_gate")

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
MODEL = os.getenv("AI_GATE_MODEL", "claude-sonnet-5-5").strip()
EFFORT = os.getenv("AI_GATE_EFFORT", "low").strip()
TIMEOUT_S = float(os.getenv("AI_GATE_TIMEOUT_S", "60"))
POLL_S = max(10, int(os.getenv("AI_GATE_POLL_S", "30")))
CONCURRENCY = max(1, int(os.getenv("AI_GATE_CONCURRENCY", "4")))
MAX_TOKENS = 4000
PROMPT_VERSION = "2026-11-10.1"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Claude Sonnet 5.5 list prices, USD per million tokens (cache writes 1.25x input)
PRICE = {"in": 2.0, "out": 10.0, "cache_write": 2.5, "cache_read": 0.20}
DEC, POS, STATE = "ai_gate_decisions", "ai_positions", "ai_gate_state"
VOID_AFTER_S = 1800          # a premium trade missing this long after it was approved was replaced by its engine

MODULES: dict[str, dict] = {
    "intraday": {"code": "INT", "label": "Intraday Stocks", "lookback_min": 10, "daily_max": 700},
    "commodity": {"code": "COM", "label": "Commodity Trading", "lookback_min": 15, "daily_max": 400},
    "gold": {"code": "GLD", "label": "Gold Desk", "lookback_min": 20, "daily_max": 100},
    "premium": {"code": "PRM", "label": "Premium Strategies", "lookback_min": 40, "daily_max": 600},
}
for _part in os.getenv("AI_GATE_DAILY_MAX", "").split(","):           # e.g. "intraday=500,premium=300"
    _k, _, _v = _part.partition("=")
    if _k.strip() in MODULES and _v.strip().isdigit():
        MODULES[_k.strip()]["daily_max"] = int(_v)


def _ledger():
    from app.services import intraday_signal_ledger as ledger
    return ledger


def _enabled() -> bool:
    try:
        return bool(_ledger().ENABLED) and os.getenv("AI_GATE", "on").strip().lower() not in ("0", "off", "false", "no")
    except Exception:  # noqa: BLE001
        return False


ENABLED = _enabled()

SYSTEM = (
    "You are the final gate of a paper-trading desk. A mechanical strategy has just produced a position, and you "
    "decide whether it belongs in the AI-approved book: answer take or skip. You see the position as the strategy saw "
    "it: its rule, the side, entry, stop, target and costs, the bars that had closed by the signal, the market index "
    "and the strategy's own record. The data ends at the signal; assume nothing about later prices.\n\n"
    "Most mechanical intraday signals have no edge after costs, and costs are paid on every trade, so take a position "
    "only when the data gives a concrete reason to expect it to do better than a coin flip after costs. Weigh: reward "
    "to risk after costs; whether the trade goes with the instrument's own trend and the market's; how far price has "
    "already run before the entry; whether the stop sits inside the normal noise of recent bars; how much of the "
    "session is left; the strategy's record; and any event risk noted. A losing record is evidence against the rule, "
    "not a reason to expect a reversal.\n\n"
    "p_profit is your probability that this position ends with a net profit after costs. Take only when p_profit is "
    "at least 0.5 and nothing in the data is a clear red flag; otherwise skip. Be calibrated, not agreeable: a signal "
    "existing is not a reason to take it. Keep each reason to one short sentence about the numbers you were given."
)
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["take", "skip"]},
        "p_profit": {"type": "number"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "main_risk": {"type": "string"},
    },
    "required": ["decision", "p_profit", "confidence", "reasons", "main_risk"],
}

stats: dict = {"cycles": 0, "reviews": 0, "errors": 0, "last_cycle_at": None, "last_error": None, "running": False}


# ── small helpers ────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(t) -> datetime | None:
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(float(t), UTC)
    if isinstance(t, str):
        try:
            t = datetime.fromisoformat(t)
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _ist(t: datetime | None, fmt: str = "%d %b %H:%M") -> str:
    return t.astimezone(IST).strftime(fmt) if t else "-"


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _num(x, nd: int = 2) -> str:
    v = _f(x)
    return "-" if v is None else f"{v:,.{nd}f}"


def _side(x) -> str:
    if isinstance(x, (int, float)):
        return "BUY" if x > 0 else "SELL"
    return "BUY" if str(x).upper() in ("BUY", "LONG", "1") else "SELL"


def _rows_from_arrays(b, cutoff_ts: int, step_s: int, n: int) -> list[list]:
    """The last `n` bars of a Bars object (t, o, h, l, c, v arrays; t = bar start) that had CLOSED by cutoff_ts."""
    if b is None or not len(getattr(b, "t", ())):
        return []
    from bisect import bisect_right
    k = bisect_right(b.t, cutoff_ts - step_s)          # bars starting at or before cutoff - step have closed
    lo = max(0, k - n)
    return [[int(b.t[i]), float(b.o[i]), float(b.h[i]), float(b.l[i]), float(b.c[i]), float(b.v[i])] for i in range(lo, k)]


def _rows_from_objects(bars, cutoff: datetime, minutes: int, n: int) -> list[list]:
    """Bar objects (ts = bar start, open/high/low/close/volume) that had CLOSED by `cutoff`."""
    out = []
    for x in bars or []:
        ts = _aware(getattr(x, "ts", None))
        if ts is None or ts + timedelta(minutes=minutes) > cutoff:
            continue
        out.append([int(ts.timestamp()), float(x.open), float(x.high), float(x.low), float(x.close), float(x.volume or 0)])
    return out[-n:]


def _features(rows: list[list], p: dict) -> list[str]:
    """Plain facts from the pre-signal bars, so the model does not have to compute them."""
    out = []
    entry, stop, target = _f(p.get("entry")), _f(p.get("stop")), _f(p.get("target"))
    if rows:
        rng = [r[2] - r[3] for r in rows[-14:]]
        avg_rng = sum(rng) / len(rng) if rng else 0.0
        last = rows[-1][4]
        first_today = next((r for r in rows if _ist(_aware(r[0]), "%Y-%m-%d") == _ist(_aware(rows[-1][0]), "%Y-%m-%d")), rows[0])
        out.append(f"Last close {last:,.2f}; move since this session's first bar shown: "
                   f"{(last / first_today[1] - 1) * 100:+.2f}%.")
        if entry and stop and avg_rng > 0:
            out.append(f"Stop distance = {abs(entry - stop) / avg_rng:.2f} x the average range of the last {len(rng)} bars.")
        hi = max(r[2] for r in rows[-20:])
        lo = min(r[3] for r in rows[-20:])
        if hi > lo and entry:
            out.append(f"Entry sits at {(entry - lo) / (hi - lo) * 100:.0f}% of the last {min(20, len(rows))} bars' range.")
    if entry and stop:
        risk = abs(entry - stop)
        out.append(f"Stop {risk / entry * 100:.2f}% from entry.")
        if target:
            reward = abs(target - entry)
            out.append(f"Target {reward / entry * 100:.2f}% from entry; reward to risk {reward / risk:.2f} before costs." if risk else "")
        else:
            out.append("No fixed target: the rule exits on its stop, a time stop or the session close.")
    return [x for x in out if x]


def build_prompt(module: str, p: dict, ctx: dict) -> str:
    """The question for one position. Pure: everything comes from `p` (the position) and `ctx` (data to its signal)."""
    label = MODULES[module]["label"]
    lines = [f"Module: {label} (paper trading)."]
    lines.append(f"Strategy: {p.get('strategy_name') or p.get('strategy_id')} [{p.get('strategy_id')}]"
                 + (f", timeframe {p['timeframe']}" if p.get("timeframe") else "") + ".")
    if p.get("rule"):
        lines.append(f"Its rule: {p['rule']}")
    rec = ctx.get("record") or {}
    if rec.get("n"):
        cur = p.get("currency") or "INR"
        lines.append(f"Its record before this signal ({rec.get('window', 'recent')}): {rec['n']} closed trades, "
                     f"{rec['wins'] / rec['n'] * 100:.0f}% won, net {cur} {rec['net']:,.0f} "
                     f"(average {cur} {rec['net'] / rec['n']:,.0f} a trade).")
    else:
        lines.append("Its record before this signal: no closed trades yet.")
    sig = p.get("signal_time")
    lines.append(f"Signal: {p['side']} {p['symbol']} ({p.get('market') or label}) at {_ist(sig, '%a %d %b %Y %H:%M IST')}. "
                 f"Entry {_num(p.get('entry'), 4)}, stop {_num(p.get('stop'), 4)}, "
                 f"target {_num(p.get('target'), 4) if p.get('target') is not None else 'none'}.")
    if p.get("cost_note"):
        lines.append(f"Costs: {p['cost_note']}")
    if p.get("exit_note"):
        lines.append(f"Exit rules: {p['exit_note']}")
    for n in _features(ctx.get("bars") or [], p):
        lines.append(n)
    if ctx.get("bars"):
        lines.append(f"Bars before the signal ({ctx.get('bar_label', '')}; IST time, open, high, low, close, volume), oldest first:")
        for r in ctx["bars"]:
            lines.append(f"{_ist(_aware(r[0]))} {r[1]:.4g} {r[2]:.4g} {r[3]:.4g} {r[4]:.4g} {r[5]:.0f}")
    else:
        lines.append("No bars are available to this review for this market.")
    if ctx.get("index"):
        idx = ctx["index"]
        lines.append(f"{ctx.get('index_label', 'Index')} closes before the signal: "
                     + ", ".join(f"{_ist(_aware(r[0]), '%H:%M')} {r[4]:,.1f}" for r in idx))
    for n in ctx.get("notes") or []:
        lines.append(n)
    if p.get("rationale"):
        lines.append(f"The strategy's own note: {p['rationale']}")
    lines.append("Decide: take or skip this position for the AI-approved book.")
    return "\n".join(lines)


def parse_answer(text: str) -> dict:
    """Validate the model's JSON. Raises ValueError when it is not usable."""
    d = json.loads(text)
    dec = str(d.get("decision", "")).strip().lower()
    if dec not in ("take", "skip"):
        raise ValueError(f"decision {dec!r}")
    p = _f(d.get("p_profit"))
    if p is None:
        raise ValueError("no p_profit")
    conf = str(d.get("confidence", "")).strip().lower()
    reasons = [str(x).strip()[:300] for x in (d.get("reasons") or []) if str(x).strip()][:4]
    return {"decision": dec, "p_profit": round(min(max(p, 0.0), 1.0), 3),
            "confidence": conf if conf in ("low", "medium", "high") else "low",
            "reasons": reasons, "main_risk": str(d.get("main_risk") or "").strip()[:300]}


def cost_usd(usage: dict) -> float:
    return round((usage.get("input_tokens", 0) * PRICE["in"] + usage.get("output_tokens", 0) * PRICE["out"]
                  + usage.get("cache_creation_input_tokens", 0) * PRICE["cache_write"]
                  + usage.get("cache_read_input_tokens", 0) * PRICE["cache_read"]) / 1e6, 6)


def ai_position_id(module: str, day: str, seq: int) -> str:
    return f"AI-{MODULES[module]['code']}-{day.replace('-', '')}-{seq:04d}"


# ── the model ────────────────────────────────────────────────────────────────────────

_client = None


class GateError(Exception):
    """A review that could not be completed; `why` becomes the not-reviewed reason."""

    def __init__(self, why: str, called: bool = True):
        super().__init__(why)
        self.why, self.called = why, called


def configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _anthropic():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(timeout=TIMEOUT_S, max_retries=1)
    return _client


async def ask(prompt: str) -> tuple[dict, dict, str]:
    """(answer, usage, model that answered). Raises GateError."""
    if not configured():
        raise GateError("no Anthropic API key on the server", called=False)
    import anthropic
    client = _anthropic()
    kwargs = {
        "model": MODEL, "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": prompt}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    }
    try:
        try:
            resp = await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        except (TypeError, anthropic.BadRequestError):
            # an SDK that predates the server-side fallback parameter, or an account the beta is not open to:
            # ask once more without it (a 400 is not billed)
            resp = await client.messages.create(**kwargs)
    except anthropic.RateLimitError as exc:
        raise GateError(f"rate limited: {exc}"[:200]) from exc
    except anthropic.APITimeoutError as exc:
        raise GateError("timeout") from exc
    except anthropic.APIStatusError as exc:
        raise GateError(f"API error {exc.status_code}: {getattr(exc, 'message', exc)}"[:200]) from exc
    except anthropic.APIConnectionError as exc:
        raise GateError(f"connection error: {exc}"[:200]) from exc
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        raise GateError(f"declined by the model ({getattr(details, 'category', None) or 'no category'})")
    if resp.stop_reason == "max_tokens":
        raise GateError("answer cut off at max_tokens")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text")
    try:
        answer = parse_answer(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise GateError(f"unreadable answer: {exc}"[:200]) from exc
    u = getattr(resp, "usage", None)
    usage = {k: int(getattr(u, k, 0) or 0) for k in
             ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    return answer, usage, str(getattr(resp, "model", MODEL))


# ── storage ──────────────────────────────────────────────────────────────────────────


class MongoRepo:
    """The gate's three collections in the local ledger database."""

    def __init__(self, db):
        self.db = db
        self._ready = False

    async def ensure(self) -> None:
        if self._ready:
            return
        await self.db[DEC].create_index([("module", 1), ("d", 1)], name="module_day")
        await self.db[DEC].create_index([("module", 1), ("decision", 1)], name="module_decision")
        await self.db[DEC].create_index([("module", 1), ("seen_at", -1)], name="module_seen")
        await self.db[POS].create_index([("module", 1), ("status", 1)], name="module_status")
        await self.db[POS].create_index([("module", 1), ("opened_at", -1)], name="module_opened")
        await self.db[POS].create_index("parent_id", name="parent")
        self._ready = True

    async def claim(self, doc: dict) -> bool:
        """Insert the decision as pending; False when it already exists (decided, or claimed elsewhere)."""
        from pymongo.errors import DuplicateKeyError
        try:
            await self.db[DEC].insert_one(doc)
            return True
        except DuplicateKeyError:
            return False

    async def expire_pending(self, before: datetime) -> int:
        """A review a restart interrupted stays undecided: mark it not reviewed (fail closed)."""
        r = await self.db[DEC].update_many({"decision": "pending", "seen_at": {"$lt": before}}, {"$set": {
            "decision": "not_reviewed", "why": "interrupted by a restart", "decided_at": _now()}})
        return r.modified_count

    async def decided(self, ids: list[str]) -> set:
        return {d["_id"] async for d in self.db[DEC].find({"_id": {"$in": ids}}, {"_id": 1})}

    async def called_today(self, module: str, day: str) -> int:
        return await self.db[DEC].count_documents({"module": module, "d": day, "called": True})

    async def finish(self, dec_id: str, fields: dict) -> None:
        await self.db[DEC].update_one({"_id": dec_id}, {"$set": fields})

    async def next_seq(self, module: str, day: str) -> int:
        from pymongo import ReturnDocument
        d = await self.db[STATE].find_one_and_update({"_id": f"seq|{module}|{day}"}, {"$inc": {"n": 1}},
                                                     upsert=True, return_document=ReturnDocument.AFTER)
        return int(d["n"])

    async def add_position(self, doc: dict) -> None:
        await self.db[POS].insert_one(doc)

    async def open_positions(self, module: str) -> list[dict]:
        return [d async for d in self.db[POS].find({"module": module, "status": "OPEN"})]

    async def update_position(self, ai_id: str, fields: dict) -> None:
        await self.db[POS].update_one({"_id": ai_id}, {"$set": fields})

    async def positions(self, module: str, status: str | None, limit: int) -> list[dict]:
        q: dict = {"module": module}
        if status:
            q["status"] = status.upper()
        return [d async for d in self.db[POS].find(q).sort("opened_at", -1).limit(limit)]

    async def decisions(self, module: str, limit: int, decision: str | None = None) -> list[dict]:
        q: dict = {"module": module}
        if decision:
            q["decision"] = decision
        return [d async for d in self.db[DEC].find(q).sort("seen_at", -1).limit(limit)]

    async def decision_stats(self, module: str, day: str) -> dict:
        out: dict = {"all": {}, "today": {}, "cost_usd": 0.0, "cost_today_usd": 0.0, "first_seen": None}
        async for r in self.db[DEC].aggregate([
                {"$match": {"module": module}},
                {"$group": {"_id": {"dec": "$decision", "today": {"$eq": ["$d", day]}}, "n": {"$sum": 1},
                            "cost": {"$sum": {"$ifNull": ["$cost_usd", 0]}}, "first": {"$min": "$seen_at"}}}]):
            k = r["_id"]
            out["all"][k["dec"]] = out["all"].get(k["dec"], 0) + r["n"]
            out["cost_usd"] += r["cost"]
            if k["today"]:
                out["today"][k["dec"]] = r["n"]
                out["cost_today_usd"] += r["cost"]
            if r.get("first") and (out["first_seen"] is None or r["first"] < out["first_seen"]):
                out["first_seen"] = r["first"]
        return out

    async def ids_with(self, module: str, decision: str, limit: int = 20000) -> list[str]:
        return [d["parent_id"] async for d in self.db[DEC].find({"module": module, "decision": decision},
                                                               {"parent_id": 1}).limit(limit)]

    async def decision_counts(self, module: str) -> list[dict]:
        return [r async for r in self.db[DEC].aggregate([
            {"$match": {"module": module}},
            {"$group": {"_id": {"sid": "$strategy_id", "dec": "$decision"}, "n": {"$sum": 1},
                        "name": {"$first": "$strategy_name"}}}])]

    async def all_positions(self, module: str) -> list[dict]:
        return [d async for d in self.db[POS].find({"module": module}, {
            "strategy_id": 1, "strategy_name": 1, "status": 1, "pnl": 1, "currency": 1, "closed_at": 1})]

    async def closed_positions(self, module: str) -> list[dict]:
        return [d async for d in self.db[POS].find({"module": module, "status": "CLOSED"},
                                                   {"pnl": 1, "currency": 1})]


_repo: MongoRepo | None = None


def repo() -> MongoRepo:
    global _repo
    if _repo is None:
        _repo = MongoRepo(_ledger()._db())
    return _repo


# ── the four modules ─────────────────────────────────────────────────────────────────


def _agg_record(window_days: int = 60) -> str:
    return f"last {window_days} days"


async def _record(coll, match: dict, pnl_field: str = "$realized_pnl") -> dict:
    """{n, wins, net} of closed positions matching `match`."""
    async for r in coll.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "n": {"$sum": 1},
                        "wins": {"$sum": {"$cond": [{"$gt": [pnl_field, 0]}, 1, 0]}},
                        "net": {"$sum": {"$ifNull": [pnl_field, 0]}}}}]):
        return {"n": int(r["n"]), "wins": int(r["wins"]), "net": float(r["net"])}
    return {"n": 0, "wins": 0, "net": 0.0}


class IntradayAdapter:
    """The Intraday Stocks tournament (intraday_v2_engine): engine 'v2' rows of intraday_lab_positions."""
    module = "intraday"

    def _coll(self):
        from app.core.db import intraday_lab_positions_collection
        return intraday_lab_positions_collection

    async def new_parents(self, since: datetime) -> list[dict]:
        rows = [d async for d in self._coll().find({"engine": "v2", "opened_at": {"$gte": since}}).sort("opened_at", 1).limit(800)]
        try:
            from app.services import intraday_v2_strategies as v2
            rules = {s.strategy_id: s.why for s in v2.CATALOG}
        except Exception:  # noqa: BLE001
            rules = {}
        out = []
        for d in rows:
            bp = _f(d.get("slippage_bp")) or 0.0
            out.append({
                "parent_id": d["position_id"], "strategy_id": d.get("strategy_id"), "strategy_name": d.get("strategy_name"),
                "rule": rules.get(d.get("strategy_id")), "symbol": d.get("symbol"), "market": "NSE cash, intraday",
                "side": _side(d.get("side")), "entry": _f(d.get("entry_price")), "signal_price": _f(d.get("signal_price")),
                "stop": _f(d.get("stoploss")), "target": _f(d.get("target")), "qty": _f(d.get("qty")),
                "timeframe": d.get("timeframe"), "currency": "INR",
                "signal_time": _aware(d.get("signal_bar_close")) or _aware(d.get("opened_at")),
                "opened_at": _aware(d.get("opened_at")), "rationale": d.get("rationale"),
                "cost_note": f"about {2 * bp + 4:.1f} bp of the position for a round trip ({bp:g} bp slippage a side "
                             "plus Angel One's charges).",
                "exit_note": (f"a time stop after {d.get('max_bars')} bars of its timeframe; " if d.get("max_bars") else "")
                + "flat by 15:05 in closing-auction stocks and 15:12 in the rest."})
        return out

    async def context(self, p: dict) -> dict:
        from app.services.intraday_store import store
        cut = int(p["signal_time"].timestamp())
        ctx: dict = {"bar_label": "15-minute bars", "notes": []}
        try:
            ctx["bars"] = _rows_from_arrays(store.get(p["symbol"]), cut, 900, 26)
        except Exception:  # noqa: BLE001
            ctx["bars"] = []
        try:
            ctx["index"] = _rows_from_arrays(store.get("NIFTY"), cut, 900, 8)
            ctx["index_label"] = "NIFTY 50 15-minute"
        except Exception:  # noqa: BLE001
            pass
        ctx["record"] = await _record(self._coll(), {
            "engine": "v2", "strategy_id": p["strategy_id"], "status": {"$ne": "OPEN"},
            "closed_at": {"$lt": p["signal_time"], "$gte": p["signal_time"] - timedelta(days=60)}})
        ctx["record"]["window"] = _agg_record()
        try:
            from app.services import event_classifier
            if await event_classifier.recent_high(p["symbol"], 120, now=p["signal_time"]):
                ctx["notes"].append("Event risk: a high-materiality company announcement in the two hours before the signal.")
        except Exception:  # noqa: BLE001
            pass
        return ctx

    async def outcomes(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        async for d in self._coll().find({"position_id": {"$in": ids}},
                                         {"position_id": 1, "status": 1, "exit_price": 1, "exit_reason": 1,
                                          "closed_at": 1, "realized_pnl": 1}):
            if d.get("status") != "OPEN" and d.get("realized_pnl") is not None:
                out[d["position_id"]] = {"status": "CLOSED", "exit_price": _f(d.get("exit_price")),
                                         "exit_reason": d.get("exit_reason"), "closed_at": _aware(d.get("closed_at")),
                                         "pnl": _f(d.get("realized_pnl")), "currency": "INR"}
            else:
                out[d["position_id"]] = {"status": "OPEN"}
        return out

    async def control(self, since: datetime) -> dict:
        return {"INR": await _record(self._coll(), {"engine": "v2", "opened_at": {"$gte": since}, "status": {"$ne": "OPEN"},
                                                    "realized_pnl": {"$ne": None}})}

    async def closed_since(self, since: datetime) -> list[dict]:
        return [{"strategy_id": d.get("strategy_id"), "strategy_name": d.get("strategy_name"), "currency": "INR",
                 "pnl": _f(d.get("realized_pnl")) or 0.0, "closed_at": _aware(d.get("closed_at"))}
                async for d in self._coll().find(
                    {"engine": "v2", "opened_at": {"$gte": since}, "status": {"$ne": "OPEN"}, "realized_pnl": {"$ne": None}},
                    {"strategy_id": 1, "strategy_name": 1, "realized_pnl": 1, "closed_at": 1})]


class CommodityAdapter:
    """Commodity Trading (commodity_engine): every row of commodity_positions."""
    module = "commodity"

    def _coll(self):
        from app.core.db import commodity_positions_collection
        return commodity_positions_collection

    async def new_parents(self, since: datetime) -> list[dict]:
        out = []
        async for d in self._coll().find({"opened_at": {"$gte": since}}).sort("opened_at", 1).limit(500):
            cap = _f(d.get("capital_deployed")) or 0.0
            costs = (_f(d.get("entry_costs")) or 0.0) * 2
            out.append({
                "parent_id": d["position_id"], "strategy_id": d.get("strategy_id"), "strategy_name": d.get("strategy_name"),
                "rule": f"{d.get('family_label') or d.get('family') or ''} pattern '{d.get('pattern') or d.get('template')}'".strip(),
                "symbol": d.get("symbol"), "market": "MCX futures", "side": _side(d.get("side")),
                "entry": _f(d.get("entry_price")), "signal_price": _f(d.get("signal_price")), "stop": _f(d.get("stoploss")),
                "target": _f(d.get("target")), "qty": _f(d.get("qty")), "timeframe": d.get("timeframe"), "currency": "INR",
                "signal_time": _aware(d.get("opened_at")), "opened_at": _aware(d.get("opened_at")),
                "rationale": d.get("rationale"),
                "cost_note": (f"about {costs / cap * 100:.3f}% of the position for a round trip (MCX charges plus slippage)."
                              if cap else None),
                "exit_note": f"stop, target, or a time stop after {d.get('max_hold_bars')} bars." if d.get("max_hold_bars") else None})
        return out

    async def context(self, p: dict) -> dict:
        from app.services import commodity_bars as cb
        minutes = cb.TIMEFRAMES.get(p.get("timeframe") or "", (None, 15))[1]
        ctx: dict = {"bar_label": f"{p.get('timeframe')} bars", "notes": []}
        try:
            bars = await cb.load_bars(p["symbol"], p["timeframe"], limit=60)
            ctx["bars"] = _rows_from_objects(bars, p["signal_time"], minutes, 26)
        except Exception:  # noqa: BLE001
            ctx["bars"] = []
        ctx["record"] = await _record(self._coll(), {
            "strategy_id": p["strategy_id"], "status": {"$ne": "OPEN"},
            "closed_at": {"$lt": p["signal_time"], "$gte": p["signal_time"] - timedelta(days=60)}})
        ctx["record"]["window"] = _agg_record()
        return ctx

    async def outcomes(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        async for d in self._coll().find({"position_id": {"$in": ids}},
                                         {"position_id": 1, "status": 1, "exit_price": 1, "exit_reason": 1,
                                          "closed_at": 1, "realized_pnl": 1}):
            if d.get("status") != "OPEN" and d.get("realized_pnl") is not None:
                out[d["position_id"]] = {"status": "CLOSED", "exit_price": _f(d.get("exit_price")),
                                         "exit_reason": d.get("exit_reason"), "closed_at": _aware(d.get("closed_at")),
                                         "pnl": _f(d.get("realized_pnl")), "currency": "INR"}
            else:
                out[d["position_id"]] = {"status": "OPEN"}
        return out

    async def control(self, since: datetime) -> dict:
        return {"INR": await _record(self._coll(), {"opened_at": {"$gte": since}, "status": {"$ne": "OPEN"},
                                                    "realized_pnl": {"$ne": None}})}

    async def closed_since(self, since: datetime) -> list[dict]:
        return [{"strategy_id": d.get("strategy_id"), "strategy_name": d.get("strategy_name"), "currency": "INR",
                 "pnl": _f(d.get("realized_pnl")) or 0.0, "closed_at": _aware(d.get("closed_at"))}
                async for d in self._coll().find(
                    {"opened_at": {"$gte": since}, "status": {"$ne": "OPEN"}, "realized_pnl": {"$ne": None}},
                    {"strategy_id": 1, "strategy_name": 1, "realized_pnl": 1, "closed_at": 1})]


class GoldAdapter:
    """Gold Desk (gold_desk): gold_positions on Delta (USD) and MCX (INR). H1's record is untouched: this only reads."""
    module = "gold"

    def _coll(self):
        from app.core.db import gold_positions_collection
        return gold_positions_collection

    async def new_parents(self, since: datetime) -> list[dict]:
        out = []
        async for d in self._coll().find({"opened_at": {"$gte": since}}).sort("opened_at", 1).limit(200):
            notional = _f(d.get("notional")) or 0.0
            costs = (_f(d.get("entry_costs")) or 0.0) * 2
            out.append({
                "parent_id": d["position_id"], "strategy_id": d.get("strategy_id") or d.get("strategy_template"),
                "strategy_name": d.get("strategy_name"), "venue": d.get("venue"), "instrument": d.get("instrument") or {},
                "rule": f"{d.get('family_label') or d.get('family') or ''} pattern '{d.get('pattern') or d.get('strategy_template')}'"
                        + (" (the pre-registered H1 forward test)" if d.get("h1") else ""),
                "symbol": d.get("symbol"), "market": f"gold on {'Delta Exchange' if d.get('venue') == 'delta' else 'MCX'}",
                "side": _side(d.get("side")), "entry": _f(d.get("entry_price")), "signal_price": _f(d.get("signal_price")),
                "stop": _f(d.get("stoploss")), "target": _f(d.get("target")), "qty": _f(d.get("qty")),
                "timeframe": d.get("timeframe"), "currency": d.get("currency") or "INR",
                "signal_time": _aware(d.get("signal_bar_close")) or _aware(d.get("opened_at")),
                "opened_at": _aware(d.get("opened_at")), "rationale": d.get("rationale"),
                "cost_note": (f"about {costs / notional * 100:.3f}% of the notional for a round trip, plus funding on Delta."
                              if notional else None),
                "exit_note": f"stop, target, or a time stop after {d.get('max_hold_bars')} bars." if d.get("max_hold_bars") else None})
        return out

    async def context(self, p: dict) -> dict:
        from app.services import gold_desk as gd
        ctx: dict = {"bar_label": f"{p.get('timeframe')} bars", "notes": []}
        try:
            v = gd.venue(p.get("venue") or "delta")
            bars = await gd.load_bars(v, p["symbol"], p["timeframe"], 60, p.get("instrument") or None)
            ctx["bars"] = _rows_from_objects(bars, p["signal_time"], gd.tf_minutes(v, p["timeframe"]), 26)
        except Exception:  # noqa: BLE001
            ctx["bars"] = []
        ctx["record"] = await _record(self._coll(), {
            "venue": p.get("venue"), "strategy_name": p.get("strategy_name"), "timeframe": p.get("timeframe"),
            "status": {"$ne": "OPEN"}, "void": {"$ne": True},
            "closed_at": {"$lt": p["signal_time"], "$gte": p["signal_time"] - timedelta(days=90)}})
        ctx["record"]["window"] = "last 90 days"
        return ctx

    async def outcomes(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        async for d in self._coll().find({"position_id": {"$in": ids}},
                                         {"position_id": 1, "status": 1, "exit_price": 1, "exit_reason": 1, "closed_at": 1,
                                          "realized_pnl": 1, "currency": 1, "void": 1}):
            if d.get("void"):
                out[d["position_id"]] = {"status": "VOID"}
            elif d.get("status") != "OPEN" and d.get("realized_pnl") is not None:
                out[d["position_id"]] = {"status": "CLOSED", "exit_price": _f(d.get("exit_price")),
                                         "exit_reason": d.get("exit_reason"), "closed_at": _aware(d.get("closed_at")),
                                         "pnl": _f(d.get("realized_pnl")), "currency": d.get("currency") or "INR"}
            else:
                out[d["position_id"]] = {"status": "OPEN"}
        return out

    async def control(self, since: datetime) -> dict:
        out = {}
        for cur in ("USD", "INR"):
            r = await _record(self._coll(), {"opened_at": {"$gte": since}, "status": {"$ne": "OPEN"}, "void": {"$ne": True},
                                             "currency": cur, "realized_pnl": {"$ne": None}})
            if r["n"]:
                out[cur] = r
        return out or {"USD": {"n": 0, "wins": 0, "net": 0.0}}

    async def closed_since(self, since: datetime) -> list[dict]:
        return [{"strategy_id": d.get("strategy_id") or d.get("strategy_template"), "strategy_name": d.get("strategy_name"),
                 "currency": d.get("currency") or "INR", "pnl": _f(d.get("realized_pnl")) or 0.0,
                 "closed_at": _aware(d.get("closed_at"))}
                async for d in self._coll().find(
                    {"opened_at": {"$gte": since}, "status": {"$ne": "OPEN"}, "void": {"$ne": True}, "realized_pnl": {"$ne": None}},
                    {"strategy_id": 1, "strategy_template": 1, "strategy_name": 1, "currency": 1, "realized_pnl": 1,
                     "closed_at": 1})]


class PremiumAdapter:
    """Premium Strategies (premium-paper-service): sized rows (qty > 0) of premium_trades in the box's local MongoDB.
    Rupee P&L is the account's own, at its own sizing. Trades of unsealed days are rewritten every cycle under the
    same id; a trade the desk later replaced is voided."""
    module = "premium"
    NSE = ("NSE15", "NSE5", "VWAP", "NSED")
    INDEX = {"NIFTY": "NIFTY", "BANKNIFTY": "NIFTYBANK", "NIFTY_D": "NIFTY"}

    def _db(self):
        from app.api.routes.premium_paper import _database
        return _database()

    async def new_parents(self, since: datetime) -> list[dict]:
        db = self._db()
        if db is None:
            return []
        rows = [d async for d in db.premium_trades.find({"entry_t": {"$gte": int(since.timestamp())}, "qty": {"$gt": 0}})
                .sort("entry_t", 1).limit(800)]
        names: dict = {}
        accts = sorted({d.get("acct") for d in rows if d.get("acct")})
        if accts:
            async for a in db.premium_accounts.find({"_id": {"$in": accts}}, {"name": 1, "channel": 1, "markets": 1}):
                names[a["_id"]] = a
        out = []
        for d in rows:
            a = names.get(d.get("acct")) or {}
            t = _aware(d.get("entry_t"))
            cost_r = _f(d.get("cost_r"))
            out.append({
                "parent_id": d["_id"], "strategy_id": d.get("acct"), "strategy_name": a.get("name") or d.get("acct"),
                "rule": (f"from {a.get('channel')}; setup {d.get('setup')}, variant {d.get('variant')}" if a.get("channel")
                         else f"setup {d.get('setup')}, variant {d.get('variant')}"),
                "symbol": d.get("sym"), "market": d.get("mkt"), "mkt": d.get("mkt"), "side": _side(d.get("side")),
                "entry": _f(d.get("entry")), "stop": _f(d.get("stop")), "target": _f(d.get("target")),
                "qty": _f(d.get("qty")), "timeframe": None, "currency": "INR", "signal_time": t, "opened_at": t,
                "cost_note": f"about {cost_r:.2f}R for a round trip." if cost_r is not None else None, "exit_note": None})
        return out

    async def context(self, p: dict) -> dict:
        ctx: dict = {"bar_label": "15-minute bars", "notes": []}
        sym = p["symbol"] if p.get("mkt") in self.NSE else self.INDEX.get(p.get("mkt") or "")
        if sym:
            try:
                from app.services.intraday_store import store
                ctx["bars"] = _rows_from_arrays(store.get(sym), int(p["signal_time"].timestamp()), 900, 26)
            except Exception:  # noqa: BLE001
                ctx["bars"] = []
        db = self._db()
        if db is not None:
            ctx["record"] = await _record(db.premium_trades, {
                "acct": p["strategy_id"], "qty": {"$gt": 0}, "open": False,
                "exit_t": {"$lt": int(p["signal_time"].timestamp())}}, "$pnl")
            ctx["record"]["window"] = "since its paper start"
        return ctx

    async def outcomes(self, ids: list[str]) -> dict[str, dict]:
        db = self._db()
        if db is None:
            return {}
        out = {i: {"status": "MISSING"} for i in ids}
        async for d in db.premium_trades.find({"_id": {"$in": ids}},
                                              {"open": 1, "exit_t": 1, "exit": 1, "reason": 1, "pnl": 1, "qty": 1}):
            if not d.get("open") and d.get("exit_t") is not None and d.get("pnl") is not None:
                out[d["_id"]] = {"status": "CLOSED", "exit_price": _f(d.get("exit")), "exit_reason": d.get("reason"),
                                 "closed_at": _aware(d.get("exit_t")), "pnl": _f(d.get("pnl")), "currency": "INR"}
            else:
                out[d["_id"]] = {"status": "OPEN"}
        return out

    async def control(self, since: datetime) -> dict:
        db = self._db()
        if db is None:
            return {"INR": {"n": 0, "wins": 0, "net": 0.0}}
        return {"INR": await _record(db.premium_trades, {"entry_t": {"$gte": int(since.timestamp())}, "qty": {"$gt": 0},
                                                         "open": False}, "$pnl")}

    async def closed_since(self, since: datetime) -> list[dict]:
        db = self._db()
        if db is None:
            return []
        rows = [d async for d in db.premium_trades.find(
            {"entry_t": {"$gte": int(since.timestamp())}, "qty": {"$gt": 0}, "open": False},
            {"acct": 1, "pnl": 1, "exit_t": 1})]
        names: dict = {}
        accts = sorted({d.get("acct") for d in rows if d.get("acct")})
        if accts:
            async for a in db.premium_accounts.find({"_id": {"$in": accts}}, {"name": 1}):
                names[a["_id"]] = a.get("name")
        return [{"strategy_id": d.get("acct"), "strategy_name": names.get(d.get("acct")) or d.get("acct"), "currency": "INR",
                 "pnl": _f(d.get("pnl")) or 0.0, "closed_at": _aware(d.get("exit_t"))} for d in rows]


ADAPTERS = {a.module: a for a in (IntradayAdapter(), CommodityAdapter(), GoldAdapter(), PremiumAdapter())}


# ── review, open, close ──────────────────────────────────────────────────────────────


def _dec_doc(module: str, p: dict, now: datetime) -> dict:
    return {"_id": f"{module}|{p['parent_id']}", "module": module, "parent_id": p["parent_id"],
            "strategy_id": p.get("strategy_id"), "strategy_name": p.get("strategy_name"), "symbol": p.get("symbol"),
            "market": p.get("market"), "side": p.get("side"), "entry": p.get("entry"), "stop": p.get("stop"),
            "target": p.get("target"), "qty": p.get("qty"), "currency": p.get("currency"),
            "signal_time": p.get("signal_time"), "parent_opened_at": p.get("opened_at"), "seen_at": now,
            "d": now.astimezone(IST).date().isoformat(), "decision": "pending", "called": False,
            "model": MODEL, "effort": EFFORT, "prompt_version": PROMPT_VERSION}


async def review(module: str, p: dict, rp=None, adapter=None, asker=None, now: datetime | None = None) -> dict | None:
    """Judge one new parent position. Returns the finished decision (None when already decided)."""
    rp = rp or repo()
    adapter = adapter or ADAPTERS[module]
    asker = asker or ask
    now = now or _now()
    doc = _dec_doc(module, p, now)
    if not await rp.claim(dict(doc)):
        return None
    fields: dict = {}
    try:
        if p.get("opened_at") and now - p["opened_at"] > timedelta(minutes=MODULES[module]["lookback_min"]):
            raise GateError("seen too late to review", called=False)
        if await rp.called_today(module, doc["d"]) >= MODULES[module]["daily_max"]:
            raise GateError(f"daily cap of {MODULES[module]['daily_max']} reviews reached", called=False)
        try:
            ctx = await adapter.context(p)
        except Exception as exc:  # noqa: BLE001 - a missing context is stated in the prompt, not a reason to stop
            logger.warning("[ai_gate] %s context for %s failed: %s", module, p["parent_id"], exc)
            ctx = {"bars": [], "notes": ["(Market data for this review could not be read.)"]}
        prompt = build_prompt(module, p, ctx)
        await rp.finish(doc["_id"], {"called": True})
        t0 = time.monotonic()
        try:
            answer, usage, model = await asyncio.wait_for(asker(prompt), TIMEOUT_S + 15)
        except asyncio.TimeoutError as exc:
            raise GateError("timeout") from exc
        decided = _now() if asker is ask else now
        fields = {"decision": answer["decision"], **answer, "usage": usage, "cost_usd": cost_usd(usage),
                  "model": model, "latency_ms": int((time.monotonic() - t0) * 1000), "decided_at": decided,
                  "lag_s": round((decided - p["opened_at"]).total_seconds(), 1) if p.get("opened_at") else None,
                  "prompt_chars": len(prompt), "called": True}
        if answer["decision"] == "take":
            seq = await rp.next_seq(module, doc["d"])
            ai_id = ai_position_id(module, doc["d"], seq)
            await rp.add_position({
                "_id": ai_id, "ai_position_id": ai_id, "module": module, "parent_id": p["parent_id"],
                "decision_id": doc["_id"], "strategy_id": p.get("strategy_id"), "strategy_name": p.get("strategy_name"),
                "symbol": p.get("symbol"), "market": p.get("market"), "side": p.get("side"), "qty": p.get("qty"),
                "entry_price": p.get("entry"), "stop": p.get("stop"), "target": p.get("target"),
                "currency": p.get("currency") or "INR", "signal_time": p.get("signal_time"),
                "parent_opened_at": p.get("opened_at"), "approved_at": decided, "opened_at": decided,
                "opened_on": decided.astimezone(IST).date().isoformat(), "status": "OPEN", "exit_price": None,
                "exit_reason": None, "closed_at": None, "pnl": None, "p_profit": answer["p_profit"],
                "confidence": answer["confidence"], "reasons": answer["reasons"], "main_risk": answer["main_risk"],
                "model": model, "prompt_version": PROMPT_VERSION})
            fields["ai_position_id"] = ai_id
    except GateError as exc:
        fields = {"decision": "not_reviewed", "why": exc.why, "called": exc.called or fields.get("called", False),
                  "decided_at": _now()}
    except Exception as exc:  # noqa: BLE001 - fail closed
        stats["errors"] += 1
        stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("[ai_gate] review of %s %s failed", module, p.get("parent_id"))
        fields = {"decision": "not_reviewed", "why": f"error: {type(exc).__name__}", "decided_at": _now()}
    await rp.finish(doc["_id"], fields)
    stats["reviews"] += 1
    return {**doc, **fields}


async def sync_closes(module: str, rp=None, adapter=None, now: datetime | None = None) -> int:
    """Close (or void) AI positions whose parent has closed. Returns how many changed."""
    rp = rp or repo()
    adapter = adapter or ADAPTERS[module]
    now = now or _now()
    open_pos = await rp.open_positions(module)
    if not open_pos:
        return 0
    outs = await adapter.outcomes([x["parent_id"] for x in open_pos])
    changed = 0
    for x in open_pos:
        o = outs.get(x["parent_id"]) or {"status": "MISSING"}
        if o["status"] == "CLOSED":
            entry, ext = _f(x.get("entry_price")), o.get("exit_price")
            ret = None
            if entry and ext:
                ret = round((ext / entry - 1) * 100 * (1 if x.get("side") == "BUY" else -1), 4)
            await rp.update_position(x["_id"], {"status": "CLOSED", "exit_price": ext, "exit_reason": o.get("exit_reason"),
                                                "closed_at": o.get("closed_at") or now, "pnl": o.get("pnl"),
                                                "currency": o.get("currency") or x.get("currency"), "move_pct": ret,
                                                "closed_on": (o.get("closed_at") or now).astimezone(IST).date().isoformat(),
                                                "synced_at": now})
            changed += 1
        elif o["status"] == "VOID":
            await rp.update_position(x["_id"], {"status": "VOID", "void_reason": "the module voided its position",
                                                "synced_at": now})
            changed += 1
        elif o["status"] == "MISSING":
            first = _aware(x.get("missing_since"))
            if first is None:
                await rp.update_position(x["_id"], {"missing_since": now})
            elif (now - first).total_seconds() > VOID_AFTER_S:
                await rp.update_position(x["_id"], {"status": "VOID", "void_reason": "the module's position no longer exists",
                                                    "synced_at": now})
                changed += 1
        elif x.get("missing_since"):
            await rp.update_position(x["_id"], {"missing_since": None})
    return changed


async def cycle(now: datetime | None = None) -> dict:
    """One pass over the four modules: review what is new, then close what has closed."""
    rp = repo()
    await rp.ensure()
    now = now or _now()
    out: dict = {"expired": await rp.expire_pending(now - timedelta(minutes=10))}
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(module: str, p: dict):
        async with sem:
            return await review(module, p, rp)

    for module, adapter in ADAPTERS.items():
        info: dict = {}
        try:
            since = now - timedelta(minutes=MODULES[module]["lookback_min"])
            parents = [p for p in await adapter.new_parents(since) if p.get("parent_id") and p.get("entry")]
            done = await rp.decided([f"{module}|{p['parent_id']}" for p in parents]) if parents else set()
            fresh = [p for p in parents if f"{module}|{p['parent_id']}" not in done]
            results = await asyncio.gather(*(one(module, p) for p in fresh))
            info["reviewed"] = sum(1 for r in results if r)
            info["approved"] = sum(1 for r in results if r and r.get("decision") == "take")
            info["closed"] = await sync_closes(module, rp, adapter, now)
        except Exception as exc:  # noqa: BLE001 - one module's failure must not stop the others
            stats["errors"] += 1
            stats["last_error"] = f"{module}: {type(exc).__name__}: {exc}"[:300]
            logger.exception("[ai_gate] %s cycle failed", module)
            info["error"] = str(exc)[:200]
        out[module] = info
    stats["cycles"] += 1
    stats["last_cycle_at"] = _now().isoformat()
    stats["last_cycle"] = out
    return out


async def loop() -> None:
    """The background loop, started from main.py when the gate is enabled."""
    stats["running"] = True
    await asyncio.sleep(30)                       # let the app and its stores finish starting
    while True:
        t0 = time.monotonic()
        try:
            await cycle()
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            logger.exception("[ai_gate] cycle failed")
        await asyncio.sleep(max(5.0, POLL_S - (time.monotonic() - t0)))


# ── what the page reads ──────────────────────────────────────────────────────────────


def _stats_from(rows: list[dict]) -> dict:
    by: dict = {}
    for r in rows:
        cur = r.get("currency") or "INR"
        s = by.setdefault(cur, {"n": 0, "wins": 0, "net": 0.0})
        pnl = _f(r.get("pnl")) or 0.0
        s["n"] += 1
        s["wins"] += pnl > 0
        s["net"] += pnl
    return by


def _finish_stats(by: dict) -> dict:
    out = {}
    for cur, s in by.items():
        n = s["n"]
        out[cur] = {"trades": n, "wins": s["wins"], "win_rate": round(s["wins"] / n * 100, 1) if n else None,
                    "net": round(s["net"], 2), "avg": round(s["net"] / n, 2) if n else None}
    return out


def _jsonable(d: dict) -> dict:
    """Timestamps as UTC ISO strings (Mongo hands them back without a zone), and no token detail."""
    return {k: (_aware(v).isoformat() if isinstance(v, datetime) else v) for k, v in d.items() if k != "usage"}


def status() -> dict:
    return {"enabled": ENABLED, "configured": configured(), "model": MODEL, "effort": EFFORT, "prompt_version": PROMPT_VERSION,
            "poll_s": POLL_S, "timeout_s": TIMEOUT_S,
            "modules": {k: {"label": v["label"], "lookback_min": v["lookback_min"], "daily_max": v["daily_max"]}
                        for k, v in MODULES.items()},
            "price_usd_per_mtok": PRICE, **{k: v for k, v in stats.items() if k != "last_cycle"},
            "last_cycle": stats.get("last_cycle")}


async def summary(module: str) -> dict:
    """The A/B picture for one module: every position it took since the gate started, the AI-approved book, and the
    positions the AI skipped."""
    rp = repo()
    await rp.ensure()
    day = _now().astimezone(IST).date().isoformat()
    ds = await rp.decision_stats(module, day)
    adapter = ADAPTERS[module]
    since = _aware(ds["first_seen"])
    control = _finish_stats(await adapter.control(since)) if since else {}
    approved = _finish_stats(_stats_from(await rp.closed_positions(module)))
    skipped_ids = await rp.ids_with(module, "skip")
    skipped_rows = []
    for i in range(0, len(skipped_ids), 500):
        outs = await adapter.outcomes(skipped_ids[i:i + 500])
        skipped_rows += [o for o in outs.values() if o.get("status") == "CLOSED"]
    open_n = len(await rp.open_positions(module))
    return {"module": module, "label": MODULES[module]["label"], **status_brief(module),
            "since": since.isoformat() if since else None, "decisions": ds["all"], "today": ds["today"],
            "prompt_version": PROMPT_VERSION,
            "cost_usd": round(ds["cost_usd"], 4), "cost_today_usd": round(ds["cost_today_usd"], 4),
            "control": control, "approved": approved, "skipped": _finish_stats(_stats_from(skipped_rows)),
            "open_ai_positions": open_n}


def status_brief(module: str) -> dict:
    return {"enabled": ENABLED, "configured": configured(), "model": MODEL, "daily_max": MODULES[module]["daily_max"],
            "lookback_min": MODULES[module]["lookback_min"]}


def _primary(by: dict) -> str:
    """The currency most of a strategy's trades are in (gold on Delta: USD)."""
    return max(by, key=lambda c: by[c]["n"]) if by else "INR"


def _flat(by: dict, cur: str, prefix: str) -> dict:
    s = by.get(cur) or {"n": 0, "wins": 0, "net": 0.0}
    n = s["n"]
    return {f"{prefix}_trades": n, f"{prefix}_wins": s["wins"],
            f"{prefix}_win_rate": round(s["wins"] / n * 100, 1) if n else None,
            f"{prefix}_net": round(s["net"], 2), f"{prefix}_avg": round(s["net"] / n, 2) if n else None}


def _add(s: dict, pnl: float) -> None:
    s["n"] += 1
    s["wins"] += pnl > 0
    s["net"] += pnl


async def leaderboard(module: str) -> dict:
    """Every strategy the gate has reviewed: its reviews and approvals, the AI-approved book's result, and the
    module's own result for that strategy since the gate started. Ranked by the AI book's net P&L."""
    rp = repo()
    await rp.ensure()
    ds = await rp.decision_stats(module, _now().astimezone(IST).date().isoformat())
    since = _aware(ds["first_seen"])
    rows: dict = {}

    def row(sid, name):
        r = rows.setdefault(sid or "?", {"strategy_id": sid, "strategy_name": name or sid, "reviewed": 0, "approved": 0,
                                         "skipped": 0, "not_reviewed": 0, "ai_open": 0, "ai": {}, "mod": {}})
        if name and (not r["strategy_name"] or r["strategy_name"] == sid):
            r["strategy_name"] = name
        return r

    for g in await rp.decision_counts(module):
        r = row(g["_id"].get("sid"), g.get("name"))
        dec, n = g["_id"].get("dec"), int(g["n"])
        if dec == "take":
            r["approved"] += n
            r["reviewed"] += n
        elif dec == "skip":
            r["skipped"] += n
            r["reviewed"] += n
        elif dec == "not_reviewed":
            r["not_reviewed"] += n
    for p in await rp.all_positions(module):
        r = row(p.get("strategy_id"), p.get("strategy_name"))
        if p.get("status") == "OPEN":
            r["ai_open"] += 1
        elif p.get("status") == "CLOSED":
            _add(r["ai"].setdefault(p.get("currency") or "INR", {"n": 0, "wins": 0, "net": 0.0}), _f(p.get("pnl")) or 0.0)
    if since:
        for c in await ADAPTERS[module].closed_since(since):
            r = rows.get(c.get("strategy_id") or "?")
            if r is None:                      # a strategy the gate never reviewed (opened while the gate was down)
                continue
            _add(r["mod"].setdefault(c.get("currency") or "INR", {"n": 0, "wins": 0, "net": 0.0}), c["pnl"])
    out = []
    for r in rows.values():
        cur = _primary({**r["mod"], **r["ai"]})
        out.append({"strategy_id": r["strategy_id"], "strategy_name": r["strategy_name"], "currency": cur,
                    "reviewed": r["reviewed"], "approved": r["approved"], "skipped": r["skipped"],
                    "not_reviewed": r["not_reviewed"],
                    "approval_rate": round(r["approved"] / r["reviewed"] * 100, 1) if r["reviewed"] else None,
                    "ai_open": r["ai_open"], **_flat(r["ai"], cur, "ai"), **_flat(r["mod"], cur, "module")})
    out.sort(key=lambda x: (-(x["ai_net"] if x["ai_trades"] else -1e18), -x["approved"], str(x["strategy_name"])))
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return {"module": module, "since": since.isoformat() if since else None, "rows": out}


async def daily(module: str) -> dict:
    """Per IST day: the AI-approved book's closed positions and the module's own, since the gate started."""
    rp = repo()
    await rp.ensure()
    ds = await rp.decision_stats(module, _now().astimezone(IST).date().isoformat())
    since = _aware(ds["first_seen"])
    days: dict = {}

    def cell(t, cur):
        d = (t or _now()).astimezone(IST).date().isoformat()
        return days.setdefault((d, cur), {"day": d, "currency": cur, "ai": {"n": 0, "wins": 0, "net": 0.0},
                                          "mod": {"n": 0, "wins": 0, "net": 0.0}})

    for p in await rp.all_positions(module):
        if p.get("status") == "CLOSED":
            _add(cell(_aware(p.get("closed_at")), p.get("currency") or "INR")["ai"], _f(p.get("pnl")) or 0.0)
    if since:
        for x in await ADAPTERS[module].closed_since(since):
            _add(cell(x.get("closed_at"), x.get("currency") or "INR")["mod"], x["pnl"])
    rows = []
    for v in sorted(days.values(), key=lambda v: (v["day"], v["currency"]), reverse=True):
        rows.append({"day": v["day"], "currency": v["currency"],
                     **_flat({v["currency"]: v["ai"]}, v["currency"], "ai"),
                     **_flat({v["currency"]: v["mod"]}, v["currency"], "module")})
    return {"module": module, "since": since.isoformat() if since else None, "rows": rows}


async def positions(module: str, status_: str | None = None, limit: int = 100) -> list[dict]:
    rp = repo()
    return [_jsonable(d) for d in await rp.positions(module, status_, max(1, min(limit, 500)))]


async def decisions(module: str, limit: int = 100, decision: str | None = None) -> list[dict]:
    rp = repo()
    return [_jsonable(d) for d in await rp.decisions(module, max(1, min(limit, 500)), decision)]
