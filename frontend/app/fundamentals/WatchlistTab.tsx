"use client";

/** Watchlists, and the paper book that checks whether the grades were right.
 *
 * The per-tier table is the reason this screen exists. Everything else — the positions,
 * the daily rows — is there to make that table trustworthy.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import {
  BookDay,
  GRADE_COLOR,
  GRADE_ORDER,
  GradeKey,
  PaperBook,
  FundWatchlist,
  deleteFundWatchlist,
  fetchBookDaily,
  fetchPaperBook,
  fetchFundWatchlists,
  fundWatchlist,
  saveFundWatchlist,
  snapshotBook,
} from "../../lib/api";
import TvExport from "./TvExport";
import { downloadTxt, prettyGroup, tvFilename, tvSections } from "./tradingview";

/** Best grade first, then the two "no grade" buckets - the order sections and chips use. */
const BEST_FIRST: string[] = ([...GRADE_ORDER] as string[]).reverse().concat(["unrated", "not-in-book"]);

const rs = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined
    ? "—"
    : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: dp })}`;

const signed = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

const tone = (v: number | null | undefined) =>
  v === null || v === undefined ? "" : v > 0 ? "up" : v < 0 ? "down" : "";

export default function WatchlistTab() {
  const [lists, setLists] = useState<FundWatchlist[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [book, setBook] = useState<PaperBook | null>(null);
  const [days, setDays] = useState<BookDay[]>([]);
  const [name, setName] = useState("Fundamentally strong stocks");
  const [symbols, setSymbols] = useState("");
  const [perStock, setPerStock] = useState(100000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  // Grade-at-entry filter on Positions. Empty = every grade.
  const [fGrades, setFGrades] = useState<string[]>([]);

  const loadLists = useCallback(async () => {
    try {
      const r = await fetchFundWatchlists();
      setLists(r.watchlists);
      if (!active && r.watchlists.length) setActive(r.watchlists[0].name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load watchlists.");
    }
  }, [active]);

  const loadBook = useCallback(async (n: string) => {
    try {
      const [b, d] = await Promise.all([fetchPaperBook(n, true), fetchBookDaily(n)]);
      setBook(b);
      setDays(d.days);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the book.");
    }
  }, []);

  useEffect(() => {
    loadLists();
  }, [loadLists]);

  useEffect(() => {
    if (active) loadBook(active);
    setFGrades([]);
  }, [active, loadBook]);

  const activeList = lists.find((w) => w.name === active) ?? null;
  const positions = useMemo(() => book?.positions ?? [], [book]);

  /** Grade at entry per symbol, from the book. A list name that never made it into the book
   *  (no price when funded, say) has no entry grade, and is exported under its own section
   *  rather than being passed off as one of the grades. */
  const gradeOf = useMemo(() => {
    const m: Record<string, string> = {};
    for (const p of positions) m[p.symbol] = p.grade_key_at_entry || "unrated";
    return m;
  }, [positions]);

  const listItems = useMemo(
    () =>
      (activeList?.symbols ?? []).map((sym) => ({
        symbol: sym,
        group: gradeOf[sym] ?? (book?.funded ? "not-in-book" : null),
      })),
    [activeList, gradeOf, book],
  );

  const gradeCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const p of positions) {
      const g = p.grade_key_at_entry || "unrated";
      c[g] = (c[g] ?? 0) + 1;
    }
    return c;
  }, [positions]);
  const gradesPresent = BEST_FIRST.filter((g) => gradeCounts[g]);

  const shownPositions = useMemo(
    () =>
      fGrades.length
        ? positions.filter((p) => fGrades.includes(p.grade_key_at_entry || "unrated"))
        : positions,
    [positions, fGrades],
  );

  const toggleGrade = (g: string) =>
    setFGrades((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]));

  /** Every list in one TradingView file, a ###section per list. TradingView will not hold a
   *  symbol twice in one watchlist, so a name in two lists lands in the first one's section. */
  const exportAll = () => {
    const items = lists.flatMap((w) => w.symbols.map((sym) => ({ symbol: sym, group: w.name })));
    downloadTxt(
      tvFilename("Fundamental Rating - all lists"),
      tvSections(items, lists.map((w) => w.name), (g) => g),
    );
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const w = await saveFundWatchlist(name, symbols);
      setMsg(`Saved "${w.name}" with ${w.count} stocks.`);
      setSymbols("");
      setShowAdd(false);
      setActive(w.name);
      await loadLists();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const fund = async () => {
    if (!active) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await fundWatchlist(active, perStock);
      const skipped = r.skipped?.length
        ? ` ${r.skipped.length} skipped: ${r.skipped.map((s) => `${s.symbol} (${s.reason})`).join("; ")}`
        : "";
      setMsg(`Opened ${r.opened} positions at ${rs(perStock)} each.${skipped}`);
      await loadBook(active);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not fund the book.");
    } finally {
      setBusy(false);
    }
  };

  const snap = async () => {
    if (!active) return;
    setBusy(true);
    try {
      const r = await snapshotBook(active);
      setMsg(r.written ? "Today's row written." : `Not written — ${r.reason}.`);
      await loadBook(active);
    } finally {
      setBusy(false);
    }
  };

  const drop = async (n: string) => {
    await deleteFundWatchlist(n);
    if (active === n) {
      setActive(null);
      setBook(null);
      setDays([]);
    }
    await loadLists();
  };

  return (
    <>
      {error && <div className="bad">{error}</div>}
      {msg && <div className="ok">{msg}</div>}

      <GlassPanel title="Watchlists">
        <div className="listrow">
          {lists.map((w) => (
            <button
              key={w.name}
              className={`chip ${active === w.name ? "on" : ""}`}
              onClick={() => setActive(w.name)}
            >
              {w.name} <span className="n">{w.count}</span>
            </button>
          ))}
          <button className="chip add" onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? "Cancel" : "+ New list"}
          </button>
          {active && (
            <button className="chip danger" onClick={() => drop(active)}>
              Delete “{active}”
            </button>
          )}
        </div>

        {activeList && !showAdd && (
          <div className="tvwrap">
            <TvExport
              items={listItems}
              name={activeList.name}
              groupOrder={BEST_FIRST}
              sectionsLabel="sections by grade at entry"
            />
            {lists.length > 1 && (
              <button className="ghost" onClick={exportAll}>
                All {lists.length} lists in one .txt
              </button>
            )}
          </div>
        )}

        {showAdd && (
          <div className="addbox">
            <input
              className="nm"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Watchlist name"
            />
            <textarea
              rows={3}
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="NSE:RELIANCE,NSE:TCS,…  — paste a TradingView list, commas, or one per line"
            />
            <button className="primary" onClick={save} disabled={busy}>
              Save list
            </button>
          </div>
        )}
      </GlassPanel>

      {active && (
        <GlassPanel
          title={`Paper book — ${active}`}
          note={book?.marked_at ? `marked ${new Date(book.marked_at).toLocaleString("en-IN")}` : undefined}
          onRefresh={() => loadBook(active)}
        >
          <div className="fundrow">
            <label>
              <span>Per stock</span>
              <input
                type="number"
                step={10000}
                min={1000}
                value={perStock}
                onChange={(e) => setPerStock(Number(e.target.value))}
              />
            </label>
            <button className="primary" onClick={fund} disabled={busy}>
              {book?.funded ? "Fund any new names" : "Fund this book"}
            </button>
            <button className="ghost" onClick={snap} disabled={busy || !book?.funded}>
              Snapshot today
            </button>
            <span className="hint">
              Whole shares only; the remainder stays as cash. Buy price is the live price
              when a name is added and is never rewritten.
            </span>
          </div>

          {book?.funded ? (
            <>
              <div className="tiles">
                <Tile label="Invested" value={rs(book.invested)} sub={`${book.stocks} stocks`} />
                <Tile label="Value now" value={rs(book.value)} />
                <Tile
                  label="P&L"
                  value={signed(book.pnl)}
                  cls={tone(book.pnl)}
                  sub={pct(book.return_pct)}
                />
                <Tile
                  label="Winners"
                  value={`${book.winners} / ${book.stocks}`}
                  sub={`${book.win_rate}% up`}
                />
                <Tile label="Idle cash" value={rs(book.cash_left)} sub="unspent remainders" />
              </div>

              <h4 className="h">How each grade performed</h4>
              <p className="explain">
                Grouped by the grade the stock held <b>when it was bought</b>, not its grade
                today — otherwise a stock upgraded after it rose would flatter the tier it
                landed in. This is the table that says whether the scale is worth anything.
              </p>
              <div className="wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="l">Grade at entry</th>
                      <th>Stocks</th>
                      <th>Invested</th>
                      <th>Value</th>
                      <th>P&amp;L</th>
                      <th>Return</th>
                      <th>Win rate</th>
                      <th className="l">Best</th>
                      <th className="l">Worst</th>
                    </tr>
                  </thead>
                  <tbody>
                    {book.tiers.map((t) => (
                      <tr
                        key={t.grade_key}
                        className={`tier ${fGrades.includes(t.grade_key || "unrated") ? "sel" : ""}`}
                        onClick={() => toggleGrade(t.grade_key || "unrated")}
                        title="Show only this grade in Positions below"
                      >
                        <td className="l">
                          <span
                            className="pill"
                            style={{
                              borderColor: GRADE_COLOR[t.grade_key as GradeKey] ?? "#888",
                              color: GRADE_COLOR[t.grade_key as GradeKey] ?? "#888",
                            }}
                          >
                            {(t.grade_key || "unrated").replace("-", " ")}
                          </span>
                        </td>
                        <td>{t.stocks}</td>
                        <td>{rs(t.invested)}</td>
                        <td>{rs(t.value)}</td>
                        <td className={tone(t.pnl)}>{signed(t.pnl)}</td>
                        <td className={`big ${tone(t.avg_return_pct)}`}>
                          {pct(t.avg_return_pct)}
                        </td>
                        <td>{t.win_rate}%</td>
                        <td className="l sm">
                          {t.best ? `${t.best.symbol} ${pct(t.best.return_pct)}` : "—"}
                        </td>
                        <td className="l sm">
                          {t.worst ? `${t.worst.symbol} ${pct(t.worst.return_pct)}` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {days.length > 0 && (
                <>
                  <h4 className="h">Day by day</h4>
                  <div className="wrap">
                    <table>
                      <thead>
                        <tr>
                          <th className="l">Session</th>
                          <th>Value</th>
                          <th>Day P&amp;L</th>
                          <th>Day %</th>
                          <th>Total P&amp;L</th>
                          <th>Total %</th>
                          <th>Win rate</th>
                          <th className="l">Best / worst that day</th>
                        </tr>
                      </thead>
                      <tbody>
                        {days.map((d) => (
                          <tr key={d.session}>
                            <td className="l">{d.session}</td>
                            <td>{rs(d.value)}</td>
                            <td className={tone(d.day_pnl)}>{signed(d.day_pnl)}</td>
                            <td className={tone(d.day_return_pct)}>{pct(d.day_return_pct)}</td>
                            <td className={tone(d.pnl)}>{signed(d.pnl)}</td>
                            <td className={tone(d.return_pct)}>{pct(d.return_pct)}</td>
                            <td>{d.win_rate}%</td>
                            <td className="l sm">
                              {d.movers?.best
                                ? `${d.movers.best.symbol} ${pct(d.movers.best.return_pct)}`
                                : "—"}
                              {" · "}
                              {d.movers?.worst
                                ? `${d.movers.worst.symbol} ${pct(d.movers.worst.return_pct)}`
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="explain">
                    Written once per session after 15:35 IST, so a row is a closing number
                    rather than something the closing auction then moved. Each row also
                    freezes every tier&rsquo;s value that day, which is where the per-grade day
                    move comes from.
                  </p>
                </>
              )}

              <h4 className="h">Positions</h4>
              <div className="gfilter" role="group" aria-label="Filter by grade at entry">
                <span className="gl">Grade at entry</span>
                <button
                  className={`gchip ${fGrades.length === 0 ? "on" : ""}`}
                  onClick={() => setFGrades([])}
                >
                  All <span className="n">{positions.length}</span>
                </button>
                {gradesPresent.map((g) => {
                  const c = GRADE_COLOR[g as GradeKey] ?? "#888";
                  const on = fGrades.includes(g);
                  return (
                    <button
                      key={g}
                      className={`gchip ${on ? "on" : ""}`}
                      style={on ? { borderColor: c, color: c, background: `${c}14` } : { borderColor: `${c}55` }}
                      onClick={() => toggleGrade(g)}
                      aria-pressed={on}
                    >
                      {prettyGroup(g)} <span className="n">{gradeCounts[g]}</span>
                    </button>
                  );
                })}
                {fGrades.length > 0 && (
                  <span className="shown">
                    Showing {shownPositions.length} of {positions.length}
                  </span>
                )}
              </div>
              <div className="tvwrap">
                <TvExport
                  items={shownPositions.map((p) => ({
                    symbol: p.symbol,
                    group: p.grade_key_at_entry || "unrated",
                  }))}
                  name={`${active} - ${fGrades.length ? fGrades.map(prettyGroup).join(" + ") : "all grades"}`}
                  groupOrder={BEST_FIRST}
                  sectionsLabel="sections by grade at entry"
                  hint={false}
                />
              </div>
              <div className="wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="l">Stock</th>
                      <th className="l">Grade at entry</th>
                      <th>Qty</th>
                      <th>Buy</th>
                      <th>LTP</th>
                      <th>Invested</th>
                      <th>Value</th>
                      <th>P&amp;L</th>
                      <th>Return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shownPositions.map((p) => (
                      <tr key={p.symbol}>
                        <td className="l">
                          <b>{p.symbol}</b>
                          <div className="sub">{p.name}</div>
                        </td>
                        <td className="l">
                          <span
                            className="pill"
                            style={{
                              borderColor: GRADE_COLOR[p.grade_key_at_entry as GradeKey] ?? "#888",
                              color: GRADE_COLOR[p.grade_key_at_entry as GradeKey] ?? "#888",
                            }}
                          >
                            {(p.grade_key_at_entry || "unrated").replace("-", " ")}
                          </span>
                        </td>
                        <td>{p.qty}</td>
                        <td>{rs(p.buy_price, 2)}</td>
                        <td>{rs(p.ltp, 2)}</td>
                        <td>{rs(p.invested)}</td>
                        <td>{rs(p.value)}</td>
                        <td className={tone(p.unrealized_pnl)}>{signed(p.unrealized_pnl)}</td>
                        <td className={tone(p.return_pct)}>{pct(p.return_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="explain">
              {book?.note ??
                "Not funded yet — set the amount per stock and press Fund this book."}
            </p>
          )}
        </GlassPanel>
      )}

      <style jsx>{`
        .bad,
        .ok {
          margin-bottom: 12px;
          font-size: 12.5px;
          border-radius: 9px;
          padding: 10px 12px;
        }
        .bad {
          color: #b3261e;
          background: rgba(212, 68, 60, 0.08);
          border: 1px solid rgba(212, 68, 60, 0.3);
        }
        .ok {
          color: #1a9c5b;
          background: rgba(26, 156, 91, 0.08);
          border: 1px solid rgba(26, 156, 91, 0.3);
        }
        .listrow {
          display: flex;
          gap: 7px;
          flex-wrap: wrap;
        }
        .chip {
          border: 1px solid var(--panel-border);
          background: var(--canvas-soft);
          border-radius: 20px;
          padding: 6px 13px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          color: inherit;
        }
        .chip.on {
          background: var(--purple);
          border-color: var(--purple);
          color: #fff;
        }
        .chip .n {
          opacity: 0.65;
          margin-left: 4px;
        }
        .chip.danger {
          color: #d4443c;
          border-color: rgba(212, 68, 60, 0.35);
        }
        .addbox {
          margin-top: 14px;
          display: flex;
          flex-direction: column;
          gap: 9px;
        }
        .addbox input,
        .addbox textarea,
        .fundrow input {
          border: 1px solid var(--panel-border);
          border-radius: 9px;
          padding: 9px 11px;
          font-size: 12.5px;
          background: var(--canvas-soft);
          color: var(--text);
        }
        .addbox textarea {
          font-family: var(--font-mono, ui-monospace, monospace);
          resize: vertical;
        }
        .primary {
          background: var(--purple);
          color: #fff;
          border: none;
          border-radius: 9px;
          padding: 9px 16px;
          font-weight: 650;
          font-size: 12.5px;
          cursor: pointer;
          align-self: flex-start;
        }
        .primary:disabled,
        .ghost:disabled {
          opacity: 0.55;
          cursor: default;
        }
        .ghost {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          border-radius: 9px;
          padding: 8px 14px;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
        }
        .fundrow {
          display: flex;
          gap: 10px;
          align-items: flex-end;
          flex-wrap: wrap;
          margin-bottom: 16px;
        }
        .fundrow label {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .fundrow span {
          font-size: 10.5px;
          color: var(--text-faint);
          text-transform: uppercase;
          letter-spacing: 0.4px;
        }
        .hint {
          font-size: 11.5px;
          color: var(--text-faint);
          max-width: 420px;
          text-transform: none;
          letter-spacing: 0;
        }
        .tiles {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 10px;
          margin-bottom: 20px;
        }
        .h {
          font-size: 13.5px;
          margin: 22px 0 6px;
        }
        .explain {
          font-size: 12px;
          color: var(--text-faint);
          line-height: 1.55;
          margin: 0 0 12px;
          max-width: 760px;
        }
        .wrap {
          overflow-x: auto;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
        }
        th,
        td {
          padding: 8px 10px;
          text-align: right;
          border-bottom: 1px solid var(--panel-border);
          white-space: nowrap;
        }
        th {
          font-size: 10.5px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-faint);
          font-weight: 600;
        }
        .l {
          text-align: left;
        }
        .sm {
          font-size: 11px;
          color: var(--text-muted);
        }
        .sub {
          font-size: 10.5px;
          color: var(--text-faint);
          font-weight: 400;
          max-width: 170px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .big {
          font-size: 13.5px;
          font-weight: 700;
        }
        .up {
          color: #1a9c5b;
        }
        .down {
          color: #d4443c;
        }
        .tvwrap {
          display: flex;
          flex-wrap: wrap;
          align-items: flex-start;
          gap: 8px;
          margin-top: 12px;
        }
        .gfilter {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 6px;
          margin: 4px 0 2px;
        }
        .gl {
          font-size: 10.5px;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          color: var(--text-faint);
          font-weight: 600;
          margin-right: 4px;
        }
        .gchip {
          border: 1px solid var(--panel-border);
          background: var(--panel);
          color: var(--text-muted);
          border-radius: 20px;
          padding: 4px 11px;
          font-size: 11.5px;
          font-weight: 650;
          cursor: pointer;
        }
        .gchip.on {
          color: var(--purple);
          border-color: var(--purple);
          background: var(--purple-dim);
        }
        .gchip .n {
          opacity: 0.65;
          margin-left: 3px;
          font-weight: 600;
        }
        .shown {
          font-size: 11.5px;
          color: var(--text-muted);
          margin-left: 4px;
        }
        tr.tier {
          cursor: pointer;
        }
        tr.tier:hover td {
          background: var(--canvas-soft);
        }
        tr.tier.sel td {
          background: var(--purple-dim);
        }
        .pill {
          border: 1px solid;
          border-radius: 20px;
          padding: 2px 9px;
          font-size: 10.5px;
          font-weight: 650;
          text-transform: capitalize;
        }
      `}</style>
    </>
  );
}

function Tile({
  label,
  value,
  sub,
  cls = "",
}: {
  label: string;
  value: string;
  sub?: string;
  cls?: string;
}) {
  return (
    <div className="tile">
      <div className="tl">{label}</div>
      <div className={`tv ${cls}`}>{value}</div>
      {sub && <div className="ts">{sub}</div>}
      <style jsx>{`
        .tile {
          border: 1px solid var(--panel-border);
          border-radius: 10px;
          padding: 11px 13px;
          background: var(--canvas-soft);
        }
        .tl {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-faint);
        }
        .tv {
          font-size: 18px;
          font-weight: 750;
          font-family: var(--font-display);
          margin-top: 3px;
        }
        .ts {
          font-size: 11px;
          color: var(--text-faint);
          margin-top: 2px;
        }
        .up {
          color: #1a9c5b;
        }
        .down {
          color: #d4443c;
        }
      `}</style>
    </div>
  );
}
