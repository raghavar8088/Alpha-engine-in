"""Portfolio analytics + risk status (roadmap Phase 4) computed over the connected
Dhan account's real holdings/positions/funds, not raw pass-through — this is what
lifts /portfolio from a mirror of Dhan's JSON to actual P&L/exposure/risk numbers.

Field shapes are the live Dhan v2 API (verified against a real connected account):
holdings = [{tradingSymbol, securityId, totalQty, avgCostPrice, lastTradedPrice, ...}]
positions = [{tradingSymbol, netQty, buyAvg, costPrice, realizedProfit,
              unrealizedProfit, positionType, ...}] (day positions only)
funds = {availabelBalance, utilizedAmount, collateralAmount, ...} (Dhan's own spelling)
"""

from datetime import datetime, timezone

from app.core.db import bars_collection, risk_config_collection
from app.services.dhan_client import DhanClient
from risk_service import RiskEngine, RiskLimits
from tradingai_shared.sectors import get_sector

TRADING_DAYS_PER_YEAR = 252
BETA_LOOKBACK_BARS = 60
BENCHMARK_SYMBOL = "NIFTY"

DEFAULT_RISK_LIMITS = RiskLimits(
    daily_loss_limit_pct=3.0,
    max_drawdown_pct=15.0,
    max_open_positions=5,
    max_exposure_pct=80.0,
    max_sector_exposure_pct=30.0,
    max_portfolio_heat_pct=6.0,
)


async def get_risk_limits() -> RiskLimits:
    doc = await risk_config_collection.find_one({"_id": "default"})
    return RiskLimits(**doc["limits"]) if doc else DEFAULT_RISK_LIMITS


async def set_risk_limits(limits: RiskLimits) -> None:
    await risk_config_collection.update_one(
        {"_id": "default"}, {"$set": {"limits": limits.model_dump()}}, upsert=True
    )


async def _fetch_account_state(client: DhanClient) -> tuple[list[dict], list[dict], dict]:
    holdings = await client.get_holdings()
    positions = await client.get_positions()
    funds = await client.get_fund_limits()
    holdings = holdings if isinstance(holdings, list) else []
    positions = positions if isinstance(positions, list) else []
    return holdings, positions, funds


def _holding_value(h: dict) -> float:
    return h["totalQty"] * h["lastTradedPrice"]


def _holding_cost(h: dict) -> float:
    return h["totalQty"] * h["avgCostPrice"]


def _position_notional(p: dict) -> float:
    price = p.get("costPrice") or p.get("buyAvg") or 0
    return abs(p.get("netQty", 0)) * price


async def compute_portfolio_analytics(client: DhanClient) -> dict:
    holdings, positions, funds = await _fetch_account_state(client)

    holdings_value = sum(_holding_value(h) for h in holdings)
    holdings_cost = sum(_holding_cost(h) for h in holdings)
    unrealized_holdings = holdings_value - holdings_cost
    unrealized_positions = sum(p.get("unrealizedProfit", 0) for p in positions)
    realized_today = sum(p.get("realizedProfit", 0) for p in positions)
    positions_notional = sum(_position_notional(p) for p in positions)

    cash_available = funds.get("availabelBalance", 0)
    total_capital = cash_available + funds.get("utilizedAmount", 0)
    deployed = positions_notional  # holdings are pre-funded delivery equity, not
    # drawn from this trading-margin pool (verified against a live account: holdings
    # value routinely dwarfs availabelBalance+utilizedAmount, since that's the margin
    # account's capital, not the user's total net worth) — so exposure here is
    # deliberately POSITIONS-only ("how much of my trading capital is at work in open
    # intraday/F&O positions right now"). Holdings get their own P&L/allocation
    # figures below without being forced through this ratio.
    exposure_pct = round(deployed / total_capital * 100, 2) if total_capital > 0 else None
    total_portfolio_value = holdings_value + positions_notional
    holdings_pct_of_portfolio = (
        round(holdings_value / total_portfolio_value * 100, 2) if total_portfolio_value > 0 else None
    )

    sector_value: dict[str, float] = {}
    for h in holdings:
        sector = get_sector(h["tradingSymbol"]) or "Unclassified"
        sector_value[sector] = sector_value.get(sector, 0) + _holding_value(h)
    for p in positions:
        sector = get_sector(p.get("tradingSymbol", "")) or "Unclassified"
        sector_value[sector] = sector_value.get(sector, 0) + _position_notional(p)
    sector_allocation = [
        {
            "sector": s,
            "value": round(v, 2),
            "pct": round(v / total_portfolio_value * 100, 2) if total_portfolio_value > 0 else 0,
        }
        for s, v in sorted(sector_value.items(), key=lambda kv: -kv[1])
    ]

    beta, alpha_annual_pct, volatility_annual_pct, beta_symbols, beta_note = await _compute_beta_alpha_vol(
        holdings, positions
    )

    return {
        "unrealized_pnl": round(unrealized_holdings + unrealized_positions, 2),
        "unrealized_pnl_holdings": round(unrealized_holdings, 2),
        "unrealized_pnl_positions": round(unrealized_positions, 2),
        "realized_pnl_today": round(realized_today, 2),
        "holdings_value": round(holdings_value, 2),
        "positions_notional": round(positions_notional, 2),
        "capital_allocation": {
            "total_capital": round(total_capital, 2),
            "cash_available": round(cash_available, 2),
            "deployed": round(deployed, 2),
        },
        "exposure_pct": exposure_pct,
        "exposure_note": (
            "Positions (intraday/F&O) only, vs available trading capital. Holdings "
            "are pre-funded delivery equity, not drawn from this margin pool."
        ),
        "holdings_pct_of_portfolio": holdings_pct_of_portfolio,
        "sector_allocation": sector_allocation,
        "beta": beta,
        "alpha_annual_pct": alpha_annual_pct,
        "volatility_annual_pct": volatility_annual_pct,
        "beta_symbols_used": beta_symbols,
        "beta_note": beta_note,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def _compute_beta_alpha_vol(
    holdings: list[dict], positions: list[dict]
) -> tuple[float | None, float | None, float | None, list[str], str | None]:
    """Weighted-portfolio beta/alpha/volatility vs NIFTY, from the Mongo `bars` daily
    series. Weights are current market value (a snapshot, not rebalanced through the
    window — a documented simplification). Symbols without backfilled daily bars are
    silently excluded; if NONE have data, every field is None with an explanatory note
    rather than a fabricated number."""
    weights: dict[str, float] = {}
    for h in holdings:
        value = _holding_value(h)
        if value > 0:
            weights[h["tradingSymbol"]] = weights.get(h["tradingSymbol"], 0) + value
    for p in positions:
        value = _position_notional(p)
        symbol = p.get("tradingSymbol", "")
        if value > 0 and symbol:
            weights[symbol] = weights.get(symbol, 0) + value

    total_value = sum(weights.values())
    if total_value <= 0:
        return None, None, None, [], "No holdings/positions with market value to weight."

    benchmark_closes = await _load_daily_closes(BENCHMARK_SYMBOL)
    if len(benchmark_closes) < 2:
        return None, None, None, [], f"No backfilled daily bars for benchmark {BENCHMARK_SYMBOL}."

    symbol_returns: dict[str, list[float]] = {}
    used_symbols: list[str] = []
    for symbol, value in weights.items():
        if symbol == BENCHMARK_SYMBOL:
            continue
        closes = await _load_daily_closes(symbol)
        if len(closes) < 2:
            continue
        symbol_returns[symbol] = closes
        used_symbols.append(symbol)

    if not used_symbols:
        return (
            None, None, None, [],
            "No backfilled daily bars for any held symbol — run market-data-service/backfill.py "
            "for these holdings to enable beta/alpha/volatility.",
        )

    # Align on the shortest common trailing window across symbols + benchmark
    window = min([len(c) for c in symbol_returns.values()] + [len(benchmark_closes)])
    window = min(window, BETA_LOOKBACK_BARS + 1)
    if window < 10:
        return None, None, None, used_symbols, "Fewer than 10 aligned trading days of history — too short to size a beta."

    bench_rets = _returns(benchmark_closes[-window:])
    used_weight = sum(weights[s] for s in used_symbols)
    portfolio_rets = [0.0] * len(bench_rets)
    for symbol in used_symbols:
        w = weights[symbol] / used_weight
        rets = _returns(symbol_returns[symbol][-window:])
        for i in range(len(bench_rets)):
            portfolio_rets[i] += w * rets[i]

    beta = _beta(portfolio_rets, bench_rets)
    port_mean = sum(portfolio_rets) / len(portfolio_rets)
    bench_mean = sum(bench_rets) / len(bench_rets)
    alpha_annual_pct = round((port_mean - beta * bench_mean) * TRADING_DAYS_PER_YEAR * 100, 2) if beta is not None else None
    vol = _stdev(portfolio_rets)
    volatility_annual_pct = round(vol * (TRADING_DAYS_PER_YEAR ** 0.5) * 100, 2)

    note = None
    if used_weight < total_value * 0.999:
        missing_pct = round((1 - used_weight / total_value) * 100, 1)
        note = f"{missing_pct}% of portfolio value excluded (no backfilled bars for those symbols)."

    return (round(beta, 3) if beta is not None else None, alpha_annual_pct, volatility_annual_pct, used_symbols, note)


async def _load_daily_closes(symbol: str) -> list[float]:
    cursor = (
        bars_collection.find({"symbol": symbol, "timeframe": "1d"})
        .sort("ts", -1)
        .limit(BETA_LOOKBACK_BARS + 1)
    )
    docs = [doc async for doc in cursor]
    docs.reverse()
    return [doc["close"] for doc in docs]


def _returns(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1]]


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def _beta(portfolio_rets: list[float], bench_rets: list[float]) -> float | None:
    n = len(bench_rets)
    if n < 2:
        return None
    p_mean = sum(portfolio_rets) / n
    b_mean = sum(bench_rets) / n
    covariance = sum((portfolio_rets[i] - p_mean) * (bench_rets[i] - b_mean) for i in range(n)) / (n - 1)
    variance = sum((r - b_mean) ** 2 for r in bench_rets) / (n - 1)
    return covariance / variance if variance > 0 else None


async def get_risk_status(client: DhanClient) -> dict:
    """Point-in-time live risk status. Unlike the backtester (which tracks a full
    equity curve), the live account has no persisted daily baseline yet — day P&L
    comes straight from Dhan's own day-scoped realizedProfit/unrealizedProfit on open
    positions, so this is a documented v1 approximation; a persisted equity-curve
    snapshot (for true max-drawdown and portfolio heat) arrives with Phase 8's
    scheduler + Phase 5's live strategy engine (which tracks per-position stops)."""
    holdings, positions, funds = await _fetch_account_state(client)
    limits = await get_risk_limits()

    day_pnl = sum(p.get("realizedProfit", 0) + p.get("unrealizedProfit", 0) for p in positions)
    total_capital = funds.get("availabelBalance", 0) + funds.get("utilizedAmount", 0)
    day_start_equity = total_capital - day_pnl
    day_pnl_pct = round(day_pnl / day_start_equity * 100, 3) if day_start_equity > 0 else None

    engine = RiskEngine(limits)
    if day_start_equity > 0:
        engine.update_equity(day_start_equity, day_key="baseline")
        engine.update_equity(total_capital, day_key="baseline")
    status = engine.status(total_capital)

    return {
        "total_capital": round(total_capital, 2),
        "day_start_equity": round(day_start_equity, 2),
        "day_pnl": round(day_pnl, 2),
        "day_pnl_pct": day_pnl_pct,
        "open_positions_count": len(positions),
        "limits": limits.model_dump(),
        "kill_switch_active": status["kill_switch_active"],
        "kill_switch_reasons": [
            r for r, active in [
                ("daily loss limit breached", status["daily_kill_switch"]),
                ("max drawdown breached", status["drawdown_kill_switch"]),
            ] if active
        ],
        "note": (
            "Live status is a point-in-time approximation from Dhan's day-scoped "
            "position P&L, not a persisted equity curve — full historical drawdown "
            "and portfolio-heat tracking land with Phase 5 (live strategy engine) "
            "and Phase 8 (scheduler)."
        ),
    }
