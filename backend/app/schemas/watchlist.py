from pydantic import BaseModel, Field


class CreateWatchlistRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class AddSymbolRequest(BaseModel):
    symbol: str
    security_id: str
    exchange_segment: str
