"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchV2H1, type V2H1Report } from "../../lib/api";

const NAMES: Record<string, string> = {
  iv2_donchian_45m: "Donchian 20 breakout · 45m",
  iv2_donchian_1h: "Donchian 20 breakout · 1h",
  iv2_vwap_trend_1h: "VWAP reclaim · 1h",
};

const bp = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(2)} bp`);

/** H1: the one experiment that could change the Intraday Stocks verdict.
 *
 * Over two years these three strategies had a real edge BEFORE friction — and lost after
 * it, because slippage is modelled at ~2.76 bp a side. Each breaks even if real slippage on
 * a Rs 10 lakh order is below its own number. This panel shows that number being measured
 * from Angel's order book at every signal, against a rule written down before measuring. */
export default function H1Panel() {
  const [r, setR] = useState<V2H1Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setR(await fetchV2H1());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load H1");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (err) return <div className="h1 h1-err">H1 measurement unavailable: {err}</div>;
  if (!r) return null;
  const rule = r.preregistration;

  return (
    <div className="h1">
      <div className="h1-head">
        <b>H1 · what a ₹{(rule.notional_rs / 1e5).toFixed(0)} lakh order really costs</b>
        <span className="h1-sub">
          measured from Angel&apos;s order book at every signal — no order is placed
        </span>
      </div>
      <p className="h1-why">
        These three strategies had a real edge before friction over two years and lost after it,
        because slippage is <em>modelled</em> at about 2.76 bp a side. Each breaks even only if a
        real ₹10 lakh order costs less than its number below. The rule was written down before
        the first sample: <b>GO</b> if the median measured cost is at most{" "}
        {Math.round(rule.go_fraction_of_break_even * 100)}% of break-even over at least{" "}
        {rule.min_samples_per_strategy} signals. A GO earns a forward paper test, not real money.
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Strategy</th>
              <th>Break-even</th>
              <th>GO if ≤</th>
              <th>Signals</th>
              <th>Median cost</th>
              <th>Middle half</th>
              <th>Half-spread</th>
              <th>Book too thin</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(r.strategies).map(([sid, s]) => (
              <tr key={sid}>
                <td style={{ textAlign: "left" }}>{NAMES[sid] ?? sid}</td>
                <td>{bp(s.break_even_bp)}</td>
                <td>{bp(s.threshold_bp)}</td>
                <td>
                  {s.n} / {rule.min_samples_per_strategy}
                  <div className="h1-bar"><span style={{ width: `${s.progress_pct}%` }} /></div>
                </td>
                <td className={s.median_bp == null ? "" : s.median_bp <= s.threshold_bp ? "gain" : "loss"}>
                  {bp(s.median_bp)}
                </td>
                <td>{s.p25_bp == null ? "—" : `${s.p25_bp.toFixed(2)} – ${s.p75_bp?.toFixed(2)}`}</td>
                <td>{bp(s.median_half_spread_bp)}</td>
                <td>{s.n ? `${Math.round(s.insufficient_share * 100)}%` : "—"}</td>
                <td><span className={`pill h1-${s.status.toLowerCase()}`}>{s.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="h1-foot">
        Pre-registered {rule.written}
        {r.fingerprint ? ` · fingerprint ${r.fingerprint}` : " · not yet stored"}
        {r.fingerprint && !r.code_matches_stored ? " · the code's rule differs; the stored rule governs" : ""}
        {r.unmeasurable ? ` · ${r.unmeasurable} signal(s) the book could not price` : ""}
      </div>
      <style jsx>{`
        .h1 { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--panel-border); }
        .h1-err { font-size: 12px; color: var(--text-faint); }
        .h1-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; font-size: 13.5px; }
        .h1-sub { font-size: 11.5px; color: var(--text-muted); }
        .h1-why { margin: 6px 0 10px; font-size: 12px; line-height: 1.6; color: var(--text-muted); }
        .h1-bar { height: 3px; margin-top: 4px; border-radius: 2px; background: var(--canvas-soft); overflow: hidden; }
        .h1-bar span { display: block; height: 100%; background: var(--text-muted); }
        .h1-foot { margin-top: 8px; font-size: 10.5px; color: var(--text-faint); }
        .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10.5px; font-weight: 700;
                background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .h1-go { color: var(--gain); }
        .h1-no-go { color: var(--loss); }
        .h1-collecting { color: var(--text-muted); }
        .table-scroll { overflow-x: auto; }
        .data-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
        .data-table th { text-align: center; padding: 8px 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
                         text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--panel-border); }
        .data-table td { padding: 7px 10px; text-align: center; border-bottom: 1px solid var(--canvas-soft); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
