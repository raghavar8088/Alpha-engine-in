package backtest

import (
	"context"
	"fmt"
	"io"
	"log"
	"sort"
	"time"

	"niftypilot/internal/calendar"
	"niftypilot/internal/execution"
	"niftypilot/internal/indicators"
	"niftypilot/internal/instruments"
	"niftypilot/internal/ledger"
	"niftypilot/internal/marketdata"
	"niftypilot/internal/regime"
	"niftypilot/internal/risk"
	"niftypilot/internal/sizing"
	"niftypilot/internal/strategy"
	"niftypilot/internal/validator"
)

// Family classifies a strategy's holding horizon, derived from the live
// registry groups (no strategy code changes). It governs the exit policy:
// scalping/intraday positions are force-closed at session end; swing
// positions may hold across days until SL/TP.
type Family string

const (
	FamilyScalping Family = "scalping"
	FamilyIntraday Family = "intraday"
	FamilySwing    Family = "swing"
)

// Config is the backtest run configuration (mapped from CLI flags).
type Config struct {
	From        time.Time // UTC, inclusive trading start
	To          time.Time // UTC, inclusive trading end
	CapitalINR  float64
	WarmupDays  int
	Instruments []Instrument
	Verbose     bool
	Logw        io.Writer

	// MaxConcurrentStrategies caps simultaneous open positions (0 = unlimited).
	MaxConcurrentStrategies int
	// ProgressCallback is called after each 90-day chunk.
	ProgressCallback func(pct float64, msg string)
	// StrategyFilter when non-empty restricts evaluation to only these strategy names.
	StrategyFilter []string
}

// EquityPoint is one row of the equity curve (PART 4).
type EquityPoint struct {
	TimeUTC        time.Time
	EquityINR      float64 // capital + realized + unrealized (mark-to-market)
	RealizedINR    float64
	CumPnLINR      float64
	DailyReturnPct float64
}

// RegimePoint records a regime transition for regime_analysis.csv (PART 4).
type RegimePoint struct {
	TimeUTC          time.Time
	Underlying       string
	Regime           string
	PositionSizeMult float64
	ActiveStrategies int
	CumRealizedINR   float64
}

// KillEvent records a kill-switch activation during the backtest (PART 8).
type KillEvent struct {
	TimeUTC time.Time
	Reason  string
}

// BacktestResults is the full output of a run (PART 4).
type BacktestResults struct {
	From, To     time.Time
	CapitalINR   float64
	Instruments  []string
	DataSource   string
	Trades       []ledger.Trade // chronological by exit time (deterministic)
	Equity       []EquityPoint
	Daily        []DailyPnL
	Regimes      []RegimePoint
	WalkForward  []WalkForwardResult
	KillEvents   []KillEvent
	DataWarnings []string

	// Extended multi-year fields (populated only when run spans >1 year).
	YearlyBreakdowns   map[string][]YearlyBreakdown           // strategyName → per-year stats
	RegimePerformances map[string][]RegimePerformance         // strategyName → per-regime stats
	CorrelationMatrix  map[string]map[string]float64          // strategyA → strategyB → correlation
	MonthlyReturnsMap  map[string]map[int]map[int]float64     // strategyName → year → month → pnl
	DrawdownPeriods    []DrawdownPeriod                       // top-10 portfolio drawdowns
}

// DailyPnL is one row of daily_pnl.csv (PART 4).
type DailyPnL struct {
	DateIST          string
	DailyPnLINR      float64
	DailyReturnPct   float64
	MaxIntradayDDPct float64
	WinningTrades    int
	LosingTrades     int
}

// openPosition tracks a live backtest position for exit management.
type openPosition struct {
	tradeID    string
	strategy   string
	underlying string
	direction  string
	instrument string
	family     Family
	entry      float64
	sl, tp     float64
	qty        int64
	marginINR  float64
	entryAtUTC time.Time
}

// perStrategyStat accumulates rolling stats so the Kelly sizer can adapt
// to a strategy's realized edge (reusing sizing.PositionSizeINR exactly).
type perStrategyStat struct {
	trades     int
	wins       int
	sumWinPct  float64
	sumLossPct float64
}

// BacktestEngine replays history through the live pipeline (PART 2).
type BacktestEngine struct {
	cfg        Config
	cal        *calendar.Service
	classifier *regime.Classifier
	bundle     *marketdata.NiftyDataBundle
	cb         *ContextBuilder
	exec       *execution.Engine
	ledger     *ledger.Ledger
	risk       *risk.Engine
	strategies []strategy.Strategy
	tracks     map[string]*validator.StrategyTrack
	family     map[string]Family

	// ProgressCallback is called after each completed 90-day chunk with
	// (percentage 0..100, current simulation date as YYYY-MM-DD).
	ProgressCallback func(pct float64, msg string)

	// MaxConcurrentStrategies caps the number of simultaneously open strategy
	// positions (across all underlyings). 0 means unlimited.
	MaxConcurrentStrategies int

	open        map[string]*openPosition // key: strategy|underlying (one position each)
	stats       map[string]*perStrategyStat
	closed      []ledger.Trade // chronological close order
	realizedPnL float64        // running realized PnL summed in deterministic close order
	equity      []EquityPoint
	daily       []DailyPnL
	regimes     []RegimePoint
	killEvents  []KillEvent

	lastRegime map[string]regime.Regime // per underlying, for transition logging
}

// NewBacktestEngine wires the SAME components the live engine uses (PART 7):
// same calendar, classifier, bundle, execution engine, ledger, risk engine,
// strategy roster, and validator tracks. Only the data source differs.
func NewBacktestEngine(cfg Config, fetcher HistoricalDataFetcher) (*BacktestEngine, error) {
	cal := calendar.NewService()
	classifier := regime.NewClassifier(cal, regime.DefaultEventCalendar())
	bundle := marketdata.NewNiftyDataBundle()
	l := ledger.New()

	allStrats := strategy.AllStrategies()
	if len(cfg.StrategyFilter) > 0 {
		filterSet := map[string]bool{}
		for _, n := range cfg.StrategyFilter {
			filterSet[n] = true
		}
		var filtered []strategy.Strategy
		for _, s := range allStrats {
			if filterSet[s.Name()] {
				filtered = append(filtered, s)
			}
		}
		allStrats = filtered
	}

	e := &BacktestEngine{
		cfg:                     cfg,
		cal:                     cal,
		classifier:              classifier,
		bundle:                  bundle,
		cb:                      NewContextBuilder(bundle, classifier),
		exec:                    execution.NewEngine(l),
		ledger:                  l,
		risk:                    risk.NewEngine(risk.DefaultConfig(), cal, cfg.CapitalINR),
		strategies:              allStrats,
		tracks:                  map[string]*validator.StrategyTrack{},
		family:                  buildFamilyMap(),
		open:                    map[string]*openPosition{},
		stats:                   map[string]*perStrategyStat{},
		lastRegime:              map[string]regime.Regime{},
		ProgressCallback:        cfg.ProgressCallback,
		MaxConcurrentStrategies: cfg.MaxConcurrentStrategies,
	}
	for _, s := range e.strategies {
		e.tracks[s.Name()] = validator.NewStrategyTrack(s.Name())
		e.stats[s.Name()] = &perStrategyStat{}
	}

	if err := e.loadData(fetcher); err != nil {
		return nil, err
	}
	return e, nil
}

// buildFamilyMap derives each strategy's holding family from the live
// registry groups. Anything not scalping/swing (incl. S1–S9) is intraday.
func buildFamilyMap() map[string]Family {
	m := map[string]Family{}
	for _, s := range strategy.ScalpingStrategies() {
		m[s.Name()] = FamilyScalping
	}
	for _, s := range strategy.SwingStrategies() {
		m[s.Name()] = FamilySwing
	}
	for _, s := range strategy.AllStrategies() {
		if _, ok := m[s.Name()]; !ok {
			m[s.Name()] = FamilyIntraday
		}
	}
	return m
}

func (e *BacktestEngine) familyOf(name string) Family {
	if f, ok := e.family[name]; ok {
		return f
	}
	return FamilyIntraday
}

// loadData fetches every interval for every instrument (+ warmup) and
// registers the streams with the context builder.
func (e *BacktestEngine) loadData(fetcher HistoricalDataFetcher) error {
	warmupStart := e.cfg.From.AddDate(0, 0, -e.cfg.WarmupDays)
	intervals := []string{Interval1m, Interval5m, Interval15m, Interval1h}

	insts := append([]Instrument(nil), e.cfg.Instruments...)
	insts = append(insts, Instrument{Symbol: "INDIAVIX", Underlying: "INDIAVIX", Token: "INDIAVIX"})

	ctx := context.Background()
	for _, inst := range insts {
		byInterval := map[string][]Candle{}
		ivList := intervals
		if inst.IsVIX() {
			ivList = []string{Interval1m} // VIX only needs the base clock
		}
		for _, iv := range ivList {
			candles, err := fetcher.FetchCandles(ctx, inst, warmupStart, e.cfg.To, iv)
			if err != nil {
				return fmt.Errorf("fetch %s %s: %w", inst.Symbol, iv, err)
			}
			byInterval[iv] = candles
		}
		e.cb.AddInstrument(inst, byInterval)
	}
	return nil
}

// Run executes the replay loop and returns results (PART 2). Deterministic:
// the same inputs always produce identical trades and equity (CRITERION 4).
func (e *BacktestEngine) Run(ctx context.Context) (BacktestResults, error) {
	timeline := e.cb.BaseTimeline()
	if len(timeline) == 0 {
		return BacktestResults{}, ErrNoData
	}

	logw := e.cfg.Logw
	if logw == nil {
		logw = io.Discard
	}
	lg := log.New(logw, "", 0)

	startUTC := e.cfg.From
	endUTC := e.cfg.To
	underlyings := e.cb.Underlyings()

	var prevDate string
	var wasInSession bool
	var lastEquity = e.cfg.CapitalINR
	var dayStartEquity = e.cfg.CapitalINR
	var dayPeakEquity = e.cfg.CapitalINR
	var dayMaxDD float64
	var dayWins, dayLosses int
	var prevDayRealized float64

	// Progress tracking: fire callback every ~90 calendar days.
	totalSpan := endUTC.Sub(startUTC)
	var lastProgressFire time.Time
	const progressChunkDays = 90
	fireProgress := func(now time.Time) {
		if e.ProgressCallback == nil {
			return
		}
		if lastProgressFire.IsZero() || now.Sub(lastProgressFire) >= time.Duration(progressChunkDays)*24*time.Hour {
			lastProgressFire = now
			pct := 0.0
			if totalSpan > 0 {
				pct = now.Sub(startUTC).Seconds() / totalSpan.Seconds() * 100
				if pct > 100 {
					pct = 100
				}
			}
			e.ProgressCallback(pct, now.In(calendar.IST).Format("2006-01-02"))
		}
	}

	flushDaily := func(dateIST string) {
		if dateIST == "" {
			return
		}
		realizedNow := e.realizedPnL
		dayPnL := realizedNow - prevDayRealized
		ret := 0.0
		if dayStartEquity > 0 {
			ret = (lastEquity - dayStartEquity) / dayStartEquity
		}
		e.daily = append(e.daily, DailyPnL{
			DateIST: dateIST, DailyPnLINR: dayPnL, DailyReturnPct: ret * 100,
			MaxIntradayDDPct: dayMaxDD * 100, WinningTrades: dayWins, LosingTrades: dayLosses,
		})
		prevDayRealized = realizedNow
	}

	for _, now := range timeline {
		select {
		case <-ctx.Done():
			return BacktestResults{}, ctx.Err()
		default:
		}

		e.cb.Advance(now)
		inSession := e.cal.IsMarketOpen(now)
		istDate := now.In(calendar.IST).Format("2006-01-02")

		// Warmup: fill indicator history, take no trades, record nothing.
		if now.Before(startUTC) {
			wasInSession = inSession
			prevDate = istDate
			continue
		}
		if now.After(endUTC) {
			break
		}

		// New trading day: flush prior day's daily row, reset day counters,
		// and clear a per-day daily-loss halt (desk morning clear).
		if prevDate != "" && istDate != prevDate {
			flushDaily(prevDate)
			dayStartEquity = lastEquity
			dayPeakEquity = lastEquity
			dayMaxDD = 0
			dayWins, dayLosses = 0, 0
			if e.risk.KillSwitch().IsActive() {
				lg.Printf("%s session rollover: clearing per-day kill switch (%s)",
					istDate, e.risk.KillSwitch().ActiveReason())
				e.risk.KillSwitch().ManualClear("backtest-session-rollover")
			}
		}

		// Session just ended -> force-close scalping/intraday positions (PART 2.2).
		if wasInSession && !inSession {
			e.closeIntradayAtSessionEnd(now, lg)
		}

		if inSession {
			// 1) Manage exits for already-open positions on this bar.
			for _, u := range underlyings {
				e.manageExits(u, now, &dayWins, &dayLosses, lg)
			}
			// 2) Evaluate strategies for new entries.
			for _, u := range underlyings {
				e.evaluateEntries(u, now, lg)
			}
		}

		// 3) Mark-to-market equity snapshot.
		realized := e.realizedPnL
		unrealized := e.unrealizedPnL()
		eq := e.cfg.CapitalINR + realized + unrealized
		lastEquity = eq
		if eq > dayPeakEquity {
			dayPeakEquity = eq
		}
		if dayPeakEquity > 0 {
			dd := eq/dayPeakEquity - 1
			if dd < dayMaxDD {
				dayMaxDD = dd
			}
		}
		ret := 0.0
		if len(e.equity) > 0 && e.equity[len(e.equity)-1].EquityINR > 0 {
			ret = (eq - e.equity[len(e.equity)-1].EquityINR) / e.equity[len(e.equity)-1].EquityINR
		}
		e.equity = append(e.equity, EquityPoint{
			TimeUTC: now, EquityINR: eq, RealizedINR: realized,
			CumPnLINR: realized + unrealized, DailyReturnPct: ret * 100,
		})

		fireProgress(now)
		wasInSession = inSession
		prevDate = istDate
	}

	// Close any remaining open positions at the last known price.
	e.closeAllRemaining(endUTC, lg)
	flushDaily(prevDate)

	// Deterministic chronological order for the trade log + walk-forward.
	sortTradesByExit(e.closed)

	// Walk-forward per strategy, in registry order (deterministic).
	wf := make([]WalkForwardResult, 0, len(e.strategies))
	byStrat := map[string][]ledger.Trade{}
	for _, t := range e.closed {
		byStrat[t.Strategy] = append(byStrat[t.Strategy], t)
	}
	for _, s := range e.strategies {
		wf = append(wf, EvaluateWalkForward(s.Name(), byStrat[s.Name()], e.cfg.CapitalINR))
	}

	instNames := make([]string, 0, len(e.cfg.Instruments))
	for _, i := range e.cfg.Instruments {
		instNames = append(instNames, i.Symbol)
	}

	// Build extended multi-year stats.
	yearlyBreakdowns := map[string][]YearlyBreakdown{}
	monthlyReturnsMap := map[string]map[int]map[int]float64{}
	dailySeriesMap := map[string]map[string]float64{}
	for _, s := range e.strategies {
		st := byStrat[s.Name()]
		yearlyBreakdowns[s.Name()] = BuildYearlyBreakdowns(st, e.cfg.CapitalINR)
		mr := MonthlyReturns(st)
		monthlyReturnsMap[s.Name()] = mr
		dailySeriesMap[s.Name()] = DailyPnLSeries(st)
	}

	// Correlation matrix over daily PnL series.
	stratNames := make([]string, 0, len(e.strategies))
	for _, s := range e.strategies {
		stratNames = append(stratNames, s.Name())
	}
	corrMatrix := CorrelationMatrix(stratNames, dailySeriesMap)

	// Regime performance: tag each trade's regime from the regime transition log.
	regimePerfs := buildRegimePerformances(e.strategies, e.closed, e.regimes)

	// Top-10 portfolio drawdown periods.
	ddPeriods := TopDrawdownPeriods(e.equity, 10)

	return BacktestResults{
		From: startUTC, To: endUTC, CapitalINR: e.cfg.CapitalINR,
		Instruments: instNames, Trades: e.closed, Equity: e.equity,
		Daily: e.daily, Regimes: e.regimes, WalkForward: wf,
		KillEvents:         e.killEvents,
		YearlyBreakdowns:   yearlyBreakdowns,
		RegimePerformances: regimePerfs,
		CorrelationMatrix:  corrMatrix,
		MonthlyReturnsMap:  monthlyReturnsMap,
		DrawdownPeriods:    ddPeriods,
	}, nil
}

// sortedOpenKeys returns the open-position keys in deterministic order, so
// exit processing (and thus the closed-trade sequence) is reproducible —
// Go map iteration order is randomized and must never drive trade order.
func (e *BacktestEngine) sortedOpenKeys() []string {
	keys := make([]string, 0, len(e.open))
	for k := range e.open {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func (e *BacktestEngine) unrealizedPnL() float64 {
	var sum float64
	for _, k := range e.sortedOpenKeys() {
		p := e.open[k]
		cur := e.cb.Spot(p.underlying)
		if cur == 0 {
			cur = p.entry
		}
		sign := 1.0
		if p.direction == "SHORT" {
			sign = -1.0
		}
		sum += sign * (cur - p.entry) * float64(p.qty)
	}
	return sum
}

// manageExits checks each open position for SL/TP on the latest closed 1m
// bar of the underlying, exiting pessimistically (SL before TP).
func (e *BacktestEngine) manageExits(underlying string, now time.Time, wins, losses *int, lg *log.Logger) {
	candles := e.bundle.Candles(underlying, "1m")
	if len(candles) == 0 {
		return
	}
	bar := candles[len(candles)-1]
	atr := indicators.ATR(candles, 14)

	for _, key := range e.sortedOpenKeys() {
		p := e.open[key]
		if p.underlying != underlying {
			continue
		}
		var exitPx float64
		var reason string
		if p.direction == "LONG" {
			switch {
			case bar.Low <= p.sl:
				exitPx, reason = p.sl, "SL"
			case bar.High >= p.tp:
				exitPx, reason = p.tp, "TP"
			}
		} else { // SHORT
			switch {
			case bar.High >= p.sl:
				exitPx, reason = p.sl, "SL"
			case bar.Low <= p.tp:
				exitPx, reason = p.tp, "TP"
			}
		}
		if reason == "" {
			continue
		}
		e.closePosition(key, p, exitPx, now, reason, atr, wins, losses, lg)
	}
}

// closeIntradayAtSessionEnd force-closes scalping/intraday positions at the
// last close when the session ends (PART 2.2). Swing positions remain open.
func (e *BacktestEngine) closeIntradayAtSessionEnd(now time.Time, lg *log.Logger) {
	var d1, d2 int
	for _, key := range e.sortedOpenKeys() {
		p := e.open[key]
		if p.family == FamilySwing {
			continue
		}
		cur := e.cb.Spot(p.underlying)
		if cur == 0 {
			cur = p.entry
		}
		candles := e.bundle.Candles(p.underlying, "1m")
		atr := indicators.ATR(candles, 14)
		e.closePosition(key, p, cur, now, "TIME", atr, &d1, &d2, lg)
	}
}

func (e *BacktestEngine) closeAllRemaining(now time.Time, lg *log.Logger) {
	var d1, d2 int
	for _, key := range e.sortedOpenKeys() {
		p := e.open[key]
		cur := e.cb.Spot(p.underlying)
		if cur == 0 {
			cur = p.entry
		}
		candles := e.bundle.Candles(p.underlying, "1m")
		atr := indicators.ATR(candles, 14)
		e.closePosition(key, p, cur, now, "END", atr, &d1, &d2, lg)
	}
}

// closePosition executes the exit via the SAME execution engine, records the
// closed trade into the walk-forward track, releases margin, and updates
// directional risk counters and rolling Kelly stats.
func (e *BacktestEngine) closePosition(key string, p *openPosition, exitPx float64, now time.Time, reason string, atr float64, wins, losses *int, lg *log.Logger) {
	e.exec.ExecuteExit(p.tradeID, exitPx, now, reason, atr)
	t, ok := e.ledger.Trade(p.tradeID)
	if !ok {
		delete(e.open, key)
		return
	}
	e.closed = append(e.closed, t)
	// Sum realized PnL in deterministic close order. ledger.RealizedPnL()
	// folds over a map (random iteration order); float addition is not
	// associative, so its last-ULP result can vary run-to-run and flip a
	// Kelly/margin threshold — that would make the backtest non-deterministic.
	e.realizedPnL += t.NetPnL
	e.risk.RegisterClose(p.direction)
	e.risk.MarginBook().Release(p.marginINR)
	delete(e.open, key)

	win := t.NetPnL > 0
	if win {
		*wins++
	} else {
		*losses++
	}
	e.tracks[p.strategy].RecordTrade(validator.TradeResult{NetPnL: t.NetPnL, Win: win})

	// Update rolling Kelly stats (return as % of entry notional).
	st := e.stats[p.strategy]
	st.trades++
	notional := p.entry * float64(p.qty)
	if notional > 0 {
		pct := t.NetPnL / notional
		if win {
			st.wins++
			st.sumWinPct += pct
		} else {
			st.sumLossPct += -pct
		}
	}
	if e.cfg.Verbose {
		lg.Printf("%s EXIT %s %s %s qty=%d exit=%.2f net=%.2f reason=%s",
			now.In(calendar.IST).Format("2006-01-02 15:04"), p.strategy, p.underlying,
			p.direction, p.qty, exitPx, t.NetPnL, reason)
	}
}

// evaluateEntries runs the live evaluation pipeline for one underlying:
// classify → walk-forward gate → strategy.Evaluate → risk gate → size → fill.
func (e *BacktestEngine) evaluateEntries(underlying string, now time.Time, lg *log.Logger) {
	mctx, rc := e.cb.BuildContext(underlying, now)

	// Log regime transitions for regime_analysis.csv.
	if e.lastRegime[underlying] != rc.Regime {
		e.lastRegime[underlying] = rc.Regime
		e.regimes = append(e.regimes, RegimePoint{
			TimeUTC: now, Underlying: underlying, Regime: string(rc.Regime),
			PositionSizeMult: rc.PositionSizeMult,
			ActiveStrategies: e.countActiveStrategies(rc),
			CumRealizedINR:   e.realizedPnL,
		})
	}

	for _, s := range e.strategies {
		track := e.tracks[s.Name()]
		if track != nil && !track.IsTradeable() {
			continue // DEMOTED strategies are cut off, same as live
		}
		key := s.Name() + "|" + underlying
		if _, exists := e.open[key]; exists {
			continue // one open position per strategy+underlying
		}
		// Cap total concurrent open positions.
		if e.MaxConcurrentStrategies > 0 && len(e.open) >= e.MaxConcurrentStrategies {
			continue
		}
		sig, ok := s.Evaluate(mctx)
		if !ok {
			continue
		}
		equity := e.cfg.CapitalINR + e.realizedPnL
		allowed, reason := e.risk.CheckEntryAllowed(now, equity, string(sig.Direction))
		if !allowed {
			if e.risk.KillSwitch().IsActive() {
				e.recordKill(now, e.risk.KillSwitch().ActiveReason())
			}
			_ = reason
			continue
		}
		e.enter(s.Name(), sig, rc, now, lg)
	}
}

func (e *BacktestEngine) recordKill(now time.Time, reason string) {
	// De-dup consecutive identical kills.
	if n := len(e.killEvents); n > 0 && e.killEvents[n-1].Reason == reason {
		return
	}
	e.killEvents = append(e.killEvents, KillEvent{TimeUTC: now, Reason: reason})
}

// enter sizes the position with the SAME Kelly sizer + margin book the live
// engine uses, fills via the SAME execution engine, and registers the open.
func (e *BacktestEngine) enter(name string, sig strategy.Signal, rc regime.RegimeClass, now time.Time, lg *log.Logger) {
	lots, marginINR := e.sizeLots(name, sig, rc, now)
	if lots < 1 {
		return
	}
	candles := e.bundle.Candles(sig.Underlying, "1m")
	atr := indicators.ATR(candles, 14)

	trade := e.exec.ExecuteEntry(sig, lots, atr)
	e.risk.RegisterOpen(trade.Direction)
	e.risk.MarginBook().Block(marginINR)

	key := name + "|" + sig.Underlying
	e.open[key] = &openPosition{
		tradeID: trade.ID, strategy: name, underlying: sig.Underlying,
		direction: trade.Direction, instrument: sig.Instrument, family: e.familyOf(name),
		entry: trade.EntryPrice, sl: sig.StopLoss, tp: sig.TakeProfit,
		qty: trade.Quantity, marginINR: marginINR, entryAtUTC: now,
	}
	if e.cfg.Verbose {
		lg.Printf("%s ENTRY %s %s %s lots=%d entry=%.2f sl=%.2f tp=%.2f regime=%s",
			now.In(calendar.IST).Format("2006-01-02 15:04"), name, sig.Underlying,
			sig.Direction, lots, trade.EntryPrice, sig.StopLoss, sig.TakeProfit, rc.Regime)
	}
}

// sizeLots applies the live half-Kelly sizer (sizing.PositionSizeINR) with
// regime/session/VIX multipliers, then converts to whole lots under the
// margin book (sizing.LotsForRisk). Falls back to 1 lot when Kelly yields a
// sub-1-lot budget but margin permits, so screening still accrues trades.
func (e *BacktestEngine) sizeLots(name string, sig strategy.Signal, rc regime.RegimeClass, now time.Time) (int64, float64) {
	lotSize := instruments.LotSize[sig.Underlying]
	if lotSize == 0 {
		lotSize = 1
	}
	slDist := sig.Entry - sig.StopLoss
	if slDist < 0 {
		slDist = -slDist
	}
	if slDist == 0 {
		return 0, 0
	}
	perLotRisk := slDist * float64(lotSize)
	marginPerLot := e.marginPerLot(sig)

	// Rolling edge -> Kelly inputs (defaults until a strategy has history).
	winRate, avgWinPct, avgLossPct := e.kellyInputs(name)
	istMin := now.In(calendar.IST).Hour()*60 + now.In(calendar.IST).Minute()
	budget := sizing.PositionSizeINR(sizing.KellyInputsIndia{
		PortfolioINR:   e.cfg.CapitalINR + e.realizedPnL,
		MaxPositionPct: 0.10,
		RegimeMult:     rc.PositionSizeMult,
		SessionMult:    sizing.SessionMultiplier(istMin),
		VIXMult:        sizing.VIXMultiplier(rc.VIXLevel),
		WinRate:        winRate, AvgWinPct: avgWinPct, AvgLossPct: avgLossPct,
	})

	lots := sizing.LotsForRisk(budget, perLotRisk, marginPerLot, e.risk.MarginBook())
	if lots < 1 && e.risk.MarginBook().CanOpen(marginPerLot) {
		lots = 1 // minimum screening size
	}
	if lots < 1 {
		return 0, 0
	}
	return lots, marginPerLot * float64(lots)
}

func (e *BacktestEngine) marginPerLot(sig strategy.Signal) float64 {
	switch sig.Instrument {
	case "FUTURE":
		return sizing.EstimateFuture(sig.Underlying, sig.Entry, 1).TotalMarginINR
	case "STRANGLE":
		step := 50.0
		if sig.Underlying == "BANKNIFTY" {
			step = 100.0
		}
		return sizing.EstimateShortStrangle(sig.Underlying, sig.Strike, sig.Strike-2*step, sig.Entry, 1).TotalMarginINR
	default: // CE / PE — notional-based proxy (documented approximation)
		return sizing.EstimateShortOption(sig.Underlying, sig.Strike, sig.Entry, 1).TotalMarginINR
	}
}

// kellyInputs returns rolling win-rate and avg win/loss % for a strategy,
// or conservative seeds (positive edge) until ≥10 trades have accrued.
func (e *BacktestEngine) kellyInputs(name string) (winRate, avgWinPct, avgLossPct float64) {
	st := e.stats[name]
	if st == nil || st.trades < 10 {
		return 0.50, 0.006, 0.004 // seed: modest positive edge
	}
	winRate = float64(st.wins) / float64(st.trades)
	losses := st.trades - st.wins
	if st.wins > 0 {
		avgWinPct = st.sumWinPct / float64(st.wins)
	}
	if losses > 0 {
		avgLossPct = st.sumLossPct / float64(losses)
	}
	if avgWinPct <= 0 {
		avgWinPct = 0.004
	}
	if avgLossPct <= 0 {
		avgLossPct = 0.004
	}
	return winRate, avgWinPct, avgLossPct
}

func (e *BacktestEngine) countActiveStrategies(rc regime.RegimeClass) int {
	count := 0
	for _, s := range e.strategies {
		if strategy.RegimeAllowed(s, rc) {
			count++
		}
	}
	return count
}

// sortTradesByExit guarantees deterministic chronological ordering even if
// two trades exit on the same bar (tie-break by strategy then trade ID).
func sortTradesByExit(trades []ledger.Trade) {
	sort.SliceStable(trades, func(i, j int) bool {
		if !trades[i].ExitAt.Equal(trades[j].ExitAt) {
			return trades[i].ExitAt.Before(trades[j].ExitAt)
		}
		if trades[i].Strategy != trades[j].Strategy {
			return trades[i].Strategy < trades[j].Strategy
		}
		return trades[i].ID < trades[j].ID
	})
}

// buildRegimePerformances assigns each closed trade to the regime that was
// active at its entry time (from the regime transition log) and aggregates
// per-strategy per-regime stats.
func buildRegimePerformances(strategies []strategy.Strategy, trades []ledger.Trade, regimes []RegimePoint) map[string][]RegimePerformance {
	// Build a sorted list of (time, regime) transitions for fast lookup.
	type transition struct {
		at     time.Time
		regime string
	}
	var transitions []transition
	for _, r := range regimes {
		transitions = append(transitions, transition{at: r.TimeUTC, regime: r.Regime})
	}
	sort.Slice(transitions, func(i, j int) bool {
		return transitions[i].at.Before(transitions[j].at)
	})

	regimeAt := func(t time.Time) string {
		regime := "UNKNOWN"
		for _, tr := range transitions {
			if !tr.at.After(t) {
				regime = tr.regime
			} else {
				break
			}
		}
		return regime
	}

	// Accumulate per-strategy per-regime stats.
	type key struct{ strategy, regime string }
	type acc struct {
		trades int
		wins   int
		netPnL float64
	}
	data := map[key]*acc{}
	for _, t := range trades {
		r := regimeAt(t.EntryAt)
		k := key{t.Strategy, r}
		if data[k] == nil {
			data[k] = &acc{}
		}
		data[k].trades++
		data[k].netPnL += t.NetPnL
		if t.NetPnL > 0 {
			data[k].wins++
		}
	}

	result := map[string][]RegimePerformance{}
	for _, s := range strategies {
		name := s.Name()
		var perfs []RegimePerformance
		for _, regimeName := range []string{"TRENDING_BULL", "TRENDING_BEAR", "RANGING", "HIGH_VOL", "EXPIRY_DAY", "EVENT_RISK"} {
			k := key{name, regimeName}
			a := data[k]
			if a == nil {
				continue
			}
			wr := 0.0
			if a.trades > 0 {
				wr = float64(a.wins) / float64(a.trades)
			}
			perfs = append(perfs, RegimePerformance{
				RegimeName: regimeName, Trades: a.trades,
				WinRate: wr, NetPnL: a.netPnL,
				AvgPnL: a.netPnL / float64(max1(a.trades)),
			})
		}
		result[name] = perfs
	}
	return result
}

func max1(n int) int {
	if n < 1 {
		return 1
	}
	return n
}
