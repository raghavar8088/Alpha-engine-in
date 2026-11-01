"use client";

// Crypto Trading (2026-11-01): the top ten cryptocurrencies by market cap (stablecoins and wrapped /
// staked duplicates excluded, screened for liquidity, history and venue listing) paper traded on Delta
// Exchange India's perpetuals by the Strategy Factory's and the Strategies module's strategies - one
// $10,000 account per strategy-cryptocurrency pair, every pair backtested on the venue's own history
// and only those graded 3+ on crypto results trading. Backend: app/services/crypto_trading,
// /api/crypto-trading.
import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  AccountRow,
  BacktestRow,
  Overview,
  PairDetail,
  PairStatus,
  Position,
  Signal,
  StrategyRow,
  controlDesk,
  fetchAccounts,
  fetchBacktests,
  fetchLibrary,
  fetchOverview,
  fetchPair,
  fetchPositions,
  fetchSignals,
  fetchUniverse,
  resetDesk,
  Universe,
} from "../../lib/cryptoTrading";

const REFRESH_MS = 30000;
const PAGE = 100;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"];
const STATUS_LABEL: Record<PairStatus, string> = {
  eligible: "Eligible",
  failed_validation: "Failed validation",
  insufficient_data: "Insufficient data",
  unsupported: "Unsupported",
  error: "Error",
};
const STATUSES = Object.keys(STATUS_LABEL) as PairStatus[];

type Tab = "overview" | "library" | "backtests" | "signals" | "positions" | "trades" | "accounts";
const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "library", label: "Strategy library" },
  { key: "backtests", label: "Backtests & grades" },
  { key: "signals", label: "Live signals" },
  { key: "positions", label: "Open positions" },
  { key: "trades", label: "Completed trades" },
  { key: "accounts", label: "Accounts & rankings" },
];

// -- formatting ------------------------------------------------------------------------------------

const usd = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${usd(v, dp)}`;
const big = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  const s = a >= 1e12 ? `${(a / 1e12).toFixed(2)}T` : a >= 1e9 ? `${(a / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(2)}M`
    : a >= 1e3 ? `${(a / 1e3).toFixed(1)}K` : a.toFixed(0);
  return `${v < 0 ? "−" : ""}$${s}`;
};
const pct = (v: number | null | undefined, dp = 1) => (v === null || v === undefined ? "—" : `${v.toFixed(dp)}%`);
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: dp });
const price = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  return v.toLocaleString("en-US", { maximumFractionDigits: a >= 1000 ? 2 : a >= 1 ? 4 : 6 });
};
const utc = (v: string | null | undefined) =>
  v
    ? `${new Date(v).toLocaleString("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })} UTC`
    : "—";
const ist = (v: string | null | undefined) =>
  v ? `${new Date(v).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })} IST` : "";
const tone = (v: number | null | undefined) => ((v ?? 0) > 0 ? "gain" : (v ?? 0) < 0 ? "loss" : "");
const errText = (e: unknown, what: string) => (e instanceof Error ? e.message : `Failed to load ${what}`);

// -- page ------------------------------------------------------------------------------------------

export default function CryptoTradingPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [pairId, setPairId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(async () => {
    try {
      setOv(await fetchOverview());
      setError(null);
    } catch (e) {
      setError(errText(e, "Crypto Trading"));
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setNonce((n) => n + 1);
    setRefreshing(false);
  }, [load]);

  const coins = useMemo(() => (ov?.universe?.selected ?? []).map((c) => ({ symbol: c.venue_symbol ?? "", coin: c.symbol })), [ov]);

  return (
    <div className="ct">
      <PageHeader
        onRefresh={refresh}
        refreshing={refreshing}
        crumb="Crypto Trading"
        title="Crypto Trading"
        subtitle="The ten largest cryptocurrencies, paper traded on Delta Exchange India's perpetuals by the Strategy Factory's and the Strategies module's strategies: one $10,000 account per strategy and coin, every pair backtested on the venue's own history first. Nothing here reaches a broker."
      />
      {error && <ErrorBanner message={error} onRetry={load} />}

      <DeskStrip ov={ov} onChanged={refresh} />

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "tab on" : "tab"} onClick={() => setTab(t.key)}>
            {t.label}
            {t.key === "positions" && ov ? <span className="count">{ov.open_positions}</span> : null}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab ov={ov} />}
      {tab === "library" && <LibraryTab key={`l${nonce}`} />}
      {tab === "backtests" && <BacktestsTab key={`b${nonce}`} coins={coins} onPair={setPairId} />}
      {tab === "signals" && <SignalsTab key={`s${nonce}`} coins={coins} onPair={setPairId} />}
      {tab === "positions" && <PositionsTab key={`p${nonce}`} coins={coins} status="OPEN" onPair={setPairId} />}
      {tab === "trades" && <PositionsTab key={`t${nonce}`} coins={coins} status="CLOSED" onPair={setPairId} />}
      {tab === "accounts" && <AccountsTab key={`a${nonce}`} coins={coins} onPair={setPairId} />}

      {pairId && <PairDrawer id={pairId} onClose={() => setPairId(null)} />}

      <style jsx global>{`
        .ct { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
        .ct .note { padding: 12px 16px; border-radius: 10px; background: var(--canvas-soft); border: 1px solid var(--panel-border);
                    font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
        .ct .note b { color: var(--text); }
        .ct .dim { color: var(--text-faint); }
        .ct .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .ct .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; min-width: 0; }
        .ct .t-label { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
        .ct .t-value { font-family: var(--font-display); font-weight: 800; font-size: 19px; margin-top: 6px; font-variant-numeric: tabular-nums; }
        .ct .t-sub { font-size: 11px; color: var(--text-faint); margin-top: 4px; line-height: 1.45; }
        .ct .tabs { display: flex; gap: 6px; flex-wrap: wrap; border-bottom: 1px solid var(--panel-border); padding-bottom: 8px; }
        .ct .tab { background: transparent; border: 1px solid transparent; color: var(--text-muted); padding: 7px 12px; border-radius: 8px;
                   font-size: 12.5px; font-weight: 700; cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
        .ct .tab.on { background: var(--brand-dim); border-color: rgba(var(--brand-rgb), 0.35); color: var(--brand); }
        .ct .count { font-size: 10.5px; padding: 1px 6px; border-radius: 10px; background: var(--canvas-soft); color: var(--text-muted); }
        .ct .controls { display: flex; gap: 8px; align-items: center; padding-bottom: 10px; flex-wrap: wrap; }
        .ct .controls select, .ct .controls input { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text);
                   padding: 6px 9px; border-radius: 8px; font-size: 12px; max-width: 100%; }
        .ct .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 6px 11px;
                    border-radius: 8px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
        .ct .chip.on { background: var(--brand-dim); border-color: rgba(var(--brand-rgb), 0.35); color: var(--brand); }
        .ct .btn { background: var(--brand); color: #fff; border: 0; padding: 8px 14px; border-radius: 8px; font-size: 12.5px; font-weight: 800; cursor: pointer; }
        .ct .btn.ghost { background: var(--canvas-soft); color: var(--text); border: 1px solid var(--panel-border); }
        .ct .btn.danger { background: var(--loss); }
        .ct .btn:disabled { opacity: 0.5; cursor: default; }
        .ct .empty { padding: 22px 20px; font-size: 13px; color: var(--text-faint); line-height: 1.5; }
        .ct .table-scroll { overflow-x: auto; max-height: 720px; overflow-y: auto; }
        .ct .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
        .ct .data-table th { text-align: right; padding: 9px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
                             color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); z-index: 1; }
        .ct .data-table td { padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--canvas-soft); vertical-align: top; }
        .ct .data-table .l { text-align: left; }
        .ct .data-table tr.click { cursor: pointer; }
        .ct .data-table tr.click:hover td { background: var(--canvas-soft); }
        .ct .wrap { white-space: normal; min-width: 220px; max-width: 460px; }
        .ct .sub { font-size: 10.5px; color: var(--text-faint); margin-top: 2px; }
        .ct .badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10.5px; font-weight: 700; background: var(--canvas-soft);
                     border: 1px solid var(--panel-border); color: var(--text-muted); white-space: nowrap; }
        .ct .badge.good { background: var(--gain-dim, rgba(16, 185, 129, 0.12)); color: var(--gain); border-color: transparent; }
        .ct .badge.bad { background: var(--loss-dim); color: var(--loss); border-color: transparent; }
        .ct .badge.warn { background: rgba(245, 158, 11, 0.14); color: #b45309; border-color: transparent; }
        .ct .gain { color: var(--gain); }
        .ct .loss { color: var(--loss); }
        .ct .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
        .ct .kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; font-size: 12.5px; line-height: 1.5; }
        .ct .kv dt { color: var(--text-muted); font-weight: 700; }
        .ct .kv dd { margin: 0; color: var(--text); white-space: normal; overflow-wrap: anywhere; }
        .ct .pager { display: flex; gap: 8px; align-items: center; justify-content: flex-end; padding-top: 10px; font-size: 12px; color: var(--text-muted); }
        .ct .drawer-bg { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); z-index: 60; display: flex; justify-content: flex-end; }
        .ct .drawer { width: min(980px, 100vw); height: 100%; overflow-y: auto; background: var(--canvas, var(--panel)); border-left: 1px solid var(--panel-border);
                      padding: 18px 16px 40px; display: flex; flex-direction: column; gap: 14px; }
        .ct .drawer h2 { margin: 0; font-size: 18px; }
        .ct .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .ct .spacer { flex: 1; }
        .ct .confirm { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 10px 12px; border-radius: 10px;
                       border: 1px solid var(--loss); background: var(--loss-dim); font-size: 12.5px; }
        .ct .confirm input { background: var(--panel); border: 1px solid var(--panel-border); color: var(--text); padding: 6px 9px; border-radius: 8px;
                             font-size: 12.5px; min-width: 220px; }
        @media (max-width: 640px) { .ct .t-value { font-size: 16px; } .ct .drawer { padding: 14px 12px 32px; } }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone: t }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${t ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
    </div>
  );
}

function StatusBadge({ s }: { s: PairStatus | string }) {
  const cls = s === "eligible" ? "badge good" : s === "failed_validation" ? "badge bad" : s === "insufficient_data" ? "badge warn" : "badge";
  return <span className={cls}>{STATUS_LABEL[s as PairStatus] ?? s}</span>;
}

function Pager({ offset, total, onPage }: { offset: number; total: number; onPage: (o: number) => void }) {
  if (total <= PAGE) return <div className="pager">{total.toLocaleString("en-US")} rows</div>;
  return (
    <div className="pager">
      <span>
        {(offset + 1).toLocaleString("en-US")}–{Math.min(offset + PAGE, total).toLocaleString("en-US")} of {total.toLocaleString("en-US")}
      </span>
      <button className="chip" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE))}>Previous</button>
      <button className="chip" disabled={offset + PAGE >= total} onClick={() => onPage(offset + PAGE)}>Next</button>
    </div>
  );
}

type CoinOpt = { symbol: string; coin: string };

function CoinSelect({ coins, value, onChange }: { coins: CoinOpt[]; value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Coin">
      <option value="">All coins</option>
      {coins.map((c) => <option key={c.symbol} value={c.symbol}>{c.coin}</option>)}
    </select>
  );
}

function TfSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Timeframe">
      <option value="">All timeframes</option>
      {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
    </select>
  );
}

function LibSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Library">
      <option value="">Both libraries</option>
      <option value="factory">Strategy Factory</option>
      <option value="strategies">Strategies module</option>
    </select>
  );
}

const libName = (l: string) => (l === "factory" ? "Strategy Factory" : "Strategies module");

// -- the desk strip: state and controls --------------------------------------------------------------

function DeskStrip({ ov, onChanged }: { ov: Overview | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [phrase, setPhrase] = useState("");
  const d = ov?.desk;
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(done);
      onChanged();
    } catch (e) {
      setMsg(errText(e, "the desk"));
    } finally {
      setBusy(false);
    }
  };
  const statusText = d ? (d.status === "running" ? "Running" : d.status === "paused" ? "Paused" : "Stopped") : "—";
  const lc = d?.last_cycle;
  const closed = lc ? Object.values(lc.closed ?? {}).reduce((a, b) => a + b, 0) : 0;
  return (
    <GlassPanel title="The desk">
      <div className="row">
        <div className="tiles" style={{ flex: "1 1 640px" }}>
          <Tile label="Desk" value={statusText} tone={d?.status === "running" ? "gain" : d ? "loss" : undefined}
                sub={d?.since ? `since ${utc(d.since)}${d.last_action ? ` · ${d.last_action}` : ""}` : "no state yet"} />
          <Tile label="Main Control" value={d ? (d.switch_on ? "ON" : "OFF") : "—"} tone={d && !d.switch_on ? "loss" : undefined}
                sub={d && !d.switch_on ? "no new entries; open positions still managed" : "entries allowed while running"} />
          <Tile label="Last cycle" value={d?.last_cycle_at ? utc(d.last_cycle_at) : "—"}
                sub={lc ? `${lc.pairs} pairs live · ${lc.signals} signals · ${lc.opened} opened · ${closed} closed · ${lc.ms} ms` : "the engine has not run yet"} />
        </div>
        <div className="row">
          {d?.status === "running" && <button className="btn ghost" disabled={busy} onClick={() => act(() => controlDesk("pause"), "Paused: no new entries; open positions are still managed.")}>Pause</button>}
          {d?.status === "paused" && <button className="btn" disabled={busy} onClick={() => act(() => controlDesk("resume"), "Resumed.")}>Resume</button>}
          {d?.status === "stopped" && <button className="btn" disabled={busy} onClick={() => act(() => controlDesk("start"), "Started.")}>Start</button>}
          <button className="btn danger" disabled={busy || !d} onClick={() => { setConfirming(true); setPhrase(""); }}>Reset…</button>
        </div>
      </div>
      {confirming && d && (
        <div className="confirm" style={{ marginTop: 12 }}>
          <span>
            Reset archives every position and signal, puts all {ov?.accounts.total.toLocaleString("en-US")} accounts back to $10,000 and stops the desk.
            Backtests and grades stay. Type <b>{d.reset_phrase}</b> to confirm:
          </span>
          <input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder={d.reset_phrase} aria-label="Reset confirmation" />
          <button className="btn danger" disabled={busy || phrase.trim() !== d.reset_phrase}
                  onClick={() => act(async () => { await resetDesk(phrase.trim()); setConfirming(false); }, "Reset done: every account is back to $10,000 and the desk is stopped.")}>
            Reset everything
          </button>
          <button className="btn ghost" onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      )}
      {msg && <div className="sub" style={{ marginTop: 8 }}>{msg}</div>}
    </GlassPanel>
  );
}

// -- overview ----------------------------------------------------------------------------------------

function OverviewTab({ ov }: { ov: Overview | null }) {
  const [uni, setUni] = useState<Universe | null>(null);
  useEffect(() => {
    fetchUniverse().then(setUni).catch(() => setUni(null));
  }, []);
  if (!ov) return <div className="empty">Loading…</div>;
  const m = ov.money;
  const equity = (m.cash ?? 0) + (m.unrealized ?? 0);
  const capital = (m.accounts ?? 0) * ov.accounts.capital_each;
  const counts = ov.sweep.counts ?? {};
  const eligible = counts.eligible ?? 0;
  const curve = ov.equity_curve.map((p) => ({ ts: p.ts, value: p.equity - p.capital }));
  const grid = ov.accounts.eligible_grid;
  const libs = ["factory", "strategies"] as const;
  return (
    <>
      <div className="tiles">
        <Tile label="Accounts" value={ov.accounts.total.toLocaleString("en-US")}
              sub={`one per strategy × coin · $${ov.accounts.capital_each.toLocaleString("en-US")} each`} />
        <Tile label="Eligible · trading" value={eligible.toLocaleString("en-US")}
              sub={`graded 3+ on crypto results · ${(m.halted ?? 0).toLocaleString("en-US")} halted by a limit`} />
        <Tile label="Open positions" value={ov.open_positions.toLocaleString("en-US")} sub={`${(m.traded ?? 0).toLocaleString("en-US")} accounts have traded`} />
        <Tile label="Desk P&L" value={signed(equity - capital)} tone={tone(equity - capital)}
              sub={`equity ${big(equity)} on ${big(capital)} (eligible + traded accounts)`} />
        <Tile label="Realised" value={signed(m.realized)} tone={tone(m.realized)}
              sub={`${(m.trades ?? 0).toLocaleString("en-US")} trades · ${m.trades ? Math.round(((m.wins ?? 0) / m.trades) * 100) : 0}% won`} />
        <Tile label="Unrealised" value={signed(m.unrealized)} tone={tone(m.unrealized)} sub="open positions at the venue's mark" />
        <Tile label="Costs paid" value={usd((m.fees ?? 0) + (m.funding ?? 0))}
              sub={`fees ${usd(m.fees)} · funding ${signed(-(m.funding ?? 0))}`} />
      </div>

      <GlassPanel title="Desk P&L, hourly" note="eligible and traded accounts together, realised + marked">
        {curve.length >= 2 ? <LineChart points={curve} color="var(--brand)" height={200} formatValue={(v) => signed(v, 0)} />
          : <div className="empty">The desk records one point an hour once it is running.</div>}
      </GlassPanel>

      <GlassPanel title={`The ten cryptocurrencies · ${ov.universe?.venue ?? ""}`}
                  note={`ranked ${utc(ov.universe?.ranking_as_of ?? ov.universe?.selected_at)} · selected ${utc(ov.universe?.selected_at)}`}>
        <div className="sub" style={{ paddingBottom: 8 }}>
          Ranking source: {ov.universe?.ranking_source ?? "—"}. Stablecoins, wrapped and staked tokens and tokenised assets are excluded before any
          market check; then each candidate must list a live USD perpetual on the venue, trade at least {big(ov.universe?.screens?.min_turnover_24h_usd)} a day with
          {" "}{big(ov.universe?.screens?.min_open_interest_usd)} open interest, and have {ov.universe?.screens?.min_history_days ?? 365}+ days of history.
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Rank</th><th className="l">Coin</th><th>Market cap</th><th>Price</th><th className="l">Venue contract</th>
                <th>24h turnover</th><th>Open interest</th><th>History</th><th title="half-spread + $10k impact on the live book, at least 3 bp">Slippage</th>
                <th>Funding</th><th>Eligible pairs</th><th>Open</th><th>Realised</th>
              </tr>
            </thead>
            <tbody>
              {(ov.universe?.selected ?? []).map((c) => {
                const g = grid[c.venue_symbol ?? ""] ?? {};
                const n = Object.values(g).reduce((a, b) => a + b, 0);
                const pc = ov.per_coin[c.venue_symbol ?? ""];
                return (
                  <tr key={c.id}>
                    <td>{c.rank}</td>
                    <td className="l"><b>{c.symbol}</b> <span className="dim">{c.name}</span></td>
                    <td>{big(c.market_cap_usd)}</td>
                    <td>{price(c.price_usd)}</td>
                    <td className="l">{c.venue_symbol}<div className="sub">{c.contract_value} {c.symbol} a contract</div></td>
                    <td>{big(c.turnover_24h_usd)}</td>
                    <td>{big(c.open_interest_usd)}</td>
                    <td>{c.history_days} d</td>
                    <td>{num(c.slippage_bps)} bp</td>
                    <td>{c.funding_interval_s ? `${c.funding_interval_s / 3600}h` : "—"}</td>
                    <td>{n}</td>
                    <td>{pc?.open ?? 0}</td>
                    <td className={tone(pc?.realized)}>{pc ? signed(pc.realized) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {uni?.candidates && (
          <details style={{ marginTop: 10 }}>
            <summary className="sub" style={{ cursor: "pointer" }}>Every candidate read, with the reason it was taken or left ({uni.candidates.length})</summary>
            <div className="table-scroll" style={{ maxHeight: 420 }}>
              <table className="data-table">
                <thead><tr><th>Rank</th><th className="l">Coin</th><th>Market cap</th><th className="l">Verdict</th></tr></thead>
                <tbody>
                  {uni.candidates.map((c) => (
                    <tr key={c.id}>
                      <td>{c.rank}</td>
                      <td className="l"><b>{c.symbol}</b> <span className="dim">{c.name}</span></td>
                      <td>{big(c.market_cap_usd)}</td>
                      <td className="l wrap">{c.verdict === "selected" ? <span className="badge good">selected</span> : <span className="dim">{c.reason}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </GlassPanel>

      <div className="grid2">
        <GlassPanel title="Every pair, by verdict" note={ov.sweep.imported_at ? `backtests imported ${utc(ov.sweep.imported_at)}` : ""}>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">Library</th>{STATUSES.map((s) => <th key={s}>{STATUS_LABEL[s]}</th>)}<th>Total</th></tr></thead>
              <tbody>
                {libs.map((l) => {
                  const r = ov.accounts.by_library[l] ?? ({} as Record<PairStatus, number>);
                  const tot = STATUSES.reduce((a, s) => a + (r[s] ?? 0), 0);
                  return (
                    <tr key={l}>
                      <td className="l">{libName(l)}</td>
                      {STATUSES.map((s) => <td key={s}>{(r[s] ?? 0).toLocaleString("en-US")}</td>)}
                      <td><b>{tot.toLocaleString("en-US")}</b></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="sub" style={{ paddingTop: 8 }}>
            Unsupported: cannot run honestly on this venue's data (options strategies, open-interest strategies, two-leg spreads). Insufficient data: too
            few bars, fewer than 20 trades, or a series whose bars mostly carry no trade. Failed validation: graded 1–2 on crypto results.
          </div>
        </GlassPanel>
        <GlassPanel title="Eligible pairs, coin × timeframe">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th className="l">Coin</th>{TIMEFRAMES.map((t) => <th key={t}>{t}</th>)}</tr></thead>
              <tbody>
                {(ov.universe?.selected ?? []).map((c) => (
                  <tr key={c.id}>
                    <td className="l">{c.symbol}</td>
                    {TIMEFRAMES.map((t) => {
                      const n = grid[c.venue_symbol ?? ""]?.[t] ?? 0;
                      return <td key={t} className={n ? "" : "dim"}>{n || "·"}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassPanel>
      </div>

      <GlassPanel title="How the desk works">
        <dl className="kv">
          {Object.entries(ov.method).map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>{k[0].toUpperCase() + k.slice(1)}</dt>
              <dd>{v}</dd>
            </div>
          ))}
          <dt>Sweep</dt>
          <dd>
            {ov.sweep.pairs ? `${ov.sweep.pairs.toLocaleString("en-US")} pairs of ${ov.sweep.strategies ?? "?"} strategies × 10 coins` : "—"}
            {ov.sweep.libraries ? ` · Strategies-module registry ${ov.sweep.libraries.strategies_registry}, Factory catalog ${ov.sweep.libraries.factory_catalog}` : ""}
            {ov.sweep.code_version ? ` · ${ov.sweep.code_version}` : ""}
          </dd>
        </dl>
      </GlassPanel>
    </>
  );
}

// -- the strategy library -----------------------------------------------------------------------------

function LibraryTab() {
  const [lib, setLib] = useState("");
  const [support, setSupport] = useState("");
  const [tf, setTf] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; rows: StrategyRow[]; counts: Record<string, Record<string, number>> } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const id = setTimeout(() => {
      fetchLibrary({ library: lib, support, timeframe: tf, q, offset, limit: PAGE })
        .then((d) => { setData(d); setError(null); })
        .catch((e) => setError(errText(e, "the library")));
    }, q ? 250 : 0);
    return () => clearTimeout(id);
  }, [lib, support, tf, q, offset]);
  const reset = (f: (v: string) => void) => (v: string) => { f(v); setOffset(0); };
  return (
    <GlassPanel title="The strategy library" note="read from where the strategies live: nothing copied">
      {error && <ErrorBanner message={error} />}
      {data?.counts && (
        <div className="sub" style={{ paddingBottom: 8 }}>
          {Object.entries(data.counts).map(([l, c]) => `${libName(l)}: ${Object.entries(c).map(([s, n]) => `${n} ${s}`).join(", ")}`).join(" · ")}
        </div>
      )}
      <div className="controls">
        <LibSelect value={lib} onChange={reset(setLib)} />
        <select value={support} onChange={(e) => reset(setSupport)(e.target.value)} aria-label="Support">
          <option value="">Any verdict</option>
          <option value="supported">Supported</option>
          <option value="adapted">Adapted</option>
          <option value="unsupported">Unsupported</option>
        </select>
        <TfSelect value={tf} onChange={reset(setTf)} />
        <input value={q} onChange={(e) => reset(setQ)(e.target.value)} placeholder="Search id, name or family" aria-label="Search" />
      </div>
      {!data ? <div className="empty">Loading…</div> : (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th className="l">Strategy</th><th className="l">Library</th><th className="l">Family</th><th>TF</th><th>HTF</th><th>R:R</th>
                  <th className="l">Regimes</th><th className="l">Crypto verdict</th></tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <FragmentRow key={r.strategy_id} r={r} open={open === r.strategy_id} onToggle={() => setOpen(open === r.strategy_id ? null : r.strategy_id)} />
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} total={data.total} onPage={setOffset} />
        </>
      )}
    </GlassPanel>
  );
}

function FragmentRow({ r, open, onToggle }: { r: StrategyRow; open: boolean; onToggle: () => void }) {
  const verdict = r.support === "unsupported" ? "badge" : r.support === "adapted" ? "badge warn" : "badge good";
  return (
    <>
      <tr className="click" onClick={onToggle}>
        <td className="l"><b>{r.name}</b><div className="sub">{r.strategy_id}</div></td>
        <td className="l">{libName(r.library)}</td>
        <td className="l">{r.family}</td>
        <td>{r.timeframe}</td>
        <td>{r.htf ?? "—"}</td>
        <td>{r.rules.risk_reward ?? "—"}</td>
        <td className="l">{(r.rules.regimes ?? []).join(", ")}</td>
        <td className="l"><span className={verdict}>{r.support}</span></td>
      </tr>
      {open && (
        <tr>
          <td colSpan={8} className="l" style={{ whiteSpace: "normal" }}>
            <StrategyRules r={r} />
          </td>
        </tr>
      )}
    </>
  );
}

function StrategyRules({ r }: { r: StrategyRow }) {
  const params = Object.entries(r.rules.params ?? {});
  return (
    <dl className="kv">
      {r.rules.hypothesis && (<><dt>Idea</dt><dd>{r.rules.hypothesis}</dd></>)}
      {r.rules.entry && (<><dt>Entry</dt><dd>{r.rules.entry}</dd></>)}
      {r.rules.stop && (<><dt>Stop</dt><dd>{r.rules.stop}</dd></>)}
      {r.rules.target && (<><dt>Target</dt><dd>{r.rules.target}</dd></>)}
      {r.rules.exit && (<><dt>Exit</dt><dd>{r.rules.exit}</dd></>)}
      {r.rules.sizing && (<><dt>Sizing</dt><dd>{r.rules.sizing}</dd></>)}
      {r.rules.confirmations && r.rules.confirmations.length > 0 && (
        <><dt>Confirmations</dt><dd>{r.rules.confirmations.map((c) => c.name).join(", ")}</dd></>
      )}
      {params.length > 0 && (<><dt>Parameters</dt><dd>{params.map(([k, v]) => `${k} ${v}`).join(" · ")}</dd></>)}
      <dt>On crypto</dt>
      <dd>{r.support === "unsupported" ? r.unsupported_reason : r.adaptation}{r.instrument ? ` Instrument: ${r.instrument}.` : ""}</dd>
    </dl>
  );
}

// -- backtests ------------------------------------------------------------------------------------------

function BacktestsTab({ coins, onPair }: { coins: CoinOpt[]; onPair: (id: string) => void }) {
  const [f, setF] = useState({ status: "", symbol: "", timeframe: "", library: "", min_grade: "", q: "", sort: "grade" });
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; rows: BacktestRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const id = setTimeout(() => {
      fetchBacktests({ ...f, offset, limit: PAGE })
        .then((d) => { setData(d); setError(null); })
        .catch((e) => setError(errText(e, "the backtests")));
    }, f.q ? 250 : 0);
    return () => clearTimeout(id);
  }, [f, offset]);
  const set = (k: keyof typeof f) => (v: string) => { setF((x) => ({ ...x, [k]: v })); setOffset(0); };
  return (
    <GlassPanel title="Backtests and grades" note="one per strategy × coin, on the venue's own history">
      {error && <ErrorBanner message={error} />}
      <div className="controls">
        <select value={f.status} onChange={(e) => set("status")(e.target.value)} aria-label="Status">
          <option value="">Every verdict</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <CoinSelect coins={coins} value={f.symbol} onChange={set("symbol")} />
        <TfSelect value={f.timeframe} onChange={set("timeframe")} />
        <LibSelect value={f.library} onChange={set("library")} />
        <select value={f.min_grade} onChange={(e) => set("min_grade")(e.target.value)} aria-label="Minimum grade">
          <option value="">Any grade</option>
          {[5, 4, 3, 2].map((g) => <option key={g} value={g}>Grade {g}+</option>)}
        </select>
        <select value={f.sort} onChange={(e) => set("sort")(e.target.value)} aria-label="Sort">
          <option value="grade">Sort: grade</option>
          <option value="net">{"Sort: net P&L"}</option>
          <option value="pf">Sort: profit factor</option>
          <option value="oos">Sort: out-of-sample net</option>
          <option value="sharpe">Sort: Sharpe</option>
          <option value="trades">Sort: trades</option>
          <option value="dd">Sort: smallest drawdown</option>
        </select>
        <input value={f.q} onChange={(e) => set("q")(e.target.value)} placeholder="Search strategy" aria-label="Search" />
      </div>
      {!data ? <div className="empty">Loading…</div> : !data.rows.length ? <div className="empty">No pair matches these filters.</div> : (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Strategy</th><th className="l">Coin</th><th>TF</th><th className="l">Verdict</th><th>Grade</th><th>Trades</th>
                  <th>Net</th><th>PF</th><th>Win</th><th>Max DD</th><th title="the last 30% of trades in time">Out of sample</th><th>Funding</th>
                  <th>Sharpe</th><th className="l">Why</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.pair_id} className="click" onClick={() => onPair(r.pair_id)}>
                    <td className="l"><b>{r.name}</b><div className="sub">{r.strategy_id} · {libName(r.library)}</div></td>
                    <td className="l">{r.coin}</td>
                    <td>{r.timeframe}</td>
                    <td className="l"><StatusBadge s={r.status} /></td>
                    <td>{r.grade ?? "—"}</td>
                    <td>{r.overall?.trades ?? "—"}</td>
                    <td className={tone(r.overall?.net_pnl)}>{r.overall ? signed(r.overall.net_pnl, 0) : "—"}</td>
                    <td>{num(r.overall?.profit_factor)}</td>
                    <td>{r.overall?.win_rate !== undefined ? pct(r.overall.win_rate * 100, 0) : "—"}</td>
                    <td>{pct(r.overall?.max_drawdown_pct)}</td>
                    <td className={tone(r.out_of_sample?.net_pnl)}>
                      {r.out_of_sample ? signed(r.out_of_sample.net_pnl, 0) : "—"}
                      {r.out_of_sample && <div className="sub">{r.out_of_sample.trades} trades</div>}
                    </td>
                    <td>{r.funding_total !== undefined ? signed(-r.funding_total, 0) : "—"}</td>
                    <td>{num(r.overall?.sharpe)}</td>
                    <td className="l wrap dim">{r.status_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} total={data.total} onPage={setOffset} />
        </>
      )}
    </GlassPanel>
  );
}

// -- live signals -------------------------------------------------------------------------------------

function SignalsTab({ coins, onPair }: { coins: CoinOpt[]; onPair: (id: string) => void }) {
  const [symbol, setSymbol] = useState("");
  const [taken, setTaken] = useState<"" | "true" | "false">("");
  const [rows, setRows] = useState<Signal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchSignals({ symbol, taken: taken === "" ? undefined : taken === "true", limit: 300 })
      .then((d) => { setRows(d); setError(null); })
      .catch((e) => setError(errText(e, "the signals")));
  }, [symbol, taken]);
  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);
  return (
    <GlassPanel title="Live signal feed" note="every signal an eligible pair produced on a bar that had just closed (kept 14 days)">
      {error && <ErrorBanner message={error} onRetry={load} />}
      <div className="controls">
        <CoinSelect coins={coins} value={symbol} onChange={setSymbol} />
        <button className={taken === "" ? "chip on" : "chip"} onClick={() => setTaken("")}>All</button>
        <button className={taken === "true" ? "chip on" : "chip"} onClick={() => setTaken("true")}>Taken</button>
        <button className={taken === "false" ? "chip on" : "chip"} onClick={() => setTaken("false")}>Not taken</button>
      </div>
      {!rows ? <div className="empty">Loading…</div> : !rows.length ? (
        <div className="empty">No signal yet. Eligible pairs signal only when their own setup appears on a bar that has just closed.</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr><th className="l">When</th><th className="l">Strategy</th><th className="l">Coin</th><th>TF</th><th>Side</th>
                <th title="the signal's own reference">Entry ref</th><th>Stop</th><th>Target</th><th className="l">Outcome</th><th>Fill</th></tr>
            </thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={`${s.pair_id}${s.at}${i}`} className="click" onClick={() => onPair(s.pair_id)}>
                  <td className="l" title={ist(s.at)}>{utc(s.at)}<div className="sub">bar {utc(s.bar_ts)}</div></td>
                  <td className="l"><b>{s.name ?? s.strategy_id}</b><div className="sub">{s.strategy_id}</div></td>
                  <td className="l">{s.coin}</td>
                  <td>{s.timeframe}</td>
                  <td><span className={s.side === "BUY" ? "badge good" : "badge bad"}>{s.side === "BUY" ? "LONG" : "SHORT"}</span></td>
                  <td>{price(s.entry_ref)}</td>
                  <td>{price(s.stop)}</td>
                  <td>{price(s.target)}</td>
                  <td className="l wrap">{s.outcome.startsWith("not taken") ? <span className="dim">{s.outcome}</span> : <b>{s.outcome}</b>}</td>
                  <td>{s.fill_px ? `${price(s.fill_px)} × ${s.contracts}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassPanel>
  );
}

// -- positions and completed trades --------------------------------------------------------------------

function PositionsTab({ coins, status, onPair }: { coins: CoinOpt[]; status: "OPEN" | "CLOSED"; onPair: (id: string) => void }) {
  const [symbol, setSymbol] = useState("");
  const [lib, setLib] = useState("");
  const [rows, setRows] = useState<Position[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchPositions({ status, symbol, library: lib, limit: 500 })
      .then((d) => { setRows(d); setError(null); })
      .catch((e) => setError(errText(e, "the positions")));
  }, [status, symbol, lib]);
  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);
  const open = status === "OPEN";
  const totals = useMemo(() => {
    const r = rows ?? [];
    return {
      pnl: r.reduce((a, p) => a + (open ? p.unrealized_pnl ?? 0 : p.net_pnl ?? 0), 0),
      notional: r.reduce((a, p) => a + (p.notional_usd ?? 0), 0),
      fees: r.reduce((a, p) => a + (p.entry_fee ?? 0) + (p.exit_fee ?? 0), 0),
      funding: r.reduce((a, p) => a + (p.funding_paid ?? 0), 0),
      wins: r.filter((p) => (p.net_pnl ?? 0) > 0).length,
    };
  }, [rows, open]);
  return (
    <GlassPanel title={open ? "Open positions" : "Completed trades"}
                note={open ? "marked at the venue's mark price every minute" : "the latest 500"}>
      {error && <ErrorBanner message={error} onRetry={load} />}
      <div className="controls">
        <CoinSelect coins={coins} value={symbol} onChange={setSymbol} />
        <LibSelect value={lib} onChange={setLib} />
        {rows && rows.length > 0 && (
          <span className="sub">
            {rows.length} · {open ? "unrealised" : "net"} <span className={tone(totals.pnl)}>{signed(totals.pnl)}</span> · notional {big(totals.notional)} · fees {usd(totals.fees)} ·
            {" "}funding {signed(-totals.funding)}{!open && rows.length ? ` · ${Math.round((totals.wins / rows.length) * 100)}% won` : ""}
          </span>
        )}
      </div>
      {!rows ? <div className="empty">Loading…</div> : !rows.length ? (
        <div className="empty">{open ? "No position is open." : "No trade has completed yet."}</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              {open ? (
                <tr><th className="l">Strategy</th><th className="l">Coin</th><th>TF</th><th>Side</th><th>Contracts</th><th>Entry</th><th>Mark</th>
                  <th>Stop</th><th>Target</th><th title="isolated margin at 1x">Liquidation</th><th>Notional · margin</th><th>Funding</th>
                  <th>Unrealised</th><th className="l">Opened</th><th>Held</th></tr>
              ) : (
                <tr><th className="l">Strategy</th><th className="l">Coin</th><th>TF</th><th>Side</th><th>Contracts</th><th>Entry → exit</th>
                  <th className="l">Exit</th><th className="l">Opened → closed</th><th>Fees</th><th>Funding</th><th>Net</th><th>R</th></tr>
              )}
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p._id} className="click" onClick={() => onPair(p.pair_id)}>
                  <td className="l"><b>{p.name ?? p.strategy_id}</b><div className="sub">{p.strategy_id}</div></td>
                  <td className="l">{p.coin}</td>
                  <td>{p.timeframe}</td>
                  <td><span className={p.side === "BUY" ? "badge good" : "badge bad"}>{p.direction.toUpperCase()}</span></td>
                  <td>{p.contracts.toLocaleString("en-US")}<div className="sub">{num(p.qty_coin, 6)} {p.coin}</div></td>
                  {open ? (
                    <>
                      <td title={p.entry_basis}>{price(p.entry_px)}</td>
                      <td>{price(p.mark)}</td>
                      <td>{price(p.stop)}</td>
                      <td>{price(p.target)}</td>
                      <td className="dim">{price(p.liq_px)}</td>
                      <td>{big(p.notional_usd)}<div className="sub">margin {big(p.margin_usd)} · {p.leverage}x</div></td>
                      <td>{signed(-p.funding_paid)}<div className="sub">{p.funding_exchanges} exchanges</div></td>
                      <td className={tone(p.unrealized_pnl)}>{signed(p.unrealized_pnl)}</td>
                      <td className="l dim" title={ist(p.entry_ts)}>{utc(p.entry_ts)}</td>
                      <td>{p.max_hold_bars ? `${p.bars_held ?? 0} / ${p.max_hold_bars} bars` : "—"}</td>
                    </>
                  ) : (
                    <>
                      <td>{price(p.entry_px)} → {price(p.exit_px)}</td>
                      <td className="l"><span className={p.exit_reason === "stoploss" || p.exit_reason === "liquidation" ? "badge bad" : p.exit_reason === "target" ? "badge good" : "badge"}>{p.exit_reason}</span>
                        <div className="sub">{p.exit_basis}</div></td>
                      <td className="l dim" title={`${ist(p.entry_ts)} → ${ist(p.exit_ts)}`}>{utc(p.entry_ts)}<div className="sub">→ {utc(p.exit_ts)}</div></td>
                      <td className="loss">{usd(-((p.entry_fee ?? 0) + (p.exit_fee ?? 0)))}</td>
                      <td>{signed(-p.funding_paid)}</td>
                      <td className={tone(p.net_pnl)}>{signed(p.net_pnl)}</td>
                      <td>{num(p.r_multiple)}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassPanel>
  );
}

// -- accounts and rankings -----------------------------------------------------------------------------

function AccountsTab({ coins, onPair }: { coins: CoinOpt[]; onPair: (id: string) => void }) {
  const [f, setF] = useState({ trading: "true", status: "", symbol: "", timeframe: "", library: "", min_grade: "", q: "", traded: "", sort: "equity" });
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; rows: AccountRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchAccounts({ ...f, trading: f.trading === "" ? undefined : f.trading === "true", traded: f.traded ? true : undefined, offset, limit: PAGE })
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(errText(e, "the accounts")));
  }, [f, offset]);
  useEffect(() => {
    const id = setTimeout(load, f.q ? 250 : 0);
    const iv = setInterval(load, REFRESH_MS);
    return () => { clearTimeout(id); clearInterval(iv); };
  }, [load, f.q]);
  const set = (k: keyof typeof f) => (v: string) => { setF((x) => ({ ...x, [k]: v })); setOffset(0); };
  return (
    <GlassPanel title="Accounts and rankings" note="every pair has its own $10,000; only eligible pairs trade">
      {error && <ErrorBanner message={error} onRetry={load} />}
      <div className="controls">
        <button className={f.trading === "true" ? "chip on" : "chip"} onClick={() => set("trading")("true")}>Trading (eligible)</button>
        <button className={f.trading === "" ? "chip on" : "chip"} onClick={() => set("trading")("")}>All accounts</button>
        <button className={f.traded ? "chip on" : "chip"} onClick={() => set("traded")(f.traded ? "" : "1")}>Has traded</button>
        <select value={f.status} onChange={(e) => set("status")(e.target.value)} aria-label="Status">
          <option value="">Every verdict</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <CoinSelect coins={coins} value={f.symbol} onChange={set("symbol")} />
        <TfSelect value={f.timeframe} onChange={set("timeframe")} />
        <LibSelect value={f.library} onChange={set("library")} />
        <select value={f.sort} onChange={(e) => set("sort")(e.target.value)} aria-label="Rank by">
          <option value="equity">Rank: equity</option>
          <option value="realized">{"Rank: realised P&L"}</option>
          <option value="worst">Rank: worst equity</option>
          <option value="trades">Rank: trades</option>
          <option value="grade">Rank: backtest grade</option>
          <option value="drawdown">Rank: deepest drawdown</option>
          <option value="costs">Rank: fees paid</option>
        </select>
        <input value={f.q} onChange={(e) => set("q")(e.target.value)} placeholder="Search strategy" aria-label="Search" />
      </div>
      {!data ? <div className="empty">Loading…</div> : !data.rows.length ? <div className="empty">No account matches these filters.</div> : (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>#</th><th className="l">Strategy</th><th className="l">Coin</th><th>TF</th><th className="l">Verdict</th><th>Equity</th>
                  <th>Return</th><th>Realised</th><th>Unrealised</th><th>Fees · funding</th><th>Trades</th><th>Win</th><th>PF</th><th>Max DD</th>
                  <th title="the pair's crypto backtest">Backtest</th><th className="l">State</th></tr>
              </thead>
              <tbody>
                {data.rows.map((a, i) => (
                  <tr key={a._id} className="click" onClick={() => onPair(a._id)}>
                    <td>{offset + i + 1}</td>
                    <td className="l"><b>{a.name}</b><div className="sub">{a.strategy_id}</div></td>
                    <td className="l">{a.coin}</td>
                    <td>{a.timeframe}</td>
                    <td className="l"><StatusBadge s={a.status} />{a.grade ? <span className="sub"> grade {a.grade}</span> : null}</td>
                    <td>{usd(a.equity ?? a.cash)}</td>
                    <td className={tone(a.return_pct)}>{a.return_pct > 0 ? "+" : ""}{pct(a.return_pct, 2)}</td>
                    <td className={tone(a.realized_pnl)}>{signed(a.realized_pnl)}</td>
                    <td className={tone(a.unrealized_pnl)}>{a.open_position_id ? signed(a.unrealized_pnl) : "—"}</td>
                    <td>{usd(a.fees)}<div className="sub">funding {signed(-(a.funding ?? 0))}</div></td>
                    <td>{a.trades}</td>
                    <td>{a.win_rate !== null ? pct(a.win_rate * 100, 0) : "—"}</td>
                    <td>{num(a.profit_factor)}</td>
                    <td>{pct(a.max_drawdown_pct)}</td>
                    <td className={tone(a.backtest?.net_pnl)}>{a.backtest ? signed(a.backtest.net_pnl, 0) : "—"}
                      {a.backtest && <div className="sub">{a.backtest.trades} trades · PF {num(a.backtest.profit_factor)}</div>}</td>
                    <td className="l wrap dim">{a.halt ? a.halt.reason : a.open_position_id ? "in a position" : a.eligible ? "flat, waiting for a signal" : "not trading"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} total={data.total} onPage={setOffset} />
        </>
      )}
    </GlassPanel>
  );
}

// -- one pair --------------------------------------------------------------------------------------------

function PairDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [d, setD] = useState<PairDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetchPair(id).then((x) => { setD(x); setError(null); }).catch((e) => setError(errText(e, "the pair")));
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [id, onClose]);
  const bt = d?.backtest;
  const acc = d?.account;
  const btCurve = (bt?.equity_curve ?? []).map(([t, v]) => ({ ts: new Date(t * 1000).toISOString(), value: v }));
  const liveCurve = (d?.equity_curve ?? []).filter(([t]) => !!t).map(([t, v]) => ({ ts: t, value: v }));
  const M = ({ label, m }: { label: string; m?: BacktestRow["overall"] }) => (
    <tr>
      <td className="l">{label}</td>
      <td>{m?.trades ?? "—"}</td>
      <td className={tone(m?.net_pnl)}>{m ? signed(m.net_pnl, 0) : "—"}</td>
      <td>{num(m?.profit_factor)}</td>
      <td>{m?.win_rate !== undefined ? pct(m.win_rate * 100, 0) : "—"}</td>
      <td>{pct(m?.max_drawdown_pct)}</td>
      <td>{num(m?.sharpe)}</td>
      <td>{m?.total_costs !== undefined ? usd(m.total_costs, 0) : "—"}</td>
    </tr>
  );
  return (
    <div className="drawer-bg" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Strategy and coin">
        <div className="row">
          <h2>{bt?.name ?? acc?.name ?? id}</h2>
          <span className="spacer" />
          <button className="btn ghost" onClick={onClose}>Close</button>
        </div>
        {error && <ErrorBanner message={error} />}
        {!d ? <div className="empty">Loading…</div> : (
          <>
            <div className="row">
              <StatusBadge s={bt?.status ?? acc?.status ?? "error"} />
              {bt?.grade ? <span className="badge">grade {bt.grade}</span> : null}
              <span className="sub">{bt?.coin ?? acc?.coin} · {bt?.timeframe ?? acc?.timeframe} · {libName(bt?.library ?? acc?.library ?? "factory")} · {bt?.strategy_id ?? acc?.strategy_id}</span>
            </div>
            <div className="note">{bt?.status_reason ?? acc?.status_reason}{bt?.grade_reasons?.length ? ` · ${bt.grade_reasons.join(" · ")}` : ""}</div>

            <div className="tiles">
              <Tile label="Account equity" value={usd(acc?.equity ?? acc?.cash)} tone={tone((acc?.equity ?? acc?.cash ?? 10000) - 10000)}
                    sub={acc ? `${signed((acc.equity ?? acc.cash) - 10000)} on $10,000` : ""} />
              <Tile label="Realised" value={signed(acc?.realized_pnl)} tone={tone(acc?.realized_pnl)}
                    sub={acc ? `${acc.trades} trades · ${acc.wins} won · ${acc.losses} lost` : ""} />
              <Tile label="Costs" value={usd((acc?.fees ?? 0) + (acc?.funding ?? 0))} sub={`fees ${usd(acc?.fees)} · funding ${signed(-(acc?.funding ?? 0))}`} />
              <Tile label="State" value={acc?.halt ? "Halted" : acc?.open_position_id ? "In a position" : acc?.eligible ? "Flat" : "Not trading"}
                    sub={acc?.halt?.reason ?? (acc?.eligible ? "trades its own signals" : "only eligible pairs trade")} />
            </div>

            {liveCurve.length >= 2 && (
              <GlassPanel title="Paper account equity">
                <LineChart points={liveCurve} color="var(--brand)" height={170} formatValue={(v) => usd(v, 0)} />
              </GlassPanel>
            )}

            {bt?.overall && (
              <GlassPanel title="Crypto backtest" note={`${utc(bt.window_start)} → ${utc(bt.window_end)} · ${bt.engine ?? ""}`}>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead><tr><th className="l">Sample</th><th>Trades</th><th>Net</th><th>PF</th><th>Win</th><th>Max DD</th><th>Sharpe</th><th>Costs</th></tr></thead>
                    <tbody>
                      <M label="All trades" m={bt.overall} />
                      <M label="In sample (first 70%)" m={bt.in_sample} />
                      <M label="Out of sample (last 30%)" m={bt.out_of_sample} />
                    </tbody>
                  </table>
                </div>
                <div className="sub" style={{ paddingTop: 6 }}>
                  {bt.bars_tested?.toLocaleString("en-US")} bars over {bt.span_days} days · slippage {num(bt.slippage_bps)} bp a fill · funding {signed(-(bt.funding_total ?? 0))} over
                  {" "}{bt.funding_exchanges ?? 0} exchanges · {bt.no_trade_bar_pct !== undefined ? `${bt.no_trade_bar_pct}% no-trade bars` : ""}
                  {bt.unit_contracts && bt.unit_contracts > 1 ? ` · unit ${bt.unit_contracts} contracts` : ""}
                </div>
                {btCurve.length >= 2 && <LineChart points={btCurve} color="var(--brand)" height={170} formatValue={(v) => usd(v, 0)} />}
              </GlassPanel>
            )}

            {d.strategy && (
              <GlassPanel title="The strategy, as defined">
                <StrategyRules r={d.strategy} />
              </GlassPanel>
            )}

            <GlassPanel title="Paper positions" note="the latest 200">
              {!d.positions.length ? <div className="empty">{acc?.eligible ? "No position yet: it trades when its own setup appears." : "This pair does not trade."}</div> : (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead><tr><th className="l">Opened</th><th>Side</th><th>Contracts</th><th>Entry</th><th>Stop · target</th><th>Exit</th><th className="l">Reason</th><th>Net / unrealised</th></tr></thead>
                    <tbody>
                      {d.positions.map((p) => (
                        <tr key={p._id}>
                          <td className="l dim">{utc(p.entry_ts)}</td>
                          <td>{p.direction}</td>
                          <td>{p.contracts}</td>
                          <td>{price(p.entry_px)}</td>
                          <td>{price(p.stop)} · {price(p.target)}</td>
                          <td>{p.status === "OPEN" ? `mark ${price(p.mark)}` : price(p.exit_px)}</td>
                          <td className="l">{p.status === "OPEN" ? "open" : p.exit_reason}</td>
                          <td className={tone(p.status === "OPEN" ? p.unrealized_pnl : p.net_pnl)}>{signed(p.status === "OPEN" ? p.unrealized_pnl : p.net_pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </GlassPanel>

            {bt?.trades_sample && bt.trades_sample.length > 0 && (
              <GlassPanel title="Backtest trades" note={`the latest ${bt.trades_sample.length}`}>
                <div className="table-scroll" style={{ maxHeight: 360 }}>
                  <table className="data-table">
                    <thead><tr><th className="l">Entry → exit</th><th>Side</th><th>Entry</th><th>Exit</th><th className="l">Reason</th><th>Costs</th><th>Net</th><th>R</th></tr></thead>
                    <tbody>
                      {bt.trades_sample.slice().reverse().map((t, i) => (
                        <tr key={`${t.entry_ts}${i}`}>
                          <td className="l dim">{utc(t.entry_ts)}<div className="sub">→ {utc(t.exit_ts)}</div></td>
                          <td>{t.side === "BUY" ? "long" : "short"}</td>
                          <td>{price(t.entry)}</td>
                          <td>{price(t.exit)}</td>
                          <td className="l">{t.reason}</td>
                          <td>{usd(t.costs)}</td>
                          <td className={tone(t.net)}>{signed(t.net)}</td>
                          <td>{num(t.r)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </GlassPanel>
            )}
          </>
        )}
      </div>
    </div>
  );
}
