"""AnthropicProvider — the AIProvider contract implementation (roadmap Phase 6).

Reads ANTHROPIC_API_KEY from the environment. Never fabricates a response when no key
is configured: `complete()`/`embed()` raise `ProviderNotConfiguredError`, and every
caller in this package catches it and returns an honest `{"status": "not_configured"}`
payload rather than fake text. The moment a key is added to `.env`, everything works
with zero code changes.

Anthropic has no first-party embeddings endpoint (there is none in the Messages API) —
`embed()` always raises, pointing at a third-party embedding provider (e.g. Voyage AI)
as the documented path; `vector-service` is built to accept a pluggable embed function
rather than assuming Anthropic can supply one."""

import os

from anthropic import AsyncAnthropic
from tradingai_shared.contracts import AIProvider

DEFAULT_MODEL = "claude-opus-4-8"  # per Anthropic guidance: always the latest Opus unless told otherwise


class ProviderNotConfiguredError(Exception):
    pass


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = AsyncAnthropic(api_key=self.api_key) if self.api_key else None

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def complete(
        self, system: str, prompt: str, max_tokens: int = 1024,
        thinking: bool = True, json_schema: dict | None = None,
    ) -> str:
        """`thinking=True` requests adaptive thinking — Opus 4.8 does NOT think by
        default; it must be requested explicitly. `json_schema`, when given, uses
        structured outputs (`output_config.format`) so the response is guaranteed-valid
        JSON instead of free text needing fragile parsing."""
        if not self.configured:
            raise ProviderNotConfiguredError("ANTHROPIC_API_KEY not set")

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        if json_schema:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}

        response = await self._client.messages.create(**kwargs)
        return "".join(block.text for block in response.content if block.type == "text")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderNotConfiguredError(
            "Anthropic has no first-party embeddings API — configure a separate "
            "embedding provider (e.g. Voyage AI) and wire it into vector-service"
        )


_default_provider: AnthropicProvider | None = None


def get_provider() -> AnthropicProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = AnthropicProvider()
    return _default_provider
