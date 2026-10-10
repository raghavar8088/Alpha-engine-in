"""Replace the real-money ledger's ESTIMATES with Angel's own record of what happened.

Some real trades can only be priced from Angel's records, never from its API: the API's
trade book holds the current session only. On this desk that is every trade whose fill was
not captured the same day — above all the 49 positions Angel squared off on 18-19 Aug 2026,
which `backfill_live_trading_ledger.py` re-priced at that day's NSE close as an ESTIMATE
(`reconcile_status: needs_contract_note`).

THREE COMMANDS (run inside the backend image)

  export                 write the trades that need a broker price to a CSV template:
                         /app/data/live_trading_needs_contract_note.csv

  apply <template.csv>   after filling actual_entry_price / actual_exit_price (and,
                         optionally, actual_charges from the contract note) for any rows
                         you have, write them. Blank cells are left as they are.

  tradebook <export.csv> import Angel's own trade-history download (Angel One web ->
                         Reports -> Trade history, the date range 10-20 Aug 2026, as CSV).
                         Columns are recognised by name; the mapping is printed and the run
                         stops if any is ambiguous. Entries and desk exits match by ORDER ID.
                         A broker square-off has an order id this desk never sent, so it is
                         matched by (trade date, symbol, the closing side) instead, and only
                         when that leaves exactly one candidate quantity.

Every write is preceded by a verified gzip backup, and each corrected row keeps
`reported_exit_price` / `reported_realized_pnl` from the original record. Add --apply to
write; without it every command except `export` is a dry run.
"""

import asyncio
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from bson import json_util  # noqa: E402

import app.services.live_trading_engine as LT  # noqa: E402
from app.core.db import (  # noqa: E402
    live_trading_positions_collection as POS,
    live_trading_trades_collection as TRD,
)

APPLY = "--apply" in sys.argv
OUT = os.getenv("CONTRACT_NOTE_CSV", "/app/data/live_trading_needs_contract_note.csv")
BACKUP_DIR = os.getenv("BACKFILL_BACKUP_DIR", "/app/data/backups")
COLS = ["position_id", "trade_date", "symbol", "side", "qty", "entry_order_id", "exit_order_id",
        "ledger_entry_price", "ledger_exit_price", "exit_basis",
        "actual_entry_price", "actual_exit_price", "actual_charges"]


async def _backup() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = f"{BACKUP_DIR}/live_trading_pre_contract_notes_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl.gz"
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for name, coll in (("live_trading_positions", POS), ("live_trading_trades", TRD)):
            async for d in coll.find({}):
                fh.write(json.dumps({"_collection": name, "doc": d}, default=json_util.default) + "\n")
                n += 1
    back = sum(1 for _ in gzip.open(path, "rt", encoding="utf-8"))
    if back != n:
        raise SystemExit("backup did not verify — nothing changed")
    print(f"  backup {path} ({n} rows, verified)")


async def _write(p: dict, entry: float | None, exit_: float | None, charges: float | None,
                 basis: str) -> dict:
    entry = entry or p["entry_price"]
    exit_ = exit_ or p["exit_price"]
    money = LT._charge(entry, exit_, p["qty"], p["side"])
    if charges is not None:
        money["fees"] = round(charges, 2)
        money["realized_pnl"] = round(money["gross_pnl"] - charges, 2)
        money["charges_basis"] = "contract_note"
    upd = {"entry_price": round(entry, 2), "exit_price": round(exit_, 2), **money,
           "reported_exit_price": p.get("reported_exit_price", p.get("exit_price")),
           "reported_realized_pnl": p.get("reported_realized_pnl", p.get("realized_pnl")),
           "reconcile_status": "contract_note", "exit_basis": basis,
           "reconciled_at": datetime.now(timezone.utc)}
    if APPLY:
        await POS.update_one({"_id": p["_id"]}, {"$set": upd})
        if p.get("entry_order_id"):
            await TRD.update_one({"entry_order_id": p["entry_order_id"], "strategy_id": p["strategy_id"]},
                                 {"$set": {k: upd[k] for k in ("entry_price", "exit_price", "gross_pnl",
                                                               "fees", "realized_pnl", "charges_basis",
                                                               "exit_basis")}})
    return upd


async def export() -> None:
    rows = [p async for p in POS.find({"status": "CLOSED", "reconcile_status": {"$ne": "reconciled"}})]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for p in sorted(rows, key=lambda r: (r.get("opened_on") or "", r["symbol"])):
            w.writerow({"position_id": p.get("position_id"), "trade_date": p.get("opened_on"),
                        "symbol": p["symbol"], "side": p["side"], "qty": p["qty"],
                        "entry_order_id": p.get("entry_order_id"), "exit_order_id": p.get("exit_order_id"),
                        "ledger_entry_price": p.get("entry_price"), "ledger_exit_price": p.get("exit_price"),
                        "exit_basis": p.get("exit_basis") or "", "actual_entry_price": "",
                        "actual_exit_price": "", "actual_charges": ""})
    print(f"  {len(rows)} trades need Angel's record -> {OUT}")


def _num(v):
    try:
        return float(str(v).replace(",", "").strip()) if str(v).strip() else None
    except ValueError:
        return None


async def apply_template(path: str) -> None:
    by_id = {p.get("position_id"): p async for p in POS.find({"status": "CLOSED"})}
    todo = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            p = by_id.get(r.get("position_id"))
            if not p:
                print(f"  skip {r.get('position_id')}: no such closed position")
                continue
            e, x, c = _num(r.get("actual_entry_price")), _num(r.get("actual_exit_price")), _num(r.get("actual_charges"))
            if e is None and x is None and c is None:
                continue
            if str(p["qty"]) != str(r.get("qty")).split(".")[0]:
                print(f"  skip {r.get('position_id')}: quantity {r.get('qty')} != ledger {p['qty']}")
                continue
            todo.append((p, e, x, c))
    if APPLY and todo:
        await _backup()
    for p, e, x, c in todo:
        u = await _write(p, e, x, c, "Angel contract note")
        print(f"  {p.get('opened_on')} {p['symbol']:<10} {p['side']:<4} x{p['qty']:<4} "
              f"{p.get('realized_pnl') or 0:>9.2f} -> {u['realized_pnl']:>9.2f}")
    print(f"  {len(todo)} row(s) {'written' if APPLY else 'would be written (dry run)'}")


# ── Angel's trade-history export ─────────────────────────────────────────────────

WANT = {
    "order": ("order id", "order no", "orderid", "order number", "order"),
    "symbol": ("symbol", "scrip", "tradingsymbol", "security", "instrument"),
    "side": ("buy/sell", "transaction type", "trade type", "side", "b/s", "type"),
    "qty": ("qty", "quantity", "trade qty", "traded qty", "filled qty"),
    "price": ("trade price", "price", "rate", "avg price", "traded price"),
    "date": ("trade date", "date", "trade time", "time"),
}


def _map_columns(header: list[str]) -> dict[str, str]:
    norm = {h: h.strip().lower() for h in header}
    out = {}
    for key, names in WANT.items():
        hits = [h for h, n in norm.items() if any(n == x for x in names)] or \
               [h for h, n in norm.items() if any(x in n for x in names)]
        if len(hits) != 1:
            raise SystemExit(f"column for '{key}' is {'missing' if not hits else 'ambiguous: ' + str(hits)}"
                             f" — header was {header}")
        out[key] = hits[0]
    return out


def _date(v: str) -> str | None:
    """A trade date or timestamp in any of the layouts Angel's exports use."""
    v = (v or "").strip()
    fmts = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y")
    for text in (v, v.split(" ")[0], v.split("T")[0]):
        for fmt in fmts + tuple(f + " %H:%M:%S" for f in fmts):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
    return None


async def import_tradebook(path: str) -> None:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = _map_columns(reader.fieldnames or [])
        print("  columns:", {k: v for k, v in cols.items()})
        fills = []
        for r in reader:
            side = (r[cols["side"]] or "").strip().upper()
            side = "BUY" if side.startswith("B") else "SELL" if side.startswith("S") else None
            q, px = _num(r[cols["qty"]]), _num(r[cols["price"]])
            sym = (r[cols["symbol"]] or "").strip().upper().replace("-EQ", "")
            if side and q and px:
                fills.append({"order": str(r[cols["order"]]).strip(), "symbol": sym, "side": side,
                              "qty": q, "price": px, "date": _date(r[cols["date"]])})
    print(f"  {len(fills)} fills read")
    by_order = defaultdict(list)
    for f in fills:
        by_order[f["order"]].append(f)

    def vwap(fs):
        q = sum(f["qty"] for f in fs)
        return (sum(f["price"] * f["qty"] for f in fs) / q, q) if q else (None, 0)

    rows = [p async for p in POS.find({"status": "CLOSED", "reconcile_status": {"$ne": "reconciled"}})]
    ours = {str(p.get(k)) for p in [x async for x in POS.find({})] for k in ("entry_order_id", "exit_order_id")
            if p.get(k)}
    todo = []
    for p in rows:
        e = x = None
        if p.get("entry_order_id") in by_order:
            e, _ = vwap(by_order[p["entry_order_id"]])
        if p.get("exit_order_id") and p["exit_order_id"] in by_order:
            x, _ = vwap(by_order[p["exit_order_id"]])
        elif not p.get("exit_order_id"):
            close_side = "SELL" if p["side"] == "BUY" else "BUY"
            cands = [f for f in fills if f["symbol"] == p["symbol"] and f["side"] == close_side
                     and f["date"] == p.get("opened_on") and f["order"] not in ours]
            px, q = vwap(cands)
            # Only when the broker's unattributed closing quantity is exactly what the ledger
            # held in that symbol that day — otherwise another trade is mixed in.
            held = sum(r["qty"] for r in rows if r["symbol"] == p["symbol"] and r.get("opened_on") == p.get("opened_on")
                       and r["side"] == p["side"] and not r.get("exit_order_id"))
            if px and int(round(q)) == int(held):
                x = px
            elif cands:
                print(f"  ambiguous square-off for {p['symbol']} {p.get('opened_on')}: broker {q}, ledger {held} — left")
        if e or x:
            todo.append((p, e, x))
    if APPLY and todo:
        await _backup()
    for p, e, x in todo:
        u = await _write(p, e, x, None, "Angel trade history" + ("" if x else " (entry only)"))
        print(f"  {p.get('opened_on')} {p['symbol']:<10} {p['side']:<4} x{p['qty']:<4} "
              f"{p.get('realized_pnl') or 0:>9.2f} -> {u['realized_pnl']:>9.2f}")
    print(f"  {len(todo)} of {len(rows)} matched; {'written' if APPLY else 'dry run'}")
    if APPLY:
        for sid in {p["strategy_id"] for p, *_ in todo}:
            await LT._update_score(sid)


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        await export()
    elif cmd == "apply" and len(sys.argv) > 2:
        await apply_template(sys.argv[2])
    elif cmd == "tradebook" and len(sys.argv) > 2:
        await import_tradebook(sys.argv[2])
    else:
        print(__doc__)


asyncio.run(main())
