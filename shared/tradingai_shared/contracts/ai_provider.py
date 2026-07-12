from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Contract for LLM/embedding providers (Phase 6). Anthropic Claude is the default
    implementation; OpenAI/Gemini/Ollama are drop-ins. Model ids come from config —
    never hardcode one."""

    @abstractmethod
    async def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
