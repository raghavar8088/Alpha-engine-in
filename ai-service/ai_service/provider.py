"""LLM providers behind one contract (tradingai_shared.contracts.AIProvider): Anthropic Claude by
default, or OpenAI — chosen with AI_PROVIDER=anthropic|openai (Phase 8 of
INTRADAY_STOCKS_AI_UPGRADE_PLAN.md).

Never fabricates a response: with no key configured, `complete()` raises
`ProviderNotConfiguredError` and every caller returns an honest `{"status": "not_configured"}`.
A declined request raises `ProviderRefusalError` and an answer cut off at the token cap raises
`ProviderError` — content is never read from either.

ANTHROPIC (the `anthropic` SDK): model AI_MODEL (default claude-opus-5-5); effort AI_EFFORT
(default medium — current Claude models think adaptively and Opus 5.5 cannot turn thinking off,
so effort is the control); structured outputs through output_config.format; the fixed system
prompt marked for prompt caching; and the server-side refusal fallback (fallbacks="default",
beta server-side-fallback-2026-07-01) on by default — AI_FALLBACKS=off turns it off.
Anthropic has no first-party embeddings endpoint: `embed()` raises, pointing at a separate
embedding provider (e.g. Voyage AI) as the documented path.

OPENAI: ai_service.openai_provider (REST through httpx — no extra dependency). Needs
OPENAI_API_KEY and OPENAI_MODEL; no model id is assumed.
"""

import os

from anthropic import AsyncAnthropic
from tradingai_shared.contracts import AIProvider

DEFAULT_MODEL = os.getenv("AI_MODEL", "claude-opus-5-5")
DEFAULT_EFFORT = os.getenv("AI_EFFORT", "medium")
FALLBACKS = os.getenv("AI_FALLBACKS", "default").strip().lower() not in ("off", "0", "false", "no")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ProviderError(Exception):
    pass


class ProviderNotConfiguredError(ProviderError):
    pass


class ProviderRefusalError(ProviderError):
    pass


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self.effort = effort
        self._client = AsyncAnthropic(api_key=self.api_key) if self.api_key else None

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def complete(
        self, system: str, prompt: str, max_tokens: int = 16000,
        thinking: bool = True, json_schema: dict | None = None, effort: str | None = None,
    ) -> str:
        """`thinking` stays for callers written for older models: current Claude models think
        adaptively (Opus 5.5 cannot turn it off), so adaptive thinking is always sent and
        `effort` sets the depth. `json_schema` gives guaranteed-valid JSON (structured outputs)."""
        if not self.configured:
            raise ProviderNotConfiguredError("ANTHROPIC_API_KEY not set")
        output_config: dict = {"effort": effort or self.effort}
        if json_schema:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }
        if FALLBACKS:
            response = await self._client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            response = await self._client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise ProviderRefusalError(f"declined ({getattr(details, 'category', None) or 'no category'})")
        if response.stop_reason == "max_tokens":
            raise ProviderError("the answer was cut off at max_tokens")
        return "".join(block.text for block in response.content if block.type == "text")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderNotConfiguredError(
            "Anthropic has no first-party embeddings API — configure a separate "
            "embedding provider (e.g. Voyage AI) and wire it into vector-service"
        )


_default_provider: AIProvider | None = None


def get_provider() -> AIProvider:
    """The configured provider: AI_PROVIDER=openai selects OpenAI, anything else Anthropic."""
    global _default_provider
    if _default_provider is None:
        if os.getenv("AI_PROVIDER", "anthropic").strip().lower() == "openai":
            from ai_service.openai_provider import OpenAIProvider
            _default_provider = OpenAIProvider()
        else:
            _default_provider = AnthropicProvider()
    return _default_provider
