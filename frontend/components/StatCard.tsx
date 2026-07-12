import Sparkline from "./Sparkline";
import FlashOnChange from "./FlashOnChange";

export default function StatCard({
  label,
  price,
  change,
  pctChange,
  sparklineValues,
  index = 0,
}: {
  label: string;
  price: string;
  change: number | null;
  pctChange: number | null;
  sparklineValues: number[];
  index?: number;
}) {
  const up = (change ?? 0) >= 0;

  return (
    <div className="stat-card" style={{ animationDelay: `${index * 0.05}s` }}>
      <div className="stat-symbol">{label}</div>
      <FlashOnChange value={price}>
        <div className="stat-price">{price}</div>
      </FlashOnChange>
      <div className={`stat-change ${up ? "up" : "down"}`}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
          {up ? <path d="M6 15l6-6 6 6" /> : <path d="M6 9l6 6 6-6" />}
        </svg>
        {change !== null ? `${up ? "+" : ""}${change.toFixed(2)}` : "-"}
        {pctChange !== null ? ` (${up ? "+" : ""}${pctChange.toFixed(2)}%)` : ""}
      </div>
      <div style={{ marginTop: 12 }}>
        <Sparkline values={sparklineValues} />
      </div>

      <style jsx>{`
        .stat-card {
          background: var(--panel);
          border: 1px solid var(--panel-border);
          border-radius: 16px;
          padding: 18px 18px 14px;
          box-shadow: var(--shadow-sm);
          transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
          opacity: 0;
          animation: rise 0.5s ease forwards;
        }
        @keyframes rise {
          from {
            opacity: 0;
            transform: translateY(8px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        .stat-card:hover {
          transform: translateY(-2px);
          border-color: var(--panel-border-hover);
          box-shadow: var(--shadow-md);
        }
        .stat-symbol {
          font-size: 11.5px;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-muted);
          margin-bottom: 10px;
        }
        .stat-change {
          display: flex;
          align-items: center;
          gap: 5px;
          margin-top: 6px;
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 12.5px;
          font-weight: 600;
        }
        .stat-change.up {
          color: var(--gain);
        }
        .stat-change.down {
          color: var(--loss);
        }
        .stat-change svg {
          width: 11px;
          height: 11px;
        }
        .stat-card :global(.stat-price) {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 25px;
          font-weight: 600;
          letter-spacing: -0.2px;
        }
      `}</style>
    </div>
  );
}
