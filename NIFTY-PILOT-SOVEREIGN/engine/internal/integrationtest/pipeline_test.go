// Package integrationtest drives the full classify -> evaluate -> risk
// gate -> paper execute pipeline end-to-end, the same path main.go's
// evaluationLoop runs every 5 seconds during market hours. It exists
// because the live engine can only be observed organically during
// 09:15-15:30 IST on a trading day; this test exercises the identical
// code path deterministically, at any time, against constructed
// candle data designed to produce a known regime and signal.
package integrationtest

import (
	"context"
	"math/rand"
	"testing"
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/execution"
	"niftypilot/internal/ledger"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
	"niftypilot/internal/risk"
	"niftypilot/internal/sizing"
	"niftypilot/internal/strategy"
)

// nextTradingTuesday returns 10:00 IST on the next Tuesday from base
// that is not in the calendar's holiday set, so EXPIRY_DAY for NIFTY
// (Tuesday, per calendar.IsExpiryDay) does NOT confuse the test - we
// deliberately pick a non-expiry weekday instead: Wednesday, 10:00 IST.
func nextTradingWednesday(cal *calendar.Service, base time.Time) time.Time {
	ist := base.In(calendar.IST)
	for {
		ist = ist.AddDate(0, 0, 1)
		if ist.Weekday() == time.Wednesday && cal.IsTradingDay(ist) {
			return time.Date(ist.Year(), ist.Month(), ist.Day(), 10, 0, 0, 0, calendar.IST)
		}
	}
}

// genTrendingCandles produces a deterministic, consistently-rising
// OHLCV series so EMA9>21>50 alignment and ADX>25 are reliably
// satisfied - a pure random walk (as used by the dev SyntheticFeed)
// would not reliably trend, and this test needs to prove the
// strategies' actual trend-following logic fires, not just that the
// pipeline doesn't crash on arbitrary data.
func genTrendingCandles(end time.Time, n int, step time.Duration, startPrice, perBarDrift float64) []marketdata.Candle {
	rng := rand.New(rand.NewSource(1))
	start := end.Add(-time.Duration(n) * step)
	price := startPrice
	out := make([]marketdata.Candle, 0, n)
	for i := 0; i < n; i++ {
		open := price
		drift := perBarDrift + perBarDrift*0.15*rng.Float64()
		close := open + drift
		high := close + perBarDrift*0.2*rng.Float64()
		low := open - perBarDrift*0.2*rng.Float64()
		out = append(out, marketdata.Candle{
			Time: start.Add(time.Duration(i) * step), Open: open, High: high, Low: low, Close: close,
			Volume: 60000 + rng.Float64()*20000,
		})
		price = close
	}
	return out
}

func buildTrendingBundle(now time.Time) (*marketdata.NiftyDataBundle, float64) {
	bundle := marketdata.NewNiftyDataBundle()

	// All four timeframes must agree on "the price right now", so each
	// series is anchored backward from the SAME endPrice using its own
	// per-bar drift (perMinuteDrift * minutes-per-bar) and bar count -
	// otherwise four independently-drifting series disagree wildly at
	// "now" (a bug this fixture originally had: a 1m series ending
	// near 24480 compared against a 15m EMA50 that had drifted to
	// ~29000, because the 15m series covered a much longer lookback at
	// the same per-bar drift, from the same start price).
	const perMinuteDrift = 1.2
	const endPrice = 30000.0

	anchored := func(n int, step time.Duration, driftPerBar float64) []marketdata.Candle {
		startPrice := endPrice - float64(n)*driftPerBar
		return genTrendingCandles(now, n, step, startPrice, driftPerBar)
	}

	c1m := anchored(400, time.Minute, perMinuteDrift)
	c5m := anchored(300, 5*time.Minute, perMinuteDrift*5)
	c15m := anchored(300, 15*time.Minute, perMinuteDrift*15)
	c1h := anchored(300, time.Hour, perMinuteDrift*60)

	bundle.SeedCandles("NIFTY", "1m", c1m)
	bundle.SeedCandles("NIFTY", "5m", c5m)
	bundle.SeedCandles("NIFTY", "15m", c15m)
	bundle.SeedCandles("NIFTY", "1h", c1h)

	lastSpot := c15m[len(c15m)-1].Close
	bundle.SetSpot("NIFTY", lastSpot, now)
	bundle.SetIndiaVIX(14.0) // < 16, required for TRENDING_BULL

	feed := marketdata.NewSyntheticFeed()
	chain, _ := feed.OptionChain(context.Background(), "NIFTY")
	chain.SpotPrice = lastSpot
	bundle.SetOptionChain("NIFTY", chain)

	return bundle, lastSpot
}

// TestFullPipeline_TrendingRegime_GeneratesAndSettlesATrade drives the
// exact sequence main.go's evaluationLoop runs: regime classify ->
// strategy evaluate -> risk gate -> paper entry -> paper exit, and
// asserts a trend-following strategy actually fires on a deterministic
// uptrend, the risk gate allows it, and the ledger settles it with the
// Indian cost model applied on both legs (non-zero entry AND exit cost
// - the BTC engine's exact P0 bug class this build was built to avoid).
func TestFullPipeline_TrendingRegime_GeneratesAndSettlesATrade(t *testing.T) {
	cal := calendar.NewService()
	now := nextTradingWednesday(cal, time.Now())
	if !cal.IsMarketOpen(now) {
		t.Fatalf("test setup bug: chosen timestamp %v is not within market hours per the calendar service", now)
	}

	bundle, lastSpot := buildTrendingBundle(now)
	classifier := regime.NewClassifier(cal, regime.DefaultEventCalendar())
	rc := classifier.Classify("NIFTY", bundle, now)

	if rc.Regime != regime.TrendingBull {
		t.Fatalf("expected TRENDING_BULL on a deterministic uptrend, got %s (reason: %s, ADX=%.1f, VIX=%.1f)",
			rc.Regime, rc.Reason, rc.ADX, rc.VIXLevel)
	}
	if !rc.AllowNewEntries {
		t.Fatal("expected AllowNewEntries=true in TRENDING_BULL")
	}

	mctx := strategy.MarketContext{Now: now, Underlying: "NIFTY", Bundle: bundle, Regime: rc}

	l := ledger.New()
	execEngine := execution.NewEngine(l)
	riskEngine := risk.NewEngine(risk.DefaultConfig(), cal, 1_00_00_000.0)

	var fired []string
	for _, s := range strategy.AllStrategies() {
		sig, ok := s.Evaluate(mctx)
		if !ok {
			continue
		}
		fired = append(fired, s.Name())

		allowed, reason := riskEngine.CheckEntryAllowed(now, 1_00_00_000.0, string(sig.Direction))
		if !allowed {
			t.Fatalf("risk engine blocked a valid signal from %s on a clean account: %s", s.Name(), reason)
		}

		trade := execEngine.ExecuteEntry(sig, 1, 20.0)
		if trade.EntryCostINR <= 0 {
			t.Fatalf("%s: expected positive entry cost, got %.2f", s.Name(), trade.EntryCostINR)
		}
		riskEngine.RegisterOpen(trade.Direction)

		exitPrice := sig.TakeProfit
		execEngine.ExecuteExit(trade.ID, exitPrice, now.Add(30*time.Minute), "TP", 20.0)
		closed, ok := l.Trade(trade.ID)
		if !ok || closed.Status != ledger.StatusClosed {
			t.Fatalf("%s: trade %s did not settle to CLOSED", s.Name(), trade.ID)
		}
		if closed.ExitCostINR <= 0 {
			t.Fatalf("%s: expected positive EXIT cost (entry-only fee charging is the exact BTC-engine P0 bug class), got %.2f", s.Name(), closed.ExitCostINR)
		}
		riskEngine.RegisterClose(trade.Direction)
	}

	if len(fired) == 0 {
		t.Fatalf("no strategy fired on a deterministic TRENDING_BULL uptrend (spot=%.2f) - expected at least S1_ORB or S8_EMA_Ribbon to engage", lastSpot)
	}
	t.Logf("strategies fired on deterministic uptrend: %v", fired)

	if len(l.ClosedTrades()) != len(fired) {
		t.Fatalf("expected %d closed trades, got %d", len(fired), len(l.ClosedTrades()))
	}
}

// TestFullPipeline_MarketClosed_BlocksAllEntries proves the risk
// engine's market-hours gate actually blocks entries outside
// 09:15-15:30 IST, using a real Saturday timestamp (today, at the time
// this test suite was authored, is a Saturday - the same condition
// observed live against the running engine during manual testing).
func TestFullPipeline_MarketClosed_BlocksAllEntries(t *testing.T) {
	cal := calendar.NewService()
	saturday := time.Date(2026, 6, 20, 11, 0, 0, 0, calendar.IST)
	if saturday.Weekday() != time.Saturday {
		t.Fatalf("test fixture bug: 2026-06-20 is not a Saturday")
	}
	riskEngine := risk.NewEngine(risk.DefaultConfig(), cal, 1_00_00_000.0)
	allowed, reason := riskEngine.CheckEntryAllowed(saturday, 1_00_00_000.0, "LONG")
	if allowed {
		t.Fatal("expected market-closed Saturday to block entry, but it was allowed")
	}
	if reason == "" {
		t.Fatal("expected a non-empty block reason")
	}
}

// TestFullPipeline_MarginGateBlocksOversizedStrangle proves the
// SPAN+exposure margin constraint layer (the addition over the BTC
// engine's simple position-count caps) actually rejects a position
// that would exceed available margin.
func TestFullPipeline_MarginGateBlocksOversizedStrangle(t *testing.T) {
	book := &sizing.MarginBook{TotalCapitalINR: 1_00_00_000.0}
	est := sizing.EstimateShortStrangle("NIFTY", 25200, 24600, 24900, 50) // 50 lots, deliberately oversized
	if book.CanOpen(est.TotalMarginINR) {
		t.Fatalf("expected 50-lot strangle margin (%.0f) to exceed Rs 1Cr capital, but CanOpen returned true", est.TotalMarginINR)
	}

	smallEst := sizing.EstimateShortStrangle("NIFTY", 25200, 24600, 24900, 1)
	if !book.CanOpen(smallEst.TotalMarginINR) {
		t.Fatalf("expected a 1-lot strangle (%.0f) to fit within Rs 1Cr capital", smallEst.TotalMarginINR)
	}
}
