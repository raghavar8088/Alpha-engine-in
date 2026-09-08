"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import {
  refreshing,
  CommodityPreliveBoard,
  CommodityPrelivePosition,
  CommodityPreliveScore,
  CommodityPreliveScript,
  CommodityPreliveSummary,
  CommodityPreliveTrade,
  closeAllCommodityPrelive,
  fetchCommodityPreliveBoard,
  fetchCommodityPrelivePositions,
  fetchCommodityPreliveScripts,
  fetchCommodityPreliveSummary,
  fetchCommodityPreliveTrades,
  runCommodityPreliveCycle,
  setCommodityPreliveAdmissionMode,
  setCommodityPreliveAllScripts,
  setCommodityPreliveEngine,
  setCommodityPreliveScript,
} from "../../lib/api";

const REFRESH_MS = 20000;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"];
const FAMILIES = [
  { key: "chart", label: "Chart Pattern" },
  { key: "candlestick", label: "Candlestick" },
  { key: "structure", label: "Price Structure" },
];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const inr2 = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const num = (v: number | null | undefined, dp = 2) => (v === null || v === undefined ? "-" : v.toFixed(dp));

const VERDICT_TONE: Record<string, "gain" | "loss" | "muted"> = {
  READY: "gain",
  REJECTED: "loss",
  PENDING: "muted",
};

export default function CommodityPrelivePage() {
  const [summary, setSummary] = useState<CommodityPreliveSummary | null>(null);
  const [scripts, setScripts] = useState<CommodityPreliveScript[]>([]);
  const [scriptsNote, setScriptsNote] = useState<string>("");
  const [board, setBoard] = useState<CommodityPreliveBoard | null>(null);
  const [positions, setPositions] = useState<CommodityPrelivePosition[]>([]);
  const [trades, setTrades] = useState<CommodityPreliveTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [symbol, setSymbol] = useState<string>("ALL");
  const [family, setFamily] = useState<string>("ALL");
  const [timeframe, setTimeframe] = useState<string>("ALL");
  const [verdict, setVerdict] = useState<string>("ALL");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, sc, lb, pos, tr] = await Promise.all([
        fetchCommodityPreliveSummary(),
        fetchCommodityPreliveScripts(),
        fetchCommodityPreliveBoard({
          symbol: symbol === "ALL" ? undefined : symbol,
          family: family === "ALL" ? undefined : family,
          timeframe: timeframe === "ALL" ? undefined : timeframe,
          verdict: verdict === "ALL" ? undefined : verdict,
        }),
        fetchCommodityPrelivePositions(),
        fetchCommodityPreliveTrades(60),
      ]);
      setSummary(s);
      setScripts(sc.rows ?? []);
      setScriptsNote(sc.note ?? "");
      setBoard(lb);
      setPositions(pos.open ?? []);
      setTrades(tr);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the Pre-Live Commodity desk");
    }
  }, [symbol, family, timeframe, verdict]);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const act = async (label: string, fn: () => Promise<unknown>, msg?: string) => {
    if (busy) return;
    setBusy(label);
    setNotice(null);
    try {
      await fn();
      if (msg) setNotice(msg);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${label} failed`);
    } finally {
      setBusy(null);
    }
  };

  const engineOn = !!summary?.enabled;
  const gate = summary?.promotion_gate;
  const capital = summary?.script_capital ?? 200000;
  const activeScripts = summary?.active_scripts ?? [];
  const untradable = useMemo(() => scripts.filter((s) => !s.tradable && !s.unpriced), [scripts]);
  const symbolsWithRows = useMemo(
    () => Array.from(new Set((board?.rows ?? []).map((r) => r.symbol))).sort(),
    [board],
  );

  const toggleEngine = () =>
    act(
      "engine",
      () => setCommodityPreliveEngine(!engineOn),
      !engineOn
        ? "Pre-Live engine ON — admitted strategies will take whole-lot paper positions on the contracts you have switched on."
        : "Pre-Live engine OFF — no new entries. Open positions are still managed to their target or stop.",
    );

  const toggleScript = (row: CommodityPreliveScript) =>
    act(
      `script:${row.symbol}`,
      () => setCommodityPreliveScript(row.symbol, !row.enabled),
      `${row.symbol} switched ${row.enabled ? "OFF" : "ON"}.`,
    );

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Pre-Live Commodity Trading"
        title="Pre-Live Commodity Trading"
        subtitle={
          <>
            The graduation desk above Commodity Trading. Only patterns that already{" "}
            <strong>cleared that desk&rsquo;s promotion gate</strong> trade here, and they trade the way a
            real account would: <strong>whole MCX lots</strong> sized against SPAN-lite margin, on a{" "}
            <strong>₹{capital.toLocaleString("en-IN")} book per contract</strong> rather than per strategy.
            Every contract has its own switch, and the engine ships off. Still paper — fills are simulated
            and charged real MCX brokerage, CTT, exchange, SEBI, stamp duty and GST; no order reaches a
            broker from this page.
          </>
        }
        actions={
          <>
            <StatusPill label="Pre-live · paper" tone="accent" />
            {summary?.market_open ? (
              <StatusPill label="MCX open" tone="gain" pulse />
            ) : (
              <StatusPill label="MCX closed" tone="muted" />
            )}
            <button className="btn" onClick={() => act("run", runCommodityPreliveCycle)} disabled={!!busy}>
              {busy === "run" ? "Running…" : "Run cycle"}
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}
      {notice && (
        <div className="notice" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      {/* ── the master switch ─────────────────────────────────────────────────── */}
      <div className={`arm-banner ${engineOn ? "on" : "off"}`}>
        <div>
          <div className="arm-title">PRE-LIVE ENGINE {engineOn ? "ON" : "OFF"}</div>
          <div className="arm-sub">
            {engineOn
              ? `Running — ${activeScripts.length} of ${summary?.script_count ?? 0} contracts switched on, ` +
                `${summary?.admitted_total ?? 0} admitted strategies, ` +
                `${inr(summary?.capital_switched_on)} of capital live.`
              : "Off — no new positions are taken. Open positions are still managed to their target or stop, " +
                "because an open position is exposure whether or not the desk may add to it."}
            {summary?.disabled_reason && !engineOn ? ` · last: ${summary.disabled_reason}` : ""}
          </div>
        </div>
        <button
          className={`switch ${engineOn ? "on" : "off"}`}
          onClick={toggleEngine}
          disabled={!!busy}
          aria-label="Toggle the pre-live engine"
        >
          <span className="knob" />
          <span className="switch-label">{engineOn ? "ON" : "OFF"}</span>
        </button>
      </div>

      {summary?.breaker_tripped && (
        <div className="breaker">
          Daily loss breaker tripped — today&rsquo;s P&amp;L {signed(summary.today_pnl)} crossed the{" "}
          {inr(summary.daily_loss_limit)} limit (3% of the {inr(summary.breaker_base)} you have switched on).
          No new positions; open ones still managed.
        </div>
      )}

      <div className="tiles">
        <Tile
          label="Desk equity"
          value={inr(summary?.equity)}
          sub={`${summary?.script_count ?? 0} × ${inr(capital)} = ${inr(summary?.initial_capital)}`}
        />
        <Tile
          label="Today P&L"
          value={signed(summary?.today_pnl)}
          tone={(summary?.today_pnl ?? 0) >= 0 ? "gain" : "loss"}
          sub={`breaker at ${inr(summary?.daily_loss_limit)}`}
        />
        <Tile
          label="Realised (net)"
          value={signed(summary?.realized_pnl)}
          tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}
          sub={`${summary?.closed_positions ?? 0} closed`}
        />
        <Tile
          label="Margin blocked"
          value={inr(summary?.margin_deployed)}
          sub={`${summary?.open_positions ?? 0} open · ${inr(summary?.available_margin)} free`}
        />
        <Tile
          label="MCX charges paid"
          value={inr2(summary?.total_costs)}
          tone="loss"
          sub={`+ ${summary?.slippage_bps ?? 5} bps slippage/side`}
        />
        <Tile
          label="Contracts switched on"
          value={`${summary?.active_script_count ?? 0} / ${summary?.script_count ?? 0}`}
          tone={(summary?.active_script_count ?? 0) > 0 ? "gain" : undefined}
          sub={`${inr(summary?.capital_switched_on)} live`}
        />
        <Tile
          label="Admitted strategies"
          value={String(summary?.admitted_total ?? 0)}
          sub={`from the paper desk's ${summary?.admission_mode === "blended" ? "blended" : "per-contract"} gate`}
        />
      </div>

      {/* ── per-contract switches ─────────────────────────────────────────────── */}
      <GlassPanel
        title={`Contracts — one switch and one ${inr(capital)} book each`}
        note={`${summary?.active_script_count ?? 0} on · ${scripts.length} contracts`}
      >
        <div className="toolbar">
          <button
            className="btn sm"
            onClick={() => act("all-on", () => setCommodityPreliveAllScripts(true), "All contracts switched on.")}
            disabled={!!busy}
          >
            All on
          </button>
          <button
            className="btn sm"
            onClick={() => act("all-off", () => setCommodityPreliveAllScripts(false), "All contracts switched off.")}
            disabled={!!busy}
          >
            All off
          </button>
          <span className="tb-note">
            Only the contracts switched on take new positions. Switch one on by itself and the desk trades
            that contract alone.
          </span>
        </div>
        {!scripts.length ? (
          <EmptyState
            title="No contracts resolved"
            note="No unexpired MCX front-month futures with an Angel token are on file."
          />
        ) : (
          <>
            <div className="script-grid">
              {scripts.map((s) => (
                <div key={s.symbol} className={`script ${s.enabled ? "on" : "off"} ${s.tradable ? "" : "blocked"}`}>
                  <div className="s-head">
                    <div>
                      <div className="s-sym">{s.symbol}</div>
                      <div className="s-contract">{s.contract}</div>
                    </div>
                    <button
                      className={`mini-switch ${s.enabled ? "on" : "off"}`}
                      onClick={() => toggleScript(s)}
                      disabled={!!busy}
                      aria-label={`Toggle ${s.symbol}`}
                    >
                      <span className="mini-knob" />
                    </button>
                  </div>

                  <div className="s-rows">
                    <Row label="Book" value={inr(s.capital)} />
                    <Row label="LTP" value={s.ltp === null ? "no quote" : inr2(s.ltp)} dim={s.ltp === null} />
                    <Row label="1 lot" value={`${s.multiplier.toLocaleString("en-IN")} × price`} dim />
                    <Row label="Lot notional" value={inr(s.lot_notional)} />
                    <Row
                      label={`Margin / lot (${s.margin_pct}%)`}
                      value={inr(s.margin_per_lot)}
                      tone={s.tradable ? undefined : "loss"}
                    />
                    <Row
                      label={`Lots per ₹${(capital / 1000).toFixed(0)}k`}
                      value={String(s.lots_per_book)}
                      tone={s.tradable ? "gain" : "loss"}
                    />
                    <Row label="Admitted" value={String(s.admitted_strategies)} />
                    <Row label="Open" value={`${s.open_positions} · ${inr(s.margin_deployed)} blocked`} dim />
                    <Row
                      label="Net P&L"
                      value={`${signed(s.net_pnl)} (${s.return_pct >= 0 ? "+" : ""}${num(s.return_pct, 1)}%)`}
                      tone={s.net_pnl >= 0 ? "gain" : "loss"}
                    />
                  </div>

                  {s.afford_note && <div className="s-warn">{s.afford_note}</div>}
                  {!s.enabled && !s.afford_note && (
                    <div className="s-off">Switched off — this contract takes no new positions.</div>
                  )}
                </div>
              ))}
            </div>
            <div className="legend">{scriptsNote}</div>
          </>
        )}
      </GlassPanel>

      {untradable.length > 0 && (
        <div className="warnbar">
          <b>
            {untradable.length} contract{untradable.length === 1 ? "" : "s"} cannot be traded on ₹
            {capital.toLocaleString("en-IN")}:
          </b>{" "}
          {untradable.map((s) => `${s.symbol} (one lot needs ${inr(s.margin_per_lot)} of margin)`).join(", ")}. This
          is a fact about MCX contract sizes at this book size, not a data problem — the mini contracts are the
          version ₹{capital.toLocaleString("en-IN")} can carry. Switching one of these on has no effect: the desk
          refuses to invent a fraction of a lot.
        </div>
      )}

      {/* ── admission ─────────────────────────────────────────────────────────── */}
      <GlassPanel title="Admission" note="which paper strategies earned a seat, and on what evidence">
        <div className="admit">
          <div className="modes">
            <button
              className={`mode ${summary?.admission_mode === "per_script" ? "on" : ""}`}
              onClick={() => act("mode", () => setCommodityPreliveAdmissionMode("per_script"), "Admission: per contract.")}
              disabled={!!busy}
            >
              <div className="m-title">Per contract {summary?.admission_mode === "per_script" && "· active"}</div>
              <div className="m-why">
                A strategy is admitted to a contract only if it cleared the paper desk&rsquo;s gate on{" "}
                <b>that contract&rsquo;s own trades</b>. Since capital here is committed per contract, this is the
                only reading that supports putting money on one. A <b>mini inherits its parent&rsquo;s</b> record
                &mdash; CRUDEOILM and CRUDEOIL are the same commodity at the same quote, so a pattern proved on
                one was proved on the other&rsquo;s price series.
              </div>
              <div className="m-count">
                {summary?.admission_counts?.per_script_total ?? 0} seats across all contracts
              </div>
            </button>
            <button
              className={`mode ${summary?.admission_mode === "blended" ? "on" : ""}`}
              onClick={() => act("mode", () => setCommodityPreliveAdmissionMode("blended"), "Admission: blended.")}
              disabled={!!busy}
            >
              <div className="m-title">Blended {summary?.admission_mode === "blended" && "· active"}</div>
              <div className="m-why">
                The READY badges from the main Commodity Trading page — one verdict per strategy,{" "}
                <b>pooled across all eight contracts</b>. Available for comparison, but it admits strategies to
                contracts they have never proved anything on.
              </div>
              <div className="m-count">
                {summary?.admission_counts?.blended_per_contract ?? 0} strategies × {summary?.script_count ?? 0}{" "}
                contracts = {summary?.admission_counts?.blended_total ?? 0} seats
              </div>
            </button>
          </div>
          <div className="admit-by">
            {scripts.map((s) => (
              <span key={s.symbol} className={`pill ${s.admitted_strategies ? "has" : ""}`}>
                {s.symbol} <b>{s.admitted_strategies}</b>
              </span>
            ))}
          </div>
        </div>
      </GlassPanel>

      <GlassPanel title="Promotion gate" note="re-run here on this desk's own whole-lot trades">
        <div className="gate">
          <Criterion
            label="Closed trades"
            value={`≥ ${gate?.min_trades ?? 30}`}
            why="Below this the record is noise. No verdict is not approval."
          />
          <Criterion label="Net P&L" value="> ₹0" why="After MCX brokerage, CTT, exchange, SEBI, stamp, GST and slippage." />
          <Criterion label="Profit factor" value={`> ${gate?.min_profit_factor ?? 1.2}`} why="Gross profit divided by gross loss." />
          <Criterion label="Expectancy" value="> ₹0" why="Average rupees kept per trade." />
          <Criterion
            label="Win rate"
            value={`≥ ${((gate?.min_win_rate ?? 0.3) * 100).toFixed(0)}%`}
            why="Deliberately low — breakouts win by asymmetry."
          />
          <Criterion
            label="Max drawdown"
            value={`≤ ${gate?.max_drawdown_pct ?? 20}%`}
            why={`Peak-to-trough, against this contract's ${inr(capital)} — not against ₹10L.`}
          />
          <Criterion label="t-statistic" value={`≥ ${gate?.min_t_stat ?? 1.5}`} why="Separates a real edge from a lucky run." />
        </div>
      </GlassPanel>

      {/* ── contract-wise leaderboard ─────────────────────────────────────────── */}
      <GlassPanel
        title="Contract-wise strategy leaderboard"
        note={`${board?.shown ?? 0} of ${board?.total ?? 0} rows · one strategy on one contract`}
      >
        <div className="filters">
          <div className="frow">
            <span className="flabel">Contract</span>
            <button className={`chip ${symbol === "ALL" ? "on" : ""}`} onClick={() => setSymbol("ALL")}>
              All
            </button>
            {(summary?.scripts ?? symbolsWithRows).map((s) => (
              <button key={s} className={`chip ${symbol === s ? "on" : ""}`} onClick={() => setSymbol(s)}>
                {s}
              </button>
            ))}
          </div>
          <div className="frow">
            <span className="flabel">Family</span>
            <button className={`chip ${family === "ALL" ? "on" : ""}`} onClick={() => setFamily("ALL")}>
              All
            </button>
            {FAMILIES.map((f) => (
              <button key={f.key} className={`chip ${family === f.key ? "on" : ""}`} onClick={() => setFamily(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="frow">
            <span className="flabel">Timeframe</span>
            <button className={`chip ${timeframe === "ALL" ? "on" : ""}`} onClick={() => setTimeframe("ALL")}>
              All
            </button>
            {TIMEFRAMES.map((t) => (
              <button key={t} className={`chip ${timeframe === t ? "on" : ""}`} onClick={() => setTimeframe(t)}>
                {t}
              </button>
            ))}
          </div>
          <div className="frow">
            <span className="flabel">Verdict</span>
            {["ALL", "READY", "REJECTED", "PENDING"].map((v) => (
              <button key={v} className={`chip ${verdict === v ? "on" : ""}`} onClick={() => setVerdict(v)}>
                {v}
              </button>
            ))}
          </div>
        </div>

        {!board?.rows?.length ? (
          <EmptyState
            title="Nothing on the board yet"
            note="Rows appear as soon as a strategy is admitted to a contract. Admission comes from the Commodity Trading desk's promotion gate — if nothing has cleared it, nothing trades here."
          />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th>
                  <th className="l">Strategy</th>
                  <th className="l">Family</th>
                  <th>TF</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>Expectancy</th>
                  <th>Max DD</th>
                  <th>t-stat</th>
                  <th>Costs</th>
                  <th>Net P&amp;L</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {board.rows.map((r) => {
                  const key = `${r.symbol}:${r.strategy_id}`;
                  return (
                    <Fragment key={key}>
                      <tr
                        className={`row ${r.verdict.toLowerCase()}`}
                        onClick={() => setExpanded(expanded === key ? null : key)}
                      >
                        <td className="l sym">{r.symbol}</td>
                        <td className="l sname">
                          {r.name}
                          {r.open_positions > 0 && <span className="dot" />}
                        </td>
                        <td className="l">
                          <span className="cat">{r.family_label}</span>
                        </td>
                        <td>{r.timeframe}</td>
                        <td>{r.trades}</td>
                        <td>{r.trades ? `${(r.win_rate * 100).toFixed(0)}%` : "-"}</td>
                        <td>{r.profit_factor === null ? "-" : num(r.profit_factor)}</td>
                        <td className={r.expectancy >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.expectancy) : "-"}</td>
                        <td>{r.trades ? `${num(r.max_drawdown_pct, 1)}%` : "-"}</td>
                        <td>{r.t_stat === null ? "-" : num(r.t_stat)}</td>
                        <td className="dim">{r.total_costs ? inr2(r.total_costs) : "-"}</td>
                        <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.net_pnl) : "-"}</td>
                        <td>
                          <StatusPill label={r.verdict} tone={VERDICT_TONE[r.verdict]} />
                        </td>
                      </tr>
                      {expanded === key && (
                        <tr className="expand">
                          <td colSpan={13}>
                            {r.admitted_because && (
                              <div className="why">
                                <b>Admitted because:</b> {r.admitted_because}
                              </div>
                            )}
                            {!r.still_admitted && (
                              <div className="why loss">
                                No longer admitted under the current rule — it holds its record here but takes no new
                                entries.
                              </div>
                            )}
                            <ul>
                              {r.verdict_reasons.map((x, i) => (
                                <li key={i}>{x}</li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            <div className="legend">{board.note}</div>
          </div>
        )}
      </GlassPanel>

      <GlassPanel
        title={`Open positions (${positions.length})`}
        note="whole MCX lots, marked on live prices, net of the round trip's charges"
      >
        {positions.length > 0 && (
          <div className="toolbar">
            <button
              className="btn sm danger"
              onClick={() => {
                if (!window.confirm(`Square off all ${positions.length} open paper positions now?`)) return;
                act("close-all", () => closeAllCommodityPrelive(), "All open positions squared off.");
              }}
              disabled={!!busy}
            >
              {busy === "close-all" ? "Closing…" : "Square off all"}
            </button>
            <span className="tb-note">Closes every open position at its current mark, on every contract.</span>
          </div>
        )}
        {!positions.length ? (
          <EmptyState
            title="No open positions"
            note="Admitted patterns are evaluated every few minutes while MCX is open (09:00–23:30 IST), on the contracts you have switched on."
          />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th>
                  <th className="l">Strategy</th>
                  <th>TF</th>
                  <th>Side</th>
                  <th>Lots</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>Target</th>
                  <th>Stop</th>
                  <th>Notional</th>
                  <th>Margin</th>
                  <th>Held</th>
                  <th>Unrealised</th>
                  <th>on margin</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.position_id}>
                    <td className="l sym">{p.symbol}</td>
                    <td className="l dim">{p.strategy_name}</td>
                    <td>{p.timeframe}</td>
                    <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                    <td className="sym">{p.lots}</td>
                    <td className="dim">{p.qty.toLocaleString("en-IN")}</td>
                    <td>{inr2(p.entry_price)}</td>
                    <td>{inr2(p.ltp)}</td>
                    <td>{inr2(p.target)}</td>
                    <td>{inr2(p.stoploss)}</td>
                    <td className="dim">{inr(p.notional)}</td>
                    <td>{inr(p.margin_used)}</td>
                    <td className="dim">
                      {p.bars_held}/{p.max_hold_bars}
                    </td>
                    <td className={p.unrealized_pnl >= 0 ? "gain" : "loss"}>{signed(p.unrealized_pnl)}</td>
                    <td className={p.return_on_margin_pct >= 0 ? "gain" : "loss"}>
                      {num(p.return_on_margin_pct, 1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title="Closed trades" note="gross, then what the MCX charges took, then return on the margin blocked">
        {!trades.length ? (
          <EmptyState title="No closed trades yet" note="Every close shows gross P&L, charges, the net kept and what it returned on margin." />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th>
                  <th className="l">Strategy</th>
                  <th>TF</th>
                  <th>Side</th>
                  <th>Lots</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Gross</th>
                  <th>Costs</th>
                  <th>Net</th>
                  <th>on margin</th>
                  <th>Why</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.trade_id}>
                    <td className="l sym">{t.symbol}</td>
                    <td className="l dim">{t.strategy_name}</td>
                    <td>{t.timeframe}</td>
                    <td className={t.side === "BUY" ? "gain" : "loss"}>{t.side}</td>
                    <td className="sym">{t.lots}</td>
                    <td>{inr2(t.entry_price)}</td>
                    <td>{inr2(t.exit_price)}</td>
                    <td className={t.gross_pnl >= 0 ? "gain" : "loss"}>{signed(t.gross_pnl)}</td>
                    <td className="loss">-{inr2(t.costs)}</td>
                    <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{signed(t.realized_pnl)}</td>
                    <td className={t.return_on_margin_pct >= 0 ? "gain" : "loss"}>
                      {num(t.return_on_margin_pct, 1)}%
                    </td>
                    <td>
                      <span className="cat">{t.exit_reason}</span>
                    </td>
                    <td className="dim">
                      {new Date(t.closed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      {summary?.last_notes && summary.last_notes.length > 0 && (
        <GlassPanel title="Last cycle" note={`${summary.last_evaluated?.toLocaleString("en-IN") ?? 0} evaluations`}>
          <ul className="notes">
            {summary.last_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .btn { padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .btn.sm { padding: 5px 11px; font-size: 11.5px; }
        .btn.danger { color: var(--loss); border-color: rgba(217,45,63,.3); }
        .btn:disabled { opacity: 0.55; cursor: default; }
        .notice { border-radius: 12px; padding: 11px 16px; font-size: 12.5px; cursor: pointer;
                  background: var(--purple-dim); border: 1px solid rgba(125,52,220,.24); color: var(--purple); }
        .breaker { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; font-weight: 600;
                   background: var(--loss-dim); border: 1px solid rgba(217,45,63,.24); color: var(--loss); }
        .warnbar { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.5;
                   background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }

        .arm-banner { display: flex; align-items: center; justify-content: space-between; gap: 18px;
                      border-radius: 16px; padding: 18px 22px; border: 1px solid var(--panel-border);
                      background: var(--panel); box-shadow: var(--shadow-sm); }
        .arm-banner.on { border-color: rgba(14,159,110,.35); background: rgba(14,159,110,.06); }
        .arm-banner.off { border-color: rgba(217,45,63,.22); }
        .arm-title { font-size: 15px; font-weight: 800; letter-spacing: .04em; }
        .arm-banner.on .arm-title { color: var(--gain); }
        .arm-banner.off .arm-title { color: var(--loss); }
        .arm-sub { margin-top: 5px; font-size: 12px; color: var(--text-muted); line-height: 1.45; max-width: 76ch; }
        .switch { position: relative; width: 122px; height: 44px; border-radius: 24px; border: none; cursor: pointer;
                  display: flex; align-items: center; transition: background .15s; flex-shrink: 0; padding: 0 5px; }
        .switch.on { background: var(--gain); justify-content: flex-end; }
        .switch.off { background: var(--loss); justify-content: flex-start; }
        .switch:disabled { opacity: .6; cursor: default; }
        .knob { width: 34px; height: 34px; border-radius: 50%; background: #fff; }
        .switch-label { position: absolute; top: 50%; transform: translateY(-50%); color: #fff;
                        font-weight: 800; font-size: 13px; letter-spacing: .05em; }
        .switch.on .switch-label { left: 18px; }
        .switch.off .switch-label { right: 16px; }

        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }

        .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 14px 20px 0; }
        .tb-note { font-size: 11.5px; color: var(--text-faint); line-height: 1.45; }

        .script-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(268px, 1fr));
                       gap: 12px; padding: 16px 20px; }
        .script { border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px;
                  background: var(--canvas-soft); }
        .script.on { border-color: rgba(14,159,110,.34); background: rgba(14,159,110,.05); }
        .script.blocked { opacity: .78; }
        .s-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
        .s-sym { font-size: 13.5px; font-weight: 800; letter-spacing: .02em; }
        .s-contract { font-size: 10.5px; color: var(--text-faint); margin-top: 2px; }
        .mini-switch { position: relative; width: 46px; height: 24px; border-radius: 14px; border: none;
                       cursor: pointer; display: flex; align-items: center; padding: 0 3px; flex-shrink: 0;
                       transition: background .15s; }
        .mini-switch.on { background: var(--gain); justify-content: flex-end; }
        .mini-switch.off { background: var(--text-faint); justify-content: flex-start; }
        .mini-switch:disabled { opacity: .6; cursor: default; }
        .mini-knob { width: 18px; height: 18px; border-radius: 50%; background: #fff; }
        .s-rows { margin-top: 11px; display: flex; flex-direction: column; gap: 3px; }
        .s-warn { margin-top: 10px; font-size: 11px; line-height: 1.45; color: var(--loss);
                  border-top: 1px solid var(--panel-border); padding-top: 8px; }
        .s-off { margin-top: 10px; font-size: 11px; color: var(--text-faint);
                 border-top: 1px solid var(--panel-border); padding-top: 8px; }

        .admit { padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
        .modes { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
        .mode { text-align: left; border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px;
                background: var(--canvas-soft); cursor: pointer; color: var(--text); }
        .mode.on { border-color: rgba(125,52,220,.34); background: var(--purple-dim); }
        .mode:disabled { opacity: .6; cursor: default; }
        .m-title { font-size: 12.5px; font-weight: 800; }
        .mode.on .m-title { color: var(--purple); }
        .m-why { margin-top: 6px; font-size: 11.5px; line-height: 1.5; color: var(--text-muted); }
        .m-count { margin-top: 8px; font-family: var(--font-data); font-size: 11.5px; font-weight: 700;
                   color: var(--text-faint); }
        .admit-by { display: flex; flex-wrap: wrap; gap: 6px; }
        .pill { font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 100px;
                border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-faint); }
        .pill.has { color: var(--gain); border-color: rgba(14,159,110,.28); }

        .gate { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; padding: 16px 20px; }
        .filters { padding: 14px 20px 4px; display: flex; flex-direction: column; gap: 8px; }
        .frow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
        .flabel { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase;
                  color: var(--text-muted); min-width: 66px; }
        .chip { font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 100px; cursor: pointer;
                border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .chip.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }

        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px;
                      font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700;
                         letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted);
                         border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 9px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .row { cursor: pointer; }
        .row:hover { background: var(--canvas-soft); }
        .row.ready { background: rgba(14,159,110,.05); }
        .sname { font-weight: 600; }
        .sym { font-weight: 700; }
        .dim { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .cat { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 6px;
               background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--gain); margin-left: 7px; }
        .expand td { background: var(--canvas-soft); white-space: normal; text-align: left; }
        .expand ul { margin: 6px 0 0; padding-left: 18px; }
        .expand li { font-size: 12px; color: var(--text-muted); margin: 2px 0; }
        .why { font-size: 12px; color: var(--text-muted); }
        .why.loss { color: var(--loss); margin-top: 4px; }
        .legend { padding: 10px 20px 14px; font-size: 11.5px; color: var(--text-faint);
                  white-space: normal; line-height: 1.5; }
        .notes { margin: 0; padding: 14px 20px 16px 38px; }
        .notes li { font-size: 12.5px; color: var(--text-muted); margin: 4px 0; }
      `}</style>
    </div>
  );
}

function Row({ label, value, tone, dim }: { label: string; value: string; tone?: "gain" | "loss"; dim?: boolean }) {
  return (
    <div className="r">
      <span className="r-label">{label}</span>
      <span className={`r-value ${tone ?? ""} ${dim ? "dim" : ""}`}>{value}</span>
      <style jsx>{`
        .r { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
        .r-label { font-size: 11px; color: var(--text-muted); }
        .r-value { font-family: var(--font-data); font-variant-numeric: tabular-nums;
                   font-size: 11.5px; font-weight: 600; text-align: right; }
        .r-value.gain { color: var(--gain); }
        .r-value.loss { color: var(--loss); }
        .r-value.dim { color: var(--text-faint); font-weight: 500; }
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
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
                padding: 14px 16px; box-shadow: var(--shadow-sm); }
        .t-label { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
                   color: var(--text-muted); }
        .t-value { margin-top: 7px; font-family: var(--font-data); font-variant-numeric: tabular-nums;
                   font-size: 21px; font-weight: 600; letter-spacing: -.2px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}

function Criterion({ label, value, why }: { label: string; value: string; why: string }) {
  return (
    <div className="crit">
      <div className="c-head">
        <span className="c-label">{label}</span>
        <span className="c-value">{value}</span>
      </div>
      <div className="c-why">{why}</div>
      <style jsx>{`
        .crit { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; background: var(--canvas-soft); }
        .c-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
        .c-label { font-size: 11.5px; font-weight: 700; }
        .c-value { font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 12px;
                   font-weight: 700; color: var(--purple); }
        .c-why { margin-top: 4px; font-size: 11px; color: var(--text-muted); line-height: 1.35; }
      `}</style>
    </div>
  );
}
