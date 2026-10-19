"use client";

import { useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { type AcAnalytics, type AcImportResult, type AcSummary, importAngelCommodity } from "../../lib/api";
import { Kv, downloadCsv } from "./ui";

export default function DataTab({ data, analytics, onImported }: { data: AcSummary; analytics: AcAnalytics | null; onImported: () => Promise<void> }) {
  const [csvText, setCsvText] = useState<string | null>(null);
  const [csvName, setCsvName] = useState("");
  const [preview, setPreview] = useState<AcImportResult | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const cov = analytics?.coverage;

  const pick = async (f: File | null) => {
    setPreview(null);
    setMsg(null);
    if (!f) return;
    setCsvName(f.name);
    const text = await f.text();
    setCsvText(text);
    try {
      setPreview(await importAngelCommodity(text, false));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not read the file");
    }
  };
  const apply = async () => {
    if (!csvText) return;
    try {
      const r = await importAngelCommodity(csvText, true);
      setMsg(`Imported ${r.fills} trades across ${r.days.length} day(s).`);
      setPreview(null);
      setCsvText(null);
      await onImported();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Import failed");
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
          ) : <div className="empty">Nothing recorded yet.</div>}
        </GlassPanel>

        <GlassPanel title="Download">
          <div className="dl">
            <button type="button" className="btn" disabled={!data.days.length} onClick={() => downloadCsv("angel-commodity-days.csv", data.days as unknown as Record<string, unknown>[])}>Daily records (CSV)</button>
            <button type="button" className="btn" disabled={!analytics?.trips.length} onClick={() => downloadCsv("angel-commodity-trades.csv", (analytics?.trips ?? []) as unknown as Record<string, unknown>[])}>Completed trades (CSV)</button>
            <button type="button" className="btn" disabled={!data.today.fills.length} onClick={() => downloadCsv(`angel-commodity-fills-${data.today.date}.csv`, data.today.fills as unknown as Record<string, unknown>[])}>Today&apos;s fills (CSV)</button>
            <button type="button" className="btn" disabled={!data.today.positions.length} onClick={() => downloadCsv(`angel-commodity-positions-${data.today.date}.csv`, data.today.positions as unknown as Record<string, unknown>[])}>Today&apos;s positions (CSV)</button>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel title="Older days — import Angel's trade history">
        <div className="note">
          Angel&apos;s API only returns <b>today&apos;s</b> session, so days before this page started are imported from Angel&apos;s
          own record: Angel One web → <b>Reports → Trade History</b>, choose the dates, download as <b>CSV</b>, and pick the file
          here. You see a preview first. Those days&apos; P&amp;L is the realised P&amp;L of trades closed that day (first in, first
          out per contract) and their capital is estimated. Days already captured live are never overwritten, and importing the
          same file twice adds nothing.
        </div>
        <input type="file" accept=".csv,text/csv" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
        {preview && (
          <div className="preview">
            <div><b>{csvName}</b>: {preview.rows_read} MCX trades read · {preview.fills} new across {preview.days.length} day(s)
              {preview.days.length ? ` (${preview.days[0]} → ${preview.days[preview.days.length - 1]})` : ""}
              {preview.skipped_live_days.length ? ` · ${preview.skipped_live_days.length} day(s) already captured live, left as they are` : ""}</div>
            <div className="small muted">Columns used: {Object.entries(preview.columns).filter(([, v]) => v).map(([k, v]) => `${k} = "${v}"`).join(" · ")}</div>
            <button type="button" className="btn" disabled={!preview.fills} onClick={apply}>Import these days</button>
          </div>
        )}
        {msg && <div className="note">{msg}</div>}
      </GlassPanel>

      <GlassPanel title="How these numbers are made">
        <ul className="defs">
          <li><b>Trades, orders, positions</b> — Angel One&apos;s API for your account, MCX only, polled every minute while MCX is open. Read-only: nothing here can place or change an order.</li>
          <li><b>P&amp;L</b> — Angel&apos;s own realised + unrealised for the day per contract (a carried position is marked from the previous close, as in the Angel app).</li>
          <li><b>Completed trades</b> — each closing order matched first-in-first-out against the open quantity of the same contract; positions already open when the page began use Angel&apos;s carry-forward price. Charges are each order&apos;s, spread over its fills by value.</li>
          <li><b>Charges</b> — estimated per executed order from Angel&apos;s commodity rate card (options: ₹20, 0.0418% MCX charge, 0.05% CTT on sells, 0.003% stamp on buys, SEBI, 18% GST; futures: the futures card).</li>
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
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .note { font-size: 12px; color: var(--text-muted); padding: 8px 2px; line-height: 1.6; }
        .note b { color: var(--text); }
        .preview { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; font-size: 12.5px; }
        .defs { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.7; color: var(--text-muted); }
        .defs b { color: var(--text); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </>
  );
}
