"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchGoldH1, type GoldH1Report } from "../../lib/api";

const NAMES: Record<string, string> = {
  donchian_fast: "Donchian 20",
  donchian_slow: "Donchian 55",
  keltner_break: "Keltner breakout",
  prior_session_break: "Prior-session break",
  round_number_break: "Round-number break",
  pivot_break: "Pivot R1/S1",
  hh_hl_shift: "HH/HL shift",
  atr_thrust: "ATR thrust",
  ema_ribbon: "EMA ribbon",
};

const num = (v: number | null | undefined, d = 2, sign = true) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${sign && v > 0 ? "+" : ""}${v.toFixed(d)}`;

/** H1 — the one experiment the Gold Desk research left standing.
 *
 * The research replayed all 353 strategies on six gold histories; nothing below 4h earned its
 * costs and 39 of 40 daily templates lost to holding gold. The nine breakout / trend templates at
 * 4h were the only effect with the same sign everywhere — found in that data, so only trades taken
 * after the rule was stored can confirm it. This panel shows the stored rule, how far the test
 * has run, and the verdict the rule gives — nothing else. */
export default function GoldH1Panel() {
  const [r, setR] = useState<GoldH1Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setR(await fetchGoldH1());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load H1");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, [load]);

  if (err) return <div className="h1 h1-err">H1 unavailable: {err}</div>;
  if (!r) return null;
  const d = r.rule.decision;
  const tone =
    r.status === "GO" ? "go" : r.status === "NO-GO" || r.status === "FUTILE" ? "stop" : "wait";

  return (
    <div className="h1">
      <div className="h1-head">
        <span className={`pill ${tone}`}>{r.status}</span>
        <b>H1 · {r.rule.title}</b>
      </div>
      <p className="why">
        {r.rule.hypothesis} Judged at week {d.final_week}: <b>GO</b> only if {d.go}; a single
        futility look at week {d.futility_week} stops the test if {d.futility.replace(/^stop at week \d+ if /, "")}.
        A GO earns the Commodity Lab gate and an incubation on real fills — not money.
      </p>
      <div className="grid">
        <div className="cell">
          <div className="lab">Progress</div>
          <div className="val">
            week {r.weeks ?? 0} / {d.final_week}
          </div>
          <div className="bar">
            <span style={{ width: `${r.progress_pct ?? 0}%` }} />
          </div>
        </div>
        <div className="cell">
          <div className="lab">Trades closed</div>
          <div className="val">{r.trades ?? 0}</div>
          <div className="sub">
            {r.open_positions ?? 0} open · ≥ {d.min_trades_for_any_verdict} needed for a GO
          </div>
        </div>
        <div className="cell">
          <div className="lab">Pooled net</div>
          <div className={`val ${(r.net_bp_mean ?? 0) > 0 ? "gain" : (r.net_bp_mean ?? 0) < 0 ? "loss" : ""}`}>
            {num(r.net_bp_mean)} bp
          </div>
          <div className="sub">a trade, after fees, spread and funding</div>
        </div>
        <div className="cell">
          <div className="lab">Weekly t</div>
          <div className="val">{num(r.weekly_t)}</div>
          <div className="sub">GO needs ≥ 2.00</div>
        </div>
        <div className="cell">
          <div className="lab">Alpha t vs XAUT</div>
          <div className="val">{num(r.alpha_t)}</div>
          <div className="sub">
            beta {num(r.beta, 2, false)} · {r.xaut_weeks_measured ?? 0} weeks priced · GO needs ≥ 2.00
          </div>
        </div>
      </div>
      <div className="tmpl">
        {r.rule.rule.templates.map((t) => (
          <span key={t}>{NAMES[t] ?? t}</span>
        ))}
        <span className="muted">
          · {r.rule.rule.timeframe} · {r.rule.rule.symbol} · one ${(r.rule.rule.capital_usd / 9).toFixed(0)} sleeve
          each at 1x
        </span>
      </div>
      <p className="power">Power, stated before the first trade: {r.rule.power}.</p>
      <div className="foot">
        {r.preregistered
          ? `Pre-registered ${r.stored_at ? new Date(r.stored_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : ""} · fingerprint ${r.fingerprint}`
          : "Not stored yet — the test starts when the Delta book is switched on, and no H1 position opens before its rule is stored."}
        {r.preregistered && r.code_matches_stored === false
          ? " · the code's rule differs from the stored one; the STORED rule governs"
          : ""}
        {r.why ? ` · ${r.why}` : ""}
      </div>
      <style jsx>{`
        .h1 { display: flex; flex-direction: column; gap: 10px; }
        .h1-err { font-size: 12px; color: var(--text-faint); }
        .h1-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13.5px; }
        .why, .power { margin: 0; font-size: 12px; line-height: 1.6; color: var(--text-muted); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .cell { background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px;
                padding: 10px 12px; }
        .lab { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
               color: var(--text-faint); }
        .val { margin-top: 6px; font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
        .sub { margin-top: 3px; font-size: 11px; color: var(--text-muted); }
        .bar { height: 4px; margin-top: 8px; border-radius: 2px; background: var(--panel-border); overflow: hidden; }
        .bar span { display: block; height: 100%; background: var(--text-muted); }
        .tmpl { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11.5px; }
        .tmpl span { padding: 3px 8px; border-radius: 999px; background: var(--canvas-soft);
                     border: 1px solid var(--panel-border); }
        .tmpl .muted { background: none; border: none; color: var(--text-muted); padding: 3px 0; }
        .foot { font-size: 10.5px; color: var(--text-faint); }
        .pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 10.5px; font-weight: 800;
                letter-spacing: 0.04em; background: var(--canvas-soft); border: 1px solid var(--panel-border); }
        .pill.go { color: var(--gain); background: var(--gain-dim); }
        .pill.stop { color: var(--loss); background: var(--loss-dim); }
        .pill.wait { color: var(--warn); background: var(--warn-dim); }
        .gain { color: var(--gain); }
        .loss { color: var(--loss); }
      `}</style>
    </div>
  );
}
