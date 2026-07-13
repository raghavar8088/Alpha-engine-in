// Package sizing implements Kelly-based position sizing and the
// India-specific margin (SPAN + exposure) constraint layer that has no
// equivalent in the reference BTC engine (BTC futures margin is a
// simple leverage multiple; Indian options-selling margin is not).
package sizing

import "niftypilot/internal/instruments"

// MarginMethod documents the approximation used. A real SPAN
// calculation requires NSE's published SPAN risk-array files (margin
// scanning ranges per underlying, updated daily) run through their
// span.exe/span4j methodology. This build approximates SPAN with a
// percentage-of-notional method calibrated to NSE's typically observed
// SPAN+exposure margin for short index-options positions (roughly
// 8-12% of contract notional for short single-leg options, with a
// partial offset for defined-risk spreads/strangles).
//
// KNOWN LIMITATION: this is a coarse approximation, not the real SPAN
// risk-array calculation. Acceptable for paper trading; replace with
// either NSE's published SPAN files or a broker's margin-calculator
// API (most brokers expose one) before relying on this for realistic
// live-sizing decisions.
const MarginMethod = "percent-of-notional approximation (8-12% short options, see margin.go)"

// MarginEstimate holds the SPAN + exposure margin breakdown for one position.
type MarginEstimate struct {
	SPANMarginINR     float64
	ExposureMarginINR float64
	TotalMarginINR    float64
}

// SPANRatePctShortOption is the percentage-of-notional used to
// approximate SPAN margin for a short (written) single-leg option
// position. REGULATORY FLAG: calibrate against NSE's published SPAN
// span-file output or a broker margin-calculator API before live use.
const SPANRatePctShortOption = 0.10 // 10% of notional

// ExposureMarginRate is the additional exposure margin layered on top
// of SPAN, applied to notional. REGULATORY FLAG: verify against
// current NSE F&O exposure margin circular.
const ExposureMarginRate = 0.03 // 3% of notional

// StrangleOffsetCredit is the partial margin offset NSE grants for a
// defined-risk combination (e.g. short strangle with both legs
// margined together rather than as two independent shorts). Modeled
// as a flat discount on the summed single-leg margin. REGULATORY FLAG:
// real offsets come from NSE's combined-margin risk-array logic; this
// is a coarse approximation.
const StrangleOffsetCredit = 0.25 // 25% discount vs sum of two single-leg margins

// EstimateShortOption returns the margin required to hold one short
// single-leg option position (e.g. one leg of S3/S9's strangle, or a
// directional short PE/CE in a strategy that sells rather than buys).
func EstimateShortOption(underlying string, strike, spot float64, lots int64) MarginEstimate {
	qty := instruments.LotsToQuantity(underlying, lots)
	notional := spot * float64(qty)
	span := notional * SPANRatePctShortOption
	exposure := notional * ExposureMarginRate
	return MarginEstimate{SPANMarginINR: span, ExposureMarginINR: exposure, TotalMarginINR: span + exposure}
}

// EstimateShortStrangle returns the combined margin for a short
// strangle (S3/S9), applying the combined-margin discount.
func EstimateShortStrangle(underlying string, callStrike, putStrike, spot float64, lots int64) MarginEstimate {
	call := EstimateShortOption(underlying, callStrike, spot, lots)
	put := EstimateShortOption(underlying, putStrike, spot, lots)
	summed := call.TotalMarginINR + put.TotalMarginINR
	discounted := summed * (1 - StrangleOffsetCredit)
	return MarginEstimate{
		SPANMarginINR:     (call.SPANMarginINR + put.SPANMarginINR) * (1 - StrangleOffsetCredit),
		ExposureMarginINR: (call.ExposureMarginINR + put.ExposureMarginINR) * (1 - StrangleOffsetCredit),
		TotalMarginINR:    discounted,
	}
}

// EstimateLongOption returns the margin for a long (bought) option:
// premium paid in full, no SPAN/exposure margin (defined risk = premium).
func EstimateLongOption(premium float64, qty int64) MarginEstimate {
	cost := premium * float64(qty)
	return MarginEstimate{TotalMarginINR: cost}
}

// EstimateFuture returns the margin for one futures lot (SPAN +
// exposure on full contract notional, no offset).
func EstimateFuture(underlying string, price float64, lots int64) MarginEstimate {
	qty := instruments.LotsToQuantity(underlying, lots)
	notional := price * float64(qty)
	span := notional * SPANRatePctShortOption // futures SPAN approximated at same rate as short options
	exposure := notional * ExposureMarginRate
	return MarginEstimate{SPANMarginINR: span, ExposureMarginINR: exposure, TotalMarginINR: span + exposure}
}

// MarginBook tracks total margin utilization across all open positions
// against the portfolio's available margin (capital not otherwise blocked).
type MarginBook struct {
	TotalCapitalINR float64
	UsedMarginINR   float64
}

func (b *MarginBook) AvailableMarginINR() float64 {
	avail := b.TotalCapitalINR - b.UsedMarginINR
	if avail < 0 {
		return 0
	}
	return avail
}

func (b *MarginBook) UtilizationPct() float64 {
	if b.TotalCapitalINR == 0 {
		return 0
	}
	return b.UsedMarginINR / b.TotalCapitalINR
}

// CanOpen reports whether a new position requiring requiredMargin can
// be opened without exceeding available margin.
func (b *MarginBook) CanOpen(requiredMargin float64) bool {
	return requiredMargin <= b.AvailableMarginINR()
}

func (b *MarginBook) Block(amount float64) { b.UsedMarginINR += amount }
func (b *MarginBook) Release(amount float64) {
	b.UsedMarginINR -= amount
	if b.UsedMarginINR < 0 {
		b.UsedMarginINR = 0
	}
}
