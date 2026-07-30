"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  FnoAccount,
  FnoInstrumentKind,
  FnoOrder,
  FnoPosition,
  FnoPositionsSummary,
  FnoProductType,
  FnoUnderlying,
  OptionChainResponse,
  OptionLeg,
  TopMover,
  createFnoAccount,
  editFnoAccount,
  exitFnoPosition,
  fetchFnoAccounts,
  fetchFnoFutureExpiries,
  fetchFnoOptionChain,
  fetchFnoOptionExpiries,
  fetchFnoOrders,
  fetchFnoPositions,
  fetchFnoTopMovers,
  fetchFnoUnderlyings,
  placeFnoOrder,
  resetFnoPositions,
} from "../../lib/api";

const SELECTED_ACCOUNT_KEY = "tradingai:fno-positions:selected-account";

const PRODUCT_TYPES: { id: FnoProductType; label: string }[] = [
  { id: "INTRADAY", label: "Intraday" },
  { id: "MARGIN", label: "Margin" },
];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

type Tab = "chain" | "futures" | "movers" | "positions" | "orders";

type OrderDraft = {
  instrument_kind: FnoInstrumentKind;
  symbol: string;
  expiry: string;
  strike?: number;
  option_type?: "CE" | "PE";
  transaction_type: "BUY" | "SELL";
  ltp: number;
  lot_size: number;
};

export default function FnoPositionsPage() {
  const [accounts, setAccounts] = useState<FnoAccount[]>([]);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [createAccountOpen, setCreateAccountOpen] = useState(false);
  const [editAccountOpen, setEditAccountOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("chain");
  const [underlyings, setUnderlyings] = useState<FnoUnderlying[]>([]);
  const [symbol, setSymbol] = useState<string>("NIFTY");
  const [expiry, setExpiry] = useState<string>("");
  const [expiries, setExpiries] = useState<string[]>([]);
  const [chain, setChain] = useState<OptionChainResponse | null>(null);
  const [chainLoading, setChainLoading] = useState(false);
  const [futSymbol, setFutSymbol] = useState<string>("NIFTY");
  const [futExpiry, setFutExpiry] = useState<string>("");
  const [futExpiries, setFutExpiries] = useState<string[]>([]);
  const [movers, setMovers] = useState<{ top_calls: TopMover[]; top_puts: TopMover[] } | null>(null);
  const [positions, setPositions] = useState<FnoPosition[]>([]);
  const [summary, setSummary] = useState<FnoPositionsSummary | null>(null);
  const [orders, setOrders] = useState<FnoOrder[]>([]);
  const [positionsFilter, setPositionsFilter] = useState<"OPEN" | "all">("OPEN");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [draft, setDraft] = useState<OrderDraft | null>(null);

  useEffect(() => {
    fetchFnoUnderlyings()
      .then((u) => setUnderlyings(u.length ? u : [{ symbol: "NIFTY", name: "Nifty 50", kind: "INDEX" }]))
      .catch(() => setUnderlyings([{ symbol: "NIFTY", name: "Nifty 50", kind: "INDEX" }]));
  }, []);

  const loadAccounts = useCallback(async () => {
    setAccountsLoading(true);
    try {
      const data = await fetchFnoAccounts();
      setAccounts(data);
      setAccountId((current) => {
        if (current && data.some((a) => a.account_id === current)) return current;
        const saved = typeof window !== "undefined" ? window.localStorage.getItem(SELECTED_ACCOUNT_KEY) : null;
        if (saved && data.some((a) => a.account_id === saved)) return saved;
        return data[0]?.account_id ?? null;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load accounts");
    } finally {
      setAccountsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  const selectAccount = useCallback((id: string) => {
    setAccountId(id);
    if (typeof window !== "undefined") window.localStorage.setItem(SELECTED_ACCOUNT_KEY, id);
  }, []);

  const activeAccount = accounts.find((a) => a.account_id === accountId) ?? null;

  const loadPositions = useCallback(async () => {
    if (!accountId) return;
    setError(null);
    try {
      const data = await fetchFnoPositions(accountId, positionsFilter === "all" ? undefined : positionsFilter);
      setPositions(data.positions);
      setSummary(data.summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    }
  }, [accountId, positionsFilter]);

  useEffect(() => {
    loadPositions();
    const t = setInterval(loadPositions, 20_000);
    return () => clearInterval(t);
  }, [loadPositions]);

  useEffect(() => {
    if (tab === "orders" && accountId) fetchFnoOrders(accountId).then((d) => setOrders(d.orders)).catch(() => {});
  }, [tab, accountId]);

  useEffect(() => {
    if (tab !== "chain" || !symbol) return;
    setError(null);
    fetchFnoOptionExpiries(symbol)
      .then((exps) => {
        setExpiries(exps);
        setExpiry(exps[0] ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load expiries"));
  }, [tab, symbol]);

  useEffect(() => {
    if (tab !== "chain" || !symbol || !expiry) return;
    setChainLoading(true);
    setError(null);
    fetchFnoOptionChain(symbol, expiry)
      .then(setChain)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load option chain"))
      .finally(() => setChainLoading(false));
  }, [tab, symbol, expiry]);

  useEffect(() => {
    if (tab !== "futures" || !futSymbol) return;
    fetchFnoFutureExpiries(futSymbol)
      .then((exps) => {
        setFutExpiries(exps);
        setFutExpiry(exps[0] ?? "");
      })
      .catch(() => setFutExpiries([]));
  }, [tab, futSymbol]);

  useEffect(() => {
    if (tab !== "movers") return;
    fetchFnoTopMovers(10).then(setMovers).catch(() => setMovers(null));
  }, [tab]);

  const atmStrike = useMemo(() => {
    if (!chain || !chain.strikes.length) return null;
    return chain.strikes.reduce((best, s) => (Math.abs(s.strike - chain.spot) < Math.abs(best.strike - chain.spot) ? s : best)).strike;
  }, [chain]);

  // Dhan returns the entire listed ladder (224 strikes on a NIFTY weekly), and most
  // of it is far-OTM contracts that have never traded — every field zero. Show only
  // strikes that are actually live. A deep-ITM leg can quote a real LTP while its OI
  // and volume sit at zero, so any one of the three fields keeps the row.
  const liveStrikes = useMemo(() => {
    if (!chain) return [];
    const traded = (leg: OptionLeg | undefined) =>
      !!leg && ((leg.last_price ?? 0) > 0 || (leg.oi ?? 0) > 0 || (leg.volume ?? 0) > 0);
    return chain.strikes.filter((row) => traded(row.ce) || traded(row.pe));
  }, [chain]);

  const exit = useCallback(
    async (p: FnoPosition) => {
      if (!accountId) return;
      if (!window.confirm(`Exit ${p.lots} lot(s) of ${p.display_name} @ market?`)) return;
      try {
        const result = await exitFnoPosition(accountId, p.position_id);
        setNotice(`Exited ${p.display_name} at ${inr(result.fill_price)} (realized P&L ${inr(result.position.realized_pnl)})`);
        await loadPositions();
      } catch (e) {
        setNotice(`Exit failed: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [accountId, loadPositions],
  );

  const reset = useCallback(async () => {
    if (!accountId) return;
    if (!window.confirm(
      `Reset "${activeAccount?.name ?? "this"}" account? This permanently deletes every position and order in it and restores ${inr(activeAccount?.initial_capital ?? 10000000)} initial capital. Other accounts are untouched. This cannot be undone.`,
    )) return;
    setResetting(true);
    try {
      const result = await resetFnoPositions(accountId);
      setNotice(`Reset complete — ${result.positions_deleted} position(s) and ${result.orders_deleted} order(s) cleared, capital restored to ${inr(result.initial_capital)}`);
      await loadPositions();
    } catch (e) {
      setNotice(`Reset failed: ${e instanceof Error ? e.message : "unknown error"}`);
    } finally {
      setResetting(false);
    }
  }, [accountId, activeAccount, loadPositions]);

  const createAccount = useCallback(
    async (name: string, initialCapital?: number) => {
      try {
        const account = await createFnoAccount(name, initialCapital);
        setCreateAccountOpen(false);
        await loadAccounts();
        selectAccount(account.account_id);
        setNotice(`Created account "${account.name}" with ${inr(account.initial_capital)} paper capital`);
      } catch (e) {
        setNotice(`Could not create account: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [loadAccounts, selectAccount],
  );

  const saveAccountEdit = useCallback(
    async (changes: { name?: string; initialCapital?: number }) => {
      if (!accountId) return;
      try {
        const account = await editFnoAccount(accountId, changes);
        setEditAccountOpen(false);
        await loadAccounts();
        await loadPositions();
        setNotice(`Updated account — now "${account.name}" with ${inr(account.initial_capital)} base capital`);
      } catch (e) {
        setNotice(`Could not update account: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [accountId, loadAccounts, loadPositions],
  );

  const win = summary?.win_rate;

  return (
    <div className="page">
      <PageHeader
        crumb="F&O Positions"
        title="F&O Positions"
        subtitle="Live index/stock option chains and futures off your Dhan account — buy or sell CE/PE and futures with real premiums and hedge-aware SPAN-style portfolio margin (a bought option that caps a sold option's risk lowers the margin blocked, like a real broker), across multiple paper accounts each with its own editable balance (default ₹1 crore). Not investment advice."
        actions={
          <div className="account-bar">
            {accounts.length > 0 && (
              <select
                className="account-select"
                value={accountId ?? ""}
                onChange={(e) => selectAccount(e.target.value)}
              >
                {accounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>{a.name}</option>
                ))}
              </select>
            )}
            <button className="ghost-btn" onClick={() => setCreateAccountOpen(true)}>+ New Account</button>
            <button className="ghost-btn" onClick={() => setEditAccountOpen(true)} disabled={!activeAccount}>Edit</button>
            <button className="reset-cta" onClick={reset} disabled={resetting || !accountId}>
              {resetting ? "Resetting…" : "Reset"}
            </button>
          </div>
        }
      />

      {!accountsLoading && accounts.length === 0 && (
        <div className="notice">No F&amp;O accounts yet — hit <b>+ New Account</b> to create your first paper account.</div>
      )}

      {summary && (
        <div className="capital-tiles">
          <div className="tile"><span className="label">Initial capital</span><span className="value">{inr(summary.initial_capital)}</span></div>
          <div className="tile"><span className="label">Equity</span><span className={`value ${summary.equity >= summary.initial_capital ? "gain" : "loss"}`}>{inr(summary.equity)}</span></div>
          <div className="tile"><span className="label">Total P&amp;L</span><span className={`value ${summary.total_pnl >= 0 ? "gain" : "loss"}`}>{inr(summary.total_pnl)}</span></div>
          <div className="tile"><span className="label">ROI</span><span className={`value ${summary.roi_pct >= 0 ? "gain" : "loss"}`}>{summary.roi_pct >= 0 ? "+" : ""}{summary.roi_pct.toFixed(2)}%</span></div>
          <div className="tile"><span className="label">Win %</span><span className="value">{win === null || win === undefined ? "-" : `${win.toFixed(1)}%`}</span></div>
          <div className="tile"><span className="label">Margin deployed (netted)</span><span className="value">{inr(summary.deployed_margin)}</span></div>
          {(summary.margin_benefit ?? 0) > 0 && (
            <div className="tile"><span className="label">Hedge benefit</span><span className="value gain">−{inr(summary.margin_benefit)}</span></div>
          )}
          <div className="tile"><span className="label">Available cash</span><span className="value">{inr(summary.available_cash)}</span></div>
        </div>
      )}

      <div className="tabs">
        {(["chain", "futures", "movers", "positions", "orders"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {t === "chain" ? "Option Chain" : t === "futures" ? "Futures" : t === "movers" ? "Top Movers" : t === "positions" ? "Positions" : "Orders"}
            {t === "positions" && <span className="count">{summary?.open_positions ?? 0}</span>}
          </button>
        ))}
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="notice">{notice}</div>}

      {tab === "chain" && (
        <GlassPanel title="Option Chain" note={chain ? `Spot ${inr(chain.spot)} · PCR(OI) ${chain.pcr_oi ?? "-"} · Max pain ${chain.max_pain ?? "-"}` : undefined}>
          <div className="chain-controls">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {underlyings.map((u) => (
                <option key={u.symbol} value={u.symbol}>{u.symbol} ({u.kind})</option>
              ))}
            </select>
            <select value={expiry} onChange={(e) => setExpiry(e.target.value)} disabled={!expiries.length}>
              {expiries.map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
          </div>
          {chainLoading ? (
            <div className="empty">Loading chain…</div>
          ) : !chain || chain.strikes.length === 0 ? (
            <div className="empty">No chain data — connect your Dhan account under Broker Settings.</div>
          ) : liveStrikes.length === 0 ? (
            <div className="empty">No strikes are trading yet for this expiry — premiums appear once the market is open.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table chain-table">
                <thead>
                  <tr>
                    <th colSpan={4}>CALLS</th>
                    <th>Strike</th>
                    <th colSpan={4}>PUTS</th>
                  </tr>
                  <tr>
                    <th>OI</th><th>Vol</th><th>LTP</th><th></th>
                    <th></th>
                    <th></th><th>LTP</th><th>Vol</th><th>OI</th>
                  </tr>
                </thead>
                <tbody>
                  {liveStrikes.map((row) => (
                    <tr key={row.strike} className={row.strike === atmStrike ? "atm" : ""}>
                      <td>{(row.ce.oi ?? 0).toLocaleString("en-IN")}</td>
                      <td>{(row.ce.volume ?? 0).toLocaleString("en-IN")}</td>
                      <td className="ltp">{inr(row.ce.last_price)}</td>
                      <td>
                        <div className="chip-pair">
                          <button
                            className="buy-chip"
                            onClick={() =>
                              setDraft({
                                instrument_kind: "OPTION", symbol, expiry, strike: row.strike, option_type: "CE",
                                transaction_type: "BUY", ltp: row.ce.last_price ?? 0, lot_size: 1,
                              })
                            }
                          >
                            Buy CE
                          </button>
                          <button
                            className="sell-chip"
                            onClick={() =>
                              setDraft({
                                instrument_kind: "OPTION", symbol, expiry, strike: row.strike, option_type: "CE",
                                transaction_type: "SELL", ltp: row.ce.last_price ?? 0, lot_size: 1,
                              })
                            }
                          >
                            Sell CE
                          </button>
                        </div>
                      </td>
                      <td className="strike">{row.strike.toLocaleString("en-IN")}</td>
                      <td>
                        <div className="chip-pair">
                          <button
                            className="buy-chip pe"
                            onClick={() =>
                              setDraft({
                                instrument_kind: "OPTION", symbol, expiry, strike: row.strike, option_type: "PE",
                                transaction_type: "BUY", ltp: row.pe.last_price ?? 0, lot_size: 1,
                              })
                            }
                          >
                            Buy PE
                          </button>
                          <button
                            className="sell-chip pe"
                            onClick={() =>
                              setDraft({
                                instrument_kind: "OPTION", symbol, expiry, strike: row.strike, option_type: "PE",
                                transaction_type: "SELL", ltp: row.pe.last_price ?? 0, lot_size: 1,
                              })
                            }
                          >
                            Sell PE
                          </button>
                        </div>
                      </td>
                      <td className="ltp">{inr(row.pe.last_price)}</td>
                      <td>{(row.pe.volume ?? 0).toLocaleString("en-IN")}</td>
                      <td>{(row.pe.oi ?? 0).toLocaleString("en-IN")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "futures" && (
        <GlassPanel title="Futures">
          <div className="chain-controls">
            <select value={futSymbol} onChange={(e) => setFutSymbol(e.target.value)}>
              {underlyings.map((u) => (
                <option key={u.symbol} value={u.symbol}>{u.symbol} ({u.kind})</option>
              ))}
            </select>
            <select value={futExpiry} onChange={(e) => setFutExpiry(e.target.value)} disabled={!futExpiries.length}>
              {futExpiries.map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
          </div>
          {!futExpiries.length ? (
            <div className="empty">No futures contract on file for {futSymbol} — try another underlying.</div>
          ) : (
            <div className="fut-buy-row">
              <button
                className="buy-chip"
                onClick={() => setDraft({ instrument_kind: "FUTURE", symbol: futSymbol, expiry: futExpiry, transaction_type: "BUY", ltp: 0, lot_size: 1 })}
              >
                Buy {futSymbol} FUT ({futExpiry})
              </button>
              <span className="fut-hint">Exit an open futures position from the Positions tab.</span>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "movers" && (
        <GlassPanel title="Today's Top Performing Options" note="Nearest expiry, whitelisted indices only">
          <div className="movers-grid">
            <div>
              <div className="movers-head">Top Calls (CE)</div>
              {(movers?.top_calls ?? []).map((m) => (
                <div key={`${m.symbol}-${m.strike}-CE`} className="mover-row">
                  <span>{m.symbol} {m.strike.toLocaleString("en-IN")}CE</span>
                  <span className="gain">+{m.change_pct.toFixed(2)}%</span>
                  <span>{inr(m.ltp)}</span>
                  <button className="buy-chip" onClick={() => setDraft({ instrument_kind: "OPTION", symbol: m.symbol, expiry: m.expiry, strike: m.strike, option_type: "CE", transaction_type: "BUY", ltp: m.ltp, lot_size: 1 })}>Buy</button>
                </div>
              ))}
              {!movers?.top_calls.length && <div className="empty">No data</div>}
            </div>
            <div>
              <div className="movers-head">Top Puts (PE)</div>
              {(movers?.top_puts ?? []).map((m) => (
                <div key={`${m.symbol}-${m.strike}-PE`} className="mover-row">
                  <span>{m.symbol} {m.strike.toLocaleString("en-IN")}PE</span>
                  <span className="gain">+{m.change_pct.toFixed(2)}%</span>
                  <span>{inr(m.ltp)}</span>
                  <button className="buy-chip pe" onClick={() => setDraft({ instrument_kind: "OPTION", symbol: m.symbol, expiry: m.expiry, strike: m.strike, option_type: "PE", transaction_type: "BUY", ltp: m.ltp, lot_size: 1 })}>Buy</button>
                </div>
              ))}
              {!movers?.top_puts.length && <div className="empty">No data</div>}
            </div>
          </div>
        </GlassPanel>
      )}

      {tab === "positions" && (
        <GlassPanel title="Positions">
          <div className="tabs-row">
            <select value={positionsFilter} onChange={(e) => setPositionsFilter(e.target.value as "OPEN" | "all")}>
              <option value="OPEN">Open</option>
              <option value="all">All (incl. closed)</option>
            </select>
          </div>
          {positions.length === 0 ? (
            <div className="empty">No F&O positions yet — buy a CE/PE from the Option Chain tab or a future from the Futures tab.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Contract</th>
                    <th>Product</th>
                    <th>Lots</th>
                    <th>Avg price</th>
                    <th>LTP</th>
                    <th>Margin (standalone)</th>
                    <th>P&amp;L</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const pnl = p.status === "OPEN" ? p.unrealized_pnl : p.realized_pnl;
                    return (
                      <tr key={p.position_id}>
                        <td style={{ textAlign: "left" }}>
                          <div className="name-cell">
                            <span className="name">{p.display_name}</span>
                            <span className={p.side === "SELL" ? "chip short" : "chip long"}>
                              {p.side === "SELL" ? "SHORT" : "LONG"}
                            </span>
                            {p.status === "CLOSED" && <span className="chip muted">CLOSED</span>}
                          </div>
                        </td>
                        <td>{p.product_type}</td>
                        <td>{p.lots}</td>
                        <td>{inr(p.avg_price)}</td>
                        <td>{inr(p.ltp)}</td>
                        <td>{inr(p.margin_used)}</td>
                        <td className={pnl >= 0 ? "gain" : "loss"}>
                          {inr(pnl)}
                          {p.status === "OPEN" && <span className="pct"> ({p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct.toFixed(2)}%)</span>}
                        </td>
                        <td>{p.status === "OPEN" && <button className="exit-btn" onClick={() => exit(p)}>Exit</button>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {tab === "orders" && (
        <GlassPanel title="Orders">
          {orders.length === 0 ? (
            <div className="empty">No orders yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Contract</th>
                    <th>Side</th>
                    <th>Lots</th>
                    <th>Type</th>
                    <th>Product</th>
                    <th>Price</th>
                    <th>Status</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.order_id}>
                      <td style={{ textAlign: "left" }}>{o.display_name}</td>
                      <td className={o.transaction_type === "BUY" ? "gain" : "loss"}>{o.transaction_type}</td>
                      <td>{o.lots}</td>
                      <td>{o.order_type}{o.order_type === "LIMIT" ? ` @ ${inr(o.limit_price)}` : ""}</td>
                      <td>{o.product_type}</td>
                      <td>{inr(o.fill_price ?? o.limit_price)}</td>
                      <td><span className={`status ${o.status === "FILLED" ? "gain" : "muted"}`}>{o.status}</span></td>
                      <td>{new Date(o.filled_at ?? o.placed_at).toLocaleString("en-IN")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {draft && (
        <OrderModal
          draft={draft}
          accountId={accountId}
          onClose={() => setDraft(null)}
          onDone={(msg) => {
            setDraft(null);
            setNotice(msg);
            loadPositions();
          }}
        />
      )}

      {createAccountOpen && (
        <AccountModal
          mode="create"
          onClose={() => setCreateAccountOpen(false)}
          onSubmit={({ name, initialCapital }) => createAccount(name!, initialCapital)}
        />
      )}

      {editAccountOpen && activeAccount && (
        <AccountModal
          mode="edit"
          initialName={activeAccount.name}
          initialCapital={activeAccount.initial_capital}
          onClose={() => setEditAccountOpen(false)}
          onSubmit={saveAccountEdit}
        />
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .reset-cta { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); font-weight: 700; font-size: 13px; border-radius: 10px; padding: 10px 18px; cursor: pointer; }
        .reset-cta:disabled { opacity: 0.55; cursor: default; }
        .account-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .account-select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; font-size: 13px; font-weight: 700; min-width: 150px; }
        .ghost-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); font-weight: 600; font-size: 13px; border-radius: 10px; padding: 10px 16px; cursor: pointer; }
        .ghost-btn:disabled { opacity: 0.5; cursor: default; }
        .capital-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .capital-tiles .tile { display: flex; flex-direction: column; gap: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; }
        .capital-tiles .label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .capital-tiles .value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .capital-tiles .value.gain { color: var(--gain); }
        .capital-tiles .value.loss { color: var(--loss); }
        .tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .tabs-row { display: flex; justify-content: flex-end; margin-bottom: 10px; }
        .tab { display: flex; align-items: center; gap: 7px; background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .count { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; }
        .tab.active .count { background: var(--purple); color: #fff; border-color: transparent; }
        select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13px; }
        .notice { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12.5px; }
        .empty { padding: 28px 20px; font-size: 13px; color: var(--text-muted); }
        .chain-controls { display: flex; gap: 10px; padding: 14px 20px; border-bottom: 1px solid var(--panel-border); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); background: var(--panel); position: sticky; top: 0; }
        .data-table td { padding: 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .chain-table tr.atm { background: var(--purple-dim); }
        .chain-table td.strike { font-weight: 800; }
        .chain-table td.ltp { font-weight: 700; }
        .name-cell { display: flex; align-items: center; gap: 6px; }
        .name { font-weight: 700; font-size: 13px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700; color: var(--text-muted); }
        .chip.muted { color: var(--text-faint); }
        .chip.long { background: var(--gain-dim); border-color: rgba(14, 159, 110, 0.26); color: var(--gain); }
        .chip.short { background: var(--loss-dim); border-color: rgba(217, 45, 63, 0.26); color: var(--loss); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .pct { font-size: 11px; }
        .status.gain { color: var(--gain); }
        .status.muted { color: var(--text-faint); }
        .exit-btn { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); border-radius: 8px; padding: 6px 14px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
        .buy-chip { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 11px; border: none; border-radius: 7px; padding: 6px 10px; cursor: pointer; }
        .buy-chip.pe { background: linear-gradient(145deg, #7d34dc, #5b23a8); color: #fff; }
        .chip-pair { display: flex; align-items: center; gap: 6px; justify-content: center; }
        .sell-chip { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.3); font-weight: 700; font-size: 11px; border-radius: 7px; padding: 5px 10px; cursor: pointer; }
        .sell-chip:hover { background: rgba(217, 45, 63, 0.18); }
        .fut-buy-row { display: flex; align-items: center; gap: 14px; padding: 20px; }
        .fut-hint { font-size: 12px; color: var(--text-faint); }
        .movers-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 16px 20px; }
        .movers-head { font-weight: 700; font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); margin-bottom: 8px; }
        .mover-row { display: grid; grid-template-columns: 1fr auto auto auto; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--canvas-soft); font-size: 12.5px; }
        @media (max-width: 720px) { .movers-grid { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}

function OrderModal({ draft, accountId, onClose, onDone }: { draft: OrderDraft; accountId: string | null; onClose: () => void; onDone: (msg: string) => void }) {
  const [lotsInput, setLotsInput] = useState("1");
  const lots = Math.max(1, parseInt(lotsInput, 10) || 0);
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [limitPrice, setLimitPrice] = useState<number>(draft.ltp || 0);
  const [productType, setProductType] = useState<FnoProductType>("INTRADAY");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const label =
    draft.instrument_kind === "OPTION"
      ? `${draft.symbol} ${draft.expiry} ${draft.strike?.toLocaleString("en-IN")}${draft.option_type}`
      : `${draft.symbol} ${draft.expiry} FUT`;

  const submit = useCallback(async () => {
    if (!accountId) {
      setErr("Select or create an account first");
      return;
    }
    if (orderType === "LIMIT" && limitPrice <= 0) {
      setErr("Enter a limit price");
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      const result = await placeFnoOrder({
        account_id: accountId,
        instrument_kind: draft.instrument_kind, symbol: draft.symbol, expiry: draft.expiry,
        strike: draft.strike, option_type: draft.option_type, transaction_type: draft.transaction_type,
        lots, order_type: orderType, product_type: productType, limit_price: orderType === "LIMIT" ? limitPrice : 0,
      });
      if (result.status === "PENDING") {
        onDone(`Limit order placed for ${lots} lot(s) of ${label} @ ${limitPrice} — will fill when price is hit`);
      } else {
        onDone(`${draft.transaction_type === "BUY" ? "Bought" : "Sold"} ${lots} lot(s) of ${label} @ ${inr(result.fill_price)} (${productType})`);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Order failed");
    } finally {
      setSubmitting(false);
    }
  }, [accountId, draft, lots, orderType, limitPrice, productType, label, onDone]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">{draft.transaction_type === "BUY" ? "Buy" : "Sell"} {label}</div>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        {draft.ltp > 0 && <div className="ltp-line">Live LTP (at click): <b>{inr(draft.ltp)}</b></div>}

        {draft.transaction_type === "SELL" && (
          <div className="sell-warn">
            Selling collects the premium but blocks <b>margin</b> — typically many times the premium, not the
            premium itself. If this opens a new short rather than closing a long, the downside is unlimited.
            Buying a further-OTM option of the same type as a hedge sharply lowers the margin blocked. Exiting a
            short buys it back.
          </div>
        )}

        <div className="field-row">
          <div className="field">
            <label>Lots</label>
            <input type="number" min={1} inputMode="numeric" value={lotsInput} onChange={(e) => setLotsInput(e.target.value)} onBlur={() => setLotsInput(String(lots))} />
          </div>
          <div className="field">
            <label>Order type</label>
            <select value={orderType} onChange={(e) => setOrderType(e.target.value as "MARKET" | "LIMIT")}>
              <option value="MARKET">Market</option>
              <option value="LIMIT">Limit</option>
            </select>
          </div>
        </div>

        {orderType === "LIMIT" && (
          <div className="field">
            <label>Limit price (₹)</label>
            <input type="number" min={0} step="0.05" value={limitPrice || ""} onChange={(e) => setLimitPrice(parseFloat(e.target.value) || 0)} />
          </div>
        )}

        <div className="field">
          <label>Product type</label>
          <div className="product-row">
            {PRODUCT_TYPES.map((pt) => (
              <button key={pt.id} className={productType === pt.id ? "product-btn active" : "product-btn"} onClick={() => setProductType(pt.id)}>
                {pt.label}
              </button>
            ))}
          </div>
        </div>

        {err && <div className="err">{err}</div>}

        <button className="submit-btn" onClick={submit} disabled={submitting}>
          {submitting ? "Placing order…" : `${draft.transaction_type === "BUY" ? "Buy" : "Sell"} ${lots} lot(s)`}
        </button>
      </div>

      <style jsx>{`
        .modal-scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 5vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 14px; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-family: var(--font-display); font-weight: 800; font-size: 16px; }
        .modal-close { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input, .field select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .field-row { display: flex; gap: 12px; }
        .field-row .field { flex: 1; min-width: 0; }
        .product-row { display: flex; flex-wrap: wrap; gap: 6px; }
        .product-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 8px 10px; font-size: 11.5px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .product-btn.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .ltp-line { font-size: 12.5px; color: var(--text-muted); }
        .sell-warn { background: var(--loss-dim); border: 1px solid rgba(217, 45, 63, 0.26); border-radius: 8px; padding: 9px 11px; font-size: 11.5px; line-height: 1.5; color: var(--loss); }
        .err { color: var(--loss); font-size: 12px; }
        .submit-btn { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 12px; cursor: pointer; }
        .submit-btn:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}

const QUICK_BALANCES: { label: string; value: number }[] = [
  { label: "₹10 L", value: 1000000 },
  { label: "₹50 L", value: 5000000 },
  { label: "₹1 Cr", value: 10000000 },
  { label: "₹5 Cr", value: 50000000 },
];

function AccountModal({
  mode, initialName, initialCapital, onClose, onSubmit,
}: {
  mode: "create" | "edit";
  initialName?: string;
  initialCapital?: number;
  onClose: () => void;
  onSubmit: (changes: { name?: string; initialCapital?: number }) => Promise<void> | void;
}) {
  const [name, setName] = useState(initialName ?? "");
  const [balanceInput, setBalanceInput] = useState(String(initialCapital ?? 10000000));
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const balance = Math.round(parseFloat(balanceInput) || 0);
  const isEdit = mode === "edit";

  const submit = useCallback(async () => {
    if (!name.trim()) {
      setErr("Enter an account name");
      return;
    }
    if (balance <= 0) {
      setErr("Balance must be a positive amount");
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      await onSubmit({ name: name.trim(), initialCapital: balance });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
      setSubmitting(false);
    }
  }, [name, balance, onSubmit]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">{isEdit ? "Edit account" : "New account"}</div>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="field">
          <label>Account name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Swing Trading" autoFocus />
        </div>

        <div className="field">
          <label>{isEdit ? "Account balance (₹)" : "Starting balance (₹)"}</label>
          <input type="number" min={0} step="1" inputMode="numeric" value={balanceInput} onChange={(e) => setBalanceInput(e.target.value)} />
          <div className="balance-line">= <b>{balance.toLocaleString("en-IN")}</b> {isEdit ? "base capital" : "paper capital"}</div>
          <div className="quick-row">
            {QUICK_BALANCES.map((q) => (
              <button key={q.value} className={balance === q.value ? "quick-btn active" : "quick-btn"} onClick={() => setBalanceInput(String(q.value))}>
                {q.label}
              </button>
            ))}
          </div>
          {isEdit && (
            <div className="edit-note">
              Changing the balance only moves the base capital pool. Your open positions and realized/unrealized
              P&amp;L are untouched — available cash simply re-derives from the new base.
            </div>
          )}
        </div>

        {err && <div className="err">{err}</div>}

        <button className="submit-btn" onClick={submit} disabled={submitting}>
          {submitting ? "Saving…" : isEdit ? "Save changes" : "Create account"}
        </button>
      </div>

      <style jsx>{`
        .modal-scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 8vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 420px; display: flex; flex-direction: column; gap: 14px; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-family: var(--font-display); font-weight: 800; font-size: 16px; }
        .modal-close { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .balance-line { font-size: 12.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .quick-row { display: flex; flex-wrap: wrap; gap: 6px; }
        .quick-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 7px 12px; font-size: 12px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .quick-btn.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .edit-note { font-size: 11.5px; line-height: 1.5; color: var(--text-faint); background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 9px 11px; }
        .err { color: var(--loss); font-size: 12px; }
        .submit-btn { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 12px; cursor: pointer; }
        .submit-btn:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}
