package risk

import "niftypilot/internal/ledger"

// PersistedSnapshot is the minimal shape of engine state as loaded
// from MongoDB/SQLite on restart. The real persistence layer
// (engine/internal/persistence in the BTC-reference repo) supplies
// this; this package only defines the reconciliation contract.
type PersistedSnapshot struct {
	OpenTradeIDs map[string]bool
	EquityINR    float64
}

// ReconcileOnRestart compares in-memory ledger state against persisted
// state and returns a mismatch report. The engine MUST call this
// before allowing any new trades after a restart (same pattern as the
// BTC engine) — trading on divergent state risks double-counting
// positions or missing a position the persisted layer still considers
// open.
type ReconciliationResult struct {
	Clean               bool
	MissingFromMemory   []string // open in persisted snapshot, not in memory
	UnexpectedInMemory  []string // open in memory, not in persisted snapshot
	EquityDriftINR      float64
	EquityDriftMaterial bool // true if drift exceeds the materiality threshold
}

// MaterialEquityDriftINR is the threshold above which an equity drift
// is escalated from informational (TriggerEquityDrift, non-halting) to
// a halting TriggerReconciliationFail. Tune relative to portfolio size.
const MaterialEquityDriftINR = 50000.0 // Rs 50,000 on a Rs 1 crore paper book = 0.5%

func ReconcileOnRestart(l *ledger.Ledger, persisted PersistedSnapshot, currentEquity float64) ReconciliationResult {
	inMemory := map[string]bool{}
	for _, t := range l.OpenTrades() {
		inMemory[t.ID] = true
	}

	res := ReconciliationResult{Clean: true}
	for id := range persisted.OpenTradeIDs {
		if !inMemory[id] {
			res.MissingFromMemory = append(res.MissingFromMemory, id)
			res.Clean = false
		}
	}
	for id := range inMemory {
		if !persisted.OpenTradeIDs[id] {
			res.UnexpectedInMemory = append(res.UnexpectedInMemory, id)
			res.Clean = false
		}
	}

	drift := currentEquity - persisted.EquityINR
	if drift < 0 {
		drift = -drift
	}
	res.EquityDriftINR = drift
	res.EquityDriftMaterial = drift > MaterialEquityDriftINR
	if res.EquityDriftMaterial {
		res.Clean = false
	}
	return res
}

// ApplyReconciliation raises the correctly classified kill-switch
// trigger for a reconciliation result: a material position mismatch or
// equity drift halts trading (TriggerReconciliationFail); a small,
// immaterial equity drift is logged as non-halting (TriggerEquityDrift)
// per this engine's explicit classification table.
func ApplyReconciliation(ks *KillSwitch, res ReconciliationResult) {
	if len(res.MissingFromMemory) > 0 || len(res.UnexpectedInMemory) > 0 {
		ks.Trigger(TriggerReconciliationFail, "open-position set diverged between memory and persisted state on restart", false)
		return
	}
	if res.EquityDriftMaterial {
		ks.Trigger(TriggerReconciliationFail, "equity drift exceeded materiality threshold on restart", false)
		return
	}
	if res.EquityDriftINR > 0 {
		ks.Trigger(TriggerEquityDrift, "small equity drift detected on restart, within materiality threshold", false)
	}
}
