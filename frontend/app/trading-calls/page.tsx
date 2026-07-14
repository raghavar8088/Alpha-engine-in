"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  CallSchedulerStatus,
  CallSegment,
  GenerateCallsResult,
  TradingCall,
  TradingCallPosition,
  TradingCallPositionsSummary,
  closeTradingCall,
  fetchTradingCallPositions,
  fetchTradingCalls,
  generateTradingCalls,
  placeOrder,
} from "../../lib/api";

const SEGMENTS: { id: CallSegment; label: string }[] = [
  { id: "STOCK", label: "Stocks" },
  { id: "FNO", label: "F&O" },
  { id: "COMMODITY", label: "Commodity" },
];

const POSITION_STATUS_LABEL: Record<string, string> = {
  OPEN: "OPEN",
  TARGET_HIT: "TARGET HIT",
  STOPLOSS: "STOPLOSS",
  EXPIRED: "EXPIRED",
  CLOSED: "CLOSED",
};

const POSITION_STATUS_TONE: Record<string, string> = {
  OPEN: "gain",
  TARGET_HIT: "gain",
  STOPLOSS: "loss",
  EXPIRED: "muted",
  CLOSED: "loss",
};

const STATUS_LABEL: Record<string, string> = {
  OPEN: "OPEN",
  PARTIAL_EXIT: "PARTIAL EXIT",
  TARGET_HIT: "TARGET HIT",
  STOPLOSS: "STOPLOSS",
  EXPIRED: "EXPIRED",
  CLOSED: "CLOSED",
};

const STATUS_TONE: Record<string, string> = {
  OPEN: "gain",
  PARTIAL_EXIT: "gain",
  TARGET_HIT: "gain",
  STOPLOSS: "loss",
  EXPIRED: "muted",
  CLOSED: "loss",
};

const LTP_SOURCE_LABEL: Record<string, string> = {
  dhan_quote: "Live Dhan quote",
  last_bar_close: "Last stored bar close (broker offline)",
  model: "Black-Scholes model estimate (no live quote)",
};

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function expiryLabel(iso: string): string {
  const today = new Date();
  const d = new Date(`${iso}T00:00:00`);
  if (
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  )
    return "TODAY";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }).toUpperCase();
}

function pctVs(ltp: number, level: number): string | null {
  if (!ltp) return null;
  const pct = ((level - ltp) / ltp) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function tradeLabel(call: TradingCall): string {
  if (call.segment === "STOCK") return call.horizon === "INTRADAY" ? "Buy intraday" : "Buy positional";
  return call.side === "BUY" ? "Buy" : "Sell";
}

type ViewTab = CallSegment | "POSITIONS";

export default function TradingCallsPage() {
  const [segment, setSegment] = useState<ViewTab>("STOCK");
  const [calls, setCalls] = useState<TradingCall[]>([]);
  const [counts, setCounts] = useState<Record<CallSegment, number>>({ STOCK: 0, FNO: 0, COMMODITY: 0 });
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("live");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [genResult, setGenResult] = useState<GenerateCallsResult | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tradeMsg, setTradeMsg] = useState<string | null>(null);

  const [positions, setPositions] = useState<TradingCallPosition[]>([]);
  const [positionsSummary, setPositionsSummary] = useState<TradingCallPositionsSummary | null>(null);
  const [positionsStatusFilter, setPositionsStatusFilter] = useState("OPEN");
  const [positionsLoading, setPositionsLoading] = useState(true);
  const [scheduler, setScheduler] = useState<CallSchedulerStatus | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchTradingCalls();
      setCalls(data.calls);
      setCounts(data.live_counts);
      setScheduler(data.scheduler ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trading calls");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPositions = useCallback(async () => {
    try {
      const data = await fetchTradingCallPositions();
      setPositions(data.positions);
      setPositionsSummary(data.summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trading call positions");
    } finally {
      setPositionsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    loadPositions();
    const timer = setInterval(() => {
      load();
      loadPositions();
    }, 60_000);
    return () => clearInterval(timer);
  }, [load, loadPositions]);

  // Refetch positions the moment the tab is opened so it never shows a stale or
  // pre-load view — the positions table has its own loading state, independent of
  // the calls list.
  useEffect(() => {
    if (segment === "POSITIONS") loadPositions();
  }, [segment, loadPositions]);

  const generate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    setGenResult(null);
    try {
      const result = await generateTradingCalls();
      setGenResult(result);
      await Promise.all([load(), loadPositions()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Call generation failed");
    } finally {
      setGenerating(false);
    }
  }, [load, loadPositions]);

  const trade = useCallback(async (call: TradingCall) => {
    const inst = call.instrument;
    if (!inst) return;
    const qty = Math.max(inst.lot_size, 1);
    const ok = window.confirm(
      `Place a PAPER ${call.side} order?\n\n${call.display_name} — qty ${qty} (${inst.exchange_segment})\nEntry ref ${inr(call.ltp)} | Target ${inr(call.target)} | SL ${inr(call.stoploss)}`,
    );
    if (!ok) return;
    setTradeMsg(null);
    try {
      const order = await placeOrder({
        security_id: inst.security_id,
        exchange_segment: inst.exchange_segment,
        transaction_type: call.side,
        quantity: qty,
        order_type: "MARKET",
        product_type: call.horizon === "INTRADAY" ? "INTRADAY" : call.segment === "STOCK" ? "CNC" : "MARGIN",
        paper_trading: true,
      });
      setTradeMsg(`Paper order ${order.order_id} filled at ${inr(order.price)} for ${call.display_name}`);
    } catch (e) {
      setTradeMsg(`Order failed: ${e instanceof Error ? e.message : "unknown error"}`);
    }
  }, []);

  const close = useCallback(
    async (call: TradingCall) => {
      if (!window.confirm(`Close the ${call.display_name} call?`)) return;
      try {
        await closeTradingCall(call.call_id);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to close call");
      }
    },
    [load],
  );

  const visible = useMemo(() => {
    if (segment === "POSITIONS") return [];
    const q = search.trim().toUpperCase();
    return calls.filter((c) => {
      if (c.segment !== segment) return false;
      if (statusFilter === "live" && !["OPEN", "PARTIAL_EXIT"].includes(c.status)) return false;
      if (statusFilter !== "live" && statusFilter !== "all" && c.status !== statusFilter) return false;
      if (q && !c.display_name.toUpperCase().includes(q) && !c.symbol.toUpperCase().includes(q)) return false;
      return true;
    });
  }, [calls, segment, statusFilter, search]);

  const visiblePositions = useMemo(() => {
    const q = search.trim().toUpperCase();
    return positions.filter((p) => {
      if (positionsStatusFilter !== "all" && p.status !== positionsStatusFilter) return false;
      if (q && !p.display_name.toUpperCase().includes(q) && !p.symbol.toUpperCase().includes(q)) return false;
      return true;
    });
  }, [positions, positionsStatusFilter, search]);

  const segmentNote = segment === "POSITIONS" ? undefined : genResult?.notes?.[segment];

  return (
    <div className="page">
      <PageHeader
        crumb="Trading Calls"
        title="Trading Calls"
        subtitle="System-generated research calls with live target/stoploss tracking. Stock calls come from a daily technical scan of locally backfilled symbols; F&O option calls are emitted only when the qualified strategies of the latest Buying-Lab sweep agree on a direction; every price is labeled with its source (live quote, stored close, or model). Not investment advice — validate before trading real money."
      />

      <div className="tabs-row">
        <div className="tabs">
          {SEGMENTS.map((s) => (
            <button key={s.id} className={segment === s.id ? "tab active" : "tab"} onClick={() => setSegment(s.id)}>
              {s.label}
              <span className="count">{counts[s.id] ?? 0}</span>
            </button>
          ))}
          <button
            className={segment === "POSITIONS" ? "tab active" : "tab"}
            onClick={() => setSegment("POSITIONS")}
          >
            Trading Call Positions
            <span className="count">{positionsSummary?.open_positions ?? 0}</span>
          </button>
        </div>
        <div className="toolbar">
          <input placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
          {segment === "POSITIONS" ? (
            <select value={positionsStatusFilter} onChange={(e) => setPositionsStatusFilter(e.target.value)}>
              <option value="OPEN">Open</option>
              <option value="all">All statuses</option>
              <option value="TARGET_HIT">Target hit</option>
              <option value="STOPLOSS">Stoploss</option>
              <option value="EXPIRED">Expired</option>
              <option value="CLOSED">Closed</option>
            </select>
          ) : (
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="live">Live (open + partial exit)</option>
              <option value="all">All statuses</option>
              <option value="OPEN">Open</option>
              <option value="PARTIAL_EXIT">Partial exit</option>
              <option value="TARGET_HIT">Target hit</option>
              <option value="STOPLOSS">Stoploss</option>
              <option value="EXPIRED">Expired</option>
              <option value="CLOSED">Closed</option>
            </select>
          )}
          <button className="generate" onClick={generate} disabled={generating}>
            {generating ? "Scanning…" : "Generate calls"}
          </button>
        </div>
      </div>

      {scheduler?.enabled && (
        <div className="sched-line">
          <span className="sched-dot" />
          Auto-scan every 2h on trading days ({scheduler.slots.join(" · ")} IST)
          {scheduler.last_slot
            ? ` · last run ${scheduler.last_slot}${scheduler.last_created !== null ? ` (${scheduler.last_created} new call${scheduler.last_created === 1 ? "" : "s"})` : ""}`
            : " · no runs yet"}
          {scheduler.next_slot ? ` · next ${scheduler.next_slot}` : ""}
        </div>
      )}
      {error && <ErrorBanner message={error} />}
      {tradeMsg && <div className="notice">{tradeMsg}</div>}
      {genResult && (
        <div className="notice">
          Scan complete: {genResult.created} new call{genResult.created === 1 ? "" : "s"} ({genResult.scanned} candidates
          {genResult.created < genResult.scanned ? ", duplicates skipped" : ""}).
          {genResult.positions_opened > 0 && ` ${genResult.positions_opened} paper position${genResult.positions_opened === 1 ? "" : "s"} opened.`}
          {!genResult.broker_connected && " Broker offline — prices are stored closes / model estimates."}
        </div>
      )}
      {segmentNote && <div className="notice warn">{segmentNote}</div>}

      {segment === "POSITIONS" ? (
        <>
          {positionsSummary && (
            <div className="capital-tiles">
              <div className="tile">
                <span className="label">Initial capital</span>
                <span className="value">{inr(positionsSummary.initial_capital)}</span>
              </div>
              <div className="tile">
                <span className="label">Equity</span>
                <span className={`value ${positionsSummary.equity >= positionsSummary.initial_capital ? "gain" : "loss"}`}>
                  {inr(positionsSummary.equity)}
                </span>
              </div>
              <div className="tile">
                <span className="label">Deployed capital</span>
                <span className="value">{inr(positionsSummary.deployed_capital)}</span>
              </div>
              <div className="tile">
                <span className="label">Available cash</span>
                <span className="value">{inr(positionsSummary.available_cash)}</span>
              </div>
              <div className="tile">
                <span className="label">Unrealized P&amp;L</span>
                <span className={`value ${positionsSummary.unrealized_pnl >= 0 ? "gain" : "loss"}`}>
                  {inr(positionsSummary.unrealized_pnl)}
                </span>
              </div>
              <div className="tile">
                <span className="label">Realized P&amp;L</span>
                <span className={`value ${positionsSummary.realized_pnl >= 0 ? "gain" : "loss"}`}>
                  {inr(positionsSummary.realized_pnl)}
                </span>
              </div>
            </div>
          )}
          <GlassPanel title="Trading Call Positions">
            {positionsLoading && positions.length === 0 ? (
              <div className="empty">Loading…</div>
            ) : visiblePositions.length === 0 ? (
              <div className="empty">
                No {positionsStatusFilter === "OPEN" ? "open " : ""}positions yet — positions open automatically the moment a
                trading call is generated.
              </div>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Name</th>
                      <th>Entry</th>
                      <th>Qty</th>
                      <th>Capital deployed</th>
                      <th>LTP</th>
                      <th>Target</th>
                      <th>Stoploss</th>
                      <th>P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePositions.map((pos) => {
                      const live = pos.status === "OPEN";
                      const pnl = live ? pos.unrealized_pnl : pos.realized_pnl ?? 0;
                      return (
                        <tr key={pos.position_id}>
                          <td style={{ textAlign: "left" }}>
                            <div className="name-cell">
                              <div className="name-line">
                                <span className="name">{pos.display_name}</span>
                                <span className={`chip horizon ${pos.horizon.toLowerCase()}`}>{pos.horizon}</span>
                              </div>
                              <span className={`status ${POSITION_STATUS_TONE[pos.status] ?? ""}`}>
                                {POSITION_STATUS_LABEL[pos.status]}
                              </span>
                            </div>
                          </td>
                          <td>{inr(pos.entry_price)}</td>
                          <td>
                            {pos.qty}
                            {pos.lot_size > 1 ? ` (${pos.lots} lot${pos.lots === 1 ? "" : "s"})` : ""}
                          </td>
                          <td>{inr(pos.capital_deployed)}</td>
                          <td>
                            {inr(pos.ltp)}
                            {pos.ltp_source !== "dhan_quote" && (
                              <span className="src-star" title={LTP_SOURCE_LABEL[pos.ltp_source]}>*</span>
                            )}
                          </td>
                          <td>{inr(pos.target)}</td>
                          <td>{inr(pos.stoploss)}</td>
                          <td className={pnl >= 0 ? "gain" : "loss"}>{inr(pnl)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <div className="footnote">
              Every position is opened automatically the instant its trading call is generated, sized off a shared{" "}
              {inr(positionsSummary?.initial_capital ?? 10000000)} paper capital pool ({(0.02 * 100).toFixed(0)}% of capital
              per trade). Target/stoploss are copied directly from the call — positions close the moment their call hits
              target, stoploss, or expires. Paper only, no live orders.
            </div>
          </GlassPanel>
        </>
      ) : (
      <GlassPanel title={`${SEGMENTS.find((s) => s.id === segment)?.label} calls`}>
        {loading ? (
          <div className="empty">Loading…</div>
        ) : visible.length === 0 ? (
          <div className="empty">
            No {statusFilter === "live" ? "live " : ""}calls in this segment yet — hit <b>Generate calls</b> to run the scan.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Name</th>
                  <th>Call expiry date</th>
                  <th>LTP</th>
                  <th>Target</th>
                  <th>Stoploss</th>
                  <th>Details</th>
                  <th>Trade call</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((call) => {
                  const live = call.status === "OPEN" || call.status === "PARTIAL_EXIT";
                  const targetPct = live ? pctVs(call.ltp, call.target) : null;
                  const stopPct = live ? pctVs(call.ltp, call.stoploss) : null;
                  const isOpen = expanded === call.call_id;
                  return (
                    <Fragment key={call.call_id}>
                      <tr>
                        <td style={{ textAlign: "left" }}>
                          <div className="name-cell">
                            <div className="name-line">
                              <span className="name">{call.symbol}</span>
                              {call.tags.map((t) => (
                                <span key={t} className="chip">
                                  {t.match(/^\d{4}-\d{2}-\d{2}$/) ? expiryLabel(t) : t}
                                </span>
                              ))}
                              <span className={`chip horizon ${call.horizon.toLowerCase()}`}>{call.horizon}</span>
                            </div>
                            <span className={`status ${STATUS_TONE[call.status] ?? ""}`}>{STATUS_LABEL[call.status]}</span>
                          </div>
                        </td>
                        <td>{expiryLabel(call.call_expiry_date)}</td>
                        <td>
                          {inr(call.ltp)}
                          {call.ltp_source !== "dhan_quote" && <span className="src-star" title={LTP_SOURCE_LABEL[call.ltp_source]}>*</span>}
                        </td>
                        <td>
                          {inr(call.target)} {targetPct && <span className="gain pct">{targetPct}</span>}
                        </td>
                        <td>
                          {inr(call.stoploss)} {stopPct && <span className="loss pct">{stopPct}</span>}
                        </td>
                        <td>
                          <button className="info-btn" title="Why this call?" onClick={() => setExpanded(isOpen ? null : call.call_id)}>
                            i
                          </button>
                        </td>
                        <td>
                          <button
                            className={`trade-btn ${call.side === "SELL" ? "sell" : "buy"}`}
                            disabled={!live || !call.instrument}
                            onClick={() => trade(call)}
                          >
                            {tradeLabel(call)}
                          </button>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="details-row">
                          <td colSpan={7}>
                            <div className="details">
                              <p className="rationale">{call.rationale}</p>
                              <div className="facts">
                                <span>Source: {call.source.name ?? call.source.kind}{call.source.kind === "qualified_sweep" ? " (qualified Buying-Lab strategy consensus)" : ""}</span>
                                <span>Confidence: {(call.confidence * 100).toFixed(0)}%</span>
                                <span>Entry: {inr(call.entry_price)}</span>
                                <span>P&amp;L: {call.pnl_pct === null ? "-" : `${call.pnl_pct >= 0 ? "+" : ""}${call.pnl_pct.toFixed(2)}%`}</span>
                                <span>Price source: {LTP_SOURCE_LABEL[call.ltp_source]}</span>
                                {call.data_as_of && <span>Signal data as of: {call.data_as_of}</span>}
                                {call.instrument && <span>Lot/qty: {call.instrument.lot_size}</span>}
                                <span>Generated: {call.generated_on}</span>
                              </div>
                              {live && (
                                <button className="close-call" onClick={() => close(call)}>
                                  Close this call
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="footnote">
          * price is not a live quote — hover the asterisk for the source. Statuses roll automatically: 60% of the way
          to target books a PARTIAL EXIT and trails the stoploss to entry; target/stoploss/expiry close the call. Trade
          buttons place <b>paper</b> orders via the broker route.
        </div>
      </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .tabs-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .tabs { display: flex; gap: 8px; }
        .tab {
          display: flex; align-items: center; gap: 7px;
          background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
          padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
        }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .count { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; }
        .tab.active .count { background: var(--purple); color: #fff; border-color: transparent; }
        .toolbar { display: flex; gap: 10px; align-items: center; }
        .sched-line { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--text-muted); padding: 0 2px; }
        .sched-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--gain); flex-shrink: 0; }
        .capital-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .capital-tiles .tile { display: flex; flex-direction: column; gap: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; }
        .capital-tiles .label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .capital-tiles .value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .capital-tiles .value.gain { color: var(--gain); }
        .capital-tiles .value.loss { color: var(--loss); }
        input, select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13px; min-width: 120px; }
        .generate { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13px; border: none; border-radius: 10px; padding: 10px 18px; cursor: pointer; }
        .generate:disabled { opacity: 0.55; cursor: default; }
        .notice { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12.5px; }
        .notice.warn { border-color: rgba(217, 160, 45, 0.4); color: var(--text-muted); }
        .empty { padding: 28px 20px; font-size: 13px; color: var(--text-muted); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); background: var(--panel); position: sticky; top: 0; }
        .data-table td { padding: 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .name-cell { display: flex; flex-direction: column; gap: 4px; }
        .name-line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .name { font-weight: 700; font-size: 13px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700; color: var(--text-muted); }
        .chip.horizon.intraday { color: var(--accent); }
        .chip.horizon.positional { color: var(--purple); }
        .status { font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em; }
        .status.gain { color: var(--gain); }
        .status.loss { color: var(--loss); }
        .status.muted { color: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .pct { font-size: 11px; margin-left: 4px; }
        .src-star { color: var(--accent); margin-left: 2px; cursor: help; }
        .info-btn { width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--panel-border); background: var(--canvas-soft); color: var(--text-muted); font-weight: 700; font-style: italic; cursor: pointer; }
        .trade-btn { border: none; border-radius: 18px; padding: 9px 20px; font-size: 12.5px; font-weight: 700; cursor: pointer; color: #fff; background: linear-gradient(145deg, #1d4f91, #163d72); }
        .trade-btn.sell { background: linear-gradient(145deg, #e2622b, #c94f1d); }
        .trade-btn:disabled { opacity: 0.45; cursor: default; }
        .details-row td { background: var(--canvas-soft); text-align: left; }
        .details { display: flex; flex-direction: column; gap: 8px; padding: 4px 6px; }
        .rationale { margin: 0; font-size: 12.5px; line-height: 1.55; }
        .facts { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 11px; color: var(--text-muted); }
        .close-call { align-self: flex-start; background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); border-radius: 8px; padding: 6px 12px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
        .footnote { padding: 10px 20px 16px; font-size: 11px; color: var(--text-faint); line-height: 1.5; }
        @media (max-width: 900px) { .tabs-row { flex-direction: column; align-items: stretch; } .toolbar { flex-wrap: wrap; } }
      `}</style>
    </div>
  );
}
