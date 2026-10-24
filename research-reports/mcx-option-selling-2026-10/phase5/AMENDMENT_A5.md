# Amendment A5: Phase 5, more strategies tested where nothing has looked yet (2026-10-24, before any A5 backtest)

## Why this design
- **The crude and natural-gas history is used up.** Jun 2024 – Oct 2026 has now been tested in
  four phases, and Jun 2018 – Dec 2019 in two. More variants on that data mostly find luck.
- **New evidence needs data the rules have not seen.** MCX has years of option history on
  other commodities that no phase has ever touched.

This amendment uses that data in two ways:
- **Part A, transfer test:** the rules that held up in Phases 1–4 run unchanged on the new
  markets.
- **Part B, new families:** three new families, each built on a documented economic reason.
  Each is picked on crude 2020–24 only, then run once on every other market.

## Data
**New markets:**
- MCX's official bhavcopy, downloaded with `download_more.py` to Fri 23 Oct 2026: every
  option expiry of GOLD, SILVER, COPPER, ZINC, NICKEL, GOLDM and SILVERM, plus their futures.
  The energy data is Phase 4's (to 23 Oct 2026).
- **Contract multipliers:** GOLD 100, SILVER 30, COPPER 2,500, ZINC 5,000, NICKEL 1,500,
  GOLDM 10, SILVERM 5 (₹ per ₹1 of quoted price per lot).
  - These are confirmed against the futures' traded value before any backtest.
  - Ticks are read from the data.
- **Margin:** Angel's rates as measured by the app on 9 Oct 2026 (`commodity_broker_margin.
  MEASURED_RATE`): GOLD 9.2%, SILVER 12.7%, COPPER 9.2%, ZINC 9.1%, NICKEL 9.3% of notional
  for a futures leg. A short option uses 1.2× that, as in every phase. Minis take their
  parent's rate.

**Markets and periods**

| Role | Market | Period |
|---|---|---|
| Part B discovery only | CRUDEOIL, parent prices | Jan 2020 – May 2024 |
| Test | Crude T1, parent prices | Jun 2018 – Dec 2019 |
| Test | Crude T2, CRUDEOILM's own prices | Jun 2024 – Oct 2026 |
| Test | Natural gas, parent prices | Mar 2022 – Oct 2026. Untouched for Part B. Part A rules from natural gas are not re-run here. |
| Test, untouched | GOLD, SILVER, COPPER, ZINC | Full option history (2017/18 – Oct 2026) |
| Test, untouched | NICKEL | Jan 2022 – Aug 2023 (short) |
| Cross-check, not counted | GOLDM, SILVERM | Their own prices |

## Execution (exactly as Phases 1–4)
- **Fills:** at the daily close ± 1% slippage (minimum one tick), only on strikes that traded.
  The slippage is 3× at an exit leg that did not trade that day.
- **Fees:** Angel's MCX option card. Delta-hedge futures as in A2.
- **Strikes by Black-76 delta**, as in A2.
- **Capital:** margin with no netting, plus any premium paid.
- **Expiry:** everything closes by the expiry-day close.
- **IV percentile:** each market's own front-month ATM implied vol, against its previous 250
  trading days (at least 60).

## Part A: transfer test (nothing chosen on the new data)
Each rule is run ONCE on each new market, exactly as frozen in its phase.

| Rule | Definition | From |
|---|---|---|
| CO-1 | Short put 0.5 straddle below, 15 trading days before expiry, only if IV > RV20, stop at 2× credit | Phase 1 |
| CO-2 | Trend-aware (put above SMA20, else call), 1 straddle out, 15 days, IV > 1.10 × RV20, stop 1×, exit the day before expiry | Phase 1 |
| N-B | Strangle at delta 0.10, 10 days, only when IV percentile ≤ 50, held to expiry | Phase 2 |
| C-E | Delta-hedged ATM straddle, 10 lots, 10 days, futures re-hedged at every close | Phase 2 |
| P4-W | Weekly strangle at delta 0.10, only in calm-IV weeks (IV percentile ≤ 50), front month, previous week's last close to this week's last close, no stop | Phase 4 |

## Part B: three new families (42 variants), each with its economic reason
**F1 · Weekend decay (12 variants).** Option prices fall over non-trading days. Short options
earn more across weekends (Jones & Shemesh, 2018, *Journal of Finance*).
- **Trade:** sell at the close of the week's last trading day, exit on the next trading day.
  - Contract: the front month (the nearest expiry strictly after entry).
- **Grid:**
  - structure: short ATM straddle / short strangle at delta 0.25 / at delta 0.15;
  - filter: none / IV percentile ≥ 50;
  - exit: the next day's open / the next day's close.
- **Open exits:** a leg that traded that day exits at its open ± slippage. Otherwise it exits
  at the close with 3× slippage.

**F2 · After a volatility shock (24 variants).** Implied vol overshoots after large moves, and
the variance premium is largest after spikes.
- **Shock day:** |ln(F_t / F_t−1)| ≥ k × RV20 at t−1 ÷ √252.
- **Grid:**
  - k: 2.0 / 2.5;
  - entry: the shock day's close / the next close;
  - structure: short strangle at delta 0.15 / at delta 0.25 / ATM straddle;
  - hold: 5 / 10 trading days (or to expiry if sooner).
- **Fixed rules:** stop at 2× credit at closes. One position at a time per market; shocks
  while a position is open are ignored. Front month with at least 2 trading days to expiry.

**F3 · Report-day premium (6 variants; crude and natural gas only).** Implied vol is bid ahead
of scheduled reports. Phase 4 found that report-day BUYERS lost, so this tests the sellers'
side.
- **Trade:** sell at the close before the report day and exit at the report day's close.
  Report days are Wednesday for crude (EIA) and Thursday for natural gas (storage).
- **Grid:**
  - structure: short ATM straddle / short strangle at delta 0.25 / at delta 0.15;
  - filter: none / IV percentile ≥ 50.

**Selection (crude Jan 2020 – May 2024, parent prices):**
- Eligibility, as in A2/A3:
  - coverage ≥ 70% of the trades the rule's own conditions allow;
  - net > 0, and net > 0 at 2× slippage;
  - PF ≥ 1.3;
  - t ≥ 1.5;
  - worst trade ≥ −30% of capital;
  - at least 3 trades.
- Rank by the bootstrap 5th percentile of return per trade on capital (5,000 draws, seed 7).
  The best eligible variant per family is frozen.

## Verdicts
- **Per market:**
  - A market gives a verdict only with at least 10 trades. Below that it is "too few".
  - **Pass** means: net > 0; PF ≥ 1.15; net > 0 at 2× slippage; worst trade ≥ −45% of
    capital.
- **A rule GENERALISES** if it passes in at least 3 markets, and in more than half of the
  markets where it has a verdict:
  - Part A counts GOLD, SILVER, COPPER, ZINC and NICKEL;
  - Part B counts crude T1, crude T2, natural gas, and the five metals.
- **Chance check.** If a rule with no edge passed a market 30% of the time, at least 3 passes
  out of 5 would happen 16% of the time, and at least 3 out of 4, 8%. Gold and silver move
  together, and so do the base metals, so the markets are not fully independent.

## Disclosures fixed now
- **The ₹10 lakh view:** for any rule that generalises, sized at the lots a ₹10 lakh account
  could carry.
- **Multiple testing:** 42 new variants plus 5 transfers. The transfers choose nothing.
- **Market size:** GOLD (1 kg) and SILVER (30 kg) lots are far larger than a ₹10 lakh account.
  They are tested because their history is long. GOLDM and SILVERM are the retail-sized
  versions and are shown as cross-checks.
- **Open exits:** F1's open exits depend on the first trade of the day, which can be thin in
  the 9:00 session.
