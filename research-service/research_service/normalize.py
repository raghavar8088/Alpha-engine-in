"""Normalizes one RSS entry into the shared `Signal` schema. No AI is used here (that's
`ai-service`'s job, e.g. `summarize_news` for sentiment) — this stage does mechanical
symbol detection and stores a neutral placeholder signal (HOLD, confidence 0.5) that
downstream AI/strategy consumers can enrich. Never claims a directional call it didn't
actually derive."""

import re
from datetime import datetime, timezone
from time import mktime

from tradingai_shared.domain import Signal, SignalAction, Timeframe
from tradingai_shared.sectors import SECTOR_MAP

_SYMBOL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in sorted(SECTOR_MAP, key=len, reverse=True)) + r")\b"
)


def detect_symbols(text: str) -> list[str]:
    """Keyword match against the known symbol/index list — a mechanical detector, not
    NLP; misses paraphrased company names (e.g. 'Reliance Industries' vs 'RELIANCE')
    and can't be perfect, but never fabricates a match."""
    return sorted(set(_SYMBOL_PATTERN.findall(text.upper())))


def normalize_entry(entry: dict, source: str) -> Signal:
    title = entry.get("title", "")
    summary = entry.get("summary", "") or entry.get("description", "")
    symbols = detect_symbols(f"{title} {summary}")
    published = entry.get("published_parsed")
    timestamp = (
        datetime.fromtimestamp(mktime(published), tz=timezone.utc)
        if published
        else datetime.now(timezone.utc)
    )
    return Signal(
        symbol=symbols[0] if symbols else "MARKET",
        timeframe=Timeframe.D1,
        signal=SignalAction.HOLD,  # no directional call without AI-derived sentiment
        confidence=0.5,
        source=source,
        timestamp=timestamp,
        reasoning=f"{title} — {summary[:280]}".strip(" —"),
    )
