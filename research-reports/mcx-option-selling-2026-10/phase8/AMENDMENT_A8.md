# Amendment A8: Phase 8, INTRADAY strategies on real MCX crude and natural-gas bars (2026-10-24, before any A8 backtest)

## The request and the data
**The request:** the owner asked for intraday strategies only, with the target of 2% a week.

**Why only a short window exists:**
- No multi-year intraday history can be fetched legitimately: the free sources block automated
  downloads, and MCX and Angel keep no intraday history for expired contracts.
- The owner chose the app's own recorded bars instead.

**The data:**
- **Source:** the app's own recorded bars, real MCX prices from Angel One, exported read-only
  from production (`commodity_bars`).
- **Days:** CRUDEOIL and NATURALGAS front months.

  | Bars | Window | Sessions |
  |---|---|---|
  | 5-minute | 5 Aug – 23 Oct 2026 | 57 |
  | 15-minute | 17 Jul – 23 Oct | 70 |
  | 1-hour | 21 May – 23 Oct | 111 |
- **Day selection:** each day uses the contract with the most bars that day. A day is used only
  if that contract has at least 90% of a full session (5m 157 of 174; 15m 52 of 58; 1h 13 of 15).
- **Reading the result:** 10–22 weeks cannot prove a weekly edge. This is a first look on real
  MCX data, and it says so.

## Rules common to every strategy
- **Session:** MCX 09:00–23:30 IST. The whole window is in US daylight saving, so the close is
  23:30.
- **Flat every night:** every position is closed at the close of the 23:25 five-minute bar (the
  last bar for 15m and 1h).
- **No look-ahead:**
  - a signal is read at a bar's close and filled at the NEXT bar's open;
  - breakout entries fill at the level, or at the bar's open if it gapped past;
  - a stop or target is checked against each later bar's high and low. If both could have hit
    in one bar, the stop counts.
- **One position at a time** per strategy and instrument.
- **Costs, per side:**
  - slippage of 1 tick (crude ₹1, natural gas ₹0.10), with a 2-tick stress test;
  - MCX 0.0021% and SEBI 0.0001% (both plus 18% GST);
  - CTT 0.01% on the sell side, stamp 0.002% on the buy side;
  - ₹20 brokerage + GST per order.
- **Size:** 1× exposure (₹10 lakh notional) per trade. Results are % of a ₹10 lakh account.

## The fixed strategy set (standard settings; nothing tuned; 16 per instrument, 32 in total)
| # | Code | Rule | Bars |
|---|---|---|---|
| 1 | ORB-AM | 09:00–09:30 range; first breakout after 09:30; stop at the other side; exit at the close | 5m |
| 2 | ORB-US | 18:30–19:00 range (NYMEX open); first breakout after 19:00; stop at the other side; exit at the close | 5m |
| 3 | PDHL | Break of the previous session's high (long) or low (short) after 09:30; stop at half the previous day's range; exit at the close; at most one trade a day | 5m |
| 4 | VWAP-REV | Close more than 2σ from the session VWAP (σ of close − VWAP so far, at least 12 bars): fade it; target the VWAP, stop 1σ beyond entry; at most 3 trades a day | 5m |
| 5 | RSI2 | RSI(2) < 10 long, > 90 short; exit when RSI crosses 50, at a 0.5% stop, or at the close | 5m |
| 6 | EMA-X | EMA 9 / 21 cross: always in after the first cross, reversing on each cross; no new entries after 23:00 | 5m |
| 7 | MOM-LH-a | Sign of the 09:00 → 22:25 return; hold 22:25 → close (intraday momentum, Gao et al. 2018) | 5m |
| 8 | MOM-LH-b | Sign of the 18:30 → 22:25 return; hold 22:25 → close | 5m |
| 9 | EVT | Report day (crude Wednesday EIA, gas Thursday storage, 20:00 IST): trade in the direction of the 20:00 → 20:15 move from 20:15; stop at the 20:00 price; exit at the close | 5m |
| 10 | BB-BREAK | Close outside Bollinger 20/2: enter that way; exit when a close crosses the middle band, or at the close | 15m |
| 11 | GAP-FADE | 09:00 open more than 0.5% from the previous close of the same contract: fade it from 09:05; target the previous close; stop 0.5% further; exit at the close | 5m |
| 12 | LONG-DAY | Long 09:00 → close (benchmark) | 5m |
| 13 | LONG-US | Long 18:30 → close (benchmark) | 5m |
| 14 | MOM-LH-1h | Sign of the 09:00 → 22:00 hourly return; hold through the last hourly bar | 1h |
| 15 | EMA-X-1h | EMA 5 / 20 on hourly closes, the same as EMA-X, flat at the close | 1h |
| 16 | ORB-US-1h | The 18:30 hourly bar's range; first breakout after 19:30; stop at the other side; exit at the close | 1h |

## Verdicts (nothing is selected; every strategy is reported)
1. **Promising.** Every condition must hold:
   - net > 0 at 2-tick slippage;
   - net > 0 in BOTH halves of its window (split at the middle session);
   - t ≥ 3.0 on per-trade net returns. That is a Bonferroni bar for 32 tests: one strategy
     with no edge clears it about 0.13% of the time.
2. **Meets 2% a week.** Every condition must hold:
   - Promising;
   - the leverage that averages 2% a week fits the margin limit (crude 3.2×, gas 6.0×);
   - at least 75% of weeks are profitable at that leverage.

## Stop rule
- The fixed set runs once.
- No parameter is changed after seeing a result, and no strategy is added because of one.
- If nothing is promising, that is the answer for this data. Anything promising would still
  need months of new data (paper trading) before real money.
