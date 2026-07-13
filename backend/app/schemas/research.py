from pydantic import BaseModel


class ResearchSignalOut(BaseModel):
    id: str
    symbol: str
    timeframe: str
    signal: str
    confidence: float
    source: str
    timestamp: str
    reasoning: str
    link: str | None = None


class IngestResult(BaseModel):
    counts: dict
