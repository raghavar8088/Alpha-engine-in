"use client";

/** Drawings, saved layouts and alerts (Phase 7).
 *
 * Controlled view only — the chart page owns state, drawing capture and the
 * alert evaluation loop.
 */

import { useState } from "react";
import { ChartAlert, ChartDrawing, ChartDrawingKind, ChartLayout } from "../../lib/api";

export type DrawingTool = ChartDrawingKind | null;

interface Props {
  // drawings
  activeTool: DrawingTool;
  onSelectTool: (tool: DrawingTool) => void;
  colors: string[];
  activeColor: string;
  onSelectColor: (color: string) => void;
  drawings: ChartDrawing[];
  onDeleteDrawing: (id: string) => void;
  pendingPoint: boolean;
  // layouts
  layouts: ChartLayout[];
  onSaveLayout: (name: string) => void;
  onApplyLayout: (layout: ChartLayout) => void;
  onDeleteLayout: (id: string) => void;
  // alerts
  alerts: ChartAlert[];
  onCreateAlert: (condition: "crosses_above" | "crosses_below", price: number, note: string) => void;
  onDeleteAlert: (id: string) => void;
  lastPrice: number | null;
  // multi-chart
  compareSymbols: string[];
  onRemoveCompare: (symbol: string) => void;
  canAddCompare: boolean;
  onAddCompare: () => void;
  disabled: boolean;
}

const TOOLS: { id: ChartDrawingKind; label: string; hint: string }[] = [
  { id: "trendline", label: "Trend line", hint: "Click two points on the chart" },
  { id: "horizontal", label: "Horizontal", hint: "Click one point" },
  { id: "rectangle", label: "Zone", hint: "Click two opposite corners" },
  { id: "fibonacci", label: "Fib", hint: "Click the swing low, then the swing high" },
  { id: "long_position", label: "Long", hint: "Click your entry — target and stop default to a 1:2 risk:reward, drag either to adjust" },
  { id: "short_position", label: "Short", hint: "Click your entry — target and stop default to a 1:2 risk:reward, drag either to adjust" },
  { id: "text", label: "Note", hint: "Click where the note goes" },
];

const KIND_LABEL: Record<ChartDrawingKind, string> = {
  trendline: "trendline", horizontal: "horizontal", rectangle: "zone",
  fibonacci: "fib", text: "note", long_position: "long", short_position: "short",
};

export default function WorkspacePanel({
  activeTool, onSelectTool, colors, activeColor, onSelectColor, drawings, onDeleteDrawing, pendingPoint,
  layouts, onSaveLayout, onApplyLayout, onDeleteLayout,
  alerts, onCreateAlert, onDeleteAlert, lastPrice,
  compareSymbols, onRemoveCompare, canAddCompare, onAddCompare, disabled,
}: Props) {
  const [layoutName, setLayoutName] = useState("");
  const [alertPrice, setAlertPrice] = useState("");
  const [alertCondition, setAlertCondition] = useState<"crosses_above" | "crosses_below">("crosses_above");
  const [alertNote, setAlertNote] = useState("");

  const submitAlert = () => {
    const price = Number(alertPrice);
    if (!Number.isFinite(price) || price <= 0) return;
    onCreateAlert(alertCondition, price, alertNote.trim());
    setAlertPrice("");
    setAlertNote("");
  };

  return (
    <div className="panel">
      <div className="group">
        <div className="group-title">Draw</div>
        <div className="tools">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              className={activeTool === t.id ? "tool active" : "tool"}
              disabled={disabled}
              onClick={() => onSelectTool(activeTool === t.id ? null : t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="swatches">
          {colors.map((c) => (
            <button
              key={c}
              className={activeColor === c ? "swatch active" : "swatch"}
              style={{ background: c }}
              disabled={disabled}
              onClick={() => onSelectColor(c)}
              title={`Draw in ${c}`}
              aria-label={`Draw in ${c}`}
            />
          ))}
        </div>
        {activeTool && (
          <div className="hint">
            {pendingPoint
              ? "Now click the second point."
              : TOOLS.find((t) => t.id === activeTool)?.hint}
          </div>
        )}
        {drawings.length > 0 && (
          <ul className="list">
            {drawings.map((d) => (
              <li key={d.drawing_id}>
                <span className="dk">{KIND_LABEL[d.kind] || d.kind}</span>
                <span className="dv">
                  {d.kind === "text" ? d.text || "note" : d.points.map((p) => p.price.toFixed(1)).join(" → ")}
                </span>
                <button className="x" onClick={() => onDeleteDrawing(d.drawing_id)} title="Delete">×</button>
              </li>
            ))}
          </ul>
        )}
        {drawings.length === 0 && <div className="hint">Nothing drawn on this symbol yet.</div>}
      </div>

      <div className="group">
        <div className="group-title">Layouts</div>
        <div className="row">
          <input
            placeholder="Layout name"
            value={layoutName}
            onChange={(e) => setLayoutName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && layoutName.trim()) {
                onSaveLayout(layoutName.trim());
                setLayoutName("");
              }
            }}
          />
          <button
            className="go"
            disabled={!layoutName.trim()}
            onClick={() => {
              onSaveLayout(layoutName.trim());
              setLayoutName("");
            }}
          >
            Save
          </button>
        </div>
        {layouts.length > 0 ? (
          <ul className="list">
            {layouts.map((l) => (
              <li key={l.layout_id}>
                <button className="apply" onClick={() => onApplyLayout(l)}>{l.name}</button>
                <span className="dv">{l.resolution}</span>
                <button className="x" onClick={() => onDeleteLayout(l.layout_id)} title="Delete">×</button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="hint">Saves the indicator set, timeframe and overlay toggles.</div>
        )}
      </div>

      <div className="group">
        <div className="group-title">Alerts</div>
        <div className="row">
          <select value={alertCondition} onChange={(e) => setAlertCondition(e.target.value as typeof alertCondition)}>
            <option value="crosses_above">Crosses above</option>
            <option value="crosses_below">Crosses below</option>
          </select>
        </div>
        <div className="row">
          <input
            type="number"
            placeholder={lastPrice ? lastPrice.toFixed(2) : "Price"}
            value={alertPrice}
            onChange={(e) => setAlertPrice(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitAlert()}
          />
          <button className="go" disabled={disabled || !alertPrice} onClick={submitAlert}>Add</button>
        </div>
        <input
          className="note-input"
          placeholder="Note (optional)"
          value={alertNote}
          onChange={(e) => setAlertNote(e.target.value)}
        />

        {alerts.length > 0 && (
          <ul className="list">
            {alerts.map((a) => (
              <li key={a.alert_id}>
                <span className={a.status === "TRIGGERED" ? "st fired" : "st"}>
                  {a.status === "TRIGGERED" ? "✓" : "●"}
                </span>
                <span className="dv">
                  {a.condition === "crosses_above" ? "↑" : "↓"} {a.price}
                </span>
                <button className="x" onClick={() => onDeleteAlert(a.alert_id)} title="Delete">×</button>
              </li>
            ))}
          </ul>
        )}
        <div className="hint">
          Checked live while this chart is open. This app has no outbound notification channel yet
          (notification-service is an empty stub), so alerts show in-app only — they will not reach you
          with the tab closed.
        </div>
      </div>

      <div className="group">
        <div className="group-title">Compare</div>
        <button className="go wide" disabled={!canAddCompare} onClick={onAddCompare}>
          + Add current symbol
        </button>
        {compareSymbols.length > 0 ? (
          <ul className="list">
            {compareSymbols.map((s) => (
              <li key={s}>
                <span className="dv">{s}</span>
                <button className="x" onClick={() => onRemoveCompare(s)} title="Remove">×</button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="hint">Add up to 4 symbols to see them side by side.</div>
        )}
      </div>

      <style jsx>{`
        .panel { display: flex; flex-direction: column; gap: 14px; padding: 14px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; width: 236px; flex-shrink: 0; max-height: 620px; overflow-y: auto; }
        .group { display: flex; flex-direction: column; gap: 7px; }
        .group-title { font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .tools { display: flex; flex-wrap: wrap; gap: 4px; }
        .tool { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 7px; padding: 5px 8px; font-size: 11px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .tool.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.35); color: var(--purple); }
        .tool:disabled { opacity: 0.45; cursor: not-allowed; }
        .hint { font-size: 10px; color: var(--text-faint); line-height: 1.45; }
        .swatches { display: flex; gap: 5px; margin-top: 6px; }
        .swatch { width: 16px; height: 16px; border-radius: 50%; border: 1px solid var(--panel-border); cursor: pointer; padding: 0; }
        .swatch.active { box-shadow: 0 0 0 2px var(--canvas), 0 0 0 3px currentColor; }
        .swatch:disabled { opacity: 0.4; cursor: default; }
        .row { display: flex; gap: 5px; }
        .row input, .row select, .note-input { flex: 1; min-width: 0; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 7px; padding: 5px 7px; font-size: 11px; }
        .go { background: var(--purple-dim); border: 1px solid rgba(125, 52, 220, 0.3); color: var(--purple); border-radius: 7px; padding: 5px 9px; font-size: 11px; font-weight: 700; cursor: pointer; flex-shrink: 0; }
        .go:disabled { opacity: 0.45; cursor: not-allowed; }
        .go.wide { width: 100%; }
        .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
        .list li { display: flex; align-items: center; gap: 6px; font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--text-muted); }
        .dk { font-weight: 700; text-transform: capitalize; font-size: 9.5px; color: var(--text-faint); min-width: 54px; }
        .dv { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .apply { flex: 1; text-align: left; background: none; border: none; color: var(--purple); font-size: 10.5px; font-weight: 700; cursor: pointer; padding: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .st { color: var(--text-faint); font-size: 9px; }
        .st.fired { color: var(--gain); }
        .x { background: none; border: none; color: var(--text-faint); font-size: 14px; line-height: 1; cursor: pointer; padding: 0 2px; }
        .x:hover { color: var(--loss); }
      `}</style>
    </div>
  );
}
