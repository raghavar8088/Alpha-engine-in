"use client";

/**
 * The paper trading terminal — Stock and F&O, one component, two segments.
 *
 * Laid out the way a broker terminal is laid out, because that layout is not decoration:
 * the funds strip sits above everything since every decision is bounded by it; the order
 * ticket is always visible rather than hidden behind a modal, because you place orders far
 * more often than you do anything else here; and the books sit below in tabs because you
 * read them between decisions rather than during one.
 *
 * The F&O segment swaps the scrip search for an option chain, since you pick an F&O
 * contract by its coordinates — underlying, expiry, strike, side — not by typing a name.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "./PageHeader";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import EmptyState from "./EmptyState";
import StatusPill from "./StatusPill";
import Skeleton from "./Skeleton";
import {
  refreshing,
  fetchPTConfig, fetchPTDashboard, searchPTScrips, fetchPTMargin, placePTOrder,
  fetchPTOrders, fetchPTTrades, fetchPTPositions, fetchPTHoldings, fetchPTLedger,
  cancelPTOrder, exitPTPosition, fetchPTUnderlyings, fetchPTExpiries, fetchPTChain,
  runPTTick, resetPTAccount, fetchPTClosed,
  PTConfig, PTDashboard, PTContract, PTOrder, PTPosition, PTTrade, PTHolding,
  PTLedgerEntry, PTMargin, PTChain, PTClosedBook,
} from "../lib/api";

type Book = "positions" | "orders" | "closed" | "trades" | "holdings" | "funds";

const inr = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" :
    `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: dp });
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const cls = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : v > 0 ? "gain" : v < 0 ? "loss" : "";

const STATUS_TONE: Record<string, "gain" | "loss" | "warn" | "accent" | "muted"> = {
  COMPLETE: "gain", REJECTED: "loss", CANCELLED: "muted",
  EXPIRED: "muted", PENDING: "warn", TRIGGER_PENDING: "accent",
};

export default function PaperTerminal({ segment }: { segment: "EQUITY" | "FNO" }) {
  const isFno = segment === "FNO";

  const [cfg, setCfg] = useState<PTConfig | null>(null);
  const [dash, setDash] = useState<PTDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [book, setBook] = useState<Book>("positions");

  const [positions, setPositions] = useState<PTPosition[]>([]);
  const [orders, setOrders] = useState<PTOrder[]>([]);
  const [trades, setTrades] = useState<PTTrade[]>([]);
  const [holdings, setHoldings] = useState<PTHolding[]>([]);
  const [ledger, setLedger] = useState<PTLedgerEntry[]>([]);
  const [closed, setClosed] = useState<PTClosedBook | null>(null);

  // ── order ticket ──────────────────────────────────────────────────────────
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PTContract[]>([]);
  const [picked, setPicked] = useState<PTContract | null>(null);
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState(1);
  const [orderType, setOrderType] = useState("MARKET");
  const [product, setProduct] = useState(isFno ? "NRML" : "MIS");
  const [validity, setValidity] = useState("DAY");
  const [price, setPrice] = useState<string>("");
  const [trigger, setTrigger] = useState<string>("");
  const [margin, setMargin] = useState<PTMargin | null>(null);

  // ── F&O contract picker ───────────────────────────────────────────────────
  const [underlyings, setUnderlyings] = useState<{ symbol: string; lot_size: number }[]>([]);
  const [under, setUnder] = useState("");
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState("");
  const [chain, setChain] = useState<PTChain | null>(null);

  useEffect(() => {
    fetchPTConfig().then(setCfg).catch((e) => setError(e.message));
    if (isFno) {
      fetchPTUnderlyings()
        .then((r) => {
          setUnderlyings(r.underlyings);
          const first = r.underlyings.find((u) => u.symbol === "NIFTY") ?? r.underlyings[0];
          if (first) setUnder(first.symbol);
        })
        .catch((e) => setError(e.message));
    }
  }, [isFno]);

  useEffect(() => {
    if (!under) return;
    fetchPTExpiries(under).then((r) => {
      setExpiries(r.expiries);
      setExpiry(r.expiries[0] ?? "");
    }).catch((e) => setError(e.message));
  }, [under]);

  useEffect(() => {
    if (!under || !expiry) return;
    fetchPTChain(under, expiry).then(setChain).catch((e) => setError(e.message));
  }, [under, expiry]);

  const load = useCallback(async () => {
    try {
      const jobs: Promise<unknown>[] = [fetchPTDashboard(undefined, segment).then(setDash)];
      if (book === "positions") jobs.push(fetchPTPositions(undefined, segment).then((r) => setPositions(r.rows)));
      if (book === "orders") jobs.push(fetchPTOrders(undefined, segment).then((r) => setOrders(r.rows)));
      if (book === "trades") jobs.push(fetchPTTrades(undefined, segment).then((r) => setTrades(r.rows)));
      if (book === "holdings") jobs.push(fetchPTHoldings().then((r) => setHoldings(r.rows)));
      if (book === "closed") jobs.push(fetchPTClosed(undefined, segment).then(setClosed));
      if (book === "funds") jobs.push(fetchPTLedger().then((r) => setLedger(r.rows)));
      await Promise.all(jobs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [segment, book]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, [load]);

  // scrip search (equity)
  useEffect(() => {
    if (isFno || query.trim().length < 1) { setResults([]); return; }
    const t = setTimeout(() => {
      searchPTScrips(query, segment).then((r) => setResults(r.results)).catch(() => setResults([]));
    }, 220);
    return () => clearTimeout(t);
  }, [query, segment, isFno]);

  const contractRef = useMemo(() => {
    if (!picked) return null;
    return {
      segment,
      symbol: isFno ? (picked.underlying ?? picked.symbol) : picked.symbol,
      expiry: picked.expiry,
      strike: picked.strike,
      option_type: picked.option_type,
      instrument_kind: picked.kind,
    };
  }, [picked, segment, isFno]);

  // live margin preview whenever the ticket changes
  useEffect(() => {
    if (!contractRef || qty < 1) { setMargin(null); return; }
    const t = setTimeout(() => {
      fetchPTMargin({
        ...contractRef, transaction_type: side, quantity: qty, product,
        price: price ? Number(price) : null,
      }).then(setMargin).catch(() => setMargin(null));
    }, 260);
    return () => clearTimeout(t);
  }, [contractRef, side, qty, product, price]);

  const lot = picked?.lot_size ?? 1;

  const submit = async () => {
    if (!contractRef) return;
    setBusy(true); setNotice(null);
    try {
      const res = await placePTOrder({
        ...contractRef, transaction_type: side, quantity: qty,
        order_type: orderType, product, validity,
        price: price ? Number(price) : null,
        trigger_price: trigger ? Number(trigger) : null,
      });
      // A REJECTED order is a successful API call carrying a refusal. Showing it as an
      // error banner would be wrong — it is a record, and the reason is the useful part.
      if (res.status === "REJECTED") {
        setNotice(`Order rejected — ${res.status_message}`);
      } else if (res.status === "COMPLETE") {
        setNotice(`${side} ${res.quantity} ${res.symbol} filled at ${res.fill_price}`);
      } else {
        setNotice(`${side} ${res.quantity} ${res.symbol} accepted — ${res.status.replace("_", " ").toLowerCase()}`);
      }
      await refreshing(load);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const needsPrice = orderType === "LIMIT" || orderType === "SL";
  const needsTrigger = orderType === "SL" || orderType === "SL-M";
  const products = cfg?.segments.find((s) => s.key === segment)?.products ?? [];

  return (
    <div className="page">
      <PageHeader
        crumb={isFno ? "F&O Paper Trading" : "Stock Paper Trading"}
        title={isFno ? "F&O Paper Trading" : "Stock Paper Trading"}
        subtitle={isFno
          ? "Futures and options on live Angel One prices with paper money — option chain, lots, SPAN-lite margin, NRML and MIS, stop-loss orders and an auto square-off at the intraday cutoff. No order reaches a broker."
          : "A broker terminal on live Angel One prices with paper money — market, limit and stop-loss orders, CNC and MIS, an order book you can modify and cancel, holdings that settle overnight, and a funds ledger that explains every rupee. No order reaches a broker."}
        onRefresh={() => refreshing(load)}
        actions={
          <div className="hdr-actions">
            {cfg && <StatusPill label={cfg.market_open ? "Market Open" : "Market Closed"}
              tone={cfg.market_open ? "gain" : "muted"} pulse={cfg.market_open} />}
            <StatusPill label="PAPER MONEY" tone="accent" />
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}
      {notice && (
        <div className={notice.includes("rejected") ? "notice bad" : "notice ok"}>
          {notice}
          <button onClick={() => setNotice(null)}>✕</button>
        </div>
      )}

      {/* ── funds strip ─────────────────────────────────────────────────── */}
      <div className="funds">
        {dash ? (
          <>
            <Cell label="Available margin" value={inr(dash.funds.available_margin)} strong />
            <Cell label="Used margin" value={inr(dash.funds.blocked_margin)} />
            <Cell label="Day P&L" value={inr(dash.positions.day_realised)}
              tone={dash.positions.day_realised >= 0 ? "gain" : "loss"} />
            <Cell label="Unrealised" value={inr(dash.positions.unrealised_pnl)}
              tone={dash.positions.unrealised_pnl >= 0 ? "gain" : "loss"} />
            <Cell label="Equity" value={inr(dash.funds.equity)} strong />
            <Cell label="Net P&L" value={inr(dash.funds.net_pnl)}
              tone={dash.funds.net_pnl >= 0 ? "gain" : "loss"} note={pct(dash.funds.roi_pct)} />
            <Cell label="Charges paid" value={inr(dash.funds.charges_paid)} />
            <Cell label="Open orders" value={String(dash.open_orders)} />
          </>
        ) : (
          Array.from({ length: 8 }).map((_, i) => (
            <div className="cell" key={i}><Skeleton height={34} /></div>
          ))
        )}
      </div>

      <div className="grid">
        {/* ── left: instrument picker + order ticket ────────────────────── */}
        <div className="left">
          <GlassPanel title={isFno ? "Contract" : "Search a scrip"}>
            {isFno ? (
              <div className="fno-pick">
                <label>Underlying
                  <select value={under} onChange={(e) => { setUnder(e.target.value); setPicked(null); }}>
                    {underlyings.map((u) => <option key={u.symbol} value={u.symbol}>{u.symbol}</option>)}
                  </select>
                </label>
                <label>Expiry
                  <select value={expiry} onChange={(e) => { setExpiry(e.target.value); setPicked(null); }}>
                    {expiries.map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                </label>
                {chain && (
                  <div className="chainwrap">
                    <div className="chainhead">
                      <span>{chain.count} strikes · lot {chain.lot_size}</span>
                      {chain.atm_strike && <span className="atm">ATM {chain.atm_strike}</span>}
                    </div>
                    <table className="chain">
                      <thead><tr><th>CE</th><th>Strike</th><th>PE</th></tr></thead>
                      <tbody>
                        {chain.strikes.map((row) => {
                          const isAtm = chain.atm_strike === row.strike;
                          return (
                            <tr key={row.strike} className={isAtm ? "atmrow" : ""}>
                              <td>
                                {row.CE ? (
                                  <button className={picked?.angel_token === row.CE.contract.angel_token ? "leg on" : "leg"}
                                    onClick={() => setPicked(row.CE!.contract)}>
                                    {row.CE.ltp === null ? "—" : num(row.CE.ltp)}
                                  </button>
                                ) : "—"}
                              </td>
                              <td className="strike">{row.strike}</td>
                              <td>
                                {row.PE ? (
                                  <button className={picked?.angel_token === row.PE.contract.angel_token ? "leg on" : "leg"}
                                    onClick={() => setPicked(row.PE!.contract)}>
                                    {row.PE.ltp === null ? "—" : num(row.PE.ltp)}
                                  </button>
                                ) : "—"}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : (
              <>
                <input className="search" value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder="Type a symbol, e.g. RELIANCE" />
                <div className="results">
                  {results.map((r) => (
                    <button key={r.angel_token} className="res" onClick={() => { setPicked(r); setResults([]); setQuery(r.symbol); }}>
                      <b>{r.symbol}</b><span>{r.name}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </GlassPanel>

          <GlassPanel title="Order ticket">
            {!picked ? (
              <EmptyState title="Pick an instrument"
                note={isFno ? "Choose a strike from the chain above." : "Search for a scrip above."} />
            ) : (
              <div className="ticket">
                <div className="tsym">
                  <b>{picked.symbol}</b>
                  <span>{picked.kind === "OPTION"
                    ? `${picked.underlying} ${picked.expiry} ${picked.strike}${picked.option_type}`
                    : picked.name}</span>
                  {picked.lot_size > 1 && <span className="lot">lot {picked.lot_size}</span>}
                </div>

                <div className="sides">
                  <button className={side === "BUY" ? "sd buy on" : "sd buy"} onClick={() => setSide("BUY")}>BUY</button>
                  <button className={side === "SELL" ? "sd sell on" : "sd sell"} onClick={() => setSide("SELL")}>SELL</button>
                </div>

                <div className="row2">
                  <label>Quantity
                    <input type="number" min={lot} step={lot} value={qty}
                      onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
                    {picked.lot_size > 1 && <small>{Math.floor(qty / lot)} lot(s)</small>}
                  </label>
                  <label>Product
                    <select value={product} onChange={(e) => setProduct(e.target.value)}>
                      {products.map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                    <small>{cfg?.product_help[product]}</small>
                  </label>
                </div>

                <div className="row2">
                  <label>Order type
                    <select value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                      {(cfg?.order_types ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <small>{cfg?.order_type_help[orderType]}</small>
                  </label>
                  <label>Validity
                    <select value={validity} onChange={(e) => setValidity(e.target.value)}>
                      {(cfg?.validities ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </label>
                </div>

                {(needsPrice || needsTrigger) && (
                  <div className="row2">
                    {needsPrice && (
                      <label>Price
                        <input type="number" step={picked.tick_size} value={price}
                          onChange={(e) => setPrice(e.target.value)} placeholder="limit price" />
                      </label>
                    )}
                    {needsTrigger && (
                      <label>Trigger
                        <input type="number" step={picked.tick_size} value={trigger}
                          onChange={(e) => setTrigger(e.target.value)} placeholder="trigger price" />
                      </label>
                    )}
                  </div>
                )}

                {margin && (
                  <div className={margin.sufficient ? "marg ok" : "marg bad"}>
                    <div className="mrow">
                      <span>Margin required</span><b>{inr(margin.margin)}</b>
                    </div>
                    <div className="mrow">
                      <span>Available</span><b>{inr(margin.available_margin)}</b>
                    </div>
                    {margin.mtf && (
                      <div className="mtfbox">
                        <div className="mrow"><span>Broker funds</span>
                          <b>{inr(margin.mtf.funded_amount)}</b></div>
                        <div className="mrow"><span>Interest per day</span>
                          <b className="loss">{inr(margin.mtf.daily_interest)}</b></div>
                        <div className="mrow"><span>Pledge in + out</span>
                          <b className="loss">{inr(margin.mtf.pledge_charge + margin.mtf.unpledge_charge)}</b></div>
                        <div className="mrow"><span>Leverage</span>
                          <b>{margin.mtf.leverage}x · {margin.mtf.margin_pct}% yours
                            <span className="src"> ({margin.mtf.source})</span></b></div>
                        <div className="mtfwarn">
                          Funding runs every calendar day, weekends included. Holding this
                          30 days costs about {inr(margin.mtf.daily_interest * 30)} in interest
                          alone — more than a 1% move on the position.
                        </div>
                      </div>
                    )}
                    <div className="mbasis">{margin.basis}</div>
                    {!margin.sufficient && (
                      <div className="mwarn">
                        Not enough margin — the order will be recorded as REJECTED, which is
                        what a real broker does.
                      </div>
                    )}
                  </div>
                )}

                <button className={side === "BUY" ? "submit buy" : "submit sell"}
                  disabled={busy} onClick={submit}>
                  {busy ? "Placing…" : `${side} ${qty} ${picked.symbol}`}
                </button>
              </div>
            )}
          </GlassPanel>
        </div>

        {/* ── right: the books ──────────────────────────────────────────── */}
        <div className="right">
          <div className="booktabs">
            {(["positions", "orders", "closed", "trades", ...(isFno ? [] : ["holdings"]), "funds"] as Book[]).map((b) => (
              <button key={b} className={book === b ? "bt active" : "bt"} onClick={() => setBook(b)}>
                {b[0].toUpperCase() + b.slice(1)}
              </button>
            ))}
            <button className="tickbtn" title="Run one engine pass now — arms stops, fills resting orders"
              onClick={async () => { await runPTTick(); await refreshing(load); }}>
              Run engine tick
            </button>
          </div>

          <GlassPanel>
            {book === "positions" && (
              positions.length === 0 ? <EmptyState title="No open positions" note="Place an order to open one." /> : (
                <div className="tw"><table>
                  <thead><tr>
                    <th className="l">Instrument</th><th>Product</th><th>Qty</th><th>Avg</th><th>LTP</th>
                    <th>P&amp;L</th><th>%</th><th>Margin</th>
                    <th title="Funding interest accrued plus pledge fees — what it costs to close">MTF cost</th>
                    <th title="Unrealised P&L minus the MTF cost of getting out">After funding</th>
                    <th></th>
                  </tr></thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.position_id}>
                        <td className="l"><b>{p.symbol}</b>
                          <div className="sub">{p.side}{p.strike ? ` · ${p.strike}${p.option_type} ${p.expiry}` : ""}</div></td>
                        <td className="dim">{p.product}</td>
                        <td className={p.quantity > 0 ? "gain" : "loss"}>{p.quantity}</td>
                        <td>{num(p.avg_price)}</td>
                        <td>{num(p.ltp)}</td>
                        <td className={cls(p.unrealised_pnl)}><b>{inr(p.unrealised_pnl)}</b></td>
                        <td className={cls(p.pnl_pct)}>{pct(p.pnl_pct)}</td>
                        <td className="dim">{inr(p.margin_blocked, 0)}</td>
                        <td className={p.mtf ? "loss" : "dim"}>
                          {p.mtf ? (
                            <>
                              {inr(p.mtf.estimated_exit_cost)}
                              <div className="sub">{p.mtf.days_held}d · {inr(p.mtf.daily_interest)}/day</div>
                            </>
                          ) : "—"}
                        </td>
                        <td className={p.pnl_after_funding !== undefined ? cls(p.pnl_after_funding) : "dim"}>
                          {p.pnl_after_funding !== undefined ? <b>{inr(p.pnl_after_funding)}</b> : "—"}
                        </td>
                        <td><button className="exit" onClick={async () => {
                          await exitPTPosition(p.position_id); await refreshing(load);
                        }}>Exit</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )
            )}

            {book === "orders" && (
              orders.length === 0 ? <EmptyState title="No orders yet" /> : (
                <div className="tw"><table>
                  <thead><tr>
                    <th className="l">Instrument</th><th>Side</th><th>Qty</th><th>Type</th>
                    <th>Price</th><th>Trigger</th><th>Product</th><th>Status</th>
                    <th className="l">Message</th><th></th>
                  </tr></thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.order_id}>
                        <td className="l"><b>{o.symbol}</b>
                          <div className="sub">{new Date(o.placed_at).toLocaleTimeString()}</div></td>
                        <td className={o.transaction_type === "BUY" ? "gain" : "loss"}>{o.transaction_type}</td>
                        <td>{o.quantity}</td>
                        <td className="dim">{o.order_type}</td>
                        <td>{o.fill_price ? <b>{num(o.fill_price)}</b> : num(o.price)}</td>
                        <td className="dim">{num(o.trigger_price)}</td>
                        <td className="dim">{o.product}</td>
                        <td><StatusPill label={o.status.replace("_", " ")} tone={STATUS_TONE[o.status] ?? "muted"} /></td>
                        <td className="l sub wide">{o.status_message ?? "—"}</td>
                        <td>
                          {(o.status === "PENDING" || o.status === "TRIGGER_PENDING") && (
                            <button className="exit" onClick={async () => {
                              await cancelPTOrder(o.order_id); await refreshing(load);
                            }}>Cancel</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )
            )}

            {book === "closed" && (
              !closed ? <div className="tw"><EmptyState title="Loading…" /></div> :
              closed.rows.length === 0 ? (
                <EmptyState title="No closed positions yet"
                  note="Close a position and its full cost — statutory charges, MTF funding, pledge fees — is itemised here." />
              ) : (
                <>
                  <div className="closedtotals">
                    <Cell label="Gross P&L" value={inr(closed.totals.gross_pnl)}
                      tone={closed.totals.gross_pnl >= 0 ? "gain" : "loss"} />
                    <Cell label="Statutory charges" value={inr(closed.totals.statutory_charges)} />
                    <Cell label="MTF interest" value={inr(closed.totals.mtf_interest)} />
                    <Cell label="Pledge fees" value={inr(closed.totals.pledge_charges)} />
                    <Cell label="Total charges" value={inr(closed.totals.total_charges)} />
                    <Cell label="Net P&L" value={inr(closed.totals.net_pnl)}
                      tone={closed.totals.net_pnl >= 0 ? "gain" : "loss"} strong />
                  </div>
                  <div className="tw">
                    <table>
                      <thead><tr>
                        <th className="l">Instrument</th><th>Product</th><th>Qty</th><th>Exit</th>
                        <th>Gross P&amp;L</th>
                        <th title="Brokerage, STT, exchange + SEBI fees, stamp duty, GST, DP charge">Statutory</th>
                        <th title="Funding interest on the amount the broker lent">MTF interest</th>
                        <th title="Pledge in + unpledge out">Pledge</th>
                        <th>Total charges</th><th>Net P&amp;L</th><th>Held</th><th>When</th>
                      </tr></thead>
                      <tbody>
                        {closed.rows.map((t) => {
                          const b = t.charge_breakdown;
                          const m = b?.mtf ?? null;
                          const statutory = b ? b.total_charges - (m?.total ?? 0) : 0;
                          return (
                            <tr key={t.trade_id}>
                              <td className="l"><b>{t.symbol}</b></td>
                              <td className={t.product === "MTF" ? "mtftag" : "dim"}>{t.product}</td>
                              <td>{t.quantity}</td>
                              <td>{num(t.price)}</td>
                              <td className={cls(b?.gross_pnl)}>{inr(b?.gross_pnl)}</td>
                              <td className="dim">{inr(statutory)}</td>
                              <td className={m ? "loss" : "dim"}>
                                {m ? inr(m.interest) : "—"}
                                {m && <div className="sub">{inr(m.funded_amount, 0)} funded</div>}
                              </td>
                              <td className={m ? "loss" : "dim"}>
                                {m ? inr(m.pledge_charge + m.unpledge_charge) : "—"}</td>
                              <td className="loss">{inr(b?.total_charges)}</td>
                              <td className={cls(b?.net_pnl)}><b>{inr(b?.net_pnl)}</b></td>
                              <td className="dim">{m ? `${m.days_held}d` : "—"}</td>
                              <td className="dim">{new Date(t.traded_at).toLocaleDateString()}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="note">{closed.note}</div>
                </>
              )
            )}

            {book === "trades" && (
              trades.length === 0 ? <EmptyState title="No trades yet" /> : (
                <div className="tw"><table>
                  <thead><tr>
                    <th className="l">Instrument</th><th>Side</th><th>Qty</th><th>Price</th>
                    <th>Value</th><th>Realised</th><th>Charges</th><th>Product</th><th>Time</th>
                  </tr></thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.trade_id}>
                        <td className="l"><b>{t.symbol}</b></td>
                        <td className={t.transaction_type === "BUY" ? "gain" : "loss"}>{t.transaction_type}</td>
                        <td>{t.quantity}</td>
                        <td>{num(t.price)}</td>
                        <td className="dim">{inr(t.value, 0)}</td>
                        <td className={cls(t.realised_pnl)}>{t.realised_pnl ? inr(t.realised_pnl) : "—"}</td>
                        <td className="dim">{inr(t.charges)}</td>
                        <td className="dim">{t.product}</td>
                        <td className="dim">{new Date(t.traded_at).toLocaleTimeString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )
            )}

            {book === "holdings" && (
              holdings.length === 0 ? (
                <EmptyState title="No holdings"
                  note="CNC buys move here after the close — that overnight settlement is what makes delivery different from an intraday position." />
              ) : (
                <div className="tw"><table>
                  <thead><tr>
                    <th className="l">Stock</th><th>Qty</th><th>Avg</th><th>LTP</th>
                    <th>Invested</th><th>Value</th><th>P&amp;L</th><th>%</th><th>Since</th>
                  </tr></thead>
                  <tbody>
                    {holdings.map((h) => (
                      <tr key={h.token}>
                        <td className="l"><b>{h.symbol}</b></td>
                        <td>{h.quantity}</td>
                        <td>{num(h.avg_price)}</td>
                        <td>{num(h.ltp)}</td>
                        <td className="dim">{inr(h.invested, 0)}</td>
                        <td>{inr(h.current_value, 0)}</td>
                        <td className={cls(h.pnl)}><b>{inr(h.pnl)}</b></td>
                        <td className={cls(h.pnl_pct)}>{pct(h.pnl_pct)}</td>
                        <td className="dim">{h.settled_on}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )
            )}

            {book === "funds" && (
              <>
                {dash && (
                  <div className="fundsdetail">
                    <Row label="Opening balance" value={inr(dash.funds.opening_balance)} />
                    <Row label="Realised P&L" value={inr(dash.funds.realised_pnl)} tone={dash.funds.realised_pnl} />
                    <Row label="Charges paid" value={`- ${inr(dash.funds.charges_paid)}`} />
                    <Row label="Margin blocked" value={`- ${inr(dash.funds.blocked_margin)}`} />
                    <Row label="Available margin" value={inr(dash.funds.available_margin)} strong />
                    <Row label="Unrealised P&L" value={inr(dash.funds.unrealised_pnl)} tone={dash.funds.unrealised_pnl} />
                    <Row label="Equity" value={inr(dash.funds.equity)} strong />
                  </div>
                )}
                <h4>Ledger — every cash movement</h4>
                {ledger.length === 0 ? <EmptyState title="No entries" /> : (
                  <div className="tw"><table>
                    <thead><tr><th className="l">Kind</th><th className="l">Note</th><th>Amount</th><th>When</th></tr></thead>
                    <tbody>
                      {ledger.map((e) => (
                        <tr key={e.entry_id}>
                          <td className="l dim">{e.kind}</td>
                          <td className="l sub wide">{e.note}</td>
                          <td className={cls(e.amount)}>{inr(e.amount)}</td>
                          <td className="dim">{new Date(e.ts).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table></div>
                )}
                {cfg?.mtf && !isFno && (
                  <>
                    <h4>MTF rate card</h4>
                    <div className="tw">
                      <table>
                        <thead><tr><th className="l">Tier</th><th>Leverage</th><th>You fund</th></tr></thead>
                        <tbody>
                          {cfg.mtf.leverage_tiers.map((t) => (
                            <tr key={t.tier}>
                              <td className="l">{t.tier}</td>
                              <td>{t.leverage}x</td>
                              <td>{t.margin_pct}%</td>
                            </tr>
                          ))}
                          <tr>
                            <td className="l dim">anything else</td>
                            <td className="dim">{cfg.mtf.default_leverage}x</td>
                            <td className="dim">{cfg.mtf.default_margin_pct}%</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div className="fundsdetail">
                      <Row label="Funding rate" value={`${cfg.mtf.daily_rate_pct}% / day  (${cfg.mtf.annual_rate_pct}% a year)`} />
                      <Row label="Pledge charge" value={inr(cfg.mtf.pledge_charge)} />
                      <Row label="Unpledge charge" value={inr(cfg.mtf.unpledge_charge)} />
                      <Row label="Live leverage source" value={cfg.mtf.live_leverage_enabled ? "Dhan margin calculator" : "rate card (configured)"} />
                    </div>
                    <div className="provenance">
                      <b>Where these numbers come from.</b> {cfg.mtf.provenance}
                    </div>
                    <div className="note small">{cfg.mtf.mechanics}</div>
                  </>
                )}
                <div className="reset">
                  <button onClick={async () => {
                    if (!dash) return;
                    if (!window.confirm("Reset this paper account? Every order, trade, position and holding is deleted. This cannot be undone.")) return;
                    await resetPTAccount(dash.funds.account_id);
                    await refreshing(load);
                  }}>Reset paper account</button>
                </div>
              </>
            )}
          </GlassPanel>

          {cfg && <div className="note">{cfg.fills_note}</div>}
        </div>
      </div>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 14px; }
        .hdr-actions { display: flex; gap: 8px; align-items: center; }
        .notice { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 14px; border-radius: 10px; font-size: 13px; }
        .notice.ok { background: var(--gain-dim); color: var(--gain); border: 1px solid var(--gain); }
        .notice.bad { background: var(--warn-dim); color: var(--warn); border: 1px solid var(--warn); }
        .notice button { border: 0; background: transparent; cursor: pointer; color: inherit; font-size: 13px; }

        .funds { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }

        .grid { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 14px; align-items: start; }
        @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
        .left, .right { display: flex; flex-direction: column; gap: 14px; }

        .search { width: 100%; padding: 9px 12px; border-radius: 9px; border: 1px solid var(--panel-border); font-size: 13px; background: var(--panel); color: var(--text); }
        .results { display: flex; flex-direction: column; gap: 2px; margin-top: 8px; max-height: 240px; overflow-y: auto; }
        .res { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; border: 0; background: transparent; padding: 7px 9px; border-radius: 7px; cursor: pointer; text-align: left; }
        .res:hover { background: var(--canvas-soft); }
        .res b { font-size: 12.5px; color: var(--text); }
        .res span { font-size: 10.5px; color: var(--text-faint); }

        .fno-pick { display: flex; flex-direction: column; gap: 10px; }
        .fno-pick label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--text-muted); font-weight: 600; }
        .fno-pick select { padding: 8px 10px; border-radius: 8px; border: 1px solid var(--panel-border); font-size: 13px; background: var(--panel); color: var(--text); }
        .chainwrap { max-height: 340px; overflow-y: auto; border: 1px solid var(--panel-border); border-radius: 9px; }
        .chainhead { display: flex; justify-content: space-between; padding: 6px 10px; font-size: 10.5px; color: var(--text-faint); border-bottom: 1px solid var(--panel-border); position: sticky; top: 0; background: var(--panel); }
        .atm { color: var(--purple); font-weight: 700; }
        table.chain { width: 100%; border-collapse: collapse; font-size: 12px; }
        table.chain th { font-size: 10px; color: var(--text-muted); padding: 4px; text-transform: uppercase; }
        table.chain td { padding: 2px 4px; text-align: center; border-bottom: 1px solid var(--canvas-edge); }
        .strike { font-weight: 700; font-variant-numeric: tabular-nums; color: var(--text-muted); }
        .atmrow .strike { color: var(--purple); }
        .leg { border: 1px solid transparent; background: var(--canvas-soft); border-radius: 5px; padding: 3px 8px; font-size: 11.5px; cursor: pointer; width: 100%; font-variant-numeric: tabular-nums; color: var(--text); }
        .leg:hover { border-color: var(--purple); }
        .leg.on { background: var(--purple); color: #fff; font-weight: 700; }

        .ticket { display: flex; flex-direction: column; gap: 11px; }
        .tsym { display: flex; flex-direction: column; gap: 2px; }
        .tsym b { font-size: 15px; }
        .tsym span { font-size: 11px; color: var(--text-faint); }
        .lot { color: var(--purple) !important; font-weight: 600; }
        .sides { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .sd { padding: 10px; border-radius: 9px; border: 1px solid var(--panel-border); background: var(--panel); font-weight: 700; font-size: 13px; cursor: pointer; color: var(--text-muted); }
        .sd.buy.on { background: var(--gain); border-color: var(--gain); color: #fff; }
        .sd.sell.on { background: var(--loss); border-color: var(--loss); color: #fff; }
        .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .ticket label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; font-weight: 600; color: var(--text-muted); }
        .ticket input, .ticket select { padding: 8px 10px; border-radius: 8px; border: 1px solid var(--panel-border); font-size: 13px; background: var(--panel); color: var(--text); }
        .ticket small { font-size: 9.5px; color: var(--text-faint); font-weight: 400; line-height: 1.35; }

        .marg { border-radius: 9px; padding: 10px 12px; font-size: 12px; border: 1px solid var(--panel-border); }
        .marg.ok { background: var(--canvas-soft); }
        .marg.bad { background: var(--loss-dim); border-color: var(--loss); }
        .mrow { display: flex; justify-content: space-between; padding: 2px 0; }
        .mrow span { color: var(--text-muted); }
        .mbasis { font-size: 10px; color: var(--text-faint); margin-top: 6px; line-height: 1.4; }
        .mtfbox { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--panel-border); }
        .src { font-weight: 400; color: var(--text-faint); font-size: 10px; }
        .mtfwarn { font-size: 10.5px; color: var(--warn); line-height: 1.45; margin-top: 6px; }
        .closedtotals { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin-bottom: 12px; }
        .mtftag { color: var(--purple); font-weight: 700; }
        .provenance { font-size: 11px; color: var(--warn); background: var(--warn-dim); border: 1px solid var(--warn); border-radius: 9px; padding: 10px 13px; line-height: 1.55; margin-top: 12px; }
        .mwarn { font-size: 11px; color: var(--loss); margin-top: 6px; line-height: 1.4; }

        .submit { padding: 12px; border-radius: 10px; border: 0; font-weight: 700; font-size: 14px; cursor: pointer; color: #fff; }
        .submit.buy { background: var(--gain); }
        .submit.sell { background: var(--loss); }
        .submit:disabled { opacity: .6; cursor: default; }

        .booktabs { display: flex; gap: 2px; align-items: center; border-bottom: 1px solid var(--panel-border); }
        .bt { border: 0; background: transparent; padding: 9px 15px; font-size: 13px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
        .bt.active { color: var(--purple); border-bottom-color: var(--purple); }
        .tickbtn { margin-left: auto; border: 1px solid var(--panel-border); background: var(--panel); border-radius: 8px; padding: 5px 10px; font-size: 11px; color: var(--text-muted); cursor: pointer; }

        .tw { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        th, td { padding: 8px 10px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--panel-border); font-variant-numeric: tabular-nums; }
        th { font-size: 10.5px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
        th.l, td.l { text-align: left; }
        td.dim { color: var(--text-muted); }
        .sub { font-size: 10px; color: var(--text-faint); white-space: normal; }
        td.wide { max-width: 280px; white-space: normal; }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .exit { border: 1px solid var(--panel-border); background: var(--panel); border-radius: 6px; padding: 3px 10px; font-size: 11px; cursor: pointer; color: var(--text-muted); }
        .exit:hover { border-color: var(--loss); color: var(--loss); }

        .fundsdetail { display: flex; flex-direction: column; gap: 2px; margin-bottom: 6px; }
        h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin: 16px 0 8px; }
        .reset { margin-top: 14px; }
        .reset button { border: 1px solid var(--loss); background: var(--loss-dim); color: var(--loss); border-radius: 8px; padding: 7px 13px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .note { font-size: 11.5px; color: var(--text-muted); background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 9px; padding: 10px 13px; line-height: 1.55; }
      `}</style>
    </div>
  );
}

function Cell({ label, value, note, tone, strong }: {
  label: string; value: string; note?: string;
  tone?: "gain" | "loss"; strong?: boolean;
}) {
  return (
    <div className="cell">
      <div className="cl">{label}</div>
      <div className={`cv ${tone ?? ""}${strong ? " strong" : ""}`}>{value}</div>
      {note && <div className="cn">{note}</div>}
      <style jsx>{`
        .cell { border: 1px solid var(--panel-border); border-radius: 10px; padding: 9px 12px; background: var(--panel); }
        .cl { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
        .cv { font-size: 15px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
        .cv.strong { font-weight: 700; }
        .cv.gain { color: var(--gain); }
        .cv.loss { color: var(--loss); }
        .cn { font-size: 10px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}

function Row({ label, value, tone, strong }: {
  label: string; value: string; tone?: number; strong?: boolean;
}) {
  const t = tone === undefined ? "" : tone > 0 ? "gain" : tone < 0 ? "loss" : "";
  return (
    <div className={strong ? "r strong" : "r"}>
      <span>{label}</span><b className={t}>{value}</b>
      <style jsx>{`
        .r { display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid var(--canvas-edge); }
        .r.strong { font-size: 14.5px; border-bottom: 1px solid var(--panel-border); }
        .r span { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
