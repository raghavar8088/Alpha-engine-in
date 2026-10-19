"use client";

import { useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import Histogram from "../../components/charts/Histogram";
import LineChart from "../../components/charts/LineChart";
import MonthlyHeatmap from "../../components/charts/MonthlyHeatmap";
import { type AcAnalytics, type AcDay, type AcDayDetail, type AcSummary, fetchAngelCommodityDay } from "../../lib/api";
import { CalendarHeat, Tile, holdText, inr, num, pct, signed, tone } from "./ui";

function dayPnl(d: AcDay): number | undefined {
  return d.basis === "angel-api" ? d.gross_pnl : d.realised_fifo;
}

function DayDetail({ day, onClose }: { day: string; onClose: () => void }) {
  const [d, setD] = useState<AcDayDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setD(null);
    setErr(null);
    fetchAngelCommodityDay(day).then((r) => { if (alive) setD(r); }).catch((e) => { if (alive) setErr(e instanceof Error ? e.message : "failed"); });
    return () => { alive = false; };
  }, [day]);
  const dd = d?.day;
  return (
    <GlassPanel title={`${day} in full`}>
      <button type="button" className="close" onClick={onClose}>Close ✕</button>
      {err && <div className="empty">{err}</div>}
      {!d && !err && <div className="empty">Loading {day}…</div>}
      {d && dd && dd.found !== false && (
        <>
          <div className="tiles">
            <Tile label="P&L" value={signed(dayPnl(dd), 2)} valueClass={tone(dayPnl(dd))} sub={dd.basis === "angel-api" ? "Angel's own" : "realised (imported)"} />
            <Tile label="Charges" value={`−₹${(dd.charges ?? 0).toFixed(2)}`} valueClass="loss" sub={`${dd.orders ?? 0} orders`} />
            <Tile label="Net" value={signed(dd.net_pnl, 2)} valueClass={tone(dd.net_pnl)} />
            <Tile label="Capital invested" value={inr(dd.capital)} sub={dd.capital_source === "angel-rms" ? "Angel, peak in use" : "estimated"} />
            <Tile label="ROI" value={pct(dd.roi)} valueClass={tone(dd.roi)} />
            <Tile label="Trades closed" value={String(d.trips.length)} sub={`${d.fills.length} fills`} />
          </div>
          {d.points.length > 1 && (
            <div className="charts">
              <div className="chart-title">P&amp;L through the day</div>
              <LineChart points={d.points.map((p) => ({ ts: p.slot, value: Math.round(p.gross_pnl) }))} height={140} fillToZero formatValue={(v) => signed(v)} />
            </div>
          )}
          {dd.positions && dd.positions.length > 0 && (
            <>
              <div className="sub-title">Positions at the last poll</div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th className="l">Contract</th><th>Net qty</th><th>Bought</th><th>Sold</th><th>LTP</th><th>Realised</th><th>Unrealised</th><th>P&amp;L</th></tr></thead>
                  <tbody>{dd.positions.map((p) => (
                    <tr key={p.tradingsymbol + p.product}>
                      <td className="l">{p.tradingsymbol}</td><td>{p.netqty}</td>
                      <td>{p.buyqty ? `${p.buyqty} @ ${num(p.buyavg)}` : "–"}</td><td>{p.sellqty ? `${p.sellqty} @ ${num(p.sellavg)}` : "–"}</td>
                      <td>{num(p.ltp)}</td><td className={tone(p.realised)}>{signed(p.realised, 2)}</td>
                      <td className={tone(p.unrealised)}>{signed(p.unrealised, 2)}</td><td className={tone(p.pnl)}><b>{signed(p.pnl, 2)}</b></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </>
          )}
          {d.trips.length > 0 && (
            <>
              <div className="sub-title">Trades closed this day</div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th className="l">Contract</th><th>Style</th><th>Qty</th><th>Entry → exit</th><th>Held</th><th>Net</th></tr></thead>
                  <tbody>{d.trips.map((t, i) => (
                    <tr key={`${t.tradingsymbol}-${i}`}>
                      <td className="l">{t.tradingsymbol}</td><td className="small">{t.style}</td><td>{t.qty}</td>
                      <td>{num(t.entry_avg)} → {num(t.exit_avg)}</td><td className="small">{holdText(t.hold_minutes, t.hold_days)}</td>
                      <td className={tone(t.net)}><b>{signed(t.net, 2)}</b></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </>
          )}
          <div className="sub-title">Fills and what each order cost</div>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Time</th><th className="l">Contract</th><th>Side</th><th>Qty</th><th>Price</th><th>Value</th><th>Order</th></tr></thead>
              <tbody>{d.fills.map((f) => (
                <tr key={`${f.orderid}-${f.fillid}`}>
                  <td>{f.time}</td><td className="l">{f.tradingsymbol}</td><td className={f.side === "BUY" ? "gain" : "loss"}>{f.side}</td>
                  <td>{f.qty}</td><td>{num(f.price)}</td><td>{inr(f.value, 2)}</td><td className="small muted">{f.orderid}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {d.order_charges.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th className="l">Order</th><th>Turnover</th><th>Brokerage</th><th>MCX</th><th>CTT</th><th>Stamp</th><th>SEBI</th><th>GST</th><th>Total</th></tr></thead>
                <tbody>{d.order_charges.map((o) => (
                  <tr key={o.order}>
                    <td className="l small">{o.order}</td><td>{inr(o.turnover, 2)}</td>
                    {["brokerage", "exchange", "ctt", "stamp", "sebi", "gst"].map((k) => <td key={k}>{num(o.breakdown?.[k] ?? 0)}</td>)}
                    <td className="loss"><b>{num(o.charges)}</b></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </>
      )}
      <style jsx>{`
        .close { float: right; font-size: 12px; padding: 4px 10px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; clear: both; padding-top: 8px; }
        .charts { margin-top: 12px; }
        .chart-title, .sub-title { font-size: 11.5px; color: var(--text-muted); margin: 12px 0 4px; font-weight: 600; }
        .table-scroll { overflow-x: auto; max-height: 360px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 7px; font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 6px 7px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table .l { text-align: left; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </GlassPanel>
  );
}

export default function DailyTab({ data, analytics }: { data: AcSummary; analytics: AcAnalytics | null }) {
  const [picked, setPicked] = useState<string | null>(null);
  const days = useMemo(() => data.days ?? [], [data]);
  const cum = useMemo(() => {
    const m: Record<string, number> = {};
    let c = 0;
    [...days].reverse().forEach((d) => { c += d.net_pnl ?? 0; m[d.date] = c; });
    return m;
  }, [days]);
  const perf = analytics?.performance;
  const periods = analytics?.periods;
  return (
    <>
      {picked && <DayDetail day={picked} onClose={() => setPicked(null)} />}

      <GlassPanel title="Calendar" note="net P&L per day — click a day in the table below for the full day">
        <CalendarHeat days={days.map((d) => ({ date: d.date, net: d.net_pnl ?? 0, roi: d.roi }))} />
      </GlassPanel>

      <div className="grid-2">
        <GlassPanel title="Monthly ROI" note="net ÷ the month's average capital, %">
          {periods && periods.heatmap.length ? <MonthlyHeatmap data={periods.heatmap} /> : <div className="empty">No months yet.</div>}
        </GlassPanel>
        <GlassPanel title="How daily ROI is spread" note={perf?.days ? `${perf.days} day(s), %` : undefined}>
          {perf?.histogram && perf.histogram.length ? <Histogram buckets={perf.histogram} /> : <div className="empty">Needs a few days.</div>}
        </GlassPanel>
      </div>

      <GlassPanel title="Day by day" note="click a row for the day in full">
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Date</th><th>Trades</th><th>Turnover</th><th>Capital invested</th><th>P&amp;L</th><th>Charges</th><th>Net P&amp;L</th><th>ROI</th><th>Cumulative</th></tr></thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date} className={`click ${picked === d.date ? "on" : ""}`} onClick={() => setPicked(d.date)}>
                  <td><b>{d.date}</b></td>
                  <td>{d.fills ?? 0}</td>
                  <td>{inr(d.turnover)}</td>
                  <td>{inr(d.capital)}<div className="small muted">{d.capital_source === "angel-rms" ? "Angel, peak" : "estimated"}</div></td>
                  <td className={tone(dayPnl(d))}>{signed(dayPnl(d), 2)}</td>
                  <td className="loss">{d.charges ? `−₹${d.charges.toFixed(2)}` : "–"}</td>
                  <td className={tone(d.net_pnl)}><b>{signed(d.net_pnl, 2)}</b></td>
                  <td className={tone(d.roi)}>{pct(d.roi)}</td>
                  <td className={tone(cum[d.date])}>{signed(cum[d.date])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <div className="grid-2">
        <GlassPanel title="Weeks">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Week</th><th>Days</th><th>Net</th><th>Avg capital</th><th>ROI</th><th>Green</th></tr></thead>
              <tbody>{(periods?.weeks ?? []).map((w) => (
                <tr key={w.period}><td>{w.period}</td><td>{w.days}</td><td className={tone(w.net)}>{signed(w.net)}</td>
                  <td>{inr(w.avg_capital)}</td><td className={tone(w.roi)}>{pct(w.roi)}</td><td>{w.green_days}/{w.days}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </GlassPanel>
        <GlassPanel title="Months">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Month</th><th>Days</th><th>Net</th><th>Charges</th><th>Avg capital</th><th>ROI</th><th>Best / worst day</th></tr></thead>
              <tbody>{(periods?.months ?? []).map((m) => (
                <tr key={m.period}><td>{m.period}</td><td>{m.days}</td><td className={tone(m.net)}>{signed(m.net)}</td>
                  <td className="loss">−₹{m.charges.toFixed(0)}</td><td>{inr(m.avg_capital)}</td><td className={tone(m.roi)}>{pct(m.roi)}</td>
                  <td className="small"><span className="gain">{signed(m.best)}</span> / <span className="loss">{signed(m.worst)}</span></td></tr>
              ))}</tbody>
            </table>
          </div>
        </GlassPanel>
      </div>

      <style jsx>{`
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .table-scroll { overflow-x: auto; max-height: 480px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 8px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .click { cursor: pointer; }
        .click:hover td, .click.on td { background: var(--canvas-soft); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </>
  );
}
