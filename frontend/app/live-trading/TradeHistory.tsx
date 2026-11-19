"use client";

// Trade history of the REAL-money Live Trading desk (19 Nov 2026): every closed round trip, newest first.
//
// It reads the desk's positions ledger (status CLOSED), the same rows the Realised P&L tile and the
// "Daily P&L and ROI" table add up, so its totals always agree with them. VOID rows (entries Angel
// rejected, which never became trades) are not listed. Read-only: nothing here can place an order.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { LiveTradingClosedPosition, fetchLiveTradingClosed } from "../../lib/api";

// The ledger only changes when a trade closes or is re-priced to Angel's fills, and both move the
// summary's closed count or realised total, which reload this at once. The timer is only a fallback.
const REFRESH_MS = 60000;
const LIMIT = 1000;        // the endpoint's maximum
const PAGE = 50;

const money = (v: number | null | undefined, dp = 2) =>
  v == null || Number.isNaN(v)
    ? "-"
    : `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined, dp = 2) => (v == null ? "-" : `${v > 0 ? "+" : ""}${money(v, dp)}`);
const tone = (v: number | null | undefined) => (v == null || Math.abs(v) < 0.005 ? "" : v > 0 ? "gain" : "loss");
const px = (v: number | null | undefined) =>
  v == null ? "-" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const IST = "Asia/Kolkata";
const ms = (iso: string | null | undefined) => {
  const t = iso ? new Date(iso).getTime() : NaN;
  return Number.isNaN(t) ? null : t;
};
const clock = (iso: string | null | undefined) => {
  const t = ms(iso);
  return t == null ? "-" : new Date(t).toLocaleTimeString("en-IN", { timeZone: IST, hour12: false });
};
// The IST trading day a trade closed on. `closed_on` is written by the engine; older rows fall back to
// the close timestamp, exactly as the daily table does.
const dayOf = (t: LiveTradingClosedPosition) => {
  if (t.closed_on) return t.closed_on;
  const c = ms(t.closed_at);
  return c == null ? "" : new Date(c).toLocaleDateString("en-CA", { timeZone: IST });
};
const dayLabel = (d: string) => {
  if (!d) return "-";
  const t = new Date(`${d}T12:00:00+05:30`);
  return Number.isNaN(t.getTime())
    ? d
    : t.toLocaleDateString("en-IN", { timeZone: IST, day: "2-digit", month: "short", year: "numeric" });
};
const held = (t: LiveTradingClosedPosition) => {
  const a = ms(t.opened_at), b = ms(t.closed_at);
  if (a == null || b == null || b < a) return "-";
  const m = Math.round((b - a) / 60000);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
};

const REASON: Record<string, string> = {
  target: "Target",
  stoploss: "Stop loss",
  eod: "Session square-off",
  panic: "Panic close-all",
  broker_squared_off: "Angel squared off",
  stale_session_reconciled: "Stale session (estimated)",
};
const PARENT: Record<string, string> = { time: "time exit", stoploss: "stop", target: "target", eod: "square-off" };
function reasonLabel(r: string | null | undefined): string {
  if (!r) return "-";
  const m = /^tournament closed \((.*)\)$/.exec(r);
  if (m) return `Tournament closed · ${PARENT[m[1]] ?? m[1]}`;
  return REASON[r] ?? r.replace(/_/g, " ");
}

function pricing(t: LiveTradingClosedPosition): { label: string; why: string; tone: string } {
  if (t.reconcile_status === "reconciled" || (t.entry_fill_price != null && t.exit_fill_price != null))
    return { label: "Angel fills", why: "Entry and exit are priced at Angel's own fills", tone: "gain" };
  if (t.reconcile_status === "needs_contract_note")
    return { label: "Estimate", why: t.exit_basis || "An estimate until Angel's contract note is imported", tone: "warn" };
  return {
    label: "Provisional",
    why: "Priced at the decision price until the desk reads Angel's trade book (normally within minutes)",
    tone: "muted",
  };
}

const FEE_LABEL: Record<string, string> = {
  brokerage: "Brokerage", stt: "STT", exchange_txn: "Exchange", sebi: "SEBI", ipft: "IPFT",
  stamp_duty: "Stamp duty", gst: "GST", dp_charge: "DP",
};
function feeTitle(t: LiveTradingClosedPosition): string | undefined {
  const fb = t.fee_breakdown;
  if (!fb) return undefined;
  const parts = Object.entries(FEE_LABEL)
    .map(([k, label]) => [label, fb[k]] as const)
    .filter(([, v]) => typeof v === "number" && v > 0)
    .map(([label, v]) => `${label} ${money(v as number)}`);
  const basis = t.charges_basis === "rate_card" ? " (Angel's rate card; the contract note is the final word)" : "";
  return parts.length ? parts.join(" · ") + basis : undefined;
}

const orderIds = (t: LiveTradingClosedPosition) => {
  const x = Array.isArray(t.exit_order_id) ? t.exit_order_id.join(", ") : t.exit_order_id;
  return `${t.entry_order_id || "-"} / ${x || "-"}`;
};

export default function TradeHistory({ closedCount, realized }: { closedCount?: number; realized?: number }) {
  const [rows, setRows] = useState<LiveTradingClosedPosition[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [strategy, setStrategy] = useState("all");
  const [day, setDay] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const r = await fetchLiveTradingClosed(LIMIT);
      if (mine !== seq.current) return;          // a newer read is already on its way
      setRows(r);
      setError(null);
    } catch (e) {
      if (mine !== seq.current) return;
      setError(e instanceof Error ? e.message : "Could not load the trade history");
    }
  }, []);

  // Reload whenever a trade closes or is re-priced (the page's summary moves), and on a slow timer.
  useEffect(() => {
    load();
  }, [load, closedCount, realized]);
  useEffect(() => {
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const refresh = async () => {
    setBusy(true);
    try {
      await load();
    } finally {
      setBusy(false);
    }
  };

  const sorted = useMemo(
    () => [...(rows ?? [])].sort((a, b) => (ms(b.closed_at) ?? 0) - (ms(a.closed_at) ?? 0)),
    [rows],
  );
  const strategies = useMemo(() => {
    const m = new Map<string, { name: string; n: number }>();
    for (const t of sorted) {
      const s = m.get(t.strategy_id) ?? { name: t.strategy_name, n: 0 };
      s.n += 1;
      m.set(t.strategy_id, s);
    }
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
  }, [sorted]);
  const days = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of sorted) m.set(dayOf(t), (m.get(dayOf(t)) ?? 0) + 1);
    return [...m.entries()].filter(([d]) => d).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [sorted]);

  const shown = useMemo(
    () => sorted.filter((t) => (strategy === "all" || t.strategy_id === strategy) && (day === "all" || dayOf(t) === day)),
    [sorted, strategy, day],
  );
  const tot = useMemo(() => {
    let gross = 0, fees = 0, net = 0, wins = 0, notional = 0;
    for (const t of shown) {
      gross += t.gross_pnl ?? 0;
      fees += t.fees ?? 0;
      net += t.realized_pnl ?? 0;
      wins += (t.realized_pnl ?? 0) > 0 ? 1 : 0;
      notional += t.capital_deployed ?? t.entry_price * t.qty;
    }
    return { gross, fees, net, wins, notional, n: shown.length };
  }, [shown]);

  const visible = showAll ? shown : shown.slice(0, PAGE);
  const truncated = rows != null && closedCount != null && closedCount > rows.length;
  const filtered = strategy !== "all" || day !== "all";

  return (
    <GlassPanel
      title={rows == null ? "Trade history" : `Trade history (${sorted.length})`}
      note="Real Angel One round trips · newest first"
      onRefresh={refresh}
      refreshing={busy}
    >
      {error && <p className="err">{rows == null ? error : `Showing the last good read: ${error}`}</p>}
      {rows == null ? (
        !error && <div className="empty">Loading…</div>
      ) : !sorted.length ? (
        <div className="empty">No closed trades yet.</div>
      ) : (
        <>
          <div className="bar">
            <div className="totals">
              <span><b>{tot.n}</b> trade{tot.n === 1 ? "" : "s"}{filtered ? " shown" : ""}</span>
              <span><b>{tot.wins}</b> won ({tot.n ? Math.round((tot.wins / tot.n) * 100) : 0}%)</span>
              <span>Gross <b className={tone(tot.gross)}>{signed(tot.gross)}</b></span>
              <span>Charges <b className="loss">{money(tot.fees)}</b></span>
              <span>Net <b className={tone(tot.net)}>{signed(tot.net)}</b></span>
              <span>
                Avg net / trade <b className={tone(tot.n ? tot.net / tot.n : 0)}>{tot.n ? signed(tot.net / tot.n) : "-"}</b>
              </span>
              <span>
                Net on traded value{" "}
                <b className={tone(tot.net)}>
                  {tot.notional ? `${tot.net >= 0 ? "+" : ""}${((tot.net / tot.notional) * 100).toFixed(2)}%` : "-"}
                </b>
              </span>
            </div>
            <div className="filters">
              <select value={strategy} onChange={(e) => setStrategy(e.target.value)} aria-label="Filter by strategy">
                <option value="all">All strategies</option>
                {strategies.map(([id, s]) => (
                  <option key={id} value={id}>{s.name} ({s.n})</option>
                ))}
              </select>
              <select value={day} onChange={(e) => setDay(e.target.value)} aria-label="Filter by day">
                <option value="all">All days</option>
                {days.map(([d, n]) => (
                  <option key={d} value={d}>{dayLabel(d)} ({n})</option>
                ))}
              </select>
            </div>
          </div>

          {!shown.length ? (
            <div className="empty">No trades match these filters.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Date</th>
                    <th>Entry (IST)</th>
                    <th>Exit (IST)</th>
                    <th>Held</th>
                    <th style={{ textAlign: "left" }}>Strategy</th>
                    <th style={{ textAlign: "left" }}>Symbol</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Entry ₹</th>
                    <th>Exit ₹</th>
                    <th>Value</th>
                    <th>Gross</th>
                    <th>Charges</th>
                    <th>Net</th>
                    <th>Net %</th>
                    <th style={{ textAlign: "left" }}>Exit reason</th>
                    <th>Priced at</th>
                    <th>Orders (entry / exit)</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((t) => {
                    const value = t.capital_deployed ?? t.entry_price * t.qty;
                    const net = t.realized_pnl;
                    const p = pricing(t);
                    return (
                      <tr key={t.position_id}>
                        <td style={{ textAlign: "left" }}>{dayLabel(dayOf(t))}</td>
                        <td>{clock(t.opened_at)}</td>
                        <td>{clock(t.closed_at)}</td>
                        <td className="muted">{held(t)}</td>
                        <td style={{ textAlign: "left" }} className="pstrat">
                          {t.is_anti && <span className="anti">ANTI</span>}{t.strategy_name}
                        </td>
                        <td style={{ textAlign: "left" }} className="sym">{t.symbol}</td>
                        <td><span className={t.side === "BUY" ? "side buy" : "side sell"}>{t.side}</span></td>
                        <td>{t.qty}</td>
                        <td>{px(t.entry_price)}</td>
                        <td>{px(t.exit_price)}</td>
                        <td className="muted">{money(value, 0)}</td>
                        <td className={tone(t.gross_pnl)}>{signed(t.gross_pnl)}</td>
                        <td className="muted" title={feeTitle(t)}>{money(t.fees)}</td>
                        <td className={`strong ${tone(net)}`}>{signed(net)}</td>
                        <td className={tone(net)}>
                          {net != null && value ? `${net >= 0 ? "+" : ""}${((net / value) * 100).toFixed(2)}%` : "-"}
                        </td>
                        <td style={{ textAlign: "left" }} title={t.exit_reason ?? undefined}>{reasonLabel(t.exit_reason)}</td>
                        <td><span className={`basis ${p.tone}`} title={p.why}>{p.label}</span></td>
                        <td className="muted oid">{orderIds(t)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="foot">
            {shown.length > PAGE && (
              <button className="more" onClick={() => setShowAll((v) => !v)}>
                {showAll ? `Show the latest ${PAGE}` : `Show all ${shown.length}`}
              </button>
            )}
            <span className="muted">
              Net is after Angel&apos;s charges (hover a charge for its breakdown).
              {realized != null && !filtered && !truncated && Math.abs(realized - tot.net) < 0.5
                ? " The rows add up to the Realised P&L tile."
                : ""}
              {truncated ? ` Showing the latest ${rows.length} of ${closedCount} closed trades.` : ""}
            </span>
          </div>
        </>
      )}

      <style jsx>{`
        .err { margin: 0 0 10px; padding: 0 12px; font-size: 12px; color: var(--loss); }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); }
        .bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 16px; margin-bottom: 12px; padding: 0 12px; }
        .totals { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 12.5px; color: var(--text-muted); }
        .totals b { color: var(--text); font-variant-numeric: tabular-nums; }
        .totals b.gain { color: var(--gain); }
        .totals b.loss { color: var(--loss); }
        .filters { display: flex; flex-wrap: wrap; gap: 8px; }
        .filters select { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text);
                          padding: 7px 10px; border-radius: 8px; font-size: 12px; font-weight: 600; max-width: 100%; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 9px 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .sym { font-weight: 700; }
        .strong { font-weight: 700; }
        .pstrat { color: var(--text-muted); }
        .anti { font-size: 9px; font-weight: 800; padding: 1px 5px; border-radius: 4px; background: var(--brand-dim); color: var(--brand); margin-right: 6px; }
        .side { font-weight: 800; font-size: 11px; padding: 2px 8px; border-radius: 6px; }
        .side.buy { color: var(--gain); background: var(--gain-dim); }
        .side.sell { color: var(--loss); background: var(--loss-dim); }
        .basis { font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 6px; cursor: help; }
        .basis.gain { color: var(--gain); background: var(--gain-dim); }
        .basis.warn { color: var(--warn); background: var(--warn-dim); }
        .basis.muted { color: var(--text-muted); background: var(--canvas-soft); }
        .oid { font-size: 10.5px; }
        .foot { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 12px; padding: 0 12px; font-size: 11.5px; }
        .more { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
                padding: 7px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .muted { color: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </GlassPanel>
  );
}
