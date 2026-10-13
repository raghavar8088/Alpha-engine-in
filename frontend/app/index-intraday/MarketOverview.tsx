"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import { fetchIIOverview, type IIOverview, type IIResearch } from "../../lib/indexIntradayApi";
import { dash, inr, num, pct, px, tone } from "./ui";

const REFRESH_MS = 15000;

/** Market Overview: the indexes live, what trading each one in the cash market really costs, and
 * how far back its one-minute history goes. */
export default function MarketOverview({ research }: { research: IIResearch | null }) {
  const [ov, setOv] = useState<IIOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOv(await fetchIIOverview());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load the market overview.");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (!ov) return <div className="muted pad">{err ?? "Loading the market…"}</div>;

  const indexes = ov.instruments.filter((i) => i.kind === "index");
  const etfs = ov.instruments.filter((i) => i.kind === "etf");
  const vix = ov.instruments.find((i) => i.kind === "vix");
  const f = ov.feed;
  const starts = research?.history_starts ?? {};

  return (
    <div className="stack">
      {err && <div className="warnbox">Showing the last good read — {err}</div>}

      <div className="stats">
        <div className="stat">
          <div className="k">Session</div>
          <div className={`v ${ov.session === "open" ? "gain" : ""}`}>{ov.session}</div>
          <div className="s">
            entries {ov.entry_window} · square-off {ov.square_off}
          </div>
        </div>
        <div className="stat">
          <div className="k">India VIX</div>
          <div className="v">{px(vix?.ltp)}</div>
          <div className={`s ${tone(vix?.change_pct)}`}>
            {pct(vix?.change_pct)} on the day · prev {px(vix?.prev_close)}
          </div>
        </div>
        <div className="stat">
          <div className="k">Live feed (Angel One)</div>
          <div className={`v ${f.connected ? "gain" : "loss"}`}>{f.connected ? "connected" : "not connected"}</div>
          <div className="s">
            {f.ticking.length} of {ov.instruments.length} instruments ticking
            {f.seconds_since_message !== null ? ` · last message ${f.seconds_since_message}s ago` : ""}
            {f.reconnects ? ` · ${f.reconnects} reconnects` : ""}
          </div>
        </div>
        <div className="stat">
          <div className="k">Mode</div>
          <div className="v">Paper only</div>
          <div className="s">no order reaches a broker or an exchange from this module</div>
        </div>
      </div>
      {f.last_error && <div className="warnbox">Feed: {f.last_error}</div>}
      {!f.connected && (
        <div className="note">
          The feed connects for the session (09:05–15:36 IST on trading days). Outside it, the prices below are the
          last ones it saw, or blank after a restart.
        </div>
      )}

      <GlassPanel title="Indexes and how each would be traded" note="an index cannot be bought — its ETF can">
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">Index</th>
                <th>Last</th>
                <th>Day</th>
                <th>Low – High</th>
                <th className="l">Cash route</th>
                <th>Charges</th>
                <th>Spread</th>
                <th>All-in round trip</th>
                <th>ETF minute value</th>
                <th>Largest paper order</th>
                <th className="l">Intraday</th>
                <th>1-minute history from</th>
              </tr>
            </thead>
            <tbody>
              {indexes.map((r) => (
                <tr key={r.symbol}>
                  <td className="l strong">
                    {r.label}
                    <span className="faint"> · {r.exchange}</span>
                  </td>
                  <td>{px(r.ltp)}</td>
                  <td className={tone(r.change_pct)}>{pct(r.change_pct)}</td>
                  <td className="muted">
                    {px(r.low)} – {px(r.high)}
                  </td>
                  <td className="l">{r.etf ?? <span className="warn">no ETF — simulation only</span>}</td>
                  <td>{r.fee_rt_bp == null ? "—" : `${(r.fee_rt_bp / 100).toFixed(3)}%`}</td>
                  <td>{r.slip_bp == null ? "—" : `${(r.slip_bp / 100).toFixed(3)}% a side`}</td>
                  <td className="strong">{r.all_in_rt_bp == null ? "—" : `${(r.all_in_rt_bp / 100).toFixed(3)}%`}</td>
                  <td>{r.etf_minute_value_lakh !== null && r.etf_minute_value_lakh !== undefined ? `₹${num(r.etf_minute_value_lakh, 1)} L` : dash}</td>
                  <td>{r.etf ? inr(r.etf_order_cap, false) : dash}</td>
                  <td className="l">
                    {r.tradable ? (
                      <span className="chip good">tradable</span>
                    ) : (
                      <span className="chip bad">{r.etf ? "too thin" : "not tradable"}</span>
                    )}
                  </td>
                  <td className="muted">{starts[r.symbol] ?? dash}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="foot">
          <strong>Charges</strong> are Angel One&rsquo;s intraday rate card on a ₹10 lakh round trip (STT on the sell,
          stamp duty on the buy, exchange and SEBI fees, GST). <strong>Spread</strong> is each ETF&rsquo;s measured
          effective half-spread from its own one-minute prices, paid on the way in and again on the way out.{" "}
          <strong>Minute value</strong> is the median rupee value an ETF trades in a minute (2024–26); the paper engine
          never sends an ETF order above a quarter of it. Only NIFTYBEES, BANKBEES and JUNIORBEES trade enough to
          take an intraday position of size; the other ETFs print so rarely that most of their minutes are empty.
          MIDCAP SELECT&rsquo;s history begins in 2022 and BANKEX&rsquo;s in 2023, after the research&rsquo;s
          2016–21 selection period.
        </p>
      </GlassPanel>

      <GlassPanel title="Tracking ETFs" note="the cash instruments">
        <div className="tscroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="l">ETF</th>
                <th className="l">Tracks</th>
                <th>Last</th>
                <th>Day</th>
                <th>Low – High</th>
                <th>Last tick</th>
              </tr>
            </thead>
            <tbody>
              {etfs.map((r) => (
                <tr key={r.symbol}>
                  <td className="l strong">{r.symbol}</td>
                  <td className="l muted">{r.tracks}</td>
                  <td>{px(r.ltp)}</td>
                  <td className={tone(r.change_pct)}>{pct(r.change_pct)}</td>
                  <td className="muted">
                    {px(r.low)} – {px(r.high)}
                  </td>
                  <td className="muted">{r.ticked_s_ago !== null ? `${r.ticked_s_ago}s ago` : dash}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassPanel>
    </div>
  );
}
