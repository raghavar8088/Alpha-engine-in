"""Crypto Trading (2026-11-01): the app's two strategy libraries - the Strategy Factory (546
composed strategies) and the Strategies module (its registry, one variant per declared timeframe) -
backtested, graded and paper traded on the ten largest eligible cryptocurrencies, with an
independent $10,000 paper account for every strategy-cryptocurrency pair.

  config.py     every crypto-specific choice in one place: venue, costs, sessions, windows, limits
  universe.py   the top-10 selection: CoinGecko market cap, minus stablecoins / wrapped / staked /
                tokenised assets, then Delta Exchange India listing, liquidity and history depth
  delta.py      Delta's public REST API: products, tickers, paged candles, funding history
  library.py    one row per strategy (Factory + Strategies module) with its rules and whether, and
                how, it can run on crypto - or why it cannot
  adapters.py   the instrument adapter (one Delta perpetual CONTRACT is the traded unit), the two
                libraries' bar types, the crypto session, the Delta fee card and funding
  backtest.py   one pair's backtest on its strategy's own definition - the Factory's evaluate in a
                corrected no-look-ahead replay, the Strategies module's own BacktestEngine - with
                funding from the venue's history, the no-trade data gate, the Factory's grade
  sweep.py      the batch that backtests every pair (CLI; resumable; runs off the box)
  importer.py   loads a sweep: universe, library, backtests, one $10,000 account per pair
  engine.py     the live paper desk for pairs graded >= 3: signals, fills, stops, funding, limits
  views.py      what the page reads
  store.py      the collections (the box's second MongoDB, like the other new desks)

Nothing here can reach a broker: there is no key, no order path, only public market data.
"""
