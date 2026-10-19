"use client";

import { useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { type AcAnalytics, type AcFileImportResult, type AcSummary, importAngelCommodityFile } from "../../lib/api";
import { StatementTable, StatementTiles, longDate, periodText } from "./StatementView";
import { Kv, downloadCsv, signed, tone } from "./ui";

// The page's API calls pass through a Vercel function, which refuses request bodies over about
// 4.5 MB; base64 adds a third, so 3 MB of file is the safe ceiling.
const MAX_BYTES = 3 * 1024 * 1024;

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...Array.from(bytes.subarray(i, i + 0x8000)));
  return btoa(bin);
}

export default function DataTab({ data, analytics, onImported }: { data: AcSummary; analytics: AcAnalytics | null; onImported: () => Promise<void> }) {
  const [file, setFile] = useState<{ name: string; b64: string } | null>(null);
  const [preview, setPreview] = useState<AcFileImportResult | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cov = analytics?.coverage;
  const stmts = data.statements ?? [];

  const pick = async (f: File | null) => {
    setPreview(null);
    setMsg(null);
    setFile(null);
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setMsg(`${f.name} is ${(f.size / 1024 / 1024).toFixed(1)} MB — download a shorter date range (up to 3 MB a file) and import the parts one by one.`);
      return;
    }
    setBusy(true);
    try {
      const b64 = toBase64(await f.arrayBuffer());
      setFile({ name: f.name, b64 });
      setPreview(await importAngelCommodityFile(f.name, b64, false));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not read the file");
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await importAngelCommodityFile(file.name, file.b64, true);
      setMsg(r.kind === "pnl-report"
        ? `Added Angel's P&L report for ${periodText(r)}: ${r.positions} closed positions, net ${signed(r.net, 2)}. It is in the Overview, Trades, Daily and Charges tabs.`
        : `Imported ${r.fills} trades across ${r.days.length} day(s).`);
      setPreview(null);
      setFile(null);
      await onImported();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="grid-2">
        <GlassPanel title="What the page holds">
          {cov && cov.days ? (
            <>
              <Kv k="Trading days recorded" v={`${cov.days} (${cov.first} → ${cov.last})`} />
              <Kv k="Captured live from Angel" v={String(cov.live ?? 0)} />
              <Kv k="Imported from Angel's trade history" v={String(cov.imported ?? 0)} />
              <Kv k="Weekdays with no record" v={cov.weekdays_without_a_record?.length ? `${cov.weekdays_without_a_record.length}` : "none"} />
              {cov.weekdays_without_a_record && cov.weekdays_without_a_record.length > 0 && (
                <div className="small muted">
                  {cov.weekdays_without_a_record.join(", ")} — either MCX holidays, days without trading, or days the page did not
                  poll; Angel&apos;s trade history can fill the last kind.
                </div>
              )}
            </>
          ) : <div className="empty">No day recorded yet.</div>}
          {stmts.map((s) => (
            <Kv key={s.id ?? s.from}
              k={<>Angel P&amp;L report · {periodText(s)}<div className="small muted">{s.filename ? `${s.filename} · ` : ""}{s.imported_at ? `imported ${new Date(s.imported_at).toLocaleString("en-IN")}` : ""}{s.counted === false ? ` · not in the totals: ${s.reason}` : " · in the lifetime total"}</div></>}
              v={<>{signed(s.net, 2)}<div className="small muted">{s.positions} closed positions</div></>} vClass={tone(s.net)} />
          ))}
        </GlassPanel>

        <GlassPanel title="Download">
          <div className="dl">
            <button type="button" className="btn" disabled={!data.days.length} onClick={() => downloadCsv("angel-commodity-days.csv", data.days as unknown as Record<string, unknown>[])}>Daily records (CSV)</button>
            <button type="button" className="btn" disabled={!analytics?.trips.length} onClick={() => downloadCsv("angel-commodity-trades.csv", (analytics?.trips ?? []) as unknown as Record<string, unknown>[])}>Completed trades (CSV)</button>
            <button type="button" className="btn" disabled={!stmts.length} onClick={() => downloadCsv("angel-commodity-pnl-report-positions.csv", stmts.flatMap((s) => s.rows.map((r) => ({ period_from: s.from, period_to: s.to, ...r }))) as unknown as Record<string, unknown>[])}>P&amp;L report positions (CSV)</button>
            <button type="button" className="btn" disabled={!data.today.fills.length} onClick={() => downloadCsv(`angel-commodity-fills-${data.today.date}.csv`, data.today.fills as unknown as Record<string, unknown>[])}>Today&apos;s fills (CSV)</button>
            <button type="button" className="btn" disabled={!data.today.positions.length} onClick={() => downloadCsv(`angel-commodity-positions-${data.today.date}.csv`, data.today.positions as unknown as Record<string, unknown>[])}>Today&apos;s positions (CSV)</button>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel title="Older history — import Angel One's reports">
        <div className="note">
          Angel&apos;s API only returns <b>today&apos;s</b> session, so anything older comes from reports you download from Angel One
          (web → <b>Reports</b>) and pick here, as Excel (.xlsx) or CSV. The page works out which report it is and shows a preview first.
        </div>
        <ul className="defs">
          <li><b>P&amp;L report</b> — every position closed over the dates you choose, with Angel&apos;s own P&amp;L and actual charges.
            It has no trade dates, so it is kept as one block for its period: it counts in your lifetime total and its positions are
            listed, but it gives no daily ROI.</li>
          <li><b>Trade History</b> (tradebook) — each trade with its date. Its days are added one by one, with their realised P&amp;L
            (first in, first out per contract) and an estimated capital, so they get a daily ROI. Days already captured live are never
            overwritten, and importing the same file twice adds nothing.</li>
        </ul>
        <label className={`pick ${busy ? "busy" : ""}`}>
          <input type="file" accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={busy} onChange={(e) => { pick(e.target.files?.[0] ?? null); e.target.value = ""; }} />
          {busy ? "Reading…" : "Choose an Angel One report (.xlsx or .csv)"}
        </label>

        {preview && preview.kind === "pnl-report" && (
          <div className="preview">
            <div className="head">
              <b>{preview.filename}</b> is Angel&apos;s <b>P&amp;L report</b> for <b>{periodText(preview)}</b>
              {preview.downloaded ? ` (downloaded ${longDate(preview.downloaded)})` : ""}: {preview.positions} closed MCX
              position{preview.positions === 1 ? "" : "s"}{preview.non_commodity_rows_ignored ? ` — ${preview.non_commodity_rows_ignored} non-MCX row(s) left out` : ""}.
              {preview.totals_source === "angel-summary" ? " Totals are Angel's own summary lines." : ""}
            </div>
            {preview.recorded_days_inside.length > 0 && (
              <div className="warn">
                {preview.recorded_days_inside.length} day(s) inside this period are already recorded one by one
                ({preview.recorded_days_inside.join(", ")}), so the report will be listed but not added to the lifetime total — it has
                no dates to split around them. A report ending the day before those days would be counted.
              </div>
            )}
            {preview.overlaps_reports.length > 0 && (
              <div className="warn">It overlaps a report already imported ({preview.overlaps_reports.join("; ")}); only one of the two counts in the total — the longer period.</div>
            )}
            {preview.replaces_existing && <div className="small muted">A report for exactly these dates is already here; adding this one replaces it.</div>}
            <StatementTiles s={preview} />
            <StatementTable s={preview} />
            <div className="small muted">The client name, id and PAN in the report&apos;s header are not read or stored.</div>
            <div><button type="button" className="btn primary" disabled={busy} onClick={apply}>Add this report</button></div>
          </div>
        )}

        {preview && preview.kind === "trade-history" && (
          <div className="preview">
            <div><b>{file?.name}</b> is a <b>trade history</b>: {preview.rows_read} MCX trades read · {preview.fills} new across {preview.days.length} day(s)
              {preview.days.length ? ` (${preview.days[0]} → ${preview.days[preview.days.length - 1]})` : ""}
              {preview.skipped_live_days.length ? ` · ${preview.skipped_live_days.length} day(s) already captured live, left as they are` : ""}</div>
            <div className="small muted">Columns used: {Object.entries(preview.columns).filter(([, v]) => v).map(([k, v]) => `${k} = "${v}"`).join(" · ")}</div>
            <div><button type="button" className="btn primary" disabled={busy || !preview.fills} onClick={apply}>Import these days</button></div>
          </div>
        )}
        {msg && <div className="note">{msg}</div>}
      </GlassPanel>

      <GlassPanel title="How these numbers are made">
        <ul className="defs">
          <li><b>Trades, orders, positions</b> — Angel One&apos;s API for your account, MCX only, polled every minute while MCX is open. Read-only: nothing here can place or change an order.</li>
          <li><b>P&amp;L</b> — Angel&apos;s own realised + unrealised for the day per contract (a carried position is marked from the previous close, as in the Angel app).</li>
          <li><b>Completed trades</b> — each closing order matched first-in-first-out against the open quantity of the same contract; positions already open when the page began use Angel&apos;s carry-forward price. Charges are each order&apos;s, spread over its fills by value.</li>
          <li><b>Charges</b> — estimated per executed order from Angel&apos;s commodity rate card (options: ₹20, 0.0418% MCX charge, 0.05% CTT on sells, 0.003% stamp on buys, SEBI, 18% GST; futures: the futures card). Checked against the actual charges in Angel&apos;s P&amp;L report when one is imported (Charges tab).</li>
          <li><b>Angel&apos;s P&amp;L report</b> — Angel&apos;s figures exactly as reported: closed positions over a period, gross, actual charges and net. One block per report, with no daily split and no ROI (it has neither dates nor capital).</li>
          <li><b>Capital invested</b> — the highest amount Angel reported in use (margin + premium) during the day; it covers the whole account.</li>
          <li><b>ROI</b> — net P&amp;L ÷ capital invested. <b>Average return %</b> — average daily net ÷ average capital. <b>Month / year</b> — that average over 21 / 250 sessions, simple and compounded; arithmetic, not a forecast.</li>
          <li><b>Greeks</b> — Black-76 on the future each option is written on, at the volatility implied by the option&apos;s last price; theta is per calendar day, vega per volatility point. <b>Margin</b> — Angel&apos;s own margin calculator per position and for the whole basket.</li>
          <li><b>Drawdown</b> — how far cumulative net P&amp;L is below its running peak. <b>Sharpe / Sortino</b> — mean daily ROI over its spread (all days / losing days only) × √250; meaningless on a few days.</li>
        </ul>
      </GlassPanel>
      <style jsx>{`
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .dl { display: flex; flex-wrap: wrap; gap: 8px; }
        .btn { font-size: 12px; font-weight: 600; padding: 7px 12px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .btn.primary { background: var(--accent-hover); border-color: var(--accent-hover); color: #fff; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .note { font-size: 12px; color: var(--text-muted); padding: 8px 2px; line-height: 1.6; }
        .note b { color: var(--text); }
        .pick { display: inline-flex; align-items: center; gap: 10px; margin: 8px 0 4px; padding: 9px 14px; border-radius: 9px; border: 1px dashed var(--panel-border); background: var(--canvas-soft); font-size: 12.5px; font-weight: 600; color: var(--text); cursor: pointer; }
        .pick.busy { opacity: 0.6; cursor: progress; }
        .pick input { max-width: 220px; font-size: 11.5px; }
        .preview { display: flex; flex-direction: column; gap: 12px; padding: 14px 0 4px; font-size: 12.5px; }
        .preview .head { line-height: 1.6; }
        .warn { font-size: 12px; padding: 8px 12px; border-radius: 8px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--warn); line-height: 1.55; }
        .defs { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.7; color: var(--text-muted); }
        .defs b { color: var(--text); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); font-weight: 400; }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </>
  );
}
