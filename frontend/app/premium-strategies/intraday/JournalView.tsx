"use client";

import { useState } from "react";
import GlassPanel from "../../../components/GlassPanel";
import { API, num, pct, share, tone, useDesk } from "./desk";

const KINDS: [string, string][] = [
  ["", "Everything"], ["entry,portfolio_entry", "Entries"], ["rejected,portfolio_rejected,portfolio_skip", "Refused"],
  ["setup_end", "Missed / cancelled / expired"], ["exit", "Exits"], ["setup,plan,checkpoint", "Plan and checkpoints"],
];
const KIND_LABEL: Record<string, string> = {
  entry: "Entered (observation book)", portfolio_entry: "Entered (portfolio)", rejected: "Refused by the book",
  portfolio_rejected: "Refused by the portfolio", portfolio_skip: "Not for the portfolio", setup_end: "Setup ended",
  exit: "Exit", setup: "Setup planned", plan: "Plan published", checkpoint: "Checkpoint",
};

function Knew({ k }: { k: any }) {
  if (!k || !Object.keys(k).length) return <p className="pis-small pis-muted">No snapshot stored for this row.</p>;
  const tb = k.trigger_bar || {};
  return (
    <dl className="pis-dl">
      {k.plan && (<><dt>The plan (09:45)</dt><dd>{k.plan.reason} · trigger {k.plan.trigger?.type?.replace("_", " ")}
        {k.plan.trigger?.level != null ? ` ${num(k.plan.trigger.level)}` : ""} · entry range {k.plan.entry_range?.[0] != null ? `${num(k.plan.entry_range[0])}–${num(k.plan.entry_range[1])}` : "near VWAP"}
        {" "}· window {k.plan.window?.join("–")} · target {k.plan.target_R}R</dd></>)}
      {k.market_0945 && (<><dt>Market at 09:45</dt><dd>{k.market_0945.condition} · NIFTY {pct(k.market_0945.nifty_ret_open)} since the open ·
        {" "}{share(k.market_0945.up_open)} of stocks above their open · coverage {share(k.market_0945.coverage)}</dd></>)}
      {k.market_now && (<><dt>Market at the trigger</dt><dd>{k.market_now.condition} · NIFTY {pct(k.market_now.nifty_ret_open)}</dd></>)}
      {k.sector_0945 && k.sector_0945.rank != null && (<><dt>Sector at 09:45</dt><dd>rank {k.sector_0945.rank} · {k.sector_0945.why}</dd></>)}
      {k.sector_now && k.sector_now.rank != null && (<><dt>Sector at the trigger</dt><dd>rank {k.sector_now.rank} · {pct(k.sector_now.rel)} vs NIFTY ·
        {" "}{share(k.sector_now.up_open)} above their open{k.sector_now.narrow ? " · NARROW" : ""}</dd></>)}
      {tb.start && (<><dt>Trigger bar</dt><dd>{tb.start} bar: O {num(tb.o)} H {num(tb.h)} L {num(tb.l)} C {num(tb.c)} · volume {Number(tb.v).toLocaleString("en-IN")}
        {tb.arrived ? ` · received ${new Date(tb.arrived * 1000).toLocaleTimeString("en-IN")}` : ""} · VWAP {num(k.vwap)}</dd></>)}
      {k.ledger && (<><dt>Source signal (tournament ledger)</dt><dd>{JSON.stringify(k.ledger)}</dd></>)}
    </dl>
  );
}

export default function JournalView() {
  const [d, setD] = useState("");
  const [kind, setKind] = useState("");
  const [sym, setSym] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = `${API}/journal?limit=1000${d ? `&d=${d}` : ""}${kind ? `&kind=${kind}` : ""}${sym ? `&symbol=${encodeURIComponent(sym.toUpperCase())}` : ""}`;
  const { data, error, reload, loading } = useDesk<any>(q, 60_000);
  const { data: days } = useDesk<any>(`${API}/days?limit=60`, 300_000);
  const rows = data?.rows || [];
  const jsel = rows.find((r: any) => r.id === open);
  return (
    <div className="pis-col">
      <GlassPanel title="Trade journal" onRefresh={reload} refreshing={loading}
        note="every entry, refusal, missed setup and exit, with what the desk knew at that moment">
        <div className="pis-filters">
          <select value={d} onChange={(e) => setD(e.target.value)}>
            <option value="">All days</option>
            {(days?.days || []).map((x: any) => <option key={x._id} value={x._id}>{x._id}</option>)}
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}</select>
          <input placeholder="Stock" value={sym} onChange={(e) => setSym(e.target.value)} />
        </div>
        {error && <p className="pis-err">{error}</p>}
        {!rows.length && !error && <div className="pis-empty">Nothing recorded yet for this filter.</div>}
        {rows.length > 0 && (
          <div className="pis-scroll">
            <table className="pis-table">
              <thead><tr><th>Day</th><th>Time</th><th>What</th><th>Strategy · book</th><th>Stock</th><th>Side</th><th>Decision and reason</th><th className="r">Price / qty</th><th className="r">Net</th></tr></thead>
              <tbody>{rows.map((r: any) => (
                  <tr key={r.id} className={`${r.knew ? "pis-click" : ""}${open === r.id ? " pis-sel" : ""}`} onClick={() => r.knew && setOpen(open === r.id ? null : r.id)}>
                    <td className="pis-small">{r.day}</td><td>{r.t}</td>
                    <td className="pis-small">{KIND_LABEL[r.kind] || r.kind}{r.status ? `: ${r.status}` : ""}{r.stage ? ` ${r.stage}` : ""}</td>
                    <td className="pis-small">{r.strategy ? `${r.strategy} ${r.level || ""} ${r.variant || ""}` : ""}{r.book && r.book !== r.strategy ? <div className="pis-muted">{r.book}</div> : null}</td>
                    <td className="pis-strong">{r.symbol || ""}</td>
                    <td className={r.side === "LONG" ? "pis-up" : r.side === "SHORT" ? "pis-down" : ""}>{r.side || ""}</td>
                    <td className="pis-small pis-wrap">{r.why || r.reason || r.note || (r.summary ? JSON.stringify(r.summary) : "") || (r.no_trade || []).join("; ")}
                      {r.knew ? <span className="pis-link"> · what we knew</span> : null}</td>
                    <td className="r pis-small">{r.price != null ? num(r.price) : r.ref != null ? num(r.ref) : ""}{r.qty ? ` × ${r.qty}` : ""}</td>
                    <td className={`r ${tone(r.net)}`}>{r.net != null ? num(r.net, 0) : ""}{r.failed ? <span className="pis-pill pis-pill-bad">failed exit</span> : null}</td>
                  </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        {jsel && (
          <div className="pis-selbox">
            <div className="pis-selbox-head"><b>What the desk knew: {jsel.day} {jsel.t} · {jsel.strategy} {jsel.symbol} {jsel.side}</b>
              <button className="pis-btn" onClick={() => setOpen(null)}>Close</button></div>
            <p className="pis-small">{jsel.why || jsel.kind}{jsel.note ? ` · ${jsel.note}` : ""}</p>
            <Knew k={jsel.knew} />
          </div>
        )}
      </GlassPanel>
    </div>
  );
}
