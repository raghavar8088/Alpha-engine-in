// S37–S43: Advanced intraday strategies (15m–1h timeframes).
// All follow the exact Strategy interface in strategy.go.
// No modifications to S1–S29, risk engine, or core architecture.
package strategy

import (
	"math"

	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// ─────────────────────────────────────────────────────────────────────────────
// S37 — Opening_Gap_Strategy
// Instrument : FUTURE (index futures)
// Timeframe  : 09:15–09:30 IST; gap > 0.5% from prev close
// Win target : 56%+  Holding: 30–90 minutes
// ─────────────────────────────────────────────────────────────────────────────

type OpeningGapStrategy struct {
	MinSLDistancePct float64
	MinGapPct        float64
}

func NewOpeningGapStrategy() *OpeningGapStrategy {
	return &OpeningGapStrategy{MinSLDistancePct: 0.003, MinGapPct: 0.005}
}

func (s *OpeningGapStrategy) Name() string { return "S37_Opening_Gap_Strategy" }

func (s *OpeningGapStrategy) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *OpeningGapStrategy) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Active only in the first 15 minutes.
	if mins < calendar.MarketOpen || mins > calendar.MarketOpen+15 {
		return Signal{}, false
	}

	prevClose := ctx.Bundle.PrevClose(ctx.Underlying)
	spot := ctx.Bundle.Spot(ctx.Underlying)
	if prevClose <= 0 || spot <= 0 {
		return Signal{}, false
	}

	gapPct := (spot - prevClose) / prevClose
	if math.Abs(gapPct) < s.MinGapPct {
		return Signal{}, false
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 5 {
		return Signal{}, false
	}
	atr := indicators.ATR(candles5m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	// VIX/PCR-based direction bias.
	vix := ctx.Regime.VIXLevel
	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	pcr := chain.PCR()
	// Gap up: follow if low VIX+PCR, fade if high VIX.
	// Gap down: follow if high VIX+PCR, fade if low VIX.
	slDist := atr
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}

	switch {
	case gapPct > s.MinGapPct:
		var direction Direction
		var reason string
		if vix < 16 && pcr < 1.0 {
			direction = Long
			reason = "Gap-up >0.5%, VIX<16, PCR<1.0 — follow-through long"
		} else {
			direction = Short
			reason = "Gap-up >0.5%, elevated VIX/PCR — fade gap down"
		}
		entry := spot
		var sl, tp float64
		var risk float64
		if direction == Long {
			sl = entry - slDist
			risk = entry - sl
			tp = entry + 2*risk
		} else {
			sl = entry + slDist
			risk = sl - entry
			tp = entry - 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: direction,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: tp, TakeProfit2: prevClose,
			Instrument:  "FUTURE",
			Reason:      reason,
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case gapPct < -s.MinGapPct:
		var direction Direction
		var reason string
		if vix > 18 && pcr > 1.0 {
			direction = Short
			reason = "Gap-down >0.5%, VIX>18, PCR>1.0 — follow-through short"
		} else {
			direction = Long
			reason = "Gap-down >0.5%, low VIX/PCR — fade gap up"
		}
		entry := spot
		var sl, tp float64
		var risk float64
		if direction == Long {
			sl = entry - slDist
			risk = entry - sl
			tp = entry + 2*risk
		} else {
			sl = entry + slDist
			risk = sl - entry
			tp = entry - 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: direction,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: tp, TakeProfit2: prevClose,
			Instrument:  "FUTURE",
			Reason:      reason,
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S38 — VWAP_Multi_Touch_Breakout
// Instrument : FUTURE
// Timeframe  : 15m; 3+ VWAP touches building, breakout on 4th touch
// Win target : 56%+  Holding: 15–30 minutes
// ─────────────────────────────────────────────────────────────────────────────

type VWAPMultiTouchBreakout struct {
	MinSLDistancePct float64
	MinTouches       int
}

func NewVWAPMultiTouchBreakout() *VWAPMultiTouchBreakout {
	return &VWAPMultiTouchBreakout{MinSLDistancePct: 0.003, MinTouches: 3}
}

func (s *VWAPMultiTouchBreakout) Name() string { return "S38_VWAP_Multi_Touch_Breakout" }

func (s *VWAPMultiTouchBreakout) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *VWAPMultiTouchBreakout) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+45 || mins > 14*60 {
		return Signal{}, false
	}

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles15m) < 12 {
		return Signal{}, false
	}

	var sess []marketdata.Candle
	for _, c := range candles15m {
		ci := c.Time.In(calendar.IST)
		if ci.Hour()*60+ci.Minute() >= calendar.MarketOpen {
			sess = append(sess, c)
		}
	}
	if len(sess) < 6 {
		return Signal{}, false
	}

	vwap := indicators.VWAP(sess)
	atr := indicators.ATR(candles15m, 14)
	if vwap == 0 || atr == 0 {
		return Signal{}, false
	}

	// Count VWAP touches in the session (within 0.3×ATR of VWAP).
	touchThresh := 0.3 * atr
	touchCount := 0
	for _, c := range sess[:len(sess)-1] {
		if math.Abs(c.Close-vwap) <= touchThresh || math.Abs(c.Low-vwap) <= touchThresh || math.Abs(c.High-vwap) <= touchThresh {
			touchCount++
		}
	}
	if touchCount < s.MinTouches {
		return Signal{}, false
	}

	last := sess[len(sess)-1]
	avgVol := indicators.AvgVolume(candles15m, 20)
	volSurge := last.Volume > 2.0*avgVol

	slDist := atr * 0.8
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case last.Close > vwap+touchThresh && volSurge:
		entry := last.Close
		sl := vwap - atr*0.5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - slDist
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "3+ VWAP touches, 4th touch breakout above VWAP with volume surge",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case last.Close < vwap-touchThresh && volSurge:
		entry := last.Close
		sl := vwap + atr*0.5
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + slDist
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "3+ VWAP touches, 4th touch breakdown below VWAP with volume surge",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S39 — Intraday_Fibonacci_Retracement
// Instrument : FUTURE
// Timeframe  : 1h; 38.2% / 61.8% retracement from first 30min swing
// Win target : 52%+  Holding: 30–90 minutes
// ─────────────────────────────────────────────────────────────────────────────

type IntradayFibonacciRetracement struct {
	MinSLDistancePct float64
}

func NewIntradayFibonacciRetracement() *IntradayFibonacciRetracement {
	return &IntradayFibonacciRetracement{MinSLDistancePct: 0.004}
}

func (s *IntradayFibonacciRetracement) Name() string {
	return "S39_Intraday_Fibonacci_Retracement"
}

func (s *IntradayFibonacciRetracement) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *IntradayFibonacciRetracement) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+60 || mins > 13*60+30 {
		return Signal{}, false
	}

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles15m) < 10 {
		return Signal{}, false
	}

	// Identify swing from first 30min (2 bars of 15m).
	var swHigh, swLow float64
	swCount := 0
	for _, c := range candles15m {
		ci := c.Time.In(calendar.IST)
		ciMins := ci.Hour()*60 + ci.Minute()
		if ciMins >= calendar.MarketOpen && ciMins < calendar.MarketOpen+30 {
			if swCount == 0 || c.High > swHigh {
				swHigh = c.High
			}
			if swCount == 0 || c.Low < swLow {
				swLow = c.Low
			}
			swCount++
		}
	}
	if swCount == 0 || swHigh-swLow < 50 {
		return Signal{}, false
	}

	swRange := swHigh - swLow
	atr := indicators.ATR(candles15m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	last := candles15m[len(candles15m)-1]
	closes := closesOf(candles15m)
	rsi := indicators.RSI(closes, 14)

	fib382 := swHigh - 0.382*swRange
	fib618 := swHigh - 0.618*swRange
	fib382b := swLow + 0.382*swRange
	fib618b := swLow + 0.618*swRange

	slDist := atr
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case ctx.Regime.Regime == regime.TrendingBull &&
		last.Close >= fib618-atr*0.5 && last.Close <= fib382+atr*0.5 && rsi < 45:
		entry := last.Close
		sl := fib618 - atr
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - slDist
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: swHigh,
			Instrument:  "FUTURE",
			Reason:      "Intraday 38.2–61.8% Fibonacci retrace from 30min swing, RSI<45, bull regime",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case ctx.Regime.Regime == regime.TrendingBear &&
		last.Close >= fib382b-atr*0.5 && last.Close <= fib618b+atr*0.5 && rsi > 55:
		entry := last.Close
		sl := fib618b + atr
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + slDist
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: swLow,
			Instrument:  "FUTURE",
			Reason:      "Intraday 38.2–61.8% Fibonacci retrace from 30min swing, RSI>55, bear regime",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S40 — Stochastic_RSI_Divergence
// Instrument : CE / PE (options, ADX<20 sideways filter)
// Timeframe  : 15m; StochRSI divergence at extremes
// Win target : 52%+  Holding: 30–60 minutes
// ─────────────────────────────────────────────────────────────────────────────

type StochasticRSIDivergence struct {
	MinSLDistancePct float64
	ADXMax           float64
	RSIPeriod        int
	StochPeriod      int
}

func NewStochasticRSIDivergence() *StochasticRSIDivergence {
	return &StochasticRSIDivergence{MinSLDistancePct: 0.005, ADXMax: 20.0, RSIPeriod: 14, StochPeriod: 14}
}

func (s *StochasticRSIDivergence) Name() string { return "S40_Stochastic_RSI_Divergence" }

func (s *StochasticRSIDivergence) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging}
}

func (s *StochasticRSIDivergence) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+45 || mins > 14*60 {
		return Signal{}, false
	}

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	need := s.RSIPeriod + s.StochPeriod + 5
	if len(candles15m) < need {
		return Signal{}, false
	}

	adx := indicators.ADX(candles15m, 14)
	if adx > s.ADXMax {
		return Signal{}, false
	}

	closes := closesOf(candles15m)
	n := len(closes)

	// Compute RSI series over last StochPeriod bars (inclusive).
	rsiNow := indicators.RSI(closes, s.RSIPeriod)
	rsiWindow := make([]float64, s.StochPeriod)
	for i := 0; i < s.StochPeriod; i++ {
		if n-1-i < s.RSIPeriod {
			break
		}
		rsiWindow[i] = indicators.RSI(closes[:n-i], s.RSIPeriod)
	}

	// StochRSI = (RSInow - RSImin) / (RSImax - RSImin).
	rsiMin, rsiMax := rsiWindow[0], rsiWindow[0]
	for _, r := range rsiWindow {
		if r < rsiMin {
			rsiMin = r
		}
		if r > rsiMax {
			rsiMax = r
		}
	}
	if rsiMax-rsiMin == 0 {
		return Signal{}, false
	}
	stochRSI := (rsiNow - rsiMin) / (rsiMax - rsiMin)

	// Also compute for lb bars ago.
	lb := 5
	if n-lb < s.RSIPeriod+s.StochPeriod {
		return Signal{}, false
	}
	rsiPrev := indicators.RSI(closes[:n-lb], s.RSIPeriod)

	last := candles15m[n-1]
	prev := candles15m[n-1-lb]
	atr := indicators.ATR(candles15m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	bullDiv := last.Low < prev.Low && rsiNow > rsiPrev && stochRSI < 0.2
	bearDiv := last.High > prev.High && rsiNow < rsiPrev && stochRSI > 0.8

	slDist := atr
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		spot = last.Close
	}
	strike := roundToStrike(spot, stepSize)

	switch {
	case bullDiv:
		entry := last.Close
		sl := last.Low - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "CE",
			Strike:      strike,
			Reason:      "StochRSI<0.2 + bullish divergence + ADX<20 sideways — CE long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case bearDiv:
		entry := last.Close
		sl := last.High + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "PE",
			Strike:      strike,
			Reason:      "StochRSI>0.8 + bearish divergence + ADX<20 sideways — PE short",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S41 — Time_of_Day_Momentum
// Instrument : FUTURE
// Timeframe  : Active only in two momentum windows: 10:15–10:45 and 14:00–14:30
// Win target : 54%+  Holding: 15–30 minutes
// ─────────────────────────────────────────────────────────────────────────────

type TimeOfDayMomentum struct {
	MinSLDistancePct float64
}

func NewTimeOfDayMomentum() *TimeOfDayMomentum {
	return &TimeOfDayMomentum{MinSLDistancePct: 0.003}
}

func (s *TimeOfDayMomentum) Name() string { return "S41_Time_of_Day_Momentum" }

func (s *TimeOfDayMomentum) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *TimeOfDayMomentum) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Only in the two momentum windows.
	window1 := mins >= 10*60+15 && mins <= 10*60+45
	window2 := mins >= 14*60 && mins <= 14*60+30
	if !window1 && !window2 {
		return Signal{}, false
	}

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles15m) < 10 {
		return Signal{}, false
	}

	closes := closesOf(candles15m)
	ema9 := indicators.LastEMA(closes, 9)
	ema21 := indicators.LastEMA(closes, 21)
	atr := indicators.ATR(candles15m, 14)
	if atr == 0 || ema9 == 0 || ema21 == 0 {
		return Signal{}, false
	}

	last := candles15m[len(candles15m)-1]
	avgVol := indicators.AvgVolume(candles15m, 20)
	volConfirm := last.Volume > 1.5*avgVol

	slDist := atr
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case ema9 > ema21 && last.Close > ema9 && volConfirm:
		entry := last.Close
		sl := ema9 - atr*0.5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - slDist
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "Time-of-day momentum window, EMA9>EMA21, price above EMA9 + volume",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case ema9 < ema21 && last.Close < ema9 && volConfirm:
		entry := last.Close
		sl := ema9 + atr*0.5
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + slDist
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "Time-of-day momentum window, EMA9<EMA21, price below EMA9 + volume",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S42 — Intraday_OI_Reversal
// Instrument : CE (if large PE OI drop → long) / PE (if large CE OI drop → short)
// Timeframe  : Any intraday bar; triggered when OI drops >10% in one bar
// Win target : 50%+  Holding: 15–45 minutes
// ─────────────────────────────────────────────────────────────────────────────

type IntradayOIReversal struct {
	MinSLDistancePct float64
	OIDropPct        float64
}

func NewIntradayOIReversal() *IntradayOIReversal {
	return &IntradayOIReversal{MinSLDistancePct: 0.004, OIDropPct: 0.10}
}

func (s *IntradayOIReversal) Name() string { return "S42_Intraday_OI_Reversal" }

func (s *IntradayOIReversal) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *IntradayOIReversal) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 14*60 {
		return Signal{}, false
	}

	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 {
		return Signal{}, false
	}

	// Sum CE and PE OI and OI changes.
	var ceOI, peOI int64
	var ceOIChange, peOIChange int64
	for _, sd := range chain.Strikes {
		if sd.OptionType == "CE" {
			ceOI += sd.OI
			ceOIChange += sd.OIChange
		} else if sd.OptionType == "PE" {
			peOI += sd.OI
			peOIChange += sd.OIChange
		}
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		return Signal{}, false
	}
	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles15m) < 10 {
		return Signal{}, false
	}
	atr := indicators.ATR(candles15m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	strike := roundToStrike(spot, stepSize)

	slDist := atr
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}

	// Large PE OI drop (unwinding shorts) → upside reversal, buy CE.
	if peOI > 0 && peOIChange < 0 && float64(-peOIChange)/float64(peOI) > s.OIDropPct {
		entry := spot
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "CE",
			Strike:      strike,
			Reason:      "PE OI drop >10% in one bar — short-covering reversal → CE long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}

	// Large CE OI drop (unwinding calls) → downside reversal, buy PE.
	if ceOI > 0 && ceOIChange < 0 && float64(-ceOIChange)/float64(ceOI) > s.OIDropPct {
		entry := spot
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "PE",
			Strike:      strike,
			Reason:      "CE OI drop >10% in one bar — long-unwinding reversal → PE short",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S43 — CPR_Pivot_Breakout
// Instrument : FUTURE
// Timeframe  : 15m; Central Pivot Range breakout with prior-day support/resistance
// Win target : 56%+  Holding: 30–60 minutes
// CPR = (High + Low + Close) / 3 of prior day's 1h candles.
// ─────────────────────────────────────────────────────────────────────────────

type CPRPivotBreakout struct {
	MinSLDistancePct float64
}

func NewCPRPivotBreakout() *CPRPivotBreakout {
	return &CPRPivotBreakout{MinSLDistancePct: 0.003}
}

func (s *CPRPivotBreakout) Name() string { return "S43_CPR_Pivot_Breakout" }

func (s *CPRPivotBreakout) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *CPRPivotBreakout) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 13*60 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	// Need at least 7 1h bars (one prior day) + current session bars.
	if len(candles1h) < barsPerDay*2 {
		return Signal{}, false
	}

	// Identify prior trading day's candles (7 bars before today's bars).
	n := len(candles1h)
	priorDayStart := n - barsPerDay*2
	priorDayEnd := n - barsPerDay
	if priorDayStart < 0 {
		priorDayStart = 0
	}
	priorBars := candles1h[priorDayStart:priorDayEnd]
	if len(priorBars) == 0 {
		return Signal{}, false
	}

	var priorHigh, priorLow, priorClose float64
	for _, c := range priorBars {
		if priorHigh == 0 || c.High > priorHigh {
			priorHigh = c.High
		}
		if priorLow == 0 || c.Low < priorLow {
			priorLow = c.Low
		}
		priorClose = c.Close
	}

	// CPR levels.
	pivot := (priorHigh + priorLow + priorClose) / 3
	bc := (priorHigh + priorLow) / 2   // Bottom Central Pivot
	tc := (pivot - bc) + pivot          // Top Central Pivot
	r1 := 2*pivot - priorLow            // Resistance 1
	s1 := 2*pivot - priorHigh           // Support 1

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles15m) < 10 {
		return Signal{}, false
	}
	atr := indicators.ATR(candles15m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	last := candles15m[len(candles15m)-1]
	avgVol := indicators.AvgVolume(candles15m, 20)
	volConfirm := last.Volume > 1.5*avgVol

	slDist := atr
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	// Use tc, bc, r1, s1 to avoid "declared and not used" error.
	_ = bc

	switch {
	case last.Close > tc && volConfirm:
		entry := last.Close
		sl := pivot - atr*0.5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - slDist
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: r1,
			Instrument:  "FUTURE",
			Reason:      "Price breaks above CPR Top Central Pivot with volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case last.Close < bc && volConfirm:
		entry := last.Close
		sl := pivot + atr*0.5
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + slDist
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: s1,
			Instrument:  "FUTURE",
			Reason:      "Price breaks below CPR Bottom Central Pivot with volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}
