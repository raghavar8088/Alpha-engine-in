"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import DeskHistory from "../../components/DeskHistory";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import LineChart from "../../components/charts/LineChart";
import {
  refreshing,
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
  const [driftPct, setDriftPct] = useState("2");
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
        drift_pct: driftPct === "" ? undefined : Number(driftPct),
      });
      setNotice(`${picked.symbol} added to the buy zone at ₹${buyPrice}`);
      setPicked(null); setQ(""); setBuyPrice(""); setHits([]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add that watch");
    } finally { setBusy(false); }
  }

  async function patchWatch(id: string, field: "buy_price" | "sl_pct" | "tp_pct" | "drift_pct", cur: number) {
    const label = field === "buy_price" ? "buy price (₹)"
      : field === "sl_pct" ? "stop-loss %"
      : field === "drift_pct" ? "drift % (how far a gap may open past your price)"
      : "target %";
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
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Swing Trading"
        title="Swing Trading"
        subtitle="You name the price; the desk waits for it. Search any listed Indian equity, set the price you want to buy at, and the order fills automatically when the market reaches it — then runs to a stop and target you can change at any time, before the fill or after. ₹1,00,000 per position out of a ₹10 crore book. Paper, on live Angel One prices, with real Angel One delivery costs charged on every close."
      />

      <div className="desk-banner">
        <strong>GAP-UPS STILL FILL, WITHIN A LIMIT.</strong> Name ₹102 on a ₹100 stock and
        it opens at ₹104 — that is still your trade, so it fills at ₹104 and is marked{" "}
        <span className="badge drift">DRIFTED</span>. But only inside the{" "}
        <b>drift band</b> (2% by default). Open at ₹130 against your ₹102 and the desk{" "}
        <em>refuses</em> — that is not the trade you asked for at any price. The watch stays
        live, records how far it gapped, and still fills if price pulls back into the band.
        Stop and target are set from the price you <strong>actually filled at</strong>, so a
        drifted entry measures its risk from where the money really went in.
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
       <div className="addwrap">
        <div className="addbox">
          <div className="field grow">
            <label>Search any Indian stock</label>
            <input
              value={q}
              placeholder="symbol or company name, e.g. TATASTEEL or Reliance"
              onChange={(e) => { setPicked(null); setQ(e.target.value); }}
            />
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
          <div className="field sm">
            <label>Drift %</label>
            <input type="number" step="0.5" min="0" value={driftPct}
                   onChange={(e) => setDriftPct(e.target.value)} />
          </div>
          <button className="primary" disabled={!picked || !buyPrice || busy} onClick={submitWatch}>
            {busy ? "Adding…" : "Add to buy zone"}
          </button>
        </div>

        {/* Results sit IN FLOW, not floating over the page. GlassPanel clips its children
            (overflow: hidden), so an absolutely-positioned dropdown rendered correctly and
            was then invisible below the panel edge — which read as "search is broken". */}
        {!picked && q.trim() !== "" && (
          <div className="hits">
            {hits.length === 0 ? (
              <div className="nohit">No listed stock matches “{q}”.</div>
            ) : (
              hits.map((h) => (
                <button key={h.symbol} className="hit" onClick={() => { setPicked(h); setQ(""); setHits([]); }}>
                  <b>{h.symbol}</b><span>{h.name}</span>
                </button>
              ))
            )}
          </div>
        )}
        {picked && (
          <div className="chosen">
            Selected <b>{picked.symbol}</b> — {picked.name}
            <button className="clear" onClick={() => { setPicked(null); setQ(""); }}>change</button>
          </div>
        )}
        {picked && buyPrice && (
          <p className="preview">
            <b>{picked.symbol}</b> at ₹{buyPrice} → stop ₹{inr2(Number(buyPrice) * (1 - Number(slPct) / 100))} ·
            target ₹{inr2(Number(buyPrice) * (1 + Number(tpPct) / 100))} ·
            about {Math.floor((summary?.position_size ?? 100000) / Number(buyPrice))} shares.
            {" "}Fills anywhere up to ₹{inr2(Number(buyPrice) * (1 + Number(driftPct || 0) / 100))}{" "}
            if it gaps; above that it is refused.
          </p>
        )}
       </div>
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
                  <th>LTP</th><th>Away</th><th>Fills up to</th><th>Stop</th><th>Target</th><th>Edit</th>
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
                        <td>
                          ₹{inr2(w.max_fill_price)} <span className="sub">({w.drift_pct}% drift)</span>
                          {w.gapped_past && (
                            <div className="gapwarn">
                              gapped {(w.last_gap_pct ?? 0) > 0 ? "+" : ""}{w.last_gap_pct}% past — not filled
                            </div>
                          )}
                        </td>
                        <td>₹{inr2(w.stop_price)} <span className="sub">({w.sl_pct}%)</span></td>
                        <td>₹{inr2(w.target_price)} <span className="sub">({w.tp_pct}%)</span></td>
                        <td className="acts">
                          <button onClick={() => patchWatch(w.watch_id, "buy_price", w.buy_price)}>price</button>
                          <button onClick={() => patchWatch(w.watch_id, "sl_pct", w.sl_pct)}>SL</button>
                          <button onClick={() => patchWatch(w.watch_id, "tp_pct", w.tp_pct)}>TP</button>
                          <button onClick={() => patchWatch(w.watch_id, "drift_pct", w.drift_pct)}>drift</button>
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
                    <tr key={p.position_id} className={p.drifted ? "drifted" : ""}>
                      <td style={{ textAlign: "left" }}>
                        <strong>{p.symbol}</strong>
                        {p.drifted && <span className="badge drift">DRIFTED</span>}
                        <div className="sub">{p.name}</div>
                      </td>
                      <td>{p.qty}</td>
                      <td>₹{inr2(p.buy_price)}</td>
                      <td>
                        ₹{inr2(p.entry_price)}
                        <div className="sub">
                          {p.drifted
                            ? `gapped ${(p.drift_pct_actual ?? 0) > 0 ? "+" : ""}${p.drift_pct_actual}%`
                            : "exact"}
                        </div>
                      </td>
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

      <DeskHistory deskKey={"swing"} />

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
        .tile { padding: 12px 14px; border-radius: 10px; background: var(--panel); border: 1px solid var(--panel-border); }
        .tile-label { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .tile-value { margin-top: 5px; font-family: var(--font-data); font-variant-numeric: tabular-nums; font-size: 16px; font-weight: 600; }
        .tile-value.sm { font-size: 13px; }
        .tile-sub { margin-top: 3px; font-size: 10.5px; color: var(--text-faint); line-height: 1.4; }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .table-scroll { overflow-x: auto; max-height: 460px; overflow-y: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .badge { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .badge.loss { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.3); }
        .empty { padding: 18px 20px; font-size: 12px; color: var(--text-faint); text-align: center; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .sub { font-size: 10.5px; color: var(--text-faint); }
        .desk-banner { background: var(--canvas-edge); border: 1px solid var(--panel-border); border-radius: 12px; padding: 12px 16px; font-size: 12px; line-height: 1.7; color: var(--text-muted); }
        .notice { background: var(--purple-dim); border: 1px solid rgba(125, 52, 220, 0.3); color: var(--purple); border-radius: 10px; padding: 9px 14px; font-size: 12px; cursor: pointer; }
        .addwrap { padding: 16px 20px 18px; }
        .addbox { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
        .field { display: flex; flex-direction: column; gap: 5px; }
        .field.grow { flex: 1 1 320px; }
        .field.sm { width: 96px; }
        .field label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 12.5px; color: var(--text); width: 100%; font-variant-numeric: tabular-nums; }
        .field input:focus { outline: none; border-color: var(--purple); }
        .hits { margin-top: 12px; border: 1px solid var(--panel-border); border-radius: 10px; max-height: 300px; overflow-y: auto; background: var(--canvas-soft); }
        .hit { display: flex; align-items: baseline; gap: 12px; width: 100%; padding: 9px 14px; background: none; border: none; border-bottom: 1px solid var(--panel-border); cursor: pointer; text-align: left; color: var(--text); }
        .hit:last-child { border-bottom: none; }
        .hit:hover { background: var(--purple-dim); color: var(--purple); }
        .hit b { min-width: 132px; font-size: 12px; font-weight: 700; }
        .hit span { font-size: 11px; color: var(--text-faint); }
        .nohit { padding: 14px; font-size: 12px; color: var(--text-faint); text-align: center; }
        .chosen { margin-top: 12px; font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 10px; }
        .clear { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); border-radius: 7px; padding: 3px 10px; font-size: 10.5px; font-weight: 600; cursor: pointer; }
        .primary { background: var(--purple); color: #fff; border: none; border-radius: 9px; padding: 10px 18px; font-weight: 700; font-size: 12.5px; cursor: pointer; }
        .primary:hover:not(:disabled) { background: var(--purple-hover); }
        .primary:disabled { opacity: 0.4; cursor: not-allowed; }
        .preview { margin: 12px 0 0; font-size: 11.5px; color: var(--text-muted); line-height: 1.6; }
        .acts { display: flex; gap: 4px; justify-content: center; }
        .acts button { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); border-radius: 6px; padding: 3px 8px; font-size: 10px; font-weight: 600; cursor: pointer; }
        .acts button:hover { color: var(--purple); border-color: rgba(125, 52, 220, 0.3); background: var(--purple-dim); }
        .acts button.danger:hover { color: var(--loss); border-color: rgba(217, 45, 63, 0.3); background: var(--loss-dim); }
        .badge.dip { background: var(--gain-dim); border-color: rgba(16, 150, 90, 0.3); color: var(--gain); }
        /* DRIFTED is neither an error nor an ordinary fill, so it takes the app's WARN
           token rather than a hand-picked colour or the loss red. */
        .badge.drift { background: var(--warn-dim); border-color: var(--warn); color: var(--warn); margin-left: 6px; }
        tr.drifted { background: var(--warn-dim); }
        .gapwarn { font-size: 10px; color: var(--warn); margin-top: 2px; }
        .hint { font-size: 11px; color: var(--text-faint); padding: 10px 20px 14px; margin: 0; }
      `}</style>
    </div>
  );
}
