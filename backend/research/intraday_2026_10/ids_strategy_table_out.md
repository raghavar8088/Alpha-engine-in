| # | Strategy | Kind / TF | 2y trades | Raw edge bp | Raw t | Net bp | 2y net ₹ | Holdout ₹ | Break-even slip (bp/side) | Live 4d net ₹ | Decision |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `iv2_orb_sel30` | orb / day | — | — | — | — | — | — | — | -44,877 (8) | INCUBATE (pre-registered; S4 study) |
| 2 | `iv2_orb_sel15` | orb / day | — | — | — | — | — | — | — | 28,329 (2) | INCUBATE (pre-registered; S4 study) |
| 3 | `iv2_donchian_45m` | breakout / 45m | 3,891 | +7.48 | 3.98 | -1.85 | -719,090 | 138,370 | 1.80 | 6,570 (32) | OPTIMIZE — measure real slippage (H1) |
| 4 | `iv2_donchian_1h` | breakout / 1h | 3,503 | +6.94 | 3.45 | -2.46 | -860,662 | 300,528 | 1.50 | 171,003 (28) | OPTIMIZE — measure real slippage (H1) |
| 5 | `iv2_vwap_trend_1h` | trend / 1h | 3,783 | +6.52 | 3.54 | -2.86 | -1,078,960 | 14,334 | 1.29 | 10,210 (35) | OPTIMIZE — measure real slippage (H1) |
| 6 | `iv2_macd_trend_1h` | trend / 1h | 3,098 | +5.64 | 3.36 | -3.77 | -1,166,377 | -202,501 | 0.83 | 116,955 (31) | RESEARCH ONLY — edge < friction |
| 7 | `iv2_gap_go` | gap / day | 821 | +5.51 | 0.90 | -3.84 | -315,112 | 5,435 | 0.77 | 17,107 (8) | RESEARCH ONLY — edge < friction |
| 8 | `iv2_rsi_momentum_45m` | trend / 45m | 3,848 | +5.18 | 3.34 | -4.17 | -1,604,466 | -524,544 | 0.60 | -105,168 (31) | RESEARCH ONLY — edge < friction |
| 9 | `iv2_pdh_pdl_45m` | breakout / 45m | 2,987 | +4.91 | 2.34 | -4.40 | -1,313,679 | -125,360 | 0.47 | 106,398 (21) | RESEARCH ONLY — edge < friction |
| 10 | `iv2_ema_pullback_45m` | trend / 45m | 3,384 | +4.44 | 2.90 | -4.87 | -1,645,992 | -140,426 | 0.22 | 73,157 (37) | RESEARCH ONLY — edge < friction |
| 11 | `iv2_bollinger_snap_1h` | reversion / 1h | 3,178 | +4.20 | 3.47 | -5.01 | -1,589,266 | -456,500 | 0.09 | -31,882 (26) | RESEARCH ONLY — edge < friction |
| 12 | `iv2_supertrend_1h` | trend / 1h | 2,843 | +4.09 | 2.14 | -5.39 | -1,530,595 | -313,245 | 0.03 | 110,193 (25) | RESEARCH ONLY — edge < friction |
| 13 | `iv2_supertrend_45m` | trend / 45m | 2,977 | +3.83 | 2.01 | -5.61 | -1,667,541 | -615,351 | never | 2,273 (29) | DISABLE — fees alone exceed edge |
| 14 | `iv2_keltner_45m` | breakout / 45m | 3,284 | +3.53 | 1.95 | -5.81 | -1,906,857 | -18,099 | never | 83,899 (32) | DISABLE — fees alone exceed edge |
| 15 | `iv2_adx_dmi_45m` | trend / 45m | 2,904 | +3.26 | 2.02 | -6.17 | -1,788,854 | -346,068 | never | 30,667 (33) | DISABLE — fees alone exceed edge |
| 16 | `iv2_adx_dmi_15m` | trend / 15m | 4,357 | +3.18 | 3.19 | -6.06 | -2,638,428 | -395,033 | never | 39,842 (55) | DISABLE — fees alone exceed edge |
| 17 | `iv2_stoch_range_1h` | reversion / 1h | 702 | +3.15 | 1.47 | -5.98 | -419,423 | -143,165 | never | -29,224 (12) | DISABLE — fees alone exceed edge |
| 18 | `iv2_vwap_trend_45m` | trend / 45m | 3,181 | +3.10 | 1.76 | -6.26 | -1,989,182 | -483,657 | never | 33,447 (23) | DISABLE — fees alone exceed edge |
| 19 | `iv2_donchian_15m` | breakout / 15m | 5,413 | +3.08 | 2.56 | -6.01 | -3,250,061 | -412,594 | never | 52,571 (59) | DISABLE — fees alone exceed edge |
| 20 | `iv2_rsi_momentum_1h` | trend / 1h | 3,382 | +3.07 | 1.91 | -6.36 | -2,147,601 | -264,851 | never | 18,165 (33) | DISABLE — fees alone exceed edge |
| 21 | `iv2_cci_extreme_1h` | reversion / 1h | 2,553 | +2.65 | 1.88 | -6.43 | -1,640,061 | -475,332 | never | -3,478 (19) | DISABLE — fees alone exceed edge |
| 22 | `iv2_macd_trend_45m` | trend / 45m | 3,025 | +2.59 | 1.48 | -6.77 | -2,044,331 | -192,712 | never | 16,623 (29) | DISABLE — fees alone exceed edge |
| 23 | `iv2_vwap_trend_15m` | trend / 15m | 4,338 | +2.46 | 2.24 | -6.64 | -2,878,741 | -494,847 | never | -63,275 (46) | DISABLE — fees alone exceed edge |
| 24 | `iv2_macd_trend_15m` | trend / 15m | 4,549 | +2.02 | 1.95 | -7.10 | -3,226,523 | -519,571 | never | -55,605 (46) | DISABLE — fees alone exceed edge |
| 25 | `iv2_supertrend_15m` | trend / 15m | 4,036 | +1.80 | 1.47 | -7.48 | -3,014,494 | -643,046 | never | -70,515 (39) | DISABLE — fees alone exceed edge |
| 26 | `iv2_cci_extreme_45m` | reversion / 45m | 2,720 | +1.77 | 1.28 | -7.10 | -1,928,774 | -310,820 | never | -24,999 (19) | DISABLE — fees alone exceed edge |
| 27 | `iv2_bollinger_snap_15m` | reversion / 15m | 4,711 | +1.67 | 2.04 | -7.17 | -3,374,539 | -252,015 | never | -86,459 (58) | DISABLE — fees alone exceed edge |
| 28 | `iv2_or_close_break_1h` | breakout / 1h | 2,590 | +1.58 | 0.72 | -7.83 | -2,025,530 | 12,114 | never | -69,916 (20) | DISABLE — fees alone exceed edge |
| 29 | `iv2_cci_extreme_15m` | reversion / 15m | 4,585 | +1.47 | 1.79 | -6.97 | -3,193,011 | -264,159 | never | -96,775 (53) | DISABLE — fees alone exceed edge |
| 30 | `iv2_rsi_momentum_15m` | trend / 15m | 4,592 | +1.32 | 1.31 | -7.83 | -3,591,241 | -506,416 | never | -8,658 (51) | DISABLE — fees alone exceed edge |
| 31 | `iv2_ema_pullback_15m` | trend / 15m | 4,500 | +1.31 | 1.36 | -7.77 | -3,490,946 | -315,571 | never | -61,573 (60) | DISABLE — fees alone exceed edge |
| 32 | `iv2_or_close_break_15m` | breakout / 15m | 3,615 | +1.18 | 0.83 | -7.97 | -2,877,268 | -627,033 | never | -30,357 (34) | DISABLE — fees alone exceed edge |
| 33 | `iv2_bollinger_snap_45m` | reversion / 45m | 3,060 | +1.17 | 0.93 | -7.92 | -2,421,168 | -293,353 | never | -121,343 (25) | DISABLE — fees alone exceed edge |
| 34 | `iv2_keltner_1h` | breakout / 1h | 2,862 | +0.93 | 0.50 | -8.50 | -2,429,047 | -11,979 | never | 102,567 (28) | DISABLE — fees alone exceed edge |
| 35 | `iv2_zscore_45m` | reversion / 45m | 1,472 | +0.82 | 0.39 | -8.46 | -1,243,161 | -239,642 | never | -11,937 (14) | DISABLE — fees alone exceed edge |
| 36 | `iv2_or_close_break_45m` | breakout / 45m | 2,733 | +0.75 | 0.35 | -8.62 | -2,353,206 | -472,683 | never | -25,222 (16) | DISABLE — fees alone exceed edge |
| 37 | `iv2_pdh_pdl_1h` | breakout / 1h | 2,551 | +0.68 | 0.30 | -8.72 | -2,220,598 | -72,141 | never | 47,715 (15) | DISABLE — fees alone exceed edge |
| 38 | `iv2_keltner_15m` | breakout / 15m | 4,333 | +0.59 | 0.54 | -8.54 | -3,696,078 | -541,320 | never | 66,425 (57) | DISABLE — fees alone exceed edge |
| 39 | `iv2_rsi2_1h` | reversion / 1h | 2,711 | +0.26 | 0.18 | -8.74 | -2,366,139 | -633,970 | never | -68,125 (28) | DISABLE — fees alone exceed edge |
| 40 | `iv2_stoch_range_45m` | reversion / 45m | 869 | -0.11 | -0.05 | -9.01 | -782,140 | -280,270 | never | -25,479 (14) | DISABLE — no edge even before costs |
| 41 | `iv2_adx_dmi_1h` | trend / 1h | 2,499 | -0.61 | -0.36 | -10.10 | -2,519,881 | -495,362 | never | 17,442 (26) | DISABLE — no edge even before costs |
| 42 | `iv2_ema_pullback_1h` | trend / 1h | 2,758 | -1.51 | -0.94 | -10.91 | -3,005,037 | -535,701 | never | 56,078 (35) | DISABLE — no edge even before costs |
| 43 | `iv2_rsi2_45m` | reversion / 45m | 2,598 | -1.52 | -1.04 | -10.34 | -2,683,022 | -766,546 | never | -123,238 (34) | DISABLE — no edge even before costs |
| 44 | `iv2_zscore_15m` | reversion / 15m | 2,596 | -1.97 | -1.70 | -10.93 | -2,833,316 | -444,241 | never | -72,899 (34) | DISABLE — no edge even before costs |
| 45 | `iv2_pdh_pdl_15m` | breakout / 15m | 3,211 | -2.15 | -1.63 | -11.27 | -3,613,824 | -482,719 | never | -32,769 (37) | DISABLE — no edge even before costs |
| 46 | `iv2_stoch_range_15m` | reversion / 15m | 2,705 | -2.16 | -2.80 | -10.73 | -2,899,281 | -718,763 | never | -118,350 (45) | DISABLE — no edge even before costs |
| 47 | `iv2_gap_fade` | gap / day | 421 | -2.19 | -0.41 | -10.61 | -446,311 | -124,433 | never | — | DISABLE — no edge even before costs |
| 48 | `iv2_zscore_1h` | reversion / 1h | 1,165 | -2.81 | -1.20 | -12.17 | -1,416,409 | -291,089 | never | -35,554 (10) | DISABLE — no edge even before costs |
| 49 | `iv2_rsi2_15m` | reversion / 15m | 3,503 | -2.98 | -3.73 | -11.50 | -4,022,152 | -509,043 | never | -75,872 (58) | DISABLE — no edge even before costs |
| 50 | `iv2_vwap_reversion_15m` | reversion / 15m | 2,984 | -4.30 | -4.38 | -13.56 | -4,041,226 | -452,170 | never | -65,816 (43) | DISABLE — no edge even before costs |
| 51 | `iv2_vwap_reversion_45m` | reversion / 45m | 729 | -4.35 | -1.79 | -13.78 | -1,003,072 | -330,039 | never | -29,805 (6) | DISABLE — no edge even before costs |
| 52 | `iv2_orb_inplay_25` | orb / day | 2,326 | -6.34 | -2.87 | -15.88 | -3,689,935 | -933,627 | never | 36,325 (9) | DISABLE — no edge even before costs |
| 53 | `iv2_vwap_reversion_1h` | reversion / 1h | 273 | -7.30 | -1.97 | -16.81 | -458,245 | -189,571 | never | -25,213 (5) | DISABLE — no edge even before costs |
| 54 | `iv2_orb_inplay_10` | orb / day | 1,694 | -14.30 | -15.16 | -23.84 | -4,033,494 | -9,320 | never | -23,705 (23) | DISABLE — no edge even before costs |

DECISION COUNTS: {'DISABLE': 42, 'OPTIMIZE': 3, 'RESEARCH ONLY': 7, 'INCUBATE': 2}


PATTERNS DESK, corrected (targets AT the target; stops as booked; 3 bp/side)

| timeframe | trades | reported net ₹ | corrected net ₹ |
|---|---:|---:|---:|
| 1m | 1,442 | 1,515,145 | -977,588 |
| 45m | 310 | -267,295 | -689,377 |
| 1d | 58 | -315,388 | -502,105 |
| 1h | 261 | -188,336 | -463,858 |
| 5m | 927 | 1,673,442 | -388,383 |
| 15m | 490 | 1,044,413 | -175,458 |
| 4h | 51 | 364,874 | 133,495 |
| 30m | 374 | 1,469,913 | 750,675 |
| **total** | 3,913 | 5,296,768 | -2,312,599 |

| family | trades | reported net ₹ | corrected net ₹ |
|---|---:|---:|---:|
| mean_reversion | 650 | -86,908 | -1,102,707 |
| pattern | 794 | 546,888 | -1,065,983 |
| momentum | 531 | 466,843 | -292,087 |
| vcp | 68 | -97,377 | -282,883 |
| breakout | 754 | 2,087,139 | 27,471 |
| trend | 940 | 1,679,442 | 65,210 |
| chart_pattern | 176 | 700,741 | 338,378 |
| **total** | 3,913 | 5,296,768 | -2,312,599 |
