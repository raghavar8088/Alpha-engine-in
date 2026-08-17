"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import PageHeader from "../../components/PageHeader";
import ErrorBanner from "../../components/ErrorBanner";
import {
  refreshing,
  ManualAccount,
  ManualInstrument,
  ManualOrder,
  ManualPosition,
  ManualPositionsSummary,
  ManualProductType,
  cancelManualOrder,
  createManualAccount,
  estimateManualMargin,
  exitManualPosition,
  fetchManualAccounts,
  fetchManualOrders,
  fetchManualPositions,
  fetchManualQuote,
  placeManualOrder,
  resetManualPositions,
  searchManualInstruments,
} from "../../lib/api";

const SELECTED_ACCOUNT_KEY = "tradingai:manual-positions:selected-account";

const DEFAULT_BUY_NOTIONAL = 100_000; // pre-filled quantity targets ~1L notional; user can still edit
const DEFAULT_PRODUCT_TYPE: ManualProductType = "MTF";

const PRODUCT_TYPES: { id: ManualProductType; label: string }[] = [
  { id: "CNC", label: "CNC (Delivery)" },
  { id: "MTF", label: "MTF (Margin Trade Funding)" },
  { id: "MARGIN", label: "Margin" },
  { id: "INTRADAY", label: "Intraday" },
];

const inr = (v: number | null | undefined) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function PositionsPage() {
  const [accounts, setAccounts] = useState<ManualAccount[]>([]);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [createAccountOpen, setCreateAccountOpen] = useState(false);

  const [tab, setTab] = useState<"positions" | "orders">("positions");
  const [positions, setPositions] = useState<ManualPosition[]>([]);
  const [summary, setSummary] = useState<ManualPositionsSummary | null>(null);
  const [orders, setOrders] = useState<ManualOrder[]>([]);
  const [positionsFilter, setPositionsFilter] = useState<"OPEN" | "all">("OPEN");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [buyOpen, setBuyOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  const loadAccounts = useCallback(async () => {
    setAccountsLoading(true);
    try {
      const data = await fetchManualAccounts();
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

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => loadAccounts());
    } finally {
      setIsRefreshing(false);
    }
  }, [loadAccounts]);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  const selectAccount = useCallback((id: string) => {
    setAccountId(id);
    if (typeof window !== "undefined") window.localStorage.setItem(SELECTED_ACCOUNT_KEY, id);
  }, []);

  const loadPositions = useCallback(async () => {
    if (!accountId) return;
    setError(null);
    try {
      const data = await fetchManualPositions(accountId, positionsFilter === "all" ? undefined : positionsFilter);
      setPositions(data.positions);
      setSummary(data.summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, [accountId, positionsFilter]);

  const loadOrders = useCallback(async () => {
    if (!accountId) return;
    try {
      const data = await fetchManualOrders(accountId);
      setOrders(data.orders);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load orders");
    }
  }, [accountId]);

  useEffect(() => {
    if (!accountId) return;
    loadPositions();
    const timer = setInterval(loadPositions, 20_000);
    return () => clearInterval(timer);
  }, [accountId, loadPositions]);

  useEffect(() => {
    if (tab === "orders") loadOrders();
  }, [tab, loadOrders]);

  const exit = useCallback(
    async (position: ManualPosition) => {
      if (!accountId) return;
      if (!window.confirm(`Exit ${position.quantity} ${position.symbol} @ market?`)) return;
      try {
        const result = await exitManualPosition(accountId, position.position_id);
        setNotice(`Exited ${position.symbol} at ${inr(result.fill_price)} (realized P&L ${inr(result.position.realized_pnl)})`);
        await loadPositions();
      } catch (e) {
        setNotice(`Exit failed: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [accountId, loadPositions],
  );

  const cancelOrder = useCallback(
    async (order: ManualOrder) => {
      if (!accountId) return;
      if (!window.confirm(`Cancel the pending ${order.order_type} order for ${order.quantity} ${order.symbol}?`)) return;
      try {
        await cancelManualOrder(accountId, order.order_id);
        setNotice(`Cancelled pending order for ${order.symbol}`);
        await loadOrders();
      } catch (e) {
        setNotice(`Cancel failed: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [accountId, loadOrders],
  );

  const reset = useCallback(async () => {
    if (!accountId) return;
    const account = accounts.find((a) => a.account_id === accountId);
    if (
      !window.confirm(
        `Reset "${account?.name ?? "this"}" account? This permanently deletes every position and order in it and restores ${inr(account?.initial_capital ?? 10000000)} initial capital. Other accounts are untouched. This cannot be undone.`,
      )
    )
      return;
    setResetting(true);
    try {
      const result = await resetManualPositions(accountId);
      setNotice(`Reset complete — ${result.positions_deleted} position(s) and ${result.orders_deleted} order(s) cleared, capital restored to ${inr(result.initial_capital)}`);
      await Promise.all([loadPositions(), loadOrders()]);
    } catch (e) {
      setNotice(`Reset failed: ${e instanceof Error ? e.message : "unknown error"}`);
    } finally {
      setResetting(false);
    }
  }, [accountId, accounts, loadPositions, loadOrders]);

  const createAccount = useCallback(
    async (name: string) => {
      try {
        const account = await createManualAccount(name);
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

  const win = summary?.win_rate;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Positions"
        title="Positions"
        subtitle="Manual paper trading desk — search a stock on NSE or BSE, buy it with a market or limit order, optionally via MTF leverage. Real Dhan prices and real Dhan margin/leverage figures, ₹1 crore paper capital. Not investment advice."
        actions={
          <>
            {accounts.length > 0 && (
              <select
                className="account-select"
                value={accountId ?? ""}
                onChange={(e) => selectAccount(e.target.value)}
              >
                {accounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.name}
                  </option>
                ))}
              </select>
            )}
            <button className="account-cta" onClick={() => setCreateAccountOpen(true)}>
              + New Account
            </button>
            <button className="reset-cta" onClick={reset} disabled={resetting || !accountId}>
              {resetting ? "Resetting…" : "Reset"}
            </button>
            <button className="buy-cta" onClick={() => setBuyOpen(true)} disabled={!accountId}>
              + Buy
            </button>
          </>
        }
      />

      {accountsLoading ? (
        <div className="empty">Loading accounts…</div>
      ) : accounts.length === 0 ? (
        <GlassPanel>
          <div className="empty">
            No trading accounts yet — hit <b>+ New Account</b> to create your first paper trading account.
          </div>
        </GlassPanel>
      ) : (
        <>
      {summary && (
        <div className="capital-tiles">
          <div className="tile">
            <span className="label">Initial capital</span>
            <span className="value">{inr(summary.initial_capital)}</span>
          </div>
          <div className="tile">
            <span className="label">Total capital (equity)</span>
            <span className={`value ${summary.equity >= summary.initial_capital ? "gain" : "loss"}`}>{inr(summary.equity)}</span>
          </div>
          <div className="tile">
            <span className="label">Total P&amp;L</span>
            <span className={`value ${summary.total_pnl >= 0 ? "gain" : "loss"}`}>{inr(summary.total_pnl)}</span>
          </div>
          <div className="tile">
            <span className="label">ROI</span>
            <span className={`value ${summary.roi_pct >= 0 ? "gain" : "loss"}`}>
              {summary.roi_pct >= 0 ? "+" : ""}
              {summary.roi_pct.toFixed(2)}%
            </span>
          </div>
          <div className="tile">
            <span className="label">Win %</span>
            <span className="value">{win === null || win === undefined ? "-" : `${win.toFixed(1)}%`}</span>
          </div>
          <div className="tile">
            <span className="label">Margin deployed</span>
            <span className="value">{inr(summary.deployed_margin)}</span>
          </div>
          <div className="tile">
            <span className="label">Available cash</span>
            <span className="value">{inr(summary.available_cash)}</span>
          </div>
        </div>
      )}

      <div className="tabs-row">
        <div className="tabs">
          <button className={tab === "positions" ? "tab active" : "tab"} onClick={() => setTab("positions")}>
            Positions
            <span className="count">{summary?.open_positions ?? 0}</span>
          </button>
          <button className={tab === "orders" ? "tab active" : "tab"} onClick={() => setTab("orders")}>
            Orders
          </button>
        </div>
        {tab === "positions" && (
          <select value={positionsFilter} onChange={(e) => setPositionsFilter(e.target.value as "OPEN" | "all")}>
            <option value="OPEN">Open</option>
            <option value="all">All (incl. closed)</option>
          </select>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="notice">{notice}</div>}

      {tab === "positions" ? (
        <GlassPanel title="Positions">
          {loading ? (
            <div className="empty">Loading…</div>
          ) : positions.length === 0 ? (
            <div className="empty">
              No positions yet — hit <b>+ Buy</b> to search a stock and place your first paper trade.
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Symbol</th>
                    <th>Product</th>
                    <th>Qty</th>
                    <th>Avg price</th>
                    <th>LTP</th>
                    <th>Invested</th>
                    <th>Leverage</th>
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
                            <span className="name">{p.symbol}</span>
                            <span className="chip">{p.instrument.exchange_segment === "BSE_EQ" ? "BSE" : "NSE"}</span>
                            {p.status === "CLOSED" && <span className="chip muted">CLOSED</span>}
                          </div>
                        </td>
                        <td>{p.product_type}</td>
                        <td>{p.quantity}</td>
                        <td>{inr(p.avg_price)}</td>
                        <td>{inr(p.ltp)}</td>
                        <td>{inr(p.margin_used)}</td>
                        <td>
                          {p.leverage > 1 ? `${p.leverage.toFixed(2)}x` : "1x"}
                          {p.margin_source === "fallback" && (
                            <span className="src-star" title="Dhan's margin calculator was unreachable when this position was opened — shown as 1x/full notional, not a verified figure">*</span>
                          )}
                        </td>
                        <td className={pnl >= 0 ? "gain" : "loss"}>
                          {inr(pnl)}
                          {p.status === "OPEN" && <span className="pct"> ({p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct.toFixed(2)}%)</span>}
                        </td>
                        <td>
                          {p.status === "OPEN" && (
                            <button className="exit-btn" onClick={() => exit(p)}>
                              Exit
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      ) : (
        <GlassPanel title="Orders">
          {orders.length === 0 ? (
            <div className="empty">No orders yet.</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Symbol</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Type</th>
                    <th>Product</th>
                    <th>Price</th>
                    <th>Status</th>
                    <th>Time</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.order_id}>
                      <td style={{ textAlign: "left" }}>{o.symbol}</td>
                      <td className={o.transaction_type === "BUY" ? "gain" : "loss"}>{o.transaction_type}</td>
                      <td>{o.quantity}</td>
                      <td>{o.order_type}{o.order_type === "LIMIT" ? ` @ ${inr(o.limit_price)}` : ""}</td>
                      <td>{o.product_type}</td>
                      <td>{inr(o.fill_price ?? o.limit_price)}</td>
                      <td>
                        <span className={`status ${o.status === "FILLED" ? "gain" : "muted"}`}>{o.status}</span>
                      </td>
                      <td>{new Date(o.filled_at ?? o.placed_at).toLocaleString("en-IN")}</td>
                      <td>
                        {o.status === "PENDING" && (
                          <button className="cancel-order-btn" onClick={() => cancelOrder(o)}>
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {buyOpen && accountId && (
        <BuyModal
          accountId={accountId}
          existingPositions={positions}
          onClose={() => setBuyOpen(false)}
          onDone={(msg) => {
            setBuyOpen(false);
            setNotice(msg);
            loadPositions();
          }}
        />
      )}
        </>
      )}

      {createAccountOpen && (
        <CreateAccountModal onClose={() => setCreateAccountOpen(false)} onCreate={createAccount} />
      )}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .buy-cta { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13px; border: none; border-radius: 10px; padding: 10px 20px; cursor: pointer; }
        .buy-cta:disabled { opacity: 0.5; cursor: default; }
        .reset-cta { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); font-weight: 700; font-size: 13px; border-radius: 10px; padding: 10px 18px; cursor: pointer; }
        .account-select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 12px; font-size: 13px; font-weight: 600; min-width: 140px; }
        .account-cta { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); font-weight: 700; font-size: 12.5px; border-radius: 10px; padding: 10px 16px; cursor: pointer; }
        .reset-cta:disabled { opacity: 0.55; cursor: default; }
        .capital-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .capital-tiles .tile { display: flex; flex-direction: column; gap: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; }
        .capital-tiles .label { font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
        .capital-tiles .value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .capital-tiles .value.gain { color: var(--gain); }
        .capital-tiles .value.loss { color: var(--loss); }
        .tabs-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .tabs { display: flex; gap: 8px; }
        .tab {
          display: flex; align-items: center; gap: 7px;
          background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
          padding: 9px 16px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
        }
        .tab.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .count { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 20px; padding: 1px 8px; font-size: 10.5px; }
        .tab.active .count { background: var(--purple); color: #fff; border-color: transparent; }
        select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 9px 12px; font-size: 13px; }
        .notice { padding: 10px 14px; border-radius: 9px; background: var(--canvas-soft); border: 1px solid var(--panel-border); font-size: 12.5px; }
        .empty { padding: 28px 20px; font-size: 13px; color: var(--text-muted); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 9px 12px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); background: var(--panel); position: sticky; top: 0; }
        .data-table td { padding: 12px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .name-cell { display: flex; align-items: center; gap: 6px; }
        .name { font-weight: 700; font-size: 13px; }
        .chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700; color: var(--text-muted); }
        .chip.muted { color: var(--text-faint); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .pct { font-size: 11px; }
        .src-star { color: var(--accent); margin-left: 2px; cursor: help; }
        .status.gain { color: var(--gain); }
        .status.muted { color: var(--text-faint); }
        .exit-btn { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217, 45, 63, 0.26); border-radius: 8px; padding: 6px 14px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
        .cancel-order-btn { background: var(--canvas-soft); color: var(--text-muted); border: 1px solid var(--panel-border); border-radius: 8px; padding: 6px 14px; font-size: 11.5px; font-weight: 700; cursor: pointer; }
      `}</style>
    </div>
  );
}

function BuyModal({
  accountId,
  existingPositions,
  onClose,
  onDone,
}: {
  accountId: string;
  existingPositions: ManualPosition[];
  onClose: () => void;
  onDone: (msg: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ManualInstrument[]>([]);
  const [selected, setSelected] = useState<ManualInstrument | null>(null);
  const [quantityInput, setQuantityInput] = useState("1");
  const quantity = Math.max(1, parseInt(quantityInput, 10) || 0);
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [limitPrice, setLimitPrice] = useState<number>(0);
  const [productType, setProductType] = useState<ManualProductType>(DEFAULT_PRODUCT_TYPE);
  const [margin, setMargin] = useState<{ margin_required: number; leverage: number; notional_value: number; source: "dhan_calculator" | "fallback" } | null>(null);
  const [ltp, setLtp] = useState<number | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 1 || selected) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        setResults(await searchManualInstruments(q));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query, selected]);

  const select = useCallback(async (inst: ManualInstrument) => {
    setSelected(inst);
    setResults([]);
    setQuery(`${inst.symbol} (${inst.exchange_segment === "BSE_EQ" ? "BSE" : "NSE"})`);
    setMargin(null);
    setLtp(null);
    setQuoteError(null);
    setProductType(DEFAULT_PRODUCT_TYPE);
    try {
      const q = await fetchManualQuote(inst.security_id, inst.exchange_segment);
      setLtp(q.ltp);
      setLimitPrice(q.ltp);
      // Pre-fill quantity so notional is at least DEFAULT_BUY_NOTIONAL — ceil, not
      // round, so it never lands a hair under 1L (e.g. 73 shares @ 1368 = 99,864).
      // A little over is fine, under is not. Still freely editable either way.
      if (q.ltp > 0) setQuantityInput(String(Math.max(1, Math.ceil(DEFAULT_BUY_NOTIONAL / q.ltp))));
    } catch (e) {
      setQuoteError(e instanceof Error ? e.message : "Could not fetch a live quote");
    }
  }, []);

  const priceForMargin = orderType === "LIMIT" ? limitPrice : ltp ?? 0;

  useEffect(() => {
    if (!selected || priceForMargin <= 0) return;
    let cancelled = false;
    const t = setTimeout(() => {
      estimateManualMargin({
        security_id: selected.security_id, exchange_segment: selected.exchange_segment,
        transaction_type: "BUY", quantity, product_type: productType, price: priceForMargin,
      })
        .then((est) => !cancelled && setMargin(est))
        .catch(() => !cancelled && setMargin(null));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [selected, quantity, productType, priceForMargin]);

  const submit = useCallback(async () => {
    if (!selected) return;
    if (orderType === "LIMIT" && limitPrice <= 0) {
      setErr("Enter a limit price");
      return;
    }

    const existingPosition = existingPositions.find((p) => p.status === "OPEN" && p.symbol === selected.symbol);
    let existingPendingOrder: ManualOrder | undefined;
    try {
      const pending = await fetchManualOrders(accountId, "PENDING");
      existingPendingOrder = pending.orders.find((o) => o.symbol === selected.symbol);
    } catch {
      // if the pending-order check itself fails, don't block the buy over it
    }

    let forceNewPosition = false;
    if (existingPosition || existingPendingOrder) {
      const detail = existingPosition
        ? `an open position (${existingPosition.quantity} qty, ${existingPosition.product_type})`
        : `a pending ${existingPendingOrder!.order_type} order (${existingPendingOrder!.quantity} qty, ${existingPendingOrder!.product_type})`;
      const proceed = window.confirm(
        `${selected.symbol} already has ${detail}.\n\n` +
          `Click OK to open this as a brand new, separate position (it will NOT merge with the existing one).\n` +
          `Click Cancel to stop without placing an order.`,
      );
      if (!proceed) return;
      forceNewPosition = true;
    }

    setSubmitting(true);
    setErr(null);
    try {
      const result = await placeManualOrder({
        account_id: accountId,
        security_id: selected.security_id, exchange_segment: selected.exchange_segment,
        transaction_type: "BUY", quantity, order_type: orderType, product_type: productType,
        limit_price: orderType === "LIMIT" ? limitPrice : 0,
        force_new_position: forceNewPosition,
      });
      if (result.status === "PENDING") {
        onDone(`Limit order placed for ${quantity} ${selected.symbol} @ ${limitPrice} — will fill when price is hit`);
      } else {
        onDone(`Bought ${quantity} ${selected.symbol} @ ${result.fill_price} (${productType})`);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Order failed");
    } finally {
      setSubmitting(false);
    }
  }, [accountId, selected, quantity, orderType, limitPrice, productType, existingPositions, onDone]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">Buy stock</div>
          <button className="modal-close" onClick={onClose}>
            &times;
          </button>
        </div>

        <div className="field">
          <label>Search NSE / BSE</label>
          <input
            placeholder="Search stock name or symbol"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelected(null);
            }}
            autoFocus
          />
          {!selected && query.trim().length >= 1 && (
            <div className="dropdown">
              {results.length > 0 ? (
                results.map((r) => (
                  <button
                    key={`${r.exchange_segment}-${r.security_id}`}
                    type="button"
                    className="dropdown-item"
                    onClick={() => select(r)}
                  >
                    <span className="dsym">{r.symbol}</span>
                    <span className="dname">{r.name}</span>
                    <span className={`dseg ${r.exchange_segment === "BSE_EQ" ? "bse" : "nse"}`}>
                      {r.exchange_segment === "BSE_EQ" ? "BSE" : "NSE"}
                    </span>
                  </button>
                ))
              ) : (
                <div className="dropdown-empty">{searching ? "Searching…" : "No matching stocks"}</div>
              )}
            </div>
          )}
        </div>

        {selected && (
          <>
            <div className="field-row">
              <div className="field">
                <label>Quantity</label>
                <input
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={quantityInput}
                  onChange={(e) => setQuantityInput(e.target.value)}
                  onBlur={() => setQuantityInput(String(quantity))}
                />
              </div>
              <div className="field">
                <label>Order type</label>
                <select value={orderType} onChange={(e) => setOrderType(e.target.value as "MARKET" | "LIMIT")}>
                  <option value="MARKET">Market</option>
                  <option value="LIMIT">Limit</option>
                </select>
              </div>
            </div>

            {quoteError && <div className="err">{quoteError}</div>}
            {ltp !== null && (
              <div className="ltp-line">
                Live LTP: <b>{inr(ltp)}</b>
              </div>
            )}

            {orderType === "LIMIT" && (
              <div className="field">
                <label>Limit price (₹)</label>
                <input
                  type="number"
                  min={0}
                  step="0.05"
                  value={limitPrice || ""}
                  onChange={(e) => setLimitPrice(parseFloat(e.target.value) || 0)}
                />
              </div>
            )}

            <div className="field">
              <label>Product type</label>
              <div className="product-row">
                {PRODUCT_TYPES.map((pt) => (
                  <button
                    key={pt.id}
                    className={productType === pt.id ? "product-btn active" : "product-btn"}
                    onClick={() => setProductType(pt.id)}
                  >
                    {pt.label}
                  </button>
                ))}
              </div>
            </div>

            {margin && (
              <div className={`margin-box ${margin.source === "fallback" ? "warn" : ""}`}>
                <span>Notional value: {inr(margin.notional_value)}</span>
                <span>Margin required: {inr(margin.margin_required)}</span>
                <span className="leverage">Leverage: {margin.leverage.toFixed(2)}x</span>
                {margin.source === "fallback" && (
                  <span className="margin-warn">
                    ⚠ Dhan's margin calculator is unreachable right now, so this is just the full notional
                    value with no leverage assumed — not {productType}'s real margin. Try again shortly for
                    {productType === "CNC" ? "" : ` ${productType}'s`} actual figure.
                  </span>
                )}
              </div>
            )}

            {err && <div className="err">{err}</div>}

            <button className="submit-btn" onClick={submit} disabled={submitting}>
              {submitting ? "Placing order…" : `Buy ${quantity} ${selected.symbol}`}
            </button>
          </>
        )}
      </div>

      <style jsx>{`
        .modal-scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 5vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 14px; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-family: var(--font-display); font-weight: 800; font-size: 17px; }
        .modal-close { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input, .field select { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .field-row { display: flex; gap: 12px; }
        .field-row .field { flex: 1; min-width: 0; }
        .dropdown { margin-top: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; max-height: 260px; overflow-y: auto; -webkit-overflow-scrolling: touch; }
        .dropdown-item { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; padding: 12px; background: none; border: none; border-bottom: 1px solid var(--panel-border); cursor: pointer; font-size: 13.5px; }
        .dropdown-item:last-child { border-bottom: none; }
        .dropdown-item:hover, .dropdown-item:active { background: var(--panel); }
        .dsym { font-weight: 700; min-width: 74px; flex-shrink: 0; }
        .dname { flex: 1; color: var(--text-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .dseg { font-size: 10px; font-weight: 800; flex-shrink: 0; padding: 2px 6px; border-radius: 5px; letter-spacing: 0.03em; }
        .dseg.nse { color: #1d4f91; background: rgba(29, 79, 145, 0.12); }
        .dseg.bse { color: #b45309; background: rgba(180, 83, 9, 0.12); }
        .dropdown-empty { padding: 14px 12px; font-size: 13px; color: var(--text-faint); text-align: center; }
        .product-row { display: flex; flex-wrap: wrap; gap: 6px; }
        .product-btn { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 8px; padding: 8px 10px; font-size: 11.5px; font-weight: 600; color: var(--text-muted); cursor: pointer; }
        .product-btn.active { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .margin-box { display: flex; flex-direction: column; gap: 4px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 10px 12px; font-size: 12px; }
        .margin-box .leverage { font-weight: 700; color: var(--purple); }
        .margin-box.warn { background: rgba(217, 160, 45, 0.1); border-color: rgba(217, 160, 45, 0.35); }
        .margin-warn { color: #92620a; font-size: 11px; line-height: 1.4; margin-top: 2px; }
        .ltp-line { font-size: 12.5px; color: var(--text-muted); }
        .err { color: var(--loss); font-size: 12px; }
        .submit-btn { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 12px; cursor: pointer; }
        .submit-btn:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}

function CreateAccountModal({ onClose, onCreate }: { onClose: () => void; onCreate: (name: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    try {
      await onCreate(trimmed);
    } finally {
      setSubmitting(false);
    }
  }, [name, onCreate]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">New trading account</div>
          <button className="modal-close" onClick={onClose}>
            &times;
          </button>
        </div>

        <div className="field">
          <label>Account name</label>
          <input
            placeholder="e.g. Momentum Strategy, Swing Trades"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            autoFocus
          />
        </div>

        <p className="account-note">Starts with its own independent ₹1 crore paper capital, separate from every other account.</p>

        <button className="submit-btn" onClick={submit} disabled={submitting || !name.trim()}>
          {submitting ? "Creating…" : "Create account"}
        </button>
      </div>

      <style jsx>{`
        .modal-scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5); display: flex; align-items: flex-start; justify-content: center; z-index: 50; padding: 5vh 16px 16px; overflow-y: auto; }
        .modal { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 16px; padding: 20px; width: 100%; max-width: 380px; display: flex; flex-direction: column; gap: 14px; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; }
        .modal-title { font-family: var(--font-display); font-weight: 800; font-size: 17px; }
        .modal-close { background: none; border: none; font-size: 26px; line-height: 1; color: var(--text-muted); cursor: pointer; padding: 0 4px; }
        .field { display: flex; flex-direction: column; gap: 6px; }
        .field label { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
        .field input { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 11px 12px; font-size: 16px; width: 100%; }
        .account-note { margin: 0; font-size: 12px; color: var(--text-muted); }
        .submit-btn { background: linear-gradient(145deg, var(--accent), var(--accent-hover)); color: #241404; font-weight: 700; font-size: 13.5px; border: none; border-radius: 10px; padding: 12px; cursor: pointer; }
        .submit-btn:disabled { opacity: 0.55; cursor: default; }
      `}</style>
    </div>
  );
}
