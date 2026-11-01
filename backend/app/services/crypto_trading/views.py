"""The read side of Crypto Trading: what the page shows. Reads only - stored rows, nothing fetched."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import store
from .config import (
    ACCOUNT_CAPITAL_USD, DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT, MAX_NO_TRADE_BAR_PCT, MIN_GRADE_TO_TRADE, RISK_PCT,
    SESSION_NOTE, TIMEFRAMES, UTC, VENUE,
)
from .engine import LEVERAGE, RESET_PHRASE, STATE_ID, SWITCH, state

STATUSES = ("eligible", "failed_validation", "insufficient_data", "unsupported", "error")
LIBRARY = store.LIBRARY

METHOD = {
    "venue": f"{VENUE} USD perpetuals - long and short, 1x",
    "session": SESSION_NOTE,
    "backtest": ("Next-bar-open fills; stops and targets checked from the entry bar on, the stop first on a bar "
                 "touching both, a bar opening through a level filled at that open; higher-timeframe bars used "
                 "only once closed; a decision only while flat; out-of-sample = the LAST 30% of trades in time."),
    "costs": ("Delta's taker fee + 18% GST on both sides, the coin's slippage (half-spread + $10,000 impact on the "
              "live book, at least 3 bp) on every fill, and funding at every exchange held through, from the "
              "venue's own funding history."),
    "grade": (f"The Strategy Factory's grade on crypto results; grade {MIN_GRADE_TO_TRADE} or better is eligible. "
              "Fewer than 20 trades is insufficient data, not a failure. Eligible is the app's existing bar, not "
              "proof of an edge: thousands of pairs were tested, most eligible ones on 20-60 trades, so some clear "
              "it by chance - the paper record that follows is the real test."),
    "data": (f"A series with more than {MAX_NO_TRADE_BAR_PCT:g}% of bars that have no trade in them (the last trade "
             "carried forward) is insufficient data - its prices were never tradeable."),
    "risk": (f"Each account: one position at a time; the Factory risks {RISK_PCT:.0%} a trade (capped at 1x), the "
             f"Strategies module sizes with its own RiskEngine at 1x; leverage {LEVERAGE:g}x; -{DAILY_LOSS_PCT:.0%} in a "
             f"UTC day stops entries to the next day; equity at {1 - MAX_DRAWDOWN_PCT:.0%} of capital stops them "
             "until a reset."),
    "live": ("Signals on bars that have just closed; fills by walking the venue's L2 book, never better than "
             "mid +/- slippage; stops and targets watched on 1-minute bars; marks at the venue's mark price."),
}


def _clean(d: dict | None) -> dict | None:
    if d is None:
        return None
    out = {}
    for k, v in d.items():
        if isinstance(v, datetime):
            out[k] = (v if v.tzinfo else v.replace(tzinfo=UTC)).isoformat()
        elif isinstance(v, dict):
            out[k] = _clean(v)
        elif isinstance(v, list):
            out[k] = [_clean(x) if isinstance(x, dict) else
                      ((x if x.tzinfo else x.replace(tzinfo=UTC)).isoformat() if isinstance(x, datetime) else x) for x in v]
        else:
            out[k] = v
    return out


async def overview() -> dict:
    from app.services.desk_switches import is_on
    st = await state()
    sweep = await store.STATE.find_one({"_id": "sweep"}) or {}
    uni = await store.UNIVERSE.find_one({"_id": "current"}, {"candidates": 0}) or {}
    by_status: dict[str, dict] = {}
    async for r in store.ACCOUNTS.aggregate([{"$group": {"_id": {"library": "$library", "status": "$status"},
                                                         "n": {"$sum": 1}}}]):
        lib = r["_id"].get("library") or "?"
        by_status.setdefault(lib, {s: 0 for s in STATUSES})[r["_id"].get("status") or "error"] = r["n"]
    grid: dict[str, dict[str, int]] = {}
    async for r in store.ACCOUNTS.aggregate([{"$match": {"eligible": True}},
                                             {"$group": {"_id": {"s": "$symbol", "tf": "$timeframe"}, "n": {"$sum": 1}}}]):
        grid.setdefault(r["_id"]["s"], {tf: 0 for tf in TIMEFRAMES})[r["_id"]["tf"]] = r["n"]
    money = (await store.ACCOUNTS.aggregate([
        {"$match": {"$or": [{"eligible": True}, {"trades": {"$gt": 0}}, {"open_position_id": {"$ne": None}}]}},
        {"$group": {"_id": None, "accounts": {"$sum": 1}, "cash": {"$sum": "$cash"},
                    "unrealized": {"$sum": {"$ifNull": ["$unrealized_pnl", 0]}}, "realized": {"$sum": "$realized_pnl"},
                    "fees": {"$sum": "$fees"}, "funding": {"$sum": "$funding"}, "trades": {"$sum": "$trades"},
                    "wins": {"$sum": "$wins"}, "losses": {"$sum": "$losses"},
                    "halted": {"$sum": {"$cond": [{"$ifNull": ["$halt", False]}, 1, 0]}},
                    "traded": {"$sum": {"$cond": [{"$gt": ["$trades", 0]}, 1, 0]}}}}]).to_list(1) or [{}])[0]
    per_coin: dict[str, dict] = {}
    async for r in store.POSITIONS.aggregate([{"$group": {
            "_id": "$symbol", "open": {"$sum": {"$cond": [{"$eq": ["$status", "OPEN"]}, 1, 0]}},
            "closed": {"$sum": {"$cond": [{"$eq": ["$status", "CLOSED"]}, 1, 0]}},
            "realized": {"$sum": {"$ifNull": ["$net_pnl", 0]}},
            "unrealized": {"$sum": {"$cond": [{"$eq": ["$status", "OPEN"]}, {"$ifNull": ["$unrealized_pnl", 0]}, 0]}}}}]):
        per_coin[r["_id"]] = {k: r[k] for k in ("open", "closed", "realized", "unrealized")}
    curve = [_clean(d) async for d in store.EQUITY.find({"scope": "desk"}, {"_id": 0}).sort("ts", -1).limit(24 * 45)]
    accounts_total = await store.ACCOUNTS.count_documents({})
    return _clean({
        "desk": {"status": st.get("status", "stopped"), "since": st.get("since"), "by": st.get("by"),
                 "last_action": st.get("last_action"), "last_cycle_at": st.get("last_cycle_at"),
                 "last_cycle": st.get("last_cycle"), "last_reset": st.get("last_reset"),
                 "switch_on": await is_on(SWITCH), "reset_phrase": RESET_PHRASE},
        "universe": uni, "sweep": {k: v for k, v in sweep.items() if k != "_id"},
        "accounts": {"total": accounts_total, "capital_each": ACCOUNT_CAPITAL_USD,
                     "by_library": by_status, "eligible_grid": grid},
        "money": {k: v for k, v in money.items() if k != "_id"},
        "open_positions": await store.POSITIONS.count_documents({"status": "OPEN"}),
        "per_coin": per_coin, "equity_curve": list(reversed(curve)), "method": METHOD,
    })


async def universe() -> dict:
    return _clean(await store.UNIVERSE.find_one({"_id": "current"}) or {})


async def library(q: str = "", lib: str | None = None, support: str | None = None, timeframe: str | None = None,
                  offset: int = 0, limit: int = 100) -> dict:
    f: dict = {}
    if lib:
        f["library"] = lib
    if support:
        f["support"] = support
    if timeframe:
        f["timeframe"] = timeframe
    if q:
        rx = re.compile(re.escape(q), re.I)
        f["$or"] = [{"strategy_id": rx}, {"name": rx}, {"family": rx}]
    total = await LIBRARY.count_documents(f)
    rows = [_clean(d) async for d in LIBRARY.find(f).sort([("library", 1), ("strategy_id", 1)]).skip(offset).limit(limit)]
    counts: dict = {}
    async for r in LIBRARY.aggregate([{"$group": {"_id": {"l": "$library", "s": "$support"}, "n": {"$sum": 1}}}]):
        counts.setdefault(r["_id"]["l"], {})[r["_id"]["s"]] = r["n"]
    return {"total": total, "rows": rows, "counts": counts}


_BT_FIELDS = {"pair_id": 1, "strategy_id": 1, "name": 1, "library": 1, "family": 1, "timeframe": 1, "symbol": 1,
              "coin": 1, "status": 1, "status_reason": 1, "grade": 1, "funding_total": 1, "no_trade_bar_pct": 1,
              "span_days": 1, "bars_tested": 1, "slippage_bps": 1,
              **{f"overall.{k}": 1 for k in ("trades", "net_pnl", "profit_factor", "win_rate", "max_drawdown_pct",
                                             "return_pct", "sharpe", "expectancy", "total_costs")},
              **{f"out_of_sample.{k}": 1 for k in ("trades", "net_pnl", "profit_factor")}}
_BT_SORTS = {"grade": [("grade", -1), ("overall.net_pnl", -1)], "net": [("overall.net_pnl", -1)],
             "pf": [("overall.profit_factor", -1)], "trades": [("overall.trades", -1)],
             "oos": [("out_of_sample.net_pnl", -1)], "dd": [("overall.max_drawdown_pct", 1)],
             "sharpe": [("overall.sharpe", -1)]}


def _filters(status=None, symbol=None, timeframe=None, lib=None, min_grade=None, q: str = "") -> dict:
    f: dict = {}
    if status:
        f["status"] = status
    if symbol:
        f["symbol"] = symbol
    if timeframe:
        f["timeframe"] = timeframe
    if lib:
        f["library"] = lib
    if min_grade:
        f["grade"] = {"$gte": int(min_grade)}
    if q:
        rx = re.compile(re.escape(q), re.I)
        f["$or"] = [{"strategy_id": rx}, {"name": rx}, {"family": rx}]
    return f


async def backtests(status=None, symbol=None, timeframe=None, lib=None, min_grade=None, q: str = "",
                    sort: str = "grade", offset: int = 0, limit: int = 100) -> dict:
    f = _filters(status, symbol, timeframe, lib, min_grade, q)
    total = await store.BACKTESTS.count_documents(f)
    cur = store.BACKTESTS.find(f, _BT_FIELDS).sort(_BT_SORTS.get(sort, _BT_SORTS["grade"])).skip(offset).limit(limit)
    return {"total": total, "rows": [_clean(d) async for d in cur]}


async def pair(pid: str) -> dict | None:
    bt = await store.BACKTESTS.find_one({"_id": pid})
    acc = await store.ACCOUNTS.find_one({"_id": pid})
    if bt is None and acc is None:
        return None
    sid = (bt or acc)["strategy_id"]
    lib_row = await LIBRARY.find_one({"strategy_id": sid})
    pos = [_clean(d) async for d in store.POSITIONS.find({"pair_id": pid}).sort("entry_ts", -1).limit(200)]
    return {"backtest": _clean(bt), "account": _clean(acc), "strategy": _clean(lib_row), "positions": pos,
            "equity_curve": _curve(acc, list(reversed(pos)))}


def _curve(acc: dict | None, positions: list[dict]) -> list[list]:
    """The account's equity after each closed trade, then now (with what is open, marked)."""
    eq = ACCOUNT_CAPITAL_USD
    since = (acc or {}).get("reset_at") or (acc or {}).get("created_at")
    if isinstance(since, datetime):
        since = (since if since.tzinfo else since.replace(tzinfo=UTC)).isoformat()
    pts = [[since, eq]] if since else []
    for p in positions:
        if p.get("status") == "CLOSED" and p.get("net_pnl") is not None:
            eq += p["net_pnl"]
            pts.append([p.get("exit_ts"), round(eq, 2)])
    if acc and acc.get("equity") is not None:
        pts.append([datetime.now(UTC).isoformat(), round(float(acc["equity"]), 2)])
    return pts


async def signals(limit: int = 200, symbol: str | None = None, taken: bool | None = None) -> list[dict]:
    f: dict = {}
    if symbol:
        f["symbol"] = symbol
    if taken is True:
        f["outcome"] = {"$in": ["opened", "reversed"]}
    elif taken is False:
        f["outcome"] = {"$regex": "^not taken"}
    return [_clean(d) async for d in store.SIGNALS.find(f, {"_id": 0, "expires": 0}).sort("at", -1).limit(limit)]


async def positions(status: str = "OPEN", symbol: str | None = None, lib: str | None = None,
                    limit: int = 300) -> list[dict]:
    f: dict = {"status": status}
    if symbol:
        f["symbol"] = symbol
    if lib:
        f["library"] = lib
    key = "entry_ts" if status == "OPEN" else "closed_at"
    return [_clean(d) async for d in store.POSITIONS.find(f).sort(key, -1).limit(limit)]


_ACC_FIELDS = {"strategy_id": 1, "name": 1, "library": 1, "family": 1, "timeframe": 1, "symbol": 1, "coin": 1,
               "status": 1, "status_reason": 1, "grade": 1, "eligible": 1, "cash": 1, "equity": 1, "unrealized_pnl": 1,
               "realized_pnl": 1, "fees": 1, "funding": 1, "trades": 1, "wins": 1, "losses": 1, "gross_profit": 1,
               "gross_loss": 1, "max_drawdown_pct": 1, "halt": 1, "open_position_id": 1, "last_trade_at": 1,
               "backtest": 1, "capital": 1}
_ACC_SORTS = {"equity": [("equity", -1), ("realized_pnl", -1)], "realized": [("realized_pnl", -1)],
              "trades": [("trades", -1)], "grade": [("grade", -1), ("backtest.net_pnl", -1)],
              "drawdown": [("max_drawdown_pct", -1)], "costs": [("fees", -1)], "worst": [("equity", 1)]}


async def accounts(status=None, symbol=None, timeframe=None, lib=None, min_grade=None, q: str = "",
                   trading: bool | None = None, traded: bool | None = None, sort: str = "equity",
                   offset: int = 0, limit: int = 100) -> dict:
    f = _filters(status, symbol, timeframe, lib, min_grade, q)
    if trading is not None:
        f["eligible"] = trading
    if traded:
        f["trades"] = {"$gt": 0}
    total = await store.ACCOUNTS.count_documents(f)
    cur = store.ACCOUNTS.find(f, _ACC_FIELDS).sort(_ACC_SORTS.get(sort, _ACC_SORTS["equity"])).skip(offset).limit(limit)
    rows = []
    async for d in cur:
        eq = d.get("equity") if d.get("equity") is not None else d.get("cash")
        d["return_pct"] = round(((eq or ACCOUNT_CAPITAL_USD) / ACCOUNT_CAPITAL_USD - 1) * 100, 3)
        d["win_rate"] = round(d["wins"] / d["trades"], 4) if d.get("trades") else None
        d["profit_factor"] = round(d["gross_profit"] / d["gross_loss"], 3) if d.get("gross_loss") else None
        rows.append(_clean(d))
    return {"total": total, "rows": rows}


async def equity(days: int = 45) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    return [_clean(d) async for d in store.EQUITY.find({"scope": "desk", "ts": {"$gte": since}}, {"_id": 0}).sort("ts", 1)]


__all__ = ["overview", "universe", "library", "backtests", "pair", "signals", "positions", "accounts", "equity",
           "LIBRARY", "STATE_ID"]
