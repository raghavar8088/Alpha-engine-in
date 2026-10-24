# Champion traders' intraday strategies — pre-registration

Written 2026-10-24, before any strategy in this folder was run. The data checks in `ch_checks.py` ran first; they decided only how the data is cleaned (section "Data"), never a rule. Any later change goes under "Changes after registration", with its reason.

## The question

The intraday traders named in the earlier answer: which of their published methods make money after costs, and do any reach the 2%-a-trade goal of the original gold brief?

| Trader | Intraday? | In this test |
|---|---|---|
| Toby Crabel | yes | the opening-range breakout with the "stretch", on every day and only after narrow-range days (NR4, NR7, ID/NR4) |
| Larry Williams | partly | the two rules he gives in a same-day form: the volatility breakout and the Oops! gap reversal (exit at the close) |
| Andrea Unger | partly | his three intraday building blocks: first-hours breakout, false-breakout reversal, time-of-day bias, and his habit of running a portfolio of them |
| Paul Rotter | yes | **not testable**: order-book scalping for a few ticks needs order-book data and an exchange member's costs; minute bars carry neither |
| Forex-contest winners | unknown | **not testable**: no published method |
| Michael Cook, Williams' swing rules | no | **out of scope**: held 2–5 days |

## Markets and periods

The test runs on gold, which is the brief, and on the markets the three traders built these rules for. No earlier study in this repository has examined the S&P 500, Nasdaq 100 or DAX data.

| Market | Session traded (local) | Data | In-sample | Out-of-sample |
|---|---|---|---|---|
| XAUUSD (gold) | COMEX day session 08:20–13:30 New York | HistData minutes, mid = bid + half Dukascopy's quoted spread (`../xauusd_intraday_2026_10`) | 2010-01-01 → 2021-09-30 | 2021-10-01 → 2026-10-16 |
| SPXUSD (S&P 500) | 09:30–16:00 New York | HistData minutes, mid = price + 0.125 pt | 2010-11-15 → 2021-09-30 | 2021-10-01 → 2026-10-16 |
| NSXUSD (Nasdaq 100) | 09:30–16:00 New York | HistData minutes, mid = price + 0.25 pt | 2010-11-15 → 2021-09-30 | 2021-10-01 → 2026-10-16 |
| GRXEUR (DAX) | 09:00–17:30 Frankfurt | HistData minutes, mid = price + 0.5 pt | 2010-11-15 → 2020-06-12 | 2023-12-04 → 2026-10-16 |

**Gold's out-of-sample period is not unseen.** The intraday and trader-style studies already used it, and it was a strong bull market. The clean out-of-sample tests are the three index markets.

**Unger's own rule decides which market a method suits.** Each market therefore chooses its own settings in-sample, and each market's out-of-sample run is its own test.

## Data (decided from `ch_checks.py`, before any strategy ran)

- **Clock.** HistData's timestamps are New York time with daylight saving, in every market. The busiest minutes sit at each session's open and at its known data times (08:30 and 10:00 New York, 14:30 Frankfurt) in summer and winter alike.
- **Regular session only, weekdays only.** A session needs at least 60% of its minutes. At 80%, quiet days, which have fewer quoted minutes, would be dropped too; 60% still removes half-days.
- **Cut out before anything else:**
  - every market, 2023-02-01 → 2023-07-31: HistData thins the feed to about half its minutes;
  - DAX, 2020-06-13 → 2023-12-03: HistData's GRXEUR file holds Euro Stoxx 50 prices (about 3,100–4,400) there.
- **Not traded:**
  - a session whose weekday predecessor was dropped (its "previous session" values would be stale);
  - the 10 sessions after any gap of more than 10 calendar days between kept sessions.
- **Contract rolls.**
  - S&P 500 and Nasdaq 100: the price change across each daily break shows no roll jumps. The largest are news, such as the 2 April 2025 tariffs and Apple's 2 January 2019 warning.
  - DAX: its index futures basis is small.
  - Gold: spot has no rolls.
- **WTI crude was fetched and dropped.** HistData has no WTI minutes for 2024 to May 2026, and the series jumps at monthly contract rolls (+35% over the weekend of 19 April 2020).

## Common rules

- **One trade a session per rule,** flat at the session's last minute. No new entry fills in the last 60 minutes.
- **Daily values come from completed sessions of the same regular session:**
  - the previous high, low and range;
  - ATR14 (Wilder, true range with the previous close);
  - the stretch: the 10-session mean of the open-to-nearer-extreme distance;
  - the 10-session mean range.
- **Fills** use the earlier studies' engine (`../xauusd_intraday_2026_10/xi_engine.py`):
  - stop and limit orders fill at their level, or at a worse open;
  - a stop touched in the entry minute counts against the trade;
  - a stop and a target in the same minute count as the stop.

## The rules and their settings (every combination is run in-sample)

1. **CRABEL_ORB** (Crabel 1990):
   - buy-stop at open + k × stretch and sell-stop at open − k × stretch; the first fill trades;
   - stop at the other level, or none;
   - out at the close.
   - Settings: k ∈ {0.5, 1.0, 1.5}, stop ∈ {opposite, none}. 6 configurations.
2. **CRABEL_NR:**
   - the same, only on sessions after an NR4 (narrowest range of 4 sessions), an NR7, or an inside day that is also an NR4.
   - Settings: pattern ∈ {NR4, NR7, ID_NR4} × the 6 above. 18 configurations.
3. **WILLIAMS_VBO** (Williams 1999, the day-trade form):
   - buy-stop at open + k × previous range (sell-stop below for shorts);
   - stop half the previous range from the entry, or none;
   - out at the close.
   - Settings: k ∈ {0.3, 0.5, 0.7}, direction ∈ {both, long}, stop ∈ {none, half_range}. 12 configurations.
4. **WILLIAMS_OOPS** (the intraday form):
   - opening below the previous low (by more than gap × ATR14) puts a buy-stop at that low; opening above the previous high puts a sell-stop at that high;
   - stop at the session's extreme before the entry, or none;
   - out at the close.
   - Settings: direction ∈ {both, long}, gap ∈ {0, 0.1}, stop ∈ {extreme, none}. 8 configurations.
5. **UNGER_RANGE** (his early DAX and S&P system):
   - OCO stops 0.01% beyond the high and low of the session's first 2 or 3 hours;
   - stop at the range's other side, or 0.5 × ATR14;
   - no target; out at the close;
   - anti-chop filter "compression": trade only after a session narrower than its 10-session mean.
   - Settings: hours ∈ {2, 3}, stop ∈ {opposite, atr}, filter ∈ {none, compression}. 8 configurations.
6. **UNGER_REVERSAL** (his DAX false-breakout reversal, intraday form):
   - on 15- or 30-minute bars, once price has traded above the previous high, the first bar to close back below it sells at the next bar's open; the mirror at the previous low buys;
   - stop at the extreme reached so far, or 0.25 × ATR14;
   - target 2R or none; out at the close.
   - Settings: tf ∈ {15, 30}, stop ∈ {extreme, atr}, target ∈ {none, 2R}. 8 configurations.
7. **UNGER_BIAS** (his time-of-day bias systems):
   - enter at the open or at a whole hour after it, hold 60 or 120 minutes, long or short.
   - Every start that leaves the holding time before the close: 18 configurations on gold, 22 on the US indices, 30 on the DAX.

**Configurations per market:** 78 on gold, 82 on the S&P 500 and the Nasdaq 100, 90 on the DAX. That is 332 in all.

## Costs (round trip = spread + 2 × slippage + 2 × commission, in price units)

| Market | Base (selection and verdicts) | Harsh | Note |
|---|---|---|---|
| Gold | spread $0.40, slippage $0.10 a side, commission $0.035/oz a side (= $0.67) | $0.50, $0.25, $0.05 (= $1.10) | retail CFD, as in the earlier gold studies; also reported: COMEX futures ($0.10, $0.10, $0.025 = $0.35) and Dukascopy's measured spread |
| S&P 500 | 0.25 pt, 0.125 pt, 0.05 pt (= 0.60 pt) | 2 × base | ES futures: one tick, half a tick of slippage a side, $2.50 a side |
| Nasdaq 100 | 0.5 pt, 0.25 pt, 0.125 pt (= 1.25 pt) | 2 × base | NQ futures |
| DAX | 1.0 pt, 0.5 pt, 0.1 pt (= 2.2 pt) | 2 × base | FDAX futures |

## Decisions, fixed now

- **Selection, per market and rule** (in-sample, base costs): among configurations with at least 100 trades, the highest t-statistic of the net return per trade. That one is locked (code hash) and run out-of-sample once, whatever its in-sample result.
- **Each locked rule is called EDGE** when all of these hold:
  - in-sample average > 0;
  - out-of-sample: at least 50 trades, average > 0 at base costs, and > 0 at harsh costs;
  - the one-sided test of a positive mean survives Holm's correction across all market-and-rule tests at 5% (normal approximation of the t-test);
  - the timing beats random placement with p < 0.05. For non-bias rules: the same side, entry minute and holding time on random out-of-sample days. For bias rules: the same days, side and holding time at a random minute of the session.
- **TARGET** (the brief's 2% a trade): EDGE, plus an average of at least +0.10% a trade in-sample and out-of-sample. That is 2% of the account at 20× leverage, the most allowed.
- **Anything else: NO EDGE.**
- **Unger's portfolio.** Every locked rule, on every market, whose in-sample average is > 0 joins it, with an equal share of the account. Daily returns are the share-weighted sum. The portfolio is WORKING when, out-of-sample:
  - its mean monthly return is > 0 with t ≥ 2 across months;
  - it stays > 0 at harsh costs.

  A gold-only version is reported alongside.

**Reported, not used to decide:**
- each rule's year-by-year results and its monthly returns on the account at 1×, 10× and 20×;
- the drawdown, ruin date and leverage needed for 2% a trade;
- long trades vs short trades;
- the bootstrap interval;
- gold at futures costs and at the measured spread;
- the earlier study's gold results for Crabel's breakout and Williams' breakout, defined there on the 18:00–17:00 day.

## Changes after registration

- **No rule, setting, cost or decision changed.** The lock (code `9d807cc9aad5ffd1`, lock `d54431d2ee79f68f`) was made once, and the out-of-sample run happened once.
- **Added after the out-of-sample run, reported only** (`ch_diagnostics.py`):
  - each member's share of the portfolio's result;
  - the portfolio without its best months;
  - a placebo portfolio with the same trades on random days;
  - an open-to-close drift benchmark;
  - leverage and cost ladders;
  - calendar years.
- **Wording only:** Rotter's target is described as "a few ticks", instead of "1–3 ticks".
