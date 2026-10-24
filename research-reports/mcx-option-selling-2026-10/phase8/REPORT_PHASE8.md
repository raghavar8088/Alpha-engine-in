# Phase 8: INTRADAY strategies on real MCX crude-oil and natural-gas bars (24 Oct 2026)

## The answer first
**What was tested:** **32 intraday strategies**, 16 classic types each on crude oil and natural
gas:
- opening-range and previous-day breakouts;
- VWAP and RSI(2) mean reversion;
- EMA trend;
- last-hour intraday momentum;
- inventory-report reaction and gap fades;
- "long the session" benchmarks.

**How:** every position was flat by the 23:30 close. The prices were **real MCX bars your app
recorded from Angel One**: 5-minute bars from 6 Aug to 23 Oct 2026, hourly bars from 22 May.
Trades paid Angel's charges plus one tick of slippage each way. The set was pre-registered
before any run (`AMENDMENT_A8.md`) and nothing was tuned.

**What happened:**
- **1 of 32 passed the strict bar, and it is not an intraday edge.** The pass was "buy crude at
  the US open (18:30 IST) and sell at the MCX close". It made +35.6% (t 3.26) and was profitable
  in 92% of weeks, but those weeks were a **37% crude rally** (₹7,140 → ₹9,796).
  - In May–Aug 2026, when crude **fell 24%**, the same trade **lost 6.7%**.
  - Over **every MCX session since 2005**, buying at the open and selling at the close **lost 8
    bp a day after costs** (t −2.95); only 5 of 22 years were positive.
- **Mean reversion lost heavily and consistently.**
  - RSI(2): crude −47% from 1,142 trades; natural gas −105%.
  - VWAP fade: crude t −5.0; natural gas t −2.9.

  Many small trades in a trending market pay costs and lose.
- **Natural gas: almost every intraday strategy lost.** Over 20 years, buying at the open and
  selling at the close lost 22 bp a day (t −5.8).
- **One idea is worth watching, but it is not proven.** It is crude **last-hour momentum**:
  take the side of the day's move at 22:25 and hold to the close (Gao, Han, Li & Zhou 2018).
  - It made +9.7% from 53 trades (t 2.08), positive in both halves, profitable in 83% of weeks,
    about +0.8% a week at 1× exposure.
  - On verified days only: +10.1%, t 2.56.
  - It is below the bar, it covers a trending stretch, and it has only 53 trades.
- **2% a week:** only the rally trade got there, and that is not a real edge.
- **A data warning.** Your app's stored bars match MCX's official daily prices on about 72% of
  5-minute days, but on only **about 20% of hourly days**: the store spliced contracts before the
  5 Oct fix. The best-looking hourly result (crude EMA 5/20, +47.6%) **lost 8.8% on verified
  days**.

## 1. All 32 strategies (the pre-registered run)
- **Net** = % of a ₹10 lakh account at 1× exposure (₹10 lakh notional per trade).
- **t** = the t-statistic on per-trade results.
- **Weeks +** = the share of weeks with a profit.

| Strategy | Bars | Crude: trades | net | t | weeks + | Natural gas: trades | net | t | weeks + |
|---|---|---|---|---|---|---|---|---|---|
| ORB-AM (09:00–09:30 range breakout) | 5m | 52 | −7.8% | −0.82 | 42% | 53 | −6.0% | −0.54 | 42% |
| ORB-US (18:30–19:00 range breakout) | 5m | 54 | −5.5% | −0.69 | 33% | 53 | −2.4% | −0.30 | 33% |
| PDHL (previous-day high/low breakout) | 5m | 39 | +11.8% | 0.90 | 58% | 42 | −4.1% | −0.35 | 42% |
| VWAP-REV (2σ fade to VWAP) | 5m | 161 | −12.8% | **−4.97** | 8% | 159 | −8.4% | −2.86 | 33% |
| RSI2 (10/90) | 5m | 1,142 | **−46.7%** | −4.84 | 0% | 1,142 | **−104.6%** | −9.91 | 0% |
| EMA-X (9/21) | 5m | 462 | +14.4% | 0.84 | 75% | 520 | −34.5% | −1.92 | 33% |
| **MOM-LH-a (day's move at 22:25 → close)** | 5m | 53 | **+9.7%** | **2.08** | **83%** | 53 | −1.2% | −0.37 | 42% |
| MOM-LH-b (move since 18:30) | 5m | 53 | −3.0% | −0.61 | 67% | 54 | +1.0% | 0.31 | 58% |
| EVT (report-day 20:00 reaction) | 5m | 11 | +1.1% | 0.63 | 33% | 12 | +7.9% | 1.08 | 50% |
| BB-BREAK (Bollinger 20/2) | 15m | 114 | +9.4% | 0.68 | 50% | 123 | −13.8% | −1.07 | 36% |
| GAP-FADE (> 0.5% gap) | 5m | 33 | −6.3% | −1.30 | 25% | 35 | −15.9% | −2.56 | 33% |
| LONG-DAY (benchmark) | 5m | 53 | +40.3% | 2.34 | 75% | 53 | −8.9% | −0.51 | 50% |
| **LONG-US (benchmark)** | 5m | 54 | **+35.6%** | **3.26** | **92%** | 54 | +5.4% | 0.37 | 50% |
| MOM-LH-1h | 1h | 104 | +15.4% | 1.61 | 65% | 101 | −1.4% | −0.23 | 39% |
| EMA-X-1h (5/20) | 1h | 168 | +47.6% | 1.68 | 65% | 178 | −7.8% | −0.33 | 43% |
| ORB-US-1h | 1h | 105 | −9.9% | −0.82 | 39% | 102 | +11.3% | 0.76 | 48% |

- **Pass bar:** t ≥ 3.0 (a Bonferroni bar for 32 tests), positive in both halves, and positive at
  2-tick slippage. Only crude LONG-US passed.
- **Costs:** a round trip costs 2.19 bp plus 2 ticks. That is about 2–3 bp more in crude and 7–8
  bp more in natural gas.

## 2. Is the one pass an intraday edge? No. It is the rally
| Check | Result |
|---|---|
| Crude in the test window | **+37%** (₹7,140 → ₹9,796), all of it during MCX hours (+47% summed) while the nights gave back 17% |
| The same trade, 22 May – 5 Aug 2026 (crude −24%; hourly bars) | 18:00 → close **−6.7%**; 09:00 → close −21.9% |
| Natural gas, the same window | 18:00 → close −22.2%; 09:00 → close −25.4% |
| **Crude, every session since 2005** (MCX daily open → close, same costs) | **−8.1 bp a day, t −2.95**; 5 of 22 years positive; −0.85 bp before costs |
| **Gas, every session since 2006** | **−21.8 bp a day, t −5.82**; 1 of 21 years positive |

Crude rose during the MCX session in Aug–Oct 2026 and fell in the months before. There is no
lasting session drift for a long position to collect.

## 3. Data quality: how far to trust the bars
Each day's stored open, high and low were compared with MCX's official daily record for the same
contract. The kept days are those that agree, or whose three prices are all shifted alike (which
means a whole day of one other contract).

| | 5-minute | 15-minute | 1-hour |
|---|---|---|---|
| Crude days verified | 39 of 54 | 24 of 65 | **21 of 105** |
| Gas days verified | 39 of 54 | 25 of 66 | **21 of 103** |

**Rerunning all 32 strategies on verified days only:**
- crude LONG-US +22.9% (t 2.96);
- crude LONG-DAY +27.9% (t 1.95);
- **crude MOM-LH-a +10.1% (t 2.56, positive in both halves)**;
- crude EMA-X-1h **−8.8%**;
- mean reversion still lost (VWAP t −5.5, RSI2 −38%);
- natural gas: still nothing.

The hourly store is mostly spliced data from before the 5 Oct fix. Treat every hourly result
above as unreliable.

## 4. What I would do
1. **Do not trade any of these intraday strategies with real money.** The only pass is a bet on a
   crude rally, and mean reversion loses after costs.
2. **If you want one intraday idea tested properly, make it crude last-hour momentum (MOM-LH-a).**
   - Freeze its rule exactly as it is now.
   - Keep the app recording 5-minute crude bars.
   - Judge it on the next ~6 months of NEW data with a single pre-registered check.
   - At about +0.8% a week it would still be far from 2%.
3. **For better intraday research,** multi-year 1-minute history (e.g. bought from TrueData or
   Global Datafeeds) would allow a real test instead of 11 weeks.
4. **Your plan's rules apply:** "no short-hold strategies" and "one idea at a time". These are
   research results, not trades.

## 5. How it was tested
- **Pre-registration:**
  - `AMENDMENT_A8.md` (sha256 `30d16ca5…`, 18:00 on 24 Oct) fixed the 32 strategies, the costs,
    the bar and the stop rule before any run;
  - `AMENDMENT_A8_1.md` (`6dae9b2f…`, 18:01) corrected the hourly ORB's bar, also before any run.
- **Data:** a read-only export of the app's `commodity_bars`, done in a throwaway, memory-capped
  container on the server (`export_bars.py`) and deleted from the server afterwards. The live
  backend was not touched.
- **Engine checks** (`test_engine8.py`, 10 checks, all pass):
  - breakout fills and gapped stops;
  - a bar spanning both sides counts as a loss;
  - the stop counts before the target;
  - RSI(2) matches a hand calculation;
  - no look-ahead;
  - a real session reproduces by hand.
- **Fills:** at the next bar's open after the signal, breakouts at the level (or the gapped
  open), flat by the close, one position at a time.

## 6. Disclosures
- **The first run crashed on a print bug.** It stopped after printing two lines (crude ORB-AM and
  ORB-US), from a "%" in an output label. The identical set was rerun after the fix; the code
  that computes results did not change.
- **Sections 2 and 3 are descriptive.** They were run after the one-time result and do not change
  it.
- **11 weeks (5m) to 22 weeks (1h) cannot prove a weekly edge**, as A8 stated in advance.
- **Report days are taken by weekday.** Holiday weeks, which shift the reports, were not
  adjusted.

## Files (`phase8/`)
| File | What it is |
|---|---|
| `AMENDMENT_A8.md`, `AMENDMENT_A8_1.md` (+ `.sha256`) | Pre-registration and its clarification |
| `export_bars.py` | The read-only export of the app's recorded bars |
| `engine8.py` | The intraday engine and the 16 strategy types |
| `test_engine8.py` | 10 checks |
| `run_phase8.py` | The one-time run |
| `robust8.py` | The rally checks, the 20-year session drift, the verified-days rerun |
| `results/` | Per-strategy summary, every trade, robustness JSON, run logs (the raw bars are not committed) |
