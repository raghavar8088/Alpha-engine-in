"use client";

import GlassPanel from "../../components/GlassPanel";
import LineChart from "../../components/charts/LineChart";
import type { AcAnalytics, AcSummary } from "../../lib/api";
import { longDate } from "./StatementView";
import { BarList, Kv, Tile, holdText, inr, num, pct, plainPct, signed, tone } from "./ui";

const FUNDS: [string, string][] = [
  ["net", "Account value (net)"],
  ["availablecash", "Available cash"],
  ["utiliseddebits", "In use (margin + premium)"],
  ["m2mrealized", "M2M realised"],
  ["m2munrealized", "M2M unrealised"],
  ["collateral", "Collateral"],
  ["availablelimitmargin", "Available limit margin"],
  ["availableintradaypayin", "Intraday pay-in"],
  ["utilisedpayout", "Payout utilised"],
];
const COMP_LABEL: Record<string, string> = {
  brokerage: "Brokerage", gst: "GST", exchange: "MCX charge", ctt: "CTT", stamp: "Stamp duty", sebi: "SEBI fee",
};

export default function OverviewTab({ data, analytics }: { data: AcSummary; analytics: AcAnalytics | null }) {
  const today = data.today;
  const td = today.day;
  const av = data.averages;
  const pj = av.projection;
  const funds = td?.funds ?? {};
  const used = funds.utiliseddebits ?? td?.capital_now ?? 0;
  const free = funds.availablecash ?? td?.available_cash ?? 0;
  const util = used + free > 0 ? used / (used + free) : null;
  const perf = analytics?.performance;
  const st = analytics?.stats;
  const pnlCurve = today.points.map((p) => ({ ts: p.slot, value: Math.round(p.gross_pnl) }));
  const capCurve = today.points.map((p) => ({ ts: p.slot, value: Math.round(p.capital) }));
  const breakdown = Object.entries(td?.charges_breakdown ?? {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const openNow = today.positions.filter((p) => p.netqty).length;
  const life = data.lifetime;
  const stmts = data.statements ?? [];
  const counted = stmts.filter((s) => s.counted !== false);
  const lastReport = counted[0];
  const dayFirst = data.days.length ? data.days[data.days.length - 1].date : null;
  const dayLast = data.days.length ? data.days[0].date : null;

  return (
    <>
      <GlassPanel title={`Today · ${today.date}`}>
        <div className="tiles">
          <Tile label="Angel P&L (gross)" value={signed(td?.gross_pnl, 2)} valueClass={tone(td?.gross_pnl)}
            sub={td ? `realised ${signed(td.realised, 0)} · unrealised ${signed(td.unrealised, 0)}` : "as the Angel app shows"} />
          <Tile label="Charges (estimated)" value={td ? `−₹${(td.charges ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "–"} valueClass="loss"
            sub={breakdown.length ? breakdown.slice(0, 3).map(([k, v]) => `${COMP_LABEL[k] ?? k} ₹${v.toFixed(0)}`).join(" · ") : `${td?.orders ?? 0} orders`} />
          <Tile label="Net P&L" value={signed(td?.net_pnl, 2)} valueClass={tone(td?.net_pnl)} sub="after charges" />
          <Tile label="Capital invested" value={inr(td?.capital)} sub={`peak in use today · now ${inr(td?.capital_now)}`} />
          <Tile label="ROI today" value={pct(td?.roi)} valueClass={tone(td?.roi)} sub="net P&L ÷ capital invested" />
          <Tile label="Activity" value={`${today.fills.length} trades`} sub={`${today.orders.length} orders · ${openNow} open position${openNow === 1 ? "" : "s"} · turnover ${inr(td?.turnover)}`} />
        </div>
        {pnlCurve.length > 1 && (
          <div className="grid-2 charts">
            <div>
              <div className="chart-title">P&amp;L through the day (Angel, gross, every 5 minutes)</div>
              <LineChart points={pnlCurve} height={150} fillToZero formatValue={(v) => signed(v)} />
            </div>
            <div>
              <div className="chart-title">Capital in use through the day</div>
              <LineChart points={capCurve} height={150} formatValue={(v) => inr(v)} />
            </div>
          </div>
        )}
      </GlassPanel>

      {life && stmts.length > 0 && (
        <GlassPanel title="Your record with Angel One" note={life.from ? `${longDate(life.from)} → ${longDate(life.to)}` : undefined}>
          <div className="tiles">
            <Tile label="Net P&L, everything recorded" value={signed(life.net, 2)} valueClass={tone(life.net)}
              sub={`gross ${signed(life.gross, 2)} · charges −₹${life.charges.toFixed(2)}`} />
            {counted.map((s) => (
              <Tile key={s.id ?? s.from} label={`${longDate(s.from)} → ${longDate(s.to)}`} value={signed(s.net, 2)} valueClass={tone(s.net)}
                sub={`Angel's P&L report · ${s.positions} closed positions, ${s.wins} won${s.stats.sessions ? ` · ${signed(s.stats.net_per_session, 0)} a session` : ""}`} />
            ))}
            <Tile label={`Day by day · ${life.days} day${life.days === 1 ? "" : "s"}`} value={signed(life.days_net, 2)} valueClass={tone(life.days_net)}
              sub={dayFirst ? `${longDate(dayFirst)}${dayLast !== dayFirst ? ` → ${longDate(dayLast)}` : ""} · with capital and ROI` : "from the next MCX session"} />
            <Tile label="Charges" value={`−₹${life.charges.toFixed(2)}`} valueClass="loss"
              sub={`₹${life.charges_actual.toFixed(2)} Angel's actual (report) + ₹${life.charges_estimated.toFixed(2)} estimated (days)`} />
          </div>
          {stmts.filter((s) => s.counted === false).map((s) => (
            <div key={`out-${s.id ?? s.from}`} className="note warn">Angel&apos;s report for {longDate(s.from)} → {longDate(s.to)} is not in this total: {s.reason}.</div>
          ))}
          <div className="note">
            Angel&apos;s P&amp;L report adds the period before this page began, with Angel&apos;s own P&amp;L and charges. It has no trade
            dates and no capital, so it counts here but not in the daily ROI, the averages or the projections below — those rest on the
            days recorded one by one. The Trades tab lists its positions; Angel&apos;s Trade History (Data tab) would give its days one by one.
          </div>
        </GlassPanel>
      )}

      <div className="grid-2">
        <GlassPanel title="Account and margin (Angel RMS)">
          {Object.keys(funds).length ? (
            <>
              {util !== null && (
                <div className="util">
                  <div className="util-head"><span>Capital in use</span><b>{plainPct(util)} of {inr(used + free)}</b></div>
                  <div className="util-track"><div className="util-fill" style={{ width: `${Math.min(100, util * 100)}%` }} /></div>
                  <div className="small muted">{inr(used)} in use · {inr(free)} free</div>
                </div>
              )}
              {FUNDS.filter(([k]) => funds[k] !== undefined).map(([k, label]) => (
                <Kv key={k} k={label} v={inr(funds[k], 2)} vClass={k.startsWith("m2m") ? tone(funds[k]) : ""} />
              ))}
              {td?.funds_open?.availablecash !== undefined && (
                <Kv k="Available cash at the first poll today" v={inr(td.funds_open.availablecash, 2)} />
              )}
            </>
          ) : <div className="empty">Angel&apos;s funds are recorded from the next poll.</div>}
        </GlassPanel>

        <GlassPanel title="Averages and what they come to" note={av.days ? `${av.days} trading day(s), ${av.first} → ${av.last}` : undefined}>
          {av.days ? (
            <>
              <Kv k="Average capital invested a day" v={inr(av.avg_capital)} />
              <Kv k="Average net return a day" v={signed(av.avg_net_pnl)} vClass={tone(av.avg_net_pnl)} />
              <Kv k="Average return % a day (return ÷ capital)" v={pct(av.avg_return_pct, 3)} vClass={tone(av.avg_return_pct)} />
              <Kv k="Mean of the daily ROIs" v={pct(av.mean_daily_roi, 3)} vClass={tone(av.mean_daily_roi)} />
              <Kv k={`One month (${pj?.sessions_month} sessions)`} v={<>{signed(pj?.month_rupees)} · {pct(pj?.month_pct_simple)} simple · {pct(pj?.month_pct_compound)} compounded</>} vClass={tone(pj?.month_rupees)} />
              <Kv k={`One year (${pj?.sessions_year} sessions)`} v={<>{signed(pj?.year_rupees)} · {pct(pj?.year_pct_simple)} simple · {pj?.year_pct_compound === null ? "compounding too large to state" : `${pct(pj?.year_pct_compound)} compounded`}</>} vClass={tone(pj?.year_rupees)} />
              <Kv k="Record so far" v={<>{signed(av.total_net_pnl)} · {av.green_days} of {av.days} days green</>} vClass={tone(av.total_net_pnl)} />
              {lastReport && (
                <Kv k={`Actual, ${longDate(lastReport.from)} → ${longDate(lastReport.to)} (Angel's P&L report)`}
                  v={<>{signed(lastReport.net, 2)}{lastReport.stats.sessions ? ` · ${signed(lastReport.stats.net_per_session, 0)} a session over ${lastReport.stats.sessions}` : ""}</>}
                  vClass={tone(lastReport.net)} />
              )}
              <div className="note">
                Month and year repeat the past average — arithmetic, not a forecast. They rest on {av.days} day(s)
                {av.t_stat !== null && av.t_stat !== undefined ? ` (t = ${av.t_stat})` : ""}
                {av.days < 20 ? ", far too few for the average to mean much yet." : "."}
              </div>
            </>
          ) : <div className="empty">No trading days recorded yet.</div>}
        </GlassPanel>
      </div>

      <GlassPanel title="Performance so far" note={perf?.days ? `daily records · ${analytics?.stats.trades ?? 0} completed trades` : undefined}>
        {perf && perf.days ? (
          <>
            <div className="tiles">
              <Tile label="Green days" value={`${perf.green_days} / ${perf.days}`} sub={`avg green ${signed(perf.avg_green)} · avg red ${signed(perf.avg_red)}`} />
              <Tile label="Profit factor (days)" value={num(perf.profit_factor_days)} sub="gains on green days ÷ losses on red days" />
              <Tile label="Max drawdown" value={signed(perf.max_drawdown)} valueClass={tone(perf.max_drawdown)}
                sub={perf.drawdown_from ? `${perf.drawdown_from} → ${perf.drawdown_to} · ${pct(perf.max_drawdown_pct_avg_capital)} of avg capital` : "none yet"} />
              <Tile label="Current drawdown" value={signed(perf.current_drawdown)} valueClass={tone(perf.current_drawdown)}
                sub={`longest run below a peak: ${perf.longest_drawdown_days ?? 0} day(s)`} />
              <Tile label="Sharpe / Sortino" value={`${num(perf.sharpe)} / ${num(perf.sortino)}`}
                sub={perf.days < 20 ? "annualised on daily ROI — needs 20+ days to mean anything" : "annualised on daily ROI (×√250)"} />
              <Tile label="Streak" value={perf.current_streak ? `${Math.abs(perf.current_streak)} ${perf.current_streak > 0 ? "green" : "red"}` : "–"}
                valueClass={tone(perf.current_streak)} sub={`best day ${signed(perf.best?.net)} · worst ${signed(perf.worst?.net)}`} />
              {st && st.trades ? (
                <>
                  <Tile label="Trade win rate" value={plainPct(st.win_rate)} sub={`${st.wins} won of ${st.trades} completed trades`} />
                  <Tile label="Expectancy / trade" value={signed(st.expectancy)} valueClass={tone(st.expectancy)}
                    sub={`profit factor ${num(st.profit_factor)} · avg hold ${holdText(st.avg_hold_minutes)}`} />
                </>
              ) : null}
            </div>
            {perf.series && perf.series.length > 1 && (
              <div className="grid-2 charts">
                <div>
                  <div className="chart-title">Cumulative net P&amp;L</div>
                  <LineChart points={perf.series.map((s) => ({ ts: s.date, value: s.cum }))} height={160} fillToZero formatValue={(v) => signed(v)} />
                </div>
                <div>
                  <div className="chart-title">Drawdown from the running peak</div>
                  <LineChart points={perf.series.map((s) => ({ ts: s.date, value: s.drawdown }))} height={160} fillToZero formatValue={(v) => signed(v)} />
                </div>
              </div>
            )}
          </>
        ) : <div className="empty">Performance appears once a day has been recorded.</div>}
      </GlassPanel>

      {breakdown.length > 0 && (
        <GlassPanel title="Where today's charges went">
          <BarList rows={breakdown.map(([k, v]) => ({ key: k, label: COMP_LABEL[k] ?? k, value: -v }))} format={(v) => `−₹${Math.abs(v).toFixed(2)}`} />
        </GlassPanel>
      )}

      <style jsx>{`
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        @media (max-width: 1000px) { .grid-2 { grid-template-columns: 1fr; } }
        .charts { margin-top: 14px; }
        .chart-title { font-size: 11.5px; color: var(--text-muted); margin-bottom: 4px; }
        .util { margin-bottom: 10px; }
        .util-head { display: flex; justify-content: space-between; font-size: 12.5px; }
        .util-track { height: 10px; background: var(--canvas-soft); border-radius: 6px; overflow: hidden; margin: 6px 0 4px; }
        .util-fill { height: 100%; background: var(--accent-hover); }
        .small { font-size: 11px; }
        .muted { color: var(--text-muted); }
        .note { font-size: 11.5px; color: var(--text-muted); padding: 8px 2px 0; line-height: 1.55; }
        .note.warn { color: var(--warn); }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
      `}</style>
    </>
  );
}
