// S30–S36: Advanced scalping strategies (1m–5m timeframes).
// All follow the exact Strategy interface in strategy.go.
// No modifications to S1–S29, risk engine, or core architecture.
package strategy

import (
	"math"

	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// ─────────────────────────────────────────────────────────────────────────────
// S30 — SuperTrend_Scalper
// Instrument : FUTURE / CE / PE (direction-driven)
// Timeframe  : 2m (proxied via 1m candles, signal on every 2nd bar)
// Win target : 58%+  Holding: 2–5 minutes
// SuperTrend emulated: ATR(7)*3.0 bands on 1m bars.
// ─────────────────────────────────────────────────────────────────────────────

type SuperTrendScalper struct {
	MinSLDistancePct float64
	ATRPeriod        int
	ATRMult          float64
}

func NewSuperTrendScalper() *SuperTrendScalper {
	return &SuperTrendScalper{MinSLDistancePct: 0.002, ATRPeriod: 7, ATRMult: 3.0}
}

func (s *SuperTrendScalper) Name() string { return "S30_SuperTrend_Scalper" }

func (s *SuperTrendScalper) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *SuperTrendScalper) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	if ctx.Regime.Regime == regime.ExpiryDay || ctx.Regime.Regime == regime.HighVol {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	need := s.ATRPeriod + 5
	if len(candles1m) < need {
		return Signal{}, false
	}

	atr := indicators.ATR(candles1m, s.ATRPeriod)
	if atr == 0 {
		return Signal{}, false
	}

	n := len(candles1m)
	last := candles1m[n-1]
	prev := candles1m[n-2]

	// SuperTrend bands (upper = bearish band, lower = bullish band).
	upperBand := ((last.High + last.Low) / 2) + s.ATRMult*atr
	lowerBand := ((last.High + last.Low) / 2) - s.ATRMult*atr
	prevUpper := ((prev.High + prev.Low) / 2) + s.ATRMult*atr
	prevLower := ((prev.High + prev.Low) / 2) - s.ATRMult*atr

	// Crossover: price crosses above lower band = bullish; below upper band = bearish.
	bullCross := prev.Close < prevLower && last.Close > lowerBand
	bearCross := prev.Close > prevUpper && last.Close < upperBand

	// Volume confirmation.
	avgVol := indicators.AvgVolume(candles1m, 20)
	volConfirm := last.Volume > 1.5*avgVol

	slDist := atr * 0.5
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case bullCross && volConfirm:
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		instrument := "CE"
		if ctx.Regime.Regime == regime.TrendingBull {
			instrument = "FUTURE"
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.58, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  instrument,
			Reason:      "SuperTrend bullish crossover above lower band + volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case bearCross && volConfirm:
		entry := last.Close
		sl := entry + slDist
		risk := sl - entry
		instrument := "PE"
		if ctx.Regime.Regime == regime.TrendingBear {
			instrument = "FUTURE"
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.58, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  instrument,
			Reason:      "SuperTrend bearish crossover below upper band + volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S31 — VWAP_Band_Bounce
// Instrument : FUTURE (mean-reversion)
// Timeframe  : 3m (proxied via 1m candles); ±1.5σ VWAP band touch
// Win target : 56%+  Holding: 3min max
// ─────────────────────────────────────────────────────────────────────────────

type VWAPBandBounce struct {
	MinSLDistancePct float64
	BandSigma        float64
}

func NewVWAPBandBounce() *VWAPBandBounce {
	return &VWAPBandBounce{MinSLDistancePct: 0.0025, BandSigma: 1.5}
}

func (s *VWAPBandBounce) Name() string { return "S31_VWAP_Band_Bounce" }

func (s *VWAPBandBounce) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *VWAPBandBounce) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 14*60+30 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	// Collect session candles for VWAP.
	var sess []marketdata.Candle
	for _, c := range candles1m {
		ci := c.Time.In(calendar.IST)
		if ci.Hour()*60+ci.Minute() >= calendar.MarketOpen {
			sess = append(sess, c)
		}
	}
	if len(sess) < 20 {
		return Signal{}, false
	}

	vwap := indicators.VWAP(sess)
	if vwap == 0 {
		return Signal{}, false
	}

	// Compute σ of (close - vwap) over session bars.
	var sumSq float64
	for _, c := range sess {
		d := c.Close - vwap
		sumSq += d * d
	}
	sigma := math.Sqrt(sumSq / float64(len(sess)))
	if sigma == 0 {
		return Signal{}, false
	}

	upperBand := vwap + s.BandSigma*sigma
	lowerBand := vwap - s.BandSigma*sigma

	last := candles1m[len(candles1m)-1]
	closes := closesOf(candles1m)
	rsi := indicators.RSI(closes, 14)
	atr := indicators.ATR(candles1m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	slDist := atr * 0.75
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case last.Close <= lowerBand && rsi < 35:
		// Price at lower band, RSI divergence → long mean-reversion.
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: vwap,
			Instrument:  "FUTURE",
			Reason:      "Price at −1.5σ VWAP band, RSI<35 — mean-reversion long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case last.Close >= upperBand && rsi > 65:
		// Price at upper band, RSI divergence → short mean-reversion.
		entry := last.Close
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.56, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: vwap,
			Instrument:  "FUTURE",
			Reason:      "Price at +1.5σ VWAP band, RSI>65 — mean-reversion short",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S32 — Opening_15min_ORB_Futures
// Instrument : FUTURE (index futures, directional)
// Timeframe  : 15m; first 15min high/low breakout, 1.5×ATR target
// Win target : 58%+  Holding: 30–90 minutes
// ─────────────────────────────────────────────────────────────────────────────

type Opening15minORBFutures struct {
	MinSLDistancePct float64
}

func NewOpening15minORBFutures() *Opening15minORBFutures {
	return &Opening15minORBFutures{MinSLDistancePct: 0.003}
}

func (s *Opening15minORBFutures) Name() string { return "S32_Opening_15min_ORB_Futures" }

func (s *Opening15minORBFutures) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *Opening15minORBFutures) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Active window: 09:30–11:00 IST (after 15min OR is established).
	if mins < calendar.MarketOpen+15 || mins > 11*60 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(candles1m) < 20 {
		return Signal{}, false
	}

	// Build 15-minute opening range from session start.
	var orHigh, orLow float64
	orCount := 0
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
			orCount++
		}
	}
	if orCount == 0 {
		return Signal{}, false
	}

	atr := indicators.ATR(candles1m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	last := candles1m[len(candles1m)-1]
	avgVol := indicators.AvgVolume(candles1m, 20)
	volConfirm := last.Volume > 1.5*avgVol

	switch {
	case last.Close > orHigh && volConfirm:
		entry := last.Close
		sl := orLow
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		tp := entry + 1.5*atr
		if tp < entry+2*risk {
			tp = entry + 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.58, Entry: entry, StopLoss: sl,
			TakeProfit: tp, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "15min ORB high breakout + volume confirm, 1.5×ATR target",
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
		tp := entry - 1.5*atr
		if tp > entry-2*risk {
			tp = entry - 2*risk
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.58, Entry: entry, StopLoss: sl,
			TakeProfit: tp, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "15min ORB low breakdown + volume confirm, 1.5×ATR target",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S33 — Tick_Velocity_Scalp
// Instrument : FUTURE
// Timeframe  : 1m; detects rapid close velocity > 2σ vs 20-bar history
// Win target : 54%+  Holding: 1–3 minutes
// ─────────────────────────────────────────────────────────────────────────────

type TickVelocityScalp struct {
	MinSLDistancePct float64
	LookbackBars     int
	VelocitySigmas   float64
}

func NewTickVelocityScalp() *TickVelocityScalp {
	return &TickVelocityScalp{MinSLDistancePct: 0.002, LookbackBars: 20, VelocitySigmas: 2.0}
}

func (s *TickVelocityScalp) Name() string { return "S33_Tick_Velocity_Scalp" }

func (s *TickVelocityScalp) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.HighVol}
}

func (s *TickVelocityScalp) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	need := s.LookbackBars + 2
	if len(candles1m) < need {
		return Signal{}, false
	}

	// Compute 1m close velocities over lookback.
	n := len(candles1m)
	vels := make([]float64, s.LookbackBars)
	for i := 0; i < s.LookbackBars; i++ {
		idx := n - 2 - i
		if idx < 1 {
			break
		}
		vels[i] = candles1m[idx].Close - candles1m[idx-1].Close
	}
	var mean, sumSq float64
	for _, v := range vels {
		mean += v
	}
	mean /= float64(len(vels))
	for _, v := range vels {
		d := v - mean
		sumSq += d * d
	}
	sigma := math.Sqrt(sumSq / float64(len(vels)))
	if sigma == 0 {
		return Signal{}, false
	}

	last := candles1m[n-1]
	prev := candles1m[n-2]
	curVel := last.Close - prev.Close
	zscore := curVel / sigma

	atr := indicators.ATR(candles1m, 14)
	if atr == 0 {
		return Signal{}, false
	}
	slDist := 0.5 * atr
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case zscore > s.VelocitySigmas:
		// Strong upward velocity — continuation or mean-reversion depending on regime.
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 2.5*risk,
			Instrument:  "FUTURE",
			Reason:      "1m close velocity +2σ spike — momentum continuation long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case zscore < -s.VelocitySigmas:
		entry := last.Close
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 2.5*risk,
			Instrument:  "FUTURE",
			Reason:      "1m close velocity −2σ spike — momentum continuation short",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S34 — Delta_Weighted_Options_Scalp
// Instrument : CE / PE (directional options scalp)
// Timeframe  : 5m; PCR flip + total OI change > 5% → directional scalp
// Win target : 52%+  Holding: up to 5min implied
// ─────────────────────────────────────────────────────────────────────────────

type DeltaWeightedOptionsScalp struct {
	MinSLDistancePct float64
	OIChangePct      float64
}

func NewDeltaWeightedOptionsScalp() *DeltaWeightedOptionsScalp {
	return &DeltaWeightedOptionsScalp{MinSLDistancePct: 0.003, OIChangePct: 0.05}
}

func (s *DeltaWeightedOptionsScalp) Name() string { return "S34_Delta_Weighted_Options_Scalp" }

func (s *DeltaWeightedOptionsScalp) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *DeltaWeightedOptionsScalp) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 14*60+30 {
		return Signal{}, false
	}

	chain := ctx.Bundle.OptionChain(ctx.Underlying)
	if len(chain.Strikes) == 0 {
		return Signal{}, false
	}

	// PCR from current chain.
	pcr := chain.PCR()
	if pcr == 0 {
		return Signal{}, false
	}

	// Total absolute OI change in the last bar.
	var totalOI, totalOIChange int64
	for _, sd := range chain.Strikes {
		if sd.OI > 0 {
			totalOI += sd.OI
		}
		if sd.OIChange > 0 {
			totalOIChange += sd.OIChange
		} else {
			totalOIChange -= sd.OIChange
		}
	}
	if totalOI == 0 {
		return Signal{}, false
	}
	oiChangeFrac := float64(totalOIChange) / float64(totalOI)
	if oiChangeFrac < s.OIChangePct {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		return Signal{}, false
	}
	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 10 {
		return Signal{}, false
	}
	atr := indicators.ATR(candles5m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	strike := roundToStrike(spot, stepSize)

	slDist := atr
	if slDist < spot*s.MinSLDistancePct {
		slDist = spot * s.MinSLDistancePct
	}

	switch {
	case pcr < 0.8:
		// Low PCR = call-heavy = bullish → CE scalp.
		entry := spot
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "CE",
			Strike:      strike,
			Reason:      "PCR<0.8 call-heavy + OI change >5% → CE directional scalp",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case pcr > 1.2:
		// High PCR = put-heavy = bearish → PE scalp.
		entry := spot
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "PE",
			Strike:      strike,
			Reason:      "PCR>1.2 put-heavy + OI change >5% → PE directional scalp",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S35 — EMA9_21_ZeroLag_Scalp
// Instrument : FUTURE
// Timeframe  : 3m (proxied via 1m); EMA9/EMA21 crossover, ADX>25 filter
// Win target : 55%+  Holding: 3–10 minutes
// ─────────────────────────────────────────────────────────────────────────────

type EMA921ZeroLagScalp struct {
	MinSLDistancePct float64
	ADXThreshold     float64
}

func NewEMA921ZeroLagScalp() *EMA921ZeroLagScalp {
	return &EMA921ZeroLagScalp{MinSLDistancePct: 0.003, ADXThreshold: 25.0}
}

func (s *EMA921ZeroLagScalp) Name() string { return "S35_EMA9_21_ZeroLag_Scalp" }

func (s *EMA921ZeroLagScalp) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *EMA921ZeroLagScalp) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	if len(candles1m) < 30 {
		return Signal{}, false
	}

	closes := closesOf(candles1m)
	// Current and previous EMAs for crossover detection.
	ema9Now := indicators.LastEMA(closes, 9)
	ema21Now := indicators.LastEMA(closes, 21)
	ema9Prev := indicators.LastEMA(closes[:len(closes)-1], 9)
	ema21Prev := indicators.LastEMA(closes[:len(closes)-1], 21)

	adx := indicators.ADX(candles1m, 14)
	if adx < s.ADXThreshold {
		return Signal{}, false
	}

	atr := indicators.ATR(candles1m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	last := candles1m[len(candles1m)-1]
	slDist := last.Close * s.MinSLDistancePct
	if slDist < 0.3*atr {
		slDist = 0.3 * atr
	}

	bullCross := ema9Prev <= ema21Prev && ema9Now > ema21Now
	bearCross := ema9Prev >= ema21Prev && ema9Now < ema21Now

	switch {
	case bullCross:
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "EMA9 crossed above EMA21, ADX>25 — zero-lag scalp long",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case bearCross:
		entry := last.Close
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "EMA9 crossed below EMA21, ADX>25 — zero-lag scalp short",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S36 — ATR_Channel_Breakout_Scalp
// Instrument : FUTURE
// Timeframe  : 1m; 1m ATR channel high/low breakout, volume >1.5× avg
// Win target : 54%+  Holding: 2–8 minutes
// ─────────────────────────────────────────────────────────────────────────────

type ATRChannelBreakoutScalp struct {
	MinSLDistancePct float64
	ChannelBars      int
	ATRMult          float64
}

func NewATRChannelBreakoutScalp() *ATRChannelBreakoutScalp {
	return &ATRChannelBreakoutScalp{MinSLDistancePct: 0.002, ChannelBars: 20, ATRMult: 1.0}
}

func (s *ATRChannelBreakoutScalp) Name() string { return "S36_ATR_Channel_Breakout_Scalp" }

func (s *ATRChannelBreakoutScalp) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.HighVol}
}

func (s *ATRChannelBreakoutScalp) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+15 || mins > 14*60+45 {
		return Signal{}, false
	}

	candles1m := ctx.Bundle.Candles(ctx.Underlying, "1m")
	need := s.ChannelBars + 5
	if len(candles1m) < need {
		return Signal{}, false
	}

	atr := indicators.ATR(candles1m, 14)
	if atr == 0 {
		return Signal{}, false
	}

	n := len(candles1m)
	// Channel: max/min close over last ChannelBars excluding the current bar.
	window := candles1m[n-1-s.ChannelBars : n-1]
	var chanHigh, chanLow float64
	for _, c := range window {
		if chanHigh == 0 || c.Close > chanHigh {
			chanHigh = c.Close
		}
		if chanLow == 0 || c.Close < chanLow {
			chanLow = c.Close
		}
	}

	channelHigh := chanHigh + s.ATRMult*atr
	channelLow := chanLow - s.ATRMult*atr

	last := candles1m[n-1]
	avgVol := indicators.AvgVolume(candles1m, 20)
	volConfirm := last.Volume > 1.5*avgVol

	slDist := atr * 0.5
	if slDist < last.Close*s.MinSLDistancePct {
		slDist = last.Close * s.MinSLDistancePct
	}

	switch {
	case last.Close > channelHigh && volConfirm:
		entry := last.Close
		sl := entry - slDist
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "1m close breaks ATR channel high, volume >1.5× avg — continuation scalp",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	case last.Close < channelLow && volConfirm:
		entry := last.Close
		sl := entry + slDist
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "1m close breaks ATR channel low, volume >1.5× avg — continuation scalp",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}
