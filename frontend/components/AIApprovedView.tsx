"use client";

// The AI Approved tab of a module (2026-11-10). Claude reviews every new position the module opens; each one it approves
// is recorded as a separate AI position with its own ID and timestamps (backend: app/services/ai_gate.py, /api/ai-gate).
// The module's own paper trading is untouched: the gate only reads its positions. This view shows the AI-approved
// positions, a strategy leaderboard, the AI book against the module day by day, and every AI decision.
import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";
import PageHeader from "./PageHeader";
import GlassPanel from "./GlassPanel";
import { apiFetch } from "../lib/api";

export type AIModule = "intraday" | "commodity" | "gold" | "premium";
const MOD: Record<AIModule, { label: string; href: string }> = {
  intraday: { label: "Intraday Stocks", href: "/intraday-stocks" },
  commodity: { label: "Commodity Trading", href: "/commodity" },
  gold: { label: "Gold Desk", href: "/gold-desk" },
  premium: { label: "Premium Strategies", href: "/premium-strategies" },
};

type Stat = { trades: number; wins: number; win_rate: number | null; net: number; avg: number | null };
type Summary = {
  enabled: boolean; configured: boolean; model: string; daily_max?: number; why_off?: string; since?: string | null;
  decisions?: Record<string, number>; today?: Record<string, number>; cost_usd?: number; cost_today_usd?: number;
  control?: Record<string, Stat>; approved?: Record<string, Stat>; skipped?: Record<string, Stat>; open_ai_positions?: number;
};
type Pos = {
  ai_position_id: string; parent_id: string; strategy_name?: string; strategy_id?: string; symbol: string; side: string;
  entry_price?: number | null; stop?: number | null; target?: number | null; exit_price?: number | null; status: string;
  pnl?: number | null; currency?: string; move_pct?: number | null; signal_time?: string; approved_at?: string;
  closed_at?: string | null; exit_reason?: string | null; p_profit?: number; confidence?: string; reasons?: string[];
  main_risk?: string; market?: string;
};
type LbRow = {
  rank: number; strategy_id: string; strategy_name: string; currency: string; reviewed: number; approved: number;
  skipped: number; not_reviewed: number; approval_rate: number | null; ai_open: number; ai_trades: number;
  ai_win_rate: number | null; ai_net: number; ai_avg: number | null; module_trades: number; module_win_rate: number | null;
  module_net: number; module_avg: number | null;
};
type DayRow = {
  day: string; currency: string; ai_trades: number; ai_win_rate: number | null; ai_net: number; module_trades: number;
  module_win_rate: number | null; module_net: number;
};
type Decision = {
  _id: string; parent_id: string; strategy_name?: string; strategy_id?: string; symbol: string; side: string; entry?: number;
  decision: string; why?: string; p_profit?: number; confidence?: string; reasons?: string[]; main_risk?: string;
  ai_position_id?: string; seen_at?: string; latency_ms?: number;
};
type View = "open" | "closed" | "leaderboard" | "daily" | "decisions";

const POLL_MS = 60_000;

function money(x: number | null | undefined, ccy = "INR"): string {
  if (x == null) return "—";
  const sign = x > 0 ? "+" : x < 0 ? "−" : "";
  const abs = Math.abs(x);
  return ccy === "USD"
    ? `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
    : `${sign}₹${Math.round(abs).toLocaleString("en-IN")}`;
}

function ist(iso?: string | null, withDay = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false,
    ...(withDay ? { day: "numeric", month: "short" } : {}),
  });
}

const dayLabel = (iso: string) => new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short" });
const px = (x?: number | null) => (x == null ? "—" : x.toLocaleString("en-IN", { maximumFractionDigits: 4 }));
const pctv = (x?: number | null, d = 1) => (x == null ? "—" : `${x.toFixed(d)}%`);
const tone = (x?: number | null) => (x == null || x === 0 ? "" : x > 0 ? "av-pos" : "av-neg");
const DEC_LABEL: Record<string, string> = { take: "Approved", skip: "Skipped", not_reviewed: "Not reviewed", pending: "Reviewing" };

function Tile({ label, value, sub, cls = "" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="av-tile">
      <span className="av-tile-label">{label}</span>
      <span className={`av-tile-val ${cls}`}>{value}</span>
      {sub && <span className="av-tile-sub">{sub}</span>}
      <style jsx>{`
        .av-tile { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px;
          background: var(--canvas-soft); border: 1px solid var(--panel-border); min-width: 0; }
        .av-tile-label { font-size: 11px; font-weight: 700; color: var(--text-muted); }
        .av-tile-val { font-size: 19px; font-weight: 800; color: var(--text); font-variant-numeric: tabular-nums; }
        .av-tile-sub { font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .av-pos { color: var(--gain); }
        .av-neg { color: var(--loss); }
      `}</style>
    </div>
  );
}

const statLine = (s?: Stat, ccy = "INR") =>
  s && s.trades ? `${s.trades} closed · ${pctv(s.win_rate)} won · avg ${money(s.avg, ccy)}` : "no closed positions yet";

export default function AIApprovedView({ module }: { module: AIModule }) {
  const m = MOD[module];
  const [sum, setSum] = useState<Summary | null>(null);
  const [positions, setPositions] = useState<Pos[]>([]);
  const [board, setBoard] = useState<LbRow[]>([]);
  const [days, setDays] = useState<DayRow[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [decFilter, setDecFilter] = useState<string>("");
  const [view, setView] = useState<View>("open");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const s: Summary = await apiFetch(`/api/ai-gate/summary?module=${module}`);
      setSum(s);
      setMissing(false);
      if (s.enabled) {
        const [p, lb, dd, dec] = await Promise.all([
          apiFetch(`/api/ai-gate/positions?module=${module}&limit=500`),
          apiFetch(`/api/ai-gate/leaderboard?module=${module}`),
          apiFetch(`/api/ai-gate/daily?module=${module}`),
          apiFetch(`/api/ai-gate/decisions?module=${module}&limit=300${decFilter ? `&decision=${decFilter}` : ""}`),
        ]);
        setPositions(p.positions ?? []);
        setBoard(lb.rows ?? []);
        setDays(dd.rows ?? []);
        setDecisions(dec.decisions ?? []);
      }
    } catch {
      setMissing(true);
    } finally {
      setBusy(false);
    }
  }, [module, decFilter]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const open = positions.filter((p) => p.status === "OPEN");
  const closed = positions.filter((p) => p.status !== "OPEN");
  const ccys = Array.from(new Set([...Object.keys(sum?.approved ?? {}), ...Object.keys(sum?.control ?? {}), ...Object.keys(sum?.skipped ?? {})]));
  if (!ccys.length) ccys.push(module === "gold" ? "USD" : "INR");
  const today = sum?.today ?? {};
  const reviewedToday = (today.take ?? 0) + (today.skip ?? 0);
  const state = missing
    ? { label: "Not running yet", cls: "av-pill-muted" }
    : !sum ? { label: "Loading", cls: "av-pill-muted" }
    : !sum.enabled ? { label: "Off", cls: "av-pill-muted" }
    : !sum.configured ? { label: "No API key", cls: "av-pill-warn" }
    : { label: `AI gate on · ${sum.model}`, cls: "av-pill-on" };

  const VIEWS: { id: View; label: string }[] = [
    { id: "open", label: `Open AI positions · ${open.length}` },
    { id: "closed", label: `Closed AI positions · ${closed.length}` },
    { id: "leaderboard", label: `Strategy leaderboard · ${board.length}` },
    { id: "daily", label: "Day by day" },
    { id: "decisions", label: "AI decisions" },
  ];

  return (
    <div className="page">
      <Link className="av-back" href={m.href}>← {m.label}</Link>
      <PageHeader
        crumb={`${m.label} / AI Approved`}
        title="AI Approved"
        onRefresh={load}
        refreshing={busy}
        subtitle={`Every position ${m.label} opens is reviewed by Claude before it can join this book. The ones it approves are recorded here as AI positions, each with its own AI position ID and timestamps, so their performance can be measured against everything the module took.`}
        actions={<span className={`av-pill ${state.cls}`}>{state.label}</span>}
      />

      <div className="av-note" role="note">
        {`${m.label}'s paper trading continues exactly as before: the AI gate only reads the module's positions after they open, and never blocks, delays or changes them. Paper only.`}
      </div>

      {missing ? (
        <GlassPanel title="Not running on the server yet">
          <p className="av-p">
            The AI gate is built and pushed, but the server has not been updated yet. It also needs an Anthropic API key on the server.
            Until then no position is reviewed and this tab stays empty; {m.label} trades as usual.
          </p>
        </GlassPanel>
      ) : sum && !sum.enabled ? (
        <GlassPanel title="The AI gate is switched off on the server">
          <p className="av-p">{sum.why_off ?? "AI_GATE is set to off."} {m.label} trades as usual.</p>
        </GlassPanel>
      ) : (
        <>
          {sum && !sum.configured && (
            <div className="av-warn">No Anthropic API key is set on the server, so nothing can be approved yet: the gate fails closed and records each position as not reviewed.</div>
          )}
          {ccys.map((c) => (
            <div key={c} className="av-tiles">
              <Tile label={`AI-approved book · net P&L${ccys.length > 1 ? ` (${c})` : ""}`} value={money(sum?.approved?.[c]?.net ?? 0, c)}
                    sub={statLine(sum?.approved?.[c], c)} cls={tone(sum?.approved?.[c]?.net)} />
              <Tile label="All module positions · same period" value={money(sum?.control?.[c]?.net ?? 0, c)}
                    sub={statLine(sum?.control?.[c], c)} cls={tone(sum?.control?.[c]?.net)} />
              <Tile label="AI skipped · what they did" value={money(sum?.skipped?.[c]?.net ?? 0, c)}
                    sub={statLine(sum?.skipped?.[c], c)} cls={tone(sum?.skipped?.[c]?.net)} />
              <Tile label="Open AI positions" value={String(sum?.open_ai_positions ?? 0)}
                    sub={sum?.since ? `gate started ${ist(sum.since)}` : "no position reviewed yet"} />
              <Tile label="Reviews today" value={`${reviewedToday}${sum?.daily_max ? ` / ${sum.daily_max}` : ""}`}
                    sub={`${today.take ?? 0} approved · ${today.skip ?? 0} skipped · ${today.not_reviewed ?? 0} not reviewed`} />
              <Tile label="AI cost" value={`$${(sum?.cost_today_usd ?? 0).toFixed(2)} today`}
                    sub={`$${(sum?.cost_usd ?? 0).toFixed(2)} in all · ${sum?.model ?? ""}`} />
            </div>
          ))}

          <div className="av-tabs" role="tablist">
            {VIEWS.map((v) => (
              <button key={v.id} role="tab" aria-selected={view === v.id} className={view === v.id ? "av-tab on" : "av-tab"} onClick={() => setView(v.id)}>
                {v.label}
              </button>
            ))}
          </div>

          {(view === "open" || view === "closed") && (
            <GlassPanel title={view === "open" ? "Open AI positions" : "Closed AI positions"}
                        note="Fills and size are the module's own; times are IST">
              {(view === "open" ? open : closed).length === 0 ? (
                <p className="av-p">{view === "open" ? "No open AI position." : "No closed AI position yet."}</p>
              ) : (
                <div className="av-scroll av-tall">
                  <table className="av-table">
                    <thead>
                      <tr>
                        <th className="av-l">AI position ID</th><th>Approved</th><th>Signal</th><th className="av-l">Strategy</th>
                        <th className="av-l">Symbol</th><th>Side</th><th>Entry</th><th>Stop</th><th>Target</th>
                        {view === "closed" && (<><th>Exit</th><th>Closed</th><th>Exit reason</th><th>Move</th><th>P&amp;L</th></>)}
                        <th>P(profit)</th><th>Confidence</th><th className="av-l">Why the AI approved</th><th className="av-l">Main risk</th>
                        <th className="av-l">Module position</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(view === "open" ? open : closed).map((p) => (
                        <tr key={p.ai_position_id} className={p.status === "VOID" ? "av-void" : ""}>
                          <td className="av-l av-id">{p.ai_position_id}</td>
                          <td>{ist(p.approved_at)}</td>
                          <td>{ist(p.signal_time)}</td>
                          <td className="av-l">{p.strategy_name ?? p.strategy_id}</td>
                          <td className="av-l">{p.symbol}</td>
                          <td>{p.side === "BUY" ? "Long" : "Short"}</td>
                          <td>{px(p.entry_price)}</td>
                          <td>{px(p.stop)}</td>
                          <td>{px(p.target)}</td>
                          {view === "closed" && (
                            <>
                              <td>{px(p.exit_price)}</td>
                              <td>{ist(p.closed_at)}</td>
                              <td>{p.status === "VOID" ? "void" : (p.exit_reason ?? "—")}</td>
                              <td className={tone(p.move_pct)}>{p.move_pct == null ? "—" : `${p.move_pct > 0 ? "+" : ""}${p.move_pct.toFixed(2)}%`}</td>
                              <td className={tone(p.pnl)}>{money(p.pnl, p.currency)}</td>
                            </>
                          )}
                          <td>{p.p_profit == null ? "—" : `${Math.round(p.p_profit * 100)}%`}</td>
                          <td>{p.confidence ?? "—"}</td>
                          <td className="av-l av-why">{(p.reasons ?? []).join(" ")}</td>
                          <td className="av-l av-why">{p.main_risk ?? ""}</td>
                          <td className="av-l av-id">{p.parent_id}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassPanel>
          )}

          {view === "leaderboard" && (
            <GlassPanel title="Strategy leaderboard · AI-approved positions"
                        note="Ranked by the AI book's net P&L; 'Module' = every position of that strategy since the gate started">
              {board.length === 0 ? (
                <p className="av-p">No strategy reviewed yet.</p>
              ) : (
                <div className="av-scroll av-tall">
                  <table className="av-table">
                    <thead>
                      <tr>
                        <th>#</th><th className="av-l">Strategy</th><th>Reviewed</th><th>Approved</th><th>Approval %</th>
                        <th>Skipped</th><th>Not reviewed</th><th>AI open</th><th>AI closed</th><th>AI win %</th>
                        <th>AI net P&amp;L</th><th>AI avg</th><th>Module closed</th><th>Module win %</th><th>Module net P&amp;L</th>
                        <th>Module avg</th>
                      </tr>
                    </thead>
                    <tbody>
                      {board.map((r) => (
                        <tr key={r.strategy_id}>
                          <td>{r.rank}</td>
                          <td className="av-l">{r.strategy_name}</td>
                          <td>{r.reviewed}</td>
                          <td>{r.approved}</td>
                          <td>{pctv(r.approval_rate)}</td>
                          <td>{r.skipped}</td>
                          <td>{r.not_reviewed}</td>
                          <td>{r.ai_open}</td>
                          <td>{r.ai_trades}</td>
                          <td>{pctv(r.ai_win_rate)}</td>
                          <td className={tone(r.ai_trades ? r.ai_net : null)}>{r.ai_trades ? money(r.ai_net, r.currency) : "—"}</td>
                          <td className={tone(r.ai_avg)}>{money(r.ai_avg, r.currency)}</td>
                          <td>{r.module_trades}</td>
                          <td>{pctv(r.module_win_rate)}</td>
                          <td className={tone(r.module_trades ? r.module_net : null)}>{r.module_trades ? money(r.module_net, r.currency) : "—"}</td>
                          <td className={tone(r.module_avg)}>{money(r.module_avg, r.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassPanel>
          )}

          {view === "daily" && (
            <GlassPanel title="Day by day · the AI book against the module" note="By the day each position closed (IST)">
              {days.length === 0 ? (
                <p className="av-p">No closed position yet.</p>
              ) : (
                <div className="av-scroll">
                  <table className="av-table">
                    <thead>
                      <tr><th className="av-l">Day</th><th>AI closed</th><th>AI win %</th><th>AI net P&amp;L</th>
                        <th>Module closed</th><th>Module win %</th><th>Module net P&amp;L</th></tr>
                    </thead>
                    <tbody>
                      {days.map((d) => (
                        <tr key={`${d.day}|${d.currency}`}>
                          <td className="av-l">{dayLabel(d.day)}{days.some((x) => x.currency !== d.currency) ? ` · ${d.currency}` : ""}</td>
                          <td>{d.ai_trades}</td>
                          <td>{pctv(d.ai_win_rate)}</td>
                          <td className={tone(d.ai_net)}>{money(d.ai_net, d.currency)}</td>
                          <td>{d.module_trades}</td>
                          <td>{pctv(d.module_win_rate)}</td>
                          <td className={tone(d.module_net)}>{money(d.module_net, d.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassPanel>
          )}

          {view === "decisions" && (
            <GlassPanel title="AI decisions" note="Every position the gate reviewed, newest first, with the AI's own reasons">
              <div className="av-chips">
                {[["", "All"], ["take", "Approved"], ["skip", "Skipped"], ["not_reviewed", "Not reviewed"]].map(([k, l]) => (
                  <button key={k || "all"} className={decFilter === k ? "av-chip on" : "av-chip"} onClick={() => setDecFilter(k)}>{l}</button>
                ))}
              </div>
              {decisions.length === 0 ? (
                <p className="av-p">No decision yet.</p>
              ) : (
                <div className="av-scroll av-tall">
                  <table className="av-table">
                    <thead>
                      <tr><th>Reviewed</th><th className="av-l">Strategy</th><th className="av-l">Symbol</th><th>Side</th><th>Entry</th>
                        <th>Decision</th><th>P(profit)</th><th>Confidence</th><th className="av-l">Reasons</th><th className="av-l">Main risk</th>
                        <th className="av-l">AI position ID</th><th>Answer time</th></tr>
                    </thead>
                    <tbody>
                      {decisions.map((d) => (
                        <Fragment key={d._id}>
                          <tr>
                            <td>{ist(d.seen_at)}</td>
                            <td className="av-l">{d.strategy_name ?? d.strategy_id}</td>
                            <td className="av-l">{d.symbol}</td>
                            <td>{d.side === "BUY" ? "Long" : "Short"}</td>
                            <td>{px(d.entry)}</td>
                            <td><span className={`av-dec av-dec-${d.decision}`}>{DEC_LABEL[d.decision] ?? d.decision}</span></td>
                            <td>{d.p_profit == null ? "—" : `${Math.round(d.p_profit * 100)}%`}</td>
                            <td>{d.confidence ?? "—"}</td>
                            <td className="av-l av-why">{d.decision === "not_reviewed" ? (d.why ?? "") : (d.reasons ?? []).join(" ")}</td>
                            <td className="av-l av-why">{d.main_risk ?? ""}</td>
                            <td className="av-l av-id">{d.ai_position_id ?? ""}</td>
                            <td>{d.latency_ms == null ? "—" : `${(d.latency_ms / 1000).toFixed(1)}s`}</td>
                          </tr>
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassPanel>
          )}
        </>
      )}

      <style jsx>{`
        .page :global(.av-back) { display: inline-block; margin-bottom: 8px; font-size: 12.5px; font-weight: 700; color: var(--purple); text-decoration: none; }
        .av-pill { font-size: 11.5px; font-weight: 800; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--panel-border); color: var(--text-muted); white-space: nowrap; }
        .av-pill-on { color: var(--gain); border-color: var(--gain); }
        .av-pill-warn { color: var(--warn); border-color: var(--warn); }
        .av-note { margin: 0 0 14px; padding: 10px 14px; border-radius: 12px; border: 1px solid var(--panel-border); background: var(--panel);
          font-size: 12.5px; line-height: 1.55; color: var(--text-muted); }
        .av-warn { margin: 0 0 14px; padding: 10px 14px; border-radius: 12px; border: 1px solid var(--warn); font-size: 12.5px; color: var(--text); }
        .av-p { margin: 0; font-size: 13px; line-height: 1.6; color: var(--text-muted); }
        .av-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin-bottom: 14px; }
        .av-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 14px; }
        .av-tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 14px;
          border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .av-tab.on { background: var(--purple-dim); color: var(--purple); }
        .av-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
        .av-chip { background: none; border: 1px solid var(--panel-border); color: var(--text-muted); padding: 4px 10px; border-radius: 999px;
          font-size: 12px; font-weight: 600; cursor: pointer; }
        .av-chip.on { color: var(--purple); border-color: var(--purple); }
        .av-scroll { overflow-x: auto; }
        .av-tall { max-height: 560px; overflow-y: auto; }
        .av-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .av-table th { position: sticky; top: 0; background: var(--panel); text-align: right; font-size: 10.5px; font-weight: 800;
          color: var(--text-muted); text-transform: uppercase; padding: 7px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .av-table td { text-align: right; padding: 7px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; color: var(--text); }
        .av-l { text-align: left !important; }
        .av-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
        .av-why { white-space: normal !important; min-width: 240px; max-width: 420px; color: var(--text-muted) !important; }
        .av-void td { opacity: 0.55; }
        .av-pos { color: var(--gain) !important; }
        .av-neg { color: var(--loss) !important; }
        .av-dec { font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--panel-border); }
        .av-dec-take { color: var(--gain); border-color: var(--gain); }
        .av-dec-skip { color: var(--loss); border-color: var(--loss); }
        .av-dec-not_reviewed { color: var(--text-muted); }
      `}</style>
    </div>
  );
}
