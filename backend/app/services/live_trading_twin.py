"""The Live Trading paper twin, read beside the REAL desk (2026-11-18). Read only.

The twin is one Live Intraday book (`live_intraday_engine.TWIN_BOOK`, "ltpaper") configured from the
real-money desk: the same strategies (whichever are switched on there), the same Rs 30,000 a position at
5x MIS, at most five at once, one per stock, the same 3% breaker, and the real Angel balance of 18 Nov 2026
as its money. It copies the tournament's own fills, so it shows what the desk's RULES earn with perfect
fills and no refusals. This module puts each of its trades beside what the real desk did with the same
tournament signal, which is where the two part:

  * the real desk sizes on the live quote and fills at Angel's price; the twin at the tournament's;
  * Angel refuses stocks on the exchange's caution list (AB4036) - the twin takes them;
  * the real desk copies a signal only within 180 s and only while it is ARMED; the twin always does;
  * a real order can fail; a paper one cannot.

Each real decision is the `copy|<tournament position id>` claim the real desk writes before it orders
(`live_trading_state`), and each real position carries `parent_id`, the tournament position it copied.
Nothing here writes, orders or quotes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.db import (live_intraday_positions_collection, live_trading_positions_collection,
                         live_trading_state_collection)
from app.services.book_reset import naive_utc


def _iso(v) -> str | None:
    if not isinstance(v, datetime):
        return v if isinstance(v, str) else None
    return naive_utc(v).replace(tzinfo=timezone.utc).isoformat()


def real_outcome(claim: dict | None, real: dict | None) -> tuple[str, str]:
    """(kind, words) for what the real desk did with one tournament signal."""
    if real is not None:
        return "taken", "taken by the real desk"
    if claim is None:
        return "not_seen", ("not tried by the real desk (it copies a signal only within 180 s, while "
                            "its loop runs and the strategy's switch is on)")
    decision = str(claim.get("decision") or "")
    if decision.startswith("Angel refused"):
        return "refused", decision
    if decision == "desk disarmed":
        return "disarmed", "the real desk was disarmed"
    if decision in ("opened", "ordering"):
        return "taken", "taken by the real desk"
    return "skipped", decision or "skipped by the real desk"


def _net(row: dict) -> float:
    if row.get("status") == "OPEN":
        return float(row.get("unrealized_pnl") or 0.0)
    return float(row.get("realized_pnl") or 0.0)


def _side_by_side(paper: dict | None, real: dict | None, claim: dict | None) -> dict:
    kind, words = real_outcome(claim, real)
    base = paper or real or {}
    out = {
        "parent_id": (paper or {}).get("parent_position_id") or (real or {}).get("parent_id"),
        "opened_at": _iso(base.get("opened_at")), "symbol": base.get("symbol"), "side": base.get("side"),
        "strategy_id": base.get("strategy_id"), "strategy_name": base.get("strategy_name"),
        "real_outcome": kind, "real_outcome_text": words,
        "paper": None, "real": None,
    }
    if paper is not None:
        out["paper"] = {
            "qty": paper.get("qty"), "entry": paper.get("entry_price"), "exit": paper.get("exit_price"),
            "status": paper.get("status"), "net": round(_net(paper), 2),
            "fees": paper.get("fees"), "notional": paper.get("notional"),
            "margin": paper.get("capital_deployed"), "exit_reason": paper.get("exit_reason"),
            "closed_at": _iso(paper.get("closed_at")),
        }
    if real is not None:
        out["real"] = {
            "qty": real.get("qty"), "entry": real.get("entry_fill_price") or real.get("entry_price"),
            "exit": real.get("exit_fill_price") or real.get("exit_price"), "status": real.get("status"),
            "net": round(_net(real), 2), "fees": real.get("fees"), "exit_reason": real.get("exit_reason"),
            "closed_at": _iso(real.get("closed_at")),
        }
    return out


def _tally(rows: list[dict], key: str) -> dict:
    xs = [r[key] for r in rows if r.get(key)]
    closed = [x for x in xs if x.get("status") != "OPEN"]
    return {
        "trades": len(xs), "closed": len(closed), "open": len(xs) - len(closed),
        "wins": sum(1 for x in closed if (x.get("net") or 0) > 0),
        "net": round(sum(float(x.get("net") or 0.0) for x in xs), 2),
        "realized": round(sum(float(x.get("net") or 0.0) for x in closed), 2),
    }


async def compare(limit: int = 300) -> dict:
    """The twin's summary, then every trade since it started with the real desk's beside it."""
    from app.services import live_intraday_engine as li
    from app.services import live_intraday_mirror as mirror

    book = li.TWIN_BOOK
    desk = li.twin_desk()
    summary = await li.summary(book)
    started = await mirror.started_at(book)
    start = naive_utc(started) if started else li.TWIN_START

    paper_rows = [r async for r in live_intraday_positions_collection.find(
        {"book": book, "opened_at": {"$gte": start}}).sort("opened_at", -1).limit(limit)]
    real_rows = [r async for r in live_trading_positions_collection.find(
        {"opened_at": {"$gte": start}}).sort("opened_at", -1).limit(limit)]
    pids = {r["parent_position_id"] for r in paper_rows if r.get("parent_position_id")}
    pids |= {r["parent_id"] for r in real_rows if r.get("parent_id")}
    claims: dict[str, dict] = {}
    if pids:
        async for c in live_trading_state_collection.find({"_id": {"$in": [f"copy|{p}" for p in pids]}}):
            claims[str(c["_id"]).split("|", 1)[1]] = c

    real_by_parent = {r["parent_id"]: r for r in real_rows if r.get("parent_id")}
    rows = []
    for p in paper_rows:
        pid = p.get("parent_position_id")
        rows.append(_side_by_side(p, real_by_parent.pop(pid, None) if pid else None, claims.get(pid)))
    # Real trades the twin did not take (its slots were full, it held the stock, ...) or with no parent.
    for r in real_rows:
        if r.get("parent_id") in real_by_parent or not r.get("parent_id"):
            rows.append(_side_by_side(None, r, claims.get(r.get("parent_id"))))
    rows.sort(key=lambda x: x.get("opened_at") or "", reverse=True)

    both = [r for r in rows if r["paper"] and r["real"]]
    outcomes: dict[str, int] = {}
    for r in rows:
        if r["paper"] and not r["real"]:
            outcomes[r["real_outcome"]] = outcomes.get(r["real_outcome"], 0) + 1
    flags = await _switches(desk)
    return {
        "book": book,
        "summary": summary,
        "copying_since": _iso(start),
        "capital_read_at": li.TWIN_CAPITAL_READ_AT,
        "real_desk": {
            "copy_notional": desk.COPY_NOTIONAL, "max_open_positions": desk.MAX_OPEN_POSITIONS,
            "mis_leverage": desk.MIS_LEVERAGE, "breaker_pct": desk.DAILY_LOSS_BREAKER_PCT,
            "strategies": flags,
        },
        "totals": {
            "paper": _tally(rows, "paper"),
            "real": _tally(rows, "real"),
            "both": len(both),
            "paper_only": sum(outcomes.values()),
            "paper_only_by_reason": outcomes,
            "real_only": sum(1 for r in rows if r["real"] and not r["paper"]),
            # On the trades BOTH took: how far the real result is from the paper one.
            "both_paper_net": round(sum(r["paper"]["net"] for r in both), 2),
            "both_real_net": round(sum(r["real"]["net"] for r in both), 2),
        },
        "rows": rows[:limit],
    }


async def _switches(desk) -> list[dict]:
    """The real desk's strategies, each with its switch and when it last changed."""
    from app.core.db import live_trading_flags_collection

    flags = {f.get("strategy_id"): f async for f in live_trading_flags_collection.find({})}
    out = []
    for ls in desk.SELECTED:
        f = flags.get(ls.strategy_id)
        out.append({"strategy_id": ls.strategy_id, "name": ls.name,
                    "enabled": bool(f.get("enabled", True)) if f else ls.default_enabled,
                    "since": _iso(f.get("updated_at")) if f else None})
    return out
