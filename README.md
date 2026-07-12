# TradingAI

Local-first, single-user AI trading platform. No login — every request acts as one
auto-provisioned local user (`local@tradingai.dev`), since this runs only on your machine.
Phase 1: live NSE market data dashboard. Phase 2: Dhan broker integration
(holdings/positions/funds, paper + live order placement, live order-update WebSocket).

## Architecture

- `frontend/` — Next.js dashboard (live market data, portfolio + analytics, risk, orders,
  strategies, backtesting, broker settings)
- `backend/` — FastAPI gateway (market data REST + WebSocket, broker REST + WebSocket,
  strategy registry, backtest runner, portfolio analytics, risk status/config), no auth
  - `app/services/dhan_client.py` — async Dhan REST client (profile, funds, holdings, positions, orders, quotes)
  - `app/services/portfolio_analytics.py` — real P&L/exposure/sector/beta/alpha over the
    connected account + the live risk-status/kill-switch check (also gates `POST /api/broker/orders`)
  - `app/core/encryption.py` — Fernet encryption for stored broker access tokens
- `market-data-service/` — Python collector polling NSE public endpoints, writing to MongoDB and publishing to Redis
  - `universe.py` — loads the tradeable universe (NSE equities/ETFs, major indices, futures,
    index options) from Dhan's public scrip master into the `instruments` collection
  - `backfill.py` + `providers/dhan_history.py` — historical OHLCV backfill from Dhan
    (1m/5m/15m/1h/daily/weekly) into the `bars` collection. **Requires the Dhan Data APIs
    subscription** (Dhan returns HTTP 451 without it)
  - `live_feed.py` — real-time bar aggregator for Paper/Live strategy runs: polls Dhan
    quotes for whatever (symbol, timeframe) pairs are in the `live_watchlist` collection
    (registered/deregistered by the backend as runs start/stop), rolls ticks into bars,
    and publishes finalized ones to Redis (`bars_updates`) + the same `bars` collection.
    Run as its own process (`python live_feed.py`), like broker-service
- `strategy-service/` — the strategy library: independent strategy modules on the shared
  `Strategy` contract, registered into `STRATEGY_REGISTRY` (see its README)
- `backtesting-service/` — event-driven backtest engine with the Indian cost stack
  (brokerage/STT/exchange/GST/stamp/SEBI + slippage + partial fills), full metric set,
  walk-forward, grid optimization, and Monte Carlo. `POST /api/backtest` + the
  `/backtesting` screen, or its own CLI (see its README)
- `shared/` — `tradingai_shared` package (installed editable by the other services):
  the internal domain model (Bar/Instrument/Signal/Trade/Position/...), the four
  plugin contracts (Strategy, DataProvider, Broker, AIProvider), and a starter NSE
  sector classification (`sectors.py`)
- `risk-service/` — position sizing (capital-%/fixed-fractional/ATR/volatility/Kelly) +
  `RiskEngine` (exposure/sector/heat limits, daily-loss and max-drawdown kill-switches).
  Every backtest entry is risk-checked; the backend's `GET /api/risk/status` and
  `POST /api/broker/orders` use the same engine live (see its README)
- `backend/app/services/strategy_runner.py` + `live_engine.py` — the Phase 5 mode
  switch: HISTORICAL/BACKTEST/REPLAY/SIMULATION run one-shot through the exact same
  `BacktestEngine` the backtester uses (proving "identical logic" by literal code
  reuse); PAPER/LIVE are standing runs against `live_feed.py`'s live bars, filling
  immediately at the risk-checked size (PAPER: simulated; LIVE: a real Dhan order —
  gated behind `confirm_live: true` and a clear kill-switch check).
  `POST/GET /api/live/runs[/{id}]`, `POST /api/live/runs/{id}/stop`, and the `/live`
  screen
- `broker-service/` — standalone process maintaining a persistent Dhan order-update WebSocket per connected
  user, publishing fills/status changes to Redis for the backend to relay to that user's browser
- `database/init/` — `init-mongo.js` creates all collections (`users`, `market_data_snapshot`,
  `market_data_history`, `broker_credentials`, `paper_orders`, `bars`, `instruments`) and their
  indexes. MongoDB itself is **not** run in Docker (see below) — run this script once with `mongosh`
  (or via a one-off `pymongo`/Compass shell) against your local server before first use. The `bars`/
  `instruments` indexes are also ensured in code, so existing installs don't need to re-run it.
- `docker/` — Dockerfiles for future containerized deployment (not wired into compose yet)

- `options-service/` — Black-Scholes pricing/Greeks/IV, live Dhan option-chain
  analytics (PCR, max pain, OI build-up), multi-leg payoff (breakeven, bounded/
  unbounded max P/L, net Greeks), and a synthetic-premium backtester for options
  strategies #46-50. `GET /api/options/expiries|chain/{symbol}`,
  `POST /api/options/payoff|backtest`, and the `/options` screen (see its README)

- `ai-service/` — the `AIProvider` implementation: Anthropic Claude
  (`claude-opus-4-8`, adaptive thinking, structured JSON outputs) behind 7 modules
  (explain-trade, summarize-news/earnings, rank/compare strategies, detect-unusual,
  trade ideas). **No `ANTHROPIC_API_KEY` is configured yet** — every endpoint honestly
  returns `{"status": "not_configured"}` until one is set in the backend's env; the
  full integration activates the moment it is (see its README)
- `research-service/` — legally-clean RSS ingestion (Economic Times, Moneycontrol,
  LiveMint) normalized into the shared `Signal` schema with mechanical symbol
  detection and a neutral HOLD placeholder — no fabricated directional calls.
  `GET /api/research/ideas`, `POST /api/research/ingest` (see its README)
- `vector-service/` — wires the Qdrant container (running since Phase 1) as a RAG
  store with a pluggable `Embedder`. Anthropic has no first-party embeddings API, so
  today it runs a clearly-labeled non-semantic placeholder hash embedder
  (`mode: "placeholder"` surfaced everywhere incl. the UI);
  `/api/research/vector/{status,search,index-research}` (see its README)
- The `/ai` screen ties these together: AI/vector status banner, research feed,
  trade explainer, strategy ranking/comparison, and vector search tabs

Everything else (`notification-service/`, `scheduler/`) is a placeholder for later
phases — see each folder's README and `ROADMAP.md` for the build order.

## MongoDB setup

This project uses **MongoDB Community Server (free edition) running natively**, not a Docker container —
if it's already installed (e.g. alongside MongoDB Compass) it runs as a Windows service on
`localhost:27017` with no auth configured by default, which is what `MONGO_URL` in `.env.example` assumes.
Connect with Compass at `mongodb://localhost:27017` to browse the `tradingai` database.

If you don't have it yet, install MongoDB Community Server, then run `database/init/init-mongo.js` once
against it (`mongosh < database/init/init-mongo.js`, or paste it into a Compass shell) to create the
collections and unique indexes.

## Broker (Dhan) setup

Dhan is **live-only** — there is no sandbox API. Generate a Client ID + Access Token from
[developer.dhan.co](https://developer.dhan.co) (Live Environment → Access Token), then connect it via
`/settings/broker` in the app. The access token is encrypted (Fernet) before being stored in MongoDB.

Every order defaults to **paper trading** (simulated fill at the current Dhan quote, stored only in
`paper_orders` — no real order reaches Dhan) unless you explicitly uncheck "Paper trading" on the order
form. `backend/.env.example`'s `BROKER_ENCRYPTION_KEY` must match `broker-service/.env`'s exactly, or
`broker-service` can't decrypt stored tokens to open the live order-update feed.

## Local dev workflow

1. `docker compose up -d` — starts Redis, MinIO, Qdrant (MongoDB runs natively, see above).
2. Backend:
   ```
   cd backend
   cp .env.example .env
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```
3. Market data collector:
   ```
   cd market-data-service
   cp .env.example .env
   pip install -r requirements.txt
   python main.py
   ```
4. Broker service:
   ```
   cd broker-service
   cp .env.example .env
   pip install -r requirements.txt
   python main.py
   ```
5. Frontend:
   ```
   cd frontend
   cp .env.local.example .env.local
   npm install
   npm run dev
   ```
6. Open http://localhost:3000 — no login, you land straight on the dashboard and it updates every ~7s.
   Connect a Dhan account under Broker Settings to use Portfolio/Orders.

## Future phases

Roadmap Phases 1–7 are built (foundation, backtester, all 50 strategies + validation
gate, risk + portfolio analytics, live strategy engine, AI research/trade intelligence,
options analytics) — see `ROADMAP.md` for each phase's definition-of-done notes.
Remaining:

- **Phase 8** — ops layer: `notification-service/` (Telegram/email alerts on fills,
  signals, risk breaches), `scheduler/` (nightly universe refresh / EOD re-validation),
  and containerizing the Python services (wire `docker/` into compose, connect MinIO).
- **Unblock Phase 6's AI**: set `ANTHROPIC_API_KEY` in `backend/.env` — everything
  else is already wired.
