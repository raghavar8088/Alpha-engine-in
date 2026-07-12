from pydantic import BaseModel


class AIStatus(BaseModel):
    configured: bool
    model: str
    note: str


class ExplainTradeRequest(BaseModel):
    trade: dict


class CompareStrategiesRequest(BaseModel):
    strategy_id_a: str
    strategy_id_b: str


class DetectUnusualRequest(BaseModel):
    symbol: str
    market_data: dict


class SummarizeNewsRequest(BaseModel):
    limit: int = 20
    symbol: str | None = None


class VectorSearchRequest(BaseModel):
    query: str
    collection: str = "research_signals"
    limit: int = 5
