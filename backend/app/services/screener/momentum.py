"""The multi-horizon momentum board: day, week, month and six months.

WHAT MAKES THIS DIFFERENT from the Bullish Stocks screen it sits beside. That one asks a
single yes/no question — is this stock in a confirmed uptrend right now — and answers it
with nine technical signals on daily bars. This one asks a comparative question across four
horizons at once: WHICH stocks are strongest today, this week, this month, this half-year,
and how does a name's rank differ between them. A stock top-10 on 1d and bottom-half on 6m
is a fresh move; the reverse is a trend losing its legs. Neither fact exists on a screen
that only looks at one horizon.

EVERY NUMBER COMES FROM STORED DAILY BARS except the live LTP, which is Angel's batched
quote — the same sweep Stocks Range already runs. No new vendor, no new credential, and
roughly ten broker requests for the entire Nifty 500.

RANKS ARE WITHIN THE SELECTED INDEX. A microcap's +8% and a Nifty-50 name's +8% are not
the same event, and pooling them produces a board permanently topped by the smallest,
thinnest names. The index selector is therefore part of the question, not a filter applied
after the fact.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app.core.db import instruments_collection, stock_universe_collection
from app.services.angel_client import AngelAPIError, angel_client
from app.services.screener import horizons as H
from app.services.screener import reasons as R
from app.services.stock_fundamentals import load_fundamentals
from app.services.stock_highs import load_highs
from app.services.stocks_range import INDEX_LABELS, QUOTE_PACE_SECONDS
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("screener.momentum")

BENCHMARK_SYMBOL = os.getenv("SCREENER_BENCHMARK", "NIFTY")
DEFAULT_INDEX = os.getenv("SCREENER_INDEX", "nifty500")
MIN_TURNOVER = float(os.getenv("SCREENER_MIN_TURNOVER", "10000000"))  # Rs1 crore/day
SNAPSHOT_TTL = float(os.getenv("SCREENER_SNAPSHOT_TTL", "300"))       # 5 min

_snapshot: dict[str, tuple[float, dict]] = {}


class ScreenerError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


async def _live_quotes(symbols: list[str]) -> dict[str, dict]:
    """Batched Angel FULL quotes keyed by symbol. Never raises: a quote failure costs the
    live LTP column, and every row falls back to its last stored close."""
    if not angel_client.configured():
        return {}
    inst = {
        d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": symbols}, "angel_token": {"$ne": None}},
            {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
        )
    }
    by_ex: dict[str, list[str]] = {}
    tok_sym: dict[str, str] = {}
    for sym, i in inst.items():
        tok = str(i["angel_token"])
        by_ex.setdefault(i.get("angel_exchange") or "NSE", []).append(tok)
        tok_sym[tok] = sym

    # Warm the session once, with one retry — a momentarily rate-limited login otherwise
    # fails the first chunk and blanks every price behind it.
    for attempt in range(2):
        try:
            await angel_client._session()
            break
        except AngelAPIError:
            if attempt == 0:
                await asyncio.sleep(0.7)

    out: dict[str, dict] = {}
    for grouped in batches(by_ex):
        try:
            for tok, q in (await angel_client.full_quote(grouped)).items():
                if tok in tok_sym:
                    out[tok_sym[tok]] = q
        except AngelAPIError:
            # Per-chunk catch: one bad chunk must not blank the other 450 stocks.
            pass
        await asyncio.sleep(QUOTE_PACE_SECONDS)
    return out


async def universe_snapshot(index: str = DEFAULT_INDEX, fresh: bool = False) -> dict:
    """Compute every per-symbol measurement once, for all four horizons.

    This is the expensive call and everything else in the module reads its output — the
    board, the sector roll-up and the drill-downs all share one snapshot rather than each
    re-walking the bar set.
    """
    if index not in INDEX_LABELS:
        raise ScreenerError(f"unknown index {index!r}; expected one of {sorted(INDEX_LABELS)}")

    now = time.monotonic()
    if not fresh:
        hit = _snapshot.get(index)
        if hit and now - hit[0] < SNAPSHOT_TTL:
            return hit[1]

    docs = [d async for d in stock_universe_collection.find(
        {"indices": index}, {"_id": 0, "symbol": 1, "name": 1, "sector": 1, "tightest_index": 1})]
    if not docs:
        raise ScreenerError(
            f"no constituents stored for {index}. The universe seed runs on startup and "
            f"weekly — POST /api/stocks-range/refresh to force it.")

    symbols = [d["symbol"] for d in docs]
    bars_by_sym, quotes, funds, highs = await asyncio.gather(
        H.load_daily_bars(symbols + [BENCHMARK_SYMBOL], fresh=fresh),
        _live_quotes(symbols),
        load_fundamentals(symbols),
        load_highs(symbols),
    )

    # Benchmark returns, for relative strength. Absent benchmark bars mean RS columns are
    # None everywhere rather than silently zero — zero would read as "matched the index".
    bench_bars = bars_by_sym.get(BENCHMARK_SYMBOL, [])
    bench_closes = [b.close for b in bench_bars]
    bench_returns = H.all_horizon_returns(bench_closes) if bench_closes else {
        h: None for h in H.HORIZONS}

    rows: list[dict] = []
    for d in docs:
        sym = d["symbol"]
        bars = bars_by_sym.get(sym) or []
        if len(bars) < 2:
            continue
        closes = [b.close for b in bars]
        q = quotes.get(sym) or {}

        # The live LTP replaces the last stored close so today's move is current during
        # the session. Outside market hours they are the same number.
        ltp = q.get("ltp") or closes[-1]
        live_closes = closes[:-1] + [float(ltp)]

        rets = H.all_horizon_returns(live_closes)
        hl52 = H.high_low_context(bars, 252)
        ath = (highs.get(sym) or {}).get("all_time_high")

        # Which Donchian level, if any, the last close broke. Widest first: reporting a
        # 252-day breakout as a 20-day one understates the event.
        breakout = None
        for window in (252, 50, 20):
            when = H.donchian_break(bars, window)
            if when:
                breakout = {"window": window, "date": when.isoformat()}
                break

        f = funds.get(sym) or {}
        rows.append({
            "symbol": sym,
            "name": d.get("name"),
            "sector": d.get("sector") or "Unclassified",
            "belongs_to": INDEX_LABELS.get(d.get("tightest_index")),
            "ltp": round(float(ltp), 2),
            "returns": {h: (round(v, 2) if v is not None else None) for h, v in rets.items()},
            "volume_x": _r(H.volume_ratio(bars)),
            "turnover": H.turnover(bars, 1),
            "ema9_hold_pct": _r(H.days_above_ema(closes)),
            "up_streak": H.up_streak(live_closes),
            "pct_from_52w_high": _r(hl52["pct_from_high"]),
            "pct_from_52w_low": _r(hl52["pct_from_low"]),
            "pct_from_ath": _r((float(ltp) / ath - 1) * 100) if ath else None,
            "breakout": breakout,
            "sma20": _r(H.sma(closes, 20)),
            "sma50": _r(H.sma(closes, 50)),
            "sma200": _r(H.sma(closes, 200)),
            "ema20": _r(H.ema_last(closes, 20)),
            # Levels the trade plans are built from, computed here so plans.py never has
            # to re-walk the bar set for one symbol.
            "atr14": _r(H.atr(bars)),
            "swing_low": _r(H.last_swing_low(bars)),
            "donchian_high_20": _r(H.donchian_high(bars, 20)),
            "donchian_high_50": _r(H.donchian_high(bars, 50)),
            "base_low_20": _r(H.donchian_low(bars, 20)),
            "sessions": len(bars),
            "delivery_pct": None,   # filled by nse_breadth when NSE is reachable
            # The tail of the close series, kept so consistency can be measured per
            # horizon without re-reading the bar set. 130 sessions covers the deepest
            # horizon (126) plus the bar it measures from.
            "_closes": [round(c, 2) for c in live_closes[-131:]],
            "_fund": {
                "known": bool(f),
                "revenue_growth": f.get("revenue_growth"),
                "earnings_growth": f.get("earnings_growth"),
                "roe": f.get("roe"),
            },
        })

    snap = {
        "index": index,
        "label": INDEX_LABELS[index],
        "rows": rows,
        "benchmark": {
            "symbol": BENCHMARK_SYMBOL,
            "available": bool(bench_closes),
            "returns": {h: (round(v, 2) if v is not None else None)
                        for h, v in bench_returns.items()},
        },
        "coverage": {h: H.coverage({r["symbol"]: bars_by_sym.get(r["symbol"], [])
                                    for r in rows}, h)
                     for h in H.HORIZON_ORDER},
        "quotes_live": bool(quotes),
        "computed_at": time.time(),
    }
    _snapshot[index] = (time.monotonic(), snap)
    return snap


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None else None


async def board(index: str = DEFAULT_INDEX, horizon: str = "1d",
                sector: str | None = None, limit: int = 100,
                min_turnover: float | None = None, fresh: bool = False) -> dict:
    """The ranked momentum table for one horizon."""
    if horizon not in H.HORIZONS:
        raise ScreenerError(f"unknown horizon {horizon!r}; expected one of {H.HORIZON_ORDER}")

    snap = await universe_snapshot(index, fresh=fresh)
    from app.services.screener import sectors as S

    sector_board = S.roll_up(snap, horizon)
    sector_index = {s["sector"]: s for s in sector_board["sectors"]}

    floor = MIN_TURNOVER if min_turnover is None else min_turnover
    bench = snap["benchmark"]["returns"].get(horizon)

    pool = [r for r in snap["rows"] if r["returns"].get(horizon) is not None]
    if floor:
        # Keep the turnover filter OUT of the ranking population only when a stock has no
        # turnover figure at all — filtering on a missing number would quietly drop names
        # for a data gap rather than for being illiquid.
        pool = [r for r in pool if r["turnover"] is None or r["turnover"] >= floor]
    if sector:
        pool = [r for r in pool if r["sector"] == sector]

    population = [r["returns"][horizon] for r in pool]
    sessions = H.HORIZONS[horizon]

    out = []
    for r in pool:
        ret = r["returns"][horizon]
        sec = sector_index.get(r["sector"]) or {}
        metrics = {
            **r,
            "consistency": None,
            "rs_index": H.relative_strength(ret, bench),
            "rs_sector": H.relative_strength(ret, sec.get("return_pct")),
        }
        # Consistency only means something over a multi-session window.
        if sessions > 1:
            metrics["consistency"] = _r(H.consistency(r.get("_closes") or [], sessions))

        stack = R.build(
            metrics,
            sector_ctx={
                "sector": r["sector"],
                "return_pct": sec.get("return_pct"),
                "rank": sec.get("rank"),
                "of": sector_board["count"],
            } if sec else None,
            fundamentals=r.get("_fund"),
            fno=None,
            narrative=None,
        )
        out.append({
            **{k: v for k, v in r.items() if not k.startswith("_")},
            "return_pct": ret,
            "rank_pct": _r(H.percentile_rank(ret, population)),
            "rs_index": _r(metrics["rs_index"]),
            "rs_sector": _r(metrics["rs_sector"]),
            "consistency": metrics["consistency"],
            "sector_return_pct": sec.get("return_pct"),
            "why": R.chips(stack),
            "why_summary": R.summarise(r["symbol"], ret, stack, narrative_available=False),
            "character": R.classify(stack),
            "score": _score(r, ret, metrics),
        })

    out.sort(key=lambda x: (-(x["score"] or 0), -(x["return_pct"] or 0)))
    for i, row in enumerate(out, 1):
        row["rank"] = i

    return {
        "index": snap["index"],
        "label": snap["label"],
        "horizon": horizon,
        "horizon_label": H.HORIZON_LABELS[horizon],
        "benchmark": snap["benchmark"],
        "coverage": snap["coverage"][horizon],
        "quotes_live": snap["quotes_live"],
        "sector_filter": sector,
        "min_turnover": floor,
        "count": len(out),
        "rows": out[:limit],
    }


def _score(row: dict, ret: float | None, metrics: dict) -> float | None:
    """A blunt 0-100 composite for default ordering, not a prediction.

    Deliberately simple and fully inspectable: return, relative strength, participation
    and trend quality, each capped so no single term can dominate. It exists so the board
    has a sensible default sort; the columns behind it are what a decision should use.
    """
    if ret is None:
        return None
    score = 0.0
    score += max(-20.0, min(40.0, ret * 2))                      # the move itself
    rs = metrics.get("rs_index")
    if rs is not None:
        score += max(-10.0, min(20.0, rs * 1.5))                 # vs the index
    vx = row.get("volume_x")
    if vx is not None:
        score += min(15.0, (vx - 1) * 7)                          # participation
    hold = row.get("ema9_hold_pct")
    if hold is not None:
        score += hold * 0.15                                      # trend quality
    if row.get("breakout"):
        score += 10.0
    pfh = row.get("pct_from_52w_high")
    if pfh is not None and pfh >= -2:
        score += 8.0
    return round(max(0.0, min(100.0, score + 30)), 1)


async def detail(symbol: str, index: str = DEFAULT_INDEX, fresh: bool = False) -> dict:
    """One stock: every horizon, the full reason stack, and the three trade plans."""
    symbol = symbol.strip().upper()
    snap = await universe_snapshot(index, fresh=fresh)
    row = next((r for r in snap["rows"] if r["symbol"] == symbol), None)
    if row is None:
        raise ScreenerError(f"{symbol} is not in {snap['label']} (or has no stored bars)")

    from app.services.screener import patterns as P
    from app.services.screener import plans as PL
    from app.services.screener import sectors as S

    per_horizon = {}
    for h in H.HORIZON_ORDER:
        sector_board = S.roll_up(snap, h)
        sec = next((s for s in sector_board["sectors"] if s["sector"] == row["sector"]), {})
        ret = row["returns"].get(h)
        bench = snap["benchmark"]["returns"].get(h)
        metrics = {**row, "rs_index": H.relative_strength(ret, bench),
                   "rs_sector": H.relative_strength(ret, sec.get("return_pct"))}
        stack = R.build(
            metrics,
            sector_ctx={"sector": row["sector"], "return_pct": sec.get("return_pct"),
                        "rank": sec.get("rank"), "of": sector_board["count"]} if sec else None,
            fundamentals=row.get("_fund"),
        )
        per_horizon[h] = {
            "label": H.HORIZON_LABELS[h],
            "return_pct": ret,
            "benchmark_pct": bench,
            "rs_index": _r(metrics["rs_index"]),
            "sector_return_pct": sec.get("return_pct"),
            "sector_rank": sec.get("rank"),
            "reasons": stack,
            "summary": R.summarise(symbol, ret, stack, narrative_available=False),
            "character": R.classify(stack),
        }

    hits = await P.for_symbol(symbol, fresh=fresh)
    trade_plans = await PL.plans_for(row, hits)

    return {
        "symbol": symbol,
        "name": row.get("name"),
        "sector": row["sector"],
        "belongs_to": row.get("belongs_to"),
        "ltp": row["ltp"],
        "sessions": row["sessions"],
        "horizons": per_horizon,
        "structure": {
            "sma20": row["sma20"], "sma50": row["sma50"], "sma200": row["sma200"],
            "ema9_hold_pct": row["ema9_hold_pct"],
            "pct_from_52w_high": row["pct_from_52w_high"],
            "pct_from_52w_low": row["pct_from_52w_low"],
            "pct_from_ath": row["pct_from_ath"],
            "volume_x": row["volume_x"],
            "up_streak": row["up_streak"],
            "breakout": row["breakout"],
        },
        "patterns": hits,
        "trade_plans": trade_plans,
        "narrative": {
            "available": False,
            "reason": "AI research not configured (ANTHROPIC_API_KEY unset) — news and "
                      "filings are not checked, and no narrative is invented in their place",
        },
    }
