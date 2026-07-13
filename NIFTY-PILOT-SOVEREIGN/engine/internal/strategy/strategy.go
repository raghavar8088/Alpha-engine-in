// Package strategy defines the Strategy interface every S1-S9 strategy
// implements, mirroring the BTC engine's Strategy/MarketContext/Signal
// pattern so the evaluation loop, risk gate, and sizer are unaware of
// strategy-specific logic.
package strategy

import (
	"time"

	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

type Direction string

const (
	Long  Direction = "LONG"
	Short Direction = "SHORT"
	Flat  Direction = "FLAT"
)

// Signal is the output of one strategy evaluation. StopLoss/TakeProfit
// are in underlying-equivalent price terms (premium for options legs);
// the execution layer translates into the actual instrument traded.
type Signal struct {
	Strategy    string
	Underlying  string
	Direction   Direction
	Confidence  float64 // 0..1
	Entry       float64
	StopLoss    float64
	TakeProfit  float64
	TakeProfit2 float64
	Instrument  string // "FUTURE" | "CE" | "PE" | "IRON_CONDOR" | "STRANGLE"
	Strike      float64
	Expiry      time.Time
	Reason      string
	GeneratedAt time.Time
}

// IsValid enforces the two hard geometry rules every strategy must
// satisfy before a signal reaches the risk gate (lesson from the BTC
// system: minimum SL distance and minimum 2:1 R:R, or normal
// volatility sweeps the stop before the thesis plays out).
func (s Signal) IsValid(minSLDistancePct float64) bool {
	if s.Direction == Flat {
		return false
	}
	if s.Entry <= 0 || s.StopLoss <= 0 || s.TakeProfit <= 0 {
		return false
	}
	slDist := abs(s.Entry - s.StopLoss)
	if slDist/s.Entry < minSLDistancePct {
		return false // stop too tight, would be noise-swept
	}
	tpDist := abs(s.TakeProfit - s.Entry)
	rr := tpDist / slDist
	return rr >= 2.0 // minimum 2:1 R:R
}

func abs(f float64) float64 {
	if f < 0 {
		return -f
	}
	return f
}

// MarketContext is everything a strategy's Evaluate call receives:
// read-only market data, the authoritative regime classification, and
// the evaluation timestamp. No strategy may read global state outside
// this struct - keeps every strategy unit-testable in isolation.
type MarketContext struct {
	Now        time.Time
	Underlying string
	Bundle     *marketdata.NiftyDataBundle
	Regime     regime.RegimeClass
}

// Strategy is the interface every S1-S9 implementation satisfies.
type Strategy interface {
	Name() string
	// AllowedRegimes lists the regimes this strategy is permitted to
	// generate new entry signals in; the evaluation loop gates on this
	// before calling Evaluate, in addition to RegimeClass.AllowNewEntries.
	AllowedRegimes() []regime.Regime
	Evaluate(ctx MarketContext) (Signal, bool)
}

// RegimeAllowed checks both the strategy's own allowed-regime list and
// the classifier's global AllowNewEntries gate.
func RegimeAllowed(s Strategy, rc regime.RegimeClass) bool {
	if !rc.AllowNewEntries {
		return false
	}
	for _, r := range s.AllowedRegimes() {
		if r == rc.Regime {
			return true
		}
	}
	return false
}
