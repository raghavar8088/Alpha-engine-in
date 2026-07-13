package strategy

import (
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// VWAPReversion (S2) fades extensions beyond 1.5x session ATR from the
// session VWAP, intended primarily for Bank Nifty (higher volatility
// needs wider bands than Nifty). Valid only in RANGING regime.
type VWAPReversion struct {
	ATRMultiplier    float64
	MinSLDistancePct float64
}

func NewVWAPReversion() *VWAPReversion {
	return &VWAPReversion{ATRMultiplier: 1.5, MinSLDistancePct: 0.0025}
}

func (s *VWAPReversion) Name() string { return "S2_VWAP_Reversion_BankNifty" }

func (s *VWAPReversion) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging}
}

func (s *VWAPReversion) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 30 {
		return Signal{}, false
	}

	// Session-only candles for VWAP (from today's 09:15 open).
	sessionCandles := sessionSlice(candles5m, ctx.Now)
	if len(sessionCandles) < 4 {
		return Signal{}, false
	}
	vwap := indicators.VWAP(sessionCandles)
	atr := indicators.ATR(candles5m, 14)
	if vwap == 0 || atr == 0 {
		return Signal{}, false
	}

	last := candles5m[len(candles5m)-1]
	deviation := last.Close - vwap
	band := s.ATRMultiplier * atr

	switch {
	case deviation > band:
		// Extended above VWAP -> fade short back toward VWAP.
		entry := last.Close
		sl := entry + atr*0.75
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: vwap, TakeProfit2: vwap - risk*0.5,
			Instrument: "PE", Reason: "extended >1.5xATR above session VWAP, fading to VWAP",
			GeneratedAt: ctx.Now,
		}
		if abs(sig.TakeProfit-entry) < 2*risk {
			return Signal{}, false // enforce 2:1 R:R even though TP target is VWAP
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case deviation < -band:
		entry := last.Close
		sl := entry - atr*0.75
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: vwap, TakeProfit2: vwap + risk*0.5,
			Instrument: "CE", Reason: "extended >1.5xATR below session VWAP, fading to VWAP",
			GeneratedAt: ctx.Now,
		}
		if abs(sig.TakeProfit-entry) < 2*risk {
			return Signal{}, false
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// sessionSlice returns candles from the current IST trading day's
// 09:15 open onward.
func sessionSlice(candles []marketdata.Candle, now time.Time) []marketdata.Candle {
	open := calendar.SessionOpenTime(now)
	var out []marketdata.Candle
	for _, c := range candles {
		if !c.Time.Before(open) {
			out = append(out, c)
		}
	}
	return out
}
