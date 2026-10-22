# Amendment A2: Phase 2, strategies built from the option data (written 2026-10-22, before any A2 backtest)

## What was looked at first, and only on the discovery period
`analytics.py` ran on crude CRUDEOIL expiries Jan 2020 - May 2024 and natural-gas NATURALGAS
expiries Mar 2022 - Apr 2024. No Jun 2024+ data was used. Findings:

### Premium map (short, held to expiry)
**Crude**
- OTM calls at |delta| 0.05-0.20 with 4-12 trading days left were the most reliable cells
  (t 5-10).
- Short-dated puts (1-7 days, |delta| 0.05-0.20) gave t 3-9.
- Far OTM puts with 13-22 days left lost money.

**Natural gas**
- Only the far wings (|delta| 0.02-0.05, both sides, 8-22 days) were reliably positive
  (t 5-9).
- The large call-side and put-side results elsewhere are the 2022-23 crash.

### Other signals
- **IV/RV ratio:** no information in either market (correlation ~0.0).
- **ATM IV level:** in crude, a higher IV level means a better short strangle (correlation
  +0.45 to +0.54). In natural gas the sign is reversed (-0.23 to -0.34).
- **Skew, put/call OI ratio, OI walls, weekday:** no reliable signal.
- **Delta-hedged ATM straddle:** crude t 2.1-2.5; natural gas no edge.

## Families (complete list)
Strikes are chosen by DELTA. At entry, take Black-76 implied vol and delta for every traded
strike. The leg is the traded strike whose |delta| is nearest the target, provided it lies
within 0.5x-1.5x of the target; otherwise the cycle is skipped.

`ivpct` is the percentile of today's front-month ATM implied vol within the previous 250
trading days of that series. It is causal (past only) and needs at least 60 earlier days.

| Family | Market | Structure | Grid |
|---|---|---|---|
| C-A | crude | short call | delta 0.05/0.10/0.15/0.20; entry 12/10/7/5; stop none/2x |
| C-B | crude | short put | delta 0.05/0.10/0.15/0.20; entry 7/5/3; stop none/2x |
| C-C | crude | short strangle | delta 0.10/0.15/0.20 each side; entry 10/7/5; stop none/1x/2x |
| C-D | crude | short strangle, only if ivpct >= 50 or >= 67 | delta 0.15/0.20/0.25; entry 15/10; stop none/2x |
| C-E | crude | ATM straddle, delta-hedged daily | entry 20/10; 10 lots; hedged in whole mini-futures lots |
| N-A | natural gas | far-wing strangle | delta 0.03/0.05/0.08 each side; entry 20/15/10; stop none/1x/2x |
| N-B | natural gas | short strangle, only if ivpct <= 50 | delta 0.10/0.15/0.20; entry 15/10; stop none/1x/2x |

That is 154 variants in total. Every position is held to the expiry-day close unless its
stop fires; the stop is checked at the close. Fills, slippage, fees and margin are exactly as
in PROTOCOL.md.

C-E specifics:
- **Hedge cost:** futures at Rs20 per order plus MCX/CTT/stamp/GST, and 2 bp of slippage per
  re-hedge.
- **Capital:** 10 short straddles' margin, no netting. The futures hedge margin is assumed to
  net against them.

## Selection on discovery (fixed)
These rules are PROTOCOL.md's, with one change: the worst-trade cap is now an absolute -30% of
capital, unchanged from discovery eligibility.

1. **Eligible:**
   - coverage >= 70%;
   - net > 0;
   - PF >= 1.3;
   - t >= 1.5;
   - net > 0 at 2% slippage;
   - worst trade >= -30% of capital.
2. **Ranking:** bootstrap 5th percentile of mean trade return on capital.
3. **Candidates:** the best eligible variant from each family. There are at most 7, and none
   if a family has no eligible variant.

## Holdout test (fixed; run once)
- **Data:** the minis' own prices, expiries Jun 2024 - Oct 2026. The parents' prices over
  the same period are a cross-check.
- **A candidate PASSES if:**
  - net > 0;
  - PF >= 1.15;
  - net > 0 at 2% slippage;
  - worst trade >= -45% of capital (an absolute cap, replacing PROTOCOL.md's ratio rule,
    which broke down when discovery had no losing trade).

## Second check: walk-forward per family
For each family and year (crude 2022-26, natural gas 2024-26):
1. pick that family's best eligible variant using only cycles expiring before the year;
2. trade it in that year.

The stitched out-of-sample result is reported per family.

## Honesty notes, fixed in advance
- The holdout period was used before (Phase 1 validation and walk-forward), but not for any
  of these families.
- The family designs come from discovery-period analytics only.
- Results that fail are reported as failures.
