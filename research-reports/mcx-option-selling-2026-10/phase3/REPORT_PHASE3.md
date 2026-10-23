# Phase 3: more strategy types, and a second untouched test period (23 Oct 2026)

## The answer first
- I backtested **140 more variants in 11 new strategy families**:
  - crude: calendars, ratio spreads, delta-hedged strangles, a cheaper hedge band, rolled strangles, expiry-week selling;
  - natural gas: calendars, a calm-volatility hedged straddle, seasonal selling, rolls, ratios.
- I also found a period that **no strategy had ever been tested on: Jun 2018 – Dec 2019**, 19 monthly cycles of crude options. Every crude strategy, new or old, now had to pass **both** that period and Jun 2024 – Oct 2026.
- **New strategies: 1 of 6 candidates passed.** It is **G2**, a natural-gas delta-hedged straddle traded only when implied volatility is calm. It is fragile (details below), so it is for paper trading only.
- **Earlier strategies on 2018–19, their first test there: 2 of 6 held up, CO-1 and CO-2.**
  - **C-E**, Phase 2's "strongest", only broke even in 2018–19 and missed the bar.
  - **C-B, C-C and CO-3 failed.**

### The new families
- **Units:** K3, K4 and G2 are per 10 lots; the rest are per lot of the structure.
- **Prices:** "2018–19" uses CRUDEOIL (parent) prices at the mini's lot size. "2024–26" uses the minis' own prices.

| | Family | Variant picked on old data | 2018–19 test | 2024–26 test | Verdict |
|---|---|---|---|---|---|
| K1 | Crude **calendar** (sell this month, buy next month, same strike) | none | | | ❌ can't be filled (see below) |
| K2 | Crude **ratio** (buy 1, sell 2 further out) | none (the most profitable had t 1.41, below 1.5) | | | ❌ |
| K3 | Crude **delta-hedged strangle**, delta 0.35, 15 days out | +₹3,70,019, PF 4.20 | **−₹36,784**, PF 0.65 | +₹1,40,074 | ❌ |
| K4 | C-E with a **cheaper hedge**: re-hedge only when 2+ lots off, 10 days out | +₹3,76,831, PF 4.21 | +₹5,028, PF 1.06; **−₹2,965 at 2× slippage** | +₹2,29,997 | ❌ |
| K5 | Crude **rolled strangle**: delta 0.15; roll a side when its delta passes 0.40 | +₹20,279 | −₹2,372 | −₹2,376 | ❌ lost in both |
| K6 | Crude **expiry-week strangle**, delta 0.20, 2 days out | +₹16,461, PF 7.90, 53 trades | **−₹2,712**, PF 0.51 | +₹10,164, PF 3.35 | ❌ |
| G1 | Natural-gas calendar | none | (no natural-gas options then) | | ❌ can't be filled |
| **G2** | **Natural-gas calm-IV delta-hedged ATM straddle**, 10 days out, only when IV ≤ its 1-year median | +₹96,341, PF 5.08, 16 trades | (no data) | **+₹62,743**, PF 1.68, 15 trades | ✅ **passed, fragile** |
| G3 | Natural-gas seasonal strangle (Apr–Oct expiries only) | none (1 of 12 variants even positive) | | | ❌ |
| G4 | Natural-gas rolled strangle | none (1 of 8 positive) | | | ❌ |
| G5 | Natural-gas put ratio (buy 1 at delta 0.25, sell 2 at 0.10) | +₹39,636, PF 2.99 | | +₹992, PF 1.05; −₹221 at 2× slippage | ❌ |

### The earlier strategies, on 2018–19 for the first time
| Strategy | 2024–26 (its earlier test) | **2018–19 (new)** | Verdict now |
|---|---|---|---|
| **CO-1**: crude put 0.5 straddle below, 15 days, IV > RV, stop 2× | +₹12,088 per lot | **+₹5,026**: 11 trades, 91% wins, PF 3.33, both years positive | ✅ **passed twice** |
| **CO-2**: crude trend-aware, 1 straddle out, 15 days, stop 1× | +₹8,690 | **+₹1,576**: 7 trades, PF 2.97, both years positive | ✅ **passed twice** |
| CO-3: crude trend-aware, 0.5 out, 10 days, stop 2× | +₹10,260 | −₹347, PF 0.92 | ❌ |
| C-B: crude put at delta 0.15, 5 days, no stop | +₹2,984 | −₹1,136, PF 0.61 | ❌ |
| C-C: crude strangle at delta 0.15, 5 days, no stop | +₹4,386 | +₹163, PF 1.06 | ❌ |
| C-E: crude delta-hedged straddle (per 10 lots) | +₹2,35,909 | +₹9,514, PF 1.11 (needed 1.15): about break-even on ~₹3.2 lakh | ❌ missed the bar |

**Why the stops mattered:**
- **C-B and C-C** have no stop. One cycle wiped out nearly all of their 18-month gains: entry on 10 Jul 2018, and crude dropped sharply the next day.
  - C-B: −₹2,457, against 16 small wins totalling +₹1,798.
  - C-C: −₹2,352, against +₹2,931.
- **CO-1 and CO-2** have stops. Their worst 2018–19 trades were cut at −₹2,161 and −₹799.

## What is standing now (Phases 1–3)
| Strategy | Evidence | Status |
|---|---|---|
| **CO-1** crude put, IV filter, stop 2× | Passed two separate untouched periods (2024–26 and 2018–19) | ✅ strongest |
| **CO-2** crude trend-aware, stop 1× | Passed both periods (only 7 trades in 2018–19) | ✅ |
| **N-B** natural-gas calm-IV strangle, delta 0.10 | Passed 2024–26, the only untouched period natural gas has | ✅ one period |
| G2 natural-gas calm-IV hedged straddle | Passed 2024–26, but all its profit came in 2026 | 🟡 paper only |
| C-E crude delta-hedged straddle | Big profits 2020–26, break-even 2018–19 | 🟡 paper only |
| CO-5, NG-X (Phase 1) | Weak / unvalidated; not re-tested | unchanged |
| CO-3, C-B, C-C | Failed 2018–19 | ❌ drop |

## ₹10 lakh: what the portfolios made in each period
| | Holdings | Jun 2024 – Oct 2026 (29 months, minis' prices) | Jun 2018 – Dec 2019 (19 months; crude only, as natural-gas options did not exist yet) |
|---|---|---|---|
| **A.** Phase 2 portfolio | C-E 5 lots, CO-1 3, CO-2 3, N-B 5 | **+₹1,88,108** (18.8%)<br>worst month −₹35,650<br>max drawdown ₹36,267<br>up to ₹8.3 lakh in use | **+₹21,813** (2.2%), of which C-E only +₹2,010<br>worst month −₹19,652 (C-E, Sep 2019) |
| **B.** Revised after the tests | CO-1 3, CO-2 3, N-B 5, G2 5 | +₹1,08,861 (10.9%): 2024 +₹10,872, 2025 +₹3,800, 2026 +₹94,189<br>max drawdown ₹34,843 | +₹19,804 (2.0%) |
| **C.** B without G2 | CO-1 3, CO-2 3, N-B 5 | **+₹93,767** (9.4%), **every year positive** (₹27,005 / ₹19,284 / ₹47,478)<br>22 of 29 months positive<br>worst month −₹18,420<br>max drawdown ₹18,941<br>at most ₹3.5 lakh in use | **+₹19,804** (2.0%)<br>worst month −₹6,484 |

- **Last 30 days** (exits 23 Sep – 23 Oct 2026): A +₹32,106, B +₹18,566, C +₹14,066.
- **How drawdowns are measured:** at month ends, as in Phase 2. Measured trade by trade they are A ₹46,086, B ₹40,138 and C ₹27,872.
- **Lot scaling:** multi-lot results are per-lot results × lots, except the hedged straddles, which were simulated at their real lot count because whole-lot hedging changes with size.

What this means:
- **A's extra profit over C is exactly C-E's** (+₹94,341), and C-E made only ₹2,010 at 5 lots in 2018–19.
- **C is the set that survived every test it faced.** In 2024–26 it made about ₹3,200 a month on ₹10 lakh, using at most ₹3.5 lakh of margin; the rest sat idle.
- **Its crude part made 2% in 2018–19.** Expect thin years.
- **Bigger positions scale losses as much as profits.** Doubling every position roughly doubles both. Fills at a larger size were not tested.
- **B was fixed in code before the robustness results were printed.** C was added after G2's fragility showed up.

## Why C-E weakened in 2018–19
C-E sells an ATM straddle and hedges away the direction every day. Its profit is therefore roughly the gap between the implied vol it sold and the volatility that actually followed.

| Period | Cycles | Average IV sold | Average vol that followed | Gap | Average P&L per cycle (10 lots) | PF |
|---|---|---|---|---|---|---|
| **2018–19** | 19 | 35.1% | 32.9% | **2.1 pts** | **+₹501** | 1.11 |
| 2020–24 (discovery) | 53 | 51.8% | 41.6% | 10.3 pts | +₹6,732 | 3.94 |
| 2024–26 (minis) | 29 | 45.4% | 40.6% | 4.8 pts | +₹8,135 | 2.84 |

- **The gap drives the result.** Cycle by cycle, it tracks C-E's P&L almost exactly in 2018–19 (correlation 0.94). In 2018–19 it was too small to pay for costs and hedging error.
- **Two one-day shocks did the damage:**
  - Aug 2019: the vol that followed was 57% against 29% sold; crude fell sharply on 1 Aug 2019 on new US tariffs on China.
  - Sep 2019: 87% against 38%; the attack on Saudi Abqaiq.
  - These two cycles lost −₹63,718 together. A hedge rebalanced at the daily close cannot protect against an overnight jump.
- **This explains the result; it cannot be traded.** The vol that followed is only known afterwards. Phase 2 found that the gap against past realised vol predicts nothing.
- **What it means:** C-E earns when implied vol runs well above what follows, as in 2020–26 (COVID, wars, OPEC shocks). In years like 2019 it earns about nothing, and it still loses ₹20–43k per 10 lots on a shock. Paper only.

## G2: the new natural-gas pass, and why it is fragile
**Rule:**
1. 10 trading days before expiry, check the front-month ATM implied vol. Trade only if it is at or below its median of the previous 250 trading days.
2. If so, sell 10 ATM NATGASMINI straddles.
3. Hold `round(straddle delta × 10)` futures, re-hedged at every close.
4. Close everything at the expiry-day close.

**Test, Jun 2024 – Oct 2026, minis' prices, run once:**
- 15 trades, **+₹62,743 per 10 lots**, PF 1.68, 67% wins, worst −₹27,950, max drawdown ₹53,909.
- Capital including the hedge's margin: ₹3.7 lakh on average, ₹5.8 lakh at most.
- On parent prices: +₹49,442.

**Why it is fragile:**
- **All the profit came in 2026.** By year: 2024 −₹33,470, 2025 −₹20,439, 2026 +₹1,16,651.
  - The 8 trades taken with IV in its bottom fifth made +₹1,12,741.
  - The 7 trades at IV percentile 30–50 lost −₹49,998.
  - Tightening the filter to "bottom fifth" would be fitted on the test data, so it needs a fresh period first.
- **Entry timing:** 8 days out made +₹79,368, but 12 days out **lost −₹20,663**.
- **Hedge rounding:** the same rule makes +₹30,189 per 10 lots when run at 5 lots, and +₹45,309 at 20 lots.
- **On parent prices, 2022–26 by year:** +₹12,823, +₹87,247, −₹41,401, −₹22,728, +₹1,08,109. 2022–23 are the years it was picked on.

**What does hold up:**
- 2× slippage on options and futures: +₹40,688.
- A re-hedge band of 2 lots: +₹74,205.
- Without its best trade: +₹34,533.
- All three neighbouring variants positive (IV ≤ 40 / 10 days +₹1,30,494; ≤ 50 / 15 days +₹57,765; ≤ 40 / 15 days +₹44,269).
- The filter itself works: the same trade when IV was *above* its median lost −₹34,399, including one trade of −₹1,53,308.

**Verdict:**
- It passed the pre-registered rule, but its profit sits in one calm stretch of 2026. Paper only.
- Together with N-B (correlation 0.44) it says the same thing: **natural gas can only be sold when it is calm.**

## What did not work, and why
- **Calendars (K1, G1) can't be filled.** On entry day, the next month's option at the same strike traded on both sides in only 3–10 of 101 crude cycles and 7–23 of 55 natural-gas cycles. With fills only at prices that actually traded, there is no calendar to trade.
- **Delta-hedged strangles (K3) and the cheaper hedge (K4)** made big walk-forward profits in 2022–26 (+₹3.0 lakh and +₹3.2 lakh per 10 lots). They lost or broke even in 2018–19, for the same reason as C-E.
- **The expiry-week strangle (K6)** won 86% of 2024–26 trades and was positive in every walk-forward year. It still lost in 2018–19 (PF 0.51): small premiums 2 days before expiry, wiped out by a few sharp moves.
- **Rolling the threatened side (K5)** lost in both test periods. A roll books the loss and re-sells nearer the move.
- **Ratios:** no crude ratio (K2) qualified. The natural-gas put ratio (G5) made +₹992 in 2024–26 and lost at 2× slippage.
- **Seasonal selling (G3) and rolls (G4) in natural gas** were barely positive even on the data they were picked on.

## What I would do now
1. **Paper-trade portfolio C** (CO-1 3 lots, CO-2 3 lots, N-B 5 lots) for 2–3 monthly cycles. It is the only set that survived every test it faced.
2. **Paper-trade G2 and C-E alongside, but do not fund them.**
   - G2 must show it works outside 2026's calm.
   - C-E needs a nervous market and gives profits back in quiet years.
3. **Drop CO-3, C-B and C-C.**

## How it was tested (pre-registered)
- **Pre-registration:** `AMENDMENT_A3.md` (sha256 `d5c49a9c…`) fixed the families, all 140 variants, the second test period and the pass rules. It was registered at 22:34 on 23 Oct, before any Phase 3 backtest.
- **Frozen candidates:** `p3_candidates_frozen.json` (`84a056f0…`, 22:45).
- **Discovery** used crude Jan 2020 – May 2024 and natural gas Mar 2022 – Apr 2024.
  - The best eligible variant per family was picked by its bootstrap 5th percentile.
  - To be eligible a variant needed: coverage ≥ 70%; net > 0; PF ≥ 1.3; t ≥ 1.5; net > 0 at 2× slippage; worst trade ≥ −30% of capital.
- **Tests:** each frozen candidate ran once on each test.
  - To pass a test it needed: net > 0; PF ≥ 1.15; net > 0 at 2× slippage; worst trade ≥ −45% of capital.
  - A crude family had to pass both 2018–19 and 2024–26.
- **Re-tests:** CO-1, CO-2, CO-3, C-B, C-C and C-E each ran once on 2018–19, unchanged.
- **Walk-forward per family:** each year, the family's best variant was re-picked on earlier data and traded that year. Crude training started in 2020, so 2018–19 stayed untouched.
- **Execution, the same as Phases 1–2:**
  - fills at the daily close, only on strikes that traded;
  - 1% slippage (minimum one tick), 3× when a leg did not trade at exit;
  - Angel One's fee card, and margin from Angel's calculator with no netting;
  - hedge futures charged ₹20 an order, plus exchange fees, CTT or stamp duty, GST and 2 bp slippage.

## Disclosures
- **Prices for 2018–19:** CRUDEOIL (parent) prices at the mini's lot size and tick, as Phases 1–2 did for pre-2024 data. Mini options did not exist then.
- **Small samples in 2018–19:** 19 cycles. CO-1's pass rests on 11 trades and CO-2's on 7. It is a second, independent piece of evidence, not proof.
- **Hedge margin in capital:** Phase 3's hedged structures count the hedge's futures margin; Phase 2's C-E did not. This only affects the worst-trade-as-%-of-capital rule, and no Phase 3 test came near it (the closest was −16.5%, against a limit of −45%).
- **The 2024–26 period is no longer blind.** It has now been used in three phases. Natural gas has no other period, so G2 and N-B rest on a period that is no longer blind. Their next real test is paper trading.
- **One code change outside `phase3/`:** `engine.build_cycles` gained `require_expiry`, so a calendar's back month can be loaded before it expires. The default is unchanged and `test_engine.py` passes.

## Caveats
- **These are backtests on daily closes.** Intraday spikes and the liquidity at the 23:30/23:55 close are not modelled.
- **Margins** are Angel's, measured 9 Oct 2026. Recheck them before trading.
- **Multiple testing:** 140 variants in Phase 3, on top of 154 in Phase 2 and 21,870 per instrument in Phase 1.
- **Past results do not guarantee future ones.** Option selling wins often and loses big occasionally.

## Files (`phase3/`)
| File | What it is |
|---|---|
| `AMENDMENT_A3.md` (+ `.sha256`) | Pre-registration |
| `engine3.py` | Calendars, ratios, generic delta-hedged positions with a hedge band, rolled strangles |
| `run_phase3.py` | `build` / `discover` / `test` |
| `robust3.py` | G2 robustness, C-E's 2018–19 diagnosis, 2018–19 trade lists, ₹10 lakh portfolios |
| `p3_candidates_frozen.json` (+ `.sha256`) | Frozen candidates |
| `results/` | Discovery table, test and robustness JSON, every trade list, run logs |
