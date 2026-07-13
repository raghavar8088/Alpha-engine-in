# TradingAI — Build Roadmap & Converted Spec

> This is the "converted prompt": a generic institutional-trading-platform brief,
> rewritten as a concrete, phased build plan grounded in **this** codebase. It is the
> durable reference for future build sessions. Scope is **TradingAI only** — do not pull
> in NIFTY-PILOT-SOVEREIGN or the sibling repos under `D:\INDIAN MARKET\`.

---

## 0. Context & current state

**Goal:** turn TradingAI into a production-grade, single-user, local-first AI quant
platform for the Indian market — real Dhan data, a 50-strategy library, an institutional
backtester, AI trade intelligence, risk + portfolio analytics, paper→live execution —
built so new brokers, strategies, data providers, and AI models plug in without touching
existing code.

**Non-negotiable:** preserve everything that works today. Phases 1–2 below are already
live; treat them as **"preserve, do not regress."** Only replace working code when the
replacement is demonstrably superior, and say why.

### What is real today (verified)

- **backend/** — FastAPI gateway, no auth (auto local user `local@tradingai.dev`).
  - Routes: `GET /health`; market-data `GET /api/market-data/latest`, `/{symbol}`,
    `/{symbol}/history`; broker `GET /api/broker/status`, `POST /api/broker/connect`,
    `GET holdings|positions|funds`, `POST/GET /api/broker/orders`,
    `DELETE /api/broker/orders/{id}`. WS: `/ws/market-data`, `/ws/broker/orders`.
  - `app/services/dhan_client.py` async httpx Dhan REST client (profile, funds,
    holdings, positions, orders, quote, cancel). `app/core/encryption.py` Fernet token
    crypto. `app/core/db.py` Motor + 5 Mongo collections. `app/api/deps.py` auto-user.
  - `app/schemas/` — only `market_data.py` + `broker.py` (order models mirror Dhan's raw
    API; **no internal domain model**).
- **frontend/** — Next.js 16 App Router, React 19, framer-motion. Screens: `/dashboard`
  (live index quotes via WS), `/orders` (paper/live order form + live fills), `/portfolio`
  (Dhan holdings/positions/funds), `/settings/broker` (connect token). `lib/api.ts` +
  `useMarketDataSocket` + `useBrokerOrdersSocket`. Components: GlassPanel, StatCard,
  StatusPill, Sparkline, FlashOnChange, Sidebar.
- **market-data-service/** — NSE public **indices** poller → Mongo
  (`market_data_snapshot`/`market_data_history`) + Redis (`market_data_updates`).
  `EQUITY_SYMBOLS = []` (blocked by NSE WAF; deferred to broker APIs).
- **broker-service/** — per-user persistent Dhan order-update WSS
  (`wss://api-order-update.dhan.co`) → Redis `broker_order_updates:{user_id}`.
- **shared/** — one file: `market_data_schema.py` (field list + channel constant).
- **database/init/init-mongo.js** — creates 5 collections + indexes. Mongo runs
  **natively**, not in Docker.
- **docker-compose.yml** — Redis + MinIO + Qdrant only. **MinIO/Qdrant have no consumer
  code yet.** `docker/Dockerfile.backend` exists but is not wired into compose.

### What is 100% stub (README-only, zero code)

`strategy-service/`, `backtesting-service/`, `options-service/`, `ai-service/`,
`research-service/`, `vector-service/`, `notification-service/`, `scheduler/`.

### What is absent everywhere

Strategy interface · historical OHLCV pipeline · backtester · risk engine · position
sizing · portfolio analytics / P&L aggregation · AI client (no `anthropic`/`openai` in any
`requirements.txt`) · options chain · Monte Carlo / walk-forward · internal domain model.

---

## 1. Target architecture

### Service map

```
                         ┌─────────────┐
   NSE public  ─────────▶│ market-data │────┐
   Dhan REST/hist ──────▶│  -service   │    │  Redis pub/sub  +  MongoDB
                         └─────────────┘    │  (snapshots, history, bars)
                                            ▼
 ┌───────────┐   signals   ┌────────────┐  risk-checked orders  ┌──────────────┐
 │ strategy  │────────────▶│    risk    │──────────────────────▶│   backend    │
 │ -service  │             │  -service  │                       │ (FastAPI GW) │
 └─────┬─────┘             └────────────┘                       └──────┬───────┘
       │ backtests                                                     │ REST/WS
       ▼                                                               ▼
 ┌──────────────┐   ┌────────────┐  ┌────────────┐            ┌──────────────┐
 │ backtesting  │   │  options   │  │ ai/research│◀─Qdrant───▶│  frontend    │
 │  -service    │   │  -service  │  │ +vector    │ (RAG)      │  (Next.js)   │
 └──────────────┘   └────────────┘  └────────────┘            └──────────────┘
       ▲                                                               │
       │                                            broker-service ◀───┘ (Dhan order WS)
   notification-service · scheduler  (ops, cross-cutting)
```

### Signal flow (the spine)

`market data → Strategy.on_bar() → Signal → Risk.approve()/size() → Order → broker-service
→ fill → Portfolio.update() → AI.explain() → Notification`.

Every phase below is a segment of this spine. Build the spine end-to-end thin first, then
widen (10 strategies before 50, one asset class before all).

### Shared domain model (`shared/`)

Introduce a real internal model so services stop passing raw Dhan JSON around. Minimum:

- `Bar` (symbol, timeframe, ts, o/h/l/c/v, oi?)
- `Instrument` (symbol, exchange_segment, security_id, asset_class, lot_size, tick_size)
- `Signal` — the normalized schema below, from the mega-prompt:
  ```json
  { "symbol", "timeframe", "signal", "confidence", "stop_loss",
    "target", "source", "timestamp", "reasoning" }
  ```
- `Trade`, `Position`, `Fill`, `RiskDecision`, `BacktestResult`.

Keep it dependency-light (pydantic dataclasses) so every service can import it.

### Plugin contracts (what keeps it extensible)

Four interfaces are the whole extensibility story — new X = one new module, no edits to
existing code:

1. **`Strategy`** — `params_schema`, `warmup`, `on_bar(ctx) -> Signal | None`, plus a
   metadata block (category, timeframe, asset classes, expected win-rate, RR). Registered
   via a decorator into a `STRATEGY_REGISTRY`.
2. **`DataProvider`** — `get_history(instrument, tf, start, end)`,
   `subscribe(instruments)`. Dhan + NSE are the first two impls.
3. **`Broker`** — `place`, `cancel`, `positions`, `funds`, `order_stream`. Dhan is the
   first impl (wrap existing `dhan_client.py`).
4. **`AIProvider`** — `complete()`, `embed()`. Anthropic Claude is the default impl;
   OpenAI/Gemini/Ollama are drop-ins.

---

## 2. Phased build plan (re-derived priority)

Ordering rule: **unblock the critical path; never build a value-add layer before its
foundation.** No phase depends on a later phase.

---

### Phase 1 — Foundation: domain model + historical data + Strategy interface ✅ (built 2026-07-04)

**Why first:** you cannot backtest, run, or risk-manage anything without a domain model, a
real historical OHLCV feed, and a plugin interface. Everything else sits on this.

**Deliverables**
- `shared/domain/` — the domain model above (`Bar`, `Instrument`, `Signal`, `Trade`,
  `Position`, `Fill`, `RiskDecision`, `BacktestResult`) + the `STRATEGY_REGISTRY`.
- `shared/contracts/` — the 4 interfaces (`Strategy`, `DataProvider`, `Broker`,
  `AIProvider`).
- `market-data-service/` — add a **Dhan historical/intraday `DataProvider`** (daily +
  1/5/15/60-min) and populate the equity + derivatives **instrument universe** the NSE
  poller can't reach (fill `EQUITY_SYMBOLS`, add F&O). Persist bars to a new Mongo
  `bars` collection (compound index `instrument+timeframe+ts`).
- `strategy-service/` — skeleton package: registry loader, `Strategy` base class, one
  trivial reference strategy (EMA Cross) to prove the interface end-to-end.
- `backend/app/schemas/` — expose signal/strategy DTOs; add `GET /api/strategies` (list
  registered strategies + metadata).

**Asset classes to cover in the universe** (carried from mega-prompt — checklist):
NSE Stocks · NIFTY 50 · BANK NIFTY · FINNIFTY · MIDCPNIFTY · SENSEX (where available) ·
Equity Futures · Index Futures · Stock Options · Index Options · ETFs.

**Timeframes:** 1m · 5m · 15m · 1h · daily · weekly.

**Definition of done:** can fetch ≥5y daily + intraday history for any instrument in the
universe into Mongo; EMA-Cross strategy loads from the registry and emits `Signal`s over a
historical bar stream.

---

### Phase 2 — Institutional backtesting engine ✅ (built 2026-07-04)

**Why second (before the 50 strategies):** it is the **validation gate**. A strategy is
not trustworthy until it clears the backtester. Build the judge before the contestants.

**Deliverables** (`backtesting-service/`)
- Event-driven backtest core consuming the Phase-1 bar stream + `Strategy` interface.
- **Indian cost model:** brokerage · STT · exchange charges · GST · stamp duty · SEBI
  fees · slippage · impact cost · partial fills.
- **Analyses:** walk-forward · out-of-sample · parameter optimization · portfolio /
  multi-strategy · **Monte Carlo**.
- **Metrics (checklist):** Net Profit · Annual Return · CAGR · Win Rate · Profit Factor ·
  Sharpe · Sortino · Calmar · Expectancy · Max Drawdown · Recovery Factor · Avg Win ·
  Avg Loss · Avg Holding Time · Trade Distribution · Exposure · Capital Curve · Equity
  Curve · Monthly Returns · Yearly Returns.
- **Visualization outputs** (JSON the frontend renders): Equity Curve · Drawdown Curve ·
  Monthly Heatmap · Trade Distribution · Winning/Losing Streak · Capital Growth · Rolling
  Returns.
- `backend` route `POST /api/backtest` + `GET /api/backtest/{id}`; a `/backtesting`
  frontend screen.

**Definition of done:** run a ≥5y backtest of EMA Cross on NIFTY with full costs, get the
full metric set + equity/drawdown/heatmap JSON, and a walk-forward + Monte Carlo report.

---

### Phase 3 — Strategy library (interface-first, scaled to 50) ✅ (all 50 built 2026-07-04: 49 modules across 7 categories — ORB serves slots #19+#36; validation gate with 3-state status + real-money walk-forward tier; options/futures strategies run as documented underlying-proxies until Phase 7 wires chains, OI/2-leg strategies report awaiting-data)

**Why now:** foundation + judge exist, so strategies can be built and validated
immediately. Build ~10 reference strategies across all categories first, validate each
through Phase 2, then scale to 50.

**Each strategy module carries the full spec block:** mathematical logic · entry · exit ·
stop loss · target · trailing stop · position sizing · time filters · risk management ·
suitable market regime · suitable timeframe · expected win rate · risk-reward · parameter
grid (for optimization) · backtest-compatible.

**The 50 (checklist — each an independent module on the `Strategy` interface):**

*Trend Following:* 1 EMA Cross · 2 SMA Cross · 3 SuperTrend · 4 ADX Trend · 5 Donchian
Breakout · 6 Ichimoku · 7 MACD Trend · 8 VWAP Trend · 9 Multi-Timeframe EMA · 10 ATR Trend.

*Momentum:* 11 RSI Momentum · 12 Stochastic Momentum · 13 MACD Momentum · 14 ROC ·
15 Relative Strength · 16 Price Breakout · 17 Volume Breakout · 18 Gap Momentum ·
19 Opening Range Breakout · 20 Momentum Ignition.

*Mean Reversion:* 21 RSI Reversal · 22 Bollinger Reversion · 23 VWAP Reversion ·
24 ATR Reversion · 25 Keltner Reversion.

*Swing:* 26 Darvas Box · 27 CPR Breakout · 28 Pivot Swing · 29 Flag Pattern ·
30 Triangle Breakout · 31 Cup & Handle · 32 High Volume Breakout · 33 Delivery Breakout ·
34 Sector Rotation · 35 Earnings Momentum.

*Intraday:* 36 Opening Range · 37 VWAP Scalping · 38 Volume Spike · 39 Trend Pullback ·
40 Gap Fade.

*Futures:* 41 Calendar Spread · 42 Trend Futures · 43 Breakout Futures · 44 VWAP Futures ·
45 OI Build-Up.

*Options:* 46 Long Call · 47 Long Put · 48 Covered Call · 49 Bull Put Spread ·
50 Iron Condor. (46–50 depend on Phase 7 options analytics for Greeks/chain — stub their
signal logic here, wire pricing when Phase 7 lands.)

**Trading styles the library must span (checklist):** Intraday · Scalping · Momentum ·
Swing · Positional · Short-term · Long-term · Futures · Options Buying · Options Selling ·
Multi-Leg Options · Event-Based · Sector Rotation · Quantitative.

**Definition of done:** ≥10 strategies across ≥4 categories pass the backtest gate;
`GET /api/strategies` returns all with live metadata; a `/strategies` frontend screen lists
them with backtest stats. Remaining strategies added incrementally, each behind the gate.

---

### Phase 4 — Risk engine + portfolio analytics ✅ (built 2026-07-04)

**Why now:** before any strategy touches capital (even paper at scale), sizing and limits
must exist. Reuses Phase-2 metrics math.

**Deliverables** (`risk-service/` — new; or a `backend/app/risk` module if a separate
process is overkill)
- **Global risk engine:** daily loss limit · max drawdown · max open positions · max
  exposure · sector exposure caps · portfolio heat · kill-switch.
- **Position sizing:** fixed · ATR-based · volatility-based · Kelly criterion.
- **Portfolio analytics** (`backend` module over Dhan holdings/positions + fills):
  realized P&L · unrealized P&L · sector allocation · exposure · beta · alpha · volatility
  · capital allocation.
- `backend` routes `GET /api/portfolio/analytics`, `GET /api/risk/status`; upgrade the
  `/portfolio` screen from raw pass-through to computed analytics.

**Definition of done:** every `Signal` passes through `Risk.approve()/size()` before
becoming an order (in backtest and paper); `/portfolio` shows computed P&L + exposure +
beta/alpha; kill-switch halts new orders when a limit trips. — All met: `risk-service`'s
`RiskEngine` gates every backtest entry (5 sizing methods, exposure/sector/heat limits,
daily-loss + max-drawdown kill-switches, verified with 9 unit checks + real-data
integration tests); `POST /api/broker/orders` calls the same engine live (verified
tripping on a synthetic loss day) with `GET/PUT /api/risk/config` to tune limits and a
`/risk` screen; `/portfolio` now shows real unrealized/realized P&L, sector allocation,
beta/alpha/volatility vs NIFTY (from backfilled `bars`), and a corrected exposure
definition (positions-only vs trading capital — a live-data test caught holdings being
wrongly blended against margin funds, producing a bogus 1183% figure, fixed before
shipping).

---

### Phase 5 — Live strategy engine (mode switch) ✅ (built 2026-07-04)

**Why now:** foundation + backtest + strategies + risk exist, so wiring them to execution
is the natural next step. Reuses the existing paper-order path and broker-service.

**Deliverables** (`strategy-service/` + `backend`)
- Execution modes per strategy: **Historical · Backtest · Paper · Live · Replay ·
  Simulation.** Paper reuses the existing simulated-fill path; Live routes through
  risk-service → Dhan; Replay/Simulation feed recorded/synthetic bars.
- Runner that hosts active strategies against live Redis market data, emits risk-checked
  orders, tracks positions.
- `backend` routes to start/stop/monitor strategy runs; a `/live` (or extend `/orders`)
  frontend screen showing active strategies, their signals, and mode.

**Definition of done:** a validated strategy runs in Paper mode against live data
end-to-end (signal → risk → simulated fill → portfolio update), and the same strategy
switches to Replay on recorded bars with identical logic. — All met, with one
placement deviation from the original sketch: `StrategyRunner` lives in the **backend**
(`app/services/strategy_runner.py`), not strategy-service — it needs both
`BacktestEngine` and the Dhan client, and backtesting-service already depends on
strategy-service, so putting it there would cycle. REPLAY/SIMULATION/BACKTEST/
HISTORICAL are one-shot, calling `BacktestEngine`/`run_historical` directly — verified
**byte-identical** to `POST /api/backtest` on the same inputs. PAPER/LIVE are standing
runs: `market-data-service/live_feed.py` polls Dhan quotes into bars per the
`live_watchlist` collection, publishes finalized ones to Redis (`bars_updates`), and
`LiveEngine` (one shared subscriber, same pattern as `ws/manager.py`) dispatches each
to the `StrategyRunner`(s) watching that (symbol, timeframe). Verified end-to-end with
synthetic bars (NSE was closed — a Saturday — during this build): entry sized via
RiskEngine, intrabar stop-loss firing correctly ahead of the strategy's own lagging
exit signal (a `last_signal` vs. `last_action` distinction was added after this test
revealed the former could show a stale no-op), full cash/equity reconciliation, and
clean `live_watchlist` deregistration on stop. LIVE mode requires `confirm_live: true`
and refuses to start while the risk kill-switch is active (both verified); real order
placement itself was verified only against a **mocked** DhanClient — no real order was
placed during this build.

---

### Phase 6 — AI research & trade intelligence ✅ (built 2026-07-04; AI provider key not yet configured)

**Why now:** it is the value-add layer over a working execution spine — explanations and
idea-generation only matter once trades exist.

**Deliverables** (`ai-service/`, `research-service/`, `vector-service/`)
- **AIProvider** impl: **Anthropic Claude, default to the latest model** (per the model
  policy in §3). OpenAI/Gemini/Ollama as drop-in impls behind the same interface.
- **`vector-service/`** — wire the already-running **Qdrant** container (currently
  unused): embeddings + RAG store for news/filings/backtests.
- **Trade Intelligence Engine** (`research-service/`) — ingest **only legally-clean
  sources**: official APIs · RSS feeds · licensed data · public market data · company
  filings · exchange announcements · economic calendars · market breadth · FII/DII stats ·
  insider disclosures · bulk/block deals · corporate actions · (analyst/social APIs only
  if licensed). **Never scrape or redistribute copyrighted trade calls or premium
  research.** Normalize every incoming idea into the `Signal` schema (§1).
- **AI modules (checklist):** explain every trade · summarize news · summarize earnings ·
  rank strategies · detect unusual activity/volume/options activity · detect momentum ·
  generate trade ideas · compare strategies · explain why a trade exists · confidence
  score · risk score · reasoning.
- `backend` routes `GET /api/ai/explain/{trade_id}`, `GET /api/research/ideas`; an
  `/ai` / `/research` frontend screen.

**Definition of done:** every executed/backtested trade gets a Claude-generated
explanation + confidence + risk score; research engine produces normalized `Signal`s from
≥2 legal sources; strategy ranking endpoint works. — **Built with one honest deviation
(user's explicit call): no `ANTHROPIC_API_KEY` is configured yet.** The full Claude
integration is real and complete (`ai_service/provider.py`: `AsyncAnthropic`, model
`claude-opus-4-8`, adaptive thinking, structured outputs via JSON schema for all 7
modules — explain/summarize-news/summarize-earnings/rank/detect-unusual/ideas/compare)
and activates the instant a key is set; until then every endpoint returns
`{"status": "not_configured"}` rather than fabricated text — verified live. The research
engine ingests 3 real RSS feeds (Economic Times, Moneycontrol, LiveMint; Business
Standard 403'd and was excluded), normalizes to `Signal` with mechanical symbol
detection and a neutral HOLD placeholder (no fake directional calls) — 75 real docs
ingested, 12 symbol-matched, manually spot-checked. `vector-service` wires Qdrant with a
pluggable `Embedder` protocol: **Anthropic has no first-party embeddings API**, so today
it runs a clearly-labeled non-semantic `PlaceholderHashEmbedder` (`mode: "placeholder"`
surfaced end-to-end, incl. in the UI) proving the store/upsert/search plumbing against
real data; a real embedder (e.g. Voyage) drops in with zero other changes. Backend
routes as built: `POST /api/ai/explain-trade` (takes a Trade dict — trades live across
several collections without a unified id, so `/explain/{trade_id}` became body-based),
`GET /api/ai/rank-strategies` (auto-sources passing strategies from
`strategy_validation`), `POST /api/ai/compare-strategies`, `POST /api/ai/detect-unusual`,
`GET /api/ai/trade-ideas`, `POST /api/ai/summarize-news`, `GET /api/ai/status`,
`GET /api/research/ideas`, `POST /api/research/ingest`, and
`/api/research/vector/{status,search,index-research}` (Qdrant point IDs must be
uint/UUID — Mongo ObjectIds are mapped via deterministic UUID5). Frontend: `/ai` page
(status banner + 4 tabs: research feed, trade explainer, strategy intelligence, vector
search) with sidebar entry. All routes verified against the live backend, real Mongo,
and real Qdrant.

---

### Phase 7 — Options & futures analytics ✅ (built 2026-07-04)

**Why now:** plugs Greeks/chain into the already-working strategy + backtest interfaces;
completes strategies 41–50.

**Deliverables** (`options-service/`)
- Option chain + futures chain (via Dhan), Greeks, IV, payoff calculators, multi-leg
  builder, OI analytics/build-up.
- Back-fill pricing for the options/futures strategies (41–50) stubbed in Phase 3.
- `backend` routes `GET /api/options/chain/{symbol}`, `POST /api/options/payoff`; an
  `/options` frontend screen (chain + payoff diagram).

**Definition of done:** live option chain with Greeks renders; a multi-leg payoff (e.g.
Iron Condor) computes; strategies 46–50 run in backtest with real option pricing. — All
met: `greeks.py`'s Black-Scholes engine verified exactly against put-call parity and an
IV round-trip; the live NIFTY chain (234 strikes) parses correctly with PCR/max-pain/
OI-buildup, gap-filling illiquid Dhan-reported Greeks with our own BS calc (tagged
`source: computed` vs `broker` — never silently overriding a real quote). "Real option
pricing" for the backtester means **Black-Scholes-modeled from the underlying's realized
volatility**, not historical-quoted premiums — Dhan has no continuous multi-year option
chain to backtest against (each contract trades one expiry cycle only), so this is the
standard institutional fallback, stated plainly rather than disguised as historical data.
A P&L sign bug was caught mid-build (closing a structure reverses every leg's cash flow;
P&L is `entry_net_premium − exit_value`, not the reverse) — all 5 strategies' results
flipped from economically implausible to sane after the fix (e.g. bull_put_spread's win
rate went from 17% to 83%, correct for a net-credit structure), and equity now
reconciles exactly with summed trade P&L for all 5.

---

### Phase 8 — Ops layer: notifications, scheduler, infra

**Why last:** cross-cutting support that hardens an already-working platform.

**Deliverables**
- **`notification-service/`** — Telegram/email alerts on fills, signals, risk breaches,
  kill-switch trips.
- **`scheduler/`** — shared job scheduling (universe refresh, EOD backtests, data
  backfills, report generation).
- **Infra:** wire `docker/Dockerfile.backend` into compose; containerize the Python
  services; connect **MinIO** (currently unused) for artifact/report storage.

**Definition of done:** a fill triggers a Telegram alert; a scheduled nightly job
refreshes the universe and re-runs the backtest gate; `docker compose up` brings up the
full stack (Mongo stays native per README).

---

## 3. Cross-cutting standards

- **Preserve Phases 1–2.** Dashboard, broker connect, portfolio, paper/live orders, both
  WebSockets, the 5 Mongo collections, and the no-auth local-user model are **working —
  do not regress.** Replace only with a demonstrably superior implementation, and justify
  it.
- **Extensibility first.** New broker/strategy/data-provider/AI-model = one new module
  implementing a §1 contract, registered via decorator/registry. No edits to existing
  modules to add one.
- **Architecture:** repository pattern · dependency injection · clean architecture /
  DDD-lite · the domain model in `shared/` is the lingua franca between services.
- **Tech stack (fixed):** FastAPI + Python 3.12 · Next.js/React/TypeScript · MongoDB
  Community (native) + Redis · Qdrant (RAG) · MinIO (artifacts) · Dhan broker · Claude /
  OpenAI / Gemini / Ollama behind `AIProvider`.
- **Anthropic model policy:** default to the **latest, most capable Claude model**
  (currently the Claude 5 family / Opus 4.8 tier). Never hardcode an old model id; read it
  from config with a current default. Consult the `claude-api` skill before writing any
  Anthropic integration code.
- **Engineering baseline:** structured logging · unit + integration tests per service ·
  explicit error handling with retries/backoff on all network calls (Dhan, NSE, AI) ·
  secrets in `.env` / Fernet-encrypted (reuse `core/encryption.py`) · config via
  pydantic-settings (reuse `core/config.py`).
- **Data & reconnects:** cache intelligently (Redis) · reconnect + failover on every
  streaming feed (reuse broker-service's reconnect loop pattern).
- **Legal:** market-data ingestion uses official/licensed/public sources only — no
  scraping of copyrighted trade calls or premium research.
- **Method per subsystem:** before building each phase, (1) analyze the existing code,
  (2) name the deficiencies, (3) explain the proposed improvement, (4) implement with
  maintainability + performance as primary goals.

---

## 4. The converted prompt (paste into a future build session)

> **You are the Lead Quant Architect / Principal AI Engineer for TradingAI**, a
> local-first, single-user AI quant platform for the Indian market (FastAPI + Next.js +
> MongoDB + Redis + Dhan, no auth). Phases 1–2 are live and must be preserved: live
> market-data dashboard, Dhan broker connect, portfolio view, paper+live orders, and two
> WebSockets. Your job is to build the platform to institutional quality **following the
> phase order in `ROADMAP.md` §2** — Foundation (domain model + Dhan historical data +
> `Strategy` interface) → Backtesting engine → 50-strategy library → Risk + portfolio
> analytics → Live strategy engine → AI research/trade-intelligence → Options analytics →
> Ops. 
>
> Build the signal spine (`data → strategy → risk → broker → fill → AI explain →
> notify`) thin end-to-end first, then widen (10 strategies before 50, one asset class
> before all). Every new broker/strategy/data-provider/AI-model must be a single new
> module implementing one of the four `shared/contracts` interfaces — no edits to existing
> code to add one. Cover the full asset-class, trading-style, strategy, backtest-metric,
> and AI-module checklists in §2. Default every LLM call to the latest Claude model via the
> `AIProvider` interface. Ingest only legally-clean market data. Enterprise standards:
> logging, tests, error handling, reconnect/failover, DI + repository pattern. Before each
> subsystem: analyze the existing code, state its deficiencies, explain your improvement,
> then implement. **Do not regress Phases 1–2.**

---

*Every requirement from the original institutional brief — all asset classes, trading
styles, the 50 named strategies, every backtest metric & visualization, all AI modules,
risk items, portfolio items, the 13 services, and the tech stack — is carried into the
phase checklists above. Nothing was dropped; items were re-ordered by dependency and
mapped onto real TradingAI folders.*
