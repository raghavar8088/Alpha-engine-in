# Trending Stocks — Build Plan

A new module in TradingAI, placed in the sidebar **directly below Momentum Trading**.

**What it is:** you name the stocks. The desk trades **only** those names, **long only**, and
it does not take a trade just because a pattern printed — every entry must survive a
multi-pillar evidence gate (volume, momentum, news, price action, chart pattern, market
regime, liquidity) and every open position carries, on the row, the **written reason it was
taken**.

Status: **BUILT** (2026-08-21). Everything below the build report is the plan as approved;
the report says what actually shipped, where it differs, and what the gate measured.
Numbers marked `verified` were read out of this repo during the audit.

---

## BUILD REPORT

### What shipped

| Piece | Where | Result |
|---|---|---|
| Long-only library | `backend/app/services/trending_stocks/catalog.py` | **678 strategies** = 86 recipes × 8 timeframes − 10 session-anchored on 1d. Asserted at import. |
| 19 new long-only recipes | `recipes.py` | 13 need no new detection code — they attach hypotheses to five factory detectors no factory recipe used. |
| 6 new detectors | `detectors_ext.py` | Anchored VWAP, long-horizon high, Ichimoku kumo, VCP, RS-vs-NIFTY, RSI failure swing. |
| 1:6 gate | `feasibility.py` | Five distinct verdicts, each with its own fixture in the test suite. |
| Evidence engine | `evidence.py` | 7 pillars, each returning a score, a verdict and one English sentence. |
| One decision function | `signals.py` | `evaluate_long()` is a drop-in for the factory's `evaluate()`, so backtest and paper desk share it. |
| Walk-forward + Monte Carlo | `validation.py` | Neither existed anywhere in the backend before. |
| Paper desk | `engine.py` | ₹10L per strategy → ₹678 crore book, real NSE costs by holding style, breakers before sizing. |
| Daemon | `scheduler.py` | Session loop, nightly sweep, and the RSS ingest **nothing had ever scheduled**. |
| API | `app/api/routes/trending_stocks.py` | 21 endpoints. |
| UI | `frontend/app/trending-stocks/page.tsx` | 7 tabs, sidebar link directly under Momentum Trading. |
| Tests | `backend/tests/trending_stocks/verify_*.py` | 4 suites, 70 assertions, all passing. |

### Where the build differs from the plan

1. **One file under `strategy_factory/` WAS edited**, contrary to §1 of the plan. `backtest.py`
   gained one optional parameter, `evaluate_fn`, defaulting to its own `evaluate` — so factory
   behaviour is byte-identical. The alternative was forking 120 lines of no-look-ahead replay
   into this module, which would have produced two replays that drift apart. One additive
   parameter beats a second copy of the thing every desk's numbers come out of.
2. **`stop_not_structural` became two verdicts.** The plan had one anti-gaming rule. Measurement
   showed it was firing for two *opposite* reasons, so it is now `stop_too_tight` (the pattern's
   invalidation was inside the volatility floor — the gaming case) and `stop_too_wide` (the
   invalidation is beyond the ATR cap, so the position would be stopped out while the idea was
   still alive). At 1:6 the split is 9 vs 199 — one bucket hid that almost completely.

### Three bugs the tests caught, all of which would have failed silently

* **`overhead_levels` counted the current bar's own high as resistance.** On any breakout the
  newest bar's high sits a hair above entry, so *every genuine new high was blocked by itself* —
  the exact opposite of what a "no overhead supply" test is for. Fixing it took accepted setups
  from 0.5% to 2.6% of those reaching the gate.
* **`CP.pivots` returns plateau pivots.** A flat-topped turn produces three consecutive "swing
  highs" at the same price, so the contraction detector was pairing one peak with three different
  troughs and measuring nonsense. Adjacent pivots are now collapsed.
* **The RSI failure swing searched for the wrong peak.** Taking the maximum RSI after the trough
  finds the *current* bar, so the "intervening peak" it had to clear was itself. It now walks
  back from the current bar to find the pullback low, then takes the peak before that.

### What the 1:6 gate actually measured

76 daily strategies replayed over 1,500 synthetic trending bars; 2,074 setups passed the
detector and confirmations and reached the feasibility gate:

| Verdict | Share | Meaning |
|---|---:|---|
| `rr_infeasible` | 57.2% | 6R is beyond the instrument's own excursion over the holding period |
| `overhead_supply` | 29.4% | a known level sits in the first half of the journey |
| `stop_too_wide` | 9.6% | the pattern's invalidation is beyond the 6-ATR cap |
| **`ok`** | **2.6%** | **accepted** |
| `degenerate_levels` | 0.8% | inverted or non-positive geometry |
| `stop_too_tight` | 0.4% | the gaming case |

Re-run at 1:3, acceptances roughly triple. **The gate is doing exactly what §8 of the brief asked
for and it is severe**: on daily bars a 6R target off a typical 1.5-ATR structural stop is an 18%
advance inside 40 sessions. `TS_MIN_RR` is configurable so the same 678 strategies can be re-run
at 1:3 to price what the constraint costs — that is what it is for, not for quietly relaxing the
rule when the answer is unwelcome.

Fast timeframes fail differently and are reported separately as `edge_below_costs`: a 6R target
on a 1-minute chart is often 0.3–0.9%, which clears the R:R test and still loses to ~0.22%
round-trip friction.

### Not yet run against live data

The sweep numbers above are from synthetic series, because the basket is empty until you name
stocks and the bar backfill has not run. Nothing here has touched Angel or Mongo yet.

---

## 0. Audit — what already exists (so we build the 20% that doesn't)

Read on 2026-08-21 from `d:/INDIAN MARKET`.

### 0.1 The Strategy Factory already answers most of the brief

`backend/app/services/strategy_factory/` (commit `fee6ebf`, 5,459 lines) — **verified**:

| Brief section | Already implemented | Where |
|---|---|---|
| §1 chart patterns | 13 recipes, detectors adapted from `commodity_patterns` (39 tested templates) | `detectors.py`, `catalog.py` |
| §2 candlesticks | 13 recipes incl. engulfing, hammer/star, doji, marubozu, inside/outside, soldiers, star, pin bar, Heikin Ashi | `catalog.py` |
| §3 price structure | 18 recipes — Donchian, Keltner, %B, prior-session, round number, BB/TTM squeeze, ribbon, ATR thrust, HH/HL, BOS, CHoCH, S/R flip, ORB, EMA pullback, prev-week, rectangle | `catalog.py` |
| §4 indicators | 13 recipes — EMA/golden cross, RSI (regime/extreme/divergence), MACD ×2, ADX-DI, Supertrend, PSAR, Stochastic, Williams, CCI | `catalog.py` |
| §5 multi-condition | 12 hybrid recipes | `catalog.py` |
| §6 timeframes | all 8 (1m…1d), **parameterised per timeframe** via `TF_PROFILE`, not copied | `catalog.py` |
| §12 backtesting | no-look-ahead replay: fills on the **next bar's open**, stop-before-target on ambiguous bars, real NSE costs + slippage both sides | `backtest.py` |
| §14 grading | Grade 1–5 on PF / OOS survival / drawdown / Sharpe — **never win rate alone** | `backtest.py:_grade` |
| §16 signal contract | `Signal` dataclass carries every field the brief lists | `signals.py` |
| §17 duplicate control | `fingerprint()` hashes **structure, not constants** — a duplicate hypothesis raises on import | `catalog.py` |
| §9 capital | ₹10,00,000/strategy, 1% risk sizing, no-leverage notional cap | `primitives.py` |
| §11 regime | 9 regime **tags** (not one enum), classified from price alone | `primitives.py:classify_regime` |
| §23 no-trade | `Rejection` records stage + reason for every setup that did not become a trade | `signals.py` |

Current library: **546 strategies** = 69 recipes × 8 timeframes − 6 session-only recipes on 1d.
`sf_*` collections, `/api/strategy-factory/*`, `/strategy-factory` page.

**Conclusion: we do not rebuild any of that.** Trending Stocks imports it and adds what the
brief asks for that the factory deliberately does not do.

### 0.2 What is genuinely missing

1. **Long-only.** Every factory detector is symmetric — one function emits `BUY` or `SELL`
   (`Setup.side`). There is no long-only mode anywhere in the app.
2. **A user-named basket.** The factory sweeps its own universe (`SF_EQUITY_MAX_SYMBOLS=120`,
   deepest daily histories first). Nothing lets you say "trade these eleven names".
3. **The 1:6 gate.** `primitives.py` states outright: *"There is deliberately no universal
   minimum R:R here."* The brief demands one, as a hard eligibility rule. This is a real
   conflict — resolved in §4 below, not papered over.
4. **The evidence layer.** Nothing in the app gathers volume + news + momentum + price
   action into one *reason* attached to a position. The factory's `Signal.confirmations` is
   the closest thing and it is a list of indicator predicates, not research.
5. **Walk-forward and Monte Carlo.** `backtest.py` does an in-sample/out-of-sample split
   (`oos_fraction=0.3`) — **verified**. There is no walk-forward and no Monte Carlo anywhere
   in the backend (only request flags in `routes/backtest.py` for the legacy engine).
6. **Intraday equity bars.** See §2 — this is the binding constraint on the whole module.

### 0.3 Infrastructure we reuse as-is

- **Costs**: `primitives.equity_intraday_charges` / `equity_delivery_charges` — NSE rate
  card, STT both sides on delivery. Plus `backtesting_service.costs.CostModel`.
- **Bars**: shared `bars` collection (`symbol`, `timeframe`, `ts` as a real datetime — the
  string-`ts` bug was migrated), plus `sources.resample()` which anchors 30m/45m/4h to the
  **NSE 09:15 open**, not midnight.
- **Feed**: `angel_client` (primary) → `dhan_client` → last daily close, via
  `intraday_lab_engine._equity_quote_map`, with `ltp_source` on every row.
- **News**: `research_service` RSS ingest (3 feeds, headlines only, legal-by-syndication) →
  `research_signals` collection, with mechanical symbol tagging in `normalize.detect_symbols`.
  `POST /api/research/ingest` exists; **nothing schedules it** — we will.
- **Desk history**: register one entry in `routes/desk_history.py:DESKS` and get
  since-inception stats, equity curve, daily P&L and two ROI bases for free.
- **Scheduler pattern**: `long_horizon_scheduler.py` / `commodity_scheduler.py` — an
  `asyncio` loop started from `main.py`, gated by an env flag.
- **Indicators**: `strategy_service.indicators` already has ichimoku, CPR pivots, ADX,
  Keltner, session/rolling VWAP, Aroon, StochRSI, linreg slope, Heikin Ashi. OBV, Supertrend
  and RVOL live in `strategy_factory/detectors.py`.

### 0.4 Two housekeeping facts found during the audit

- The repo is **3 commits behind `origin/main`**. Fetch and rebase before starting.
- `STOCK_SCREENER_MODULE_PLAN.md` (untracked, written today) is another session's plan for a
  **Stock Screener** under Market Data that also surfaces "momentum stocks and why they are
  trending". Overlapping subject, different module. Decide before Phase 3 whether Trending
  Stocks consumes that screener's output as an eighth evidence pillar or stays independent.
  Default in this plan: **independent**, no cross-dependency.

---

## 1. Shape of the module

```
frontend/app/trending-stocks/page.tsx          the UI
frontend/components/Sidebar.tsx                one new link, under Momentum Trading
backend/app/api/routes/trending_stocks.py      /api/trending-stocks/*
backend/app/services/trending_stocks/
    __init__.py
    basket.py        the user's stock list: CRUD, resolution to Angel/Dhan instruments
    bars.py          multi-timeframe bar pipeline for the basket only
    recipes.py       19 NEW long-only recipes
    catalog.py       LONG_CATALOG = inherited long-capable + new, fingerprinted
    detectors_ext.py 6 new detectors (AVWAP, 52w high, kumo, VCP, RS-vs-index, RSI failure swing)
    feasibility.py   the 1:6 R:R gate — structural reachability, not arithmetic
    evidence.py      the 7 research pillars -> the written reason
    signals.py       evaluate_long(): long-only wrapper over the factory's evaluate()
    validation.py    walk-forward + Monte Carlo + the extended grade
    engine.py        ₹10L paper accounts, scan / open / manage / square-off
    scheduler.py     the daemon
```

**Nothing under `strategy_factory/` is edited.** The only touch points outside the new
package are additive: one sidebar link, one router include in `main.py`, one `DESKS` entry,
new collections in `core/db.py`, and index/TTL rows in `main.py`'s existing maps.

---

## 2. The data pipeline — the binding constraint, handled first

**The problem.** The brief wants all 8 timeframes. The shared `bars` collection holds deep
**daily** history for ~500 NSE symbols (backfilled by `stocks_range.py` calling Angel with
resolution `"D"`) and **almost no intraday equity bars**. `sources.py` says so in its own
docstring: *"deep DAILY history for ~500 symbols but intraday bars for a handful."*

If we skip this, 7 of 8 timeframes silently never fire and the leaderboard is a daily-only
library wearing a multi-timeframe label.

**The fix, and why the user-named basket makes it affordable.** Angel serves
`ONE_MINUTE / FIVE_MINUTE / TEN_MINUTE / FIFTEEN_MINUTE / THIRTY_MINUTE / ONE_HOUR / ONE_DAY`
(**verified**, `ANGEL_INTERVALS`). It has **no 45m and no 4h** — those are resampled from 15m
and 1h on the 09:15 anchor by the existing `sources.resample()`. Backfilling 8 timeframes for
120 symbols is not feasible against Angel's candle rate limit (it throttles far harder than
quotes; the commodity module needed 3s pacing). Backfilling 8 timeframes for **the 10–30 names
you actually name** is roughly 6 native pulls × N symbols, chunked by date window — minutes,
not days.

`bars.py` does:

- **Backfill on add.** When a symbol enters the basket, pull 1m/5m/15m/30m/1h for the deepest
  window Angel will serve per interval (chunked; Angel caps days-per-request by interval), and
  `"D"` for 10 years. Upsert into the shared `bars` collection, same schema, `ts` as a real
  UTC datetime. Other modules benefit for free.
- **Incremental top-up.** Each scheduler tick pulls only bars newer than the stored max `ts`.
- **Honest coverage reporting.** Per symbol × timeframe: bar count, first/last ts, gaps. The
  UI shows a coverage grid. A strategy on a timeframe with insufficient history is reported as
  a **data gap**, never as "no signal" — the same rule `sources.available_timeframes()` follows.
- **Corporate-action guard.** Reuse the momentum desk's lesson: if the live quote deviates
  from the last stored close by more than `MAX_QUOTE_DEVIATION_PCT` (20%), the symbol is
  quarantined — an unadjusted split reads as "very strong momentum" and would be bought.

**Acceptance for Phase 1:** for every basket symbol, `1m,5m,15m,30m,1h,1d` each have ≥ the
`min_bars` of the deepest strategy on that timeframe, and 45m/4h resample without a stub bar
at the session open.

---

## 3. The strategy library — long only, ~678 strategies

### 3.1 How we get there

Start from the factory's 69 recipes. Two are structurally short-only and are **dropped**, not
kept as dead weight: `desc_tri` (Descending Triangle → `SELL` only) and `hanging_man` (bearish
by definition). That leaves **67 long-capable recipes** — every other detector has a `BUY`
branch (inverse H&S, double bottom, ascending triangle, falling wedge, bull flag/pennant, cup
& handle, rounding bottom, hammer, bullish engulfing, morning star, three white soldiers,
Donchian/Keltner breakout, %B low, squeeze release, HH/HL shift, BOS, S/R flip, ORB, EMA
pullback, golden cross, RSI regime/oversold/divergence, MACD, DI cross, Supertrend, PSAR,
Stochastic, Williams, CCI, and all 12 hybrids).

Then add **19 new long-only recipes** (`recipes.py`). Six need new detector code; **thirteen
need none** — the factory already ships detectors that no recipe currently uses:
`pivot_level_break`, `channel_break`, `roc_momentum`, `obv_breakout`, `rvol_thrust`, and
`fib_retracement` (used only at 0.618, in one hybrid).

| # | Recipe | Detector | New code? | Hypothesis |
|---|---|---|---|---|
| 1 | Fib shallow continuation | `fib_retracement` | no | 38.2/50% pullback in an uptrend is profit-taking, not distribution |
| 2 | Fib deep reclaim | `fib_retracement` | no | 78.6% held and reclaimed is a failed reversal — bigger objective |
| 3 | Pivot R1/R2 breakout | `pivot_level_break` | no | the floor-trader level every intraday desk shares |
| 4 | Pivot S1/S2 bounce | `pivot_level_break` | no | the same shared level as support |
| 5 | Ascending channel break | `channel_break` | no | parallel rails broken upward |
| 6 | ROC thrust | `roc_momentum` | no | rate-of-change expansion with trend agreement |
| 7 | OBV leads price | `obv_breakout` | no | accumulation visible in volume before price |
| 8 | RVOL continuation | `rvol_thrust` | no | participation confirming, filtered by higher timeframe |
| 9 | VWAP reclaim (standalone) | `vwap_reclaim` | no | who is offside intraday, without the HTF filter |
| 10 | Previous month high break | `prev_period_break` | no | a slower level than the weekly, so a larger objective |
| 11 | MTF pullback | `ema_pullback` | no | HTF trend + LTF pullback — the brief's §22 shape, explicitly |
| 12 | Stochastic bull cross in trend | `stochastic_cross` | no | the same cross used for continuation, not mean reversion |
| 13 | First-range breakout | `opening_range` | no | session range + HTF agreement |
| 14 | Anchored VWAP reclaim | `avwap_swing` | **yes** | AVWAP from the last swing low is the real average entry of this leg |
| 15 | 52-week / all-time high breakout | `high_52w` | **yes** | no overhead supply above an all-time high |
| 16 | Ichimoku kumo breakout | `ichimoku_kumo` | **yes** | cloud + Tenkan/Kijun alignment (indicator exists, detector doesn't) |
| 17 | VCP (volatility contraction) | `vcp` | **yes** | 2–3 progressively tighter contractions on falling volume |
| 18 | Relative strength leader | `rs_vs_bench` | **yes** | RS line vs NIFTY makes a new high before price does |
| 19 | RSI bullish failure swing | `rsi_failure_swing` | **yes** | RSI holds above its prior low while price does not |

**Count:** 86 recipes × 8 timeframes − 10 session-anchored recipes skipped on 1d = **678
long-only strategies**. Asserted at import, exactly as the factory does.

### 3.2 The fingerprint rule constrains us, correctly

`fingerprint()` hashes `(detector, confirmation-set, regimes, rounded target_r, timeframe,
style)` — **and deliberately not numeric parameters**. Two consequences you should know about,
because they contradict a literal reading of the brief:

- **"Fib 38.2 / 50 / 61.8 / 78.6" is not four strategies.** Under the fingerprint rule they
  are one, unless the surrounding logic differs. That is the brief's own §17 talking
  ("RSI 29 → RSI 30 does NOT constitute a genuinely different strategy"). So we ship *two*
  fib recipes — shallow-continuation and deep-reclaim — which differ in confirmations,
  regime and reward multiple, i.e. in hypothesis. Same treatment for pivot R1 vs R2 (one
  recipe, `level` parameter) and 15-min vs 30-min opening range.
- **Any new recipe that collides raises on import.** The library cannot silently fill with
  cosmetic variants. This is a feature and we keep it.

Trending Stocks fingerprints are namespaced (`ts:` prefix) so they are checked against each
other but never against the factory's — the two libraries are allowed to overlap, since one
is long-only on your basket and the other is two-sided on its own universe.

### 3.3 Long-only enforcement

`signals.evaluate_long()` wraps the factory's `evaluate()`:

```python
signal, rejection = evaluate(strategy, bars, symbol, ...)
if signal and signal.side != "BUY":
    return None, Rejection(sid, "short setup — this desk is long only", "direction")
```

Recorded as a rejection with its own stage, so the ledger can answer "how many setups did we
decline purely because they were shorts?" A desk that silently dropped them would look like a
desk with no signals.

---

## 4. The 1:6 gate — as eligibility, not arithmetic

The brief is explicit: *"Do NOT artificially force a 1:6 target onto a setup that cannot
realistically achieve it."* `feasibility.py` implements that literally.

For every long candidate:

1. **Stop** = the detector's structural invalidation level, clamped to
   `[MIN_STOP_ATR, MAX_STOP_ATR]` = `[0.35, 6.0]` ATR (existing `build_levels`).
2. **Anti-gaming rule (ours, new).** A trade only qualifies for 1:6 if
   `stop_basis == "structural"`. A stop that fell back to the ATR **floor** can manufacture a
   6R target out of a 0.35-ATR stop that ordinary noise will take out — the R:R would be
   fiction. Floor-stop signals are either rejected or flagged `low_confidence` (configurable).
3. **6R target** = entry + 6 × stop distance.
4. **Reachability**, three independent tests, all must pass:
   - **Volatility budget** — is 6R within `k × ATR × sqrt(max_hold_bars)` for this timeframe?
     (`DEFAULT_MAX_HOLD`: 120 bars on 1m … 40 on 1d.) A target the instrument cannot travel in
     the time the strategy allows is not a target.
   - **Overhead supply** — the nearest swing high / prior-week-month high / 52-week high /
     round number between entry and target. If a wall sits at 2.5R, the 6R target is a hope.
     The blocking level is **named in the rejection**.
   - **Pattern projection** — where the detector supplies a `measured_target`, the 6R target
     must not exceed it by more than a configured tolerance.
5. **Fail → `NO TRADE`**, with the failing test and its number recorded.
6. A strategy whose backtest produces **zero feasible 6R setups** is stamped
   **`FAILED — DOES NOT MEET 1:6 RISK/REWARD`** and barred from paper, exactly as §8 requires.

### What I expect this gate to do, stated up front

Two different things will kill strategies at the two ends of the timeframe range, and the
module must report them **separately** or you will misread the result:

- **Slow timeframes (1h/4h/1d): reachability failures.** A structural stop of ~1.5 ATR on a
  daily chart means 6R ≈ a **9 ATR** move, roughly an 18% advance, inside 40 trading days.
  Real, but uncommon. Most daily setups will be declined.
- **Fast timeframes (1m/5m): cost failures, not R:R failures.** 6R on a 1m chart is often
  only 0.3–0.9%, comfortably reachable inside 2 hours — but an NSE intraday round trip costs
  ~0.10–0.14% plus ~0.10% slippage at 5bps a side. The gate passes and the **net edge** dies.

So `feasibility` reports `rr_infeasible` and `edge_below_costs` as distinct verdicts. If, at
the end of the sweep, almost everything is rejected — that is the honest answer to "can this
basket produce 1:6 trades", and it is a result, not a bug. `TS_MIN_RR` defaults to `6.0` and
is configurable precisely so you can run the same 678 strategies at 1:2 and 1:3 and see what
the constraint actually costs you.

---

## 5. The evidence engine — "the reason behind the trade"

This is the part that does not exist anywhere in this app, and it is what makes the module
yours rather than a filtered clone of the Strategy Factory.

A strategy signal is a **candidate**, never an entry. `evidence.py` then assembles seven
pillars. Each returns a score in `[-1, +1]`, a `verdict` in `{supports, neutral, opposes,
vetoes}`, and **one plain-English sentence**.

| Pillar | Computed from | Example sentence |
|---|---|---|
| **Volume** | RVOL vs 20-bar median, up-vs-down volume ratio, OBV slope | "Traded 2.3× its 20-day median volume, with OBV at a 30-day high — participation is confirming the move." |
| **Momentum** | 1d/5d/20d/60d returns, RSI(14) regime, ADX, distance from 52-week high, **relative strength vs NIFTY** | "Up 8.4% in 5 sessions and 21% in 3 months, outperforming NIFTY by 14 points; RSI 63 (trend regime), ADX 28." |
| **News** | `research_signals` matched by `detect_symbols`, last 72h, scored by recency + count, sentiment via `ai-service` when a key is configured | "Two headlines in the last 24h (Economic Times, Moneycontrol) — both order-win related." **or** "No headlines found in the last 72h for this symbol." |
| **Price action** | Swing structure (HH/HL sequence intact?), close vs EMA20/50/200 and VWAP, pullback depth, signal-bar wick ratio, gap behaviour | "Higher highs and higher lows intact for 6 swings; closed above its 20- and 50-EMA in the top 18% of the bar's range." |
| **Chart pattern** | The firing detector, its `detail`, plus a quality score (how cleanly the geometry fit) | "Bull flag: 7-bar orderly drift after a 4.2% pole, broken on the close." |
| **Regime** | `classify_regime` on the **symbol**, and separately on **NIFTY** | "Stock in strong_bull (ADX 28); index above its 200-DMA with index vol in the normal band." |
| **Liquidity** | 20-day median turnover, quote freshness, quote-vs-close deviation, tick sanity | "₹142 crore median daily turnover; live quote 0.4% from the last close." |

**The gate.** Entry requires:
- **no veto** (a veto is: index regime hostile, stale/deviant quote, turnover below floor,
  news sentiment strongly negative in the last 24h), **and**
- **at least `TS_MIN_PILLARS` (default 5 of 7) pillars at `supports`**, **and**
- the 1:6 feasibility test passed.

**The reason is stored on the position** as an ordered list of those sentences plus the pillar
scores, and is what the UI renders on the row and in the position detail. It is written at
entry time from the data available at entry time — never regenerated later, so it cannot drift
into a post-hoc justification.

### Honest limits of the news pillar — read this before trusting it

- `research_service` ingests **three RSS feeds** (ET Markets, Moneycontrol Business, LiveMint
  Markets), **headlines and summaries only**. That is broad market news, not per-stock
  coverage. Many of your names will legitimately have **no news**, and the pillar will say so
  rather than invent a story.
- Symbol tagging is a **regex over the known symbol list** (`normalize.detect_symbols`) — it
  matches "RELIANCE" but not "Reliance Industries said…". Improving this to a company-name
  alias table is Phase 3 work, and I will report the match rate rather than assume it works.
- Nothing currently schedules the ingest. We add a 30-minute loop.
- Sentiment needs `ai-service`; per your memory there is **no `ANTHROPIC_API_KEY` configured**,
  so unless a Groq/Mistral/DeepSeek key is present the pillar runs in count+recency mode and
  reports `sentiment: not-configured`. It never fabricates a sentiment score.
- **Therefore:** news is a **veto-capable but not required** pillar. "No news" is neutral, not
  negative. A design that required positive news would simply never trade.

---

## 6. Capital, risk and regime

- **₹10,00,000 per strategy**, independent virtual account. 678 strategies ⇒ a **₹678 crore**
  notional paper desk. That is what "₹10L per strategy × 500+" means; stated so it is not a
  surprise on the summary tile. `TS_PER_STRATEGY_CAPITAL` is configurable.
- **Per-trade risk** 1% of the strategy's own capital (₹10,000), sized by stop distance via
  the existing `position_size()` — risk-capped **and** cash-capped, no leverage.
- **Concurrency cap**: `TS_MAX_STRATEGIES_PER_SYMBOL` (default 8). Straight from this app's
  own history — the buying desk lost 29% in a day because six near-identical strategies bought
  the same instrument at once. With a *small basket*, this cap matters more here than anywhere
  else in the app: 678 strategies pointed at 15 names will pile up by construction.
- **Breakers**: max daily loss (3% of desk), max weekly loss, max drawdown, max consecutive
  losses per strategy, max simultaneous positions per strategy (default 1) — all configurable,
  all enforced before sizing, never after.
- **Regime gate**: new entries withheld while NIFTY is below its 200-DMA or index volatility is
  above the configured band (the Daniel–Moskowitz momentum-crash finding the Momentum desk
  already encodes). **Open positions keep being managed** either way — a desk that stops
  managing its book leaves real risk untracked.
- **Style split**: `TF_PROFILE.style` decides it. `scalp`/`intraday` strategies square off at
  15:15 and are charged **intraday** rates; `swing`/`positional` carry and are charged
  **delivery** rates (STT both sides, ~4× the drag). Same rule the backtest uses.

---

## 7. Validation — backtest → OOS → walk-forward → Monte Carlo → paper

Reuses `strategy_factory.backtest.backtest()` unchanged (next-bar fills, stop-before-target,
costs both sides), then adds `validation.py`:

- **Walk-forward** (new): anchored rolling windows — train *k*, test 1, roll. Report the
  **fraction of test windows profitable** and the in-sample-to-out-of-sample efficiency ratio.
  A strategy profitable in one long backtest and in 2 of 9 forward windows is unstable, and the
  grade must say so.
- **Monte Carlo** (new): bootstrap the trade sequence 1,000× → distribution of max drawdown,
  final equity, and **probability of ruin** at the configured breaker. Report the 5th
  percentile outcome, not the mean.
- **Extended grade** (wraps `_grade`, does not replace it):

| Grade | Requires |
|---|---|
| 5 | existing G5 (PF ≥1.6, DD ≤15%, deep sample, Sharpe ≥1.0) **+** ≥70% of walk-forward windows profitable **+** MC 5th-percentile equity above starting capital **+** ≥1 feasible 6R trade |
| 4 | existing G4 + ≥55% WF windows profitable |
| 3 | existing G3 + OOS positive |
| 2 | in-sample only, or edge thinner than costs |
| 1 | rejected — negative net, PF ≤1, too few trades |
| **F** | **`FAILED — DOES NOT MEET 1:6 RISK/REWARD`** — never produced a feasible 6R setup |

**Only Grade ≥3 trades paper** (`TS_MIN_GRADE`, mirroring `SF_MIN_GRADE`). Ungraded strategies
are held back — paper trading is earned by evidence, not granted by existing.

---

## 8. The paper desk

`engine.py`, modelled on `strategy_factory/engine.py` and `momentum_engine.py`:

- **Scan**: for each basket symbol × each eligible strategy on each timeframe with sufficient
  bars → `evaluate_long()` → feasibility → evidence → open or record a rejection.
- **Open**: `entry` at the live quote with slippage applied adversely, quantity from
  `position_size`, cash deducted from that strategy's own account, evidence stored on the row.
- **Manage**: stop / 6R target / max-hold / EOD square-off for intraday styles. Net P&L
  charged real costs on both fills. Optional ATR trailing stop after +2R (configurable, off by
  default — it changes the realised R distribution and must not silently differ from the
  backtest).
- **Equity snapshot** every tick, into `ts_equity` (the app-wide convention; `DeskHistory`
  reads it).
- **Ships armed** — it is paper, and accruing the track record is the point. Real money is a
  different desk.

`scheduler.py`: tick every `TS_TICK_SECONDS` (default 180) during 09:15–15:30 IST on weekdays;
bar top-up first, then scan, then manage. Plus a 16:00 IST nightly job: full bar refresh →
backtest sweep → walk-forward → Monte Carlo → re-grade. Plus a 30-minute RSS ingest loop.

---

## 9. API

```
GET    /api/trending-stocks/summary                 desk totals, grade histogram, gate config, breakers
GET    /api/trending-stocks/basket                  the user's stocks + coverage + live quote
POST   /api/trending-stocks/basket                  add {symbol} -> resolve instrument, queue backfill
DELETE /api/trending-stocks/basket/{symbol}         remove (open positions are managed to close, not orphaned)
GET    /api/trending-stocks/basket/{symbol}/coverage bars per timeframe, first/last ts, gaps
GET    /api/trending-stocks/research/{symbol}       the 7 evidence pillars, live, with sentences
GET    /api/trending-stocks/library                 678 strategies, filterable, graded (the leaderboard)
GET    /api/trending-stocks/strategy/{id}           rules, backtest, WF windows, MC distribution, equity curve
GET    /api/trending-stocks/signals                 signal feed = the alert stream (§21 format)
GET    /api/trending-stocks/rejections              why NO TRADE, grouped by stage
GET    /api/trending-stocks/positions               open + closed, each with its reason
GET    /api/trending-stocks/trades                  closed blotter, net of costs
GET    /api/trending-stocks/equity                  desk equity curve
POST   /api/trending-stocks/backtest                run the sweep (background)
POST   /api/trending-stocks/validate                run walk-forward + Monte Carlo (background)
POST   /api/trending-stocks/run                     one scan+manage cycle, on demand
```

All behind `get_current_user`, matching every other route.

---

## 10. UI — `/trending-stocks`

Sidebar link inserted **between Momentum Trading and NIFTY 50 Option Scalping**, with a
distinct icon (a flame-over-candles mark, not a fourth trend arrow — the sidebar already has
three).

Tabs:

1. **Basket** — add/remove stocks (autocomplete via the existing instrument search), live LTP,
   a **coverage grid** (symbol × 8 timeframes, green/amber/red with bar counts), and a
   per-symbol **Research card** showing all 7 pillars with their sentences and scores.
2. **Signals** — the live feed in the brief's §21 alert format: strategy, symbol, timeframe,
   LONG, entry, stop, 6R target, risk ₹, reward ₹, R:R, grade, confidence, regime, pattern,
   volume verdict — plus the **reason sentences** inline.
3. **Positions** — open and closed. Every row expands to the **full reason it was taken**, the
   evidence scores at entry, and the live distance to stop and to target in R.
4. **No-Trade** — the rejection ledger, grouped by stage (direction / regime / detector /
   confirmation / evidence pillar / 1:6 infeasible / costs / risk limit). This is the tab that
   proves the desk is being selective rather than broken.
5. **Library** — all 678 strategies. Columns exactly as §19: ID, Strategy, Family, Timeframe,
   Trades, Win %, PF, CAGR, Max DD, Avg R, R:R, Grade, Status. Filters: family, sub-family,
   timeframe, grade, regime, paper status, and a `FAILED 1:6` filter.
6. **Strategy detail** — overview, rules (setup/entry/confirmation/stop/target/exit), equity
   curve, drawdown curve, walk-forward window table, Monte Carlo drawdown distribution, trade
   distribution, and current state.
7. **History** — the shared `DeskHistory` component, once `trending-stocks` is registered.

---

## 11. Storage

New collections in `core/db.py`: `ts_basket`, `ts_backtests`, `ts_validation`, `ts_scores`,
`ts_positions`, `ts_trades`, `ts_signals`, `ts_rejections`, `ts_evidence`, `ts_equity`,
`ts_state`. Bars go into the **existing shared `bars` collection** — no private bar store.

Indexes registered in `main.py`'s existing map: `(strategy_id, symbol, timeframe)` on
backtests; `(status, opened_at)` on positions; `(symbol, created_at)` on signals and evidence;
`(stage, created_at)` on rejections. TTL: `ts_equity` 14 days, `ts_rejections` 7 days (it is
high-volume by design — 678 strategies × 15 symbols × every tick).

Desk registration: one entry in `routes/desk_history.py:DESKS`.

---

## 12. Phases, with acceptance criteria

| Phase | Deliverable | Done when |
|---|---|---|
| **0** | Basket CRUD + instrument resolution + sidebar link + empty page | You can add stocks; nothing trades; existing modules provably untouched (`/api/strategy-factory/summary`, `/api/momentum-trading/summary` unchanged) |
| **1** | `bars.py` — 8-timeframe pipeline for basket symbols | Coverage grid green for 1m/5m/15m/30m/1h/1d on every basket name; 45m/4h resample with no session-open stub; quarantine fires on a deviant quote |
| **2** | `recipes.py` + `catalog.py` + `detectors_ext.py` + `feasibility.py` | `len(LONG_CATALOG) == 678` asserted; zero fingerprint collisions; every strategy emits `BUY` only; unit tests for the 6 new detectors on purpose-built series (matching `commodity_patterns`' 50-assertion standard); 1:6 gate rejects a stop-basis=`atr_floor` 6R and names the blocking level on an overhead-supply reject |
| **3** | `evidence.py` + RSS scheduling + symbol-alias table | All 7 pillars return a score **and a sentence** for every basket symbol; news match rate reported honestly; a veto demonstrably blocks a signal |
| **4** | `validation.py` + sweep | Full backtest of 678 × basket completes; per-strategy WF windows and MC distributions stored; grade histogram published; the count of `FAILED — 1:6` reported explicitly |
| **5** | `engine.py` + `scheduler.py` | Paper positions open only from Grade ≥3 strategies, every one carrying its reason; breakers verified by forcing one; EOD square-off verified on an intraday-style strategy |
| **6** | API + full UI + desk history | All 7 tabs live; No-Trade tab populated; DeskHistory renders |
| **7** | **The honest report** | A written summary: how many of 678 survived, on which timeframes, and — the real question — **whether a 1:6 long-only desk on your basket produced a positive expectancy after costs** |

---

## 13. What will probably go wrong — said now, not later

1. **The 1:6 gate will reject most setups.** Expected, and it is the point. Phase 7 reports
   the rejection breakdown by cause so you can decide whether to relax `TS_MIN_RR` to 3 or 4.
2. **Fast timeframes will pass 1:6 and still lose after costs.** ~0.20–0.24% round-trip
   friction against a 0.3–0.9% target is a coin flip you pay to take. Every desk in this app
   that charged honest costs found this; the intraday fee cutover turned 1,415 "winners" into
   losers. Expect 1m and 5m to be near-empty on the leaderboard.
3. **The news pillar will be thin.** Three market-wide RSS feeds will not cover a mid-cap.
   It is built to say "no news found" rather than to guess.
4. **678 strategies on ~15 symbols will crowd.** The per-symbol cap is the defence; if the cap
   binds constantly, the honest read is that the library is over-parameterised for a basket
   this small, and the fix is a smaller qualified set, not a bigger cap.
5. **Angel's candle endpoint will rate-limit the backfill.** Pacing and chunking are in the
   Phase 1 design; a 30-name basket is still minutes of backfill, not seconds.
6. **A 1:6 long-only desk may simply not have an edge on your names.** If that is the answer,
   the module will say so with numbers instead of finding a way to look profitable.

---

## 14. What I need from you

1. **The stock list.** The module works without it (you type them into the Basket tab), but if
   you give me the names now I will size the Phase 1 backfill and run the first sweep on the
   real basket rather than a placeholder.
2. **Three defaults to confirm** (each has a sensible default, so silence is fine):
   - `TS_MIN_RR` = **6.0** — keep as a hard gate, or also run a 1:3 shadow book for comparison?
   - Trading style — **both** intraday and swing strategies, or swing/positional only?
   - `TS_MIN_PILLARS` = **5 of 7** for entry.
3. Nothing else blocks. Say go and I start at Phase 0.
