# Deviations from PROTOCOL.md (sha256 93306f5c298b6d117ba52d167f134686899d4e23a08a275b40cc34ca0479c2cb)

1. **Validation-period descriptive statistics were seen before the candidates were frozen
   (2026-10-22).** While debugging `vrp.py` on a partial download, I printed the
   implied-vs-realised volatility table for CRUDEOILM and NATGASMINI over Jun 2024 - Oct 2026,
   which is the validation period. One column, "straddle > |move|", is a costless
   short-straddle statistic. No strategy, cost model or selection rule was run on validation
   data. The selection is mechanical (`search.py`), and nothing in the protocol or its rules
   changed afterwards.

2. **A bug in `search.py` was fixed before any selection was made.** The variant ID left out
   the instrument, so the first run crashed before choosing anything. The ID now includes it.
   It was then re-run unchanged: same rules, same grid.

3. **The validation tail rule breaks down when discovery had no losing trade.** The rule is
   "worst validation trade no worse than 1.5x the discovery worst". If the discovery worst was
   a gain, the rule demands a validation worst that is an even bigger gain. This affected 3
   natural-gas candidates. Two of them lost money in validation anyway. The third, an NG short
   strangle (k = 1.25, entry 20, profit-take 50%), made +Rs10,701 with PF 1.60, but its worst
   trade lost 40% of its capital. It fails the rule as written. It would pass a generous
   reading (1.5 x the -30% eligibility cap = -45%). It is reported as borderline and NOT
   promoted.

4. **The walk-forward stage (`AMENDMENT_A1.md`) was designed after seeing the validation
   results.** Its trend-aware family was motivated partly by the natural-gas short calls
   failing in rallies. The natural-gas walk-forward years 2024-26 are therefore not blind for
   that family. For crude the family was motivated by the literature (crude variance is
   put-like), but the crude validation results had also been seen.

5. **NG-X is in-sample only.** NG-X is the natural-gas short call 1.5 straddles above, 7
   trading days before expiry, with a 1x stop. It was found AFTER both honest tests had
   failed for natural gas, by screening all 21,870 variants for "positive in every year
   2022-2026". The walk-forward procedure, which could have chosen it, did not choose it in
   any test year. It is reported as an unvalidated idea for paper trading only.
