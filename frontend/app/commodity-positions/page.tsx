"use client";

/**
 * Commodity Positions — the MCX twin of F&O Positions.
 *
 * Same five tabs and the same trading flow, with the three things MCX does differently
 * made visible rather than hidden:
 *
 *   - Every contract shows its LOT QUANTITY and CONTRACT VALUE. An MCX lot is not one
 *     unit: a ZINC lot is 5 tonnes and a GOLD lot is a kilo, so "1 lot" ranges from
 *     ₹16,000 (GOLDPETAL) to ₹1.6 crore (GOLD). Trading without that on screen is how a
 *     position ends up a hundred times the size you meant.
 *   - An underlying whose contract spec is UNVERIFIED says so on its own row.
 *   - Options are options on FUTURES, so the chain names the futures contract it is
 *     priced against and that contract's own, later, expiry.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import DeskHistory from "../../components/DeskHistory";
import {
  CmpChain,
  CmpFuture,
  CmpOrder,
  CmpPosition,
  CmpSpecCheckRow,
  CmpSummary,
  CmpUnderlying,
  createCmpAccount,
  editCmpAccount,
  exitCmpPosition,
  fetchCmpAccounts,
  fetchCmpChain,
  fetchCmpFutureExpiries,
  fetchCmpFutures,
  fetchCmpOptionExpiries,
  fetchCmpOrders,
  fetchCmpPositions,
  fetchCmpSpecCheck,
  fetchCmpUnderlyings,
  placeCmpOrder,
  resetCmpAccount,
  syncCmpInstruments,
} from "../../lib/api";

const REFRESH_MS = 20000;
type Tab = "chain" | "futures" | "positions" | "orders" | "specs" | "history";

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: dp })}`;
const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const compact = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e7) return `₹${(v / 1e7).toFixed(2)}cr`;
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
};
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(dp);

export default function CommodityPositionsPage() {
  const [accounts, setAccounts] = useState<CmpSummary["account"][]>([]);
  const [accountId, setAccountId] = useState("");
  const [summary, setSummary] = useState<CmpSummary | null>(null);
  const [orders, setOrders] = useState<CmpOrder[]>([]);
  const [unders, setUnders] = useState<CmpUnderlying[]>([]);
  const [futures, setFutures] = useState<CmpFuture[]>([]);
  const [specs, setSpecs] = useState<CmpSpecCheckRow[]>([]);
  const [chain, setChain] = useState<CmpChain | null>(null);

  const [symbol, setSymbol] = useState("");
  const [optExpiry, setOptExpiry] = useState("");
  const [optExpiries, setOptExpiries] = useState<string[]>([]);
  const [futExpiries, setFutExpiries] = useState<string[]>([]);

  const [tab, setTab] = useState<Tab>("chain");
  const [lots, setLots] = useState(1);
  const [product, setProduct] = useState<"MARGIN" | "INTRADAY">("MARGIN");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const spec = useMemo(() => unders.find((u) => u.symbol === symbol), [unders, symbol]);

  // ---- bootstrap -------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const [a, u] = await Promise.all([fetchCmpAccounts(), fetchCmpUnderlyings()]);
        setAccounts(a.accounts);
        if (a.accounts.length && !accountId) setAccountId(a.accounts[0].account_id);
        setUnders(u.underlyings);
        const first = u.underlyings.find((x) => x.has_options) ?? u.underlyings[0];
        if (first && !symbol) setSymbol(first.symbol);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load the commodity desk");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- expiries follow the underlying ----------------------------------------
  useEffect(() => {
    if (!symbol) return;
    fetchCmpOptionExpiries(symbol).then((r) => {
      setOptExpiries(r.expiries);
      setOptExpiry(r.expiries[0] ?? "");
    }).catch(() => { setOptExpiries([]); setOptExpiry(""); });
    fetchCmpFutureExpiries(symbol).then((r) => setFutExpiries(r.expiries)).catch(() => setFutExpiries([]));
  }, [symbol]);

  useEffect(() => {
    if (tab !== "chain" || !symbol || !optExpiry) return;
    setChain(null);
    fetchCmpChain(symbol, optExpiry).then(setChain)
      .catch((e) => setError(e instanceof Error ? e.message : "Chain unavailable"));
  }, [tab, symbol, optExpiry]);

  useEffect(() => {
    if (tab !== "futures") return;
    fetchCmpFutures().then((r) => { setFutures(r.contracts); setSpecs(r.spec_check); })
      .catch(() => {});
  }, [tab]);

  useEffect(() => {
    if (tab === "specs" && !specs.length) fetchCmpSpecCheck().then((r) => setSpecs(r.spec_check)).catch(() => {});
  }, [tab, specs.length]);

  const loadBook = useCallback(async () => {
    if (!accountId) return;
    try {
      const s = await fetchCmpPositions(accountId);
      setSummary(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    }
  }, [accountId]);

  useEffect(() => {
    loadBook();
    const id = setInterval(loadBook, REFRESH_MS);
    return () => clearInterval(id);
  }, [loadBook]);

  useEffect(() => {
    if (tab === "orders" && accountId) {
      fetchCmpOrders(accountId).then((r) => setOrders(r.orders)).catch(() => {});
    }
  }, [tab, accountId]);

  // ---- actions ---------------------------------------------------------------
  const act = async (label: string, fn: () => Promise<unknown>, after = true) => {
    if (busy) return;
    setBusy(label);
    setError(null);
    try {
      await fn();
      if (after) await loadBook();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${label} failed`);
    } finally {
      setBusy(null);
    }
  };

  const trade = (kind: "OPTION" | "FUTURE", side: "BUY" | "SELL",
                 expiry: string, strike?: number, optionType?: "CE" | "PE") =>
    act(`${side}-${strike ?? "fut"}`, async () => {
      const res = await placeCmpOrder({
        account_id: accountId, instrument_kind: kind, symbol, expiry,
        transaction_type: side, lots, order_type: "MARKET", product_type: product,
        strike: strike ?? null, option_type: optionType ?? null,
      });
      setNotice(`${side} ${lots} lot${lots > 1 ? "s" : ""} of ${res.display_name} filled at ` +
        `${inr(res.fill_price, 2)} — contract value ${compact(res.contract_value)}, ` +
        `margin ${compact(res.margin_used)}.`);
    });

  const lotValue = (price: number | null | undefined) =>
    price && spec ? price * spec.multiplier * lots : null;

  return (
    <div className="page">
      <PageHeader
        crumb="Commodity Positions"
        title="Commodity Positions"
        subtitle={
          <>
            Live MCX futures and option chains — buy or sell in lots at real prices, across
            multiple paper accounts each with its own balance (default ₹1 crore).{" "}
            <strong>An MCX lot is not one unit.</strong> A ZINC lot is 5 tonnes and a GOLD
            lot is a kilogram, so every contract here shows its lot quantity and its full
            contract value before you trade it. Priced by Angel One — Dhan does not cover
            MCX — and margined with a local SPAN-style model scanned per commodity. Not
            investment advice.
          </>
        }
        actions={
          <>
            <StatusPill label="MCX · paper" tone="accent" />
            <select className="sel" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.name} · {compact(a.initial_capital)}
                </option>
              ))}
            </select>
            <button className="btn" disabled={!!busy} onClick={() => {
              const name = window.prompt("New paper account name");
              if (!name) return;
              act("new", async () => {
                const a = await createCmpAccount(name);
                const list = await fetchCmpAccounts();
                setAccounts(list.accounts);
                setAccountId(a.account_id);
              }, false);
            }}>+ New Account</button>
            <button className="btn" disabled={!!busy || !accountId} onClick={() => {
              const cap = window.prompt("New starting capital (₹)",
                String(summary?.initial_capital ?? 10000000));
              if (!cap) return;
              act("edit", async () => {
                await editCmpAccount(accountId, { initial_capital: Number(cap) });
                setAccounts((await fetchCmpAccounts()).accounts);
              });
            }}>Edit</button>
            <button className="btn danger" disabled={!!busy || !accountId} onClick={() => {
              if (!window.confirm("Wipe every position and order in this account?")) return;
              act("reset", () => resetCmpAccount(accountId));
            }}>Reset</button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={loadBook} />}
      {notice && (
        <GlassPanel title="Filled" note="paper">
          <div className="notice">{notice}</div>
        </GlassPanel>
      )}

      <div className="tiles">
        <Tile label="Equity" value={compact(summary?.equity)}
              sub={`started at ${compact(summary?.initial_capital)}`} />
        <Tile label="Available cash" value={compact(summary?.available_cash)}
              sub={`${compact(summary?.margin_deployed)} margin blocked`} />
        <Tile label="Contract exposure" value={compact(summary?.contract_exposure)}
              sub="full notional of the open book" />
        <Tile label="Unrealised" value={signed(summary?.unrealized_pnl)}
              tone={(summary?.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}
              sub={`${summary?.open_count ?? 0} open`} />
        <Tile label="Realised" value={signed(summary?.realized_pnl)}
              tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}
              sub={`${summary?.closed_count ?? 0} closed`} />
        <Tile label="Underlyings" value={String(unders.length)}
              sub={`${unders.filter((u) => u.has_options).length} with options`} />
      </div>

      {/* ---- order ticket -------------------------------------------------- */}
      <GlassPanel title="Order ticket" note="applies to every Buy/Sell button below">
        <div className="ticket">
          <label>Underlying
            <select className="sel" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {unders.map((u) => (
                <option key={u.symbol} value={u.symbol}>
                  {u.symbol}{u.has_options ? "" : " (futures only)"}
                </option>
              ))}
            </select>
          </label>
          <label>Lots
            <input className="inp" type="number" min={1} max={1000} value={lots}
                   onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))} />
          </label>
          <label>Product
            <select className="sel" value={product}
                    onChange={(e) => setProduct(e.target.value as "MARGIN" | "INTRADAY")}>
              <option value="MARGIN">MARGIN (carry)</option>
              <option value="INTRADAY">INTRADAY</option>
            </select>
          </label>
          {spec && (
            <div className="specbox">
              <div><b>1 lot = {spec.lot_quantity}</b> · quoted {spec.price_unit}</div>
              <div className="dim">
                multiplier ×{spec.multiplier.toLocaleString("en-IN")} · {spec.futures} futures
                {spec.options ? ` · ${spec.options} options` : " · no options listed"}
              </div>
              {!spec.verified && (
                <div className="warn">
                  Contract spec unverified — the lot value below comes from the broker&apos;s
                  order unit, not a published specification. Check it against the exchange
                  before trading this one.
                </div>
              )}
            </div>
          )}
        </div>
      </GlassPanel>

      <div className="tabs">
        {([
          ["chain", `Option Chain${spec && !spec.has_options ? " (none)" : ""}`],
          ["futures", "Futures"],
          ["positions", `Positions${summary?.open_count ? ` (${summary.open_count})` : ""}`],
          ["orders", "Orders"],
          ["specs", "Contract Specs"],
          ["history", "History"],
        ] as [Tab, string][]).map(([t, label]) => (
          <button key={t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>
            {label}
          </button>
        ))}
      </div>

      {/* ---- chain --------------------------------------------------------- */}
      {tab === "chain" && (
        <GlassPanel
          title="Option chain"
          note={chain ? `${chain.strikes_shown} of ${chain.strikes_listed} listed strikes, around the future` : ""}
        >
          <div className="chainbar">
            <select className="sel" value={optExpiry} onChange={(e) => setOptExpiry(e.target.value)}>
              {optExpiries.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
            {chain && (
              <span className="dim">
                Underlying future <b>{chain.underlying_contract ?? "—"}</b> at{" "}
                <b>{inr(chain.spot, 2)}</b>
                {chain.underlying_expiry && chain.underlying_expiry !== chain.expiry && (
                  <> — note it expires {chain.underlying_expiry}, after this option does</>
                )}
                {" · "}{chain.days_to_expiry}d to expiry
              </span>
            )}
          </div>

          {!optExpiries.length ? (
            <EmptyState title={`${symbol} has no listed options`}
                        note="MCX lists options on ten underlyings. Use the Futures tab for this one." />
          ) : !chain ? (
            <div className="dim pad">Loading chain…</div>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th colSpan={4}>CALLS</th>
                    <th>STRIKE</th>
                    <th colSpan={4}>PUTS</th>
                  </tr>
                  <tr>
                    <th>IV</th><th>Δ</th><th>LTP</th><th>Trade</th>
                    <th />
                    <th>Trade</th><th>LTP</th><th>Δ</th><th>IV</th>
                  </tr>
                </thead>
                <tbody>
                  {chain.strikes.map((s) => {
                    const atm = Math.abs(s.strike - chain.spot) ===
                      Math.min(...chain.strikes.map((x) => Math.abs(x.strike - chain.spot)));
                    return (
                      <tr key={s.strike} className={atm ? "atm" : ""}>
                        <td className="dim">{s.ce.iv ? `${(s.ce.iv * 100).toFixed(1)}%` : "—"}</td>
                        <td className="dim">{num(s.ce.delta)}</td>
                        <td className="px">{num(s.ce.last_price, 2)}</td>
                        <td className="acts">
                          <button className="mini buy" disabled={!!busy}
                                  onClick={() => trade("OPTION", "BUY", chain.expiry, s.strike, "CE")}>B</button>
                          <button className="mini sell" disabled={!!busy}
                                  onClick={() => trade("OPTION", "SELL", chain.expiry, s.strike, "CE")}>S</button>
                        </td>
                        <td className="strike">{s.strike.toLocaleString("en-IN")}</td>
                        <td className="acts">
                          <button className="mini buy" disabled={!!busy}
                                  onClick={() => trade("OPTION", "BUY", chain.expiry, s.strike, "PE")}>B</button>
                          <button className="mini sell" disabled={!!busy}
                                  onClick={() => trade("OPTION", "SELL", chain.expiry, s.strike, "PE")}>S</button>
                        </td>
                        <td className="px">{num(s.pe.last_price, 2)}</td>
                        <td className="dim">{num(s.pe.delta)}</td>
                        <td className="dim">{s.pe.iv ? `${(s.pe.iv * 100).toFixed(1)}%` : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {chain && <div className="gnote">{chain.note}</div>}
        </GlassPanel>
      )}

      {/* ---- futures ------------------------------------------------------- */}
      {tab === "futures" && (
        <GlassPanel title="Futures board" note="every unexpired MCX contract, priced live">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th><th className="l">Underlying</th>
                  <th>Expiry</th><th>LTP</th><th>Tick</th>
                  <th className="l">1 lot</th><th>Contract value</th><th>Trade</th>
                </tr>
              </thead>
              <tbody>
                {futures.map((f) => (
                  <tr key={f.symbol}>
                    <td className="l sym">{f.symbol}</td>
                    <td className="l">{f.underlying}{!f.verified && <span className="tag warn">spec?</span>}</td>
                    <td>{f.expiry}</td>
                    <td className="px">{num(f.ltp, 2)}</td>
                    <td className="dim">{f.tick}</td>
                    <td className="l dim">{f.lot_quantity}</td>
                    <td className="px">{compact(f.contract_value)}</td>
                    <td className="acts">
                      <button className="mini buy" disabled={!!busy || !f.ltp}
                              onClick={() => { setSymbol(f.underlying); trade("FUTURE", "BUY", f.expiry); }}>B</button>
                      <button className="mini sell" disabled={!!busy || !f.ltp}
                              onClick={() => { setSymbol(f.underlying); trade("FUTURE", "SELL", f.expiry); }}>S</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!futures.length && <div className="dim pad">Loading the board…</div>}
        </GlassPanel>
      )}

      {/* ---- positions ----------------------------------------------------- */}
      {tab === "positions" && (
        <>
          <GlassPanel title="Open positions" note="marked to the live Angel price">
            <PositionTable rows={summary?.open_positions ?? []} live busy={busy}
                           onExit={(p, l) => act(`exit-${p.position_id}`,
                             () => exitCmpPosition(p.position_id, accountId, l))} />
          </GlassPanel>
          <GlassPanel title="Closed positions" note="realised P&L">
            <PositionTable rows={summary?.closed_positions ?? []} busy={busy} />
          </GlassPanel>
          {summary?.note && <div className="gnote standalone">{summary.note}</div>}
        </>
      )}

      {/* ---- orders -------------------------------------------------------- */}
      {tab === "orders" && (
        <GlassPanel title="Order book" note={`${orders.length} orders`}>
          {!orders.length ? <EmptyState title="No orders yet" note="Trade from the chain or the futures board." /> : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="l">Contract</th><th>Side</th><th>Lots</th><th>Qty</th>
                    <th>Type</th><th>Fill</th><th>Contract value</th><th>Margin</th>
                    <th>Status</th><th>Placed</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.order_id}>
                      <td className="l sym">{o.display_name}</td>
                      <td className={o.transaction_type === "BUY" ? "gain" : "loss"}>{o.transaction_type}</td>
                      <td>{o.lots}</td><td>{o.quantity.toLocaleString("en-IN")}</td>
                      <td className="dim">{o.order_type}</td>
                      <td className="px">{num(o.fill_price, 2)}</td>
                      <td className="px">{compact(o.contract_value)}</td>
                      <td className="px">{compact(o.margin_used)}</td>
                      <td><StatusPill label={o.status} tone={o.status === "FILLED" ? "gain" : "muted"} /></td>
                      <td className="dim small">{o.placed_at ? new Date(o.placed_at).toLocaleString("en-IN") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassPanel>
      )}

      {/* ---- specs --------------------------------------------------------- */}
      {tab === "specs" && (
        <GlassPanel title="Contract specifications"
                    note="every multiplier re-derived from a live price">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Underlying</th><th className="l">1 lot</th>
                  <th className="l">Quoted</th><th>Multiplier</th>
                  <th>Live price</th><th>Contract value</th><th className="l">Source</th>
                </tr>
              </thead>
              <tbody>
                {specs.map((r) => (
                  <tr key={r.underlying} className={r.plausible ? "" : "bad"}>
                    <td className="l sym">{r.underlying}</td>
                    <td className="l">{r.lot_quantity}</td>
                    <td className="l dim">{r.price_unit}</td>
                    <td>×{r.multiplier.toLocaleString("en-IN")}</td>
                    <td className="px">{num(r.price, 2)}</td>
                    <td className="px">{compact(r.contract_value)}</td>
                    <td className="l small">
                      {r.verified
                        ? <span className="tag ok">published spec</span>
                        : <span className="tag warn">broker lot size</span>}
                      {!r.plausible && <span className="tag bad">implausible</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="gnote">
            A lot ranges from a 1-gram GOLDPETAL to a 1 kg GOLD bar, so the plausible band
            is wide on purpose — anything outside it means a multiplier is out by a power of
            ten and every P&amp;L on that underlying would be wrong by the same factor. The
            rows marked <strong>broker lot size</strong> have no published specification in
            this module: their value comes from the broker&apos;s order unit and should be
            checked against the exchange before trading.
          </div>
          <div className="pad">
            <button className="btn" disabled={!!busy}
                    onClick={() => act("sync", async () => {
                      const r = await syncCmpInstruments();
                      setNotice(`Reloaded ${r.mcx_contracts} MCX contracts across ${r.underlyings} underlyings.`);
                      setUnders((await fetchCmpUnderlyings()).underlyings);
                      setSpecs((await fetchCmpSpecCheck()).spec_check);
                    }, false)}>
              {busy === "sync" ? "Reloading…" : "Reload MCX contracts"}
            </button>
          </div>
        </GlassPanel>
      )}

      {tab === "history" && <DeskHistory deskKey="commodity-positions" scope={accountId} />}

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 18px; }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
        .tabs { display: flex; gap: 6px; flex-wrap: wrap; }
        .tab { padding: 7px 14px; border-radius: 100px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .tab.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
        .sel, .inp { border-radius: 9px; border: 1px solid var(--panel-border); background: var(--panel);
                     padding: 7px 10px; font-size: 12.5px; color: var(--text); font-family: var(--font-ui); }
        .inp { width: 90px; font-family: var(--font-data); }
        .ticket { display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; padding: 16px 20px; }
        .ticket label { display: flex; flex-direction: column; gap: 5px; font-size: 10.5px;
                        font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: var(--text-muted); }
        .specbox { margin-left: auto; font-size: 12px; max-width: 420px; }
        .specbox .dim { color: var(--text-muted); font-size: 11.5px; margin-top: 2px; }
        .specbox .warn { color: #b45309; font-size: 11.5px; margin-top: 5px; line-height: 1.45; }
        .chainbar { display: flex; gap: 12px; align-items: center; padding: 14px 20px 6px;
                    flex-wrap: wrap; font-size: 12px; }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px;
                      font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 8px 9px; font-size: 9.5px; font-weight: 700;
                         letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted);
                         border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 7px 9px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .atm { background: var(--purple-dim); }
        .bad { background: rgba(220,38,38,.06); }
        .strike { font-family: var(--font-data); font-weight: 700; }
        .px { font-family: var(--font-data); }
        .sym { font-weight: 600; }
        .dim { color: var(--text-muted); }
        .small { font-size: 11px; }
        .pad { padding: 14px 20px; }
        .gain { color: var(--gain); } .loss { color: var(--loss); }
        .acts { display: flex; gap: 4px; justify-content: center; }
        .mini { border: 1px solid var(--panel-border); border-radius: 6px; width: 24px; height: 22px;
                font-size: 10.5px; font-weight: 800; cursor: pointer; background: var(--panel); }
        .mini.buy { color: var(--gain); } .mini.sell { color: var(--loss); }
        .mini:disabled { opacity: .4; cursor: default; }
        .tag { font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 5px; margin-left: 5px;
               border: 1px solid var(--panel-border); background: var(--canvas-soft); }
        .tag.ok { color: var(--gain); } .tag.warn { color: #b45309; } .tag.bad { color: var(--loss); }
        .notice { padding: 12px 20px; font-size: 12.5px; }
        .gnote { padding: 10px 20px 16px; font-size: 11.5px; color: var(--text-muted);
                 max-width: 940px; line-height: 1.55; }
        .gnote.standalone { padding: 0 4px; }
        .btn.danger { color: var(--loss); }
      `}</style>
    </div>
  );
}

function PositionTable({ rows, live, busy, onExit }: {
  rows: CmpPosition[]; live?: boolean; busy: string | null;
  onExit?: (p: CmpPosition, lots?: number) => void;
}) {
  if (!rows.length) {
    return <EmptyState title={live ? "No open positions" : "Nothing closed yet"}
                       note="Trade from the option chain or the futures board." />;
  }
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th className="l">Contract</th><th>Side</th><th>Lots</th><th>Qty</th>
            <th>Entry</th><th>{live ? "LTP" : "Exit"}</th>
            <th>Contract value</th><th>Margin</th>
            <th>{live ? "Unrealised" : "Realised"}</th>
            {live && <th>Close</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const pnl = live ? p.unrealized_pnl : p.realized_pnl;
            return (
              <tr key={p.position_id}>
                <td className="l sym">{p.display_name}
                  <div className="small dim">{p.instrument_kind} · {p.product_type}</div>
                </td>
                <td className={p.side === "BUY" ? "gain" : "loss"}>{p.side}</td>
                <td>{p.lots}</td>
                <td className="dim">{p.quantity.toLocaleString("en-IN")}</td>
                <td className="px">{p.entry_price?.toFixed(2)}</td>
                <td className="px">{p.ltp?.toFixed(2)}</td>
                <td className="px">{p.contract_value >= 1e5
                  ? `₹${(p.contract_value / 1e5).toFixed(2)}L` : `₹${Math.round(p.contract_value)}`}</td>
                <td className="px dim">{p.margin_used >= 1e5
                  ? `₹${(p.margin_used / 1e5).toFixed(2)}L` : `₹${Math.round(p.margin_used)}`}</td>
                <td className={(pnl ?? 0) >= 0 ? "gain" : "loss"}>
                  {pnl === null || pnl === undefined ? "—"
                    : `${pnl >= 0 ? "+" : ""}₹${pnl.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
                </td>
                {live && (
                  <td>
                    <button className="mini" disabled={!!busy} onClick={() => onExit?.(p)}>×</button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      <style jsx>{`
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px;
                      font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 8px 9px; font-size: 9.5px; font-weight: 700;
                         letter-spacing: .04em; text-transform: uppercase; color: var(--text-muted);
                         border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 7px 9px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .sym { font-weight: 600; }
        .px { font-family: var(--font-data); }
        .dim { color: var(--text-muted); }
        .small { font-size: 11px; }
        .gain { color: var(--gain); } .loss { color: var(--loss); }
        .mini { border: 1px solid var(--panel-border); border-radius: 6px; width: 24px; height: 22px;
                font-size: 11px; font-weight: 800; cursor: pointer; background: var(--panel);
                color: var(--loss); }
        .mini:disabled { opacity: .4; cursor: default; }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: "gain" | "loss";
}) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      <div className={`t-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="t-sub">{sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
                padding: 14px 16px; box-shadow: var(--shadow-sm); }
        .t-label { font-size: 10.5px; font-weight: 700; letter-spacing: .05em;
                   text-transform: uppercase; color: var(--text-muted); }
        .t-value { margin-top: 7px; font-family: var(--font-data); font-variant-numeric: tabular-nums;
                   font-size: 21px; font-weight: 600; letter-spacing: -.2px; }
        .t-value.gain { color: var(--gain); } .t-value.loss { color: var(--loss); }
        .t-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}
