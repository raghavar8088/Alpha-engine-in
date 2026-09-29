"use client";

/** Gold Desk — the pattern library on gold, on two venues that price the same metal.
 *
 * Two tabs, one page, because the comparison IS the module: MCX gold futures in rupees
 * per 10 grams during Indian hours, and Delta's gold-backed token perpetuals in dollars
 * per ounce around the clock. Each has its own book, its own switch and its own costs,
 * and no number on this page ever adds the two together.
 *
 * Ported from the antigravity app's Gold Desk. Rebuilt on this app's shared pattern
 * library and paper-book plumbing rather than proxied to that app's Go engine — that
 * engine is stopped more often than it runs, and a page that renders someone else's
 * process is a page that shows an error most days.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import DeskHistory from "../../components/DeskHistory";
import {
  GoldBasis,
  GoldPosition,
  GoldStrategy,
  GoldSummary,
  GoldVenueKey,
  closeAllGold,
  fetchGoldBasis,
  fetchGoldPositions,
  fetchGoldStrategies,
  fetchGoldVenues,
  runGoldCycle,
  toggleGoldDesk,
} from "../../lib/api";

const REFRESH_MS = 20000;

/** Money in the book's OWN currency. The two tabs are never expressed in one unit — an
 *  INR total beside a USD total that shared a symbol would read as one book. */
function money(v: number | null | undefined, ccy: string, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = signed ? (v >= 0 ? "+" : "−") : v < 0 ? "−" : "";
  const abs = Math.abs(v);
  if (ccy === "USD") {
    return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: abs < 100 ? 2 : 0 })}`;
  }
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
const plain = (v: number | null | undefined, ccy: string) => money(v, ccy, false);
const pc = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
/** Gold quotes at 4,150 on one venue and 146,800 on the other — precision by magnitude. */
const px = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0
    ? "—"
    : v >= 10000
      ? v.toLocaleString("en-IN", { maximumFractionDigits: 0 })
      : v.toFixed(2);
const when = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

export default function GoldDeskPage() {
  const [tab, setTab] = useState<GoldVenueKey>("mcx");
  const [venues, setVenues] = useState<GoldSummary[]>([]);
  const [strats, setStrats] = useState<GoldStrategy[]>([]);
  const [open, setOpen] = useState<GoldPosition[]>([]);
  const [closed, setClosed] = useState<GoldPosition[]>([]);
  const [basis, setBasis] = useState<GoldBasis | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, b] = await Promise.all([fetchGoldVenues(), fetchGoldBasis()]);
      setVenues(v.venues);
      setBasis(b);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the Gold Desk.");
    }
  }, []);

  const loadTab = useCallback(async (v: GoldVenueKey) => {
    try {
      const [st, o, c] = await Promise.all([
        fetchGoldStrategies(v),
        fetchGoldPositions(v, "OPEN"),
        fetchGoldPositions(v, "CLOSED"),
      ]);
      setStrats(st.strategies);
      setOpen(o.positions);
      setClosed(c.positions);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load this book.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    loadTab(tab);
    const id = setInterval(() => loadTab(tab), REFRESH_MS);
    return () => clearInterval(id);
  }, [tab, loadTab]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([load(), loadTab(tab)]);
    setRefreshing(false);
  };

  const sum = useMemo(() => venues.find((v) => v.venue === tab) ?? null, [venues, tab]);
  const ccy = sum?.currency ?? "INR";
  const on = sum?.enabled ?? false;

  const act = async (key: string, fn: () => Promise<unknown>, done: (r: never) => string) => {
    setBusy(key);
    setNotice(null);
    try {
      const r = await fn();
      setNotice(done(r as never));
      await Promise.all([load(), loadTab(tab)]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={refreshing}
        crumb="Gold Desk"
        title="Gold Desk"
        subtitle={
          <>
            The whole pattern library — <strong>{sum?.strategy_count ?? 312} strategies</strong>, long and
            short — traded on gold, on two venues that price the same metal differently:{" "}
            <strong>MCX futures</strong> in rupees per 10 grams during Indian hours, and{" "}
            <strong>Delta gold perpetuals</strong> in dollars per ounce around the clock. One shared book per
            venue, so a win funds the next position the way a real account does. Paper only — fills are
            simulated and charged the venue&rsquo;s real costs; no order reaches a broker from this page.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper" tone="accent" />
            {sum?.market_open ? (
              <StatusPill label={tab === "mcx" ? "MCX open" : "24/7"} tone="gain" pulse />
            ) : (
              <StatusPill label="MCX closed" tone="muted" />
            )}
            <button
              className="btn"
              disabled={!!busy}
              onClick={() =>
                act("run", () => runGoldCycle(tab), (r: { opened: number; managed: number; evaluated: number }) =>
                  `Cycle run — ${r.opened} opened, ${r.managed} managed, ${r.evaluated} evaluated.`)
              }
            >
              {busy === "run" ? "Running…" : "Run cycle"}
            </button>
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={handleRefresh} />}
      {notice && (
        <div className="notice" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      {/* ── the two books, side by side in the tab strip so neither is hidden ─────── */}
      <div className="page-tabs">
        {venues.map((v) => (
          <button
            key={v.venue}
            className={tab === v.venue ? "ptab on" : "ptab"}
            onClick={() => setTab(v.venue)}
          >
            <span>{v.label}</span>
            <span className={`tv ${tone(v.total_pnl)}`}>
              {v.closed_positions || v.open_positions ? money(v.total_pnl, v.currency) : "no trades yet"}
            </span>
          </button>
        ))}
        {!venues.length && <div className="ptab muted">loading books…</div>}
      </div>

      {/* ── the basis: the one number neither tab can show on its own ─────────────── */}
      {basis && (basis.mcx || basis.delta) && (
        <GlassPanel
          title="The same ounce, two markets"
          note="compared, never netted — nothing here can trade one against the other"
        >
          <div className="basis">
            {basis.mcx && (
              <div className="bcard">
                <div className="blab">MCX · {basis.mcx.symbol}</div>
                <div className="bval">₹{px(basis.mcx.price)}</div>
                <div className="bsub">{basis.mcx.quote} · ₹{px(basis.mcx.per_oz_inr)} per troy ounce</div>
              </div>
            )}
            {basis.delta &&
              Object.entries(basis.delta.prices).map(([sym, p]) => (
                <div className="bcard" key={sym}>
                  <div className="blab">Delta · {sym}</div>
                  <div className="bval">${px(p)}</div>
                  <div className="bsub">{basis.delta?.quote}</div>
                </div>
              ))}
            {basis.delta && (
              <div className="bcard">
                <div className="blab">Token basis</div>
                <div className="bval">${basis.delta.token_basis_usd.toFixed(2)}</div>
                <div className="bsub">
                  XAUT against PAXG on the same ounce — a real spread, not a data error
                </div>
              </div>
            )}
            {basis.implied?.premium_pct !== undefined && (
              <div className="bcard">
                <div className="blab">MCX premium</div>
                <div className="bval">{pc(basis.implied.premium_pct)}</div>
                <div className="bsub">at ₹{basis.implied.usd_inr_used}/$ · duty and GST live inside it</div>
              </div>
            )}
          </div>
          {basis.implied?.note && <p className="bnote">{basis.implied.note}</p>}
        </GlassPanel>
      )}

      {/* ── the switch ───────────────────────────────────────────────────────────── */}
      <div className={`arm-banner ${on ? "on" : "off"}`}>
        <div>
          <div className="arm-title">
            {(sum?.label ?? "GOLD").toUpperCase()} {on ? "ON" : "OFF"}
          </div>
          <div className="arm-sub">
            {on
              ? `Running — ${plain(sum?.capital, ccy)} book on ${sum?.tradable_symbols?.join(", ") || "—"}, ` +
                `${sum?.max_positions ?? 0} position slots, ${sum?.strategy_count ?? 0} strategies evaluated per symbol.`
              : "Off — no new positions. Open positions are still managed to their target or stop, because " +
                "an open position is exposure whether or not the desk may add to it."}
            {sum?.floor_reached &&
              ` · BOOK FLOOR REACHED: equity is at or below ${plain(sum?.book_floor, ccy)} (${((sum?.book_floor_pct ?? 0) * 100).toFixed(0)}% of capital). No new entries.`}
            {sum?.breaker_tripped && " · Daily loss breaker tripped: no new entries today."}
          </div>
        </div>
        <div className="arm-actions">
          <button
            className="btn danger"
            disabled={!!busy || !open.length}
            onClick={() =>
              act("close", () => closeAllGold(tab), (r: { closed: number; net_pnl: number }) =>
                `Closed ${r.closed} — net ${money(r.net_pnl, ccy)}.`)
            }
          >
            Close all
          </button>
          <button
            className={`switch ${on ? "on" : ""}`}
            disabled={!!busy || !sum}
            onClick={() =>
              act("toggle", () => toggleGoldDesk(tab, !on), () =>
                on ? "Desk switched OFF — open positions still managed." : "Desk switched ON.")
            }
            aria-label="Toggle this gold book"
          >
            <span className="knob" />
            <span className="lbl">{on ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>

      {/* ── realised / unrealised / total, all against the same book ──────────────── */}
      <div className="pnl">
        <div className="card">
          <div className="lab">Realised P&amp;L</div>
          <div className={`val ${tone(sum?.realized_pnl)}`}>{money(sum?.realized_pnl, ccy)}</div>
          <div className={`pct ${tone(sum?.realized_pnl)}`}>{pc(sum?.realized_pct)}</div>
          <div className="sub">
            {sum?.closed_positions ?? 0} closed · after {plain(sum?.total_costs, ccy)} of costs
          </div>
        </div>
        <div className="card">
          <div className="lab">Unrealised P&amp;L</div>
          <div className={`val ${tone(sum?.unrealized_pnl)}`}>{money(sum?.unrealized_pnl, ccy)}</div>
          <div className={`pct ${tone(sum?.unrealized_pnl)}`}>{pc(sum?.unrealized_pct)}</div>
          <div className="sub">{sum?.open_positions ?? 0} open · marked on the live venue price</div>
        </div>
        <div className="card total">
          <div className="lab">Total P&amp;L</div>
          <div className={`val ${tone(sum?.total_pnl)}`}>{money(sum?.total_pnl, ccy)}</div>
          <div className={`pct ${tone(sum?.total_pnl)}`}>{pc(sum?.total_pct)}</div>
          <div className="sub">realised + unrealised, on {plain(sum?.capital, ccy)}</div>
        </div>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="lab">Equity</div>
          <div className="tv">{plain(sum?.equity, ccy)}</div>
          <div className="sub">from {plain(sum?.capital, ccy)}</div>
        </div>
        <div className="tile">
          <div className="lab">Today</div>
          <div className={`tv ${tone(sum?.today_pnl)}`}>{money(sum?.today_pnl, ccy)}</div>
          <div className="sub">
            {pc(sum?.today_pct)} · breaker at −{plain(sum?.daily_loss_limit, ccy)}
          </div>
        </div>
        <div className="tile">
          <div className="lab">Capital committed</div>
          <div className="tv">{plain(sum?.margin_deployed, ccy)}</div>
          <div className="sub">{plain(sum?.available_margin, ccy)} free</div>
        </div>
        <div className="tile">
          <div className="lab">Win rate</div>
          <div className="tv">{(sum?.win_rate ?? 0).toFixed(1)}%</div>
          <div className="sub">over {sum?.closed_positions ?? 0} closed trades</div>
        </div>
        <div className="tile">
          <div className="lab">Book floor</div>
          <div className={`tv ${sum?.floor_reached ? "loss" : ""}`}>{plain(sum?.book_floor, ccy)}</div>
          <div className="sub">entries stop below {((sum?.book_floor_pct ?? 0) * 100).toFixed(0)}% of capital</div>
        </div>
        <div className="tile">
          <div className="lab">Last cycle</div>
          <div className="tv sm">{when(sum?.last_run_at)}</div>
          <div className="sub">
            {sum?.last_opened ?? 0} opened · {sum?.last_managed ?? 0} managed ·{" "}
            {(sum?.last_evaluated ?? 0).toLocaleString("en-IN")} evaluated
          </div>
        </div>
      </div>

      {/* How this book trades, in numbers rather than adjectives. */}
      <GlassPanel title="How this book trades">
        <div className="rules">
          <div className="rule">
            <span className="rk">Instruments</span>
            <span className="rv">
              {sum?.tradable_symbols?.length ? sum.tradable_symbols.join(", ") : "—"}
              {sum?.symbols?.length !== sum?.tradable_symbols?.length && sum?.symbols?.length
                ? ` (of ${sum.symbols.join(", ")})`
                : ""}
            </span>
          </div>
          <div className="rule">
            <span className="rk">Sizing</span>
            <span className="rv">
              Whole {sum?.unit_label ?? "lot"}s only · {sum?.quote_note ?? ""}
            </span>
          </div>
          <div className="rule">
            <span className="rk">Costs</span>
            <span className="rv">{sum?.fee_note ?? "—"}</span>
          </div>
          <div className="rule">
            <span className="rk">Exits</span>
            <span className="rv">
              Target, stop, or {sum?.max_hold_bars ?? 60} bars held — whichever comes first. Fills carry{" "}
              {sum?.slippage_bps ?? 5} bps of slippage each way.
            </span>
          </div>
          <div className="rule">
            <span className="rk">Slots</span>
            <span className="rv">
              {sum?.max_positions ?? 0} concurrent positions against{" "}
              {(sum?.stream_count ?? 0).toLocaleString("en-IN")} strategy/symbol streams. They queue, so the
              fastest timeframes take most of the fills — a property of the clock, not of the edge.
            </span>
          </div>
        </div>
      </GlassPanel>

      {sum?.last_notes?.length ? (
        <GlassPanel title="What the last cycle said" note="the desk's own reasons, not a summary">
          <ul className="notes">
            {sum.last_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </GlassPanel>
      ) : null}

      <GlassPanel
        title="Strategies that have traded in this book"
        note={`${strats.length} of ${(sum?.stream_count ?? 0).toLocaleString("en-IN")} streams have a record`}
      >
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th>Symbol</th>
                <th>TF</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>PF</th>
                <th>Expectancy</th>
                <th>Costs</th>
                <th>Realised</th>
                <th>Open</th>
                <th>Max DD</th>
                <th className="l">Worth real money?</th>
              </tr>
            </thead>
            <tbody>
              {strats.map((s) => (
                <tr key={`${s.symbol}-${s.template}-${s.timeframe}`}>
                  <td className="l strong">{s.name}</td>
                  <td>{s.symbol}</td>
                  <td>{s.timeframe}</td>
                  <td>{s.trades}</td>
                  <td>{s.trades ? s.win_rate.toFixed(1) : "—"}</td>
                  <td>{s.profit_factor === null ? "—" : s.profit_factor.toFixed(2)}</td>
                  <td className={tone(s.expectancy)}>{money(s.expectancy, ccy)}</td>
                  <td className="muted">{plain(s.total_costs, ccy)}</td>
                  <td className={`strong ${tone(s.realized_pnl)}`}>{money(s.realized_pnl, ccy)}</td>
                  <td className={tone(s.unrealized_pnl)}>
                    {s.open_positions ? money(s.unrealized_pnl, ccy) : "—"}
                  </td>
                  <td>{s.max_drawdown_pct.toFixed(2)}%</td>
                  <td className="l">
                    <span className={`verdict ${s.verdict.toLowerCase()}`}>{s.verdict}</span>
                    {s.verdict_reasons?.[0] && <span className="why"> {s.verdict_reasons[0]}</span>}
                  </td>
                </tr>
              ))}
              {!strats.length && (
                <tr>
                  <td className="l empty" colSpan={12}>
                    No strategy has traded in this book yet. A record appears here the first time one of the{" "}
                    {(sum?.stream_count ?? 0).toLocaleString("en-IN")} streams fills — and unlike the desk this
                    was ported from, a record cannot disappear afterwards: it is the positions in the database,
                    not a list held in memory.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Open positions" note={`${open.length} of ${sum?.max_positions ?? 0} slots in use`}>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>{sum?.unit_label === "contract" ? "Contracts" : "Lots"}</th>
                <th>Entry</th>
                <th>Mark</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Notional</th>
                <th>Unrealised</th>
                <th>Held</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={p.position_id}>
                  <td className="l strong">{p.strategy_name}</td>
                  <td>{p.symbol}</td>
                  <td>
                    <span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span>
                  </td>
                  <td>{p.units}</td>
                  <td>{px(p.entry_price)}</td>
                  <td>{px(p.ltp)}</td>
                  <td>{px(p.stoploss)}</td>
                  <td>{px(p.target)}</td>
                  <td className="muted">{plain(p.notional, ccy)}</td>
                  <td className={`strong ${tone(p.unrealized_pnl)}`}>{money(p.unrealized_pnl, ccy)}</td>
                  <td>
                    {p.bars_held}/{p.max_hold_bars}
                  </td>
                  <td className="muted">{when(p.opened_at)}</td>
                </tr>
              ))}
              {!open.length && (
                <tr>
                  <td className="l empty" colSpan={12}>
                    Nothing open. Every position here is opened by a pattern signal and closed by its own
                    target, stop or hold limit — never by hand.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Closed trades" note={`${closed.length} shown, newest first`}>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Why</th>
                <th>Costs</th>
                <th>Net</th>
                <th>On margin</th>
                <th>Closed</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((p) => (
                <tr key={p.position_id}>
                  <td className="l strong">{p.strategy_name}</td>
                  <td>{p.symbol}</td>
                  <td>
                    <span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span>
                  </td>
                  <td>{px(p.entry_price)}</td>
                  <td>{px(p.exit_price)}</td>
                  <td>
                    <span className={`why-chip ${p.exit_reason === "target" ? "good" : p.exit_reason === "stoploss" ? "bad" : ""}`}>
                      {p.exit_reason ?? "—"}
                    </span>
                  </td>
                  <td className="muted">{plain(p.costs, ccy)}</td>
                  <td className={`strong ${tone(p.realized_pnl)}`}>{money(p.realized_pnl, ccy)}</td>
                  <td className={tone(p.return_on_margin_pct)}>{pc(p.return_on_margin_pct)}</td>
                  <td className="muted">{when(p.closed_at)}</td>
                </tr>
              ))}
              {!closed.length && (
                <tr>
                  <td className="l empty" colSpan={10}>
                    No closed trades in this book yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <DeskHistory deskKey="gold-desk" scope={tab} title={`${sum?.label ?? "Gold"} — history`} />

      <style jsx>{`
        .page { padding: 28px 32px 56px; display: flex; flex-direction: column; gap: 18px; }
        .notice { background: var(--purple-dim); border: 1px solid rgba(125, 52, 220, 0.3);
                  color: var(--purple); border-radius: 10px; padding: 10px 14px; font-size: 12.5px;
                  cursor: pointer; }

        .page-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
        .ptab { display: flex; flex-direction: column; align-items: flex-start; gap: 3px;
                background: var(--canvas-soft); border: 1px solid var(--panel-border);
                color: var(--text-muted); border-radius: 10px; padding: 9px 16px;
                font-size: 12.5px; font-weight: 700; cursor: pointer; }
        .ptab.on { background: var(--purple-dim); border-color: rgba(125, 52, 220, 0.3); color: var(--purple); }
        .ptab.muted { cursor: default; font-weight: 500; }
        .ptab .tv { font-family: var(--font-data); font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums; opacity: 0.9; }

        .basis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .bcard { background: var(--canvas-soft); border: 1px solid var(--panel-border);
                 border-radius: 10px; padding: 12px 14px; }
        .blab { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
                color: var(--text-faint); }
        .bval { margin-top: 6px; font-family: var(--font-data); font-size: 19px; font-weight: 700;
                font-variant-numeric: tabular-nums; }
        .bsub { margin-top: 4px; font-size: 11.5px; color: var(--text-muted); }
        .bnote { margin: 12px 2px 0; font-size: 12px; color: var(--text-muted); }

        .arm-banner { display: flex; justify-content: space-between; align-items: center; gap: 16px;
                      flex-wrap: wrap; border-radius: 14px; padding: 16px 20px;
                      border: 1px solid var(--panel-border); background: var(--canvas-soft); }
        .arm-banner.on { border-color: rgba(14, 159, 110, 0.3); background: var(--gain-dim); }
        .arm-title { font-family: var(--font-display); font-weight: 800; font-size: 14px;
                     letter-spacing: 0.04em; }
        .arm-sub { margin-top: 5px; font-size: 12.5px; color: var(--text-muted); max-width: 860px; }
        .arm-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

        .btn { background: var(--canvas-soft); border: 1px solid var(--panel-border);
               color: var(--text-muted); border-radius: 9px; padding: 8px 14px; font-size: 12.5px;
               font-weight: 600; cursor: pointer; }
        .btn:hover:not(:disabled) { color: var(--purple); border-color: rgba(125, 52, 220, 0.3); }
        .btn:disabled { opacity: 0.55; cursor: default; }
        .btn.danger:hover:not(:disabled) { color: var(--loss); border-color: rgba(217, 45, 63, 0.3); }

        .switch { position: relative; width: 74px; height: 32px; border-radius: 100px;
                  border: 1px solid var(--panel-border); background: var(--canvas-soft);
                  cursor: pointer; display: flex; align-items: center; }
        .switch.on { background: var(--gain-dim); border-color: rgba(14, 159, 110, 0.35); }
        .switch:disabled { opacity: 0.55; cursor: default; }
        .knob { position: absolute; left: 3px; width: 24px; height: 24px; border-radius: 50%;
                background: var(--text-faint); transition: transform 0.16s ease, background 0.16s ease; }
        .switch.on .knob { transform: translateX(42px); background: var(--gain); }
        .lbl { position: absolute; right: 10px; font-size: 10.5px; font-weight: 800;
               letter-spacing: 0.06em; color: var(--text-faint); }
        .switch.on .lbl { right: auto; left: 12px; color: var(--gain); }

        .pnl { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
        .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
                padding: 16px 18px; }
        .card.total { border-color: rgba(125, 52, 220, 0.25); background: var(--purple-dim); }
        .lab { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
               color: var(--text-faint); }
        .val { margin-top: 8px; font-family: var(--font-data); font-size: 23px; font-weight: 700;
               font-variant-numeric: tabular-nums; }
        .pct { margin-top: 2px; font-family: var(--font-data); font-size: 12.5px; font-weight: 600; }
        .sub { margin-top: 6px; font-size: 11.5px; color: var(--text-muted); }

        .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
        .tile { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px;
                padding: 13px 15px; }
        .tv { margin-top: 7px; font-family: var(--font-data); font-size: 17px; font-weight: 700;
              font-variant-numeric: tabular-nums; }
        .tv.sm { font-size: 12.5px; font-weight: 600; }

        .rules { display: flex; flex-direction: column; gap: 9px; }
        .rule { display: grid; grid-template-columns: 140px 1fr; gap: 12px; align-items: baseline; }
        .rk { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
              color: var(--text-faint); }
        .rv { font-size: 12.5px; color: var(--text-muted); }

        .notes { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
        .notes :global(li) { font-size: 12.5px; color: var(--text-muted); }

        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px;
                      font-variant-numeric: tabular-nums; white-space: nowrap; }
        .data-table th { text-align: center; padding: 9px 10px; font-size: 10px; font-weight: 700;
                         letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-faint);
                         border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 9px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .data-table th.l, .data-table td.l { text-align: left; }
        .strong { font-weight: 700; }
        .muted { color: var(--text-muted); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .empty { color: var(--text-muted); white-space: normal; padding: 16px 10px; max-width: 760px; }

        .side { font-size: 10.5px; font-weight: 800; letter-spacing: 0.05em; padding: 3px 8px;
                border-radius: 100px; }
        .side.buy { color: var(--gain); background: var(--gain-dim); }
        .side.sell { color: var(--loss); background: var(--loss-dim); }
        .why-chip { font-size: 10.5px; font-weight: 700; padding: 3px 8px; border-radius: 100px;
                    background: var(--canvas-soft); color: var(--text-muted); }
        .why-chip.good { color: var(--gain); background: var(--gain-dim); }
        .why-chip.bad { color: var(--loss); background: var(--loss-dim); }
        .verdict { font-size: 10.5px; font-weight: 800; letter-spacing: 0.04em; padding: 3px 8px;
                   border-radius: 100px; background: var(--canvas-soft); color: var(--text-muted); }
        .verdict.pass { color: var(--gain); background: var(--gain-dim); }
        .verdict.fail { color: var(--loss); background: var(--loss-dim); }
        .verdict.pending { color: var(--warn); background: var(--warn-dim); }
        .why { margin-left: 8px; font-size: 11.5px; color: var(--text-muted); white-space: normal; }
      `}</style>
    </div>
  );
}
