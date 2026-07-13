package risk

import (
	"sync"
	"time"
)

// TriggerType enumerates every kill-switch trigger this engine can
// raise. Each one is explicitly classified as halting or non-halting
// in triggerClassification below — the BTC engine had a P0 incident
// where a NON-halting equity_drift reconciliation mismatch got
// classified as halting by a logic bug and stayed ACTIVE for 22+
// hours, blocking all trading. Every trigger here is classified
// explicitly and unit-tested (see killswitch_test.go) so that
// ambiguity can never silently default to "halting".
type TriggerType string

const (
	TriggerDailyLossLimit      TriggerType = "DAILY_LOSS_LIMIT"
	TriggerMarginBreach        TriggerType = "MARGIN_BREACH"
	TriggerEquityDrift         TriggerType = "EQUITY_DRIFT"          // reconciliation mismatch, informational unless large
	TriggerDataFeedStale       TriggerType = "DATA_FEED_STALE"       // non-halting: pause new entries, don't kill
	TriggerReconciliationFail  TriggerType = "RECONCILIATION_FAIL"   // halting: in-memory vs persisted state diverged materially
	TriggerManualHalt          TriggerType = "MANUAL_HALT"           // always halting: operator-initiated
	TriggerExpiryDayGammaSpike TriggerType = "EXPIRY_GAMMA_SPIKE"    // non-halting: regime classifier already throttles via EXPIRY_DAY
)

// triggerClassification is the single source of truth for whether a
// trigger type halts all trading (kill switch ACTIVE, blocks every new
// entry until manually cleared or the condition provably resolves) or
// is non-halting (logged/alerted but does not stop the engine). Keep
// this table exhaustive and explicit — no trigger may fall through to
// a default. This directly encodes the BTC engine's post-incident fix.
var triggerClassification = map[TriggerType]bool{
	TriggerDailyLossLimit:      true,  // halting: capital preservation, must stop for the day
	TriggerMarginBreach:        true,  // halting: force-reduce required before any new risk
	TriggerEquityDrift:         false, // non-halting: log + alert, reconcile, do not block trading on a drift alone
	TriggerDataFeedStale:       false, // non-halting: pause new ENTRIES via the calendar/health check, not a full kill
	TriggerReconciliationFail:  true,  // halting: in-memory and persisted state diverged, must not trade on unknown state
	TriggerManualHalt:          true,  // halting: always, operator override
	TriggerExpiryDayGammaSpike: false, // non-halting: handled by EXPIRY_DAY regime sizing, not a kill condition
}

// IsHalting returns the explicit classification for a trigger type. It
// panics on an unregistered trigger type rather than silently
// defaulting to halting or non-halting — an unclassified trigger is a
// programming error that must be caught at development time, not
// resolved by a guess in production.
func IsHalting(t TriggerType) bool {
	v, ok := triggerClassification[t]
	if !ok {
		panic("risk: unclassified kill-switch trigger type: " + string(t))
	}
	return v
}

type triggerRecord struct {
	Type      TriggerType
	Message   string
	Halting   bool
	At        time.Time
}

// KillSwitch tracks halting and non-halting trigger history. Only
// halting triggers set Active=true and block CheckEntryAllowed.
type KillSwitch struct {
	mu      sync.RWMutex
	active  bool
	reason  string
	history []triggerRecord
}

func NewKillSwitch() *KillSwitch { return &KillSwitch{} }

// Trigger records a trigger event. The classification table
// (triggerClassification) is the sole source of truth for whether the
// trigger halts trading — callers cannot weaken or strengthen it via a
// parameter, eliminating the class of bug where a caller's local
// boolean disagreed with the authoritative classification.
func (k *KillSwitch) Trigger(t TriggerType, message string, _ bool) {
	k.mu.Lock()
	defer k.mu.Unlock()
	halting := IsHalting(t)
	k.history = append(k.history, triggerRecord{Type: t, Message: message, Halting: halting, At: time.Now()})
	if halting {
		k.active = true
		k.reason = string(t) + ": " + message
	}
}

func (k *KillSwitch) IsActive() bool {
	k.mu.RLock()
	defer k.mu.RUnlock()
	return k.active
}

func (k *KillSwitch) ActiveReason() string {
	k.mu.RLock()
	defer k.mu.RUnlock()
	return k.reason
}

// ManualClear resets the kill switch. Must be an explicit operator
// action — never auto-cleared by the engine itself, even for triggers
// whose underlying condition has since resolved (e.g. margin back
// under threshold), to avoid a flapping kill switch.
func (k *KillSwitch) ManualClear(operator string) {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.active = false
	k.reason = ""
	k.history = append(k.history, triggerRecord{Type: TriggerManualHalt, Message: "cleared by " + operator, Halting: false, At: time.Now()})
}

// History returns a copy of all recorded triggers, halting and non-halting.
func (k *KillSwitch) History() []triggerRecord {
	k.mu.RLock()
	defer k.mu.RUnlock()
	out := make([]triggerRecord, len(k.history))
	copy(out, k.history)
	return out
}
