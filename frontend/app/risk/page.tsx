"use client";

import { useEffect, useState } from "react";
import GlassPanel from "@/components/GlassPanel";
import PageHeader from "@/components/PageHeader";
import { fetchRiskConfig, fetchRiskStatus, RiskLimits, RiskStatus, updateRiskConfig } from "@/lib/api";

const inr = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const LIMIT_FIELDS: { key: keyof RiskLimits; label: string; suffix: string }[] = [
  { key: "daily_loss_limit_pct", label: "Daily Loss Limit", suffix: "%" },
  { key: "max_drawdown_pct", label: "Max Drawdown", suffix: "%" },
  { key: "max_open_positions", label: "Max Open Positions", suffix: "" },
  { key: "max_exposure_pct", label: "Max Exposure", suffix: "%" },
  { key: "max_sector_exposure_pct", label: "Max Sector Exposure", suffix: "%" },
  { key: "max_portfolio_heat_pct", label: "Max Portfolio Heat", suffix: "%" },
];

export default function RiskPage() {
  const [status, setStatus] = useState<RiskStatus | null>(null);
  const [limits, setLimits] = useState<RiskLimits | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = () => {
    fetchRiskStatus().then(setStatus).catch((e) => setError(e instanceof Error ? e.message : "Failed to load risk status"));
    fetchRiskConfig().then((l) => {
      setLimits(l);
      setDraft(Object.fromEntries(Object.entries(l).map(([k, v]) => [k, String(v)])));
    });
  };

  useEffect(load, []);

  const save = async () => {
    setSaving(true);
    try {
      const payload: Partial<RiskLimits> = {};
      for (const f of LIMIT_FIELDS) {
        const raw = draft[f.key];
        if (raw !== undefined && raw !== "") payload[f.key] = Number(raw) as never;
      }
      const updated = await updateRiskConfig(payload);
      setLimits(updated);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save risk limits");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader crumb="Risk" title="Risk" subtitle="Kill-switch status and configurable risk limits for order placement and strategy runs." />

      {error && (
        <GlassPanel>
          <div style={{ padding: 20, color: "var(--loss)" }}>{error}</div>
        </GlassPanel>
      )}

      {status && (
        <GlassPanel
          title="Kill-Switch Status"
          note={status.kill_switch_active ? "ACTIVE — order placement halted" : "clear"}
        >
          <div className={`kill-banner ${status.kill_switch_active ? "active" : "clear"}`}>
            <div className="kill-dot" />
            <div>
              <div className="kill-title">
                {status.kill_switch_active ? "Kill-switch ACTIVE" : "No limits breached"}
              </div>
              {status.kill_switch_reasons.length > 0 && (
                <div className="kill-reasons">{status.kill_switch_reasons.join(", ")}</div>
              )}
            </div>
          </div>
          <div className="status-grid">
            <div className="s-tile">
              <div className="s-label">Total Capital</div>
              <div className="s-value">{inr(status.total_capital)}</div>
            </div>
            <div className="s-tile">
              <div className="s-label">Day Start Equity</div>
              <div className="s-value">{inr(status.day_start_equity)}</div>
            </div>
            <div className="s-tile">
              <div className="s-label">Day P&amp;L</div>
              <div className={`s-value ${status.day_pnl >= 0 ? "up" : "down"}`}>
                {status.day_pnl >= 0 ? "+" : ""}
                {inr(status.day_pnl)}
                {status.day_pnl_pct !== null ? ` (${status.day_pnl_pct >= 0 ? "+" : ""}${status.day_pnl_pct}%)` : ""}
              </div>
            </div>
            <div className="s-tile">
              <div className="s-label">Open Positions</div>
              <div className="s-value">
                {status.open_positions_count} / {status.limits.max_open_positions}
              </div>
            </div>
          </div>
          <div className="status-note">{status.note}</div>
        </GlassPanel>
      )}

      {limits && (
        <GlassPanel title="Risk Limits" note="applies to new order placement and future strategy runs">
          <div className="limits-form">
            {LIMIT_FIELDS.map((f) => (
              <label key={f.key}>
                {f.label}
                <div className="input-row">
                  <input
                    type="number"
                    value={draft[f.key] ?? ""}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                  />
                  {f.suffix && <span className="suffix">{f.suffix}</span>}
                </div>
              </label>
            ))}
            <button onClick={save} disabled={saving}>
              {saving ? "Saving..." : "Save limits"}
            </button>
          </div>
        </GlassPanel>
      )}

      <style jsx>{`
        .kill-banner {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 16px 20px;
          border-bottom: 1px solid var(--panel-border);
        }
        .kill-dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .kill-banner.clear .kill-dot {
          background: var(--gain);
          box-shadow: 0 0 10px var(--gain);
        }
        .kill-banner.active .kill-dot {
          background: var(--loss);
          box-shadow: 0 0 10px var(--loss);
        }
        .kill-title {
          font-weight: 700;
          font-size: 14px;
        }
        .kill-reasons {
          margin-top: 3px;
          font-size: 12px;
          color: var(--text-muted);
        }
        .status-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 14px;
          padding: 18px 20px;
        }
        .s-label {
          font-size: 10.5px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-faint);
        }
        .s-value {
          margin-top: 6px;
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 16px;
          font-weight: 600;
        }
        .s-value.up {
          color: var(--gain);
        }
        .s-value.down {
          color: var(--loss);
        }
        .status-note {
          padding: 0 20px 18px;
          font-size: 11.5px;
          color: var(--text-faint);
          line-height: 1.5;
        }
        .limits-form {
          display: flex;
          flex-wrap: wrap;
          gap: 16px;
          padding: 18px 20px;
          align-items: flex-end;
        }
        label {
          display: flex;
          flex-direction: column;
          gap: 6px;
          font-size: 11.5px;
          font-weight: 600;
          color: var(--text-muted);
          letter-spacing: 0.03em;
        }
        .input-row {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        input {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 9px 12px;
          font-size: 13.5px;
          width: 100px;
        }
        .suffix {
          color: var(--text-faint);
          font-size: 12px;
        }
        button {
          background: linear-gradient(145deg, var(--accent), var(--accent-hover));
          color: #241404;
          font-weight: 700;
          font-size: 13.5px;
          border: none;
          border-radius: 10px;
          padding: 11px 22px;
          cursor: pointer;
          height: fit-content;
        }
        button:disabled {
          opacity: 0.55;
          cursor: default;
        }
      `}</style>
    </div>
  );
}
