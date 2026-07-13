package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// MaxPainMagnet (S5) is EXPIRY_DAY specific: price tends to gravitate
// toward the Max Pain strike near expiry as option writers' hedging
// flows dominate. Fades moves away from Max Pain in the final 2 hours
// of expiry day (13:30-15:30 IST).
type MaxPainMagnet struct {
	MinSLDistancePct float64
}

func NewMaxPainMagnet() *MaxPainMagnet {
	return &MaxPainMagnet{MinSLDistancePct: 0.002}
}

func (s *MaxPainMagnet) Name() string { return "S5_Max_Pain_Magnet" }

func (s *MaxPainMagnet) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.ExpiryDay}
}

func (s *MaxPainMagnet) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < 13*60+30 || mins >= calendar.MarketClose {
		return Signal{}, false // only the final 2 hours of expiry day
	}

	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 || chain.SpotPrice == 0 {
		return Signal{}, false
	}
	maxPain := chain.MaxPain()
	if maxPain == 0 {
		return Signal{}, false
	}

	c5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(c5m) < 5 {
		return Signal{}, false
	}
	atr := indicators.ATR(c5m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	spot := chain.SpotPrice
	deviation := spot - maxPain
	// Require a meaningful deviation (>0.5 ATR) before fading toward Max Pain.
	if abs(deviation) < 0.5*atr {
		return Signal{}, false
	}

	switch {
	case deviation > 0:
		// Spot above Max Pain -> fade short toward Max Pain.
		entry := spot
		sl := entry + atr
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		target := maxPain
		if entry-target < 2*risk {
			target = entry - 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.5, Entry: entry, StopLoss: sl,
			TakeProfit: target, TakeProfit2: maxPain,
			Instrument: "PE", Strike: maxPain,
			Reason: "expiry day, spot above Max Pain strike, fading toward magnet in final 2h",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	default:
		entry := spot
		sl := entry - atr
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		target := maxPain
		if target-entry < 2*risk {
			target = entry + 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.5, Entry: entry, StopLoss: sl,
			TakeProfit: target, TakeProfit2: maxPain,
			Instrument: "CE", Strike: maxPain,
			Reason: "expiry day, spot below Max Pain strike, fading toward magnet in final 2h",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
}
