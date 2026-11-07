# Channels 17–20: Nitin Bhatia, Super Trader Lakshya, Tori Trades, Bear Bull Traders

Read as **rule digests** of the Video Explainer transcripts. Tags: **E** = stated or shown, **I** = inferred.

## #17 Nitin Bhatia (988K subscribers, Hindi)

Picked video 8cgqRS7s3jo ("RSI intraday strategy") has no captions; J9FA7Ouc9i0 replaced it.

### aLwpyla5Hrk, "Intraday Strategy #2 – Heikin Ashi and Stochastic RSI" (20:52)

| Rule | Type | Evidence |
|---|---|---|
| **Heikin-Ashi candles + Stochastic RSI**; 15-minute for intraday, 30-minute for swing | E | 03:30, 06:00 |
| **Buy:** two green Heikin-Ashi candles **with Stochastic RSI below 20** (swing: below 30) | E | 11:30, 13:30, 17:30 |
| **Sell:** two red Heikin-Ashi candles with Stochastic RSI above 80 | E | 11:30, 17:30 |
| **Exit a long** when Stochastic RSI starts falling below 80; **exit a short** when it starts rising above 20 | E | 19:30 |
| Stocks selected by him; he claims close to 100% on paper trading | E (claim) | 02:30 |
| **Stop:** not stated (I: the low of the two signal candles) | I | — |

**Testability: testable with documented assumptions:**
- Stochastic RSI (14, 14, 3, 3), signal on %K;
- the HA colour from the HA close vs the HA open;
- a protective stop at the two candles' extreme in real prices.

Spec **YT-22**: NSE stocks (15-minute) plus Nifty and Bank Nifty.

### cFqdpiHokDw, "Best Intraday Trend Indicator – Vortex" (28:15)

| Rule | Type | Evidence |
|---|---|---|
| The Vortex indicator (+VI, −VI) as a faster trend signal than Supertrend or ADX | E | 00:00–01:30, 20:30 |
| **Rule 1:** if both +VI and −VI are between 0.90 and 1.10, it is a congestion period: **no signals** | E | 23:00 |
| **Signal:** +VI crossing above −VI = bullish; −VI above +VI = bearish | E | 11:00–14:00 |
| He targets 75–80% profitable trades | E (claim) | 02:00 |
| **Exit:** not in the digest (I: the opposite crossover) | I | — |

**Testability: testable with documented assumptions** (period 14; enter on a crossover bar where the leading line is outside the 0.90–1.10 band; exit on the opposite crossover; stop at the signal bar's extreme). Spec **YT-23**: NSE stocks (15-minute), Nifty.

### J9FA7Ouc9i0, "Exponential Moving Average – Best Combination" (30:14)

| Rule | Type | Evidence |
|---|---|---|
| The **5-8-13 moving average** combination ("normally used in forex"); EMA preferred over SMA | E | 02:30, 03:30 |
| Intraday on 15-minute | E | 05:30 |
| **Bullish trend:** price above the three EMAs; the **5 EMA (or the 8 EMA) is the trailing stop** | E | 15:00 |
| **Bearish:** price convincingly breaks all three | E | 15:00 |

**Testability: testable with documented assumptions:**
- entry when the 5, 8 and 13 EMAs first align (5 > 8 > 13) and the bar closes above all three;
- exit on a close below the 8 EMA;
- mirror for shorts.

Spec **YT-24**: Nifty and NSE stocks (15-minute).

## #18 Super Trader Lakshya (905K subscribers, Hindi)

### N3VDbcqilys, "How to use RSI Indicator in Trading – Best Intraday Trading Strategy for Beginners" (17:47, 1.8M views)

- RSI overbought at 70 and oversold at 30 (E 03:30).
- Examples on L&T and Tata Motors: sell after an overbought reading turns down, stop above the recent high, target a 1–2% move (E 08:30–14:00).
- Practise each indicator for 100–200 hours (E 03:00–03:30).
- **Captions partly garbled. Testable only with research assumptions:**
  - RSI(14) on 15-minute: short when RSI crosses back below 70, long when it crosses back above 30;
  - stop beyond the last 5 bars' extreme;
  - target 2R.

  Spec **YT-25**: NSE stocks. Low fidelity.

### -ctjPFOozr8, "Scalping & Price Action FREE COURSE Part 1" (28:27)

- Learn on 5-minute, then trade 15-minute (E 11:00).
- Enter on the break of a candle's high; stop at the low or the wick's midpoint plus 10–15 points (E 07:00–08:30).
- Buy and sell at hand-drawn lines and zones (E 21:30–25:30).
- **Insufficiently defined** (discretionary lines).

### -0f2mu2LU1M, "Banknifty Option Trading & Scalping – Strategy & Setup" (10:05)

A profit showcase: hedged puts on a gap-down expiry day, exit within 5 minutes, and a lesson on emotional control. **Not a strategy.**

## #19 Tori Trades (739K subscribers, English)

### PnIkSLm2yRk, "This boring trading strategy made me $526,454" (28:08)

### qLtq73bTPBA, "Breaking Down My SIMPLE Trading Strategy" (55:50)

| Rule | Type | Evidence |
|---|---|---|
| One tool: **trendlines**, drawn top-down (monthly → weekly → daily → 4h → 1h → 30m → 15m → 10m → 5m); "capture as many touch points as possible without price intersecting"; each new line starts at the previous line's point B | E | PnIk 03:30–14:30; qLtq 45:00–47:30 |
| **Playbooks:** a trendline break, a break-and-retest, and a bounce off the line | E | qLtq 00:00, 30:30–31:00 |
| The "action line" and the "safety line" are the same line; **the stop goes on the other side of the safety line** and **trails along it** | E | PnIk 19:00–21:30 |
| Risk 1–2% a trade; futures | E | qLtq 52:30 |
| **Claim:** a $5,000 account grown to over $500,000 in 11 years | E (claim) | PnIk 00:30 |

**Testability: insufficiently defined.** The whole system rests on hand-drawn trendlines across nine timeframes. An algorithmic trendline would be my strategy, not hers.

## #20 Bear Bull Traders, Andrew Aziz (662K subscribers, English)

### oqzgq4StNS8, "Opening Range Breakout Strategy for Day Trading" (7:47)

| Rule | Type | Evidence |
|---|---|---|
| **Stocks in play:** gapping pre-market on news or earnings with high volume (Delta Air Lines example) | E | 00:00 |
| Wait for 1-minute candles to **close above VWAP** (if it opened below) | E | 01:00–01:30 |
| **Entry:** the break of the **first 5-minute candle's high** | E | 01:30–02:00 |
| **Stop:** just below VWAP / below the previous 1-minute candle (about $0.60 on a $66 stock) | E | 02:30 |
| **Targets:** the next levels (the all-time high), with partials | E | 04:30–06:00 |

**Testability:** US stocks in play are not on disk, so the original is unable to evaluate. Spec **YT-26, a labelled proxy** on NSE stocks (5-minute, with volume, so VWAP can be computed):
- gappers at least 2% with first-candle volume at least 3× its 20-day mean;
- the first 5-minute candle high broken after a 1-minute-equivalent close above VWAP (the 5-minute close);
- stop below VWAP or the first candle's low, whichever is closer;
- target 2R.

### AuArOT-tK9M, "This SIMPLE Trading Strategy Makes a 90% Win Rate Possible!" (1:02:53)

| Rule | Type | Evidence |
|---|---|---|
| **Camarilla pivots** (R3/R4, S3/S4) plus order flow (Bookmap) | E | 00:30 |
| **"Above a 4 we go long, below a 4 we go short"** (R4/S4 breakouts) | E | 18:00 |
| **Fade the extremes:** wait for price to rally into the R3 area and reject → short for the ride back; buy the S3 area after a sell-off | E | 15:00, 25:30 |
| Targets: the opposite level; stops beyond the day's extreme (a new low of day stops you out) | E | 15:00, 25:30 |
| Order-flow confirmation (large resting orders) | E | 24:30 |

**Testability: testable with documented assumptions.** The standard Camarilla rules:
- **Fade:** the open is between S3 and R3. A 5-minute close back below R3 after trading above it → short, stop beyond R4, target the pivot. Mirror at S3.
- **Breakout:** a 5-minute close beyond R4 or S4 → trade the breakout, stop at R3 or S3, target 2R.
- **Not modelled:** order flow.

Spec **YT-27**: Nifty, Bank Nifty and NAS100.
