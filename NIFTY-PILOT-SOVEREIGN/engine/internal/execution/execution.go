// Package execution implements the paper fill model: IOC-style
// immediate fill at best available price plus ATR-scaled slippage,
// calibrated for Indian options liquidity (far-OTM strikes have much
// wider spreads than ATM). Crucially, the Indian cost model (costs
// package) is applied on BOTH entry and exit — the BTC engine's exact
// P0 bug class (exit fees silently never charged) must not recur here.
package execution

import (
	"fmt"
	"time"

	"niftypilot/internal/costs"
	"niftypilot/internal/instruments"
	"niftypilot/internal/ledger"
	"niftypilot/internal/strategy"
)

// SlippageModel estimates the entry/exit slippage in premium terms.
// Far-OTM strikes get a wider spread multiplier than ATM strikes,
// reflecting real NSE options-chain liquidity (modeled, not flat bps).
type SlippageModel struct {
	BaseSlippageATRFraction float64 // fraction of 1m ATR added as baseline slippage
}

func DefaultSlippageModel() SlippageModel {
	return SlippageModel{BaseSlippageATRFraction: 0.1}
}

// Estimate returns the slippage in premium points, scaling up for
// strikes further OTM (moneyness = |strike-spot|/spot).
func (m SlippageModel) Estimate(atr, spot, strike float64) float64 {
	base := atr * m.BaseSlippageATRFraction
	if strike == 0 || spot == 0 {
		return base
	}
	moneyness := abs(strike-spot) / spot
	// Liquidity widens roughly linearly with OTM distance beyond 1%;
	// ATM strikes (moneyness ~0) get ~1x base, 5% OTM gets ~3x base.
	widening := 1.0 + moneyness*40.0
	return base * widening
}

func abs(f float64) float64 {
	if f < 0 {
		return -f
	}
	return f
}

// Engine executes paper entries/exits against a ledger, applying the
// full Indian cost model and the slippage model on every leg.
type Engine struct {
	Ledger    *ledger.Ledger
	Rates     costs.Rates
	Slippage  SlippageModel
	idSeq     int64
}

func NewEngine(l *ledger.Ledger) *Engine {
	return &Engine{Ledger: l, Rates: costs.DefaultRates(), Slippage: DefaultSlippageModel()}
}

func (e *Engine) nextID() string {
	e.idSeq++
	return fmt.Sprintf("TRD-%d-%d", time.Now().UnixNano(), e.idSeq)
}

// ExecuteEntry fills the entry leg of a validated signal at lots*lotSize
// quantity, applying slippage against the signal's Entry price and the
// full entry-side Indian cost model. Returns the opened Trade.
func (e *Engine) ExecuteEntry(sig strategy.Signal, lots int64, atr float64) ledger.Trade {
	qty := instruments.LotsToQuantity(sig.Underlying, lots)
	slip := e.Slippage.Estimate(atr, sig.Entry, sig.Strike)

	fillPrice := sig.Entry
	side := costs.Buy
	switch sig.Direction {
	case strategy.Long:
		fillPrice = instruments.RoundToTick(sig.Entry + slip) // worse fill for buyer
		side = costs.Buy
	case strategy.Short:
		fillPrice = instruments.RoundToTick(sig.Entry - slip) // worse fill for seller
		side = costs.Sell
	}

	instType := costs.Future
	if sig.Instrument != "FUTURE" {
		instType = costs.Option
	}
	entryCost := costs.Compute(e.Rates, costs.CostInputs{
		Instrument: instType, Side: side, Quantity: qty, Price: fillPrice,
	})

	t := ledger.Trade{
		ID: e.nextID(), Strategy: sig.Strategy, Underlying: sig.Underlying,
		Instrument: sig.Instrument, Direction: string(sig.Direction),
		Strike: sig.Strike, Lots: lots, Quantity: qty,
		EntryPrice: fillPrice, StopLoss: sig.StopLoss, TakeProfit: sig.TakeProfit,
		EntryAt: sig.GeneratedAt, EntryCostINR: entryCost.Total,
	}
	e.Ledger.RecordEntry(t)
	return t
}

// ExecuteExit fills the exit leg at exitPrice (already including
// caller-applied slippage if any), applies the exit-side Indian cost
// model (the leg the BTC engine's bug skipped — never skip it here),
// and records the closed trade with full net PnL.
func (e *Engine) ExecuteExit(tradeID string, exitPrice float64, exitAt time.Time, reason string, atr float64) {
	t, ok := e.Ledger.Trade(tradeID)
	if !ok {
		return
	}
	slip := e.Slippage.Estimate(atr, exitPrice, t.Strike)
	fillPrice := exitPrice
	side := costs.Sell // closing a long = selling
	if t.Direction == "LONG" {
		fillPrice = instruments.RoundToTick(exitPrice - slip)
		side = costs.Sell
	} else {
		fillPrice = instruments.RoundToTick(exitPrice + slip)
		side = costs.Buy // closing a short = buying back
	}

	instType := costs.Future
	if t.Instrument != "FUTURE" {
		instType = costs.Option
	}
	isExercise := reason == "EXPIRY"
	exitCost := costs.Compute(e.Rates, costs.CostInputs{
		Instrument: instType, Side: side, Quantity: t.Quantity, Price: fillPrice, IsExercise: isExercise,
	})

	e.Ledger.RecordExit(tradeID, fillPrice, exitAt, reason, exitCost.Total)
}
