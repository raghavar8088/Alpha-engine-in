"""Request bodies for the Trending Stocks module.

Only the basket is user-authored — every other collection in the module is produced by the
engine — so this file is deliberately small. Symbols are normalised to upper case at the
schema boundary rather than in three different places downstream.
"""

from pydantic import BaseModel, Field, field_validator


class AddSymbolRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=40)
    note: str | None = Field(None, max_length=280)

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class SetBasketRequest(BaseModel):
    """Replace the whole basket in one call — what the UI's bulk paste box posts.

    Accepts the messy shapes people actually paste: newlines, commas, or spaces between
    tickers. Rejecting a list because it used the wrong separator would be a worse
    experience than parsing it."""

    symbols: list[str] = Field(default_factory=list, max_length=200)
    raw: str | None = Field(None, max_length=4000)

    def resolved(self) -> list[str]:
        out = [s.strip().upper() for s in self.symbols if s and s.strip()]
        if self.raw:
            for token in self.raw.replace("\n", ",").replace(" ", ",").split(","):
                token = token.strip().upper()
                if token:
                    out.append(token)
        seen: set[str] = set()
        return [s for s in out if not (s in seen or seen.add(s))]


class SweepRequest(BaseModel):
    symbols: list[str] | None = None
    strategy_ids: list[str] | None = None
    # 0 forces a full redo; the default skips rows already refreshed today so a restart
    # continues a sweep rather than beginning it again.
    redo_after_hours: float = 20.0


class ValidateRequest(BaseModel):
    limit: int = 400
    min_base_grade: int = 4
