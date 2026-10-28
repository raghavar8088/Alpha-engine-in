"use client";

/** Gold Desk — gold on two venues, rebuilt on its research (October 2026).
 *
 * The research (GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md) replayed all 353 pattern strategies on six
 * gold histories with honest fills and measured costs: below 4h none earned its fees, at 1d 39 of
 * 40 lost to simply holding gold, and run with its old rules each book hit its 50% floor within
 * weeks. So the desk now runs only what the evidence allows:
 *
 *   Delta — H1, a pre-registered two-year forward test of the nine 4h breakout / trend templates
 *           on XAUTUSD, each in its own sleeve. Its verdict comes from its stored rule, not this page.
 *   MCX   — off: every strategy was retired. Its machinery (own-contract pricing, roll exits,
 *           touch fills, exposure caps) is fixed, so a record would be honest if it ever ran.
 *
 * Paper only. No order reaches a broker or an exchange from this page.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import FactoryDeskView from "../../components/FactoryDeskView";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import DeskHistory from "../../components/DeskHistory";
import GoldH1Panel from "./GoldH1Panel";
import GoldCostsPanel from "./GoldCostsPanel";
import GoldLabPanel from "./GoldLabPanel";
import { RankNote, RankTd, RankTh, sortByRank, useStrategyRanks } from "../../components/StrategyRank";
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
  fetchGoldLab,
  GoldLabSummary,
  runGoldCycle,
  toggleGoldDesk,
} from "../../lib/api";

const REFRESH_MS = 20000;
const VENUE_ORDER: GoldVenueKey[] = ["delta", "mcx"];

/** Money in the book's OWN currency — the two tabs are never added together. */
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
const bpx = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)} bp`;
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
/** Gold quotes at ~4,190 on one venue and ~1,50,000 on the other — precision by magnitude. */
const px = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0
    ? "—"
    : v >= 10000
      ? v.toLocaleString("en-IN", { maximumFractionDigits: 0 })
      : v.toFixed(2);
const when = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
const basisLabel = (b: string | null | undefined) =>
  !b
    ? "—"
    : ({
        touch: "at the touch",
        book_walk: "book walked",
        minute_level: "at its level",
        minute_gap_open: "gap — at the open",
        minute_close: "hold limit — minute close",
        quote_fallback: "live quote (store stale)",
        contract_last_bar: "contract's last print",
        last_mark: "last mark",
      } as Record<string, string>)[b] ?? b;

export default function GoldDeskPage() {
  const [tab, setTab] = useState<GoldVenueKey>("delta");
  const [lab, setLab] = useState(false);                  // the Gold Lab tab (not a venue of the desk engine)
  // The Strategy Factory tab (2026-10-27): its 546 strategies as records on Delta XAUTUSD, beside H1.
  const [fac, setFac] = useState(false);
  const [labSum, setLabSum] = useState<GoldLabSummary | null>(null);
  const [venues, setVenues] = useState<GoldSummary[]>([]);
  const [strats, setStrats] = useState<GoldStrategy[]>([]);
  const ranks = useStrategyRanks(lab ? null : "gold", { venue: tab });
  const rankId = (s: GoldStrategy) => `${s.symbol}-${s.template}-${s.timeframe}`;
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
      fetchGoldLab().then(setLabSum).catch(() => setLabSum(null));
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
    if (lab) return;                                       // the lab panel loads its own data
    loadTab(tab);
    const id = setInterval(() => loadTab(tab), REFRESH_MS);
    return () => clearInterval(id);
  }, [tab, loadTab, lab]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([load(), loadTab(tab)]);
    setRefreshing(false);
  };

  const ordered = useMemo(
    () => VENUE_ORDER.map((k) => venues.find((v) => v.venue === k)).filter(Boolean) as GoldSummary[],
    [venues],
  );
  const sum = useMemo(() => venues.find((v) => v.venue === tab) ?? null, [venues, tab]);
  const ccy = sum?.currency ?? "USD";
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
            Gold on two venues, rebuilt on its research. All 353 pattern strategies were replayed on six gold
            histories with honest fills and measured costs: <strong>none earned its costs below 4h</strong>, and at
            1d <strong>39 of 40 lost to simply holding gold</strong>. Delta now runs <strong>H1</strong> — one
            pre-registered forward test of the nine 4h breakout / trend strategies on XAUTUSD; MCX is off. The{" "}
            <strong>Gold Lab</strong> tab runs the seven daily strategies a second, 157-variant search left standing.
            Paper only — no order reaches a broker from this page.
          </>
        }
        actions={
          <>
            <StatusPill label="Paper" tone="accent" />
            {lab ? null : sum?.market_open ? (
              <StatusPill label={tab === "mcx" ? "MCX open" : "24/7"} tone="gain" pulse />
            ) : (
              <StatusPill label="MCX closed" tone="muted" />
            )}
            {lab ? null : (
              <button
                className="btn"
                disabled={!!busy || !sum?.can_enable}
                title={sum?.can_enable ? "Manage open positions and scan the latest closed bars now" : sum?.why_off ?? ""}
                onClick={() =>
                  act("run", () => runGoldCycle(tab), (r: { opened: number; managed: number; evaluated: number }) =>
                    `Cycle run — ${r.opened} opened, ${r.managed} managed, ${r.evaluated} evaluated.`)
                }
              >
                {busy === "run" ? "Running…" : "Run cycle"}
              </button>
            )}
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={handleRefresh} />}
      {notice && (
        <div className="notice" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      {/* ── the two books ───────────────────────────────────────────────────────── */}
      <div className="page-tabs">
        {ordered.map((v) => (
          <button
            key={v.venue}
            className={!lab && !fac && tab === v.venue ? "ptab on" : "ptab"}
            onClick={() => {
              setLab(false);
              setFac(false);
              setTab(v.venue);
            }}
          >
            <span>{v.label}</span>
            <span className={`tv ${tone(v.total_pnl)}`}>
              {!v.can_enable
                ? "off — nothing earned its costs"
                : v.closed_positions || v.open_positions
                  ? money(v.total_pnl, v.currency)
                  : v.enabled
                    ? "running · no trades yet"
                    : "off"}
            </span>
          </button>
        ))}
        {!ordered.length && <div className="ptab muted">loading books…</div>}
        <button className={lab && !fac ? "ptab on" : "ptab"} onClick={() => { setFac(false); setLab(true); }}>
          <span>Gold Lab · 7 tested strategies</span>
          <span className={`tv ${tone(labSum?.net_pnl)}`}>
            {!labSum
              ? "—"
              : labSum.strategies.some((x) => x.fills > 0)
                ? money(labSum.net_pnl, "USD")
                : labSum.enabled
                  ? "running · first decision after a NY close"
                  : "off"}
          </span>
        </button>
        <button className={fac ? "ptab on" : "ptab"} onClick={() => { setLab(false); setFac(true); }}>
          <span>Strategy Factory · 546</span>
          <span className="tv">records beside H1 · Delta XAUTUSD</span>
        </button>
      </div>

      {fac ? (
        <FactoryDeskView desk="gold" />
      ) : lab ? (
        <GlassPanel title="Gold Lab — seven tested strategies" note="Tier B: profitable in every test period, not proven better than holding gold">
          <GoldLabPanel />
        </GlassPanel>
      ) : (
      <>
      {tab === "delta" && (
        <GlassPanel title="H1 — the pre-registered forward test" note="judged only by its stored rule">
          <GoldH1Panel />
        </GlassPanel>
      )}

      {tab === "mcx" && sum && !sum.can_enable && (
        <div className="retired">
          <div className="arm-title">MCX GOLD — OFF</div>
          <p>
            {sum.why_off} Replayed on MCX GOLDM and on COMEX gold in MCX hours, every timeframe below 4h lost after
            Angel&rsquo;s charges (₹305 a GOLDM round trip) and the measured spread; the daily patterns lost to holding
            gold; and run with its old rules the ₹30 lakh book hit its 50% floor — over May 2024 – Oct 2026 it lost
            52% while gold rose 78%. The machinery behind this tab is fixed — positions priced on their own contract,
            forced out before delivery, filled at the bid / ask, exits walked minute by minute, net exposure capped —
            so any record it ever produces would be honest. It trades nothing until a strategy earns it through the
            Commodity Lab.
          </p>
        </div>
      )}

      {/* ── the basis: the one number neither tab can show on its own ─────────────── */}
      {basis && (basis.mcx || basis.delta) && (
        <GlassPanel title="The same ounce, two markets" note="compared, never netted">
          <div className="basis">
            {basis.mcx && (
              <div className="bcard">
                <div className="blab">MCX · {basis.mcx.symbol}</div>
                <div className="bval">₹{px(basis.mcx.price)}</div>
                <div className="bsub">
                  {basis.mcx.quote} · ₹{px(basis.mcx.per_oz_inr)} per troy ounce
                  {basis.mcx.fresh === false ? " · last trade (market quiet)" : ""}
                </div>
              </div>
            )}
            {basis.delta &&
              Object.entries(basis.delta.prices).map(([sym, p]) => (
                <div className="bcard" key={sym}>
                  <div className="blab">
                    Delta · {sym}
                    {sym === "XAUTUSD" ? " · traded" : " · shown for the basis"}
                  </div>
                  <div className="bval">${px(p)}</div>
                  <div className="bsub">{basis.delta?.quote}</div>
                </div>
              ))}
            {basis.delta && (
              <div className="bcard">
                <div className="blab">Token basis</div>
                <div className="bval">${basis.delta.token_basis_usd.toFixed(2)}</div>
                <div className="bsub">XAUT against PAXG on the same ounce — a real spread, not a data error</div>
              </div>
            )}
            {basis.implied?.premium_pct !== undefined && (
              <div className="bcard">
                <div className="blab">MCX premium</div>
                <div className="bval">{pc(basis.implied.premium_pct)}</div>
                <div className="bsub">
                  at ₹{basis.implied.usd_inr_used?.toFixed(2)}/$ (live) · import duty and the local premium live inside it
                </div>
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
            {!sum?.can_enable
              ? "Nothing to switch on: the research retired every strategy on this venue."
              : on
                ? `Running — ${plain(sum?.capital, ccy)} on ${sum?.symbols?.join(", ") || "—"}, ` +
                  `${sum?.strategy_count ?? 0} strategies, ${sum?.mode === "record" ? "one sleeve each" : `${sum?.max_positions ?? 0} slots`}.`
                : "Off — no new positions. Open positions are still managed to their target, stop or hold limit."}
            {sum?.floor_reached &&
              ` · BOOK FLOOR REACHED: equity is at or below ${plain(sum?.book_floor, ccy)}. No new entries.`}
            {sum?.breaker_tripped && " · Daily loss breaker tripped: no new entries today."}
          </div>
        </div>
        <div className="arm-actions">
          <button
            className="btn danger"
            disabled={!!busy || !open.length}
            onClick={() =>
              act("close", () => closeAllGold(tab), (r: { closed: number; net_pnl: number; left_open_no_live_price?: string[] }) =>
                `Closed ${r.closed} at the market — net ${money(r.net_pnl, ccy)}` +
                (r.left_open_no_live_price?.length ? `; ${r.left_open_no_live_price.length} left open (no live price).` : "."))
            }
          >
            Close all
          </button>
          <button
            className={`switch ${on ? "on" : ""}`}
            disabled={!!busy || !sum || (!on && !sum.can_enable)}
            title={!sum?.can_enable ? sum?.why_off ?? "" : ""}
            onClick={() =>
              act("toggle", () => toggleGoldDesk(tab, !on), () =>
                on ? "Switched OFF — open positions still managed." : "Switched ON.")
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
            {sum?.funding ? ` (incl. ${money(sum?.funding_paid, ccy)} funding)` : ""}
          </div>
        </div>
        <div className="card">
          <div className="lab">Unrealised P&amp;L</div>
          <div className={`val ${tone(sum?.unrealized_pnl)}`}>{money(sum?.unrealized_pnl, ccy)}</div>
          <div className={`pct ${tone(sum?.unrealized_pnl)}`}>{pc(sum?.unrealized_pct)}</div>
          <div className="sub">{sum?.open_positions ?? 0} open · at the mark, after the fees to close</div>
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
            {pc(sum?.today_pct)}
            {sum?.daily_loss_limit ? ` · breaker at −${plain(sum.daily_loss_limit, ccy)}` : " · no daily breaker (record mode)"}
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
          <div className="sub">a ruin guard: entries stop below {((sum?.book_floor_pct ?? 0) * 100).toFixed(0)}%</div>
        </div>
        <div className="tile">
          <div className="lab">Last cycle</div>
          <div className="tv sm">{when(sum?.last_run_at)}</div>
          <div className="sub">
            {sum?.last_opened ?? 0} opened · {sum?.last_managed ?? 0} managed · {sum?.last_evaluated ?? 0} evaluated
          </div>
        </div>
      </div>

      <GlassPanel title="How this book trades">
        <div className="rules">
          <div className="rule">
            <span className="rk">Instrument</span>
            <span className="rv">
              {sum?.symbols?.join(", ") || "—"} · {sum?.quote_note ?? ""}
            </span>
          </div>
          <div className="rule">
            <span className="rk">Strategies</span>
            <span className="rv">
              {sum?.strategies_enabled?.length
                ? sum.strategies_enabled.join(" · ")
                : "none — every strategy on this venue was retired by the research"}
            </span>
          </div>
          <div className="rule">
            <span className="rk">Signals</span>
            <span className="rv">
              Evaluated once on each newly CLOSED bar, and only after the store has re-read it since its close — never
              on the bar still forming, nor on one stored while it was.
              {sum?.max_entry_lag_s
                ? ` A bar first seen more than ${Math.round(sum.max_entry_lag_s / 60)} minutes after its close is skipped, never traded late.`
                : " No decision on a bar that closed more than a bar ago."}
            </span>
          </div>
          <div className="rule">
            <span className="rk">Exits</span>
            <span className="rv">
              Target, stop or the close of the {sum?.max_hold_bars ?? 60}th bar after the signal — walked over final
              one-minute bars: a level fills at the level, a minute opening past it at that open, a minute touching both
              is a stop.{sum?.funding ? " Funding is paid at every exchange the position is open across." : ""}
            </span>
          </div>
          <div className="rule">
            <span className="rk">Costs</span>
            <span className="rv">{sum?.fee_note ?? "—"}</span>
          </div>
          <div className="rule">
            <span className="rk">Retired</span>
            <span className="rv">
              Every timeframe below 4h ({sum?.retired_timeframes?.join(", ") ?? "—"}): none earned its fees on any history.
            </span>
          </div>
        </div>
      </GlassPanel>

      <GlassPanel title="What trading here costs" note="measured, not assumed">
        <GoldCostsPanel />
      </GlassPanel>

      {sum?.last_notes?.length ? (
        <GlassPanel title="What the last cycle said" note="the desk's own reasons">
          <ul className="notes">
            {sum.last_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </GlassPanel>
      ) : null}

      <GlassPanel title="Strategy records" note="a record states what happened — it is never a promotion">
        {ranks && <RankNote board={ranks} />}
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {ranks && <RankTh />}
                <th className="l">Strategy</th>
                <th>TF</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>Net / trade</th>
                <th>t</th>
                <th>PF</th>
                <th>Costs</th>
                <th>Realised</th>
                <th>Open</th>
                <th className="l">Record</th>
              </tr>
            </thead>
            <tbody>
              {sortByRank(strats, ranks, rankId).map((s) => (
                <tr key={`${s.symbol}-${s.template}-${s.timeframe}`}>
                  {ranks && <RankTd board={ranks} id={rankId(s)} />}
                  <td className="l strong">
                    {s.name}
                    {s.h1 && <span className="h1tag">H1</span>}
                  </td>
                  <td>{s.timeframe}</td>
                  <td>{s.trades}</td>
                  <td>{s.trades ? s.win_rate.toFixed(1) : "—"}</td>
                  <td className={tone(s.net_bp_mean)}>{bpx(s.net_bp_mean)}</td>
                  <td>{s.net_bp_t === null || s.net_bp_t === undefined ? "—" : s.net_bp_t.toFixed(2)}</td>
                  <td>{s.profit_factor === null ? "—" : s.profit_factor.toFixed(2)}</td>
                  <td className="muted">{plain(s.total_costs, ccy)}</td>
                  <td className={`strong ${tone(s.realized_pnl)}`}>{money(s.realized_pnl, ccy)}</td>
                  <td className={tone(s.unrealized_pnl)}>{s.open_positions ? money(s.unrealized_pnl, ccy) : "—"}</td>
                  <td className="l">
                    <span className="verdict record">{s.verdict}</span>
                    {s.verdict_reasons?.[0] && <span className="why"> {s.verdict_reasons[0]}</span>}
                  </td>
                </tr>
              ))}
              {!strats.length && (
                <tr>
                  <td className="l empty" colSpan={11}>
                    No strategy is enabled on this venue, and none has a record here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </GlassPanel>

      <GlassPanel title="Open positions" note={`${open.length} open`}>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th className="l">Strategy</th>
                <th>Side</th>
                <th>{sum?.unit_label === "contract" ? "Contracts" : "Lots"}</th>
                <th>Entry</th>
                <th>Filled</th>
                <th>Mark</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Notional</th>
                {sum?.funding ? <th>Funding</th> : null}
                <th>Unrealised</th>
                <th>Hold until</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={p.position_id}>
                  <td className="l strong">
                    {p.strategy_name}
                    {p.h1 && <span className="h1tag">H1</span>}
                  </td>
                  <td>
                    <span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span>
                  </td>
                  <td>{p.units}</td>
                  <td>{px(p.entry_price)}</td>
                  <td className="muted">
                    {basisLabel(p.entry_basis)}
                    {p.entry_spread_bp !== undefined && p.entry_spread_bp !== null ? ` · ${p.entry_spread_bp.toFixed(2)} bp spread` : ""}
                  </td>
                  <td>
                    {px(p.ltp)}
                    {p.store_stale ? <span className="warn"> · bars stale</span> : null}
                    {p.quote_status && p.quote_status !== "live" ? <span className="warn"> · {p.quote_status}</span> : null}
                  </td>
                  <td>{px(p.stoploss)}</td>
                  <td>{px(p.target)}</td>
                  <td className="muted">{plain(p.notional, ccy)}</td>
                  {sum?.funding ? <td className={tone(-(p.funding_paid ?? 0))}>{money(-(p.funding_paid ?? 0), ccy)}</td> : null}
                  <td className={`strong ${tone(p.unrealized_pnl)}`}>{money(p.unrealized_pnl, ccy)}</td>
                  <td className="muted">{p.hold_until ? when(p.hold_until) : `${p.bars_held}/${p.max_hold_bars} bars`}</td>
                </tr>
              ))}
              {!open.length && (
                <tr>
                  <td className="l empty" colSpan={12}>
                    Nothing open. Every position is opened by a signal on a closed bar and closed by its own target, stop or
                    hold limit — never by hand.
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
                <th>Side</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Why</th>
                <th>Filled</th>
                <th>Costs</th>
                <th>Net</th>
                <th>Net / notional</th>
                <th>Closed</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((p) => (
                <tr key={p.position_id}>
                  <td className="l strong">
                    {p.strategy_name}
                    {p.h1 && <span className="h1tag">H1</span>}
                  </td>
                  <td>
                    <span className={p.side === "BUY" ? "side buy" : "side sell"}>{p.side}</span>
                  </td>
                  <td>{px(p.entry_price)}</td>
                  <td>{px(p.exit_price)}</td>
                  <td>
                    <span
                      className={`why-chip ${p.exit_reason === "target" ? "good" : p.exit_reason === "stoploss" ? "bad" : ""}`}
                    >
                      {p.exit_reason ?? "—"}
                    </span>
                  </td>
                  <td className="muted">{basisLabel(p.exit_basis)}</td>
                  <td className="muted">
                    {plain(p.costs, ccy)}
                    {p.funding_paid ? ` · funding ${money(-p.funding_paid, ccy)}` : ""}
                  </td>
                  <td className={`strong ${tone(p.realized_pnl)}`}>{money(p.realized_pnl, ccy)}</td>
                  <td className={tone(p.net_bp)}>{bpx(p.net_bp)}</td>
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
      </>
      )}

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

        .retired { border-radius: 14px; padding: 16px 20px; border: 1px solid var(--panel-border);
                   background: var(--canvas-soft); }
        .retired p { margin: 6px 0 0; font-size: 12.5px; line-height: 1.6; color: var(--text-muted); max-width: 980px; }

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
        .warn { color: var(--warn); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
        .empty { color: var(--text-muted); white-space: normal; padding: 16px 10px; max-width: 760px; }

        .h1tag { margin-left: 6px; font-size: 9.5px; font-weight: 800; letter-spacing: 0.05em; padding: 1px 6px;
                 border-radius: 100px; color: var(--warn); background: var(--warn-dim); }
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
        .verdict.record { color: var(--text-muted); border: 1px solid var(--panel-border); }
        .why { margin-left: 8px; font-size: 11.5px; color: var(--text-muted); white-space: normal; }
      `}</style>
    </div>
  );
}
