"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import PageHeader from "../../components/PageHeader";
import GlassPanel from "../../components/GlassPanel";
import StatusPill from "../../components/StatusPill";
import ErrorBanner from "../../components/ErrorBanner";
import {
  refreshing,
  ModuleSwitch,
  ModuleSwitches,
  fetchMainControl,
  setMainControlAll,
  setMainControlModule,
  setMainControlOnly,
  resetMainControlCounts,
} from "../../lib/api";

const REFRESH_MS = 30000;

export default function MainControlPage() {
  const [data, setData] = useState<ModuleSwitches | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await fetchMainControl());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Main Control");
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

  const run = async (
    label: string,
    fn: () => Promise<ModuleSwitches>,
    msg: string,
  ) => {
    if (busy) return;
    setBusy(label);
    setNotice(null);
    try {
      setData(await fn());
      setNotice(msg);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change the switch");
    } finally {
      setBusy(null);
    }
  };

  const toggle = (m: ModuleSwitch) =>
    run(
      m.module,
      () => setMainControlModule(m.module, !m.enabled),
      m.enabled
        ? `${m.label} switched OFF. Its loop stops, and its API now refuses anything that would fetch data or write a row. Open positions are left as they are and will not be managed.`
        : `${m.label} switched ON. Its API answers again and the loop resumes on its next tick.`,
    );

  const only = (m: ModuleSwitch) => {
    const n = (data?.total ?? 1) - 1;
    if (
      !window.confirm(
        `Leave ONLY "${m.label}" running and switch OFF the other ${n} modules?\n\n` +
          `Every other desk stops polling and stops trading, and their APIs stop doing work. ` +
          `Open positions everywhere are left unmanaged.`,
      )
    )
      return;
    run(
      "only",
      () => setMainControlOnly(m.module),
      `Only ${m.label} is running now. The other ${n} modules are OFF.`,
    );
  };

  const toggleAll = (enabled: boolean) => {
    const n = data?.total ?? 0;
    if (
      !enabled &&
      !window.confirm(
        `Switch OFF all ${n} modules?\n\nEvery desk stops polling and trading, and every ` +
          `module API stops fetching and writing. Open positions are left unmanaged. ` +
          `Main Control itself stays reachable.`,
      )
    )
      return;
    run(
      "all",
      () => setMainControlAll(enabled),
      enabled ? `All ${n} modules switched ON.` : `All ${n} modules switched OFF.`,
    );
  };

  const rows = data?.modules ?? [];
  const groups = data?.groups ?? [];

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (m) =>
        m.label.toLowerCase().includes(q) ||
        m.module.toLowerCase().includes(q) ||
        (m.api_prefixes ?? []).some((p) => p.toLowerCase().includes(q)),
    );
  }, [rows, filter]);

  const byGroup = useMemo(() => {
    const out: { group: string; items: ModuleSwitch[] }[] = [];
    for (const g of groups) {
      const items = visible.filter((m) => m.group === g);
      if (items.length) out.push({ group: g, items });
    }
    const rest = visible.filter((m) => !groups.includes(m.group ?? ""));
    if (rest.length) out.push({ group: "Other", items: rest });
    return out;
  }, [visible, groups]);

  const blockedTotal = data?.blocked_total ?? 0;

  return (
    <div className="page">
      <PageHeader
        onRefresh={handleRefresh}
        refreshing={isRefreshing}
        crumb="Main Control"
        title="Main Control"
        subtitle={
          <>
            One switch per module, for the whole application. <strong>ON</strong> is exactly
            how the module behaves today. <strong>OFF</strong> stops its background loop{" "}
            <em>and</em> makes its API refuse any request that would call the broker or add or
            change a document — so a module that is off costs nothing and writes nothing.
          </>
        }
        actions={
          <>
            <StatusPill label={`${data?.on ?? 0} on`} tone="gain" />
            <StatusPill
              label={`${data?.off ?? 0} off`}
              tone={(data?.off ?? 0) > 0 ? "loss" : "muted"}
            />
            {blockedTotal > 0 && (
              <StatusPill label={`${blockedTotal} requests blocked`} tone="warn" />
            )}
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
        <strong>Two things OFF does not do.</strong> It does not close anything — whatever a
        module already holds stays exactly as it is, frozen at its last mark and{" "}
        <em>not</em> managed, so an open position will not hit its own stop while the module is
        off. Square off first if that matters. And it does not blank the page: plain reads of
        rows already stored still answer, so an OFF module still shows its last known numbers.{" "}
        <strong>Those numbers are frozen, not live.</strong> Blocking reads too would only cost
        you the ability to look at history you already have.
      </div>

      <GlassPanel
        title="Modules"
        note={`${rows.length} modules · ${data?.api_prefixes_controlled ?? 0} API prefixes`}
      >
        <div className="toolbar">
          <button className="btn sm" onClick={() => toggleAll(true)} disabled={!!busy}>
            All on
          </button>
          <button className="btn sm danger" onClick={() => toggleAll(false)} disabled={!!busy}>
            All off
          </button>
          {blockedTotal > 0 && (
            <button
              className="btn sm"
              onClick={() =>
                run("counts", resetMainControlCounts, "Blocked-request counters cleared.")
              }
              disabled={!!busy}
            >
              Clear counters
            </button>
          )}
          <input
            className="find"
            placeholder="Filter by name, key or /api prefix"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        <div className="tb-note">{data?.note}</div>

        {byGroup.map(({ group, items }) => (
          <div className="group" key={group}>
            <div className="g-head">
              <span className="g-name">{group}</span>
              <span className="g-count">
                {items.filter((m) => m.enabled).length}/{items.length} on
              </span>
            </div>
            <div className="grid">
              {items.map((m) => (
                <div key={m.module} className={`mod ${m.enabled ? "on" : "off"}`}>
                  <div className="m-head">
                    <div className="m-text">
                      <div className="m-label">
                        {m.label}
                        {m.module === "live_trading" && <span className="tag real">REAL MONEY</span>}
                        {m.shared && <span className="tag shared">SHARED</span>}
                        {!m.has_api && <span className="tag loop">LOOP ONLY</span>}
                      </div>
                      <Link href={m.href} className="m-href">
                        {m.href}
                      </Link>
                      {(m.api_prefixes ?? []).length > 0 && (
                        <div className="m-api">{(m.api_prefixes ?? []).join("  ")}</div>
                      )}
                    </div>
                    <div className="m-ctl">
                      <button
                        className={`switch ${m.enabled ? "on" : "off"}`}
                        onClick={() => toggle(m)}
                        disabled={!!busy}
                        aria-label={`Toggle ${m.label}`}
                      >
                        <span className="knob" />
                        <span className="s-label">{m.enabled ? "ON" : "OFF"}</span>
                      </button>
                      <button
                        className="only"
                        onClick={() => only(m)}
                        disabled={!!busy}
                        title={`Run ONLY ${m.label} and switch off everything else`}
                      >
                        only this
                      </button>
                    </div>
                  </div>

                  {m.shared && m.note && <div className="m-note">{m.note}</div>}

                  {!m.enabled && (
                    <div className="m-off">
                      Not polling, not trading, API not fetching or writing.
                      {(m.blocked_requests ?? 0) > 0 && (
                        <>
                          {" "}
                          <strong>{m.blocked_requests} request(s) blocked</strong>
                          {m.last_blocked ? ` — last: ${m.last_blocked}` : ""}.
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}

        {!visible.length && <div className="empty">No module matches “{filter}”.</div>}
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
        .find { flex: 1 1 220px; min-width: 160px; padding: 6px 11px; border-radius: 9px; font-size: 12px;
                border: 1px solid var(--panel-border); background: var(--canvas-soft); color: var(--text); }
        .tb-note { padding: 10px 20px 0; font-size: 11.5px; color: var(--text-faint); line-height: 1.5; }
        .group { padding: 4px 20px 0; }
        .g-head { display: flex; align-items: baseline; gap: 10px; padding: 16px 0 8px; }
        .g-name { font-size: 11px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase;
                  color: var(--text-muted); }
        .g-count { font-size: 10.5px; color: var(--text-faint); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
        .mod { border: 1px solid var(--panel-border); border-radius: 12px; padding: 13px 15px;
               background: var(--canvas-soft); }
        .mod.on { border-color: rgba(14,159,110,.32); background: rgba(14,159,110,.05); }
        .mod.off { border-color: rgba(217,45,63,.24); }
        .m-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
        .m-text { min-width: 0; }
        .m-label { font-size: 12.5px; font-weight: 700; line-height: 1.4; }
        .tag { margin-left: 6px; font-size: 8.5px; font-weight: 800; letter-spacing: .05em;
               padding: 2px 5px; border-radius: 5px; vertical-align: middle; white-space: nowrap; }
        .tag.real { background: var(--loss-dim); color: var(--loss); border: 1px solid rgba(217,45,63,.3); }
        .tag.shared { background: var(--canvas); color: var(--text-muted); border: 1px solid var(--panel-border); }
        .tag.loop { background: var(--canvas); color: var(--text-faint); border: 1px solid var(--panel-border); }
        .m-href { display: inline-block; margin-top: 3px; font-size: 10.5px; color: var(--text-faint);
                  text-decoration: none; }
        .m-href:hover { color: var(--purple); text-decoration: underline; }
        .m-api { margin-top: 4px; font-family: var(--font-mono, ui-monospace), monospace;
                 font-size: 9.5px; color: var(--text-faint); word-break: break-all; }
        .m-ctl { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
        .switch { position: relative; width: 74px; height: 30px; border-radius: 16px; border: none;
                  cursor: pointer; display: flex; align-items: center; padding: 0 4px;
                  transition: background .15s; }
        .switch.on { background: var(--gain); justify-content: flex-end; }
        .switch.off { background: var(--loss); justify-content: flex-start; }
        .switch:disabled { opacity: .6; cursor: default; }
        .knob { width: 22px; height: 22px; border-radius: 50%; background: #fff; }
        .s-label { position: absolute; top: 50%; transform: translateY(-50%); color: #fff;
                   font-weight: 800; font-size: 10px; letter-spacing: .05em; }
        .switch.on .s-label { left: 11px; }
        .switch.off .s-label { right: 9px; }
        .only { padding: 2px 7px; border-radius: 6px; font-size: 9.5px; font-weight: 700; cursor: pointer;
                border: 1px solid var(--panel-border); background: transparent; color: var(--text-faint); }
        .only:hover:not(:disabled) { color: var(--purple); border-color: rgba(125,52,220,.34); }
        .only:disabled { opacity: .5; cursor: default; }
        .m-note { margin-top: 9px; padding-top: 8px; border-top: 1px solid var(--panel-border);
                  font-size: 10.5px; color: var(--text-muted); line-height: 1.45; }
        .m-off { margin-top: 9px; padding-top: 8px; border-top: 1px solid var(--panel-border);
                 font-size: 11px; color: var(--loss); line-height: 1.45; }
        .empty { padding: 26px 20px; text-align: center; font-size: 12.5px; color: var(--text-faint); }
      `}</style>
    </div>
  );
}
