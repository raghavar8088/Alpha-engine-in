"use client";

// Index Option Buying: the Strategy Factory tab's Rank-band paper accounts (17 Nov 2026), side by side. Ten bands of
// the tab's Rank - 1-5, 6-10 ... 46-50 - each in a ₹2 lakh and a ₹10 lakh account (sfb1_5_2L ... sfb46_50_10L): one
// row per band with its two accounts; a click opens that account in full (PickBook).
// Backend: app.services.prelive_pick_books (Book.group "sf-bands"), GET /api/prelive-pick-books/accounts?group=sf-bands.
// Paper only: nothing here places an order.

import { useCallback, useEffect, useMemo, useState } from "react";
import GlassPanel from "./GlassPanel";
import ErrorBanner from "./ErrorBanner";
import PickBook from "./PickBook";
import { PickBookAccounts, PickBookKey, PickBookSummary, fetchPickBookAccounts } from "../lib/prelivePickBooks";

const REFRESH_MS = 30000;

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

type Band = { key: string; lo: number; hi: number; small?: PickBookSummary; large?: PickBookSummary };

export default function PickBookBands() {
  const [data, setData] = useState<PickBookAccounts | null | undefined>(undefined);   // undefined = loading, null = not on the server
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetchPickBookAccounts("sf-bands"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the accounts");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // Pair each band's ₹2 lakh account with its ₹10 lakh twin; the server's order is band order.
  const bands = useMemo<Band[]>(() => {
    const out: Band[] = [];
    const byBase = new Map<string, Band>();
    for (const a of data?.accounts ?? []) {
      const m = a.book.match(/^sfb(\d+)_(\d+)_(2L|10L)$/);
      if (!m) continue;
      const base = `sfb${m[1]}_${m[2]}`;
      let b = byBase.get(base);
      if (!b) {
        b = { key: base, lo: Number(m[1]), hi: Number(m[2]) };
        byBase.set(base, b);
        out.push(b);
      }
      if (m[3] === "2L") b.small = a;
      else b.large = a;
    }
    return out;
  }, [data]);

  const totals = useMemo(() => {
    const sum = (pick: (b: Band) => PickBookSummary | undefined) => {
      const xs = bands.map(pick).filter(Boolean) as PickBookSummary[];
      const capital = xs.reduce((a, s) => a + s.desk_capital, 0);
      const equity = xs.reduce((a, s) => a + s.equity, 0);
      return {
        n: xs.length, capital, equity, pnl: equity - capital,
        roi: capital ? ((equity - capital) / capital) * 100 : 0,
        open: xs.reduce((a, s) => a + s.open_positions, 0),
        closed: xs.reduce((a, s) => a + s.closed_positions, 0),
      };
    };
    return { small: sum((b) => b.small), large: sum((b) => b.large) };
  }, [bands]);

  const pickedAt = data?.accounts?.[0]?.picked_at;
  const pickedOn = pickedAt
    ? new Date(pickedAt).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "17 Nov 2026";

  if (data === null) {
    return (
      <GlassPanel title="Strategy Factory Rank bands">
        <div className="pb-wait">
          These twenty accounts are set up, but the server has not been updated with them yet. They start copying the
          Strategy Factory tab on the first cycle after the backend is deployed — nothing is backfilled. Until then this
          tab shows nothing, so no other account&apos;s numbers can appear under these names.
        </div>
        <style jsx>{`
          .pb-wait { padding: 18px 20px; font-size: 12.5px; line-height: 1.55; color: var(--text-muted); }
        `}</style>
      </GlassPanel>
    );
  }

  const pick = (book: string) => setSel(sel === book ? null : book);

  return (
    <>
      {error && <ErrorBanner message={error} onRetry={load} />}
      <GlassPanel
        title={`Strategy Factory Rank bands · ${data?.total ?? 20} accounts`}
        note={data?.accounts?.[0]?.copying_since ? "paper · copying the tab's own trades" : "paper · starts on its first cycle"}
      >
        <div className="pb-intro">
          The Strategy Factory tab&apos;s Rank in ten bands of five — Top 1-5, 5-10 … 45-50 (ranks 1-5, 6-10 … 46-50) — each
          copied into a ₹2 lakh and a ₹10 lakh paper account. An account holds its five strategies with a slot each, a
          fifth of the account per position (₹40,000 or ₹2,00,000), and takes the tab&apos;s own entries and exits; it
          never holds two positions in one contract. The fifty were frozen from the board at {pickedOn} and are never
          re-picked.
        </div>
        <div className="pb-sets">
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
          <div className="pb-load">Loading accounts…</div>
        ) : (
          <div className="pb-scroll">
            <table className="pb-table">
              <thead>
                <tr>
                  <th className="l">Band</th>
                  <th className="l">Strategies</th>
                  <th>₹2 lakh account</th>
                  <th>₹10 lakh account</th>
                </tr>
              </thead>
              <tbody>
                {bands.map((b) => {
                  const s = b.small ?? b.large;
                  const names = s?.pick_names ?? [];
                  return (
                    <tr key={b.key}>
                      <td className="l band">
                        Top {b.lo === 1 ? 1 : b.lo - 1}-{b.hi}
                        <span className="sub">Rank {b.lo}-{b.hi}</span>
                      </td>
                      <td className="l picks" title={s?.pick_rule ?? ""}>
                        <ol start={b.lo}>
                          {names.map((n) => <li key={n}>{n}</li>)}
                        </ol>
                      </td>
                      <td><AccountCell s={b.small} on={sel === b.small?.book} onPick={pick} /></td>
                      <td><AccountCell s={b.large} on={sel === b.large?.book} onPick={pick} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="pb-foot">
          Click an account for its strategies, open and closed positions, charges and skips. Picked after the fact off a
          board where luck collects, many on fewer than ten trades; none is validated — these accounts are the
          out-of-sample test.
        </div>
      </GlassPanel>

      {sel && <PickBook key={sel} book={sel as PickBookKey} />}

      <style jsx>{`
        .pb-intro { padding: 14px 20px 0; font-size: 12.5px; line-height: 1.55; color: var(--text-muted); }
        .pb-sets { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; padding: 14px 20px 0; }
        .set { border: 1px solid var(--panel-border); border-radius: 10px; padding: 10px 14px; background: var(--canvas-soft); }
        .set-k { font-size: 10px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--text-faint); }
        .set-v { margin-top: 3px; font-size: 18px; font-weight: 800; font-family: var(--font-data, ui-monospace), monospace; color: var(--text); }
        .set-s { margin-top: 2px; font-size: 11.5px; color: var(--text-muted); line-height: 1.45; }
        .pb-load { padding: 18px 20px; font-size: 12px; color: var(--text-faint); }
        .pb-scroll { overflow-x: auto; padding: 12px 20px 4px; }
        .pb-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; min-width: 560px; }
        .pb-table th { padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
                       color: var(--text-muted); border-bottom: 1px solid var(--panel-border); text-align: center; }
        .pb-table td { padding: 6px 10px; border-bottom: 1px solid var(--canvas-soft); text-align: center; vertical-align: middle; }
        .pb-table .l { text-align: left; }
        .band { font-weight: 700; color: var(--text); white-space: nowrap; }
        .band .sub { display: block; font-weight: 500; font-size: 10.5px; color: var(--text-faint); }
        .picks { font-size: 11px; color: var(--text-muted); line-height: 1.45; }
        .picks ol { margin: 0; padding-left: 22px; }
        .gain { color: var(--gain) !important; }
        .loss { color: var(--loss) !important; }
        .pb-foot { padding: 10px 20px 16px; font-size: 11px; line-height: 1.5; color: var(--text-faint); }
      `}</style>
    </>
  );
}

// Its own component so styled-jsx scopes the button: markup built in a helper function outside the
// returned tree gets no scope class and falls back to the browser's default button.
function AccountCell({ s, on, onPick }: { s?: PickBookSummary; on: boolean; onPick: (book: string) => void }) {
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
