package risk

import "testing"

// TestEveryTriggerIsClassified guards against the BTC engine's exact
// P0 bug class: an unclassified or misclassified trigger silently
// defaulting to the wrong halting behavior. Every TriggerType constant
// must appear in triggerClassification with an explicit value.
func TestEveryTriggerIsClassified(t *testing.T) {
	all := []TriggerType{
		TriggerDailyLossLimit,
		TriggerMarginBreach,
		TriggerEquityDrift,
		TriggerDataFeedStale,
		TriggerReconciliationFail,
		TriggerManualHalt,
		TriggerExpiryDayGammaSpike,
	}
	for _, tt := range all {
		if _, ok := triggerClassification[tt]; !ok {
			t.Fatalf("trigger %s has no explicit classification", tt)
		}
	}
	if len(triggerClassification) != len(all) {
		t.Fatalf("triggerClassification has entries not covered by this test's all-triggers list; update the test")
	}
}

func TestUnclassifiedTriggerPanics(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Fatal("expected IsHalting to panic on an unregistered trigger type")
		}
	}()
	IsHalting(TriggerType("NOT_REGISTERED"))
}

// TestNonHaltingTriggerDoesNotActivateKillSwitch is the direct
// regression test for the BTC P0 incident: a non-halting trigger
// (equity_drift-equivalent) must NEVER set the kill switch active,
// regardless of message content or call frequency.
func TestNonHaltingTriggerDoesNotActivateKillSwitch(t *testing.T) {
	ks := NewKillSwitch()
	nonHalting := []TriggerType{TriggerEquityDrift, TriggerDataFeedStale, TriggerExpiryDayGammaSpike}
	for _, tt := range nonHalting {
		ks.Trigger(tt, "test non-halting condition", false)
		if ks.IsActive() {
			t.Fatalf("trigger %s must be non-halting but activated the kill switch", tt)
		}
	}
}

func TestHaltingTriggersActivateKillSwitch(t *testing.T) {
	halting := []TriggerType{TriggerDailyLossLimit, TriggerMarginBreach, TriggerReconciliationFail, TriggerManualHalt}
	for _, tt := range halting {
		ks := NewKillSwitch()
		ks.Trigger(tt, "test halting condition", false)
		if !ks.IsActive() {
			t.Fatalf("trigger %s must be halting but did not activate the kill switch", tt)
		}
	}
}

func TestCallerCannotWeakenHaltingClassification(t *testing.T) {
	ks := NewKillSwitch()
	// Even passing haltingOverride=false must not prevent a halting
	// trigger from activating the kill switch — the classification
	// table is authoritative, not the caller's local boolean.
	ks.Trigger(TriggerDailyLossLimit, "attempt to weaken via override", false)
	if !ks.IsActive() {
		t.Fatal("halting trigger was weakened by caller override - this is the exact bug class being guarded against")
	}
}

func TestManualClearResetsActiveState(t *testing.T) {
	ks := NewKillSwitch()
	ks.Trigger(TriggerManualHalt, "operator halt", false)
	if !ks.IsActive() {
		t.Fatal("expected kill switch active after manual halt")
	}
	ks.ManualClear("test-operator")
	if ks.IsActive() {
		t.Fatal("expected kill switch inactive after manual clear")
	}
}

func TestHistoryPreservesNonHaltingEvents(t *testing.T) {
	ks := NewKillSwitch()
	ks.Trigger(TriggerEquityDrift, "small drift, informational", false)
	hist := ks.History()
	if len(hist) != 1 {
		t.Fatalf("expected 1 history entry, got %d", len(hist))
	}
	if hist[0].Halting {
		t.Fatal("equity drift event must be recorded as non-halting in history")
	}
}
