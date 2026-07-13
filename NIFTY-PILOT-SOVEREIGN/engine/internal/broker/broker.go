// Package broker defines the Broker interface that both live (Angel One,
// Dhan) and paper adapters implement. The strategy evaluation loop calls
// only this interface; the concrete adapter is injected at startup.
//
// Architecture note: the paper adapter delegates to the existing
// execution.Engine so P&L accounting (slippage, Indian cost model, ledger)
// is identical for paper and live runs. Live adapters send REST calls to
// the broker APIs and record fills in the same ledger.
//
// REGULATORY: live order placement is subject to SEBI position limits,
// NSE circuit breakers, and broker risk-desk checks. The adapters here
// implement the API calls correctly but cannot enforce all exchange-level
// guardrails programmatically — the production deployment checklist must
// include manual review against current SEBI circulars.
package broker

import (
	"context"
	"time"

	"niftypilot/internal/ledger"
	"niftypilot/internal/strategy"
)

// OrderType maps to NSE/broker order-type enum.
type OrderType string

const (
	Market OrderType = "MARKET"
	Limit  OrderType = "LIMIT"
	SLM    OrderType = "SL-M" // stop-loss market
)

// ProductType mirrors broker-side product codes.
type ProductType string

const (
	NRML ProductType = "NRML" // positional (overnight)
	MIS  ProductType = "MIS"  // intraday, auto-squared-off by broker
)

// OrderRequest is the normalised order payload any adapter submits.
type OrderRequest struct {
	SignalID    string      // trace back to the generating signal
	Symbol      string      // NSE trading symbol, e.g. "NIFTY25JUNFUT"
	Exchange    string      // "NSE" | "NFO"
	Underlying  string      // "NIFTY" | "BANKNIFTY"
	Instrument  string      // "FUTURE" | "CE" | "PE" | "STRANGLE"
	Side        string      // "BUY" | "SELL"
	Quantity    int64       // total lots × lot-size
	Price       float64     // 0 for MARKET orders
	TriggerPx   float64     // for SL-M orders
	OrderType   OrderType
	ProductType ProductType
	Validity    string    // "DAY" | "IOC"
	RequestedAt time.Time
}

// Fill is what the broker confirmed after the order was processed.
type Fill struct {
	OrderID     string
	BrokerRef   string // broker's own order ID
	Symbol      string
	Side        string
	Quantity    int64
	FilledQty   int64
	AvgFillPx   float64
	Status      string // "COMPLETE" | "REJECTED" | "PARTIAL" | "PENDING"
	RejReason   string
	FilledAt    time.Time
}

// Broker is the interface all execution adapters must satisfy.
// The paper adapter and both live adapters implement this.
type Broker interface {
	// Name returns a human-readable adapter name ("paper", "angelone", "dhan").
	Name() string

	// PlaceOrder submits an order. Returns a Fill with the result (or an error).
	// For paper orders the fill is synthetic (IOC). For live orders it polls
	// until the order settles or ctx is cancelled.
	PlaceOrder(ctx context.Context, req OrderRequest) (Fill, error)

	// CancelOrder cancels an open order by the broker's order reference.
	CancelOrder(ctx context.Context, brokerRef string) error

	// Positions returns all open positions from the broker for cross-check.
	// Paper adapter returns ledger open trades translated into the same schema.
	Positions(ctx context.Context) ([]Position, error)

	// Balance returns the available trading margin/cash in INR.
	Balance(ctx context.Context) (float64, error)
}

// Position is a normalised open position record from either broker.
type Position struct {
	Symbol      string
	Underlying  string
	Instrument  string
	NetQty      int64   // positive = long, negative = short
	AvgCostPx   float64
	LastPx      float64
	UnrealisedPL float64
	DayPL       float64
}

// SignalToOrder translates a strategy.Signal into an OrderRequest.
// Callers must provide the resolved NSE trading symbol (symbol) since
// the signal only carries the underlying name and instrument type.
func SignalToOrder(sig strategy.Signal, symbol string, lots int64, lotSize int64, product ProductType) OrderRequest {
	side := "BUY"
	if sig.Direction == strategy.Short {
		side = "SELL"
	}
	exchange := "NFO"
	if sig.Instrument == "FUTURE" {
		exchange = "NFO"
	}
	return OrderRequest{
		SignalID:    sig.Strategy + "@" + sig.GeneratedAt.Format("150405"),
		Symbol:      symbol,
		Exchange:    exchange,
		Underlying:  sig.Underlying,
		Instrument:  sig.Instrument,
		Side:        side,
		Quantity:    lots * lotSize,
		Price:       0, // market order
		OrderType:   Market,
		ProductType: product,
		Validity:    "IOC",
		RequestedAt: sig.GeneratedAt,
	}
}

// LedgerTrade is an alias so callers need not import ledger directly.
type LedgerTrade = ledger.Trade
