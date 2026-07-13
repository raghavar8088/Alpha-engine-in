// Package instruments holds NSE contract-specification constants:
// lot sizes, tick size, and circuit-band defaults. NSE revises lot
// sizes periodically (most recently to standardize index F&O lot
// notional value around Rs 5-10 lakh per SEBI's Oct 2024 framework) —
// every constant here carries a REGULATORY FLAG and must be checked
// against the current NSE contract-specification circular before use
// beyond paper trading.
package instruments

// LotSize, REGULATORY FLAG: VERIFY CURRENT LOT SIZE against the latest
// NSE F&O contract specification circular (https://www.nseindia.com,
// Market Data > F&O > Lot Size). NSE revised index-option lot sizes
// market-wide in 2025 to target a higher minimum contract notional per
// SEBI's framework; the values below are the seed used by this build
// and must be re-verified, not assumed permanent.
var LotSize = map[string]int64{
	"NIFTY":     75, // VERIFY against current NSE circular
	"BANKNIFTY": 30, // VERIFY against current NSE circular (revised upward from 15 historically)
}

// TickSize is the minimum price increment for options premium quoting.
const TickSize = 0.05 // Rs 0.05, standard NSE options tick

// PrevDayCloseFallback is used only when no live previous-close feed
// is available (synthetic/dev mode).
var PrevDayCloseFallback = map[string]float64{
	"NIFTY":     24800.0,
	"BANKNIFTY": 52600.0,
}

// LotsToQuantity converts a lot count to total quantity for the given underlying.
func LotsToQuantity(underlying string, lots int64) int64 {
	return lots * LotSize[underlying]
}

// RoundToTick rounds a premium to the nearest valid tick.
func RoundToTick(price float64) float64 {
	ticks := price / TickSize
	rounded := float64(int64(ticks + 0.5))
	return rounded * TickSize
}
