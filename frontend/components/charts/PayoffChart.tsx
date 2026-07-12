"use client";

import { useId } from "react";

/** Payoff-at-expiry line (P&L vs spot), not a time series — a dedicated component
 * since LineChart's x-axis assumes dates. Zero line and breakeven points are called
 * out directly since color alone must never carry the profit/loss distinction. */
export default function PayoffChart({
  points,
  breakevens = [],
  height = 220,
}: {
  points: { spot: number; pnl: number }[];
  breakevens?: number[];
  height?: number;
}) {
  if (points.length < 2) {
    return <div style={{ padding: 24, color: "var(--text-faint)", fontSize: 13 }}>No payoff data</div>;
  }
  const W = 900;
  const H = height;
  const PAD = { top: 14, right: 20, bottom: 24, left: 60 };
  const spots = points.map((p) => p.spot);
  const pnls = points.map((p) => p.pnl);
  const minSpot = Math.min(...spots);
  const maxSpot = Math.max(...spots);
  const minPnl = Math.min(...pnls, 0);
  const maxPnl = Math.max(...pnls, 0);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const xAt = (spot: number) => PAD.left + ((spot - minSpot) / (maxSpot - minSpot || 1)) * innerW;
  const yAt = (pnl: number) => PAD.top + (1 - (pnl - minPnl) / (maxPnl - minPnl || 1)) * innerH;
  const zeroY = yAt(0);

  const uid = useId().replace(/:/g, "");
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${xAt(p.spot).toFixed(1)},${yAt(p.pnl).toFixed(1)}`).join("");
  const areaAbove = `${path}L${xAt(points[points.length - 1].spot).toFixed(1)},${zeroY.toFixed(1)}L${xAt(points[0].spot).toFixed(1)},${zeroY.toFixed(1)}Z`;

  const fmt = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 0 });

  return (
    <div className="wrap">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="payoff diagram">
        <line x1={PAD.left} x2={W - PAD.right} y1={zeroY} y2={zeroY} stroke="var(--text-faint)" strokeWidth={1} strokeDasharray="4 3" />
        <clipPath id={`above-zero-${uid}`}>
          <rect x={PAD.left} y={PAD.top} width={innerW} height={Math.max(zeroY - PAD.top, 0)} />
        </clipPath>
        <clipPath id={`below-zero-${uid}`}>
          <rect x={PAD.left} y={zeroY} width={innerW} height={Math.max(H - PAD.bottom - zeroY, 0)} />
        </clipPath>
        <path d={areaAbove} fill="var(--gain)" opacity={0.12} clipPath={`url(#above-zero-${uid})`} />
        <path d={areaAbove} fill="var(--loss)" opacity={0.12} clipPath={`url(#below-zero-${uid})`} />
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        {breakevens.map((be) => (
          <line key={be} x1={xAt(be)} x2={xAt(be)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="2 2" />
        ))}
      </svg>
      <div className="axis-row">
        <span>{fmt(minSpot)}</span>
        <span className="mid">spot at expiry</span>
        <span>{fmt(maxSpot)}</span>
      </div>
      {breakevens.length > 0 && (
        <div className="be-row">
          Breakeven: {breakevens.map((b) => fmt(b)).join(", ")}
        </div>
      )}
      <style jsx>{`
        .wrap { padding: 4px 8px 8px; }
        svg { display: block; width: 100%; height: ${H}px; }
        .axis-row {
          display: flex;
          justify-content: space-between;
          padding: 4px 2px 2px;
          font-size: 10.5px;
          color: var(--text-faint);
          font-variant-numeric: tabular-nums;
        }
        .mid { text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; }
        .be-row {
          padding: 0 2px 6px;
          font-size: 11px;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
}
