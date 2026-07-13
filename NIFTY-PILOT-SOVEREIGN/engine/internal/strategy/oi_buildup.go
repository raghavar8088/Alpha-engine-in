package strategy

import (
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// OIBuildupDirectional (S6) classifies the dominant open-interest
// pattern at the ATM strike — long buildup (price up + OI up), short
// buildup (price down + OI up), or short covering (price up + OI down)
// — and trades the dominant pattern. Equivalent to the BTC engine's S9
// OI Divergence strategy, adapted for per-strike options OI. Valid in
// TRENDING regimes.
type OIBuildupDirectional struct {
	MinSLDistancePct float64
}

func NewOIBuildupDirectional() *OIBuildupDirectional {
	return &OIBuildupDirectional{MinSLDistancePct: 0.003}
}

func (s *OIBuildupDirectional) Name() string { return "S6_OI_Buildup_Directional" }

func (s *OIBuildupDirectional) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *OIBuildupDirectional) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 || chain.SpotPrice == 0 {
		return Signal{}, false
	}

	atmFuturesStrike := nearestStrike(chain, chain.SpotPrice)
	var ceOIChange, peOIChange int64
	for _, k := range chain.Strikes {
		if k.Strike != atmFuturesStrike {
			continue
		}
		if k.OptionType == "CE" {
			ceOIChange = k.OIChange
		} else if k.OptionType == "PE" {
			peOIChange = k.OIChange
		}
	}

	c5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(c5m) < 5 {
		return Signal{}, false
	}
	atr := indicators.ATR(c5m, 14)
	if atr == 0 {
		return Signal{}, false
	}
	last := c5m[len(c5m)-1]
	prev := c5m[len(c5m)-2]
	priceUp := last.Close > prev.Close

	// Long buildup: price up + (call writing falls / put writing rises is
	// noisy at single-strike level) -- use futures-style proxy: price up
	// with rising OI on the put side at ATM (put writers adding shorts,
	// bullish) classifies as long buildup; price down with rising call OI
	// at ATM (call writers adding shorts, bearish) classifies as short buildup.
	longBuildup := priceUp && peOIChange > 0 && peOIChange > ceOIChange
	shortBuildup := !priceUp && ceOIChange > 0 && ceOIChange > peOIChange

	switch {
	case longBuildup:
		entry := last.Close
		sl := entry - 1.5*atr
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument: "CE", Strike: atmFuturesStrike,
			Reason: "long buildup: price up + ATM put OI addition exceeding call OI addition",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case shortBuildup:
		entry := last.Close
		sl := entry + 1.5*atr
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument: "PE", Strike: atmFuturesStrike,
			Reason: "short buildup: price down + ATM call OI addition exceeding put OI addition",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// nearestStrike returns the strike in the chain closest to spot.
func nearestStrike(chain marketdata.OptionChainSnapshot, spot float64) float64 {
	var best float64
	bestDist := -1.0
	for _, k := range chain.Strikes {
		d := abs(k.Strike - spot)
		if bestDist < 0 || d < bestDist {
			bestDist = d
			best = k.Strike
		}
	}
	return best
}
