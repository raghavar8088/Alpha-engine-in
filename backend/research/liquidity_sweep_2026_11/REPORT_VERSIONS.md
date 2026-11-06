# Liquidity Sweep versions: backtest report, 6 Nov 2026 (round 2)

**Verdict: none of the 27 versions works.** Each changes one rule of the original Booming Bulls liquidity sweep: the levels, the confirmation, the exit, a filter, the timeframe or the instrument.

- After costs, every version loses in every period.
- Before costs, none clears the pre-registered bar (t ≥ 3 in 2016–2022 and positive afterwards).
- The best before-cost result is t 2.32. That is about what the luckiest of 27 random versions shows.

The original (`bb_liquidity_sweep`, D9) is unchanged. It is v00 in the table and reproduces round 1 exactly.

- **Rules:** [PREREGISTRATION_VERSIONS.md](PREREGISTRATION_VERSIONS.md), SHA-256 `ad8a63189373a7c6033365ebe99f17678687c3b0090341113e71f922c3921a67`, fixed before the run.
- **Code:** `strategy-service/.../options_buying/booming_bulls_sweep_versions.py`.
- **Checks:** `ls_versions_verify.py`, 112 of 112 pass. They include:
  - the version engine at its defaults reproducing the original signal for signal over all 2,639 sessions;
  - exit-candle parity on every real trade of every version.

## Scoreboard

Each version's trades are on its own instrument (NIFTY unless the row says otherwise), 2016 to 23 Oct 2026. R = the trade's planned risk. Costs are one futures lot with Angel One charges plus 1 point of slippage per fill.

- **S:** 2016–2022 (selection).
- **V:** 2023 to 23 Sep 2025 (validation).
- **P:** 24 Sep 2025 to the last day on disk (the PDF's period).

| Id | One change from the original | Trades | Gross R: S / V / P (t in S) | Net R: S / V / P | Net ₹/lot in P |
|---|---|---:|---|---|---:|
| v00 | none (the original) | 4,140 | −0.002 / +0.006 / −0.025 (−0.09) | −0.41 / −0.34 / −0.56 | −₹3,69,585 |
| v01 | levels: PDH/PDL only | 790 | −0.080 / +0.088 / −0.133 (−1.32) | −0.45 / −0.23 / −0.57 | −₹1,05,537 |
| v02 | levels: PDC only | 1,021 | −0.074 / −0.092 / −0.036 (−1.38) | −0.39 / −0.37 / −0.40 | −₹99,367 |
| v03 | levels: equal highs/lows only | 3,556 | **+0.068** / +0.017 / −0.009 (**2.32**) | −0.37 / −0.35 / −0.57 | −₹2,78,713 |
| v04 | levels: 1-hour swings only | 1,093 | −0.067 / −0.067 / −0.163 (−1.33) | −0.49 / −0.40 / −0.68 | −₹1,00,985 |
| v05 | levels: + round numbers | 4,515 | −0.043 / −0.026 / −0.083 (−1.70) | −0.44 / −0.36 / −0.58 | −₹4,71,714 |
| v06 | wick sweeps only | 2,891 | −0.002 / −0.051 / −0.050 (−0.07) | −0.49 / −0.45 / −0.63 | −₹2,72,995 |
| v07 | strong rejection candle | 3,235 | −0.005 / +0.038 / +0.021 (−0.17) | −0.36 / −0.26 / −0.46 | −₹2,54,722 |
| v08 | next-candle confirmation | 2,815 | −0.023 / +0.018 / +0.142 (−0.72) | −0.37 / −0.28 / −0.29 | −₹1,48,502 |
| v09 | retest-and-reject entry | 2,228 | −0.055 / +0.139 / +0.132 (−1.54) | −0.48 / −0.23 / −0.41 | −₹1,54,105 |
| v10 | market-structure shift entry | 809 | −0.093 / −0.004 / −0.038 (−1.81) | −0.31 / −0.18 / −0.29 | −₹99,896 |
| v11 | target 1:1 | 4,317 | +0.003 / +0.002 / −0.002 (0.13) | −0.41 / −0.35 / −0.54 | −₹3,54,887 |
| v12 | target 1:3 | 4,018 | −0.029 / −0.013 / −0.044 (−0.93) | −0.44 / −0.36 / −0.57 | −₹3,75,872 |
| v13 | breakeven at +1R | 4,217 | +0.014 / +0.024 / +0.017 (0.59) | −0.40 / −0.32 / −0.52 | −₹3,19,394 |
| v14 | target = opposite liquidity | 4,074 | +0.018 / +0.024 / −0.049 (0.56) | −0.39 / −0.32 / −0.58 | −₹3,58,784 |
| v15 | no target (stop or 15:15) | 3,789 | +0.065 / +0.059 / −0.022 (1.21) | −0.34 / −0.28 / −0.55 | −₹3,51,769 |
| v16 | 200-EMA side filter | 2,231 | +0.027 / +0.095 / +0.115 (0.76) | −0.38 / −0.25 / −0.43 | −₹1,39,408 |
| v17 | big sweeps only (risk ≥ 0.15%) | 1,702 | −0.080 / +0.040 / −0.107 (−2.14) | −0.30 / −0.13 / −0.37 | −₹1,58,395 |
| v18 | morning only (to 11:15) | 2,027 | −0.052 / +0.030 / −0.060 (−1.34) | −0.42 / −0.28 / −0.50 | −₹1,74,734 |
| v19 | afternoon only (from 12:00) | 2,937 | **+0.065** / +0.031 / +0.024 (**2.08**) | −0.38 / −0.36 / −0.57 | −₹2,51,434 |
| v20 | one trade a day | 2,453 | −0.031 / −0.037 / −0.101 (−0.90) | −0.42 / −0.36 / −0.61 | −₹2,56,823 |
| v21 | breakout-and-retest (the video's other entry) | 528 | −0.084 / +0.083 / −0.055 (−1.14) | −0.62 / −0.36 / −0.74 | −₹38,978 |
| v22 | full video: sweeps + break-retests | 4,292 | −0.014 / +0.016 / −0.055 (−0.53) | −0.43 / −0.33 / −0.60 | −₹4,10,076 |
| r1 | 15-minute candles (research only) | 2,036 | −0.106 / +0.035 / −0.139 (−2.93) | −0.45 / −0.26 / −0.55 | −₹2,45,536 |
| r2 | 3-minute candles (research only) | 4,911 | −0.026 / −0.024 / −0.029 (−1.06) | −0.46 / −0.39 / −0.60 | −₹4,17,802 |
| r3 | BANK NIFTY, data to 9 Oct 2026 (research only) | 4,170 | −0.040 / −0.029 / −0.018 (−1.49) | −0.32 / −0.30 / −0.46 | −₹3,75,267 |
| r4 | SENSEX, data to 9 Oct 2026 (research only) | 4,174 | +0.013 / −0.026 / +0.058 (0.47) | −0.28 / −0.31 / −0.40 | −₹1,90,990 |

## What the table says

1. **No version has a raw edge to manage.**
   - The original makes 0.000R before costs. Rewiring the exit doesn't change that: 1:1, 1:3, breakeven, opposite liquidity and no target all stay within ±0.07R. With no edge at entry there is nothing for an exit to protect.
2. **The two best before-cost results don't hold up.**
   - **v03 (equal highs/lows only).** +0.068R in 2016–2022 (t 2.32), then +0.017R and −0.009R. It fades to nothing.
   - **v19 (afternoon only).** +0.065, +0.031, +0.024. It is positive in all three periods but small and never significant.
   - Both are at or below the luck bar for 27 tries.
3. **Three entries look better only since 2023.**
   - These are v09 (retest entry), v08 (next candle) and v16 (200-EMA filter), at +0.10–0.14R in V and/or P.
   - Each was flat or negative in 2016–2022.
   - That pattern is what a regime change or chance produces. It would need new data (a forward paper test) before anyone trusted it, and even +0.14R is about a third of the costs.
4. **The least-bad results after costs** are v17 (big sweeps, −0.27R) and v10 (MSS, −0.27R). They lose *less* because their stops are bigger (median 30–32 points), so the fixed costs are a smaller share of each trade. Before costs both are negative.
5. **Costs decide everything.**
   - A NIFTY futures round trip costs about 0.3–0.6R at these stop sizes: ~16 points since STT rose to 0.05% on 1 Apr 2026.
   - The best raw signals here (+0.05 to +0.14R) are several times smaller than that.
6. **Other instruments behave the same.** BANK NIFTY and SENSEX run under the same rules and land at about 0R before costs.

## In the app

- **22 versions are registered** in the option-buying library, as `bb_ls_v01_pdh_pdl` … `bb_ls_v22_full_video`. The app adds an ANTI mirror for each automatically.
- **Not registered:**
  - r1 (15-minute): it would join the stock desks' live paper library.
  - r2 (3-minute): the app has no 3-minute timeframe.
  - r3 and r4: they are instruments, not new strategies.
- **No desk trades them by itself.** Prelive trades only Buying Lab qualifiers, and the crypto module marks options strategies unsupported.
- **The Options Buying Lab will flatter them.** As round 1 found for the original, its engine has no bid-ask spread, so some versions may show a small profit there.

## Reproduce

See [README.md](README.md), round 2 steps.
