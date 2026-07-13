// Package indicators provides the shared technical-analysis primitives
// used by both the regime classifier and the strategy suite, so every
// consumer computes EMA/ATR/ADX/VWAP the same way (the BTC system found
// that divergent indicator math between subsystems caused mistimed
// entries — keep ONE implementation of each indicator).
package indicators

import "niftypilot/internal/marketdata"

// EMA returns the exponential moving average series for period over
// closes. Returns nil if there is insufficient data.
func EMA(closes []float64, period int) []float64 {
	if len(closes) < period {
		return nil
	}
	out := make([]float64, len(closes))
	k := 2.0 / (float64(period) + 1.0)
	var sum float64
	for i := 0; i < period; i++ {
		sum += closes[i]
	}
	out[period-1] = sum / float64(period)
	for i := period; i < len(closes); i++ {
		out[i] = closes[i]*k + out[i-1]*(1-k)
	}
	return out
}

// LastEMA returns just the most recent EMA value, or 0 if insufficient data.
func LastEMA(closes []float64, period int) float64 {
	e := EMA(closes, period)
	if len(e) == 0 {
		return 0
	}
	return e[len(e)-1]
}

// TrueRange computes the per-bar true range series from candles.
func TrueRange(candles []marketdata.Candle) []float64 {
	if len(candles) < 2 {
		return nil
	}
	tr := make([]float64, len(candles))
	tr[0] = candles[0].High - candles[0].Low
	for i := 1; i < len(candles); i++ {
		h, l, pc := candles[i].High, candles[i].Low, candles[i-1].Close
		v := h - l
		if d := abs(h - pc); d > v {
			v = d
		}
		if d := abs(l - pc); d > v {
			v = d
		}
		tr[i] = v
	}
	return tr
}

// ATR returns the most recent Wilder-smoothed Average True Range over period.
func ATR(candles []marketdata.Candle, period int) float64 {
	tr := TrueRange(candles)
	if len(tr) < period {
		return 0
	}
	var sum float64
	for i := 0; i < period; i++ {
		sum += tr[i]
	}
	atr := sum / float64(period)
	for i := period; i < len(tr); i++ {
		atr = (atr*(float64(period)-1) + tr[i]) / float64(period)
	}
	return atr
}

// ADX returns the most recent Average Directional Index over period.
// Standard Wilder ADX(14) implementation.
func ADX(candles []marketdata.Candle, period int) float64 {
	if len(candles) < period*2 {
		return 0
	}
	n := len(candles)
	plusDM := make([]float64, n)
	minusDM := make([]float64, n)
	tr := TrueRange(candles)
	for i := 1; i < n; i++ {
		upMove := candles[i].High - candles[i-1].High
		downMove := candles[i-1].Low - candles[i].Low
		if upMove > downMove && upMove > 0 {
			plusDM[i] = upMove
		}
		if downMove > upMove && downMove > 0 {
			minusDM[i] = downMove
		}
	}
	smooth := func(series []float64) []float64 {
		out := make([]float64, len(series))
		var sum float64
		for i := 1; i <= period; i++ {
			sum += series[i]
		}
		out[period] = sum
		for i := period + 1; i < len(series); i++ {
			out[i] = out[i-1] - out[i-1]/float64(period) + series[i]
		}
		return out
	}
	smPlus := smooth(plusDM)
	smMinus := smooth(minusDM)
	smTR := smooth(tr)

	dx := make([]float64, n)
	for i := period; i < n; i++ {
		if smTR[i] == 0 {
			continue
		}
		pdi := 100 * smPlus[i] / smTR[i]
		mdi := 100 * smMinus[i] / smTR[i]
		if pdi+mdi == 0 {
			continue
		}
		dx[i] = 100 * abs(pdi-mdi) / (pdi + mdi)
	}
	start := period * 2
	if start >= n {
		start = n - 1
	}
	var sum float64
	count := 0
	for i := period; i <= start && i < n; i++ {
		sum += dx[i]
		count++
	}
	if count == 0 {
		return 0
	}
	adx := sum / float64(count)
	for i := start + 1; i < n; i++ {
		adx = (adx*(float64(period)-1) + dx[i]) / float64(period)
	}
	return adx
}

// VWAP computes the session volume-weighted average price over the
// supplied candles (caller passes only the bars from the current
// session's 09:15 open onward).
func VWAP(candles []marketdata.Candle) float64 {
	var pv, vol float64
	for _, c := range candles {
		typical := (c.High + c.Low + c.Close) / 3
		pv += typical * c.Volume
		vol += c.Volume
	}
	if vol == 0 {
		return 0
	}
	return pv / vol
}

func abs(f float64) float64 {
	if f < 0 {
		return -f
	}
	return f
}

// RSI returns the most recent Wilder RSI over period.
// Returns 50 (neutral) if insufficient data.
func RSI(closes []float64, period int) float64 {
	if len(closes) < period+1 {
		return 50
	}
	var avgGain, avgLoss float64
	for i := 1; i <= period; i++ {
		d := closes[i] - closes[i-1]
		if d > 0 {
			avgGain += d
		} else {
			avgLoss += -d
		}
	}
	avgGain /= float64(period)
	avgLoss /= float64(period)
	for i := period + 1; i < len(closes); i++ {
		d := closes[i] - closes[i-1]
		if d > 0 {
			avgGain = (avgGain*float64(period-1) + d) / float64(period)
			avgLoss = (avgLoss * float64(period-1)) / float64(period)
		} else {
			avgLoss = (avgLoss*float64(period-1) + (-d)) / float64(period)
			avgGain = (avgGain * float64(period-1)) / float64(period)
		}
	}
	if avgLoss == 0 {
		return 100
	}
	rs := avgGain / avgLoss
	return 100 - 100/(1+rs)
}

// MACDHistogram returns the MACD histogram (MACD line minus signal line)
// using standard 12/26/9 parameters. Returns 0 if insufficient data.
func MACDHistogram(closes []float64) float64 {
	if len(closes) < 35 {
		return 0
	}
	fast := EMA(closes, 12)
	slow := EMA(closes, 26)
	if len(fast) == 0 || len(slow) == 0 {
		return 0
	}
	macdLine := make([]float64, len(closes))
	for i := 25; i < len(closes); i++ {
		macdLine[i] = fast[i] - slow[i]
	}
	signal := EMA(macdLine[25:], 9)
	if len(signal) == 0 {
		return 0
	}
	lastMACD := macdLine[len(macdLine)-1]
	lastSig := signal[len(signal)-1]
	return lastMACD - lastSig
}

// BollingerBands returns (upper, middle, lower) for the last candle
// using period and stddev multiplier. Returns zeros if insufficient data.
func BollingerBands(closes []float64, period int, mult float64) (upper, middle, lower float64) {
	if len(closes) < period {
		return 0, 0, 0
	}
	window := closes[len(closes)-period:]
	var sum float64
	for _, v := range window {
		sum += v
	}
	mid := sum / float64(period)
	var variance float64
	for _, v := range window {
		d := v - mid
		variance += d * d
	}
	stddev := 0.0
	if period > 1 {
		v := variance / float64(period)
		stddev = 0.0
		// Newton-Raphson sqrt
		x := v
		for i := 0; i < 20; i++ {
			x = (x + v/x) / 2
		}
		stddev = x
	}
	return mid + mult*stddev, mid, mid - mult*stddev
}

// BollingerWidth returns the bandwidth (upper-lower)/middle, normalised.
// Used to detect squeezes: smaller value = tighter bands.
func BollingerWidth(closes []float64, period int, mult float64) float64 {
	u, m, l := BollingerBands(closes, period, mult)
	if m == 0 {
		return 0
	}
	return (u - l) / m
}

// AvgVolume returns the mean volume over the last n candles.
func AvgVolume(candles []marketdata.Candle, n int) float64 {
	if len(candles) < n {
		n = len(candles)
	}
	if n == 0 {
		return 0
	}
	var sum float64
	for _, c := range candles[len(candles)-n:] {
		sum += c.Volume
	}
	return sum / float64(n)
}

// PDI and MDI return the last +DI and -DI components of Wilder's ADX.
// Used by strategies that need directional discrimination, not just ADX magnitude.
func PDIMDI(candles []marketdata.Candle, period int) (pdi, mdi float64) {
	if len(candles) < period*2 {
		return 0, 0
	}
	n := len(candles)
	plusDM := make([]float64, n)
	minusDM := make([]float64, n)
	tr := TrueRange(candles)
	for i := 1; i < n; i++ {
		up := candles[i].High - candles[i-1].High
		dn := candles[i-1].Low - candles[i].Low
		if up > dn && up > 0 {
			plusDM[i] = up
		}
		if dn > up && dn > 0 {
			minusDM[i] = dn
		}
	}
	smooth := func(s []float64) []float64 {
		out := make([]float64, len(s))
		var sum float64
		for i := 1; i <= period; i++ {
			sum += s[i]
		}
		out[period] = sum
		for i := period + 1; i < len(s); i++ {
			out[i] = out[i-1] - out[i-1]/float64(period) + s[i]
		}
		return out
	}
	smP := smooth(plusDM)
	smM := smooth(minusDM)
	smT := smooth(tr)
	last := n - 1
	if smT[last] == 0 {
		return 0, 0
	}
	return 100 * smP[last] / smT[last], 100 * smM[last] / smT[last]
}

// MinBollingerWidth returns the minimum Bollinger width over the last n windows
// of size period. Used to identify squeeze: is the current width the narrowest recently?
func MinBollingerWidth(closes []float64, period int, mult float64, lookback int) float64 {
	if len(closes) < period+lookback {
		return 0
	}
	minW := abs(BollingerWidth(closes, period, mult)) + 1
	for i := lookback; i >= 1; i-- {
		end := len(closes) - i + 1
		if end < period {
			continue
		}
		w := BollingerWidth(closes[:end], period, mult)
		if w < minW {
			minW = w
		}
	}
	return minW
}
