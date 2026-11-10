"use client";

// AI final gate (2026-11-10). Claude reviews every new position this module opens; each one it approves becomes a
// separate AI position with its own ID and timestamps (backend: app/services/ai_gate.py, /api/ai-gate). The module's
// own positions are unchanged, so the panel compares the AI-approved book with everything the module took.
import { Fragment, useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type Module = "intraday" | "commodity" | "gold" | "premium";
type Stat = { trades: number; wins: number; win_rate: number | null; net: number; avg: number | null };
type Summary = {
  enabled: boolean; configured: boolean; model: string; daily_max?: number; why_off?: string; since?: string | null;
  decisions?: Record<string, number>; today?: Record<string, number>; cost_usd?: number; cost_today_usd?: number;
  control?: Record<string, Stat>; approved?: Record<string, Stat>; skipped?: Record<string, Stat>; open_ai_positions?: number;
};
type AIPosition = {
  ai_position_id: string; parent_id: string; strategy_name?: string; strategy_id?: string; symbol: string; side: string;
  entry_price?: number | null; exit_price?: number | null; status: string; pnl?: number | null; currency?: string;
  signal_time?: string; approved_at?: string; closed_at?: string | null; p_profit?: number; reasons?: string[];
  exit_reason?: string | null;
};

const POLL_MS = 60_000;

function money(x: number | null | undefined, ccy = "INR"): string {
  if (x == null) return "—";
  const sign = x > 0 ? "+" : x < 0 ? "−" : "";
  const abs = Math.abs(x);
  return ccy === "USD"
    ? `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
    : `${sign}₹${Math.round(abs).toLocaleString("en-IN")}`;
}

function ist(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

const tone = (x: number | null | undefined) => (x == null || x === 0 ? "" : x > 0 ? "ag-pos" : "ag-neg");

function Row({ label, s, ccy }: { label: string; s?: Stat; ccy: string }) {
  return (
    <tr>
      <td className="ag-left">{label}</td>
      <td>{s ? s.trades.toLocaleString("en-IN") : "0"}</td>
      <td>{s?.win_rate == null ? "—" : `${s.win_rate.toFixed(1)}%`}</td>
      <td className={tone(s?.net)}>{s ? money(s.net, ccy) : "—"}</td>
      <td className={tone(s?.avg)}>{s?.avg == null ? "—" : money(s.avg, ccy)}</td>
    </tr>
  );
}

export default function AIGatePanel({ module }: { module: Module }) {
  const [sum, setSum] = useState<Summary | null>(null);
  const [rows, setRows] = useState<AIPosition[]>([]);
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const s: Summary = await apiFetch(`/api/ai-gate/summary?module=${module}`);
      setSum(s);
      setMissing(false);
      if (s.enabled) {
        const p = await apiFetch(`/api/ai-gate/positions?module=${module}&limit=100`);
        setRows(p.positions ?? []);
      }
    } catch {
      setMissing(true);
    }
  }, [module]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const ccys = Array.from(new Set([...Object.keys(sum?.control ?? {}), ...Object.keys(sum?.approved ?? {}), ...Object.keys(sum?.skipped ?? {})]));
  if (!ccys.length) ccys.push(module === "gold" ? "USD" : "INR");
  const today = sum?.today ?? {};
  const reviewed = (today.take ?? 0) + (today.skip ?? 0);
  const state = missing
    ? { label: "Not running yet", cls: "ag-pill-muted" }
    : !sum ? { label: "Loading", cls: "ag-pill-muted" }
    : !sum.enabled ? { label: "Off", cls: "ag-pill-muted" }
    : !sum.configured ? { label: "No API key", cls: "ag-pill-warn" }
    : { label: `On · ${sum.model}`, cls: "ag-pill-on" };

  return (
    <details className="ag-card" open>
      <summary className="ag-head">
        <span className="ag-title">AI final gate</span>
        <span className={`ag-pill ${state.cls}`}>{state.label}</span>
        <span className="ag-sub">A/B paper test: the module&apos;s own positions are unchanged</span>
      </summary>
      {missing ? (
        <p className="ag-note">
          The AI gate is not running on the server yet. It needs the backend update and an Anthropic API key on the server.
        </p>
      ) : sum && !sum.enabled ? (
        <p className="ag-note">The AI gate is switched off on the server{sum.why_off ? `: ${sum.why_off}` : "."}</p>
      ) : (
        <>
          <p className="ag-note">
            Claude reviews every new position this module opens, using only data up to its signal, and approves or skips it.
            Each approval becomes an AI position with its own ID and timestamps.
            {sum && !sum.configured ? " No Anthropic API key is set on the server, so nothing is approved yet: the gate fails closed." : ""}
          </p>
          <div className="ag-scroll">
            <table className="ag-table">
              <thead>
                <tr><th className="ag-left">Since the gate started{sum?.since ? ` (${ist(sum.since)})` : ""}</th><th>Closed</th><th>Win %</th><th>Net P&amp;L</th><th>Avg a trade</th></tr>
              </thead>
              <tbody>
                {ccys.map((c) => (
                  <Fragment key={c}>
                    <Row key={`c${c}`} label={`All module positions${ccys.length > 1 ? ` (${c})` : ""}`} s={sum?.control?.[c]} ccy={c} />
                    <Row key={`a${c}`} label="AI approved (AI positions)" s={sum?.approved?.[c]} ccy={c} />
                    <Row key={`s${c}`} label="AI skipped" s={sum?.skipped?.[c]} ccy={c} />
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <p className="ag-meta">
            Today: {reviewed} reviewed{sum?.daily_max ? ` of ${sum.daily_max} allowed` : ""} · {today.take ?? 0} approved ·{" "}
            {today.skip ?? 0} skipped · {today.not_reviewed ?? 0} not reviewed · AI cost ${(sum?.cost_today_usd ?? 0).toFixed(2)} today,
            ${(sum?.cost_usd ?? 0).toFixed(2)} in all · {sum?.open_ai_positions ?? 0} AI positions open
          </p>
          <details className="ag-list">
            <summary>{`AI positions (${rows.length}${rows.length >= 100 ? ", newest 100" : ""})`}</summary>
            {rows.length === 0 ? (
              <p className="ag-note">No AI position yet.</p>
            ) : (
              <div className="ag-scroll ag-tall">
                <table className="ag-table">
                  <thead>
                    <tr>
                      <th className="ag-left">AI position ID</th><th>Approved</th><th>Signal</th><th className="ag-left">Strategy</th>
                      <th className="ag-left">Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Status</th><th>P&amp;L</th>
                      <th>P(profit)</th><th className="ag-left">Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.ai_position_id}>
                        <td className="ag-left ag-id" title={`Module position ${r.parent_id}`}>{r.ai_position_id}</td>
                        <td>{ist(r.approved_at)}</td>
                        <td>{ist(r.signal_time)}</td>
                        <td className="ag-left">{r.strategy_name ?? r.strategy_id}</td>
                        <td className="ag-left">{r.symbol}</td>
                        <td>{r.side === "BUY" ? "Long" : "Short"}</td>
                        <td>{r.entry_price == null ? "—" : r.entry_price.toLocaleString("en-IN", { maximumFractionDigits: 4 })}</td>
                        <td>{r.exit_price == null ? "—" : r.exit_price.toLocaleString("en-IN", { maximumFractionDigits: 4 })}</td>
                        <td>{r.status === "CLOSED" ? (r.exit_reason ?? "Closed") : r.status === "OPEN" ? "Open" : "Void"}</td>
                        <td className={tone(r.pnl)}>{money(r.pnl, r.currency)}</td>
                        <td>{r.p_profit == null ? "—" : `${Math.round(r.p_profit * 100)}%`}</td>
                        <td className="ag-left ag-why">{(r.reasons ?? [])[0] ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </details>
        </>
      )}
      <style jsx>{`
        .ag-card { margin: 0 0 16px; padding: 14px 16px; border-radius: 14px; background: var(--panel); border: 1px solid var(--panel-border); }
        .ag-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; cursor: pointer; list-style: none; }
        .ag-head::-webkit-details-marker { display: none; }
        .ag-title { font-size: 15px; font-weight: 800; color: var(--text); }
        .ag-sub { font-size: 12px; color: var(--text-muted); }
        .ag-pill { font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--panel-border); color: var(--text-muted); }
        .ag-pill-on { color: var(--gain); border-color: var(--gain); }
        .ag-pill-warn { color: var(--warn); border-color: var(--warn); }
        .ag-note { margin: 10px 0 0; font-size: 12.5px; line-height: 1.55; color: var(--text-muted); max-width: 980px; }
        .ag-meta { margin: 8px 0 0; font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .ag-scroll { overflow-x: auto; margin-top: 10px; }
        .ag-tall { max-height: 420px; overflow-y: auto; }
        .ag-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .ag-table th { text-align: right; font-size: 10.5px; font-weight: 800; color: var(--text-muted); text-transform: uppercase;
          padding: 6px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .ag-table td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; color: var(--text); }
        .ag-left { text-align: left !important; }
        .ag-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
        .ag-why { white-space: normal !important; min-width: 220px; color: var(--text-muted) !important; }
        .ag-pos { color: var(--gain) !important; }
        .ag-neg { color: var(--loss) !important; }
        .ag-list { margin-top: 10px; }
        .ag-list summary { cursor: pointer; font-size: 12.5px; font-weight: 800; color: var(--purple); }
      `}</style>
    </details>
  );
}
