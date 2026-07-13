package strategy

import (
	"niftypilot/internal/regime"
)

// EventVolatilityFade (S9) sells premium immediately after a scheduled
// macro event (RBI policy, Union Budget) when the pre-event IV spike
// was not matched by an equivalently large actual price move — the
// classic post-event IV crush trade. Valid ONLY in EVENT_RISK regime,
// and only triggers once the event's immediate volatility has been
// observed (i.e. on the event day itself, not the pre-event day).
type EventVolatilityFade struct {
	OTMOffsetPct     float64
	MinSLDistancePct float64
	IVSpikeThreshold float64 // VIX level above which we consider IV "spiked"
}

func NewEventVolatilityFade() *EventVolatilityFade {
	return &EventVolatilityFade{OTMOffsetPct: 0.025, MinSLDistancePct: 0.01, IVSpikeThreshold: 17}
}

func (s *EventVolatilityFade) Name() string { return "S9_Event_Volatility_Fade" }

func (s *EventVolatilityFade) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.EventRisk}
}

func (s *EventVolatilityFade) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	if ctx.Regime.VIXLevel < s.IVSpikeThreshold {
		return Signal{}, false // IV has not spiked enough to be worth fading
	}

	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 || chain.SpotPrice == 0 {
		return Signal{}, false
	}

	c5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(c5m) < 6 {
		return Signal{}, false
	}
	// Realized move over the last 6 5m bars (30 min), compared against
	// the IV-implied expected move proxy (VIX-derived daily sigma).
	first := c5m[len(c5m)-6]
	last := c5m[len(c5m)-1]
	realizedMovePct := abs((last.Close - first.Close) / first.Close)

	// Approximate daily expected move from VIX: VIX is an annualized %,
	// daily expected move ~= VIX/100 * spot / sqrt(252).
	expectedDailyMovePct := (ctx.Regime.VIXLevel / 100.0) / 15.87 // sqrt(252) ~= 15.87

	ivOverpricedVsRealized := realizedMovePct < expectedDailyMovePct*0.5

	if !ivOverpricedVsRealized {
		return Signal{}, false
	}

	spot := chain.SpotPrice
	callStrike := spot * (1 + s.OTMOffsetPct)
	putStrike := spot * (1 - s.OTMOffsetPct)
	if callStrike-putStrike <= 0 {
		return Signal{}, false
	}

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.5, Entry: spot,
		StopLoss:   callStrike,
		TakeProfit: spot,
		TakeProfit2: spot,
		Instrument: "STRANGLE", Strike: callStrike,
		Reason: "post-event IV spike not matched by realized move, selling for IV crush",
		GeneratedAt: ctx.Now,
	}
	return sig, true
}
