"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import DeskHistory from "../../components/DeskHistory";
import ErrorBanner from "../../components/ErrorBanner";
import {
  refreshing,
  ZeroHeroDaily,
  ZeroHeroPosition,
  ZeroHeroScore,
  ZeroHeroSignal,
  ZeroHeroSummary,
  ZeroHeroTrade,
  fetchZeroHeroDaily,
  fetchZeroHeroLeaderboard,
  fetchZeroHeroPositions,
  fetchZeroHeroSignals,
  fetchZeroHeroSummary,
  fetchZeroHeroTrades,
} from "../../lib/api";

const REFRESH_MS = 30000;
type Tab = "leaderboard" | "open" | "closed" | "daily" | "signals";

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pctv = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;

export default function ZeroHeroPage() {
  const [tab, setTab] = useState<Tab>("leaderboard");
  const [summary, setSummary] = useState<ZeroHeroSummary | null>(null);
  const [board, setBoard] = useState<ZeroHeroScore[]>([]);
  const [open, setOpen] = useState<ZeroHeroPosition[]>([]);
  const [closed, setClosed] = useState<ZeroHeroPosition[]>([]);
  const [trades, setTrades] = useState<ZeroHeroTrade[]>([]);
  const [daily, setDaily] = useState<ZeroHeroDaily[]>([]);
  const [signals, setSignals] = useState<ZeroHeroSignal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, lb, op, cl, tr, dp, sg] = await Promise.all([
        fetchZeroHeroSummary(),
        fetchZeroHeroLeaderboard(),
        fetchZeroHeroPositions("OPEN"),
        fetchZeroHeroPositions("CLOSED"),
        fetchZeroHeroTrades(),
        fetchZeroHeroDaily(),
        fetchZeroHeroSignals(),
      ]);
      setSummary(s);
      setBoard(lb);
      setOpen(op.positions ?? []);
      setClosed(cl.positions ?? []);
      setTrades(tr);
      setDaily(dp);
      setSignals(sg);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Zero Hero Trades");
    }
  }, []);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return board;
    return board.filter((r) => r.name.toLowerCase().includes(f) || r.index.toLowerCase().includes(f));
  }, [board, filter]);

  const expiring = summary?.expiring_today ?? [];

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Zero Hero Trades"
        title="Zero Hero Trades"
        subtitle="PAPER desk for the expiry-day lottery: 50 strategies buying deep-OTM index options for a few rupees, betting one sharp move turns ₹2 into ₹50. Each strategy trades its own ₹1,00,000 account on live Angel One premiums, and only on a day that index actually expires."
      />

      {error && <ErrorBanner message={error} />}

      <div className="warn">
        <b>Read this before you trust a number here.</b> Deep-OTM expiry buying is a lottery
        ticket, not an edge: the payoff is genuinely asymmetric (risk 100% of a tiny premium,
        reward 20–100×) but the base rate is awful — most of these expire at exactly zero, and
        theta on expiry day is brutal. SEBI&apos;s own data has ~90% of retail F&amp;O traders
        losing money, with expiry-day speculation a large part of it. That is why this board
        ranks on <b>profit factor and expectancy</b>, not win rate: the only question that
        matters is whether the rare winners pay for the many losers. This desk is here to
        measure that honestly, on paper, before any of it is believed.
      </div>

      <div className="tiles">
        <Tile label="Mode" value="PAPER" sub={`${summary?.strategy_count ?? 0} strategies`} />
        <Tile label="Capital" value={inr(summary?.initial_capital)} sub={`${inr(summary?.per_strategy_capital)} each`} />
        <Tile
          label="Equity"
          value={inr(summary?.equity)}
          tone={(summary?.equity ?? 0) >= (summary?.initial_capital ?? 0) ? "gain" : "loss"}
          sub={`${signed(summary?.realized_pnl)} realised`}
        />
        <Tile label="Open" value={String(summary?.open_positions ?? 0)} sub={`${signed(summary?.unrealized_pnl)} unrealised`} />
        <Tile
          label="Closed"
          value={String(summary?.closed_positions ?? 0)}
          sub={`${summary?.wins ?? 0} winners · ${pctv(summary?.win_rate)} hit`}
        />
        <Tile label="Max per trade" value={inr(summary?.max_trade_budget)} sub="10% of a strategy's account" />
        <Tile
          label="Expiring today"
          value={expiring.length ? String(expiring.length) : "none"}
          tone={expiring.length ? "gain" : undefined}
          sub={expiring.length ? expiring.join(" · ") : "desk idle — expiry-day only"}
        />
      </div>

      {summary?.last_notes?.length ? <div className="note">{summary.last_notes.join(" · ")}</div> : null}

      <div className="tabs">
        {([
          ["leaderboard", `Leaderboard (${board.length})`],
          ["open", `Open (${open.length})`],
          ["closed", `Closed (${closed.length})`],
          ["daily", `Daily P&L (${daily.length})`],
          ["signals", `Signals (${signals.length})`],
        ] as [Tab, string][]).map(([k, label]) => (
          <button key={k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "leaderboard" && (
        <GlassPanel title="Strategy leaderboard">
          <div className="controls">
            <input className="filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by index or name…" />
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>Index</th>
                  <th>OTM</th>
                  <th>Max ₹</th>
                  <th>Window</th>
                  <th>Trigger</th>
                  <th>Target</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>PF</th>
                  <th>Expectancy</th>
                  <th>Best</th>
                  <th>Net P&amp;L</th>
                  <th>Account</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.strategy_id}>
                    <td style={{ textAlign: "left" }} className="sname">{r.name}</td>
                    <td><span className="badge">{r.index}</span></td>
                    <td>{(r.otm_pct * 100).toFixed(2)}%</td>
                    <td>₹{r.max_premium}</td>
                    <td className="dim">{r.window_from}–{r.window_to}</td>
                    <td><span className="trig">{r.trigger}</span></td>
                    <td>{r.target_mult}×</td>
                    <td>{r.trades}</td>
                    <td>{r.trades ? pctv(r.win_rate) : "—"}</td>
                    <td className={r.profit_factor != null && r.profit_factor >= 1 ? "gain" : r.profit_factor != null ? "loss" : ""}>
                      {r.profit_factor == null ? "—" : r.profit_factor.toFixed(2)}
                    </td>
                    <td className={r.expectancy >= 0 ? "gain" : "loss"}>{r.trades ? signed(r.expectancy) : "—"}</td>
                    <td className="gain">{r.trades ? signed(r.best_trade) : "—"}</td>
                    <td className={r.net_pnl >= 0 ? "gain" : "loss"}>{signed(r.net_pnl)}</td>
                    <td>{inr(r.capital)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      )}

      {(tab === "open" || tab === "closed") && (
        <GlassPanel title={tab === "open" ? `Open positions (${open.length})` : `Closed positions (${closed.length})`}>
          {!(tab === "open" ? open : closed).length ? (
            <div className="empty">
              {tab === "open"
                ? "No open positions — this desk only trades on an index's expiry day."
                : "Nothing closed yet."}
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Index</th>
                    <th>Contract</th>
                    <th>Spot @ entry</th>
                    <th>Lots</th>
                    <th>Qty</th>
                    <th>Entry ₹</th>
                    <th>{tab === "open" ? "Now ₹" : "Exit ₹"}</th>
                    <th>Cost</th>
                    <th>Target ₹</th>
                    <th>{tab === "open" ? "Unrealised" : "Realised"}</th>
                    {tab === "closed" && <th>Outcome</th>}
                    <th style={{ textAlign: "left" }}>Strategy</th>
                  </tr>
                </thead>
                <tbody>
                  {(tab === "open" ? open : closed).map((p) => (
                    <tr key={p.position_id}>
                      <td><span className="badge">{p.index}</span></td>
                      <td className="sym">{p.strike}&nbsp;{p.option_type}</td>
                      <td className="dim">{p.spot_at_entry}</td>
                      <td>{p.lots}</td>
                      <td>{p.qty}</td>
                      <td>{inr(p.entry_premium)}</td>
                      <td>{inr(tab === "open" ? p.ltp : p.exit_premium)}</td>
                      <td>{inr(p.capital_deployed)}</td>
                      <td className="dim">{inr(p.target_premium)}</td>
                      <td className={((tab === "open" ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "gain" : "loss"}>
                        {signed(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}
                      </td>
                      {tab === "closed" && (
                        <td>
                          <span className={p.exit_reason === "target" ? "out win" : "out lose"}>
                            {p.exit_reason === "expired_worthless" ? "expired ₹0" : p.exit_reason}
                          </span>
                        </td>
                      )}
                      <td style={{ textAlign: "left" }} className="dim">{p.strategy_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "daily" && (
        <GlassPanel title="Daily P&L by session">
          {!daily.length ? (
            <div className="empty">No completed sessions yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Session</th>
                    <th>Trades</th>
                    <th>Winners</th>
                    <th>Win %</th>
                    <th>Best trade</th>
                    <th>Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {daily.map((d) => (
                    <tr key={d.session}>
                      <td className="sym">{d.session}</td>
                      <td>{d.trades}</td>
                      <td>{d.wins}</td>
                      <td>{pctv(d.win_rate)}</td>
                      <td className="gain">{signed(d.best_trade)}</td>
                      <td className={d.net_pnl >= 0 ? "gain" : "loss"}>{signed(d.net_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {trades.length > 0 && (
            <div className="sub">
              <div className="sub-head">Recent closed trades — the multiple achieved is what a zero-hero trade lives or dies on</div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Session</th>
                      <th>Index</th>
                      <th>Contract</th>
                      <th>Entry ₹</th>
                      <th>Exit ₹</th>
                      <th>Multiple</th>
                      <th>P&amp;L</th>
                      <th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.slice(0, 50).map((t) => (
                      <tr key={t.trade_id}>
                        <td className="dim">{t.session}</td>
                        <td><span className="badge">{t.index}</span></td>
                        <td className="sym">{t.strike}&nbsp;{t.option_type}</td>
                        <td>{inr(t.entry_premium)}</td>
                        <td>{inr(t.exit_premium)}</td>
                        <td className={(t.multiple ?? 0) >= 1 ? "gain" : "loss"}>{t.multiple == null ? "—" : `${t.multiple}×`}</td>
                        <td className={t.realized_pnl >= 0 ? "gain" : "loss"}>{signed(t.realized_pnl)}</td>
                        <td>
                          <span className={t.exit_reason === "target" ? "out win" : "out lose"}>
                            {t.exit_reason === "expired_worthless" ? "expired ₹0" : t.exit_reason}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "signals" && (
        <GlassPanel title="Signal history">
          <div className="note">
            Every candidate the desk evaluated, taken or not. A signal that was skipped carries
            the reason — which is how you tell &quot;the strategy never fired&quot; apart from
            &quot;it fired and lost&quot;.
          </div>
          {!signals.length ? (
            <div className="empty">No signals recorded yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Index</th>
                    <th>Contract</th>
                    <th>Spot</th>
                    <th>Premium</th>
                    <th>Band</th>
                    <th>Taken</th>
                    <th style={{ textAlign: "left" }}>Reason / strategy</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((s) => (
                    <tr key={s.signal_id}>
                      <td className="dim">{(s.ts || "").replace("T", " ").slice(0, 16)}</td>
                      <td><span className="badge">{s.index}</span></td>
                      <td className="sym">{s.strike}&nbsp;{s.option_type}</td>
                      <td className="dim">{s.spot}</td>
                      <td>{s.premium == null ? "—" : inr(s.premium)}</td>
                      <td className="dim">≤ ₹{s.max_premium}</td>
                      <td>
                        <span className={s.taken ? "out win" : "out skip"}>{s.taken ? "taken" : "skipped"}</span>
                      </td>
                      <td style={{ textAlign: "left" }} className="dim">
                        {s.reason ? s.reason : s.strategy_name}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      <DeskHistory deskKey={"zero-hero"} />

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .warn { padding: 13px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-left: 3px solid var(--accent); font-size: 12px; line-height: 1.65; color: var(--text-muted); }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .note { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12px; color: var(--text-muted); line-height: 1.6; }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 15px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .controls { padding-bottom: 10px; }
        .filter { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 8px 13px; font-size: 12.5px; min-width: 240px; }
        .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); }
        .table-scroll { overflow-x: auto; max-height: 620px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 11px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 8px 11px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .sname { font-weight: 600; }
        .sym { font-weight: 700; }
        .dim { color: var(--text-faint); }
        .badge { display: inline-block; padding: 2px 7px; border-radius: 6px; font-size: 10px; font-weight: 700; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .trig { font-size: 10.5px; font-weight: 700; color: var(--purple); background: var(--purple-dim); padding: 2px 7px; border-radius: 6px; }
        .out { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }
        .out.win { background: var(--gain-dim); color: var(--gain); }
        .out.lose { background: var(--loss-dim); color: var(--loss); }
        .out.skip { background: var(--canvas-soft); color: var(--text-faint); }
        .sub { margin-top: 18px; }
        .sub-head { font-size: 11.5px; font-weight: 700; color: var(--text-muted); padding-bottom: 8px; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>

      <style jsx global>{`
        .app-main { max-width: none !important; margin-left: 0 !important; margin-right: 0 !important; }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "gain" | "loss" }) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .t-label { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .t-value { font-family: var(--font-display); font-weight: 800; font-size: 21px; margin-top: 6px; }
        .t-value.gain { color: var(--gain); }
        .t-value.loss { color: var(--loss); }
        .t-sub { font-size: 11px; color: var(--text-faint); margin-top: 4px; }
      `}</style>
    </div>
  );
}
