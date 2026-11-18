"use client";

// A group of picked paper accounts on NIFTY 50 Option Scalping (17 Nov 2026), side by side:
//   rank-band   20 accounts - the desk's Rank bands 1-5 ... 46-50, each in Rs 2 lakh and Rs 10 lakh
//   paper-top4   8 accounts - the Paper book's top 4, each strategy alone in Rs 2 lakh and Rs 10 lakh
//   top25-each  25 accounts - the desk's Rank 1-25 (18 Nov 2026), each strategy alone in Rs 2 lakh, in five sets
// One row per band / strategy with its two accounts; a click opens that account in full (Top10Book).
// Backend: app.services.top10_books (PICKED_BOOKS, group), GET /api/top10-books/nifty-scalp/accounts.

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import Top10Book from "../../components/Top10Book";
import {
  PickedAccounts as Accounts,
  PickedBookKey,
  PickedGroup,
  Top10Summary,
  fetchPickedAccounts,
} from "../../lib/top10Books";

const REFRESH_MS = 30000;

const INTRO: Record<PickedGroup, { title: string; body: string }> = {
  "rank-band": {
    title: "Rank-band accounts",
    body:
      "Ten bands of this page's Strategy leaderboard by Rank — 1-5, 6-10 … 46-50 — each copied into a ₹2 lakh " +
      "and a ₹10 lakh paper account. An account holds its five strategies with a slot each (a fifth of the " +
      "account per position) and takes the desk's own entries and exits. The fifty were frozen from the board " +
      "at 20:20 IST on 17 Nov 2026 and are never re-picked.",
  },
  "paper-top4": {
    title: "Paper book top 4 · one account each",
    body:
      "The top 4 strategies of the Paper book · ₹2L by their Rank there, each alone in a ₹2 lakh and a ₹10 lakh " +
      "paper account. One strategy, one slot: every trade may use the whole account, as the desk sizes each " +
      "strategy on its own ₹2 lakh. Each copies the desk's own trades of that strategy — the same signals the " +
      "Paper book takes. Frozen at 20:20 IST on 17 Nov 2026.",
  },
  "top25-each": {
    title: "Top 25 · ₹2 lakh each",
    body:
      "The top 25 of this page's Strategy leaderboard by Rank, each strategy alone in its own ₹2 lakh paper " +
      "account, in five sets: Top 1-5, 5-10, 10-15, 15-20 and 20-25 (Rank 1-5, 6-10 … 21-25). One strategy, one " +
      "slot: every trade may use the whole account, as the desk sizes each strategy on its own ₹2 lakh. Each " +
      "copies the desk's own trades of its strategy from the moment it was picked, so it starts at ₹2 lakh. " +
      "Frozen at 22:59 IST on 18 Nov 2026 and never re-picked.",
  },
};

function inr(v: number | null | undefined, dp = 0): string {
  if (v == null || Number.isNaN(v)) return "₹-";
  return `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;
}

function signed(v: number | null | undefined): string {
  if (v == null) return "₹-";
  return `${v > 0 ? "+" : ""}${inr(v)}`;
}

function tone(v: number | null | undefined): string {
  return v == null || Math.abs(v) < 0.005 ? "" : v > 0 ? "gain" : "loss";
}

type Pair = { key: string; label: string; small?: Top10Summary; large?: Top10Summary };
type EachSet = { lo: number; hi: number; rows: { rank: number; s: Top10Summary }[] };

function sumOf(xs: Top10Summary[]) {
  const capital = xs.reduce((a, s) => a + s.desk_capital, 0);
  const equity = xs.reduce((a, s) => a + s.equity, 0);
  return {
    n: xs.length, capital, equity, pnl: equity - capital,
    roi: capital ? ((equity - capital) / capital) * 100 : 0,
    open: xs.reduce((a, s) => a + s.open_positions, 0),
    closed: xs.reduce((a, s) => a + s.closed_positions, 0),
  };
}

// "Top 5-10" is how the owner names Rank 6-10; the first set is "Top 1-5".
const setName = (lo: number, hi: number) => `Top ${lo === 1 ? 1 : lo - 1}-${hi}`;

// `initial` lets a render test show a loaded group; the page never passes it.
export default function PickedAccounts({ group, initial }: { group: PickedGroup; initial?: Accounts | null }) {
  const [data, setData] = useState<Accounts | null | undefined>(initial);   // undefined = loading, null = not on the server
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetchPickedAccounts("nifty-scalp", group));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the accounts");
    }
  }, [group]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // Pair each ₹2 lakh account with its ₹10 lakh twin; the server's order is band / pick order.
  const pairs = useMemo<Pair[]>(() => {
    const out: Pair[] = [];
    const byBase = new Map<string, Pair>();
    for (const a of data?.accounts ?? []) {
      const base = a.book.replace(/_(2L|10L)$/, "");
      let p = byBase.get(base);
      if (!p) {
        const label = a.label.replace(/ · ₹(2|10) lakh$/, "");
        p = { key: base, label };
        byBase.set(base, p);
        out.push(p);
      }
      if (a.book.endsWith("_2L")) p.small = a;
      else p.large = a;
    }
    return out;
  }, [data]);

  const totals = useMemo(() => {
    const sum = (pick: (p: Pair) => Top10Summary | undefined) => {
      const xs = pairs.map(pick).filter(Boolean) as Top10Summary[];
      const capital = xs.reduce((a, s) => a + s.desk_capital, 0);
      const equity = xs.reduce((a, s) => a + s.equity, 0);
      return {
        n: xs.length, capital, equity, pnl: equity - capital,
        roi: capital ? ((equity - capital) / capital) * 100 : 0,
        open: xs.reduce((a, s) => a + s.open_positions, 0),
        closed: xs.reduce((a, s) => a + s.closed_positions, 0),
      };
    };
    return { small: sum((p) => p.small), large: sum((p) => p.large) };
  }, [pairs]);

  // top25-each: the accounts in their five sets, by the Rank in the book key (each7_2L = #7, set 6-10).
  const sets = useMemo<EachSet[]>(() => {
    if (group !== "top25-each") return [];
    const out: EachSet[] = [];
    for (const a of data?.accounts ?? []) {
      const rank = Number(a.book.match(/^each(\d+)_/)?.[1] ?? 0);
      if (!rank) continue;
      const lo = Math.floor((rank - 1) / 5) * 5 + 1;
      let set = out.find((x) => x.lo === lo);
      if (!set) {
        set = { lo, hi: lo + 4, rows: [] };
        out.push(set);
      }
      set.rows.push({ rank, s: a });
    }
    out.sort((a, b) => a.lo - b.lo);
    for (const x of out) x.rows.sort((a, b) => a.rank - b.rank);
    return out;
  }, [data, group]);

  const intro = INTRO[group];

  if (data === null) {
    return (
      <GlassPanel title={intro.title}>
        <div className="pa-wait">
          These accounts are set up, but the server has not been updated with them yet. They start copying the desk
          on the first cycle after the backend is deployed — nothing is backfilled. Until then this tab shows nothing,
          so no other account&apos;s numbers can appear under these names.
        </div>
        <style jsx>{`
          .pa-wait { padding: 18px 20px; font-size: 12.5px; line-height: 1.55; color: var(--text-muted); }
        `}</style>
      </GlassPanel>
    );
  }

  const pick = (book: string) => setSel(sel === book ? null : book);

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}
      <GlassPanel
        title={`${intro.title} · ${data?.total ?? 0}`}
        note={data?.accounts?.[0]?.copying_since ? "paper · copying the desk's own trades" : "paper · starts on its first cycle"}
      >
        <div className="pa-intro">{intro.body}</div>
        {group === "top25-each" ? (
          <>
            <div className="pa-sets">
              {[{ key: "all", name: "All 25 accounts", sub: "", xs: sets.flatMap((x) => x.rows.map((r) => r.s)) },
                ...sets.map((x) => ({ key: String(x.lo), name: setName(x.lo, x.hi), sub: `Rank ${x.lo}-${x.hi}`,
                                      xs: x.rows.map((r) => r.s) }))].map((c) => {
                const t = sumOf(c.xs);
                return (
                  <div className="set" key={c.key}>
                    <div className="set-k">{c.name}{c.sub ? ` · ${c.sub}` : ""}</div>
                    <div className="set-v">{inr(t.equity)}</div>
                    <div className="set-s">
                      {t.n} accounts · {inr(t.capital)} in all ·{" "}
                      <span className={tone(t.pnl)}>
                        {signed(t.pnl)} ({t.roi >= 0 ? "+" : ""}
                        {t.roi.toFixed(2)}%)
                      </span>{" "}
                      · {t.open} open · {t.closed} closed
                    </div>
                  </div>
                );
              })}
            </div>
            {data === undefined ? (
              <div className="pa-load">Loading accounts…</div>
            ) : (
              <div className="pa-scroll">
                <table className="pa-table">
                  <thead>
                    <tr>
                      <th className="l">Set</th>
                      <th>Rank</th>
                      <th className="l">Strategy</th>
                      <th>₹2 lakh account</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sets.flatMap((x) =>
                      x.rows.map((r, i) => (
                        <tr key={r.s.book} className={i === 0 ? "set-first" : ""}>
                          {i === 0 && (
                            <td className="l band" rowSpan={x.rows.length}>
                              {setName(x.lo, x.hi)}
                              <span className="sub">Rank {x.lo}-{x.hi}</span>
                            </td>
                          )}
                          <td className="rk">#{r.rank}</td>
                          <td className="l picks" title={r.s.pick_rule ?? ""}>
                            {r.s.pick_names?.[0] ?? r.s.label}
                            <span className="sub">one slot · all-in a trade</span>
                          </td>
                          <td><AccountCell s={r.s} on={sel === r.s.book} onPick={pick} /></td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
        <>
        <div className="pa-sets">
          {(["small", "large"] as const).map((k) => {
            const t = totals[k];
            return (
              <div className="set" key={k}>
                <div className="set-k">{k === "small" ? "₹2 lakh accounts" : "₹10 lakh accounts"}</div>
                <div className="set-v">{inr(t.equity)}</div>
                <div className="set-s">
                  {t.n} accounts · {inr(t.capital)} in all ·{" "}
                  <span className={tone(t.pnl)}>
                    {signed(t.pnl)} ({t.roi >= 0 ? "+" : ""}
                    {t.roi.toFixed(2)}%)
                  </span>{" "}
                  · {t.open} open · {t.closed} closed
                </div>
              </div>
            );
          })}
        </div>
        {data === undefined ? (
          <div className="pa-load">Loading accounts…</div>
        ) : (
          <div className="pa-scroll">
            <table className="pa-table">
              <thead>
                <tr>
                  <th className="l">{group === "rank-band" ? "Band" : "Strategy"}</th>
                  <th className="l">Strategies</th>
                  <th>₹2 lakh account</th>
                  <th>₹10 lakh account</th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((p) => {
                  const s = p.small ?? p.large;
                  const names = s?.pick_names ?? [];
                  return (
                    <tr key={p.key}>
                      <td className="l band">{p.label}</td>
                      <td className="l picks" title={s?.pick_rule ?? ""}>
                        {group === "rank-band" ? (
                          <ol start={Number(p.label.match(/\d+/)?.[0] ?? 1)}>
                            {names.map((n) => <li key={n}>{n}</li>)}
                          </ol>
                        ) : (
                          <>
                            {names[0] ?? ""}
                            <span className="sub">one slot · all-in a trade</span>
                          </>
                        )}
                      </td>
                      <td><AccountCell s={p.small} on={sel === p.small?.book} onPick={pick} /></td>
                      <td><AccountCell s={p.large} on={sel === p.large?.book} onPick={pick} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        </>
        )}
        <div className="pa-foot">
          Click an account for its strategies, open and closed positions, charges and skips. Picked after the fact off a
          board where luck collects; none is validated — these accounts are the out-of-sample test.
        </div>
      </GlassPanel>

      {sel && <Top10Book key={sel} desk="nifty-scalp" book={sel as PickedBookKey} />}

      <style jsx>{`
        .pa-intro { padding: 14px 20px 0; font-size: 12.5px; line-height: 1.55; color: var(--text-muted); }
        .pa-sets { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; padding: 14px 20px 0; }
        .set { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; background: var(--canvas-soft); }
        .set-k { font-size: 10px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--text-faint); }
        .set-v { margin-top: 3px; font-size: 18px; font-weight: 800; font-family: var(--font-data, ui-monospace), monospace; color: var(--text); }
        .set-s { margin-top: 2px; font-size: 11.5px; color: var(--text-muted); line-height: 1.45; }
        .pa-load { padding: 18px 20px; font-size: 12px; color: var(--text-faint); }
        .pa-scroll { overflow-x: auto; padding: 12px 20px 4px; }
        .pa-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; min-width: 560px; }
        .pa-table th { padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
                       color: var(--text-muted); border-bottom: 1px solid var(--panel-border); text-align: center; }
        .pa-table td { padding: 6px 10px; border-bottom: 1px solid var(--canvas-soft); text-align: center; vertical-align: middle; }
        .pa-table .l { text-align: left; }
        .band { font-weight: 700; color: var(--text); white-space: nowrap; }
        .picks { font-size: 11px; color: var(--text-muted); line-height: 1.45; }
        .picks ol { margin: 0; padding-left: 22px; }
        .picks .sub, .band .sub { display: block; color: var(--text-faint); font-size: 10.5px; font-weight: 500; }
        .rk { font-weight: 700; color: var(--text-muted); white-space: nowrap; }
        .set-first td { border-top: 2px solid var(--panel-border); }
        .gain { color: var(--gain) !important; }
        .loss { color: var(--loss) !important; }
        .pa-foot { padding: 10px 20px 16px; font-size: 11px; line-height: 1.5; color: var(--text-faint); }
      `}</style>
    </>
  );
}

// Its own component so styled-jsx scopes the button: markup built in a helper function outside the
// returned tree gets no scope class and falls back to the browser's default button.
function AccountCell({ s, on, onPick }: { s?: Top10Summary; on: boolean; onPick: (book: string) => void }) {
  if (!s) return <span style={{ color: "var(--text-faint)" }}>—</span>;
  return (
    <button className={`acct ${on ? "on" : ""}`} onClick={() => onPick(s.book)} title={`Open ${s.label}`}>
      <span className="eq">{inr(s.equity)}</span>
      <span className={`roi ${tone(s.roi_pct)}`}>
        {s.roi_pct > 0 ? "+" : ""}
        {s.roi_pct.toFixed(2)}%
      </span>
      <span className="meta">
        {s.open_positions} open · {s.closed_positions} closed
      </span>
      <style jsx>{`
        .acct { display: inline-flex; flex-direction: column; align-items: center; gap: 1px; min-width: 150px;
                padding: 6px 10px; border-radius: 9px; cursor: pointer; border: 1px solid var(--panel-border);
                background: var(--panel); color: var(--text); font: inherit; }
        .acct:hover { border-color: rgba(var(--brand-rgb), .35); }
        .acct.on { border-color: var(--brand); background: var(--brand-dim); }
        .eq { font-weight: 700; font-family: var(--font-data, ui-monospace), monospace; }
        .roi { font-size: 11.5px; font-weight: 700; color: var(--text-muted); }
        .roi.gain { color: var(--gain); }
        .roi.loss { color: var(--loss); }
        .meta { font-size: 10.5px; color: var(--text-faint); }
      `}</style>
    </button>
  );
}
