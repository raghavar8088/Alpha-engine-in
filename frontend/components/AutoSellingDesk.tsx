"use client";

// One auto option-selling desk: per instrument, 11 strike distances x 5 account sizes, each account
// selling one call + put pair a day. Rendered by Commodity Auto Positions (MCX minis) and Indian Market
// Option Auto Selling (index options); the backend says which instruments, market and schedule.
import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "./PageHeader";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import {
  AutoAccount,
  AutoDeskApi,
  AutoPosition,
  AutoSummary,
  fetchAutoAccounts,
  fetchAutoSummary,
  fetchAutoTrades,
} from "../lib/autoSelling";

const REFRESH_MS = 30000;
const SIZES = [500000, 1000000, 2000000, 5000000, 10000000];

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" : `${v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined, dp = 0) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${inr(v, dp)}`);
const sizeLabel = (v: number) => (v >= 10000000 ? `₹${v / 10000000} Cr` : `₹${v / 100000} L`);
const big = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  const s = a >= 10000000 ? `₹${(a / 10000000).toFixed(2)} Cr` : a >= 100000 ? `₹${(a / 100000).toFixed(2)} L` : `₹${a.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  return `${v < 0 ? "−" : ""}${s}`;
};
const when = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleString("en-IN", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
const tone = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");
const px = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));

export default function AutoSellingDesk({
  api,
  crumb,
  title,
  subtitle,
  rules,
}: {
  api: AutoDeskApi;
  crumb: string;
  title: string;
  subtitle: string;
  rules: React.ReactNode;
}) {
  const [summary, setSummary] = useState<AutoSummary | null>(null);
  const [instrument, setInstrument] = useState<string | null>(null);
  const [size, setSize] = useState<number | null>(null);
  const [view, setView] = useState<"accounts" | "trades">("accounts");
  const [rows, setRows] = useState<AutoAccount[]>([]);
  const [trades, setTrades] = useState<AutoPosition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await fetchAutoSummary(api);
      setSummary(s);
      if (!instrument) {
        if (s.instruments.length) setInstrument(s.instruments[0]);   // the effect runs again with it
        return;
      }
      const [a, t] = await Promise.all([
        fetchAutoAccounts(api, instrument),
        view === "trades" ? fetchAutoTrades(api, instrument, size) : Promise.resolve(null),
      ]);
      setRows(a);
      if (t) setTrades(t);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to load ${title}`);
    }
  }, [api, instrument, view, size, title]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const shown = useMemo(() => (size ? rows.filter((r) => r.size === size) : rows), [rows, size]);
  const tot = instrument ? summary?.per_instrument?.[instrument] : undefined;
  const label = (k: string) => summary?.instrument_info?.[k]?.label ?? k;
  const run = summary?.last_run;
  const runLine = run
    ? Object.entries(run.counts)
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `${v} ${k}`)
        .join(" · ")
    : "";

  return (
    <div className="page">
      <PageHeader onRefresh={refresh} refreshing={refreshing} crumb={crumb} title={title} subtitle={subtitle} />

      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="note">{rules}</div>

      <div className="tiles">
        <Tile label="Next entry" value={when(summary?.next_entry_at)} sub={summary?.entry_label ?? ""} />
        <Tile
          label="Last entry run"
          value={run ? run.day : "—"}
          sub={run ? (run.finished_at ? runLine || "nothing to do" : "running…") : "no run yet"}
        />
        <Tile label={summary?.market_label ?? "Market"} value={summary ? (summary.market_open ? "Open" : "Closed") : "—"}
              sub="stop checks run only in session" />
        <Tile
          label="Main Control"
          value={summary ? (summary.switch_on ? "ON" : "OFF") : "—"}
          tone={summary && !summary.switch_on ? "loss" : undefined}
          sub={summary && !summary.switch_on ? "no new entries; open pairs still managed" : "entries allowed"}
        />
      </div>

      <div className="ctabs" role="tablist">
        {(summary?.instruments ?? []).map((c) => {
          const t = summary?.per_instrument?.[c];
          const net = t ? t.equity - t.starting : null;
          return (
            <button key={c} role="tab" aria-selected={instrument === c} className={instrument === c ? "ctab on" : "ctab"}
                    onClick={() => { setInstrument(c); setRows([]); setTrades([]); }}>
              <span className="ctab-name">{label(c)}</span>
              <span className="ctab-sub">{summary?.instrument_info?.[c]?.sub ?? ""}</span>
              <span className={`ctab-sub ${tone(net)}`}>{t ? `${signed(net)} · ${t.open} open` : "—"}</span>
            </button>
          );
        })}
      </div>

      <div className="tiles">
        <Tile label="Accounts" value="55" sub="11 strategies × 5 sizes" />
        <Tile label="Starting capital" value={big(tot?.starting)} sub="all 55 together" />
        <Tile label="Equity" value={big(tot?.equity)} tone={tone((tot?.equity ?? 0) - (tot?.starting ?? 0))}
              sub={`${signed((tot?.equity ?? 0) - (tot?.starting ?? 0))} since the start`} />
        <Tile label="Realised" value={signed(tot?.realized)} tone={tone(tot?.realized)}
              sub={`${tot?.trades ?? 0} closed · ${tot?.trades ? Math.round(((tot?.wins ?? 0) / tot.trades) * 100) : 0}% won`} />
        <Tile label="Unrealised" value={signed(tot?.unrealized)} tone={tone(tot?.unrealized)} sub={`${tot?.open ?? 0} pairs open`} />
      </div>

      <GlassPanel title={instrument ? `${label(instrument)} — ${view === "accounts" ? "the 55 accounts" : "closed trades"}` : "Loading…"}>
        <div className="controls">
          <button className={view === "accounts" ? "chip on" : "chip"} onClick={() => setView("accounts")}>Accounts</button>
          <button className={view === "trades" ? "chip on" : "chip"} onClick={() => setView("trades")}>Closed trades</button>
          <span className="sep" />
          <button className={size === null ? "chip on" : "chip"} onClick={() => setSize(null)}>All sizes</button>
          {SIZES.map((s) => (
            <button key={s} className={size === s ? "chip on" : "chip"} onClick={() => setSize(s)}>{sizeLabel(s)}</button>
          ))}
        </div>

        {view === "accounts" ? (
          !shown.length ? (
            <div className="empty">Loading the accounts…</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Strategy</th>
                    <th>Account</th>
                    <th>Equity</th>
                    <th>Available</th>
                    <th>Margin used</th>
                    <th>Expiry</th>
                    <th title="Call sold / put sold">Strikes</th>
                    <th>Lots · qty</th>
                    <th title="Sold at the bid, call / put">Entry</th>
                    <th title="What buying back would cost now, call / put">Now</th>
                    <th>Combined P&amp;L</th>
                    <th title="20% of the capital allocated to the pair">Allocated · stop</th>
                    <th>Opened → exit due</th>
                    <th style={{ textAlign: "left" }}>Last closed</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const o = r.open;
                    const lc = r.last_closed;
                    const skip = !o && r.last_entry?.outcome && !r.last_entry.outcome.startsWith("opened") ? r.last_entry.outcome : null;
                    return (
                      <tr key={r.account_id}>
                        <td style={{ textAlign: "left" }}>{r.strategy}</td>
                        <td>{sizeLabel(r.size)}</td>
                        <td className={tone(r.equity - r.starting_capital)}>
                          {inr(r.equity)}
                          <div className="sub">{signed(r.equity - r.starting_capital)}</div>
                        </td>
                        <td>{inr(r.available)}</td>
                        <td>{r.margin_used ? inr(r.margin_used) : "—"}</td>
                        {o ? (
                          <>
                            <td>{o.expiry}</td>
                            <td>{px(o.call.strike)} CE / {px(o.put.strike)} PE</td>
                            <td>{o.lots} · {o.qty.toLocaleString("en-IN")}</td>
                            <td>{px(o.call.entry)} / {px(o.put.entry)}</td>
                            <td className="dim" title={o.mark?.basis ?? ""}>{o.mark ? `${px(o.mark.call)} / ${px(o.mark.put)}` : "—"}</td>
                            <td className={tone(o.unrealized_pnl)}>{signed(o.unrealized_pnl)}</td>
                            <td>
                              {big(o.allocated)}
                              <div className="sub">stop at −{inr(o.stop_loss)}</div>
                            </td>
                            <td className="dim">
                              {when(o.entry_at)}
                              <div className="sub">→ {when(o.scheduled_exit_at)}</div>
                            </td>
                          </>
                        ) : (
                          <td colSpan={8} className="dim" style={{ textAlign: "left", whiteSpace: "normal", maxWidth: 520 }}>
                            {skip ? `No pair open — ${skip}` : "No pair open — the next one is sold at the next entry."}
                          </td>
                        )}
                        <td style={{ textAlign: "left" }} className="dim">
                          {lc ? (
                            <>
                              <span className={tone(lc.realized_pnl)}>{signed(lc.realized_pnl)}</span> · {lc.exit_reason} · {when(lc.exit_at)}
                              <div className="sub">{r.trades} trades · {r.trades ? Math.round((r.wins / r.trades) * 100) : 0}% won · realised {signed(r.realized)}</div>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : !trades.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Account</th>
                  <th>Expiry</th>
                  <th>Strikes</th>
                  <th>Lots · qty</th>
                  <th>Sold at</th>
                  <th>Bought back at</th>
                  <th>Allocated · stop</th>
                  <th>Opened</th>
                  <th>Closed</th>
                  <th>Reason</th>
                  <th>Charges</th>
                  <th>Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td style={{ textAlign: "left" }}>{t.strategy}</td>
                    <td>{sizeLabel(t.size)}</td>
                    <td>{t.expiry}</td>
                    <td>{px(t.call.strike)} CE / {px(t.put.strike)} PE</td>
                    <td>{t.lots} · {t.qty.toLocaleString("en-IN")}</td>
                    <td>{px(t.call.entry)} / {px(t.put.entry)}</td>
                    <td title={t.exit_basis ?? ""}>{t.exit ? `${px(t.exit.call)} / ${px(t.exit.put)}` : "—"}</td>
                    <td>
                      {big(t.allocated)}
                      <div className="sub">stop at −{inr(t.stop_loss)}</div>
                    </td>
                    <td className="dim">{when(t.entry_at)}</td>
                    <td className="dim">{when(t.exit_at)}</td>
                    <td>
                      <span className={t.exit_reason === "stoploss" ? "badge bad" : "badge"}>{t.exit_reason}</span>
                    </td>
                    <td className="loss">{t.fees ? inr(-t.fees, 2) : "—"}</td>
                    <td className={tone(t.realized_pnl)}>{signed(t.realized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .note { padding: 12px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border);
                font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .note :global(p) { margin: 0 0 8px; }
        .note :global(p:last-child) { margin-bottom: 0; }
        .note :global(b) { color: var(--text); }
        .note :global(.dim) { color: var(--text-faint); }
        .dim { color: var(--text-faint); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
        .ctabs { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
        .ctab { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; text-align: left; padding: 12px 14px;
                border-radius: 12px; background: var(--panel); border: 1px solid var(--panel-border); cursor: pointer; }
        .ctab.on { background: var(--brand-dim); border-color: rgba(var(--brand-rgb), 0.35); }
        .ctab-name { font-weight: 800; font-size: 14px; color: var(--text); }
        .ctab.on .ctab-name { color: var(--brand); }
        .ctab-sub { font-size: 11.5px; color: var(--text-faint); }
        .controls { display: flex; gap: 8px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .sep { width: 1px; height: 22px; background: var(--panel-border); margin: 0 4px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 6px 11px; border-radius: 8px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
        .chip.on { background: var(--brand-dim); border-color: rgba(var(--brand-rgb), 0.35); color: var(--brand); }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); line-height: 1.5; }
        .table-scroll { overflow-x: auto; max-height: 720px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); z-index: 1; }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); vertical-align: top; }
        .sub { font-size: 10.5px; color: var(--text-faint); margin-top: 2px; }
        .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .badge.bad { background: var(--loss-dim); color: var(--loss); border-color: transparent; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "gain" | "loss" }) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .t-label { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .t-value { font-family: var(--font-display); font-weight: 800; font-size: 19px; margin-top: 6px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { font-size: 11px; color: var(--text-faint); margin-top: 4px; }
      `}</style>
    </div>
  );
}
