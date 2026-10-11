"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchGoldCosts, type GoldCosts } from "../../lib/api";

const bp = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toFixed(d)} bp`;

/** What trading here really costs — measured, not assumed.
 *
 * The desk used to charge a guessed 5 bp a side on both venues. The research measured the books:
 * GOLDM's median quoted spread is ~1.3 bp, and one H1 sleeve crosses XAUTUSD's book for a few
 * hundredths of a basis point. This panel shows the venues' own fee rates and the spreads and
 * funding the desk's monitors keep measuring (the Delta book every 5 minutes, MCX quotes as the
 * commodity desks read them). */
export default function GoldCostsPanel() {
  const [c, setC] = useState<GoldCosts | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setC(await fetchGoldCosts());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load costs");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (err) return <div className="muted">Costs unavailable: {err}</div>;
  if (!c) return null;
  const d = c.delta;
  const m = c.mcx;

  return (
    <div className="costs">
      <div className="venue">
        <div className="vh">Delta · {d?.symbol ?? "XAUTUSD"}</div>
        {d?.error ? (
          <div className="muted">{d.error}</div>
        ) : (
          <ul>
            <li>
              <span>Fee</span>
              <b>
                {d?.taker_fee_pct?.toFixed(3)}% taker · {d?.maker_fee_pct?.toFixed(3)}% maker + {d?.gst_pct?.toFixed(0)}% GST
              </b>
            </li>
            <li>
              <span>Round trip, fees</span>
              <b>{bp(d?.round_trip_fee_bp)}</b>
            </li>
            <li>
              <span>Quoted spread (30 d)</span>
              <b>
                median {bp(d?.spreads?.spread_bp_median, 3)} · p90 {bp(d?.spreads?.spread_bp_p90, 3)}
              </b>
            </li>
            <li>
              <span>One sleeve crossing</span>
              <b>
                buy {bp(d?.spreads?.sleeve_buy_bp_median, 3)} · sell {bp(d?.spreads?.sleeve_sell_bp_median, 3)}
              </b>
            </li>
            <li>
              <span>Funding</span>
              <b>
                {d?.funding_rate_pct_last !== null && d?.funding_rate_pct_last !== undefined
                  ? `${d.funding_rate_pct_last}% per ${d.funding_interval_h ?? 4} h exchange · longs pay ≈ ${bp(d.funding_bp_per_day_long)} a day`
                  : "not read yet — the funding series is fetched while the H1 book runs"}
              </b>
            </li>
            <li>
              <span>Samples</span>
              <b>{d?.spreads?.samples ?? 0} book samples</b>
            </li>
          </ul>
        )}
      </div>
      <div className="venue">
        <div className="vh">MCX · {m?.symbol ?? "GOLDM"}</div>
        {m?.error ? (
          <div className="muted">{m.error}</div>
        ) : (
          <ul>
            <li>
              <span>One lot</span>
              <b>₹{(m?.lot_notional_inr ?? 0).toLocaleString("en-IN")} of notional</b>
            </li>
            <li>
              <span>Round trip, charges</span>
              <b>
                ₹{m?.round_trip_fee_inr?.toFixed(0)} · {bp(m?.round_trip_fee_bp)}
              </b>
            </li>
            <li>
              <span>Quoted spread (30 d)</span>
              <b>
                median {bp(m?.spreads?.median_bp)} · p90 {bp(m?.spreads?.p90_bp)}
              </b>
            </li>
            <li>
              <span>Live spread</span>
              <b>{bp(m?.live_spread_bp)}</b>
            </li>
            <li>
              <span>Samples</span>
              <b>{m?.spreads?.samples ?? 0} quotes</b>
            </li>
          </ul>
        )}
      </div>
      <p className="note">
        How the desk fills: entries at the bid / ask (the book walked if an order is bigger than the touch);
        targets as resting limits at their level; stops and time exits at the market, paying the measured
        half-spread ({bp(d?.exit_slip_bp)} Delta, {bp(m?.exit_slip_bp)} MCX). Below 4h the fee alone is
        larger than the edge any of the 353 strategies had — no cheaper execution changes that.
      </p>
      <style jsx>{`
        .costs { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
        .venue { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px;
                 padding: 12px 14px; }
        .vh { font-size: 10.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
              color: var(--text-faint); margin-bottom: 8px; }
        ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
        li { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
        li span { color: var(--text-muted); }
        li b { font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
        .note { grid-column: 1 / -1; margin: 0; font-size: 11.5px; line-height: 1.6; color: var(--text-muted); }
        .muted { font-size: 12px; color: var(--text-muted); }
      `}</style>
    </div>
  );
}
