package backtest

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/ledger"
)

// GenerateAll writes every report artifact (PART 4) into outDir.
func GenerateAll(res BacktestResults, outDir string) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	writers := []func(BacktestResults, string) error{
		writeSummaryJSON,
		writeSummaryMD,
		writeEquityCurveCSV,
		writeEquityCurvePNG,
		writeTradesCSV,
		writeLeaderboardJSON,
		writeDailyPnLCSV,
		writeWalkForwardJSON,
		writeRegimeAnalysisCSV,
		// Extended multi-year reports.
		writeMonthlyReturnsJSON,
		writeYearlySummaryJSON,
		writeRegimePerformanceJSON,
		writeCorrelationMatrixJSON,
		writeDrawdownAnalysisJSON,
	}
	for _, w := range writers {
		if err := w(res, outDir); err != nil {
			return err
		}
	}
	return nil
}

// ── Leaderboard / per-strategy aggregation ──────────────────────────────────

// LeaderboardEntry ranks one strategy (PART 4). Sharpe/ProfitFactor are
// JSON-safe (any): NaN serializes as null and +Inf as the string "inf",
// since encoding/json rejects raw NaN/Inf.
type LeaderboardEntry struct {
	Strategy        string  `json:"strategy"`
	TotalTrades     int     `json:"total_trades"`
	WinRate         float64 `json:"win_rate"`
	Sharpe          any     `json:"sharpe_per_trade"`
	MaxDrawdownPct  float64 `json:"max_drawdown_pct"`
	ProfitFactor    any     `json:"profit_factor"`
	NetPnLINR       float64 `json:"net_pnl_inr"`
	PromotionStatus string  `json:"promotion_status"`

	sortSharpe float64 // raw value for ranking (NaN sinks to bottom)
}

// jsonFloat makes a float JSON-safe: NaN -> nil (null), +Inf -> "inf",
// -Inf -> "-inf", otherwise the float itself.
func jsonFloat(f float64) any {
	switch {
	case math.IsNaN(f):
		return nil
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	default:
		return f
	}
}

func tradesByStrategy(res BacktestResults) map[string][]ledger.Trade {
	m := map[string][]ledger.Trade{}
	for _, t := range res.Trades {
		m[t.Strategy] = append(m[t.Strategy], t)
	}
	return m
}

// perTradeSharpe mirrors validator.ComputeWindowStats' Sharpe (mean/stddev of
// per-trade PnL) so the leaderboard's Sharpe matches the promotion metric.
func perTradeSharpe(trades []ledger.Trade) float64 {
	n := len(trades)
	if n < 2 {
		return math.NaN()
	}
	var sum, sumSq float64
	for _, t := range trades {
		sum += t.NetPnL
		sumSq += t.NetPnL * t.NetPnL
	}
	mean := sum / float64(n)
	variance := sumSq/float64(n) - mean*mean
	if variance <= 0 {
		return math.NaN()
	}
	return mean / math.Sqrt(variance)
}

func buildLeaderboard(res BacktestResults) []LeaderboardEntry {
	promo := map[string]string{}
	for _, wf := range res.WalkForward {
		promo[wf.Strategy] = wf.PromotionStatus
	}
	byStrat := tradesByStrategy(res)
	entries := make([]LeaderboardEntry, 0, len(byStrat))
	for strat, trades := range byStrat {
		pnls := make([]float64, len(trades))
		var net float64
		for i, t := range trades {
			pnls[i] = t.NetPnL
			net += t.NetPnL
		}
		sharpe := perTradeSharpe(trades)
		entries = append(entries, LeaderboardEntry{
			Strategy: strat, TotalTrades: len(trades), WinRate: WinRate(trades),
			Sharpe: jsonFloat(sharpe), MaxDrawdownPct: MaxDrawdownFromPnls(pnls, res.CapitalINR) * 100,
			ProfitFactor: jsonFloat(ProfitFactor(trades)), NetPnLINR: net, PromotionStatus: promo[strat],
			sortSharpe: sharpe,
		})
	}
	sort.SliceStable(entries, func(i, j int) bool {
		si, sj := entries[i].sortSharpe, entries[j].sortSharpe
		// NaN sinks to the bottom.
		if math.IsNaN(si) && math.IsNaN(sj) {
			return entries[i].WinRate > entries[j].WinRate
		}
		if math.IsNaN(si) {
			return false
		}
		if math.IsNaN(sj) {
			return true
		}
		if si != sj {
			return si > sj
		}
		return entries[i].WinRate > entries[j].WinRate
	})
	return entries
}

// ── summary.json ────────────────────────────────────────────────────────────

func writeSummaryJSON(res BacktestResults, outDir string) error {
	var promoted, rejected, insufficient []string
	for _, wf := range res.WalkForward {
		switch wf.PromotionStatus {
		case PromotionPromoted:
			promoted = append(promoted, wf.Strategy)
		case PromotionRejected:
			rejected = append(rejected, wf.Strategy)
		default:
			insufficient = append(insufficient, wf.Strategy)
		}
	}

	dailyReturns := make([]float64, 0, len(res.Daily))
	for _, d := range res.Daily {
		dailyReturns = append(dailyReturns, d.DailyReturnPct/100)
	}
	eqSeries := make([]float64, 0, len(res.Equity))
	for _, p := range res.Equity {
		eqSeries = append(eqSeries, p.EquityINR)
	}
	endEquity := res.CapitalINR
	if len(eqSeries) > 0 {
		endEquity = eqSeries[len(eqSeries)-1]
	}
	days := res.To.Sub(res.From).Hours() / 24
	if days < 1 {
		days = 1
	}

	summary := map[string]any{
		"backtest_from_ist":     res.From.In(calendar.IST).Format("2006-01-02"),
		"backtest_to_ist":       res.To.In(calendar.IST).Format("2006-01-02"),
		"data_source":           res.DataSource,
		"capital_inr":           res.CapitalINR,
		"ending_equity_inr":     endEquity,
		"net_pnl_inr":           endEquity - res.CapitalINR,
		"instruments":           res.Instruments,
		"total_trades":          len(res.Trades),
		"portfolio_sharpe_annualized": roundNaN(AnnualizedSharpe(dailyReturns, TradingDaysPerYear)),
		"portfolio_return_annualized": roundNaN(AnnualizedReturnFromEquity(res.CapitalINR, endEquity, days)),
		"portfolio_max_drawdown_pct":  roundNaN(MaxDrawdownFromEquity(eqSeries) * 100),
		"strategies_promoted":         promoted,
		"strategies_rejected":         rejected,
		"strategies_insufficient":     insufficient,
		"promoted_count":              len(promoted),
		"rejected_count":              len(rejected),
		"insufficient_count":          len(insufficient),
		"kill_events":                 len(res.KillEvents),
		"data_warnings":               res.DataWarnings,
		"disclaimer": "Walk-forward Sharpe/WinRate use the live validator thresholds " +
			"(0.60 / 0.48). Results on the Synthetic data source are for harness " +
			"validation only — not tradable signal quality.",
	}
	return writeJSON(filepath.Join(outDir, "summary.json"), summary)
}

func roundNaN(f float64) any {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return nil
	}
	return f
}

// ── summary.md ──────────────────────────────────────────────────────────────

func writeSummaryMD(res BacktestResults, outDir string) error {
	f, err := os.Create(filepath.Join(outDir, "summary.md"))
	if err != nil {
		return err
	}
	defer f.Close()

	fmt.Fprintf(f, "# Backtest Summary\n\n")
	fmt.Fprintf(f, "- **Period (IST):** %s → %s\n", res.From.In(calendar.IST).Format("2006-01-02"), res.To.In(calendar.IST).Format("2006-01-02"))
	fmt.Fprintf(f, "- **Data source:** %s\n", res.DataSource)
	fmt.Fprintf(f, "- **Capital:** ₹%.0f\n", res.CapitalINR)
	fmt.Fprintf(f, "- **Instruments:** %v\n", res.Instruments)
	fmt.Fprintf(f, "- **Total trades:** %d\n", len(res.Trades))
	fmt.Fprintf(f, "- **Kill events:** %d\n\n", len(res.KillEvents))

	fmt.Fprintf(f, "## Walk-forward promotion (live rules: Sharpe ≥ 0.60, WinRate ≥ 0.48, two 30-trade windows)\n\n")
	for _, wf := range res.WalkForward {
		fmt.Fprintf(f, "### %s\n", wf.Strategy)
		fmt.Fprintf(f, "Total trades: %d\n\n", wf.TotalTrades)
		writeWindowMD(f, "Window 1 (trades 1–30)", wf.Window1)
		writeWindowMD(f, "Window 2 (trades 31–60)", wf.Window2)
		mark := "✗"
		if wf.PromotionStatus == PromotionPromoted {
			mark = "✓"
		}
		fmt.Fprintf(f, "**Promotion: %s %s** — %s\n\n---\n\n", mark, wf.PromotionStatus, wf.Reasoning)
	}
	return nil
}

func writeWindowMD(f *os.File, title string, w WalkForwardWindow) {
	if w.Status == WindowInsufficient && w.Trades == 0 {
		fmt.Fprintf(f, "- %s: _not evaluated_ (%s)\n", title, w.Status)
		return
	}
	fmt.Fprintf(f, "- %s: Sharpe %s  WinRate %.0f%%  MaxDD %.1f%%  PF %s → **%s**\n",
		title, sharpeStr(w.Sharpe), w.WinRate*100, w.MaxDrawdown*100, pfStr(w.ProfitFactor), w.Status)
}

func pfStr(pf float64) string {
	if math.IsInf(pf, 1) {
		return "∞"
	}
	return fmt.Sprintf("%.2fx", pf)
}

// ── equity_curve.csv ────────────────────────────────────────────────────────

func writeEquityCurveCSV(res BacktestResults, outDir string) error {
	return writeCSV(filepath.Join(outDir, "equity_curve.csv"),
		[]string{"timestamp_ist", "equity_inr", "cumulative_pnl_inr", "period_return_pct"},
		func(w *csv.Writer) error {
			for _, p := range res.Equity {
				rec := []string{
					p.TimeUTC.In(calendar.IST).Format("2006-01-02 15:04:05"),
					strconv.FormatFloat(p.EquityINR, 'f', 2, 64),
					strconv.FormatFloat(p.CumPnLINR, 'f', 2, 64),
					strconv.FormatFloat(p.DailyReturnPct, 'f', 4, 64),
				}
				if err := w.Write(rec); err != nil {
					return err
				}
			}
			return nil
		})
}

// ── equity_curve.png (pure-stdlib renderer, no external charting dep) ───────

func writeEquityCurvePNG(res BacktestResults, outDir string) error {
	const width, height = 1000, 400
	const padL, padR, padT, padB = 70, 20, 20, 40
	img := image.NewRGBA(image.Rect(0, 0, width, height))
	// white background
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			img.Set(x, y, color.White)
		}
	}
	if len(res.Equity) < 2 {
		return savePNG(filepath.Join(outDir, "equity_curve.png"), img)
	}

	minE, maxE := res.Equity[0].EquityINR, res.Equity[0].EquityINR
	for _, p := range res.Equity {
		if p.EquityINR < minE {
			minE = p.EquityINR
		}
		if p.EquityINR > maxE {
			maxE = p.EquityINR
		}
	}
	if maxE == minE {
		maxE = minE + 1
	}

	plotW := width - padL - padR
	plotH := height - padT - padB
	axis := color.RGBA{120, 120, 120, 255}
	line := color.RGBA{0, 90, 200, 255}

	// axes
	for x := padL; x < width-padR; x++ {
		img.Set(x, height-padB, axis)
	}
	for y := padT; y < height-padB; y++ {
		img.Set(padL, y, axis)
	}
	// baseline at starting capital
	capY := padT + int(float64(plotH)*(1-(res.CapitalINR-minE)/(maxE-minE)))
	if capY >= padT && capY < height-padB {
		for x := padL; x < width-padR; x += 4 {
			img.Set(x, capY, color.RGBA{200, 160, 160, 255})
		}
	}

	n := len(res.Equity)
	prevX, prevY := -1, -1
	for i, p := range res.Equity {
		x := padL + int(float64(i)/float64(n-1)*float64(plotW))
		y := padT + int(float64(plotH)*(1-(p.EquityINR-minE)/(maxE-minE)))
		if prevX >= 0 {
			drawLine(img, prevX, prevY, x, y, line)
		}
		prevX, prevY = x, y
	}
	return savePNG(filepath.Join(outDir, "equity_curve.png"), img)
}

// drawLine is a minimal Bresenham line for the equity curve.
func drawLine(img *image.RGBA, x0, y0, x1, y1 int, c color.Color) {
	dx := abs(x1 - x0)
	dy := -abs(y1 - y0)
	sx := 1
	if x0 > x1 {
		sx = -1
	}
	sy := 1
	if y0 > y1 {
		sy = -1
	}
	err := dx + dy
	for {
		img.Set(x0, y0, c)
		if x0 == x1 && y0 == y1 {
			break
		}
		e2 := 2 * err
		if e2 >= dy {
			err += dy
			x0 += sx
		}
		if e2 <= dx {
			err += dx
			y0 += sy
		}
	}
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func savePNG(path string, img image.Image) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return png.Encode(f, img)
}

// ── trades.csv ──────────────────────────────────────────────────────────────

func writeTradesCSV(res BacktestResults, outDir string) error {
	return writeCSV(filepath.Join(outDir, "trades.csv"),
		[]string{"entry_time_ist", "exit_time_ist", "underlying", "instrument", "strategy",
			"direction", "entry_price", "exit_price", "quantity", "gross_pnl_inr",
			"fees_inr", "net_pnl_inr", "holding_min", "exit_reason", "status"},
		func(w *csv.Writer) error {
			for _, t := range res.Trades {
				holding := t.ExitAt.Sub(t.EntryAt).Minutes()
				status := "LOSS"
				if t.NetPnL > 0 {
					status = "WIN"
				}
				fees := t.EntryCostINR + t.ExitCostINR
				rec := []string{
					t.EntryAt.In(calendar.IST).Format("2006-01-02 15:04"),
					t.ExitAt.In(calendar.IST).Format("2006-01-02 15:04"),
					t.Underlying, t.Instrument, t.Strategy, t.Direction,
					strconv.FormatFloat(t.EntryPrice, 'f', 2, 64),
					strconv.FormatFloat(t.ExitPrice, 'f', 2, 64),
					strconv.FormatInt(t.Quantity, 10),
					strconv.FormatFloat(t.GrossPnL, 'f', 2, 64),
					strconv.FormatFloat(fees, 'f', 2, 64),
					strconv.FormatFloat(t.NetPnL, 'f', 2, 64),
					strconv.FormatFloat(holding, 'f', 1, 64),
					t.ExitReason, status,
				}
				if err := w.Write(rec); err != nil {
					return err
				}
			}
			return nil
		})
}

// ── leaderboard.json ────────────────────────────────────────────────────────

func writeLeaderboardJSON(res BacktestResults, outDir string) error {
	return writeJSON(filepath.Join(outDir, "leaderboard.json"), buildLeaderboard(res))
}

// ── daily_pnl.csv ───────────────────────────────────────────────────────────

func writeDailyPnLCSV(res BacktestResults, outDir string) error {
	return writeCSV(filepath.Join(outDir, "daily_pnl.csv"),
		[]string{"date_ist", "daily_pnl_inr", "daily_return_pct", "max_intraday_dd_pct",
			"winning_trades", "losing_trades"},
		func(w *csv.Writer) error {
			for _, d := range res.Daily {
				rec := []string{
					d.DateIST,
					strconv.FormatFloat(d.DailyPnLINR, 'f', 2, 64),
					strconv.FormatFloat(d.DailyReturnPct, 'f', 4, 64),
					strconv.FormatFloat(d.MaxIntradayDDPct, 'f', 4, 64),
					strconv.Itoa(d.WinningTrades),
					strconv.Itoa(d.LosingTrades),
				}
				if err := w.Write(rec); err != nil {
					return err
				}
			}
			return nil
		})
}

// ── walkforward_details.json ────────────────────────────────────────────────

func writeWalkForwardJSON(res BacktestResults, outDir string) error {
	return writeJSON(filepath.Join(outDir, "walkforward_details.json"), res.WalkForward)
}

// ── regime_analysis.csv ─────────────────────────────────────────────────────

func writeRegimeAnalysisCSV(res BacktestResults, outDir string) error {
	return writeCSV(filepath.Join(outDir, "regime_analysis.csv"),
		[]string{"timestamp_ist", "underlying", "regime_class", "position_size_mult",
			"strategies_active", "cumulative_realized_pnl_inr"},
		func(w *csv.Writer) error {
			for _, r := range res.Regimes {
				rec := []string{
					r.TimeUTC.In(calendar.IST).Format("2006-01-02 15:04"),
					r.Underlying, r.Regime,
					strconv.FormatFloat(r.PositionSizeMult, 'f', 2, 64),
					strconv.Itoa(r.ActiveStrategies),
					strconv.FormatFloat(r.CumRealizedINR, 'f', 2, 64),
				}
				if err := w.Write(rec); err != nil {
					return err
				}
			}
			return nil
		})
}

// GenerateCSVOnly writes only the CSV artifacts (equity curve, trades, daily PnL).
func GenerateCSVOnly(res BacktestResults, outDir string) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	for _, w := range []func(BacktestResults, string) error{
		writeEquityCurveCSV,
		writeTradesCSV,
		writeDailyPnLCSV,
		writeRegimeAnalysisCSV,
	} {
		if err := w(res, outDir); err != nil {
			return err
		}
	}
	return nil
}

// ── small IO helpers ────────────────────────────────────────────────────────

func writeJSON(path string, v any) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func writeCSV(path string, header []string, body func(*csv.Writer) error) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	if err := w.Write(header); err != nil {
		return err
	}
	if err := body(w); err != nil {
		return err
	}
	w.Flush()
	return w.Error()
}

// ─────────────────────────────────────────────────────────────────────────────
// Extended multi-year JSON reports
// ─────────────────────────────────────────────────────────────────────────────

func writeMonthlyReturnsJSON(res BacktestResults, outDir string) error {
	type monthRow struct {
		Strategy string             `json:"strategy"`
		Monthly  map[string]float64 `json:"monthly"` // "YYYY-MM" -> net PnL
	}
	keys := make([]string, 0, len(res.MonthlyReturnsMap))
	for k := range res.MonthlyReturnsMap {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	rows := make([]monthRow, 0, len(keys))
	for _, k := range keys {
		monthly := make(map[string]float64)
		for yr, months := range res.MonthlyReturnsMap[k] {
			for mo, pnl := range months {
				key := fmt.Sprintf("%04d-%02d", yr, mo)
				monthly[key] += pnl
			}
		}
		rows = append(rows, monthRow{Strategy: k, Monthly: monthly})
	}
	return writeJSON(filepath.Join(outDir, "monthly_returns.json"), rows)
}

func writeYearlySummaryJSON(res BacktestResults, outDir string) error {
	return writeJSON(filepath.Join(outDir, "yearly_summary.json"), res.YearlyBreakdowns)
}

func writeRegimePerformanceJSON(res BacktestResults, outDir string) error {
	return writeJSON(filepath.Join(outDir, "regime_performance.json"), res.RegimePerformances)
}

func writeCorrelationMatrixJSON(res BacktestResults, outDir string) error {
	type matrixOut struct {
		Strategies []string    `json:"strategies"`
		Matrix     [][]float64 `json:"matrix"`
	}
	strats := make([]string, 0, len(res.CorrelationMatrix))
	for k := range res.CorrelationMatrix {
		strats = append(strats, k)
	}
	sort.Strings(strats)
	n := len(strats)
	mat := make([][]float64, n)
	for i, si := range strats {
		mat[i] = make([]float64, n)
		for j, sj := range strats {
			if inner, ok := res.CorrelationMatrix[si]; ok {
				mat[i][j] = inner[sj]
			} else {
				mat[i][j] = math.NaN()
			}
		}
	}
	return writeJSON(filepath.Join(outDir, "correlation_matrix.json"), matrixOut{Strategies: strats, Matrix: mat})
}

func writeDrawdownAnalysisJSON(res BacktestResults, outDir string) error {
	return writeJSON(filepath.Join(outDir, "drawdown_analysis.json"), res.DrawdownPeriods)
}

// TimestampedDir returns engine/backtest_results/{YYYY-MM-DD_HHMMSS_UTC}.
func TimestampedDir(base string, now time.Time) string {
	return filepath.Join(base, now.UTC().Format("2006-01-02_150405")+"_UTC")
}
