"use client";

/**
 * Per-contract strategy leaderboards for the commodity desk.
 *
 * THE BLENDED BOARD ANSWERS A DIFFERENT QUESTION. Every strategy trades all eight MCX
 * futures, and the main leaderboard pools them — so "Opening Range Breakout · 30m ·
 * READY" describes a book dominated by copper, gold, silver and zinc. On crude oil that
 * same strategy is four trades and negative. Anyone reading the main board as a shortlist
 * for one contract is reading it wrong, and there was no view that let them read it right.
 *
 * So: pick a contract, and both the statistics and the promotion gate are recomputed from
 * that contract's trades alone.
 */

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import {
  fetchCommodityScripts, fetchCommodityScriptBoard,
  CommodityScriptOverview, CommodityScriptBoard,
} from "../lib/api";
import { Th, Select, SearchBox, FilterBar, cmp, SortState } from "./TableControls";

type SortKey = "name" | "family" | "tf" | "trades" | "win" | "pf" | "expectancy"
  | "dd" | "tstat" | "costs" | "net" | "verdict";

const VERDICT_OPTS: [string, string][] = [
  ["any", "any"], ["READY", "READY"], ["REJECTED", "REJECTED"], ["PENDING", "PENDING"],
];
const FAMILY_OPTS: [string, string][] = [
  ["any", "any"], ["chart", "Chart"], ["candlestick", "Candlestick"], ["structure", "Price structure"],
];

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—"
    : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${inr(v)}`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(dp);

export default function CommodityScripts() {
  const [ov, setOv] = useState<CommodityScriptOverview | null>(null);
  const [symbol, setSymbol] = useState<string>("");
  const [board, setBoard] = useState<CommodityScriptBoard | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [verdict, setVerdict] = useState("any");
  const [family, setFamily] = useState("any");
  const [tf, setTf] = useState("any");
  const [sort, setSort] = useState<SortState<SortKey>>({ key: "net", dir: -1 });

  useEffect(() => {
    fetchCommodityScripts()
      .then((d) => { setOv(d); if (!symbol && d.rows.length) setSymbol(d.rows[0].symbol); })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async (sym: string) => {
    if (!sym) return;
    setBusy(true);
    try { setBoard(await fetchCommodityScriptBoard(sym)); setErr(null); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { load(symbol); }, [symbol, load]);

  const activeFilters = [q.trim(), verdict, family, tf]
    .filter((v, i) => (i === 0 ? !!v : v !== "any")).length;
  const clearFilters = () => { setQ(""); setVerdict("any"); setFamily("any"); setTf("any"); };

  const timeframes = board?.timeframes ?? [];
  const rows = (board?.rows ?? [])
    .filter((r) => {
      const needle = q.trim().toLowerCase();
      if (needle && !r.name.toLowerCase().includes(needle)) return false;
      if (verdict !== "any" && r.verdict !== verdict) return false;
      if (family !== "any" && r.family !== family) return false;
      if (tf !== "any" && r.timeframe !== tf) return false;
      return true;
    })
    .sort((a, b) => {
      const { key, dir } = sort;
      // Verdict sorts by MEANING, not alphabetically — READY above PENDING above REJECTED.
      if (key === "verdict") {
        const rank: Record<string, number> = { READY: 3, PENDING: 2, REJECTED: 1 };
        const d = cmp(rank[a.verdict] ?? 0, rank[b.verdict] ?? 0, dir);
        return d !== 0 ? d : cmp(b.net_pnl, a.net_pnl, 1);
      }
      const pick = (r: typeof a) =>
        key === "name" ? r.name : key === "family" ? r.family_label
        : key === "tf" ? r.timeframe : key === "trades" ? r.trades
        : key === "win" ? r.win_rate : key === "pf" ? r.profit_factor
        : key === "expectancy" ? r.expectancy : key === "dd" ? r.max_drawdown_pct
        : key === "tstat" ? r.t_stat : key === "costs" ? r.total_costs : r.net_pnl;
      return cmp(pick(a), pick(b), dir);
    });

  return (
    <div className="cs">
      {err && <div className="err">{err}</div>}

      <GlassPanel title="Every contract, side by side"
        note={ov ? `${ov.rows.length} underlyings` : undefined}>
        <p className="lede">
          Each of the 353 strategies trades <b>all eight</b> MCX futures, and the main
          leaderboard pools them. Here the statistics and the promotion gate are recomputed
          on <b>one contract&rsquo;s trades alone</b>, so a verdict means &ldquo;clears the
          gate on this contract&rdquo; — which is the only reading that supports funding one.
        </p>
        {!ov ? (
          <div className="sk">{Array.from({ length: 5 }).map((_, i) =>
            <Skeleton key={i} height={26} />)}</div>
        ) : (
          <div className="tw">
            <table>
              <thead><tr>
                <th className="l">Contract</th><th>Strategies</th><th>Trades</th>
                <th>Ready</th><th>Rejected</th><th>Pending</th>
                <th>Profitable</th><th>Open</th><th>Net P&amp;L</th>
              </tr></thead>
              <tbody>
                {ov.rows.map((r) => (
                  <tr key={r.symbol} className={r.symbol === symbol ? "on" : ""}
                    onClick={() => setSymbol(r.symbol)}>
                    <td className="l sym">{r.symbol}</td>
                    <td>{r.strategies_traded}</td>
                    <td>{r.closed_trades.toLocaleString("en-IN")}</td>
                    <td className={r.ready ? "gain" : "dim"}><b>{r.ready}</b></td>
                    <td className="dim">{r.rejected}</td>
                    <td className="dim">{r.pending}</td>
                    <td className="dim">{r.profitable}</td>
                    <td className="dim">{r.open_positions}</td>
                    <td className={r.net_pnl >= 0 ? "gain" : "loss"}><b>{signed(r.net_pnl)}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel
        title={symbol ? `${symbol} — strategy leaderboard` : "Pick a contract"}
        note={board ? (activeFilters ? `${rows.length} of ${board.rows.length}` : `${rows.length} strategies`) : undefined}
        onRefresh={() => load(symbol)} refreshing={busy}>
        <div className="picker">
          {(ov?.rows ?? []).map((r) => (
            <button key={r.symbol} className={r.symbol === symbol ? "on" : ""}
              onClick={() => setSymbol(r.symbol)}>
              {r.symbol}
              <i className={r.ready ? "ok" : ""}>{r.ready} ready</i>
            </button>
          ))}
        </div>

        {board?.totals && (
          <div className="mini">
            <span><b>{board.totals.closed_trades.toLocaleString("en-IN")}</b> closed trades</span>
            <span><b className={board.totals.ready ? "gain" : ""}>{board.totals.ready}</b> clear the gate</span>
            <span><b>{board.totals.profitable}</b> of {board.totals.strategies_traded} profitable</span>
            <span>charges <b>{inr(board.totals.total_costs)}</b></span>
            <span className={board.totals.net_pnl >= 0 ? "gain" : "loss"}>
              net <b>{signed(board.totals.net_pnl)}</b></span>
          </div>
        )}

        <FilterBar active={activeFilters} onClear={clearFilters}>
          <SearchBox value={q} onChange={setQ} placeholder="Find a strategy…" />
          <Select label="Verdict" value={verdict} onChange={setVerdict} options={VERDICT_OPTS} />
          <Select label="Family" value={family} onChange={setFamily} options={FAMILY_OPTS} />
          <Select label="Timeframe" value={tf} onChange={setTf}
            options={[["any", "any"], ...timeframes.map((t) => [t, t] as [string, string])]} />
        </FilterBar>

        {busy && !board ? (
          <div className="sk">{Array.from({ length: 8 }).map((_, i) =>
            <Skeleton key={i} height={26} />)}</div>
        ) : !rows.length ? (
          <EmptyState title="Nothing matches"
            note={board?.error ?? "No strategy has traded this contract under those filters."} />
        ) : (
          <div className="tw">
            <table>
              <thead><tr>
                <Th k="name" sort={sort} setSort={setSort} align="l">Strategy</Th>
                <Th k="family" sort={sort} setSort={setSort} align="l">Family</Th>
                <Th k="tf" sort={sort} setSort={setSort}>TF</Th>
                <Th k="trades" sort={sort} setSort={setSort} numeric>Trades</Th>
                <Th k="win" sort={sort} setSort={setSort} numeric>Win %</Th>
                <Th k="pf" sort={sort} setSort={setSort} numeric>PF</Th>
                <Th k="expectancy" sort={sort} setSort={setSort} numeric>Expectancy</Th>
                <Th k="dd" sort={sort} setSort={setSort} numeric>Max DD</Th>
                <Th k="tstat" sort={sort} setSort={setSort} numeric>t-stat</Th>
                <Th k="costs" sort={sort} setSort={setSort} numeric>Costs</Th>
                <Th k="net" sort={sort} setSort={setSort} numeric>Net P&amp;L</Th>
                <Th k="verdict" sort={sort} setSort={setSort} align="l" numeric>Verdict</Th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.strategy_id}>
                    <td className="l nm">{r.name}
                      {r.open_positions > 0 && <span className="op">{r.open_positions} open</span>}</td>
                    <td className="l dim">{r.family_label}</td>
                    <td className="dim">{r.timeframe}</td>
                    <td>{r.trades}</td>
                    <td>{(r.win_rate * 100).toFixed(0)}%</td>
                    <td>{r.profit_factor === null ? "—" : num(r.profit_factor)}</td>
                    <td className={r.expectancy >= 0 ? "gain" : "loss"}>{signed(r.expectancy)}</td>
                    <td className="dim">{num(r.max_drawdown_pct, 1)}%</td>
                    <td className="dim">{r.t_stat === null ? "—" : num(r.t_stat)}</td>
                    <td className="dim">{inr(r.total_costs)}</td>
                    <td className={r.net_pnl >= 0 ? "gain" : "loss"}><b>{signed(r.net_pnl)}</b></td>
                    <td className="l">
                      <span className={`vd ${r.verdict.toLowerCase()}`}
                        title={r.verdict_reasons?.join("  ")}>{r.verdict}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {board?.note && <div className="foot">{board.note}</div>}
      </GlassPanel>

      <style jsx>{`
        .cs { display: flex; flex-direction: column; gap: 16px; }
        .err { border: 1px solid var(--loss); background: rgba(220,38,38,.07); color: var(--loss);
               border-radius: 10px; padding: 10px 14px; font-size: 12.5px; }
        .lede { font-size: 12.5px; line-height: 1.65; color: var(--text-secondary); margin: 0 0 12px; max-width: 96ch; }
        .lede b { color: var(--text-primary); }
        .sk { display: flex; flex-direction: column; gap: 8px; }
        .picker { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
        .picker button {
          display: inline-flex; align-items: baseline; gap: 6px;
          padding: 6px 13px; border-radius: 999px; font-size: 12px; cursor: pointer;
          border: 1px solid var(--border); background: var(--canvas-soft); color: var(--text-secondary);
        }
        .picker button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
        .picker i { font-style: normal; font-size: 10px; opacity: .75; }
        .picker button.on i { opacity: .9; }
        .picker i.ok { color: var(--gain); font-weight: 700; }
        .picker button.on i.ok { color: #fff; }
        .mini { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12px;
                color: var(--text-muted); margin-bottom: 12px; }
        .mini b { color: var(--text-primary); }
        .tw { overflow-x: auto; }
        .tw table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        .tw :global(th) {
          text-align: right; padding: 8px 10px; font-weight: 600; font-size: 11px;
          text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted);
          border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        .tw :global(th.l) { text-align: left; }
        .tw td { text-align: right; padding: 8px 10px; white-space: nowrap;
                 border-bottom: 1px solid var(--border-soft, var(--border)); color: var(--text-secondary); }
        .tw td.l { text-align: left; }
        .tw td.dim { color: var(--text-faint); }
        .tw td.nm { color: var(--text-primary); font-weight: 600; white-space: normal; }
        .tw td.sym { font-weight: 700; color: var(--text-primary); }
        .tw tbody tr { cursor: default; }
        .tw tbody tr.on td { background: var(--canvas-soft); }
        .tw tbody tr:hover td { background: var(--canvas-soft); }
        .op { margin-left: 7px; font-size: 10px; font-weight: 600; color: var(--accent); }
        .vd { display: inline-block; padding: 2px 9px; border-radius: 999px;
              font-size: 10.5px; font-weight: 700; letter-spacing: .03em; }
        .vd.ready { background: rgba(22,163,74,.15); color: var(--gain); }
        .vd.rejected { background: rgba(220,38,38,.12); color: var(--loss); }
        .vd.pending { background: var(--canvas-soft); color: var(--text-faint); border: 1px solid var(--border); }
        .foot { margin-top: 10px; font-size: 11px; line-height: 1.55; color: var(--text-faint); max-width: 96ch; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
