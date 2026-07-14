"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickData,
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
  LineSeries,
  UTCTimestamp,
} from "lightweight-charts";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  ChartResolution,
  ChartSymbol,
  ChartSymbolInfo,
  ChartTrend,
  fetchChartHistory,
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

export default function ChartPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const trendSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

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
  const [lastBar, setLastBar] = useState<CandlestickData | null>(null);

  // --- chart setup (once) ---
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
    };
  }, []);

  // --- search ---
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
    setQuery(`${s.symbol} (${s.exchange_segment === "BSE_EQ" ? "BSE" : s.exchange_segment === "NSE_FNO" ? "F&O" : s.exchange_segment === "IDX_I" ? "INDEX" : "NSE"})`);
    try {
      setSymbolInfo(await resolveChartSymbol(s.security_id, s.exchange_segment));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resolve symbol");
    }
  }, []);

  const load = useCallback(async () => {
    if (!selected || !candleSeriesRef.current || !volumeSeriesRef.current) return;
    setLoading(true);
    setError(null);
    try {
      const cfg = RESOLUTIONS.find((r) => r.id === resolution)!;
      const to = Math.floor(Date.now() / 1000);
      const from = to - cfg.lookbackSeconds;
      const bars = await fetchChartHistory(selected.security_id, selected.exchange_segment, resolution, from, to);
      if (bars.s !== "ok" || !bars.t?.length) {
        candleSeriesRef.current.setData([]);
        volumeSeriesRef.current.setData([]);
        trendSeriesRef.current?.setData([]);
        setLastBar(null);
        setError("No candle data available for this symbol/timeframe right now.");
        return;
      }
      const candles: CandlestickData[] = bars.t.map((time, i) => ({
        time: time as UTCTimestamp, open: bars.o![i], high: bars.h![i], low: bars.l![i], close: bars.c![i],
      }));
      const volumes = bars.t.map((time, i) => ({
        time: time as UTCTimestamp, value: bars.v![i],
        color: bars.c![i] >= bars.o![i] ? "rgba(38,166,154,0.5)" : "rgba(239,83,80,0.5)",
      }));
      candleSeriesRef.current.setData(candles);
      volumeSeriesRef.current.setData(volumes);
      chartRef.current?.timeScale().fitContent();
      setLastBar(candles[candles.length - 1]);

      if (showTrend) {
        try {
          const t = await fetchChartTrendline(selected.security_id, selected.exchange_segment, resolution);
          setTrend(t.trend);
          if (t.trend) {
            trendSeriesRef.current?.setData([
              { time: t.trend.p1.time as UTCTimestamp, value: t.trend.p1.price },
              { time: t.trend.p2.time as UTCTimestamp, value: t.trend.p2.price },
            ]);
          } else {
            trendSeriesRef.current?.setData([]);
          }
        } catch {
          trendSeriesRef.current?.setData([]);
          setTrend(null);
        }
      } else {
        trendSeriesRef.current?.setData([]);
        setTrend(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chart data");
    } finally {
      setLoading(false);
    }
  }, [selected, resolution, showTrend]);

  useEffect(() => {
    load();
  }, [load]);

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
              placeholder="Search stock, index, or future (e.g. NIFTY, RELIANCE)"
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
                      <span className="dsym">{r.symbol}</span>
                      <span className="dname">{r.name}</span>
                      <span className="dseg">{r.asset_class}</span>
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
          </div>
        </div>

        {selected && symbolInfo && (
          <div className="symbol-line">
            <span className="sym-name">{symbolInfo.name}</span>
            <span className="sym-tag">{symbolInfo.asset_class}</span>
            {lastBar && (
              <span className={`sym-price ${lastBar.close >= lastBar.open ? "gain" : "loss"}`}>
                {lastBar.close.toFixed(2)}
              </span>
            )}
            {trend && <span className={`trend-tag ${trend.kind}`}>{trend.kind === "support" ? "▲ Uptrend line" : "▼ Downtrend line"}</span>}
          </div>
        )}

        {error && <ErrorBanner message={error} />}

        <div className="chart-wrap">
          {!selected && <div className="empty">Search for a symbol above to load its chart.</div>}
          {loading && <div className="loading-overlay">Loading…</div>}
          <div ref={containerRef} className="chart-el" />
        </div>

        <div className="footnote">
          Candles and volume are live Dhan data (intraday resolutions are capped to the last ~30 days of history — Dhan
          doesn't serve much further back intraday). The dashed purple line is an automatically detected swing-based
          trend line over the visible lookback, not a guarantee of future direction.
        </div>
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .toolbar { display: flex; flex-direction: column; gap: 12px; padding: 16px 20px 0; }
        .search-wrap { position: relative; }
        .search-wrap input { width: 100%; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 15px; }
        .dropdown { margin-top: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; max-height: 260px; overflow-y: auto; }
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
        .trend-btn { margin-left: auto; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 7px 14px; font-size: 12px; font-weight: 700; color: var(--text-muted); cursor: pointer; }
        .trend-btn.active { background: rgba(125, 52, 220, 0.12); border-color: rgba(125, 52, 220, 0.35); color: var(--purple); }
        .symbol-line { display: flex; align-items: center; gap: 10px; padding: 12px 20px 0; flex-wrap: wrap; }
        .sym-name { font-weight: 700; font-size: 14px; }
        .sym-tag { font-size: 10px; font-weight: 800; color: var(--text-faint); background: var(--canvas-soft); border-radius: 6px; padding: 2px 7px; }
        .sym-price { font-weight: 700; font-size: 14px; font-variant-numeric: tabular-nums; }
        .sym-price.gain { color: var(--gain); }
        .sym-price.loss { color: var(--loss); }
        .trend-tag { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
        .trend-tag.support { color: var(--gain); background: var(--gain-dim); }
        .trend-tag.resistance { color: var(--loss); background: var(--loss-dim); }
        .chart-wrap { position: relative; padding: 12px 20px 4px; min-height: 520px; }
        .chart-el { width: 100%; }
        .empty { position: absolute; inset: 12px 20px 4px; display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-size: 13px; background: var(--canvas-soft); border-radius: 10px; }
        .loading-overlay { position: absolute; top: 18px; right: 26px; font-size: 12px; color: var(--text-muted); background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px; padding: 5px 10px; z-index: 5; }
        .footnote { padding: 8px 20px 18px; font-size: 11px; color: var(--text-faint); line-height: 1.5; }
      `}</style>
    </div>
  );
}
