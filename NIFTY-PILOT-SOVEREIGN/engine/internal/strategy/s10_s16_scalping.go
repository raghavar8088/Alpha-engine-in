// S10–S16: Scalping strategies (1m–5m timeframes) for NSE index futures
// and individual stock futures. All follow the exact Strategy interface
// defined in strategy.go; no modifications to S1–S9 or core architecture.
//
// VERIFY flags are India-specific assumptions that need re-confirmation
// against current NSE/SEBI circulars before live use.
package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// ─────────────────────────────────────────────────────────────────────────────
// S10 — Tick_Scalp_Bid_Ask_Compression
// Instrument : Nifty 50 / Bank Nifty spot futures
// Timeframe  : 1m candles (spread compression detected vs ATR)
// Win target : 60%+   Holding: 2–5 minutes
// VERIFY     : NSE tick-level bid/ask availability via AngelOne SmartWebSocket
// ─────────────────────────────────────────────────────────────────────────────

type TickScalpBidAskCompression struct {
	MinSLDistancePct float64
}

func NewTickScalpBidAskCompression() *TickScalpBidAskCompression {
	return &TickScalpBidAskCompression{MinSLDistancePct: 0.002}
}

func (s *TickScalpBidAskCompression) Name() string {
	return "S10_Tick_Scalp_Bid_Ask_Compression"
}

func (s *TickScalpBidAskCompression) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *TickScalpBidAskCompression) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	// Block expiry/high-vol: theta noise invalidates micro-structure signal.
	if ctx.Regime.Regime == regime.ExpiryDay || ctx.Regime.Regime == regime.HighVol {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(candles1m) < 20 {
		return Signal{}, false
	}
	atr5 := indicators.ATR(candles1m, 5)
	if atr5 == 0 {
		return Signal{}, false
	}

	// Spread proxy: use ATM option chain bid/ask if available.
	// STUB: real implementation needs tick-level bid/ask feed.
	// VERIFY: wire actual bid/ask from AngelOne SmartWebSocket v2.
	spot := ctx.Bundle.Spot(ctx.Underlying)
	last := candles1m[len(candles1m)-1]
	if spot == 0 {
		spot = last.Close
	}
	var atmSpread float64
	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	for _, sd := range chain.Strikes {
		if abs(sd.Strike-spot) < 100 && sd.OptionType == "CE" && sd.AskPrice > 0 {
			atmSpread = sd.AskPrice - sd.BidPrice
			break
		}
	}
	// Fallback to high-low range as proxy when chain unavailable.
	if atmSpread == 0 {
		atmSpread = last.High - last.Low
	}
	if atmSpread >= 0.5*atr5 {
		return Signal{}, false
	}

	// Order-flow direction from last 3 candle bodies.
	n := len(candles1m)
	if n < 4 {
		return Signal{}, false
	}
	bullCount, bearCount := 0, 0
	for _, c := range candles1m[n-3:] {
		if c.Close > c.Open {
			bullCount++
		} else if c.Close < c.Open {
			bearCount++
		}
	}

	slDist := 1.5 * atr5 * 0.5
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case bullCount >= 2:
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.6, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "Bid/ask compression <0.5×ATR5 + 3-tick bullish order flow",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case bearCount >= 2:
		entry := last.Close
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.6, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "Bid/ask compression <0.5×ATR5 + 3-tick bearish order flow",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S11 — Pullback_Scalp_VWAP_Micro
// Instrument : Bank Nifty spot futures
// Timeframe  : 1m candles + 5m VWAP context
// Win target : 58%+   Holding: 3–8 minutes
// VERIFY     : Bank Nifty lot sizes and intraday spread profile
// ─────────────────────────────────────────────────────────────────────────────

type PullbackScalpVWAPMicro struct {
	MinSLDistancePct float64
}

func NewPullbackScalpVWAPMicro() *PullbackScalpVWAPMicro {
	return &PullbackScalpVWAPMicro{MinSLDistancePct: 0.0025}
}

func (s *PullbackScalpVWAPMicro) Name() string { return "S11_Pullback_Scalp_VWAP_Micro" }

func (s *PullbackScalpVWAPMicro) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *PullbackScalpVWAPMicro) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles1m) < 20 || len(candles5m) < 20 {
		return Signal{}, false
	}

	// Session candles only for VWAP (09:15 IST onwards).
	sess5m := make([]marketdata.Candle, 0, len(candles5m))
	for _, c := range candles5m {
		ci := c.Time.In(calendar.IST)
		if ci.Hour()*60+ci.Minute() >= calendar.MarketOpen {
			sess5m = append(sess5m, c)
		}
	}
	if len(sess5m) < 3 {
		return Signal{}, false
	}
	vwap5m := indicators.VWAP(sess5m)
	atr1m := indicators.ATR(candles1m, 14)
	if vwap5m == 0 || atr1m == 0 {
		return Signal{}, false
	}

	last := candles1m[len(candles1m)-1]
	closes1m := closesOf(candles1m)
	rsi1m := indicators.RSI(closes1m, 14)
	avgVol := indicators.AvgVolume(candles1m, 20)
	nearVWAP := abs(last.Close-vwap5m) <= 0.5*atr1m
	volSpike := last.Volume > 1.5*avgVol

	switch {
	case ctx.Regime.Regime == regime.TrendingBull && nearVWAP && rsi1m < 35 && volSpike:
		entry := last.Close
		sl := last.Low - 0.75*atr1m
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.58, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "1m pullback to 5m VWAP, RSI oversold, volume spike — bull regime bounce",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case ctx.Regime.Regime == regime.TrendingBear && nearVWAP && rsi1m > 65 && volSpike:
		entry := last.Close
		sl := last.High + 0.75*atr1m
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.58, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "1m pullback to 5m VWAP, RSI overbought, volume spike — bear regime fade",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S12 — Volume_Spike_Scalp_Order_Flow
// Instrument : NSE stock futures (top 20 liquid equities)
// Timeframe  : 1m candles
// Win target : 52%+   Holding: 2–6 minutes
// VERIFY     : Stock futures lot sizes; >1,000 contracts/day volume
// ─────────────────────────────────────────────────────────────────────────────

type VolumeSpikeScalpOrderFlow struct {
	MinSLDistancePct float64
	VolMultiplier    float64
}

func NewVolumeSpikeScalpOrderFlow() *VolumeSpikeScalpOrderFlow {
	return &VolumeSpikeScalpOrderFlow{MinSLDistancePct: 0.002, VolMultiplier: 2.0}
}

func (s *VolumeSpikeScalpOrderFlow) Name() string { return "S12_Volume_Spike_Scalp_Order_Flow" }

func (s *VolumeSpikeScalpOrderFlow) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *VolumeSpikeScalpOrderFlow) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+30 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(candles1m) < 25 {
		return Signal{}, false
	}
	avgVol := indicators.AvgVolume(candles1m, 20)
	if avgVol == 0 {
		return Signal{}, false
	}
	last := candles1m[len(candles1m)-1]
	atr1m := indicators.ATR(candles1m, 14)
	if atr1m == 0 {
		return Signal{}, false
	}
	if last.Volume < s.VolMultiplier*avgVol {
		return Signal{}, false
	}

	// Multi-bar confirmation: 2 of last 3 candles above-avg volume.
	n := len(candles1m)
	aboveAvg := 0
	for _, c := range candles1m[n-3:] {
		if c.Volume > avgVol {
			aboveAvg++
		}
	}
	if aboveAvg < 2 {
		return Signal{}, false
	}

	slDist := 0.5 * atr1m
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	if last.Close > last.Open {
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 2.5*risk,
			Instrument:  "FUTURE",
			Reason:      "Volume spike >2×avg on bullish 1m candle, 2/3 bars confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	entry := last.Close
	sl := entry + slDist
	risk := sl - entry
	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.52, Entry: entry, StopLoss: sl,
		TakeProfit: entry - 2*risk, TakeProfit2: entry - 2.5*risk,
		Instrument:  "FUTURE",
		Reason:      "Volume spike >2×avg on bearish 1m candle, 2/3 bars confirm",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.IsValid(s.MinSLDistancePct)
}

// ─────────────────────────────────────────────────────────────────────────────
// S13 — EMA_Ribbon_Scalp_Fast
// Instrument : Index futures (Nifty/BankNifty — Midcap50 proxied)
// Timeframe  : 1m; EMA3/EMA5/EMA9 ribbon + MACD histogram
// Win target : 55%+   Holding: 3–10 minutes
// ─────────────────────────────────────────────────────────────────────────────

type EMARibbonScalpFast struct {
	MinSLDistancePct float64
}

func NewEMARibbonScalpFast() *EMARibbonScalpFast {
	return &EMARibbonScalpFast{MinSLDistancePct: 0.0025}
}

func (s *EMARibbonScalpFast) Name() string { return "S13_EMA_Ribbon_Scalp_Fast" }

func (s *EMARibbonScalpFast) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *EMARibbonScalpFast) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(candles1m) < 35 {
		return Signal{}, false
	}
	closes := closesOf(candles1m)
	ema3 := indicators.LastEMA(closes, 3)
	ema5 := indicators.LastEMA(closes, 5)
	ema9 := indicators.LastEMA(closes, 9)
	atr1m := indicators.ATR(candles1m, 14)
	macdHist := indicators.MACDHistogram(closes)
	if ema3 == 0 || ema5 == 0 || ema9 == 0 || atr1m == 0 {
		return Signal{}, false
	}

	last := candles1m[len(candles1m)-1]
	nearEMA3 := abs(last.Close-ema3) <= 0.5*atr1m

	switch {
	case ema3 > ema5 && ema5 > ema9 && nearEMA3 && macdHist > 0:
		entry := last.Close
		sl := ema3 - 0.8*atr1m
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "EMA3>5>9 bullish ribbon, MACD histogram positive, price near EMA3",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case ema3 < ema5 && ema5 < ema9 && nearEMA3 && macdHist < 0:
		entry := last.Close
		sl := ema3 + 0.8*atr1m
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "EMA3<5<9 bearish ribbon, MACD histogram negative, price near EMA3",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S14 — Breakout_Scalp_Support_Resistance
// Instrument : Stock futures (Nifty 50 constituents, high F&O volume)
// Timeframe  : 5m; micro S/R = 09:15–09:45 high/low
// Win target : 56%+   Holding: 5–15 minutes
// VERIFY     : Opening range hours after NSE pre-open auction rule changes
// ─────────────────────────────────────────────────────────────────────────────

type BreakoutScalpSupportResistance struct {
	MinSLDistancePct float64
}

func NewBreakoutScalpSupportResistance() *BreakoutScalpSupportResistance {
	return &BreakoutScalpSupportResistance{MinSLDistancePct: 0.003}
}

func (s *BreakoutScalpSupportResistance) Name() string {
	return "S14_Breakout_Scalp_Support_Resistance"
}

func (s *BreakoutScalpSupportResistance) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *BreakoutScalpSupportResistance) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 14*60+30 {
		return Signal{}, false
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 10 {
		return Signal{}, false
	}

	var orHigh, orLow float64
	orCount := 0
	for _, c := range candles5m {
		ci := c.Time.In(calendar.IST)
		ciMins := ci.Hour()*60 + ci.Minute()
		if ciMins >= calendar.MarketOpen && ciMins < calendar.MarketOpen+30 {
			if orCount == 0 || c.High > orHigh {
				orHigh = c.High
			}
			if orCount == 0 || c.Low < orLow {
				orLow = c.Low
			}
			orCount++
		}
	}
	if orCount == 0 {
		return Signal{}, false
	}

	atr5m := indicators.ATR(candles5m, 14)
	if atr5m == 0 {
		return Signal{}, false
	}
	last := candles5m[len(candles5m)-1]
	avgVol := indicators.AvgVolume(candles5m, 20)
	volConfirm := last.Volume > 1.5*avgVol

	switch {
	case last.Close > orHigh && volConfirm:
		entry := last.Close
		sl := orLow
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "5m close above 30m micro resistance with volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case last.Close < orLow && volConfirm:
		entry := last.Close
		sl := orHigh
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "5m close below 30m micro support with volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S15 — RSI_Divergence_Scalp
// Instrument : Stock futures (high-beta small-cap)
// Timeframe  : 5m candles; RSI divergence at extremes
// Win target : 50%+   Holding: 5–20 minutes
// VERIFY     : Small-cap F&O liquidity >1,000 contracts/day
// ─────────────────────────────────────────────────────────────────────────────

type RSIDivergenceScalp struct {
	MinSLDistancePct float64
	LookbackBars     int
}

func NewRSIDivergenceScalp() *RSIDivergenceScalp {
	return &RSIDivergenceScalp{MinSLDistancePct: 0.003, LookbackBars: 5}
}

func (s *RSIDivergenceScalp) Name() string { return "S15_RSI_Divergence_Scalp" }

func (s *RSIDivergenceScalp) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *RSIDivergenceScalp) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 14*60+30 {
		return Signal{}, false
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	lb := s.LookbackBars
	if len(candles5m) < lb+15 {
		return Signal{}, false
	}

	closes := closesOf(candles5m)
	rsiNow := indicators.RSI(closes, 14)
	rsiPrev := indicators.RSI(closes[:len(closes)-lb], 14)
	atr5m := indicators.ATR(candles5m, 14)
	if atr5m == 0 {
		return Signal{}, false
	}

	last := candles5m[len(candles5m)-1]
	prev := candles5m[len(candles5m)-1-lb]

	bullDiv := last.Low < prev.Low && rsiNow > rsiPrev && rsiNow < 35
	bearDiv := last.High > prev.High && rsiNow < rsiPrev && rsiNow > 65

	slDist := atr5m
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case bullDiv && ctx.Regime.Regime == regime.TrendingBear:
		entry := last.Close
		sl := last.Low - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 2.5*risk,
			Instrument:  "FUTURE",
			Reason:      "Bullish RSI divergence: price lower-low, RSI higher-low, RSI<35",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case bearDiv && ctx.Regime.Regime == regime.TrendingBull:
		entry := last.Close
		sl := last.High + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 2.5*risk,
			Instrument:  "FUTURE",
			Reason:      "Bearish RSI divergence: price higher-high, RSI lower-high, RSI>65",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S16 — ATR_Breakout_Scalp_Volatility
// Instrument : Nifty 50 / Bank Nifty spot futures
// Timeframe  : 5m candles; entry on >1.5×ATR5 move
// Win target : 54%+   Holding: 5–15 minutes
// VERIFY     : India VIX threshold vs current market structure
// ─────────────────────────────────────────────────────────────────────────────

type ATRBreakoutScalpVolatility struct {
	MinSLDistancePct  float64
	ATRMoveMultiplier float64
}

func NewATRBreakoutScalpVolatility() *ATRBreakoutScalpVolatility {
	return &ATRBreakoutScalpVolatility{MinSLDistancePct: 0.0025, ATRMoveMultiplier: 1.5}
}

func (s *ATRBreakoutScalpVolatility) Name() string { return "S16_ATR_Breakout_Scalp_Volatility" }

func (s *ATRBreakoutScalpVolatility) AllowedRegimes() []regime.Regime {
	// HIGH_VOL allowed: ATR breakouts valid when VIX > 20; AllowNewEntries governs.
	return []regime.Regime{regime.HighVol, regime.TrendingBull, regime.TrendingBear}
}

func (s *ATRBreakoutScalpVolatility) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 20 {
		return Signal{}, false
	}
	atr5 := indicators.ATR(candles5m, 5)
	if atr5 == 0 {
		return Signal{}, false
	}

	n := len(candles5m)
	last := candles5m[n-1]
	prev := candles5m[n-2]
	move := last.Close - prev.Close
	if abs(move) < s.ATRMoveMultiplier*atr5 {
		return Signal{}, false
	}

	if move > 0 {
		entry := last.Close
		sl := last.Low - 0.5*atr5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "5m candle >1.5×ATR5 above prev close — volatility breakout long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}

	entry := last.Close
	sl := last.High + 0.5*atr5
	if sl-entry < entry*s.MinSLDistancePct {
		sl = entry + entry*s.MinSLDistancePct
	}
	risk := sl - entry
	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.54, Entry: entry, StopLoss: sl,
		TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
		Instrument:  "FUTURE",
		Reason:      "5m candle >1.5×ATR5 below prev close — volatility breakout short",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.IsValid(s.MinSLDistancePct)
}
