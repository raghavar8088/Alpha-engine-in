package backtest

import (
	"testing"
	"time"

	"niftypilot/internal/calendar"
)

func TestISTOffset(t *testing.T) {
	// IST is UTC+5:30, no DST.
	_, offset := time.Date(2024, 7, 1, 0, 0, 0, 0, calendar.IST).Zone()
	if offset != 5*3600+30*60 {
		t.Errorf("IST offset = %d sec, want %d", offset, 5*3600+30*60)
	}
	// Mid-winter must be identical (India has no DST).
	_, offsetW := time.Date(2024, 1, 1, 0, 0, 0, 0, calendar.IST).Zone()
	if offsetW != offset {
		t.Errorf("IST offset changed across seasons (%d vs %d) — India has no DST", offset, offsetW)
	}
}

func TestMarketOpenBoundaries(t *testing.T) {
	cal := calendar.NewService()
	// 2024-01-15 is a Monday (trading day).
	open := time.Date(2024, 1, 15, 9, 15, 0, 0, calendar.IST)
	beforeOpen := time.Date(2024, 1, 15, 9, 14, 0, 0, calendar.IST)
	close := time.Date(2024, 1, 15, 15, 30, 0, 0, calendar.IST)
	mid := time.Date(2024, 1, 15, 12, 0, 0, 0, calendar.IST)

	if !cal.IsMarketOpen(open) {
		t.Error("09:15 IST should be market-open")
	}
	if cal.IsMarketOpen(beforeOpen) {
		t.Error("09:14 IST should be pre-open (closed)")
	}
	if cal.IsMarketOpen(close) {
		t.Error("15:30 IST should be closed (end-exclusive)")
	}
	if !cal.IsMarketOpen(mid) {
		t.Error("12:00 IST should be open")
	}
}

func TestMarketClosedWeekend(t *testing.T) {
	cal := calendar.NewService()
	sat := time.Date(2024, 1, 13, 12, 0, 0, 0, calendar.IST) // Saturday
	sun := time.Date(2024, 1, 14, 12, 0, 0, 0, calendar.IST) // Sunday
	if cal.IsMarketOpen(sat) || cal.IsMarketOpen(sun) {
		t.Error("weekend must be closed")
	}
}

func TestIntervalDuration(t *testing.T) {
	cases := map[string]time.Duration{
		Interval1m: time.Minute, Interval5m: 5 * time.Minute,
		Interval15m: 15 * time.Minute, Interval1h: time.Hour, IntervalDay: 24 * time.Hour,
	}
	for iv, want := range cases {
		if got := intervalDuration(iv); got != want {
			t.Errorf("intervalDuration(%s) = %v, want %v", iv, got, want)
		}
	}
}

func TestBundleTimeframeMapping(t *testing.T) {
	cases := map[string]string{
		Interval1m: "1m", Interval5m: "5m", Interval15m: "15m",
		Interval1h: "1h", IntervalDay: "",
	}
	for iv, want := range cases {
		if got := bundleTimeframe(iv); got != want {
			t.Errorf("bundleTimeframe(%s) = %q, want %q", iv, got, want)
		}
	}
}

func TestUTCStorageISTDisplay(t *testing.T) {
	// A candle stored at 09:15 IST must serialize to 03:45 UTC internally.
	ist := time.Date(2024, 1, 15, 9, 15, 0, 0, calendar.IST)
	utc := ist.UTC()
	if utc.Hour() != 3 || utc.Minute() != 45 {
		t.Errorf("09:15 IST -> %02d:%02d UTC, want 03:45", utc.Hour(), utc.Minute())
	}
	// Round-trip back to IST for display.
	back := utc.In(calendar.IST)
	if back.Hour() != 9 || back.Minute() != 15 {
		t.Errorf("round-trip IST = %02d:%02d, want 09:15", back.Hour(), back.Minute())
	}
}
