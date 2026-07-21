"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BaselineSeries,
  CandlestickData,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import IndicatorPanel, {
  DEFAULT_INDICATORS,
  EMA_COLORS,
  IndicatorConfig,
  SMA_COLORS,
} from "./IndicatorPanel";
import {
  Bar,
  bollinger,
  ema,
  heikinAshi,
  macd,
  Point,
  referenceLevels,
  rsi,
  sma,
  supertrend,
  valueAt,
  vwap,
} from "./indicators";
import { StreamStatus, useChartStream } from "./useChartStream";
import OverlayPanel, { DEFAULT_OVERLAYS, OverlayConfig, ReplayState } from "./OverlayPanel";
import AnalysisPanel from "./AnalysisPanel";
import WorkspacePanel, { DrawingTool } from "./WorkspacePanel";
import DrawToolbar from "./DrawToolbar";
import CompareGrid from "./CompareGrid";
import WatchlistPanel from "./WatchlistPanel";
import {
  ChartAlert,
  ChartDrawing,
  ChartDrawingPoint,
  ChartLayout,
  createChartAlert,
  deleteChartAlert,
  deleteChartDrawing,
  deleteChartLayout,
  evaluateChartAlerts,
  fetchChartAlerts,
  fetchChartDrawings,
  fetchChartLayouts,
  saveChartDrawing,
  updateChartDrawing,
  saveChartLayout,
} from "../../lib/api";
import {
  ChartBacktestRun,
  ChartBacktestTrade,
  ChartCallOverlay,
  ChartExplanation,
  ChartOptionContext,
  ChartPositionOverlay,
  ChartResolution,
  ChartStructure,
  ChartSymbol,
  ChartSymbolInfo,
  ChartTrend,
  explainChart,
  fetchChartBacktests,
  fetchChartBacktestTrades,
  fetchChartHistory,
  fetchChartOptionContext,
  fetchChartOverlays,
  fetchChartStructure,
  fetchChartTrendline,
  resolveChartSymbol,
  searchChartSymbols,
} from "../../lib/api";

const RESOLUTIONS: { id: ChartResolution; label: string; lookbackSeconds: number }[] = [
  { id: "1", label: "1m", lookbackSeconds: 2 * 86400 },
  { id: "5", label: "5m", lookbackSeconds: 5 * 86400 },
  { id: "15", label: "15m", lookbackSeconds: 10 * 86400 },
  { id: "60", label: "1H", lookbackSeconds: 30 * 86400 },
  { id: "D", label: "D", lookbackSeconds: 400 * 86400 },
  { id: "W", label: "W", lookbackSeconds: 5 * 365 * 86400 },
];

const INTRADAY_RESOLUTIONS: ChartResolution[] = ["1", "5", "15", "60"];

/** Bar width per resolution, used to decide whether a streamed update belongs
 * to the bar the chart is already showing or to the next one. */
const RESOLUTION_SECONDS: Record<ChartResolution, number> = {
  "1": 60, "5": 300, "15": 900, "60": 3600, D: 86400, W: 604800,
};

// A streamed bar that lands somewhere the history grid doesn't expect is never
// drawn — it's far worse to paint a candle at the wrong timestamp than to miss
// an update. Instead, after a few consecutive mismatches the page re-pulls
// history, which is the source of truth, no more often than this.
// Standard retracement ladder, including the 0/100 anchors so the swing itself is
// drawn too. 78.6% is the square root of 61.8% and is the one traders add beyond
// the textbook set.
const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

// How close the pointer must get to an anchor to grab it. Generous enough to hit
// on a trackpad without stealing ordinary clicks on the chart.
const GRAB_RADIUS = 10;

// Default sizing for a freshly placed Long/Short Position: risk 1% of entry price,
// reward twice that — a 1:2 risk:reward starting point, same convention the tool
// carries in TradingView. Either handle is draggable afterward to any ratio.
const POSITION_DEFAULT_RISK_PCT = 0.01;
const POSITION_DEFAULT_REWARD_MULTIPLE = 2;
// How far right of the entry click the position box extends, in bars rather than
// a fixed duration so it reads the same width at any timeframe.
const POSITION_WIDTH_BARS = 20;

// Palette offered for drawings. Kept small and legible on the chart background
// rather than exposing a full colour wheel.
const DRAW_COLORS = ["#f2b705", "#7d34dc", "#0e9f6e", "#d92d3f", "#2f80ed", "#e0e0e0"];

/** Hex (#rgb or #rrggbb) to rgba() so a zone can be filled semi-transparently.
 *  Anything already in a functional form is returned untouched. */
function withAlpha(color: string, alpha: number): string {
  const hex = color.trim();
  if (!hex.startsWith("#")) return hex;
  const body = hex.slice(1);
  const full = body.length === 3 ? body.split("").map((ch) => ch + ch).join("") : body;
  if (full.length !== 6) return hex;
  const value = parseInt(full, 16);
  if (Number.isNaN(value)) return hex;
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

const RESYNC_MISMATCHES = 3;
const RESYNC_COOLDOWN_MS = 120_000;

/** One overlay line drawn on the price pane. Built once per data/config change
 * and reused by both the series-sync effect and the crosshair legend, so the
 * HUD can never disagree with what's actually rendered. */
interface Overlay {
  key: string;
  label: string;
  color: string;
  data: Point[];
  lineWidth: 1 | 2;
  lineStyle: LineStyle;
}

interface HudRow {
  label: string;
  color: string;
  value: number | null;
}

const fmt = (n: number | null | undefined, digits = 2) =>
  n === null || n === undefined || Number.isNaN(n) ? "–" : n.toFixed(digits);

/** "28 Aug" from an ISO expiry date, for contract labels. */
function shortExpiry(expiry: string | null | undefined): string | null {
  if (!expiry) return null;
  const parsed = new Date(expiry);
  if (Number.isNaN(parsed.getTime())) return expiry;
  return parsed.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

/** A derivative's own symbol is an opaque contract code, so build the label a
 * trader actually recognises: "NIFTY 24500 CE · 28 Aug". Non-derivatives keep
 * their plain ticker. */
function contractLabel(s: {
  symbol: string; strike?: number | null; option_type?: string | null;
  expiry?: string | null; underlying_symbol?: string | null;
}): string {
  const expiry = shortExpiry(s.expiry);
  if (s.strike && s.option_type) {
    const base = s.underlying_symbol || s.symbol;
    return `${base} ${s.strike} ${s.option_type}${expiry ? ` · ${expiry}` : ""}`;
  }
  if (expiry) return `${s.underlying_symbol || s.symbol} FUT · ${expiry}`;
  return s.symbol;
}

const SEGMENT_LABEL: Record<string, string> = {
  BSE_EQ: "BSE", NSE_FNO: "F&O", IDX_I: "INDEX", MCX_COMM: "MCX", NSE_EQ: "NSE",
};

const ASSET_CLASS_LABEL: Record<string, string> = {
  EQUITY: "EQ", ETF: "ETF", INDEX: "INDEX",
  EQUITY_FUTURE: "STK FUT", INDEX_FUTURE: "IDX FUT",
  EQUITY_OPTION: "STK OPT", INDEX_OPTION: "IDX OPT",
  COMMODITY_FUTURE: "MCX FUT", COMMODITY_OPTION: "MCX OPT",
};

export default function ChartPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const trendSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Dynamically managed series, keyed so the sync effect can add/remove exactly
  // what changed rather than tearing down the whole chart on every toggle.
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const subPaneSeriesRef = useRef<ISeriesApi<"Line" | "Histogram">[]>([]);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  // Kept separate from priceLinesRef so indicator reference levels and
  // cross-module position/call levels can be redrawn independently.
  const crossModuleLinesRef = useRef<IPriceLine[]>([]);
  // Exactly one markers plugin per series: a second instance on the same series
  // maintains its own list and the two overwrite each other, so backtest trade
  // markers and drawing notes are merged into this single set instead.
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ChartSymbol[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<ChartSymbol | null>(null);
  const [symbolInfo, setSymbolInfo] = useState<ChartSymbolInfo | null>(null);
  const [resolution, setResolution] = useState<ChartResolution>("D");
  const [showTrend, setShowTrend] = useState(true);
  const [trend, setTrend] = useState<ChartTrend | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [config, setConfig] = useState<IndicatorConfig>(DEFAULT_INDICATORS);
  const [showPanel, setShowPanel] = useState(true);
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [liveEnabled, setLiveEnabled] = useState(true);
  /** Bumped on each completed history fetch; distinguishes "new dataset" from
   * "same dataset, one bar revised by the stream". */
  const [loadSeq, setLoadSeq] = useState(0);

  // --- Phase 5: cross-module overlays --------------------------------------
  const [overlayConfig, setOverlayConfig] = useState<OverlayConfig>(DEFAULT_OVERLAYS);
  const [showOverlayPanel, setShowOverlayPanel] = useState(false);
  const [positions, setPositions] = useState<ChartPositionOverlay[]>([]);
  const [calls, setCalls] = useState<ChartCallOverlay[]>([]);
  const [runs, setRuns] = useState<ChartBacktestRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [trades, setTrades] = useState<ChartBacktestTrade[]>([]);
  const [replay, setReplay] = useState<ReplayState>({ active: false, playing: false, index: 0 });
  const [optionContext, setOptionContext] = useState<ChartOptionContext | null>(null);
  const [optionContextLoading, setOptionContextLoading] = useState(false);
  const [optionContextError, setOptionContextError] = useState<string | null>(null);

  // --- Phase 6: structure + AI explain --------------------------------------
  const [showAnalysisPanel, setShowAnalysisPanel] = useState(false);
  const [showWatchlist, setShowWatchlist] = useState(true);
  const [showStructure, setShowStructure] = useState(false);
  const [structure, setStructure] = useState<ChartStructure | null>(null);
  const [structureLoading, setStructureLoading] = useState(false);
  const [explanation, setExplanation] = useState<ChartExplanation | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);
  const structureSeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const structureLinesRef = useRef<IPriceLine[]>([]);

  // --- Phase 7: workspace ---------------------------------------------------
  const [showWorkspacePanel, setShowWorkspacePanel] = useState(false);
  const [activeTool, setActiveTool] = useState<DrawingTool>(null);
  const [pendingPoint, setPendingPoint] = useState<ChartDrawingPoint | null>(null);
  const [drawColor, setDrawColor] = useState<string>(DRAW_COLORS[0]);
  // Where an in-progress note is being typed: the chart point it pins to, plus the
  // pixel position to float the input over.
  const [noteDraft, setNoteDraft] = useState<{ point: ChartDrawingPoint; x: number; y: number } | null>(null);
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [layouts, setLayouts] = useState<ChartLayout[]>([]);
  const [alerts, setAlerts] = useState<ChartAlert[]>([]);
  const [firedAlerts, setFiredAlerts] = useState<ChartAlert[]>([]);
  const [compareSymbols, setCompareSymbols] = useState<ChartSymbol[]>([]);
  const drawingSeriesRef = useRef<ISeriesApi<"Line" | "Baseline">[]>([]);
  const drawingLinesRef = useRef<IPriceLine[]>([]);
  // Which anchor is being dragged, and the latest drawings — both read from inside
  // long-lived mouse handlers that must not re-subscribe on every mouse move.
  const dragRef = useRef<{ drawingId: string; index: number } | null>(null);
  const drawingsRef = useRef<ChartDrawing[]>([]);
  const [noteMarkers, setNoteMarkers] = useState<SeriesMarker<Time>[]>([]);
  const alertLinesRef = useRef<IPriceLine[]>([]);
  const lastAlertPriceRef = useRef<number | null>(null);

  const intraday = INTRADAY_RESOLUTIONS.includes(resolution);

  // --- derived series (pure, no network) ------------------------------------
  const computed = useMemo(() => {
    const displayBars = config.heikinAshi ? heikinAshi(bars) : bars;
    const overlays: Overlay[] = [];

    if (config.ema.on) {
      config.ema.periods.forEach((p, i) => {
        overlays.push({
          key: `ema-${i}-${p}`, label: `EMA ${p}`, color: EMA_COLORS[i % EMA_COLORS.length],
          data: ema(bars, p), lineWidth: 2, lineStyle: LineStyle.Solid,
        });
      });
    }
    if (config.sma.on) {
      config.sma.periods.forEach((p, i) => {
        overlays.push({
          key: `sma-${i}-${p}`, label: `SMA ${p}`, color: SMA_COLORS[i % SMA_COLORS.length],
          data: sma(bars, p), lineWidth: 2, lineStyle: LineStyle.Solid,
        });
      });
    }
    if (config.vwap.on && intraday) {
      overlays.push({
        key: "vwap", label: "VWAP", color: "#00bcd4",
        data: vwap(bars), lineWidth: 2, lineStyle: LineStyle.Solid,
      });
    }
    if (config.bollinger.on) {
      const b = bollinger(bars, config.bollinger.period, config.bollinger.mult);
      overlays.push({ key: "bb-u", label: `BB ${config.bollinger.period} upper`, color: "#90a4ae", data: b.upper, lineWidth: 1, lineStyle: LineStyle.Solid });
      overlays.push({ key: "bb-m", label: "BB mid", color: "#607d8b", data: b.middle, lineWidth: 1, lineStyle: LineStyle.Dashed });
      overlays.push({ key: "bb-l", label: "BB lower", color: "#90a4ae", data: b.lower, lineWidth: 1, lineStyle: LineStyle.Solid });
    }
    if (config.supertrend.on) {
      const st = supertrend(bars, config.supertrend.period, config.supertrend.mult);
      // Split legs so a flip doesn't draw one line straight across the candles.
      overlays.push({ key: "st-up", label: "Supertrend", color: "#26a69a", data: st.up, lineWidth: 2, lineStyle: LineStyle.Solid });
      overlays.push({ key: "st-dn", label: "Supertrend ↓", color: "#ef5350", data: st.down, lineWidth: 2, lineStyle: LineStyle.Solid });
    }

    const rsiPoints = config.rsi.on ? rsi(bars, config.rsi.period) : [];
    const macdResult = config.macd.on ? macd(bars, config.macd.fast, config.macd.slow, config.macd.signal) : null;
    const levels = referenceLevels(bars, intraday, config.levels.openingRangeMinutes);

    return { displayBars, overlays, rsiPoints, macdResult, levels };
  }, [bars, config, intraday]);

  // --- chart setup (once) ---------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const c: IChartApi = createChart(el, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#787b86" },
      grid: { vertLines: { color: "rgba(120,123,134,0.08)" }, horzLines: { color: "rgba(120,123,134,0.08)" } },
      width: el.clientWidth,
      height: 520,
      timeScale: { timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    const candleSeries = c.addSeries(CandlestickSeries, {
      upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
      wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    const volumeSeries = c.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "vol",
    });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const trendSeries = c.addSeries(LineSeries, {
      color: "#7d34dc", lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false,
    });

    chartRef.current = c;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    trendSeriesRef.current = trendSeries;

    const onResize = () => c.applyOptions({ width: el.clientWidth });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      c.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      trendSeriesRef.current = null;
      overlaySeriesRef.current.clear();
      subPaneSeriesRef.current = [];
      priceLinesRef.current = [];
    };
  }, []);

  // --- search ---------------------------------------------------------------
  useEffect(() => {
    const q = query.trim();
    if (q.length < 1 || selected) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        setResults(await searchChartSymbols(q));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query, selected]);

  const selectSymbol = useCallback(async (s: ChartSymbol) => {
    setSelected(s);
    setResults([]);
    setQuery(`${contractLabel(s)} (${SEGMENT_LABEL[s.exchange_segment] || "NSE"})`);
    try {
      setSymbolInfo(await resolveChartSymbol(s.security_id, s.exchange_segment));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resolve symbol");
    }
  }, []);

  // --- data load ------------------------------------------------------------
  const load = useCallback(async () => {
    if (!selected || !candleSeriesRef.current || !volumeSeriesRef.current) return;
    setLoading(true);
    setError(null);
    try {
      const cfg = RESOLUTIONS.find((r) => r.id === resolution)!;
      const to = Math.floor(Date.now() / 1000);
      const from = to - cfg.lookbackSeconds;
      const raw = await fetchChartHistory(selected.security_id, selected.exchange_segment, resolution, from, to);
      if (raw.s !== "ok" || !raw.t?.length) {
        setBars([]);
        setTrend(null);
        setError("No candle data available for this symbol/timeframe right now.");
        return;
      }
      setBars(
        raw.t.map((time, i) => ({
          time, open: raw.o![i], high: raw.h![i], low: raw.l![i], close: raw.c![i], volume: raw.v![i],
        })),
      );
      setLoadSeq((n) => n + 1);

      if (showTrend) {
        try {
          const t = await fetchChartTrendline(selected.security_id, selected.exchange_segment, resolution);
          setTrend(t.trend);
        } catch {
          setTrend(null);
        }
      } else {
        setTrend(null);
      }
    } catch (e) {
      setBars([]);
      setError(e instanceof Error ? e.message : "Failed to load chart data");
    } finally {
      setLoading(false);
    }
  }, [selected, resolution, showTrend]);

  useEffect(() => {
    load();
  }, [load]);

  // --- live streaming -------------------------------------------------------
  const { status: streamStatus, bar: streamBar, marketOpen } = useChartStream({
    securityId: selected?.security_id ?? null,
    exchangeSegment: selected?.exchange_segment ?? null,
    resolution,
    enabled: liveEnabled && !!selected && bars.length > 0,
    session: symbolInfo?.session,
  });

  // Called from the merge effect below without making it depend on `load`,
  // which would re-run (and re-fetch) on every unrelated change.
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  const mismatchRef = useRef(0);
  const lastResyncRef = useRef(0);
  const [misaligned, setMisaligned] = useState(false);

  useEffect(() => {
    mismatchRef.current = 0;
    setMisaligned(false);
  }, [selected, resolution]);

  useEffect(() => {
    if (!streamBar) return;
    const interval = RESOLUTION_SECONDS[resolution];

    setBars((prev) => {
      if (!prev.length) return prev;
      const last = prev[prev.length - 1];
      const gap = streamBar.time - last.time;

      if (gap === 0) {
        mismatchRef.current = 0;
        const merged: Bar = {
          time: last.time,
          open: last.open,
          high: Math.max(last.high, streamBar.high),
          low: Math.min(last.low, streamBar.low),
          close: streamBar.close,
          volume: Math.max(last.volume, streamBar.volume),
        };
        return [...prev.slice(0, -1), merged];
      }

      // A brand-new bucket: one interval on from the last bar. Anything further
      // out is treated as a grid mismatch rather than trusted, because appending
      // at a wrong timestamp silently corrupts every indicator downstream.
      if (gap > 0 && gap <= interval) {
        mismatchRef.current = 0;
        return [...prev, { ...streamBar }];
      }

      mismatchRef.current += 1;
      return prev;
    });
  }, [streamBar, resolution]);

  // Re-pull history when the stream keeps landing off-grid, so the chart still
  // advances (via the authoritative endpoint) instead of quietly freezing.
  useEffect(() => {
    if (!streamBar || mismatchRef.current < RESYNC_MISMATCHES) return;
    setMisaligned(true);
    const now = Date.now();
    if (now - lastResyncRef.current < RESYNC_COOLDOWN_MS) return;
    lastResyncRef.current = now;
    mismatchRef.current = 0;
    console.warn("[chart stream] update did not land on the history grid — re-pulling history");
    loadRef.current();
  }, [streamBar]);

  // --- candles + volume -----------------------------------------------------
  // Tracks what is currently painted so a live tick can go through the
  // incremental `update()` path instead of re-uploading the whole series (which
  // would also reset the user's zoom on every tick).
  const paintedRef = useRef<{ count: number; lastTime: number; prevTime: number; heikinAshi: boolean } | null>(null);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!candleSeries || !volumeSeries) return;
    const { displayBars } = computed;

    const toCandle = (b: Bar) => ({
      time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close,
    });
    const toVolume = (b: Bar) => ({
      time: b.time as UTCTimestamp,
      value: b.volume,
      color: b.close >= b.open ? "rgba(38,166,154,0.5)" : "rgba(239,83,80,0.5)",
    });

    if (!displayBars.length) {
      candleSeries.setData([]);
      volumeSeries.setData([]);
      paintedRef.current = null;
      return;
    }

    const painted = paintedRef.current;
    const last = displayBars[displayBars.length - 1];
    const grew = displayBars.length - (painted?.count ?? -1);
    // Only the tail can have changed if the series kept its length (last bar
    // revised) or gained exactly one bar whose predecessor is what used to be
    // the last bar. Toggling Heikin-Ashi rewrites every bar, so it always forces
    // a full repaint.
    const incremental =
      painted !== null &&
      painted.heikinAshi === config.heikinAshi &&
      ((grew === 0 && last.time === painted.lastTime) ||
        (grew === 1 && displayBars[displayBars.length - 2].time === painted.lastTime));

    if (incremental) {
      candleSeries.update(toCandle(last));
      volumeSeries.update(toVolume(last));
    } else {
      candleSeries.setData(displayBars.map(toCandle));
      volumeSeries.setData(displayBars.map(toVolume));
    }

    paintedRef.current = {
      count: displayBars.length,
      lastTime: last.time,
      prevTime: displayBars.length > 1 ? displayBars[displayBars.length - 2].time : last.time,
      heikinAshi: config.heikinAshi,
    };
  }, [computed, config.heikinAshi]);

  // Fit the viewport only on a fresh load — not on indicator toggles, and above
  // all not on live ticks, either of which would yank the user's zoom away.
  useEffect(() => {
    if (loadSeq > 0) chartRef.current?.timeScale().fitContent();
  }, [loadSeq]);

  // --- auto trend line ------------------------------------------------------
  useEffect(() => {
    const series = trendSeriesRef.current;
    if (!series) return;
    if (showTrend && trend) {
      series.setData([
        { time: trend.p1.time as UTCTimestamp, value: trend.p1.price },
        { time: trend.p2.time as UTCTimestamp, value: trend.p2.price },
      ]);
    } else {
      series.setData([]);
    }
  }, [trend, showTrend]);

  // --- overlay indicator series --------------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const existing = overlaySeriesRef.current;
    const wanted = new Map(computed.overlays.map((o) => [o.key, o]));

    for (const [key, series] of Array.from(existing.entries())) {
      if (!wanted.has(key)) {
        chart.removeSeries(series);
        existing.delete(key);
      }
    }
    for (const overlay of computed.overlays) {
      let series = existing.get(overlay.key);
      const options = {
        color: overlay.color,
        lineWidth: overlay.lineWidth,
        lineStyle: overlay.lineStyle,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      };
      if (!series) {
        series = chart.addSeries(LineSeries, options, 0);
        existing.set(overlay.key, series);
      } else {
        series.applyOptions(options);
      }
      series.setData(overlay.data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    }
  }, [computed]);

  // --- RSI / MACD sub-panes -------------------------------------------------
  // Pane indices are positional, so when either sub-pane is toggled the whole
  // set is rebuilt rather than trying to renumber live series.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    for (const series of subPaneSeriesRef.current) chart.removeSeries(series);
    subPaneSeriesRef.current = [];

    const { rsiPoints, macdResult } = computed;
    let pane = 1;

    if (config.rsi.on && rsiPoints.length) {
      const rsiSeries = chart.addSeries(
        LineSeries,
        { color: "#7d34dc", lineWidth: 2, priceLineVisible: false, lastValueVisible: true },
        pane,
      );
      rsiSeries.setData(rsiPoints.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      for (const level of [70, 30]) {
        rsiSeries.createPriceLine({
          price: level, color: "rgba(120,123,134,0.4)", lineWidth: 1,
          lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: String(level),
        });
      }
      subPaneSeriesRef.current.push(rsiSeries);
      chart.panes()[pane]?.setHeight(110);
      pane += 1;
    }

    if (config.macd.on && macdResult && macdResult.macd.length) {
      const hist = chart.addSeries(HistogramSeries, { priceFormat: { type: "price" }, priceLineVisible: false }, pane);
      hist.setData(macdResult.histogram.map((p) => ({ time: p.time as UTCTimestamp, value: p.value, color: p.color })));
      const macdLine = chart.addSeries(
        LineSeries,
        { color: "#2196f3", lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
        pane,
      );
      macdLine.setData(macdResult.macd.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      const signalLine = chart.addSeries(
        LineSeries,
        { color: "#ff7043", lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
        pane,
      );
      signalLine.setData(macdResult.signal.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      subPaneSeriesRef.current.push(hist, macdLine, signalLine);
      chart.panes()[pane]?.setHeight(110);
      pane += 1;
    }

    // Drop panes left empty by a toggle-off, highest index first.
    for (let i = chart.panes().length - 1; i >= pane; i--) chart.removePane(i);
  }, [computed, config.rsi.on, config.macd.on]);

  // --- reference level price lines -----------------------------------------
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    for (const line of priceLinesRef.current) series.removePriceLine(line);
    priceLinesRef.current = [];

    const { levels } = computed;
    const add = (price: number | null, title: string, color: string) => {
      if (price === null) return;
      priceLinesRef.current.push(
        series.createPriceLine({
          price, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title,
        }),
      );
    };
    if (config.levels.previousClose) add(levels.previousClose, "PDC", "#9e9e9e");
    if (config.levels.dayRange) {
      add(levels.dayHigh, "DH", "#26a69a");
      add(levels.dayLow, "DL", "#ef5350");
    }
    if (config.levels.openingRange && intraday) {
      add(levels.openingRangeHigh, "ORH", "#f2b705");
      add(levels.openingRangeLow, "ORL", "#f2b705");
    }
  }, [computed, config.levels, intraday]);

  // --- Phase 5: overlay data ------------------------------------------------
  // Mongo-backed, no broker call, so it can refresh freely with the symbol.
  useEffect(() => {
    if (!selected) {
      setPositions([]);
      setCalls([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchChartOverlays(selected.security_id, selected.exchange_segment);
        if (cancelled) return;
        setPositions(data.positions);
        setCalls(data.calls);
      } catch {
        if (!cancelled) {
          setPositions([]);
          setCalls([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  // Backtest runs are listed per underlying symbol, not per contract.
  useEffect(() => {
    setSelectedRunId(null);
    setTrades([]);
    setReplay({ active: false, playing: false, index: 0 });
    if (!selected || !overlayConfig.backtest) {
      setRuns([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchChartBacktests(selected.symbol);
        if (!cancelled) setRuns(data.runs);
      } catch {
        if (!cancelled) setRuns([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, overlayConfig.backtest]);

  useEffect(() => {
    if (!selectedRunId) {
      setTrades([]);
      setReplay({ active: false, playing: false, index: 0 });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchChartBacktestTrades(selectedRunId);
        if (cancelled) return;
        setTrades(data.trades);
        // Start showing everything; the user opts into replay explicitly.
        setReplay({ active: false, playing: false, index: data.trades.length });
      } catch {
        if (!cancelled) setTrades([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  /** Option context is keyed on the underlying, so an index option or future
   * shows its parent index's chain rather than nothing. */
  const optionContextSymbol = useMemo(() => {
    if (!symbolInfo) return null;
    if (symbolInfo.asset_class === "INDEX") return symbolInfo.symbol;
    if (symbolInfo.asset_class === "INDEX_OPTION" || symbolInfo.asset_class === "INDEX_FUTURE") {
      return symbolInfo.underlying_symbol ?? null;
    }
    return null;
  }, [symbolInfo]);

  useEffect(() => {
    if (!overlayConfig.optionContext || !optionContextSymbol) {
      setOptionContext(null);
      setOptionContextError(null);
      return;
    }
    let cancelled = false;
    setOptionContextLoading(true);
    setOptionContextError(null);
    (async () => {
      try {
        const data = await fetchChartOptionContext(optionContextSymbol);
        if (!cancelled) setOptionContext(data);
      } catch (e) {
        if (!cancelled) setOptionContextError(e instanceof Error ? e.message : "Could not load option context");
      } finally {
        if (!cancelled) setOptionContextLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [overlayConfig.optionContext, optionContextSymbol]);

  // --- Phase 5: position & call price lines --------------------------------
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    for (const line of crossModuleLinesRef.current) series.removePriceLine(line);
    crossModuleLinesRef.current = [];

    const add = (price: number | null | undefined, title: string, color: string, style: LineStyle) => {
      if (price === null || price === undefined || Number.isNaN(price)) return;
      crossModuleLinesRef.current.push(
        series.createPriceLine({ price, color, lineWidth: 2, lineStyle: style, axisLabelVisible: true, title }),
      );
    };

    if (overlayConfig.positions) {
      for (const p of positions) {
        // Entry only — this app's positions carry no stop-loss or target field,
        // and drawing invented levels would be worse than drawing none.
        add(p.entry_price, `${p.side === "BUY" ? "LONG" : "SHORT"} ${p.quantity}`, "#7d34dc", LineStyle.Solid);
      }
    }
    if (overlayConfig.calls) {
      for (const c of calls) {
        add(c.entry_price, `CALL ${c.side} entry`, "#2196f3", LineStyle.Solid);
        add(c.target, "CALL target", "#26a69a", LineStyle.Dashed);
        add(c.stoploss, "CALL SL", "#ef5350", LineStyle.Dashed);
      }
    }
  }, [positions, calls, overlayConfig.positions, overlayConfig.calls, loadSeq]);

  // --- Phase 5: backtest trade markers + replay ----------------------------
  const visibleTrades = useMemo(
    () => (replay.active ? trades.slice(0, replay.index) : trades),
    [trades, replay.active, replay.index],
  );

  const tradeMarkers = useMemo((): SeriesMarker<Time>[] => {
    if (!overlayConfig.backtest || !visibleTrades.length || !bars.length) return [];

    // Trade timestamps come from the backtester's own bar series; snap each to
    // the nearest loaded candle so a marker can't be dropped for landing
    // between bars of a different resolution.
    const barTimes = bars.map((b) => b.time);
    const snap = (iso: string): number | null => {
      const target = Math.floor(new Date(iso).getTime() / 1000);
      if (Number.isNaN(target)) return null;
      let lo = 0;
      let hi = barTimes.length - 1;
      let best: number | null = null;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (barTimes[mid] <= target) {
          best = barTimes[mid];
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      return best;
    };

    const markers: SeriesMarker<Time>[] = [];
    for (const trade of visibleTrades) {
      const long = trade.direction === "BUY";
      const entryTime = snap(trade.entry_ts);
      if (entryTime !== null) {
        markers.push({
          time: entryTime as UTCTimestamp,
          position: long ? "belowBar" : "aboveBar",
          shape: long ? "arrowUp" : "arrowDown",
          color: long ? "#26a69a" : "#ef5350",
          text: `${long ? "BUY" : "SELL"} ${trade.entry_price.toFixed(1)}`,
        });
      }
      if (trade.exit_ts && trade.exit_price !== null) {
        const exitTime = snap(trade.exit_ts);
        if (exitTime !== null) {
          const won = (trade.pnl ?? 0) >= 0;
          markers.push({
            time: exitTime as UTCTimestamp,
            position: long ? "aboveBar" : "belowBar",
            shape: long ? "arrowDown" : "arrowUp",
            color: won ? "#26a69a" : "#ef5350",
            text: `exit ${trade.exit_price.toFixed(1)}${trade.pnl === null ? "" : ` (${trade.pnl >= 0 ? "+" : ""}${trade.pnl.toFixed(0)})`}`,
          });
        }
      }
    }
    return markers;
  }, [visibleTrades, overlayConfig.backtest, bars]);

  // Replay transport: advance one trade at a time and keep it in view.
  useEffect(() => {
    if (!replay.active || !replay.playing) return;
    if (replay.index >= trades.length) {
      setReplay((r) => ({ ...r, playing: false }));
      return;
    }
    const timer = setTimeout(() => setReplay((r) => ({ ...r, index: Math.min(r.index + 1, trades.length) })), 1200);
    return () => clearTimeout(timer);
  }, [replay.active, replay.playing, replay.index, trades.length]);

  useEffect(() => {
    if (!replay.active || replay.index === 0 || !trades.length) return;
    const trade = trades[Math.min(replay.index, trades.length) - 1];
    if (!trade) return;
    const at = Math.floor(new Date(trade.entry_ts).getTime() / 1000);
    if (Number.isNaN(at)) return;
    const span = RESOLUTION_SECONDS[resolution] * 40;
    chartRef.current?.timeScale().setVisibleRange({
      from: (at - span) as UTCTimestamp,
      to: (at + span) as UTCTimestamp,
    });
  }, [replay.active, replay.index, trades, resolution]);

  // --- Phase 6: structure fetch + drawing -----------------------------------
  useEffect(() => {
    if (!selected || !showStructure) {
      setStructure(null);
      return;
    }
    let cancelled = false;
    setStructureLoading(true);
    (async () => {
      try {
        const data = await fetchChartStructure(selected.security_id, selected.exchange_segment, resolution);
        if (!cancelled) setStructure(data);
      } catch {
        if (!cancelled) setStructure({ available: false, reason: "Could not analyse this chart." });
      } finally {
        if (!cancelled) setStructureLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, resolution, showStructure]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    if (!chart || !series) return;

    for (const s of structureSeriesRef.current) chart.removeSeries(s);
    structureSeriesRef.current = [];
    for (const line of structureLinesRef.current) series.removePriceLine(line);
    structureLinesRef.current = [];

    if (!showStructure || !structure?.available) return;

    // Zones as price lines, labelled with their touch count — the whole point
    // of the upgrade over the old single swing line.
    const addZone = (zone: { price: number; touches: number }, kind: "support" | "resistance") => {
      structureLinesRef.current.push(
        series.createPriceLine({
          price: zone.price,
          color: kind === "support" ? "rgba(38,166,154,0.7)" : "rgba(239,83,80,0.7)",
          lineWidth: zone.touches >= 3 ? 2 : 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: `${kind === "support" ? "S" : "R"}×${zone.touches}`,
        }),
      );
    };
    for (const z of structure.support_zones || []) addZone(z, "support");
    for (const z of structure.resistance_zones || []) addZone(z, "resistance");

    for (const [key, line] of [
      ["upper", structure.channel?.upper],
      ["lower", structure.channel?.lower],
    ] as const) {
      if (!line) continue;
      const s = chart.addSeries(
        LineSeries,
        {
          color: key === "upper" ? "rgba(239,83,80,0.55)" : "rgba(38,166,154,0.55)",
          lineWidth: 1, lineStyle: LineStyle.LargeDashed,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        },
        0,
      );
      s.setData([
        { time: line.p1.time as UTCTimestamp, value: line.p1.price },
        { time: line.p2.time as UTCTimestamp, value: line.p2.price },
      ]);
      structureSeriesRef.current.push(s);
    }
  }, [structure, showStructure, loadSeq]);

  /** Digest of what's actually on screen. Summarised deliberately — the model
   * gets the shape of the window and the live indicator values, not a 2000-bar
   * dump that would be mostly tokens. */
  const buildExplainContext = useCallback(() => {
    const source = computed.displayBars;
    const window = source.slice(-120);
    const closes = window.map((b) => b.close);
    const last = window[window.length - 1];
    const first = window[0];
    const activeIndicators: Record<string, number | null> = {};
    for (const overlay of computed.overlays) {
      if (overlay.key === "st-dn") continue;
      activeIndicators[overlay.label] = valueAt(overlay.data, last.time);
    }
    if (config.rsi.on) activeIndicators[`RSI ${config.rsi.period}`] = valueAt(computed.rsiPoints, last.time);
    if (config.macd.on && computed.macdResult) {
      activeIndicators.MACD = valueAt(computed.macdResult.macd, last.time);
      activeIndicators["MACD signal"] = valueAt(computed.macdResult.signal, last.time);
    }

    return {
      instrument: {
        symbol: symbolInfo?.symbol ?? selected?.symbol,
        name: symbolInfo?.name,
        asset_class: symbolInfo?.asset_class,
        expiry: symbolInfo?.expiry ?? null,
        strike: symbolInfo?.strike ?? null,
        option_type: symbolInfo?.option_type ?? null,
      },
      resolution,
      rendering: config.heikinAshi ? "heikin-ashi" : "candles",
      window: {
        bars: window.length,
        from: new Date(first.time * 1000).toISOString(),
        to: new Date(last.time * 1000).toISOString(),
        open: first.open,
        close: last.close,
        high: Math.max(...window.map((b) => b.high)),
        low: Math.min(...window.map((b) => b.low)),
        change_pct: first.open ? ((last.close - first.open) / first.open) * 100 : null,
        mean_close: closes.reduce((a, b) => a + b, 0) / closes.length,
        last_volume: last.volume,
      },
      reference_levels: computed.levels,
      active_indicators: activeIndicators,
      structure: structure?.available ? structure : null,
      open_positions: overlayConfig.positions ? positions : [],
      active_calls: overlayConfig.calls ? calls : [],
    };
  }, [computed, config, resolution, symbolInfo, selected, structure, overlayConfig, positions, calls]);

  const runExplain = useCallback(async () => {
    if (!computed.displayBars.length) return;
    setExplaining(true);
    setExplainError(null);
    setExplanation(null);
    try {
      setExplanation(await explainChart(buildExplainContext()));
    } catch (e) {
      setExplainError(e instanceof Error ? e.message : "The AI service could not be reached.");
    } finally {
      setExplaining(false);
    }
  }, [buildExplainContext, computed.displayBars.length]);

  // A read of one window says nothing about another.
  useEffect(() => {
    setExplanation(null);
    setExplainError(null);
  }, [selected, resolution]);

  // --- Phase 7: load workspace for the selected instrument ------------------
  useEffect(() => {
    if (!selected) {
      setDrawings([]);
      setAlerts([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [d, a] = await Promise.all([
          fetchChartDrawings(selected.security_id, selected.exchange_segment),
          fetchChartAlerts(selected.security_id),
        ]);
        if (cancelled) return;
        setDrawings(d.drawings);
        setAlerts(a.alerts);
      } catch {
        if (!cancelled) {
          setDrawings([]);
          setAlerts([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchChartLayouts();
        if (!cancelled) setLayouts(data.layouts);
      } catch {
        if (!cancelled) setLayouts([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Switching tool or symbol abandons a half-finished shape.
  useEffect(() => {
    setPendingPoint(null);
  }, [activeTool, selected]);

  useEffect(() => {
    drawingsRef.current = drawings;
  }, [drawings]);

  // --- Phase 2: drag an existing drawing by its anchors ---------------------
  // Armed only when no tool is selected: with a tool active a click is placing a
  // new shape, and that path must keep working untouched.
  useEffect(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    const host = containerRef.current;
    if (!chart || !series || !host || activeTool) return;
    const timeScale = chart.timeScale();

    const anchorAt = (x: number, y: number) => {
      for (const d of drawingsRef.current) {
        for (let i = 0; i < d.points.length; i++) {
          const py = series.priceToCoordinate(d.points[i].price);
          if (py === null) continue;
          // A horizontal ray and a position box's levels each span a width rather
          // than sitting at one point, so only price needs to be close to grab them.
          if (d.kind === "horizontal" || d.kind === "long_position" || d.kind === "short_position") {
            if (Math.abs(py - y) <= GRAB_RADIUS) return { drawingId: d.drawing_id, index: i };
            continue;
          }
          const px = timeScale.timeToCoordinate(d.points[i].time as UTCTimestamp);
          if (px === null) continue;
          if (Math.hypot(px - x, py - y) <= GRAB_RADIUS) return { drawingId: d.drawing_id, index: i };
        }
      }
      return null;
    };

    const localPoint = (e: MouseEvent) => {
      const rect = host.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const onMove = (e: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag && !host.contains(e.target as Node)) return;
      const { x, y } = localPoint(e);
      if (!drag) {
        host.style.cursor = anchorAt(x, y) ? "grab" : "";
        return;
      }
      const price = series.coordinateToPrice(y);
      if (price === null) return;
      const time = timeScale.coordinateToTime(x);
      setDrawings((prev) =>
        prev.map((d) =>
          d.drawing_id !== drag.drawingId
            ? d
            : {
                ...d,
                points: d.points.map((p, i) =>
                  i !== drag.index
                    ? p
                    : {
                        // A horizontal ray has no meaningful time to slide along, and
                        // a position box's width is fixed — dragging its handles
                        // adjusts entry/target/stop price, not the box's extent.
                        time:
                          d.kind === "horizontal" || d.kind === "long_position" || d.kind === "short_position" || time === null
                            ? p.time
                            : (time as number),
                        price: Number(price),
                      },
                ),
              },
        ),
      );
    };

    const onDown = (e: MouseEvent) => {
      const { x, y } = localPoint(e);
      const hit = anchorAt(x, y);
      if (!hit) return;
      dragRef.current = hit;
      host.style.cursor = "grabbing";
      // Freeze pan/zoom, otherwise the chart slides under the anchor being moved.
      chart.applyOptions({ handleScroll: false, handleScale: false });
      e.stopPropagation();
      e.preventDefault();
    };

    const onUp = () => {
      const drag = dragRef.current;
      if (!drag) return;
      dragRef.current = null;
      host.style.cursor = "";
      chart.applyOptions({ handleScroll: true, handleScale: true });
      const moved = drawingsRef.current.find((d) => d.drawing_id === drag.drawingId);
      if (!moved) return;
      updateChartDrawing(drag.drawingId, { points: moved.points }).catch((err) =>
        setError(err instanceof Error ? err.message : "Could not save that edit"),
      );
    };

    host.addEventListener("mousedown", onDown, true);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      host.removeEventListener("mousedown", onDown, true);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      host.style.cursor = "";
    };
  }, [activeTool, selected, loadSeq]);

  // --- Phase 7: capture clicks into drawings --------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    if (!chart || !series || !activeTool || !selected) return;

    const handler = (param: { time?: unknown; point?: { x: number; y: number } }) => {
      if (typeof param.time !== "number" || !param.point) return;
      const price = series.coordinateToPrice(param.point.y);
      if (price === null) return;
      const point: ChartDrawingPoint = { time: param.time, price: Number(price) };

      const persist = async (points: ChartDrawingPoint[], text?: string) => {
        try {
          const saved = await saveChartDrawing(selected.security_id, selected.exchange_segment, {
            kind: activeTool, points, color: drawColor, ...(text ? { text } : {}),
          });
          setDrawings((prev) => [...prev, saved]);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Could not save that drawing");
        }
      };

      // One-click shapes finish immediately; two-click shapes bank the first
      // point and complete on the next click.
      if (activeTool === "horizontal") {
        persist([point]);
        setActiveTool(null);
        return;
      }
      if (activeTool === "long_position" || activeTool === "short_position") {
        // One click marks entry; target and stop default to a 1:2 risk:reward on
        // the correct side for the direction, adjustable afterward by dragging
        // either handle — nobody wants to place three points for a starting guess.
        const risk = point.price * POSITION_DEFAULT_RISK_PCT;
        const long = activeTool === "long_position";
        const target = point.price + (long ? 1 : -1) * risk * POSITION_DEFAULT_REWARD_MULTIPLE;
        const stop = point.price - (long ? 1 : -1) * risk;
        persist([point, { time: point.time, price: target }, { time: point.time, price: stop }]);
        setActiveTool(null);
        return;
      }
      if (activeTool === "text") {
        // Hand off to an inline input anchored at the click; it persists on commit.
        setNoteDraft({ point, x: param.point.x, y: param.point.y });
        setActiveTool(null);
        return;
      }
      if (!pendingPoint) {
        setPendingPoint(point);
        return;
      }
      persist([pendingPoint, point]);
      setPendingPoint(null);
      setActiveTool(null);
    };

    chart.subscribeClick(handler);
    return () => chart.unsubscribeClick(handler);
  }, [activeTool, pendingPoint, selected, drawColor]);

  // Commits the note being typed. Empty text simply abandons it, so a stray click
  // with the note tool doesn't litter the chart with blank markers.
  const commitNote = useCallback(
    async (text: string) => {
      const draft = noteDraft;
      setNoteDraft(null);
      if (!draft || !selected || !text.trim()) return;
      try {
        const saved = await saveChartDrawing(selected.security_id, selected.exchange_segment, {
          kind: "text", points: [draft.point], text: text.trim(), color: drawColor,
        });
        setDrawings((prev) => [...prev, saved]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not save that note");
      }
    },
    [noteDraft, selected, drawColor],
  );

  // A note pinned to a symbol makes no sense once the chart moves on.
  useEffect(() => {
    setNoteDraft(null);
  }, [selected]);

  // --- Phase 7: render drawings --------------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    if (!chart || !series) return;

    for (const s of drawingSeriesRef.current) chart.removeSeries(s);
    drawingSeriesRef.current = [];
    for (const line of drawingLinesRef.current) series.removePriceLine(line);
    drawingLinesRef.current = [];

    const notes: SeriesMarker<Time>[] = [];

    for (const drawing of drawings) {
      const color = drawing.color || "#f2b705";
      if (drawing.kind === "horizontal" && drawing.points[0]) {
        drawingLinesRef.current.push(
          series.createPriceLine({
            price: drawing.points[0].price, color, lineWidth: 1,
            lineStyle: LineStyle.Solid, axisLabelVisible: true, title: drawing.text || "",
          }),
        );
      } else if (drawing.kind === "text" && drawing.points[0]) {
        notes.push({
          time: drawing.points[0].time as UTCTimestamp,
          position: "aboveBar", shape: "circle", color,
          text: drawing.text || "note",
        });
      } else if (drawing.kind === "fibonacci" && drawing.points.length >= 2) {
        // Levels run from the first click (0%) to the second (100%), so clicking a
        // swing low then its high gives the familiar retracement ladder. Drawn as
        // price lines rather than segments bounded by the swing: a retracement is
        // read as forward support/resistance, not only inside the move that made it.
        const [from, to] = drawing.points;
        const span = to.price - from.price;
        for (const level of FIB_LEVELS) {
          const anchor = level === 0 || level === 1;
          drawingLinesRef.current.push(
            series.createPriceLine({
              price: from.price + span * level,
              color,
              lineWidth: 1,
              lineStyle: anchor ? LineStyle.Solid : LineStyle.Dashed,
              axisLabelVisible: true,
              title: `fib ${(level * 100).toFixed(1).replace(/\.0$/, "")}%`,
            }),
          );
        }
      } else if (drawing.kind === "rectangle" && drawing.points.length >= 2) {
        // lightweight-charts has no box primitive, but a baseline series fills
        // between its line and a baseline price — anchor the line to the zone's top
        // and the baseline to its bottom and the fill *is* the rectangle.
        const [a, b] = drawing.points;
        const top = Math.max(a.price, b.price);
        const bottom = Math.min(a.price, b.price);
        const [t0, t1] = a.time <= b.time ? [a.time, b.time] : [b.time, a.time];
        const zone = chart.addSeries(
          BaselineSeries,
          {
            baseValue: { type: "price", price: bottom },
            topLineColor: color,
            topFillColor1: withAlpha(color, 0.18),
            topFillColor2: withAlpha(color, 0.18),
            bottomLineColor: "transparent",
            bottomFillColor1: "transparent",
            bottomFillColor2: "transparent",
            lineWidth: 2,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          },
          0,
        );
        zone.setData([
          { time: t0 as UTCTimestamp, value: top },
          { time: t1 as UTCTimestamp, value: top },
        ]);
        drawingSeriesRef.current.push(zone);
        // The baseline itself isn't stroked, so the lower edge gets its own line.
        const floor = chart.addSeries(
          LineSeries,
          {
            color, lineWidth: 2, lineStyle: LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          },
          0,
        );
        floor.setData([
          { time: t0 as UTCTimestamp, value: bottom },
          { time: t1 as UTCTimestamp, value: bottom },
        ]);
        drawingSeriesRef.current.push(floor);
      } else if (
        (drawing.kind === "long_position" || drawing.kind === "short_position") &&
        drawing.points.length >= 3
      ) {
        // Entry, target and stop are stored at the same time — the box's width is
        // a fixed number of bars rather than something dragged, so every level's
        // own time is redundant and only its price matters (see the drag handler
        // and hit-test above, both of which already treat these points that way).
        const [entryPt, targetPt, stopPt] = drawing.points;
        const t0 = entryPt.time as UTCTimestamp;
        const t1 = (entryPt.time + RESOLUTION_SECONDS[resolution] * POSITION_WIDTH_BARS) as UTCTimestamp;
        const span = [
          { time: t0, value: 0 },
          { time: t1, value: 0 },
        ];
        // Profit and loss are always green/above and red/below in meaning, however
        // the box happens to be oriented — a baseline series fills whichever side
        // of its base the value falls on, so painting both sides the same colour
        // means the fill is correct for a long AND a short without branching.
        const zone = (basePrice: number, valuePrice: number, hue: string) =>
          chart.addSeries(
            BaselineSeries,
            {
              baseValue: { type: "price", price: basePrice },
              topLineColor: hue, bottomLineColor: hue,
              topFillColor1: withAlpha(hue, 0.16), topFillColor2: withAlpha(hue, 0.16),
              bottomFillColor1: withAlpha(hue, 0.16), bottomFillColor2: withAlpha(hue, 0.16),
              lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
            },
            0,
          );
        const profit = zone(entryPt.price, targetPt.price, "#0e9f6e");
        profit.setData(span.map((p) => ({ time: p.time, value: targetPt.price })));
        const loss = zone(entryPt.price, stopPt.price, "#d92d3f");
        loss.setData(span.map((p) => ({ time: p.time, value: stopPt.price })));
        drawingSeriesRef.current.push(profit, loss);

        const reward = Math.abs(targetPt.price - entryPt.price);
        const risk = Math.abs(entryPt.price - stopPt.price);
        const rr = risk > 0 ? (reward / risk).toFixed(1) : "—";
        const pct = (p: number) => `${p >= 0 ? "+" : ""}${((p / entryPt.price) * 100).toFixed(2)}%`;

        drawingLinesRef.current.push(
          series.createPriceLine({
            price: entryPt.price, color: "#f2b705", lineWidth: 2, lineStyle: LineStyle.Solid,
            axisLabelVisible: true, title: `Entry ${entryPt.price.toFixed(2)}`,
          }),
          series.createPriceLine({
            price: targetPt.price, color: "#0e9f6e", lineWidth: 1, lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `Target ${targetPt.price.toFixed(2)} (${pct(targetPt.price - entryPt.price)}) R:R 1:${rr}`,
          }),
          series.createPriceLine({
            price: stopPt.price, color: "#d92d3f", lineWidth: 1, lineStyle: LineStyle.Dashed,
            axisLabelVisible: true, title: `Stop ${stopPt.price.toFixed(2)} (${pct(stopPt.price - entryPt.price)})`,
          }),
        );
      } else if (drawing.points.length >= 2) {
        const line = chart.addSeries(
          LineSeries,
          {
            color, lineWidth: 2, lineStyle: LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          },
          0,
        );
        // Series data must run left to right; the anchors are in click order.
        const ordered = [drawing.points[0], drawing.points[1]].sort((p, q) => p.time - q.time);
        line.setData(ordered.map((p) => ({ time: p.time as UTCTimestamp, value: p.price })));
        drawingSeriesRef.current.push(line);
      }
    }
    setNoteMarkers(notes);
  }, [drawings, loadSeq, resolution]);

  // Single owner of the markers plugin: trade markers and drawing notes share
  // one series, so they are merged and written together.
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    if (!markersRef.current) markersRef.current = createSeriesMarkers(series, []);
    // Markers must be time-ordered or lightweight-charts drops the tail.
    const merged = [...tradeMarkers, ...noteMarkers].sort(
      (a, b) => (a.time as number) - (b.time as number),
    );
    markersRef.current.setMarkers(merged);
  }, [tradeMarkers, noteMarkers]);

  // --- Phase 7: alert lines + live evaluation -------------------------------
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    for (const line of alertLinesRef.current) series.removePriceLine(line);
    alertLinesRef.current = [];
    for (const alert of alerts) {
      if (alert.status !== "ACTIVE") continue;
      alertLinesRef.current.push(
        series.createPriceLine({
          price: alert.price,
          color: "#ffa726",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: alert.condition === "crosses_above" ? "⤴ alert" : "⤵ alert",
        }),
      );
    }
  }, [alerts, loadSeq]);

  useEffect(() => {
    if (!selected) {
      lastAlertPriceRef.current = null;
      return;
    }
    const price = streamBar?.close ?? null;
    if (price === null) return;
    const previous = lastAlertPriceRef.current;
    lastAlertPriceRef.current = price;
    // A cross needs both sides of the move — the first observed tick can't
    // establish one, so it only seeds the reference price.
    if (previous === null || previous === price) return;
    if (!alerts.some((a) => a.status === "ACTIVE")) return;

    (async () => {
      try {
        const result = await evaluateChartAlerts({
          security_id: selected.security_id,
          exchange_segment: selected.exchange_segment,
          last_price: price,
          previous_price: previous,
        });
        if (result.triggered.length) {
          setFiredAlerts((prev) => [...result.triggered, ...prev].slice(0, 5));
          setAlerts((prev) =>
            prev.map((a) => result.triggered.find((t) => t.alert_id === a.alert_id) ?? a),
          );
        }
      } catch {
        // A failed evaluation must not disturb the chart; the next tick retries.
      }
    })();
  }, [streamBar, selected, alerts]);

  // --- Phase 7: layout save/apply -------------------------------------------
  const handleSaveLayout = useCallback(
    async (name: string) => {
      try {
        const saved = await saveChartLayout({
          name, resolution, indicators: config, overlays: overlayConfig,
        });
        setLayouts((prev) => [saved, ...prev.filter((l) => l.layout_id !== saved.layout_id)]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not save that layout");
      }
    },
    [resolution, config, overlayConfig],
  );

  const handleApplyLayout = useCallback((layout: ChartLayout) => {
    if (layout.resolution) setResolution(layout.resolution);
    // Stored layouts are opaque JSON, hence the cast. Merging over the current
    // defaults means a layout saved before a newer indicator existed still
    // applies cleanly rather than leaving that indicator undefined.
    if (layout.indicators && Object.keys(layout.indicators).length) {
      setConfig({ ...DEFAULT_INDICATORS, ...(layout.indicators as unknown as IndicatorConfig) });
    }
    if (layout.overlays && Object.keys(layout.overlays).length) {
      setOverlayConfig({ ...DEFAULT_OVERLAYS, ...(layout.overlays as unknown as OverlayConfig) });
    }
  }, []);

  const handleCreateAlert = useCallback(
    async (condition: "crosses_above" | "crosses_below", price: number, note: string) => {
      if (!selected) return;
      try {
        const created = await createChartAlert({
          security_id: selected.security_id,
          exchange_segment: selected.exchange_segment,
          symbol: selected.symbol,
          display_name: symbolInfo?.name ?? selected.symbol,
          condition,
          price,
          ...(note ? { note } : {}),
        });
        setAlerts((prev) => [created, ...prev]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not create that alert");
      }
    },
    [selected, symbolInfo],
  );

  // --- log scale ------------------------------------------------------------
  useEffect(() => {
    chartRef.current?.priceScale("right").applyOptions({
      mode: config.logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
  }, [config.logScale]);

  // --- crosshair HUD --------------------------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const handler = (param: { time?: unknown }) => {
      setHoverTime(typeof param.time === "number" ? param.time : null);
    };
    chart.subscribeCrosshairMove(handler);
    return () => chart.unsubscribeCrosshairMove(handler);
  }, []);

  // The bar under the crosshair, falling back to the latest bar when the mouse
  // is off the chart — so the legend always shows something useful.
  const hudBar = useMemo(() => {
    const source = computed.displayBars;
    if (!source.length) return null;
    if (hoverTime === null) return source[source.length - 1];
    let found = source[source.length - 1];
    for (const b of source) {
      if (b.time > hoverTime) break;
      found = b;
    }
    return found;
  }, [computed.displayBars, hoverTime]);

  const hudRows: HudRow[] = useMemo(() => {
    if (!hudBar) return [];
    const rows: HudRow[] = computed.overlays
      .filter((o) => o.key !== "st-dn") // both Supertrend legs share one legend row
      .map((o) => ({
        label: o.label,
        color: o.color,
        value: valueAt(o.data, hudBar.time),
      }));
    if (config.rsi.on) {
      rows.push({ label: `RSI ${config.rsi.period}`, color: "#7d34dc", value: valueAt(computed.rsiPoints, hudBar.time) });
    }
    if (config.macd.on && computed.macdResult) {
      rows.push({ label: "MACD", color: "#2196f3", value: valueAt(computed.macdResult.macd, hudBar.time) });
      rows.push({ label: "Signal", color: "#ff7043", value: valueAt(computed.macdResult.signal, hudBar.time) });
    }
    return rows;
  }, [computed, hudBar, config.rsi.on, config.rsi.period, config.macd.on]);

  /** Reflects real connection health, not just "streaming was switched on" —
   * a pill that says LIVE while the feed is dead is worse than no pill. */
  const sessionLabel = (symbolInfo?.session ?? "0915-1530").replace(
    /^(\d{2})(\d{2})-(\d{2})(\d{2})$/,
    "$1:$2–$3:$4",
  );

  const livePill = useMemo((): { label: string; tone: string; title: string } | null => {
    if (!selected) return null;
    if (!liveEnabled) return { label: "Live off", tone: "muted", title: "Live updates are switched off" };
    const closed = !marketOpen;
    switch (streamStatus as StreamStatus) {
      case "unsupported":
        return { label: "No live feed", tone: "muted", title: "Weekly candles have no live feed" };
      case "connecting":
        return { label: "Connecting…", tone: "muted", title: "Opening the live feed" };
      case "reconnecting":
        return { label: "Reconnecting…", tone: "warn", title: "Connection dropped — retrying" };
      case "stale":
        return closed
          ? { label: "Market closed", tone: "muted", title: `Outside this instrument's session (${sessionLabel} IST) — no ticks expected` }
          : { label: "Stale", tone: "warn", title: "Connected, but no update has arrived recently" };
      case "live":
        if (misaligned) {
          return { label: "LIVE · resyncing", tone: "warn", title: "Live bars aren't aligning with history; refreshing from the server instead" };
        }
        return closed
          ? { label: "Connected · market closed", tone: "muted", title: "Feed is up; the session is closed" }
          : { label: "LIVE", tone: "ok", title: "Streaming live bar updates" };
      default:
        return null;
    }
  }, [selected, liveEnabled, streamStatus, marketOpen, misaligned, sessionLabel]);

  const lastBar = computed.displayBars.length ? computed.displayBars[computed.displayBars.length - 1] : null;
  const hudDate = hudBar
    ? new Date(hudBar.time * 1000).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit", month: "short", year: "numeric",
        ...(intraday ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
      })
    : "";

  return (
    <div className="page">
      <PageHeader
        crumb="Chart"
        title="Chart"
        subtitle="Real candlestick charts from live Dhan OHLCV data — search any NSE/BSE stock, index, or F&O future. Built with lightweight-charts (TradingView's free, open-source charting library). Not investment advice."
      />

      <GlassPanel>
        <div className="toolbar">
          <div className="search-wrap">
            <input
              placeholder="Search stock, index, future, option or MCX contract (e.g. NIFTY, RELIANCE, CRUDEOIL)"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSelected(null);
              }}
            />
            {!selected && query.trim().length >= 1 && (
              <div className="dropdown">
                {results.length > 0 ? (
                  results.map((r) => (
                    <button key={`${r.exchange_segment}-${r.security_id}`} className="dropdown-item" onClick={() => selectSymbol(r)}>
                      <span className="dsym">{contractLabel(r)}</span>
                      <span className="dname">{r.name}</span>
                      <span className="dseg">{ASSET_CLASS_LABEL[r.asset_class] || r.asset_class}</span>
                    </button>
                  ))
                ) : (
                  <div className="dropdown-empty">{searching ? "Searching…" : "No matching symbols"}</div>
                )}
              </div>
            )}
          </div>

          <div className="res-row">
            {RESOLUTIONS.map((r) => (
              <button key={r.id} className={resolution === r.id ? "res-btn active" : "res-btn"} onClick={() => setResolution(r.id)}>
                {r.label}
              </button>
            ))}
            <button className={showTrend ? "trend-btn active" : "trend-btn"} onClick={() => setShowTrend((v) => !v)}>
              Auto trend line
            </button>
            <button className={showPanel ? "trend-btn active" : "trend-btn"} onClick={() => setShowPanel((v) => !v)}>
              Indicators
            </button>
            <button className={showOverlayPanel ? "trend-btn active" : "trend-btn"} onClick={() => setShowOverlayPanel((v) => !v)}>
              My data
            </button>
            <button className={showAnalysisPanel ? "trend-btn active" : "trend-btn"} onClick={() => setShowAnalysisPanel((v) => !v)}>
              Analysis
            </button>
            <button className={showWatchlist ? "trend-btn active" : "trend-btn"} onClick={() => setShowWatchlist((v) => !v)}>
              Watchlist
            </button>
            <button className={showWorkspacePanel ? "trend-btn active" : "trend-btn"} onClick={() => setShowWorkspacePanel((v) => !v)}>
              Workspace
            </button>
            <button className={liveEnabled ? "trend-btn active" : "trend-btn"} onClick={() => setLiveEnabled((v) => !v)}>
              {liveEnabled ? "Live on" : "Live off"}
            </button>
          </div>
        </div>

        {selected && symbolInfo && (
          <div className="symbol-line">
            <span className="sym-name">{contractLabel(symbolInfo)}</span>
            <span className="sym-tag">{ASSET_CLASS_LABEL[symbolInfo.asset_class] || symbolInfo.asset_class}</span>
            {symbolInfo.lot_size && symbolInfo.lot_size > 1 && (
              <span className="sym-tag">Lot {symbolInfo.lot_size}</span>
            )}
            {lastBar && (
              <span className={`sym-price ${lastBar.close >= lastBar.open ? "gain" : "loss"}`}>
                {lastBar.close.toFixed(2)}
              </span>
            )}
            {config.heikinAshi && <span className="sym-tag">Heikin-Ashi</span>}
            {livePill && (
              <span className={`live-pill ${livePill.tone}`} title={livePill.title}>
                <i className="dot" />
                {livePill.label}
              </span>
            )}
            {trend && <span className={`trend-tag ${trend.kind}`}>{trend.kind === "support" ? "▲ Uptrend line" : "▼ Downtrend line"}</span>}
          </div>
        )}

        {error && <ErrorBanner message={error} />}

        {firedAlerts.length > 0 && (
          <div className="alert-toasts">
            {firedAlerts.map((a) => (
              <div key={a.alert_id} className="alert-toast">
                <span className="bell">🔔</span>
                <span>
                  <b>{a.display_name || a.symbol}</b> crossed {a.condition === "crosses_above" ? "above" : "below"}{" "}
                  <b>{a.price}</b>
                  {a.triggered_price !== null && <> — now {a.triggered_price}</>}
                  {a.note && <span className="tnote"> · {a.note}</span>}
                </span>
                <button onClick={() => setFiredAlerts((prev) => prev.filter((x) => x.alert_id !== a.alert_id))}>×</button>
              </div>
            ))}
          </div>
        )}

        <div className="chart-row">
          <div className="chart-wrap">
            {!selected && <div className="empty">Search for a symbol above to load its chart.</div>}
            {loading && <div className="loading-overlay">Loading…</div>}
            {selected && hudBar && (
              <div className="hud">
                <div className="hud-head">
                  <span className="hud-date">{hudDate}</span>
                </div>
                <div className="hud-ohlc">
                  <span>O <b>{fmt(hudBar.open)}</b></span>
                  <span>H <b>{fmt(hudBar.high)}</b></span>
                  <span>L <b>{fmt(hudBar.low)}</b></span>
                  <span className={hudBar.close >= hudBar.open ? "gain" : "loss"}>C <b>{fmt(hudBar.close)}</b></span>
                  <span>V <b>{Math.round(hudBar.volume).toLocaleString("en-IN")}</b></span>
                </div>
                {hudRows.length > 0 && (
                  <div className="hud-ind">
                    {hudRows.map((row) => (
                      <span key={row.label} className="hud-ind-row">
                        <i className="swatch" style={{ background: row.color }} />
                        {row.label} <b>{fmt(row.value)}</b>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div ref={containerRef} className="chart-el" />
            <DrawToolbar
              activeTool={activeTool}
              onSelectTool={setActiveTool}
              colors={DRAW_COLORS}
              activeColor={drawColor}
              onSelectColor={setDrawColor}
              disabled={!selected}
            />
            {noteDraft && (
              <input
                className="note-input"
                autoFocus
                placeholder="Note, then Enter"
                style={{ left: noteDraft.x, top: noteDraft.y }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitNote((e.target as HTMLInputElement).value);
                  if (e.key === "Escape") setNoteDraft(null);
                }}
                onBlur={(e) => commitNote(e.target.value)}
              />
            )}
          </div>
          {showWatchlist && (
            <WatchlistPanel activeSecurityId={selected?.security_id} onSelect={selectSymbol} />
          )}
          {showPanel && <IndicatorPanel config={config} onChange={setConfig} intraday={intraday} />}
          {showOverlayPanel && (
            <OverlayPanel
              config={overlayConfig}
              onChange={setOverlayConfig}
              positions={positions}
              calls={calls}
              runs={runs}
              selectedRunId={selectedRunId}
              onSelectRun={setSelectedRunId}
              tradeCount={trades.length}
              replay={replay}
              onReplayChange={setReplay}
              optionContext={optionContext}
              optionContextLoading={optionContextLoading}
              optionContextError={optionContextError}
              optionContextEligible={optionContextSymbol !== null}
            />
          )}
          {showAnalysisPanel && (
            <AnalysisPanel
              structure={structure}
              structureLoading={structureLoading}
              showStructure={showStructure}
              onToggleStructure={setShowStructure}
              explanation={explanation}
              explaining={explaining}
              explainError={explainError}
              onExplain={runExplain}
              canExplain={computed.displayBars.length > 0}
            />
          )}
          {showWorkspacePanel && (
            <WorkspacePanel
              activeTool={activeTool}
              onSelectTool={setActiveTool}
              colors={DRAW_COLORS}
              activeColor={drawColor}
              onSelectColor={setDrawColor}
              drawings={drawings}
              onDeleteDrawing={async (id) => {
                try {
                  await deleteChartDrawing(id);
                  setDrawings((prev) => prev.filter((d) => d.drawing_id !== id));
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Could not delete that drawing");
                }
              }}
              pendingPoint={pendingPoint !== null}
              layouts={layouts}
              onSaveLayout={handleSaveLayout}
              onApplyLayout={handleApplyLayout}
              onDeleteLayout={async (id) => {
                try {
                  await deleteChartLayout(id);
                  setLayouts((prev) => prev.filter((l) => l.layout_id !== id));
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Could not delete that layout");
                }
              }}
              alerts={alerts}
              onCreateAlert={handleCreateAlert}
              onDeleteAlert={async (id) => {
                try {
                  await deleteChartAlert(id);
                  setAlerts((prev) => prev.filter((a) => a.alert_id !== id));
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Could not delete that alert");
                }
              }}
              lastPrice={lastBar?.close ?? null}
              compareSymbols={compareSymbols.map((s) => s.symbol)}
              onRemoveCompare={(sym) => setCompareSymbols((prev) => prev.filter((s) => s.symbol !== sym))}
              canAddCompare={
                !!selected && compareSymbols.length < 4 &&
                !compareSymbols.some((s) => s.security_id === selected.security_id)
              }
              onAddCompare={() => selected && setCompareSymbols((prev) => [...prev, selected])}
              disabled={!selected}
            />
          )}
        </div>

        {compareSymbols.length > 0 && (
          <CompareGrid
            symbols={compareSymbols}
            resolution={resolution}
            onRemove={(sym) => setCompareSymbols((prev) => prev.filter((s) => s.security_id !== sym))}
          />
        )}

        <div className="footnote">
          Candles and volume are live Dhan data (intraday resolutions are capped to the last ~30 days of history — Dhan
          doesn&apos;t serve much further back intraday). The dashed purple line is an automatically detected swing-based
          trend line over the visible lookback, not a guarantee of future direction. Indicators are computed in your
          browser from the candles already loaded — they add no extra data requests, and they are always calculated from
          the real OHLC values even when Heikin-Ashi rendering is on.
        </div>
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .toolbar { display: flex; flex-direction: column; gap: 12px; padding: 16px 20px 0; }
        .search-wrap { position: relative; }
        .search-wrap input { width: 100%; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 15px; }
        .dropdown { margin-top: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; max-height: 260px; overflow-y: auto; position: absolute; left: 0; right: 0; z-index: 20; }
        .dropdown-item { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; padding: 11px 12px; background: none; border: none; border-bottom: 1px solid var(--panel-border); cursor: pointer; font-size: 13px; }
        .dropdown-item:last-child { border-bottom: none; }
        .dropdown-item:hover { background: var(--panel); }
        .dsym { font-weight: 700; min-width: 90px; flex-shrink: 0; }
        .dname { flex: 1; color: var(--text-muted); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .dseg { font-size: 10px; font-weight: 800; color: var(--purple); flex-shrink: 0; }
        .dropdown-empty { padding: 14px 12px; font-size: 13px; color: var(--text-faint); text-align: center; }
        .res-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .res-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 7px 14px; font-size: 12.5px; font-weight: 700; color: var(--text-muted); cursor: pointer; }
        .res-btn.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .trend-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 7px 14px; font-size: 12px; font-weight: 700; color: var(--text-muted); cursor: pointer; }
        .trend-btn:first-of-type { margin-left: auto; }
        .trend-btn.active { background: rgba(125, 52, 220, 0.12); border-color: rgba(125, 52, 220, 0.35); color: var(--purple); }
        .symbol-line { display: flex; align-items: center; gap: 10px; padding: 12px 20px 0; flex-wrap: wrap; }
        .sym-name { font-weight: 700; font-size: 14px; }
        .sym-tag { font-size: 10px; font-weight: 800; color: var(--text-faint); background: var(--canvas-soft); border-radius: 6px; padding: 2px 7px; }
        .sym-price { font-weight: 700; font-size: 14px; font-variant-numeric: tabular-nums; }
        .sym-price.gain { color: var(--gain); }
        .sym-price.loss { color: var(--loss); }
        .live-pill { display: inline-flex; align-items: center; gap: 5px; font-size: 10.5px; font-weight: 800; letter-spacing: 0.03em; padding: 2px 8px; border-radius: 6px; }
        .live-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; display: inline-block; }
        .live-pill.ok { color: var(--gain); background: var(--gain-dim); }
        .live-pill.ok .dot { animation: pulse 1.6s ease-in-out infinite; }
        .live-pill.warn { color: #f2b705; background: rgba(242, 183, 5, 0.12); }
        .live-pill.muted { color: var(--text-faint); background: var(--canvas-soft); }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.25; } }
        .trend-tag { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
        .trend-tag.support { color: var(--gain); background: var(--gain-dim); }
        .trend-tag.resistance { color: var(--loss); background: var(--loss-dim); }
        .alert-toasts { display: flex; flex-direction: column; gap: 6px; padding: 10px 20px 0; }
        .alert-toast { display: flex; align-items: center; gap: 9px; background: rgba(255, 167, 38, 0.1); border: 1px solid rgba(255, 167, 38, 0.35); border-radius: 9px; padding: 9px 12px; font-size: 12px; color: var(--text); }
        .alert-toast .bell { flex-shrink: 0; }
        .alert-toast span { flex: 1; line-height: 1.45; }
        .alert-toast .tnote { color: var(--text-faint); }
        .alert-toast button { background: none; border: none; color: var(--text-faint); font-size: 16px; line-height: 1; cursor: pointer; flex-shrink: 0; }
        .chart-row { display: flex; gap: 14px; align-items: flex-start; padding: 12px 20px 4px; }
        .chart-wrap { position: relative; flex: 1; min-width: 0; min-height: 520px; }
        .note-input {
          position: absolute; z-index: 6; transform: translate(-50%, -140%);
          background: var(--panel); color: inherit; border: 1px solid var(--purple);
          border-radius: 7px; padding: 5px 8px; font-size: 12px; font-family: inherit;
          width: 190px; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
        }
        .chart-el { width: 100%; }
        .empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-size: 13px; background: var(--canvas-soft); border-radius: 10px; z-index: 4; }
        .loading-overlay { position: absolute; top: 6px; right: 14px; font-size: 12px; color: var(--text-muted); background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px; padding: 5px 10px; z-index: 6; }
        .hud { position: absolute; top: 6px; left: 10px; z-index: 5; pointer-events: none; display: flex; flex-direction: column; gap: 2px; font-size: 11px; line-height: 1.5; font-variant-numeric: tabular-nums; }
        .hud-date { color: var(--text-faint); font-size: 10.5px; font-weight: 700; }
        .hud-ohlc { display: flex; flex-wrap: wrap; gap: 9px; color: var(--text-muted); }
        .hud-ohlc b { color: var(--text); font-weight: 700; }
        .hud-ohlc .gain b { color: var(--gain); }
        .hud-ohlc .loss b { color: var(--loss); }
        .hud-ind { display: flex; flex-wrap: wrap; gap: 9px; color: var(--text-muted); }
        .hud-ind b { color: var(--text); font-weight: 700; }
        .hud-ind-row { display: inline-flex; align-items: center; gap: 4px; }
        .swatch { width: 7px; height: 7px; border-radius: 2px; display: inline-block; }
        .footnote { padding: 8px 20px 18px; font-size: 11px; color: var(--text-faint); line-height: 1.5; }
        @media (max-width: 900px) {
          .chart-row { flex-direction: column; }
        }
      `}</style>
    </div>
  );
}
