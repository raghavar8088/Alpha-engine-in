// S48–S50: Index options spread strategies (expiry-day straddle, iron condor, calendar).
// All follow the exact Strategy interface in strategy.go.
// No modifications to S1–S29, risk engine, or core architecture.
package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// ─────────────────────────────────────────────────────────────────────────────
// S48 — BankNifty_Options_Straddle
// Instrument : STRANGLE (short ATM straddle on expiry day)
// Timeframe  : Entered at 09:20–09:30 IST on expiry day (Wednesday for BankNifty)
// SL: 30% gain on either individual leg (proxied as 30% of ATM premium)
// Target: 15% premium decay by afternoon
// Win target : 60%+  Holding: 1–4 hours (theta decay)
// ─────────────────────────────────────────────────────────────────────────────

type BankNiftyOptionsStraddle struct {
	MinSLDistancePct float64
	MaxVIX           float64
}

func NewBankNiftyOptionsStraddle() *BankNiftyOptionsStraddle {
	return &BankNiftyOptionsStraddle{MinSLDistancePct: 0.01, MaxVIX: 18.0}
}

func (s *BankNiftyOptionsStraddle) Name() string { return "S48_BankNifty_Options_Straddle" }

func (s *BankNiftyOptionsStraddle) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.ExpiryDay, regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *BankNiftyOptionsStraddle) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	// Skip high-vol environments — theta decay straddle needs calm.
	if ctx.Regime.VIXLevel > s.MaxVIX {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Enter only at 09:20–09:30 on any day (expiry regime already classified).
	if mins < calendar.MarketOpen+5 || mins > calendar.MarketOpen+15 {
		return Signal{}, false
	}
	// Only on Wednesday (BankNifty expiry) or Thursday (Nifty expiry).
	wd := ist.Weekday()
	if wd != 3 && wd != 4 {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
		if len(candles1m) == 0 {
			return Signal{}, false
		}
		spot = candles1m[len(candles1m)-1].Close
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 10 {
		return Signal{}, false
	}
	atr5m := indicators.ATR(candles5m, 14)
	if atr5m == 0 {
		return Signal{}, false
	}

	stepSize := 100.0 // BankNifty default; Nifty uses 50.
	if ctx.Underlying == "NIFTY" {
		stepSize = 50.0
	}
	atmStrike := roundToStrike(spot, stepSize)

	// SL if price moves beyond 1.5×ATR (either wing ITM).
	slDist := atr5m * 2
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}
	sl := spot + slDist

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.60, Entry: spot, StopLoss: sl,
		TakeProfit: spot, TakeProfit2: spot - slDist*0.5,
		Instrument:  "STRANGLE",
		Strike:      atmStrike,
		Reason:      "Expiry day, VIX<18 — short ATM straddle at 09:20 for theta decay",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// ─────────────────────────────────────────────────────────────────────────────
// S49 — Nifty_Iron_Condor
// Instrument : IRON_CONDOR (weekly sell 100-pt OTM strangle, buy 150-pt OTM hedge)
// Timeframe  : Monday morning entry on weekly expiry cycle
// Win target : 58%+  Holding: Monday–Thursday (theta decay with defined risk)
// ─────────────────────────────────────────────────────────────────────────────

type NiftyIronCondor struct {
	MinSLDistancePct float64
	ShortOTMOffset   float64 // points OTM for short legs (e.g. 100)
	LongOTMOffset    float64 // points OTM for long hedge legs (e.g. 150)
	MaxVIX           float64
}

func NewNiftyIronCondor() *NiftyIronCondor {
	return &NiftyIronCondor{
		MinSLDistancePct: 0.01, ShortOTMOffset: 100, LongOTMOffset: 150, MaxVIX: 18.0,
	}
}

func (s *NiftyIronCondor) Name() string { return "S49_Nifty_Iron_Condor" }

func (s *NiftyIronCondor) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *NiftyIronCondor) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	if ctx.Regime.VIXLevel > s.MaxVIX {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Monday morning only, after opening range settles.
	if ist.Weekday() != 1 || mins < calendar.MarketOpen+30 || mins > calendar.MarketOpen+60 {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		return Signal{}, false
	}

	// Weekly range check: avoid if prior week moved >2%.
	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < barsPerDay*5 {
		return Signal{}, false
	}
	prevWeekBars := barsPerDay * 5
	if prevWeekBars > len(candles1h)-1 {
		prevWeekBars = len(candles1h) - 1
	}
	var weekHigh, weekLow float64
	for _, c := range candles1h[len(candles1h)-1-prevWeekBars : len(candles1h)-1] {
		if weekHigh == 0 || c.High > weekHigh {
			weekHigh = c.High
		}
		if weekLow == 0 || c.Low < weekLow {
			weekLow = c.Low
		}
	}
	if weekLow > 0 && (weekHigh-weekLow)/weekLow > 0.02 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	// Short strikes (100-pt OTM).
	shortCallStrike := roundToStrike(spot+s.ShortOTMOffset, stepSize)
	shortPutStrike := roundToStrike(spot-s.ShortOTMOffset, stepSize)
	// Long strikes (150-pt OTM hedge) — used in Reason string.
	longCallStrike := roundToStrike(spot+s.LongOTMOffset, stepSize)
	longPutStrike := roundToStrike(spot-s.LongOTMOffset, stepSize)

	entry := spot
	slDist := s.LongOTMOffset // max loss per leg capped by long hedge
	if slDist < entry*s.MinSLDistancePct {
		slDist = entry * s.MinSLDistancePct
	}
	sl := entry + slDist

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.58, Entry: entry, StopLoss: sl,
		TakeProfit: entry, TakeProfit2: entry - slDist*0.5,
		Instrument: "IRON_CONDOR",
		Strike:     shortCallStrike,
		Reason: "Weekly iron condor: sell " + formatStrike(shortCallStrike) + "C / " +
			formatStrike(shortPutStrike) + "P, buy " + formatStrike(longCallStrike) + "C / " +
			formatStrike(longPutStrike) + "P — collect premium, VIX<18",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// ─────────────────────────────────────────────────────────────────────────────
// S50 — Nifty_ATM_Calendar_Spread
// Instrument : STRANGLE (calendar: long next-week ATM, short this-week ATM)
// Timeframe  : Monday morning; delta-neutral entry
// Win target : 52%+  Holding: until current-week expiry (Thursday)
// ─────────────────────────────────────────────────────────────────────────────

type NiftyATMCalendarSpread struct {
	MinSLDistancePct float64
	MaxVIX           float64
}

func NewNiftyATMCalendarSpread() *NiftyATMCalendarSpread {
	return &NiftyATMCalendarSpread{MinSLDistancePct: 0.01, MaxVIX: 20.0}
}

func (s *NiftyATMCalendarSpread) Name() string { return "S50_Nifty_ATM_Calendar_Spread" }

func (s *NiftyATMCalendarSpread) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *NiftyATMCalendarSpread) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	if ctx.Regime.VIXLevel > s.MaxVIX {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Monday morning only.
	if ist.Weekday() != 1 || mins < calendar.MarketOpen+30 || mins > calendar.MarketOpen+75 {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < 14 {
		return Signal{}, false
	}
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	atmStrike := roundToStrike(spot, stepSize)

	// Calendar spread: Long next-week ATM - Short this-week ATM.
	// Net debit = time-value difference. Max loss = net debit.
	slDist := atr1h * 1.5
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}
	sl := spot + slDist

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
		Confidence: 0.52, Entry: spot, StopLoss: sl,
		TakeProfit: spot + slDist*2, TakeProfit2: spot + slDist*3,
		Instrument:  "STRANGLE",
		Strike:      atmStrike,
		Reason:      "Calendar spread: long next-week ATM, short this-week ATM — time-value decay delta-neutral",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// formatStrike renders a strike price as an integer string for Reason logging.
func formatStrike(strike float64) string {
	i := int(strike)
	s := ""
	if i == 0 {
		return "0"
	}
	for i > 0 {
		s = string(rune('0'+i%10)) + s
		i /= 10
	}
	return s
}
