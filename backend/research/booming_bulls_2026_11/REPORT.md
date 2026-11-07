# Booming Bulls strategies: backtest report (Phases 7–10)

Pre-registration SHA-256 `6ccca647f41f4f9a9827b9376668677901e45e1b93e1a1823b2f94eb728e1242`. Every number below comes from `results/`, written by `bb_run.py`.

## Summary

**Scope.** The channel has 2,965 public uploads: 1,083 videos, 1,604 Shorts and 278 live streams. Of these, 222 were selected as strategy-related (`catalogue/`).
- **Captions:** extracted with the project's Video Explainer app for 221 of the 222; a 25-second Short had none.
- **Analyses:** the 96 strategy videos (P1) and 13 worked examples (P3) were analysed with timestamps (`analyses/`).
- **Library:** the result is a library of 18 strategies (`specs/LIBRARY.md`). 17 were run on the markets their videos name, or the nearest on disk: Nifty, BankNifty, gold, EURUSD, GBPUSD and the Nasdaq 100. That gives 25 strategy-market books.
- **Rules:** every rule was written down and hash-locked before the first run (`specs/PREREGISTRATION.md`).

**Result: none of the 25 passes. All are "not supported".**
- **Before costs:** the hold-out results are close to zero, between −0.16R and +0.15R a trade.
- **After costs:** spread, slippage, commission and, for Nifty, India's futures charges cost 0.10-0.44R a trade. That makes every book lose.
- **Only BB-06 was positive in development and validation** (+0.31R and +0.46R a trade, 100 trades); it lost in the hold-out (-0.07R, 36 trades).
- **Nearest to break-even:** BB-11 on EURUSD and BB-13 on the Nasdaq. Each was within 0.02R of zero in the hold-out, but both lost in development and validation.

**The Nifty video analysed first (gNoByC3ZEOo, BB-01).** Executed on NIFTY futures:
- **2016-2026:** −0.21R a trade after costs (+0.08R before) over 1,899 trades.
- **Hold-out:** −0.20R from January 2024.
- **Rs 10 lakh account:** Rs 10,00,000 became Rs 504,525 over the hold-out.
- **September 2025:** in the month the video walks through, the same rules made +3.1R before costs and -0.8R after, over 13 trades. The presenter's own count for that month was about +12R.

**What this does and does not show.** The rules as the videos state them, executed mechanically with realistic costs, do not make money on these markets. That does not show the presenter's own discretionary trading has no edge. It does show that the edge, if any, is not in the stated rules. The videos' profit claims remain unverified.

## Verdicts (the chosen variant of each strategy and market)

- **Candidate for paper trading:** 0
- **Needs more evidence:** 0
- **Not supported:** 25 (BB-01 NIFTY, BB-02 NIFTY, BB-03 NIFTY, BB-04 NIFTY, BB-05 BANKNIFTY, BB-06 NIFTY, BB-07 NAS100, BB-07 XAUUSD, BB-08 EURUSD, BB-08 GBPUSD, BB-08 XAUUSD, BB-09 XAUUSD, BB-10 XAUUSD, BB-11 EURUSD, BB-11 GBPUSD, BB-11 XAUUSD, BB-12 XAUUSD, BB-13 NAS100, BB-13 XAUUSD, BB-14 NAS100, BB-16 XAUUSD, BB-17 EURUSD, BB-17 XAUUSD, BB-18 EURUSD, BB-18 GBPUSD)
- **Unable to evaluate:** 0
- **Unable to evaluate (no data):** BB-15 Apple opening-range trap; option P&L of every Nifty strategy (no intraday option prices).

Hold-out tests in the study: 44 (V0 and each chosen variant), Holm-corrected.

## Results (net of costs; R = profit ÷ the risk at entry; 1% of equity risked a trade)

| Strategy | Market | Variant | Dev mean R (n) | Validation mean R (n) | Hold-out mean R (n) | Hold-out t | Hold-out gross R | Win % | PF | Max DD | Class |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| BB-01 Previous-day high/low: breakout, trap, gap fill, retest | NIFTY | V0 | −0.25 (1,054) | −0.10 (348) | −0.20 (497) | −3.23 | +0.10 | 38 | 0.74 | 68.1% | not supported |
| BB-01 Previous-day high/low: breakout, trap, gap fill, retest | NIFTY | R1 (chosen) | −0.20 (1,036) | −0.17 (344) | −0.16 (488) | −2.54 | +0.15 | 39 | 0.79 | 58.2% | not supported |
| BB-02 15-minute opening-range breakout, 5-minute close | NIFTY | V0 | −0.40 (2,385) | −0.23 (769) | −0.37 (1,079) | −8.50 | +0.04 | 34 | 0.59 | 98.5% | not supported |
| BB-02 15-minute opening-range breakout, 5-minute close | NIFTY | S2 (chosen) | −0.36 (2,201) | −0.25 (696) | −0.37 (992) | −11.23 | +0.03 | 48 | 0.47 | 97.8% | not supported |
| BB-03 Nifty + BankNifty synchronised level break | NIFTY | V0 | −0.24 (1,197) | −0.22 (401) | −0.30 (545) | −5.09 | +0.01 | 34 | 0.64 | 83.3% | not supported |
| BB-04 Zone trap with RSI divergence (15m) | NIFTY | V0 | −0.12 (68) | −0.14 (24) | −0.25 (29) | −1.23 | −0.07 | 34 | 0.60 | 10.1% | not supported |
| BB-04 Zone trap with RSI divergence (15m) | NIFTY | R1 (chosen) | −0.09 (311) | −0.06 (92) | −0.10 (154) | −1.10 | +0.06 | 40 | 0.82 | 27.0% | not supported |
| BB-05 SMC structure break into an order block | BANKNIFTY | V0 | −0.33 (2,720) | −0.26 (932) | −0.32 (1,221) | −10.92 | −0.01 | 43 | 0.50 | 98.2% | not supported |
| BB-05 SMC structure break into an order block | BANKNIFTY | S1 (chosen) | −0.34 (2,550) | −0.20 (883) | −0.35 (1,147) | −9.27 | −0.04 | 33 | 0.56 | 98.3% | not supported |
| BB-06 Gap day + first candle through the 15m 200 MA | NIFTY | V0 | +0.31 (76) | +0.46 (24) | −0.07 (36) | −0.34 | +0.12 | 50 | 0.88 | 5.9% | not supported |
| BB-07 Liquidity sweep of previous-day high/low (masterclass) | NAS100 | V0 | −0.17 (1,216) | −0.16 (416) | −0.13 (439) | −2.04 | −0.09 | 31 | 0.81 | 46.0% | not supported |
| BB-07 Liquidity sweep of previous-day high/low (masterclass) | XAUUSD | V0 | −0.23 (1,666) | −0.22 (514) | −0.18 (499) | −3.10 | −0.03 | 30 | 0.74 | 63.1% | not supported |
| BB-07 Liquidity sweep of previous-day high/low (masterclass) | XAUUSD | S1 (chosen) | −0.22 (2,127) | −0.21 (638) | −0.16 (667) | −2.99 | +0.01 | 30 | 0.78 | 69.0% | not supported |
| BB-08 Previous-day high/low 'manipulation' trap after 10:00 IST | EURUSD | V0 | −0.07 (1,757) | −0.21 (525) | −0.11 (518) | −2.14 | +0.04 | 40 | 0.83 | 46.6% | not supported |
| BB-08 Previous-day high/low 'manipulation' trap after 10:00 IST | EURUSD | S3 (chosen) | −0.04 (1,757) | −0.22 (525) | −0.08 (518) | −1.33 | +0.08 | 36 | 0.88 | 37.5% | not supported |
| BB-08 Previous-day high/low 'manipulation' trap after 10:00 IST | GBPUSD | V0 | −0.10 (1,805) | −0.19 (520) | −0.19 (547) | −3.79 | −0.02 | 36 | 0.72 | 69.3% | not supported |
| BB-08 Previous-day high/low 'manipulation' trap after 10:00 IST | GBPUSD | S3 (chosen) | −0.09 (1,805) | −0.17 (520) | −0.20 (547) | −3.45 | −0.03 | 30 | 0.73 | 72.1% | not supported |
| BB-08 Previous-day high/low 'manipulation' trap after 10:00 IST | XAUUSD | V0 | −0.28 (1,578) | −0.23 (481) | −0.26 (466) | −4.90 | −0.06 | 32 | 0.63 | 72.2% | not supported |
| BB-09 Value-area (volume profile) trap | XAUUSD | V0 | −0.19 (2,335) | −0.22 (693) | −0.13 (738) | −2.63 | −0.00 | 33 | 0.81 | 63.7% | not supported |
| BB-09 Value-area (volume profile) trap | XAUUSD | R2 (chosen) | −0.16 (2,312) | −0.22 (688) | −0.15 (700) | −2.99 | −0.02 | 33 | 0.78 | 66.5% | not supported |
| BB-10 Gold 11:30-12:30 IST range sweep | XAUUSD | V0 | −0.44 (2,069) | −0.33 (591) | −0.31 (655) | −6.06 | −0.06 | 25 | 0.61 | 87.6% | not supported |
| BB-11 Forex 10:00 IST range trap | EURUSD | V0 | −0.03 (1,734) | −0.16 (456) | +0.02 (488) | +0.24 | +0.15 | 38 | 1.02 | 22.2% | not supported |
| BB-11 Forex 10:00 IST range trap | EURUSD | S1 (chosen) | −0.03 (1,734) | −0.14 (456) | −0.01 (488) | −0.12 | +0.12 | 34 | 0.99 | 20.6% | not supported |
| BB-11 Forex 10:00 IST range trap | GBPUSD | V0 | −0.09 (1,756) | −0.07 (457) | −0.16 (524) | −2.61 | −0.02 | 31 | 0.79 | 60.8% | not supported |
| BB-11 Forex 10:00 IST range trap | GBPUSD | R1 (chosen) | −0.08 (2,171) | −0.08 (584) | −0.18 (642) | −3.38 | −0.04 | 30 | 0.76 | 71.7% | not supported |
| BB-11 Forex 10:00 IST range trap | XAUUSD | V0 | −0.23 (1,665) | −0.25 (446) | −0.28 (476) | −4.71 | −0.14 | 27 | 0.63 | 74.9% | not supported |
| BB-11 Forex 10:00 IST range trap | XAUUSD | R1 (chosen) | −0.25 (2,022) | −0.19 (563) | −0.30 (582) | −5.55 | −0.16 | 27 | 0.61 | 83.0% | not supported |
| BB-12 400 EMA trap (15m) | XAUUSD | V0 | −0.11 (626) | −0.22 (201) | −0.19 (172) | −2.34 | −0.09 | 34 | 0.68 | 34.4% | not supported |
| BB-13 'Prop-firm' inside-body breakout | NAS100 | V0 | −0.24 (1,729) | −0.14 (535) | −0.01 (540) | −0.26 | +0.03 | 50 | 0.98 | 32.4% | not supported |
| BB-13 'Prop-firm' inside-body breakout | NAS100 | R1 (chosen) | −0.17 (1,729) | −0.10 (535) | +0.01 (540) | +0.26 | +0.04 | 51 | 1.02 | 27.2% | not supported |
| BB-13 'Prop-firm' inside-body breakout | XAUUSD | V0 | −0.30 (1,632) | −0.20 (481) | −0.12 (501) | −2.58 | +0.05 | 46 | 0.79 | 48.5% | not supported |
| BB-13 'Prop-firm' inside-body breakout | XAUUSD | R1 (chosen) | −0.26 (1,632) | −0.15 (481) | −0.10 (501) | −2.23 | +0.02 | 46 | 0.82 | 45.5% | not supported |
| BB-14 Inside candle with the poke filter | NAS100 | V0 | −0.28 (2,735) | −0.10 (983) | −0.08 (1,100) | −2.14 | −0.02 | 37 | 0.88 | 63.0% | not supported |
| BB-14 Inside candle with the poke filter | NAS100 | R1 (chosen) | −0.15 (2,423) | −0.09 (868) | −0.05 (975) | −1.38 | −0.02 | 40 | 0.91 | 45.9% | not supported |
| BB-16 Retracement-zone (Fibonacci 50-61.8%) sweep | XAUUSD | V0 | −0.35 (789) | −0.39 (231) | −0.25 (256) | −2.47 | −0.03 | 25 | 0.70 | 51.6% | not supported |
| BB-16 Retracement-zone (Fibonacci 50-61.8%) sweep | XAUUSD | S2 (chosen) | −0.33 (789) | −0.32 (231) | −0.20 (256) | −2.13 | +0.01 | 30 | 0.74 | 44.6% | not supported |
| BB-17 Order-block 50% trap | EURUSD | V0 | −0.12 (5,000) | −0.14 (1,394) | −0.20 (1,503) | −5.50 | −0.02 | 31 | 0.75 | 95.8% | not supported |
| BB-17 Order-block 50% trap | EURUSD | S1 (chosen) | −0.10 (4,968) | −0.10 (1,381) | −0.20 (1,497) | −5.59 | −0.05 | 31 | 0.74 | 96.2% | not supported |
| BB-17 Order-block 50% trap | XAUUSD | V0 | −0.39 (4,909) | −0.33 (1,366) | −0.30 (1,474) | −8.94 | −0.03 | 26 | 0.62 | 99.1% | not supported |
| BB-17 Order-block 50% trap | XAUUSD | S1 (chosen) | −0.36 (4,891) | −0.23 (1,362) | −0.19 (1,461) | −5.41 | +0.01 | 29 | 0.74 | 95.0% | not supported |
| BB-18 15m 200 EMA breakout-retest | EURUSD | V0 | −0.11 (745) | −0.16 (242) | −0.12 (274) | −1.43 | +0.03 | 34 | 0.83 | 30.5% | not supported |
| BB-18 15m 200 EMA breakout-retest | EURUSD | S1 (chosen) | −0.07 (745) | −0.11 (242) | −0.09 (274) | −0.88 | +0.07 | 28 | 0.89 | 29.6% | not supported |
| BB-18 15m 200 EMA breakout-retest | GBPUSD | V0 | −0.19 (731) | +0.01 (240) | −0.15 (252) | −1.73 | +0.01 | 32 | 0.80 | 36.6% | not supported |
| BB-18 15m 200 EMA breakout-retest | GBPUSD | S1 (chosen) | −0.15 (731) | +0.08 (240) | −0.14 (252) | −1.35 | +0.02 | 26 | 0.82 | 35.2% | not supported |

## Robustness (hold-out mean R under each stress; V0 and the chosen variant)

| Strategy | Market | Variant | Base | Gross (no costs) | Costs ×2 | Slippage ×3 | Entry 1 min late | Entry 1 bar late | Target −0.5R | Target +0.5R |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BB-01 | NIFTY | V0 | −0.20 | +0.12 | −0.47 | −0.26 | −0.21 | −0.36 | −0.24 | −0.15 |
| BB-01 | NIFTY | R1 | −0.16 | +0.15 | −0.44 | −0.23 | −0.19 | −0.49 | −0.18 | −0.14 |
| BB-02 | NIFTY | V0 | −0.37 | +0.04 | −0.74 | −0.49 | −0.42 | −0.94 | −0.34 | −0.39 |
| BB-02 | NIFTY | S2 | −0.37 | +0.02 | −0.71 | −0.43 | −0.45 | −0.97 | −0.38 | −0.34 |
| BB-03 | NIFTY | V0 | −0.30 | +0.05 | −0.59 | −0.37 | −0.30 | −0.38 | −0.26 | −0.27 |
| BB-04 | NIFTY | V0 | −0.25 | −0.07 | −0.41 | −0.28 | −0.24 | −0.40 | −0.25 | −0.20 |
| BB-04 | NIFTY | R1 | −0.10 | +0.06 | −0.26 | −0.15 | −0.13 | −0.15 | −0.11 | −0.09 |
| BB-05 | BANKNIFTY | V0 | −0.32 | −0.02 | −0.60 | −0.41 | −0.34 | −0.43 | −0.32 | −0.31 |
| BB-05 | BANKNIFTY | S1 | −0.35 | −0.04 | −0.62 | −0.43 | −0.34 | −0.44 | −0.33 | −0.32 |
| BB-06 | NIFTY | V0 | −0.07 | +0.12 | −0.24 | −0.10 | −0.15 | −1.17 | −0.10 | −0.15 |
| BB-07 | NAS100 | V0 | −0.13 | −0.06 | −0.17 | −0.14 | −0.13 | −0.17 | −0.06 | −0.20 |
| BB-07 | XAUUSD | V0 | −0.18 | −0.02 | −0.33 | −0.25 | −0.20 | −0.24 | −0.19 | −0.19 |
| BB-07 | XAUUSD | S1 | −0.16 | +0.00 | −0.29 | −0.22 | −0.21 | −0.22 | −0.18 | −0.16 |
| BB-08 | EURUSD | V0 | −0.11 | +0.01 | −0.25 | −0.15 | −0.14 | −0.25 | −0.11 | −0.08 |
| BB-08 | EURUSD | S3 | −0.08 | +0.07 | −0.28 | −0.17 | −0.13 | −0.25 | −0.11 | −0.17 |
| BB-08 | GBPUSD | V0 | −0.19 | −0.02 | −0.34 | −0.26 | −0.23 | −0.30 | −0.16 | −0.20 |
| BB-08 | GBPUSD | S3 | −0.20 | −0.01 | −0.36 | −0.27 | −0.24 | −0.33 | −0.19 | −0.24 |
| BB-08 | XAUUSD | V0 | −0.26 | −0.07 | −0.44 | −0.34 | −0.28 | −0.48 | −0.25 | −0.28 |
| BB-09 | XAUUSD | V0 | −0.13 | +0.01 | −0.25 | −0.18 | −0.14 | −0.16 | −0.11 | −0.15 |
| BB-09 | XAUUSD | R2 | −0.15 | −0.04 | −0.25 | −0.19 | −0.16 | −0.18 | −0.13 | −0.13 |
| BB-10 | XAUUSD | V0 | −0.31 | −0.08 | −0.54 | −0.43 | −0.37 | −0.48 | −0.32 | −0.34 |
| BB-11 | EURUSD | V0 | +0.02 | +0.14 | −0.11 | −0.03 | +0.03 | −0.29 | −0.02 | +0.02 |
| BB-11 | EURUSD | S1 | −0.01 | +0.11 | −0.12 | −0.04 | +0.03 | −0.30 | −0.02 | +0.01 |
| BB-11 | GBPUSD | V0 | −0.16 | −0.00 | −0.27 | −0.20 | −0.16 | −0.26 | −0.15 | −0.17 |
| BB-11 | GBPUSD | R1 | −0.18 | −0.02 | −0.30 | −0.22 | −0.19 | −0.26 | −0.16 | −0.19 |
| BB-11 | XAUUSD | V0 | −0.28 | −0.17 | −0.37 | −0.32 | −0.28 | −0.30 | −0.26 | −0.25 |
| BB-11 | XAUUSD | R1 | −0.30 | −0.20 | −0.38 | −0.33 | −0.30 | −0.29 | −0.29 | −0.28 |
| BB-12 | XAUUSD | V0 | −0.19 | −0.03 | −0.26 | −0.22 | −0.15 | −0.13 | −0.16 | −0.14 |
| BB-13 | NAS100 | V0 | −0.01 | +0.01 | −0.06 | −0.03 | −0.05 | −0.01 | −0.05 | +0.01 |
| BB-13 | NAS100 | R1 | +0.01 | +0.04 | −0.02 | −0.01 | −0.01 | −0.04 | −0.03 | −0.03 |
| BB-13 | XAUUSD | V0 | −0.12 | +0.01 | −0.30 | −0.19 | −0.11 | −0.25 | −0.13 | −0.12 |
| BB-13 | XAUUSD | R1 | −0.10 | +0.03 | −0.21 | −0.15 | −0.07 | −0.14 | −0.08 | −0.09 |
| BB-14 | NAS100 | V0 | −0.08 | −0.01 | −0.13 | −0.11 | −0.11 | −0.12 | −0.08 | −0.06 |
| BB-14 | NAS100 | R1 | −0.05 | −0.03 | −0.06 | −0.06 | −0.05 | −0.04 | −0.06 | −0.02 |
| BB-16 | XAUUSD | V0 | −0.25 | −0.04 | −0.50 | −0.36 | −0.26 | −0.35 | −0.20 | −0.31 |
| BB-16 | XAUUSD | S2 | −0.20 | −0.03 | −0.49 | −0.34 | −0.25 | −0.38 | −0.26 | −0.25 |
| BB-17 | EURUSD | V0 | −0.20 | −0.04 | −0.35 | −0.23 | −0.21 | −0.28 | −0.20 | −0.19 |
| BB-17 | EURUSD | S1 | −0.20 | −0.06 | −0.34 | −0.24 | −0.21 | −0.21 | −0.18 | −0.20 |
| BB-17 | XAUUSD | V0 | −0.30 | +0.03 | −0.48 | −0.38 | −0.28 | −0.61 | −0.26 | −0.27 |
| BB-17 | XAUUSD | S1 | −0.19 | −0.02 | −0.37 | −0.28 | −0.19 | −0.26 | −0.21 | −0.23 |
| BB-18 | EURUSD | V0 | −0.12 | +0.00 | −0.26 | −0.14 | −0.12 | −0.26 | −0.17 | −0.07 |
| BB-18 | EURUSD | S1 | −0.09 | +0.06 | −0.25 | −0.11 | −0.04 | −0.18 | −0.07 | −0.07 |
| BB-18 | GBPUSD | V0 | −0.15 | +0.01 | −0.26 | −0.19 | −0.20 | −0.15 | −0.09 | −0.18 |
| BB-18 | GBPUSD | S1 | −0.14 | −0.01 | −0.32 | −0.26 | −0.19 | −0.22 | −0.18 | −0.17 |

## After each video was published (the only span the presenter could not have seen)

| Strategy | Market | Variant | From | Trades | Mean R | t |
|---|---|---|---|---:|---:|---:|
| BB-01 | NIFTY | V0 | 2025-10-04 | 197 | −0.23 | −2.29 |
| BB-01 | NIFTY | R1 | 2025-10-04 | 198 | −0.31 | −3.17 |
| BB-02 | NIFTY | V0 | 2026-05-26 | 161 | −0.76 | −6.95 |
| BB-02 | NIFTY | S2 | 2026-05-26 | 152 | −0.74 | −9.02 |
| BB-03 | NIFTY | V0 | 2023-01-01 | 745 | −0.30 | −5.86 |
| BB-04 | NIFTY | V0 | 2021-01-01 | 63 | −0.24 | −1.96 |
| BB-04 | NIFTY | R1 | 2021-01-01 | 306 | −0.14 | −2.36 |
| BB-05 | BANKNIFTY | V0 | 2023-08-21 | 1,393 | −0.31 | −11.17 |
| BB-05 | BANKNIFTY | S1 | 2023-08-21 | 1,312 | −0.32 | −9.16 |
| BB-06 | NIFTY | V0 | 2023-01-01 | 49 | +0.00 | +0.01 |
| BB-07 | NAS100 | V0 | 2026-10-01 | 3 | −1.01 | −514.61 |
| BB-07 | XAUUSD | V0 | 2026-10-01 | 6 | −0.24 | −0.47 |
| BB-07 | XAUUSD | S1 | 2026-10-01 | 8 | −0.06 | −0.13 |
| BB-08 | EURUSD | V0 | 2024-01-01 | 431 | −0.09 | −1.61 |
| BB-08 | EURUSD | S3 | 2024-01-01 | 431 | −0.05 | −0.77 |
| BB-08 | GBPUSD | V0 | 2024-01-01 | 458 | −0.16 | −2.83 |
| BB-08 | GBPUSD | S3 | 2024-01-01 | 458 | −0.19 | −2.94 |
| BB-08 | XAUUSD | V0 | 2024-01-01 | 390 | −0.26 | −4.56 |
| BB-09 | XAUUSD | V0 | 2026-06-02 | 82 | −0.28 | −1.90 |
| BB-09 | XAUUSD | R2 | 2026-06-02 | 85 | −0.35 | −2.56 |
| BB-10 | XAUUSD | V0 | 2025-01-01 | 356 | −0.31 | −4.56 |
| BB-11 | EURUSD | V0 | 2025-12-01 | 125 | −0.06 | −0.44 |
| BB-11 | EURUSD | S1 | 2025-12-01 | 125 | −0.08 | −0.67 |
| BB-11 | GBPUSD | V0 | 2025-12-01 | 131 | −0.19 | −1.60 |
| BB-11 | GBPUSD | R1 | 2025-12-01 | 155 | −0.28 | −2.66 |
| BB-11 | XAUUSD | V0 | 2025-12-01 | 110 | −0.34 | −2.54 |
| BB-11 | XAUUSD | R1 | 2025-12-01 | 141 | −0.34 | −2.97 |
| BB-12 | XAUUSD | V0 | 2025-01-01 | 89 | −0.35 | −3.21 |
| BB-13 | NAS100 | V0 | 2025-12-01 | 153 | −0.11 | −1.34 |
| BB-13 | NAS100 | R1 | 2025-12-01 | 153 | −0.04 | −0.48 |
| BB-13 | XAUUSD | V0 | 2025-12-01 | 133 | −0.14 | −1.63 |
| BB-13 | XAUUSD | R1 | 2025-12-01 | 133 | −0.08 | −0.94 |
| BB-14 | NAS100 | V0 | 2025-01-01 | 594 | −0.04 | −0.77 |
| BB-14 | NAS100 | R1 | 2025-01-01 | 529 | −0.06 | −1.18 |
| BB-16 | XAUUSD | V0 | 2026-07-01 | 24 | −0.73 | −1.43 |
| BB-16 | XAUUSD | S2 | 2026-07-01 | 24 | −0.64 | −1.27 |
| BB-17 | EURUSD | V0 | 2026-05-01 | 205 | −0.18 | −1.86 |
| BB-17 | EURUSD | S1 | 2026-05-01 | 203 | −0.13 | −1.30 |
| BB-17 | XAUUSD | V0 | 2026-05-01 | 197 | −0.25 | −2.65 |
| BB-17 | XAUUSD | S1 | 2026-05-01 | 196 | −0.15 | −1.57 |
| BB-18 | EURUSD | V0 | 2023-01-01 | 274 | −0.12 | −1.43 |
| BB-18 | EURUSD | S1 | 2023-01-01 | 274 | −0.09 | −0.88 |
| BB-18 | GBPUSD | V0 | 2023-01-01 | 252 | −0.15 | −1.73 |
| BB-18 | GBPUSD | S1 | 2023-01-01 | 252 | −0.14 | −1.35 |

## Walk-forward (each year trades the variant with the best record in all earlier years)

| Strategy | Market | Out-of-sample trades | Mean R | t | Picks by year |
|---|---|---:|---:|---:|---|
| BB-01 | NIFTY | 1,358 | −0.15 | −4.08 | 2019:R1, 2020:R1, 2021:R1, 2022:R1, 2023:R1, 2024:R1, 2025:R1, 2026:R1 |
| BB-02 | NIFTY | 2,928 | −0.35 | −13.02 | 2019:S2, 2020:S2, 2021:S3, 2022:S2, 2023:S3, 2024:S2, 2025:S3, 2026:S3 |
| BB-03 | NIFTY | 1,384 | −0.24 | −6.47 | 2019:V0, 2020:V0, 2021:V0, 2022:R1, 2023:V0, 2024:V0, 2025:V0, 2026:V0 |
| BB-04 | NIFTY | 332 | −0.14 | −2.50 | 2019:V0, 2020:V0, 2021:R1, 2022:R1, 2023:R1, 2024:R1, 2025:R1, 2026:R1 |
| BB-05 | BANKNIFTY | 3,437 | −0.30 | −15.64 | 2019:V0, 2020:V0, 2021:V0, 2022:V0, 2023:V0, 2024:S1, 2025:S1, 2026:V0 |
| BB-06 | NIFTY | 94 | +0.07 | +0.57 | 2019:V0, 2020:V0, 2021:V0, 2022:V0, 2023:V0, 2024:V0, 2025:V0, 2026:V0 |
| BB-07 | NAS100 | 1,793 | −0.16 | −5.28 | 2013:V0, 2014:V0, 2015:V0, 2016:V0, 2017:V0, 2018:V0, 2019:V0, 2020:V0, 2021:V0, 2022:V0, 2023:V0, 2024:V0, 2025:V0, 2026:V0 |
| BB-07 | XAUUSD | 2,850 | −0.19 | −7.79 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:S1, 2017:S1, 2018:S1, 2019:S1, 2020:S1, 2021:S1, 2022:S1, 2023:S1, 2024:S1, 2025:S1, 2026:S1 |
| BB-08 | EURUSD | 2,331 | −0.10 | −3.28 | 2012:S3, 2013:S3, 2014:V0, 2015:S3, 2016:S2, 2017:S2, 2018:S2, 2019:S2, 2020:S2, 2021:S2, 2022:S2, 2023:S3, 2024:S3, 2025:S3, 2026:S3 |
| BB-08 | GBPUSD | 2,358 | −0.14 | −5.17 | 2012:S1, 2013:S1, 2014:S1, 2015:S2, 2016:S3, 2017:S3, 2018:S3, 2019:S2, 2020:S2, 2021:S3, 2022:S3, 2023:S3, 2024:S3, 2025:S3, 2026:S3 |
| BB-08 | XAUUSD | 2,074 | −0.29 | −10.55 | 2012:V0, 2013:S3, 2014:S3, 2015:S3, 2016:S3, 2017:S3, 2018:S3, 2019:S3, 2020:S3, 2021:S3, 2022:S3, 2023:V0, 2024:V0, 2025:V0, 2026:V0 |
| BB-09 | XAUUSD | 3,087 | −0.18 | −7.94 | 2012:R2, 2013:R2, 2014:R2, 2015:R2, 2016:R2, 2017:R2, 2018:R2, 2019:R2, 2020:R2, 2021:R1, 2022:R2, 2023:R2, 2024:R2, 2025:R1, 2026:R2 |
| BB-10 | XAUUSD | 2,814 | −0.41 | −16.92 | 2012:R1, 2013:R1, 2014:R1, 2015:R1, 2016:R1, 2017:R1, 2018:V0, 2019:V0, 2020:R1, 2021:V0, 2022:R1, 2023:V0, 2024:V0, 2025:V0, 2026:V0 |
| BB-11 | EURUSD | 2,266 | −0.08 | −2.69 | 2012:S1, 2013:S1, 2014:R1, 2015:V0, 2016:R1, 2017:V0, 2018:V0, 2019:V0, 2020:V0, 2021:V0, 2022:V0, 2023:S1, 2024:V0, 2025:V0, 2026:V0 |
| BB-11 | GBPUSD | 2,579 | −0.11 | −4.14 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:V0, 2017:R1, 2018:V0, 2019:R1, 2020:R1, 2021:R1, 2022:R1, 2023:R1, 2024:R1, 2025:R1, 2026:R1 |
| BB-11 | XAUUSD | 2,212 | −0.25 | −9.07 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:S1, 2017:V0, 2018:S1, 2019:V0, 2020:V0, 2021:V0, 2022:R1, 2023:R1, 2024:R1, 2025:V0, 2026:V0 |
| BB-12 | XAUUSD | 825 | −0.16 | −4.25 | 2012:S1, 2013:V0, 2014:S1, 2015:S1, 2016:V0, 2017:V0, 2018:V0, 2019:V0, 2020:V0, 2021:V0, 2022:V0, 2023:V0, 2024:V0, 2025:V0, 2026:V0 |
| BB-13 | NAS100 | 2,387 | −0.11 | −5.47 | 2013:R1, 2014:R1, 2015:R1, 2016:R1, 2017:R1, 2018:R1, 2019:R1, 2020:R1, 2021:R1, 2022:R1, 2023:R1, 2024:R1, 2025:R1, 2026:R1 |
| BB-13 | XAUUSD | 2,180 | −0.20 | −9.62 | 2012:R1, 2013:R1, 2014:R1, 2015:R1, 2016:R1, 2017:R1, 2018:R1, 2019:R1, 2020:R1, 2021:R1, 2022:R1, 2023:R1, 2024:R1, 2025:R1, 2026:R1 |
| BB-14 | NAS100 | 3,748 | −0.12 | −6.27 | 2013:R1, 2014:R1, 2015:R1, 2016:R1, 2017:R1, 2018:R1, 2019:R1, 2020:R1, 2021:R1, 2022:R1, 2023:R1, 2024:R1, 2025:R1, 2026:R1 |
| BB-16 | XAUUSD | 1,080 | −0.32 | −7.94 | 2012:S2, 2013:S2, 2014:S2, 2015:S2, 2016:S2, 2017:S2, 2018:S2, 2019:S2, 2020:S2, 2021:S2, 2022:S2, 2023:S2, 2024:S2, 2025:S2, 2026:S2 |
| BB-17 | EURUSD | 6,501 | −0.13 | −7.13 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:S1, 2017:S1, 2018:S1, 2019:S1, 2020:S1, 2021:S1, 2022:S1, 2023:S1, 2024:S1, 2025:S1, 2026:S1 |
| BB-17 | XAUUSD | 6,409 | −0.29 | −17.59 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:S1, 2017:S1, 2018:S1, 2019:S1, 2020:S1, 2021:S1, 2022:S1, 2023:S1, 2024:S1, 2025:S1, 2026:S1 |
| BB-18 | EURUSD | 1,092 | −0.10 | −1.90 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:S1, 2017:S1, 2018:S1, 2019:S1, 2020:S1, 2021:S1, 2022:S1, 2023:S1, 2024:S1, 2025:S1, 2026:S1 |
| BB-18 | GBPUSD | 1,052 | −0.13 | −2.59 | 2012:S1, 2013:S1, 2014:S1, 2015:S1, 2016:S1, 2017:S1, 2018:S1, 2019:S1, 2020:S1, 2021:S1, 2022:S1, 2023:S1, 2024:S1, 2025:S1, 2026:S1 |

## A ₹10 lakh account on NIFTY futures, hold-out only (whole lots of 65, 1% risk, 12% margin a lot)

| Strategy | Variant | Start | End | Return | Max drawdown | Trades | Skipped (0 lots) |
|---|---|---:|---:|---:|---:|---:|---:|
| BB-01 | V0 | ₹1,000,000 | ₹504,525 | −49.5% | 52.5% | 477 | 20 |
| BB-01 | R1 | ₹1,000,000 | ₹540,621 | −45.9% | 48.0% | 479 | 9 |
| BB-02 | V0 | ₹1,000,000 | ₹179,218 | −82.1% | 83.9% | 902 | 177 |
| BB-02 | S2 | ₹1,000,000 | ₹175,540 | −82.4% | 83.2% | 871 | 121 |
| BB-03 | V0 | ₹1,000,000 | ₹330,537 | −66.9% | 68.6% | 536 | 9 |
| BB-04 | V0 | ₹1,000,000 | ₹949,674 | −5.0% | 7.1% | 27 | 2 |
| BB-04 | R1 | ₹1,000,000 | ₹900,871 | −9.9% | 20.5% | 144 | 10 |
| BB-06 | V0 | ₹1,000,000 | ₹971,798 | −2.8% | 5.2% | 31 | 5 |

Rupee figures use today's lot of 65 for every year. NIFTY's lot size changed several times over the decade, and the R figures do not depend on it.

## Verification (Phase 5)

- **Engine unit tests:** 12 of 12 pass (next-minute fills at the ask/bid plus slippage, stop first, gap fills at the open, breakeven, partials, forced exits, rejections).
- **Look-ahead truncation test:** 75 of 75 strategy-market-variant combinations give identical signals before three random cut points.
- **Fidelity, BB-01 against the video's own September 2025 replay:** the video trades 15 of 22 days; our rules trade 13. Both trade on 12 days and both stand aside on 6. The setup family matches on 7 of 12, and the direction matches on 9 of 10 days where he states it. Our retest stops are tighter than his (about 13 vs 23–25 points). No rule was changed after this comparison.

## Data (Phase 6)

| Market | Days | First | Last | Excluded days (feed defect) | Median half-spread |
|---|---:|---|---|---:|---:|
| NIFTY | 2,639 | 2016-01-01 | 2026-10-23 | 0 | 0 |
| BANKNIFTY | 2,630 | 2016-01-01 | 2026-10-09 | 0 | 0 |
| XAUUSD | 4,543 | 2009-03-16 | 2026-10-16 | 128 | 0.1775 |
| EURUSD | 4,622 | 2009-01-02 | 2026-10-16 | 129 | 1e-05 |
| GBPUSD | 4,621 | 2009-01-02 | 2026-10-16 | 128 | 2e-05 |
| NAS100 | 3,837 | 2010-11-15 | 2026-10-16 | 0 | 0.5 |

## Limitations

- **Options are not evaluated.** The Nifty videos (BB-01 to BB-04) teach buying calls and puts. No intraday option prices are on disk, so the signals were traded on futures instead. An option version would differ: premium decay, wider spreads and a non-linear payoff. It cannot be inferred from the index.
- **Futures at the index price.** No intraday NIFTY/BANKNIFTY futures minutes exist, so fills use the index plus 1 point (BankNifty 3 points) of slippage a side, with Angel One's full futures charges. Intraday basis changes are ignored.
- **Volume proxy.** The value-area profile (BB-09) uses Dukascopy's hourly tick volume spread over each hour's minutes, not the broker volume TradingView shows.
- **Spot gold, forex and Nasdaq:**
  - Gold uses HistData minutes, which are Dukascopy's bid, with Dukascopy's quoted spread.
  - EURUSD, GBPUSD and NAS100 use fixed modelled spreads.
  - February-July 2023 is excluded for all four (HistData thinned the feed).
- **Markets blocked on data.** Dukascopy throttled the US30 and Apple download (HTTP 503), so:
  - BB-15 (Apple) is unevaluated;
  - BB-12 ran on gold only;
  - BB-14 ran on the Nasdaq 100 (the video's own "homework" market) instead of US30.
- **Rule fidelity.** Discretionary words ("big candle", "good candle", "with space", "logical stop") had to be fixed as numbers; every such choice is tagged A in the pre-registration.
  - The BB-01 check against the video's own September 2025 replay matched 12 of his 15 trade days and 9 of the 10 directions he states. Our retest stops were tighter than his.
  - BB-03 to BB-06 and BB-16 to BB-18 rest mostly on my definitions (low fidelity).
- **Video coverage:**
  - The 113 concept videos (P2) were transcribed but not analysed one by one.
  - 2020-2022 auto-captions are badly garbled.
  - No video frames were analysed (the app's media download needs the owner's approval), and Whisper is not installed. On-screen-only details, such as the strike table at 05:15 of gNoByC3ZEOo, were not read.
- **Multiple testing.** 44 hold-out tests were run and Holm-corrected. With none positive and significant, the correction did not change any verdict.

## Reproduce

From `backend/research/booming_bulls_2026_11/`, Python 3.12 with numpy and pandas, always run with `python -I`.
- **Steps 1-6** (catalogue and transcripts): in the README.
- **Steps 7-11:**

| Step | Command | Does |
|---|---|---|
| 7 | `python -I bb_markets.py` | Builds `data/cache/*.npz` from the earlier studies' minute data and writes `results/data_quality.json` |
| 8 | `python -I bb_checks.py` | Engine unit tests, look-ahead truncation test, BB-01 fidelity check -> `results/checks.json` |
| 9 | `python -I bb_run.py` | All strategies, variants and robustness runs -> `results/runs/`, `results/trades/`, `results/equity/` |
| 10 | `python -I bb_run.py --summary` | Opens the hold-out, applies Holm and the gates -> `results/summary.json` |
| 11 | `python -I bb_report.py` | This file |

## Next steps

1. **Do not paper-trade or arm any of these rule sets.** None passed the pre-registered gates, and live trading was out of scope.
2. **Test the option-buying versions** of BB-01 to BB-04 only with real intraday option prices (Angel or Dhan candles for live contracts, recorded forward). Results should not be inferred from the index.
3. **Re-run the frozen rules on new data in 6-12 months,** without re-tuning, for the three near-zero books: BB-06, BB-11 EURUSD and BB-13 NAS100. The hold-out is spent, so only data after 16-23 Oct 2026 counts as new.
4. **Fetch US30 and Apple minutes** when Dukascopy stops throttling, then run BB-12 (US30), BB-14 (US30) and BB-15 exactly as pre-registered.
5. **With the owner's OK,** download frames (`--media`) for the on-screen-only rules, and install Whisper for the garbled 2020-2022 videos.