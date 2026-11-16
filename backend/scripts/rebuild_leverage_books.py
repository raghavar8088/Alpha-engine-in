"""Replay the Intraday Stocks paper accounts' history at 5x intraday leverage (2026-11-16).

The owner asked for the module's accounts to trade with 5x intraday leverage, and for the rule to
apply to the existing data as well as to future trades. So each account is REPLAYED from its first
trade, against the same parent trades it copied: the tournament's for the Live Intraday books, the
Patterns desk's for the Patterns paper books. The replay uses the plan_book rules the live passes
use now (`book_rules`): 5x on an eligible intraday copy, 20% of its value blocked as margin, the
same slots, one stock at a time, whole shares, Angel's costs on the quantity held, and (Live
Intraday) the 3% daily breaker followed on the trades' own clock. P&L is the price move on the
shares the replay holds; nothing is multiplied.

Run inside the backend image with the production environment (the box), from /app/backend:
  python scripts/rebuild_leverage_books.py --desk live-intraday --out DIR            # dry run
  python scripts/rebuild_leverage_books.py --desk live-intraday --out DIR --write    # rewrite
  python scripts/rebuild_leverage_books.py --restore DIR/live-intraday-2L.json.gz    # undo one book

Per book:
 1. CHECK. Replays the parents at 1x - the rule the record was written under - and requires that
    to reproduce the book's existing rows: the same parents taken, at the same quantity, with the
    same realised net. A book that does not reproduce is NOT rewritten (its record holds something
    the replay does not model), unless --allow-mismatch names it after the report was read.
 2. REPLAY at the rules now.
 3. --write: exports every document it will replace to DIR/<desk>-<book>.json.gz (canonical
    extended JSON, so --restore puts back the exact documents), deletes exactly those, writes the
    replayed rows, trades, skip records and scores through the module's own writers, and
    recomputes the book's equity snapshots at their original times from realised P&L - a past
    intraday mark cannot be known - flagged `rebuilt`.
Rows from before an account copied a desk (another source) are left as they are.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import gzip
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bson import json_util                                    # noqa: E402
from pymongo import ReplaceOne, UpdateOne                      # noqa: E402

REBUILT_REASON = "5x intraday leverage replay, 2026-11-16"


@dataclass
class Desk:
    key: str
    tag: str
    books: list[str]
    positions: Any
    trades: Any
    scores: Any
    state: Any
    equity: Any
    capital: Callable[[str], float]
    roster: Callable[[str], Any]
    floor: Callable[[str], Awaitable[datetime]]
    parents: Callable[[datetime, list[str]], Awaitable[list[dict]]]
    rules: Callable[[str], dict]
    row: Callable[..., dict]
    close_fields: Callable[[dict, dict], dict]
    trade: Callable[..., Awaitable[None]]
    score: Callable[..., Awaitable[None]]
    skip_id: Callable[[str, str], str]
    marks_pct: bool                       # whether open rows carry pnl_pct (Live Intraday)


def _live_desk() -> Desk:
    from app.core import db as D
    from app.services import live_intraday_engine as li
    from app.services import live_intraday_mirror as m

    async def floor(book: str) -> datetime:
        return await m._floor(book, await m._mirror_start())

    return Desk(
        key="live-intraday", tag=m.SOURCE_TAG, books=list(li.BOOKS) if li.COPIES_TOURNAMENT else [],
        positions=D.live_intraday_positions_collection, trades=D.live_intraday_trades_collection,
        scores=D.live_intraday_scores_collection, state=D.live_intraday_state_collection,
        equity=D.live_intraday_equity_collection,
        capital=li.book_capital, roster=li.book_roster, floor=floor, parents=m._parents,
        rules=m.book_rules,
        row=lambda book, p, o, capital: m._row(book, p, o["qty"], o["spend"], o.get("notional"),
                                               o.get("leverage", 1.0)),
        close_fields=m._close_fields, trade=m._trade,
        score=lambda book, sid, skips, capital: m._score(book, sid, skips),
        skip_id=m._skip_doc_id, marks_pct=True)


def _pattern_desk() -> Desk:
    from app.core import db as D
    from app.services import pattern_books_copy as c
    from app.services import pattern_books_engine as pbe

    return Desk(
        key="pattern-books", tag=c.SOURCE_TAG, books=list(pbe.COPY_BOOKS),
        positions=D.pattern_book_positions_collection, trades=D.pattern_book_trades_collection,
        scores=D.pattern_book_scores_collection, state=D.pattern_book_state_collection,
        equity=D.pattern_book_equity_collection,
        capital=pbe.book_capital, roster=pbe.book_roster, floor=c._floor, parents=c._parents,
        rules=c.book_rules,
        row=lambda book, p, o, capital: c._row(book, p, o["qty"], o["spend"], capital,
                                               o.get("notional"), o.get("leverage", 1.0)),
        close_fields=c._close_fields, trade=c._trade,
        score=lambda book, sid, skips, capital: c._score(book, sid, skips, capital),
        skip_id=c._skip_doc, marks_pct=False)


DESKS = {"live-intraday": _live_desk, "pattern-books": _pattern_desk}


def _naive(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _plan(desk: Desk, book: str, capital: float, realized: float, parents: list[dict],
          *, old_rule: bool) -> dict:
    from app.services.live_intraday_mirror import plan_book

    rules = dict(desk.rules(book))
    if old_rule:                    # the rule the record was written under: 1x, the per-pass breaker
        rules.pop("leverage_fn", None)
        rules.pop("loss_limit", None)
    return plan_book(capital=capital, realized=realized, deployed=0.0, open_rows=[],
                     parents=parents, decided=set(), breaker_tripped=False, entries=True,
                     closed_rows=[], **rules)


def _replayed(plan: dict) -> dict[str, dict]:
    """parent id -> what the replay holds: qty, margin, value, leverage, net (None while open)."""
    out = {}
    for o in plan["opens"]:
        c = o["close"]
        out[o["parent"]["position_id"]] = {
            "qty": o["qty"], "spend": o["spend"], "notional": o.get("notional", o["spend"]),
            "leverage": o.get("leverage", 1.0), "net": None if c is None else c["net"],
            "gross": None if c is None else c["gross"], "fees": None if c is None else c["fb"].total}
    return out


def _timeline(plan: dict) -> dict:
    """Max open, max margin, max exposure and min free margin on the trades' own clock."""
    ev = []
    for o in plan["opens"]:
        p = o["parent"]
        ev.append((_naive(p.get("opened_at")), 1, o))
        if o["close"] is not None:
            ev.append((_naive(p.get("closed_at")), 0, o))
    ev.sort(key=lambda e: (e[0] or datetime.min, e[1]))
    n = margin = value = 0.0
    peak = {"max_open": 0, "max_margin": 0.0, "max_exposure": 0.0}
    for _at, kind, o in ev:
        sgn = 1 if kind == 1 else -1
        n += sgn
        margin += sgn * o["spend"]
        value += sgn * o.get("notional", o["spend"])
        peak["max_open"] = max(peak["max_open"], int(n))
        peak["max_margin"] = round(max(peak["max_margin"], margin), 2)
        peak["max_exposure"] = round(max(peak["max_exposure"], value), 2)
    return peak


def _totals(rep: dict[str, dict]) -> dict:
    closed = [r for r in rep.values() if r["net"] is not None]
    return {"trades": len(closed), "open": len(rep) - len(closed),
            "net": round(sum(r["net"] for r in closed), 2),
            "gross": round(sum(r["gross"] for r in closed), 2),
            "fees": round(sum(r["fees"] for r in closed), 2),
            "wins": sum(1 for r in closed if r["net"] > 0)}


async def _analyse(desk: Desk, book: str) -> dict:
    capital = desk.capital(book)
    floor = await desk.floor(book)
    rows = [r async for r in desk.positions.find({"book": book})]
    tagged = [r for r in rows if r.get("source") == desk.tag]
    other = [r for r in rows if r.get("source") != desk.tag]
    problems: list[str] = []
    for r in other:
        if r.get("status") == "OPEN":
            problems.append(f"untagged OPEN row {r.get('position_id')}")
        elif r.get("status") == "CLOSED" and (_naive(r.get("closed_at")) or datetime.min) > floor:
            problems.append(f"untagged row {r.get('position_id')} closed after the floor")
    legacy_realized = round(sum(float(r.get("realized_pnl") or 0.0) for r in other
                                if r.get("status") == "CLOSED"), 2)
    pointed = [r["parent_position_id"] for r in tagged if r.get("parent_position_id")]
    parents = await desk.parents(floor, pointed)
    roster = desk.roster(book)
    if roster is not None:
        keep = set(roster)
        parents = [p for p in parents if p["strategy_id"] in keep]
    early = [p["position_id"] for p in parents if (_naive(p.get("opened_at")) or datetime.min) < floor]
    if early:
        problems.append(f"{len(early)} copied parents opened before the floor")
    statuses: dict[str, int] = {}
    for p in parents:
        statuses[str(p.get("status"))] = statuses.get(str(p.get("status")), 0) + 1

    old = _plan(desk, book, capital, legacy_realized, parents, old_rule=True)
    new = _plan(desk, book, capital, legacy_realized, parents, old_rule=False)
    rep_old, rep_new = _replayed(old), _replayed(new)

    have = {r["parent_position_id"]: r for r in tagged if r.get("parent_position_id")}
    only_rows = sorted(set(have) - set(rep_old))
    only_replay = sorted(set(rep_old) - set(have))
    qty_diff, net_diff, status_diff = [], [], []
    for pid in set(have) & set(rep_old):
        r, x = have[pid], rep_old[pid]
        if int(r.get("qty") or 0) != x["qty"]:
            qty_diff.append((pid, r.get("qty"), x["qty"]))
        if (r.get("status") == "OPEN") != (x["net"] is None):
            status_diff.append((pid, r.get("status")))
        elif x["net"] is not None and abs(float(r.get("realized_pnl") or 0.0) - x["net"]) > 0.011:
            net_diff.append((pid, r.get("realized_pnl"), x["net"]))
    closed_rows = [r for r in tagged if r.get("status") == "CLOSED"]
    recorded = {"trades": len(closed_rows), "open": sum(1 for r in tagged if r.get("status") == "OPEN"),
                "net": round(sum(float(r.get("realized_pnl") or 0) for r in closed_rows), 2),
                "gross": round(sum(float(r.get("gross_pnl") or 0) for r in closed_rows), 2),
                "fees": round(sum(float(r.get("fees") or 0) for r in closed_rows), 2),
                "wins": sum(1 for r in closed_rows if (r.get("realized_pnl") or 0) > 0)}
    skips_new: dict[str, int] = {}
    for s in new["skips"]:
        skips_new[s["reason"]] = skips_new.get(s["reason"], 0) + 1
    reproduces = not (only_rows or only_replay or qty_diff or status_diff or net_diff or problems)
    return {
        "book": book, "capital": capital, "floor": floor.isoformat(), "parents": len(parents),
        "parent_status": statuses, "rows": len(rows), "untagged_rows": len(other),
        "legacy_realized": legacy_realized, "problems": problems,
        "check": {"reproduces": reproduces, "only_in_rows": only_rows[:20], "only_in_replay": only_replay[:20],
                  "n_only_in_rows": len(only_rows), "n_only_in_replay": len(only_replay),
                  "qty_diff": qty_diff[:20], "n_qty_diff": len(qty_diff),
                  "net_diff": net_diff[:20], "n_net_diff": len(net_diff), "status_diff": status_diff[:20]},
        "recorded": recorded, "replay_1x": _totals(rep_old), "replay_now": _totals(rep_new),
        "replay_now_peaks": _timeline(new), "replay_1x_peaks": _timeline(old),
        "replay_now_skips": skips_new,
        "_plan": new, "_tagged": tagged, "_other": other, "_parents": parents,
    }


async def _backup(desk: Desk, book: str, tagged: list[dict], path: Path) -> dict:
    skip_docs = [d async for d in desk.state.find({"_id": {"$regex": f"^{_re(desk.skip_id(book, ''))}"}})]
    out = {
        "desk": desk.key, "book": book, "taken_at": datetime.now(timezone.utc),
        "positions": tagged,
        "trades": [d async for d in desk.trades.find({"book": book, "source": desk.tag})],
        "scores": [d async for d in desk.scores.find({"book": book, "source": desk.tag})],
        "skip_docs": skip_docs,
        "equity": [d async for d in desk.equity.find({"book": book})],
    }
    raw = json_util.dumps(out, json_options=json_util.CANONICAL_JSON_OPTIONS).encode()
    with gzip.open(path, "wb") as f:
        f.write(raw)
    back = json_util.loads(gzip.open(path, "rb").read())        # prove the file reads back whole
    counts = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    if {k: len(back[k]) for k in counts} != counts:
        raise RuntimeError(f"backup {path} does not read back: {counts}")
    return counts


def _re(prefix: str) -> str:
    import re
    return re.escape(prefix)


def _equity_fix(desk: Desk, snaps: list[dict], capital: float, legacy: list[dict],
                docs: list[dict]) -> list:
    """Each snapshot re-stated at its own time from the replayed rows: realised P&L and fees of
    what had closed, margin / value / count of what was open. Unrealised is 0 (a past mark is not
    knowable); `rebuilt` says so."""
    closes = sorted((_naive(d["closed_at"]), float(d.get("realized_pnl") or 0.0), float(d.get("fees") or 0.0))
                    for d in docs if d.get("status") == "CLOSED")
    closes += sorted((_naive(d.get("closed_at")) or datetime.min, float(d.get("realized_pnl") or 0.0),
                      float(d.get("fees") or 0.0)) for d in legacy if d.get("status") == "CLOSED")
    closes.sort(key=lambda c: c[0])
    ts_list = [c[0] for c in closes]
    cum_r, cum_f, r, f = [], [], 0.0, 0.0
    for _t, net, fee in closes:
        r += net
        f += fee
        cum_r.append(r)
        cum_f.append(f)
    spans = [(_naive(d.get("opened_at")), _naive(d.get("closed_at")) if d.get("status") == "CLOSED" else None,
              float(d.get("capital_deployed") or 0.0), float(d.get("notional") or d.get("capital_deployed") or 0.0))
             for d in docs]
    ops = []
    for s in snaps:
        ts = _naive(s.get("ts"))
        if ts is None:
            continue
        i = bisect.bisect_right(ts_list, ts)
        realized = cum_r[i - 1] if i else 0.0
        fees = cum_f[i - 1] if i else 0.0
        live = [sp for sp in spans if sp[0] and sp[0] <= ts and (sp[1] is None or sp[1] > ts)]
        equity = capital + realized
        fix = {"equity": round(equity, 2), "realized": round(realized, 2), "unrealized": 0.0,
               "open_positions": len(live), "rebuilt": True, "rebuilt_reason": REBUILT_REASON}
        if desk.key == "live-intraday":
            fix.update({"fees": round(fees, 2), "deployed": round(sum(sp[2] for sp in live), 2),
                        "exposure": round(sum(sp[3] for sp in live), 2),
                        "roi_pct": round((equity - capital) / capital * 100, 2) if capital else 0.0})
        ops.append(UpdateOne({"_id": s["_id"]}, {"$set": fix}))
    return ops


async def _write(desk: Desk, book: str, a: dict, out_dir: Path) -> dict:
    capital = a["capital"]
    tagged, plan = a["_tagged"], a["_plan"]
    path = out_dir / f"{desk.key}-{book}.json.gz"
    counts = await _backup(desk, book, tagged, path)

    # Build every new document first; nothing is deleted until all of them exist in memory.
    docs, closes = [], []
    for o in plan["opens"]:
        p = o["parent"]
        doc = desk.row(book, p, o, capital)
        if o["close"] is not None:
            doc.update(desk.close_fields(p, o["close"]))
            closes.append((doc, p, o["close"]))
        elif p.get("ltp"):
            ltp = float(p["ltp"])
            sign = 1 if (doc.get("side") or "BUY") == "BUY" else -1
            doc["ltp"] = round(ltp, 2)
            doc["unrealized_pnl"] = round(sign * (ltp - doc["entry_price"]) * doc["qty"], 2)
            if desk.marks_pct:
                doc["pnl_pct"] = round(sign * (ltp - doc["entry_price"]) / doc["entry_price"] * 100, 2)
        doc["rebuilt_reason"] = REBUILT_REASON
        docs.append(doc)
    skips_by_day: dict[str, list[str]] = {}
    skips_by_sid: dict[str, dict[str, int]] = {}
    for s in plan["skips"]:
        p = s["parent"]
        skips_by_day.setdefault(p.get("opened_on") or "", []).append(p["position_id"])
        per = skips_by_sid.setdefault(p["strategy_id"], {})
        per[s["reason"]] = per.get(s["reason"], 0) + 1
    sids = {d["strategy_id"] for d in docs} | set(skips_by_sid)
    snaps = [s async for s in desk.equity.find({"book": book}, {"_id": 1, "ts": 1})]
    eq_ops = _equity_fix(desk, snaps, capital, a["_other"], docs)

    # Replace. Only the documents the backup holds are deleted.
    await desk.positions.delete_many({"_id": {"$in": [r["_id"] for r in tagged]}})
    await desk.trades.delete_many({"book": book, "source": desk.tag})
    await desk.scores.delete_many({"book": book, "source": desk.tag})
    await desk.state.delete_many({"_id": {"$regex": f"^{_re(desk.skip_id(book, ''))}"}})
    if docs:
        await desk.positions.insert_many(docs, ordered=True)
    for doc, p, c in closes:
        await desk.trade(book, doc, p, c)
    for day, ids in skips_by_day.items():
        await desk.state.update_one({"_id": desk.skip_id(book, day)},
                                    {"$addToSet": {"ids": {"$each": ids}}, "$set": {"book": book, "day": day}},
                                    upsert=True)
    for sid in sorted(sids):
        await desk.score(book, sid, skips_by_sid.get(sid, {}), capital)
    for i in range(0, len(eq_ops), 1000):
        await desk.equity.bulk_write(eq_ops[i:i + 1000], ordered=False)
    return {"backup": str(path), "backed_up": counts, "rows_written": len(docs),
            "trades_written": len(closes), "skip_days": len(skips_by_day), "scores": len(sids),
            "equity_rewritten": len(eq_ops)}


async def _restore(path: Path) -> dict:
    data = json_util.loads(gzip.open(path, "rb").read())
    desk = DESKS[data["desk"]]()
    book = data["book"]
    await desk.positions.delete_many({"book": book, "source": desk.tag})
    await desk.trades.delete_many({"book": book, "source": desk.tag})
    await desk.scores.delete_many({"book": book, "source": desk.tag})
    await desk.state.delete_many({"_id": {"$regex": f"^{_re(desk.skip_id(book, ''))}"}})
    for coll, key in ((desk.positions, "positions"), (desk.trades, "trades"), (desk.scores, "scores"),
                      (desk.state, "skip_docs")):
        if data[key]:
            await coll.insert_many(data[key], ordered=False)
    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in data["equity"]]
    for i in range(0, len(ops), 1000):
        await desk.equity.bulk_write(ops[i:i + 1000], ordered=False)
    return {k: len(data[k]) for k in ("positions", "trades", "scores", "skip_docs", "equity")}


def _public(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.startswith("_")}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desk", choices=sorted(DESKS))
    ap.add_argument("--book", action="append", help="only these books (repeatable)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--allow-mismatch", action="append", default=[],
                    help="rewrite this book even though the 1x check did not reproduce it")
    ap.add_argument("--restore", type=Path)
    args = ap.parse_args()
    if args.restore:
        print(json.dumps({"restored": str(args.restore), **await _restore(args.restore)}, default=str))
        return 0
    if not (args.desk and args.out):
        ap.error("--desk and --out are required")
    args.out.mkdir(parents=True, exist_ok=True)
    desk = DESKS[args.desk]()
    report = []
    for book in desk.books:
        if args.book and book not in args.book:
            continue
        a = await _analyse(desk, book)
        entry = _public(a)
        if args.write:
            if a["check"]["reproduces"] or book in args.allow_mismatch:
                entry["write"] = await _write(desk, book, a, args.out)
            else:
                entry["write"] = "SKIPPED: the 1x check did not reproduce the recorded rows"
        report.append(entry)
        print(json.dumps({"book": book, "reproduces": a["check"]["reproduces"],
                          "recorded": a["recorded"], "replay_1x": a["replay_1x"],
                          "replay_now": a["replay_now"], "peaks": a["replay_now_peaks"],
                          "skips": a["replay_now_skips"], "write": entry.get("write")}, default=str),
              flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (args.out / f"report-{args.desk}-{'write' if args.write else 'dry'}-{stamp}.json").write_text(
        json.dumps(report, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
