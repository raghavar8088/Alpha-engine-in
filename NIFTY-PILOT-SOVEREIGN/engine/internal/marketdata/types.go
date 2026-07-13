package marketdata

import "time"

// Candle is a single OHLCV bar, timestamped in UTC internally (display
// layers convert to IST).
type Candle struct {
	Time   time.Time
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume float64
}

// Greeks holds option Greeks for a single contract.
type Greeks struct {
	Delta float64
	Gamma float64
	Theta float64
	Vega  float64
	IV    float64 // implied volatility, decimal (0.18 = 18%)
}

// StrikeData holds the full quote + OI + Greeks for one strike, one
// option type (CE/PE), one expiry.
type StrikeData struct {
	Strike      float64
	OptionType  string // "CE" | "PE"
	LTP         float64
	BidPrice    float64
	BidQty      int64
	AskPrice    float64
	AskQty      int64
	OI          int64
	OIChange    int64
	Volume      int64
	Greeks      Greeks
}

// OptionChainSnapshot is the full chain for one underlying + expiry.
type OptionChainSnapshot struct {
	Underlying string // "NIFTY" | "BANKNIFTY"
	Expiry     time.Time
	SpotPrice  float64
	Strikes    []StrikeData
	FetchedAt  time.Time
}

// PCR computes the Put-Call Ratio (OI-based) for the snapshot.
func (s OptionChainSnapshot) PCR() float64 {
	var putOI, callOI int64
	for _, k := range s.Strikes {
		if k.OptionType == "PE" {
			putOI += k.OI
		} else if k.OptionType == "CE" {
			callOI += k.OI
		}
	}
	if callOI == 0 {
		return 0
	}
	return float64(putOI) / float64(callOI)
}

// MaxPain computes the strike at which option writers (sellers) lose
// the least money in aggregate, i.e. the strike toward which price
// tends to gravitate near expiry.
func (s OptionChainSnapshot) MaxPain() float64 {
	if len(s.Strikes) == 0 {
		return 0
	}
	strikeSet := map[float64]bool{}
	for _, k := range s.Strikes {
		strikeSet[k.Strike] = true
	}
	var bestStrike float64
	bestLoss := -1.0
	for candidate := range strikeSet {
		var totalLoss float64
		for _, k := range s.Strikes {
			if k.OptionType == "CE" && candidate > k.Strike {
				totalLoss += float64(k.OI) * (candidate - k.Strike)
			}
			if k.OptionType == "PE" && candidate < k.Strike {
				totalLoss += float64(k.OI) * (k.Strike - candidate)
			}
		}
		if bestLoss < 0 || totalLoss < bestLoss {
			bestLoss = totalLoss
			bestStrike = candidate
		}
	}
	return bestStrike
}
