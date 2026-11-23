"use client";

import { useMemo } from "react";
import GlassPanel from "../../../components/GlassPanel";
import { RESEARCH } from "./researchData";
import { API, LEVEL, R, bp, inr, num, pct, share, statusClass, tone, useDesk } from "./desk";

function fmtCheck(v: any): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Math.abs(v) >= 100 ? Math.round(v).toLocaleString("en-IN") : num(v, 3);
  return String(v);
}

function SideBlock({ side, x }: { side: string; x: any }) {
  const wf = x.walk_forward || {};
  const f = x.final || {};
  return (
    <div className="pis-side">
      <div className="pis-side-head">
        <b className={side === "LONG" ? "pis-up" : "pis-down"}>{side}</b> · target {x.target_R}R
        <span className={statusClass(x.status)}>{x.status}</span>
      </div>
      <div className="pis-scroll"><table className="pis-table pis-compact">
        <thead><tr><th>Period</th><th className="r">Trades</th><th className="r">Mean net</th><th className="r">Net / trade</th>
          <th className="r">PF</th><th className="r">Win</th><th className="r">Max DD</th><th className="r">Return</th></tr></thead>
        <tbody>
          <tr><td>Walk-forward (out of sample)</td><td className="r">{wf.trades ?? 0}</td><td className={`r ${tone(wf.mean_R)}`}>{R(wf.mean_R)}</td>
            <td className={`r ${tone(wf.mean_net_bp)}`}>{bp(wf.mean_net_bp)}</td><td className="r">{num(wf.profit_factor)}</td>
            <td className="r">{num(wf.win_pct, 0)}%</td><td className="r">{num(wf.max_dd_pct, 1)}%</td><td className={`r ${tone(wf.return_pct)}`}>{pct(wf.return_pct)}</td></tr>
          <tr><td>Final period (untouched)</td><td className="r">{f.trades ?? 0}</td><td className={`r ${tone(f.mean_R)}`}>{R(f.mean_R)}</td>
            <td className={`r ${tone(f.mean_net_bp)}`}>{bp(f.mean_net_bp)}</td><td className="r">{num(f.profit_factor)}</td>
            <td className="r">{num(f.win_pct, 0)}%</td><td className="r">{num(f.max_dd_pct, 1)}%</td><td className={`r ${tone(f.return_pct)}`}>{pct(f.return_pct)}</td></tr>
        </tbody>
      </table></div>
      <p className="pis-small">
        Folds (mean net R): {(x.wf_fold_mean_R || []).map((m: any) => (m === null ? "—" : num(m, 3))).join(" / ")} ·
        {" "}final at 2x slippage {R(x.final_x2_mean_R)}, at 3x {R(x.final_x3_mean_R)} · pooled day-clustered t {num(x.pooled_t)} ({x.pooled_trades ?? 0} trades)
        {f.trades ? ` · final: ${f.days_traded} trading days, ${inr(f.avg_daily_net_sessions)} average a session, costs ${inr(f.costs)}, capital used ${num(x.utilized_avg_pct, 1)}% on average (${num(x.utilized_peak_pct, 0)}% peak) of Rs 10 lakh allocated` : ""}
      </p>
      <details className="pis-rules"><summary>Every criterion</summary>
        <ul className="pis-checks">{x.checks.map((c: any) => (
          <li key={c.name} className={c.pass ? "ok" : "bad"}><b>{c.pass ? "pass" : "fail"}</b> {c.name}: {fmtCheck(c.value)}</li>))}</ul>
      </details>
      <p className="pis-small pis-muted">{x.reason}</p>
    </div>
  );
}

function Forward() {
  const { data: books } = useDesk<any>(`${API}/books`, 120_000);
  const { data: closed } = useDesk<any>(`${API}/positions?status=CLOSED&limit=5000`, 120_000);
  const rows = useMemo(() => {
    const by: Record<string, any[]> = {};
    for (const p of closed?.rows || []) (by[p.book] ||= []).push(p);
    return (books?.books || []).map((b: any) => {
      const ps = by[b.id] || [];
      const nets = ps.map((p: any) => p.net || 0);
      const wins = nets.filter((n: number) => n > 0).reduce((a: number, c: number) => a + c, 0);
      const losses = -nets.filter((n: number) => n <= 0).reduce((a: number, c: number) => a + c, 0);
      const days = new Set(ps.map((p: any) => p.day)).size;
      return {
        id: b.id, equity: b.equity, trades: ps.length, days, open: b.open,
        meanR: ps.length ? ps.reduce((a: number, p: any) => a + (p.r_net || 0), 0) / ps.length : null,
        pf: losses > 0 ? wins / losses : null, net: nets.reduce((a: number, c: number) => a + c, 0),
        missed: null,
      };
    }).sort((a: any, b: any) => (a.id === "portfolio" ? -1 : b.id === "portfolio" ? 1 : a.id.localeCompare(b.id)));
  }, [books, closed]);
  if (!books) return <p className="pis-muted">Reading the forward record…</p>;
  if (!rows.length) {
    return <div className="pis-empty">No forward paper record yet: the desk’s first session fills these books. Every strategy
      keeps collecting forward observations in its own Rs 10 lakh book whatever its status.</div>;
  }
  return (
    <div className="pis-scroll">
      <table className="pis-table">
        <thead><tr><th>Book</th><th className="r">Equity</th><th className="r">Net since start</th><th className="r">Trades</th>
          <th className="r">Days</th><th className="r">Mean net R</th><th className="r">PF</th><th className="r">Open</th></tr></thead>
        <tbody>{rows.map((r: any) => (
          <tr key={r.id}><td className="pis-strong">{r.id === "portfolio" ? "Shared portfolio (eligible strategies only)" : r.id}</td>
            <td className="r">{inr(r.equity)}</td><td className={`r ${tone(r.net)}`}>{inr(r.net)}</td><td className="r">{r.trades}</td>
            <td className="r">{r.days}</td><td className={`r ${tone(r.meanR)}`}>{R(r.meanR)}</td><td className="r">{num(r.pf)}</td>
            <td className="r">{r.open ?? 0}</td></tr>))}</tbody>
      </table>
    </div>
  );
}

export default function ResultsView() {
  const S = RESEARCH.strategies;
  const eligible = S.flatMap((s: any) => ["LONG", "SHORT"].filter((k) => s.sides[k].status === "Portfolio Eligible").map((k) => `${s.id} ${k}`));
  return (
    <div className="pis-col">
      <div className="pis-banner">
        <span className={eligible.length ? "pis-pill pis-pill-good" : "pis-pill pis-pill-bad"}>{eligible.length} eligible</span>
        <span>
          <b>No strategy has earned Portfolio Eligible status</b>, so the shared Rs 10 lakh portfolio places no trade. None of
          the six new strategies passed its backtest criteria on either side; all twelve are Rejected and keep collecting
          forward observations in their own books. The closest: N03 long (+0.33R a trade in the final period but only 12 trades
          and negative in walk-forward) and N05 long (+0.19R, 18 trades, negative in walk-forward).
        </span>
      </div>
      {S.map((s: any) => (
        <GlassPanel key={s.id} title={`${s.id} · ${s.name}`} note={`registered at ladder level ${s.primary} (${LEVEL[s.primary]})`}>
          <div className="pis-col">
            <SideBlock side="LONG" x={s.sides.LONG} />
            <SideBlock side="SHORT" x={s.sides.SHORT} />
          </div>
          <h4 className="pis-h4">What each addition does (rule alone → + sector → + 09:40 checkpoint → + news)</h4>
          <div className="pis-scroll">
            <table className="pis-table pis-compact">
              <thead><tr><th>Side</th><th>Level</th><th className="r">WF trades</th><th className="r">WF mean</th><th className="r">WF net</th><th className="r">WF DD</th>
                <th className="r">Final trades</th><th className="r">Final mean</th><th className="r">Final net</th><th className="r">Final DD</th><th className="r">Removed vs rule alone</th></tr></thead>
              <tbody>{(["LONG", "SHORT"] as const).flatMap((side) => (s.ladder[side] || []).map((r: any) => (
                <tr key={side + r.level} className={r.level === s.primary ? "pis-row-strong" : ""}>
                  <td className={side === "LONG" ? "pis-up" : "pis-down"}>{side}</td>
                  <td>{r.level} {r.label}{r.news_period_only ? " (Nov 2025 on)" : ""}</td>
                  <td className="r">{r.wf_trades}</td><td className={`r ${tone(r.wf_mean_R)}`}>{R(r.wf_mean_R)}</td>
                  <td className={`r ${tone(r.wf_net_bp)}`}>{bp(r.wf_net_bp)}</td><td className="r">{r.wf_trades ? `${num(r.wf_max_dd_pct, 1)}%` : "—"}</td>
                  <td className="r">{r.final_trades}</td><td className={`r ${tone(r.final_mean_R)}`}>{R(r.final_mean_R)}</td>
                  <td className={`r ${tone(r.final_net_bp)}`}>{bp(r.final_net_bp)}</td><td className="r">{r.final_trades ? `${num(r.final_max_dd_pct, 1)}%` : "—"}</td>
                  <td className="r">{r.removed_vs_rule_alone_final == null ? "—" : share(r.removed_vs_rule_alone_final)}</td>
                </tr>)))}</tbody>
            </table>
          </div>
        </GlassPanel>
      ))}
      <GlassPanel title="Forward paper observation (live, from the desk's own books)">
        <Forward />
      </GlassPanel>
    </div>
  );
}
