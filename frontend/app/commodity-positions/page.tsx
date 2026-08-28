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

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import EmptyState from "../../components/EmptyState";
import DeskHistory from "../../components/DeskHistory";
import {
  CmpBasketEstimate,
  CmpBasketLeg,
  CmpMaxLots,
  CmpChain,
  CmpFuture,
  CmpOrder,
  CmpPosition,
  CmpSpecCheckRow,
  CmpSummary,
  CmpUnderlying,
  createCmpAccount,
  editCmpAccount,
  estimateCmpBasket,
  executeCmpBasket,
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
  deleteCmpAccount,
  maxCmpLots,
  reopenCmpAtm,
  reopenCmpAtmAll,
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
// Mirrors COMMODITY_MAX_LOTS_PER_ORDER on the server. The server is the authority — this
// only keeps the box from accepting a number it will refuse.
const MAX_LOTS = 500;
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
  // Which underlying the expiry list above belongs to. Without this the chain fetches with
  // the NEW symbol and the OLD expiry the moment you switch commodity, because the expiry
  // list is loaded asynchronously and has not caught up — and MCX runs a different expiry
  // calendar per commodity, so that pair is usually a contract that does not exist.
  const [expiriesFor, setExpiriesFor] = useState("");
  const [futExpiries, setFutExpiries] = useState<string[]>([]);

  // Open on the book, not the chain. The first thing you want on arriving is what you
  // are already holding and what it is worth; the chain is where you go to add to it.
  const [tab, setTab] = useState<Tab>("positions");
  const [lots, setLots] = useState(1);
  // Auto-sizing for the at-the-money pair: the largest EQUAL number of calls and puts this
  // account can carry, sold or bought. Computed by the server against the same margin model
  // the order gate uses, so the number offered is a number that will actually fill.
  const [sizing, setSizing] = useState<{ sell: CmpMaxLots | null; buy: CmpMaxLots | null } | null>(null);
  const [sizingFor, setSizingFor] = useState("");
  // Bumped after a fill so the ATM pair is re-sized against the cash that is left. Keying
  // the sizer on live available cash instead would re-run it on every mark-to-market tick.
  const [sizingNonce, setSizingNonce] = useState(0);
  const [product, setProduct] = useState<"MARGIN" | "INTRADAY">("MARGIN");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loadingBook, setLoadingBook] = useState(true);
  const [loadingUnders, setLoadingUnders] = useState(true);
  const [undersError, setUndersError] = useState<string | null>(null);
  // The account editor. `mode` null means closed; "new" creates, "edit" renames and
  // re-capitalises the selected book. Replaces two window.prompt() calls, which could not
  // show what the number meant and looked like a different application.
  const [editor, setEditor] = useState<null | "new" | "edit">(null);
  // The basket. Buy/Sell adds a leg; nothing reaches the book until it is placed, and the
  // estimate below is what the execute gate will use — so the capital on screen is never a
  // different number from the one that decides whether the order is allowed.
  const [basket, setBasket] = useState<CmpBasketLeg[]>([]);
  const [quote, setQuote] = useState<CmpBasketEstimate | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formCapital, setFormCapital] = useState("");

  const spec = useMemo(() => unders.find((u) => u.symbol === symbol), [unders, symbol]);

  // True when the basket REDUCES the account's required margin rather than consuming any:
  // it hedges a position already open, so less is held against the pair than against the
  // surviving leg on its own.
  const releasesMargin = !!quote && quote.margin_released > 0;

  // Only options have an at-the-money strike, so futures are not counted in the button.
  const rollableLegs = (summary?.open_positions ?? []).filter(
    (p) => (p.instrument as { option_type?: string } | undefined)?.option_type).length;

  // The at-the-money strike: the listed strike nearest the underlying FUTURE, which is the
  // reference the chain is priced against — not the spot commodity, which MCX does not
  // quote intraday. Computed once here rather than rescanning every strike per row.
  const atmRow = useMemo(() => {
    if (!chain?.strikes?.length) return null;
    return chain.strikes.reduce((best, r) =>
      Math.abs(r.strike - chain.spot) < Math.abs(best.strike - chain.spot) ? r : best);
  }, [chain]);

  // One key for "which ATM pair, in which book". Sizing is only shown when it was computed
  // for exactly this key, so a stale number from the previous contract or the previous
  // account can never be displayed as if it applied here.
  const sizingKey = useMemo(
    () => (chain && atmRow && accountId
      ? `${accountId}|${chain.symbol}|${chain.expiry}|${atmRow.strike}` : ""),
    [accountId, chain, atmRow]);

  const atmSizing = sizingFor === sizingKey ? sizing?.sell ?? null : null;

  // Size the ATM pair whenever the contract or the account changes, and pre-fill Lots with
  // it. Both directions are priced: selling is margin-bound and buying is premium-bound, so
  // they are different numbers and neither stands in for the other.
  useEffect(() => {
    if (!sizingKey || !chain || !atmRow) { setSizing(null); setSizingFor(""); return; }
    let live = true;
    setSizing(null);
    setSizingFor("");
    const pair = (side: "BUY" | "SELL"): CmpBasketLeg[] =>
      (["CE", "PE"] as const).map((ot) => ({
        instrument_kind: "OPTION", symbol: chain.symbol, expiry: chain.expiry,
        strike: atmRow.strike, option_type: ot, transaction_type: side, lots: 1,
      }));
    Promise.all([
      maxCmpLots(accountId, pair("SELL")).catch(() => null),
      maxCmpLots(accountId, pair("BUY")).catch(() => null),
    ]).then(([sell, buy]) => {
      if (!live) return;
      setSizing({ sell, buy });
      setSizingFor(sizingKey);
      // Pre-fill with the selling size: every position in this book is a short pair, and
      // it is the binding constraint of the two. The buying size is one click away.
      if (sell && sell.max_lots > 0) setLots(sell.max_lots);
    });
    return () => { live = false; };
  }, [sizingKey, accountId, chain, atmRow, sizingNonce]);

  // ---- bootstrap -------------------------------------------------------------
  // Two INDEPENDENT loads, deliberately not one Promise.all. When they were combined, a
  // single slow endpoint rejected the pair and blanked the entire page — no accounts, no
  // underlyings, every tile a dash — even though the account list had answered fine.
  const loadAccounts = useCallback(async () => {
    try {
      const a = await fetchCmpAccounts();
      setAccounts(a.accounts);
      setAccountId((cur) => cur || a.accounts[0]?.account_id || "");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the paper accounts");
    }
  }, []);

  const loadUnderlyings = useCallback(async () => {
    setLoadingUnders(true);
    try {
      const u = await fetchCmpUnderlyings();
      setUnders(u.underlyings);
      setSymbol((cur) => cur ||
        (u.underlyings.find((x) => x.has_options) ?? u.underlyings[0])?.symbol || "");
      setUndersError(null);
    } catch (e) {
      setUndersError(e instanceof Error ? e.message : "Could not load the MCX board");
    } finally {
      setLoadingUnders(false);
    }
  }, []);

  useEffect(() => { loadAccounts(); loadUnderlyings(); }, [loadAccounts, loadUnderlyings]);

  // ---- expiries follow the underlying ----------------------------------------
  useEffect(() => {
    if (!symbol) return;
    // Drop the previous commodity's expiries immediately, so nothing downstream can pair
    // them with the new symbol while the new list is in flight.
    setExpiriesFor("");
    setOptExpiries([]);
    setOptExpiry("");
    setChain(null);
    let live = true;
    fetchCmpOptionExpiries(symbol).then((r) => {
      if (!live) return;
      setOptExpiries(r.expiries);
      setOptExpiry(r.expiries[0] ?? "");
      setExpiriesFor(symbol);
    }).catch(() => { if (live) setExpiriesFor(symbol); });
    fetchCmpFutureExpiries(symbol).then((r) => live && setFutExpiries(r.expiries))
      .catch(() => live && setFutExpiries([]));
    return () => { live = false; };
  }, [symbol]);

  useEffect(() => {
    // Only fetch once the expiry list is known to belong to THIS symbol and the chosen
    // expiry is one of its own.
    if (tab !== "chain" || !symbol || !optExpiry) return;
    if (expiriesFor !== symbol || !optExpiries.includes(optExpiry)) return;
    let live = true;
    setChain(null);
    fetchCmpChain(symbol, optExpiry)
      .then((c) => { if (live) { setChain(c); setError(null); } })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Chain unavailable"));
    return () => { live = false; };
  }, [tab, symbol, optExpiry, expiriesFor, optExpiries]);

  useEffect(() => {
    if (tab !== "futures") return;
    fetchCmpFutures().then((r) => { setFutures(r.contracts); setSpecs(r.spec_check); })
      .catch(() => {});
  }, [tab]);

  useEffect(() => {
    if (tab === "specs" && !specs.length) fetchCmpSpecCheck().then((r) => setSpecs(r.spec_check)).catch(() => {});
  }, [tab, specs.length]);

  const loadBook = useCallback(async () => {
    if (!accountId) { setLoadingBook(false); return; }
    try {
      const s = await fetchCmpPositions(accountId);
      setSummary(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    } finally {
      setLoadingBook(false);
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

  // ---- the basket ------------------------------------------------------------
  const addLeg = useCallback((leg: CmpBasketLeg) => {
    setBasket((cur) => {
      // Same contract and same direction? Add lots rather than stacking a duplicate row.
      const i = cur.findIndex((l) =>
        l.symbol === leg.symbol && l.expiry === leg.expiry &&
        l.instrument_kind === leg.instrument_kind &&
        (l.strike ?? null) === (leg.strike ?? null) &&
        (l.option_type ?? null) === (leg.option_type ?? null) &&
        l.transaction_type === leg.transaction_type);
      if (i >= 0) {
        const next = [...cur];
        next[i] = { ...next[i], lots: next[i].lots + leg.lots };
        return next;
      }
      return [...cur, leg];
    });
    setNotice(null);
  }, []);

  const setLegLots = (i: number, n: number) =>
    setBasket((cur) => cur.map((l, k) => (k === i ? { ...l, lots: Math.max(1, n) } : l)));
  const dropLeg = (i: number) => setBasket((cur) => cur.filter((_, k) => k !== i));

  // Re-price on every change. Debounced because each estimate resolves and quotes every
  // leg through Angel, which is rate-limited.
  useEffect(() => {
    if (!basket.length || !accountId) { setQuote(null); setQuoteError(null); return; }
    setQuoting(true);
    const t = setTimeout(() => {
      estimateCmpBasket(accountId, basket)
        .then((q) => { setQuote(q); setQuoteError(null); })
        .catch((e) => {
          setQuote(null);
          setQuoteError(e instanceof Error ? e.message : "Could not price the basket");
        })
        .finally(() => setQuoting(false));
    }, 350);
    return () => clearTimeout(t);
  }, [basket, accountId]);

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

  // Buy/Sell no longer fires an order — it puts a leg in the basket. Nothing reaches the
  // book without passing the affordability gate first.
  const trade = (kind: "OPTION" | "FUTURE", side: "BUY" | "SELL",
                 expiry: string, strike?: number, optionType?: "CE" | "PE") =>
    addLeg({ instrument_kind: kind, symbol, expiry, transaction_type: side, lots,
             strike: strike ?? null, option_type: optionType ?? null });

  // Roll a leg back to the money: close it, and put the same contract straight back on at
  // whichever listed strike now sits nearest the future. A strike picked weeks ago drifts
  // as the underlying moves — a 159000 call against a 162000 future is no longer the trade
  // that was put on — and doing it by hand is two trips through the chain with the book
  // unhedged in between.
  const reopenAtm = (p: CmpPosition) => {
    const inst = p.instrument as { strike?: number; option_type?: string } | undefined;
    if (!window.confirm(
      `Close ${p.display_name} (${p.lots} lots) and re-open the same `
      + `${inst?.option_type ?? "option"} at the at-the-money strike?\n\n`
      + `The ${inst?.strike ?? "current"} strike is closed at the live price, realising its `
      + `P&L, and the new leg goes on at the same ${p.lots} lots on the same side.`)) return;
    act(`atm-${p.position_id}`, async () => {
      const r = await reopenCmpAtm(p.position_id, accountId);
      const rs = Math.round(r.closed.realized).toLocaleString("en-IN");
      const md = Math.round(r.margin_delta).toLocaleString("en-IN");
      setNotice(
        `${r.closed.contract} closed at ${r.closed.exit_price} `
        + `(realised ${r.closed.realized >= 0 ? "+" : ""}₹${rs}), re-opened at the `
        + `${r.opened.strike} strike at ${r.opened.entry_price}. Future ${r.future} · `
        + `margin ${r.margin_delta >= 0 ? "+" : ""}₹${md}.`);
      setSizingNonce((n) => n + 1);
    });
  };

  // The same roll, across the whole book. Deliberately one server call rather than a
  // loop over the per-row buttons: rolling a straddle a leg at a time leaves a naked leg
  // in between, which costs MORE margin than the pair did, and on a tight book that
  // intermediate state can refuse the second roll and strand the position half-rolled.
  const rollBookToAtm = () => {
    const legs = (summary?.open_positions ?? []).filter(
      (p) => (p.instrument as { option_type?: string } | undefined)?.option_type);
    if (!legs.length) return;
    if (!window.confirm(
      `Roll all ${legs.length} option leg${legs.length > 1 ? "s" : ""} to the money?\n\n`
      + "Every one is closed at the live price, realising its P&L, and re-opened at the "
      + "strike nearest its own future — same side, same lots. Futures are left alone.\n\n"
      + "This is checked against your margin before anything is closed.")) return;
    act("rollall", async () => {
      const r = await reopenCmpAtmAll(accountId);
      const rs = Math.round(r.realized).toLocaleString("en-IN");
      const md = Math.round(r.margin_delta).toLocaleString("en-IN");
      setNotice(
        `${r.note} Realised ${r.realized >= 0 ? "+" : ""}₹${rs}, `
        + `margin ${r.margin_delta >= 0 ? "+" : ""}₹${md}.`);
      if (r.failed.length) {
        setError(r.failed.map((f) => `${f.underlying} ${f.expiry}: ${f.reason}`).join(" "));
      }
      setSizingNonce((n) => n + 1);
    });
  };

  const placeBasket = () =>
    act("basket", async () => {
      const res = await executeCmpBasket(accountId, basket, product);
      setBasket([]);
      setQuote(null);
      setSizingNonce((n) => n + 1);
      setNotice(`${res.filled} leg${res.filled > 1 ? "s" : ""} filled — margin blocked ` +
        `${compact(res.margin_added)}, net premium ${signed(res.net_premium)}.`);
      setTab("positions");
    });

  return (
    <div className="page">
      <PageHeader
        crumb="Commodity Positions"
        title="Commodity Positions"
        subtitle={
          <>
            Live MCX futures and option chains — buy or sell in lots at real prices, across
            multiple paper accounts each with its own balance. Priced by Angel One and
            margined with a local SPAN-style model. Not investment advice.
          </>
        }
        onRefresh={async () => {
          setLoadingBook(true);
          await Promise.all([loadAccounts(), loadUnderlyings(), loadBook()]);
        }}
        refreshing={busy === "refresh"}
        actions={
          <>
            <StatusPill label="MCX · paper" tone="accent" />
            <button className="btn primary" disabled={!!busy} onClick={() => {
              setFormName("");
              setFormCapital("10000000");
              setEditor("new");
            }}>
              <Icon d="M12 5v14M5 12h14" /> New account
            </button>
            <button className="btn" disabled={!!busy || !accountId} onClick={() => {
              const a = accounts.find((x) => x.account_id === accountId);
              setFormName(a?.name ?? "");
              setFormCapital(String(a?.initial_capital ?? 10000000));
              setEditor("edit");
            }}>
              <Icon d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z" /> Edit
            </button>
            <button className="btn danger" disabled={!!busy || !accountId} onClick={() => {
              if (!window.confirm("Wipe every position and order in this account?")) return;
              act("reset", () => resetCmpAccount(accountId));
            }}>
              <Icon d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /> Reset
            </button>
            <button className="btn danger" disabled={!!busy || !accountId} onClick={() => {
              const a = accounts.find((x) => x.account_id === accountId);
              if (!window.confirm(
                `Delete "${a?.name ?? "this account"}" and its whole history?\n\n` +
                "Closed positions and orders go with it. This cannot be undone — " +
                "Reset empties the book but keeps it.")) return;
              act("delete", async () => {
                const r = await deleteCmpAccount(accountId);
                // Point at another book BEFORE anything reloads, or the page keeps an id
                // that no longer resolves and every panel below renders an error.
                const rest = accounts.filter((x) => x.account_id !== accountId);
                setAccountId(rest[0]?.account_id ?? "");
                setBasket([]);
                setQuote(null);
                setNotice(`Deleted "${r.deleted}" — ${r.closed_positions_removed} closed ` +
                          `position(s) and ${r.orders_removed} order(s) went with it.`);
                await loadAccounts();
              }, false);
            }}>
              <Icon d="M10 11v6M14 11v6M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /> Delete
            </button>
          </>
        }
      />

      <div className="accountbar">
        <label className="fld">
          <span>Paper account</span>
          <select className="sel wide" value={accountId}
                  onChange={(e) => {
                    // Clear the fill notice with the account. It described the PREVIOUS
                    // book's trade, and left above another account's tiles it reads as a
                    // statement about this one — a premium figure from a different book.
                    setAccountId(e.target.value);
                    setNotice(null);
                    setQuoteError(null);
                    setLoadingBook(true);
                  }}>
            {!accounts.length && <option value="">Loading accounts…</option>}
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.name} — starting capital {compact(a.initial_capital)}
              </option>
            ))}
          </select>
        </label>
        <div className="lotnote">
          <b>An MCX lot is not one unit.</b> A ZINC lot is 5 tonnes and a GOLD lot is a
          kilogram, so every contract here shows its lot quantity and full contract value
          before you trade it — one lot ranges from ₹16,000 to ₹1.6 crore.
        </div>
      </div>

      {editor && (
        <GlassPanel
          title={editor === "new" ? "New paper account" : "Edit account"}
          note="capital is the book's starting balance — changing it rebases every return"
        >
          <div className="editor">
            <label className="fld">
              <span>Name</span>
              <input className="inp wide" value={formName} autoFocus
                     placeholder="e.g. MCX swing book"
                     onChange={(e) => setFormName(e.target.value)} />
            </label>
            <label className="fld">
              <span>Starting capital (₹)</span>
              <input className="inp wide mono" value={formCapital} inputMode="numeric"
                     onChange={(e) => setFormCapital(e.target.value.replace(/[^0-9.]/g, ""))} />
              <em className="hint">
                {Number(formCapital) > 0
                  ? `= ${compact(Number(formCapital))}`
                  : "enter a number greater than zero"}
              </em>
            </label>
            <div className="presets">
              {[1000000, 5000000, 10000000, 50000000, 100000000].map((v) => (
                <button key={v} type="button"
                        className={`chip ${Number(formCapital) === v ? "on" : ""}`}
                        onClick={() => setFormCapital(String(v))}>{compact(v)}</button>
              ))}
            </div>
            <div className="editor-actions">
              <button className="btn primary" disabled={!!busy || !formName.trim() || !(Number(formCapital) > 0)}
                      onClick={() => act(editor === "new" ? "new" : "edit", async () => {
                        const capital = Number(formCapital);
                        if (editor === "new") {
                          const a = await createCmpAccount(formName.trim(), capital);
                          await loadAccounts();
                          setAccountId(a.account_id);
                        } else {
                          await editCmpAccount(accountId, {
                            name: formName.trim(), initial_capital: capital });
                          await loadAccounts();
                        }
                        setEditor(null);
                        setNotice(editor === "new"
                          ? `Created ${formName.trim()} with ${compact(capital)}.`
                          : `${formName.trim()} now starts from ${compact(capital)}.`);
                      })}>
                {busy ? "Saving…" : editor === "new" ? "Create account" : "Save changes"}
              </button>
              <button className="btn" disabled={!!busy} onClick={() => setEditor(null)}>Cancel</button>
            </div>
          </div>
        </GlassPanel>
      )}

      {error && <ErrorBanner message={error} onRetry={loadBook} />}
      {undersError && <ErrorBanner
        message={undersError + " \u2014 the MCX contract board could not be read, "
                 + "so the underlying list is empty."}
        onRetry={loadUnderlyings} />}
      {notice && (
        <GlassPanel title="Filled" note="paper">
          <div className="notice">{notice}</div>
        </GlassPanel>
      )}

      {summary && summary.available_cash < 0 && (
        <div className="overcommitted">
          <b>This book is over-committed.</b> Its open positions require{" "}
          {compact(summary.margin_deployed)} of margin against{" "}
          {compact(summary.initial_capital)} of capital, so available cash is{" "}
          {compact(summary.available_cash)}. No further order will be accepted until you
          close something or raise the account&apos;s capital. Margin is re-derived from the
          live futures price on every fill, so this can also appear when a position moves
          against you.
        </div>
      )}

      {(basket.length > 0 || quoteError) && (
        <GlassPanel
          title={`Basket — ${basket.length} leg${basket.length === 1 ? "" : "s"}`}
          note="nothing is filled until you place it"
        >
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="l">Contract</th><th>Side</th><th>Lots</th>
                  <th className="l">1 lot</th><th>Price</th><th>Contract value</th><th />
                </tr>
              </thead>
              <tbody>
                {(quote?.legs ?? []).map((l, i) => (
                  <tr key={`${l.label}-${l.side}-${i}`}>
                    <td className="l sym">{l.label}
                      {!l.verified && <span className="tag warn">spec?</span>}
                    </td>
                    <td className={l.side === "BUY" ? "gain" : "loss"}>{l.side}</td>
                    <td>
                      <LotsInput className="inp tiny" max={MAX_LOTS}
                                 value={basket[i]?.lots ?? l.lots}
                                 onCommit={(n) => setLegLots(i, n)} />
                    </td>
                    <td className="l dim">{l.lot_quantity}</td>
                    <td className="px">{num(l.ltp, 2)}</td>
                    <td className="px">{compact(l.contract_value)}</td>
                    <td>
                      <button className="mini" onClick={() => dropLeg(i)} title="Remove leg">×</button>
                    </td>
                  </tr>
                ))}
                {!quote && basket.map((l, i) => (
                  <tr key={`pending-${i}`}>
                    <td className="l sym">{l.symbol} {l.expiry}{" "}
                      {l.instrument_kind === "OPTION" ? `${l.strike}${l.option_type}` : "FUT"}</td>
                    <td className={l.transaction_type === "BUY" ? "gain" : "loss"}>{l.transaction_type}</td>
                    <td>
                      <LotsInput className="inp tiny" max={MAX_LOTS} value={l.lots}
                                 onCommit={(n) => setLegLots(i, n)} />
                    </td>
                    <td className="l dim">—</td><td className="px">—</td><td className="px">—</td>
                    <td><button className="mini" onClick={() => dropLeg(i)}>×</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {quoteError && <div className="bad-note">{quoteError}</div>}

          <div className="basketfoot">
            <div className="figures">
              {/* A basket that hedges something already open needs NEGATIVE margin — the
                  book holds less against the pair than against the leg alone. Showing that
                  as "Margin required -12,331" reads like a defect, so it is labelled for
                  what it is. */}
              {releasesMargin ? (
                <Figure label="Margin released" value={compact(quote!.margin_released)}
                        tone="gain" sub="this basket hedges an open position" />
              ) : (
                <Figure label="Margin required" value={compact(quote?.margin_required)}
                        tone={quote && !quote.affordable ? "loss" : undefined}
                        sub={quote && quote.hedge_benefit > 0
                          ? `${compact(quote.hedge_benefit)} saved by hedging`
                          : "portfolio margin for the whole basket"} />
              )}
              <Figure label="Available cash" value={compact(quote?.available_cash)}
                      tone={(quote?.available_cash ?? 0) < 0 ? "loss" : undefined}
                      sub={quote ? `${compact(quote.cash_after)} left after` : "in this account"} />
              <Figure label="Contract exposure" value={compact(quote?.contract_exposure)}
                      sub="full notional controlled" />
              <Figure label="Net premium" value={signed(quote?.net_premium)}
                      tone={(quote?.net_premium ?? 0) >= 0 ? "gain" : "loss"}
                      sub={(quote?.net_premium ?? 0) >= 0 ? "received" : "paid"} />
            </div>

            <div className="basketactions">
              {quote && !quote.affordable && (
                <div className="blocked">
                  Short by <b>{compact(quote.shortfall)}</b> — this basket adds{" "}
                  {compact(quote.margin_required)} of margin and the account has{" "}
                  {compact(quote.available_cash)}. Reduce lots, remove a leg, or raise the
                  account&apos;s capital.
                </div>
              )}
              {releasesMargin && (quote?.available_cash ?? 0) < 0 && (
                <div className="freed">
                  This basket <b>frees {compact(quote!.margin_released)}</b> — it hedges what
                  is already open, so the book needs less held against it after the fill.
                  Allowed even though cash is negative: it cannot make this account any less
                  solvent, and refusing it would leave you holding the riskier half.
                </div>
              )}
              <button className="btn" disabled={!!busy} onClick={() => { setBasket([]); setQuote(null); }}>
                Clear
              </button>
              <button className="btn primary"
                      disabled={!!busy || quoting || !quote || !quote.affordable}
                      onClick={placeBasket}>
                {busy === "basket" ? "Placing…"
                  : quoting ? "Pricing…"
                  : quote && !quote.affordable ? "Exceeds available cash"
                  : releasesMargin ? `Place basket · frees ${compact(quote!.margin_released)}`
                  : `Place basket · ${compact(quote?.margin_required)}`}
              </button>
            </div>
          </div>
          {quote && <div className="gnote">{quote.note}</div>}
        </GlassPanel>
      )}

      <div className="tiles">
        <Tile label="Equity" value={compact(summary?.equity)} loading={loadingBook}
              sub={summary ? `started at ${compact(summary.initial_capital)}` : "no account selected"} />
        <Tile label="Available cash" value={compact(summary?.available_cash)} loading={loadingBook}
              tone={(summary?.available_cash ?? 0) < 0 ? "loss" : undefined}
              sub={`${compact(summary?.margin_deployed)} margin blocked`} />
        <Tile label="Contract exposure" value={compact(summary?.contract_exposure)} loading={loadingBook}
              sub="full notional of the open book" />
        <Tile label="Unrealised" value={signed(summary?.unrealized_pnl)} loading={loadingBook}
              tone={(summary?.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"}
              sub={`${summary?.open_count ?? 0} open`} />
        <Tile label="Realised" value={signed(summary?.realized_pnl)} loading={loadingBook}
              tone={(summary?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"}
              sub={`${summary?.closed_count ?? 0} closed`} />
        <Tile label="Underlyings" value={String(unders.length)} loading={loadingUnders}
              sub={unders.length
                ? `${unders.filter((u) => u.has_options).length} with options`
                : undersError ? "board unavailable" : "none loaded"} />
      </div>

      {/* ---- order ticket -------------------------------------------------- */}
      <GlassPanel title="Order ticket" note="applies to every Buy/Sell button below">
        <div className="ticket">
          <label>Underlying
            <UnderlyingPicker value={symbol} onChange={setSymbol}
                              unders={unders} loading={loadingUnders} />
          </label>
          <label>Lots
            <LotsInput value={lots} onCommit={setLots} max={MAX_LOTS} />
            {atmSizing && atmSizing.max_lots > 0 && (
              <button className="linkish" type="button"
                      onClick={() => setLots(atmSizing.max_lots)}
                      title={atmSizing.reason}>
                max {atmSizing.max_lots}
              </button>
            )}
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

          {chain && atmRow && (
            <div className="atmstrip">
              <div className="atmhead">
                <span className="atmtag">AT THE MONEY</span>
                <b className="atmstrike">{atmRow.strike.toLocaleString("en-IN")}</b>
                <span className="dim">
                  future {inr(chain.spot, 2)}
                  {atmRow.strike !== chain.spot && (
                    <> · strike is {chain.spot > atmRow.strike ? "below" : "above"} it by{" "}
                      {Math.abs(chain.spot - atmRow.strike).toFixed(2)}</>
                  )}
                </span>
                <span className="grow" />
                {sizingFor === sizingKey ? (
                  <span className="sizeline">
                    {atmSizing && atmSizing.max_lots > 0
                      ? <>max <b>{atmSizing.max_lots}</b> lots each side · {atmSizing.reason}</>
                      : <span className="warn-text">
                          {atmSizing?.reason ?? "this account cannot carry one lot here"}
                        </span>}
                  </span>
                ) : <span className="dim">sizing…</span>}
              </div>
              <div className="atmpair">
                {(["CE", "PE"] as const).map((ot) => {
                  const side = atmRow[ot === "CE" ? "ce" : "pe"];
                  return (
                    <div key={ot} className={`atmleg ${ot.toLowerCase()}`}>
                      <span className="atmlabel">{ot === "CE" ? "CALL" : "PUT"}</span>
                      <span className="atmname">
                        {chain.symbol} {atmRow.strike.toLocaleString("en-IN")}{ot}
                      </span>
                      <span className="atmpx">{num(side.last_price, 2)}</span>
                      <span className="atmiv">
                        {side.iv ? `${(side.iv * 100).toFixed(1)}% IV` : "—"}
                      </span>
                      <span className="grow" />
                      <button className="mini buy" disabled={!!busy}
                              onClick={() => trade("OPTION", "BUY", chain.expiry, atmRow.strike, ot)}>
                        Buy
                      </button>
                      <button className="mini sell" disabled={!!busy}
                              onClick={() => trade("OPTION", "SELL", chain.expiry, atmRow.strike, ot)}>
                        Sell
                      </button>
                    </div>
                  );
                })}
              </div>
              <div className="atmfoot dim">
                Lots is pre-filled with the largest EQUAL size this account can carry on both
                legs — {sizing?.sell ? <>{sizing.sell.max_lots} selling</> : "—"}
                {sizing?.buy ? <>, {sizing.buy.max_lots} buying</> : ""}. Sized against the
                same margin model the order gate uses, so it is a size that will fill.
                {sizing?.buy && sizing.buy.max_lots > 0 && (
                  <button className="linkish" type="button"
                          onClick={() => setLots(sizing.buy!.max_lots)}>
                    use the buying size
                  </button>
                )}
              </div>
            </div>
          )}

          {!optExpiries.length ? (
            <EmptyState
              title={expiriesFor !== symbol ? `Loading ${symbol} expiries…`
                                            : `${symbol} has no listed options`}
              note={expiriesFor !== symbol
                ? "MCX runs a different expiry calendar per commodity."
                : "MCX lists options on ten underlyings only. Use the Futures tab for this one."} />
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
                  {chain.strikes.map((s) => (
                      <tr key={s.strike}
                          className={s.strike === atmRow?.strike ? "atm" : ""}>
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
                  ))}
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
            {!!rollableLegs && (
              <div className="bookbar">
                <div className="bookbar-say">
                  <b>Roll the book to the money.</b> Every option leg closed at the live
                  price and re-opened at the strike nearest its own future — same side,
                  same lots. Checked against your margin before anything is closed, and
                  done per expiry group so a straddle never sits half-rolled.
                </div>
                <button className="btn rollall" disabled={!!busy}
                        onClick={rollBookToAtm}>
                  {busy === "rollall"
                    ? "Rolling the book…"
                    : `Re-add ATM · all ${rollableLegs} leg${rollableLegs > 1 ? "s" : ""}`}
                </button>
              </div>
            )}
            <PositionTable rows={summary?.open_positions ?? []} live busy={busy}
                           onReopenAtm={reopenAtm}
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
        .page {
          display: flex; flex-direction: column; gap: 18px;

          /* Four token names this page uses are not defined anywhere in the frontend:
             --fg, --fg-dim, --line and --purple-line. An undefined custom property makes
             the whole declaration invalid at computed-value time, so a colour set from
             --fg-dim was rendering as ordinary body text rather than muted, and a border
             set from --purple-line was falling back to currentColor. Alias them to the
             real design tokens once, here, so every rule on the page is repaired rather
             than each call site being hunted down.
             (No backticks in this comment: the block is a template literal, and one ends
             the string.) */
          --fg: var(--text);
          --fg-dim: var(--text-muted);
          --line: var(--panel-border);
          --purple-line: var(--purple-glow);
          --purple-line: color-mix(in srgb, var(--purple) 30%, transparent);
        }
        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
        .tabs { display: flex; gap: 6px; flex-wrap: wrap; }
        .tab { padding: 7px 14px; border-radius: 100px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text-muted); }
        .tab.on { background: var(--purple-dim); border-color: rgba(125,52,220,.24); color: var(--purple); }
        .sel, .inp { border-radius: 10px; border: 1px solid var(--panel-border); background: var(--panel);
                     padding: 8px 11px; font-size: 12.5px; color: var(--text);
                     font-family: var(--font-ui); transition: border-color .15s, box-shadow .15s; }
        .sel:focus, .inp:focus { outline: none; border-color: rgba(125,52,220,.45);
                                 box-shadow: 0 0 0 3px var(--purple-dim); }
        .inp { width: 90px; font-family: var(--font-data); }
        .inp.wide { width: 260px; }
        .inp.mono { font-family: var(--font-data); letter-spacing: .3px; }

        /* Buttons. .btn is not a global class in this app — every page supplies its own,
           and this page previously supplied none, so these rendered as bare native
           buttons. Matched to PageHeader's own Refresh control so the row reads as one
           set of controls rather than two. (No backticks in here: this is inside a
           template literal and one would end it.) */
        .btn { display: inline-flex; align-items: center; gap: 7px; border-radius: 10px;
               border: 1px solid var(--panel-border); background: var(--canvas-soft);
               color: var(--text-muted); padding: 8px 14px; font-size: 12.5px;
               font-weight: 600; cursor: pointer; font-family: var(--font-ui);
               transition: background .15s, color .15s, border-color .15s, transform .06s; }
        .btn:hover:not(:disabled) { color: var(--purple); border-color: rgba(125,52,220,.32);
                                    background: var(--purple-dim); }
        .btn:active:not(:disabled) { transform: translateY(1px); }
        .btn:disabled { opacity: .5; cursor: default; }
        .btn.primary { background: var(--purple); border-color: var(--purple); color: #fff;
                       box-shadow: 0 1px 2px rgba(125,52,220,.35); }
        .btn.primary:hover:not(:disabled) { background: #6a2cbb; border-color: #6a2cbb; color: #fff; }
        .btn.danger { color: var(--loss); }
        .btn.danger:hover:not(:disabled) { color: #fff; background: var(--loss);
                                           border-color: var(--loss); }

        .inp.tiny { width: 60px; padding: 5px 8px; text-align: center; }
        .basketfoot { display: flex; gap: 20px; align-items: flex-end; flex-wrap: wrap;
                      padding: 14px 20px 4px; }
        .figures { display: flex; gap: 26px; flex-wrap: wrap; }
        .basketactions { margin-left: auto; display: flex; gap: 8px; align-items: flex-end;
                         flex-wrap: wrap; }
        .blocked { font-size: 11.5px; color: var(--loss); max-width: 380px; line-height: 1.5;
                   align-self: center; }
        .freed {
          color: var(--gain); font-size: 12px; line-height: 1.55;
          max-width: 560px; text-align: right;
        }
        .bad-note { padding: 10px 20px; font-size: 12px; color: var(--loss); }
        .overcommitted { border: 1px solid rgba(220,38,38,.35); background: rgba(220,38,38,.06);
                         border-radius: 14px; padding: 13px 18px; font-size: 12.5px;
                         color: var(--loss); line-height: 1.55; }
        .editor { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; padding: 16px 20px; }
        .editor .hint { font-style: normal; font-size: 11px; color: var(--text-faint);
                        font-weight: 500; letter-spacing: 0; text-transform: none; }
        .presets { display: flex; gap: 6px; flex-wrap: wrap; align-self: flex-end; padding-bottom: 2px; }
        .chip { font-size: 11.5px; font-weight: 600; padding: 6px 11px; border-radius: 100px;
                cursor: pointer; border: 1px solid var(--panel-border);
                background: var(--panel); color: var(--text-muted); font-family: var(--font-ui); }
        .chip.on { background: var(--purple-dim); border-color: rgba(125,52,220,.3); color: var(--purple); }
        .editor-actions { display: flex; gap: 8px; align-self: flex-end; margin-left: auto;
                          padding-bottom: 2px; }
        .accountbar { display: flex; gap: 20px; align-items: flex-end; flex-wrap: wrap;
                      padding: 14px 18px; border: 1px solid var(--panel-border);
                      border-radius: 14px; background: var(--panel); box-shadow: var(--shadow-sm); }
        .fld { display: flex; flex-direction: column; gap: 5px; font-size: 10.5px;
               font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
               color: var(--text-muted); }
        .sel.wide { min-width: 300px; }
        .lotnote { flex: 1; min-width: 320px; font-size: 11.5px; color: var(--text-muted);
                   line-height: 1.5; }
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

        .bookbar {
          display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
          padding: 12px 16px; margin: 0 0 2px;
          border-bottom: 1px solid var(--panel-border);
          background: var(--panel-tint);
        }
        .bookbar-say {
          flex: 1 1 320px; min-width: 0;
          font-size: 12px; line-height: 1.55; color: var(--text-muted);
        }
        .bookbar-say b { color: var(--text); font-weight: 650; }
        .btn.rollall {
          flex: none;
          color: var(--purple); background: var(--purple-dim);
          border-color: rgba(125, 52, 220, .28);
        }
        .btn.rollall:hover:not(:disabled) { border-color: var(--purple); }

        /* The at-the-money pair, lifted above the ladder. The ladder itself is unchanged —
           this is an addition, not a reordering, so a strike stays where you expect it. */
        .atmstrip {
          border: 1px solid var(--purple-line);
          background: var(--purple-dim);
          border-radius: 14px;
          padding: 12px 14px;
          margin-bottom: 14px;
          display: flex; flex-direction: column; gap: 10px;
        }
        .atmhead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .atmtag {
          font-size: 10px; font-weight: 700; letter-spacing: .09em;
          color: var(--purple); border: 1px solid var(--purple-line);
          border-radius: 999px; padding: 3px 9px; background: var(--panel);
        }
        .atmstrike { font-size: 19px; font-variant-numeric: tabular-nums; }
        .grow { flex: 1 1 auto; }
        .sizeline { font-size: 12px; color: var(--fg-dim); }
        .sizeline b { color: var(--fg); font-variant-numeric: tabular-nums; }
        .warn-text { color: var(--loss); font-size: 12px; }

        .atmpair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .atmleg {
          display: flex; align-items: center; gap: 10px;
          background: var(--panel); border: 1px solid var(--line);
          border-radius: 10px; padding: 9px 12px; min-width: 0;
        }
        .atmleg.ce { border-left: 3px solid var(--gain); }
        .atmleg.pe { border-left: 3px solid var(--loss); }
        .atmlabel {
          font-size: 10px; font-weight: 700; letter-spacing: .07em; color: var(--fg-dim);
        }
        .atmname {
          font-size: 12px; color: var(--fg-dim);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .atmpx {
          font-size: 16px; font-weight: 650; font-variant-numeric: tabular-nums;
        }
        .atmiv { font-size: 11px; color: var(--fg-dim); font-variant-numeric: tabular-nums; }
        .atmfoot { font-size: 11.5px; line-height: 1.5; }

        .linkish {
          background: none; border: 0; padding: 0 0 0 6px; cursor: pointer;
          color: var(--purple); font: inherit; font-size: 11.5px;
          text-decoration: underline; text-underline-offset: 2px;
        }
        .linkish:hover { opacity: .78; }

        @media (max-width: 720px) {
          .atmpair { grid-template-columns: 1fr; }
        }
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
      `}</style>
    </div>
  );
}

/** One labelled number in the basket footer — smaller than a Tile, same vocabulary. */
/** A lot-count box you can actually edit.
 *
 * The obvious `value={n} onChange={e => set(Number(e.target.value) || 1)}` cannot be typed
 * in. Backspacing to empty parses as 0, the `|| 1` snaps it straight back to "1", and the
 * caret lands after a digit nobody typed — so changing 10 to 30 means deleting the 0,
 * watching a 1 reappear, and never getting the field empty. Replacing the value is
 * impossible without selecting all of it first.
 *
 * The fix is to let the field hold raw text while it has focus, including empty, and only
 * coerce to a number on blur. Digits still commit as you type, so the estimate below keeps
 * updating live; it is only the snap-back that is gone. Focus also selects, so typing over
 * a value works the way it does everywhere else. */
function LotsInput({ value, onCommit, min = 1, max = MAX_LOTS, className = "inp" }: {
  value: number;
  onCommit: (n: number) => void;
  min?: number;
  max?: number;
  className?: string;
}) {
  const [text, setText] = useState(String(value));
  const [editing, setEditing] = useState(false);

  useEffect(() => { if (!editing) setText(String(value)); }, [value, editing]);

  return (
    <>
      <LotsInputStyles />
    <input
      className={className.replace(/\binp\b/, "cmp-inp")}
      type="text"
      inputMode="numeric"
      value={editing ? text : String(value)}
      aria-label="Lots"
      onFocus={(e) => { setEditing(true); setText(String(value)); e.currentTarget.select(); }}
      onChange={(e) => {
        const raw = e.target.value.replace(/[^0-9]/g, "").slice(0, 5);
        setText(raw);
        const n = parseInt(raw, 10);
        // Empty and 0 are legal to HOLD but not to commit — they are mid-edit states.
        if (Number.isFinite(n) && n >= min) onCommit(Math.min(max, n));
      }}
      onBlur={() => {
        setEditing(false);
        const n = parseInt(text, 10);
        onCommit(Number.isFinite(n) && n >= min ? Math.min(max, n) : min);
      }}
    />
    </>
  );
}

/* styled-jsx scopes a style block to the component that DECLARES it, so a helper
   component gets nothing from the page's block however many classes it shares. The .inp
   rules below are the page's, repeated here because this input lives in its own
   component and was otherwise rendering as a bare browser field. */
function LotsInputStyles() {
  return (
    <style jsx global>{`
      .cmp-inp {
        border-radius: 10px;
        border: 1px solid var(--panel-border);
        background: var(--panel);
        color: var(--text);
        padding: 8px 11px;
        font-size: 12.5px;
        font-family: var(--font-data);
        font-variant-numeric: tabular-nums;
        width: 90px;
        transition: border-color .15s, box-shadow .15s;
      }
      .cmp-inp:focus {
        outline: none;
        border-color: rgba(125, 52, 220, .45);
        box-shadow: 0 0 0 3px var(--purple-dim);
      }
      .cmp-inp.tiny { width: 68px; padding: 6px 9px; font-size: 12px; }
    `}</style>
  );
}

// The four mini contracts, in the order they are pinned. These are not favourites: on a
// paper book of a few lakh they are the only contracts on their market that a single lot
// fits inside. A GOLD lot is a kilogram and runs past a crore of notional; GOLDM is a
// tenth of that. Burying them alphabetically between GOLDGUINEA and GOLDPETAL hides the
// one contract most of these accounts can actually trade.
const MINI_SYMBOLS = ["NATGASMINI", "CRUDEOILM", "GOLDM", "SILVERM"] as const;

/** The underlying picker.
 *
 * A native <select> cannot group, cannot search, cannot show a second line, and renders
 * as an OS menu that looks nothing like the rest of the page. With 28 commodities — most
 * of them futures-only, and the tradable minis scattered through the alphabet — that list
 * was a wall of names in which the useful entries were the hardest to find. */
function UnderlyingPicker({ value, onChange, unders, loading }: {
  value: string;
  onChange: (symbol: string) => void;
  unders: CmpUnderlying[];
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  // Where to put the menu on screen. It is rendered into document.body rather than beside
  // the trigger, so it needs real coordinates instead of `top: 100%`.
  const [at, setAt] = useState<{ top: number; left: number; width: number } | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const selected = unders.find((u) => u.symbol === value) ?? null;

  const groups = useMemo(() => {
    const q = query.trim().toUpperCase();
    const hit = (u: CmpUnderlying) =>
      !q || u.symbol.includes(q) || (u.lot_quantity ?? "").toUpperCase().includes(q);
    const rest = unders.filter((u) => !MINI_SYMBOLS.includes(u.symbol as never));
    return [
      {
        key: "mini",
        label: "Minis",
        note: "smallest lot on each market",
        rows: MINI_SYMBOLS
          .map((sym) => unders.find((u) => u.symbol === sym))
          .filter((u): u is CmpUnderlying => !!u && hit(u)),
      },
      {
        key: "options",
        label: "Full size, with options",
        note: null,
        rows: rest.filter((u) => u.has_options && hit(u)),
      },
      {
        key: "futures",
        label: "Futures only",
        note: "MCX lists no options on these",
        rows: rest.filter((u) => !u.has_options && hit(u)),
      },
    ].filter((g) => g.rows.length);
  }, [unders, query]);

  // One flat list behind the groups, so the arrow keys walk the visible rows in the
  // order they are drawn rather than the order the data arrived in.
  const flat = useMemo(() => groups.flatMap((g) => g.rows), [groups]);

  useEffect(() => { setCursor(0); }, [query]);

  // The menu is portalled to document.body because every ancestor panel on this page sets
  // overflow: hidden to clip its own rounded corners — which also clipped the menu, leaving
  // the search box visible and the list cut off at the panel edge. A portal escapes that,
  // at the cost of having to place and re-place the menu by hand.
  const place = useCallback(() => {
    const r = boxRef.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.max(392, r.width);
    const height = Math.min(408, window.innerHeight - 24);
    const below = window.innerHeight - r.bottom - 8;
    // Drop upward when there is not room beneath, so the list is never half off-screen.
    const top = below >= height || r.top - 8 < height
      ? r.bottom + 7
      : Math.max(8, r.top - 7 - height);
    const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
    setAt({ top, left, width });
  }, []);

  useEffect(() => {
    if (!open) { setAt(null); return; }
    place();
    searchRef.current?.focus();
    const away = (e: MouseEvent) => {
      const t = e.target as Node;
      if (boxRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    // `true` so the menu follows the trigger when any scrolling ancestor moves, not only
    // the window.
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  const pick = (sym: string) => { onChange(sym); setOpen(false); setQuery(""); };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); setQuery(""); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => {
        const n = flat.length;
        if (!n) return 0;
        return (c + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
      });
      return;
    }
    if (e.key === "Enter" && flat[cursor]) { e.preventDefault(); pick(flat[cursor].symbol); }
  };

  if (!unders.length) {
    return (
      <button className="picker" type="button" disabled>
        <span className="pickmain">{loading ? "Loading MCX board…" : "No contracts on file"}</span>
      </button>
    );
  }

  let index = -1;
  return (
    <div className="pickwrap" ref={boxRef}>
      <button className={`picker${open ? " open" : ""}`} type="button"
              aria-haspopup="listbox" aria-expanded={open}
              onClick={() => setOpen((o) => !o)} onKeyDown={onKey}>
        <span className="pickcol">
          <span className="pickmain">
            {selected?.symbol ?? "Pick a commodity"}
            {selected && MINI_SYMBOLS.includes(selected.symbol as never) && (
              <span className="minitag">mini</span>
            )}
          </span>
          <span className="picksub">
            {selected
              ? `${selected.lot_quantity ?? "1 lot"} · ${selected.has_options
                  ? `${selected.options.toLocaleString("en-IN")} options`
                  : "futures only"}`
              : `${unders.length} MCX underlyings`}
          </span>
        </span>
        <svg className={`chev ${open ? "up" : ""}`} viewBox="0 0 24 24" width="16" height="16"
             fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && at && typeof document !== "undefined" && createPortal(
        <div className="pickmenu" role="listbox" ref={menuRef} onKeyDown={onKey}
             style={{ top: at.top, left: at.left, width: at.width }}>
          <input ref={searchRef} className="picksearch" value={query} placeholder="Search commodities…"
                 onChange={(e) => setQuery(e.target.value)} onKeyDown={onKey} />
          <div className="picklist">
            {groups.map((g) => (
              <div key={g.key} className="pickgroup">
                <div className="pickhead">
                  {g.label}
                  {g.note && <span className="pickheadnote">{g.note}</span>}
                </div>
                {g.rows.map((u) => {
                  index += 1;
                  const here = index;
                  return (
                    <button key={u.symbol} type="button" role="option"
                            aria-selected={u.symbol === value}
                            className={`pickrow${u.symbol === value ? " on" : ""}`
                                       + (here === cursor ? " cursor" : "")}
                            onMouseEnter={() => setCursor(here)}
                            onClick={() => pick(u.symbol)}>
                      <span className="pickrowsym">{u.symbol}</span>
                      <span className="pickrowlot">{u.lot_quantity ?? "—"}</span>
                      <span className={`pickrowopt${u.has_options ? "" : " none"}`}>
                        {u.has_options
                          ? `${u.options.toLocaleString("en-IN")} options`
                          : "futures only"}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
            {!flat.length && (
              <div className="pickempty">Nothing matches “{query}”.</div>
            )}
          </div>
        </div>,
        document.body,
      )}

      <style jsx>{`
        .pickwrap { position: relative; display: inline-block; }

        .picker {
          display: flex; align-items: center; gap: 12px;
          min-width: 268px; width: 100%;
          padding: 7px 12px;
          border-radius: 10px;
          border: 1px solid var(--panel-border);
          background: var(--panel);
          color: var(--text);
          font-family: var(--font-ui);
          text-align: left;
          cursor: pointer;
          transition: border-color .15s, box-shadow .15s;
        }
        .picker:hover:not(:disabled) { border-color: var(--panel-border-hover); }
        .picker.open, .picker:focus-visible {
          outline: none;
          border-color: rgba(125, 52, 220, .45);
          box-shadow: 0 0 0 3px var(--purple-dim);
        }
        .picker:disabled { opacity: .55; cursor: default; }

        .pickcol { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
        .pickmain {
          display: flex; align-items: center; gap: 7px;
          font-size: 13.5px; font-weight: 600; letter-spacing: -.1px;
        }
        .picksub {
          font-size: 11px; color: var(--text-muted);
          font-family: var(--font-data); font-variant-numeric: tabular-nums;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .minitag {
          font-size: 9px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
          color: var(--purple); background: var(--purple-dim);
          border: 1px solid rgba(125, 52, 220, .24);
          border-radius: 100px; padding: 2px 7px; line-height: 1.35;
        }
        .chev { color: var(--text-faint); flex: none; transition: transform .18s ease; }
        .chev.up { transform: rotate(180deg); }

        .pickmenu {
          position: fixed; z-index: 200;
          background: var(--panel);
          border: 1px solid var(--panel-border);
          border-radius: 14px;
          box-shadow: var(--shadow-lg);
          overflow: hidden;
          font-family: var(--font-ui);
        }
        .picksearch {
          display: block; width: 100%;
          padding: 11px 14px;
          border: 0; border-bottom: 1px solid var(--panel-border);
          background: transparent;
          color: var(--text);
          font-family: var(--font-ui); font-size: 12.5px;
          outline: none;
        }
        .picksearch::placeholder { color: var(--text-faint); }

        .picklist { max-height: 348px; overflow-y: auto; padding: 6px; }
        .picklist::-webkit-scrollbar { width: 10px; }
        .picklist::-webkit-scrollbar-thumb {
          background: var(--scroll-thumb); border-radius: 100px;
          border: 3px solid var(--panel);
        }
        .picklist::-webkit-scrollbar-thumb:hover { background: var(--scroll-thumb-hover); }

        .pickgroup + .pickgroup {
          margin-top: 5px; padding-top: 5px;
          border-top: 1px solid var(--panel-border);
        }
        .pickhead {
          display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
          padding: 8px 10px 6px;
          font-size: 10px; font-weight: 700; letter-spacing: .06em;
          text-transform: uppercase; color: var(--text-muted);
        }
        .pickheadnote {
          font-size: 10.5px; font-weight: 500; letter-spacing: 0;
          text-transform: none; color: var(--text-faint);
        }

        .pickrow {
          display: grid;
          grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) auto;
          align-items: center; gap: 12px;
          width: 100%; padding: 8px 10px;
          border: 0; border-radius: 9px;
          background: none; color: var(--text);
          font-family: var(--font-ui); text-align: left;
          cursor: pointer;
        }
        .pickrow.cursor { background: var(--panel-tint); }
        .pickrow.on {
          background: var(--purple-dim);
          box-shadow: inset 2px 0 0 var(--purple);
        }
        .pickrowsym {
          font-size: 13px; font-weight: 600; letter-spacing: -.1px;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .pickrowlot {
          font-size: 11.5px; color: var(--text-muted);
          font-family: var(--font-data); font-variant-numeric: tabular-nums;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .pickrowopt {
          justify-self: end;
          font-size: 10.5px; font-weight: 600; white-space: nowrap;
          font-family: var(--font-data); font-variant-numeric: tabular-nums;
          color: var(--purple); background: var(--purple-dim);
          border-radius: 100px; padding: 3px 9px;
        }
        .pickrowopt.none {
          color: var(--text-faint); background: var(--panel-tint);
          font-weight: 500;
        }
        .pickempty {
          padding: 22px 14px; text-align: center;
          font-size: 12.5px; color: var(--text-muted);
        }
        @media (max-width: 620px) {
          .pickrow { grid-template-columns: minmax(0, 1fr) auto; }
          .pickrowlot { display: none; }
        }

        @media (max-width: 620px) {
          .picker { min-width: 0; }
        }

      `}</style>
    </div>
  );
}

function Figure({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: "gain" | "loss";
}) {
  return (
    <div className="fig">
      <div className="f-label">{label}</div>
      <div className={`f-value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="f-sub">{sub}</div>}
      <style jsx>{`
        .fig { min-width: 120px; }
        .f-label { font-size: 9.5px; font-weight: 800; letter-spacing: .06em;
                   text-transform: uppercase; color: var(--text-muted); }
        .f-value { margin-top: 4px; font-family: var(--font-data); font-size: 17px;
                   font-weight: 600; font-variant-numeric: tabular-nums; }
        .f-value.gain { color: var(--gain); } .f-value.loss { color: var(--loss); }
        .f-sub { margin-top: 2px; font-size: 10.5px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}


/** A 14px stroked glyph, so a button reads as an action rather than a word in a box. */
function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
         strokeWidth={2.1} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}


function PositionTable({ rows, live, busy, onExit, onReopenAtm }: {
  rows: CmpPosition[]; live?: boolean; busy: string | null;
  onExit?: (p: CmpPosition, lots?: number) => void;
  onReopenAtm?: (p: CmpPosition) => void;
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
            {live && onReopenAtm && <th>Re-add ATM</th>}
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
                {live && onReopenAtm && (
                  <td>
                    {(p.instrument as { option_type?: string } | undefined)?.option_type ? (
                      <button className="mini roll" disabled={!!busy}
                              onClick={() => onReopenAtm(p)}
                              title="Close this leg and re-open the same option at today's at-the-money strike">
                        {busy === `atm-${p.position_id}` ? "Rolling…" : "Re-add ATM"}
                      </button>
                    ) : (
                      <span className="dim small">futures</span>
                    )}
                  </td>
                )}
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
        /* The roll button carries a word, so it cannot use the square close-button box. */
        .mini.roll { width: auto; height: 24px; padding: 0 11px; white-space: nowrap;
                     font-size: 11px; font-weight: 700; letter-spacing: .01em;
                     color: var(--purple); border-color: rgba(125, 52, 220, .28);
                     background: var(--purple-dim); border-radius: 100px;
                     transition: background .15s, border-color .15s; }
        .mini.roll:hover:not(:disabled) { border-color: var(--purple); }
        .small { font-size: 10.5px; }
      `}</style>
    </div>
  );
}

function Tile({ label, value, sub, tone, loading }: {
  label: string; value: string; sub?: string; tone?: "gain" | "loss"; loading?: boolean;
}) {
  return (
    <div className="tile">
      <div className="t-label">{label}</div>
      {loading
        ? <div className="t-skel" />
        : <div className={`t-value ${tone ?? ""}`}>{value}</div>}
      {sub && <div className="t-sub">{loading ? "loading\u2026" : sub}</div>}
      <style jsx>{`
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
                padding: 14px 16px; box-shadow: var(--shadow-sm); }
        .t-label { font-size: 10.5px; font-weight: 700; letter-spacing: .05em;
                   text-transform: uppercase; color: var(--text-muted); }
        .t-value { margin-top: 7px; font-family: var(--font-data); font-variant-numeric: tabular-nums;
                   font-size: 21px; font-weight: 600; letter-spacing: -.2px; }
        .t-value.gain { color: var(--gain); } .t-value.loss { color: var(--loss); }
        .t-skel { margin-top: 9px; height: 22px; width: 70%; border-radius: 6px;
                  background: linear-gradient(90deg, var(--canvas-soft) 25%,
                              var(--panel-border) 50%, var(--canvas-soft) 75%);
                  background-size: 200% 100%; animation: shim 1.3s linear infinite; }
        @keyframes shim { to { background-position: -200% 0; } }
        .t-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}
