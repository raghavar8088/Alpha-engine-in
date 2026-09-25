"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import {
  refreshing,
  ModuleSwitch,
  ModuleSwitches,
  fetchModuleSwitches,
  setAllModuleSwitches,
  setModuleSwitch,
} from "../../lib/api";

const REFRESH_MS = 30000;

export default function ModulesPage() {
  const [data, setData] = useState<ModuleSwitches | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetchModuleSwitches());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the module switches");
    }
  }, []);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refreshing(() => load());
    } finally {
      setIsRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const toggle = async (m: ModuleSwitch) => {
    if (busy) return;
    setBusy(m.module);
    setNotice(null);
    try {
      setData(await setModuleSwitch(m.module, !m.enabled));
      setNotice(
        !m.enabled
          ? `${m.label} switched ON — it resumes on its next scheduler tick.`
          : `${m.label} switched OFF — no market-data polling, no new paper trades. Any open positions are left as they are and will not be managed.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change the switch");
    } finally {
      setBusy(null);
    }
  };

  const toggleAll = async (enabled: boolean) => {
    if (busy) return;
    const n = data?.modules.length ?? 0;
    if (!enabled && !window.confirm(`Switch OFF all ${n} modules? Market-data polling and paper trading stop everywhere. Open positions are left unmanaged.`)) return;
    setBusy("all");
    setNotice(null);
    try {
      setData(await setAllModuleSwitches(enabled));
      setNotice(enabled ? "Every module switched ON." : "Every module switched OFF.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change the switches");
    } finally {
      setBusy(null);
    }
  };

  const rows = data?.modules ?? [];
  const realMoney = (m: ModuleSwitch) => m.module === "live_trading";

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Modules"
        title="Modules"
        subtitle={
          <>
            One switch per auto-trading desk. Switching a module <strong>OFF</strong> stops its
            scheduler cycle — and because each desk fetches its market data{" "}
            <em>inside</em> that cycle, the polling and the paper trading stop together. Switching
            it back <strong>ON</strong> returns it to exactly what it did before; nothing else
            changes.
          </>
        }
        actions={
          <>
            <StatusPill label={`${data?.on ?? 0} on`} tone="gain" />
            <StatusPill label={`${data?.off ?? 0} off`} tone={(data?.off ?? 0) > 0 ? "loss" : "muted"} />
          </>
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}
      {notice && (
        <div className="notice" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      <div className="warn">
        <strong>A switch does not close anything.</strong> An OFF module stops taking new
        positions and stops polling, but whatever it already holds is left exactly as it is —
        frozen at its last mark and <em>not</em> managed, so an open position will not hit its own
        stop while the module is off. Square off first if that matters.
      </div>

      <GlassPanel title="Desks" note={`${rows.length} modules`}>
        <div className="toolbar">
          <button className="btn sm" onClick={() => toggleAll(true)} disabled={!!busy}>
            All on
          </button>
          <button className="btn sm danger" onClick={() => toggleAll(false)} disabled={!!busy}>
            All off
          </button>
          <span className="tb-note">{data?.note}</span>
        </div>

        <div className="grid">
          {rows.map((m) => (
            <div key={m.module} className={`mod ${m.enabled ? "on" : "off"}`}>
              <div className="m-head">
                <div className="m-text">
                  <div className="m-label">
                    {m.label}
                    {realMoney(m) && <span className="real">REAL MONEY</span>}
                  </div>
                  <Link href={m.href} className="m-href">
                    {m.href}
                  </Link>
                </div>
                <button
                  className={`switch ${m.enabled ? "on" : "off"}`}
                  onClick={() => toggle(m)}
                  disabled={!!busy}
                  aria-label={`Toggle ${m.label}`}
                >
                  <span className="knob" />
                  <span className="s-label">{m.enabled ? "ON" : "OFF"}</span>
                </button>
              </div>
              {!m.enabled && (
                <div className="m-off">
                  Not polling, not trading. Open positions unmanaged.
                </div>
              )}
            </div>
          ))}
        </div>
      </GlassPanel>

      <style jsx>{`
        .page { display: flex; flex-direction: column; gap: 16px; }
        .btn { padding: 7px 14px; border-radius: 9px; font-size: 12.5px; font-weight: 600; cursor: pointer;
               border: 1px solid var(--panel-border); background: var(--panel); color: var(--text); }
        .btn.sm { padding: 5px 11px; font-size: 11.5px; }
        .btn.danger { color: var(--loss); border-color: rgba(217,45,63,.3); }
        .btn:disabled { opacity: .55; cursor: default; }
        .notice { border-radius: 12px; padding: 11px 16px; font-size: 12.5px; cursor: pointer; line-height: 1.5;
                  background: var(--purple-dim); border: 1px solid rgba(125,52,220,.24); color: var(--purple); }
        .warn { border-radius: 12px; padding: 12px 16px; font-size: 12.5px; line-height: 1.55;
                background: var(--canvas-soft); border: 1px solid var(--panel-border); color: var(--text-muted); }
        .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 14px 20px 0; }
        .tb-note { font-size: 11.5px; color: var(--text-faint); line-height: 1.45; flex: 1 1 320px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
                gap: 12px; padding: 16px 20px; }
        .mod { border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px;
               background: var(--canvas-soft); }
        .mod.on { border-color: rgba(14,159,110,.32); background: rgba(14,159,110,.05); }
        .mod.off { opacity: .92; border-color: rgba(217,45,63,.24); }
        .m-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
        .m-text { min-width: 0; }
        .m-label { font-size: 12.5px; font-weight: 700; line-height: 1.35; }
        .real { margin-left: 7px; font-size: 9px; font-weight: 800; letter-spacing: .05em;
                padding: 2px 6px; border-radius: 5px; background: var(--loss-dim); color: var(--loss);
                border: 1px solid rgba(217,45,63,.3); vertical-align: middle; }
        .m-href { display: inline-block; margin-top: 3px; font-size: 10.5px; color: var(--text-faint);
                  text-decoration: none; }
        .m-href:hover { color: var(--purple); text-decoration: underline; }
        .switch { position: relative; width: 74px; height: 30px; border-radius: 16px; border: none;
                  cursor: pointer; display: flex; align-items: center; padding: 0 4px; flex-shrink: 0;
                  transition: background .15s; }
        .switch.on { background: var(--gain); justify-content: flex-end; }
        .switch.off { background: var(--loss); justify-content: flex-start; }
        .switch:disabled { opacity: .6; cursor: default; }
        .knob { width: 22px; height: 22px; border-radius: 50%; background: #fff; }
        .s-label { position: absolute; top: 50%; transform: translateY(-50%); color: #fff;
                   font-weight: 800; font-size: 10px; letter-spacing: .05em; }
        .switch.on .s-label { left: 11px; }
        .switch.off .s-label { right: 9px; }
        .m-off { margin-top: 9px; padding-top: 8px; border-top: 1px solid var(--panel-border);
                 font-size: 11px; color: var(--loss); }
      `}</style>
    </div>
  );
}
