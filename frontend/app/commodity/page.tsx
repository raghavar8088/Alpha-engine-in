"use client";

/**
 * Commodity Trading — after the 2026-10-03 audit and the C0-C6 upgrade.
 *
 * The desk no longer promotes anything. Its ~350 pattern strategies are a RESEARCH RECORD,
 * labelled trade by trade (live-quote fill or stale signal-bar fill, MCX open or shut, own
 * contract or the next month's), and the honest subset is what the headline numbers use.
 * The only door to real money is the Commodity Lab (deflated, out-of-sample, must beat
 * always-long) and the pre-registered hypotheses; the real-money executor is locked.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import {
  refreshing,
  CmdHypothesis,
  CmdLabRun,
  CmdLabVerdict,
  CmdMarket,
  CmdRealMoney,
  CmdRecordRow,
  CmdRecords,
  CmdTrendBook,
  CommodityCoverage,
  CommodityPosition,
  CommoditySummary,
  CommodityTrade,
  fetchCommodityBars,
  fetchCommodityHypotheses,
  fetchCommodityLab,
  fetchCommodityMarket,
  fetchCommodityPositions,
  fetchCommodityRealMoney,
  fetchCommodityRecords,
  fetchCommoditySummary,
  fetchCommodityTrades,
  fetchCommodityTrendBook,
  runCommodityLab,
  setCommodityKillSwitch,
} from "../../lib/api";

type Tab = "record" | "market" | "lab" | "money";
const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const bp = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(1)} bp`);
const num = (v: number | null | undefined, dp = 2) => (v === null || v === undefined ? "-" : v.toFixed(dp));
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${(v * 100).toFixed(0)}%`);
const tone = (v: number | null | undefined) => (v === null || v === undefined ? "" : v >= 0 ? "gain" : "loss");

const STATUS_TONE: Record<string, "gain" | "loss" | "muted" | "accent"> = {
  CONFIRMED: "gain", INCUBATING: "accent", RECORD_ONLY: "muted", WAITING_FOR_DATA: "muted",
  READY_TO_EVALUATE: "accent", REJECTED_ON_HISTORY: "loss", REJECTED_FORWARD: "loss", REJECTED_IN_INCUBATION: "loss",
};

export default function CommodityPage() {
  const [tab, setTab] = useState<Tab>("record");
  const [summary, setSummary] = useState<CommoditySummary | null>(null);
  const [records, setRecords] = useState<CmdRecords | null>(null);
  const [positions, setPositions] = useState<CommodityPosition[]>([]);
  const [trades, setTrades] = useState<CommodityTrade[]>([]);
  const [market, setMarket] = useState<CmdMarket | null>(null);
  const [coverage, setCoverage] = useState<CommodityCoverage | null>(null);
  const [lab, setLab] = useState<{ run: CmdLabRun | null; verdicts: CmdLabVerdict[] } | null>(null);
  const [hyps, setHyps] = useState<CmdHypothesis[]>([]);
  const [book, setBook] = useState<CmdTrendBook | null>(null);
  const [money, setMoney] = useState<CmdRealMoney | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setSummary(await fetchCommoditySummary());
      if (tab === "record") {
        const [r, p, t] = await Promise.all([fetchCommodityRecords(), fetchCommodityPositions(), fetchCommodityTrades(60)]);
        setRecords(r); setPositions(p.open ?? []); setTrades(t);
      } else if (tab === "market") {
        const [m, b] = await Promise.all([fetchCommodityMarket(), fetchCommodityBars()]);
        setMarket(m); setCoverage(b.coverage);
      } else if (tab === "lab") {
        const [l, h, bk] = await Promise.all([fetchCommodityLab(), fetchCommodityHypotheses(), fetchCommodityTrendBook()]);
        setLab(l); setHyps(h.hypotheses ?? []); setBook(bk);
      } else {
        setMoney(await fetchCommodityRealMoney());
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the commodity desk");
    }
  }, [tab]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try { await refreshing(() => load()); } finally { setIsRefreshing(false); }
  }, [load]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(label);
    try { await fn(); await load(); } catch (e) { setError(e instanceof Error ? e.message : `${label} failed`); } finally { setBusy(null); }
  };

  const honest = records?.desk.honest ?? null;
  const all = records?.desk.all ?? null;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Commodity Trading"
        title="Commodity Trading"
        subtitle={
          <>
            A <strong>research record</strong>, not a strategy picker. {summary?.strategy_count ?? 353} pattern
            strategies on MCX futures, paper only. The 2026-10-03 audit found no pattern or trend rule with
            an edge after costs and carry, so nothing here is promoted. Real money stays locked until the
            Commodity Lab or a pre-registered hypothesis earns a CONFIRMED verdict.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper · research record" tone="accent" />
            {summary?.market_open ? <StatusPill label="MCX open" tone="gain" pulse /> : <StatusPill label="MCX closed" tone="muted" />}
            <StatusPill label="Real money locked" tone="muted" />
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="desk-tabs">
        <button className={tab === "record" ? "dt active" : "dt"} onClick={() => setTab("record")}>Research record</button>
        <button className={tab === "market" ? "dt active" : "dt"} onClick={() => setTab("market")}>Market &amp; contracts</button>
        <button className={tab === "lab" ? "dt active" : "dt"} onClick={() => setTab("lab")}>Lab &amp; hypotheses</button>
        <button className={tab === "money" ? "dt active" : "dt"} onClick={() => setTab("money")}>Real money</button>
      </div>

      {tab === "record" && (
        <>
          <div className="tiles">
            <Tile label="Honest trades · net" value={bp(honest?.net_bp)} tone={tone(honest?.net_bp)}
              sub={honest ? `${honest.trades.toLocaleString("en-IN")} trades · t ${num(honest.net_t)} · ${signed(honest.net_pnl)}` : "—"} />
            <Tile label="Honest · before costs" value={bp(honest?.raw_bp)} tone={tone(honest?.raw_bp)}
              sub={honest ? `price move caught · t ${num(honest.raw_t)} · direction right ${pct(honest.direction_hit)}` : "—"} />
            <Tile label="Whole record · net" value={bp(all?.net_bp)} tone={tone(all?.net_bp)}
              sub={all ? `${all.trades.toLocaleString("en-IN")} trades incl. stale fills · ${signed(all.net_pnl)}` : "—"} />
            <Tile label="Real-money estimate" value={bp(honest?.real_bp)} tone={tone(honest?.real_bp)}
              sub={honest?.real_trades ? `${honest.real_trades} trades at the touch, 1 lot, Angel card` : "recorded from 2026-10-05"} />
            <Tile label="Desk equity (paper)" value={inr(summary?.equity)} sub={`${summary?.strategy_count ?? 0} × ₹10L notional · open ${summary?.open_positions ?? 0}`} />
          </div>

          <div className="explain">
            <b>How to read this.</b> An <i>honest</i> trade was filled at a live market quote, with MCX open at entry and
            exit, on its own contract. 91% of the old record was filled at the signal bar&rsquo;s own price — a price the
            market had usually left — and those fills flattered the result. They stay in the whole record, labelled,
            but the headline uses honest trades only. No row below is a recommendation.
          </div>

          {records && (
            <GlassPanel title="The luck line" note={`${records.luck.strategies_judged} strategies with ≥ ${records.luck.min_trades} honest trades`}>
              <div className="luck">
                <div><span className="big gain">{records.luck.t_above_2}</span><span>with t &gt; 2</span></div>
                <div><span className="big">{records.luck.expected_by_chance_each_tail}</span><span>expected by chance alone</span></div>
                <div><span className="big loss">{records.luck.t_below_minus_2}</span><span>with t &lt; −2</span></div>
                <div><span className="big">{records.luck.positive}</span><span>net positive at all</span></div>
                <p>{records.luck.note}</p>
              </div>
            </GlassPanel>
          )}

          {records && (
            <GlassPanel title="By timeframe" note={`retired: ${records.retired_timeframes.join(", ")} — no new entries since 2026-10-05`}>
              <RecordTable rows={records.by_timeframe} label="Timeframe" extra={records.by_timeframe_all} retired={records.retired_timeframes} />
            </GlassPanel>
          )}

          {records && (
            <GlassPanel title="By contract" note="honest trades only">
              <RecordTable rows={records.by_contract} label="Contract" />
            </GlassPanel>
          )}

          {records && <DataQuality records={records} />}

          {records && <StrategyRecords rows={records.strategies} />}

          <GlassPanel title={`Open positions (${positions.length})`} note="each marked on its OWN contract; rolled before its delivery window">
            {!positions.length ? (
              <EmptyState title="No open positions" note="Entries need a live quote — a trade must have printed this session." />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th className="l">Contract</th><th className="l">Pattern</th><th>TF</th><th>Side</th><th>Entry</th><th>LTP</th><th>Target</th><th>Stop</th><th>Bars</th><th>Unrealised</th></tr></thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.position_id}>
                        <td className="l sym">{p.symbol}<span className="dim"> {p.display_name?.split("-")[1] ?? ""}</span></td>
                        <td className="l dim">{p.pattern}</td>
                        <td>{p.timeframe}</td>
                        <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                        <td>{num(p.entry_price)}</td>
                        <td>{num(p.ltp)}</td>
                        <td>{num(p.target)}</td>
                        <td>{num(p.stoploss)}</td>
                        <td className="dim">{p.bars_held}/{p.max_hold_bars}</td>
                        <td className={tone(p.unrealized_pnl)}>{signed(p.unrealized_pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          <GlassPanel title="Latest closed trades" note="gross, charges, net">
            {!trades.length ? <EmptyState title="No closed trades yet" note="" /> : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th className="l">Contract</th><th className="l">Pattern</th><th>TF</th><th>Side</th><th>Entry</th><th>Exit</th><th>Gross</th><th>Costs</th><th>Net</th><th>Why</th><th>Closed</th></tr></thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.trade_id}>
                        <td className="l sym">{t.symbol}</td>
                        <td className="l dim">{t.pattern}</td>
                        <td>{t.timeframe}</td>
                        <td className={t.side === "BUY" ? "gain" : "loss"}>{t.side}</td>
                        <td>{num(t.entry_price)}</td>
                        <td>{num(t.exit_price)}</td>
                        <td className={tone(t.gross_pnl)}>{signed(t.gross_pnl)}</td>
                        <td className="loss">−{inr(t.costs)}</td>
                        <td className={tone(t.realized_pnl)}>{signed(t.realized_pnl)}</td>
                        <td><span className="cat">{t.exit_reason}</span></td>
                        <td className="dim">{new Date(t.closed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>
        </>
      )}

      {tab === "market" && market && <MarketTab market={market} coverage={coverage} />}

      {tab === "lab" && (
        <LabTab lab={lab} hyps={hyps} book={book} busy={busy}
          onRun={() => act("lab", runCommodityLab)} />
      )}

      {tab === "money" && money && (
        <MoneyTab money={money} busy={busy} onKill={(on) => act("kill", () => setCommodityKillSwitch(on))} />
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .desk-tabs { display: flex; flex-wrap: wrap; gap: 8px; }
        .dt { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .dt.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .explain { font-size: 12.5px; line-height: 1.5; color: var(--text-muted); background: var(--canvas-soft);
                   border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 16px; }
        .luck { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; padding: 14px 20px; align-items: end; }
        .luck div { display: flex; flex-direction: column; gap: 2px; font-size: 11.5px; color: var(--text-muted); }
        .luck .big { font-family: var(--font-data); font-size: 26px; font-weight: 700; color: var(--text); }
        .luck .big.gain { color: var(--gain); } .luck .big.loss { color: var(--loss); }
        .luck p { grid-column: 1 / -1; margin: 4px 0 0; font-size: 12px; color: var(--text-muted); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .sym { font-weight: 700; } .dim { color: var(--text-muted); } .gain { color: var(--gain); } .loss { color: var(--loss); }
        .cat { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 6px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; padding: 14px 16px; box-shadow: var(--shadow-sm); }
        .t-label { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: var(--text-muted); }
        .t-value { margin-top: 7px; font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 21px; font-weight: 600; }
        .t-value.gain { color: var(--gain); } .t-value.loss { color: var(--loss); }
        .t-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}

function RecordTable({ rows, label, extra, retired }: { rows: CmdRecordRow[]; label: string; extra?: CmdRecordRow[]; retired?: string[] }) {
  const allBy = new Map((extra ?? []).map((r) => [String(r.key), r]));
  if (!rows.length) return <EmptyState title="No honest trades yet" note="They accrue from live-quote fills while MCX is open." />;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th className="l">{label}</th><th>Honest trades</th><th>Net / trade</th><th>95% range</th><th>t</th>
            <th>Before costs</th><th>Direction right</th><th>Real (touch)</th><th>Net ₹</th>
            {extra && <><th>All trades</th><th>All · net</th></>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = String(r.key);
            const a = allBy.get(k);
            return (
              <tr key={k}>
                <td className="l sym">{k}{retired?.includes(k) && <span className="ret">retired</span>}</td>
                <td>{r.trades.toLocaleString("en-IN")}</td>
                <td className={tone(r.net_bp)}>{bp(r.net_bp)}</td>
                <td className="dim">{r.net_ci95 ? `${r.net_ci95[0].toFixed(0)} … ${r.net_ci95[1].toFixed(0)}` : "-"}</td>
                <td>{num(r.net_t)}</td>
                <td className={tone(r.raw_bp)}>{bp(r.raw_bp)}</td>
                <td>{pct(r.direction_hit)}</td>
                <td className={tone(r.real_bp)}>{r.real_trades ? bp(r.real_bp) : "-"}</td>
                <td className={tone(r.net_pnl)}>{signed(r.net_pnl)}</td>
                {extra && <><td className="dim">{a ? a.trades.toLocaleString("en-IN") : "-"}</td><td className={`${tone(a?.net_bp)}`}>{bp(a?.net_bp)}</td></>}
              </tr>
            );
          })}
        </tbody>
      </table>
      <style jsx>{`
        .ret { margin-left: 8px; font-size: 9.5px; font-weight: 700; padding: 1px 6px; border-radius: 5px; background: var(--loss-dim); color: var(--loss); text-transform: uppercase; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .sym { font-weight: 700; } .dim { color: var(--text-muted); } .gain { color: var(--gain); } .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

function DataQuality({ records }: { records: CmdRecords }) {
  const l = records.labels as Record<string, number>;
  const items: [string, number | undefined, string][] = [
    ["Positions labelled", l.positions, "every paper position the desk ever opened"],
    ["Stale signal-bar fills", l.stale_signal_bar, "filled at the signal bar's own price ± slippage (before 2026-09-25)"],
    ["Void", l.void, "entered or exited while MCX was shut (2 Oct, 14 Sep morning, after 23:30) — kept, never counted"],
    ["Wrong-contract closes", l.wrong_contract, "closed on the next month's price after expiry; repriced on their own contract"],
    ["Repriced", l.repriced, "of those, repriced from the store's last bar of their own contract"],
    ["Honest", l.honest, "live-quote fill, MCX open both ends, own contract"],
  ];
  return (
    <GlassPanel title="Data quality" note="labels on every position; nothing deleted">
      <div className="dq">
        {items.map(([k, v, why]) => (
          <div key={k} className="dqi"><b>{v === undefined ? "-" : Number(v).toLocaleString("en-IN")}</b><span>{k}</span><i>{why}</i></div>
        ))}
      </div>
      <style jsx>{`
        .dq { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; padding: 14px 20px; }
        .dqi { display: flex; flex-direction: column; gap: 3px; border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; background: var(--canvas-soft); }
        .dqi b { font-family: var(--font-data); font-size: 18px; } .dqi span { font-size: 11.5px; font-weight: 700; }
        .dqi i { font-style: normal; font-size: 11px; color: var(--text-muted); line-height: 1.35; }
      `}</style>
    </GlassPanel>
  );
}

function StrategyRecords({ rows }: { rows: CmdRecords["strategies"] }) {
  const [tf, setTf] = useState("ALL");
  const [sort, setSort] = useState<"trades" | "net" | "t">("trades");
  const tfs = useMemo(() => Array.from(new Set(rows.map((r) => r.timeframe))), [rows]);
  const shown = useMemo(() => {
    const xs = rows.filter((r) => tf === "ALL" || r.timeframe === tf);
    return [...xs].sort((a, b) => sort === "trades" ? b.trades - a.trades : sort === "net" ? b.net_bp - a.net_bp : (b.net_t ?? -99) - (a.net_t ?? -99));
  }, [rows, tf, sort]);
  return (
    <GlassPanel title="Strategy records" note={`${rows.length} strategies with honest trades · a record, not a ranking`}>
      <div className="filters">
        <span className="flabel">Timeframe</span>
        {["ALL", ...tfs].map((t) => <button key={t} className={`chip ${tf === t ? "on" : ""}`} onClick={() => setTf(t)}>{t}</button>)}
        <span className="flabel" style={{ marginLeft: 12 }}>Sort</span>
        {(["trades", "net", "t"] as const).map((s) => <button key={s} className={`chip ${sort === s ? "on" : ""}`} onClick={() => setSort(s)}>{s}</button>)}
      </div>
      <div className="table-scroll">
        <table className="data-table">
          <thead><tr><th className="l">Strategy</th><th>TF</th><th>Trades</th><th>Net / trade</th><th>95% range</th><th>t</th><th>Before costs</th><th>Direction</th><th>Net ₹</th></tr></thead>
          <tbody>
            {shown.slice(0, 150).map((r) => (
              <Fragment key={r.strategy_id}>
                <tr className={r.retired ? "retired" : ""}>
                  <td className="l">{r.name}{r.retired && <span className="ret">retired</span>}</td>
                  <td>{r.timeframe}</td>
                  <td>{r.trades}</td>
                  <td className={tone(r.net_bp)}>{bp(r.net_bp)}</td>
                  <td className="dim">{r.net_ci95 ? `${r.net_ci95[0].toFixed(0)} … ${r.net_ci95[1].toFixed(0)}` : "-"}</td>
                  <td>{num(r.net_t)}</td>
                  <td className={tone(r.raw_bp)}>{bp(r.raw_bp)}</td>
                  <td>{pct(r.direction_hit)}</td>
                  <td className={tone(r.net_pnl)}>{signed(r.net_pnl)}</td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <style jsx>{`
        .filters { padding: 12px 20px 4px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .flabel { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: var(--text-muted); }
        .chip { font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 100px; cursor: pointer; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .chip.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
        .retired td { opacity: .6; }
        .ret { margin-left: 8px; font-size: 9.5px; font-weight: 700; padding: 1px 6px; border-radius: 5px; background: var(--loss-dim); color: var(--loss); text-transform: uppercase; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .dim { color: var(--text-muted); } .gain { color: var(--gain); } .loss { color: var(--loss); }
      `}</style>
    </GlassPanel>
  );
}

function MarketTab({ market, coverage }: { market: CmdMarket; coverage: CommodityCoverage | null }) {
  const c = market.calendar;
  return (
    <>
      <GlassPanel title="MCX session" note={c.today_holiday ? `today: ${c.today_holiday.name}` : "today: normal trading day"}>
        <div className="kv">
          <div><span>Now</span><b>{c.session ? `${c.session} session` : "closed"}</b></div>
          <div><span>Close today</span><b>{c.close_today} IST</b><i>{c.us_daylight_saving ? "US on daylight saving" : "US standard time"}</i></div>
          <div><span>Stale quote after</span><b>{market.stale_after_min} min</b><i>without a trade — no fill on a frozen price</i></div>
          <div><span>Holiday list</span><b>to {c.list_covers_through}</b><i>{c.list_expired ? "EXPIRED — extend it" : "MCX circular, 3 broker copies"}</i></div>
        </div>
        <div className="hol">
          {c.upcoming_holidays.map((h) => (
            <span key={h.date} className="h">{h.date} · {h.name} · {h.morning_closed && h.evening_closed ? "both sessions shut" : h.morning_closed ? "morning shut, evening open" : "evening shut"}</span>
          ))}
        </div>
      </GlassPanel>

      <GlassPanel title="Which contract is traded" note="the nearest expiry OUTSIDE its exit window; held positions roll out before it">
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th className="l">Underlying</th><th className="l">Settlement</th><th>Exit window</th><th className="l">Trading now</th><th className="l">Listed contracts (trading days left)</th></tr></thead>
            <tbody>
              {market.contracts.map((r) => (
                <tr key={r.underlying}>
                  <td className="l sym">{r.underlying}</td>
                  <td className="l dim">{r.settlement}</td>
                  <td>last {r.exit_days} days</td>
                  <td className="l">{r.trading ?? "—"}</td>
                  <td className="l dim">{r.contracts.map((x) => `${x.expiry} (${x.trading_days_left}${x.in_exit_window ? ", in window" : ""})`).join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Quoted spreads, last 30 days" note="sampled from live two-sided quotes — what the 5 bp a side the desk assumes is checked against">
        {!market.spreads_30d.length ? <EmptyState title="No samples yet" note="Collected from every live quote the desks take, from 2026-10-05." /> : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">Underlying</th><th>Samples</th><th>Median spread</th><th>90th pct</th><th>Half-spread (cost a side)</th></tr></thead>
              <tbody>{market.spreads_30d.map((s) => (
                <tr key={s.underlying}><td className="l sym">{s.underlying}</td><td>{s.samples}</td><td>{s.median_bp} bp</td><td>{s.p90_bp} bp</td><td>{s.half_spread_bp} bp</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Futures-curve recorder" note="every listed expiry, 3× a trading day — the data a carry test (HC4) needs">
        <div className="kv">
          <div><span>Snapshots</span><b>{market.curve_recorder.documents}</b></div>
          <div><span>Trading days recorded</span><b>{market.curve_recorder.trading_days_recorded}</b><i>HC4 needs 126</i></div>
          <div><span>First day</span><b>{market.curve_recorder.first_date ?? "—"}</b></div>
          <div><span>Next snapshot</span><b>{market.curve_recorder.next_slot}</b><i>{new Date(market.curve_recorder.next_at).toLocaleString("en-IN")}</i></div>
        </div>
        {market.curve_recorder.error && <div className="err">Last error: {market.curve_recorder.error}</div>}
      </GlassPanel>

      {coverage && (
        <GlassPanel title="Bar store" note="per contract since 2026-10-05; signals read one back-adjusted series, closed bars only">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">Symbol</th>{coverage.native_timeframes.map((t) => <th key={t}>{t}</th>)}<th>Latest bar (IST)</th></tr></thead>
              <tbody>{coverage.symbols.map((s) => (
                <tr key={s}><td className="l sym">{s}</td>{coverage.native_timeframes.map((t) => <td key={t}>{coverage.bars[s]?.[t] ?? 0}</td>)}
                  <td className="dim">{coverage.latest_bar_ist[s] ? new Date(coverage.latest_bar_ist[s] as string).toLocaleString("en-IN") : "-"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </GlassPanel>
      )}
      <style jsx>{`
        .kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; padding: 14px 20px; }
        .kv div { display: flex; flex-direction: column; gap: 2px; }
        .kv span { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); }
        .kv b { font-size: 15px; } .kv i { font-style: normal; font-size: 11px; color: var(--text-muted); }
        .hol { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 20px 14px; }
        .h { font-size: 11px; padding: 3px 9px; border-radius: 7px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .err { padding: 0 20px 14px; font-size: 12px; color: var(--loss); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .sym { font-weight: 700; } .dim { color: var(--text-muted); }
      `}</style>
    </>
  );
}

function LabTab({ lab, hyps, book, busy, onRun }: {
  lab: { run: CmdLabRun | null; verdicts: CmdLabVerdict[] } | null; hyps: CmdHypothesis[]; book: CmdTrendBook | null;
  busy: string | null; onRun: () => void;
}) {
  const run = lab?.run ?? null;
  const lastEq = book?.equity?.length ? book.equity[book.equity.length - 1] : null;
  const targets = book?.state?.last_targets;
  return (
    <>
      <GlassPanel title="Pre-registered hypotheses" note="rules, priors and decision rules written before any forward data">
        <div className="hyps">
          {hyps.map((h) => (
            <div key={h.id} className="hyp">
              <div className="hh"><b>{h.id}</b><span>{h.name}</span><StatusPill label={h.status.replaceAll("_", " ")} tone={STATUS_TONE[h.status] ?? "muted"} /></div>
              <p>{h.rule}</p>
              {h.verdict_reason && <p className="why">{h.verdict_reason}</p>}
              {h.expectation && <p className="why">{h.expectation}</p>}
              {h.test && <p className="dim">Test: {h.test}</p>}
              {h.forward && <p className="dim">Forward: {Object.entries(h.forward).map(([k, v]) => `${k.replaceAll("_", " ")} ${v === null ? "—" : String(v)}`).join(" · ")}</p>}
            </div>
          ))}
        </div>
      </GlassPanel>

      <GlassPanel title="HC1 paper book" note={book ? `${inr(book.capital)} · whole lots of ${Object.values(book.vehicles).join(", ")} · first entry ${book.start_date}` : ""}>
        {!book ? <EmptyState title="Loading" note="" /> : (
          <>
            <div className="kv">
              <div><span>Equity</span><b>{inr(lastEq?.equity ?? book.capital)}</b><i>{lastEq ? `as of ${lastEq.date}` : "not started — first rebalance 2026-10-05 from 11:00"}</i></div>
              <div><span>Realised − fees</span><b className={tone((lastEq?.realized ?? 0) - (lastEq?.fees ?? 0))}>{signed((lastEq?.realized ?? 0) - (lastEq?.fees ?? 0))}</b></div>
              <div><span>Unrealised</span><b className={tone(lastEq?.unrealized)}>{signed(lastEq?.unrealized ?? 0)}</b></div>
              <div><span>Last rebalance</span><b>{book.state?.rebalanced_month ?? "—"}</b><i>{(book.state?.last_notes ?? []).join(" · ")}</i></div>
              {targets?.stress && <div><span>Worst-day stress</span><b>{inr(targets.stress.worst_day_loss)}</b><i>{targets.stress.worst_day_pct !== null ? `${(targets.stress.worst_day_pct * 100).toFixed(1)}% of capital` : ""} · margin {inr(targets.stress.margin)}</i></div>}
            </div>
            {targets && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th className="l">Commodity</th><th>12-month return</th><th>Signal</th><th>60-day vol</th><th>Target notional</th><th className="l">Contract</th><th>Lots</th><th className="l">Note</th></tr></thead>
                  <tbody>{Object.entries(targets.legs).map(([k, t]) => (
                    <tr key={k}><td className="l sym">{k}</td><td className={tone(t.ret_12m)}>{t.ret_12m !== undefined ? `${(t.ret_12m * 100).toFixed(1)}%` : "-"}</td>
                      <td className={t.side === "BUY" ? "gain" : "loss"}>{t.side}</td><td>{t.vol_60d ? `${(t.vol_60d * 100).toFixed(0)}%` : "-"}</td>
                      <td>{inr(t.notional)}</td><td className="l">{t.contract}</td><td><b>{t.lots}</b></td><td className="l dim">{t.not_held_reason ?? ""}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            {book.legs.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th className="l">Leg</th><th>Side</th><th>Lots</th><th className="l">Contract</th><th>Avg price</th><th>Mark</th><th>Unrealised</th><th>Realised</th><th>Fees</th></tr></thead>
                  <tbody>{book.legs.map((l) => (
                    <tr key={l.commodity}><td className="l sym">{l.commodity}</td><td className={l.side === "BUY" ? "gain" : "loss"}>{l.side ?? "flat"}</td><td>{l.lots}</td>
                      <td className="l">{l.contract}</td><td>{num(l.avg_price)}</td><td>{num(l.mark)}</td>
                      <td className={tone(l.unrealized_pnl)}>{signed(l.unrealized_pnl ?? 0)}</td><td className={tone(l.realized_pnl)}>{signed(l.realized_pnl)}</td><td className="loss">−{inr(l.fees)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </GlassPanel>

      <GlassPanel title="Commodity Lab" note={run ? `last run ${new Date(run.at).toLocaleString("en-IN")} · ${run.n_trials_registry} trials in the registry` : "not run yet"}>
        <div className="labhead">
          <p>
            A candidate must be net positive in 2004–2015 <i>and</i> 2016–2026 after MCX costs, rolls and the cost of
            carry; reach a deflated Sharpe ≥ {run?.gate.dsr_min ?? 0.95} over every trial ever registered; come from a
            trial set whose PBO is ≤ {run?.gate.pbo_max ?? 0.5}; beat always-long (alpha t ≥ {run?.gate.alpha_t_min ?? 2});
            and be tradable in whole lots. Then {run?.gate.incubation_sessions ?? 60} sessions of paper incubation.
          </p>
          <button className="btn" disabled={!!busy} onClick={onRun}>{busy === "lab" ? "Starting…" : "Run the Lab"}</button>
        </div>
        {run && (
          <>
            <div className="kv">
              <div><span>Passed the history gate</span><b className={run.passed_history.length ? "gain" : ""}>{run.passed_history.length}</b><i>of {run.candidates.length}</i></div>
              <div><span>PBO of the trial set</span><b>{run.pbo.pbo ?? "-"}</b><i>{run.pbo.combinations} CSCV splits</i></div>
              <div><span>Always-long, held-out</span><b>Sharpe {num(run.benchmark.heldout.sharpe ?? null)}</b><i>{run.benchmark.name}</i></div>
              <div><span>Verdicts</span><b>{Object.entries(run.verdict_counts).map(([k, v]) => `${v} ${k.toLowerCase().replaceAll("_", " ")}`).join(" · ")}</b></div>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th className="l">Candidate</th><th>Explore Sharpe</th><th>Held-out Sharpe</th><th>Held-out %/yr</th><th>DSR</th><th>Alpha t vs long</th><th>Whole-lot legs</th><th className="l">Why not</th></tr></thead>
                <tbody>{run.candidates.slice(0, 40).map((c) => (
                  <tr key={c.key}><td className="l">{c.kind === "pattern" ? c.name : `${c.rule} · ${c.series}`}</td>
                    <td>{num(c.explore.sharpe ?? null)}</td><td className={tone(c.heldout.sharpe ?? null)}>{num(c.heldout.sharpe ?? null)}</td>
                    <td className={tone(c.heldout.ann_ret_pct ?? null)}>{c.heldout.ann_ret_pct ?? "-"}</td><td>{num(c.dsr, 3)}</td>
                    <td>{num(c.alpha.alpha_t ?? null)}</td><td>{c.feasible_legs}/{c.legs.length}</td>
                    <td className="l dim reasons">{c.passes_history ? "passes" : c.reasons[0]}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th className="l">Whole-lot feasibility at {inr(run.book_capital)}</th><th>60-day vol</th><th>Vol-budget notional</th><th className="l">Smallest contract</th><th>Lot value</th><th>Lots</th></tr></thead>
                <tbody>{Object.entries(run.feasibility).map(([k, f]) => (
                  <tr key={k}><td className="l sym">{k}</td><td>{f.vol_60d ? `${(f.vol_60d * 100).toFixed(0)}%` : "-"}</td><td>{inr(f.target_notional)}</td>
                    <td className="l">{f.vehicle?.contract ?? "-"}</td><td>{inr(f.vehicle?.lot_value)}</td><td className={f.feasible ? "gain" : "loss"}>{f.vehicle?.lots ?? 0}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </>
        )}
      </GlassPanel>
      <style jsx>{`
        .hyps { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; padding: 14px 20px; }
        .hyp { border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 14px; background: var(--canvas-soft); }
        .hh { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .hh b { font-family: var(--font-data); } .hh span { font-weight: 600; font-size: 13px; flex: 1; }
        .hyp p { margin: 8px 0 0; font-size: 12px; line-height: 1.45; } .hyp .why { color: var(--text); font-weight: 500; } .dim { color: var(--text-muted); }
        .kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; padding: 14px 20px; }
        .kv div { display: flex; flex-direction: column; gap: 2px; }
        .kv span { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); }
        .kv b { font-size: 15px; } .kv i { font-style: normal; font-size: 11px; color: var(--text-muted); }
        .labhead { display: flex; gap: 16px; align-items: flex-start; padding: 14px 20px 0; }
        .labhead p { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--text-muted); flex: 1; }
        .btn { padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); white-space: nowrap; }
        .btn:disabled { opacity: .55; }
        .reasons { white-space: normal; min-width: 260px; font-size: 11.5px; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .sym { font-weight: 700; } .gain { color: var(--gain); } .loss { color: var(--loss); }
      `}</style>
    </>
  );
}

function MoneyTab({ money, busy, onKill }: { money: CmdRealMoney; busy: string | null; onKill: (on: boolean) => void }) {
  const s = money.state;
  return (
    <>
      <div className="locked">
        <b>Real money is locked.</b> An MCX order can only be sent when a strategy has a CONFIRMED verdict, the server
        enables it, Angel&rsquo;s MCX order-quantity unit has been proven with a real 1-lot round trip, you arm it with
        the phrase, and dry-run is switched off. Today none of these hold; every order the HC1 book makes is recorded
        as SIMULATED.
      </div>
      <GlassPanel title="Executor state" note={s.armed ? `ARMED for ${s.armed_for}` : "disarmed"}>
        <div className="kv">
          <div><span>Armed</span><b className={s.armed ? "loss" : ""}>{s.armed ? `yes — ${s.armed_for}` : "no"}</b><i>{s.disarmed_reason ?? ""}</i></div>
          <div><span>Server switch</span><b>{s.env_enabled ? "MCX_LIVE_ENABLED=1" : "off"}</b></div>
          <div><span>Dry run</span><b>{s.dry_run ? "yes — nothing is sent" : "NO — real orders"}</b></div>
          <div><span>Quantity unit verified</span><b>{s.qty_verified ? "yes" : "no"}</b></div>
          <div><span>Limits</span><b>{inr(s.max_order_notional)} / order</b><i>daily loss cap {inr(s.daily_loss_cap)}</i></div>
          <div><span>Kill switch</span><b className={s.kill_switch ? "loss" : ""}>{s.kill_switch ? "ON" : "off"}</b>
            <button className="btn" disabled={!!busy} onClick={() => onKill(!s.kill_switch)}>{s.kill_switch ? "Release" : "Engage"}</button></div>
        </div>
      </GlassPanel>
      <GlassPanel title="Who could trade real money" note="and exactly why not">
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th className="l">Strategy</th><th className="l">Status</th><th>Can arm</th><th className="l">Why not</th></tr></thead>
            <tbody>{money.strategies.map((r) => (
              <tr key={r.strategy}><td className="l"><b>{r.strategy}</b> {r.name}</td><td className="l">{r.status}</td>
                <td className={r.can_arm ? "gain" : "loss"}>{r.can_arm ? "yes" : "no"}</td><td className="l dim reasons">{r.why_not.join(" · ")}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </GlassPanel>
      <GlassPanel title="Checks before every opening order" note="closing orders are always allowed">
        <ul className="checks">{money.checks.map((c) => <li key={c}>{c}</li>)}</ul>
      </GlassPanel>
      <GlassPanel title="Recent orders" note="simulated while locked">
        {!money.recent_orders.length ? <EmptyState title="No orders yet" note="The HC1 book's rebalances appear here as SIMULATED." /> : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">When</th><th>Strategy</th><th className="l">Contract</th><th>Side</th><th>Lots</th><th>Ref price</th><th>Status</th></tr></thead>
              <tbody>{money.recent_orders.map((o, i) => (
                <tr key={i}><td className="l dim">{new Date(o.at).toLocaleString("en-IN")}</td><td>{o.strategy}</td><td className="l">{o.tradingsymbol}</td>
                  <td className={o.side === "BUY" ? "gain" : "loss"}>{o.side}</td><td>{o.lots}</td><td>{num(o.ref_price)}</td><td>{o.status}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </GlassPanel>
      <style jsx>{`
        .locked { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.5; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; padding: 14px 20px; }
        .kv div { display: flex; flex-direction: column; gap: 3px; }
        .kv span { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); }
        .kv b { font-size: 14px; } .kv i { font-style: normal; font-size: 11px; color: var(--text-muted); }
        .btn { align-self: flex-start; margin-top: 4px; padding: 5px 12px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .checks { margin: 0; padding: 14px 20px 16px 38px; } .checks li { font-size: 12.5px; color: var(--text-muted); margin: 3px 0; }
        .reasons { white-space: normal; min-width: 260px; font-size: 11.5px; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .dim { color: var(--text-muted); } .gain { color: var(--gain); } .loss { color: var(--loss); }
      `}</style>
    </>
  );
}
