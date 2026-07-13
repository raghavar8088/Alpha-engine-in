"use client";

export interface MonthlyReturn {
  year: number;
  month: number;
  return_pct: number;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Year x month returns heatmap. Diverging encoding: gain-green vs loss-red arms
 * around a neutral near-zero midpoint. The gain/loss pair sits in the CVD floor
 * band, so every cell carries a direct text label (secondary encoding) and a
 * tooltip — color never carries the sign alone. */
export default function MonthlyHeatmap({ data }: { data: MonthlyReturn[] }) {
  if (data.length === 0) {
    return <div style={{ padding: 24, color: "var(--text-faint)", fontSize: 13 }}>No monthly data</div>;
  }
  const years = [...new Set(data.map((d) => d.year))].sort();
  const byKey = new Map(data.map((d) => [`${d.year}-${d.month}`, d.return_pct]));
  const maxAbs = Math.max(0.01, ...data.map((d) => Math.abs(d.return_pct)));

  const cellBg = (v: number | undefined) => {
    if (v === undefined) return "transparent";
    const t = Math.min(Math.abs(v) / maxAbs, 1);
    if (Math.abs(v) < 0.005) return "rgba(20, 20, 30, 0.04)"; // neutral midpoint
    const alpha = 0.10 + t * 0.5; // lightness-monotonic per arm
    return v > 0 ? `rgba(14, 159, 110, ${alpha})` : `rgba(217, 45, 63, ${alpha})`;
  };

  return (
    <div className="heatmap">
      <table>
        <thead>
          <tr>
            <th />
            {MONTHS.map((m) => (
              <th key={m}>{m}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <th>{y}</th>
              {MONTHS.map((_, i) => {
                const v = byKey.get(`${y}-${i + 1}`);
                return (
                  <td
                    key={i}
                    style={{ background: cellBg(v) }}
                    title={v !== undefined ? `${MONTHS[i]} ${y}: ${v > 0 ? "+" : ""}${v.toFixed(2)}%` : ""}
                  >
                    {v !== undefined ? `${v > 0 ? "+" : ""}${v.toFixed(1)}` : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <style jsx>{`
        .heatmap {
          overflow-x: auto;
          padding: 8px 12px 12px;
        }
        table {
          border-collapse: separate;
          border-spacing: 2px; /* 2px surface gap between fills */
          width: 100%;
          min-width: 640px;
        }
        th {
          font-size: 10.5px;
          font-weight: 600;
          color: var(--text-muted);
          padding: 3px 4px;
          text-align: center;
        }
        tbody th {
          text-align: right;
          padding-right: 8px;
          font-variant-numeric: tabular-nums;
        }
        td {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 10.5px;
          color: var(--text);
          text-align: center;
          padding: 6px 2px;
          border-radius: 4px;
          min-width: 40px;
        }
      `}</style>
    </div>
  );
}
