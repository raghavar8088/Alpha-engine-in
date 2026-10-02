"use client";

/*
 * Today's Playbook — the stock-selection layer in one place: the pre-market brief, the
 * Scanner Board, the one side signal, and the evidence behind every list.
 *
 * The research this page is built on (2026-10-02, 200 stocks, 516 sessions) found that
 * WHERE a stock will move is predictable and WHICH WAY is not. So every list carries the
 * badge the evidence earned: PROVEN lists say where the moves will be; the CANDIDATE
 * opening-range break is the only list with a side, and it is under test; CONTEXT lists
 * are direction ideas that failed out of sample and are never a reason to go long or
 * short; FORWARD data has no history yet. Nothing on this page places an order.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import { copySymbols } from "../../lib/copySymbols";
import {
  fetchEdgeReport,
  fetchSelectionBoard,
  fetchSelectionBrief,
  fetchSelectionModel,
  fetchSelectionSnapshot,
  fetchSelectionSnapshots,
  refreshing,
  type EdgeReport,
  type EvidenceStatus,
  type ScannerBoard,
  type ScannerList,
  type ScannerRow,
  type SelectionBrief,
  type SelectionModel,
} from "../../lib/api";

const PROVEN = ["expected_move", "in_play", "volatility", "gappers", "opening_drive", "results_today"];
const CONTEXT = ["day_change", "relative_strength", "oi_buildup", "delivery", "near_extremes", "preopen"];
const STATUS_LABEL: Record<EvidenceStatus, string> = {
  proven: "Proven · where",
  candidate: "Candidate · side",
  context: "Context only",
  forward: "Forward test",
};
const NOTIFY_KEY = "playbook.notify-breaks";

const signed = (v: number | null | undefined, dp = 0, unit = "") =>
  v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(dp)}${unit}`;
const pct = (v: number | null | undefined, dp = 0) => (v == null ? "–" : `${(v * 100).toFixed(dp)}%`);
const num = (v: number | null | undefined) => (v == null ? "–" : Math.round(v).toLocaleString("en-IN"));
const ist = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "–";

function inSession(): boolean {
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const m = now.getHours() * 60 + now.getMinutes();
  return now.getDay() >= 1 && now.getDay() <= 5 && m >= 8 * 60 + 50 && m <= 15 * 60 + 35;
}

function Badge({ status }: { status: EvidenceStatus }) {
  return <span className={`badge b-${status}`}>{STATUS_LABEL[status]}</span>;
}

function CopyButton({ symbols }: { symbols: string[] }) {
  const [done, setDone] = useState(false);
  if (!symbols.length) return null;
  return (
    <button
      className="copy"
      title="Copy as NSE:AAA,NSE:BBB for a TradingView watchlist"
      onClick={async () => {
        await copySymbols(symbols, "tv");
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? "Copied" : `Copy ${symbols.length} to TradingView`}
    </button>
  );
}

function ListTable({ list, fresh }: { list: ScannerList; fresh?: Set<string> }) {
  if (!list.rows.length) {
    return <div className="empty">Nothing on this list at this time.</div>;
  }
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>#</th>
            <th>Symbol</th>
            <th>Reading</th>
            <th className="r">Expected move</th>
            <th className="r">Change</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((r, i) => (
            <tr key={`${r.symbol}-${i}`} className={fresh?.has(`${r.symbol}:${r.side}`) ? "fresh" : ""}>
              <td className="muted">{i + 1}</td>
              <td className="sym">
                {r.symbol}
                {r.side && <span className={`side ${r.side === "LONG" ? "long" : "short"}`}>{r.side}</span>}
              </td>
              <td>{r.value}</td>
              <td className="r">{r.expected_move_bp != null ? `${r.expected_move_bp.toFixed(0)} bp` : "–"}</td>
              <td className={`r ${(r.chg_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{signed(r.chg_pct, 2, "%")}</td>
              <td className="why">{r.reasons.join(" · ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListCard({ name, list, fresh }: { name: string; list: ScannerList; fresh?: Set<string> }) {
  return (
    <div className="card" id={`list-${name}`}>
      <div className="card-head">
        <div>
          <div className="card-title">
            {list.title} <Badge status={list.status} />
          </div>
          <div className="evidence">{list.evidence}</div>
        </div>
        <CopyButton symbols={list.rows.map((r) => r.symbol)} />
      </div>
      <ListTable list={list} fresh={fresh} />
    </div>
  );
}

export default function TodaysPlaybook() {
  const [brief, setBrief] = useState<SelectionBrief | null>(null);
  const [board, setBoard] = useState<ScannerBoard | null>(null);
  const [model, setModel] = useState<SelectionModel | null>(null);
  const [edge, setEdge] = useState<EdgeReport | null>(null);
  const [snapDays, setSnapDays] = useState<string[]>([]);
  const [snapTimes, setSnapTimes] = useState<string[]>([]);
  const [view, setView] = useState<{ date: string; time: string } | null>(null); // null = live
  const [provenTab, setProvenTab] = useState("expected_move");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notify, setNotify] = useState(false);
  const seenBreaks = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      setNotify(localStorage.getItem(NOTIFY_KEY) === "1");
    } catch {
      /* private window: the toggle simply starts off */
    }
  }, []);

  const loadBoard = useCallback(async () => {
    const b = view ? await fetchSelectionSnapshot(view.date, view.time) : await fetchSelectionBoard();
    setBoard(b);
    if (!view) {
      // New opening-range breaks since the last read: highlight, and notify if asked.
      const now = new Set(
        (b.scanners.or_break?.rows ?? []).filter((r) => r.side).map((r) => `${r.symbol}:${r.side}`),
      );
      if (seenBreaks.current) {
        const added = [...now].filter((k) => !seenBreaks.current!.has(k));
        if (added.length) {
          setFresh(new Set(added));
          if (notify && typeof Notification !== "undefined" && Notification.permission === "granted") {
            new Notification("Opening-range break (candidate)", {
              body: added.map((k) => k.replace(":", " ")).join(", ") + " — under test, not a proven signal",
            });
          }
        }
      }
      seenBreaks.current = now;
    }
  }, [view, notify]);

  const loadAll = useCallback(async () => {
    setBusy(true);
    try {
      const [br, , md, ed, sn] = await Promise.all([
        fetchSelectionBrief(),
        loadBoard(),
        fetchSelectionModel().catch(() => null),
        fetchEdgeReport().catch(() => ({})),
        fetchSelectionSnapshots().catch(() => null),
      ]);
      setBrief(br);
      setModel(md);
      setEdge(ed && "date" in ed ? (ed as EdgeReport) : null);
      if (sn) setSnapDays(sn.days);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed to load");
    } finally {
      setBusy(false);
    }
  }, [loadBoard]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Live view in the session: the board every minute, the brief every five.
  useEffect(() => {
    if (view) return;
    const b = setInterval(() => inSession() && loadBoard().catch(() => undefined), 60000);
    const r = setInterval(() => inSession() && fetchSelectionBrief().then(setBrief).catch(() => undefined), 300000);
    return () => {
      clearInterval(b);
      clearInterval(r);
    };
  }, [view, loadBoard]);

  const pickDay = async (d: string) => {
    if (!d) {
      setView(null);
      return;
    }
    const sn = await fetchSelectionSnapshots(d);
    setSnapTimes(sn.times);
    if (sn.times.length) setView({ date: d, time: sn.times[sn.times.length - 1] });
  };

  const toggleNotify = async () => {
    let on = !notify;
    if (on && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      on = (await Notification.requestPermission()) === "granted";
    }
    setNotify(on);
    try {
      localStorage.setItem(NOTIFY_KEY, on ? "1" : "0");
    } catch {
      /* not persisted in a private window */
    }
  };

  const proven = useMemo(() => PROVEN.filter((k) => board?.scanners[k]), [board]);
  const orb = board?.scanners.or_break;
  const sides = orb?.rows.filter((r) => r.side) ?? [];
  const watching = orb?.rows.filter((r) => !r.side) ?? [];
  const gap = brief?.gap_forecast;
  const ho = gap?.model.held_out;

  return (
    <div className="pb-root">
      <PageHeader
        crumb="Today's Playbook"
        title="Today's Playbook"
        subtitle={
          brief ? (
            <>
              Session {brief.session}
              {!brief.trading_today && brief.closed_reason ? ` — today is closed (${brief.closed_reason})` : ""}
              {board ? ` · board ${view ? `snapshot ${view.date} ${view.time}` : `live as of ${board.hhmm} IST`}` : ""}
            </>
          ) : (
            "Which stocks to watch, and what the evidence says about each list"
          )
        }
        onRefresh={() => refreshing(loadAll)}
        refreshing={busy}
        actions={
          <div className="view-pick">
            <select value={view?.date ?? ""} onChange={(e) => pickDay(e.target.value)} title="Live board or a frozen snapshot">
              <option value="">Live</option>
              {snapDays.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
            {view && (
              <select value={view.time} onChange={(e) => setView({ date: view.date, time: e.target.value })}>
                {snapTimes.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            )}
            <button className={`notify ${notify ? "on" : ""}`} onClick={toggleNotify}
              title="A browser notification when a top expected-move name breaks its opening range">
              {notify ? "Break alerts on" : "Break alerts off"}
            </button>
          </div>
        }
      />
      {err && <ErrorBanner message={`Couldn't load the playbook: ${err}`} />}

      <div className="truth">
        <strong>What this page can and cannot tell you.</strong> Which stocks will move a lot today is predictable
        (the model&rsquo;s held-out top 20 moved {model?.model?.oos?.["0945"]?.top20_move_bp?.toFixed(0) ?? "~177"} bp
        against {model?.model?.oos?.["0945"]?.all_move_bp?.toFixed(0) ?? "~99"} bp for everyone). Which way they move
        is not: every scanner-based direction rule failed out of sample. The only side shown is the opening-range
        break, where price picks it, and that is still under test.
        <div className="legend">
          {(["proven", "candidate", "context", "forward"] as EvidenceStatus[]).map((s) => (
            <span key={s}>
              <Badge status={s} /> {brief?.evidence.statuses[s]}
            </span>
          ))}
        </div>
      </div>

      {/* ── the pre-market brief ─────────────────────────────────────────────── */}
      <div className="tiles">
        <div className="tile">
          <div className="k">Expected NIFTY gap <Badge status="proven" /></div>
          <div className={`v ${(gap?.pred_bp ?? 0) >= 0 ? "gain" : "loss"}`}>
            {gap ? `${signed(gap.pred_bp)} bp` : "–"}
          </div>
          <div className="s">
            {gap ? `${gap.call}, ${gap.confidence} confidence${gap.provisional ? " (provisional)" : ""}` : "no global read yet"}
          </div>
          {gap && <div className="s">{gap.basis}: S&amp;P {signed(gap.us_move_bp)} bp. Typical gap ±{gap.typical_abs_gap_bp.toFixed(0)} bp.</div>}
          {ho && (
            <div className="s faint">
              Held out ({ho.sessions} sessions): direction right {pct(ho.direction_hit)}, {ho.big_direction_hit != null ? `${pct(ho.big_direction_hit)} on 30 bp+ calls` : ""}.
              Says nothing about after 09:45.
            </div>
          )}
        </div>
        <div className="tile">
          <div className="k">India VIX <Badge status="proven" /></div>
          <div className="v">{brief?.vix ? brief.vix.level.toFixed(2) : "–"}</div>
          <div className="s">
            {brief?.vix ? `${brief.vix.regime} — ${pct(brief.vix.percentile_1y)} of the last year was lower` : ""}
          </div>
          <div className="s faint">{brief?.vix?.means}</div>
        </div>
        <div className="tile">
          <div className="k">How big a day <Badge status="proven" /></div>
          <div className="v">{brief?.expected_day ? `${brief.expected_day.ratio.toFixed(2)}×` : "–"}</div>
          <div className="s">
            {brief?.expected_day
              ? `${brief.expected_day.universe_expected_move_bp.toFixed(0)} bp expected for the average stock vs ${brief.expected_day.typical_bp.toFixed(0)} bp usually (as of ${brief.expected_day.as_of})`
              : ""}
          </div>
        </div>
        <div className="tile">
          <div className="k">Results today <Badge status="proven" /></div>
          <div className="v">{brief ? brief.results.in_universe_today.length : "–"}</div>
          <div className="s">
            {brief?.results.in_universe_today.length
              ? brief.results.in_universe_today.slice(0, 8).join(", ")
              : "none in the 200-stock universe"}
          </div>
          <div className="s faint">{brief ? `${brief.results.next_7_days} results due in the next 7 days` : ""}</div>
        </div>
        {brief?.preopen?.stocks ? (
          <div className="tile">
            <div className="k">NSE pre-open <Badge status="forward" /></div>
            <div className="v">{brief.preopen.advances}/{brief.preopen.declines}</div>
            <div className="s">advances / declines at {brief.preopen.nse_time ?? "09:08"}</div>
          </div>
        ) : null}
      </div>

      {/* ── where the moves will be (proven) ─────────────────────────────────── */}
      <GlassPanel title="Where the moves will be" note="proven lists: use them to choose WHAT to trade, not which way">
        <div className="tabs">
          {proven.map((k) => (
            <button key={k} className={`tab ${provenTab === k ? "on" : ""}`} onClick={() => setProvenTab(k)}>
              {board!.scanners[k].title} <span className="cnt">{board!.scanners[k].count}</span>
            </button>
          ))}
        </div>
        {board?.scanners[provenTab] && <ListCard name={provenTab} list={board.scanners[provenTab]} />}
        {board?.model && (
          <div className="foot">
            Model trained {new Date(board.model.trained_at).toLocaleDateString("en-IN")} on {num(board.model.samples)} stock-days;
            this board ranked with {Object.entries(board.model.variants).map(([k, v]) => `${v} × ${k}`).join(", ")}
            {" "}(pre = before the open, open = with the gap, 0945 = with the first half hour).
          </div>
        )}
      </GlassPanel>

      {/* ── the one side signal (candidate) ──────────────────────────────────── */}
      <GlassPanel title="Which way: the opening-range break" note="candidate: price picks the side; under test, not proven">
        <div className="evidence pad">{brief?.stock_bias.rule ?? orb?.evidence}</div>
        {sides.length ? (
          <ListTable list={{ ...(orb as ScannerList), rows: sides }} fresh={fresh} />
        ) : (
          <div className="empty">No top expected-move name has broken its 09:15–09:45 range yet.</div>
        )}
        {watching.length > 0 && (
          <>
            <div className="sub-h">Inside their range — the levels to watch</div>
            <div className="chips">
              {watching.map((r: ScannerRow) => (
                <span key={r.symbol} className="chip">
                  <b>{r.symbol}</b> {r.or_low?.toFixed(2)} / {r.or_high?.toFixed(2)}
                </span>
              ))}
            </div>
          </>
        )}
        <div className="foot">
          Two strategies trade exactly this rule on paper in the Intraday Stocks tournament
          (&ldquo;Selected ORB 30-min / 15-min&rdquo;), registered with frozen expectations on 2 Oct 2026.
          Their forward record below decides whether it is real.
        </div>
      </GlassPanel>

      {/* ── context lists ────────────────────────────────────────────────────── */}
      <GlassPanel title="Context" note="direction ideas that FAILED out of sample — shown because traders look at them, never a trigger">
        <div className="grid2">
          {CONTEXT.filter((k) => board?.scanners[k]).map((k) => (
            <details key={k} className="ctx">
              <summary>
                {board!.scanners[k].title} <span className="cnt">{board!.scanners[k].count}</span>{" "}
                <Badge status={board!.scanners[k].status} />
              </summary>
              <ListCard name={k} list={board!.scanners[k]} />
            </details>
          ))}
        </div>
      </GlassPanel>

      {/* ── global and positioning ───────────────────────────────────────────── */}
      <div className="grid2">
        <GlassPanel title="Global cues" note={brief?.global.snapshot_of ?? undefined}>
          <table className="tbl">
            <thead>
              <tr><th>Market</th><th className="r">Last session</th><th className="r">Now</th><th>Used for</th></tr>
            </thead>
            <tbody>
              {(brief?.global.series ?? []).map((g) => (
                <tr key={g.key}>
                  <td>{g.label}</td>
                  <td className={`r ${(g.session_ret_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{signed(g.session_ret_pct, 2, "%")}</td>
                  <td className={`r ${(g.live_chg_pct ?? 0) >= 0 ? "gain" : "loss"}`}>{signed(g.live_chg_pct, 2, "%")}</td>
                  <td className="muted">{g.used_for}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="foot">Only the S&amp;P 500 feeds the gap forecast: adding the others made it worse out of sample.</div>
        </GlassPanel>
        <GlassPanel title="Positioning and breadth" note="context only">
          {brief?.breadth_prev && (
            <div className="kv">
              <span>Breadth {brief.breadth_prev.session}</span>
              <b>
                market {brief.breadth_prev.market.advances}/{brief.breadth_prev.market.declines}, universe{" "}
                {brief.breadth_prev.universe.advances}/{brief.breadth_prev.universe.declines}
              </b>
            </div>
          )}
          {brief?.positioning &&
            ["FII", "Client", "Pro", "DII"].map((who) => {
              const p = brief.positioning![who];
              if (!p || typeof p === "string") return null;
              return (
                <div className="kv" key={who}>
                  <span>{who} index futures</span>
                  <b>
                    {pct(p.long_share)} long · net {num(p.net)}
                    {p.net_change != null ? ` (${p.net_change >= 0 ? "+" : ""}${num(p.net_change)} on the day)` : ""}
                  </b>
                </div>
              );
            })}
          <div className="foot">
            {brief?.evidence.market.fii_positioning?.evidence} {brief?.evidence.market.breadth?.evidence}
          </div>
        </GlassPanel>
      </div>

      {/* ── is it working ────────────────────────────────────────────────────── */}
      <GlassPanel title="Is it working?" note="held-out numbers from the research, then the live record">
        <div className="tiles">
          <div className="tile">
            <div className="k">Expected-move ranking, held out</div>
            <div className="v">{model?.model?.oos?.["0945"]?.rank_ic?.toFixed(2) ?? "–"}</div>
            <div className="s">rank correlation with the 09:45→15:00 move over {model?.model?.oos?.["0945"]?.days ?? "–"} sessions</div>
          </div>
          <div className="tile">
            <div className="k">… live since launch</div>
            <div className="v">{model?.live_record.mean_rank_ic?.toFixed(2) ?? "–"}</div>
            <div className="s">
              {model?.live_record.days.length
                ? `${model.live_record.days.length} sessions; top 20 moved ${model.live_record.mean_lift_top20?.toFixed(2)}× the average`
                : "scored after each close from 5 Oct 2026"}
            </div>
          </div>
          <div className="tile">
            <div className="k">Gap forecast, live</div>
            <div className="v">{brief?.gap_record.direction_hit != null ? pct(brief.gap_record.direction_hit) : "–"}</div>
            <div className="s">
              {brief?.gap_record.scored ? `direction right over ${brief.gap_record.scored} sessions; off by ${brief.gap_record.mae_bp} bp on average` : "scored after each close"}
            </div>
          </div>
        </div>
        {edge?.selection?.incubation?.length ? (
          <table className="tbl">
            <thead>
              <tr><th>Pre-registered strategy</th><th>Status</th><th className="r">Trades</th>
                <th className="r">Forward ₹/trade</th><th className="r">Expected ₹/trade</th><th className="r">z vs expected</th></tr>
            </thead>
            <tbody>
              {edge.selection.incubation.map((s) => (
                <tr key={s.strategy_id}>
                  <td>{s.strategy_id === "iv2_orb_sel30" ? "Selected ORB 30-min" : s.strategy_id === "iv2_orb_sel15" ? "Selected ORB 15-min" : s.strategy_id}</td>
                  <td>{s.status}</td>
                  <td className="r">{s.trades}</td>
                  <td className={`r ${(s.forward_mean ?? 0) >= 0 ? "gain" : "loss"}`}>{s.forward_mean != null ? num(s.forward_mean) : "–"}</td>
                  <td className="r">{num(s.expected_mean)}</td>
                  <td className="r">{s.z_vs_expected?.toFixed(2) ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">
            The pre-registered strategies&rsquo; forward record appears in the edge report after their first session.
            A verdict needs at least 40 trades; confirming an edge this size takes a few hundred.
          </div>
        )}
      </GlassPanel>

      {/* ── the evidence registry ────────────────────────────────────────────── */}
      <GlassPanel title="Every input considered" note="the research verdict behind each badge">
        <table className="tbl">
          <thead>
            <tr><th>Input</th><th>Verdict</th><th>Predicts</th><th>Evidence</th></tr>
          </thead>
          <tbody>
            {brief &&
              [...Object.values(brief.evidence.market), ...Object.values(brief.evidence.stock_lists)].map((e) => (
                <tr key={e.title}>
                  <td className="sym">{e.title}</td>
                  <td><Badge status={e.status} /></td>
                  <td className="muted">{e.predicts ?? (e.use === "where" ? "how far" : e.use === "side" ? "which way (under test)" : "nothing")}</td>
                  <td className="why">{e.evidence}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </GlassPanel>

      <style jsx global>{`
        .pb-root { display: flex; flex-direction: column; gap: 16px; }
        .pb-root .truth { font-size: 12.5px; color: var(--text-muted); padding: 12px 14px; border-radius: 12px;
          background: var(--canvas-soft); border: 1px solid var(--panel-border); line-height: 1.55; }
        .pb-root .truth strong { color: var(--text); }
        .pb-root .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px; font-size: 11.5px; }
        .pb-root .badge { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.03em;
          padding: 2px 7px; border-radius: 999px; white-space: nowrap; vertical-align: middle; }
        .pb-root .b-proven { background: var(--gain-dim); color: var(--gain); }
        .pb-root .b-candidate { background: var(--accent-dim); color: var(--accent-hover); }
        .pb-root .b-context { background: var(--canvas-edge); color: var(--text-muted); }
        .pb-root .b-forward { background: var(--purple-dim); color: var(--purple); }
        .pb-root .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
        .pb-root .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; padding: 12px 14px; }
        .pb-root .k { font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
          color: var(--text-muted); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .pb-root .v { font-size: 22px; font-weight: 700; margin: 4px 0 2px; font-variant-numeric: tabular-nums; }
        .pb-root .s { font-size: 11.5px; color: var(--text-muted); line-height: 1.45; }
        .pb-root .faint { color: var(--text-faint); margin-top: 4px; }
        .pb-root .gain { color: var(--gain); }
        .pb-root .loss { color: var(--loss); }
        .pb-root .muted { color: var(--text-muted); }
        .pb-root .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        .pb-root .tab { font-size: 12px; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--panel-border);
          background: var(--panel); color: var(--text-muted); cursor: pointer; }
        .pb-root .tab.on { background: var(--purple-dim); color: var(--purple); border-color: transparent; font-weight: 600; }
        .pb-root .cnt { font-size: 10.5px; color: var(--text-faint); margin-left: 3px; }
        .pb-root .card-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 8px; }
        .pb-root .card-title { font-size: 13px; font-weight: 700; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        .pb-root .evidence { font-size: 11.5px; color: var(--text-muted); margin-top: 3px; }
        .pb-root .evidence.pad { margin: 0 0 10px; }
        .pb-root .copy, .pb-root .notify { font-size: 11.5px; padding: 5px 10px; border-radius: 8px; cursor: pointer;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); white-space: nowrap; }
        .pb-root .notify.on { background: var(--accent-dim); border-color: transparent; color: var(--accent-hover); }
        .pb-root .view-pick { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .pb-root .view-pick select { font-size: 12px; padding: 5px 8px; border-radius: 8px; border: 1px solid var(--panel-border);
          background: var(--panel); color: var(--text); }
        .pb-root .tbl-wrap { overflow-x: auto; }
        .pb-root .tbl { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .pb-root .tbl th { text-align: left; font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
          color: var(--text-muted); padding: 6px 8px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .pb-root .tbl td { padding: 6px 8px; border-bottom: 1px solid var(--canvas-soft); vertical-align: top; }
        .pb-root .tbl .r { text-align: right; white-space: nowrap; }
        .pb-root .tbl .sym { font-weight: 600; white-space: nowrap; }
        .pb-root .tbl .why { color: var(--text-muted); font-size: 11.5px; min-width: 220px; }
        .pb-root .tbl tr.fresh td { background: var(--accent-dim); }
        .pb-root .side { font-size: 9.5px; font-weight: 700; margin-left: 6px; padding: 1px 5px; border-radius: 4px; }
        .pb-root .side.long { background: var(--gain-dim); color: var(--gain); }
        .pb-root .side.short { background: var(--loss-dim); color: var(--loss); }
        .pb-root .empty { padding: 14px 4px; font-size: 12px; color: var(--text-faint); }
        .pb-root .foot { font-size: 11px; color: var(--text-faint); margin-top: 10px; line-height: 1.5; }
        .pb-root .sub-h { font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--text-muted); margin: 12px 0 6px; }
        .pb-root .chips { display: flex; flex-wrap: wrap; gap: 6px; }
        .pb-root .chip { font-size: 11.5px; padding: 4px 8px; border-radius: 8px; background: var(--canvas-soft); }
        .pb-root .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .pb-root .ctx { border: 1px solid var(--panel-border); border-radius: 12px; padding: 8px 10px; }
        .pb-root .ctx summary { cursor: pointer; font-size: 12.5px; font-weight: 600; }
        .pb-root .ctx[open] summary { margin-bottom: 8px; }
        .pb-root .kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; padding: 6px 0;
          border-bottom: 1px solid var(--canvas-soft); }
        .pb-root .kv span { color: var(--text-muted); }
        @media (max-width: 900px) { .pb-root .grid2 { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
