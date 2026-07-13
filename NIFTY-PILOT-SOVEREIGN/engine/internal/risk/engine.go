// Package risk implements the risk gate, ported directly from the BTC
// engine's risk lessons and adapted for INR/IST: daily loss circuit
// breaker resetting at market open (not midnight UTC), intraday
// drawdown ratchet, directional caps, a correlation/concentration gate
// for Nifty/Bank Nifty co-movement, the kill switch with precise
// halting-vs-non-halting trigger classification, and a margin-breach
// circuit breaker with no BTC-engine equivalent.
package risk

import (
	"fmt"
	"sync"
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/sizing"
)

// Config holds all risk-engine thresholds.
type Config struct {
	DailyLossLimitPct      float64 // e.g. 0.03 = 3% of portfolio, circuit breaker for the day
	IntradayDrawdownPct    float64 // e.g. 0.02 = 2%, triggers a 1h pause (ratchet, not full day)
	IntradayPauseDuration  time.Duration
	MaxConcurrentPerDir    int     // max concurrent positions per direction
	MarginBreachThreshold  float64 // e.g. 0.80 = 80% margin utilization triggers force-reduce
}

func DefaultConfig() Config {
	return Config{
		DailyLossLimitPct:     0.03,
		IntradayDrawdownPct:   0.02,
		IntradayPauseDuration: time.Hour,
		MaxConcurrentPerDir:   5,
		MarginBreachThreshold: 0.80,
	}
}

// Engine is the single risk gate every execution path must pass
// through before a new entry is allowed.
type Engine struct {
	mu sync.RWMutex

	cfg      Config
	cal      *calendar.Service
	killSw   *KillSwitch

	portfolioINR     float64
	sessionStartDate string // IST calendar date, "2026-06-20"
	sessionStartEquity float64
	peakEquityToday    float64

	intradayPausedUntil time.Time

	longCount  int
	shortCount int

	marginBook *sizing.MarginBook
}

func NewEngine(cfg Config, cal *calendar.Service, portfolioINR float64) *Engine {
	return &Engine{
		cfg: cfg, cal: cal, killSw: NewKillSwitch(),
		portfolioINR: portfolioINR,
		marginBook:   &sizing.MarginBook{TotalCapitalINR: portfolioINR},
	}
}

func (e *Engine) MarginBook() *sizing.MarginBook { return e.marginBook }
func (e *Engine) KillSwitch() *KillSwitch        { return e.killSw }

// rolloverIfNewSession resets the daily loss circuit breaker at
// session open (09:15 IST) — NOT midnight UTC. This is the critical
// timezone adaptation called out in the build spec: a naive UTC-day
// reset would roll over mid-session for IST.
func (e *Engine) rolloverIfNewSession(now time.Time, currentEquity float64) {
	ist := now.In(calendar.IST)
	today := ist.Format("2006-01-02")
	if e.sessionStartDate != today {
		e.sessionStartDate = today
		e.sessionStartEquity = currentEquity
		e.peakEquityToday = currentEquity
		e.longCount = 0
		e.shortCount = 0
	}
	if currentEquity > e.peakEquityToday {
		e.peakEquityToday = currentEquity
	}
}

// CheckEntryAllowed is the single gate every new entry must pass. It
// evaluates, in order: kill switch, market hours, daily loss circuit
// breaker, intraday drawdown ratchet pause, directional caps, and
// margin-breach circuit breaker. Returns (allowed, reason-if-blocked).
func (e *Engine) CheckEntryAllowed(now time.Time, currentEquity float64, direction string) (bool, string) {
	e.mu.Lock()
	defer e.mu.Unlock()

	if e.killSw.IsActive() {
		return false, "kill switch ACTIVE: " + e.killSw.ActiveReason()
	}
	if !e.cal.IsMarketOpen(now) {
		return false, "market closed (outside 09:15-15:30 IST or non-trading day)"
	}

	e.rolloverIfNewSession(now, currentEquity)

	dailyLossPct := (e.sessionStartEquity - currentEquity) / e.sessionStartEquity
	if e.sessionStartEquity > 0 && dailyLossPct >= e.cfg.DailyLossLimitPct {
		e.killSw.Trigger(TriggerDailyLossLimit, "daily loss circuit breaker hit: "+formatPct(dailyLossPct), true)
		return false, "daily loss circuit breaker triggered"
	}

	if now.Before(e.intradayPausedUntil) {
		return false, "intraday drawdown ratchet pause active until " + e.intradayPausedUntil.In(calendar.IST).Format("15:04:05")
	}
	intradayDD := (e.peakEquityToday - currentEquity) / e.peakEquityToday
	if e.peakEquityToday > 0 && intradayDD >= e.cfg.IntradayDrawdownPct {
		e.intradayPausedUntil = now.Add(e.cfg.IntradayPauseDuration)
		return false, "intraday drawdown ratchet triggered, paused for " + e.cfg.IntradayPauseDuration.String()
	}

	if direction == "LONG" && e.longCount >= e.cfg.MaxConcurrentPerDir {
		return false, "max concurrent LONG positions reached"
	}
	if direction == "SHORT" && e.shortCount >= e.cfg.MaxConcurrentPerDir {
		return false, "max concurrent SHORT positions reached"
	}

	if e.marginBook.UtilizationPct() >= e.cfg.MarginBreachThreshold {
		e.killSw.Trigger(TriggerMarginBreach, "margin utilization >= "+formatPct(e.cfg.MarginBreachThreshold), true)
		return false, "margin breach circuit breaker triggered"
	}

	return true, ""
}

// RegisterOpen increments directional position counters after a fill.
func (e *Engine) RegisterOpen(direction string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if direction == "LONG" {
		e.longCount++
	} else if direction == "SHORT" {
		e.shortCount++
	}
}

// RegisterClose decrements directional position counters after an exit.
func (e *Engine) RegisterClose(direction string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if direction == "LONG" && e.longCount > 0 {
		e.longCount--
	} else if direction == "SHORT" && e.shortCount > 0 {
		e.shortCount--
	}
}

// ConcentrationGate flags when Nifty and Bank Nifty positions (highly
// correlated instruments) would together exceed the directional cap if
// treated as one concentrated bet rather than two independent ones.
// Call before opening a new Nifty or Bank Nifty position; pass the
// counts of currently open same-direction positions in EACH index.
func ConcentrationGate(niftySameDir, bankNiftySameDir, maxConcentratedBet int) (bool, string) {
	combined := niftySameDir + bankNiftySameDir
	if combined >= maxConcentratedBet {
		return false, "Nifty+BankNifty combined same-direction exposure treated as one concentrated bet, limit reached"
	}
	return true, ""
}

func formatPct(f float64) string {
	return fmt.Sprintf("%.2f%%", f*100)
}
