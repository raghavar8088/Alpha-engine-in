package backtest

import (
	"sort"
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
	"niftypilot/internal/strategy"
)

// candleStream is one (instrument, interval) historical series plus a
// visibility cursor. Candles are revealed to the bundle only AFTER they
// close (no lookahead), so a strategy at time t sees only fully-formed bars.
type candleStream struct {
	interval string
	bundleTF string // "" for daily (no bundle slot)
	candles  []Candle
	cursor   int // index of next not-yet-visible candle
}

// instrumentState holds all timeframe streams for one instrument plus
// rolling spot / previous-close state used by the bundle.
type instrumentState struct {
	inst      Instrument
	streams   map[string]*candleStream
	lastClose float64 // last visible 1m close (current spot)
	curDate   string  // IST date of the last visible bar (for prev-close rollover)
	prevClose float64 // previous session's last close
}

// ContextBuilder feeds historical candles into the SAME marketdata bundle
// the live engine uses, then classifies regime with the SAME classifier.
// It is the only adapter between historical data and the live strategy
// pipeline — strategies cannot tell they are in a backtest (PART 7).
type ContextBuilder struct {
	bundle     *marketdata.NiftyDataBundle
	classifier *regime.Classifier
	states     map[string]*instrumentState // keyed by Instrument.Underlying
	vixState   *instrumentState
}

func NewContextBuilder(bundle *marketdata.NiftyDataBundle, classifier *regime.Classifier) *ContextBuilder {
	return &ContextBuilder{
		bundle:     bundle,
		classifier: classifier,
		states:     map[string]*instrumentState{},
	}
}

// AddInstrument registers an instrument's per-interval candle streams.
func (cb *ContextBuilder) AddInstrument(inst Instrument, byInterval map[string][]Candle) {
	st := &instrumentState{inst: inst, streams: map[string]*candleStream{}}
	for interval, candles := range byInterval {
		sorted := append([]Candle(nil), candles...)
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].TimeUTC.Before(sorted[j].TimeUTC) })
		st.streams[interval] = &candleStream{
			interval: interval, bundleTF: bundleTimeframe(interval), candles: sorted,
		}
	}
	if inst.IsVIX() {
		cb.vixState = st
	} else {
		cb.states[inst.Underlying] = st
	}
}

// Underlyings returns the tradable (non-VIX) underlyings in deterministic order.
func (cb *ContextBuilder) Underlyings() []string {
	out := make([]string, 0, len(cb.states))
	for u := range cb.states {
		out = append(out, u)
	}
	sort.Strings(out)
	return out
}

// BaseTimeline returns the sorted, de-duplicated set of 1m bar CLOSE times
// across all instruments. The replay loop steps through these; each is a
// valid "now" at which fully-closed bars are visible.
func (cb *ContextBuilder) BaseTimeline() []time.Time {
	set := map[int64]time.Time{}
	collect := func(st *instrumentState) {
		s := st.streams[Interval1m]
		if s == nil {
			return
		}
		for _, c := range s.candles {
			closeT := c.TimeUTC.Add(intervalDuration(Interval1m))
			set[closeT.UnixNano()] = closeT
		}
	}
	for _, st := range cb.states {
		collect(st)
	}
	if cb.vixState != nil {
		collect(cb.vixState)
	}
	out := make([]time.Time, 0, len(set))
	for _, t := range set {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Before(out[j]) })
	return out
}

// Advance reveals every candle that has closed at or before now, pushing it
// into the bundle, and updates spot / India VIX / previous-close. It must be
// called once per base timeline step before BuildContext.
func (cb *ContextBuilder) Advance(now time.Time) {
	// VIX first so the classifier sees the right VIX for this step.
	if cb.vixState != nil {
		cb.advanceState(cb.vixState, now, true)
	}
	for _, st := range cb.states {
		cb.advanceState(st, now, false)
	}
}

// fixedIntervalOrder is the deterministic order timeframes are revealed in.
// Iterating st.streams (a map) directly is non-deterministic and, because
// spot/prev-close are derived from the base 1m stream, must never depend on
// Go's randomized map iteration order.
var fixedIntervalOrder = []string{Interval1m, Interval5m, Interval15m, Interval1h}

func (cb *ContextBuilder) advanceState(st *instrumentState, now time.Time, isVIX bool) {
	for _, interval := range fixedIntervalOrder {
		s := st.streams[interval]
		if s == nil {
			continue
		}
		dur := intervalDuration(interval)
		for s.cursor < len(s.candles) {
			c := s.candles[s.cursor]
			if c.TimeUTC.Add(dur).After(now) {
				break // bar hasn't closed yet -> not visible
			}
			s.cursor++
			if isVIX {
				cb.bundle.SetIndiaVIX(c.Close)
				continue
			}
			if s.bundleTF != "" {
				cb.bundle.PushCandle(st.inst.Underlying, s.bundleTF, c.ToMarketCandle())
			}
			// Spot and previous-close rollover are derived ONLY from the base
			// 1m stream, so they never depend on map iteration order and never
			// reflect a higher-timeframe bar that closed at a different instant.
			if interval == Interval1m {
				ist := c.TimeUTC.In(calendar.IST).Format("2006-01-02")
				if st.curDate != "" && st.curDate != ist && st.lastClose > 0 {
					st.prevClose = st.lastClose
					cb.bundle.SetPrevClose(st.inst.Underlying, st.prevClose)
				}
				st.curDate = ist
				st.lastClose = c.Close
				cb.bundle.SetSpot(st.inst.Underlying, c.Close, c.TimeUTC)
			}
		}
	}
}

// Spot returns the last visible close for an underlying.
func (cb *ContextBuilder) Spot(underlying string) float64 {
	if st, ok := cb.states[underlying]; ok {
		return st.lastClose
	}
	return 0
}

// BuildContext classifies regime via the live classifier and returns the
// strategy.MarketContext for one underlying at time now — byte-for-byte the
// same context shape the live evaluation loop builds (PART 7).
func (cb *ContextBuilder) BuildContext(underlying string, now time.Time) (strategy.MarketContext, regime.RegimeClass) {
	rc := cb.classifier.Classify(underlying, cb.bundle, now)
	return strategy.MarketContext{Now: now, Underlying: underlying, Bundle: cb.bundle, Regime: rc}, rc
}
