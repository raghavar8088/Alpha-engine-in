# Phase 6: crude-oil and natural-gas FUTURES, judged week by week (24 Oct 2026)

## The answer first
**No futures strategy for crude oil or natural gas makes 2% a week, on any honest test.**

**What was tested:**
- **Data:** MCX's own price for **every futures contract** since the markets opened:
  - crude: 264 contracts, Feb 2005 – Oct 2026;
  - natural gas: 246 contracts, Jul 2006 – Oct 2026.
- **Rolls and carry:** every roll and the cost of carry are in the prices. The app's earlier
  futures study used Yahoo's continuous prices, which leave carry out.
- **Costs:** Angel One's charges plus slippage.
- **Strategies:** **208 weekly strategies** in 8 families:
  - trend (momentum, moving averages, breakouts);
  - carry (from the real futures curve), and carry plus trend;
  - seasonality;
  - weekly reversal;
  - always long or always short.

**What happened:**
1. **On 2008–2016, not one strategy was consistent enough to trust** (t ≥ 2). Even with
   hindsight, the best managed about 0.3% a week in crude and 0.45% in gas, with Sharpe ratios
   of at most 0.59.
2. **Walk-forward, 2017–2026:** each year the best strategy on all earlier years was picked and
   traded that year.
   - Most families never produced a pick worth trusting.
   - The picks that were made lost money or made nothing: crude carry-plus-trend −30% in its
     one year, always-short gas −40% in its one year, crude moving averages +0.6% in total.
3. **Even the best of 2008–16, run on 2017–26 regardless** (a descriptive check outside the
   pre-registered verdicts):
   - in crude, most of them turned into losses;
   - the best survivors made **0.12–0.25% a week** at 1× exposure, with 44–90% drawdowns.

**What 2% a week would take:**
- **Natural gas:** the best survivor (short gas when its 50-day average is below its 200-day)
  made 0.25% a week. Reaching 2% needs **7.9 times the leverage**, and at that size its
  drawdown would have been **706% of the account**: wiped out, several times over.
- **Crude:** the best survivor needs **16 times**, and MCX's margin allows only 3.2.
- **At a size where the worst drawdown stays under 50%**, the best futures strategies make about
  **0.14% a week (about 7% a year)**.

**The real problem: 2% weeks come with the big losing weeks.**
- Simply holding crude made 2% or more in **36% of weeks** in 2017–26, but lost **33% in a single
  week** at no leverage.
- Short natural gas made 2% or more in 40% of weeks, and lost **61% in one week**.
- No rule found the good weeks without also catching the bad ones.

## 1. The search, 2008–2016 (where strategies are picked)
| Family | Crude: best average week | Natural gas: best average week | Eligible (t ≥ 2) |
|---|---|---|---|
| Momentum (TS) | 0.29% (Sharpe 0.44) | 0.43%, short-only (0.59) | 0 of 60 |
| Moving averages (MA) | 0.29% (0.44) | 0.48% (0.56) | 0 of 48 |
| Breakout (BO) | 0.11% (0.22) | 0.07% (0.10) | 0 of 32 |
| Carry (CY) | 0.31% (0.48) | 0.40%, short-only (0.51) | 0 of 36 |
| Carry + trend (CT) | 0.31% (0.55) | 0.35% (0.49) | 0 of 8 |
| Seasonality (SE) | 0.23% (0.35) | 0.02% (0.03) | 0 of 4 |
| Weekly reversal (MR) | −0.04% | 0.00% | 0 of 12 |
| Always in (BH) | 0.25%, short (0.39) | 0.45%, short (0.53) | 0 of 8 |

Natural gas looks best on the short side because 2008–2016 was gas's long slide, with steep
contango (the next month dearer than this one), which rewards shorts.

## 2. Walk-forward, 2017–2026 (pre-registered)
| | Years with a pick | Result |
|---|---|---|
| Crude, moving averages | 4 of 10 | +0.6% in total |
| Crude, carry + trend | 1 of 10 | **−30.0%** |
| Natural gas, moving averages | 6 of 10 | +3.9% in total |
| Natural gas, momentum | 1 of 10 | −18.6% |
| Natural gas, always short | 1 of 10 | **−40.1%** |
| Every other family, both markets | 0 of 10 | (no pick) |

## 3. The best of 2008–16, run on 2017–26 anyway (descriptive)
| | Strategy | 2008–16 | 2017–26 | Drawdown at 1× | For 2% a week |
|---|---|---|---|---|---|
| Crude | Momentum, short-only, 13 weeks | +0.28%/wk | **−0.07%/wk** (−33%) | 169% | — |
| Crude | Moving average 5/20, short-only | +0.28% | **−0.03%** (−17%) | 141% | — |
| Crude | Seasonality | +0.23% | **−0.50%** (−255%) | 261% | — |
| Crude | Carry ± 5% | +0.22% | −0.03% | 89% | — |
| Crude | Breakout 55/20, long-only | +0.01% | +0.12% (+63%) | 44% | 16× leverage (cap 3.2×); drawdown 716% |
| Crude | Carry + trend | +0.31% | +0.04% (+19%) | 140% | 54× leverage |
| Gas | Moving average 50/200, short-only | +0.47% | **+0.25%** (+130%) | 90% | 7.9× leverage (5.6× exposure; cap 6×); drawdown **706%** |
| Gas | Always short | +0.45% | +0.24% (+122%) | 164% | 8.4× leverage (cap 6×) |
| Gas | Momentum 26 weeks, short-only | +0.43% | +0.04% (+18%) | 132% | 56× leverage |
| Gas | Carry, short-only | +0.24% | −0.05% (−23%) | 83% | — |
| Gas | Breakout | +0.05% | −0.09% (−44%) | 85% | — |

None of these meets the pre-registered "tradeable" bar (Sharpe ≥ 0.30 over 2017–26).

## 4. Benchmarks, 2017–2026, 1× exposure (no leverage)
| | Net | Average week | Weeks ≥ +2% | Worst week | Best week | Max drawdown |
|---|---|---|---|---|---|---|
| Crude, always long | +147% | +0.29% | 36% | −33.0% | +37.3% | 156% |
| Crude, always short | −163% | −0.32% | 27% | −37.3% | +33.0% | 280% |
| Gas, always long | −148% | −0.29% | 35% | −23.3% | +60.4% | 224% |
| Gas, always short | +122% | +0.24% | 40% | −60.6% | +23.2% | 164% |

A drawdown above 100% means a ₹10 lakh account holding ₹10 lakh of exposure would have been
wiped out. The crude crash of April 2020 and the gas spike of 2021–22 both did that.

## 5. Why 2% a week is not there in futures
- **Futures have no premium to collect.** Options pay their seller a little time value every
  week; futures pay only for being right about direction. Week-to-week direction in crude and
  gas is close to unpredictable.
- **The edges that do exist are small and slow.** Trend and carry are the only effects with
  decades of evidence, and they work over months. Their Sharpe ratios here are 0.2–0.6.
- **Leverage is capped, and the tails are huge.** MCX margin allows about 3.2× in crude and 6×
  in gas. A strategy earning 0.25% a week would need 8× just to average 2%, and the losing
  weeks scale with it.
- **This confirms the app's earlier result with better data.** The 22-year study found trend
  rules looked good only until the cost of carry was charged. With MCX's own contract prices,
  carry included, the result is the same.

## 6. The stop rule, and what I would do
- **I stopped here, as `AMENDMENT_A6.md` fixed in advance:** the search ends when its families
  are complete. Searching on "until a backtest shows 2% a week" would eventually find one, and
  it would be luck: a strategy that fits the past and loses real money.
- **Honest numbers for these two markets:**
  - futures, at a survivable size: about 0.14% a week;
  - the option-selling strategies already found (Phases 1–5): about 0.1–0.2% a week.
- **Your reset plan already points the right way:** the SIP and the wealth page, and one
  carefully tested idea at a time.

## 7. How it was tested
- **Pre-registration:** `AMENDMENT_A6.md` (sha256 `864377bf…`, 13:08 on 24 Oct), before any
  Phase 6 backtest. It includes the stop rule.
- **Frozen candidates:** `p6_candidates_frozen.json` (`4f53cda1…`). The list is **empty**:
  nothing was eligible.
- **Engine checks** (`test_engine6.py`, 16 checks, all pass):
  - each day's index return equals the held contract's own price change (0 of 11,639 days
    differ);
  - every roll is exactly 3 trading days before expiry (504 rolls);
  - carry, weekly costs and returns match hand calculations;
  - no signal uses data after its decision close.
- **Costs:** ₹20 an order, MCX 0.0021%, CTT 0.01% (sell), stamp 0.002% (buy), SEBI fee, 18% GST,
  slippage max(1 tick, 2 bp), and both sides on every roll.
- **Margin:** Angel's rates measured 9 Oct 2026: crude 31.1% (3.2×), gas 16.7% (6.0×).

## 8. Disclosures
- **Section 3 is descriptive**, run because nothing passed. It does not change the
  pre-registered verdict: no candidate.
- **The years were looked at before.** The app's earlier study covered 2004–2026 with different
  data and rules.
- **Intraday is not tested.** There are no historical intraday MCX prices to test on, and the
  app's live intraday futures record already lost before costs.
- **"Drawdown"** is measured on a fixed ₹10 lakh base (no compounding). Above 100% means the
  account would have been wiped out.

## Files (`phase6/`)
| File | What it is |
|---|---|
| `AMENDMENT_A6.md` (+ `.sha256`) | Pre-registration, with the stop rule |
| `expiries6.json`, `download_futures.py`, `build_futures.py` | 663 futures contracts from MCX, and the table |
| `engine6.py` | Held-contract index, rolls, carry, weekly positions, costs |
| `test_engine6.py` | 16 checks |
| `run_phase6.py` | `discover` / `test` / `walkforward` / `relaxed` |
| `p6_candidates_frozen.json` (+ `.sha256`) | The frozen (empty) candidate list |
| `results/` | Discovery table (all 208), walk-forward, the descriptive run, logs |
