"""Stock Screener — momentum, sector rotation and chart patterns over the NSE universe.

See STOCK_SCREENER_MODULE_PLAN.md in the repo root for the full design. In short:

  horizons.py   bar loading, calendar-aware weekly resample, multi-horizon return maths
  momentum.py   the day / week / month / 6-month stock board
  sectors.py    sector rotation, drill-down and driver decomposition
  patterns.py   daily + weekly chart-pattern scan (reuses the commodity detector library)
  reasons.py    the "why is it trending" engine
  plans.py      intraday / swing / breakout trade plans, net of real Angel One costs
  nse_breadth.py  NSE gainers / allIndices / delivery-% capture (enrichment, fails soft)
  chartink.py   optional secondary scan feed, flagged OFF by default
  engine.py     orchestration, snapshots and the cached read paths

THE SPINE IS LOCAL. Momentum, sectors and patterns are computed from `bars_collection` and
`stock_universe_collection`, both of which other modules already keep current. This module
adds essentially no broker load: only the live LTP column calls Angel, and that is the same
batched 50-token sweep Stocks Range already runs.
"""
