"""TradingAI AI research & trade intelligence (roadmap Phase 6). `AnthropicProvider`
implements the shared `AIProvider` contract; every module in `modules.py` returns an
honest `not_configured` status rather than fabricated text when no API key is set —
see `provider.py`'s docstring."""

from ai_service.provider import AnthropicProvider, ProviderNotConfiguredError, get_provider

__all__ = ["AnthropicProvider", "ProviderNotConfiguredError", "get_provider"]
