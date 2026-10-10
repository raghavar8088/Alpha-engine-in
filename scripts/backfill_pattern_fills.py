"""Re-run the Patterns desk's first sessions through the corrected fill rules.

WHY. Until 2026-10-10 `intraday_pattern_engine` closed every trade at whatever LTP its
three-minute poll happened to see — so price that had run PAST a target was booked as profit
— and charged no slippage on any fill. Over 6-9 Oct 2026 that reported +Rs52.97 lakh for a
desk that, filled honestly, lost money (INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md, D1). The
engine now fills like the tournament; this repairs the record already written, and the two
Paper Trade books that copied it.

THE RULE APPLIED — the fixed engine's own quote path, on the prices the desk actually saw.
The stream's minute bars for those sessions are gone, and 13 of the 23 names traded are
outside the 200-name intraday universe, so most have no stored 5-minute bars either. The
only price record that exists for every trade is the quote each decision was made on. So
each trade is replayed exactly as the corrected engine treats a name it has no minute bars
for:
    entry           the recorded price plus slippage (a market order), by that day's
                    turnover bucket (`intraday_fills.slippage_bp`; names outside the
                    universe pay the thinnest bucket)
    target exit     AT the target — a resting limit order never fills better than its level
    stop / time /   the recorded quote less slippage (market orders)
    end of day
Charges are recomputed on the corrected prices. The exit REASON is kept as recorded: from a
three-minute poll nobody can know whether a stop was touched on the way to a target, and
inventing that would be a guess in the other direction.

NOTHING IS LOST. Each corrected row keeps its original numbers under `reported_*`, gains
`fill_corrected_at`, and is skipped on any later run, so the script is idempotent. Equity
marks keep `reported_equity` / `reported_realized`. A verified gzip backup of every collection
touched is written first, and the run aborts if it does not read back.

Run inside the backend image:
    python /tmp/backfill_pattern_fills.py            dry run
    python /tmp/backfill_pattern_fills.py --apply
"""

import asyncio
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

from bson import json_util  # noqa: E402

import app.services.intraday_pattern_engine as PE  # noqa: E402
import app.services.pattern_books_engine as PB  # noqa: E402
from app.core.db import db  # noqa: E402
from app.services import intraday_universe  # noqa: E402
from app.services.angel_fees import product_for, round_trip  # noqa: E402
from app.services.intraday_fills import adverse, slippage_bp  # noqa: E402

APPLY = "--apply" in sys.argv
BACKUP_DIR = os.getenv("BACKFILL_BACKUP_DIR", "/app/data/backups")
IST = timezone(timedelta(hours=5, minutes=30))
COLLS = ("pattern_positions", "pattern_trades", "pattern_scores", "pattern_equity",
         "pattern_book_positions", "pattern_book_trades", "pattern_book_scores",
         "pattern_book_equity")
MARKET = {"stoploss", "eod", "time_stop", "max_hold"}


async def backup() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = f"{BACKUP_DIR}/patterns_pre_fill_fix_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl.gz"
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for name in COLLS:
            async for d in db[name].find({}):
                fh.write(json.dumps({"_collection": name, "doc": d}, default=json_util.default) + "\n")
                n += 1
    back = 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            json.loads(line)
            back += 1
    print(f"  backup  {path}\n          {n} rows written, {back} read back "
          f"{'OK' if back == n else '*** MISMATCH ***'}")
    if back != n:
        raise SystemExit("backup did not verify — nothing changed")


def ist_day(ts) -> str | None:
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).date().isoformat()


def aware(ts):
    return ts.replace(tzinfo=timezone.utc) if ts is not None and ts.tzinfo is None else ts


_turnover_cache: dict[str, dict[str, float]] = {}


async def turnover_on(day: str) -> dict[str, float]:
    if day not in _turnover_cache:
        doc = await intraday_universe.on(day)
        _turnover_cache[day] = {m["symbol"]: m.get("turnover_cr")
                                for m in ((doc or {}).get("members") or [])}
    return _turnover_cache[day]


def money(entry: float, exit_: float, qty: int, side: str, days: int) -> dict:
    sign = 1 if side == "BUY" else -1
    gross = round(sign * (exit_ - entry) * qty, 2)
    fb = round_trip(entry, exit_, qty, side=side, product=product_for(None, days))
    return {"gross_pnl": gross, "fees": fb.total, "fee_breakdown": fb.as_dict(),
            "realized_pnl": round(gross - fb.total, 2)}


async def main() -> None:
    print("=" * 78)
    print("APPLYING" if APPLY else "DRY RUN — nothing will be written")
    print("=" * 78)
    await backup()

    # ── the desk ────────────────────────────────────────────────────────────────
    parents = [p async for p in db["pattern_positions"].find({"status": "CLOSED"})]
    todo = [p for p in parents if not p.get("fill_corrected_at")]
    print(f"\n  closed pattern positions {len(parents):,}; to correct {len(todo):,}")
    corrected: dict[str, dict] = {}            # position_id -> the corrected numbers
    totals = defaultdict(float)
    by_reason = defaultdict(lambda: [0, 0.0, 0.0])
    bucket = defaultdict(int)
    for p in todo:
        side, qty = p["side"], int(p["qty"])
        opened_on = p.get("opened_on") or ist_day(p.get("opened_at"))
        closed_on = p.get("closed_on") or ist_day(p.get("closed_at"))
        tv = (await turnover_on(opened_on)).get(p["symbol"])
        bp = slippage_bp(tv)
        bucket[bp] += 1
        entry = adverse(float(p["entry_price"]), side, bp, opening=True)
        reason = p.get("exit_reason")
        if reason == "target" and p.get("target"):
            exit_ = float(p["target"])
            basis = f"level @ {exit_:.2f} (corrected: was booked at {p['exit_price']})"
        else:
            px = float(p["exit_price"])
            exit_ = adverse(px, side, bp, opening=False)
            basis = f"market @ {px:.2f} (recorded quote) - {bp:g} bp"
        days = 0
        if opened_on and closed_on:
            days = (datetime.fromisoformat(closed_on).date()
                    - datetime.fromisoformat(opened_on).date()).days
        m = money(entry, exit_, qty, side, days)
        upd = {
            "reported_entry_price": p["entry_price"], "reported_exit_price": p["exit_price"],
            "reported_gross_pnl": p.get("gross_pnl"), "reported_fees": p.get("fees"),
            "reported_realized_pnl": p.get("realized_pnl"),
            "signal_price": p["entry_price"], "entry_price": round(entry, 2),
            "exit_price": round(exit_, 2), **m, "slippage_bp": bp, "turnover_cr": tv,
            "fill_basis": f"market @ {p['entry_price']} (recorded quote) + {bp:g} bp slippage",
            "exit_basis": basis, "closed_on": closed_on,
            "fill_corrected_at": datetime.now(timezone.utc),
        }
        corrected[p["position_id"]] = {**upd, "_id": p["_id"], "strategy_id": p["strategy_id"],
                                       "symbol": p["symbol"], "opened_at": p.get("opened_at"),
                                       "closed_at": p.get("closed_at"), "days": days}
        totals["before"] += p.get("realized_pnl") or 0.0
        totals["after"] += m["realized_pnl"]
        r = by_reason[reason]
        r[0] += 1
        r[1] += p.get("realized_pnl") or 0.0
        r[2] += m["realized_pnl"]

    print(f"  slippage buckets (bp: trades): {dict(sorted(bucket.items()))}")
    print(f"\n  {'exit reason':<12}{'trades':>8}{'reported net':>16}{'corrected net':>16}")
    for k, (n, b, a) in sorted(by_reason.items(), key=lambda kv: -kv[1][0]):
        print(f"  {str(k):<12}{n:>8,}{b:>16,.0f}{a:>16,.0f}")
    print(f"  {'TOTAL':<12}{len(todo):>8,}{totals['before']:>16,.0f}{totals['after']:>16,.0f}")

    # ── the two Paper Trade books, which copied the parent's prices ─────────────
    books = [b async for b in db["pattern_book_positions"].find({"status": "CLOSED"})]
    btodo = [b for b in books if not b.get("fill_corrected_at")]
    all_parents = {p["position_id"]: p async for p in db["pattern_positions"].find({})}
    book_upd = []
    btot = defaultdict(lambda: [0, 0.0, 0.0])
    missing_parent = 0
    for b in btodo:
        par = corrected.get(b.get("parent_position_id"))
        if par is None:
            pp = all_parents.get(b.get("parent_position_id"))
            if pp and pp.get("fill_corrected_at"):          # parent corrected on an earlier run
                par = {"entry_price": pp["entry_price"], "exit_price": pp["exit_price"],
                       "days": 0, "closed_on": pp.get("closed_on"), "exit_basis": pp.get("exit_basis")}
            else:
                missing_parent += 1
                continue
        m = money(par["entry_price"], par["exit_price"], int(b["qty"]), b["side"], par.get("days", 0))
        u = {"reported_entry_price": b["entry_price"], "reported_exit_price": b.get("exit_price"),
             "reported_gross_pnl": b.get("gross_pnl"), "reported_fees": b.get("fees"),
             "reported_realized_pnl": b.get("realized_pnl"),
             "entry_price": par["entry_price"], "exit_price": par["exit_price"], **m,
             "closed_on": b.get("closed_on") or par.get("closed_on") or ist_day(b.get("closed_at")),
             "exit_basis": par.get("exit_basis"), "fill_corrected_at": datetime.now(timezone.utc)}
        book_upd.append((b, u))
        t = btot[b["book"]]
        t[0] += 1
        t[1] += b.get("realized_pnl") or 0.0
        t[2] += m["realized_pnl"]
    print(f"\n  Paper Trade books: {len(btodo)} closed rows to correct"
          + (f" ({missing_parent} without a parent on file — left as recorded)" if missing_parent else ""))
    for bk, (n, bb, aa) in sorted(btot.items()):
        print(f"    book {bk:<6}{n:>6} trades   reported {bb:>12,.0f}   corrected {aa:>12,.0f}")

    if not APPLY:
        print("\n  re-run with --apply to write")
        return

    # ── write ───────────────────────────────────────────────────────────────────
    for pid, c in corrected.items():
        upd = {k: v for k, v in c.items() if k not in ("_id", "strategy_id", "symbol", "opened_at",
                                                        "closed_at", "days")}
        await db["pattern_positions"].update_one({"_id": c["_id"]}, {"$set": upd})
        await db["pattern_trades"].update_one(
            {"strategy_id": c["strategy_id"], "symbol": c["symbol"], "opened_at": c["opened_at"]},
            {"$set": {k: upd[k] for k in ("entry_price", "exit_price", "gross_pnl", "fees",
                                           "realized_pnl", "exit_basis", "reported_realized_pnl")}})
    for sid in {c["strategy_id"] for c in corrected.values()}:
        await PE._update_score(sid)
    print(f"  wrote {len(corrected):,} desk positions, their trades and scores")

    for b, u in book_upd:
        await db["pattern_book_positions"].update_one({"_id": b["_id"]}, {"$set": u})
        await db["pattern_book_trades"].update_one(
            {"book": b["book"], "strategy_id": b["strategy_id"], "symbol": b["symbol"],
             "opened_at": b["opened_at"]},
            {"$set": {k: u[k] for k in ("entry_price", "exit_price", "gross_pnl", "fees",
                                         "realized_pnl", "closed_on", "exit_basis")}})
    await PB._update_scores({(b["book"], b["strategy_id"]) for b, _ in book_upd})
    print(f"  wrote {len(book_upd)} book positions, their trades and scores")

    # ── equity marks: realised re-summed from the corrected trades ──────────────
    desk_closes = sorted([(aware(p.get("closed_at")), p.get("realized_pnl") or 0.0)
                          async for p in db["pattern_positions"].find(
                              {"status": "CLOSED"}, {"closed_at": 1, "realized_pnl": 1})
                          if p.get("closed_at")])
    n_marks = 0
    async for mk in db["pattern_equity"].find({"reported_realized": {"$exists": False}}):
        ts = aware(mk["ts"])
        realized = round(sum(r for t, r in desk_closes if t <= ts), 2)
        base = (mk.get("equity") or 0.0) - (mk.get("realized") or 0.0) - (mk.get("unrealized") or 0.0)
        delta = realized - (mk.get("realized") or 0.0)
        upd = {"reported_realized": mk.get("realized"), "reported_equity": mk.get("equity"),
               "realized": realized, "equity": round((mk.get("equity") or 0.0) + delta, 2)}
        if base > 0 and mk.get("roi_pct") is not None:
            upd["roi_pct"] = round((mk["roi_pct"] or 0.0) + delta / base * 100, 4)
        await db["pattern_equity"].update_one({"_id": mk["_id"]}, {"$set": upd})
        n_marks += 1
    book_closes = defaultdict(list)
    async for b in db["pattern_book_positions"].find({"status": "CLOSED"},
                                                     {"book": 1, "closed_at": 1, "realized_pnl": 1}):
        if b.get("closed_at"):
            book_closes[b["book"]].append((aware(b["closed_at"]), b.get("realized_pnl") or 0.0))
    async for mk in db["pattern_book_equity"].find({"reported_realized": {"$exists": False}}):
        ts = aware(mk["ts"])
        realized = round(sum(r for t, r in book_closes.get(mk.get("book"), []) if t <= ts), 2)
        delta = realized - (mk.get("realized") or 0.0)
        await db["pattern_book_equity"].update_one({"_id": mk["_id"]}, {"$set": {
            "reported_realized": mk.get("realized"), "reported_equity": mk.get("equity"),
            "realized": realized, "equity": round((mk.get("equity") or 0.0) + delta, 2)}})
        n_marks += 1
    print(f"  re-summed {n_marks} equity marks from the corrected trades")


asyncio.run(main())
