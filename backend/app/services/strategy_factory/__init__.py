"""Strategy Factory — 512 composed, rule-based strategies with a hard 1:6 R:R gate.

This package ADDS to the application; it replaces nothing. Every existing desk
(intraday lab, commodity, NIFTY scalp, momentum, options, long-horizon...) keeps its own
catalog and engine untouched. What is new here is a strategy *factory*: strategies are
composed from primitives — setup x confirmations x regime x exit model x timeframe —
rather than hand-written one at a time, and every composition is fingerprinted so the
library cannot fill up with cosmetic variations of one idea.

Layout
------
  primitives.py     market-regime classifier, 1:6 feasibility gate, sizing, cost adapters
  detectors.py      setup detectors (chart / candlestick / structure / indicator)
  confirmations.py  composable confirmation predicates, incl. higher-timeframe trend
  catalog.py        the 64 recipes x 8 timeframes = 512 strategies, with fingerprinting
  engine.py         signal generation, per-strategy Rs10L paper accounts, grading
  backtest.py       no-look-ahead replay with real costs
"""
