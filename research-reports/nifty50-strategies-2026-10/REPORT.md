# NIFTY 50 intraday momentum from the first 15 minutes: the result (25 Oct 2026)

## The answer first
**No strategy showed a reliable edge after costs.** Every rule was frozen before the final test, and the
final test was run once. Nothing was re-tuned afterwards.

**What was tested:** the brief's process, on 5-minute candles for the stocks in the NIFTY 50 on each date:
- **Data:** Oct 2021 – Oct 2026, 59 stocks, 1,248 sessions.
- **The screen:** at 09:30, rank the members by how far they moved in the first 15 minutes, measured in
  ATRs. Take the 5 strongest risers (longs) and the 5 strongest fallers (shorts).
- **Filters:** 8 confirmation filters. A filter was kept only if it improved both the development and the
  validation results.
- **Setups:** opening-range breakout (S1), momentum continuation (S2) and pullback to VWAP (S3), each run
  long, short and both. That makes 9 configurations.
- **Trading rules:** everything squared off by 15:10. Angel One's intraday charges and slippage were paid
  on every trade. Each trade risked ₹5,000 of a ₹10 lakh account.

**The final test:** 1 Jan 2025 – 23 Oct 2026, 448 sessions, untouched until today.
- **8 of the 9 configurations lost money:** from −₹38,267 (−3.8%) to −₹2,65,302 (−26.5%).
- **The best, S3 short, finished flat:** +₹2,356 (+0.2%) from 334 trades, profit factor 1.00.
- **The plain opening-range breakout (B1) lost ₹14.98 lakh.** It traded every member, both sides, and the
  loss is 150% of the account in 22 months. It also lost ₹11.5 lakh in development and ₹6.4 lakh in
  validation.
- **0 of 9 passed the pre-registered bar.** None was profitable in each of 2022, 2023 and 2024, so none
  could have passed whatever 2025–26 showed.

**Why:** a strong first 15 minutes hardly predicts the rest of the day.
- **Continuation is tiny.** Bought at 09:30 and sold at 15:10, the 5 strongest risers moved between
  −1.3 and +0.6 bp on average. The 5 strongest fallers fell between 0.4 and 7.8 bp further.
- **Costs are larger.** A round trip costs about 15 bp: 5.5 bp of charges plus 9.8 bp of slippage.
- **Before costs, most configurations earned a little:** mostly +0.01R to +0.26R per trade. Costs took
  almost all of it.
- **Day type decided the outcome.** The strategies made money on trend days (NIFTY up or down more than 1%)
  and lost it on range days. At 09:30 there is no telling which kind of day it will be.

**2% a week:** no configuration came close.
- The best average week was +0.00%.
- The best configurations reached 2% in only 4 of 95 weeks.

**Paper trading:** not recommended. Nothing passed.

**One lead.** This is a post-hoc observation, not a result.
- **The setup:** S3 short shorts a weak opener after it pulls back to VWAP and breaks down again.
- **Before costs** it earned +0.26R, +0.18R and +0.19R per trade in the three periods.
- **After costs** it keeps that only if real slippage is below about 4 bp a side. The model charged about
  5 bp.
- Even if it is real, it would make a few percent a year, not 2% a week (§5).

## 1. What was tested (`PREREG_A1.md`, frozen before any result)
| | |
|---|---|
| Stocks | NIFTY 50 members on each date, rebuilt from NSE's index changes (`phase0/membership.json`). HDFC Ltd (merged 2023) and LTIM have no Angel history, so 49 members are tradable in those spans |
| Candles | Angel One 5-minute OHLCV, 1 Oct 2021 – 23 Oct 2026 (`phase0/DATA_REPORT.md`). Three corporate-action errors in Angel's history were fixed; NSE's closing auction from 3 Aug 2026 is after the 15:10 square-off |
| Periods | development 1 Oct 2021 – 31 Dec 2023; validation 2024; **final test 1 Jan 2025 – 23 Oct 2026, run once** |
| Screen at 09:30 | or_move = (09:25 close − 09:15 open) ÷ ATR14. Longs: or_move ≥ +0.25; shorts: ≤ −0.25. After the filters, the 5 strongest each side |
| Filters (longs; shorts mirror) | F1 relative volume of the first 15 minutes ≥ 1.5 · F2 above the 15-minute VWAP · F3 beats NIFTY · F4 beats its sector index · F5 the 09:25 close in the top quarter of the range · F6 NIFTY up · F7 gapped up · F8 above the previous day's high |
| S1 breakout | stop order at the 15-minute high, 09:30–11:30; stop at the 15-minute low; target 2R |
| S2 continuation | enter at the 09:30 open; stop at the 15-minute low; exit at the next open after a 5-minute close below the session VWAP |
| S3 pullback | after 09:30, a candle touches the session VWAP, then a later candle closes above that candle's high (by 13:30); enter at the next open; stop at the lowest low in between; target 2R |
| Exits | all at the 15:10 candle's open at the latest; stop counts first when a candle reaches both; a stop gapped through fills at the open |
| Sizing | ₹5,000 risk; at most ₹10 lakh a trade and 1% of the stock's average 5-minute turnover; at most 5 positions and 5 entries a day |
| Costs | Angel One INTRADAY charges from the app's own `angel_fees.py`, plus slippage on each side of the Corwin–Schultz half-spread (2–7 bp, per stock and year) + 2 bp |
| Baselines | B1 plain two-sided ORB on every member; B2 the same stock-days with a random entry time and **random direction** (200 draws); B3 the same with the **screen's direction** |
| A reliable edge needed all of | final net > 0, and at 2× costs; beats B2 with t ≥ 2.5; deflated Sharpe ≥ 0.95; net > 0 in 2022, 2023 and 2024; no stock above 20% of the profit; every robustness variant net > 0 |

## 2. Development and validation: choosing the filters
The unfiltered screen lost in every setup and on both sides, in both periods:

| Base screen, mean net R per trade | S1 long | S1 short | S2 long | S2 short | S3 long | S3 short |
|---|---|---|---|---|---|---|
| development | −0.080 | −0.068 | −0.113 | −0.094 | −0.226 | −0.130 |
| validation | −0.103 | −0.091 | −0.111 | −0.089 | −0.281 | −0.181 |

The filters cut the losses but did not turn them into profits. 135 configurations were tried; these were
frozen (commit `635fc37`, before any 2025–26 candle was read):

| Configuration | Filters kept | Dev trades | Dev net ₹ | Dev mean R | Val trades | Val net ₹ | Val mean R | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 long | F1+F6 | 468 | −1,17,005 | −0.051 | 209 | +45,344 | +0.044 | +5k | −71k | +45k |
| S1 short | F1+F5 | 585 | +72,956 | +0.018 | 302 | −86,645 | −0.053 | +86k | −15k | −87k |
| S1 both | F1+F6 / F1+F5 | 1,024 | −49,404 | −0.013 | 488 | −53,610 | −0.021 | +85k | −82k | −54k |
| S2 long | F1+F6+F5 | 532 | −1,83,375 | −0.077 | 226 | +24,391 | +0.020 | −81k | −79k | +24k |
| S2 short | F7+F5+F1 | 296 | −74,582 | −0.054 | 153 | −4,920 | +0.005 | −27k | −44k | −5k |
| S2 both | both sets | 811 | −2,51,931 | −0.072 | 368 | +15,228 | +0.009 | −109k | −117k | +15k |
| S3 long | F6+F1+F4 | 332 | −1,21,331 | −0.161 | 157 | −59,767 | −0.141 | −50k | −59k | −60k |
| S3 short | F1+F5 | 383 | +1,32,229 | +0.040 | 190 | +675 | −0.023 | +152k | −19k | +1k |
| S3 both | both sets | 709 | +23,263 | −0.050 | 342 | −64,938 | −0.089 | +117k | −80k | −65k |
| B1 plain ORB | — | 2,670 | −11,49,509 | −0.125 | 1,230 | −6,36,351 | −0.125 | | | |

- **Relative volume (F1) was kept in all six,** the one consistent finding. A high-volume open is a better
  candidate than a quiet one, but "better" here means losing less.
- **Every configuration had at least one losing year in 2022–2024,** so the gate was already failed
  before the final test.

## 3. The final test (1 Jan 2025 – 23 Oct 2026, run once)
| Configuration | Trades | Net ₹ | % of ₹10 L | Mean net R | Win rate | Profit factor | Max drawdown | Sharpe (yr) | vs B2: t |
|---|---|---|---|---|---|---|---|---|---|
| S1 long | 447 | −1,40,786 | −14.1% | −0.077 | 45% | 0.76 | −14.9% | −1.49 | +0.17 |
| S1 short | 508 | −41,108 | −4.1% | −0.020 | 49% | 0.94 | −12.8% | −0.34 | +1.46 |
| S1 both | 929 | −1,66,912 | −16.7% | −0.045 | 47% | 0.86 | −20.9% | −1.17 | +1.30 |
| S2 long | 501 | −1,19,090 | −11.9% | −0.064 | 29% | 0.77 | −15.1% | −1.57 | +0.78 |
| S2 short | 297 | −38,267 | −3.8% | −0.040 | 29% | 0.86 | −9.9% | −0.58 | +1.17 |
| S2 both | 769 | −1,69,787 | −17.0% | −0.059 | 29% | 0.78 | −21.5% | −1.68 | +1.00 |
| S3 long | 337 | −2,65,302 | −26.5% | −0.270 | 35% | 0.61 | −26.7% | −2.44 | −0.66 |
| **S3 short** | 334 | **+2,356** | +0.2% | +0.004 | 44% | 1.00 | −15.9% | +0.02 | **+3.37** |
| S3 both | 662 | −2,48,274 | −24.8% | −0.131 | 40% | 0.79 | −32.6% | −1.66 | +2.06 |
| B1 plain two-sided ORB | 2,240 | −14,97,825 | −149.8% | −0.171 | 40% | 0.66 | −158.5% | −5.12 | |

**The gate, for the closest result (S3 short):**

| Test | Result | |
|---|---|---|
| Final net > 0 | +₹2,356 | ✓ (barely) |
| Final net > 0 at 2× costs | −₹2,35,171 | ✗ |
| Beats random entries (B2) with t ≥ 2.5 | t = 3.37 | ✓, but only because random entries lose 0.22R to costs |
| Deflated Sharpe ≥ 0.95 | 0.00 | ✗ (milder versions: 0.02; probability the Sharpe is above zero: 0.51) |
| Net > 0 in 2022, 2023 and 2024 | 2023: −₹19,247 | ✗ |
| No stock above 20% of the profit | one stock made ₹17,343, seven times the total | ✗ |
| Every robustness variant net > 0 | 10 of 12 negative | ✗ |

**Membership sensitivity.** The BSE-for-WIPRO index swap was also run with 30 Sep 2026 as its date,
instead of 31 Mar. The results barely changed and no sign flipped: S3 short was identical, and the rest
moved by ₹4,000–13,000.

## 4. Why nothing works
**Before and after costs: mean R per trade.** These are post-hoc diagnostics, outside the gate. "Zero
costs" means no charges and no slippage.

| Configuration | Zero costs: dev | val | final | Charges (bp) | Slippage (bp) | Stop distance (bp) | Costs in R |
|---|---|---|---|---|---|---|---|
| S1 long | +0.039 | +0.127 | +0.009 | 5.6 | 9.8 | 207 | 0.07 |
| S1 short | +0.115 | +0.038 | +0.064 | 5.7 | 9.8 | 219 | 0.07 |
| S1 both | +0.080 | +0.066 | +0.040 | 5.7 | 9.8 | 212 | 0.07 |
| S2 long | +0.025 | +0.120 | +0.033 | 5.5 | 9.8 | 188 | 0.08 |
| S2 short | +0.041 | +0.104 | +0.051 | 5.7 | 9.8 | 210 | 0.07 |
| S2 both | +0.026 | +0.107 | +0.035 | 5.5 | 9.8 | 197 | 0.08 |
| S3 long | +0.050 | +0.052 | −0.040 | 4.8 | 9.8 | 87 | 0.17 |
| **S3 short** | **+0.264** | **+0.178** | **+0.194** | 4.8 | 9.8 | 80 | 0.18 |
| S3 both | +0.168 | +0.109 | +0.079 | 4.8 | 9.8 | 83 | 0.17 |

- **There is a small signal before costs,** positive in most cells. It is smaller than the cost of trading
  it.
- **The cost problem differs by setup:**
  - **S1 and S2** use wide stops (about 2% of the price), so costs are only about 0.07R a trade. But
    their gross edge is only about +0.01R to +0.06R in the final test.
  - **S3** has a bigger gross edge, but its stop is tight (about 0.8%), so the same 15 bp is about 0.18R.
- **Continuation itself is close to zero.** This measures the 5 strongest movers held from the 09:30
  open to the 15:10 open, with no stop and no target, before costs:

  | | Development | Validation | Final |
  |---|---|---|---|
  | Risers, bought (base screen) | −1.3 bp | +0.6 bp | −0.8 bp |
  | Fallers, sold (base screen) | +6.3 bp | +7.8 bp | +0.4 bp |
  | Risers, with S2's filters | +0.2 bp | +11.5 bp | +3.5 bp |
  | Fallers, with S2's filters | +10.6 bp | +7.2 bp | +14.8 bp (t 1.6) |

  - **Risers:** a strong first 15 minutes does not carry on upward.
  - **Fallers:** they drift a little lower, but not significantly, and by less than a round trip costs.
  - This matches the earlier Stock Selection finding: the open tells you *how much* a stock will move,
    not *which way*.
- **Trend days pay, range days cost more.** On sessions where NIFTY moved more than 1%, most
  configurations made money:
  - S1 both made +₹94k on 235 trades.
  - S1 short made +₹78k on 127 trades.

  On range days they lost more (S1 both −₹2.61 lakh on 694 trades). A trend day is only known at the close.
- **Shorts beat longs in every setup.** Stocks drift down during the session and up overnight (−7.5 bp a
  session, found earlier), so intraday longs start with a headwind.
- **Stops do the damage.** S1 both's 123 stop-outs lost ₹5.93 lakh. Its 791 square-offs (+₹2.94 lakh) and
  15 targets (+₹1.32 lakh) did not cover them. S2's VWAP trail exited 85% of its trades, at −0.23R on
  average.

## 5. The one lead: S3 short (post-hoc, not a result)
**The rule.**
- **Screen:** the 5 strongest fallers at 09:30, with relative volume ≥ 1.5 (F1) and the 09:25 close in the
  bottom quarter of the range (F5).
- **Entry:** when one bounces up to the session VWAP and then closes below that candle's low, short at the
  next open.
- **Stop:** the highest high of the bounce.
- **Exit:** a 2R target, or the 15:10 square-off.

**Why it stands out:**
- Its pre-cost edge was positive in all three periods: +0.26R, +0.18R and +0.19R.
- The filters were fixed before the final test, so the final-period figure is out of sample.
- It beat random entries on the same stock-days (B2, t = 3.37).

**Why it is not a result:**
- **It is the best of 9 configurations** tested out of sample, so some of its showing is luck of the pick.
- **The pre-registered costs leave it flat.** Under the modelled slippage of about 5 bp a side it made
  +0.004R in the final test and −0.023R in validation.
- **Break-even slippage.** It breaks even at about 8–14 bp per round trip: 13.9, 8.8 and 8.3 bp in the
  three periods (about 4–7 bp a side). With charges only and no slippage at all (an impossible best case),
  it would make +0.17R, +0.10R and +0.11R.
- **Real slippage is unknown here.** NIFTY 50 quoted spreads are usually below 1 bp a side. But a market
  order at the candle open, and stop exits in fast markets, cost more than the quoted spread. The
  Corwin–Schultz estimate from candle ranges (2–7 bp) is an estimate, not a measurement. Choosing a
  cheaper cost model now, after seeing the result, would be exactly the kind of tuning the stop rule
  forbids.
- **B3 beat it.** Random entry times in the same direction on the same stock-days did better (+0.035R).
  So S3's pullback timing adds nothing measurable beyond the short direction. B3 also carries a hindsight
  advantage here (§11).
- **It is small even if real.** Its tight stops hit the notional and turnover caps, so its average risk
  was ₹3,497, not ₹5,000. At +0.07R a trade it would have made about ₹0.8 lakh over these 22 months on
  ₹10 lakh: roughly +0.1% a week, not 2%.
- **It cannot be confirmed quickly.** Its trades vary by 1.16R (standard deviation). Confirming +0.1R a
  trade at t ≥ 2.5 needs about 850 trades; +0.07R needs about 1,700. At its pace of 0.75 trades a session,
  that is 4½ to 9 years.

**If you want to pursue it,** the honest next step is a **new, separately pre-registered forward paper
test of S3 short only**. Its first job is to measure real slippage:
- record Angel's bid and ask at each signal and each exit;
- run it for a few weeks;
- treat a measured slippage above about 4 bp a side as the end of it.

That should be decided by you; it was not started.

## 6. Robustness (final test, net in ₹ thousand)
| Variant | S1 long | S1 short | S1 both | S2 long | S2 short | S2 both | S3 long | S3 short | S3 both |
|---|---|---|---|---|---|---|---|---|---|
| **As frozen** | **−141** | **−41** | **−167** | **−119** | **−38** | **−170** | **−265** | **+2** | **−248** |
| Costs ×1.5 | −226 | −136 | −343 | −226 | −98 | −328 | −371 | −91 | −445 |
| Costs ×2 | −315 | −230 | −521 | −330 | −155 | −483 | −492 | −235 | −707 |
| Slippage +5 bp | −256 | −165 | −400 | −260 | −116 | −378 | −425 | −165 | −572 |
| Top 3 instead of 5 | −112 | −52 | −164 | −110 | −48 | −163 | −203 | −14 | −213 |
| Top 10 | −113 | −43 | −130 | −119 | −38 | −170 | −222 | −1 | −202 |
| Threshold 0.15 ATR | −163 | −14 | −177 | −163 | −49 | −217 | −290 | +28 | −240 |
| Threshold 0.35 ATR | −143 | +14 | −123 | −115 | −36 | −167 | −262 | +16 | −231 |
| 30-minute range | −31 | −118 | −146 | −135 | −50 | −176 | −185 | −32 | −211 |
| Stop at the range midpoint | −196 | −97 | −278 | −195 | −11 | −239 | n/a | n/a | n/a |
| Target 1.5R | −148 | −49 | −183 | n/a | n/a | n/a | −226 | −30 | −242 |
| Target 3R | −136 | −35 | −156 | n/a | n/a | n/a | −284 | −9 | −279 |
| Without the best stock | −168 | −61 | −195 | −140 | −49 | −188 | −293 | −15 | −275 |
| Without the best year | −79 | −87 | −138 | −94 | −49 | −154 | −144 | −68 | −186 |

105 of the 108 variant cells are negative. The three positive ones are all small: S1 short at threshold
0.35, and S3 short at thresholds 0.15 and 0.35. ("n/a": S2 has no target, and S3's stop is not the range.)

## 7. Breakdowns (final test, net in ₹ thousand, trades in brackets)
| | S1 long | S1 short | S1 both | S2 long | S2 short | S2 both | S3 long | S3 short | S3 both |
|---|---|---|---|---|---|---|---|---|---|
| 2025 | −61 (238) | −87 (265) | −138 (488) | −94 (272) | −49 (140) | −154 (398) | −121 (186) | −68 (171) | −186 (356) |
| 2026 to 23 Oct | −79 (209) | +45 (243) | −28 (441) | −25 (229) | +11 (157) | −16 (371) | −144 (151) | +71 (163) | −62 (306) |
| Trend day (\|NIFTY\| > 1%) | −0 (117) | +78 (127) | +94 (235) | −5 (132) | +40 (75) | +45 (203) | −29 (92) | +40 (71) | +22 (158) |
| Range day | −141 (330) | −119 (381) | −261 (694) | −114 (369) | −78 (222) | −215 (566) | −237 (245) | −37 (263) | −270 (504) |
| VIX above its 60-day median | −93 (194) | −36 (241) | −122 (420) | −68 (215) | −7 (148) | −81 (351) | −98 (143) | +44 (156) | −41 (294) |
| VIX at or below it | −47 (253) | −5 (267) | −45 (509) | −51 (286) | −31 (149) | −89 (418) | −167 (194) | −41 (178) | −207 (368) |
| Gap against the trade, over 1% | +9 (70) | +14 (93) | +29 (154) | −7 (77) | – | −3 (72) | −42 (50) | −5 (58) | −41 (105) |
| Gap against, up to 1% | −59 (103) | −71 (185) | −135 (285) | −55 (117) | – | −68 (114) | −38 (78) | −25 (126) | −58 (201) |
| Gap with the trade, up to 1% | −91 (211) | −0 (154) | −83 (357) | −69 (231) | −37 (200) | −111 (416) | −158 (160) | +21 (104) | −137 (263) |
| Gap with, over 1% | −1 (63) | +16 (76) | +22 (133) | +12 (76) | −1 (97) | +12 (167) | −28 (49) | +11 (46) | −12 (93) |

- **No year was good for the longs.**
- **Shorts did better in 2026 than in 2025**, which is the market's direction, not a skill.
- **No VIX regime or gap bucket rescues anything**; the small positive cells are scattered and thin.
- Per-stock and per-sector tables are in `results/final_A1.json`.

## 8. Weekly returns (final test, % of ₹10 lakh)
| Configuration | Weeks | Mean week | Weeks with a profit | Worst week | Best week | Weeks ≥ 2% |
|---|---|---|---|---|---|---|
| S1 long | 95 | −0.15% | 39% | −2.00% | +1.47% | 0 |
| S1 short | 95 | −0.04% | 44% | −3.30% | +2.49% | 1 |
| S1 both | 95 | −0.18% | 42% | −2.95% | +2.88% | 4 |
| S2 long | 95 | −0.12% | 32% | −1.56% | +1.30% | 0 |
| S2 short | 95 | −0.04% | 28% | −1.07% | +1.93% | 0 |
| S2 both | 95 | −0.18% | 33% | −1.99% | +1.84% | 0 |
| S3 long | 95 | −0.28% | 27% | −2.62% | +2.57% | 1 |
| S3 short | 95 | +0.00% | 42% | −2.07% | +2.42% | 4 |
| S3 both | 95 | −0.26% | 35% | −3.19% | +4.61% | 2 |

## 9. The exact rules that were tested (frozen in `FROZEN_A1.json`)
Every configuration uses the screen, setups, exits, sizing and costs of §1. They differ only in their
filters:

| Configuration | Long filters | Short filters |
|---|---|---|
| S1 long / short / both | F1 relative volume ≥ 1.5; F6 NIFTY's first 15 minutes up | F1; F5 the 09:25 close in the bottom quarter of the 15-minute range |
| S2 long / short / both | F1; F6; F5 the 09:25 close in the top quarter | F7 gapped down; F5; F1 |
| S3 long / short / both | F6; F1; F4 the stock beats its sector index | F1; F5 |

"Both" runs the long and short filter sets together, under one book: at most 5 entries a day, ranked by
the size of the first-15-minute move.

## 10. How to reproduce
| Step | Command | Output |
|---|---|---|
| Data | `phase0/n50_fetch.py`, `n50_checks.py`, `n50_adjust.py` (see `phase0/DATA_REPORT.md`) | `n50_clean.pkl`, sha256 `ada44df0…` (not committed: licensed market data) |
| Tests | `python test_n50.py`, then `N50_DATA=<dir> python test_n50.py` | 20 checks: rules, fees equal to `angel_fees.round_trip`, no look-ahead |
| Independent check | `python reference_n50.py <dir>` | 707 sampled trades rebuilt with plain loops from the raw candles: 0 mismatches |
| Phase 1 | `python n50_ablation.py <dir> results` | `results/ablation_A1.json`; `FROZEN_A1.json` (sha256 `c84ab988…`, commit `635fc37`) |
| Final test | `python n50_final.py <dir> results` (script committed in `84124e4` before it ran) | `results/final_A1.json` |
| Diagnostics | `python n50_diagnostics.py <dir> results` | `results/diagnostics_A1.json` (post-hoc) |

The engine is `n50_engine.py`. Everything after the data step runs in a few minutes on a laptop.

## 11. Disclosures
- **Rules the pre-registration left open,** resolved before any result (listed in `n50_engine.py`):
  - S1's stop order is live on the candles 09:30 through 11:25.
  - S3 uses the first VWAP touch after 09:30, and its signal candle must close by 13:30.
  - Filters act before the top-5 cut.
  - "Costs ×1.5/×2" scale both the charges and the slippage.
  - R is net P&L over the risk actually carried.
  - Greedy selection adds, among the filters that improve both periods with at least 100 trades each, the
    one with the largest validation gain.
- **The B2 statistic** is the smaller of two: the z-score against the 200 draws, and a t that adds the
  strategy's own day-clustered error.
- **B3 has a hindsight advantage for S1 and S3.** It reuses those trades' stock-days, which were selected
  by a breakout or breakdown that happened later in the day. A random entry before that move, in the same
  direction, benefits from knowing it came. So B3 beating S1/S3 partly reflects this, and B3 is a fair
  test only for S2.
- **The deflated Sharpe.** The pre-registered version uses the spread of all 135 tried configurations'
  Sharpes, and it is 0.00 for every configuration. Many unfiltered screens lost heavily, which pushes the
  luck benchmark to an annual Sharpe of about 4. Two milder versions were also computed, outside the gate:
  - a noise-only spread: at most 0.02;
  - the plain probability that the Sharpe is above zero: at most 0.51 (S3 short).

  Neither changes the verdict.
- **The slippage model is probably on the high side** for NIFTY 50 stocks. §5 shows where that matters
  (S3 short only). It was not changed after the result.
- **The final-test script was rehearsed** with 2024 standing in for the final period, so the real run
  could not fail halfway through. The rehearsal read no 2025–26 candle.
- **Some members are missing.** HDFC Ltd and LTIM have no Angel history, so 49 members are tradable in
  those spans. The BSE-for-WIPRO swap date was not confirmed, so both dates were run (§3).
- **Not touched:** the incubating paper strategies `iv2_orb_sel15` / `iv2_orb_sel30`. No app code,
  database or live desk was changed by this study.
