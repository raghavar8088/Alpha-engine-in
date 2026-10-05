"""Honest records for the Commodity Trading pattern desk (C1).

WHAT CHANGED AND WHY
--------------------
The desk used to rank its strategies and promote the top ones as READY (30 trades, t >= 1.5,
profit factor > 1.2 ...). Measured on its own record (2026-08-17..10-02, 37,053 trades):
  * 91% of trades were filled at the SIGNAL BAR's price, not at a price the market offered
    when the order went in. Those fills flattered 5m and 30m by 13 and 49 bp a trade;
  * strategy rankings did not persist from the first half of the record to the second
    (Spearman -0.035), and 11 of the 16 READY strategies lost money afterwards;
  * with ~350 strategies, about 2.3% of them clear t > 2 by luck alone — the board's
    winners were the expected crop of lucky ones.
So the desk no longer selects anything. It keeps a RECORD per strategy, labelled trade by
trade, and the only door to real money is the Commodity Lab (pre-registered, deflated,
out-of-sample — see commodity_lab).

THE LABELS (on every position document)
--------------------------------------
fill_basis      "market_quote" (filled at a live quote) | "stale_signal_bar" (filled at
                the signal bar's own price +- slippage — the pre-2026-09-25 behaviour)
entry_session / exit_session   "morning" | "evening" | None (MCX was shut)
contract_ok     False when the position was closed at ANOTHER contract's price (held past
                its contract's expiry and marked on the next month)
repriced        for those: the same trade closed at its OWN contract's last recorded price
void            True when the record cannot stand: entered or exited while MCX was shut
                (2026-10-02, morning sessions of morning-only holidays), or a wrong-contract
                close that could not be repriced. Void trades are NOT deleted — they are
                kept, labelled, and left out of every statistic.
honest          not void AND filled at a market quote — the only trades headline numbers use
record_pnl      realised P&L to use (the repriced one where a reprice exists)
net_bp, raw_bp  per trade, against the entry notional; raw_bp adds the desk's own slippage
                back, so it is the price move the signal caught before any cost
"""

from __future__ import annotations

import logging
import math
import os
import time as _time
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne
from tradingai_shared import mcx_calendar as mcal

from app.core.db import commodity_positions_collection, commodity_state_collection

logger = logging.getLogger("commodity_records")

LABELS_VERSION = 1
SLIP_BP = float(os.getenv("COMMODITY_SLIPPAGE_BPS", "5"))
FIX_STALE_FILLS_ON = "2026-09-25"     # the market-fill fix went live that day
MIN_TRADES_FOR_T = 20
IST = mcal.IST


def _aware(ts):
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def fill_basis_of(p: dict) -> str:
    if p.get("fill_basis"):
        return p["fill_basis"]
    sig, entry = p.get("signal_price") or 0.0, p.get("entry_price") or 0.0
    if sig > 0 and entry > 0 and abs(abs(entry / sig - 1.0) - SLIP_BP / 1e4) < 1e-5:
        return "stale_signal_bar"
    return "market_quote"


def _bp(x: float | None, notional: float) -> float | None:
    return x / notional * 1e4 if (x is not None and notional) else None


def label(p: dict, repriced: dict | None = None) -> dict:
    """Pure: the label fields for one position document (closed or open)."""
    opened, closed = _aware(p.get("opened_at")), _aware(p.get("closed_at"))
    entry_session = mcal.session_at(opened) if opened else None
    settled = (p.get("exit_basis") or "market_quote") != "market_quote"
    exit_session = mcal.session_at(closed) if (closed and not settled) else None
    exp = (p.get("instrument") or {}).get("expiry")
    contract_ok = True
    if closed is not None and exp and p.get("exit_basis") is None:
        # Only the old loop could close at another contract's price; every close since C0
        # carries `exit_basis` and is on its own contract by construction.
        contract_ok = closed.astimezone(IST).date().isoformat() <= exp
    basis = fill_basis_of(p)
    reasons = []
    if opened is not None and entry_session is None:
        reasons.append("entered_while_mcx_closed")
    if closed is not None and not settled and exit_session is None:
        reasons.append("exited_while_mcx_closed")
    if not contract_ok and not repriced:
        reasons.append("priced_on_next_contract_unrecoverable")
    notional = (p.get("entry_price") or 0.0) * (p.get("qty") or 0.0)
    pnl = (repriced or {}).get("realized_pnl", p.get("realized_pnl"))
    gross = (repriced or {}).get("gross_pnl", p.get("gross_pnl"))
    exit_slip = 0.0 if settled else SLIP_BP
    raw = _bp(gross, notional)
    out = {
        "fill_basis": basis, "entry_session": entry_session, "exit_session": exit_session,
        "contract_ok": contract_ok, "repriced": repriced, "void": bool(reasons), "void_reasons": reasons,
        "labels_v": LABELS_VERSION,
    }
    if closed is not None:
        out.update({
            "honest": (not reasons) and basis == "market_quote",
            "record_pnl": round(pnl, 2) if pnl is not None else None,
            "net_bp": round(_bp(pnl, notional), 3) if pnl is not None and notional else None,
            "raw_bp": round(raw + SLIP_BP + exit_slip, 3) if raw is not None else None,
            "real_bp": (p.get("real") or {}).get("net_bp"),
        })
    return out


async def _reprice(p: dict, cache: dict) -> dict | None:
    """The same trade closed at its OWN contract's last recorded price (with the desk's
    exit slippage and real charges) — for a position the old loop closed on the next month."""
    from app.services.commodity_bars import last_contract_price
    from app.services.commodity_engine import order_charges

    inst = p.get("instrument") or {}
    exp = inst.get("expiry")
    if not exp:
        return None
    key = (p["symbol"], exp)
    if key not in cache:
        end = datetime.fromisoformat(exp).replace(tzinfo=IST) + timedelta(days=1)
        cache[key] = await last_contract_price(p["symbol"], exp, on_or_before=end)
    got = cache[key]
    if not got:
        return None
    px, ts = got
    is_long = p["side"] == "BUY"
    fill = px * (1 - SLIP_BP / 1e4) if is_long else px * (1 + SLIP_BP / 1e4)
    qty = p["qty"]
    gross = (fill - p["entry_price"]) * qty * (1 if is_long else -1)
    costs = (p.get("entry_costs") or 0.0) + order_charges(fill, qty, not is_long)
    return {"exit_price": round(fill, 4), "gross_pnl": round(gross, 2), "costs": round(costs, 2),
            "realized_pnl": round(gross - costs, 2), "basis": "contract_last_bar",
            "price_ts": ts.isoformat(), "contract_price": px}


async def relabel(force: bool = False) -> dict:
    """Label every position document. Idempotent; runs once per LABELS_VERSION unless forced.
    Never deletes or changes a P&L field — labels are added beside them."""
    st = await commodity_state_collection.find_one({"_id": "labels"}) or {}
    if st.get("version") == LABELS_VERSION and not force:
        return {k: v for k, v in st.items() if k != "_id"}
    started = _time.monotonic()
    proj = {"opened_at": 1, "closed_at": 1, "signal_price": 1, "entry_price": 1, "exit_price": 1, "qty": 1,
            "side": 1, "symbol": 1, "instrument.expiry": 1, "realized_pnl": 1, "gross_pnl": 1,
            "entry_costs": 1, "fill_basis": 1, "exit_basis": 1, "status": 1, "real": 1}
    cache: dict = {}
    ops, n = [], 0
    counts = {"positions": 0, "void": 0, "honest": 0, "stale_signal_bar": 0, "wrong_contract": 0,
              "repriced": 0, "entered_closed": 0, "exited_closed": 0}
    async for p in commodity_positions_collection.find({}, proj):
        rep = None
        lab = label(p)
        if not lab["contract_ok"] and p.get("status") != "OPEN":
            rep = await _reprice(p, cache)
            lab = label(p, rep)
            counts["wrong_contract"] += 1
            counts["repriced"] += 1 if rep else 0
        counts["positions"] += 1
        counts["void"] += 1 if lab["void"] else 0
        counts["honest"] += 1 if lab.get("honest") else 0
        counts["stale_signal_bar"] += 1 if lab["fill_basis"] == "stale_signal_bar" else 0
        counts["entered_closed"] += 1 if "entered_while_mcx_closed" in lab["void_reasons"] else 0
        counts["exited_closed"] += 1 if "exited_while_mcx_closed" in lab["void_reasons"] else 0
        ops.append(UpdateOne({"_id": p["_id"]}, {"$set": lab}))
        if len(ops) >= 1000:
            await commodity_positions_collection.bulk_write(ops, ordered=False)
            n += len(ops)
            ops = []
    if ops:
        await commodity_positions_collection.bulk_write(ops, ordered=False)
        n += len(ops)
    out = {"version": LABELS_VERSION, "labelled": n, **counts,
           "seconds": round(_time.monotonic() - started, 1), "at": datetime.now(timezone.utc)}
    await commodity_state_collection.update_one({"_id": "labels"}, {"$set": out}, upsert=True)
    _invalidate()
    logger.info("[commodity_records] relabelled %s", out)
    return out


async def label_one(position_id) -> None:
    """Label a single document after it closes (the engine calls this)."""
    p = await commodity_positions_collection.find_one({"_id": position_id})
    if p:
        await commodity_positions_collection.update_one({"_id": position_id}, {"$set": label(p)})


# ── the records ──────────────────────────────────────────────────────────────────

_CACHE: dict | None = None
_CACHE_AT = 0.0
CACHE_TTL = float(os.getenv("COMMODITY_RECORDS_TTL", "300"))


def _invalidate() -> None:
    global _CACHE, _CACHE_AT
    _CACHE, _CACHE_AT = None, 0.0


def _stats(n: int, s: float, ss: float) -> dict:
    mean = s / n if n else 0.0
    var = (ss - n * mean * mean) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(max(var, 0.0))
    se = sd / math.sqrt(n) if n > 1 and sd > 0 else None
    return {"mean": round(mean, 2), "sd": round(sd, 2),
            "t": round(mean / se, 2) if se else None,
            "ci95": [round(mean - 1.96 * se, 2), round(mean + 1.96 * se, 2)] if se else None}


async def _group(match: dict, key) -> list[dict]:
    rows = []
    async for g in commodity_positions_collection.aggregate([
        {"$match": {"status": {"$ne": "OPEN"}, "net_bp": {"$ne": None}, **match}},
        {"$group": {"_id": key, "n": {"$sum": 1},
                    "s": {"$sum": "$net_bp"}, "ss": {"$sum": {"$multiply": ["$net_bp", "$net_bp"]}},
                    "rs": {"$sum": "$raw_bp"}, "rss": {"$sum": {"$multiply": ["$raw_bp", "$raw_bp"]}},
                    "hits": {"$sum": {"$cond": [{"$gt": ["$raw_bp", 0]}, 1, 0]}},
                    "real_n": {"$sum": {"$cond": [{"$ne": [{"$ifNull": ["$real_bp", None]}, None]}, 1, 0]}},
                    "real_s": {"$sum": {"$ifNull": ["$real_bp", 0]}},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$record_pnl", 0]}, 1, 0]}},
                    "pnl": {"$sum": "$record_pnl"}}},
    ], allowDiskUse=True):
        n = g["n"]
        net, raw = _stats(n, g["s"], g["ss"]), _stats(n, g["rs"], g["rss"])
        rows.append({"key": g["_id"], "trades": n, "net_bp": net["mean"], "net_t": net["t"], "net_ci95": net["ci95"],
                     "raw_bp": raw["mean"], "raw_t": raw["t"],
                     "direction_hit": round(g["hits"] / n, 4) if n else None,
                     "win_rate": round(g["wins"] / n, 4) if n else None, "net_pnl": round(g["pnl"] or 0.0, 2),
                     "real_trades": g["real_n"],
                     "real_bp": round(g["real_s"] / g["real_n"], 2) if g["real_n"] else None})
    return rows


def _norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2))


async def records(fresh: bool = False) -> dict:
    """Everything the Research Record tab shows, computed in Mongo and cached."""
    global _CACHE, _CACHE_AT
    now = _time.monotonic()
    if not fresh and _CACHE and now - _CACHE_AT < CACHE_TTL:
        return _CACHE
    from app.services.commodity_patterns import COMMODITY_BY_ID, FAMILY_LABELS
    from app.services.commodity_engine import RETIRED_TIMEFRAMES

    honest = {"honest": True}
    everything = {"void": {"$ne": True}}
    desk_all = await _group({}, None)
    desk_kept = await _group(everything, None)
    desk_honest = await _group(honest, None)
    by_basis = await _group({}, {"basis": "$fill_basis", "void": "$void"})
    by_tf = await _group(honest, "$timeframe")
    by_tf_all = await _group(everything, "$timeframe")
    by_sym = await _group(honest, "$symbol")
    by_family = await _group(honest, "$family")
    per = await _group(honest, "$strategy_id")

    rows = []
    for r in per:
        spec = COMMODITY_BY_ID.get(r["key"])
        if spec is None:
            continue
        rows.append({**r, "strategy_id": r["key"], "name": spec.name, "template": spec.template,
                     "timeframe": spec.timeframe, "family": spec.family,
                     "family_label": FAMILY_LABELS.get(spec.family, spec.family),
                     "retired": spec.timeframe in RETIRED_TIMEFRAMES})
    rows.sort(key=lambda r: (-(r["trades"] >= MIN_TRADES_FOR_T), r["strategy_id"]))

    # THE LUCK LINE. Among strategies with enough honest trades for a t-stat to mean
    # anything, how many would clear |t| > 2 if NONE had an edge? (~2.3% each tail.)
    judged = [r for r in rows if r["trades"] >= MIN_TRADES_FOR_T and r["net_t"] is not None]
    m = len(judged)
    luck = {
        "strategies_judged": m, "min_trades": MIN_TRADES_FOR_T,
        "t_above_2": sum(1 for r in judged if r["net_t"] > 2),
        "t_below_minus_2": sum(1 for r in judged if r["net_t"] < -2),
        "expected_by_chance_each_tail": round(m * _norm_sf(2.0), 1),
        "positive": sum(1 for r in judged if r["net_bp"] > 0),
        "note": ("If no strategy had any edge, about 2.3% of them would still show t > 2 (and as "
                 "many t < -2). Compare the observed counts with that before reading any single row."),
    }
    labels = await commodity_state_collection.find_one({"_id": "labels"}) or {}
    labels.pop("_id", None)
    if isinstance(labels.get("at"), datetime):
        labels["at"] = labels["at"].isoformat()

    def one(x):
        return x[0] if x else None

    out = {
        "desk": {"all": one(desk_all), "not_void": one(desk_kept), "honest": one(desk_honest)},
        "by_fill_basis": by_basis, "by_timeframe": sorted(by_tf, key=lambda r: str(r["key"])),
        "by_timeframe_all": sorted(by_tf_all, key=lambda r: str(r["key"])),
        "by_contract": sorted(by_sym, key=lambda r: str(r["key"])),
        "by_family": by_family, "strategies": rows, "luck": luck, "labels": labels,
        "retired_timeframes": sorted(RETIRED_TIMEFRAMES),
        "definitions": {
            "honest": "Filled at a live market quote, MCX open at entry and exit, on its own contract.",
            "raw_bp": "Price move caught per trade before slippage and charges (signal quality).",
            "net_bp": "Per trade after the desk's slippage and real MCX charges.",
            "direction_hit": "Share of trades where the price moved the signal's way before costs.",
            "real_bp": ("One lot of the trade's own contract, in at the ask / out at the bid the market "
                        "showed at the paper fill, Angel's charges. Recorded from 2026-10-05 on."),
        },
    }
    _CACHE, _CACHE_AT = out, now
    return out
