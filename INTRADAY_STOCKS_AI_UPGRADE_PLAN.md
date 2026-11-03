# Intraday Stocks — Gates and AI: 10-Phase Upgrade Plan

**Written:** 4 November 2026 · **Status:** approved by the owner, who asked for all ten phases to be built in one go. Progress is tracked in §8.
**Builds on:** [INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md](INTRADAY_STOCKS_RESEARCH_AND_UPGRADE_PLAN.md) (October 2026). Item codes such as I3, I4, H1, H2, C3 and C4 refer to that plan.

---

## 0. Summary

The goal is intraday stock trades that make money after costs, and evidence strong enough to trust them. The module already has 54 fully specified strategies and a strict testing pipeline. It does not yet have a tradeable edge:

- **The signals carry a small, real edge that is smaller than the cost of trading it.**
  - Over two years, six rules earn 4–7.5 bp a trade before costs, and each clears t ≥ 3.31.
  - A ₹10 lakh market order costs about 4 bp in charges, plus 3.0–3.4 bp of slippage on each side. H1 measured this and returned NO-GO.
- **The leaderboard ranks luck.**
  - From 6 Oct to 3 Nov the Rank top 10 made +2.75% on paper.
  - The same rules, replayed, made −0.35%, or +0.54% with the live engine's rules modelled.
  - The difference came from which signals got the five slots, not from better signals.
- **No strategy passes the gate.** 0 of 54 are READY; the best t-stat is 1.68 against a bar of 3.31. Real money stays locked.

The plan works on the gap from three sides:

1. **Pay less to trade:** honest costs, limit orders, and order sizes the book can absorb (Phases 1 and 3).
2. **Take better signals:** risk gates, a move-size model, market and sector context, an AI signal scorer, and news/event flags (Phases 4–8).
3. **Prove it before money:** a research harness, pre-registered tests, forward paper tests and automatic demotion (Phases 2, 9 and 10).

**Realistic upside.** If everything works, the best rules may net a few bp a trade. The October plan worked out the best case: the best rule at zero slippage earns about +13% a year on ₹50 lakh, which is a modest return carried with intraday risk. This is a research programme with stop rules (§5), not a promise of profit.

---

## 1. Starting point (3–4 Nov 2026)

### 1.1 Evidence

| Fact | Number | Source |
|---|---|---|
| Two-year replay, 153,403 trades | After slippage, gross −3.49 bp a trade; with no costs at all, +1.67 bp. 0 of 25 months positive; every market condition negative | backtest run `20261010-0605` |
| Rules with a real edge before costs (t ≥ 3.31) | `donchian_45m` +7.48 bp, `donchian_1h` +6.94, `vwap_trend_1h` +6.52, `macd_trend_1h` +5.64, `rsi_momentum_45m` +5.18, `bollinger_snap_1h` +4.20 | `backend/research/intraday_2026_10/ids_strategy_table_out.md` |
| Real cost of a ₹10 lakh market order (H1, 3,355 entry samples) | Median 3.0–3.4 bp a side. The visible book was too thin to fill the order in 52–56% of signals. NO-GO for all three rules tested | `intraday_h1_samples`, `h1_slippage.report()` |
| Paper slippage model | about 2.76 bp a side, which undercharges | `intraday_fills.slippage_bp` |
| Live tournament, 6 Oct – 3 Nov | −1.36% on ₹27 crore (8,109 trades) | `intraday_lab_positions` |
| Rank top 10, same period | Live +2.75%. Backtest −0.35%, or +0.54% with the live rules. 315 of the 1,091 live trades were reproduced, rising to about 645 with the live rules | comparison of 3 Nov |
| Verdicts | 50 REJECTED, 4 PENDING, 0 READY. Registry: `orb_sel15` and `orb_sel30` INCUBATING | `intraday_lab_scores`, `intraday_v2_registry` |
| What is predictable | How far a stock will move (expected-move model, held-out rank IC 0.30), but not which way | stock-selection research, S2 |
| Drift in these 200 stocks | overnight +13 bp a day; intraday −7.5 bp a day | stock-selection research |

Only one of the current Rank top 10 (`macd_trend_1h`) is among the six rules with a real edge before costs.

### 1.2 The ten gates today, and the phase that closes each

| # | Gate | Today | Closed by |
|---|---|---|---|
| 1 | Scan and select stocks | **Done.** Each day's top 200 by 20-day traded value is stored | Phase 5 (better move model) |
| 2 | Market suits the strategy | **Not built.** The NIFTY-direction filter has been off since 2 Oct | Phase 6 |
| 3 | Fully specified strategy | **Done** | Phase 1 (rule versions) |
| 4 | Validate before live | **Done, strict** | Phases 2 and 10 |
| 5 | Risk-based position size | **Not built.** Every position is ₹10 lakh | Phases 4 and 5 |
| 6 | Reward, cost and exposure checks | **Partly** | Phases 4 and 7 |
| 7 | Daily loss and drawdown limits | **Partly.** A 3% daily stop exists; there is no drawdown limit | Phase 4 |
| 8 | Execution checks | **Partly** | Phases 3 and 4 |
| 9 | Record every decision | **Partly.** Rejected signals are only counted | Phase 1 |
| 10 | Review and demote | **Partly.** Nothing is paused automatically | Phase 9 |

---

## 2. Principles for every phase

1. **The tournament stays the control.** Its rules don't change. New behaviour goes into new paper books and research jobs, behind flags. The one exception is honest costs (Phase 1), with a dated cutover.
2. **Pre-register every test before looking at results.** Write down the hypothesis, metric, sample size and decision rule, and fingerprint them, as H1 did. The most recent 6 months of history are the holdout, opened once per test.
3. **Judge by net profit per trade after measured costs, not by win rate.** A test passes only through walk-forward, the holdout, DSR/PBO and a clustered t-stat, then a forward paper test.
4. **Two kinds of AI, each in its own lane.**
   - Trained machine-learning models, built on our own data, produce numbers: move size, signal score, execution cost.
   - LLMs (Claude or ChatGPT) read text: announcements, news, reviews. An LLM never predicts prices and never places or approves a trade.
5. **Everything point-in-time.** Every feature carries the time it became known. Replays use stored values, never a fresh lookup made with hindsight.
6. **Heavy work stays off the server.** Training and large replays run on the PC; the backend sits near its 800 MB memory limit. The server only does light scoring.

---

## 3. The ten phases

| Phase | Name | Gates | AI | Needs | Rough build time | Decision at the end |
|---|---|---|---|---|---|---|
| 1 | Decision ledger and honest costs | 9, 3, 8 | — | — | 1–2 weeks | Is the ledger complete? Do paper costs match measured costs? |
| 2 | Research harness and backtest fidelity | 4 | — | 1 | 2 weeks | Does the backtest reproduce live trading? Is the two-year signal dataset built? |
| 3 | Execution: limit orders and order size | 8 | ML cost model | 1, 2 | 2–3 weeks | GO / NO-GO per rule |
| 4 | Gated paper account | 5, 6, 7, 8 | — | 1 | 2 weeks to build, then 1 month of running | Keep or drop each gate |
| 5 | Move-size model and big-mover filter | 1, 5 | ML model 1 | 2 | 2 weeks | Adopt the model? Filter GO / NO-GO |
| 6 | Market and sector context | 2 | — | 2 | 2 weeks, plus forward data | Context gate GO / NO-GO; features ready |
| 7 | AI signal scorer | 6 | ML model 2 | 2, 3, 5, 6 | 3–4 weeks | GO → incubation; NO-GO → stop AI signal work |
| 8 | News and events | 2, 8 | LLM | 1, 6 | 3 weeks, plus data | Provider chosen; event gate GO / NO-GO |
| 9 | Daily review and automatic demotion | 10 | LLM | 1, 4 | 2 weeks | Report running; demotion rules enforced |
| 10 | Forward test and real-money bridge | 4, 7 | — | any GO from 3–8 | 3 months or more | CONFIRMED / FAILED per candidate |

**Order of work:**
- Phases 1 and 2 come first.
- Phase 4 can be built alongside Phases 2 and 3.
- Phases 3, 5 and 6 can run in parallel once Phase 2 is done.
- Phase 7 needs Phases 5 and 6.
- The data collectors for Phases 6 and 8 should start during Phase 1, because they need forward time to build up history.

### Phase 1 — Decision ledger and honest costs

**Goal.** Every signal leaves a full record, and paper fills cost what real orders cost.

**Build**
- **Signal ledger** (`intraday_signal_ledger`, new). One row for every candidate signal at every bar close, whether taken or not. Each row holds:
  - the time, strategy id, rule fingerprint, symbol and side;
  - the signal price, stop, target and priority;
  - universe metrics (turnover and rank) and a snapshot of the context available then;
  - every gate's result, the rejection reason, and the slot and cash state;
  - the position id, if the signal was taken.
  Rows are written in batches.
- **Storage.**
  - Use the server's **local MongoDB** (as the Strategy Factory does), not Atlas: Atlas M0 is near its 512 MB quota.
  - Expect about 3,200 candidates a day, a few MB a day.
  - The server disk is 96% full, so free space first and set a retention period (for example, 12 months of raw rows).
- **Versions.** Give each strategy's rules and each gate configuration a fingerprint, and stamp it on ledger rows and positions. A change creates a new version; nothing is edited in place.
- **Honest costs (October plan I4).**
  - Replace the turnover-bucket slippage with H1's measured costs, by turnover band and order size. Charge the 10%-trimmed mean, not the median: a cost model must charge the average, and these costs are right-skewed.
  - Exception: the two pre-registered strategies (`iv2_orb_sel15`, `iv2_orb_sel30`) keep the cost model their expectation was written under, so their forward test isn't moved mid-way.
  - Show the cutover date on the page, and never compare P&L across it.
- **Start the slow data collectors now** (F&O ban list, bulk and block deals, corporate announcements; see Phases 6 and 8), so forward history builds up.
- **Coordinate first.** Another session has uncommitted changes in `intraday_v2_engine.py` and `angel_stream.py` (a scanner re-check and fill-evidence rules). They must be committed or handed over before this phase edits the engine.

**Done when**
- Ledger rows equal signals evaluated (100%, checked daily against the engine's skip counters) for 5 sessions.
- Backend memory is no higher than before (`/api/diagnostics/memory`).
- Paper costs equal H1's measured averages by turnover band (1.50 / 2.85 / 3.73 / 4.12 bp a side on ₹10 lakh).

### Phase 2 — Research harness, backtest fidelity and pre-registration

**Goal.** One trustworthy, repeatable way to test any idea on two years of history, matching how the live engine behaves.

**Build**
- **Research harness** in `backend/research/intraday_ai/`. This makes the off-server setup used on 3 Nov permanent:
  - Exports run in a throwaway container on the server, so the database credential never leaves it.
  - The server's exact code is copied and md5-checked.
  - The replay runs on the PC.
- **Backtest fidelity**, as an option (`--live-rules`) so the nightly gate stays unchanged until it is reviewed:
  - The live engine's two-strategies-per-stock cap, and ranking of every strategy's signals together at each bar close. Both are missing today; adding them doubled the trades reproduced on 3 Nov.
  - Measured costs from Phase 1.
  - October plan I3: a clustered t-stat, break-even slippage, and cost sensitivity.
- **Fidelity check.** Replay the live period. The targets:
  - at least 60% of live trades reproduced;
  - at least 95% of shared trades closing for the same reason.

  On 3 Nov, about 59% of trades were reproduced with the live rules, and nearly all shared exits matched.
- **Two-year signal dataset.** Every candidate signal of all 54 rules, focusing on the six. Each signal is stored with the features available at its time and its outcomes:
  - gross;
  - net at the measured market-order cost;
  - net with a limit entry (from Phase 3).

  This is the training data for Phases 5–7.
- **Pre-registration register** in `backend/research/intraday_ai/prereg/`: JSON plus a fingerprint, committed to git **before** each test runs. The git history is the timestamp.

**Done when**
- For every row of the dataset, each feature was known before the signal time (100%).
- The fidelity targets are met.
- The register is in use.

### Phase 3 — Execution: limit orders and order size

**Goal.** Stop paying more to trade than the signal earns (October plan H2).

**Build and test**
- **Limit-entry simulator** on the stored 5-minute history (219 instruments):
  - Post a limit at the signal price.
  - It fills only if a later bar trades through it by at least one tick, a cautious assumption about the queue.
  - Cancel after a set number of minutes.
  - Targets are already limit orders; stops stay market orders.
- **Measure per rule:**
  - fill rate;
  - the winners missed;
  - adverse selection, meaning how much worse the filled trades do than all signals;
  - net after charges.
- **Pre-registered decision for each of the six rules.** GO if all three hold:
  - holdout net after charges is above 0;
  - the clustered t-stat is at least 2;
  - the fill rate is at least 40%.
- **Cost model (machine learning).**
  - It predicts a market order's cost from the spread, depth coverage, turnover, volatility, time of day and order size.
  - It is trained on H1's ~3,355 entries plus the new recorder.
  - Live, it chooses between market and limit orders and caps the order size at what the visible book can absorb.
- **New depth recorder.** It records both sides' five-level prices **and quantities** at every signal of the six rules, which gives order-book pressure features for Phase 7. It is kept separate from H1, which is pre-registered and must not be edited.

**Done when**
- Each of the six rules has a GO or NO-GO.
- The cost model beats H1's median on held-out samples.
- The recorder is running.

### Phase 4 — Gated paper account

**Goal.** A paper account that behaves like a careful real account, run beside the existing ungated ones, so the gates' effect is measured on live data.

**Build.** New paper books copy tournament signals (the tournament itself is unchanged) through these gates:
- **Gate 5 — size by risk:**
  `shares = floor(min(risk budget ÷ (entry − stop + cost per share), cash ÷ entry))`.
  The risk budget is configurable, for example 0.5% of the book per trade.
- **Gate 6 — reward and exposure:**
  - a minimum reward-to-risk after costs;
  - a maximum number of open positions;
  - a maximum total open risk (for example, 3% of the book);
  - one position per stock;
  - a maximum per sector. NSE industry labels are already stored in `fundamental_universe`.
- **Gate 7 — account limits:** the daily loss stop, plus a drawdown limit (for example, pause new entries at −8% from the peak until reviewed). Exits always keep running.
- **Gate 8 — execution:**
  - a fresh, exchange-timestamped quote;
  - the spread under a limit;
  - an order no larger than the visible depth (from Phase 3).
- **Logging and settings.** Every accept and reject goes to the ledger with its reason. Gate settings are versioned and held fixed for the comparison month.
- **Two books:**
  - **A**, which takes all tournament signals, to measure the gates' effect alone.
  - **B**, which takes only the six rules with a real edge before costs. This is the future real-money candidate.

  Neither book picks strategies from the Rank top 10.

**Test (pre-registered).** After at least 20 sessions, compare book A with the ungated ₹10 lakh book on four measures:
- net;
- maximum drawdown;
- worst day;
- net ÷ drawdown.

Keep a gate only if it cuts drawdown by more than it costs in net.

**Done when.** Both books have run at least 20 sessions, and each gate has a decision.

### Phase 5 — AI model 1: move-size forecast and the big-mover filter

**Goal.** Trade where moves are big enough to pay the costs, and size positions by the expected range.

**Build and test**
- **Upgrade the scanner's expected-move model** in `scanner_board.py`. Today it is a linear regression with a held-out rank IC of 0.30.
  - Replace it with a gradient-boosted model on richer point-in-time features: relative volume, ATR %, gap, first-30-minute range, India VIX, results day, sector move, pre-open data, expiry proximity and day of week.
  - Train it walk-forward on the PC.
- **Adopt it only if it beats the linear model by a pre-registered margin** (for example, +0.03 rank IC walk-forward, holding on the holdout). Otherwise keep the linear model.
- **Big-mover filter test** on the six rules: take a signal only if the stock is among today's top-K expected movers. K is fixed in the pre-registration, and the test runs with both market and limit execution.
- **Sizing:** the expected range sets the stop distance and the position size (equal risk per trade) in the gated books.
- **Keep live scoring light:** ship the trained model as a small file evaluated in plain Python or NumPy. No heavy ML library goes on the server.

**Done when.** The model is adopted or rejected, and the filter has a GO or NO-GO for each rule.

### Phase 6 — Market and sector context (gate 2)

**Goal.** Record the market picture behind each signal, and test whether any context really helps.

**Build**
- **Context features at every signal:**
  - NIFTY's return since the open, and its trend;
  - the stock's sector index against NIFTY (15-minute bars for 17 sector and broad indices are already stored), and the stock against its sector;
  - India VIX level and change;
  - breadth across the 200 stocks;
  - time of day;
  - results day (the calendar is already collected) and expiry day;
  - daily FII/DII F&O positions;
  - the previous day's delivery %;
  - the overnight gap.
- **New collectors, started in Phase 1:** F&O ban list, bulk and block deals, and index rebalance announcements. Also intraday stock-futures open interest, which can only be collected forward; there is no history.
- **Test (pre-registered, per strategy family).** Write down a short list of hypotheses first, for example "trend rules only when the stock's sector moves the same way". The odds are low, since every market condition lost money over two years, so adopt only what passes.
- **All features feed the Phase 7 scorer**, whether or not a context gate passes.

**Done when.** The feature store passes point-in-time tests, and each context hypothesis has a GO or NO-GO.

### Phase 7 — AI model 2: the signal scorer

**Goal.** Estimate each signal's profit after costs. Take the good signals, skip the rest, and fill the five slots with the best-scored signals instead of by relative volume.

**Build**
- **Model.** A gradient-boosted classifier (the chance of a net profit after measured costs) and a regressor (expected net bp). It covers the six rules pooled together, with the rule as a feature.
- **Inputs:**
  - the signal's own fields: stop distance, target, priority and time;
  - the Phase 5 expected move;
  - the Phase 6 context;
  - the Phase 3 execution features: spread, depth, and order-book pressure once it is recorded;
  - the Phase 8 event flags, when they are available.
- **Training.**
  - Walk-forward by month: train on everything before a month, then predict that month.
  - Leave a gap so that no trade overlaps the training data.
  - Calibrate the probabilities.
- **Leakage checks.** These must pass before any result is read:
  - shuffled labels show no edge;
  - every feature was known before the signal time;
  - no feature is built from the outcome.
- **Two uses:**
  - **(a) Gate:** take a signal only if its predicted net clears the pre-registered threshold.
  - **(b) Ranking:** order signals that arrive together by score when filling the slots.

**Test (pre-registered).** On the holdout, with both market and limit execution, all of these must hold:
- the scored version's net after measured costs is above 0;
- the clustered t-stat is at least 2;
- DSR is at least 0.95, counting every model and threshold tried;
- the top fifth of scores beats the bottom fifth by at least the cost gap (about 3–4 bp).

**Done when.** GO sends the scored rules to Phase 10 incubation. NO-GO stops AI signal work (decision point D2).

### Phase 8 — News and events with an LLM (Anthropic Claude or OpenAI ChatGPT)

**Goal.** Know what is happening to a company before trading it.

**Build**
- **Data:**
  - NSE corporate announcements, with exchange timestamps;
  - the results and board-meeting calendar (already exists);
  - bulk and block deals;
  - the F&O ban list;
  - a licensed news-headline feed, if one is chosen later.
- **LLM task.** For each announcement, return structured JSON:
  - category (results, order win, rating change, regulatory, management, M&A, …);
  - materiality (low, medium or high);
  - direction of the surprise (positive, negative or unclear);
  - confidence;
  - a quoted line from the text as evidence.

  Each answer is stored once, with the model and prompt version. Replays use the stored answer and never ask again with hindsight.
- **One interface, two providers.**
  - Implement the existing `AIProvider` contract (`shared/tradingai_shared/contracts/ai_provider.py`) for both Anthropic and OpenAI.
  - Choose between them with `AI_PROVIDER=anthropic|openai`.
  - API keys live only in the server's `.env`, never in the repo, which is public.
  - Only public market text is sent to the provider.
- **Choose the provider by testing, not preference.**
  - Hand-label about 300 announcements.
  - Compare both providers, and a cheaper model from each, on accuracy, consistency across repeat calls, cost and speed.
  - Start with each provider's most capable current model. Current Claude model IDs are `claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5` and `claude-haiku-5-5`.
  - Keep a daily spending cap, and use batch processing for anything not time-critical.
- **Three uses:**
  1. **An event-risk gate in the gated books.** No new entry in a stock with a high-materiality announcement in the last N minutes, or with results due today. The pre-registered test asks whether this cuts losses and drawdown without cutting net.
  2. **Event features** for the Phase 7 scorer.
  3. **A research note:** drift over the days after results belongs in a swing module, not intraday.

**Done when**
- The provider is chosen on the labelled set.
- Classification runs within the spending cap.
- The event gate has a GO or NO-GO.

### Phase 9 — Daily AI review, monitoring and automatic demotion

**Goal.** Catch problems the same day, explain results in plain language, and pull back anything that stops working.

**Build**
- **Daily reconciliation job**, which automates the analysis of 3 Nov. It compares the day's live trades with a replay and reports:
  - shared trades and exit agreement;
  - fill and cost differences;
  - gate rejections, by reason;
  - data gaps and stale quotes;
  - model calibration (predicted vs actual).
- **LLM summary.**
  - A short, plain-English daily note that flags anomalies, written from the numbers above. The LLM explains; it does not calculate.
  - Connect the app's existing `/api/ai/*` endpoints (explain trade, detect unusual, summarize news, compare strategies) to the chosen provider. Today they return "not configured", because no key is set.
- **Automatic demotion**, using pre-set, versioned rules. A strategy or model in the gated books is paused, sent back to research and reported to the owner if either happens:
  - its forward mean falls 2 or more standard errors below its pre-registered expectation;
  - its drawdown passes its limit.

**Done when**
- The report is delivered every session for 2 weeks.
- The demotion rules have been tested on replayed history.

### Phase 10 — Forward test, promotion and the real-money bridge

**Goal.** Only rules that keep their edge on new data reach real money, and then only at small size.

**Build and run**
- **Register every GO** from Phases 3, 5, 6, 7 and 8 in `intraday_v2_registry` with a frozen expectation: net bp a trade, execution method and model version. Each runs in gated book B.
- **Sample:** at least 300 forward trades or 3 months, whichever comes later.
- **Verdict:** CONFIRMED only under the registry's rule (forward t ≥ 2, and not significantly below expectation). FAILED otherwise.
- **Real money** is the owner's decision, after CONFIRMED:
  - The live desk's existing arming gate stays in place.
  - Start small, for example ₹10,000–50,000 per strategy, with the same gates.
  - Reconcile daily against Angel contract notes. October plan C3 (a ledger that matches the broker) must be confirmed done first.
  - Test the kill switch.
  - Scale up only after 20 clean, reconciled sessions with real slippage no worse than expected.

**Done when.** Every candidate has a verdict.

---

## 4. AI: Anthropic or ChatGPT — what goes where

| Job | Kind of AI | Where it runs | Phase |
|---|---|---|---|
| Execution cost model | trained regression | trained on the PC, scored on the server | 3 |
| Move-size forecast | trained gradient-boosted model | trained on the PC, scored on the server | 5 |
| Signal scorer | trained gradient-boosted model | trained on the PC, scored on the server | 7 |
| Reading announcements and news | LLM (Claude or ChatGPT) | provider API, batched | 8 |
| Daily review and trade explanations | LLM | provider API | 9 |

LLM rules:
- An LLM never predicts prices, and never places or approves trades.
- It never sees keys or account data.
- Every output is stored with its model and prompt version.
- Spending is capped per day.
- Both providers sit behind one interface, so switching is a setting.

---

## 5. Decision points and stop rules

- **D1, after Phase 3.** If limit entries fail for all six rules, only the scorer can close the gap. Continue Phase 7, but expect less.
- **D2, after Phase 7.** If the scorer fails its holdout, stop AI signal work. Keep the ledger, the gated books and the daily review as risk tools.
- **D3, at the end of Phase 10.** If nothing is CONFIRMED after 3 months of forward testing, the module stays an honest research record. No more build time goes into intraday stock strategies unless a new data source shows a before-cost edge several times larger than the costs.

---

## 6. Guardrails for whoever builds this

- **Leave tested things alone.**
  - Don't change the tournament's rules.
  - Never edit pre-registered experiments: H1 (fingerprint `d50a4bbecfe6e146`), `iv2_orb_sel15` and `iv2_orb_sel30`.
- **Storage limits.**
  - Atlas M0 is near its 512 MB quota, so new high-volume collections go to the server's local MongoDB.
  - The server disk is 96% full; free space before Phase 1.
- **Memory limits.** The backend is near its 800 MB limit.
  - No training on the server.
  - Keep new loops light.
  - Check `/api/diagnostics/memory` after each deploy.
- **Code safety.** Startup hooks must not raise. No exact-count asserts.
- **Shared work.** Another session has uncommitted engine changes. Coordinate before editing `intraday_v2_engine.py` or `angel_stream.py`.
- **The repo is public.** No API keys, passwords or security details in code or docs.
- **Deploying.**
  - Deploy outside market hours (09:15–15:30 IST).
  - Back up and md5-check before deploying.
  - Confirm "startup complete" afterwards.
- **Data.** Never reset or bulk-delete shared data.

---

## 7. What this plan will not do

- Add more indicator rules, or tune parameters on history.
- Ask an AI to read charts or predict prices.
- Rank strategies by one month of paper profit, as the leaderboard does.
- Put money on anything before a CONFIRMED forward verdict.

---

## 8. Progress

| Phase | Status | Notes |
|---|---|---|
| 1 | **Built, tested** (4 Nov 2026) | Decision ledger (`intraday_signal_ledger`, local MongoDB `alpha_engine_intraday`, 180-day retention) with rule and gate versions on every row and position. Measured costs: 1.50 / 2.85 / 3.73 / 4.12 bp a side by turnover band; pre-registered rules on the legacy model. NSE event collectors (`nse_events`: ban list, bulk/block deals, announcements). Functional test 21/21 on the server, against a scratch database. APIs: `/api/intraday-lab/v2/ledger`, `/v2/ledger/rows`. |
| 2 | **Built, run** (4 Nov 2026) | `--live-rules` backtest option (`intraday_v2_portfolio.accept_live`, matches the hand-written joint replay exactly). Research harness `backend/research/intraday_ai` (build from a git commit, read-only exports, runner, features, fidelity, pre-registration). Fidelity on 6 Oct – 3 Nov: 55.8% of live trades reproduced (target 60%), 94.8% same exit (target 95%) — **not met**; the causes are listed in `RESULTS.md`. Two-year dataset: 495 sessions, 147,427 signal rows for the six rules. |
| 3 | **Built, tested** (4 Nov 2026) | Pre-registered tests (`fd2cc2a`): **limit entries NO-GO for all six rules** (fill 93–94%, +1.3 bp a signal, still −4.8 to −8.6 bp net on the holdout); **book-based cost model not adopted** (6% better than bands, 10% needed). Depth recorder `intraday_depth_recorder` (both sides' five levels with quantities at every signal of the six rules). Server test 10/10. Decision point D1 reached: only the scorer can close the gap. |
| 4 | **Built, tested** (4 Nov 2026) | `gated_books`: books A (all signals) and B (six rules), ₹10 lakh each. Event-driven from the engine, with every decision logged; risk-based size, reward/risk, open/total-risk/stock/industry caps, daily stop, drawdown pause. API `/v2/gated`; panel on the tournament tab (hidden until the backend is deployed). Server test 10/10. The comparison month starts once deployed. |
| 5 | **Tested** (4 Nov 2026) | Pre-registered (`668be3e`): **LightGBM move model not adopted** (rank IC 0.238 vs OLS 0.246 on the holdout; worse in development too) — the scanner keeps its OLS, no production change. **Big-mover filter NO-GO** (top 40 halves the loss, pooled holdout −9.3 to −5.2 bp a signal; MACD 1h +1.3 bp, t 0.28). The expected-move rank becomes a scorer feature. |
| 6 | **Tested** (4 Nov 2026) | Context features for every signal (`context.py`: sector vs NIFTY, stock vs sector, VIX regime, breadth, expiry, FII positioning, delivery, results day, expected-move rank). Pre-registered (`f4347f9`): **all five context filters NO-GO** — none moves the holdout net (−9.3 bp a signal either way). The features feed the scorer. |
| 7 | to do | |
| 8 | to do | |
| 9 | to do | |
| 10 | to do | |
