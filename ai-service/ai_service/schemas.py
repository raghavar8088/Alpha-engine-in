"""JSON Schemas for structured-output completions — every AI module gets a guaranteed-
valid, guaranteed-parseable response shape instead of free text needing regex/fragile
parsing. Field names mirror the roadmap's requirement list (confidence score, risk
score, reasoning) directly."""

TRADE_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string", "description": "Plain-language explanation of why this trade happened"},
        "confidence": {"type": "number", "description": "0-1: how confident the underlying setup looks"},
        "risk_score": {"type": "number", "description": "0-1: how risky this trade is (1 = highest risk)"},
        "reasoning": {"type": "string", "description": "The technical/fundamental reasoning chain behind the score"},
    },
    "required": ["explanation", "confidence", "risk_score", "reasoning"],
    "additionalProperties": False,
}

CHART_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Plain-English read of what this chart is doing right now"},
        "trend": {"type": "string", "enum": ["uptrend", "downtrend", "sideways", "unclear"]},
        "key_observations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific, number-citing observations drawn only from the supplied data",
        },
        "levels_to_watch": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "price": {"type": "number"},
                    "kind": {"type": "string", "enum": ["support", "resistance"]},
                    "why": {"type": "string"},
                },
                "required": ["price", "kind", "why"],
                "additionalProperties": False,
            },
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What would invalidate the read above",
        },
        "confidence": {"type": "number", "description": "0-1: how clear the picture is from the data given"},
    },
    "required": ["summary", "trend", "key_observations", "levels_to_watch", "risks", "confidence"],
    "additionalProperties": False,
}

NEWS_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["bullish", "bearish", "neutral", "mixed"]},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "affected_symbols": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "sentiment", "key_points", "affected_symbols"],
    "additionalProperties": False,
}

STRATEGY_RANKING_SCHEMA = {
    "type": "object",
    "properties": {
        "rankings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "string"},
                    "rank": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": ["strategy_id", "rank", "rationale"],
                "additionalProperties": False,
            },
        },
        "overall_commentary": {"type": "string"},
    },
    "required": ["rankings", "overall_commentary"],
    "additionalProperties": False,
}

UNUSUAL_ACTIVITY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_unusual": {"type": "boolean"},
        "activity_type": {
            "type": "string",
            "enum": ["unusual_volume", "unusual_options_activity", "unusual_oi_buildup", "momentum_spike", "none"],
        },
        "explanation": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["is_unusual", "activity_type", "explanation", "confidence"],
    "additionalProperties": False,
}

TRADE_IDEA_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "direction": {"type": "string", "enum": ["BUY", "SELL"]},
                    "confidence": {"type": "number"},
                    "risk_score": {"type": "number"},
                    "reasoning": {"type": "string"},
                },
                "required": ["symbol", "direction", "confidence", "risk_score", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ideas"],
    "additionalProperties": False,
}

STRATEGY_COMPARISON_SCHEMA = {
    "type": "object",
    "properties": {
        "strengths_a": {"type": "array", "items": {"type": "string"}},
        "strengths_b": {"type": "array", "items": {"type": "string"}},
        "weaknesses_a": {"type": "array", "items": {"type": "string"}},
        "weaknesses_b": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "description": "Which strategy looks stronger and in what conditions"},
    },
    "required": ["strengths_a", "strengths_b", "weaknesses_a", "weaknesses_b", "verdict"],
    "additionalProperties": False,
}
