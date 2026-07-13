package strategy

import (
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// PCRExtremeReversal (S4) takes a contrarian entry when the options
// Put-Call Ratio (OI-based) reaches an extreme (>1.5 oversold-puts /
// <0.5 overbought-calls) combined with price confirmation (a reversal
// candle against the prevailing short-term move). Valid in RANGING and
// TRENDING regimes — PCR extremes are a sentiment exhaustion signal
// that work across both.
type PCRExtremeReversal struct {
	HighPCR          float64
	LowPCR           float64
	MinSLDistancePct float64
}

func NewPCRExtremeReversal() *PCRExtremeReversal {
	return &PCRExtremeReversal{HighPCR: 1.5, LowPCR: 0.5, MinSLDistancePct: 0.003}
}

func (s *PCRExtremeReversal) Name() string { return "S4_PCR_Extreme_Reversal" }

func (s *PCRExtremeReversal) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *PCRExtremeReversal) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 {
		return Signal{}, false
	}
	pcr := chain.PCR()

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 5 {
		return Signal{}, false
	}
	atr := indicators.ATR(candles5m, 14)
	if atr == 0 {
		return Signal{}, false
	}
	last := candles5m[len(candles5m)-1]
	prev := candles5m[len(candles5m)-2]
	bullishReversal := last.Close > last.Open && last.Close > prev.High
	bearishReversal := last.Close < last.Open && last.Close < prev.Low

	switch {
	case pcr > s.HighPCR && bullishReversal:
		// Extreme put buildup (bearish positioning) + bullish reversal -> contrarian long.
		entry := last.Close
		sl := entry - atr
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument: "CE", Reason: "PCR extreme (puts crowded) + bullish reversal confirmation",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case pcr < s.LowPCR && bearishReversal:
		// Extreme call buildup (bullish positioning) + bearish reversal -> contrarian short.
		entry := last.Close
		sl := entry + atr
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument: "PE", Reason: "PCR extreme (calls crowded) + bearish reversal confirmation",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}
