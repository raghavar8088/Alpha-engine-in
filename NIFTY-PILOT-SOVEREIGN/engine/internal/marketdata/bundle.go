package marketdata

import (
	"sync"
	"time"
)

const ringCap1m = 1500  // ~6 trading days of 1m bars
const ringCap5m = 1500
const ringCap15m = 1500
const ringCap1h = 1500

// NiftyDataBundle is the single in-memory market-data store all
// strategies and the regime classifier read from. It is the
// India-market equivalent of the BTC engine's ScalerBundle: every
// goroutine-accessed field is protected by mu, and buffers are warmed
// up before market open so strategies never operate on an empty
// history on the first tick of the session.
type NiftyDataBundle struct {
	mu sync.RWMutex

	spotCandles1m  map[string][]Candle // keyed by underlying: "NIFTY" | "BANKNIFTY"
	spotCandles5m  map[string][]Candle
	spotCandles15m map[string][]Candle
	spotCandles1h  map[string][]Candle

	spotPrice map[string]float64
	prevClose map[string]float64

	indiaVIX        float64
	indiaVIXHistory [5]float64
	vixIdx          int

	optionChain map[string]OptionChainSnapshot // keyed by underlying

	lastTickAt map[string]time.Time // data-feed staleness tracking
}

func NewNiftyDataBundle() *NiftyDataBundle {
	return &NiftyDataBundle{
		spotCandles1m:  map[string][]Candle{},
		spotCandles5m:  map[string][]Candle{},
		spotCandles15m: map[string][]Candle{},
		spotCandles1h:  map[string][]Candle{},
		spotPrice:      map[string]float64{},
		prevClose:      map[string]float64{},
		optionChain:    map[string]OptionChainSnapshot{},
		lastTickAt:     map[string]time.Time{},
	}
}

func pushCapped(buf []Candle, c Candle, cap int) []Candle {
	buf = append(buf, c)
	if len(buf) > cap {
		buf = buf[len(buf)-cap:]
	}
	return buf
}

// SeedCandles bulk-loads historical bars during the pre-market warmup
// phase, so strategies have full lookback (EMA200, ATR14, etc.) ready
// before the first live tick at 09:15 IST.
func (b *NiftyDataBundle) SeedCandles(underlying, timeframe string, candles []Candle) {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch timeframe {
	case "1m":
		b.spotCandles1m[underlying] = candles
	case "5m":
		b.spotCandles5m[underlying] = candles
	case "15m":
		b.spotCandles15m[underlying] = candles
	case "1h":
		b.spotCandles1h[underlying] = candles
	}
}

func (b *NiftyDataBundle) PushCandle(underlying, timeframe string, c Candle) {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch timeframe {
	case "1m":
		b.spotCandles1m[underlying] = pushCapped(b.spotCandles1m[underlying], c, ringCap1m)
	case "5m":
		b.spotCandles5m[underlying] = pushCapped(b.spotCandles5m[underlying], c, ringCap5m)
	case "15m":
		b.spotCandles15m[underlying] = pushCapped(b.spotCandles15m[underlying], c, ringCap15m)
	case "1h":
		b.spotCandles1h[underlying] = pushCapped(b.spotCandles1h[underlying], c, ringCap1h)
	}
}

func (b *NiftyDataBundle) Candles(underlying, timeframe string) []Candle {
	b.mu.RLock()
	defer b.mu.RUnlock()
	var src []Candle
	switch timeframe {
	case "1m":
		src = b.spotCandles1m[underlying]
	case "5m":
		src = b.spotCandles5m[underlying]
	case "15m":
		src = b.spotCandles15m[underlying]
	case "1h":
		src = b.spotCandles1h[underlying]
	}
	out := make([]Candle, len(src))
	copy(out, src)
	return out
}

func (b *NiftyDataBundle) SetSpot(underlying string, price float64, at time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.spotPrice[underlying] = price
	b.lastTickAt[underlying] = at
}

func (b *NiftyDataBundle) Spot(underlying string) float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.spotPrice[underlying]
}

func (b *NiftyDataBundle) SetPrevClose(underlying string, price float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.prevClose[underlying] = price
}

func (b *NiftyDataBundle) PrevClose(underlying string) float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.prevClose[underlying]
}

func (b *NiftyDataBundle) SetIndiaVIX(v float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.indiaVIX = v
	b.indiaVIXHistory[b.vixIdx%5] = v
	b.vixIdx++
}

func (b *NiftyDataBundle) IndiaVIX() float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.indiaVIX
}

func (b *NiftyDataBundle) IndiaVIXHistory() [5]float64 {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.indiaVIXHistory
}

func (b *NiftyDataBundle) SetOptionChain(underlying string, snap OptionChainSnapshot) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.optionChain[underlying] = snap
	b.lastTickAt[underlying+":chain"] = snap.FetchedAt
}

func (b *NiftyDataBundle) OptionChain(underlying string) OptionChainSnapshot {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.optionChain[underlying]
}

// StaleSince returns how long it has been since the last tick for the
// given feed key ("NIFTY", "BANKNIFTY", "NIFTY:chain", ...). Used by
// the observability layer's data-feed health check.
func (b *NiftyDataBundle) StaleSince(feedKey string, now time.Time) time.Duration {
	b.mu.RLock()
	defer b.mu.RUnlock()
	last, ok := b.lastTickAt[feedKey]
	if !ok {
		return time.Duration(1<<63 - 1)
	}
	return now.Sub(last)
}
