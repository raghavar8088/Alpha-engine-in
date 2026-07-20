"use client";

/** Cross-module overlay controls (Phase 5).
 *
 * Controlled view only — the chart page owns all state and does the drawing.
 * Each overlay is opt-in; option-chain context especially, because it is the
 * one item here that costs a Dhan call.
 */

import {
  ChartBacktestRun,
  ChartCallOverlay,
  ChartOptionContext,
  ChartPositionOverlay,
} from "../../lib/api";

export interface OverlayConfig {
  positions: boolean;
  calls: boolean;
  backtest: boolean;
  optionContext: boolean;
}

export const DEFAULT_OVERLAYS: OverlayConfig = {
  positions: true,
  calls: true,
  backtest: false,
  optionContext: false,
};

export interface ReplayState {
  active: boolean;
  playing: boolean;
  index: number;
}

interface Props {
  config: OverlayConfig;
  onChange: (next: OverlayConfig) => void;
  positions: ChartPositionOverlay[];
  calls: ChartCallOverlay[];
  runs: ChartBacktestRun[];
  selectedRunId: string | null;
  onSelectRun: (id: string | null) => void;
  tradeCount: number;
  replay: ReplayState;
  onReplayChange: (next: ReplayState) => void;
  optionContext: ChartOptionContext | null;
  optionContextLoading: boolean;
  optionContextError: string | null;
  /** Option context is only meaningful for an index underlying. */
  optionContextEligible: boolean;
}

const money = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

export default function OverlayPanel({
  config, onChange, positions, calls, runs, selectedRunId, onSelectRun,
  tradeCount, replay, onReplayChange, optionContext, optionContextLoading,
  optionContextError, optionContextEligible,
}: Props) {
  const set = (patch: Partial<OverlayConfig>) => onChange({ ...config, ...patch });

  const stepTo = (index: number) =>
    onReplayChange({ ...replay, index: Math.max(0, Math.min(tradeCount, index)) });

  return (
    <div className="panel">
      <div className="group">
        <div className="group-title">My data on this chart</div>

        <label className="toggle">
          <input type="checkbox" checked={config.positions} onChange={(e) => set({ positions: e.target.checked })} />
          <span>Open positions {positions.length > 0 && <b>({positions.length})</b>}</span>
        </label>
        {config.positions && positions.length > 0 && (
          <ul className="list">
            {positions.map((p) => (
              <li key={`${p.source}-${p.position_id}`}>
                <span className={p.side === "BUY" ? "side long" : "side short"}>{p.side === "BUY" ? "LONG" : "SHORT"}</span>
                <span className="qty">{p.quantity}</span>
                <span className="at">@ {money(p.entry_price)}</span>
                {p.unrealized_pnl !== null && (
                  <span className={p.unrealized_pnl >= 0 ? "pnl gain" : "pnl loss"}>
                    {p.unrealized_pnl >= 0 ? "+" : ""}{money(p.unrealized_pnl)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {config.positions && positions.length === 0 && <div className="empty-note">No open position here.</div>}

        <label className="toggle">
          <input type="checkbox" checked={config.calls} onChange={(e) => set({ calls: e.target.checked })} />
          <span>Trading calls {calls.length > 0 && <b>({calls.length})</b>}</span>
        </label>
        {config.calls && calls.length > 0 && (
          <ul className="list">
            {calls.map((c) => (
              <li key={c.call_id}>
                <span className={c.side === "BUY" ? "side long" : "side short"}>{c.side}</span>
                <span className="at">E {money(c.entry_price)}</span>
                <span className="t">T {money(c.target)}</span>
                <span className="sl">SL {money(c.stoploss)}</span>
              </li>
            ))}
          </ul>
        )}
        {config.calls && calls.length === 0 && <div className="empty-note">No active call for this symbol.</div>}
      </div>

      <div className="group">
        <div className="group-title">Backtest trades</div>
        <label className="toggle">
          <input type="checkbox" checked={config.backtest} onChange={(e) => set({ backtest: e.target.checked })} />
          <span>Show entry / exit markers</span>
        </label>
        {config.backtest && (
          <>
            {runs.length === 0 ? (
              <div className="empty-note">No stored backtest for this symbol yet — run one from the Backtesting page.</div>
            ) : (
              <select value={selectedRunId ?? ""} onChange={(e) => onSelectRun(e.target.value || null)}>
                <option value="">Select a run…</option>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.strategy_id} · {r.timeframe} · {r.total_return_pct === null ? "–" : `${r.total_return_pct.toFixed(1)}%`}
                  </option>
                ))}
              </select>
            )}

            {selectedRunId && tradeCount > 0 && (
              <div className="replay">
                <div className="replay-head">
                  <span>Replay</span>
                  <span className="counter">{replay.index} / {tradeCount}</span>
                </div>
                <div className="replay-btns">
                  <button title="Reset" onClick={() => onReplayChange({ active: true, playing: false, index: 0 })}>⏮</button>
                  <button title="Step back" onClick={() => stepTo(replay.index - 1)}>◀</button>
                  <button
                    title={replay.playing ? "Pause" : "Play"}
                    className="play"
                    onClick={() => onReplayChange({ ...replay, active: true, playing: !replay.playing })}
                  >
                    {replay.playing ? "❚❚" : "▶"}
                  </button>
                  <button title="Step forward" onClick={() => stepTo(replay.index + 1)}>▶|</button>
                  <button
                    title="Show all trades"
                    onClick={() => onReplayChange({ active: false, playing: false, index: tradeCount })}
                  >
                    All
                  </button>
                </div>
                <div className="replay-note">
                  {replay.active
                    ? "Only trades up to this point are drawn."
                    : "All trades shown."}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="group">
        <div className="group-title">Option-chain context</div>
        {!optionContextEligible ? (
          <div className="empty-note">Available for index underlyings (NIFTY, BANKNIFTY, …).</div>
        ) : (
          <>
            <label className="toggle">
              <input
                type="checkbox"
                checked={config.optionContext}
                onChange={(e) => set({ optionContext: e.target.checked })}
              />
              <span>Load max pain / OI / PCR</span>
            </label>
            <div className="empty-note">Costs one broker call — off by default.</div>
            {config.optionContext && optionContextLoading && <div className="empty-note">Loading…</div>}
            {config.optionContext && optionContextError && <div className="err">{optionContextError}</div>}
            {config.optionContext && optionContext?.available && (
              <div className="oc">
                <div className="oc-row"><span>Expiry</span><b>{optionContext.expiry}</b></div>
                <div className="oc-row"><span>Spot</span><b>{money(optionContext.spot)}</b></div>
                <div className="oc-row"><span>Max pain</span><b>{money(optionContext.max_pain)}</b></div>
                <div className="oc-row"><span>PCR (OI)</span><b>{optionContext.pcr_oi ?? "–"}</b></div>
                <div className="oc-sub">Heaviest call OI</div>
                {(optionContext.top_call_oi || []).map((s) => (
                  <div key={`c${s.strike}`} className="oc-row"><span>{s.strike}</span><b>{money(s.oi)}</b></div>
                ))}
                <div className="oc-sub">Heaviest put OI</div>
                {(optionContext.top_put_oi || []).map((s) => (
                  <div key={`p${s.strike}`} className="oc-row"><span>{s.strike}</span><b>{money(s.oi)}</b></div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <style jsx>{`
        .panel { display: flex; flex-direction: column; gap: 14px; padding: 14px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; width: 236px; flex-shrink: 0; max-height: 620px; overflow-y: auto; }
        .group { display: flex; flex-direction: column; gap: 7px; }
        .group-title { font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .toggle { display: flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .empty-note { font-size: 10.5px; color: var(--text-faint); padding-left: 21px; line-height: 1.45; }
        .err { font-size: 10.5px; color: var(--loss); padding-left: 21px; line-height: 1.45; }
        .list { list-style: none; margin: 0; padding: 0 0 0 21px; display: flex; flex-direction: column; gap: 4px; }
        .list li { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--text-muted); }
        .side { font-weight: 800; font-size: 9.5px; padding: 1px 5px; border-radius: 4px; }
        .side.long { color: var(--gain); background: var(--gain-dim); }
        .side.short { color: var(--loss); background: var(--loss-dim); }
        .t { color: var(--gain); }
        .sl { color: var(--loss); }
        .pnl.gain { color: var(--gain); font-weight: 700; }
        .pnl.loss { color: var(--loss); font-weight: 700; }
        select { margin-left: 21px; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 7px; padding: 5px 7px; font-size: 11px; max-width: 190px; }
        .replay { margin-left: 21px; display: flex; flex-direction: column; gap: 6px; }
        .replay-head { display: flex; justify-content: space-between; font-size: 10.5px; font-weight: 700; color: var(--text-muted); }
        .counter { font-variant-numeric: tabular-nums; }
        .replay-btns { display: flex; gap: 4px; }
        .replay-btns button { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 6px; padding: 4px 7px; font-size: 11px; color: var(--text-muted); cursor: pointer; }
        .replay-btns button:hover { color: var(--text); }
        .replay-btns .play { color: var(--purple); font-weight: 800; }
        .replay-note { font-size: 10px; color: var(--text-faint); line-height: 1.4; }
        .oc { margin-left: 21px; display: flex; flex-direction: column; gap: 3px; }
        .oc-row { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .oc-row b { color: var(--text); }
        .oc-sub { font-size: 9.5px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-faint); margin-top: 5px; }
      `}</style>
    </div>
  );
}
