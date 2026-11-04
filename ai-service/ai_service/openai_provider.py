"""OpenAI behind the same AIProvider contract (Phase 8 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md).

Chat Completions over REST through httpx (already a backend dependency; the openai package is
not installed). Needs OPENAI_API_KEY and OPENAI_MODEL — no model id is assumed; optional
OPENAI_BASE_URL. JSON-schema response format when a schema is given. Untested until a key is
set: the first real call is the check.
"""

import os

import httpx
from tradingai_shared.contracts import AIProvider

from ai_service.provider import ProviderError, ProviderNotConfiguredError, ProviderRefusalError


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    async def complete(
        self, system: str, prompt: str, max_tokens: int = 16000,
        thinking: bool = True, json_schema: dict | None = None, effort: str | None = None,
    ) -> str:
        if not self.configured:
            raise ProviderNotConfiguredError("OPENAI_API_KEY and OPENAI_MODEL must both be set")
        body: dict = {"model": self.model, "max_completion_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "result", "schema": json_schema}}
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
        if r.status_code != 200:
            raise ProviderError(f"OpenAI {r.status_code}: {r.text[:300]}")
        choice = (r.json().get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise ProviderRefusalError(str(message["refusal"])[:300])
        if choice.get("finish_reason") == "length":
            raise ProviderError("the answer was cut off at max_completion_tokens")
        return message.get("content") or ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderNotConfiguredError("embeddings are not wired for OpenAI in this app")
