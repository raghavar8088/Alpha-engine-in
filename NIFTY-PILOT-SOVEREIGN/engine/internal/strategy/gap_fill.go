package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// GapFillOpening (S7) fades an opening gap (vs previous close) beyond a
// threshold when the first 15 minutes show no strong follow-through in
// the gap direction. Valid in RANGING regime.
type GapFillOpening struct {
	MinGapPct        float64
	MinSLDistancePct float64
}

func NewGapFillOpening() *GapFillOpening {
	return &GapFillOpening{MinGapPct: 0.004, MinSLDistancePct: 0.0025}
}

func (s *GapFillOpening) Name() string { return "S7_Gap_Fill_Opening" }

func (s *GapFillOpening) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging}
}

func (s *GapFillOpening) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > calendar.MarketOpen+30 {
		return Signal{}, false // only evaluate in the 09:30-09:45 window
	}

	prevClose := ctx.Bundle.PrevClose(ctx.Underlying)
	if prevClose == 0 {
		return Signal{}, false
	}
	c1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(c1m) < 16 {
		return Signal{}, false
	}
	atr := indicators.ATR(c1m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	openCandle := c1m[0]
	for _, c := range c1m {
		ci := c.Time.In(calendar.IST)
		if ci.Hour()*60+ci.Minute() == calendar.MarketOpen {
			openCandle = c
			break
		}
	}
	gapPct := (openCandle.Open - prevClose) / prevClose
	last := c1m[len(c1m)-1]
	followThrough := abs((last.Close - openCandle.Open) / openCandle.Open)

	switch {
	case gapPct > s.MinGapPct && followThrough < s.MinGapPct*0.5:
		// Gapped up, no follow-through -> fade down toward prev close.
		entry := last.Close
		sl := entry + atr
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		target := prevClose
		if entry-target < 2*risk {
			target = entry - 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.5, Entry: entry, StopLoss: sl,
			TakeProfit: target, TakeProfit2: prevClose,
			Instrument: "PE", Reason: "opening gap-up with no follow-through, fading toward prev close",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case gapPct < -s.MinGapPct && followThrough < s.MinGapPct*0.5:
		entry := last.Close
		sl := entry - atr
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		target := prevClose
		if target-entry < 2*risk {
			target = entry + 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.5, Entry: entry, StopLoss: sl,
			TakeProfit: target, TakeProfit2: prevClose,
			Instrument: "CE", Reason: "opening gap-down with no follow-through, fading toward prev close",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}
