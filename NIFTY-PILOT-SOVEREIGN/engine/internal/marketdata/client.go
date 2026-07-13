package marketdata

import (
	"context"
	"errors"
	"math"
	"math/rand"
	"time"
)

// Feed is the broker-agnostic market-data interface every concrete
// client (AngelOne SmartAPI, Zerodha Kite, Upstox) must implement.
// Strategies and the data warmup loop talk to this interface only, so
// swapping brokers never touches strategy code.
//
// BROKER CHOSEN: AngelOne SmartAPI. Reasoning (documented in final
// report): free tier with no recurring API fee (Kite Connect is a paid
// ~Rs 2000/mo API; Upstox free tier has a lower-resolution options
// chain), websocket tick feed, REST option-chain endpoint with OI, and
// it is already the broker integrated in the reference BTC-adjacent
// repo's AngelOne client (engine/internal/.../angelone), so connection
// patterns, TOTP login flow, and rate-limit handling are proven.
type Feed interface {
	// Connect establishes the websocket tick session and authenticates
	// the REST session (TOTP login flow).
	Connect(ctx context.Context) error

	// SubscribeSpot streams LTP ticks for an underlying ("NIFTY",
	// "BANKNIFTY", "INDIAVIX") to the returned channel.
	SubscribeSpot(ctx context.Context, underlying string) (<-chan Tick, error)

	// HistoricalCandles fetches OHLCV bars for warmup buffers.
	HistoricalCandles(ctx context.Context, underlying, timeframe string, from, to time.Time) ([]Candle, error)

	// OptionChain fetches the full chain (OI, Greeks, quotes) for the
	// nearest weekly expiry of the given underlying.
	OptionChain(ctx context.Context, underlying string) (OptionChainSnapshot, error)

	// Close releases the websocket/session.
	Close() error
}

// Tick is a single LTP update.
type Tick struct {
	Underlying string
	LTP        float64
	Time       time.Time
}

var ErrNotImplemented = errors.New("marketdata: broker client method not implemented in this build")

// AngelOneFeed is the concrete AngelOne SmartAPI client. Network calls
// are stubbed pending API-key provisioning (ANGELONE_API_KEY,
// ANGELONE_CLIENT_CODE, ANGELONE_PIN, ANGELONE_TOTP_SECRET) — wiring
// the TOTP login + websocket parsing is an OPEN ITEM, see final report.
type AngelOneFeed struct {
	APIKey      string
	ClientCode  string
	PIN         string
	TOTPSecret  string
}

func NewAngelOneFeed(apiKey, clientCode, pin, totpSecret string) *AngelOneFeed {
	return &AngelOneFeed{APIKey: apiKey, ClientCode: clientCode, PIN: pin, TOTPSecret: totpSecret}
}

func (f *AngelOneFeed) Connect(ctx context.Context) error { return ErrNotImplemented }

func (f *AngelOneFeed) SubscribeSpot(ctx context.Context, underlying string) (<-chan Tick, error) {
	return nil, ErrNotImplemented
}

func (f *AngelOneFeed) HistoricalCandles(ctx context.Context, underlying, timeframe string, from, to time.Time) ([]Candle, error) {
	return nil, ErrNotImplemented
}

func (f *AngelOneFeed) OptionChain(ctx context.Context, underlying string) (OptionChainSnapshot, error) {
	return OptionChainSnapshot{}, ErrNotImplemented
}

func (f *AngelOneFeed) Close() error { return nil }

// SyntheticFeed is a deterministic offline data generator used for
// local development, unit tests, and the backtest/replay harness when
// no live broker session is available. It never touches the network.
type SyntheticFeed struct {
	seedPrice map[string]float64
}

func NewSyntheticFeed() *SyntheticFeed {
	return &SyntheticFeed{seedPrice: map[string]float64{
		"NIFTY":     24800,
		"BANKNIFTY": 52600,
		"INDIAVIX":  13.5,
	}}
}

func (f *SyntheticFeed) Connect(ctx context.Context) error { return nil }

func (f *SyntheticFeed) SubscribeSpot(ctx context.Context, underlying string) (<-chan Tick, error) {
	ch := make(chan Tick, 16)
	go func() {
		defer close(ch)
		rng := rand.New(rand.NewSource(time.Now().UnixNano() ^ int64(len(underlying))))
		price := f.seedPrice[underlying]
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case t := <-ticker.C:
				price += randomWalkStep(price, underlying, rng)
				ch <- Tick{Underlying: underlying, LTP: price, Time: t}
			}
		}
	}()
	return ch, nil
}

// randomWalkStep returns a small Gaussian price increment. India VIX is
// mean-reverting around its seed rather than a pure random walk, since
// an unbounded walk would eventually drift VIX into nonsensical
// territory for a dev/synthetic feed.
func randomWalkStep(price float64, underlying string, rng *rand.Rand) float64 {
	volBps := 2.0 // ~2bps per second jitter, deliberately small for a synthetic dev feed
	step := price * (volBps / 10000.0) * rng.NormFloat64()
	if underlying == "INDIAVIX" {
		meanReversion := (13.5 - price) * 0.01
		return step*0.3 + meanReversion
	}
	return step
}

// HistoricalCandles generates a deterministic synthetic OHLCV series
// for local dev/testing so warmup buffers are never empty when running
// against SyntheticFeed. NOT real market data — swap to AngelOneFeed
// for anything beyond pipeline smoke-testing.
func (f *SyntheticFeed) HistoricalCandles(ctx context.Context, underlying, timeframe string, from, to time.Time) ([]Candle, error) {
	step := timeframeDuration(timeframe)
	if step <= 0 || !to.After(from) {
		return nil, nil
	}
	n := int(to.Sub(from) / step)
	if n < 1 {
		return nil, nil
	}
	if n > 2000 {
		n = 2000
	}
	rng := rand.New(rand.NewSource(42 ^ int64(len(underlying)+len(timeframe))))
	price := f.seedPrice[underlying]
	if price == 0 {
		price = 20000
	}
	start := to.Add(-time.Duration(n) * step)
	candles := make([]Candle, 0, n)
	for i := 0; i < n; i++ {
		open := price
		drift := open * 0.0006 * rng.NormFloat64()
		high := open + math.Abs(drift)*1.4 + open*0.0002*rng.Float64()
		low := open - math.Abs(drift)*1.4 - open*0.0002*rng.Float64()
		close := open + drift
		if close > high {
			high = close
		}
		if close < low {
			low = close
		}
		vol := 50000 + rng.Float64()*50000
		candles = append(candles, Candle{
			Time: start.Add(time.Duration(i) * step), Open: open, High: high, Low: low, Close: close, Volume: vol,
		})
		price = close
	}
	return candles, nil
}

func timeframeDuration(tf string) time.Duration {
	switch tf {
	case "1m":
		return time.Minute
	case "5m":
		return 5 * time.Minute
	case "15m":
		return 15 * time.Minute
	case "1h":
		return time.Hour
	default:
		return 0
	}
}

// OptionChain generates a synthetic strikes ladder around the current
// seed spot so option-chain-dependent strategies (S3/S4/S5/S6/S9) have
// non-empty data to evaluate against in dev/synthetic mode. NOT real
// market data.
func (f *SyntheticFeed) OptionChain(ctx context.Context, underlying string) (OptionChainSnapshot, error) {
	spot := f.seedPrice[underlying]
	if spot == 0 {
		spot = 20000
	}
	stepSize := 50.0
	if underlying == "BANKNIFTY" {
		stepSize = 100.0
	}
	rng := rand.New(rand.NewSource(7 ^ int64(len(underlying))))
	atmStrike := math.Round(spot/stepSize) * stepSize

	var strikes []StrikeData
	for i := -10; i <= 10; i++ {
		strike := atmStrike + float64(i)*stepSize
		moneyness := (strike - spot) / spot
		for _, optType := range []string{"CE", "PE"} {
			iv := 0.13 + math.Abs(moneyness)*0.6 + rng.Float64()*0.01
			intrinsic := 0.0
			if optType == "CE" && spot > strike {
				intrinsic = spot - strike
			}
			if optType == "PE" && spot < strike {
				intrinsic = strike - spot
			}
			timeValue := spot * iv * 0.02 * (1 - math.Abs(moneyness)*2)
			if timeValue < 1 {
				timeValue = 1
			}
			ltp := intrinsic + timeValue
			oi := int64(50000 + rng.Float64()*200000 - math.Abs(float64(i))*8000)
			if oi < 1000 {
				oi = 1000
			}
			strikes = append(strikes, StrikeData{
				Strike: strike, OptionType: optType, LTP: ltp,
				BidPrice: ltp * 0.995, BidQty: oi / 20,
				AskPrice: ltp * 1.005, AskQty: oi / 20,
				OI: oi, OIChange: int64(rng.NormFloat64() * 5000),
				Volume: oi / 5,
				Greeks: Greeks{IV: iv},
			})
		}
	}
	return OptionChainSnapshot{Underlying: underlying, SpotPrice: spot, Strikes: strikes, FetchedAt: time.Now()}, nil
}

func (f *SyntheticFeed) Close() error { return nil }
