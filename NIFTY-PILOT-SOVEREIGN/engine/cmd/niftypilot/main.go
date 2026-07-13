// Command niftypilot boots the NIFTY-PILOT SOVEREIGN paper trading
// engine: market data warmup, regime classification, strategy
// evaluation, risk gating, paper execution, and observability.
// PAPER (MOCK) TRADING ONLY — no live order placement is wired in this build.
//
// Market Detection: The engine automatically detects Indian market hours
// (09:15-15:30 IST, NSE trading days) and starts/stops mock trading accordingly.
// No manual intervention required.
//
// Strategy Validation: All strategies must pass walk-forward validation
// (WinRate >= 40%, ProfitFactor > 1.0, positive Expectancy, Sharpe >= 0.60)
// before they are approved for mock trading.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"sort"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"

	"niftypilot/internal/alerting"
	"niftypilot/internal/calendar"
	"niftypilot/internal/execution"
	"niftypilot/internal/ledger"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/metrics"
	"niftypilot/internal/regime"
	"niftypilot/internal/risk"
	"niftypilot/internal/strategy"
	"niftypilot/internal/validator"
)

const PaperCapitalINR = 1_00_00_000.0 // Rs 1 Crore

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8090"
	}

	cal := calendar.NewService()
	events := regime.DefaultEventCalendar()
	classifier := regime.NewClassifier(cal, events)

	bundle := marketdata.NewNiftyDataBundle()
	feed := marketdata.NewSyntheticFeed()

	l := ledger.New()
	execEngine := execution.NewEngine(l)
	riskEngine := risk.NewEngine(risk.DefaultConfig(), cal, PaperCapitalINR)

	tg := alerting.NewTelegramAlerter(os.Getenv("TELEGRAM_BOT_TOKEN"), os.Getenv("TELEGRAM_CHAT_ID"))
	watchdog := alerting.NewStalenessWatchdog(tg)

	tracks := map[string]*validator.StrategyTrack{}
	for _, s := range strategy.AllStrategies() {
		tracks[s.Name()] = validator.NewStrategyTrack(s.Name())
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	warmup(ctx, feed, bundle)
	go tickIngestLoop(ctx, feed, bundle)
	go optionChainPollLoop(ctx, feed, bundle)
	go evaluationLoop(ctx, cal, classifier, bundle, riskEngine, execEngine, l, tracks)
	go positionMonitorLoop(ctx, cal, bundle, riskEngine, execEngine, l, tracks)
	go stalenessWatchLoop(ctx, cal, bundle, watchdog)
	go selfPingLoop(ctx, port)

	mux := http.NewServeMux()

	// Core engine endpoints
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/health", healthHandler(cal, riskEngine, bundle))
	mux.HandleFunc("/api/equity", equityHandler(riskEngine, l))
	mux.HandleFunc("/api/positions", positionsHandler(l))
	mux.HandleFunc("/api/trades", tradesHandler(l))
	mux.HandleFunc("/api/strategies", strategiesHandler(tracks))
	mux.HandleFunc("/api/market", marketHandler(bundle))

	// Mock Trading endpoints
	mux.HandleFunc("/api/mock-trading/status", mockTradingStatusHandler(cal, riskEngine))
	mux.HandleFunc("/api/mock-trading/portfolio", mockTradingPortfolioHandler(riskEngine, l))
	mux.HandleFunc("/api/mock-trading/analytics", mockTradingAnalyticsHandler(l))
	mux.HandleFunc("/api/mock-trading/leaderboard", mockTradingLeaderboardHandler(l, tracks))
	mux.HandleFunc("/api/strategies/validation", strategiesValidationHandler(tracks))

	log.Printf("niftypilot engine listening on :%s — auto market detection active (09:15–15:30 IST)", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

// ─── Boot loops ───────────────────────────────────────────────────────────────

func warmup(ctx context.Context, feed marketdata.Feed, bundle *marketdata.NiftyDataBundle) {
	now := time.Now()
	for _, underlying := range []string{"NIFTY", "BANKNIFTY"} {
		for _, tf := range []string{"1m", "5m", "15m", "1h"} {
			candles, err := feed.HistoricalCandles(ctx, underlying, tf, now.Add(-30*24*time.Hour), now)
			if err != nil {
				log.Printf("warmup: %s %s historical candles unavailable: %v", underlying, tf, err)
				continue
			}
			bundle.SeedCandles(underlying, tf, candles)
		}
	}
	log.Println("warmup complete")
}

func tickIngestLoop(ctx context.Context, feed marketdata.Feed, bundle *marketdata.NiftyDataBundle) {
	for _, underlying := range []string{"NIFTY", "BANKNIFTY", "INDIAVIX"} {
		ch, err := feed.SubscribeSpot(ctx, underlying)
		if err != nil {
			log.Printf("tick ingest: %s subscribe failed: %v", underlying, err)
			continue
		}
		go func(name string, ticks <-chan marketdata.Tick) {
			for {
				select {
				case <-ctx.Done():
					return
				case tick, ok := <-ticks:
					if !ok {
						return
					}
					if name == "INDIAVIX" {
						bundle.SetIndiaVIX(tick.LTP)
					} else {
						bundle.SetSpot(name, tick.LTP, tick.Time)
					}
				}
			}
		}(underlying, ch)
	}
}

func optionChainPollLoop(ctx context.Context, feed marketdata.Feed, bundle *marketdata.NiftyDataBundle) {
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()
	poll := func() {
		for _, underlying := range []string{"NIFTY", "BANKNIFTY"} {
			snap, err := feed.OptionChain(ctx, underlying)
			if err != nil {
				log.Printf("option chain poll: %s failed: %v", underlying, err)
				continue
			}
			bundle.SetOptionChain(underlying, snap)
		}
	}
	poll()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			poll()
		}
	}
}

// evaluationLoop is the core mock trading engine. It automatically detects
// market open (09:15 IST) and starts evaluating strategies, and stops at
// market close (15:30 IST). No manual intervention required.
func evaluationLoop(ctx context.Context, cal *calendar.Service, classifier *regime.Classifier, bundle *marketdata.NiftyDataBundle, riskEngine *risk.Engine, execEngine *execution.Engine, l *ledger.Ledger, tracks map[string]*validator.StrategyTrack) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	strategies := strategy.AllStrategies()

	wasOpen := false
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			isOpen := cal.IsMarketOpen(now)

			// Log market state transitions
			if isOpen && !wasOpen {
				log.Printf("[MOCK TRADING] Market OPENED at %s — auto-starting mock trading engine",
					now.In(calendar.IST).Format("15:04:05 IST"))
			} else if !isOpen && wasOpen {
				log.Printf("[MOCK TRADING] Market CLOSED at %s — stopping new entries, monitoring open positions",
					now.In(calendar.IST).Format("15:04:05 IST"))
			}
			wasOpen = isOpen

			if !isOpen {
				continue
			}

			for _, underlying := range []string{"NIFTY", "BANKNIFTY"} {
				rc := classifier.Classify(underlying, bundle, now)
				metrics.RegimeState.WithLabelValues(underlying, string(rc.Regime)).Set(1)
				metrics.IndiaVIXLevel.Set(rc.VIXLevel)

				// Build set of strategies that already have an open position for this underlying
				openByStrategy := map[string]bool{}
				for _, t := range l.OpenTrades() {
					if t.Underlying == underlying {
						openByStrategy[t.Strategy] = true
					}
				}

				mctx := strategy.MarketContext{Now: now, Underlying: underlying, Bundle: bundle, Regime: rc}
				for _, s := range strategies {
					metrics.SignalsEvaluated.WithLabelValues(s.Name(), underlying).Inc()
					track := tracks[s.Name()]
					if track != nil && !track.IsTradeable() {
						metrics.SignalsRejected.WithLabelValues(s.Name(), "demoted").Inc()
						continue
					}
					// Skip if this strategy already has an open position on this underlying
					if openByStrategy[s.Name()] {
						continue
					}
					sig, ok := s.Evaluate(mctx)
					if !ok {
						continue
					}
					allowed, reason := riskEngine.CheckEntryAllowed(now, PaperCapitalINR+l.RealizedPnL(), string(sig.Direction))
					if !allowed {
						metrics.SignalsRejected.WithLabelValues(s.Name(), reason).Inc()
						continue
					}
					trade := execEngine.ExecuteEntry(sig, 1, 0)
					riskEngine.RegisterOpen(trade.Direction)
					metrics.SignalsExecuted.WithLabelValues(s.Name(), trade.Direction).Inc()
					openByStrategy[s.Name()] = true
				}
			}
			metrics.MarginUtilizationPct.Set(riskEngine.MarginBook().UtilizationPct())
			metrics.RealizedPnLINR.Set(l.RealizedPnL())
			if riskEngine.KillSwitch().IsActive() {
				metrics.KillSwitchActive.Set(1)
			} else {
				metrics.KillSwitchActive.Set(0)
			}
		}
	}
}

// positionMonitorLoop checks every 5 seconds whether any open position has hit
// its StopLoss or TakeProfit against the current spot price, and executes the
// exit leg. It also force-closes all open positions at market close (15:29 IST).
// On exit it calls riskEngine.RegisterClose and track.RecordTrade so the
// walk-forward validator receives results and directional caps decrement.
func positionMonitorLoop(ctx context.Context, cal *calendar.Service, bundle *marketdata.NiftyDataBundle, riskEngine *risk.Engine, execEngine *execution.Engine, l *ledger.Ledger, tracks map[string]*validator.StrategyTrack) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	closePosition := func(t ledger.Trade, exitPrice float64, reason string, now time.Time) {
		execEngine.ExecuteExit(t.ID, exitPrice, now, reason, 0)
		riskEngine.RegisterClose(t.Direction)
		closed, ok := l.Trade(t.ID)
		if !ok {
			return
		}
		if track, exists := tracks[t.Strategy]; exists {
			track.RecordTrade(validator.TradeResult{
				NetPnL: closed.NetPnL,
				Win:    closed.NetPnL > 0,
			})
		}
		log.Printf("[MONITOR] %s %s exit=%s price=%.2f pnl=%.2f", t.Strategy, t.ID, reason, exitPrice, closed.NetPnL)
	}

	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			open := l.OpenTrades()
			if len(open) == 0 {
				continue
			}

			// Force-close all positions at 15:29 IST (1 minute before official close)
			nowIST := now.In(calendar.IST)
			isForceClose := nowIST.Hour() == 15 && nowIST.Minute() >= 29

			for _, t := range open {
				spot := bundle.Spot(t.Underlying)
				if spot == 0 {
					continue
				}

				if isForceClose {
					closePosition(t, spot, "TIME", now)
					continue
				}

				// Only monitor during market hours
				if !cal.IsMarketOpen(now) {
					continue
				}

				switch t.Direction {
				case "LONG":
					if t.StopLoss > 0 && spot <= t.StopLoss {
						closePosition(t, t.StopLoss, "SL", now)
					} else if t.TakeProfit > 0 && spot >= t.TakeProfit {
						closePosition(t, t.TakeProfit, "TP", now)
					}
				case "SHORT":
					if t.StopLoss > 0 && spot >= t.StopLoss {
						closePosition(t, t.StopLoss, "SL", now)
					} else if t.TakeProfit > 0 && spot <= t.TakeProfit {
						closePosition(t, t.TakeProfit, "TP", now)
					}
				}
			}
		}
	}
}

func stalenessWatchLoop(ctx context.Context, cal *calendar.Service, bundle *marketdata.NiftyDataBundle, watchdog *alerting.StalenessWatchdog) {
	ticker := time.NewTicker(watchdog.CheckInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			if !cal.IsMarketOpen(now) {
				continue
			}
			for _, feedKey := range []string{"NIFTY", "BANKNIFTY", "NIFTY:chain", "BANKNIFTY:chain"} {
				staleness := bundle.StaleSince(feedKey, now)
				metrics.DataFeedStalenessSeconds.WithLabelValues(feedKey).Set(staleness.Seconds())
				watchdog.CheckOnce(ctx, feedKey, staleness)
			}
		}
	}
}

func selfPingLoop(ctx context.Context, port string) {
	ticker := time.NewTicker(2 * time.Minute)
	defer ticker.Stop()
	client := &http.Client{Timeout: 5 * time.Second}
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			resp, err := client.Get("http://127.0.0.1:" + port + "/health")
			if err != nil {
				log.Printf("self-ping failed: %v", err)
				continue
			}
			resp.Body.Close()
		}
	}
}

// ─── Core handlers ────────────────────────────────────────────────────────────

func healthHandler(cal *calendar.Service, riskEngine *risk.Engine, bundle *marketdata.NiftyDataBundle) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		now := time.Now()
		status := "OPEN"
		switch {
		case riskEngine.KillSwitch().IsActive():
			status = "KILL_SWITCH_ACTIVE"
		case cal.IsPreOpen(now):
			status = "PRE_OPEN"
		case !cal.IsMarketOpen(now):
			status = "CLOSED"
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"status":      status,
			"time_ist":    now.In(calendar.IST).Format(time.RFC3339),
			"trading_day": cal.IsTradingDay(now),
		})
	}
}

func equityHandler(riskEngine *risk.Engine, l *ledger.Ledger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"capital_inr":             PaperCapitalINR,
			"realized_pnl_inr":        l.RealizedPnL(),
			"equity_inr":              PaperCapitalINR + l.RealizedPnL(),
			"margin_used_inr":         riskEngine.MarginBook().UsedMarginINR,
			"margin_available_inr":    riskEngine.MarginBook().AvailableMarginINR(),
			"margin_utilization_pct":  riskEngine.MarginBook().UtilizationPct(),
		})
	}
}

func marketHandler(bundle *marketdata.NiftyDataBundle) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		chainN := bundle.OptionChain("NIFTY")
		chainBN := bundle.OptionChain("BANKNIFTY")
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"nifty_spot":         bundle.Spot("NIFTY"),
			"banknifty_spot":     bundle.Spot("BANKNIFTY"),
			"india_vix":          bundle.IndiaVIX(),
			"nifty_pcr":          chainN.PCR(),
			"nifty_max_pain":     chainN.MaxPain(),
			"banknifty_pcr":      chainBN.PCR(),
			"banknifty_max_pain": chainBN.MaxPain(),
		})
	}
}

func positionsHandler(l *ledger.Ledger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(l.OpenTrades())
	}
}

func tradesHandler(l *ledger.Ledger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(l.ClosedTrades())
	}
}

func strategiesHandler(tracks map[string]*validator.StrategyTrack) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		out := make([]map[string]any, 0, len(tracks))
		for name, t := range tracks {
			last, _ := t.LastWindow()
			out = append(out, map[string]any{
				"strategy":             name,
				"status":               t.Status,
				"last_window_sharpe":   last.Sharpe,
				"last_window_winrate":  last.WinRate,
			})
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(out)
	}
}

// ─── Mock Trading handlers ────────────────────────────────────────────────────

// mockTradingStatusHandler returns comprehensive mock trading engine status.
func mockTradingStatusHandler(cal *calendar.Service, riskEngine *risk.Engine) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		now := time.Now()
		nowIST := now.In(calendar.IST)

		isMarketOpen := cal.IsMarketOpen(now)
		isPreOpen := cal.IsPreOpen(now)
		isTradingDay := cal.IsTradingDay(now)
		killSwitchActive := riskEngine.KillSwitch().IsActive()

		engineStatus := "MOCK_TRADING_ACTIVE"
		if killSwitchActive {
			engineStatus = "KILL_SWITCH_ACTIVE"
		} else if !isMarketOpen {
			if isPreOpen {
				engineStatus = "PRE_OPEN_READY"
			} else {
				engineStatus = "MARKET_CLOSED"
			}
		}

		// Compute next market open time
		nextOpen := computeNextMarketOpen(cal, now)

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"engine_status":          engineStatus,
			"mock_trading_active":    isMarketOpen && !killSwitchActive,
			"market_open":            isMarketOpen,
			"pre_open":               isPreOpen,
			"trading_day":            isTradingDay,
			"kill_switch_active":     killSwitchActive,
			"time_ist":               nowIST.Format("15:04:05"),
			"date_ist":               nowIST.Format("2006-01-02"),
			"timestamp":              now.UTC().Format(time.RFC3339),
			"market_open_time":       "09:15 IST",
			"market_close_time":      "15:30 IST",
			"next_market_open":       nextOpen,
			"session_start":          sessionStartToday(nowIST),
			"session_end":            sessionEndToday(nowIST),
			"auto_detection_enabled": true,
		})
	}
}

func computeNextMarketOpen(cal *calendar.Service, now time.Time) string {
	for i := 0; i <= 7; i++ {
		candidate := now.Add(time.Duration(i) * 24 * time.Hour)
		candidateIST := candidate.In(calendar.IST)
		open := time.Date(candidateIST.Year(), candidateIST.Month(), candidateIST.Day(), 9, 15, 0, 0, calendar.IST)
		if open.After(now) && cal.IsTradingDay(open) {
			return open.Format(time.RFC3339)
		}
	}
	return ""
}

func sessionStartToday(nowIST time.Time) string {
	return time.Date(nowIST.Year(), nowIST.Month(), nowIST.Day(), 9, 15, 0, 0, calendar.IST).Format(time.RFC3339)
}

func sessionEndToday(nowIST time.Time) string {
	return time.Date(nowIST.Year(), nowIST.Month(), nowIST.Day(), 15, 30, 0, 0, calendar.IST).Format(time.RFC3339)
}

// mockTradingPortfolioHandler returns full portfolio snapshot with time-bucketed P&L.
func mockTradingPortfolioHandler(riskEngine *risk.Engine, l *ledger.Ledger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		now := time.Now().UTC()
		closedTrades := l.ClosedTrades()
		openTrades := l.OpenTrades()

		realizedPnL := l.RealizedPnL()
		capital := PaperCapitalINR
		equity := capital + realizedPnL

		// Unrealized PnL from open trades
		unrealizedPnL := 0.0
		for _, t := range openTrades {
			unrealizedPnL += t.GrossPnL
		}

		// Time-bucketed PnL
		dailyPnL := pnlSince(closedTrades, now.Add(-24*time.Hour))
		weeklyPnL := pnlSince(closedTrades, now.Add(-7*24*time.Hour))
		monthlyPnL := pnlSince(closedTrades, now.Add(-30*24*time.Hour))

		// Today's trades
		todayStart := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
		todayTrades := tradesAfter(closedTrades, todayStart)
		todayWins := 0
		for _, t := range todayTrades {
			if t.NetPnL > 0 {
				todayWins++
			}
		}

		marginBook := riskEngine.MarginBook()

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"capital_inr":             capital,
			"portfolio_value_inr":     equity + unrealizedPnL,
			"equity_inr":              equity,
			"realized_pnl_inr":        realizedPnL,
			"unrealized_pnl_inr":      unrealizedPnL,
			"total_pnl_inr":           realizedPnL + unrealizedPnL,
			"daily_pnl_inr":           dailyPnL,
			"weekly_pnl_inr":          weeklyPnL,
			"monthly_pnl_inr":         monthlyPnL,
			"margin_used_inr":         marginBook.UsedMarginINR,
			"margin_available_inr":    marginBook.AvailableMarginINR(),
			"margin_utilization_pct":  marginBook.UtilizationPct(),
			"open_positions":          len(openTrades),
			"total_closed_trades":     len(closedTrades),
			"today_trades":            len(todayTrades),
			"today_wins":              todayWins,
			"kill_switch_active":      riskEngine.KillSwitch().IsActive(),
		})
	}
}

// mockTradingAnalyticsHandler returns comprehensive performance analytics.
func mockTradingAnalyticsHandler(l *ledger.Ledger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		trades := l.ClosedTrades()
		analytics := computeAnalytics(trades)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(analytics)
	}
}

type Analytics struct {
	TotalTrades        int                      `json:"total_trades"`
	WinningTrades      int                      `json:"winning_trades"`
	LosingTrades       int                      `json:"losing_trades"`
	BreakevenTrades    int                      `json:"breakeven_trades"`
	WinRate            float64                  `json:"win_rate"`
	LossRate           float64                  `json:"loss_rate"`
	NetPnLINR          float64                  `json:"net_pnl_inr"`
	GrossPnLINR        float64                  `json:"gross_pnl_inr"`
	TotalFeesINR       float64                  `json:"total_fees_inr"`
	ProfitFactor       float64                  `json:"profit_factor"`
	Expectancy         float64                  `json:"expectancy_inr"`
	AvgWinINR          float64                  `json:"avg_win_inr"`
	AvgLossINR         float64                  `json:"avg_loss_inr"`
	RiskRewardRatio    float64                  `json:"risk_reward_ratio"`
	MaxDrawdownPct     float64                  `json:"max_drawdown_pct"`
	MaxDrawdownINR     float64                  `json:"max_drawdown_inr"`
	SharpeRatio        float64                  `json:"sharpe_ratio"`
	SortinoRatio       float64                  `json:"sortino_ratio"`
	CAGR               float64                  `json:"cagr"`
	RecoveryFactor     float64                  `json:"recovery_factor"`
	MaxConsecWins      int                      `json:"max_consecutive_wins"`
	MaxConsecLosses    int                      `json:"max_consecutive_losses"`
	AvgHoldMinutes     float64                  `json:"avg_hold_minutes"`
	LargestWinINR      float64                  `json:"largest_win_inr"`
	LargestLossINR     float64                  `json:"largest_loss_inr"`
	EquityCurve        []EquityPoint            `json:"equity_curve"`
	DailyPnL           []DailyPnLPoint          `json:"daily_pnl"`
	MonthlyReturns     []MonthlyReturnPoint     `json:"monthly_returns"`
	PnLDistribution    []PnLBucket              `json:"pnl_distribution"`
}

type EquityPoint struct {
	Date      string  `json:"date"`
	EquityINR float64 `json:"equity_inr"`
	DrawdownPct float64 `json:"drawdown_pct"`
}

type DailyPnLPoint struct {
	Date   string  `json:"date"`
	PnLINR float64 `json:"pnl_inr"`
	Trades int     `json:"trades"`
	WinRate float64 `json:"win_rate"`
}

type MonthlyReturnPoint struct {
	Month      string  `json:"month"`  // "2025-01"
	PnLINR     float64 `json:"pnl_inr"`
	ReturnPct  float64 `json:"return_pct"`
	Trades     int     `json:"trades"`
	WinRate    float64 `json:"win_rate"`
}

type PnLBucket struct {
	Label string `json:"label"`
	Count int    `json:"count"`
}

func computeAnalytics(trades []ledger.Trade) Analytics {
	a := Analytics{}
	if len(trades) == 0 {
		return a
	}

	a.TotalTrades = len(trades)
	var grossWin, grossLoss float64
	var sumWin, sumLoss float64
	var winCount, lossCount int
	var curWin, curLoss int
	var totalHoldMins float64

	for _, t := range trades {
		a.GrossPnLINR += t.GrossPnL
		a.NetPnLINR += t.NetPnL
		a.TotalFeesINR += t.EntryCostINR + t.ExitCostINR
		totalHoldMins += t.ExitAt.Sub(t.EntryAt).Minutes()

		if t.NetPnL > 0 {
			winCount++
			grossWin += t.NetPnL
			sumWin += t.NetPnL
			if t.NetPnL > a.LargestWinINR {
				a.LargestWinINR = t.NetPnL
			}
			curWin++
			curLoss = 0
		} else if t.NetPnL < 0 {
			lossCount++
			grossLoss += -t.NetPnL
			sumLoss += -t.NetPnL
			if -t.NetPnL > a.LargestLossINR {
				a.LargestLossINR = -t.NetPnL
			}
			curLoss++
			curWin = 0
		} else {
			a.BreakevenTrades++
			curWin = 0
			curLoss = 0
		}
		if curWin > a.MaxConsecWins {
			a.MaxConsecWins = curWin
		}
		if curLoss > a.MaxConsecLosses {
			a.MaxConsecLosses = curLoss
		}
	}

	a.WinningTrades = winCount
	a.LosingTrades = lossCount
	a.WinRate = float64(winCount) / float64(a.TotalTrades)
	a.LossRate = float64(lossCount) / float64(a.TotalTrades)
	a.AvgHoldMinutes = totalHoldMins / float64(a.TotalTrades)

	if grossLoss > 0 {
		a.ProfitFactor = grossWin / grossLoss
	} else if grossWin > 0 {
		a.ProfitFactor = 999
	}

	avgWin, avgLoss := 0.0, 0.0
	if winCount > 0 {
		avgWin = sumWin / float64(winCount)
	}
	if lossCount > 0 {
		avgLoss = sumLoss / float64(lossCount)
	}
	a.AvgWinINR = avgWin
	a.AvgLossINR = avgLoss
	a.Expectancy = a.WinRate*avgWin - (1-a.WinRate)*avgLoss

	if avgLoss > 0 {
		a.RiskRewardRatio = avgWin / avgLoss
	}

	// Equity curve + drawdown
	a.EquityCurve, a.MaxDrawdownPct, a.MaxDrawdownINR = buildEquityCurve(trades)

	// Recovery factor
	if a.MaxDrawdownINR > 0 {
		a.RecoveryFactor = math.Max(0, a.NetPnLINR) / a.MaxDrawdownINR
	}

	// Sharpe & Sortino from daily returns
	dailyReturns := buildDailyReturns(trades)
	if len(dailyReturns) >= 2 {
		a.SharpeRatio = annualizedSharpe(dailyReturns)
		a.SortinoRatio = annualizedSortino(dailyReturns)
	}

	// CAGR
	if len(trades) >= 2 {
		first := trades[0].EntryAt
		last := trades[len(trades)-1].ExitAt
		days := last.Sub(first).Hours() / 24
		if days > 0 {
			endEq := PaperCapitalINR + a.NetPnLINR
			ratio := endEq / PaperCapitalINR
			if ratio > 0 {
				a.CAGR = math.Pow(ratio, 365/days) - 1
			}
		}
	}

	// Daily P&L series
	a.DailyPnL = buildDailyPnLSeries(trades)

	// Monthly returns
	a.MonthlyReturns = buildMonthlyReturns(trades)

	// PnL distribution buckets
	a.PnLDistribution = buildPnLDistribution(trades)

	return a
}

func buildEquityCurve(trades []ledger.Trade) ([]EquityPoint, float64, float64) {
	if len(trades) == 0 {
		return nil, 0, 0
	}

	// Group by date
	byDate := map[string]float64{}
	dateOrder := []string{}
	seen := map[string]bool{}
	for _, t := range trades {
		d := t.ExitAt.UTC().Format("2006-01-02")
		byDate[d] += t.NetPnL
		if !seen[d] {
			dateOrder = append(dateOrder, d)
			seen[d] = true
		}
	}
	sort.Strings(dateOrder)

	equity := PaperCapitalINR
	peak := equity
	maxDDPct := 0.0
	maxDDINR := 0.0

	points := make([]EquityPoint, 0, len(dateOrder))
	for _, d := range dateOrder {
		equity += byDate[d]
		if equity > peak {
			peak = equity
		}
		ddPct := 0.0
		if peak > 0 {
			ddPct = (equity - peak) / peak * 100
		}
		if ddPct < maxDDPct {
			maxDDPct = ddPct
			maxDDINR = peak - equity
		}
		points = append(points, EquityPoint{
			Date:        d,
			EquityINR:   equity,
			DrawdownPct: ddPct,
		})
	}
	return points, maxDDPct, maxDDINR
}

func buildDailyReturns(trades []ledger.Trade) []float64 {
	byDate := map[string]float64{}
	for _, t := range trades {
		d := t.ExitAt.UTC().Format("2006-01-02")
		byDate[d] += t.NetPnL
	}
	returns := make([]float64, 0, len(byDate))
	for _, pnl := range byDate {
		returns = append(returns, pnl/PaperCapitalINR)
	}
	return returns
}

func annualizedSharpe(dailyReturns []float64) float64 {
	const rfr = 0.06 / 252
	n := float64(len(dailyReturns))
	mean := 0.0
	for _, r := range dailyReturns {
		mean += r
	}
	mean /= n
	variance := 0.0
	for _, r := range dailyReturns {
		d := r - mean
		variance += d * d
	}
	variance /= (n - 1)
	stddev := math.Sqrt(variance)
	if stddev == 0 {
		return math.NaN()
	}
	return (mean*252 - 0.06) / (stddev * math.Sqrt(252))
}

func annualizedSortino(dailyReturns []float64) float64 {
	const annualRFR = 0.065
	const periods = 252.0
	dailyRFR := annualRFR / periods
	mean := 0.0
	for _, r := range dailyReturns {
		mean += r
	}
	mean /= float64(len(dailyReturns))

	downsideSumSq := 0.0
	for _, r := range dailyReturns {
		excess := r - dailyRFR
		if excess < 0 {
			downsideSumSq += excess * excess
		}
	}
	downsideDev := math.Sqrt(downsideSumSq/float64(len(dailyReturns))) * math.Sqrt(periods)
	if downsideDev == 0 {
		return math.Inf(1)
	}
	return (mean*periods - annualRFR) / downsideDev
}

func buildDailyPnLSeries(trades []ledger.Trade) []DailyPnLPoint {
	type dayData struct {
		pnl    float64
		trades int
		wins   int
	}
	byDate := map[string]*dayData{}
	dateOrder := []string{}
	seen := map[string]bool{}
	for _, t := range trades {
		d := t.ExitAt.UTC().Format("2006-01-02")
		if byDate[d] == nil {
			byDate[d] = &dayData{}
		}
		byDate[d].pnl += t.NetPnL
		byDate[d].trades++
		if t.NetPnL > 0 {
			byDate[d].wins++
		}
		if !seen[d] {
			dateOrder = append(dateOrder, d)
			seen[d] = true
		}
	}
	sort.Strings(dateOrder)
	result := make([]DailyPnLPoint, 0, len(dateOrder))
	for _, d := range dateOrder {
		dd := byDate[d]
		wr := 0.0
		if dd.trades > 0 {
			wr = float64(dd.wins) / float64(dd.trades)
		}
		result = append(result, DailyPnLPoint{
			Date:    d,
			PnLINR:  dd.pnl,
			Trades:  dd.trades,
			WinRate: wr,
		})
	}
	return result
}

func buildMonthlyReturns(trades []ledger.Trade) []MonthlyReturnPoint {
	type monthData struct {
		pnl    float64
		trades int
		wins   int
	}
	byMonth := map[string]*monthData{}
	monthOrder := []string{}
	seen := map[string]bool{}
	for _, t := range trades {
		m := t.ExitAt.UTC().Format("2006-01")
		if byMonth[m] == nil {
			byMonth[m] = &monthData{}
		}
		byMonth[m].pnl += t.NetPnL
		byMonth[m].trades++
		if t.NetPnL > 0 {
			byMonth[m].wins++
		}
		if !seen[m] {
			monthOrder = append(monthOrder, m)
			seen[m] = true
		}
	}
	sort.Strings(monthOrder)
	result := make([]MonthlyReturnPoint, 0, len(monthOrder))
	equity := PaperCapitalINR
	for _, m := range monthOrder {
		md := byMonth[m]
		wr := 0.0
		if md.trades > 0 {
			wr = float64(md.wins) / float64(md.trades)
		}
		returnPct := 0.0
		if equity > 0 {
			returnPct = md.pnl / equity * 100
		}
		equity += md.pnl
		result = append(result, MonthlyReturnPoint{
			Month:     m,
			PnLINR:    md.pnl,
			ReturnPct: returnPct,
			Trades:    md.trades,
			WinRate:   wr,
		})
	}
	return result
}

func buildPnLDistribution(trades []ledger.Trade) []PnLBucket {
	buckets := map[string]int{
		"<-5000": 0, "-5000:-2000": 0, "-2000:-500": 0, "-500:0": 0,
		"0:500": 0, "500:2000": 0, "2000:5000": 0, ">5000": 0,
	}
	order := []string{"<-5000", "-5000:-2000", "-2000:-500", "-500:0", "0:500", "500:2000", "2000:5000", ">5000"}
	for _, t := range trades {
		p := t.NetPnL
		switch {
		case p < -5000:
			buckets["<-5000"]++
		case p < -2000:
			buckets["-5000:-2000"]++
		case p < -500:
			buckets["-2000:-500"]++
		case p < 0:
			buckets["-500:0"]++
		case p < 500:
			buckets["0:500"]++
		case p < 2000:
			buckets["500:2000"]++
		case p < 5000:
			buckets["2000:5000"]++
		default:
			buckets[">5000"]++
		}
	}
	labels := []string{"< -₹5K", "-₹5K to -₹2K", "-₹2K to -₹500", "-₹500 to ₹0", "₹0 to ₹500", "₹500 to ₹2K", "₹2K to ₹5K", "> ₹5K"}
	result := make([]PnLBucket, len(order))
	for i, k := range order {
		result[i] = PnLBucket{Label: labels[i], Count: buckets[k]}
	}
	return result
}

// StrategyLeaderboardEntry is a ranked entry in the strategy leaderboard.
type StrategyLeaderboardEntry struct {
	Rank                int                          `json:"rank"`
	Name                string                       `json:"name"`
	Status              string                       `json:"status"`
	MockTradingApproved bool                         `json:"mock_trading_approved"`
	ValidationReason    string                       `json:"validation_reason,omitempty"`
	TotalTrades         int                          `json:"total_trades"`
	WinningTrades       int                          `json:"winning_trades"`
	WinRate             float64                      `json:"win_rate"`
	NetPnLINR           float64                      `json:"net_pnl_inr"`
	ProfitFactor        float64                      `json:"profit_factor"`
	Sharpe              float64                      `json:"sharpe"`
	MaxDrawdownPct      float64                      `json:"max_drawdown_pct"`
	RecoveryFactor      float64                      `json:"recovery_factor"`
	Expectancy          float64                      `json:"expectancy_inr"`
	OverallScore        float64                      `json:"overall_score"`
	WindowsCompleted    int                          `json:"windows_completed"`
	CurrentWindowProg   int                          `json:"current_window_progress"`
	LastValidation      *validator.ValidationResult  `json:"last_validation,omitempty"`
}

// mockTradingLeaderboardHandler returns all strategies ranked by composite score.
func mockTradingLeaderboardHandler(l *ledger.Ledger, tracks map[string]*validator.StrategyTrack) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		closedTrades := l.ClosedTrades()

		// Group trades by strategy
		tradesByStrategy := map[string][]ledger.Trade{}
		for _, t := range closedTrades {
			tradesByStrategy[t.Strategy] = append(tradesByStrategy[t.Strategy], t)
		}

		entries := make([]StrategyLeaderboardEntry, 0, len(tracks))
		for name, track := range tracks {
			stratTrades := tradesByStrategy[name]
			entry := buildLeaderboardEntry(name, track, stratTrades)
			entries = append(entries, entry)
		}

		// Sort by overall score descending
		sort.Slice(entries, func(i, j int) bool {
			return entries[i].OverallScore > entries[j].OverallScore
		})
		for i := range entries {
			entries[i].Rank = i + 1
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(entries)
	}
}

func buildLeaderboardEntry(name string, track *validator.StrategyTrack, trades []ledger.Trade) StrategyLeaderboardEntry {
	entry := StrategyLeaderboardEntry{
		Name:               name,
		Status:             string(track.Status),
		MockTradingApproved: track.IsMockTradingApproved(),
		WindowsCompleted:   len(track.AllWindows()),
		CurrentWindowProg:  track.CurrentWindowProgress(),
	}

	// Rejection reasons from last validation
	if rejections := track.LastRejectionReasons(); len(rejections) > 0 {
		entry.ValidationReason = formatRejectionReason(rejections)
	}

	if len(trades) == 0 {
		return entry
	}

	entry.TotalTrades = len(trades)
	var grossWin, grossLoss float64
	var wins int
	var sumWin, sumLoss float64
	var winCount, lossCount int
	pnls := make([]float64, len(trades))

	for i, t := range trades {
		pnls[i] = t.NetPnL
		if t.NetPnL > 0 {
			wins++
			grossWin += t.NetPnL
			sumWin += t.NetPnL
			winCount++
		} else if t.NetPnL < 0 {
			grossLoss += -t.NetPnL
			sumLoss += -t.NetPnL
			lossCount++
		}
	}

	entry.WinningTrades = wins
	entry.WinRate = float64(wins) / float64(len(trades))

	for _, t := range trades {
		entry.NetPnLINR += t.NetPnL
	}

	if grossLoss > 0 {
		entry.ProfitFactor = grossWin / grossLoss
	} else if grossWin > 0 {
		entry.ProfitFactor = 999
	}

	avgWin, avgLoss := 0.0, 0.0
	if winCount > 0 {
		avgWin = sumWin / float64(winCount)
	}
	if lossCount > 0 {
		avgLoss = sumLoss / float64(lossCount)
	}
	entry.Expectancy = entry.WinRate*avgWin - (1-entry.WinRate)*avgLoss

	// Max drawdown
	_, maxDDPct, maxDDINR := buildEquityCurve(trades)
	entry.MaxDrawdownPct = maxDDPct

	// Recovery factor
	if maxDDINR > 0 {
		entry.RecoveryFactor = math.Max(0, entry.NetPnLINR) / maxDDINR
	}

	// Sharpe
	dailyReturns := buildDailyReturns(trades)
	if len(dailyReturns) >= 2 {
		entry.Sharpe = annualizedSharpe(dailyReturns)
		if math.IsNaN(entry.Sharpe) {
			entry.Sharpe = 0
		}
	}

	// Composite score (0–100 scale)
	entry.OverallScore = computeOverallScore(entry)

	// Run last window validation
	lastWin, hasWin := track.LastWindow()
	if hasWin {
		vr := validator.ValidateWindow(lastWin)
		entry.LastValidation = &vr
	}

	return entry
}

// computeOverallScore produces a 0–100 composite score from key metrics.
// Weights: WinRate 30%, ProfitFactor 25%, Sharpe 20%, MaxDrawdown 15%, RecoveryFactor 10%.
func computeOverallScore(e StrategyLeaderboardEntry) float64 {
	if e.TotalTrades == 0 {
		return 0
	}

	// Normalize each metric to 0–1
	wrScore := math.Min(1.0, math.Max(0, e.WinRate/0.70))           // 70%+ WR = 1.0
	pfScore := math.Min(1.0, math.Max(0, (e.ProfitFactor-1)/3))     // PF 4+ = 1.0
	sharpeScore := math.Min(1.0, math.Max(0, e.Sharpe/3))           // Sharpe 3+ = 1.0
	ddScore := math.Min(1.0, math.Max(0, 1+e.MaxDrawdownPct/25))    // MaxDD 25%+ = 0.0
	rfScore := math.Min(1.0, math.Max(0, e.RecoveryFactor/5))       // RF 5+ = 1.0

	score := wrScore*0.30 + pfScore*0.25 + sharpeScore*0.20 + ddScore*0.15 + rfScore*0.10
	return math.Round(score*1000) / 10 // 0–100 with 1 decimal
}

func formatRejectionReason(failures []validator.ValidationFailure) string {
	if len(failures) == 0 {
		return ""
	}
	msg := ""
	for i, f := range failures {
		if i > 0 {
			msg += "; "
		}
		switch f.Rule {
		case "WinRate":
			msg += fmt.Sprintf("WinRate %.1f%% < required %.0f%%", f.Actual, f.Target)
		case "ProfitFactor":
			msg += fmt.Sprintf("ProfitFactor %.2f < %.1f", f.Actual, f.Target)
		case "Expectancy":
			msg += fmt.Sprintf("Expectancy ₹%.0f < ₹0 (negative expected value)", f.Actual)
		case "Sharpe":
			msg += fmt.Sprintf("Sharpe %.2f < %.2f", f.Actual, f.Target)
		case "MaxDrawdown":
			msg += fmt.Sprintf("MaxDrawdown %.1f%% exceeds -%.0f%% limit", f.Actual, -f.Target)
		case "MinTrades":
			msg += fmt.Sprintf("Only %d trades (need %d for validation window)", int(f.Actual), int(f.Target))
		default:
			msg += fmt.Sprintf("%s: %.2f vs %.2f required", f.Rule, f.Actual, f.Target)
		}
	}
	return msg
}

// strategiesValidationHandler returns per-strategy validation status and details.
func strategiesValidationHandler(tracks map[string]*validator.StrategyTrack) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		type ValidationStatus struct {
			Strategy            string                    `json:"strategy"`
			Status              string                    `json:"status"`
			MockTradingApproved bool                      `json:"mock_trading_approved"`
			IsTradeable         bool                      `json:"is_tradeable"`
			WindowsCompleted    int                       `json:"windows_completed"`
			CurrentWindowProg   int                       `json:"current_window_progress"`
			TradesNeeded        int                       `json:"trades_needed_for_next_window"`
			LastWindow          *validator.WindowStats    `json:"last_window,omitempty"`
			ValidationResult    *validator.ValidationResult `json:"validation_result,omitempty"`
			RejectionReason     string                    `json:"rejection_reason,omitempty"`
		}

		out := make([]ValidationStatus, 0, len(tracks))
		for name, track := range tracks {
			vs := ValidationStatus{
				Strategy:            name,
				Status:              string(track.Status),
				MockTradingApproved: track.IsMockTradingApproved(),
				IsTradeable:         track.IsTradeable(),
				WindowsCompleted:    len(track.AllWindows()),
				CurrentWindowProg:   track.CurrentWindowProgress(),
				TradesNeeded:        validator.MinTradesPerWindow - track.CurrentWindowProgress(),
			}

			lastWin, hasWin := track.LastWindow()
			if hasWin {
				vr := validator.ValidateWindow(lastWin)
				vs.LastWindow = &lastWin
				vs.ValidationResult = &vr
			}

			if rejections := track.LastRejectionReasons(); len(rejections) > 0 {
				vs.RejectionReason = formatRejectionReason(rejections)
			}

			out = append(out, vs)
		}

		// Sort: approved first, then by status
		sort.Slice(out, func(i, j int) bool {
			if out[i].MockTradingApproved != out[j].MockTradingApproved {
				return out[i].MockTradingApproved
			}
			return out[i].Strategy < out[j].Strategy
		})

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(out)
	}
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

func pnlSince(trades []ledger.Trade, since time.Time) float64 {
	total := 0.0
	for _, t := range trades {
		if t.ExitAt.After(since) {
			total += t.NetPnL
		}
	}
	return total
}

func tradesAfter(trades []ledger.Trade, since time.Time) []ledger.Trade {
	var result []ledger.Trade
	for _, t := range trades {
		if t.ExitAt.After(since) {
			result = append(result, t)
		}
	}
	return result
}
