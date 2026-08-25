"""One history endpoint for every desk.

  GET /api/desk-history/desks          what can be asked for
  GET /api/desk-history/{desk}         started_on, days, per-day P&L/ROI, averages, curve

A single registry instead of a /history route bolted onto ten routers: the shape of the
answer is identical everywhere, so the only per-desk facts are which collection holds the
positions, what the capital is, which field means "money at risk", and whether the desk
keeps equity snapshots. Those four things are the registry.

Capital is resolved LAZILY, inside the request. Several desks compute theirs at import time
from a strategy catalog, and importing all of them at module load would drag every engine
into the process just to answer a question about one.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core import db as D
from app.services.desk_history import history
from app.services.response_cache import cached as _cached

router = APIRouter(prefix="/api/desk-history", tags=["desk-history"])


def _capital(getter):
    """Defer the engine import until the desk is actually asked for."""
    return getter


DESKS: dict[str, dict] = {
    "live-trading": {
        "label": "Live Trading (real money)",
        "positions": lambda: D.live_trading_positions_collection,
        "equity": lambda: D.live_trading_equity_collection,
        "capital": lambda: __import__("app.services.live_trading_engine", fromlist=["x"]).INITIAL_CAPITAL,
    },
    "swing": {
        "label": "Swing Trading",
        "positions": lambda: D.swing_positions_collection,
        "equity": lambda: D.swing_equity_collection,
        "capital": lambda: __import__("app.services.swing_trading", fromlist=["x"]).TOTAL_CAPITAL,
    },
    "nifty-scalp": {
        "label": "NIFTY 50 Option Scalping",
        "positions": lambda: D.nifty_scalp_positions_collection,
        "equity": lambda: D.nifty_scalp_equity_collection,
        "capital": lambda: __import__("app.services.nifty_scalp_engine", fromlist=["x"]).TOTAL_CAPITAL,
    },
    "intraday-lab": {
        "label": "Intraday Stocks tournament",
        "positions": lambda: D.intraday_lab_positions_collection,
        "equity": lambda: D.intraday_lab_equity_collection,
        "capital": lambda: __import__("app.services.intraday_lab_engine", fromlist=["x"]).INTRADAY_LAB_INITIAL_CAPITAL,
    },
    "zero-hero": {
        "label": "Zero Hero Trades",
        "positions": lambda: D.zero_hero_positions_collection,
        "equity": lambda: D.zero_hero_equity_collection,
        # zero_hero sizes per strategy and never names a desk total, so the total is
        # derived from its catalog rather than assumed into existence.
        "capital": lambda: (lambda z: z.PER_STRATEGY_CAPITAL * max(len(z.STRATEGIES), 1))(
            __import__("app.services.zero_hero", fromlist=["x"])),
    },
    "buy-low": {
        "label": "Buy Low Options",
        "positions": lambda: D.buy_low_positions_collection,
        "equity": lambda: D.buy_low_equity_collection,
        "capital": lambda: __import__("app.services.buy_low_options", fromlist=["x"]).TOTAL_CAPITAL,
    },
    "momentum": {
        "label": "Momentum",
        "positions": lambda: D.momentum_positions_collection,
        "equity": lambda: D.momentum_equity_collection,
        "capital": lambda: __import__("app.services.momentum_engine", fromlist=["x"]).INITIAL_CAPITAL,
    },
    # Long-only desk over the user's own basket. Its capital is 678 strategies x Rs10L, so
    # the desk-level ROI denominator is enormous and the "on capital deployed" number is
    # the one that means anything here — which is exactly why this reader reports both.
    "trending-stocks": {
        "label": "Trending Stocks",
        "positions": lambda: D.ts_positions_collection,
        "equity": lambda: D.ts_equity_collection,
        "capital": lambda: __import__("app.services.trending_stocks.engine",
                                      fromlist=["x"]).INITIAL_CAPITAL,
    },
}

# Desks that split into books/buckets take a `scope` and filter on their own key.
SCOPED: dict[str, dict] = {
    "live-intraday": {
        "label": "Live Intraday",
        "positions": lambda: D.live_intraday_positions_collection,
        "equity": lambda: D.live_intraday_equity_collection,
        "field": "book",
        "default": "80k",
        "capital": lambda s: __import__("app.services.live_intraday_engine", fromlist=["x"]).book_capital(s),
    },
    "momentum-trading": {
        "label": "Momentum Trading",
        "positions": lambda: D.momentum_trading_positions_collection,
        "equity": lambda: D.momentum_trading_equity_collection,
        "field": "bucket",
        "default": "top752",
        "capital": lambda s: __import__("app.services.momentum_trading", fromlist=["x"]).TOTAL_CAPITAL,
    },
}


@router.get("/desks")
async def list_desks(current_user: dict = Depends(get_current_user)):
    return {
        "desks": [{"key": k, "label": v["label"], "scoped": False} for k, v in DESKS.items()]
        + [{"key": k, "label": v["label"], "scoped": True, "default_scope": v["default"]}
           for k, v in SCOPED.items()]
        + [{"key": "fno", "label": "F&O Positions (per account)", "scoped": True,
            "default_scope": None},
           {"key": "commodity-positions", "label": "Commodity Positions (per account)",
            "scoped": True, "default_scope": None}],
    }


async def _fno(account_id: str | None):
    """F&O keeps one positions collection for many paper accounts, and no equity
    snapshots — so the curve is derived from closed trades."""
    acc = await (D.fno_accounts_collection.find_one({"account_id": account_id})
                 if account_id else D.fno_accounts_collection.find_one({}))
    if not acc:
        raise HTTPException(404, "no such F&O account")
    return await history(
        D.fno_positions_collection,
        float(acc.get("initial_capital") or 0),
        match={"account_id": acc["account_id"]},
        deployed_field="margin_used",
    ) | {"account_id": acc["account_id"], "account_name": acc.get("name")}


async def _commodity_positions(account_id: str | None):
    """Same shape as the F&O reader: one positions collection across many paper accounts,
    no equity snapshots, so the curve is derived from closed trades. Margin is the money
    actually put at risk, which on a commodity book is a small fraction of the notional —
    so the deployed-capital ROI is the one that means anything here."""
    acc = await (D.commodity_accounts_collection.find_one({"account_id": account_id})
                 if account_id else D.commodity_accounts_collection.find_one({}))
    if not acc:
        raise HTTPException(404, "no such commodity account")
    return await history(
        D.commodity_pos_positions_collection,
        float(acc.get("initial_capital") or 0),
        match={"account_id": acc["account_id"]},
        deployed_field="margin_used",
    ) | {"account_id": acc["account_id"], "account_name": acc.get("name")}


@router.get("/{desk}")
async def desk_history(
    desk: str,
    scope: str | None = Query(None, description="book / bucket / F&O account_id"),
    fresh: bool = Query(False, description="bypass the short cache"),
    current_user: dict = Depends(get_current_user),
):
    if desk == "fno":
        return await _cached(f"hist:fno:{scope}", lambda: _fno(scope), fresh=fresh)

    if desk == "commodity-positions":
        return await _cached(f"hist:cmp:{scope}",
                             lambda: _commodity_positions(scope), fresh=fresh)

    if desk in SCOPED:
        cfg = SCOPED[desk]
        sc = scope or cfg["default"]
        return await _cached(
            f"hist:{desk}:{sc}",
            lambda: history(cfg["positions"](), float(cfg["capital"](sc)),
                            match={cfg["field"]: sc},
                            equity=cfg["equity"](), equity_match={cfg["field"]: sc}),
            fresh=fresh)

    cfg = DESKS.get(desk)
    if not cfg:
        raise HTTPException(404, f"unknown desk {desk!r}; see /api/desk-history/desks")
    return await _cached(
        f"hist:{desk}",
        lambda: history(cfg["positions"](), float(cfg["capital"]()), equity=cfg["equity"]()),
        fresh=fresh)
