"use client";

/** Natural Gas Paper Trading — Rs 2 lakh on two picked NATGASMINI strategies.
 *
 * Every style this component uses is declared in it. styled-jsx scopes CSS to the
 * component that declares it, so leaning on the page's classes would render this tab with
 * browser defaults — the exact bug that left the Intraday Stocks Daily ROI table unstyled.
 */

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import DeskHistory from "../../components/DeskHistory";
import {
  NatGasPosition,
  NatGasStrategy,
  NatGasSummary,
  closeAllNatGas,
  fetchNatGasPositions,
  fetchNatGasStrategies,
  fetchNatGasSummary,
  runNatGasCycle,
  toggleNatGasBook,
} from "../../lib/api";

const REFRESH_MS = 20000;

const money = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const rs = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: dp })}`;
const pc = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");

export default function NatGasBook() {
  const [sum, setSum] = useState<NatGasSummary | null>(null);
  const [strats, setStrats] = useState<NatGasStrategy[]>([]);
  const [open, setOpen] = useState<NatGasPosition[]>([]);
  const [closed, setClosed] = useState<NatGasPosition[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, st, o, c] = await Promise.all([
        fetchNatGasSummary(), fetchNatGasStrategies(),
        fetchNatGasPositions("OPEN"), fetchNatGasPositions("CLOSED"),
      ]);
      setSum(s);
      setStrats(st.strategies);
      setOpen(o.positions);
      setClosed(c.positions);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the book.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const act = async (key: string, fn: () => Promise<unknown>, done: (r: never) => string) => {
    setBusy(key);
    setMsg(null);
    try {
      const r = await fn();
      setMsg(done(r as never));
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  };

  const on = sum?.enabled ?? false;

  return (
    <>
      {err && <div className="bad">{err}</div>}
      {msg && <div className="ok" onClick={() => setMsg(null)}>{msg}</div>}

      <div className={`arm ${on ? "on" : "off"}`}>
        <div>
          <div className="arm-title">NATURAL GAS BOOK {on ? "ON" : "OFF"}</div>
          <div className="arm-sub">
            {rs(sum?.capital)} on {sum?.symbol ?? "NATGASMINI"}, trading two picked strategies in whole
            lots on margin. Runs on its own switch — independent of the Pre-Live engine above.
            {sum?.breaker_tripped && " Daily loss breaker is tripped: no new entries today."}
          </div>
        </div>
        <div className="arm-actions">
          <button className="btn" disabled={!!busy}
                  onClick={() => act("run", runNatGasCycle,
                    (r: { opened: number; managed: number }) => `Cycle run — ${r.opened} opened, ${r.managed} managed.`)}>
            {busy === "run" ? "Running…" : "Run cycle"}
          </button>
          <button className="btn danger" disabled={!!busy || !open.length}
                  onClick={() => act("close", closeAllNatGas,
                    (r: { closed: number; net_pnl: number }) => `Closed ${r.closed} — net ${money(r.net_pnl)}.`)}>
            Close all
          </button>
          <button className={`switch ${on ? "on" : ""}`} disabled={!!busy}
                  onClick={() => act("toggle", () => toggleNatGasBook(!on),
                    () => (on ? "Book switched OFF — open positions still managed." : "Book switched ON."))}
                  aria-label="Toggle the natural gas book">
            <span className="knob" />
            <span className="lbl">{on ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>

      {/* realised / unrealised / total, each against the same Rs 2 lakh, so the three % add up */}
      <div className="pnl">
        <div className="card">
          <div className="lab">Realised P&amp;L</div>
          <div className={`val ${tone(sum?.realized_pnl)}`}>{money(sum?.realized_pnl)}</div>
          <div className={`pct ${tone(sum?.realized_pnl)}`}>{pc(sum?.realized_pct)}</div>
          <div className="sub">{sum?.closed_positions ?? 0} closed · after {rs(sum?.total_costs)} MCX charges</div>
        </div>
        <div className="card">
          <div className="lab">Unrealised P&amp;L</div>
          <div className={`val ${tone(sum?.unrealized_pnl)}`}>{money(sum?.unrealized_pnl)}</div>
          <div className={`pct ${tone(sum?.unrealized_pnl)}`}>{pc(sum?.unrealized_pct)}</div>
          <div className="sub">{sum?.open_positions ?? 0} open · marked on live Angel quotes</div>
        </div>
        <div className="card total">
          <div className="lab">Total P&amp;L</div>
          <div className={`val ${tone(sum?.total_pnl)}`}>{money(sum?.total_pnl)}</div>
          <div className={`pct ${tone(sum?.total_pnl)}`}>{pc(sum?.total_pct)}</div>
          <div className="sub">realised + unrealised, on {rs(sum?.capital)}</div>
        </div>
      </div>

      <div className="tiles">
        <div className="tile"><div className="lab">Equity</div><div className="tv">{rs(sum?.equity)}</div><div className="sub">from {rs(sum?.capital)}</div></div>
        <div className="tile"><div className="lab">Today</div><div className={`tv ${tone(sum?.today_pnl)}`}>{money(sum?.today_pnl)}</div><div className="sub">{pc(sum?.today_pct)} · breaker at −{rs(sum?.daily_loss_limit)}</div></div>
        <div className="tile"><div className="lab">Margin blocked</div><div className="tv">{rs(sum?.margin_deployed)}</div><div className="sub">{rs(sum?.available_margin)} free</div></div>
        <div className="tile"><div className="lab">Win rate</div><div className="tv">{(sum?.win_rate ?? 0).toFixed(1)}%</div><div className="sub">over {sum?.closed_positions ?? 0} closed trades</div></div>
      </div>

      <GlassPanel title="The two strategies — their record in THIS book">
        <div className="wrap">
          <table>
            <thead>
              <tr>
                <th className="l">Strategy</th><th className="l">Family</th><th>TF</th><th>Trades</th>
                <th>Win %</th><th>PF</th><th>Expectancy</th><th>Max DD</th><th>T-stat</th>
                <th>Costs</th><th>Realised</th><th>Unrealised</th><th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {strats.map((s) => (
                <tr key={`${s.template}:${s.timeframe}`}>
                  <td className="l"><b>{s.name}</b>{s.open_positions > 0 && <span className="dot" title="position open" />}</td>
                  <td className="l"><span className="fam">{s.family_label}</span></td>
                  <td>{s.timeframe}</td>
                  <td>{s.trades}</td>
                  <td>{s.trades ? `${s.win_rate.toFixed(0)}%` : "—"}</td>
                  <td>{s.profit_factor != null ? s.profit_factor.toFixed(2) : "—"}</td>
                  <td className={tone(s.expectancy)}>{s.trades ? money(s.expectancy) : "—"}</td>
                  <td>{s.trades ? `${s.max_drawdown_pct.toFixed(1)}%` : "—"}</td>
                  <td>{s.t_stat != null ? s.t_stat.toFixed(2) : "—"}</td>
                  <td>{rs(s.total_costs, 2)}</td>
                  <td className={tone(s.realized_pnl)}>{money(s.realized_pnl)}</td>
                  <td className={tone(s.unrealized_pnl)}>{money(s.unrealized_pnl)}</td>
                  <td><span className={`verdict ${s.verdict.toLowerCase()}`} title={s.verdict_reasons.join(" · ")}>{s.verdict}</span></td>
                </tr>
              ))}
              {!strats.length && <tr><td colSpan={13} className="empty">Loading roster…</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="note">
          These numbers start at zero: they are this book&rsquo;s own trades, not the Pre-Live desk&rsquo;s.
          On that desk these two made +₹13,808 and +₹6,037 over 21 trades each — this book is where
          they show whether that repeats.
        </p>
      </GlassPanel>

      <GlassPanel title={`Open positions (${open.length})`}>
        <div className="wrap">
          <table>
            <thead>
              <tr>
                <th className="l">Strategy</th><th>Side</th><th>Lots</th><th>Entry</th><th>LTP</th>
                <th>Target</th><th>Stop</th><th>Margin</th><th>Unrealised</th><th>On margin</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={p.position_id}>
                  <td className="l"><b>{p.strategy_name}</b> · {p.timeframe}</td>
                  <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                  <td>{p.lots}</td>
                  <td>{rs(p.entry_price, 2)}</td>
                  <td>{rs(p.ltp, 2)}</td>
                  <td>{rs(p.target, 2)}</td>
                  <td>{rs(p.stoploss, 2)}</td>
                  <td>{rs(p.margin_used)}</td>
                  <td className={tone(p.unrealized_pnl)}>{money(p.unrealized_pnl)}</td>
                  <td className={tone(p.return_on_margin_pct)}>{pc(p.return_on_margin_pct)}</td>
                </tr>
              ))}
              {!open.length && <tr><td colSpan={10} className="empty">No open positions — the book is flat.</td></tr>}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title={`Closed trades (${closed.length})`}>
        <div className="wrap">
          <table>
            <thead>
              <tr>
                <th className="l">Closed</th><th className="l">Strategy</th><th>Side</th><th>Entry</th>
                <th>Exit</th><th>Reason</th><th>Costs</th><th>Net P&amp;L</th><th>On margin</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((p) => (
                <tr key={p.position_id}>
                  <td className="l">{p.closed_at ? new Date(p.closed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                  <td className="l">{p.strategy_name} · {p.timeframe}</td>
                  <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                  <td>{rs(p.entry_price, 2)}</td>
                  <td>{rs(p.exit_price, 2)}</td>
                  <td>{(p.exit_reason || "").replace(/_/g, " ")}</td>
                  <td>{rs(p.costs, 2)}</td>
                  <td className={tone(p.realized_pnl)}>{money(p.realized_pnl)}</td>
                  <td className={tone(p.return_on_margin_pct)}>{pc(p.return_on_margin_pct)}</td>
                </tr>
              ))}
              {!closed.length && <tr><td colSpan={9} className="empty">No closed trades yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      {sum?.last_notes && sum.last_notes.length > 0 && (
        <GlassPanel title="Last cycle">
          <ul className="notes">{sum.last_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </GlassPanel>
      )}

      <DeskHistory deskKey="natgas-book" title="History — Natural Gas Paper Trading" />

      <style jsx>{`
        .bad, .ok { font-size: 12.5px; border-radius: 9px; padding: 10px 12px; cursor: pointer; }
        .bad { color: var(--loss); background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.3); }
        .ok { color: var(--gain); background: rgba(34, 170, 96, 0.08); border: 1px solid rgba(34, 170, 96, 0.3); }
        .arm { display: flex; justify-content: space-between; align-items: center; gap: 16px;
               border-radius: 14px; padding: 16px 20px; border: 1px solid var(--panel-border); flex-wrap: wrap; }
        .arm.on { background: rgba(34, 170, 96, 0.07); border-color: rgba(34, 170, 96, 0.35); }
        .arm.off { background: var(--canvas-soft); }
        .arm-title { font-weight: 800; font-size: 15px; letter-spacing: 0.04em; }
        .arm.on .arm-title { color: var(--gain); }
        .arm-sub { font-size: 12.5px; color: var(--text-muted); margin-top: 4px; max-width: 760px; line-height: 1.5; }
        .arm-actions { display: flex; gap: 10px; align-items: center; }
        .btn { background: var(--panel); border: 1px solid var(--panel-border); color: var(--text);
               border-radius: 9px; padding: 8px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .btn.danger { color: var(--loss); border-color: rgba(217, 45, 63, 0.35); }
        .btn:disabled { opacity: 0.5; cursor: default; }
        .switch { position: relative; width: 96px; height: 36px; border-radius: 20px; border: none;
                  background: var(--panel-border); cursor: pointer; transition: background 0.2s; }
        .switch.on { background: var(--gain); }
        .knob { position: absolute; top: 4px; left: 4px; width: 28px; height: 28px; border-radius: 50%;
                background: #fff; transition: left 0.2s; }
        .switch.on .knob { left: 64px; }
        .lbl { position: absolute; top: 50%; transform: translateY(-50%); font-size: 12px; font-weight: 800; color: #fff; }
        .switch.on .lbl { left: 14px; }
        .switch:not(.on) .lbl { right: 14px; color: var(--text-muted); }
        .pnl { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
        .card, .tile { border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px; background: var(--panel); }
        .card.total { background: var(--canvas-soft); border-color: rgba(125, 52, 220, 0.28); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
        .lab { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .val { font-size: 22px; font-weight: 750; font-variant-numeric: tabular-nums; margin-top: 4px; }
        .tv { font-size: 18px; font-weight: 750; font-variant-numeric: tabular-nums; margin-top: 4px; }
        .pct { font-size: 12.5px; font-weight: 650; font-variant-numeric: tabular-nums; margin-top: 1px; }
        .sub { margin-top: 4px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
        .wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
             text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        td { padding: 8px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        tbody tr:hover td { background: var(--canvas-soft); }
        .l { text-align: left; }
        .empty { color: var(--text-faint); padding: 18px; }
        .fam { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;
               background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--gain); margin-left: 7px; vertical-align: middle; }
        .verdict { display: inline-block; padding: 4px 11px; border-radius: 20px; font-size: 10.5px; font-weight: 700;
                   letter-spacing: 0.04em; border: 1px solid var(--panel-border); background: var(--canvas-soft); cursor: help; }
        .verdict.ready { color: var(--gain); border-color: rgba(34, 170, 96, 0.4); }
        .verdict.rejected { color: var(--loss); border-color: rgba(217, 45, 63, 0.4); }
        .note { font-size: 11.5px; color: var(--text-faint); margin: 12px 0 0; line-height: 1.5; }
        .notes { margin: 0; padding-left: 18px; font-size: 12px; color: var(--text-muted); line-height: 1.6; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </>
  );
}
