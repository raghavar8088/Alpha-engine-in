"use client";

// The Live Trading PAPER TWIN (18 Nov 2026): this desk's rules on paper money, side by side with what the
// real desk actually did.
//
// It is one Live Intraday book ("ltpaper", backend live_intraday_engine.TWIN_BOOK) configured from the
// real-money desk: whichever strategies are switched on here (from the moment each is switched on),
// Rs 30,000 a position at 5x MIS, at most five at once, one per stock, the 3% daily breaker, and the
// real Angel balance of 18 Nov 2026 as its money. It copies the tournament's own fills, so it shows what
// the RULES earn with perfect fills and no refusals; every trade sits beside the real desk's decision on
// the same signal. Paper only - nothing here can place an order.

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import { LiveTradingTwin, TwinOutcome, TwinRow, fetchLiveTradingTwin } from "../../lib/api";

const REFRESH_MS = 30000;

const OUTCOME: Record<TwinOutcome, { label: string; why: string; tone: "gain" | "loss" | "warn" | "muted" }> = {
  taken: { label: "Real desk took it", why: "taken by the real desk", tone: "gain" },
  refused: { label: "Angel refused", why: "refused by Angel", tone: "loss" },
  disarmed: { label: "Real desk disarmed", why: "real desk disarmed", tone: "warn" },
  not_seen: { label: "Real desk never tried", why: "never tried by the real desk", tone: "muted" },
  skipped: { label: "Real desk skipped", why: "skipped by the real desk", tone: "warn" },
};

const inr = (v: number | null | undefined, dp = 0) =>
  v == null || Number.isNaN(v)
    ? "₹-"
    : `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined, dp = 0) => (v == null ? "₹-" : `${v > 0 ? "+" : ""}${inr(v, dp)}`);
const tone = (v: number | null | undefined) => (v == null || Math.abs(v) < 0.005 ? "" : v > 0 ? "gain" : "loss");
const px = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));

function ist(iso: string | null | undefined, withDay = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    ...(withDay ? { day: "numeric", month: "short" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function PaperTwin({ realArmed }: { realArmed: boolean | null }) {
  const [data, setData] = useState<LiveTradingTwin | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetchLiveTradingTwin());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the paper twin");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // Per strategy, from the side-by-side rows: what the twin earned and what the real desk earned on it.
  const byStrategy = useMemo(() => {
    const m = new Map<string, { name: string; pT: number; pN: number; rT: number; rN: number }>();
    for (const r of data?.rows ?? []) {
      const k = r.strategy_name || r.strategy_id || "—";
      const x = m.get(k) ?? { name: k, pT: 0, pN: 0, rT: 0, rN: 0 };
      if (r.paper) {
        x.pT += 1;
        x.pN += r.paper.net;
      }
      if (r.real) {
        x.rT += 1;
        x.rN += r.real.net;
      }
      m.set(k, x);
    }
    return [...m.values()].sort((a, b) => b.pN - a.pN);
  }, [data]);

  if (data === null) {
    return (
      <GlassPanel title="Paper twin">
        <div className="tw-wait">
          The paper twin is set up — the same strategies, ₹30,000 a position at 5x, five at once, one per stock,
          and ₹33,882 of paper money (the Angel balance on 18 Nov 2026) — but the server has not been updated with
          it yet. It starts copying from 18 Nov 2026&apos;s session once the backend is deployed. Until then this tab
          shows nothing, so no other account&apos;s numbers can appear under its name.
        </div>
        <style jsx>{`
          .tw-wait { padding: 18px 20px; font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        `}</style>
      </GlassPanel>
    );
  }

  const s = data?.summary;
  const t = data?.totals;
  const desk = data?.real_desk;
  const sk: Record<string, number> = { ...(s?.skipped ?? {}) };
  const skippedTotal = Object.values(sk).reduce((a, b) => a + (b || 0), 0);
  const on = (desk?.strategies ?? []).filter((x) => x.enabled);
  const reasons = t?.paper_only_by_reason ?? {};

  return (
    <div className="tw">
      {error && <ErrorBanner message={error} onRetry={load} />}

      <div className="tw-note">
        <p>
          <b>Paper twin of this desk.</b> The same rules on paper money: the strategies switched on here (each from
          the moment it is switched on), {inr(desk?.copy_notional ?? 30000)} a position at {desk?.mis_leverage ?? 5}x
          intraday (MIS) leverage, at most {desk?.max_open_positions ?? 5} at once, one per stock, the{" "}
          {Math.round((desk?.breaker_pct ?? 0.03) * 100)}% daily loss breaker — and {inr(s?.initial_capital, 2)} of paper
          money, the real Angel balance read {ist(data?.capital_read_at)} IST.
        </p>
        <p>
          It copies the tournament&apos;s own fills, so it shows what the rules earn with perfect fills and no broker
          refusals. Every trade sits beside what the real desk did with the same signal. Paper only — nothing here can
          place an order.
        </p>
        <p className="tw-state">
          Real desk now:{" "}
          <span className={`chip ${realArmed == null ? "muted" : realArmed ? "gain" : "loss"}`}>
            {realArmed == null ? "status unknown" : realArmed ? "ARMED" : "disarmed"}
          </span>
          {" · "}switched on:{" "}
          {on.length ? on.map((x) => <span className="chip" key={x.strategy_id}>{x.name}</span>) : <span className="chip muted">none</span>}
        </p>
      </div>

      {data === undefined ? (
        <div className="tw-load">Loading the paper twin…</div>
      ) : (
        <>
          <div className="tiles">
            <div className="tile">
              <div className="t-k">Paper money</div>
              <div className="t-v">{inr(s?.initial_capital, 2)}</div>
              <div className="t-s">copying since {ist(data?.copying_since)}</div>
            </div>
            <div className="tile">
              <div className="t-k">Equity</div>
              <div className="t-v">{inr(s?.equity, 2)}</div>
              <div className={`t-s ${tone(s?.roi_pct)}`}>
                {(s?.roi_pct ?? 0) >= 0 ? "+" : ""}
                {(s?.roi_pct ?? 0).toFixed(2)}% on the paper money
              </div>
            </div>
            <div className="tile">
              <div className="t-k">Realised (after costs)</div>
              <div className={`t-v ${tone(s?.realized_pnl)}`}>{signed(s?.realized_pnl, 2)}</div>
              <div className="t-s">{s?.closed_positions ?? 0} closed · charges {inr(s?.total_fees, 2)}</div>
            </div>
            <div className="tile">
              <div className="t-k">Open</div>
              <div className="t-v">{s?.open_positions ?? 0}</div>
              <div className={`t-s ${tone(s?.unrealized_pnl)}`}>
                {signed(s?.unrealized_pnl, 2)} unrealised · margin {inr(s?.margin_used ?? s?.deployed_capital)}
              </div>
            </div>
            <div className="tile">
              <div className="t-k">Today</div>
              <div className={`t-v ${tone(s?.today_pnl)}`}>{signed(s?.today_pnl, 2)}</div>
              <div className="t-s">
                {s?.breaker_tripped ? "breaker tripped — no new entries today" : `breaker at −${inr(s?.daily_loss_limit)}`}
              </div>
            </div>
            <div className="tile">
              <div className="t-k">Signals skipped</div>
              <div className="t-v">{skippedTotal}</div>
              <div className="t-s">
                {skippedTotal
                  ? Object.entries(sk).filter(([, v]) => v).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ")
                  : "none yet"}
              </div>
            </div>
          </div>

          <GlassPanel title="Paper twin vs the real desk" note={`since ${ist(data?.copying_since)} IST`}>
            <div className="vs">
              <table className="vs-t">
                <thead>
                  <tr>
                    <th />
                    <th>Paper twin</th>
                    <th>Real desk</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="l">Trades</td>
                    <td>{t?.paper.trades ?? 0}</td>
                    <td>{t?.real.trades ?? 0}</td>
                  </tr>
                  <tr>
                    <td className="l">Closed · won</td>
                    <td>
                      {t?.paper.closed ?? 0} · {t?.paper.wins ?? 0}
                    </td>
                    <td>
                      {t?.real.closed ?? 0} · {t?.real.wins ?? 0}
                    </td>
                  </tr>
                  <tr>
                    <td className="l">Net P&amp;L (open marked)</td>
                    <td className={tone(t?.paper.net)}>{signed(t?.paper.net, 2)}</td>
                    <td className={tone(t?.real.net)}>{signed(t?.real.net, 2)}</td>
                  </tr>
                </tbody>
              </table>
              <ul className="vs-notes">
                <li>
                  <b>{t?.both ?? 0}</b> signal{t?.both === 1 ? "" : "s"} both took: paper{" "}
                  <span className={tone(t?.both_paper_net)}>{signed(t?.both_paper_net, 2)}</span>, real{" "}
                  <span className={tone(t?.both_real_net)}>{signed(t?.both_real_net, 2)}</span> — the gap is the real
                  fills, quantity and timing.
                </li>
                <li>
                  <b>{t?.paper_only ?? 0}</b>{" "}only on paper:{" "}
                  {(Object.keys(OUTCOME) as TwinOutcome[])
                    .filter((k) => k !== "taken" && (reasons[k] ?? 0) > 0)
                    .map((k) => `${reasons[k]} ${OUTCOME[k].why}`)
                    .join(" · ") || "none"}
                  .
                </li>
                <li>
                  <b>{t?.real_only ?? 0}</b>{" "}
                  {"only on the real desk — the twin's five slots or one-stock rule turned them down (or the twin had not started)."}
                </li>
              </ul>
            </div>
          </GlassPanel>

          {byStrategy.length > 0 && (
            <GlassPanel title="By strategy">
              <div className="scroll">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th className="l">Strategy</th>
                      <th>Paper trades</th>
                      <th>Paper net</th>
                      <th>Real trades</th>
                      <th>Real net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byStrategy.map((x) => (
                      <tr key={x.name}>
                        <td className="l">{x.name}</td>
                        <td>{x.pT}</td>
                        <td className={tone(x.pN)}>{signed(x.pN, 2)}</td>
                        <td>{x.rT}</td>
                        <td className={tone(x.rN)}>{x.rT ? signed(x.rN, 2) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassPanel>
          )}

          <GlassPanel title={`Trades, paper beside real (${data?.rows.length ?? 0})`}>
            {!data?.rows.length ? (
              <div className="empty">
                No trade yet. The twin takes the switched-on strategies&apos; tournament signals from{" "}
                {ist(data?.copying_since)} IST, during market hours.
              </div>
            ) : (
              <div className="scroll">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th className="l">Opened (IST)</th>
                      <th className="l">Strategy</th>
                      <th className="l">Stock</th>
                      <th>Side</th>
                      <th>Paper: qty · entry → exit</th>
                      <th>Paper net</th>
                      <th className="l">Real desk</th>
                      <th>Real: qty · entry → exit</th>
                      <th>Real net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r: TwinRow, i: number) => (
                      <tr key={`${r.parent_id ?? "x"}-${i}`}>
                        <td className="l">{ist(r.opened_at)}</td>
                        <td className="l muted">{r.strategy_name ?? r.strategy_id}</td>
                        <td className="l sym">{r.symbol}</td>
                        <td>
                          <span className={`side ${r.side === "SELL" ? "sell" : "buy"}`}>{r.side}</span>
                        </td>
                        <td>
                          {r.paper ? (
                            <>
                              {r.paper.qty} · {px(r.paper.entry)} → {r.paper.status === "OPEN" ? "open" : px(r.paper.exit)}
                            </>
                          ) : (
                            <span className="muted">not taken</span>
                          )}
                        </td>
                        <td className={r.paper ? tone(r.paper.net) : ""}>{r.paper ? signed(r.paper.net, 2) : "—"}</td>
                        <td className="l">
                          <span className={`chip ${OUTCOME[r.real_outcome]?.tone ?? "muted"}`} title={r.real_outcome_text}>
                            {OUTCOME[r.real_outcome]?.label ?? r.real_outcome}
                          </span>
                        </td>
                        <td>
                          {r.real ? (
                            <>
                              {r.real.qty} · {px(r.real.entry)} → {r.real.status === "OPEN" ? "open" : px(r.real.exit)}
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className={r.real ? tone(r.real.net) : ""}>{r.real ? signed(r.real.net, 2) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassPanel>

          <div className="tw-foot">
            Paper fills are the tournament&apos;s own prices; the real desk sizes on the live quote and fills at Angel&apos;s,
            so even a signal both took will not match to the rupee. A stock on the exchange&apos;s caution list is refused by
            Angel&apos;s API and taken only here. The same account also appears on the Intraday Stocks page as
            &quot;Live Trading · Paper twin&quot;.
          </div>
        </>
      )}

      <style jsx>{`
        .tw { display: flex; flex-direction: column; gap: 16px; }
        .tw-note { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.55;
                   background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .tw-note p { margin: 0 0 8px; }
        .tw-note p:last-child { margin: 0; }
        .tw-state { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
        .chip { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 700;
                border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); white-space: nowrap; }
        .chip.gain { color: var(--gain); background: var(--gain-dim); border-color: rgba(var(--gain-rgb), .3); }
        .chip.loss { color: var(--loss); background: var(--loss-dim); border-color: rgba(var(--loss-rgb), .3); }
        .chip.warn { color: var(--warn); background: var(--warn-dim); border-color: rgba(var(--warn-rgb), .3); }
        .chip.muted { color: var(--text-faint); }
        .tw-load { padding: 18px 4px; font-size: 12.5px; color: var(--text-faint); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
        .tile { border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 14px; background: var(--panel); }
        .t-k { font-size: 10.5px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: var(--text-muted); }
        .t-v { margin-top: 4px; font-size: 19px; font-weight: 800; font-family: var(--font-data, ui-monospace), monospace; color: var(--text); }
        .t-s { margin-top: 3px; font-size: 11px; color: var(--text-faint); line-height: 1.4; }
        .vs { padding: 12px 20px 16px; display: grid; grid-template-columns: minmax(260px, 1fr) 2fr; gap: 18px; align-items: start; }
        @media (max-width: 820px) { .vs { grid-template-columns: 1fr; } }
        .vs-t { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .vs-t th { font-size: 10px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: var(--text-muted);
                   padding: 6px 8px; border-bottom: 1px solid var(--panel-border); text-align: center; }
        .vs-t td { padding: 7px 8px; border-bottom: 1px solid var(--canvas-soft); text-align: center; }
        .vs-notes { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .scroll { overflow-x: auto; }
        .tbl { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .tbl th { padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
                  color: var(--text-muted); border-bottom: 1px solid var(--panel-border); text-align: center; }
        .tbl td { padding: 7px 10px; border-bottom: 1px solid var(--canvas-soft); text-align: center; }
        .l { text-align: left !important; }
        .sym { font-weight: 700; color: var(--text); }
        .side { font-weight: 800; font-size: 10.5px; padding: 2px 7px; border-radius: 6px; }
        .side.buy { color: var(--gain); background: var(--gain-dim); }
        .side.sell { color: var(--loss); background: var(--loss-dim); }
        .muted { color: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .empty { padding: 20px; font-size: 12.5px; color: var(--text-faint); }
        .tw-foot { font-size: 11px; line-height: 1.55; color: var(--text-faint); padding: 0 2px; }
      `}</style>
    </div>
  );
}
