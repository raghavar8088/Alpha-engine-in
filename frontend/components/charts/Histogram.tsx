"use client";

export interface HistogramBucket {
  from: number;
  to: number;
  count: number;
}

/** Trade P&L distribution. Sign is encoded positionally (left/right of the zero
 * line) AND by color, with 2px gaps between bars and per-bar tooltips — the
 * gain/loss hues never carry meaning alone. */
export default function Histogram({ buckets }: { buckets: HistogramBucket[] }) {
  if (buckets.length === 0) {
    return <div style={{ padding: 24, color: "var(--text-faint)", fontSize: 13 }}>No closed trades</div>;
  }
  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
  const fmt = (v: number) =>
    Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0);

  return (
    <div className="hist">
      <div className="bars">
        {buckets.map((b, i) => {
          const mid = (b.from + b.to) / 2;
          const h = (b.count / maxCount) * 100;
          return (
            <div
              key={i}
              className="bar-slot"
              title={`${fmt(b.from)} to ${fmt(b.to)}: ${b.count} trade${b.count === 1 ? "" : "s"}`}
            >
              <div
                className="bar"
                style={{
                  height: `${Math.max(h, b.count > 0 ? 4 : 0)}%`,
                  background: mid >= 0 ? "var(--gain)" : "var(--loss)",
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="axis-row">
        <span>{fmt(buckets[0].from)}</span>
        <span>0</span>
        <span>{fmt(buckets[buckets.length - 1].to)}</span>
      </div>

      <style jsx>{`
        .hist {
          padding: 12px 16px 8px;
        }
        .bars {
          display: flex;
          align-items: flex-end;
          gap: 2px; /* 2px surface gap between adjacent bars */
          height: 140px;
        }
        .bar-slot {
          flex: 1;
          height: 100%;
          display: flex;
          align-items: flex-end;
        }
        .bar {
          width: 100%;
          border-radius: 4px 4px 0 0; /* rounded data-end, flat baseline */
          min-height: 0;
        }
        .axis-row {
          display: flex;
          justify-content: space-between;
          padding-top: 6px;
          font-size: 10.5px;
          color: var(--text-faint);
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
        }
      `}</style>
    </div>
  );
}
