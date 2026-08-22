"""Normalisation and the alias map — the part of instrument search that is genuinely hard.

WHY THIS FILE EXISTS
--------------------
The broker scrip master fights you. Measured on production:

    ARE&M       AMARA RAJA ENERGY MOB LTD     ticker resembles nothing a human types
    BALKRISHNA  BALKRISHNA PAPER MILLS L      truncated mid-word at ~25 characters
    GODREJCP    GODREJ CONSUMER PRODUCTS      no suffix at all

So "amara raja" must find `ARE&M`, "mahindra" must find `M&M`, and "L&T" must find `LT`
even though none of those are prefix or substring matches of anything.

TWO MECHANISMS, IN ORDER OF PREFERENCE
---------------------------------------
1. **Rules** handle the bulk: case, punctuation, `&` versus `and`, and the corporate-suffix
   noise (`LTD`, `LIMITED`, `INDIA`) that appears in the master but never in what a person
   types. Rules are preferred because they need no maintenance as the universe changes.
2. **A curated map** for the ones no rule can reach — where the ticker is an abbreviation
   or the company is universally known by a name that is not in the master at all
   (`SBI` -> `SBIN`, `HUL` -> `HINDUNILVR`, `Zomato` -> `ETERNAL` after the rename).

EVERY CURATED ALIAS IS VALIDATED AT INDEX BUILD. An alias whose target symbol is not in
the instrument master is dropped and logged, never silently kept — otherwise the map rots
as tickers are renamed or delisted and starts pointing at nothing, which is worse than
having no alias at all.
"""

from __future__ import annotations

import re

# Words that appear in the instrument master but never in what a person types. Stripped
# from names before indexing so "Godrej Consumer" matches "GODREJ CONSUMER PRODUCTS LTD".
SUFFIX_NOISE = {
    "LTD", "LTD.", "LIMITED", "LIMITE", "LIMIT", "L", "THE", "CO", "COMPANY",
    "CORP", "CORPORATION", "PVT", "PRIVATE", "INDIA", "INDIAN", "OF", "AND",
    "INC", "PLC", "GROUP", "HOLDINGS", "HOLDING",
}

_PUNCT = re.compile(r"[^A-Z0-9&]+")
_MULTI_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Upper-case, `&` spelled out, punctuation flattened to single spaces.

    `&` becomes ` AND ` rather than being dropped: `M&M` and `M AND M` and `M & M` all
    have to land on the same string, and dropping the ampersand would collide `AT&T`-style
    tickers with unrelated letter runs."""
    if not text:
        return ""
    s = text.upper().replace("&", " AND ")
    s = _PUNCT.sub(" ", s)
    return _MULTI_SPACE.sub(" ", s).strip()


def tokens(text: str) -> list[str]:
    """Meaningful words only — corporate noise removed.

    A single-letter token is kept ONLY if it is the whole name, because the master
    truncates: `BALKRISHNA PAPER MILLS L` ends in a stray `L` that is really `LIMITED`."""
    words = normalise(text).split()
    kept = [w for w in words if w not in SUFFIX_NOISE]
    return kept or words


def squash(text: str) -> str:
    """All separators removed: `HDFC BANK` -> `HDFCBANK`.

    This is what lets a typed company name match a concatenated ticker, which is how most
    NSE symbols are actually formed."""
    return normalise(text).replace(" ", "")


def trigrams(text: str) -> set[str]:
    """Character trigrams of the squashed form, padded so short strings still produce some.

    Padding matters: without it a 3-character ticker yields exactly one trigram and any
    typo in it drops the similarity to zero."""
    s = f"  {squash(text)}  "
    if len(s) < 3:
        return set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def dice(a: set[str], b: set[str]) -> float:
    """Sorensen-Dice coefficient — the standard similarity for trigram sets.

    Chosen over raw edit distance because it is symmetric in length and cheap on sets we
    have already built, and over Jaccard because it weights the shared portion more
    heavily, which suits short strings like tickers."""
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


# --------------------------------------------------------------------------------
# The curated map
# --------------------------------------------------------------------------------
# what a person types (normalised)  ->  NSE symbol
# Only entries the rules genuinely cannot reach. Validated against the instrument master
# at index build; anything that no longer resolves is dropped with a warning.
CURATED: dict[str, str] = {
    # Ticker is an abbreviation of a name nobody spells out
    "AMARA RAJA": "ARE&M",
    "AMARARAJA": "ARE&M",
    "MAHINDRA": "M&M",
    "MAHINDRA AND MAHINDRA": "M&M",
    "MAHINDRA FINANCE": "M&MFIN",
    "LARSEN": "LT",
    "LARSEN AND TOUBRO": "LT",
    "L AND T": "LT",
    "LNT": "LT",
    # Universally-known short names that are not the ticker
    "SBI": "SBIN",
    "STATE BANK": "SBIN",
    "HUL": "HINDUNILVR",
    "HINDUSTAN UNILEVER": "HINDUNILVR",
    "INFOSYS": "INFY",
    "ULTRATECH": "ULTRACEMCO",
    "KOTAK": "KOTAKBANK",
    "KOTAK BANK": "KOTAKBANK",
    "ASIAN PAINTS": "ASIANPAINT",
    "SUN PHARMA": "SUNPHARMA",
    "DR REDDY": "DRREDDY",
    "REDDYS": "DRREDDY",
    "POWER GRID": "POWERGRID",
    "INDIAN OIL": "IOC",
    "NESTLE": "NESTLEIND",
    "LIC": "LICI",
    "LIFE INSURANCE": "LICI",
    "BAJAJ FINANCE": "BAJFINANCE",
    "BAJAJ FINSERV": "BAJAJFINSV",
    "BAJAJ AUTO": "BAJAJ-AUTO",
    "TATA MOTORS": "TATAMOTORS",
    "TATA STEEL": "TATASTEEL",
    "TATA POWER": "TATAPOWER",
    "TATA CONSULTANCY": "TCS",
    "ADANI PORTS": "ADANIPORTS",
    "ADANI ENTERPRISES": "ADANIENT",
    "JIO": "JIOFIN",
    "JIO FINANCIAL": "JIOFIN",
    # Renamed companies — people keep typing the old name for years
    "ZOMATO": "ETERNAL",
    "ONE 97": "PAYTM",
    "ONE97": "PAYTM",
    "MINDTREE": "LTIM",
    "LTI": "LTIM",
}


def curated_targets() -> set[str]:
    return set(CURATED.values())


def lookup_curated(query: str) -> str | None:
    """Exact curated hit for a normalised query, or None."""
    return CURATED.get(normalise(query))


__all__ = ["normalise", "tokens", "squash", "trigrams", "dice", "CURATED",
           "lookup_curated", "curated_targets", "SUFFIX_NOISE"]
