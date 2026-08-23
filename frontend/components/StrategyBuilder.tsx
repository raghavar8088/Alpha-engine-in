"use client";

/**
 * Multi-leg option strategy builder.
 *
 * The panel is ordered the way the decision is made, not the way the data arrives:
 * pick a shape, see what it pays, see what it risks, then commit. The payoff chart sits
 * above the numbers because the shape of the outcome is the thing you recognise first —
 * a condor and a butterfly are two words and two very different pictures.
 *
 * Every number that can be unbounded says so in words rather than printing the edge of the
 * scan window. "Max loss ₹4,030" on a short strangle would be a lie of the most expensive
 * kind, and it is exactly what a naive payoff calculator prints.
 */

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "./GlassPanel";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import PayoffChart from "./charts/PayoffChart";
import {
  fetchStrategyPresets, analyseStrategy, executeStrategy,
  StrategyPreset, StrategyLeg, StrategyAnalysis,
} from "../lib/api";

const inr = (v: number | null | undefined, dp = 0) =>
  v === null || v === undefined ? "—" :
    `₹${v.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

const OUTLOOK_TONE: Record<string, string> = {
  bullish: "gain", bearish: "loss", volatile: "accent",
  "range-bound": "warn", "mildly bullish": "gain",
};

export default function StrategyBuilder({
  symbol, expiry, atmStrike, strikeStep, lotSize, onExecuted,
}: {
  symbol: string;
  expiry: string;
  atmStrike: number | null;
  strikeStep: number;
  lotSize: number;
  onExecuted?: () => void;
}) {
  const [presets, setPresets] = useState<StrategyPreset[]>([]);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [legs, setLegs] = useState<StrategyLeg[]>([]);
  const [analysis, setAnalysis] = useState<StrategyAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => { fetchStrategyPresets().then((r) => setPresets(r.presets)).catch(() => {}); }, []);

  const applyPreset = (p: StrategyPreset) => {
    if (!atmStrike) return;
    setActivePreset(p.key);
    setResult(null);
    setLegs(p.legs.map((l) => ({
      strike: atmStrike + l.offset * strikeStep,
      option_type: l.type,
      side: l.side,
      lots: l.lots,
    })));
  };

  const analyse = useCallback(async () => {
    if (legs.length === 0 || !expiry) { setAnalysis(null); return; }
    setBusy(true);
    try {
      setAnalysis(await analyseStrategy({ symbol, expiry, legs }));
      setError(null);
    } catch (e) {
      setAnalysis(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [legs, symbol, expiry]);

  // Debounced so dragging a strike through five values is one request, not five.
  useEffect(() => {
    const t = setTimeout(analyse, 300);
    return () => clearTimeout(t);
  }, [analyse]);

  const setLeg = (i: number, patch: Partial<StrategyLeg>) =>
    setLegs((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  const removeLeg = (i: number) => setLegs((ls) => ls.filter((_, idx) => idx !== i));
  const addLeg = () => {
    if (!atmStrike) return;
    setLegs((ls) => [...ls, { strike: atmStrike, option_type: "CE", side: "BUY", lots: 1 }]);
    setActivePreset(null);
  };

  const execute = async () => {
    if (!analysis) return;
    const risk = analysis.unlimited_loss
      ? "\n\nThis structure has UNBOUNDED loss on the upside."
      : analysis.downside_open ? "\n\nThis structure's downside is open beyond the chart." : "";
    if (!window.confirm(
      `Place ${legs.length} leg(s) on ${symbol} ${expiry}?\n\n` +
      `Margin ${inr(analysis.margin.total)} · ` +
      `${analysis.is_debit ? "Debit" : "Credit"} ${inr(Math.abs(analysis.net_premium))}${risk}`)) return;
    setBusy(true);
    try {
      const r = await executeStrategy({ symbol, expiry, legs });
      setResult(r.complete
        ? `All ${r.placed.length} legs filled.`
        : `${r.placed.length} filled, ${r.failed.length} did not. ${r.warning ?? ""}`);
      onExecuted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassPanel title="Strategy builder" note={atmStrike ? `ATM ${atmStrike}` : undefined}>
      <div className="presets">
        {presets.map((p) => (
          <button key={p.key} className={activePreset === p.key ? "pre on" : "pre"}
            onClick={() => applyPreset(p)} title={p.why} disabled={!atmStrike}>
            <span className="pname">{p.name}</span>
            <span className={`pout ${OUTLOOK_TONE[p.outlook] ?? "muted"}`}>{p.outlook}</span>
          </button>
        ))}
      </div>

      {activePreset && (
        <div className="why">{presets.find((p) => p.key === activePreset)?.why}</div>
      )}

      {legs.length === 0 ? (
        <EmptyState title="Pick a structure"
          note="Choose a preset above, or add legs by hand. Everything is priced off the live chain." />
      ) : (
        <>
          <div className="legs">
            {legs.map((l, i) => (
              <div className="leg" key={i}>
                <button className={l.side === "BUY" ? "sd buy" : "sd sell"}
                  onClick={() => setLeg(i, { side: l.side === "BUY" ? "SELL" : "BUY" })}
                  title="Flip the side">{l.side}</button>
                <input type="number" className="qty" value={l.lots} min={1}
                  onChange={(e) => setLeg(i, { lots: Math.max(1, Number(e.target.value)) })} />
                <span className="xl">lot{l.lots > 1 ? "s" : ""}</span>
                <input type="number" className="stk" value={l.strike} step={strikeStep}
                  onChange={(e) => setLeg(i, { strike: Number(e.target.value) })} />
                <button className={l.option_type === "CE" ? "ot ce" : "ot pe"}
                  onClick={() => setLeg(i, { option_type: l.option_type === "CE" ? "PE" : "CE" })}
                  title="Switch call / put">{l.option_type}</button>
                <span className="prem">
                  {analysis?.legs[i]?.premium !== undefined ? inr(analysis.legs[i].premium, 2) : "—"}
                </span>
                <button className="rm" onClick={() => removeLeg(i)} title="Remove leg">✕</button>
              </div>
            ))}
            <button className="addleg" onClick={addLeg}>+ add leg</button>
          </div>

          {busy && !analysis && <Skeleton height={200} />}

          {analysis && (
            <>
              <PayoffChart points={analysis.points} breakevens={analysis.breakevens} height={220} />

              <div className="outcome">
                <Stat label="Max profit"
                  value={analysis.unlimited_profit ? "Unlimited" : inr(analysis.max_profit)}
                  tone="gain" />
                <Stat label="Max loss"
                  value={analysis.unlimited_loss ? "UNLIMITED"
                    : analysis.downside_open ? `${inr(analysis.max_loss)}+`
                    : inr(analysis.max_loss)}
                  tone="loss"
                  warn={analysis.unlimited_loss || analysis.downside_open} />
                <Stat label={analysis.is_debit ? "Net debit" : "Net credit"}
                  value={inr(Math.abs(analysis.net_premium))} />
                <Stat label="Margin blocked" value={inr(analysis.margin.total)}
                  tone={analysis.affordable ? undefined : "loss"} />
                <Stat label="Breakeven"
                  value={analysis.breakevens.length
                    ? analysis.breakevens.map((b) => b.toLocaleString("en-IN")).join(" / ")
                    : "none"} />
                <Stat label="Days to expiry" value={String(analysis.days_to_expiry)} />
              </div>

              <h4>Net Greeks — the whole structure, not the legs</h4>
              <div className="greeks">
                <G label="Delta" value={analysis.greeks.delta} dp={2}
                  hint="Rupees the position moves per 1 point of the underlying" />
                <G label="Gamma" value={analysis.greeks.gamma} dp={4}
                  hint="How fast delta itself changes — the risk that sneaks up" />
                <G label="Theta" value={analysis.greeks.theta} dp={0} perDay
                  hint="Rupees gained or lost per day from time passing alone" />
                <G label="Vega" value={analysis.greeks.vega} dp={0}
                  hint="Rupees per 1 volatility point" />
                <G label="Rho" value={analysis.greeks.rho} dp={1}
                  hint="Rupees per 1% change in interest rates" />
              </div>

              <div className={analysis.unlimited_loss || analysis.downside_open ? "risk bad" : "risk"}>
                {analysis.risk_note}
              </div>

              {analysis.unpriced_legs > 0 && (
                <div className="risk bad">
                  {analysis.unpriced_legs} leg(s) had no solvable implied volatility, so they are
                  excluded from the net Greeks above. The payoff curve is still exact — it needs
                  no volatility assumption — but the Greeks describe only the legs that priced.
                </div>
              )}

              {!analysis.affordable && (
                <div className="risk bad">
                  Margin {inr(analysis.margin.total)} exceeds the {inr(analysis.available_margin)}
                  {" "}available. Placing this will produce rejected legs.
                </div>
              )}

              {result && <div className="result">{result}</div>}
              {error && <div className="risk bad">{error}</div>}

              <button className="exec" disabled={busy || !analysis.affordable} onClick={execute}>
                {busy ? "Working…" : `Place ${legs.length} leg${legs.length > 1 ? "s" : ""} at market`}
              </button>
            </>
          )}
        </>
      )}

      <style jsx>{`
        .presets { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        .pre { display: flex; flex-direction: column; gap: 1px; align-items: flex-start; border: 1px solid var(--panel-border); background: var(--panel); border-radius: 8px; padding: 6px 10px; cursor: pointer; }
        .pre:hover:not(:disabled) { border-color: var(--purple); }
        .pre:disabled { opacity: .5; cursor: default; }
        .pre.on { border-color: var(--purple); background: var(--purple-dim); }
        .pname { font-size: 11.5px; font-weight: 600; color: var(--text); }
        .pout { font-size: 9px; text-transform: uppercase; letter-spacing: .05em; }
        .pout.gain { color: var(--gain); } .pout.loss { color: var(--loss); }
        .pout.accent { color: var(--purple); } .pout.warn { color: var(--warn); }
        .pout.muted { color: var(--text-faint); }
        .why { font-size: 11.5px; color: var(--text-muted); background: var(--canvas-soft); border-radius: 8px; padding: 8px 11px; margin-bottom: 10px; line-height: 1.5; }

        .legs { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
        .leg { display: flex; align-items: center; gap: 6px; }
        .sd { border: 0; border-radius: 6px; padding: 5px 10px; font-size: 11px; font-weight: 700; cursor: pointer; color: #fff; width: 52px; }
        .sd.buy { background: var(--gain); } .sd.sell { background: var(--loss); }
        .qty { width: 46px; padding: 5px 6px; border-radius: 6px; border: 1px solid var(--panel-border); font-size: 12px; background: var(--panel); color: var(--text); text-align: right; }
        .xl { font-size: 10px; color: var(--text-faint); }
        .stk { width: 88px; padding: 5px 8px; border-radius: 6px; border: 1px solid var(--panel-border); font-size: 12px; background: var(--panel); color: var(--text); text-align: right; font-variant-numeric: tabular-nums; }
        .ot { border: 1px solid var(--panel-border); border-radius: 6px; padding: 5px 9px; font-size: 11px; font-weight: 700; cursor: pointer; background: var(--canvas-soft); width: 42px; }
        .ot.ce { color: var(--gain); } .ot.pe { color: var(--loss); }
        .prem { font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; margin-left: auto; }
        .rm { border: 0; background: transparent; color: var(--text-faint); cursor: pointer; font-size: 12px; padding: 4px 6px; }
        .rm:hover { color: var(--loss); }
        .addleg { align-self: flex-start; border: 1px dashed var(--panel-border); background: transparent; border-radius: 7px; padding: 5px 12px; font-size: 11.5px; color: var(--text-muted); cursor: pointer; }
        .addleg:hover { border-color: var(--purple); color: var(--purple); }

        .outcome { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 7px; margin: 12px 0; }
        h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin: 14px 0 7px; }
        .greeks { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 7px; }

        .risk { font-size: 11.5px; line-height: 1.5; color: var(--text-muted); background: var(--canvas-soft); border-radius: 8px; padding: 9px 12px; margin-top: 10px; }
        .risk.bad { color: var(--loss); background: var(--loss-dim); border: 1px solid var(--loss); }
        .result { font-size: 12px; color: var(--gain); background: var(--gain-dim); border: 1px solid var(--gain); border-radius: 8px; padding: 9px 12px; margin-top: 10px; }
        .exec { width: 100%; margin-top: 12px; padding: 12px; border: 0; border-radius: 10px; background: var(--purple); color: #fff; font-weight: 700; font-size: 13.5px; cursor: pointer; }
        .exec:disabled { opacity: .5; cursor: default; }
      `}</style>
    </GlassPanel>
  );
}

function Stat({ label, value, tone, warn }: {
  label: string; value: string; tone?: "gain" | "loss"; warn?: boolean;
}) {
  return (
    <div className={warn ? "st warn" : "st"}>
      <div className="l">{label}</div>
      <div className={`v ${tone ?? ""}`}>{value}</div>
      <style jsx>{`
        .st { border: 1px solid var(--panel-border); border-radius: 9px; padding: 7px 10px; background: var(--panel); }
        .st.warn { border-color: var(--loss); background: var(--loss-dim); }
        .l { font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
        .v { font-size: 14px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
        .v.gain { color: var(--gain); } .v.loss { color: var(--loss); }
      `}</style>
    </div>
  );
}

function G({ label, value, dp, hint, perDay }: {
  label: string; value: number; dp: number; hint: string; perDay?: boolean;
}) {
  return (
    <div className="g" title={hint}>
      <div className="l">{label}</div>
      <div className={`v ${value > 0 ? "gain" : value < 0 ? "loss" : ""}`}>
        {value > 0 ? "+" : ""}{value.toFixed(dp)}{perDay ? <span className="pd">/day</span> : null}
      </div>
      <style jsx>{`
        .g { border: 1px solid var(--panel-border); border-radius: 9px; padding: 7px 10px; background: var(--panel); cursor: help; }
        .l { font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
        .v { font-size: 13.5px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
        .v.gain { color: var(--gain); } .v.loss { color: var(--loss); }
        .pd { font-size: 9px; font-weight: 500; color: var(--text-faint); }
      `}</style>
    </div>
  );
}
