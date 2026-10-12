"use client";

import { useCallback, useEffect, useState } from "react";
import GlassPanel from "../../components/GlassPanel";
import {
  fetchIIRisk,
  freshII,
  resetIIHalt,
  saveIIRisk,
  setIIEmergency,
  type IIAccount,
  type IIDayState,
  type IIRiskConfig,
} from "../../lib/indexIntradayApi";
import { dash, inr } from "./ui";

type Field = {
  key: keyof IIRiskConfig;
  label: string;
  unit: string;
  help: string;
  kind: "number" | "time";
  step?: number;
};

const FIELDS: Field[] = [
  { key: "capital", label: "Virtual capital", unit: "₹", kind: "number", step: 100000, help: "The paper account's starting money." },
  {
    key: "risk_per_trade_pct",
    label: "Risk per trade",
    unit: "% of equity",
    kind: "number",
    step: 0.1,
    help: "The loss to a trade's initial stop. The position size follows from it; a strategy with no stop is sized as if its stop were half the day's ATR away (volatility sizing).",
  },
  {
    key: "max_position_pct",
    label: "Largest position",
    unit: "% of equity",
    kind: "number",
    step: 5,
    help: "A cap on any one position's value. At most 100 — the cash market has no leverage here.",
  },
  {
    key: "max_daily_loss_pct",
    label: "Daily loss limit",
    unit: "% of capital",
    kind: "number",
    step: 0.1,
    help: "When the day's closed plus open losses reach it, no new entry is taken that day.",
  },
  { key: "max_trades_per_day", label: "Entries a day", unit: "trades", kind: "number", step: 1, help: "No new entry after this many in a day." },
  { key: "max_concurrent", label: "Open at once", unit: "positions", kind: "number", step: 1, help: "No new entry while this many are open." },
  {
    key: "max_drawdown_pct",
    label: "Drawdown halt",
    unit: "% from peak",
    kind: "number",
    step: 0.5,
    help: "If equity falls this far below its peak, entries stop until you reset the halt.",
  },
  { key: "loss_streak", label: "Losing streak", unit: "trades", kind: "number", step: 1, help: "After this many losing trades in a row…" },
  { key: "streak_cooldown_min", label: "…pause entries for", unit: "minutes", kind: "number", step: 5, help: "…no new entry for this long." },
  {
    key: "cooldown_after_exit_min",
    label: "Cooldown after an exit",
    unit: "minutes",
    kind: "number",
    step: 5,
    help: "After any exit, that strategy waits this long before its next entry (0 = off).",
  },
  { key: "entry_from", label: "Entries from", unit: "IST", kind: "time", help: "No entry before this time." },
  {
    key: "entry_until",
    label: "Entries until",
    unit: "IST",
    kind: "time",
    help: "No entry after this time (the last-half-hour momentum family may enter until 14:45).",
  },
  {
    key: "square_off",
    label: "Square-off",
    unit: "IST",
    kind: "time",
    help: "Everything still open is closed at this minute — 15:12 at the latest, the research's and before Angel's 15:15 auto square-off.",
  },
];

/** Risk Management: the limits every paper entry must pass, the emergency stop, the halt reset. */
export default function RiskPanel() {
  const [cfg, setCfg] = useState<IIRiskConfig | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [day, setDay] = useState<IIDayState | null>(null);
  const [acct, setAcct] = useState<IIAccount | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetchIIRisk();
      setCfg(r.config);
      setDay(r.day);
      setAcct(r.account);
      setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(r.config[f.key])])));
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "Could not load the risk settings.", bad: true });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dirty = cfg ? FIELDS.some((f) => draft[f.key] !== String(cfg[f.key])) : false;

  const save = async () => {
    const values: Partial<IIRiskConfig> = {};
    for (const f of FIELDS) {
      const raw = (draft[f.key] ?? "").trim();
      if (f.kind === "number") {
        const n = Number(raw);
        if (raw === "" || Number.isNaN(n)) {
          setMsg({ text: `${f.label}: enter a number.`, bad: true });
          return;
        }
        (values as Record<string, number>)[f.key] = n;
      } else {
        (values as Record<string, string>)[f.key] = raw;
      }
    }
    setBusy("save");
    setMsg(null);
    try {
      await saveIIRisk(values);
      setMsg({ text: "Saved. The engine applies the new limits from its next minute." });
      await freshII(load);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "Not saved.", bad: true });
    } finally {
      setBusy(null);
    }
  };

  const emergency = async (on: boolean) => {
    if (on && !window.confirm("Emergency stop: close every open paper position at the market now and block all entries?")) return;
    setBusy("emergency");
    setMsg(null);
    try {
      const r = await setIIEmergency(on);
      setMsg({
        text: on
          ? `Emergency stop ON — ${r.closed ?? 0} position${r.closed === 1 ? "" : "s"} closed; entries blocked until you switch it off.`
          : "Emergency stop off — entries resume inside the window and limits.",
      });
      await freshII(load);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "Did not change.", bad: true });
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("reset");
    setMsg(null);
    try {
      await resetIIHalt();
      setMsg({ text: "Halt cleared — the peak is reset to today's equity." });
      await freshII(load);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "Not reset.", bad: true });
    } finally {
      setBusy(null);
    }
  };

  if (!cfg || !day) return <div className="muted pad">{msg?.text ?? "Loading the risk settings…"}</div>;

  const dailyLimit = (cfg.max_daily_loss_pct / 100) * cfg.capital;
  const ddFloor = day.peak_equity * (1 - cfg.max_drawdown_pct / 100);

  return (
    <div className="stack">
      <div className={`estop ${cfg.emergency_stop ? "on" : ""}`}>
        <div>
          <div className="etitle">Emergency stop {cfg.emergency_stop ? "is ON" : "is off"}</div>
          <div className="esub">
            {cfg.emergency_stop
              ? "Every entry is blocked. Positions were closed at the market when it was switched on."
              : "Switching it on closes every open paper position at the market at once and blocks every new entry until you switch it off."}
          </div>
        </div>
        <button
          className={`btn ${cfg.emergency_stop ? "" : "danger strongbtn"}`}
          disabled={!!busy}
          onClick={() => emergency(!cfg.emergency_stop)}
        >
          {busy === "emergency" ? "…" : cfg.emergency_stop ? "Switch off" : "Emergency stop"}
        </button>
      </div>

      {msg && <div className={msg.bad ? "warnbox" : "note"}>{msg.text}</div>}

      <div className="stats">
        <div className="stat">
          <div className="k">Today ({day.day})</div>
          <div className={`v ${day.realized > 0 ? "gain" : day.realized < 0 ? "loss" : ""}`}>{inr(day.realized)}</div>
          <div className="s">
            closed P&amp;L · limit {inr(-dailyLimit)} including open losses
          </div>
        </div>
        <div className="stat">
          <div className="k">Entries today</div>
          <div className="v">
            {day.trades} / {cfg.max_trades_per_day}
          </div>
          <div className="s">{acct?.open_positions ?? 0} open of {cfg.max_concurrent} allowed</div>
        </div>
        <div className="stat">
          <div className="k">Losing streak</div>
          <div className={`v ${day.paused_until ? "warn" : ""}`}>{day.loss_streak}</div>
          <div className="s">{day.paused_until ? `entries paused until ${day.paused_until}` : `pause after ${cfg.loss_streak} in a row`}</div>
        </div>
        <div className="stat">
          <div className="k">Drawdown</div>
          <div className={`v ${day.halted ? "loss" : ""}`}>{day.halted ? "HALTED" : "within limit"}</div>
          <div className="s">
            peak {inr(day.peak_equity, false)} · halts below {inr(ddFloor, false)} · equity {acct ? inr(acct.equity, false) : dash}
          </div>
          {day.halted && (
            <button className="btn sm" disabled={!!busy} onClick={reset}>
              Reset the halt
            </button>
          )}
        </div>
      </div>

      <GlassPanel title="Limits" note="every new entry must pass all of them; nothing here ever blocks an exit">
        <div className="form">
          {FIELDS.map((f) => (
            <label key={f.key} className="field">
              <span className="fl">
                {f.label} <span className="faint">({f.unit})</span>
              </span>
              <input
                type={f.kind === "time" ? "text" : "number"}
                inputMode={f.kind === "time" ? "numeric" : "decimal"}
                step={f.step}
                value={draft[f.key] ?? ""}
                placeholder={f.kind === "time" ? "HH:MM" : ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              />
              <span className="fh">{f.help}</span>
            </label>
          ))}
        </div>
        <div className="row">
          <button className="btn primary" disabled={!dirty || !!busy} onClick={save}>
            {busy === "save" ? "Saving…" : "Save limits"}
          </button>
          <button
            className="btn"
            disabled={!dirty || !!busy}
            onClick={() => setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(cfg[f.key])])))}
          >
            Discard changes
          </button>
        </div>
        <p className="foot">
          Exits always run: a stop, target, trail, signal or time exit, the square-off and the emergency stop are never
          refused by a limit. Main Control&rsquo;s switch for this module also gates new entries only.
        </p>
      </GlassPanel>
    </div>
  );
}
