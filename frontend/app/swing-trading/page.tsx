"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  fetchSwingSummary,
  fetchSwingWatchlist,
  fetchSwingPositions,
  fetchSwingEquity,
  fetchSwingDaily,
  searchSwingStocks,
  addSwingWatch,
  editSwingWatch,
  removeSwingWatch,
  editSwingPosition,
  type SwingSummary,
  type SwingWatch,
  type SwingPosition,
  type SwingEquityPoint,
  type SwingDay,
  type SwingSearchResult,
} from "../../lib/api";

const REFRESH_MS = 30000;
type Tab = "watchlist" | "open" | "closed" | "daily";
const TABS: { key: Tab; label: string }[] = [
  { key: "watchlist", label: "Buy zone" },
  { key: "open", label: "Open positions" },
  { key: "closed", label: "Closed" },
  { key: "daily", label: "Daily P&L / ROI" },
];

const inr = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v: number | null | undefined, dp = 2) =>
  `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(dp)}%`;
const cls = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");

export default function SwingTradingPage() {
  const [tab, setTab] = useState<Tab>("watchlist");
  const [summary, setSummary] = useState<SwingSummary | null>(null);
  const [watchlist, setWatchlist] = useState<SwingWatch[]>([]);
  const [open, setOpen] = useState<SwingPosition[]>([]);
  const [closed, setClosed] = useState<SwingPosition[]>([]);
  const [equity, setEquity] = useState<SwingEquityPoint[]>([]);
  const [daily, setDaily] = useState<SwingDay[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // add form
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SwingSearchResult[]>([]);
  const [picked, setPicked] = useState<SwingSearchResult | null>(null);
  const [buyPrice, setBuyPrice] = useState("");
  const [slPct, setSlPct] = useState("10");
  const [tpPct, setTpPct] = useState("10");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, w, o, c, e, d] = await Promise.all([
        fetchSwingSummary(),
        fetchSwingWatchlist(),
        fetchSwingPositions("OPEN"),
        fetchSwingPositions("CLOSED"),
        fetchSwingEquity(),
        fetchSwingDaily(),
      ]);
      setSummary(s); setWatchlist(w); setOpen(o); setClosed(c); setEquity(e); setDaily(d);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Swing Trading");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // debounce so a fast typist does not fire a query per keystroke
  useEffect(() => {
    if (q.trim().length < 1) { setHits([]); return; }
    const t = setTimeout(async () => {
      try { setHits(await searchSwingStocks(q, 12)); } catch { setHits([]); }
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  const equitySeries = useMemo(
    () => equity.map((p) => ({ ts: p.ts, value: p.equity })), [equity]);

  async function submitWatch() {
    if (!picked || !buyPrice) return;
    setBusy(true);
    try {
      await addSwingWatch({
        symbol: picked.symbol,
        buy_price: Number(buyPrice),
        sl_pct: Number(slPct) || undefined,
        tp_pct: Number(tpPct) || undefined,
      });
      setNotice(`${picked.symbol} added to the buy zone at ₹${buyPrice}`);
      setPicked(null); setQ(""); setBuyPrice(""); setHits([]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add that watch");
    } finally { setBusy(false); }
  }

  async function patchWatch(id: string, field: "buy_price" | "sl_pct" | "tp_pct", cur: number) {
    const label = field === "buy_price" ? "buy price (₹)" : field === "sl_pct" ? "stop-loss %" : "target %";
    const v = window.prompt(`New ${label}:`, String(cur));
    if (v === null || v.trim() === "") return;
    try {
      await editSwingWatch(id, { [field]: Number(v) });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Edit failed");
    }
  }

  async function patchPosition(id: string, field: "sl_pct" | "tp_pct", cur: number) {
    const v = window.prompt(`New ${field === "sl_pct" ? "stop-loss %" : "target %"}:`, String(cur));
    if (v === null || v.trim() === "") return;
    try {
      await editSwingPosition(id, { [field]: Number(v) });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Edit failed");
    }
  }

  async function cancelWatch(id: string, sym: string) {
    if (!window.confirm(`Cancel the waiting buy order for ${sym}?`)) return;
    try { await removeSwingWatch(id); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Cancel failed"); }
  }

  const waiting = watchlist.filter((w) => w.status === "WAITING");
  const others = watchlist.filter((w) => w.status !== "WAITING");

  return (
    <div className="page">
      <PageHeader
        crumb="Swing Trading"
        title="Swing Trading"
        subtitle="You name the price; the desk waits for it. Search any listed Indian equity, set the price you want to buy at, and the order fills automatically when the market reaches it — then runs to a stop and target you can change at any time, before the fill or after. ₹1,00,000 per position out of a ₹10 crore book. Paper, on live Angel One prices, with real Angel One delivery costs charged on every close."
      />

      <div className="desk-banner">
        <strong>HOW YOUR PRICE IS READ.</strong> A price <em>below</em> the market is a{" "}
        <b>DIP</b> order — it fills when price falls to it. A price <em>above</em> the market
        is a <b>BREAKOUT</b> order — it fills when price rises to it. The direction is fixed
        when you add the watch, from where the stock trades at that moment, so a stock
        drifting past your level overnight cannot silently reverse what you asked for.
        Stop and target are anchored to <strong>the price you named</strong>, not to the fill,
        so a gap-through fill never quietly changes the risk you accepted.
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}

      <div className="tiles">
        <div className="tile"><div className="tile-label">Mode</div><div className="tile-value gain">PAPER</div><div className="tile-sub">live Angel feed</div></div>
        <div className="tile"><div className="tile-label">Desk capital</div><div className="tile-value">₹{inr(summary?.initial_capital)}</div><div className="tile-sub">₹{inr(summary?.position_size)} / position · max {summary?.max_positions ?? 0}</div></div>
        <div className="tile"><div className="tile-label">Equity</div><div className="tile-value">₹{inr(summary?.equity)}</div><div className="tile-sub">₹{inr(summary?.unrealized_pnl)} unrealised</div></div>
        <div className="tile"><div className="tile-label">Total capital ROI</div><div className={`tile-value ${cls(summary?.roi_pct)}`}>{pct(summary?.roi_pct, 4)}</div><div className="tile-sub">on the full ₹{inr(summary?.initial_capital)}</div></div>
        <div className="tile"><div className="tile-label">ROI on deployed</div><div className={`tile-value ${cls(summary?.deployed_roi_pct)}`}>{pct(summary?.deployed_roi_pct, 3)}</div><div className="tile-sub">on ₹{inr(summary?.deployed_capital)} actually at risk</div></div>
        <div className="tile"><div className="tile-label">Today P&amp;L</div><div className={`tile-value ${cls(summary?.today_pnl)}`}>{(summary?.today_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(summary?.today_pnl)}</div><div className="tile-sub">{pct(summary?.today_roi_pct, 4)} today</div></div>
        <div className="tile"><div className="tile-label">Angel fees</div><div className="tile-value loss">−₹{inr(summary?.total_fees)}</div><div className="tile-sub">gross ₹{inr(summary?.gross_realized_pnl)} before costs</div></div>
        <div className="tile"><div className="tile-label">Positions</div><div className="tile-value">{summary?.open_positions ?? 0}</div><div className="tile-sub">{summary?.waiting ?? 0} waiting · {summary?.closed_positions ?? 0} closed</div></div>
      </div>

      <GlassPanel title="Add a stock to the buy zone">
        <div className="addbox">
          <div className="field grow">
            <label>Search any Indian stock</label>
            <input
              value={picked ? `${picked.symbol} — ${picked.name}` : q}
              placeholder="symbol or company name, e.g. TATASTEEL or Reliance"
              onChange={(e) => { setPicked(null); setQ(e.target.value); }}
            />
            {!picked && hits.length > 0 && (
              <div className="hits">
                {hits.map((h) => (
                  <button key={h.symbol} className="hit" onClick={() => { setPicked(h); setHits([]); }}>
                    <b>{h.symbol}</b><span>{h.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="field">
            <label>Buy price (₹)</label>
            <input type="number" step="0.05" value={buyPrice}
                   onChange={(e) => setBuyPrice(e.target.value)} placeholder="0.00" />
          </div>
          <div className="field sm">
            <label>Stop-loss %</label>
            <input type="number" step="0.5" value={slPct} onChange={(e) => setSlPct(e.target.value)} />
          </div>
          <div className="field sm">
            <label>Target %</label>
            <input type="number" step="0.5" value={tpPct} onChange={(e) => setTpPct(e.target.value)} />
          </div>
          <button className="primary" disabled={!picked || !buyPrice || busy} onClick={submitWatch}>
            {busy ? "Adding…" : "Add to buy zone"}
          </button>
        </div>
        {picked && buyPrice && (
          <p className="preview">
            <b>{picked.symbol}</b> at ₹{buyPrice} → stop ₹{inr2(Number(buyPrice) * (1 - Number(slPct) / 100))} ·
            target ₹{inr2(Number(buyPrice) * (1 + Number(tpPct) / 100))} ·
            about {Math.floor((summary?.position_size ?? 100000) / Number(buyPrice))} shares
          </p>
        )}
      </GlassPanel>

      <GlassPanel title="Equity">
        {equitySeries.length < 2 ? (
          <div className="empty">The equity curve appears once the desk has run a few cycles.</div>
        ) : (
          <LineChart
            points={equitySeries}
            height={220}
            formatValue={(v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          />
        )}
      </GlassPanel>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "tab active" : "tab"} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "watchlist" && (
        <GlassPanel title={`Waiting for your price (${waiting.length})`}>
          {!waiting.length ? (
            <div className="empty">Nothing waiting — add a stock above.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr>
                  <th style={{ textAlign: "left" }}>Symbol</th><th>Type</th><th>Your price</th>
                  <th>LTP</th><th>Away</th><th>Stop</th><th>Target</th><th>Edit</th>
                </tr></thead>
                <tbody>
                  {waiting.map((w) => {
                    const away = w.ltp ? ((w.buy_price / w.ltp - 1) * 100) : null;
                    return (
                      <tr key={w.watch_id}>
                        <td style={{ textAlign: "left" }}><strong>{w.symbol}</strong><div className="sub">{w.name}</div></td>
                        <td><span className={w.trigger_side === "BREAKOUT" ? "badge" : "badge dip"}>{w.trigger_side}</span></td>
                        <td>₹{inr2(w.buy_price)}</td>
                        <td>{w.ltp ? `₹${inr2(w.ltp)}` : "—"}</td>
                        <td className={away === null ? "" : cls(-Math.abs(away))}>{away === null ? "—" : `${away.toFixed(2)}%`}</td>
                        <td>₹{inr2(w.stop_price)} <span className="sub">({w.sl_pct}%)</span></td>
                        <td>₹{inr2(w.target_price)} <span className="sub">({w.tp_pct}%)</span></td>
                        <td className="acts">
                          <button onClick={() => patchWatch(w.watch_id, "buy_price", w.buy_price)}>price</button>
                          <button onClick={() => patchWatch(w.watch_id, "sl_pct", w.sl_pct)}>SL</button>
                          <button onClick={() => patchWatch(w.watch_id, "tp_pct", w.tp_pct)}>TP</button>
                          <button className="danger" onClick={() => cancelWatch(w.watch_id, w.symbol)}>✕</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {others.length > 0 && (
            <p className="hint">
              {others.filter((o) => o.status === "TRIGGERED").length} already filled ·{" "}
              {others.filter((o) => o.status === "UNFILLABLE").length} could not be sized
              (one share costs more than ₹{inr(summary?.position_size)}).
            </p>
          )}
        </GlassPanel>
      )}

      {(tab === "open" || tab === "closed") && (
        <GlassPanel title={tab === "open" ? `Open positions (${open.length})` : `Closed positions (${closed.length})`}>
          {!(tab === "open" ? open : closed).length ? (
            <div className="empty">{tab === "open" ? "No positions open yet." : "Nothing closed yet."}</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr>
                  <th style={{ textAlign: "left" }}>Symbol</th><th>Qty</th><th>Your price</th><th>Filled at</th>
                  <th>{tab === "open" ? "LTP" : "Exit"}</th><th>Stop</th><th>Target</th>
                  <th>{tab === "open" ? "Unrealised" : "Net P&L"}</th>
                  {tab === "closed" && <th>Fees</th>}{tab === "closed" && <th>Why</th>}
                  {tab === "open" && <th>Edit</th>}
                </tr></thead>
                <tbody>
                  {(tab === "open" ? open : closed).map((p) => (
                    <tr key={p.position_id}>
                      <td style={{ textAlign: "left" }}><strong>{p.symbol}</strong><div className="sub">{p.name}</div></td>
                      <td>{p.qty}</td>
                      <td>₹{inr2(p.buy_price)}</td>
                      <td>₹{inr2(p.entry_price)}<div className="sub">{p.slippage ? `slip ₹${inr2(p.slippage)}` : "exact"}</div></td>
                      <td>₹{inr2(tab === "open" ? p.ltp : p.exit_price)}</td>
                      <td>₹{inr2(p.stop_price)}</td>
                      <td>₹{inr2(p.target_price)}</td>
                      <td className={cls(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}>
                        {((tab === "open" ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "+" : ""}₹{inr(tab === "open" ? p.unrealized_pnl : p.realized_pnl)}
                      </td>
                      {tab === "closed" && <td className="loss">−₹{inr(p.fees)}</td>}
                      {tab === "closed" && <td className="sub">{p.exit_reason}</td>}
                      {tab === "open" && (
                        <td className="acts">
                          <button onClick={() => patchPosition(p.position_id, "sl_pct", p.sl_pct)}>SL</button>
                          <button onClick={() => patchPosition(p.position_id, "tp_pct", p.tp_pct)}>TP</button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "daily" && (
        <GlassPanel title="Daily P&L and ROI">
          {!daily.length ? <div className="empty">No closed sessions yet.</div> : (
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr>
                  <th style={{ textAlign: "left" }}>Date</th><th>Trades</th><th>Win %</th>
                  <th>Gross</th><th>Fees</th><th>Net P&amp;L</th>
                  <th>ROI (total capital)</th><th>ROI (deployed)</th>
                </tr></thead>
                <tbody>
                  {daily.map((d) => (
                    <tr key={d.date}>
                      <td style={{ textAlign: "left" }}>{d.date}</td>
                      <td>{d.trades}</td>
                      <td>{(d.win_rate * 100).toFixed(1)}%</td>
                      <td className={cls(d.gross_pnl)}>{d.gross_pnl >= 0 ? "+" : ""}₹{inr(d.gross_pnl)}</td>
                      <td className="loss">−₹{inr(d.fees)}</td>
                      <td className={cls(d.realized_pnl)}>{d.realized_pnl >= 0 ? "+" : ""}₹{inr(d.realized_pnl)}</td>
                      <td className={cls(d.roi_pct)}>{pct(d.roi_pct, 4)}</td>
                      <td className={cls(d.deployed_roi_pct)}>{pct(d.deployed_roi_pct, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .desk-banner { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.65; color: var(--text-muted); }
        .notice { background: var(--purple-dim); border: 1px solid rgba(125,52,220,.35); color: var(--purple); border-radius: 10px; padding: 9px 14px; font-size: 12.5px; cursor: pointer; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .tile { background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 12px; padding: 14px 16px; }
        .tile-label { font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--text-faint); }
        .tile-value { font-size: 21px; font-weight: 800; margin-top: 4px; font-variant-numeric: tabular-nums; }
        .tile-sub { font-size: 11px; color: var(--text-faint); margin-top: 3px; }
        .addbox { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
        .field { display: flex; flex-direction: column; gap: 5px; position: relative; }
        .field.grow { flex: 1 1 320px; }
        .field.sm { width: 108px; }
        .field label { font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-faint); }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13px; color: var(--text); width: 100%; }
        .hits { position: absolute; top: 100%; left: 0; right: 0; z-index: 20; margin-top: 4px; background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 10px; overflow: hidden; max-height: 280px; overflow-y: auto; }
        .hit { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; width: 100%; padding: 8px 12px; background: none; border: none; cursor: pointer; text-align: left; color: var(--text); }
        .hit:hover { background: var(--canvas-soft); }
        .hit span { font-size: 11px; color: var(--text-faint); }
        .primary { background: var(--purple); color: #fff; border: none; border-radius: 9px; padding: 10px 20px; font-weight: 700; font-size: 13px; cursor: pointer; }
        .primary:disabled { opacity: .45; cursor: not-allowed; }
        .preview { margin: 12px 0 0; font-size: 12px; color: var(--text-muted); }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 8px 15px; border-radius: 10px; cursor: pointer; font-size: 12.5px; font-weight: 700; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125,52,220,.35); color: var(--purple); }
        .table-scroll { overflow-x: auto; }
        .sub { font-size: 10.5px; color: var(--text-faint); }
        .acts { display: flex; gap: 5px; justify-content: center; }
        .acts button { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); border-radius: 7px; padding: 3px 9px; font-size: 11px; cursor: pointer; }
        .acts button:hover { color: var(--purple); border-color: rgba(125,52,220,.35); }
        .acts button.danger:hover { color: var(--red); border-color: var(--red); }
        .badge.dip { background: rgba(34,160,90,.14); color: var(--green); }
        .empty { padding: 22px; text-align: center; color: var(--text-faint); font-size: 12.5px; }
        .hint { font-size: 11.5px; color: var(--text-faint); margin: 10px 0 0; }
        .gain { color: var(--green); }
        .loss { color: var(--red); }
      `}</style>
    </div>
  );
}
