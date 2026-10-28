"""Where each strategy leaderboard's Rank comes from - every desk in one table.

PAPER / LIVE DESKS are ranked from their own closed trades (`strategy_rank.position_stats`),
on the same seven factors as the Tournament. Each entry names the collection, which rows are
closed trades, and the few fields that differ between desks (the P&L field, what was deployed,
which day a trade belongs to). Read-only: nothing here writes or changes a desk.

BACKTEST BOARDS (Options Lab sweeps, Strategy Factory, Trending Stocks) have no trade record,
so they are ranked on the metrics they report, with a factor list of their own.

A rank is computed over the WHOLE desk (or the one book / side / contract asked for), not over
whatever filter the page has on, so a strategy keeps its rank when the board is filtered.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.core.db import db
from app.services.strategy_rank import (MIN_TRADES, POSITION_FACTORS, Factor, compact,
                                        position_stats, rank_rows, stats_from_trades)

CLOSED = {"status": "CLOSED"}
_SAFE = re.compile(r"^[A-Za-z0-9_.\-@&|: ]{1,64}$")
# Option SELLING is not judged on win rate anywhere in this app - a seller wins most trades and
# can still lose money on the tail - so its rank leaves win rate out too.
SELLING_FACTORS: tuple[Factor, ...] = tuple(f for f in POSITION_FACTORS if f[0] != "win_rate")
SELLING_DESKS = {"prelive-selling", "selling-books"}


@dataclass(frozen=True)
class TradeSource:
    coll: str
    match: dict
    key: Any = "strategy_id"
    pnl: str = "realized_pnl"
    deployed: Any = "capital_deployed"
    day: Any = None                      # None: closed_on, else the IST date of `ts`
    ts: str = "closed_at"
    params: dict = field(default_factory=dict)   # query param -> document field it filters
    note: str | None = None                      # which P&L the rank is computed on, if not obvious


DESKS: dict[str, TradeSource] = {
    # Intraday Stocks
    "pattern": TradeSource("pattern_positions", CLOSED),
    "pattern-books": TradeSource("pattern_book_positions", {**CLOSED, "source": "desk"},
                                 params={"book": "book"}),
    "live-intraday": TradeSource("live_intraday_positions", {**CLOSED, "source": "tournament"},
                                 params={"book": "book"}),
    "focus-five": TradeSource("intraday_focus_trades", CLOSED),
    "live-trading": TradeSource("live_trading_positions", CLOSED),
    # Momentum, long horizon
    "momentum": TradeSource("momentum_positions", CLOSED),
    "long-horizon": TradeSource("long_horizon_positions", CLOSED),
    # NIFTY options
    "nifty-scalp": TradeSource("nifty_scalp_positions", CLOSED),
    "nifty-scalp-paper": TradeSource("nifty_scalp_paper_positions", CLOSED),
    "zero-hero": TradeSource("zero_hero_positions", CLOSED, day="session"),
    "live-paper": TradeSource("live_paper_positions", CLOSED, day="session",
                              deployed={"$multiply": ["$entry_premium", "$qty"]},
                              params={"book": "book"}),
    # The selling daemon writes one document per CLOSED trade; its P&L is `pnl` on `margin`.
    "prelive-selling": TradeSource("prelive_selling_trades", {}, pnl="pnl", deployed="margin",
                                   ts="exit_ts", day={"$substrCP": ["$exit_ts", 0, 10]}),
    "selling-books": TradeSource("selling_book_positions", CLOSED, key="pick", deployed="capital",
                                 params={"book": "book"}),
    # Stock options
    "stock-desk": TradeSource("stock_desk_positions", CLOSED, params={"side": "side"}),
    "stock-books": TradeSource("stock_book_positions", CLOSED, params={"book": "book"}),
    # Commodity. The pattern desk's record is its `honest` trades at `record_pnl` (repriced on
    # each contract's own prices) - what its leaderboard and gate count; `realized_pnl` is the
    # old loop's, and trades before the honest cutover are not part of the record at all.
    "commodity": TradeSource("commodity_positions", {**CLOSED, "honest": True}, pnl="record_pnl",
                             params={"symbol": "symbol"},
                             note="honest trades only (filled at a live quote with MCX open at entry and "
                                  "exit, on the trade's own contract), at the repriced record P&L"),
    "commodity-prelive": TradeSource("commodity_prelive_positions", CLOSED,
                                     key={"$concat": ["$strategy_id", "|", {"$ifNull": ["$symbol", ""]}]}),
    # The NatGas book's roster names a strategy by template and timeframe, not by id.
    "natgas": TradeSource("natgas_book_positions", CLOSED,
                          key={"$concat": ["$strategy_template", ":", "$timeframe"]}),
    # Gold's records are keyed symbol-template-timeframe on its page.
    "gold": TradeSource("gold_desk_positions", CLOSED, params={"venue": "venue"},
                        key={"$concat": ["$symbol", "-", "$strategy_template", "-", "$timeframe"]}),
    # Stock screener paper desk: its board is per SIGNAL FAMILY.
    "screener-paper": TradeSource("screener_paper_trades", {"status": {"$ne": "OPEN"}},
                                  key="family", pnl="net_pnl", deployed="capital"),
    # Top-10 paper books on six desks (app.services.top10_books): one board per desk and book.
    "top10-books": TradeSource("top10_book_positions", {**CLOSED, "source": "top10"}, key="key",
                               params={"desk": "desk", "book": "book"}),
    # Strategy Factory tabs on six modules (app.services.factory_desks): one board per tab.
    "factory-desks": TradeSource("factory_desk_positions", CLOSED, params={"desk": "desk"}),
}


# -- backtest boards: ranked on the metrics they report -------------------------------------

def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


async def _options_buying() -> tuple[list[dict], str | None]:
    doc = await db["option_sweeps"].find_one({}, sort=[("created_at", -1)])
    rows = []
    for r in (doc or {}).get("results") or []:
        m = r.get("metrics") or {}
        rows.append({
            # The page keys a row as strategy-symbol-timeframe; the same key here.
            "id": f"{r.get('strategy_id')}-{r.get('symbol') or ''}-{r.get('timeframe')}",
            "trades": 0 if r.get("error") else int(m.get("total_trades") or 0),
            "profit_factor": _num(m.get("profit_factor")), "expectancy": _num(m.get("expectancy")),
            "max_drawdown_pct": _num(m.get("max_drawdown_pct")), "net_pnl": _num(m.get("net_profit")),
            "win_rate": _num(m.get("win_rate")),
        })
    return rows, (doc or {}).get("sweep_id")


async def _options_selling() -> tuple[list[dict], str | None]:
    doc = await db["option_sweeps_selling"].find_one({}, sort=[("created_at", -1)])
    rows = []
    for r in (doc or {}).get("results") or []:
        m = r.get("metrics") or {}
        s = m.get("selling") or {}
        rows.append({
            "id": r.get("strategy_id"),
            "trades": 0 if r.get("error") else int(m.get("total_trades") or 0),
            "profit_factor": _num(m.get("profit_factor")),
            "return_on_margin_pct": _num(s.get("return_on_margin_pct")),
            "worst_trade_pct_capital": _num(s.get("worst_trade_pct_capital")),
            "max_drawdown_pct": _num(m.get("max_drawdown_pct")), "tail_ratio": _num(s.get("tail_ratio")),
            "net_pnl": _num(m.get("net_profit")),
        })
    return rows, (doc or {}).get("sweep_id")


def _catalog_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "id": r.get("strategy_id"), "trades": int(r.get("bt_trades") or 0),
            # Out-of-sample net only means something when it traded out of sample.
            "oos_net_pnl": _num(r.get("oos_net_pnl")) if r.get("oos_trades") else None,
            "sharpe": _num(r.get("bt_sharpe")),
            "profit_factor": _num(r.get("bt_profit_factor")), "avg_r": _num(r.get("bt_avg_r")),
            "max_drawdown_pct": _num(r.get("bt_max_dd_pct")), "cagr_pct": _num(r.get("bt_cagr_pct")),
            "wf_fraction": _num(r.get("wf_fraction")), "win_rate": _num(r.get("bt_win_rate")),
            "net_pnl": _num(r.get("oos_net_pnl")) or 0.0,
        })
    return out


async def _strategy_factory() -> tuple[list[dict], str | None]:
    from app.services.strategy_factory import engine as sf
    return _catalog_rows(await sf.leaderboard(limit=100_000)), None


async def _trending_stocks() -> tuple[list[dict], str | None]:
    from app.services.trending_stocks import engine as ts
    return _catalog_rows(await ts.leaderboard(limit=100_000)), None


@dataclass(frozen=True)
class RowSource:
    # Rows, plus the id of the run they came from (a sweep id) so the page can tell a rank of
    # the sweep it is showing from one of a sweep run since.
    load: Callable[[], Awaitable[tuple[list[dict], str | None]]]
    factors: tuple[Factor, ...]


BACKTESTS: dict[str, RowSource] = {
    "options-buying": RowSource(_options_buying, (
        ("profit_factor", "Profit factor", 25.0, True, "ratio"),
        ("expectancy", "Expectancy per trade", 25.0, True, "inr"),
        ("max_drawdown_pct", "Max drawdown", 20.0, False, "pct"),
        ("net_pnl", "Net P&L", 15.0, True, "inr"),
        ("win_rate", "Win rate", 15.0, True, "fraction"),
    )),
    # The selling gate ignores win rate on purpose (a seller wins most trades and dies on the
    # tail), so the rank does too.
    "options-selling": RowSource(_options_selling, (
        ("profit_factor", "Profit factor", 25.0, True, "ratio"),
        ("return_on_margin_pct", "Return on margin", 25.0, True, "pct"),
        ("worst_trade_pct_capital", "Worst trade", 20.0, False, "pct"),
        ("max_drawdown_pct", "Max drawdown", 15.0, False, "pct"),
        ("tail_ratio", "Tail ratio", 15.0, False, "ratio"),
    )),
    # Sharpe stands in for the t-stat a backtest catalog does not report.
    "strategy-factory": RowSource(_strategy_factory, (
        ("oos_net_pnl", "Out-of-sample net", 20.0, True, "inr"),
        ("sharpe", "Sharpe", 20.0, True, "ratio"),
        ("profit_factor", "Profit factor", 15.0, True, "ratio"),
        ("avg_r", "Average R", 15.0, True, "r"),
        ("max_drawdown_pct", "Max drawdown", 15.0, False, "pct"),
        ("cagr_pct", "CAGR", 10.0, True, "pct"),
        ("win_rate", "Win rate", 5.0, True, "fraction"),
    )),
    "trending-stocks": RowSource(_trending_stocks, (
        ("oos_net_pnl", "Out-of-sample net", 15.0, True, "inr"),
        ("sharpe", "Sharpe", 15.0, True, "ratio"),
        ("profit_factor", "Profit factor", 15.0, True, "ratio"),
        ("wf_fraction", "Walk-forward windows won", 15.0, True, "fraction"),
        ("avg_r", "Average R", 15.0, True, "r"),
        ("max_drawdown_pct", "Max drawdown", 15.0, False, "pct"),
        ("cagr_pct", "CAGR", 5.0, True, "pct"),
        ("win_rate", "Win rate", 5.0, True, "fraction"),
    )),
}


# -- desks whose honest P&L exists only in Python -------------------------------------------

def _epoch(v) -> float | None:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
    return None


async def _prelive_items() -> list[dict]:
    """The NIFTY option-buying tournament (Index Option Buying, NIFTY 50), one item per closed
    trade at its REAL-MONEY estimate - prelive_stats.real_money: today's lot of 65, bought at the
    ask and sold at the bid, Angel's rate card - which is what that page judges a strategy on.
    The paper fill (option LTP, old 75 lot, no STT before 2 Oct) flatters every strategy."""
    from app.services import prelive_stats as ps

    fields = {"_id": 0, "key": 1, "session": 1, "exit_ts": 1, "real_pnl": 1, "real_basis": 1,
              "lot_size": 1, "lots": 1, "qty": 1, "entry_premium": 1, "exit_premium": 1}
    trades = [t async for t in db["prelive_trades"].find({}, fields)]

    def build() -> list[dict]:
        items = []
        for t in trades:
            try:
                pnl, _basis = ps.real_money(t)
                lots = int(t.get("lots") or max(1, round(float(t.get("qty") or 75) / float(t.get("lot_size") or 75))))
            except (KeyError, TypeError, ValueError):
                continue
            items.append({"key": t.get("key"), "pnl": pnl, "day": t.get("session"),
                          "deployed": float(t.get("entry_premium") or 0.0) * lots * ps.LOT_NOW,
                          "ts": _epoch(t.get("exit_ts"))})
        return items

    return await asyncio.to_thread(build)


@dataclass(frozen=True)
class PyTradeSource:
    load: Callable[[], Awaitable[list[dict]]]
    note: str | None = None


PY_TRADES: dict[str, PyTradeSource] = {
    "prelive": PyTradeSource(_prelive_items, note=(
        "the real-money estimate of each trade (NIFTY's lot of 65, bought at the ask and sold at "
        "the bid - from the order book since 5 Oct, an estimated half-spread before - Angel One's "
        "rate card), not the paper fill")),
}

# Seconds a ranked board is cached. The Python-computed desk reads ~10,000 trades.
TTL_BY_DESK: dict[str, float] = {"prelive": 300.0}


def known(desk: str) -> bool:
    return desk in DESKS or desk in BACKTESTS or desk in PY_TRADES


def clean_params(desk: str, raw: dict[str, str | None]) -> dict[str, str]:
    """Only the params this desk takes, and only plain short strings - they go into a query."""
    allowed = DESKS[desk].params if desk in DESKS else {}
    out = {}
    for name in allowed:
        v = raw.get(name)
        if v is None or v == "":
            continue
        if not _SAFE.match(v):
            raise ValueError(f"bad {name!r}")
        out[name] = v
    return out


async def desk_ranks(desk: str, params: dict[str, str]) -> dict:
    """The ranked board for one desk (and book / side / contract), compact."""
    if desk in BACKTESTS:
        src = BACKTESTS[desk]
        loaded, source_id = await src.load()
        rows = [r for r in loaded if r.get("id")]
        ranked = rank_rows(rows, min_trades=MIN_TRADES, factors=src.factors)
        return {"desk": desk, "params": params, "basis": "backtest", "min_trades": MIN_TRADES,
                "source_id": source_id, "strategies": len(rows),
                **compact(ranked, src.factors, id_key="id")}

    if desk in PY_TRADES:
        py = PY_TRADES[desk]
        stats = stats_from_trades(await py.load())
        rows = [{"id": sid, **st} for sid, st in stats.items()]
        ranked = rank_rows(rows, min_trades=MIN_TRADES, factors=POSITION_FACTORS)
        return {"desk": desk, "params": params, "basis": "trades", "basis_note": py.note,
                "min_trades": MIN_TRADES, "strategies": len(rows),
                **compact(ranked, POSITION_FACTORS, id_key="id")}

    src = DESKS[desk]
    match = dict(src.match)
    for name, value in params.items():
        match[src.params[name]] = value
    stats = await position_stats(db[src.coll], match, key=src.key, pnl=src.pnl,
                                 deployed=src.deployed, day=src.day, ts=src.ts)
    rows = [{"id": sid, **st} for sid, st in stats.items()]
    factors = SELLING_FACTORS if desk in SELLING_DESKS or params.get("side") == "selling" else POSITION_FACTORS
    ranked = rank_rows(rows, min_trades=MIN_TRADES, factors=factors)
    return {"desk": desk, "params": params, "basis": "trades", "basis_note": src.note,
            "min_trades": MIN_TRADES, "strategies": len(rows), **compact(ranked, factors, id_key="id")}
