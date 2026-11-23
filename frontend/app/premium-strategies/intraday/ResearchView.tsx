"use client";

import { Fragment, useState } from "react";
import GlassPanel from "../../../components/GlassPanel";
import { RESEARCH } from "./researchData";

const STATUS_CLASS: Record<string, string> = {
  implemented: "pis-pill pis-pill-info", deferred: "pis-pill pis-pill-warn", rejected: "pis-pill pis-pill-bad",
};

function HypDetail({ h, src, onClose }: { h: any; src: Record<string, any>; onClose: () => void }) {
  return (
    <div className="pis-selbox">
      <div className="pis-selbox-head"><b>{h.id} {h.family}</b><button className="pis-btn" onClick={onClose}>Close</button></div>
                    <dl className="pis-dl">
                      <dt>Why an edge could exist</dt><dd>{h.mechanism}</dd>
                      {h.fails_when && h.fails_when !== "-" && (<><dt>When it should fail</dt><dd>{h.fails_when}</dd></>)}
                      {h.invalidation && h.invalidation !== "-" && (<><dt>What would invalidate it</dt><dd>{h.invalidation}</dd></>)}
                      {h.evidence_note && (<><dt>Evidence</dt><dd>{h.evidence_note}</dd></>)}
                      {h.missing && h.missing !== "-" && (<><dt>Missing input</dt><dd>{h.missing}</dd></>)}
                      {h.data && (<><dt>Data</dt><dd>{h.data}</dd></>)}
                      <dt>Sources</dt>
                      <dd>{h.evidence.map((id: string) => src[id] ? (
                        <div key={id}>{id}: <a href={src[id].link.startsWith("http") ? src[id].link : undefined} target="_blank" rel="noreferrer">
                          {src[id].title}</a> ({src[id].date}; {src[id].type}; {src[id].region})</div>) : null)}</dd>
                    </dl>
                  
    </div>
  );
}

export default function ResearchView() {
  const reg = RESEARCH.register;
  const P = RESEARCH.prereg;
  const [open, setOpen] = useState<string | null>(null);
  const hsel = reg.hypotheses.find((h: any) => h.id === open);
  const counts = reg.hypotheses.reduce((m: any, h: any) => ({ ...m, [h.status]: (m[h.status] || 0) + 1 }), {});
  const src: Record<string, any> = Object.fromEntries(reg.sources.map((s: any) => [s.id, s]));
  const tests = RESEARCH.tests || {};
  const passed = (tests.checks || []).filter((c: any) => c.pass).length;
  return (
    <div className="pis-col">
      <div className="pis-banner">
        <span className="pis-pill pis-pill-neutral">{reg.hypotheses.length} hypotheses</span>
        <span>
          {counts.implemented || 0} implemented, {counts.deferred || 0} deferred, {counts.rejected || 0} rejected, from {reg.sources.length} sources:
          academic papers, Indian studies, SEBI’s intraday study, practitioner work and this app’s own earlier tests.
          Evidence from other markets is marked International: it still needs validation on Indian equities. The imported
          Top 25 are not counted here.
        </span>
      </div>

      <GlassPanel title="Hypotheses: implemented, deferred, rejected">
        <div className="pis-scroll">
          <table className="pis-table">
            <thead><tr><th>ID</th><th>Family</th><th>Status</th><th>Evidence</th><th>Why, and what is different from the existing catalogs</th></tr></thead>
            <tbody>{reg.hypotheses.map((h: any) => (
                <tr key={h.id} className={`pis-click${open === h.id ? " pis-sel" : ""}`} onClick={() => setOpen(open === h.id ? null : h.id)}>
                  <td className="pis-strong">{h.id}</td><td className="pis-strong pis-wrap">{h.family}</td>
                  <td><span className={STATUS_CLASS[h.status]}>{h.status}</span></td>
                  <td className="pis-small">{h.evidence.join(", ") || "—"}</td>
                  <td className="pis-small pis-wrap">{h.why || h.vs_existing}</td>
                </tr>
            ))}</tbody>
          </table>
        </div>
        {hsel && <HypDetail h={hsel} src={src} onClose={() => setOpen(null)} />}
      </GlassPanel>

      <GlassPanel title="Exact rules (what a second developer needs to reproduce a trade)">
        <h4 className="pis-h4">Common to every strategy</h4>
        <dl className="pis-dl">{RESEARCH.common_rules.map(([k, v]: [string, string]) => (<Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>))}</dl>
        {RESEARCH.strategies.map((s: any) => (
          <details key={s.id} className="pis-rules">
            <summary><b>{s.id}</b> {s.name} <span className="pis-muted pis-small">registered version: ladder level {s.primary}</span></summary>
            <dl className="pis-dl">{s.rules.map(([k, v]: [string, string]) => (<Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>))}</dl>
          </details>
        ))}
        <p className="pis-note">Code: premium-intraday-service/pis/strategies.py. The replay and the live desk run the same code;
          the tests replay five historical days through the live worker and get the same trades as the research replay.</p>
      </GlassPanel>

      <GlassPanel title="How it was tested: frozen before the final period was opened">
        <ul className="pis-list">
          <li><b>Development</b> {P.periods.development[0]} to {P.periods.development[1]}: four walk-forward folds, each training on six
            months and testing the next three. The only fitted choice is each strategy’s target ({P.walk_forward_parameter.values.join("R, ")}R),
            picked on the training window.</li>
          <li><b>Final period</b> {P.periods.final[0]} to {P.periods.final[1]}: untouched until the rules, the target choices and the
            promotion criteria were frozen. Freeze: sha256 {P.sha256.slice(0, 16)}… in commit {P.commit} on{" "}
            <a href={P.branch} target="_blank" rel="noreferrer">its own branch</a>, pushed before the final run.</li>
          <li><b>Trials counted:</b> {P.trials.configurations_replayed} configurations replayed (6 strategies x 2 sides x 4 ladder levels x 3 targets),
            {" "}{P.trials.candidate_configurations} of them candidates; {P.trials.imported_strategies} imported strategies judged the same way;
            the multiple-testing bar uses K = {P.trials.K_for_bonferroni} (t ≥ {Number(RESEARCH.prereg.t_bonferroni).toFixed(2)} for Portfolio Eligible).</li>
          <li><b>Costs:</b> Angel One’s intraday charges plus measured slippage by traded-value band; stress tests at 2x and 3x slippage;
            missed entries, partial fills (2% of the bar’s volume) and failed exits are part of the fill model.</li>
          <li><b>Fixed during development, before the freeze:</b> {P.fixes.map((f: any) => f.what).join("; ")}.</li>
          <li><b>After the freeze:</b> {P.post_freeze_note}</li>
        </ul>
        <h4 className="pis-h4">Promotion criteria (long and short judged separately)</h4>
        <div className="pis-detail-grid">
          <dl className="pis-dl">
            <dt>Backtest Qualified</dt>
            <dd>{Object.entries(P.criteria.backtest_qualified).map(([k, v]: [string, any]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</dd>
          </dl>
          <dl className="pis-dl">
            <dt>Portfolio Eligible (after forward paper observation)</dt>
            <dd>{Object.entries(P.criteria.portfolio_eligible).map(([k, v]: [string, any]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</dd>
            <dt>Paused</dt><dd>{Object.entries(P.criteria.paused).map(([k, v]: [string, any]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</dd>
          </dl>
        </div>
      </GlassPanel>

      <GlassPanel title="Sources">
        <div className="pis-scroll">
          <table className="pis-table">
            <thead><tr><th>ID</th><th>Source</th><th>Date</th><th>Market and sample</th><th>Costs in the result?</th><th>Type</th><th>Region</th><th>Finding</th></tr></thead>
            <tbody>{reg.sources.map((s: any) => (
              <tr key={s.id}>
                <td className="pis-strong">{s.id}</td>
                <td className="pis-wrap">{s.link.startsWith("http") ? <a href={s.link} target="_blank" rel="noreferrer">{s.title}</a> : <span>{s.title} ({s.link})</span>}
                  <div className="pis-small pis-muted">{s.authors} · read: {s.read}</div></td>
                <td className="pis-small">{s.date}</td><td className="pis-small pis-wrap">{s.market}; {s.sample}</td>
                <td className="pis-small pis-wrap">{s.costs}</td><td className="pis-small">{s.type}</td><td className="pis-small">{s.region}</td>
                <td className="pis-small pis-wrap">{s.finding}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title={`Isolation and failure tests: ${passed} of ${(tests.checks || []).length} passed`}>
        <ul className="pis-checks">
          {(tests.checks || []).map((c: any) => (
            <li key={c.name} className={c.pass ? "ok" : "bad"}><b>{c.pass ? "PASS" : "FAIL"}</b> {c.name}
              {c.detail ? <span className="pis-muted"> [{c.detail}]</span> : null}</li>))}
        </ul>
        {tests.live_day && (
          <p className="pis-small">One simulated live day ({tests.live_day.day}, the real worker on recorded bars): {tests.live_day.prepare_cpu_s}s of CPU
            {" "}before the open, {tests.live_day.poll_cpu_ms_mean} ms per bar on average ({tests.live_day.poll_cpu_ms_max} ms at most),
            {" "}{tests.live_day.python_heap_peak_mb} MB peak Python heap, {tests.live_day.db_writes} writes to its own database.
            The backend feed route answered a full universe in {tests.feed_route?.full_universe_ms} ms ({Math.round((tests.feed_route?.full_bytes || 0) / 1024)} KB)
            {" "}and an incremental poll in {tests.feed_route?.incremental_ms} ms ({Math.round((tests.feed_route?.incremental_bytes || 0) / 1024)} KB).</p>
        )}
        <p className="pis-note">Still needs production observation: the box’s CPU steal and the backend’s memory cap during a real
          session (the box is CPU-throttled and the backend runs near 800 MB); the Angel stream’s real outages; the backend
          route’s cost under the API cache; disk growth of the desk’s database on a nearly full disk.</p>
      </GlassPanel>
    </div>
  );
}
