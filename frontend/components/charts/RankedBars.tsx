"use client";

/**
 * Ranked diverging bars — the form for "who is up, who is down, in order".
 *
 * SIGN IS ENCODED BY POSITION FIRST. Bars grow right from a centre zero line when positive
 * and left when negative, and every bar carries its own signed value as a direct label. The
 * gain/loss hues reinforce that; they never carry it alone. This matters beyond neatness:
 * green against red is ΔE 6.6 under deuteranopia — separable, but only just — so a chart
 * that encoded direction in colour alone would be unreadable to a red-green colourblind
 * reader. Direction and the printed number are both immune to that.
 *
 * The zero line is a real axis, not decoration: with mixed signs it sits in the middle of
 * the track, so the eye reads "where does this sector cross from losing to winning" without
 * comparing lengths across a gap.
 *
 * Scale is shared across every row (the largest absolute value sets the half-width), so bar
 * lengths are comparable — the single most common way a ranked bar chart lies is by scaling
 * each row to itself.
 */

export interface RankedBarRow {
  key: string;
  label: string;
  value: number | null;
  sublabel?: string;
  badge?: { text: string; tone?: "gain" | "loss" | "warn" | "accent" | "muted" };
  tooltip?: string;
  muted?: boolean;
}

export default function RankedBars({
  rows,
  unit = "%",
  labelWidth = 150,
  maxRows,
  onSelect,
  emptyNote = "Nothing to plot",
}: {
  rows: RankedBarRow[];
  unit?: string;
  labelWidth?: number;
  maxRows?: number;
  onSelect?: (key: string) => void;
  emptyNote?: string;
}) {
  const usable = rows.filter((r) => r.value !== null && Number.isFinite(r.value as number));
  if (usable.length === 0) {
    return <div className="empty">{emptyNote}<style jsx>{`
      .empty { padding: 22px; color: var(--text-faint); font-size: 13px; }
    `}</style></div>;
  }

  const shown = maxRows ? usable.slice(0, maxRows) : usable;
  // One shared scale for every row. Never per-row.
  const extent = Math.max(...shown.map((r) => Math.abs(r.value as number)), 0.001);
  const hasNegative = shown.some((r) => (r.value as number) < 0);
  // With no negatives the zero line sits at the left edge and the full track is available,
  // which keeps a single-sign chart from wasting half its width.
  const zeroPct = hasNegative ? 50 : 0;
  const halfSpan = hasNegative ? 50 : 100;

  const fmt = (v: number) =>
    `${v >= 0 ? "+" : ""}${Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)}${unit}`;

  return (
    <div className="ranked">
      {shown.map((r) => {
        const v = r.value as number;
        const width = (Math.abs(v) / extent) * halfSpan;
        const up = v >= 0;
        return (
          <div
            key={r.key}
            className={`row${onSelect ? " clickable" : ""}${r.muted ? " muted" : ""}`}
            onClick={onSelect ? () => onSelect(r.key) : undefined}
            title={r.tooltip || `${r.label}: ${fmt(v)}`}
          >
            <div className="label" style={{ width: labelWidth }}>
              <span className="name">{r.label}</span>
              {r.sublabel && <span className="sub">{r.sublabel}</span>}
            </div>

            <div className="track">
              <div className="zero" style={{ left: `${zeroPct}%` }} />
              <div
                className={`bar ${up ? "up" : "down"}`}
                style={
                  up
                    ? { left: `${zeroPct}%`, width: `${width}%` }
                    : { right: `${100 - zeroPct}%`, width: `${width}%` }
                }
              />
              <span
                className={`val ${up ? "up" : "down"}`}
                style={up ? { left: `calc(${zeroPct}% + ${width}% + 6px)` }
                          : { right: `calc(${100 - zeroPct}% + ${width}% + 6px)` }}
              >
                {fmt(v)}
              </span>
            </div>

            {r.badge && <span className={`badge ${r.badge.tone ?? "muted"}`}>{r.badge.text}</span>}
          </div>
        );
      })}

      <style jsx>{`
        .ranked {
          display: flex;
          flex-direction: column;
          /* 2px between marks so adjacent bars never read as one shape */
          gap: 2px;
          padding: 4px 0;
        }
        .row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 3px 0;
          border-radius: 6px;
        }
        .row.clickable { cursor: pointer; }
        .row.clickable:hover { background: var(--canvas-soft); }
        .row.muted { opacity: 0.55; }

        .label {
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          line-height: 1.25;
          overflow: hidden;
        }
        .name {
          font-size: 12.5px;
          font-weight: 600;
          color: var(--text);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sub { font-size: 10px; color: var(--text-faint); }

        .track {
          position: relative;
          flex: 1;
          height: 20px;
          min-width: 120px;
        }
        /* Recessive axis — present, never competing with the data */
        .zero {
          position: absolute;
          top: 0;
          bottom: 0;
          width: 1px;
          background: var(--panel-border);
        }
        .bar {
          position: absolute;
          top: 4px;
          height: 12px;
          min-width: 2px;
          /* Rounded on the DATA end only; the baseline end stays square so the bar
             visibly starts at zero rather than floating near it. */
          transition: width 0.18s ease;
        }
        .bar.up {
          background: var(--gain);
          border-radius: 0 4px 4px 0;
        }
        .bar.down {
          background: var(--loss);
          border-radius: 4px 0 0 4px;
        }
        .val {
          position: absolute;
          top: 50%;
          transform: translateY(-50%);
          font-size: 11px;
          font-weight: 600;
          font-variant-numeric: tabular-nums;
          white-space: nowrap;
          /* Values wear text tokens tinted to the sign, never the raw mark colour on
             a light ground where it would fail contrast. */
        }
        .val.up { color: var(--gain); }
        .val.down { color: var(--loss); }

        .badge {
          flex-shrink: 0;
          font-size: 10px;
          font-weight: 600;
          padding: 2px 7px;
          border-radius: 20px;
          white-space: nowrap;
        }
        .badge.gain { background: var(--gain-dim); color: var(--gain); }
        .badge.loss { background: var(--loss-dim); color: var(--loss); }
        .badge.warn { background: var(--warn-dim); color: var(--warn); }
        .badge.accent { background: var(--purple-dim); color: var(--purple); }
        .badge.muted { background: var(--canvas-soft); color: var(--text-muted); }
      `}</style>
    </div>
  );
}
