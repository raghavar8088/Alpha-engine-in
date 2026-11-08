"""The paper ledger. Two layers:

  premium_trades    what each strategy did, per unit, exactly as the study's engine says (entry, exit, net of costs).
                    A trade is `sealed` once its bars are final and is never rewritten after that.
  premium_accounts  what that means for a Rs 10 lakh account: a pure function of the trades above, recomputed from the
                    first trade every cycle, so it cannot drift.

Sizing: 1% of current equity at risk per trade (0.25% with a 25% notional cap in the NSE stock pools, as the VWAP study
scaled to Rs 10 lakh; 1% with a 10% cap in the daily stock pools), rounded down to whole lots or the market's smallest size, and
never more than the free margin allows. A lot-sized market still takes one lot if that risks at most 5% of equity.
Dollar markets convert at the USD/INR rate of the entry date.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

from catalog import ACCOUNTS, BY_ID, LABEL, MONEY, ONE_LOT_MAX_RISK
from settings import BTC_START_T, CAPITAL, IST, MONGO_DB, MONGO_URL, PAPER_START

log = logging.getLogger("premium.ledger")


def database():
    if not MONGO_URL:
        raise RuntimeError("FACTORY_MONGO_URL is not set: the paper desk never writes to the main database")
    return MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000, maxPoolSize=2)[MONGO_DB]


def ensure_indexes(db) -> None:
    try:
        db.premium_trades.create_index([("acct", 1), ("entry_t", -1)], name="acct_entry")
        db.premium_trades.create_index([("book", 1), ("sealed", 1)], name="book_sealed")
    except Exception:  # noqa: BLE001 - an index is a speed-up, never a precondition
        log.warning("index creation skipped", exc_info=True)


# ── per-book state and trades ────────────────────────────────────────────────────────

def sealed_through(db, acct: str, market: str) -> str | None:
    d = db.premium_books.find_one({"_id": f"{acct}|{market}"}, {"sealed_through": 1})
    return d.get("sealed_through") if d else None


def persist(db, acct: str, market: str, docs: list[dict], replay_from: str, final_day: str, overnight: bool) -> int:
    """Replace the book's unsealed trades with this replay's, and seal whatever has become final."""
    key = f"{acct}|{market}"
    T = db.premium_trades
    sealed_ids = {d["_id"] for d in T.find({"book": key, "sealed": True}, {"_id": 1})}
    T.delete_many({"book": key, "sealed": False})
    new = []
    for d in docs:
        if d["_id"] in sealed_ids:
            continue
        d["sealed"] = (not d["open"]) and d["exit_date"] <= final_day
        new.append(d)
    if new:
        T.insert_many(new, ordered=False)
    if not overnight and final_day >= replay_from:
        db.premium_books.update_one({"_id": key}, {"$set": {"sealed_through": final_day}}, upsert=True)
    return len(new)


# ── the money ────────────────────────────────────────────────────────────────────────

def vwap_net(side: int, qty: float, entry: float, exit_: float, s: float) -> float:
    """The VWAP study's trade_pnl (lib_bt.py): real NSE intraday charges plus tiered slippage, in rupees."""
    long = side > 0
    buy = (entry if long else exit_) * (1 + s)
    sell = (exit_ if long else entry) * (1 - s)
    bv, sv = qty * buy, qty * sell
    brok = min(20.0, 0.0003 * bv) + min(20.0, 0.0003 * sv)
    stt = 0.00025 * sv
    exch = 0.0000297 * (bv + sv)
    sebi = 1e-6 * (bv + sv)
    stamp = 3e-5 * bv
    gst = 0.18 * (brok + exch + sebi)
    return (sv - bv) - (brok + stt + exch + sebi + stamp + gst)


def _size(d: dict, cash: float, used_margin: float, rate: float) -> tuple[float, float, str | None]:
    """(quantity, margin, why skipped)."""
    cfg = MONEY[d["mkt"]]
    if cash <= 0:
        return 0.0, 0.0, "account empty"
    entry, unit = d["entry"] * rate, (d.get("unit") or 0.0) * rate
    if entry <= 0 or unit <= 0:
        return 0.0, 0.0, "no risk unit"
    free = max(cash - used_margin, 0.0)
    if cfg.fixed_inr:                     # accumulation: a fixed amount a buy, while the cash lasts
        q = math.floor(min(cfg.fixed_inr, free) / entry / cfg.step + 1e-9) * cfg.step
        if q <= 0:
            return 0.0, 0.0, "no cash left"
        return q, q * entry * cfg.margin, None
    budget = cfg.risk_pct * cash
    if cfg.lot:
        per_lot = unit * cfg.lot
        lots = int(budget // per_lot)
        if lots == 0 and per_lot <= ONE_LOT_MAX_RISK * cash:
            lots = 1
        lots = min(lots, int(free // (cfg.margin * entry * cfg.lot)))
        if lots <= 0:
            return 0.0, 0.0, "below one lot"
        q = float(lots * cfg.lot)
    else:
        q = budget / unit
        if cfg.notional_cap:
            q = min(q, cfg.notional_cap * cash / entry)
        if d.get("vol_cap") is not None:
            q = min(q, d["vol_cap"])
        q = min(q, free / (cfg.margin * entry))
        q = math.floor(q / cfg.step + 1e-9) * cfg.step
        if q <= 0:
            return 0.0, 0.0, "below minimum size"
    return q, q * entry * cfg.margin, None


def _pnl(d: dict, qty: float, rate: float) -> float:
    if d.get("vwap_costs"):
        return vwap_net(d["side"], qty, d["entry"], d["exit"], d["slip"])
    return qty * (d.get("r_net") or 0.0) * (d.get("unit") or 0.0) * rate


def _rate(rates: dict, date: str, fallback: float) -> float:
    if date in rates:
        return rates[date]
    earlier = [k for k in rates if k <= date]
    return rates[max(earlier)] if earlier else fallback


def walk(trades: list[dict], rates: dict, today: str) -> dict:
    """Replay the account from Rs 10 lakh. Returns the summary and the per-trade money fields."""
    fallback = (rates[max(rates)] if rates else 94.0)
    tr = sorted(trades, key=lambda d: (d["entry_t"], d.get("rank") if d.get("rank") is not None else 1e9, d["_id"]))
    cash = CAPITAL
    live: list[dict] = []
    by_day: dict[str, float] = {}
    by_market: dict[str, dict] = {}
    fields: dict[str, dict] = {}
    n_closed = wins = 0
    gross_win = gross_loss = 0.0
    skipped: dict[str, int] = {}
    today_pnl = 0.0

    def realise(p):
        nonlocal cash, n_closed, wins, gross_win, gross_loss, today_pnl
        cash += p["pnl"]
        by_day[p["exit_date"]] = by_day.get(p["exit_date"], 0.0) + p["pnl"]
        n_closed += 1
        wins += p["pnl"] > 0
        gross_win += max(p["pnl"], 0.0)
        gross_loss += max(-p["pnl"], 0.0)
        if p["exit_date"] == today:
            today_pnl += p["pnl"]

    for d in tr:
        keep = []
        for p in live:
            if p["exit_t"] is not None and p["exit_t"] <= d["entry_t"]:
                realise(p)
            else:
                keep.append(p)
        live = keep
        cfg = MONEY[d["mkt"]]
        rate = _rate(rates, d["date"], fallback) if cfg.ccy == "USD" else 1.0
        q, margin, why = _size(d, cash, sum(p["margin"] for p in live), rate)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            fields[d["_id"]] = {"qty": 0, "pnl": 0.0, "skip": why, "rate": rate}
            continue
        pnl = round(_pnl(d, q, rate), 2)
        fields[d["_id"]] = {"qty": q, "pnl": pnl, "skip": None, "rate": rate}
        bm = by_market.setdefault(d["mkt"], {"market": LABEL.get(d["mkt"], d["mkt"]), "trades": 0, "pnl": 0.0})
        bm["trades"] += 1
        bm["pnl"] = round(bm["pnl"] + pnl, 2)
        live.append({**d, "pnl": pnl, "qty": q, "margin": margin, "rate": rate})

    unrealised, positions = 0.0, []
    for p in sorted(live, key=lambda x: x["entry_t"]):
        if p["exit_t"] is None:
            unrealised += p["pnl"]
            positions.append({"sym": p["sym"], "mkt": LABEL.get(p["mkt"], p["mkt"]), "side": p["side"], "qty": p["qty"], "entry": p["entry"],
                              "stop": p["stop"], "target": p["target"], "last": p["last"], "pnl": p["pnl"], "entry_t": p["entry_t"],
                              "setup": p["setup"], "ccy": MONEY[p["mkt"]].ccy})
        else:
            realise(p)
    equity = cash + unrealised
    curve, peak, dd, eq = [], CAPITAL, 0.0, CAPITAL
    for day in sorted(by_day):
        eq += by_day[day]
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak if peak > 0 else 0.0)
        curve.append([day, round(eq, 2)])
    return {
        "summary": {
            "capital": CAPITAL, "equity": round(equity, 2), "realised": round(cash - CAPITAL, 2), "unrealised": round(unrealised, 2),
            "return_pct": round(100 * (equity / CAPITAL - 1), 3), "closed": n_closed, "open": len(positions), "wins": wins,
            "win_rate": round(100 * wins / n_closed, 1) if n_closed else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
            "max_dd_pct": round(100 * dd, 2), "today_pnl": round(today_pnl + unrealised, 2), "skipped": skipped,
            "by_market": sorted(by_market.values(), key=lambda x: -x["trades"]), "last_trade_t": tr[-1]["entry_t"] if tr else None,
        },
        "positions": positions, "curve": curve, "fields": fields,
    }


def update_accounts(db, ids: list[str] | None = None) -> None:
    rates = (db.premium_meta.find_one({"_id": "fx"}) or {}).get("rates") or {}
    today = datetime.now(IST).date().isoformat()
    T = db.premium_trades
    stamp = datetime.now(timezone.utc)
    for a in ([BY_ID[i] for i in ids] if ids else ACCOUNTS):
        trades = list(T.find({"acct": a.id}))
        res = walk(trades, rates, today)
        ops = []
        for d in trades:
            f = res["fields"][d["_id"]]
            if any(d.get(k) != f[k] for k in f):
                ops.append(UpdateOne({"_id": d["_id"]}, {"$set": f}))
        if ops:
            T.bulk_write(ops, ordered=False)
        doc = {"source": a.source, "name": a.name, "channel": a.channel,
               "markets": [LABEL.get(m, m) for m, _ in a.books], "variants": [v for _, v in a.books], **res["summary"],
               "positions": res["positions"], "curve": res["curve"], "updated_at": stamp}
        db.premium_accounts.replace_one({"_id": a.id}, doc, upsert=True)


def note_cycle(db, group: str, ok: bool, seconds: float, info: dict, error: str | None = None) -> None:
    s = {"at": datetime.now(timezone.utc), "ok": ok, "seconds": round(seconds, 1), "info": info, "error": error}
    db.premium_meta.update_one({"_id": "status"}, {"$set": {f"groups.{group}": s, "paper_start": PAPER_START.isoformat(), "capital": CAPITAL,
                                                            "btc_start": datetime.fromtimestamp(BTC_START_T, timezone.utc).isoformat()}},
                               upsert=True)


def signature(db, group: str) -> str | None:
    return (db.premium_meta.find_one({"_id": f"sig_{group}"}) or {}).get("sig")


def set_signature(db, group: str, sig: str) -> None:
    db.premium_meta.update_one({"_id": f"sig_{group}"}, {"$set": {"sig": sig, "t": time.time()}}, upsert=True)
