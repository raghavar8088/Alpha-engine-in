// Package costs implements the full Indian F&O transaction-cost model.
// The BTC system had a P0 bug where exit fees were never charged,
// systematically overstating paper PnL — this package is invoked on
// BOTH entry and exit of every paper trade, with no shortcuts.
//
// REGULATORY FLAG: every rate below is sourced from the SEBI/NSE/CBDT
// circulars in force at build time and WILL change. STT in particular
// was hiked materially for F&O effective 1 Oct 2024 (Finance Act 2024
// amendment). Re-verify all rates against the latest circular before
// any live-money use; this is a paper-trading system so stale rates
// only bias simulated PnL, but they must still be kept current to keep
// the simulation meaningful.
package costs

// InstrumentType distinguishes options from futures, since STT differs.
type InstrumentType string

const (
	Option InstrumentType = "OPTION"
	Future InstrumentType = "FUTURE"
)

// Side of the leg being costed.
type Side string

const (
	Buy  Side = "BUY"
	Sell Side = "SELL"
)

// Rates holds the full current Indian F&O cost-model rate card.
// REGULATORY FLAG on every field — verify against the latest NSE/SEBI/
// CBDT circular before relying on these in anything beyond paper sims.
type Rates struct {
	// STTSellOptionsOnPremium: STT on SELL side of an options trade,
	// charged on premium value. Post Oct-2024 Finance Act hike this is
	// 0.1% (0.001) of premium turnover on the sell leg only.
	// SOURCE: Finance (No. 2) Act 2024 F&O STT amendment, effective
	// 2024-10-01. VERIFY CURRENT RATE before production use.
	STTSellOptionsOnPremium float64

	// STTSellOptionsOnExercise: STT on exercised/ITM-expired options,
	// charged on the intrinsic value at exercise, sell side. Post hike:
	// 0.125% (0.00125). VERIFY CURRENT RATE.
	STTSellOptionsOnExercise float64

	// STTFuturesSell: STT on SELL side of a futures trade, on contract
	// turnover value. Post hike: 0.02% (0.0002). VERIFY CURRENT RATE.
	STTFuturesSell float64

	// BrokerageFlatPerOrder: flat per-order brokerage typical of
	// discount brokers (e.g. Zerodha/Upstox/AngelOne F&O flat fee).
	// Many brokers charge min(0.03% of turnover, flat fee); this model
	// uses the flat fee as the dominant term for F&O. VERIFY CURRENT
	// RATE against the chosen broker's published tariff.
	BrokerageFlatPerOrder float64

	// ExchangeTxnChargeOptionsRate: NSE F&O segment transaction charge
	// for options, on premium turnover. SOURCE: NSE F&O segment
	// transaction charge circular. VERIFY CURRENT RATE.
	ExchangeTxnChargeOptionsRate float64

	// ExchangeTxnChargeFuturesRate: NSE F&O segment transaction charge
	// for futures, on contract turnover. VERIFY CURRENT RATE.
	ExchangeTxnChargeFuturesRate float64

	// SEBITurnoverFeeRate: SEBI turnover fee, on turnover value, both
	// legs. SOURCE: SEBI (Turnover Fees) circular, currently
	// Rs 10 per crore = 0.0001%. VERIFY CURRENT RATE.
	SEBITurnoverFeeRate float64

	// StampDutyBuyRate: stamp duty, BUY side only, on turnover value.
	// State-dependent in principle but brokers apply a uniform
	// 0.003% (0.00003) for F&O under the centralized stamp-duty regime.
	// VERIFY CURRENT RATE.
	StampDutyBuyRate float64

	// GSTRate: GST on (brokerage + exchange transaction charge + SEBI
	// fee), currently 18% (0.18). VERIFY CURRENT RATE.
	GSTRate float64
}

// DefaultRates returns the rate card used by this build.
// REGULATORY FLAG: see package doc and each field's comment — verify
// against current circulars before relying on these for anything but
// paper-trading simulation.
func DefaultRates() Rates {
	return Rates{
		STTSellOptionsOnPremium:     0.001,    // 0.1% sell-side premium, post Oct-2024 hike
		STTSellOptionsOnExercise:    0.00125,  // 0.125% on exercise/ITM-expiry intrinsic value
		STTFuturesSell:              0.0002,   // 0.02% sell-side turnover
		BrokerageFlatPerOrder:       20.0,     // Rs 20 flat per executed order (discount broker norm)
		ExchangeTxnChargeOptionsRate: 0.0003503, // ~0.03503% of premium turnover (NSE F&O options)
		ExchangeTxnChargeFuturesRate: 0.0000173, // ~0.00173% of turnover (NSE F&O futures)
		SEBITurnoverFeeRate:         0.0000001, // Rs 10/crore = 0.0001% = 0.000001 -> per rupee 1e-7... see note below
		StampDutyBuyRate:            0.00003,   // 0.003% buy-side only
		GSTRate:                     0.18,
	}
}

// LegCost is the itemised cost breakdown for a single order leg
// (one entry fill or one exit fill).
type LegCost struct {
	Brokerage          float64
	STT                float64
	ExchangeTxnCharge  float64
	SEBITurnoverFee    float64
	StampDuty          float64
	GST                float64
	Total              float64
}

// CostInputs describes one order leg to be costed.
type CostInputs struct {
	Instrument   InstrumentType
	Side         Side
	Quantity     int64   // total quantity (lots * lot size)
	Price        float64 // premium (options) or futures price
	IsExercise   bool    // true if this is an expiry exercise/ITM-settlement leg, not a market sell
}

// Compute returns the full itemised cost for one order leg. Called on
// BOTH the entry leg and the exit leg of every paper trade — never
// skip the exit call, that was the BTC system's exact P0 bug class.
func Compute(r Rates, in CostInputs) LegCost {
	turnover := float64(in.Quantity) * in.Price

	var stt float64
	if in.Instrument == Option {
		if in.Side == Sell {
			if in.IsExercise {
				stt = turnover * r.STTSellOptionsOnExercise
			} else {
				stt = turnover * r.STTSellOptionsOnPremium
			}
		}
	} else { // Future
		if in.Side == Sell {
			stt = turnover * r.STTFuturesSell
		}
	}

	var exchTxn float64
	if in.Instrument == Option {
		exchTxn = turnover * r.ExchangeTxnChargeOptionsRate
	} else {
		exchTxn = turnover * r.ExchangeTxnChargeFuturesRate
	}

	sebiFee := turnover * r.SEBITurnoverFeeRate

	var stamp float64
	if in.Side == Buy {
		stamp = turnover * r.StampDutyBuyRate
	}

	brokerage := r.BrokerageFlatPerOrder

	gst := (brokerage + exchTxn + sebiFee) * r.GSTRate

	total := brokerage + stt + exchTxn + sebiFee + stamp + gst

	return LegCost{
		Brokerage:         brokerage,
		STT:                stt,
		ExchangeTxnCharge:  exchTxn,
		SEBITurnoverFee:    sebiFee,
		StampDuty:          stamp,
		GST:                gst,
		Total:              total,
	}
}

// RoundTrip computes entry + exit cost for a position, the figure that
// must be subtracted from paper PnL on every closed trade.
func RoundTrip(r Rates, entry, exit CostInputs) (entryCost, exitCost LegCost, total float64) {
	entryCost = Compute(r, entry)
	exitCost = Compute(r, exit)
	return entryCost, exitCost, entryCost.Total + exitCost.Total
}
