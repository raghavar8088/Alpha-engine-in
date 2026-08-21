# Stock Screener — Build Plan

A new module under **Live Market Data** in TradingAI. Four things in one dashboard:

1. **Momentum stocks** for that day / week / month / 6 months, each with *why* it is trending
2. **Sector rotation** over the same four horizons, drillable into the stocks inside a sector, with the driver behind the move
3. **Chart patterns** on daily and weekly candles — swing lows, W (double bottom), triangles, flags, cup & handle and the rest
4. **Trade setups** derived from the above, split into **Intraday**, **Swing** and **Breakout**, each priced net of real Angel One costs

Status: plan only. Nothing below is built yet.

---

## 1. Answering the Chartink question first

**Verified by direct probe on 2026-08-21, not from documentation.**

### What works

`POST https://chartink.com/screener/process` works with **no login**:

```
GET  https://chartink.com/screener/          -> session cookies + <meta name="csrf-token">
POST https://chartink.com/screener/process   -> header x-csrf-token, form field scan_clause
```

Live response shape:

```json
{"draw":1,"recordsTotal":115,"recordsFiltered":115,
 "data":[{"sr":1,"nsecode":"BOSCHLTD","name":"Bosch Limited","bsecode":"500530",
          "close":48200,"per_chg":-1.13,"volume":30216}]}
```

So **any scan clause we write can be pulled programmatically.**

### Dashboard 11543 specifically

It is **public** — `is_private: false`, `authorizations.view: true`, no login needed. Its real name is
**"Market Matrix"** and it holds **20 widgets**. `GET https://chartink.com/dashboard/11543/widgets`
returns every widget's name and its underlying `query` string.

The 20 widgets:

| Widget | What it measures |
|---|---|
| Market Matrix | composite board |
| Gold ETFs vs Nifty — 1 month chg % | ETF vs index |
| Monthly Sector Advances % | sector breadth |
| Nifty current vs previous year | index YoY |
| 1 yr avg sector change | sector 1Y |
| Intraday Nifty 50 Candles | green vs red count |
| RSI distribution | oversold / overbought counts |
| New high vs low count | 52-week highs vs lows |
| Stock opportunities | 5-min volume spurt + % chg + LTP |
| % abv 20 / 50 / 200 SMA | breadth, three widgets |
| Current vs previous yr volumes (cr) | turnover YoY |
| % at 52-wk low / high | two widgets |
| Stocks above/below VWAP | intraday breadth |
| Index stats | LTP + % chg |
| Top gainers % / Top losers % | two widgets |
| Intraday stocks % abv Pivot | intraday breadth |
| Futures Advancing vs Declining | F&O breadth |

### What does *not* work

The widget query language (`select groupavg(...) ... where ...`) is **not** accepted by
`/screener/process`. Posting the "Top gainers %" widget query verbatim returns:

```json
{"data":[],"scan_error":"There was a error in running your scan"}
```

Their JS bundle (`build/assets/atlas-*.js`) exposes only `/screener/process` and
`/backtest/process` as execution routes — there is no public execute-widget endpoint.
So we can read **what that dashboard measures**, but not **its rendered numbers**.

### Verdict

**Use Chartink as a secondary idea feed, never as the price of record.** Reasons:

- free tier data is delayed (~30–45 min intraday by published accounts) — unusable for intraday entries
- the endpoint is undocumented and can change or throttle without notice
- scraping it is ToS-grey; the app already pays for a licensed Angel One feed

**And we largely don't need it.** 17 of those 20 widgets are breadth metrics we can compute
*exactly* and *live* from data already in the database — `bars_collection` holds daily bars for
the whole Nifty 500 and `stock_universe_collection` holds each stock's sector. We reimplement the
ideas on our own data.

Keep a thin, feature-flagged `chartink.py` adapter for the handful of scans genuinely cheaper to
ask Chartink than to compute (e.g. a 5-minute volume spurt across the entire market, which we do
not have intraday bars for). It must degrade to "unavailable" without breaking a page.

---

## 2. Data sources

### 2a. Already in the database — this is the spine

Nothing below needs a new vendor, a new credential, or a new API call.

| Asset | What it gives | Refreshed by |
|---|---|---|
| `stock_universe_collection` | Nifty 50/100/250/500 members **with sector** (niftyindices "Industry") | `stocks_range.refresh_stock_universe`, weekly |
| `bars_collection` | daily OHLCV, ~500-day lookback, whole universe | `stocks_range.backfill_universe_bars`, daily |
| `stock_highs_collection` | genuine all-time high per symbol | `stock_highs`, daily |
| `stock_fundamentals_collection` | revenue/PAT growth, margin, D/E, ROE, institutional holding | Yahoo, daily |
| `instruments_collection` | Angel `symboltoken`, F&O eligibility | `angel_instruments`, 12-hourly |

**Consequence worth stating plainly:** momentum, sector rotation and chart patterns are all
computable from stored daily bars. This module adds **almost zero broker load**. Only the live
LTP column needs Angel, and that is the same batched 50-token quote sweep `stocks_range` already
runs (~10 requests for the full Nifty 500).

### 2b. NSE — enrichment, not spine

Verified 200 from this machine on 2026-08-21:

- `/api/marketStatus`
- `/api/allIndices` — every sectoral index with `last`, `variation`, `percentChange` (113 KB)
- `/api/live-analysis-variations?index=gainers`
- `/api/live-analysis-volume-gainers` — today's volume vs its own 1-week / 2-week average
- `/api/index-names`

To verify in Phase 1 (not yet probed): `/api/equity-stockIndices?index=NIFTY BANK` (sectoral index
constituents), `/api/historical/indicesHistory` (sector index history for the week/month/6M
columns), and `/api/quote-equity?symbol=X&section=trade_info` (**delivery %** — a strong "why"
signal, since high delivery means investor buying rather than day-trade churn).

`nse_volume_gainers.py` already contains the correct cookie-priming pattern (prime the homepage,
then the market-data page, then call the JSON endpoint on the same client) and the correct failure
discipline. Reuse it; do not re-derive it.

> **Risk — read this before relying on NSE.** NSE blocks many datacentre IP ranges. The probes
> above succeeded from a residential Indian IP. That is **not** evidence they work from the
> Lightsail box. `nse_volume_gainers` already fails softly for exactly this reason. Verify on the
> box in Phase 1. Because our own bars carry momentum, sector and patterns unaided, an NSE outage
> costs us enrichment columns, never the module.

### 2c. Chartink — optional, flagged, degradable

As above. Behind `SCREENER_CHARTINK_ENABLED`, default off.

---

## 3. What already exists — do not rebuild it

This module is mostly **composition and presentation** over parts that are already written.

| Existing | Reuse for |
|---|---|
| `bullish_stocks.py` | the 9-signal technical screen, EMA/RSI/MACD/structure/RS math, and the entry/SL/target/trail plan. **The day-momentum reason engine is ~80% built here.** |
| `nifty_scalp_strategies.py` | `Series`, `from_rows`, `resample`, `pivots()`, `swings()`, and 63 templates including 13 geometric chart patterns |
| `commodity_patterns.py` | the same 13 chart patterns + 10 candlesticks, but returning `PatternSignal(side, entry, target, stoploss, confidence, rationale, pattern)` — **the right shape for a screener, because it explains itself** |
| `nse_volume_gainers.py` | NSE session priming, soft failure, dated capture |
| `angel_fees.round_trip` | real NSE cost model, intraday vs delivery |
| `swing_trading.py` | the drift-band idea — a breakout order must refuse a fill that gapped far past your level |
| `stocks_range.py` | universe seeding, batched Angel quotes, `QUOTE_PACE_SECONDS` |
| `SortableTables`, `PageHeader`, `GlassPanel`, `StatCard`, `StatusPill`, `Sparkline` | the whole UI kit |
| `api_cache.py` | door-level 20s GET cache — these endpoints get it for free |

Genuinely new work: multi-horizon momentum ranking, sector rotation with drill-down, a
daily/weekly pattern scan over the equity universe, and the reason engine that ties them together.

---

## 4. Backend

### 4a. Layout

```
backend/app/services/screener/
  __init__.py
  horizons.py     multi-horizon returns + calendar-aware weekly resample over bars_collection
  momentum.py     the multi-horizon stock board
  sectors.py      sector rotation, drill-down, driver decomposition
  patterns.py     daily + weekly chart-pattern scan
  reasons.py      the "why is it trending" engine
  plans.py        intraday / swing / breakout trade plans, net of Angel costs
  nse_breadth.py  NSE gainers / allIndices / delivery-% capture
  chartink.py     optional secondary adapter
  engine.py       orchestration, caching, the scheduled refresh
backend/app/api/routes/screener.py
backend/app/services/screener_scheduler.py
```

A package rather than flat files, following `services/strategy_factory/`; this module is too large
for one file.

### 4b. Endpoints — prefix `/api/screener`

```
GET  /summary                      breadth header + market status + per-source freshness
GET  /momentum                     ?horizon=1d|1w|1m|6m &index=nifty500 &sector= &limit=100
GET  /momentum/{symbol}            one stock: all 4 horizons, full reason stack, all 3 trade plans
GET  /sectors                      ?horizon=1d|1w|1m|6m
GET  /sectors/{sector}             drill-down: constituents ranked + the sector driver
GET  /patterns                     ?timeframe=1d|1w &pattern= &state=triggered|forming &index=
GET  /setups                       ?kind=intraday|swing|breakout
GET  /sources                      honest per-feed status for the Sources tab
POST /refresh                      force a recompute
GET  /chartink                     ?scan=<preset>   optional, clearly labelled as delayed
```

All plain GETs, so the existing 20 s door cache applies. Nothing here streams — **if a live SSE
breadth ticker is ever added it must go in `NEVER_CACHE`**, because that cache once hung the chart
SSE stream.

### 4c. Collections (all TTL'd on `ts`, per the `EXPIRING_COLLECTIONS` convention in `main.py`)

```
screener_momentum   90d    per-symbol daily snapshot: returns, ranks, scores, reasons
screener_sectors   365d    per-sector per-horizon snapshot (kept longer — rotation history is the point)
screener_patterns   90d    pattern hits, daily and weekly
screener_breadth   365d    one market-breadth row per day
nse_gainers        120d    NSE top gainers / losers daily capture
chartink_scans      30d    cached scan results with fetched_at + ok/error
```

Indexes: `(symbol, date)`, `(sector, horizon, date)`, `(timeframe, state, date)`.

### 4d. Scheduler

One loop in `screener_scheduler.py`, registered as a `@app.on_event("startup")` task like every
other desk, gated on `SCREENER_ENABLED`.

- **every 5 min, 09:15–15:30 IST** — breadth, intraday momentum, NSE gainers, live LTP refresh
- **16:15 IST** — EOD full recompute: all four horizons, sector rotation, daily pattern scan
  (co-timed with the existing `nse_volume_gainers` capture, which already runs at 16:15)
- **Friday after close / Saturday** — weekly bar rebuild and weekly pattern scan

### 4e. Horizon maths

Returns over 1D, 1W (5 sessions), 1M (21), 6M (126) — session counts, not calendar days, so a
holiday week does not silently shorten a window.

Each horizon carries: absolute return, percentile rank within the index, **relative strength vs
Nifty**, **relative strength vs its own sector**, and a consistency measure (share of sessions in
the window that closed up). A stock up 30% in one gap and flat for five months is not the same
animal as one up 30% in a steady climb, and the board must not rank them identically.

**Weekly bars**: resample daily into ISO-week buckets (open = first, high = max, low = min,
close = last, volume = sum). `nifty_scalp_strategies.resample` resamples by fixed factor, which
is wrong for calendar weeks once holidays appear — `horizons.py` needs a calendar-aware version.

> **Known gap:** `BARS_LOOKBACK_DAYS = 500` gives only ~100 weekly bars. Cup & handle needs 70 and
> rounding needs 60, so weekly hits for the longer patterns will be sparse until the backfill is
> deepened to ~1200 days. That is a paced one-off job, best run in Phase 1.

---

## 5. The "why is it trending" engine

The hard part, and the part most likely to go wrong. **The rule: never write a reason we cannot
point at a number for.** Same discipline as `bullish_stocks`, which deliberately refuses to
approximate order-book strength rather than invent it.

### Tier 1 — mechanical, always available (our own bars and quotes)

- return and percentile rank on each horizon
- relative strength vs Nifty and vs its own sector
- volume: today vs 20-day average; plus NSE's own 1-week / 2-week volume ratio when reachable
- **delivery %** vs its own average (NSE `trade_info`) — separates investor buying from churn
- structure: higher highs / higher lows, days held above the 9 EMA, distance from 52-week high and ATH
- breakout: which Donchian level (20 / 50 / 252-day) was broken, and on what date
- continuity: how many of the last N sessions closed up

### Tier 2 — corroborating, may legitimately be absent

- fundamentals delta from `stock_fundamentals` (revenue, PAT, margin, ROE)
- **F&O buildup**: price up with OI up is accumulation; price up with OI down is short covering.
  That distinction is the difference between a swing trade and a fade, and we already have the
  option chain and `fno_positions.py` to compute it.
- sector context: is the whole sector moving (rotation) or is this a lone name (stock-specific)?
- index events: added to an index, from the weekly universe diff

### Tier 3 — narrative, explicitly labelled

News and filings via the existing `research-service` / `vector-service` / RSS layer and the AI
research module. **`ANTHROPIC_API_KEY` is not set in this deployment**, so build the hook and show
*"narrative unavailable — AI research not configured"* rather than fabricating one. This mirrors
how Bullish Stocks reports ungraded stocks when Yahoo is unavailable.

### What an honest empty answer looks like

> **TATAELXSI +9.1% today** — 3.2× its 20-day average volume, broke a 50-day high.
> No sector move (NIFTY IT +0.3%), no fundamental change, no F&O buildup, no news found.
> *Stock-specific and uncorroborated.*

That is a useful row. A fabricated story would not be.

---

## 6. Sector rotation

Two **independent** sector reads, shown side by side, because they disagree and the disagreement
is itself information.

1. **NSE sectoral indices** (`/api/allIndices`) — official, cap-weighted, what the market quotes.
   Day change is direct. Week/month/6M need `indicesHistory` (to verify) — fallback is to store
   `allIndices` daily and build our own history forward from today.
2. **Our own constituent roll-up** — equal-weighted *and* cap-weighted mean return per sector from
   `stock_universe.sector` + `bars_collection`, over all four horizons. Available from day one,
   for every horizon, with no NSE dependency. It also gives **breadth within the sector**, which a
   single index number hides entirely.

> **Do not equate the two.** `stock_universe.sector` is niftyindices' "Industry" label and does
> not map 1:1 onto NSE's sectoral indices. Showing both, labelled, is the honest treatment.

### Sector board columns

Sector · 1D · 1W · 1M · 6M · breadth (n up / n total) · RS vs Nifty · **rank change** (is it
climbing the table?) · turnover vs its 20-day average · leader stock · laggard stock

Plus an **RRG-style quadrant** (RS-ratio vs RS-momentum) for the rotation picture —
`RRG-Sector-Rotation-India` is already cloned in the repo as a reference implementation.

### Drill-down: what is driving the sector

Click a sector and the move gets decomposed:

- **Contribution** — each stock's return × weight, ranked. *"NIFTY IT +2.1% today; 68% of that is
  INFY +4.2% and TCS +3.1%."*
- **Breadth** — broad (>70% of names up) vs narrow (one or two names carrying it). This is the
  single most useful sector fact and it is pure arithmetic.
- **Turnover** — is sector volume above its own 20-day average?
- **Persistence** — how many of the last N sessions the sector outperformed Nifty
- **Union of constituent reasons** — the Tier 1/2 reasons of its member stocks, deduplicated

Then the full momentum table, filtered to that sector, across all four horizons.

---

## 7. Chart patterns

### Detectors — reuse, do not rewrite

`commodity_patterns.py` already implements all of them, returning entry / target / stoploss /
confidence / rationale. The detectors are pure geometry over bars and are asset-neutral in
practice.

Covered: **head & shoulders** (and inverse), **double top / bottom — the "W" pattern**, triple
top / bottom, **ascending / descending / symmetrical triangle**, rising / falling wedge, bull /
bear flag, pennant, cup & handle, rounding top / bottom, diamond, broadening formation. Plus
**swing highs and lows** via `pivots()` / `swings()`, and 10 candlestick patterns.

Phase 3 imports them directly (`from app.services.commodity_patterns import TEMPLATES`) — zero
risk. Extracting the library into a shared asset-neutral `services/patterns_lib.py` is a genuine
cleanup, but it touches the live commodity desk, so it belongs in an optional later phase.

### Two states, not one

The existing library only fires once price has **closed through the pattern's own boundary** —
correct for a trading engine, and the reason these patterns avoid being imaginary. But a screener
should also show shapes that are still **forming**, so a trader can wait for the break.

So every hit carries a state:

- **TRIGGERED** — closed through the boundary. Actionable now.
- **FORMING** — shape valid, boundary intact. Watch it.

Sort TRIGGERED first. Never blur the two.

### Scope and cost

Nifty 500 × {daily, weekly} × ~25 detectors ≈ 25,000 detector runs, each O(n) over a few hundred
stored bars. Seconds of CPU, **zero API calls**. Cache per day; rescan weekly bars after Friday's
close.

Do not write `assert len(TEMPLATES) == N` anywhere. An exact-count assert on a catalog once
crash-looped the entire backend when templates were added. Use `>=`.

---

## 8. Trading the output — Intraday, Swing, Breakout

Each mode is a horizon, a gate, and the **right cost model**. Costs are not a footnote here: the
intraday fee cutover once turned a +₹23.5k desk into −₹33.6k and reclassified 1,415 tournament
"winners" as losers. A screener that shows gross R:R would repeat that mistake, so every row shows
R:R **after** `angel_fees.round_trip`.

| | **Intraday** | **Swing** | **Breakout** |
|---|---|---|---|
| **Signal** | today's momentum + volume spurt + above VWAP/pivot + a triggered 1d pattern | 1W and 1M momentum agreeing, sector confirming, weekly pattern | Donchian 20/50/252 high + volume ≥1.5× + tight prior range |
| **Horizon** | same session | 3–15 sessions | 1–10 sessions |
| **Entry** | opening-range break or retest of the level | pullback to the 9/20 EMA, or neckline retest | on the break, inside a **drift band** |
| **Stop** | ATR-based, or the pattern's own invalidation | below the last swing low / pattern low | below the breakout base |
| **Target** | 1R then 2R, square off 15:10 | prior swing high, then trail | measured move — pattern height projected |
| **Costs** | Angel **INTRADAY** schedule | Angel **DELIVERY** (≈4× the intraday sell-side rate) | delivery unless closed same day |

**Drift band** — reuse the rule `swing_trading.py` already documents: a breakout order fills
within ~2% above the level, and *refuses* beyond it. A stock that opened at ₹130 against your ₹102
trigger is not the trade you asked for at any price, and filling it "because the level was
crossed" is the desk overruling you.

Each setup row: entry · stop · target · R:R net of costs · position size at the desk's per-trade
capital · the reason stack that produced it · the pattern that confirms it.

> **Boundary.** Phases 1–5 build a **screener**: ranked, explained, cost-honest setups. It does
> **not** auto-trade. Wiring the shortlist into a paper desk is a separate, optional Phase 7 —
> there are already many auto-trading desks in this app, and adding a fifteenth unasked would be
> scope creep.

---

## 9. UI

Route `/stock-screener`. Sidebar: **Trading** group, directly under **Market Data** — the same
placement logic that puts Bullish Stocks under Stocks Range.

### Header + breadth strip

`PageHeader` "Stock Screener" · subtitle *"NSE + Angel One · momentum, sector rotation and chart
patterns across day / week / month / 6 months"* · `StatusPill` market open/closed · Refresh button
using `refreshing()` so it bypasses the cache.

`StatCard` strip: Advances/Declines · % above 20 / 50 / 200 SMA · new 52-week highs vs lows ·
stocks above VWAP · Nifty and Bank Nifty · "as of" timestamp with source label.

*(These are the Chartink Market Matrix breadth widgets, computed on our own data and live rather
than delayed.)*

### Tab 1 — Momentum

Segmented control: **Today · This Week · This Month · 6 Months**. Filters: index (50/100/250/500),
sector, minimum turnover.

Table (`SortableTables`): Rank · Stock · Sector · LTP · **Return (selected horizon)** · 1D/1W/1M/6M
mini-columns · RS vs Nifty · RS vs sector · Vol× · Delivery% · Days above 9EMA · vs 52w H · vs ATH ·
Up-streak · **Why** · Score.

**Why** shows 2–3 compact chips — `Vol 3.2×`, `Sector +4.1%`, `Long buildup`, `52w breakout`.

### Row drawer — the screen that earns the module

Opens on row click:

- the stock's four-horizon return bar
- the **full ranked reason stack**, each line with the number behind it
- sector context — *"NIFTY IT is +6.2% this month, rank 2 of 20 — this is rotation, not a lone move"*
- chart-pattern hits on 1d and 1w, with state and levels
- the **three trade plans side by side**, each with net-of-cost R:R
- actions: add to Watchlist · open in Chart · send to the Swing Trading desk at this price

### Tab 2 — Sectors

The sector board table, the RRG quadrant, and a heat strip. Click a sector → drill-down: four-horizon
returns, breadth bar, top-3 contributors with each one's share of the move, the driver summary,
then the momentum table filtered to that sector.

### Tab 3 — Chart Patterns

Toggle **Daily | Weekly**. Filters: family (chart / candlestick / structure), specific pattern,
state (Triggered / Forming), direction.

Table: Stock · Sector · Pattern · TF · **State** · Detected on · Entry · Stop · Target · R:R (net) ·
Confidence · Rationale.

A small inline SVG sketch of the detected shape with its pivots marked is high value and moderate
effort — Phase 6.

### Tab 4 — Setups

Sub-tabs **Intraday / Swing / Breakout**. Each is the shortlist passing that mode's gate, with the
full plan and net R:R, sorted by score. This is the "what do I actually trade today" page.

### Tab 5 — Sources

Per-feed honesty: Angel One (primary, live), NSE (endpoint-by-endpoint last success and error),
Chartink (last fetch, delay warning, on/off), Yahoo fundamentals, bars coverage %.

This tab is what stops a silent data failure from being misread as *"nothing is trending today"*.
It follows the same principle as the existing honest `ltp_source` labelling.

---

## 10. Phasing

| Phase | Delivers | Notes |
|---|---|---|
| **1 — Data spine** | `horizons.py`, weekly resample, deepened bar backfill, `screener_momentum` + `screener_sectors` collections + TTLs, `/momentum` + `/sectors` | **Verify NSE reachability from the Lightsail box here**, not just locally |
| **2 — Reasons + drill-down** | `reasons.py`, sector driver decomposition, `/sectors/{sector}`, `/momentum/{symbol}` | Tier 3 narrative stubbed and labelled honestly |
| **3 — Patterns** | daily + weekly scan reusing `commodity_patterns`, FORMING vs TRIGGERED, `/patterns` | zero API calls |
| **4 — Setups** | `plans.py` with `angel_fees.round_trip`, `/setups` | drift band from `swing_trading` |
| **5 — UI** | `/stock-screener`, 5 tabs, row drawer, sidebar entry | can start against Phase 2 stubs |
| **6 — Polish (optional)** | Chartink adapter, pattern SVG sketches, extract shared `patterns_lib.py` | |
| **7 — Optional** | wire the shortlist into a paper desk | separate decision |

---

## 11. Risks, in order of how much they matter

1. **NSE may be unreachable from AWS.** It blocks datacentre ranges. Everything NSE-only (gainers,
   delivery %, `allIndices`) may simply not work in production despite working locally.
   *Mitigation:* our own bars carry momentum, sectors and patterns unaided. NSE is enrichment.
   Verify on the box in Phase 1.
2. **Chartink is undocumented, delayed and ToS-grey.** Secondary only, feature-flagged, degradable.
3. **Weekly patterns need deeper history.** 500 days ≈ 100 weekly bars; cup & handle needs 70.
   Backfill to ~1200 days, paced, one-off.
4. **API cache and streaming.** These endpoints are plain GETs and benefit from the 20 s cache.
   Any future SSE ticker must be added to `NEVER_CACHE`.
5. **No exact-count asserts** on the pattern catalog. Use `>=`.
6. **Sector labels differ** between niftyindices "Industry" and NSE sectoral indices. Show both,
   labelled; never silently equate them.
7. **No performance claim.** This is a live screen, not a backtest. If anyone later backtests the
   ranking, ranks must be computed only from bars available on that date.

---

## 12. Open questions

1. **Universe** — Nifty 500 only, or the top-1000 list `momentum_trading.py` already maintains
   (NIFTY TOTAL MARKET + MICROCAP 250)? Wider is better for breakouts and worse for data quality.
2. **Paper desk** — should Phase 7 happen, or does the screener stay a research tool?
3. **Chartink** — build the adapter at all, or drop it entirely given the delay?
4. **Weekly-bar backfill depth** — 1200 days is ~5 min of paced Angel calls per few hundred
   symbols. Acceptable as a one-off?
