# Trader-style gold setups — pre-registration

Written 2026-10-24, before any result of this study existed. The code in this folder implements exactly this. Any later change is listed under "Changes after registration" with its reason.

## What is being tested

Discretionary gold traders who reportedly make money describe the same practices:
- they risk 0.5–1% of the account per trade with a fixed stop;
- they aim for 2–3 times what they risk;
- they trade one or two setups at fixed times;
- they trade only with the trend;
- they keep costs low.

Risk control changes how fast an account wins or loses. It does not decide *whether* it wins: that depends on the setup's average result per trade in R (R = the amount risked). So the question is whether trend-aligned session setups, with these rules, have a positive expectancy after costs.

## Known contamination, and the clean test

Gold 2021-10 → 2026-10 was already the out-of-sample period of the intraday study (`../xauusd_intraday_2026_10`). It was a strong bull market, which favours long trades. So gold's out-of-sample period is **not unseen**.

The clean test runs the rules locked on gold 2010–2021, unchanged, on **XAGUSD, EURUSD and GBPUSD**, from 2010-01-01 to the latest data. No study here has examined those markets. If these practices carry a real edge, it should not be specific to gold.

## Common rules

- Intraday only: flat by 16:59 New York, at most one trade a day per setup.
- Sessions roll at 17:00 New York. Indicators use completed sessions or earlier minutes only, and entries come on a later minute than the decision.
- **Trend filter**, from completed sessions:
  - "20/50": UP when close > SMA50 and SMA20 > SMA50; DOWN when close < SMA50 and SMA20 < SMA50.
  - "50/200": the same with SMA50 and SMA200.
  - Otherwise there is no trade.
- **ATR14:** the daily Wilder ATR from completed sessions.

## The three setups

1. **LONDON: London-open breakout with the trend.**
   - The Asian range is 20:00–02:59 New York.
   - From 03:00 to 07:59, place a buy stop 0.02% above the range high on UP days, or a sell stop 0.02% below the low on DOWN days.
   - Skip the day if the range is above 0.8×ATR14 or below 0.1×ATR14.
   - The stop is the far side of the range, capped at 0.5×ATR14.
   - Target k×R; exit at 11:59 or 16:59.
2. **NY_PULLBACK: New York pullback with the trend.**
   - Uses 5-minute bars and an EMA20 of 5-minute closes.
   - From 08:30 to 11:59 on UP days: after a 5-minute close below the EMA20, the first close back above it buys at the next bar's open. DOWN days mirror this.
   - The stop is the lowest low of the last six 5-minute bars, less 0.02%. It must be between 0.1×ATR14 and 0.5×ATR14 away, or the signal is skipped.
   - Target k×R, an optional break-even at 1R, and an exit at 16:59.
3. **NY_ORB: New York opening-range breakout with the trend.**
   - The opening range is the 30 minutes from 08:20.
   - From 08:50 to 11:59, place a buy stop 0.02% above the range high on UP days, or a sell stop below the low on DOWN days.
   - The stop is the far side of the range; skip unless it is between 0.1 and 0.5×ATR14 away.
   - Target k×R, an optional break-even at 1R, and an exit at 16:59.

**Grid per setup:** k ∈ {2, 3}, trend filter ∈ {20/50, 50/200}, and LONDON exit ∈ {11:59, 16:59} or NY break-even ∈ {off, 1R}. That is 8 configurations each, 24 in total.

## Measurement

- **Each trade in R:** the net price move after costs, divided by the stop distance at entry.
- **Account:** position size = risk% × equity ÷ stop distance, capped at 20× leverage. Under the cap, the realised risk is smaller.
- **Risk levels reported:** 0.5% and 1% of the account per trade.

## Costs, per side unless stated

| Market | Low-cost | Base (used to select and pass) | Harsh |
|---|---|---|---|
| XAUUSD | spread $0.25 (round trip), slippage $0.05, commission $0.035/oz | $0.40, $0.10, $0.035 | $0.50, $0.25, $0.05 |
| XAGUSD | — | spread $0.025, slippage $0.005, commission $0.0007/oz | 2× base |
| EURUSD | — | spread 0.2 pip, slippage 0.1 pip, commission 0.35 pip | 2× base |
| GBPUSD | — | spread 0.4 pip, slippage 0.2 pip, commission 0.35 pip | 2× base |

**Mid prices:** gold uses bid + half Dukascopy's quoted hourly spread, as in the intraday study. The other markets use bid + half the base spread. No overnight financing applies, since every trade closes the same day.

## Decisions, fixed now

- **Selection** (gold, 2010-01-01 → 2021-09-30, base costs): within each setup, among configurations with ≥ 100 trades and expectancy ≥ +0.15R, take the highest t-statistic of R. A setup with no such configuration fails.
- **Gold out-of-sample** (2021-10-01 → latest): passes with ≥ 40 trades, expectancy ≥ +0.15R and profit factor > 1.2.
- **Cross-market confirmation** (locked rules unchanged, 2010-01-01 → latest, base costs): expectancy > 0 in at least 2 of XAGUSD, EURUSD and GBPUSD.
- **A setup is WORKING only if it passes gold out-of-sample AND is confirmed cross-market.**
- **Why +0.15R:** at 1% risk, that is +0.15% of the account per trade. At 5–15 trades a month it comes to about 1–2% a month, which a disciplined professional would accept.

**Reported, not used to decide:**
- long trades vs short trades;
- a random-entry test: same side, same entry minute of the session, same holding time, random days;
- low-cost and harsh costs;
- the account at 0.5% and 1% risk: monthly returns, maximum drawdown and the longest losing streak.

## Changes after registration

None yet.
