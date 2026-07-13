// S44–S47: Advanced swing strategies (daily–weekly horizon, 1–10 day holds).
// All follow the exact Strategy interface in strategy.go.
// No modifications to S1–S29, risk engine, or core architecture.
package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// ─────────────────────────────────────────────────────────────────────────────
// S44 — Weekly_Options_Momentum
// Instrument : CE or PE (weekly Nifty options)
// Timeframe  : Monday open; EMA50 daily trend determines direction.
//
//	Exit: Thursday (hold 3 days). Signal only on Monday 09:45–10:15 IST.
//
// Win target : 52%+  Holding: Monday–Thursday
// ─────────────────────────────────────────────────────────────────────────────

type WeeklyOptionsMomentum struct {
	MinSLDistancePct float64
}

func NewWeeklyOptionsMomentum() *WeeklyOptionsMomentum {
	return &WeeklyOptionsMomentum{MinSLDistancePct: 0.01}
}

func (s *WeeklyOptionsMomentum) Name() string { return "S44_Weekly_Options_Momentum" }

func (s *WeeklyOptionsMomentum) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *WeeklyOptionsMomentum) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Only on Monday morning.
	if ist.Weekday() != 1 || mins < calendar.MarketOpen+30 || mins > calendar.MarketOpen+60 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	need := (50 + 5) * barsPerDay
	if len(candles1h) < need {
		return Signal{}, false
	}

	dailyCloses := deriveDailyCloses(candles1h)
	if len(dailyCloses) < 55 {
		return Signal{}, false
	}

	ema50 := indicators.LastEMA(dailyCloses, 50)
	if ema50 == 0 {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
		if len(candles1m) > 0 {
			spot = candles1m[len(candles1m)-1].Close
		}
	}
	if spot == 0 {
		return Signal{}, false
	}

	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}
	atr5d := atr1h * float64(barsPerDay) * 0.5

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	strike := roundToStrike(spot, stepSize)

	slDist := atr5d * 0.8
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}

	switch {
	case ctx.Regime.Regime == regime.TrendingBull && spot > ema50:
		entry := spot
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "CE",
			Strike:      strike,
			Reason:      "Monday open, Nifty above EMA50, bull regime — weekly CE momentum trade",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case ctx.Regime.Regime == regime.TrendingBear && spot < ema50:
		entry := spot
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "PE",
			Strike:      strike,
			Reason:      "Monday open, Nifty below EMA50, bear regime — weekly PE momentum trade",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S45 — Positional_Breakout_Swing
// Instrument : FUTURE (rolling front-month)
// Timeframe  : Daily closes (from 1h); 20-day channel breakout + EMA50 slope
// Win target : 50%+  Holding: 5–10 days
// ─────────────────────────────────────────────────────────────────────────────

type PositionalBreakoutSwing struct {
	MinSLDistancePct    float64
	ChannelDays         int
	EMASlowPeriod       int
}

func NewPositionalBreakoutSwing() *PositionalBreakoutSwing {
	return &PositionalBreakoutSwing{MinSLDistancePct: 0.005, ChannelDays: 20, EMASlowPeriod: 50}
}

func (s *PositionalBreakoutSwing) Name() string { return "S45_Positional_Breakout_Swing" }

func (s *PositionalBreakoutSwing) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *PositionalBreakoutSwing) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// EOD signal.
	if mins < 14*60+45 || mins > calendar.MarketClose {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	need := (s.EMASlowPeriod + s.ChannelDays + 5) * barsPerDay
	if len(candles1h) < need {
		return Signal{}, false
	}

	dailyCloses := deriveDailyCloses(candles1h)
	need2 := s.EMASlowPeriod + s.ChannelDays + 5
	if len(dailyCloses) < need2 {
		return Signal{}, false
	}

	n := len(dailyCloses)
	ema50 := indicators.LastEMA(dailyCloses, s.EMASlowPeriod)
	ema50Prev := indicators.LastEMA(dailyCloses[:n-1], s.EMASlowPeriod)
	if ema50 == 0 || ema50Prev == 0 {
		return Signal{}, false
	}

	// 20-day high/low channel (excluding current day).
	channelStart := n - 1 - s.ChannelDays
	if channelStart < 0 {
		return Signal{}, false
	}
	var chanHigh, chanLow float64
	for _, c := range dailyCloses[channelStart : n-1] {
		if chanHigh == 0 || c > chanHigh {
			chanHigh = c
		}
		if chanLow == 0 || c < chanLow {
			chanLow = c
		}
	}

	spot := dailyCloses[n-1]
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}
	atr5d := atr1h * float64(barsPerDay) * 0.5

	slopeUp := ema50 > ema50Prev
	slopeDown := ema50 < ema50Prev

	slDist := atr5d
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}

	switch {
	case spot > chanHigh && slopeUp:
		entry := spot
		sl := chanHigh - atr1h*0.5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - slDist
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 4*risk,
			Instrument:  "FUTURE",
			Reason:      "20-day channel breakout high + EMA50 slope positive — positional long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case spot < chanLow && slopeDown:
		entry := spot
		sl := chanLow + atr1h*0.5
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + slDist
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 4*risk,
			Instrument:  "FUTURE",
			Reason:      "20-day channel breakdown low + EMA50 slope negative — positional short",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S46 — Mean_Reversion_Swing
// Instrument : FUTURE
// Timeframe  : Daily closes (from 1h); price > 2σ from 20-day SMA, RSI extreme
// Win target : 52%+  Holding: 3–5 days
// ─────────────────────────────────────────────────────────────────────────────

type MeanReversionSwing struct {
	MinSLDistancePct float64
	SMAPeriod        int
	RSIOversold      float64
	RSIOverbought    float64
}

func NewMeanReversionSwing() *MeanReversionSwing {
	return &MeanReversionSwing{
		MinSLDistancePct: 0.005, SMAPeriod: 20, RSIOversold: 30, RSIOverbought: 70,
	}
}

func (s *MeanReversionSwing) Name() string { return "S46_Mean_Reversion_Swing" }

func (s *MeanReversionSwing) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *MeanReversionSwing) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < 14*60+45 || mins > calendar.MarketClose {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	need := (s.SMAPeriod + 10) * barsPerDay
	if len(candles1h) < need {
		return Signal{}, false
	}

	dailyCloses := deriveDailyCloses(candles1h)
	if len(dailyCloses) < s.SMAPeriod+10 {
		return Signal{}, false
	}

	n := len(dailyCloses)
	window := dailyCloses[n-s.SMAPeriod : n]

	// 20-day SMA and σ.
	var sma float64
	for _, c := range window {
		sma += c
	}
	sma /= float64(s.SMAPeriod)
	var sumSq float64
	for _, c := range window {
		d := c - sma
		sumSq += d * d
	}
	sigma := 0.0
	if s.SMAPeriod > 1 {
		sigma = 0.0
		for _, c := range window {
			d := c - sma
			sigma += d * d
		}
		sigma = sqrt(sigma / float64(s.SMAPeriod))
	}
	if sigma == 0 {
		return Signal{}, false
	}

	spot := dailyCloses[n-1]
	rsi := indicators.RSI(dailyCloses, 14)
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}
	atr3d := atr1h * float64(barsPerDay) * 0.4

	slDist := atr3d
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}

	zScore := (spot - sma) / sigma

	switch {
	case zScore < -2.0 && rsi < s.RSIOversold:
		entry := spot
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: sma,
			Instrument:  "FUTURE",
			Reason:      "Price −2σ from 20-day SMA, RSI<30 — mean-reversion long swing",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case zScore > 2.0 && rsi > s.RSIOverbought:
		entry := spot
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: sma,
			Instrument:  "FUTURE",
			Reason:      "Price +2σ from 20-day SMA, RSI>70 — mean-reversion short swing",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// sqrt is a local alias to avoid importing math in this file.
func sqrt(x float64) float64 {
	if x <= 0 {
		return 0
	}
	// Newton's method for simplicity (math is imported in other files in package).
	z := x
	for i := 0; i < 20; i++ {
		z -= (z*z - x) / (2 * z)
	}
	return z
}

// ─────────────────────────────────────────────────────────────────────────────
// S47 — Earnings_Event_Strangle
// Instrument : STRANGLE (ATM call + put, EventRisk regime)
// Timeframe  : Entered 3 trading-day sessions before results (EventRisk regime)
// Win target : 55%+  Holding: 3 days (sell day after results)
// ─────────────────────────────────────────────────────────────────────────────

type EarningsEventStrangle struct {
	MinSLDistancePct float64
	// MaxVIX: skip buying strangles when VIX too elevated (overpaying for premium).
	MaxVIX float64
}

func NewEarningsEventStrangle() *EarningsEventStrangle {
	return &EarningsEventStrangle{MinSLDistancePct: 0.01, MaxVIX: 22.0}
}

func (s *EarningsEventStrangle) Name() string { return "S47_Earnings_Event_Strangle" }

func (s *EarningsEventStrangle) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.EventRisk}
}

func (s *EarningsEventStrangle) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	// Skip if VIX already elevated (premium too expensive for gamma play).
	if ctx.Regime.VIXLevel > s.MaxVIX {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Enter 1–2 hours after open on EventRisk days.
	if mins < calendar.MarketOpen+60 || mins > 11*60+30 {
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

	entry := spot
	slDist := atr1h * 2.5
	if slDist < entry*s.MinSLDistancePct {
		slDist = entry * s.MinSLDistancePct
	}
	sl := entry + slDist

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
		Confidence: 0.55, Entry: entry, StopLoss: sl,
		TakeProfit: entry + slDist*2, TakeProfit2: entry + slDist*3,
		Instrument:  "STRANGLE",
		Strike:      atmStrike,
		Reason:      "EventRisk regime, VIX<22 — buy ATM strangle 3 days before earnings for gamma",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && absF(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// absF avoids importing math for a simple absolute value.
func absF(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}
