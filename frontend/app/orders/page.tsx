"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { fetchOrders, placeOrder, PlaceOrderRequest } from "@/lib/api";
import { useBrokerOrdersSocket } from "@/lib/useBrokerOrdersSocket";
import GlassPanel from "@/components/GlassPanel";
import StatusPill from "@/components/StatusPill";
import PageHeader from "@/components/PageHeader";

const initialForm: PlaceOrderRequest = {
  security_id: "",
  exchange_segment: "NSE_EQ",
  transaction_type: "BUY",
  quantity: 1,
  order_type: "MARKET",
  product_type: "CNC",
  price: 0,
  paper_trading: true,
};

interface PaperOrder {
  order_id: string;
  security_id: string;
  status: string;
  transaction_type: string;
  quantity: number;
  price: number;
  created_at: string;
}

interface LiveOrder {
  orderId: string;
  tradingSymbol: string;
  orderStatus: string;
  transactionType: string;
  quantity: number;
  price: number;
  createTime: string;
}

interface NormalizedOrder {
  id: string;
  symbol: string;
  status: string;
  side: string;
  qty: number;
  price: number;
  time: string;
  isPaper: boolean;
}

function statusTone(status: string): "gain" | "loss" | "warn" | "muted" {
  const s = status.toUpperCase();
  if (["TRADED", "FILLED", "COMPLETE"].includes(s)) return "gain";
  if (["REJECTED", "CANCELLED"].includes(s)) return "loss";
  if (["PENDING", "OPEN", "TRANSIT"].includes(s)) return "warn";
  return "muted";
}

export default function OrdersPage() {
  const [form, setForm] = useState<PlaceOrderRequest>(initialForm);
  const [orders, setOrders] = useState<{ paper_orders: PaperOrder[]; live_orders: LiveOrder[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    refreshOrders();
  }, []);

  const liveUpdates = useBrokerOrdersSocket();

  async function refreshOrders() {
    try {
      setOrders(await fetchOrders());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load orders");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await placeOrder(form);
      await refreshOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to place order");
    } finally {
      setSubmitting(false);
    }
  }

  const rows: NormalizedOrder[] = [
    ...(orders?.paper_orders ?? []).map((o) => ({
      id: o.order_id,
      symbol: o.security_id,
      status: o.status,
      side: o.transaction_type,
      qty: o.quantity,
      price: o.price,
      time: o.created_at,
      isPaper: true,
    })),
    ...(orders?.live_orders ?? []).map((o) => ({
      id: o.orderId,
      symbol: o.tradingSymbol,
      status: o.orderStatus,
      side: o.transactionType,
      qty: o.quantity,
      price: o.price,
      time: o.createTime,
      isPaper: false,
    })),
  ].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());

  return (
    <div>
      <PageHeader crumb="Orders" title="Orders" subtitle="Place paper or live orders and track fills in real time." />

      <GlassPanel title="Place Order" style={{ marginBottom: 20 }}>
        <form onSubmit={handleSubmit} className="order-form">
          <input
            placeholder="Security ID"
            value={form.security_id}
            onChange={(e) => setForm({ ...form, security_id: e.target.value })}
            required
          />
          <select value={form.exchange_segment} onChange={(e) => setForm({ ...form, exchange_segment: e.target.value })}>
            <option value="NSE_EQ">NSE_EQ</option>
            <option value="NSE_FNO">NSE_FNO</option>
          </select>
          <select value={form.transaction_type} onChange={(e) => setForm({ ...form, transaction_type: e.target.value })}>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
          <input
            type="number"
            placeholder="Quantity"
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })}
            required
          />
          <select value={form.order_type} onChange={(e) => setForm({ ...form, order_type: e.target.value })}>
            <option value="MARKET">MARKET</option>
            <option value="LIMIT">LIMIT</option>
          </select>
          <select value={form.product_type} onChange={(e) => setForm({ ...form, product_type: e.target.value })}>
            <option value="CNC">CNC</option>
            <option value="INTRADAY">INTRADAY</option>
            <option value="MARGIN">MARGIN</option>
          </select>
          <input
            type="number"
            placeholder="Price (LIMIT only)"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: Number(e.target.value) })}
          />
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={form.paper_trading}
              onChange={(e) => setForm({ ...form, paper_trading: e.target.checked })}
            />
            Paper trading
          </label>
          <button type="submit" disabled={submitting}>
            {submitting ? "Placing..." : "Place Order"}
          </button>
        </form>
        {error && <div className="form-error">{error}</div>}
      </GlassPanel>

      <GlassPanel title="Live Order Updates" note={`${liveUpdates.length} received`} style={{ marginBottom: 20 }}>
        <div className="feed">
          {liveUpdates.length === 0 && (
            <p className="feed-empty">No live updates yet — requires a connected Dhan account with order activity.</p>
          )}
          <AnimatePresence initial={false}>
            {liveUpdates.map((update, i) => {
              const data = update as Record<string, unknown>;
              const orderNo = String(data.orderNo ?? data.orderId ?? "-");
              const status = String(data.status ?? data.orderStatus ?? "UPDATE");
              return (
                <motion.div
                  key={`${orderNo}-${i}`}
                  className="feed-row"
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25 }}
                >
                  <StatusPill label={status} tone={statusTone(status)} />
                  <span className="feed-order-id">{orderNo}</span>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </GlassPanel>

      <GlassPanel title="Order Book" note={`${rows.length} orders`}>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Status</th>
                <th>Time</th>
                <th>Mode</th>
              </tr>
            </thead>
            <tbody>
              {orders === null && (
                <tr>
                  <td colSpan={7} className="loading-cell">
                    Loading...
                  </td>
                </tr>
              )}
              {orders !== null && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="loading-cell">
                    No orders yet
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="sym-cell">{row.symbol}</td>
                  <td className={row.side === "BUY" ? "num up" : "num down"}>{row.side}</td>
                  <td className="num">{row.qty}</td>
                  <td className="num">{row.price.toFixed(2)}</td>
                  <td>
                    <StatusPill label={row.status} tone={statusTone(row.status)} />
                  </td>
                  <td className="updated-cell">{new Date(row.time).toLocaleString()}</td>
                  <td>{row.isPaper ? <StatusPill label="Paper" tone="warn" /> : <StatusPill label="Live" tone="accent" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <style jsx>{`
        .order-form {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 10px;
          padding: 20px;
        }
        @media (max-width: 700px) {
          .order-form {
            grid-template-columns: repeat(2, 1fr);
          }
          .order-form button {
            grid-column: span 2;
          }
        }
        .order-form input,
        .order-form select {
          padding: 10px 12px;
          border-radius: 8px;
          border: 1px solid var(--panel-border);
          background: var(--canvas-soft);
          color: var(--text);
          font-size: 13.5px;
        }
        .order-form input::placeholder {
          color: var(--text-faint);
        }
        .order-form input:focus,
        .order-form select:focus {
          border-color: var(--accent);
        }
        .checkbox-field {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          color: var(--text-muted);
        }
        .order-form button {
          grid-column: span 2;
          padding: 10px;
          border-radius: 8px;
          border: 1px solid var(--accent);
          background: var(--accent-dim);
          color: var(--accent);
          font-weight: 600;
          font-size: 13.5px;
          cursor: pointer;
          transition: background-color 0.15s ease;
        }
        .order-form button:hover:not(:disabled) {
          background: var(--accent-hover);
        }
        .order-form button:disabled {
          opacity: 0.6;
          cursor: default;
        }
        .form-error {
          padding: 0 20px 16px;
          color: var(--loss);
          font-size: 13px;
        }
        .feed {
          padding: 16px 20px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 260px;
          overflow-y: auto;
        }
        .feed-empty {
          color: var(--text-faint);
          font-size: 13px;
          margin: 0;
        }
        .feed-row {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .feed-order-id {
          font-family: var(--font-data);
          font-size: 12px;
          color: var(--text-muted);
        }
        .table-scroll {
          overflow-x: auto;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          min-width: 700px;
        }
        th {
          text-align: left;
          font-size: 11px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-faint);
          font-weight: 600;
          padding: 12px 20px;
          border-bottom: 1px solid var(--panel-border);
        }
        td {
          padding: 13px 20px;
          font-size: 13.5px;
          border-bottom: 1px solid var(--panel-border);
        }
        tbody tr:hover {
          background: var(--canvas-soft);
        }
        tbody tr:last-child td {
          border-bottom: none;
        }
        .sym-cell {
          font-weight: 600;
        }
        .num {
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
        }
        .num.up {
          color: var(--gain);
        }
        .num.down {
          color: var(--loss);
        }
        .updated-cell {
          color: var(--text-faint);
          font-family: var(--font-data);
          font-variant-numeric: tabular-nums;
          font-size: 12px;
        }
        .loading-cell {
          color: var(--text-faint);
          text-align: center;
          padding: 24px;
        }
      `}</style>
    </div>
  );
}
