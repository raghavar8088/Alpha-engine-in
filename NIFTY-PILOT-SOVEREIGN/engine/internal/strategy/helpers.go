package strategy

import "niftypilot/internal/marketdata"

func closesOf(candles []marketdata.Candle) []float64 {
	out := make([]float64, len(candles))
	for i, c := range candles {
		out[i] = c.Close
	}
	return out
}
