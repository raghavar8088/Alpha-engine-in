// S23–S29: Swing strategies (daily–weekly horizon, 1–7 day holds).
// Uses 1h candles with multi-day lookbacks (bundle has no daily timeframe).
// All follow the exact Strategy interface in strategy.go.
// No modifications to S1–S9, risk engine, or core architecture.
package strategy

import (
	"niftypilot/internal/calendar"
	"niftypilot/internal/indicators"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
)

// barsPerDay is the approximate number of 1h bars in one Indian trading session.
const barsPerDay = 7

// ─────────────────────────────────────────────────────────────────────────────
// S23 — Weekly_Options_Theta_Decay_Strangle
// Instrument : Short OTM strangle — weekly expiry, BankNifty or Nifty
// Timeframe  : Signal generated on Monday 09:45 IST, holds to Wednesday/Thursday
// Win target : 60%+   Holding: 2–5 days (pure theta / IV crush)
// VERIFY     : NSE BankNifty weekly expiry moves to Wednesdays from 2024;
//              Nifty weekly is still Thursday — confirm before deploy.
// ─────────────────────────────────────────────────────────────────────────────

type WeeklyOptionsThetaDecayStrangle struct {
	MinSLDistancePct float64
	// OTMOffsetPct: strangle wings placed this far OTM from spot.
	OTMOffsetPct float64
	// MaxVIX: skip theta-selling when VIX > this level (elevated IV risk).
	MaxVIX float64
}

func NewWeeklyOptionsThetaDecayStrangle() *WeeklyOptionsThetaDecayStrangle {
	return &WeeklyOptionsThetaDecayStrangle{
		MinSLDistancePct: 0.01, OTMOffsetPct: 0.03, MaxVIX: 20.0,
	}
}

func (s *WeeklyOptionsThetaDecayStrangle) Name() string {
	return "S23_Weekly_Options_Theta_Decay_Strangle"
}

func (s *WeeklyOptionsThetaDecayStrangle) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *WeeklyOptionsThetaDecayStrangle) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Only enter on Monday morning after the opening range settles.
	if ist.Weekday() != 1 || mins < calendar.MarketOpen+30 || mins > calendar.MarketOpen+60 {
		return Signal{}, false
	}
	// Skip when VIX is too elevated — avoid selling cheap premium into a spike.
	if ctx.Regime.VIXLevel > s.MaxVIX {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < barsPerDay*3 {
		return Signal{}, false
	}

	// Weekly range check: if the index moved >2% intraweek last week, VIX
	// likely reflects directional risk — skip theta selling.
	prevWeekBars := barsPerDay * 5
	if prevWeekBars > len(candles1h)-1 {
		prevWeekBars = len(candles1h) - 1
	}
	var weekHigh, weekLow float64
	for _, c := range candles1h[len(candles1h)-1-prevWeekBars : len(candles1h)-1] {
		if weekHigh == 0 || c.High > weekHigh {
			weekHigh = c.High
		}
		if weekLow == 0 || c.Low < weekLow {
			weekLow = c.Low
		}
	}
	weekMove := 0.0
	if weekLow > 0 {
		weekMove = (weekHigh - weekLow) / weekLow
	}
	if weekMove > 0.025 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	callStrike := roundToStrike(spot*(1+s.OTMOffsetPct), stepSize)
	putStrike := roundToStrike(spot*(1-s.OTMOffsetPct), stepSize)

	entry := spot
	slDist := spot * s.OTMOffsetPct * 1.5 // SL if either wing is breached 1.5× away
	sl := callStrike * 1.02               // breach proxy
	if slDist < entry*s.MinSLDistancePct {
		slDist = entry * s.MinSLDistancePct
		sl = entry + slDist
	}

	_ = putStrike // both legs implicit in STRANGLE instrument
	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
		Confidence: 0.60, Entry: entry, StopLoss: sl,
		TakeProfit: entry, TakeProfit2: entry - slDist*0.5,
		Instrument:  "STRANGLE",
		Strike:      callStrike,
		Reason:      "Monday open, VIX<20, weekly move <2.5% — short OTM strangle for theta decay",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// ─────────────────────────────────────────────────────────────────────────────
// S24 — Momentum_Breakout_Swing
// Instrument : Nifty 200 stock futures (liquid large-cap)
// Timeframe  : Multi-day breakout from 10-day consolidation using 1h bars
// Win target : 50%+   Holding: 3–7 days
// ─────────────────────────────────────────────────────────────────────────────

type MomentumBreakoutSwing struct {
	MinSLDistancePct float64
	// ConsolidationDays: number of days the stock must be in range before breakout.
	ConsolidationDays int
	// VolumeSpikeMultiplier: volume on breakout bar must be > this × avg.
	VolumeSpikeMultiplier float64
}

func NewMomentumBreakoutSwing() *MomentumBreakoutSwing {
	return &MomentumBreakoutSwing{
		MinSLDistancePct: 0.005, ConsolidationDays: 10, VolumeSpikeMultiplier: 2.0,
	}
}

func (s *MomentumBreakoutSwing) Name() string { return "S24_Momentum_Breakout_Swing" }

func (s *MomentumBreakoutSwing) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *MomentumBreakoutSwing) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Only evaluate in the final 45 min of session (EOD signal for next day entry).
	if mins < 14*60+45 || mins > calendar.MarketClose {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	need := s.ConsolidationDays*barsPerDay + barsPerDay + 5
	if len(candles1h) < need {
		return Signal{}, false
	}

	// Consolidation range over ConsolidationDays (excluding today's bars).
	todayBars := barsPerDay
	consEnd := len(candles1h) - todayBars
	consStart := consEnd - s.ConsolidationDays*barsPerDay
	if consStart < 0 {
		return Signal{}, false
	}

	var consHigh, consLow float64
	for _, c := range candles1h[consStart:consEnd] {
		if consHigh == 0 || c.High > consHigh {
			consHigh = c.High
		}
		if consLow == 0 || c.Low < consLow {
			consLow = c.Low
		}
	}
	consRange := consHigh - consLow
	if consRange == 0 {
		return Signal{}, false
	}

	// Consolidation validity: high/low ratio must be < 5% (tight range).
	if consRange/consHigh > 0.05 {
		return Signal{}, false
	}

	// Today's bars.
	todayCandles := candles1h[len(candles1h)-todayBars:]
	if len(todayCandles) == 0 {
		return Signal{}, false
	}
	last := todayCandles[len(todayCandles)-1]
	avgVol := indicators.AvgVolume(candles1h[:consEnd], 20*barsPerDay)
	volConfirm := last.Volume > s.VolumeSpikeMultiplier*avgVol
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	switch {
	case last.Close > consHigh && volConfirm:
		entry := last.Close
		sl := consHigh - atr1h*0.5
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "EOD breakout above 10-day consolidation high, 2× avg volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case last.Close < consLow && volConfirm:
		entry := last.Close
		sl := consLow + atr1h*0.5
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.50, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "EOD breakdown below 10-day consolidation low, 2× avg volume confirm",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S25 — Mean_Reversion_RSI_Oversold_Swing
// Instrument : Large-cap stock futures (Nifty 50 constituents)
// Timeframe  : Daily RSI<30 (bull) or RSI>70 (bear) — uses 1h closes
// Win target : 52%+   Holding: 2–5 days
// ─────────────────────────────────────────────────────────────────────────────

type MeanReversionRSIOversoldSwing struct {
	MinSLDistancePct float64
	RSIPeriod        int
	RSIOversold      float64
	RSIOverbought    float64
}

func NewMeanReversionRSIOversoldSwing() *MeanReversionRSIOversoldSwing {
	return &MeanReversionRSIOversoldSwing{
		MinSLDistancePct: 0.005, RSIPeriod: 14, RSIOversold: 30, RSIOverbought: 70,
	}
}

func (s *MeanReversionRSIOversoldSwing) Name() string {
	return "S25_Mean_Reversion_RSI_Oversold_Swing"
}

func (s *MeanReversionRSIOversoldSwing) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear, regime.Ranging}
}

func (s *MeanReversionRSIOversoldSwing) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	if mins < 14*60+45 || mins > calendar.MarketClose {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	// Need enough 1h bars for RSI across several days.
	if len(candles1h) < (s.RSIPeriod+5)*barsPerDay {
		return Signal{}, false
	}

	// Derive pseudo-daily closes: take last candle of each day (every barsPerDay bars).
	dailyCloses := deriveDailyCloses(candles1h)
	if len(dailyCloses) < s.RSIPeriod+5 {
		return Signal{}, false
	}

	rsi := indicators.RSI(dailyCloses, s.RSIPeriod)
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	// Trend filter: EMA50 direction on daily closes.
	ema50 := indicators.LastEMA(dailyCloses, 50)
	ema20 := indicators.LastEMA(dailyCloses, 20)
	last1h := candles1h[len(candles1h)-1]
	spot := last1h.Close
	if ctx.Bundle.Spot(ctx.Underlying) > 0 {
		spot = ctx.Bundle.Spot(ctx.Underlying)
	}

	// ATR proxy over 3 days for swing stop placement.
	atr3d := atr1h * float64(barsPerDay) * 0.5

	switch {
	case rsi < s.RSIOversold && (ema50 == 0 || spot > ema50*0.97):
		// Oversold bounce: only in bull regime or near long-term support.
		entry := spot
		sl := entry - 2*atr3d
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
			Instrument:  "FUTURE",
			Reason:      "Daily RSI<30, price near EMA50 support — mean-reversion long swing",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case rsi > s.RSIOverbought && (ema20 == 0 || spot < ema20*1.03):
		entry := spot
		sl := entry + 2*atr3d
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.52, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 3*risk,
			Instrument:  "FUTURE",
			Reason:      "Daily RSI>70, price near EMA20 resistance — mean-reversion short swing",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S26 — Sector_Rotation_Nifty_Rebalance
// Instrument : Nifty sector index futures (Auto, IT, Bank, FMCG, Metal)
// Timeframe  : Weekly — signal on Monday EOD, holds 5 days
// Win target : 50%+   Holding: 5–7 days
// VERIFY     : Sector ETF futures liquidity on NSE; check OI before entry.
// ─────────────────────────────────────────────────────────────────────────────

type SectorRotationNiftyRebalance struct {
	MinSLDistancePct float64
	// WeakRelStrengthPct: how much weaker a sector must be vs Nifty 50 (proxy)
	// to qualify as a laggard that will rotate up on mean reversion.
	WeakRelStrengthPct float64
}

func NewSectorRotationNiftyRebalance() *SectorRotationNiftyRebalance {
	return &SectorRotationNiftyRebalance{MinSLDistancePct: 0.005, WeakRelStrengthPct: 0.03}
}

func (s *SectorRotationNiftyRebalance) Name() string { return "S26_Sector_Rotation_Nifty_Rebalance" }

func (s *SectorRotationNiftyRebalance) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull}
}

func (s *SectorRotationNiftyRebalance) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Weekly signal: Friday EOD for following-week entry.
	if ist.Weekday() != 5 || mins < 14*60+45 || mins > calendar.MarketClose {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < barsPerDay*15 {
		return Signal{}, false
	}

	// Measure 4-week (20 daily) return for the underlying vs its own EMA20 proxy.
	dailyCloses := deriveDailyCloses(candles1h)
	if len(dailyCloses) < 25 {
		return Signal{}, false
	}

	d := len(dailyCloses)
	ret4w := (dailyCloses[d-1] - dailyCloses[d-21]) / dailyCloses[d-21]
	ema20 := indicators.LastEMA(dailyCloses, 20)
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}
	atr5d := atr1h * float64(barsPerDay) * 0.5

	spot := dailyCloses[d-1]

	// Laggard: negative 4-week return in bull regime = rotation candidate.
	if ret4w >= -s.WeakRelStrengthPct {
		return Signal{}, false
	}
	if ema20 > 0 && spot < ema20*0.95 {
		// Too far below EMA20 — may be a broken sector, not a laggard.
		return Signal{}, false
	}

	entry := spot
	sl := entry - 2*atr5d
	if entry-sl < entry*s.MinSLDistancePct {
		sl = entry - entry*s.MinSLDistancePct
	}
	risk := entry - sl
	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
		Confidence: 0.50, Entry: entry, StopLoss: sl,
		TakeProfit: entry + 2*risk, TakeProfit2: entry + 3*risk,
		Instrument:  "FUTURE",
		Reason:      "Sector laggard: 4-week return < -3% in bull regime, near EMA20 — rotation long",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.IsValid(s.MinSLDistancePct)
}

// ─────────────────────────────────────────────────────────────────────────────
// S27 — Gap_Up_Down_Fade_Options
// Instrument : OTM put/call options on Nifty/BankNifty (fade the gap)
// Timeframe  : 09:15–09:30 IST only; targets gap fill within the session
// Win target : 55%+   Holding: 30–120 minutes
// VERIFY     : NSE pre-open auction settlement vs actual open; gap definition.
// ─────────────────────────────────────────────────────────────────────────────

type GapFadeOptions struct {
	MinSLDistancePct float64
	// MinGapPct: minimum overnight gap size to qualify for fade trade.
	MinGapPct float64
	// MaxGapPct: beyond this gap the move may be fundamental — skip fade.
	MaxGapPct float64
}

func NewGapFadeOptions() *GapFadeOptions {
	return &GapFadeOptions{MinSLDistancePct: 0.005, MinGapPct: 0.007, MaxGapPct: 0.025}
}

func (s *GapFadeOptions) Name() string { return "S27_Gap_Up_Down_Fade_Options" }

func (s *GapFadeOptions) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.Ranging, regime.TrendingBull, regime.TrendingBear}
}

func (s *GapFadeOptions) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Tight window: only the first 15 minutes to catch the gap before it resolves.
	if mins < calendar.MarketOpen || mins > calendar.MarketOpen+15 {
		return Signal{}, false
	}

	prevClose := ctx.Bundle.PrevClose(ctx.Underlying)
	spot := ctx.Bundle.Spot(ctx.Underlying)
	if prevClose <= 0 || spot <= 0 {
		return Signal{}, false
	}

	gapPct := (spot - prevClose) / prevClose
	gapSize := abs(gapPct)
	if gapSize < s.MinGapPct || gapSize > s.MaxGapPct {
		return Signal{}, false
	}

	candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
	if len(candles5m) < 5 {
		return Signal{}, false
	}
	atr5m := indicators.ATR(candles5m, 14)
	if atr5m == 0 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}

	switch {
	case gapPct > s.MinGapPct:
		// Gap up — buy puts to fade (price expected to fill gap back toward prevClose).
		putStrike := roundToStrike(spot, stepSize)
		entry := spot
		sl := spot + atr5m*2 // gap extension = thesis broken
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		tp := prevClose // gap fill target
		if tp > entry-risk*2 {
			tp = entry - risk*2 // ensure 2:1 R:R minimum
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: tp, TakeProfit2: prevClose,
			Instrument:  "PE",
			Strike:      putStrike,
			Reason:      "Gap-up 0.7–2.5% at open, fading toward gap fill via PE options",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case gapPct < -s.MinGapPct:
		// Gap down — buy calls to fade.
		callStrike := roundToStrike(spot, stepSize)
		entry := spot
		sl := spot - atr5m*2
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		tp := prevClose
		if tp < entry+risk*2 {
			tp = entry + risk*2
		}
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.55, Entry: entry, StopLoss: sl,
			TakeProfit: tp, TakeProfit2: prevClose,
			Instrument:  "CE",
			Strike:      callStrike,
			Reason:      "Gap-down 0.7–2.5% at open, fading toward gap fill via CE options",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// S28 — Earnings_Straddle_IV_Play
// Instrument : ATM straddle on single-stock futures (pre/post earnings)
// Timeframe  : Event-driven (EventRisk regime); entered 2 days before earnings
// Win target : 55%+   Holding: 1–3 days
// VERIFY     : NSE earnings calendar integration; SEBI restriction on
//              options positions within 1 day of earnings for insiders.
// ─────────────────────────────────────────────────────────────────────────────

type EarningsStraddleIVPlay struct {
	MinSLDistancePct float64
	// IVRankMinForPreEarnings: buy straddle only if IV rank is moderate
	// (VIX proxy above this multiplier vs its rolling avg, but not too high).
	IVRankMinForPreEarnings float64
}

func NewEarningsStraddleIVPlay() *EarningsStraddleIVPlay {
	return &EarningsStraddleIVPlay{MinSLDistancePct: 0.01, IVRankMinForPreEarnings: 1.1}
}

func (s *EarningsStraddleIVPlay) Name() string { return "S28_Earnings_Straddle_IV_Play" }

func (s *EarningsStraddleIVPlay) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.EventRisk}
}

func (s *EarningsStraddleIVPlay) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// Enter 2 hours after open — let opening gap/noise settle first.
	if mins < calendar.MarketOpen+120 || mins > 12*60 {
		return Signal{}, false
	}

	// IV check: VIX should be moderately elevated (not too high — overpaying for premium).
	vixNow := ctx.Regime.VIXLevel
	vixHistory := ctx.Bundle.IndiaVIXHistory()
	var vixAvg float64
	for _, v := range vixHistory {
		vixAvg += v
	}
	vixAvg /= 5
	if vixAvg == 0 {
		return Signal{}, false
	}
	ivRank := vixNow / vixAvg
	// IV rank between 1.1× and 1.5× rolling avg: elevated but not extreme.
	if ivRank < s.IVRankMinForPreEarnings || ivRank > 1.5 {
		return Signal{}, false
	}

	spot := ctx.Bundle.Spot(ctx.Underlying)
	if spot == 0 {
		candles5m := ctx.Bundle.Candles(ctx.Underlying, "5m")
		if len(candles5m) == 0 {
			return Signal{}, false
		}
		spot = candles5m[len(candles5m)-1].Close
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	if len(candles1h) < 10 {
		return Signal{}, false
	}
	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	stepSize := 50.0
	if ctx.Underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	atmStrike := roundToStrike(spot, stepSize)

	entry := spot
	// SL: index moves 2× ATR1h against straddle (event gap extends far enough that delta
	// overwhelms gamma before IV crush can profit).
	slDist := atr1h * 2
	if slDist < entry*s.MinSLDistancePct {
		slDist = entry * s.MinSLDistancePct
	}
	sl := entry + slDist

	sig := Signal{
		Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
		Confidence: 0.55, Entry: entry, StopLoss: sl,
		TakeProfit: entry + slDist*2, TakeProfit2: entry + slDist*3,
		Instrument:  "STRANGLE",
		Strike:      atmStrike,
		Reason:      "EventRisk regime, IV rank 1.1–1.5×, pre-earnings ATM straddle for gamma",
		GeneratedAt: ctx.Now,
	}
	return sig, sig.Entry > 0 && sig.StopLoss > 0 && abs(sig.Entry-sig.StopLoss)/sig.Entry >= s.MinSLDistancePct
}

// ─────────────────────────────────────────────────────────────────────────────
// S29 — Index_Futures_Positional_Trend
// Instrument : Nifty or BankNifty rolling futures (current-month)
// Timeframe  : Multi-day trend using EMA50/EMA200 crossover on daily closes
// Win target : 48%+   Holding: 5–15 days
// ─────────────────────────────────────────────────────────────────────────────

type IndexFuturesPositionalTrend struct {
	MinSLDistancePct float64
	// FastEMAPeriod: EMA period for the fast line (pseudo-daily).
	FastEMAPeriod int
	// SlowEMAPeriod: EMA period for the slow/trend line.
	SlowEMAPeriod int
}

func NewIndexFuturesPositionalTrend() *IndexFuturesPositionalTrend {
	return &IndexFuturesPositionalTrend{
		MinSLDistancePct: 0.005, FastEMAPeriod: 20, SlowEMAPeriod: 50,
	}
}

func (s *IndexFuturesPositionalTrend) Name() string {
	return "S29_Index_Futures_Positional_Trend"
}

func (s *IndexFuturesPositionalTrend) AllowedRegimes() []regime.Regime {
	return []regime.Regime{regime.TrendingBull, regime.TrendingBear}
}

func (s *IndexFuturesPositionalTrend) Evaluate(ctx MarketContext) (Signal, bool) {
	if !RegimeAllowed(s, ctx.Regime) {
		return Signal{}, false
	}
	ist := ctx.Now.In(calendar.IST)
	mins := ist.Hour()*60 + ist.Minute()
	// EOD signal: generates entry for following day.
	if mins < 14*60+45 || mins > calendar.MarketClose {
		return Signal{}, false
	}

	candles1h := ctx.Bundle.Candles(ctx.Underlying, "1h")
	need := (s.SlowEMAPeriod + 10) * barsPerDay
	if len(candles1h) < need {
		return Signal{}, false
	}

	dailyCloses := deriveDailyCloses(candles1h)
	if len(dailyCloses) < s.SlowEMAPeriod+5 {
		return Signal{}, false
	}

	emaFast := indicators.LastEMA(dailyCloses, s.FastEMAPeriod)
	emaSlow := indicators.LastEMA(dailyCloses, s.SlowEMAPeriod)
	if emaFast == 0 || emaSlow == 0 {
		return Signal{}, false
	}

	atr1h := indicators.ATR(candles1h, 14)
	if atr1h == 0 {
		return Signal{}, false
	}

	// Previous day's fast/slow EMAs for crossover detection.
	prevCloses := dailyCloses[:len(dailyCloses)-1]
	if len(prevCloses) < s.SlowEMAPeriod {
		return Signal{}, false
	}
	prevFast := indicators.LastEMA(prevCloses, s.FastEMAPeriod)
	prevSlow := indicators.LastEMA(prevCloses, s.SlowEMAPeriod)

	spot := dailyCloses[len(dailyCloses)-1]
	atr5d := atr1h * float64(barsPerDay) * 0.8

	switch {
	case prevFast <= prevSlow && emaFast > emaSlow:
		// Bullish crossover.
		entry := spot
		sl := entry - atr5d
		if entry-sl < entry*s.MinSLDistancePct {
			sl = entry - entry*s.MinSLDistancePct
		}
		risk := entry - sl
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Long,
			Confidence: 0.48, Entry: entry, StopLoss: sl,
			TakeProfit: entry + 2*risk, TakeProfit2: entry + 4*risk,
			Instrument:  "FUTURE",
			Reason:      "Daily EMA20 crossed above EMA50 — positional bull trend entry",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)

	case prevFast >= prevSlow && emaFast < emaSlow:
		// Bearish crossover.
		entry := spot
		sl := entry + atr5d
		if sl-entry < entry*s.MinSLDistancePct {
			sl = entry + entry*s.MinSLDistancePct
		}
		risk := sl - entry
		sig := Signal{
			Strategy: s.Name(), Underlying: ctx.Underlying, Direction: Short,
			Confidence: 0.48, Entry: entry, StopLoss: sl,
			TakeProfit: entry - 2*risk, TakeProfit2: entry - 4*risk,
			Instrument:  "FUTURE",
			Reason:      "Daily EMA20 crossed below EMA50 — positional bear trend entry",
			GeneratedAt: ctx.Now,
		}
		return sig, sig.IsValid(s.MinSLDistancePct)
	}
	return Signal{}, false
}

// ─────────────────────────────────────────────────────────────────────────────
// deriveDailyCloses synthesizes pseudo-daily close prices from 1h candles.
// It takes the close of the last bar before 15:30 IST each trading day,
// approximating the NSE closing price for daily indicator calculations.
// ─────────────────────────────────────────────────────────────────────────────
func deriveDailyCloses(candles []marketdata.Candle) []float64 {
	if len(candles) == 0 {
		return nil
	}
	var result []float64
	var prevDate int
	for i, c := range candles {
		ci := c.Time.In(calendar.IST)
		day := ci.Year()*10000 + int(ci.Month())*100 + ci.Day()
		isMktClose := ci.Hour()*60+ci.Minute() >= calendar.MarketClose-60
		isLastBar := i == len(candles)-1
		if isMktClose && day != prevDate {
			result = append(result, c.Close)
			prevDate = day
		} else if isLastBar && len(result) == 0 {
			result = append(result, c.Close)
		}
	}
	return result
}
