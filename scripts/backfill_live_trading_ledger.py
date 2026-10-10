"""Correct the REAL-MONEY ledger already on disk: charges on every trade, and the 49 broker
square-offs re-priced at their own day's close instead of the next session's price.

WHY. Until 2026-10-10 `live_trading_engine` recorded GROSS P&L on real trades (no Angel
charges at all), and a position Angel had squared off on its own was booked whenever the
desk next noticed it — the following session — at that session's price. Measured on
production: 78 real round trips 10-20 Aug 2026, 0 with charges, 49 `stale_session_reconciled`
(30 opened 18 Aug and booked 19 Aug, 19 opened 19 Aug and booked 20 Aug).

The engine now does both correctly going forward. This repairs what is already recorded.

WHAT EACH ROW BECOMES
  every closed position   charged on Angel's rate card (`angel_fees.round_trip`, checked
                          against the published card to the rupee); realized_pnl = gross -
                          charges; closed_on written.
  stale_session_reconciled  exit re-priced at the NSE close of the day it was OPENED — the
                          day the broker squared it off — from the daily bar store; labelled
                          as an estimate in `exit_basis`.
  status                  `reconciled` only when BOTH legs carry Angel's real fill;
                          otherwise `needs_contract_note`. Only the contract note can turn an
                          estimate into a fact (scripts/live_trading_contract_notes.py).

NOTHING IS LOST. The first run copies each row's original exit price and P&L into
`reported_exit_price` / `reported_realized_pnl` and never overwrites them again, so the run
is idempotent and the original record stays on the row. A verified gzip backup of both
collections is written before anything changes, and the run aborts if it does not read back.

Run inside the backend image:
    python /tmp/backfill_live_trading_ledger.py            dry run
    python /tmp/backfill_live_trading_ledger.py --apply
"""

import asyncio
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

from bson import json_util  # noqa: E402

import app.services.live_trading_engine as LT  # noqa: E402
from app.core.db import (  # noqa: E402
    live_trading_positions_collection as POS,
    live_trading_trades_collection as TRD,
)

APPLY = "--apply" in sys.argv
BACKUP_DIR = os.getenv("BACKFILL_BACKUP_DIR", "/app/data/backups")
IST = timezone(timedelta(hours=5, minutes=30))


async def backup(pos: list, trd: list) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = f"{BACKUP_DIR}/live_trading_pre_ledger_fix_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl.gz"
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for name, docs in (("live_trading_positions", pos), ("live_trading_trades", trd)):
            for d in docs:
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
    return path


def ist_day(ts) -> str | None:
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).date().isoformat()


async def main() -> None:
    print("=" * 78)
    print("APPLYING" if APPLY else "DRY RUN — nothing will be written")
    print("=" * 78)
    pos = [p async for p in POS.find({})]
    trd = [t async for t in TRD.find({})]
    await backup(pos, trd)

    before = sum(p.get("realized_pnl") or 0.0 for p in pos if p.get("status") == "CLOSED")
    after = charges = 0.0
    counts = {"reconciled": 0, "needs_contract_note": 0, "repriced_stale": 0, "skipped_open": 0}
    plan = []
    for p in pos:
        if p.get("status") != "CLOSED":
            counts["skipped_open"] += 1
            continue
        reported_exit = p.get("reported_exit_price", p.get("exit_price"))
        reported_pnl = p.get("reported_realized_pnl", p.get("realized_pnl"))
        exit_px = p.get("exit_fill_price") or p.get("exit_price")
        upd = {"reported_exit_price": reported_exit, "reported_realized_pnl": reported_pnl}
        closed_on = p.get("closed_on") or ist_day(p.get("closed_at"))

        if p.get("exit_reason") == "stale_session_reconciled":
            day = p.get("opened_on")
            est = await LT._close_of_session(p["symbol"], day) if day else None
            if est:
                exit_px = est
                upd["exit_basis"] = (f"estimate: NSE close on {day} — Angel squared this off that "
                                     "afternoon; first booked a day later at "
                                     f"{reported_exit} (next-session price)")
                counts["repriced_stale"] += 1
            else:
                upd["exit_basis"] = (f"estimate: next-session price {reported_exit} — no close on "
                                     f"file for {day}")
            closed_on = day

        money = LT._charge(p["entry_price"], exit_px, p["qty"], p["side"])
        both_fills = p.get("entry_fill_price") is not None and p.get("exit_fill_price") is not None
        status = "reconciled" if both_fills and p.get("exit_reason") != "stale_session_reconciled" \
            else "needs_contract_note"
        counts[status] += 1
        upd.update({"exit_price": round(exit_px, 2), **money, "closed_on": closed_on,
                    "reconcile_status": status, "ledger_fixed_at": datetime.now(timezone.utc)})
        after += money["realized_pnl"]
        charges += money["fees"]
        plan.append((p, upd))

    print(f"\n  closed real positions   {len(plan)}")
    print(f"  re-priced stale         {counts['repriced_stale']} (at their own day's close)")
    print(f"  reconciled (both fills) {counts['reconciled']}")
    print(f"  needs contract note     {counts['needs_contract_note']}")
    print(f"\n  recorded P&L  Rs {before:>10,.2f}   (gross, and 49 at next-day prices)")
    print(f"  charges       Rs {charges:>10,.2f}   (rate card; none were recorded)")
    print(f"  corrected P&L Rs {after:>10,.2f}   (net)")
    print("\n  largest changes:")
    for p, u in sorted(plan, key=lambda x: -abs(x[1]["realized_pnl"] - (x[0].get("realized_pnl") or 0)))[:8]:
        print(f"    {p.get('opened_on')} {p['symbol']:<10} {p['side']:<4} x{p['qty']:<4} "
              f"{p.get('exit_reason'):<26} {p.get('realized_pnl') or 0:>9.2f} -> {u['realized_pnl']:>9.2f}  "
              f"exit {p.get('exit_price')} -> {u['exit_price']}")

    if not APPLY:
        print("\n  re-run with --apply to write")
        return

    for p, u in plan:
        await POS.update_one({"_id": p["_id"]}, {"$set": u})
        if p.get("entry_order_id"):
            await TRD.update_one(
                {"entry_order_id": p["entry_order_id"], "strategy_id": p["strategy_id"]},
                {"$set": {k: u[k] for k in ("exit_price", "gross_pnl", "fees", "fee_breakdown",
                                            "realized_pnl", "charges_basis") if k in u}
                 | ({"exit_basis": u["exit_basis"]} if "exit_basis" in u else {})
                 | {"reported_realized_pnl": u["reported_realized_pnl"]}})
    for sid in {p["strategy_id"] for p, _ in plan}:
        await LT._update_score(sid)
    print(f"\n  wrote {len(plan)} positions, their blotter rows, and {len({p['strategy_id'] for p, _ in plan})} scores")


asyncio.run(main())
