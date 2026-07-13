# NIFTY-PILOT-SOVEREIGN Strategy Guide: S10–S29

> **Paper-trading only.** Live order placement wired to Angel One + Dhan is implemented
> in `engine/internal/broker/` but must pass separate UAT before going live.
>
> All strategies follow the exact same `Strategy` interface as S1–S9.
> No modifications to existing strategies or core architecture.

---

## Architecture overview

```
Regime classifier → AllStrategies() roster → Strategy.Evaluate(MarketContext)
        ↓ (signal passes IsValid)
    Risk gate (Kelly half-sizing, VIX/regime multipliers)
        ↓
    Broker.PlaceOrder()  ← paper / Angel One / Dhan (injected at startup)
        ↓
    execution.Engine (slippage + Indian cost model) + Ledger
```

### Regime-awareness rules (all 20 strategies)

| Regime        | S10–S16 scalping | S17–S22 intraday | S23–S29 swing |
|---------------|:----------------:|:----------------:|:-------------:|
| TrendingBull  | ✓ (most)         | ✓ (most)         | ✓ (most)      |
| TrendingBear  | ✓ (most)         | ✓ (most)         | S24, S25, S29 |
| Ranging       | S10, S12         | S18, S21         | S23, S25      |
| HighVol       | S16 only         | —                | —             |
| EventRisk     | —                | S22              | S28           |
| ExpiryDay     | blocked          | —                | —             |

`AllowNewEntries=false` (set by regime classifier during extreme conditions) blocks all strategies.

---

## S10–S16 Scalping (1m–5m, 09:15–14:45 IST)

### S10 — Tick Scalp Bid/Ask Compression
- **File:** `engine/internal/strategy/s10_s16_scalping.go`
- **Timeframe:** 1m
- **Logic:** Detects bid/ask spread compression on ATM option chain (3-tick directional order flow). Entry on 3 consistent directional bars. Stop = 1×ATR1m beyond opposite extreme.
- **Allowed regimes:** Ranging, TrendingBull, TrendingBear. Blocked on ExpiryDay, HighVol.
- **Window:** 09:15–14:45 IST
- **Target WR:** 55%+

### S11 — Pullback Scalp VWAP Micro
- **Timeframe:** 1m + 5m VWAP
- **Logic:** 1m pullback to 5m session VWAP ±0.5×ATR1m. RSI<35 (long) or RSI>65 (short). Volume >1.5× avg confirms. SL = ATR1m beyond VWAP; TP = 2×risk.
- **Window:** 09:30–14:30 IST

### S12 — Volume Spike Scalp Order Flow
- **Logic:** 2×avg volume spike on 1m; 2 of 3 bars confirm direction. Body > 60% of range. SL = prior bar low/high.
- **Window:** 09:15–14:45 IST

### S13 — EMA Ribbon Scalp Fast
- **Logic:** EMA3 > EMA5 > EMA9 alignment on 1m. MACD histogram positive. Price within 0.5×ATR1m of EMA3. Ribbon collapse = exit.
- **Window:** 09:30–14:30 IST

### S14 — Breakout Scalp Support/Resistance
- **Logic:** Opening range (09:15–09:45) established on 5m. Breakout with 1.5×avg volume after 09:45. SL = within opening range. Active until 13:00.
- **VERIFY:** NSE circuit limits; large morning auction swings can widen the ORB artificially.

### S15 — RSI Divergence Scalp
- **Logic:** Price makes lower-low but RSI makes higher-low (bull divergence); opposite for bear. RSI must be <35 or >65 to confirm. Minimum 5 bars for divergence detection.
- **Window:** 09:30–13:30 IST

### S16 — ATR Breakout Scalp Volatility
- **Logic:** 5m candle close > 1.5×ATR5 from prior close signals explosive move. Only strategy allowed in HighVol regime. SL = 0.5×ATR5 back from entry.
- **Note:** High-conviction but rare (needs genuine volatility expansion, not just elevated VIX).

---

## S17–S22 Intraday (15m–1h, holds 45 min–4 hours)

### S17 — Opening Range Breakout Intraday
- **File:** `engine/internal/strategy/s17_s22_intraday.go`
- **Timeframe:** 15m; ORB from 09:15–09:45 IST
- **Logic:** 30-minute range established. Breakout above (CE) or below (PE) with directional gap (>0.5% vs prev close) or confirmed by TrendingBull/Bear regime. SL = opposite range extreme.
- **Window:** 09:45–11:30 IST
- **VERIFY:** NSE pre-open auction may move close before 09:15; prevClose source should use NSE official closing price, not last traded.

### S18 — VWAP Mean Reversion Straddle
- **Logic:** Session VWAP (09:15 IST onwards on 15m). Price extends >1.5×ATR1h from VWAP → mean reversion thesis. Buys ATM straddle on BankNifty weekly options. IV proxy: VIX < 1.2× rolling average.
- **Window:** 10:00–13:30 IST
- **Instrument:** STRANGLE (long call + long put; 2:1 R:R exempt — straddle geometry)
- **VERIFY:** Replace VIX proxy with real IV rank from option chain Greeks when available.

### S19 — ADX Trend Filter Breakouts
- **Timeframe:** 1h
- **Logic:** ADX > 25 AND +DI > -DI (long) or -DI > +DI (short). 3h breakout from 3-bar high/low. 1.5×ATR1h SL.
- **Window:** 10:30–14:00 IST
- **VERIFY:** ADX reliability on mid-cap stocks; check OI and circuit filters before entry.

### S20 — Fibonacci Retracement Intraday
- **Timeframe:** 1h
- **Logic:** 6-bar swing high/low. Entry at 38.2%–50% retracement. RSI<40 (bull) or RSI>60 (bear) confirms momentum exhaustion. SL beyond 61.8% level.
- **Window:** 10:30–13:30 IST
- **Note:** Swing range must be ≥50 points; otherwise the Fibonacci levels are noise.

### S21 — Bollinger Band Squeeze Breakout Intraday
- **Timeframe:** 15m; BB(20, 2)
- **Logic:** Current bandwidth is the narrowest in the last 20 bars (squeeze detected). Breakout above upper or below lower band with 1.5×avg volume. SL = opposite band.
- **Allowed:** Ranging, TrendingBull, TrendingBear (squeeze can precede any directional move)
- **Window:** 09:45–14:00 IST

### S22 — News Event Vol Fade (Options Sell)
- **Trigger:** EventRisk regime only (RBI policy, CPI, budget, index rebalance)
- **Logic:** VIX spike >1.5 points above 5-sample rolling avg. Realised move in last 30 minutes < 50% of daily ATR proxy → IV overpriced vs actual move → short strangle 2.5% OTM.
- **Window:** 09:45–12:00 IST (let opening spike settle first)
- **Instrument:** STRANGLE (short call + short put)
- **VERIFY:** RBI event dates, CPI release times. Update quarterly.

---

## S23–S29 Swing (daily–weekly, holds 1–15 days)

> These strategies use **1h candles with multi-day lookbacks** because the bundle
> has no daily-timeframe store. `deriveDailyCloses()` synthesises pseudo-daily
> closes from the last 1h bar before 15:30 IST each trading day.

### S23 — Weekly Options Theta Decay Strangle
- **File:** `engine/internal/strategy/s23_s29_swing.go`
- **Trigger:** Monday 09:45–10:15 IST only
- **Logic:** VIX < 20. Previous week's index range < 2.5%. Short OTM strangle (3% OTM) on Nifty/BankNifty weekly options. Theta decay target: Wednesday/Thursday (expiry).
- **VERIFY:** BankNifty weekly expiry moved to Wednesday (last Tuesday of month for monthly). Nifty weekly is Tuesday. Confirm current schedule before deploy.

### S24 — Momentum Breakout Swing
- **Logic:** 10-day (proxy: 70 bars 1h) consolidation range < 5% wide. EOD breakout with 2×avg volume. Entry next day open. SL = 0.5×ATR1h inside consolidation zone.
- **Trigger:** EOD (14:45–15:30 IST) signal
- **Instrument:** Stock futures (Nifty 200 constituents)

### S25 — Mean Reversion RSI Oversold Swing
- **Logic:** Pseudo-daily RSI (Wilder, 14) < 30 in bull regime, or > 70 in bear. EMA50 support/resistance filter. SL = 2×(ATR1h × barsPerDay × 0.5) for multi-day stop.
- **Allowed:** TrendingBull, TrendingBear, Ranging
- **Target WR:** 52%+   Holding: 2–5 days

### S26 — Sector Rotation Nifty Rebalance
- **Logic:** Friday EOD. Sector underlying with 4-week return < -3% in bull regime, not more than 5% below its 20-day EMA. Laggard-rotation long for following week.
- **Allowed:** TrendingBull only (laggard rotation is a bull-market phenomenon)
- **VERIFY:** Check NSE sector futures OI before entry; some sector futures are illiquid.

### S27 — Gap Up/Down Fade Options
- **Trigger:** 09:15–09:30 IST; gap of 0.7%–2.5% vs prevClose
- **Logic:** Gap is too large for fundamental news (above 2.5% = skip) but large enough to fade (below 0.7% = skip). Buy options in gap-fill direction. SL = 2×ATR5m extension.
- **Instrument:** CE (for gap-down fade) or PE (for gap-up fade)
- **VERIFY:** Large gaps on earnings / RBI policy days often do not fill intraday; the EventRisk regime check should filter these.

### S28 — Earnings Straddle IV Play
- **Trigger:** EventRisk regime; 11:30–12:00 IST only
- **Logic:** IV rank (VIX vs 5-sample rolling avg) between 1.1×–1.5×. Buy ATM straddle for gamma capture ahead of earnings move. SL = 2×ATR1h directional extension (overwhelms gamma). TP = premium doubles.
- **Instrument:** STRANGLE (long ATM straddle)
- **VERIFY:** Earnings calendar integration needed for correct filtering. SEBI restricts insiders from options positions within 1 day of earnings; system-level check required.

### S29 — Index Futures Positional Trend
- **Logic:** EMA20/EMA50 crossover on pseudo-daily closes. Entry EOD on crossover day. SL = 0.8×(ATR1h × barsPerDay) for multi-day stop. Target: 4× risk at second TP.
- **Allowed:** TrendingBull, TrendingBear
- **Target WR:** 48%+ (low WR offset by high R:R of 4:1 at second target)
- **Instrument:** Nifty or BankNifty rolling futures

---

## Signal geometry contract (enforced by IsValid)

All directional signals (FUTURE / CE / PE) must satisfy:
- `|Entry - StopLoss| / Entry >= MinSLDistancePct` (never noise-swept)
- `|TakeProfit - Entry| / |StopLoss - Entry| >= 2.0` (minimum 2:1 R:R)

Premium-selling / straddle strategies (STRANGLE) are exempt from the 2:1 R:R check
(inverted geometry: max loss is bounded, max gain is theta/IV crush). They apply only the
SL distance check.

---

## Broker adapters

| Adapter         | File                              | Notes                                      |
|-----------------|-----------------------------------|--------------------------------------------|
| Paper           | `internal/broker/paper.go`        | Wraps execution.Engine; IOC synthetic fill |
| Angel One live  | `internal/broker/angelone.go`     | SmartAPI REST; JWT from angel_one_config.py |
| Dhan live       | `internal/broker/dhan.go`         | DhanHQ v2 REST; JWT from dhan_config.py    |

Inject the adapter at startup:

```go
var b broker.Broker
if *liveMode {
    b = broker.NewAngelOneBroker(os.Getenv("AO_CLIENT_ID"), os.Getenv("AO_JWT"))
    // or: b = broker.NewDhanBroker(os.Getenv("DHAN_CLIENT_ID"), os.Getenv("DHAN_TOKEN"))
} else {
    b = broker.NewPaperBroker(execEngine, ledger)
}
```

**Never hard-code credentials** — read from environment or a secrets manager.

---

## Regulatory flags (summarised)

| Flag | Detail |
|------|--------|
| NSE weekly expiry schedule | BankNifty weekly discontinued Nov 2024; Nifty weekly = Tuesday. **Verify** before S23 deploy. |
| NSE holiday list | Static fallback in calendar.go — refresh via `RefreshFromNSE()` each December. |
| RBI/CPI event dates | S22, S28 rely on EventRisk regime being set correctly; wire an economic-calendar cron. |
| SEBI earnings blackout | S28: insiders blocked from options within 1 trading day of earnings; add KYC-level check. |
| NSE circuit breakers | 10%/15%/20% market-wide; strategies will not fire when AllowNewEntries=false. |
| Angel One rate limit | 1 req/sec on order APIs. PlaceOrder polls with 1s back-off (10 attempts max). |
| Dhan position limits | Enforced server-side by Dhan; broker will reject over-limit orders automatically. |

---

## Running tests

```powershell
cd engine
go test ./internal/strategy/... -v          # 43 tests, 1 expected skip (S29 crossover)
go test ./...                               # full suite: all pass
go vet ./...                               # clean
```
