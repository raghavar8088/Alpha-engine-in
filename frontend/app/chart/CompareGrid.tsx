"use client";

/** Linked multi-chart comparison view (Phase 7).
 *
 * Each tile is a small, self-contained candlestick chart on the same timeframe
 * as the main chart, so a stock can be eyeballed against its index or sector
 * peers. Tiles are deliberately plain — no indicators, no streaming — because
 * this is a glance view, and giving every tile a live subscription would
 * multiply the work the main chart already does.
 */

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  IChartApi,
  UTCTimestamp,
} from "lightweight-charts";
import { ChartResolution, ChartSymbol, fetchChartHistory } from "../../lib/api";

const LOOKBACK_SECONDS: Record<ChartResolution, number> = {
  "1": 2 * 86400,
  "5": 5 * 86400,
  "15": 10 * 86400,
  "60": 30 * 86400,
  D: 400 * 86400,
  W: 5 * 365 * 86400,
};

interface TileProps {
  symbol: ChartSymbol;
  resolution: ChartResolution;
  onRemove: (securityId: string) => void;
}

function CompareTile({ symbol, resolution, onRemove }: TileProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [change, setChange] = useState<number | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#787b86" },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(120,123,134,0.06)" } },
      width: el.clientWidth,
      height: 190,
      timeScale: { timeVisible: resolution !== "D" && resolution !== "W", secondsVisible: false },
      rightPriceScale: { borderVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
      wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    chartRef.current = chart;

    let cancelled = false;
    (async () => {
      try {
        const to = Math.floor(Date.now() / 1000);
        const from = to - LOOKBACK_SECONDS[resolution];
        const bars = await fetchChartHistory(
          symbol.security_id, symbol.exchange_segment, resolution, from, to,
        );
        if (cancelled) return;
        if (bars.s !== "ok" || !bars.t?.length) {
          setStatus("empty");
          return;
        }
        series.setData(
          bars.t.map((time, i) => ({
            time: time as UTCTimestamp,
            open: bars.o![i], high: bars.h![i], low: bars.l![i], close: bars.c![i],
          })),
        );
        chart.timeScale().fitContent();
        const first = bars.o![0];
        const last = bars.c![bars.c!.length - 1];
        setChange(first ? ((last - first) / first) * 100 : null);
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    const onResize = () => chart.applyOptions({ width: el.clientWidth });
    window.addEventListener("resize", onResize);
    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [symbol.security_id, symbol.exchange_segment, resolution]);

  return (
    <div className="tile">
      <div className="head">
        <span className="sym">{symbol.symbol}</span>
        {change !== null && (
          <span className={change >= 0 ? "chg gain" : "chg loss"}>
            {change >= 0 ? "+" : ""}{change.toFixed(2)}%
          </span>
        )}
        <button className="x" onClick={() => onRemove(symbol.security_id)} title="Remove">×</button>
      </div>
      <div className="body">
        {status === "loading" && <div className="state">Loading…</div>}
        {status === "empty" && <div className="state">No data for this timeframe.</div>}
        {status === "error" && <div className="state">Could not load.</div>}
        <div ref={containerRef} className="el" />
      </div>

      <style jsx>{`
        .tile { border: 1px solid var(--panel-border); border-radius: 10px; background: var(--canvas-soft); overflow: hidden; }
        .head { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--panel-border); }
        .sym { font-weight: 700; font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .chg { font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .chg.gain { color: var(--gain); }
        .chg.loss { color: var(--loss); }
        .x { background: none; border: none; color: var(--text-faint); font-size: 15px; line-height: 1; cursor: pointer; padding: 0 2px; }
        .x:hover { color: var(--loss); }
        .body { position: relative; min-height: 190px; }
        .state { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--text-faint); z-index: 2; }
        .el { width: 100%; }
      `}</style>
    </div>
  );
}

interface Props {
  symbols: ChartSymbol[];
  resolution: ChartResolution;
  onRemove: (securityId: string) => void;
}

export default function CompareGrid({ symbols, resolution, onRemove }: Props) {
  return (
    <div className="grid-wrap">
      <div className="label">Comparison · {resolution === "D" ? "daily" : resolution === "W" ? "weekly" : `${resolution}m`}</div>
      <div className="grid">
        {symbols.map((s) => (
          <CompareTile key={`${s.exchange_segment}-${s.security_id}`} symbol={s} resolution={resolution} onRemove={onRemove} />
        ))}
      </div>

      <style jsx>{`
        .grid-wrap { padding: 4px 20px 18px; display: flex; flex-direction: column; gap: 8px; }
        .label { font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
        @media (max-width: 760px) {
          .grid { grid-template-columns: minmax(0, 1fr); }
        }
      `}</style>
    </div>
  );
}
