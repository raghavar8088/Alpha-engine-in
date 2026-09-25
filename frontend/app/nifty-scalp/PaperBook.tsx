"use client";

/* The ₹2,00,000 paper book that sits under the 504-strategy scalping desk.
 *
 * Its own file, and its own loading, deliberately. The desk page bootstraps through one
 * `Promise.all`, and that page has already been bitten once by exactly that: a single slow
 * call rejected the group and blanked the whole screen even though the rest had answered.
 * A paper book that fails should cost its own tab and nothing else. */

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import ErrorBanner from "../../components/ErrorBanner";
import {
  fetchNiftyScalpPaperSummary,
  fetchNiftyScalpPaperRoster,
  fetchNiftyScalpPaperPositions,
  setNiftyScalpPaperRoster,
  type NiftyScalpPaperSummary,
  type NiftyScalpPaperRosterRow,
  type NiftyScalpPosition,
  type NiftyScalpScore,
} from "../../lib/api";

const REFRESH_MS = 30000;

const inr = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const inr2 = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const roiPct = (v: number | null | undefined, dp = 2) =>
  `${(v ?? 0) >= 0 ? "+" : ""}${(v ?? 0).toFixed(dp)}%`;
const cls = (v: number | null | undefined) => ((v ?? 0) >= 0 ? "gain" : "loss");

export default function PaperBook({ board }: { board: NiftyScalpScore[] }) {
  const [sum, setSum] = useState<NiftyScalpPaperSummary | null>(null);
  const [roster, setRoster] = useState<NiftyScalpPaperRosterRow[]>([]);
  const [open, setOpen] = useState<NiftyScalpPosition[]>([]);
  const [closed, setClosed] = useState<NiftyScalpPosition[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, r, o, c] = await Promise.all([
        fetchNiftyScalpPaperSummary(),
        fetchNiftyScalpPaperRoster(),
        fetchNiftyScalpPaperPositions("OPEN"),
        fetchNiftyScalpPaperPositions("CLOSED"),
      ]);
      setSum(s);
      setRoster(r);
      setOpen(o);
      setClosed(c);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load the paper book");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const save = async (ids: string[]) => {
    if (busy) return;
    setBusy(true);
    try {
      await setNiftyScalpPaperRoster(ids);
      await load();
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the roster");
    } finally {
      setBusy(false);
    }
  };

  const ids = roster.map((r) => r.strategy_id);
  const onRoster = new Set(ids);
  // Offer the desk's best first. The roster is chosen off that ranking, so making someone
  // scroll past 490 losers to find the next candidate would be perverse.
  const candidates = board.filter((b) => !onRoster.has(b.strategy_id)).slice(0, 60);

  const remove = (sid: string) => {
    if (ids.length <= 1) {
      setErr("A book needs at least one strategy. Add another before removing this one.");
      return;
    }
    save(ids.filter((x) => x !== sid));
  };

  return (
    <>
      {err && <ErrorBanner message={err} />}

      <div className="banner">
        <strong>ONE BOOK, NOT ₹2 LAKH EACH.</strong> The desk above funds every one of its
        504 strategies with its own ₹2,00,000, so nothing there ever competes for cash.
        Here {sum?.roster_size ?? roster.length} picked strategies share a single{" "}
        <strong>₹{inr(sum?.book_capital)}</strong> — about{" "}
        <strong>₹{inr(sum?.slice_per_strategy)}</strong> of target size each, one lot
        minimum, and a signal that arrives when the book is fully deployed is{" "}
        <em>skipped and said so</em> rather than quietly dropped. Same rules, same live
        Angel prices, same real F&amp;O costs as the desk.
        <br />
        <br />
        <strong>Read the record here, not the one that got them picked.</strong> These were
        chosen after the fact as the best of 504, on a desk whose own ROI was −15%, with
        4–19 trades each. The best dozen of 504 look excellent on luck alone. This book is
        the out-of-sample test of that choice — until it has its own trades behind it, it
        is a hypothesis, not a result.
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Book capital</div>
          <div className="tile-value">₹{inr(sum?.book_capital)}</div>
          <div className="tile-sub">{sum?.roster_size ?? 0} strategies sharing it</div>
        </div>
        <div className="tile">
          <div className="tile-label">Equity</div>
          <div className="tile-value">₹{inr(sum?.equity)}</div>
          <div className="tile-sub">₹{inr(sum?.unrealized_pnl)} unrealised</div>
        </div>
        <div className="tile">
          <div className="tile-label">ROI</div>
          <div className={`tile-value ${cls(sum?.roi_pct)}`}>{roiPct(sum?.roi_pct, 3)}</div>
          <div className="tile-sub">on the whole ₹{inr(sum?.book_capital)}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Today P&amp;L</div>
          <div className={`tile-value ${cls(sum?.today_pnl)}`}>
            {(sum?.today_pnl ?? 0) >= 0 ? "+" : ""}₹{inr(sum?.today_pnl)}
          </div>
          <div className="tile-sub">
            {sum?.breaker_tripped
              ? "BREAKER TRIPPED — no new entries today"
              : `breaker at ₹${inr(sum?.daily_loss_limit)}`}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Available cash</div>
          <div className="tile-value">₹{inr(sum?.available_cash)}</div>
          <div className="tile-sub">₹{inr(sum?.deployed_capital)} deployed</div>
        </div>
        <div className="tile">
          <div className="tile-label">Angel F&amp;O fees</div>
          <div className="tile-value loss">−₹{inr(sum?.total_fees)}</div>
          <div className="tile-sub">gross ₹{inr(sum?.gross_realized_pnl)} before costs</div>
        </div>
        <div className="tile">
          <div className="tile-label">Open positions</div>
          <div className="tile-value">{sum?.open_positions ?? 0}</div>
          <div className="tile-sub">{sum?.closed_positions ?? 0} closed</div>
        </div>
        <div className="tile">
          <div className="tile-label">Mode</div>
          <div className="tile-value gain">PAPER</div>
          <div className="tile-sub">{sum?.enabled ? "armed · live Angel feed" : "disabled"}</div>
        </div>
      </div>

      <GlassPanel
        title={`The roster · ${roster.length} strategies`}
        note={`₹${inr(sum?.slice_per_strategy)} target each`}
      >
        <div className="rosterbar">
          <select value={pick} onChange={(e) => setPick(e.target.value)} disabled={busy}>
            <option value="">Add a strategy from the desk leaderboard…</option>
            {candidates.map((b) => (
              <option key={b.strategy_id} value={b.strategy_id}>
                {b.template} · {b.timeframe} — {b.trades} trades, {roiPct(b.roi_pct, 1)}
              </option>
            ))}
          </select>
          <button
            className="chip active"
            disabled={!pick || busy}
            onClick={() => {
              save([...ids, pick]);
              setPick("");
            }}
          >
            {busy ? "Saving…" : "Add to book"}
          </button>
          <span className="sub">
            Adding a strategy makes every slice smaller — the book stays at ₹
            {inr(sum?.book_capital)}.
          </span>
        </div>

        {!roster.length ? (
          <div className="empty">No strategies on the book.</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th>TF</th>
                  <th>Style</th>
                  <th>Slice</th>
                  <th>Trades</th>
                  <th>Win %</th>
                  <th>Fees</th>
                  <th>Net P&amp;L</th>
                  <th>ROI on slice</th>
                  <th>On the desk</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {roster.map((r) => (
                  <tr key={r.strategy_id}>
                    <td style={{ textAlign: "left" }}>{r.template}</td>
                    <td>
                      <span className="badge">{r.timeframe}</span>
                    </td>
                    <td style={{ fontSize: 11 }}>{r.style}</td>
                    <td>₹{inr(r.slice)}</td>
                    <td>{r.trades}</td>
                    <td>{r.trades ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                    <td className="loss">−₹{inr(r.fees)}</td>
                    <td className={cls(r.net_pnl)}>
                      {r.net_pnl >= 0 ? "+" : ""}₹{inr(r.net_pnl)}
                    </td>
                    <td className={cls(r.roi_pct)}>{r.trades ? roiPct(r.roi_pct, 2) : "—"}</td>
                    {/* The record that got it picked, kept beside the record it is earning
                        here. The gap between these two columns IS the experiment. */}
                    <td className="sub">
                      {r.desk_trades} trades ·{" "}
                      <span className={cls(r.desk_roi_pct)}>{roiPct(r.desk_roi_pct, 1)}</span>
                    </td>
                    <td>
                      <button className="chip" disabled={busy} onClick={() => remove(r.strategy_id)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassPanel>

      <GlassPanel title={`Open on the book (${open.length})`}>
        {!open.length ? (
          <div className="empty">
            Nothing open. Entries run during market hours up to 15:05 IST, and only when a
            rostered strategy fires on a freshly closed bar.
          </div>
        ) : (
          <PaperPositions rows={open} live />
        )}
      </GlassPanel>

      <GlassPanel title={`Closed on the book (${closed.length})`} note="net of real Angel F&O costs">
        {!closed.length ? (
          <div className="empty">No closed trades yet.</div>
        ) : (
          <PaperPositions rows={closed} />
        )}
      </GlassPanel>

      <style jsx>{`
        .banner {
          background: var(--canvas-edge);
          border: 1px solid var(--panel-border);
          border-radius: 12px;
          padding: 12px 16px;
          font-size: 12px;
          line-height: 1.7;
          color: var(--text-muted);
        }
        .tiles {
          display: grid;
          gap: 12px;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          margin: 16px 0;
        }
        .tile {
          padding: 12px 14px;
          border-radius: 10px;
          background: var(--panel);
          border: 1px solid var(--panel-border);
        }
        .tile-label {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: var(--text-muted);
        }
        .tile-value {
          margin-top: 5px;
          font-size: 19px;
          font-weight: 700;
          font-variant-numeric: tabular-nums;
        }
        .tile-sub {
          margin-top: 3px;
          font-size: 10.5px;
          color: var(--text-faint);
          line-height: 1.4;
        }
        .rosterbar {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          padding: 4px 2px 12px;
        }
        .rosterbar select {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text);
          padding: 7px 10px;
          border-radius: 8px;
          font-size: 12px;
          max-width: 420px;
        }
        .chip {
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
          color: var(--text-muted);
          padding: 5px 12px;
          border-radius: 999px;
          cursor: pointer;
          font-size: 11.5px;
          font-weight: 600;
        }
        .chip.active {
          background: var(--purple-dim);
          border-color: rgba(125, 52, 220, 0.3);
          color: var(--purple);
        }
        .chip:disabled {
          opacity: 0.45;
          cursor: default;
        }
        .table-scroll {
          overflow-x: auto;
          max-height: 460px;
          overflow-y: auto;
        }
        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
          font-variant-numeric: tabular-nums;
        }
        .data-table th {
          text-align: center;
          padding: 8px 10px;
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: var(--text-muted);
          border-bottom: 1px solid var(--panel-border);
          position: sticky;
          top: 0;
          background: var(--panel);
        }
        .data-table td {
          padding: 7px 10px;
          text-align: center;
          border-bottom: 1px solid var(--canvas-soft);
        }
        .badge {
          display: inline-block;
          padding: 3px 8px;
          border-radius: 6px;
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.05em;
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .empty {
          padding: 18px 20px;
          font-size: 12px;
          color: var(--text-faint);
          text-align: center;
        }
        .sub {
          font-size: 10.5px;
          color: var(--text-faint);
        }
        .gain {
          color: var(--gain);
        }
        .loss {
          color: var(--loss);
        }
      `}</style>
    </>
  );
}

function PaperPositions({ rows, live }: { rows: NiftyScalpPosition[]; live?: boolean }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Strategy</th>
            <th>TF</th>
            <th>Option</th>
            <th>Dir</th>
            <th>Lots</th>
            <th>Deployed</th>
            <th>Entry</th>
            <th>{live ? "LTP" : "Exit"}</th>
            <th>Target</th>
            <th>Stop</th>
            <th>{live ? "Unrealised" : "Net P&L"}</th>
            {!live && <th>Fees</th>}
            {!live && <th>Why</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.position_id}>
              <td style={{ textAlign: "left", fontSize: 11 }}>{p.template}</td>
              <td>
                <span className="badge">{p.timeframe}</span>
              </td>
              <td style={{ fontSize: 11 }}>
                {p.strike} {p.option_type}
              </td>
              <td>
                <span className={p.direction === "BEARISH" ? "badge loss" : "badge"}>
                  {p.direction === "BEARISH" ? "PUT" : "CALL"}
                </span>
              </td>
              <td>{p.lots}</td>
              <td>₹{inr(p.capital_deployed)}</td>
              <td>₹{inr2(p.entry_premium)}</td>
              <td>₹{inr2(live ? p.ltp : p.exit_premium)}</td>
              <td>₹{inr2(p.target_premium)}</td>
              <td>₹{inr2(p.stop_premium)}</td>
              <td className={cls(live ? p.unrealized_pnl : p.realized_pnl)}>
                {((live ? p.unrealized_pnl : p.realized_pnl) ?? 0) >= 0 ? "+" : ""}₹
                {inr(live ? p.unrealized_pnl : p.realized_pnl)}
              </td>
              {!live && <td className="loss">−₹{inr(p.fees)}</td>}
              {!live && <td style={{ fontSize: 11 }}>{p.exit_reason}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      <style jsx>{`
        .table-scroll {
          overflow-x: auto;
          max-height: 460px;
          overflow-y: auto;
        }
        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
          font-variant-numeric: tabular-nums;
        }
        .data-table th {
          text-align: center;
          padding: 8px 10px;
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: var(--text-muted);
          border-bottom: 1px solid var(--panel-border);
          position: sticky;
          top: 0;
          background: var(--panel);
        }
        .data-table td {
          padding: 7px 10px;
          text-align: center;
          border-bottom: 1px solid var(--canvas-soft);
        }
        .badge {
          display: inline-block;
          padding: 3px 8px;
          border-radius: 6px;
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.05em;
          background: var(--canvas-soft);
          border: 1px solid var(--panel-border);
        }
        .badge.loss {
          background: var(--loss-dim);
          border-color: rgba(217, 45, 63, 0.3);
        }
        .gain {
          color: var(--gain);
        }
        .loss {
          color: var(--loss);
        }
      `}</style>
    </div>
  );
}
