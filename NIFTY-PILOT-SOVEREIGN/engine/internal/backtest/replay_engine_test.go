package backtest

import (
	"context"
	"io"
	"os"
	"testing"
	"time"

	"niftypilot/internal/calendar"
)

func testConfig(from, to time.Time) Config {
	return Config{
		From:       from,
		To:         to,
		CapitalINR: 1_00_00_000,
		WarmupDays: 25, // ensure ≥200 15m bars so regime != UNKNOWN
		Instruments: []Instrument{
			{Symbol: "NIFTY50", Underlying: "NIFTY", Token: "256265"},
			{Symbol: "BANKNIFTY", Underlying: "BANKNIFTY", Token: "260105"},
		},
		Verbose: false,
		Logw:    io.Discard,
	}
}

func runShortBacktest(t *testing.T, seed int64) BacktestResults {
	t.Helper()
	from := time.Date(2024, 1, 15, 0, 0, 0, 0, calendar.IST).UTC()
	to := time.Date(2024, 2, 9, 23, 59, 59, 0, calendar.IST).UTC()
	eng, err := NewBacktestEngine(testConfig(from, to), NewSyntheticFetcher(seed))
	if err != nil {
		t.Fatalf("engine init: %v", err)
	}
	res, err := eng.Run(context.Background())
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	return res
}

func TestReplayProducesEquityCurve(t *testing.T) {
	res := runShortBacktest(t, 42)
	if len(res.Equity) == 0 {
		t.Fatal("no equity points produced")
	}
	// equity should start at (or near) starting capital
	first := res.Equity[0].EquityINR
	if first <= 0 {
		t.Errorf("first equity point non-positive: %v", first)
	}
}

func TestReplayDeterministic(t *testing.T) {
	a := runShortBacktest(t, 42)
	b := runShortBacktest(t, 42)
	if len(a.Trades) != len(b.Trades) {
		t.Fatalf("non-deterministic trade count: %d vs %d", len(a.Trades), len(b.Trades))
	}
	if len(a.Equity) == 0 || len(b.Equity) == 0 {
		t.Fatal("missing equity")
	}
	af := a.Equity[len(a.Equity)-1].EquityINR
	bf := b.Equity[len(b.Equity)-1].EquityINR
	if af != bf {
		t.Errorf("non-deterministic final equity: %.4f vs %.4f", af, bf)
	}
	for i := range a.Trades {
		if a.Trades[i].NetPnL != b.Trades[i].NetPnL || a.Trades[i].Strategy != b.Trades[i].Strategy {
			t.Fatalf("trade %d differs between runs", i)
		}
	}
}

func TestReplayTradesWithinMarketHours(t *testing.T) {
	res := runShortBacktest(t, 42)
	cal := calendar.NewService()
	for _, tr := range res.Trades {
		ist := tr.EntryAt.In(calendar.IST)
		mins := ist.Hour()*60 + ist.Minute()
		if mins < calendar.MarketOpen || mins > calendar.MarketClose {
			t.Errorf("%s entry outside 09:15-15:30 IST: %s", tr.Strategy, ist.Format("15:04"))
		}
		if ist.Weekday() == time.Saturday || ist.Weekday() == time.Sunday {
			t.Errorf("%s entry on weekend: %v", tr.Strategy, ist.Weekday())
		}
		if !cal.IsTradingDay(tr.EntryAt) {
			t.Errorf("%s entry on non-trading day: %s", tr.Strategy, ist.Format("2006-01-02"))
		}
	}
}

func TestReplayWalkForwardComputedForAllStrategies(t *testing.T) {
	res := runShortBacktest(t, 42)
	if len(res.WalkForward) != 29 {
		t.Errorf("walk-forward results = %d, want 29 (one per strategy)", len(res.WalkForward))
	}
	for _, wf := range res.WalkForward {
		switch wf.PromotionStatus {
		case PromotionPromoted, PromotionRejected, PromotionInsufficient:
			// valid
		default:
			t.Errorf("%s: invalid promotion status %q", wf.Strategy, wf.PromotionStatus)
		}
	}
}

func TestReplayTradePnLConsistency(t *testing.T) {
	res := runShortBacktest(t, 42)
	for _, tr := range res.Trades {
		// NetPnL must equal Gross minus both cost legs (PART 7: costs on both legs).
		want := tr.GrossPnL - tr.EntryCostINR - tr.ExitCostINR
		if diff := tr.NetPnL - want; diff > 0.01 || diff < -0.01 {
			t.Errorf("%s: NetPnL %.2f != Gross %.2f - entryCost %.2f - exitCost %.2f",
				tr.Strategy, tr.NetPnL, tr.GrossPnL, tr.EntryCostINR, tr.ExitCostINR)
		}
		if tr.ExitCostINR <= 0 {
			t.Errorf("%s: exit cost not charged (%.2f) — both legs must be costed", tr.Strategy, tr.ExitCostINR)
		}
	}
}

func TestReplayNoDataError(t *testing.T) {
	// A window with no trading days yields no timeline.
	from := time.Date(2024, 1, 13, 0, 0, 0, 0, calendar.IST).UTC() // Saturday
	to := time.Date(2024, 1, 14, 23, 59, 0, 0, calendar.IST).UTC() // Sunday
	cfg := testConfig(from, to)
	cfg.WarmupDays = 0
	eng, err := NewBacktestEngine(cfg, NewSyntheticFetcher(42))
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	_, err = eng.Run(context.Background())
	if err != ErrNoData {
		t.Errorf("weekend-only window: err = %v, want ErrNoData", err)
	}
}

func TestGenerateAllWritesArtifacts(t *testing.T) {
	res := runShortBacktest(t, 42)
	res.DataSource = "Synthetic"
	dir := t.TempDir()
	if err := GenerateAll(res, dir); err != nil {
		t.Fatalf("GenerateAll: %v", err)
	}
	wantFiles := []string{
		"summary.json", "summary.md", "equity_curve.csv", "equity_curve.png",
		"trades.csv", "leaderboard.json", "daily_pnl.csv",
		"walkforward_details.json", "regime_analysis.csv",
	}
	for _, fn := range wantFiles {
		if _, err := readFileLen(dir + "/" + fn); err != nil {
			t.Errorf("expected artifact %s: %v", fn, err)
		}
	}
}

func readFileLen(path string) (int, error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	b, err := io.ReadAll(f)
	return len(b), err
}
