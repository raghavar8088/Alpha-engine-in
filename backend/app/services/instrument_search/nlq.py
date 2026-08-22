"""Natural-language queries — the model translates, it never chooses.

THE ONE RULE
------------
The language model turns English into a **structured filter**. It does not rank stocks, it
does not pick them, and its output is never shown to you as a recommendation. The filter is
then executed by ordinary deterministic code against the screener's own daily snapshot, and
the filter itself is returned to the caller so the UI can show exactly what was run.

That separation is the whole design. It means a bad model answer produces a visibly wrong
FILTER — which you can see and correct — rather than a plausible-looking list of stocks
with no way to tell how it was chosen. It is also the pattern the published work on
natural-language screening converges on (an intent parser producing a structured query,
executed separately).

PROVIDER-AGNOSTIC ON PURPOSE
-----------------------------
`ai_service.AnthropicProvider` is hardcoded to Anthropic and reports `configured = False`
whenever `ANTHROPIC_API_KEY` is unset — which it is on this deployment, even though Groq,
Mistral, DeepSeek, Cerebras and XAI keys are all present. Rather than leave five working
keys unused, this speaks the OpenAI-compatible chat API that all of them expose, and the
Anthropic Messages API when that key exists.

WHEN NO PROVIDER IS REACHABLE
------------------------------
`parse()` returns `None` with a reason, and the caller falls back to lexical search and
SAYS SO. It never guesses a filter from keywords: a bag-of-words parse that mistakes
"not above 200 DMA" for "above 200 DMA" would silently return the opposite of what was
asked, which is worse than not answering.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

logger = logging.getLogger("instrument_search.nlq")

TIMEOUT_S = float(os.getenv("SEARCH_NLQ_TIMEOUT_S", "12"))

# OpenAI-compatible endpoints, tried in order. Models are env-overridable because vendors
# retire model names far faster than this file will be edited.
PROVIDERS: list[dict] = [
    {"name": "groq", "key": "GROQ_API_KEY", "kind": "openai",
     "url": "https://api.groq.com/openai/v1/chat/completions",
     "model": os.getenv("SEARCH_NLQ_GROQ_MODEL", "llama-3.3-70b-versatile")},
    {"name": "cerebras", "key": "CEREBRAS_API_KEY", "kind": "openai",
     "url": "https://api.cerebras.ai/v1/chat/completions",
     "model": os.getenv("SEARCH_NLQ_CEREBRAS_MODEL", "llama-3.3-70b")},
    {"name": "deepseek", "key": "DEEPSEEK_API_KEY", "kind": "openai",
     "url": "https://api.deepseek.com/chat/completions",
     "model": os.getenv("SEARCH_NLQ_DEEPSEEK_MODEL", "deepseek-chat")},
    {"name": "mistral", "key": "MISTRAL_API_KEY", "kind": "openai",
     "url": "https://api.mistral.ai/v1/chat/completions",
     "model": os.getenv("SEARCH_NLQ_MISTRAL_MODEL", "mistral-small-latest")},
    {"name": "xai", "key": "XAI_API_KEY", "kind": "openai",
     "url": "https://api.x.ai/v1/chat/completions",
     "model": os.getenv("SEARCH_NLQ_XAI_MODEL", "grok-3-mini")},
    {"name": "anthropic", "key": "ANTHROPIC_API_KEY", "kind": "anthropic",
     "url": "https://api.anthropic.com/v1/messages",
     "model": os.getenv("SEARCH_NLQ_ANTHROPIC_MODEL", "claude-sonnet-5")},
]

PREFERRED = os.getenv("SEARCH_NLQ_PROVIDER", "").strip().lower()

FILTER_KEYS = {"sector", "index", "returns", "pct_from_ath", "pct_from_52w_high",
               "turnover_min", "volume_x_min", "up_streak_min", "above_sma",
               "breakout_only", "sort_by", "sort_dir", "limit"}
RETURN_WINDOWS = ("1d", "1w", "1m", "6m")
SORTABLE = set(RETURN_WINDOWS) | {"turnover", "volume_x", "pct_from_ath", "up_streak"}

SYSTEM = """You convert a trader's English request into a JSON filter over an Indian
equity screener. You never choose stocks and you never explain — you emit JSON only.

Available fields:
  sector          one of the sector names given below, or null
  index           "nifty50" | "nifty100" | "nifty250" | "nifty500" | null
  returns         object keyed by "1d","1w","1m","6m"; each {"gte":num} and/or {"lte":num}, percent
  pct_from_ath    {"gte":num,"lte":num} — distance from all-time high, NEGATIVE below it
  pct_from_52w_high  same shape
  turnover_min    rupees, e.g. 500000000 for 50 crore
  volume_x_min    today's volume as a multiple of average, e.g. 2 for "double volume"
  up_streak_min   consecutive up sessions
  above_sma       any of ["20","50","200"]
  breakout_only   true if they asked for breakouts
  sort_by         one of "1d","1w","1m","6m","turnover","volume_x","pct_from_ath","up_streak"
  sort_dir        "desc" or "asc"
  limit           integer, default 20

Rules:
- Omit every field you were not asked about. Do not invent constraints.
- "near its high" means pct_from_ath gte -5. "well below its high" means pct_from_ath lte -20.
- Percentages are numbers, not strings. Crores are 10,000,000 rupees.
- Output a single JSON object and nothing else."""


def available() -> dict | None:
    """The first configured provider, honouring SEARCH_NLQ_PROVIDER if it is set."""
    configured = [p for p in PROVIDERS if os.getenv(p["key"])]
    if not configured:
        return None
    if PREFERRED:
        for p in configured:
            if p["name"] == PREFERRED:
                return p
    return configured[0]


def status() -> dict:
    p = available()
    return {
        "enabled": p is not None,
        "provider": p["name"] if p else None,
        "model": p["model"] if p else None,
        "configured_providers": [x["name"] for x in PROVIDERS if os.getenv(x["key"])],
        "note": ("Natural-language queries are translated into a filter which is shown to "
                 "you and executed deterministically — the model never picks stocks.")
        if p else
        ("No language-model key is configured, so natural-language queries are off and "
         "search stays lexical. No filter is ever guessed from keywords."),
    }


async def _chat(provider: dict, prompt: str) -> str | None:
    key = os.getenv(provider["key"])
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
            if provider["kind"] == "anthropic":
                r = await c.post(provider["url"], headers={
                    "x-api-key": key, "anthropic-version": "2023-06-01",
                    "content-type": "application/json"},
                    json={"model": provider["model"], "max_tokens": 700,
                          "system": SYSTEM,
                          "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                blocks = r.json().get("content") or []
                return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            r = await c.post(provider["url"], headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": provider["model"], "temperature": 0,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception as exc:  # noqa: BLE001 — a provider outage must not break search
        logger.info("[nlq] %s failed: %s", provider["name"], str(exc)[:200])
        return None


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def sanitise(raw: dict, valid_sectors: set[str]) -> dict:
    """Keep only fields we understand, with values in range.

    The model is not trusted to stay inside the schema — an unknown key or an out-of-range
    number is dropped rather than passed to the executor. This is what stops a malformed
    answer from silently becoming a filter that matches everything."""
    out: dict = {}
    for k, v in (raw or {}).items():
        if k not in FILTER_KEYS or v is None:
            continue
        if k == "sector":
            match = next((s for s in valid_sectors if s.lower() == str(v).strip().lower()), None)
            if match:
                out["sector"] = match
        elif k == "index":
            if str(v).lower() in ("nifty50", "nifty100", "nifty250", "nifty500"):
                out["index"] = str(v).lower()
        elif k == "returns" and isinstance(v, dict):
            r = {w: _bounds(v[w]) for w in RETURN_WINDOWS if isinstance(v.get(w), dict)}
            r = {w: b for w, b in r.items() if b}
            if r:
                out["returns"] = r
        elif k in ("pct_from_ath", "pct_from_52w_high") and isinstance(v, dict):
            b = _bounds(v)
            if b:
                out[k] = b
        elif k in ("turnover_min", "volume_x_min", "up_streak_min"):
            if isinstance(v, (int, float)) and v >= 0:
                out[k] = float(v)
        elif k == "above_sma" and isinstance(v, list):
            keep = [str(x) for x in v if str(x) in ("20", "50", "200")]
            if keep:
                out["above_sma"] = keep
        elif k == "breakout_only":
            out["breakout_only"] = bool(v)
        elif k == "sort_by" and str(v) in SORTABLE:
            out["sort_by"] = str(v)
        elif k == "sort_dir" and str(v).lower() in ("asc", "desc"):
            out["sort_dir"] = str(v).lower()
        elif k == "limit" and isinstance(v, (int, float)):
            out["limit"] = max(1, min(100, int(v)))
    return out


def _bounds(d: dict) -> dict:
    out = {}
    for side in ("gte", "lte"):
        v = d.get(side)
        if isinstance(v, (int, float)):
            out[side] = float(v)
    return out


async def parse(query: str, valid_sectors: set[str]) -> tuple[dict | None, str]:
    """English -> filter. Returns (filter, note); filter is None when unavailable."""
    provider = available()
    if provider is None:
        return None, "no language-model key configured"
    text = await _chat(provider, query.strip()[:400])
    raw = _extract_json(text or "")
    if raw is None:
        return None, f"{provider['name']} did not return usable JSON"
    clean = sanitise(raw, valid_sectors)
    if not clean:
        return None, f"{provider['name']} produced no filter this app understands"
    return clean, f"translated by {provider['name']}"


# --------------------------------------------------------------------------------
# Deterministic execution — no model involved past this point
# --------------------------------------------------------------------------------


def apply_filter(rows: list[dict], flt: dict, index_of) -> list[dict]:
    """Run a sanitised filter over screener rows. Pure, ordinary Python, replayable."""
    out = []
    for r in rows:
        if not _row_matches(r, flt, index_of):
            continue
        out.append(r)

    sort_by = flt.get("sort_by")
    if sort_by:
        reverse = flt.get("sort_dir", "desc") == "desc"
        out.sort(key=lambda r: _sort_value(r, sort_by), reverse=reverse)
    return out[: int(flt.get("limit", 20))]


def _sort_value(r: dict, key: str) -> float:
    if key in RETURN_WINDOWS:
        v = (r.get("returns") or {}).get(key)
    else:
        v = r.get(key)
    return float(v) if isinstance(v, (int, float)) else float("-inf")


def _row_matches(r: dict, flt: dict, index_of) -> bool:
    if flt.get("sector") and (r.get("sector") or "").lower() != flt["sector"].lower():
        return False
    if flt.get("index"):
        if flt["index"] not in (index_of(r.get("symbol")) or ()):
            return False
    for window, bounds in (flt.get("returns") or {}).items():
        v = (r.get("returns") or {}).get(window)
        if not isinstance(v, (int, float)) or not _within(v, bounds):
            return False
    for key in ("pct_from_ath", "pct_from_52w_high"):
        if key in flt:
            v = r.get(key)
            if not isinstance(v, (int, float)) or not _within(v, flt[key]):
                return False
    if "turnover_min" in flt:
        v = r.get("turnover")
        if not isinstance(v, (int, float)) or v < flt["turnover_min"]:
            return False
    if "volume_x_min" in flt:
        v = r.get("volume_x")
        if not isinstance(v, (int, float)) or v < flt["volume_x_min"]:
            return False
    if "up_streak_min" in flt:
        v = r.get("up_streak")
        if not isinstance(v, (int, float)) or v < flt["up_streak_min"]:
            return False
    for period in flt.get("above_sma", []):
        ltp, sma = r.get("ltp"), r.get(f"sma{period}")
        if not (isinstance(ltp, (int, float)) and isinstance(sma, (int, float)) and sma):
            return False
        if ltp <= sma:
            return False
    if flt.get("breakout_only") and not r.get("breakout"):
        return False
    return True


def _within(v: float, bounds: dict) -> bool:
    if "gte" in bounds and v < bounds["gte"]:
        return False
    if "lte" in bounds and v > bounds["lte"]:
        return False
    return True


def describe(flt: dict) -> str:
    """The filter in English, so the UI can show what was actually run."""
    bits = []
    if flt.get("index"):
        bits.append(flt["index"].replace("nifty", "Nifty "))
    if flt.get("sector"):
        bits.append(f"{flt['sector']} sector")
    for window, b in (flt.get("returns") or {}).items():
        if "gte" in b:
            bits.append(f"up at least {b['gte']:g}% over {window}")
        if "lte" in b:
            bits.append(f"up at most {b['lte']:g}% over {window}")
    if "pct_from_ath" in flt:
        b = flt["pct_from_ath"]
        if "gte" in b:
            bits.append(f"within {abs(b['gte']):g}% of its all-time high")
        if "lte" in b:
            bits.append(f"more than {abs(b['lte']):g}% below its all-time high")
    if "turnover_min" in flt:
        bits.append(f"turnover over ₹{flt['turnover_min']/1e7:g} crore")
    if "volume_x_min" in flt:
        bits.append(f"volume at least {flt['volume_x_min']:g}x average")
    if "up_streak_min" in flt:
        bits.append(f"{int(flt['up_streak_min'])}+ up sessions in a row")
    for p in flt.get("above_sma", []):
        bits.append(f"above its {p}-day average")
    if flt.get("breakout_only"):
        bits.append("breaking out")
    if flt.get("sort_by"):
        bits.append(f"sorted by {flt['sort_by']} {flt.get('sort_dir', 'desc')}")
    return "; ".join(bits) or "no constraints"


__all__ = ["available", "status", "parse", "apply_filter", "describe", "sanitise",
           "PROVIDERS", "FILTER_KEYS"]
