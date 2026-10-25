# Pre-registration A1: NIFTY 50 intraday momentum from the first 15 minutes (2026-10-25, after the Phase 0 data checks, before any strategy result)

Every rule below is fixed now. A rule that turns out to be ambiguous in code is resolved in the
direction that makes results worse, and the report discloses it.

## 1. Universe and data
- **Members:** NIFTY 50 members on each date, from `phase0/membership.json`. The BSE-for-WIPRO swap is
  taken on 2026-03-31; 2026-09-30 is run as a sensitivity.
- **Data:** 5-minute candles from `phase0/n50_clean.pkl` (sha256 `ada44df0…`).
- **A stock-day is eligible when all of these hold:**
  - the stock is a member that day;
  - its session has at least 70 candles;
  - its 09:15, 09:20 and 09:25 candles exist;
  - it has at least 20 earlier sessions.

## 2. The 09:30 screen (only the 09:15, 09:20 and 09:25 candles, plus earlier days)
| Feature | Definition |
|---|---|
| O, H15, L15, P, V15 | the 09:15 open; the highest high and lowest low of the three candles; the 09:25 candle's close; their total volume |
| ATR14 | the mean true range of the previous 14 sessions (daily high and low from the candles; true range uses the previous last close) |
| **or_move** | (P − O) ÷ ATR14 |
| gap | O ÷ the previous session's last close − 1 |
| or_pos | (P − L15) ÷ (H15 − L15) |
| rvol | V15 ÷ the mean V15 of the previous 20 sessions |
| VWAP15 | Σ(typical price × volume) ÷ Σvolume over the three candles; typical price = (h + l + c) ÷ 3 |
| rs_nifty | (P ÷ O − 1) − the same for NIFTY |
| rs_sector | (P ÷ O − 1) − the same for the stock's sector index (`SECTOR_INDEX`; NIFTY when unmapped) |

**Base screen:**
- **Long candidates:** or_move ≥ +0.25, ranked by or_move.
- **Short candidates:** or_move ≤ −0.25, ranked by −or_move.
- At most the top **N = 5** on each side.

## 3. Confirmation filters (each must earn its place)
Each filter is stated for longs; shorts use the mirror image.

| Code | Filter |
|---|---|
| F1 | rvol ≥ 1.5 |
| F2 | P > VWAP15 |
| F3 | rs_nifty > 0 |
| F4 | rs_sector > 0 |
| F5 | or_pos ≥ 0.75 |
| F6 | NIFTY's own (P ÷ O − 1) > 0 |
| F7 | gap > 0 |
| F8 | P > the previous session's high |

**Selection is greedy forward selection, per setup and side:**
1. Start from the base screen.
2. For each filter not yet added, compute the mean net R per trade on development data and on
   validation data.
3. Add the filter with the largest validation gain, provided it raises BOTH means and leaves at least
   100 trades in each period.
4. Repeat. Stop when no filter qualifies, or after 3 filters.

The resulting configuration is frozen before the final test.

## 4. The setups
| | S1 · Opening-range breakout | S2 · Momentum continuation | S3 · Pullback entry |
|---|---|---|---|
| **Entry** | A stop order at H15, live from the 09:30 candle to 11:30. Fill at max(H15, the candle's open) plus slippage | At the 09:30 candle's open | After 09:30, a candle whose low touches the session VWAP, then a later candle that closes above that candle's high. Enter at the next open, signal by 13:30 |
| **Stop** | L15 | L15 | the lowest low from the touch to the signal |
| **Target** | 2R | none: a VWAP trail exits at the next open after a 5-minute close below the session VWAP | 2R |

All three square off at the 15:10 candle's open. Shorts use the mirror image throughout. The session
VWAP accumulates from 09:15.

**Rules every setup shares:**
- **One trade per stock per day per setup.** No re-entry.
- **Sizing:** risk ₹5,000 per trade (0.5% of ₹10 lakh); quantity = ₹5,000 ÷ |entry − stop|.
- **Caps on the quantity:**
  - notional at most ₹10 lakh;
  - notional at most 1% of the stock's average 5-minute turnover over the previous 20 sessions.
- **Portfolio limits:** at most 5 positions open at once; total notional at most ₹50 lakh (5×); at most
  5 new entries a day. Candidates are taken in screen-rank order.
- **Inside a candle:** if one candle could reach both the stop and the target, the stop counts. The
  entry candle is checked for the stop too. A stop the market gaps through fills at the open. Targets
  fill at the level only when traded through.

## 5. Costs (Angel One intraday, `angel_fees.py` INTRADAY)
**Charges:**
- brokerage min(₹20, 0.25% × turnover) per order;
- STT 0.025% on the sell leg (for a short, the entry);
- stamp 0.003% on the buy leg;
- exchange 0.00297%, SEBI 0.0001% and IPFT 0.0001% on both legs;
- GST 18% on brokerage, exchange, SEBI and IPFT.

**Slippage:** each side pays the stock's half-spread plus 2 bp. The half-spread is the Corwin–Schultz
estimate per stock and calendar year from its 5-minute highs and lows, floored at 1 bp.

**Shorts:** cash-market intraday shorts, squared off the same day.

## 6. Periods
| Period | Dates |
|---|---|
| Development | 1 Oct 2021 – 31 Dec 2023 |
| Validation | 1 Jan – 31 Dec 2024 |
| **Final test** | **1 Jan 2025 – 23 Oct 2026, run ONCE** |

**Runs:** long only, short only, and combined (both sides; the 5-position cap applies across both;
ranking by |or_move|).

## 7. Baselines (on the same periods)
- **B1:** a plain two-sided ORB on every eligible member, with no screen and no minimum move. It uses
  OCO stop orders at H15 and L15 (09:30–11:30), the stop at the other side, a 2R target and the 15:10
  square-off. The first 5 triggers each day are taken.
- **B2:** matched random entries. For each strategy trade, the same stock-day, a uniformly random
  entry candle from 09:30 to 11:25, a **random direction**, the same stop distance in ATR, a 2R target
  and the same square-off and sizing. Drawn 200 times.
- **B3:** the same as B2 but in the **screen's direction**. This tests the timing of the entry, not
  the direction.

## 8. Reporting
**Measures:**
- net ₹ and % of ₹10 lakh (no compounding);
- win rate, mean net R, profit factor;
- maximum drawdown, number of trades, weekly returns.

**Broken down by:** year, stock, sector, trend day vs range day (|NIFTY day return| > 1%), the VIX regime
(prior-day close against its 60-day median), and gap-size buckets.

**Robustness:**
- costs ×1.5 and ×2;
- slippage +5 bp;
- N = 3 and 10;
- an or_move threshold of 0.15 and 0.35;
- a 30-minute range (09:15–09:45) instead of 15 minutes;
- the stop at the range midpoint;
- targets of 1.5R and 3R;
- without the best stock, and without the best year.

## 9. A "reliable edge" needs all of
- final-test net > 0 after costs, and also at 2× costs;
- mean net R above B2's with t ≥ 2.5 (against B2's draws);
- deflated Sharpe ≥ 0.95, counting every configuration evaluated (all ablation steps and robustness
  variants);
- net > 0 in each of 2022, 2023 and 2024;
- no single stock above 20% of the net profit;
- every robustness variant still net > 0.

## 10. Stop rule
- The final test runs once, for the frozen configurations.
- Nothing is changed afterwards and nothing is added because of a result.
- If nothing passes, the report says so, and shows the closest result next to its baselines.
