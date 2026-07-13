"use client";

import { useMemo, useRef, useState } from "react";

export interface SeriesPoint {
  ts: string;
  value: number;
}

/** Single-series SVG line/area chart with crosshair + tooltip hover layer.
 * Dataviz rules applied: 2px line, recessive grid, one axis, direct last-value
 * label, text in text tokens (never series color), tabular numerals. */
export default function LineChart({
  points,
  color = "var(--accent)",
  height = 220,
  fillToZero = false,
  valueSuffix = "",
  formatValue = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 2 }),
}: {
  points: SeriesPoint[];
  color?: string;
  height?: number;
  fillToZero?: boolean;
  valueSuffix?: string;
  formatValue?: (v: number) => string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 900;
  const H = height;
  const PAD = { top: 14, right: 74, bottom: 24, left: 10 };

  const { path, area, xs, ys, min, max, gridYs } = useMemo(() => {
    if (points.length < 2) return { path: "", area: "", xs: [], ys: [], min: 0, max: 0, gridYs: [] as number[] };
    const values = points.map((p) => p.value);
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    if (fillToZero) hi = Math.max(hi, 0);
    if (hi === lo) hi = lo + 1;
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;
    const xAt = (i: number) => PAD.left + (i / (points.length - 1)) * innerW;
    const yAt = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * innerH;
    const xsA = points.map((_, i) => xAt(i));
    const ysA = values.map(yAt);
    const d = xsA.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ysA[i].toFixed(1)}`).join("");
    const baseline = yAt(fillToZero ? 0 : lo);
    const a = `${d}L${xsA[xsA.length - 1].toFixed(1)},${baseline.toFixed(1)}L${xsA[0].toFixed(1)},${baseline.toFixed(1)}Z`;
    const gYs = [0.25, 0.5, 0.75].map((f) => PAD.top + f * innerH);
    return { path: d, area: a, xs: xsA, ys: ysA, min: lo, max: hi, gridYs: gYs };
  }, [points, fillToZero, H]);

  if (points.length < 2) {
    return <div style={{ padding: 24, color: "var(--text-faint)", fontSize: 13 }}>Not enough data</div>;
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const fx = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < xs.length; i++) {
      const d = Math.abs(xs[i] - fx);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    setHover(best);
  };

  const h = hover;
  const last = points[points.length - 1];
  const tipLeft = h !== null ? (xs[h] / W) * 100 : 0;

  return (
    <div ref={wrapRef} className="chart-wrap" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="time series chart">
        {gridYs.map((gy) => (
          <line key={gy} x1={PAD.left} x2={W - PAD.right} y1={gy} y2={gy} stroke="var(--panel-border)" strokeWidth={1} />
        ))}
        {fillToZero && <path d={area} fill={color} opacity={0.12} />}
        <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {h !== null && (
          <>
            <line x1={xs[h]} x2={xs[h]} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--text-faint)" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={xs[h]} cy={ys[h]} r={4} fill={color} stroke="var(--canvas)" strokeWidth={2} />
          </>
        )}
      </svg>
      {/* direct last-value label (HTML so it never stretches with preserveAspectRatio) */}
      <div className="last-tag" style={{ top: `${(ys[ys.length - 1] / H) * 100}%` }}>
        {formatValue(last.value)}{valueSuffix}
      </div>
      {h !== null && (
        <div className="tooltip" style={{ left: `${tipLeft}%` }}>
          <div className="tip-date">{points[h].ts.slice(0, 10)}</div>
          <div className="tip-value">{formatValue(points[h].value)}{valueSuffix}</div>
        </div>
      )}
      <div className="axis-row">
        <span>{points[0].ts.slice(0, 10)}</span>
        <span>{last.ts.slice(0, 10)}</span>
      </div>

      <style jsx>{`
        .chart-wrap {
          position: relative;
          padding: 4px 8px 0;
        }
        svg {
          display: block;
          width: 100%;
          height: ${H}px;
        }
        .last-tag {
          position: absolute;
          right: 8px;
          transform: translateY(-50%);
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 11px;
          color: var(--text);
          background: var(--panel);
          border: 1px solid var(--panel-border);
          border-radius: 6px;
          padding: 2px 6px;
          pointer-events: none;
        }
        .tooltip {
          position: absolute;
          top: 6px;
          transform: translateX(-50%);
          background: var(--text);
          border-radius: 8px;
          padding: 6px 10px;
          pointer-events: none;
          white-space: nowrap;
          z-index: 5;
          box-shadow: var(--shadow-md);
        }
        .tip-date {
          font-size: 10.5px;
          color: rgba(255, 255, 255, 0.6);
        }
        .tip-value {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 12.5px;
          font-weight: 600;
          color: #fff;
        }
        .axis-row {
          display: flex;
          justify-content: space-between;
          padding: 4px 2px 8px;
          font-size: 10.5px;
          color: var(--text-faint);
          font-variant-numeric: tabular-nums;
        }
      `}</style>
    </div>
  );
}
