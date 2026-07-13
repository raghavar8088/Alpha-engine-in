package broker

import (
	"context"
	"fmt"
	"time"

	"niftypilot/internal/execution"
	"niftypilot/internal/ledger"
)

// PaperBroker wraps the existing execution.Engine so paper trades go
// through the same slippage + Indian cost model as S1–S9 did, and every
// P&L record lands in the same ledger. No live API calls are made.
type PaperBroker struct {
	engine *execution.Engine
	ledger *ledger.Ledger
	seq    int64
}

func NewPaperBroker(eng *execution.Engine, l *ledger.Ledger) *PaperBroker {
	return &PaperBroker{engine: eng, ledger: l}
}

func (b *PaperBroker) Name() string { return "paper" }

func (b *PaperBroker) PlaceOrder(_ context.Context, req OrderRequest) (Fill, error) {
	b.seq++
	ref := fmt.Sprintf("PAPER-%d-%d", time.Now().UnixNano(), b.seq)

	// IOC synthetic fill: filled immediately at requested price.
	fill := Fill{
		OrderID:   req.SignalID,
		BrokerRef: ref,
		Symbol:    req.Symbol,
		Side:      req.Side,
		Quantity:  req.Quantity,
		FilledQty: req.Quantity,
		AvgFillPx: req.Price,
		Status:    "COMPLETE",
		FilledAt:  req.RequestedAt,
	}
	// If no explicit price (market order), we treat AvgFillPx=0 as a signal
	// that the caller will record the trade via execution.Engine.ExecuteEntry
	// using the signal's Entry price. The PaperBroker only manages the fill
	// record; the evaluation loop calls ExecuteEntry separately.
	return fill, nil
}

func (b *PaperBroker) CancelOrder(_ context.Context, _ string) error {
	// Paper orders fill instantly (IOC); nothing to cancel.
	return nil
}

func (b *PaperBroker) Positions(_ context.Context) ([]Position, error) {
	trades := b.ledger.OpenTrades()
	out := make([]Position, 0, len(trades))
	for _, t := range trades {
		qty := t.Quantity
		if t.Direction == "SHORT" {
			qty = -qty
		}
		out = append(out, Position{
			Symbol:     t.Instrument,
			Underlying: t.Underlying,
			Instrument: t.Instrument,
			NetQty:     qty,
			AvgCostPx:  t.EntryPrice,
		})
	}
	return out, nil
}

func (b *PaperBroker) Balance(_ context.Context) (float64, error) {
	// Paper balance = realised PnL (starting capital not tracked in ledger).
	return b.ledger.RealizedPnL(), nil
}
