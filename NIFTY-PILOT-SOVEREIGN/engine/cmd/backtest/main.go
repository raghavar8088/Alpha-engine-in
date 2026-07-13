// Command backtest is the NIFTY-PILOT SOVEREIGN walk-forward backtest
// harness. It replays historical candles through the EXACT same strategy,
// regime, risk, sizing, and execution code the live engine uses (no forks),
// and emits performance + walk-forward reports. PAPER/SIMULATION ONLY.
//
// It is intentionally a SEPARATE binary (engine/cmd/backtest) from the live
// engine (engine/cmd/niftypilot) — PART 0 rule 10. It imports the live
// internal packages read-only and modifies none of them.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"niftypilot/internal/backtest"
	"niftypilot/internal/calendar"
)

func main() {
	var (
		fromStr       = flag.String("backtest-from", "", "start date, ISO 8601 YYYY-MM-DD")
		toStr         = flag.String("backtest-to", "", "end date, ISO 8601 YYYY-MM-DD")
		capital       = flag.Float64("backtest-capital", 1_00_00_000, "starting capital in INR")
		instStr       = flag.String("backtest-instruments", "NIFTY50,BANKNIFTY", "comma-separated instruments")
		dataSource    = flag.String("backtest-data-source", "Kite", "Kite | NSE | Synthetic | SyntheticMultiYear")
		outputDir     = flag.String("backtest-output-dir", "backtest_results", "output directory root")
		warmupDays    = flag.Int("backtest-warmup-days", 60, "days of warmup history before start")
		verbose       = flag.Bool("backtest-verbose", false, "verbose execution logging")
		syntheticSeed = flag.Int64("backtest-seed", 42, "deterministic seed for the Synthetic data source")
		yearsFlag     = flag.Int("backtest-years", 1, "number of years to backtest (1–5); overrides --backtest-from/to when >0")
		strategiesStr = flag.String("backtest-strategies", "", "comma-separated strategy IDs to run (empty = all)")
		outputFormat  = flag.String("backtest-output-format", "json", "report format: json | csv | both")
		showProgress  = flag.Bool("backtest-progress", false, "print progress to stdout")
		serveFlag     = flag.Bool("serve", false, "run HTTP job server on --serve-addr")
		serveAddr     = flag.String("serve-addr", ":8090", "address for HTTP serve mode")
		maxConcurrent = flag.Int("backtest-max-concurrent", 0, "max concurrent open positions (0 = unlimited)")
	)
	flag.Parse()

	if *serveFlag {
		runServer(*serveAddr, *outputDir, *syntheticSeed)
		return
	}

	// When --backtest-years is given, derive from/to automatically.
	if *yearsFlag > 0 && *fromStr == "" {
		y := *yearsFlag
		if y > 5 {
			y = 5
		}
		now := time.Now().In(calendar.IST)
		*toStr = now.Format("2006-01-02")
		*fromStr = now.AddDate(-y, 0, 0).Format("2006-01-02")
	}

	if *fromStr == "" || *toStr == "" {
		fmt.Fprintln(os.Stderr, "error: --backtest-from and --backtest-to are required (or use --backtest-years)")
		flag.Usage()
		os.Exit(2)
	}

	from, err := parseISTDate(*fromStr, false)
	if err != nil {
		log.Fatalf("invalid --backtest-from: %v", err)
	}
	to, err := parseISTDate(*toStr, true)
	if err != nil {
		log.Fatalf("invalid --backtest-to: %v", err)
	}
	if !to.After(from) {
		log.Fatal("--backtest-to must be after --backtest-from")
	}

	instruments, err := parseInstruments(*instStr)
	if err != nil {
		log.Fatalf("invalid --backtest-instruments: %v", err)
	}

	outDir := backtest.TimestampedDir(*outputDir, time.Now())
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		log.Fatalf("cannot create output dir: %v", err)
	}
	logFile, err := os.Create(outDir + "/backtest.log")
	if err != nil {
		log.Fatalf("cannot create backtest.log: %v", err)
	}
	defer logFile.Close()
	var logw io.Writer = logFile
	if *verbose {
		logw = io.MultiWriter(logFile, os.Stdout)
	}

	cacheDir := *outputDir + "/.cache"
	cache, err := backtest.NewCandleCache(cacheDir)
	if err != nil {
		log.Fatalf("cache init: %v", err)
	}

	fetcher, sourceName := buildFetcher(*dataSource, cache, *syntheticSeed)

	var stratFilter []string
	if *strategiesStr != "" {
		for _, s := range strings.Split(*strategiesStr, ",") {
			s = strings.TrimSpace(s)
			if s != "" {
				stratFilter = append(stratFilter, s)
			}
		}
	}

	var progressCB func(float64, string)
	if *showProgress {
		progressCB = func(pct float64, msg string) {
			fmt.Printf("[%5.1f%%] %s\n", pct*100, msg)
		}
	}

	cfg := backtest.Config{
		From: from, To: to, CapitalINR: *capital, WarmupDays: *warmupDays,
		Instruments: instruments, Verbose: *verbose, Logw: logw,
		StrategyFilter:         stratFilter,
		ProgressCallback:       progressCB,
		MaxConcurrentStrategies: *maxConcurrent,
	}

	fmt.Printf("NIFTY-PILOT backtest  |  %s → %s  |  source=%s  |  capital=₹%.0f\n",
		from.In(calendar.IST).Format("2006-01-02"), to.In(calendar.IST).Format("2006-01-02"),
		sourceName, *capital)

	engine, err := backtest.NewBacktestEngine(cfg, fetcher)
	if err != nil {
		log.Fatalf("engine init: %v", err)
	}

	start := time.Now()
	results, err := engine.Run(context.Background())
	if err != nil {
		log.Fatalf("backtest run: %v", err)
	}
	results.DataSource = sourceName
	fmt.Printf("replay complete in %s — %d trades, %d kill events\n",
		time.Since(start).Round(time.Millisecond), len(results.Trades), len(results.KillEvents))

	switch strings.ToLower(*outputFormat) {
	case "csv":
		if err := backtest.GenerateCSVOnly(results, outDir); err != nil {
			log.Fatalf("report generation: %v", err)
		}
	case "both":
		if err := backtest.GenerateAll(results, outDir); err != nil {
			log.Fatalf("report generation: %v", err)
		}
		if err := backtest.GenerateCSVOnly(results, outDir); err != nil {
			log.Fatalf("CSV generation: %v", err)
		}
	default: // "json"
		if err := backtest.GenerateAll(results, outDir); err != nil {
			log.Fatalf("report generation: %v", err)
		}
	}

	printConsoleSummary(results, outDir)
}

// ─────────────────────────────────────────────────────────────────────────────
// HTTP serve mode
// ─────────────────────────────────────────────────────────────────────────────

type jobStatus struct {
	ID       string                  `json:"id"`
	Status   string                  `json:"status"` // RUNNING | DONE | ERROR
	Progress float64                 `json:"progress"`
	Message  string                  `json:"message,omitempty"`
	Error    string                  `json:"error,omitempty"`
	Results  *backtest.BacktestResults `json:"results,omitempty"`
	OutDir   string                  `json:"out_dir,omitempty"`
}

type jobStore struct {
	mu   sync.RWMutex
	jobs map[string]*jobStatus
}

func (s *jobStore) get(id string) (*jobStatus, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	j, ok := s.jobs[id]
	return j, ok
}

func (s *jobStore) set(j *jobStatus) {
	s.mu.Lock()
	s.jobs[j.ID] = j
	s.mu.Unlock()
}

func (s *jobStore) list() []*jobStatus {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*jobStatus, 0, len(s.jobs))
	for _, j := range s.jobs {
		out = append(out, j)
	}
	return out
}

func (s *jobStore) delete(id string) {
	s.mu.Lock()
	delete(s.jobs, id)
	s.mu.Unlock()
}

type runRequest struct {
	FromStr       string   `json:"from"`
	ToStr         string   `json:"to"`
	Years         int      `json:"years"`
	Capital       float64  `json:"capital"`
	Instruments   string   `json:"instruments"`
	DataSource    string   `json:"data_source"`
	Strategies    []string `json:"strategies"`
	MaxConcurrent int      `json:"max_concurrent"`
}

func runServer(addr, outputDir string, seed int64) {
	store := &jobStore{jobs: make(map[string]*jobStatus)}
	mux := http.NewServeMux()

	// POST /run — submit a backtest job.
	mux.HandleFunc("/run", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}
		var req runRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad JSON: "+err.Error(), http.StatusBadRequest)
			return
		}
		if req.Capital <= 0 {
			req.Capital = 1_00_00_000
		}
		if req.Instruments == "" {
			req.Instruments = "NIFTY50,BANKNIFTY"
		}
		if req.DataSource == "" {
			req.DataSource = "Synthetic"
		}

		id := fmt.Sprintf("job_%d", time.Now().UnixNano())
		job := &jobStatus{ID: id, Status: "RUNNING"}
		store.set(job)

		go func() {
			from, to, err := resolveDateRange(req.FromStr, req.ToStr, req.Years)
			if err != nil {
				job.Status = "ERROR"
				job.Error = err.Error()
				store.set(job)
				return
			}
			instruments, err := parseInstruments(req.Instruments)
			if err != nil {
				job.Status = "ERROR"
				job.Error = err.Error()
				store.set(job)
				return
			}
			cacheDir := outputDir + "/.cache"
			cache, _ := backtest.NewCandleCache(cacheDir)
			fetcher, sourceName := buildFetcher(req.DataSource, cache, seed)
			outDir := backtest.TimestampedDir(outputDir, time.Now())

			cfg := backtest.Config{
				From: from, To: to, CapitalINR: req.Capital,
				Instruments: instruments, WarmupDays: 60,
				StrategyFilter:          req.Strategies,
				MaxConcurrentStrategies: req.MaxConcurrent,
				ProgressCallback: func(pct float64, msg string) {
					job.Progress = pct
					job.Message = msg
					store.set(job)
				},
				Logw: io.Discard,
			}

			eng, err := backtest.NewBacktestEngine(cfg, fetcher)
			if err != nil {
				job.Status = "ERROR"
				job.Error = err.Error()
				store.set(job)
				return
			}

			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
			defer cancel()
			results, err := eng.Run(ctx)
			if err != nil {
				job.Status = "ERROR"
				job.Error = err.Error()
				store.set(job)
				return
			}
			results.DataSource = sourceName
			_ = backtest.GenerateAll(results, outDir)

			job.Status = "DONE"
			job.Progress = 1.0
			job.Results = &results
			job.OutDir = outDir
			store.set(job)
		}()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(map[string]string{"job_id": id})
	})

	// GET /status/{jobId}
	mux.HandleFunc("/status/", func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimPrefix(r.URL.Path, "/status/")
		job, ok := store.get(id)
		if !ok {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		// Omit full results in status response.
		summary := map[string]any{
			"id": job.ID, "status": job.Status,
			"progress": job.Progress, "message": job.Message,
			"error": job.Error, "out_dir": job.OutDir,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(summary)
	})

	// GET /results/{jobId}
	mux.HandleFunc("/results/", func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/results/")
		parts := strings.SplitN(path, "/", 2)
		id := parts[0]
		job, ok := store.get(id)
		if !ok {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if job.Status != "DONE" {
			http.Error(w, "job not complete", http.StatusConflict)
			return
		}
		// Sub-resource: /results/{jobId}/equity_curve
		if len(parts) == 2 && parts[1] == "equity_curve" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(job.Results.Equity)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(job.Results)
	})

	// GET /list
	mux.HandleFunc("/list", func(w http.ResponseWriter, r *http.Request) {
		jobs := store.list()
		summaries := make([]map[string]any, 0, len(jobs))
		for _, j := range jobs {
			summaries = append(summaries, map[string]any{
				"id": j.ID, "status": j.Status,
				"progress": j.Progress, "out_dir": j.OutDir,
			})
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(summaries)
	})

	// DELETE /jobs/{jobId}
	mux.HandleFunc("/jobs/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodDelete {
			http.Error(w, "DELETE only", http.StatusMethodNotAllowed)
			return
		}
		id := strings.TrimPrefix(r.URL.Path, "/jobs/")
		store.delete(id)
		w.WriteHeader(http.StatusNoContent)
	})

	fmt.Printf("backtest HTTP server listening on %s\n", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func resolveDateRange(fromStr, toStr string, years int) (time.Time, time.Time, error) {
	if years > 0 && fromStr == "" {
		if years > 5 {
			years = 5
		}
		now := time.Now().In(calendar.IST)
		toStr = now.Format("2006-01-02")
		fromStr = now.AddDate(-years, 0, 0).Format("2006-01-02")
	}
	from, err := parseISTDate(fromStr, false)
	if err != nil {
		return time.Time{}, time.Time{}, fmt.Errorf("invalid from date: %w", err)
	}
	to, err := parseISTDate(toStr, true)
	if err != nil {
		return time.Time{}, time.Time{}, fmt.Errorf("invalid to date: %w", err)
	}
	if !to.After(from) {
		return time.Time{}, time.Time{}, fmt.Errorf("to must be after from")
	}
	return from, to, nil
}

// buildFetcher selects the data source. Kite/NSE need credentials; when Kite
// is requested without KITE_API_KEY/KITE_ACCESS_TOKEN it auto-falls back to
// the deterministic Synthetic source so the harness always runs offline.
func buildFetcher(source string, cache *backtest.CandleCache, seed int64) (backtest.HistoricalDataFetcher, string) {
	switch strings.ToLower(source) {
	case "kite":
		key, tok := os.Getenv("KITE_API_KEY"), os.Getenv("KITE_ACCESS_TOKEN")
		if key == "" || tok == "" {
			fmt.Println("Kite credentials not set — falling back to Synthetic")
			return backtest.NewSyntheticFetcher(seed), "Synthetic"
		}
		return backtest.NewKiteHistoricalFetcher(key, tok, cache), "Kite"
	case "nse":
		return backtest.NewNSEFTPFetcher(cache), "NSE"
	case "syntheticmultiyear":
		return backtest.NewSyntheticMultiYearFetcher(seed), "SyntheticMultiYear"
	default:
		return backtest.NewSyntheticFetcher(seed), "Synthetic"
	}
}

func printConsoleSummary(res backtest.BacktestResults, outDir string) {
	var promoted, rejected, insufficient int
	for _, wf := range res.WalkForward {
		switch wf.PromotionStatus {
		case backtest.PromotionPromoted:
			promoted++
		case backtest.PromotionRejected:
			rejected++
		default:
			insufficient++
		}
	}
	endEquity := res.CapitalINR
	if len(res.Equity) > 0 {
		endEquity = res.Equity[len(res.Equity)-1].EquityINR
	}
	fmt.Println("─────────────────────────────────────────────")
	fmt.Printf("Net PnL:        ₹%.2f\n", endEquity-res.CapitalINR)
	fmt.Printf("Promoted:       %d\n", promoted)
	fmt.Printf("Rejected:       %d\n", rejected)
	fmt.Printf("Insufficient:   %d\n", insufficient)
	fmt.Printf("Reports:        %s\n", outDir)
	fmt.Println("─────────────────────────────────────────────")
}

// parseISTDate parses YYYY-MM-DD in IST. endOfDay=true returns 23:59:59 IST.
func parseISTDate(s string, endOfDay bool) (time.Time, error) {
	d, err := time.ParseInLocation("2006-01-02", s, calendar.IST)
	if err != nil {
		return time.Time{}, err
	}
	if endOfDay {
		d = d.Add(23*time.Hour + 59*time.Minute + 59*time.Second)
	}
	return d.UTC(), nil
}

// parseInstruments maps CLI names to canonical underlyings + Kite tokens.
func parseInstruments(s string) ([]backtest.Instrument, error) {
	tokens := map[string]struct{ underlying, token string }{
		"NIFTY50":   {"NIFTY", "256265"},
		"NIFTY":     {"NIFTY", "256265"},
		"BANKNIFTY": {"BANKNIFTY", "260105"},
	}
	var out []backtest.Instrument
	for _, name := range strings.Split(s, ",") {
		name = strings.TrimSpace(strings.ToUpper(name))
		if name == "" {
			continue
		}
		m, ok := tokens[name]
		if !ok {
			return nil, fmt.Errorf("unknown instrument %q (supported: NIFTY50, BANKNIFTY)", name)
		}
		out = append(out, backtest.Instrument{Symbol: name, Underlying: m.underlying, Token: m.token})
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("no instruments parsed")
	}
	return out, nil
}
