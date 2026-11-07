# Booming Bulls strategy library (Phase 3)

This file merges the 96 P1 videos into one library, with duplicates removed. Each entry points to its analysis in `../analyses/`, which holds every rule with its timestamp and an E/I tag.

**Rule tags:**
- **E** = the video states or demonstrates the rule.
- **I** = inferred from the video's reasoning.
- **A** = a research assumption I added to make the rule measurable.

The exact, measurable version of every tested strategy is in [PREREGISTRATION.md](PREREGISTRATION.md). That file was hash-locked before the first run.

**Nothing below is attributed to Booming Bulls unless it is tagged E.**

## Status

**18 strategies are tested.**
- **4 ready to test.** The core rules are explicit; the A-tagged items are thresholds such as a buffer or a cut-off time: BB-02, BB-10, BB-11, BB-13.
- **7 testable with documented assumptions.** One or more central definitions are A: BB-01, BB-07, BB-08, BB-09, BB-12, BB-14, BB-15.
- **7 testable only with research assumptions.** The video gives a concept, and the definitions are mine, so these are low fidelity: BB-03, BB-04, BB-05, BB-06, BB-16, BB-17, BB-18.

**2 are already tested elsewhere** (D9, VWAP) and **16 groups are not testable**.

| ID | Strategy | Source videos | Market (as taught) | Executed on | Status |
|---|---|---|---|---|---|
| BB-01 | Previous-day high/low: breakout, trap, gap fill, retest | gNoByC3ZEOo | Nifty 5m, buying options | NIFTY futures (index-price proxy) | Testable with documented assumptions |
| BB-02 | 15-minute opening-range breakout, 5-minute close | yKtI-VEMwC0, 4iPEKSo_vwY | Nifty and NSE stocks, 5m | NIFTY futures | Ready to test |
| BB-03 | Nifty + BankNifty synchronised level break | 0MasZZQiL5s | Nifty/BankNifty options, 5m | NIFTY futures | Research assumptions |
| BB-04 | Zone bull/bear trap with RSI divergence | SxQwiHBfHUs (+ v5AUeTSUiiM mirror) | Nifty 15m, buying puts | NIFTY futures | Research assumptions |
| BB-05 | SMC: break of structure / change of character into an order block | hXtpVnpjuXg | BankNifty 5m | BANKNIFTY futures | Research assumptions |
| BB-06 | Gap day + first candle breaks the 15m 200 MA | zm9emzopBi0 | Nifty 15m | NIFTY futures | Research assumptions (exit undefined) |
| BB-07 | Liquidity sweep of previous-day high/low (masterclass) | IOBoaM71MUA (+ CHD5Rx8Sj8I, XOAPW8nUYSk, jvzd7UPlb5Y, 3QXl4h4Xb40 examples) | Gold 5m; Nifty, Nasdaq | XAUUSD CFD; NAS100 CFD | Testable with documented assumptions |
| BB-08 | Previous-day high/low "manipulation" trap after 10:00 IST | HxBwAconvqA, 7LLm0HSarPc, TIQeTWWc1-8, ZEqfiVSbDG0 | Gold, forex 5m | XAUUSD, EURUSD, GBPUSD CFD | Testable with documented assumptions |
| BB-09 | Value-area (volume profile) trap | zYGUL82NsS4, rFrFhpwJJOc (setup B), eT4kr2HDXoE, 99fQ_As8Wuo | Gold 5m | XAUUSD CFD | Testable with documented assumptions (volume proxy) |
| BB-10 | Gold 11:30–12:30 IST range sweep | 1hZMOSd34vQ | Gold 5m | XAUUSD CFD | Ready to test |
| BB-11 | Forex 10:00 IST range trap | uUa61jN45vM | EURUSD 15m | EURUSD (+ GBPUSD, XAUUSD checks) | Ready to test |
| BB-12 | 400 EMA trap | DI3ydbq9b6M | Crude, US30, BTC, gold 15m | XAUUSD, US30 CFD | Testable with documented assumptions |
| BB-13 | "Prop-firm" inside-body breakout, 1:1 | Lb4yel3nCws, NwCyONUCsC0, t_ziTZLkiXA | Nasdaq 100, gold 5m | NAS100, XAUUSD CFD | Ready to test |
| BB-14 | Inside candle with the 10-point poke filter | kakFchv-ylo, XDCW2kXVbc8, QTDX-f7_phI | US30 (timeframe unstated) | US30 CFD (5m and 15m) | Testable with documented assumptions |
| BB-15 | Apple opening-range trap | T_VlPXyqj0U | Apple CFD 3m | AAPL CFD | Testable with documented assumptions |
| BB-16 | Retracement-zone (Fibonacci 50–61.8%) sweep | rFrFhpwJJOc (setup A), 3gj7MbZ0vHs, 37uPX6Li-xE (OTE variant), T9w_j3qyb14 | Gold 1h + 5m | XAUUSD CFD | Research assumptions |
| BB-17 | Order-block 50% trap | RTbVZfriRrw (+ N8SsGMpUgYk confluence ideas) | Gold, forex 15m + 5m | XAUUSD, EURUSD CFD | Research assumptions |
| BB-18 | 15m 200 EMA breakout-retest | Hj56fabq2c8 | Forex 15m | EURUSD, GBPUSD CFD | Research assumptions (currency-strength filter omitted) |

## Already tested elsewhere (not re-run)

| Strategy | Source | Earlier test | Result |
|---|---|---|---|
| D9 Nifty liquidity sweep (and 22 one-change versions) | iTWMIaqYLJg (+ its PDF) | `backend/research/liquidity_sweep_2026_11` (6 Nov 2026) | 0 of 27 versions pass; no pre-cost edge (best t 2.32) |
| VWAP breakout-retest and sweep-to-VWAP | T04vDiuAG4w | `D:\NSE-Intraday-Research\vwap` (6 Nov 2026): built from a summary of this video, run on **NSE stocks** | No workable version. **A Nifty test is blocked:** VWAP needs Nifty futures volume, and no historical intraday futures volume is on disk |

## Not tested: why

| Group | Videos | Reason |
|---|---|---|
| Option-buying payoffs (strike choice, premium P&L) for BB-01 to BB-06 | gNoByC3ZEOo (strike table on screen only, 05:15), yKtI-VEMwC0, 0MasZZQiL5s, SxQwiHBfHUs | **Unable to evaluate:** no intraday option prices on disk. The index signals are traded on futures instead; option results cannot be inferred from index moves |
| Option selling, straddles, hedges, budget/election days | bNdyeSxKVfE, XniIt3tDSI0, 3dJcozAX2ug, pDuMtj60Efc, TrnwDFPfk0c, xJi3L2TFw-c, YBUrHpGUst0, c2pBpSdxQZ0, vRc6v4764fQ, aHusxL16OGI, hxzRM3Fb41I | **Unable to evaluate:** no intraday option prices |
| Budget-day futures breakout | hGYfGHEtkJc, B9DW6O8VvlQ | **Too few samples:** about 10 budget days since 2016 |
| Quarterly-results swing | VSsvcYq5eUw (bZYuWfbR5M4 superseded) | **Blocked:** needs historical result dates and a survivorship-free stock universe; the app's NSE-events store was not exported for research |
| Banking-stock 10:00 range | 2WkkkZ5N08c | **Blocked:** needs intraday bank-stock data and a "leader" rule |
| ATR bias + FVG, daily bias | xWl9BZ1_uHc, 5glwOHR6nEA, u3g1Zk7GiL0 | **Insufficiently defined:** the bias rules would be mine. The ATR gate is tested as BB-07 variant S1 |
| ICT concept course | 37uPX6Li-xE | Concepts covered by BB-07, BB-16 and BB-17; its OTE zone is BB-16 variant S1 |
| Sniper / POI / headshot entries, alerts, "obvious" trap | jvzd7UPlb5Y, 8Huu4P25ZEA, 3QXl4h4Xb40, dJ4QitUYo90, Ezlqgr74DC0, WRIWzdPA-x4 | **Insufficiently defined** (levels drawn by eye); their mechanics are the BB-07/08 sweep |
| Triangles, flags, demand/supply, AOI, rejection/power candles, mean reversion, Bollinger, pyramiding | a2mPpV6qK_4, _kRoHbfzK3I, OoilOgjzUdQ, n3aumdwdJmo, fBbwDhtER9c, mlrWUBI_Bp8, xmRyk4y2j2c, Sa8q2sY8174, qd6hCjK0y_4, r3cbKsUItwM, dMQJgSv_NPI, wvPzUW4Hvgw, vp-3Morug0Y, M5NISnxBzeU | **Insufficiently defined:** patterns drawn by eye or no exit. Pyramiding is a management overlay, not a strategy |
| Supertrend/ADX, RSI, EMA, VWAP+pivots, 2020–2022 systems | 1TFcGjMwh4s, jc3DySIdok4, 3GqxRTiOLY0, wqyBXMct7EI, ID48Wsb30Ns, 8OurAiVyhE4 and the other 2020 indicator videos | **Unable to extract:** garbled 2020–2022 auto-captions; frames and Whisper not used |
| Forex price-action, POC, news, crypto breakouts | a-VAXIg4gZc, T3AyXqau_QA, gk7sfzWgkaI, YIgNsAwNCC8, PFEJFWxoODU, QH3KAJGumos, Gv2irT8javk, vldS7qhIYE8, VeRFSaOj6S4 | **Insufficiently defined** (discretionary); YIgNsAwNCC8 is close to BB-09 but needs a 2-day POC with volume, so it gets low priority |
| Swing stock picks, case studies, live streams | t5ItITJlaPQ, 68_65YqI_BQ, 84N6qYTxgHs, zrEeFLw322M, P3 streams | **Discretionary** worked examples (see batch_p3-applied-examples.md) |
| Earlier code D1–D8 (`booming_bulls.py`) | coded from titles only | **Not a source:** D1 does not match yKtI-VEMwC0, D2 does not match rFrFhpwJJOc, and D3 lacks RTbVZfriRrw's 50% trap |

## Duplicates found

| Duplicate | Original | Kind |
|---|---|---|
| T9w_j3qyb14 (Day 41 Short) | rFrFhpwJJOc 08:30–10:00 | Word for word |
| XDCW2kXVbc8, QTDX-f7_phI (Day 36/37 Shorts) | kakFchv-ylo | Cut from the video |
| 8Huu4P25ZEA | jvzd7UPlb5Y | English-language version |
| UUbubd80xco (2024), rqgWWqDmsfI (2022) | 3gj7MbZ0vHs (2026) | Earlier versions of the Fibonacci class |
| 4iPEKSo_vwY (2020) | yKtI-VEMwC0 (2026) | The same 15m ORB, 6 years apart |
| 7LLm0HSarPc (2024) | uUa61jN45vM (2025) | Two different forex trap rule sets; both kept (BB-08, BB-11) |
| zYGUL82NsS4, rFrFhpwJJOc B, eT4kr2HDXoE | — | One value-area trap; merged as BB-09 |
