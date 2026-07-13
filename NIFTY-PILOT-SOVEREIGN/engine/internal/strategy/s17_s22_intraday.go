// S17–S22: Intraday strategies (15m–1h timeframes).
// All follow the exact Strategy interface in strategy.go.
// No modifications to S1–S9, risk engine, or core architecture.
package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// ─────────────────────────────────────────────────────────────────────────────
// S17 — Opening_Range_Breakout_Intraday
// Instrument : Index futures or ATM options (Nifty / BankNifty)
// Timeframe  : 15m; opening range = 09:15–09:45 IST
// Win target : 56%+   Holding: 45–90 minutes
// VERIFY     : NSE circuit limits, pre-open auction rules post-2024
// ─────────────────────────────────────────────────────────────────────────────

type OpeningRangeBreakoutIntraday struct {
	MinSLDistancePct float64
	// OpenGapPct: minimum gap vs prev close to confirm a directional open.
	OpenGapPct float64
}

func NewOpeningRangeBreakoutIntraday() *OpeningRangeBreakoutIntraday {
	return &OpeningRangeBreakoutIntraday{MinSLDistancePct: 0.003, OpenGapPct: 0.005}
}

func (s *OpeningRangeBreakoutIntraday) Name() string {
	return "S17_Opening_Range_Breakout_Intraday"
}

func (s *OpeningRangeBreakoutIntraday) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *OpeningRangeBreakoutIntraday) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Active window: 09:45–11:30 IST.
	if mins < calendar.MarketOpen+30 || mins > 11*60+30 {
		return Signal{}, false
	}

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles15m) < 8 {
		return Signal{}, false
	}

	// Build 30-minute opening range from 09:15–09:45 IST (two 15m bars).
	var orHigh, orLow float64
	orCount := 0
	for _, c := range candles15m {
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

	atr15m := indicators.ATR(candles15m, 14)
	if atr15m == 0 {
		return Signal{}, false
	}

	prevClose := ctx.Bundle.PrevClose(ctx.Underlying)
	spot := ctx.Bundle.Spot(ctx.Underlying)
	last := candles15m[len(candles15m)-1]
	if spot == 0 {
		spot = last.Close
	}

	// Gap > 0.5% from prev close confirms directional open.
	gapUp := prevClose > 0 && (spot-prevClose)/prevClose > s.OpenGapPct
	gapDown := prevClose > 0 && (prevClose-spot)/prevClose > s.OpenGapPct

	switch {
	case (gapUp || ctx.Regime.Regime == regime.TrendingBull) && last.Close > orHigh:
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
			Instrument:  "CE",
			Reason:      "15m close above 30m ORB high, directional gap-up open confirmed",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case (gapDown || ctx.Regime.Regime == regime.TrendingBear) && last.Close < orLow:
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
			Instrument:  "PE",
			Reason:      "15m close below 30m ORB low, directional gap-down open confirmed",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S18 — VWAP_Mean_Reversion_Options_Straddle
// Instrument : ATM straddle (long call + long put) on BankNifty weekly options
// Timeframe  : 15m; triggered when price extends >1.5×ATR1h from VWAP
// Win target : 52%+   Holding: 1–4 hours
// VERIFY     : NSE weekly options chain depth, IV percentile data source
// ─────────────────────────────────────────────────────────────────────────────

type VWAPMeanReversionStraddle struct {
	MinSLDistancePct float64
	// ATRExtMult: price extension beyond this multiple of ATR1h triggers entry.
	ATRExtMult float64
	// IVPercentileMax: only buy straddles when IV is below this percentile.
	// VERIFY: replace with live IV rank data from option chain Greeks.
	IVPercentileMax float64
}

func NewVWAPMeanReversionStraddle() *VWAPMeanReversionStraddle {
	return &VWAPMeanReversionStraddle{
		MinSLDistancePct: 0.01, ATRExtMult: 1.5, IVPercentileMax: 50,
	}
}

func (s *VWAPMeanReversionStraddle) Name() string {
	return "S18_VWAP_Mean_Reversion_Options_Straddle"
}

func (s *VWAPMeanReversionStraddle) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *VWAPMeanReversionStraddle) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Only enter between 10:00–13:30 IST (not first 45m, not last 2h).
	if mins < 10*60 || mins > 13*60+30 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	if len(candles1h) < 5 || len(candles15m) < 10 {
		return Signal{}, false
	}

	// Session VWAP from 09:15 IST.
	sess15m := make([]marketdata.Candle, 0, len(candles15m))
	for _, c := range candles15m {
		ci := c.Time.In(calendar.IST)
		if ci.Hour()*60+ci.Minute() >= calendar.MarketOpen {
			sess15m = append(sess15m, c)
		}
	}
	if len(sess15m) < 3 {
		return Signal{}, false
	}
	vwap := indicators.VWAP(sess15m)
	atr1h := indicators.ATR(candles1h, 14)
	if vwap == 0 || atr1h == 0 {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	last15m := candles15m[len(candles15m)-1]
	if spot == 0 {
		spot = last15m.Close
	}

	ext := abs(spot - vwap)
	if ext < s.ATRExtMult*atr1h {
		return Signal{}, false
	}

	// IV check: use rolling VIX history as IV proxy.
	// VERIFY: replace with actual IV rank from option chain Greeks.
	vixHistory := ctx.Bundle.IndiaVIXHistory()
	var vixAvg float64
	for _, v := range vixHistory {
		vixAvg += v
	}
	vixAvg /= 5
	// If VIX is more than 20% above its 5-sample avg → IV elevated → skip straddle buy.
	if vixAvg > 0 && ctx.Regime.VIXLevel > vixAvg*1.20 {
		return Signal{}, false
	}

	// ATM strike.
	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	atmStrike := roundToStrike(spot, stepSize)

	// Straddle: long call + long put — STRANGLE instrument represents both legs.
	// SL at 1×ATR1h further from VWAP (thesis: mean reversion, not expansion).
	entry := spot
	sl := spot + s.ATRExtMult*atr1h // price moves further away = thesis broken
	if spot < vwap {
		sl = spot - s.ATRExtMult*atr1h
	}
	tp := vwap
	slDist := abs(entry - sl)
	if slDist < entry*s.MinSLDistancePct {
		slDist = entry * s.MinSLDistancePct
		if spot > vwap {
			sl = entry + slDist
		} else {
			sl = entry - slDist
		}
	}
	tpDist := abs(tp - entry)
	if tpDist < 2*slDist {
		tp = entry - 2*slDist
		if spot > vwap {
			tp = entry - 2*slDist
		} else {
			tp = entry + 2*slDist
		}
	}

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
		Confidence: 0.52, Entry: entry, StopLoss: sl,
		TakeProfit: tp, TakeProfit2: vwap,
		Instrument:  "STRANGLE",
		Strike:      atmStrike,
		Reason:      "Price >1.5×ATR1h from VWAP, IV not elevated → long straddle for mean-reversion gamma",
		GeneratedAt: ctx.Now,
	}
	// Straddles are exempt from standard IsValid directional check.
	// Validate only SL distance, not R:R (premium-selling/buying inverted geometry).
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// ─────────────────────────────────────────────────────────────────────────────
// S19 — ADX_Trend_Filter_Breakouts
// Instrument : Mid-cap NSE stock futures (500 Cr – 5,000 Cr market cap)
// Timeframe  : 1h candles; ADX > 25 + hourly breakout
// Win target : 54%+   Holding: 1–3 hours
// VERIFY     : ADX reliability on mid-cap stocks; check for gaps/halts
// ─────────────────────────────────────────────────────────────────────────────

type ADXTrendFilterBreakouts struct {
	MinSLDistancePct float64
	ADXThreshold     float64
}

func NewADXTrendFilterBreakouts() *ADXTrendFilterBreakouts {
	return &ADXTrendFilterBreakouts{MinSLDistancePct: 0.004, ADXThreshold: 25.0}
}

func (s *ADXTrendFilterBreakouts) Name() string { return "S19_ADX_Trend_Filter_Breakouts" }

func (s *ADXTrendFilterBreakouts) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *ADXTrendFilterBreakouts) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < 10*60+30 || mins > 14*60 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < 20 {
		return Signal{}, false
	}

	adx := indicators.ADX(candles1h, 14)
	if adx < s.ADXThreshold {
		return Signal{}, false
	}

	pdi, mdi := indicators.PDIMDI(candles1h, 14)
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	// Last 3-hour high/low breakout level.
	n := len(candles1h)
	lookback := 3
	if n < lookback+1 {
		return Signal{}, false
	}
	var h3High, h3Low float64
	for _, c := range candles1h[n-1-lookback : n-1] {
		if h3High == 0 || c.High > h3High {
			h3High = c.High
		}
		if h3Low == 0 || c.Low < h3Low {
			h3Low = c.Low
		}
	}

	last := candles1h[n-1]

	switch {
	case pdi > mdi && last.Close > h3High:
		entry := last.Close
		sl := entry - 1.5*atr1h
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "ADX>25, +DI>-DI, 1h close above 3h high — strong uptrend breakout",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case mdi > pdi && last.Close < h3Low:
		entry := last.Close
		sl := entry + 1.5*atr1h
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "ADX>25, -DI>+DI, 1h close below 3h low — strong downtrend breakout",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S20 — Fibonacci_Retracement_Intraday
// Instrument : Stock futures (high-volume Nifty 50 constituents)
// Timeframe  : 1h candles; Fibonacci 38.2%/50% retracement bounce
// Win target : 50%+   Holding: 1–3 hours
// ─────────────────────────────────────────────────────────────────────────────

type FibonacciRetracementIntraday struct {
	MinSLDistancePct float64
}

func NewFibonacciRetracementIntraday() *FibonacciRetracementIntraday {
	return &FibonacciRetracementIntraday{MinSLDistancePct: 0.004}
}

func (s *FibonacciRetracementIntraday) Name() string {
	return "S20_Fibonacci_Retracement_Intraday"
}

func (s *FibonacciRetracementIntraday) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *FibonacciRetracementIntraday) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < 10*60+30 || mins > 13*60+30 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < 8 {
		return Signal{}, false
	}

	// Identify swing high/low over last 6 bars.
	n := len(candles1h)
	window := candles1h[n-7 : n-1]
	var swHigh, swLow float64
	for _, c := range window {
		if swHigh == 0 || c.High > swHigh {
			swHigh = c.High
		}
		if swLow == 0 || c.Low < swLow {
			swLow = c.Low
		}
	}
	swRange := swHigh - swLow
	if swRange < 50 {
		return Signal{}, false
	}

	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	closes1h := closesOf(candles1h)
	rsi1h := indicators.RSI(closes1h, 14)
	last := candles1h[n-1]

	// Fibonacci levels from swing low (bull) or swing high (bear).
	fib382 := swHigh - 0.382*swRange
	fib500 := swHigh - 0.500*swRange
	fib618 := swHigh - 0.618*swRange // SL beyond this if long

	// Bull: price at 38.2% or 50% retrace, RSI oversold.
	atFib := last.Close >= fib500-atr1h*0.5 && last.Close <= fib382+atr1h*0.5

	switch {
	case ctx.Regime.Regime == regime.TrendingBull && atFib && rsi1h < 40:
		entry := last.Close
		sl := fib618 - atr1h*0.5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: swHigh,
			Instrument:  "FUTURE",
			Reason:      "1h price at 38.2–50% Fibonacci retrace, RSI<40, bull regime bounce",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case ctx.Regime.Regime == regime.TrendingBear:
		// Bear: flip levels — retrace from swing low upward.
		fib382b := swLow + 0.382*swRange
		fib500b := swLow + 0.500*swRange
		fib618b := swLow + 0.618*swRange
		atFibB := last.Close >= fib382b-atr1h*0.5 && last.Close <= fib500b+atr1h*0.5
		if atFibB && rsi1h > 60 {
			entry := last.Close
			sl := fib618b + atr1h*0.5
			if sl-entry < entry*s.MinSLDistancePct {
				sl = entry + entry*s.MinSLDistancePct
			}
			risk := sl - entry
			sig := Signal{
				Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
				Confidence: 0.50, Entry: entry, StopLoss: sl,
				TakeProfit: entry - 2*risk, TakeProfit2: swLow,
				Instrument:  "FUTURE",
				Reason:      "1h price at 38.2–50% Fibonacci retrace from low, RSI>60, bear regime fade",
				GeneratedAt: ctx.Now,
			}
			return sig, sig.IsValid(s.MinSLDistancePct)
		}
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S21 — Bollinger_Band_Squeeze_Breakout_Intraday
// Instrument : Index futures (Nifty Midcap / Nifty / BankNifty)
// Timeframe  : 15m; BB(20,2) squeeze detected, breakout confirmed by volume
// Win target : 54%+   Holding: 30–90 minutes
// ─────────────────────────────────────────────────────────────────────────────

type BollingerBandSqueezeBreakoutIntraday struct {
	MinSLDistancePct float64
	BBPeriod         int
	BBMult           float64
	SqueezeLookback  int
}

func NewBollingerBandSqueezeBreakoutIntraday() *BollingerBandSqueezeBreakoutIntraday {
	return &BollingerBandSqueezeBreakoutIntraday{
		MinSLDistancePct: 0.003, BBPeriod: 20, BBMult: 2.0, SqueezeLookback: 20,
	}
}

func (s *BollingerBandSqueezeBreakoutIntraday) Name() string {
	return "S21_Bollinger_Band_Squeeze_Breakout_Intraday"
}

func (s *BollingerBandSqueezeBreakoutIntraday) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *BollingerBandSqueezeBreakoutIntraday) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < calendar.MarketOpen+30 || mins > 14*60 {
		return Signal{}, false
	}

	candles15m := ctx.Bundle.Candles(ctx.Underlying, "15m")
	need := s.BBPeriod + s.SqueezeLookback + 5
	if len(candles15m) < need {
		return Signal{}, false
	}

	closes := closesOf(candles15m)
	upper, mid, lower := indicators.BollingerBands(closes, s.BBPeriod, s.BBMult)
	if mid == 0 {
		return Signal{}, false
	}

	// Squeeze: current width is the narrowest in the last SqueezeLookback bars.
	currentWidth := indicators.BollingerWidth(closes, s.BBPeriod, s.BBMult)
	minWidth := indicators.MinBollingerWidth(closes[:len(closes)-1], s.BBPeriod, s.BBMult, s.SqueezeLookback)
	isSqueeze := currentWidth <= minWidth*1.05 // within 5% of historical min = active squeeze

	if !isSqueeze {
		return Signal{}, false
	}

	last := candles15m[len(candles15m)-1]
	avgVol := indicators.AvgVolume(candles15m, 20)
	volConfirm := last.Volume > 1.5*avgVol
	atr15m := indicators.ATR(candles15m, 14)
	if atr15m == 0 {
		return Signal{}, false
	}

	switch {
	case last.Close > upper && volConfirm:
		entry := last.Close
		sl := lower
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "BB squeeze broken: 15m close above upper band with volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case last.Close < lower && volConfirm:
		entry := last.Close
		sl := upper
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.54, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "BB squeeze broken: 15m close below lower band with volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S22 — News_Event_Vol_Fade_Options_Sell
// Instrument : Weekly/monthly short strangles on Nifty / BankNifty
// Timeframe  : Event-driven; active in EVENT_RISK regime only
// Win target : 60%+   Holding: 1–5 days (theta decay)
// VERIFY     : RBI policy dates, CPI dates, earnings calendar; update quarterly
// ─────────────────────────────────────────────────────────────────────────────

type NewsEventVolFadeOptionsSell struct {
	MinSLDistancePct float64
	// IVSpikeVIXThreshold: VIX must be this many points above its 5-sample
	// rolling average for IV to be considered "elevated post-event".
	IVSpikeVIXThreshold float64
	// OTMOffsetPct: how far OTM the short strangle legs are placed.
	OTMOffsetPct float64
}

func NewNewsEventVolFadeOptionsSell() *NewsEventVolFadeOptionsSell {
	return &NewsEventVolFadeOptionsSell{
		MinSLDistancePct: 0.01, IVSpikeVIXThreshold: 1.5, OTMOffsetPct: 0.025,
	}
}

func (s *NewsEventVolFadeOptionsSell) Name() string { return "S22_News_Event_Vol_Fade_Options_Sell" }

func (s *NewsEventVolFadeOptionsSell) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.EventRisk}
}

func (s *NewsEventVolFadeOptionsSell) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Enter 30 minutes AFTER market open (let initial event spike settle).
	if mins < calendar.MarketOpen+30 || mins > 12*60 {
		return Signal{}, false
	}

	// VIX spike check: current VIX vs 5-sample rolling history.
	vixNow := ctx.Regime.VIXLevel
	vixHistory := ctx.Bundle.IndiaVIXHistory()
	var vixAvg float64
	for _, v := range vixHistory {
		vixAvg += v
	}
	vixAvg /= 5
	if vixAvg == 0 || vixNow < vixAvg+s.IVSpikeVIXThreshold {
		return Signal{}, false
	}

	// Realized move check: compare last 30 min vs ATR14 on 5m.
	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 10 {
		return Signal{}, false
	}
	atr5m := indicators.ATR(candles5m, 14)
	if atr5m == 0 {
		return Signal{}, false
	}
	// Realized move = range of last 6 5m bars (~30 min).
	n := len(candles5m)
	start := n - 6
	if start < 0 {
		start = 0
	}
	var realHigh, realLow float64
	for _, c := range candles5m[start:] {
		if realHigh == 0 || c.High > realHigh {
			realHigh = c.High
		}
		if realLow == 0 || c.Low < realLow {
			realLow = c.Low
		}
	}
	realizedMove := realHigh - realLow
	// If realized move < 50% of daily ATR proxy → IV is overpriced vs actual move.
	dailyATRProxy := atr5m * 20
	if realizedMove >= 0.5*dailyATRProxy {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	last := candles5m[n-1]
	if spot == 0 {
		spot = last.Close
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	callStrike := roundToStrike(spot*(1+s.OTMOffsetPct), stepSize)
	putStrike := roundToStrike(spot*(1-s.OTMOffsetPct), stepSize)

	// Short strangle: STRANGLE instrument, Short direction.
	entry := spot
	sl := callStrike // breach of either wing = max loss scenario
	slDist := abs(callStrike - entry)
	if slDist < entry*s.MinSLDistancePct {
		slDist = entry * s.MinSLDistancePct
		sl = entry + slDist
	}
	tp := entry // pin at spot = full theta decay

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.60, Entry: entry, StopLoss: sl,
		TakeProfit: tp, TakeProfit2: entry - slDist*0.5,
		Instrument:  "STRANGLE",
		Strike:      callStrike,
		Reason:      "Post-event IV spike, realized move <50% of daily ATR → short strangle for IV crush",
		GeneratedAt: ctx.Now,
	}
	// Exempt from 2:1 R:R — premium-selling inverted geometry (same as S3, S9).
	_ = putStrike // logged in Reason; both legs implicit in STRANGLE instrument
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// roundToStrike rounds price to nearest option strike step.
func roundToStrike(price, step float64) float64 {
	if step == 0 {
		return price
	}
	return float64(int64(price/step+0.5)) * step
}
