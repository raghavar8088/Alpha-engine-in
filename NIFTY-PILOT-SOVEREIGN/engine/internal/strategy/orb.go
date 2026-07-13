package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// ORBBreakout (S1) trades the breakout of the first 15-minute opening
// range (09:15-09:30 IST), confirmed by a volume surge and India VIX
// not spiking on the breakout bar. Valid only in TRENDING regimes.
type ORBBreakout struct {
	MinSLDistancePct float64 // e.g. 0.003 (0.3%) of entry
}

func NewORBBreakout() *ORBBreakout {
	return &ORBBreakout{MinSLDistancePct: 0.003}
}

func (s *ORBBreakout) Name() string { return "S1_ORB_Nifty_Breakout" }

func (s *ORBBreakout) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *ORBBreakout) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > calendar.MarketOpen+90 {
		return Signal{}, false // only act within 09:30-10:45 IST window
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(candles1m) < 20 {
		return Signal{}, false
	}

	// Isolate the opening-range candles (first 15 of the session).
	var orHigh, orLow float64
	orCount := 0
	var avgVol float64
	for _, c := range candles1m {
		ci := c.Time.In(calendar.IST)
		ciMins := ci.Hour()*60 + ci.Minute()
		if ciMins >= calendar.MarketOpen && ciMins < calendar.MarketOpen+15 {
			if orCount == 0 || c.High > orHigh {
				orHigh = c.High
			}
			if orCount == 0 || c.Low < orLow {
				orLow = c.Low
			}
			avgVol += c.Volume
			orCount++
		}
	}
	if orCount == 0 {
		return Signal{}, false
	}
	avgVol /= float64(orCount)

	last := candles1m[len(candles1m)-1]
	atr := indicators.ATR(candles1m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	volumeSurge := last.Volume > avgVol*1.5
	vixStable := ctx.Regime.VIXLevel < 18

	switch {
	case last.Close > orHigh && volumeSurge && vixStable:
		entry := last.Close
		sl := orLow
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.6, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument: "CE", Reason: "ORB breakout above opening range high with volume surge",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case last.Close < orLow && volumeSurge && vixStable:
		entry := last.Close
		sl := orHigh
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.6, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument: "PE", Reason: "ORB breakdown below opening range low with volume surge",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}
