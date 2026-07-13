// Package calendar implements the NSE trading-session calendar:
// IST market hours, weekday gating, and the NSE holiday list.
//
// REGULATORY FLAG: the holiday list below is a static fallback seed
// (NSE trading holidays as published for calendar year 2025/2026 at
// build time). NSE publishes a fresh holiday circular every December
// for the following year. RefreshFromNSE must be wired to NSE's public
// holiday-master endpoint (or a licensed vendor's calendar endpoint) in
// production and run on a daily cron; do not let this list go stale.
package calendar

import (
	"sync"
	"time"
)

// IST is India Standard Time, UTC+5:30, no daylight saving.
var IST = time.FixedZone("IST", 5*60*60+30*60)

const (
	PreOpenStart = 9*60 + 0  // 09:00 IST, minutes since midnight
	MarketOpen   = 9*60 + 15 // 09:15 IST
	MarketClose  = 15*60 + 30 // 15:30 IST
)

// Service is the authoritative trading-calendar service. All engine
// subsystems must consult this instead of recomputing hours locally.
type Service struct {
	mu       sync.RWMutex
	holidays map[string]string // "2026-01-26" -> reason, IST calendar date
}

// NewService seeds the service with the static fallback holiday list.
// REGULATORY FLAG: verify against the latest NSE circular before go-live.
func NewService() *Service {
	s := &Service{holidays: map[string]string{}}
	for date, reason := range seedHolidays2026 {
		s.holidays[date] = reason
	}
	return s
}

// seedHolidays2026 is a static seed extracted from the NSE 2026 trading
// holiday circular at build time. VERIFY CURRENT LIST against
// https://www.nseindia.com (Markets > Trading Holidays) before each
// calendar year and whenever a special/Muhurat session is announced.
var seedHolidays2026 = map[string]string{
	"2026-01-26": "Republic Day",
	"2026-03-04": "Holi",
	"2026-03-21": "Eid-Ul-Fitr (tentative, lunar calendar - VERIFY)",
	"2026-04-01": "Annual Bank Closing (tentative - VERIFY)",
	"2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
	"2026-05-01": "Maharashtra Day",
	"2026-08-15": "Independence Day",
	"2026-10-02": "Gandhi Jayanti",
	"2026-10-20": "Diwali Laxmi Pujan (Muhurat session, short trading window - VERIFY)",
	"2026-11-25": "Guru Nanak Jayanti (tentative - VERIFY)",
	"2026-12-25": "Christmas",
}

// RefreshFromNSE replaces the in-memory holiday set with a freshly
// fetched list. Wire this to NSE's published holiday-master JSON (or a
// licensed broker API's equivalent /holidays endpoint) and call it from
// a daily cron. Left as an explicit integration point: this build does
// not scrape nseindia.com directly (violates NSE terms of use).
func (s *Service) RefreshFromNSE(fresh map[string]string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.holidays = fresh
}

// IsHoliday reports whether the IST calendar date of t is an NSE holiday.
func (s *Service) IsHoliday(t time.Time) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	_, ok := s.holidays[t.In(IST).Format("2006-01-02")]
	return ok
}

// IsMarketOpen reports whether normal continuous trading is live at t:
// IST weekday Mon-Fri, within 09:15-15:30, and not an NSE holiday.
// Does NOT include the 09:00-09:15 pre-open auction window.
func (s *Service) IsMarketOpen(t time.Time) bool {
	ist := t.In(IST)
	if ist.Weekday() == time.Saturday || ist.Weekday() == time.Sunday {
		return false
	}
	if s.IsHoliday(ist) {
		return false
	}
	mins := ist.Hour()*60 + ist.Minute()
	return mins >= MarketOpen && mins < MarketClose
}

// IsPreOpen reports whether t falls in the 09:00-09:15 IST auction
// window, during which no new orders may be placed.
func (s *Service) IsPreOpen(t time.Time) bool {
	ist := t.In(IST)
	if ist.Weekday() == time.Saturday || ist.Weekday() == time.Sunday || s.IsHoliday(ist) {
		return false
	}
	mins := ist.Hour()*60 + ist.Minute()
	return mins >= PreOpenStart && mins < MarketOpen
}

// IsTradingDay reports whether the IST calendar date of t is a trading
// day at all (weekday, not a holiday), independent of time-of-day.
func (s *Service) IsTradingDay(t time.Time) bool {
	ist := t.In(IST)
	if ist.Weekday() == time.Saturday || ist.Weekday() == time.Sunday {
		return false
	}
	return !s.IsHoliday(ist)
}

// SessionOpenTime returns 09:15 IST on the same IST calendar date as t.
// Used by the risk engine for the daily-loss-circuit-breaker reset,
// which must reset at market open, not midnight UTC.
func SessionOpenTime(t time.Time) time.Time {
	ist := t.In(IST)
	return time.Date(ist.Year(), ist.Month(), ist.Day(), 9, 15, 0, 0, IST)
}

// IsExpiryDay reports whether t's IST calendar date is the weekly
// expiry date for the given index.
//
// REGULATORY FLAG: NSE has changed weekly expiry days multiple times.
// As of the most recent NSE circular at build time: Nifty 50 weekly
// options expire on Tuesday; Bank Nifty's standalone weekly options
// contract was discontinued in Nov 2024 (Bank Nifty now expires monthly
// only, on the last Tuesday). VERIFY the current expiry-day circular
// before relying on this in production - NSE has moved expiry day
// repeatedly (Thu->Fri->Mon->Tue across 2023-2025).
func IsExpiryDay(t time.Time, index string) bool {
	ist := t.In(IST)
	switch index {
	case "NIFTY":
		return ist.Weekday() == time.Tuesday
	case "BANKNIFTY":
		return isLastTuesdayOfMonth(ist)
	default:
		return false
	}
}

func isLastTuesdayOfMonth(t time.Time) bool {
	if t.Weekday() != time.Tuesday {
		return false
	}
	nextWeek := t.AddDate(0, 0, 7)
	return nextWeek.Month() != t.Month()
}
