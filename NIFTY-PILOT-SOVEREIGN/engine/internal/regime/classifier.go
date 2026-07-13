// Package regime implements the single, authoritative India-market
// regime classifier. The BTC system ran two competing classifiers at
// one point and that caused mistimed entries; this package is
// deliberately the ONLY source of regime truth in this engine — every
// strategy and the Kelly sizer must read RegimeClass from here, never
// recompute their own regime signal.
package regime

import (
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
)

type Regime string

const (
	TrendingBull Regime = "TRENDING_BULL"
	TrendingBear Regime = "TRENDING_BEAR"
	Ranging      Regime = "RANGING"
	HighVol      Regime = "HIGH_VOL"
	ExpiryDay    Regime = "EXPIRY_DAY"
	EventRisk    Regime = "EVENT_RISK"
	Unknown      Regime = "UNKNOWN"
)

// RegimeClass is the classifier's output, consumed by strategies and sizing.
type RegimeClass struct {
	Regime           Regime
	VIXLevel         float64
	ADX              float64
	PositionSizeMult float64
	AllowNewEntries  bool
	Reason           string
}

// EventCalendar is a hardcoded list of high-impact macro event dates
// (RBI monetary policy, Union Budget, major election results) that
// trigger EVENT_RISK regime. REGULATORY/CALENDAR FLAG: this list is a
// point-in-time seed and MUST be refreshed quarterly from RBI's
// monetary-policy calendar and the Union Budget date — do not let it
// silently go stale.
type EventCalendar struct {
	Dates map[string]string // "2026-02-01" -> "Union Budget"
}

func DefaultEventCalendar() *EventCalendar {
	return &EventCalendar{Dates: map[string]string{
		"2026-02-01": "Union Budget (tentative - VERIFY)",
		"2026-02-06": "RBI MPC Policy (tentative - VERIFY against RBI calendar)",
		"2026-04-09": "RBI MPC Policy (tentative - VERIFY)",
		"2026-06-05": "RBI MPC Policy (tentative - VERIFY)",
		"2026-08-07": "RBI MPC Policy (tentative - VERIFY)",
		"2026-10-08": "RBI MPC Policy (tentative - VERIFY)",
		"2026-12-05": "RBI MPC Policy (tentative - VERIFY)",
	}}
}

func (e *EventCalendar) IsEventDay(t time.Time) (bool, string) {
	d := t.In(calendar.IST).Format("2006-01-02")
	reason, ok := e.Dates[d]
	return ok, reason
}

// IsEventAdjacent reports whether t is the event day or the trading day
// immediately before it (event risk is priced in ahead of the print).
func (e *EventCalendar) IsEventAdjacent(t time.Time, cal *calendar.Service) (bool, string) {
	if ok, reason := e.IsEventDay(t); ok {
		return true, reason
	}
	next := t.AddDate(0, 0, 1)
	for i := 0; i < 4 && !cal.IsTradingDay(next); i++ {
		next = next.AddDate(0, 0, 1)
	}
	if ok, reason := e.IsEventDay(next); ok {
		return true, reason + " (day before)"
	}
	return false, ""
}

// Classifier is the single authoritative regime engine.
type Classifier struct {
	Calendar *calendar.Service
	Events   *EventCalendar
}

func NewClassifier(cal *calendar.Service, events *EventCalendar) *Classifier {
	return &Classifier{Calendar: cal, Events: events}
}

// Classify produces the authoritative RegimeClass for underlying at time t,
// using EMA50/EMA200/ADX14 on 15m candles and the live India VIX level.
//
// Threshold rationale (documented starting points to refine via
// backtesting, per Part 4 of the build spec):
//   TRENDING_BULL: spot > EMA50 > EMA200, ADX14 > 25, VIX < 16
//   TRENDING_BEAR: spot < EMA50 < EMA200, ADX14 > 25, VIX < 16
//   RANGING:       ADX14 < 20, VIX in [12,16]
//   HIGH_VOL:      VIX > 20 -> size mult 0, block entries
//   EXPIRY_DAY:    weekly expiry date for this underlying -> size mult 0.5
//   EVENT_RISK:    RBI/Budget/election day or day before -> size mult 0.3
//   UNKNOWN:       insufficient candle history -> size mult 0, block entries
//
// Priority order when multiple conditions overlap: EVENT_RISK and
// EXPIRY_DAY are date-driven overrides checked first (gamma/event risk
// dominates regardless of trend), then HIGH_VOL (VIX spike dominates
// trend/range classification), then trend/range.
func (c *Classifier) Classify(underlying string, bundle *marketdata.NiftyDataBundle, t time.Time) RegimeClass {
	vix := bundle.IndiaVIX()

	if ok, reason := c.Events.IsEventAdjacent(t, c.Calendar); ok {
		return RegimeClass{Regime: EventRisk, VIXLevel: vix, PositionSizeMult: 0.3, AllowNewEntries: true, Reason: reason}
	}

	expIndex := underlying
	if calendar.IsExpiryDay(t, expIndex) {
		return RegimeClass{Regime: ExpiryDay, VIXLevel: vix, PositionSizeMult: 0.5, AllowNewEntries: true, Reason: "weekly/monthly expiry day - elevated gamma risk"}
	}

	if vix > 20 {
		return RegimeClass{Regime: HighVol, VIXLevel: vix, PositionSizeMult: 0.0, AllowNewEntries: false, Reason: "India VIX > 20"}
	}

	candles := bundle.Candles(underlying, "15m")
	if len(candles) < 200 {
		return RegimeClass{Regime: Unknown, VIXLevel: vix, PositionSizeMult: 0.0, AllowNewEntries: false, Reason: "insufficient 15m history for EMA200/ADX14"}
	}

	closes := make([]float64, len(candles))
	for i, cd := range candles {
		closes[i] = cd.Close
	}
	ema50 := indicators.LastEMA(closes, 50)
	ema200 := indicators.LastEMA(closes, 200)
	adx := indicators.ADX(candles, 14)
	spot := bundle.Spot(underlying)
	if spot == 0 {
		spot = closes[len(closes)-1]
	}

	switch {
	case spot > ema50 && ema50 > ema200 && adx > 25 && vix < 16:
		return RegimeClass{Regime: TrendingBull, VIXLevel: vix, ADX: adx, PositionSizeMult: 1.0, AllowNewEntries: true, Reason: "spot>EMA50>EMA200, ADX>25, VIX<16"}
	case spot < ema50 && ema50 < ema200 && adx > 25 && vix < 16:
		return RegimeClass{Regime: TrendingBear, VIXLevel: vix, ADX: adx, PositionSizeMult: 1.0, AllowNewEntries: true, Reason: "spot<EMA50<EMA200, ADX>25, VIX<16"}
	case adx < 20 && vix >= 12 && vix <= 16:
		return RegimeClass{Regime: Ranging, VIXLevel: vix, ADX: adx, PositionSizeMult: 0.75, AllowNewEntries: true, Reason: "ADX<20, VIX in [12,16]"}
	default:
		return RegimeClass{Regime: Unknown, VIXLevel: vix, ADX: adx, PositionSizeMult: 0.0, AllowNewEntries: false, Reason: "no regime condition matched cleanly - low confidence"}
	}
}
