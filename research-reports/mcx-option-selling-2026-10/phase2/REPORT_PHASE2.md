# Phase 2: strategies built from the option data itself (22 Oct 2026)

## The answer first
- I analysed the MCX option data to find where the premium actually is.
- From that, I built 7 new strategy families.
- I selected the best variant of each on old data only, then tested it ONCE on Jun 2024 –
  Oct 2026 data it had never seen, using the minis' own prices.
- **4 of 7 passed**, including the first natural-gas strategy to survive an honest test.

| | New strategy | Holdout, Jun 2024 – Oct 2026 (per lot) | Full history | Verdict |
|---|---|---|---|---|
| **C-E** | Crude **delta-hedged** ATM straddle, 10 trading days before expiry, futures hedge rebalanced at every close (per 5 lots) | **+₹94,341**, 29 cycles, PF 2.31 | +₹2,53,199 (82 cycles); **every year 2020–26 positive** | ✅ strongest |
| **N-B** | **Natural gas** strangle at delta 0.10, 10 days out, **only when implied vol is calm** (≤ its 1-year median) | **+₹6,287**, 15 trades, 93% wins, PF 3.88 | +₹16,267 (32 trades, 97% wins); every year positive | ✅ first natural-gas pass |
| **C-B** | Crude short put at delta 0.15, 5 days out | +₹2,984, 90% wins, PF 1.50 | +₹14,841 (82 trades, 95% wins); every year positive | ✅ small but steady |
| **C-C** | Crude strangle at delta 0.15, 5 days out | +₹4,386, PF 1.36 | +₹21,935 (80 trades); 2025 negative | ✅ passed, fading |
| C-A | Crude short call at delta 0.20, 7 days out | +₹1,618, PF 1.12; negative on parent prices | | ❌ |
| C-D | Crude strangle only when implied vol is HIGH | −₹2,673; one trade −40% | | ❌ |
| N-A | Natural-gas far-wing strangle (delta 0.08) | −₹2,507; worst −33% | | ❌ |

**A diversified ₹10 lakh portfolio**, run over the 2024–26 holdout on the minis' own prices:
- **Holdings:** C-E 5 lots, CO-1 3 lots, CO-2 3 lots, N-B 5 lots.
- **Total:** **+₹1,88,108 (+18.8% over 29 months)**.
- **Risk:** 72% of months positive, worst month −₹35,650, max drawdown ₹36,267.
- **Capital:** at most ~₹8.3 lakh in use at once.
- **Last 30 days:** about **+₹32,100**.

## What the option data showed
These analytics ran on the discovery period only: crude Jan 2020 – May 2024, natural gas Mar 2022 – Apr 2024.

| Question | Crude | Natural gas |
|---|---|---|
| Where is the premium? (short and hold, cycle-averaged, after costs) | OTM **calls** at delta 0.05–0.20 with 4–12 days left are the most reliable (t 5–10). Short-dated **puts** (1–7 days, delta 0.05–0.20) are also reliable (t 3–9). Long-dated far puts lose. | Only the far wings (delta 0.02–0.05, 8–22 days) were reliable. Elsewhere the call/put split was the 2022–23 crash. |
| Does a bigger IV/realised-vol gap predict profit? | **No** (correlation 0.00) | No |
| Does the IV **level** predict profit? | Yes: higher IV, better strangle (+0.45 to +0.54) | **Reversed:** calm IV, better strangle |
| Skew, put/call OI ratio, max-OI "walls" | No reliable signal | Inconsistent |
| Inventory report days (crude Wednesday, gas Thursday) | No penalty for sellers | No penalty |
| Delta-hedged ATM straddle (the "pure" volatility premium) | **Positive** (t 2.1–2.5) | No edge |

Two of those findings became the winners:
- **The pure volatility premium in crude (C-E).** Hedging the direction away left a steady profit every year.
- **Calm-only selling in natural gas (N-B).** Natural gas punishes sellers in turbulent regimes; staying out of them is what makes it sellable.

## How it was tested (pre-registered)
- `AMENDMENT_A2.md` (sha256 `7886a9f9…`) fixed the 7 families, all 154 variants, and the selection and pass rules before any of them ran.
- `AMENDMENT_A2_1.md` (`a3ed20e7…`) clarified, still before running anything, that the vol-filtered families' coverage is counted over the months the filter allows.
- The frozen candidates are `p2_candidates_frozen.json` (`d459142a…`).

The process:
1. **Discovery:** best eligible variant per family on old data. All 7 families produced one.
2. **Holdout, run once** on Jun 2024 – Oct 2026 mini prices. To pass, a strategy needed:
   - net > 0;
   - PF ≥ 1.15;
   - net > 0 at 2% slippage;
   - worst trade ≥ −45% of capital.
3. **Walk-forward per family:** each year the family's best variant was picked on earlier data and traded that year.
   - C-E: +₹3.97 lakh per 10 lots over 2022–26, positive every year.
   - C-B: +₹9,837, every year positive.
   - N-B: +₹5,898 over 2024–26.
   - C-C: +₹2,963 (2025–26 negative).

## The four new strategies, exactly
These use the same definitions as `REPORT.md`:
- every decision and fill is at the daily close, only on strikes that traded;
- delta is from Black-76;
- positions are held to the expiry-day close unless stated.

### C-E · Crude delta-hedged straddle
- **Entry:** 10 trading days before expiry, sell N ATM straddles (call + put at the strike nearest the futures).
- **Every close until expiry:** compute the straddle's delta, hold `round((call delta + put delta) × N)` CRUDEOILM futures, and buy or sell the difference.
- **Exit:** close the options and the hedge at the expiry-day close.
- **Results:**
  - per 5 lots: full history +₹2,53,199 (82 cycles, PF 2.78); holdout +₹94,341 (PF 2.31);
  - per 10 lots: +₹5,35,711, positive every year 2020–2026 (₹50k–96k a year).
- **Robust:**
  - entry 8 or 12 days gives +₹3.8L / +₹5.5L per 10 lots;
  - 5 or 20 lots gives the same per-10-lot result;
  - without its best trade, +₹4.48L.
- **Capital:** the option margin plus the futures hedge's margin. Angel did not net option positions, so assume it will not net the hedge either. For 5 lots that is ~₹2.9–3.2 lakh on average and up to ₹4.7 lakh at peak.
- **Worst:** −₹42,193 per 5 lots in the holdout.
- **Practical cost:** it needs a daily re-hedge near the 23:30/23:55 close. It is the most operationally demanding strategy, and the least correlated with the others (0.06–0.31).

### N-B · Natural gas calm-volatility strangle
- **Filter:** trade only if today's front-month ATM implied vol is at or below its median of the previous 250 trading days. That happens in about half of months.
- **Entry:** 10 trading days before expiry, sell the call and the put whose |delta| is nearest 0.10. Hold to the expiry-day close.
- **Results:**
  - holdout: 15 trades, +₹6,287 per lot, 93% wins, PF 3.88, worst −₹2,186;
  - full history: 32 trades, +₹16,267, 97% wins, every year positive.
- **Robust:** delta 0.08 or 0.15, entry 8 or 12 days, and filter thresholds 40 or 60 all stay positive (₹9.7k–23.5k).
- **Caveat:** few trades, so modest certainty.

### C-B · Crude short put, delta 0.15, 5 days before expiry
- **Rule:** sell the put whose |delta| is nearest 0.15, 5 trading days before expiry, and hold.
- **Results:**
  - holdout: +₹2,984 per lot (90% wins);
  - full history: +₹14,841 (82 trades, 95% wins), every year positive.
- **Overlap:** correlated 0.69 with CO-1, so they are largely the same put bet.

### C-C · Crude strangle, delta 0.15, 5 days before expiry
- **Rule:** both sides at delta 0.15, 5 trading days before expiry, held to expiry.
- **Results:** holdout +₹4,386 per strangle; full history +₹21,935; 2025 negative.
- **Verdict:** a weaker pass.

## Everything now on the shelf (Phases 1 + 2), by strength of evidence
| Strategy | Evidence | Per lot, full history | Holdout (mini) | Last 30 days per lot | Correlation note |
|---|---|---|---|---|---|
| **C-E** crude delta-hedged straddle | holdout ✅ + walk-forward ✅ | +₹2.53L per 5 lots | +₹94,341 per 5 lots | +₹18,040 per 5 lots | independent of the rest |
| **CO-1** crude put 0.5 straddle, 15 days, IV filter | strict pre-registered test ✅ | +₹36,516 | +₹12,088 | +₹2,710 | |
| **CO-2** crude trend-aware, 1 straddle out, 15 days | walk-forward ✅ | +₹26,593 | +₹8,690 | +₹1,324 | negative vs C-B/C-C |
| **CO-3** crude trend-aware, 0.5 out, 10 days | walk-forward ✅ | +₹36,684 | +₹10,260 | +₹1,001 | 0.51 with CO-1 |
| **N-B** natural-gas calm strangle | holdout ✅ + walk-forward ✅ | +₹16,267 | +₹6,287 | +₹393 | |
| **C-B** crude put, delta 0.15, 5 days | holdout ✅ + walk-forward ✅ | +₹14,841 | +₹2,984 | +₹546 | 0.69 with CO-1 |
| C-C crude strangle, delta 0.15, 5 days | holdout ✅ (weak) | +₹21,935 | +₹4,386 | +₹1,007 | 0.71 with C-B |
| CO-5 / NG-X | weak / unvalidated | see REPORT.md | | | |

## Caveats
- **Backtests, not live fills.** Daily closes cannot see intraday spikes. The close is the last trade of a session ending 23:30/23:55 IST.
- **C-E is the most complex.** Its results assume a disciplined daily re-hedge with 2 bp futures slippage. Missed hedges change the risk completely.
- **Multiple testing.** 154 variants were tried in Phase 2, on top of 21,870 in Phase 1. The holdout and walk-forward guard against luck, but they cannot remove it.
- **The holdout was used before.** It was used in Phase 1 for other strategies; the Phase 2 families were never run on it before their single test.
- **Margin estimates** are from Angel's calculator measured on 9 Oct 2026. Recheck before trading.
- **Paper-trade first** for 2–3 monthly cycles.

## Files (phase2/)
| File | What it is |
|---|---|
| `analytics.py` | Option-data analysis |
| `engine2.py` | Delta strikes, IV percentile, hedged straddle |
| `run_phase2.py` | Discovery and holdout |
| `robust2.py` | Robustness and sizing |
| `AMENDMENT_A2*.md` | Pre-registration |
| `p2_candidates_frozen.json` | Frozen candidates |
| `results/` | Outputs |
