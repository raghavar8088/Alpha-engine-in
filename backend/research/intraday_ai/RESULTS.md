# Results — Intraday Stocks AI upgrade (pre-registered tests and checks)

Each test is judged by the rule stored in `prereg/<name>.json`, committed before it ran.
Data: exports of 3–4 Nov 2026; research data in `D:/intraday_ai_data` (not in the repo).

## Phase 2 — backtest fidelity (4 Nov 2026)

Run `fid_live10L`: code `f8d054b`, 6 Oct – 3 Nov 2026 (20 sessions), ₹10 lakh slots, `--live-rules --live-universe`; `fidelity.py`.

| | Result | Target |
|---|---|---|
| Live trades reproduced | 4,524 of 8,109 (55.8%) | ≥ 60% — **not met** |
| Same exit reason on shared trades | 94.8% | ≥ 95% — **not met** |

Why the gap remains:
- The two Selected ORB rules (76 live trades) need the Scanner Board's expected-move ranks, which the backtest doesn't compute: 0 reproduced.
- The ORB stocks-in-play rules agree on only 82–86% of exits. On 15-minute bars a trigger bar that also reaches the stop counts as stopped.
- The rest is path dependence: live exits on minute bars free slots at different moments.

`accept_live` reproduces the hand-written joint replay exactly (top 10: 1,292 trades, +₹1,87,974, identical skip counts).

Two-year dataset `y2`:
- 495 sessions (4 Nov 2024 – 3 Nov 2026).
- 1,134,273 candidate trades; 130,255 taken under the live rules.
- 147,427 signal rows with features for the six rules.

## P3_cost_model — **KEEP BAND MODEL**
Registered `fd2cc2a`, fingerprint `a0b904044f6b0e0b`.

H1 entry samples: 1,941 for training (to 26 Oct), 1,414 for testing (27 Oct – 3 Nov).

| | Test MAE (bp) |
|---|---|
| Book model (OLS) | 2.077 |
| Band baseline (training data only) | 2.210 |
| Ratio | 0.94 — the rule needed ≤ 0.90 |

What the fit still shows:
- Each 1 bp of half-spread adds 0.72 bp of cost.
- A thin book (the order beyond the five visible levels) adds 0.84 bp.
- Buys are 0.84 bp cheaper than sells.
- Each tenfold rise in turnover cuts 0.93 bp.

## P3_limit_entry — **NO-GO for all six rules**
Registered `fd2cc2a`, fingerprint `7eb11697337e9c15`.

Holdout (4 May – 3 Nov 2026), net bp per signal:

| Rule | Signals | Limit fill rate | Market net/signal | Limit net/signal | t (limit) | Gross the limit missed |
|---|---|---|---|---|---|---|
| donchian_45m | 8,432 | 94.5% | −10.09 | −8.61 | −3.79 | +31.7 |
| donchian_1h | 7,235 | 94.2% | −9.02 | −7.92 | −3.17 | +40.9 |
| vwap_trend_1h | 10,826 | 94.2% | −8.80 | −7.33 | −5.95 | +32.4 |
| macd_trend_1h | 4,903 | 93.7% | −6.42 | −4.80 | −2.57 | +28.6 |
| rsi_momentum_45m | 11,287 | 93.9% | −9.12 | −7.75 | −4.57 | +33.1 |
| bollinger_snap_1h | 5,378 | 93.4% | −8.79 | −7.32 | −3.27 | +26.1 |

Reading the results:
- **Filled trades:** limit orders fill 93–94% of the time and save the whole entry cost (filled limit trades gross +3.1 to +3.4 bp more than at market).
- **Missed signals:** the 6–7% they miss are the runaway winners, which earn +26 to +41 bp gross at market.
- **Net effect:** about 1.3 bp better per signal, but every rule stays clearly negative after the measured exit costs and charges.

Plan decision point D1: limit entries fail for all six, so only the signal scorer (Phase 7) can close the gap, which is now 5–9 bp per signal.

## P5_move_model — **KEEP OLS**
Registered `668be3e`, fingerprint `dd5fcc770aeeb2d0`.

64,304 stock-days (249 stocks, 480 sessions, point-in-time top 200), walk-forward by month.

| | Development (247 days) | Holdout (127 days) |
|---|---|---|
| Rank IC, OLS (production form) | 0.244 | 0.246 |
| Rank IC, LightGBM (+10 features) | 0.216 | 0.238 |
| Top-20 move, OLS (bp) | 153.9 | 164.9 |
| Mean move, all stocks (bp) | 98.3 | 102.9 |

The gradient-boosted model is worse in both periods, so the scanner keeps its OLS. The OLS genuinely ranks movers: its top 20 move about 60% more than the average stock.

## P5_big_mover — **NO-GO** (all six rules and the pool)
Registered `668be3e`, fingerprint `aca4446fae55ee64`.

Six rules' signals restricted to the day's top 40 expected movers (OLS, walk-forward). Holdout net bp per signal:

| Rule | Filtered (t) | All signals |
|---|---|---|
| donchian_45m | −4.92 (−1.07) | −10.49 |
| rsi_momentum_45m | −4.72 (−1.57) | −9.64 |
| donchian_1h | −3.83 (−0.82) | −9.39 |
| macd_trend_1h | +1.30 (0.28) | −6.71 |
| bollinger_snap_1h | −9.26 (−2.02) | −9.19 |
| vwap_trend_1h | −7.31 (−2.66) | −9.11 |
| Pooled | −5.16 (−1.92) | −9.28 |

The filter roughly halves the loss for the trend and breakout rules (about +4 bp a signal), but nothing is positive with t ≥ 2. Its rank goes into the Phase 7 scorer as a feature.

## P6_context — **NO-GO** (all five hypotheses)
Registered `f4347f9`, fingerprint `c245bf8c9090a471`.

Pooled net bp per signal on the holdout (4 May – 3 Nov 2026):

| Filter | Filtered (t) | Whole group |
|---|---|---|
| H6_sector: TB with the sector moving their way | −9.34 (−3.97) | −9.29 |
| H6_relative: TB outrunning their sector | −9.13 (−5.27) | −9.29 |
| H6_vix (TB, high VIX) | −8.63 (−1.89) | −9.29 |
| H6_vix (R, low VIX) | −8.10 (−3.39) | −9.19 |
| H6_breadth: TB with breadth on their side | −8.01 (−2.69) | −9.29 |
| H6_expiry: all six on non-expiry days | −8.98 (−6.40) | −9.28 |

No context filter changes the result: it confirms the October finding that every market condition loses.

Feature coverage across 147k signals: sector 97.5%, VIX and expiry 100%, breadth 95.3%, delivery 91.0%, expected-move rank 93.7%. Every feature goes into the scorer.
