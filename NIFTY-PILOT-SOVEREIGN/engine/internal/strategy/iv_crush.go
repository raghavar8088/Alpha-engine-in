package strategy

import (
	"niftypilot/internal/regime"
)

// IVCrushThetaDecay (S3) sells weekly OTM options (short-strangle
// style) when IV percentile is elevated relative to realized vol —
// the classic Indian options-selling edge. This strategy emits a
// STRANGLE signal; margin (SPAN+exposure) and theta decay are modeled
// downstream by the sizing/execution layers, not here. Valid in
// RANGING regime (selling premium into a trend is the strategy this
// suite explicitly avoids).
//
// IV percentile proxy: this build approximates "IV percentile elevated"
// using India VIX as the IV proxy (VIX is the market's aggregate IV
// estimate for Nifty options) compared against its own 5-sample
// rolling history, since a full per-strike IV-percentile-of-252-days
// series requires a deeper historical IV store than the warmup buffers
// hold in v1. KNOWN LIMITATION: refine with a dedicated IV history
// store before relying on this for real strike selection.
type IVCrushThetaDecay struct {
	OTMOffsetPct     float64 // distance of short strikes from spot, e.g. 0.02 = 2%
	MinSLDistancePct float64
}

func NewIVCrushThetaDecay() *IVCrushThetaDecay {
	return &IVCrushThetaDecay{OTMOffsetPct: 0.02, MinSLDistancePct: 0.01}
}

func (s *IVCrushThetaDecay) Name() string { return "S3_IV_Crush_Theta_Decay" }

func (s *IVCrushThetaDecay) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging}
}

func (s *IVCrushThetaDecay) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 || chain.SpotPrice == 0 {
		return Signal{}, false
	}

	vixHist := ctx.Bundle.IndiaVIXHistory()
	var avgVix float64
	n := 0
	for _, v := range vixHist {
		if v > 0 {
			avgVix += v
			n++
		}
	}
	if n == 0 {
		return Signal{}, false
	}
	avgVix /= float64(n)
	currentVix := ctx.Regime.VIXLevel
	ivElevated := currentVix > avgVix*1.1 // current VIX 10%+ above its own short-run average

	if !ivElevated {
		return Signal{}, false
	}

	spot := chain.SpotPrice
	callStrike := spot * (1 + s.OTMOffsetPct)
	putStrike := spot * (1 - s.OTMOffsetPct)
	// SL on a short strangle is defined as the underlying breaching either
	// short strike by the minimum distance buffer; TP is the premium
	// collected decaying toward zero (modeled by execution layer, not here).
	width := callStrike - putStrike

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.5, Entry: spot,
		StopLoss:   callStrike, // breach of either wing triggers SL management
		TakeProfit: spot,       // target: spot pinned inside the strangle through theta decay
		TakeProfit2: spot,
		Instrument: "STRANGLE", Strike: callStrike, // CE leg strike; PE leg = putStrike (see Reason)
		Reason: "IV elevated vs own 5-sample avg, RANGING regime, selling OTM strangle for theta decay",
		GeneratedAt: ctx.Now,
	}
	if width <= 0 {
		return Signal{}, false
	}
	// Strangle signals are exempt from the directional 2:1 R:R geometry
	// check (premium-selling has inverted risk geometry: small consistent
	// gains, capped occasional larger losses bounded by the risk engine's
	// margin-breach circuit breaker) but MUST still pass a minimum
	// distance check so wings are not placed inside normal noise.
	if s.OTMOffsetPct < s.MinSLDistancePct {
		return Signal{}, false
	}
	return sig, true
}
