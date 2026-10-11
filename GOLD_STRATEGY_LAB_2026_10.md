# Gold Strategy Lab — a search for new profitable gold strategies

**Date:** 2026-10-11 · **Asked for:** new gold strategies, each backtested, the process repeated until there were 10 profitable ones (first 50), keeping every existing strategy · **Code and data:** [`backend/research/gold_lab_2026_10/`](backend/research/gold_lab_2026_10/README.md) · **Running now:** the **Gold Lab** tab of the Gold Desk (paper)

---

## 1. The answer

**Seven strategies are profitable after costs in every period tested, including six years nobody looked at until the end. None is proven better than simply holding gold.** They are three ideas, not seven, so the honest count is **7 strategies / 3 independent edges / 0 proven**.

- **157 strategy variants** were built in five rounds (38 families) and every one was recorded.
- **0 of 157** passed the full bar: beat holding gold, then survive the correction for having tried 157 things. After 157 attempts, pure luck is expected to produce a best Sharpe ratio of about **0.63**. The best strategy's luck-corrected confidence was **0.62**, against the 0.95 required.
- **7 of 157** are *profitable but unproven* (Tier B). That means they made money after costs in selection (2004–14), validation (2015–19) and the untouched holdout (2020–26). They also held up on COMEX data and when their parameters were nudged.
- **Why I did not stop at 10.** The holdout was opened once, for the final candidates. Any strategy found after that could not be tested on data it was not fitted to. Adding three more would have meant near-copies of the trend rules, or a lower bar after seeing the answer. Either would have produced numbers, not strategies.

The seven now run as a paper book, the **Gold Lab**, on the Gold Desk. They trade Delta's XAUTUSD perpetual at the bid/ask, with the venue's real fees and funding. The 353 existing strategies and the H1 forward test are untouched.

## 2. How the search was kept honest

Repeating "generate → backtest → keep the winners" until enough winners appear always succeeds, because enough tries on the same history produce winners by chance. So the search was run under rules fixed before round 1:

| Rule | What it was |
|---|---|
| Instrument | GLD, a spot-gold ETF with no futures roll gaps; daily data 2004-11 → 2026-10 |
| Execution | Signal at a day's close, executed at the **next** New York open. The overnight move goes to the position already held. No trading at the close the signal was computed from. |
| Costs | 2 bp per side on every change of position (Delta measures 1.3, MCX 1.7). Returns are over the cash rate, which is what a futures or perpetual position earns. |
| Benchmark | Holding gold, charged the same way |
| Selection, 2004-11 → 2014-12 | Alpha vs holding gold t ≥ 2 (weekly, Newey-West); Sharpe ≥ 0.30; positive in both halves; ≥ 10 trades |
| Validation, 2015 → 2019 | Alpha > 0 and Sharpe > 0 |
| Luck correction | Deflated Sharpe Ratio (Bailey & López de Prado), computed against **all** registered variants; PBO by CSCV |
| Robustness | Parameter neighbours keep ≥ 50% of the Sharpe; the same rule on COMEX GC=F, 2000–2019, has alpha > 0 |
| Holdout, 2020 → 2026-10 | Opened **once**, for the final candidates only. The script locks itself after one run. |

**Tier A (proven)** = every bar above. **Tier B (profitable, unproven)** was fixed after round 2, before any holdout number existed. It requires:
- selection Sharpe ≥ 0.30 with both halves positive;
- validation Sharpe > 0 and alpha ≥ 0;
- alpha t ≥ 1.5 over 2004–2019;
- the robustness checks;
- holdout Sharpe > 0 and alpha ≥ 0.

## 3. What was tried

| Round | Families (variants) | Passed selection → validation |
|---|---|---|
| 1 | Time-series momentum, moving-average trend, Donchian/turtle, volatility-managed gold, shock reversal/continuation, dollar filter, real-yield (TIPS) filter, turn of month, 52-week high, GVZ regime (57) | 0 → 0 |
| 2 | Shock continuation (wider grid), diversified trend ensemble, gold/silver ratio reversion and trend, equity-crash safe haven, VIX regime, copper/gold ratio, oil inflation, trend + shock (37) | 1 → 0 |
| 3 | Dual momentum, gold miners leading gold, metals breadth, capitulation buying, volume-confirmed shocks, shock-with-trend, overnight-gap continuation, trend with a volatility brake, pre-set composites (33) | 2 → 1 |
| 4 | Autumn effect (Baur 2013), trend pullback, RSI(2), weekly trend, shock sized by strength, volume breakouts, breakeven inflation (18) | 1 → 0 |
| 5 | Wide-range-bar continuation, macro fair-value reversion, short-horizon gold/silver spread, shock continuation with a stop (12) | 1 → 0 |

**What the failures say:**
- **Most gold timing rules do not beat holding gold.** Gold rose steadily for most of 2004–2014, and a rule that is out of the market misses that.
- **The best selection results did not survive.**

  | Rule | Selection alpha t | Validation Sharpe |
  |---|---|---|
  | Macro fair-value reversion (5-day) | 2.72 | −0.07 |
  | Weekly 26-week trend | 2.39 | 0.02 |
  | 3σ shock continuation, 3 days | 2.35 | −0.15 |

- **A published effect failed out of sample.** Baur's 2013 "autumn effect" (strong Septembers and Novembers, found on 1981–2010) had a Sharpe of 0.51 here in 2004–14, then **−1.31** in 2015–19.
- **Shock continuation depends on when you enter.** After a 2–2.5σ day, riding its direction for a few days works on GLD, entering at the next New York open. It fails on COMEX data, where the engine enters an hour after the shock. The difference is timing, not bad data: only 5 of 166 COMEX shock days had no matching move in GLD, and those were announcement-timing differences, not futures-roll jumps. One reading, not tested here: the overnight session right after a shock gives part of the move back. The pure shock rules therefore failed robustness. Only the versions with a stop, or above 3σ, are in Tier B.
- **Gold earns its return overnight**, during Asian and London hours: +3.8 bp a day on GLD in 2004–14 (t 2.2), and about 0 during New York hours. Trading that directly costs more than the effect.

## 4. The seven (Tier B)

Sharpe ratios are over cash, after 2 bp a side. In the holdout, holding gold had a Sharpe of 0.73, a 12.6% CAGR and a 27.6% maximum drawdown. The last column re-prices 2004–26 with Delta's 11% a year funding and 1.3 bp a side.

| ID | Strategy | Cluster | Selection 04–14 | Validation 15–19 | **Holdout 20–26** | Holdout alpha (t) | β (holdout) | 2004–26 | Delta costs, 2004–26 |
|---|---|---|---|---|---|---|---|---|---|
| gl1 | Multi-signal: trend + shock + month-turn | trend | 0.67 | 0.67 | **0.73** | +3.5%/yr (1.0) | 0.39 | 0.68 | **0.43** |
| gl2 | Macro fair-value reversion | macro | 0.53 | 0.05 | **0.56** | +5.8%/yr (2.0) | −0.08 | 0.46 | **0.49** |
| gl3 | Trend + shock continuation | trend | 0.76 | 0.61 | **0.57** | +0.8%/yr (0.2) | 0.63 | 0.66 | 0.28 |
| gl4 | Trend + half-weight shock | trend | 0.77 | 0.54 | **0.62** | +0.6%/yr (0.2) | 0.66 | 0.67 | 0.25 |
| gl5 | 6-month trend, long/flat, vol-sized | trend | 0.68 | 0.43 | **0.69** | +0.8%/yr (0.3) | 0.67 | 0.63 | 0.19 |
| gl6 | Shock continuation with a stop | shock | 0.46 | 0.31 | **0.08** | +1.3%/yr (0.3) | −0.03 | 0.30 | 0.31 |
| gl7 | 3-sigma shock continuation | shock | 0.40 | 0.01 | **0.13** | +1.3%/yr (0.6) | −0.03 | 0.25 | 0.28 |

In the holdout, all seven stay positive at double the costs.

**Three ideas, not seven.** Holdout return correlations:
- gl1, gl3, gl4 and gl5 move together (0.75–0.98): they are one trend idea.
- gl6 and gl7 (0.48) are one shock-continuation idea.
- gl2 is independent of both (−0.34 to −0.49 against the trend rules).

**On Delta, the trend rules are weak.** Delta's funding charges longs about 11% a year, and simply holding XAUT there would have earned a Sharpe of 0.03 over 2004–26. The long-leaning trend rules keep 0.19–0.28. Each of these held up in all three periods:
- gl1, the multi-signal blend (0.43; 0.43 / 0.26 / 0.51 by period);
- gl2, the macro reversion (0.49);
- gl6, the stopped shock rule (0.31).

**What "Tier B" means in practice.** They made money in every period and kept smaller drawdowns than holding gold. But their extra return over gold is not statistically distinguishable from luck after 157 tries. Expect profits that track gold's direction for the trend cluster, and small, noisy profits for the shock pair. Don't expect a reliable edge.

## 5. What runs now: the Gold Lab book

- **Book:** $10,000 paper, one $1,428.57 sleeve per strategy, on **Delta XAUTUSD** (USD, 0.001 oz contracts).
- **Signals:** GLD's daily closes, plus UUP, TIP and the S&P 500 for gl2, read from Yahoo after the New York close. One decision per NYSE session, taken after 16:30 New York, on that session's bar. A stale bar decides nothing.
- **Execution:** at the **next NYSE session's open** (09:35–11:35 New York), each strategy is rebalanced to its target in whole contracts, at the bid/ask, walking the order book if needed. A missed window is skipped, never traded late. No trade on NYSE holidays; the holiday list runs to the end of 2028, after which the lab stops trading until it is extended.
- **Costs:** Delta's taker fee × 1.18 (GST) on every contract traded, and funding at every 4-hourly exchange on what is held.
- **The live rules are the research rules.** A test holds all seven to the research code on every one of 5,507 days, 2004–2026: maximum difference 0.0.
- **Pre-registration:** the rules, evidence and execution are stored with a fingerprint when the book is first switched on. Main Control gates new decisions; funding and marking always run.
- **Its record is a record.** A strategy here reaches real money only through the Commodity Lab gate: beat holding gold, survive deflation, then incubate on real fills.

## 6. What would change this verdict

- **A forward record.** Two years of the Gold Lab will show whether the trend cluster's profits are more than gold's drift. gl2 is the strategy to watch, since it is market-neutral and its holdout alpha t was 2.0.
- **More independent history.** Every gold history available here overlaps 2004–26. The pure shock rules' dependence on entry timing could be settled with intraday gold data covering many years, which this search did not have.
- **Not more variants.** Each one raises the bar for all the others. The 157 tried already set the luck baseline at a Sharpe of 0.63.

## Reproduction

Run in order:

```
python backend/research/gold_lab_2026_10/gl_fetch.py
python backend/research/gold_lab_2026_10/gl_round.py 1 GLD    # ... rounds 2-5
python backend/research/gold_lab_2026_10/gl_final.py stage3
python backend/research/gold_lab_2026_10/gl_final.py holdout   # once; it refuses a second run
python backend/tests/gold_desk/verify_gold_lab.py              # live rules == research rules
```

The data lands in the folder's `data/`, which is not committed. The holdout run is recorded in `data/holdout_opened.json`.
