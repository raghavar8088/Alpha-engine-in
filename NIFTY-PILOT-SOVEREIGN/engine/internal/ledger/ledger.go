// Package ledger is the event-sourced trade/position store, mirroring
// the BTC engine's ledger pattern: every state change is appended as
// an immutable event, and current state is a fold over the event log.
// This is what reconciliation-on-restart replays against.
package ledger

import (
	"sync"
	"time"
)

type EventType string

const (
	EventEntry EventType = "ENTRY"
	EventExit  EventType = "EXIT"
	EventSLHit EventType = "SL_HIT"
	EventTPHit EventType = "TP_HIT"
)

type Event struct {
	Seq        int64
	Type       EventType
	TradeID    string
	Strategy   string
	Underlying string
	At         time.Time
	Payload    map[string]any
}

type TradeStatus string

const (
	StatusOpen   TradeStatus = "OPEN"
	StatusClosed TradeStatus = "CLOSED"
)

// Trade is the current-state projection of one paper position,
// equivalent to the BTC engine's BTCFuturesTrade.
type Trade struct {
	ID           string
	Strategy     string
	Underlying   string
	Instrument   string
	Direction    string
	Strike       float64
	Lots         int64
	Quantity     int64
	EntryPrice   float64
	StopLoss     float64
	TakeProfit   float64
	ExitPrice    float64
	ExitReason   string // TP | SL | TIME | EXPIRY | MAX_PAIN_TARGET
	EntryAt      time.Time
	ExitAt       time.Time
	Status       TradeStatus
	GrossPnL     float64
	EntryCostINR float64
	ExitCostINR  float64
	NetPnL       float64
	MarginBlockedINR float64
}

// Ledger holds all trades and the append-only event log, protected by
// a single RWMutex (same pattern as the BTC engine's goroutine-safe
// ledger).
type Ledger struct {
	mu     sync.RWMutex
	trades map[string]*Trade
	events []Event
	seq    int64
}

func New() *Ledger {
	return &Ledger{trades: map[string]*Trade{}}
}

func (l *Ledger) RecordEntry(t Trade) {
	l.mu.Lock()
	defer l.mu.Unlock()
	t.Status = StatusOpen
	l.trades[t.ID] = &t
	l.seq++
	l.events = append(l.events, Event{Seq: l.seq, Type: EventEntry, TradeID: t.ID, Strategy: t.Strategy, Underlying: t.Underlying, At: t.EntryAt})
}

func (l *Ledger) RecordExit(id string, exitPrice float64, exitAt time.Time, exitReason string, exitCostINR float64) {
	l.mu.Lock()
	defer l.mu.Unlock()
	t, ok := l.trades[id]
	if !ok {
		return
	}
	t.ExitPrice = exitPrice
	t.ExitAt = exitAt
	t.ExitReason = exitReason
	t.ExitCostINR = exitCostINR
	sign := 1.0
	if t.Direction == "SHORT" {
		sign = -1.0
	}
	t.GrossPnL = sign * (exitPrice - t.EntryPrice) * float64(t.Quantity)
	t.NetPnL = t.GrossPnL - t.EntryCostINR - t.ExitCostINR
	t.Status = StatusClosed
	l.seq++
	l.events = append(l.events, Event{Seq: l.seq, Type: EventExit, TradeID: id, Strategy: t.Strategy, Underlying: t.Underlying, At: exitAt})
}

func (l *Ledger) OpenTrades() []Trade {
	l.mu.RLock()
	defer l.mu.RUnlock()
	var out []Trade
	for _, t := range l.trades {
		if t.Status == StatusOpen {
			out = append(out, *t)
		}
	}
	return out
}

func (l *Ledger) ClosedTrades() []Trade {
	l.mu.RLock()
	defer l.mu.RUnlock()
	var out []Trade
	for _, t := range l.trades {
		if t.Status == StatusClosed {
			out = append(out, *t)
		}
	}
	return out
}

func (l *Ledger) Trade(id string) (Trade, bool) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	t, ok := l.trades[id]
	if !ok {
		return Trade{}, false
	}
	return *t, true
}

func (l *Ledger) AllTrades() []Trade {
	l.mu.RLock()
	defer l.mu.RUnlock()
	out := make([]Trade, 0, len(l.trades))
	for _, t := range l.trades {
		out = append(out, *t)
	}
	return out
}

// Events returns a copy of the full event log, used for
// reconciliation-on-restart replay against persisted state.
func (l *Ledger) Events() []Event {
	l.mu.RLock()
	defer l.mu.RUnlock()
	out := make([]Event, len(l.events))
	copy(out, l.events)
	return out
}

// RealizedPnL sums NetPnL across all closed trades.
func (l *Ledger) RealizedPnL() float64 {
	l.mu.RLock()
	defer l.mu.RUnlock()
	var sum float64
	for _, t := range l.trades {
		if t.Status == StatusClosed {
			sum += t.NetPnL
		}
	}
	return sum
}
