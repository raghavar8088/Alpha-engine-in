"use client";

/**
 * Best and worst name in every sector, on one shared scale.
 *
 * WHY THIS IS NOT ANOTHER RANKED BAR CHART. The sector board answers "which sector moved".
 * This answers a different question — how much AGREEMENT there was inside it. A sector at
 * +5% where every name did +4% to +6% is a real sector move; a sector at +5% where the best
 * name did +31% and the worst did -12% is not a sector move at all, it is two stories
 * filed under one label. Both look identical on a chart of sector averages, and the
 * difference decides whether "buy the sector" is even a coherent idea.
 *
 * So each row plots the laggard and the leader as a SPAN across a shared zero line. The
 * width of the span is the dispersion; where it sits is the direction. A narrow span far
 * to the right is the sector you can trade as a sector.
 *
 * Both ends are labelled with their symbol and value, so the pair is readable without
 * relying on the red/green hues — which is the same reason the ranked bars use direction
 * plus a direct label rather than colour alone.
 */

export interface SectorSpreadRow {
  sector: string;
  count: number;
  thin?: boolean;
  leader: { symbol: string; return_pct: number } | null;
  laggard: { symbol: string; return_pct: number } | null;
  sectorReturn: number | null;
}

export default function SectorSpread({
  rows,
  onSelectSector,
  onSelectSymbol,
}: {
  rows: SectorSpreadRow[];
  onSelectSector?: (sector: string) => void;
  onSelectSymbol?: (symbol: string) => void;
}) {
  const usable = rows.filter(
    (r) => r.leader && r.laggard &&
      Number.isFinite(r.leader.return_pct) && Number.isFinite(r.laggard.return_pct));

  if (usable.length === 0) {
    return (
      <div className="empty">
        Nothing to plot yet
        <style jsx>{`.empty { padding: 22px; color: var(--text-faint); font-size: 13px; }`}</style>
      </div>
    );
  }

  // One shared scale across every sector, so span widths are comparable between rows.
  const lo = Math.min(...usable.map((r) => r.laggard!.return_pct), 0);
  const hi = Math.max(...usable.map((r) => r.leader!.return_pct), 0);
  const span = Math.max(hi - lo, 0.001);
  const posOf = (v: number) => ((v - lo) / span) * 100;
  const zero = posOf(0);

  const fmt = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;

  // Widest dispersion first: the sectors that are NOT really moving together are the ones
  // worth noticing, and burying them under the tidy ones would defeat the point.
  const sorted = [...usable].sort(
    (a, b) => (b.leader!.return_pct - b.laggard!.return_pct)
            - (a.leader!.return_pct - a.laggard!.return_pct));

  return (
    <div className="spread">
      {sorted.map((r) => {
        const lag = r.laggard!;
        const led = r.leader!;
        const left = posOf(lag.return_pct);
        const right = posOf(led.return_pct);
        const dispersion = led.return_pct - lag.return_pct;

        return (
          <div className="row" key={r.sector}>
            <div
              className={`sector${onSelectSector ? " clickable" : ""}`}
              onClick={onSelectSector ? () => onSelectSector(r.sector) : undefined}
              title={`${r.sector} — open the drill-down`}
            >
              <span className="sname">{r.sector}</span>
              <span className="smeta">
                {r.count} names · spread {dispersion.toFixed(1)} pts
                {r.thin ? " · thin" : ""}
              </span>
            </div>

            <div className="track">
              <div className="zero" style={{ left: `${zero}%` }} />
              {/* The span itself: from worst to best. */}
              <div
                className="span"
                style={{ left: `${left}%`, width: `${Math.max(right - left, 0.4)}%` }}
              />
              <span
                className="cap lag"
                style={{ left: `${left}%` }}
                onClick={onSelectSymbol ? (e) => { e.stopPropagation(); onSelectSymbol(lag.symbol); } : undefined}
                title={`${lag.symbol}: ${fmt(lag.return_pct)} — worst in ${r.sector}`}
              />
              <span
                className="cap led"
                style={{ left: `${right}%` }}
                onClick={onSelectSymbol ? (e) => { e.stopPropagation(); onSelectSymbol(led.symbol); } : undefined}
                title={`${led.symbol}: ${fmt(led.return_pct)} — best in ${r.sector}`}
              />
            </div>

            <div className="ends">
              <span className="end low" title={`Worst: ${lag.symbol}`}>
                <b>{lag.symbol}</b> {fmt(lag.return_pct)}
              </span>
              <span className="end high" title={`Best: ${led.symbol}`}>
                <b>{led.symbol}</b> {fmt(led.return_pct)}
              </span>
            </div>
          </div>
        );
      })}

      <style jsx>{`
        .spread { display: flex; flex-direction: column; gap: 3px; padding: 4px 0; }
        .row { display: flex; align-items: center; gap: 12px; padding: 4px 0; }

        .sector { width: 190px; flex-shrink: 0; display: flex; flex-direction: column; line-height: 1.25; overflow: hidden; }
        .sector.clickable { cursor: pointer; }
        .sector.clickable:hover .sname { color: var(--purple); text-decoration: underline; }
        .sname { font-size: 12.5px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .smeta { font-size: 10px; color: var(--text-faint); white-space: nowrap; }

        .track { position: relative; flex: 1; height: 20px; min-width: 140px; }
        .zero { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--panel-border-hover); }
        .span {
          position: absolute; top: 8px; height: 4px; border-radius: 2px;
          /* One neutral band rather than a red half and a green half: the band is the
             RANGE, and colouring its halves would imply the middle of a sector behaves
             like its edges, which is exactly the assumption this chart exists to test. */
          background: var(--panel-border-hover);
        }
        .cap {
          position: absolute; top: 5px; width: 10px; height: 10px; border-radius: 50%;
          transform: translateX(-50%);
          /* 2px surface ring so two caps that land close together stay countable */
          box-shadow: 0 0 0 2px var(--panel);
          cursor: pointer;
        }
        .cap.lag { background: var(--loss); }
        .cap.led { background: var(--gain); }
        .cap:hover { transform: translateX(-50%) scale(1.25); }

        .ends { width: 250px; flex-shrink: 0; display: flex; justify-content: space-between; gap: 10px; font-size: 10.5px; font-variant-numeric: tabular-nums; }
        .end { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .end.low { color: var(--loss); }
        .end.high { color: var(--gain); }
        .end b { font-weight: 700; }

        @media (max-width: 900px) {
          .ends { display: none; }
          .sector { width: 130px; }
        }
      `}</style>
    </div>
  );
}
