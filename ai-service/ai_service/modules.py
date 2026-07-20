"""The AI modules from the roadmap: explain every trade, summarize news/earnings, rank
strategies, detect unusual activity, generate trade ideas, compare strategies. Every
function returns `{"status": "ok", ...}` or `{"status": "not_configured", "message": ...}`
— never fabricated content when no API key is set."""

import json

from ai_service.provider import AnthropicProvider, ProviderNotConfiguredError, get_provider
from ai_service.schemas import (
    CHART_EXPLANATION_SCHEMA,
    NEWS_SUMMARY_SCHEMA,
    STRATEGY_COMPARISON_SCHEMA,
    STRATEGY_RANKING_SCHEMA,
    TRADE_EXPLANATION_SCHEMA,
    TRADE_IDEA_SCHEMA,
    UNUSUAL_ACTIVITY_SCHEMA,
)

SYSTEM_QUANT_ANALYST = (
    "You are a quantitative trading analyst for an Indian equities/derivatives desk. "
    "Be precise, cite the specific numbers you were given, and never invent data you "
    "were not given. Respond only with the requested JSON — no prose outside it."
)


async def _run(provider: AnthropicProvider, prompt: str, schema: dict, max_tokens: int = 1024) -> dict:
    try:
        raw = await provider.complete(SYSTEM_QUANT_ANALYST, prompt, max_tokens=max_tokens, json_schema=schema)
        return {"status": "ok", **json.loads(raw)}
    except ProviderNotConfiguredError as exc:
        return {"status": "not_configured", "message": str(exc)}


async def explain_trade(trade: dict, provider: AnthropicProvider | None = None) -> dict:
    """`trade` is a Trade-shaped dict (symbol, direction, entry/exit price, stop_loss,
    target, pnl, exit_reason, strategy_id — whatever's available)."""
    provider = provider or get_provider()
    prompt = f"Explain this trade in plain language, then score it.\n\nTrade data:\n{json.dumps(trade, indent=2)}"
    return await _run(provider, prompt, TRADE_EXPLANATION_SCHEMA)


async def explain_chart(context: dict, provider: AnthropicProvider | None = None) -> dict:
    """Plain-English read of the chart window the user is actually looking at.

    `context` carries the instrument, the resolution, an OHLCV digest of the
    visible window, whichever indicators the user has switched on with their
    current values, and the structural analysis (zones/channel/swings) from
    services.chart_data. Only summarised data is sent, never the full candle
    array — a 2000-bar series would be mostly tokens and no more informative.
    """
    provider = provider or get_provider()
    prompt = (
        "Read this chart for a trader and explain what it is doing. Work only from the "
        "numbers provided — do not assume news, fundamentals, or anything outside this data, "
        "and do not tell the user to buy or sell.\n\n"
        f"Chart context:\n{json.dumps(context, indent=2, default=str)}"
    )
    return await _run(provider, prompt, CHART_EXPLANATION_SCHEMA, max_tokens=1500)


async def summarize_news(articles: list[dict], provider: AnthropicProvider | None = None) -> dict:
    """`articles` is a list of {title, source, published_at, summary/body} dicts —
    e.g. from research-service's RSS ingestion."""
    provider = provider or get_provider()
    body = "\n\n".join(f"[{a.get('source','?')}] {a.get('title','')}\n{a.get('summary') or a.get('body','')}" for a in articles)
    prompt = f"Summarize this batch of market news for a trader. Extract sentiment and affected symbols.\n\n{body}"
    return await _run(provider, prompt, NEWS_SUMMARY_SCHEMA, max_tokens=1500)


async def summarize_earnings(earnings_text: str, symbol: str, provider: AnthropicProvider | None = None) -> dict:
    provider = provider or get_provider()
    prompt = f"Summarize this earnings report/call transcript for {symbol}. Extract sentiment and key points.\n\n{earnings_text}"
    return await _run(provider, prompt, NEWS_SUMMARY_SCHEMA, max_tokens=1500)


async def rank_strategies(strategies: list[dict], provider: AnthropicProvider | None = None) -> dict:
    """`strategies` is a list of {strategy_id, metrics: {...from compute_metrics/
    validate.py...}} dicts."""
    provider = provider or get_provider()
    prompt = (
        "Rank these strategies best-to-worst for a trader deciding what to allocate capital to. "
        "Weigh profit factor, win rate, max drawdown, and Sharpe together — don't just sort by one metric.\n\n"
        f"{json.dumps(strategies, indent=2)}"
    )
    return await _run(provider, prompt, STRATEGY_RANKING_SCHEMA, max_tokens=2000)


async def detect_unusual_activity(symbol: str, market_data: dict, provider: AnthropicProvider | None = None) -> dict:
    """`market_data` might be recent volume/OI/price-change stats — e.g. from
    options-service's chain analytics or a volume z-score."""
    provider = provider or get_provider()
    prompt = (
        f"Given this market data for {symbol}, is there unusual activity (volume spike, "
        f"options OI build-up, momentum ignition)?\n\n{json.dumps(market_data, indent=2)}"
    )
    return await _run(provider, prompt, UNUSUAL_ACTIVITY_SCHEMA)


async def generate_trade_ideas(research_signals: list[dict], provider: AnthropicProvider | None = None) -> dict:
    """`research_signals` are normalized Signal-shaped dicts from research-service."""
    provider = provider or get_provider()
    prompt = (
        "Given these normalized research signals, generate concrete trade ideas with "
        "confidence and risk scores. Only use symbols present in the input.\n\n"
        f"{json.dumps(research_signals, indent=2)}"
    )
    return await _run(provider, prompt, TRADE_IDEA_SCHEMA, max_tokens=2000)


async def compare_strategies(strategy_a: dict, strategy_b: dict, provider: AnthropicProvider | None = None) -> dict:
    provider = provider or get_provider()
    prompt = (
        f"Compare these two strategies' backtest metrics and explain which is stronger and when.\n\n"
        f"Strategy A:\n{json.dumps(strategy_a, indent=2)}\n\nStrategy B:\n{json.dumps(strategy_b, indent=2)}"
    )
    return await _run(provider, prompt, STRATEGY_COMPARISON_SCHEMA, max_tokens=1500)
