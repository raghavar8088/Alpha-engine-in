package strategy

import (
	"niftypilot/internal/indicators"
	"niftypilot/internal/regime"
)

// EMARibbonTrendRider (S8) is a direct port of the BTC engine's S1:
// multi-EMA alignment (9/21/50) on the 15m timeframe with a 1h bias
// confirmation filter. Valid only in TRENDING regimes.
type EMARibbonTrendRider struct {
	MinSLDistancePct float64
}

func NewEMARibbonTrendRider() *EMARibbonTrendRider {
	return &EMARibbonTrendRider{MinSLDistancePct: 0.003}
}

func (s *EMARibbonTrendRider) Name() string { return "S8_EMA_Ribbon_Trend_Rider" }

func (s *EMARibbonTrendRider) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *EMARibbonTrendRider) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}

	c15 := ctx.Bundle.Candles(ctx.Underlying, "15m")
	c1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(c15) < 60 || len(c1h) < 60 {
		return Signal{}, false
	}
	closes15 := closesOf(c15)
	closes1h := closesOf(c1h)

	ema9 := indicators.LastEMA(closes15, 9)
	ema21 := indicators.LastEMA(closes15, 21)
	ema50 := indicators.LastEMA(closes15, 50)
	atr := indicators.ATR(c15, 14)
	if ema9 == 0 || ema21 == 0 || ema50 == 0 || atr == 0 {
		return Signal{}, false
	}

	bias1hEMA50 := indicators.LastEMA(closes1h, 50)
	last := c15[len(c15)-1]

	bullAligned := ema9 > ema21 && ema21 > ema50 && last.Close > bias1hEMA50
	bearAligned := ema9 < ema21 && ema21 < ema50 && last.Close < bias1hEMA50

	switch {
	case bullAligned:
		entry := last.Close
		sl := entry - 1.5*atr
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.6, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3.5*risk,
			Instrument: "CE", Reason: "EMA9>21>50 aligned bullish on 15m, confirmed by 1h bias",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case bearAligned:
		entry := last.Close
		sl := entry + 1.5*atr
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.6, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3.5*risk,
			Instrument: "PE", Reason: "EMA9<21<50 aligned bearish on 15m, confirmed by 1h bias",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}
