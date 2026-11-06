# Liquidity Sweep (Booming Bulls): backtest report, 6 Nov 2026

**Verdict: no edge.** The video's rules make nothing even before costs. Over the PDF's own 13 months (24 Sep 2025 – 19 Oct 2026) they take 407 trades at −0.025R a trade (t −0.37). Since 2016 they take 3,730 trades at 0.000R a trade. After NIFTY-futures costs they lose about 0.4–0.6R a trade in every period and every variant.

The PDF's 42 examples are real and did win as drawn: 32 hit their target on the minute data. They are a hand-picked 42 of the 407 setups the same rules produced in that period.

- **Rules:** [PREREGISTRATION.md](PREREGISTRATION.md), SHA-256 `1300ccfcdcc652206fd9f2e9206f6a83397d4d56431cdaa239b0811592f5c386`, fixed before the first run.
- **Strategy:** `bb_liquidity_sweep` (Booming Bulls D9) in `strategy-service/strategy_service/strategies/options_buying/booming_bulls.py`.
- **Harness:** this folder; it drives that same class.
- **Checks:** `ls_verify.py`, 32 of 32 pass.

## Results

R = the trade's planned risk (entry to stop). Costs are one NIFTY futures lot (65) with Angel One's futures charges on the trade date, plus 1 point of slippage per fill. "Gross" is before all costs.

| Run | Period | Trades | Winners (net) | Gross R / trade | Net R / trade | Net t | Net ₹ / lot |
|---|---|---:|---:|---:|---:|---:|---:|
| **A** 5-min (primary) | **P** 24 Sep 25 – 19 Oct 26 (262 sessions) | 407 | 33.2% | −0.025 (t −0.37) | **−0.557** | −8.05 | −₹3,71,004 |
| A | H 2016 – 23 Sep 25 (2,374 sessions) | 3,730 | 34.3% | 0.000 (t −0.01) | −0.390 | −17.3 | −₹14,48,172 |
| B 5-min + 200-EMA side | P | 218 | 37.6% | +0.115 (t +1.24) | −0.426 | −4.45 | −₹1,39,408 |
| B | H | 2,013 | 36.1% | +0.047 (t +1.54) | −0.342 | −11.2 | −₹6,26,658 |
| C 3-min | P | 483 | 32.7% | −0.023 (t −0.37) | −0.590 | −9.24 | −₹4,06,205 |
| C | H | 4,422 | 33.1% | −0.025 (t −1.22) | −0.443 | −21.2 | −₹17,61,716 |

- **Exits in A over P:** 117 targets, 256 stops, 34 closed at 15:15. Profit factor 0.51. Maximum drawdown 5,826 points.
- **After the PDF (20–23 Oct 2026):** A took 3 trades (+₹1,418), C took 6 (−₹11,597), B took none. That is too few to read anything from.
- **The 200-EMA filter (B)** is the only variant above zero before costs. It isn't significant (t 1.24 and 1.54), and it is roughly 0.4–0.5R short of covering costs.
- **No level type works.** In A over H, every level type is at −0.33R or worse after costs. Before costs the best is +0.08R (equal highs).
- **Costs since 1 Apr 2026.** STT on futures rose to 0.05%. A round trip now costs about 16 points (₹921 in fees plus slippage), against 9.5 points before. The rules' median risk is only 26–29 points, so costs alone are about 0.6R a trade.

## The PDF's 42 trades

**Replay.** Each PDF trade was run with its own entry, stop and target on the 1-minute data.

| Outcome | Trades |
|---|---:|
| Target hit | 32 |
| Stopped out | 9 (23 Sep, 7 Oct, 20 Aug, 14 Aug, 6 Jul, 21 May, 17 Feb, 27 Jan, 24 Sep '25) |
| Still open at 15:15 | 1 |
| **Average** | **+1.41R before costs** |

41 of the 42 PDF entry prices are within 3 points of the marked candle's close, with a median gap of 0.2 points. That confirms the transcription, confirms that Angel's index minutes match TradingView's, and confirms the entry convention: the entry is the confirmation candle's close. The PDF's stops are wider than the rules' (median 43 points against 27).

**Replication.** Did the rules take the same trade?

| Match | PDF trades |
|---|---:|
| Same candle | 8 |
| Within 30 minutes | 11 |
| Same day, at a different time | 12 |
| No trade on that side that day | 11 |

The same-day misses are revealing. On 30 Sep, 1 Sep, 18 Jun, 15 May and 20 Mar the rules took an earlier sweep that day and it was stopped out; the PDF shows a later sweep that won. Picking the winning sweep afterwards is the edge the examples display, and it can't be traded in advance.

## The app's own options engine

Run A in the Options Buying Lab engine (`run_options_backtest`: Black-Scholes premiums from realised volatility, fills at candle closes, statutory charges only, **no bid-ask spread**) gives +₹17,504 on one lot over P. That is +₹43 a trade, with t +0.55: noise.

- With 0.5 premium points of spread per side it becomes −₹8,951.
- With 1 point per side it becomes −₹35,406.
- Over its full span, including 80 lead-in sessions, the Lab would display PF 1.15 and Sharpe 1.08. Don't read that as an edge.

## Caveats

- The spot index stands in for the future and for the option. Futures basis and option theta are not modelled in runs A–C.
- These are one mechanical reading of a discretionary method. The choices the video leaves open (tolerances, windows, risk band) are in PREREGISTRATION.md §1 and were not tuned. The replication table shows this reading takes about half of the presenter's trades at the same moment.
- PREREGISTRATION.md says half of the PDF's charts are 3-minute. The count is 12 of 42.
- The data runs to 23 Oct 2026. The server's daily files after that weren't copied, because the auto-mode classifier blocked reads of production.

## Reproduce

See [README.md](README.md).
