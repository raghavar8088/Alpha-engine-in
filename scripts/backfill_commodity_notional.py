"""Rewrite the stored `contract_value` on every MCX option row to the notional it controls.

WHY. `contract_value(symbol, price, lots)` is a notional only when `price` IS the
underlying's price. For a future it is; for an option the price is the premium. Every
commodity option row ever written therefore stored premium x quantity under a field the
page renders as "contract value", and summed into an account's "contract exposure".

Measured on production 2026-10-08, before this ran:

    319 orders          Rs    4,79,67,500 stored  ->  Rs 138,61,96,500 correct   (28.9x)
     18 open positions  Rs      30,70,194 stored  ->  Rs   9,43,90,000 correct   (30.7x)
    146 closed positions            every one understated the same way

The code that writes these was fixed in the same change as this script; this repairs what
was already on disk. Open positions would have self-healed on the next mark-to-market,
but only while MCX is open — and orders and closed positions are never re-marked at all,
so without this they keep the wrong number for ever.

HOW EACH ROW IS REBUILT

    orders, open positions   strike x quantity. Both store the quantity they were filled
                             at, so this needs nothing but the row itself.

    closed positions         quantity and lots are both zeroed when a position fully
                             closes, so the row no longer knows how big it was. The size
                             is rebuilt from its own fills: the orders carrying its
                             position_id, summed over those in the OPENING direction.
                             All 146 had their orders on file. A row whose orders are
                             missing is left untouched and reported, never guessed at.

`instrument.multiplier` and `instrument.strike` are read from the row itself rather than
re-derived from the underlying, because they are what the position was actually sized
with — re-deriving would silently rewrite history if a spec were ever corrected.

`premium_value` is written alongside, which is the number `contract_value` used to hold.
Nothing is lost; it is just under a name that says which of the two it is.

IDEMPOTENT. strike x quantity is deterministic, so a second run writes the same values.

Run:  docker exec -e PYTHONPATH=/app/backend <container> python /tmp/backfill.py          (dry run)
      docker exec -e PYTHONPATH=/app/backend <container> python /tmp/backfill.py --apply
"""

import asyncio
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from bson import json_util  # noqa: E402
from pymongo import UpdateOne  # noqa: E402

from app.core.db import (  # noqa: E402
    commodity_pos_orders_collection as ORD,
    commodity_pos_positions_collection as POS,
)

APPLY = "--apply" in sys.argv
BACKUP_DIR = os.getenv("BACKFILL_BACKUP_DIR", "/app/data/backups")


def strike_of(doc) -> float | None:
    return (doc.get("instrument") or {}).get("strike")


def is_option(doc) -> bool:
    return (doc.get("instrument_kind") or "").upper() == "OPTION"


async def backup(docs_by_coll: dict) -> str:
    """Dump every row this script may touch, and read it back before anything changes.

    A dump nobody verified is not a backup. This project lost months of record to a reset
    that kept none."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = f"{BACKUP_DIR}/commodity_notional_pre_backfill_{stamp}.jsonl.gz"
    written = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for name, docs in docs_by_coll.items():
            for d in docs:
                fh.write(json.dumps({"_collection": name, "doc": d},
                                    default=json_util.default) + "\n")
                written += 1
    check = 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            json.loads(line)
            check += 1
    print(f"  backup   : {path}")
    print(f"  rows     : {written:,} dumped, {check:,} re-read and parsed"
          f"  {'OK' if check == written else '*** MISMATCH ***'}")
    if check != written:
        raise SystemExit("backup did not verify — nothing was changed")
    return path


async def main() -> None:
    print("=" * 76)
    print("DRY RUN — nothing will be written" if not APPLY else "APPLYING")
    print("=" * 76)

    orders = [d async for d in ORD.find({})]
    positions = [d async for d in POS.find({})]
    await backup({"commodity_pos_orders": orders, "commodity_pos_positions": positions})

    # Orders by the position they belong to, for rebuilding closed sizes.
    by_pos = defaultdict(list)
    for o in orders:
        if o.get("position_id"):
            by_pos[o["position_id"]].append(o)

    order_ops, pos_ops = [], []
    skipped: list[str] = []
    totals = {"orders_before": 0.0, "orders_after": 0.0,
              "open_before": 0.0, "open_after": 0.0,
              "closed_before": 0.0, "closed_after": 0.0}

    # ---- orders -----------------------------------------------------------------
    for o in orders:
        if not is_option(o):
            continue                     # a future's price IS the underlying
        k, qty = strike_of(o), o.get("quantity") or 0
        if not k or not qty:
            skipped.append(f"order {o.get('order_id')} {o.get('display_name')} — no strike/qty")
            continue
        before = o.get("contract_value") or 0.0
        after = round(k * qty, 2)
        price = o.get("fill_price") or o.get("limit_price") or 0.0
        totals["orders_before"] += before
        totals["orders_after"] += after
        order_ops.append(UpdateOne({"_id": o["_id"]}, {"$set": {
            "contract_value": after, "premium_value": round(price * qty, 2)}}))

    # ---- positions ---------------------------------------------------------------
    for p in positions:
        if not is_option(p):
            continue
        k = strike_of(p)
        if not k:
            skipped.append(f"position {p.get('position_id')} {p.get('display_name')} — no strike")
            continue
        open_row = p.get("status") == "OPEN"
        qty = p.get("quantity") or 0

        if not open_row and not qty:
            # Fully closed: rebuild the size from its own fills.
            ords = by_pos.get(p.get("position_id")) or []
            qty = sum(o.get("quantity") or 0 for o in ords
                      if o.get("transaction_type") == p.get("side"))
            if not qty:
                # One row (SILVERM 228000CE) had only its CLOSING fill carrying the
                # position_id — the opening one lost it. A fully closed position was
                # closed by exactly the quantity it held, so the closing side is an
                # equally good measure of its size, and the only one left here.
                qty = sum(o.get("quantity") or 0 for o in ords
                          if o.get("transaction_type") != p.get("side"))
            if not qty:
                skipped.append(
                    f"position {p.get('position_id')} {p.get('display_name')} — "
                    "closed and no fills of either side on file, left untouched")
                continue

        before = p.get("contract_value") or 0.0
        after = round(k * qty, 2)
        price = p.get("ltp") or p.get("entry_price") or 0.0
        bucket = "open" if open_row else "closed"
        totals[f"{bucket}_before"] += before
        totals[f"{bucket}_after"] += after

        update = {"contract_value": after, "premium_value": round(price * qty, 2)}
        if not open_row:
            # Say where the number came from: the row's own quantity is zero, so anyone
            # recomputing strike x quantity from it would get zero and think this wrong.
            update["contract_value_basis"] = (
                f"notional at the {qty:,}-unit size this position held, rebuilt from its "
                "fills; the row's own quantity is zero because it is closed")
        pos_ops.append(UpdateOne({"_id": p["_id"]}, {"$set": update}))

    # ---- report -------------------------------------------------------------------
    def line(label, before, after, n):
        mult = f"{after / before:,.1f}x" if before else "-"
        print(f"  {label:<20} {n:>5} rows   Rs {before:>16,.0f} -> Rs {after:>16,.0f}   {mult}")

    print()
    line("orders", totals["orders_before"], totals["orders_after"], len(order_ops))
    n_open = sum(1 for _ in [p for p in positions if is_option(p) and p.get("status") == "OPEN"])
    line("open positions", totals["open_before"], totals["open_after"], n_open)
    line("closed positions", totals["closed_before"], totals["closed_after"],
         len(pos_ops) - n_open)
    print(f"\n  skipped: {len(skipped)}")
    for s in skipped[:10]:
        print(f"      {s}")

    if not APPLY:
        print("\n  re-run with --apply to write")
        return

    for ops, coll, name in ((order_ops, ORD, "orders"), (pos_ops, POS, "positions")):
        for i in range(0, len(ops), 200):
            chunk = ops[i:i + 200]
            if chunk:
                await coll.bulk_write(chunk, ordered=False)
        print(f"  wrote {len(ops):,} {name}")


asyncio.run(main())
