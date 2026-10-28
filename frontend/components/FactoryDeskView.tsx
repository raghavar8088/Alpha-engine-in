"use client";

// The Strategy Factory tab of one module: the Factory's 546 strategies, decided on this module's
// underlying, traded in this module's instrument. Backend: app/services/factory_desks.py.
import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import { RankNote, RankTd, RankTh, sortByRank, useStrategyRanks } from "./StrategyRank";
import {
  FactoryDeskKey,
  FactoryDeskRow,
  FactoryDeskSummary,
  FactoryPosition,
  fetchFactoryDeskLeaderboard,
  fetchFactoryDeskPositions,
  fetchFactoryDeskSummary,
} from "../lib/factoryDesks";

const REFRESH_MS = 30000;
const TFS = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"];

const when = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
const tone = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });

export default function FactoryDeskView({ desk }: { desk: FactoryDeskKey }) {
  const [summary, setSummary] = useState<FactoryDeskSummary | null>(null);
  const [rows, setRows] = useState<FactoryDeskRow[]>([]);
  const [family, setFamily] = useState<string | null>(null);
  const [tf, setTf] = useState<string | null>(null);
  const [onlyTraded, setOnlyTraded] = useState(true);
  const [posTab, setPosTab] = useState<"OPEN" | "CLOSED">("OPEN");
  const [positions, setPositions] = useState<FactoryPosition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const ranks = useStrategyRanks("factory-desks", { desk });

  const usd = summary?.currency === "USD";
  const money = useCallback(
    (v: number | null | undefined, dp = 0) =>
      v === null || v === undefined ? "—" : `${v < 0 ? "−" : ""}${usd ? "$" : "₹"}${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: dp })}`,
    [usd],
  );
  const signed = useCallback(
    (v: number | null | undefined, dp = 0) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${money(v, dp)}`),
    [money],
  );

  const load = useCallback(async () => {
    try {
      const [s, b, p] = await Promise.all([
        fetchFactoryDeskSummary(desk),
        fetchFactoryDeskLeaderboard(desk, family, tf),
        fetchFactoryDeskPositions(desk, posTab),
      ]);
      setSummary(s);
      setRows(b);
      setPositions(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the Strategy Factory tab");
    }
  }, [desk, family, tf, posTab]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const shown = useMemo(
    () => (onlyTraded ? rows.filter((r) => r.trades > 0 || r.open_positions > 0) : rows),
    [rows, onlyTraded],
  );
  const net = (summary?.realized_pnl ?? 0) + (summary?.unrealized_pnl ?? 0);
  const coverage = summary?.coverage ?? {};
  const skipped = summary?.skipped ?? {};
  const unit = usd ? `$${num(summary?.per_strategy_capital, 0)} sleeve` : `₹${num(summary?.per_strategy_capital, 0)} account`;

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="note">
        <p>
          <b>Strategy Factory · {summary?.strategies ?? 546} strategies on {summary?.module ?? "this module"}.</b> Each strategy
          has its own {unit}. It decides on closed bars of its own timeframe with the Factory’s own code (the code its
          backtests run) and trades {summary?.instrument ?? "this module's instrument"}. It keeps its own stop, target and
          hold limit, measured on the underlying; this module’s rules apply on top. This module’s own strategies are untouched.
        </p>
        {(summary?.notes ?? []).map((n) => <p key={n}>{n}</p>)}
        {summary?.entry_gate && (
          <p>
            <b>Entries held.</b> {summary.entry_gate}
          </p>
        )}
        <p>
          <b>Data.</b> Strategy × symbol pairs with enough bars, by timeframe:{" "}
          {TFS.map((t) => `${t} ${coverage[t] ?? 0}`).join(" · ")}. A timeframe at 0 has no bars here yet, so its
          strategies cannot fire; nothing is filled in with a short series.
          {summary?.stale_tfs?.length
            ? ` Last pass had no just-closed bar on ${summary.stale_tfs.join(", ")} (feed behind or not live), so those did not trade.`
            : ""}
          {Object.keys(skipped).length ? ` Signals not taken: ${Object.entries(skipped).map(([k, v]) => `${v} ${k}`).join(", ")}.` : ""}
        </p>
        <p className="dim">
          Paper only; fills at the quoted touch where the module has one. None of the 546 is validated here — most are
          graded 1 by the Factory’s own backtest. Last cycle {when(summary?.last_cycle_at)}
          {summary?.last_notes?.length ? ` · ${summary.last_notes.join(" · ")}` : ""}.
        </p>
      </div>

      <div className="tiles">
        <Tile label="Strategies" value={`${summary?.strategies ?? 546}`} sub={`${unit} each`} />
        <Tile label="Capital" value={money(summary?.desk_capital)} sub="all strategies together" />
        <Tile label="Net P&L" value={signed(net)} tone={tone(net)}
              sub={`${(summary?.roi_pct ?? 0) >= 0 ? "+" : ""}${(summary?.roi_pct ?? 0).toFixed(3)}% on the capital`} />
        <Tile label="Realised" value={signed(summary?.realized_pnl)} tone={tone(summary?.realized_pnl)}
              sub={`${summary?.closed_positions ?? 0} closed · ${summary?.closed_positions ? Math.round(((summary?.wins ?? 0) / summary.closed_positions) * 100) : 0}% won`} />
        <Tile label="Charges" value={money(summary?.fees, 2)} tone={(summary?.fees ?? 0) > 0 ? "loss" : undefined} sub="on closed trades" />
        <Tile label="Open" value={`${summary?.open_positions ?? 0}`} sub={`${signed(summary?.unrealized_pnl)} unrealised · ${money(summary?.deployed)} deployed`} />
      </div>

      <GlassPanel title={`The 546 strategies${onlyTraded ? " — the ones that have traded" : ""}`}>
        <div className="controls">
          <button className={family === null ? "chip on" : "chip"} onClick={() => setFamily(null)}>All families</button>
          {Object.entries(summary?.families ?? {}).map(([f, n]) => (
            <button key={f} className={family === f ? "chip on" : "chip"} onClick={() => setFamily(f)}>{f} · {n}</button>
          ))}
        </div>
        <div className="controls">
          <button className={tf === null ? "chip on" : "chip"} onClick={() => setTf(null)}>All timeframes</button>
          {TFS.map((t) => (
            <button key={t} className={tf === t ? "chip on" : "chip"} onClick={() => setTf(t)}>{t}</button>
          ))}
          <label className="toggle-label">
            <input type="checkbox" checked={onlyTraded} onChange={(e) => setOnlyTraded(e.target.checked)} /> only strategies that have traded
          </label>
        </div>
        {ranks && <RankNote board={ranks} />}
        {!shown.length ? (
          <div className="empty">
            {onlyTraded
              ? "No strategy has traded here yet. Each one trades when its own setup appears on a closed bar of its timeframe."
              : "No strategies match these filters."}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {ranks && <RankTh />}
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Family</th>
                  <th>TF</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>Charges</th>
                  <th>Net P&amp;L</th>
                  <th>Open</th>
                </tr>
              </thead>
              <tbody>
                {sortByRank(shown, ranks, (r) => r.strategy_id).map((r) => (
                  <tr key={r.strategy_id}>
                    {ranks && <RankTd board={ranks} id={r.strategy_id} />}
                    <td style={{ textAlign: "left" }}>
                      <span className="dim">{r.strategy_id}</span> {r.name}
                    </td>
                    <td className="dim">{r.family}</td>
                    <td><span className="badge">{r.timeframe}</span></td>
                    <td>{r.trades}</td>
                    <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                    <td>{r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}</td>
                    <td className="loss">{r.fees ? money(-r.fees, 2) : "—"}</td>
                    <td className={tone(r.net_pnl)}>{r.trades ? signed(r.net_pnl) : "—"}</td>
                    <td>{r.open_positions ? `${r.open_positions} · ${signed(r.unrealized_pnl)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Positions">
        <div className="controls">
          {(["OPEN", "CLOSED"] as const).map((t) => (
            <button key={t} className={posTab === t ? "chip on" : "chip"} onClick={() => setPosTab(t)}>
              {t === "OPEN" ? `Open (${summary?.open_positions ?? 0})` : `Closed (${summary?.closed_positions ?? 0})`}
            </button>
          ))}
        </div>
        {!positions.length ? (
          <div className="empty">{posTab === "OPEN" ? "Nothing open." : "No closed trades yet."}</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>TF</th>
                  <th style={{ textAlign: "left" }}>Instrument</th>
                  <th>View</th>
                  <th>Size</th>
                  <th>Entry</th>
                  <th>{posTab === "OPEN" ? "Now" : "Exit"}</th>
                  <th title="On the underlying, from the strategy's own levels">Stop / target</th>
                  <th>Deployed</th>
                  {posTab === "CLOSED" && <th>Charges</th>}
                  <th>{posTab === "OPEN" ? "Unrealised" : "Net P&L"}</th>
                  <th>{posTab === "OPEN" ? "Opened" : "Closed"}</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const legs = p.legs ?? [];
                  const now = posTab === "OPEN" ? (p.mark_legs ?? null) : (p.exit_legs ?? null);
                  return (
                    <tr key={p.position_id}>
                      <td style={{ textAlign: "left" }}>{p.strategy_name}</td>
                      <td><span className="badge">{p.timeframe}</span></td>
                      <td style={{ textAlign: "left" }} className="dim">
                        {legs.length ? legs.map((l) => `${l.side === "SELL" ? "−" : "+"}${l.tradingsymbol}`).join(" ") : p.symbol}
                      </td>
                      <td><span className={p.signal_side === "SELL" ? "side short" : "side long"}>{p.signal_side === "SELL" ? "BEAR" : "BULL"}</span></td>
                      <td>{legs.length ? `${p.lots} lot` : num(p.lots, 4)}</td>
                      <td>{legs.length ? legs.map((l) => num(l.entry)).join(" / ") : num(p.entry_px)}</td>
                      <td>{legs.length ? (now ? now.map((x) => num(x)).join(" / ") : "—") : num(posTab === "OPEN" ? p.under_ltp : p.exit_px)}</td>
                      <td className="dim">{num(p.stop)} / {num(p.target)}</td>
                      <td>{money(p.capital_deployed)}</td>
                      {posTab === "CLOSED" && <td className="loss">{money(p.fees, 2)}</td>}
                      <td className={tone(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}>
                        {signed(posTab === "OPEN" ? p.unrealized_pnl : p.realized_pnl)}
                      </td>
                      <td className="dim" title={p.exit_reason ? `${p.exit_reason}${p.exit_basis ? ` · ${p.exit_basis}` : ""}` : ""}>
                        {when(posTab === "OPEN" ? p.opened_at : p.closed_at)}{posTab === "CLOSED" && p.exit_reason ? ` · ${p.exit_reason}` : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .note { padding: 12px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border);
                font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .note p { margin: 0 0 8px; }
        .note p:last-child { margin-bottom: 0; }
        .note b { color: var(--text); }
        .dim { color: var(--text-faint); }
        .controls { display: flex; gap: 8px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 6px 11px; border-radius: 8px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
        .chip.on { background: var(--brand-dim); border-color: rgba(var(--brand-rgb), 0.35); color: var(--brand); }
        .toggle-label { font-size: 11.5px; color: var(--text-muted); display: inline-flex; gap: 6px; align-items: center; margin-left: 6px; }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); line-height: 1.5; }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .side { font-size: 9.5px; font-weight: 800; letter-spacing: 0.04em; padding: 2px 6px; border-radius: 5px; }
        .side.short { background: var(--loss-dim); color: var(--loss); }
        .side.long { background: var(--brand-dim); color: var(--brand); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </>
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
        .t-value { font-family: var(--font-display); font-weight: 800; font-size: 21px; margin-top: 6px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { font-size: 11px; color: var(--text-faint); margin-top: 4px; }
      `}</style>
    </div>
  );
}
