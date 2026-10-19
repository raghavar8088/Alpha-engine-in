"use client";

import { useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import type { AcAnalytics, AcBreakdownRow, AcSummary } from "../../lib/api";
import { BarList, Tile, downloadCsv, holdText, num, pct, plainPct, signed, tone } from "./ui";

function Breakdown({ title, rows, label = (k: string) => k }: { title: string; rows: AcBreakdownRow[]; label?: (k: string) => string }) {
  return (
    <GlassPanel title={title}>
      <BarList rows={rows.map((r) => ({ key: r.key, label: label(r.key), value: r.net,
        sub: `${r.trades} trade${r.trades === 1 ? "" : "s"} · ${plainPct(r.win_rate, 0)} won · charges ₹${r.charges.toFixed(0)}` }))}
        emptyNote="No completed trades yet." />
    </GlassPanel>
  );
}

const hourLabel = (k: string) => (k === "None" ? "time unknown" : `${k.padStart(2, "0")}:00–${String(Number(k) + 1).padStart(2, "0")}:00`);

export default function TradesTab({ data, analytics }: { data: AcSummary; analytics: AcAnalytics | null }) {
  const [style, setStyle] = useState("all");
  const [und, setUnd] = useState("all");
  const [result, setResult] = useState("all");
  const trips = useMemo(() => analytics?.trips ?? [], [analytics]);
  const shown = useMemo(() => trips.filter((t) => (style === "all" || t.style === style) && (und === "all" || t.underlying === und)
    && (result === "all" || (result === "won" ? t.net > 0 : t.net < 0))), [trips, style, und, result]);
  const styles = useMemo(() => Array.from(new Set(trips.map((t) => t.style))), [trips]);
  const unds = useMemo(() => Array.from(new Set(trips.map((t) => t.underlying))), [trips]);
  const st = analytics?.stats;

  // Today, per contract: Angel's own realised P&L against the round trips closed today
  const today = data.today.date;
  const recon = useMemo(() => {
    const mine: Record<string, number> = {};
    trips.filter((t) => t.exit_date === today).forEach((t) => { mine[t.tradingsymbol] = (mine[t.tradingsymbol] ?? 0) + t.gross; });
    const syms = new Set([...data.today.positions.filter((p) => p.realised).map((p) => p.tradingsymbol), ...Object.keys(mine)]);
    return Array.from(syms).map((s) => {
      const angel = data.today.positions.find((p) => p.tradingsymbol === s)?.realised ?? 0;
      return { symbol: s, angel, mine: mine[s] ?? 0, diff: (mine[s] ?? 0) - angel };
    });
  }, [trips, data, today]);

  if (!analytics) {
    return <GlassPanel title="Trades"><div className="empty">Working out your trades…</div><style jsx>{`.empty { padding: 26px; text-align: center; color: var(--text-faint); font-size: 12.5px; }`}</style></GlassPanel>;
  }

  return (
    <>
      <GlassPanel title="Completed trades" note={`${analytics.trip_count} matched first-in-first-out from Angel's fills`}>
        {st && st.trades ? (
          <div className="tiles">
            <Tile label="Win rate" value={plainPct(st.win_rate)} sub={`${st.wins} won · ${st.losses} lost of ${st.trades}`} />
            <Tile label="Average win / loss" value={<><span className="gain">{signed(st.avg_win)}</span> / <span className="loss">{signed(st.avg_loss)}</span></>}
              sub={`payoff ratio ${num(st.payoff)}`} />
            <Tile label="Profit factor" value={num(st.profit_factor)} sub="total won ÷ total lost" />
            <Tile label="Expectancy" value={signed(st.expectancy)} valueClass={tone(st.expectancy)} sub={`per trade · median ${signed(st.median)}`} />
            <Tile label="Largest win / loss" value={<><span className="gain">{signed(st.largest_win)}</span> / <span className="loss">{signed(st.largest_loss)}</span></>} />
            <Tile label="Holding time" value={holdText(st.avg_hold_minutes)} sub={`median ${holdText(st.median_hold_minutes)} · ${st.overnight_trades} held overnight`} />
            <Tile label="Streaks" value={`${st.current_streak && st.current_streak > 0 ? `${st.current_streak} won` : st.current_streak ? `${-st.current_streak} lost` : "–"}`}
              valueClass={tone(st.current_streak)} sub={`longest: ${st.max_win_streak} won, ${st.max_loss_streak} lost`} />
            <Tile label="Charges vs gross" value={st.charges_share_of_gross !== null && st.charges_share_of_gross !== undefined ? plainPct(st.charges_share_of_gross) : "–"}
              sub={`gross ${signed(st.gross)} · charges −₹${(st.charges ?? 0).toFixed(0)} · net ${signed(st.net)}`} />
          </div>
        ) : <div className="empty">No trade has been closed since the page began recording.</div>}
      </GlassPanel>

      <div className="grid-3">
        <Breakdown title="By style" rows={analytics.by_style} />
        <Breakdown title="By commodity" rows={analytics.by_underlying} />
        <Breakdown title="By entry hour" rows={analytics.by_hour} label={hourLabel} />
        <Breakdown title="By weekday (exit)" rows={analytics.by_weekday} />
        <Breakdown title="By holding time" rows={analytics.by_hold} />
        <Breakdown title="By days to expiry at entry" rows={analytics.by_dte} />
      </div>

      {recon.length > 0 && (
        <GlassPanel title="Today, checked against Angel" note="realised P&L per contract">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">Contract</th><th>Angel realised</th><th>Matched trades (gross)</th><th>Difference</th></tr></thead>
              <tbody>{recon.map((r) => (
                <tr key={r.symbol}>
                  <td className="l">{r.symbol}</td>
                  <td className={tone(r.angel)}>{signed(r.angel, 2)}</td>
                  <td className={tone(r.mine)}>{signed(r.mine, 2)}</td>
                  <td className={Math.abs(r.diff) < 1 ? "gain" : "warn"}>{Math.abs(r.diff) < 1 ? "matches" : signed(r.diff, 2)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="note">
            A difference appears when Angel prices a position carried in from an earlier day off the previous settlement
            while the matched trade uses the carry-forward price Angel reports — the day&apos;s total P&amp;L is Angel&apos;s either way.
          </div>
        </GlassPanel>
      )}

      <GlassPanel title="Every completed trade" note={`${shown.length} shown`}>
        <div className="filters">
          <select value={style} onChange={(e) => setStyle(e.target.value)}><option value="all">All styles</option>{styles.map((s) => <option key={s}>{s}</option>)}</select>
          <select value={und} onChange={(e) => setUnd(e.target.value)}><option value="all">All commodities</option>{unds.map((s) => <option key={s}>{s}</option>)}</select>
          <select value={result} onChange={(e) => setResult(e.target.value)}><option value="all">Won and lost</option><option value="won">Won</option><option value="lost">Lost</option></select>
          <button type="button" className="btn" disabled={!shown.length} onClick={() => downloadCsv("angel-commodity-trades.csv", shown as unknown as Record<string, unknown>[])}>Download CSV</button>
        </div>
        <div className="table-scroll tall">
          <table className="data-table">
            <thead><tr><th>Closed</th><th className="l">Contract</th><th>Style</th><th>Qty (lots)</th><th>Entry → exit</th><th>Held</th>
              <th>Gross</th><th>Charges</th><th>Net</th><th>On premium</th></tr></thead>
            <tbody>{shown.map((t, i) => (
              <tr key={`${t.tradingsymbol}-${t.exit_date}-${t.exit_time}-${i}`}>
                <td className="small">{t.exit_date}<div className="muted">{t.exit_time ?? ""}</div></td>
                <td className="l">{t.tradingsymbol}{t.carried_in ? <div className="small muted">carried in</div> : null}</td>
                <td className="small">{t.style}</td>
                <td>{t.qty.toLocaleString("en-IN")}{t.lots ? ` (${t.lots})` : ""}</td>
                <td>{num(t.entry_avg)} → {num(t.exit_avg)}</td>
                <td className="small">{holdText(t.hold_minutes, t.hold_days)}</td>
                <td className={tone(t.gross)}>{signed(t.gross, 2)}</td>
                <td className="loss">−₹{t.charges.toFixed(2)}</td>
                <td className={tone(t.net)}><b>{signed(t.net, 2)}</b></td>
                <td className={tone(t.return_on_premium)}>{t.return_on_premium !== undefined ? pct(t.return_on_premium, 1) : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </GlassPanel>

      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; }
        .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
        .filters select { font-size: 12px; padding: 6px 8px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .btn { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); cursor: pointer; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .table-scroll { overflow-x: auto; max-height: 420px; overflow-y: auto; }
        .table-scroll.tall { max-height: 620px; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 8px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table .l { text-align: left; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .warn { color: var(--warn); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 8px 2px 0; line-height: 1.55; }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </>
  );
}
