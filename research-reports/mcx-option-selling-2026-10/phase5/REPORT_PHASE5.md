# Phase 5: more strategies, tested on markets they had never seen (24 Oct 2026)

## The answer first
**Two experiments:**
- **Transfer test.** The strategies that worked on crude and natural gas were frozen exactly, then run once on MCX's other option markets: gold, silver, copper and zinc, 2017/18 – Oct 2026. No strategy had ever touched that data.
- **Three new strategy types,** each with a known economic reason. They were picked on crude 2020–24 only, then run once on every other market.

**What I found:**
- **The selling premium is real beyond crude.** Four of the five frozen rules made money on most of the new markets, and passed the pre-registered "generalises" test:
  - CO-1, the crude put rule;
  - CO-2, the trend-aware rule;
  - N-B, the calm-volatility strangle;
  - C-E, the hedged straddle.

  This is the strongest evidence in the whole study, because the rules chose nothing on this data.
- **Much of the money came from the 2024–26 metals rally.** In 2025 alone gold rose 76%, silver 169% and copper 62%, which flatters strategies that sell puts or follow the trend. Before 2024:
  - **N-B held up best.** On gold, silver and copper it had **not one losing trade before 2024**, and 95–100% wins overall. But it earns only 1–5% a year on its margin.
  - **CO-1 held up on gold and copper** (PF 3.07 and 1.95), but not on silver or zinc.
  - **CO-2's metal profits are almost all from 2024–26.** Before 2024 its PF was 0.21–0.72 on gold, silver and copper, so it is not reliable outside a strong trend.
  - **C-E was positive before 2024 everywhere** (PF 1.6–4.1), but it is very lumpy (5 losing years out of 10 on gold) and needs crores of margin.
- **The new types mostly failed:**
  - selling over the weekend: lost money even on the data it was picked from;
  - selling before report days: lost money even on the data it was picked from;
  - selling after a 2.5-sigma shock: passed 4 of 6 markets, but lost on natural gas and silver, and all of its gold profit came in 2026.

**The one new strategy a ₹10 lakh account can use:** **CO-1 on the gold mini** (100 g).
- About ₹90,000 of margin per lot.
- **+₹1,19,335 per lot over 2022–26** from 28 trades, 82% of them winners.
- Every year positive, and positive before 2024 too (PF 2.04).
- Worst trade about −₹19,500 per lot.
- **The caveat:** gold rose in every year of that period, and this is a put-selling rule. It has never been tested through a gold bear market, because the data has none.

## 1. Transfer test: frozen rules on untouched markets
- **Units:** per lot of each market's own contract (C-E per 10 lots). Lots are large: GOLD is 1 kg (about ₹1.6 crore in 2026), SILVER 30 kg, COPPER 2.5 t and ZINC 5 t.
- **Verdict rule:** pass = net > 0, PF ≥ 1.15, still net > 0 at 2× slippage, worst trade ≥ −45% of capital, with at least 10 trades.

| Rule | GOLD | SILVER | COPPER | ZINC | Verdict | Gold mini / silver mini (cross-check) |
|---|---|---|---|---|---|---|
| **CO-1** crude put rule | ✅ +₹13.5L, PF 5.11, 89% wins | ✅ +₹6.7L, PF 2.58 | ❌ +₹4.2L but a −54% trade | ✅ +₹1.9L, PF 2.69 | **Generalises** (3 of 4) | ✅ +₹1.19L / ❌ −₹5,872 |
| **CO-2** trend-aware | ✅ +₹1.8L, PF 1.51 | ✅ +₹5.0L, PF 4.82 | ✅ +₹1.7L, PF 1.82 | ✅ +₹23k, PF 1.33 | **Generalises** (4 of 4) | ✅ +₹23.8k / ✅ +₹36.3k |
| **N-B** calm-vol strangle | ✅ +₹1.6L, 95% wins | ✅ +₹2.9L, 100% wins | ✅ +₹1.2L, 100% wins | too few (4) | **Generalises** (3 of 3) | ✅ +₹7.9k / too few |
| **C-E** hedged straddle (10 lots) | ✅ +₹54L, PF 1.32 | ✅ +₹79L, PF 1.97 | ✅ +₹1.16 cr, PF 4.99 | ✅ +₹40L, PF 3.82 | **Generalises** (4 of 4) | ❌ −₹2.2L / ✅ +₹14.7L |
| P4-W weekly gas strangle | ❌ −₹6.5L | ❌ −₹2.7L | ✅ +₹95k | ✅ +₹45k | does not generalise (2 of 4) | ❌ / ❌ |

Nickel options barely traded (906 lots in two years), so every rule had too few trades there.

## 2. Where the money came from: the 2024–26 rally
**Each market's own move per year:**

| Market | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| Gold | +20% | +23% | −4% | +15% | +15% | +21% | **+76%** | +5% |
| Silver | +19% | +55% | −8% | +12% | +7% | +17% | **+169%** | −17% |
| Copper | +8% | +35% | +26% | −4% | +1% | +9% | **+62%** | +7% |
| Zinc | +7% | +21% | +34% | −6% | −14% | +20% | +10% | +30% |

**Before 2024 only** (net, profit factor):

| Rule | GOLD | SILVER | COPPER | ZINC | Read |
|---|---|---|---|---|---|
| **N-B** | +₹1.50L, **no losing trade** (14) | +₹1.11L, **no losing trade** (13) | +₹17k, no losing trade (5) | +₹1k (3) | ✅ holds up |
| **CO-1** | +₹2.9L, PF 3.07 | −₹50k, PF 0.82 | +₹90k, PF 1.95 | −₹66k, PF 0.29 | ✅ gold and copper only |
| CO-2 | −₹1.6L, PF 0.21 | −₹22k, PF 0.70 | −₹20k, PF 0.72 | +₹9k, PF 1.71 | ❌ trend-dependent |
| C-E (10 lots) | +₹15.3L, PF 1.61 | +₹18.0L, PF 2.03 | +₹21.0L, PF 2.65 | +₹3.5L, PF 1.64 | ✅ positive but lumpy |

## 3. The new strategy types
| Family | Economic reason | On crude 2020–24 (where picked) | Verdict |
|---|---|---|---|
| F1 · Sell over the weekend (Friday close to Monday) | Options lose value over non-trading days (Jones & Shemesh 2018) | 0 of 12 variants eligible; the best lost −₹7,593 | ❌ costs eat it on MCX |
| F3 · Sell before report days (EIA / gas storage) | Implied vol is bid ahead of reports | 0 of 6 eligible; the best lost −₹6,337 | ❌ (buyers lost too, in Phase 4, so costs eat both sides) |
| F2 · Sell a delta-0.25 strangle the day after a 2.5-sigma move, hold 10 days, stop 2× | Implied vol overshoots after shocks | +₹17,043 (28 trades, PF 2.56), frozen | Passed 4 of 6 markets; see below |

F2 by market:
- **Lost:** natural gas −₹40,737 and silver −₹89,820.
- **Made money:**
  - copper +₹4.4L, positive in 8 of 9 years;
  - zinc +₹2.3L, positive every year;
  - crude 2024–26 +₹3,949.
- **Gold:** +₹2.9L overall, but **−₹5.3L before 2024 and +₹12L in 2026 alone**.
- **Verdict:** it meets the pre-registered bar, but it is not a dependable strategy.

## 4. What a ₹10 lakh account can carry
Only the retail-size contracts fit:
- gold mini (100 g) and silver mini (5 kg);
- copper and zinc, which take ₹1.4–2.3 lakh of margin per short option;
- the crude and natural-gas minis from Phases 1–4.

The table assumes at most 40% of the account is used as margin, one rule at a time:

| Strategy | Margin per lot | Lots | Profit a year (2022–26 average) | Worst trade at that size | Read |
|---|---|---|---|---|---|
| **CO-1 on gold mini** | ₹90k | 4 | **≈ +₹1.09 lakh** | −₹77,808 | ✅ best new option; gold never fell in the test |
| CO-2 on silver mini | ₹87k | 4 | ≈ +₹29,700 | −₹52,144 | 2025–26 only |
| CO-2 on gold mini | ₹98k | 4 | ≈ +₹21,700 | −₹51,316 | 2025–26 only |
| N-B on silver mini | ₹2.25L | 1 | ≈ +₹10,700 | no losing trade (9 trades: too few to judge) | watch |
| CO-1 on zinc | ₹1.45L | 2 | ≈ +₹45,600 | −₹82,678 | lost 2018–19 |
| CO-1 on copper | ₹2.26L | 1 | ≈ +₹50,600 | −₹1,33,846 | a −54% trade |

Even the best of these averages about **0.2% of ₹10 lakh a week**. The 2%-every-week target from Phase 4 is still out of reach.

## 5. What I would do
1. **Paper-trade CO-1 on the gold mini** alongside the crude and natural-gas core. Its record (2022–26, never a losing year) is good, but it comes from a gold bull market.
2. **Treat N-B as a family that works in calm markets everywhere** (gold, silver, copper, natural gas). It is the most consistent result in five phases. It earns little, and its gold profit turned to −₹28k in 2026, so do not size it up.
3. **Do not trust CO-2, C-E or F2 on metals** for real money. CO-2 and F2 depend on 2024–26. C-E is lumpy and needs crores of margin.
4. **Your plan's rule 7 still applies:** these are naked option sales. They belong on paper until a pre-registered paper test confirms them.

## 6. How it was tested (pre-registered)
- **Pre-registration:** `AMENDMENT_A5.md` (sha256 `f85deec1…`, 11:47 on 24 Oct) fixed the markets, the five transfers, the 42 new variants and the verdict rules. That was before any Phase 5 backtest and before the metals data finished downloading.
- **Frozen candidate:** `p5_candidates_frozen.json` (`0130167d…`, 11:52), before any test.
- **Data:** MCX's official bhavcopy, 836 new contracts, with 7.0 million option rows. Contract multipliers were checked against the futures' traded value and all matched to 0.1%.
- **Margin:** Angel's rates as measured by the app on 9 Oct 2026.
- **Engine checks** (`test_engine5.py`, 16 checks, all pass on crude, gold and copper):
  - open prices match the bhavcopy;
  - open exits match a hand calculation;
  - every shock entry is a true shock day;
  - shock positions never overlap.
- **Execution, the same as Phases 1–4:**
  - fill at the close, only on strikes that traded;
  - 1% slippage (3× when a leg did not trade at exit);
  - Angel's fee card;
  - margin with no netting.

## 7. Disclosures
- **Rally caveat:** the 2024–26 metals rally is in the test data. Section 2's "before 2024" split was added after the results and is descriptive. It does not change the pre-registered verdicts, but it is the more honest reading.
- **The markets are not independent:** gold and silver move together, and so do the base metals. "Generalises" (3 or more passes, and a majority) is therefore weaker evidence than four truly independent markets would be.
- **Liquidity:** copper and zinc options are thin. An ATM straddle traded on only 22% and 13% of days, and fills at the close may be optimistic there.
- **No bear-market test:** gold has had no bear market in this data. Selling puts on gold has not been tested through one.
- **Nickel and zinc:** nickel had essentially no option trading, and zinc too little for N-B.

## Files (`phase5/`)
| File | What it is |
|---|---|
| `AMENDMENT_A5.md` (+ `.sha256`) | Pre-registration |
| `expiries5.json`, `download_more.py` | The other MCX option markets: expiry list and downloader |
| `engine5.py` | New-market specs, opening prices, the weekend / shock / report-day families |
| `test_engine5.py` | 16 checks against the bhavcopy and hand calculations |
| `run_phase5.py` | `specs` / `build_energy` / `build_metals` / `discover` / `test` |
| `robust5.py` | By year, before and after 2024, without the best trade, ₹10 lakh sizing |
| `p5_candidates_frozen.json` (+ `.sha256`) | The frozen Part B candidate |
| `results/` | Discovery table, test and robustness JSON, every trade list, run logs |
