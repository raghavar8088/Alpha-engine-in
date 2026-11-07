# Strategy library: the 20 largest trading-strategy YouTube channels (Phase 3)

## How the channels were chosen

Data: `data/candidates*.json`, `data/screen.json`, `data/top20.json`.
1. **Candidate pool:** 67 channels, from published "best trading YouTubers" lists (Pocketful, Analytics Insight, Feedspot, daytradingz, AskTraders, Benzinga, Traders Union) plus well-known channels I added.
2. **Live counts:** each candidate's subscriber count, channel id and upload list were read from YouTube with yt-dlp on 7 Nov 2026, never taken from the lists.
3. **Inclusion rule:** among a channel's 50 most-viewed long-form videos, at least 25 titles must be about trading, and more than the investing-only titles.
4. **Excluded by the rule**, above the cut:
   - Pranjal Kamra, CA Rachana Ranade, Asset Yogi, FinnovationZ;
   - DAY TRADER Telugu, which is personal finance despite its name;
   - Abhishek Kar, Ricky Gutierrez, P R Sundar, Benjamin Cowen, Tom Nash.
5. **Also excluded:** Booming Bulls, already studied in `../booming_bulls_2026_11`.
6. **Ranking:** the 20 that qualify, by subscribers.

**Not covered:** channels outside the candidate pool. The pool may miss a large channel; the selection is the top 20 of this pool, not a census of YouTube.

| # | Channel | Subscribers | Region | Videos analysed |
|---|---|--:|---|---|
| 1 | Pushkar Raj Thakur | 15.5M | IN | 3 |
| 2 | The Trading Channel | 2.87M | Global | 3 |
| 3 | The Inner Circle Trader | 2.26M | Global | 3 |
| 4 | Rayner Teo | 2.22M | Global | 3 |
| 5 | Power of Stocks (Subasish Pani) | 2.15M | IN | 3 |
| 6 | Warrior Trading (Ross Cameron) | 2.12M | Global | 2 |
| 7 | Ghanshyam Tech | 1.54M | IN | 3 (1 had no captions; replaced) |
| 8 | Wysetrade | 1.53M | Global | 3 |
| 9 | Humbled Trader | 1.50M | Global | 2 |
| 10 | Sunil Minglani | 1.38M | IN | 2 (3 picks had no captions) |
| 11 | Siddharth Bhanushali | 1.25M | IN | 3 |
| 12 | The Moving Average | 1.14M | Global | 3 |
| 13 | Adam Khoo | 1.11M | Global | 2 |
| 14 | Wealth Secret | 1.08M | IN | 3 |
| 15 | Elearnmarkets | 1.02M | IN | 2 (one unreadable) |
| 16 | The Secret Mindset | 997K | Global | 3 |
| 17 | Nitin Bhatia | 988K | IN | 3 (1 had no captions; replaced) |
| 18 | Super Trader Lakshya | 905K | IN | 3 |
| 19 | Tori Trades | 739K | Global | 2 |
| 20 | Bear Bull Traders | 662K | Global | 2 |

**Videos analysed.** 58 picks; 53 had captions and were analysed. Per channel, they are the most-viewed long-form videos (4 minutes or more) whose titles name a strategy, setup, system or indicator. Videos teaching one specific strategy were preferred over general courses and tutorials (`yt_picks.mjs`, `data/strategy_pool.json`). Analyses are in `../analyses/`.

## Strategies

- **Status:** "ready" = every core rule is explicit. "Assumptions" = one or more definitions are mine (tagged A in PREREGISTRATION.md). "Proxy" = the video's instrument isn't available, so its signal is run on another, and the result isn't the video's.
- **Data:** stocks use NSE 15-minute bars for 2024-10 to 2026-11 (today's liquid universe), or the daily bhavcopy for 2011–2026 (all stocks, point-in-time liquidity).

| ID | Strategy | Channel (videos) | Run on | Status |
|---|---|---|---|---|
| YT-01 | 5 EMA alert candle (5m sells, 15m buys, 1:3) | Power of Stocks (fBTMspiqjS4); Pushkar Raj Thakur (uu3zGIXaG8g) | Nifty, Bank Nifty futures | Ready |
| YT-02 | Market-structure pullback into the broken-swing zone, ATR stop | The Trading Channel (2h5ryPi6ZYo) | EURUSD, GBPUSD 1h (4h trend) | Assumptions |
| YT-03 | 50 MA double bottom / top | The Trading Channel (hTDVTH8umR8) | EURUSD, GBPUSD 1h | Assumptions |
| YT-04 | ICT Silver Bullet (FVG in the 3–4, 10–11, 14–15 NY windows) | ICT (tRq1hyGGtl4) | EURUSD, NAS100 1m | Assumptions |
| YT-05 | ICT Judas Swing (Asian range, midnight open) | ICT (xJMbva8SjzE) | EURUSD, GBPUSD 5m | Assumptions |
| YT-06 | ICT OTE 62% limit, 08:30–11:00 NY | ICT (E9F_aT9f038) | EURUSD 5m | Assumptions |
| YT-07 | Connors RSI(10) < 30 above the 200-day MA, exit RSI > 40 or 10 days | Rayner Teo (W8ENIXvcGlQ) | S&P 500 daily (+ Nasdaq 100, Nifty) | Ready |
| YT-08 | Inside candle (15m), mother-range target | Power of Stocks (42J_foitsdI) | NSE stocks 15m, Nifty, Bank Nifty | Assumptions |
| YT-09 | Traffic light: first red/green 1-minute pair breakout | Power of Stocks (djC2hSdNo74) | Bank Nifty, Nifty | Assumptions |
| YT-10 | Gap day + shooting-star / hammer first candle | Ghanshyam Tech (3v9nvXaW0QQ) | Nifty, Bank Nifty | Assumptions |
| YT-11 | Momentum loss into a 4h swing level, rejection candle | Wysetrade (asDBegQaupM) | EURUSD, GBPUSD, gold 1h | Assumptions |
| YT-12a | 44 SMA bullish candle (daily) | Siddharth Bhanushali (0igedWz9xD0) | NSE stocks daily | Assumptions |
| YT-12b | 44 SMA + big green opening candle (15m) | Siddharth Bhanushali (0igedWz9xD0) | NSE stocks 15m | Assumptions |
| YT-13 | Daily bear / bull trap (big candle after a breakdown) | Siddharth Bhanushali (EIA095N86Vk) | NSE stocks daily (long only), Nifty daily | Assumptions |
| YT-14 | 21/50/200 smoothed-MA fan + engulfing / three-line strike, RSI 50, 1:2 | The Moving Average (wbfXaqjIrJ0, oDOCBTYgCQM) | EURUSD, GBPUSD, gold 5m | Ready |
| YT-15 | MA alignment + Williams fractal, 10-pip target | The Moving Average (MK47z07tGNM) | EURUSD, GBPUSD 5m | Ready |
| YT-16 | MA pullback + engulfing / pin bar, 1:2 | Adam Khoo (lHhtVfeoCdQ, MVI7Jm_abrg) | EURUSD, GBPUSD 1h; S&P 500, Nasdaq 100 daily | Assumptions |
| YT-17 | Opening-range breakout, pullback, continuation | Wealth Secret (oEc3_vjg6PE, QqQLqWMjcsc) | Bank Nifty, Nifty 5m | Assumptions |
| YT-18 | Heikin-Ashi colour change + RSI 50 | The Secret Mindset (Ci1hKIHL9VY) | EURUSD, GBPUSD, gold 15m | Assumptions |
| YT-19 | Supertrend (10, 3) direction at 09:20 | Elearnmarkets / Vishal Mehta (bj6hVKjweZ8) | Bank Nifty, Nifty futures | **Proxy** (the video sells options) |
| YT-20 | 3-EMA (50/100/150) 1-minute pullback scalp | The Secret Mindset (7XhVy9z5SbM) | EURUSD, GBPUSD 1m | Ready |
| YT-21 | Bollinger (20, 2.5) range fade to the middle band | The Secret Mindset (2G9fHBEsauE) | EURUSD, GBPUSD 15m | Assumptions |
| YT-22 | Two Heikin-Ashi candles + Stochastic RSI 20/80 | Nitin Bhatia (aLwpyla5Hrk) | NSE stocks 15m, Nifty, Bank Nifty | Ready |
| YT-23 | Vortex crossover outside 0.9–1.1 | Nitin Bhatia (cFqdpiHokDw) | NSE stocks 15m, Nifty | Assumptions |
| YT-24 | 5-8-13 EMA ribbon, exit below the 8 EMA | Nitin Bhatia (J9FA7Ouc9i0) | NSE stocks 15m, Nifty, Bank Nifty | Assumptions |
| YT-25 | RSI 70/30 reversal | Super Trader Lakshya (N3VDbcqilys) | NSE stocks 15m | Assumptions (low fidelity) |
| YT-26 | 5-minute ORB on gappers above/below VWAP | Bear Bull Traders (oqzgq4StNS8) | NSE stocks 5m | **Proxy** (the video trades US stocks in play) |
| YT-27 | Camarilla R3/S3 fade, R4/S4 breakout | Bear Bull Traders (AuArOT-tK9M) | Nifty, Bank Nifty, NAS100 5m | Assumptions (order flow omitted) |

## Not tested

| What | Why |
|---|---|
| Warrior Trading (5X_ZcifasBg, mfGQr2tHoX0) | US small-cap momentum: needs the whole US tape (top gainers, float). **No data** |
| Humbled Trader VWAP setups (IWk9kf2wQJo); the ChatGPT VWAP strategy (Jh5rJskkEkU) | US stocks with volume; the ChatGPT rules are a demonstration on an unstated timeframe. **No data** |
| Vishal Mehta's option selling (bj6hVKjweZ8) | No intraday option prices; only its direction signal is tested (YT-19, proxy) |
| Gomathi Shankar CPR system (dwuTRDcsgDg) | The only caption track is unreadable (Hindi ASR of non-Hindi speech) |
| Tori Trades trendline system (PnIkSLm2yRk, qLtq73bTPBA) | Hand-drawn trendlines across nine timeframes: **insufficiently defined** |
| Wysetrade trendline and RSI-divergence methods (jdYNaE5GJ0k, 4dVB_g5YeSE) | Hand-drawn trendlines and key levels |
| Rayner Teo MA and MACD concepts (cSWC2WwbhHE, eob4wv2v--k); The Trading Channel 3-step (APUVNDWelRI) | Concepts or filters, not complete strategies |
| Pushkar Raj Thakur price action and S/R (9UMXvhbZ8AY, r2LzjTUs3lo) | No entry rule; "details in the next video" |
| Sunil Minglani (9FCmraBvyVc, hvG7tOqhUgo) | A concept (pattern failure) and discipline rules; his strategy videos have no captions |
| Ghanshyam Tech LDHCL levels and golden rules (8X67v5NfY6I, Nyc8KXziAQU) | Hand-picked daily levels; money management |
| Super Trader Lakshya course and option showcase (-ctjPFOozr8, -0f2mu2LU1M) | Discretionary lines; a P&L showcase |
| Wealth Secret level breaks (J9mz71XaF3I) | Hand-drawn levels; the mechanism is covered by YT-17 |
| Five videos with no captions | EE3AftNnVNk, uy7GXqCmhNY, F9W8clfvp2k (Sunil Minglani); s6Y4higMT1Y (Ghanshyam Tech); 8cgqRS7s3jo (Nitin Bhatia). Whisper is not installed |
