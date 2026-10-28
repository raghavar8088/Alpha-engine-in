"""Strategy Rank for every leaderboard in the app.

  GET /api/strategy-rank/{board}  ?book= &desk= &side= &symbol= &venue= (only the ones that board takes)

The path names the BOARD. `?desk=` is a query parameter of the Top-10 books' board, which holds one
board per desk; it was ignored while the path parameter was itself called `desk` (every desk's
Top-10 Rank was pooled into one).

Returns the desk's factor list once and, per strategy, its rank (1 = best on that desk), its
0-100 score and each factor's value and percentile. The page merges it into its own board by
strategy id. Desks and their sources are listed in services/strategy_rank_desks.py; the
Tournament's board carries its rank inline (/api/intraday-lab/leaderboard).

Cached 60 s per desk + params (5 min for a desk computed in Python): a rank moves only when a
trade closes, and the heavier boards (the commodity desk has ~42k closed trades) should not be
re-aggregated on every page poll.
`?fresh=true` recomputes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.response_cache import cached
from app.services.strategy_rank_desks import TTL_BY_DESK, clean_params, desk_ranks, known

router = APIRouter(prefix="/api/strategy-rank", tags=["strategy-rank"])

TTL_SECONDS = 60.0


@router.get("/{board}")
async def strategy_rank(
    board: str,
    book: str | None = Query(None),
    desk: str | None = Query(None),
    side: str | None = Query(None),
    symbol: str | None = Query(None),
    venue: str | None = Query(None),
    fresh: bool = Query(False),
    _user: dict = Depends(get_current_user),
):
    if not known(board):
        raise HTTPException(404, f"no ranked leaderboard called {board!r}")
    try:
        params = clean_params(board, {"book": book, "desk": desk, "side": side, "symbol": symbol,
                                      "venue": venue})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    key = "strategy-rank:" + board + ":" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return await cached(key, lambda: desk_ranks(board, params), ttl=TTL_BY_DESK.get(board, TTL_SECONDS),
                        fresh=fresh)
