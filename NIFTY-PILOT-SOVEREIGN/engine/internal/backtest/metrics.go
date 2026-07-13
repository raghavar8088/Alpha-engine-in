// Package backtest implements the read-only walk-forward backtest
// harness for NIFTY-PILOT SOVEREIGN. It replays historical candles
// through the EXACT same strategy / regime / risk / execution code the
// live engine uses (no forks), and emits performance reports.
//
// This file holds the pure metric calculators (PART 9 of the spec).
// Every function here is deterministic and side-effect free so the
// metrics are unit-testable against known-good sequences.
package backtest

import (
	"math"

	"niftypilot/internal/ledger"
)

// RiskFreeRate is the annual risk-free rate assumption for the Sharpe
// ratio (≈6% Indian government securities, per PART 9).
const RiskFreeRate = 0.06

// TradingDaysPerYear is the annualization factor for Sharpe.
const TradingDaysPerYear = 252.0

// WinOf reports whether a closed trade is a WIN. Per PART 9 a trade is a
// WIN only if NetPnL > 0; breakeven (==0) counts as a loss (conservatism).
func WinOf(t ledger.Trade) bool { return t.NetPnL > 0 }

// WinRate = wins / total. Returns 0 for an empty set.
func WinRate(trades []ledger.Trade) float64 {
	if len(trades) == 0 {
		return 0
	}
	wins := 0
	for _, t := range trades {
		if WinOf(t) {
			wins++
		}
	}
	return float64(wins) / float64(len(trades))
}

// ProfitFactor = sum(wins) / |sum(losses)|. Returns +Inf if there are
// winning trades but zero losses, and 0 if there are no winning trades.
func ProfitFactor(trades []ledger.Trade) float64 {
	var gross, grossLoss float64
	for _, t := range trades {
		if t.NetPnL > 0 {
			gross += t.NetPnL
		} else {
			grossLoss += -t.NetPnL
		}
	}
	if grossLoss == 0 {
		if gross == 0 {
			return 0
		}
		return math.Inf(1)
	}
	return gross / grossLoss
}

// Expectancy is the expected INR value per trade:
//
//	(winRate * avgWin) - ((1-winRate) * avgLoss)
func Expectancy(trades []ledger.Trade) float64 {
	if len(trades) == 0 {
		return 0
	}
	var sumWin, sumLoss float64
	var wins, losses int
	for _, t := range trades {
		if t.NetPnL > 0 {
			sumWin += t.NetPnL
			wins++
		} else {
			sumLoss += -t.NetPnL
			losses++
		}
	}
	wr := float64(wins) / float64(len(trades))
	avgWin := 0.0
	if wins > 0 {
		avgWin = sumWin / float64(wins)
	}
	avgLoss := 0.0
	if losses > 0 {
		avgLoss = sumLoss / float64(losses)
	}
	return wr*avgWin - (1-wr)*avgLoss
}

// AvgWinLoss returns the average winning and average (absolute) losing
// trade size in INR.
func AvgWinLoss(trades []ledger.Trade) (avgWin, avgLoss float64) {
	var sumWin, sumLoss float64
	var wins, losses int
	for _, t := range trades {
		if t.NetPnL > 0 {
			sumWin += t.NetPnL
			wins++
		} else {
			sumLoss += -t.NetPnL
			losses++
		}
	}
	if wins > 0 {
		avgWin = sumWin / float64(wins)
	}
	if losses > 0 {
		avgLoss = sumLoss / float64(losses)
	}
	return avgWin, avgLoss
}

// MaxDrawdownFromEquity returns the maximum peak-to-trough drawdown of an
// equity series as a negative fraction (e.g. -0.05 = -5%). Computed on
// the supplied equity points (one per day or per snapshot), per PART 9.
func MaxDrawdownFromEquity(equity []float64) float64 {
	if len(equity) == 0 {
		return 0
	}
	peak := equity[0]
	maxDD := 0.0
	for _, e := range equity {
		if e > peak {
			peak = e
		}
		if peak > 0 {
			dd := e/peak - 1
			if dd < maxDD {
				maxDD = dd
			}
		}
	}
	return maxDD
}

// MaxDrawdownFromPnls builds a cumulative-PnL equity curve from a per-trade
// PnL sequence (starting at startEquity) and returns its max drawdown.
func MaxDrawdownFromPnls(pnls []float64, startEquity float64) float64 {
	if len(pnls) == 0 {
		return 0
	}
	eq := make([]float64, 0, len(pnls)+1)
	running := startEquity
	eq = append(eq, running)
	for _, p := range pnls {
		running += p
		eq = append(eq, running)
	}
	return MaxDrawdownFromEquity(eq)
}

// AnnualizedSharpe computes the annualized Sharpe ratio from a series of
// per-period (daily) returns, per PART 9. periodsPerYear is normally 252.
// Returns NaN when volatility is zero (insufficient variance to score).
func AnnualizedSharpe(dailyReturns []float64, periodsPerYear float64) float64 {
	if len(dailyReturns) < 2 {
		return math.NaN()
	}
	mean := 0.0
	for _, r := range dailyReturns {
		mean += r
	}
	mean /= float64(len(dailyReturns))

	var variance float64
	for _, r := range dailyReturns {
		d := r - mean
		variance += d * d
	}
	variance /= float64(len(dailyReturns) - 1) // sample stddev
	stddev := math.Sqrt(variance)
	if stddev == 0 {
		return math.NaN()
	}

	annReturn := mean * periodsPerYear
	annVol := stddev * math.Sqrt(periodsPerYear)
	return (annReturn - RiskFreeRate) / annVol
}

// AnnualizedReturnFromEquity computes the CAGR-style annualized return
// from start/end equity over a number of calendar days, per PART 9.
func AnnualizedReturnFromEquity(startEquity, endEquity float64, daysInBacktest float64) float64 {
	if startEquity <= 0 || daysInBacktest <= 0 {
		return 0
	}
	ratio := endEquity / startEquity
	if ratio <= 0 {
		return -1
	}
	return math.Pow(ratio, TradingDaysPerYear/daysInBacktest) - 1
}

// RecoveryFactor = total profit / |max drawdown in absolute INR|. Measures
// how efficiently a strategy recovers from drawdowns. Returns +Inf when
// there is profit but no drawdown.
func RecoveryFactor(totalProfitINR, maxDrawdownINR float64) float64 {
	absDD := math.Abs(maxDrawdownINR)
	if absDD == 0 {
		if totalProfitINR == 0 {
			return 0
		}
		return math.Inf(1)
	}
	return totalProfitINR / absDD
}

// IndiaRiskFreeRate is the annualized risk-free rate for Sortino (6.5% India G-Sec).
const IndiaRiskFreeRate = 0.065

// CalmarRatio = Annualized Return / |Max Drawdown fraction|.
// Returns NaN when maxDD is zero (no drawdown = undefined Calmar).
func CalmarRatio(annualizedReturn, maxDrawdownFraction float64) float64 {
	absDD := math.Abs(maxDrawdownFraction)
	if absDD == 0 {
		return math.NaN()
	}
	return annualizedReturn / absDD
}

// SortinoRatio computes Sortino using daily returns, annualizing with periodsPerYear.
// Downside deviation = std dev of returns below the risk-free hurdle.
// RFR should be daily (annualRFR / periodsPerYear).
func SortinoRatio(dailyReturns []float64, periodsPerYear float64) float64 {
	if len(dailyReturns) < 2 {
		return math.NaN()
	}
	dailyRFR := IndiaRiskFreeRate / periodsPerYear

	var mean float64
	for _, r := range dailyReturns {
		mean += r
	}
	mean /= float64(len(dailyReturns))

	var downsideSumSq float64
	var downsideCount int
	for _, r := range dailyReturns {
		excess := r - dailyRFR
		if excess < 0 {
			downsideSumSq += excess * excess
			downsideCount++
		}
	}
	if downsideCount == 0 {
		return math.Inf(1) // no downside days
	}
	downsideDev := math.Sqrt(downsideSumSq/float64(len(dailyReturns))) * math.Sqrt(periodsPerYear)
	if downsideDev == 0 {
		return math.NaN()
	}
	annReturn := mean*periodsPerYear - IndiaRiskFreeRate
	return annReturn / downsideDev
}

// OmegaRatio = Sum(positive returns above threshold) / |Sum(negative returns below threshold)|.
// threshold is typically 0 (or daily RFR).
func OmegaRatio(dailyReturns []float64, threshold float64) float64 {
	var pos, neg float64
	for _, r := range dailyReturns {
		excess := r - threshold
		if excess > 0 {
			pos += excess
		} else {
			neg += -excess
		}
	}
	if neg == 0 {
		if pos == 0 {
			return 1.0
		}
		return math.Inf(1)
	}
	return pos / neg
}

// UlcerIndex = RMS of the drawdown percentage series.
// A higher Ulcer Index means deeper and longer drawdowns.
func UlcerIndex(equity []float64) float64 {
	if len(equity) < 2 {
		return 0
	}
	peak := equity[0]
	var sumSq float64
	for _, e := range equity {
		if e > peak {
			peak = e
		}
		if peak > 0 {
			dd := (e - peak) / peak * 100 // in percent
			sumSq += dd * dd
		}
	}
	return math.Sqrt(sumSq / float64(len(equity)))
}

// YearlyBreakdown summarizes one calendar year's performance for a strategy.
type YearlyBreakdown struct {
	Year       int     `json:"year"`
	NetPnL     float64 `json:"net_pnl_inr"`
	Trades     int     `json:"trades"`
	WinRate    float64 `json:"win_rate"`
	MaxDD      float64 `json:"max_drawdown_pct"`
	BestMonth  string  `json:"best_month"`
	WorstMonth string  `json:"worst_month"`
}

// PerStrategyExtended holds additional per-strategy metrics beyond the leaderboard.
type PerStrategyExtended struct {
	Strategy          string
	MaxConsecWins     int
	MaxConsecLosses   int
	AvgHoldMinutes    float64
	BestMonthLabel    string
	BestMonthPnL      float64
	WorstMonthLabel   string
	WorstMonthPnL     float64
}

// ComputeExtendedMetrics derives per-strategy extended metrics from a trade slice.
func ComputeExtendedMetrics(strategyName string, trades []ledger.Trade) PerStrategyExtended {
	m := PerStrategyExtended{Strategy: strategyName}
	if len(trades) == 0 {
		return m
	}

	// Consecutive wins/losses.
	var curWin, curLoss int
	for _, t := range trades {
		if WinOf(t) {
			curWin++
			curLoss = 0
		} else {
			curLoss++
			curWin = 0
		}
		if curWin > m.MaxConsecWins {
			m.MaxConsecWins = curWin
		}
		if curLoss > m.MaxConsecLosses {
			m.MaxConsecLosses = curLoss
		}
	}

	// Average hold duration.
	var totalMins float64
	for _, t := range trades {
		totalMins += t.ExitAt.Sub(t.EntryAt).Minutes()
	}
	m.AvgHoldMinutes = totalMins / float64(len(trades))

	// Best/worst month by PnL.
	monthPnL := map[string]float64{}
	for _, t := range trades {
		key := t.ExitAt.UTC().Format("2006-01")
		monthPnL[key] += t.NetPnL
	}
	first := true
	for label, pnl := range monthPnL {
		if first {
			m.BestMonthLabel = label
			m.BestMonthPnL = pnl
			m.WorstMonthLabel = label
			m.WorstMonthPnL = pnl
			first = false
			continue
		}
		if pnl > m.BestMonthPnL {
			m.BestMonthPnL = pnl
			m.BestMonthLabel = label
		}
		if pnl < m.WorstMonthPnL {
			m.WorstMonthPnL = pnl
			m.WorstMonthLabel = label
		}
	}
	return m
}

// BuildYearlyBreakdowns groups a strategy's trades by calendar year and
// returns one YearlyBreakdown per year, sorted ascending.
func BuildYearlyBreakdowns(trades []ledger.Trade, startEquity float64) []YearlyBreakdown {
	byYear := map[int][]ledger.Trade{}
	for _, t := range trades {
		y := t.ExitAt.UTC().Year()
		byYear[y] = append(byYear[y], t)
	}
	var years []int
	for y := range byYear {
		years = append(years, y)
	}
	// Sort ascending.
	for i := 0; i < len(years); i++ {
		for j := i + 1; j < len(years); j++ {
			if years[j] < years[i] {
				years[i], years[j] = years[j], years[i]
			}
		}
	}
	result := make([]YearlyBreakdown, 0, len(years))
	runningEquity := startEquity
	for _, y := range years {
		yt := byYear[y]
		pnls := make([]float64, len(yt))
		var netPnL float64
		for i, t := range yt {
			pnls[i] = t.NetPnL
			netPnL += t.NetPnL
		}
		maxDD := MaxDrawdownFromPnls(pnls, runningEquity) * 100
		ext := ComputeExtendedMetrics("", yt)
		result = append(result, YearlyBreakdown{
			Year: y, NetPnL: netPnL, Trades: len(yt),
			WinRate: WinRate(yt), MaxDD: maxDD,
			BestMonth: ext.BestMonthLabel, WorstMonth: ext.WorstMonthLabel,
		})
		runningEquity += netPnL
	}
	return result
}

// MonthlyReturns builds a year→month→pnl map from a trade slice.
func MonthlyReturns(trades []ledger.Trade) map[int]map[int]float64 {
	result := map[int]map[int]float64{}
	for _, t := range trades {
		y := t.ExitAt.UTC().Year()
		mo := int(t.ExitAt.UTC().Month())
		if result[y] == nil {
			result[y] = map[int]float64{}
		}
		result[y][mo] += t.NetPnL
	}
	return result
}

// DailyPnLSeries builds a date→pnl map (UTC date) from a trade slice.
// Used for correlation matrix and Sharpe on daily series.
func DailyPnLSeries(trades []ledger.Trade) map[string]float64 {
	result := map[string]float64{}
	for _, t := range trades {
		key := t.ExitAt.UTC().Format("2006-01-02")
		result[key] += t.NetPnL
	}
	return result
}

// DrawdownPeriod describes one peak-to-trough drawdown episode.
type DrawdownPeriod struct {
	StartDate    string  `json:"start_date"`
	EndDate      string  `json:"end_date"`
	MaxDDPct     float64 `json:"max_dd_pct"`
	RecoveryDate string  `json:"recovery_date,omitempty"`
	RecoveryDays int     `json:"recovery_days"`
}

// TopDrawdownPeriods identifies the N deepest drawdown periods from an equity series.
func TopDrawdownPeriods(equity []EquityPoint, n int) []DrawdownPeriod {
	if len(equity) < 2 {
		return nil
	}
	type dd struct {
		start, end int
		maxDD      float64
		peak       float64
	}
	var periods []dd
	peak := equity[0].EquityINR
	peakIdx := 0
	inDD := false
	var cur dd

	for i, p := range equity {
		if p.EquityINR >= peak {
			if inDD {
				// End of drawdown.
				cur.end = i
				periods = append(periods, cur)
				inDD = false
			}
			peak = p.EquityINR
			peakIdx = i
		} else {
			ddPct := (p.EquityINR - peak) / peak * 100
			if !inDD {
				inDD = true
				cur = dd{start: peakIdx, peak: peak}
			}
			if ddPct < cur.maxDD {
				cur.maxDD = ddPct
				cur.end = i
			}
		}
	}
	if inDD {
		cur.end = len(equity) - 1
		periods = append(periods, cur)
	}

	// Sort by magnitude (most negative first).
	for i := 0; i < len(periods); i++ {
		for j := i + 1; j < len(periods); j++ {
			if periods[j].maxDD < periods[i].maxDD {
				periods[i], periods[j] = periods[j], periods[i]
			}
		}
	}

	if n > len(periods) {
		n = len(periods)
	}
	result := make([]DrawdownPeriod, 0, n)
	for _, p := range periods[:n] {
		startDate := equity[p.start].TimeUTC.Format("2006-01-02")
		endDate := equity[p.end].TimeUTC.Format("2006-01-02")
		// Find recovery: first equity point after end where equity >= peak.
		recoveryDate := ""
		recoveryDays := 0
		for i := p.end + 1; i < len(equity); i++ {
			if equity[i].EquityINR >= p.peak {
				recoveryDate = equity[i].TimeUTC.Format("2006-01-02")
				recoveryDays = int(equity[i].TimeUTC.Sub(equity[p.end].TimeUTC).Hours() / 24)
				break
			}
		}
		result = append(result, DrawdownPeriod{
			StartDate: startDate, EndDate: endDate,
			MaxDDPct: p.maxDD, RecoveryDate: recoveryDate, RecoveryDays: recoveryDays,
		})
	}
	return result
}

// CorrelationMatrix computes pairwise Pearson correlation of daily PnL series.
// strategies is a list of strategy names; dailySeries maps strategyName→date→pnl.
// Returns a map[strategyA][strategyB]correlation.
func CorrelationMatrix(strategies []string, dailySeries map[string]map[string]float64) map[string]map[string]float64 {
	// Collect union of all dates.
	dateSet := map[string]bool{}
	for _, ds := range dailySeries {
		for d := range ds {
			dateSet[d] = true
		}
	}
	dates := make([]string, 0, len(dateSet))
	for d := range dateSet {
		dates = append(dates, d)
	}
	// Sort dates.
	for i := 0; i < len(dates); i++ {
		for j := i + 1; j < len(dates); j++ {
			if dates[j] < dates[i] {
				dates[i], dates[j] = dates[j], dates[i]
			}
		}
	}

	// Build per-strategy aligned return vectors.
	vecs := map[string][]float64{}
	for _, s := range strategies {
		v := make([]float64, len(dates))
		for i, d := range dates {
			v[i] = dailySeries[s][d] // 0 if absent
		}
		vecs[s] = v
	}

	result := map[string]map[string]float64{}
	for _, a := range strategies {
		result[a] = map[string]float64{}
		for _, b := range strategies {
			result[a][b] = pearsonCorr(vecs[a], vecs[b])
		}
	}
	return result
}

func pearsonCorr(a, b []float64) float64 {
	n := len(a)
	if n == 0 || n != len(b) {
		return 0
	}
	var ma, mb float64
	for i := 0; i < n; i++ {
		ma += a[i]
		mb += b[i]
	}
	ma /= float64(n)
	mb /= float64(n)
	var num, da2, db2 float64
	for i := 0; i < n; i++ {
		da := a[i] - ma
		db := b[i] - mb
		num += da * db
		da2 += da * da
		db2 += db * db
	}
	denom := math.Sqrt(da2 * db2)
	if denom == 0 {
		return 0
	}
	return num / denom
}

// RegimePerformance holds per-regime stats for a single strategy.
type RegimePerformance struct {
	RegimeName string  `json:"regime"`
	Trades     int     `json:"trades"`
	WinRate    float64 `json:"win_rate"`
	NetPnL     float64 `json:"net_pnl_inr"`
	AvgPnL     float64 `json:"avg_pnl_inr"`
}
