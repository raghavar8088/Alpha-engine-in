package backtest

import (
	"context"
	"testing"
	"time"

	"niftypilot/internal/calendar"
)

func niftyInst() Instrument {
	return Instrument{Symbol: "NIFTY50", Underlying: "NIFTY", Token: "256265"}
}

func TestSyntheticFetcherDeterministic(t *testing.T) {
	from := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2024, 1, 10, 0, 0, 0, 0, time.UTC)

	f1 := NewSyntheticFetcher(42)
	f2 := NewSyntheticFetcher(42)
	a, err := f1.FetchCandles(context.Background(), niftyInst(), from, to, Interval5m)
	if err != nil {
		t.Fatal(err)
	}
	b, err := f2.FetchCandles(context.Background(), niftyInst(), from, to, Interval5m)
	if err != nil {
		t.Fatal(err)
	}
	if len(a) == 0 {
		t.Fatal("synthetic fetcher returned no candles")
	}
	if len(a) != len(b) {
		t.Fatalf("non-deterministic length: %d vs %d", len(a), len(b))
	}
	for i := range a {
		if a[i].Close != b[i].Close || !a[i].TimeUTC.Equal(b[i].TimeUTC) {
			t.Fatalf("non-deterministic candle at %d: %+v vs %+v", i, a[i], b[i])
		}
	}
}

func TestSyntheticFetcherOnlyMarketHours(t *testing.T) {
	from := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2024, 1, 8, 0, 0, 0, 0, time.UTC)
	cal := calendar.NewService()

	f := NewSyntheticFetcher(7)
	candles, err := f.FetchCandles(context.Background(), niftyInst(), from, to, Interval1m)
	if err != nil {
		t.Fatal(err)
	}
	if len(candles) == 0 {
		t.Fatal("no candles")
	}
	for _, c := range candles {
		if !cal.IsMarketOpen(c.TimeUTC) {
			ist := c.TimeUTC.In(calendar.IST)
			t.Fatalf("candle outside market hours: %s IST (weekday %v)", ist.Format("2006-01-02 15:04"), ist.Weekday())
		}
	}
}

func TestSyntheticVIXInRange(t *testing.T) {
	from := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2024, 2, 1, 0, 0, 0, 0, time.UTC)
	f := NewSyntheticFetcher(1)
	vix := Instrument{Symbol: "INDIAVIX", Underlying: "INDIAVIX", Token: "INDIAVIX"}
	candles, err := f.FetchCandles(context.Background(), vix, from, to, Interval1m)
	if err != nil {
		t.Fatal(err)
	}
	if len(candles) == 0 {
		t.Fatal("no VIX candles")
	}
	for _, c := range candles {
		if c.Close < 5 || c.Close > 40 {
			t.Fatalf("VIX out of sane range: %.2f", c.Close)
		}
	}
}

func TestCandleToMarketCandle(t *testing.T) {
	c := Candle{
		TimeUTC: time.Unix(1700000000, 0).UTC(),
		Open:    100, High: 110, Low: 95, Close: 105, Volume: 1234, OpenInterest: 99,
	}
	mc := c.ToMarketCandle()
	if mc.Open != 100 || mc.High != 110 || mc.Low != 95 || mc.Close != 105 || mc.Volume != 1234 {
		t.Errorf("conversion mismatch: %+v", mc)
	}
	if !mc.Time.Equal(c.TimeUTC) {
		t.Errorf("time mismatch: %v vs %v", mc.Time, c.TimeUTC)
	}
}

func TestCandleCacheRoundTrip(t *testing.T) {
	dir := t.TempDir()
	cache, err := NewCandleCache(dir)
	if err != nil {
		t.Fatal(err)
	}
	candles := []Candle{
		{TimeUTC: time.Unix(1000, 0).UTC(), Close: 1, Open: 1, High: 1, Low: 1},
		{TimeUTC: time.Unix(2000, 0).UTC(), Close: 2, Open: 2, High: 2, Low: 2},
		{TimeUTC: time.Unix(3000, 0).UTC(), Close: 3, Open: 3, High: 3, Low: 3},
	}
	if err := cache.Put("TOK", Interval1m, candles); err != nil {
		t.Fatal(err)
	}
	got, ok := cache.Get("TOK", Interval1m, time.Unix(1500, 0).UTC(), time.Unix(3500, 0).UTC())
	if !ok {
		t.Fatal("cache miss after Put")
	}
	if len(got) != 2 { // only 2000 and 3000 fall in [1500,3500]
		t.Fatalf("range filter wrong: got %d, want 2", len(got))
	}
}

func TestCandleCacheMiss(t *testing.T) {
	dir := t.TempDir()
	cache, _ := NewCandleCache(dir)
	if _, ok := cache.Get("NOPE", Interval1m, time.Unix(0, 0), time.Unix(1<<40, 0)); ok {
		t.Error("expected cache miss for unknown token")
	}
}

func TestKiteRowToCandle(t *testing.T) {
	row := []any{"2024-01-15T09:15:00+0530", 100.0, 110.0, 95.0, 105.0, 12345.0, 678.0}
	c, err := kiteRowToCandle(row)
	if err != nil {
		t.Fatal(err)
	}
	if c.Open != 100 || c.High != 110 || c.Low != 95 || c.Close != 105 {
		t.Errorf("OHLC parse wrong: %+v", c)
	}
	if c.Volume != 12345 || c.OpenInterest != 678 {
		t.Errorf("vol/oi parse wrong: %+v", c)
	}
	// 09:15 IST == 03:45 UTC
	if c.TimeUTC.UTC().Hour() != 3 || c.TimeUTC.UTC().Minute() != 45 {
		t.Errorf("ts not converted to UTC: %v", c.TimeUTC.UTC())
	}
}

func TestKiteFetcherNoCredsErrors(t *testing.T) {
	k := NewKiteHistoricalFetcher("", "", nil)
	_, err := k.FetchCandles(context.Background(), niftyInst(),
		time.Now().Add(-24*time.Hour), time.Now(), Interval1m)
	if err == nil {
		t.Error("expected error with no Kite credentials")
	}
}

func TestNSEFetcherStub(t *testing.T) {
	n := NewNSEFTPFetcher(nil)
	if n.SourceName() != "NSE" {
		t.Errorf("SourceName = %s, want NSE", n.SourceName())
	}
	_, err := n.FetchCandles(context.Background(), niftyInst(), time.Now().Add(-time.Hour), time.Now(), Interval1m)
	if err == nil {
		t.Error("NSE stub should return not-implemented error")
	}
}
