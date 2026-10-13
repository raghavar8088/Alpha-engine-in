# BANKNIFTY option buying — research behind Index Option Buying › NIFTY BANK (2026-10-11/12)

Question: which BANKNIFTY option-BUYING strategies make money after real costs? Answer in one
line: **none is statistically proven; intraday option buying has no edge; ten distinct swing
strategies made money in both 2016-2021 and 2022-2026 at real option prices** and now run on
paper in the NIFTY BANK tab. `PROTOCOL.md` holds the pre-registered gate and its one disclosed
amendment.

## Data (not committed — `BN_DATA` points at it)

| Source | What | Script |
|---|---|---|
| Angel One candles | NIFTY BANK, NIFTY, India VIX 5-minute + daily, 2015-01 → 2026-10-09 (217k bars each; VIX 5m from 2015-12) | `bn_fetch_angel.py` |
| NSE F&O bhavcopy | every BANKNIFTY option + future close, 2,905 sessions 2015-01 → 2026-10-09, strikes ±10%, expiries ≤ 100 days | `bn_fetch_bhav.py` |
| Angel One candles | real 5-minute prices of the live Oct/Nov 2026 monthlies, 144 contracts, 48 sessions | `bn_fetch_optcandles.py` |

## Run order

| Script | Does |
|---|---|
| `bn_surface.py` | per session and monthly expiry: put-call-parity forward, ATM vol, smile fit from real closes (2,805 sessions) |
| `bn_calibrate.py` | picks the model's VIX pass-through and smile dynamics on 2016-21 only → sticky strike, β = 0.4 |
| `bn_model_check.py` | one-day premium change vs real closes, 22,479 option-days: bias ≤ 0.4% of premium for the contracts traded, corr 0.98 |
| `bn_intraday_check.py` | vs real 5-minute option prices (Aug-Oct 2026): 30 / 60 / 120-minute / to-15:15 bias −0.08 / −0.12 / −0.37 / −0.42% |
| `bn_lib_replay.py` | the library's 167 intraday option-buying strategies, live-desk rules, monthly ATM |
| `bn_family_replay.py` | 66 BANKNIFTY intraday rules (`app/services/banknifty_strategies.py` — the code the live desk runs) |
| `bn_swing_replay.py` | 48 library swing + 16 BANKNIFTY daily rules at REAL closing premiums, decided at 15:20 |
| `bn_benchmarks.py` | signal-free benchmarks: always calls / puts / straddles |
| `bn_real_check.py` | re-prices the replays' own Aug-Oct 2026 intraday trades with real option candles: −Rs807 real vs −Rs894 modelled a trade |
| `bn_gate.py out.json` | scores all 297 trials against the protocol, picks ten, writes `app/data/banknifty_research.json` |

## Results

* Tier A (significant in both periods, DSR ≥ 0.95): **0**. Tier B: **0**. Tier C (positive in both): **11** of 280 eligible.
* Intraday (233 trials): index moved the bought option's way on 49% of trades; median strategy −Rs245 to −Rs322 a trade after costs. One marginal positive (`bn_gap_go_80bp_1515`, +Rs16 a trade after 2022).
* Daily (64 trials, real prices): ten positive in both periods; profit mostly from calls and a few large winners. Holding calls with no signal LOST −Rs740 a trade in 2022-26 (t −2.4), so the timing added something; straddles lose (t −5.5, the volatility risk premium).
* The ten chosen: `livermore_pivotal_point`, `swing_fractal`, `wt_btst`, `swing_gap_trend`, `bn_d_donchian_10`, `bn_d_donchian_20`, `swing_3day_momo`, `qullamaggie_flag`, `swing_cci`, `bn_gap_go_80bp_1515` — the 11 Tier C minus `mr_btst_finnifty` (0.76 correlated with `wt_btst`).

## Live parity (2026-10-12)

The live engine (`app/services/banknifty_desk.py`) recomputed what each strategy wanted on the last
25 sessions from the server's own bar store: 191 of 192 comparable decisions were identical to the
research's. The one difference (`wt_btst`, 2026-10-07) is data, not code: Angel's historical
candles lack that day's 15:15 and 15:20 bars, which the server's live stream had, and the 15:20
price sat on the strategy's 40%-of-range threshold.
