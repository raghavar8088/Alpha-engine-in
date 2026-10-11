# Gold Desk — Research, Profitability Validation & Upgrade Plan

**Date:** 2026-10-10 · **Scope:** `/gold-desk` — both books (MCX gold futures in rupees, Delta gold-token perpetuals in dollars), the 353-strategy pattern catalogue they trade, their data feeds, loops, risk controls and page · **Status:** research complete — this document changes no code.

Every figure below was measured on the production database, on the venues' public data, or by replaying the desk's own code on gold history on 2026-10-10. The scripts that produce each one are in [`backend/research/gold_2026_10/`](backend/research/gold_2026_10/README.md). Measured results, assumptions and hypotheses are labelled as such.

---

## 0. Executive summary

**Verdict: no Gold Desk strategy has a demonstrated, tradeable edge after realistic costs, on either venue.** The desk has never placed a trade — both books shipped OFF on 29 September and stayed off — so nothing has been lost. But switched on as built, each book would lose half its capital within weeks, and its record would describe its own plumbing rather than the market.

Because there is no record, the question was answered by replaying the desk's own catalogue — all 353 strategies, through its own `evaluate()`, on closed bars, filled honestly and charged measured costs — on six gold histories: Delta's own perpetuals, 21 months of a 24/7 gold token, COMEX gold in MCX hours, MCX GOLDM itself, and 26 years of daily gold. 8.8 million signals; 2,977,769 trades.

The five findings that matter:

1. **Below four hours there is no edge, even before costs.** On every history the average trade at 1m–1h moved between −1.0 and +1.9 bp gross against a measured round trip of 2.4–2.6 bp on Delta and 3.3 bp on MCX. All 24 timeframe-by-history cells are negative after costs, in every trend, session and weekday/weekend cut. **All 46 templates fail below 4h.** No execution improvement fixes this: the venue fee alone exceeds the gross edge in every cell.
2. **Above four hours, the positive numbers are gold's trend, and holding gold did better.** On 26 years of daily gold, long trades made +45 bp and short trades lost −33 bp. **39 of 40 daily templates lose to simply holding gold** on the Commodity Lab's own test. The one that wins (Bollinger Squeeze, alpha t 2.37) lost money when the Lab ran it on four other commodities. **0 strategies reach a Deflated Sharpe of 0.95 or a drift-adjusted net t of 3 on any history.**
3. **The one consistent signal is a regime, not a strategy.** At 4h the breakout / trend-structure templates earned +12 to +16 bp a trade net on all three histories that have them. But those histories are one 2024–26 market that trended hard both ways, and books trading only 4h and 1d made money with alpha against gold that is not significant (t 0.3–1.6). That is worth one pre-registered forward test (H1) and nothing more.
4. **As a system, the desk would destroy its own books.** Replayed with its own rules — one shared balance, slots handed out in scan order — **both books hit their 50% floor**: Delta within about three weeks, MCX within about 22 sessions. Over May 2024 – Oct 2026 the MCX book lost 52% while gold rose 78%. The fastest timeframes take every slot (100% of fills on 1m/5m), and they are exactly the strategies that cannot pay their fees. The book also held long and short GOLDM at the same time for 31–45% of its open hours.
5. **As built, the desk would not measure what it names, and it costs the database every day.** It evaluates the bar that is still forming (40–62% of its trades would be signals that vanish by the close, losing before costs), books exits at whatever price it polls (targets 3.4–5.4 bp past their level), guesses execution cost 8–140× too high, charges no funding, marks MCX positions on the wrong contract after a roll, and labels 3–6% of zero-edge strategies "Worth real money? READY" by luck. Switched off, its Delta poller still rewrites **~17,000 candles every 2 minutes — ~12 million writes a day** on the shared database.

**Do, in order:**
1. **Stop the write load** (C7). It is the only change with a benefit today.
2. **Decide what the desk is for.**
   - If the goal is income, **retire it**: stop its three loops and keep the code and this research. Nothing here earns its costs, and holding gold beat 39 of 40 daily templates.
   - If the goal is research, make the record honest before anything is switched on: C1–C3, C5, C8, and retire every timeframe below 4h (I1).
3. If kept, run **H1**: one pre-registered, two-year forward test of the 4h breakout / trend family on Delta XAUTUSD, with a frozen rule and its low power stated up front.

**Do not:**
- switch either book on as built;
- add templates, timeframes or venues (each one raises the bar every survivor must clear);
- read the daily long patterns' profits as skill (they lose to holding gold);
- trade the losers' mirror (a gross edge of zero mirrors to zero, and costs are paid both ways);
- re-tune anything on this history;
- build the token-basis or session-drift trades (+0.4 bp net; no better than holding).

---

## 1. Scope, evidence and limits

| Evidence | Source | Size | Used for |
|---|---|---|---|
| The desk's own record | `gold_desk_positions`, `_trades`, `_equity`, `_state` | **0 positions, 0 trades** on both venues since launch (2026-09-29); 7,127 flat equity samples | that there is no live record to judge |
| Delta, the venue itself | public `/v2/history/candles` XAUTUSD + PAXGUSD 1m since launch; `FUNDING:<sym>`; `/v2/products` | 253,655 + 335,660 one-minute bars (2026-02-19 / 04-17 → 10-10); 4,229 + 5,592 hourly funding prints | the Delta book's replay, funding, fees |
| Delta order books | `gd_l2_sampler.py` on the AWS host, every 60 s for 72 h (started 2026-10-10 22:00 IST) | weekend samples so far; weekday samples accumulating | spread and the cost of crossing with a slot |
| 24/7 gold-token history | Binance spot PAXG/USDT 1m (data.binance.vision) | 3.21 M bars 2020-08 → 2026-10; **only 2025-01 → used** (931,680 bars) | the longest usable 24/7 replay |
| COMEX gold | Yahoo GC=F hourly and daily | 13,733 hourly bars (2024-05 → 2026-10); 6,553 daily (2000 → 2026) | MCX-hours replay at 1h/4h/1d; 26-year daily replay |
| MCX gold itself | production `commodity_bars`, GOLD + GOLDM, every contract | 91,830 bars; GOLDM 1m from 2026-08-11, 15m from 07-16, 1h from 05-21, 1d from 2025-04 | the MCX book's replay; proxy fidelity |
| MCX spreads | production `mcx_quote_log` | 568 GOLDM and 569 GOLD front-month samples (2026-10-05 → 09) | the MCX cost model |
| MCX curve | production `mcx_curve` | GOLDM Nov → Mar 2027 contracts, 2026-10-09 | carry |
| USD/INR | Yahoo INR=X | daily since 2003, hourly 2 years | the MCX premium; proxy check |
| Code | `gold_desk.py`, `gold_delta_feed.py`, `gold_scheduler.py`, `api/routes/gold_desk.py`, `frontend/app/gold-desk/page.tsx`, and the shared `commodity_patterns`, `commodity_bars`, `commodity_engine`, `mcx_market`, `tradingai_shared/mcx_fees` | 2,270 lines of the desk's own, plus the shared modules it calls | look-ahead, fills, risk controls, cost |
| Literature | §7, with sources | — | hypotheses, base rates |

**Limits, stated up front.**

- **The desk has never traded.** Both books shipped OFF on 29 September and were never switched on, so there is no forward record of any kind. Every profitability figure here is a replay of the desk's own catalogue through its own `evaluate()` on history — honest about fills and costs, but a replay, not a record.
- **Delta's gold perps are young.** PAXGUSD launched 2026-02-19 and XAUTUSD 2026-04-17, so the desk's own Delta venue offers 6–8 months of history. The 24/7 replay is extended to 21 months with Binance PAXG, which is a different venue's book of the same token.
- **Before 2025 there is no usable one-minute gold-token history.** Binance PAXG had no trade at all in 49–81% of minutes in 2020–2023, and its hourly moves tracked COMEX gold at only 0.67 in 2024 (0.88 in 2025, 0.985 in 2026). It is used only from 2025.
- **MCX intraday history is two to three months.** Angel serves nothing for an expired contract, so the MCX store holds only what the poller has collected since August. Below one hour, MCX's own bars are the only faithful history: world gold explains MCX gold well at an hour (correlation 0.87) but poorly at a minute (0.62), because the rupee, the import premium and MCX's own order flow move it too. Sub-hour MCX results are labelled THIN.
- **Two costs are modelled, not measured, where measurement was impossible:** Delta's funding period (the venue's documentation does not state whether its 0.005 rate is per 8 hours or per 4-hourly exchange — both are reported) and Binance-era spreads (Delta's measured spreads are applied to the Binance replay).
- **Exits on the COMEX and daily replays are resolved on hourly and daily bars,** stop-first inside a bar. That is conservative for both directions of error except one: a bar that touched the target first and the stop later is booked as a stop.

---

## 2. Architecture and strategy inventory

```
gold_scheduler.py ── gold_mcx_loop (180 s, MCX hours) ─┐
                  ├─ gold_delta_loop (180 s, 24/7) ────┼─► gold_desk.run_cycle(venue)
                  └─ gold_delta_bars_loop (120 s, 24/7)│      manage_cycle → scan_cycle → equity sample
                         └─► gold_delta_feed.refresh_all ─► gold_delta_bars (Mongo)
commodity_bars poller (shared, Angel) ─► commodity_bars (Mongo) ─► MCX bars
gold_desk.scan_cycle: for symbol in venue.symbols → for tf in 1m..1d → load 250 bars →
    for spec in COMMODITY_CATALOG (that tf) → commodity_patterns.evaluate(spec, bars) → _open
gold_desk.manage_cycle: one LTP per symbol → target / stop / max-hold → _close
api/routes/gold_desk.py (/api/gold-desk/*) ─► frontend/app/gold-desk/page.tsx (two tabs)
```

| Venue | Instruments | Book | Slots | Sizing | Costs charged | Hours |
|---|---|---|---|---|---|---|
| MCX | GOLDM (100 g), GOLD (1 kg — always refused: ₹1.47 crore a lot) | ₹30,00,000 | 4 | 1 lot per position, margin at the measured 9.2% | 5 bp slippage a side + Angel MCX charges (₹305 a GOLDM round trip, 2.03 bp) | MCX calendar |
| Delta | XAUTUSD, PAXGUSD (0.001 oz contracts) | $10,000 | 6 | an equal slot share at 1x | 5 bp slippage a side + taker 0.01% × 1.18 GST | 24/7 |

**The strategy catalogue** is the shared commodity pattern library (`commodity_patterns.COMMODITY_CATALOG`): **46 templates on up to 8 timeframes = 353 strategies** (the VCP family starts at 15m, the opening range skips 1d), every one evaluated on every symbol of the venue (706 streams a venue). Three families:

| Family | Templates | Strategies | What they bet on |
|---|---|---|---|
| Chart (geometry over swing pivots) | 13: head & shoulders, double/triple top-bottom, three triangles, wedge, flag, pennant, cup & handle, rounding, diamond, broadening | 104 | classical reversal/continuation shapes |
| Candlestick | 10: engulfing, hammer/star, doji, marubozu, inside bar, outside bar, three soldiers/crows, morning/evening star, pin bar, Heikin-Ashi flip | 80 | one-to-three-bar reversal or continuation |
| Structure | 23: Donchian fast/slow, Keltner, Bollinger %B and squeeze, TTM squeeze, EMA ribbon, ATR thrust, HH/HL shift, opening range, pivot R1/S1, Fibonacci 61.8%, EMA pullback, gap fade, prior-session break, round-number break, 5 VCP variants, pocket pivot, high-tight flag | 169 | breakouts, mean reversion, volatility expansion |

Every template exits on an ATR-scaled target and stop (targets 2–5 ATR, stops 1–2 ATR, reward-to-risk 2.0–2.5) or after 60 bars of its own timeframe. Long and short.

---

## 3. Verified profitability findings

### 3.1 The desk has no record — so the question is answered by replay

`gold_desk_positions` and `gold_desk_trades` are empty for both venues. Both books shipped OFF on 2026-09-29 and were never switched on; the loops have run anyway, writing 7,127 equity samples that all read exactly ₹30,00,000 and $10,000. There is nothing to audit for profitability, and nothing has been lost.

So every strategy was replayed (§9): the desk's own catalogue, through its own `evaluate()`, on closed bars, filled at the next minute's open, exits walked minute by minute, on six gold histories — **8.8 million signals, 2,977,769 trades taken** under the desk's one-position-per-strategy rule.

| History | Venue it stands for | Span | Trades | Gold over the span |
|---|---|---|---|---|
| Delta XAUTUSD 1m | Delta (the venue itself) | 2026-04-17 → 10-10 | 511,745 | −13% |
| Delta PAXGUSD 1m | Delta (the venue itself) | 2026-02-19 → 10-10 | 610,143 | −16% |
| Binance PAXG/USDT 1m | Delta (24/7 token, longest clean history) | 2025-01-01 → 2026-10-09 | 1,765,921 | +59% |
| COMEX GC=F hourly in MCX hours | MCX at 1h / 4h / 1d | 2024-05-17 → 2026-10-09 | 17,349 | +78% |
| MCX GOLDM (production store) | MCX itself | 1d from 2025-07, 1h from 2026-05, 1m from 2026-08-11 | 62,220 | −2% (1m span) |
| COMEX GC=F daily | MCX at 1d, 26 years | 2000-12 → 2026-10 | 10,391 | 15× |

### 3.2 Below four hours there is no edge, even before costs

Mean bp per trade, **gross** (before any cost) → **net** of measured costs (§3.8). Pooled t-statistics are on weekly sums (§9).

| Timeframe | Delta XAUT 2026 | Delta PAXG 2026 | Binance PAXG 2025–26 | MCX GOLDM | Median move | Median stop |
|---|---|---|---|---|---|---|
| 1m | +0.21 → −2.22 | +0.15 → −2.45 | +0.22 → −2.38 | −0.30 → −3.62 | 3.7–6.3 bp | 2.9–4.9 bp |
| 5m | −0.00 → −2.43 | +0.06 → −2.54 | +0.05 → −2.55 | −0.57 → −3.88 | 10–17 bp | 8–13 bp |
| 15m | −0.31 → −2.75 | +0.18 → −2.42 | +0.04 → −2.58 | +1.83 → −1.49 | 20–30 bp | 17–23 bp |
| 30m | +0.31 → −2.14 | +0.70 → −1.92 | +0.81 → −1.83 | +1.92 → −1.39 | 30–42 bp | 25–33 bp |
| 45m | +0.38 → −2.07 | +0.12 → −2.50 | +0.86 → −1.80 | −0.99 → −4.30 | 38–52 bp | 32–41 bp |
| 1h | +0.23 → −2.22 | −0.12 → −2.75 | +1.35 → −1.34 | +1.63 → −1.69 | 46–63 bp | 38–50 bp |

**Every one of the 24 cells is negative after costs.** The gross edge is a fraction of a basis point on moves of tens of basis points: the largest, +1.92 bp at 30m on MCX (weekly t 0.6), is still less than MCX's fees alone (2.03 bp, of which the sell-side CTT is 1.00). On the 24/7 histories the tiny positive gross at 1m (+0.15 to +0.22 bp, "significant" only because there are a million trades) is the kind of bounce a minute bar's close carries, worth less than a tenth of the venue's fee.

### 3.3 Above four hours, the positive numbers are gold's trend — and holding gold did better

| | 4h net (n) | 1d net (n) | Long-side gross, all trades | Short-side gross, all trades |
|---|---|---|---|---|
| Delta XAUT 2026 (gold falling) | +5.12 (1,479) | +12.79 (146) | −0.08 | +0.44 |
| Delta PAXG 2026 (gold falling) | +2.96 (1,954) | +41.16 (209) | −0.27 | +0.62 |
| Binance PAXG 2025–26 | **+8.86 (5,758), weekly t 2.2** | +54.40 (884), t 1.9 | +0.58 | −0.00 |
| COMEX in MCX hours 2024–26 | +7.62 (3,631), t 1.2 | +53.25 (771), t 1.9 | **+17.56** | **−5.26** |
| MCX GOLDM | +10.10 (481), t 0.8 | +87.73 (472), t 2.3 | +0.86 | +0.61 |
| COMEX daily 2000–2026 | — | +7.76 (10,391), t 1.3 | **+44.98** | **−33.11** |

Three tests separate pattern from trend:

1. **Drift-adjusted** — each trade's gross minus what a random trade on the same side, held as long, earned from the period's trend. At 1d: COMEX 26 years +7.0 bp (weekly t 1.2); COMEX MCX-hours +33.9 (t 1.2); MCX GOLDM +64.6 (t 1.8). Per strategy, on drift-adjusted **net**: **0 strategies reach t 3 on any of the six histories**; 0–3 per history clear t 2, which is what chance produces among 200–270 strategies.
2. **Against holding gold** (the Commodity Lab's criterion 4, gold alone, 26 years, `gd_benchmark.py`): always-long gold has a held-out Sharpe of 0.64. **39 of 40 daily templates fail** — the long-only VCP family that looked strongest (+75 to +156 bp a trade) has held-out Sharpes of 0.05–0.48: it earned from being long, not from choosing when. **One passes**: Bollinger Squeeze Release (1d) — held-out Sharpe 0.79, alpha +3.2% a year, t 2.37, beta 0.01, in the market 16% of days. The Lab ran the same template on gold, silver, copper, crude and natural gas in rupees with carry: **REJECTED**, −1.8% a year explore, −2.8% held-out, alpha t −1.3. One asset of five looking good is what luck produces; its deflated Sharpe here is 0.34, and at four trades a year a forward test would need about seven years to say anything.
3. **The 4h effect is a regime, not a set of strategies.** Pooled 4h is positive on all five histories that have it, but those histories are one market seen five ways (2024–26, when gold trended hard in both directions); it is significant on one (Binance PAXG, weekly t 2.2; drift-adjusted t 2.6), positive in 6 of 8 quarters there and 7 of 11 on COMEX. It is broad: 31 of 40 templates are positive at 4h on Binance PAXG — and concentrated in the **breakout / trend-structure** templates (+16.2, +12.2, +12.0 bp on the three 4h histories) and chart geometry; candlesticks (≈ 0) and mean reversion (mixed) carry none of it. That is the shape of short-horizon trend-following in a trending market. **No 4h strategy survives deflation on its own** (best: VCP Breakout 4h, t 3.27 on 41 trades, DSR 0.77, negative on Delta's own 2026 data). It is one hypothesis worth one pre-registered forward test (H1), not a result.

**Persistence.** Does a strategy's first half predict its second? Spearman across strategies: −0.01 (Delta XAUT), −0.11 (Delta PAXG), +0.14 (Binance), +0.14 (COMEX hours), +0.21 (COMEX daily). Of the strategies at t > 2 in a first half, the second half was positive for 0 of 1, 0 of 2, 6 of 6, 0 of 0 and 3 of 3 — the six and the three are 4h and daily trend-side strategies in a trending market. **Probability of backtest overfitting** (CSCV): 0.32, 0.26, 0.12, 0.67, 0.36, 0.32 — on COMEX hours the in-sample best is more likely than not to land below the median out of sample. **Deflated Sharpe ≥ 0.95: 0 strategies on any history.**

### 3.4 Every ex-ante cut is negative below four hours

Binance PAXG 2025–26, net of measured costs, all timeframes (the other 24/7 histories match it to ±0.3 bp):

| Cut | Result |
|---|---|
| Trend (close vs 50-day mean, yesterday) | down −2.34 · up −2.23 bp |
| Volatility (20-day, tercile, yesterday) | low −2.41 · mid −2.27 · high −2.15 |
| Session (UTC) | Asia 00–07 −1.93 · London 07–13 −2.38 · New York 13–21 −2.48 · late 21–24 −2.65 |
| Weekday / weekend | −2.20 · −2.65 (weekend bars barely move: XAUT's median 1-minute range is 0.07 bp on weekends vs 2.33 on weekdays) |
| Side | long +0.58 gross · short −0.00 gross (both negative net) |
| Family | candlestick −2.36 · chart −2.25 · structure −2.28 |

Holding time *looks* decisive (<15 min −3.01, 1–5 days +19.72, >5 days +100.81) but it is decided by the outcome — winners run to distant targets, losers stop out fast — so it cannot be traded ex ante. The MCX GOLDM cuts tell the same story (`gd_analyse.py D_GOLDM`): both trend states and all three sessions negative after costs (−0.9 to −3.8 bp); one volatility tercile is positive (+14.7 bp on 607 trades, t 1.3), the other two negative.

### 3.5 Where the money goes

The gross edge per trade *is* the most a round trip could cost and still break even:

| Timeframe | Break-even round trip (Binance PAXG gross) | Delta's measured round trip | MCX's measured round trip |
|---|---|---|---|
| 1m–15m | 0.04–0.22 bp | 2.43–2.60 bp | 3.31 bp |
| 30m–1h | 0.81–1.35 bp | ″ | ″ |
| 4h | 11.77 bp | ″ | ″ |
| 1d | 58.24 bp | ″ | ″ |

Below 4h the fee alone (Delta 2.36 bp; MCX 2.03 bp) exceeds the gross edge in every cell, so **even a zero-spread fill leaves every sub-4h cell negative**. Halving the fee as well would lift three cells barely above zero — Binance 1h +0.05, MCX 15m +0.17, MCX 30m +0.26 bp — on gross t-statistics of 0.6–1.3: not an edge anyone could trade or verify.

### 3.6 The desk as a system: both books hit their floor

`gd_book.py` runs each book with the desk's own rules — one shared balance, slots filled in scan order (symbol, then 1m → 1d, then catalogue order), one position per strategy, 1 GOLDM lot or one equal Delta slot, the 3% daily breaker and the 50% floor.

| Book | Window | Costs | Trades | Result | Gold | What took the slots |
|---|---|---|---|---|---|---|
| Delta $10,000, 6 slots | 2026-04-17 → 10-10 | desk (5 bp) | 2,733 | **−50.1%, floor hit** | −13.4% | 100% 1m/5m |
| ″ | ″ | measured | 14,756 | **−50.0%, floor hit within ~3 weeks** | −13.4% | 100% 1m/5m (+0.11 bp gross, −2.33 net) |
| MCX ₹30 L, 4 slots | 2026-08-11 → 10-09 | desk | 804 | **−50.4%, floor hit** | −1.8% | 100% 1m/5m |
| ″ | ″ | measured | 2,694 | **−50.3%, floor hit within ~22 sessions**; breaker tripped 15 days | −1.8% | 100% 1m/5m |
| MCX, 1h/4h/1d only | 2024-05-23 → 2026-10-09 | measured | 1,206 | **−52.2%, floor hit**; under water 315 days | **+77.9%** | 1h 98%; the 20 4h trades that got a slot made +49 bp each; 1d never got one |

The page says it itself: "They queue, so the fastest timeframes take most of the fills — a property of the clock, not of the edge." In replay that property is the whole result: the slots go to the strategies that cannot pay their fees, and the only ones with a positive record never trade. (The replay lets 1m strategies act on every minute; the live desk, scanning every 3 minutes, would see one minute in three — the floor arrives later, not differently.) The MCX book also held **long and short GOLDM at the same time for 31–45% of the hours it had positions** (D9), and four lots in one direction (₹60 lakh on ₹30 lakh) at its peak.

### 3.7 What the desk *as built* would report instead

| Defect | Measured effect |
|---|---|
| Forming-bar signals (D1) — Delta XAUT, 12 templates | the desk would take **1.5–2.7× the closed-bar strategy's trades**; **40% (15m), 54% (1h), 58% (4h), 62% (1d)** of its trades are signals that do not exist on the closed bar, decided a median 20% / 10% / 5% / 2% of the way into the bar (a daily signal ~30 minutes into the UTC day). Those extra trades lose **−2.6 / −3.7 / −5.5 / −20.1 bp before costs**. |
| Polled exits (D4) | targets booked **+3.4 to +5.4 bp beyond their own level** on average (Delta XAUT +3.41, PAXG +4.19, Binance +3.73, MCX GOLDM +5.41); net effect on the record −0.2 to +1.0 bp a trade depending on how stops are missed |
| The 5 bp slippage guess (D5) | desk-charged net −12.1 to −12.3 bp a trade on Delta histories where the measured cost is 2.4–2.6 |
| No funding (D6) | a long 1d trade (held ~7.5 days) owes **≈11 bp** of funding at the base rate (22 bp in the high case); a 4h trade ≈2 bp (4 bp) — none of it charged |
| "Worth real money? READY" (D13) | with zero true edge (sign-randomised records), the desk's gate labels **3–6% of eligible strategies READY** — 2.2 to 10.3 of them per history; on the real histories it labels 1–11 at measured costs, inside the same range |

### 3.8 Costs, measured

| Component | Delta | MCX (one GOLDM lot) |
|---|---|---|
| Fee | taker = maker = **0.01%** a side (product spec) + 18% GST = **2.36 bp** a round trip | Angel ₹20/order + exchange 0.0021% + SEBI + CTT 0.01% (sell) + stamp 0.002% (buy) + GST = **₹305 = 2.03 bp** at ₹15 L |
| Spread | XAUTUSD quoted **0.072 bp**, $1,667 crosses for **0.036 bp** a side; PAXGUSD 0.239 / 0.12 bp (weekend samples; weekday sampling continues to 2026-10-13) | GOLDM front month median **1.28 bp** (p90 2.03), 1–2 lots at the touch; GOLD 2.21 bp |
| Funding / carry | **+0.005 on 100% of XAUT hours, 96% of PAXG**, longs pay: ~1.5 bp a day (5.5%/yr) if per 8 h, ~3 bp if per 4-hourly exchange — the venue does not document which | curve ~0.8–0.9% a month (Nov → Dec 2026) — in the futures price, paid by longs at every roll |
| Other | perps trade ~12 bp over their spot index | MCX trades **+13.7% to +15.1%** over world gold at USD/INR ≈ 96.8 (import duty and local premium) |

### 3.9 Statistical limitations

- The six histories overlap in time: four of them cover 2025–26. They are not six independent confirmations, and 2024–26 was an unusual gold market (+78%, then −13%).
- The intraday histories are short: Delta's own 6–8 months, MCX's sub-hour bars 2–3 months. They cannot show a sub-hour edge of 1 bp if one existed; they can, and do, show that none is anywhere near the cost of trading.
- Funding's period is an assumption (both cases reported; neither changes a sign below 4h).
- The 4h and 1d per-strategy samples are small (tens to a few hundred trades); pooled results carry the conclusions there.
- A replay is not a record. It cannot see exchange outages, MCX price-band lock days, or an order queue — none of which would make a negative gross edge positive.

---

## 4. Confirmed defects

Separate from improvements and hypotheses (§8). Each was confirmed in the code and, where the desk's state allows, in data. Because the desk has never traded, none of them has cost money or corrupted a record yet — they decide what the record would say on the day the switch is flipped.

| ID | Where | Defect | Evidence | Severity |
|---|---|---|---|---|
| **D1** | `gold_desk.load_bars` (`gold_desk.py:180-183`) → `scan_cycle` (`:574-591`) | **Patterns are evaluated on the bar that is still forming.** MCX bars are loaded without `closed_only`; Delta's store holds the venue's live candle. `bars[-1]` — the bar every template reads as "the latest" — is a half-built candle, and the desk acts on the first 3-minute scan on which a pattern appears on it. The commodity desks were fixed for exactly this on 2026-10-05 (`commodity_engine.py:493`, `commodity_prelive.py:756`, `natgas_book.py:352`); the Gold Desk, built a week earlier, was not. | Replayed exactly as built on Delta XAUT (`gd_forming.py`, 12 templates): the desk takes 1.5–2.7× the closed-bar strategy's trades; **40–62% of them are signals that never exist on the closed bar**, decided a median 2–20% into the bar, and those lose **−2.6 to −20.1 bp before costs**. | Critical (for evidence) |
| **D2** | `manage_cycle` (`:482`), `close_all` (`:639`) | **After a roll, positions are marked and closed on the wrong contract, and nothing exits before delivery.** `uni.get(symbol)` is the *current* tradable front month (roll-aware since C0–C6), not the contract the position holds. `mcx_market.forced_exit` (roll window, expired contract) exists and is never called. | GOLDM curve on 2026-10-09: Nov 149,720, Dec 151,023 (+0.87%). A long opened on November and marked on December after the roll books a phantom **+87 bp (≈₹13,000 a lot)**; a short a phantom loss. GOLDM is a staggered-delivery contract: a real position left in the tender days becomes a delivery obligation. The commodity desk booked 148 trades this way before its fix. | Critical (for evidence) |
| **D3** | `mark` (`:207-216`) | **MCX fills use an unvalidated last-traded price.** `get_ltp(None, …)` first calls the Dhan client with `None` (an exception, caught and logged on every call), then Angel's LTP with no trade time — a frozen quote inside a session is filled as if live. The shared `mcx_market.quotes` (fresh only when `exchTradeTime` is inside the session; fills at the bid/ask touch) is not used. | Code path; the commodity desks moved to `mcx_market.quotes` on 2026-10-05 after trading a full holiday on a frozen price. | High |
| **D4** | `manage_cycle` (`:507-514`) | **Exits fill at the polled price, not at the level.** One price is read every 180 s; a target that price has overshot is booked *beyond* the target, a stop beyond the stop, and a wick through a level between polls is never seen. The same defect produced the Intraday Patterns desk's +₹52.9 lakh that corrected to −₹23.1 lakh. | Polled model vs honest exits on the same signals (`gd_replay.py`): target exits booked **+3.4 to +5.4 bp beyond their own target** on average (Delta XAUT +3.41, PAXG +4.19, Binance PAXG +3.73, MCX GOLDM +5.41); wicks through a stop between polls are missed and later stops overshoot, so the net bias runs −0.2 to +1.0 bp a trade by history — the record would carry the polling, not the strategy. | Critical (for evidence) |
| **D5** | `Venue.slippage_bps` (`:122`, `:133`) | **The cost of execution is a guess, roughly 8–140× too high.** 5 bp a side on both venues. Measured: GOLDM's quoted spread has a median of **1.28 bp** (half-spread 0.64; p90 2.03) with 1–2 lots at the touch; Delta XAUTUSD is quoted **0.07 bp** wide and a full $1,667 slot crosses for **0.036 bp** a side, PAXGUSD 0.24 bp / 0.12 bp. | `mcx_quote_log` (568 GOLDM samples); `gd_l2_sampler` on Delta. The desk charges **10 bp a round trip** for execution where the market charges 1.3 bp (MCX) or 0.07–0.24 bp (Delta) — on strategies whose typical move below an hour is a few bp, the assumption, not the market, would decide the verdict. | High |
| **D6** | `_close` (`:431-463`) | **No funding on Delta.** Perpetual positions pay or receive funding; the desk charges fees only. | The venue's `FUNDING:XAUTUSD` printed **+0.005 on 4,229 of 4,229 hours** since launch, PAXGUSD on 96.2% of 5,592: longs pay shorts continuously — ~1.5 bp a day (5.5% a year) if the rate is per 8 hours, ~3 bp a day if per 4-hourly exchange. A 60-day hold of a 1d strategy owes 90–180 bp. | High |
| **D7** | `_charges` (`:238`) | **A missing fee is charged as zero.** `inst.get("taker_fee_rate") or 0.0`; the test suite asserts this ("an unknown venue rate charges zero rather than a guessed default"). The product spec is cached for the life of the process. | Code + `verify_gold_book.py`. A record with fees silently at zero is not evidence. | Medium |
| **D8** | `manage_cycle` (`:496-501`) | **The 60-bar hold is wall-clock time, counted from the start of the signal bar.** On MCX the clock runs through nights and weekends: a 1h strategy's "60 bars" ends after 60 hours — about 36 trading hours — and a 1d strategy's after 60 calendar days (≈42 sessions). | Code. Every backtest, including this one, counts bars. | Medium |
| **D9** | `_open` (`:372-375`), `_sizing` (`:260`) | **The book can hold opposite and stacked positions on one contract.** Duplicates are checked per (template, timeframe, symbol) only, so one strategy can be long GOLDM while another is short it — a real account nets those to zero and pays one set of costs; the paper book pays two and holds two margins. The "never hold more gold than the book can pay for" cap is per position: four GOLDM lots (₹60 lakh) fit on the ₹30 lakh book, **2× leverage**. | Book replay (`gd_book.py`): the MCX book held **long and short GOLDM at the same time for 45% (store window) and 31% (COMEX-hours window) of the hours it had positions**; 1,626 and 617 entries opened a position offsetting one already held; four lots in one direction at the peak. | High |
| **D10** | `today_pnl` (`:352-364`) | **The daily-loss breaker undercounts.** It adds open P&L only for positions *opened today*; a position opened yesterday and losing today is invisible to it until it closes. | Code. | Medium |
| **D11** | `gold_delta_feed.refresh_symbol` (`:246-257`), `gold_scheduler.py:63-74`, `run_cycle` (`:617`) | **Heavy writes for a desk that is off.** The Delta bar loop has no switch and rewrites every stored candle of every interval each pass, setting `updated_at` each time; the store is never pruned; `run_cycle` writes an equity sample every 3 minutes whether or not anything happened. | Measured on production: **~17,000 candle documents rewritten per 2-minute pass** (8,233 of them more than 3 days old, which cannot have changed) — ~140 writes a second, ~12 million a day, around the clock; 58,762 candles after 13 days, growing ~3,000 a day; 7,127 flat equity rows. | High (operational) |
| **D12** | `gold_scheduler.py:53`, `:83` | **Main Control "off" also stops stop-management.** `is_on("gold_desk")` gates the whole `run_cycle`, so open positions would sit unmanaged; the module docstring says the loops run "whether or not the desk is switched on" — true of the desk's own switch, not of Main Control. | Code. | Medium |
| **D13** | `gold_desk.strategies` → `commodity_engine._verdict`; `page.tsx:418-439` | **The page labels strategies "READY" under a column titled "Worth real money?"** — the gate the commodity desk retired on 2026-10-05 because it promoted luck (11 of 16 READY strategies lost money afterwards; ranking persistence Spearman −0.035). Its drawdown test is measured against the whole book (₹30 lakh / $10k), so it cannot fail for one strategy. The CSS knows `pass/fail/pending`; the verdicts are `READY/REJECTED/PENDING`. Copy is stale ("whole MCX lots on SPAN-lite margin"; margin has been broker-measured since 2026-10-09). | `gd_luck.py`: with every strategy's edge removed (trade signs randomised, 200 draws) the gate labels **3–6% of eligible strategies READY** — 2.2 to 10.3 per history. On the real replays it labels 1–11 at measured costs: indistinguishable from luck. | High |
| **D14** | catalogue on Delta | **Session templates on a market with no session, and dead weekend bars.** `gap_fade` and `opening_range` treat UTC midnight as an open on a continuous 24/7 market (no gap exists; the "opening range" is an arbitrary hour) — 15 strategies with no meaning there. Weekend token bars barely move (XAUTUSD median 1-minute range **0.07 bp on weekends vs 2.33 bp on weekdays**), so patterns read noise, with ATR-scaled stops a fraction of a weekday's. | `gd_quality.py`. | Medium |
| **D15** | `Venue.symbols` | **The same bet twice, and a contract that can never trade.** Every strategy runs on both XAUT and PAXG, which are the same ounce (basis sd 13 bp), so two slots can carry one idea. Every strategy is also evaluated on GOLD (1 kg) every cycle, which `_sizing` always refuses. | Basis statistics; sizing test. | Low |
| **D16** | `_sizing` | **Size ignores risk.** One lot or one equal slot regardless of the stop: a 1m strategy's stop is a few bp, a 1d strategy's a few hundred, so risk per trade varies by roughly two orders of magnitude and the book's result is the daily strategies'. | Replay: stop distance by timeframe (§3). | Medium |
| **D17** | `backend/tests/gold_desk/verify_gold_book.py` | **The tests fail to import under the default interpreter** (a stale `TradingAI/shared` package shadows the repo's `shared/`; the file does not put `shared/` on the path the way the newer suites do), and they cover none of D1–D12. They pass (26/26) with the repo path set. | Run log. | Low |
| **D18** | `basis()` | **The cross-venue card never shows the MCX premium** — it needs `GOLD_USD_INR`, which is unset. Measured: **+13.7% to +15.1%** over world gold at USD/INR ≈ 96.8 (2026-07-01 → 10-08). | `gd_quality.py`. | Low |

---

## 5. Strategy-by-strategy assessment

### 5.1 By family — hypothesis, implementation, evidence, decision

All 46 templates live in `backend/app/services/commodity_patterns.py` (`TEMPLATES`, `evaluate`), are instantiated on up to eight timeframes by `_build_catalog`, and are run by `gold_desk.scan_cycle`. Figures are net of measured costs (bp a trade) unless marked gross: "below 4h" pools 1m–1h on Binance PAXG (Delta-like) and on the MCX GOLDM store; "4h" lists Binance PAXG / Delta's own 2026 data / COMEX in MCX hours; "1d" is 26 years of COMEX daily.

| Family (strategies) | Trading hypothesis | Current implementation | Performance evidence | Cost sensitivity | Risk profile | Main weaknesses | Upgrade proposal | Final decision |
|---|---|---|---|---|---|---|---|---|
| **Candlestick** — engulfing, hammer/star, doji, marubozu, inside bar, outside bar, three soldiers/crows, morning/evening star, pin bar, Heikin-Ashi flip (80) | one-to-three-bar exhaustion or continuation predicts the next move | body/wick ratios and 20-bar extremes; target 2–2.5 ATR, stop 1–1.2 ATR | below 4h gross **+0.21 / −0.02**, net **−2.39 / −3.34**; 4h ≈ 0 (−0.2, +0.3, −1.9); 1d +5.7, **0 of 10 beat holding gold** | total: the sub-4h gross is < 10% of the fee | 62% stop-outs; stops of 1 ATR sit inside noise | no edge before costs at any horizon (consistent with Marshall, Young & Rose 2006) | none worth building | **DISABLE** (all 80) |
| **Chart geometry** — head & shoulders, double/triple top-bottom, three triangles, wedge, flag, pennant, cup & handle, rounding, diamond, broadening (104) | classical shapes mark shifts between supply and demand | geometry over 3-bar swing pivots; target 2.5–4 ATR, stop 1.5–2 ATR | below 4h **−2.33 / −3.56**; 4h **+16.2 / +9.9 / +18.6** (a few hundred trades each); 1d +1.8, **0 of 10** beat holding gold; flags, pennants, wedges, rounding and symmetrical triangles fire a few dozen times in years | below 4h total; at 4h costs are ~15% of gross | 63% stop-outs; rare triggers make results lumpy | a pivot-geometry reading of a visual pattern; several templates have no sample at all | none on their own; their 4h signals belong to H1's pooled test | **DISABLE** below 4h and at 1d; 4h only inside H1 |
| **Breakout / trend structure** — Donchian 20 and 55, Keltner, prior-session break, round-number break, pivot R1/S1, HH/HL shift, ATR thrust, EMA ribbon (72) | a break of a recent range or level starts a move that persists (short-horizon time-series momentum) | channel and level breaks; target 2–4 ATR, stop 1–2 ATR | below 4h **−2.37 / −3.23**; **4h +16.2 / +12.2 / +12.0 — the one result with the same sign on all three 4h histories**; 1d +3.1, **0 of 9** beat holding gold; the Lab's gold trend rules (TS12, TS3, MA, Donchian) all lose to holding | below 4h total; at 4h costs ~15–20% of gross | 61% stop-outs, positively skewed at 4h | fixed targets cut the trend tail; daily versions are being long a rising asset | **H1**: one pre-registered forward test of this family at 4h on Delta XAUTUSD | **DISABLE** below 4h and at 1d; **4h → H1 only** |
| **Volatility squeeze** — Bollinger squeeze, TTM squeeze (16) | compression precedes expansion; the break picks the direction | Bollinger width at a 30-bar low / Bollinger inside Keltner; target 3.5 ATR | below 4h **−2.52 / −3.57**; 4h mixed (+15.0, −15.4, +29.7); 1d: **Bollinger Squeeze is the only daily template that beats holding gold** (alpha t 2.37, held-out Sharpe 0.79 vs 0.64) — and the Lab's five-commodity run of it lost (alpha t −1.3); TTM squeeze does not beat it | below 4h total | 64% stop-outs; four trades a year at 1d | one asset of five; deflated Sharpe 0.34 | none — a forward test would need ~7 years | **DISABLE**; Bollinger Squeeze 1d **RESEARCH ONLY** |
| **Mean reversion / pullback** — Bollinger %B extremes, Fibonacci 61.8%, EMA pullback (24) | stretched prices revert; trends resume after pullbacks | %B beyond the bands, 61.8% retracement holds, a touch of the 20-EMA in a 20/50 trend | below 4h **−2.52 / −3.36**; 4h mixed (−1.7, +3.4, −9.4); 1d −2.5, **0 of 3** | total | 62% stop-outs | no edge in either direction | none | **DISABLE** |
| **VCP / Minervini**, long-only, 15m and up — VCP breakout, 3-contraction, tight base, volume dry-up, pivot reclaim, pocket pivot, high-tight flag (42) | supply dries up in contracting bases before a breakout (growth-stock lore) | `vcp_core` shared with Intraday Stocks; long only; target 3–5 ATR | below 4h **−1.49 / −1.97**; 4h **+37.4** (Binance, gold +59%) / **−21.3** (Delta 2026, gold −13%) / +52.6 — the sign follows the market's direction; 1d +61.3 but **0 of 6 beat holding gold** (held-out Sharpe 0.05–0.48 vs 0.64) | modest at 4h+ | 66% stop-outs; long gold exposure only | a lagged way of being long gold | none | **DISABLE** |
| **Session** — opening range breakout, gap fade (15) | the session's opening range and opening gap carry information | first 4 bars of the session; gap ≥ 0.4% vs the prior close | below 4h **−2.30 / −3.64**; gap fade never fires on Delta (no gaps in a 24/7 market) | total | 64% stop-outs | **meaningless on Delta** (UTC midnight is not an open — D14) | — | **REMOVE on Delta; DISABLE on MCX** |

### 5.2 Every template, in numbers

Generated by `gd_strategy_table.py` (the rule is in its docstring): below 4h, DISABLE when pooled net ≤ 0 on both venues — or positive only on fewer than 100 trades or t < 2; at 4h, **H1** for the nine breakout / trend-structure templates when net > 0 on the longest 24/7 history (admitted only to the pooled forward test), "4h+ (regime, not H1)" for any other template positive there, otherwise DISABLE; at 1d, DISABLE unless the template beats holding gold on both of the Lab's tests.

**Counts:** below 4h — **46 of 46 DISABLE** (10 of them with a positive sign on fewer than 100 trades or t < 2). 4h — **9 H1** (all nine breakout / trend templates positive), 21 positive but outside H1 (regime, no standing on their own), 9 DISABLE, 5 too few trades, 2 session templates removed on Delta. 1d — **39 DISABLE (holding gold did better)**, 6 too few trades, 1 RESEARCH ONLY (Bollinger Squeeze). **Per strategy (353 × 2 venues): 0 CANDIDATE.**

| Template | Family | <4h Delta-like: gross / net (n) | <4h MCX: gross / net (n) | 4h Binance: net (n, t) | 4h Delta 2026: net (n) | 4h COMEX/MCX hrs: net (n) | 1d 26-yr: net (n) | 1d vs holding gold: alpha t · held-out SR | Decision <4h · 4h · 1d |
|---|---|---|---|---|---|---|---|---|---|
| Doji Reversal | candlestick | +0.36 / -2.24 (34,014) | +0.29 / -3.02 (759) | -20.1 (61, t -1.8) | -38.3 (25) | -29.6 (57) | -4.6 (136) | -0.04 · -0.09 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Engulfing Candle | candlestick | +0.25 / -2.35 (66,701) | +0.27 / -3.04 (3,013) | +6.4 (318, t +1.0) | +2.7 (180) | -9.4 (175) | +1.7 (364) | +0.48 · +0.22 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Hammer / Shooting Star | candlestick | +0.22 / -2.38 (67,129) | -0.22 / -3.53 (4,162) | -4.0 (336, t -0.6) | -1.9 (201) | -14.9 (262) | +6.2 (520) | +0.43 · -0.08 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Heikin Ashi Flip | candlestick | +0.09 / -2.51 (113,086) | -0.76 / -4.08 (3,915) | +9.9 (293, t +1.2) | +17.8 (166) | +26.6 (196) | +17.9 (605) | +1.83 · +0.47 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Inside Bar Breakout | candlestick | +0.15 / -2.46 (65,373) | +0.44 / -2.87 (2,102) | -6.6 (126, t -0.7) | -12.6 (86) | -11.7 (128) | +0.4 (299) | -0.09 · -0.03 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Marubozu Continuation | candlestick | +0.25 / -2.35 (176,810) | -0.20 / -3.51 (4,052) | -5.0 (120, t -0.5) | -3.1 (68) | +6.2 (54) | +0.3 (399) | +0.10 · +0.13 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Morning / Evening Star | candlestick | +0.24 / -2.36 (65,076) | -0.04 / -3.36 (2,760) | -18.1 (260, t -2.3) | -5.6 (157) | -7.6 (172) | +0.8 (409) | -0.22 · -0.09 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Outside Bar Reversal | candlestick | +0.25 / -2.35 (45,583) | +1.23 / -2.09 (2,551) | +1.3 (294, t +0.2) | +10.3 (197) | -4.3 (185) | +10.7 (388) | +0.97 · +0.13 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Pin Bar at Extreme | candlestick | +0.25 / -2.34 (37,536) | -0.43 / -3.75 (1,135) | -6.4 (100, t -0.5) | -25.1 (49) | +10.7 (62) | -5.5 (140) | -0.44 · +0.10 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Three Soldiers / Crows | candlestick | +0.17 / -2.43 (81,811) | -0.12 / -3.44 (3,381) | +11.4 (317, t +1.4) | -1.4 (199) | +10.0 (183) | +7.3 (419) | +0.49 · +0.04 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Ascending Triangle | chart | +1.29 / -1.49 (1,119) | -8.45 / -11.76 (95) | +55.8 (22, t +2.3) | +94.1 (4) | +97.4 (9) | -3.9 (15) | — · — | DISABLE · 4h+ (regime, not H1) · INSUFFICIENT |
| Broadening Formation | chart | +3.66 / +0.94 (109) | +18.84 / +15.53 (13) | +13.4 (15, t +0.2) | +112.9 (9) | -58.0 (10) | +34.7 (51) | +0.89 · +0.38 | DISABLE (+ on < 100 trades or t < 2) · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Bull / Bear Flag | chart | +37.80 / +35.23 (40) | +10.90 / +7.59 (4) | +147.7 (7, t +1.9) | +192.7 (3) | -8.2 (18) | -17.8 (88) | -0.53 · -0.02 | DISABLE (+ on < 100 trades or t < 2) · INSUFFICIENT · DISABLE — holding gold did better |
| Cup & Handle | chart | +0.02 / -2.59 (9,587) | -1.32 / -4.63 (324) | +20.5 (20, t +0.5) | +25.9 (12) | +42.7 (11) | -74.2 (28) | -0.98 · -0.24 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Descending Triangle | chart | -0.73 / -3.18 (793) | +12.79 / +9.48 (65) | -52.6 (7, t -1.4) | -80.9 (4) | -156.6 (3) | -56.8 (8) | — · — | DISABLE (+ on < 100 trades or t < 2) · INSUFFICIENT · INSUFFICIENT |
| Diamond | chart | +0.28 / -2.32 (21,362) | -0.47 / -3.78 (609) | +12.7 (53, t +0.5) | +8.8 (44) | -2.0 (30) | +5.1 (92) | +0.14 · +0.12 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Double Top / Bottom | chart | +0.30 / -2.31 (79,419) | +0.12 / -3.19 (3,157) | +15.5 (237, t +1.6) | +7.8 (154) | +7.1 (118) | -2.7 (367) | -0.47 · -0.25 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Head & Shoulders | chart | +0.51 / -2.10 (20,414) | -1.12 / -4.43 (974) | +38.6 (59, t +2.2) | +23.8 (27) | +30.9 (61) | +11.2 (136) | +0.36 · +0.07 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Pennant | chart | +22.02 / +19.28 (49) | -56.81 / -60.13 (6) | -75.5 (11, t -2.3) | -43.1 (7) | +101.0 (13) | -40.1 (57) | -1.12 · -0.20 | DISABLE (+ on < 100 trades or t < 2) · DISABLE · DISABLE — holding gold did better |
| Rising / Falling Wedge | chart | -17.31 / -20.15 (48) | +5.22 / +1.91 (5) | -31.6 (4, t -0.3) | -47.1 (4) | +154.1 (5) | -32.2 (19) | — · — | DISABLE (+ on < 100 trades or t < 2) · INSUFFICIENT · INSUFFICIENT |
| Rounding Top / Bottom | chart | +23.72 / +20.86 (69) | -100.68 / -103.99 (8) | -42.4 (25, t -0.9) | -171.4 (12) | +8.6 (32) | -18.4 (156) | -0.30 · +0.13 | DISABLE (+ on < 100 trades or t < 2) · DISABLE · DISABLE — holding gold did better |
| Symmetrical Triangle | chart | +9.93 / +7.35 (74) | -79.69 / -83.01 (4) | +40.5 (14, t +1.0) | +23.2 (10) | +49.6 (11) | +39.7 (47) | +0.68 · +0.58 | DISABLE (+ on < 100 trades or t < 2) · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Triple Top / Bottom | chart | +0.19 / -2.41 (103,220) | +0.20 / -3.12 (2,799) | +16.2 (187, t +1.4) | +20.5 (95) | +21.2 (100) | +31.0 (246) | +1.30 · +0.19 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| ATR Expansion Thrust | structure | +0.12 / -2.48 (66,804) | +0.58 / -2.73 (838) | +20.5 (120, t +1.6) | +30.3 (79) | +8.0 (48) | +1.1 (146) | +0.70 · +0.13 | DISABLE · H1 · DISABLE — holding gold did better |
| Bollinger %B Extreme | structure | +0.18 / -2.42 (89,864) | -0.25 / -3.57 (3,158) | -8.8 (327, t -1.5) | -2.7 (205) | -4.6 (156) | -5.5 (471) | -0.31 · -0.20 | DISABLE · DISABLE · DISABLE — holding gold did better |
| Bollinger Squeeze Release | structure | +0.23 / -2.37 (19,312) | -0.55 / -3.87 (665) | +16.2 (75, t +0.9) | -5.9 (50) | +27.9 (39) | +84.5 (102) | +2.37 · +0.79 | DISABLE · 4h+ (regime, not H1) · RESEARCH ONLY |
| Donchian Breakout (fast) | structure | +0.14 / -2.46 (80,137) | -0.19 / -3.51 (2,519) | +17.6 (207, t +1.5) | +8.2 (119) | +4.0 (133) | +19.0 (425) | +0.84 · +0.25 | DISABLE · H1 · DISABLE — holding gold did better |
| Donchian Breakout (slow) | structure | +0.46 / -2.14 (40,177) | +0.91 / -2.41 (1,247) | +20.9 (115, t +1.1) | +27.8 (57) | +40.7 (71) | +9.5 (215) | -0.40 · +0.03 | DISABLE · H1 · DISABLE — holding gold did better |
| EMA Ribbon Compression | structure | +0.06 / -2.55 (24,256) | +0.85 / -2.47 (1,210) | +34.2 (145, t +2.8) | +16.4 (112) | +36.8 (76) | -1.5 (175) | -0.15 · +0.00 | DISABLE · H1 · DISABLE — holding gold did better |
| Fibonacci 61.8% Bounce | structure | -0.04 / -2.64 (26,723) | +0.87 / -2.44 (978) | +13.2 (64, t +0.6) | +17.5 (43) | -17.9 (43) | -3.3 (144) | -0.54 · -0.06 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Gap Fade | structure | — / — (0) | -3.78 / -7.09 (789) | — (0, t —) | — (0) | +24.3 (123) | — (0) | — · — | DISABLE · REMOVE on Delta; DISABLE on MCX · INSUFFICIENT |
| HH/HL Structure Shift | structure | +0.40 / -2.21 (13,983) | -0.64 / -3.95 (839) | +11.6 (60, t +0.6) | +11.7 (38) | +30.1 (75) | -1.0 (151) | +0.09 · +0.01 | DISABLE · H1 · DISABLE — holding gold did better |
| High Tight Flag | structure | — / — (0) | — / — (0) | — (0, t —) | — (0) | — (0) | — (0) | — · — | DISABLE · INSUFFICIENT · INSUFFICIENT |
| Keltner Breakout | structure | +0.25 / -2.35 (86,860) | +0.48 / -2.83 (2,002) | +23.6 (169, t +1.8) | +29.4 (92) | -2.5 (115) | +18.5 (400) | +0.68 · +0.34 | DISABLE · H1 · DISABLE — holding gold did better |
| Opening Range Breakout | structure | +0.30 / -2.30 (173,039) | +0.25 / -3.06 (4,667) | +2.4 (177, t +0.2) | -2.6 (97) | — (0) | — (0) | — · — | DISABLE · REMOVE on Delta; DISABLE on MCX · INSUFFICIENT |
| Pivot R1/S1 Break | structure | +0.46 / -2.16 (7,362) | +1.36 / -1.95 (516) | +15.3 (271, t +1.9) | +15.2 (166) | +20.6 (206) | -7.1 (926) | -0.76 · -0.29 | DISABLE · H1 · DISABLE — holding gold did better |
| Pocket Pivot | structure | +1.87 / -1.07 (5,245) | -0.44 / -3.76 (266) | +23.3 (172, t +2.1) | -12.2 (91) | +28.6 (94) | +29.8 (240) | -0.21 · +0.21 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Prior Session High/Low Break | structure | +0.85 / -1.77 (25,308) | +0.49 / -2.82 (1,320) | +9.8 (290, t +1.0) | +1.4 (189) | +12.3 (207) | -2.1 (709) | -0.16 · +0.10 | DISABLE · H1 · DISABLE — holding gold did better |
| Round Number Break | structure | +0.04 / -2.56 (53,510) | -1.82 / -5.14 (1,599) | +7.3 (316, t +1.2) | +0.1 (193) | -9.1 (198) | +4.2 (631) | +0.39 · +0.13 | DISABLE · H1 · DISABLE — holding gold did better |
| TTM Squeeze | structure | -0.19 / -2.80 (10,414) | +0.03 / -3.28 (696) | +13.9 (87, t +0.9) | -22.9 (63) | +31.8 (34) | +56.5 (54) | +1.21 · +0.11 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| Trend Pullback to EMA | structure | -0.04 / -2.65 (42,519) | -0.18 / -3.49 (1,878) | +7.9 (146, t +0.6) | +11.1 (85) | -13.8 (87) | +3.0 (266) | -0.22 · +0.03 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| VCP 3-Contraction | structure | +0.94 / -2.15 (590) | -18.20 / -21.52 (21) | +84.4 (17, t +2.8) | -83.3 (5) | -195.4 (3) | +37.8 (38) | -0.05 · -0.14 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| VCP Breakout | structure | +1.52 / -1.50 (1,380) | -5.55 / -8.87 (64) | +73.5 (41, t +3.3) | -39.6 (11) | +152.1 (18) | +85.1 (102) | +1.31 · +0.19 | DISABLE · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| VCP Pivot Reclaim | structure | -0.99 / -4.05 (235) | +45.36 / +42.04 (12) | +58.2 (6, t +1.0) | +82.2 (3) | -255.1 (1) | +155.7 (21) | +2.31 · +0.48 | DISABLE (+ on < 100 trades or t < 2) · INSUFFICIENT · DISABLE — holding gold did better |
| VCP Tight Base | structure | +1.04 / -1.90 (1,271) | +6.15 / +2.84 (56) | +25.1 (39, t +1.2) | -64.3 (12) | +232.1 (7) | +75.1 (95) | +1.31 · +0.05 | DISABLE (+ on < 100 trades or t < 2) · 4h+ (regime, not H1) · DISABLE — holding gold did better |
| VCP Volume Dry-Up | structure | +0.81 / -2.22 (868) | +16.91 / +13.60 (34) | +55.5 (28, t +2.3) | -32.5 (10) | +183.1 (2) | +91.3 (91) | +1.44 · +0.16 | DISABLE (+ on < 100 trades or t < 2) · 4h+ (regime, not H1) · DISABLE — holding gold did better |

### 5.3 All 353 strategies

[`backend/research/gold_2026_10/gd_strategy_table_out.md`](backend/research/gold_2026_10/gd_strategy_table_out.md) lists every strategy on both venues — trades, gross, net, t, both halves, the confirming history and the mechanical decision (INSUFFICIENT < 30 trades · DISABLE-RAW gross ≤ 0 · DISABLE-COST net ≤ 0 · RESEARCH ONLY · CANDIDATE: both halves positive, net t ≥ 3, DSR ≥ 0.95, same sign on the confirming history). Delta: 81 DISABLE-RAW, 110 DISABLE-COST, 62 RESEARCH ONLY, 85 INSUFFICIENT, 15 STRUCTURAL, **0 CANDIDATE**. MCX: 92 DISABLE-RAW, 50 DISABLE-COST, 77 RESEARCH ONLY, 134 INSUFFICIENT, **0 CANDIDATE**. About half the RESEARCH ONLY rows are 4h and 1d strategies with a positive mean on tens of trades (33 of 62 on Delta, 28 of 77 on MCX) — the regime of §3.3, not separable from it one strategy at a time. The rest are 15m–1h strategies whose positive mean on 30–400 trades is what chance hands a few dozen of ~270 strategies when the pooled mean is negative: **no strategy below 4h reaches a net t of 2.2** on any history.


---

## 6. Root-cause analysis

Weak results were investigated before being judged. Four separate causes, in order of how much they explain:

1. **There is no edge before costs below about four hours — a property of the market, not of the code.** Gold is one of the deepest, most arbitraged markets there is: COMEX, London, MCX and the tokens are tied together by arbitrage, and the tokens are redeemable for the metal. On every one-minute-to-one-hour history here the catalogue's gross edge is within a couple of basis points of zero (Binance PAXG 15m +0.04 bp, MCX GOLDM 1m −0.30 bp — §3), while the cheapest honest round trip is 2.4 bp on Delta and 3.3 bp on MCX. The replay uses the desk's own `evaluate()` on honest fills, so this is not an implementation error, and no cost reduction rescues a gross edge of zero.
2. **What looks positive at four hours and above is gold's bull market.** Gold went 15× in 26 years and +78% over the COMEX-hours window. Longs earned +45 bp a trade and shorts lost −33 bp on the 26-year daily replay; on every rising history the long side carries the result, and on Delta's falling 2026 the short side did slightly better instead. Against the right benchmark — simply holding gold — **1 of 40 daily templates beats it**, and the same template loses money on the other four commodities the Lab tested. Excess over the trend is within noise everywhere (no strategy has a drift-adjusted *net* t above 3 on any history).
3. **The catalogue's shape works against this asset.** Every template exits at a fixed 2–5 ATR target or a 1–2 ATR stop: about two trades in three stop out, the targets cap the right tail that trend-following earns on (§7.2), and the stops sit inside ordinary noise at short horizons. Long-horizon edges in commodities come from letting winners run on many markets; this library does the reverse on one.
4. **The desk as built would measure something else, and its book could not express an edge if it had one.** Forming-bar signals (D1: 40–62% of its trades would be signals that vanish by the close, losing before costs), polled exits (D4), a cost guess 8–140× the market's (D5) and no funding (D6) would make the record an artefact of the plumbing. And the shared book hands its slots to whatever ticks fastest: in the replays the 1m/5m strategies (both books on their own venues' data) or the 1h strategies (the COMEX window) took essentially every slot, so the daily strategies — the only ones with a drift-positive record — never traded.

Two process causes sit under all four: the desk was ported from another app a week **before** the commodity desks' C0–C6 fixes and never received them, and it scores itself with a promotion gate (`_verdict`) that labels about 6% of zero-edge strategies "READY" (§3) — exactly the failure that gate was retired for on 5 October.

---

## 7. Research findings and benchmarks

### 7.1 Base rates

| Benchmark | Figure | Source |
|---|---|---|
| Holding gold, 2000–2026 (COMEX) | $274 → $4,216 (15×); Sharpe 0.68 full, **0.64 held-out** (2013-07 →) | `gd_benchmark.py` |
| Holding gold in rupees, 2016–2026 (the Lab's held-out) | Sharpe **0.76** (the five-commodity long basket: 0.77) | Commodity Lab run, 2026-10-05 |
| Holding gold over the replay windows | +77.9% (May 2024 → Oct 2026); −13% (Delta XAUT, Apr → Oct 2026); −1.8% (MCX 1m, Aug → Oct 2026) | bar files |
| Commodity Lab, every gold trial | TS12, TS3, MA 50/200, Donchian 50/20 on gold: **all REJECTED** — none beats always-long (best held-out Sharpe 0.566 vs 0.76, alpha t 0.64); the desk's daily templates as 5-commodity baskets: 0 of 45 pass | `commodity_lab_verdicts` (81 trials = 36 trend + 45 pattern baskets, 0 pass) |
| The desk's own "READY" gate under zero edge | ~6% of eligible strategies pass by luck | `gd_luck.py` |

### 7.2 Literature relevant to this desk

- **Technical rules and data snooping.** With hundreds of rules tried on one history, the best one's backtest is mostly selection; Sullivan, Timmermann & White (1999, *Journal of Finance* 54(5)) built the bootstrap test for exactly this. This study applies the Deflated Sharpe Ratio (Bailey & López de Prado 2014) and the Probability of Backtest Overfitting (Bailey, Borwein, López de Prado & Zhu 2017) instead — both used across this app's research.
- **Candlesticks.** Marshall, Young & Rose (2006, *Journal of Banking & Finance* 30(8):2303–2323) tested candlestick strategies on large US stocks; the authors' follow-up summarises the result as not generally profitable. The candlestick family here: net negative on every history below 4h (§3).
- **Trend-following in commodities works at the monthly horizon, diversified, letting winners run.** Szakmary, Shen & Sharma (2010, *JBF* 34(2):409–426): dual moving-average and channel rules on 28 commodity futures over 48 years earned positive mean excess returns net of costs in at least 22 of 28 markets, robust to data-mining adjustments. The Gold Desk's catalogue is the opposite design — short horizons, one asset, fixed 2–5 ATR targets that cut the right tail trend-following lives on. And on gold alone in rupees after carry, the Lab found plain holding beat every trend rule 2016–2026 — a fact about this asset's bull market, not a refutation of the paper.
- **What moves gold intraday.** Cai, Cheung & Wong (2001, *Journal of Futures Markets* 21(3):257–278): among 23 US macro releases, employment, GDP, CPI and personal income move COMEX gold most, and intraday patterns shape its volatility. Iwatsubo, Watkins & Xu (2018, *Journal of Commodity Markets* 11:59–71): informed trading dominates the New York session for gold futures, uninformed trading the Tokyo session. Both argue against reading the same template the same way at every hour — and the session cuts here (§3) find no hour in which the catalogue earns its costs.
- **Intraday momentum.** The first half-hour predicts the last for the S&P 500 (Gao, Han, Li & Zhou 2018, *Journal of Financial Economics*) and for Chinese metal futures (Jin, Kearney, Li & Yang 2020, *Journal of Futures Markets* 40(4):632–650); untested on gold — tested here (H-G1).
- **Perpetual futures.** He, Manela, Ross & von Wachter ("Fundamentals of Perpetual Futures", arXiv 2212.06888): a perpetual's fair price is proportional to spot, the constant set by interest rates and the funding mechanism; crypto perps deviate far more than currency markets. Delta's gold perps sit ~12 bp over their spot index with funding held at a constant +0.005 (§3) — funding is a cost the desk must charge.

### 7.3 Three gold-specific alternatives, each a single rule fixed before it was run

`gd_hypotheses.py`; costs are the measured round trip on the venue.

| Hypothesis | Rule | Result | Verdict |
|---|---|---|---|
| **H-G1 intraday momentum** | sign of the COMEX day session's first half hour (08:20–08:50 NY) → that side for its last half hour (13:00–13:30 NY) | Binance PAXG 2025–26 (455 days): predictive slope **+0.085, t +3.14** — the relation is real — but the sign rule earns **+0.13 bp gross** (t 0.15), **−2.47 bp net**; halves −0.37 / +0.64. Delta XAUT 2026: slope +0.02 (t 0.6), rule −0.33 bp gross; Delta PAXG: −0.88 bp gross. | **Reject.** A statistically visible relation that the simplest rule cannot monetise; a magnitude-conditioned version would be a new hypothesis needing data not yet seen. |
| **H-G2 session drift** | long 23:00–13:00 UTC (Asia + London), flat otherwise, vs holding all day | COMEX 1h 2024–26: rule − hold **−2.22 bp a day (t −0.59)**; PAXG 2025–26: −2.03 (t −0.47). Gold's return did lean away from New York hours (NY block −0.19 / −0.57 bp an hour, the late block +1.94 / +2.40) but the timing rule does not beat simply holding. | **Reject.** |
| **H-G3 XAUT/PAXG basis reversion (Delta)** | z of the token basis vs its trailing day; \|z\| ≥ 2 opens the pair, z = 0 or 48 h closes it | **317 pair trades** (Apr → Oct 2026): **+5.36 bp gross, +0.40 bp net** (t 2.05) after four legs of fees, 62% winners, median hold 4 h; halves +0.52 / +0.29. | **Real but too thin to build.** The basis does mean-revert — but by about what four taker fees cost; maker and taker rates are both 0.01% here, so there is no cheaper way in. Record only. |

### 7.4 The approaches the brief lists, against this desk

| Approach | Evidence here | Assessment |
|---|---|---|
| Momentum / trend-following | Lab: no gold trend rule beats holding (2004–2026, INR, carry); intraday breakouts (Donchian, Keltner, prior-session) gross ≈ 0 at 15m–1h; **at 4h the breakout / trend family is +12 to +16 bp net on all three histories** (§3.3) | Below 4h, no. At 4h, the one hypothesis worth a forward test (H1) |
| Breakout / volatility expansion | squeeze, TTM, ATR thrust, Donchian across all timeframes (§5) | One daily template beats holding gold on COMEX history (Bollinger Squeeze) and loses on the other four commodities — chance until shown otherwise |
| VWAP / volume confirmation | not in the catalogue; gold has no consolidated volume (MCX, COMEX and token volumes are different markets) | Low prior; not added |
| Mean reversion / range | candlestick reversals, %B, Fibonacci: net negative below 4h | No |
| Opening range / time of day | `opening_range` on MCX sessions: negative; session drift (H-G2): no improvement over holding | No |
| Regime detection / adaptive selection | every ex-ante cut negative after costs below 4h; on daily, "trade with the 50-day trend" is just being long a rising asset | An adaptive selector would be a trend rule — rejected by the Lab against holding |
| Liquidity and spread filters | measured costs are already small (Delta 2.4–2.6 bp, MCX 3.3 bp a round trip) | Spreads are not why it fails; the gross edge is |
| Volatility-adjusted sizing | no edge to size | Worth doing for risk comparability (I2), not for return |
| Portfolio exposure / correlated risk | every position is the same asset | Net-exposure caps (C5) |
| Execution / cost reduction | at zero spread every sub-4h cell stays negative; halving every cost lifts three of 24 to +0.05–0.26 bp on t ≤ 1.3 (§3.5) | Cannot rescue a gross edge this close to zero |

---

## 8. Prioritised upgrade plan

Confirmed defects are **C-items**, improvements **I-items**, experimental hypotheses **H-items**. Nothing here adds a strategy. The order matters: **no C-item makes the desk profitable** — they make its record true, which is the precondition for knowing anything from it.

### C1 · Closed bars only — Critical

- **Problem / evidence:** D1. As built, 40–62% of the desk's trades on 15m–1d would be signals that vanish by the bar's close, losing −2.6 to −20.1 bp before costs (§3.7).
- **Root cause / impact:** `gold_desk.load_bars` predates the shared store's `closed_only`; the Delta feed has no equivalent. The desk would trade signals no backtest can reproduce, so its record and any replay would disagree by construction.
- **Solution:** MCX — `mcx_load_bars(symbol, tf, limit=limit, closed_only=True, prefer_expiry=inst.get("expiry"))`, passing the contract from `scan_cycle`. Delta — a `closed_only` flag on `gold_delta_feed.load_bars` that drops trailing bars with `ts + tf > now` (and on the derived 45m). The "one decision per bar" key then refers to the last *closed* bar.
- **Files:** `gold_desk.py` (`load_bars`, `scan_cycle`), `gold_delta_feed.py` (`load_bars`, new `drop_forming`).
- **Steps:** (1) Delta `drop_forming` + test; (2) thread `inst` and `closed_only=True` through `gold_desk.load_bars`; (3) replay one stored day through `scan_cycle` with a fake clock; (4) compare its decisions with `gd_replay`'s closed-bar signals for that day.
- **Benefit / trade-off:** what the desk trades becomes reproducible. Entries move from mid-bar to ≤ 3 minutes after the close; fewer signals.
- **Dependencies / complexity:** none; low.
- **Edge cases:** the MCX session's last bar (ends at the close, not at ts + tf — `commodity_bars.bar_end` handles it); Delta's daily bar closes at 00:00 UTC; 1m bars under a 3-minute scan (moot once I1 retires 1m/5m).
- **Tests / acceptance:** §12 C1 — 100% of decisions match a closed-bar signal of the same bar and side.

### C2 · Own contract, roll exits, settlement — Critical (MCX)

- **Problem / evidence:** D2 — a roll books the calendar spread (+0.87% Nov → Dec) as P&L; nothing leaves the delivery window.
- **Root cause:** the Gold Desk reads `uni.get(symbol)` (the new entry contract) where the commodity desks now read `mcx_market.position_contract(pos)`.
- **Solution:** in `manage_cycle` and `close_all`, price every position on its **own** contract through `mcx_market.quotes([position_contract(pos)])` (fresh quotes only); call `mcx_market.forced_exit(pos)` first — `roll_exit` closes at the own contract's quote, `contract_expired` settles at `commodity_bars.last_contract_price(symbol, expiry)`; stamp `angel_token` and `expiry` on every position at entry.
- **Files:** `gold_desk.py` (`_open`, `mark`, `manage_cycle`, `close_all`).
- **Steps:** (1) stamp the contract; (2) own-contract pricing; (3) forced exits; (4) a roll-day test on the stored GOLDM Oct → Nov contracts.
- **Benefit / trade-off:** no phantom roll P&L; positions are never carried into tender days. A strategy's position is cut at the roll even if its signal is still alive (a new signal can re-enter on the new contract).
- **Edge cases:** no fresh quote on the old contract inside the window → retry each cycle, labelled; expired with no stored bar → `void`, never an invented price.
- **Tests / acceptance:** §12 C2 — 0 positions marked on another contract; 0 open inside a tender window.

### C3 · Honest fills and costs — Critical

- **Problem / evidence:** D3 (frozen quotes), D4 (polled exits — targets booked 3.4–5.4 bp past their level), D5 (5 bp guess vs 0.04–0.64 bp measured), D6 (no funding), D7 (zero fee on a missing spec).
- **Root cause:** the desk was ported with its source's execution model; the shared fixes (fresh quotes, touch fills, bar-walked exits) landed after it.
- **Solution:** (a) **exits** walk the one-minute bars since `checked_through` — stop-first, levels as limit/stop orders, gap opens at the open — using the Intraday desk's tested scanner (`intraday_fills.scan_exit`, already shared) on the gold stores; quotes only as a labelled fallback. (b) **entries** fill at the touch — MCX `McxQuote.touch(side)` on a fresh quote; Delta the best bid/ask (or an L2 walk for the order size) — and record the spread at fill; `slippage_bps` becomes a monitored *floor*, not a cost. (c) **funding** accrues per 4-hourly exchange from the venue's `FUNDING:<sym>` series × notional × side; stored as `funding_paid`, included in net. (d) **fees fail closed:** no taker rate on the product spec → no trade, and the spec is refreshed daily.
- **Files:** `gold_desk.py` (`_open`, `_close`, `manage_cycle`, `_charges`, `Venue`), `gold_delta_feed.py` (quotes, funding series, product refresh).
- **Steps:** (1) exits (largest effect); (2) touch fills + spread capture; (3) funding; (4) fail-closed fees; (5) tests per item.
- **Benefit / trade-off:** the record's costs become the market's; reported targets stop beating their levels. More code paths (bars, quotes, funding) — each needs a labelled fallback.
- **Edge cases:** a gap through both levels in one minute (stop, at the open); a bar store gap (quote fallback, labelled `exit_basis`); funding on a position opened and closed inside one interval (none owed).
- **Tests / acceptance:** §12 C3.

### C4 · Count the hold in bars — Medium

D8. Count the strategy's own closed bars since entry from the store, not wall-clock minutes from the signal bar's start. Files: `gold_desk.manage_cycle`. Acceptance: a 1h MCX position exits after 60 session bars.

### C5 · Exposure that a real account could hold — High

- **Problem:** D9, D15 — offsetting positions on one contract, 2× notional on the MCX book, two tokens of one ounce, a 1 kg contract that can never trade.
- **Solution:** refuse an entry opposite to an open position on the same contract (a real account would net it); cap net lots per contract (MCX: 2 GOLDM lots) and aggregate notional at the book's capital; on Delta trade one token per strategy (XAUTUSD: tighter book — 0.036 vs 0.12 bp a side — and ~2.7× PAXGUSD's monthly volume, $7.8 bn vs $2.9 bn); drop GOLD from the MCX symbol list.
- **Files:** `gold_desk.py` (`VENUES`, `_open`, `_sizing`). **Complexity:** low. **Trade-off:** fewer positions; the book measures fewer, more realistic bets.
- **Acceptance:** §12 C5.

### C6 · A breaker that sees every position — Medium

D10. Store the equity at the first cycle of each day (IST for MCX, UTC for Delta); the breaker trips when equity falls 3% below it, every position marked. Files: `gold_desk.today_pnl`, `scan_cycle`.

### C7 · Stop writing when there is nothing to write — High (operational)

- **Problem:** D11 — ~17,000 candle rewrites every 2 minutes (~12 million a day) and 7,127 flat equity rows for a desk that has never traded.
- **Solution:** the Delta bar loop runs only while the Delta book is enabled (or every 30 minutes to keep coverage warm); each pass fetches and upserts only the last few bars per interval and never re-sets `updated_at` on an unchanged candle; a daily prune keeps `KEEP_BARS` per (symbol, interval); `run_cycle` writes an equity row only when the book is enabled and its equity or open positions changed.
- **Files:** `gold_delta_feed.py` (`refresh_symbol`, `FETCH_DAYS`, a prune), `gold_scheduler.py` (switch check), `gold_desk.run_cycle`.
- **Acceptance:** §12 C7 — ≤ 50 candle writes a pass while enabled, none while off; a bounded store.

### C8 · Records, not verdicts — High

- **Problem:** D13, D12 — a "Worth real money?" column on a gate that promotes luck (§3), and a Main Control switch that strands stops.
- **Solution:** replace `_verdict` with the commodity desk's `_record_status` (a strategy here has a *record*; the only door to money is the Commodity Lab); rename the column; fix the CSS and the stale copy (margin is broker-measured; costs come from the market); in `gold_scheduler`, `manage_cycle` runs whenever positions are open, Main Control gating entries only — or Main Control "off" closes everything explicitly, never silently.
- **Files:** `gold_desk.strategies`, `gold_scheduler.py`, `frontend/app/gold-desk/page.tsx`, `frontend/lib/api.ts` (types).
- **Acceptance:** §12 C8 — 0 READY labels; stops managed with Main Control off.

### C9 · Delta catalogue hygiene — Medium

D14. Exclude `gap_fade` and `opening_range` on Delta (no session); do not evaluate on weekend bars (no reference market; median 1-minute range 0.07 bp), still managing open positions. Files: `gold_desk.scan_cycle`.

### C10 · Tests that run and cover — Low

D17. Put `shared/` on the path as the newer suites do; add the C1–C9 cases (§12).

### I1 · Retire every timeframe below 4h — High

- **Problem / evidence:** §3.2 — 24 of 24 (timeframe × history) cells negative after costs; the venue fee alone exceeds the gross edge in every cell; 0 of 46 templates survive; in the book these strategies take every slot and drive both books to the floor (§3.6).
- **Solution:** a `RETIRED_TIMEFRAMES` set (`1m,5m,15m,30m,45m,1h`) in `gold_desk.scan_cycle`, exactly as `commodity_engine` retired 1m/5m on 2026-10-05: no new entries, open positions run to their own exits, records stay; strategy ids are untouched (they are positional).
- **Benefit / trade-off:** 262 of 353 strategies stop trading. In replay, the same books with only 4h and 1d would have made **+37.7%** (Delta-like, Binance PAXG 2025–26, max drawdown 6.3%), **+0.7%** (Delta XAUT, Apr → Oct 2026) and **+41.9%** (MCX, COMEX hours 2024–26, max drawdown 28.5%) — profitable, but **behind simply holding gold** in the rising windows (+53.3%, +78.1%), and with **no significant alpha against gold** (t 1.62, 0.32, 0.91; beta 0.20, 0.17, −0.02).
- **Acceptance:** no entry below 4h after the change; slots used only by 4h / 1d.

### I2 · Size by risk, on contracts small enough to do it — Medium

D16. Risk 0.25–0.5% of equity per trade at the stop; on MCX that needs GOLDPETAL (1 g; measured spread 1.33 bp, 7–10 lots at the touch) or GOLDTEN (10 g; 2.19 bp) instead of GOLD; Delta's 0.001 oz contracts already allow it. Files: `gold_desk._sizing`, `VENUES`. Acceptance: realised risk per trade within ±25% of the target across timeframes.

### I3 · The MCX premium, live — Low

D18. Read USD/INR from a live source (the NSE currency future on Angel, or the existing Yahoo feed, labelled with its time) instead of an unset environment variable. Measured premium today: +15.1%.

### I4 · The Commodity Lab is the only door — High

A strategy on this desk has a record, not a verdict. Any gold idea reaches money only through `commodity_lab` — deflated over every trial ever registered (this study alone tested ~1,000 strategy-history pairs on gold, so a future gold candidate's bar starts there), PBO ≤ 0.5, positive in both periods, **beating always-long gold**, then ≥ 60 sessions of incubation on real fills.

### I5 · Cost monitors — Medium

Keep `mcx_quote_log`; make the Delta order-book sampler a permanent low-rate job (one sample every 5 minutes, public endpoint, no keys); publish monthly spread and funding distributions; alert when either moves by more than 2× its median. The desk's slippage setting becomes a floor equal to the measured median half-spread.

### H1 · The 4h breakout / trend-structure family, forward, pre-registered — the one experiment

- **Why this and nothing else:** it is the only effect in this study with the same sign on every history that can show it (+16.2, +12.2, +12.0 bp a trade net at 4h on Binance PAXG, Delta 2026, COMEX hours), with a known mechanism (short-horizon trend-following; Szakmary, Shen & Sharma 2010 for the long-horizon version) — and Delta is the cheapest place to trade it (2.4 bp a round trip).
- **Why it may fail:** it was found in this data, so history cannot confirm it; 2024–26 was an unusually trending gold market; no single 4h strategy survives deflation; the 4h+1d books' alpha against gold is not significant (t ≤ 1.6).
- **Rule, frozen before the first sample:** the nine breakout / trend-structure templates (Donchian 20 and 55, Keltner, prior-session break, round-number break, pivot R1/S1, HH/HL shift, ATR thrust, EMA ribbon) at **4h on Delta XAUTUSD only**; closed bars (C1); fills at the touch for the order size (C3); exits walked on 1m bars; the templates' own ATR target and stop and 60-bar hold; costs = venue fee + measured spread + funding accrued; one position per template; risk-based size (I2); net exposure ≤ 100% of equity (C5); paper only.
- **Decision, frozen:** at **104 weeks**: GO (to the Lab gate) only if pooled net > 0 **and** weekly t ≥ 2 **and** weekly alpha against XAUT itself t ≥ 2; otherwise NO-GO. **Futility at 52 weeks:** stop if pooled net ≤ 0 or weekly t ≤ −1. Stored with a fingerprint before the first sample, as the Intraday H1 was; never re-tuned.
- **Power, stated up front:** at the replay's own edge (+10 to +14 bp a trade, ~18.5 trades a week), the expected weekly t is **1.5 after one year and 2.1 after two**; at half that edge, 0.7 and 1.0. A NO-GO is the likely outcome even if a small edge exists; a GO would mean something.
- **Prerequisites:** C1–C3, C5, C8, I1, I2. **Cost:** the desk running one venue, one symbol, nine strategies.

### H-items not recommended

| Hypothesis | Status | Why |
|---|---|---|
| Bollinger Squeeze 1d on gold | RESEARCH ONLY — no capital, no incubation | beats holding gold on 26 years of COMEX (alpha t 2.37) and loses on the Lab's five-commodity run (alpha t −1.3); four trades a year → ~7 years to test forward |
| H-G3 XAUT/PAXG basis reversion | RECORD ONLY — not built | real mean reversion (+5.4 bp gross) eaten by four taker fees (net +0.4 bp); maker fees are the same 0.01%, so there is no cheaper route |
| Event filter (no entries before US employment / CPI / GDP releases) | only as a pre-registered add-on to H1, never alone | gold's largest moves cluster on those releases (Cai, Cheung & Wong 2001); needs an events calendar |
| H-G1 intraday momentum, H-G2 session drift | REJECTED | pre-registered rules lose after costs (−2.5 bp) / do not beat holding (−2.0 bp a day) |

---

## 9. Backtesting and validation methodology

**What was replayed.** The desk's own catalogue through its own `commodity_patterns.evaluate()`, imported, not reimplemented — 353 strategies on six histories — on a window of the last 250 bars (the desk loads `max(need, 250)`), skipping any series under 65 bars as the desk does.

**How bars were built** (`gd_data.py`, `gd_replay.py build`), exactly as the live stores build them: 24/7 venues in buckets anchored to UTC midnight, the day being the UTC day (`gold_delta_feed.resample`); MCX only inside the session, buckets anchored to 09:00 IST, the day being the IST trading date, 4h built from 1h (`commodity_bars.resample`); MCX contracts joined newest-first with a ratio adjustment at the overlap (`commodity_bars._continuous`, logic copied). The last, still-forming bar of every series is dropped.

**No look-ahead.** A signal at bar *i* uses bars up to and including *i*, which has closed; it fills at the first one-minute open after bar *i* closes (MCX: the next session minute, so a signal at the close fills at the next morning's open). Target and stop are scaled by fill ÷ signal close, as `_open` does. Regime labels use the previous day's reading. Pivots need `right` bars after them by construction, so an unconfirmed swing is never a pivot.

**Exits** walk one-minute bars: a level touched inside a minute fills at the level; a minute that *opens* beyond a level fills at that open (worse for a stop, better for a resting target); a minute touching both is a stop. The hold limit is the close of the 60th bar of the strategy's own timeframe. The COMEX-hours and daily replays resolve exits on their own hourly or daily bars, stop-first. The desk *as built* (D4: one look every 3 minutes at the latest close, fill at that price, hold counted on the wall clock) is recorded beside every honest exit so the defect can be sized.

**Position rule.** One position per (template, timeframe, symbol); the next signal is acted on only if the previous trade has exited when the signal bar closes. The book simulation (`gd_book.py`) adds the desk's slots, scan order, sizing, margin and breakers.

**Costs**, in bp of notional per round trip:

| | Gross | As the desk charges | Measured |
|---|---|---|---|
| Delta | 0 | 10 (slippage) + 2.36 (fee 0.01% × 1.18 a side) | 2.36 fee + spread (XAUT 0.07, PAXG 0.24) + funding (longs pay 1.5 bp a day; high case 3.0) |
| MCX | 0 | 10 (slippage) + 2.03 (₹305 a GOLDM lot) | 2.03 + 1.28 quoted spread |

**Statistics.** Per strategy: trades, win rate, average win and loss, mean gross and net bp, profit factor, per-trade t, drawdown; the first half of each history against the second (fixed split dates, chosen before results); the Deflated Sharpe Ratio (Bailey & López de Prado 2014) with the number of strategies tested as the trial count; the Probability of Backtest Overfitting by combinatorially symmetric cross-validation over weekly returns (Bailey, Borwein, López de Prado & Zhu 2017, 10 blocks, 252 splits). Pooled figures are tested on **weekly sums**, because trades overlap and share bars — a per-trade t over 400,000 overlapping trades overstates certainty by an order of magnitude. Regime cuts are ex-ante only: trend (close vs its 50-day mean, yesterday), volatility (20-day realised, tercile, yesterday), session, weekday/weekend, holding time.

**What the replay cannot see.** Queue position and partial fills (irrelevant at one GOLDM lot or a $1,667 slot against the measured depth); exchange outages; MCX daily price bands on a limit day (a stop cannot fill while the market is locked — no such day appears in the MCX sample); the rupee leg on the COMEX proxy.

**Reproducibility.** Every figure in §3 and §5 is reproduced by the scripts in `backend/research/gold_2026_10/` from the fetched data within rounding; the run order is in its README.

---

## 10. Risk management and capital protection

The desk is paper-only and has no order path to any broker or exchange. Its risk controls therefore protect the *record* — what the book says would have happened — and, if the desk were ever pointed at real money, they would be the first line of defence. Measured against the brief's list:

| Safeguard | Today | Gap | Recommendation |
|---|---|---|---|
| Max risk per trade | none — size is one lot / one equal slot whatever the stop (D16) | risk per trade varies ~100× across timeframes | size by stop distance: `units = floor(r × equity / (stop distance × unit value))`, r = 0.25–0.5% of equity; on MCX that needs small contracts (GOLDPETAL 1 g, GOLDTEN 10 g), since one GOLDM lot is ₹15 lakh |
| Max loss per day | 3% of capital, entries only (`scan_cycle`) | undercounts losses on positions opened earlier (D10) | measure the day against the equity at the session's start (store it), all positions marked |
| Drawdown limit | book floor at 50% of capital, entries only | 50% is a ruin threshold, not a limit; nothing between 3%-a-day and −50% | add a running drawdown limit (e.g. −10% from the equity peak → entries stop, review) |
| Volatility-adjusted sizing | none | ATR-scaled levels with fixed size = risk follows volatility | follows from risk-per-trade sizing |
| Concurrent positions / correlated exposure | 4 / 6 slots; no net-position limit; opposite positions on one contract allowed (D9); two tokens of one ounce (D15) | the book is one asset — every position is the same bet or its opposite | cap **net** exposure per venue (|net lots| ≤ N, aggregate notional ≤ capital); refuse an entry that offsets an open position on the same contract; one token per strategy |
| Liquidity / spread | none | — | refuse a fill when the quoted spread exceeds 3× its 30-day median (`mcx_quote_log`; the Delta sampler) or the book holds less than the order at the touch |
| Gap, sudden volatility, circuit limits | MCX positions are held through nights and weekends; a stop gaps at the next open (the replay charges that); MCX applies daily price bands to bullion, widened in steps, and a stop cannot fill while the market is locked at a band | no handling of a locked market | treat an untraded level on a band day as unfilled and keep the position at risk (the record must say so); no new entries within 30 minutes of scheduled US releases — gold's largest moves cluster on employment, GDP and CPI releases (Cai, Cheung & Wong 2001) — as a hypothesis to test, not a rule to assume |
| Duplicate orders / idempotency | paper; one position per (template, timeframe, symbol); "one decision per bar" key | the decision key is the *forming* bar (D1) | key on the closed bar; if an order path is ever added, a client order id derived from (strategy, closed bar) |
| Partial fills, rejections, API failures, delayed data | Delta: retried public GETs; MCX: an LTP with no freshness check (D3) | a frozen quote can fill | fill only on `mcx_market.quotes(...).fresh`; on Delta refuse a mark older than 2 minutes |
| Stop execution / emergency close | stops evaluated every 180 s on one price (D4); `close_all` falls back to a stored price | overshoot booked; a stale fallback can close at a price that no longer exists | exits walked over bars since the last check; `close_all` refuses a stale mark |
| Capital / margin / exposure reconciliation | MCX margin at the measured 9.2%; Delta 1x | — | when there is a record, a nightly check that open positions, the store and the page agree |
| Session boundaries / end-of-day | MCX calendar gates the MCX loop; no roll exits (D2) | positions can drift into the tender days | `mcx_market.forced_exit` in `manage_cycle`, at the position's own contract |
| Kill switches / recovery | desk switch per venue (entries); Main Control (everything, including stops — D12); breakers; positions live in Mongo, so a restart resumes them | Main Control off strands stops | Main Control gates entries only, or closes everything deliberately — never silently leaves stops unwatched |

**Can the controls be bypassed?** Three ways today: the forming-bar decision key lets the "one decision per bar" guard pass a signal a closed bar would never have produced (D1); a missing venue fee becomes a zero cost rather than a refusal (D7); and Main Control can stop risk management rather than risk-taking (D12). Retries are not a bypass on the paper desk (no orders), and a stale signal cannot re-fire on the same closed bar once D1 is fixed.

---

## 11. Phased roadmap

| Phase | Work | Status | Deliverable | Go / no-go |
|---|---|---|---|---|
| 1 · Code audit | map, trace, baseline | **done** (this document) | §2, §4 | — |
| 2 · Data and backtest audit | data fitness, closed-bar replay, cost measurement | **done** | §3, §9, `gd_quality.py`, `gd_replay.py` | — |
| 3 · Critical fixes | **C7 first** (it costs the shared database every day the desk exists, on or off); then C1, C2, C3, C5, C8 before the switch is ever flipped; C4, C6, C9, C10 after | to do | tests green (§12) | **No-go for switching either book on until C1–C3, C5 and C8 pass** — otherwise the first record would measure the plumbing |
| 4 · Strategy research | I1 (retire sub-4h); H-items only by pre-registration | to do | pre-registered protocols | a hypothesis enters only with its rule, data and decision written down first (`commodity_hypotheses` style) |
| 5 · Independent validation | the Commodity Lab's gate, gold included as its own series | machinery exists | a Lab run that counts every gold trial | DSR ≥ 0.95 over every trial ever registered, PBO ≤ 0.5, positive in both periods, **beats always-long** (held-out Sharpe and alpha t ≥ 2) |
| 6 · Paper incubation | Pre-Live Commodity desk (it admits only Lab INCUBATING/CONFIRMED) | machinery exists | CONFIRMED / REJECTED_IN_INCUBATION | ≥ 60 MCX sessions, positive P&L on real fills |
| 7 · Controlled real money | `mcx_live_executor` — locked (CONFIRMED + `MCX_LIVE_ENABLED` + phrase + `DRY_RUN=0` + verified quantity unit) | blocked — nothing to arm | — | a CONFIRMED verdict; Delta has no order path and should not get one without the same chain |
| 8 · Continuous improvement | cost monitors (`mcx_quote_log`, the Delta sampler), drift between record and replay | partly exists | monthly cost report | a cost distribution that shifts by > 2× its median, or a record/replay gap > 1 bp a trade, is investigated before any number is quoted |

**The likely outcome, stated plainly:** Phases 5–7 have nothing to work on today. The honest end states are (a) a switched-off desk that stops writing to the database, or (b) a correctly instrumented research record whose expected result, on this evidence, is a slow loss.

---

## 12. Required tests and acceptance criteria

| Item | Unit | Integration / regression | Quantitative acceptance |
|---|---|---|---|
| C1 closed bars | a pattern that fires on a partial bar and not on the closed one opens nothing; the decision key is the closed bar | one simulated day per venue against the replay's closed-bar signals | 100% of the desk's decisions match a closed-bar signal of the same bar and side |
| C2 own contract + roll exit | a November position is marked on November's token after the universe rolls to December; `forced_exit` closes it inside the window at its own price; an expired contract settles at its last stored close | roll day replay on the stored GOLDM Oct→Nov contracts | 0 positions marked on another contract; 0 positions open inside a tender window |
| C3 fills and costs | target fills at the target (open if gapped past); stop-first in one bar; no fill on a stale or one-sided quote; Delta funding accrues for every funding exchange a position is open across; a missing fee refuses the trade | replay the polled vs honest models on the stored bars | 0 target exits beyond the target; funding on 100% of Delta closes; 0 trades with a zero fee |
| C4 bar-count hold | a 1h MCX position exits after 60 session bars, not 60 wall-clock hours | — | hold in bars == 60 at the limit on both venues |
| C5 exposure | an opposite entry on a held contract is refused; aggregate notional ≤ capital; one token per strategy | 200 simultaneous signals | max net lots per contract ≤ cap; 0 offsetting pairs |
| C6 breaker | day P&L includes positions opened earlier | multi-day position losing on day 2 | breaker trips at −3% measured from the day's opening equity |
| C7 write load | the bar loop is idle while the desk is off; a pass rewrites only bars that changed; equity is written only when enabled or changed | production metrics for 24 h | ≤ 50 candle writes per pass; 0 equity rows while off; candle store bounded |
| C8 record, not verdict | strategies carry RECORD status, never READY; `manage_cycle` runs with Main Control off while positions are open | page snapshot; a switch-off with an open position | no "Worth real money?" column; 0 READY labels; stops managed while off |
| C9 Delta hygiene | no `gap_fade` / `opening_range` signal on Delta; no evaluation on Saturday/Sunday UTC bars | one replayed week | 0 session-template or weekend entries |
| C10 tests | the suite imports with the default interpreter | CI run | all suites green without a custom `PYTHONPATH` |
| I1 retire < 4h | no entry below 4h; open positions run to their exits | one simulated day | slots used only by 4h / 1d |
| I2 risk sizing | units from stop distance; whole contracts | a 4h and a 1d signal on the same book | realised risk per trade within ±25% of target |
| H1 | pre-registration stored (fingerprinted) before the first sample; the decision function evaluates exactly the frozen rule | — | the pre-registered GO / NO-GO at 104 weeks (futility at 52), nothing else |

Every number in §3 and §5 should be reproducible from `backend/research/gold_2026_10/` within rounding; a change to the fill or cost model that moves them is a regression to explain, not to accept.

---

## 13. Expected benefits, trade-offs and unresolved risks

**Benefits.** Truth first: any number this desk publishes would describe the market rather than its plumbing (C1–C4), and the page would stop labelling luck as "worth real money" (C8). Operationally, C7 removes ~12 million writes a day (~140 a second, around the clock) from the shared database for a desk that has never traded, and bounds a collection that grows ~3,000 documents a day. I1 removes the churn that sends both books to their floor within weeks.

**What profitability to expect — the replay's own numbers, not a forecast:**

| If the desk ran… | It would have made | Holding gold over the same window | Alpha against gold |
|---|---|---|---|
| as built, all timeframes (either venue) | **−50%, floor in ~3–5 weeks** | −13% to +78% | — |
| 4h + 1d only, Delta-like, 2025-01 → 2026-10 | +37.7% (max DD 6.3%) | +53.3% | +16%/yr, t 1.62 |
| 4h + 1d only, Delta XAUT, 2026-04 → 10 | +0.7% (max DD 6.4%) | −9.3% | +5%/yr, t 0.32 |
| 4h + 1d only, MCX, 2024-06 → 2026-10 | +41.9% (max DD 28.5%) | +78.1% | +18%/yr, t 0.91 |

The best honest reading: retiring sub-4h turns a desk that destroys its book into one that, in a strongly trending two years, made money with low correlation to gold but less than holding gold, with alpha that is not yet distinguishable from luck. Anyone hoping this desk becomes an income source should weigh that before investing more build time.

**Trade-offs.** C1–C8 are real work (an estimate: one to two weeks), and the corrected desk will look worse than nothing at all — it has no trades today. I1 retires 74% of the catalogue. H1 takes two years to answer and will most likely answer "no".

**Unresolved risks.**
- Delta's funding period is undocumented (5.5% or 11% a year paid by longs — both reported; neither changes a sign below 4h).
- Delta's weekday spreads: the sampler runs to 2026-10-13; the weekend figures (0.036 / 0.12 bp a side) are an order of magnitude below the fee — even a 20× widening would add under 1.5 bp to an XAUT round trip and change no conclusion here.
- The 2024–26 regime: four of six histories sit inside it; the 4h result may be that regime and nothing else.
- MCX intraday history is 2–3 months; MCX below 1h is judged mostly on international proxies that explain MCX poorly at a minute (correlation 0.62).
- A replay cannot see exchange outages or price-band lock days.

---

## 14. Final decisions

| Component | Decision | Why |
|---|---|---|
| Both books (MCX, Delta) | **KEEP OFF.** Recommended: **RETIRE** the desk's loops unless H1 is wanted | no strategy has a demonstrated edge; as built, both books reach their floor in weeks |
| Delta bar poller + equity sampler | **FIX now** (C7) — or stop them with the books | ~12 million writes a day for a desk that is off |
| 262 strategies below 4h (1m–1h, all 46 templates) | **DISABLE** (I1) | gross ≈ 0; the venue fee alone exceeds it in every cell; 24 of 24 cells negative after costs |
| 9 breakout / trend-structure strategies at 4h | **RESEARCH ONLY — as one pooled hypothesis** (H1, on Delta XAUTUSD), never one at a time | same sign on every history (+16.2 / +12.2 / +12.0 bp), significant on one; no single strategy survives deflation; alpha against gold t ≤ 1.6 |
| the other 37 strategies at 4h | **DISABLE** | 21 are positive at 4h on Binance PAXG — the same regime, with no standing on their own; the rest negative or too few trades |
| 45 strategies at 1d | **DISABLE** | 39 lose to holding gold; 6 have too few trades |
| Bollinger Squeeze 1d | **RESEARCH ONLY** — no capital, no incubation | beats holding gold on COMEX, loses on the Lab's five commodities; four trades a year |
| `gap_fade`, `opening_range` on Delta | **REMOVE** | no session on a 24/7 market |
| GOLD (1 kg) on MCX; PAXGUSD on Delta | **REMOVE** | GOLD can never be sized on the book; PAXG duplicates XAUT at a wider spread |
| "Worth real money?" / READY | **REPLACE** with RECORD (C8) | the gate passes 3–6% of zero-edge strategies |
| Execution and cost model | **FIX** (C1–C4) before either book is switched on | forming bars, polled exits, guessed costs, no funding, wrong contract after a roll |
| Exposure rules | **FIX** (C5, C6) | offsetting positions 31–45% of the time; 2× notional; a breaker blind to older positions |
| H-G1 intraday momentum · H-G2 session drift | **REJECTED** | pre-registered rules lose after costs / do not beat holding |
| H-G3 XAUT/PAXG basis | **RECORD ONLY**, not built | +0.4 bp net — the fees take the edge |
| Commodity Lab | **KEEP** as the only door to money; count gold-only trials | it already rejected every gold trend rule against holding |
| Holding gold | the benchmark | it beat 39 of 40 daily templates; any gold strategy here must clear it |

---

## Appendix — reproduction

All database reads are read-only and run inside the backend image (`docker exec -e PYTHONPATH=/app/backend alpha-engine-backend-1 python <script>`); the replays run locally on public data and an export of the MCX bar store. See [`backend/research/gold_2026_10/README.md`](backend/research/gold_2026_10/README.md) for what each script settles and the run order. Data lands in `backend/research/gold_2026_10/data/` and is not committed.
