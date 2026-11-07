# The 20 largest trading-strategy YouTube channels: backtest report

Pre-registration SHA-256 `76f59c5325e1e22bcb924d39ae6453c64cac0801fefee3f8df9c6522e9ca8e48`. Every number below comes from `results/`, written by `yt_run.py`.

## Summary

- **Scope:** the 20 largest trading-strategy channels by live subscriber count (`catalogue/`). 58 signature strategy videos were picked; 53 were readable and were analysed with the project's Video Explainer app (`analyses/`).
- **Library:** they gave 28 strategy specifications (`specs/LIBRARY.md`). 61 strategy-market books were run on Indian indices, NSE stocks, forex, gold and US indices, with every rule hash-locked before the first run.
- **Hold-out results** (books with at least 30 hold-out trades): before costs, the chosen versions averaged between −0.25R and +0.17R a trade; after costs, between −1.19R and +0.05R.

**Result: no strategy passes the gates fixed before the test.** Four books are positive in the hold-out but fail on sample size or significance:
- **YT-07, Rayner Teo's Connors RSI(10) pullback** (long only, daily), on the S&P 500 and the Nasdaq 100: positive in development, validation and hold-out, but only about 30 trades in 16 years (8 in each hold-out).
  - On Nifty it gained +0.57R a trade over 5 hold-out trades (Holm p 0.017), but with 22 trades in all it stays below the 30-trade minimum.
  - It is the one rule set here with a consistent, if rare, edge.
- **YT-10, Ghanshyam Tech's gap + hammer first candle** on Bank Nifty: +1.19R over 7 hold-out trades. Validation was flat, and there are too few trades to tell.
- **YT-27, Bear Bull Traders' Camarilla rules** on the Nasdaq 100: +0.03R over 312 trades (t 0.59), indistinguishable from zero.

- **Candidate for paper trading:** 0
- **Needs more evidence:** 4 (YT-07 Nasdaq 100 daily, YT-07 S&P 500 daily, YT-10 Bank Nifty, YT-27 Nasdaq 100)
- **Not supported:** 54 (YT-01 Bank Nifty, YT-01 Nifty, YT-02 EUR/USD, YT-02 GBP/USD, YT-03 EUR/USD, YT-03 GBP/USD, YT-04 EUR/USD, YT-04 Nasdaq 100, YT-05 EUR/USD, YT-05 GBP/USD, YT-06 EUR/USD, YT-08 Bank Nifty, YT-08 Nifty, YT-08 NSE stocks 15m, YT-09 Bank Nifty, YT-09 Nifty, YT-10 Nifty, YT-11 EUR/USD, YT-11 GBP/USD, YT-11 Gold, YT-12a NSE stocks daily, YT-12b NSE stocks 15m, YT-13 Nifty daily, YT-13 NSE stocks daily, YT-14 EUR/USD, YT-14 GBP/USD, YT-14 Gold, YT-15 EUR/USD, YT-15 GBP/USD, YT-16 EUR/USD, YT-16 GBP/USD, YT-17 Bank Nifty, YT-17 Nifty, YT-18 EUR/USD, YT-18 GBP/USD, YT-18 Gold, YT-19 Bank Nifty, YT-19 Nifty, YT-20 EUR/USD, YT-20 GBP/USD, YT-21 EUR/USD, YT-21 GBP/USD, YT-22 Bank Nifty, YT-22 Nifty, YT-22 NSE stocks 15m, YT-23 Nifty, YT-23 NSE stocks 15m, YT-24 Bank Nifty, YT-24 Nifty, YT-24 NSE stocks 15m, YT-25 NSE stocks 15m, YT-26 NSE stocks 5m, YT-27 Bank Nifty, YT-27 Nifty)
- **Unable to evaluate:** 3 (YT-07 Nifty daily, YT-16 Nasdaq 100 daily, YT-16 S&P 500 daily)

## Results by channel (the chosen variant; net of costs; R = profit ÷ the risk at entry)

| Strategy | Channel | Market | Variant | Dev mean R (n) | Validation mean R (n) | Hold-out mean R (n) | Hold-out t | Gross R | Costs R | Win % | Class |
|---|---|---|---|---|---|---|--:|--:|--:|--:|---|
| YT-01 5 EMA alert candle | Power of Stocks; Pushkar Raj Thakur | Bank Nifty | S1 | −0.25 (3,633) | −0.26 (1,237) | −0.36 (1,667) | −7.72 | +0.03 | 0.39 | 26 | not supported |
| YT-01 5 EMA alert candle | Power of Stocks; Pushkar Raj Thakur | Nifty | S1 | −0.33 (3,733) | −0.33 (1,219) | −0.42 (1,750) | −8.93 | +0.06 | 0.48 | 26 | not supported |
| YT-02 Market-structure pullback, ATR stop | The Trading Channel | EUR/USD | R1 | −0.10 (585) | −0.05 (166) | −0.13 (189) | −1.48 | −0.09 | 0.04 | 36 | not supported |
| YT-02 Market-structure pullback, ATR stop | The Trading Channel | GBP/USD | V0 | +0.06 (542) | −0.11 (149) | −0.08 (173) | −0.78 | −0.03 | 0.05 | 32 | not supported |
| YT-03 50 MA double bottom / top | The Trading Channel | EUR/USD | R1 | −0.08 (247) | +0.02 (76) | +0.01 (86) | +0.06 | +0.06 | 0.05 | 42 | not supported |
| YT-03 50 MA double bottom / top | The Trading Channel | GBP/USD | V0 | −0.08 (240) | −0.19 (75) | −0.31 (66) | −1.92 | −0.25 | 0.06 | 24 | not supported |
| YT-04 ICT Silver Bullet | The Inner Circle Trader | EUR/USD | V0 | −0.53 (7,132) | −0.49 (1,960) | −0.63 (2,044) | −10.13 | −0.03 | 0.6 | 11 | not supported |
| YT-04 ICT Silver Bullet | The Inner Circle Trader | Nasdaq 100 | V0 | −0.60 (3,623) | −0.09 (1,303) | −0.02 (1,440) | −0.44 | +0.10 | 0.12 | 34 | not supported |
| YT-05 ICT Judas Swing | The Inner Circle Trader | EUR/USD | R1 | −0.07 (755) | +0.02 (217) | +0.05 (219) | +0.58 | +0.11 | 0.06 | 43 | not supported |
| YT-05 ICT Judas Swing | The Inner Circle Trader | GBP/USD | V0 | +0.01 (993) | −0.06 (229) | −0.13 (249) | −1.70 | −0.06 | 0.06 | 37 | not supported |
| YT-06 ICT OTE 62% retracement | The Inner Circle Trader | EUR/USD | V0 | −0.09 (1,423) | −0.08 (411) | −0.10 (445) | −1.62 | −0.02 | 0.08 | 36 | not supported |
| YT-07 Connors RSI(10) pullback, S&P 500 | Rayner Teo | Nasdaq 100 daily | V0 | +0.47 (16) | +0.27 (7) | +0.33 (8) | +1.23 | +0.33 | 0.0 | 88 | needs more evidence |
| YT-07 Connors RSI(10) pullback, S&P 500 | Rayner Teo | Nifty daily | V0 | +0.14 (14) | +0.67 (3) | +0.57 (5) | +3.52 | +0.59 | 0.02 | 100 | unable to evaluate |
| YT-07 Connors RSI(10) pullback, S&P 500 | Rayner Teo | S&P 500 daily | V0 | +0.54 (17) | +0.21 (5) | +0.31 (8) | +1.30 | +0.32 | 0.01 | 75 | needs more evidence |
| YT-08 Inside candle (15m) | Power of Stocks | Bank Nifty | R1 | −0.16 (1,630) | −0.14 (492) | −0.27 (712) | −6.61 | −0.07 | 0.2 | 39 | not supported |
| YT-08 Inside candle (15m) | Power of Stocks | Nifty | R1 | −0.16 (1,525) | −0.06 (462) | −0.25 (696) | −5.92 | −0.01 | 0.24 | 40 | not supported |
| YT-08 Inside candle (15m) | Power of Stocks | NSE stocks 15m | V0 | −0.17 (56,184) | −0.22 (41,705) | −0.19 (69,940) | −14.91 | +0.05 | 0.24 | 36 | not supported |
| YT-09 Traffic light candle pair | Power of Stocks | Bank Nifty | V0 | −0.19 (1,424) | −0.20 (477) | −0.25 (673) | −4.53 | +0.10 | 0.35 | 35 | not supported |
| YT-09 Traffic light candle pair | Power of Stocks | Nifty | S1 | −0.20 (1,442) | −0.12 (487) | −0.19 (688) | −3.53 | +0.09 | 0.29 | 36 | not supported |
| YT-10 Gap + shooting star / hammer first candle | Ghanshyam Tech | Bank Nifty | V0 | +0.55 (25) | −0.00 (5) | +1.19 (7) | +3.40 | +1.29 | 0.1 | 71 | needs more evidence |
| YT-10 Gap + shooting star / hammer first candle | Ghanshyam Tech | Nifty | S1 | −0.24 (35) | +0.15 (6) | +0.54 (5) | +0.75 | +0.82 | 0.27 | 60 | not supported |
| YT-11 Momentum loss into a swing level | Wysetrade | EUR/USD | R1 | −0.05 (333) | +0.14 (90) | −0.17 (102) | −1.43 | −0.03 | 0.15 | 37 | not supported |
| YT-11 Momentum loss into a swing level | Wysetrade | GBP/USD | R1 | −0.12 (371) | −0.26 (101) | −0.03 (114) | −0.24 | +0.10 | 0.13 | 42 | not supported |
| YT-11 Momentum loss into a swing level | Wysetrade | Gold | R1 | −0.24 (328) | −0.24 (112) | −0.23 (115) | −2.05 | −0.08 | 0.15 | 32 | not supported |
| YT-12a 44 SMA bullish candle (daily) | Siddharth Bhanushali | NSE stocks daily | R1 | −0.09 (6,799) | +0.05 (4,865) | −0.02 (10,821) | −2.67 | +0.07 | 0.09 | 30 | not supported |
| YT-12b 44 SMA + big green opening candle (15m) | Siddharth Bhanushali | NSE stocks 15m | V0 | −0.03 (766) | −0.11 (1,179) | −0.12 (1,375) | −3.11 | −0.02 | 0.09 | 40 | not supported |
| YT-13 Daily bear / bull trap | Siddharth Bhanushali | Nifty daily | V0 | −0.30 (18) | −0.55 (5) | −0.96 (7) | −15.31 | −0.95 | 0.02 | 0 | not supported |
| YT-13 Daily bear / bull trap | Siddharth Bhanushali | NSE stocks daily | V0 | −0.06 (5,080) | −0.15 (4,032) | −0.09 (8,263) | −4.75 | −0.05 | 0.05 | 39 | not supported |
| YT-14 MA fan + engulfing / three-line strike, RSI 50 | The Moving Average | EUR/USD | R1 | −0.19 (7,776) | −0.20 (2,198) | −0.22 (2,382) | −8.93 | −0.02 | 0.2 | 38 | not supported |
| YT-14 MA fan + engulfing / three-line strike, RSI 50 | The Moving Average | GBP/USD | V0 | −0.17 (7,623) | −0.15 (2,163) | −0.23 (2,327) | −8.34 | −0.03 | 0.2 | 31 | not supported |
| YT-14 MA fan + engulfing / three-line strike, RSI 50 | The Moving Average | Gold | R1 | −0.36 (7,477) | −0.26 (2,146) | −0.14 (2,317) | −5.84 | +0.04 | 0.18 | 36 | not supported |
| YT-15 MA alignment + Williams fractal, 10 pips | The Moving Average | EUR/USD | V0 | −0.26 (13,908) | −0.26 (3,785) | −0.37 (4,128) | −15.40 | −0.06 | 0.31 | 30 | not supported |
| YT-15 MA alignment + Williams fractal, 10 pips | The Moving Average | GBP/USD | V0 | −0.29 (13,984) | −0.24 (3,833) | −0.32 (4,159) | −14.66 | +0.00 | 0.32 | 34 | not supported |
| YT-16 MA pullback + engulfing / pin bar, 1:2 | Adam Khoo | EUR/USD | V0 | −0.16 (466) | −0.19 (157) | +0.04 (188) | +0.34 | +0.12 | 0.09 | 37 | not supported |
| YT-16 MA pullback + engulfing / pin bar, 1:2 | Adam Khoo | GBP/USD | V0 | −0.09 (498) | −0.33 (130) | −0.24 (151) | −2.22 | −0.15 | 0.09 | 27 | not supported |
| YT-16 MA pullback + engulfing / pin bar, 1:2 | Adam Khoo | Nasdaq 100 daily | V0 | +0.50 (8) | −1.00 (1) | −1.11 (3) | −10.05 | −1.11 | 0.0 | 0 | unable to evaluate |
| YT-16 MA pullback + engulfing / pin bar, 1:2 | Adam Khoo | S&P 500 daily | V0 | +1.00 (6) | +0.20 (5) | −0.00 (3) | −0.00 | +0.01 | 0.01 | 33 | unable to evaluate |
| YT-17 Breakout, pullback, continuation | Wealth Secret | Bank Nifty | R1 | −0.36 (626) | −0.52 (224) | −0.46 (304) | −6.41 | −0.05 | 0.41 | 36 | not supported |
| YT-17 Breakout, pullback, continuation | Wealth Secret | Nifty | V0 | −0.47 (659) | −0.51 (241) | −0.54 (293) | −6.40 | −0.04 | 0.5 | 31 | not supported |
| YT-18 Heikin-Ashi colour change + RSI 50 | The Secret Mindset | EUR/USD | S1 | −0.10 (6,668) | −0.12 (1,800) | −0.13 (1,991) | −2.99 | +0.01 | 0.14 | 28 | not supported |
| YT-18 Heikin-Ashi colour change + RSI 50 | The Secret Mindset | GBP/USD | S1 | −0.13 (6,674) | −0.06 (1,784) | −0.16 (2,017) | −4.20 | −0.01 | 0.15 | 28 | not supported |
| YT-18 Heikin-Ashi colour change + RSI 50 | The Secret Mindset | Gold | S1 | −0.23 (6,612) | −0.20 (1,797) | −0.14 (1,960) | −3.51 | +0.01 | 0.15 | 27 | not supported |
| YT-19 Supertrend(10,3) at 09:20 (futures proxy) | Elearnmarkets / Vishal Mehta | Bank Nifty | V0 | −0.08 (1,459) | −0.09 (485) | −0.22 (677) | −2.75 | +0.09 | 0.3 | 36 | not supported |
| YT-19 Supertrend(10,3) at 09:20 (futures proxy) | Elearnmarkets / Vishal Mehta | Nifty | V0 | −0.19 (1,460) | −0.15 (487) | −0.37 (688) | −2.20 | +0.06 | 0.43 | 35 | not supported |
| YT-20 3-EMA 1-minute scalp | The Secret Mindset | EUR/USD | V0 | −0.39 (13,669) | −0.47 (3,723) | −0.50 (4,057) | −23.21 | +0.01 | 0.51 | 27 | not supported |
| YT-20 3-EMA 1-minute scalp | The Secret Mindset | GBP/USD | V0 | −0.36 (13,656) | −0.35 (3,732) | −0.45 (4,090) | −21.78 | +0.06 | 0.51 | 25 | not supported |
| YT-21 Bollinger 2.5 SD range fade | The Secret Mindset | EUR/USD | V0 | −0.13 (1,309) | −0.01 (348) | −0.32 (386) | −4.82 | −0.10 | 0.21 | 33 | not supported |
| YT-21 Bollinger 2.5 SD range fade | The Secret Mindset | GBP/USD | V0 | −0.15 (1,224) | −0.20 (343) | −0.28 (376) | −4.56 | −0.06 | 0.22 | 37 | not supported |
| YT-22 Heikin-Ashi pair + Stochastic RSI 20/80 | Nitin Bhatia | Bank Nifty | V0 | −0.55 (599) | −0.45 (177) | −0.93 (263) | −4.51 | −0.11 | 0.83 | 21 | not supported |
| YT-22 Heikin-Ashi pair + Stochastic RSI 20/80 | Nitin Bhatia | Nifty | V0 | −0.60 (572) | −0.40 (177) | −1.19 (226) | −3.62 | −0.05 | 1.14 | 21 | not supported |
| YT-22 Heikin-Ashi pair + Stochastic RSI 20/80 | Nitin Bhatia | NSE stocks 15m | V0 | −0.57 (16,141) | −0.65 (11,047) | −0.58 (19,771) | −18.47 | +0.01 | 0.59 | 23 | not supported |
| YT-23 Vortex crossover outside congestion | Nitin Bhatia | Nifty | V0 | −0.65 (507) | −0.66 (163) | −0.62 (251) | −2.93 | +0.17 | 0.79 | 20 | not supported |
| YT-23 Vortex crossover outside congestion | Nitin Bhatia | NSE stocks 15m | V0 | −0.68 (20,398) | −0.78 (13,958) | −0.70 (25,774) | −20.94 | +0.03 | 0.73 | 22 | not supported |
| YT-24 5-8-13 EMA ribbon | Nitin Bhatia | Bank Nifty | V0 | −0.35 (1,725) | −0.41 (572) | −0.49 (797) | −8.50 | −0.09 | 0.4 | 24 | not supported |
| YT-24 5-8-13 EMA ribbon | Nitin Bhatia | Nifty | V0 | −0.40 (1,693) | −0.29 (557) | −0.60 (777) | −8.48 | −0.03 | 0.57 | 24 | not supported |
| YT-24 5-8-13 EMA ribbon | Nitin Bhatia | NSE stocks 15m | V0 | −0.41 (53,899) | −0.53 (40,081) | −0.43 (64,849) | −18.11 | +0.03 | 0.46 | 24 | not supported |
| YT-25 RSI 70/30 reversal | Super Trader Lakshya | NSE stocks 15m | V0 | −0.19 (29,632) | −0.22 (19,505) | −0.18 (34,591) | −9.23 | +0.00 | 0.18 | 38 | not supported |
| YT-26 5-minute ORB on gappers with VWAP (proxy) | Bear Bull Traders | NSE stocks 5m | V0 | −0.30 (192) | +0.14 (101) | −0.22 (257) | −1.69 | −0.09 | 0.13 | 37 | not supported |
| YT-27 Camarilla R3/S3 fade, R4/S4 breakout | Bear Bull Traders | Bank Nifty | V0 | +0.08 (708) | +0.01 (201) | −0.10 (315) | −1.70 | +0.03 | 0.13 | 47 | not supported |
| YT-27 Camarilla R3/S3 fade, R4/S4 breakout | Bear Bull Traders | Nasdaq 100 | V0 | −0.02 (912) | +0.12 (306) | +0.03 (312) | +0.59 | +0.05 | 0.02 | 55 | needs more evidence |
| YT-27 Camarilla R3/S3 fade, R4/S4 breakout | Bear Bull Traders | Nifty | V0 | −0.04 (600) | +0.03 (180) | −0.08 (326) | −1.44 | +0.06 | 0.14 | 48 | not supported |

Source-faithful V0, where a different variant was chosen:

| Strategy | Market | Hold-out mean R (n) | t | Class |
|---|---|---|--:|---|
| YT-01 | Bank Nifty | −0.39 (1,701) | −10.00 | not supported |
| YT-01 | Nifty | −0.45 (1,792) | −11.23 | not supported |
| YT-02 | EUR/USD | −0.07 (182) | −0.71 | not supported |
| YT-03 | EUR/USD | +0.11 (81) | +0.67 | not supported |
| YT-05 | EUR/USD | +0.01 (219) | +0.14 | not supported |
| YT-08 | Bank Nifty | −0.31 (812) | −6.74 | not supported |
| YT-08 | Nifty | −0.31 (776) | −6.34 | not supported |
| YT-09 | Nifty | −0.41 (678) | −7.42 | not supported |
| YT-10 | Nifty | +0.62 (10) | +1.37 | not supported |
| YT-11 | EUR/USD | −0.16 (102) | −1.18 | not supported |
| YT-11 | GBP/USD | −0.08 (114) | −0.61 | not supported |
| YT-11 | Gold | −0.14 (115) | −1.12 | not supported |
| YT-12a | NSE stocks daily | −0.05 (11,578) | −4.73 | not supported |
| YT-14 | EUR/USD | −0.21 (2,347) | −7.54 | not supported |
| YT-14 | Gold | −0.13 (2,275) | −4.52 | not supported |
| YT-17 | Bank Nifty | −0.45 (304) | −5.56 | not supported |
| YT-18 | EUR/USD | −0.47 (2,571) | −14.43 | not supported |
| YT-18 | GBP/USD | −0.49 (2,571) | −17.59 | not supported |
| YT-18 | Gold | −0.29 (2,550) | −9.67 | not supported |

## Robustness (hold-out mean R under each stress, chosen variant)

| Strategy | Market | Base | Gross | Costs ×2 | Slippage ×3 | Entry one row late |
|---|---|--:|--:|--:|--:|--:|
| YT-01 | Bank Nifty | −0.36 | +0.02 | −0.70 | −0.48 | −0.34 |
| YT-01 | Nifty | −0.42 | +0.06 | −0.85 | −0.53 | −0.40 |
| YT-02 | EUR/USD | −0.13 | −0.08 | −0.18 | −0.14 | −0.12 |
| YT-02 | GBP/USD | −0.08 | −0.05 | −0.16 | −0.14 | −0.12 |
| YT-03 | EUR/USD | +0.01 | +0.05 | −0.09 | −0.06 | −0.05 |
| YT-03 | GBP/USD | −0.31 | −0.23 | −0.34 | −0.32 | −0.27 |
| YT-04 | EUR/USD | −0.63 | −0.08 | −1.13 | −0.74 | n/a¹ |
| YT-04 | Nasdaq 100 | −0.02 | +0.08 | −0.13 | −0.06 | −0.03 |
| YT-05 | EUR/USD | +0.05 | +0.11 | +0.00 | +0.04 | +0.03 |
| YT-05 | GBP/USD | −0.13 | −0.06 | −0.18 | −0.16 | −0.12 |
| YT-06 | EUR/USD | −0.10 | −0.03 | −0.18 | −0.12 | −0.09 |
| YT-07 | Nasdaq 100 daily | +0.33 | +0.33 | +0.32 | +0.32 | +0.04 |
| YT-07 | Nifty daily | +0.57 | +0.59 | +0.55 | +0.56 | +0.29 |
| YT-07 | S&P 500 daily | +0.31 | +0.32 | +0.31 | +0.31 | −0.02 |
| YT-08 | Bank Nifty | −0.27 | −0.07 | −0.45 | −0.34 | −0.27 |
| YT-08 | Nifty | −0.25 | −0.01 | −0.48 | −0.31 | −0.25 |
| YT-08 | NSE stocks 15m | −0.19 | +0.06 | −0.40 | −0.32 | −0.17 |
| YT-09 | Bank Nifty | −0.25 | +0.08 | −0.58 | −0.41 | −0.29 |
| YT-09 | Nifty | −0.19 | +0.09 | −0.47 | −0.26 | −0.20 |
| YT-10 | Bank Nifty | +1.19 | +1.29 | +1.10 | +1.18 | +1.19 |
| YT-10 | Nifty | +0.54 | +0.80 | +0.30 | +0.54 | +0.54 |
| YT-11 | EUR/USD | −0.17 | +0.03 | −0.34 | −0.26 | −0.13 |
| YT-11 | GBP/USD | −0.03 | +0.11 | −0.23 | −0.11 | −0.06 |
| YT-11 | Gold | −0.23 | −0.07 | −0.34 | −0.28 | −0.23 |
| YT-12a | NSE stocks daily | −0.02 | +0.07 | −0.11 | −0.05 | – |
| YT-12b | NSE stocks 15m | −0.12 | −0.03 | −0.20 | −0.18 | −0.11 |
| YT-13 | Nifty daily | −0.96 | −0.95 | −0.97 | −0.96 | – |
| YT-13 | NSE stocks daily | −0.09 | −0.05 | −0.14 | −0.11 | – |
| YT-14 | EUR/USD | −0.22 | −0.02 | −0.41 | −0.27 | −0.23 |
| YT-14 | GBP/USD | −0.23 | −0.04 | −0.41 | −0.29 | −0.23 |
| YT-14 | Gold | −0.14 | +0.07 | −0.28 | −0.21 | −0.15 |
| YT-15 | EUR/USD | −0.37 | −0.06 | −0.63 | −0.44 | n/a¹ |
| YT-15 | GBP/USD | −0.32 | +0.03 | −0.58 | −0.43 | −0.38 |
| YT-16 | EUR/USD | +0.04 | +0.10 | −0.04 | +0.01 | +0.06 |
| YT-16 | GBP/USD | −0.24 | −0.17 | −0.33 | −0.28 | −0.28 |
| YT-16 | Nasdaq 100 daily | −1.11 | −1.11 | −1.11 | −1.11 | −0.08 |
| YT-16 | S&P 500 daily | −0.00 | +0.00 | −0.00 | −0.00 | −0.80 |
| YT-17 | Bank Nifty | −0.46 | −0.04 | −0.84 | −0.58 | −0.46 |
| YT-17 | Nifty | −0.54 | −0.05 | −0.97 | −0.63 | −0.52 |
| YT-18 | EUR/USD | −0.13 | +0.01 | −0.27 | −0.17 | −0.17 |
| YT-18 | GBP/USD | −0.16 | −0.02 | −0.31 | −0.23 | −0.22 |
| YT-18 | Gold | −0.14 | +0.01 | −0.25 | −0.20 | −0.15 |
| YT-19 | Bank Nifty | −0.22 | +0.10 | −0.91 | −0.28 | −0.22 |
| YT-19 | Nifty | −0.37 | +0.05 | −0.45 | −0.30 | −0.12 |
| YT-20 | EUR/USD | −0.50 | +0.03 | −0.90 | −0.59 | n/a¹ |
| YT-20 | GBP/USD | −0.45 | +0.06 | −0.84 | −0.60 | −0.68 |
| YT-21 | EUR/USD | −0.32 | −0.11 | −0.51 | −0.38 | −0.34 |
| YT-21 | GBP/USD | −0.28 | −0.04 | −0.46 | −0.38 | −0.34 |
| YT-22 | Bank Nifty | −0.93 | −0.11 | −1.30 | −0.89 | −2.58 |
| YT-22 | Nifty | −1.19 | −0.06 | −1.62 | −0.96 | −0.88 |
| YT-22 | NSE stocks 15m | −0.58 | +0.02 | −0.96 | −0.76 | −1.21 |
| YT-23 | Nifty | −0.62 | +0.22 | −1.21 | −0.72 | −0.90 |
| YT-23 | NSE stocks 15m | −0.70 | +0.06 | −1.09 | −0.81 | −1.31 |
| YT-24 | Bank Nifty | −0.49 | −0.10 | −0.79 | −0.57 | −0.57 |
| YT-24 | Nifty | −0.60 | −0.01 | −1.02 | −0.69 | −0.67 |
| YT-24 | NSE stocks 15m | −0.43 | +0.04 | −0.75 | −0.60 | −0.82 |
| YT-25 | NSE stocks 15m | −0.18 | +0.00 | −0.34 | −0.29 | −0.26 |
| YT-26 | NSE stocks 5m | −0.22 | −0.03 | −0.28 | −0.21 | −0.20 |
| YT-27 | Bank Nifty | −0.10 | +0.03 | −0.21 | −0.13 | −0.10 |
| YT-27 | Nasdaq 100 | +0.03 | +0.04 | +0.01 | +0.02 | +0.01 |
| YT-27 | Nifty | −0.08 | +0.06 | −0.22 | −0.12 | −0.09 |

¹ Not meaningful: a one-row-late limit fill can land a fraction of a pip from the stop, and dividing by that near-zero risk explodes the R figure.
– under "Entry one row late" for the daily stop-entry strategies (YT-12a, YT-13): the order is valid for the next day only, so a one-day delay leaves nothing to fill.

## After each video was published, and walk-forward

| Strategy | Market | From | Trades | Mean R | Walk-forward trades | Walk-forward mean R | t |
|---|---|---|--:|--:|--:|--:|--:|
| YT-01 | Bank Nifty | 2022-06-01 | 2,653 | −0.34 | 4,811 | −0.28 | −10.69 |
| YT-01 | Nifty | 2022-06-01 | 2,714 | −0.40 | 4,841 | −0.33 | −11.67 |
| YT-02 | EUR/USD | 2021-06-01 | 283 | −0.15 | 782 | −0.13 | −3.04 |
| YT-02 | GBP/USD | 2021-06-01 | 250 | −0.12 | 700 | −0.00 | −0.01 |
| YT-03 | EUR/USD | 2022-01-01 | 113 | +0.01 | 341 | −0.04 | −0.64 |
| YT-03 | GBP/USD | 2022-01-01 | 91 | −0.27 | 322 | −0.10 | −1.41 |
| YT-04 | EUR/USD | 2023-06-01 | 1,989 | −0.63 | 9,152 | −0.55 | −18.20 |
| YT-04 | Nasdaq 100 | 2023-06-01 | 1,403 | −0.02 | 5,584 | −0.31 | −11.01 |
| YT-05 | EUR/USD | 2018-01-01 | 607 | −0.01 | 1,057 | −0.04 | −1.11 |
| YT-05 | GBP/USD | 2018-01-01 | 685 | −0.05 | 1,237 | −0.05 | −1.29 |
| YT-06 | EUR/USD | 2020-05-01 | 815 | −0.10 | 1,888 | −0.09 | −3.09 |
| YT-07 | Nasdaq 100 daily | 2021-01-01 | 14 | +0.32 | 2 | +0.49 | +4.12 |
| YT-07 | Nifty daily | 2021-01-01 | 11 | +0.70 | – | – | – |
| YT-07 | S&P 500 daily | 2021-01-01 | 11 | +0.33 | 1 | −0.25 | – |
| YT-08 | Bank Nifty | 2021-12-01 | 1,225 | −0.21 | 2,013 | −0.18 | −7.46 |
| YT-08 | Nifty | 2021-12-01 | 1,180 | −0.18 | 1,899 | −0.14 | −5.43 |
| YT-08 | NSE stocks 15m | 2021-12-01 | 167,829 | −0.19 | – | – | – |
| YT-09 | Bank Nifty | 2022-03-01 | 1,111 | −0.26 | 1,855 | −0.18 | −5.30 |
| YT-09 | Nifty | 2022-03-01 | 1,136 | −0.17 | 1,887 | −0.15 | −4.42 |
| YT-10 | Bank Nifty | 2022-01-01 | 12 | +0.69 | 14 | +0.50 | +1.35 |
| YT-10 | Nifty | 2022-01-01 | 11 | +0.33 | 18 | +0.28 | +0.83 |
| YT-11 | EUR/USD | 2021-01-01 | 160 | −0.05 | 440 | −0.13 | −2.14 |
| YT-11 | GBP/USD | 2021-01-01 | 178 | −0.03 | 485 | −0.13 | −2.37 |
| YT-11 | Gold | 2021-01-01 | 196 | −0.23 | 479 | −0.22 | −3.71 |
| YT-12a | NSE stocks daily | 2021-06-01 | 13,849 | −0.03 | 21,249 | −0.02 | −3.40 |
| YT-12b | NSE stocks 15m | 2021-06-01 | 3,320 | −0.09 | – | – | – |
| YT-13 | Nifty daily | 2021-01-01 | 16 | −0.55 | – | – | – |
| YT-13 | NSE stocks daily | 2021-01-01 | 11,260 | −0.10 | 16,406 | −0.09 | −5.94 |
| YT-14 | EUR/USD | 2022-06-01 | 2,807 | −0.21 | 10,203 | −0.21 | −15.99 |
| YT-14 | GBP/USD | 2022-06-01 | 2,739 | −0.20 | 10,116 | −0.19 | −14.45 |
| YT-14 | Gold | 2022-06-01 | 2,734 | −0.15 | 9,860 | −0.29 | −22.67 |
| YT-15 | EUR/USD | 2022-01-01 | 5,403 | −0.34 | 17,975 | −0.31 | −26.74 |
| YT-15 | GBP/USD | 2022-01-01 | 5,430 | −0.30 | 18,141 | −0.30 | −29.47 |
| YT-16 | EUR/USD | 2016-01-01 | 520 | −0.10 | 690 | −0.08 | −1.50 |
| YT-16 | GBP/USD | 2016-01-01 | 461 | −0.22 | 644 | −0.19 | −3.47 |
| YT-16 | Nasdaq 100 daily | 2016-01-01 | 9 | −0.37 | – | – | – |
| YT-16 | S&P 500 daily | 2016-01-01 | 10 | −0.10 | – | – | – |
| YT-17 | Bank Nifty | 2023-09-01 | 342 | −0.48 | 845 | −0.43 | −10.11 |
| YT-17 | Nifty | 2023-09-01 | 330 | −0.62 | 857 | −0.48 | −9.86 |
| YT-18 | EUR/USD | 2021-06-01 | 2,968 | −0.13 | 8,638 | −0.12 | −5.49 |
| YT-18 | GBP/USD | 2021-06-01 | 2,973 | −0.16 | 8,640 | −0.12 | −5.52 |
| YT-18 | Gold | 2021-06-01 | 2,901 | −0.16 | 8,581 | −0.20 | −10.37 |
| YT-19 | Bank Nifty | 2021-08-01 | 1,265 | −0.16 | 1,890 | −0.12 | −2.72 |
| YT-19 | Nifty | 2021-08-01 | 1,278 | −0.27 | 1,904 | −0.23 | −3.55 |
| YT-20 | EUR/USD | 2021-03-01 | 6,353 | −0.49 | 17,728 | −0.47 | −47.97 |
| YT-20 | GBP/USD | 2021-03-01 | 6,389 | −0.41 | 17,730 | −0.39 | −40.26 |
| YT-21 | EUR/USD | 2021-06-01 | 558 | −0.22 | 1,689 | −0.16 | −4.78 |
| YT-21 | GBP/USD | 2021-06-01 | 565 | −0.24 | 1,602 | −0.20 | −5.25 |
| YT-22 | Bank Nifty | 2020-06-01 | 595 | −0.68 | 728 | −0.65 | −6.72 |
| YT-22 | Nifty | 2020-06-01 | 542 | −0.70 | 666 | −0.68 | −4.93 |
| YT-22 | NSE stocks 15m | 2020-06-01 | 46,959 | −0.59 | – | – | – |
| YT-23 | Nifty | 2020-09-01 | 510 | −0.67 | 635 | −0.58 | −4.73 |
| YT-23 | NSE stocks 15m | 2020-09-01 | 60,130 | −0.71 | – | – | – |
| YT-24 | Bank Nifty | 2020-06-01 | 1,829 | −0.41 | 2,233 | −0.39 | −10.53 |
| YT-24 | Nifty | 2020-06-01 | 1,771 | −0.45 | 2,154 | −0.43 | −9.45 |
| YT-24 | NSE stocks 15m | 2020-06-01 | 158,829 | −0.45 | – | – | – |
| YT-25 | NSE stocks 15m | 2021-01-01 | 83,728 | −0.19 | – | – | – |
| YT-26 | NSE stocks 5m | 2023-01-01 | 550 | −0.18 | – | – | – |
| YT-27 | Bank Nifty | 2022-01-01 | 516 | −0.05 | 890 | +0.01 | +0.31 |
| YT-27 | Nasdaq 100 | 2022-01-01 | 421 | +0.02 | 1,322 | +0.04 | +1.35 |
| YT-27 | Nifty | 2022-01-01 | 506 | −0.04 | 825 | −0.04 | −1.06 |

## Verification (Phase 5)

- **Engine unit tests:** 12 of 12 pass. They cover stop-entry orders, OCO pairs, limit entries, indicator exits, holding limits, fixed targets, risk units and overnight trades.
- **Look-ahead truncation test:** 45 of 45 strategy-variant combinations give identical signals and exit flags when the data is cut at random rows.
- **One real defect was caught before any run:** four strategies filtered days by their final length. Logged in the pre-registration change log.

## Limitations

- **Videos:** 2–3 signature strategy videos per channel were analysed, not every upload, and most from rule digests (the opening plus the highest-scoring rule blocks) rather than full reads. Five picks had no captions, and Whisper is not installed. No video frames were used.
- **Options:** Indian channels mostly trade index options; their signals ran on index futures at the index price, so option P&L is not measured. Vishal Mehta's option-selling system was tested only through its Supertrend direction signal (YT-19, a proxy).
- **No data:** US stocks, US small caps, intraday options and crypto minutes. Warrior Trading, Humbled Trader and the US-stock setups of Bear Bull Traders could not be tested as taught; YT-26 runs the Bear Bull opening-range idea on NSE stocks as a labelled proxy.
- **NSE stocks:**
  - Intraday stock tests use today's 268-stock liquid universe (survivorship bias) over two years only (2024-10 to 2026-11).
  - The daily tests use the full bhavcopy with a point-in-time liquidity filter, back-adjusted for splits by an overnight-ratio rule rather than the corporate-actions file.
- **Rule fidelity:** many words needed numbers ("big candle", "key level", "pullback"). Every such choice is tagged A in the pre-registration, and strategies resting mostly on such choices are marked low fidelity in the library.
- **Multiple testing:** every hold-out test is Holm-corrected; gates as in the pre-registration.
- **Tight stops:** R is measured against each strategy's own stop. Stops at a tiny signal bar's extreme make 37 of about 700,000 trades exceed ±50R. They sit in books that lose heavily overall (t between −3 and −21) and change no verdict. A future engine should cap position size by margin.

## Reproduce

From `backend/research/youtube_top20_2026_11/`: Node 22+ with yt-dlp, Deno and FFmpeg on PATH for steps 1–5, and `python -I` for the rest.

| Step | Command |
|---|---|
| 1 | `node yt_candidates.mjs && node yt_candidates.mjs 2` |
| 2 | `node yt_listings.mjs 600000` |
| 3 | `node yt_select.mjs` |
| 4 | `node yt_extract.mjs 2` |
| 5 | `node yt_build_catalogue.mjs` |
| 6 | `D:/NSE-Intraday-Research/env/Scripts/python.exe yt_bhav_convert.py` |
| 7 | `python -I yt_checks.py` |
| 8 | `python -I yt_run.py` |
| 9 | `python -I yt_run.py --summary` |
| 10 | `python -I yt_report.py` |