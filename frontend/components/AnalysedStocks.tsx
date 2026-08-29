"use client";

/**
 * Analysed Stocks — every NSE name at an all-time high, swept and analysed.
 *
 * THE COVERAGE PANEL IS NOT DECORATION. The request behind this page was "don't miss a
 * single stock", which is a claim about completeness that no single source can support.
 * So the page shows what each net contributed, what had to be seeded, and — stated
 * plainly rather than buried — what could still be missed. A list of 129 stocks with no
 * account of how it was assembled invites the reader to assume it is exhaustive.
 *
 * "ALL-TIME HIGH" IS A VERDICT, NOT A TAG. Chartink's window reaches about 20 years; our
 * own register walks each stock back to its listing date. A candidate is only labelled
 * all-time high if the register agrees. Everything else is shown as the multi-year high it
 * actually is, and the difference is a column rather than a footnote.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import {
  fetchAthUniverseSweep, fetchAthUniverseStatus, buildAthUniverse,
  AthUniverseSnapshot, AthUniverseRowFull,
} from "../lib/api";

const PILLAR_LABEL: Record<string, string> = {
  trend: "Trend", momentum: "Momentum", volume: "Volume & delivery",
  structure: "Position in range", tradability: "Can you trade it",
};
const BIAS_TONE: Record<string, string> = { Bullish: "ok", Neutral: "mid", Bearish: "bad" };
const ACTION_TONE: Record<string, string> = { Buy: "ok", Watch: "mid", Avoid: "bad" };

const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });
const pctf = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
const cls = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : v > 0 ? "gain" : v < 0 ? "loss" : "";

type Filter = "all" | "confirmed" | "near" | "buy" | "confirmed_buy";

export default function AnalysedStocks() {
  const [snap, setSnap] = useState<AthUniverseSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [showCoverage, setShowCoverage] = useState(false);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try { setSnap(await fetchAthUniverseSweep()); setErr(null); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // While a build runs, poll the CHEAP status route — the full snapshot carries every
  // analysed row and re-fetching it every few seconds would be wasteful.
  useEffect(() => {
    if (snap?.state !== "running") {
      if (poll.current) { clearInterval(poll.current); poll.current = null; }
      return;
    }
    poll.current = setInterval(async () => {
      try {
        const st = await fetchAthUniverseStatus();
        if (st.state !== "running") await load();
        else setSnap((p) => ({ ...(p ?? {}), ...st } as AthUniverseSnapshot));
      } catch { /* a failed poll is not worth surfacing; the next one will tell */ }
    }, 4000);
    return () => { if (poll.current) clearInterval(poll.current); };
  }, [snap?.state, load]);

  const rebuild = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await buildAthUniverse();
      if (!r.started) setErr(r.reason ?? "Could not start a build.");
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const rows = (snap?.rows ?? []).filter((r) => {
    const buy = r.verdict?.action === "Buy";
    if (filter === "confirmed") return r.ath_grade === "all_time";
    if (filter === "near") return r.ath_grade === "near_ath";
    if (filter === "buy") return buy;
    if (filter === "confirmed_buy") return buy && r.ath_grade === "all_time";
    return true;
  });

  const cov = snap?.coverage;
  const running = snap?.state === "running";

  return (
    <div className="as">
      {err && <div className="err">{err}</div>}

      <GlassPanel title="All-time-high sweep"
        note={snap?.finished_at ? `built ${new Date(snap.finished_at).toLocaleString()}` : undefined}>
        <p className="lede">
          Every NSE stock at a multi-year or all-time high, pulled from{" "}
          <b>nineteen independent nets</b> — thirteen clauses across Chartink&rsquo;s whole
          cash market, six named public screeners, and our own register of stocks walked
          back to their listing date — then run through the full analysis: trend, momentum,
          delivery, position in range and whether the stock can actually be traded.
          A high is judged on the session&rsquo;s <i>high</i>, so a stock that set a record
          intraday and closed under it still counts as having set one.
        </p>

        <div className="acts">
          <button className="go" disabled={busy || running} onClick={rebuild}>
            {running ? "Sweeping…" : busy ? "Starting…" : snap?.state === "ready" ? "Rebuild sweep" : "Run the sweep"}
          </button>
          {snap?.seconds ? <span className="took">last run took {Math.round(snap.seconds)}s</span> : null}
          {cov && (
            <button className="cov" onClick={() => setShowCoverage(!showCoverage)}>
              {showCoverage ? "hide" : "how complete is this?"}
            </button>
          )}
        </div>

        {running && (
          <div className="prog">
            <div className="bar"><div style={{ width: `${snap?.progress ?? 0}%` }} /></div>
            <div className="stepline">{snap?.step ?? "working"} · {snap?.progress ?? 0}%</div>
            <div className="patience">
              Seeding a stock the register has never seen costs several rate-limited Angel
              calls, so a full sweep takes a few minutes. It runs on the server — you can
              leave this tab.
            </div>
          </div>
        )}
      </GlassPanel>

      {snap?.state === "never built" && !running && (
        <EmptyState title="No sweep yet"
          note="Run the sweep above. It takes a few minutes because every candidate without stored history has to be walked back to its listing date first." />
      )}

      {snap?.state === "ready" && (
        <>
          <div className="stats">
            <Cell label="Candidates found" value={String(snap.candidates ?? 0)}
              note="union of every net" />
            <Cell label="At a true all-time high" value={String(snap.confirmed_ath ?? 0)}
              tone="ok" note="confirmed against our own register" />
            <Cell label="Buyable now" value={String(snap.buyable ?? 0)} tone="ok"
              note="bullish AND tradable" />
            <Cell label="Within 3% of one" value={String(snap.near_ath ?? 0)} tone="mid"
              note="one push from a record" />
            <Cell label="Multi-year high"
              value={String((snap.count ?? 0) - (snap.confirmed_ath ?? 0) - (snap.near_ath ?? 0))}
              note="high, but its record still stands well above" />
          </div>

          {showCoverage && cov && (
            <GlassPanel title="How this list was assembled">
              <div className="tw">
                <table>
                  <thead><tr><th className="l">Net</th><th>Matched</th><th>Non-equity removed</th><th className="l">Status</th></tr></thead>
                  <tbody>
                    {Object.entries(cov.chartink_nets).map(([k, n]) => (
                      <tr key={k}>
                        <td className="l">{n.label}</td>
                        <td>{n.rows}</td>
                        <td className="dim">{n.excluded ?? 0}</td>
                        <td className="l">{n.error ? <span className="bad">{n.error}</span> : "ok"}</td>
                      </tr>
                    ))}
                    <tr className="own">
                      <td className="l">Our own all-time-high register</td>
                      <td>{cov.own_register_hits}</td>
                      <td className="dim">—</td>
                      <td className="l">{cov.register_size} symbols walked to listing date</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="blind">
                <b>What could still be missed.</b> {cov.blind_spot}
              </div>
              <div className="blind soft">
                {cov.excluded_non_equity} index and ETF rows were removed across the nets —
                they are not companies and cannot be bought on an equity desk.
              </div>
            </GlassPanel>
          )}

          <GlassPanel title="The stocks" note={`${rows.length} shown`}>
            <div className="legend">
              <b>All-time high</b> is confirmed against our own register, which walks each
              stock back to its listing date. Chartink&rsquo;s window stops around 20 years,
              so a name it flags may be at a <i>multi-year</i> high while its real record
              still stands — those are labelled as such, not counted as all-time highs.
              Names within 3% show the actual gap, because one push from a record is a
              different setup from one that is 40% below it.
              <br />
              <b>Action</b> is capped by tradability: a stock in a narrow circuit band or
              under ASM reads Avoid however good its chart is.
            </div>

            <div className="filters">
              {([["all", "All"], ["confirmed", "At an all-time high"],
                 ["near", "Within 3% of one"], ["buy", "Buy only"],
                 ["confirmed_buy", "All-time high + Buy"]] as const)
                .map(([k, l]) => (
                  <button key={k} className={filter === k ? "on" : ""}
                    onClick={() => setFilter(k as Filter)}>{l}</button>
              ))}
            </div>

            {!rows.length ? <EmptyState title="Nothing matches that filter" /> : (
              <div className="tw">
                <table>
                  <thead><tr>
                    <th className="l">Stock</th><th className="l">High</th><th>Score</th>
                    <th className="l">Bias</th><th className="l">Action</th>
                    <th>LTP</th><th>1m</th><th>6m</th>
                    <th className="l">Why</th><th></th>
                  </tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <Row key={r.symbol} r={r} open={open === r.symbol}
                        toggle={() => setOpen(open === r.symbol ? null : r.symbol)} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {!snap && !err && (
        <GlassPanel title="Loading">
          <div className="sk">{Array.from({ length: 5 }).map((_, i) =>
            <Skeleton key={i} height={26} />)}</div>
        </GlassPanel>
      )}

      <style jsx>{`
        .as { display: flex; flex-direction: column; gap: 16px; }
        .err {
          border: 1px solid var(--loss); background: rgba(220,38,38,0.08);
          color: var(--loss); border-radius: 10px; padding: 10px 14px; font-size: 12.5px;
        }
        .lede { font-size: 12.5px; line-height: 1.65; color: var(--text-secondary); margin: 0 0 12px; max-width: 94ch; }
        .lede b { color: var(--text-primary); }
        .acts { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .go {
          padding: 8px 22px; border-radius: 8px; font-size: 13px; font-weight: 600;
          border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer;
        }
        .go:disabled { opacity: 0.5; cursor: default; }
        .took { font-size: 11.5px; color: var(--text-muted); }
        .cov {
          margin-left: auto; padding: 5px 13px; border-radius: 999px; font-size: 11.5px;
          border: 1px dashed var(--border); background: transparent; color: var(--text-muted);
          cursor: pointer;
        }
        .prog { margin-top: 14px; }
        .prog .bar { height: 6px; border-radius: 999px; background: var(--canvas-soft); overflow: hidden; }
        .prog .bar div { height: 100%; background: var(--accent); transition: width 0.4s ease; }
        .stepline { font-size: 12px; color: var(--text-secondary); margin-top: 7px; }
        .patience { font-size: 11px; color: var(--text-muted); margin-top: 4px; line-height: 1.5; max-width: 80ch; }
        .stats { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
        .legend {
          font-size: 12px; line-height: 1.65; color: var(--text-muted);
          border: 1px solid var(--border); border-radius: 10px; padding: 10px 13px;
          margin-bottom: 12px; max-width: 96ch; background: var(--canvas-soft);
        }
        .legend b { color: var(--text-primary); }
        .blind {
          font-size: 11.5px; line-height: 1.6; color: var(--text-secondary);
          border: 1px dashed rgba(217,119,6,0.4); background: rgba(217,119,6,0.06);
          border-radius: 9px; padding: 10px 12px; margin-top: 12px; max-width: 96ch;
        }
        .blind.soft { border-color: var(--border); background: var(--canvas-soft); color: var(--text-muted); }
        .filters { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
        .filters button {
          padding: 5px 13px; border-radius: 999px; font-size: 12px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas-soft); color: var(--text-secondary);
        }
        .filters button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
        .sk { display: flex; flex-direction: column; gap: 8px; }
        .tw { overflow-x: auto; }
        .tw table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        .tw :global(th) {
          text-align: right; padding: 8px 10px; font-weight: 600; font-size: 11px;
          text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted);
          border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        .tw :global(th.l) { text-align: left; }
        .tw td { text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--border-soft, var(--border)); color: var(--text-secondary); }
        .tw td.l { text-align: left; }
        .tw td.dim { color: var(--text-faint); }
        .tw tr.own td { border-top: 1px solid var(--border); font-weight: 600; }
        .bad { color: var(--loss); }
      `}</style>
    </div>
  );
}

function Cell({ label, value, note, tone }: {
  label: string; value: string; note?: string; tone?: string;
}) {
  return (
    <div className="cell">
      <div className="lab">{label}</div>
      <div className={`val ${tone ?? ""}`}>{value}</div>
      {note && <div className="nt">{note}</div>}
      <style jsx>{`
        .cell { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--canvas); }
        .lab { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 5px; }
        .val { font-size: 22px; font-weight: 700; color: var(--text-primary); }
        .val.ok { color: var(--gain); }
        .val.mid { color: #b45309; }
        .nt { font-size: 10.5px; color: var(--text-faint); margin-top: 4px; line-height: 1.45; }
      `}</style>
    </div>
  );
}

function Row({ r, open, toggle }: { r: AthUniverseRowFull; open: boolean; toggle: () => void }) {
  const v = r.verdict;
  return (
    <>
      <tr>
        <td className="l sym">
          <b>{r.symbol}</b>
          {r.market_cap_cr ? <div className="sub">₹{r.market_cap_cr.toLocaleString("en-IN")}cr</div> : null}
        </td>
        <td className="l">
          <span className={`ath ${r.ath_grade}`} title={r.ath_basis}>
            {r.ath_grade === "all_time" ? "all-time"
             : r.ath_grade === "near_ath" ? `${Math.abs(r.pct_from_ath ?? 0).toFixed(1)}% away`
             : r.ath_grade === "multi_year" ? "multi-year"
             : "unverified"}
          </span>
        </td>
        <td>{v ? <span className={`sc ${v.score >= 72 ? "ok" : v.score >= 50 ? "mid" : "bad"}`}>{v.score}</span> : "—"}</td>
        <td className="l">{v ? <span className={`tag ${BIAS_TONE[v.bias]}`}>{v.bias}</span> : "—"}</td>
        <td className="l">{v ? <span className={`tag ${ACTION_TONE[v.action]}`}>{v.action}</span> : "—"}</td>
        <td>{num(r.ltp)}</td>
        <td className={cls(r.returns?.["1m"])}>{pctf(r.returns?.["1m"])}</td>
        <td className={cls(r.returns?.["6m"])}>{pctf(r.returns?.["6m"])}</td>
        <td className="l why">{v?.action_why ?? r.note}</td>
        <td><button className="exp" onClick={toggle}>{open ? "hide" : "detail"}</button></td>
      </tr>
      {open && (
        <tr className="det">
          <td colSpan={10}>
            <div className="grid">
              <div className="card">
                <h4>What the verdict rests on</h4>
                {Object.entries(r.pillars ?? {}).map(([k, p]) => (
                  <div key={k} className={`pill ${p.verdict}`}>
                    <div className="ph"><span className="dot" /><b>{PILLAR_LABEL[k] ?? k}</b><span className="ps">{p.score}</span></div>
                    <div className="pn">{p.note}</div>
                  </div>
                ))}
              </div>
              <div className="card">
                <h4>The high</h4>
                <Kv k="Verdict" v={r.ath_basis} />
                <Kv k="Stored all-time high" v={num(r.stored_ath)} />
                <Kv k="Distance from it" v={pctf(r.pct_from_ath)} />
                <Kv k="Set on" v={r.stored_ath_date ?? "—"} />
                <Kv k="History walked" v={r.history_sessions ? `${r.history_sessions} sessions` : "—"} />
                <Kv k="52-week high" v={num(r.levels?.week52_high)} />
                <Kv k="Extension past 20d break" v={pctf(r.levels?.extension_pct)} />
                <div className="sub2">Found by</div>
                <div className="chips">
                  {r.nets.map((n) => <span key={n}>{n}</span>)}
                  {r.from_own_register && <span className="own">our own register</span>}
                </div>
              </div>
              <div className="card">
                <h4>Next target &amp; plan</h4>
                {r.next_target?.target ? (
                  <>
                    <div className="big">{num(r.next_target.target)} <i>{pctf(r.next_target.upside_pct)}</i></div>
                    <div className="meth">{r.next_target.method}</div>
                  </>
                ) : <div className="none">No level worth naming above here.</div>}
                {r.plan && (
                  <div style={{ marginTop: 10 }}>
                    <Kv k="Entry" v={num(r.plan.entry)} />
                    <Kv k="Stop" v={`${num(r.plan.stop)} (${pctf(r.plan.stop_pct)})`} />
                    <Kv k="Target" v={`${num(r.plan.target)} (${pctf(r.plan.target_pct)})`} />
                  </div>
                )}
                <div className="sub2">Patterns</div>
                {r.patterns?.length ? (
                  <div className="chips">
                    {r.patterns.slice(0, 6).map((p, i) => (
                      <span key={i} className={p.direction === "bullish" ? "up" : "dn"}>
                        {p.label}<i>{p.timeframe}</i>
                      </span>))}
                  </div>
                ) : <div className="none">None.</div>}
              </div>
            </div>
          </td>
        </tr>
      )}

      <style jsx>{`
        td { vertical-align: top; }
        td.sym { white-space: nowrap; }
        td.sym b { color: var(--text-primary); font-weight: 650; }
        .sub { font-size: 10px; color: var(--text-faint); font-weight: 400; }
        td.why { color: var(--text-muted); font-size: 11.5px; line-height: 1.5; min-width: 230px; max-width: 440px; }
        .ath { display: inline-block; padding: 2px 8px; border-radius: 5px; font-size: 10.5px; font-weight: 700; white-space: nowrap; }
        .ath.all_time { background: rgba(22,163,74,0.15); color: var(--gain); }
        .ath.near_ath { background: rgba(217,119,6,0.12); color: #b45309; }
        .ath.multi_year { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--border); }
        /* unverified is dashed and grey on purpose — no register entry is an absence of
           evidence, not a weaker kind of high. */
        .ath.unverified { background: transparent; color: var(--text-faint); border: 1px dashed var(--border); }
        .sc { display: inline-block; min-width: 32px; padding: 2px 8px; border-radius: 6px; font-weight: 700; font-size: 12px; }
        .sc.ok { background: rgba(22,163,74,0.14); color: var(--gain); }
        .sc.mid { background: rgba(217,119,6,0.13); color: #b45309; }
        .sc.bad { background: rgba(220,38,38,0.13); color: var(--loss); }
        .tag { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 11.5px; font-weight: 600; }
        .tag.ok { background: rgba(22,163,74,0.14); color: var(--gain); }
        .tag.mid { background: rgba(217,119,6,0.13); color: #b45309; }
        .tag.bad { background: rgba(220,38,38,0.13); color: var(--loss); }
        .exp { padding: 3px 10px; border-radius: 6px; font-size: 11px; cursor: pointer; border: 1px solid var(--border); background: var(--canvas); color: var(--text-secondary); }
        .det td { background: var(--canvas-soft); padding: 14px; text-align: left; }
        .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(265px, 1fr)); align-items: start; }
        .card { border: 1px solid var(--border); border-radius: 11px; padding: 12px 14px; background: var(--canvas); }
        h4 { margin: 0 0 9px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: 700; }
        .pill { padding: 7px 0; border-bottom: 1px solid var(--border-soft, var(--border)); }
        .pill:last-child { border-bottom: none; }
        .ph { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-primary); }
        .ph .ps { margin-left: auto; font-weight: 700; }
        .pn { font-size: 11.5px; line-height: 1.5; color: var(--text-muted); margin-top: 3px; }
        .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
        .pill.strong .dot { background: var(--gain); } .pill.strong .ps { color: var(--gain); }
        .pill.ok .dot { background: var(--gain); opacity: 0.55; }
        .pill.weak .dot { background: #d97706; } .pill.weak .ps { color: #b45309; }
        .pill.bad .dot { background: var(--loss); } .pill.bad .ps { color: var(--loss); }
        .pill.unknown .dot { background: var(--text-faint); }
        .pill.unknown .pn { font-style: italic; }
        .big { font-size: 19px; font-weight: 700; color: var(--text-primary); }
        .big i { font-size: 12.5px; font-style: normal; color: var(--gain); margin-left: 6px; }
        .meth { font-size: 11px; color: var(--text-muted); margin-top: 3px; line-height: 1.5; }
        .none { font-size: 11.5px; color: var(--text-faint); }
        .sub2 { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-faint); margin: 12px 0 6px; }
        .chips { display: flex; flex-wrap: wrap; gap: 5px; }
        .chips span { display: inline-flex; align-items: baseline; gap: 4px; padding: 3px 8px; border-radius: 6px; font-size: 10.5px; border: 1px solid var(--border); background: var(--canvas-soft); color: var(--text-secondary); }
        .chips span.own { border-color: var(--accent); color: var(--accent); }
        .chips span.up { border-color: rgba(22,163,74,0.35); color: var(--gain); }
        .chips span.dn { border-color: rgba(220,38,38,0.32); color: var(--loss); }
        .chips i { font-size: 9px; font-style: normal; color: var(--text-faint); }
        .gain { color: var(--gain); font-weight: 600; }
        .loss { color: var(--loss); font-weight: 600; }
      `}</style>
    </>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div className="kv">
      <span>{k}</span><b>{v}</b>
      <style jsx>{`
        .kv { display: flex; justify-content: space-between; gap: 10px; font-size: 11.5px; padding: 3px 0; color: var(--text-muted); }
        .kv b { color: var(--text-secondary); font-weight: 600; text-align: right; }
      `}</style>
    </div>
  );
}
