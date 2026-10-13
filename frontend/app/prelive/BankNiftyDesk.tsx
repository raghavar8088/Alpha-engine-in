"use client";

/*
 * Index Option Buying > NIFTY BANK (2026-10-11).
 *
 * The ten BANKNIFTY option-buying strategies chosen by a pre-registered research protocol
 * (backend/research/banknifty_2026_10/PROTOCOL.md) from 297 tested on 2016-2026 data, and the
 * paper desk that trades them forward on live Angel data. Every strategy carries its evidence
 * tier: a backtest that is positive in two periods is not the same as a proven edge, and with
 * 297 trials some would look good by luck alone - the page says how many.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import Sparkline from "../../components/Sparkline";
import LineChart from "../../components/charts/LineChart";
import {
  type BnDesk,
  type BnPeriodStats,
  type BnPosition,
  type BnStrategy,
  type BnTrial,
  fetchBankNiftyDesk,
  fetchBankNiftyResearch,
  refreshing,
} from "../../lib/api";

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : `₹${Math.round(v).toLocaleString("en-IN")}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : `${v >= 0 ? "+" : "−"}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
const pct = (v: number | null | undefined, dp = 0) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(dp)}%`);
const tone = (v: number | null | undefined) => (v === null || v === undefined ? "" : v >= 0 ? "gain" : "loss");
const num = (v: number | null | undefined, dp = 2) => (v === null || v === undefined ? "–" : v.toFixed(dp));

const TIER: Record<string, { label: string; cls: string; help: string }> = {
  A: { label: "A · passed", cls: "ok", help: "Significant before 2022 AND after (t ≥ 2 each), deflated Sharpe ≥ 0.95 over every trial, survives double spreads, positive in most years." },
  B: { label: "B · confirmed", cls: "wait", help: "Significant before 2022 (t ≥ 2) and still positive after (t ≥ 1), even at double spreads." },
  C: { label: "C · positive", cls: "soft", help: "Made money in both periods but not significantly — about a quarter of all tested strategies would do that by luck. Treat as a candidate, not an edge." },
};

const KIND: Record<string, string> = {
  library_intraday: "library · intraday",
  custom_intraday: "BANKNIFTY rule · intraday",
  daily: "daily · held overnight",
};

function Period({ s }: { s: BnPeriodStats }) {
  return (
    <span>
      {s.trades} · <b className={tone(s.mean)}>{signed(s.mean)}</b>/trade · t {num(s.t)}
    </span>
  );
}

function legText(p: BnPosition) {
  const l = p.legs[0];
  return `${l?.expiry ?? p.expiry} ${l ? l.strike.toFixed(0) : ""} ${p.kind}`;
}

export default function BankNiftyDesk({ refreshKey = 0 }: { refreshKey?: number }) {
  const [desk, setDesk] = useState<BnDesk | null>(null);
  const [trials, setTrials] = useState<BnTrial[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showTrials, setShowTrials] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setDesk(await fetchBankNiftyDesk());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the NIFTY BANK desk");
    }
  }, []);

  useEffect(() => {
    // refreshKey > 0 means the page's Refresh button: re-read the database, not the 20 s cache
    if (refreshKey) refreshing(() => load());
    else load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load, refreshKey]);

  useEffect(() => {
    if (!showTrials || trials) return;
    fetchBankNiftyResearch().then((r) => setTrials(r.trials)).catch(() => setTrials([]));
  }, [showTrials, trials]);

  const meta = desk?.research;
  const eng = desk?.engine;
  const tiers = meta?.tiers ?? {};
  const strategies = desk?.strategies ?? [];
  const tierCounts = useMemo(() => {
    const c: Record<string, number> = {};
    strategies.forEach((s) => { c[s.tier] = (c[s.tier] ?? 0) + 1; });
    return c;
  }, [strategies]);

  return (
    <>
      {error && <ErrorBanner message={error} />}

      {meta && (
        <div className="bn-verdict">
          <b>Read this first.</b> {meta.verdict}
        </div>
      )}

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Engine</div>
          <div className={`tile-value ${eng?.session === "open" ? "gain" : ""}`}>
            <span className={`dot ${eng?.session === "open" && eng?.switch_on ? "live" : "off"}`} />
            {eng ? (!eng.switch_on ? "switched off" : eng.session === "open" ? "trading" : "market closed") : "–"}
          </div>
          <div className="tile-sub">
            {eng?.last_cycle ? `last cycle ${new Date(eng.last_cycle).toLocaleTimeString()}` : "no cycle yet"}
            {eng?.errors ? ` · ${eng.errors} errors` : ""}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Forward P&amp;L (real-money estimate)</div>
          <div className={`tile-value ${tone(desk?.totals.real_net)}`}>{signed(desk?.totals.real_net)}</div>
          <div className="tile-sub">ask in, bid out, Angel charges · paper (LTP) {signed(desk?.totals.paper_net)}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Forward trades</div>
          <div className="tile-value">{desk?.totals.trades ?? "–"}</div>
          <div className="tile-sub">{desk?.totals.wins ?? 0} won · {desk?.totals.open ?? 0} open now ({signed(desk?.totals.unrealized_real)} unrealised)</div>
        </div>
        <div className="tile">
          <div className="tile-label">Paper accounts</div>
          <div className="tile-value">{inr(desk?.account.total_capital)}</div>
          <div className="tile-sub">{desk?.account.strategies ?? 0} × {inr(desk?.account.per_strategy_capital)} · 1 lot ({desk?.account.lot_size ?? 30}) a trade</div>
        </div>
        <div className="tile">
          <div className="tile-label">Research</div>
          <div className="tile-value">{meta ? `${meta.trials} tested` : "–"}</div>
          <div className="tile-sub">
            {meta ? `${tiers.A ?? 0} passed · ${tiers.B ?? 0} confirmed · ${tiers.C ?? 0} positive · luck alone ≈ ${meta.luck.expected_C_or_better_by_luck} positive` : ""}
          </div>
        </div>
      </div>

      <GlassPanel
        title="The ten strategies"
        note={meta ? `${meta.window.from} → ${meta.window.to} · ${Object.entries(tierCounts).map(([t, n]) => `${n} tier ${t}`).join(" · ")}` : undefined}
      >
        <div className="note">{meta?.selection_note}</div>
        <div className="table-scroll tall">
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th><th>Tier</th><th className="l">Strategy</th><th>Kind</th>
                <th>2016–2021 (trades · per trade · t)</th><th>2022–2026</th><th>Win %</th><th>Max DD</th><th>DSR</th>
                <th className="l">Backtest curve</th><th>Forward</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s: BnStrategy) => {
                const open = expanded === s.key;
                const t = TIER[s.tier] ?? { label: s.tier, cls: "", help: "" };
                return (
                  <Fragment key={s.key}>
                    <tr className={`row ${open ? "open" : ""}`} onClick={() => setExpanded(open ? null : s.key)}>
                      <td>{s.rank}</td>
                      <td><span className={`pill ${t.cls}`} title={t.help}>{t.label}</span></td>
                      <td className="l"><b>{s.label}</b><div className="small muted">{s.family} · {s.sid}{s.tf !== "1d" ? `@${s.tf}` : ""}</div></td>
                      <td className="small">{KIND[s.source] ?? s.source}</td>
                      <td className="small"><Period s={s.research.explore} /></td>
                      <td className="small"><Period s={s.research.holdout} /></td>
                      <td>{pct(s.research.all.win_rate)}</td>
                      <td className="loss">{inr(s.research.all.max_drawdown)}</td>
                      <td>{num(s.research.dsr)}</td>
                      <td className="spark"><Sparkline values={s.research.equity.map(([, v]) => v)} /></td>
                      <td className="small">{s.forward.trades ? <><b className={tone(s.forward.real_net)}>{signed(s.forward.real_net)}</b> · {s.forward.trades} tr</> : s.forward.open ? "open" : "no trades yet"}</td>
                    </tr>
                    {open && (
                      <tr className="detail">
                        <td colSpan={11}>
                          <div className="detail-grid">
                            <div>
                              <div className="small muted">{t.help}</div>
                              <LineChart
                                points={s.research.equity.map(([ts, value]) => ({ ts, value }))}
                                height={170}
                                fillToZero
                                formatValue={(v) => signed(v)}
                              />
                              <div className="small muted">Cumulative net P&amp;L of one lot per trade, after spread and Angel charges, month by month.</div>
                            </div>
                            <div className="kvs">
                              <div className="kv"><span>All trades</span><b><Period s={s.research.all} /></b></div>
                              <div className="kv"><span>Net over 2016–2026 (1 lot)</span><b className={tone(s.research.all.net)}>{signed(s.research.all.net)}</b></div>
                              <div className="kv"><span>At double spreads</span><b className={tone(s.research.all.mean_stressed)}>{signed(s.research.all.mean_stressed)}/trade</b></div>
                              <div className="kv"><span>Profit factor</span><b>{num(s.research.all.profit_factor)}</b></div>
                              <div className="kv"><span>Index moved its way</span><b>{pct(s.research.all.direction_hit, 1)} · {s.research.all.fav_bp == null ? "—" : `${(s.research.all.fav_bp / 100).toFixed(3)}% avg`}</b></div>
                              <div className="kv"><span>Exits</span><b>{Object.entries(s.research.exits).map(([k, v]) => `${k} ${v}`).join(" · ")}</b></div>
                              {s.research.avg_hold_min !== null && <div className="kv"><span>Average hold</span><b>{s.source === "daily" ? `${s.research.avg_hold_min} sessions` : `${s.research.avg_hold_min} min`}</b></div>}
                              <div className="years">
                                {Object.entries(s.research.years).map(([y, v]) => (
                                  <span key={y} className={`chip ${tone(v.net)}`}>{y}: {signed(v.net)} ({v.trades})</span>
                                ))}
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <div className="grid-2">
        <GlassPanel title="Open paper positions (marked at the bid)">
          {desk && desk.open.length ? (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th className="l">Strategy</th><th>Contract</th><th>Bought (ask)</th><th>Bid now</th><th>Unrealised</th><th>Opened</th></tr></thead>
                <tbody>{desk.open.map((p) => (
                  <tr key={`${p.strategy}-${p.opened_at}`}>
                    <td className="l">{p.strategy}</td>
                    <td className={p.kind === "CE" ? "gain" : p.kind === "PE" ? "loss" : ""}>{legText(p)}</td>
                    <td>{p.legs.map((l) => l.real_entry.toFixed(2)).join(" + ")}</td>
                    <td>{p.legs.map((l) => (l.mark_bid ?? l.mark)?.toFixed(2) ?? "–").join(" + ")}</td>
                    <td className={tone(p.unrealized_real)}>{signed(p.unrealized_real)}</td>
                    <td className="small">{new Date(p.opened_at).toLocaleString()}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <div className="empty">No open positions.</div>}
        </GlassPanel>

        <GlassPanel title="Recent paper trades">
          {desk && desk.trades.length ? (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Closed</th><th className="l">Strategy</th><th>Contract</th><th>Ask → bid</th><th>Real</th><th>Paper</th><th>Why</th></tr></thead>
                <tbody>{desk.trades.map((t) => (
                  <tr key={`${t.strategy}-${t.opened_at}`}>
                    <td className="small">{t.closed_at ? new Date(t.closed_at).toLocaleString() : "–"}</td>
                    <td className="l">{t.strategy}</td>
                    <td className={t.kind === "CE" ? "gain" : t.kind === "PE" ? "loss" : ""}>{legText(t)}</td>
                    <td>{t.legs.map((l) => `${l.real_entry.toFixed(1)}→${(l.real_exit ?? 0).toFixed(1)}`).join(" + ")}</td>
                    <td className={tone(t.real_pnl)}>{signed(t.real_pnl)}</td>
                    <td className={tone(t.paper_pnl)}>{signed(t.paper_pnl)}</td>
                    <td className="small">{t.exit_reason}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <div className="empty">No closed trades yet.</div>}
        </GlassPanel>
      </div>

      {meta && (
        <GlassPanel title="How these were found" note="backend/research/banknifty_2026_10">
          <div className="kvs">
            <div className="kv"><span>Data</span><b>{meta.data}</b></div>
            <div className="kv"><span>Contract</span><b>{meta.contract}</b></div>
            <div className="kv"><span>Costs</span><b>{meta.costs}</b></div>
            <div className="kv"><span>Periods</span><b>chosen on {meta.periods.explore}; checked on {meta.periods.holdout}</b></div>
            <div className="kv"><span>Strategies tested</span><b>{Object.entries(meta.trials_by_source).map(([k, v]) => `${v} ${KIND[k] ?? k}`).join(" · ")}</b></div>
            <div className="kv"><span>Luck line</span><b>by chance alone ≈ {meta.luck.expected_C_or_better_by_luck} positive in both periods, {meta.luck.expected_B_or_better_by_luck} confirmed, {meta.luck.expected_A_by_luck} passed — observed {tiers.C ?? 0} / {tiers.B ?? 0} / {tiers.A ?? 0}</b></div>
            {Object.entries(meta.model).map(([k, v]) => (
              <div key={k} className="kv"><span>{k.replace(/_/g, " ")}</span><b>{String(v)}</b></div>
            ))}
          </div>
          <button className="linkish" onClick={() => setShowTrials((v) => !v)}>
            {showTrials ? "Hide" : "Show"} all {meta.trials} strategies tested
          </button>
          {showTrials && (
            trials === null ? <div className="empty">Loading…</div> : (
              <div className="table-scroll tall">
                <table className="data-table">
                  <thead><tr><th className="l">Strategy</th><th>Kind</th><th>Tier</th><th>2016–2021</th><th>2022–2026</th><th>DSR</th><th className="l">Note</th></tr></thead>
                  <tbody>{trials.map((r) => (
                    <tr key={r.key} className={r.chosen ? "chosen" : ""}>
                      <td className="l">{r.label}<div className="small muted">{r.key}</div></td>
                      <td className="small">{KIND[r.source] ?? r.source}</td>
                      <td>{r.tier}</td>
                      <td className="small">{r.explore.trades} · <span className={tone(r.explore.mean)}>{signed(r.explore.mean)}</span> · t {num(r.explore.t)}</td>
                      <td className="small">{r.holdout.trades} · <span className={tone(r.holdout.mean)}>{signed(r.holdout.mean)}</span> · t {num(r.holdout.t)}</td>
                      <td>{num(r.dsr)}</td>
                      <td className="l small">{r.chosen ? "chosen" : r.skipped ?? ""}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )
          )}
        </GlassPanel>
      )}

      <style jsx>{`
        .bn-verdict { font-size: 12.5px; line-height: 1.6; color: var(--text-muted); padding: 12px 16px; border-radius: 12px; background: var(--warn-dim); border: 1px solid var(--panel-border); }
        .bn-verdict b { color: var(--text); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .tile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 6px; font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px; font-variant-numeric: tabular-nums; }
        .tile-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); line-height: 1.4; }
        .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
        .dot.live { background: var(--gain); box-shadow: 0 0 8px var(--gain); }
        .dot.off { background: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .muted { color: var(--text-muted); font-weight: 500; }
        .small { font-size: 11px; }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 6px 2px 10px; line-height: 1.5; }
        .empty { padding: 28px 20px; text-align: center; color: var(--text-faint); font-size: 13px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .table-scroll { overflow-x: auto; max-height: 420px; overflow-y: auto; }
        .table-scroll.tall { max-height: 640px; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); z-index: 1; }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); vertical-align: middle; }
        .data-table .l { text-align: left; }
        .row { cursor: pointer; }
        .row:hover td, .row.open td { background: var(--canvas-soft); }
        .detail td { background: var(--canvas-soft); text-align: left; }
        .chosen td { background: var(--gain-dim); }
        .spark { width: 140px; min-width: 120px; }
        .detail-grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 18px; padding: 6px 2px; }
        @media (max-width: 900px) { .detail-grid { grid-template-columns: 1fr; } }
        .kvs { display: flex; flex-direction: column; }
        .kv { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; padding: 6px 0; border-bottom: 1px solid var(--canvas-soft); }
        .kv span { color: var(--text-muted); white-space: nowrap; }
        .kv b { text-align: right; font-weight: 600; }
        .years { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 8px; }
        .chip { font-size: 11px; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 8px; padding: 3px 8px; }
        .pill { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: var(--canvas-edge); color: var(--text-muted); white-space: nowrap; }
        .pill.ok { background: var(--gain-dim); color: var(--gain); }
        .pill.wait { background: var(--accent-dim); color: var(--accent-hover); }
        .pill.soft { background: var(--warn-dim); color: var(--text); }
        .linkish { margin-top: 10px; background: none; border: 1px solid var(--panel-border); color: var(--text); padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; }
      `}</style>
    </>
  );
}
