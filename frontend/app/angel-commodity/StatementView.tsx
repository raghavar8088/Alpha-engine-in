"use client";

/*
 * One of Angel's P&L reports: the commodity positions closed over its date range, with Angel's
 * own gross P&L and ACTUAL charges. The report has no trade dates and does not say which side
 * opened a position, so nothing here splits it into days or into longs and shorts.
 */

import GlassPanel from "../../components/GlassPanel";
import type { AcStatement, AcStatementGroup, AcStatementRow } from "../../lib/api";
import { BarList, Tile, inr, num, plainPct, signed, tone } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 2026-10-15 -> 15 Oct 2026 (no time zone involved: the report's dates are plain dates). */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
}

export function periodText(s: { from: string; to: string }): string {
  return `${longDate(s.from)} → ${longDate(s.to)}`;
}

export function contractText(r: AcStatementRow): string {
  const strike = r.strike !== null && r.strike !== undefined ? ` ${Number.isInteger(r.strike) ? r.strike : r.strike.toFixed(2)}` : "";
  return `${r.underlying}${strike} ${r.kind ?? ""}`.trim();
}

const groupLabel = (k: string) => (k === "CE" ? "Calls (CE)" : k === "PE" ? "Puts (PE)" : k === "FUT" ? "Futures" : k);

function Groups({ title, rows, label = (k: string) => k }: { title: string; rows: AcStatementGroup[]; label?: (k: string) => string }) {
  return (
    <div>
      <div className="sv-sub">{title}</div>
      <BarList rows={rows.map((g) => ({ key: g.key, label: label(g.key), value: g.net,
        sub: `${g.positions} position${g.positions === 1 ? "" : "s"} · ${g.wins} won · charges ₹${g.charges.toFixed(2)}` }))} />
      <style jsx>{`.sv-sub { font-size: 11.5px; color: var(--text-muted); font-weight: 600; margin: 4px 0 8px; }`}</style>
    </div>
  );
}

export function StatementTable({ s }: { s: AcStatement }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr><th className="l">Contract</th><th>Expiry</th><th>Qty</th><th>Avg buy</th><th>Avg sell</th><th>Points</th>
            <th>Buy value</th><th>Sell value</th><th>Gross</th><th>Charges</th><th>Net</th></tr>
        </thead>
        <tbody>
          {s.rows.map((r) => (
            <tr key={`${r.scrip}-${r.seq}`}>
              <td className="l"><b>{contractText(r)}</b><div className="small muted">{r.instrument ?? ""}</div></td>
              <td>{longDate(r.expiry)}</td>
              <td>{r.qty.toLocaleString("en-IN")}{r.lots ? <div className="small muted">{r.lots} lot{r.lots === 1 ? "" : "s"}</div> : null}</td>
              <td>{num(r.avg_buy)}</td>
              <td>{num(r.avg_sell)}</td>
              <td className={tone(r.points)}>{r.points > 0 ? "+" : ""}{num(r.points)}</td>
              <td>{inr(r.buy_value, 2)}</td>
              <td>{inr(r.sell_value, 2)}</td>
              <td className={tone(r.gross)}>{signed(r.gross, 2)}</td>
              <td className="loss" title={Object.entries(r.charges).filter(([, v]) => v).map(([k, v]) => `${k} ₹${v.toFixed(2)}`).join(" · ")}>−₹{r.charges_total.toFixed(2)}</td>
              <td className={tone(r.net)}><b>{signed(r.net, 2)}</b></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td className="l"><b>Total</b>{s.totals_source === "angel-summary" ? <div className="small muted">Angel&apos;s own summary line</div> : null}</td>
            <td /><td /><td /><td /><td />
            <td>{inr(s.stats.buy_value, 2)}</td>
            <td>{inr(s.stats.sell_value, 2)}</td>
            <td className={tone(s.gross)}><b>{signed(s.gross, 2)}</b></td>
            <td className="loss"><b>−₹{s.charges_total.toFixed(2)}</b></td>
            <td className={tone(s.net)}><b>{signed(s.net, 2)}</b></td>
          </tr>
        </tfoot>
      </table>
      <style jsx>{`
        .table-scroll { overflow-x: auto; max-height: 520px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 8px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table tfoot td { border-top: 1px solid var(--panel-border); border-bottom: none; }
        .data-table .l { text-align: left; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .small { font-size: 10.5px; }
        .muted { color: var(--text-muted); font-weight: 400; }
      `}</style>
    </div>
  );
}

export function StatementTiles({ s }: { s: AcStatement }) {
  const st = s.stats;
  return (
    <div className="sv-tiles">
      <Tile label="Net P&L (Angel)" value={signed(s.net, 2)} valueClass={tone(s.net)} sub="after Angel's actual charges" />
      <Tile label="Gross P&L" value={signed(s.gross, 2)} valueClass={tone(s.gross)} sub={`sold ${inr(st.sell_value)} · bought ${inr(st.buy_value)}`} />
      <Tile label="Charges (Angel's actual)" value={`−₹${s.charges_total.toFixed(2)}`} valueClass="loss"
        sub={`₹${num(st.charges_per_position)} a position · ${plainPct(st.charges_share_of_gross)} of gross`} />
      <Tile label="Closed positions" value={`${s.positions}`} sub={`${st.wins ?? 0} won · ${st.losses ?? 0} lost · ${plainPct(st.win_rate, 0)} won`} />
      <Tile label="Profit factor" value={num(st.profit_factor)} sub="total won ÷ total lost" />
      <Tile label="Expectancy" value={signed(st.expectancy, 2)} valueClass={tone(st.expectancy)} sub={`a position · median ${signed(st.median, 2)}`} />
      <Tile label="Average win / loss" value={<><span className="gain">{signed(st.avg_win)}</span> / <span className="loss">{signed(st.avg_loss)}</span></>}
        sub={`payoff ${num(st.payoff)} · largest ${signed(st.largest_win)} / ${signed(st.largest_loss)}`} />
      <Tile label="A session, on average" value={signed(st.net_per_session, 2)} valueClass={tone(st.net_per_session)}
        sub={st.sessions ? `net ÷ the ${st.sessions} MCX sessions in the period — no capital in the report, so no ROI` : "MCX calendar does not cover the period"} />
      <style jsx>{`
        .sv-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

/** The whole report: tiles, each position's result, breakdowns and the table. */
export default function StatementView({ s }: { s: AcStatement }) {
  const st = s.stats;
  const sorted = [...s.rows].sort((a, b) => b.net - a.net);
  return (
    <GlassPanel title={`Angel's P&L report · ${periodText(s)}`}
      note={`${s.positions} closed MCX position${s.positions === 1 ? "" : "s"} · Angel's own figures${s.filename ? ` · ${s.filename}` : ""}`}>
      {s.counted === false && s.reason && <div className="warn-box">Not added to the lifetime total: {s.reason}.</div>}
      <StatementTiles s={s} />
      <div className="grid-3">
        <div>
          <div className="sub">Each closed position, net</div>
          <BarList rows={sorted.map((r) => ({ key: `${r.scrip}-${r.seq}`, label: contractText(r), value: r.net,
            sub: `expiry ${longDate(r.expiry)} · ${num(r.avg_buy)} / ${num(r.avg_sell)}` }))} format={(v) => signed(v, 2)} />
        </div>
        {st.by_type && st.by_type.length > 0 && <Groups title="Calls and puts" rows={st.by_type} label={groupLabel} />}
        {st.by_expiry && st.by_expiry.length > 0 && <Groups title="By expiry" rows={st.by_expiry} label={(k) => longDate(k)} />}
        {st.by_underlying && st.by_underlying.length > 1 && <Groups title="By commodity" rows={st.by_underlying} />}
      </div>
      <div className="sub">The positions, as Angel reports them</div>
      <StatementTable s={s} />
      <div className="note">
        Angel&apos;s P&amp;L report lists each position closed between {longDate(s.from)} and {longDate(s.to)}, matched first in,
        first out, with Angel&apos;s actual brokerage, GST, MCX charge, CTT, stamp duty and SEBI fee. It carries <b>no trade
        dates</b>, so this period stands as one block — it is not spread over days and has no ROI (the capital in use is not in
        the report). It also does not say which side opened a position: &ldquo;avg buy&rdquo; and &ldquo;avg sell&rdquo; read the
        same for a long and for a short, so &ldquo;points&rdquo; is simply sell minus buy. Positions still open on {longDate(s.to)} are not
        in it. For each day on its own, import Angel&apos;s <b>Trade History</b> for these dates in the Data tab.
      </div>
      <style jsx>{`
        .grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; margin: 16px 0 6px; }
        .sub { font-size: 11.5px; color: var(--text-muted); font-weight: 600; margin: 14px 0 8px; }
        .grid-3 .sub { margin-top: 4px; }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 10px 2px 0; line-height: 1.6; }
        .note b { color: var(--text); }
        .warn-box { font-size: 12px; padding: 8px 12px; margin-bottom: 12px; border-radius: 8px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--warn); }
      `}</style>
    </GlassPanel>
  );
}
