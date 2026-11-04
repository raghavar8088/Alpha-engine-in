"""The daily review — Phases 9 and 10 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md.

After each session (the data scheduler, 15:50 IST) one report is built and stored in the box's
local MongoDB (alpha_engine_intraday.intraday_daily_reviews, _id = the date):

  ledger      every signal recorded? (rows = signals at each close), decisions, rejection
              reasons, closes at which entries were blocked
  tournament  the day's closed tournament positions: count, net, exits by reason, cost model,
              and any exit still unresolved
  gated       both gated paper accounts, the rules paused by automatic demotion, and the
              FORWARD MONITOR (Phase 10): book B's record per rule against the frozen two-year
              expectation (research dataset y2, measured costs) — a rule doing significantly worse
              than even that is flagged
  recorders   depth snapshots and H1 samples stored today; announcements stored and classified
  real money  how many strategies hold a CONFIRMED forward verdict (the live desk's arming gate)
  flags       rule-based anomalies, each one sentence
  summary     with an LLM configured (ai_service): a short plain-English note written FROM the
              numbers above — the model explains, it does not compute; otherwise 'not configured'
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone

from app.services import intraday_signal_ledger as ledger

logger = logging.getLogger("intraday_daily_review")

IST = ledger.IST
COLLECTION = "intraday_daily_reviews"
# Frozen expectation per rule: mean net bp per signal over 4 Nov 2024 - 3 Nov 2026 at measured
# costs, and the per-trade standard deviation (backend/research/intraday_ai, run y2).
EXPECTATIONS = {
    "iv2_bollinger_snap_1h": (-7.65, 70.1), "iv2_donchian_1h": (-7.04, 102.4),
    "iv2_donchian_45m": (-8.07, 102.1), "iv2_macd_trend_1h": (-7.34, 87.6),
    "iv2_rsi_momentum_45m": (-8.19, 85.1), "iv2_vwap_trend_1h": (-7.8, 94.2),
}
SUMMARY_SYSTEM = (
    "You write the daily operations note for a paper-trading research desk. You are given the "
    "day's numbers as JSON. Explain them in plain English in at most eight short sentences, and "
    "list anything that looks wrong. Use only the numbers given; never compute new ones or guess "
    "at causes the numbers do not show."
)
SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": {"summary": {"type": "string"}, "attention": {"type": "array", "items": {"type": "string"}}},
                  "required": ["summary", "attention"]}


def _iso(x):
    return x.isoformat() if isinstance(x, datetime) else x


async def _tournament(day: str) -> dict:
    from app.core.db import intraday_lab_positions_collection as pos
    rows = [p async for p in pos.find({"engine": "v2", "closed_on": day},
                                      {"realized_pnl": 1, "exit_reason": 1, "cost_model": 1, "_id": 0})]
    unresolved = await pos.count_documents({"engine": "v2", "status": "OPEN", "exit_pending_reason": {"$ne": None}})
    by_reason: dict = {}
    for r in rows:
        k = (r.get("exit_reason") or "?").split(" ")[0]
        by_reason[k] = by_reason.get(k, 0) + 1
    models: dict = {}
    for r in rows:
        models[r.get("cost_model") or "unstamped"] = models.get(r.get("cost_model") or "unstamped", 0) + 1
    return {"closed": len(rows), "net": round(sum(r.get("realized_pnl") or 0.0 for r in rows), 2),
            "exits": by_reason, "cost_models": models, "unresolved_exits": unresolved}


def forward_monitor(book_b: dict) -> list[dict]:
    """Book B's forward record per rule vs the frozen expectation; z <= -2 is flagged."""
    out = []
    for sid, (mean_exp, sd) in EXPECTATIONS.items():
        rec = (book_b.get("rule_records") or {}).get(sid)
        if not rec or not rec.get("trades"):
            out.append({"rule": sid, "trades": 0, "expected_net_bp": mean_exp})
            continue
        n, m = rec["trades"], rec["mean_net_bp"]
        z = (m - mean_exp) / (sd / math.sqrt(n))
        out.append({"rule": sid, "trades": n, "forward_net_bp": m, "expected_net_bp": mean_exp,
                    "z": round(z, 2), "flag": z <= -2,
                    "paused": sid in (book_b.get("paused_rules") or {})})
    return out


async def build(day: str | None = None) -> dict:
    day = day or datetime.now(IST).date().isoformat()
    doc: dict = {"_id": day, "built_at": datetime.now(timezone.utc)}
    flags: list[str] = []
    try:
        lg = await ledger.summary(day)
        doc["ledger"] = {k: lg.get(k) for k in ("enabled", "closes", "closes_judged", "signals", "rows_at_closes",
                                                "complete", "mismatched_closes", "decisions", "rejection_reasons",
                                                "blocked_closes", "write_errors", "storage")}
        if lg.get("enabled") and lg.get("closes_judged") and not lg.get("complete"):
            flags.append(f"The decision ledger is incomplete at {len(lg.get('mismatched_closes') or [])} close(s).")
        if lg.get("write_errors"):
            flags.append(f"The decision ledger failed to write {lg['write_errors']} time(s).")
        if lg.get("blocked_closes"):
            flags.append(f"Entries were blocked at {len(lg['blocked_closes'])} close(s): {lg['blocked_closes'][0]['why']}.")
    except Exception as exc:  # noqa: BLE001 - one section failing must not lose the report
        flags.append(f"Ledger section failed: {exc}")
    try:
        doc["tournament"] = await _tournament(day)
        if doc["tournament"]["unresolved_exits"]:
            flags.append(f"{doc['tournament']['unresolved_exits']} tournament position(s) have an unresolved exit.")
    except Exception as exc:  # noqa: BLE001
        flags.append(f"Tournament section failed: {exc}")
    try:
        from app.services import gated_books
        g = await gated_books.summary()
        doc["gated"] = {"config_version": g.get("config_version"),
                        "books": [{k: b.get(k) for k in ("book", "equity", "return_pct", "today_pnl", "trades", "win_rate",
                                                          "drawdown_pct", "today_decisions", "paused_rules", "rule_records")}
                                  for b in g.get("books", [])]}
        b = next((x for x in g.get("books", []) if x["book"] == "B"), None)
        if b:
            doc["forward_monitor"] = forward_monitor(b)
            for f in doc["forward_monitor"]:
                if f.get("flag"):
                    flags.append(f"Book B: {f['rule']} is doing worse than even its two-year expectation (z {f['z']}).")
        for x in g.get("books", []):
            for sid in (x.get("paused_rules") or {}):
                flags.append(f"Book {x['book']}: {sid} is paused by automatic demotion.")
    except Exception as exc:  # noqa: BLE001
        flags.append(f"Gated section failed: {exc}")
    try:
        db = ledger._db()
        start = datetime.fromisoformat(day).replace(tzinfo=IST).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        from app.core.db import db as atlas
        doc["recorders"] = {
            "depth_snapshots": await db["intraday_depth_samples"].count_documents({"d": day}),
            "h1_samples": await atlas["intraday_h1_samples"].count_documents({"measured_at": {"$gte": start, "$lt": end}}),
            "announcements": await db["market_events"].count_documents({"d": day}),
            "announcements_classified": await db["market_events"].count_documents({"d": day, "label": {"$ne": None}, "classified": True})}
        from app.services.intraday_v2_registry import registry
        doc["real_money"] = {"confirmed_strategies": await registry.count_documents({"status": "CONFIRMED"}),
                             "note": "the live desk arms only on CONFIRMED forward verdicts"}
    except Exception as exc:  # noqa: BLE001
        flags.append(f"Recorder section failed: {exc}")
    doc["flags"] = flags
    doc["summary"] = await _summary(doc)
    try:
        await ledger._db()[COLLECTION].replace_one({"_id": day}, doc, upsert=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[review] could not store the review: %s", exc)
    return doc


async def _summary(doc: dict) -> dict:
    try:
        from ai_service.provider import ProviderError, get_provider
        p = get_provider()
        if not getattr(p, "configured", False):
            return {"status": "not_configured"}
        numbers = json.dumps({k: v for k, v in doc.items() if k not in ("_id", "built_at", "summary")}, default=str)
        raw = await p.complete(SUMMARY_SYSTEM, numbers, max_tokens=16000, json_schema=SUMMARY_SCHEMA)
        return {"status": "ok", "model": getattr(p, "model", None), **json.loads(raw)}
    except (ProviderError, ValueError) as exc:
        return {"status": "error", "message": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"[:300]}


async def get(day: str | None = None) -> dict | None:
    if not ledger.ENABLED:
        return {"enabled": False}
    day = day or datetime.now(IST).date().isoformat()
    doc = await ledger._db()[COLLECTION].find_one({"_id": day})
    if doc:
        doc["built_at"] = _iso(doc.get("built_at"))
    return doc
