// Package metrics exposes the Prometheus instrumentation, mirroring
// the BTC engine's metrics surface exactly per the build spec: signal
// counters per strategy/outcome, walk-forward status, margin
// utilization, India VIX, regime, and data-feed staleness.
package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	SignalsEvaluated = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "niftypilot_signals_evaluated_total",
		Help: "Strategy signal evaluations, labeled by strategy and underlying.",
	}, []string{"strategy", "underlying"})

	SignalsRejected = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "niftypilot_signals_rejected_total",
		Help: "Strategy signals rejected by validity/regime/risk gating, labeled by strategy and reason.",
	}, []string{"strategy", "reason"})

	SignalsExecuted = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "niftypilot_signals_executed_total",
		Help: "Strategy signals that resulted in a paper fill, labeled by strategy and direction.",
	}, []string{"strategy", "direction"})

	WalkForwardStatus = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "niftypilot_walkforward_status",
		Help: "Walk-forward validator status per strategy: 0=PROBATION 1=PENDING 2=ACTIVE 3=DEMOTED.",
	}, []string{"strategy"})

	MarginUtilizationPct = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "niftypilot_margin_utilization_pct",
		Help: "Current margin utilization as a fraction of total paper capital.",
	})

	IndiaVIXLevel = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "niftypilot_india_vix",
		Help: "Current India VIX level.",
	})

	RegimeState = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "niftypilot_regime_state",
		Help: "Current regime classification per underlying (1=active regime, labeled by regime name).",
	}, []string{"underlying", "regime"})

	DataFeedStalenessSeconds = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "niftypilot_data_feed_staleness_seconds",
		Help: "Seconds since the last tick was received per feed key.",
	}, []string{"feed"})

	KillSwitchActive = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "niftypilot_kill_switch_active",
		Help: "1 if the kill switch is currently ACTIVE (halting), 0 otherwise.",
	})

	RealizedPnLINR = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "niftypilot_realized_pnl_inr",
		Help: "Cumulative realized paper PnL in INR.",
	})
)

// WalkForwardStatusValue maps a validator.Status string to the numeric
// gauge value documented in WalkForwardStatus's Help string.
func WalkForwardStatusValue(status string) float64 {
	switch status {
	case "PROBATION":
		return 0
	case "PENDING":
		return 1
	case "ACTIVE":
		return 2
	case "DEMOTED":
		return 3
	default:
		return -1
	}
}
