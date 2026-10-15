"use client";

/**
 * "Reset account" for one paper book on Intraday Stocks (Paper Trade ₹50k / ₹2 lakh and
 * Live Intraday ₹80k / ₹30k / ₹10k). A reset deletes the book's whole paper record — open and
 * closed positions, trades, strategy scores, equity — so it restarts at its capital. The server
 * keeps a backup of everything it deletes and refuses unless RESET is typed. Paper only: these
 * books never place an order.
 */

import { useEffect, useState } from "react";
import {
  type BookResetInfo,
  type BookResetPreview,
  type ResettableDesk,
  fetchBookResetPreview,
  fetchBookResets,
  resetBook,
} from "../../lib/api";

const WHAT: [string, string][] = [
  ["_trades", "trades"],
  ["_positions", "positions"],
  ["_scores", "strategy scores"],
  ["_equity", "equity snapshots"],
];

function describe(counts: Record<string, number> | null | undefined): string {
  if (!counts) return "";
  return WHAT.map(([suffix, name]) => {
    const key = Object.keys(counts).find((k) => k.endsWith(suffix));
    return key !== undefined ? `${counts[key].toLocaleString("en-IN")} ${name}` : null;
  }).filter(Boolean).join(", ");
}

export default function ResetBook({
  desk, book, label, capital, onDone,
}: {
  desk: ResettableDesk;
  book: string;
  label: string;
  capital?: number | null;
  onDone: () => void | Promise<void>;
}) {
  const [last, setLast] = useState<BookResetInfo | null>(null);
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<BookResetPreview | null>(null);
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setOpen(false);
    setWord("");
    setMsg(null);
    setPreview(null);
    fetchBookResets(desk).then((r) => { if (alive) setLast(r[book] ?? null); }).catch(() => {});
    return () => { alive = false; };
  }, [desk, book]);

  const start = async () => {
    setOpen(true);
    setMsg(null);
    try {
      setPreview(await fetchBookResetPreview(desk, book));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not read what a reset would delete");
    }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const r = await resetBook(desk, book, word);
      setLast(r);
      setOpen(false);
      setWord("");
      setMsg(`Reset done — deleted ${describe(r.deleted)}. A backup is kept on the server.`);
      await onDone();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  const openCount = preview?.counts.open_positions ?? 0;

  return (
    <div className="reset-book">
      <div className="reset-row">
        <span className="reset-last">
          {last
            ? `Last reset ${new Date(last.at).toLocaleString()} — ${describe(last.deleted)} cleared`
            : "Never reset — this record runs from the book's first trade."}
        </span>
        {!open && (
          <button type="button" className="reset-btn" onClick={start}>Reset account</button>
        )}
      </div>
      {open && (
        <div className="reset-confirm" role="alertdialog" aria-label={`Reset ${label}`}>
          <div>
            <b>Reset {label}?</b>{" "}This permanently deletes the book&apos;s paper record
            {preview ? ` — ${describe(preview.counts)}` : ""}
            {openCount ? `, including ${openCount} open position${openCount === 1 ? "" : "s"}` : ""} — and restarts it
            {capital ? ` at ₹${Math.round(capital).toLocaleString("en-IN")}` : " at its starting capital"}.
            Paper only: no real order or real money is affected, and the server keeps a backup of what it deletes.
          </div>
          <div className="reset-actions">
            <input
              value={word}
              onChange={(e) => setWord(e.target.value)}
              placeholder="type RESET"
              aria-label="Type RESET to confirm"
              autoFocus
            />
            <button type="button" className="reset-go" disabled={busy || word.trim().toUpperCase() !== "RESET"} onClick={confirm}>
              {busy ? "Resetting…" : "Delete history and restart"}
            </button>
            <button type="button" className="reset-cancel" disabled={busy} onClick={() => { setOpen(false); setWord(""); }}>Cancel</button>
          </div>
        </div>
      )}
      {msg && <div className="reset-msg">{msg}</div>}
      <style jsx>{`
        .reset-book { display: flex; flex-direction: column; gap: 8px; }
        .reset-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .reset-last { font-size: 11.5px; color: var(--text-muted); }
        .reset-btn { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 8px; cursor: pointer; background: var(--panel); color: var(--loss); border: 1px solid var(--panel-border); }
        .reset-btn:hover { background: var(--loss-dim); }
        .reset-confirm { display: flex; flex-direction: column; gap: 10px; font-size: 12.5px; line-height: 1.55; color: var(--text); padding: 12px 14px; border-radius: 10px; background: var(--loss-dim); border: 1px solid var(--panel-border); }
        .reset-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
        .reset-actions input { font-size: 12px; padding: 6px 8px; border-radius: 8px; border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); width: 130px; }
        .reset-go { font-size: 12px; font-weight: 700; padding: 6px 12px; border-radius: 8px; cursor: pointer; background: var(--loss); color: #fff; border: 1px solid var(--loss); }
        .reset-go:disabled { opacity: 0.45; cursor: not-allowed; }
        .reset-cancel { font-size: 12px; padding: 6px 12px; border-radius: 8px; cursor: pointer; background: var(--panel); color: var(--text); border: 1px solid var(--panel-border); }
        .reset-msg { font-size: 11.5px; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
