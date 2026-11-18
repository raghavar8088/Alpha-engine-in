"use client";

// The Gold Desk's Strategy Factory top-25 accounts (18 Nov 2026): a ₹2 lakh paper account for each of the 546 board's
// Rank 1-25, shown in five sets as the owner asked - Top 1-5, 5-10, 10-15, 15-20 and 20-25 (Rank 1-5, 6-10 ... 21-25).
// They copy the Strategy Factory tab's own gold trades at their own size (backend app/services/gold_sf_books.py).
// Paper only: nothing here can place an order.
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { DAY_COL_TITLES, dayCell, istDaysSince, pctCell, perDayTraded, toneOf } from "../../lib/dayReturns";

type PickInfo = { rank: number; strategy_id: string; name: string; timeframe: string; family: string; score: number;
  trades: number; win_rate: number; profit_factor: number | null; net_usd: number; t: number | null; bp: number | null };
type Money = { capital: number; equity: number; realized_pnl: number; unrealized_pnl: number; deployed: number;
  available_cash: number; fees: number; gross_pnl: number; open_positions: number; closed_positions: number; wins: number;
  win_rate: number | null; roi_pct: number };
type Account = Money & { id: string; label: string; rank: number; band: string; strategy_id: string; name: string;
  timeframe: string; family: string; pick: PickInfo; days_traded: number; started_at: string | null;
  last_close_at: string | null; skipped: Record<string, number>; voided: number };
type Total = Money & { accounts: number; traded: number };
type BandRow = { band: string; lo: number; hi: number; label: string; ranks: string; accounts: string[]; total: Total };
export type SfOverview = { mode: string; enabled: boolean; tick_seconds: number; tab: string; instrument: string;
  picked_at: string; board: string; capital_each: number; bands: BandRow[]; total: Total; accounts: Account[];
  usd_inr: { rate: number | null; asof: string | null; at: string | null } | null; notes: string[] };
export type SfCopy = { position_id: string; account: string; rank: number; band: string; strategy_id: string;
  strategy_name: string; timeframe: string; side: "BUY" | "SELL"; qty: number; ounces: number; entry_px: number;
  exit_px: number | null; ltp: number | null; usd_inr: number | null; capital_deployed: number; unrealized_pnl: number;
  realized_pnl: number | null; gross_pnl: number | null; fees: number | null; exit_reason: string | null; status: string;
  opened_at: string; closed_at: string | null };

// The frozen 25 (gold_sf_books.PICKS), shown only while the server has not been updated with the accounts:
// [rank, strategy id, name, Rank score, closed trades, net $ on the tab's $1,111 sleeve] at 22:21 IST on 18 Nov 2026.
const ROSTER: [number, string, string, number, number, number][] = [
  [1, "SF0181", "Three Soldiers / Crows · 45m", 82.7, 41, 112.06], [2, "SF0020", "Triple Top / Bottom · 30m", 81.8, 41, 131.4],
  [3, "SF0182", "Three Soldiers / Crows · 1h", 79.9, 33, 69.73], [4, "SF0219", "Donchian Breakout (slow) · 15m", 79.6, 39, 78.32],
  [5, "SF0013", "Double Top / Bottom · 45m", 79.3, 38, 97.61], [6, "SF0346", "Rectangle / Trading Range Break · 30m", 78.7, 23, 116.33],
  [7, "SF0331", "Trend Pullback to EMA · 45m", 76.1, 30, 73.13], [8, "SF0245", "Prior Session High/Low Break · 45m", 75.8, 28, 91.94],
  [9, "SF0021", "Triple Top / Bottom · 45m", 75.8, 26, 88.87], [10, "SF0324", "Opening Range Breakout · 45m", 75.4, 46, 62.94],
  [11, "SF0213", "Donchian Breakout (fast) · 45m", 74.8, 23, 73.82], [12, "SF0022", "Triple Top / Bottom · 1h", 73.4, 27, 79.89],
  [13, "SF0206", "Heikin Ashi Flip · 1h", 72.8, 32, 44.66], [14, "SF0090", "Diamond · 5m", 72.6, 36, 24.78],
  [15, "SF0251", "Round Number Break · 30m", 71.7, 18, 41.28], [16, "SF0370", "RSI Trend Regime (40/60) · 30m", 71.0, 18, 99.31],
  [17, "SF0347", "Rectangle / Trading Range Break · 45m", 70.8, 17, 108.05],
  [18, "SF0243", "Prior Session High/Low Break · 15m", 69.9, 75, 60.93], [19, "SF0282", "ATR Expansion Thrust · 15m", 69.3, 51, 20.37],
  [20, "SF0542", "Rectangle + Volume + ATR · 30m", 69.2, 18, 85.29], [21, "SF0466", "Breakout + Volume + HTF Trend · 30m", 68.2, 25, 41.98],
  [22, "SF0426", "Parabolic SAR Flip · 30m", 67.8, 23, 72.42], [23, "SF0205", "Heikin Ashi Flip · 45m", 67.8, 31, 34.15],
  [24, "SF0476", "Pullback + EMA + RSI + VWAP · 1h", 67.7, 19, 85.42], [25, "SF0332", "Trend Pullback to EMA · 1h", 67.7, 19, 77.47],
];
const SETS = [[1, 5], [6, 10], [11, 15], [16, 20], [21, 25]].map(([lo, hi]) => ({
  key: `${lo}-${hi}`, label: `Top ${lo === 1 ? 1 : lo - 1}-${hi}`, ranks: `Rank ${lo}-${hi}`, lo, hi }));

const inr = (v: number | null | undefined, signed = false) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const d = a < 100 ? 2 : 0;
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return `${sign}₹${a.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
};
const usd = (v: number | null | undefined, signed = false) =>
  v === null || v === undefined ? "—"
    : `${signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const ist = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: false });
const WHY: Record<string, string> = { target: "Target", stoploss: "Stop", max_hold: "Hold limit", void: "Void (no price)" };

export default function GoldSfBooksPanel() {
  const [ov, setOv] = useState<SfOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [set, setSet] = useState<string>("all");
  const [acct, setAcct] = useState<string | null>(null);
  const [open, setOpen] = useState<SfCopy[]>([]);
  const [closed, setClosed] = useState<SfCopy[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOv(await apiFetch("/api/gold-desk/sf-books"));
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read the accounts.");
    }
  }, []);
  const scope = acct ? `account=${encodeURIComponent(acct)}` : set !== "all" ? `band=${encodeURIComponent(set)}` : "";
  const loadPositions = useCallback(async () => {
    try {
      const q = scope ? `${scope}&` : "";
      const [o, c] = await Promise.all([
        apiFetch(`/api/gold-desk/sf-books/positions?${q}status=OPEN`),
        apiFetch(`/api/gold-desk/sf-books/positions?${q}status=CLOSED&limit=200`),
      ]);
      setOpen(o.positions ?? []);
      setClosed(c.positions ?? []);
    } catch {
      /* the overview's error explains a dead backend; a stale table is better than none */
    }
  }, [scope]);
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    if (!ov) return;
    loadPositions();
    const t = setInterval(loadPositions, 30000);
    return () => clearInterval(t);
  }, [loadPositions, ov]);

  const runNow = async () => {
    setBusy(true);
    setNote(null);
    try {
      const r = await apiFetch("/api/gold-desk/sf-books/run", { method: "POST" });
      const moved = Object.values((r?.accounts ?? {}) as Record<string, { opened?: number; closed?: number }>);
      const opened = moved.reduce((n, b) => n + (b.opened ?? 0), 0);
      const shut = moved.reduce((n, b) => n + (b.closed ?? 0), 0);
      setNote(r?.note ?? `Copied the tab now: ${opened} opened, ${shut} closed.`);
      await Promise.all([load(), loadPositions()]);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "The copy could not run.");
    } finally {
      setBusy(false);
    }
  };

  if (err && !ov) return <NotDeployed err={err} />;
  if (!ov) return <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading the 25 accounts…</div>;
  return (
    <SfView ov={ov} set={set} acct={acct} onSet={(k) => { setSet(k); setAcct(null); }} onAcct={setAcct}
      open={open} closed={closed} busy={busy} note={note} onRun={runNow} />
  );
}

/** The server has no such route yet: say so, and show the five sets as they were frozen. */
function NotDeployed({ err }: { err: string }) {
  return (
    <div className="sf">
      <div className="sf-warn">
        <b>Not running yet.</b>{" "}
        {err === "Not Found"
          ? "These 25 accounts are set up, but the server has not been updated with them yet. They start copying the Strategy Factory tab on the first pass after the backend is deployed; nothing is back-filled."
          : `The accounts could not be read: ${err}.`}
      </div>
      <h4 className="sf-h">The five sets, frozen from the board at 22:21 IST on 18 Nov · ₹2 lakh each</h4>
      <div className="sf-scroll">
        <table className="sf-table">
          <thead>
            <tr><th className="l">Set</th><th>Rank</th><th className="l">Strategy</th><th>Score</th><th>Trades</th><th>Net on the tab</th></tr>
          </thead>
          <tbody>
            {ROSTER.map(([rank, id, name, score, trades, net]) => (
              <tr key={id}>
                <td className="l">{SETS[Math.floor((rank - 1) / 5)].label}</td>
                <td>{rank}</td>
                <td className="l"><span className="sf-dim">{id}</span> {name}</td>
                <td>{score.toFixed(1)}</td>
                <td>{trades}</td>
                <td className={toneOf(net)}>{usd(net, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <SfStyle />
    </div>
  );
}

function SetCard({ title, sub, m, on, onClick }: { title: string; sub: string; m: Total | undefined; on: boolean; onClick: () => void }) {
  return (
    <button className={`sf-card${on ? " on" : ""}`} onClick={onClick} aria-pressed={on}>
      <span className="sf-k">{title}</span>
      <span className="sf-v">{m ? inr(m.equity) : "—"}</span>
      <span className={`sf-r ${toneOf(m?.roi_pct)}`}>{m ? `${pctCell(m.roi_pct)} on ${inr(m.capital)}` : ""}</span>
      <span className="sf-s">{m ? `realised ${inr(m.realized_pnl, true)} · open ${inr(m.unrealized_pnl, true)}` : ""}</span>
      <span className="sf-s">
        {m ? `${m.closed_positions} trades${m.win_rate === null ? "" : ` · ${m.win_rate.toFixed(0)}% won`} · ${m.open_positions} open` : ""}
      </span>
      <span className="sf-about">{sub}</span>
    </button>
  );
}

/** What the panel shows, given what it read: no state of its own beyond its props, so it can be rendered on its own. */
export function SfView({ ov, set, acct, onSet, onAcct, open, closed, busy, note, onRun }: {
  ov: SfOverview; set: string; acct: string | null; onSet: (k: string) => void; onAcct: (id: string | null) => void;
  open: SfCopy[]; closed: SfCopy[]; busy: boolean; note: string | null; onRun: () => void;
}) {
  const shown = useMemo(() => ov.accounts.filter((a) => set === "all" || a.band === set), [ov.accounts, set]);
  const started = ov.accounts.map((a) => a.started_at).filter((x): x is string => !!x).sort()[0] ?? null;
  const cur = acct ? ov.accounts.find((a) => a.id === acct) : undefined;
  const bandOf = (k: string) => ov.bands.find((b) => b.band === k);
  const scopeLabel = cur ? `#${cur.rank} ${cur.name}` : set === "all" ? "all 25 accounts" : `${bandOf(set)?.label ?? set} (${bandOf(set)?.ranks ?? ""})`;

  return (
    <div className="sf">
      <div className="sf-warn">
        <b>Paper only, and not proven.</b>{" "}These are the 546 board&apos;s Rank 1-25 on 18 Nov, frozen. They had 17 to 75
        closed trades each and t-stats of 0.8 to 2.6 - the best of 415 short records on a tab that had lost money overall,
        so luck collects at the top. Each account is the forward test of whether its strategy keeps earning.
      </div>

      <div className="sf-cards">
        <SetCard title="All 25 · ₹2 lakh each" sub={`${ov.total.accounts} accounts · ${ov.total.traded} have traded`}
          m={ov.total} on={set === "all" && !acct} onClick={() => onSet("all")} />
        {ov.bands.map((b) => (
          <SetCard key={b.band} title={b.label} sub={`${b.ranks} · 5 accounts × ₹2 lakh`} m={b.total}
            on={set === b.band && !acct} onClick={() => onSet(b.band)} />
        ))}
      </div>

      <div className="sf-scroll">
        <table className="sf-table sf-click">
          <thead>
            <tr>
              <th className="l">Set</th>
              <th>Rank</th>
              <th className="l">Strategy</th>
              <th className="l" title="On the board when it was picked: Rank score, closed trades and net P&L on the tab's $1,111 sleeve">
                At the pick
              </th>
              <th>Equity</th>
              <th>Trades</th>
              <th>Win %</th>
              <th>Realised</th>
              <th>Open</th>
              <th title={DAY_COL_TITLES.traded}>Days traded</th>
              <th title="Days since the account started, today counted (Delta's XAUTUSD trades every day)">Total days</th>
              <th title="Realised + open P&L on the account's own ₹2 lakh">Total return</th>
              <th title={DAY_COL_TITLES.avg}>Avg / day</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => {
              const avg = perDayTraded(a.roi_pct, a.days_traded);
              return (
                <tr key={a.id} className={acct === a.id ? "sel" : ""} onClick={() => onAcct(acct === a.id ? null : a.id)}
                  title="Show this account's positions">
                  <td className="l">{bandOf(a.band)?.label ?? a.band}</td>
                  <td>{a.rank}</td>
                  <td className="l"><span className="sf-dim">{a.strategy_id}</span> {a.name}</td>
                  <td className="l sf-dim">{`${a.pick.score.toFixed(1)} · ${a.pick.trades} trades · ${usd(a.pick.net_usd, true)}`}</td>
                  <td>{inr(a.equity)}</td>
                  <td>{a.closed_positions}</td>
                  <td>{a.win_rate === null ? "—" : `${a.win_rate.toFixed(0)}%`}</td>
                  <td className={toneOf(a.realized_pnl)}>{a.closed_positions ? inr(a.realized_pnl, true) : "—"}</td>
                  <td className={toneOf(a.unrealized_pnl)}>{a.open_positions ? inr(a.unrealized_pnl, true) : "—"}</td>
                  <td>{dayCell(a.days_traded)}</td>
                  <td>{dayCell(istDaysSince(a.started_at))}</td>
                  <td className={`strong ${toneOf(a.roi_pct)}`}>{pctCell(a.roi_pct)}</td>
                  <td className={toneOf(avg)}>{pctCell(avg)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="sf-bar">
        <div className="sf-sum">
          Positions of <b>{scopeLabel}</b>
          {cur ? ` · equity ${inr(cur.equity)} · free cash ${inr(cur.available_cash)} · tied up ${inr(cur.deployed)}` : ""}
          {cur && Object.keys(cur.skipped).length
            ? ` · skipped ${Object.entries(cur.skipped).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}` : ""}
          {cur ? " · click the row again for its set" : " · click a strategy for its own account"}
        </div>
        <button className="sf-run" disabled={busy} onClick={onRun} title="Copy the tab's latest trades into every account now">
          {busy ? "Copying…" : "Copy now"}
        </button>
      </div>
      {note && <div className="sf-note">{note}</div>}

      <h4 className="sf-h">Open positions ({open.length})</h4>
      {open.length ? (
        <div className="sf-scroll">
          <table className="sf-table">
            <thead>
              <tr>
                <th className="l">Strategy</th><th>Side</th><th>Contracts</th><th>Entered (IST)</th><th>Entry</th><th>Last</th>
                <th>Ties up</th><th>Open P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {open.map((r) => (
                <tr key={r.position_id}>
                  <td className="l">#{r.rank} {r.strategy_name}</td>
                  <td>{r.side === "BUY" ? "Long" : "Short"}</td>
                  <td>{r.qty.toLocaleString("en-IN")}</td>
                  <td>{ist(r.opened_at)}</td>
                  <td>{usd(r.entry_px)}</td>
                  <td>{usd(r.ltp)}</td>
                  <td>{inr(r.capital_deployed)}</td>
                  <td className={toneOf(r.unrealized_pnl)}>{inr(r.unrealized_pnl, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="sf-dim">No open position here.</p>
      )}

      <h4 className="sf-h">Closed trades ({closed.length})</h4>
      {closed.length ? (
        <div className="sf-scroll">
          <table className="sf-table">
            <thead>
              <tr>
                <th className="l">Strategy</th><th>Side</th><th>Contracts</th><th>Entered (IST)</th><th>Left (IST)</th>
                <th>Entry</th><th>Exit</th><th>Why</th><th>Gross</th><th>Costs</th><th>Net</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((r) => (
                <tr key={r.position_id}>
                  <td className="l">#{r.rank} {r.strategy_name}</td>
                  <td>{r.side === "BUY" ? "Long" : "Short"}</td>
                  <td>{r.qty.toLocaleString("en-IN")}</td>
                  <td>{ist(r.opened_at)}</td>
                  <td>{ist(r.closed_at)}</td>
                  <td>{usd(r.entry_px)}</td>
                  <td>{usd(r.exit_px)}</td>
                  <td>{WHY[r.exit_reason ?? ""] ?? r.exit_reason ?? "—"}</td>
                  <td className={toneOf(r.gross_pnl)}>{inr(r.gross_pnl, true)}</td>
                  <td>{inr(r.fees)}</td>
                  <td className={`strong ${toneOf(r.realized_pnl)}`}>{inr(r.realized_pnl, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="sf-dim">
          {`No closed trade yet. The accounts copy only trades the tab opens after they started${started ? ` (${ist(started)} IST)` : ""}, so each account's first trade is its strategy's next entry on the tab.`}
        </p>
      )}

      <ul className="sf-notes">
        {ov.notes.map((n, i) => <li key={i}>{n}</li>)}
      </ul>
      <div className="sf-foot">
        {`Copies the Strategy Factory tab every ${Math.round(ov.tick_seconds / 60)} minutes${ov.enabled ? "" : " (switched off)"}`}
        {ov.usd_inr?.rate ? ` · USD/INR ${ov.usd_inr.rate.toFixed(2)} (read ${ist(ov.usd_inr.at)} IST)` : " · USD/INR not read yet"}
        {started ? ` · started ${ist(started)} IST` : ""}
        {` · picked ${ist(ov.picked_at)} IST`}
      </div>
      <SfStyle />
    </div>
  );
}

/** Global, because the set cards are drawn by <SetCard>, a child component scoped styles never reach. Every selector
 *  is under .sf, so nothing outside this panel is touched. */
function SfStyle() {
  return (
    <style jsx global>{`
      .sf { display: flex; flex-direction: column; gap: 14px; }
      .sf .sf-warn { font-size: 12.5px; line-height: 1.55; color: var(--text-muted); background: var(--canvas-soft);
                     border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; }
      .sf .sf-warn b { color: var(--text); }
      .sf .sf-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
      .sf .sf-card { display: flex; flex-direction: column; gap: 4px; text-align: left; cursor: pointer; font: inherit;
                     background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; padding: 14px 16px; }
      .sf .sf-card.on { border-color: var(--brand-border); background: var(--brand-dim); }
      .sf .sf-k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
      .sf .sf-v { font-family: var(--font-data); font-size: 20px; font-weight: 700; color: var(--text);
                  font-variant-numeric: tabular-nums; }
      .sf .sf-r { font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; }
      .sf .sf-s { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
      .sf .sf-about { margin-top: 4px; font-size: 11.5px; color: var(--text-faint); }
      .sf .sf-scroll { overflow-x: auto; }
      .sf .sf-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
      .sf .sf-table th { font-size: 10.5px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase;
                         color: var(--text-faint); text-align: right; padding: 8px 10px;
                         border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
      .sf .sf-table td { text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--panel-border);
                         white-space: nowrap; }
      .sf .sf-table .l { text-align: left; }
      .sf .sf-click tbody tr { cursor: pointer; }
      .sf .sf-click tbody tr:hover td { background: var(--canvas-soft); }
      .sf .sf-click tr.sel td { background: var(--brand-dim); }
      .sf .sf-dim { font-size: 11.5px; color: var(--text-muted); }
      .sf .gain { color: var(--gain); }
      .sf .loss { color: var(--loss); }
      .sf .strong { font-weight: 700; }
      .sf .sf-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
      .sf .sf-sum { font-size: 12.5px; color: var(--text-muted); line-height: 1.5; }
      .sf .sf-sum b { color: var(--text); }
      .sf .sf-run { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
                    border-radius: 9px; padding: 7px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
      .sf .sf-run:hover:not(:disabled) { color: var(--brand); border-color: var(--brand-border); }
      .sf .sf-run:disabled { opacity: 0.55; cursor: default; }
      .sf .sf-note { font-size: 12.5px; color: var(--brand); }
      .sf .sf-h { margin: 6px 0 0; font-size: 13px; font-weight: 800; color: var(--text); }
      .sf .sf-notes { margin: 4px 0 0; padding-left: 18px; font-size: 12px; line-height: 1.6; color: var(--text-muted); }
      .sf .sf-foot { font-size: 11.5px; color: var(--text-faint); }
      @media (max-width: 640px) {
        .sf .sf-v { font-size: 18px; }
      }
    `}</style>
  );
}
