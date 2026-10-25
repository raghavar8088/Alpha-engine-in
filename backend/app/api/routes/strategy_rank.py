"""Strategy Rank for every leaderboard in the app.

  GET /api/strategy-rank/{desk}   ?book= &side= &symbol= &venue= (only the ones that desk takes)

Returns the desk's factor list once and, per strategy, its rank (1 = best on that desk), its
0-100 score and each factor's value and percentile. The page merges it into its own board by
strategy id. Desks and their sources are listed in services/strategy_rank_desks.py; the
Tournament's board carries its rank inline (/api/intraday-lab/leaderboard).

Cached 60 s per desk + params: a rank moves only when a trade closes, and the heavier boards
(the commodity desk has ~42k closed trades) should not be re-aggregated on every page poll.
`?fresh=true` recomputes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.response_cache import cached
from app.services.strategy_rank_desks import clean_params, desk_ranks, known

router = APIRouter(prefix="/api/strategy-rank", tags=["strategy-rank"])

TTL_SECONDS = 60.0


@router.get("/{desk}")
async def strategy_rank(
    desk: str,
    book: str | None = Query(None),
    side: str | None = Query(None),
    symbol: str | None = Query(None),
    venue: str | None = Query(None),
    fresh: bool = Query(False),
    _user: dict = Depends(get_current_user),
):
    if not known(desk):
        raise HTTPException(404, f"no ranked leaderboard called {desk!r}")
    try:
        params = clean_params(desk, {"book": book, "side": side, "symbol": symbol, "venue": venue})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    key = "strategy-rank:" + desk + ":" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return await cached(key, lambda: desk_ranks(desk, params), ttl=TTL_SECONDS, fresh=fresh)
