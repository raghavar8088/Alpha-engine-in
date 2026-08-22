"""Instrument search — ranked, typo-tolerant, enriched, and app-wide.

Replaces a Mongo `$regex` built from raw user input, which on production returned a 500
for a query of `(` and ranked RPOWER above RELIANCE for `reliance`.

  aliases.py   normalisation rules + the curated map for tickers no rule can reach
  scoring.py   the ranking function — additive, pure, and able to explain itself
  index.py     the in-process index, built at startup and refreshed on a timer
  enrich.py    joins the screener snapshot so a result says whether the desk would trade it
  nlq.py       English -> structured filter; the model translates, it never chooses
  service.py   the three ways in: typed text, nothing at all, or a sentence
"""

from .service import MODE_LEXICAL, MODE_NATURAL, MODE_TRENDING, nl_search, resolve, search, stats, trending

__all__ = ["search", "trending", "nl_search", "resolve", "stats",
           "MODE_LEXICAL", "MODE_NATURAL", "MODE_TRENDING"]
