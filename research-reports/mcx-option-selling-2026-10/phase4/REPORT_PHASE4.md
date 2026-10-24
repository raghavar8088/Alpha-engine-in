# Phase 4: is there a crude or natural-gas option strategy that makes 2% every week? (24 Oct 2026)

## The answer first
**No.** I tested **988 weekly strategies** on MCX's real prices, refreshed to Fri 23 Oct 2026, after Angel One's charges:
- 494 on crude oil and 494 on natural gas;
- 696 option-selling and 292 option-buying.

**The headline results:**
- **Not one made 2% every week**, not even on the data it was picked from.
- **Nothing came close:** none averaged 2% a week while being profitable in 3 weeks out of 4, and none was profitable in even 90% of weeks.
- **One of the 9 best passed.** The 9 best were frozen and run once on data they had never seen. **8 failed.** The one that passed the basic "makes money after costs" rule is a natural-gas strangle sold only in calm weeks. It makes **0.26% a week** on its margin and is profitable in 45% of weeks.
- **Your best validated set never had a +2% week.** That is CO-1 3 lots + CO-2 3 + N-B 5 on ₹10 lakh.
  - It made money in 63% of weeks and averaged **+₹750 a week (0.075%)**.
  - In 125 weeks its best week was +1.73% and its worst −2.27%.

**What 2% a week would take:**
- 2% of ₹10 lakh is ₹20,000 a week. Your best validated set would have to be about **27 times bigger**.
- That means about **₹31 lakh of margin**, which a ₹10 lakh account cannot post.
- At that size its worst week would have cost about **₹6 lakh**.
- The new weekly pass would need 7.6 times your account as margin. Its worst week at that size would have cost 56% of the account.

## 1. Even the best case did not reach it
These figures are measured **on the data each strategy was picked from**, so they are flattered. The natural-gas years (Mar 2022 – Apr 2024) also include gas's 2022–23 collapse, which made selling calls and buying puts look easy.

"Return" means:
- per week on the margin used, for selling;
- per week on the premium paid, for buying.

| | Most weeks at +2% or more | Most weeks profitable | Highest average week | Made money at all |
|---|---|---|---|---|
| **Crude selling** (348) | 52% of weeks; average 0.47%; worst week −31% | 77%; average 0.46%; worst week −52% | 0.54% | 275 of 348 |
| **Crude buying** (146) | 32%; average **−5.1%** | 32% | 0.36%, profitable 26% of weeks | **1 of 146** |
| **Natural-gas selling** (348) | 72%; average 1.81%; worst week −44% | 77%; average 0.71% | 2.16%, worst week **−73%** | 236 of 348 |
| **Natural-gas buying** (146) | 36%; worst week −105% | 36% | 8.65% on premium, profitable 24% of weeks | 50 of 146 |

- **Every week at +2% or more: 0 of 988.**
- **An average of 2%+ a week with 75%+ of weeks profitable: 0 of 988.**

## 2. The 9 frozen candidates, run once on untouched periods
- **Test periods:**
  - "2018–19" is Jun 2018 – Dec 2019 on CRUDEOIL prices (83 weeks). Crude must pass it.
  - "2024–26" is Jun 2024 – Oct 2026 on the minis' own prices (125 weeks).
- **Units:** per lot. WS7 is per 10 lots.

| | Strategy | 2018–19 | 2024–26 | Average week (2024–26) | Profitable weeks | Weeks ≥ +2% | Worst week | Verdict |
|---|---|---|---|---|---|---|---|---|
| Crude | Strangle at delta 0.20, calm IV only | −₹6,402 | −₹9,711 | −0.17% | 23% | 1% | −10.8% | ❌ |
| Crude | Put at delta 0.20, calm IV only | −₹3,037 | +₹860 (PF 1.09) | 0.01% | 30% | 3% | −15.5% | ❌ |
| Crude | Call at delta 0.10, stop 1× | −₹4,550 | −₹5,144 | −0.16% | 65% | 2% | −9.2% | ❌ |
| Crude | Trend side at delta 0.15 (put above SMA20, else call), stop 2× | −₹5,227 | +₹8,719 (PF 1.49) | 0.16% | 74% | 7% | −11.5% | ❌ lost 2018–19 |
| Crude | Delta-hedged ATM straddle, calm IV (10 lots) | −₹1,12,247 | −₹82,931 | −0.10% | 22% | 1% | −7.7% | ❌ |
| **Gas** | **Strangle at delta 0.10, calm IV only** | (no data) | **+₹8,346** (PF 1.85) | **0.26%** | **45%** | 3% | −7.5% | ✅ tradeable, far from 2% |
| Gas | Call at delta 0.20, calm IV only | | +₹2,313 (PF 1.08) | 0.13% | 47% | **42%** | **−30.4%** | ❌ |
| Gas | Trend side at delta 0.15, stop 2× | | **−₹12,865** | −0.60% | **69%** | **52%** | **−45.9%** | ❌ |
| Gas | **Buy** on a 10-day breakout, delta 0.50, +50% / −50% exits | | −₹22,203 | −4.5% of premium | 10% | 10% | −83% | ❌ |

**The natural-gas trend-side row is what "2% most weeks" looks like in practice:**
- it made 2% or more in over half of the weeks;
- it was profitable in 69% of weeks;
- **it still lost money**, because its bad weeks reached −46%.

**The one pass** (gas strangle at delta 0.10, calm IV only):
- **Every year was positive:** 2024 +₹1,482, 2025 +₹1,820, 2026 +₹5,045.
- It survives 3× slippage (+₹7,574) and losing its best week (+₹7,260).
- **The calm-IV filter is essential.** Without it the same trade lost −₹23,607, with one week at −128% of margin.
- **Weak spots:**
  - on parent prices it made only +₹2,501;
  - its walk-forward lost −₹10,805;
  - it is essentially N-B traded weekly.

**Walk-forward** (each year's best variant picked on earlier years only):
- Most families were near zero or negative.
- The weekly hedged straddle made +₹1.71 lakh per 10 lots on 2022–26 parent prices, but the frozen version lost in both test periods. It is C-E's story again: it pays only when implied volatility runs well above what follows.

## 3. Your validated strategies, week by week (Jun 2024 – Oct 2026, 125 weeks)
| | Weeks profitable | Weeks flat (no position) | Average week | Best week | Worst week |
|---|---|---|---|---|---|
| CO-1 (per lot) | 56% | 27% | +₹97 (0.40% of its margin) | +₹2,976 | −₹8,330 |
| CO-2 (per lot) | 52% | 38% | +₹70 (0.29%) | +₹1,596 | −₹1,879 |
| N-B (per lot) | 26% | 64% | +₹50 (0.18%) | +₹3,628 | −₹2,489 |
| **Core on ₹10 lakh** (CO-1 3 + CO-2 3 + N-B 5) | **63%** | 17% | **+₹750 (0.075%)** | +₹17,314 (+1.73%) | −₹22,680 (−2.27%) |

Weeks at +2% of ₹10 lakh: **0 of 125**. These totals match Phase 3 exactly: +₹93,767 for the core, +₹12,088 for CO-1.

## 4. Why 2% every week is not there
- **Selling earns a small weekly premium and sometimes loses big.**
  - The sellers that made money averaged 0.1–0.5% a week on their margin.
  - Every one of them had losing weeks, and their worst week cost roughly 30–90 times their average week (CO-1: 86×; the weekly gas strangle: 29×).
  - Margin rules cap the size: you cannot post more margin than you have.
- **Buying loses most weeks.**
  - An option loses value every week the market does not move enough.
  - In crude, 145 of 146 buying variants lost money even on the data they were picked from.
  - The natural-gas buys that looked good there (in 2022–23's collapse) were profitable in at most 36% of weeks, and the frozen one lost in the test.
- **This matches SEBI's FY26 study** (cited in your reset plan):
  - traders who only buy options: 89.9% lost money, median return −114%;
  - option sellers: median return on capital +1%, and as a group they still lost money.
- **A promise of 2% every week is a promise of enough leverage to blow up eventually.**

## 5. What I would do
1. **Do not chase 2% a week.** On this data, the honest figure for these markets is around **0.1% of the account a week**: the core lost money in about 1 week in 5 and had no position in 1 week in 6, with an occasional −2% week.
2. **Keep paper-trading the core** (CO-1, CO-2, N-B) as Phase 3 recommended. The new weekly gas strangle can sit beside it on paper. Its weekly P&L is nearly independent of the core's (correlation 0.07).
3. **Remember your plan's rule 7:** "no short-hold strategies, no naked option selling, and no option buying within a day of expiry". Every strategy that made money here is a naked option sale held for about a week. So this stays research, and none of it should get real money.

## 6. How it was tested (pre-registered)
- **Pre-registration:** `AMENDMENT_A4.md` (sha256 `7b7f75f0…`, registered 11:18 on 24 Oct, before any Phase 4 backtest) fixed the 15 families, all 988 variants, the periods and the pass rules.
- **Frozen candidates:** `p4_candidates_frozen.json`.
- **Data:** refreshed with `refresh_mcx.py`, which re-fetched 28 live contracts to Fri 23 Oct 2026.
- **The week:**
  - enter at the previous week's last close and exit at this week's last close;
  - exit earlier on a stop or target, or at the expiry close;
  - use the front month;
  - a week with no trade counts as 0 and as not profitable.
- **Execution, the same as Phases 1–3:**
  - fill at the close, only on strikes that traded;
  - 1% slippage (3× when a leg did not trade at exit);
  - Angel's fee card;
  - margin from Angel's calculator with no netting;
  - the hedge's margin added for hedged trades;
  - a buyer's capital is the premium paid.
- **Engine checks** (`test_engine4.py`): weekly trades held to expiry reproduce `engine.run_trade` and Phase 2's hedged straddle **exactly** (0.00 difference over 169 trades). Stops and targets fire on the first qualifying close.
- **Discovery:**
  - Periods: crude Jan 2020 – May 2024; natural gas Mar 2022 – Apr 2024.
  - Eligibility: coverage ≥ 70%; net > 0, also at 2× slippage; PF ≥ 1.3; weekly t ≥ 1.5; sellers' worst week ≥ −30%.
  - Each family's best eligible variant was picked by the bootstrap 5th percentile of its mean weekly return.
- **Verdicts on the tests:**
  - **Literal:** every week ≥ +2%.
  - **Near target:** an average week ≥ 2% and ≥ 75% of weeks profitable, plus tradeable.
  - **Tradeable:** net > 0, also at 2× slippage; PF ≥ 1.15; sellers' worst week ≥ −45%.
  - Crude had to pass both periods.

## 7. Disclosures
- **Both test periods had been used before for other strategies:** 2024–26 in Phases 1–3, and 2018–19 in Phase 3. No weekly family had ever run on either.
- **Multiple testing:** 988 variants in Phase 4. Because the target was missed even in-sample, this cannot have produced a false "yes".
- **Intraday was not tested.** No source we can reach has historical intraday prices for these options.
- **"Calm IV"** means front-month implied vol at or below its median of the previous 250 trading days.
- **Implementation choices not spelled out in A4:**
  - a variant needed at least 3 trades to be eligible (as in Phase 3);
  - a breakout needs at least N−2 traded closes in its window.
- **Limits of the ₹10 lakh arithmetic:** it scales P&L linearly, ignores whole-lot rounding, and assumes fills at size.

## Files (`phase4/`)
| File | What it is |
|---|---|
| `AMENDMENT_A4.md` (+ `.sha256`) | Pre-registration |
| `refresh_mcx.py` | Re-fetch live contracts to a date |
| `engine4.py` | One trade a week: generic legs (selling or buying), the hedged straddle, weekly statistics |
| `test_engine4.py` | Cross-checks against the audited engines |
| `run_phase4.py` | `build` / `discover` / `test` |
| `reference4.py` | The validated strategies week by week |
| `robust4.py` | Robustness of the one pass, and the 2%-a-week arithmetic |
| `p4_candidates_frozen.json` (+ `.sha256`) | Frozen candidates |
| `results/` | Discovery table (all 988 variants), test and robustness JSON, weekly rows, run logs |
