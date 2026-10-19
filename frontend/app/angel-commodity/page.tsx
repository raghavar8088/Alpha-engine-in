"use client";

/*
 * Angel One Commodity Live Trading Data — the owner's REAL Angel One MCX account, read-only.
 * Trades, orders and positions come from Angel's API (today's session; the backend keeps each
 * day), P&L is Angel's own, charges follow Angel's published commodity rate card, and the
 * capital each day is the peak of what Angel reported in use (margin + premium). Older days
 * come from Angel's trade-history download. Nothing on this page can place an order.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  type AcDay,
  type AcImportResult,
  type AcSummary,
  fetchAngelCommodity,
  importAngelCommodity,
  refreshing,
  syncAngelCommodity,
} from "../../lib/api";

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "–" : `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "–" : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "–" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp })}%`;
const tone = (v: number | null | undefined) => (v === null || v === undefined ? "" : v >= 0 ? "gain" : "loss");
const qtyText = (q: number, lot: number | null | undefined) =>
  lot ? `${q.toLocaleString("en-IN")} (${(q / lot).toLocaleString("en-IN", { maximumFractionDigits: 2 })} lot)` : q.toLocaleString("en-IN");

function dayPnl(d: AcDay): number | undefined {
  return d.basis === "angel-api" ? d.gross_pnl : d.realised_fifo;
}

export default function AngelCommodityPage() {
  const [data, setData] = useState<AcSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [csvText, setCsvText] = useState<string | null>(null);
  const [csvName, setCsvName] = useState<string>("");
  const [preview, setPreview] = useState<AcImportResult | null>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [showOrders, setShowOrders] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await fetchAngelCommodity());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the Angel One commodity data");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, [load]);

  const handleRefresh = useCallback(async () => {
    setBusy(true);
    try { await refreshing(() => load()); } finally { setBusy(false); }
  }, [load]);

  const syncNow = async () => {
    setSyncMsg("Asking Angel One…");
    try {
      const r = await syncAngelCommodity();
      setSyncMsg(r.skipped ? String(r.skipped) : `Synced: ${r.fills ?? 0} trades, ${r.positions ?? 0} positions today`);
      await refreshing(() => load());
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    }
  };

  const pickFile = async (f: File | null) => {
    setPreview(null);
    setImportMsg(null);
    if (!f) return;
    setCsvName(f.name);
    const text = await f.text();
    setCsvText(text);
    try {
      setPreview(await importAngelCommodity(text, false));
    } catch (e) {
      setImportMsg(e instanceof Error ? e.message : "Could not read the file");
    }
  };

  const applyImport = async () => {
    if (!csvText) return;
    try {
      const r = await importAngelCommodity(csvText, true);
      setImportMsg(`Imported ${r.fills} trades across ${r.days.length} day(s).`);
      setPreview(null);
      setCsvText(null);
      await refreshing(() => load());
    } catch (e) {
      setImportMsg(e instanceof Error ? e.message : "Import failed");
    }
  };

  const st = data?.status;
  const today = data?.today;
  const td = today?.day ?? null;
  const av = data?.averages;
  const pj = av?.projection;
  const days = useMemo(() => data?.days ?? [], [data]);
  const curve = useMemo(() => {
    let cum = 0;
    return [...days].reverse().filter((d) => d.net_pnl !== undefined).map((d) => {
      cum += d.net_pnl;
      return { ts: d.date, value: Math.round(cum) };
    });
  }, [days]);
  const cumByDate = useMemo(() => {
    const m: Record<string, number> = {};
    curve.forEach((p) => { m[p.ts] = p.value; });
    return m;
  }, [curve]);

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={busy}
        crumb="Angel One Commodity Live Trading Data"
        title="Angel One Commodity Live Trading Data"
        subtitle="Your REAL Angel One MCX account: every trade, Angel's own P&L, and the return on the capital you had in use each day — with the averages and what they come to over a month and a year. Read-only: this page can never place an order."
      />

      {error && <ErrorBanner message={error} />}

      <div className="strip">
        <span className="pill real">REAL ACCOUNT · READ-ONLY</span>
        <span className={`pill ${st?.angel_ok === false ? "bad" : st?.angel_ok ? "ok" : ""}`}>
          {st?.angel_ok === false ? `Angel One error: ${st.last_error ?? ""}` : st?.angel_ok ? "Angel One connected" : "Angel One — not polled yet"}
        </span>
        <span className="pill">{st?.window_open ? "MCX window open — polled every minute" : "MCX window closed (Mon–Fri 08:45–23:59)"}</span>
        {st && !st.switch_on && <span className="pill bad">switched off in Main Control</span>}
        <span className="muted small">{st?.last_sync ? `last sync ${new Date(st.last_sync).toLocaleTimeString()}` : ""}</span>
        <button type="button" className="btn" onClick={syncNow} disabled={!st?.window_open}>Sync now</button>
        {syncMsg && <span className="muted small">{syncMsg}</span>}
      </div>

      <GlassPanel title={`Today · ${today?.date ?? ""}`}>
        <div className="tiles">
          <div className="tile"><div className="tile-label">Angel P&amp;L (gross)</div>
            <div className={`tile-value ${tone(td?.gross_pnl)}`}>{signed(td?.gross_pnl, 2)}</div>
            <div className="tile-sub">realised + unrealised, as the Angel app shows</div></div>
          <div className="tile"><div className="tile-label">Charges (estimated)</div>
            <div className="tile-value loss">{td ? `−₹${(td.charges ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "–"}</div>
            <div className="tile-sub">{td?.orders ?? 0} orders · Angel&apos;s commodity rate card</div></div>
          <div className="tile"><div className="tile-label">Net P&amp;L</div>
            <div className={`tile-value ${tone(td?.net_pnl)}`}>{signed(td?.net_pnl, 2)}</div>
            <div className="tile-sub">after charges</div></div>
          <div className="tile"><div className="tile-label">Capital invested today</div>
            <div className="tile-value">{inr(td?.capital)}</div>
            <div className="tile-sub">peak in use (Angel) · now {inr(td?.capital_now)}</div></div>
          <div className="tile"><div className="tile-label">ROI today</div>
            <div className={`tile-value ${tone(td?.roi)}`}>{pct(td?.roi)}</div>
            <div className="tile-sub">net P&amp;L ÷ capital invested</div></div>
          <div className="tile"><div className="tile-label">Trades</div>
            <div className="tile-value">{today?.fills.length ?? 0}</div>
            <div className="tile-sub">{td ? `turnover ${inr(td.turnover)}` : "none yet today"}</div></div>
        </div>
      </GlassPanel>

      <GlassPanel title="Averages and what they come to" note={av?.days ? `over ${av.days} trading day(s), ${av.first} → ${av.last}` : undefined}>
        {av && av.days ? (
          <>
            <div className="tiles">
              <div className="tile"><div className="tile-label">Average capital invested</div>
                <div className="tile-value">{inr(av.avg_capital)}</div><div className="tile-sub">a day</div></div>
              <div className="tile"><div className="tile-label">Average net return</div>
                <div className={`tile-value ${tone(av.avg_net_pnl)}`}>{signed(av.avg_net_pnl)}</div><div className="tile-sub">a day, after charges</div></div>
              <div className="tile"><div className="tile-label">Average return %</div>
                <div className={`tile-value ${tone(av.avg_return_pct)}`}>{pct(av.avg_return_pct, 3)}</div>
                <div className="tile-sub">a day = average return ÷ average capital{av.mean_daily_roi !== null && av.mean_daily_roi !== undefined ? ` (mean of daily ROIs ${pct(av.mean_daily_roi, 3)})` : ""}</div></div>
              <div className="tile"><div className="tile-label">One month ({pj?.sessions_month} sessions)</div>
                <div className={`tile-value ${tone(pj?.month_rupees)}`}>{signed(pj?.month_rupees)}</div>
                <div className="tile-sub">{pct(pj?.month_pct_simple)} simple · {pct(pj?.month_pct_compound)} compounded</div></div>
              <div className="tile"><div className="tile-label">One year ({pj?.sessions_year} sessions)</div>
                <div className={`tile-value ${tone(pj?.year_rupees)}`}>{signed(pj?.year_rupees)}</div>
                <div className="tile-sub">{pct(pj?.year_pct_simple)} simple · {pj?.year_pct_compound === null ? "too large to state" : `${pct(pj?.year_pct_compound)} compounded`}</div></div>
              <div className="tile"><div className="tile-label">Record so far</div>
                <div className={`tile-value ${tone(av.total_net_pnl)}`}>{signed(av.total_net_pnl)}</div>
                <div className="tile-sub">{av.green_days} of {av.days} days positive · charges {inr(av.total_charges)}</div></div>
            </div>
            <div className="note">
              The month and year figures repeat the past average: <b>{signed(av.avg_net_pnl)}</b> a day × the sessions
              (simple), or <b>{pct(av.avg_return_pct, 3)}</b> a day compounded on itself. They are arithmetic, not a forecast
              — they rest on {av.days} day(s){av.t_stat !== null && av.t_stat !== undefined ? `, and the daily results so far give t = ${av.t_stat}` : ""}
              {av.days < 20 ? " — far too few for the average to mean much yet." : "."} Best day {signed(av.best_day)}, worst {signed(av.worst_day)}.
            </div>
          </>
        ) : <div className="empty">No trading days recorded yet. Days are kept from the first sync; import Angel&apos;s trade history below for older days.</div>}
      </GlassPanel>

      <GlassPanel title="Day by day" note="P&L, charges and ROI on the capital in use that day">
        {curve.length > 1 && (
          <LineChart points={curve} height={170} fillToZero formatValue={(v) => signed(v)} />
        )}
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Date</th><th>Trades</th><th>Turnover</th><th>Capital invested</th><th>P&amp;L</th><th>Charges</th><th>Net P&amp;L</th><th>ROI</th><th>Cumulative</th></tr></thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date}>
                  <td>{d.date}</td>
                  <td>{d.fills ?? 0}</td>
                  <td>{inr(d.turnover)}</td>
                  <td>{inr(d.capital)}<div className="small muted">{d.capital_source === "angel-rms" ? "Angel, peak in use" : "estimated"}</div></td>
                  <td className={tone(dayPnl(d))}>{signed(dayPnl(d), 2)}<div className="small muted">{d.basis === "angel-api" ? "Angel P&L" : "realised (imported)"}</div></td>
                  <td className="loss">{d.charges ? `−₹${d.charges.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "–"}</td>
                  <td className={tone(d.net_pnl)}><b>{signed(d.net_pnl, 2)}</b></td>
                  <td className={tone(d.roi)}>{pct(d.roi)}</td>
                  <td className={tone(cumByDate[d.date])}>{signed(cumByDate[d.date])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Today's positions (from Angel)">
        {today && today.positions.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">Contract</th><th>Product</th><th>Net qty</th><th>Bought</th><th>Sold</th><th>LTP</th><th>Realised</th><th>Unrealised</th><th>P&amp;L</th></tr></thead>
              <tbody>{today.positions.map((p) => (
                <tr key={`${p.tradingsymbol}-${p.product}`}>
                  <td className="l">{p.tradingsymbol}</td><td className="small">{p.product}</td>
                  <td className={p.netqty > 0 ? "gain" : p.netqty < 0 ? "loss" : ""}>{qtyText(p.netqty, p.lot_units)}</td>
                  <td>{p.buyqty ? `${p.buyqty} @ ${p.buyavg.toFixed(2)}` : "–"}</td>
                  <td>{p.sellqty ? `${p.sellqty} @ ${p.sellavg.toFixed(2)}` : "–"}</td>
                  <td>{p.ltp.toFixed(2)}</td>
                  <td className={tone(p.realised)}>{signed(p.realised, 2)}</td>
                  <td className={tone(p.unrealised)}>{signed(p.unrealised, 2)}</td>
                  <td className={tone(p.pnl)}><b>{signed(p.pnl, 2)}</b></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div className="empty">No MCX positions today.</div>}
      </GlassPanel>

      <GlassPanel title="Today's trades (from Angel)" note={today?.orders.length ? `${today.orders.length} orders` : undefined}>
        {today && today.fills.length ? (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Time</th><th className="l">Contract</th><th>Side</th><th>Qty</th><th>Price</th><th>Value</th><th>Product</th><th>Order</th></tr></thead>
              <tbody>{today.fills.map((f) => (
                <tr key={`${f.orderid}-${f.fillid}`}>
                  <td>{f.time}</td><td className="l">{f.tradingsymbol}</td>
                  <td className={f.side === "BUY" ? "gain" : "loss"}>{f.side}</td>
                  <td>{qtyText(f.qty, f.lot_units)}</td><td>{f.price.toFixed(2)}</td><td>{inr(f.value, 2)}</td>
                  <td className="small">{f.product}</td><td className="small muted">{f.orderid}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div className="empty">No MCX trades today.</div>}
        {today && today.orders.length > 0 && (
          <>
            <button type="button" className="btn link" onClick={() => setShowOrders((v) => !v)}>{showOrders ? "Hide" : "Show"} today&apos;s orders</button>
            {showOrders && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Time</th><th className="l">Contract</th><th>Side</th><th>Qty</th><th>Filled</th><th>Price</th><th>Status</th><th className="l">Note</th></tr></thead>
                  <tbody>{today.orders.map((o) => (
                    <tr key={o.orderid}>
                      <td className="small">{o.time}</td><td className="l">{o.tradingsymbol}</td><td>{o.side}</td>
                      <td>{o.qty}</td><td>{o.filled}</td><td>{(o.avg_price || o.price).toFixed(2)}</td>
                      <td>{o.status}</td><td className="l small muted">{o.text}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </GlassPanel>

      <GlassPanel title="Older days — import Angel's trade history">
        <div className="note">
          Angel&apos;s API only returns <b>today&apos;s</b> session, so days before this page started are imported from Angel&apos;s
          own record: Angel One web → <b>Reports → Trade History</b>, choose the dates, download as <b>CSV</b>, and pick the
          file here. You see a preview first. Those days&apos; P&amp;L is the realised P&amp;L of trades closed that day (first in,
          first out per contract) and their capital is estimated (premium paid for bought options, Angel&apos;s measured margin
          rates for sold options and futures). Days already captured live are never overwritten.
        </div>
        <input type="file" accept=".csv,text/csv" onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
        {preview && (
          <div className="preview">
            <div><b>{csvName}</b>: {preview.rows_read} MCX trades read · {preview.fills} new across {preview.days.length} day(s)
              {preview.days.length ? ` (${preview.days[0]} → ${preview.days[preview.days.length - 1]})` : ""}
              {preview.skipped_live_days.length ? ` · ${preview.skipped_live_days.length} day(s) already captured live, left as they are` : ""}</div>
            <div className="small muted">Columns used: {Object.entries(preview.columns).filter(([, v]) => v).map(([k, v]) => `${k} = "${v}"`).join(" · ")}</div>
            <button type="button" className="btn" disabled={!preview.fills} onClick={applyImport}>Import these days</button>
          </div>
        )}
        {importMsg && <div className="note">{importMsg}</div>}
      </GlassPanel>

      <GlassPanel title="How these numbers are made">
        <ul className="defs">
          <li><b>Trades, orders, positions</b> — Angel One&apos;s API for your account, MCX only, polled every minute while MCX is open. Nothing else in the account is touched or shown.</li>
          <li><b>P&amp;L</b> — Angel&apos;s own realised + unrealised for the day per contract, as in the Angel app (a carried position is marked from the previous close).</li>
          <li><b>Charges</b> — estimated per executed order from Angel&apos;s commodity rate card (options: ₹20, 0.0418% MCX charge, 0.05% CTT on sells, 0.003% stamp on buys, SEBI, 18% GST; futures: the futures card). Your contract note is the final word.</li>
          <li><b>Capital invested</b> — the highest amount Angel reported as in use (margin + premium, &ldquo;utilised&rdquo;) during the day. It covers the whole account, so anything else held in the same account counts too.</li>
          <li><b>ROI</b> — net P&amp;L ÷ capital invested that day. <b>Average return %</b> — average daily net P&amp;L ÷ average capital invested.</li>
        </ul>
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .strip { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .pill { font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 999px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .pill.real { background: var(--loss-dim); color: var(--loss); }
        .pill.ok { background: var(--gain-dim); color: var(--gain); }
        .pill.bad { background: var(--loss-dim); color: var(--loss); }
        .btn { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn.link { margin-top: 10px; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .tile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 6px; font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .tile-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); line-height: 1.4; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .muted { color: var(--text-muted); }
        .small { font-size: 11px; }
        .note { font-size: 12px; color: var(--text-muted); padding: 10px 2px; line-height: 1.6; }
        .note b { color: var(--text); }
        .empty { padding: 24px 20px; text-align: center; color: var(--text-faint); font-size: 13px; }
        .table-scroll { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table .l { text-align: left; }
        .preview { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; font-size: 12.5px; }
        .defs { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.7; color: var(--text-muted); }
        .defs b { color: var(--text); }
      `}</style>
    </div>
  );
}
