# Booming Bulls "Crypto Trading" playlist (PLHqOiFE9RQj8): its strategies as exact rules

The owner asked (8 Nov 2026) to read the playlist's 8 videos, list every strategy, and add them all to the Premium
Strategies module with Rs 10 lakh of paper capital each, without a backtest.

| # | Video | Strategies |
|---|---|---|
| 1 | qPBdLsiEa3s Crypto Trading Full Course | CP-01 to CP-04 (bitcoin), CP-29 (Fear & Greed accumulation) |
| 2 | ngEcBdQxs00 Trading for Beginners roadmap | none (a learning roadmap) |
| 3 | Z0T-OWvruGo Risk Management | money rules only (used as every strategy's defaults) |
| 4 | lYr7pBtCORs Trading Psychology Mistakes | money rules only |
| 5 | ieZ--wMeSxE Order Flow Masterclass | CP-14, CP-15 (bitcoin, real taker delta) |
| 6 | IOBoaM71MUA Liquidity Masterclass | CP-12, CP-13; its previous-day sweep already trades as BB-07 |
| 7 | mb0AeY9YyPg How to Read Charts | CP-01 to CP-03 (gold), CP-05 to CP-10 |
| 8 | 37uPX6Li-xE Complete ICT Guide | CP-16 to CP-28; premium/discount is part of CP-17 and CP-18 |

- `specs/RULES.md`: the readable rules, with E (stated in a video) and A (an assumption where a video was vague).
- `cp_strategies.py`: the exact rules, run by the YouTube study's engine (`../youtube_top20_2026_11/yt_engine.py`).
- `cp_markets.py`: bitcoin from Binance 1-minute klines with the taker-buy volume of each minute, so CP-14 and CP-15 read a
  real order-flow delta (`python -I cp_markets.py fetch 2024-10 2026-10` for research copies; data/ is not in git).
- `cp_checks.py`: the look-ahead (truncation) test. On 40 days of each market, signals computed on data cut at random
  minutes equal the full run's signals already known at that minute: 29 of 29 strategy-market combinations pass
  (gold/silver SMT has no silver minutes in the research data and is checked only through EUR/USD-GBP/USD).

Paper trading: `premium-paper-service` (accounts CP-01..CP-29 in `catalog.py`; `runner.run_cp`; bitcoin and silver feeds
in `feeds.py`). Not backtested, at the owner's request: paper trading from 9 Nov 2026 is their first test.
