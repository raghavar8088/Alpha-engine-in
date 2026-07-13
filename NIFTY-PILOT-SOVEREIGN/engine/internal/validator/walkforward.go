// Package validator implements the walk-forward strategy promotion
// gate. A 30-trade minimum window, two consecutive passing windows
// required for promotion to ACTIVE, and a fast-demotion rule for
// an ACTIVE strategy that has one bad window.
//
// Validation gate (UPDATED): WinRate >= 40%, ProfitFactor > 1.0,
// positive Expectancy, and Sharpe >= 0.60 must ALL pass for promotion.
package validator

import "math"

type Status string

const (
	StatusProbation Status = "PROBATION" // accumulating trades toward the first window
	StatusPending   Status = "PENDING"   // first window passed, awaiting second confirmation window
	StatusActive    Status = "ACTIVE"    // both confirmation windows passed
	StatusDemoted   Status = "DEMOTED"   // fast-demoted after an ACTIVE strategy's bad window
)

const (
	MinTradesPerWindow       = 30
	PromotionMinSharpe       = 0.60
	PromotionMinWinRate      = 0.40  // minimum 40% win rate required
	PromotionMinProfitFactor = 1.0   // profit factor must exceed 1.0
	PromotionMinExpectancy   = 0.0   // must have positive expected value per trade
	DemotionMaxSharpe        = 0.20
	DemotionMinWinRate       = 0.30
	MaxAllowedDrawdownPct    = 0.25  // 25% max drawdown allowed
)

// TradeResult is the minimal per-trade input the validator needs.
type TradeResult struct {
	NetPnL float64
	Win    bool
}

// WindowStats summarizes one 30-trade window including all validation metrics.
type WindowStats struct {
	Trades       int
	WinRate      float64
	Sharpe       float64
	ProfitFactor float64
	Expectancy   float64
	MaxDrawdown  float64 // as a negative fraction, e.g. -0.15 = -15%
}

// ValidationFailure describes why a strategy failed validation.
type ValidationFailure struct {
	Rule   string
	Actual float64
	Target float64
}

// ValidationResult is returned by ValidateWindow with pass/fail and reasons.
type ValidationResult struct {
	Passed   bool
	Failures []ValidationFailure
}

func ComputeWindowStats(trades []TradeResult) WindowStats {
	n := len(trades)
	if n == 0 {
		return WindowStats{}
	}
	wins := 0
	var sum, sumSq float64
	var grossWin, grossLoss float64
	var winCount, lossCount int

	for _, t := range trades {
		if t.Win {
			wins++
			grossWin += t.NetPnL
			winCount++
		} else {
			grossLoss += -t.NetPnL
			lossCount++
		}
		sum += t.NetPnL
		sumSq += t.NetPnL * t.NetPnL
	}
	mean := sum / float64(n)
	variance := sumSq/float64(n) - mean*mean
	if variance < 0 {
		variance = 0
	}
	stddev := math.Sqrt(variance)
	sharpe := 0.0
	if stddev > 0 {
		sharpe = mean / stddev
	}

	// Profit Factor
	profitFactor := 0.0
	if grossLoss > 0 {
		profitFactor = grossWin / grossLoss
	} else if grossWin > 0 {
		profitFactor = math.Inf(1)
	}

	// Expectancy = WR*avgWin - (1-WR)*avgLoss
	wr := float64(wins) / float64(n)
	avgWin := 0.0
	avgLoss := 0.0
	if winCount > 0 {
		avgWin = grossWin / float64(winCount)
	}
	if lossCount > 0 {
		avgLoss = grossLoss / float64(lossCount)
	}
	expectancy := wr*avgWin - (1-wr)*avgLoss

	// Max Drawdown from PnL sequence
	maxDD := computeMaxDrawdownFromPnLs(trades)

	return WindowStats{
		Trades:       n,
		WinRate:      wr,
		Sharpe:       sharpe,
		ProfitFactor: profitFactor,
		Expectancy:   expectancy,
		MaxDrawdown:  maxDD,
	}
}

func computeMaxDrawdownFromPnLs(trades []TradeResult) float64 {
	if len(trades) == 0 {
		return 0
	}
	peak := 0.0
	equity := 0.0
	maxDD := 0.0
	for _, t := range trades {
		equity += t.NetPnL
		if equity > peak {
			peak = equity
		}
		if peak > 0 {
			dd := (equity - peak) / peak
			if dd < maxDD {
				maxDD = dd
			}
		}
	}
	return maxDD
}

// Validate runs all promotion validation rules and returns a detailed result.
func ValidateWindow(w WindowStats) ValidationResult {
	var failures []ValidationFailure

	if w.Trades < MinTradesPerWindow {
		failures = append(failures, ValidationFailure{
			Rule: "MinTrades", Actual: float64(w.Trades), Target: float64(MinTradesPerWindow),
		})
	}
	if w.WinRate < PromotionMinWinRate {
		failures = append(failures, ValidationFailure{
			Rule: "WinRate", Actual: w.WinRate * 100, Target: PromotionMinWinRate * 100,
		})
	}
	if w.Sharpe < PromotionMinSharpe {
		failures = append(failures, ValidationFailure{
			Rule: "Sharpe", Actual: w.Sharpe, Target: PromotionMinSharpe,
		})
	}
	pf := w.ProfitFactor
	if math.IsInf(pf, 1) {
		pf = 999
	}
	if pf < PromotionMinProfitFactor {
		failures = append(failures, ValidationFailure{
			Rule: "ProfitFactor", Actual: pf, Target: PromotionMinProfitFactor,
		})
	}
	if w.Expectancy < PromotionMinExpectancy {
		failures = append(failures, ValidationFailure{
			Rule: "Expectancy", Actual: w.Expectancy, Target: PromotionMinExpectancy,
		})
	}
	if w.MaxDrawdown < -MaxAllowedDrawdownPct {
		failures = append(failures, ValidationFailure{
			Rule: "MaxDrawdown", Actual: w.MaxDrawdown * 100, Target: -MaxAllowedDrawdownPct * 100,
		})
	}
	return ValidationResult{Passed: len(failures) == 0, Failures: failures}
}

// Passes reports whether all promotion criteria are met.
func (w WindowStats) Passes() bool {
	return ValidateWindow(w).Passed
}

func (w WindowStats) IsBadWindow() bool {
	return w.Trades >= MinTradesPerWindow && (w.Sharpe < DemotionMaxSharpe || w.WinRate < DemotionMinWinRate)
}

// StrategyTrack holds the rolling walk-forward state for one strategy.
type StrategyTrack struct {
	Strategy         string
	Status           Status
	completedWindows []WindowStats
	currentWindow    []TradeResult
	lastRejection    []ValidationFailure
}

func NewStrategyTrack(name string) *StrategyTrack {
	return &StrategyTrack{Strategy: name, Status: StatusProbation}
}

// RecordTrade appends a closed trade to the current window and
// advances the window/status machine once a window fills.
func (s *StrategyTrack) RecordTrade(tr TradeResult) {
	s.currentWindow = append(s.currentWindow, tr)
	if len(s.currentWindow) < MinTradesPerWindow {
		return
	}
	stats := ComputeWindowStats(s.currentWindow)
	s.completedWindows = append(s.completedWindows, stats)
	s.currentWindow = nil

	result := ValidateWindow(stats)

	switch s.Status {
	case StatusProbation:
		if result.Passed {
			s.Status = StatusPending
			s.lastRejection = nil
		} else {
			s.lastRejection = result.Failures
		}

	case StatusPending:
		if result.Passed {
			s.Status = StatusActive
			s.lastRejection = nil
		} else {
			s.Status = StatusProbation
			s.lastRejection = result.Failures
		}

	case StatusActive:
		if stats.IsBadWindow() {
			s.Status = StatusDemoted
		}

	case StatusDemoted:
		// Requires manual operator review to re-enter PROBATION.
	}
}

func (s *StrategyTrack) LastWindow() (WindowStats, bool) {
	if len(s.completedWindows) == 0 {
		return WindowStats{}, false
	}
	return s.completedWindows[len(s.completedWindows)-1], true
}

// LastRejectionReasons returns the validation failures from the last rejected window.
func (s *StrategyTrack) LastRejectionReasons() []ValidationFailure {
	return s.lastRejection
}

// IsTradeable reports whether the strategy may generate new entries.
// PROBATION and PENDING strategies keep trading to accumulate windows;
// only a DEMOTED strategy is cut off pending manual review.
func (s *StrategyTrack) IsTradeable() bool {
	return s.Status != StatusDemoted
}

// IsMockTradingApproved reports whether the strategy has met all
// validation requirements and is approved for mock trading.
// Requires at least PENDING status (one passing window).
func (s *StrategyTrack) IsMockTradingApproved() bool {
	return s.Status == StatusPending || s.Status == StatusActive
}

// CurrentWindowProgress returns the number of trades in the current incomplete window.
func (s *StrategyTrack) CurrentWindowProgress() int {
	return len(s.currentWindow)
}

// AllWindows returns all completed window stats for this strategy.
func (s *StrategyTrack) AllWindows() []WindowStats {
	return s.completedWindows
}
