"use client";

// The Gold Desk's Top-5 paper books (2026-11-12): three paper accounts on the five best-ranked strategies of the
// desk's Delta board (H1's 4h templates on XAUTUSD) - one Rs 2 lakh account the five share, one Rs 10 lakh account
// the five share, and five Rs 10 lakh accounts, one per strategy. They copy the desk's own trades at their own size
// (backend app/services/gold_top5_books.py). Paper only: nothing here can place an order.
// 18 Nov 2026: that day's top 5 (Keltner Breakout in for HH/HL Structure Shift), each on its own ₹2 lakh and its own
// ₹10 lakh account (own2L_n / own10L_n) - a second section below the 12 Nov accounts, which keep their five.
// 19 Nov 2026: all nine H1 strategies on twenty more accounts - a ₹2 lakh and a ₹10 lakh account the nine share
// (h1_2L / h1_10L) and each of the nine on its own ₹2 lakh and ₹10 lakh (h1own2L_n / h1own10L_n). They are the
// same engine's books, so this panel shows them as a second view (view="h1"), on its own tab of the page.
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { DAY_COL_TITLES, dayCell, istDaysSince, pctCell, perDayTraded, toneOf } from "../../lib/dayReturns";

type Pick = { n: number; key: string; template: string; timeframe: string; name: string; score: number; trades: number;
  bp: number; net_usd: number; t: number };
type StratRow = { key: string; name: string; trades: number; wins: number; net: number; open: number; unrealized: number;
  days_traded?: number };
type Money = { capital: number; equity: number; realized_pnl: number; unrealized_pnl: number; deployed: number;
  available_cash: number; fees: number; gross_pnl: number; open_positions: number; closed_positions: number; wins: number;
  win_rate: number | null; roi_pct: number };
type Book = Money & { id: string;
  group: "2L" | "10L" | "each10L" | "own2L" | "own10L" | "h1_2L" | "h1_10L" | "h1own2L" | "h1own10L"; label: string; roster: string[];
  max_open: number; position_cap: number | null; compound: boolean; skipped: Record<string, number>; voided: number;
  started_at: string | null; strategies: StratRow[];
  /** The IST days a copy closed on (18 Nov 2026; absent on a server not yet updated). */
  days_traded?: number };

/** The four trading-day cells of one account (18 Nov 2026): days traded, days since it started, its total return
 *  (realised + open on its own capital) and that return per day traded. Rendered inline by each table. */
function dayFigures(b: Book | undefined) {
  const ret = b ? b.roi_pct : null;
  const days = b?.days_traded ?? null;
  return { days, total: istDaysSince(b?.started_at), ret, avg: perDayTraded(ret, days) };
}
type Total = Money & { accounts: number };
export type Overview = { mode: string; enabled: boolean; tick_seconds: number; picked_at: string; board: string; instrument: string;
  picks: Pick[]; groups: { group: string; label: string; about: string }[]; books: Book[]; each_total: Total;
  usd_inr: { rate: number | null; asof: string | null; at: string | null } | null; notes: string[];
  // 18 Nov 2026 (absent on a server not yet updated): that day's top 5, each on its own ₹2 lakh and ₹10 lakh
  picks_1811?: Pick[]; picked_at_1811?: string; board_1811?: string; group_totals?: Record<string, Total>;
  // 19 Nov 2026 (absent on a server not yet updated): all nine H1 strategies, shared and each on its own
  picks_h1?: Pick[]; picked_at_h1?: string; board_h1?: string; h1_groups?: string[]; notes_h1?: string[] };
export type View = "top5" | "h1";
export type Copy = { position_id: string; book: string; key: string; strategy_name: string; side: "BUY" | "SELL"; qty: number;
  ounces: number; entry_px: number; exit_px: number | null; ltp: number | null; usd_inr: number | null;
  capital_deployed: number; unrealized_pnl: number; realized_pnl: number | null; gross_pnl: number | null;
  fees: number | null; exit_reason: string | null; status: string; opened_at: string; closed_at: string | null };

const inr = (v: number | null | undefined, signed = false) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const d = a < 100 ? 2 : 0;
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return `${sign}₹${a.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
};
const usd = (v: number | null | undefined) =>
  v === null || v === undefined ? "—"
    : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`;
const tone = (v: number | null | undefined) => (!v ? "" : v > 0 ? "gain" : "loss");
const ist = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: false });
const WHY: Record<string, string> = { target: "Target", stop: "Stop", time: "Hold limit", void: "Void (no price)" };
const SHORT = (name: string) => name.split(" · ")[0];

function Card({ title, sub, m, on, onClick }: { title: string; sub: string; m: Money | undefined; on: boolean; onClick: () => void }) {
  return (
    <button className={`t5-card${on ? " on" : ""}`} onClick={onClick} aria-pressed={on}>
      <span className="t5-k">{title}</span>
      <span className="t5-v">{m ? inr(m.equity) : "—"}</span>
      <span className={`t5-r ${tone(m?.roi_pct)}`}>{m ? `${pct(m.roi_pct)} on ${inr(m.capital)}` : ""}</span>
      <span className="t5-s">
        {m ? `realised ${inr(m.realized_pnl, true)} · open ${inr(m.unrealized_pnl, true)}` : ""}
      </span>
      <span className="t5-s">
        {m ? `${m.closed_positions} trades${m.win_rate === null ? "" : ` · ${m.win_rate.toFixed(0)}% won`} · ${m.open_positions} open · costs ${inr(m.fees)}` : ""}
      </span>
      <span className="t5-about">{sub}</span>
    </button>
  );
}

export default function GoldTop5Panel({ view = "top5" }: { view?: View }) {
  const [ov, setOv] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState(view === "h1" ? "h1_2L" : "top5_2L");
  const what = view === "h1" ? "the H1-nine accounts" : "the Top-5 books";
  const [open, setOpen] = useState<Copy[]>([]);
  const [closed, setClosed] = useState<Copy[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOv(await apiFetch("/api/gold-desk/top5"));
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : `Could not read ${what}.`);
    }
  }, [what]);
  const loadBook = useCallback(async (id: string) => {
    try {
      const q = `book=${encodeURIComponent(id)}`;
      const [o, c] = await Promise.all([
        apiFetch(`/api/gold-desk/top5/positions?${q}&status=OPEN`),
        apiFetch(`/api/gold-desk/top5/positions?${q}&status=CLOSED&limit=200`),
      ]);
      setOpen(o.positions ?? []);
      setClosed(c.positions ?? []);
    } catch {
      /* the overview's error explains a dead backend; a stale table is better than none */
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    loadBook(sel);
    const t = setInterval(() => loadBook(sel), 30000);
    return () => clearInterval(t);
  }, [sel, loadBook]);

  const runNow = async () => {
    setBusy(true);
    setNote(null);
    try {
      const r = await apiFetch("/api/gold-desk/top5/run", { method: "POST" });
      const books = Object.values((r?.books ?? {}) as Record<string, { opened?: number; closed?: number }>);
      const opened = books.reduce((n, b) => n + (b.opened ?? 0), 0);
      const shut = books.reduce((n, b) => n + (b.closed ?? 0), 0);
      setNote(r?.note ?? `Copied the desk now: ${opened} opened, ${shut} closed across the ${books.length} accounts.`);
      await Promise.all([load(), loadBook(sel)]);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "The copy could not run.");
    } finally {
      setBusy(false);
    }
  };

  if (err && !ov) {
    return (
      <div style={{ fontSize: 13, color: "var(--loss)", padding: "6px 2px" }}>
        {`${what[0].toUpperCase()}${what.slice(1)} could not be read: ${err}.`}
        {err === "Not Found" ? " The backend that runs them has not been deployed to the server yet." : ""}
      </div>
    );
  }
  if (!ov) return <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{`Loading ${what}…`}</div>;
  return <Top5View ov={ov} view={view} sel={sel} onSel={setSel} open={open} closed={closed} busy={busy} note={note} onRun={runNow} />;
}

/** What the panel shows, given what it read: no state of its own beyond its props, so it can be rendered on its own. */
export function Top5View({ ov, view = "top5", sel, onSel, open, closed, busy, note, onRun }: {
  ov: Overview; view?: View; sel: string; onSel: (id: string) => void; open: Copy[]; closed: Copy[]; busy: boolean;
  note: string | null; onRun: () => void;
}) {
  const setSel = onSel;
  const runNow = onRun;
  const byId: Record<string, Book> = Object.fromEntries(ov.books.map((b) => [b.id, b]));
  const each = ov.books.filter((b) => b.group === "each10L");
  const H1G = ov.h1_groups ?? ["h1_2L", "h1_10L", "h1own2L", "h1own10L"];
  const inView = (b: Book) => (view === "h1") === H1G.includes(b.group);
  const started = ov.books.filter(inView).map((b) => b.started_at).filter((x): x is string => !!x).sort()[0] ?? null;
  const cur = byId[sel];
  const notes = view === "h1" ? (ov.notes_h1 ?? ov.notes) : ov.notes;
  const allPicks = [...(ov.picks_h1 ?? []), ...(ov.picks_1811 ?? []), ...ov.picks];
  const pickOf = (key: string) => allPicks.find((p) => p.key === key);
  const p18 = ov.picks_1811 ?? [];
  const own2 = ov.books.filter((b) => b.group === "own2L");
  const own10 = ov.books.filter((b) => b.group === "own10L");
  const gt = ov.group_totals ?? {};
  const ph = ov.picks_h1 ?? [];
  const h1own2 = ov.books.filter((b) => b.group === "h1own2L");
  const h1own10 = ov.books.filter((b) => b.group === "h1own10L");

  return (
    <div className="t5">
      {view === "h1" ? (
        <>
          <div className="t5-warn">
            <b>Paper only, and not proven.</b>{" "}All nine of H1&apos;s strategies, in this desk&apos;s Rank order on 19 Nov
            at 20:15 IST, fixed from then. They had 5 to 24 closed trades each; the best t-stat was 1.31 and four were below
            zero. Every account copies H1&apos;s own trades on Delta&apos;s live XAUTUSD at its own size; no order is sent.
          </div>
          <h4 className="t5-h">All nine H1 strategies · a ₹2 lakh and a ₹10 lakh account they share, and each on its own ₹2 lakh and ₹10 lakh</h4>
          {!ov.picks_h1 ? (
            <p className="t5-dim">
              These twenty accounts are set up, but the server has not been updated with them yet. They start copying H1 on
              the first pass after the backend is deployed; nothing is back-filled.
            </p>
          ) : (
            <>
              <div className="t5-cards">
                <Card title="H1 nine · ₹2 lakh" sub="one account the nine share · up to 9 positions of ₹22,222"
                  m={byId.h1_2L} on={sel === "h1_2L"} onClick={() => setSel("h1_2L")} />
                <Card title="H1 nine · ₹10 lakh" sub="one account the nine share · up to 9 positions of ₹1,11,111"
                  m={byId.h1_10L} on={sel === "h1_10L"} onClick={() => setSel("h1_10L")} />
                <Card title="₹2 lakh each" sub={`${gt.h1own2L?.accounts ?? h1own2.length} accounts, one per strategy · each trade uses its own balance`}
                  m={gt.h1own2L} on={sel.startsWith("h1own2L")} onClick={() => setSel(h1own2[0]?.id ?? "h1own2L_1")} />
                <Card title="₹10 lakh each" sub={`${gt.h1own10L?.accounts ?? h1own10.length} accounts, one per strategy · each trade uses its own balance`}
                  m={gt.h1own10L} on={sel.startsWith("h1own10L")} onClick={() => setSel(h1own10[0]?.id ?? "h1own10L_1")} />
              </div>
              <div className="t5-scroll">
                <table className="t5-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th className="l">Strategy</th>
                      <th className="l">At the pick (19 Nov, 20:15 IST)</th>
                      <th title="Its trades inside the ₹2 lakh account the nine share">Shared ₹2 lakh</th>
                      <th title="Its trades inside the ₹10 lakh account the nine share">Shared ₹10 lakh</th>
                      <th>Its own ₹2 lakh</th>
                      <th>Its own ₹10 lakh</th>
                      <th>Open now</th>
                      <th title={`${DAY_COL_TITLES.traded}, in its own ₹2 lakh account`}>Days traded</th>
                      <th title="Days since its accounts started, today counted (Delta's XAUTUSD trades every day)">Total days</th>
                      <th title="Its own ₹2 lakh account's total return: realised + open P&L on ₹2 lakh (the ₹10 lakh twin copies the same trades; its return is in its cell)">
                        Total return
                      </th>
                      <th title={DAY_COL_TITLES.avg}>Avg / day</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ph.map((p) => {
                      const s2 = byId.h1_2L?.strategies.find((x) => x.key === p.key);
                      const s10 = byId.h1_10L?.strategies.find((x) => x.key === p.key);
                      const a = byId[`h1own2L_${p.n}`];
                      const b = byId[`h1own10L_${p.n}`];
                      const openNow = (s2?.open ?? 0) + (s10?.open ?? 0) + (a?.open_positions ?? 0) + (b?.open_positions ?? 0);
                      const dd = dayFigures(a);
                      return (
                        <tr key={p.key}>
                          <td>{p.n}</td>
                          <td className="l"><b>{p.name}</b><div className="t5-dim">H1 template · {p.template}</div></td>
                          <td className="l">
                            score {p.score.toFixed(1)} · {p.trades} trades
                            <div className="t5-dim">{`${p.bp >= 0 ? "+" : ""}${p.bp.toFixed(1)} bp a trade · t ${p.t.toFixed(2)} · ${usd(p.net_usd)} on the desk`}</div>
                          </td>
                          {[s2, s10].map((s, i) => {
                            const v = s ? s.net + s.unrealized : null;     // realised + open, in the shared account
                            return (
                              <td key={`s${i}`} className={tone(v)}>
                                {s ? <>{inr(v, true)}<div className="t5-dim">{s.trades} trades{s.open ? ` · ${s.open} open` : ""}</div></> : "—"}
                              </td>
                            );
                          })}
                          {[a, b].map((acct, i) => (
                            <td key={`o${i}`} className={tone(acct?.roi_pct)}>
                              {acct ? (
                                <button className={`t5-cell${sel === acct.id ? " on" : ""}`} onClick={() => setSel(acct.id)}
                                  title={`Open ${acct.label}`}>
                                  {inr(acct.equity)}
                                  <div className="t5-dim">{pct(acct.roi_pct)} · {acct.closed_positions} trades</div>
                                </button>
                              ) : "—"}
                            </td>
                          ))}
                          <td>{openNow || "—"}</td>
                          <td>{dayCell(dd.days)}</td>
                          <td>{dayCell(dd.total)}</td>
                          <td className={toneOf(dd.ret)}>{pctCell(dd.ret)}</td>
                          <td className={toneOf(dd.avg)}>{pctCell(dd.avg)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      ) : (
      <>
      <div className="t5-warn">
        <b>Paper only, and not proven.</b>{" "}Each set of five is the top of this desk&apos;s Rank on the day it was picked
        and stays fixed. They had 8 to 20 closed trades each and none a t-stat of 2: a short good record, not an edge.
      </div>

      <h4 className="t5-h">Today&apos;s top 5 (18 Nov) · each strategy on its own ₹2 lakh and its own ₹10 lakh</h4>
      {!ov.picks_1811 ? (
        <p className="t5-dim">
          These ten accounts are set up, but the server has not been updated with them yet. They start copying H1 on the
          first pass after the backend is deployed; nothing is back-filled.
        </p>
      ) : (
        <>
          <div className="t5-cards">
            <Card title="₹2 lakh each" sub={`${gt.own2L?.accounts ?? own2.length} accounts, one per strategy · each trade uses its own balance`}
              m={gt.own2L} on={sel.startsWith("own2L")} onClick={() => setSel(own2[0]?.id ?? "own2L_1")} />
            <Card title="₹10 lakh each" sub={`${gt.own10L?.accounts ?? own10.length} accounts, one per strategy · each trade uses its own balance`}
              m={gt.own10L} on={sel.startsWith("own10L")} onClick={() => setSel(own10[0]?.id ?? "own10L_1")} />
          </div>
          <div className="t5-scroll">
            <table className="t5-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th className="l">Strategy</th>
                  <th className="l">At the pick (18 Nov, 07:53 IST)</th>
                  <th>Its own ₹2 lakh</th>
                  <th>Its own ₹10 lakh</th>
                  <th>Open now</th>
                  <th title={`${DAY_COL_TITLES.traded}, in its own ₹2 lakh account`}>Days traded</th>
                  <th title="Days since its accounts started, today counted (Delta's XAUTUSD trades every day)">Total days</th>
                  <th title="Its own ₹2 lakh account's total return: realised + open P&L on ₹2 lakh (the ₹10 lakh twin copies the same trades; its return is in its cell)">
                    Total return
                  </th>
                  <th title={DAY_COL_TITLES.avg}>Avg / day</th>
                </tr>
              </thead>
              <tbody>
                {p18.map((p) => {
                  const a = byId[`own2L_${p.n}`];
                  const b = byId[`own10L_${p.n}`];
                  const openNow = (a?.open_positions ?? 0) + (b?.open_positions ?? 0);
                  const dd = dayFigures(a);
                  return (
                    <tr key={p.key}>
                      <td>{p.n}</td>
                      <td className="l"><b>{p.name}</b><div className="t5-dim">H1 template · {p.template}</div></td>
                      <td className="l">
                        score {p.score.toFixed(1)} · {p.trades} trades
                        <div className="t5-dim">{`${p.bp >= 0 ? "+" : ""}${p.bp.toFixed(1)} bp a trade · t ${p.t.toFixed(2)} · ${usd(p.net_usd)} on the desk`}</div>
                      </td>
                      {[a, b].map((acct, i) => (
                        <td key={i} className={tone(acct?.roi_pct)}>
                          {acct ? (
                            <button className={`t5-cell${sel === acct.id ? " on" : ""}`} onClick={() => setSel(acct.id)}
                              title={`Open ${acct.label}`}>
                              {inr(acct.equity)}
                              <div className="t5-dim">{pct(acct.roi_pct)} · {acct.closed_positions} trades</div>
                            </button>
                          ) : "—"}
                        </td>
                      ))}
                      <td>{openNow || "—"}</td>
                      <td>{dayCell(dd.days)}</td>
                      <td>{dayCell(dd.total)}</td>
                      <td className={toneOf(dd.ret)}>{pctCell(dd.ret)}</td>
                      <td className={toneOf(dd.avg)}>{pctCell(dd.avg)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h4 className="t5-h">The 12 Nov top 5 · three accounts</h4>
      <div className="t5-cards">
        <Card title="Top 5 · ₹2 lakh" sub="one account the five share · up to 5 positions of ₹40,000"
          m={byId.top5_2L} on={sel === "top5_2L"} onClick={() => setSel("top5_2L")} />
        <Card title="Top 5 · ₹10 lakh" sub="one account the five share · up to 5 positions of ₹2,00,000"
          m={byId.top5_10L} on={sel === "top5_10L"} onClick={() => setSel("top5_10L")} />
        <Card title="Top 5 · ₹10 lakh each" sub={`${ov.each_total.accounts} accounts, one per strategy · each trade uses its own balance`}
          m={ov.each_total} on={sel.startsWith("each10L")} onClick={() => setSel(each[0]?.id ?? "each10L_1")} />
      </div>

      <div className="t5-scroll">
        <table className="t5-table">
          <thead>
            <tr>
              <th>#</th>
              <th className="l">Strategy</th>
              <th className="l">At the pick</th>
              <th>₹2 lakh book</th>
              <th>₹10 lakh book</th>
              <th>Its own ₹10 lakh account</th>
              <th>Open now</th>
              <th title={`${DAY_COL_TITLES.traded}, in its own ₹10 lakh account`}>Days traded</th>
              <th title="Days since its accounts started, today counted (Delta's XAUTUSD trades every day)">Total days</th>
              <th title="Its own ₹10 lakh account's total return: realised + open P&L on ₹10 lakh">Total return</th>
              <th title={DAY_COL_TITLES.avg}>Avg / day</th>
            </tr>
          </thead>
          <tbody>
            {ov.picks.map((p) => {
              const a = byId.top5_2L?.strategies.find((x) => x.key === p.key);
              const b = byId.top5_10L?.strategies.find((x) => x.key === p.key);
              const own = byId[`each10L_${p.n}`];
              const openNow = (a?.open ?? 0) + (b?.open ?? 0) + (own?.open_positions ?? 0);
              const dd = dayFigures(own);
              return (
                <tr key={p.key}>
                  <td>{p.n}</td>
                  <td className="l"><b>{p.name}</b><div className="t5-dim">H1 template · {p.template}</div></td>
                  <td className="l">
                    score {p.score.toFixed(1)} · {p.trades} trades
                    <div className="t5-dim">{`${p.bp >= 0 ? "+" : ""}${p.bp.toFixed(1)} bp a trade · t ${p.t.toFixed(2)} · ${usd(p.net_usd)} on the desk`}</div>
                  </td>
                  <td className={tone(a?.net)}>{a ? <>{inr(a.net, true)}<div className="t5-dim">{a.trades} trades</div></> : "—"}</td>
                  <td className={tone(b?.net)}>{b ? <>{inr(b.net, true)}<div className="t5-dim">{b.trades} trades</div></> : "—"}</td>
                  <td className={tone(own?.roi_pct)}>
                    {own ? <>{inr(own.equity)}<div className="t5-dim">{pct(own.roi_pct)} · {own.closed_positions} trades</div></> : "—"}
                  </td>
                  <td>{openNow || "—"}</td>
                  <td>{dayCell(dd.days)}</td>
                  <td>{dayCell(dd.total)}</td>
                  <td className={toneOf(dd.ret)}>{pctCell(dd.ret)}</td>
                  <td className={toneOf(dd.avg)}>{pctCell(dd.avg)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      </>
      )}

      <div className="t5-bar">
        {view === "h1" ? (
          <div className="t5-chips" role="group" aria-label="Account">
            {ov.picks_h1 && (
              <>
                <button className={`t5-chip${sel === "h1_2L" ? " on" : ""}`} onClick={() => setSel("h1_2L")}>Shared ₹2 lakh</button>
                <button className={`t5-chip${sel === "h1_10L" ? " on" : ""}`} onClick={() => setSel("h1_10L")}>Shared ₹10 lakh</button>
              </>
            )}
            {[...h1own2, ...h1own10].map((b) => (
              <button key={b.id} className={`t5-chip${sel === b.id ? " on" : ""}`} onClick={() => setSel(b.id)}>
                {`${SHORT(pickOf(b.roster[0])?.name ?? b.label)} · ${b.group === "h1own2L" ? "₹2L" : "₹10L"}`}
              </button>
            ))}
          </div>
        ) : (
        <div className="t5-chips" role="group" aria-label="Account">
          {[...own2, ...own10].map((b) => (
            <button key={b.id} className={`t5-chip${sel === b.id ? " on" : ""}`} onClick={() => setSel(b.id)}>
              {`${SHORT(pickOf(b.roster[0])?.name ?? b.label)} · ${b.group === "own2L" ? "₹2L" : "₹10L"} (18 Nov)`}
            </button>
          ))}
          <button className={`t5-chip${sel === "top5_2L" ? " on" : ""}`} onClick={() => setSel("top5_2L")}>₹2 lakh book</button>
          <button className={`t5-chip${sel === "top5_10L" ? " on" : ""}`} onClick={() => setSel("top5_10L")}>₹10 lakh book</button>
          {each.map((b) => (
            <button key={b.id} className={`t5-chip${sel === b.id ? " on" : ""}`} onClick={() => setSel(b.id)}>
              {`${SHORT(pickOf(b.roster[0])?.name ?? b.label)} · ₹10 lakh`}
            </button>
          ))}
        </div>
        )}
        <button className="t5-run" disabled={busy} onClick={runNow} title="Copy the desk's latest trades into every account now">
          {busy ? "Copying…" : "Copy now"}
        </button>
      </div>
      {note && <div className="t5-note">{note}</div>}

      {cur && (
        <div className="t5-sum">
          <b>{cur.label}</b>
          {` · equity ${inr(cur.equity)} · free cash ${inr(cur.available_cash)} · tied up ${inr(cur.deployed)}`}
          {cur.position_cap ? ` · up to ${inr(cur.position_cap)} a position` : " · each trade uses the account's balance"}
          {Object.keys(cur.skipped).length ? ` · skipped ${Object.entries(cur.skipped).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}` : ""}
          {cur.voided ? ` · ${cur.voided} void` : ""}
        </div>
      )}

      <h4 className="t5-h">Open positions ({open.length})</h4>
      {open.length ? (
        <div className="t5-scroll">
          <table className="t5-table">
            <thead>
              <tr>
                <th className="l">Strategy</th><th>Side</th><th>Contracts</th><th>Entered (IST)</th><th>Entry</th><th>Last</th>
                <th>Ties up</th><th>Open P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {open.map((r) => (
                <tr key={r.position_id}>
                  <td className="l">{SHORT(r.strategy_name)}</td>
                  <td>{r.side === "BUY" ? "Long" : "Short"}</td>
                  <td>{r.qty.toLocaleString("en-IN")}<div className="t5-dim">{r.ounces} oz</div></td>
                  <td>{ist(r.opened_at)}</td>
                  <td>{usd(r.entry_px)}</td>
                  <td>{usd(r.ltp)}</td>
                  <td>{inr(r.capital_deployed)}</td>
                  <td className={tone(r.unrealized_pnl)}>{inr(r.unrealized_pnl, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="t5-dim">No open position in this account.</p>
      )}

      <h4 className="t5-h">Closed trades ({closed.length})</h4>
      {closed.length ? (
        <div className="t5-scroll">
          <table className="t5-table">
            <thead>
              <tr>
                <th className="l">Strategy</th><th>Side</th><th>Contracts</th><th>Entered (IST)</th><th>Left (IST)</th>
                <th>Entry</th><th>Exit</th><th>Why</th><th>Gross</th><th>Costs</th><th>Net</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((r) => (
                <tr key={r.position_id}>
                  <td className="l">{SHORT(r.strategy_name)}</td>
                  <td>{r.side === "BUY" ? "Long" : "Short"}</td>
                  <td>{r.qty.toLocaleString("en-IN")}</td>
                  <td>{ist(r.opened_at)}</td>
                  <td>{ist(r.closed_at)}</td>
                  <td>{usd(r.entry_px)}</td>
                  <td>{usd(r.exit_px)}</td>
                  <td>{WHY[r.exit_reason ?? ""] ?? r.exit_reason ?? "—"}</td>
                  <td className={tone(r.gross_pnl)}>{inr(r.gross_pnl, true)}</td>
                  <td>{inr(r.fees)}</td>
                  <td className={`strong ${tone(r.realized_pnl)}`}>{inr(r.realized_pnl, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="t5-dim">
          {`No closed trade yet. The accounts copy only trades the desk opens after they started${started ? ` (${ist(started)} IST)` : ""}; H1 trades on 4-hour bars, so the first copies come at its next 4-hour closes.`}
        </p>
      )}

      <ul className="t5-notes">
        {notes.map((n, i) => <li key={i}>{n}</li>)}
      </ul>
      <div className="t5-foot">
        {`Copies the desk every ${Math.round(ov.tick_seconds / 60)} minutes${ov.enabled ? "" : " (switched off)"}`}
        {ov.usd_inr?.rate ? ` · USD/INR ${ov.usd_inr.rate.toFixed(2)} (read ${ist(ov.usd_inr.at)} IST)` : " · USD/INR not read yet"}
        {started ? ` · started ${ist(started)} IST` : ""}
      </div>

      {/* global: the account cards are drawn by <Card>, a child component that scoped styles never reach. Every
          selector is under .t5, so nothing outside this panel is touched. */}
      <style jsx global>{`
        .t5 { display: flex; flex-direction: column; gap: 14px; }
        .t5 .t5-warn { font-size: 12.5px; line-height: 1.55; color: var(--text-muted); background: var(--canvas-soft);
                       border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; }
        .t5 .t5-warn b { color: var(--text); }
        .t5 .t5-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
        .t5 .t5-card { display: flex; flex-direction: column; gap: 4px; text-align: left; cursor: pointer; font: inherit;
                       background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; padding: 14px 16px; }
        .t5 .t5-card.on { border-color: var(--brand-border); background: var(--brand-dim); }
        .t5 .t5-k { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .t5 .t5-v { font-family: var(--font-data); font-size: 22px; font-weight: 700; color: var(--text);
                    font-variant-numeric: tabular-nums; }
        .t5 .t5-r { font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .t5 .t5-s { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
        .t5 .t5-about { margin-top: 4px; font-size: 11.5px; color: var(--text-faint); }
        .t5 .t5-scroll { overflow-x: auto; }
        .t5 .t5-table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .t5 .t5-table th { font-size: 10.5px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase;
                           color: var(--text-faint); text-align: right; padding: 8px 10px;
                           border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
        .t5 .t5-table td { text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--panel-border);
                           vertical-align: top; white-space: nowrap; }
        .t5 .t5-table .l { text-align: left; }
        .t5 .t5-table td.l { white-space: normal; min-width: 160px; }
        .t5 .t5-dim { font-size: 11.5px; color: var(--text-muted); }
        .t5 .gain { color: var(--gain); }
        .t5 .loss { color: var(--loss); }
        .t5 .strong { font-weight: 700; }
        .t5 .t5-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
        .t5 .t5-chips { display: flex; flex-wrap: wrap; gap: 8px; }
        .t5 .t5-chip { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
                       border-radius: 999px; padding: 6px 12px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .t5 .t5-chip.on { color: var(--brand); border-color: var(--brand-border); background: var(--brand-dim); }
        .t5 .t5-cell { font: inherit; color: inherit; text-align: right; cursor: pointer; background: transparent;
                       border: 1px solid transparent; border-radius: 8px; padding: 2px 6px; }
        .t5 .t5-cell:hover { border-color: var(--brand-border); }
        .t5 .t5-cell.on { border-color: var(--brand-border); background: var(--brand-dim); }
        .t5 .t5-run { background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted);
                      border-radius: 9px; padding: 7px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .t5 .t5-run:hover:not(:disabled) { color: var(--brand); border-color: var(--brand-border); }
        .t5 .t5-run:disabled { opacity: 0.55; cursor: default; }
        .t5 .t5-note { font-size: 12.5px; color: var(--brand); }
        .t5 .t5-sum { font-size: 12.5px; color: var(--text-muted); line-height: 1.5; }
        .t5 .t5-sum b { color: var(--text); }
        .t5 .t5-h { margin: 6px 0 0; font-size: 13px; font-weight: 800; color: var(--text); }
        .t5 .t5-notes { margin: 4px 0 0; padding-left: 18px; font-size: 12px; line-height: 1.6; color: var(--text-muted); }
        .t5 .t5-foot { font-size: 11.5px; color: var(--text-faint); }
        @media (max-width: 640px) {
          .t5 .t5-v { font-size: 19px; }
        }
      `}</style>
    </div>
  );
}
