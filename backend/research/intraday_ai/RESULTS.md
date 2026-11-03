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
