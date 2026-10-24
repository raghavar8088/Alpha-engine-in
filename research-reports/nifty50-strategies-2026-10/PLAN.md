# NIFTY 50 stocks: intraday momentum strategies from the first 15 minutes. Research plan (revised 24 Oct 2026)

## Scope
**Intraday only.** Decisions are made from 09:30 IST on. Every position is squared off at **15:10 IST** the
same day. There are no positional, swing or overnight trades.

**The question:** after the first three 5-minute candles (09:15, 09:20, 09:25) close, can we pick stocks
with strong buying or selling momentum, confirm it, and trade it within the session profitably after
real costs?

## What earlier work in this app already found
- **The Stock Selection study** (Sep 2024 – Oct 2026, 200 NSE stocks, 5-minute bars):
  - **Predictable: WHERE a stock will move** (relative volume, ATR%, gap, first-30-minute range).
  - **Not predictable: WHICH WAY.** Every directional screening rule flipped out of sample.
  - 5,184 opening-range-breakout variants: **none** passed the deflated-Sharpe test.
  - What held in both of its periods: stop-order entries beat confirmation entries; relative volume
    ≥ 1.5 helped; and entries had to be two-sided (one-sided ORB was a bet on the market's direction).
- **The average stock drift:** −7.5 bp during the session and +13 bp overnight. Intraday longs start
  with a headwind.
- **The app's intraday stock desks** lost −₹11.51 crore over a 2-year walk-forward.
- **A live paper test that must not be disturbed:** two pre-registered ORB strategies (`iv2_orb_sel15`,
  which enters from 09:30, and `iv2_orb_sel30`) are in the middle of it. This study does not touch or
  re-tune them; it compares against them.

**What is new here:**
- **Five years instead of two.** The 2021–2024 stretch has never been used for stock intraday research
  in this app.
- **Point-in-time NIFTY 50 members.**
- **A first-15-minute screen whose confirmation filters each have to prove their worth.**
- **Matched random-entry baselines.**

## Phase 0: data
1. **Universe:** the NIFTY 50 members on each date, from NSE's official index-change notices. That is
   about 60–70 stocks over five years. If the official history cannot be obtained cleanly, we use
   today's 50 plus every stock removed since 2021, and say so.
2. **5-minute OHLCV, Oct 2021 – Oct 2026, from Angel One:**
   - pulled on the server in a separate, memory-capped container (Angel logins are independent, so the
     live session is untouched);
   - run on a weekend or at night, when no desk needs the candle endpoint;
   - written to resumable files only, with nothing written to the database.
3. **Market context:** NIFTY 50 and the sector indices at 5 minutes (or equal-weight sector baskets
   built from members), plus India VIX daily.
4. **Quality checks:**
   - 75 candles in every full session;
   - missing, duplicate or zero-volume candles;
   - halted and special sessions (Muhurat trading excluded);
   - daily OHLC rebuilt from the 5-minute bars compared with NSE's official bhavcopy on sample days;
   - splits, bonuses and demergers detected (overnight jumps, volume steps) and matched to NSE corporate
     actions, so that multi-day features (volume averages, ATR, prior-day levels) are adjusted.
5. **The usable window:** if Angel's history does not reach Oct 2021 for every stock, the study starts
   where the data is complete, and the report says so.

## Phase 1: the 09:30 screen (only what is known at 09:30)
These are computed from the 09:15–09:25 candles and earlier days:
- **Opening-range move:** (09:30 price − 09:15 open) ÷ 14-day ATR. Gap: the 09:15 open against the
  previous close.
- **Opening-range position:** where the 09:30 price sits inside the 09:15–09:30 high–low range.
- **Relative volume:** first-15-minute volume ÷ its 20-session average (split-adjusted).
- **Price against VWAP** at 09:30, with VWAP measured from 09:15.
- **Relative strength:** the stock's first-15-minute return minus NIFTY's, and minus its sector's.

A pre-registered momentum score ranks the stocks. The long list is the top **5** bullish and the short
list the top **5** bearish; lists of 3 and 10 are run as neighbours.

## Phase 2: confirmation (each filter must earn its place)
**Candidates:**
- the price holding its side of VWAP;
- relative strength against NIFTY and the sector;
- relative volume ≥ 1.5;
- 5-minute EMA slope or ADX;
- position against the prior day's high and low;
- NIFTY agreeing in direction;
- the VIX regime.

**Method:** an ablation. Add one filter at a time to the base screen on development data, and judge it
on validation data. A filter stays only if it improves validation expectancy without cutting the trade
count below a minimum. No filter is assumed to help.

## Phase 3: a small set of setups (every rule frozen before the final test)
| Setup | Entry | Stop | Exit |
|---|---|---|---|
| **S1 · Opening-range breakout** | Two-sided stop orders at the 09:15–09:30 high and low, screened stocks only | The other side of the range (or its midpoint, as a neighbour) | Target at 1.5–2R, or the square-off |
| **S2 · Momentum continuation** | The next bar's open after 09:30, in the screen's direction | Beyond the opening range | Trail by VWAP or the 9-EMA; square-off |
| **S3 · Pullback entry** | After 09:30, the first pullback to VWAP or the 9-EMA that holds; enter on the bar that resumes the move | Beyond the pullback's extreme | Target 2R or a trail; square-off |

**Rules every setup shares:**
- risk 0.5% of ₹10 lakh per trade;
- exposure within the broker's intraday leverage (at most 5×);
- at most one re-entry after a stop;
- at most 5 trades a day;
- no new entries after 14:30;
- **square-off at 15:10**.

**Code reused:** the Strategy Factory's intraday detectors (ORB, VWAP reclaim, pullback + EMA + RSI +
VWAP, gap continuation), adapted to the 09:30 screen.

## Phase 4: a realistic backtest
- **Direction:** long and short **separately and combined**.
- **Periods, chronological:**
  - **development:** Oct 2021 – Dec 2023;
  - **validation:** Jan – Dec 2024;
  - **final test:** Jan 2025 – Oct 2026, **run once**.

  The final test overlaps the earlier ORB study's data (Sep 2024 onward). Its findings are treated as
  known, and paper trading is the only fully clean test.
- **Costs:** Angel's intraday card from `angel_fees.py`:
  - brokerage min(₹20, 0.25%) per order;
  - STT 0.025% on sells and stamp 0.003% on buys;
  - exchange charges, SEBI fee and 18% GST.
- **Slippage:** each stock's half-spread, estimated from its own 5-minute prices (Roll / Corwin–Schultz,
  as in the index study), plus 2 bp. Stop orders fill at the stop or worse, never better.
- **Liquidity:** a position is at most 1% of the stock's average 5-minute traded value at entry.
- **Shorts:** cash-market intraday shorts, squared off the same day under Angel's rules. Our 15:10
  square-off comes before the broker's automatic one.
- **No look-ahead:**
  - the screen uses only candles closed by 09:30;
  - indicators use closed candles only;
  - fills come at the next bar's open or through stop orders;
  - if one candle hits both the stop and the target, the stop counts.

## Phase 5: the evidence
**Baselines:**
- plain two-sided ORB on all members, with no screen;
- **matched random entries** (same stock-days, entry times, stops, targets and sizing), once with a
  random direction and once with the same direction (which tests timing alone);
- the app's two incubating ORB strategies, where comparable.

**Reported:**
- net return (₹ and % of ₹10 lakh), win rate, average R achieved, profit factor;
- maximum drawdown, trade count, weekly returns;
- results by year, stock, sector, trend day vs range day, VIX regime and gap size.

**Robustness:**
- costs ×1.5 and ×2;
- slippage + 5 bp;
- nearby parameters (list size, a 15- vs 30-minute range, stop and target);
- without the best stock or year;
- a deflated Sharpe over every variant tried.

**A "reliable edge" needs all of:**
- final-test net > 0 after costs, and also at 2× costs;
- beats the matched random baseline with t ≥ 2.5;
- deflated Sharpe ≥ 0.95;
- positive in each year of development and validation;
- no single stock more than 20% of the profit;
- nearby parameters also positive.

## Phase 6: the deliverable
- **If anything passes:**
  - a one-page rule card per strategy with every exact rule;
  - reproducible code and data checksums;
  - a paper-trading plan: 8–12 weeks on an existing desk, judged against the backtest's range, with no
    real money.
- **If nothing passes:** the report says so plainly and shows what came closest.

## Stop rule and pre-registration
- The pre-registration is written and fingerprinted after Phase 0's data checks and before any strategy
  result.
- The search ends when Phases 1–5 are complete. It is never extended until a number appears.

## Time
| Phase | Effort |
|---|---|
| 0 Data and checks | 1 session (the pull takes about an hour, unattended, on a weekend or at night) |
| 1–2 Screen and ablations | 1 session |
| 3–4 Setups and backtest | 1–2 sessions |
| 5–6 Evidence and report | 1 session |

## What to expect, honestly
- The earlier study's main finding (direction not predictable from screens; no ORB variant passed) makes
  a strong edge unlikely. The controls are there to tell a real edge from luck.
- Intraday costs for NIFTY 50 stocks are about 5–8 bp a round trip, so a strategy must average well
  above that on every trade.
- 2% a week is not a planning assumption.

## Governance
- Research only: nothing in the app changes, and all data is read-only.
- Your reset plan's rule 2 (one idea at a time) and rule 7 (no short-hold strategies with real money)
  apply.
