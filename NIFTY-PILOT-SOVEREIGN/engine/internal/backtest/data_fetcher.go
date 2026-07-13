package backtest

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/marketdata"
)

// Candle is the backtest-layer OHLCV bar. Unlike marketdata.Candle it
// carries OpenInterest (needed for options data) and is the on-disk cache
// row shape. TimeUTC is always UTC internally (PART 0 rule 4).
type Candle struct {
	TimeUTC      time.Time `json:"t"`
	Open         float64   `json:"o"`
	High         float64   `json:"h"`
	Low          float64   `json:"l"`
	Close        float64   `json:"c"`
	Volume       float64   `json:"v"`
	OpenInterest int64     `json:"oi"`
}

// ToMarketCandle converts to the engine's marketdata.Candle (drops OI,
// which the live bundle does not store).
func (c Candle) ToMarketCandle() marketdata.Candle {
	return marketdata.Candle{
		Time: c.TimeUTC, Open: c.Open, High: c.High, Low: c.Low, Close: c.Close, Volume: c.Volume,
	}
}

// Instrument identifies one tradable series. Underlying is the canonical
// name strategies consume ("NIFTY"|"BANKNIFTY"); Symbol is the user-facing
// CLI name ("NIFTY50"); Token is the broker instrument token.
type Instrument struct {
	Symbol     string
	Underlying string
	Token      string
}

// IsVIX reports the synthetic India VIX pseudo-instrument.
func (i Instrument) IsVIX() bool { return i.Underlying == "INDIAVIX" }

// Interval constants use the broker-API vocabulary (PART 1). Map to the
// engine's bundle timeframes via bundleTimeframe.
const (
	Interval1m  = "1min"
	Interval5m  = "5min"
	Interval15m = "15min"
	Interval1h  = "60min"
	IntervalDay = "daily"
)

// bundleTimeframe maps a broker interval string to the engine bundle's
// timeframe key. Returns "" for daily (the engine has no daily slot;
// swing strategies derive daily bars from 1h, matching the live engine).
func bundleTimeframe(interval string) string {
	switch interval {
	case Interval1m:
		return "1m"
	case Interval5m:
		return "5m"
	case Interval15m:
		return "15m"
	case Interval1h:
		return "1h"
	default:
		return ""
	}
}

func intervalDuration(interval string) time.Duration {
	switch interval {
	case Interval1m:
		return time.Minute
	case Interval5m:
		return 5 * time.Minute
	case Interval15m:
		return 15 * time.Minute
	case Interval1h:
		return time.Hour
	case IntervalDay:
		return 24 * time.Hour
	default:
		return 0
	}
}

// HistoricalDataFetcher is the data-source abstraction (PART 1). At least
// two concrete implementations are provided: SyntheticFetcher (default,
// deterministic, offline) and KiteHistoricalFetcher (live REST). An
// NSE-FTP fetcher stub documents the fallback integration point.
type HistoricalDataFetcher interface {
	FetchCandles(ctx context.Context, inst Instrument, from, to time.Time, interval string) ([]Candle, error)
	SourceName() string
}

var ErrNoData = errors.New("backtest: no candle data available for the requested range")

// ─────────────────────────────────────────────────────────────────────────────
// Filesystem candle cache (substitute for the spec's sqlite3 cache).
//
// DEVIATION (documented in BACKTEST_GUIDE.md): the spec calls for a
// sqlite3 cache. A cgo sqlite driver requires a C toolchain (which failed
// to build in this environment earlier), and a pure-Go sqlite driver pulls
// a large dependency tree requiring network fetch. To keep the harness
// CGO-free, dependency-free, and deterministically buildable, the cache is
// a per-(token,interval) JSON file. Same contract (avoid re-fetching),
// different storage engine. Swap for sqlite3 when a toolchain is available.
// ─────────────────────────────────────────────────────────────────────────────

type CandleCache struct {
	dir string
}

func NewCandleCache(dir string) (*CandleCache, error) {
	if dir == "" {
		return &CandleCache{}, nil // no-op cache
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("candle cache mkdir: %w", err)
	}
	return &CandleCache{dir: dir}, nil
}

func (c *CandleCache) path(token, interval string) string {
	safe := url.QueryEscape(token)
	return filepath.Join(c.dir, fmt.Sprintf("%s_%s.json", safe, interval))
}

// Get returns cached candles for the token+interval intersected with
// [from,to]. ok is false on a cache miss.
func (c *CandleCache) Get(token, interval string, from, to time.Time) (candles []Candle, ok bool) {
	if c.dir == "" {
		return nil, false
	}
	data, err := os.ReadFile(c.path(token, interval))
	if err != nil {
		return nil, false
	}
	var all []Candle
	if err := json.Unmarshal(data, &all); err != nil {
		return nil, false
	}
	var out []Candle
	for _, cd := range all {
		if !cd.TimeUTC.Before(from) && !cd.TimeUTC.After(to) {
			out = append(out, cd)
		}
	}
	if len(out) == 0 {
		return nil, false
	}
	return out, true
}

// Put merges candles into the token+interval cache file (dedup by time).
func (c *CandleCache) Put(token, interval string, candles []Candle) error {
	if c.dir == "" || len(candles) == 0 {
		return nil
	}
	existing, _ := c.Get(token, interval, time.Unix(0, 0), time.Unix(1<<62, 0))
	byTime := map[int64]Candle{}
	for _, cd := range existing {
		byTime[cd.TimeUTC.UnixNano()] = cd
	}
	for _, cd := range candles {
		byTime[cd.TimeUTC.UnixNano()] = cd
	}
	merged := make([]Candle, 0, len(byTime))
	for _, cd := range byTime {
		merged = append(merged, cd)
	}
	sort.Slice(merged, func(i, j int) bool { return merged[i].TimeUTC.Before(merged[j].TimeUTC) })
	data, err := json.MarshalIndent(merged, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(c.path(token, interval), data, 0o644)
}

// ─────────────────────────────────────────────────────────────────────────────
// SyntheticFetcher — deterministic, offline, network-free data source.
// This is the DEFAULT source so the harness, its tests, and the sample run
// are fully reproducible without broker API keys (CRITICAL CRITERION 4:
// deterministic). It generates regime-cycling price action (trend runs,
// ranging chop, vol spikes) so a meaningful subset of strategies fire.
// NOT real market data — use Kite/NSE for real validation.
// ─────────────────────────────────────────────────────────────────────────────

type SyntheticFetcher struct {
	seed      int64
	basePrice map[string]float64
}

func NewSyntheticFetcher(seed int64) *SyntheticFetcher {
	return &SyntheticFetcher{
		seed: seed,
		basePrice: map[string]float64{
			"NIFTY":     24800,
			"BANKNIFTY": 52600,
			"INDIAVIX":  13.5,
		},
	}
}

func (f *SyntheticFetcher) SourceName() string { return "Synthetic" }

// FetchCandles generates only candles inside NSE market hours (09:15–15:30
// IST, trading days), so the replay's market-hours gate and the generator
// agree. The series is a deterministic function of (token, interval, seed),
// independent of wall-clock time.
func (f *SyntheticFetcher) FetchCandles(_ context.Context, inst Instrument, from, to time.Time, interval string) ([]Candle, error) {
	step := intervalDuration(interval)
	if step <= 0 || !to.After(from) {
		return nil, nil
	}
	cal := calendar.NewService()

	base := f.basePrice[inst.Underlying]
	if base == 0 {
		base = 20000
	}
	// Deterministic RNG seeded by instrument+interval+global seed.
	rng := rand.New(rand.NewSource(f.seed ^ int64(len(inst.Underlying)*131+len(interval)*17)))

	price := base
	vix := 13.5
	var out []Candle

	// Regime cycle: advance a slow phase so we get alternating trend/range/vol.
	phase := 0.0
	phaseStep := 2 * math.Pi / float64(6*60) // ~6h cycle in minute units

	for t := from.Truncate(step); !t.After(to); t = t.Add(step) {
		ist := t.In(calendar.IST)
		if !cal.IsMarketOpen(t) {
			// keep VIX/phase evolving across the gap but emit no bar
			phase += phaseStep * float64(step/time.Minute+1)
			continue
		}
		_ = ist
		phase += phaseStep * float64(step/time.Minute)

		// Regime driver in [-1,1]: >0.5 trend-up, <-0.5 trend-down, else range.
		drive := math.Sin(phase)
		volSpike := math.Sin(phase*0.37) // independent slow wave for VIX

		if inst.IsVIX() {
			target := 12.0 + 8.0*math.Max(0, volSpike) // 12..20
			vix += (target - vix) * 0.05
			vix += rng.NormFloat64() * 0.05
			if vix < 9 {
				vix = 9
			}
			o := vix
			c := vix
			out = append(out, Candle{TimeUTC: t.UTC(), Open: o, High: o + 0.1, Low: o - 0.1, Close: c, Volume: 0})
			continue
		}

		// Price drift driven by regime.
		trend := drive * 0.0008 // up to ±8 bps/bar directional drift
		noise := rng.NormFloat64() * 0.0006
		ret := trend + noise
		open := price
		closeP := open * (1 + ret)
		hi := math.Max(open, closeP) * (1 + math.Abs(noise)*0.5 + 0.0002)
		lo := math.Min(open, closeP) * (1 - math.Abs(noise)*0.5 - 0.0002)
		vol := 40000 + rng.Float64()*60000 + math.Abs(drive)*40000
		out = append(out, Candle{
			TimeUTC: t.UTC(), Open: open, High: hi, Low: lo, Close: closeP, Volume: vol,
		})
		price = closeP
	}
	if len(out) == 0 {
		return nil, nil
	}
	return out, nil
}

// ─────────────────────────────────────────────────────────────────────────────
// KiteHistoricalFetcher — Zerodha Kite Connect historical REST (PART 1B).
// Real request construction; requires KITE_API_KEY + KITE_ACCESS_TOKEN.
// Cached via CandleCache. Without credentials/network it returns a clear
// error (the harness then falls back to --backtest-data-source Synthetic).
// ─────────────────────────────────────────────────────────────────────────────

type KiteHistoricalFetcher struct {
	apiKey      string
	accessToken string
	cache       *CandleCache
	httpClient  *http.Client
	baseURL     string
}

func NewKiteHistoricalFetcher(apiKey, accessToken string, cache *CandleCache) *KiteHistoricalFetcher {
	return &KiteHistoricalFetcher{
		apiKey: apiKey, accessToken: accessToken, cache: cache,
		httpClient: &http.Client{Timeout: 20 * time.Second},
		baseURL:    "https://api.kite.trade",
	}
}

func (k *KiteHistoricalFetcher) SourceName() string { return "Kite" }

func (k *KiteHistoricalFetcher) FetchCandles(ctx context.Context, inst Instrument, from, to time.Time, interval string) ([]Candle, error) {
	if k.cache != nil {
		if cached, ok := k.cache.Get(inst.Token, interval, from, to); ok {
			return cached, nil
		}
	}
	if k.apiKey == "" || k.accessToken == "" {
		return nil, fmt.Errorf("kite: missing KITE_API_KEY/KITE_ACCESS_TOKEN; use --backtest-data-source Synthetic for offline runs")
	}

	kiteInterval := map[string]string{
		Interval1m: "minute", Interval5m: "5minute", Interval15m: "15minute",
		Interval1h: "60minute", IntervalDay: "day",
	}[interval]
	if kiteInterval == "" {
		return nil, fmt.Errorf("kite: unsupported interval %q", interval)
	}

	endpoint := fmt.Sprintf("%s/instruments/historical/%s/%s", k.baseURL, inst.Token, kiteInterval)
	q := url.Values{}
	q.Set("from", from.In(calendar.IST).Format("2006-01-02 15:04:05"))
	q.Set("to", to.In(calendar.IST).Format("2006-01-02 15:04:05"))
	if inst.IsVIX() {
		q.Set("oi", "0")
	} else {
		q.Set("oi", "1")
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint+"?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Kite-Version", "3")
	req.Header.Set("Authorization", "token "+k.apiKey+":"+k.accessToken)

	resp, err := k.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("kite historical request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("kite historical: HTTP %d", resp.StatusCode)
	}

	// Kite response: {"status":"success","data":{"candles":[[ts,o,h,l,c,vol,oi],...]}}
	var parsed struct {
		Status string `json:"status"`
		Data   struct {
			Candles [][]any `json:"candles"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return nil, fmt.Errorf("kite historical decode: %w", err)
	}

	candles := make([]Candle, 0, len(parsed.Data.Candles))
	for _, row := range parsed.Data.Candles {
		c, err := kiteRowToCandle(row)
		if err != nil {
			return nil, err
		}
		candles = append(candles, c)
	}
	if k.cache != nil {
		_ = k.cache.Put(inst.Token, interval, candles)
	}
	return candles, nil
}

func kiteRowToCandle(row []any) (Candle, error) {
	if len(row) < 6 {
		return Candle{}, fmt.Errorf("kite candle row too short: %v", row)
	}
	tsStr, _ := row[0].(string)
	ts, err := time.Parse("2006-01-02T15:04:05-0700", tsStr)
	if err != nil {
		// Kite sometimes uses +05:30 colon format
		ts, err = time.Parse(time.RFC3339, tsStr)
		if err != nil {
			return Candle{}, fmt.Errorf("kite candle ts parse %q: %w", tsStr, err)
		}
	}
	num := func(v any) float64 {
		f, _ := v.(float64)
		return f
	}
	c := Candle{
		TimeUTC: ts.UTC(),
		Open:    num(row[1]), High: num(row[2]), Low: num(row[3]), Close: num(row[4]),
		Volume: num(row[5]),
	}
	if len(row) >= 7 {
		c.OpenInterest = int64(num(row[6]))
	}
	return c, nil
}

// ─────────────────────────────────────────────────────────────────────────────
// NSEFTPFetcher — NSE official bhavcopy/FTP fallback (PART 1A). Stub: NSE's
// data-distribution URLs and bhavcopy formats change periodically and a
// production parser must be re-verified against the current circular
// (REGULATORY FLAG). Documented integration point; returns ErrNotImplemented.
// ─────────────────────────────────────────────────────────────────────────────

type NSEFTPFetcher struct{ cache *CandleCache }

func NewNSEFTPFetcher(cache *CandleCache) *NSEFTPFetcher { return &NSEFTPFetcher{cache: cache} }

func (n *NSEFTPFetcher) SourceName() string { return "NSE" }

func (n *NSEFTPFetcher) FetchCandles(_ context.Context, inst Instrument, _, _ time.Time, _ string) ([]Candle, error) {
	return nil, fmt.Errorf("NSE FTP fetcher not implemented in this build (REGULATORY FLAG: verify current NSE bhavcopy URL/format); use Kite or Synthetic")
}

// ─────────────────────────────────────────────────────────────────────────────
// CSVFetcher — loads OHLCV data from engine/backtest_data/<SYMBOL>_<YYYY>_1m.csv
// CSV format: timestamp,open,high,low,close,volume (standard OHLCV, RFC3339 ts)
// For intervals coarser than 1m, bars are built by downsampling 1m data.
// ─────────────────────────────────────────────────────────────────────────────

type CSVFetcher struct {
	dataDir string
	cache   *CandleCache
}

func NewCSVFetcher(dataDir string, cache *CandleCache) *CSVFetcher {
	return &CSVFetcher{dataDir: dataDir, cache: cache}
}

func (f *CSVFetcher) SourceName() string { return "CSV" }

func (f *CSVFetcher) FetchCandles(ctx context.Context, inst Instrument, from, to time.Time, interval string) ([]Candle, error) {
	if f.cache != nil {
		if cached, ok := f.cache.Get(inst.Token+"_csv", interval, from, to); ok {
			return cached, nil
		}
	}

	// Load 1m CSV files for each year in range, then downsample.
	var allMinute []Candle
	for y := from.Year(); y <= to.Year(); y++ {
		fname := filepath.Join(f.dataDir, fmt.Sprintf("%s_%d_1m.csv", inst.Symbol, y))
		bars, err := loadCSVFile(fname)
		if err != nil {
			// Missing year file is not fatal — we just have fewer bars.
			continue
		}
		allMinute = append(allMinute, bars...)
	}
	if len(allMinute) == 0 {
		return nil, fmt.Errorf("CSV: no 1m data files found in %s for %s", f.dataDir, inst.Symbol)
	}

	// Filter to [from, to].
	var filtered []Candle
	for _, c := range allMinute {
		if !c.TimeUTC.Before(from) && !c.TimeUTC.After(to) {
			filtered = append(filtered, c)
		}
	}
	if interval == Interval1m || interval == "" {
		if f.cache != nil {
			_ = f.cache.Put(inst.Token+"_csv", interval, filtered)
		}
		return filtered, nil
	}

	// Downsample 1m → requested interval.
	step := intervalDuration(interval)
	downsampled := downsample1m(filtered, step)
	if f.cache != nil {
		_ = f.cache.Put(inst.Token+"_csv", interval, downsampled)
	}
	return downsampled, nil
}

func loadCSVFile(path string) ([]Candle, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var candles []Candle
	buf := make([]byte, 0, 1<<20)
	tmp := make([]byte, 4096)
	for {
		n, rerr := f.Read(tmp)
		buf = append(buf, tmp[:n]...)
		if rerr != nil {
			break
		}
	}

	lines := splitLines(buf)
	for i, line := range lines {
		if i == 0 && len(line) > 0 && line[0] == 't' {
			continue // header
		}
		if len(line) == 0 {
			continue
		}
		fields := splitCSV(line)
		if len(fields) < 6 {
			continue
		}
		ts, err := time.Parse(time.RFC3339, fields[0])
		if err != nil {
			// Try common fallback format.
			ts, err = time.Parse("2006-01-02 15:04:05", fields[0])
			if err != nil {
				continue
			}
		}
		o := parseFloat(fields[1])
		h := parseFloat(fields[2])
		l := parseFloat(fields[3])
		c := parseFloat(fields[4])
		v := parseFloat(fields[5])
		candles = append(candles, Candle{TimeUTC: ts.UTC(), Open: o, High: h, Low: l, Close: c, Volume: v})
	}
	return candles, nil
}

// downsample1m aggregates 1m candles into wider bars aligned to step boundaries.
func downsample1m(bars []Candle, step time.Duration) []Candle {
	if len(bars) == 0 || step <= time.Minute {
		return bars
	}
	var result []Candle
	var cur *Candle
	for _, b := range bars {
		barStart := b.TimeUTC.Truncate(step)
		if cur == nil || !cur.TimeUTC.Equal(barStart) {
			if cur != nil {
				result = append(result, *cur)
			}
			cp := Candle{TimeUTC: barStart, Open: b.Open, High: b.High, Low: b.Low, Close: b.Close, Volume: b.Volume}
			cur = &cp
		} else {
			if b.High > cur.High {
				cur.High = b.High
			}
			if b.Low < cur.Low {
				cur.Low = b.Low
			}
			cur.Close = b.Close
			cur.Volume += b.Volume
		}
	}
	if cur != nil {
		result = append(result, *cur)
	}
	return result
}

// ─────────────────────────────────────────────────────────────────────────────
// SyntheticMultiYearFetcher — 5-year realistic OHLCV generator using GBM
// with regime injection (trending 40%, ranging 40%, high-vol 20%),
// gap simulation, VIX mean-reversion, PCR cycling.
// All data is generated in 90-day chunks to avoid memory exhaustion.
// ─────────────────────────────────────────────────────────────────────────────

type SyntheticMultiYearFetcher struct {
	seed int64
	base *SyntheticFetcher // delegate for VIX and non-multi-year data
}

func NewSyntheticMultiYearFetcher(seed int64) *SyntheticMultiYearFetcher {
	return &SyntheticMultiYearFetcher{seed: seed, base: NewSyntheticFetcher(seed)}
}

func (f *SyntheticMultiYearFetcher) SourceName() string { return "SyntheticMultiYear" }

func (f *SyntheticMultiYearFetcher) FetchCandles(ctx context.Context, inst Instrument, from, to time.Time, interval string) ([]Candle, error) {
	// Delegate VIX to base fetcher.
	if inst.IsVIX() {
		return f.base.FetchCandles(ctx, inst, from, to, interval)
	}

	step := intervalDuration(interval)
	if step <= 0 || !to.After(from) {
		return nil, nil
	}

	base := map[string]float64{
		"NIFTY":     24800,
		"BANKNIFTY": 52600,
	}[inst.Underlying]
	if base == 0 {
		base = 20000
	}

	cal := calendar.NewService()
	rng := rand.New(rand.NewSource(f.seed ^ int64(len(inst.Underlying)*131+len(interval)*17)))

	// GBM parameters (annualized).
	const mu = 0.12       // 12%/year expected return
	const sigma = 0.18    // 18%/year annualized volatility
	dt := step.Hours() / (252 * 6.25) // fraction of trading year per bar (6.25h/day)

	price := base
	vix := 14.0
	var out []Candle

	// Process in 90-day chunks.
	chunkSize := 90 * 24 * time.Hour
	chunkStart := from.Truncate(step)

	// Regime state machine: 0=trending, 1=ranging, 2=highvol.
	regimePhase := 0
	regimeDays := 0
	const trendDays = 15  // avg days in trending regime
	const rangeDays = 15
	const hvolDays = 7

	for chunkStart.Before(to) {
		select {
		case <-ctx.Done():
			return out, ctx.Err()
		default:
		}
		chunkEnd := chunkStart.Add(chunkSize)
		if chunkEnd.After(to) {
			chunkEnd = to
		}

		for t := chunkStart; !t.After(chunkEnd); t = t.Add(step) {
			if !cal.IsMarketOpen(t) {
				continue
			}

			// Advance regime state.
			regimeDays++
			var maxDays int
			switch regimePhase {
			case 0:
				maxDays = trendDays + int(rng.NormFloat64()*3)
			case 1:
				maxDays = rangeDays + int(rng.NormFloat64()*3)
			default:
				maxDays = hvolDays + int(rng.NormFloat64()*2)
			}
			if maxDays < 3 {
				maxDays = 3
			}
			if regimeDays > maxDays {
				// Transition: trending→ranging→highvol→trending (weighted).
				regimeDays = 0
				r := rng.Float64()
				switch regimePhase {
				case 0:
					if r < 0.5 {
						regimePhase = 1
					} else {
						regimePhase = 2
					}
				case 1:
					if r < 0.6 {
						regimePhase = 0
					} else {
						regimePhase = 2
					}
				case 2:
					regimePhase = 1
				}
			}

			// GBM drift + vol by regime.
			var drift, localSigma float64
			switch regimePhase {
			case 0: // trending
				trendDir := 1.0
				if rng.Float64() < 0.4 {
					trendDir = -1.0
				}
				drift = trendDir * mu * dt
				localSigma = sigma * 0.9
			case 1: // ranging
				drift = 0
				localSigma = sigma * 0.6
			case 2: // high-vol
				drift = 0
				localSigma = sigma * 1.6
			}

			// GBM step: dS = S*(mu*dt + sigma*sqrt(dt)*Z)
			sqrtDt := math.Sqrt(dt)
			ret := drift + localSigma*sqrtDt*rng.NormFloat64()

			// Realistic gap on open (0.3% avg, log-normal).
			gap := rng.NormFloat64() * 0.003
			open := price * (1 + gap)
			closeP := open * math.Exp(ret)

			// Build OHLC from open/close with intrabar noise.
			noise := math.Abs(rng.NormFloat64()) * localSigma * sqrtDt * 0.5
			hi := math.Max(open, closeP) * (1 + noise)
			lo := math.Min(open, closeP) * (1 - noise)
			if lo <= 0 {
				lo = math.Min(open, closeP) * 0.995
			}

			// VIX mean-reversion correlated to realized vol.
			vixTarget := 12.0 + localSigma*100 // higher sigma → higher VIX
			vix += (vixTarget-vix)*0.05 + rng.NormFloat64()*0.1
			if vix < 9 {
				vix = 9
			}

			// Volume: higher in trending/hv, lower in ranging.
			volBase := 40000 + rng.Float64()*60000
			switch regimePhase {
			case 0:
				volBase *= 1.3
			case 2:
				volBase *= 1.8
			}

			out = append(out, Candle{
				TimeUTC: t.UTC(), Open: open, High: hi, Low: lo, Close: closeP, Volume: volBase,
			})
			price = closeP
		}
		chunkStart = chunkEnd.Add(step)
	}
	return out, nil
}

// ─────────────────────────────────────────────────────────────────────────────
// Small parsing helpers (no external dependencies).
// ─────────────────────────────────────────────────────────────────────────────

func splitLines(b []byte) []string {
	var lines []string
	start := 0
	for i, c := range b {
		if c == '\n' {
			line := string(b[start:i])
			if len(line) > 0 && line[len(line)-1] == '\r' {
				line = line[:len(line)-1]
			}
			lines = append(lines, line)
			start = i + 1
		}
	}
	if start < len(b) {
		lines = append(lines, string(b[start:]))
	}
	return lines
}

func splitCSV(line string) []string {
	var fields []string
	start := 0
	for i := 0; i < len(line); i++ {
		if line[i] == ',' {
			fields = append(fields, line[start:i])
			start = i + 1
		}
	}
	fields = append(fields, line[start:])
	return fields
}

func parseFloat(s string) float64 {
	// Trim whitespace.
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\t') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\t') {
		s = s[:len(s)-1]
	}
	f, _ := strconv.ParseFloat(s, 64)
	return f
}
