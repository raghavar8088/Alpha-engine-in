"use client";

import { useCallback, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import {
  LiveTradingOpenPosition,
  LiveTradingScore,
  LiveTradingSummary,
  fetchLiveTradingLeaderboard,
  fetchLiveTradingPositions,
  fetchLiveTradingSummary,
  panicCloseAllLiveTrading,
  setLiveTradingArmed,
  setLiveTradingKillSwitch,
  setLiveTradingStrategyEnabled,
} from "../../lib/api";

const REFRESH_MS = 15000;

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

export default function LiveTradingPage() {
  const [summary, setSummary] = useState<LiveTradingSummary | null>(null);
  const [board, setBoard] = useState<LiveTradingScore[]>([]);
  const [positions, setPositions] = useState<LiveTradingOpenPosition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, lb, pos] = await Promise.all([
        fetchLiveTradingSummary(),
        fetchLiveTradingLeaderboard(),
        fetchLiveTradingPositions(),
      ]);
      setSummary(s);
      setBoard(lb);
      setPositions(pos.open ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the live trading desk");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const armed = !!summary?.armed;
  const killed = !!summary?.kill_switch;

  const toggleArm = async () => {
    if (busy || !summary) return;
    if (!armed) {
      const ok = window.confirm(
        "ARM LIVE TRADING?\n\nThis places REAL orders with real money on your Dhan account as the " +
          "strategies fire during market hours (each capped at ₹10,000, ₹80,000 desk total). " +
          "You can disarm or hit the kill switch at any time.\n\nArm the desk now?",
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      const r = await setLiveTradingArmed(!armed);
      setSummary(r.summary);
      setNotice(!armed ? "Live trading ARMED — real orders will be placed as signals fire." : "Live trading DISARMED — no new orders; open positions still managed.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change armed state");
    } finally {
      setBusy(false);
    }
  };

  const toggleKill = async () => {
    if (busy || !summary) return;
    setBusy(true);
    try {
      const r = await setLiveTradingKillSwitch(!killed);
      setSummary(r.summary);
      setNotice(!killed ? "KILL SWITCH ON — all new orders halted." : "Kill switch off — new orders allowed again (if armed).");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to toggle kill switch");
    } finally {
      setBusy(false);
    }
  };

  const panic = async () => {
    if (busy) return;
    const ok = window.confirm(
      "PANIC — CLOSE ALL?\n\nThis immediately squares off every open position with market orders, " +
        "disarms the desk, and trips the kill switch. Proceed?",
    );
    if (!ok) return;
    setBusy(true);
    try {
      const r = await panicCloseAllLiveTrading();
      setSummary(r.summary);
      setNotice(`Panic close-all: ${r.result.closed} squared off${r.result.failed ? `, ${r.result.failed} failed (will retry)` : ""}. Desk disarmed.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Panic close-all failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleStrategy = async (s: LiveTradingScore) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await setLiveTradingStrategyEnabled(s.strategy_id, !s.enabled);
      setBoard(r.leaderboard);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to toggle strategy");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        crumb="Live Trading"
        title="Live Trading"
        subtitle="REAL-MONEY desk: the same 8 intraday strategies as the Live Intraday shortlist, but routing real orders to your Dhan account when ARMED. Each strategy trades up to ₹10,000 (₹80,000 desk ceiling, server-enforced), on the live Angel One feed. Cash equities can't hold shorts overnight, so every order is INTRADAY (MIS) and squares off the same day. Ships disarmed — nothing trades until you flip the toggle."
      />

      {error && <ErrorBanner message={error} />}
      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}

      {/* The big green/red LIVE TRADING switch */}
      <div className={`arm-banner ${armed ? "on" : "off"}`}>
        <div className="arm-left">
          <div className="arm-title">
            LIVE TRADING {armed ? "ENABLED" : "OFF"}
            <span className="mode-tag">REAL MONEY · {inr(summary?.desk_ceiling)} ceiling</span>
          </div>
          <div className="arm-sub">
            {armed
              ? "Real orders are placed on your Dhan account as strategies fire during market hours."
              : "Disarmed — no orders are placed. Turn on to trade with real money."}
            {summary?.disarmed_reason && !armed ? ` · last: ${summary.disarmed_reason}` : ""}
          </div>
        </div>
        <button className={`switch ${armed ? "on" : "off"}`} onClick={toggleArm} disabled={busy} aria-label="Toggle live trading">
          <span className="knob" />
          <span className="switch-label">{armed ? "ON" : "OFF"}</span>
        </button>
      </div>

      {/* Kill switch + panic + broker status */}
      <div className="controls">
        <button className={`ctl ${killed ? "kill-on" : ""}`} onClick={toggleKill} disabled={busy}>
          {killed ? "● KILL SWITCH ON — new orders halted" : "Kill switch off — trading allowed"}
        </button>
        <button className="ctl panic" onClick={panic} disabled={busy}>Panic — CLOSE ALL</button>
        <span className={`broker ${summary?.broker_connected ? "ok" : "bad"}`}>
          {summary?.broker_connected ? "Dhan connected" : "Dhan not connected"}
        </span>
        {summary?.breaker_tripped && <span className="breaker">Daily loss breaker tripped</span>}
        <span className="rejects">{summary ? `rejects ${summary.consecutive_rejects}/${summary.max_consecutive_rejects} → auto-disarm` : ""}</span>
      </div>

      {/* Summary tiles */}
      <div className="tiles">
        <Tile label="Mode" value="REAL" tone={armed ? "gain" : "loss"} sub={armed ? "armed · live Dhan" : "disarmed"} />
        <Tile label="Equity" value={inr(summary?.equity)} sub={`from ${inr(summary?.initial_capital)}`} />
        <Tile label="Today P&L" value={signed(summary?.today_pnl)} tone={(summary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"} sub={`breaker at −${inr(summary?.daily_loss_limit)}`} />
        <Tile label="Realised P&L" value={signed(summary?.realized_pnl)} tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"} sub={`${summary?.closed_positions ?? 0} closed`} />
        <Tile label="Open positions" value={String(summary?.open_positions ?? 0)} sub={`${inr(summary?.unrealized_pnl)} unrealised`} />
        <Tile label="Deployed" value={inr(summary?.deployed_capital)} sub={`${inr(summary?.available_cash)} free of ${inr(summary?.desk_ceiling)}`} />
        <Tile label="Strategies" value={String(board.filter((s) => s.enabled).length)} sub={`of ${summary?.strategy_count ?? 0} enabled`} />
      </div>

      <GlassPanel title="Selected strategies">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Strategy</th>
                <th>Category</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>Net P&L</th>
                <th>Account</th>
                <th>Live trade</th>
              </tr>
            </thead>
            <tbody>
              {board.map((s) => (
                <tr key={s.strategy_id} className={s.enabled ? "" : "disabled-row"}>
                  <td style={{ textAlign: "left" }}>
                    <span className="sname">
                      {s.is_anti && <span className="anti">ANTI</span>}
                      {s.name}
                    </span>
                  </td>
                  <td><span className="cat">{s.category}</span></td>
                  <td>{s.trades}</td>
                  <td>{s.trades ? `${(s.win_rate * 100).toFixed(1)}%` : "-"}</td>
                  <td className={s.net_pnl >= 0 ? "gain" : "loss"}>{signed(s.net_pnl)}</td>
                  <td>{inr(s.allocated_capital)}</td>
                  <td>
                    <button
                      className={`mini-switch ${s.enabled ? "on" : "off"}`}
                      onClick={() => toggleStrategy(s)}
                      disabled={busy}
                      title={s.enabled ? "Enabled — takes new live entries" : "Disabled — no new live entries"}
                    >
                      <span className="mini-knob" />
                      <span className="mini-label">{s.enabled ? "ON" : "OFF"}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title={`Open positions (${positions.length})`}>
        {!positions.length ? (
          <div className="empty">No open positions.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol</th>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>Target</th>
                  <th>Stop</th>
                  <th>Unrealised</th>
                  <th>Order id</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td style={{ textAlign: "left" }} className="sym">{p.symbol}</td>
                    <td style={{ textAlign: "left" }} className="pstrat">
                      {p.is_anti && <span className="anti">ANTI</span>}{p.strategy_name}
                    </td>
                    <td><span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span></td>
                    <td>{p.qty}</td>
                    <td>{inr(p.entry_price)}</td>
                    <td>{inr(p.ltp)}</td>
                    <td className="gain">{inr(p.target)}</td>
                    <td className="loss">{inr(p.stoploss)}</td>
                    <td className={p.unrealized_pnl >= 0 ? "gain" : "loss"}>{signed(p.unrealized_pnl)} <span className="muted">({pct(p.pnl_pct)})</span></td>
                    <td className="muted oid">{p.entry_order_id || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .notice { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12.5px; cursor: pointer; }
        .arm-banner { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 22px; border-radius: 14px; border: 1px solid; }
        .arm-banner.on { background: rgba(14, 159, 110, 0.10); border-color: rgba(14, 159, 110, 0.4); }
        .arm-banner.off { background: rgba(224, 49, 49, 0.08); border-color: rgba(224, 49, 49, 0.35); }
        .arm-title { font-family: var(--font-display); font-weight: 800; font-size: 18px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .arm-banner.on .arm-title { color: var(--gain); }
        .arm-banner.off .arm-title { color: var(--loss); }
        .mode-tag { font-size: 10px; font-weight: 800; letter-spacing: 0.05em; padding: 3px 8px; border-radius: 6px; background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .arm-sub { font-size: 12.5px; color: var(--text-muted); margin-top: 4px; }
        .switch { position: relative; width: 128px; height: 46px; border-radius: 24px; border: none; cursor: pointer; display: flex; align-items: center; transition: background 0.15s; flex-shrink: 0; }
        .switch.on { background: var(--gain); justify-content: flex-end; }
        .switch.off { background: var(--loss); justify-content: flex-start; }
        .switch:disabled { opacity: 0.6; cursor: default; }
        .knob { width: 38px; height: 38px; border-radius: 50%; background: #fff; margin: 0 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.3); }
        .switch-label { position: absolute; top: 50%; transform: translateY(-50%); color: #fff; font-weight: 800; font-size: 13px; letter-spacing: 0.05em; }
        .switch.on .switch-label { left: 18px; }
        .switch.off .switch-label { right: 16px; }
        .controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .ctl { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 14px; border-radius: 9px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .ctl.kill-on { background: var(--loss-dim); border-color: rgba(224,49,49,0.4); color: var(--loss); }
        .ctl.panic { color: var(--loss); border-color: rgba(224,49,49,0.4); }
        .ctl:disabled { opacity: 0.6; cursor: default; }
        .broker { font-size: 12px; font-weight: 700; padding: 6px 10px; border-radius: 7px; }
        .broker.ok { color: var(--gain); background: var(--gain-dim); }
        .broker.bad { color: var(--loss); background: var(--loss-dim); }
        .breaker { font-size: 12px; font-weight: 700; color: var(--loss); }
        .rejects { font-size: 11.5px; color: var(--text-faint); margin-left: auto; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 9px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        tr.disabled-row { opacity: 0.5; }
        .sname { font-weight: 600; display: inline-flex; align-items: center; gap: 7px; }
        .anti { font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 4px; background: var(--purple-dim); color: var(--purple); }
        .cat { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 6px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .sym { font-weight: 700; }
        .pstrat { color: var(--text-muted); display: inline-flex; align-items: center; gap: 6px; }
        .side { font-weight: 800; font-size: 11px; padding: 2px 8px; border-radius: 6px; }
        .side.buy { color: var(--gain); background: var(--gain-dim); }
        .side.sell { color: var(--loss); background: var(--loss-dim); }
        .oid { font-size: 10.5px; }
        .mini-switch { position: relative; width: 62px; height: 26px; border-radius: 14px; border: none; cursor: pointer; display: flex; align-items: center; }
        .mini-switch.on { background: var(--gain); justify-content: flex-end; }
        .mini-switch.off { background: var(--text-faint); justify-content: flex-start; }
        .mini-switch:disabled { opacity: 0.6; cursor: default; }
        .mini-knob { width: 20px; height: 20px; border-radius: 50%; background: #fff; margin: 0 3px; }
        .mini-label { position: absolute; top: 50%; transform: translateY(-50%); color: #fff; font-weight: 800; font-size: 9px; }
        .mini-switch.on .mini-label { left: 9px; }
        .mini-switch.off .mini-label { right: 8px; }
        .muted { color: var(--text-faint); }
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
        .t-value { font-family: var(--font-display); font-weight: 800; font-size: 22px; margin-top: 6px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { font-size: 11px; color: var(--text-faint); margin-top: 4px; }
      `}</style>
    </div>
  );
}
