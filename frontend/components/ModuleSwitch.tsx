"use client";

// The module's ON/OFF switch, in the header of every module page.
//
// It finds its module(s) from the URL - each module in Main Control names the pages it lives
// on - so no page has to wire anything up. One module: a state label and a switch. A page that
// hosts several (Intraday Stocks has four): a summary button that opens a list, one switch each.
//
// ON is how the module always ran. OFF stops its new entries at once; a module still holding
// positions keeps managing them to their exits and shows "Stopping", then pauses by itself
// once flat. The server decides all of that; this only asks, and shows what it says.

import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ModuleStatusMap,
  ModuleStatusRow,
  currentModuleStatus,
  loadModuleStatus,
  modulesForPath,
  offConsequence,
  stateText,
  subscribeModuleStatus,
  toggleModule,
} from "../lib/moduleStatus";

const POLL_MS = 30_000;

export default function ModuleSwitch() {
  const pathname = usePathname() || "";
  const [map, setMap] = useState<ModuleStatusMap | null>(() => currentModuleStatus());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  // Which edge the list hangs from: the header wraps its actions to the LEFT on narrow or
  // long-subtitle pages, and to the right on others, so it is decided when it opens.
  const [alignRight, setAlignRight] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const off = subscribeModuleStatus(setMap);
    loadModuleStatus().catch(() => undefined);
    const id = setInterval(() => {
      if (typeof document === "undefined" || !document.hidden) loadModuleStatus().catch(() => undefined);
    }, POLL_MS);
    return () => {
      off();
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const keys = useMemo(() => (map ? modulesForPath(map, pathname) : []), [map, pathname]);
  if (!map || keys.length === 0) return null;

  const flip = async (key: string) => {
    const m = map.modules[key];
    if (!m || busy) return;
    if (m.enabled) {
      const lines = [
        `Switch OFF "${m.label}"?`,
        "",
        offConsequence(m, map.semantics),
        "",
        "Its history stays visible, and you can switch it back on at any time.",
      ];
      if (m.real_money) lines.splice(1, 0, "", "This is the REAL-MONEY desk.");
      if (!window.confirm(lines.join("\n"))) return;
    }
    setBusy(key);
    setError(null);
    try {
      await toggleModule(key, !m.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the switch");
    } finally {
      setBusy(null);
    }
  };

  const rows = keys.map((k) => ({ key: k, m: map.modules[k] }));
  const single = rows.length === 1 ? rows[0] : null;

  return (
    <div className="msw" ref={boxRef}>
      {single ? (
        <Row k={single.key} m={single.m} states={map.states} busy={busy} onFlip={flip} compact />
      ) : (
        <>
          <button
            className={`sum ${summaryTone(rows.map((r) => r.m))}`}
            onClick={() => {
              const r = boxRef.current?.getBoundingClientRect();
              if (r) setAlignRight(r.left + 380 > window.innerWidth - 16);
              setOpen((v) => !v);
            }}
            aria-expanded={open}
            aria-haspopup="true"
            title="Switch this page's modules on or off"
          >
            <span className="dot" />
            {summaryText(rows.map((r) => r.m))}
            <span className="caret">▾</span>
          </button>
          {open && (
            <div className={`pop ${alignRight ? "right" : "left"}`} role="dialog" aria-label="Modules on this page">
              <div className="pop-head">
                Modules on this page
                <a href="/main-control" className="all">
                  Main Control →
                </a>
              </div>
              {rows.map(({ key, m }) => (
                <Row key={key} k={key} m={m} states={map.states} busy={busy} onFlip={flip} />
              ))}
              <div className="pop-note">
                {map.semantics === "drain"
                  ? "OFF stops new entries; open positions are managed to their exits, then the module pauses."
                  : "OFF pauses a module at once; open positions are not managed while off."}
              </div>
            </div>
          )}
        </>
      )}
      {error && (
        <div className="err" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      <style jsx>{`
        .msw { position: relative; display: inline-flex; flex-direction: column; align-items: flex-start; gap: 4px; }
        .sum {
          display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px; border-radius: 9px;
          font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap;
          border: 1px solid var(--panel-border); background: var(--panel); color: var(--text);
        }
        .sum .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
        .sum.active .dot { background: var(--gain); }
        .sum.stopping .dot { background: var(--warn); }
        .sum.paused .dot { background: var(--loss); }
        .sum.mixed .dot { background: var(--warn); }
        .caret { font-size: 10px; color: var(--text-faint); }
        .pop {
          position: absolute; top: calc(100% + 6px); z-index: 40;
          width: min(380px, calc(100vw - 32px)); padding: 6px 0;
          border-radius: 12px; border: 1px solid var(--panel-border); background: var(--panel);
          box-shadow: var(--shadow-md);
        }
        .pop.left { left: 0; }
        .pop.right { right: 0; }
        .pop-head {
          display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
          padding: 8px 14px 6px; font-size: 10.5px; font-weight: 800; letter-spacing: .06em;
          text-transform: uppercase; color: var(--text-muted);
        }
        .all { font-size: 11px; font-weight: 600; letter-spacing: 0; text-transform: none;
               color: var(--brand); text-decoration: none; }
        .all:hover { text-decoration: underline; }
        .pop-note { padding: 8px 14px 6px; font-size: 11px; line-height: 1.45; color: var(--text-faint);
                    border-top: 1px solid var(--panel-border); margin-top: 4px; }
        .err { max-width: 320px; font-size: 11px; color: var(--loss); cursor: pointer; text-align: right; }
      `}</style>
    </div>
  );
}

function Row({
  k,
  m,
  states,
  busy,
  onFlip,
  compact = false,
}: {
  k: string;
  m: ModuleStatusRow;
  states: Record<string, string>;
  busy: string | null;
  onFlip: (key: string) => void;
  compact?: boolean;
}) {
  const label = stateText(m, states);
  return (
    <div className={`row ${compact ? "compact" : ""}`}>
      {!compact && (
        <div className="name">
          {m.label}
          {m.real_money && <span className="real">REAL MONEY</span>}
        </div>
      )}
      <span className={`state ${m.state}`} title={label}>
        <span className="dot" />
        {label}
      </span>
      <button
        className={`switch ${m.enabled ? "on" : "off"}`}
        role="switch"
        aria-checked={m.enabled}
        aria-label={`${m.label}: ${m.enabled ? "on" : "off"}. Click to switch ${m.enabled ? "off" : "on"}.`}
        title={m.enabled ? `Switch ${m.label} OFF` : `Switch ${m.label} ON`}
        disabled={!!busy}
        onClick={() => onFlip(k)}
      >
        <span className="knob" />
        <span className="s-label">{busy === k ? "…" : m.enabled ? "ON" : "OFF"}</span>
      </button>
      <style jsx>{`
        .row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 10px;
               padding: 8px 14px; }
        .row.compact { display: inline-flex; padding: 0; gap: 8px; }
        .name { min-width: 0; font-size: 12.5px; font-weight: 700; color: var(--text); line-height: 1.35; }
        .real { margin-left: 6px; font-size: 8.5px; font-weight: 800; letter-spacing: .05em; padding: 2px 5px;
                border-radius: 5px; background: var(--loss-dim); color: var(--loss); vertical-align: middle; }
        .state {
          display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 100px;
          font-size: 11.5px; font-weight: 600; white-space: nowrap; max-width: 280px; overflow: hidden;
          text-overflow: ellipsis; border: 1px solid var(--panel-border); background: var(--canvas-soft);
          color: var(--text-muted);
        }
        .state .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: currentColor; }
        .state.active { color: var(--gain); background: var(--gain-dim); border-color: rgba(var(--gain-rgb), .28); }
        .state.stopping { color: var(--warn); background: var(--warn-dim); border-color: rgba(var(--warn-rgb), .32); }
        .state.paused { color: var(--loss); background: var(--loss-dim); border-color: rgba(var(--loss-rgb), .26); }
        .switch {
          position: relative; width: 62px; height: 26px; border-radius: 14px; border: none; cursor: pointer;
          display: inline-flex; align-items: center; padding: 0 3px; flex-shrink: 0; transition: background .15s;
        }
        .switch.on { background: var(--gain-solid); justify-content: flex-end; }
        .switch.off { background: var(--loss-solid); justify-content: flex-start; }
        .switch:disabled { opacity: .6; cursor: default; }
        .switch:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
        .knob { width: 20px; height: 20px; border-radius: 50%; background: var(--on-brand); }
        .s-label { position: absolute; top: 50%; transform: translateY(-50%); color: var(--on-brand);
                   font-weight: 800; font-size: 9.5px; letter-spacing: .05em; }
        .switch.on .s-label { left: 9px; }
        .switch.off .s-label { right: 8px; }
        @media (max-width: 560px) {
          .state { max-width: 210px; white-space: normal; line-height: 1.3; border-radius: 10px; }
        }
      `}</style>
    </div>
  );
}

function summaryTone(ms: ModuleStatusRow[]): string {
  const states = new Set(ms.map((m) => m.state));
  if (states.size === 1) return [...states][0];
  return "mixed";
}

function summaryText(ms: ModuleStatusRow[]): string {
  const n = (s: string) => ms.filter((m) => m.state === s).length;
  const parts: string[] = [];
  if (n("active")) parts.push(`${n("active")} active`);
  if (n("stopping")) parts.push(`${n("stopping")} stopping`);
  if (n("paused")) parts.push(`${n("paused")} paused`);
  return `${ms.length} modules · ${parts.join(" · ")}`;
}
