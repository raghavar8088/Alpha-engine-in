"use client";

// Strategy cards for the Booming Bulls and YouTube top-20 studies. Rules and results come from ./library.ts (generated
// from the studies' pre-registrations and saved hold-out tests); the paper figures come from the live desk.
import type { Account } from "./PaperDesk";
import { LIBRARY, type LibStrategy } from "./library";
import { num, pct, rupees, tone } from "./format";

const PILL: Record<string, string> = { "Paper test only": "ps-pill-neutral", "Not supported": "ps-pill-loss", "Needs more evidence": "ps-pill-warn", "Too few trades to judge": "ps-pill-neutral", "Not tested": "ps-pill-neutral" };

export function PaperLine({ a }: { a?: Account }) {
  if (!a) return null;
  const traded = a.closed + a.open;
  return (
    <div className="pd-paper">
      <span className="ps-stat-label">Paper account</span>
      {traded ? (
        <span>{rupees(a.equity)} <b className={tone(a.return_pct)}>{pct(a.return_pct)}</b> · {traded} {traded === 1 ? "trade" : "trades"}</span>
      ) : (
        <span>{rupees(a.equity)} · no trades yet</span>
      )}
    </div>
  );
}

function Card({ s, account }: { s: LibStrategy; account?: Account }) {
  return (
    <div className="ps-card">
      <div className="ps-card-top">
        <span className="ps-fam up">{s.id}</span>
        <span className={`ps-pill ${PILL[s.verdict] ?? "ps-pill-neutral"}`}>{s.verdict}</span>
      </div>
      <div className="ps-card-name">{s.name}</div>
      <div className="ps-card-idea">{s.channel}</div>
      {s.source === "crypto_playlist" || s.source === "sniper_headshot" || s.source === "youtube_channels11" ? (
        <div className="pd-paper">
          <span className="ps-stat-label">Markets</span>
          <span>{s.books.map((b) => b.market).join(", ")} · not backtested</span>
        </div>
      ) : (
      <div className="pd-books">
        <table className="ps-table">
          <thead><tr><th>Market</th><th title="Net result per trade on data held back from the design, in R (R = result ÷ the risk at entry)">Hold-out</th><th>Trades</th></tr></thead>
          <tbody>
            {s.books.map((b) => (
              <tr key={b.market}>
                <td className="ps-name">{b.market}</td>
                <td className={tone(b.meanR)}>{b.meanR == null ? "—" : `${num(b.meanR, 2)}R`}</td>
                <td>{b.n == null ? "—" : b.n.toLocaleString("en-US")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
      <PaperLine a={account} />
      <details className="ps-rules">
        <summary>Exact rules</summary>
        <dl>
          {s.rules.map((r, i) => (
            <div key={i} className={r.label ? "ps-rule" : "pd-rule-plain"}>
              {r.label && <dt>{r.label}</dt>}
              <dd>{r.text}</dd>
            </div>
          ))}
          {s.source !== "crypto_playlist" && s.source !== "sniper_headshot" && s.source !== "youtube_channels11" && (
            <div className="ps-rule">
              <dt>Variant traded</dt>
              <dd>{s.books.map((b) => `${b.market}: ${b.variant}${b.change && b.variant !== "V0" ? ` (${b.change})` : ""}`).join("; ")}</dd>
            </div>
          )}
          {s.videos.length > 0 && (
            <div className="ps-rule">
              <dt>Source</dt>
              <dd>
                {s.videos.map((v, i) => (
                  <span key={v}>{i > 0 && ", "}<a href={`https://www.youtube.com/watch?v=${v}`} target="_blank" rel="noreferrer">{v}</a></span>
                ))}
              </dd>
            </div>
          )}
        </dl>
      </details>
    </div>
  );
}

export default function LibraryCards({ source, accounts }: { source: "booming_bulls" | "youtube_top20" | "crypto_playlist" | "liquidity_sweep" | "sniper_headshot" | "youtube_channels11"; accounts: Record<string, Account> }) {
  return (
    <div className="ps-cards">
      {LIBRARY.filter((s) => s.source === source).map((s) => <Card key={s.id} s={s} account={accounts[s.id]} />)}
    </div>
  );
}
