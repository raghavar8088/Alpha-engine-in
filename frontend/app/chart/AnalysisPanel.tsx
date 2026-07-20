"use client";

/** Structure read + AI "Explain this chart" (Phase 6).
 *
 * Controlled view only. The disclaimer copy is reused verbatim from the
 * Trading Calls page rather than reworded — advice-adjacent output must carry
 * the same wording everywhere it appears in this app.
 */

import { ChartExplanation, ChartStructure } from "../../lib/api";

/** Same sentence the Trading Calls page uses. Do not reword. */
export const NOT_ADVICE = "Not investment advice — validate before trading real money.";

interface Props {
  structure: ChartStructure | null;
  structureLoading: boolean;
  showStructure: boolean;
  onToggleStructure: (on: boolean) => void;
  explanation: ChartExplanation | null;
  explaining: boolean;
  explainError: string | null;
  onExplain: () => void;
  canExplain: boolean;
}

const BIAS_TONE: Record<string, string> = {
  uptrend: "gain",
  downtrend: "loss",
  compression: "warn",
  expansion: "warn",
  sideways: "muted",
  unclear: "muted",
};

const num = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

export default function AnalysisPanel({
  structure, structureLoading, showStructure, onToggleStructure,
  explanation, explaining, explainError, onExplain, canExplain,
}: Props) {
  const bias = structure?.structure?.bias;

  return (
    <div className="panel">
      <div className="group">
        <div className="group-title">Structure</div>
        <label className="toggle">
          <input type="checkbox" checked={showStructure} onChange={(e) => onToggleStructure(e.target.checked)} />
          <span>Show S/R zones &amp; channel</span>
        </label>

        {showStructure && structureLoading && <div className="note">Analysing…</div>}
        {showStructure && structure && !structure.available && (
          <div className="note">{structure.reason || "Not enough data to analyse."}</div>
        )}

        {showStructure && structure?.available && (
          <div className="body">
            {structure.structure && (
              <div className={`bias ${BIAS_TONE[bias || "unclear"] || "muted"}`}>
                {structure.structure.label}
              </div>
            )}
            <div className="meta">{structure.bars_analyzed} bars analysed</div>

            {(structure.resistance_zones?.length ?? 0) > 0 && (
              <>
                <div className="sub">Resistance</div>
                {structure.resistance_zones!.map((z) => (
                  <div key={`r${z.price}`} className="zone">
                    <span className="zp loss">{num(z.price)}</span>
                    <span className="zt">{z.touches} touches</span>
                  </div>
                ))}
              </>
            )}
            {(structure.support_zones?.length ?? 0) > 0 && (
              <>
                <div className="sub">Support</div>
                {structure.support_zones!.map((z) => (
                  <div key={`s${z.price}`} className="zone">
                    <span className="zp gain">{num(z.price)}</span>
                    <span className="zt">{z.touches} touches</span>
                  </div>
                ))}
              </>
            )}
            {structure.channel && <div className="note">Channel drawn from fitted swing highs/lows.</div>}
          </div>
        )}
      </div>

      <div className="group">
        <div className="group-title">AI read</div>
        <button className="explain" disabled={!canExplain || explaining} onClick={onExplain}>
          {explaining ? "Reading the chart…" : "Explain this chart"}
        </button>
        {!canExplain && <div className="note">Load a symbol first.</div>}

        {explainError && <div className="err">{explainError}</div>}

        {explanation?.status === "not_configured" && (
          <div className="err">
            AI is not configured on this server ({explanation.message || "no API key set"}). No summary can be
            generated — nothing is being guessed in its place.
          </div>
        )}

        {explanation?.status === "ok" && (
          <div className="body">
            {explanation.trend && (
              <div className={`bias ${BIAS_TONE[explanation.trend] || "muted"}`}>{explanation.trend}</div>
            )}
            {explanation.summary && <p className="summary">{explanation.summary}</p>}

            {(explanation.key_observations?.length ?? 0) > 0 && (
              <>
                <div className="sub">Observations</div>
                <ul>
                  {explanation.key_observations!.map((o, i) => (
                    <li key={i}>{o}</li>
                  ))}
                </ul>
              </>
            )}

            {(explanation.levels_to_watch?.length ?? 0) > 0 && (
              <>
                <div className="sub">Levels to watch</div>
                {explanation.levels_to_watch!.map((l, i) => (
                  <div key={i} className="zone">
                    <span className={`zp ${l.kind === "support" ? "gain" : "loss"}`}>{num(l.price)}</span>
                    <span className="zt">{l.why}</span>
                  </div>
                ))}
              </>
            )}

            {(explanation.risks?.length ?? 0) > 0 && (
              <>
                <div className="sub">What would invalidate this</div>
                <ul>
                  {explanation.risks!.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}

            {explanation.confidence !== undefined && (
              <div className="meta">Model confidence {(explanation.confidence * 100).toFixed(0)}%</div>
            )}

            <div className="disclaimer">{NOT_ADVICE}</div>
          </div>
        )}
      </div>

      <style jsx>{`
        .panel { display: flex; flex-direction: column; gap: 14px; padding: 14px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; width: 250px; flex-shrink: 0; max-height: 620px; overflow-y: auto; }
        .group { display: flex; flex-direction: column; gap: 7px; }
        .group-title { font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .toggle { display: flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .body { display: flex; flex-direction: column; gap: 5px; }
        .bias { font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 6px; align-self: flex-start; text-transform: capitalize; }
        .bias.gain { color: var(--gain); background: var(--gain-dim); }
        .bias.loss { color: var(--loss); background: var(--loss-dim); }
        .bias.warn { color: #f2b705; background: rgba(242, 183, 5, 0.12); }
        .bias.muted { color: var(--text-faint); background: var(--panel); }
        .meta { font-size: 10px; color: var(--text-faint); }
        .sub { font-size: 9.5px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-faint); margin-top: 5px; }
        .zone { display: flex; gap: 7px; align-items: baseline; font-size: 10.5px; font-variant-numeric: tabular-nums; }
        .zp { font-weight: 700; }
        .zp.gain { color: var(--gain); }
        .zp.loss { color: var(--loss); }
        .zt { color: var(--text-faint); line-height: 1.4; }
        .summary { font-size: 11.5px; line-height: 1.55; color: var(--text-muted); margin: 2px 0; }
        ul { margin: 0; padding-left: 15px; display: flex; flex-direction: column; gap: 3px; }
        li { font-size: 10.5px; line-height: 1.45; color: var(--text-muted); }
        .note { font-size: 10.5px; color: var(--text-faint); line-height: 1.45; }
        .err { font-size: 10.5px; color: var(--loss); line-height: 1.45; }
        .explain { background: var(--purple-dim); border: 1px solid rgba(125, 52, 220, 0.3); color: var(--purple); border-radius: 8px; padding: 7px 10px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .explain:disabled { opacity: 0.5; cursor: not-allowed; }
        .disclaimer { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--panel-border); font-size: 9.5px; color: var(--text-faint); line-height: 1.45; }
      `}</style>
    </div>
  );
}
