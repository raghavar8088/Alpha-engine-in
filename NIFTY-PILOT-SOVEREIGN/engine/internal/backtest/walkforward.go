package backtest

import (
	"encoding/json"
	"fmt"
	"math"
	"time"

	"niftypilot/internal/ledger"
	"niftypilot/internal/validator"
)

// WalkForwardWindow summarizes one 30-trade window (PART 3). The PASS/FAIL
// Sharpe and WinRate are computed by the SAME validator.ComputeWindowStats
// used by the live engine — the harness does NOT re-implement the rule, it
// reuses it, so backtest and live promotion logic can never diverge.
type WalkForwardWindow struct {
	StartTrade   int     `json:"start_trade"`
	EndTrade     int     `json:"end_trade"`
	Trades       int     `json:"trades"`
	Sharpe       float64 `json:"sharpe"`        // per-trade Sharpe (validator rule, threshold 0.60)
	WinRate      float64 `json:"win_rate"`
	MaxDrawdown  float64 `json:"max_drawdown"`  // fraction, negative
	ProfitFactor float64 `json:"profit_factor"`
	AvgWinSize   float64 `json:"avg_win_size_inr"`
	AvgLossSize  float64 `json:"avg_loss_size_inr"`
	Status       string  `json:"status"` // PASS | FAIL | INSUFFICIENT_DATA
}

// MarshalJSON renders Sharpe/ProfitFactor JSON-safely (encoding/json rejects
// raw NaN/+Inf, which arise for zero-variance or zero-loss windows).
func (w WalkForwardWindow) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		StartTrade   int     `json:"start_trade"`
		EndTrade     int     `json:"end_trade"`
		Trades       int     `json:"trades"`
		Sharpe       any     `json:"sharpe"`
		WinRate      float64 `json:"win_rate"`
		MaxDrawdown  float64 `json:"max_drawdown"`
		ProfitFactor any     `json:"profit_factor"`
		AvgWinSize   float64 `json:"avg_win_size_inr"`
		AvgLossSize  float64 `json:"avg_loss_size_inr"`
		Status       string  `json:"status"`
	}{
		w.StartTrade, w.EndTrade, w.Trades, jsonFloat(w.Sharpe), w.WinRate,
		w.MaxDrawdown, jsonFloat(w.ProfitFactor), w.AvgWinSize, w.AvgLossSize, w.Status,
	})
}

// WalkForwardResult is the full per-strategy promotion decision (PART 3).
type WalkForwardResult struct {
	Strategy        string            `json:"strategy"`
	TotalTrades     int               `json:"total_trades"`
	Window1         WalkForwardWindow `json:"window1"`
	Window2         WalkForwardWindow `json:"window2"`
	PromotionStatus string            `json:"promotion_status"` // PROMOTED | REJECTED | INSUFFICIENT_DATA
	Reasoning       string            `json:"reasoning"`
}

// Window status strings.
const (
	WindowPass             = "PASS"
	WindowFail             = "FAIL"
	WindowInsufficient     = "INSUFFICIENT_DATA"
	PromotionPromoted      = "PROMOTED"
	PromotionRejected      = "REJECTED"
	PromotionInsufficient  = "INSUFFICIENT_DATA"
)

// toValidatorResults adapts ledger trades into the validator's minimal
// per-trade input, so window Sharpe/WinRate are computed identically to live.
func toValidatorResults(trades []ledger.Trade) []validator.TradeResult {
	out := make([]validator.TradeResult, 0, len(trades))
	for _, t := range trades {
		out = append(out, validator.TradeResult{NetPnL: t.NetPnL, Win: WinOf(t)})
	}
	return out
}

// buildWindow computes one window's full metrics from a slice of trades.
// startTrade/endTrade are 1-based, inclusive, for display.
func buildWindow(trades []ledger.Trade, startTrade, endTrade int, startEquity float64) WalkForwardWindow {
	w := WalkForwardWindow{StartTrade: startTrade, EndTrade: endTrade, Trades: len(trades)}

	if len(trades) < validator.MinTradesPerWindow {
		w.Status = WindowInsufficient
		// still fill descriptive stats where possible
		if len(trades) > 0 {
			vs := validator.ComputeWindowStats(toValidatorResults(trades))
			w.Sharpe = vs.Sharpe
			w.WinRate = vs.WinRate
		}
		return w
	}

	// Sharpe + WinRate via the live validator (authoritative PASS rule).
	vs := validator.ComputeWindowStats(toValidatorResults(trades))
	w.Sharpe = vs.Sharpe
	w.WinRate = vs.WinRate

	// Descriptive metrics (not part of the PASS rule).
	w.ProfitFactor = ProfitFactor(trades)
	w.AvgWinSize, w.AvgLossSize = AvgWinLoss(trades)
	pnls := make([]float64, len(trades))
	for i, t := range trades {
		pnls[i] = t.NetPnL
	}
	w.MaxDrawdown = MaxDrawdownFromPnls(pnls, startEquity)

	// PASS rule: identical to validator.WindowStats.Passes().
	if vs.Passes() {
		w.Status = WindowPass
	} else {
		w.Status = WindowFail
	}
	return w
}

// EvaluateWalkForward runs the live engine's 2-window promotion logic over
// a strategy's full backtest trade history (PART 3):
//
//   - < 30 trades in window 1            -> INSUFFICIENT_DATA
//   - window 1 fails                     -> REJECTED (no 2-window confirmation)
//   - window 1 passes, < 30 in window 2  -> INSUFFICIENT_DATA (awaiting confirmation)
//   - window 1 passes, window 2 fails    -> REJECTED (fast-demotion analog)
//   - window 1 passes, window 2 passes   -> PROMOTED
//
// These mirror validator.StrategyTrack's PROBATION→PENDING→ACTIVE machine.
func EvaluateWalkForward(strategyName string, trades []ledger.Trade, startEquity float64) WalkForwardResult {
	res := WalkForwardResult{Strategy: strategyName, TotalTrades: len(trades)}

	n := validator.MinTradesPerWindow

	// Window 1: trades 1..30.
	var w1Trades []ledger.Trade
	if len(trades) >= n {
		w1Trades = trades[:n]
	} else {
		w1Trades = trades
	}
	res.Window1 = buildWindow(w1Trades, 1, n, startEquity)

	if res.Window1.Status == WindowInsufficient {
		res.PromotionStatus = PromotionInsufficient
		res.Reasoning = fmt.Sprintf("only %d trades in backtest; need %d for window 1", len(trades), n)
		return res
	}

	if res.Window1.Status == WindowFail {
		res.PromotionStatus = PromotionRejected
		res.Reasoning = "Window 1 failed: " + windowFailReason(res.Window1) +
			"; does not qualify for 2-window confirmation"
		// Window 2 left zero-valued (not evaluated, window 1 already disqualified).
		res.Window2.Status = WindowInsufficient
		return res
	}

	// Window 2: trades 31..60.
	if len(trades) < 2*n {
		res.Window2 = buildWindow(nil, n+1, 2*n, startEquity)
		res.Window2.Status = WindowInsufficient
		res.PromotionStatus = PromotionInsufficient
		res.Reasoning = fmt.Sprintf(
			"Window 1 PASSED but only %d trades total; need %d for the confirmation window",
			len(trades), 2*n)
		return res
	}
	w2Trades := trades[n : 2*n]
	// Window 2 drawdown should start from equity at the end of window 1.
	w1EndEquity := startEquity
	for _, t := range w1Trades {
		w1EndEquity += t.NetPnL
	}
	res.Window2 = buildWindow(w2Trades, n+1, 2*n, w1EndEquity)

	switch res.Window2.Status {
	case WindowPass:
		res.PromotionStatus = PromotionPromoted
		res.Reasoning = "Both windows passed (Sharpe ≥ 0.60, WinRate ≥ 0.48): eligible for live paper trading"
	default: // FAIL
		res.PromotionStatus = PromotionRejected
		res.Reasoning = "Window 1 passed but Window 2 failed: " + windowFailReason(res.Window2) +
			" (fast-demotion: flip to conservative)"
	}
	return res
}

func windowFailReason(w WalkForwardWindow) string {
	reasons := ""
	if w.Sharpe < validator.PromotionMinSharpe {
		reasons += fmt.Sprintf("Sharpe %.2f < %.2f", w.Sharpe, validator.PromotionMinSharpe)
	}
	if w.WinRate < validator.PromotionMinWinRate {
		if reasons != "" {
			reasons += ", "
		}
		reasons += fmt.Sprintf("WinRate %.0f%% < %.0f%%", w.WinRate*100, validator.PromotionMinWinRate*100)
	}
	if reasons == "" {
		reasons = "below promotion thresholds"
	}
	return reasons
}

// sharpeStr renders a Sharpe that might be NaN.
func sharpeStr(s float64) string {
	if math.IsNaN(s) {
		return "NaN"
	}
	return fmt.Sprintf("%.2f", s)
}

// ─────────────────────────────────────────────────────────────────────────────
// Multi-year rolling walk-forward (IS=180 days, OOS=60 days, slide=30 days)
// ─────────────────────────────────────────────────────────────────────────────

// RollingWindow is one IS+OOS slice in the rolling walk-forward.
type RollingWindow struct {
	WindowIndex  int               `json:"window_index"`
	ISStart      string            `json:"is_start"`
	ISEnd        string            `json:"is_end"`
	OOSStart     string            `json:"oos_start"`
	OOSEnd       string            `json:"oos_end"`
	ISResult     WalkForwardWindow `json:"is_result"`
	OOSResult    WalkForwardWindow `json:"oos_result"`
	Promoted     bool              `json:"promoted"`
}

// RollingWalkForwardResult extends the 2-window result with rolling windows
// and a stability score for multi-year runs.
type RollingWalkForwardResult struct {
	WalkForwardResult
	RollingWindows  []RollingWindow `json:"rolling_windows,omitempty"`
	StabilityScore  float64         `json:"stability_score"`   // fraction of windows promoted
	StabilityStatus string          `json:"stability_status"`  // STABLE | UNSTABLE
}

// EvaluateRollingWalkForward runs IS=180 days, OOS=60 days, slide=30 days
// over a strategy's full trade history, tagged by exit time. Only applicable
// for backtests spanning ≥ 6 months of trading. Falls back to the standard
// 2-window result for shorter histories.
func EvaluateRollingWalkForward(strategyName string, trades []ledger.Trade, startEquity float64) RollingWalkForwardResult {
	base := EvaluateWalkForward(strategyName, trades, startEquity)
	res := RollingWalkForwardResult{WalkForwardResult: base}

	if len(trades) == 0 {
		res.StabilityStatus = "UNSTABLE"
		return res
	}

	// Check span: if < 180 trading days equivalent, skip rolling analysis.
	first := trades[0].ExitAt
	last := trades[len(trades)-1].ExitAt
	spanDays := int(last.Sub(first).Hours() / 24)
	if spanDays < 180 {
		res.StabilityScore = 0
		res.StabilityStatus = "UNSTABLE"
		return res
	}

	const isDays = 180
	const oosDays = 60
	const slideDays = 30

	var windows []RollingWindow
	windowIdx := 0

	for isStart := first; ; isStart = isStart.AddDate(0, 0, slideDays) {
		isEnd := isStart.AddDate(0, 0, isDays)
		oosStart := isEnd
		oosEnd := oosStart.AddDate(0, 0, oosDays)

		if oosEnd.After(last) {
			break
		}

		isTrades := filterTradesByRange(trades, isStart, isEnd)
		oosTrades := filterTradesByRange(trades, oosStart, oosEnd)

		isResult := buildWindow(isTrades, 1, len(isTrades), startEquity)
		isResult.StartTrade = 0 // use date-based window, override trade count display
		oosResult := buildWindow(oosTrades, 1, len(oosTrades), startEquity)

		promoted := isResult.Status == WindowPass && oosResult.Status == WindowPass

		windows = append(windows, RollingWindow{
			WindowIndex: windowIdx,
			ISStart:     isStart.UTC().Format("2006-01-02"),
			ISEnd:       isEnd.UTC().Format("2006-01-02"),
			OOSStart:    oosStart.UTC().Format("2006-01-02"),
			OOSEnd:      oosEnd.UTC().Format("2006-01-02"),
			ISResult:    isResult,
			OOSResult:   oosResult,
			Promoted:    promoted,
		})
		windowIdx++
	}

	res.RollingWindows = windows

	if len(windows) == 0 {
		res.StabilityScore = 0
		res.StabilityStatus = "UNSTABLE"
		return res
	}

	var promotedCount int
	for _, w := range windows {
		if w.Promoted {
			promotedCount++
		}
	}
	res.StabilityScore = float64(promotedCount) / float64(len(windows))
	if res.StabilityScore >= 0.60 {
		res.StabilityStatus = "STABLE"
	} else {
		res.StabilityStatus = "UNSTABLE"
	}
	return res
}

func filterTradesByRange(trades []ledger.Trade, from, to time.Time) []ledger.Trade {
	var out []ledger.Trade
	for _, t := range trades {
		if !t.ExitAt.Before(from) && t.ExitAt.Before(to) {
			out = append(out, t)
		}
	}
	return out
}
