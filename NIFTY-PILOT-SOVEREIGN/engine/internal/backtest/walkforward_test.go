package backtest

import (
	"testing"

	"niftypilot/internal/ledger"
)

// makeTrades builds n trades alternating to hit a target win rate with a
// fixed win/loss magnitude, producing a controllable Sharpe.
func makeTrades(n int, winEvery int, win, loss float64) []ledger.Trade {
	out := make([]ledger.Trade, 0, n)
	for i := 0; i < n; i++ {
		if winEvery > 0 && i%winEvery != 0 {
			out = append(out, ledger.Trade{NetPnL: win})
		} else {
			out = append(out, ledger.Trade{NetPnL: -loss})
		}
	}
	return out
}

// strongTrades: high win rate, low variance -> passes (Sharpe>=0.6, WR>=0.48).
func strongTrades(n int) []ledger.Trade {
	out := make([]ledger.Trade, 0, n)
	for i := 0; i < n; i++ {
		if i%5 == 0 {
			out = append(out, ledger.Trade{NetPnL: -80}) // 20% losers
		} else {
			out = append(out, ledger.Trade{NetPnL: 100}) // 80% winners
		}
	}
	return out
}

// weakTrades: low win rate -> fails.
func weakTrades(n int) []ledger.Trade {
	out := make([]ledger.Trade, 0, n)
	for i := 0; i < n; i++ {
		if i%5 == 0 {
			out = append(out, ledger.Trade{NetPnL: 100}) // only 20% winners
		} else {
			out = append(out, ledger.Trade{NetPnL: -100})
		}
	}
	return out
}

func TestWalkForwardInsufficientData(t *testing.T) {
	res := EvaluateWalkForward("S_test", strongTrades(20), 100000)
	if res.PromotionStatus != PromotionInsufficient {
		t.Errorf("20 trades: got %s, want %s", res.PromotionStatus, PromotionInsufficient)
	}
	if res.Window1.Status != WindowInsufficient {
		t.Errorf("window1 status = %s, want INSUFFICIENT_DATA", res.Window1.Status)
	}
}

func TestWalkForwardPromoted(t *testing.T) {
	res := EvaluateWalkForward("S_test", strongTrades(60), 100000)
	if res.Window1.Status != WindowPass {
		t.Fatalf("window1 = %s (sharpe %.2f wr %.2f), want PASS", res.Window1.Status, res.Window1.Sharpe, res.Window1.WinRate)
	}
	if res.Window2.Status != WindowPass {
		t.Fatalf("window2 = %s, want PASS", res.Window2.Status)
	}
	if res.PromotionStatus != PromotionPromoted {
		t.Errorf("promotion = %s, want PROMOTED", res.PromotionStatus)
	}
}

func TestWalkForwardRejectedWindow1Fail(t *testing.T) {
	res := EvaluateWalkForward("S_test", weakTrades(60), 100000)
	if res.Window1.Status != WindowFail {
		t.Fatalf("window1 = %s, want FAIL", res.Window1.Status)
	}
	if res.PromotionStatus != PromotionRejected {
		t.Errorf("promotion = %s, want REJECTED", res.PromotionStatus)
	}
}

func TestWalkForwardFastDemotion(t *testing.T) {
	// Window 1 strong (passes), Window 2 weak (fails) -> REJECTED.
	trades := append(strongTrades(30), weakTrades(30)...)
	res := EvaluateWalkForward("S_test", trades, 100000)
	if res.Window1.Status != WindowPass {
		t.Fatalf("window1 = %s, want PASS", res.Window1.Status)
	}
	if res.Window2.Status != WindowFail {
		t.Fatalf("window2 = %s, want FAIL", res.Window2.Status)
	}
	if res.PromotionStatus != PromotionRejected {
		t.Errorf("promotion = %s, want REJECTED (fast-demotion)", res.PromotionStatus)
	}
}

func TestWalkForwardPendingConfirmation(t *testing.T) {
	// Window 1 passes but only 45 trades total -> awaiting confirmation.
	trades := append(strongTrades(30), strongTrades(15)...)
	res := EvaluateWalkForward("S_test", trades, 100000)
	if res.Window1.Status != WindowPass {
		t.Fatalf("window1 = %s, want PASS", res.Window1.Status)
	}
	if res.PromotionStatus != PromotionInsufficient {
		t.Errorf("promotion = %s, want INSUFFICIENT_DATA (awaiting window 2)", res.PromotionStatus)
	}
}

func TestWalkForwardWindowBoundaries(t *testing.T) {
	res := EvaluateWalkForward("S_test", strongTrades(60), 100000)
	if res.Window1.StartTrade != 1 || res.Window1.EndTrade != 30 {
		t.Errorf("window1 bounds = [%d,%d], want [1,30]", res.Window1.StartTrade, res.Window1.EndTrade)
	}
	if res.Window2.StartTrade != 31 || res.Window2.EndTrade != 60 {
		t.Errorf("window2 bounds = [%d,%d], want [31,60]", res.Window2.StartTrade, res.Window2.EndTrade)
	}
}

func TestWalkForwardProfitFactorComputed(t *testing.T) {
	res := EvaluateWalkForward("S_test", strongTrades(60), 100000)
	// 80% winners @100, 20% losers @80 -> PF = (24*100)/(6*80) = 2400/480 = 5.0
	if res.Window1.ProfitFactor < 4.9 || res.Window1.ProfitFactor > 5.1 {
		t.Errorf("window1 ProfitFactor = %v, want ~5.0", res.Window1.ProfitFactor)
	}
}
