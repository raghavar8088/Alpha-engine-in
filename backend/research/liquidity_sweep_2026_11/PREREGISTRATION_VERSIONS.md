# Liquidity Sweep versions: rules and test plan, fixed before the first run (round 2)

**Request (6 Nov 2026):** "keep this strategy as the original, then create different versions of this strategy, backtest those strategies also."

- **The original is untouched.** `bb_liquidity_sweep` (D9) in `booming_bulls.py` keeps its code, rules and results (PREREGISTRATION.md, REPORT.md).
- **Where the versions live.** Each version is the original with **one** rule changed. They are in `strategy-service/.../options_buying/booming_bulls_sweep_versions.py`.
- **How they are built.** All versions share one subclass engine. With no change applied, that engine must reproduce the original signal for signal over all 2,639 sessions, and this is checked.
- **Hashing.** This file was written and hashed before any version was run. Nothing in it changes after results are seen.

**Already seen (disclosed).** All of the original's round-1 results:

- P and H totals;
- the breakdowns by level type, side, entry hour and month;
- runs B (200 EMA) and C (3-minute).

The versions below come from the video and PDF and from standard liquidity-sweep practice (ICT/SMC), not from those breakdowns. Where a family slices one dimension, every slice is included (each level type alone; morning and afternoon), not just the slice that looked best.

## Versions (each = the original + one change)

| Id | Strategy id | Change |
|---|---|---|
| v00 | `bb_liquidity_sweep` | The original, as the baseline. |
| v01 | `bb_ls_v01_pdh_pdl` | Levels: only PDH and PDL. |
| v02 | `bb_ls_v02_pdc_only` | Levels: only PDC. |
| v03 | `bb_ls_v03_equal_hl` | Levels: only equal highs/lows. |
| v04 | `bb_ls_v04_1h_swings` | Levels: only 1-hour swing highs/lows. |
| v05 | `bb_ls_v05_round_numbers` | Levels: the original's, plus every multiple of 100 within ±1% of the open. Round numbers are day levels, as in the PDF's "round number trap". |
| v06 | `bb_ls_v06_wick_only` | Confirmation: the sweep candle itself must close back inside. A candle closing beyond the level is a breakout. |
| v07 | `bb_ls_v07_strong_reject` | Confirmation: the confirming candle must close at least 2/3 of its range away from its extreme (the low third for a short, the high third for a long). |
| v08 | `bb_ls_v08_next_candle` | Confirmation: the candle after the confirming candle must close further in the trade's direction. Entry at that close. Otherwise the setup is dropped. |
| v09 | `bb_ls_v09_retest_entry` | Entry: after the close back inside, wait up to 30 minutes for a candle that trades back to the level and closes back inside again. Entry at that close. A close beyond the level cancels the setup. |
| v10 | `bb_ls_v10_mss` | Entry: market-structure shift. The reference is the lowest low (for a short) or highest high (for a long) of the 6 candles before the sweep began. A candle must close past it within 30 minutes of the confirmation; if the confirming candle already did, entry is immediate. A close beyond the level cancels the setup. |
| v11 | `bb_ls_v11_target_1r` | Target: 1:1. |
| v12 | `bb_ls_v12_target_3r` | Target: 1:3. |
| v13 | `bb_ls_v13_breakeven` | Exit: once a candle closes after price has reached +1R, the stop moves to the entry price. |
| v14 | `bb_ls_v14_opposite_liq` | Target: the nearest live opposite-side level at least 1R away, capped at 4R. With no such level, 4R. |
| v15 | `bb_ls_v15_no_target` | Exit: no target. The trade closes at the stop or at 15:15. |
| v16 | `bb_ls_v16_ema200` | Filter: longs only above the 5-minute 200 EMA, shorts only below it. Same as round 1's run B. |
| v17 | `bb_ls_v17_big_sweeps` | Filter: risk between 0.15% and 0.35% of price, i.e. PDF-sized sweeps only. |
| v18 | `bb_ls_v18_morning` | Filter: entries only from candles closing 09:20–11:15. |
| v19 | `bb_ls_v19_afternoon` | Filter: entries only from candles closing 12:05–14:45. |
| v20 | `bb_ls_v20_one_a_day` | Filter: at most 1 trade a day. |
| v21 | `bb_ls_v21_break_retest` | The video's other entry: when a level is broken and accepted (30 minutes beyond it), wait for a candle that comes back to it and closes on the breakout side. Enter in the breakout direction. Stop past that candle's extreme plus 0.02%, target 2R. A close back through the level cancels. No sweep trades. |
| v22 | `bb_ls_v22_full_video` | The whole video: the original's sweep trades plus v21's breakout-retest trades. They share one position and the 2-a-day limit. |

**Research only, not registered.**

| Id | What | Why not registered |
|---|---|---|
| r1 | The original on 15-minute candles | Registering a 15-minute strategy would add it to the stock desks' live paper library. |
| r2 | The original on 3-minute candles (round 1's run C) | The app has no 3-minute timeframe. |
| r3 | The original on BANK NIFTY, futures lot 30 | A change of instrument is not a new strategy in the app. |
| r4 | The original on SENSEX, lot 20, costed with the NSE futures formula | Same reason as r3. |

Every other rule and number stays as in PREREGISTRATION.md §1, including:

- the 0.04% equal-high tolerance;
- 2-candle swings;
- the 30-minute acceptance window;
- the 0.02% stop buffer;
- the 0.05–0.35% risk band (except v17);
- 2 trades a day (except v20);
- entries by 14:45 and out at 15:15.

## Test plan

Data, fills and costs are as in PREREGISTRATION.md §2:

- 1-minute candles cleaned by `index_intraday.data._build`;
- entry at the confirming candle's close;
- stop or target on 1-minute candles, stop first when one minute touches both;
- out at 15:15;
- one futures lot with Angel One charges on the trade date, plus 1 point of slippage per fill.

Two additions:

- v13's stop moves to entry only after the candle that reached +1R has closed.
- v15 has no target.

**Periods.**

| Period | Dates | Role |
|---|---|---|
| S | 1 Jan 2016 – 31 Dec 2022 | Selection |
| V | 1 Jan 2023 – 23 Sep 2025 | Validation |
| P | 24 Sep 2025 – 23 Oct 2026 | The PDF's period plus the 4 sessions after it |

**Verdicts, fixed now, one per version.**

- **PASS (tradeable):** net R/trade > 0 with t ≥ 3.0 in S, and net R/trade > 0 in V and in P. The bar is t ≥ 3, not 2, because 27 versions are being tested; by luck alone the best of 27 would show t ≈ 2.
- **RAW EDGE (a real signal that costs eat):** the same three conditions on gross R/trade, before costs.
- **NO EDGE:** everything else.

No version is tuned after the run. Combining versions would be a new, separately pre-registered round.
