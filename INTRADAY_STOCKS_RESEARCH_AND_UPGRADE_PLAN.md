# Intraday Stocks — Research, Profitability Validation & Upgrade Plan

**Date:** 2026-10-10 · **Scope:** every book on `/intraday-stocks`, plus the real-money Live Trading desk that mirrors one of them · **Status:** research complete — this document changes no code.

Every figure below was measured on the production database or on the stored two-year walk-forward backtest on 2026-10-10. The scripts that produce each one are in [`backend/research/intraday_2026_10/`](backend/research/intraday_2026_10/README.md). Measured results, assumptions, and hypotheses are labelled as such.

---

## 0. Executive summary

**Verdict: no strategy in this module has a demonstrated, tradeable edge after realistic costs.** The rigorous part of the module — the 54-strategy tournament and its walk-forward gate — is built correctly and says so plainly. Two other parts of the module report profits that are artifacts of how they fill trades, and the real-money desk traded on unvalidated strategies with a ledger that does not record its costs.

The five findings that matter:

1. **The tournament loses money every way it can be cut.** Over two years (495 sessions, 153,403 simulated trades on a point-in-time universe of the 200 most-traded names) the catalog lost **₹11.51 crore — 42.6% of its ₹27 crore paper book — with 0 of 25 months positive.** Bull, bear and sideways markets; high and low volatility; long and short; every hour of the day: negative. **0 of 52** replayable strategies is net-positive. Only 5 are positive even before fees.
2. **There is a real signal, and it is smaller than the cost of trading it.** Before any friction the average trade made **+1.67 bp**; modelled slippage cost 5.17 bp and Angel's charges 4.02 bp. Six strategies have a raw edge that clears the multiple-testing bar (t > 3.31), but the best, `donchian_45m`, captures 7.48 bp against about 9 bp of friction. For three of them, profitability reduces to one measurable number: **real slippage on a ₹10 lakh order** (break-even 1.29–1.80 bp a side).
3. **The Patterns tab's +₹52.9 lakh is not real.** That engine closes each trade at whatever price it sees on its next polling cycle, so price that ran *past* a target is booked as profit; it also charges no slippage. Filling targets at the target, as a limit order would, leaves **+₹19,035**; adding the tournament's own slippage gives **−₹23.1 lakh**. It has no per-symbol cap — 88% of its trades duplicate another strategy's bet, and one idea was taken by 32 strategies at once (₹3.18 crore on a single trade) — and no backtest or promotion gate of any kind. The ₹50k and ₹2 lakh Paper Trade books copy its fills.
4. **Real money was traded on unvalidated strategies, and the ledger is wrong.** Live Trading placed **78 real Angel orders** between 10 and 20 August. It recorded −₹799 with **no charges at all**. **49 of the 78** positions were closed by Angel's MIS auto-square-off after the desk missed its own close, and were then booked at the price the desk saw when it next ran — the *following* session — instead of the broker's square-off price on the day. The desk is disarmed now. The eight strategies it trades are about four ideas from the retired first catalog, seven of them swing rules forced into same-day square-off, and the record they were chosen on was destroyed in the 5 October reset.
5. **The backend is swap-thrashing** — 91.6% of its 800 MB cap, 113,603 major page faults — and the Patterns candle cache is bounded by entry count rather than by bars, so it can regrow to the size that caused the last incident.

**Do, in order:** keep Live Trading disarmed and make arming require a confirmed incubation verdict (C4); fix or switch off the Patterns desk (C1, C2); correct the real-money ledger from Angel's contract notes (C3); then run **one** experiment that could change the verdict — measure real execution cost for the three strategies whose break-even slippage exceeds 1.2 bp a side (H1). Stop paper-trading the 42 strategies whose edge cannot cover fees even at zero slippage (I1).

**Do not:** add indicators, patterns or timeframes (each one raises the bar every survivor must clear); re-tune parameters on this history (the low overfitting score exists because nothing was tuned); trade the catalog backwards (the mirrored book loses 10.86 bp a trade — costs are paid in both directions); or treat "trades held 2–4 hours made money" as a rule (holding time is decided by the outcome, not before it).

---

## 1. Scope, evidence and limits

| Evidence | Source | Size | Used for |
|---|---|---|---|
| Tournament, live paper | `intraday_lab_trades`, `intraday_lab_positions`, `intraday_lab_scores` | 1,596 trades, 4 sessions (6–9 Oct 2026) | costs, fill realism, liquidity, concentration |
| Tournament, walk-forward | `/data/intraday/backtests/v2-20261010-0605-trades.jsonl.gz` + `intraday_v2_backtests` | 153,403 trades, 495 sessions (10 Oct 2024 – 9 Oct 2026), 213 symbols | profitability, regimes, sensitivity, decisions |
| Patterns | `pattern_positions` | 3,913 trades, 4 sessions | fill defect, concentration |
| Paper Trade ₹50k / ₹2 lakh | `pattern_book_positions`, `pattern_book_trades` | 416 trades | inherited fills, missing fields |
| Live Intraday ₹80k / ₹30k / ₹10k | `live_intraday_trades` | 99 trades, 4 sessions | shortlist audit |
| Live Trading (real money) | `live_trading_state`, `_flags`, `_positions`, `_trades` | 78 real round trips, 10–20 Aug 2026 | ledger, reconciliation, arming |
| NIFTY daily | `bars` (NIFTY, 1d) | 2,534 closes since 2016 | regime labels |
| Angel One rate card | per-position `fee_breakdown` vs the published card | 7 components | cost-model validation |
| Code | 17 service modules, 4 route modules (§2) | — | look-ahead, fills, risk controls |
| Literature | §7, with sources | — | hypotheses, base rates |

**Limits, stated up front.**

- **The live record is four sessions long.** Hundreds of trades inside one session share that session's market, so the honest sample size of the live record is 4, not 1,596, and four days say nothing about edge either way (per-day t = −0.71). Every profitability conclusion here rests on the two-year walk-forward.
- **History before 5 October is gone.** The module reset that day deleted it, and its archive collections were dropped without a backup. Live Intraday's August–October selection evidence cannot be re-audited. An Atlas snapshot taken before 22:11 IST on 5 October, if one exists, would restore it.
- **Slippage in the walk-forward is modelled** (1–4 bp a side by turnover), not measured. §3.4 shows exactly how much rests on it — it is the single most consequential assumption in this document.
- **Real-money charges for 10–20 August are not in the database.** Angel's contract notes are the only record.

---

## 2. Architecture and strategy inventory

The page is six tabs over four engines, plus a real-money twin elsewhere in the app.

| Tab | Engine | Catalog | Capital | Fill model | Validation | Verdict |
|---|---|---|---|---|---|---|
| Tournament · 54 | `intraday_v2_engine.py` | `intraday_v2_strategies.py`: 16 bar families × 15m/45m/1h + 6 day-level setups | ₹27 cr (₹50 L × 54, five ₹10 L slots each) | stream minute-bar walk, stop-first, gap fills, slippage by liquidity, Angel card | walk-forward with DSR, PBO and holdout (`intraday_v2_backtest.py`); pre-registered incubation (`intraday_v2_registry.py`); promotion gate t ≥ 3.31 | **Sound** |
| Patterns · 504 | `intraday_pattern_engine.py` | 63 templates × 8 timeframes (1m…1d), 25-name universe | ₹50.4 cr (₹10 L × 504) | polled LTP, **no slippage** | **none** | Defective (D1–D3) |
| Paper Trade ₹50k / ₹2 lakh | `pattern_books_engine.py` | picks from Patterns | ₹50k / ₹2 L | **copies the Patterns exit price** | none | Defective (D4) |
| Live Intraday ₹80k / ₹30k / ₹10k | `live_intraday_engine.py` | 8 picks from the **first** catalog, `intraday_strategies.py` (6 are ANTI mirrors) | ₹80k / ₹30k / ₹10k | quote-based, Angel card | none surviving | Unsupported (D6) |
| *Live Trading* (real money, under Market Data) | `live_trading_engine.py` | the same 8 | ₹10k per strategy, ₹80k ceiling | real Angel MIS orders | none | Disarmed; ledger defective (D5) |

Shared infrastructure: `intraday_store.py` and `intraday_data_scheduler.py` (Angel stream → bars, two-year store), `intraday_session.py` (closing-auction-aware square-off at 15:05 / 15:12), `intraday_universe.py` (point-in-time top 200), `angel_fees.py` (rate card), `promotion_gate.py`, `intraday_ops.py` (alarms), and the indicator library in `nifty_scalp_strategies.py` (`ema`, `rsi`, `atr`, `adx_di`, `stoch`, `cci`, `supertrend`, `macd`).

---

## 3. Verified profitability findings

### 3.1 The tournament's live record — measures costs, not edge

| | Value |
|---|---|
| Trades / sessions | 1,596 / 4 |
| Gross P&L | +₹2,46,536 |
| Angel charges | ₹6,40,664 (**2.60× gross**) |
| Net P&L | **−₹3,94,128** (−0.146% of ₹27 cr) |
| Per trade: gross / charges / net | ₹154 / ₹401 / −₹247 |
| Profit factor gross / net | 1.048 / 0.928 |
| t-stat of the mean, per trade (gross / net) | 0.71 / −1.14 |
| t-stat per **session** (n = 4) | −0.71 |
| Daily net | −₹1,36,112 · −₹2,33,978 · +₹3,55,862 · −₹3,79,900 |
| Price source | Angel stream on 100% of fills |
| Largest position vs that stock's daily traded value | 0.083% |

Nothing about edge can be concluded from four sessions. What the live record does measure precisely is the cost structure (§3.5) and that fills are honest: every price came from the stream, slippage of 1–4 bp was charged on every market fill, and no position was large enough to move its stock.

### 3.2 The two-year walk-forward

Run `20261010-0605` (it reruns nightly): 730 days back, point-in-time universe (each day trades only that day's top 200, so delisted and demoted names are included), 54 trials, most recent ~20% (from 13 May 2026) held out, gate thresholds written into every run document. The two `~opt` rows in the trades file are an *optimistic upper bound* on ambiguous ORB bars, stored for reference; they are excluded below.

| | Value |
|---|---|
| Trades / sessions / symbols | 153,403 / 495 / 213 |
| Gross (after modelled slippage) | **−₹5.35 cr** (−3.49 bp of notional a trade) |
| Angel charges | ₹6.16 cr (4.02 bp) |
| Net | **−₹11.51 cr** (−7.51 bp) — **−42.6%** of the ₹27 cr book |
| Sessions underwater | 495 of 495 |
| Positive sessions / months | 123 of 495 / **0 of 25** |
| Daily Sharpe / Sortino (annualised) | −9.28 / −8.77 |
| Probability of backtest overfitting (CSCV, 12,870 splits), runs on file | 0.018 – 0.043 |

**How many strategies survive each bar** (52 replayable; the two selected-ORB setups cannot be replayed and have their own study):

| Bar | Survivors |
|---|---|
| Positive gross (before charges) | 5 / 52 |
| Positive net | 0 / 52 |
| + profit factor ≥ 1.1 | 0 |
| + positive in the untouched holdout | 0 |
| + ≥ 55% of months positive | 0 |
| + t ≥ 3.31 (Bonferroni over 54) | 0 |

The low PBO matters for interpretation: it says the in-sample ranking carries out of sample. The gate is not failing these strategies because of overfitting; it fails them because they lose, consistently.

The loss is not concentrated: 37 of 213 symbols are net-positive, and the 20 worst account for only 31% of the loss. Every month lost money; the worst stretch was May–July 2025 (about −₹1.1 crore a month), the least bad April 2026 (−₹4.4 lakh).

### 3.3 Every cut is negative

`g bp` = gross per trade after modelled slippage, `n bp` = net after charges, both in basis points of position notional.

| Cut | Bucket | Trades | g bp | n bp | t (net) |
|---|---|---:|---:|---:|---:|
| Category | momentum | 109,868 | −2.94 | −6.96 | −24.73 |
| | mean reversion | 43,535 | −4.89 | −8.91 | −28.95 |
| Kind | trend | 64,054 | −2.39 | −6.41 | −18.74 |
| | breakout | 40,973 | −2.64 | −6.66 | −13.33 |
| | reversion | 43,114 | −4.88 | −8.90 | −29.02 |
| | opening-range (ORB) | 4,020 | −15.22 | −19.24 | −14.36 |
| | gap | 1,242 | −2.12 | −6.14 | −1.37 |
| Timeframe | 15m | 64,028 | −4.21 | −8.23 | −30.33 |
| | 45m | 43,662 | −2.19 | −6.21 | −13.55 |
| | 1h | 40,451 | −2.63 | −6.65 | −13.96 |
| | day-level setups | 5,262 | −12.12 | −16.14 | −10.97 |
| Side | BUY | 84,714 | −3.35 | −7.37 | −23.68 |
| | SELL | 68,689 | −3.66 | −7.68 | −25.19 |
| Trend regime, *ex-ante* (NIFTY's prior 20 sessions) | bull (> +3%) | 22,133 | −2.37 | −6.39 | −10.45 |
| | bear (< −3%) | 28,660 | −1.90 | −5.92 | −10.81 |
| | sideways | 102,610 | −4.18 | −8.20 | −31.69 |
| Volatility regime, *ex-ante* (NIFTY 20-session realised, median 11%) | high | 72,612 | −3.18 | −7.20 | −21.88 |
| | low | 80,791 | −3.77 | −7.79 | −26.51 |
| Day type, *ex-post* (descriptive only) | NIFTY > +1% | 12,368 | +2.41 | −1.62 | −1.88 |
| | NIFTY 0 to +1% | 61,620 | −3.13 | −7.15 | −21.02 |
| | NIFTY −1% to 0 | 64,081 | −4.71 | −8.73 | −26.42 |
| | NIFTY < −1% | 15,334 | −4.60 | −8.61 | −11.46 |
| Entry time | 09:45–10:30 | 57,178 | −2.90 | −6.92 | −15.72 |
| | 10:30–11:30 | 20,600 | −3.05 | −7.07 | −12.13 |
| | 11:30–12:30 | 22,316 | −3.05 | −7.07 | −13.85 |
| | 12:30–13:30 | 29,608 | −4.23 | −8.25 | −19.83 |
| | 13:30–14:30 | 23,701 | −4.80 | −8.82 | −24.03 |
| Exit reason | target | 19,698 | +108.17 | +104.13 | |
| | time stop | 48,196 | +17.09 | +13.07 | |
| | end of day | 37,448 | +7.46 | +3.43 | |
| | **stop-loss** | **48,061** | **−78.43** | **−82.44** | |

Three readings follow.

- **Regime does not rescue anything.** Every ex-ante regime loses. There is no market condition to switch into, so adaptive regime selection is not worth building (§7).
- **The stop is the gross loss.** Stop-outs are 31% of exits and lose 78 bp each; everything else earns. Tight ATR stops (1.0–1.2 ATR on 15m–1h bars) are hit by ordinary intraday noise.
- **A trap: holding time.** Trades held 2–4 hours made +7.38 bp net (t = +24) and those held 15–60 minutes lost 29.5 bp. This is not a rule anyone can trade. Holding time is decided by the exit, and the exit by the outcome: a trade that is stopped out is short by definition, a trade that works runs to its time stop. "Hold longer" in advance means wider stops or no stops — a different strategy that would need its own test.

### 3.4 Where the money goes: a real signal, smaller than the friction

Slippage is applied *inside* the fill price, so the "gross" above already includes it. The trades file does not carry each trade's slippage, so it is reconstructed with the live desk's measured mean of **2.76 bp a side** on every entry and every market exit (87% of exits); targets are limit orders and pay none. *This is an approximation.*

| Per trade, bp of notional | Value |
|---|---:|
| Frictionless edge (before slippage and charges) | **+1.67** |
| Modelled slippage | −5.17 |
| Angel charges | −4.02 |
| Net | −7.51 |
| Friction ÷ frictionless edge | **5.5×** |

**37 of 52 strategies have a positive frictionless edge**, and six clear the Bonferroni bar on it:

| Strategy | Raw edge bp | Raw t | Net bp at modelled / half / zero slippage | Break-even slippage (bp a side) | Holdout net |
|---|---:|---:|---|---:|---:|
| `iv2_donchian_45m` | +7.48 | 3.98 | −1.85 / +0.80 / +3.46 | **1.80** | +₹1,38,370 |
| `iv2_donchian_1h` | +6.94 | 3.45 | −2.46 / +0.23 / +2.92 | **1.50** | +₹3,00,528 |
| `iv2_vwap_trend_1h` | +6.52 | 3.54 | −2.86 / −0.18 / +2.50 | **1.29** | +₹14,334 |
| `iv2_macd_trend_1h` | +5.64 | 3.36 | −3.77 / −1.08 / +1.62 | 0.83 | −₹2,02,501 |
| `iv2_rsi_momentum_45m` | +5.18 | 3.34 | −4.17 / −1.51 / +1.16 | 0.60 | −₹5,24,544 |
| `iv2_bollinger_snap_1h` | +4.20 | 3.47 | −5.01 / −2.42 / +0.18 | 0.09 | −₹4,56,500 |

The first three are also three of only five strategies that were net-positive in the untouched holdout — after modelled slippage and charges. That is a modest supporting signal, not proof: 104 sessions, and they were identified by looking.

Two caveats keep this honest. Raw t-stats are per trade, and trades cluster by session, so these are *upper bounds* on significance. And break-even slippage is the decision variable: if real slippage on a ₹10 lakh order in these names is below 1.3–1.8 bp a side, the first three are candidates; if it is 2.76 bp as modelled, none is. That number is measurable (H1).

**Cost sensitivity** — what if Angel's charges were a fraction of the real card (slippage unchanged)?

| Charges at | Whole book net | Strategies net-positive |
|---|---:|---:|
| 0× (free) | −₹5.35 cr | 5 / 52 |
| 0.25× | −₹6.89 cr | 3 / 52 |
| 0.5× | −₹8.43 cr | 1 / 52 |
| 0.75× | −₹9.97 cr | 0 / 52 |
| 1× (real) | −₹11.51 cr | 0 / 52 |

Even trading for free, 47 of 52 lose.

### 3.5 The cost model is exactly right

The whole conclusion would collapse if charges were overstated, so they were checked against Angel One's published intraday equity card on the desk's median position of ₹10 lakh:

| Component | Card | Expected ₹ | Measured ₹ (mean of 1,596) |
|---|---|---:|---:|
| Brokerage | ₹20 or 0.25% per order, lower | 40.00 | 40.00 |
| STT | 0.025%, sell side | 250.00 | 249.59 |
| Exchange transaction | 0.00297% both sides | 59.40 | 59.30 |
| Stamp duty | 0.003%, buy side | 30.00 | 29.95 |
| SEBI fee | ₹10 per crore | 2.00 | 2.00 |
| IPFT | ₹10 per crore | 2.00 | 2.00 |
| GST | 18% of brokerage + exchange + SEBI + IPFT | 18.61 | 18.59 |
| **Total** | | **402.01** | **401.42** |

**4.02 bp a round trip.** STT is 62% of it, and STT is proportional to value — no position size makes it smaller. Brokerage, the only component that shrinks with size, is already 0.4 bp at ₹10 lakh. **Charges cannot be engineered down; slippage is the only reducible friction.**

### 3.6 What is *not* wrong — the tournament passes a code audit

The brief asks for look-ahead, survivorship, leakage and fill realism to be tested. For the tournament, each was:

| Check | Finding |
|---|---|
| Look-ahead in indicators | Every indicator in `nifty_scalp_strategies.py` is strictly trailing — each value at index *i* reads only `vals[…i]`; no full-series normalisation, no centred windows. |
| Look-ahead in context | `build_ctx` (`intraday_v2_strategies.py`) takes ATR, prior-day high/low and prior close from earlier sessions only; the opening range only once both 15m bars have closed; average volume excludes the current bar; session VWAP stops at the last closed bar. |
| Look-ahead in rules | Rules read `ind[i]` and `ind[i-1]` only. The `Ctx` docstring states the contract and the code keeps it. |
| Live vs backtest consistency | The same rule functions run in both. The live window is 420 15m bars and 220 45m/1h bars, by which point EMA(50)'s seed contributes about 0.015% — converged. |
| Survivorship | Each backtest day trades only that day's top 200 by turnover (`point_in_time: true`). |
| Fill realism | Minute-bar walk; stop assumed first when one minute crosses both levels; a gap through a level fills at the open; slippage on every market fill; targets as limit orders. The ambiguous-bar optimistic case is computed as a separate `~opt` *bound*, not counted. |
| Gate integrity | Thresholds are written into each run document; incubation thresholds are frozen at registration. |
| Untested filters | The NIFTY-direction filter (Gao et al. 2018) was already tested and switched off on evidence: NIFTY's first 30 minutes do not predict its rest of day here (correlation −0.07). |

**The tournament's negative result is the market's answer, not a bug.**

### 3.7 Statistical limitations

- Per-trade t-stats overstate significance because trades inside a session are correlated; the per-session unit is more honest. This matters most for the raw-edge t-stats in §3.4, which should be read as upper bounds.
- The slippage decomposition uses a desk-wide mean (2.76 bp a side); each strategy's real mix of names differs.
- Regime labels in §3.3 are ex-ante (prior 20 sessions) except the day-type cut, which is descriptive only.
- Risk of ruin is not a meaningful statistic here: for a strategy with negative expectancy it is 100% given enough time. The book lost 1.8% of capital a month on average and never recovered a peak.

---

## 4. Confirmed defects

Separate from improvements (§8) and hypotheses (§8, H-items). Each was confirmed in both code and data.

| ID | Where | Defect | Evidence | Severity |
|---|---|---|---|---|
| **D1** | `intraday_pattern_engine._manage` | Exits fill at the **polled LTP** rather than at the level, and the price path between polls is never walked. Targets therefore book price that ran past them; a stop crossed and recovered between polls is missed. No slippage on any fill; no `fill_basis`, `exit_basis`, `slippage_bp` or `ltp_source` recorded. | Sample row: target 705.44, booked exit 714.65. Target exits booked **₹52.8 lakh better** than their own levels; stop exits ₹40.7 lakh worse. Corrected net **−₹23.1 lakh** vs +₹52.9 lakh reported. | Critical |
| **D2** | `intraday_pattern_engine.scan` / `_open` | No per-symbol cap, no slot limit, no daily-loss breaker. 504 strategies on a 25-name universe is ~20 per name by construction. | 88% of trades share a (symbol, side, price, minute) with another strategy. `BBOX BUY @895.65`: 32 strategies, **₹3.18 crore on one idea**. `CPPLUS BUY`: 23 strategies, ₹2.30 crore, −₹4.1 lakh. | Critical |
| **D3** | Patterns desk | No backtest, no holdout, no promotion gate, no verdict. 1,442 of its 3,913 trades are on 1-minute bars. | No code path validates it (grep across services). | High |
| **D4** | `pattern_books_engine._close_mirror` | Copies the parent's `exit_price`, so the ₹50k and ₹2 lakh books inherit D1 exactly. `closed_on` is read from the parent but never written on the book's own row. | `_close_mirror` sets eleven fields, not `closed_on`; all 416 book rows lack it, so every per-day view of those books is empty. The books' strategies were picked from the Patterns leaderboard, which ranks on D1's overstated figures. | High |
| **D5** | `live_trading_engine` (real money) | **Real trades carry no charges**: no `fees` or `fee_breakdown` on any of 78 positions or trades. **49 of 78 were closed by Angel's MIS auto-square-off** after the desk missed its own close. The stale-session branch of `_manage_cycle` then booked each at the LTP of the session in which it noticed — the *next* trading day — so their P&L carries an overnight move the account never had (`exit_reason: stale_session_reconciled`, no exit order id). `reconcile_fills` reads Angel's trade book, which is same-day only, so those fills can never be recovered through the API. | 30 on 19 Aug, 19 on 20 Aug. Recorded −₹799.34. Estimated unrecorded charges ≈ ₹22 a round trip at the ₹3,533 average position (brokerage 0.25% binds below ₹8,000) ≈ ₹1,700, plus any auto-square-off charges — contract notes are the source of truth. | Critical |
| **D6** | `live_intraday_engine._DEFAULT_SELECTION` | The "real-money shortlist" is 8 names but about 4 ideas (four thresholds of one EMA20 pullback, two lookbacks of one breakout retest), drawn from the first catalog the 2 October audit retired. Seven of eight are **swing** rules forced into same-day square-off; the tournament excludes the `swing` category. Two strategies (045, 047) booked identical P&L in two books. | Picks listed in the module; 4-day record: ₹80k −₹1,886, ₹30k −₹689, ₹10k −₹142. The evidence they were picked on was destroyed on 5 October. | High |
| **D7** | `intraday_ops._set` | Alarms are keyed `kind:date`, and resolution only targets today's id, so an alarm still active at midnight is never resolved. Re-raising sets `resolved: false` without unsetting `resolved_at`. | Memory alarms for 5, 6, 9 and 10 October all still `active`; the page shows two memory banners. | Medium |
| **D8** | `intraday_pattern_engine._prune_cache` / `CACHE_MAX` | The series cache is bounded by entries (25 × 8 × 2 = 400), not by bars. | 74 entries hold 56,183 bars (~760 each); at the cap that is ~300,000 bars, the same order as the 343,000-bar incident on record. Backend at 91.6% of 800 MB, 53 MB swapped, 113,603 major faults. | High (operational) |
| **D9** | `intraday_v2_engine.slippage_bp` | Calibrated and documented for "a ~₹2 lakh order"; positions became ₹10 lakh on 2 October. For the thinnest names a ₹10 lakh market order is roughly a third of a minute's traded value. | Docstring vs `SLOT_NOTIONAL`. Direction of bias unknown: possibly conservative for mega-caps, optimistic for the tail. | Medium |
| **D10** | Tournament per-symbol cap | One cluster of three strategies on one symbol and minute (`PWL BUY @137.22`) against a cap of two. | Observed once in 1,596; cause not traced. | Low |
| **D11** | Page | "ENGINE IDLE · beat 83324s ago" on a Saturday is correct behaviour shown as an alarm. | Heartbeat 15:28 IST Friday; all positions squared off. | Low |

---

## 5. Strategy-by-strategy assessment

### 5.1 Tournament — by family (hypothesis, implementation, weakness, upgrade)

The three timeframes of a family share hypothesis and implementation, so those fields are given once per family; every individual strategy's numbers and decision are in §5.2.

| Family | Hypothesis | Implementation (stop / target in ATR of its timeframe) | Evidence (2 years) | Main weakness | Upgrade / decision |
|---|---|---|---|---|---|
| Donchian 20 breakout | range expansion continues | close through the 20-bar high/low on 1.2× volume; 1.0 / 2.0 | raw +3.1 to +7.5 bp; 45m and 1h clear t 3.31 raw; both positive in holdout | friction > edge at modelled slippage | **45m, 1h: OPTIMIZE (H1)**; 15m: disable |
| VWAP reclaim | reclaiming a rising VWAP signals institutional demand | close crosses a rising/falling session VWAP; 1.0 / 1.8 | 1h raw +6.52 (t 3.54), positive in holdout | same | **1h: OPTIMIZE (H1)**; 15m, 45m: disable |
| MACD trend turn | momentum turns persist | MACD line/signal turn with trend; stop/target per rule | 1h raw +5.64 (t 3.36), break-even 0.83 bp | needs sub-1 bp slippage | 1h: research only; others disable |
| RSI momentum 60/40 | strength persists | RSI crosses 60/40 | 45m raw +5.18 (t 3.34), break-even 0.60 bp | same | 45m: research only; others disable |
| Prior-day high/low break | yesterday's extremes are reference levels | close through PDH/PDL | 45m raw +4.91, break-even 0.47 bp | same; 15m negative before costs | research only / disable |
| EMA trend pullback | buying pullbacks in an established trend | EMA 9>21>50, pullback to 21, close above 9; 1.0 / 1.8 | 45m raw +4.44; 1h negative raw | edge too small | research only / disable |
| Supertrend flip, ADX trend start, Keltner breakout | trend onset | indicator flips | raw +0.6 to +4.1 bp, mostly t < 3 | fees alone exceed edge | disable (all timeframes) |
| Opening-range close break | first 30 minutes set the day's direction | close beyond the 09:15–09:45 range | raw +0.75 to +1.58 bp | fees exceed edge | disable |
| VWAP reversion | stretches from VWAP revert | ≥ 1.5 ATR from VWAP, closed off the extreme → target VWAP; stop 1.0 | **raw −4.3 to −7.3 bp** | pays the liquidity premium (§6) | disable |
| RSI(2) extreme | sharp dips in an uptrend revert | RSI(2) < 5 above EMA50; **stop 1.2, target 1.0** | raw −3.0 to +0.3 bp | a stop larger than the target needs about 55% wins just to break even before costs | disable |
| Bollinger snap-back | closes back inside 2σ revert to the mean | target SMA20; stop 1.0 | 1h raw +4.20 (t 3.47) but break-even 0.09 bp | edge far below friction | 1h: research only; others disable |
| Z-score fade, stochastic range turn, CCI ±200 | ranges mean-revert (ADX < 20–25) | z ≥ 2.5 / stoch turn / CCI return; stop 1.0–1.2, target 1.0 or mean | raw −2.8 to +3.2 bp | same asymmetry; reversion via market orders | disable |
| ORB on stocks in play (10% / 25% ATR stop) | Zarattini, Barbon & Aziz (2024) | top-20 relative-volume names at 09:45; stop entry at the **30-minute** range edge; held to close | **raw −14.3 / −6.3 bp** | the published result is a **5-minute** range under US costs; a 10%-ATR stop is noise-sized | disable (10% ATR mirror: H3) |
| Gap and go / gap fade | gaps continue / fill | 09:45 read | +5.51 / −2.19 raw; 821 / 421 trades | too few trades, low t | go: research only; fade: disable |
| Selected ORB 15 / 30 min | the only idea that survived the 5,184-variant 5-minute study (S4) | top-5 by expected move, opening volume ≥ 1.5×, OCO stop entries at both edges | cannot be replayed here; S4 DSR 0.05; forward record 2 and 8 trades | too early | **INCUBATE untouched** (pre-registered; never re-tune) |

### 5.2 Tournament — every strategy, numbers and decision

Raw edge = frictionless bp per trade (slippage reconstructed at 2.76 bp a side, §3.4). Net bp and 2-year net are after modelled slippage and Angel charges. Break-even slippage is the per-side slippage at which the strategy would net zero; "never" means charges alone exceed its raw edge. Live = the four sessions 6–9 October (trades in brackets) — shown for completeness, not evidence.

Decision rule, applied mechanically: raw edge ≤ 0 → **DISABLE (no edge)**; raw t ≥ 3.31 and break-even ≥ 1.2 bp → **OPTIMIZE (H1)**; break-even > 0 → **RESEARCH ONLY**; otherwise → **DISABLE (charges exceed edge)**.

| # | Strategy | Kind / TF | 2y trades | Raw edge bp | Raw t | Net bp | 2y net ₹ | Holdout ₹ | Break-even slip | Live 4d net ₹ | Decision |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `iv2_orb_sel30` | orb / day | — | — | — | — | — | — | — | −44,877 (8) | INCUBATE (pre-registered; S4 study) |
| 2 | `iv2_orb_sel15` | orb / day | — | — | — | — | — | — | — | 28,329 (2) | INCUBATE (pre-registered; S4 study) |
| 3 | `iv2_donchian_45m` | breakout / 45m | 3,891 | +7.48 | 3.98 | −1.85 | −7,19,090 | 1,38,370 | 1.80 | 6,570 (32) | OPTIMIZE — measure real slippage (H1) |
| 4 | `iv2_donchian_1h` | breakout / 1h | 3,503 | +6.94 | 3.45 | −2.46 | −8,60,662 | 3,00,528 | 1.50 | 1,71,003 (28) | OPTIMIZE — measure real slippage (H1) |
| 5 | `iv2_vwap_trend_1h` | trend / 1h | 3,783 | +6.52 | 3.54 | −2.86 | −10,78,960 | 14,334 | 1.29 | 10,210 (35) | OPTIMIZE — measure real slippage (H1) |
| 6 | `iv2_macd_trend_1h` | trend / 1h | 3,098 | +5.64 | 3.36 | −3.77 | −11,66,377 | −2,02,501 | 0.83 | 1,16,955 (31) | RESEARCH ONLY — edge < friction |
| 7 | `iv2_gap_go` | gap / day | 821 | +5.51 | 0.90 | −3.84 | −3,15,112 | 5,435 | 0.77 | 17,107 (8) | RESEARCH ONLY — edge < friction |
| 8 | `iv2_rsi_momentum_45m` | trend / 45m | 3,848 | +5.18 | 3.34 | −4.17 | −16,04,466 | −5,24,544 | 0.60 | −1,05,168 (31) | RESEARCH ONLY — edge < friction |
| 9 | `iv2_pdh_pdl_45m` | breakout / 45m | 2,987 | +4.91 | 2.34 | −4.40 | −13,13,679 | −1,25,360 | 0.47 | 1,06,398 (21) | RESEARCH ONLY — edge < friction |
| 10 | `iv2_ema_pullback_45m` | trend / 45m | 3,384 | +4.44 | 2.90 | −4.87 | −16,45,992 | −1,40,426 | 0.22 | 73,157 (37) | RESEARCH ONLY — edge < friction |
| 11 | `iv2_bollinger_snap_1h` | reversion / 1h | 3,178 | +4.20 | 3.47 | −5.01 | −15,89,266 | −4,56,500 | 0.09 | −31,882 (26) | RESEARCH ONLY — edge < friction |
| 12 | `iv2_supertrend_1h` | trend / 1h | 2,843 | +4.09 | 2.14 | −5.39 | −15,30,595 | −3,13,245 | 0.03 | 1,10,193 (25) | RESEARCH ONLY — edge < friction |
| 13 | `iv2_supertrend_45m` | trend / 45m | 2,977 | +3.83 | 2.01 | −5.61 | −16,67,541 | −6,15,351 | never | 2,273 (29) | DISABLE — charges exceed edge |
| 14 | `iv2_keltner_45m` | breakout / 45m | 3,284 | +3.53 | 1.95 | −5.81 | −19,06,857 | −18,099 | never | 83,899 (32) | DISABLE — charges exceed edge |
| 15 | `iv2_adx_dmi_45m` | trend / 45m | 2,904 | +3.26 | 2.02 | −6.17 | −17,88,854 | −3,46,068 | never | 30,667 (33) | DISABLE — charges exceed edge |
| 16 | `iv2_adx_dmi_15m` | trend / 15m | 4,357 | +3.18 | 3.19 | −6.06 | −26,38,428 | −3,95,033 | never | 39,842 (55) | DISABLE — charges exceed edge |
| 17 | `iv2_stoch_range_1h` | reversion / 1h | 702 | +3.15 | 1.47 | −5.98 | −4,19,423 | −1,43,165 | never | −29,224 (12) | DISABLE — charges exceed edge |
| 18 | `iv2_vwap_trend_45m` | trend / 45m | 3,181 | +3.10 | 1.76 | −6.26 | −19,89,182 | −4,83,657 | never | 33,447 (23) | DISABLE — charges exceed edge |
| 19 | `iv2_donchian_15m` | breakout / 15m | 5,413 | +3.08 | 2.56 | −6.01 | −32,50,061 | −4,12,594 | never | 52,571 (59) | DISABLE — charges exceed edge |
| 20 | `iv2_rsi_momentum_1h` | trend / 1h | 3,382 | +3.07 | 1.91 | −6.36 | −21,47,601 | −2,64,851 | never | 18,165 (33) | DISABLE — charges exceed edge |
| 21 | `iv2_cci_extreme_1h` | reversion / 1h | 2,553 | +2.65 | 1.88 | −6.43 | −16,40,061 | −4,75,332 | never | −3,478 (19) | DISABLE — charges exceed edge |
| 22 | `iv2_macd_trend_45m` | trend / 45m | 3,025 | +2.59 | 1.48 | −6.77 | −20,44,331 | −1,92,712 | never | 16,623 (29) | DISABLE — charges exceed edge |
| 23 | `iv2_vwap_trend_15m` | trend / 15m | 4,338 | +2.46 | 2.24 | −6.64 | −28,78,741 | −4,94,847 | never | −63,275 (46) | DISABLE — charges exceed edge |
| 24 | `iv2_macd_trend_15m` | trend / 15m | 4,549 | +2.02 | 1.95 | −7.10 | −32,26,523 | −5,19,571 | never | −55,605 (46) | DISABLE — charges exceed edge |
| 25 | `iv2_supertrend_15m` | trend / 15m | 4,036 | +1.80 | 1.47 | −7.48 | −30,14,494 | −6,43,046 | never | −70,515 (39) | DISABLE — charges exceed edge |
| 26 | `iv2_cci_extreme_45m` | reversion / 45m | 2,720 | +1.77 | 1.28 | −7.10 | −19,28,774 | −3,10,820 | never | −24,999 (19) | DISABLE — charges exceed edge |
| 27 | `iv2_bollinger_snap_15m` | reversion / 15m | 4,711 | +1.67 | 2.04 | −7.17 | −33,74,539 | −2,52,015 | never | −86,459 (58) | DISABLE — charges exceed edge |
| 28 | `iv2_or_close_break_1h` | breakout / 1h | 2,590 | +1.58 | 0.72 | −7.83 | −20,25,530 | 12,114 | never | −69,916 (20) | DISABLE — charges exceed edge |
| 29 | `iv2_cci_extreme_15m` | reversion / 15m | 4,585 | +1.47 | 1.79 | −6.97 | −31,93,011 | −2,64,159 | never | −96,775 (53) | DISABLE — charges exceed edge |
| 30 | `iv2_rsi_momentum_15m` | trend / 15m | 4,592 | +1.32 | 1.31 | −7.83 | −35,91,241 | −5,06,416 | never | −8,658 (51) | DISABLE — charges exceed edge |
| 31 | `iv2_ema_pullback_15m` | trend / 15m | 4,500 | +1.31 | 1.36 | −7.77 | −34,90,946 | −3,15,571 | never | −61,573 (60) | DISABLE — charges exceed edge |
| 32 | `iv2_or_close_break_15m` | breakout / 15m | 3,615 | +1.18 | 0.83 | −7.97 | −28,77,268 | −6,27,033 | never | −30,357 (34) | DISABLE — charges exceed edge |
| 33 | `iv2_bollinger_snap_45m` | reversion / 45m | 3,060 | +1.17 | 0.93 | −7.92 | −24,21,168 | −2,93,353 | never | −1,21,343 (25) | DISABLE — charges exceed edge |
| 34 | `iv2_keltner_1h` | breakout / 1h | 2,862 | +0.93 | 0.50 | −8.50 | −24,29,047 | −11,979 | never | 1,02,567 (28) | DISABLE — charges exceed edge |
| 35 | `iv2_zscore_45m` | reversion / 45m | 1,472 | +0.82 | 0.39 | −8.46 | −12,43,161 | −2,39,642 | never | −11,937 (14) | DISABLE — charges exceed edge |
| 36 | `iv2_or_close_break_45m` | breakout / 45m | 2,733 | +0.75 | 0.35 | −8.62 | −23,53,206 | −4,72,683 | never | −25,222 (16) | DISABLE — charges exceed edge |
| 37 | `iv2_pdh_pdl_1h` | breakout / 1h | 2,551 | +0.68 | 0.30 | −8.72 | −22,20,598 | −72,141 | never | 47,715 (15) | DISABLE — charges exceed edge |
| 38 | `iv2_keltner_15m` | breakout / 15m | 4,333 | +0.59 | 0.54 | −8.54 | −36,96,078 | −5,41,320 | never | 66,425 (57) | DISABLE — charges exceed edge |
| 39 | `iv2_rsi2_1h` | reversion / 1h | 2,711 | +0.26 | 0.18 | −8.74 | −23,66,139 | −6,33,970 | never | −68,125 (28) | DISABLE — charges exceed edge |
| 40 | `iv2_stoch_range_45m` | reversion / 45m | 869 | −0.11 | −0.05 | −9.01 | −7,82,140 | −2,80,270 | never | −25,479 (14) | DISABLE — no edge before costs |
| 41 | `iv2_adx_dmi_1h` | trend / 1h | 2,499 | −0.61 | −0.36 | −10.10 | −25,19,881 | −4,95,362 | never | 17,442 (26) | DISABLE — no edge before costs |
| 42 | `iv2_ema_pullback_1h` | trend / 1h | 2,758 | −1.51 | −0.94 | −10.91 | −30,05,037 | −5,35,701 | never | 56,078 (35) | DISABLE — no edge before costs |
| 43 | `iv2_rsi2_45m` | reversion / 45m | 2,598 | −1.52 | −1.04 | −10.34 | −26,83,022 | −7,66,546 | never | −1,23,238 (34) | DISABLE — no edge before costs |
| 44 | `iv2_zscore_15m` | reversion / 15m | 2,596 | −1.97 | −1.70 | −10.93 | −28,33,316 | −4,44,241 | never | −72,899 (34) | DISABLE — no edge before costs |
| 45 | `iv2_pdh_pdl_15m` | breakout / 15m | 3,211 | −2.15 | −1.63 | −11.27 | −36,13,824 | −4,82,719 | never | −32,769 (37) | DISABLE — no edge before costs |
| 46 | `iv2_stoch_range_15m` | reversion / 15m | 2,705 | −2.16 | −2.80 | −10.73 | −28,99,281 | −7,18,763 | never | −1,18,350 (45) | DISABLE — no edge before costs |
| 47 | `iv2_gap_fade` | gap / day | 421 | −2.19 | −0.41 | −10.61 | −4,46,311 | −1,24,433 | never | — | DISABLE — no edge before costs |
| 48 | `iv2_zscore_1h` | reversion / 1h | 1,165 | −2.81 | −1.20 | −12.17 | −14,16,409 | −2,91,089 | never | −35,554 (10) | DISABLE — no edge before costs |
| 49 | `iv2_rsi2_15m` | reversion / 15m | 3,503 | −2.98 | −3.73 | −11.50 | −40,22,152 | −5,09,043 | never | −75,872 (58) | DISABLE — no edge before costs |
| 50 | `iv2_vwap_reversion_15m` | reversion / 15m | 2,984 | −4.30 | −4.38 | −13.56 | −40,41,226 | −4,52,170 | never | −65,816 (43) | DISABLE — no edge before costs |
| 51 | `iv2_vwap_reversion_45m` | reversion / 45m | 729 | −4.35 | −1.79 | −13.78 | −10,03,072 | −3,30,039 | never | −29,805 (6) | DISABLE — no edge before costs |
| 52 | `iv2_orb_inplay_25` | orb / day | 2,326 | −6.34 | −2.87 | −15.88 | −36,89,935 | −9,33,627 | never | 36,325 (9) | DISABLE — no edge before costs |
| 53 | `iv2_vwap_reversion_1h` | reversion / 1h | 273 | −7.30 | −1.97 | −16.81 | −4,58,245 | −1,89,571 | never | −25,213 (5) | DISABLE — no edge before costs |
| 54 | `iv2_orb_inplay_10` | orb / day | 1,694 | −14.30 | −15.16 | −23.84 | −40,33,494 | −9,320 | never | −23,705 (23) | DISABLE — no edge before costs (mirror: H3) |

**Totals:** 3 OPTIMIZE, 7 RESEARCH ONLY, 42 DISABLE, 2 INCUBATE. Note how little the live column agrees with the two-year record — `keltner_1h` made ₹1.03 lakh in four sessions and has a raw edge of 0.93 bp over two years. That is what four sessions are worth.

### 5.3 Patterns · 504 — corrected

Per-strategy decisions are not supportable: four sessions on 25 names, with D1 in every row. At desk level, with targets filled at the target, stops as booked, and 3 bp a side of slippage:

| Timeframe | Trades | Reported net ₹ | Corrected net ₹ |
|---|---:|---:|---:|
| 1m | 1,442 | 15,15,145 | **−9,77,588** |
| 45m | 310 | −2,67,295 | −6,89,377 |
| 1d | 58 | −3,15,388 | −5,02,105 |
| 1h | 261 | −1,88,336 | −4,63,858 |
| 5m | 927 | 16,73,442 | **−3,88,383** |
| 15m | 490 | 10,44,413 | −1,75,458 |
| 4h | 51 | 3,64,874 | 1,33,495 |
| 30m | 374 | 14,69,913 | 7,50,675 |
| **Total** | **3,913** | **52,96,768** | **−23,12,599** |

| Family | Trades | Reported net ₹ | Corrected net ₹ |
|---|---:|---:|---:|
| mean_reversion | 650 | −86,908 | −11,02,707 |
| pattern (candlestick) | 794 | 5,46,888 | −10,65,983 |
| momentum | 531 | 4,66,843 | −2,92,087 |
| vcp | 68 | −97,377 | −2,82,883 |
| breakout | 754 | 20,87,139 | 27,471 |
| trend | 940 | 16,79,442 | 65,210 |
| chart_pattern | 176 | 7,00,741 | 3,38,378 |

The 1-minute and 5-minute books, which looked best, are where the polling defect bites hardest: a target a few ticks away is overshot most when bars are shortest. **Decision: FIX (C1, C2) and then validate through the same walk-forward gate as the tournament (H4) — or retire the desk.** Until then its numbers should not be shown as performance.

### 5.4 Paper Trade ₹50k / ₹2 lakh

208 trades each over four sessions: ₹50k −₹3,346 (₹5,027 charges, 30.8% win), ₹2 lakh −₹3,761 (₹11,104 charges, 41.3% win) — negative *even with* inherited overstatement. Their strategies were chosen from the Patterns leaderboard, which ranks on overstated figures. **Decision: FIX (C5); label the picks unvalidated; re-pick only from strategies that pass H4.**

### 5.5 Live Intraday ₹80k / ₹30k / ₹10k

| Pick | Strategy id | Notes |
|---|---|---|
| ANTI EMA20 Pullback Swing 2.0% / 2.5% / 1.5% / 1.0% | four of `anti_intraday_041…044` | one idea, four thresholds |
| ANTI Breakout Retest (10d) / (30d) Swing | `anti_intraday_045`, `047` | one idea, two lookbacks; identical P&L in two books |
| Aroon25 Trend Up80 | `intraday_105` | |
| ANTI Momentum Swing ROC20 | `anti_intraday_049` | |

Hypothesis behind the picks: the base strategies lost on the old leaderboard, so their mirrors should win. Weaknesses: (1) seven are **swing** rules whose targets are sized for multi-day moves but which are squared off the same day, so they mostly exit at the close rather than at a level; (2) about four independent ideas, not eight; (3) drawn from the first catalog, which the 2 October audit found lost ₹21 lakh *gross* in four sessions and replaced; (4) a mirror pays costs in both directions — the mirrored v2 book loses 10.86 bp a trade (§8, H3); (5) the record they were chosen on no longer exists. Four sessions now: all three books slightly negative, 59–70% win rates (the signature of a small edge eaten by costs). **Decision: DISABLE as a real-money shortlist; replace it only with strategies that earn a CONFIRMED incubation verdict.**

### 5.6 Live Trading (real money)

78 real round trips, 10–20 August, ₹2.76 lakh notional (average ₹3,533). Recorded −₹799 before charges (none recorded). 29 closed by the desk's own orders (19 target, 9 end-of-day, 1 stop); 49 closed by Angel's auto-square-off and booked at the next session's price. Currently `armed: false` ("manual disarm"; last armed for about three seconds at 19:07 IST on 7 October, after market hours), kill switch off, all eight strategies still flagged enabled. **Decision: KEEP DISARMED; FIX the ledger (C3) and the arming precondition (C4).**

---

## 6. Root-cause analysis

The brief asks to separate implementation errors from poor market conditions, excessive costs, and absence of edge. For this module, all four are present in different places:

| Cause | Where | Evidence |
|---|---|---|
| **Implementation error** | Patterns, Pattern Books, Live Trading ledger, Live Intraday design | D1–D6. The tournament is clean (§3.6). |
| **Poor market conditions** | ruled out | Every ex-ante regime is negative (§3.3). There is no condition under which this catalog works. |
| **Excessive costs** | ~10 strategies | Positive frictionless edge up to 7.5 bp against ~9 bp of friction (§3.4). Charges are correct and irreducible (§3.5); slippage is the open question. |
| **No edge at all** | 15 strategies | Negative raw edge before any friction (§5.2 rows 40–54). |

Four mechanisms explain the shape of the losses:

1. **Friction is structural.** At 4.02 bp of charges plus 2–5 bp of slippage, an intraday round trip in NSE cash costs 6–9 bp. The catalog's average raw edge is 1.67 bp. No refinement of entry signals closes a 5× gap; only larger moves per trade, cheaper execution, or fewer trades can.
2. **The stop is the loss.** 31% of exits are stops at −78 bp each. A 1.0 ATR stop on a 15-minute bar sits inside the ordinary range of the next hour. Several reversion rules compound this with a target *smaller* than the stop (RSI(2), CCI: stop 1.2 ATR, target 1.0), which needs a win rate of about 55% (1.2 ÷ 2.2) just to break even before costs.
3. **Mean reversion with market orders pays the liquidity premium instead of earning it.** Short-horizon reversal returns are largely compensation for supplying liquidity (Nagel 2012). A rule that *takes* liquidity with a market order to fade a move is on the paying side of that trade. The reversion family's −4.88 bp gross is consistent with exactly that.
4. **The opening-range setups test a weaker variant under heavier costs.** The published ORB result uses a 5-minute range on US stocks with negligible commissions and no transaction tax; this desk uses a 30-minute range (no entries before 09:45) and pays 2.5 bp of STT on every sell. The 5-minute version was tested separately (S4: 5,184 variants) and is the one now incubating.

---

## 7. Research findings and benchmarks

### 7.1 Base rates

- **SEBI (published 24 July 2024)**, a study of about 7 million individual intraday traders in the equity cash segment: **7 in 10 made losses in FY2022-23**, and loss-makers spent a further 57% of their trading losses on trading costs. Sources: [Business Standard](https://www.business-standard.com/amp/markets/news/7-in-10-intraday-traders-in-equity-cash-suffered-losses-in-fy23-sebi-study-124072400975_1.html), [Angel One summary](https://www.angelone.in/news/market-updates/sebi-highlights-intraday-trading-risk).
- **Barber, Lee, Liu & Odean (2014)**, *The cross-section of speculator skill: Evidence from day trading*, Journal of Financial Markets 18: fewer than 1% of Taiwanese day traders predictably earn positive returns net of fees.

A system-built intraday desk is not a retail trader, but these set the prior: an intraday equity edge that survives costs is rare, and claims of one need strong evidence.

### 7.2 Literature relevant to this module

| Work | Claim | Relevance here |
|---|---|---|
| Zarattini, Barbon & Aziz (2024), *A Profitable Day Trading Strategy for the U.S. Equity Market*, Swiss Finance Institute RP 24-98 ([SSRN/RePEc](https://ideas.repec.org/p/chf/rpseri/rp2498.html), [authors' page](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/)) | 5-minute ORB on top-20 "stocks in play", 7,000+ US stocks 2016–2023: Sharpe 2.81 net | Implemented as `orb_inplay_*` with a 30-minute range: −15.2 bp gross here. The 5-minute version is the S4 study → `orb_sel15/30` incubating. |
| Gao, Han, Li & Zhou (2018), *Market intraday momentum*, JFE 129(2) | first half-hour return predicts last half-hour | Tested on NIFTY: correlation −0.07; filter removed. Also not tradeable as published in NSE cash since the closing auction. |
| Heston, Korajczyk & Sadka (2010), *Intraday patterns in the cross-section of stock returns*, JF 65(4) | returns recur at the same half-hour on prior days | Not implemented. A low-priority hypothesis (H5). |
| Nagel (2012), *Evaporating liquidity*, RFS 25(7) | short-term reversal is compensation for liquidity provision | Explains the reversion family's gross losses with market orders (§6). |
| Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, JPM 40(5) | correct Sharpe for the number of trials and non-normality | Already the gate's first test. |
| Bailey, Borwein, López de Prado & Zhu (2017), *The Probability of Backtest Overfitting*, J. Computational Finance 20(4) | CSCV estimate of PBO | Already in the gate; PBO 0.02–0.04 here. |
| Harvey, Liu & Zhu (2016), *…and the cross-section of expected returns*, RFS 29(1) | multiple testing demands t ≈ 3 | The promotion gate's 3.31 bar follows the same logic. |
| Almgren & Chriss (2000), *Optimal execution of portfolio transactions*, Journal of Risk 3(2) | execution cost depends on urgency and size | Basis for H1/H2: slippage is the only reducible friction. |

### 7.3 The approaches the brief lists, assessed against this module

| Approach | Already here? | Evidence in this data | Verdict |
|---|---|---|---|
| Momentum / trend following | 10 families × 3 timeframes | raw edge up to +7.5 bp at 45m/1h; never enough after friction | keep the best 3 as an **execution-cost** experiment (H1) |
| Breakout / volatility expansion | Donchian, Keltner, PDH/PDL, opening-range close | Donchian best of all; the rest below friction | same as above |
| VWAP | VWAP reclaim (trend) and VWAP reversion | reclaim +6.52 raw at 1h; reversion negative raw on every timeframe | keep reclaim-1h in H1; VWAP is also the right **benchmark** for measuring slippage |
| Mean reversion | 7 families | negative or tiny raw edge; pays the liquidity premium | retire; retest only as **passive limit entries** (H2) |
| Opening range / time of day | ORB, gap, opening-range close; entries after 09:45 | afternoon entries worst (−4.2 to −4.8 bp gross after 12:30) | stopping entries at 12:30 lifts average gross from −3.49 to −2.96 bp — still negative, not a fix on its own |
| Regime detection, adaptive selection | NIFTY filter (removed) | every ex-ante regime negative | **do not build**: there is no regime to switch into |
| Liquidity and spread filters | top-200 universe | liquidity not binding (≤ 0.083% of daily value) | spread *is* the slippage term — measure it (H1) |
| Volatility-adjusted sizing | fixed ₹10 lakh, ATR stops | risk per trade varies with ATR% | reweights a negative edge; implement only for a strategy that passes |
| Portfolio exposure, correlated risk | tournament: ≤ 2 strategies per symbol, 3% daily breaker | Patterns: none (D2) | fix Patterns (C2) |
| Execution optimisation | none | charges fixed, slippage 5.17 bp modelled | **the only lever with arithmetic behind it** (H1, H2) |

---

## 8. Prioritised upgrade plan

Confirmed defects are **C-items**, improvements are **I-items**, experimental hypotheses are **H-items**. Nothing here adds a strategy, and nothing changes the tournament's rules.

### C1 · Patterns: fill like the tournament — Critical

- **Problem / evidence:** D1. +₹52.9 lakh reported, −₹23.1 lakh corrected.
- **Root cause / impact:** `_manage` compares a polled LTP to the levels and closes *at that LTP*; path between polls is unseen; no slippage. Every figure the desk publishes — and every pick made from its leaderboard — is overstated.
- **Solution:** move the tournament's fill functions into a shared module and call them from both engines: `_minutes`, `_scan_exit`, `_adverse` and `slippage_bp` from `intraday_v2_engine.py` into a new `intraday_fills.py`. In `_manage`, replace the LTP comparison with `_scan_exit(p)` over the stream's minute bars since `checked_through`, fill targets at the level (limit) and stops/time/end-of-day at the market with `_adverse`. Apply entry slippage in `_open`. Record `fill_basis`, `exit_basis`, `slippage_bp`, `ltp_source`, `checked_through` on every position.
- **Files:** new `backend/app/services/intraday_fills.py`; `intraday_v2_engine.py` (import from it, behaviour unchanged); `intraday_pattern_engine.py` (`_open`, `_manage`).
- **Steps:** (1) extract the four functions verbatim, re-import in `intraday_v2_engine` and prove no behaviour change with the v2 tests; (2) wire into `_manage`; (3) when the stream has no minute bars for a name, fall back to quotes and label the fill, exactly as the tournament does; (4) recompute the 3,913 historical rows with the corrected model into new fields (`reported_*` kept for audit), never overwriting in place; (5) relabel the page.
- **Benefit / trade-off:** the desk's numbers become comparable with the tournament's. The reported P&L will fall sharply — that is the point.
- **Dependencies / complexity:** stream coverage of the 25 names; medium.
- **Edge cases:** gap through both levels in one minute (stop first, at the open); stream gap (fall back to quotes, labelled, as v2 does); a position opened and closed inside one minute.
- **Tests:** unit — target filled at level, not beyond; stop first when one minute crosses both; open beyond a level fills at the open; slippage on market fills only. Regression — v2 behaviour identical after the extraction.
- **Acceptance:** 0 rows with `exit_reason = target` and an exit beyond the target; 100% of market fills carry `slippage_bp`; replaying the 3,913 trades reproduces the −₹23.1 lakh ±5%.

### C2 · Patterns: risk caps — Critical

- **Problem / evidence:** D2 — 88% duplicated bets, ₹3.18 crore on one idea.
- **Solution:** in `scan`/`_open`: at most 2 strategies per (symbol, side) open at once (the tournament's rule); a per-strategy slot limit; a desk daily-loss breaker at 3% of desk capital (the tournament's `DAILY_LOSS_BREAKER_PCT`); rank competing signals by the rule's own priority, never by catalog order.
- **Files:** `intraday_pattern_engine.py` (`scan`, `_open`); reuse the breaker helper from `intraday_v2_engine._entries_allowed`.
- **Tests:** two hundred simultaneous signals on one symbol open at most two positions; breaker trips at −3% and blocks entries only, never exits.
- **Acceptance:** max cluster size ≤ 2 over a full session; no entries after the breaker trips.

### C3 · Live Trading: a ledger that matches the broker — Critical

- **Problem / evidence:** D5 — no charges on any real trade; 49 of 78 closed by the broker and booked at an estimated price.
- **Solution:** (1) charge `angel_fees.round_trip` on every real close in `_close_real` and in the stale-session path of `_manage_cycle`, storing `fee_breakdown`; (2) run `reconcile_fills` **before 15:30 IST every session** (Angel's trade book is same-day only), writing the broker's actual fill price and order id for both legs — including auto-square-off fills, which should appear in the same-day trade book (verify on the first occurrence) — and replace the stale-session branch's next-day LTP with that fill; (3) one-off: reconstruct 10–20 August from Angel's contract notes into an audited correction document (never overwrite the original rows; add `contract_note_*` fields).
- **Files:** `live_trading_engine.py` (`_close_real`, `_manage_cycle`, `reconcile_fills`, the scheduler that calls it).
- **Edge cases:** partial fills (sum the trade-book legs); an order rejected after the position was recorded (mark `orphaned`, never silently close); the broker square-off charge as a separate line.
- **Tests:** stubbed trade book → reconciled price replaces the estimate; charges present on every closed real position; reconciliation idempotent.
- **Acceptance:** 100% of real closes carry `fee_breakdown` and a broker fill price; ledger net equals the contract-note net to the rupee for every reconciled day.

### C4 · Live Trading: arming requires a confirmed verdict — Critical

- **Problem / evidence:** real orders were placed on strategies with no surviving validation.
- **Solution:** `set_armed(True)` refuses unless every enabled strategy has a `CONFIRMED` verdict in `intraday_v2_registry` (or the registry of the desk it comes from), the ledger reconciled cleanly for the last 20 sessions (C3), and the kill switch is clear. The refusal message says which strategy failed which test. Keep a manual override only behind an explicit, logged `override_reason`.
- **Files:** `live_trading_engine.set_armed`; the route that calls it.
- **Acceptance:** with today's data, arming is refused and names all eight strategies.

### C5 · Pattern Books: write `closed_on`, inherit corrected fills — High

- **Solution:** in `_close_mirror`, set `closed_on` (IST date of the close) alongside `closed_at`; once C1 lands, the copied `exit_price` is the corrected one. Backfill `closed_on` on the 416 existing rows from `closed_at`. Label the books "picks unvalidated" until H4 completes.
- **Acceptance:** every closed book row has `closed_on`; per-day views populate.

### C6 · Memory: bound the pattern cache by bars — High

- **Solution:** in `_prune_cache`, evict oldest entries until `bars_held` ≤ `PAT_CACHE_MAX_BARS` (default 60,000), keeping the entry cap as a secondary limit. Separately, take one heap profile of the backend (tracemalloc or memray) at peak to attribute the remaining ~700 MB — this audit did not, and the cache alone does not explain it.
- **Acceptance:** `cache_stats().bars_held` never exceeds the cap; backend under 80% of its limit through a full session with no `memory_high` alarm.

### C7 · Alarms resolve across sessions — Medium

- **Solution:** in `intraday_ops._set`, resolve by kind (`update_many({"kind": kind, "active": True}, …)`) and `$unset` `resolved_at` when re-raising.
- **Acceptance:** one active alarm per kind at most; no `resolved: false` row carrying a `resolved_at`.

### I1 · Stop paper-trading the 42 DISABLE strategies — High

- **Why:** two years say they cannot cover charges even at zero slippage. Paper-trading them adds noise to the page, load to the backend, and nothing to the evidence.
- **How:** remove them from the live tournament's active set (a list, not a code deletion); keep them in the backtest catalog so the two-year record stays reproducible. Note honestly: dropping them after looking does **not** lower the bar for the survivors in hindsight — a fresh, pre-registered forward test does (H1 → registry).

### I2 · Page honesty — High

- Label Patterns and the Pattern Books "unvalidated · fills not modelled" until C1; show "Market closed (weekend)" instead of a raw heartbeat age when the session is closed; add a friction tile to the tournament (raw edge vs slippage vs charges, from §3.4) so the reason for the loss is visible, not inferred.

### I3 · Gate additions — Medium

- In `intraday_v2_backtest.py`, report per strategy: a **per-session clustered** t-stat beside the per-trade one; break-even slippage; and net at 0.5× and 1.5× the modelled slippage. Store them in the run document.
- **Acceptance:** the nightly run document carries all three for every strategy.

### I4 · Recalibrate slippage — Medium (after H1)

- Replace the turnover buckets in `slippage_bp` with a model fitted to H1's measured fills by turnover band and order size, and fix the "₹2 lakh" docstring (D9).

### H1 · Measure real execution cost for the three OPTIMIZE strategies — the one experiment that could change the verdict

- **Hypothesis:** real per-side slippage on ₹10 lakh market orders in the names `donchian_45m`, `donchian_1h` and `vwap_trend_1h` trade is below their break-even (1.80 / 1.50 / 1.29 bp).
- **Method:** at every live signal of the three, capture Angel's market depth (best five levels, quote mode `FULL`) at the decision moment, and compute the volume-weighted price to fill ₹10 lakh against the visible book on both entry and exit. No orders. Pre-register the thresholds below before collecting.
- **Sample:** ≥ 300 signals across the three (about three weeks at their backtest rate of 7–8 a session each).
- **Go:** median measured cost ≤ 80% of each strategy's break-even → register that strategy in incubation with its measured slippage. **No-go:** otherwise — the module has no tradeable strategy and the decision becomes "keep as research record".

### H2 · Passive entries — experimental

- **Hypothesis:** entering the H1 strategies (and, separately, the reversion family) with a limit order at the signal level instead of a market order removes most of the entry slippage.
- **Risk to test, not assume:** adverse selection — a passive order fills more often when the price is moving against it, and misses the best moves entirely. Requires a fill simulator that queues behind displayed size; pre-registered; walk-forward.

### H3 · The `orb_inplay_10` mirror — experimental

- The only one of 52 mirrors positive after friction (+4.76 bp, 1,694 trades). It was found by selecting the most extreme of 52, which inflates it exactly as selecting the best would. Pre-register, then forward-test only.

### H4 · Put Patterns through the gate — after C1, C2

- Replay the 504 through the same walk-forward machinery (DSR, PBO, holdout, gate). Note the cost: 504 trials push the Bonferroni bar to about 3.9 — expect nothing to pass, and retire the desk if nothing does.

### H5 · Intraday periodicity — low priority

- Heston, Korajczyk & Sadka (2010). Cheap to test with the stored 15m history; implement only if it shows a raw edge several times the 6–9 bp friction.

---

## 9. Backtesting and validation methodology

What exists and should be preserved: point-in-time universe; the live rule functions replayed unchanged; minute-bar fill walk with stop-first, gap fills and limit targets; Angel's real card; selection / holdout split with thresholds written per run; DSR and PBO; pre-registered incubation with frozen thresholds; optimistic fills computed only as a labelled bound.

What to add: I3 (clustered t, break-even slippage, slippage sensitivity); H1's measured slippage feeding the model (I4); the same machinery for any desk that publishes performance (H4). And one rule: **no desk shows P&L as performance unless it has passed through this pipeline** — otherwise it is labelled as unvalidated.

Combined performance: strategies compete for the same names and the same rupees. Any strategy that passes must be re-run inside the portfolio pass with the live caps (≤ 2 per symbol, five slots, the daily breaker) before incubation, and the combined book's DSR reported — individual profitability does not imply portfolio profitability.

---

## 10. Risk management and capital protection

| Safeguard | Tournament | Patterns | Live Intraday (paper) | Live Trading (real) |
|---|---|---|---|---|
| Risk per trade | ₹10 L slot, ATR stop | ₹10 L, % stop | slice of book | ₹10k per strategy |
| Daily loss limit | 3% breaker | **none** (C2) | 3% breaker per book | breaker state exists |
| Concurrent positions | 5 slots per strategy | **none** (C2) | capital slice per strategy | ₹80k ceiling |
| Correlated exposure | ≤ 2 strategies per symbol | **none** — 32 on one name (C2) | 8 picks ≈ 4 ideas (D6) | same 8 |
| Liquidity limits | top-200 universe | top-25 | top-150 scan | top-150 scan |
| Gap / circuit handling | gap fills at the open | **none** (C1) | quote-based | broker fills |
| Duplicate-order prevention | n/a (paper) | n/a | n/a | order id stored on entry; **missing on 49 exits** (C3) |
| Partial / rejected orders | n/a | n/a | n/a | reject counter exists; partial fills not summed (C3) |
| Stale data | stream age check | polled quotes; the path between polls is unseen (C1) | quote-based | stale-session reconcile at the *next* session's price (C3) |
| End-of-day | shared CAS-aware close-out loop | shared close-out | shared close-out | **missed on 19–20 Aug**; broker squared off |
| Capital / margin reconciliation | n/a | n/a | n/a | Angel balance read; ledger lacks charges (C3) |
| Kill switch | n/a | n/a | n/a | exists (`panic_close_all`, `set_kill_switch`) |
| Arming | n/a | n/a | n/a | manual; **no validation precondition** (C4) |

The two gaps that can lose real money are C3 and C4. Everything else is paper.

---

## 11. Phased roadmap

| Phase | Work | Status | Deliverable | Go / no-go |
|---|---|---|---|---|
| 1 · Code audit | map, trace, baseline | **done** (this document) | §2–§6 | — |
| 2 · Data and backtest audit | fills, costs, leakage, survivorship | **done** for the tournament; Patterns has none to audit | §3.5, §3.6 | — |
| 3 · Critical fixes | C1–C4, then C5–C7 | to do | tests green; acceptance criteria met | Live Trading stays disarmed until C3 and C4 pass |
| 4 · Strategy research | H1 (first), then H2–H5 | to do | pre-registered protocols, then measurements | **H1 no-go ends strategy work**: record kept, no capital |
| 5 · Independent validation | walk-forward gate + I3 + portfolio pass | machinery exists | run document per candidate | DSR ≥ 0.95, PBO ≤ 0.5, holdout positive, clustered t ≥ 2 |
| 6 · Paper incubation | registry, frozen thresholds | machinery exists | CONFIRMED / FAILED verdict | ≥ 40 forward trades, forward t ≥ 2, z ≥ −1 vs expectation |
| 7 · Controlled real money | ₹10k per strategy | blocked by C3, C4 | daily reconciliation vs contract notes | CONFIRMED verdict, 20 clean reconciled sessions, max loss defined in advance |
| 8 · Continuous improvement | live vs backtest drift | — | weekly drift report | disarm on the registry's FAILED rule (forward mean ≥ 2 standard errors below expectation; early stop at z ≤ −3 from 20 trades) |

The likely outcome, stated plainly: Phase 4's H1 decides whether Phases 5–7 have anything to work on. If measured slippage exceeds the break-even, the honest end state is a well-instrumented research record, not a trading desk.

---

## 12. Required tests and acceptance criteria

| Item | Unit | Integration / regression | Quantitative acceptance |
|---|---|---|---|
| C1 | level fills, stop-first, gap fills, slippage only on market fills | v2 unchanged after extraction; replay 3,913 Patterns trades | 0 target exits beyond target; replay −₹23.1 lakh ±5% |
| C2 | cap 2 per (symbol, side); breaker blocks entries not exits | full simulated session | max cluster ≤ 2 |
| C3 | charges on every real close; reconciled price replaces estimate; idempotent | stubbed Angel trade book incl. auto-square-off | ledger = contract notes to the rupee |
| C4 | arming refused without CONFIRMED | route test | refused today, naming all eight |
| C5 | `closed_on` written | backfill 416 rows | 100% populated |
| C6 | cache evicts by bars | 1 session under load | bars ≤ cap; RSS < 80% |
| C7 | resolve by kind | across a midnight | ≤ 1 active per kind |
| I3 | clustered t, break-even slippage | nightly run | fields present for every strategy |
| H1 | depth-walk cost calculator against a hand-computed book | ≥ 300 live signals | pre-registered go / no-go |

Every number in §3 and §5 should be reproducible from `backend/research/intraday_2026_10/` within rounding; a change to the cost model or fill model that moves them is a regression to explain, not to accept.

---

## 13. Expected benefits, trade-offs and unresolved risks

**Benefits.** The main benefit is truth: the page stops publishing profits that do not exist, and real money cannot be armed on strategies that have not earned it. Operationally, C6 and I1 reduce memory pressure and noise.

**What profitability to expect — conditional arithmetic, not a forecast.** For the best candidate, `donchian_45m` (≈ 7.9 trades a session on ₹50 lakh of strategy capital):

| Real slippage | Net per trade | Per year (~248 sessions) | On ₹50 lakh |
|---|---:|---:|---:|
| as modelled (~2.76 bp a side) | −1.85 bp | −₹3.6 lakh | −7% |
| half | +0.80 bp | +₹1.6 lakh | +3% |
| zero (impossible with market orders) | +3.46 bp | +₹6.7 lakh | +13% |

Even the favourable case is about a fixed-deposit return, carried with intraday risk. Anyone hoping this module becomes a meaningful income source should weigh that before investing more build time.

**Trade-offs.** C1 will make the Patterns tab look much worse; I1 removes most of the tournament's activity; C4 makes arming harder by design.

**Unresolved risks.**
- The slippage model is the largest open assumption, in both directions (D9, H1).
- The pre-5-October history is lost unless an Atlas snapshot exists.
- Real charges for 10–20 August are unknown until the contract notes are read.
- The backend's memory pressure is not fully attributed (C6).
- Four sessions of live data cannot validate anything; only time can.

---

## 14. Final decisions

| Component | Decision | Why |
|---|---|---|
| Tournament engine, backtest, gate, registry | **KEEP** unchanged | verified sound; it is the module's source of truth |
| `donchian_45m`, `donchian_1h`, `vwap_trend_1h` | **OPTIMIZE** via H1 | real raw edge (t 3.5–4.0), positive holdout, break-even slippage 1.3–1.8 bp |
| 7 RESEARCH ONLY strategies | **KEEP in the backtest record**, no paper capital | raw edge exists, below friction |
| 42 DISABLE strategies | **DISABLE** from live paper (I1) | charges exceed edge even at zero slippage, or no edge at all |
| `orb_sel15`, `orb_sel30` | **INCUBATE**, untouched | pre-registered; forward record decides |
| Patterns · 504 | **FIX** (C1, C2), then **VALIDATE** (H4) or **RETIRE** | fills overstate; no caps; no validation |
| Paper Trade ₹50k / ₹2 lakh | **FIX** (C5), re-pick after H4 | inherits D1; picks ranked on overstated figures |
| Live Intraday shortlist | **DISABLE** as a real-money shortlist | ~4 ideas, retired catalog, swing rules intraday, evidence destroyed |
| Live Trading (real money) | **KEEP DISARMED**; **FIX** (C3, C4) | ledger lacks charges and broker fills; no validation precondition |
| Operations | **FIX** (C6, C7, I2) | memory pressure, stale alarms, misleading labels |

---

## Appendix — reproduction

All scripts are read-only and run inside the backend image (`docker exec -e PYTHONPATH=/app/backend alpha-engine-backend-1 python <script>`). See [`backend/research/intraday_2026_10/README.md`](backend/research/intraday_2026_10/README.md) for what each settles. The walk-forward trades file is regenerated nightly; the figures here are from run `20261010-0605`.
