package backtest

import (
	"math"
	"testing"

	"niftypilot/internal/ledger"
)

func tr(pnl float64) ledger.Trade { return ledger.Trade{NetPnL: pnl} }

func TestWinRate(t *testing.T) {
	trades := []ledger.Trade{tr(100), tr(-50), tr(20), tr(-10), tr(0)}
	// wins: 100,20 -> 2; breakeven(0) counts as loss -> 2/5 = 0.4
	if got := WinRate(trades); math.Abs(got-0.4) > 1e-9 {
		t.Errorf("WinRate = %v, want 0.4", got)
	}
}

func TestWinRateEmpty(t *testing.T) {
	if got := WinRate(nil); got != 0 {
		t.Errorf("WinRate(nil) = %v, want 0", got)
	}
}

func TestProfitFactor(t *testing.T) {
	trades := []ledger.Trade{tr(100), tr(50), tr(-30), tr(-20)}
	// wins=150, losses=50 -> 3.0
	if got := ProfitFactor(trades); math.Abs(got-3.0) > 1e-9 {
		t.Errorf("ProfitFactor = %v, want 3.0", got)
	}
}

func TestProfitFactorNoLosses(t *testing.T) {
	trades := []ledger.Trade{tr(100), tr(50)}
	if got := ProfitFactor(trades); !math.IsInf(got, 1) {
		t.Errorf("ProfitFactor (no losses) = %v, want +Inf", got)
	}
}

func TestProfitFactorNoWins(t *testing.T) {
	trades := []ledger.Trade{tr(-100), tr(-50)}
	if got := ProfitFactor(trades); got != 0 {
		t.Errorf("ProfitFactor (no wins) = %v, want 0", got)
	}
}

func TestExpectancy(t *testing.T) {
	trades := []ledger.Trade{tr(100), tr(100), tr(-50), tr(-50)}
	// wr=0.5, avgWin=100, avgLoss=50 -> 0.5*100 - 0.5*50 = 25
	if got := Expectancy(trades); math.Abs(got-25) > 1e-9 {
		t.Errorf("Expectancy = %v, want 25", got)
	}
}

func TestAvgWinLoss(t *testing.T) {
	trades := []ledger.Trade{tr(80), tr(120), tr(-40), tr(-60)}
	w, l := AvgWinLoss(trades)
	if math.Abs(w-100) > 1e-9 || math.Abs(l-50) > 1e-9 {
		t.Errorf("AvgWinLoss = (%v,%v), want (100,50)", w, l)
	}
}

func TestMaxDrawdownFromEquity(t *testing.T) {
	// peak 100k -> trough 95k -> recover. maxDD = -5%
	eq := []float64{100000, 102000, 95000, 99000}
	got := MaxDrawdownFromEquity(eq)
	want := 95000.0/102000.0 - 1 // trough vs prior peak 102k
	if math.Abs(got-want) > 1e-9 {
		t.Errorf("MaxDrawdown = %v, want %v", got, want)
	}
}

func TestMaxDrawdownMonotonicUp(t *testing.T) {
	eq := []float64{100, 110, 120, 130}
	if got := MaxDrawdownFromEquity(eq); got != 0 {
		t.Errorf("MaxDrawdown (monotonic up) = %v, want 0", got)
	}
}

func TestMaxDrawdownFromPnls(t *testing.T) {
	pnls := []float64{1000, -3000, 500}
	// equity: 100000, 101000, 98000, 98500. peak 101000, trough 98000 -> ~-2.97%
	got := MaxDrawdownFromPnls(pnls, 100000)
	want := 98000.0/101000.0 - 1
	if math.Abs(got-want) > 1e-9 {
		t.Errorf("MaxDrawdownFromPnls = %v, want %v", got, want)
	}
}

func TestAnnualizedSharpeZeroVol(t *testing.T) {
	returns := []float64{0.01, 0.01, 0.01}
	if got := AnnualizedSharpe(returns, 252); !math.IsNaN(got) {
		t.Errorf("Sharpe (zero vol) = %v, want NaN", got)
	}
}

func TestAnnualizedSharpePositive(t *testing.T) {
	// consistent positive returns with small variance -> positive Sharpe
	returns := []float64{0.01, 0.012, 0.008, 0.011, 0.009}
	got := AnnualizedSharpe(returns, 252)
	if math.IsNaN(got) || got <= 0 {
		t.Errorf("Sharpe = %v, want positive finite", got)
	}
}

func TestAnnualizedSharpeInsufficient(t *testing.T) {
	if got := AnnualizedSharpe([]float64{0.01}, 252); !math.IsNaN(got) {
		t.Errorf("Sharpe (1 point) = %v, want NaN", got)
	}
}

func TestAnnualizedReturnFromEquity(t *testing.T) {
	// double money in 252 days -> 100% annualized
	got := AnnualizedReturnFromEquity(100000, 200000, 252)
	if math.Abs(got-1.0) > 1e-9 {
		t.Errorf("AnnualizedReturn = %v, want 1.0", got)
	}
}

func TestRecoveryFactor(t *testing.T) {
	if got := RecoveryFactor(50000, -10000); math.Abs(got-5.0) > 1e-9 {
		t.Errorf("RecoveryFactor = %v, want 5.0", got)
	}
	if got := RecoveryFactor(50000, 0); !math.IsInf(got, 1) {
		t.Errorf("RecoveryFactor (no DD) = %v, want +Inf", got)
	}
}

func TestWinOfBreakeven(t *testing.T) {
	if WinOf(tr(0)) {
		t.Error("breakeven (NetPnL=0) must count as loss")
	}
	if !WinOf(tr(0.01)) {
		t.Error("positive NetPnL must count as win")
	}
}
