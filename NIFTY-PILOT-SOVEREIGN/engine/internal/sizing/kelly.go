package sizing

// KellyInputsIndia mirrors the BTC engine's half-Kelly architecture,
// with an added SessionMult for the Indian opening/closing volatility
// pattern and a VIXMult dampener layered on top of the regime
// classifier's own PositionSizeMult.
type KellyInputsIndia struct {
	PortfolioINR   float64
	MaxPositionPct float64 // hard cap, e.g. 0.10 = 10%
	RegimeMult     float64 // from regime.RegimeClass.PositionSizeMult
	SessionMult    float64
	VIXMult        float64
	WinRate        float64
	AvgWinPct      float64
	AvgLossPct     float64
}

// SessionMultiplier returns the size multiplier for the given IST
// minute-of-day, reflecting the well-documented Indian opening
// (09:15-10:00) and closing (14:30-15:30) volatility pattern: reduce
// size in the choppiest windows, full size in the stable midday session.
func SessionMultiplier(istMinuteOfDay int) float64 {
	switch {
	case istMinuteOfDay >= 9*60+15 && istMinuteOfDay < 10*60:
		return 0.5 // opening volatility window
	case istMinuteOfDay >= 14*60+30 && istMinuteOfDay < 15*60+30:
		return 0.6 // closing volatility window
	default:
		return 1.0 // stable midday session
	}
}

// VIXMultiplier returns an additional dampener as India VIX rises,
// independent of the regime classifier's own HIGH_VOL cutoff (this is
// a smoother taper rather than the classifier's hard 0/1 gate).
func VIXMultiplier(vix float64) float64 {
	switch {
	case vix < 13:
		return 1.0
	case vix < 16:
		return 0.85
	case vix < 18:
		return 0.6
	case vix < 20:
		return 0.35
	default:
		return 0.0
	}
}

// HalfKellyFraction computes the half-Kelly bet fraction from win rate
// and average win/loss percentages. Returns 0 if the edge is negative.
func HalfKellyFraction(winRate, avgWinPct, avgLossPct float64) float64 {
	if avgLossPct <= 0 {
		return 0
	}
	b := avgWinPct / avgLossPct
	f := winRate - (1-winRate)/b
	if f <= 0 {
		return 0
	}
	return f / 2 // half-Kelly, same conservatism as the BTC engine
}

// PositionSizeINR computes the final INR notional to risk on a trade,
// applying half-Kelly, all multipliers, and the hard MaxPositionPct cap.
func PositionSizeINR(in KellyInputsIndia) float64 {
	kelly := HalfKellyFraction(in.WinRate, in.AvgWinPct, in.AvgLossPct)
	sized := in.PortfolioINR * kelly * in.RegimeMult * in.SessionMult * in.VIXMult
	cap := in.PortfolioINR * in.MaxPositionPct
	if sized > cap {
		sized = cap
	}
	if sized < 0 {
		sized = 0
	}
	return sized
}

// LotsForRisk converts an INR risk budget and per-lot risk (SL
// distance * lot size) into a whole-lot position size, applying the
// MarginBook's available-margin gate as a hard secondary constraint
// (the new-for-this-system addition over the BTC engine: margin
// blocking, not just position-count caps).
func LotsForRisk(riskBudgetINR, perLotRiskINR float64, requiredMarginPerLot float64, book *MarginBook) int64 {
	if perLotRiskINR <= 0 {
		return 0
	}
	lots := int64(riskBudgetINR / perLotRiskINR)
	if lots < 1 {
		return 0
	}
	for lots > 0 {
		totalMargin := requiredMarginPerLot * float64(lots)
		if book.CanOpen(totalMargin) {
			return lots
		}
		lots--
	}
	return 0
}
