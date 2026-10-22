# Option selling on MCX Crude Oil Mini and Natural Gas Mini

Research and backtest on real MCX prices, 22 Oct 2026.

## The answer first

You asked for 5 option-selling strategies on Crude Oil Mini and Natural Gas Mini that make money in the real market.

I tested 21,870 strategy variants per instrument:
- on MCX's own daily price records (463 contracts, about 1.8 million option rows);
- with Angel One's real charges and margin;
- with fills only at prices that actually traded;
- through two independent out-of-sample tests.

**What held up:**

| | Strategy | Evidence | Per 1 lot, Jan 2020 – Oct 2026 | Minis' own prices, Jun 2024 – Oct 2026 |
|---|---|---|---|---|
| **CO-1** | Crude: short put, 0.5 straddle below, 15 trading days before expiry, only when implied vol > realised, stop at 2x credit | **Passed the pre-registered test on untouched data** | 73 trades, **+₹36,516**, 80% wins, worst trade −₹9,274 | 24 trades, +₹12,088 |
| **CO-2** | Crude: trend-aware, 1 straddle out, 15 days, vol filter, stop at 1x, exit day before expiry | Picked by a selection process that **made money out of sample 2022–26** | 62 trades, **+₹26,593**, 87% wins, worst −₹1,611 | 23 trades, +₹8,690 |
| **CO-3** | Crude: trend-aware, 0.5 straddle out, 10 days, vol filter, stop at 2x | Same as CO-2 | 63 trades, **+₹36,684**, 82% wins, worst −₹3,632 | 21 trades, +₹10,260 |
| CO-5 | Crude: short strangle 0.5 out, 7 days, stop at 1x | Passed the pre-registered test, but only just; fragile | 82 trades, +₹51,200, max drawdown ₹17,313 | 29 trades, +₹4,488; 2026 negative |
| NG-X | Natural gas: short call 1.5 straddles above, 7 days, stop at 1x | **UNVALIDATED.** Both honest tests failed for natural gas; this was found afterwards | 54 trades, +₹31,565, worst −₹2,764 | 28 trades, +₹9,661 |

**The honest summary:**
- **Crude Oil Mini:** three strategies have real out-of-sample support (CO-1, CO-2, CO-3). CO-5 is a weak fourth.
- **Natural Gas Mini:** no strategy survived the honest tests. Every pre-registered natural-gas candidate failed on 2024–26, and the walk-forward selection process lost **−₹50,346 out of sample**. NG-X is on the list only because you asked for natural gas. **Paper-trade it only.**
- These are backtests. Real money should follow 2–3 months of paper trading. Past results do not guarantee future ones; option selling wins often and loses big occasionally.

## The five strategies, exactly

**Definitions used in every rule**
- **F** is the underlying futures closing price.
- **S** is the at-the-money straddle: call plus put at the strike nearest F, both traded that day.
- **"k straddles below"** means the put strike nearest F − k·S. "Above" means the call strike nearest F + k·S.
- **IV** is the ATM implied volatility (Black-76). **RV20** is the 20-day realised volatility of the futures (annualised standard deviation of daily log returns).
- **Trend-aware:** if F is above its 20-day (CO-2, CO-3) or 10-day moving average, sell the PUT side. If below, sell the CALL side.

**How every rule is executed**
- All decisions are taken at the day's close. A stop is checked at the close, not intraday.
- Positions are closed by the expiry-day close at the latest, so they never turn into futures.
- One lot per strategy.

### CO-1 · Crude short put with a vol filter (strongest evidence)
- **When:** 15 trading days before the option expiry, at the close. Trade only if ATM IV > RV20.
- **What:** sell 1 CRUDEOILM put 0.5 straddles below F. On 23 Sep 2026 that was F 8,825 with S 959, so the 8350 PE for ₹2,698 per lot.
- **Exit:** if the cost to buy back minus the credit reaches 2x the credit at a close, buy back. Otherwise hold to the expiry-day close.
- **Record (parent prices 2020–26):** 73 trades, 10 stops, +₹36,516, PF 1.92, average +₹500 per trade.
- **By year:** 2020 +6,049; 2021 +4,553; 2022 +17,917; 2023 −1,906; 2024 +5,621; 2025 −890; 2026 +5,171.
- **Robust:**
  - 3% slippage still gives +₹33,126;
  - entry 13 or 17 days gives +₹30.8k / +₹27.0k;
  - strike 0.75 straddles below gives +₹30.1k;
  - without its best trade, +₹32.6k.
- **Validation (minis' own prices, never seen during selection):** 24 trades, +₹12,088, PF 1.76, worst −27.6% of capital.
- **Risk:** its worst loss, −₹9,274 (Jun 2026), is about 18 average wins. It sells puts, so it loses in crude crashes.

### CO-2 · Crude trend-aware, far strikes, early exit (best risk profile)
- **When:** 15 trading days before expiry, at the close. Trade only if IV > 1.10 × RV20.
- **What:** sell 1 option 1.0 straddle out of the money:
  - futures above their 20-day average: a put below;
  - below the average: a call above.
- **Exit:** stop at a loss of 1x credit (checked at the close). Otherwise buy back at the close 1 trading day before expiry.
- **Record:** 62 trades, 8 stops, +₹26,593, PF 4.29.
  - worst trade −₹1,611;
  - max drawdown ₹2,801;
  - **positive every year 2020–2026**.
- **Robust:**
  - 3% slippage still gives +₹25,314;
  - entry 13 or 17 days gives +₹15.7k / +₹11.9k;
  - strike 0.75 or 1.25 gives +₹29.8k / +₹19.2k.
- **Minis' prices 2024–26:** 23 trades, +₹8,690, PF 3.06.
- **Nearly uncorrelated with CO-1** (−0.03), so the two diversify each other.

### CO-3 · Crude trend-aware, closer strikes
- **When:** 10 trading days before expiry. Trade only if IV > 1.10 × RV20.
- **What:** the trend-aware side, 0.5 straddle out of the money.
- **Exit:** stop at 2x credit. Otherwise hold to the expiry-day close.
- **Record:** 63 trades, 5 stops, +₹36,684, PF 3.24, worst −₹3,632, max drawdown ₹4,699. 2023 lost ₹1,982; every other year was positive.
- **Minis' prices 2024–26:** +₹10,260, PF 2.79.
- **Weak spot:** entering 8 days out instead of 10 drops it to +₹3.9k. Keep the timing exact.
- Correlation with CO-1 is 0.51. The 10-day-average version (CO-4, no stop) is essentially the same bet (0.72), so do not run both.

### CO-5 · Crude short strangle (weak; small size or skip)
- **Rules:** 7 trading days before expiry, sell the put and the call 0.5 straddles out. Stop at 1x credit; otherwise hold to the expiry-day close.
- **Record:** +₹51,200 over 82 trades, but a ₹17,313 drawdown.
- **Recent results are poor:** on the minis' 2024–26 prices only +₹4,488 (PF 1.16), and 2026 −₹1,182.
- **Fragile:** entering 9 days out instead of 7 lost money in validation.
- It needs two short legs' margin (about ₹44–49k).

### NG-X · Natural gas far short call (UNVALIDATED; paper only)
- **Rules:** 7 trading days before expiry, sell 1 NATGASMINI call 1.5 straddles above F. Stop at 1x credit; otherwise hold to the expiry-day close.
- **Record (NATURALGAS prices 2022–26):** 54 trades, +₹31,565, positive every year. But **57% of it came in 2022's collapse**.
- **Minis' prices 2024–26:** +₹9,661, PF 2.62.
- **Why it is unvalidated:** it was found by screening all variants after the honest tests had failed. The walk-forward process, which could have chosen it, never did in real time. Natural-gas volatility spikes in rallies, which is exactly where a short call is exposed.

## How it was tested

The full method is in `METHOD.md`. In brief:

- **Data:** MCX's official bhavcopy for every option and futures contract on CRUDEOIL, CRUDEOILM, NATURALGAS and NATGASMINI.
  - **Mini history is short:** mini options only exist since mid-2024. Their parents share the same underlying and expiry dates (32 of 32), so the parents' longer history was used to search, and the minis' own prices to judge.
  - **The data passed checks:** put-call parity matches the mapped futures within a median of 0.05%. The minis' closes run 2–4% richer than the parents', which flatters sellers slightly, so the parent prices are the conservative series.
- **Fills:** at the day's close, only on strikes that traded that day.
  - Slippage is 1% of premium, minimum one tick. Every result is re-run at 2% and 3%.
  - A strike that didn't trade on exit day pays 3x slippage.
- **Costs:** Angel One's MCX option card on every order. That is about ₹48 per round trip per leg, ₹97 for a strangle.
- **Capital:** the margin Angel's calculator asked for on 9 Oct 2026, about 37% of a lot's value per short crude option and 20% per short natural-gas option, with no hedge discount (Angel gave 0% on straddles and 1.8% on verticals). Out-of-the-money shorts usually need less, so returns on margin here are conservative.

**Two independent tests**

1. **Pre-registered protocol** (`PROTOCOL.md`, fixed before any result, sha256 `93306f5c…`):
   - 18,360 variants were searched on the earlier period: 1,610 passed every rule and 12 became candidates.
   - The 12 were run **once** on the minis' own 2024–26 prices: **2 passed (CO-1, CO-5), 10 failed**, including all 6 natural-gas candidates.
2. **Walk-forward** (`AMENDMENT_A1.md`, also fixed before running):
   - Each year, strategies were chosen using only earlier data and then traded in that year.
   - **Crude 2022–26: +₹42,413 out of sample** (136 trades, PF 1.64; +₹39,649 at 2% slippage). By year: +27.1k, −7.0k, +18.6k, +0.5k, +3.2k.
   - **Natural gas 2024–26: −₹50,346** (85 trades, PF 0.52, one trade −267% of its margin). By year: +6.5k, −29.0k, −27.9k.
   - CO-2 and CO-3 are the crude process's current picks. Because they were chosen on all the data, their own full-history numbers are in-sample; the process's out-of-sample record is their evidence.

Every deviation from plan is disclosed in `DEVIATIONS.md`.

## Is there a premium to sell at all?

Yes, in both markets. Options have consistently priced more movement than followed:

| 20 trading days before expiry | ATM implied vol | Vol that followed | Implied > realised | Short straddle beat the move |
|---|---|---|---|---|
| Crude (92 cycles, 2019–26) | 42.3% | 38.8% | 76% of months | 68% |
| Natural gas (55 cycles, 2022–26) | 68.2% | 61.1% | 75% | 64% |

This matches the academic evidence: shorting energy variance has earned sizable Sharpe ratios ([Trolle & Schwartz, *Journal of Derivatives* 2010](https://research.cbs.dk/en/publications/variance-risk-premia-in-energy-commodities/)). The same study warns where it breaks:
- **Natural gas:** its variance is "call-like" and explodes in rallies.
- **Crude:** its variance is "put-like" and explodes in crashes.

**Why natural gas still failed.** The premium is there, but natural gas trends violently:
- **2022–23:** a historic collapse, when selling calls looked brilliant.
- **2024–26:** rallies. One rally month wiped out many months of premium.

Bought wings that cap the loss (condors, spreads, butterflies) made money in only 0–3% of natural-gas variants after costs. With no margin discount for them at Angel, there is no cheap way to cap the tail.

**Why defined-risk structures rarely work here.** In crude only 12–37% of spread/condor/butterfly variants were profitable, against 83–98% of naked shorts. The bought wing costs more than the premium it protects, it doubles the fees, and it does not reduce Angel's margin.

## How to use these, if you go ahead

1. **Paper-trade first for 2–3 monthly cycles.** These rules are mechanical and need exact entry days, the IV/RV check and close-only stops.
2. **One lot each to start.** Capital per crude strategy is about ₹30–35k margin at today's prices, plus a buffer of at least 2x the worst historical loss: about ₹50–60k for CO-1 and ₹35–40k for CO-2 or CO-3.
3. **Diversify by evidence:**
   - CO-2 plus CO-1 is the most diversified pair (correlation −0.03).
   - Adding CO-3 adds a partly overlapping bet (0.5 with CO-1).
   - Do not add CO-4.
4. **Respect the exit rules.** Close by the expiry-day close (CO-2: the day before). Never let an option devolve into futures. The tested stop is checked at the CLOSE. An intraday stop order is a different, untested strategy.
5. **Know the event risk.** The weekly EIA crude report (Wednesdays) and natural-gas storage report (Thursdays) were not filtered.

## Limitations

- **Daily data.** Intraday spikes that reverse before the close are invisible. A real stop could sometimes fill worse.
- **Close prices.** Fills assume trading near the close of a session that runs to 23:30/23:55 IST.
- **Short history.** About 28 mini cycles and 82 crude cycles is enough to reject what fails, not enough to promise future returns.
- **Multiple testing.** Thousands of variants were tried. The Deflated Sharpe Ratio of CO-1's validation, counting only the 12 candidates tested, is 0.52: real but modest.
- **Margin.** Margin changes with volatility; Angel's calculator decides. Recheck it before trading.

## Files

| File | What it is |
|---|---|
| `README.md` | Run order |
| `PROTOCOL.md`, `AMENDMENT_A1.md` | Pre-registered rules (sha256 in `.sha256`) |
| `DEVIATIONS.md` | Every slip, disclosed |
| `METHOD.md` | Data and execution model |
| `engine.py`, `b76.py`, `search.py`, `validate.py`, `walkforward.py`, `final_checks.py` | The code |
| `results/` | Candidates, validation, walk-forward, final checks and every finalist's trade log |
